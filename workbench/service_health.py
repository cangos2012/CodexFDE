"""Cheap, read-only readiness checks for the authoritative local data store."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path


def readiness(runtime, runtime_instance, *, minimum_free_bytes=256 * 1024 * 1024):
    runtime = Path(runtime)
    checks = {}
    checks['recovery'] = {'ok': not (runtime / 'workbench-restore-failed.json').exists()}
    database = runtime / 'workbench.db'
    checks['database'] = {'ok': False}
    if database.is_file():
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
                names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                instance = db.execute('SELECT id FROM workbench_instance WHERE singleton=1').fetchone()
                checks['database']['ok'] = (bool(instance) and instance[0] == runtime_instance
                                             and {'tasks', 'harness_projects', 'initiatives'} <= names)
        except (sqlite3.Error, OSError):
            checks['database']['reason'] = 'unavailable'
    else:
        checks['database']['reason'] = 'missing'
    try:
        free = shutil.disk_usage(runtime).free
        checks['disk_space'] = {'ok': free >= minimum_free_bytes, 'free_bytes': free,
                                'minimum_free_bytes': minimum_free_bytes}
    except OSError:
        checks['disk_space'] = {'ok': False, 'reason': 'unavailable'}
    ready = all(check['ok'] for check in checks.values())
    return (200 if ready else 503), {'status': 'ready' if ready else 'unavailable',
                                    'surface': 'workbench', 'checks': checks}
