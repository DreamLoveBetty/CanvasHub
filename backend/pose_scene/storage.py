"""Exported pose reference images: data/pose/exports/YYYY-MM-DD/<id>.png plus a JSON sidecar.

The sidecar keeps the pass, camera, size and the scene snapshot so an export stays recoverable
and reproducible without the canvas.
"""
import json
from pathlib import Path
import time
import uuid

from .contracts import identifier


class ExportStore:
    def __init__(self, root):
        self.root = Path(root)

    def save(self, export):
        ident = uuid.uuid4().hex
        folder = self.root / time.strftime('%Y-%m-%d')
        folder.mkdir(parents=True, exist_ok=True)
        image = folder / f'{ident}.png'
        pending = folder / f'{ident}.png.saving'
        pending.write_bytes(export['data'])
        pending.replace(image)
        meta = {'id': ident, 'pass': export['pass'], 'camera': export['camera'], 'width': export['width'],
                'height': export['height'], 'bytes': len(export['data']), 'created_at': time.time(),
                'scene': export['scene']}
        image.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False))
        return {key: meta[key] for key in ('id', 'pass', 'camera', 'width', 'height')}

    def path(self, ident):
        identifier(ident)
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir(), reverse=True):
                image = folder / f'{ident}.png'
                if folder.is_dir() and not folder.is_symlink() and image.is_file() and not image.is_symlink():
                    return image
        raise FileNotFoundError('姿态导出图不存在')
