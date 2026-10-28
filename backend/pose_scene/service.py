"""Pose scene service: mannequin availability, GLB lookup, image export storage and pose video encoding.

No local paths leave this module; callers get URLs and status flags only.
"""
import json
from pathlib import Path

from .contracts import BODIES, BODY_LABELS, GLB_VERSION, LODS, SOMA_RELEASE, body, glb_name, lod, normalize_export
from .storage import ExportStore
from .video_export import VideoExports

INSTALL_COMMAND = '.venv/bin/python -m backend.pose_scene.install'


class PoseSceneService:
    def __init__(self, component_root, data_root, output_dir=None):
        """output_dir(): today's image-archive folder; pose videos land there (None disables video export)."""
        self.component = Path(component_root)
        self.exports = ExportStore(Path(data_root) / 'exports')
        self.videos = VideoExports(Path(data_root) / 'videos', output_dir) if output_dir else None

    def _receipt(self):
        try:
            receipt = json.loads((self.component / 'installed.json').read_text())
        except (OSError, ValueError):
            return None
        return receipt if isinstance(receipt, dict) else None

    def status(self):
        receipt = self._receipt()
        missing = [level for level in LODS if not all((self.component / 'glb' / glb_name(level, kind)).is_file() for kind in BODIES)]
        if not receipt:
            state, message = 'missing', '姿态人偶尚未安装'
        elif receipt.get('glb_version') != GLB_VERSION or receipt.get('release') != SOMA_RELEASE:
            state, message = 'outdated', '姿态人偶版本过旧，请重新运行安装'
        elif missing:
            state, message = 'incomplete', '人偶文件缺失，请重新运行安装'
        else:
            state, message = 'ready', ''
        lods = receipt.get('lods', {}) if receipt else {}
        return {'state': state, 'ready': state == 'ready', 'message': message, 'release': SOMA_RELEASE,
                'glb_version': GLB_VERSION, 'install_command': INSTALL_COMMAND,
                'bodies': [{'id': kind, 'label': BODY_LABELS[kind]} for kind in BODIES],
                'lods': {level: {'vertices': int(lods.get(level, {}).get('vertices') or 0)} for level in LODS if level not in missing}}

    def assets_dir(self):
        """The verified SOMA assets for other local domains (recognised bodies), or None until installed."""
        return (self.component / 'assets').resolve() if self.status()['ready'] else None

    def glb(self, level, kind='neutral'):
        if not self.status()['ready']:
            raise RuntimeError('姿态人偶尚未安装')
        path = self.component / 'glb' / glb_name(lod(level), body(kind))
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError('人偶文件不存在')
        return path

    def save_export(self, body):
        saved = self.exports.save(normalize_export(body))
        saved['url'] = '/api/pose/export/artifact?id=' + saved['id']
        return saved

    def export_path(self, ident):
        return self.exports.path(ident)

    def video(self, action, body=None, ident=None, index=None, data=None):
        if self.videos is None:
            raise RuntimeError('姿态视频导出未启用')
        if action == 'start':
            return self.videos.start(body)
        if action == 'frame':
            return self.videos.frame(ident, index, data)
        return {'finish': self.videos.finish, 'cancel': self.videos.cancel, 'job': self.videos.job}[action](ident)
