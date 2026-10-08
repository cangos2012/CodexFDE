"""Real loopback HTTP drip fixtures; each server and connection belongs here."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
import unittest

from workbench.deployment_process import probe


class HealthProbeDeadlineTests(unittest.TestCase):
    @contextmanager
    def service(self, mode='normal', body=None):
        release = threading.Event(); entered = threading.Event(); finished = threading.Event()
        connections = []; connections_lock = threading.Lock()
        payload = body if body is not None else b'{"status":"ok","runtime_id":"fixture-owned"}'
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with connections_lock: connections.append(self.connection)
                entered.set()
                try:
                    if mode == 'header':
                        self.wfile.write(b'HTTP/1.0 200 OK\r\n')
                        header = b'Content-Type: application/json\r\nContent-Length: ' + str(len(payload)).encode() + b'\r\n\r\n'
                        for index, value in enumerate(header):
                            self.wfile.write(bytes([value]))
                            if release.wait(.04):
                                self.wfile.write(header[index+1:]); break
                        self.wfile.write(payload)
                    else:
                        self.send_response(200)
                        if mode in {'chunked','chunked-large'}: self.send_header('Transfer-Encoding','chunked')
                        elif mode != 'unframed': self.send_header('Content-Length',str(len(payload)))
                        self.end_headers()
                        if mode in {'body','chunked'}:
                            for index, value in enumerate(payload):
                                chunk = bytes([value])
                                self.wfile.write(b'1\r\n' + chunk + b'\r\n' if mode == 'chunked' else chunk)
                                if release.wait(.04):
                                    tail = payload[index+1:]
                                    if tail:
                                        self.wfile.write(hex(len(tail))[2:].encode() + b'\r\n' + tail + b'\r\n' if mode == 'chunked' else tail)
                                    break
                            if mode == 'chunked': self.wfile.write(b'0\r\n\r\n')
                        elif mode == 'chunked-large':
                            self.wfile.write(hex(len(payload))[2:].encode() + b'\r\n' + payload + b'\r\n0\r\n\r\n')
                        else: self.wfile.write(payload)
                except OSError:
                    pass  # The bounded probe intentionally closes its own socket.
                finally:
                    finished.set()
            def log_message(self,*args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.daemon_threads = False  # server_close joins every fixture handler.
        thread = threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02})
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}',release,entered
        finally:
            release.set()
            with connections_lock:
                for connection in connections:
                    try: connection.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
            server.shutdown(); server.server_close(); thread.join(2)
            self.assertFalse(thread.is_alive())
            if entered.is_set(): self.assertTrue(finished.wait(2),'fixture handler did not close')

    def assert_drip_deadline(self, mode):
        with self.service(mode) as (url,release,entered):
            results = []
            worker = threading.Thread(target=lambda:results.append(probe(url,{
                'path':'/health','expected':{'status':'ok','runtime_id':'fixture-owned'}},timeout=.15)))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                worker.join(.5)
                self.assertFalse(worker.is_alive(),'slow ' + mode + ' reset the total health deadline')
                self.assertEqual(1,len(results))
                self.assertFalse(results[0]['passed'])
                self.assertIn('error',results[0])
            finally:
                release.set(); worker.join(2)
                self.assertFalse(worker.is_alive(),'probe fixture cleanup must close its reader')

    def test_dripping_json_body_cannot_reset_total_deadline(self):
        self.assert_drip_deadline('body')

    def test_dripping_response_headers_cannot_reset_total_deadline(self):
        self.assert_drip_deadline('header')

    def test_chunked_dripping_body_cannot_reset_total_deadline(self):
        self.assert_drip_deadline('chunked')

    def test_oversized_json_never_reports_healthy(self):
        body = json.dumps({'status':'ok','padding':'x'*70000}).encode()
        for mode in ('normal','unframed','chunked-large'):
            with self.subTest(mode=mode),self.service(mode=mode,body=body) as (url,_,_):
                value = probe(url,{'path':'/health','expected':{'status':'ok'}})
                self.assertFalse(value['passed'],'health JSON must have a fixed body-size cap')
                self.assertIn('64KiB',value['error'])

    def test_normal_json_preserves_expected_identity_and_rejects_mismatch(self):
        with self.service() as (url,_,_):
            self.assertTrue(probe(url,{'path':'/health','expected':{'status':'ok','runtime_id':'fixture-owned'}})['passed'])
            self.assertFalse(probe(url,{'path':'/health','expected':{'runtime_id':'another-service'}})['passed'])

    def test_invalid_authority_and_path_do_not_contact_fixture(self):
        with self.service() as (url,_,entered):
            for authority,path in ((url + '/other','/health'),(url,'//different.invalid/health'),
                                   ('https://127.0.0.1','/health'),('http://untrusted.invalid','/health')):
                self.assertFalse(probe(authority,{'path':path,'expected':{'status':'ok'}})['passed'])
            self.assertFalse(entered.is_set())

    def test_deep_json_is_a_failed_receipt_instead_of_an_escaping_exception(self):
        body = b'{"status":"ok","nested":' + b'['*2000 + b'0' + b']'*2000 + b'}'
        with self.service(body=body) as (url,_,_):
            value = probe(url,{'path':'/health','expected':{'status':'ok'}})
            self.assertFalse(value['passed']); self.assertIn('error',value)
