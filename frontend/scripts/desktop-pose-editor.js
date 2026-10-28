// Pose editor controller (ES module entry). Edits a pose node's scene in place and tells the
// canvas controller through callbacks; exports stay owned by desktop-canvas-pose.js.
// The viewport WebGL context exists only while the editor is open.
import * as THREE from '../static/pose/three.module.js';
import { OrbitControls } from '../static/pose/OrbitControls.js';
import { TransformControls } from '../static/pose/TransformControls.js';
import { jointWorld, relFromBone } from './desktop-pose-soma-rig.js';
import { solveTwoBone } from './desktop-pose-ik.js';
import { applyPass, createPassKit, drawOpenPose, setDepthRange } from './desktop-pose-render-passes.js';
import { Stage, focalToFov, loadSequence, loadTemplates, presetThumbnails, renderNode, sequences } from './desktop-pose-scene.js';
import { createTimeline } from './desktop-pose-timeline.js';
import * as view from './desktop-pose-editor-view.js';

const model = window.DesktopPoseModel;
const DEG = Math.PI / 180;
const VIEW_BG = new THREE.Color(0x080d14);
const AXIS_COLORS = {x: '#e5484d', y: '#30a46c', z: '#3e8ef7'};

let root = null;
let session = null;   // {node, references, onChange, onExport, onClose, undo, redo, baseline, ...}
let gl = null;        // three.js objects, only while open
const ui = {tool: 'rotate', space: 'local', snap: false, joints: true, hands: false, reference: false, view: 'free', pass: 'mannequin', tab: 'pose', sidebar: true};
const $ = sel => root.querySelector(sel);
const $$ = sel => [...root.querySelectorAll(sel)];

// ---------------------------------------------------------------- session helpers
const scene = () => session.node.scene;
const character = () => scene().characters.find(c => c.id === session.activeCharId) || null;
const shot = () => model.activeCamera(scene());
const figureOf = c => gl?.stage.figures.get(c.id);
const sequenceState = () => scene().sequence || null;
const currentFrame = () => sequenceState()?.frame ?? 0;
// Video characters follow their recognised person; every edit becomes a keyframe at the current frame.
const onTrack = c => Boolean(c?.track && gl?.sequence);
const rotationsOf = c => onTrack(c) ? sequences.rotationsAt(c, gl.sequence, currentFrame()) : c.rotations;
const round6 = q => q.map(v => Math.round(v * 1e6) / 1e6);
function keyAt(c, frame, create = false) {
  let key = c.keys.find(k => k.frame === frame);
  if (!key && create) { key = {frame, rotations: {}}; c.keys.push(key); c.keys.sort((a, b) => a.frame - b.frame); }
  return key || null;
}
function setRotation(c, name, q) {
  const n = model.normalizeQuat(q);
  // Rotating a finger shows that hand's own fingers again (a preset would hide the edit).
  const side = /^(Left|Right)Hand./.exec(name)?.[1];
  if (side) c.hands[side.toLowerCase()] = model.CAPTURED_HAND;
  if (onTrack(c)) { if (n) keyAt(c, currentFrame(), true).rotations[name] = round6(n); return; }
  if (!n || model.isIdentity(n)) delete c.rotations[name]; else c.rotations[name] = round6(n);
}
// Keyframe every joint of a video character at the current frame with what it shows now.
function keyAll(c, rotations = rotationsOf(c)) {
  const key = keyAt(c, currentFrame(), true);
  Object.entries(rotations).forEach(([name, q]) => { key.rotations[name] = round6(q); });
}
function relEuler(c, name) {
  const q = rotationsOf(c)[name] || model.IDENTITY;
  const e = new THREE.Euler().setFromQuaternion(new THREE.Quaternion(...q), 'XYZ');
  return [e.x, e.y, e.z].map(v => Math.round(v / DEG));
}
function poseCharacter(c) { if (gl) gl.stage.pose(c); }
let changeTimer = 0;
function changed({history = false, panel = false, outline = false, immediate = false} = {}) {
  if (history) commit();
  if (panel) renderPanel(); else syncPanelValues();
  if (outline) renderOutline();
  paintStatus();
  paintTimeline();
  requestRender();
  clearTimeout(changeTimer);
  if (immediate) session.onChange(); else changeTimer = setTimeout(() => session?.onChange(), 250);
}
const snapshotState = () => JSON.stringify({scene: scene(), settings: session.node.settings, output: {pass: session.node.output.pass, size: session.node.output.size}});
function commit() {
  const snap = snapshotState();
  if (snap === session.baseline) return;
  session.undo.push(session.baseline);
  if (session.undo.length > 100) session.undo.shift();
  session.redo = [];
  session.baseline = snap;
  paintHistory();
}
function restore(snap) {
  const data = JSON.parse(snap);
  session.node.scene = model.normalizeScene(data.scene);
  Object.assign(session.node.settings, data.settings);
  Object.assign(session.node.output, data.output);
  if (!character()) session.activeCharId = scene().characters[0]?.id || '';
  gl?.stage.sync(scene());
  if (ui.view === 'camera') enterCameraView();
  attachGizmo(); rebuildHelpers(); renderOutline(); renderPanel(); paintStatus(); paintTimeline(); syncReferenceVideo(); requestRender();
  clearTimeout(changeTimer); session.onChange();
  syncBodies();
}
// Load the templates of any body the scene now uses; figures of other bodies are rebuilt on the next sync.
async function syncBodies() {
  if (!gl) return;
  const owner = gl;
  const {templates, missing} = await loadTemplates(scene().characters, 'low');
  if (gl !== owner || !session) return;
  gl.stage.setTemplates(templates);
  gl.missingBodies = new Set(missing);
  gl.stage.sync(scene());
  attachGizmo(); renderPanel(); requestRender();
}
function undo() { if (!session.undo.length) return; session.redo.push(session.baseline); session.baseline = session.undo.pop(); restore(session.baseline); paintHistory(); }
function redo() { if (!session.redo.length) return; session.undo.push(session.baseline); session.baseline = session.redo.pop(); restore(session.baseline); paintHistory(); }
function paintHistory() { $('[data-pe-undo]').disabled = !session.undo.length; $('[data-pe-redo]').disabled = !session.redo.length; }
function paintStatus() {
  const status = $('[data-pe-status]');
  const failed = session.exportError;
  status.textContent = session.exporting ? '导出中…' : failed ? '导出失败' : session.sequenceError ? '序列无法载入'
    : !session.node.output.artifactUrl ? '尚未导出' : model.dirty(session.node) ? '有未导出的修改' : '已同步到节点';
  if (session.sequenceError && !failed) status.title = session.sequenceError;
  status.classList.toggle('is-dirty', !session.exporting && !failed && model.dirty(session.node));
  status.classList.toggle('is-busy', Boolean(session.exporting));
  status.classList.toggle('is-failed', Boolean(failed));
  status.title = failed || '';
  $('[data-pe-export]').disabled = Boolean(session.exporting);
  const reset = $('[data-pe-reset-pose]'), track = onTrack(character());
  reset.textContent = track ? '清除关键帧' : '重置为站立';
  reset.title = track ? '删除选中角色的全部关键帧，回到识别结果' : '';
  const [w, h] = model.outputSize(session.node.output.size, shot().aspect);
  const seq = sequenceState(), video = model.exportsVideo(session.node);
  $('[data-pe-export]').textContent = session.exporting ? '导出中…' : video ? '导出视频' : '导出到节点';
  $('[data-pe-footer-note]').textContent = video
    ? `导出 ${shot().name} 的 ${model.PASSES[session.node.output.pass]}视频 · ${w}×${h} · ${seq.outFrame - seq.inFrame + 1} 帧，写入连接的视频节点`
    : `导出 ${shot().name} 的 ${model.PASSES[session.node.output.pass]} · ${w}×${h}，节点和下游连接随之更新`;
}

// ---------------------------------------------------------------- three.js lifecycle
async function startViewport() {
  const owner = session;
  // A force-lost context cannot be revived, so every session gets a fresh canvas element.
  const previous = $('[data-pe-canvas]');
  const canvas = previous.cloneNode(false);
  previous.replaceWith(canvas);
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const [{templates, missing}, sequence] = await Promise.all([loadTemplates(scene().characters, 'low'),
    loadSequence(scene()).catch(error => { owner.sequenceError = `识别序列无法载入（${error?.message || '已删除'}），角色显示第一帧`; return null; })]);
  if (session !== owner) { renderer.dispose(); renderer.forceContextLoss(); return; }
  const stage = new Stage(templates);
  const grid = new THREE.GridHelper(12, 24, 0x324256, 0x1a2532);
  const helpers = new THREE.Group();
  const ikProxy = new THREE.Object3D();
  stage.scene.add(grid, helpers, ikProxy);
  const freeCam = new THREE.PerspectiveCamera(32, 1, 0.05, 100);
  const orbit = new OrbitControls(freeCam, canvas);
  orbit.mouseButtons = {LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN};
  const gizmo = new TransformControls(freeCam, canvas);
  gizmo.setSize(0.72);
  stage.scene.add(gizmo);
  gl = {renderer, stage, sequence, missingBodies: new Set(missing), grid, helpers, ikProxy, freeCam, orbit, gizmo, kit: createPassKit(), screenJoints: [], syncing: false, freeSaved: null,
    resize: new ResizeObserver(() => requestRender())};
  gl.resize.observe($('[data-pe-viewer]'));
  orbit.addEventListener('change', () => { if (ui.view === 'camera' && !gl.syncing) syncShotFromView(); requestRender(); });
  orbit.addEventListener('end', () => { if (ui.view === 'camera') changed({history: true, outline: true}); });
  gizmo.addEventListener('dragging-changed', event => { orbit.enabled = !event.value; if (!event.value) changed({history: true, outline: true}); });
  gizmo.addEventListener('objectChange', onGizmoChange);
  gizmo.addEventListener('change', requestRender);
  stage.sync(scene(), sequence);
  gl.timeline = createTimeline(root, {onFrame: setFrame, onKey: keyFrame, onUnkey: unkeyFrame, onRange: setRange});
  frameCharacters();
  rebuildHelpers();
  attachGizmo();
  paintTimeline(); paintStatus(); syncReferenceVideo();
  renderPanel();  // the panel was drawn before the sequence loaded: video characters get their controls now
  $('[data-pe-loading]').hidden = true;
  if (ui.view === 'camera') { ui.view = 'free'; setView('camera'); }
  requestRender();
}
function stopViewport() {
  if (!gl) return;
  gl.timeline?.destroy();
  gl.resize.disconnect();
  gl.gizmo.detach(); gl.gizmo.dispose(); gl.orbit.dispose();
  gl.stage.dispose();
  gl.grid.geometry.dispose(); gl.grid.material.dispose();
  gl.helpers.children.forEach(line => { line.geometry.dispose(); line.material.dispose(); });
  gl.kit.depth.dispose(); gl.kit.normal.dispose();
  gl.renderer.dispose(); gl.renderer.forceContextLoss();
  gl = null;
  const overlay = $('[data-pe-overlay]');
  overlay.getContext('2d').clearRect(0, 0, overlay.width, overlay.height);
}
function frameCharacters() {
  const chars = scene().characters;
  const cx = chars.length ? chars.reduce((s, c) => s + c.position[0], 0) / chars.length : 0;
  const cz = chars.length ? chars.reduce((s, c) => s + c.position[1], 0) / chars.length : 0;
  gl.orbit.target.set(cx, 0.92, cz);
  gl.freeCam.position.set(cx + 2.6, 1.9, cz + 5.2);
  gl.orbit.update();
}

// ---------------------------------------------------------------- rendering
let frameQueued = false;
function requestRender() { if (!frameQueued && gl) { frameQueued = true; requestAnimationFrame(renderNow); } }
function viewerSize() { const r = $('[data-pe-viewer]').getBoundingClientRect(); return [Math.max(1, Math.round(r.width)), Math.max(1, Math.round(r.height))]; }
function frameRect(vw, vh) {
  const a = model.ASPECTS[shot().aspect], m = 0.86;
  let fw = vw * m, fh = fw / a;
  if (fh > vh * m) { fh = vh * m; fw = fh * a; }
  return {x: (vw - fw) / 2, y: (vh - fh) / 2, w: fw, h: fh};
}
// Camera view widens the shot's vertical FOV so the output frame sits inside the viewport with context around it.
function viewCamera(vw, vh) {
  const cam = gl.freeCam;
  if (ui.view === 'camera') {
    const f = frameRect(vw, vh);
    cam.fov = 2 * Math.atan(Math.tan(focalToFov(shot().focalMm) * DEG / 2) * (vh / f.h)) / DEG;
  } else cam.fov = 32;
  cam.aspect = vw / vh;
  cam.updateProjectionMatrix();
  return cam;
}
function renderNow() {
  frameQueued = false;
  if (!gl || !session) return;
  const [vw, vh] = viewerSize();
  const dpr = gl.renderer.getPixelRatio();
  const canvas = gl.renderer.domElement;
  if (canvas.width !== Math.round(vw * dpr) || canvas.height !== Math.round(vh * dpr)) gl.renderer.setSize(vw, vh, false);
  const overlay = $('[data-pe-overlay]');
  if (overlay.width !== Math.round(vw * dpr) || overlay.height !== Math.round(vh * dpr)) { overlay.width = Math.round(vw * dpr); overlay.height = Math.round(vh * dpr); }
  const cam = viewCamera(vw, vh);
  const entries = gl.stage.entries();
  applyPass(gl.kit, entries, ui.pass);
  gl.stage.scene.background = ui.pass === 'mannequin' ? VIEW_BG : new THREE.Color(0x000000);
  gl.grid.visible = ui.pass === 'mannequin';
  gl.helpers.visible = ui.view === 'free';
  if (ui.pass === 'depth') setDepthRange(gl.kit, entries, cam);
  gl.renderer.render(gl.stage.scene, cam);
  const ctx = overlay.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, vw, vh);
  if (ui.pass === 'openpose') drawOpenPose(ctx, entries, cam, vw, vh, {...session.node.settings, openposeWidth: 'standard'});
  drawJoints(ctx, cam, vw, vh);
  drawAxes(cam);
  const frame = $('[data-pe-frame]');
  frame.hidden = ui.view !== 'camera';
  if (!frame.hidden) {
    const f = frameRect(vw, vh), [ow, oh] = model.outputSize(session.node.output.size, shot().aspect);
    Object.assign(frame.style, {left: f.x + 'px', top: f.y + 'px', width: f.w + 'px', height: f.h + 'px'});
    $('[data-pe-frame-label]').textContent = `${shot().name} · ${shot().focalMm} mm · ${shot().aspect} · 输出 ${ow}×${oh}`;
  }
  const showReference = ui.reference && ui.view === 'camera';
  const video = Boolean(gl?.sequence && session.videos.length);
  $('[data-pe-reference]').hidden = !(showReference && !video && session.references.length);
  $('[data-pe-reference-video]').hidden = !(showReference && video);
}
// ---------------------------------------------------------------- sequence timeline
function setFrame(frame) {
  const seq = sequenceState();
  if (!seq || !gl) return;
  seq.frame = frame;
  gl.stage.setFrame(frame);
  const c = character();
  if (gl.gizmo.object === gl.ikProxy && c && session.activeJoint) { jointWorld(figureOf(c), session.activeJoint, gl.ikProxy.position); gl.ikProxy.updateMatrixWorld(); }
  syncReferenceVideo(); syncPanelValues(); paintTimeline(); paintStatus(); requestRender();
  clearTimeout(changeTimer); changeTimer = setTimeout(() => session?.onChange(), 400);
}
function paintTimeline() {
  if (!gl?.timeline) return;
  const seq = sequenceState(), c = character();
  if (!seq || !gl.sequence) { gl.timeline.paint(null); return; }
  let confidence = null;
  if (onTrack(c)) {
    const person = gl.sequence.people[c.track.person];
    confidence = gl.confidence?.person === person ? gl.confidence.values : new Float32Array(seq.frameCount).fill(NaN);
    if (gl.confidence?.person !== person) {
      for (let i = 0; i < person.count && person.start + i < seq.frameCount; i++) confidence[person.start + i] = person.confidence[i];
      gl.confidence = {person, values: confidence};
    }
  }
  gl.timeline.paint({frameCount: seq.frameCount, frame: seq.frame, fps: seq.fps, keys: onTrack(c) ? c.keys.map(k => k.frame) : [],
    confidence, inFrame: seq.inFrame, outFrame: seq.outFrame, canKey: onTrack(c) && !c.locked});
}
function keyFrame() {
  const c = character();
  if (!onTrack(c) || c.locked) return;
  keyAll(c);
  changed({history: true, panel: true});
}
function unkeyFrame() {
  const c = character();
  if (!onTrack(c)) return;
  c.keys = c.keys.filter(k => k.frame !== currentFrame());
  poseCharacter(c); attachGizmo();
  changed({history: true, panel: true});
}
function setRange(inFrame, outFrame) {
  const seq = sequenceState();
  if (!seq) return;
  Object.assign(seq, {inFrame, outFrame});
  changed({history: true});
}
// The connected video, shown under the camera frame at the current frame time. It is read into a Blob URL:
// seeking needs byte ranges, which not every media route serves.
async function loadReferenceVideo(owner) {
  const video = $('[data-pe-reference-video]');
  video.removeAttribute('src');
  if (!owner.videos[0] || !owner.node.scene.sequence) return;
  video.onloadedmetadata = syncReferenceVideo;
  try {
    const response = await fetch(owner.videos[0].url, {credentials: 'same-origin'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    if (session !== owner) { URL.revokeObjectURL(url); return; }
    owner.videoUrl = url;
    video.src = url;
  } catch (_error) {
    if (session === owner) video.src = owner.videos[0].url;  // still shows the clip; seeking may be coarse
  }
}
function syncReferenceVideo() {
  const video = $('[data-pe-reference-video]'), seq = sequenceState();
  if (!seq || !session?.videos.length) return;
  const time = (seq.frame + 0.5) / seq.fps;
  if (video.readyState >= 1 && Math.abs(video.currentTime - time) > 0.5 / seq.fps) video.currentTime = time;
}
const accent = () => getComputedStyle(root).getPropertyValue('--desk-pose-joint-active').trim() || '#ff5a1f';
function pickable() {
  const list = [...model.MAIN_JOINTS];
  if (ui.hands) model.SOMA_JOINTS.forEach(n => { if (/Hand(Thumb|Index|Middle|Ring|Pinky)\d$/.test(n)) list.push(n); });
  return list;
}
function project(v, cam, w, h) { const p = v.clone().project(cam); return [(p.x + 1) / 2 * w, (1 - p.y) / 2 * h, p.z]; }
function drawJoints(ctx, cam, w, h) {
  gl.screenJoints = [];
  if (!ui.joints) return;
  const color = accent(), names = pickable();
  for (const {character: c, figure} of gl.stage.entries()) {
    if (!c.visible) continue;
    const active = c.id === session.activeCharId, template = figure.template;
    const pts = Object.fromEntries(names.map(n => [n, project(jointWorld(figure, n), cam, w, h)]));
    if (active) {
      ctx.strokeStyle = 'rgba(214,226,236,.42)'; ctx.lineWidth = 1;
      for (const n of names) {
        const parent = template.meta.joint_names[template.parents[template.idx[n]]];
        if (!pts[parent] || n === 'Hips' || pts[n][2] > 1) continue;
        ctx.beginPath(); ctx.moveTo(pts[parent][0], pts[parent][1]); ctx.lineTo(pts[n][0], pts[n][1]); ctx.stroke();
      }
    }
    for (const n of names) {
      const [x, y, z] = pts[n];
      if (z > 1) continue;
      const r = model.MAIN_JOINTS.includes(n) ? 4 : 2.6;
      gl.screenJoints.push({id: c.id, name: n, x, y, r: r + 5});
      if (active && n === session.activeJoint) {
        ctx.fillStyle = color; ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.arc(x, y, r + 5, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(x, y, r + 1, 0, Math.PI * 2); ctx.fill();
        continue;
      }
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = active ? '#e8eef5' : 'rgba(232,238,245,.45)';
      ctx.fillStyle = active ? (model.IK_CHAINS[n] && ui.tool === 'translate' ? color : 'rgba(8,13,20,.8)') : 'rgba(8,13,20,.5)';
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }
  }
}
let axisHits = [];
function drawAxes(cam) {
  const canvas = $('[data-pe-axes]'), ctx = canvas.getContext('2d'), c = 64;
  ctx.clearRect(0, 0, 128, 128);
  ctx.fillStyle = 'rgba(255,255,255,.05)'; ctx.beginPath(); ctx.arc(c, c, 58, 0, Math.PI * 2); ctx.fill();
  const inverse = cam.quaternion.clone().invert();
  axisHits = [['x', 1], ['y', 1], ['z', 1], ['x', -1], ['y', -1], ['z', -1]].map(([axis, sign]) => {
    const v = new THREE.Vector3(axis === 'x' ? sign : 0, axis === 'y' ? sign : 0, axis === 'z' ? sign : 0);
    const p = v.clone().applyQuaternion(inverse);
    return {axis, sign, v, x: c + p.x * 40, y: c - p.y * 40, z: p.z};
  }).sort((a, b) => a.z - b.z);
  for (const it of axisHits) {
    const col = AXIS_COLORS[it.axis];
    if (it.sign > 0) { ctx.strokeStyle = col; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(c, c); ctx.lineTo(it.x, it.y); ctx.stroke(); }
    ctx.fillStyle = it.sign > 0 ? col : 'rgba(20,28,38,.95)'; ctx.strokeStyle = col; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.arc(it.x, it.y, it.sign > 0 ? 13 : 9, 0, Math.PI * 2); ctx.fill(); if (it.sign < 0) ctx.stroke();
    if (it.sign > 0) { ctx.fillStyle = '#fff'; ctx.font = '600 15px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(it.axis.toUpperCase(), it.x, it.y + 1); }
  }
}
function snapView(direction) {
  if (!gl || ui.view === 'camera') return;
  const distance = gl.freeCam.position.distanceTo(gl.orbit.target);
  gl.freeCam.position.copy(gl.orbit.target).addScaledVector(direction.clone().normalize(), distance);
  if (Math.abs(direction.y) > 0.9) gl.freeCam.position.z += 1e-4;  // keep OrbitControls away from the pole
  gl.orbit.update();
  requestRender();
}
function rebuildHelpers() {
  if (!gl) return;
  gl.helpers.children.forEach(line => { line.geometry.dispose(); line.material.dispose(); });
  gl.helpers.clear();
  for (const s of scene().cameras) {
    const active = s.id === scene().activeCameraId;
    const h = 0.32, w = h * model.ASPECTS[s.aspect], d = 0.42 * s.focalMm / 35;
    const pts = [[0, 0, 0], [-w, h, -d], [0, 0, 0], [w, h, -d], [0, 0, 0], [-w, -h, -d], [0, 0, 0], [w, -h, -d], [-w, h, -d], [w, h, -d], [w, h, -d], [w, -h, -d],
      [w, -h, -d], [-w, -h, -d], [-w, -h, -d], [-w, h, -d], [-w * 0.4, h * 1.15, -d], [0, h * 1.6, -d], [0, h * 1.6, -d], [w * 0.4, h * 1.15, -d]];
    const line = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts.map(p => new THREE.Vector3(...p))),
      new THREE.LineBasicMaterial({color: active ? accent() : 0x7c8b9c, transparent: true, opacity: active ? 1 : 0.6}));
    line.position.set(...s.position);
    line.lookAt(...s.target);
    gl.helpers.add(line);
  }
}

// ---------------------------------------------------------------- selection and gizmo
function select(characterId, joint) {
  session.activeCharId = characterId;
  session.activeJoint = joint;
  attachGizmo(); renderOutline(); renderPanel(); paintSelectionLabel(); paintTimeline(); requestRender();
}
function attachGizmo() {
  if (!gl) return;
  const c = character();
  gl.gizmo.detach();
  gl.gizmo.setRotationSnap(ui.snap ? 15 * DEG : null);
  if (!c || c.locked || ui.tool === 'select') return requestRender();
  const figure = figureOf(c);
  const joint = session.activeJoint;
  gl.gizmo.showX = gl.gizmo.showY = gl.gizmo.showZ = true;
  if (ui.tool === 'translate' && joint && model.IK_CHAINS[joint]) {
    jointWorld(figure, joint, gl.ikProxy.position);
    gl.ikProxy.updateMatrixWorld();
    gl.gizmo.setMode('translate'); gl.gizmo.setSpace('world'); gl.gizmo.attach(gl.ikProxy);
  } else if (ui.tool === 'translate') {
    gl.gizmo.setMode('translate'); gl.gizmo.setSpace('world'); gl.gizmo.attach(figure.root);
  } else if (joint) {
    gl.gizmo.setMode('rotate'); gl.gizmo.setSpace(ui.space); gl.gizmo.attach(figure.bones[figure.template.idx[joint]]);
  } else {
    // No joint: a horizontal ring turns the whole character about its standing centre (the root).
    gl.gizmo.setMode('rotate'); gl.gizmo.showX = gl.gizmo.showZ = false; gl.gizmo.setSpace('world'); gl.gizmo.attach(figure.root);
  }
  requestRender();
}
function onGizmoChange() {
  const c = character(), figure = c && figureOf(c);
  if (!figure) return;
  const object = gl.gizmo.object;
  if (object === gl.ikProxy) {
    const result = solveTwoBone(figure, model.IK_CHAINS[session.activeJoint], gl.ikProxy.position.clone());
    if (result) Object.entries(result).forEach(([name, q]) => setRotation(c, name, q));
  } else if (object === figure.root && gl.gizmo.mode === 'rotate') {
    c.yaw = model.wrapDegrees(new THREE.Euler().setFromQuaternion(figure.root.quaternion, 'YXZ').y / DEG);
  } else if (object === figure.root && onTrack(c)) {
    // A video character's root is its trajectory plus offsets: the drag moves the offsets.
    const shown = gl.stage.shownOf(c);
    c.position = [c.position[0] + figure.root.position.x - shown.position[0], c.position[1] + figure.root.position.z - shown.position[1]]
      .map(v => Math.round(v * 1000) / 1000);
    c.elevation = Math.round(Math.min(model.MAX_ELEVATION, Math.max(0, c.elevation + figure.root.position.y - shown.elevation)) * 1000) / 1000;
  } else if (object === figure.root) {
    c.position = [Math.round(figure.root.position.x * 1000) / 1000, Math.round(figure.root.position.z * 1000) / 1000];
    c.elevation = Math.round(Math.min(model.MAX_ELEVATION, Math.max(0, figure.root.position.y)) * 1000) / 1000;
  } else if (session.activeJoint) {
    setRotation(c, session.activeJoint, relFromBone(figure, session.activeJoint));
  }
  poseCharacter(c);
  changed();
}
function pick(event) {
  const r = $('[data-pe-viewer]').getBoundingClientRect(), x = event.clientX - r.left, y = event.clientY - r.top;
  const hit = gl.screenJoints.filter(s => Math.hypot(s.x - x, s.y - y) <= s.r).sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))[0];
  if (hit) return select(hit.id, hit.name);
  const [vw, vh] = viewerSize();
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(x / vw * 2 - 1, -(y / vh) * 2 + 1), viewCamera(vw, vh));
  const meshes = gl.stage.entries().filter(e => e.character.visible).map(e => e.figure.mesh);
  const mesh = ray.intersectObjects(meshes, false)[0]?.object;
  const entry = mesh && gl.stage.entries().find(e => e.figure.mesh === mesh);
  if (entry) return select(entry.character.id, entry.character.id === session.activeCharId ? session.activeJoint : null);
  select(session.activeCharId, null);
}

// ---------------------------------------------------------------- views
function enterCameraView() {
  const s = shot();
  gl.syncing = true;
  gl.freeCam.position.set(...s.position); gl.orbit.target.set(...s.target); gl.orbit.update();
  gl.syncing = false;
}
function syncShotFromView() {
  const s = shot();
  s.position = gl.freeCam.position.toArray().map(v => Math.round(v * 1000) / 1000);
  s.target = gl.orbit.target.toArray().map(v => Math.round(v * 1000) / 1000);
  rebuildHelpers();
  changed();
}
function setView(next) {
  if (next === ui.view) return;
  if (gl) {
    if (next === 'camera') { gl.freeSaved = {position: gl.freeCam.position.clone(), target: gl.orbit.target.clone()}; ui.view = 'camera'; enterCameraView(); }
    else {
      ui.view = 'free';
      if (gl.freeSaved) { gl.syncing = true; gl.freeCam.position.copy(gl.freeSaved.position); gl.orbit.target.copy(gl.freeSaved.target); gl.orbit.update(); gl.syncing = false; }
    }
  } else ui.view = next;
  paintToolbar();
  if (ui.tab === 'camera') renderPanel();
  requestRender();
}

// ---------------------------------------------------------------- outline, panels, toolbar
function renderOutline() {
  $('[data-pe-characters]').innerHTML = view.charactersHtml(scene(), session.activeCharId, session.activeJoint);
  $('[data-pe-cameras]').innerHTML = view.camerasHtml(scene());
  $('[data-pe-add-character]').disabled = scene().characters.length >= model.MAX_CHARACTERS;
  $('[data-pe-add-camera]').disabled = scene().cameras.length >= model.MAX_CAMERAS || !gl;
}
function renderPanel() {
  const c = character();
  const panel = $('[data-pe-panel]');
  const edited = new Set(!c ? [] : onTrack(c) ? Object.keys(keyAt(c, currentFrame())?.rotations || {}) : Object.keys(c.rotations));
  const [width, height] = model.outputSize(session.node.output.size, shot().aspect);
  panel.innerHTML = ui.tab === 'pose' ? view.posePanel({character: c, joint: session.activeJoint, euler: c && session.activeJoint ? relEuler(c, session.activeJoint) : [0, 0, 0], edited, track: onTrack(c)})
    : ui.tab === 'character' ? view.characterPanel({character: c, count: scene().characters.length, missingBody: Boolean(c && gl?.missingBodies.has(c.body))})
      : ui.tab === 'camera' ? view.cameraPanel({shot: shot(), count: scene().cameras.length, inCameraView: ui.view === 'camera'})
        : view.outputPanel({node: session.node, width, height});
  $$('[data-pe-tab]').forEach(b => b.classList.toggle('is-active', b.dataset.peTab === ui.tab));
  if (ui.tab === 'output') paintPassThumbs();
}
let thumbsToken = 0;
async function paintPassThumbs() {
  const token = ++thumbsToken;
  for (const pass of Object.keys(model.PASSES)) {
    try {
      const {canvas} = await renderNode(session.node, {pass, maxSide: 96, lod: 'low'});
      const target = token === thumbsToken && root.querySelector(`[data-pe-pass-thumb="${pass}"]`);
      if (!target) return;
      const ctx = target.getContext('2d');
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 96, 96);
      ctx.drawImage(canvas, (96 - canvas.width) / 2, (96 - canvas.height) / 2);
    } catch (_error) { return; }
  }
}
function syncPanelValues() {
  const c = character();
  if (ui.tab !== 'pose' || !c) return;
  const set = (key, value) => root.querySelectorAll(`[data-pe-input="${key}"]`).forEach(el => { if (document.activeElement !== el) el.value = value; });
  if (session.activeJoint) { const [x, y, z] = relEuler(c, session.activeJoint); set('rx', x); set('ry', y); set('rz', z); }
  set('px', c.position[0].toFixed(2)); set('py', c.elevation.toFixed(2)); set('pz', c.position[1].toFixed(2)); set('yaw', Math.round(c.yaw));
  const edited = onTrack(c) ? keyAt(c, currentFrame())?.rotations || {} : c.rotations;
  root.querySelectorAll('[data-pe-joint]').forEach(b => b.classList.toggle('is-edited', Boolean(edited[b.dataset.peJoint])));
}
function paintSelectionLabel() {
  const c = character();
  $('[data-pe-selection-label]').textContent = c ? `${c.name}${session.activeJoint ? ' · ' + model.jointLabel(session.activeJoint) : ''} · ${scene().characters.length} 角色 · 77 关节` : '未选中';
}
function paintToolbar() {
  const on = (sel, active) => { const b = $(sel); if (b) { b.classList.toggle('is-active', active); b.setAttribute('aria-pressed', String(active)); } };
  $$('[data-pe-tool]').forEach(b => b.classList.toggle('is-active', b.dataset.peTool === ui.tool));
  $$('[data-pe-space]').forEach(b => b.classList.toggle('is-active', b.dataset.peSpace === ui.space));
  $$('[data-pe-view]').forEach(b => b.classList.toggle('is-active', b.dataset.peView === ui.view));
  $$('[data-pe-pass]').forEach(b => b.classList.toggle('is-active', b.dataset.pePass === ui.pass));
  on('[data-pe-toggle="snap"]', ui.snap); on('[data-pe-toggle="joints"]', ui.joints); on('[data-pe-toggle="hands"]', ui.hands); on('[data-pe-toggle="reference"]', ui.reference);
  $('[data-pe-toggle="reference"]').hidden = !session.references.length && !(session.videos.length && sequenceState());
}
async function renderLibrary() {
  $('[data-pe-library]').innerHTML = view.libraryHtml(null);
  try { $('[data-pe-library]').innerHTML = view.libraryHtml(await presetThumbnails()); } catch (_error) { /* labels stay usable */ }
}

// ---------------------------------------------------------------- actions
function applyAction(action) {
  const c = character();
  if (action === 'reset-joint' && c && session.activeJoint && !c.locked) {
    // On a video character this drops the joint's keyframe here, back to the recognised rotation.
    if (onTrack(c)) { const key = keyAt(c, currentFrame()); if (key) delete key.rotations[session.activeJoint]; c.keys = c.keys.filter(k => Object.keys(k.rotations).length); }
    else delete c.rotations[session.activeJoint];
    poseCharacter(c);
  } else if (action === 'mirror-joint' && c && session.activeJoint && !c.locked) {
    const other = model.mirrorName(session.activeJoint);
    if (other !== session.activeJoint) setRotation(c, other, model.mirrorQuat(rotationsOf(c)[session.activeJoint] || model.IDENTITY));
    poseCharacter(c);
  } else if (action === 'mirror-all' && c && !c.locked) {
    if (onTrack(c)) keyAll(c, model.mirrorRotations(rotationsOf(c)));
    else c.rotations = model.mirrorRotations(c.rotations);
    c.hands = {left: c.hands.right, right: c.hands.left};
    poseCharacter(c);
  } else if (action === 'delete-character' && c && scene().characters.length > 1) {
    scene().characters = scene().characters.filter(x => x.id !== c.id);
    session.activeCharId = scene().characters[0].id; session.activeJoint = null;
    gl?.stage.sync(scene()); attachGizmo();
    return changed({history: true, panel: true, outline: true, immediate: true});
  } else if (action === 'toggle-camera-view') { setView(ui.view === 'camera' ? 'free' : 'camera'); return; }
  else if (action === 'camera-from-view' && gl) {
    const s = shot();
    s.position = gl.freeCam.position.toArray().map(v => Math.round(v * 1000) / 1000);
    s.target = gl.orbit.target.toArray().map(v => Math.round(v * 1000) / 1000);
    rebuildHelpers();
    return changed({history: true, panel: true, outline: true});
  } else if (action === 'delete-camera' && scene().cameras.length > 1) {
    scene().cameras = scene().cameras.filter(x => x.id !== scene().activeCameraId);
    scene().activeCameraId = scene().cameras[0].id;
    if (ui.view === 'camera' && gl) enterCameraView();
    rebuildHelpers();
    return changed({history: true, panel: true, outline: true, immediate: true});
  } else return;
  changed({history: true, panel: true, outline: true});
}
function onPanelInput(event) {
  const key = event.target.dataset.peInput;
  if (!key) return;
  const c = character(), s = shot(), value = parseFloat(event.target.value);
  root.querySelectorAll(`[data-pe-input="${key}"]`).forEach(el => { if (el !== event.target && el.type !== 'text' && el.type !== 'checkbox') el.value = event.target.value; });
  if (['rx', 'ry', 'rz'].includes(key) && c && session.activeJoint && !c.locked) {
    const [x, y, z] = ['rx', 'ry', 'rz'].map(k => parseFloat(root.querySelector(`[data-pe-input="${k}"]`).value) || 0);
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(x * DEG, y * DEG, z * DEG, 'XYZ'));
    setRotation(c, session.activeJoint, [q.x, q.y, q.z, q.w]);
    poseCharacter(c);
  } else if ((key === 'px' || key === 'pz') && c && Number.isFinite(value)) { c.position[key === 'px' ? 0 : 1] = value; poseCharacter(c); }
  else if (key === 'py' && c && Number.isFinite(value)) { c.elevation = Math.min(model.MAX_ELEVATION, Math.max(0, value)); poseCharacter(c); }
  else if (key === 'yaw' && c && Number.isFinite(value)) { c.yaw = value; poseCharacter(c); }
  else if (key === 'height' && c && Number.isFinite(value)) { c.height = Math.round(value); poseCharacter(c); }
  else if (key === 'name' && c) { c.name = event.target.value.slice(0, 16) || c.name; renderOutline(); paintSelectionLabel(); }
  else if (key === 'camera-name') { s.name = event.target.value.slice(0, 16) || s.name; renderOutline(); }
  else if (key === 'focal' && Number.isFinite(value)) { s.focalMm = Math.round(value); rebuildHelpers(); renderOutline(); }
  else if (key === 'camera-height' && Number.isFinite(value)) {
    s.position[1] = value;
    if (ui.view === 'camera' && gl) enterCameraView();
    rebuildHelpers(); renderOutline();
  } else return;
  changed();
}
function onPanelChange(event) {
  const key = event.target.dataset.peInput;
  const c = character(), s = shot();
  if (key === 'visible' && c) { c.visible = event.target.checked; poseCharacter(c); }
  else if (key === 'grounded' && c) { c.grounded = event.target.checked; poseCharacter(c); }
  else if (key === 'locked' && c) { c.locked = event.target.checked; attachGizmo(); }
  else if (key === 'aspect') s.aspect = event.target.value;
  else if (key === 'lens') s.focalMm = Number(event.target.value);
  else if (key === 'size') session.node.output.size = event.target.value;
  else if (key === 'openpose-hands') session.node.settings.openposeHands = event.target.checked;
  else if (['rx', 'ry', 'rz', 'px', 'py', 'pz', 'yaw', 'height', 'focal', 'camera-height', 'name', 'camera-name'].includes(key)) return changed({history: true, outline: true});
  else return;
  rebuildHelpers();
  changed({history: true, panel: !['visible', 'grounded', 'locked'].includes(key), outline: true, immediate: true});
}
function onPanelClick(event) {
  const c = character();
  const joint = event.target.closest('[data-pe-joint]');
  if (joint) return select(session.activeCharId, joint.dataset.peJoint);
  const facing = event.target.closest('[data-pe-facing]');
  if (facing && c) {
    c.yaw = model.facingYaw(c, shot().position, Number(facing.dataset.peFacing));
    poseCharacter(c);
    attachGizmo();
    return changed({history: true, panel: true});
  }
  const body = event.target.closest('[data-pe-body]');
  if (body && c && body.dataset.peBody !== c.body) {
    c.body = body.dataset.peBody;
    syncBodies();
    return changed({history: true, panel: true, outline: true, immediate: true});
  }
  const color = event.target.closest('[data-pe-color]');
  if (color && c) { c.color = color.dataset.peColor; poseCharacter(c); return changed({history: true, panel: true, outline: true}); }
  const kind = event.target.closest('[data-pe-output-kind]');
  if (kind) { session.node.output.kind = kind.dataset.peOutputKind; return changed({history: true, panel: true, immediate: true}); }
  const pass = event.target.closest('[data-pe-output-pass]');
  if (pass) { session.node.output.pass = pass.dataset.peOutputPass; return changed({history: true, panel: true, immediate: true}); }
  const width = event.target.closest('[data-pe-openpose-width]');
  if (width) { session.node.settings.openposeWidth = width.dataset.peOpenposeWidth; return changed({history: true, panel: true}); }
  const background = event.target.closest('[data-pe-background]');
  if (background) { session.node.settings.background = background.dataset.peBackground; return changed({history: true, panel: true}); }
  for (const side of ['left', 'right']) {
    const hand = event.target.closest(`[data-pe-hand-${side}]`);
    if (hand && c && !c.locked) {
      // Non-destructive: a preset hides the finger rotations, picking 识别 / 自定义 shows them again.
      c.hands[side] = hand.dataset[side === 'left' ? 'peHandLeft' : 'peHandRight'];
      poseCharacter(c);
      return changed({history: true, panel: true});
    }
  }
  const action = event.target.closest('[data-pe-action]');
  if (action && !action.disabled) applyAction(action.dataset.peAction);
}
function addCharacter() {
  const list = scene().characters;
  if (list.length >= model.MAX_CHARACTERS) return;
  const c = model.createCharacter(list.length);
  const used = new Set(list.map(x => x.color));
  c.color = model.SWATCHES.find(x => !used.has(x)) || c.color;
  list.push(c);
  gl?.stage.sync(scene());
  select(c.id, null);
  changed({history: true, outline: true, immediate: true});
}
function addCamera() {
  if (!gl || scene().cameras.length >= model.MAX_CAMERAS) return;
  const s = model.createCamera(scene().cameras.length, {position: gl.freeCam.position.toArray().map(v => Math.round(v * 1000) / 1000),
    target: gl.orbit.target.toArray().map(v => Math.round(v * 1000) / 1000), focalMm: 50, aspect: shot().aspect});
  scene().cameras.push(s);
  scene().activeCameraId = s.id;
  rebuildHelpers();
  changed({history: true, panel: true, outline: true, immediate: true});
}
function applyPreset(id) {
  const c = character();
  const preset = model.PRESETS.find(p => p.id === id);
  if (!c || c.locked || !preset) return;
  if (onTrack(c)) {
    // On a video frame a preset is a keyframe of the body joints; the recognised heading and fingers stay.
    const shown = rotationsOf(c);
    keyAll(c, Object.fromEntries(model.SOMA_JOINTS.slice(2).filter(n => !/Hand(Thumb|Index|Middle|Ring|Pinky)/.test(n))
      .map(n => [n, preset.rotations[n] || model.IDENTITY])));
    if (preset.facing != null) c.yaw = model.facingYaw({...c, rotations: {Hips: shown.Hips}}, shot().position, preset.facing);
  } else model.applyPreset(c, preset, shot().position);
  poseCharacter(c);
  attachGizmo();
  changed({history: true, panel: true});
}
async function exportToNode() {
  if (!session || session.exporting) return;
  session.exporting = true; session.exportError = '';
  paintStatus();
  try { await session.onExport(); }
  catch (error) { session.exportError = error?.message || '导出失败'; }
  finally { if (session) { session.exporting = false; paintStatus(); } }
}

// ---------------------------------------------------------------- events (bound once)
function bind() {
  root.addEventListener('click', event => {
    if (!session) return;
    const t = event.target;
    if (t.closest('[data-pe-close]')) return close();
    const b = t.closest('button');
    if (!b || b.disabled) return;
    if (b.dataset.pePass) { ui.pass = b.dataset.pePass; paintToolbar(); requestRender(); }
    else if (b.dataset.peTool) { ui.tool = b.dataset.peTool; paintToolbar(); attachGizmo(); }
    else if (b.dataset.peSpace) { ui.space = b.dataset.peSpace; paintToolbar(); attachGizmo(); }
    else if (b.dataset.peView) setView(b.dataset.peView);
    else if (b.dataset.peToggle) { ui[b.dataset.peToggle] = !ui[b.dataset.peToggle]; paintToolbar(); attachGizmo(); }
    else if (b.dataset.peTab) { ui.tab = b.dataset.peTab; renderPanel(); }
    else if ('peUndo' in b.dataset) undo();
    else if ('peRedo' in b.dataset) redo();
    else if ('peSidebarToggle' in b.dataset) {
      ui.sidebar = !ui.sidebar;
      root.classList.toggle('is-inspector-collapsed', !ui.sidebar);
      b.setAttribute('aria-pressed', String(!ui.sidebar)); b.textContent = ui.sidebar ? '›' : '‹';
      b.title = ui.sidebar ? '收起检查器' : '展开检查器';
      setTimeout(requestRender, 200);
    } else if ('peAddCharacter' in b.dataset) addCharacter();
    else if ('peAddCamera' in b.dataset) addCamera();
    else if (b.dataset.pePreset) applyPreset(b.dataset.pePreset);
    else if ('peResetPose' in b.dataset) {
      const c = character();
      if (onTrack(c) && !c.locked) { c.keys = []; poseCharacter(c); attachGizmo(); changed({history: true, panel: true}); }
      else applyPreset('stand');
    }
    else if ('peExport' in b.dataset) exportToNode();
    else if (b.dataset.peCharacterEye) {
      const c = scene().characters.find(x => x.id === b.dataset.peCharacterEye);
      if (c) { c.visible = !c.visible; poseCharacter(c); changed({history: true, outline: true, immediate: true}); }
    } else if (b.dataset.peCharacterLock) {
      const c = scene().characters.find(x => x.id === b.dataset.peCharacterLock);
      if (c) { c.locked = !c.locked; attachGizmo(); changed({history: true, outline: true}); }
    }
  });
  root.addEventListener('click', event => {
    if (!session || event.target.closest('button')) return;
    const row = event.target.closest('[data-pe-character]');
    if (row) return select(row.dataset.peCharacter, row.dataset.peCharacter === session.activeCharId ? session.activeJoint : null);
    const cam = event.target.closest('[data-pe-camera]');
    if (cam) {
      scene().activeCameraId = cam.dataset.peCamera;
      if (ui.view === 'camera' && gl) enterCameraView();
      rebuildHelpers();
      changed({history: true, panel: true, outline: true, immediate: true});
    }
  });
  const panel = $('[data-pe-panel]');
  panel.addEventListener('input', event => session && onPanelInput(event));
  panel.addEventListener('change', event => session && onPanelChange(event));
  panel.addEventListener('click', event => session && onPanelClick(event));
  const viewer = $('[data-pe-viewer]');
  let down = null;
  viewer.addEventListener('pointerdown', event => { down = event.target.matches('[data-pe-canvas]') ? {x: event.clientX, y: event.clientY, button: event.button} : null; });
  viewer.addEventListener('pointerup', event => {
    const start = down; down = null;
    if (!gl || !start || start.button !== 0 || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4 || gl.gizmo.dragging || gl.gizmo.axis) return;
    pick(event);
  });
  $('[data-pe-axes]').addEventListener('click', event => {
    const r = event.currentTarget.getBoundingClientRect(), x = (event.clientX - r.left) * 128 / r.width, y = (event.clientY - r.top) * 128 / r.height;
    const hit = [...axisHits].reverse().find(it => Math.hypot(it.x - x, it.y - y) < 16);
    if (hit) snapView(hit.v);
  });
  document.addEventListener('keydown', onKey, true);
}
function onKey(event) {
  if (!session || root.hidden) return;
  if (event.target.closest?.('input, select, textarea, [contenteditable="true"]') || document.querySelector('.desk-select-menu:not([hidden])')?.contains(event.target)) return;
  const key = event.key.toLowerCase(), mod = event.metaKey || event.ctrlKey;
  if (mod && key === 'z') { event.preventDefault(); event.stopPropagation(); event.shiftKey ? redo() : undo(); return; }
  if (mod || event.altKey) return;
  const c = character();
  const actions = {
    r: () => { ui.tool = 'rotate'; paintToolbar(); attachGizmo(); },
    g: () => { ui.tool = 'translate'; paintToolbar(); attachGizmo(); },
    q: () => { ui.tool = 'select'; paintToolbar(); attachGizmo(); },
    l: () => { ui.space = ui.space === 'local' ? 'world' : 'local'; paintToolbar(); attachGizmo(); },
    m: () => session.activeJoint && applyAction('mirror-joint'),
    f: () => {
      if (!gl || !c || ui.view === 'camera') return;
      const target = jointWorld(figureOf(c), session.activeJoint || 'Spine2');
      const offset = gl.freeCam.position.clone().sub(gl.orbit.target).setLength(session.activeJoint ? 1.6 : 3.4);
      gl.orbit.target.copy(target); gl.freeCam.position.copy(target).add(offset); gl.orbit.update();
    },
    0: () => setView(ui.view === 'camera' ? 'free' : 'camera'),
    1: () => snapView(new THREE.Vector3(0, 0, 1)), 3: () => snapView(new THREE.Vector3(1, 0, 0)), 7: () => snapView(new THREE.Vector3(0, 1, 0)),
    escape: () => session.activeJoint ? select(session.activeCharId, null) : close(),
    ...(gl?.sequence && sequenceState() ? {' ': () => gl.timeline.toggle(), arrowleft: () => gl.timeline.step(-1), arrowright: () => gl.timeline.step(1),
      home: () => gl.timeline.home(), end: () => gl.timeline.end(), k: keyFrame} : {}),
  }[key];
  if (actions) { event.preventDefault(); event.stopPropagation(); actions(); }
}

// ---------------------------------------------------------------- public API
function ensureRoot() {
  if (root) return;
  root = document.createElement('div');
  root.className = 'desk-pose-editor';
  root.hidden = true;
  root.innerHTML = view.shellHtml();
  document.body.appendChild(root);
  bind();
}
function open({node, references = [], videos = [], onChange, onExport, onClose}) {
  ensureRoot();
  if (session) close();
  model.normalize(node);
  session = {node, references: references.filter(r => r?.url), videos: videos.filter(v => v?.url), onChange, onExport, onClose,
    undo: [], redo: [], baseline: '', sequenceError: '',
    activeCharId: node.scene.characters[0]?.id || '', activeJoint: null, exporting: false, exportError: ''};
  session.baseline = snapshotState();
  ui.reference = (session.references.length > 0 || session.videos.length > 0) && ui.reference;
  $('[data-pe-node-title]').textContent = node.title;
  const reference = $('[data-pe-reference]');
  if (session.references[0]) reference.src = session.references[0].url; else reference.removeAttribute('src');
  loadReferenceVideo(session);
  $('[data-pe-loading]').hidden = false;
  root.hidden = false;
  root.classList.toggle('is-inspector-collapsed', !ui.sidebar);
  document.body.classList.add('desk-pose-editor-open');
  paintToolbar(); paintHistory(); paintStatus(); renderOutline(); renderPanel(); paintSelectionLabel(); renderLibrary();
  startViewport().catch(error => {
    const notice = $('[data-pe-loading]');
    notice.hidden = false;
    notice.innerHTML = `<strong>人偶加载失败</strong><span>${String(error?.message || error).replace(/[<>&]/g, '')}</span>`;
  });
  $('[data-pe-viewer]').focus({preventScroll: true});
}
function close() {
  if (!session) return;
  clearTimeout(changeTimer);
  const done = session;
  session = null;
  stopViewport();
  const video = $('[data-pe-reference-video]');
  video.removeAttribute('src'); video.load();
  if (done.videoUrl) URL.revokeObjectURL(done.videoUrl);
  root.hidden = true;
  document.body.classList.remove('desk-pose-editor-open');
  done.onChange();
  done.onClose?.();
}
// The canvas controller notifies a finished export so the status and footer stay current.
function exported(node) { if (session?.node === node) { session.exportError = ''; paintStatus(); } }

window.DesktopPoseEditor = Object.freeze({open, close, exported, isOpen: () => Boolean(session), renderNode});
window.dispatchEvent(new CustomEvent('desktop:pose-editor-ready'));
