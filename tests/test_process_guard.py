"""Real Windows process ownership; no Codex or student work is involved."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from workbench import process_guard


class _ProcessEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                ('flags', wintypes.DWORD), ('executable', wintypes.WCHAR * 260)]


class _FixtureHandles:
    """Keep identities alive; cleanup never selects processes by a recycled PID."""
    def __init__(self, case):
        self.case, self.handles, self.roles = case, {}, {}
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in [
            ('CreateToolhelp32Snapshot', [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            ('Process32FirstW', [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
            ('Process32NextW', [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
            ('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ('GetProcessId', [wintypes.HANDLE], wintypes.DWORD),
            ('IsProcessInJob', [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
            ('QueryFullProcessImageNameW', [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('TerminateProcess', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
        ]:
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, result

    def check(self, value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def parent(self, pid):
        snapshot = self.api.CreateToolhelp32Snapshot(2, 0)
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ProcessEntry(); entry.size = ctypes.sizeof(entry)
            self.check(self.api.Process32FirstW(snapshot, ctypes.byref(entry)))
            while True:
                if entry.pid == pid:
                    return int(entry.parent)
                if not self.api.Process32NextW(snapshot, ctypes.byref(entry)):
                    return None
        finally:
            self.check(self.api.CloseHandle(snapshot))

    def retain(self, role, pid, parent):
        self.case.assertEqual(parent, self.parent(pid), role + ' must belong to the fixture ancestry')
        if pid not in self.handles:
            # QUERY_INFORMATION | SYNCHRONIZE | TERMINATE, only for verified fixture processes.
            handle = self.check(self.api.OpenProcess(0x100401, False, pid))
            self.handles[pid] = handle
            self.case.assertEqual(pid, self.api.GetProcessId(handle))
            self.case.assertEqual(258, self.api.WaitForSingleObject(handle, 0))
            image = ctypes.create_unicode_buffer(32768); length = wintypes.DWORD(len(image))
            self.check(self.api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)))
            expected = {os.path.normcase(str(Path(p).resolve()))
                        for p in (sys.executable, sys._base_executable)}
            self.case.assertIn(os.path.normcase(str(Path(image.value).resolve())), expected)
        self.roles[role] = pid

    def members(self, owner):
        result = {}
        for role, pid in self.roles.items():
            member = wintypes.BOOL()
            self.check(self.api.IsProcessInJob(self.handles[pid], owner.handle, ctypes.byref(member)))
            result[role] = bool(member.value)
        return result

    def waits(self):
        deadline = time.monotonic() + 5
        return {role: int(self.api.WaitForSingleObject(self.handles[pid],
                    int(max(0, deadline-time.monotonic()) * 1000)))
                for role, pid in self.roles.items()}

    def terminate(self):
        errors = []
        for pid, handle in reversed(list(self.handles.items())):
            try:
                if self.api.WaitForSingleObject(handle, 0) == 258:
                    self.check(self.api.TerminateProcess(handle, 130))
                if self.api.WaitForSingleObject(handle, 5000) != 0:
                    raise RuntimeError('fixture process did not exit: ' + str(pid))
            except Exception as error:
                errors.append(str(error))
        return errors

    def retain_descendants(self):
        """Capture an incomplete startup's children while their held parent is alive."""
        snapshot = self.api.CreateToolhelp32Snapshot(2, 0)
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        records = []
        try:
            entry = _ProcessEntry(); entry.size = ctypes.sizeof(entry)
            self.check(self.api.Process32FirstW(snapshot, ctypes.byref(entry)))
            while True:
                records.append((int(entry.pid), int(entry.parent), entry.executable.lower()))
                if not self.api.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            self.check(self.api.CloseHandle(snapshot))
        changed = True
        while changed:
            changed = False
            for pid, parent, image in records:
                if (pid not in self.handles and parent in self.handles and image == 'python.exe'
                        and self.api.WaitForSingleObject(self.handles[parent], 0) == 258):
                    self.retain('startup-child-' + str(pid), pid, parent)
                    changed = True

    def close(self):
        for handle in self.handles.values():
            self.check(self.api.CloseHandle(handle))


@unittest.skipUnless(os.name == 'nt', 'Windows process lifetime contract')
class WindowsProcessGuardTests(unittest.TestCase):
    def test_preassignment_guard_cannot_leave_command_descendants_outside_owner_job(self):
        handles = _FixtureHandles(self)
        owner = process = None
        readers, eof, reader_errors = {}, {}, []
        with tempfile.TemporaryDirectory(prefix='process-guard-owned-gate-') as directory:
            root = Path(directory).resolve()
            nonce = os.urandom(16).hex()
            guard, target, grandchild = [root / name for name in ('guard.py', 'target.py', 'grandchild.py')]
            marker_code = (
                "import json,os,sys,time\nfrom pathlib import Path\n"
                f"nonce={nonce!r}\n"
                "def mark(name,**extra):\n"
                " p=Path(__file__).with_name(name)\n"
                " tmp=p.with_suffix('.pending')\n"
                " tmp.write_text(json.dumps(dict(pid=os.getpid(),parent=os.getppid(),nonce=nonce,"
                "script=str(Path(__file__).resolve()),cwd=str(Path.cwd().resolve()),"
                "executable=sys.executable,**extra)),encoding='utf-8')\n"
                " tmp.replace(p)\n")
            # The guard is deliberately alive before assign, but both stdin gates stay closed.
            guard.write_text(marker_code + "import subprocess\nmark('guard-ready.json')\n"
                "header=sys.stdin.readline()\n"
                "if not header: raise SystemExit(125)\n"
                "command=json.loads(header)\nmark('header-read.json')\n"
                "prompt=sys.stdin.read()\n"
                "raise SystemExit(subprocess.run(command,input=prompt,text=True,encoding='utf-8',"
                "creationflags=subprocess.CREATE_NO_WINDOW).returncode)\n", encoding='utf-8')
            grandchild.write_text(marker_code + "mark('grandchild-ready.json')\ntime.sleep(60)\n", encoding='utf-8')
            target.write_text(marker_code + "import subprocess\n"
                f"child=subprocess.Popen([sys.executable,'-u',{str(grandchild)!r}],"
                "creationflags=subprocess.CREATE_NO_WINDOW)\n"
                "mark('target-ready.json',child_pid=child.pid)\ntime.sleep(60)\n", encoding='utf-8')

            def marker(name, script):
                deadline = time.monotonic() + 10
                path = root / name
                while not path.is_file() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(path.is_file(), name + ' was not ready within 10 seconds')
                data = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual((nonce, str(script), str(root)),
                                 (data['nonce'], data['script'], data['cwd']))
                self.assertIs(type(data['pid']), int)
                self.assertIs(type(data['parent']), int)
                return data

            real_assign = process_guard.WindowsJob.assign
            guard_record = None
            def delayed_assign(value, pid):
                nonlocal owner, guard_record
                owner = value
                handles.retain('guard_spawn', pid, os.getpid())
                guard_record = marker('guard-ready.json', guard)
                handles.retain('guard', guard_record['pid'],
                               os.getpid() if guard_record['pid'] == pid else pid)
                self.assertFalse((root / 'target-ready.json').exists())
                self.assertFalse((root / 'grandchild-ready.json').exists())
                real_assign(value, pid)

            def drain(label):
                stream = getattr(process, label)
                try:
                    while stream.read(4096):
                        pass
                    eof[label].set()
                except Exception as error:
                    reader_errors.append(str(error))
                finally:
                    stream.close()

            try:
                command = [sys.executable, '-u', str(target)]
                with patch.object(process_guard, '__file__', str(guard)), \
                        patch.object(process_guard.WindowsJob, 'assign', delayed_assign):
                    process, owner, prefix = process_guard.spawn(command, root)
                self.assertEqual(command, json.loads(prefix), 'the registered venv command must not change')
                for label in ('stdout', 'stderr'):
                    eof[label] = threading.Event()
                    readers[label] = threading.Thread(target=drain, args=(label,), daemon=True)
                    readers[label].start()
                process.stdin.write(prefix); process.stdin.flush()
                marker('header-read.json', guard)
                self.assertFalse((root / 'target-ready.json').exists(), 'stdin EOF is still required')
                self.assertFalse((root / 'grandchild-ready.json').exists())
                process.stdin.close()
                target_record = marker('target-ready.json', target)
                guard_pid, target_pid = guard_record['pid'], target_record['pid']
                if target_record['parent'] != guard_pid:
                    handles.retain('target_launcher', target_record['parent'], guard_pid)
                handles.retain('target', target_pid, target_record['parent'])
                self.assertEqual(os.path.normcase(sys.executable),
                                 os.path.normcase(target_record['executable']))
                handles.retain('grandchild_launcher', target_record['child_pid'], target_pid)
                grandchild_record = marker('grandchild-ready.json', grandchild)
                expected_parent = (target_pid if grandchild_record['pid'] == target_record['child_pid']
                                   else target_record['child_pid'])
                handles.retain('grandchild', grandchild_record['pid'], expected_parent)
                members = handles.members(owner)
                owner.close()
                waits = handles.waits()
                deadline = time.monotonic() + 5
                for reader in readers.values():
                    reader.join(max(0, deadline-time.monotonic()))
                ended = {label: eof[label].is_set() and not reader.is_alive()
                         for label, reader in readers.items()}
                print('owned gate evidence: ' + json.dumps(dict(members=members, waits=waits, eof=ended)), flush=True)
                self.assertTrue(all(members.values()), 'guard, target and grandchild must belong to the owner Job')
                self.assertTrue(all(wait == 0 for wait in waits.values()), 'owner.close must stop every fixture process')
                self.assertEqual({'stdout': True, 'stderr': True}, ended)
                self.assertEqual([], reader_errors)
            finally:
                # Even an old-implementation failure cleans up only our held fixture identities.
                cleanup_errors = []
                try:
                    handles.retain_descendants()
                except Exception as error:
                    cleanup_errors.append(str(error))
                if owner:
                    try:
                        owner.close()
                    except Exception as error:
                        cleanup_errors.append(str(error))
                cleanup_errors.extend(handles.terminate())
                if process:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    process.stdin.close()
                for reader in readers.values():
                    reader.join(5)
                if process:
                    for label in ('stdout', 'stderr'):
                        self.assertFalse(label in readers and readers[label].is_alive(), 'fixture reader leaked')
                        getattr(process, label).close()
                handles.close()
                self.assertEqual([], cleanup_errors)

    def test_missing_base_interpreter_fails_closed_before_creating_process_resources(self):
        for value in (None, '', str(Path(tempfile.gettempdir()) / 'absent-base-python.exe')):
            with self.subTest(base=value), patch.object(process_guard.sys, '_base_executable', value), \
                    patch.object(process_guard, 'WindowsJob') as job, \
                    patch.object(process_guard.subprocess, 'Popen') as popen:
                with self.assertRaisesRegex(OSError, '基础.*解释器'):
                    process_guard.spawn([sys.executable, '-c', 'pass'], Path.cwd())
                job.assert_not_called(); popen.assert_not_called()

    def test_owner_crash_terminates_both_child_and_grandchild(self):
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handles = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'child.py'
            script.write_text("import subprocess,sys,os,json,time\nfrom pathlib import Path\n"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
                "Path('pids.json').write_text(json.dumps([os.getpid(),child.pid]))\n"
                "time.sleep(60)\n", encoding='utf-8')
            code = ("import sys,time\nfrom workbench.process_guard import spawn\n"
                    "process,owner,prefix=spawn([sys.executable,sys.argv[1]],sys.argv[2])\n"
                    "process.stdin.write(prefix);process.stdin.close()\n"
                    "time.sleep(60)\n")
            parent = subprocess.Popen([sys.executable, '-c', code, str(script), str(root)],
                                      cwd=Path(__file__).resolve().parent.parent,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 10
                while not (root / 'pids.json').exists() and time.monotonic() < deadline:
                    self.assertIsNone(parent.poll(), 'owner exited before children were ready')
                    time.sleep(.05)
                pids = json.loads((root / 'pids.json').read_text())
                for pid in pids:
                    handle = api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
                    self.assertTrue(handle, 'child must be alive before owner crash')
                    handles.append(handle)
                    self.assertEqual(258, api.WaitForSingleObject(handle, 0))
                parent.kill(); parent.wait(timeout=5)
                for handle in handles:
                    self.assertEqual(0, api.WaitForSingleObject(handle, 5000),
                                     'child must terminate when owner closes unexpectedly')
            finally:
                if parent.poll() is None:
                    parent.kill(); parent.wait(timeout=5)
                for handle in handles:
                    api.CloseHandle(handle)
