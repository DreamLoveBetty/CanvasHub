// Video compose (phases 2–3b) frontend: the pure model, recipe reopen, the API translation and page wiring.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

// files: one script or several sharing a window, in page order.
function load(files, extra = {}) {
  const window = { location: { href: 'http://127.0.0.1:18463/desktop.html', origin: 'http://127.0.0.1:18463' }, ...extra.window };
  const context = vm.createContext({ window, URL, URLSearchParams, Promise, ...extra });
  for (const file of [].concat(files)) vm.runInContext(read(file), context);
  return context.window;
}

const { DesktopVideoComposeModel: model } = load(['frontend/scripts/desktop-video-compose-subtitles.js',
  'frontend/scripts/desktop-video-compose-model.js']);
const probe = (count, fps = 30, size = [1920, 1080]) => ({ fps, width: size[0], height: size[1],
  frameTimes: Array.from({ length: count }, (_value, index) => index / fps) });

test('normalize fills defaults, drops duplicate clips and exposes a result on the output port', () => {
  const node = model.normalize({ clips: [{ sourceId: 'a', startFrame: 5, endFrame: 2 }, { sourceId: 'a' }, { sourceId: '' }],
    output: { aspect: '3:2', resolution: 4000 }, result: { url: '/video/video_compose_1_abc.mp4', key: 'k' } });
  assert.deepEqual(plain(node.clips), [{ sourceId: 'a', startFrame: 5, endFrame: -1, audio: true, speed: 1,
    transition: { type: 'none', duration: 0.5 } }]);
  assert.deepEqual(plain(node.output), { aspect: 'source', resolution: 1080, fps: 30, fit: 'crop', encoder: 'quality' });
  assert.deepEqual([node.width, node.height, node.mediaUrl, node.mimeType], [300, 318, '/video/video_compose_1_abc.mp4', 'video/mp4']);
  assert.equal(model.normalize({ result: { url: '/video/other.mp4' } }).result, null, 'only compose outputs count as results');
});

test('clip order and trims survive reconnects; new edges append in order', () => {
  const node = model.normalize({ clips: [{ sourceId: 'b', startFrame: 9 }, { sourceId: 'a' }] });
  assert.equal(model.syncClips(node, ['a', 'c', 'b']), true);
  assert.deepEqual(plain(node.clips.map(clip => [clip.sourceId, clip.startFrame])), [['b', 9], ['a', 0], ['c', 0]]);
  assert.equal(model.syncClips(node, ['a', 'c', 'b']), false);
  assert.equal(model.moveClip(node, 2, 0), true);
  assert.deepEqual(plain(node.clips.map(clip => clip.sourceId)), ['c', 'b', 'a']);
});

test('clip windows and output sizes mirror the backend plan', () => {
  const win = model.clipWindow(probe(90), 30, 59);
  assert.deepEqual([win.frames, win.start, win.seconds], [30, 1, 1]);
  assert.equal(model.clipWindow(probe(90), 0, -1).seconds, 3, 'the last frame lasts one frame gap');
  assert.deepEqual(plain(model.outputSize({ aspect: '9:16', resolution: 720 }, probe(1))), { width: 720, height: 1280 });
  assert.deepEqual(plain(model.outputSize({ aspect: 'source', resolution: 1080 }, probe(1, 30, [1906, 1080]))), { width: 1906, height: 1080 });
});

test('the settings key moves with every render input and the request is snake_case', () => {
  const node = model.normalize({ clips: [{ sourceId: 'a', startFrame: 3, audio: false }] });
  const sources = { a: { url: '/video/a.mp4', name: 'a.mp4' } };
  const key = model.settingsKey(node, sources, '');
  node.output.fps = 24;
  assert.notEqual(model.settingsKey(node, sources, ''), key);
  assert.notEqual(model.settingsKey(node, sources, '/api/assets/audio/file?path=m.wav'), model.settingsKey(node, sources, ''));
  assert.deepEqual(plain(model.request(node, sources, { sourceUrl: '/api/assets/audio/file?path=m.wav', name: 'm.wav' })), {
    title: '视频合成', clip_volume: 1, output: { aspect: 'source', resolution: 1080, fps: 24, fit: 'crop', encoder: 'quality' },
    clips: [{ source_url: '/video/a.mp4', source_name: 'a.mp4', start_frame: 3, end_frame: -1, audio: false, speed: 1,
      transition: { type: 'none', duration: 0.5 } }],
    music: { source_url: '/api/assets/audio/file?path=m.wav', source_name: 'm.wav', volume: 0.8, fade_in: 0, fade_out: 1.5 },
    subtitles: null });
});

test('timing mirrors the backend: speed divides length, transitions overlap and cap at half a clip', () => {
  const node = model.normalize({ clips: [
    { sourceId: 'a', speed: 2, transition: { type: 'fade', duration: 1 } },
    { sourceId: 'b', transition: { type: 'fadeblack', duration: 1 } },
    { sourceId: 'c', transition: { type: 'wipeleft', duration: 1 } }] });
  const wins = [{ seconds: 3 }, { seconds: 1 }, { seconds: 2 }];
  const t = model.timing(node.clips, wins);
  assert.deepEqual(plain(t.lengths), [1.5, 1, 2]);
  assert.deepEqual(plain(t.cuts), [0.5, 0.5], 'the 1 s middle clip allows 0.5 s on each side; the last clip has none');
  assert.equal(t.total, 3.5);
  assert.deepEqual(plain(t.segments.map(seg => [seg.from, seg.length])), [[0, 1.25], [1.25, 0.5], [1.75, 1.75]]);
  assert.equal(model.timing(node.clips, [wins[0], null, wins[2]]).cuts.every(cut => cut === 0), true, 'unprobed clips take no transition');
  assert.equal(model.normalize({ clips: [{ sourceId: 'x', speed: 3, transition: { type: 'spin' } }] }).clips[0].speed, 1);
});

test('speed and transitions join the settings key only when set, like the backend file name', () => {
  const sources = { a: { url: '/video/a.mp4' }, b: { url: '/video/b.mp4' } };
  const node = model.normalize({ clips: [{ sourceId: 'a' }, { sourceId: 'b' }] });
  const phase2 = JSON.stringify({ clips: [['/video/a.mp4', 0, -1, true], ['/video/b.mp4', 0, -1, true]], clipVolume: 1,
    output: plain(node.output), music: null });
  assert.equal(model.settingsKey(node, sources, ''), phase2, 'phase-2 results stay current');
  node.clips[1].transition.type = 'fade';
  assert.equal(model.settingsKey(node, sources, ''), phase2, "the last clip's transition never counts");
  node.clips[0].speed = 1.5;
  node.clips[0].transition.type = 'fade';
  assert.match(model.settingsKey(node, sources, ''), /\{"speed":1.5\},\{"transition":\["fade",0.5\]\}/);
});

test('connections: videos are clips, one audio is the music, a rendered compose feeds video consumers', () => {
  const compose = { type: 'video_compose' };
  assert.equal(model.policy({ type: 'video' }, compose).inputRole, 'clip');
  assert.equal(model.policy({ type: 'audio' }, compose).single, true);
  assert.equal(model.policy(compose, { type: 'topaz_video' }).single, true);
  assert.equal(model.policy(compose, { type: 'comfy' }).single, false);
  assert.equal(model.policy(compose, { type: 'image' }), null);
  assert.equal(model.isVideoSource({ type: 'video_compose' }), false);
  assert.equal(model.isVideoSource({ type: 'video_compose', mediaUrl: '/video/video_compose_1.mp4' }), true);
  const { DesktopVideoComposeTimeline: timeline } = load('frontend/scripts/desktop-video-compose-timeline.js');
  assert.deepEqual([0.5, 3, 6, 13, 600].map(timeline.tilesFor), [8, 8, 24, 40, 40]);
});

test('the API adapter translates a recipe to the canvas shape', async () => {
  const calls = [];
  const api = { json: async url => { calls.push(url); return {
    spec: { title: '旧片', clip_volume: 0.5, output: { aspect: '9:16', resolution: 720, fps: 24, fit: 'blur', encoder: 'fast' },
      clips: [{ source_url: '/video/a.mp4', source_name: 'a.mp4', start_frame: 65, end_frame: -1, audio: false }],
      music: { source_url: '', asset_id: 'f'.repeat(64) + '.wav', source_name: 'm.wav', volume: 0.6, fade_in: 1, fade_out: 0 } },
    result: { url: '/video/video_compose_1.mp4', filename: 'video_compose_1.mp4', file_size: 9, duration_seconds: 2.5,
      width: 720, height: 1280, fps: 24 } }; } };
  const { DesktopVideoEditAPI } = load('frontend/scripts/desktop-video-edit-api.js', { api });
  const recipe = await DesktopVideoEditAPI.compose.recipe('http://127.0.0.1:18463/video/video_compose_1.mp4?miniappAuth=x');
  assert.deepEqual(calls, ['/api/video_edit/compose_recipe?source_url=%2Fvideo%2Fvideo_compose_1.mp4']);
  assert.deepEqual(plain(recipe.clips), [{ sourceUrl: '/video/a.mp4', sourceName: 'a.mp4', startFrame: 65, endFrame: -1, audio: false,
    speed: 1, transition: { type: 'none', duration: 0.5 } }]);
  assert.deepEqual([recipe.clipVolume, recipe.music.fadeIn, recipe.music.fadeOut, recipe.music.assetId.length], [0.5, 1, 0, 68]);
  assert.deepEqual(plain(recipe.result), { url: '/video/video_compose_1.mp4', filename: 'video_compose_1.mp4', fileSize: 9,
    durationSeconds: 2.5, width: 720, height: 1280, fps: 24 });
});

function rebuild(recipe) {
  const { DesktopCanvasVideoComposeRecipe: Recipe } = load('frontend/scripts/desktop-canvas-video-compose-recipe.js');
  const nodes = { out: { id: 'out', type: 'video', x: 100, y: 50, width: 266, height: 470, mediaUrl: '/video/video_compose_1_abc.mp4' } };
  const edges = [], calls = { audio: [], adopt: [], messages: [], refreshed: [] };
  let count = 0;
  const reopen = Recipe.create({
    model, api: { compose: { recipe: async () => recipe } },
    getNodeState: id => nodes[id],
    addNode: (type, center) => {
      const id = `${type}_${count += 1}`;
      nodes[id] = type === 'video_compose' ? model.normalize({ id, type }) : { id, type, width: 320, height: 470 };
      Object.assign(nodes[id], { x: center.x - nodes[id].width / 2, y: center.y - nodes[id].height / 2 });
      return id;
    },
    // Like the canvas: every new clip edge re-syncs the compose node from the edges present so far.
    connectNodes: (from, to) => {
      edges.push([from, to]);
      if (nodes[to].type === 'video_compose' && nodes[from].type === 'video') {
        model.syncClips(nodes[to], edges.filter(edge => edge[1] === to && nodes[edge[0]].type === 'video').map(edge => edge[0]));
      }
    },
    refreshVideoNode: id => calls.refreshed.push(id),
    setAudioResult: async (id, result) => calls.audio.push({ id, result }),
    compose: { adopt: (id, result) => calls.adopt.push({ id, result }) },
    showMessage: message => calls.messages.push(message),
  });
  return { reopen, nodes, edges, calls };
}

const recipeOf = (music = { sourceUrl: '/api/assets/audio/file?path=m.wav', assetId: '', sourceName: 'm.wav', volume: 0.6, fadeIn: 1, fadeOut: 2 }) => ({
  title: '旧片', clipVolume: 0.5, output: { aspect: '9:16', resolution: 720, fps: 24, fit: 'blur', encoder: 'quality' },
  clips: [{ sourceUrl: '/video/a.mp4', sourceName: 'a.mp4', startFrame: 0, endFrame: -1, audio: true },
    { sourceUrl: '/video/b.mp4', sourceName: 'b.mp4', startFrame: 65, endFrame: 200, audio: false }],
  music, result: { url: '/video/video_compose_1_abc.mp4', filename: 'video_compose_1_abc.mp4' } });

test('reopening a recipe rebuilds clips, music and settings and adopts the archived render', async () => {
  const { reopen, nodes, edges, calls } = rebuild(recipeOf());
  const composeId = await reopen.reopen('out');
  const compose = nodes[composeId];
  assert.deepEqual(compose.clips.map(clip => [nodes[clip.sourceId].mediaUrl, clip.startFrame, clip.endFrame, clip.audio]),
    [['/video/a.mp4', 0, -1, true], ['/video/b.mp4', 65, 200, false]], 'trims survive the edge-by-edge resync');
  assert.deepEqual(plain(compose.music), { volume: 0.6, fadeIn: 1, fadeOut: 2 });
  assert.deepEqual([compose.title, compose.clipVolume, compose.output.fit, compose.output.fps], ['旧片', 0.5, 'blur', 24]);
  assert.equal(calls.audio[0].result.url, '/api/assets/audio/file?path=m.wav');
  assert.deepEqual(edges.map(([from, to]) => `${nodes[from].type}->${nodes[to].type}`),
    ['video->video_compose', 'video->video_compose', 'audio->video_compose']);
  assert.deepEqual(calls.adopt.map(item => [item.id, item.result.url]), [[composeId, '/video/video_compose_1_abc.mp4']]);
  const clips = compose.clips.map(clip => nodes[clip.sourceId]);
  assert.ok(clips.every(node => node.y > nodes.out.y + nodes.out.height), 'clips sit below the archived video');
  assert.ok(clips[1].x - clips[0].x >= 470, 'cells fit a landscape clip without overlap');
  assert.ok(compose.x > clips[1].x + 470, 'compose sits right of the clips');
});

test('uploaded music cannot be rebuilt and says so; other videos are refused', async () => {
  const { reopen, nodes, calls } = rebuild(recipeOf({ sourceUrl: '', assetId: 'f'.repeat(64) + '.wav', sourceName: 'm.wav', volume: 0.8, fadeIn: 0, fadeOut: 1.5 }));
  await reopen.reopen('out');
  assert.equal(calls.audio.length, 0);
  assert.match(calls.messages[0], /临时上传的音频，请重新连接音频节点/);
  nodes.other = { id: 'other', type: 'video', x: 0, y: 0, width: 320, height: 470, mediaUrl: '/video/comfy_1.mp4' };
  await assert.rejects(reopen.reopen('other'), /不是合成成片/);
  assert.equal(reopen.isOutput('/video/2026-11-10/video_compose_045622_ca3b816d56a1.mp4?x=1'), true);
  assert.equal(reopen.isOutput('/video/comfy_1.mp4'), false);
});

test('the video dock offers「配方」only on compose outputs', () => {
  const { DesktopCanvasVideoEdit: VideoEdit } = load('frontend/scripts/desktop-canvas-video-edit.js');
  const { DesktopCanvasVideoComposeRecipe: Recipe } = load('frontend/scripts/desktop-canvas-video-compose-recipe.js');
  const reopened = [];
  const edit = VideoEdit.create({ api: { sourceUrl: value => String(value) }, picker: {}, escapeHtml: String,
    getCanvas: () => ({}), getNodeState: () => null, getNodeElement: () => null, addNode: () => '', connectNodes: () => {},
    insertImageNode: () => '', getImageNodeSize: () => ({}), setAudioResult: async () => {}, showMessage: () => {},
    recipe: { isOutput: Recipe.isOutput, reopen: async id => reopened.push(id) } });
  assert.match(edit.dockHtml({ id: 'v', type: 'video', mediaUrl: '/video/video_compose_1.mp4' }), /data-video-edit="recipe"[^>]*>配方</);
  assert.doesNotMatch(edit.dockHtml({ id: 'v', type: 'video', mediaUrl: '/video/comfy_1.mp4' }), /data-video-edit="recipe"/);
  const button = { disabled: false, dataset: { videoEdit: 'recipe' },
    closest: () => ({ dataset: { nodeId: 'v9' } }) };
  assert.equal(edit.handleAction(button), true);
  assert.deepEqual(reopened, ['v9']);
});

test('the page loads the compose modules in dependency order and the canvas wires them', () => {
  const html = read('frontend/desktop.html');
  const files = ['scripts/desktop-video-edit-api.js', 'scripts/desktop-video-compose-subtitles.js', 'scripts/desktop-video-compose-model.js',
    'scripts/desktop-video-compose-player.js', 'scripts/desktop-video-compose-timeline.js', 'scripts/desktop-video-compose-view.js',
    'scripts/desktop-video-compose-subtitle-panel.js', 'scripts/desktop-canvas-video-compose.js',
    'scripts/desktop-canvas-video-compose-recipe.js', 'scripts/desktop-canvas.js'];
  for (const file of files) assert.ok(hasCacheKey(html, file), file);
  const at = file => html.indexOf(`${file}?v=`);
  files.slice(1).forEach((file, index) => assert.ok(at(files[index]) < at(file), `${files[index]} before ${file}`));
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.match(canvas, /DesktopCanvasVideoComposeRecipe\.create\(\{[\s\S]*?compose: canvasVideoCompose,/);
  assert.match(canvas, /recipe: \{ isOutput: window\.DesktopCanvasVideoComposeRecipe\.isOutput, reopen: nodeId => canvasVideoComposeRecipe\.reopen\(nodeId\) \}/);
  assert.match(canvas, /taskRegistry\.register\('video_compose'/);
  assert.match(canvas, /canvasVideoCompose\.connections, canvasTopazVideo\.connections/);
});
