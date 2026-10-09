"""Shared-interpreter contract and lightweight probes; never imports inference libraries."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .contracts import REVISION

PROFILE = 'cpython314-numpy233-v1'
REQUIREMENTS = Path(__file__).with_name('requirements-py314.txt')
MODEL_DIRECTORIES = ('generator', 'vae', 'transcription', 'mert')


def pins():
    return dict(line.split('==', 1) for line in REQUIREMENTS.read_text().splitlines()
                if line and not line.startswith('#'))


def profile_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def remove_finder_metadata(models_root):
    """Remove only macOS Finder metadata from known model directories.

    YuE2's converted generator verifies every relative path against
    ``conversion.json``. Finder may add ``.DS_Store`` after installation, which
    is harmless model-wise but makes that strict verification fail before any
    inference starts. Do not hide or delete any other unexpected artifact.
    """
    root = Path(models_root)
    removed = []
    for name in MODEL_DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            continue
        try:
            candidates = tuple(directory.rglob('.DS_Store'))
        except OSError as exc:
            raise RuntimeError(f'无法检查模型目录中的 Finder 元数据：{directory}') from exc
        for path in candidates:
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    removed.append(path)
            except OSError as exc:
                raise RuntimeError(f'无法清理模型目录中的 Finder 元数据：{path}') from exc
    return removed


def read_receipt(root):
    try:
        result = json.loads((Path(root) / 'installed.json').read_text())
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def shared_python(receipt=None):
    # Frozen executables cannot run ``-c`` or worker.py. Only an explicit installed
    # external runtime receipt may supply their interpreter; never the app binary.
    if getattr(sys, 'frozen', False):
        value = (receipt or {}).get('python')
        return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None
    # Keep the venv executable spelling: resolve() would escape a symlinked venv.
    return Path(sys.executable).absolute()


def probe(python, *, dependencies=True):
    expected = {**pins(), 'mlx-yue': '0.1.0'} if dependencies else {}
    code = '''import importlib.metadata as m,json,platform,sys
expected=json.loads(sys.argv[1]); missing=[]
for name, version in expected.items():
    try: actual=m.version(name)
    except m.PackageNotFoundError: actual=None
    if actual != version: missing.append(name)
print(json.dumps(dict(version=list(sys.version_info[:3]),prefix=sys.prefix,
    virtualenv=sys.prefix != sys.base_prefix,system=platform.system(),
    machine=platform.machine(),missing=missing)))
'''
    result = subprocess.run([str(python), '-c', code, json.dumps(expected)],
                            capture_output=True, text=True, check=True, timeout=15)
    return json.loads(result.stdout)


def supported(info):
    return (info.get('version', [])[:2] == [3, 14] and info.get('virtualenv')
            and info.get('system') == 'Darwin' and info.get('machine') == 'arm64')


def ready(python, receipt):
    if (python is None or not python.is_file() or receipt.get('revision') != REVISION
            or receipt.get('profile') != PROFILE or receipt.get('profile_sha256') != profile_hash()):
        return False
    try:
        info = probe(python)
        return bool(supported(info) and not info['missing'] and info['prefix'] == receipt.get('prefix'))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
