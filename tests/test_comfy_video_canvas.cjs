// ComfyUI video I/O on the canvas: video ↔ comfy connection domain, connected-video inputs,
// publication of finished Comfy video tasks into video nodes, video workflows allocating no
// image outputs, and the API adapter never sending the auth header to another origin.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} is not balanced`);
}

function loadModule() {
  const context = vm.createContext({ window: {} });
  vm.runInContext(read('frontend/scripts/desktop-canvas-comfy-video.js'), context);
  return context.window.DesktopCanvasComfyVideo;
}

function canvasHarness() {
  const canvas = {
    nodes: {
      comfy1: { id: 'comfy1', type: 'comfy', x: 0, y: 0, width: 320, height: 300 },
      src: { id: 'src', type: 'video', x: -500, y: 0, width: 400, height: 260, mediaUrl: '/video/in.mp4', mediaName: 'in.mp4' },
      empty: { id: 'empty', type: 'video', x: -500, y: 400, width: 400, height: 260 },
    },
    edges: [{ id: 'e1', from: 'src', to: 'comfy1' }, { id: 'e2', from: 'empty', to: 'comfy1' }],
  };
  const calls = { refreshed: [], saved: 0, messages: [] };
  let nextId = 0;
  const outputs = {};
  const api = loadModule().create({
    getCanvas: () => canvas,
    getNodeState: id => canvas.nodes[id],
    addNode: (type, position) => {
      const id = `new${nextId += 1}`;
      canvas.nodes[id] = { id, type, x: position.x, y: position.y, width: 400, height: 260 };
      return id;
    },
    connectNodes: (from, to) => {
      canvas.edges.push({ id: `${from}_${to}`, from, to });
      api.connections.changed(from, to);
      return `${from}_${to}`;
    },
    refreshVideoNode: id => calls.refreshed.push(id),
    refreshComfyNode: id => calls.refreshed.push(id),
    getOutput: id => outputs[id],
    saveState: () => { calls.saved += 1; },
    showMessage: message => calls.messages.push(message),
  });
  return { api, canvas, calls, outputs };
}

const finished = { status: 'succeeded', taskId: 'pid-1', videoPaths: ['/video/comfy_abc_wan.mp4'],
  videoMetadata: { width: 848, height: 480, fps: 16, duration_seconds: 5.06 } };

test('connection domain allows video → comfy and a single comfy → video source', () => {
  const { targets, policy } = loadModule();
  assert.deepEqual([...targets.comfy], ['video']);
  assert.deepEqual([...targets.video], ['comfy']);
  assert.equal(policy({ type: 'comfy' }, { type: 'video' }).replaceAllInputs, true);
  assert.equal(policy({ type: 'video' }, { type: 'comfy' }).inputRole, 'video');
  assert.equal(policy({ type: 'video' }, { type: 'comfy' }).single, undefined);
  assert.equal(policy({ type: 'image' }, { type: 'comfy' }), null);
});

test('only connected videos with media become workflow inputs', () => {
  const { api } = canvasHarness();
  assert.deepEqual(JSON.parse(JSON.stringify(api.connectedVideoReferences('comfy1'))),
    [{ nodeId: 'src', url: '/video/in.mp4', name: 'in.mp4' }]);
  assert.equal(api.connectedVideoCount('comfy1'), 2);
});

test('a finished Comfy video creates and fills a video node once', () => {
  const { api, canvas, calls } = canvasHarness();
  assert.equal(api.publish('comfy1', finished), 1);
  const created = canvas.nodes.new1;
  assert.equal(created.type, 'video');
  assert.equal(created.mediaUrl, '/video/comfy_abc_wan.mp4');
  assert.equal(created.mediaName, 'comfy_abc_wan.mp4');
  assert.equal(created.mimeType, 'video/mp4');
  assert.equal(created.sourceTaskId, 'pid-1');
  assert.equal(created.mediaWidth, 848);
  assert.equal(created.fps, 16);
  assert.ok(canvas.edges.some(edge => edge.from === 'comfy1' && edge.to === 'new1'));
  assert.equal(api.publish('comfy1', finished), 0, 'repeated polls must not rewrite the node');
  assert.equal(calls.saved, 1);
  assert.equal(api.publish('comfy1', { ...finished, videoPaths: [] }), 0);
});

test('connecting a video node after completion fills only that node', () => {
  const { api, canvas, outputs } = canvasHarness();
  outputs.comfy1 = finished;
  canvas.nodes.target = { id: 'target', type: 'video', x: 600, y: 0, width: 400, height: 260 };
  canvas.edges.push({ id: 'e3', from: 'comfy1', to: 'target' });
  api.connections.changed('comfy1', 'target');
  assert.equal(canvas.nodes.target.mediaUrl, '/video/comfy_abc_wan.mp4');
  assert.equal(Object.keys(canvas.nodes).some(id => id.startsWith('new')), false);
});

test('video → comfy refreshes the Comfy node input summary', () => {
  const { api, calls } = canvasHarness();
  api.connections.changed('src', 'comfy1');
  assert.deepEqual(calls.refreshed, ['comfy1']);
  assert.equal(calls.messages.length, 1);
});

test('video workflows allocate no image output nodes and Comfy config keeps its ports', () => {
  const source = read('frontend/scripts/desktop-canvas-generation-config.js');
  const context = vm.createContext({ DesktopState: { normalizeGptTaskType: () => 'image', clamp: () => 1 } });
  vm.runInContext(`${extractFunction(source, 'expectedImageOutputCount')}; this.count = expectedImageOutputCount;`, context);
  assert.equal(context.count({ outputKind: 'video', expectedImageOutputCount: 2 }), 0);
  assert.equal(context.count({ outputKind: 'image', expectedImageOutputCount: 2 }), 2);
  assert.match(source, /当前 Comfy 工作流需要连接一个视频节点/);
  assert.match(source, /referenceVideos: videoReferences/);
  // Comfy runs read parameter overrides through an injected port; dropping it broke every Comfy run.
  const deps = source.slice(source.indexOf('function create({'), source.indexOf('}) {'));
  assert.match(deps, /\bcomfyWorkflowParameterOverrides,/);
  const host = read('frontend/scripts/desktop-canvas.js');
  const hostCall = host.slice(host.indexOf('window.DesktopCanvasGenerationConfig.create({'));
  assert.match(hostCall.slice(0, hostCall.indexOf('});')), /\bcomfyWorkflowParameterOverrides,/);
});

test('video uploads stay same-origin and send only ComfyUI input names', async () => {
  const source = read('frontend/scripts/desktop-api.js');
  const requests = [];
  const client = {
    blob: async url => { requests.push(['blob', url]); return new Blob([new Uint8Array(32)]); },
    request: async (url, options) => {
      requests.push(['request', url, options.method]);
      return { ok: true, status: 200, json: async () => ({ name: 'miniapp_1_in.mp4' }) };
    },
  };
  const context = vm.createContext({ window: { location: { href: 'http://127.0.0.1:18463/desktop.html', origin: 'http://127.0.0.1:18463' } },
    URL, Blob, fetch: async () => { throw new Error('unexpected fetch'); }, encodeURIComponent });
  vm.runInContext(`async ${extractFunction(source, 'uploadComfyVideo')}; this.upload = uploadComfyVideo;`, context);

  assert.equal(await context.upload(client, { url: '/video/in.mp4', name: 'in.mp4' }), 'miniapp_1_in.mp4');
  assert.deepEqual(requests, [['blob', '/video/in.mp4'], ['request', '/api/comfy/upload_video?name=in.mp4', 'POST']]);
  await assert.rejects(context.upload(client, { url: 'https://evil.example/v.mp4' }), /本地视频节点/);
  assert.equal(requests.length, 2, 'a foreign URL must never be requested with the auth client');
  assert.match(source, /videos,\n/);
});

test('the module loads before the canvas host with cache keys and is wired in', () => {
  const html = read('frontend/desktop.html');
  const moduleIndex = html.indexOf('scripts/desktop-canvas-comfy-video.js');
  assert.ok(moduleIndex > 0 && moduleIndex < html.indexOf('scripts/desktop-canvas.js?'));
  for (const file of ['desktop-canvas-comfy-video.js', 'desktop-canvas.js', 'desktop-api.js', 'desktop-results.js',
    'desktop-canvas-generation-config.js', 'desktop-canvas-model-nodes.js', 'desktop-i18n.js']) {
    assert.ok(hasCacheKey(html, `scripts/${file}`), file);
  }
  const host = read('frontend/scripts/desktop-canvas.js');
  assert.match(host, /canvasMoss\.connections, canvasComfyVideo\.connections\)/);
  assert.match(host, /populateResultVideoNodes: \(resultNodeId, output\) => canvasComfyVideo\.publish\(resultNodeId, output\)/);
  const results = read('frontend/scripts/desktop-results.js');
  assert.match(results, /output\.videoPaths = Array\.isArray\(task\?\.video_paths\)/);
  assert.match(results, /populateResultVideoNodes\?\.\(resultNodeId, output\)/);
  const resultsContext = vm.createContext({});
  vm.runInContext(`function uniqueFiles(list) { return [...new Set(list)]; }
    function resultFileToImagePath(task, name) { return name ? '/image/' + name : ''; }
    ${extractFunction(results, 'normalizeTaskImagePaths')}; this.paths = normalizeTaskImagePaths;`, resultsContext);
  const videoTask = { result_file: 'comfy_x.mp4', image_paths: [], video_paths: ['/video/comfy_x.mp4'] };
  assert.deepEqual([...resultsContext.paths(videoTask, ['comfy_x.mp4'])], []);
  assert.deepEqual([...resultsContext.paths({ result_file: 'a.png', image_paths: [] }, ['a.png'])], ['/image/a.png']);
  const i18n = read('frontend/scripts/desktop-i18n.js');
  for (const text of ['视频已接入 Comfy 工作流节点。', '当前 Comfy 工作流需要连接一个视频节点', '请连接本地视频节点']) {
    assert.ok(i18n.includes(`'${text}':`), text);
  }
});
