import * as THREE from '../static/pose/three.module.js';
import { OrbitControls } from '../static/pose/OrbitControls.js';
import { TransformControls } from '../static/pose/TransformControls.js';
import { GLTFLoader } from '../static/pose/GLTFLoader.js';
import { clone as cloneSkeleton } from '../static/pose/SkeletonUtils.js';

const DIRECTOR_MANNEQUIN_ASSETS = {
  mixamo_xbot: 'static/pose/mannequin/xbot.glb',
  mixamo_ybot: 'static/pose/mannequin/ybot.glb'
};
const DIRECTOR_MODEL_OPTIONS = [
  { key: 'mixamo_xbot', label: 'X Bot / 女性代理' },
  { key: 'mixamo_ybot', label: 'Y Bot / 男性代理' },
  { key: 'procedural_mannequin', label: '程序化兜底' }
];
const DIRECTOR_GLB_PART_ALIASES = {
  spine: ['spine', 'mixamorigspine', 'mixamorigspine1'],
  neckSegment: ['necksegment', 'neck_segment'],
  leftUpperArm: ['leftupperarm', 'mixamorigleftarm'],
  leftLowerArm: ['leftlowerarm', 'mixamorigleftforearm'],
  rightUpperArm: ['rightupperarm', 'mixamorigrightarm'],
  rightLowerArm: ['rightlowerarm', 'mixamorigrightforearm'],
  leftUpperLeg: ['leftupperleg', 'mixamorigleftupleg'],
  leftLowerLeg: ['leftlowerleg', 'mixamorigleftleg'],
  rightUpperLeg: ['rightupperleg', 'mixamorigrightupleg'],
  rightLowerLeg: ['rightlowerleg', 'mixamorigrightleg'],
  pelvis: ['pelvis', 'hips', 'mixamorighips'],
  chest: ['chest', 'mixamorigspine2'],
  neckJoint: ['neckjoint', 'neck_joint', 'mixamorigneck'],
  head: ['head', 'mixamorighead'],
  leftShoulder: ['leftshoulder', 'mixamorigleftshoulder'],
  leftElbow: ['leftelbow'],
  leftHand: ['lefthand', 'mixamoriglefthand'],
  rightShoulder: ['rightshoulder', 'mixamorigrightshoulder'],
  rightElbow: ['rightelbow'],
  rightHand: ['righthand', 'mixamorigrighthand'],
  leftHip: ['lefthip', 'mixamorigleftupleg'],
  leftKnee: ['leftknee'],
  leftAnkle: ['leftankle', 'mixamorigleftfoot'],
  leftToeBase: ['lefttoebase', 'mixamoriglefttoebase'],
  rightHip: ['righthip', 'mixamorigrightupleg'],
  rightKnee: ['rightknee'],
  rightAnkle: ['rightankle', 'mixamorigrightfoot'],
  rightToeBase: ['righttoebase', 'mixamorigrighttoebase']
};
const DIRECTOR_LIMB_DIRECTION_PAIRS = [
  { key: 'leftUpperArm', child: 'leftLowerArm', chain: 'leftArm', from: 'shoulder', to: 'elbow' },
  { key: 'leftLowerArm', child: 'leftHand', chain: 'leftArm', from: 'elbow', to: 'hand' },
  { key: 'rightUpperArm', child: 'rightLowerArm', chain: 'rightArm', from: 'shoulder', to: 'elbow' },
  { key: 'rightLowerArm', child: 'rightHand', chain: 'rightArm', from: 'elbow', to: 'hand' },
  { key: 'leftUpperLeg', child: 'leftLowerLeg', chain: 'leftLeg', from: 'hip', to: 'knee' },
  { key: 'leftLowerLeg', child: 'leftAnkle', chain: 'leftLeg', from: 'knee', to: 'ankle' },
  { key: 'rightUpperLeg', child: 'rightLowerLeg', chain: 'rightLeg', from: 'hip', to: 'knee' },
  { key: 'rightLowerLeg', child: 'rightAnkle', chain: 'rightLeg', from: 'knee', to: 'ankle' }
];
const DIRECTOR_JOINT_DEFS = [
  { key: 'pelvis', label: '骨盆', part: 'pelvis', mode: 'torso' },
  { key: 'spine', label: '腰', part: 'spine', mode: 'torso' },
  { key: 'chest', label: '胸', part: 'chest', mode: 'torso' },
  { key: 'neck', label: '颈', part: 'neckJoint', mode: 'override' },
  { key: 'head', label: '头', part: 'head', mode: 'head' },
  { key: 'leftClavicle', label: '左锁骨/肩胛', part: 'leftShoulder', mode: 'override' },
  { key: 'rightClavicle', label: '右锁骨/肩胛', part: 'rightShoulder', mode: 'override' },
  { key: 'leftShoulder', label: '左肩', part: 'leftUpperArm', mode: 'shoulder', side: 'left' },
  { key: 'rightShoulder', label: '右肩', part: 'rightUpperArm', mode: 'shoulder', side: 'right' },
  { key: 'leftElbow', label: '左肘', part: 'leftLowerArm', mode: 'elbow', side: 'left' },
  { key: 'rightElbow', label: '右肘', part: 'rightLowerArm', mode: 'elbow', side: 'right' },
  { key: 'leftWrist', label: '左手腕', part: 'leftHand', mode: 'override' },
  { key: 'rightWrist', label: '右手腕', part: 'rightHand', mode: 'override' },
  { key: 'leftHip', label: '左髋', part: 'leftUpperLeg', mode: 'hip', side: 'left' },
  { key: 'rightHip', label: '右髋', part: 'rightUpperLeg', mode: 'hip', side: 'right' },
  { key: 'leftKnee', label: '左膝', part: 'leftLowerLeg', mode: 'knee', side: 'left' },
  { key: 'rightKnee', label: '右膝', part: 'rightLowerLeg', mode: 'knee', side: 'right' },
  { key: 'leftAnkle', label: '左脚踝', part: 'leftAnkle', mode: 'override' },
  { key: 'rightAnkle', label: '右脚踝', part: 'rightAnkle', mode: 'override' },
  { key: 'leftToeBase', label: '左脚趾根', part: 'leftToeBase', mode: 'override' },
  { key: 'rightToeBase', label: '右脚趾根', part: 'rightToeBase', mode: 'override' }
];
const DIRECTOR_JOINT_DEF_BY_KEY = new Map(DIRECTOR_JOINT_DEFS.map(def => [def.key, def]));
const DIRECTOR_JOINT_OVERRIDE_LIMIT = 120;
const DIRECTOR_JOINT_AXIS_COLORS = {
  x: '#ff5a5f',
  y: '#22c55e',
  z: '#3b82f6'
};
const DIRECTOR_JOINT_HUD_DRAG_PIXELS = 240;
const DIRECTOR_JOINT_HUD_FINE_SCALE = 0.25;
const POSE_BACKGROUND_MAX_DIMENSION = 1600;
const POSE_BACKGROUND_JPEG_QUALITY = 0.88;
const POSE_BACKGROUND_TARGET_BYTES = 1200 * 1024;
const DIRECTOR_ROLE_COLORS = ['#4F8EF7', '#F25F5C', '#42C77A', '#F2B544', '#9B7CFF'];
const DIRECTOR_POSE_PRESETS = {
  stand: { label: '站立', controls: {} },
  tpose: {
    label: 'T型',
    controls: {
      leftShoulderSide: 0,
      leftShoulderFront: 90,
      leftElbow: 0,
      rightShoulderSide: 90,
      rightElbow: 0,
      leftHipSide: 0,
      leftKnee: 0,
      rightHipSide: 0,
      rightKnee: 0
    }
  },
  walk: {
    label: '行走',
    controls: {
      torsoTwist: -12,
      leftShoulderSide: 56,
      leftShoulderFront: 38,
      leftElbow: 22,
      rightShoulderSide: 38,
      rightShoulderFront: -56,
      rightElbow: 34,
      leftHipFront: -32,
      leftKnee: 12,
      rightHipFront: 42,
      rightKnee: 46
    }
  },
  sit: {
    label: '坐姿',
    controls: {
      torsoTwist: 0,
      leftHipSide: 5,
      leftHipFront: 92,
      leftKnee: 104,
      rightHipSide: 5,
      rightHipFront: 92,
      rightKnee: 104,
      leftShoulderSide: 28,
      leftShoulderFront: 8,
      leftElbow: 32,
      rightShoulderSide: 8,
      rightShoulderFront: 28,
      rightElbow: 32
    }
  },
  point: {
    label: '指向',
    controls: {
      torsoTwist: 10,
      headYaw: 10,
      rightShoulderSide: 92,
      rightShoulderFront: 88,
      rightElbow: 4,
      leftShoulderSide: -12,
      leftShoulderFront: 8,
      leftElbow: 24
    }
  },
  wave: {
    label: '挥手',
    controls: {
      headYaw: -10,
      rightShoulderSide: 128,
      rightShoulderFront: -8,
      rightElbow: 92,
      leftShoulderSide: 0,
      leftShoulderFront: 8,
      leftElbow: 18
    }
  },
  arms_crossed: {
    label: '抱臂',
    controls: {
      torsoTwist: 0,
      leftShoulderSide: 86,
      leftShoulderFront: 72,
      leftElbow: 138,
      rightShoulderSide: 72,
      rightShoulderFront: 86,
      rightElbow: 138
    }
  }
};
const CONTROL_DEFS = [
  { key: 'torsoTwist', label: '躯干扭转', min: -55, max: 55, value: 0 },
  { key: 'headYaw', label: '头部转向', min: -70, max: 70, value: 0 },
  { key: 'leftShoulderSide', label: '左臂前后', min: -125, max: 125, value: 0 },
  { key: 'leftShoulderFront', label: '左肩外展', min: 0, max: 155, value: 8 },
  { key: 'leftElbow', label: '左肘弯曲', min: 0, max: 165, value: 6 },
  { key: 'rightShoulderSide', label: '右肩外展', min: 0, max: 155, value: 8 },
  { key: 'rightShoulderFront', label: '右臂前后', min: -125, max: 125, value: 0 },
  { key: 'rightElbow', label: '右肘弯曲', min: 0, max: 165, value: 6 },
  { key: 'leftHipSide', label: '左腿外展', min: -55, max: 85, value: 2 },
  { key: 'leftHipFront', label: '左腿前后', min: -120, max: 120, value: 0 },
  { key: 'leftKnee', label: '左膝弯曲', min: 0, max: 165, value: 0 },
  { key: 'rightHipSide', label: '右腿外展', min: -55, max: 85, value: 2 },
  { key: 'rightHipFront', label: '右腿前后', min: -120, max: 120, value: 0 },
  { key: 'rightKnee', label: '右膝弯曲', min: 0, max: 165, value: 0 }
];

let modal = null;
let runtime = null;

function defaultPose() {
  return CONTROL_DEFS.reduce((acc, item) => {
    acc[item.key] = item.value;
    return acc;
  }, {});
}

function defaultHumanConfig() {
  return {
    skeletonVisible: true
  };
}

function normalizeHumanConfig(value = {}) {
  return {
    skeletonVisible: value.skeletonVisible !== false
  };
}

function clamp(value, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return min;
  return Math.max(min, Math.min(max, parsed));
}

function degToRad(value) {
  return THREE.MathUtils.degToRad(Number(value) || 0);
}

function getBackgroundUrl(images = []) {
  const first = images.find(image => image?.imageData || image?.base64 || image?.url || image?.imageUrl);
  return first?.imageData || first?.base64 || first?.url || first?.imageUrl || '';
}

function firstBackgroundReference(images = []) {
  return images.find(image => image?.imageData || image?.base64 || image?.url || image?.imageUrl) || null;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('背景图读取失败'));
    reader.readAsDataURL(file);
  });
}

function estimateDataUrlBytes(dataUrl) {
  const body = String(dataUrl || '').split(',')[1] || '';
  return Math.ceil(body.length * 0.75);
}

async function fileToPoseBackground(file) {
  const rawDataUrl = await fileToDataUrl(file);
  const image = await loadImage(rawDataUrl);
  const originalWidth = image.naturalWidth || image.width || 0;
  const originalHeight = image.naturalHeight || image.height || 0;
  const maxDimension = Math.max(originalWidth, originalHeight, 1);
  let scale = Math.min(1, POSE_BACKGROUND_MAX_DIMENSION / maxDimension);
  let quality = POSE_BACKGROUND_JPEG_QUALITY;
  let imageData = rawDataUrl;
  let width = originalWidth;
  let height = originalHeight;

  for (let attempt = 0; attempt < 4; attempt += 1) {
    width = Math.max(1, Math.round(originalWidth * scale));
    height = Math.max(1, Math.round(originalHeight * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(image, 0, 0, width, height);
    imageData = canvas.toDataURL('image/jpeg', quality);
    if (estimateDataUrlBytes(imageData) <= POSE_BACKGROUND_TARGET_BYTES || (scale <= 0.45 && quality <= 0.74)) break;
    scale *= 0.82;
    quality = Math.max(0.72, quality - 0.05);
  }

  const storedBytes = estimateDataUrlBytes(imageData);
  return {
    imageData,
    meta: {
      originalName: file.name || '上传背景图',
      originalBytes: Number(file.size || 0),
      originalWidth,
      originalHeight,
      width,
      height,
      storedBytes,
      mimeType: 'image/jpeg',
      compressed: imageData !== rawDataUrl || width !== originalWidth || height !== originalHeight,
      maxDimension: POSE_BACKGROUND_MAX_DIMENSION,
      quality
    }
  };
}

function backgroundImagesForNode(node = {}, connectedImages = []) {
  const images = [];
  if (node.backgroundImage) {
    images.push({
      imageData: node.backgroundImage,
      title: node.backgroundName || '上传背景图',
      source: node.backgroundSource || 'pose-upload',
      sourceNodeId: node.backgroundSourceNodeId || '',
      meta: node.backgroundMeta || null
    });
  }
  (connectedImages || []).forEach(image => images.push(image));
  return images;
}

function normalizePoseTitle(title, fallback = '姿态参考') {
  const value = String(title || fallback);
  return value === '3D 导演台' ? '姿态参考' : value;
}

function ensureModal() {
  if (modal) return modal;
  document.body.insertAdjacentHTML('beforeend', `
    <div class="desk-pose-studio" id="deskPoseStudio" aria-hidden="true">
      <div class="desk-pose-studio__panel" role="dialog" aria-modal="true" aria-label="Pose Reference">
        <header class="desk-pose-studio__bar">
          <div>
            <p data-pose-studio-eyebrow>Pose Reference</p>
            <h2 data-pose-studio-title>姿态编辑器</h2>
          </div>
          <div class="desk-pose-studio__bar-actions">
            <button type="button" data-pose-studio-reset>重置</button>
            <button type="button" class="is-primary" data-pose-studio-export>导出到节点</button>
            <button type="button" class="desk-pose-studio__close" data-pose-studio-close title="关闭" aria-label="关闭">×</button>
          </div>
        </header>
        <div class="desk-pose-studio__body">
          <section class="desk-pose-studio__stage-shell">
            <div class="desk-pose-studio__stage" data-pose-studio-stage>
              <img data-pose-studio-background alt="姿态参考背景" hidden>
              <div data-pose-studio-canvas></div>
              <div class="desk-director-joint-layer" data-director-joint-layer></div>
            </div>
            <div class="desk-pose-studio__stage-footer">
              <span data-pose-studio-background-label>未接入背景图</span>
              <div class="desk-pose-studio__background-tools">
                <label class="desk-pose-background-upload">
                  <input type="file" accept="image/*" data-pose-studio-upload-background>
                  <span>上传背景</span>
                </label>
                <button type="button" class="desk-pose-background-clear" data-pose-studio-clear-background disabled>清除上传</button>
                <label class="desk-switch">
                  <input type="checkbox" data-pose-studio-export-background>
                  <span></span>
                  <em>导出背景</em>
                </label>
              </div>
            </div>
          </section>
          <aside class="desk-pose-studio__controls" data-pose-studio-controls></aside>
        </div>
      </div>
    </div>
  `);
  modal = document.getElementById('deskPoseStudio');
  modal.querySelector('[data-pose-studio-close]')?.addEventListener('click', close);
  modal.querySelector('[data-pose-studio-upload-background]')?.addEventListener('change', event => {
    handleBackgroundUpload(event).catch(error => {
      const label = modal?.querySelector('[data-pose-studio-background-label]');
      if (label) label.textContent = error?.message || '背景图读取失败';
    });
  });
  modal.querySelector('[data-pose-studio-clear-background]')?.addEventListener('click', () => {
    clearUploadedBackground();
  });
  modal.querySelector('[data-pose-studio-reset]')?.addEventListener('click', () => {
    if (!runtime) return;
    if (runtime.mode === 'director_stage') {
      const selected = selectedDirectorCharacter();
      if (selected) {
        selected.boneControls = defaultPose();
        selected.jointOverrides = {};
        selected.posePreset = 'stand';
        syncDirectorControls();
        renderDirectorCharacters();
        persistDirectorData();
      }
      return;
    }
    runtime.pose = defaultPose();
    syncControls();
    updateMannequin();
  });
  modal.querySelector('[data-pose-studio-export]')?.addEventListener('click', () => {
    exportCurrentPose().catch(error => {
      console.error(error);
      close();
    });
  });
  return modal;
}

function directorDefaultCamera(index = 0) {
  const number = index + 1;
  return {
    id: `camera_${String(number).padStart(2, '0')}`,
    name: `机位${number}`,
    position: [0, 2.1, 5.4],
    target: [0, 1.45, 0],
    fov: 45,
    aspect: '16:9',
    thumbnail: ''
  };
}

function directorDefaultCharacter(index = 0) {
  const letter = String.fromCharCode(65 + index);
  const modelKey = index % 2 === 0 ? 'mixamo_xbot' : 'mixamo_ybot';
  return {
    id: `char_${letter.toLowerCase()}`,
    name: `角色${letter}`,
    modelKey,
    bodyPreset: directorBodyPresetForModel(modelKey),
    color: DIRECTOR_ROLE_COLORS[index % DIRECTOR_ROLE_COLORS.length],
    position: [(index - 0.5) * 1.35, 0, 0],
    rotation: [0, 0, 0],
    scale: 1,
    posePreset: 'stand',
    boneControls: defaultPose(),
    jointOverrides: {}
  };
}

function directorBodyPresetForModel(modelKey, fallback = 'neutral') {
  if (modelKey === 'mixamo_xbot') return 'female_proxy';
  if (modelKey === 'mixamo_ybot') return 'male_proxy';
  if (modelKey === 'procedural_mannequin') return 'neutral';
  return fallback || 'neutral';
}

function normalizeVector(value, fallback, length = 3) {
  const source = Array.isArray(value) ? value : fallback;
  return Array.from({ length }, (_, index) => {
    const item = Number(source?.[index]);
    return Number.isFinite(item) ? item : Number(fallback?.[index] || 0);
  });
}

function normalizeJointOverride(value = {}) {
  return {
    x: clamp(value.x ?? 0, -DIRECTOR_JOINT_OVERRIDE_LIMIT, DIRECTOR_JOINT_OVERRIDE_LIMIT),
    y: clamp(value.y ?? 0, -DIRECTOR_JOINT_OVERRIDE_LIMIT, DIRECTOR_JOINT_OVERRIDE_LIMIT),
    z: clamp(value.z ?? 0, -DIRECTOR_JOINT_OVERRIDE_LIMIT, DIRECTOR_JOINT_OVERRIDE_LIMIT)
  };
}

function normalizeJointOverrides(value = {}) {
  if (!value || typeof value !== 'object') return {};
  const overrides = {};
  DIRECTOR_JOINT_DEFS.forEach(def => {
    if (value[def.key] && typeof value[def.key] === 'object') {
      overrides[def.key] = normalizeJointOverride(value[def.key]);
    }
  });
  return overrides;
}

function migrateLeftShoulderControlsFromV1(controls = {}) {
  const migrated = { ...controls };
  const oldSide = controls.leftShoulderSide;
  const oldFront = controls.leftShoulderFront;
  migrated.leftShoulderSide = oldFront ?? defaultPose().leftShoulderSide;
  migrated.leftShoulderFront = oldSide ?? defaultPose().leftShoulderFront;
  return migrated;
}

function normalizeDirectorCharacter(value = {}, index = 0, options = {}) {
  const defaults = directorDefaultCharacter(index);
  const rawControls = { ...defaultPose(), ...(value.boneControls || value.controls || {}) };
  const controls = options.migrateLeftShoulderV1 ? migrateLeftShoulderControlsFromV1(rawControls) : rawControls;
  CONTROL_DEFS.forEach(def => {
    controls[def.key] = clamp(controls[def.key], def.min, def.max);
  });
  const modelKey = String(value.modelKey || defaults.modelKey);
  return {
    ...defaults,
    ...value,
    id: String(value.id || defaults.id),
    name: String(value.name || defaults.name),
    modelKey,
    bodyPreset: directorBodyPresetForModel(modelKey, String(value.bodyPreset || defaults.bodyPreset)),
    color: String(value.color || defaults.color),
    position: normalizeVector(value.position, defaults.position),
    rotation: normalizeVector(value.rotation, defaults.rotation),
    scale: clamp(value.scale ?? defaults.scale, 0.25, 2.5),
    posePreset: String(value.posePreset || defaults.posePreset),
    boneControls: controls,
    jointOverrides: normalizeJointOverrides(value.jointOverrides)
  };
}

function normalizeDirectorData(node = {}) {
  const raw = node.directorData && typeof node.directorData === 'object' ? node.directorData : {};
  const dataVersion = Number(raw.version || 1);
  const migrateLeftShoulderV1 = Array.isArray(raw.characters) && dataVersion < 2;
  let characters = Array.isArray(raw.characters)
    ? raw.characters.map((character, index) => normalizeDirectorCharacter(character, index, { migrateLeftShoulderV1 }))
    : [];
  if (!characters.length) characters = [directorDefaultCharacter(0), directorDefaultCharacter(1)];
  const cameras = Array.isArray(raw.cameras) && raw.cameras.length ? raw.cameras : [directorDefaultCamera(0)];
  const selectedId = characters.some(character => character.id === raw.selectedId) ? raw.selectedId : characters[0]?.id || '';
  const activeCameraId = cameras.some(camera => camera.id === raw.activeCameraId) ? raw.activeCameraId : cameras[0]?.id || '';
  const selectedJointId = DIRECTOR_JOINT_DEF_BY_KEY.has(raw.selectedJointId) ? raw.selectedJointId : '';
  return {
    version: 5,
    characters,
    props: Array.isArray(raw.props) ? raw.props : [],
    cameras: cameras.map((camera, index) => ({
      ...directorDefaultCamera(index),
      ...camera,
      id: String(camera.id || `camera_${String(index + 1).padStart(2, '0')}`),
      name: String(camera.name || `机位${index + 1}`),
      position: normalizeVector(camera.position, directorDefaultCamera(index).position),
      target: normalizeVector(camera.target, directorDefaultCamera(index).target),
      fov: clamp(camera.fov ?? 45, 25, 85),
      aspect: String(camera.aspect || '16:9'),
      thumbnail: String(camera.thumbnail || '')
    })),
    activeCameraId,
    selectedId,
    selectedJointId,
    viewMode: raw.viewMode === 'camera' ? 'camera' : 'director',
    transformMode: ['translate', 'rotate', 'scale'].includes(raw.transformMode) ? raw.transformMode : 'translate',
    editMode: raw.editMode === 'joint' ? 'joint' : 'character'
  };
}

function selectedDirectorCharacter() {
  const data = runtime?.directorData;
  if (!data?.characters?.length) return null;
  return data.characters.find(character => character.id === data.selectedId) || data.characters[0] || null;
}

function selectedDirectorJointDef() {
  const key = runtime?.directorData?.selectedJointId || '';
  return DIRECTOR_JOINT_DEF_BY_KEY.get(key) || null;
}

function activeDirectorCamera() {
  const data = runtime?.directorData;
  if (!data?.cameras?.length) return null;
  return data.cameras.find(camera => camera.id === data.activeCameraId) || data.cameras[0] || null;
}

function directorControlDef(key) {
  return CONTROL_DEFS.find(def => def.key === key) || null;
}

function setDirectorControlValue(character, key, value) {
  const def = directorControlDef(key);
  if (!character || !def) return;
  character.boneControls = { ...defaultPose(), ...(character.boneControls || {}) };
  character.boneControls[key] = clamp(value, def.min, def.max);
}

function directorJointMappedControlKeys(def) {
  if (!def) return [];
  if (def.mode === 'torso') return ['torsoTwist'];
  if (def.mode === 'head') return ['headYaw'];
  if (def.mode === 'shoulder') {
    return def.side === 'left'
      ? ['leftShoulderSide', 'leftShoulderFront']
      : ['rightShoulderSide', 'rightShoulderFront'];
  }
  if (def.mode === 'elbow') return [def.side === 'left' ? 'leftElbow' : 'rightElbow'];
  if (def.mode === 'hip') return [def.side === 'left' ? 'leftHipSide' : 'rightHipSide', def.side === 'left' ? 'leftHipFront' : 'rightHipFront'];
  if (def.mode === 'knee') return [def.side === 'left' ? 'leftKnee' : 'rightKnee'];
  return [];
}

function directorJointAxes(def) {
  if (!def) return [];
  if (def.mode === 'elbow' || def.mode === 'knee') return ['x'];
  if (def.mode === 'torso' || def.mode === 'head') return ['y'];
  if (def.mode === 'shoulder' || def.mode === 'hip') return ['y', 'z'];
  return ['x', 'y', 'z'];
}

function directorJointOverrideValue(character, jointKey) {
  return normalizeJointOverride(character?.jointOverrides?.[jointKey] || {});
}

function setDirectorJointOverride(character, jointKey, value) {
  if (!character || !DIRECTOR_JOINT_DEF_BY_KEY.has(jointKey)) return;
  const normalized = normalizeJointOverride(value);
  character.jointOverrides = {
    ...(character.jointOverrides || {}),
    [jointKey]: normalized
  };
}

function clearDirectorJointOverride(character, jointKey) {
  if (!character?.jointOverrides?.[jointKey]) return;
  const next = { ...(character.jointOverrides || {}) };
  delete next[jointKey];
  character.jointOverrides = next;
}

function selectDirectorJoint(jointKey) {
  if (!runtime?.directorData || !DIRECTOR_JOINT_DEF_BY_KEY.has(jointKey)) return;
  runtime.directorData.editMode = 'joint';
  runtime.directorData.selectedJointId = jointKey;
  renderDirectorJointHandles();
  attachDirectorTransformControls();
  syncDirectorControls();
  persistDirectorData();
}

function resetSelectedDirectorJoint() {
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  if (!selected || !def) return;
  const defaults = defaultPose();
  directorJointMappedControlKeys(def).forEach(key => {
    setDirectorControlValue(selected, key, defaults[key]);
  });
  clearDirectorJointOverride(selected, def.key);
  selected.posePreset = 'custom';
  updateSelectedDirectorCharacterPose();
  updateDirectorBoneInputs();
  renderDirectorJointHandles();
  attachDirectorTransformControls();
  persistDirectorData();
}

function captureDirectorCameraThumbnail() {
  const source = runtime?.renderer?.domElement;
  if (!source?.width || !source?.height) return '';
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 192;
    canvas.height = 108;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.7);
  } catch (_) {
    return '';
  }
}

function cameraDataFromCurrentView(camera = activeDirectorCamera()) {
  const base = camera || directorDefaultCamera(0);
  return {
    ...base,
    position: runtime?.camera?.position?.toArray?.() || base.position,
    target: runtime?.controls?.target?.toArray?.() || base.target,
    fov: clamp(runtime?.camera?.fov ?? base.fov ?? 45, 25, 85),
    thumbnail: captureDirectorCameraThumbnail() || base.thumbnail || ''
  };
}

function updateActiveDirectorCameraFromView(options = {}) {
  const data = runtime?.directorData;
  if (!data?.cameras?.length) return null;
  const active = activeDirectorCamera();
  if (!active) return null;
  const next = cameraDataFromCurrentView(active);
  if (options.name) next.name = String(options.name);
  data.cameras = data.cameras.map(camera => camera.id === active.id ? next : camera);
  return next;
}

function persistDirectorData() {
  if (!runtime?.node) return;
  runtime.node.mode = 'director_stage';
  runtime.node.poseTitle = normalizePoseTitle(runtime.node.poseTitle);
  runtime.node.directorData = runtime.directorData;
  runtime.onUpdate?.({
    mode: 'director_stage',
    poseTitle: runtime.node.poseTitle,
    directorData: runtime.directorData
  });
  window.DesktopState?.saveSettings?.();
}

function updateDirectorPropertyInputs() {
  if (runtime?.mode !== 'director_stage') return;
  const selected = selectedDirectorCharacter();
  if (!selected || !modal) return;
  const values = {
    'position.0': selected.position?.[0] ?? 0,
    'position.1': selected.position?.[1] ?? 0,
    'position.2': selected.position?.[2] ?? 0,
    'rotation.1': selected.rotation?.[1] ?? 0,
    scale: selected.scale ?? 1
  };
  Object.entries(values).forEach(([key, value]) => {
    const input = modal.querySelector(`[data-director-field="${key}"]`);
    if (!input) return;
    const step = input.getAttribute('step') || '0.01';
    input.value = Number(value).toFixed(step === '1' ? 0 : 2);
  });
}

function updateDirectorCharacterFromObject(character, object) {
  if (!character || !object) return;
  character.position = object.position.toArray();
  character.rotation = [
    THREE.MathUtils.radToDeg(object.rotation.x || 0),
    THREE.MathUtils.radToDeg(object.rotation.y || 0),
    THREE.MathUtils.radToDeg(object.rotation.z || 0)
  ];
  character.scale = clamp(object.scale.x || 1, 0.25, 2.5);
}

function directorNumberInput(label, key, value, min, max, step = '0.01') {
  return `
    <label class="desk-director-field">
      <span>${label}</span>
      <input type="number" min="${min}" max="${max}" step="${step}" value="${Number(value).toFixed(step === '1' ? 0 : 2)}" data-director-field="${key}">
    </label>
  `;
}

function cameraNumberInput(label, key, value, min, max, step = '0.01') {
  return `
    <label class="desk-director-field">
      <span>${label}</span>
      <input type="number" min="${min}" max="${max}" step="${step}" value="${Number(value).toFixed(step === '1' ? 0 : 2)}" data-director-camera-field="${key}">
    </label>
  `;
}

function buildDirectorControls() {
  const wrap = modal.querySelector('[data-pose-studio-controls]');
  if (!wrap) return;
  const data = runtime.directorData;
  const selected = selectedDirectorCharacter();
  const camera = activeDirectorCamera() || directorDefaultCamera(0);
  const selectedJoint = selectedDirectorJointDef();
  const p = selected?.position || [0, 0, 0];
  const r = selected?.rotation || [0, 0, 0];
  wrap.innerHTML = `
    <section class="desk-director-panel">
      <div class="desk-director-panel__head">
        <strong>场景</strong>
        <button type="button" data-director-add-character>添加角色</button>
      </div>
      <div class="desk-director-scene-list">
        ${(data.characters || []).map(character => `
          <button type="button" class="${character.id === data.selectedId ? 'is-active' : ''}" data-director-select="${character.id}">
            <span style="background:${character.color}"></span>
            <em>${character.name}</em>
          </button>
        `).join('')}
      </div>
      <div class="desk-pose-segmented" role="group" aria-label="视角">
        <button type="button" class="${data.viewMode !== 'camera' ? 'is-active' : ''}" data-director-view="director">导演视角</button>
        <button type="button" class="${data.viewMode === 'camera' ? 'is-active' : ''}" data-director-view="camera">机位视角</button>
      </div>
      <div class="desk-pose-segmented" role="group" aria-label="变换工具">
        <button type="button" class="${data.transformMode === 'translate' ? 'is-active' : ''}" data-director-transform="translate">移动</button>
        <button type="button" class="${data.transformMode === 'rotate' ? 'is-active' : ''}" data-director-transform="rotate">旋转</button>
        <button type="button" class="${data.transformMode === 'scale' ? 'is-active' : ''}" data-director-transform="scale">缩放</button>
      </div>
      <div class="desk-pose-segmented" role="group" aria-label="编辑对象">
        <button type="button" class="${data.editMode !== 'joint' ? 'is-active' : ''}" data-director-edit-mode="character">角色</button>
        <button type="button" class="${data.editMode === 'joint' ? 'is-active' : ''}" data-director-edit-mode="joint">关节</button>
      </div>
    </section>
    <section class="desk-director-panel">
      <div class="desk-director-panel__head">
        <strong>关节</strong>
        <span>${selectedJoint?.label || '未选择'}</span>
      </div>
      <div class="desk-director-joint-list">
        ${DIRECTOR_JOINT_DEFS.map(def => `
          <button type="button" class="${selectedJoint?.key === def.key ? 'is-active' : ''}" data-director-joint="${def.key}">
            ${def.label}
          </button>
        `).join('')}
      </div>
      <div class="desk-director-joint-actions">
        <button type="button" data-director-reset-joint ${selectedJoint ? '' : 'disabled'}>重置当前关节</button>
      </div>
    </section>
    <section class="desk-director-panel">
      <div class="desk-director-panel__head">
        <strong>机位</strong>
        <button type="button" data-director-add-camera>添加机位</button>
      </div>
      <div class="desk-director-camera-list">
        ${(data.cameras || []).map(item => `
          <button type="button" class="${item.id === data.activeCameraId ? 'is-active' : ''}" data-director-camera="${item.id}">
            ${item.thumbnail ? `<img src="${item.thumbnail}" alt="">` : '<span></span>'}
            <em>${item.name}</em>
          </button>
        `).join('')}
      </div>
      <label class="desk-director-field is-wide">
        <span>名称</span>
        <input type="text" value="${camera.name}" data-director-camera-name>
      </label>
      <div class="desk-director-field-grid">
        ${cameraNumberInput('FOV', 'fov', camera.fov, 25, 85, '1')}
      </div>
      <div class="desk-director-camera-actions">
        <button type="button" data-director-save-camera>保存当前视角</button>
        <button type="button" data-director-apply-camera>切到机位视角</button>
      </div>
    </section>
    <section class="desk-director-panel">
      <div class="desk-director-panel__head">
        <strong>${selected ? selected.name : '未选择角色'}</strong>
        <span>低模代理</span>
      </div>
      ${selected ? `
        <label class="desk-director-field is-wide">
          <span>名称</span>
          <input type="text" value="${selected.name}" data-director-name>
        </label>
        <label class="desk-director-field is-wide">
          <span>人偶</span>
          <select data-director-model>
            ${DIRECTOR_MODEL_OPTIONS.map(option => `
              <option value="${option.key}" ${selected.modelKey === option.key ? 'selected' : ''}>${option.label}</option>
            `).join('')}
          </select>
        </label>
        <label class="desk-director-field is-wide">
          <span>颜色</span>
          <input type="color" value="${selected.color}" data-director-color>
        </label>
        <div class="desk-director-field-grid">
          ${directorNumberInput('X', 'position.0', p[0], -5, 5)}
          ${directorNumberInput('Y', 'position.1', p[1], 0, 3)}
          ${directorNumberInput('Z', 'position.2', p[2], -5, 5)}
          ${directorNumberInput('转Y', 'rotation.1', r[1], -180, 180, '1')}
          ${directorNumberInput('缩放', 'scale', selected.scale, 0.25, 2.5)}
        </div>
      ` : '<p class="desk-director-empty">添加或选择一个角色。</p>'}
    </section>
    <section class="desk-director-panel">
      <div class="desk-director-panel__head">
        <strong>姿势</strong>
        <span>${DIRECTOR_POSE_PRESETS[selected?.posePreset || 'stand']?.label || '自定义'}</span>
      </div>
      <div class="desk-director-preset-grid">
        ${Object.entries(DIRECTOR_POSE_PRESETS).map(([key, preset]) => `
          <button type="button" class="${selected?.posePreset === key ? 'is-active' : ''}" data-director-pose="${key}">${preset.label}</button>
        `).join('')}
      </div>
      ${selected ? CONTROL_DEFS.map(def => `
        <label class="desk-pose-control">
          <span><strong>${def.label}</strong><em data-director-pose-value="${def.key}">${Math.round(selected.boneControls?.[def.key] ?? def.value)}°</em></span>
          <input type="range" min="${def.min}" max="${def.max}" value="${selected.boneControls?.[def.key] ?? def.value}" data-director-bone="${def.key}">
        </label>
      `).join('') : ''}
    </section>
  `;
  wrap.scrollTop = 0;
  bindDirectorControls();
}

function bindDirectorControls() {
  const wrap = modal.querySelector('[data-pose-studio-controls]');
  if (!wrap) return;
  wrap.querySelector('[data-director-add-character]')?.addEventListener('click', () => {
    const index = runtime.directorData.characters.length;
    const character = directorDefaultCharacter(index);
    runtime.directorData.characters.push(character);
    runtime.directorData.selectedId = character.id;
    renderDirectorCharacters();
    syncDirectorControls();
    persistDirectorData();
  });
  wrap.querySelectorAll('[data-director-select]').forEach(button => {
    button.addEventListener('click', event => {
      runtime.directorData.selectedId = event.currentTarget.dataset.directorSelect || runtime.directorData.selectedId;
      renderDirectorCharacters();
      syncDirectorControls();
      persistDirectorData();
    });
  });
  wrap.querySelectorAll('[data-director-view]').forEach(button => {
    button.addEventListener('click', event => {
      runtime.directorData.viewMode = event.currentTarget.dataset.directorView === 'camera' ? 'camera' : 'director';
      applyDirectorViewMode();
      syncDirectorControls();
      persistDirectorData();
    });
  });
  wrap.querySelectorAll('[data-director-transform]').forEach(button => {
    button.addEventListener('click', event => {
      const mode = event.currentTarget.dataset.directorTransform || 'translate';
      runtime.directorData.transformMode = ['translate', 'rotate', 'scale'].includes(mode) ? mode : 'translate';
      if (runtime.directorData.editMode !== 'joint') {
        runtime.transformControls?.setMode(runtime.directorData.transformMode);
      }
      syncDirectorControls();
      persistDirectorData();
    });
  });
  wrap.querySelectorAll('[data-director-edit-mode]').forEach(button => {
    button.addEventListener('click', event => {
      runtime.directorData.editMode = event.currentTarget.dataset.directorEditMode === 'joint' ? 'joint' : 'character';
      if (runtime.directorData.editMode === 'character') runtime.directorData.selectedJointId = '';
      renderDirectorJointHandles();
      attachDirectorTransformControls();
      syncDirectorControls();
      persistDirectorData();
    });
  });
  wrap.querySelectorAll('[data-director-joint]').forEach(button => {
    button.addEventListener('click', event => {
      selectDirectorJoint(event.currentTarget.dataset.directorJoint || '');
    });
  });
  wrap.querySelector('[data-director-reset-joint]')?.addEventListener('click', () => {
    resetSelectedDirectorJoint();
  });
  wrap.querySelector('[data-director-add-camera]')?.addEventListener('click', () => {
    const index = runtime.directorData.cameras.length;
    const camera = cameraDataFromCurrentView({
      ...directorDefaultCamera(index),
      id: `camera_${String(index + 1).padStart(2, '0')}`,
      name: `机位${index + 1}`
    });
    runtime.directorData.cameras.push(camera);
    runtime.directorData.activeCameraId = camera.id;
    runtime.directorData.viewMode = 'camera';
    applyDirectorViewMode();
    syncDirectorControls();
    persistDirectorData();
  });
  wrap.querySelectorAll('[data-director-camera]').forEach(button => {
    button.addEventListener('click', event => {
      runtime.directorData.activeCameraId = event.currentTarget.dataset.directorCamera || runtime.directorData.activeCameraId;
      runtime.directorData.viewMode = 'camera';
      applyDirectorViewMode();
      syncDirectorControls();
      persistDirectorData();
    });
  });
  wrap.querySelector('[data-director-camera-name]')?.addEventListener('input', event => {
    const camera = activeDirectorCamera();
    if (!camera) return;
    camera.name = String(event.target.value || '机位');
    persistDirectorData();
  });
  wrap.querySelectorAll('[data-director-camera-field]').forEach(input => {
    input.addEventListener('input', event => {
      const camera = activeDirectorCamera();
      if (!camera) return;
      const field = event.target.dataset.directorCameraField || '';
      const value = Number(event.target.value);
      if (!Number.isFinite(value)) return;
      if (field === 'fov') {
        camera.fov = clamp(value, 25, 85);
        runtime.camera.fov = camera.fov;
        runtime.camera.updateProjectionMatrix();
        runtime.renderer?.render(runtime.scene, runtime.camera);
      }
      persistDirectorData();
    });
  });
  wrap.querySelector('[data-director-save-camera]')?.addEventListener('click', () => {
    updateActiveDirectorCameraFromView();
    runtime.directorData.viewMode = 'camera';
    syncDirectorControls();
    persistDirectorData();
  });
  wrap.querySelector('[data-director-apply-camera]')?.addEventListener('click', () => {
    runtime.directorData.viewMode = 'camera';
    applyDirectorViewMode();
    syncDirectorControls();
    persistDirectorData();
  });
  wrap.querySelector('[data-director-name]')?.addEventListener('input', event => {
    const selected = selectedDirectorCharacter();
    if (!selected) return;
    selected.name = String(event.target.value || '角色');
    renderDirectorCharacters();
    persistDirectorData();
  });
  wrap.querySelector('[data-director-model]')?.addEventListener('change', event => {
    const selected = selectedDirectorCharacter();
    if (!selected) return;
    selected.modelKey = String(event.target.value || 'mixamo_xbot');
    selected.bodyPreset = directorBodyPresetForModel(selected.modelKey);
    renderDirectorCharacters();
    persistDirectorData();
  });
  wrap.querySelector('[data-director-color]')?.addEventListener('input', event => {
    const selected = selectedDirectorCharacter();
    if (!selected) return;
    selected.color = String(event.target.value || selected.color);
    renderDirectorCharacters();
    persistDirectorData();
  });
  wrap.querySelectorAll('[data-director-field]').forEach(input => {
    input.addEventListener('input', event => {
      const selected = selectedDirectorCharacter();
      if (!selected) return;
      const field = event.target.dataset.directorField || '';
      const value = Number(event.target.value);
      if (!Number.isFinite(value)) return;
      if (field.startsWith('position.')) {
        selected.position[Number(field.split('.')[1])] = value;
      } else if (field.startsWith('rotation.')) {
        selected.rotation[Number(field.split('.')[1])] = value;
      } else if (field === 'scale') {
        selected.scale = clamp(value, 0.25, 2.5);
      }
      renderDirectorCharacters();
      persistDirectorData();
    });
  });
  wrap.querySelectorAll('[data-director-pose]').forEach(button => {
    button.addEventListener('click', event => {
      const selected = selectedDirectorCharacter();
      const key = event.currentTarget.dataset.directorPose || 'stand';
      const preset = DIRECTOR_POSE_PRESETS[key] || DIRECTOR_POSE_PRESETS.stand;
      if (!selected) return;
      selected.posePreset = key;
      selected.boneControls = { ...defaultPose(), ...(preset.controls || {}) };
      renderDirectorCharacters();
      syncDirectorControls();
      persistDirectorData();
    });
  });
  wrap.querySelectorAll('[data-director-bone]').forEach(input => {
    input.addEventListener('input', event => {
      const selected = selectedDirectorCharacter();
      const def = CONTROL_DEFS.find(item => item.key === event.target.dataset.directorBone);
      if (!selected || !def) return;
      selected.boneControls[def.key] = clamp(event.target.value, def.min, def.max);
      selected.posePreset = 'custom';
      const label = modal?.querySelector(`[data-director-pose-value="${def.key}"]`);
      if (label) label.textContent = `${Math.round(selected.boneControls[def.key])}°`;
      renderDirectorCharacters();
      persistDirectorData();
    });
  });
}

function syncDirectorControls() {
  if (runtime?.mode !== 'director_stage') return;
  buildDirectorControls();
}

function buildControls() {
  if (runtime?.mode === 'director_stage') {
    buildDirectorControls();
    return;
  }
  const wrap = modal.querySelector('[data-pose-studio-controls]');
  if (!wrap) return;
  wrap.innerHTML = `
    <section class="desk-pose-human-panel" data-pose-human-panel>
      <div class="desk-pose-human-panel__head">
        <strong>骨架参考</strong>
        <span data-pose-skeleton-label>已显示</span>
      </div>
      <div class="desk-pose-human-toggles">
        <label class="desk-switch">
          <input type="checkbox" data-pose-skeleton-visible>
          <span></span>
          <em>骨架</em>
        </label>
      </div>
    </section>
    ${CONTROL_DEFS.map(def => `
    <label class="desk-pose-control">
      <span><strong>${def.label}</strong><em data-pose-value="${def.key}">${def.value}°</em></span>
      <input type="range" min="${def.min}" max="${def.max}" value="${def.value}" data-pose-control="${def.key}">
    </label>
  `).join('')}`;
  wrap.scrollTop = 0;
  wrap.querySelectorAll('[data-pose-control]').forEach(input => {
    input.addEventListener('input', event => {
      const def = CONTROL_DEFS.find(item => item.key === event.target.dataset.poseControl);
      if (!def || !runtime) return;
      runtime.pose[def.key] = clamp(event.target.value, def.min, def.max);
      syncControlValue(def.key);
      updateMannequin();
    });
  });
  wrap.querySelector('[data-pose-skeleton-visible]')?.addEventListener('change', event => {
    if (!runtime) return;
    runtime.humanConfig.skeletonVisible = !!event.target.checked;
    syncHumanControls();
    applyHumanVisibility();
    persistHumanConfig();
  });
  syncHumanControls();
}

function syncControlValue(key) {
  const value = Math.round(Number(runtime?.pose?.[key] || 0));
  const label = modal?.querySelector(`[data-pose-value="${key}"]`);
  if (label) label.textContent = `${value}°`;
}

function syncControls() {
  CONTROL_DEFS.forEach(def => {
    const value = clamp(runtime?.pose?.[def.key] ?? def.value, def.min, def.max);
    runtime.pose[def.key] = value;
    const input = modal?.querySelector(`[data-pose-control="${def.key}"]`);
    if (input) input.value = String(value);
    syncControlValue(def.key);
  });
}

function syncHumanControls() {
  if (!runtime?.humanConfig) return;
  const config = runtime.humanConfig;
  const skeletonInput = modal?.querySelector('[data-pose-skeleton-visible]');
  if (skeletonInput) skeletonInput.checked = config.skeletonVisible !== false;
  const label = modal?.querySelector('[data-pose-skeleton-label]');
  if (label) {
    label.textContent = config.skeletonVisible === false ? '已隐藏' : '已显示';
  }
}

function persistHumanConfig() {
  if (!runtime?.node) return;
  runtime.node.humanConfig = normalizeHumanConfig(runtime.humanConfig);
  runtime.onUpdate?.({ humanConfig: runtime.node.humanConfig });
  window.DesktopState?.saveSettings?.();
}

function applyHumanVisibility() {
  if (!runtime) return;
  const config = runtime.humanConfig || defaultHumanConfig();
  if (runtime.partsGroup) {
    runtime.partsGroup.visible = config.skeletonVisible !== false;
  }
}

function createSegment(scene, name, radius, color) {
  const geometry = new THREE.CylinderGeometry(1, 1, 1, 18);
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.58, metalness: 0.06 });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = name;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}

function createJoint(scene, name, radius, color) {
  const geometry = new THREE.SphereGeometry(1, 24, 16);
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.04 });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = name;
  mesh.scale.setScalar(radius);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}

function setSegment(mesh, a, b, radius) {
  if (!mesh || mesh.isBone) return;
  const delta = new THREE.Vector3().subVectors(b, a);
  const length = Math.max(0.001, delta.length());
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.clone().normalize());
  mesh.scale.set(radius, length, radius);
}

function bodyLateralSign(side) {
  return side < 0 ? 1 : -1;
}

function directionFromSideFront(side, liftAngle, frontAngle) {
  const sideLift = clamp(liftAngle, 0, degToRad(155));
  const frontLift = clamp(frontAngle, degToRad(-125), degToRad(125));
  const lateralSign = bodyLateralSign(side);
  return new THREE.Vector3(
    lateralSign * Math.sin(sideLift),
    -Math.cos(sideLift) * Math.cos(frontLift),
    Math.sin(frontLift)
  ).normalize();
}

function elbowBendGuide(side, liftAngle, frontAngle) {
  const lift = clamp(Math.sin(liftAngle), 0, 1);
  const forwardSign = Math.abs(Math.sin(frontAngle)) > 0.08 ? Math.sign(Math.sin(frontAngle)) : 1;
  const lateralSign = bodyLateralSign(side);
  return new THREE.Vector3(
    lateralSign * (0.04 + lift * 0.1),
    0.3 + lift * 0.24,
    forwardSign
  ).normalize();
}

function rotateDirectionToward(from, toward, amountRadians) {
  const start = from.clone().normalize();
  const target = toward.clone().normalize();
  if (start.lengthSq() < 0.000001 || target.lengthSq() < 0.000001) return start;
  const angle = start.angleTo(target);
  if (angle < 0.0001) return start;
  const axis = new THREE.Vector3().crossVectors(start, target);
  if (axis.lengthSq() < 0.000001) {
    axis.crossVectors(start, Math.abs(start.y) < 0.95 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0));
  }
  axis.normalize();
  return start.applyAxisAngle(axis, Math.min(Math.abs(amountRadians), angle)).normalize();
}

function armPoints(side, pose) {
  const lateralSign = bodyLateralSign(side);
  const shoulder = new THREE.Vector3(0.46 * lateralSign, 2.6, 0);
  const sideAngle = degToRad(side < 0 ? pose.leftShoulderFront : pose.rightShoulderSide);
  const frontAngle = degToRad(side < 0 ? pose.leftShoulderSide : pose.rightShoulderFront);
  const elbowAngle = degToRad(pose[side < 0 ? 'leftElbow' : 'rightElbow']);
  const upper = directionFromSideFront(side, sideAngle, frontAngle);
  const elbow = shoulder.clone().add(upper.clone().multiplyScalar(0.72));
  const liftAngle = Math.max(0, sideAngle);
  const bendGuide = elbowBendGuide(side, liftAngle, frontAngle);
  const lower = rotateDirectionToward(upper, bendGuide, elbowAngle * 0.92);
  const hand = elbow.clone().add(lower.multiplyScalar(0.68));
  return { shoulder, elbow, hand };
}

function legPoints(side, pose) {
  const lateralSign = bodyLateralSign(side);
  const hip = new THREE.Vector3(0.24 * lateralSign, 1.42, 0);
  const sideAngle = degToRad(pose[side < 0 ? 'leftHipSide' : 'rightHipSide']);
  const frontAngle = degToRad(pose[side < 0 ? 'leftHipFront' : 'rightHipFront']);
  const kneeAngle = degToRad(pose[side < 0 ? 'leftKnee' : 'rightKnee']);
  const upper = new THREE.Vector3(
    lateralSign * Math.sin(sideAngle) * 0.75,
    -Math.cos(frontAngle),
    Math.sin(frontAngle)
  ).normalize();
  const knee = hip.clone().add(upper.multiplyScalar(0.86));
  const lowerAngle = frontAngle - kneeAngle * 0.95;
  const lower = new THREE.Vector3(
    lateralSign * Math.sin(sideAngle) * 0.34,
    -Math.cos(lowerAngle),
    Math.sin(lowerAngle)
  ).normalize();
  const ankle = knee.clone().add(lower.multiplyScalar(0.82));
  return { hip, knee, ankle };
}

function buildPoseSkeleton(pose) {
  const twist = degToRad(pose.torsoTwist);
  const headYaw = degToRad(pose.headYaw);
  const points = {
    pelvis: new THREE.Vector3(0, 1.38, 0),
    chest: new THREE.Vector3(0, 2.38, 0),
    neck: new THREE.Vector3(0, 2.82, 0),
    head: new THREE.Vector3(Math.sin(headYaw) * 0.08, 3.13, Math.cos(headYaw) * 0.04)
  };
  const leftArm = armPoints(-1, pose);
  const rightArm = armPoints(1, pose);
  const leftLeg = legPoints(-1, pose);
  const rightLeg = legPoints(1, pose);
  const twistQuat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), twist);
  [leftArm.shoulder, leftArm.elbow, leftArm.hand, rightArm.shoulder, rightArm.elbow, rightArm.hand].forEach(point => {
    point.sub(points.chest).applyQuaternion(twistQuat).add(points.chest);
  });
  return { points, leftArm, rightArm, leftLeg, rightLeg, twist, headYaw };
}

function updateMannequin() {
  if (!runtime?.parts) return;
  const pose = runtime.pose;
  const parts = runtime.parts;
  const skeleton = buildPoseSkeleton(pose);
  const { points, leftArm, rightArm, leftLeg, rightLeg } = skeleton;

  setSegment(parts.spine, points.pelvis, points.chest, 0.026);
  setSegment(parts.neck, points.chest, points.neck, 0.022);
  setSegment(parts.leftUpperArm, leftArm.shoulder, leftArm.elbow, 0.02);
  setSegment(parts.leftLowerArm, leftArm.elbow, leftArm.hand, 0.018);
  setSegment(parts.rightUpperArm, rightArm.shoulder, rightArm.elbow, 0.02);
  setSegment(parts.rightLowerArm, rightArm.elbow, rightArm.hand, 0.018);
  setSegment(parts.leftUpperLeg, leftLeg.hip, leftLeg.knee, 0.023);
  setSegment(parts.leftLowerLeg, leftLeg.knee, leftLeg.ankle, 0.02);
  setSegment(parts.rightUpperLeg, rightLeg.hip, rightLeg.knee, 0.023);
  setSegment(parts.rightLowerLeg, rightLeg.knee, rightLeg.ankle, 0.02);

  Object.entries({
    pelvis: points.pelvis,
    chest: points.chest,
    neck: points.neck,
    head: points.head,
    leftShoulder: leftArm.shoulder,
    leftElbow: leftArm.elbow,
    leftHand: leftArm.hand,
    rightShoulder: rightArm.shoulder,
    rightElbow: rightArm.elbow,
    rightHand: rightArm.hand,
    leftHip: leftLeg.hip,
    leftKnee: leftLeg.knee,
    leftAnkle: leftLeg.ankle,
    rightHip: rightLeg.hip,
    rightKnee: rightLeg.knee,
    rightAnkle: rightLeg.ankle
  }).forEach(([name, point]) => {
    if (parts[name]) parts[name].position.copy(point);
  });
  parts.head.scale.setScalar(0.082);
  applyHumanVisibility();
  runtime.renderer.render(runtime.scene, runtime.camera);
}

function createDirectorSegment(parent, name, color, radius = 0.055) {
  const geometry = new THREE.CylinderGeometry(1, 1, 1, 10);
  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.66,
    metalness: 0.02,
    flatShading: true
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = name;
  mesh.userData.directorPickable = true;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  mesh.userData.segmentRadius = radius;
  return mesh;
}

function createDirectorJoint(parent, name, color, radius = 0.085) {
  const geometry = new THREE.IcosahedronGeometry(radius, 1);
  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.62,
    metalness: 0.02,
    flatShading: true
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = name;
  mesh.userData.directorPickable = true;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function normalizeDirectorPartName(name) {
  return String(name || '')
    .replace(/\.\d+$/g, '')
    .replace(/[^a-zA-Z0-9]/g, '')
    .toLowerCase();
}

function collectDirectorGlbPoseParts(model) {
  const parts = {};
  const restQuaternions = {};
  let boneCount = 0;
  let skinnedMeshCount = 0;
  const aliasToKey = new Map();
  Object.entries(DIRECTOR_GLB_PART_ALIASES).forEach(([key, aliases]) => {
    aliases.forEach(alias => {
      const normalized = normalizeDirectorPartName(alias);
      if (!aliasToKey.has(normalized)) aliasToKey.set(normalized, key);
    });
  });
  model.traverse(child => {
    if (child.isBone) boneCount += 1;
    if (child.isSkinnedMesh) skinnedMeshCount += 1;
    const normalized = normalizeDirectorPartName(child.name);
    const key = aliasToKey.get(normalized);
    if (!key || parts[key]) return;
    if (child.isMesh || child.isBone || child.type === 'Object3D' || child.type === 'Group') {
      parts[key] = child;
      restQuaternions[key] = child.quaternion.clone();
    }
  });
  return {
    parts,
    restQuaternions,
    rigMode: boneCount ? 'bones' : 'parts',
    boneCount,
    skinnedMeshCount,
    matchedKeys: Object.keys(parts).sort()
  };
}

function createDirectorCharacterGroup(character) {
  const group = new THREE.Group();
  group.name = character.name;
  group.userData.characterId = character.id;
  group.userData.characterRoot = true;
  group.position.set(...normalizeVector(character.position, [0, 0, 0]));
  group.rotation.set(0, degToRad(character.rotation?.[1] || 0), 0);
  group.scale.setScalar(clamp(character.scale ?? 1, 0.25, 2.5));
  const assetKey = character.modelKey && character.modelKey !== 'procedural_mannequin' ? character.modelKey : 'mixamo_xbot';
  const template = runtime?.directorAssets?.templates?.[assetKey] || runtime?.directorAssets?.templates?.mixamo_xbot || null;
  if (template) {
    const model = cloneSkeleton(template);
    model.name = `${character.name}-glb-mannequin`;
    model.userData.directorPickable = true;
    model.userData.characterId = character.id;
    model.traverse(child => {
      child.userData.characterId = character.id;
      child.userData.directorPickable = true;
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
        if (child.material) {
          const nextMaterial = child.material.clone();
          nextMaterial.color = new THREE.Color(character.color || '#4F8EF7');
          nextMaterial.roughness = 0.72;
          child.material = nextMaterial;
        }
      }
    });
    group.add(model);
    const glbPose = collectDirectorGlbPoseParts(model);
    group.userData.parts = glbPose.parts;
    group.userData.glbPose = glbPose;
    group.userData.assetMode = 'glb';
    return group;
  }
  const color = new THREE.Color(character.color || '#4F8EF7');
  const darker = color.clone().multiplyScalar(0.72);
  const parts = {
    spine: createDirectorSegment(group, 'spine', darker, 0.12),
    neckSegment: createDirectorSegment(group, 'neckSegment', darker, 0.075),
    leftUpperArm: createDirectorSegment(group, 'leftUpperArm', color, 0.065),
    leftLowerArm: createDirectorSegment(group, 'leftLowerArm', color, 0.055),
    rightUpperArm: createDirectorSegment(group, 'rightUpperArm', color, 0.065),
    rightLowerArm: createDirectorSegment(group, 'rightLowerArm', color, 0.055),
    leftUpperLeg: createDirectorSegment(group, 'leftUpperLeg', color, 0.08),
    leftLowerLeg: createDirectorSegment(group, 'leftLowerLeg', color, 0.065),
    rightUpperLeg: createDirectorSegment(group, 'rightUpperLeg', color, 0.08),
    rightLowerLeg: createDirectorSegment(group, 'rightLowerLeg', color, 0.065)
  };
  ['pelvis', 'chest', 'neck', 'head', 'leftShoulder', 'leftElbow', 'leftHand', 'rightShoulder', 'rightElbow', 'rightHand', 'leftHip', 'leftKnee', 'leftAnkle', 'rightHip', 'rightKnee', 'rightAnkle'].forEach(name => {
    parts[name] = createDirectorJoint(group, name, name === 'head' ? darker : color, name === 'head' ? 0.14 : 0.07);
  });
  group.userData.parts = parts;
  group.traverse(child => {
    child.userData.characterId = character.id;
  });
  group.userData.assetMode = 'procedural';
  return group;
}

function setDirectorBonePoseRotation(group, key, rotation) {
  const poseMeta = group?.userData?.glbPose;
  const bone = poseMeta?.parts?.[key];
  if (!bone?.isBone) return false;
  const rest = poseMeta.restQuaternions?.[key] || new THREE.Quaternion();
  const delta = new THREE.Quaternion().setFromEuler(new THREE.Euler(
    rotation.x || 0,
    rotation.y || 0,
    rotation.z || 0,
    'XYZ'
  ));
  bone.quaternion.copy(rest).multiply(delta);
  bone.updateMatrixWorld(true);
  return true;
}

function applyDirectorJointOverrides(group, character) {
  const overrides = character?.jointOverrides || {};
  const parts = group?.userData?.glbPose?.parts || group?.userData?.parts || {};
  let applied = false;
  Object.entries(overrides).forEach(([jointKey, rotation]) => {
    const def = DIRECTOR_JOINT_DEF_BY_KEY.get(jointKey);
    const part = def ? parts[def.part] : null;
    if (!part) return;
    const normalized = normalizeJointOverride(rotation);
    const delta = new THREE.Quaternion().setFromEuler(new THREE.Euler(
      degToRad(normalized.x),
      degToRad(normalized.y),
      degToRad(normalized.z),
      'XYZ'
    ));
    if (part.isBone) {
      part.quaternion.multiply(delta);
      part.updateMatrixWorld(true);
      applied = true;
      return;
    }
    if (part.rotation) {
      part.rotation.x += degToRad(normalized.x);
      part.rotation.y += degToRad(normalized.y);
      part.rotation.z += degToRad(normalized.z);
      part.updateMatrixWorld?.(true);
      applied = true;
    }
  });
  return applied;
}

function directorWorldPosition(object) {
  const position = new THREE.Vector3();
  object?.updateWorldMatrix?.(true, false);
  object?.getWorldPosition?.(position);
  return position;
}

function disposeDirectorObject(object) {
  object?.traverse?.(child => {
    child.geometry?.dispose?.();
    if (Array.isArray(child.material)) {
      child.material.forEach(material => material?.dispose?.());
    } else {
      child.material?.dispose?.();
    }
  });
}

function clearDirectorGroup(group) {
  if (!group) return;
  const children = [...group.children];
  children.forEach(child => {
    group.remove(child);
    disposeDirectorObject(child);
  });
}

function directorJointUserDataFromHit(hit, key) {
  let object = hit?.object || null;
  while (object) {
    if (object.userData?.[key]) return object.userData;
    object = object.parent;
  }
  return null;
}

function directorJointPart(characterId, def) {
  const object = runtime?.directorCharacterObjects?.[characterId];
  const parts = object?.userData?.glbPose?.parts || object?.userData?.parts || {};
  return def ? parts[def.part] : null;
}

function directorJointWorldPosition(characterId, def) {
  const part = directorJointPart(characterId, def);
  return part ? directorWorldPosition(part) : null;
}

function directorJointAxisDescriptor(character, def, axis, label, controlKey = '') {
  const control = controlKey ? directorControlDef(controlKey) : null;
  const override = directorJointOverrideValue(character, def?.key || '');
  return {
    axis,
    label,
    controlKey,
    value: control ? Number(character?.boneControls?.[controlKey] ?? control.value) : Number(override[axis] || 0),
    min: control ? control.min : -DIRECTOR_JOINT_OVERRIDE_LIMIT,
    max: control ? control.max : DIRECTOR_JOINT_OVERRIDE_LIMIT,
    color: DIRECTOR_JOINT_AXIS_COLORS[axis] || '#ffffff'
  };
}

function directorJointAxisDescriptors(character, def) {
  if (!character || !def) return [];
  if (def.mode === 'torso') {
    return [directorJointAxisDescriptor(character, def, 'y', def.key === 'pelvis' ? '旋转' : '扭转', 'torsoTwist')];
  }
  if (def.mode === 'head') {
    return [directorJointAxisDescriptor(character, def, 'y', '转向', 'headYaw')];
  }
  if (def.mode === 'shoulder') {
    return def.side === 'left'
      ? [
          directorJointAxisDescriptor(character, def, 'y', '前后', 'leftShoulderSide'),
          directorJointAxisDescriptor(character, def, 'z', '外展', 'leftShoulderFront')
        ]
      : [
          directorJointAxisDescriptor(character, def, 'z', '外展', 'rightShoulderSide'),
          directorJointAxisDescriptor(character, def, 'y', '前后', 'rightShoulderFront')
        ];
  }
  if (def.mode === 'elbow') {
    return [directorJointAxisDescriptor(character, def, 'x', '弯曲', def.side === 'left' ? 'leftElbow' : 'rightElbow')];
  }
  if (def.mode === 'hip') {
    return [
      directorJointAxisDescriptor(character, def, 'z', '外展', def.side === 'left' ? 'leftHipSide' : 'rightHipSide'),
      directorJointAxisDescriptor(character, def, 'y', '前后', def.side === 'left' ? 'leftHipFront' : 'rightHipFront')
    ];
  }
  if (def.mode === 'knee') {
    return [directorJointAxisDescriptor(character, def, 'x', '弯曲', def.side === 'left' ? 'leftKnee' : 'rightKnee')];
  }
  return ['x', 'y', 'z'].map(axis => directorJointAxisDescriptor(character, def, axis, axis.toUpperCase()));
}

function directorJointAxisDescriptorByAxis(character, def, axis) {
  return directorJointAxisDescriptors(character, def).find(item => item.axis === axis) || null;
}

function directorJointAxisButtonMarkup(descriptor) {
  const progress = ((descriptor.value - descriptor.min) / Math.max(1, descriptor.max - descriptor.min)) * 100;
  return `
    <button
      type="button"
      class="desk-director-joint-axis"
      data-director-joint-axis="${descriptor.axis}"
      style="--joint-axis-color:${descriptor.color};--joint-axis-progress:${clamp(progress, 0, 100)}%"
      title="${descriptor.label}"
      aria-label="${descriptor.label} ${Math.round(descriptor.value)} 度"
      aria-pressed="false"
    >
      <span><i>${descriptor.axis.toUpperCase()}</i><strong>${descriptor.label}</strong></span>
      <em data-director-joint-axis-value="${descriptor.axis}">${Math.round(descriptor.value)}°</em>
    </button>
  `;
}

function ensureDirectorJointHud() {
  const layer = modal?.querySelector('[data-director-joint-layer]');
  if (!layer) return null;
  let root = layer.querySelector('[data-director-joint-hud]');
  if (!root) {
    root = document.createElement('div');
    root.className = 'desk-director-joint-hud';
    root.dataset.directorJointHud = '';
    root.hidden = true;
    root.innerHTML = `
      <div class="desk-director-joint-hud__card">
        <div class="desk-director-joint-hud__head">
          <strong data-director-joint-hud-label>关节</strong>
          <span data-director-joint-hud-character>角色</span>
        </div>
        <div class="desk-director-joint-hud__axes" data-director-joint-hud-axes></div>
        <div class="desk-director-joint-hud__feedback" data-director-joint-hud-feedback hidden>
          <span data-director-joint-hud-feedback-label></span>
          <strong data-director-joint-hud-feedback-value></strong>
          <em data-director-joint-hud-feedback-delta></em>
        </div>
      </div>
      <span class="desk-director-joint-hud__stem" aria-hidden="true"></span>
      <span class="desk-director-joint-hud__anchor" aria-hidden="true"></span>
    `;
    layer.appendChild(root);
  }
  if (runtime) runtime.directorJointHud = root;
  return root;
}

function updateDirectorJointHudValues() {
  const root = runtime?.directorJointHud || ensureDirectorJointHud();
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  if (!root || !selected || !def || runtime?.directorData?.editMode !== 'joint') return;
  const descriptors = directorJointAxisDescriptors(selected, def);
  descriptors.forEach(descriptor => {
    const button = root.querySelector(`[data-director-joint-axis="${descriptor.axis}"]`);
    const value = root.querySelector(`[data-director-joint-axis-value="${descriptor.axis}"]`);
    if (!button || !value) return;
    const progress = ((descriptor.value - descriptor.min) / Math.max(1, descriptor.max - descriptor.min)) * 100;
    button.style.setProperty('--joint-axis-progress', `${clamp(progress, 0, 100)}%`);
    button.style.setProperty('--joint-axis-color', descriptor.color);
    button.classList.toggle('is-active', runtime.directorJointDrag?.axis === descriptor.axis);
    button.setAttribute('aria-pressed', runtime.directorJointDrag?.axis === descriptor.axis ? 'true' : 'false');
    button.setAttribute('aria-label', `${descriptor.label} ${Math.round(descriptor.value)} 度`);
    value.textContent = `${Math.round(descriptor.value)}°`;
  });
  const feedback = root.querySelector('[data-director-joint-hud-feedback]');
  const drag = runtime.directorJointDrag;
  if (feedback && drag) {
    const current = directorJointAxisDescriptorByAxis(selected, def, drag.axis);
    feedback.hidden = false;
    feedback.style.setProperty('--joint-axis-color', drag.color);
    feedback.querySelector('[data-director-joint-hud-feedback-label]').textContent = drag.label;
    feedback.querySelector('[data-director-joint-hud-feedback-value]').textContent = `${Math.round(current?.value ?? drag.currentValue ?? drag.startValue)}°`;
    const delta = Number((current?.value ?? drag.currentValue ?? drag.startValue) - drag.startValue);
    feedback.querySelector('[data-director-joint-hud-feedback-delta]').textContent = `${delta >= 0 ? '+' : ''}${Math.round(delta)}°`;
  } else if (feedback) {
    feedback.hidden = true;
  }
  root.classList.toggle('is-dragging', !!drag);
}

function bindDirectorJointHudAxes(root) {
  root?.querySelectorAll('[data-director-joint-axis]').forEach(button => {
    button.addEventListener('pointerdown', event => {
      beginDirectorJointAxisDrag(event, {
        axis: event.currentTarget.dataset.directorJointAxis || '',
        jointKey: root.dataset.jointKey || '',
        characterId: root.dataset.characterId || ''
      });
    });
    button.addEventListener('pointermove', event => {
      updateDirectorJointAxisDrag(event);
    });
    button.addEventListener('pointerup', event => {
      endDirectorJointAxisDrag(event);
    });
    button.addEventListener('pointercancel', event => {
      endDirectorJointAxisDrag(event);
    });
    button.addEventListener('lostpointercapture', event => {
      endDirectorJointAxisDrag(event);
    });
  });
}

function syncDirectorJointHudStructure(selected, def) {
  const root = ensureDirectorJointHud();
  if (!root) return;
  if (!selected || !def || runtime?.directorData?.editMode !== 'joint') {
    root.hidden = true;
    root.dataset.signature = '';
    return;
  }
  const descriptors = directorJointAxisDescriptors(selected, def);
  const signature = `${selected.id}:${def.key}:${descriptors.map(item => `${item.axis}:${item.controlKey}`).join('|')}`;
  root.hidden = false;
  root.dataset.jointKey = def.key;
  root.dataset.characterId = selected.id;
  root.style.setProperty('--joint-role-color', selected.color || '#4F8EF7');
  root.querySelector('[data-director-joint-hud-label]').textContent = def.label;
  root.querySelector('[data-director-joint-hud-character]').textContent = selected.name;
  if (root.dataset.signature !== signature) {
    root.dataset.signature = signature;
    root.querySelector('[data-director-joint-hud-axes]').innerHTML = descriptors.map(directorJointAxisButtonMarkup).join('');
    bindDirectorJointHudAxes(root);
  }
  updateDirectorJointHudValues();
}

function updateDirectorJointHudPosition() {
  const root = runtime?.directorJointHud;
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  const stage = modal?.querySelector('[data-pose-studio-stage]');
  const canvas = runtime?.renderer?.domElement;
  const position = selected && def ? directorJointWorldPosition(selected.id, def) : null;
  if (!root || !selected || !def || !stage || !canvas || !position || runtime?.directorData?.editMode !== 'joint') {
    if (root) root.hidden = true;
    return;
  }
  const stageRect = stage.getBoundingClientRect();
  const canvasRect = canvas.getBoundingClientRect();
  const projected = position.clone().project(runtime.camera);
  if (projected.z < -1 || projected.z > 1) {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  root.style.left = `${canvasRect.left - stageRect.left + ((projected.x + 1) / 2) * canvasRect.width}px`;
  root.style.top = `${canvasRect.top - stageRect.top + ((1 - projected.y) / 2) * canvasRect.height}px`;
}

function renderDirectorJointHandles() {
  const group = runtime?.directorJointGroup;
  if (!group) return;
  clearDirectorGroup(group);
  runtime.directorJointPickables = [];
  const selected = selectedDirectorCharacter();
  if (!selected || runtime.directorData.editMode !== 'joint') {
    syncDirectorJointHudStructure(null, null);
    runtime.renderer?.render(runtime.scene, runtime.camera);
    return;
  }
  const selectedJointId = runtime.directorData.selectedJointId || '';
  const selectedDef = DIRECTOR_JOINT_DEF_BY_KEY.get(selectedJointId) || null;
  DIRECTOR_JOINT_DEFS.forEach(def => {
    const position = directorJointWorldPosition(selected.id, def);
    if (!position) return;
    const isActive = selectedJointId === def.key;
    const markerGroup = new THREE.Group();
    markerGroup.name = `joint-marker-${def.key}`;
    markerGroup.position.copy(position);
    markerGroup.userData.directorJointMarker = true;
    markerGroup.userData.characterId = selected.id;
    markerGroup.userData.jointKey = def.key;

    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(isActive ? 0.16 : 0.12, 18, 12),
      new THREE.MeshBasicMaterial({
        color: isActive ? 0xfbbf24 : 0x38bdf8,
        depthTest: false,
        depthWrite: false,
        transparent: true,
        opacity: isActive ? 0.2 : 0.08
      })
    );
    halo.name = `joint-hit-${def.key}`;
    halo.renderOrder = 1000;
    halo.userData.directorJointMarker = true;
    halo.userData.characterId = selected.id;
    halo.userData.jointKey = def.key;

    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(isActive ? 0.065 : 0.042, 18, 12),
      new THREE.MeshBasicMaterial({
        color: isActive ? 0xf59e0b : 0x38bdf8,
        depthTest: false,
        depthWrite: false,
        transparent: true,
        opacity: isActive ? 1 : 0.72
      })
    );
    marker.name = `joint-${def.key}`;
    marker.renderOrder = 1000;
    marker.userData.directorJointMarker = true;
    marker.userData.characterId = selected.id;
    marker.userData.jointKey = def.key;
    markerGroup.add(halo, marker);
    group.add(markerGroup);
    runtime.directorJointPickables.push(halo, marker);
  });
  syncDirectorJointHudStructure(selected, selectedDef);
  updateDirectorJointHudPosition();
  runtime.renderer?.render(runtime.scene, runtime.camera);
}

function ensureDirectorJointPivot() {
  if (runtime?.directorJointPivot) return runtime.directorJointPivot;
  const pivot = new THREE.Object3D();
  pivot.name = 'director-joint-pivot';
  pivot.visible = false;
  pivot.userData.directorJointPivot = true;
  runtime.scene?.add(pivot);
  runtime.directorJointPivot = pivot;
  return pivot;
}

function attachDirectorJointTransformControls() {
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  const position = selected && def ? directorJointWorldPosition(selected.id, def) : null;
  if (!runtime?.transformControls || !selected || !def || !position) {
    runtime?.transformControls?.detach?.();
    if (runtime?.transformControls) {
      runtime.transformControls.enabled = false;
      runtime.transformControls.visible = false;
    }
    return false;
  }
  const pivot = ensureDirectorJointPivot();
  pivot.position.copy(position);
  pivot.rotation.set(0, 0, 0);
  pivot.userData = {
    directorJointPivot: true,
    characterId: selected.id,
    jointKey: def.key,
    baseControls: { ...defaultPose(), ...(selected.boneControls || {}) },
    baseOverrides: { ...(selected.jointOverrides || {}) }
  };
  // Joint mode uses the anchored v3 HUD. TransformControls stays exclusive to
  // whole-character transforms so the stage never shows competing manipulators.
  runtime.transformControls.detach();
  runtime.transformControls.enabled = false;
  runtime.transformControls.visible = false;
  return true;
}

function updateSelectedDirectorCharacterPose() {
  const selected = selectedDirectorCharacter();
  const object = selected ? runtime?.directorCharacterObjects?.[selected.id] : null;
  if (!selected || !object) return;
  setDirectorCharacterPose(object, selected);
  renderDirectorJointHandles();
  const pivot = runtime?.directorJointPivot;
  const def = selectedDirectorJointDef();
  if (pivot?.userData?.directorJointPivot && def) {
    const position = directorJointWorldPosition(selected.id, def);
    if (position) pivot.position.copy(position);
  }
  runtime.renderer?.render(runtime.scene, runtime.camera);
}

function updateDirectorBoneInputs() {
  const selected = selectedDirectorCharacter();
  if (!selected || !modal) return;
  CONTROL_DEFS.forEach(def => {
    const value = selected.boneControls?.[def.key] ?? def.value;
    const input = modal.querySelector(`[data-director-bone="${def.key}"]`);
    const label = modal.querySelector(`[data-director-pose-value="${def.key}"]`);
    if (input) input.value = String(value);
    if (label) label.textContent = `${Math.round(value)}°`;
  });
}

function applyDirectorJointPivotRotation(pivot) {
  const selected = selectedDirectorCharacter();
  const def = DIRECTOR_JOINT_DEF_BY_KEY.get(pivot?.userData?.jointKey || '');
  if (!selected || !def) return;
  const baseControls = pivot.userData.baseControls || { ...defaultPose(), ...(selected.boneControls || {}) };
  const baseOverrides = pivot.userData.baseOverrides || {};
  const delta = {
    x: THREE.MathUtils.radToDeg(pivot.rotation.x || 0),
    y: THREE.MathUtils.radToDeg(pivot.rotation.y || 0),
    z: THREE.MathUtils.radToDeg(pivot.rotation.z || 0)
  };
  selected.boneControls = { ...defaultPose(), ...(selected.boneControls || {}) };
  if (def.mode === 'torso') {
    setDirectorControlValue(selected, 'torsoTwist', baseControls.torsoTwist + delta.y);
  } else if (def.mode === 'head') {
    setDirectorControlValue(selected, 'headYaw', baseControls.headYaw + delta.y);
  } else if (def.mode === 'shoulder') {
    if (def.side === 'left') {
      setDirectorControlValue(selected, 'leftShoulderSide', baseControls.leftShoulderSide + delta.y);
      setDirectorControlValue(selected, 'leftShoulderFront', baseControls.leftShoulderFront + delta.z);
    } else {
      setDirectorControlValue(selected, 'rightShoulderSide', baseControls.rightShoulderSide + delta.z);
      setDirectorControlValue(selected, 'rightShoulderFront', baseControls.rightShoulderFront + delta.y);
    }
  } else if (def.mode === 'elbow') {
    setDirectorControlValue(selected, def.side === 'left' ? 'leftElbow' : 'rightElbow', baseControls[def.side === 'left' ? 'leftElbow' : 'rightElbow'] + delta.x);
  } else if (def.mode === 'hip') {
    const sideKey = def.side === 'left' ? 'leftHipSide' : 'rightHipSide';
    const frontKey = def.side === 'left' ? 'leftHipFront' : 'rightHipFront';
    setDirectorControlValue(selected, sideKey, baseControls[sideKey] + delta.z);
    setDirectorControlValue(selected, frontKey, baseControls[frontKey] + delta.y);
  } else if (def.mode === 'knee') {
    const key = def.side === 'left' ? 'leftKnee' : 'rightKnee';
    setDirectorControlValue(selected, key, baseControls[key] + delta.x);
  } else {
    const base = normalizeJointOverride(baseOverrides[def.key] || {});
    setDirectorJointOverride(selected, def.key, {
      x: base.x + delta.x,
      y: base.y + delta.y,
      z: base.z + delta.z
    });
  }
  selected.posePreset = 'custom';
  updateSelectedDirectorCharacterPose();
  updateDirectorBoneInputs();
  persistDirectorData();
}

function beginDirectorJointAxisDrag(event, axisData) {
  const jointKey = axisData?.jointKey || '';
  const axis = axisData?.axis || '';
  if (!runtime?.directorData || !DIRECTOR_JOINT_DEF_BY_KEY.has(jointKey) || !['x', 'y', 'z'].includes(axis)) return false;
  event.preventDefault?.();
  event.stopPropagation?.();
  if (axisData.characterId && runtime.directorData.characters?.some(character => character.id === axisData.characterId)) {
    runtime.directorData.selectedId = axisData.characterId;
  }
  if (runtime.directorData.selectedJointId !== jointKey || runtime.directorData.editMode !== 'joint') {
    selectDirectorJoint(jointKey);
  } else {
    attachDirectorJointTransformControls();
  }
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  const descriptor = directorJointAxisDescriptorByAxis(selected, def, axis);
  const pivot = runtime?.directorJointPivot;
  if (!selected || !descriptor || !pivot?.userData?.directorJointPivot) return false;
  pivot.rotation.set(0, 0, 0);
  pivot.userData.baseControls = { ...defaultPose(), ...(selected.boneControls || {}) };
  pivot.userData.baseOverrides = { ...(selected.jointOverrides || {}) };
  runtime.directorJointDrag = {
    pointerId: event.pointerId ?? 1,
    source: event.currentTarget || null,
    startX: event.clientX || 0,
    startY: event.clientY || 0,
    axis,
    label: descriptor.label,
    color: descriptor.color,
    jointKey,
    characterId: selected.id,
    startValue: descriptor.value,
    currentValue: descriptor.value,
    currentDelta: 0,
    min: descriptor.min,
    max: descriptor.max,
    baseControls: { ...pivot.userData.baseControls },
    baseOverrides: { ...pivot.userData.baseOverrides }
  };
  if (runtime.controls) runtime.controls.enabled = false;
  document.body.classList.add('is-director-joint-dragging');
  try {
    event.currentTarget?.setPointerCapture?.(event.pointerId);
  } catch (_) {
    // Pointer capture is best-effort; the drag state still protects OrbitControls.
  }
  updateDirectorJointHudValues();
  return true;
}

function updateDirectorJointAxisDrag(event) {
  const drag = runtime?.directorJointDrag;
  if (!drag || (event.pointerId ?? 1) !== drag.pointerId) return false;
  event.preventDefault?.();
  event.stopPropagation?.();
  const selected = selectedDirectorCharacter();
  const pivot = runtime?.directorJointPivot;
  if (!selected || !pivot?.userData?.directorJointPivot) return false;
  const precision = event.shiftKey ? DIRECTOR_JOINT_HUD_FINE_SCALE : 1;
  const travel = (drag.startY - (event.clientY || 0)) * precision;
  const value = clamp(
    drag.startValue + travel * ((drag.max - drag.min) / DIRECTOR_JOINT_HUD_DRAG_PIXELS),
    drag.min,
    drag.max
  );
  const delta = value - drag.startValue;
  drag.currentValue = value;
  drag.currentDelta = delta;
  pivot.userData.baseControls = { ...drag.baseControls };
  pivot.userData.baseOverrides = { ...drag.baseOverrides };
  pivot.rotation.set(0, 0, 0);
  pivot.rotation[drag.axis] = degToRad(delta);
  applyDirectorJointPivotRotation(pivot);
  updateDirectorJointHudValues();
  return true;
}

function endDirectorJointAxisDrag(event) {
  const drag = runtime?.directorJointDrag;
  if (!drag || (event?.pointerId ?? drag.pointerId) !== drag.pointerId) return false;
  event?.preventDefault?.();
  event?.stopPropagation?.();
  const pivot = runtime?.directorJointPivot;
  pivot?.rotation?.set?.(0, 0, 0);
  runtime.directorJointDrag = null;
  if (runtime.controls) runtime.controls.enabled = true;
  document.body.classList.remove('is-director-joint-dragging');
  try {
    drag.source?.releasePointerCapture?.(drag.pointerId);
  } catch (_) {
    // Pointer capture may not have been acquired.
  }
  attachDirectorJointTransformControls();
  updateDirectorJointHudValues();
  persistDirectorData();
  return true;
}

function directorGroupLocalDirection(group, fromObject, toObject) {
  if (!group || !fromObject || !toObject) return null;
  group.updateMatrixWorld(true);
  const from = directorWorldPosition(fromObject);
  const to = directorWorldPosition(toObject);
  const direction = to.sub(from);
  if (direction.lengthSq() < 0.000001) return null;
  const groupQuaternion = new THREE.Quaternion();
  group.getWorldQuaternion(groupQuaternion);
  return direction.applyQuaternion(groupQuaternion.invert()).normalize();
}

function directorTargetDirection(pair, poseSkeleton) {
  const chain = poseSkeleton?.[pair.chain];
  const from = chain?.[pair.from];
  const to = chain?.[pair.to];
  if (!from || !to) return null;
  const direction = to.clone().sub(from);
  return direction.lengthSq() > 0.000001 ? direction.normalize() : null;
}

function setDirectorBoneDirection(group, key, childKey, targetDirectionGroupLocal) {
  const poseMeta = group?.userData?.glbPose;
  const bone = poseMeta?.parts?.[key];
  const child = poseMeta?.parts?.[childKey];
  if (!group || !bone?.isBone || !child || !targetDirectionGroupLocal || targetDirectionGroupLocal.lengthSq() < 0.000001) {
    return false;
  }
  group.updateMatrixWorld(true);
  const bonePosition = directorWorldPosition(bone);
  const childPosition = directorWorldPosition(child);
  const currentWorldDirection = childPosition.sub(bonePosition);
  if (currentWorldDirection.lengthSq() < 0.000001) return false;

  const groupWorldQuaternion = new THREE.Quaternion();
  group.getWorldQuaternion(groupWorldQuaternion);
  const targetWorldDirection = targetDirectionGroupLocal.clone().normalize().applyQuaternion(groupWorldQuaternion);
  const delta = new THREE.Quaternion().setFromUnitVectors(
    currentWorldDirection.normalize(),
    targetWorldDirection.normalize()
  );
  const currentWorldQuaternion = new THREE.Quaternion();
  bone.getWorldQuaternion(currentWorldQuaternion);
  const nextWorldQuaternion = delta.multiply(currentWorldQuaternion);
  const parentWorldQuaternion = new THREE.Quaternion();
  bone.parent?.getWorldQuaternion?.(parentWorldQuaternion);
  bone.quaternion.copy(parentWorldQuaternion.invert().multiply(nextWorldQuaternion));
  bone.updateMatrixWorld(true);
  return true;
}

function applyDirectorLimbDirections(group, poseSkeleton) {
  let applied = false;
  DIRECTOR_LIMB_DIRECTION_PAIRS.forEach(pair => {
    const targetDirection = directorTargetDirection(pair, poseSkeleton);
    applied = setDirectorBoneDirection(group, pair.key, pair.child, targetDirection) || applied;
  });
  return applied;
}

function applyDirectorBonePose(group, character) {
  const poseMeta = group?.userData?.glbPose;
  if (!poseMeta || poseMeta.rigMode !== 'bones') return false;
  const pose = { ...defaultPose(), ...(character.boneControls || {}) };
  const poseSkeleton = buildPoseSkeleton(pose);
  Object.entries(poseMeta.parts || {}).forEach(([key, part]) => {
    if (!part?.isBone) return;
    const rest = poseMeta.restQuaternions?.[key];
    if (rest) part.quaternion.copy(rest);
  });
  const torsoTwist = degToRad(pose.torsoTwist || 0);
  const headYaw = degToRad(pose.headYaw || 0);
  setDirectorBonePoseRotation(group, 'pelvis', { y: torsoTwist * 0.18 });
  setDirectorBonePoseRotation(group, 'spine', { y: torsoTwist * 0.42 });
  setDirectorBonePoseRotation(group, 'chest', { y: torsoTwist * 0.4 });
  setDirectorBonePoseRotation(group, 'neckJoint', { y: headYaw * 0.4 });
  setDirectorBonePoseRotation(group, 'head', { y: headYaw * 0.6 });
  group.updateMatrixWorld(true);
  applyDirectorLimbDirections(group, poseSkeleton);
  applyDirectorJointOverrides(group, character);
  group.traverse(child => {
    if (child.isSkinnedMesh) child.skeleton?.update?.();
  });
  group.updateMatrixWorld(true);
  return true;
}

function setDirectorCharacterPose(group, character) {
  const parts = group?.userData?.parts;
  if (!parts) return;
  if (applyDirectorBonePose(group, character)) return;
  Object.values(parts).forEach(part => {
    part?.rotation?.set?.(0, 0, 0);
  });
  const skeleton = buildPoseSkeleton(character.boneControls || defaultPose());
  const { points, leftArm, rightArm, leftLeg, rightLeg } = skeleton;
  const leftToeBase = leftLeg.ankle.clone().add(new THREE.Vector3(0.06, 0, 0.24));
  const rightToeBase = rightLeg.ankle.clone().add(new THREE.Vector3(-0.06, 0, 0.24));
  setSegment(parts.spine, points.pelvis, points.chest, 0.12);
  setSegment(parts.neckSegment || parts.neck, points.chest, points.neck, 0.075);
  setSegment(parts.leftUpperArm, leftArm.shoulder, leftArm.elbow, 0.065);
  setSegment(parts.leftLowerArm, leftArm.elbow, leftArm.hand, 0.055);
  setSegment(parts.rightUpperArm, rightArm.shoulder, rightArm.elbow, 0.065);
  setSegment(parts.rightLowerArm, rightArm.elbow, rightArm.hand, 0.055);
  setSegment(parts.leftUpperLeg, leftLeg.hip, leftLeg.knee, 0.08);
  setSegment(parts.leftLowerLeg, leftLeg.knee, leftLeg.ankle, 0.065);
  setSegment(parts.rightUpperLeg, rightLeg.hip, rightLeg.knee, 0.08);
  setSegment(parts.rightLowerLeg, rightLeg.knee, rightLeg.ankle, 0.065);
  Object.entries({
    pelvis: points.pelvis,
    chest: points.chest,
    neckJoint: points.neck,
    neck: points.neck,
    head: points.head,
    leftShoulder: leftArm.shoulder,
    leftElbow: leftArm.elbow,
    leftHand: leftArm.hand,
    rightShoulder: rightArm.shoulder,
    rightElbow: rightArm.elbow,
    rightHand: rightArm.hand,
    leftHip: leftLeg.hip,
    leftKnee: leftLeg.knee,
    leftAnkle: leftLeg.ankle,
    leftToeBase,
    rightHip: rightLeg.hip,
    rightKnee: rightLeg.knee,
    rightAnkle: rightLeg.ankle,
    rightToeBase
  }).forEach(([name, point]) => {
    if (parts[name]) parts[name].position.copy(point);
  });
  applyDirectorJointOverrides(group, character);
}

function renderDirectorCharacters() {
  if (!runtime?.directorGroup) return;
  runtime.transformControls?.detach?.();
  runtime.directorGroup.clear();
  runtime.directorPickables = [];
  runtime.directorCharacterObjects = {};
  (runtime.directorData.characters || []).forEach(character => {
    const group = createDirectorCharacterGroup(character);
    setDirectorCharacterPose(group, character);
    runtime.directorGroup.add(group);
    runtime.directorCharacterObjects[character.id] = group;
    group.traverse(child => {
      if (child.isMesh) runtime.directorPickables.push(child);
    });
  });
  renderDirectorJointHandles();
  attachDirectorTransformControls();
  runtime.renderer?.render(runtime.scene, runtime.camera);
}

function attachDirectorTransformControls() {
  if (runtime?.directorData?.editMode === 'joint') {
    attachDirectorJointTransformControls();
    return;
  }
  const selected = selectedDirectorCharacter();
  const object = selected ? runtime?.directorCharacterObjects?.[selected.id] : null;
  if (!runtime?.transformControls || !object) return;
  runtime.transformControls.enabled = true;
  runtime.transformControls.visible = true;
  runtime.transformControls.showX = true;
  runtime.transformControls.showY = true;
  runtime.transformControls.showZ = true;
  runtime.transformControls.setSize?.(1);
  runtime.transformControls.attach(object);
  runtime.transformControls.setMode(runtime.directorData.transformMode || 'translate');
  runtime.transformControls.setSpace('world');
}

function directorAssetSummary() {
  const objects = runtime?.directorCharacterObjects || {};
  const characters = runtime?.directorData?.characters || [];
  const summaries = characters.map(character => {
    const object = objects[character.id];
    const glbPose = object?.userData?.glbPose || null;
    return {
      id: character.id,
      name: character.name,
      modelKey: character.modelKey || 'procedural_mannequin',
      assetMode: object?.userData?.assetMode || 'unknown',
      rigMode: glbPose?.rigMode || (object?.userData?.assetMode === 'glb' ? 'parts' : 'procedural'),
      boneCount: glbPose?.boneCount || 0,
      skinnedMeshCount: glbPose?.skinnedMeshCount || 0,
      matchedKeys: glbPose?.matchedKeys || []
    };
  });
  const modes = Array.from(new Set(summaries.map(item => item.assetMode))).filter(Boolean);
  return {
    assetMode: modes.length === 1 ? modes[0] : (modes.length ? 'mixed' : 'unknown'),
    characters: summaries
  };
}

function vectorSnapshot(vector) {
  if (!vector) return null;
  return [
    Number(vector.x.toFixed(4)),
    Number(vector.y.toFixed(4)),
    Number(vector.z.toFixed(4))
  ];
}

function directorLimbDirectionSnapshot(characterId) {
  const object = runtime?.directorCharacterObjects?.[characterId];
  const poseMeta = object?.userData?.glbPose;
  const parts = poseMeta?.parts || {};
  const directions = {};
  DIRECTOR_LIMB_DIRECTION_PAIRS.forEach(pair => {
    const direction = directorGroupLocalDirection(object, parts[pair.key], parts[pair.child]);
    directions[pair.key] = vectorSnapshot(direction);
  });
  return directions;
}

function directorPartPointSnapshot(characterId) {
  const object = runtime?.directorCharacterObjects?.[characterId];
  const poseMeta = object?.userData?.glbPose;
  const parts = poseMeta?.parts || object?.userData?.parts || {};
  const points = {};
  if (!object) return points;
  object.updateMatrixWorld(true);
  Object.entries({
    leftShoulder: 'leftUpperArm',
    leftElbow: 'leftLowerArm',
    leftHand: 'leftHand',
    rightShoulder: 'rightUpperArm',
    rightElbow: 'rightLowerArm',
    rightHand: 'rightHand',
    leftHip: 'leftUpperLeg',
    leftKnee: 'leftLowerLeg',
    leftAnkle: 'leftAnkle',
    rightHip: 'rightUpperLeg',
    rightKnee: 'rightLowerLeg',
    rightAnkle: 'rightAnkle'
  }).forEach(([key, partKey]) => {
    const part = parts[key] || parts[partKey];
    if (!part) return;
    const world = directorWorldPosition(part);
    points[key] = vectorSnapshot(object.worldToLocal(world.clone()));
  });
  return points;
}

function directorMeshBoundsSnapshot(characterId) {
  const object = runtime?.directorCharacterObjects?.[characterId];
  if (!object) return null;
  object.updateMatrixWorld(true);
  const worldBox = new THREE.Box3().setFromObject(object);
  if (worldBox.isEmpty()) return null;
  const localBox = new THREE.Box3();
  [
    [worldBox.min.x, worldBox.min.y, worldBox.min.z],
    [worldBox.min.x, worldBox.min.y, worldBox.max.z],
    [worldBox.min.x, worldBox.max.y, worldBox.min.z],
    [worldBox.min.x, worldBox.max.y, worldBox.max.z],
    [worldBox.max.x, worldBox.min.y, worldBox.min.z],
    [worldBox.max.x, worldBox.min.y, worldBox.max.z],
    [worldBox.max.x, worldBox.max.y, worldBox.min.z],
    [worldBox.max.x, worldBox.max.y, worldBox.max.z]
  ].forEach(coords => {
    localBox.expandByPoint(object.worldToLocal(new THREE.Vector3(...coords)));
  });
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  localBox.getSize(size);
  localBox.getCenter(center);
  return {
    min: vectorSnapshot(localBox.min),
    max: vectorSnapshot(localBox.max),
    size: vectorSnapshot(size),
    center: vectorSnapshot(center)
  };
}

function debugSnapshot() {
  if (!runtime) return null;
  const characters = runtime.directorData?.characters || [];
  return {
    mode: runtime.mode,
    selectedId: runtime.directorData?.selectedId || '',
    editMode: runtime.directorData?.editMode || 'character',
    selectedJointId: runtime.directorData?.selectedJointId || '',
    selectedJointLabel: selectedDirectorJointDef()?.label || '',
    selectedJointAxes: directorJointAxes(selectedDirectorJointDef()),
    jointInteractionVersion: 3,
    jointHandleCount: runtime.directorJointPickables?.length || 0,
    jointAxisHandleCount: runtime.directorJointHud?.querySelectorAll?.('[data-director-joint-axis]')?.length || 0,
    jointHudVisible: !!runtime.directorJointHud && !runtime.directorJointHud.hidden,
    jointDragActive: !!runtime.directorJointDrag,
    jointDragAxis: runtime.directorJointDrag?.axis || '',
    jointDragValue: runtime.directorJointDrag?.currentValue ?? null,
    jointDragDelta: runtime.directorJointDrag?.currentDelta ?? null,
    transformControlsAttached: !!runtime.transformControls?.object,
    transformControlsEnabled: runtime.transformControls?.enabled !== false,
    transformControlsVisible: runtime.transformControls?.visible !== false,
    assetSummary: runtime.mode === 'director_stage' ? directorAssetSummary() : null,
    characters: characters.map(character => ({
      id: character.id,
      name: character.name,
      modelKey: character.modelKey,
      posePreset: character.posePreset,
      boneControls: { ...(character.boneControls || {}) },
      jointOverrides: { ...(character.jointOverrides || {}) },
      limbDirections: directorLimbDirectionSnapshot(character.id),
      limbPoints: directorPartPointSnapshot(character.id),
      meshBounds: directorMeshBoundsSnapshot(character.id)
    }))
  };
}

function debugSelectJoint(characterId, jointKey) {
  if (!runtime?.directorData || !DIRECTOR_JOINT_DEF_BY_KEY.has(jointKey)) return debugSnapshot();
  if (characterId && runtime.directorData.characters?.some(character => character.id === characterId)) {
    runtime.directorData.selectedId = characterId;
  }
  selectDirectorJoint(jointKey);
  return debugSnapshot();
}

function debugApplyJointRotation(characterId, jointKey, rotation = {}) {
  debugSelectJoint(characterId, jointKey);
  const pivot = runtime?.directorJointPivot;
  if (!pivot?.userData?.directorJointPivot) return debugSnapshot();
  pivot.rotation.set(
    degToRad(rotation.x || 0),
    degToRad(rotation.y || 0),
    degToRad(rotation.z || 0)
  );
  applyDirectorJointPivotRotation(pivot);
  return debugSnapshot();
}

function debugApplyJointAxisDelta(characterId, jointKey, axis = 'x', delta = 0) {
  debugSelectJoint(characterId, jointKey);
  const pivot = runtime?.directorJointPivot;
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  if (!pivot?.userData?.directorJointPivot || !selected || !directorJointAxes(def).includes(axis)) return debugSnapshot();
  pivot.userData.baseControls = { ...defaultPose(), ...(selected.boneControls || {}) };
  pivot.userData.baseOverrides = { ...(selected.jointOverrides || {}) };
  pivot.rotation.set(0, 0, 0);
  pivot.rotation[axis] = degToRad(clamp(Number(delta) || 0, -DIRECTOR_JOINT_OVERRIDE_LIMIT, DIRECTOR_JOINT_OVERRIDE_LIMIT));
  applyDirectorJointPivotRotation(pivot);
  pivot.rotation.set(0, 0, 0);
  return debugSnapshot();
}

function debugSelectedJointScreenTarget() {
  const selected = selectedDirectorCharacter();
  const def = selectedDirectorJointDef();
  const position = selected && def ? directorJointWorldPosition(selected.id, def) : null;
  const canvas = runtime?.renderer?.domElement;
  if (!position || !canvas || !runtime?.camera) return null;
  const rect = canvas.getBoundingClientRect();
  const projected = position.clone().project(runtime.camera);
  return {
    x: rect.left + ((projected.x + 1) / 2) * rect.width,
    y: rect.top + ((1 - projected.y) / 2) * rect.height,
    jointKey: def.key,
    axes: directorJointAxes(def),
    rect: {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height
    }
  };
}

function debugSelectedJointAxisTarget(axis = '') {
  const def = selectedDirectorJointDef();
  const selectedAxis = directorJointAxes(def).includes(axis) ? axis : directorJointAxes(def)[0];
  updateDirectorJointHudPosition();
  const button = runtime?.directorJointHud?.querySelector?.(`[data-director-joint-axis="${selectedAxis}"]`);
  const selected = selectedDirectorCharacter();
  const descriptor = directorJointAxisDescriptorByAxis(selected, def, selectedAxis);
  if (!button || !descriptor) return null;
  const rect = button.getBoundingClientRect();
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    jointKey: def?.key || '',
    axis: selectedAxis,
    label: descriptor.label,
    value: descriptor.value,
    rect: {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height
    }
  };
}

function applyDirectorViewMode() {
  if (!runtime?.camera || !runtime?.controls) return;
  const cameraData = activeDirectorCamera() || directorDefaultCamera(0);
  if (runtime.directorData.viewMode === 'camera') {
    runtime.camera.position.fromArray(cameraData.position);
    runtime.controls.target.fromArray(cameraData.target);
    runtime.camera.fov = cameraData.fov || 45;
    runtime.camera.updateProjectionMatrix();
  }
  runtime.controls.update();
  runtime.renderer?.render(runtime.scene, runtime.camera);
}

function directorAssetBoneBox(scene) {
  const box = new THREE.Box3();
  const point = new THREE.Vector3();
  let count = 0;
  scene?.updateMatrixWorld?.(true);
  scene?.traverse?.(child => {
    if (!child.isBone) return;
    child.getWorldPosition(point);
    box.expandByPoint(point);
    count += 1;
  });
  return count ? box : null;
}

function loadDirectorAsset(url) {
  return new Promise(resolve => {
    const loader = new GLTFLoader();
    loader.load(
      url,
      gltf => {
        const scene = gltf?.scene || null;
        if (!scene) {
          resolve(null);
          return;
        }
        scene.updateMatrixWorld(true);
        const meshBox = new THREE.Box3().setFromObject(scene);
        const boneBox = directorAssetBoneBox(scene);
        const box = boneBox && !boneBox.isEmpty() ? boneBox : meshBox;
        const size = new THREE.Vector3();
        const center = new THREE.Vector3();
        box.getSize(size);
        box.getCenter(center);
        const height = Math.max(size.y, 0.001);
        const scale = 2.72 / height;
        scene.scale.setScalar(scale);
        scene.position.set(
          -center.x * scale,
          -box.min.y * scale,
          -center.z * scale
        );
        scene.updateMatrixWorld(true);
        resolve(scene);
      },
      undefined,
      () => resolve(null)
    );
  });
}

async function loadDirectorAssets() {
  if (!runtime || runtime.directorAssets?.loading || runtime.directorAssets?.loaded) return;
  if (!runtime.assetsStatus && window.DesktopApi?.getPoseAssetsStatus) {
    try {
      runtime.assetsStatus = await window.DesktopApi.getPoseAssetsStatus();
    } catch (_) {
      runtime.assetsStatus = null;
    }
  }
  const mannequinStatus = runtime.assetsStatus?.directorStage?.mannequinAssets || null;
  if (mannequinStatus && mannequinStatus.available === false) {
    runtime.directorAssets = { loaded: true, loading: false, templates: {}, skipped: 'no_glb_assets' };
    const label = modal?.querySelector('[data-pose-studio-background-label]');
    if (label && !runtime.backgroundUrl) {
      label.textContent = '姿态参考使用程序化低模人偶；放入 xbot.glb 后会自动优先加载。';
    }
    return;
  }
  runtime.directorAssets = { ...(runtime.directorAssets || {}), loading: true, templates: {} };
  const entries = await Promise.all(Object.entries(DIRECTOR_MANNEQUIN_ASSETS).map(async ([key, url]) => {
    const template = await loadDirectorAsset(url);
    return [key, template];
  }));
  if (!runtime) return;
  entries.forEach(([key, template]) => {
    if (template) runtime.directorAssets.templates[key] = template;
  });
  runtime.directorAssets.loading = false;
  runtime.directorAssets.loaded = true;
  const hasGlb = Object.keys(runtime.directorAssets.templates).length > 0;
  const label = modal?.querySelector('[data-pose-studio-background-label]');
  if (label && !runtime.backgroundUrl) {
    label.textContent = hasGlb
      ? '姿态参考已加载 GLB 低模人偶，可继续用变换工具调整角色。'
      : '姿态参考使用程序化低模人偶；放入 xbot.glb 后会自动优先加载。';
  }
  if (hasGlb) renderDirectorCharacters();
}

function buildDirectorScene(stage) {
  const canvasHost = modal.querySelector('[data-pose-studio-canvas]');
  canvasHost.innerHTML = '';
  const jointLayer = modal.querySelector('[data-director-joint-layer]');
  if (jointLayer) jointLayer.innerHTML = '';
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111827);
  scene.fog = new THREE.Fog(0x111827, 8, 20);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 2.1, 5.4);
  const renderer = new THREE.WebGLRenderer({ alpha: false, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  canvasHost.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 1.45, 0);
  controls.enableDamping = true;
  controls.minDistance = 2.4;
  controls.maxDistance = 12;

  scene.add(new THREE.HemisphereLight(0xcfe8ff, 0x1f2937, 2.2));
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.7);
  keyLight.position.set(3.2, 5.4, 4.2);
  keyLight.castShadow = true;
  scene.add(keyLight);

  const grid = new THREE.GridHelper(8, 32, 0x6b7280, 0x374151);
  grid.position.y = 0;
  scene.add(grid);
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(8, 8),
    new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.9, metalness: 0.02 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.01;
  floor.receiveShadow = true;
  scene.add(floor);

  const directorGroup = new THREE.Group();
  directorGroup.name = 'director-stage-characters';
  scene.add(directorGroup);
  const directorJointGroup = new THREE.Group();
  directorJointGroup.name = 'director-stage-joints';
  scene.add(directorJointGroup);
  const transformControls = new TransformControls(camera, renderer.domElement);
  transformControls.setMode(runtime.directorData.transformMode || 'translate');
  transformControls.setSpace('world');
  transformControls.addEventListener('dragging-changed', event => {
    controls.enabled = !event.value;
  });
  transformControls.addEventListener('objectChange', () => {
    const selected = selectedDirectorCharacter();
    const object = transformControls.object;
    if (!selected || !object) return;
    if (object.userData?.directorJointPivot) {
      applyDirectorJointPivotRotation(object);
      return;
    }
    updateDirectorCharacterFromObject(selected, object);
    updateDirectorPropertyInputs();
    persistDirectorData();
  });
  scene.add(transformControls);

  function resize() {
    const rect = stage.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width));
    const height = Math.max(320, Math.floor(rect.height));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    updateDirectorJointHudPosition();
  }

  runtime.scene = scene;
  runtime.camera = camera;
  runtime.renderer = renderer;
  runtime.controls = controls;
  runtime.directorGroup = directorGroup;
  runtime.directorJointGroup = directorJointGroup;
  runtime.directorJointPickables = [];
  runtime.directorJointHud = null;
  runtime.directorJointDrag = null;
  runtime.transformControls = transformControls;
  runtime.resize = resize;
  runtime.raycaster = new THREE.Raycaster();
  runtime.pointer = new THREE.Vector2();
  function updateDirectorRaycasterFromPointer(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    runtime.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    runtime.pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    runtime.raycaster.setFromCamera(runtime.pointer, camera);
  }
  renderer.domElement.addEventListener('pointerdown', event => {
    updateDirectorRaycasterFromPointer(event);
    const jointHit = runtime.raycaster.intersectObjects(runtime.directorJointPickables || [], true)[0];
    const jointData = directorJointUserDataFromHit(jointHit, 'directorJointMarker');
    if (jointData) {
      runtime.directorData.selectedId = jointData.characterId || runtime.directorData.selectedId;
      selectDirectorJoint(jointData.jointKey || '');
      return;
    }
    const hit = runtime.raycaster.intersectObjects(runtime.directorPickables || [], true)[0];
    const characterId = hit?.object?.userData?.characterId || '';
    if (runtime.directorData.editMode === 'joint') {
      if (characterId) {
        runtime.directorData.selectedId = characterId;
        if (!runtime.directorData.selectedJointId) {
          runtime.directorData.selectedJointId = DIRECTOR_JOINT_DEFS[0]?.key || '';
        }
        renderDirectorJointHandles();
        attachDirectorTransformControls();
        syncDirectorControls();
        persistDirectorData();
      }
      return;
    }
    if (characterId) {
      runtime.directorData.selectedId = characterId;
      runtime.directorData.editMode = 'character';
      runtime.directorData.selectedJointId = '';
      renderDirectorCharacters();
      syncDirectorControls();
      persistDirectorData();
    }
  });

  resize();
  renderDirectorCharacters();
  applyDirectorViewMode();
  loadDirectorAssets().catch(() => {});

  const label = modal?.querySelector('[data-pose-studio-background-label]');
  if (label && !runtime.backgroundUrl) {
    label.textContent = '姿态参考已就绪：低模代理人偶 / 深色网格舞台';
  }

  function tick() {
    if (!runtime || runtime.renderer !== renderer) return;
    controls.update();
    renderer.render(scene, camera);
    updateDirectorJointHudPosition();
    runtime.frame = requestAnimationFrame(tick);
  }
  tick();
}

function buildScene(stage) {
  if (runtime?.mode === 'director_stage') {
    buildDirectorScene(stage);
    return;
  }
  const canvasHost = modal.querySelector('[data-pose-studio-canvas]');
  canvasHost.innerHTML = '';
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 2.35, 5.8);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  canvasHost.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 2.05, 0);
  controls.enableDamping = true;
  controls.minDistance = 3.6;
  controls.maxDistance = 8.5;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8fa3bb, 2.4));
  const light = new THREE.DirectionalLight(0xffffff, 2.8);
  light.position.set(2.5, 5, 3.5);
  light.castShadow = true;
  scene.add(light);

  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(1.7, 64),
    new THREE.MeshStandardMaterial({ color: 0xdde7f2, roughness: 0.72, metalness: 0.02, transparent: true, opacity: 0.56 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = 0.48;
  floor.receiveShadow = true;
  scene.add(floor);

  const rigGroup = new THREE.Group();
  rigGroup.name = 'pose-control-rig';
  scene.add(rigGroup);
  const color = 0x39c7b0;
  const accent = 0xf2b544;
  const parts = {
    spine: createSegment(rigGroup, 'spine', 0.1, color),
    neck: createSegment(rigGroup, 'neck', 0.07, color),
    leftUpperArm: createSegment(rigGroup, 'leftUpperArm', 0.06, color),
    leftLowerArm: createSegment(rigGroup, 'leftLowerArm', 0.05, color),
    rightUpperArm: createSegment(rigGroup, 'rightUpperArm', 0.06, color),
    rightLowerArm: createSegment(rigGroup, 'rightLowerArm', 0.05, color),
    leftUpperLeg: createSegment(rigGroup, 'leftUpperLeg', 0.07, color),
    leftLowerLeg: createSegment(rigGroup, 'leftLowerLeg', 0.06, color),
    rightUpperLeg: createSegment(rigGroup, 'rightUpperLeg', 0.07, color),
    rightLowerLeg: createSegment(rigGroup, 'rightLowerLeg', 0.06, color)
  };
  ['pelvis', 'chest', 'neck', 'head', 'leftShoulder', 'leftElbow', 'leftHand', 'rightShoulder', 'rightElbow', 'rightHand', 'leftHip', 'leftKnee', 'leftAnkle', 'leftToeBase', 'rightHip', 'rightKnee', 'rightAnkle', 'rightToeBase'].forEach(name => {
    parts[name] = createJoint(rigGroup, name, name === 'head' ? 0.082 : 0.045, name === 'head' ? color : accent);
  });

  function resize() {
    const rect = stage.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width));
    const height = Math.max(320, Math.floor(rect.height));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
  }

  runtime.scene = scene;
  runtime.camera = camera;
  runtime.renderer = renderer;
  runtime.controls = controls;
  runtime.parts = parts;
  runtime.partsGroup = rigGroup;
  runtime.resize = resize;
  resize();
  updateMannequin();

  function tick() {
    if (!runtime || runtime.renderer !== renderer) return;
    controls.update();
    renderer.render(scene, camera);
    runtime.frame = requestAnimationFrame(tick);
  }
  tick();
}

function applyBackground(images) {
  const background = modal.querySelector('[data-pose-studio-background]');
  const label = modal.querySelector('[data-pose-studio-background-label]');
  const reference = firstBackgroundReference(images || []);
  const url = getBackgroundUrl(images);
  runtime.backgroundUrl = url;
  if (background && url) {
    background.src = url;
    background.hidden = false;
  } else if (background) {
    background.removeAttribute('src');
    background.hidden = true;
  }
  if (label) {
    const meta = reference?.meta || {};
    if (!url) {
      label.textContent = '未接入背景图';
    } else if (reference?.source === 'pose-upload' && meta.width && meta.height) {
      const size = meta.storedBytes ? ` / ${Math.round(meta.storedBytes / 1024)}KB` : '';
      label.textContent = `已上传背景：${meta.width}×${meta.height}${size}，导出时可合成`;
    } else {
      label.textContent = '已接入背景图，导出时可选择是否合成';
    }
  }
  updateBackgroundControls();
}

function updateBackgroundControls() {
  const clearButton = modal?.querySelector('[data-pose-studio-clear-background]');
  if (!clearButton) return;
  clearButton.disabled = !(runtime?.node?.backgroundImage);
}

async function handleBackgroundUpload(event) {
  const input = event?.target;
  const file = input?.files?.[0];
  if (input) input.value = '';
  if (!file) return;
  if (!String(file.type || '').startsWith('image/')) {
    throw new Error('请选择图片文件作为背景。');
  }
  if (!runtime) return;
  const { imageData, meta } = await fileToPoseBackground(file);
  const uploaded = {
    imageData,
    title: file.name || '上传背景图',
    source: 'pose-upload',
    sourceNodeId: '',
    meta
  };
  runtime.backgroundImages = [
    uploaded,
    ...(runtime.backgroundImages || []).filter(image => image?.source !== 'pose-upload')
  ];
  if (runtime.node) {
    runtime.node.backgroundImage = imageData;
    runtime.node.backgroundName = uploaded.title;
    runtime.node.backgroundSource = uploaded.source;
    runtime.node.backgroundSourceNodeId = '';
    runtime.node.backgroundMeta = meta;
  }
  runtime.onUpdate?.({
    backgroundImage: imageData,
    backgroundName: uploaded.title,
    backgroundSource: uploaded.source,
    backgroundSourceNodeId: '',
    backgroundMeta: meta
  });
  applyBackground(runtime.backgroundImages);
  window.DesktopState?.saveSettings?.();
}

function clearUploadedBackground() {
  if (!runtime) return;
  runtime.backgroundImages = (runtime.backgroundImages || []).filter(image => image?.source !== 'pose-upload');
  if (runtime.node) {
    runtime.node.backgroundImage = '';
    runtime.node.backgroundName = '';
    runtime.node.backgroundSource = '';
    runtime.node.backgroundSourceNodeId = '';
    runtime.node.backgroundMeta = null;
  }
  runtime.onUpdate?.({
    backgroundImage: '',
    backgroundName: '',
    backgroundSource: '',
    backgroundSourceNodeId: '',
    backgroundMeta: null
  });
  applyBackground(runtime.backgroundImages);
  window.DesktopState?.saveSettings?.();
}

function loadPoseData(node = {}) {
  const pose = defaultPose();
  const controls = node.poseData?.controls || node.poseData?.pose || {};
  CONTROL_DEFS.forEach(def => {
    pose[def.key] = clamp(controls[def.key] ?? node.poseData?.[def.key] ?? def.value, def.min, def.max);
  });
  return pose;
}

function drawImageCover(ctx, image, width, height) {
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  ctx.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('背景图读取失败'));
    image.crossOrigin = 'anonymous';
    image.src = url;
  });
}

async function exportCanvasDataUrl() {
  runtime.renderer.render(runtime.scene, runtime.camera);
  const source = runtime.renderer.domElement;
  const includeBackground = !!modal.querySelector('[data-pose-studio-export-background]')?.checked;
  if (!includeBackground || !runtime.backgroundUrl) return source.toDataURL('image/png');
  try {
    const image = await loadImage(runtime.backgroundUrl);
    const output = document.createElement('canvas');
    output.width = source.width;
    output.height = source.height;
    const ctx = output.getContext('2d');
    drawImageCover(ctx, image, output.width, output.height);
    ctx.drawImage(source, 0, 0, output.width, output.height);
    return output.toDataURL('image/png');
  } catch (error) {
    return source.toDataURL('image/png');
  }
}

async function exportCurrentPose() {
  if (runtime?.mode === 'director_stage') {
    await exportCurrentDirectorStage();
    return;
  }
  if (!runtime?.onExport) return;
  const imageData = await exportCanvasDataUrl();
  const poseData = {
    version: 1,
    mode: 'three_skeleton_lite',
    controls: { ...runtime.pose },
    humanConfig: normalizeHumanConfig(runtime.humanConfig || {}),
    updatedAt: Date.now()
  };
  runtime.onExport({
    mode: 'three_skeleton_lite',
    poseTitle: runtime.node?.poseTitle || '姿态编辑器',
    imageData,
    poseData,
    exportMode: modal.querySelector('[data-pose-studio-export-background]')?.checked ? 'pose_with_background' : 'pose_reference',
    backgroundImage: runtime.node?.backgroundImage || '',
    backgroundName: runtime.node?.backgroundName || '',
    backgroundSource: runtime.node?.backgroundSource || '',
    backgroundSourceNodeId: runtime.node?.backgroundSourceNodeId || '',
    backgroundMeta: runtime.node?.backgroundMeta || null,
    camera: {
      position: runtime.camera.position.toArray(),
      target: runtime.controls.target.toArray()
    },
    lights: [{ type: 'hemisphere' }, { type: 'directional' }]
  });
  close();
}

async function exportCurrentDirectorStage() {
  if (!runtime?.onExport) return;
  if (runtime.directorData.viewMode === 'camera') {
    applyDirectorViewMode();
  }
  const imageData = await exportCanvasDataUrl();
  const activeCamera = activeDirectorCamera() || directorDefaultCamera(0);
  const updatedActiveCamera = cameraDataFromCurrentView(activeCamera);
  const assetSummary = directorAssetSummary();
  const directorData = {
    ...runtime.directorData,
    cameras: (runtime.directorData.cameras || [activeCamera]).map(camera => (
      camera.id === activeCamera.id
        ? updatedActiveCamera
        : camera
    )),
    updatedAt: Date.now()
  };
  runtime.directorData = directorData;
  const poseData = {
    version: 1,
    mode: 'director_stage',
    directorData,
    assetMode: assetSummary.assetMode,
    assetSummary,
    updatedAt: Date.now()
  };
  runtime.onExport({
    mode: 'director_stage',
    poseTitle: normalizePoseTitle(runtime.node?.poseTitle),
    imageData,
    poseData,
    directorData,
    exportMode: modal.querySelector('[data-pose-studio-export-background]')?.checked ? 'director_stage_with_background' : 'director_stage',
    backgroundImage: runtime.node?.backgroundImage || '',
    backgroundName: runtime.node?.backgroundName || '',
    backgroundSource: runtime.node?.backgroundSource || '',
    backgroundSourceNodeId: runtime.node?.backgroundSourceNodeId || '',
    backgroundMeta: runtime.node?.backgroundMeta || null,
    camera: {
      position: runtime.camera.position.toArray(),
      target: runtime.controls.target.toArray(),
      fov: runtime.camera.fov,
      activeCameraId: directorData.activeCameraId
    },
    lights: [{ type: 'hemisphere' }, { type: 'directional' }]
  });
  close();
}

function close() {
  if (runtime?.frame) cancelAnimationFrame(runtime.frame);
  document.body.classList.remove('is-director-joint-dragging');
  runtime?.controls?.dispose?.();
  runtime?.renderer?.dispose?.();
  runtime = null;
  modal?.classList.remove('is-open');
  modal?.setAttribute('aria-hidden', 'true');
}

function inferPoseStudioMode(node = {}) {
  const nodeMode = node?.mode || node?.poseData?.mode || '';
  if (nodeMode === 'director_stage') return 'director_stage';
  if (nodeMode === 'legacy_pose' || nodeMode === 'three_skeleton_lite') return 'legacy_pose';
  if (node?.directorData && typeof node.directorData === 'object') return 'director_stage';
  if (!nodeMode && node?.type === 'pose') return 'legacy_pose';
  return 'director_stage';
}

function open(options = {}) {
  ensureModal();
  close();
  const mode = inferPoseStudioMode(options.node || {});
  runtime = {
    mode,
    nodeId: options.nodeId || '',
    node: options.node || {},
    backgroundImages: backgroundImagesForNode(options.node || {}, options.backgroundImages || []),
    onExport: options.onExport,
    onUpdate: options.onUpdate,
    humanConfig: normalizeHumanConfig(options.node?.humanConfig || options.node?.poseData?.humanConfig || {}),
    pose: loadPoseData(options.node || {}),
    directorData: normalizeDirectorData(options.node || {})
  };
  if (runtime.node && mode === 'director_stage') {
    runtime.node.poseTitle = normalizePoseTitle(runtime.node.poseTitle);
  }
  modal.querySelector('[data-pose-studio-title]').textContent = mode === 'director_stage'
    ? normalizePoseTitle(options.node?.poseTitle)
    : (options.node?.poseTitle || '姿态编辑器');
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
  buildControls();
  syncControls();
  applyBackground(runtime.backgroundImages);
  const stage = modal.querySelector('[data-pose-studio-stage]');
  buildScene(stage);
  window.addEventListener('resize', runtime.resize, { once: true });
}

window.DesktopPoseStudio = {
  open,
  close,
  debugSnapshot,
  debugSelectJoint,
  debugApplyJointRotation,
  debugApplyJointAxisDelta,
  debugSelectedJointScreenTarget,
  debugSelectedJointAxisTarget
};
