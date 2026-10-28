"""Generate the SOMA mannequins (neutral / female / male, low and mid GLB). Runs in a subprocess at install time only.

The HTTP process never imports this module: it needs py-soma-x, torch, warp and anny.
Usage: .venv/bin/python -m backend.pose_scene.convert --assets DIR --out DIR

`rig_arrays` and `rest_height` are shared with the pose-capture worker, which builds mannequins from
recognised (MHR) identities the same way.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from .contracts import ANNY_PRESETS, BODIES, GLB_VERSION, LODS, SOMA_RELEASE, glb_name
from .glb import build_glb


def soma_layer(assets, kind, level):
    from soma import SOMALayer
    # Legacy mode = the 78-joint skeleton with plain LBS, which is what glTF skinning can express.
    return SOMALayer(data_root=Path(assets), device='cpu', identity_model_type=kind, mode='dense', lod=level,
                     enable_procedural_transforms=False)


def rig_arrays(layer, level):
    """Arrays for build_glb from a SOMALayer whose identity is already prepared."""
    import numpy as np
    skinning = layer.batched_skinning
    parents = np.asarray(skinning.joint_parent_ids, dtype=np.int64)
    parents[0] = -1  # SOMA marks the virtual Root as its own parent
    return {
        'names': [str(n) for n in layer.public_joint_names], 'parents': parents,
        'bind_world': skinning.bind_world_transforms[0].double().numpy(),
        'orient': layer._t_pose_orient.double().numpy(),
        'rest': layer._cached_rest_shape[0].double().numpy(),
        'faces': layer.faces.numpy().astype(np.int64),
        'weights': skinning.skinning_weights.double().numpy(),
        'glb_version': GLB_VERSION, 'release': SOMA_RELEASE, 'lod': level,
    }


def rest_height(rig):
    """HeadEnd above the lowest public joint in the rest pose (m): the measure height_cm is scaled by."""
    names = list(rig['names'])
    joints = rig['bind_world'][1:, 1, 3]  # skip the virtual Root
    return float(rig['bind_world'][names.index('HeadEnd'), 1, 3] - joints.min())


def preset_rigs(assets, level):
    """(body, rig) for every preset at one level of detail; neutral first."""
    import torch
    torch.set_grad_enabled(False)
    neutral = soma_layer(assets, 'soma', level)
    neutral.prepare_identity(torch.zeros(1, neutral.num_shape_components))
    yield 'neutral', rig_arrays(neutral, level)
    anny = soma_layer(assets, 'anny', level)
    labels = list(anny.identity_model.identity_model.phenotype_labels)
    for kind in BODIES[1:]:
        coeffs = torch.full((1, len(labels)), 0.5)
        for name, value in ANNY_PRESETS[kind].items():
            coeffs[0, labels.index(name)] = value
        anny.prepare_identity(coeffs, torch.zeros(1, anny.num_scale_params))
        yield kind, rig_arrays(anny, level)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    # Anny caches ~1 GB of rebuildable model data; keep it out of the user's home and drop it afterwards.
    cache = Path(tempfile.mkdtemp(prefix='pose-scene-anny-'))
    os.environ['ANNY_CACHE_DIR'] = str(cache)
    try:
        for level in LODS:
            reference = None
            for kind, rig in preset_rigs(args.assets, level):
                height = rest_height(rig)
                reference = reference or height
                rig.update(body=kind, head_end=height, height_ratio=height / reference)
                data = build_glb(rig)
                target = args.out / glb_name(level, kind)
                pending = target.with_suffix('.glb.installing')
                pending.write_bytes(data)
                os.replace(pending, target)
                summary.setdefault(level, {'vertices': int(len(rig['rest'])), 'joints': len(rig['names']), 'bodies': {}})
                summary[level]['bodies'][kind] = {'bytes': len(data), 'head_end': round(height, 4)}
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
