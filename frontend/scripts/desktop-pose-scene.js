// Pose stage: figures built from node scene state, shot cameras, and the offscreen export engine.
// The editor owns its own viewport renderer; exports and thumbnails share one hidden renderer.
import * as THREE from '../static/pose/three.module.js';
import { applyPose, createFigure, disposeFigure, parseTemplate, worldHips } from './desktop-pose-soma-rig.js';
import { createPassKit, renderPassToCanvas } from './desktop-pose-render-passes.js';

const model = window.DesktopPoseModel;
const templates = new Map();
// One sequence cache per page: a recognition job's frames are fetched once and shared by editor and exports.
export const sequences = window.DesktopPoseSequence.create({model, fetchResult: id => window.DesktopPoseAPI.capture.result(id)});
export const loadSequence = scene => scene?.sequence ? sequences.load(scene.sequence.jobId) : Promise.resolve(null);

// Recognised bodies exist only as the low mesh, so one template serves both levels of detail. A recognised
// body that failed to load stays failed (it was deleted or belongs to another machine) instead of refetching.
export function loadTemplate(lod = 'low', body = 'neutral') {
  const capture = Boolean(model.captureBodyId(body));
  const key = capture ? body : `${body}|${lod}`;
  if (!templates.has(key)) {
    const pending = window.DesktopPoseAPI.glb(lod, body).then(parseTemplate);
    templates.set(key, pending);
    pending.catch(() => { if (!capture) templates.delete(key); });
  }
  return templates.get(key);
}

// Templates for every body a scene uses. A body that cannot load falls back to the neutral mannequin.
export async function loadTemplates(characters, lod = 'low') {
  const neutral = await loadTemplate(lod);
  const out = new Map([['neutral', neutral]]), missing = [];
  await Promise.all([...new Set(characters.map(c => c.body))].filter(body => body && body !== 'neutral').map(async body => {
    try { out.set(body, await loadTemplate(lod, body)); } catch (_error) { out.set(body, neutral); missing.push(body); }
  }));
  return {templates: out, missing};
}

export const focalToFov = mm => 2 * Math.atan(24 / (2 * mm)) * 180 / Math.PI;

export function shotCamera(shot, aspect = model.ASPECTS[shot.aspect]) {
  const camera = new THREE.PerspectiveCamera(focalToFov(shot.focalMm), aspect, 0.05, 100);
  camera.position.set(...shot.position);
  camera.lookAt(...shot.target);
  camera.updateMatrixWorld();
  return camera;
}

export function addLights(scene) {
  scene.add(new THREE.HemisphereLight(0xf2f5fa, 0x39424e, 1.25));
  const key = new THREE.DirectionalLight(0xffffff, 1.9); key.position.set(2.5, 4.5, 3.5); scene.add(key);
  const rim = new THREE.DirectionalLight(0x9fc0ff, 0.9); rim.position.set(-3, 2.5, -3); scene.add(rim);
}

export class Stage {
  constructor(templates = new Map()) {
    this.templates = templates;
    this.scene = new THREE.Scene();
    addLights(this.scene);
    this.figures = new Map();
    this.characters = [];
    this.shown = new Map();  // character id -> the character as posed this frame (track characters differ from state)
    this.sequence = null;
    this.frame = 0;
  }
  // Create, pose and drop figures so they match the scene's characters (at `frame` for a recognised video).
  sync(sceneState, sequence = this.sequence, frame = sceneState.sequence?.frame ?? 0) {
    this.characters = sceneState.characters;
    this.sequence = sceneState.sequence ? sequence : null;
    this.frame = frame;
    const ids = new Set(this.characters.map(c => c.id));
    for (const [id, figure] of this.figures) if (!ids.has(id)) { disposeFigure(figure); this.figures.delete(id); this.shown.delete(id); }
    this.characters.forEach(character => this.pose(character));
  }
  setTemplates(templates) { this.templates = templates; }
  // A body whose template is still loading keeps its current figure (no neutral flash); new figures fall back to neutral.
  pose(character) {
    const template = this.templates.get(character.body);
    let figure = this.figures.get(character.id);
    if (figure && template && figure.template !== template) { disposeFigure(figure); figure = null; }
    if (!figure) {
      figure = createFigure(template || this.templates.get('neutral'));
      this.figures.set(character.id, figure); this.scene.add(figure.root);
    }
    const shown = this.sequence ? sequences.characterAt(character, this.sequence, this.frame) : character;
    this.shown.set(character.id, shown);
    applyPose(figure, shown);
    figure.root.visible = shown.visible;
    return figure;
  }
  setFrame(frame) { this.frame = frame; this.characters.forEach(c => this.pose(c)); }
  shownOf(character) { return this.shown.get(character.id) || character; }
  // Each figure with its character as shown at this frame: a recognised person is visible only inside their track
  // (render passes reset visibility from it, and the static character drew people before their track started
  // and froze them after it ended).
  entries() { return this.characters.map(character => ({character: this.shownOf(character), figure: this.figures.get(character.id)})).filter(e => e.figure); }
  world() {
    return Object.fromEntries(this.entries().map(({character, figure}) => [character.id, worldHips(figure, this.shownOf(character))]));
  }
  dispose() { this.figures.forEach(disposeFigure); this.figures.clear(); }
}

let exportRenderer = null, exportKit = null;
const stages = {};
function engine(lod) {
  if (!exportRenderer) {
    exportRenderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    exportRenderer.outputColorSpace = THREE.SRGBColorSpace;
    exportKit = createPassKit();
  }
  stages[lod] ||= new Stage();
  return stages[lod];
}

// Render one pass of a pose node from a shot camera. Exports use the mid mesh for smoother outlines
// (recognised bodies only have the low mesh).
export async function renderNode(node, {pass = node.output.pass, size = node.output.size, cameraId = node.scene.activeCameraId, maxSide = 0, lod = 'mid',
  frame = node.scene.sequence?.frame ?? 0} = {}) {
  const [{templates}, sequence] = await Promise.all([loadTemplates(node.scene.characters, lod), loadSequence(node.scene)]);
  const stage = engine(lod);
  stage.setTemplates(templates);
  stage.sync(node.scene, sequence, frame);
  const shot = node.scene.cameras.find(c => c.id === cameraId) || model.activeCamera(node.scene);
  let [width, height] = model.outputSize(size, shot.aspect);
  if (maxSide && Math.max(width, height) > maxSide) {
    const k = maxSide / Math.max(width, height);
    width = Math.max(1, Math.round(width * k)); height = Math.max(1, Math.round(height * k));
  }
  const camera = shotCamera(shot, width / height);
  const canvas = renderPassToCanvas({renderer: exportRenderer, scene: stage.scene, kit: exportKit, figures: stage.entries(),
    camera, pass, width, height, settings: node.settings});
  return {canvas, width, height, shot, world: stage.world()};
}

const thumbnails = new Map();
// Pose library thumbnails (one neutral figure, front camera), rendered once per page.
export async function presetThumbnails() {
  if (thumbnails.size) return thumbnails;
  const shot = model.createCamera(0, {position: [0, 0.95, 4.4], target: [0, 0.88, 0], focalMm: 50, aspect: '1:1'});
  for (const preset of model.PRESETS) {
    const character = model.createCharacter(0, {rotations: {...preset.rotations}, yaw: preset.facing ?? 0});
    const node = {scene: {characters: [character], cameras: [shot], activeCameraId: shot.id}, output: {size: '1024'}, settings: {background: 'black'}};
    const {canvas} = await renderNode(node, {pass: 'mannequin', maxSide: 160, lod: 'low'});
    thumbnails.set(preset.id, canvas.toDataURL('image/png'));
  }
  return thumbnails;
}
