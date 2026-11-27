const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..');
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const escapeHtml = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plain = v => JSON.parse(JSON.stringify(v));

test('DesktopLocalExtensions registers menus, schemas, submit providers, history labels and domains dynamically', () => {
  const ctx = { window: {}, URL, Promise };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(read('frontend/scripts/desktop-local-extensions.js'), ctx);
  const ext = ctx.window.DesktopLocalExtensions;

  const sampleMenu = { type: 'ext_sample', title: 'Sample Node', subtitle: 'Local Ext', icon: '<svg/>', paletteGroup: 'enhance' };
  assert.equal(ext.register({
    id: 'sample',
    menuItems: [sampleMenu],
    outputStateTypes: [{ type: 'ext_sample', outputType: 'ext_sample' }],
    imageOutputSourceTypes: ['ext_sample'],
    notchedSelectors: ['.desk-node--ext-sample'],
    stepperScopes: ['.desk-ext-panel'],
    selectVariants: [{ selector: '.desk-ext-panel', variant: 'ext-workbench' }],
    videoSourcePaths: ['/api/sample_video/source', '/api/sample_video/artifact'],
    submitProviders: { ext_sample: (_c, p) => ({ ok: true, prompt: p.config.prompt }) },
    historyProviders: [{ key: 'ext_sample', label: 'Sample Ext', match: t => t === 'ext_sample' }],
    resultLabels: { ext_sample: 'Sample · Enhanced' },
    definitions: [{
      types: ['ext_sample'],
      migrate: node => { if (node.legacyExt) { node.type = 'ext_sample'; return true; } return false; },
      normalize: node => { node.normalized = true; return node; },
    }],
    createCanvasDomain: host => ({ id: 'sample', hostSeen: Boolean(host?.mark) }),
  }), true);

  assert.deepEqual(plain(ext.nodeTypes()), ['ext_sample']);
  assert.equal(ext.outputTypeFor('ext_sample'), 'ext_sample');
  assert.equal(ext.isImageOutputSourceType('ext_sample'), true);
  assert.deepEqual(plain(ext.notchedSelectors()), ['.desk-node--ext-sample']);
  assert.deepEqual(plain(ext.stepperScopes()), ['.desk-ext-panel']);
  assert.equal(ext.matchSelectVariant({ closest: sel => sel === '.desk-ext-panel' }), 'ext-workbench');
  assert.equal(ext.matchHistoryProvider('ext_sample', '', {}), 'ext_sample');
  assert.equal(ext.historyProviderLabel('ext_sample'), 'Sample Ext');
  assert.equal(ext.resultLabel('ext_sample'), 'Sample · Enhanced');
  assert.deepEqual(plain(ext.getSubmitProvider('ext_sample')(null, { config: { prompt: 'hi' } })), { ok: true, prompt: 'hi' });

  const node = { legacyExt: true };
  assert.equal(ext.migrateNode(node), true);
  assert.equal(node.type, 'ext_sample');
  assert.equal(ext.normalizeNode(node), true);
  assert.equal(node.normalized, true);
  assert.deepEqual(plain(ext.createCanvasDomains({ mark: 1 })), [{ id: 'sample', hostSeen: true }]);

  ext.clear();
  assert.deepEqual(plain(ext.menuItems()), []);
  assert.deepEqual(plain(ext.videoSourcePaths()), []);
});

test('palette groups place local extension menuItems via paletteGroup without mutating catalog entries', () => {
  const stored = new Map();
  const ctx = {
    document: { activeElement: null },
    setTimeout: () => 1,
    clearTimeout: () => {},
    localStorage: { getItem: k => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)) },
    URL,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(read('frontend/scripts/desktop-local-extensions.js'), ctx);
  ctx.window.DesktopLocalExtensions.register({
    id: 'sample',
    menuItems: [{ type: 'ext_enhancer', title: 'Ext Enhancer', subtitle: '4x', icon: '<svg/>', paletteGroup: 'enhance' }],
  });
  for (const name of ['krea2-control', 'krea2-model', 'qwen21-model', 'moss-model', 'cyimg-model', 'easycolab-h3-model',
    'canvas-audio', 'video-control-model', 'video-understand-model', 'video-compose-subtitles', 'video-compose-model', 'kandinsky-sr-model', 'pose-model', 'music-model', 'canvas-nodes']) {
    vm.runInContext(read(`frontend/scripts/desktop-${name}.js`), ctx);
  }
  const catalogSource = read('frontend/scripts/desktop-canvas.js').match(/const NODE_MENU_ITEMS = (\[[\s\S]+?\n  \]);/)[1];
  const catalog = vm.runInContext(catalogSource, ctx);
  const palette = {
    markup: '', groups: [], buttons: [],
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    querySelector: () => null, contains: () => false,
    get innerHTML() { return this.markup; },
    set innerHTML(v) {
      this.markup = v;
      this.groups = [...v.matchAll(/<details\b([^>]*)>([\s\S]*?)<\/details>/g)].map(([, attrs, body]) => ({
        dataset: { nodeMenuGroup: attrs.match(/data-node-menu-group="([^"]+)"/)[1] },
        types: [...body.matchAll(/data-add-node="([^"]+)"/g)].map(m => m[1]),
      }));
    },
    querySelectorAll: () => [],
  };
  const api = ctx.DesktopCanvasNodes.create({
    NODE_MENU_ITEMS: catalog,
    els: { deskNodePalette: palette, deskNodeToolBtn: { setAttribute() {}, focus() {} } },
    escapeHtml,
    nodePaletteCloseTimerRef: { current: 0 },
    ORDINARY_MENU_CLOSE_FALLBACK_MS: 200,
  });
  api.renderNodePaletteItems();
  const enhanceGroup = palette.groups.find(g => g.dataset.nodeMenuGroup === 'enhance');
  assert.deepEqual(plain(enhanceGroup.types), ['upscale', 'kandinsky_sr', 'ext_enhancer']);
  assert.equal(api.normalizeNodeMenuType('ext_enhancer'), 'ext_enhancer');
});

test('port plates, number stepper, and video source allowlists consume DesktopLocalExtensions dynamically', () => {
  const ctx = {
    window: {
      location: { href: 'http://127.0.0.1:18463/desktop.html', origin: 'http://127.0.0.1:18463' },
      document: { readyState: 'loading', addEventListener() {} },
    },
    document: { readyState: 'loading', addEventListener() {} },
    Node: { ELEMENT_NODE: 1, DOCUMENT_NODE: 9 },
    URL,
    URLSearchParams,
    Promise,
  };
  vm.createContext(ctx);
  vm.runInContext(read('frontend/scripts/desktop-local-extensions.js'), ctx);
  vm.runInContext(read('frontend/scripts/desktop-canvas-port-plates.js'), ctx);
  vm.runInContext(read('frontend/scripts/desktop-number-stepper.js'), ctx);
  vm.runInContext(read('frontend/scripts/desktop-video-edit-api.js'), ctx);
  vm.runInContext(read('frontend/scripts/desktop-video-control-api.js'), ctx);
  vm.runInContext(read('frontend/scripts/desktop-video-understand-api.js'), ctx);

  const extEl = { matches: sel => sel.split(',').map(s => s.trim()).includes('.desk-node--ext-gen') };
  assert.equal(ctx.window.DesktopCanvasPortPlates.notchOf(extEl), null);
  assert.equal(ctx.window.DesktopVideoEditAPI.sourceUrl('/api/ext_vid/source?id=1'), '');
  assert.throws(() => ctx.window.DesktopVideoControlAPI.sourceUrl('/api/ext_vid/source?id=1'));
  assert.throws(() => ctx.window.DesktopVideoUnderstandAPI.sourceUrl('/api/ext_vid/artifact?id=1&name=a.mp4'));

  // Register AFTER core scripts parsed (mirrors real desktop.html load order or dynamic plugins).
  ctx.window.DesktopLocalExtensions.register({
    id: 'ext_vid',
    notchedSelectors: ['.desk-node--ext-gen'],
    stepperScopes: ['.desk-ext-workbench'],
    videoSourcePaths: ['/api/ext_vid/source', '/api/ext_vid/artifact'],
  });

  assert.equal(ctx.window.DesktopCanvasPortPlates.notchOf(extEl), ctx.window.DesktopCanvasPortPlates.NOTCH);
  assert.equal(ctx.window.DesktopVideoEditAPI.sourceUrl('/api/ext_vid/source?id=1'), '/api/ext_vid/source?id=1');
  assert.equal(ctx.window.DesktopVideoControlAPI.sourceUrl('/api/ext_vid/source?id=1'), '/api/ext_vid/source?id=1');
  assert.equal(ctx.window.DesktopVideoUnderstandAPI.sourceUrl('/api/ext_vid/artifact?id=1&name=a.mp4'), '/api/ext_vid/artifact?id=1&name=a.mp4');

  let queries = [];
  const fakeRoot = {
    nodeType: 1,
    matches: () => false,
    querySelectorAll(sel) { queries.push(sel); return []; },
  };
  ctx.window.DesktopNumberStepper.enhanceIn(fakeRoot);
  assert.match(queries[0], /\.desk-ext-workbench/);
});

test('DesktopLocalExtensions.createModelTools collects settings cards and desktop-settings wires extensionModelTools', () => {
  const ctx = { window: {}, URL, Promise };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(read('frontend/scripts/desktop-local-extensions.js'), ctx);
  const ext = ctx.window.DesktopLocalExtensions;

  ext.register({
    id: 'single_tool_ext',
    createModelTools: host => ({
      tab: 'moss',
      label: 'Single Tool',
      render: () => `<section data-ext-tool>${host.escapeHtml('ok')}</section>`,
      activate: async () => 'activated',
    }),
  });
  ext.register({
    id: 'multi_tool_ext',
    createModelTools: () => [
      { render: () => '<section data-ext-default-tab>common</section>' },
      null,
      { tab: 'krea2', render: () => '<section data-ext-krea2>krea2</section>' },
    ],
  });

  const tools = ext.createModelTools({ escapeHtml });
  assert.equal(tools.length, 3);
  assert.deepEqual(plain(tools.map(t => t.tab)), ['moss', 'common', 'krea2']);
  assert.equal(tools[0].render(), '<section data-ext-tool>ok</section>');

  const settingsSrc = read('frontend/scripts/desktop-settings.js');
  assert.match(settingsSrc, /window\.DesktopLocalExtensions\?\.createModelTools\?\./);
  assert.match(settingsSrc, /renderExtensionModelTools\('common'\)/);
  assert.match(settingsSrc, /extensionModelTools\.forEach\(tool => tool\.deactivate\?\.\(\)\)/);
  assert.match(settingsSrc, /extensionModelTools\.some\(tool => tool\.handleClick\?\.\(event\)\)/);
  assert.match(settingsSrc, /extensionModelTools\.some\(tool => tool\.handleInput\?\.\(event\)\)/);
});
