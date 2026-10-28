// Video node local upload: media-import controller (upload -> node fields, failure recovery, drop creation),
// empty-state markup, canvas wiring and page input. Synthetic stubs only; no backend.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {hasCacheKey} = require('./asset_keys.cjs');

const frontend = path.join(__dirname, '../frontend');
const read = file => fs.readFileSync(path.join(frontend, file), 'utf8');

function harness({upload}) {
  const nodes = {}, refreshed = [], messages = [], errors = [], selected = [];
  let saves = 0, next = 0;
  const empty = {classList: new Set(), strong: {textContent: ''}, small: {textContent: ''}, button: {attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }}};
  empty.classList.add = empty.classList.add.bind(empty.classList);
  empty.querySelector = sel => sel === 'strong' ? empty.strong : sel === 'small' ? empty.small : empty.button;
  const sandbox = {
    window: {},
    DesktopState: {state: {canvas: {nodes}}, saveSettings: () => { saves += 1; }},
    DesktopApi: {uploadVideo: upload},
    DesktopResults: {showTransientMessage: m => messages.push(m), showError: e => errors.push(e.message)},
  };
  vm.runInNewContext(read('scripts/desktop-canvas-media-import.js'), sandbox);
  const addNode = (type, point) => { const id = `video-${++next}`; nodes[id] = {id, type, x: point.x, y: point.y}; return id; };
  const api = sandbox.window.DesktopCanvasMediaImport.create({
    addNode, selectNode: id => selected.push(id), refreshVideoNode: id => refreshed.push(id),
    fitVideoNodeToMedia: () => true, getNodeElement: () => ({querySelector: () => empty}),
    screenToWorld: (x, y) => ({x, y}), getViewportCenterWorldPoint: () => ({x: 0, y: 0}),
  });
  return {api, nodes, refreshed, messages, errors, selected, empty, saves: () => saves, addNode};
}
const file = (name, type = '') => ({name, type, size: 10});
const asset = {mediaUrl: '/video/video_upload_120000_0123456789ab.mp4', mediaName: 'clip.mp4', mimeType: 'video/mp4',
  mediaWidth: 1280, mediaHeight: 720, fps: 30, durationSeconds: 15, fileSize: 10};

test('only MP4 / MOV / WebM files count as local videos', () => {
  const {api} = harness({upload: async () => asset});
  for (const f of [file('a.mp4', 'video/mp4'), file('b.MOV'), file('c.webm', 'video/webm'), file('d.m4v', 'video/x-m4v'), file('e.mov', 'video/quicktime')])
    assert.equal(api.isLocalVideoFile(f), true, f.name);
  for (const f of [file('a.png', 'image/png'), file('b.mkv', 'video/x-matroska'), file('c.txt', 'text/plain'), file('d.mp4', 'image/png')])
    assert.equal(api.isLocalVideoFile(f), false, f.name);
});

test('uploading fills the node with the archive URL and metadata', async () => {
  const calls = [];
  const h = harness({upload: async (f, name) => { calls.push(name); return asset; }});
  const id = h.addNode('video', {x: 0, y: 0});
  Object.assign(h.nodes[id], {status: 'failed', error: 'old', sourceTaskId: 'task-1'});
  assert.equal(await h.api.uploadVideoToNode(id, file('clip.mp4', 'video/mp4')), id);
  assert.deepEqual(calls, ['clip.mp4']);
  const node = h.nodes[id];
  assert.equal(node.mediaUrl, asset.mediaUrl);
  assert.equal(node.mediaName, 'clip.mp4');
  assert.deepEqual([node.mediaWidth, node.mediaHeight, node.fps, node.durationSeconds], [1280, 720, 30, 15]);
  assert.deepEqual([node.status, node.error, node.sourceTaskId], ['succeeded', '', '']);
  assert.ok(h.refreshed.includes(id));
  assert.ok(h.saves() > 0);
  assert.equal(h.empty.strong.textContent, '正在上传视频');
  assert.equal(h.empty.button.attrs.disabled, '');
});

test('a failed upload restores the empty node and rejects other files without calling the API', async () => {
  let calls = 0;
  const h = harness({upload: async () => { calls += 1; throw new Error('视频须小于 200 MB'); }});
  const id = h.addNode('video', {x: 0, y: 0});
  await assert.rejects(h.api.uploadVideoToNode(id, file('big.mp4', 'video/mp4')), /200 MB/);
  assert.deepEqual(h.refreshed, [id]);
  assert.equal(h.nodes[id].mediaUrl, undefined);
  await assert.rejects(h.api.uploadVideoToNode(id, file('a.png', 'image/png')), /MP4、MOV 或 WebM/);
  assert.equal(calls, 1);
});

test('dropping videos creates one node each at the drop point and reports per-file errors', async () => {
  const h = harness({upload: async f => { if (f.name === 'bad.mp4') throw new Error('无法读取视频画面'); return {...asset, mediaName: f.name}; }});
  const created = await h.api.createVideoNodesFromFiles([file('a.mp4', 'video/mp4'), file('x.png', 'image/png'), file('bad.mp4', 'video/mp4'), file('b.webm', 'video/webm')], 100, 50);
  assert.deepEqual([...created], ['video-1', 'video-3']);
  assert.deepEqual([h.nodes['video-1'].x, h.nodes['video-1'].y, h.nodes['video-3'].x], [100, 50, 156]);
  assert.equal(h.nodes['video-2'].mediaUrl, undefined);
  assert.deepEqual(h.errors, ['无法读取视频画面']);
  assert.equal(h.selected.at(-1), 'video-3');
  assert.match(h.messages.at(-1), /2 个本地视频/);
});

test('empty video nodes offer upload unless a generation is running', () => {
  const source = read('scripts/desktop-canvas-model-nodes.js');
  assert.match(source, /'连接结果或上传视频'/);
  assert.match(source, /const uploadButton = busy\s*\? ''\s*: '<button type="button" class="desk-video-result__upload" data-video-upload/);
  assert.match(source, /desk-video-result__empty\$\{busy \? ' is-busy' : ''\}">\$\{emptyMark\}.*\$\{uploadButton\}<\/div>/);
});

test('canvas routes the upload button, file input and local video drops', () => {
  const canvas = read('scripts/desktop-canvas.js');
  assert.match(canvas, /'deskVideoFileInput'/);
  assert.match(canvas, /closest\('\[data-video-upload\]'\)[\s\S]{0,400}els\.deskVideoFileInput\?\.click\(\)/);
  assert.match(canvas, /deskVideoFileInput\?\.addEventListener\('change'[\s\S]{0,300}uploadVideoToNode\(nodeId, file\)/);
  const drop = canvas.indexOf('const droppedVideos = getLocalDragFiles(event.dataTransfer).filter(isLocalVideoFile)');
  assert.ok(drop > 0 && drop < canvas.indexOf('const captured = captureExternalImageTransfer(event.dataTransfer)', drop));
  assert.match(canvas, /closest\?\.\('\.desk-node--video\.is-empty\[data-node-id\]'\)/);
  const api = read('scripts/desktop-api.js');
  assert.match(api, /request\(`\/api\/video\/upload\?name=\$\{encodeURIComponent/);
  assert.match(api, /durationSeconds: Number\(payload\.duration_seconds/);
});

test('page has a video-only input and cache keys on the changed assets', () => {
  const html = read('desktop.html');
  assert.match(html, /<input id="deskVideoFileInput" type="file" accept="video\/mp4,video\/quicktime,video\/webm,\.mp4,\.m4v,\.mov,\.webm" hidden>/);
  for (const asset of ['scripts/desktop-api.js', 'scripts/desktop-canvas-media-import.js', 'scripts/desktop-canvas-model-nodes.js',
    'scripts/desktop-canvas.js', 'styles/desktop-video.css', 'styles/desktop-creation-tools.css']) assert.ok(hasCacheKey(html, asset), asset);
  assert.ok(html.indexOf('desktop-canvas-media-import.js') < html.indexOf('scripts/desktop-canvas.js'));
});
