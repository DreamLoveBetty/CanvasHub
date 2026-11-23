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
  assert.equal(model.policy({ type: 'audio' }, { type: 'easycolab_h3_image', modelId: 'minimax_h3_image' }), null);
  assert.ok(model.policy({ type: 'easycolab_h3_image', modelId: 'minimax_h3_image' }, { type: 'image' }));
  assert.ok(model.policy({ type: 'easycolab_h3_image', modelId: 'minimax_h3_sulphur3' }, { type: 'video' }));
  assert.ok(model.policy({ type: 'easycolab_h3_video', modelId: 'minimax_h3_10eros_max' }, { type: 'video' }));
  assert.ok(model.policy({ type: 'easycolab_h3_video', modelId: 'minimax_h3_image' }, { type: 'image' }));
  for (const [source, target] of [
    ['video', 'easycolab_h3_image'],
    ['video', 'easycolab_h3_video'],
    ['topaz', 'easycolab_h3_video']
  ]) {
    assert.equal(model.policy({ type: source }, { type: target }), null);
  }
  assert.equal(model.policy({ type: 'easycolab_h3_image', modelId: 'minimax_h3_image' }, { type: 'video' }), null);
  assert.equal(model.policy({ type: 'easycolab_h3_video', modelId: 'minimax_h3_10eros_max' }, { type: 'image' }), null);
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
});
