"""只读核对本地事项的 API 与 SQLite；不代替 DOM、Task 或 ERP 验收。"""
from pathlib import Path
import argparse
import json
import sqlite3
import urllib.parse
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True)
    p.add_argument('--runtime-dir', required=True)
    p.add_argument('--initiative-id', required=True)
    a = p.parse_args()
    url = urllib.parse.urlparse(a.base_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password:
        p.error('本练习只读取无凭据的本机 HTTP 服务。')
    db = Path(a.runtime_dir).resolve() / 'workbench.db'
    if not db.is_file():
        p.error('运行目录下不存在 workbench.db，请先核对服务数据目录。')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    endpoint = a.base_url.rstrip('/') + '/api/v1/initiatives/' + urllib.parse.quote(a.initiative_id, safe='')
    with opener.open(endpoint, timeout=12) as response:
        api = json.load(response)
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT id,title,status,version,linked_task_id FROM initiatives WHERE id=?',
                           (a.initiative_id,)).fetchone()
    if row is None:
        raise SystemExit('数据库中找不到该事项；不要用相似标题替代同一对象。')
    persisted = dict(row)
    comparison = {key: {'api': api.get(key), 'sqlite': value, 'equal': api.get(key) == value}
                  for key, value in persisted.items()}
    report = {'basis': 'read_only_api_sqlite', 'initiative_id': a.initiative_id,
              'database': str(db), 'fields': comparison,
              'scope': '仅核对事项字段；未验证 DOM、真实执行、采购、下载或人审'}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(field['equal'] for field in comparison.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
