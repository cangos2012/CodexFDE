"""Relocation from a verified backup; external environment is revalidated separately."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile

from .maintenance import MaintenanceGate
from .file_io import atomic_write_text, open_read
from .runtime_lease import WorkbenchRuntimeLease
from .workbench_backup import (BackupService, _begin_restore, _checked_archive,
                              _failed_restore, _safe_member, RESTORE_MARKER)
from .reference_paths import (load_reference_mappings, resolve_reference, validate_reference_mappings,
                              unload_reference_mappings, reference_mapping_scope)


FAILED_MARKER = 'workbench-restore-failed.json'


def _physical_hash(path):
    digest = hashlib.sha256()
    # Keep Windows sharing-lock retries, while bypassing historical relocation.
    with reference_mapping_scope(Path(path).parent, {}):
        with open_read(path, 'rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def _probe(command, *, cwd=None):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=10, **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))


def _registered_projects(runtime):
    database = Path(runtime).resolve() / 'workbench.db'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_projects'").fetchone():
            return []
        return [{'id': r['id'], 'name': r['name'], 'root_path': r['root_path'],
                 'eval_command': json.loads(r['eval_command_json'])} for r in db.execute('SELECT * FROM harness_projects')]


def _verify_project(project, runtime, *, require_source_match):
    from .daily_delivery import manifest
    root = resolve_reference(project['root_path'], runtime).resolve()
    errors, executable_kind = [], 'unavailable'
    try:
        if not root.is_dir():
            raise ValueError('项目源码目录缺失')
        git = _probe(['git', '-C', str(root), 'rev-parse', '--show-toplevel'])
        if git.returncode or Path(git.stdout.strip()).resolve() != root:
            errors.append('Git登记不可用或不是登记仓库的根目录')
        with reference_mapping_scope(runtime, load_reference_mappings(runtime)):
            source = manifest(root, runtime)
        if require_source_match and source != project.get('source_manifest'):
            errors.append('源码哈希不匹配')
        command = project.get('eval_command')
        if not isinstance(command, list) or not command or any(not isinstance(p, str) or not p.strip() for p in command):
            raise ValueError('项目检查命令尚未登记')
        executable = resolve_reference(command[0], runtime)
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError('项目登记可执行程序缺失或不是绝对路径')
        python = bool(re.fullmatch(r'(?:python(?:w|[0-9.]+)?|pypy[0-9.]*|py)(?:\.exe)?', executable.name.lower()))
        if python:
            executable_kind = 'python'
            check = _probe([str(executable), '-c', 'import json,sys; print(json.dumps({"venv":sys.prefix!=sys.base_prefix,"version":list(sys.version_info[:2])}))'])
            data = json.loads(check.stdout)
            if check.returncode or not data.get('venv') or tuple(data.get('version', [])) < (3, 10):
                errors.append('项目Python虚拟环境未验证（需Python 3.10+独立环境）')
        else:
            executable_kind = 'non_python'
            check = _probe([str(executable), '--version'])
            if check.returncode or not (check.stdout.strip() or check.stderr.strip()):
                errors.append('项目可执行程序版本探测未通过')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        errors.append(str(exc))
    return {'project_id': project['id'], 'root_path': str(root), 'ok': not errors, 'errors': errors,
            'executable_kind': executable_kind, 'source_match_required': require_source_match}


def _environment_plan(path):
    """Reject incomplete control metadata without touching restored evidence."""
    plan = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(plan, dict) or plan.get('schema') != 'workbench.migration-environment/v1'
            or not isinstance(plan.get('projects'), list) or not isinstance(plan.get('dependencies'), list)):
        raise ValueError('迁移环境计划结构无效')
    seen = set()
    for project in plan['projects']:
        if (not isinstance(project, dict) or not isinstance(project.get('id'), str)
                or project['id'] in seen or not isinstance(project.get('root_path'), str)
                or not Path(project['root_path']).is_absolute()
                or not isinstance(project.get('eval_command'), list)
                or not isinstance(project.get('source_manifest'), dict)
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in project['source_manifest'].items())):
            raise ValueError('迁移项目计划结构无效')
        expected = hashlib.sha256(json.dumps(project['source_manifest'], sort_keys=True).encode()).hexdigest()
        if project.get('source_sha256') != expected:
            raise ValueError('迁移项目源码清单哈希无效')
        seen.add(project['id'])
    if any(not isinstance(d, dict) or not isinstance(d.get('path'), str)
           or not Path(d['path']).is_absolute() for d in plan['dependencies']):
        raise ValueError('迁移依赖计划结构无效')
    return plan


def _same_registration(planned, registered, runtime):
    if resolve_reference(planned['root_path'], runtime).resolve() != resolve_reference(registered['root_path'], runtime).resolve():
        return False
    command = lambda p: [str(resolve_reference(v, runtime)) if Path(v).is_absolute() else v
                         for v in p['eval_command']]
    return command(planned) == command(registered)


def migration_plan(runtime, projects):
    runtime = Path(runtime).resolve()
    from .workbench_backup import _database_state
    _, _, dependencies = _database_state(runtime / 'workbench.db', runtime, check_busy=False)
    rows = []
    for project in projects.list():
        root = Path(project['root_path'])
        from .daily_delivery import manifest
        try:
            with reference_mapping_scope(runtime, load_reference_mappings(runtime)):
                source = manifest(root, runtime)
            state = 'available'
        except (OSError, ValueError, subprocess.SubprocessError):
            source, state = {}, 'unavailable'
        rows.append({'id': project['id'], 'name': project['name'], 'root_path': str(root), 'source_manifest': source,
                     'source_sha256': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
                     'eval_command': project['eval_command'], 'status': state})
    return {'schema': 'workbench.migration-environment/v1', 'runtime_root': str(runtime), 'dependencies': dependencies, 'projects': rows,
            'missing_external_dependencies': sorted({d['path'] for d in dependencies if not d.get('exists')}),
            'restore_command': 'python -X utf8 -m workbench.cli restore-workbench-migration <备份包> --runtime-dir <新目录> --mapping-file <映射JSON>',
            'boundary': '恢复须停服并使用空目录；证据原文不改写。外部仓库、虚拟环境与客户数据单独准备；旧任务不重放。'}


def prepare_migration(runtime, projects, actor, busy_check=None):
    runtime = Path(runtime).resolve()
    plan = migration_plan(runtime, projects)
    with MaintenanceGate(runtime).write():
        folder = runtime / 'migration'
        folder.mkdir(exist_ok=True)
        path = folder / 'environment-plan.json'
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    result = BackupService(runtime).create(actor, busy_check=busy_check)
    archive = Path(result.get('path') or result.get('archive_path') or runtime / 'backups' / (result['id'] + '.zip'))
    return {**result, 'archive_path': str(archive), 'sha256': _physical_hash(archive), 'plan': plan,
            'restore_command': plan['restore_command'], 'automatic_replay': False}


def restore_migration(archive, target_runtime, mappings):
    mappings = validate_reference_mappings(mappings)
    target = Path(target_runtime).absolute()
    if target.is_symlink() or any(p.exists() and (p.is_symlink() or bool(getattr(p.stat(), 'st_file_attributes', 0) & 0x400)) for p in [target, *target.parents]):
        raise ValueError('迁移目标不可经过链接或重解析点')
    target = target.resolve()
    with WorkbenchRuntimeLease(target), MaintenanceGate(target).exclusive():
        allowed = {'workbench-service.lock', 'workbench-maintenance.lock'}
        if any(p.name not in allowed for p in target.iterdir()):
            raise ValueError('迁移目标必须为空，已有数据需先保留')
        failure_marker = _begin_restore(target, None)
        installed = []
        backup_id = None
        try:
            with tempfile.TemporaryDirectory(prefix='workbench-migrate-') as temporary:
                staging = Path(temporary) / 'payload'
                staging.mkdir()
                # The user-supplied archive is a physical file, not a historical DB reference.
                physical_archive = Path(temporary) / 'archive.zip'
                with Path(archive).open('rb') as source, physical_archive.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
                manifest = _checked_archive(physical_archive, staging)
                backup_id = manifest['id']
                original = manifest['runtime_root']
                if Path(original) == target:
                    raise ValueError('原路径恢复请使用restore-workbench-backup')
                mapping = dict(mappings)
                mapping[original] = str(target)
                previous_file = staging / 'migration' / 'reference-map.json'
                if previous_file.is_file():
                    previous = json.loads(previous_file.read_text(encoding='utf-8'))
                    if previous.get('runtime_root') != original:
                        raise ValueError('原迁移映射与备份运行目录不一致')
                    for old, intermediate in validate_reference_mappings(previous.get('mappings')).items():
                        mapping.setdefault(old, intermediate)
                mapping = validate_reference_mappings(mapping)
                with reference_mapping_scope(target, mapping):
                    mapping = {old: str(resolve_reference(old, target)) for old in mapping}
                mapping = validate_reference_mappings(mapping)
                for relative in manifest['directories']:
                    target.joinpath(*_safe_member(relative).parts).mkdir(parents=True, exist_ok=True)
                for relative in sorted(manifest['files'], key=lambda name: name == 'workbench.db'):
                    path = target / relative; path.parent.mkdir(parents=True, exist_ok=True)
                    installed.append(path)
                    shutil.copyfile(staging / relative, path)
                    if _physical_hash(path) != manifest['files'][relative]['sha256']:
                        raise ValueError('迁移后证据哈希变化')
                map_file = target / 'migration' / 'reference-map.json'
                if map_file.is_file():
                    # Retain the previous control file too, in case evidence references its bytes.
                    historical = target / 'migration' / 'history' / manifest['id'] / 'reference-map.json'
                    historical.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(map_file, historical)
                    installed.append(historical)
                    mapping[str(Path(original) / 'migration' / 'reference-map.json')] = str(historical)
                map_file.parent.mkdir(exist_ok=True)
                if map_file not in installed:
                    installed.append(map_file)
                map_file.write_text(json.dumps({'schema': 'workbench.reference-map/v1', 'runtime_root': str(target), 'mappings': mapping}, ensure_ascii=False, indent=2), encoding='utf-8')
                load_reference_mappings(target)
                for ref in manifest['references']:
                    path = resolve_reference(ref['path'], target)
                    if not path.exists() or (ref.get('expected_sha256') and _physical_hash(path) != ref['expected_sha256']):
                        raise ValueError('迁移引用缺失或哈希变化：' + ref['path'])
                marker = {'schema': 'workbench.migration/v1', 'backup_id': manifest['id'], 'automatic_replay': False,
                          'human_review_required': True, 'external_dependencies': manifest['external_dependencies'], 'execution_environment': 'not_verified'}
                installed.append(target / RESTORE_MARKER)
                atomic_write_text(target / RESTORE_MARKER, json.dumps(marker, ensure_ascii=False))
                failure_marker.unlink()
        except Exception as error:
            unload_reference_mappings(target)
            _failed_restore(target, installed, backup_id, error)
            raise
    return {'ok': True, 'runtime': str(target), 'automatic_replay': False, 'evidence_restore': 'verified',
            'execution_environment': validate_migration_environment(target)}


def validate_migration_environment(runtime, *, require_source_match=True, persist=True):
    runtime = Path(runtime).resolve()
    map_file = runtime / 'migration' / 'reference-map.json'
    map_sha256 = _physical_hash(map_file) if map_file.is_file() else None
    load_reference_mappings(runtime)
    plan_file = runtime / 'migration' / 'environment-plan.json'
    errors, results, missing = [], [], []
    try:
        plan = _environment_plan(plan_file)
        registered = {p['id']: p for p in _registered_projects(runtime)}
        if {p['id'] for p in plan['projects']} != set(registered):
            errors.append('迁移项目计划与恢复数据库登记不一致')
        for project in plan['projects']:
            result = _verify_project(project, runtime, require_source_match=require_source_match)
            current = registered.get(project['id'])
            if not current or not _same_registration(project, current, runtime):
                result['ok'] = False
                result['errors'].append('迁移项目路径或检查命令与恢复数据库登记不一致')
            results.append(result)
        missing = [d['path'] for d in plan['dependencies'] if not resolve_reference(d['path'], runtime).exists()]
    except (OSError, ValueError, TypeError, KeyError, sqlite3.DatabaseError) as error:
        errors.append(str(error))
    current_map_sha256 = _physical_hash(map_file) if map_file.is_file() else None
    if current_map_sha256 != map_sha256:
        errors.append('迁移核验期间引用映射已变化，请重新核验')
    result = {'status': 'ready' if results and all(p['ok'] for p in results) and not missing and not errors else 'missing_dependencies',
              'projects': results, 'missing_external_dependencies': sorted(set(missing)), 'automatic_replay': False,
              'errors': errors,
              'source_match_required': require_source_match,
              'reference_map_sha256': map_sha256,
              'source_plan_sha256': hashlib.sha256(plan_file.read_bytes()).hexdigest() if plan_file.is_file() else None}
    if persist:
        with MaintenanceGate(runtime).write():
            (runtime / 'migration').mkdir(exist_ok=True)
            (runtime / 'migration' / 'environment-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def fresh_migration_preflight(runtime, project_id=None):
    """New work validates today's registry, after the one-time source proof."""
    runtime = Path(runtime).resolve()
    marker_file = runtime / RESTORE_MARKER
    map_file = runtime / 'migration' / 'reference-map.json'
    if not marker_file.is_file() and map_file.is_file():
        return {'status': 'missing_dependencies', 'projects': [], 'automatic_replay': False,
                'errors': ['迁移恢复标记缺失，不能将历史映射当作普通运行环境']}
    if not marker_file.is_file() or json.loads(marker_file.read_text(encoding='utf-8')).get('schema') != 'workbench.migration/v1':
        if map_file.is_file():
            return {'status': 'missing_dependencies', 'projects': [], 'automatic_replay': False,
                    'errors': ['迁移恢复标记与引用映射不一致']}
        return {'status': 'ready', 'projects': [], 'automatic_replay': False, 'migration': False}
    if not map_file.is_file():
        return {'status': 'missing_dependencies', 'projects': [], 'automatic_replay': False,
                'errors': ['迁移引用映射缺失，请核对迁移目录']}
    load_reference_mappings(runtime)
    plan_file = runtime / 'migration' / 'environment-plan.json'
    proof_file = runtime / 'migration' / 'environment-result.json'
    if not plan_file.is_file() or not proof_file.is_file():
        return {'status': 'missing_dependencies', 'projects': [], 'automatic_replay': False,
                'errors': ['尚未完成迁移源文件与环境首次核验']}
    plan = _environment_plan(plan_file)
    proof = json.loads(proof_file.read_text(encoding='utf-8'))
    if not proof.get('source_match_required') or proof.get('source_plan_sha256') != hashlib.sha256(plan_file.read_bytes()).hexdigest():
        return {'status': 'missing_dependencies', 'projects': [], 'automatic_replay': False,
                'errors': ['迁移首次源码核验凭据缺失或计划已变化，请重新核验']}
    if not proof.get('reference_map_sha256') or proof['reference_map_sha256'] != _physical_hash(map_file):
        return {'status': 'missing_dependencies', 'projects': [], 'automatic_replay': False,
                'errors': ['迁移首次引用映射核验凭据缺失或映射已变化，请重新核验']}
    selected = [p for p in _registered_projects(runtime) if project_id is None or p['id'] == project_id]
    results = [_verify_project(p, runtime, require_source_match=False) for p in selected]
    original = {p['id'] for p in plan['projects']}
    accepted = {p['project_id'] for p in proof.get('projects', []) if p.get('ok')}
    for result in results:
        if result['project_id'] in original and result['project_id'] not in accepted:
            result['ok'] = False
            result['errors'].append('此迁移项目尚未完成首次源码一致性核验')
    missing = sorted({d['path'] for d in plan['dependencies'] if not resolve_reference(d['path'], runtime).exists()})
    return {'status': 'ready' if results and all(p['ok'] for p in results) and not missing else 'missing_dependencies',
            'projects': results, 'source_match_required': False, 'automatic_replay': False,
            'missing_external_dependencies': missing,
            'historical_missing_dependencies': proof.get('missing_external_dependencies', [])}


def assert_migration_preflight(runtime, project_id=None):
    result = fresh_migration_preflight(runtime, project_id)
    if result['status'] != 'ready':
        errors = result.get('errors', []) + [e for p in result.get('projects', []) for e in p['errors']]
        errors += ['外部依赖缺失：' + p for p in result.get('missing_external_dependencies', [])]
        raise ValueError('迁移环境未就绪：' + '；'.join(errors or ['请核对项目登记并完成迁移核验']))
    return result
