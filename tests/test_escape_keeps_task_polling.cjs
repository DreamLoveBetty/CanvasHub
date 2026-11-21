// Isolated timer harness: Escape / closing panels must not stop in-flight
// single-task or batch polling, and must not cancel those tasks.
// Loads real desktop-state + desktop-results only (no bootstrap auto-init).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');

function element() {
  const listeners = {};
  const classNames = new Set();
  const el = {
    textContent: '',
    innerHTML: '',
    hidden: true,
    disabled: false,
    style: { setProperty() {}, removeProperty() {} },
    dataset: {},
    listeners,
    classList: {
      add: (...names) => names.forEach(name => classNames.add(name)),
      remove: (...names) => names.forEach(name => classNames.delete(name)),
      toggle(name, force) {
        if (force === true) classNames.add(name);
        else if (force === false) classNames.delete(name);
        else if (classNames.has(name)) classNames.delete(name);
        else classNames.add(name);
        return classNames.has(name);
      },
      contains: name => classNames.has(name),
    },
    setAttribute() {},
    getAttribute() { return null; },
    focus() {},
    blur() {},
    contains() { return false; },
    closest() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { width: 360, top: 800, left: 200, height: 24 }; },
    addEventListener(name, cb) { (listeners[name] ||= []).push(cb); },
    appendChild() { return el; },
    replaceChildren(...nodes) {
      this.textContent = nodes.map(node => (typeof node === 'string' ? node : node?.textContent || '')).join('');
    },
    remove() {},
    title: '',
  };
  return el;
}

async function harness() {
  const elements = new Map();
  const ids = [
    'deskOutputTitle', 'deskOutputStatus', 'deskInputOutputStatus', 'deskStatusMessage',
    'deskStatusBarStatus', 'deskHistoryPanel', 'deskStatusTip', 'deskStatusTipTitle',
    'deskStatusTipSubtitle', 'deskStatusTipDisplay', 'deskStatusTipMeta', 'deskStatusTipRaw',
    'deskStatusTipCopy', 'deskStatusTipClose', 'deskServiceStatus', 'deskSidecarStatus',
    'deskFallbackStatus', 'deskArchiveStatus', 'deskTelegramStatus', 'deskProgressPercent',
    'deskProgressBar', 'deskInputProgressPercent', 'deskInputProgressBar', 'deskInputProgressStage',
    'deskInputProgressTimer', 'deskProgressFloat', 'deskResultGrid', 'deskSendOriginalBtn',
    'deskOutputPills', 'deskStopBtn',
  ];
  for (const id of ids) elements.set(id, element());

  const inputNode = element();
  inputNode.classList.contains = name => name === 'desk-node--input' || name === 'desk-node';
  inputNode.dataset = { nodeId: 'input' };
  inputNode.querySelector = selector => {
    if (selector === '[data-output-status]') return elements.get('deskInputOutputStatus');
    if (selector === '[data-output-pills]') return elements.get('deskOutputPills');
    if (selector === '[data-send-original]') return elements.get('deskSendOriginalBtn');
    if (selector === '[data-input-material-progress]') return null;
    return null;
  };

  const timeouts = new Map();
  const intervals = new Map();
  let seq = 0;
  const statusCalls = [];
  const batchCalls = [];
  const cancelCalls = [];
  const documentListeners = {};
  let disposed = false;
  let inflight = 0;
  const runInflight = fn => async (...args) => {
    if (disposed) return { status: 'processing' };
    inflight += 1;
    try { return await fn(...args); }
    finally { inflight -= 1; }
  };

  const context = vm.createContext({
    console,
    CSS: { escape: String },
    innerWidth: 1200,
    innerHeight: 900,
    setTimeout(fn, ms) {
      const id = ++seq;
      timeouts.set(id, { fn, ms: Number(ms) || 0 });
      return id;
    },
    clearTimeout(id) { timeouts.delete(id); },
    setInterval(fn, ms) {
      const id = ++seq;
      intervals.set(id, { fn, ms: Number(ms) || 0 });
      return id;
    },
    clearInterval(id) { intervals.delete(id); },
    requestAnimationFrame(fn) {
      const id = ++seq;
      timeouts.set(id, { fn, ms: 0 });
      return id;
    },
    cancelAnimationFrame(id) { timeouts.delete(id); },
    addEventListener() {},
    removeEventListener() {},
    ResizeObserver: class { observe() {} disconnect() {} },
    MutationObserver: class { observe() {} disconnect() {} },
    location: { port: '18463', protocol: 'http:', hostname: '127.0.0.1' },
    document: {
      readyState: 'complete',
      getElementById: id => elements.get(id) || null,
      createElement: () => element(),
      querySelector(selector) {
        if (String(selector).includes('data-node-id')) return inputNode;
        return null;
      },
      querySelectorAll: () => [],
      addEventListener(type, handler) {
        (documentListeners[type] ||= []).push(handler);
      },
    },
    localStorage: { getItem() { return null; }, setItem() {} },
    navigator: { clipboard: { writeText: async () => {} } },
  });
  context.window = context;
  context.DesktopApi = {
    getStatus: runInflight(async id => {
      if (disposed) return { task_id: id, status: 'processing', progress_text: '生成中', progress: 40 };
      statusCalls.push(id);
      return { task_id: id, status: 'processing', progress_text: '生成中', progress: 40 };
    }),
    getBatch: runInflight(async id => {
      if (disposed) return { batch_id: id, status: 'running', counts: { total: 3 } };
      batchCalls.push(id);
      return { batch_id: id, status: 'running', counts: { total: 3, succeeded: 1, processing: 1, queued: 1 } };
    }),
    getChatgptPoolStatus: runInflight(async () => ({ enabled: false })),
    cancelTask: async id => {
      cancelCalls.push(['task', id]);
      return { status: 'canceled' };
    },
    controlBatch: async (id, action) => {
      cancelCalls.push(['batch', id, action]);
      return { batch_id: id, status: action === 'cancel' ? 'completed' : 'running', counts: { total: 3 } };
    },
    tasks: { generation: {}, batch: {} },
  };
  context.DesktopHistory = { init() {}, loadHistory: async () => [], syncWorkbenchYield() {} };
  context.DesktopCanvas = {
    init: async () => {},
    getTaskRegistry: () => ({ register() { return () => {}; } }),
    refreshTaskNode() {},
    updateTaskProgress() {},
  };
  context.DesktopTaskOutputAdapter = { create() { return { listCancelable: () => [] }; } };

  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/desktop-state.js'), 'utf8'), context);
  context.DesktopState.saveSettings = () => {};
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/desktop-results.js'), 'utf8'), context);
  context.DesktopResults.init();
  for (let i = 0; i < 20; i += 1) await Promise.resolve();

  context.DesktopState.state.outputs.input = {
    ...(context.DesktopState.state.outputs.input || {}),
    taskId: 'task-single',
    status: 'processing',
    progressText: '生成中',
    files: [],
    imagePaths: [],
  };
  context.DesktopState.state.outputs['batch-node'] = {
    batchId: 'batch-1',
    batchStatus: 'running',
    status: 'processing',
    progressText: '批量生成中',
    files: [],
    imagePaths: [],
  };

  await context.DesktopResults.restoreActiveTasks();

  return {
    context, timeouts, intervals, statusCalls, batchCalls, cancelCalls,
    documentListeners, get inflight() { return inflight; },
    async dispose() {
      disposed = true;
      for (const id of [...timeouts.keys()]) context.clearTimeout(id);
      for (const id of [...intervals.keys()]) context.clearInterval(id);
      timeouts.clear();
      intervals.clear();
      for (let i = 0; i < 20 && inflight > 0; i += 1) await Promise.resolve();
    },
  };
}

async function flushTimeouts(timeouts) {
  const due = [...timeouts.entries()];
  for (const [id, timer] of due) {
    timeouts.delete(id);
    await timer.fn();
  }
}

function fireEscape(listeners) {
  const event = {
    key: 'Escape',
    defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() {},
    stopImmediatePropagation() {},
    target: { closest() { return null; } },
  };
  for (const handler of listeners || []) handler(event);
  return event;
}

test('Escape does not stop single-task or batch polling and does not cancel them', async () => {
  const h = await harness();
  try {
    assert.ok(h.statusCalls.includes('task-single'), 'restore should poll the single task');
    assert.ok(h.batchCalls.includes('batch-1'), 'restore should poll the batch');
    const statusBefore = h.statusCalls.length;
    const batchBefore = h.batchCalls.length;

    fireEscape(h.documentListeners.keydown);
    assert.deepEqual(h.cancelCalls, [], 'Escape must not cancel tasks');

    await flushTimeouts(h.timeouts);
    assert.ok(h.statusCalls.length > statusBefore, 'single-task polling must continue after Escape');
    assert.ok(h.batchCalls.length > batchBefore, 'batch polling must continue after Escape');
    assert.deepEqual(h.cancelCalls, [], 'continued polling must not cancel tasks');
  } finally {
    await h.dispose();
  }
});

test('stopPolling is what would freeze batch progress tracking', async () => {
  const h = await harness();
  try {
    await flushTimeouts(h.timeouts);
    const batchBefore = h.batchCalls.length;
    h.context.DesktopResults.stopPolling();
    await flushTimeouts(h.timeouts);
    assert.equal(h.batchCalls.length, batchBefore, 'stopPolling must clear scheduled batch polls');
  } finally {
    await h.dispose();
  }
});
