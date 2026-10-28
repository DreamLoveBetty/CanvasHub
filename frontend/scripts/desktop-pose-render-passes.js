// Output passes: mannequin, OpenPose, depth, normal and mask, all from one camera at one size.
// Exports render straight to a dedicated canvas so built-in materials encode sRGB in the shader
// while depth and normal values are written raw.
import * as THREE from '../static/pose/three.module.js';
import { jointWorld } from './desktop-pose-soma-rig.js';

const model = window.DesktopPoseModel;
const CLAY = 0xc4cad3;

// Linear depth between the visible figures' near and far bounds; near is white.
function depthMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {near: {value: 1}, far: {value: 2}},
    vertexShader: `#include <common>
#include <skinning_pars_vertex>
varying float vViewZ;
void main() {
  #include <skinbase_vertex>
  #include <begin_vertex>
  #include <skinning_vertex>
  #include <project_vertex>
  vViewZ = -mvPosition.z;
}`,
    fragmentShader: `uniform float near;
uniform float far;
varying float vViewZ;
void main() { gl_FragColor = vec4(vec3(clamp((far - vViewZ) / (far - near), 0.0, 1.0)), 1.0); }`,
  });
}

export function figureMaterials(figure, color) {
  if (!figure.materials.clay) {
    figure.materials.clay = new THREE.MeshStandardMaterial({roughness: 0.64, metalness: 0.02});
    figure.materials.mask = new THREE.MeshBasicMaterial();
  }
  figure.materials.clay.color.set(CLAY).lerp(new THREE.Color(color), 0.1);
  figure.materials.mask.color.set(color);
  return figure.materials;
}

export function createPassKit() {
  return {depth: depthMaterial(), normal: new THREE.MeshNormalMaterial()};
}

// figures: [{figure, character}] in the stage; swaps each figure to the pass material.
export function applyPass(kit, figures, pass) {
  figures.forEach(({figure, character}) => {
    const materials = figureMaterials(figure, character.color);
    figure.root.visible = character.visible && pass !== 'openpose';
    figure.mesh.material = pass === 'depth' ? kit.depth : pass === 'normal' ? kit.normal : pass === 'mask' ? materials.mask : materials.clay;
  });
}

export function setDepthRange(kit, figures, camera) {
  const box = new THREE.Box3();
  figures.filter(f => f.character.visible).forEach(f => box.expandByObject(f.figure.root));
  if (box.isEmpty()) return;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  camera.updateMatrixWorld();
  const distance = sphere.center.clone().applyMatrix4(camera.matrixWorldInverse).length();
  kit.depth.uniforms.near.value = Math.max(0.05, distance - sphere.radius - 0.05);
  kit.depth.uniforms.far.value = distance + sphere.radius + 0.05;
}

function project(v, camera, w, h) {
  const p = v.clone().project(camera);
  return [(p.x + 1) / 2 * w, (1 - p.y) / 2 * h, p.z];
}

// Derived COCO points: nose, neck (shoulder midpoint) and ears, from head, eye and arm joints.
export function openPosePoints(figure) {
  const P = name => jointWorld(figure, name);
  const le = P('LeftEye'), re = P('RightEye'), head = P('Head');
  const eyes = le.clone().add(re).multiplyScalar(0.5);
  const lateral = le.clone().sub(re).normalize();
  const up = P('HeadEnd').sub(head).normalize();
  const forward = new THREE.Vector3().crossVectors(lateral, up).normalize();
  const scale = figure.root.scale.x;
  const earBase = head.clone().lerp(eyes, 0.55).addScaledVector(forward, -0.06 * scale);
  const derived = {
    nose: eyes.clone().addScaledVector(forward, 0.025 * scale).addScaledVector(up, -0.04 * scale),
    neck: P('LeftArm').add(P('RightArm')).multiplyScalar(0.5),
    rightEar: earBase.clone().addScaledVector(lateral, -0.075 * scale),
    leftEar: earBase.clone().addScaledVector(lateral, 0.075 * scale),
  };
  return model.OPENPOSE.body.map(name => derived[name] || P(name));
}

export function drawOpenPose(ctx, figures, camera, w, h, settings) {
  const stick = Math.max(2, h / 128) * (settings.openposeWidth === 'bold' ? 1.5 : 1);
  const {limbs, colors} = model.OPENPOSE;
  camera.updateMatrixWorld();
  // Far figures first so nearer limbs stay on top.
  const ordered = figures.filter(f => f.character.visible)
    .map(f => ({...f, depth: jointWorld(f.figure, 'Hips').applyMatrix4(camera.matrixWorldInverse).z}))
    .sort((x, y) => x.depth - y.depth);
  ctx.save();
  ctx.lineCap = 'round';
  for (const {figure} of ordered) {
    const pts = openPosePoints(figure).map(v => project(v, camera, w, h));
    limbs.forEach(([from, to], i) => {
      const [x1, y1, z1] = pts[from], [x2, y2, z2] = pts[to];
      if (z1 > 1 || z2 > 1) return;
      ctx.fillStyle = `rgba(${colors[i].join(',')},0.6)`;
      ctx.beginPath();
      ctx.ellipse((x1 + x2) / 2, (y1 + y2) / 2, Math.hypot(x2 - x1, y2 - y1) / 2, stick, Math.atan2(y2 - y1, x2 - x1), 0, Math.PI * 2);
      ctx.fill();
    });
    pts.forEach(([x, y, z], i) => {
      if (z > 1) return;
      ctx.fillStyle = `rgb(${colors[i].join(',')})`;
      ctx.beginPath(); ctx.arc(x, y, stick, 0, Math.PI * 2); ctx.fill();
    });
    if (!settings.openposeHands) continue;
    for (const side of ['Left', 'Right']) {
      const hand = model.OPENPOSE.hand(side).map(name => project(jointWorld(figure, name), camera, w, h));
      ctx.lineWidth = Math.max(1, stick * 0.45);
      for (let finger = 0; finger < 5; finger++) {
        for (let k = 0; k < 4; k++) {
          const from = k ? hand[1 + finger * 4 + k - 1] : hand[0], to = hand[1 + finger * 4 + k];
          ctx.strokeStyle = `hsl(${(finger * 4 + k) / 20 * 360},100%,50%)`;
          ctx.beginPath(); ctx.moveTo(from[0], from[1]); ctx.lineTo(to[0], to[1]); ctx.stroke();
        }
      }
      ctx.fillStyle = '#0000ff';
      hand.slice(1).forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, Math.max(1, stick * 0.4), 0, Math.PI * 2); ctx.fill(); });
    }
  }
  ctx.restore();
}

// One pass into a fresh 2D canvas of exactly w×h.
export function renderPassToCanvas({renderer, scene, kit, figures, camera, pass, width, height, settings, prepare}) {
  renderer.setSize(width, height, false);
  const transparent = pass === 'mannequin' && settings.background === 'transparent';
  renderer.setClearColor(0x000000, transparent ? 0 : 1);
  prepare?.(pass);
  applyPass(kit, figures, pass);
  if (pass === 'depth') setDepthRange(kit, figures, camera);
  renderer.render(scene, camera);
  const out = document.createElement('canvas');
  out.width = width; out.height = height;
  const ctx = out.getContext('2d');
  ctx.drawImage(renderer.domElement, 0, 0, width, height);
  if (pass === 'openpose') drawOpenPose(ctx, figures, camera, width, height, settings);
  return out;
}
