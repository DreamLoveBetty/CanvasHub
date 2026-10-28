// Pose reference node (poseVersion 2): state model, OpenPose table, export contract, canvas
// controller, transport and page wiring. Synthetic data only; no three.js, WebGL or backend.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {hasCacheKey} = require('./asset_keys.cjs');

const frontend = path.join(__dirname, '../frontend');
const scripts = path.join(frontend, 'scripts');
const read = file => fs.readFileSync(path.join(frontend, file), 'utf8');
function load(files, extra = {}) {
  const sandbox = {window: {}, btoa, atob, globalThis: {}, ...extra};
  for (const file of files) vm.runInNewContext(fs.readFileSync(path.join(scripts, file), 'utf8'), sandbox);
  return sandbox.window;
}
const model = load(['desktop-pose-model.js']).DesktopPoseModel;
const plain = value => JSON.parse(JSON.stringify(value));
const quatAngle = q => 2 * Math.acos(Math.min(1, Math.abs(q[3]))) * 180 / Math.PI;

test('new nodes are normalised to the v2 contract with one character and one camera', () => {
  const node = model.createState();
  assert.equal(node.type, 'pose');
  assert.equal(node.poseVersion, 2);
  assert.equal(node.width, model.WIDTH);
  assert.equal(node.scene.characters.length, 1);
  assert.equal(node.scene.cameras.length, 1);
  assert.equal(node.scene.activeCameraId, node.scene.cameras[0].id);
  assert.equal(node.output.pass, 'openpose');
  assert.equal(node.output.artifactUrl, '');
  assert.ok(node.scene.characters[0].rotations.LeftArm, 'new characters start from the standing preset');
  assert.equal(node.status, 'idle');
});

test('normalisation clamps, drops unknown joints and keeps only protected artifact URLs', () => {
  const node = model.normalize({type: 'pose', scene: {
    characters: [{id: 'char_a', height: 999, position: [1e9, 2], yaw: 720, color: 'red',
      rotations: {LeftArm: [0, 0, 0.5, 0.5], NotAJoint: [0, 0, 1, 0], Root: [0, 1, 0, 0], RightArm: [0, 0, 0, 1], Head: [1, 'x', 0, 0]}}],
    cameras: [{id: 'cam_a', focalMm: 1, aspect: '5:4'}], activeCameraId: 'missing'},
  output: {pass: 'sketch', size: '9999', artifactUrl: 'https://example.com/a.png'}, status: 'exporting'});
  const c = node.scene.characters[0];
  assert.equal(c.height, 200);
  assert.deepEqual(plain(c.position), [10, 2]);
  assert.equal(c.yaw, 180);
  assert.equal(c.color, model.SWATCHES[0]);
  assert.deepEqual(plain(Object.keys(c.rotations)), ['LeftArm']);
  assert.ok(Math.abs(Math.hypot(...c.rotations.LeftArm) - 1) < 1e-6);
  assert.equal(node.scene.cameras[0].focalMm, 14);
  assert.equal(node.scene.cameras[0].aspect, '3:4');
  assert.equal(node.scene.activeCameraId, 'cam_a');
  assert.equal(node.output.pass, 'openpose');
  assert.equal(node.output.size, '1024');
  assert.equal(node.output.artifactUrl, '');
  assert.equal(node.status, 'idle', 'an interrupted export does not survive a reload');
  const exported = model.normalize({type: 'pose', output: {artifactUrl: '/api/pose/export/artifact?id=' + 'a'.repeat(32), width: 768, height: 1024}});
  assert.equal(model.artifactUrl(exported), '/api/pose/export/artifact?id=' + 'a'.repeat(32));
  assert.equal(exported.status, 'exported');
});

test('bodies: presets, recognised shapes and safe fallbacks; the snapshot names the identity source', () => {
  const capture = 'capture:' + 'a'.repeat(32);
  const make = body => model.createCharacter(0, {body});
  assert.deepEqual(plain(['female', 'male', capture, 'toString', 'capture:xyz', undefined].map(b => make(b).body)),
    ['female', 'male', capture, 'neutral', 'neutral', 'neutral'], 'old characters without a body stay neutral');
  assert.equal(make(capture).capturedBody, capture);
  assert.equal(model.createCharacter(0, {body: 'female', capturedBody: capture}).capturedBody, capture, 'switching to a preset keeps the shape');
  assert.deepEqual(plain(['neutral', 'female', capture].map(model.bodyLabel)), ['中性', '女性', '识别体型']);
  const node = model.createState();
  node.scene.characters = [make('neutral'), make('female'), make(capture)];
  assert.deepEqual(plain(model.snapshot(node).people.map(p => p.identity.model)), ['soma', 'anny', 'mhr']);
  assert.equal(model.snapshot(node).people[2].identity.body_id, 'a'.repeat(32));
  const key = model.sceneKey(node);
  node.scene.characters[0].body = 'male';
  assert.notEqual(model.sceneKey(node), key, 'a body change makes the export stale');
});

test('legacy Mixamo/Director nodes are purged with their edges, v2 nodes stay', () => {
  const canvas = {nodes: {old: {id: 'old', type: 'pose', mode: 'director_stage'}, fresh: {id: 'fresh', ...model.createState()},
    img: {id: 'img', type: 'image'}}, edges: [{from: 'img', to: 'old'}, {from: 'old', to: 'input'}, {from: 'img', to: 'fresh'}],
    selectedNodeId: 'old', selectedNodeIds: ['old', 'img']};
  assert.equal(model.isLegacy(canvas.nodes.old), true);
  assert.equal(model.purgeLegacy(canvas), 1);
  assert.deepEqual(plain(Object.keys(canvas.nodes).sort()), ['fresh', 'img']);
  assert.deepEqual(plain(canvas.edges), [{from: 'img', to: 'fresh'}]);
  assert.equal(canvas.selectedNodeId, '');
  assert.deepEqual(plain(canvas.selectedNodeIds), ['img']);
  assert.equal(model.purgeLegacy(canvas), 0);
});

test('output size follows the camera aspect and rounds the short side to 8', () => {
  assert.deepEqual(plain(model.outputSize('1024', '1:1')), [1024, 1024]);
  assert.deepEqual(plain(model.outputSize('1024', '3:4')), [768, 1024]);
  assert.deepEqual(plain(model.outputSize('1344', '16:9')), [1344, 760]);
  assert.deepEqual(plain(model.outputSize('2048', '9:16')), [1152, 2048]);
});

test('export key tracks scene, pass, size and settings; dirty until exported with the same key', () => {
  const node = model.createState();
  assert.equal(model.dirty(node), true);
  node.output.artifactUrl = '/api/pose/export/artifact?id=' + 'b'.repeat(32);
  node.output.sceneKey = model.sceneKey(node);
  assert.equal(model.dirty(node), false);
  node.scene.characters[0].yaw = 30;
  assert.equal(model.dirty(node), true);
  node.scene.characters[0].yaw = 0;
  assert.equal(model.dirty(node), false);
  node.settings.openposeHands = false;
  assert.equal(model.dirty(node), true);
});

test('pose library presets use real joints and plausible angles', () => {
  const joints = new Set(model.SOMA_JOINTS);
  assert.equal(model.SOMA_JOINTS.length, 78);
  assert.ok(model.PRESETS.length >= 6);
  for (const preset of model.PRESETS) for (const [name, q] of Object.entries(preset.rotations)) {
    assert.ok(joints.has(name), `${preset.id}: ${name}`);
    assert.ok(quatAngle(q) <= 180.0001);
  }
  const stand = model.presetRotations('stand');
  assert.ok(Math.abs(quatAngle(stand.LeftArm) - 72) < 1e-3);
  assert.deepEqual(plain(model.presetRotations('tpose')), {});
  assert.equal(new Set(model.PRESETS.map(p => p.id)).size, model.PRESETS.length, 'preset ids are unique');
  assert.ok(model.PRESETS.every(p => model.PRESET_GROUPS.includes(p.group)), 'every preset sits in a library group');
  const facing = Object.fromEntries(model.PRESETS.filter(p => p.facing != null).map(p => [p.id, p.facing]));
  assert.deepEqual(plain(facing), {back: 180, leftside: -90, rightside: 90, leftthreequarter: -45, rightthreequarter: 45});
  assert.ok(model.PRESETS.filter(p => p.group !== '朝向').length >= 20, 'common standing, action and seated poses');
});

test('facing: yaw relative to the camera, counting the heading a Hips rotation carries', () => {
  const at = (position, hipsYaw = 0) => model.createCharacter(0, {position, rotations: hipsYaw ? {Hips: model.axisAngle([0, 1, 0], hipsYaw)} : {}});
  const front = [0, 1.2, 4];
  assert.equal(model.facingYaw(at([0, 0]), front, 0), 0, 'camera on +Z: facing it needs no turn');
  assert.equal(model.facingYaw(at([0, 0]), front, 180), -180, 'back to the camera');
  assert.equal(model.facingYaw(at([0, 0]), front, 90), 90, 'right side towards the camera');
  assert.equal(model.facingYaw(at([0, 0]), [4, 1.2, 0], 0), 90, 'camera on +X');
  assert.equal(model.facingYaw(at([2, 2]), [2, 1.2, 6], -90), -90, 'measured from the character, not the origin');
  assert.equal(model.facingYaw(at([0, 0], 60), front, 0), -60, 'a recognised heading in Hips is compensated');
  assert.deepEqual(plain([190, -190, 540, 45.04].map(model.wrapDegrees)), [-170, 170, -180, 45]);
});

test('presets keep the current heading; facing presets turn towards the camera', () => {
  const preset = id => model.PRESETS.find(p => p.id === id);
  const c = model.createCharacter(0, {yaw: 30, rotations: {Hips: model.axisAngle([0, 1, 0], 40), LeftArm: model.axisAngle([0, 0, 1], -10)}});
  model.applyPreset(c, preset('hips'), [0, 1.2, 4]);
  assert.equal(c.yaw, 70, 'the Hips heading folds into yaw so the character does not spin round');
  assert.equal(c.rotations.Hips, undefined);
  model.applyPreset(c, preset('back'), [0, 1.2, 4]);
  assert.equal(c.yaw, -180);
  assert.deepEqual(plain(c.rotations), plain(model.presetRotations('stand')));
});

test('mirroring swaps sides and is its own inverse', () => {
  const rotations = model.presetRotations('wave');
  const mirrored = model.mirrorRotations(rotations);
  assert.ok(mirrored.LeftArm && mirrored.LeftForeArm, 'right-arm wave becomes a left-arm wave');
  const back = model.mirrorRotations(mirrored);
  for (const [name, q] of Object.entries(rotations)) back[name].forEach((v, i) => assert.ok(Math.abs(v - q[i]) < 1e-12));
});

test('hand shapes curl finger joints only and open clears them', () => {
  const fist = model.handRotations('Left', 'fist');
  assert.ok(Object.keys(fist).length === 15);
  assert.ok(Object.keys(fist).every(name => /^LeftHand(Thumb|Index|Middle|Ring|Pinky)\d$/.test(name)));
  assert.deepEqual(plain(model.handRotations('Right', 'open')), {});
  const left = model.handRotations('Left', 'relaxed'), right = model.handRotations('Right', 'relaxed');
  assert.ok(Math.abs(left.LeftHandIndex2[2] + right.RightHandIndex2[2]) < 1e-12, 'curl direction mirrors between hands');
});

test('OpenPose COCO-18 table: 18 points, 17 limbs, 21-point hands on SOMA joints', () => {
  const {body, derived, limbs, colors, hand} = model.OPENPOSE;
  const joints = new Set(model.SOMA_JOINTS);
  assert.equal(body.length, 18);
  assert.equal(limbs.length, 17);
  assert.equal(colors.length, 18);
  for (const name of body) assert.ok(joints.has(name) || derived.includes(name), name);
  assert.deepEqual(plain(body.slice(2, 8)), ['RightArm', 'RightForeArm', 'RightHand', 'LeftArm', 'LeftForeArm', 'LeftHand']);
  for (const [a, b] of limbs) assert.ok(a >= 0 && a < 18 && b >= 0 && b < 18);
  for (const side of ['Left', 'Right']) {
    const points = hand(side);
    assert.equal(points.length, 21);
    for (const name of points) assert.ok(joints.has(name), name);
  }
});

test('snapshot is the snake_case backend contract with 77 axis-angle rotations per person', () => {
  const node = model.createState();
  node.scene.characters.push(model.createCharacter(1, {visible: false}));
  const snap = model.snapshot(node, {[node.scene.characters[0].id]: {transl: [0.1, 0.9, 0.2], hips: [0, 0.7071068, 0, 0.7071068]}});
  assert.equal(snap.skeleton, 'soma77');
  assert.equal(snap.people.length, 1, 'hidden characters are not exported');
  const person = snap.people[0];
  assert.deepEqual(plain(person.frames.transl), [[0.1, 0.9, 0.2]]);
  const bytes = Buffer.from(person.frames.rotations.replace(/^base64:/, ''), 'base64');
  const floats = new Float32Array(bytes.buffer, bytes.byteOffset, bytes.length / 4);
  assert.equal(floats.length, 77 * 3);
  assert.ok(Math.abs(floats[1] - Math.PI / 2) < 1e-5, 'Hips carries the yaw-folded global rotation');
  const leftArm = model.SOMA_JOINTS.indexOf('LeftArm') - 1;
  assert.ok(Math.abs(Math.hypot(floats[leftArm * 3], floats[leftArm * 3 + 1], floats[leftArm * 3 + 2]) - 72 * Math.PI / 180) < 1e-4);
  assert.deepEqual(plain(Object.keys(snap.cameras[0]).sort()), ['aspect', 'focal_mm', 'height', 'id', 'label', 'position', 'target', 'width']);
  assert.equal(snap.active_camera, node.scene.activeCameraId);
});

test('transport only accepts PNG data URLs and protected artifact URLs', async () => {
  const calls = [];
  const api = {json: async (url, options) => { calls.push([url, options]); return {url: '/api/pose/export/artifact?id=' + 'c'.repeat(32), width: 4, height: 3}; },
    request: async url => ({ok: true, arrayBuffer: async () => new ArrayBuffer(8), url})};
  const transport = load(['desktop-pose-model.js', 'desktop-pose-api.js'], {api}).DesktopPoseAPI;
  await assert.rejects(transport.exportImage({image: 'data:image/jpeg;base64,AAAA', pass: 'mask'}), /PNG/);
  const result = await transport.exportImage({image: 'data:image/png;base64,AAAA', pass: 'mask', camera: '机位 1', scene: {people: []}});
  assert.equal(result.width, 4);
  assert.deepEqual(JSON.parse(calls[0][1].body), {image: 'data:image/png;base64,AAAA', pass: 'mask', camera: '机位 1', scene: {people: []}});
  await assert.rejects(transport.glb('high'), /精细度/);
  assert.equal((await transport.glb('mid')).byteLength, 8);
  const urls = [];
  const bodies = load(['desktop-pose-model.js', 'desktop-pose-api.js'], {api: {request: async url => { urls.push(url); return {ok: true, arrayBuffer: async () => new ArrayBuffer(4)}; }}}).DesktopPoseAPI;
  await bodies.glb('mid', 'female');
  await bodies.glb('mid', 'capture:' + 'e'.repeat(32));
  assert.deepEqual(urls, ['/api/pose/glb?lod=mid&body=female', '/api/pose_capture/body?id=' + 'e'.repeat(32)]);
  for (const body of ['toString', 'capture:../x', '../neutral']) await assert.rejects(bodies.glb('low', body), /体型/);
  assert.equal(transport.isArtifactUrl('/api/pose/export/artifact?id=' + 'd'.repeat(32)), true);
  assert.equal(transport.isArtifactUrl('https://example.com/x.png'), false);
  const bad = load(['desktop-pose-api.js'], {api: {json: async () => ({url: '/elsewhere'})}}).DesktopPoseAPI;
  await assert.rejects(bad.exportImage({image: 'data:image/png;base64,AAAA', pass: 'mask'}), /无效地址/);
});

function fakeElement() {
  const nodes = new Map();
  const make = () => ({hidden: false, textContent: '', disabled: false, dataset: {}, attrs: {}, classList: {toggle() {}},
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; }, querySelector: () => make(), innerHTML: ''});
  const el = {listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; },
    querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, make()); return nodes.get(selector); },
    querySelectorAll: () => [make()]};
  return el;
}

test('canvas controller exports through the editor engine and records a matching export key', async () => {
  const win = load(['desktop-pose-model.js', 'desktop-pose-view.js']);
  const controllerWin = load(['desktop-canvas-pose.js'], {AbortController, setTimeout});
  const node = {id: 'pose_1', ...win.DesktopPoseModel.createState()};
  const canvas = {nodes: {pose_1: node}, edges: []};
  const el = fakeElement();
  let saved = 0; const messages = [];
  const exports = [];
  const engine = {renderNode: async () => ({canvas: {toDataURL: () => 'data:image/png;base64,AAAA'}, width: 768, height: 1024,
    shot: node.scene.cameras[0], world: {}}), exported: () => {}, isOpen: () => false};
  controllerWin.DesktopPoseEditor = engine;
  const controller = controllerWin.DesktopCanvasPose.create({model: win.DesktopPoseModel,
    api: {status: async () => ({ready: true}), capture: {status: async () => ({ready: false, message: '未安装'})},
      exportImage: async body => { exports.push(body); return {url: '/api/pose/export/artifact?id=' + 'e'.repeat(32), width: 768, height: 1024}; }},
    view: {html: () => '', renderFields() {}, paint() {}}, capture: {active: () => false, cancel() {}}, confirm: () => true,
    getCanvas: () => canvas, getNodeState: id => canvas.nodes[id], getNodeElement: () => el,
    saveState: () => { saved++; }, connectedImages: () => [], showMessage: m => messages.push(m)});
  controller.reconcile();
  await new Promise(resolve => setTimeout(resolve, 0));
  el.listeners.click({target: {closest: selector => selector.startsWith('[data-pose-export]') ? {} : null}, stopPropagation() {}});
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(messages, []);
  assert.equal(exports.length, 1);
  assert.equal(exports[0].pass, 'openpose');
  assert.equal(exports[0].scene.skeleton, 'soma77');
  assert.equal(node.output.artifactUrl, '/api/pose/export/artifact?id=' + 'e'.repeat(32));
  assert.equal(win.DesktopPoseModel.dirty(node), false);
  assert.equal(node.status, 'exported');
  assert.ok(saved >= 1);
  const legacy = {nodes: {x: {id: 'x', type: 'pose'}}, edges: []};
  assert.equal(controller.purgeLegacy(legacy), 1);
  assert.match(messages.at(-1), /已移除 1 个旧版姿态节点/);
});

// A recognition result in the backend contract: Hips turned 90 degrees about Y, a 45-degree left elbow.
function captureResult(people = 1) {
  const values = new Float32Array(77 * 3);
  values[1] = Math.PI / 2;
  const elbow = model.SOMA_JOINTS.indexOf('LeftForeArm') - 1;
  values[elbow * 3 + 1] = Math.PI / 4;
  const rotations = 'base64:' + Buffer.from(values.buffer).toString('base64');
  return {version: 1, skeleton: 'soma77', people: Array.from({length: people}, (_, i) => ({label: `角色 ${'ABCDEFG'[i]}`, color: '#3e8ef7',
    height_cm: 168 + i, floor_offset: i ? 0.4567 : 0, ...(i ? {} : {body_id: 'f'.repeat(32)}), frames: {count: 1, transl: [[0.4 * i, 0.9, -1]], rotations}})),
    cameras: [{id: 'photo', position: [0, 1.2, 3], target: [0, 1, 0], focal_mm: 50, aspect: '2:3', width: 720, height: 1080}]};
}

test('recognition results become editable characters and the photo camera', () => {
  const node = model.createState();
  node.scene.cameras[0].name = '我的机位';
  assert.equal(model.hasCustomPose(node), false);
  model.applyCapture(node, captureResult(2));
  const [a, b] = node.scene.characters;
  assert.equal(node.scene.characters.length, 2);
  assert.deepEqual(plain([a.height, b.height, b.position]), [168, 169, [0.4, -1]]);
  assert.deepEqual(plain([a.elevation, b.elevation]), [0, 0.457], 'people the photo puts above the floor keep that lift');
  assert.deepEqual(plain([a.body, a.capturedBody, b.body]), ['capture:' + 'f'.repeat(32), 'capture:' + 'f'.repeat(32), 'neutral'],
    'recognised shapes become the default body; people without one keep the neutral mannequin');
  assert.equal(model.createCharacter(0, {elevation: 9}).elevation, model.MAX_ELEVATION);
  assert.equal(model.createCharacter(0, {elevation: -1}).elevation, 0);
  assert.ok(Math.abs(quatAngle(a.rotations.Hips) - 90) < 1e-3);
  assert.ok(Math.abs(quatAngle(a.rotations.LeftForeArm) - 45) < 1e-3);
  assert.equal(a.rotations.Spine1, undefined, 'identity joints stay implicit');
  assert.deepEqual(plain(a.hands), {left: 'captured', right: 'captured'}, 'recognized fingers are not overridden by a hand preset');
  assert.equal(node.scene.activeCameraId, model.PHOTO_CAMERA);
  assert.deepEqual(plain(node.scene.cameras.map(c => c.name)), ['照片机位', '我的机位']);
  assert.equal(node.scene.cameras[0].aspect, '2:3');
  model.applyCapture(node, captureResult(1));
  assert.equal(node.scene.cameras.filter(c => c.id === model.PHOTO_CAMERA).length, 1, 'a new recognition replaces the photo camera');
  assert.equal(model.hasCustomPose(node), true);
  assert.throws(() => model.applyCapture(model.createState(), {skeleton: 'soma77', people: []}), /没有识别到人物/);
  assert.throws(() => model.applyCapture(model.createState(), {...captureResult(), people: [{frames: {rotations: 'base64:AAAAAAAAAAA='}}]}), /关节数/);
  assert.throws(() => model.applyCapture(model.createState(), {...captureResult(), people: [{frames: {rotations: 'base64:AAAA'}}]}), /格式无效/);
});

test('hand presets replace a hand\'s fingers, captured keeps them; older scenes keep the hands they showed', () => {
  const finger = {LeftHandIndex2: model.axisAngle([0, 0, 1], 50), RightHandThumb1: model.axisAngle([0, 1, 0], 30), LeftForeArm: model.axisAngle([0, 1, 0], 40)};
  const c = model.createCharacter(0, {rotations: finger, hands: {left: 'captured', right: 'captured'}});
  const keep = model.effectiveRotations(c);
  assert.deepEqual(plain(Object.keys(keep).sort()), ['LeftForeArm', 'LeftHandIndex2', 'RightHandThumb1']);
  c.hands = {left: 'fist', right: 'open'};
  const shaped = model.effectiveRotations(c);
  assert.deepEqual(plain(shaped.LeftHandIndex2), plain(model.handRotations('Left', 'fist').LeftHandIndex2), 'the preset wins over the recognised finger');
  assert.equal(shaped.RightHandThumb1, undefined, 'open: straight fingers, the recognised ones hidden');
  assert.deepEqual(plain(shaped.LeftForeArm), plain(c.rotations.LeftForeArm), 'arms are not hand joints');
  assert.ok(c.rotations.LeftHandIndex2, 'non-destructive: the recognised fingers stay underneath');
  const curl = shape => quatAngle(model.handRotations('Left', shape).LeftHandIndex3);
  assert.ok(curl('relaxed') < curl('grip') && curl('grip') < curl('fist'), 'grip sits between relaxed and fist');
  // Characters saved before hands could be captured: explicit fingers always showed, video fingers too.
  assert.deepEqual(plain(model.createCharacter(0, {rotations: finger, hands: {left: 'open', right: 'fist'}}).hands), {left: 'captured', right: 'captured'});
  assert.deepEqual(plain(model.createCharacter(0, {hands: {left: 'fist', right: 'bogus'}}).hands), {left: 'fist', right: 'relaxed'});
  const legacyTrack = model.createCharacter(0, {track: {person: 0, start: 0, count: 5}, hands: {left: 'fist', right: 'open'}});
  assert.deepEqual(plain(legacyTrack.hands), {left: 'captured', right: 'captured'});
  const chosen = model.createCharacter(0, {...plain(legacyTrack), hands: {left: 'fist', right: 'grip'}});
  assert.deepEqual(plain(chosen.hands), {left: 'fist', right: 'grip'}, 'a preset picked after the upgrade is kept on reload');
  // Bookkeeping does not mark exported nodes changed; a static preset relaxes a hand it left without fingers.
  const node = model.createState();
  const stripped = model.createState(); stripped.scene = plain(node.scene); stripped.output = node.output; stripped.settings = node.settings;
  stripped.scene.characters.forEach(x => delete x.handsVersion);
  assert.equal(model.sceneKey(stripped), model.sceneKey(node));
  const posed = model.createCharacter(0, {rotations: finger, hands: {left: 'captured', right: 'captured'}});
  model.applyPreset(posed, model.PRESETS[0], [0, 1.2, 4]);
  assert.deepEqual(plain(posed.hands), {left: 'relaxed', right: 'relaxed'});
});

// A recognised video in the backend contract: one person walking +X for 20 frames from frame 5,
// the left forearm bending 3 degrees a frame, lifted 0.2 m on frame 12.
function sequenceResult() {
  const count = 20, values = new Float32Array(count * 77 * 3);
  const elbow = model.SOMA_JOINTS.indexOf('LeftForeArm') - 1;
  for (let f = 0; f < count; f++) values[(f * 77 + elbow) * 3 + 1] = 3 * f * Math.PI / 180;
  const rotations = 'base64:' + Buffer.from(values.buffer).toString('base64');
  return {version: 1, skeleton: 'soma77', fps: 25, frame_count: 30, source: {kind: 'video', truncated: false},
    people: [{label: '角色 A', color: '#3e8ef7', height_cm: 170, body_id: 'b'.repeat(32), confidence: Array.from({length: count}, (_, f) => f === 3 ? 0.2 : 0.9),
      frames: {start: 5, count, transl: Array.from({length: count}, (_, f) => [0.1 * f, 0.9, 0]), lift: Array.from({length: count}, (_, f) => f === 7 ? 0.2 : 0), rotations}}],
    cameras: [{id: 'photo', position: [0, 1.2, 4], target: [0, 1, 0], focal_mm: 35, aspect: '16:9', width: 1280, height: 720}]};
}
const sequenceModule = () => load(['desktop-pose-model.js', 'desktop-pose-sequence.js']);

test('video recognition: characters follow tracks, the sequence carries timing and the export range', () => {
  const node = model.createState();
  model.applyCaptureSequence(node, sequenceResult(), 'a'.repeat(32));
  const [c] = node.scene.characters;
  assert.deepEqual(plain(c.track), {person: 0, start: 5, count: 20});
  assert.deepEqual(plain(node.scene.sequence), {jobId: 'a'.repeat(32), fps: 25, frameCount: 30, frame: 0, inFrame: 0, outFrame: 29});
  assert.equal(c.body, 'capture:' + 'b'.repeat(32));
  assert.deepEqual(plain(node.scene.cameras.map(x => x.name)), ['视频机位', '机位 1']);
  assert.equal(model.hasCustomPose(node), true);
  const dropped = model.normalizeScene({...plain(node.scene), sequence: {jobId: 'bad'}});
  assert.equal(dropped.characters[0].track, null, 'a character cannot follow a sequence that is gone');
  const keys = model.normalizeScene({...plain(node.scene), characters: [{...plain(c), keys: [
    {frame: 9, rotations: {LeftArm: [0, 0, 0.3826834, 0.9238795]}}, {frame: 4, rotations: {Nope: [0, 0, 0, 1]}},
    {frame: 9, rotations: {Head: [0, 0.3826834, 0, 0.9238795]}}, {frame: 2, rotations: {Head: [0.3826834, 0, 0, 0.9238795]}}]}]}).characters[0].keys;
  assert.deepEqual(plain(keys.map(k => [k.frame, Object.keys(k.rotations)])), [[2, ['Head']], [9, ['Head']]], 'one key per frame, real joints only, sorted');
  assert.throws(() => model.applyCaptureSequence(model.createState(), {...sequenceResult(), people: []}, 'a'.repeat(32)), /视频中没有识别到人物/);
});

test('sequence frames: pose, trajectory, lift and visibility of a track character', () => {
  const window = sequenceModule(), m = window.DesktopPoseModel, sequence = window.DesktopPoseSequence.decode(sequenceResult());
  const seq = window.DesktopPoseSequence.create({model: m, fetchResult: async () => sequenceResult()});
  const c = m.createCharacter(0, {track: {person: 0, start: 5, count: 20}, yaw: 90, position: [1, 0]});
  const at = f => seq.characterAt(c, sequence, f);
  assert.ok(Math.abs(quatAngle(at(15).rotations.LeftForeArm) - 30) < 0.01, 'frame 15 is local frame 10');
  assert.ok(Math.abs(at(12).elevation - 0.2) < 1e-6);
  assert.deepEqual(plain([at(4).visible, at(5).visible, at(24).visible, at(25).visible]), [false, true, true, false]);
  const [x, z] = at(15).position;  // 1 m along +X turned 90 degrees about the first frame, then shifted +1 X
  assert.ok(Math.abs(x - 1) < 1e-6 && Math.abs(z + 1) < 1e-6, `${x}, ${z}`);
  assert.equal(at(15).grounded, true);
  assert.equal(at(15).hips, undefined, 'results without hips heights stand the figure on lift');
});

test('sequences with hips heights place the figure by its hips, plus the elevation offset', () => {
  const window = sequenceModule(), m = window.DesktopPoseModel, result = sequenceResult();
  result.people[0].frames.hips = Array.from({length: 20}, (_, f) => 0.9 - 0.02 * f);
  const sequence = window.DesktopPoseSequence.decode(result);
  const seq = window.DesktopPoseSequence.create({model: m, fetchResult: async () => result});
  const c = m.createCharacter(0, {track: {person: 0, start: 5, count: 20}, elevation: 0.1});
  assert.ok(Math.abs(seq.characterAt(c, sequence, 15).hips - (0.9 - 0.2 + 0.1)) < 1e-6);
  result.people[0].frames.hips = [0.9];
  assert.equal(window.DesktopPoseSequence.decode(result).people[0].hips, null, 'a hips list of the wrong length is ignored');
  const rig = fs.readFileSync(path.join(scripts, 'desktop-pose-soma-rig.js'), 'utf8');
  assert.match(rig, /if \(Number\.isFinite\(character\.hips\)\) \{[\s\S]{0,200}figure\.body\.position\.y = \(character\.hips - jointWorld\(figure, 'Hips', tmp\)\.y\) \/ scale;[\s\S]{0,80}\} else if \(character\.grounded !== false\)/);
});

test('keyframes override the recognition locally: exact on the key, faded over 10 frames, blended between keys', () => {
  const window = sequenceModule(), m = window.DesktopPoseModel, sequence = window.DesktopPoseSequence.decode(sequenceResult());
  const seq = window.DesktopPoseSequence.create({model: m, fetchResult: async () => sequenceResult()});
  const target = m.axisAngle([0, 1, 0], 60);  // recognised: 3 x (10 - 5) = 15 degrees at clip frame 10
  const c = m.createCharacter(0, {track: {person: 0, start: 5, count: 20}, keys: [{frame: 10, rotations: {LeftForeArm: target}}]});
  const angle = f => quatAngle(seq.rotationsAt(c, sequence, f).LeftForeArm);
  assert.ok(Math.abs(angle(10) - 60) < 0.01);
  assert.ok(Math.abs(angle(15) - (30 + 22.5)) < 0.05, 'halfway through the fade: base 30 + half of the 45 degree fix');
  assert.ok(Math.abs(angle(20) - 45) < 0.01, 'ten frames on the recognition is back');
  assert.ok(Math.abs(angle(5) - (0 + 22.5)) < 0.05, 'and five frames before the key, half of it');
  c.keys.push({frame: 20, rotations: {LeftForeArm: m.axisAngle([0, 1, 0], 45)}});  // recognised there: 45, fix 0
  assert.ok(Math.abs(angle(15) - (30 + 22.5)) < 0.05, 'between keys the fix is interpolated (45 -> 0)');
  assert.ok(Math.abs(quatAngle(seq.rotationsAt(c, sequence, 10).LeftArm || m.IDENTITY)) < 1e-6, 'unkeyed joints stay recognised');
});

test('a video export does not go stale when scrubbing; an image export does', () => {
  const node = model.createState();
  model.applyCaptureSequence(node, sequenceResult(), 'a'.repeat(32));
  assert.equal(node.output.kind, 'video');
  assert.equal(model.exportsVideo(node), true);
  const key = model.sceneKey(node);
  node.scene.sequence.frame = 12;
  assert.equal(model.sceneKey(node), key);
  node.scene.sequence.inFrame = 3;
  assert.notEqual(model.sceneKey(node), key, 'the export range is part of a video');
  node.output.kind = 'image';
  const image = model.sceneKey(node);
  node.scene.sequence.frame = 13;
  assert.notEqual(model.sceneKey(node), image);
  node.output.video = {url: '/video/pose_openpose_202835_2b8ddb7d.mp4', frames: 30, fps: 25, width: 1024, height: 576};
  assert.equal(model.normalize(node).output.video.frames, 30);
  node.output.video = {url: '/video/../../etc/passwd.mp4'};
  assert.equal(model.normalize(node).output.video, null, 'only pose videos in the archive');
});

test('recognition job uploads the connected image, polls to completion and can be cancelled', async () => {
  const calls = [];
  let polls = 0;
  const api = {capture: {
    mediaBlob: async url => { calls.push(['blob', url]); return new Blob(['x']); },
    upload: async (blob, name) => { calls.push(['upload', name]); return {asset_id: 'a'.repeat(32)}; },
    submit: async body => { calls.push(['submit', body]); return {id: 'j'.repeat(32)}; },
    job: async () => (++polls < 3 ? {status: 'running', stage: '识别姿势 1/1'} : {status: 'succeeded', people: 1, result: captureResult()}),
    cancel: async id => { calls.push(['cancel', id]); return {}; },
  }};
  const capture = load(['desktop-pose-capture.js'], {setTimeout}).DesktopPoseCapture.create({api, maxPeople: 6, pollMs: 1});
  const stages = [];
  const job = await capture.run('n1', {url: '/images/a.png', name: 'a.png'}, stage => stages.push(stage));
  assert.equal(job.people, 1);
  assert.deepEqual(plain(calls.slice(0, 3)), [['blob', '/images/a.png'], ['upload', 'a.png'], ['submit', {asset_id: 'a'.repeat(32), max_people: 6}]]);
  assert.ok(stages.includes('识别姿势 1/1'));
  assert.equal(capture.active('n1'), false);
  api.capture.job = async () => ({status: 'running', stage: '识别中'});
  const pending = capture.run('n2', {url: '/images/b.png'});
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(capture.active('n2'), true);
  await assert.rejects(capture.run('n2', {url: '/x'}), /正在识别/);
  capture.cancel('n2');
  api.capture.job = async () => ({status: 'cancelled'});
  assert.equal(await pending, null);
  assert.deepEqual(plain(calls.at(-1)), ['cancel', 'j'.repeat(32)]);
  api.capture.job = async () => ({status: 'failed', error: '引擎崩溃'});
  await assert.rejects(capture.run('n3', {url: '/images/c.png'}), /引擎崩溃/);
});

test('a video recognition uploads the clip as video and fetches the sequence once it is done', async () => {
  const calls = [];
  const api = {capture: {
    mediaBlob: async url => { calls.push(['blob', url]); return new Blob(['v']); },
    upload: async (blob, name, kind) => { calls.push(['upload', name, kind]); return {asset_id: 'a'.repeat(32)}; },
    submit: async body => ({id: 'k'.repeat(32)}),
    job: async () => ({id: 'k'.repeat(32), status: 'succeeded', people: 1, result_url: '/api/pose_capture/result?id=' + 'k'.repeat(32)}),
    result: async id => { calls.push(['result', id]); return sequenceResult(); },
    cancel: async () => ({}),
  }};
  const capture = load(['desktop-pose-capture.js'], {setTimeout}).DesktopPoseCapture.create({api, maxPeople: 6, pollMs: 1});
  const stages = [];
  const job = await capture.run('n1', {url: '/video/clip.mp4', name: 'clip.mp4', kind: 'video'}, stage => stages.push(stage));
  assert.equal(job.result.frame_count, 30);
  assert.deepEqual(plain(calls), [['blob', '/video/clip.mp4'], ['upload', 'clip.mp4', 'video'], ['result', 'k'.repeat(32)]]);
  assert.deepEqual(plain(stages.slice(0, 2)), ['读取视频', '上传视频']);
});

test('image evidence is a recognition option: submitted for videos only and never part of the export key', async () => {
  const submitted = [];
  const api = {capture: {
    mediaBlob: async () => new Blob(['v']), upload: async () => ({asset_id: 'a'.repeat(32)}),
    submit: async body => { submitted.push(body); return {id: 'k'.repeat(32)}; },
    job: async () => ({id: 'k'.repeat(32), status: 'succeeded', people: 1, result: {}}), result: async () => ({}), cancel: async () => ({}),
  }};
  const capture = load(['desktop-pose-capture.js'], {setTimeout}).DesktopPoseCapture.create({api, maxPeople: 6, pollMs: 1});
  await capture.run('v1', {url: '/video/a.mp4', kind: 'video'}, () => {}, {evidence: false});
  await capture.run('v2', {url: '/video/b.mp4', kind: 'video'});
  await capture.run('p1', {url: '/images/a.png'}, () => {}, {evidence: true});
  assert.deepEqual(plain(submitted.map(b => 'evidence' in b ? b.evidence : 'absent')), [false, true, 'absent']);
  const node = model.createState();
  assert.deepEqual(plain(node.capture), {evidence: true});
  const key = model.sceneKey(node);
  node.capture.evidence = false;
  assert.deepEqual(plain(model.normalize(node).capture), {evidence: false}, 'the choice survives normalisation');
  assert.equal(model.sceneKey(node), key, 'turning image evidence off does not mark an export out of date');
  const view = read('scripts/desktop-pose-view.js');
  assert.match(view, /data-pose-evidence aria-pressed="true" hidden/);
  assert.match(view, /const evidence = Boolean\(display\.videos\) && engineReady && videoReady && display\.recognition\?\.modes\?\.evidence === true;/);
  const controller = read('scripts/desktop-canvas-pose.js');
  assert.match(controller, /\{evidence: s\.node\.capture\.evidence && recognition\.modes\?\.evidence === true\}/);
  assert.match(controller, /closest\('\[data-pose-evidence\]:not\(:disabled\)'\)\) \{ event\.stopPropagation\(\); s\.node\.capture\.evidence = !s\.node\.capture\.evidence; changed\(s\); \}/);
});

test('downstream model inputs receive the exported pose image, not unexported or legacy nodes', () => {
  const exported = {id: 'pose_a', ...model.createState(), title: '姿态参考'};
  exported.output.artifactUrl = '/api/pose/export/artifact?id=' + 'f'.repeat(32);
  exported.output.pass = 'depth';
  const fresh = {id: 'pose_b', ...model.createState()};
  const legacy = {id: 'pose_c', type: 'pose', exportImage: 'data:image/png;base64,AAAA'};
  const DesktopState = {state: {canvas: {nodes: {pose_a: exported, pose_b: fresh, pose_c: legacy, input: {id: 'input', type: 'input'}},
    edges: [{from: 'pose_a', to: 'input'}, {from: 'pose_b', to: 'input'}, {from: 'pose_c', to: 'input'}]}}};
  const win = load(['desktop-canvas-references.js'], {DesktopState});
  const refs = win.DesktopCanvasReferences.create({poseDefinition: model}).getConnectedImageReferences('input');
  assert.equal(refs.length, 1);
  assert.equal(refs[0].url, exported.output.artifactUrl);
  assert.equal(refs[0].imageUrl, exported.output.artifactUrl);
  assert.equal(refs[0].source, 'pose-node');
  assert.match(refs[0].title, /深度/);
});

test('page wiring: new pose modules load before the canvas, old Mixamo studio is gone', () => {
  const html = read('desktop.html');
  const order = ['scripts/desktop-pose-model.js', 'scripts/desktop-pose-api.js', 'scripts/desktop-pose-view.js', 'scripts/desktop-pose-capture.js',
    'scripts/desktop-pose-sequence.js', 'scripts/desktop-canvas-pose.js', 'scripts/desktop-canvas.js', 'scripts/desktop-pose-editor.js'];
  for (const asset of [...order, 'scripts/desktop-pose-editor.js', 'styles/desktop-pose-node.css', 'styles/desktop-pose-editor-geometry.css', 'styles/desktop-pose-editor.css'])
    assert.ok(hasCacheKey(html, asset), asset);
  const positions = order.map(asset => html.indexOf(asset));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  assert.match(html, /<script type="module" src="scripts\/desktop-pose-editor\.js\?v=/);
  assert.ok(html.indexOf('styles/desktop-tokens.css') < html.indexOf('styles/desktop-pose-node.css'));
  for (const gone of ['desktop-pose-studio.js', 'desktop-pose.css']) {
    assert.ok(!html.includes(gone), gone);
    assert.ok(!fs.existsSync(path.join(frontend, gone.endsWith('.js') ? 'scripts' : 'styles', gone)), gone);
  }
  const canvas = read('scripts/desktop-canvas.js');
  assert.ok(!/DesktopPoseStudio|director_stage|connectPoseToDefaultInput/.test(canvas));
  assert.match(canvas, /window\.DesktopPoseModel\.menu/);
  assert.match(read('scripts/desktop-canvas-references.js'), /poseDefinition\.artifactUrl\(node\)/);
  assert.match(read('scripts/desktop-canvas-workflow.js'), /poseDefinition\?\.isLegacy\(clean\)/);
});

test('editor modules share one module graph and keep the viewport context scoped to the session', () => {
  const editor = fs.readFileSync(path.join(scripts, 'desktop-pose-editor.js'), 'utf8');
  for (const dep of ['desktop-pose-soma-rig.js', 'desktop-pose-ik.js', 'desktop-pose-render-passes.js', 'desktop-pose-scene.js', 'desktop-pose-editor-view.js'])
    assert.match(editor, new RegExp(`from '\\./${dep.replace('.', '\\.')}'`));
  assert.match(editor, /forceContextLoss\(\)/);
  // Render passes take visibility from the entries: a recognised person must be hidden outside their track.
  assert.match(read('scripts/desktop-pose-scene.js'), /entries\(\) \{ return this\.characters\.map\(character => \(\{character: this\.shownOf\(character\)/);
  // A force-lost WebGL context cannot be revived: each session swaps in a fresh canvas element.
  assert.match(editor, /previous\.cloneNode\(false\);\s*previous\.replaceWith\(canvas\)/);
  assert.match(editor, /viewer\.addEventListener\('pointerup'/);
  assert.match(editor, /window\.DesktopPoseEditor = Object\.freeze\(\{open, close, exported, isOpen: \(\) => Boolean\(session\), renderNode\}\)/);
  const css = read('styles/desktop-pose-editor.css') + read('styles/desktop-pose-editor-geometry.css') + read('styles/desktop-pose-node.css');
  assert.ok(!/backdrop-filter/.test(css), 'no backdrop blur over WebGL');
  assert.ok(!/\.desk-topaz-video-workbench/.test(css), 'the editor owns its classes');
  assert.ok(!/(^|\})\s*\.desk-pose/m.test(css), 'selectors stay scoped under body.desk-app');
});
