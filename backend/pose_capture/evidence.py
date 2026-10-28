"""Image evidence for video recognition (worker only; docs/POSE_REFERENCE_REBUILD_PLAN.md §22).

GEM-X lite lifts 2D keypoints without looking at the image, so it cannot tell a hand resting on the hip
from one floating in front of the belly (a push-in clip put the akimbo wrist 10-24 cm in front of the
body). SAM 3D Body reads the frame and gets that depth, and the grip of the fingers, right; its 2D
placement is less exact than VitPose's. So it supplies only relative 3D: each arm joint's depth relative
to the pelvis and each finger joint's offset from its wrist, scaled to the recognised skeleton, while
VitPose keeps the 2D and refine.fit_sequence merges both; video._fit keeps the evidence only on keyframes
where it does not cost 2D accuracy.

Evidence(component) loads SAM 3D Body (pinned submodule, local DINOv3 code, 2.8 GB of weights) with its
image backbone on Apple's GPU (MPS) and the rest on the CPU: the MHR head computes in float64, which MPS
lacks, and the backbone is 98 % of the time (1.7 s a frame in full mode instead of 43 s on the CPU).
targets() turns observations into fit targets; it is plain numpy and needs no model. body_shape() takes the person's
body shape from them: SAM 3D Body reads it from the image in the same MHR identity space GEM-X uses, where GEM-X,
seeing only keypoints, made a woman in a coat and a slim man into heavy-bellied men.
"""
import contextlib
from pathlib import Path
import sys

import numpy as np

from .contracts import DINOV3_DIR, EVIDENCE_CHECKPOINT, EVIDENCE_MHR, SAM3DB_DIR
from .scene import VISIBLE

AGREE = 0.10        # SAM 3D Body's 2D within this fraction of the person box of VitPose's, or the joint is skipped
HAND_AGREE = 0.5    # a finger's 2D offset from the wrist within this fraction of the hand's size of VitPose's
GAP_SECONDS = 0.6   # evidence is interpolated between sampled frames at most this far apart
SHAPE_FRAMES = 3    # observations needed before SAM 3D Body's body shape replaces GEM-X's

# MHR70 keypoints (sam_3d_body/metadata/mhr70.py) for the SOMA joints the evidence speaks to.
PELVIS = (9, 10)        # left-hip, right-hip
SHOULDERS = (5, 6)
ARM = {'LeftArm': 5, 'RightArm': 6, 'LeftForeArm': 7, 'RightForeArm': 8, 'LeftHand': 62, 'RightHand': 41}
WRIST = {'Left': 62, 'Right': 41}
# Per finger MHR70 lists tip, first (distal), second, third (proximal) joint; SOMA's chain is 1 (palm) .. End.
_FIRST = {'Left': {'Thumb': 42, 'Index': 46, 'Middle': 50, 'Ring': 54, 'Pinky': 58},
          'Right': {'Thumb': 21, 'Index': 25, 'Middle': 29, 'Ring': 33, 'Pinky': 37}}
FINGERS = {}
for _side, _starts in _FIRST.items():
    for _finger, _tip in _starts.items():
        chain = ('End', '3', '2', '1') if _finger == 'Thumb' else ('End', '4', '3', '2')
        for _offset, _suffix in enumerate(chain):
            FINGERS[f'{_side}Hand{_finger}{_suffix}'] = (_tip + _offset, f'{_side}Hand')


class Evidence:
    def __init__(self, component, device=None):
        import torch
        component = Path(component)
        self.device = device or ('mps' if torch.backends.mps.is_available() else 'cpu')
        if str(component / SAM3DB_DIR) not in sys.path:
            sys.path.insert(0, str(component / SAM3DB_DIR))
        if not torch.cuda.is_available():
            # Two inference paths call `.cuda()` on index tensors; without CUDA they belong on the CPU.
            torch.Tensor.cuda = lambda self, *a, **k: self.to('cpu')
            torch.nn.Module.cuda = lambda self, *a, **k: self.to('cpu')
        import sam_3d_body.models.meta_arch.sam3d_body as arch
        import sam_3d_body.sam_3d_body_estimator as estimator
        from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
        from sam_3d_body.utils.dist import recursive_to
        # Batches are sent to "cuda" by name in three places.
        estimator.recursive_to = arch.recursive_to = lambda x, target: recursive_to(x, 'cpu' if target == 'cuda' else target)
        hub_load = torch.hub.load

        def local_hub(repo, name, *args, source='github', **kwargs):
            if repo == 'facebookresearch/dinov3':  # upstream follows GitHub main; the install pins a checkout
                return hub_load(str(component / DINOV3_DIR), name, *args, source='local', **kwargs)
            return hub_load(repo, name, *args, source=source, **kwargs)
        torch.hub.load = local_hub
        with contextlib.redirect_stdout(sys.stderr):  # its prints must not reach the JSON-lines channel
            try:
                model, cfg = load_sam_3d_body(str(component / EVIDENCE_CHECKPOINT), device=torch.device('cpu'),
                                              mhr_path=str(component / EVIDENCE_MHR))
            finally:
                torch.hub.load = hub_load
        model.eval()
        if self.device != 'cpu':
            target = torch.device(self.device)
            backbone = model.backbone.to(target, torch.float32)  # the checkpoint keeps some backbone tensors in bfloat16
            inner = backbone.forward

            def move(x, dev):
                if torch.is_tensor(x):
                    return x.to(dev, torch.float32) if x.is_floating_point() else x.to(dev)
                if isinstance(x, (list, tuple)):
                    return type(x)(move(v, dev) for v in x)
                if isinstance(x, dict):
                    return {k: move(v, dev) for k, v in x.items()}
                return x

            def forward(*args, **kwargs):
                out = inner(*move(args, target), **move(kwargs, target))
                return move(out, torch.device('cpu'))
            backbone.forward = forward
        self.estimator = SAM3DBodyEstimator(model, cfg)

    def features(self, images, boxes_xys, batch_size=16):
        """GEM-X's image condition, as its own extractor makes it: SAM 3D Body's primary body token (N, 1024) and
        camera translation (N, 3) for RGB images with square boxes (N, 3) [cx, cy, side]; body decoder only."""
        import torch
        from sam_3d_body.data.utils.prepare_batch import prepare_batch
        model = self.estimator.model
        if not getattr(self, '_tokens_exposed', False):
            from gem.utils.sam3db_extractor import SAM3DBExtractor
            extractor = SAM3DBExtractor.__new__(SAM3DBExtractor)
            extractor.estimator = self.estimator
            extractor._patch_model_to_expose_pose_token()  # adds 'pose_token' to the body branch's output
            self._tokens_exposed = True
        cfg = model.cfg
        hand = cfg.MODEL.DECODER.get('DO_HAND_DETECT_TOKENS', False)
        cfg.defrost(); cfg.MODEL.DECODER.DO_HAND_DETECT_TOKENS = False; cfg.freeze()  # one body token, as GEM-X was trained
        tokens, transls = [], []
        try:
            for start in range(0, len(images), batch_size):
                parts = []
                for image, (cx, cy, side) in zip(images[start:start + batch_size], boxes_xys[start:start + batch_size]):
                    box = np.array([[cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2]], dtype=np.float32)
                    parts.append(prepare_batch(np.ascontiguousarray(image), self.estimator.transform, box, masks=None, masks_score=None))
                batch = {}
                for key, first in parts[0].items():
                    if torch.is_tensor(first):
                        batch[key] = torch.cat([p[key] for p in parts])
                    elif isinstance(first, np.ndarray):
                        batch[key] = np.concatenate([p[key] for p in parts])
                    else:
                        batch[key] = [p[key] for p in parts]
                model._initialize_batch(batch)
                with torch.no_grad(), contextlib.redirect_stdout(sys.stderr):
                    out = model.forward_step(batch, decoder_type='body')
                token = out['pose_token'].detach().float().cpu()
                tokens.append((token[:, 0] if token.ndim == 3 else token).numpy())
                transls.append(out['mhr']['pred_cam_t'].detach().float().cpu().numpy())
        finally:
            cfg.defrost(); cfg.MODEL.DECODER.DO_HAND_DETECT_TOKENS = hand; cfg.freeze()
        return np.concatenate(tokens), np.concatenate(transls)

    def observe(self, image_rgb, box_xyxy):
        """One person in one frame: {'k3d': (70, 3) camera-frame metres, 'k2d': (70, 2) image pixels, 'shape': (45,)
        MHR identity coefficients} or None."""
        with contextlib.redirect_stdout(sys.stderr):
            out = self.estimator.process_one_image(np.ascontiguousarray(image_rgb), bboxes=np.asarray([box_xyxy], dtype=np.float32),
                                                   inference_type='full')
        if not out:
            return None
        r = out[0]
        k3d = np.asarray(r['pred_keypoints_3d'], dtype=np.float64) + np.asarray(r['pred_cam_t'], dtype=np.float64)
        k2d = np.asarray(r['pred_keypoints_2d'], dtype=np.float64)[:, :2]
        shape = np.asarray(r.get('shape_params', ()), dtype=np.float64).reshape(-1)
        if k3d.shape != (70, 3) or not np.isfinite(k3d).all():
            return None
        return {'k3d': k3d, 'k2d': k2d, 'shape': shape if shape.shape == (45,) and np.isfinite(shape).all() else None}


def body_shape(observations):
    """Median SAM 3D Body identity coefficients (45,) over a person's observations, or None below SHAPE_FRAMES."""
    shapes = [o['shape'] for o in observations.values() if o is not None and o.get('shape') is not None]
    return np.median(shapes, 0) if len(shapes) >= SHAPE_FRAMES else None


def targets(observations, joints, keypoints, box_sizes, joint_names, keys, fps):
    """Fit targets for keyframe rows from SAM 3D Body observations.

    observations {row: observation}; joints (N, J, 3) the GEM-X camera-frame joints at the keyframes, used
    for scale and the pelvis reference; keypoints (N, J, 3) VitPose; box_sizes (N,); keys (N,) clip frames.
    Returns refine.fit_sequence's `evidence`: depth / depth_mask (N, J) (an arm joint's depth relative to the
    Hips joint), shape / shape_mask (N, J, 3 / J) and shape_base (J,), plus `used` {'depth', 'shape'}: the
    fraction of rows x joints that received a target.
    An arm joint gets a target only where VitPose sees it and SAM 3D Body puts it within AGREE of the same
    spot. A finger joint also needs the same hand shape in 2D: its offset from the wrist within HAND_AGREE of
    the hand's size (wrist to middle knuckle) of VitPose's, since a person-box tolerance is larger than the
    hand (an akimbo hand SAM 3D Body turned palm-on-belly kept its finger shape and fought VitPose). Rows
    between two observed rows at most GAP_SECONDS apart are interpolated.
    """
    names = list(joint_names)
    index = {n: i for i, n in enumerate(names)}
    rows, joint_count = len(joints), len(names)
    depth = np.zeros((rows, joint_count)); depth_mask = np.zeros((rows, joint_count))
    shape = np.zeros((rows, joint_count, 3)); shape_mask = np.zeros((rows, joint_count))
    base = np.arange(joint_count)
    arm = [(index[n], m) for n, m in ARM.items() if n in index]
    fingers = [(index[n], m, index[parent], WRIST[parent[:-4]]) for n, (m, parent) in FINGERS.items() if n in index and parent in index]
    for j, _, b, _ in fingers:
        base[j] = b
    pelvis_ours = [index[n] for n in ('LeftLeg', 'RightLeg') if n in index]
    shoulders_ours = [index[n] for n in ('LeftArm', 'RightArm') if n in index]
    observed = sorted(r for r, o in observations.items() if o is not None and 0 <= r < rows)
    for r in observed:
        k3d, k2d = observations[r]['k3d'], observations[r]['k2d']
        ours, kp, box = np.asarray(joints[r]), np.asarray(keypoints[r]), float(box_sizes[r]) or 1.0
        sam_pelvis, sam_shoulders = k3d[list(PELVIS)].mean(0), k3d[list(SHOULDERS)].mean(0)
        our_pelvis, our_shoulders = ours[pelvis_ours].mean(0), ours[shoulders_ours].mean(0)
        sam_torso = np.linalg.norm(sam_shoulders - sam_pelvis)
        if sam_torso < 1e-3:
            continue
        scale = np.linalg.norm(our_shoulders - our_pelvis) / sam_torso
        agrees = lambda j, m: kp[j, 2] >= VISIBLE and np.linalg.norm(k2d[m] - kp[j, :2]) <= AGREE * box
        for j, m in arm:
            if agrees(j, m):
                # depth relative to the Hips joint, as the fit's depth anchor measures it
                depth[r, j] = scale * (k3d[m, 2] - sam_pelvis[2]) + (our_pelvis[2] - ours[0, 2])
                depth_mask[r, j] = 1.0
        for j, m, b, w in fingers:
            knuckle = index.get(names[b] + 'Middle2')
            hand = np.linalg.norm(kp[knuckle, :2] - kp[b, :2]) if knuckle is not None else 0.0
            same_shape = hand > 1.0 and np.linalg.norm((k2d[m] - k2d[w]) - (kp[j, :2] - kp[b, :2])) <= HAND_AGREE * hand
            if agrees(j, m) and agrees(b, w) and same_shape:
                shape[r, j] = scale * (k3d[m] - k3d[w])
                shape_mask[r, j] = 1.0
    keys = np.asarray(keys, dtype=np.float64)
    for a, b in zip(observed[:-1], observed[1:]):
        if b - a < 2 or (keys[b] - keys[a]) / fps > GAP_SECONDS:
            continue
        t = ((keys[a + 1:b] - keys[a]) / (keys[b] - keys[a]))[:, None]
        both = depth_mask[a] * depth_mask[b]
        depth[a + 1:b] = ((1 - t) * depth[a] + t * depth[b]) * both
        depth_mask[a + 1:b] = both
        both = shape_mask[a] * shape_mask[b]
        shape[a + 1:b] = ((1 - t)[..., None] * shape[a] + t[..., None] * shape[b]) * both[:, None]
        shape_mask[a + 1:b] = both
    used = {'depth': round(float(depth_mask[:, [j for j, _ in arm]].mean()), 3) if arm else 0.0,
            'shape': round(float(shape_mask[:, [j for j, *_ in fingers]].mean()), 3) if fingers else 0.0}
    return {'depth': depth, 'depth_mask': depth_mask, 'shape': shape, 'shape_mask': shape_mask, 'shape_base': base, 'used': used}
