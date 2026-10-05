"""8010 compatibility transport and untouched, read-only historical databases."""
import http.client
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

from .platform_api import PlatformResponse


class LegacyHarnessHistory:
    def __init__(self, runtime):
        self.runtime = Path(runtime).resolve()

    def view(self):
        result = {'source': str(self.runtime), 'read_only': True, 'automatic_replay': False,
                  'projects': [], 'sessions': [], 'tasks': []}
        for filename, table, key in [('platform.db', 'harness_projects', 'projects'),
                                     ('platform.db', 'harness_sessions', 'sessions'),
                                     ('tasks.db', 'tasks', 'tasks')]:
            path = self.runtime / filename
            if not path.is_file():
                continue
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                db.row_factory = sqlite3.Row
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                    result[key] = [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid DESC LIMIT 50')]
        return result


class HarnessCompatibilityProxy:
    def __init__(self, runtime_dir='.harness-runtime', repository_root=None,
                 upstream_url='http://127.0.0.1:8001'):
        target = urlparse(upstream_url)
        if target.scheme != 'http' or target.hostname not in {'127.0.0.1', 'localhost', '::1'} or target.username or target.password or target.path not in {'','/'}:
            raise ValueError('兼容视图只能连接本机工作台根地址')
        self.upstream_url = upstream_url.rstrip('/')
        self.target = target
        self.repository_root = Path(repository_root or Path.cwd()).resolve()
        self.history = LegacyHarnessHistory(runtime_dir)

    def dispatch(self, method, raw_path, headers, body):
        headers = {k.lower(): v for k, v in headers.items()}
        if method == 'POST' and isinstance(body, dict):
            body = dict(body)
            if headers.get('x-workbench-actor'):
                body.setdefault('actor', headers['x-workbench-actor'])
            if headers.get('idempotency-key'):
                body.setdefault('submission_key', headers['idempotency-key'])
        if urlparse(raw_path).path == '/api/v1/legacy':
            if method != 'GET':
                return PlatformResponse(405, {'message':'旧 Harness 数据仅供只读查看，不迁移或重放'})
            return PlatformResponse(200, self.history.view())
        path = raw_path.replace('/api/v1/', '/api/v1/harness/', 1)
        connection = http.client.HTTPConnection(self.target.hostname, self.target.port or 80, timeout=30)
        request_headers = {'Content-Type':'application/json', 'Origin':self.upstream_url}
        for key in ('x-workbench-actor', 'idempotency-key'):
            if key in headers:
                request_headers[key] = headers[key]
        try:
            connection.request(method, path, json.dumps(body, ensure_ascii=False).encode('utf-8') if method != 'GET' else None, request_headers)
            response = connection.getresponse()
            payload = response.read(2 * 1024 * 1024)
            result = json.loads(payload.decode('utf-8'))
            if method == 'GET' and urlparse(raw_path).path == '/api/v1/health' and 200 <= response.status < 300 and isinstance(result, dict):
                result.update(workbench_url=self.upstream_url, compatibility_view=True)
            return PlatformResponse(response.status, result)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return PlatformResponse(503, {'error':'workbench_unavailable', 'message':'请先启动唯一工作台入口：' + self.upstream_url,
                                          'detail':str(exc), 'automatic_replay':False})
        finally:
            connection.close()

    def shutdown(self):
        pass
