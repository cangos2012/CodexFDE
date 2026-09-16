"""Process and source boundaries for local teaching experiments.

Business observations run in the customer's interpreter. Experiments that
modify code get explicit source copies and a manifest, never a restored
business package in the controller repository.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .external_project import flowerp_root, python_for

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {'.py', '.sql', '.json', '.md', '.txt', '.html', '.css', '.js', '.toml'}
EXCLUDED = {'.git', '.venv', '__pycache__', '.runtime', 'node_modules'}


def ensure_product_process(script: str) -> None:
    """Re-enter a standalone observation without changing its output cwd."""
    product = flowerp_root()
    # Keep the virtualenv launcher path: on POSIX both environments may symlink
    # to the same system binary. Resolving that symlink discards the environment.
    python = Path(python_for(product)).absolute()
    if Path(sys.prefix).resolve() != (product / '.venv').resolve():
        # run_path preserves __file__ and __main__, while making both sources
        # explicit. Controller Eval precedes the product's same-named package.
        bootstrap = (
            'import runpy,sys; '
            'sys.path[:0]=sys.argv[1:3]; '
            'sys.argv=sys.argv[3:]; '
            'runpy.run_path(sys.argv[0],run_name="__main__")'
        )
        command = [str(python), '-B', '-X', 'utf8', '-c', bootstrap,
                   str(ROOT), str(product), str(Path(script).resolve()), *sys.argv[1:]]
        print(f'实验客户源码：{product}；解释器：{python}', file=sys.stderr)
        raise SystemExit(subprocess.run(command, cwd=Path.cwd()).returncode)
    if str(product) not in sys.path:
        sys.path.insert(1, str(product))


def copy_experiment_sources(destination: Path, packages=('flowerp', 'eval', 'workbench', 'agent'),
                            *, product: Path | None = None) -> dict:
    """Copy source-only packages into a new candidate and record their origin."""
    destination = Path(destination).resolve()
    product = flowerp_root(product)
    if destination == ROOT or destination == product:
        raise ValueError('实验副本不能覆盖控制仓库或客户仓库')
    entries = []
    for package in packages:
        if package not in {'flowerp', 'eval', 'workbench', 'agent'}:
            raise ValueError(f'不支持的实验源码包：{package}')
        source_root = product if package == 'flowerp' else ROOT
        base = source_root / package
        if not base.is_dir():
            raise ValueError(f'实验源码包缺失：{base}')
        if (destination / package).exists():
            raise FileExistsError(f'实验源码已存在，不覆盖：{destination / package}')
        for source in sorted(base.rglob('*')):
            relative = source.relative_to(source_root)
            if set(relative.parts) & EXCLUDED:
                continue
            if source.is_symlink() or not source.resolve().is_relative_to(source_root):
                raise ValueError(f'实验源码不能链接到其他位置：{source}')
            if not source.is_file() or source.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if source.name.lower().startswith(('.env', 'auth.', 'credentials.', 'secrets.')):
                continue
            entries.append((source, relative, source.read_bytes()))
    if 'eval' in packages:
        source = product / 'eval/cases.py'
        if not source.is_file() or source.is_symlink():
            raise ValueError(f'客户业务检查缺失或为链接：{source}')
        entries.append((source, Path('eval/erp_cases.py'), source.read_bytes()))
    manifest_path = destination / '.course/experiment-source.json'
    if manifest_path.exists():
        raise FileExistsError(f'来源记录已存在：{manifest_path}')
    manifest = {
        'schema': 'course.experiment-source/v1',
        'controller_root': str(ROOT), 'product_root': str(product),
        'purpose': 'isolated teaching copy; not a second maintained product',
        'files': {relative.as_posix(): {'source': str(source),
                  'sha256': hashlib.sha256(content).hexdigest()}
                  for source, relative, content in entries},
    }
    for _source, relative, content in entries:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(content)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    return manifest
