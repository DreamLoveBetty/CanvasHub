// Two-bone IK for arms and legs. Keeps the current bend plane, so elbows and knees do not flip.
import * as THREE from '../static/pose/three.module.js';
import { jointWorld, relFromBone } from './desktop-pose-soma-rig.js';

const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();

function rotateBoneToward(bone, from, to) {
  const delta = new THREE.Quaternion().setFromUnitVectors(from.clone().normalize(), to.clone().normalize());
  const world = bone.getWorldQuaternion(new THREE.Quaternion());
  const parent = bone.parent.getWorldQuaternion(new THREE.Quaternion());
  bone.quaternion.copy(parent.invert().multiply(delta.multiply(world)));
  bone.updateMatrixWorld(true);
}

// chain: [upper, lower, end] joint names. Returns the new relative rotations of upper and lower, or null for a degenerate chain.
export function solveTwoBone(figure, chain, target) {
  const [upper, lower] = chain.slice(0, 2).map(name => figure.bones[figure.template.idx[name]]);
  jointWorld(figure, chain[0], a); jointWorld(figure, chain[1], b); jointWorld(figure, chain[2], c);
  const l1 = a.distanceTo(b), l2 = b.distanceTo(c);
  if (!(l1 > 1e-5 && l2 > 1e-5)) return null;
  const toTarget = target.clone().sub(a);
  const distance = THREE.MathUtils.clamp(toTarget.length(), Math.abs(l1 - l2) + 1e-4, l1 + l2 - 1e-4);
  const axis = toTarget.lengthSq() > 1e-10 ? toTarget.clone().normalize() : c.clone().sub(a).normalize();
  // Bend direction: the current middle joint offset perpendicular to the reach axis.
  let bend = b.clone().sub(a);
  bend.sub(axis.clone().multiplyScalar(bend.dot(axis)));
  if (bend.lengthSq() < 1e-10) bend = new THREE.Vector3(0, 0, 1).cross(axis);
  bend.normalize();
  const cos = THREE.MathUtils.clamp((l1 * l1 + distance * distance - l2 * l2) / (2 * l1 * distance), -1, 1);
  const middle = a.clone().add(axis.clone().multiplyScalar(l1 * cos)).add(bend.multiplyScalar(l1 * Math.sqrt(1 - cos * cos)));
  rotateBoneToward(upper, b.clone().sub(a), middle.clone().sub(a));
  jointWorld(figure, chain[1], b); jointWorld(figure, chain[2], c);
  const reach = a.clone().add(axis.multiplyScalar(distance));
  rotateBoneToward(lower, c.clone().sub(b), reach.sub(b));
  return {[chain[0]]: relFromBone(figure, chain[0]), [chain[1]]: relFromBone(figure, chain[1])};
}
