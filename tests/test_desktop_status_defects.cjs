// Regression for the desktop UI defects fixed on 2026-10-30: live fallback/service chips, the
// result pill outcome, confirmation before destructive node removal, the dead Google polish
// button, the progress track tooltip, input-footer alignment, neutral pills, option labels,
// text-node drawer copy and image reference tokens that keep the editor line height.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const results = read('frontend/scripts/desktop-results.js');
const nodes = read('frontend/scripts/desktop-canvas-nodes.js');
const canvas = read('frontend/scripts/desktop-canvas.js');

// Slice one named function (with its `async` keyword) out of a module source.
function fn(source, name) {
  let start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing ${name}`);
  if (source.slice(start - 6, start) === 'async ') start -= 6;
  let depth = 0;
  for (let i = source.indexOf(') {', start) + 2; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unbalanced ${name}`);
}

function chip(dot = null) {
  const classes = new Set(['desk-status-chip']);
  return {
    classes, dataset: {}, title: '', textContent: '', children: [],
    classList: {
      add: (...names) => names.forEach(name => classes.add(name)),
      remove: (...names) => names.forEach(name => classes.delete(name)),
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
    },
    replaceChildren(...items) { this.children = items; this.textContent = items.filter(item => typeof item === 'string').join(''); },
    querySelector: () => dot,
  };
}

function statusHarness(getChatgptPoolStatus) {
  const dot = { className: 'desk-live-dot' };
  const els = { deskServiceStatus: chip(dot), deskSidecarStatus: chip(), deskFallbackStatus: chip() };
  els.deskServiceStatus.classes.add('desk-status-chip--service');
  const tones = results.match(/const STATUS_TONE_CLASSES = \[[^\]]*\];/)[0];
  const names = ['setStatusChipTone', 'setSidecarStatus', 'setFallbackStatus', 'setServiceStatus', 'isNetworkFailure', 'renderSidecarStatus', 'refreshSidecarStatus'];
  const context = vm.createContext({ els, window: { location: { port: '18463', protocol: 'http:' }, DesktopApi: { getChatgptPoolStatus } } });
  const api = vm.runInContext(`${tones} let serviceLiveDot = null; ${names.map(name => fn(results, name)).join('\n')} ({ renderSidecarStatus, refreshSidecarStatus })`, context);
  return { ...api, els, dot };
}

test('GPT fallback chip follows the account pool instead of a hard-coded green', () => {
  const h = statusHarness();
  const fallback = () => [h.els.deskFallbackStatus.textContent, h.els.deskFallbackStatus.dataset.tone];
  h.renderSidecarStatus({ enabled: false });
  assert.deepEqual(fallback(), ['GPT fallback 未启用', 'warn']);
  h.renderSidecarStatus({ enabled: true, online: true, stats: { available: 2, total: 3 } });
  assert.deepEqual(fallback(), ['GPT fallback 可用', 'ok']);
  h.renderSidecarStatus({ enabled: true, online: true, stats: { available: 0, total: 3, limited: 3 } });
  assert.deepEqual(fallback(), ['GPT fallback 无可用账号', 'warn']);
  h.renderSidecarStatus({ enabled: true, online: false });
  assert.deepEqual(fallback(), ['GPT fallback 不可用', 'error']);
  assert.doesNotMatch(fn(results, 'renderOutputStatusChips'), /deskFallbackStatus/);
  assert.match(read('frontend/desktop.html'), /desk-status-chip--checking" id="deskFallbackStatus">GPT fallback 检查中</);
});

test('service chip goes offline only when the poll gets no HTTP response', async () => {
  const offline = statusHarness(() => Promise.reject(new TypeError('Failed to fetch')));
  await offline.refreshSidecarStatus();
  const service = offline.els.deskServiceStatus;
  assert.equal(service.textContent, '服务 18463 离线');
  assert.equal(service.dataset.tone, 'error');
  assert.ok(!service.classes.has('desk-status-chip--service'));
  assert.deepEqual(service.children, ['服务 18463 离线']);
  assert.equal(offline.els.deskFallbackStatus.textContent, 'GPT fallback 未知');

  const unauthorized = statusHarness(() => Promise.reject(new Error('HTTP 401')));
  await unauthorized.refreshSidecarStatus();
  const online = unauthorized.els.deskServiceStatus;
  assert.equal(online.textContent, '服务 18463 在线');
  assert.equal(online.dataset.tone, 'ok');
  assert.ok(online.classes.has('desk-status-chip--service'));
  assert.equal(online.children[0], unauthorized.dot);
});

function renderPills(status, imagePaths = []) {
  const wrap = { innerHTML: '' };
  const inFlight = ['queued', 'preparing', 'processing', 'fallback_running'];
  const labels = { failed: '失败', telegram_failed: '发送失败', canceled: '已取消' };
  const context = vm.createContext({
    DEFAULT_RESULT_NODE_ID: 'output',
    getResultEls: () => ({ pills: wrap }),
    getOutputState: () => ({ imagePaths, params: {} }),
    getTaskParams: () => ({}),
    getRequestedImageCount: () => 1,
    getExportFiles: () => [],
    isBrowserFallback: () => false,
    escapeHtml: value => String(value),
    window: {},
    DesktopState: {
      state: { output: { status } },
      isInFlight: value => inFlight.includes(value),
      isFailure: value => ['failed', 'telegram_failed'].includes(value),
      getStatusLabel: value => labels[value] || value,
    },
  });
  vm.runInContext(`${fn(results, 'renderPills')} renderPills({ status: ${JSON.stringify(status)} })`, context);
  return wrap.innerHTML;
}

test('result pills state the task outcome instead of always waiting', () => {
  assert.equal(renderPills('idle'), '<span>等待结果</span>');
  assert.equal(renderPills('failed'), '<span class="is-error">失败</span>');
  assert.equal(renderPills('canceled'), '<span>已取消</span>');
  assert.equal(renderPills('processing'), '<span class="is-busy">队列处理中</span>');
  assert.equal(renderPills('succeeded', ['a.png']), '<span class="is-success">已出 1 张</span>');
});

function removalHarness(canvasNodes, { referenceImages = [], nodeRefs = {}, outputs = {}, answer = true } = {}) {
  const prompts = [];
  const context = vm.createContext({
    window: { confirm: message => { prompts.push(message); return answer; } },
    getNodeReferenceStore: () => nodeRefs,
    DesktopState: {
      state: { canvas: { nodes: canvasNodes }, referenceImages, outputs, output: {} },
      isInFlight: status => ['queued', 'processing'].includes(status),
    },
  });
  const confirmNodeRemoval = vm.runInContext(`${fn(nodes, 'describeNodeRemovalLoss')} ${fn(nodes, 'confirmNodeRemoval')} confirmNodeRemoval`, context);
  return { confirmNodeRemoval, prompts };
}

test('removing nodes asks first only when unrecoverable content would be lost', () => {
  const empty = removalHarness({ t: { type: 'text', text: '  ' }, i: { type: 'image' } });
  assert.equal(empty.confirmNodeRemoval(['t', 'i']), true);
  assert.equal(empty.prompts.length, 0);

  const loaded = removalHarness({
    t: { type: 'text', text: '海边的少女' },
    input: { type: 'input' },
    g: { type: 'image_group', items: [{}, {}, {}] },
    m: { type: 'comfy' },
  }, { referenceImages: [{}, {}], outputs: { m: { status: 'processing' } }, answer: false });
  assert.equal(loaded.confirmNodeRemoval(['t', 'input', 'g', 'm']), false);
  assert.equal(loaded.prompts.length, 1);
  assert.match(loaded.prompts[0], /^删除这 4 个节点后无法恢复：/);
  for (const loss of ['文本节点中的提示词', '2 张参考图', '图片组中的 3 张图片', '进行中任务']) assert.ok(loaded.prompts[0].includes(loss), loss);

  const single = removalHarness({ n: { type: 'upscale' } }, { nodeRefs: { n: [{}] } });
  assert.equal(single.confirmNodeRemoval(['n']), true);
  assert.match(single.prompts[0], /^删除这个节点后无法恢复：\n· 1 张参考图/);
});

test('every node delete path confirms before removing', () => {
  assert.equal(canvas.match(/canvasNodes\.confirmNodeRemoval\(/g).length, 3);
  assert.match(canvas, /confirmNodeRemoval\(\[node\?\.dataset\.nodeId\]\)\) return;\s*removeNode\(node\?\.dataset\.nodeId/);
  assert.match(canvas, /confirmNodeRemoval\(nodeIds\)\) return;\s*nodeIds\.forEach\(\(nodeId, index\) => removeNode/);
  assert.match(canvas, /confirmNodeRemoval\(selectedNodeIds\)\) return;\s*selectedNodeIds\.forEach\(\(nodeId, index\) => removeNode/);
});

test('text node drawer ships no placeholder actions', () => {
  assert.ok(!read('frontend/scripts/desktop-canvas-text-editor.js').includes('google-polish'));
  assert.ok(!canvas.includes('会在文本节点工作流中接入'));
});

test('progress track takes hover so its full-text title can show', () => {
  const css = read('frontend/styles/desktop-progress.css');
  const track = css.slice(css.indexOf('body.desk-app .desk-progress-material > .desk-progress-material__track {'));
  assert.match(track.slice(0, track.indexOf('}')), /pointer-events: auto;/);
});

const liquid = read('frontend/styles/desktop-liquid.css');
const rule = selector => {
  const start = liquid.indexOf(`\n${selector} {`);
  assert.ok(start >= 0, selector);
  return liquid.slice(start, liquid.indexOf('}', start));
};

test('input footer controls share one centre line and the action meets the grid edge', () => {
  assert.match(rule('.desk-output-controls--input'), /min-height: 30px;/);
  assert.match(rule('.desk-input-footer'), /padding-right: 90px;/);
  const action = rule('.desk-input-footer .desk-action-row');
  assert.match(action, /right: 0;/);
  assert.match(action, /bottom: 0;/);
  assert.match(rule('.desk-pill-row span'), /box-shadow: inset 0 0 0 1px/);
});

test('image reference tokens fit inside the 14px/1.55 editor line', () => {
  const token = rule('.desk-image-reference-token');
  assert.match(token, /min-height: 18px;/);
  assert.match(token, /margin: 0 2px;/);
  assert.match(token, /line-height: 16px;/);
});

test('resolution, quality and moderation options show localized labels over unchanged values', () => {
  const html = read('frontend/desktop.html');
  for (const option of ['<option value="2k" selected>2K</option>', '<option value="medium">中</option>', '<option value="auto" selected>自动</option>']) {
    assert.ok(html.includes(option), option);
  }
  assert.doesNotMatch(html, /<option( selected)?>(1k|2k|4k|auto|low|medium|high)<\/option>/);
  const model = read('frontend/scripts/desktop-canvas-model-nodes.js');
  assert.ok(model.includes("{ value: '4k', label: '4K' }"));
  assert.ok(model.includes("{ value: 'high', label: '高' }"));
  assert.doesNotMatch(model, /label: '(1k|2k|4k|auto|low|medium|high)'/);
});

test('text node drawer uses product casing and an icon for clear', () => {
  const editor = read('frontend/scripts/desktop-canvas-text-editor.js');
  assert.ok(editor.includes('data-text-action="gpt-polish">GPT 润色</button>'));
  assert.match(editor, /data-text-action="clear"[^>]*><svg viewBox="0 0 24 24" aria-hidden="true">/);
  assert.ok(!editor.includes('❌'));
  assert.ok(!read('frontend/scripts/desktop-canvas-generation.js').includes('Gpt 润色'));
});
