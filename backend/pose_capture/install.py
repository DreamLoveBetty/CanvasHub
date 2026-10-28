"""Install GEM-X lite photo and video recognition: pinned source, verified models, pinned dependencies,
and the CoreML caches video recognition needs.

Usage:
  .venv/bin/python -m backend.pose_capture.install                    # download about 4.4 GB, then ~14 min CoreML compile
  .venv/bin/python -m backend.pose_capture.install --models-from DIR  # reuse a GEM-X checkout's inputs/
  .venv/bin/python -m backend.pose_capture.install --skip-video       # photos only (no compile, ~20 GB less disk)
  .venv/bin/python -m backend.pose_capture.install --skip-evidence    # video without SAM 3D Body image evidence
  .venv/bin/python -m backend.pose_capture.install --evidence-only    # add image evidence to an existing install
  .venv/bin/python -m backend.pose_capture.install --skip-comotion    # video tracked by YOLOX + ByteTrack (no CoMotion)
  .venv/bin/python -m backend.pose_capture.install --comotion-only    # add CoMotion tracking to an existing install
  .venv/bin/python -m backend.pose_capture.install --comotion-only --comotion-from DIR   # reuse a CoMotion checkout's data/

Video uses a fixed-batch, constant-folded VitPose copy (built here with `onnx`) compiled once for CoreML
(CPU+GPU, about 13.5 minutes, ~17 GB cache). Without CoreML, video falls back to a slower CPU setup.
Image evidence for video (SAM 3D Body: arm depth and finger shape) adds 2.8 GB of weights, the pinned
sam-3d-body submodule, a pinned DINOv3 checkout and three pure-Python packages (requirements-evidence-py314.txt).
CoMotion tracking for video (people through occlusion, and the starting body GEM-X refines) adds a 2.3 GB checkpoint
download (1.5 GB kept), the pinned ml-comotion source, the neutral SMPL model, SOMA's SMPL wrap and eight pure-Python
packages (requirements-comotion-py314.txt); it needs an Apple GPU (MPS).

Shares the main macOS Python 3.14 environment: every existing package version is locked; 21 pinned
packages are added (hydra/lightning/timm and friends). antlr4-python3-runtime 4.9.3 ships only a
source archive, so its pure-Python wheel is built first; everything else installs from wheels.
GEM-X is used from an upstream checkout at a fixed commit; its own install_requires are not used.
Nothing is installed or downloaded at server start.
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
import zipfile

from .contracts import (COMOTION_ARCHIVE, COMOTION_COMMIT, COMOTION_DIR, COMOTION_ENGINE, COMOTION_FILES, COMOTION_REPO,
                        DINOV3_COMMIT, DINOV3_DIR, DINOV3_REPO, ENGINE, EVIDENCE_ENGINE, EVIDENCE_FILES, GEMX_COMMIT, GEMX_REPO,
                        MODEL_FILES, SAM3DB_COMMIT, SAM3DB_DIR, SAM3DB_REPO, YOLOX_ONNX, YOLOX_ZIP)

DEFAULT_ROOT = Path(os.environ.get('CANVASHUB_DATA_DIR') or Path(__file__).resolve().parents[2])


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checkout(target, repo, commit):
    """A git checkout of `repo` at exactly `commit` (shallow), reused when it is already there."""
    target = Path(target)
    if (target / '.git').exists():
        head = subprocess.run(['git', '-C', str(target), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        if head == commit:
            return
        subprocess.run(['git', '-C', str(target), 'fetch', '--quiet', 'origin', commit], check=True)
    else:
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', '-C', str(target), 'init', '--quiet'], check=True)
        subprocess.run(['git', '-C', str(target), 'remote', 'add', 'origin', str(repo)], check=True)
        subprocess.run(['git', '-C', str(target), 'fetch', '--quiet', '--depth', '1', 'origin', commit], check=True)
    subprocess.run(['git', '-C', str(target), 'checkout', '--quiet', '--force', commit], check=True)


def fetch_source(component, source_from=None):
    """Upstream GEM-X at GEMX_COMMIT, without submodules (SOMA comes from py-soma-x)."""
    checkout(component / 'gemx', source_from or GEMX_REPO, GEMX_COMMIT)


def candidates(models_from, name):
    base = Path(models_from)
    rel = Path(name).relative_to('gemx') if name.startswith('gemx/') else None
    if rel is not None:
        yield base / rel
        if rel.parts[:2] == ('inputs', 'soma_assets'):
            yield base / 'third_party/soma/assets' / Path(*rel.parts[2:])
    if name == YOLOX_ONNX:
        yield Path.home() / '.cache/rtmlib/hub/checkpoints/yolox_x_8xb8-300e_humanart-a39d44ed.onnx'


def fetch_models(component, models_from=None, files=MODEL_FILES):
    from ..local_image.downloads import download
    for name, (url, size, sha256) in files.items():
        target = component / name
        if target.is_file() and target.stat().st_size == size and digest(target) == sha256:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = next((p for p in candidates(models_from, name) if p.is_file()), None) if models_from else None
        pending = target.with_name(target.name + '.installing')
        if source and source.stat().st_size == size and digest(source) == sha256:
            print(f'复制 {name} …', flush=True)
            shutil.copyfile(source, pending)
        elif name == YOLOX_ONNX:
            print('下载 YOLOX …', flush=True)
            with tempfile.TemporaryDirectory(prefix='pose-capture-yolox-') as temp:
                archive = download(YOLOX_ZIP['url'], Path(temp) / 'yolox.zip', size=YOLOX_ZIP['size'], sha256_value=YOLOX_ZIP['sha256'])
                with zipfile.ZipFile(archive) as bundle, bundle.open(YOLOX_ZIP['member']) as member, pending.open('wb') as out:
                    shutil.copyfileobj(member, out, 16 * 1024 * 1024)
        else:
            print(f'下载 {name} …', flush=True)
            download(url, pending.with_name(target.name + '.download'), size=size, sha256_value=sha256,
                     progress=lambda done, total: print(f'\r  {done / 1e6:.0f} / {total / 1e6:.0f} MB', end='', flush=True))
            print(flush=True)
            pending.with_name(target.name + '.download').replace(pending)
        if pending.stat().st_size != size or digest(pending) != sha256:
            pending.unlink(missing_ok=True)
            raise SystemExit(f'模型校验失败：{name}')
        pending.replace(target)


def pinned(requirements_name):
    """{normalised package name: version} of one of this directory's requirements files."""
    lines = Path(__file__).with_name(requirements_name).read_text().splitlines()
    return dict((name.lower().replace('_', '-'), version) for name, version in
                (line.split('==', 1) for line in lines if line and not line.startswith('#')))


def install_dependencies(requirements_name='requirements-py314.txt', prebuild=('antlr4-python3-runtime==4.9.3',)):
    """Install one requirements file with every other package of the environment locked at its version. Packages the
    file itself pins may move to the pinned version (an earlier install's timm 0.6.7 becomes 1.0.13)."""
    own = set(pinned(requirements_name))
    baseline = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()
                if d.metadata['Name'].lower().replace('_', '-') not in own}
    requirements = Path(__file__).with_name(requirements_name)
    with tempfile.TemporaryDirectory(prefix='pose-capture-install-') as temp:
        constraints = Path(temp) / 'constraints.txt'
        constraints.write_text(''.join(f'{name}=={version}\n' for name, version in sorted(baseline.items())))
        wheels = Path(temp) / 'wheels'
        wheels.mkdir()
        if prebuild:
            subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--disable-pip-version-check', '-w', str(wheels),
                            *prebuild], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--disable-pip-version-check',
                        '--find-links', str(wheels), '-c', str(constraints), '-r', str(requirements)], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    changed = [name for name, version in baseline.items() if importlib.metadata.version(name) != version]
    if changed:
        raise SystemExit('原依赖意外变化：' + ', '.join(changed))
    return digest(requirements)


def self_test(component):
    """Load the engine once in a child process (the HTTP process never imports it)."""
    project = Path(__file__).resolve().parents[2]
    code = ('import sys,json; sys.path.insert(0, sys.argv[1]); from backend.pose_capture.engine import PhotoEngine;'
            'from backend.pose_capture.contracts import YOLOX_ONNX; from pathlib import Path; import numpy as np;'
            'c=Path(sys.argv[2]); e=PhotoEngine(c/"gemx", c/YOLOX_ONNX);'
            'r=e.recognize(np.full((480,640,3),128,np.uint8)); print("SELFTEST", json.dumps({"people": len(r["people"]), "joints": len(e.joint_names)}))')
    env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TORCH_HOME': str(component / 'cache' / 'torch')}
    result = subprocess.run([sys.executable, '-c', code, str(project), str(component)], capture_output=True, text=True, env=env)
    line = next((l for l in result.stdout.splitlines() if l.startswith('SELFTEST ')), '')
    if result.returncode or not line or json.loads(line[9:])['joints'] != 77:
        raise SystemExit('识别引擎自检失败：\n' + (result.stderr or result.stdout)[-3000:])
    return json.loads(line[9:])


def prepare_video(component):
    """Build the folded VitPose and precompile the CoreML caches in a child process, printing a heartbeat."""
    from . import accel
    from .contracts import YOLOX_ONNX
    if not accel.coreml_available():
        print('此环境没有 CoreML，影片识别将使用较慢的 CPU 设置。', flush=True)
        return {'backend': 'cpu'}
    folded = component / accel.VITPOSE_FOLDED
    if not folded.is_file():
        print('生成固定批次的 VitPose（约 1 分钟）…', flush=True)
        accel.build_vitpose_batch(component)
    video = {'backend': 'coreml', 'ort': accel.runtime_version(), 'yolox_sha256': digest(component / YOLOX_ONNX),
             'vitpose_sha256': digest(folded)}
    project = Path(__file__).resolve().parents[2]
    code = ('import sys,json; sys.path.insert(0, sys.argv[1]); from backend.pose_capture import accel;'
            'accel.sessions(sys.argv[2], json.loads(sys.argv[3])); print("COMPILED")')
    print('预编译 CoreML（只需一次，约 14 分钟）…', flush=True)
    started = time.time()
    child = subprocess.Popen([sys.executable, '-c', code, str(project), str(component), json.dumps(video)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while child.poll() is None:
        try:
            child.wait(timeout=60)
        except subprocess.TimeoutExpired:
            print(f'  CoreML 编译中 … {int((time.time() - started) // 60)} 分钟', flush=True)
    out, err = child.communicate()
    if child.returncode or 'COMPILED' not in out:
        raise SystemExit('CoreML 预编译失败：\n' + (err or out)[-3000:])
    if not accel.ready(component, video):
        raise SystemExit('CoreML 缓存未生成，请重试安装')
    video['compiled_seconds'] = round(time.time() - started)
    return video


def prepare_evidence(component, models_from=None):
    """SAM 3D Body image evidence: pinned code, verified weights and packages, then one load in a child process."""
    local = Path(models_from) / 'third_party' / 'sam-3d-body' if models_from else None
    print('获取 SAM 3D Body 与 DINOv3 源码 …', flush=True)
    checkout(component / SAM3DB_DIR, local if local and (local / '.git').exists() else SAM3DB_REPO, SAM3DB_COMMIT)
    checkout(component / DINOV3_DIR, DINOV3_REPO, DINOV3_COMMIT)
    fetch_models(component, models_from, EVIDENCE_FILES)
    requirements_sha256 = install_dependencies('requirements-evidence-py314.txt', prebuild=())
    print('自检影像证据（载入约 15 秒）…', flush=True)
    project = Path(__file__).resolve().parents[2]
    code = ('import sys,json,time; sys.path.insert(0, sys.argv[1]); import numpy as np; from pathlib import Path;'
            'from backend.pose_capture.evidence import Evidence; t=time.time(); e=Evidence(Path(sys.argv[2])); load=time.time()-t;'
            'o=e.observe(np.full((480,360,3),128,np.uint8), [40,20,320,470]);'
            'print("SELFTEST", json.dumps({"device": e.device, "load_seconds": round(load,1), "keypoints": None if o is None else len(o["k3d"])}))')
    result = subprocess.run([sys.executable, '-c', code, str(project), str(component)], capture_output=True, text=True,
                            env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TORCH_HOME': str(component / 'cache' / 'torch')})
    line = next((l for l in result.stdout.splitlines() if l.startswith('SELFTEST ')), '')
    if result.returncode or not line or json.loads(line[9:])['keypoints'] != 70:
        raise SystemExit('影像证据自检失败：\n' + (result.stderr or result.stdout)[-3000:])
    check = json.loads(line[9:])
    return {'engine': EVIDENCE_ENGINE, 'commit': SAM3DB_COMMIT, 'dinov3': DINOV3_COMMIT, 'files': {k: v[2] for k, v in EVIDENCE_FILES.items()},
            'requirements_sha256': requirements_sha256, 'device': check['device'], 'self_test': check}


def fetch_comotion_checkpoints(component, comotion_from=None):
    """The checkpoint files COMOTION_FILES lists without a URL: copied from a CoMotion checkout when given and verified,
    otherwise taken out of Apple's archive (downloaded once to a temporary directory and verified; each member's
    size and SHA-256 are checked)."""
    import tarfile
    from ..local_image.downloads import download
    wanted = {name: entry for name, entry in COMOTION_FILES.items() if entry[0] is None}
    pending = {}
    for name, (_, size, sha256) in wanted.items():
        target = component / name
        if target.is_file() and target.stat().st_size == size and digest(target) == sha256:
            continue
        source = Path(comotion_from) / 'src/comotion_demo/data' / Path(name).name if comotion_from else None
        target.parent.mkdir(parents=True, exist_ok=True)
        if source and source.is_file() and source.stat().st_size == size and digest(source) == sha256:
            print(f'复制 {Path(name).name} …', flush=True)
            shutil.copyfile(source, target.with_name(target.name + '.installing'))
            target.with_name(target.name + '.installing').replace(target)
        else:
            pending[Path(name).name] = (target, size, sha256)
    if not pending:
        return
    print('下载 CoMotion 模型（2.3 GB）…', flush=True)
    with tempfile.TemporaryDirectory(prefix='pose-capture-comotion-') as temp:
        archive = download(COMOTION_ARCHIVE['url'], Path(temp) / 'checkpoints.tar.gz', size=COMOTION_ARCHIVE['size'],
                           sha256_value=COMOTION_ARCHIVE['sha256'],
                           progress=lambda done, total: print(f'\r  {done / 1e6:.0f} / {total / 1e6:.0f} MB', end='', flush=True))
        print(flush=True)
        with tarfile.open(archive) as bundle:
            for member in bundle:
                entry = pending.get(Path(member.name).name)
                if entry is None or not member.isfile():
                    continue
                target, size, sha256 = entry
                part = target.with_name(target.name + '.installing')
                with bundle.extractfile(member) as stream, part.open('wb') as out:
                    shutil.copyfileobj(stream, out, 16 * 1024 * 1024)
                if part.stat().st_size != size or digest(part) != sha256:
                    part.unlink(missing_ok=True)
                    raise SystemExit(f'模型校验失败：{target.name}')
                part.replace(target)
                del pending[Path(member.name).name]
    if pending:
        raise SystemExit('CoMotion 模型包缺少：' + ', '.join(sorted(pending)))


def prepare_comotion(component, comotion_from=None):
    """CoMotion tracking: pinned code, verified checkpoints and SMPL files, pinned packages, then one load on MPS and
    a short synthetic clip in a child process."""
    local = Path(comotion_from) if comotion_from and (Path(comotion_from) / '.git').exists() else None
    print('获取 CoMotion 源码 …', flush=True)
    checkout(component / COMOTION_DIR, local or COMOTION_REPO, COMOTION_COMMIT)
    fetch_comotion_checkpoints(component, comotion_from)
    fetch_models(component, files={name: entry for name, entry in COMOTION_FILES.items() if entry[0] is not None})
    requirements_sha256 = install_dependencies('requirements-comotion-py314.txt', prebuild=())
    print('自检 CoMotion（载入约 10 秒）…', flush=True)
    project = Path(__file__).resolve().parents[2]
    code = ('import sys,json; sys.path.insert(0, sys.argv[1]); from pathlib import Path;'
            'from backend.pose_capture.comotion import self_test; print("SELFTEST", json.dumps(self_test(Path(sys.argv[2]))))')
    result = subprocess.run([sys.executable, '-c', code, str(project), str(component)], capture_output=True, text=True,
                            env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TORCH_HOME': str(component / 'cache' / 'torch')})
    line = next((l for l in result.stdout.splitlines() if l.startswith('SELFTEST ')), '')
    if result.returncode or not line or json.loads(line[9:]).get('frames') is None:
        raise SystemExit('CoMotion 自检失败：\n' + (result.stderr or result.stdout)[-3000:])
    check = json.loads(line[9:])
    return {'engine': COMOTION_ENGINE, 'commit': COMOTION_COMMIT, 'files': {k: v[2] for k, v in COMOTION_FILES.items()},
            'requirements_sha256': requirements_sha256, 'device': check['device'], 'self_test': check}


def write_receipt(component, receipt):
    pending = component / 'installed.json.installing'
    pending.write_text(json.dumps(receipt, indent=2))
    pending.replace(component / 'installed.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--models-from', type=Path, help='已有 GEM-X 目录（含 inputs/），文件逐一校验后复制')
    parser.add_argument('--source-from', help='GEM-X 源码仓库（默认 GitHub）；必须包含固定 commit')
    parser.add_argument('--component', type=Path, default=DEFAULT_ROOT / 'components' / 'pose-capture')
    parser.add_argument('--skip-video', action='store_true', help='只安装照片识别（不生成 CoreML 缓存）')
    parser.add_argument('--skip-evidence', action='store_true', help='影片识别不安装 SAM 3D Body 影像证据（少 2.8 GB）')
    parser.add_argument('--evidence-only', action='store_true', help='只为已安装的引擎补装影像证据')
    parser.add_argument('--skip-comotion', action='store_true', help='影片不安装 CoMotion 多人追踪（沿用 YOLOX + ByteTrack）')
    parser.add_argument('--comotion-only', action='store_true', help='只为已安装的引擎补装 CoMotion 多人追踪')
    parser.add_argument('--comotion-from', type=Path, help='已有 CoMotion 目录（含 src/comotion_demo/data/），模型逐一校验后复制')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 14) or sys.prefix == sys.base_prefix or platform.system() != 'Darwin':
        raise SystemExit('请在现有 macOS Python 3.14 虚拟环境中安装')
    component = args.component.resolve()
    component.mkdir(parents=True, exist_ok=True)
    if args.evidence_only:
        try:
            receipt = json.loads((component / 'installed.json').read_text())
        except (OSError, ValueError):
            raise SystemExit('尚未安装姿态识别引擎，请先运行完整安装') from None
        receipt['evidence'] = prepare_evidence(component, args.models_from)
        write_receipt(component, receipt)
        print('影像证据已安装（SAM 3D Body，' + receipt['evidence']['device'].upper() + '）。')
        return
    if args.comotion_only:
        try:
            receipt = json.loads((component / 'installed.json').read_text())
        except (OSError, ValueError):
            raise SystemExit('尚未安装姿态识别引擎，请先运行完整安装') from None
        receipt['comotion'] = prepare_comotion(component, args.comotion_from)
        write_receipt(component, receipt)
        print('CoMotion 多人追踪已安装（' + receipt['comotion']['device'].upper() + '）。')
        return
    print('获取 GEM-X 源码 …', flush=True)
    fetch_source(component, args.source_from)
    fetch_models(component, args.models_from)
    requirements_sha256 = install_dependencies()
    print('自检识别引擎 …', flush=True)
    check = self_test(component)
    video = None if args.skip_video else prepare_video(component)
    evidence = None if args.skip_video or args.skip_evidence else prepare_evidence(component, args.models_from)
    comotion = None if args.skip_video or args.skip_comotion else prepare_comotion(component, args.comotion_from)
    receipt = {'engine': ENGINE, 'commit': GEMX_COMMIT, 'files': {k: v[2] for k, v in MODEL_FILES.items()},
               'requirements_sha256': requirements_sha256, 'self_test': check, 'video': video, 'evidence': evidence,
               'comotion': comotion, 'installed_at': time.time()}
    write_receipt(component, receipt)
    print('姿态识别引擎已安装（GEM-X 精简版）：照片' + ('' if video is None else '、影片（' + ('CoreML' if video['backend'] == 'coreml' else 'CPU') + '）')
          + '识别' + ('' if evidence is None else '，含影像证据（SAM 3D Body）') + ('' if comotion is None else '与 CoMotion 多人追踪') + '。')


if __name__ == '__main__':
    main()
