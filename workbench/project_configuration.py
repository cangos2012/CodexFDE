"""Versioned local commands. Registering configuration never starts a process."""
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlparse


def command(value, *, optional=False):
    if optional and not value:
        return []
    if not isinstance(value, list) or not value or any(not isinstance(p, str) or not p.strip() or '\x00' in p for p in value):
        raise ValueError('命令必须是非空JSON参数数组')
    if not Path(value[0]).is_absolute() or not Path(value[0]).is_file():
        raise ValueError('命令首项必须是本机可执行文件的绝对路径')
    for arg in value:
        if re.search(r'(?i)(?:^|\s)--?(?:api[-_]key|access[-_]token|token|password|passwd|secret|authorization)(?:=|\s|$)|\bbearer\s+\S+|://[^/@\s]+:[^/@\s]+@', arg):
            raise ValueError('运行配置不能保存密钥；请使用本机进程已有的认证环境')
        if set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', arg)) - {'workspace', 'runtime_dir', 'port'}:
            raise ValueError('命令包含未知占位符')
    return value


def health(value):
    if not isinstance(value, dict):
        raise ValueError('请配置健康检查')
    path = value.get('path', '')
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path:
        raise ValueError('健康检查须为本机服务的路径')
    expected = value.get('expected', {'status': 'ok'})
    if not isinstance(expected, dict) or not expected:
        raise ValueError('健康检查须有非空的预期JSON字段')
    if any(str(k).lower() in {'password', 'secret', 'token', 'api_key', 'authorization', 'access_token'} for k in expected):
        raise ValueError('健康配置不能保存认证密钥')
    return {'path': path, 'expected': expected}


def configuration(preview, profiles):
    clean_preview = None
    if preview is not None and not isinstance(preview, dict):
        raise ValueError('预览配置须为JSON对象或null')
    if preview:
        clean_preview = {'command': command(preview.get('command')), 'health': health(preview.get('health')),
                         'timeout_seconds': _timeout(preview.get('timeout_seconds', 15))}
    if not isinstance(profiles, list) or len(profiles) > 20:
        raise ValueError('部署配置须为列表，最多20项')
    result, ids = [], set()
    for p in profiles:
        if not isinstance(p, dict):
            raise ValueError('每项部署配置须为JSON对象')
        identifier = p.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in ids or len(identifier) > 80:
            raise ValueError('部署配置编号无效或重复')
        ids.add(identifier)
        url = p.get('url', '')
        parsed = urlparse(url)
        if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
            raise ValueError('首版部署只支持本机HTTP服务地址')
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError('部署服务端口无效') from error
        if port is not None and not 1 <= port <= 65535:
            raise ValueError('部署服务端口无效')
        if p.get('environment', 'local') != 'local':
            raise ValueError('首版部署目标环境须为local')
        result.append(dict(id=identifier, name=p.get('name', identifier), environment=p.get('environment', 'local'),
                           command=command(p.get('command')), rollback_command=command(p.get('rollback_command'), optional=True),
                           url=url.rstrip('/'), health=health(p.get('health')),
                           timeout_seconds=_timeout(p.get('timeout_seconds', 60))))
    return clean_preview, result


def _timeout(value):
    if type(value) is not int or not 1 <= value <= 1800:
        raise ValueError('超时必须为1至1800秒')
    return value


class ProjectConfiguration:
    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, projects):
        self.projects = projects
        with self._locks_guard:
            key = os.path.normcase(str(Path(projects.path).resolve()))
            self.lock = self._locks.setdefault(key, threading.RLock())
        with projects.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS project_configurations (project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    def get(self, project_id):
        with self.lock:
            return self._get(project_id)

    def _get(self, project_id):
        with self.projects.connect() as db:
            row = db.execute('SELECT revision,payload FROM project_configurations WHERE project_id=?', (project_id,)).fetchone()
        payload = json.loads(row['payload']) if row else {'preview_config': None, 'deployment_profiles': []}
        from .reference_paths import resolve_reference
        runtime = Path(self.projects.path).parent
        for profile in [payload.get('preview_config'), *payload.get('deployment_profiles', [])]:
            if not profile:
                continue
            for field in ('command', 'rollback_command'):
                if field in profile:
                    profile[field] = [str(resolve_reference(arg, runtime)) if Path(arg).is_absolute() else arg for arg in profile[field]]
        return {'configuration_revision': row['revision'] if row else 0, **payload}

    def save(self, project_id, body, actor):
        with self.lock:
            return self._save(project_id, body, actor)

    def _save(self, project_id, body, actor):
        self.projects.get(project_id)
        old = self.get(project_id)
        preview, profiles = configuration(body.get('preview_config', old['preview_config']), body.get('deployment_profiles', old['deployment_profiles']))
        with self.projects.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM project_configurations WHERE project_id=?', (project_id,)).fetchone()
            revision = row[0] if row else 0
            if body.get('expected_configuration_revision') != revision:
                raise ValueError('项目运行配置版本已变化，请重新读取')
            db.execute('INSERT OR REPLACE INTO project_configurations VALUES(?,?,?)', (project_id, revision + 1,
                       json.dumps(dict(preview_config=preview, deployment_profiles=profiles, actor=actor), ensure_ascii=False)))
        return self.get(project_id)
