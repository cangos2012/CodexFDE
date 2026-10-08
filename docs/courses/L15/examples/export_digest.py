"""Read an existing release index and export a traceable teaching digest."""
import argparse
import hashlib
import json
from pathlib import Path


def export_digest(index_path, runtime_dir, output):
    runtime = Path(runtime_dir).resolve()
    index = Path(index_path).resolve()
    target = Path(output).resolve()
    if not index.is_relative_to(runtime) or not index.is_file():
        raise ValueError('索引必须在指定运行目录内且已存在')
    data = json.loads(index.read_text(encoding='utf-8'))
    if data.get('schema') != 'workbench.release-index/v1':
        raise ValueError('不是支持的交付索引')
    refs = []
    for name, ref in data.get('references', {}).items():
        file = (index.parent / ref['path']).resolve()
        if not file.is_relative_to(runtime) or not file.is_file():
            raise ValueError('证据越过运行目录或已经丢失：' + name)
        actual = hashlib.sha256(file.read_bytes()).hexdigest()
        if actual != ref['sha256']:
            raise ValueError('证据指纹不一致：' + name)
        refs.append({'label': name, 'file': file.as_posix(), 'sha256': actual})
    # Keep source strings in a fenced JSON block, not executable Markdown links.
    summary = {key: data.get(key) for key in (
        'task_id', 'request', 'requirement_id', 'task_status', 'execution_mode',
        'changed_files', 'out_of_scope_files', 'pre_eval_summary',
        'post_eval_summary', 'human_review', 'evidence_gaps')}
    summary['source_index'] = index.as_posix()
    summary['checked_references'] = refs
    text = '# 交付事实摘要\n\n以下内容来自已有任务索引。状态保留原值，缺失证据不自动补齐。\n\n'
    value = json.dumps(summary, ensure_ascii=False, indent=2)
    # A fence longer than any run of backticks prevents source text from closing it.
    import re
    fence = '`' * max(3, max((len(m.group()) + 1 for m in re.finditer(r'`+', value)), default=3))
    text += fence + 'json\n' + value + '\n' + fence + '\n\n'
    text += '文件存在且指纹匹配，只证明所引用字节未变化。它不证明业务正确、已经验收或已经发布。\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    return {'output': str(target), 'task_id': data['task_id'], 'references_checked': len(refs), 'task_status': data['task_status']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index', required=True)
    p.add_argument('--runtime-dir', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    try:
        print(json.dumps(export_digest(a.index, a.runtime_dir, a.out), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as e:
        p.exit(1, str(e) + '\n')
