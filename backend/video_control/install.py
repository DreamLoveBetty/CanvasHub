"""Install pinned ReShot dependencies into the shared venv; reuse verified local weights.

Usage: .venv/bin/python -m backend.video_control.install --models-from /path/to/models
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

REVISION = '9ae7d108b7caf29b16faf2c456bf387bd94ce052'
WEIGHTS = {
    'depth/video_depth_anything_vits.pth': '13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609',
    'pose/yolox_l.onnx': '7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411',
    'pose/dw-ll_ucoco_384.onnx': '724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843',
}


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--models-from', type=Path, required=True)
    parser.add_argument('--component', type=Path, default=Path(os.environ.get('CANVASHUB_DATA_DIR') or Path(__file__).resolve().parents[2]) / 'components' / 'reshot')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 14) or sys.prefix == sys.base_prefix or platform.system() != 'Darwin':
        raise SystemExit('请在现有 macOS Python 3.14 虚拟环境中安装')
    for name, expected in WEIGHTS.items():
        source = args.models_from / name
        if not source.is_file() or digest(source) != expected: raise SystemExit(f'模型缺失或校验失败：{name}')
        target = args.component / 'models' / name
        if target.exists() and digest(target) != expected: raise SystemExit(f'已有模型不同，不覆盖：{name}')
    baseline = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
    requirements = Path(__file__).with_name('requirements-py314.txt')
    with tempfile.TemporaryDirectory(prefix='reshot-install-') as temp:
        constraints = Path(temp) / 'constraints.txt'
        constraints.write_text(''.join(f'{name}=={version}\n' for name, version in sorted(baseline.items())))
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--disable-pip-version-check',
                        '-c', str(constraints), '-r', str(requirements)], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    changed = [name for name, version in baseline.items() if importlib.metadata.version(name) != version]
    if changed: raise SystemExit('原依赖意外变化：' + ', '.join(changed))
    for name in WEIGHTS:
        target = args.component / 'models' / name
        if target.exists(): continue
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_suffix(target.suffix + '.installing')
        shutil.copyfile(args.models_from / name, pending)
        pending.replace(target)
    receipt = {'engine': 'reshot', 'version': '0.5.0', 'revision': REVISION, 'python': sys.executable,
               'weights': WEIGHTS, 'requirements_sha256': digest(requirements)}
    (args.component / 'installed.json').write_text(json.dumps(receipt, indent=2))
    print('ReShot 已安装，共用当前 Python 环境及系统 FFmpeg；原有依赖版本未改变。')


if __name__ == '__main__': main()
