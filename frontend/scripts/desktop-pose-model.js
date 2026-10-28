// Pose reference node state (poseVersion 2): scene, output and render settings, plus the
// SOMA joint vocabulary, pose library and OpenPose mapping shared by the editor and exports.
// Pure data and math; no DOM, three.js or network. Backend JSON stays snake_case (see snapshot).
(function () {
  const TYPE = 'pose';
  const VERSION = 2;
  const WIDTH = 600;
  const HEIGHT = 640;
  const MAX_CHARACTERS = 6;
  const MAX_ELEVATION = 2; // m: how far a character's lowest foot may sit above the floor
  const MAX_CAMERAS = 8;
  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4.6" r="2.1"/><path d="M12 7.6v6.2M12 9.4 7.2 7.4M12 9.4l4.8-2M12 13.8l-3.4 6.6M12 13.8l3.4 6.6"/></svg>';
  // Node palette / connection menu glyph: shares the palette's animated icon language.
  const MENU_ICON = '<svg class="desk-node-icon desk-node-icon--pose" viewBox="0 0 24 24"><g class="desk-node-icon__pose-body"><circle cx="12" cy="5" r="1"></circle><path d="m9 20 3-6 3 6"></path><path d="m6 8 6 2 6-2"></path><path d="M12 10v4"></path></g></svg>';
  const PASSES = Object.freeze({mannequin: '人偶', openpose: 'OpenPose', depth: '深度', normal: '法线', mask: '遮罩'});
  const SIZES = Object.freeze({'1024': 1024, '1344': 1344, '1536': 1536, '2048': 2048});
  const ASPECTS = Object.freeze({'1:1': 1, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16, '3:2': 3 / 2, '2:3': 2 / 3});
  const SWATCHES = Object.freeze(['#ff6b3d', '#3e8ef7', '#30a46c', '#d6409f', '#f5b83d', '#8e7cf8']);
  // Body presets (SOMA neutral, Anny adult female / male) and recognised shapes `capture:<id>`.
  const BODIES = Object.freeze({neutral: '中性', female: '女性', male: '男性'});
  const CAPTURE_BODY = /^capture:([a-f0-9]{32})$/;
  const captureBodyId = body => CAPTURE_BODY.exec(String(body || ''))?.[1] || '';
  const isPresetBody = body => typeof body === 'string' && Object.hasOwn(BODIES, body);
  const normalizeBody = body => isPresetBody(body) || captureBodyId(body) ? body : 'neutral';
  const bodyLabel = body => isPresetBody(body) ? BODIES[body] : captureBodyId(body) ? '识别体型' : BODIES.neutral;
  const STATUSES = Object.freeze(['idle', 'exporting', 'exported', 'failed']);
  const ARTIFACT = /^\/api\/pose\/export\/artifact\?id=[a-f0-9]{32}$/;

  // SOMA-X public skeleton (index 0 is the virtual Root, its own parent).
  const SOMA_JOINTS = Object.freeze(['Root', 'Hips', 'Spine1', 'Spine2', 'Chest', 'Neck1', 'Neck2', 'Head', 'HeadEnd', 'Jaw', 'LeftEye', 'RightEye',
    'LeftShoulder', 'LeftArm', 'LeftForeArm', 'LeftHand',
    'LeftHandThumb1', 'LeftHandThumb2', 'LeftHandThumb3', 'LeftHandThumbEnd', 'LeftHandIndex1', 'LeftHandIndex2', 'LeftHandIndex3', 'LeftHandIndex4', 'LeftHandIndexEnd',
    'LeftHandMiddle1', 'LeftHandMiddle2', 'LeftHandMiddle3', 'LeftHandMiddle4', 'LeftHandMiddleEnd', 'LeftHandRing1', 'LeftHandRing2', 'LeftHandRing3', 'LeftHandRing4', 'LeftHandRingEnd',
    'LeftHandPinky1', 'LeftHandPinky2', 'LeftHandPinky3', 'LeftHandPinky4', 'LeftHandPinkyEnd',
    'RightShoulder', 'RightArm', 'RightForeArm', 'RightHand',
    'RightHandThumb1', 'RightHandThumb2', 'RightHandThumb3', 'RightHandThumbEnd', 'RightHandIndex1', 'RightHandIndex2', 'RightHandIndex3', 'RightHandIndex4', 'RightHandIndexEnd',
    'RightHandMiddle1', 'RightHandMiddle2', 'RightHandMiddle3', 'RightHandMiddle4', 'RightHandMiddleEnd', 'RightHandRing1', 'RightHandRing2', 'RightHandRing3', 'RightHandRing4', 'RightHandRingEnd',
    'RightHandPinky1', 'RightHandPinky2', 'RightHandPinky3', 'RightHandPinky4', 'RightHandPinkyEnd',
    'LeftLeg', 'LeftShin', 'LeftFoot', 'LeftToeBase', 'LeftToeEnd', 'RightLeg', 'RightShin', 'RightFoot', 'RightToeBase', 'RightToeEnd']);
  const JOINT_SET = new Set(SOMA_JOINTS);
  const MAIN_JOINTS = Object.freeze(['Hips', 'Spine1', 'Spine2', 'Chest', 'Neck1', 'Head', 'LeftShoulder', 'LeftArm', 'LeftForeArm', 'LeftHand',
    'RightShoulder', 'RightArm', 'RightForeArm', 'RightHand', 'LeftLeg', 'LeftShin', 'LeftFoot', 'LeftToeBase', 'RightLeg', 'RightShin', 'RightFoot', 'RightToeBase']);
  const FINGERS = Object.freeze(['Thumb', 'Index', 'Middle', 'Ring', 'Pinky']);
  // Two-bone chains the editor solves with IK when an end joint is dragged.
  const IK_CHAINS = Object.freeze({LeftHand: ['LeftArm', 'LeftForeArm', 'LeftHand'], RightHand: ['RightArm', 'RightForeArm', 'RightHand'],
    LeftFoot: ['LeftLeg', 'LeftShin', 'LeftFoot'], RightFoot: ['RightLeg', 'RightShin', 'RightFoot']});
  const LABELS = Object.freeze({Hips: '骨盆', Spine1: '腰椎', Spine2: '下胸椎', Chest: '胸部', Neck1: '颈部', Neck2: '上颈', Head: '头部', Jaw: '下颌',
    Shoulder: '锁骨', Arm: '上臂', ForeArm: '前臂', Hand: '手腕', Leg: '大腿', Shin: '小腿', Foot: '脚踝', ToeBase: '脚趾', ToeEnd: '脚尖', Eye: '眼',
    Thumb: '拇指', Index: '食指', Middle: '中指', Ring: '无名指', Pinky: '小指'});
  function jointLabel(name) {
    if (LABELS[name]) return LABELS[name];
    const m = /^(Left|Right)(?:Hand(Thumb|Index|Middle|Ring|Pinky)(\d|End)|(Shoulder|Arm|ForeArm|Hand|Leg|Shin|Foot|ToeBase|ToeEnd|Eye))$/.exec(String(name));
    if (!m) return String(name);
    const side = m[1] === 'Left' ? '左' : '右';
    return m[2] ? `${side}${LABELS[m[2]]}${m[3] === 'End' ? '末端' : ' ' + m[3]}` : side + LABELS[m[4]];
  }
  const mirrorName = n => n.startsWith('Left') ? 'Right' + n.slice(4) : n.startsWith('Right') ? 'Left' + n.slice(5) : n;

  // ---- quaternions as [x, y, z, w] (SOMA rotations are relative to the T-pose, in T-pose world axes)
  const AXES = {x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1]};
  const IDENTITY = Object.freeze([0, 0, 0, 1]);
  function mul(a, b) {
    return [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
      a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
  }
  function axisAngle(axis, degrees) {
    const half = degrees * Math.PI / 360, s = Math.sin(half);
    return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(half)];
  }
  // World-axis steps applied in order: [['z', -72], ['x', 20]] = rotate about z, then about x.
  function steps(list) { return list.reduce((q, [axis, deg]) => mul(axisAngle(AXES[axis], deg), q), [...IDENTITY]); }
  function normalizeQuat(value) {
    if (!Array.isArray(value) || value.length !== 4 || !value.every(Number.isFinite)) return null;
    const n = Math.hypot(...value);
    if (!(n > 1e-6)) return null;
    const q = value.map(v => v / n);
    return q[3] < 0 ? q.map(v => -v) : q;
  }
  const isIdentity = q => Math.abs(Math.abs(q[3]) - 1) < 1e-6;
  const round = (v, places = 5) => Math.round(v * 10 ** places) / 10 ** places;
  function toAxisAngle(q) {
    const [x, y, z, w] = normalizeQuat(q) || IDENTITY;
    const s = Math.hypot(x, y, z);
    if (s < 1e-9) return [0, 0, 0];
    const angle = 2 * Math.atan2(s, w);
    return [x / s * angle, y / s * angle, z / s * angle];
  }
  function mirrorQuat(q) { return [q[0], -q[1], -q[2], q[3]]; }
  function mirrorRotations(rotations) {
    const out = {};
    for (const [name, q] of Object.entries(rotations || {})) out[mirrorName(name)] = mirrorQuat(q);
    return out;
  }

  // ---- pose library (specs in world-axis steps, relative to the T-pose; X = character's left, +Z = facing)
  // `facing` presets also turn the character relative to the active camera: 0 front, 90 right side, 180 back.
  const STAND = {LeftArm: [['z', -72]], RightArm: [['z', 72]], LeftForeArm: [['y', -12]], RightForeArm: [['y', 12]]};
  const PRESET_GROUPS = Object.freeze(['站立', '动作', '坐跪', '朝向']);
  const PRESET_SPECS = Object.freeze([
    ['stand', '自然站立', '站立', STAND],
    ['tpose', 'T 姿势', '站立', {}],
    ['apose', 'A 姿势', '站立', {LeftArm: [['z', -45]], RightArm: [['z', 45]]}],
    ['hips', '叉腰', '站立', {LeftArm: [['x', 60], ['z', -52], ['x', 15]], RightArm: [['x', 60], ['z', 52], ['x', 15]],
      LeftForeArm: [['y', -90]], RightForeArm: [['y', 90]]}],
    ['crossarms', '双手抱胸', '站立', {LeftArm: [['x', 60], ['z', -77], ['x', -30], ['y', -20]], RightArm: [['x', 45], ['z', 72], ['x', -20], ['y', 40]],
      LeftForeArm: [['y', -101]], RightForeArm: [['y', 94]]}],
    ['pockets', '双手插兜', '站立', {LeftArm: [['z', -78], ['y', 8]], RightArm: [['z', 78], ['y', -8]], LeftForeArm: [['y', -25]], RightForeArm: [['y', 25]]}],
    ['behind', '双手背后', '站立', {LeftArm: [['x', 105], ['z', -74], ['x', 16]], RightArm: [['x', 105], ['z', 74], ['x', 16]],
      LeftForeArm: [['y', -70]], RightForeArm: [['y', 70]]}],
    ['relaxed', '稍息', '站立', {...STAND, Hips: [['z', -4]], Spine1: [['z', 4]], LeftLeg: [['z', 6], ['x', -6]], LeftShin: [['x', 12]],
      RightLeg: [['z', 3]]}],
    ['wave', '挥手', '动作', {...STAND, RightArm: [['z', -12]], RightForeArm: [['z', -100]], Head: [['y', -10]]}],
    ['point', '指向前方', '动作', {...STAND, RightArm: [['y', 88], ['x', -12]], RightForeArm: [], Chest: [['y', 10]]}],
    ['walk', '行走', '动作', {LeftArm: [['z', -76], ['x', 22]], RightArm: [['z', 76], ['x', -22]], LeftForeArm: [['y', -18]], RightForeArm: [['y', 28]],
      LeftLeg: [['x', -24]], LeftShin: [['x', 8]], RightLeg: [['x', 16]], RightShin: [['x', 26]], RightFoot: [['x', -8]]}],
    ['run', '跑步', '动作', {Spine1: [['x', 10]], LeftArm: [['z', -75], ['x', 40]], RightArm: [['z', 75], ['x', -45]],
      LeftForeArm: [['y', -90]], RightForeArm: [['y', 100]], LeftLeg: [['x', -55]], LeftShin: [['x', 70]], RightLeg: [['x', 20]], RightShin: [['x', 95]]}],
    ['cheer', '跳跃欢呼', '动作', {LeftArm: [['z', 60]], RightArm: [['z', -60]], LeftForeArm: [['y', -10]], RightForeArm: [['y', 10]],
      LeftLeg: [['x', -20]], LeftShin: [['x', 60]], RightLeg: [['x', -10]], RightShin: [['x', 50]]}],
    ['armsup', '双手上举', '动作', {LeftArm: [['z', 85]], RightArm: [['z', -85]], Head: [['x', -8]]}],
    ['phone', '打电话', '动作', {...STAND, RightArm: [['x', 30], ['z', 100], ['x', -75]], RightForeArm: [['y', 150]], Head: [['z', -6]]}],
    ['bow', '鞠躬', '动作', {...STAND, Spine1: [['x', 30]], Spine2: [['x', 15]], Head: [['x', 10]]}],
    ['look', '回头', '动作', {...STAND, Neck1: [['y', 34]], Head: [['y', 26], ['x', -6]], Chest: [['y', 14]]}],
    ['sit', '坐姿', '坐跪', {...STAND, LeftLeg: [['x', -88]], RightLeg: [['x', -84], ['y', -4]], LeftShin: [['x', 88]], RightShin: [['x', 82]],
      Spine1: [['x', 6]], LeftForeArm: [['y', -62]], RightForeArm: [['y', 66]]}],
    ['squat', '深蹲', '坐跪', {Spine1: [['x', 30]], LeftLeg: [['x', -100]], RightLeg: [['x', -100]], LeftShin: [['x', 120]], RightShin: [['x', 120]],
      LeftArm: [['y', -84], ['x', 8]], RightArm: [['y', 84], ['x', 8]]}],
    ['kneel', '单膝跪地', '坐跪', {...STAND, LeftLeg: [['x', -90]], LeftShin: [['x', 90]], RightLeg: [['x', 5]], RightShin: [['x', 80]]}],
    ['kneelboth', '双膝跪地', '坐跪', {...STAND, LeftShin: [['x', 85]], RightShin: [['x', 85]]}],
    ['floorsit', '坐地伸腿', '坐跪', {LeftLeg: [['x', -90]], RightLeg: [['x', -90]], Spine1: [['x', -10]],
      LeftArm: [['z', -70], ['y', 35]], RightArm: [['z', 70], ['y', -35]]}],
    ['back', '背面站立', '朝向', STAND, 180],
    ['leftside', '左侧面站立', '朝向', STAND, -90],
    ['rightside', '右侧面站立', '朝向', STAND, 90],
    ['leftthreequarter', '左前侧站立', '朝向', STAND, -45],
    ['rightthreequarter', '右前侧站立', '朝向', STAND, 45],
  ]);
  function specRotations(spec) {
    const out = {};
    for (const [name, list] of Object.entries(spec)) {
      const q = steps(list).map(v => round(v, 6));
      if (!isIdentity(q)) out[name] = q;
    }
    return out;
  }
  const PRESETS = Object.freeze(PRESET_SPECS.map(([id, label, group, spec, facing = null]) =>
    Object.freeze({id, label, group, facing, rotations: Object.freeze(specRotations(spec))})));
  // Hand shapes: fingers curl about z toward the palm, the thumb about y across it (checked on renders).
  // A shape replaces every finger of its hand; `captured` keeps the finger rotations the character has
  // (recognised, keyed or rotated by hand).
  const HAND_SHAPES = Object.freeze({relaxed: '自然', grip: '半握', fist: '握拳', open: '张开'});
  const CAPTURED_HAND = 'captured';
  const HANDS_VERSION = 2;
  const CURLS = Object.freeze({relaxed: [[6, 10, 10], [14, 22, 14]], grip: [[14, 22, 20], [40, 55, 35]], fist: [[20, 30, 30], [70, 90, 60]]});
  function handRotations(side, shape) {
    const out = {};
    if (!CURLS[shape]) return out;
    const sign = side === 'Left' ? 1 : -1;
    for (const finger of FINGERS) {
      const segments = finger === 'Thumb' ? [1, 2, 3] : [2, 3, 4];
      segments.forEach((segment, index) => {
        const amount = CURLS[shape][finger === 'Thumb' ? 0 : 1][index];
        out[`${side}Hand${finger}${segment}`] = steps(finger === 'Thumb' ? [['y', sign * amount]] : [['z', sign * -amount]]).map(v => round(v, 6));
      });
    }
    return out;
  }
  const isFinger = (name, side) => name.startsWith(`${side}Hand`) && name !== `${side}Hand`;
  const hasFingers = (rotations, side) => Object.keys(rotations || {}).some(name => isFinger(name, side));
  // The rotations a figure is posed with: per hand, a shape replaces all finger rotations, `captured` keeps them.
  function effectiveRotations(character, rotations = character.rotations) {
    const out = {...rotations};
    for (const [side, key] of [['Left', 'left'], ['Right', 'right']]) {
      const shape = character.hands?.[key];
      if (shape === CAPTURED_HAND) continue;
      Object.keys(out).forEach(name => { if (isFinger(name, side)) delete out[name]; });
      Object.assign(out, handRotations(side, shape));
    }
    return out;
  }

  // ---- OpenPose COCO-18 (+21-point hands). Derived points are computed by the renderer.
  const OPENPOSE = Object.freeze({
    body: Object.freeze(['nose', 'neck', 'RightArm', 'RightForeArm', 'RightHand', 'LeftArm', 'LeftForeArm', 'LeftHand',
      'RightLeg', 'RightShin', 'RightFoot', 'LeftLeg', 'LeftShin', 'LeftFoot', 'RightEye', 'LeftEye', 'rightEar', 'leftEar']),
    derived: Object.freeze(['nose', 'neck', 'rightEar', 'leftEar']),
    limbs: Object.freeze([[1, 2], [1, 5], [2, 3], [3, 4], [5, 6], [6, 7], [1, 8], [8, 9], [9, 10], [1, 11], [11, 12], [12, 13], [1, 0], [0, 14], [14, 16], [0, 15], [15, 17]]),
    colors: Object.freeze([[255, 0, 0], [255, 85, 0], [255, 170, 0], [255, 255, 0], [170, 255, 0], [85, 255, 0], [0, 255, 0], [0, 255, 85], [0, 255, 170],
      [0, 255, 255], [0, 170, 255], [0, 85, 255], [0, 0, 255], [85, 0, 255], [170, 0, 255], [255, 0, 255], [255, 0, 170], [255, 0, 85]]),
    // Wrist + 4 points per finger, in OpenPose hand order.
    hand: side => [`${side}Hand`, ...FINGERS.flatMap(f => (f === 'Thumb' ? [1, 2, 3, 'End'] : [2, 3, 4, 'End']).map(s => `${side}Hand${f}${s}`))],
  });

  // ---- state
  const finite = (value, fallback, lo, hi) => {
    const n = Number(value);
    return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fallback;
  };
  const vec = (value, fallback, limit) => Array.isArray(value) && value.length === fallback.length && value.every(v => Number.isFinite(Number(v)))
    ? value.map(v => finite(v, 0, -limit, limit)) : [...fallback];
  const uid = prefix => prefix + (globalThis.crypto?.randomUUID?.().replaceAll('-', '').slice(0, 10) || Math.random().toString(36).slice(2, 12));
  function presetRotations(id) { return {...(PRESETS.find(p => p.id === id) || PRESETS[0]).rotations}; }
  function createCharacter(index, overrides = {}) {
    return normalizeCharacter({id: uid('char_'), name: `角色 ${String.fromCharCode(65 + index)}`, color: SWATCHES[index % SWATCHES.length],
      visible: true, locked: false, grounded: true, height: 175, position: [index ? (index % 2 ? 0.6 : -0.6) * Math.ceil(index / 2) : 0, 0], yaw: 0,
      rotations: presetRotations('stand'), ...overrides}, index);
  }
  function createCamera(index, overrides = {}) {
    return normalizeCamera({id: uid('cam_'), name: `机位 ${index + 1}`, position: [0, 1.15, 4.4], target: [0, 0.9, 0], focalMm: 35, aspect: '3:4', ...overrides}, index);
  }
  function normalizeRotations(value) {
    const out = {};
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [name, raw] of Object.entries(value)) {
        const q = JOINT_SET.has(name) && name !== 'Root' ? normalizeQuat(raw) : null;
        if (q && !isIdentity(q)) out[name] = q.map(v => round(v, 6));
      }
    }
    return out;
  }
  function normalizeCharacter(value, index) {
    const c = value && typeof value === 'object' ? value : {};
    return {id: /^[a-z0-9_]{3,40}$/i.test(c.id || '') ? c.id : uid('char_'), name: String(c.name || `角色 ${String.fromCharCode(65 + index)}`).slice(0, 16),
      color: /^#[0-9a-f]{6}$/i.test(c.color || '') ? c.color.toLowerCase() : SWATCHES[index % SWATCHES.length],
      visible: c.visible !== false, locked: c.locked === true, grounded: c.grounded !== false, body: normalizeBody(c.body),
      // The recognised shape stays available after switching to a preset, so it can be picked again.
      capturedBody: captureBodyId(c.capturedBody) ? c.capturedBody : captureBodyId(c.body) ? c.body : '',
      // Video characters follow a recognised person (`track`); position, yaw and elevation then offset the
      // whole trajectory and `keys` hold manual fixes (see desktop-pose-sequence.js).
      track: normalizeTrack(c.track), keys: c.track ? normalizeKeys(c.keys) : [],
      height: Math.round(finite(c.height, 175, 140, 200)), position: vec(c.position, [0, 0], 10),
      elevation: round(finite(c.elevation, 0, 0, MAX_ELEVATION), 3), yaw: finite(c.yaw, 0, -180, 180),
      hands: normalizeHands(c), handsVersion: HANDS_VERSION,
      rotations: normalizeRotations(c.rotations)};
  }
  // Characters saved before HANDS_VERSION showed explicit finger rotations whatever their shape said, and a
  // video character's fingers always came from its sequence: those hands read as `captured`, so older
  // scenes keep the hands they showed.
  function normalizeHands(c) {
    const out = {};
    for (const [side, key] of [['Left', 'left'], ['Right', 'right']]) {
      const value = c.hands?.[key];
      const legacy = c.handsVersion !== HANDS_VERSION && (hasFingers(c.rotations, side) || Boolean(c.track));
      out[key] = legacy ? CAPTURED_HAND : value === CAPTURED_HAND || HAND_SHAPES[value] ? value : 'relaxed';
    }
    return out;
  }
  function normalizeCamera(value, index) {
    const c = value && typeof value === 'object' ? value : {};
    return {id: /^[a-z0-9_]{3,40}$/i.test(c.id || '') ? c.id : uid('cam_'), name: String(c.name || `机位 ${index + 1}`).slice(0, 16),
      position: vec(c.position, [0, 1.15, 4.4], 50), target: vec(c.target, [0, 0.9, 0], 50),
      focalMm: Math.round(finite(c.focalMm, 35, 14, 200)), aspect: ASPECTS[c.aspect] ? c.aspect : '3:4'};
  }
  function defaultScene() {
    const camera = createCamera(0);
    return {characters: [createCharacter(0)], cameras: [camera], activeCameraId: camera.id};
  }
  const MAX_KEYS = 600;
  function normalizeTrack(value) {
    if (!value || typeof value !== 'object') return null;
    const person = Math.round(Number(value.person)), start = Math.round(Number(value.start)), count = Math.round(Number(value.count));
    return person >= 0 && person < MAX_CHARACTERS && start >= 0 && count >= 1 ? {person, start, count} : null;
  }
  function normalizeKeys(value) {
    const byFrame = new Map();
    for (const k of Array.isArray(value) ? value : []) {
      const frame = Math.round(Number(k?.frame));
      const rotations = normalizeRotations(k?.rotations);
      if (Number.isFinite(frame) && frame >= 0 && Object.keys(rotations).length) byFrame.set(frame, {frame, rotations});
    }
    return [...byFrame.values()].sort((a, b) => a.frame - b.frame).slice(0, MAX_KEYS);
  }
  // A recognised video: the backend job holding the sequence, its timing, the current frame and the export range.
  function normalizeSequence(value) {
    if (!value || typeof value !== 'object' || !/^[a-f0-9]{32}$/.test(String(value.jobId || ''))) return null;
    const frameCount = Math.round(finite(value.frameCount, 0, 0, 36000));
    if (frameCount < 2) return null;
    const clamp = v => Math.round(finite(v, 0, 0, frameCount - 1));
    const inFrame = clamp(value.inFrame ?? 0), outFrame = Math.max(inFrame, clamp(value.outFrame ?? frameCount - 1));
    return {jobId: value.jobId, fps: round(finite(value.fps, 30, 1, 240), 4), frameCount, frame: clamp(value.frame), inFrame, outFrame};
  }
  function normalizeScene(value) {
    const s = value && typeof value === 'object' ? value : {};
    const sequence = normalizeSequence(s.sequence);
    const characters = (Array.isArray(s.characters) ? s.characters : []).slice(0, MAX_CHARACTERS).map(normalizeCharacter);
    if (!sequence) characters.forEach(c => { c.track = null; c.keys = []; });
    const cameras = (Array.isArray(s.cameras) ? s.cameras : []).slice(0, MAX_CAMERAS).map(normalizeCamera);
    if (!cameras.length) cameras.push(createCamera(0));
    const ids = new Set();
    for (const item of [...characters, ...cameras]) { if (ids.has(item.id)) item.id = uid(item.id.slice(0, 5)); ids.add(item.id); }
    return {characters, cameras, activeCameraId: cameras.some(c => c.id === s.activeCameraId) ? s.activeCameraId : cameras[0].id,
      ...(sequence ? {sequence} : {})};
  }
  function normalizeSettings(value) {
    const s = value && typeof value === 'object' ? value : {};
    return {openposeHands: s.openposeHands !== false, openposeWidth: s.openposeWidth === 'bold' ? 'bold' : 'standard',
      background: s.background === 'transparent' ? 'transparent' : 'black'};
  }
  // A pose video in the image archive (served by the authenticated /video/ route).
  const VIDEO_ARTIFACT = /^\/video\/pose_[a-z]+_\d{6}_[a-f0-9]{8}\.mp4$/;
  function normalizeVideo(value) {
    const v = value && typeof value === 'object' ? value : null;
    if (!v || !VIDEO_ARTIFACT.test(String(v.url || ''))) return null;
    return {url: v.url, frames: Math.round(finite(v.frames, 0, 0, 36000)), fps: round(finite(v.fps, 30, 1, 240), 4),
      width: Math.round(finite(v.width, 0, 0, 4096)), height: Math.round(finite(v.height, 0, 0, 4096)),
      exportedAt: finite(v.exportedAt, 0, 0, 9e15), sceneKey: String(v.sceneKey || '').slice(0, 16), videoNodeId: String(v.videoNodeId || '').slice(0, 80)};
  }
  function normalizeOutput(value) {
    const o = value && typeof value === 'object' ? value : {};
    const exported = ARTIFACT.test(String(o.artifactUrl || ''));
    return {pass: PASSES[o.pass] ? o.pass : 'openpose', size: SIZES[o.size] ? o.size : '1024',
      // Recognised videos export a pose video (plus the first frame as the node's image); `image` exports one frame.
      kind: o.kind === 'image' ? 'image' : 'video',
      artifactUrl: exported ? o.artifactUrl : '', width: exported ? Math.round(finite(o.width, 0, 0, 4096)) : 0,
      height: exported ? Math.round(finite(o.height, 0, 0, 4096)) : 0, exportedAt: exported ? finite(o.exportedAt, 0, 0, 9e15) : 0,
      cameraName: exported ? String(o.cameraName || '').slice(0, 16) : '', sceneKey: exported ? String(o.sceneKey || '').slice(0, 16) : '',
      video: normalizeVideo(o.video)};
  }
  // Whether an export writes a video: a recognised sequence with the video output kind.
  const exportsVideo = node => Boolean(node?.scene?.sequence) && node.output.kind === 'video';
  const isLegacy = node => node?.type === TYPE && node.poseVersion !== VERSION;
  function normalize(node) {
    if (!node || node.type !== TYPE) return node;
    node.poseVersion = VERSION;
    node.width = WIDTH;
    node.height = HEIGHT;
    node.title = String(node.title || '姿态参考').slice(0, 24);
    node.scene = normalizeScene(node.scene || defaultScene());
    node.output = normalizeOutput(node.output);
    node.settings = normalizeSettings(node.settings);
    // Recognition options: not part of the scene, so changing them never marks an export out of date.
    node.capture = {evidence: node.capture?.evidence !== false};
    node.status = STATUSES.includes(node.status) && node.status !== 'exporting' ? node.status : (node.output.artifactUrl ? 'exported' : 'idle');
    node.error = node.status === 'failed' ? String(node.error || '').slice(0, 300) : '';
    return node;
  }
  function createState() { return normalize({type: TYPE, poseVersion: VERSION, scene: defaultScene()}); }
  // Old Mixamo/Director nodes are not migrated: drop them with their edges and report how many.
  function purgeLegacy(canvas) {
    const nodes = canvas?.nodes || {};
    const ids = Object.keys(nodes).filter(id => isLegacy(nodes[id]));
    ids.forEach(id => delete nodes[id]);
    if (ids.length && Array.isArray(canvas.edges)) canvas.edges = canvas.edges.filter(e => !ids.includes(e.from) && !ids.includes(e.to));
    if (ids.length && Array.isArray(canvas.selectedNodeIds)) canvas.selectedNodeIds = canvas.selectedNodeIds.filter(id => !ids.includes(id));
    if (ids.includes(canvas?.selectedNodeId)) canvas.selectedNodeId = '';
    return ids.length;
  }

  const activeCamera = scene => scene.cameras.find(c => c.id === scene.activeCameraId) || scene.cameras[0];
  function outputSize(sizeKey, aspect) {
    const long = SIZES[sizeKey] || 1024, a = ASPECTS[aspect] || 1;
    const short = Math.max(64, Math.round(long / (a >= 1 ? a : 1 / a) / 8) * 8);
    return a >= 1 ? [long, short] : [short, long];
  }
  function stable(value) {
    if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
    return JSON.stringify(value);
  }
  // cyrb53: a short, stable fingerprint so node state does not carry a second copy of the scene.
  function fingerprint(text) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < text.length; i++) {
      const ch = text.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761); h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
  }
  // What an export depends on; the node is "dirty" when this differs from the last export.
  // A video export covers the whole range, so scrubbing (the current frame) does not make it stale.
  function sceneKey(node) {
    const video = exportsVideo(node);
    const base = video ? {...node.scene, sequence: {...node.scene.sequence, frame: 0}} : node.scene;
    // handsVersion is bookkeeping, not content: adding it must not mark every exported node changed.
    const scene = {...base, characters: base.characters.map(({handsVersion, ...c}) => c)};
    const key = {scene, pass: node.output.pass, size: node.output.size, settings: node.settings};
    if (node.scene.sequence) key.kind = node.output.kind;
    return fingerprint(stable(key));
  }
  const dirty = node => exportsVideo(node) ? !node.output.video || node.output.video.sceneKey !== sceneKey(node)
    : !node.output.artifactUrl || node.output.sceneKey !== sceneKey(node);
  const artifactUrl = node => node?.type === TYPE && node.poseVersion === VERSION && ARTIFACT.test(String(node.output?.artifactUrl || '')) ? node.output.artifactUrl : '';

  // Backend sidecar contract (snake_case, docs/POSE_REFERENCE_REBUILD_PLAN.md §4.1). `world` comes
  // from the renderer: per character the Hips world position and the yaw-folded Hips rotation.
  function base64Floats(values) {
    const bytes = new Uint8Array(new Float32Array(values).buffer);
    let text = '';
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return 'base64:' + btoa(text);
  }
  function snapshot(node, world = {}) {
    const scene = node.scene;
    return {
      version: 1, skeleton: 'soma77', fps: 30,
      people: scene.characters.filter(c => c.visible).map(c => {
        const w = world[c.id] || {};
        const rotations = SOMA_JOINTS.slice(1).flatMap(name => toAxisAngle(name === 'Hips' && w.hips ? w.hips : (c.rotations[name] || IDENTITY)));
        const capture = captureBodyId(c.body);
        const identity = capture ? {model: 'mhr', body_id: capture} : c.body === 'neutral' ? {model: 'soma'} : {model: 'anny', preset: c.body};
        return {id: c.id, label: c.name, color: c.color, identity: {...identity, coeffs: [], scale_params: [round(c.height / 175, 4)]},
          frames: {count: 1, transl: [vec(w.transl, [c.position[0], 0.94, c.position[1]], 50)], rotations: base64Floats(rotations)},
          confidence: null, overrides: []};
      }),
      cameras: scene.cameras.map(cam => {
        const [width, height] = outputSize(node.output.size, cam.aspect);
        return {id: cam.id, label: cam.name, position: cam.position, target: cam.target, focal_mm: cam.focalMm, aspect: cam.aspect, width, height};
      }),
      active_camera: scene.activeCameraId,
      source: {kind: 'manual', engine: null, engine_version: null, input_asset_id: null},
      updated_at: Math.round(Date.now() / 1000),
    };
  }

  // Recognition result (same contract, from /api/pose_capture) -> editor characters and the photo camera.
  function decodeFloats(text) {
    const match = /^base64:([A-Za-z0-9+/=]+)$/.exec(String(text || ''));
    if (!match) throw new Error('识别结果格式无效');
    const raw = atob(match[1]);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    if (bytes.length % 4) throw new Error('识别结果格式无效');
    return new Float32Array(bytes.buffer);
  }
  function fromAxisAngle([x, y, z]) {
    const angle = Math.hypot(x, y, z);
    return angle < 1e-9 ? [...IDENTITY] : axisAngle([x / angle, y / angle, z / angle], angle * 180 / Math.PI);
  }
  const PHOTO_CAMERA = 'cam_photo';
  function applyCapture(node, result) {
    if (result?.skeleton !== 'soma77' || !Array.isArray(result.people) || !result.people.length) throw new Error('照片中没有识别到人物');
    const people = result.people.slice(0, MAX_CHARACTERS);
    const characters = people.map((p, index) => {
      const values = decodeFloats(p.frames?.rotations);
      if (values.length !== 77 * 3) throw new Error('识别结果关节数不一致');
      const rotations = {};
      SOMA_JOINTS.slice(1).forEach((name, j) => { rotations[name] = fromAxisAngle([values[j * 3], values[j * 3 + 1], values[j * 3 + 2]]); });
      const [x, , z] = p.frames.transl?.[0] || [0, 0, 0];
      return normalizeCharacter({id: uid('char_'), name: String(p.label || `角色 ${String.fromCharCode(65 + index)}`), color: p.color,
        height: p.height_cm, position: [x, z], elevation: p.floor_offset, yaw: 0, grounded: true, hands: {left: CAPTURED_HAND, right: CAPTURED_HAND}, rotations,
        body: p.body_id ? `capture:${p.body_id}` : 'neutral', capturedBody: p.body_id ? `capture:${p.body_id}` : ''}, index);
    });
    const shot = result.cameras?.[0];
    const cameras = node.scene.cameras.filter(c => c.id !== PHOTO_CAMERA);
    if (shot) {
      cameras.unshift(normalizeCamera({id: PHOTO_CAMERA, name: '照片机位', position: shot.position, target: shot.target,
        focalMm: shot.focal_mm, aspect: shot.aspect}, 0));
    }
    node.scene = normalizeScene({characters, cameras: cameras.slice(0, MAX_CAMERAS),
      activeCameraId: shot ? PHOTO_CAMERA : node.scene.activeCameraId});
    return node;
  }
  // A video recognition: characters follow the recognised people frame by frame; the static pose they keep
  // is the first frame (used if the sequence cannot be loaded).
  function applyCaptureSequence(node, result, jobId) {
    if (result?.skeleton !== 'soma77' || !Array.isArray(result.people) || !result.people.length) throw new Error('视频中没有识别到人物');
    const frameCount = Math.round(Number(result.frame_count) || 0);
    const characters = result.people.slice(0, MAX_CHARACTERS).map((p, index) => {
      const values = decodeFloats(p.frames?.rotations), count = Math.round(Number(p.frames?.count) || 0);
      if (!count || values.length !== count * 77 * 3) throw new Error('识别结果关节数不一致');
      const rotations = {};
      SOMA_JOINTS.slice(1).forEach((name, j) => { rotations[name] = fromAxisAngle([values[j * 3], values[j * 3 + 1], values[j * 3 + 2]]); });
      return normalizeCharacter({id: uid('char_'), name: String(p.label || `角色 ${String.fromCharCode(65 + index)}`), color: p.color,
        height: p.height_cm, position: [0, 0], elevation: 0, yaw: 0, grounded: true, hands: {left: CAPTURED_HAND, right: CAPTURED_HAND}, rotations,
        body: p.body_id ? `capture:${p.body_id}` : 'neutral', capturedBody: p.body_id ? `capture:${p.body_id}` : '',
        track: {person: index, start: p.frames.start, count}}, index);
    });
    const shot = result.cameras?.[0];
    const cameras = node.scene.cameras.filter(c => c.id !== PHOTO_CAMERA);
    if (shot) {
      cameras.unshift(normalizeCamera({id: PHOTO_CAMERA, name: '视频机位', position: shot.position, target: shot.target,
        focalMm: shot.focal_mm, aspect: shot.aspect}, 0));
    }
    node.scene = normalizeScene({characters, cameras: cameras.slice(0, MAX_CAMERAS), activeCameraId: shot ? PHOTO_CAMERA : node.scene.activeCameraId,
      sequence: {jobId, fps: result.fps, frameCount, frame: 0, inFrame: 0, outFrame: frameCount - 1}});
    return node;
  }
  // ---- facing (yaw about the vertical axis through the character's root, i.e. its standing centre)
  const wrapDegrees = deg => { const d = ((deg + 180) % 360 + 360) % 360 - 180; return Math.round(d * 10) / 10; };
  function rotateVector(q, v) {
    const [x, y, z, w] = normalizeQuat(q) || IDENTITY;
    const r = mul(mul([x, y, z, w], [v[0], v[1], v[2], 0]), [-x, -y, -z, w]);
    return [r[0], r[1], r[2]];
  }
  // Heading (degrees, 0 = +Z) a Hips rotation adds; recognised characters carry their facing there.
  function hipsHeading(character) {
    const f = rotateVector(character.rotations?.Hips || IDENTITY, [0, 0, 1]);
    return Math.hypot(f[0], f[2]) < 1e-6 ? 0 : Math.atan2(f[0], f[2]) * 180 / Math.PI;
  }
  // Yaw that turns a character to `offset` degrees from facing the camera: 0 front, 90 its right side, 180 back, -90 left side.
  function facingYaw(character, cameraPosition, offset = 0) {
    const toCamera = Math.atan2(cameraPosition[0] - character.position[0], cameraPosition[2] - character.position[1]) * 180 / Math.PI;
    return wrapDegrees(toCamera + offset - hipsHeading(character));
  }
  // Replace a character's pose with a library preset. The current heading is kept (folded into yaw), and
  // facing presets turn the character relative to the camera.
  function applyPreset(character, preset, cameraPosition) {
    const heading = character.yaw + hipsHeading(character);
    character.rotations = {...preset.rotations};
    // The recognised fingers went with the old rotations; a hand left without any relaxes.
    for (const [side, key] of [['Left', 'left'], ['Right', 'right']]) {
      if (character.hands[key] === CAPTURED_HAND && !hasFingers(character.rotations, side)) character.hands[key] = 'relaxed';
    }
    character.yaw = preset.facing == null ? wrapDegrees(heading) : facingYaw(character, cameraPosition, preset.facing);
    return character;
  }

  // A scene worth asking about before recognition replaces it: anything beyond the default figure.
  function hasCustomPose(node) {
    const defaults = presetRotations('stand');
    return Boolean(node.scene.sequence) || node.scene.characters.length > 1 || node.scene.characters.some(c => stable(c.rotations) !== stable(defaults));
  }

  window.DesktopPoseModel = Object.freeze({
    TYPE, VERSION, WIDTH, HEIGHT, MAX_CHARACTERS, MAX_ELEVATION, MAX_CAMERAS, BODIES, isPresetBody, captureBodyId, bodyLabel, ICON, PASSES, SIZES, ASPECTS, SWATCHES, SOMA_JOINTS, MAIN_JOINTS, IK_CHAINS,
    PRESETS, PRESET_GROUPS, HAND_SHAPES, CAPTURED_HAND, OPENPOSE, IDENTITY, wrapDegrees, hipsHeading, facingYaw, applyPreset, applyCaptureSequence, exportsVideo,
    menu: {type: TYPE, title: '姿态参考', subtitle: 'SOMA 人偶 · 多角色机位', icon: MENU_ICON},
    jointLabel, mirrorName, mul, axisAngle, steps, normalizeQuat, isIdentity, toAxisAngle, mirrorQuat, mirrorRotations, handRotations, effectiveRotations, hasFingers, presetRotations,
    createCharacter, createCamera, defaultScene, normalizeScene, normalize, createState, isLegacy, purgeLegacy,
    activeCamera, outputSize, sceneKey, dirty, artifactUrl, snapshot, applyCapture, hasCustomPose, PHOTO_CAMERA,
  });
})();
