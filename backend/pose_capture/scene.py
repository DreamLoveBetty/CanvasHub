"""Engine output -> pose sequence contract (docs/POSE_REFERENCE_REBUILD_PLAN.md §4.1). numpy only.

GEM-X returns every person in the OpenCV camera frame (x right, y down, z forward) and in a
gravity-aligned world (+Y up) whose yaw is arbitrary per person. The editor needs one shared world:
  * gravity from the world/camera orientation pair of each person (score-weighted),
  * no yaw: the camera looks along -Z, so a person facing the camera faces +Z,
  * the lowest joint of all people on the floor (y = 0), people centred on the origin.
Rotations stay SOMA's T-pose-relative axis-angles; only the Hips (global) rotation is re-expressed.
"""
import base64
import math

import numpy as np

JOINTS = 77
HEAD_END = 7  # index in the 77 public joints (Hips first)
MANNEQUIN_HEIGHT = 1.6775  # m: the neutral mannequin at 175 cm, HeadEnd above the lowest joint (its GLB head_end)
ASPECTS = {'1:1': 1, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16, '3:2': 3 / 2, '2:3': 2 / 3}
SWATCHES = ['#ff6b3d', '#3e8ef7', '#30a46c', '#d6409f', '#f5b83d', '#8e7cf8']
FINGER = ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky')
FEET = ('LeftFoot', 'RightFoot', 'LeftToeBase', 'RightToeBase', 'LeftToeEnd', 'RightToeEnd')  # the editor's ground joints
VISIBLE = 0.5  # GEM-X's own threshold: a keypoint below this confidence is treated as not visible
LIFT_SECONDS = 1.0  # camera-view height is smoothed over this window; faster vertical motion comes from GEM-X's world
CONTACT_SPEED = 0.35   # m/s: a lowest foot moving slower than this stands on the floor (dancers' feet move ~0.5-1)
CONTACT_SECONDS = 0.2  # foot positions are averaged over this window before their speed is taken (depth jitter)
GROUND_RATIO = 1.5     # a person's distance is rescaled by at most this factor (or its inverse) to share the floor
GROUND_DROP = 0.2      # m: the floor must lie at least this far below the camera for foot heights to settle distances
GROUND_SEEN = 0.7      # feet that may move a person onto the shared floor must be really seen (VitPose guesses
                       # off-screen feet around 0.5: three half-body dancers were rescaled to the 1.5 limit)


def rodrigues(vector):
    v = np.asarray(vector, dtype=np.float64)
    angle = np.linalg.norm(v)
    if angle < 1e-12:
        return np.eye(3)
    k = v / angle
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * K @ K


def axis_angle(matrix):
    """Rotation matrix -> axis-angle via a unit quaternion (Shepperd), stable near 180 degrees."""
    m = np.asarray(matrix, dtype=np.float64)
    trace = np.trace(m)
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = np.array([(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s])
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = np.array([0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s])
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = np.array([(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s])
    else:
        s = 2.0 * math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = np.array([(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s])
    q /= np.linalg.norm(q)
    if q[3] < 0:
        q = -q
    sin_half = np.linalg.norm(q[:3])
    if sin_half < 1e-12:
        return np.zeros(3)
    return q[:3] / sin_half * 2 * math.atan2(sin_half, q[3])


def nearest_aspect(width, height):
    ratio = width / height
    return min(ASPECTS, key=lambda key: abs(math.log(ASPECTS[key] / ratio)))


def camera_to_world(people):
    """Rows are the editor world axes in OpenCV camera coordinates (camera -> world rotation).
    Video people carry per-frame orientations; every 5th frame votes for the gravity direction. A person framed
    from the chest up (video upper_body) votes with their own pelvis axis: GEM-X has no legs or floor to find
    gravity from (a fisheye selfie leaned 45 deg on median), and such a person stands upright on the whole."""
    up = np.zeros(3)
    for person in people:
        incam = np.asarray(person['incam']['global_orient'], dtype=np.float64).reshape(-1, 3)[::5]
        world = np.asarray(person['global']['global_orient'], dtype=np.float64).reshape(-1, 3)[::5]
        weight = max(person.get('score', 1.0), 1e-3) / len(incam)
        for cam_vec, world_vec in zip(incam, world):
            world_from_cam = rodrigues(cam_vec).T if person.get('upper_body') else rodrigues(world_vec) @ rodrigues(cam_vec).T
            up += weight * (world_from_cam.T @ np.array([0.0, 1.0, 0.0]))
    if np.linalg.norm(up) < 1e-9:
        up = np.array([0.0, -1.0, 0.0])
    up /= np.linalg.norm(up)
    forward = np.array([0.0, 0.0, 1.0])
    horizontal = forward - forward.dot(up) * up
    if np.linalg.norm(horizontal) < 1e-6:  # looking straight down/up: keep image-up as "forward"
        horizontal = np.array([0.0, -1.0, 0.0]) - np.array([0.0, -1.0, 0.0]).dot(up) * up
    horizontal /= np.linalg.norm(horizontal)
    z_axis = -horizontal
    x_axis = np.cross(up, z_axis)
    return np.stack([x_axis, up, z_axis])


def body_keypoint_error(person, joint_names=None):
    """Median 2D error of the projected joints vs the detected keypoints, % of the person box."""
    joints, K, keypoints = person['incam']['joints'], person['K'], person['keypoints']
    uv = (K @ joints.T).T
    uv = uv[:, :2] / np.maximum(uv[:, 2:], 1e-6)
    mask = keypoints[:, 2] > 0.5
    if joint_names is not None:
        mask &= np.array([not any(f in name for f in FINGER) for name in joint_names])
    if not mask.any():
        return None
    return float(np.median(np.linalg.norm(uv[mask] - keypoints[mask, :2], axis=1)) / person['bbx_xys'][2] * 100)


def encode_rotations(values):
    data = np.asarray(values, dtype=np.float32).reshape(-1)
    return 'base64:' + base64.b64encode(data.tobytes()).decode()


def build_snapshot(result, *, joint_names=None, asset_id=None, engine_version='', updated_at=0):
    people = result['people']
    width, height = int(result['width']), int(result['height'])
    if not people:
        return {'version': 1, 'skeleton': 'soma77', 'fps': 30, 'people': [], 'cameras': [], 'active_camera': None,
                'source': {'kind': 'photo', 'engine': 'gem-x-lite', 'engine_version': engine_version, 'input_asset_id': asset_id},
                'updated_at': updated_at}
    # A single photo cannot fix absolute body size (distance and build trade off), and the engine's
    # identities run tall. Keep only relative heights, with the median person at 175 cm, and scale the
    # whole scene about the camera by the same factor so every body still projects onto the photo.
    heights = [float(p.get('rest_height') or MANNEQUIN_HEIGHT) for p in people]
    median_height = float(np.median(heights)) or MANNEQUIN_HEIGHT
    scale = MANNEQUIN_HEIGHT / median_height
    world_from_cam = camera_to_world(people)
    world_joints = [scale * (world_from_cam @ p['incam']['joints'].T).T for p in people]
    feet = [joint_names.index(n) for n in FEET if n in joint_names] if joint_names is not None else []
    lowest = [float(j[feet or slice(None), 1].min()) for j in world_joints]
    # Monocular depth is per person, so people rarely share one floor exactly. Keep each one's height
    # above the lowest person as `floor_offset`; the editor lifts that character so the photo camera
    # still matches the photo, and the user can zero it to stand everyone on the floor.
    floor = min(lowest)
    hips = np.array([j[0] for j in world_joints])
    offset = np.array([-hips[:, 0].mean(), -floor, -hips[:, 2].mean()])
    out_people = []
    for index, (person, joints) in enumerate(zip(people, world_joints)):
        rotations = np.zeros((JOINTS, 3))
        rotations[0] = axis_angle(world_from_cam @ rodrigues(person['incam']['global_orient']))
        rotations[1:] = np.asarray(person['incam']['body_pose'], dtype=np.float64).reshape(JOINTS - 1, 3)
        height_cm = int(round(min(200, max(140, 175 * heights[index] / median_height))))
        error = body_keypoint_error(person, joint_names)
        out_people.append({
            'id': f'p{index + 1}', 'label': f'角色 {chr(65 + index)}', 'color': SWATCHES[index % len(SWATCHES)],
            'identity': {'model': 'mhr', 'coeffs': [round(float(v), 5) for v in person['incam'].get('identity_coeffs', [])],
                         'scale_params': [round(float(v), 5) for v in person['incam'].get('scale_params', [])]},
            'height_cm': height_cm, 'floor_offset': round(lowest[index] - floor, 3),
            **({'body_id': person['body_id']} if person.get('body_id') else {}),
            'frames': {'count': 1, 'transl': [[round(float(v), 5) for v in joints[0] + offset]],
                       'rotations': encode_rotations(rotations)},
            'confidence': [round(float(person.get('score', 0)), 4)], 'overrides': [],
            'diagnostics': {'reprojection_median_pct': None if error is None else round(error, 2),
                            **({'keypoint_fit': person['fit']} if person.get('fit') else {}),
                            'keypoint_confidence': round(float(np.mean(person['keypoints'][:, 2])), 3),
                            'box_xyxy': [round(float(v), 1) for v in person['box_xyxy']]},
        })
    camera_world = offset  # the camera sits at the OpenCV origin
    forward = world_from_cam @ np.array([0.0, 0.0, 1.0])
    distance = max(0.5, float(np.dot(hips[0] + offset - camera_world, forward)))
    right = world_from_cam @ np.array([1.0, 0.0, 0.0])
    roll = math.degrees(math.asin(max(-1.0, min(1.0, right[1]))))
    K = np.asarray(people[0]['K'], dtype=np.float64)
    camera = {'id': 'photo', 'label': '照片机位', 'position': [round(float(v), 4) for v in camera_world],
              'target': [round(float(v), 4) for v in camera_world + forward * distance],
              'focal_mm': int(round(min(200, max(14, 24 * K[1, 1] / height)))), 'aspect': nearest_aspect(width, height),
              'width': width, 'height': height, 'roll_deg': round(roll, 2)}
    return {'version': 1, 'skeleton': 'soma77', 'fps': 30, 'people': out_people, 'cameras': [camera],
            'active_camera': 'photo',
            'source': {'kind': 'photo', 'engine': 'gem-x-lite', 'engine_version': engine_version, 'input_asset_id': asset_id},
            'updated_at': updated_at}


def smooth(values, window=5):
    """Centred moving average along the first axis (edges use the available neighbours)."""
    values = np.asarray(values, dtype=np.float64)
    if len(values) < 3 or window < 2:
        return values
    half = window // 2
    padded = np.concatenate([values[:1].repeat(half, 0), values, values[-1:].repeat(half, 0)])
    kernel = np.ones(window) / window
    return np.stack([np.convolve(padded[:, k], kernel, mode='valid') for k in range(values.shape[1])], 1)


def running_median(values, window):
    """Centred running median. The ends are padded point-symmetrically about a line fitted to the first and
    last half-windows, so a trend still under way at the clip's edge (a push-in to the last frame) carries
    on instead of folding back, and one noisy edge sample does not set the padding."""
    from scipy.ndimage import median_filter
    values = np.asarray(values, dtype=np.float64)
    half = window // 2
    if half < 1 or len(values) <= half + 1:
        return median_filter(values, size=window, mode='nearest') if len(values) else values
    t = np.arange(half + 1)
    first = np.polyval(np.polyfit(t, values[:half + 1], 1), 0)
    last = np.polyval(np.polyfit(t, values[-half - 1:], 1), half)
    padded = np.r_[2 * first - values[half:0:-1], values, 2 * last - values[-2:-half - 2:-1]]
    return median_filter(padded, size=window, mode='nearest')[half:half + len(values)]


def _floor(joints, keypoints, pick, fps=30.0, shift=None):
    """Median lowest-foot height over the frames where that foot is visible and planted (slower than
    CONTACT_SPEED). A median over every visible frame put the floor halfway up a backflip, whose feet are in
    view in the air for half the clip, and sank the standing figure 70 cm into it. Too few planted frames
    (under CONTACT_SECONDS' worth) fall back to all visible ones, and no visible feet to every frame.
    shift (F,) is added to each frame's height first: where the editor will put that frame's hips minus
    where the camera view has them, so planted feet stand on the floor as rendered.
    Returns (height, planted): planted is whether enough of those frames show the feet at GROUND_SEEN."""
    from scipy.ndimage import uniform_filter1d
    feet = np.asarray(joints, dtype=np.float64)[:, pick]
    lowest = feet[..., 1].min(1) + (0.0 if shift is None else np.asarray(shift, dtype=np.float64))
    usable = np.ones(len(lowest), bool)
    if keypoints is not None and len(keypoints) == len(lowest):
        visible = np.asarray(keypoints, dtype=np.float64)[:, pick, 2].max(1) >= VISIBLE
        if visible.any():
            usable = visible
    window = max(3, int(round(fps * CONTACT_SECONDS)) | 1)
    if len(lowest) > window:
        steady = uniform_filter1d(feet, window, axis=0, mode='nearest')  # a median keeps fast jitter's extremes
        speed = np.linalg.norm(np.gradient(steady, axis=0), axis=-1)[np.arange(len(lowest)), feet[..., 1].argmin(1)] * fps
        planted = usable & (speed < CONTACT_SPEED)
        if planted.sum() >= window:
            seen = keypoints is not None and len(keypoints) == len(lowest) and \
                (planted & (np.asarray(keypoints, dtype=np.float64)[:, pick, 2].max(1) >= GROUND_SEEN)).sum() >= window
            return float(np.median(lowest[planted])), bool(seen)
    return float(np.median(lowest[usable])), False


def common_ground(floors, planted, limits=None):
    """(floor, scales): one floor height for everyone and each person's distance factor.

    floors: each person's planted-foot height in the gravity-aligned camera frame (negative below the camera);
    planted: whether it was measured on planted feet really seen. Monocular depth is per person: a person placed
    k times too far sits k times too low or high, so the people of a group dance floated 10-24 cm above the
    lowest one. Scaling a person's camera-frame joints by k moves them along the camera rays, which keeps
    their image exactly, and scales their size by k; k = floor / their floor stands them on the shared floor,
    the median of the planted ones (one person: k = 1). With fewer than two such people, or a floor less
    than GROUND_DROP below the camera (a low camera cannot tell distance from foot height), the lowest
    person's floor is kept as before and nobody moves. limits (lows, highs) further bound each factor: the
    editor shows heights of 140-200 cm only, and a person scaled past that would be drawn at the bound, off
    their camera ray (a 0.75 dancer at 131 cm was drawn at 140 with her feet below the video's).
    """
    floors, planted = np.asarray(floors, dtype=np.float64), np.asarray(planted, bool)
    if planted.sum() < 2 or (floors[planted] > -GROUND_DROP).any():
        return float(floors.min()), np.ones(len(floors))
    floor = float(np.median(floors[planted]))
    low, high = (np.full(len(floors), 1 / GROUND_RATIO), np.full(len(floors), GROUND_RATIO)) if limits is None else \
        (np.maximum(1 / GROUND_RATIO, limits[0]), np.minimum(GROUND_RATIO, limits[1]))
    return floor, np.where(planted, np.clip(floor / floors, low, high), 1.0)


def build_sequence(result, *, joint_names=None, asset_id=None, engine_version='', updated_at=0):
    """Video result -> the §4.1 pose-sequence contract with N frames per person.

    Per person and frame: Hips world rotation plus the 76 T-pose-relative rotations (base64 float32,
    frames x 77 x 3), the Hips world position, and `lift`, the height of the lowest foot above the shared
    floor that puts the hips where the video shows them (held legs out of view give negative values), and
    `hips`, that hips height itself: the editor places the figure by it, so a body whose legs are longer
    or shorter than the recognised skeleton (the female, male or recognised mannequin) still lines up with
    the video; `lift` remains for results that predate `hips`.
    `start` is the person's first frame in the clip. Heights follow build_snapshot: relative only, the
    median person at 175 cm, the whole scene scaled about the camera so it still projects onto the video.
    """
    people = result['people']
    width, height, fps = int(result['width']), int(result['height']), float(result['fps'])
    source = {'kind': 'video', 'engine': 'gem-x-lite', 'engine_version': engine_version, 'input_asset_id': asset_id,
              'frames': int(result['frames']), 'source_frames': int(result.get('source_frames') or result['frames']),
              'truncated': bool(result.get('truncated')), 'backend': result.get('backend'), 'evidence': result.get('evidence'),
              'tracker': result.get('tracker')}
    base = {'version': 1, 'skeleton': 'soma77', 'fps': round(fps, 4), 'frame_count': int(result['frames']), 'source': source,
            'updated_at': updated_at}
    if not people:
        return {**base, 'people': [], 'cameras': [], 'active_camera': None}
    heights = [float(p.get('rest_height') or MANNEQUIN_HEIGHT) for p in people]
    median_height = float(np.median(heights)) or MANNEQUIN_HEIGHT
    scale = MANNEQUIN_HEIGHT / median_height
    world_from_cam = camera_to_world(people)
    world_joints = [scale * np.einsum('ij,fkj->fki', world_from_cam, p['incam']['joints']) for p in people]
    feet = [joint_names.index(n) for n in FEET if n in joint_names] if joint_names is not None else []
    pick = feet or slice(None)
    # Each person's hips follow the camera view: its height's running median over LIFT_SECONDS (camera-space
    # depth jitters frame to frame, and along the camera ray that became vertical bobbing: a dancer standing in
    # place floated 13 cm on median), plus the fast part of GEM-X's own world trajectory (jumps). GEM-X's world
    # alone kept the feet on its floor but drifted from the video: on a push-in the hips sit 25 cm above where
    # the camera sees them. The floor is where the recognised feet stand while planted in view (legs out of
    # view, guessed by GEM-X or held by hold_unseen_legs, are not evidence of it), measured after that hips
    # smoothing: a dancer is planted when she sinks below her running median, and her feet floated 3 cm.
    # `lift` is where the editor stands the lowest foot so the hips land there; held legs reach below the floor.
    window = max(3, int(round(fps * LIFT_SECONDS)) | 1)
    slow = lambda v: running_median(v, window)  # a median keeps short jumps out of the trend
    # A person framed from the chest up (upper_body) has no feet on a floor to keep still and only the image to go by:
    # their hips follow the camera view as it is (the median made a selfie's head trail the footage).
    trends = []
    for person, joints in zip(people, world_joints):
        if person.get('upper_body'):
            trends.append(joints[:, 0, 1].copy())
            continue
        trend = smooth(slow(joints[:, 0, 1])[:, None])[:, 0]
        world = person.get('global', {}).get('joints')
        if world is not None and len(world) == len(trend):
            gem = scale * np.asarray(world, dtype=np.float64)[:, 0, 1]
            trend = trend + gem - slow(gem)
        trends.append(trend)
    floors, planted = zip(*(_floor(scale * np.einsum('ij,fkj->fki', world_from_cam, p['incam'].get('observed_joints', p['incam']['joints'])),
                                   p.get('keypoints'), pick, fps, shift=trend - joints[:, 0, 1])
                            for p, joints, trend in zip(people, world_joints, trends)))
    shown = np.array([175 * h / median_height for h in heights])               # height_cm before the ground
    floor, ground = common_ground(floors, planted, (np.minimum(1.0, 140 / shown), np.maximum(1.0, 200 / shown)))
    world_joints = [joints * k for joints, k in zip(world_joints, ground)]
    trends = [trend * k for trend, k in zip(trends, ground)]
    lifts, hips_heights = [], []
    for joints, trend in zip(world_joints, trends):
        target = trend - floor
        hips_heights.append(target)
        lifts.append(target - (joints[:, 0, 1] - joints[:, pick, 1].min(1)))  # hips above the figure's lowest foot
    first_hips = np.array([j[0, 0] for j in world_joints])
    offset = np.array([-first_hips[:, 0].mean(), -floor, -first_hips[:, 2].mean()])
    out_people = []
    for index, (person, joints) in enumerate(zip(people, world_joints)):
        count = len(joints)
        incam = person['incam']
        rotations = np.zeros((count, JOINTS, 3), dtype=np.float32)
        orient = np.asarray(incam['global_orient'], dtype=np.float64).reshape(count, 3)
        for f in range(count):
            rotations[f, 0] = axis_angle(world_from_cam @ rodrigues(orient[f]))
        rotations[:, 1:] = np.asarray(incam['body_pose'], dtype=np.float64).reshape(count, JOINTS - 1, 3)
        transl = joints[:, 0] + offset if person.get('upper_body') else smooth(joints[:, 0] + offset)  # depth jitters frame to frame
        lift = lifts[index]
        confidence = np.asarray(person['keypoints'], dtype=np.float64)[..., 2].mean(1)
        out_people.append({
            'id': f'p{index + 1}', 'label': f'角色 {chr(65 + index)}', 'color': SWATCHES[index % len(SWATCHES)],
            'identity': {'model': 'mhr', 'coeffs': [round(float(v), 5) for v in (incam.get('identity_coeffs', [])
                                                                                if person.get('body_shape') is None else person['body_shape'])],
                         'scale_params': [round(float(v), 5) for v in incam.get('scale_params', [])]},
            'height_cm': int(round(min(200, max(140, 175 * ground[index] * heights[index] / median_height)))),
            **({'body_id': person['body_id']} if person.get('body_id') else {}),
            'frames': {'start': int(person['start']), 'count': count,
                       'transl': [[round(float(v), 4) for v in row] for row in transl],
                       'lift': [round(float(v), 3) for v in lift], 'hips': [round(float(v), 3) for v in hips_heights[index]],
                       'rotations': encode_rotations(rotations)},
            'confidence': [round(float(v), 3) for v in confidence], 'overrides': [],
            'diagnostics': {'coverage': person.get('coverage'), 'keypoint_fit': person.get('fit'),
                            'keypoint_confidence': round(float(confidence.mean()), 3),
                            'held_legs': person.get('held_legs', 0.0), 'ground_scale': round(float(ground[index]), 3),
                            'upper_body': bool(person.get('upper_body'))},
        })
    camera_world = offset  # the camera sits at the OpenCV origin
    forward = world_from_cam @ np.array([0.0, 0.0, 1.0])
    distance = max(0.5, float(np.dot(world_joints[0][0, 0] + offset - camera_world, forward)))
    right = world_from_cam @ np.array([1.0, 0.0, 0.0])
    K = np.asarray(people[0]['K'], dtype=np.float64)
    camera = {'id': 'photo', 'label': '视频机位', 'position': [round(float(v), 4) for v in camera_world],
              'target': [round(float(v), 4) for v in camera_world + forward * distance],
              'focal_mm': int(round(min(200, max(14, 24 * K[1, 1] / height)))), 'aspect': nearest_aspect(width, height),
              'width': width, 'height': height, 'roll_deg': round(math.degrees(math.asin(max(-1.0, min(1.0, right[1])))), 2)}
    return {**base, 'people': out_people, 'cameras': [camera], 'active_camera': 'photo'}
