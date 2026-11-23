const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const scriptsDir = path.join(root, 'frontend/scripts');
const read = rel => fs.readFileSync(path.join(root, rel), 'utf8');

function loadModelAndView() {
  const ctx = { window: {} };
  for (const file of [
    'desktop-state-icon.js',
    'desktop-video-understand-model.js',
    'desktop-video-understand-view.js',
    'desktop-video-compose-model.js',
    'desktop-canvas-port-plates.js',
  ]) {
    const pre = file === 'desktop-video-compose-model.js'
      ? () => { vm.runInNewContext(read('frontend/scripts/desktop-video-compose-subtitles.js'), ctx); }
      : null;
    if (pre) pre();
    vm.runInNewContext(read(`frontend/scripts/${file}`), ctx);
  }
  return ctx.window;
}

function loadTransport(apiStub = {}) {
  const ctx = {
    window: { location: { href: 'http://localhost:18463/desktop.html', origin: 'http://localhost:18463' } },
    URL,
    Blob,
    api: apiStub,
  };
  vm.runInNewContext(read('frontend/scripts/desktop-video-understand-api.js'), ctx);
  return ctx.window.DesktopVideoUnderstandAPI;
}

test('video_understand model normalization, mode defaults, and snake_case request', () => {
  const w = loadModelAndView();
  const M = w.DesktopVideoUnderstandModel;

  const node = M.normalize({ id: 'vu_1', type: M.TYPE, mode: 'invalid', fps: 99, maxFrames: 2, totalPixels: 10, maxTokens: 99999 });
  assert.equal(node.width, 720);
  assert.equal(node.height, 460);
  assert.equal(node.mode, 'storyboard');
  assert.equal(node.fps, 4);
  assert.equal(node.maxFrames, 4);
  assert.equal(node.totalPixels, 262144);
  assert.equal(node.maxTokens, 8192);

  M.applyModeDefaults(node, 'prompt_reverse');
  assert.equal(node.mode, 'prompt_reverse');
  assert.equal(node.fps, 1);
  assert.equal(node.maxFrames, 64);
  assert.equal(node.shotAnchors, false);

  M.applyModeDefaults(node, 'h3_prompt');
  assert.equal(node.mode, 'h3_prompt');
  assert.equal(node.fps, 2);
  assert.equal(node.maxFrames, 96);
  assert.equal(node.totalPixels, 4194304);
  assert.equal(node.maxTokens, 4096);
  assert.equal(node.shotAnchors, true);

  const req = M.request(node, '/video/clip.mp4', '上游文本指令');
  assert.equal(req.video_url, '/video/clip.mp4');
  assert.equal(req.mode, 'h3_prompt');
  assert.equal(req.prompt, '上游文本指令');
  assert.equal(req.use_audio, true);
  assert.equal(req.shot_anchors, true);
  assert.equal(req.max_frames, 96);
  assert.equal(req.maxFrames, undefined);
});

test('video_understand connection policy accepts video/text/compose and blocks bidirectional text loop', () => {
  const w = loadModelAndView();
  const M = w.DesktopVideoUnderstandModel;
  const C = w.DesktopVideoComposeModel;

  assert.ok(C.CONSUMERS.includes(M.TYPE));
  assert.ok(M.policy({ id: 'v1', type: 'video' }, { id: 'u1', type: M.TYPE }));
  assert.ok(M.policy({ id: 't1', type: 'text' }, { id: 'u1', type: M.TYPE }, {}, []));
  assert.ok(M.policy({ id: 'u1', type: M.TYPE }, { id: 't2', type: 'text' }, {}, []));

  // Reject creating u1 -> t1 when t1 -> u1 already exists
  const loopOut = M.policy(
    { id: 'u1', type: M.TYPE },
    { id: 't1', type: 'text' },
    {},
    [{ from: 't1', to: 'u1' }]
  );
  assert.ok(loopOut?.reject);

  // Reject creating t2 -> u1 when u1 -> t2 already exists
  const loopIn = M.policy(
    { id: 't2', type: 'text' },
    { id: 'u1', type: M.TYPE },
    {},
    [{ from: 'u1', to: 't2' }]
  );
  assert.ok(loopIn?.reject);
});

test('video_understand transport validates same-origin video URLs and translates status', async () => {
  const api = loadTransport({
    async json(url) {
      if (url === '/api/video_understand/status') {
        return {
          ok: true,
          engine: 'wemm_video_mlx',
          model_variant: 'WeMM-Video 35B-A3B MLX 6-bit',
          ready: true,
          reasons: [],
          prepared_at: 1700000000,
          download_bytes: 32000000000,
          preparation: { status: 'idle', stage: '', message: '', downloaded: 0, total: 0 },
          modes: { storyboard: {} },
        };
      }
      throw new Error('unexpected ' + url);
    },
  });

  for (const okUrl of ['/video/demo.mp4', '/api/video_control/artifact?id=1&name=a.mp4', '/api/topaz_video/source?id=2']) {
    assert.equal(api.sourceUrl(okUrl), okUrl);
  }
  for (const badUrl of ['https://evil.invalid/a.mp4', 'file:///tmp/a.mp4', '/api/settings', '/video/']) {
    assert.throws(() => api.sourceUrl(badUrl));
  }

  const st = await api.status();
  assert.equal(st.ready, true);
  assert.equal(st.modelVariant, 'WeMM-Video 35B-A3B MLX 6-bit');
  assert.equal(st.preparedAt, 1700000000);
});

test('video_understand view renders shared 72px generate key and stays registered in graphite NOTCHED_NODES', () => {
  const w = loadModelAndView();
  const view = w.DesktopVideoUnderstandView.create({
    model: w.DesktopVideoUnderstandModel,
    escapeHtml: s => String(s ?? ''),
    stateIcon: w.DesktopStateIcon,
  });
  const html = view.html(w.DesktopVideoUnderstandModel.normalize({ id: 'vu_1', type: 'video_understand' }));
  assert.match(html, /class="desk-node desk-node--video-understand"/);
  assert.match(html, /value="h3_prompt"/);
  assert.match(html, /H3 提示词反推/);
  assert.match(html, /desk-generation-action/);
  assert.match(html, /data-understand-progress/);
  assert.match(html, /data-understand-env-banner/);
  assert.ok(w.DesktopCanvasPortPlates.NOTCHED_NODES.includes('.desk-node--video-understand'));
  assert.ok(read('frontend/styles/desktop-graphite.css').includes('.desk-node--video-understand'));
});

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function controllerFixture() {
  const state = { nodes: {}, edges: [] };
  const elements = new Map();
  const reports = [];
  const timers = new Map();
  const jobs = new Map();
  const cancelled = [];
  const writtenText = [];
  let seq = 0;
  let timer = 0;

  const ctx = {
    window: {},
    AbortController,
    setTimeout(fn) { const id = ++timer; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(read('frontend/scripts/desktop-video-understand-model.js'), ctx);
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-video-understand.js'), ctx);
  const M = ctx.window.DesktopVideoUnderstandModel;

  function makeEl() {
    return {
      fields: new Map(),
      listeners: new Map(),
      addEventListener(type, fn) { this.listeners.set(type, fn); },
      querySelector(sel) {
        if (!this.fields.has(sel)) this.fields.set(sel, { textContent: '', value: '' });
        return this.fields.get(sel);
      },
      querySelectorAll() { return []; },
    };
  }

  const api = {
    sourceUrl: u => u,
    status: async () => ({ ready: true, reasons: [], preparation: { status: 'idle' } }),
    uploadVideo: async () => ({
      mediaUrl: '/video/imported.mp4',
      mediaName: 'imported.mp4',
      mimeType: 'video/mp4',
      mediaWidth: 1280,
      mediaHeight: 720,
      fps: 24,
      durationSeconds: 5,
      fileSize: 1024,
    }),
    submit: async spec => {
      const id = String(++seq).padStart(32, 'a');
      const job = { id, status: 'queued', spec, result: null };
      jobs.set(id, job);
      return job;
    },
    job: async id => jobs.get(id),
    cancel: async id => {
      cancelled.push(id);
      const j = jobs.get(id);
      if (j) j.status = 'cancelled';
      return j;
    },
  };

  let controller;
  const addNode = type => {
    const id = `${type}_${++seq}`;
    state.nodes[id] = { id, type, x: 0, y: 0, width: 320, height: 220 };
    elements.set(id, makeEl());
    return id;
  };
  const connectNodes = (from, to) => {
    state.edges.push({ from, to });
    controller.connections.changed(from, to);
  };

  controller = ctx.window.DesktopCanvasVideoUnderstand.create({
    model: M,
    api,
    view: { html: () => '', paint() {} },
    getCanvas: () => state,
    getNodeState: id => state.nodes[id],
    getNodeElement: id => elements.get(id),
    addNode,
    connectNodes,
    refreshVideoNode() {},
    materializeText: n => String(n?.text || ''),
    writeTextNode(id, text) {
      state.nodes[id].text = text;
      writtenText.push({ id, text });
    },
    saveState() {},
    reportStatus: item => reports.push(item),
  });

  return {
    M,
    state,
    elements,
    reports,
    jobs,
    cancelled,
    writtenText,
    controller,
    connectNodes,
    async poll() {
      const callbacks = [...timers.values()];
      timers.clear();
      callbacks.forEach(fn => fn());
      await flush();
    },
  };
}

test('controller publishes markdown to auto-created text node, reads upstream text, and cancels on remove', async () => {
  const h = controllerFixture();
  h.state.nodes.vid = { id: 'vid', type: 'video', mediaUrl: '/video/clip.mp4', mediaName: 'clip.mp4' };
  h.state.nodes.prompt = { id: 'prompt', type: 'text', text: '找出所有镜头切换' };
  h.state.nodes.vu = h.M.normalize({ id: 'vu', type: 'video_understand', mode: 'custom', x: 100, y: 100 });
  h.elements.set('vu', h.elements.get('vu') || { addEventListener() {}, querySelector: () => ({ textContent: '' }), querySelectorAll: () => [] });
  h.state.edges.push({ from: 'vid', to: 'vu' }, { from: 'prompt', to: 'vu' });
  h.controller.reconcile();
  await flush();

  await h.controller.run('vu');
  await flush();

  const jobId = h.state.nodes.vu.jobId;
  assert.ok(jobId);
  assert.equal(h.jobs.get(jobId).spec.prompt, '找出所有镜头切换');

  h.jobs.get(jobId).status = 'succeeded';
  h.jobs.get(jobId).result = { text: '## 镜头表\nShot 01' };
  await h.poll();

  assert.equal(h.writtenText.length, 1);
  assert.equal(h.writtenText[0].text, '## 镜头表\nShot 01');
  const createdTextId = h.writtenText[0].id;
  assert.ok(h.state.edges.some(e => e.from === 'vu' && e.to === createdTextId));

  // Subsequent text node connection reuses completed result
  h.state.nodes.t2 = { id: 't2', type: 'text', text: '' };
  h.connectNodes('vu', 't2');
  assert.equal(h.state.nodes.t2.text, '## 镜头表\nShot 01');

  // Active job is cancelled when node is removed
  h.state.nodes.vu.status = 'running';
  h.controller.dispose('vu', true);
  assert.ok(h.cancelled.includes(jobId));
});

test('settings tools card renders readiness and triggers prepare', async () => {
  const ctx = { window: {}, setTimeout, clearTimeout };
  vm.runInNewContext(read('frontend/scripts/desktop-video-understand-tools.js'), ctx);
  let prepareCalled = false;
  const tools = ctx.window.DesktopVideoUnderstandTools.create({
    api: {
      async status() {
        return {
          ready: false,
          engine: 'wemm_video_mlx',
          modelVariant: 'WeMM-Video 35B-A3B MLX 6-bit',
          reasons: ['视频理解环境尚未准备'],
          downloadBytes: 31.4 * 1024 ** 3,
          preparation: { status: 'idle', stage: '', message: '', downloaded: 0, total: 0 },
        };
      },
      async prepare() {
        prepareCalled = true;
        return { preparation: { status: 'running', stage: 'environment', message: '创建中', downloaded: 0, total: 100 } };
      },
    },
    escapeHtml: s => String(s ?? ''),
    rerender() {},
    notify() {},
  });
  await tools.activate();
  const html = tools.render();
  assert.match(html, /视频理解（WeMM-Video 6-bit）/);
  assert.match(html, /data-video-understand-prepare/);
  const handled = tools.handleClick({
    target: { closest: sel => (sel === '[data-video-understand-prepare]' ? {} : null) },
    preventDefault() {},
  });
  assert.equal(handled, true);
  await flush();
  assert.equal(prepareCalled, true);
});

test('desktop.html includes cache keys and valid load order for all video_understand assets', () => {
  const html = read('frontend/desktop.html');
  const assets = [
    'styles/desktop-video-understand-geometry.css',
    'styles/desktop-video-understand.css',
    'scripts/desktop-video-understand-model.js',
    'scripts/desktop-video-understand-api.js',
    'scripts/desktop-video-understand-tools.js',
    'scripts/desktop-video-understand-view.js',
    'scripts/desktop-canvas-video-understand.js',
  ];
  for (const file of assets) {
    assert.ok(hasCacheKey(html, file), `missing cache key for ${file}`);
  }
  assert.ok(
    html.indexOf('styles/desktop-video-understand.css') < html.indexOf('styles/desktop-graphite.css'),
    'video_understand theme CSS loads before graphite'
  );
  assert.ok(
    html.indexOf('scripts/desktop-video-understand-model.js') < html.indexOf('scripts/desktop-canvas-video-understand.js')
      && html.indexOf('scripts/desktop-canvas-video-understand.js') < html.indexOf('scripts/desktop-canvas.js')
      && html.indexOf('scripts/desktop-video-understand-tools.js') < html.indexOf('scripts/desktop-settings.js'),
    'video_understand scripts load before canvas and settings hosts'
  );
});
