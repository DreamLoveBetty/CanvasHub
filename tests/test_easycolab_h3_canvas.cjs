const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const scripts = path.join(__dirname, '../frontend/scripts');
const frontend = path.join(__dirname, '../frontend');
const read = name => fs.readFileSync(path.join(scripts, name), 'utf8');

const context = { window: {} };
vm.runInNewContext(read('desktop-easycolab-h3-model.js'), context);
const model = context.window.DesktopEasyColabH3Model;

test('EasyColab H3 图像和视频是独立 typed Canvas 节点且帧数对齐 17k+5', () => {
  assert.deepEqual(Array.from(model.TYPES), ['easycolab_h3_image', 'easycolab_h3_video']);
  assert.equal(model.MENU_ITEMS.length, 2);
  assert.equal(model.snapFrames(56), 56);
  assert.equal(model.snapFrames(120), 124);
  assert.equal(model.snapFrames(1), 22);
  for (const type of model.TYPES) {
    const node = model.normalize({ id: 'test', type, modelId: '', parameters: null });
    assert.ok(node.width >= 600);
    assert.ok(node.height >= 400);
    assert.ok(node.modelId);
    assert.deepEqual(Object.keys(node.parameters), []);
  }
});

test('EasyColab H3 节点仅展示模型参数，主提示词与媒体只从画布连线读取', () => {
  const sandbox = { window: { addEventListener() {} } };
  vm.runInNewContext(read('desktop-canvas-easycolab-h3.js'), sandbox);
  const controller = sandbox.window.DesktopCanvasEasyColabH3.create({ model });
  for (const type of model.TYPES) {
    const html = controller.nodeHtml({ id: 'ec-test', type, parameters: {} });
    assert.doesNotMatch(html, /<textarea|type="file"|data-easycolab-h3-file/);
    assert.match(html, /data-easycolab-h3-source-hint/);
    assert.match(html, /data-easycolab-h3-slots/);
    assert.match(html, /class="desk-generation-action desk-easycolab-h3__run"/);
    for (const mid of ['minimax_h3_10eros_max', 'minimax_h3_sulphur3', 'minimax_h3', 'minimax_h3_image']) {
      assert.match(html, new RegExp(`value="${mid}"`));
    }
  }
  const s3Html = controller.nodeHtml({ id: 'ec-s3', type: 'easycolab_h3_video', modelId: 'minimax_h3_sulphur3', parameters: {} });
  assert.match(s3Html, /data-easycolab-h3-field="corrector_enabled"/);
  assert.match(s3Html, /data-easycolab-h3-field="corrector_strength"/);
  assert.match(s3Html, /data-easycolab-h3-field="corrector_budget_fraction"/);
  assert.match(s3Html, /data-easycolab-h3-field="fps"/);
  assert.match(s3Html, /data-easycolab-h3-field="soundscape_prompt"/);
  assert.match(s3Html, /data-easycolab-h3-field="music_prompt"/);
  assert.match(s3Html, /data-easycolab-h3-field="negative_prompt"/);
  const source = read('desktop-canvas-easycolab-h3.js');
  assert.match(source, /getTextNodes\(s\.id\)\.map\(node => materializeText\(node\)\)/);
  assert.doesNotMatch(source, /s.node.prompt|data-easycolab-h3-file/);
});

test('连线策略仅允许正确的输入素材与输出节点类型', () => {
  for (const source of ['text', 'image', 'image_group']) {
    for (const target of model.TYPES) {
      assert.ok(model.policy({ type: source }, { type: target }));
    }
  }
  assert.ok(model.policy({ type: 'audio' }, { type: 'easycolab_h3_video', modelId: 'minimax_h3_10eros_max' }));
  assert.ok(model.policy({ type: 'audio' }, { type: 'easycolab_h3_image', modelId: 'minimax_h3_10eros_max' }));
  assert.match(
    model.policy({ type: 'audio' }, { type: 'easycolab_h3_image', modelId: 'minimax_h3_image' })?.reject || '',
    /视频模型/
  );
  assert.ok(model.policy({ type: 'easycolab_h3_image', modelId: 'minimax_h3_image' }, { type: 'image' }));
  assert.ok(model.policy({ type: 'easycolab_h3_image', modelId: 'minimax_h3_sulphur3' }, { type: 'video' }));
  assert.ok(model.policy({ type: 'easycolab_h3_video', modelId: 'minimax_h3_10eros_max' }, { type: 'video' }));
  assert.ok(model.policy({ type: 'easycolab_h3_video', modelId: 'minimax_h3_image' }, { type: 'image' }));
  for (const [source, target] of [
    ['video', 'easycolab_h3_image'],
    ['video', 'easycolab_h3_video'],
    ['upscale', 'easycolab_h3_video']
  ]) {
    assert.equal(model.policy({ type: source }, { type: target }), null);
  }
  assert.match(
    model.policy({ type: 'easycolab_h3_image', modelId: 'minimax_h3_image' }, { type: 'video' })?.reject || '',
    /图片节点/
  );
  assert.match(
    model.policy({ type: 'easycolab_h3_video', modelId: 'minimax_h3_10eros_max' }, { type: 'image' })?.reject || '',
    /视频节点/
  );
});

test('连接器对 EasyColab 模型种类不匹配执行拒绝、菜单过滤，并在切换模型后放行', () => {
  const messages = [];
  const state = {
    canvas: {
      scale: 1,
      nodes: {
        aud: { id: 'aud', type: 'audio', x: 0, y: 0, width: 200, height: 100 },
        ecImg: { id: 'ecImg', type: 'easycolab_h3_image', modelId: 'minimax_h3_image', x: 300, y: 0, width: 680, height: 460 },
        img: { id: 'img', type: 'image', x: 1100, y: 0, width: 400, height: 300 },
        vid: { id: 'vid', type: 'video', x: 1100, y: 400, width: 320, height: 400 }
      },
      edges: []
    }
  };
  const noop = () => {};
  const ctx = {
    document: { querySelector: () => null, querySelectorAll: () => [] },
    DesktopState: { state, saveSettings: noop },
    DesktopResults: { showTransientMessage: msg => messages.push(msg) },
    DesktopLayoutEditor: {}
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(read('desktop-easycolab-h3-model.js'), ctx);
  vm.runInContext(read('desktop-canvas-geometry.js'), ctx);
  vm.runInContext(read('desktop-canvas-connections.js'), ctx);

  const h3 = ctx.window.DesktopEasyColabH3Model;
  const domainConnections = ctx.window.DesktopCanvasConnections.combineDomains({
    targets: h3.targets,
    policy: h3.policy,
    changed: noop,
    removed: noop
  });
  const api = ctx.window.DesktopCanvasConnections.create({
    ...ctx.window.DesktopCanvasGeometry,
    LINK_VIEWBOX: '0 0 1600 1000',
    NODE_MENU_ITEMS: ['image', 'video', 'easycolab_h3_image', 'easycolab_h3_video'].map(type => ({ type })),
    domainConnections,
    activeInteractionRef: { current: null },
    pendingConnectionDropPointRef: { current: null },
    contextMenuConnectionSourceAnchorRef: { current: null },
    contextMenuConnectionSourceIdRef: { current: '' },
    contextMenuConnectionSourceSideRef: { current: 'right' },
    contextMenuElRef: { current: null },
    edgeMenuElRef: { current: null },
    hoveredEdgeIdRef: { current: '' },
    selectedEdgeIdRef: { current: '' },
    els: {},
    escapeHtml: String,
    nodeMenuButtonHtml: () => '',
    getNodeState: id => state.canvas.nodes[id],
    getNodeElement: () => null,
    screenToWorld: (x, y) => ({ x, y }),
    syncNodeEdgeStroke: noop,
    clearFloatingConnectionPort: noop,
    holdFloatingSwell: noop,
    releaseFloatingSwell: noop,
    renderMiniMap: noop,
    refreshImageReferenceTokens: noop,
    ensureTextNodeImageReferenceConnections: noop,
    assignImageOutputSlots: noop,
    refreshComfyNode: noop,
    refreshPoseNode: noop,
    refreshUpscaleNodeMode: noop,
    refreshVideoNode: noop,
    updateLayoutInputCount: noop,
    updateUpscaleInputCount: noop
  });

  assert.equal(api.canConnectNodes('aud', 'ecImg'), false);
  assert.equal(api.canConnectNodes('ecImg', 'vid'), false);
  assert.equal(api.canConnectNodes('ecImg', 'img'), true);
  assert.deepEqual(api.getConnectableNodeMenuItems('ecImg').map(i => i.type), ['image']);
  assert.deepEqual(api.getConnectableNodeMenuItems('aud').map(i => i.type), ['easycolab_h3_video']);

  assert.equal(api.connectNodes('aud', 'ecImg'), '');
  assert.equal(api.connectNodes('ecImg', 'vid'), '');
  assert.equal(state.canvas.edges.length, 0);
  assert.match(messages[0], /视频模型/);
  assert.match(messages[1], /图片节点/);

  state.canvas.nodes.ecImg.modelId = 'minimax_h3_10eros_max';
  assert.equal(api.canConnectNodes('aud', 'ecImg'), true);
  assert.equal(api.canConnectNodes('ecImg', 'vid'), true);
  assert.equal(api.canConnectNodes('ecImg', 'img'), false);
  assert.deepEqual(api.getConnectableNodeMenuItems('ecImg').map(i => i.type), ['video']);
  assert.deepEqual(api.getConnectableNodeMenuItems('aud').map(i => i.type), ['easycolab_h3_video']);
  assert.ok(api.connectNodes('aud', 'ecImg'));
  assert.ok(api.connectNodes('ecImg', 'vid'));
  assert.equal(state.canvas.edges.length, 2);
});

test('认证 API 适配不携带密码；桌面脚本顺序、样式与缓存版本正确', async () => {
  const calls = [];
  const api = {
    json: async (url, options) => { calls.push([url, options]); return { ok: true }; },
    request: async () => ({ ok: true, json: async () => ({ upload_token: 'tok' }) }),
    blob: async () => new Blob(['test'])
  };
  const sandbox = {
    window: {
      location: { href: 'http://localhost:18463/desktop.html', origin: 'http://localhost:18463' },
      DesktopTasks: { createClient: () => ({ submit() {}, progress() {}, cancel() {}, result() {} }) }
    },
    location: { href: 'http://localhost:18463/desktop.html', origin: 'http://localhost:18463' },
    DesktopApi: { getStatus: async () => ({}), importImageUrl: async () => ({ blob: new Blob(['test']) }) },
    DesktopTasks: { createClient: () => ({ submit() {}, progress() {}, cancel() {}, result() {} }) },
    api, URL, Blob
  };
  vm.runInNewContext(read('desktop-easycolab-h3-api.js'), sandbox);
  await sandbox.window.DesktopEasyColabH3API.catalog();
  await sandbox.window.DesktopEasyColabH3API.loadModel('minimax_h3_10eros_max');
  await sandbox.window.DesktopEasyColabH3API.submit({ kind: 'video', model_id: 'minimax_h3_10eros_max', prompt: 'test' });

  assert.equal(calls[0][0], '/api/easycolab_h3/catalog');
  assert.equal(calls[1][0], '/api/easycolab_h3/load_model');
  assert.equal(calls[2][0], '/api/easycolab_h3/submit');
  assert.doesNotMatch(JSON.stringify(calls), /password|authorization|secret/i);

  const html = fs.readFileSync(path.join(frontend, 'desktop.html'), 'utf8');
  const order = [
    'desktop-api.js',
    'desktop-easycolab-h3-model.js',
    'desktop-easycolab-h3-api.js',
    'desktop-canvas-easycolab-h3.js',
    'desktop-canvas.js'
  ];
  for (let i = 1; i < order.length; i++) {
    assert.ok(html.indexOf(order[i - 1]) < html.indexOf(order[i]), `load order: ${order[i - 1]} < ${order[i]}`);
  }
  for (const name of [
    'styles/desktop-easycolab-h3.css',
    'scripts/desktop-easycolab-h3-model.js',
    'scripts/desktop-easycolab-h3-api.js',
    'scripts/desktop-canvas-easycolab-h3.js',
    'scripts/desktop-canvas-connections.js',
    'scripts/desktop-canvas.js',
    'scripts/desktop-canvas-nodes.js',
    'scripts/desktop-canvas-workflow.js',
    'scripts/desktop-progress.js',
    'scripts/desktop-settings.js'
  ]) {
    assert.ok(hasCacheKey(html, name), name);
  }
  const css = fs.readFileSync(path.join(frontend, 'styles/desktop-easycolab-h3.css'), 'utf8');
  assert.doesNotMatch(css, /!important/);
  assert.match(css, /desk-node--easycolab-h3:has\(\.desk-select-shell\.is-open\)/);
  assert.match(read('desktop-settings.js'), /desktop:easycolab-h3-settings-updated/);
  assert.match(read('desktop-canvas-easycolab-h3.js'), /addEventListener\('desktop:easycolab-h3-settings-updated'/);
  const canvasSource = read('desktop-canvas.js');
  assert.match(canvasSource, /canvasEasyColabH3\.graphChanged\(\)/);
  assert.match(canvasSource, /canvasEasyColabH3\.disposeAll\(\)/);
  assert.match(canvasSource, /canvasEasyColabH3\.reconcile\(\)/);
  assert.match(canvasSource, /DesktopCanvasEasyColabH3\.create\(\{[\s\S]*updateLinkPath/);
  assert.match(read('desktop-canvas-easycolab-h3.js'), /s\.node\.height = measured;\s*updateLinkPath\?\.\(\);/);
});
