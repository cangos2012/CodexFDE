"""Runtime-scoped, reentrant write gate with a cross-process maintenance lock."""
from contextlib import contextmanager
from pathlib import Path
import os
import threading


class MaintenanceBusy(RuntimeError):
    pass


class _State:
    def __init__(self):
        self.lock = threading.RLock()
        self.writers = 0
        self.handle = None
        self.exclusive_owner = None
        self.exclusive_depth = 0


_states = {}
_states_lock = threading.Lock()
_local = threading.local()


def _file_lock(handle, exclusive):
    handle.seek(0 if exclusive else 1 + os.getpid() % 65535)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 65536 if exclusive else 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)


def _file_unlock(handle, exclusive):
    handle.seek(0 if exclusive else 1 + os.getpid() % 65535)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 65536 if exclusive else 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class MaintenanceGate:
    def __init__(self, runtime):
        self.runtime = Path(runtime).resolve()
        self.key = os.path.normcase(str(self.runtime))
        with _states_lock:
            self.state = _states.setdefault(self.key, _State())

    def _open(self, exclusive):
        self.runtime.mkdir(parents=True, exist_ok=True)
        handle = (self.runtime / 'workbench-maintenance.lock').open('a+b')
        try:
            _file_lock(handle, exclusive)
        except OSError as error:
            handle.close()
            raise MaintenanceBusy('工作台正在备份或写入维护，请稍后重试；当前输入仍应保留') from error
        return handle

    @contextmanager
    def write(self):
        depths = getattr(_local, 'depths', None)
        if depths is None:
            depths = _local.depths = {}
        depth = depths.get(self.key, 0)
        with self.state.lock:
            if self.state.exclusive_owner not in (None, threading.get_ident()):
                raise MaintenanceBusy('工作台正在备份，请稍后重试；当前输入仍应保留')
            if not depth and self.state.exclusive_owner is None:
                if not self.state.writers:
                    self.state.handle = self._open(False)
                self.state.writers += 1
            depths[self.key] = depth + 1
        try:
            yield
        finally:
            with self.state.lock:
                depths[self.key] -= 1
                if not depths[self.key] and self.state.exclusive_owner is None:
                    self.state.writers -= 1
                    if not self.state.writers:
                        _file_unlock(self.state.handle, False)
                        self.state.handle.close()
                        self.state.handle = None

    @contextmanager
    def exclusive(self):
        ident = threading.get_ident()
        with self.state.lock:
            if self.state.exclusive_owner == ident:
                self.state.exclusive_depth += 1
            else:
                if self.state.writers or self.state.exclusive_owner is not None:
                    raise MaintenanceBusy('仍有工作台写入，请稍后再备份')
                self.state.handle = self._open(True)
                self.state.exclusive_owner = ident
                self.state.exclusive_depth = 1
        try:
            yield
        finally:
            with self.state.lock:
                self.state.exclusive_depth -= 1
                if not self.state.exclusive_depth:
                    _file_unlock(self.state.handle, True)
                    self.state.handle.close()
                    self.state.handle = None
                    self.state.exclusive_owner = None


def runtime_write_guard(database_path):
    return MaintenanceGate(Path(database_path).resolve().parent).write()
