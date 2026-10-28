"""Resident GEM-X worker supervision and install status. No inference imports in this process."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys

from ..local_image.runtime import JsonLineRuntime
from . import accel
from .contracts import (COMOTION_DIR, COMOTION_ENGINE, COMOTION_FILES, DINOV3_DIR, ENGINE, EVIDENCE_ENGINE, EVIDENCE_FILES, GEMX_COMMIT,
                        MAX_PEOPLE, MAX_SECONDS, MAX_VIDEO_PEOPLE, MODEL_FILES, SAM3DB_DIR)
from .worker import PREFIX

INSTALL_COMMAND = '.venv/bin/python -m backend.pose_capture.install'
# POSE_CAPTURE_TRACKER=detector keeps video on YOLOX + ByteTrack even with CoMotion installed (operations / comparison).
TRACKER_ENV = 'POSE_CAPTURE_TRACKER'


class PoseCaptureError(RuntimeError):
    pass


class PoseCaptureCancelled(PoseCaptureError):
    pass


class Runtime(JsonLineRuntime):
    def __init__(self, component, timeout=600, idle_seconds=600, before_load=None):
        super().__init__(component, worker=Path(__file__).with_name('worker.py'), label='姿态识别', prefix=PREFIX,
                         error=PoseCaptureError, cancelled_error=PoseCaptureCancelled, before_load=before_load,
                         timeout=timeout, idle_seconds=idle_seconds)

    @property
    def python(self):
        return None if getattr(sys, 'frozen', False) else Path(sys.executable).absolute()

    def child_environment(self):
        return {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONUNBUFFERED': '1',
                'TORCH_HOME': str(self.root / 'cache' / 'torch'), 'HF_HOME': str(self.root / 'cache' / 'huggingface')}

    def _receipt(self):
        try:
            receipt = json.loads((self.root / 'installed.json').read_text())
        except (OSError, ValueError):
            return None
        return receipt if isinstance(receipt, dict) else None

    @staticmethod
    def _packages(name):
        expected = dict(line.split('==', 1) for line in Path(__file__).with_name(name).read_text().splitlines()
                        if line and not line.startswith('#'))
        try:
            return all(importlib.metadata.version(package) == version for package, version in expected.items())
        except importlib.metadata.PackageNotFoundError:
            return False

    def _missing(self, files):
        return [name for name, (_, size, _) in files.items()
                if not (self.root / name).is_file() or (self.root / name).stat().st_size != size]

    def _evidence(self, receipt, video):
        """Whether SAM 3D Body image evidence can run, and why not."""
        entry = (receipt or {}).get('evidence')
        if not video:
            return False, '影像证据需要先装好影片识别'
        if not entry:
            return False, '影像证据未安装（运行安装时加 --evidence-only 可补装）'
        if entry.get('engine') != EVIDENCE_ENGINE:
            return False, '影像证据版本过旧，请运行安装 --evidence-only'
        if entry.get('device') != 'mps':
            return False, '这台机器没有 Apple GPU（MPS），影像证据每帧要十几秒，未启用'
        if self._missing(EVIDENCE_FILES) or not (self.root / SAM3DB_DIR / 'sam_3d_body').is_dir() or not (self.root / DINOV3_DIR / 'hubconf.py').is_file():
            return False, '影像证据的模型或源码缺失，请运行安装 --evidence-only'
        if not self._packages('requirements-evidence-py314.txt'):
            return False, '影像证据依赖与固定版本不一致，请运行安装 --evidence-only'
        return True, ''

    def _comotion(self, receipt, video):
        """Whether CoMotion tracks video people, and why not (video then uses the detector)."""
        entry = (receipt or {}).get('comotion')
        if not video:
            return False, 'CoMotion 多人追踪需要先装好影片识别'
        if os.environ.get(TRACKER_ENV) == 'detector':
            return False, f'已用 {TRACKER_ENV}=detector 关闭 CoMotion 多人追踪'
        if not entry:
            return False, 'CoMotion 多人追踪未安装（运行安装时加 --comotion-only 可补装）'
        if entry.get('engine') != COMOTION_ENGINE:
            return False, 'CoMotion 版本过旧，请运行安装 --comotion-only'
        if entry.get('device') != 'mps':
            return False, '这台机器没有 Apple GPU（MPS），CoMotion 未启用'
        if self._missing(COMOTION_FILES) or not (self.root / COMOTION_DIR / 'src' / 'comotion_demo').is_dir():
            return False, 'CoMotion 的模型或源码缺失，请运行安装 --comotion-only'
        if not self._packages('requirements-comotion-py314.txt'):
            return False, 'CoMotion 依赖与固定版本不一致，请运行安装 --comotion-only'
        return True, ''

    def status(self):
        receipt = self._receipt()
        packages = self._packages('requirements-py314.txt')
        missing = self._missing(MODEL_FILES)
        if not receipt:
            state, message = 'missing', '姿态识别引擎尚未安装'
        elif receipt.get('engine') != ENGINE or receipt.get('commit') != GEMX_COMMIT:
            state, message = 'outdated', '姿态识别引擎版本过旧，请重新运行安装'
        elif missing or not (self.root / 'gemx' / 'gem').is_dir():
            state, message = 'incomplete', '识别模型文件缺失，请重新运行安装'
        elif not packages or self.python is None:
            state, message = 'incomplete', '识别依赖与固定版本不一致，请重新运行安装'
        else:
            state, message = 'ready', ''
        video_entry = (receipt or {}).get('video')
        video = state == 'ready' and accel.ready(self.root, video_entry)
        video_message = '' if video else ('影片识别未安装（安装时用了 --skip-video）' if state == 'ready' and video_entry is None
                                          else '影片识别的 CoreML 缓存缺失或已过期，请重新运行安装' if state == 'ready' else message)
        evidence, evidence_message = self._evidence(receipt, video)
        comotion, comotion_message = self._comotion(receipt, video)
        return {'state': state, 'ready': state == 'ready', 'message': message, 'engine': 'GEM-X 精简版',
                'install_command': INSTALL_COMMAND, 'max_people': MAX_PEOPLE, 'max_video_people': MAX_VIDEO_PEOPLE,
                'max_seconds': MAX_SECONDS, 'video_backend': (video_entry or {}).get('backend') if video else None,
                'video_message': video_message, 'evidence_message': evidence_message, 'comotion_message': comotion_message,
                'modes': {'photo': state == 'ready', 'video': bool(video), 'evidence': evidence, 'comotion': comotion}}
