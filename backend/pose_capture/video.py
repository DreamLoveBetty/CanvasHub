"""Video recognition (worker only): a static-camera clip -> per-person SOMA pose sequences.

Configuration from tests/local/pose_gem_spike/VIDEO_SPEED.md (15 s single person ~50 s cold on CoreML):
  * YOLOX + ByteTrack. The tracker only steps on detection frames (feeding it empty frames lets its
    Kalman prediction drift off fast movers); one person is detected every 5th frame, several people
    every frame (sparse boxes slide onto a dance partner when people cross).
  * Broken tracks of the same person are stitched (a spinning dancer breaks ByteTrack's main track).
  * VitPose on ~10 fps keyframes (crop and mirror in one batch of 16), short confidence dropouts bridged
    (fill_dropouts), smoothed over time (smooth_keypoints) and interpolated between with a smooth curve.
  * The GEM denoiser over each whole track (DDIM 50 steps, well under a second).
  * Optional image evidence (evidence.py, SAM 3D Body on ~2.5 frames a second per person, at most
    EVIDENCE_BUDGET frames a clip): arm depth and finger shape for the fit.
  * The keypoint fit (refine.fit_sequence) on the frames VitPose saw, rotations plus a root offset (GEM-X places a
    cut-off person too far and too high); its correction is interpolated
    (smooth curves through the keyframes, interpolate_rows) onto the frames in between. Each keyframe's VitPose
    noise is independent and was joined by straight lines, so limbs turned a corner every keyframe: on a 24 fps
    clip (keyframes every 2nd frame) hands shimmered at ~12 Hz, 4x the acceleration of the frames between.
  * A person framed from the chest up (hips seen on under refine.UPPER_BODY_SEEN of the frames) stands straight under
    the chest (refine.steady_trunk), legs hanging; otherwise legs the frame lost are held (hold_unseen_legs).
Without CoreML the CPU setup thins the work (detect every 10th frame, no flip test), ~2.7 min / 15 s.

With CoMotion installed (comotion.py, §32) its tracks replace YOLOX + ByteTrack (people kept through occlusion and
crossings; the same stitching and selection follow) and its bodies start GEM-X's pose (comotion_pose.py). When
CoMotion fails or finds nobody the clip goes through the detector as before; a track without CoMotion bodies keeps
GEM-X's own start. The detector still runs first: CoMotion misses people framed from the chest up, and the
detector's close-ups it missed join its tracks (add_close_ups).
"""
import math
import os
import sys
import time

import numpy as np

from .contracts import MAX_SECONDS
from .engine import crop, decode
from .evidence import body_shape, targets as evidence_targets
from .refine import (VIDEO_FINGER_WEIGHT, VIDEO_FOOT_MIN_CONFIDENCE, VIDEO_MIN_CONFIDENCE, fit_sequence, hold_unseen_legs,
                     keypoint_weights, steady_trunk, upper_body_only)
from .scene import FINGER, VISIBLE

MIN_TRACK_FRAMES = 30   # shorter tracks are passers-by or detector noise
MIN_TRACK_CONFIDENCE = 0.3  # mean body-keypoint confidence below this is not a person VitPose can see
MIN_RELATIVE_HEIGHT = 0.15  # median box height against the tallest chosen person's: smaller is far background
CLOSE_UP_HEIGHT = 0.5   # a detector track this tall (median box over the frame height) is a close-up CoMotion can miss ...
CLOSE_UP_COVERED = 0.5  # ... and joins CoMotion's tracks when they cover it on less than this share of its frames
COVER_IOU = 0.5         # a CoMotion box covers a detector box (both clipped to the frame) at this IoU
# GEM-X's image condition (SAM 3D Body body tokens) under validation: off (the lite engine), keys (keyframes,
# interpolated between) or all (every frame). Needs the image-evidence engine; read from the environment.
IMAGE_FEATURES_ENV = 'POSE_CAPTURE_IMAGE_FEATURES'
KEYFRAME_FPS = 10.0
STITCH_GAP_SECONDS = 1.0
RELAY_SIZE_RATIO = 0.67  # overlapping tracks of one person: box heights at the same frames within this ratio
GAP_SIZE_RATIO = 0.5     # tracks across a gap: longest box sides within this ratio
DROPOUT_SECONDS = 1.0  # a keypoint unsure for at most this long, seen on both sides, is interpolated across
DROPOUT_CONFIDENCE = 0.55  # what a filled keypoint counts as: just above GEM-X's visibility threshold
KEYPOINT_SIGMA = 0.12   # s: width of the temporal smoothing of a still joint's keyframe keypoints
KEYPOINT_SPEED = 0.3    # person boxes per second at which that width halves (fast limbs keep their sharpness)
CORRECTION_SIGMA = 0.15  # s: smoothing of the fit's per-keyframe corrections to GEM-X (rotations and root offset) ...
CORRECTION_SPEED = 0.3   # ... in still moments; it falls off with the square of the frame's speed (boxes per second)
# A chest-up person's distance from the camera, smoothed along the ray through the chest (Gaussian local-linear fit,
# s): it jittered 1.7 cm a frame on median (8.5 at p95) in a selfie, and with the figure's size fixed that pumped its
# size by 1-7 % a frame; the chest's image stays exactly where it was and a push-in's trend is kept.
UPPER_DEPTH_SIGMA = 0.25
EVIDENCE_FPS = 2.5      # image-evidence frames per second per person (SAM 3D Body, ~1.7 s each on MPS)
EVIDENCE_BUDGET = 60    # at most this many evidence frames per clip, shared by its people (~1.7 min)
# A keyframe keeps the evidence fit only if its 2D error stays within this factor of the fit without evidence:
# the evidence may decide what the 2D cannot see (a hand on the hip or in front of it), never trade what it can.
# Forcing it everywhere cost a spinning dancer 25 % more 2D error. At 1.10 the push-in clip keeps 86 % of its
# evidence frames with its 2D unchanged and the dancer 17 % (+0.03 points on the hands); 1.25 cost the dancer more.
EVIDENCE_2D_SLACK = 1.10


def configuration(backend, people):
    if backend == 'coreml':
        return {'detect_every': 5 if people == 1 else 1, 'flip': True}
    return {'detect_every': 10, 'flip': False}


def read_info(path):
    import cv2
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError('无法读取视频，请转换为 MP4（H.264）后重试')
    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if not (1 <= fps <= 240) or count < 2 or min(width, height) < 64:
        raise ValueError('视频帧率、帧数或尺寸无效')
    return {'fps': float(fps), 'frames': count, 'width': width, 'height': height}


def frames(path, indices):
    """Yield (index, RGB frame) for the requested sorted indices; other frames are skipped without decoding."""
    import cv2
    wanted = iter(sorted(set(int(i) for i in indices)))
    target = next(wanted, None)
    capture = cv2.VideoCapture(str(path))
    index = 0
    try:
        while target is not None:
            if index < target:
                if not capture.grab():
                    return
                index += 1
                continue
            ok, bgr = capture.read()
            if not ok:
                return
            yield index, bgr[..., ::-1].copy()
            index += 1
            target = next(wanted, None)
    finally:
        capture.release()


def box_overlap(a, b):
    """(IoU, intersection over the smaller box) of two xyxy boxes."""
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return (inter / union if union > 0 else 0.0), (inter / min(area_a, area_b) if min(area_a, area_b) > 0 else 0.0)


def similar_size(a, b, ratio, side=max):
    """The boxes' heights (side=None) or longest sides within `ratio` of each other."""
    la, lb = ((box[3] - box[1]) if side is None else side(box[2] - box[0], box[3] - box[1]) for box in (a, b))
    return min(la, lb) >= ratio * max(la, lb)


def continues(a, b, fps):
    """Track b picks up where track a (ended before b began) would be: a's centre moved on at its speed over its
    last half second, within 0.75 of the box width sideways and half its height vertically. Sideways reach
    follows the width: a standing person's box is tall, and a reach of 0.75 of its height had joined a dancer
    who left on the left to another who entered 270 px to the right. The longest box side may change by up to
    half (a backflip's box turns from lying to standing), not more."""
    end, start = max(a), min(b)
    prev, nxt = a[end], b[start]
    centre = lambda box: np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
    recent = [f for f in a if f >= end - fps * 0.5]
    first = min(recent)
    velocity = (centre(prev) - centre(a[first])) / (end - first) if end > first else np.zeros(2)
    dx, dy = centre(nxt) - (centre(prev) + velocity * (start - end))
    width = ((prev[2] - prev[0]) + (nxt[2] - nxt[0])) / 2
    height = ((prev[3] - prev[1]) + (nxt[3] - nxt[1])) / 2
    return similar_size(prev, nxt, GAP_SIZE_RATIO) and (dx / (0.75 * width)) ** 2 + (dy / (0.5 * height)) ** 2 <= 1.0


def same_person(a, b, fps):
    """Two ByteTrack tracks of one person. A short time overlap is a relay: a new id took over before the
    old one expired, and one box contains the other even when spread arms change its width (but not a much
    shorter box at the same moment: someone further back). A long overlap only counts as one person when
    the boxes coincide (dance partners stay side by side for seconds). Without overlap, one track continues
    the other within STITCH_GAP_SECONDS (see continues)."""
    common = set(a) & set(b)
    if common:
        iou, contained = (float(np.mean(v)) for v in zip(*(box_overlap(a[f], b[f]) for f in common)))
        relay = len(common) <= fps * STITCH_GAP_SECONDS and len(common) < 0.5 * min(len(a), len(b))
        alike = np.mean([similar_size(a[f], b[f], RELAY_SIZE_RATIO, side=None) for f in common]) >= 0.5
        return (relay and contained >= 0.7 and alike) or iou >= 0.8
    if 0 < min(b) - max(a) <= fps * STITCH_GAP_SECONDS:
        return continues(a, b, fps)
    if 0 < min(a) - max(b) <= fps * STITCH_GAP_SECONDS:
        return continues(b, a, fps)
    return False


def stitch(observed, length, fps):
    """Merge tracks of the same person that ByteTrack split (see same_person); longer tracks absorb shorter
    ones and keep their own boxes where both have one. observed: {tid: {frame: box}}."""
    tracks = {tid: dict(obs) for tid, obs in observed.items() if obs}
    merged = True
    while merged:
        merged = False
        order = sorted(tracks, key=lambda t: (-len(tracks[t]), t))
        for i, keep in enumerate(order):
            other = next((t for t in order[i + 1:] if same_person(tracks[keep], tracks[t], fps)), None)
            if other is not None:
                for frame, box in tracks.pop(other).items():
                    tracks[keep].setdefault(frame, box)
                merged = True
                break
    return tracks


def select_tracks(observed, people, length, fps):
    """Longest-covering people first: (start, boxes (L,4) interpolated between observations) per track.

    Figures under MIN_RELATIVE_HEIGHT of the tallest chosen person are left out. CoMotion follows pedestrians far down
    a path behind a runner (boxes an eighth of her height, 0.12-0.13); their depth is a guess, and the shared floor
    built from them lifted the runner 3.3 m. The smallest real participants on the evaluation set are 0.22 (street
    passers-by), the back row of a dance class 0.55."""
    tracks = stitch(observed, length, fps)
    area = {tid: sum(max(0, b[2] - b[0]) * max(0, b[3] - b[1]) for b in obs.values()) for tid, obs in tracks.items()}
    chosen = []
    for tid in sorted(area, key=area.get, reverse=True):
        idx = np.array(sorted(tracks[tid]))
        start, end = int(idx[0]), int(idx[-1])
        if end - start + 1 < min(MIN_TRACK_FRAMES, length):
            continue
        span = np.arange(start, end + 1)
        boxes = np.stack([np.interp(span, idx, [tracks[tid][i][k] for i in idx]) for k in range(4)], 1)
        chosen.append({'start': start, 'boxes': boxes, 'observed': len(idx)})
        if len(chosen) == people:
            break
    heights = [float(np.median(t['boxes'][:, 3] - t['boxes'][:, 1])) for t in chosen]
    chosen = [t for t, h in zip(chosen, heights) if h >= MIN_RELATIVE_HEIGHT * max(heights)]
    return sorted(chosen, key=lambda t: -float(np.mean((t['boxes'][:, 2] - t['boxes'][:, 0]) * (t['boxes'][:, 3] - t['boxes'][:, 1]))))


def add_close_ups(followed, detected, width, height):
    """CoMotion's tracks ({tid: {frame: box}}) with the close-ups it missed taken from the detector's.

    CoMotion detects whole SMPL bodies and does not see a person framed from the chest up: on a fisheye selfie (her
    box 86 % of the frame height for 15 s) it found her only in a 38-frame waist-up shot, and three passers-by became
    the clip's people; YOLOX followed her on 334 of 360 frames. A detector track whose median box is at least
    CLOSE_UP_HEIGHT of the frame, that spans MIN_TRACK_FRAMES (YOLOX's 1-5 frame fragments of a tumbling or crowded
    person would only be stitched into tracks) and that CoMotion's boxes cover on less than CLOSE_UP_COVERED of its frames joins
    (as id -1 - tid), and the CoMotion tracks it covers on most of their frames leave (that person's short CoMotion
    track would be a second figure). Smaller people stay CoMotion's, which follows them where ByteTrack broke."""
    clip = lambda box: np.clip(np.asarray(box, dtype=np.float64), 0.0, [width, height, width, height])
    at = {}
    for tid, obs in followed.items():
        for frame, box in obs.items():
            at.setdefault(frame, []).append((tid, clip(box)))

    def covering(frame, box):
        return [tid for tid, other in at.get(frame, ()) if box_overlap(other, clip(box))[0] >= COVER_IOU]
    merged, dropped = dict(followed), set()
    for tid, obs in detected.items():
        if (not obs or max(obs) - min(obs) + 1 < MIN_TRACK_FRAMES
                or np.median([b[3] - b[1] for b in map(clip, obs.values())]) < CLOSE_UP_HEIGHT * height):
            continue
        hits = [covering(frame, box) for frame, box in obs.items()]
        if np.mean([bool(h) for h in hits]) >= CLOSE_UP_COVERED:
            continue
        merged[-1 - tid] = dict(obs)
        for other in {t for h in hits for t in h}:
            shared = sum(1 for frame in followed[other] if frame in obs and other in covering(frame, obs[frame]))
            if shared >= 0.5 * len(followed[other]):
                dropped.add(other)
    return {tid: obs for tid, obs in merged.items() if tid not in dropped}


def trusted_tracks(tracks, keyed, joint_names):
    """The tracks (and their keyframe keypoints, renumbered) whose body keypoints average MIN_TRACK_CONFIDENCE or more.

    With room for four people the detector also follows specks: a 35-frame box far behind a park acrobat
    averaged 0.03 and became a figure of its own. Real people seen badly stay well above it (a back-view
    runner in a tracking shot 0.49, half-body dancers 0.50-0.58). Fingers and end joints are left out: they
    are uncertain even on a clear person.
    """
    body = [i for i, n in enumerate(joint_names) if not any(f in n for f in FINGER) and not n.endswith('End')]
    keep = [t for t in range(len(tracks)) if float(np.mean(np.asarray(keyed[t])[:, body, 2])) >= MIN_TRACK_CONFIDENCE]
    return [tracks[t] for t in keep], {i: keyed[t] for i, t in enumerate(keep)}


def fill_dropouts(keypoints, keys, fps):
    """Bridge short confidence dropouts of keyframe keypoints (K, J, 3) at clip frames `keys`.

    VitPose sometimes loses a clearly visible limb for a moment (a frontal, nearly symmetric pose put a
    held akimbo arm at 0.23-0.5 for 0.75 s); GEM-X and the fit then ignore it and the arm drops. A run of
    keyframes below VISIBLE that is at most DROPOUT_SECONDS long and has a visible keyframe on both sides
    is replaced by the straight line between them at DROPOUT_CONFIDENCE. Joints that leave the frame are
    not seen again on the far side, so their gap is open-ended and stays as it is (refine.hold_unseen_legs,
    not this, decides whether a foot guessed below the frame edge is seen).
    """
    out = np.array(keypoints, dtype=np.float64, copy=True)
    keys = np.asarray(keys, dtype=np.float64)
    for j in range(out.shape[1]):
        good = np.flatnonzero(out[:, j, 2] >= VISIBLE)
        for a, b in zip(good[:-1], good[1:]):
            if b - a < 2 or (keys[b] - keys[a]) / fps > DROPOUT_SECONDS:
                continue
            t = ((keys[a + 1:b] - keys[a]) / (keys[b] - keys[a]))[:, None]
            out[a + 1:b, j, :2] = (1 - t) * out[a, j, :2] + t * out[b, j, :2]
            out[a + 1:b, j, 2] = np.maximum(out[a + 1:b, j, 2], DROPOUT_CONFIDENCE)
    return out


def keep_evidence(errors, errors_evidence, targeted, slack=None):
    """Per keyframe: take the evidence fit where it had targets and its 2D error stays within EVIDENCE_2D_SLACK."""
    slack = EVIDENCE_2D_SLACK if slack is None else slack
    return np.asarray(targeted, bool) & (np.asarray(errors_evidence) <= np.asarray(errors) * slack)


def smooth_keypoints(keypoints, keys, fps, sizes, sigma=KEYPOINT_SIGMA, speed=KEYPOINT_SPEED):
    """Temporally smoothed keyframe keypoints (K, J, 3); confidences unchanged.

    Per joint and keyframe: a local linear fit over the neighbouring keyframes, weighted by confidence and by a
    Gaussian in time whose width adapts to the joint's own speed there, sigma / (1 + v / speed) with v in person
    boxes per second (sizes (K,) box sides). A line keeps steady motion at its speed; the adaptive width
    smooths a slow hand's shimmer hard but leaves a spinning dancer's hands their sharpness (a fixed 0.07 s
    tripled their error against the raw detections).
    """
    out = np.array(keypoints, dtype=np.float64, copy=True)
    if sigma <= 0 or len(out) < 3:
        return out
    t = np.asarray(keys, dtype=np.float64) / fps
    count = len(t)
    raw = out[..., :2].copy()
    gap = np.maximum(t[np.minimum(np.arange(count) + 1, count - 1)] - t[np.maximum(np.arange(count) - 1, 0)], 1e-6)
    velocity = np.linalg.norm(raw[np.minimum(np.arange(count) + 1, count - 1)] - raw[np.maximum(np.arange(count) - 1, 0)], axis=-1)
    velocity = velocity / gap[:, None] / np.maximum(np.asarray(sizes, dtype=np.float64), 1.0)[:, None]   # boxes per second
    from scipy.ndimage import median_filter
    velocity = median_filter(velocity, size=(3, 1), mode='nearest')
    width = sigma / (1.0 + velocity / speed)                       # (K, J) per centre keyframe and joint
    reach = max(1, int(np.ceil(3 * sigma / max(np.min(np.diff(t)), 1e-6))))   # keyframes within 3 sigma
    conf = np.maximum(out[:, :, 2], 1e-3)
    s0, s1, s2 = (np.zeros(conf.shape) for _ in range(3))
    sx, stx = np.zeros(raw.shape), np.zeros(raw.shape)
    centre = np.arange(count)
    for d in range(-reach, reach + 1):
        other = centre + d
        valid = (other >= 0) & (other < count)
        c, o = centre[valid], other[valid]
        dt = (t[o] - t[c])[:, None]
        w = np.exp(-0.5 * (dt / width[c]) ** 2) * conf[o]
        s0[c] += w; s1[c] += w * dt; s2[c] += w * dt ** 2
        sx[c] += w[..., None] * raw[o]
        stx[c] += (w * dt)[..., None] * raw[o]
    det = s0 * s2 - s1 ** 2
    solvable = (det > 1e-9 * np.maximum(s0 * s2, 1e-12))[..., None]
    line = (s2[..., None] * sx - s1[..., None] * stx) / np.where(solvable, det[..., None], 1.0)   # intercept at the centre
    out[..., :2] = np.where(solvable, line, sx / s0[..., None])
    return out


def frame_speed(keypoints, keys, fps, sizes):
    """Per keyframe: the 90th percentile speed of the confidently seen keypoints, in person boxes per second."""
    kp = np.asarray(keypoints, dtype=np.float64)
    count = len(kp)
    if count < 3:
        return np.zeros(count)
    t = np.asarray(keys, dtype=np.float64) / fps
    after, before = np.minimum(np.arange(count) + 1, count - 1), np.maximum(np.arange(count) - 1, 0)
    speed = np.linalg.norm(kp[after, :, :2] - kp[before, :, :2], axis=-1) / np.maximum(t[after] - t[before], 1e-6)[:, None]
    speed /= np.maximum(np.asarray(sizes, dtype=np.float64), 1.0)[:, None]
    seen = (kp[after, :, 2] >= VISIBLE) & (kp[before, :, 2] >= VISIBLE)
    out = np.array([np.percentile(speed[i][seen[i]], 90) if seen[i].any() else 0.0 for i in range(count)])
    from scipy.ndimage import median_filter
    return median_filter(out, size=3, mode='nearest')


def smooth_series(values, keys, fps, sigma):
    """Keyframe values (K, ...) smoothed by a Gaussian-weighted local linear fit in time; sigma is in seconds, one
    width for all keyframes or one per keyframe (K,)."""
    values = np.asarray(values, dtype=np.float64)
    if np.max(sigma) <= 0 or len(values) < 3:
        return values.copy()
    t = np.asarray(keys, dtype=np.float64) / fps
    flat = values.reshape(len(values), -1)
    count = len(t)
    width = np.maximum(np.broadcast_to(np.asarray(sigma, dtype=np.float64), (count,)), 1e-4)
    reach = max(1, int(np.ceil(3 * width.max() / max(np.min(np.diff(t)), 1e-6))))
    s0, s1, s2 = np.zeros(count), np.zeros(count), np.zeros(count)
    sx, stx = np.zeros(flat.shape), np.zeros(flat.shape)
    centre = np.arange(count)
    for d in range(-reach, reach + 1):
        other = centre + d
        valid = (other >= 0) & (other < count)
        c, o = centre[valid], other[valid]
        dt = t[o] - t[c]
        w = np.exp(-0.5 * (dt / width[c]) ** 2)
        s0[c] += w; s1[c] += w * dt; s2[c] += w * dt ** 2
        sx[c] += w[:, None] * flat[o]
        stx[c] += (w * dt)[:, None] * flat[o]
    det = s0 * s2 - s1 ** 2
    solvable = (det > 1e-9 * np.maximum(s0 * s2, 1e-12))[:, None]
    line = (s2[:, None] * sx - s1[:, None] * stx) / np.where(solvable, det[:, None], 1.0)
    return np.where(solvable, line, sx / s0[:, None]).reshape(values.shape)


def interpolate_rows(values, keys, length):
    """Per-frame values (length, ...) through keyframe values (K, ...) at sorted frame `keys`: a smooth monotone
    cubic (PCHIP, no overshoot, no corners at the keyframes); the ends hold the first / last keyframe."""
    from scipy.interpolate import PchipInterpolator
    values = np.asarray(values, dtype=np.float64)
    keys = np.asarray(keys, dtype=np.float64)
    frames_all = np.clip(np.arange(length, dtype=np.float64), keys[0], keys[-1])
    if len(keys) < 2:
        return np.repeat(values[:1], length, 0)
    return PchipInterpolator(keys, values, axis=0)(frames_all)


def interpolate_quats(quats, keys, length):
    """Per-frame quaternions (length, J, 4) through keyframe quaternions (K, J, 4): each joint's quaternions are
    put on one hemisphere along the keyframes, interpolated with interpolate_rows and renormalised."""
    quats = np.array(quats, dtype=np.float64, copy=True)
    for k in range(1, len(quats)):
        flip = np.sum(quats[k] * quats[k - 1], -1) < 0
        quats[k, flip] *= -1
    out = interpolate_rows(quats, keys, length)
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


class VideoEngine:
    def __init__(self, photo, component, video):
        """photo: the loaded PhotoEngine (GEM model, CPU sessions); video: the install receipt's video entry."""
        self.photo, self.backend = photo, video.get('backend', 'cpu')
        self.detector, self.vitpose, self.batch = photo.detector, photo.vitpose, 1
        if self.backend == 'coreml':
            from . import accel
            yolox, self.vitpose = accel.sessions(component, video)
            self.detector.sess = yolox
            self.batch = accel.VITPOSE_BATCH
        self.joint_names = photo.joint_names

    # ---- stages --------------------------------------------------------------
    def _sightings(self, path, limit, every, report, span=0.15):
        """YOLOX + ByteTrack over the clip: {tid: {frame: box}} (progress from 0.05 over `span`)."""
        from gem.utils.yolox_detector import ByteTracker
        from collections import defaultdict
        tracker, seen = ByteTracker(), defaultdict(dict)
        indices = [i for i in range(limit) if i % every == 0 or i == limit - 1]
        for n, (i, image) in enumerate(frames(path, indices)):
            if n % 30 == 0:
                report(f'检测人物 {round(100 * n / len(indices))}%', 0.05 + span * n / len(indices))
            boxes, scores = self.detector.detect(np.ascontiguousarray(image[..., ::-1]))
            for box, tid, _ in tracker.update(boxes, scores):
                seen[int(tid)][i] = np.asarray(box, dtype=np.float64)
        return dict(seen)

    def _detect(self, path, limit, every, people, fps, report, seen=None):
        """The detector's tracks (from `seen` when the clip was already detected)."""
        return select_tracks(self._sightings(path, limit, every, report) if seen is None else seen, people, limit, fps)

    def _comotion_tracks(self, comotion, path, limit, people, fps, report, seen=None):
        """CoMotion's tracks with the detector's close-ups it missed (`seen`, see add_close_ups), or None to fall back
        to the detector (a CoMotion failure only costs the tracker). A cancellation raised by `report` still ends the job."""
        stopped = []

        def step(frame):
            try:
                report(f'追踪人物 {round(100 * frame / max(1, limit))}%', 0.1 + 0.1 * frame / max(1, limit))
            except Exception as exc:
                stopped.append(exc)
                raise
        try:
            return comotion.tracks(path, limit, people, fps, step, detected=seen) or None
        except Exception as exc:
            if stopped:
                raise stopped[0]
            print(f'CoMotion 追踪失败，改用检测器：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return None

    def _heatmaps(self, batch):
        name = self.vitpose.get_inputs()[0].name
        if self.batch == 1:
            return np.concatenate([self.vitpose.run(None, {name: np.ascontiguousarray(c[None])})[0] for c in batch])
        out = []
        for s in range(0, len(batch), self.batch):
            part = batch[s:s + self.batch]
            pad = self.batch - len(part)
            if pad:
                part = np.concatenate([part, np.zeros((pad,) + part.shape[1:], part.dtype)])
            out.append(self.vitpose.run(None, {name: np.ascontiguousarray(part)})[0][:self.batch - pad])
        return np.concatenate(out)

    def _keypoints(self, path, tracks, flip, report):
        """VitPose at each track's keyframes, batched across people and frames; returns {track: (keys, kp)}."""
        requests = {}  # frame -> [(track index, row)]
        for t, track in enumerate(tracks):
            for row, key in enumerate(track['keys']):
                requests.setdefault(track['start'] + int(key), []).append((t, row))
        crops = {t: np.empty((len(track['keys']), 3, 256, 192), np.float32) for t, track in enumerate(tracks)}
        for n, (i, image) in enumerate(frames(path, requests)):
            for t, row in requests[i]:
                crops[t][row] = crop(image, tracks[t]['bbx_xys'][i - tracks[t]['start']])
        result = {}
        total = sum(len(c) for c in crops.values()) or 1
        done = 0
        for t, patches in crops.items():
            keys = tracks[t]['keys']
            if flip:
                heat = self._heatmaps(np.concatenate([patches, patches[..., ::-1]]))
                kp = decode(heat[:len(patches)], heat[len(patches):], tracks[t]['bbx_xys'][keys])
            else:
                kp = decode(self._heatmaps(patches), None, tracks[t]['bbx_xys'][keys])
            result[t] = kp
            done += len(patches)
            report(f'识别关键点 {round(100 * done / total)}%', 0.2 + 0.45 * done / total)
        return result

    def _observe(self, path, tracks, evidence, fps, report):
        """SAM 3D Body on evenly spaced keyframes of every track: {track: {keyframe row: observation | None}}."""
        desired = [max(2, math.ceil(len(t['bbx_xys']) / fps * EVIDENCE_FPS)) for t in tracks]
        share = min(1.0, EVIDENCE_BUDGET / max(1, sum(desired)))
        requests, out = {}, {t: {} for t in range(len(tracks))}
        for t, track in enumerate(tracks):
            count = min(len(track['keys']), max(2, int(desired[t] * share)))
            for row in np.unique(np.linspace(0, len(track['keys']) - 1, count).round().astype(int)):
                requests.setdefault(track['start'] + int(track['keys'][row]), []).append((t, int(row)))
        total, done = sum(len(v) for v in requests.values()), 0
        for i, image in frames(path, requests):
            for t, row in requests[i]:
                try:
                    out[t][row] = evidence.observe(image, tracks[t]['box_xyxy'][int(tracks[t]['keys'][row])])
                except Exception as exc:  # evidence is optional: a failed frame only loses its targets
                    print(f'影像证据失败（帧 {i}）：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                    out[t][row] = None
                done += 1
                report(f'影像证据 {done}/{total}', 0.65 + 0.03 * done / max(1, total))
        return out

    def _features(self, path, tracks, evidence, mode, report):
        """GEM-X's image condition per track: {track: (tokens (L, 1024), camera translations (L, 3))}, from SAM 3D Body
        on every frame (mode 'all') or on the keyframes, linearly interpolated between them (mode 'keys')."""
        wanted = {}
        for t, track in enumerate(tracks):
            rows = np.arange(len(track['bbx_xys'])) if mode == 'all' else track['keys']
            for row in rows:
                wanted.setdefault(track['start'] + int(row), []).append((t, int(row)))
        seen = {t: {} for t in range(len(tracks))}
        total, done, batch = sum(len(v) for v in wanted.values()), 0, []

        def flush():
            images = [image for image, _, _ in batch]
            boxes = np.array([tracks[t]['bbx_xys'][row] for _, t, row in batch])
            tokens, transls = evidence.features(images, boxes)
            for (_, t, row), token, transl in zip(batch, tokens, transls):
                seen[t][row] = (token, transl)
            batch.clear()
        for i, image in frames(path, wanted):
            for t, row in wanted[i]:
                batch.append((image, t, row))
                done += 1
            if len(batch) >= 16:
                flush()
                report(f'影像特征 {done}/{total}', 0.65 + 0.03 * done / max(1, total))
        if batch:
            flush()
        out = {}
        for t, track in enumerate(tracks):
            rows = np.array(sorted(seen[t]))
            if len(rows) < 2:
                continue
            tokens = np.stack([seen[t][r][0] for r in rows]); transls = np.stack([seen[t][r][1] for r in rows])
            L = len(track['bbx_xys'])
            out[t] = (interpolate_rows(tokens, rows, L), interpolate_rows(transls, rows, L))
        return out

    def _fit(self, params, kp_keys, keys, bbx_xys, K, fps=30.0, observations=None):
        """Fit the keyframes, then carry each keyframe's rotation correction and root offset to the frames in between."""
        import torch
        from scipy.spatial.transform import Rotation
        shape = {k: v[keys] for k, v in params.items() if k not in ('global_orient', 'body_pose')}

        def forward(go, bp):
            return self.photo.model.body_model(**shape, global_orient=go, body_pose=bp)['joints'].reshape(len(keys), 77, 3)
        go0, bp0 = params['global_orient'].numpy(), params['body_pose'].numpy()
        weights = np.stack([keypoint_weights(k, self.joint_names, min_confidence=VIDEO_MIN_CONFIDENCE, finger_weight=VIDEO_FINGER_WEIGHT,
                                             foot_min_confidence=VIDEO_FOOT_MIN_CONFIDENCE) for k in kp_keys])
        evidence = used = None
        if observations:
            with torch.no_grad():
                joints0 = forward(torch.as_tensor(go0[keys]), torch.as_tensor(bp0[keys])).numpy().astype(np.float64)
            evidence = evidence_targets(observations, joints0, kp_keys, bbx_xys[keys, 2], self.joint_names, keys, fps)
            used = evidence.pop('used')
        args = (forward, go0[keys], bp0[keys], kp_keys, K, bbx_xys[keys, 2], weights)
        go_k, bp_k, offset_k, info = fit_sequence(*args)
        errors = info.pop('frame_errors')
        if evidence is not None:
            go_e, bp_e, offset_e, info_e = fit_sequence(*args, evidence=evidence)
            errors_e = info_e.pop('frame_errors')
            targeted = (evidence['depth_mask'].any(1) | evidence['shape_mask'].any(1))
            keep = keep_evidence(errors, errors_e, targeted)
            go_k, bp_k, offset_k = (np.where(keep[:, None], e, p) for e, p in ((go_e, go_k), (bp_e, bp_k), (offset_e, offset_k)))
            errors = np.where(keep, errors_e, errors)
            info.update(error_after=round(float(np.median(errors)), 3), worst_after=round(float(errors.max()), 3),
                        steps=max(info['steps'], info_e['steps']), seconds=round(info['seconds'] + info_e['seconds'], 3))
            info['evidence'] = {'frames': sum(o is not None for o in observations.values()), 'requested': len(observations), **used,
                                'kept': round(float(keep.sum() / max(1, targeted.sum())), 3)}
        L = len(go0)
        before = np.concatenate([go0[keys][:, None], bp0[keys].reshape(len(keys), -1, 3)], 1)
        after = np.concatenate([go_k[:, None], bp_k.reshape(len(keys), -1, 3)], 1)
        J = before.shape[1]
        delta = (Rotation.from_rotvec(after.reshape(-1, 3)) * Rotation.from_rotvec(before.reshape(-1, 3)).inv()).as_quat().reshape(len(keys), J, 4)
        # The corrections are slow biases (a hand that belongs on the hip); GEM-X carries the motion. Each keyframe's
        # correction was fitted on its own (and image evidence switches on and off per keyframe), so in still moments
        # they are smoothed before use: on the push-in clip evidence had raised rotation jitter 4.5x over the plain
        # fit. In fast motion the corrections really change quickly (smoothing them doubled a spinning dancer's
        # hand error), so the width falls off with the frame's speed.
        width = CORRECTION_SIGMA / (1.0 + (frame_speed(kp_keys, keys, fps, bbx_xys[keys, 2]) / CORRECTION_SPEED) ** 2)
        for k in range(1, len(delta)):
            delta[k, np.sum(delta[k] * delta[k - 1], -1) < 0] *= -1
        delta = smooth_series(delta, keys, fps, width)
        delta /= np.linalg.norm(delta, axis=-1, keepdims=True)
        offset_k = smooth_series(offset_k, keys, fps, width)
        delta_all = interpolate_quats(delta, keys, L)
        base = np.concatenate([go0[:, None], bp0.reshape(L, -1, 3)], 1)
        fitted = (Rotation.from_quat(delta_all.reshape(-1, 4)) * Rotation.from_rotvec(base.reshape(-1, 3))).as_rotvec().reshape(L, J, 3)
        params = dict(params)
        params['global_orient'] = torch.as_tensor(fitted[:, 0], dtype=torch.float32)
        params['body_pose'] = torch.as_tensor(fitted[:, 1:].reshape(L, -1), dtype=torch.float32)
        offset = interpolate_rows(offset_k, keys, L)
        params['transl'] = params['transl'] + torch.as_tensor(offset, dtype=torch.float32)
        return params, info

    def _outside(self, params, body_pose, K, width, height):
        """(L, 77) bool: joints of `body_pose` (camera frame, the clip's params otherwise) projecting outside the image."""
        import torch
        joints = self.photo.model.body_model(**{**params, 'body_pose': torch.as_tensor(body_pose, dtype=torch.float32)})['joints']
        joints = joints.reshape(len(body_pose), 77, 3).numpy().astype(np.float64)
        depth = joints[..., 2]
        uv = (joints @ np.asarray(K).T)[..., :2] / np.where(depth > 1e-6, depth, 1e-6)[..., None]
        return (depth <= 1e-6) | (uv[..., 0] < 0) | (uv[..., 0] > width) | (uv[..., 1] < 0) | (uv[..., 1] > height)

    # ---- one clip ------------------------------------------------------------
    def recognize(self, path, max_people=1, progress=None, evidence=None, comotion=None):
        import torch
        from gem.utils.geo_transform import get_bbx_xys_from_xyxy
        from gem.utils.kp2d_utils import smooth_bbx_xyxy
        report = progress or (lambda stage, ratio=None: None)
        report('读取视频', 0.02)
        info = read_info(path)
        fps, width, height = info['fps'], info['width'], info['height']
        limit = min(info['frames'], int(round(MAX_SECONDS * fps)))
        config = configuration(self.backend, max_people)
        seen = None
        if comotion is not None:
            seen = self._sightings(path, limit, config['detect_every'], report, span=0.05)
        tracks = self._comotion_tracks(comotion, path, limit, max_people, fps, report, seen) if comotion is not None else None
        tracker = 'comotion' if tracks else 'detector'
        if not tracks:
            tracks = self._detect(path, limit, config['detect_every'], max_people, fps, report, seen)
        stride = max(1, int(round(fps / KEYFRAME_FPS)))
        for track in tracks:
            boxes = smooth_bbx_xyxy(torch.as_tensor(track['boxes'], dtype=torch.float32), window=3)
            boxes[:, [0, 2]] = boxes[:, [0, 2]].clamp(0, width - 1)
            boxes[:, [1, 3]] = boxes[:, [1, 3]].clamp(0, height - 1)
            track['box_xyxy'] = boxes.numpy().astype(np.float64)
            track['bbx_xys'] = get_bbx_xys_from_xyxy(boxes, base_enlarge=1.2).numpy().astype(np.float64)
            L = len(boxes)
            track['keys'] = np.unique(np.r_[np.arange(0, L, stride), L - 1])
        keyed = self._keypoints(path, tracks, config['flip'], report) if tracks else {}
        tracks, keyed = trusted_tracks(tracks, keyed, self.joint_names)
        started = time.time()
        sightings = self._observe(path, tracks, evidence, fps, report) if evidence is not None and tracks else {}
        evidence_seconds = round(time.time() - started, 1) if sightings else None
        mode = os.environ.get(IMAGE_FEATURES_ENV, 'off')
        started = time.time()
        conditions = self._features(path, tracks, evidence, mode, report) if evidence is not None and mode in ('keys', 'all') else {}
        feature_seconds = round(time.time() - started, 1) if conditions else None
        people = []
        for t, track in enumerate(tracks):
            report(f'时序求解 {t + 1}/{len(tracks)}', 0.68 + 0.2 * t / len(tracks))
            keys, L = track['keys'], len(track['bbx_xys'])
            kp_keys = smooth_keypoints(fill_dropouts(keyed[t], keys, fps), keys, fps, track['bbx_xys'][keys, 2])
            kp = np.empty((L, 77, 3))
            lo = np.searchsorted(keys, np.arange(L), side='right') - 1
            hi = np.minimum(lo + 1, len(keys) - 1)
            kp[..., :2] = interpolate_rows(kp_keys[..., :2], keys, L)
            kp[..., 2] = np.minimum(kp_keys[lo, :, 2], kp_keys[hi, :, 2])
            features, transl = conditions.get(t, (None, None))
            pred_cam = None
            if features is not None:
                from gem.utils.cam_utils import estimate_K, get_a_pred_cam
                pred_cam = get_a_pred_cam(torch.as_tensor(transl, dtype=torch.float32), torch.as_tensor(track['bbx_xys'], dtype=torch.float32),
                                          estimate_K(width, height).repeat(L, 1, 1)).numpy()
            pred = self.photo.predict(kp, track['bbx_xys'], width, height, features=features, pred_cam=pred_cam)
            if track.get('comotion') is not None:
                try:
                    pred = comotion.start(pred, track, width, height, fps)
                except Exception as exc:  # the start is optional: GEM-X's own prediction stands
                    print(f'CoMotion 起始姿态失败：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            K = pred['K_fullimg'][0].numpy().astype(np.float64)
            params = {k: v.detach().cpu().float() for k, v in pred['body_params_incam'].items() if torch.is_tensor(v)}
            world = {k: v.detach().cpu().float() for k, v in pred['body_params_global'].items() if torch.is_tensor(v)}
            report(f'贴合关键点 {t + 1}/{len(tracks)}', 0.7 + 0.2 * (t + 0.5) / len(tracks))
            params, fit = self._fit(params, kp_keys, keys, track['bbx_xys'], K, fps, sightings.get(t))
            observed = self.photo.model.body_model(**params)['joints'].reshape(L, 77, 3).numpy().astype(np.float64)
            upper = upper_body_only(kp[..., 2], self.joint_names)
            if upper:
                orient, pose = steady_trunk(params['global_orient'].numpy(), params['body_pose'].numpy(), self.joint_names, fps)
                params['global_orient'] = torch.as_tensor(orient, dtype=torch.float32)
                params['body_pose'] = torch.as_tensor(pose, dtype=torch.float32)
                joints = self.photo.model.body_model(**params)['joints'].reshape(L, 77, 3).numpy().astype(np.float64)
                chest = self.joint_names.index('Chest')
                shift = observed[:, chest] - joints[:, chest]   # the chest, and all the image shows above it, stays put
                distance = np.linalg.norm(observed[:, chest], axis=1)
                steady = smooth_series(distance, np.arange(L), fps, UPPER_DEPTH_SIGMA)
                shift = shift + observed[:, chest] * (steady / distance - 1.0)[:, None]   # ... on its ray, at a steady distance
                params['transl'] = params['transl'] + torch.as_tensor(shift, dtype=torch.float32)
                joints = observed = joints + shift[:, None]     # nothing below the chest was seen to stand on
                held = np.ones(L)
            else:
                pose, held = hold_unseen_legs(params['body_pose'].numpy(), kp[..., 2], self.joint_names, fps,
                                              outside=lambda candidate: self._outside(params, candidate, K, width, height))
                params['body_pose'] = torch.as_tensor(pose, dtype=torch.float32)
                joints = self.photo.model.body_model(**params)['joints'].reshape(L, 77, 3).numpy().astype(np.float64) if held.any() else observed
            identity = np.median(params['identity_coeffs'].numpy(), 0).astype(np.float64)
            scale = np.median(params['scale_params'].numpy(), 0).astype(np.float64)
            people.append({
                'start': track['start'], 'count': L, 'K': K, 'keypoints': kp, 'bbx_xys': track['bbx_xys'],
                'box_xyxy': track['box_xyxy'], 'coverage': round(track['observed'] / max(1, math.ceil(L / config['detect_every'])), 3),
                'incam': {'global_orient': params['global_orient'].numpy().astype(np.float64),
                          'body_pose': params['body_pose'].numpy().astype(np.float64),
                          'transl': params['transl'].numpy().astype(np.float64), 'joints': joints, 'observed_joints': observed,
                          'identity_coeffs': identity, 'scale_params': scale},
                'global': {'global_orient': world['global_orient'].numpy().astype(np.float64),
                           'joints': self.photo.model.body_model(**world)['joints'].reshape(L, 77, 3).numpy().astype(np.float64)},
                'rest_height': self.photo.rest_height(identity, scale), 'fit': fit,
                # The mannequin's build from the image when there is evidence; the skeleton and its height keep GEM-X's.
                'body_shape': body_shape(sightings.get(t) or {}),
                'held_legs': round(float(np.mean(held > 0.5)), 3),
                'upper_body': upper,
                'score': float(np.mean(kp_keys[..., 2])),
            })
        return {'fps': fps, 'frames': limit, 'source_frames': info['frames'], 'truncated': info['frames'] > limit,
                'width': width, 'height': height, 'people': people, 'backend': self.backend,
                'keyframe_stride': stride, 'detect_every': config['detect_every'],
                'evidence': None if evidence is None else {'engine': 'sam-3d-body', 'seconds': evidence_seconds},
                'tracker': {'engine': tracker, 'seconds': getattr(comotion, 'seconds', None) if tracker == 'comotion' else None},
                'image_features': {'mode': mode, 'seconds': feature_seconds} if conditions else None}
