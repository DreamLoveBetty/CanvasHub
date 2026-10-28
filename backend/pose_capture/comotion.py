"""CoMotion multi-person tracking for video recognition (worker only; docs/POSE_REFERENCE_REBUILD_PLAN.md §32).

Apple's CoMotion (components/pose-capture/comotion, pinned in contracts) detects SMPL bodies in every frame and
follows them as tracks; it keeps people through occlusion and crossings where YOLOX + ByteTrack broke or swapped
tracks. Each track's boxes (the projected SMPL mesh) replace the detector's tracks, and each track carries its
CoMotion bodies, which comotion_pose.StartPose turns into GEM-X's starting pose. Both of its modules run on MPS
(the CPU detector takes ~3.5 s a frame); the CoreML detector it ships is not used.

The checkout is run as it is, with two compatibility shims applied at load:
  * its SMPL model is a chumpy pickle, and chumpy does not build on Python 3.14: py-soma-x's chumpy stub stands in
    (the same one py-soma-x uses for SMPL pickles; the file is SHA-256-pinned at install);
  * transformers 5's LlamaDecoderLayer returns the hidden states instead of a tuple, which CoMotion indexed with [0]
    (its rotary embedding is the identity, cos 1 and sin 0, so the layers' output is otherwise unchanged).
Validated against the upstream environment (Python 3.11, torch 2.5, transformers 4.48): same tracks and ids,
joints within a millimetre on average.
"""
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from .contracts import COMOTION_DIR

DEVICE = 'mps'
MESH_BATCH = 256
SHOT_THRESHOLD, SHOT_MIN_FRAMES = 50.0, 3   # CoMotion.__init__'s ContentDetector settings


def prepare(component):
    """Make the pinned checkout importable and apply the compatibility shims (idempotent)."""
    import torch
    source = str(Path(component) / COMOTION_DIR / 'src')
    if source not in sys.path:
        sys.path.insert(0, source)
    from soma._smpl_family_loader import ensure_chumpy_compat
    ensure_chumpy_compat()
    from comotion_demo.models import layers
    from comotion_demo.utils import helper

    @helper.fixed_dim_op(d=3)   # as upstream: tokens arrive (b, n, d0, d1) and the layers take (b, seq, d)
    def call_llama(x, tf):
        kargs = {'position_embeddings': (torch.ones_like(x[..., :1]), torch.zeros_like(x[..., :1]))}
        for layer in tf:
            out = layer(x, **kargs)
            x = out[0] if isinstance(out, tuple) else out
        return x
    layers._call_llama = call_llama


def _on_device(module, device):
    """CoMotion's detector on `device`, called with and answering CPU tensors as CoMotion expects (a module, since it
    replaces one of CoMotion's child modules)."""
    from torch import nn

    class OnDevice(nn.Module):
        def __init__(self):
            super().__init__()
            self.inner, self.cfg, self.feat_dim = module.to(device), module.cfg, module.feat_dim

        def forward(self, image, K):
            out = self.inner(image.to(device), K.to(device))
            return type(out)(**{k: v.to('cpu') for k, v in out._asdict().items()})
    return OnDevice()


class Tracker:
    def __init__(self, component, device=DEVICE):
        import torch
        if device == 'mps' and not torch.backends.mps.is_available():
            raise RuntimeError('CoMotion 需要 Apple GPU（MPS）')
        prepare(component)
        from comotion_demo.models import comotion
        model = comotion.CoMotion(use_coreml=False, pretrained=True).eval()
        model.detection_model = _on_device(model.detection_model, device)
        self.model, self.device = model, device

    def _new_clip(self, size):
        """Per-clip state of the resident model. CoMotion's shot-cut detector and frame counter live on the model and
        were made for one clip per process: in the worker a portrait clip followed by a landscape one tripped
        scenedetect's frame-size assertion (9 of 29 clips fell back to the detector), and the counter ran on."""
        self.model.shot_detector = type(self.model.shot_detector)(threshold=SHOT_THRESHOLD, min_scene_len=SHOT_MIN_FRAMES)
        self.model.frame_count = 0
        self.model.init_tracks(size)

    def mesh(self, betas, pose, trans):
        """SMPL vertices (N, 6890, 3) in CoMotion's camera for parameter rows (N, 10), (N, 72), (N, 3)."""
        import torch
        out = []
        with torch.no_grad():
            for s in range(0, len(betas), MESH_BATCH):
                out.append(self.model.smpl_decoder(*(torch.as_tensor(np.asarray(a[s:s + MESH_BATCH]), dtype=torch.float32)
                                                     for a in (betas, pose, trans)), output_format='mesh').numpy())
        return np.concatenate(out) if out else np.zeros((0, 6890, 3), np.float32)

    def track(self, path, limit, report=None):
        """The first `limit` frames of the clip -> one row per tracked person per frame: id, frame, SMPL pose (72),
        trans, betas (10), box (x0, y0, x1, y1: the projected mesh, unclipped), the camera K (3, 3) it assumes and the
        frame size (height, width)."""
        import torch
        from comotion_demo.utils import dataloading, track as track_utils
        detections, states, K, size = [], [], None, None
        for n, (image, frame_K) in enumerate(dataloading.yield_image_and_K(Path(path), 0, int(limit), 1)):
            if K is None:
                K, size = frame_K, tuple(image.shape[-2:])
                self._new_clip(size)
            detection, state = self.model(image, frame_K, use_mps=self.device == 'mps')
            detections.append({k: v.cpu() for k, v in detection.items()})
            states.append(state.cpu())
            if report and n % 15 == 0:
                report(n)
        empty = {'id': np.zeros(0, np.int64), 'frame': np.zeros(0, np.int64), 'pose': np.zeros((0, 72)), 'trans': np.zeros((0, 3)),
                 'betas': np.zeros((0, 10)), 'box': np.zeros((0, 4)), 'K': np.eye(3), 'frames': len(states), 'size': size}
        if not states:
            return empty
        stacked = torch.stack(states, 1)
        tracks = {k: getattr(stacked, k) for k in ('id', 'pose', 'trans', 'betas')}
        detections = {k: [d[k] for d in detections] for k in detections[0]}
        reference = track_utils.cleanup_tracks({'detections': detections, 'tracks': tracks}, K, self.model.smpl_decoder.cpu(),
                                               min_matched_frames=1)
        full_K = np.vstack([K.numpy().astype(np.float64), [0.0, 0.0, 1.0]])
        if not reference:
            return {**empty, 'K': full_K}
        frames, rows = track_utils.convert_to_idxs(reference, tracks['id'][0].squeeze(-1).long())
        picked = {k: v[0, frames, rows].numpy().astype(np.float64) for k, v in tracks.items()}
        verts = self.mesh(picked['betas'], picked['pose'], picked['trans'])
        uv = verts @ full_K.T
        uv = uv[..., :2] / np.maximum(uv[..., 2:], 1e-3)
        return {'id': picked['id'].reshape(-1).astype(np.int64), 'frame': np.asarray(frames, dtype=np.int64),
                'pose': picked['pose'], 'trans': picked['trans'], 'betas': picked['betas'],
                'box': np.c_[uv.min(1), uv.max(1)], 'K': full_K, 'frames': len(states), 'size': size}


def observed(result, limit):
    """{track id: {frame: box}}: CoMotion's tracks in the shape video.select_tracks takes."""
    out = {}
    for tid, frame, box in zip(result['id'], result['frame'], result['box']):
        if frame < limit:
            out.setdefault(int(tid), {})[int(frame)] = np.asarray(box, dtype=np.float64)
    return out


def bodies_for(result, track):
    """The CoMotion rows behind one selected track: its boxes are CoMotion's own wherever a row exists (interpolated in
    between), so each frame's row is the one whose box equals the track's. {'offset' (frames from the track start),
    'id', 'pose', 'trans', 'betas'} or None when no row matches."""
    start, boxes = track['start'], np.asarray(track['boxes'], dtype=np.float64)
    inside = (result['frame'] >= start) & (result['frame'] < start + len(boxes))
    rows = np.flatnonzero(inside)
    rows = rows[np.all(np.abs(result['box'][rows] - boxes[result['frame'][rows] - start]) < 1e-6, axis=1)]
    if not len(rows):
        return None
    rows = rows[np.unique(result['frame'][rows], return_index=True)[1]]   # one row per frame
    return {'offset': result['frame'][rows] - start, 'id': result['id'][rows], 'pose': result['pose'][rows],
            'trans': result['trans'][rows], 'betas': result['betas'][rows]}


class Comotion:
    """What video recognition uses: CoMotion's tracks, chosen like the detector's, and each track's starting pose."""

    def __init__(self, component, photo):
        from .comotion_pose import StartPose
        self.tracker = Tracker(component)
        self.starter = StartPose(photo, component)

    def tracks(self, path, limit, people, fps, report=None, detected=None):
        """Chosen tracks, each with the CoMotion bodies behind it (None for a detector close-up: `detected`, the
        detector's {tid: {frame: box}}, see video.add_close_ups). Nobody when CoMotion itself found nobody."""
        from .video import add_close_ups, select_tracks
        started = time.time()
        result = self.tracker.track(path, limit, report)
        followed = observed(result, limit)
        if followed and detected:
            height, width = result['size']
            followed = add_close_ups(followed, detected, width, height)
        chosen = select_tracks(followed, people, limit, fps)
        for track in chosen:
            track['comotion'] = bodies_for(result, track)
        self.seconds = round(time.time() - started, 1)
        return chosen

    def start(self, pred, track, width, height, fps):
        bodies = track.get('comotion')
        return pred if bodies is None else self.starter.start(pred, bodies, self.tracker.mesh, len(track['bbx_xys']), width, height, fps)


def self_test(component):
    """Load CoMotion and track a short synthetic clip (installer check): {'device', 'load_seconds', 'frames', 'tracks'}."""
    import cv2
    started = time.time()
    tracker = Tracker(component)
    load = round(time.time() - started, 1)
    with tempfile.TemporaryDirectory(prefix='comotion-selftest-') as temp:
        clip = Path(temp) / 'clip.mp4'
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
        for i in range(8):
            writer.write(np.full((240, 320, 3), 100 + 10 * i, np.uint8))
        writer.release()
        result = tracker.track(clip, 8)
    return {'device': tracker.device, 'load_seconds': load, 'frames': result['frames'], 'tracks': len(np.unique(result['id']))}
