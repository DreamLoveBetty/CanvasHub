const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

function load(file, extra = {}) {
  const window = { location: { href: 'http://127.0.0.1:18463/desktop.html', origin: 'http://127.0.0.1:18463' },
    setTimeout: callback => { callback(); return 1; }, ...extra.window };
  const context = { window, URL, URLSearchParams, Promise, ...extra };
  vm.runInNewContext(read(file), context);
  return context.window;
}

test('the API adapter sends only served same-origin media URLs', () => {
  const { DesktopVideoEditAPI: api } = load('frontend/scripts/desktop-video-edit-api.js');
  assert.equal(api.sourceUrl('/video/2026-11-10/a%20b.mp4'), '/video/2026-11-10/a%20b.mp4');
  assert.equal(api.sourceUrl('http://127.0.0.1:18463/video/a.mp4?miniappAuth=secret'), '/video/a.mp4');
  assert.equal(api.sourceUrl('/api/video_control/source?id=2'), '/api/video_control/source?id=2');
  for (const value of ['', 'blob:http://127.0.0.1:18463/1', 'data:video/mp4;base64,AA', 'https://evil.test/video/a.mp4',
    '/image/a.png', '/api/audio/artifact?id=1', '/video/']) {
    assert.equal(api.sourceUrl(value), '', value);
  }
});

test('the picker maps frames to midpoints so the player shows the frame the backend extracts', () => {
  const { DesktopVideoFrames: frames } = load('frontend/scripts/desktop-video-frames.js');
  const times = [0, 0.1, 0.2, 0.3, 0.3333, 0.3667]; // 10 fps, then 30 fps
  assert.equal(frames.seekTime(times, 0), 0.05);
  assert.ok(Math.abs(frames.seekTime(times, 3) - 0.31665) < 1e-9);
  assert.ok(frames.seekTime(times, 5, 0.4) > times[5] && frames.seekTime(times, 5, 0.4) < 0.4);
  for (let n = 0; n < times.length; n += 1) {
    assert.equal(frames.bisectFrame(times, frames.seekTime(times, n, 0.4)), n, `frame ${n} round-trips`);
  }
  assert.equal(frames.bisectFrame(times, 0.25), 2);
  assert.equal(frames.clock(65.25), '01:05.250');
  assert.equal(frames.MAX_MARKS, 20);
});

test('the picker ruler keeps at most eight readable second labels', () => {
  const { DesktopVideoFrames: frames } = load('frontend/scripts/desktop-video-frames.js');
  assert.equal(frames.rulerStep(3), 0.5);
  assert.equal(frames.rulerStep(12.07), 2);
  assert.equal(frames.rulerStep(180), 30);
  assert.equal(frames.rulerStep(600), 120);
  for (const span of [0.4, 3, 12, 45, 180, 600]) assert.ok(span / frames.rulerStep(span) <= 8, `span ${span}`);
  assert.equal(frames.rulerLabel(0), '0:00');
  assert.equal(frames.rulerLabel(2.5), '0:02.5');
  assert.equal(frames.rulerLabel(95), '1:35');
});

test('the picker workbench reuses the shared play icon and dark stage tokens in every theme', () => {
  const picker = read('frontend/scripts/desktop-video-frames.js');
  assert.match(picker, /stateIcon\.html\(PLAY_ICONS, 'play'\)/);
  assert.match(picker, /stateIcon\.paint\(play\.querySelector\('svg'\), playing \? 'pause' : 'play'\)/);
  for (const hook of ['data-vf-filmstrip', 'data-vf-markers', 'data-vf-ruler', 'data-vf-head', 'data-vf-mark-label', 'data-vf-badge="cut"'])
    assert.ok(picker.includes(hook), hook);
  assert.match(read('frontend/scripts/desktop-canvas.js'), /DesktopVideoFrames\.create\(\{ api: window\.DesktopVideoEditAPI, escapeHtml, stateIcon,/);
  const tokens = read('frontend/styles/desktop-tokens.css');
  const dark = tokens.indexOf('body.desk-app[data-theme="dark"] {');
  for (const name of ['stage', 'strip', 'playhead', 'cut', 'overlay']) {
    const token = `--desk-video-frames-${name}:`;
    assert.ok(tokens.indexOf(token) > 0 && tokens.indexOf(token) < dark, `light ${name}`);
    assert.ok(tokens.indexOf(token, dark) > dark, `dark ${name}`);
  }
  const paint = read('frontend/styles/desktop-video-edit.css');
  assert.ok(!/#[0-9a-f]{3,6}\b/i.test(paint.replace(/url\("data:[^"]+"\)/g, '')), 'picker paint uses tokens, not raw colours');
});

function controller({ probe = { hasAudio: true }, receipts } = {}) {
  const { DesktopCanvasVideoEdit: VideoEdit } = load('frontend/scripts/desktop-canvas-video-edit.js');
  const nodes = { v1: { id: 'v1', type: 'video', x: 0, y: 0, width: 400, height: 225, mediaUrl: '/video/clip.mp4', mediaName: '镜头.mp4' } };
  const calls = { submit: [], images: [], edges: [], audio: [], messages: [] };
  const queue = [...(receipts || [])];
  const api = {
    sourceUrl: value => (String(value).startsWith('/video/') ? String(value) : ''),
    probe: async () => probe,
    submit: async (kind, source, extra) => { calls.submit.push({ kind, source, ...extra }); return queue.shift(); },
    progress: async () => queue.shift(),
    cancel: async () => ({}),
  };
  const edit = VideoEdit.create({
    api, picker: { open: ctx => { calls.picker = ctx; } }, escapeHtml,
    getCanvas: () => ({ nodes }), getNodeState: id => nodes[id], getNodeElement: () => null,
    addNode: (type, center) => { const id = 'a' + Object.keys(nodes).length; nodes[id] = { id, type, x: center.x - 400, y: center.y - 180, width: 800, height: 360 }; return id; },
    connectNodes: (from, to) => calls.edges.push([from, to]),
    insertImageNode: (source, center) => {
      const id = 'i' + Object.keys(nodes).length;
      nodes[id] = { id, type: 'image', x: center.x - 180, y: center.y - 101.25, width: 360, height: 202.5 };
      calls.images.push({ id, source, center });
      return id;
    },
    getImageNodeSize: () => ({ width: 360, height: 202.5 }),
    setAudioResult: async (id, result) => calls.audio.push({ id, result }),
    fetchBlob: async url => ({ fetched: url }),
    progressView: null, reportStatus: () => {}, showMessage: message => calls.messages.push(message),
  });
  return { edit, nodes, calls, VideoEdit };
}

const receipt = (status, raw = {}) => ({ task_id: 'job1', status, progress: status === 'succeeded' ? 100 : 40, stage: '', raw });

test('video nodes connect to image and audio nodes only through this domain', () => {
  const { VideoEdit } = controller();
  assert.deepEqual(JSON.parse(JSON.stringify(VideoEdit.targets)), { video: ['image', 'audio'] });
  assert.equal(VideoEdit.policy({ type: 'video' }, { type: 'image' }).outputRole, 'frame');
  assert.equal(VideoEdit.policy({ type: 'video' }, { type: 'audio' }).replaceAllInputs, true);
  assert.equal(VideoEdit.policy({ type: 'video' }, { type: 'pose' }), null);
  assert.equal(VideoEdit.policy({ type: 'image' }, { type: 'audio' }), null);
  assert.match(read('frontend/scripts/desktop-canvas.js'), /canvasVideoCompose\.connections, canvasVideoEdit\.connections,/);
});

test('the dock renders only for editable sources and disables audio once a probe finds none', async () => {
  const { edit, nodes } = controller({ probe: { hasAudio: false } });
  const html = edit.dockHtml(nodes.v1);
  for (const action of ['first', 'last', 'pick', 'audio']) assert.match(html, new RegExp(`data-video-edit="${action}"`));
  assert.match(html, /data-node-drag-ignore/);
  assert.match(html, /desk-progress-float desk-video-edit__progress" data-video-edit-progress hidden/);
  assert.equal(edit.dockHtml({ ...nodes.v1, mediaUrl: 'blob:x' }), '');
  edit.warm('v1');
  await new Promise(resolve => setImmediate(resolve));
  assert.match(edit.dockHtml(nodes.v1), /data-video-edit="audio" title="这段视频没有音轨" disabled>无音轨/);
});

test('first/last frames run a job and land as connected image nodes beside the video', async () => {
  const frame = { frame: 0, time: 0, url: '/image/video_frame_1.png', filename: 'video_frame_1.png', width: 640, height: 360 };
  const { edit, nodes, calls } = controller({ receipts: [receipt('queued'), receipt('running'),
    receipt('succeeded', { result: { frames: [frame, { ...frame, frame: 9, url: '/image/f9.png', filename: 'f9.png' }] } })] });
  const ids = await edit.extractFrames('v1', [0, 9], 'pick');
  assert.deepEqual(calls.submit, [{ kind: 'frames', source: '/video/clip.mp4', sourceName: '镜头.mp4', frames: [0, 9] }]);
  assert.equal(ids.length, 2);
  assert.deepEqual(calls.edges, [['v1', ids[0]], ['v1', ids[1]]]);
  const [first, second] = calls.images.map(item => nodes[item.id]);
  assert.equal(calls.images[0].source.imageUrl, '/image/video_frame_1.png');
  assert.equal(calls.images[0].source.provider, 'video_frame');
  assert.equal(calls.images[1].source.title, '镜头.mp4 · 第 10 帧');
  assert.ok(first.x >= 480, 'placed to the right of the video');
  assert.ok(second.y >= first.y + first.height, 'second frame stacks below the first without overlap');
});

test('separating audio adds an audio node with the archived track', async () => {
  const track = { url: '/api/assets/audio/file?path=x.m4a', name: 'video_audio_x.m4a', title: '镜头 · 音轨',
    mime_type: 'audio/mp4', file_size: 10, duration_seconds: 5, reused: false };
  const { edit, calls } = controller({ receipts: [receipt('succeeded', { result: track })] });
  const audioId = await edit.separateAudio('v1');
  assert.equal(calls.submit[0].kind, 'extract_audio');
  assert.deepEqual(calls.edges, [['v1', audioId]]);
  assert.equal(calls.audio[0].result.url, track.url);
  assert.equal(calls.audio[0].result.name, '镜头 · 音轨');
  assert.deepEqual(calls.audio[0].result.blob, { fetched: track.url }, 'bytes go along for the local waveform');
});

test('failed jobs surface their error and a busy node refuses a second job', async () => {
  const { edit } = controller({ receipts: [receipt('failed', {}), receipt('queued')] });
  const failing = edit.extractFrames('v1', [0], 'first');
  await assert.rejects(failing, /处理失败/);
  const pending = controller({ receipts: [receipt('queued'), receipt('queued')] });
  pending.edit.extractFrames('v1', [0], 'first').catch(() => {});
  await assert.rejects(pending.edit.separateAudio('v1'), /正在处理/);
});

test('the picker hands scene detection and extraction back to the controller', () => {
  const { edit, calls } = controller();
  edit.openPicker('v1');
  assert.equal(calls.picker.source, '/video/clip.mp4');
  assert.equal(calls.picker.name, '镜头.mp4');
  assert.equal(typeof calls.picker.detectScenes, 'function');
  assert.equal(typeof calls.picker.onExtract, 'function');
});

test('canvas, node template, history and page wire the domain', () => {
  const canvas = read('frontend/scripts/desktop-canvas.js');
  const editAt = canvas.indexOf("event.target.closest('[data-video-edit]')");
  assert.ok(editAt > 0 && editAt < canvas.indexOf("event.target.closest('[data-video-upload]')"));
  assert.match(canvas, /canvasVideoEdit\.handleAction\(videoEditButton\);/);
  assert.match(canvas, /if \(videoNode\) canvasVideoEdit\.warm\(videoNode\.dataset\.nodeId\);/);
  assert.match(canvas, /videoEditDockHtml: node => canvasVideoEdit\.dockHtml\(node\),/);
  assert.match(canvas, /taskRegistry\.register\('video_edit', \{client: \(\) => window\.DesktopVideoEditAPI\.tasks,/);
  assert.match(read('frontend/scripts/desktop-canvas-model-nodes.js'), /\$\{rawSource \? videoEditDockHtml\(node\) : ''\}/);
  const history = read('frontend/scripts/desktop-history.js');
  assert.match(history, /if \(type\.startsWith\('video_frame'\) \|\| provider === 'video_frame'\) return 'video_frame';/);
  assert.match(history, /video_frame: '视频抽帧'/);

  const html = read('frontend/desktop.html');
  const files = ['scripts/desktop-video-edit-api.js', 'scripts/desktop-video-frames.js', 'scripts/desktop-canvas-video-edit.js',
    'styles/desktop-video-edit-geometry.css', 'styles/desktop-video-edit.css'];
  for (const file of files) assert.ok(hasCacheKey(html, file), file);
  const at = file => html.indexOf(`${file}?v=`);
  assert.ok(at('scripts/desktop-tasks.js') < at('scripts/desktop-video-edit-api.js'));
  assert.ok(at('scripts/desktop-video-edit-api.js') < at('scripts/desktop-video-frames.js'));
  assert.ok(at('scripts/desktop-video-frames.js') < at('scripts/desktop-canvas-video-edit.js'));
  assert.ok(at('scripts/desktop-canvas-video-edit.js') < at('scripts/desktop-canvas.js'));
  assert.ok(at('styles/desktop-video-edit-geometry.css') < at('styles/desktop-video-edit.css'));
});

test('video-edit styles keep layout and paint apart without !important', () => {
  const geometry = read('frontend/styles/desktop-video-edit-geometry.css');
  const paint = read('frontend/styles/desktop-video-edit.css');
  for (const css of [geometry, paint]) assert.ok(!css.includes('!important'));
  assert.ok(!/(^|\s)(color|background|border-color|box-shadow):/m.test(geometry), 'geometry carries no paint');
  assert.ok(!/(^|\s)(width|height|padding|margin|grid-template-columns|position):/m.test(paint), 'paint carries no layout');
  assert.ok(!/\.(sidebar|menu-card|settings-overlay)\b/.test(geometry + paint), 'no mobile selectors');
});
