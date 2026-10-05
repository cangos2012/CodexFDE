"""Reserve mutation keys before side effects; uncertain requests never replay."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


class MutationPending(ValueError):
    """A reserved request is uncertain and must be inspected instead of replayed."""


class MutationReceipts:
    def __init__(self, tasks):
        self.tasks = tasks
        with tasks.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS platform_mutations (operation TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL, payload TEXT, PRIMARY KEY(operation,key))')

    def get(self, operation, key):
        """Read admission state without replaying or exposing approval payloads."""
        if (not isinstance(operation, str) or not operation.startswith('/api/v1/')
                or len(operation) > 1024 or not isinstance(key, str) or not key.strip() or len(key) > 160):
            raise ValueError('请提供原请求的操作路径和submission_key')
        database = Path(self.tasks.path).resolve()
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
            row = db.execute('SELECT status FROM platform_mutations WHERE operation=? AND key=?',
                             (operation, key)).fetchone()
        return {'operation': operation, 'key': key, 'status': row[0] if row else 'not_found',
                'automatic_replay': False}

    def run(self, operation, key, request, producer):
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise ValueError('请提供稳定的submission_key；不确定响应时使用同一个键核对')
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.tasks.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT digest,status,payload FROM platform_mutations WHERE operation=? AND key=?', (operation, key)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ValueError('同一个submission_key不能用于不同请求')
                if old['status'] == 'completed':
                    return json.loads(old['payload'])
                if old['status'] == 'failed':
                    raise ValueError(json.loads(old['payload'])['error'])
                raise MutationPending('原请求已受理或中断，请读取原事项与运行结果；不会重复执行。')
            db.execute('INSERT INTO platform_mutations VALUES(?,?,?,?,NULL)', (operation, key, digest, 'pending'))
        try:
            result = producer()
        except Exception as exc:
            with self.tasks.connect() as db:
                db.execute("UPDATE platform_mutations SET status='failed',payload=? WHERE operation=? AND key=?", (json.dumps({'error': str(exc)}, ensure_ascii=False), operation, key))
            raise
        with self.tasks.connect() as db:
            db.execute("UPDATE platform_mutations SET status='completed',payload=? WHERE operation=? AND key=?", (json.dumps(result, ensure_ascii=False), operation, key))
        return result
