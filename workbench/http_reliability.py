"""Bounded local HTTP admission and total request-body deadlines."""
from __future__ import annotations

import json
import socket
import threading
import time

from .http_bind import ExclusiveThreadingHTTPServer


class RequestBodyTimeout(TimeoutError):
    pass


def finish_rejected_response(handler, *, timeout: float = .2, max_bytes: int = 1048576) -> None:
    """Deliver a rejection before bounded cleanup of unread TCP input.

    Closing immediately while a slow sender is still writing can reset the
    connection and discard its HTTP response on Windows. Send FIN first so
    the client can read the response, then drain without parsing or dispatch.
    The byte cap covers the largest 512 KiB V0 request plus a bounded excess;
    each receive buffer remains 64 KiB and the total cleanup deadline is fixed.
    """
    connection = handler.connection
    handler.close_connection = True
    previous_timeout = connection.gettimeout()
    try:
        handler.wfile.flush()
        connection.shutdown(socket.SHUT_WR)
        deadline = time.monotonic() + timeout
        drained = 0
        while drained < max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            connection.settimeout(remaining)
            chunk = connection.recv(min(65536, max_bytes - drained))
            if not chunk:
                break
            drained += len(chunk)
    except OSError:
        # A disconnected client never turns a rejected operation into a retry.
        pass
    finally:
        try:
            connection.settimeout(previous_timeout)
        except OSError:
            pass


class WorkbenchHTTPServer(ExclusiveThreadingHTTPServer):
    """Refuse excess connections instead of growing an unbounded thread pool."""

    def __init__(self, address, handler, *, max_connections=32, connection_timeout=10):
        if max_connections < 1 or connection_timeout <= 0:
            raise ValueError('HTTP limits must be positive')
        self.connection_timeout = float(connection_timeout)
        self._slots = threading.BoundedSemaphore(max_connections)
        self._count_lock = threading.Lock()
        self.active_requests = 0
        self.rejected_requests = 0
        super().__init__(address, handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.connection_timeout)
        return request, address

    def process_request(self, request, address):
        if not self._slots.acquire(blocking=False):
            with self._count_lock:
                self.rejected_requests += 1
            try:
                # Closing a Windows socket with unread input can erase the
                # useful 503 with a TCP reset. Drain only already-arriving
                # bounded input; admission still never dispatches the request.
                drain_until = time.monotonic() + .05
                drained = 0
                while drained < 1024 * 1024:
                    remaining = drain_until - time.monotonic()
                    if remaining <= 0:
                        break
                    request.settimeout(remaining)
                    try:
                        chunk = request.recv(min(65536, 1024 * 1024 - drained))
                    except OSError:
                        break
                    if not chunk:
                        break
                    drained += len(chunk)
                    if chunk.endswith(b'\r\n\r\n'):
                        break
                body = json.dumps({'error': 'server_busy', 'message': '工作台连接繁忙，请稍后读取当前记录再决定。',
                                   'automatic_replay': False}, ensure_ascii=False).encode('utf-8')
                request.settimeout(.2)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\n'
                                b'Content-Type: application/json; charset=utf-8\r\n'
                                b'Cache-Control: no-store\r\nConnection: close\r\n'
                                b'Retry-After: 1\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                request.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        with self._count_lock:
            self.active_requests += 1
        try:
            super().process_request(request, address)
        except BaseException:
            self._release_slot()
            raise

    def _release_slot(self):
        with self._count_lock:
            self.active_requests -= 1
        self._slots.release()

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._release_slot()


def read_request_body(handler, length: int, *, timeout: float = 10) -> bytes:
    """A client sending one byte at a time cannot reset the total deadline."""
    deadline = time.monotonic() + timeout
    previous_timeout = handler.connection.gettimeout()
    chunks = []
    remaining = length
    try:
        while remaining:
            available = deadline - time.monotonic()
            if available <= 0:
                raise RequestBodyTimeout('请求体读取超时；本次请求未执行')
            handler.connection.settimeout(available)
            try:
                chunk = handler.rfile.read1(min(remaining, 65536))
            except TimeoutError as error:
                raise RequestBodyTimeout('请求体读取超时；本次请求未执行') from error
            if not chunk:
                raise ValueError('请求体不完整；本次请求未执行')
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)
    finally:
        handler._body_consumed = remaining == 0
        handler.connection.settimeout(previous_timeout)
