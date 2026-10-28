"""Install the SOMA pose mannequins: pinned converter dependencies, verified assets, neutral/female/male GLBs.

Usage:
  .venv/bin/python -m backend.pose_scene.install                      # download from Hugging Face
  .venv/bin/python -m backend.pose_scene.install --assets-from DIR    # reuse already-downloaded files

Shares the main macOS Python 3.14 environment like ReShot; every existing package version is
locked, nothing is upgraded or downgraded. Nothing is installed or downloaded at server start.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from .contracts import BODIES, GLB_VERSION, LODS, SOMA_FILES, SOMA_RELEASE, SOMA_REPO, SOMA_REVISION, glb_name

DEFAULT_ROOT = Path(os.environ.get('CANVASHUB_DATA_DIR') or Path(__file__).resolve().parents[2])


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch_assets(target, source=None):
    """Copy or download each pinned SOMA file into target, verifying SHA-256; keep valid files."""
    target.mkdir(parents=True, exist_ok=True)
    for name, expected in SOMA_FILES.items():
        path = target / name
        if path.is_file() and digest(path) == expected:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(path.name + '.installing')
        if source:
            origin = Path(source) / name
            if not origin.is_file() or digest(origin) != expected:
                raise SystemExit(f'本地资产缺失或校验失败：{name}')
            shutil.copyfile(origin, pending)
        else:
            url = f'https://huggingface.co/{SOMA_REPO}/resolve/{SOMA_REVISION}/{name}'
            print(f'下载 {name} …', flush=True)
            request = urllib.request.Request(url, headers={'User-Agent': 'CanvasHub-PoseScene'})
            with urllib.request.urlopen(request, timeout=60) as response, pending.open('wb') as stream:
                shutil.copyfileobj(response, stream, 1024 * 1024)
        if digest(pending) != expected:
            pending.unlink(missing_ok=True)
            raise SystemExit(f'下载内容校验失败：{name}')
        pending.replace(path)


def install_dependencies():
    baseline = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
    requirements = Path(__file__).with_name('requirements-py314.txt')
    with tempfile.TemporaryDirectory(prefix='pose-scene-install-') as temp:
        constraints = Path(temp) / 'constraints.txt'
        constraints.write_text(''.join(f'{name}=={version}\n' for name, version in sorted(baseline.items())))
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--disable-pip-version-check',
                        '-c', str(constraints), '-r', str(requirements)], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    changed = [name for name, version in baseline.items() if importlib.metadata.version(name) != version]
    if changed:
        raise SystemExit('原依赖意外变化：' + ', '.join(changed))
    return digest(requirements)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--assets-from', type=Path)
    parser.add_argument('--component', type=Path, default=DEFAULT_ROOT / 'components' / 'pose-soma')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 14) or sys.prefix == sys.base_prefix or platform.system() != 'Darwin':
        raise SystemExit('请在现有 macOS Python 3.14 虚拟环境中安装')
    assets = args.component / 'assets'
    fetch_assets(assets, args.assets_from)
    requirements_sha256 = install_dependencies()
    print('生成人偶 GLB …', flush=True)
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-m', 'backend.pose_scene.convert', '--assets', str(assets),
                             '--out', str(args.component / 'glb')], check=True, cwd=project_root,
                            capture_output=True, text=True)
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    receipt = {'engine': 'soma', 'release': SOMA_RELEASE, 'repo': SOMA_REPO, 'revision': SOMA_REVISION,
               'files': SOMA_FILES, 'glb_version': GLB_VERSION, 'lods': {lod: summary[lod] for lod in LODS},
               'bodies': list(BODIES), 'glb': {lod: {kind: glb_name(lod, kind) for kind in BODIES} for lod in LODS},
               'requirements_sha256': requirements_sha256,
               'installed_at': time.time()}
    pending = args.component / 'installed.json.installing'
    pending.write_text(json.dumps(receipt, indent=2))
    pending.replace(args.component / 'installed.json')
    print('SOMA 姿态人偶已安装（中性 / 女性 / 男性）：' + '，'.join(f"{lod} {summary[lod]['vertices']} 顶点" for lod in LODS))


if __name__ == '__main__':
    main()
