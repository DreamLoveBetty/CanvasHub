"""Fit a recognised pose to its own 2D keypoints (worker only; needs torch).

GEM-X lite lifts 2D keypoints to 3D through a motion prior without image features. On unusual poses
(a knee crossed in front of the standing leg, a foot kicked behind) the prior wins and limbs land
beside the person although VitPose found them. A short gradient fit of the joint rotations to the
confidence-weighted keypoints, anchored to the GEM-X pose, pulls them back. A 2D-only fit is free to
swing limbs towards or away from the camera (it splayed walking legs into lunges), so each joint's depth
relative to the hips is also held near the GEM-X estimate: the fit corrects what the photo shows and
keeps the engine's depth. Body shape and translation are untouched; a fit that does not reduce the 2D
error is discarded.

Video only: a person framed from the chest up stands straight under the chest (steady_trunk), and legs the frame no
longer shows are held (hold_unseen_legs). GEM-X assumes a static camera,
so a push-in, where the person grows and the hips sink in the frame while the feet leave it, reads as
the person crouching towards the camera and the knees folded into a kneel. A leg joint whose child
keypoint is not visible, and would be outside the image, keeps its last seen rotation instead.
"""
import math
import time

import numpy as np

from .scene import VISIBLE, axis_angle, rodrigues

FINGERS = ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky')
ANCHOR = 0.005       # pull towards the GEM-X rotations (per radian^2); lower follows the keypoints more
DEPTH_ANCHOR = 0.05  # pull towards the GEM-X depth of each joint relative to the hips (per m^2)
STEPS = 300
LEARNING_RATE = 0.02
MIN_CONFIDENCE = 0.3
FINGER_WEIGHT = 0.1  # hand keypoints are the least reliable VitPose output
# Video keyframes: only keypoints GEM-X itself counts as visible (a failed VitPose frame put the hips on the
# chest at 0.37 and twisted the pelvis), and fingers count more: in a close-up the hand is large and its
# keypoints set the palm and the grip; a small hand's residuals are small in person-box units anyway.
VIDEO_MIN_CONFIDENCE = VISIBLE
VIDEO_FINGER_WEIGHT = 0.5
# VitPose reports a foot it really sees at 0.8-0.95 but still guesses one below the frame edge, at 0.36 on
# median and up to 0.57 (never 0.7); at GEM-X's VISIBLE 0.5 such guesses counted as seen and lent their
# folded legs to the hold.
UNSEEN = 0.7         # below a reliable sighting a leg joint starts to be held ...
UNSEEN_FULL = 0.45   # ... and at or below this the GEM-X guess is replaced entirely (a guessed foot sits around 0.36)
UNSEEN_SECONDS = 0.25  # visibility is median-filtered over this window so a flickering keypoint does not pop
# The video fit takes foot keypoints (ankle, toes) from the same reliable sighting on. At VISIBLE it fitted VitPose's
# guess for a coach's ankle cut off at the right edge (0.51, placed above her knee) and folded a leg CoMotion had
# straight (170 -> 104 deg) before the hold ever ran; the hold then kept it, the straightened foot landing inside the
# frame. A dark shoe seen at 0.55 now leaves its ankle to the starting pose, which reads the image.
VIDEO_FOOT_MIN_CONFIDENCE = UNSEEN
FOOT_JOINTS = ('Foot', 'ToeBase', 'ToeEnd')
# (joint, the child keypoint that shows where the joint points): hip -> knee, knee -> ankle, ...
LEG_CHAINS = tuple((side + joint, side + child) for side in ('Left', 'Right')
                   for joint, child in (('Leg', 'Shin'), ('Shin', 'Foot'), ('Foot', 'ToeBase'), ('ToeBase', 'ToeEnd')))
# Video, a chest-up shot (upper_body_only, steady_trunk): hips seen on fewer frames than this. On the evaluation set the
# people framed chest-up see them on 0-4 % of their frames (a selfie, a moving-camera close-up, half-body speakers),
# everyone else on 26 % or more.
UPPER_BODY_SEEN = 0.15
TRUNK = ('Spine1', 'Spine2', 'Chest')
TRUNK_SIGMA = 0.5    # s: the pelvis of a chest-up shot turns with the chest smoothed over this (Gaussian sigma)
TRANSL_ANCHOR = 0.1  # video: pull of each frame's root offset towards the GEM-X position (per m^2); weak on purpose
# Video image evidence (evidence.targets), set on the push-in clip of docs §22: depth 0.5 moved the akimbo wrist a
# third of the way, 5 reaches the evidence (wrist 18 -> 6 cm in front of the pelvis) with the 2D error unchanged;
# finger shape 1.0 takes the gripping hand from 3-6 cm to 1 cm off the evidence, more buys nothing.
EVIDENCE_DEPTH = 5.0  # pull of an arm joint's depth relative to the hips towards SAM 3D Body's (per m^2), replacing DEPTH_ANCHOR
EVIDENCE_SHAPE = 1.0  # pull of a finger joint's offset from its wrist towards SAM 3D Body's (per m^2)
PATIENCE = 30        # stop once the loss has not improved by RELATIVE_GAIN for this many steps
RELATIVE_GAIN = 1e-4


def keypoint_weights(keypoints, joint_names, *, min_confidence=MIN_CONFIDENCE, finger_weight=FINGER_WEIGHT, foot_min_confidence=None):
    """Per-joint weight: VitPose confidence, zero below min_confidence (foot_min_confidence for ankles and toes when
    given), fingers damped."""
    confidence = np.asarray(keypoints, dtype=np.float64)[:, 2]
    fingers = np.array([any(f in name for f in FINGERS) for name in joint_names])
    feet = np.array([name.endswith(FOOT_JOINTS) for name in joint_names])
    floor = np.where(feet, min_confidence if foot_min_confidence is None else foot_min_confidence, min_confidence)
    return np.where(confidence >= floor, confidence, 0.0) * np.where(fingers, finger_weight, 1.0)


def fit_pose(forward, global_orient, body_pose, keypoints, K, box_size, weights, *,
             anchor=ANCHOR, depth_anchor=DEPTH_ANCHOR, steps=STEPS, lr=LEARNING_RATE, patience=PATIENCE):
    """Refine (global_orient, body_pose) axis-angles so `forward`'s joints project onto the keypoints.

    forward(global_orient (1,3), body_pose (1,N)) -> camera-frame joints (J,3), differentiable torch.
    Returns (global_orient, body_pose, info) as numpy; the inputs come back unchanged when the fit
    does not lower the 2D error. info: {accepted, error_before, error_after (mean px / box %),
    depth_shift_cm (largest change of a joint's depth relative to the hips), steps, seconds}.
    """
    import torch
    started = time.time()
    with torch.enable_grad():
        kp = torch.as_tensor(np.asarray(keypoints)[:, :2], dtype=torch.float32)
        cam = torch.as_tensor(np.asarray(K), dtype=torch.float32)
        w = torch.as_tensor(np.asarray(weights), dtype=torch.float32)
        go0 = torch.as_tensor(np.asarray(global_orient), dtype=torch.float32).reshape(1, -1)
        bp0 = torch.as_tensor(np.asarray(body_pose), dtype=torch.float32).reshape(1, -1)
        go, bp = go0.clone().requires_grad_(True), bp0.clone().requires_grad_(True)
        scale = float(box_size) or 1.0

        def residual(joints):
            uv = (cam @ joints.T).T
            uv = uv[:, :2] / uv[:, 2:].clamp(min=1e-4)
            return ((uv - kp) / scale).pow(2).sum(1)

        def depth(joints):
            return joints[:, 2] - joints[0, 2]

        def error(g, b):  # weighted mean distance, % of the person box
            with torch.no_grad():
                return float((w * residual(forward(g, b)).sqrt()).sum() / w.sum().clamp(min=1e-6) * 100)

        with torch.no_grad():
            depth0 = depth(forward(go0, bp0))
        before = error(go0, bp0)
        optimizer = torch.optim.Adam([go, bp], lr=lr)
        best, stale, done = math.inf, 0, 0
        for done in range(1, steps + 1):
            optimizer.zero_grad()
            joints = forward(go, bp)
            loss = ((w * residual(joints)).sum() + anchor * ((bp - bp0).pow(2).sum() + (go - go0).pow(2).sum())
                    + depth_anchor * (depth(joints) - depth0).pow(2).sum())
            if not torch.isfinite(loss):
                break
            loss.backward()
            optimizer.step()
            value = float(loss.detach())
            stale = stale + 1 if value > best * (1 - RELATIVE_GAIN) else 0
            best = min(best, value)
            if stale >= patience:
                break
        finite = bool(torch.isfinite(go).all() and torch.isfinite(bp).all())
        after = error(go.detach(), bp.detach()) if finite else math.inf
        accepted = after < before
        with torch.no_grad():
            shift = float((depth(forward(go, bp)) - depth0).abs().max()) * 100 if accepted else 0.0
    info = {'accepted': accepted, 'error_before': round(before, 3), 'error_after': round(after if accepted else before, 3),
            'depth_shift_cm': round(shift, 1), 'steps': done, 'seconds': round(time.time() - started, 3)}
    if not accepted:
        return np.asarray(global_orient, dtype=np.float64), np.asarray(body_pose, dtype=np.float64), info
    return (go.detach().numpy().reshape(np.shape(global_orient)).astype(np.float64),
            bp.detach().numpy().reshape(np.shape(body_pose)).astype(np.float64), info)


def fit_sequence(forward, global_orient, body_pose, keypoints, K, box_sizes, weights, *,
                 anchor=ANCHOR, depth_anchor=DEPTH_ANCHOR, transl_anchor=TRANSL_ANCHOR, steps=STEPS, lr=LEARNING_RATE,
                 patience=PATIENCE, evidence=None):
    """Batched fit_pose over N frames at once (video keyframes): accepted or rejected per frame.

    Unlike a photo, each frame also gets a root offset (camera frame, metres, weakly anchored to zero):
    on a close-up GEM-X places a cut-off person too far and too high (a push-in left the hips at 65 % of
    the frame height where the video has them at 92 %), and rotations alone cannot move the body.
    forward(global_orient (N,3), body_pose (N,M)) -> camera-frame joints (N,J,3), differentiable torch.
    evidence (evidence.targets): where it has a target, an arm joint's depth relative to the hips is pulled
    to the image evidence instead of the GEM-X estimate, and a finger joint's offset from its wrist to the
    evidence's; nothing else changes.
    Returns (global_orient, body_pose, offset (N,3), info) as numpy; rejected frames keep their input values
    and a zero offset. info: {accepted (fraction), error_before, error_after (median %), worst_before,
    worst_after (largest per-frame %), offset_cm (largest offset), steps, seconds, frame_errors (N,) the final
    per-frame 2D error, an array for the caller, not for diagnostics}.
    """
    import torch
    started = time.time()
    with torch.enable_grad():
        kp = torch.as_tensor(np.asarray(keypoints)[..., :2], dtype=torch.float32)
        cam = torch.as_tensor(np.asarray(K), dtype=torch.float32)
        w = torch.as_tensor(np.asarray(weights), dtype=torch.float32)
        scale = torch.as_tensor(np.asarray(box_sizes), dtype=torch.float32).clamp(min=1.0)[:, None]
        go0 = torch.as_tensor(np.asarray(global_orient), dtype=torch.float32)
        bp0 = torch.as_tensor(np.asarray(body_pose), dtype=torch.float32)
        go, bp = go0.clone().requires_grad_(True), bp0.clone().requires_grad_(True)
        offset = torch.zeros((len(go0), 3), dtype=torch.float32, requires_grad=True)

        def residual(joints):
            uv = joints @ cam.T
            uv = uv[..., :2] / uv[..., 2:].clamp(min=1e-4)
            return ((uv - kp) / scale[..., None]).pow(2).sum(-1)

        def error(joints):  # per frame: weighted mean distance, % of the person box
            return (w * residual(joints).sqrt()).sum(1) / w.sum(1).clamp(min=1e-6) * 100

        with torch.no_grad():
            joints0 = forward(go0, bp0)
            depth0 = joints0[..., 2] - joints0[:, :1, 2]
            before = error(joints0)
        gem_depth = torch.ones_like(depth0)
        if evidence is not None:
            ev_depth = torch.as_tensor(np.asarray(evidence['depth']), dtype=torch.float32)
            ev_depth_mask = torch.as_tensor(np.asarray(evidence['depth_mask']), dtype=torch.float32)
            ev_shape = torch.as_tensor(np.asarray(evidence['shape']), dtype=torch.float32)
            ev_shape_mask = torch.as_tensor(np.asarray(evidence['shape_mask']), dtype=torch.float32)[..., None]
            ev_base = torch.as_tensor(np.asarray(evidence['shape_base']), dtype=torch.long)
            gem_depth = 1 - ev_depth_mask

        def evidence_loss(joints):
            if evidence is None:
                return 0.0
            rel = joints[..., 2] - joints[:, :1, 2]
            offsets = joints - joints[:, ev_base]
            return (EVIDENCE_DEPTH * (ev_depth_mask * (rel - ev_depth).pow(2)).sum()
                    + EVIDENCE_SHAPE * (ev_shape_mask * (offsets - ev_shape).pow(2)).sum())
        optimizer = torch.optim.Adam([go, bp, offset], lr=lr)
        best, stale, done = math.inf, 0, 0
        for done in range(1, steps + 1):
            optimizer.zero_grad()
            joints = forward(go, bp) + offset[:, None]
            loss = ((w * residual(joints)).sum() + anchor * ((bp - bp0).pow(2).sum() + (go - go0).pow(2).sum())
                    + depth_anchor * (gem_depth * ((joints[..., 2] - joints[:, :1, 2]) - depth0).pow(2)).sum()
                    + transl_anchor * offset.pow(2).sum() + evidence_loss(joints))
            if not torch.isfinite(loss):
                break
            loss.backward()
            optimizer.step()
            value = float(loss.detach())
            stale = stale + 1 if value > best * (1 - RELATIVE_GAIN) else 0
            best = min(best, value)
            if stale >= patience:
                break
        with torch.no_grad():
            after = error(forward(go, bp) + offset[:, None])
            keep = torch.isfinite(after) & (after < before)
            go_out = torch.where(keep[:, None], go, go0)
            bp_out = torch.where(keep[:, None], bp, bp0)
            offset_out = torch.where(keep[:, None], offset, torch.zeros_like(offset))
            final = torch.where(keep, after, before)
    info = {'frame_errors': final.numpy().astype(np.float64), 'accepted': round(float(keep.float().mean()), 3),
            'error_before': round(float(before.median()), 3),
            'error_after': round(float(final.median()), 3), 'worst_before': round(float(before.max()), 3),
            'worst_after': round(float(final.max()), 3), 'offset_cm': round(float(offset_out.norm(dim=1).max()) * 100, 1),
            'steps': done, 'seconds': round(time.time() - started, 3)}
    return (go_out.numpy().astype(np.float64), bp_out.numpy().astype(np.float64),
            offset_out.numpy().astype(np.float64), info)


def carry_world(world_orient, incam_before, incam_after):
    """Apply a camera-frame change of the root rotation to the gravity-aligned one (camera stays put)."""
    world_from_cam = rodrigues(world_orient) @ rodrigues(incam_before).T
    return axis_angle(world_from_cam @ rodrigues(incam_after))


def _slerp(a, b, t):
    """Row-wise quaternion slerp (x, y, z, w), t in [0, 1] per row."""
    dot = np.sum(a * b, 1)
    b = np.where(dot[:, None] < 0, -b, b)
    dot = np.clip(np.abs(dot), -1.0, 1.0)
    theta = np.arccos(dot)
    small = theta < 1e-6
    sin = np.where(small, 1.0, np.sin(theta))
    wa = np.where(small, 1 - t, np.sin((1 - t) * theta) / sin)
    wb = np.where(small, t, np.sin(t * theta) / sin)
    out = wa[:, None] * a + wb[:, None] * b
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def hold_unseen_legs(body_pose, confidence, joint_names, fps, outside=None):
    """Hold leg joints whose child keypoint has left the frame at their last seen rotation.

    body_pose (L, 3 * (J - 1)) axis-angles for joint_names[1:]; confidence (L, J) keypoint confidence.
    Per leg joint the child's confidence, median-filtered over UNSEEN_SECONDS, sets a weight from 0 (at or
    above UNSEEN, a reliable sighting) to 1 (at or below UNSEEN_FULL), so a foot guessed at 0.55 below the
    frame never counts as seen and lends its folded leg; the rotation is slerped from the GEM-X one towards the
    joint's rotation at the nearest earlier fully seen frame (the next one before the leg is first seen;
    the straight T-pose leg when it never is). outside(body_pose) -> (L, J) bool says which joints of a
    pose project outside the image: a held candidate whose child stays inside the frame means the keypoint
    was occluded, not cut off, and GEM-X's guess is kept there (a dancer's ankle hidden behind the other
    leg). Returns (body_pose, held): held (L,) is the largest weight.
    """
    from scipy.ndimage import median_filter, uniform_filter1d
    from scipy.spatial.transform import Rotation
    names = list(joint_names)
    pose = np.asarray(body_pose, dtype=np.float64).reshape(len(body_pose), len(names) - 1, 3).copy()
    confidence = np.asarray(confidence, dtype=np.float64)
    frames = len(pose)
    window = max(1, int(round(fps * UNSEEN_SECONDS))) | 1
    chains = []
    for joint, child in LEG_CHAINS:
        if joint not in names or child not in names:
            continue
        seen = median_filter(confidence[:, names.index(child)], size=window, mode='nearest')
        weight = np.clip((UNSEEN - seen) / (UNSEEN - UNSEEN_FULL), 0.0, 1.0)
        if not weight.any():
            continue
        j = names.index(joint) - 1
        full = weight == 0
        if full.any():
            last = np.maximum.accumulate(np.where(full, np.arange(frames), -1))
            source = np.where(last >= 0, last, np.argmax(full))
            target = Rotation.from_rotvec(pose[source, j]).as_quat()
        else:
            target = np.tile([0.0, 0.0, 0.0, 1.0], (frames, 1))
        chains.append((j, names.index(child), weight, target))
    held = np.zeros(frames)
    if not chains:
        return pose.reshape(frames, -1), held
    if outside is not None:
        candidate = pose.copy()
        for j, _, weight, target in chains:
            candidate[weight > 0, j] = Rotation.from_quat(target[weight > 0]).as_rotvec()
        cut = np.asarray(outside(candidate.reshape(frames, -1)), dtype=np.float64)
        chains = [(j, c, weight * np.clip(uniform_filter1d(cut[:, c], window, mode='nearest'), 0.0, 1.0), target)
                  for j, c, weight, target in chains]
    for j, _, weight, target in chains:
        if not weight.any():
            continue
        current = Rotation.from_rotvec(pose[:, j]).as_quat()
        pose[:, j] = Rotation.from_quat(_slerp(current, target, weight)).as_rotvec()
        held = np.maximum(held, weight)
    return pose.reshape(frames, -1), held


def upper_body_only(confidence, joint_names):
    """Whether a video person is framed from the chest up: hips (LeftLeg/RightLeg) seen on under UPPER_BODY_SEEN of
    the frames. confidence (L, J)."""
    names = list(joint_names)
    hips = [names.index(n) for n in ('LeftLeg', 'RightLeg') if n in names]
    return bool(hips) and float(np.mean((np.asarray(confidence, dtype=np.float64)[:, hips] >= VISIBLE).any(1))) < UPPER_BODY_SEEN


def steady_trunk(global_orient, body_pose, joint_names, fps):
    """A chest-up person standing straight under the chest: (global_orient, body_pose).

    Nothing below the chest is seen, so the fit bent the spine to match the close-up's perspective (a fisheye selfie
    folded to 116 deg at the waist) and the hips and legs swung with every turn of it. The chest keeps its rotation,
    so everything from the chest up (head, arms, hands) is unchanged; the pelvis turns with the chest smoothed over
    TRUNK_SIGMA, the spine takes the small remainder in three equal parts, and the legs hang straight (their T-pose).
    global_orient (L, 3) and body_pose (L, 3 * (J - 1)) axis-angles for joint_names[1:]. The caller moves the root so
    the chest stays where it was."""
    from scipy.ndimage import gaussian_filter1d
    from scipy.spatial.transform import Rotation
    names = list(joint_names)
    frames = len(global_orient)
    pose = np.asarray(body_pose, dtype=np.float64).reshape(frames, len(names) - 1, 3).copy()
    trunk = [names.index(n) - 1 for n in TRUNK]
    chest = Rotation.from_rotvec(np.asarray(global_orient, dtype=np.float64))
    for j in trunk:
        chest = chest * Rotation.from_rotvec(pose[:, j])
    quats = chest.as_quat()
    for f in range(1, frames):
        if np.dot(quats[f], quats[f - 1]) < 0:
            quats[f] *= -1
    pelvis = Rotation.from_quat(gaussian_filter1d(quats, max(1e-3, TRUNK_SIGMA * fps), axis=0, mode='nearest'))
    rest = (pelvis.inv() * chest).as_rotvec() / len(trunk)
    for j in trunk:
        pose[:, j] = rest
    for joint, _ in LEG_CHAINS:
        if joint in names:
            pose[:, names.index(joint) - 1] = 0.0
    return pelvis.as_rotvec(), pose.reshape(frames, -1)
