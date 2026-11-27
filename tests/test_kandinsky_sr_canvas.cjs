const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const scriptsDir = path.join(root, 'frontend/scripts');
const read = rel => fs.readFileSync(path.join(root, rel), 'utf8');

function loadContext(extra = {}) {
  const ctx = {
    window: {},
    DesktopState: {
      state: { canvas: { nodes: {}, edges: [] }, outputs: {} },
      isInFlight: s => ['queued', 'processing'].includes(s),
      isSuccess: s => ['succeeded', 'succeeded_no_telegram', 'telegram_failed'].includes(s),
      isFailure: s => s === 'failed',
    },
    setTimeout: () => 1,
    clearTimeout: () => {},
    api: extra.api || { json: async () => ({}) },
    ...extra,
  };
  for (const file of [
    'desktop-state-icon.js',
    'desktop-kandinsky-sr-model.js',
    'desktop-kandinsky-sr-api.js',
    'desktop-kandinsky-sr-tools.js',
    'desktop-canvas-kandinsky-sr.js',
  ]) {
    vm.runInNewContext(read(`frontend/scripts/${file}`), ctx);
  }
  return ctx;
}

test('Kandinsky SR model normalizes options, estimates tiles, and enforces connection policy', () => {
  const { window: w } = loadContext();
  const M = w.DesktopKandinskySrModel;

  const node = M.normalize({
    id: 'ksr_1',
    type: M.TYPE,
    kandinsky_sr: { upscale_factor: 4, creativity: 12, overlap: 0.375 },
    output: { telegramEnabled: true },
  });
  assert.equal(node.width, 480);
  assert.equal(node.height, 300);
  assert.equal(node.model, M.MODEL_ID);
  assert.equal(node.kandinsky_sr.upscale_factor, 4);
  assert.equal(node.kandinsky_sr.creativity, 8);
  assert.equal(node.kandinsky_sr.overlap, 0.375);
  assert.equal(node.output.telegramEnabled, true);

  const bad = M.normalize({ kandinsky_sr: { upscale_factor: 3, creativity: 'bad', overlap: 0.9 } });
  assert.deepEqual(JSON.parse(JSON.stringify(bad.kandinsky_sr)), { upscale_factor: 2, creativity: 4, overlap: 0.25 });

  assert.equal(M.estimateTiles(1024, 1024, 2, 0.25), 9);
  assert.equal(M.estimateTiles(1024, 1024, 4, 0.25), 25);
  assert.equal(M.estimateTiles(512, 512, 2, 0.25), 1);

  for (const src of ['image', 'input', 'comfy', 'krea2', 'qwen21', 'moss', 'layout', 'pose']) {
    assert.equal(M.policy({ type: src }, { type: M.TYPE }).single, true);
  }
  assert.equal(M.policy({ type: M.TYPE }, { type: 'image' }).replaceAllInputs, true);
  assert.equal(M.policy({ type: 'audio' }, { type: M.TYPE }), null);
});

test('Kandinsky SR API translates payloads to snake_case and checks single image', async () => {
  const calls = [];
  const { window: w } = loadContext({
    api: {
      json: async (route, opts) => {
        calls.push({ route, opts });
        return { ok: true, ready: true, download_bytes: 10450000000 };
      },
    },
  });

  const st = await w.DesktopKandinskySrAPI.status();
  assert.equal(st.ready, true);
  assert.equal(calls[0].route, '/api/kandinsky_sr/status');

  const client = {
    json: async (route, opts) => {
      calls.push({ route, body: JSON.parse(opts.body) });
      return { task_id: 'kandinsky_sr_abc' };
    },
  };
  await assert.rejects(
    w.DesktopKandinskySrAPI.submit(client, { config: {}, images: [] }),
    /请连接一张图片/
  );
  const receipt = await w.DesktopKandinskySrAPI.submit(client, {
    config: {
      prompt: 'test',
      params: { model: 'kandinsky-imagesr-2.0', kandinsky_sr: { upscale_factor: 4, creativity: 6, overlap: 0.125 } },
    },
    images: ['data:image/png;base64,AA=='],
    lineage: { source_node_id: 'img_1' },
    telegramEnabled: true,
  });
  assert.equal(receipt.task_id, 'kandinsky_sr_abc');
  assert.equal(calls[1].route, '/api/kandinsky_sr/run');
  assert.deepEqual(calls[1].body.options, { upscale_factor: 4, creativity: 6, overlap: 0.125 });
  assert.equal(calls[1].body.telegram_enabled, true);
});

test('Canvas Kandinsky SR controller renders controls, checks readiness, and stops chain on graph swap', async () => {
  const ctx = loadContext();
  const M = ctx.window.DesktopKandinskySrModel;
  let state = {
    canvas: {
      nodes: {
        src: { id: 'src', type: 'input' },
        k1: M.normalize({ id: 'k1', type: M.TYPE }),
        k2: M.normalize({ id: 'k2', type: M.TYPE }),
      },
      edges: [
        { from: 'src', to: 'k1' },
        { from: 'src', to: 'k2' },
      ],
    },
    outputs: {
      src: { imagePaths: ['/image/sample.png'], taskId: 'task_1' },
    },
  };

  let submissions = 0;
  const ctrl = ctx.window.DesktopCanvasKandinskySr.create({
    model: M,
    stateIcon: ctx.window.DesktopStateIcon,
    getState: () => state,
    getNodeElement: () => null,
    getReferences: () => [],
    outputReference: () => ({ title: 'sample.png' }),
    ensureOutputs: () => {},
    showError: () => {},
    submit: async () => {
      submissions += 1;
      state = { canvas: { nodes: {}, edges: [] }, outputs: {} };
    },
  });

  const html = ctrl.nodeHtml(state.canvas.nodes.k1);
  assert.ok(html.includes('data-ksr-field="upscale_factor"'));
  assert.ok(html.includes('data-ksr-field="creativity"'));
  assert.ok(html.includes('data-ksr-field="overlap"'));
  assert.ok(html.includes('data-ksr-telegram'));
  assert.ok(html.includes('data-result-run'));
  assert.ok(html.includes('data-progress-bar'));

  const cfg = ctrl.readConfig('k1');
  assert.equal(cfg.provider, 'kandinsky_sr');
  assert.equal(cfg.params.kandinsky_sr.upscale_factor, 2);

  await ctrl.runChains('src', { taskId: 'task_1', imagePaths: ['/image/a.png'] });
  assert.equal(submissions, 1);

  assert.equal(await ctrl.runChains('k1', { taskId: 'task_2', imagePaths: ['/image/b.png'] }), 0);
});

test('Settings Kandinsky SR tools card renders readiness and triggers prepare', async () => {
  const ctx = loadContext();
  let prepared = 0;
  const tools = ctx.window.DesktopKandinskySrTools.create({
    api: {
      status: async () => ({
        ok: true,
        ready: false,
        reasons: ['Kandinsky SR 环境尚未准备'],
        downloadBytes: 10450000000,
        modelVariant: 'Kandinsky ImageSR 2.0',
        preparation: { status: 'idle', stage: '', message: '', downloaded: 0, total: 0 },
      }),
      prepare: async () => {
        prepared += 1;
        return { preparation: { status: 'running', stage: 'environment', message: '创建隔离环境', downloaded: 0, total: 0 } };
      },
    },
    escapeHtml: s => String(s ?? ''),
    rerender: () => {},
    notify: () => {},
  });

  await tools.activate();
  const card = tools.render();
  assert.ok(card.includes('data-kandinsky-sr-tools'));
  assert.ok(card.includes('Kandinsky SR 2.0'));
  assert.ok(card.includes('data-kandinsky-sr-prepare'));

  const handled = tools.handleClick({
    target: { closest: sel => (sel === '[data-kandinsky-sr-prepare]' ? {} : null) },
    preventDefault: () => {},
  });
  assert.equal(handled, true);
  assert.equal(prepared, 1);
});

test('desktop.html loads Kandinsky SR CSS/scripts with cache keys before desktop-canvas.js', () => {
  const html = read('frontend/desktop.html');
  const canvasIdx = html.indexOf('scripts/desktop-canvas.js?');
  const graphiteCssIdx = html.indexOf('styles/desktop-graphite.css?');
  const ksrCssIdx = html.indexOf('styles/desktop-kandinsky-sr.css?');
  assert.ok(ksrCssIdx > 0 && ksrCssIdx < graphiteCssIdx);
  assert.ok(hasCacheKey(html, 'styles/desktop-kandinsky-sr.css'));

  for (const file of [
    'scripts/desktop-kandinsky-sr-model.js',
    'scripts/desktop-kandinsky-sr-api.js',
    'scripts/desktop-kandinsky-sr-tools.js',
    'scripts/desktop-canvas-kandinsky-sr.js',
  ]) {
    const idx = html.indexOf(file + '?');
    assert.ok(idx > 0 && idx < canvasIdx, file);
    assert.ok(hasCacheKey(html, file), file);
  }
});
