"""Recognised body shapes as mannequins: a GEM-X (MHR) identity -> SOMA low-mesh GLB, content-addressed.

`BodyBuilder` runs only in the worker (torch, py-soma-x); `BodyStore` and `body_id` are numpy/stdlib only,
so the HTTP process can validate ids and serve files. Bodies live in `data/pose-capture/bodies/<id>.glb`
and are shared by every job that recognises the same identity. MHR ships only the low mesh here
(its mid model is ~700 MB), so recognised bodies render with the 4,505-vertex mesh.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np

from ..pose_scene.contracts import GLB_VERSION, SOMA_FILES
from .scene import MANNEQUIN_HEIGHT

MHR_DIR = 'gemx/inputs/soma_assets/MHR'  # inside the pose-capture component


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('无效识别体型标识')
    return value


def body_id(identity_coeffs, scale_params):
    """Stable id for an identity: rounded coefficients plus the GLB format version."""
    values = np.round(np.r_[np.asarray(identity_coeffs, dtype=np.float64).ravel(),
                            np.asarray(scale_params, dtype=np.float64).ravel()[1:]], 4).astype('<f4')
    return hashlib.sha256(f'mhr-low-v{GLB_VERSION}:'.encode() + values.tobytes()).hexdigest()[:32]


class BodyStore:
    def __init__(self, root):
        self.root = Path(root)

    def target(self, ident):
        return self.root / f'{identifier(ident)}.glb'

    def path(self, ident):
        path = self.target(ident)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError('识别体型不存在')
        return path

    def write(self, ident, data):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.target(ident)
        pending = path.with_suffix('.glb.writing')
        pending.write_bytes(data)
        os.replace(pending, path)
        return path


class BodyBuilder:
    """Lazily loads the SOMA MHR identity layer (SOMA v0.3.4 assets + the engine's MHR files)."""

    def __init__(self, soma_assets, mhr_dir):
        self.soma_assets, self.mhr_dir = Path(soma_assets), Path(mhr_dir)
        self._layer = self._root = None

    def _ensure(self):
        if self._layer is not None:
            return self._layer
        from ..pose_scene.convert import soma_layer
        # SOMALayer reads every asset from one data root: link the pinned SOMA files and the MHR folder.
        self._root = Path(tempfile.mkdtemp(prefix='pose-capture-bodies-'))
        for name in SOMA_FILES:
            if '/' not in name:
                (self._root / name).symlink_to(self.soma_assets / name)
        (self._root / 'MHR').symlink_to(self.mhr_dir, target_is_directory=True)
        self._layer = soma_layer(self._root, 'mhr', 'low')
        return self._layer

    def build(self, identity_coeffs, scale_params):
        import torch
        from ..pose_scene.convert import rest_height, rig_arrays
        from ..pose_scene.glb import build_glb
        layer = self._ensure()
        # GEM-X scale_params = [global scale, 68 MHR body-part scales]. Overall size is the character's
        # height_cm, so only the body-part proportions shape the mannequin.
        with torch.no_grad():
            layer.prepare_identity(torch.as_tensor(np.asarray(identity_coeffs), dtype=torch.float32).reshape(1, -1),
                                   torch.as_tensor(np.asarray(scale_params)[1:], dtype=torch.float32).reshape(1, -1))
            rig = rig_arrays(layer, 'low')
        height = rest_height(rig)
        rig.update(body='capture', head_end=height, height_ratio=height / MANNEQUIN_HEIGHT)
        return build_glb(rig)

    def close(self):
        if self._root:
            shutil.rmtree(self._root, ignore_errors=True)
        self._layer = self._root = None
