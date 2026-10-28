// SOMA mannequin rig: GLB template loading, per-character figures and posing. Each figure keeps the template
// of its body (neutral, an Anny preset or a recognised shape); joint names and order are the same in all of them.
// Convention (verified against SOMA, docs/POSE_REFERENCE_REBUILD_PLAN.md §2):
//   bone_local = conj(O[parent]) * R_rel * O[joint]; R_rel is T-pose-relative, in T-pose world axes.
import * as THREE from '../static/pose/three.module.js';
import { GLTFLoader } from '../static/pose/GLTFLoader.js';
import { clone as cloneSkinned } from '../static/pose/SkeletonUtils.js';

const model = window.DesktopPoseModel;
const GROUND_JOINTS = ['LeftFoot', 'RightFoot', 'LeftToeBase', 'RightToeBase', 'LeftToeEnd', 'RightToeEnd'];
const tmp = new THREE.Vector3();
const quat = a => new THREE.Quaternion(a[0], a[1], a[2], a[3]);

export function parseTemplate(buffer) {
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(buffer, '', gltf => {
      const meta = gltf.scene.userData?.soma;
      if (!meta || !Array.isArray(meta.joint_names) || meta.joint_names.join('|') !== model.SOMA_JOINTS.join('|')) {
        reject(new Error('人偶文件与 SOMA 骨架不一致，请重新安装姿态人偶')); return;
      }
      const template = {scene: gltf.scene, meta, idx: Object.fromEntries(meta.joint_names.map((n, i) => [n, i])),
        parents: meta.parents, orient: meta.orient_xyzw.map(quat), hips: new THREE.Vector3(...meta.hips_translation), restFootY: 0,
        body: String(meta.body || 'neutral'), heightRatio: meta.height_ratio > 0 ? meta.height_ratio : 1};
      const probe = createFigure(template);
      // Unit scale (height 175 cm on the neutral scale) so restFootY is in the template's own metres.
      applyPose(probe, {rotations: {}, hands: {left: 'open', right: 'open'}, position: [0, 0], yaw: 0, height: 175 * template.heightRatio, grounded: false});
      template.restFootY = Math.min(...GROUND_JOINTS.map(n => jointWorld(probe, n).y));
      disposeFigure(probe);
      resolve(template);
    }, error => reject(error instanceof Error ? error : new Error('人偶文件解析失败')));
  });
}

export function createFigure(template) {
  const root = new THREE.Group();
  const body = cloneSkinned(template.scene);
  root.add(body);
  let mesh = null;
  body.traverse(o => { if (o.isSkinnedMesh) mesh = o; });
  mesh.frustumCulled = false;
  return {root, body, mesh, template, bones: mesh.skeleton.bones, materials: {}};
}

export function disposeFigure(figure) {
  figure.root.removeFromParent();
  Object.values(figure.materials).forEach(m => m.dispose());
}

// Per hand, a shape replaces the finger rotations and `captured` keeps them (see the pose model).
export const effectiveRotations = character => model.effectiveRotations(character);

// height_cm is on the neutral mannequin's scale: other bodies divide by their rest height ratio.
export const figureScale = (template, character) => character.height / 175 / template.heightRatio;

export function applyPose(figure, character) {
  const template = figure.template;
  const rotations = effectiveRotations(character);
  const {parents, orient} = template;
  figure.bones.forEach((bone, j) => {
    const p = parents[j];
    const rel = rotations[template.meta.joint_names[j]];
    const local = p < 0 ? new THREE.Quaternion() : orient[p].clone().conjugate();
    if (rel) local.multiply(quat(rel));
    bone.quaternion.copy(local.multiply(orient[j]));
  });
  figure.bones[1].position.copy(template.hips);
  const scale = figureScale(template, character);
  figure.root.scale.setScalar(scale);
  const elevation = character.elevation || 0;
  figure.root.position.set(character.position[0], elevation, character.position[1]);
  figure.root.rotation.set(0, character.yaw * Math.PI / 180, 0);
  figure.body.position.y = 0;
  figure.root.updateMatrixWorld(true);
  if (Number.isFinite(character.hips)) {
    // A recognised video frame: the hips sit where the camera saw them, whatever this body's leg length.
    figure.body.position.y = (character.hips - jointWorld(figure, 'Hips', tmp).y) / scale;
    figure.root.updateMatrixWorld(true);
  } else if (character.grounded !== false) {
    // Keep the lowest foot point on the ground (raised by `elevation`) the way the T-pose stands.
    const lowest = Math.min(...GROUND_JOINTS.map(n => jointWorld(figure, n).y)) - elevation;
    figure.body.position.y = (template.restFootY * scale - lowest) / scale;
    figure.root.updateMatrixWorld(true);
  }
}

// The T-pose-relative rotation of a joint from its bone's current local rotation.
export function relFromBone(figure, name) {
  const template = figure.template, j = template.idx[name], bone = figure.bones[j];
  const p = template.parents[j];
  const parent = p < 0 ? new THREE.Quaternion() : template.orient[p].clone();
  const q = parent.multiply(bone.quaternion.clone()).multiply(template.orient[j].clone().conjugate()).normalize();
  return model.normalizeQuat([q.x, q.y, q.z, q.w]);
}

export function jointWorld(figure, name, out = new THREE.Vector3()) {
  return figure.bones[figure.template.idx[name]].getWorldPosition(out);
}

// Hips world position and yaw-folded Hips rotation for the backend snapshot.
export function worldHips(figure, character) {
  const transl = jointWorld(figure, 'Hips', tmp).toArray().map(v => Math.round(v * 1e5) / 1e5);
  const yaw = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), character.yaw * Math.PI / 180);
  const hips = yaw.multiply(quat(character.rotations.Hips || model.IDENTITY));
  return {transl, hips: [hips.x, hips.y, hips.z, hips.w]};
}
