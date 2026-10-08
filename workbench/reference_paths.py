"""Explicit read-time relocation. Historical payloads and hashes stay unchanged."""
import json
from contextlib import contextmanager
from pathlib import Path
import threading

_maps = {}
_lock = threading.RLock()
_local = threading.local()


def unload_reference_mappings(runtime):
    with _lock:
        _maps.pop(str(Path(runtime).resolve()), None)


def validate_reference_mappings(mappings):
    if not isinstance(mappings, dict):
        raise ValueError('迁移映射须为原绝对路径到新绝对路径的对象')
    result = {}
    for old, new in mappings.items():
        if (not isinstance(old, str) or not isinstance(new, str) or not Path(old).is_absolute()
                or not Path(new).is_absolute() or '..' in Path(old).parts or '..' in Path(new).parts):
            raise ValueError('迁移映射路径无效')
        source, target = Path(old), Path(new)
        if source == target or target.is_relative_to(source):
            raise ValueError('迁移映射不能指向自身或原目录的子目录')
        result[str(source)] = str(target)
    for source in result:
        _resolve(Path(source), list(result.items()))
    return result


def _resolve(target, choices):
    choices = sorted(choices, key=lambda p: len(p[0]), reverse=True)
    seen = set()
    for _ in range(64):
        token = str(target)
        if token in seen:
            raise ValueError('迁移映射存在循环')
        seen.add(token)
        for old, new in choices:
            try:
                relative = target.relative_to(Path(old))
            except ValueError:
                continue
            resolved = Path(new) / relative
            if not resolved.resolve().is_relative_to(Path(new).resolve()):
                raise ValueError('迁移证据路径越界')
            target = resolved
            break
        else:
            return target
    raise ValueError('迁移映射链过长或不断扩展')


@contextmanager
def reference_mapping_scope(runtime, mappings):
    """Thread-local archive interpretation; never replace the live runtime map."""
    key = str(Path(runtime).resolve())
    mappings = validate_reference_mappings(mappings)
    stack = getattr(_local, 'scopes', None)
    if stack is None:
        stack = _local.scopes = []
    stack.append((key, mappings))
    try:
        yield
    finally:
        stack.pop()


@contextmanager
def backup_reference_scope(manifest, staging):
    """Use the verified package's map while comparing its historical DB refs."""
    runtime = Path(manifest['runtime_root']).resolve()
    path = Path(staging) / 'migration' / 'reference-map.json'
    mappings = {}
    if path.is_file():
        data = json.loads(_read_control_file(path))
        if data.get('schema') != 'workbench.reference-map/v1' or Path(data.get('runtime_root', '')).resolve() != runtime:
            raise ValueError('包内迁移引用映射与备份运行目录不一致')
        mappings = data.get('mappings')
    with reference_mapping_scope(runtime, mappings):
        yield


def load_reference_mappings(runtime):
    runtime = Path(runtime).resolve()
    path = runtime / 'migration' / 'reference-map.json'
    if not path.is_file():
        with _lock:
            _maps.pop(str(runtime), None)
        return {}
    data = json.loads(_read_control_file(path))
    if data.get('schema') != 'workbench.reference-map/v1' or data.get('runtime_root') != str(runtime):
        raise ValueError('迁移引用映射不属于当前运行目录')
    mappings = validate_reference_mappings(data.get('mappings', {}))
    with _lock:
        _maps.pop(str(runtime), None)
        _maps[str(runtime)] = mappings
    return mappings


def _read_control_file(path):
    from .file_io import read_text
    # A mapping is physical control metadata, never an historical DB reference.
    with reference_mapping_scope(Path(path).parent, {}):
        return read_text(path)


def resolve_reference(path, runtime=None):
    target = Path(path)
    if not target.is_absolute():
        return target
    key = str(Path(runtime).resolve()) if runtime else None
    scopes = getattr(_local, 'scopes', [])
    for scope_runtime, mappings in reversed(scopes):
        if runtime is None or scope_runtime == key:
            return _resolve(target, list(mappings.items()))
    with _lock:
        # The most recently loaded runtime owns an otherwise ambiguous old path.
        choices = list(_maps.get(key, {}).items()) if runtime else [p for values in reversed(list(_maps.values())) for p in values.items()]
    return _resolve(target, choices)
