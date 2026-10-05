"""Owned local processes with one launch gate and complete pipe cleanup."""
import codecs
import io
from pathlib import Path
import threading
import time

from .process_guard import spawn


class ManagedProcess:
    """Register this object before start() opens the Windows launch gate."""

    def __init__(self, command, cwd, *, log_dir=None, log_mode='w', capture_limit=0,
                 env=None, spawn_factory=None):
        self.lock = threading.RLock()
        self._close_lock = threading.Lock()
        self.readers, self._errors, self._logs = [], [], {}
        self._reader_labels = {}
        self.parts = {'stdout': '', 'stderr': ''}
        self.capture_limit = capture_limit
        self._started = self._closed = False
        try:
            if log_dir is not None:
                for label in self.parts:
                    self._logs[label] = (Path(log_dir) / (label + '.log')).open(log_mode, encoding='utf-8')
            factory = spawn_factory or spawn
            kwargs = {'env': env} if env is not None else {}
            self.process, self.owner, self._prefix = factory(command, cwd, **kwargs)
        except BaseException as error:
            for log in self._logs.values():
                try: log.close()
                except Exception as cleanup:
                    if hasattr(error, 'add_note'): error.add_note('启动日志清理失败：' + str(cleanup))
            raise

    def _remember_error(self, error):
        with self.lock:
            self._errors.append(error)

    def _drain(self, label):
        pipe, log = getattr(self.process, label), self._logs.get(label)
        decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder('utf-8')('replace'), True)
        try:
            binary = getattr(pipe, 'buffer', None)
            while True:
                raw = binary.read1(65536) if binary is not None else pipe.read(65536)
                text = decoder.decode(raw, final=not raw) if binary is not None else raw
                if text:
                    if self.capture_limit:
                        with self.lock:
                            self.parts[label] = (self.parts[label] + text)[-self.capture_limit:]
                    if log is not None:
                        try:
                            log.write(text); log.flush()
                        except Exception as error:
                            # Continue draining after a disk error so the child cannot
                            # block on a full pipe. check_output() rejects its receipt.
                            self._remember_error(error)
                            try: log.close()
                            except Exception as close_error: self._remember_error(close_error)
                            log = None
                if not raw:
                    break
        except Exception as error:
            self._remember_error(error)
        finally:
            for stream in (pipe, log):
                if stream is not None:
                    try: stream.close()
                    except Exception as error: self._remember_error(error)

    def start(self):
        try:
            with self.lock:
                if self._closed:
                    raise InterruptedError('受管进程已关闭，启动门闩不会重新打开')
                if self._started:
                    return
                for label in self.parts:
                    reader = threading.Thread(target=self._drain, args=(label,), daemon=True,
                                              name='managed-' + label + '-' + str(self.process.pid))
                    reader.start()
                    self.readers.append(reader)
                    self._reader_labels[label] = reader
                self.process.stdin.write(self._prefix)
                self.process.stdin.close()
                self._started = True
        except BaseException as error:
            try: self.close()
            except Exception as cleanup:
                if hasattr(error, 'add_note'): error.add_note('受管进程清理失败：' + str(cleanup))
            raise

    def check_output(self):
        with self.lock:
            if self._errors:
                raise OSError('受管进程日志读取或保存失败：' + str(self._errors[0])) from self._errors[0]

    def _join_readers(self, timeout=5):
        deadline = time.monotonic() + timeout
        for reader in self.readers:
            reader.join(max(0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in self.readers):
            raise RuntimeError('受管进程日志线程尚未收尾')

    def receipt(self):
        if self.process.poll() is not None:
            self._join_readers()
        self.check_output()
        with self.lock:
            return dict(returncode=self.process.poll(), stdout=self.parts['stdout'],
                        stderr=self.parts['stderr'], process_id=self.process.pid)

    def close(self):
        with self._close_lock:
            with self.lock:
                self._closed = True
                owner = self.owner
            errors = []
            if owner:
                try:
                    owner.close()
                    with self.lock:
                        self.owner = None
                except Exception as error: errors.append(error)
            try:
                if self.process.poll() is None: self.process.kill()
                self.process.wait(timeout=5)
            except Exception as error: errors.append(error)
            try: self.process.stdin.close()
            except Exception as error: errors.append(error)
            if self.readers:
                try: self._join_readers()
                except Exception as error: errors.append(error)
            for label in self.parts:
                reader = self._reader_labels.get(label)
                if reader is not None and reader.is_alive():
                    continue
                for stream in (getattr(self.process, label), self._logs.get(label)):
                    if stream is None or stream.closed:
                        continue
                    try: stream.close()
                    except Exception as error: errors.append(error)
            if errors:
                raise RuntimeError('受管进程关闭未完成：' + '; '.join(map(str, errors))) from errors[0]
