"""Explicit operator-run setup; never runs on server startup or downloads on submit."""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from .contracts import REVISION
from .environment import PROFILE, REQUIREMENTS, probe, profile_hash, remove_finder_metadata, supported

MODELS = {
    'generator': ('vanch007/mlx-Yue2-3B', 'fa66d203dd56d7e033e05ee8b32269768984c4cc'),
    'vae': ('m-a-p/YuE2-Vae', '95535e72a97bc0f09b8ada125d26b4009428c0e8'),
    'transcription': ('m-a-p/SheetSage2', 'eab522a8168e8b8b8c4856bf8609cd86198f01fe'),
    'mert': ('m-a-p/MERT-v2-FullSong', 'd8ba1c745e733b3908ce6ad16ebeb17ac7600a42'),
}


def prepare_source(source):
    """Accept only the pinned checkout and our two audited metadata changes."""
    if not source.exists():
        subprocess.run(['git', 'init', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'remote', 'add', 'origin', 'https://github.com/vanch007/mlx-Yue.git'], check=True)
        subprocess.run(['git', '-C', str(source), 'fetch', '--depth', '1', 'origin', REVISION], check=True)
        subprocess.run(['git', '-C', str(source), 'checkout', '--detach', REVISION], check=True)
    git = ['git', '-C', str(source)]
    actual = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(git + ['status', '--porcelain'], text=True).splitlines()
    if actual != REVISION or any(line != ' M pyproject.toml' for line in dirty):
        raise RuntimeError('音频源码版本不同或有额外修改，保留现场，请核对后重试')
    original = subprocess.check_output(git + ['show', 'HEAD:pyproject.toml'], text=True)
    adapted = original
    for old, new in [('>=3.12,<3.13', '>=3.12,<3.15'), ('numpy==2.2.6', 'numpy==2.3.3')]:
        if original.count(old) != 1:
            raise RuntimeError('上游依赖声明与已核验版本不符')
        adapted = adapted.replace(old, new)
    project = source / 'pyproject.toml'
    if project.read_text() not in (original, adapted):
        raise RuntimeError('音频 pyproject.toml 有额外修改，未覆盖')
    project.write_text(adapted)


def download_model(root, name):
    """Explicit download only; HF metadata stays outside strict model directories."""
    from huggingface_hub import hf_hub_download, snapshot_download
    root = Path(root)
    target = root / 'models' / name
    if target.exists():
        print(f'保留已有模型：{name}（不覆盖、不重复下载）')
        return
    repo, revision = MODELS[name]
    kwargs = dict(repo_id=repo, revision=revision, cache_dir=str(root / 'cache'))
    if name == 'generator':
        manifest = Path(hf_hub_download(filename='conversion.json', **kwargs))
        patterns = ['conversion.json', 'README.md', *json.loads(manifest.read_text())['files']]
    else:
        patterns = ['config.json', 'model.safetensors', 'README.md', 'LICENSE*', 'THIRD_PARTY*', 'licenses/*']
    snapshot = Path(snapshot_download(allow_patterns=patterns, **kwargs))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.download-', dir=target.parent) as temp:
        staged = Path(temp) / name
        staged.mkdir()
        # A pre-existing HF snapshot cache may contain more than allow_patterns.
        # Copy only our allowlist, materializing links without .cache/.git extras.
        for file in snapshot.rglob('*'):
            relative = file.relative_to(snapshot)
            if not file.is_file() or not any(fnmatch.fnmatch(relative.as_posix(), p) for p in patterns):
                continue
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)
        staged.rename(target)


def install(root, python, uv, selected):
    info = probe(python, dependencies=False)
    if not supported(info):
        raise RuntimeError('请选择原生 Apple Silicon 的 Python 3.14 虚拟环境（默认使用画布主 .venv）')
    source = root / 'source'
    prepare_source(source)
    # Keep an operator-readable baseline. Constrain every existing distribution so
    # an audio install fails on conflicts rather than silently downgrading the app.
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    log_dir = root / 'install-records' / stamp
    log_dir.mkdir(parents=True)
    baseline = subprocess.check_output([str(python), '-m', 'pip', 'freeze', '--all'], text=True)
    (log_dir / 'before.txt').write_text(baseline)
    # freeze may contain a direct URL to an old temporary wheel. Constraints must
    # preserve installed versions, not require that disposable build file again.
    versions = subprocess.check_output([str(python), '-c',
        'import importlib.metadata as m; print("\\n".join(sorted(d.metadata["Name"]+"=="+d.version for d in m.distributions())))'], text=True)
    constraints = log_dir / 'constraints.txt'
    constraints.write_text(versions)
    with tempfile.TemporaryDirectory(prefix='audio-build-', dir=root) as temp:
        subprocess.run([uv, 'build', '--no-config', '--python', str(python), '--wheel',
                        '--out-dir', temp, str(source)], check=True)
        wheel, = Path(temp).glob('*.whl')
        command = [uv, 'pip', 'install', '--no-config', '--python', str(python), '--only-binary', ':all:',
                   '--constraint', str(constraints), '-r', str(REQUIREMENTS), str(wheel)]
        subprocess.run(command + ['--dry-run'], check=True)
        subprocess.run(command, check=True)
        wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    subprocess.run([uv, 'pip', 'check', '--python', str(python)], check=True)
    info = probe(python)
    if info['missing']:
        raise RuntimeError('音频依赖核验失败：' + ', '.join(info['missing']))
    for name in selected:
        subprocess.run([str(python), '-c',
                        'from backend.audio.install import download_model; import sys; download_model(sys.argv[1],sys.argv[2])',
                        str(root), name], cwd=Path(__file__).resolve().parents[2], check=True)
    # Finder metadata is not a model artifact and makes YuE2's strict converted
    # directory verification fail. Keep all other unexpected files visible.
    remove_finder_metadata(root / 'models')
    doctor = [str(python), '-m', 'lyra.cli', 'doctor']
    for flag, name in (('--model', 'generator'), ('--vae', 'vae')):
        if (root / 'models' / name).is_dir():
            doctor += [flag, str(root / 'models' / name)]
    with (log_dir / 'doctor.json').open('w') as log:
        subprocess.run(doctor + ['--verify-hashes'], cwd=source, check=True, stdout=log)
    receipt = dict(revision=REVISION, profile=PROFILE, profile_sha256=profile_hash(),
                   python=str(python), prefix=info['prefix'], python_version=info['version'],
                   wheel_sha256=wheel_hash, models=MODELS, installed_at=stamp)
    pending = root / 'installed.json.tmp'
    pending.write_text(json.dumps(receipt, indent=2) + '\n')
    os.replace(pending, root / 'installed.json')
    print('音频依赖已接入主 Python 3.14；FFmpeg 共用系统安装，推理仍在独立子进程中执行。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', choices=('none', 'generation', 'all'), default='none')
    default_python = (Path(sys.executable) if sys.prefix != sys.base_prefix else
                      Path(__file__).resolve().parents[2] / '.venv' / 'bin' / 'python')
    parser.add_argument('--python', type=Path, default=default_python,
                        help='共享主环境的 Python 3.14 解释器，不创建新环境')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        parser.error('需要原生 Apple Silicon macOS')
    import fcntl
    uv = shutil.which('uv')
    if not uv: parser.error('请先安装 uv')
    from ..app_config import APP_DATA_DIR
    root = (APP_DATA_DIR / 'components' / 'audio-yue').resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = [] if args.models == 'none' else ['generator', 'vae'] if args.models == 'generation' else list(MODELS)
    with (root / 'install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('另一个音频安装器正在运行')
        install(root, args.python.expanduser().absolute(), uv, selected)


if __name__ == '__main__':
    main()
