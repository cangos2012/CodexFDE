"""Local, task-bound candidate UI previews with separate data and owned processes."""
import hashlib
from contextlib import nullcontext
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time

from .process_guard import spawn
from .desktop import wait_for_product_release
from .managed_process import ManagedProcess
from .deployment_process import probe
from .reference_paths import resolve_reference


class CandidatePreviews:
    def __init__(self, runtime, tasks):
        self.runtime = Path(runtime).resolve()
        self.tasks = tasks
        self.running = {}
        self.lock = threading.Lock()
        self._closed = threading.Event()
        self._process_lock = threading.RLock()
        self._owned = {}

    def _start_process(self, task_id, command, workspace, data, *, log_mode, spawn_factory):
        managed = None
        try:
            with self._process_lock:
                if self._closed.is_set():
                    raise InterruptedError('工作台关闭，预览未启动')
                pending = self._owned.get(task_id)
                if pending:
                    self._stop_process(task_id, pending)
                managed = ManagedProcess(command, workspace, log_dir=data, log_mode=log_mode,
                                         spawn_factory=spawn_factory)
                self._owned[task_id] = managed
                if self._closed.is_set():
                    raise InterruptedError('工作台关闭，预览未获得启动许可')
                managed.start()
            return managed
        except BaseException as error:
            if managed:
                try: self._stop_process(task_id, managed)
                except Exception as cleanup:
                    if hasattr(error, 'add_note'): error.add_note('预览进程清理失败：' + str(cleanup))
            raise

    def _stop_process(self, task_id, managed):
        managed.close()
        with self._process_lock:
            if self._owned.get(task_id) is managed:
                self._owned.pop(task_id)

    def busy(self):
        with self._process_lock:
            return bool(self._owned)

    def _cleanup_failed_process(self, task_id, managed, error):
        if managed:
            try: self._stop_process(task_id, managed)
            except Exception as cleanup:
                if hasattr(error, 'add_note'): error.add_note('预览进程清理失败：' + str(cleanup))
                return str(cleanup)
        return None

    def _wait_for_release(self, data):
        deadline = time.monotonic() + 35
        while not self._closed.is_set():
            try:
                wait_for_product_release(data, timeout=0)
                return
            except RuntimeError:
                if time.monotonic() >= deadline: raise
            self._closed.wait(.1)
        raise ValueError('工作台已关闭，候选预览启动已中断；不会自动重放')

    def start(self, task_id, actor, *, configuration_guard=None):
        if self._closed.is_set():
            raise ValueError('工作台已关闭，候选预览不会重新启动')
        if not isinstance(actor, str) or not actor.strip() or actor.strip().lower().startswith('agent:') or len(actor) > 80:
            raise ValueError('请填写查看本次成果的署名')
        if not re.fullmatch(r'TASK-[A-Za-z0-9_-]+', task_id):
            raise ValueError('任务编号无效')
        task = self.tasks.get(task_id)
        gate = next((e.get('evidence') or {} for e in reversed(task['events'])
                     if e['detail'] == '课程红绿差分判定已完成'), {})
        package = next((e.get('evidence') or {} for e in reversed(task['events'])
                        if e['detail'] == '日常研发交付包已保存'), {})
        daily_ready = package.get('status') == 'review' and (task.get('result') or {}).get('summary', {}).get('decision') == 'pass'
        if task['status'] not in {'review', 'completed'} or not (gate.get('accepted') or daily_ready):
            raise ValueError('本次候选成果还未完成范围与自动检查，请先查看交付证据')
        workspace = resolve_reference(package['workspace'], self.runtime) if daily_ready else self.runtime / 'course-worktrees' / task_id
        if workspace.is_symlink() or not workspace.resolve().is_relative_to(self.runtime) or not (workspace/'web/index.html').is_file():
            raise ValueError('本次隔离成果不在原运行目录，或尚无可预览的客户界面')
        execution = next((e.get('evidence') or {} for e in reversed(task['events'])
                          if e['detail'] == '受控执行阶段完成'), {})
        manifest = execution.get('change_manifest') or []
        if not manifest:
            raise ValueError('缺少本次修改的文件校验记录，无法启动预览')
        for item in manifest:
            path = workspace / item['path']
            if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
                raise ValueError('候选文件路径越界')
            expected = item.get('after_sha256')
            if (expected is None and path.exists()) or (expected is not None and
                    (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected)):
                raise ValueError('本次修改文件在检查后又发生变化，请重新核验候选成果')
        with self.lock:
            if self._closed.is_set():
                raise ValueError('工作台已关闭，候选预览不会重新启动')
            old = self.running.get(task_id)
            if old and old[0].poll() is None:
                with configuration_guard() if configuration_guard else nullcontext():
                    return dict(old[2], reused=True)
            if old: self._stop_process(task_id, old[1])
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            data = self.runtime / 'candidate-previews' / task_id
            data.mkdir(parents=True, exist_ok=True)
            self._wait_for_release(data)
            command = [sys.executable, '-X', 'utf8', '-m', 'workbench.cli', 'serve',
                       '--host', '127.0.0.1', '--port', str(port), '--runtime-dir', str(data)]
            if (workspace / 'flowerp/server.py').is_file():
                from .external_project import flowerp_root, python_for
                command = [python_for(flowerp_root()), '-X', 'utf8', '-m', 'flowerp', 'serve',
                           '--host', '127.0.0.1', '--port', str(port), '--runtime-dir', str(data)]
            managed = None
            try:
                with configuration_guard() if configuration_guard else nullcontext():
                    managed = self._start_process(task_id, command, workspace, data, log_mode='a', spawn_factory=spawn)
                process = managed.process
                url = f'http://127.0.0.1:{port}'
                payload = {'task_id':task_id, 'url':url, 'workspace':str(workspace),
                           'label':'本次候选成果 · 独立预览数据', 'human_accepted':task['status']=='completed',
                           'notice':'请对照本次验收标准操作。此预览不代表正式发布；数据独立于当前客户项目。'}
                health_contract = {'path': '/api/v1/health/live', 'expected': {'service': 'flowerp', 'status': 'ok',
                    'runtime_id': hashlib.sha256(os.path.normcase(str(data.resolve())).encode()).hexdigest()}}
                deadline = time.monotonic() + 15
                while not self._closed.is_set() and time.monotonic() < deadline and process.poll() is None:
                    managed.check_output()
                    health = probe(url, health_contract, timeout=.5)
                    if health['passed']:
                        with configuration_guard() if configuration_guard else nullcontext():
                            with self._process_lock:
                                if self._closed.is_set(): break
                                self.tasks.append_event(task_id, '已打开本次候选成果预览', actor=actor, evidence=payload)
                                self.running[task_id] = process, managed, payload
                            return payload
                    self._closed.wait(.1)
                if self._closed.is_set():
                    raise ValueError('工作台已关闭，候选预览启动已中断；不会自动重放')
                raise ValueError('候选预览未能启动，日志已保留在本任务的 candidate-previews 目录')
            except Exception as error:
                self._cleanup_failed_process(task_id, managed, error)
                if isinstance(error, OSError):
                    if self._closed.is_set():
                        raise ValueError('工作台已关闭，候选预览启动已中断；不会自动重放') from error
                    raise ValueError('候选预览进程提前退出，请检查本次隔离代码') from error
                raise

    def close(self):
        # Signal before acquiring start()'s health-check lock. The shared registry
        # owns startup and successful processes, including their log readers.
        self._closed.set()
        with self._process_lock:
            owned = list(self._owned.items())
        errors = []
        for task_id, managed in owned:
            try: self._stop_process(task_id, managed)
            except Exception as error: errors.append(error)
        with self.lock:
            self.running = {task_id: value for task_id, value in self.running.items() if task_id in self._owned}
        if errors:
            raise RuntimeError('预览关闭未完成：' + '; '.join(map(str, errors))) from errors[0]
