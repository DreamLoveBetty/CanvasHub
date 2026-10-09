const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../frontend/scripts/desktop-results.js'), 'utf8');
function fixture() {
  let nextFrame = 0;
  const frames = new Map(), listeners = new Map(), observers = [];
  const element = rect => ({ hidden: false, dataset: {},
    classList: { contains: () => false },
    style: { setProperty(key, value) { this[key] = value; } },
    getBoundingClientRect: () => rect });
  const status = element({ left: 10, right: 1398 });
  const history = element({ left: 1216, right: 1440, top: 36, width: 224, height: 764 });
  const trigger = element({ top: 871 });
  const panel = element({}); panel.hidden = true;
  class Observer {
    constructor(callback) { this.callback = callback; this.targets = []; this.disconnected = false; observers.push(this); }
    observe(target, options) { this.targets.push({ target, options }); }
    disconnect() { this.disconnected = true; }
  }
  const context = vm.createContext({ console, innerWidth: 1440, innerHeight: 900,
    requestAnimationFrame(fn) { const id = ++nextFrame; frames.set(id, fn); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    addEventListener(name, callback) { const handlers = listeners.get(name) || new Set(); handlers.add(callback); listeners.set(name, handlers); },
    removeEventListener(name, callback) { listeners.get(name)?.delete(callback); },
    ResizeObserver: Observer, MutationObserver: Observer });
  context.window = context;
  vm.runInContext(source.replace('  window.DesktopResults = {', `
    window.dockTest = { calculateStatusDock, updateStatusTipPosition, bindStatusDockLayout, scheduleStatusTipPosition,
      setElements(values) { Object.assign(els, values); }, setTask(value) { statusTipTask = value; } };
    window.DesktopResults = {`), context);
  const api = context.dockTest;
  api.setElements({ deskStatusBarStatus: status, deskHistoryPanel: history, deskStatusMessage: trigger, deskStatusTip: panel });
  const flush = () => { for (const [id, fn] of [...frames]) { frames.delete(id); fn(); } };
  return { context, api, frames, listeners, observers, status, history, trigger, panel, flush };
}

for (const [name, input, expected] of [
  ['expanded history', { statusLeft: 10, statusRight: 1398, historyLeft: 1216, preferredWidth: 280 }, { left: 936, right: 1216, width: 280, trailing: 182 }],
  ['extended log', { statusLeft: 10, statusRight: 1398, historyLeft: 1216, preferredWidth: 400 }, { left: 816, right: 1216, width: 400, trailing: 182 }],
  ['collapsed history', { statusLeft: 10, statusRight: 1398, historyLeft: null, preferredWidth: 280 }, { left: 1118, right: 1398, width: 280, trailing: 0 }],
  ['narrow viewport', { statusLeft: 10, statusRight: 278, historyLeft: null, preferredWidth: 400 }, { left: 66, right: 278, width: 212, trailing: 0 }],
  ['fractional sidebar edge', { statusLeft: 10, statusRight: 1238, historyLeft: 1056.5, preferredWidth: 280 }, { left: 776.5, right: 1056.5, width: 280, trailing: 181.5 }],
]) {
  test('status label and detail dock share bounds: ' + name, () => {
    const h = fixture();
    assert.deepEqual(JSON.parse(JSON.stringify(h.api.calculateStatusDock(input))), expected);
  });
}

test('the hidden detail and footer label align before the first click', () => {
  const h = fixture(); h.api.updateStatusTipPosition();
  assert.equal(h.status.style['--desk-status-dock-width'], '280px');
  assert.equal(h.status.style['--desk-status-dock-trailing'], '182px');
  assert.equal(h.panel.style.left, '936px');
  assert.equal(h.panel.style.width, '280px');
  h.panel.hidden = false; h.api.updateStatusTipPosition();
  assert.equal(h.panel.style.bottom, '39px');
  h.api.setTask({ raw_detail: 'Synthetic multiline log' }); h.api.updateStatusTipPosition();
  assert.equal(h.panel.dataset.extended, 'true');
  assert.equal(h.panel.style.width, '400px');
  assert.equal(h.panel.style.left, '816px');
  h.api.setTask({ progress_text: 'Normal task' }); h.api.updateStatusTipPosition();
  assert.equal(h.panel.dataset.extended, 'false');
  assert.equal(h.panel.style.width, '280px');
});

test('collapsed, hidden and offscreen history use the visible footer rather than its rail', () => {
  for (const state of ['collapsed', 'hidden', 'offscreen']) {
    const h = fixture();
    if (state === 'collapsed') h.history.classList.contains = name => name === 'is-collapsed';
    if (state === 'hidden') h.history.hidden = true;
    if (state === 'offscreen') h.history.getBoundingClientRect = () => ({ left: 1600, right: 1824, width: 224, height: 764 });
    h.api.updateStatusTipPosition();
    assert.equal(h.panel.style.left, '1118px', state);
    assert.equal(h.status.style['--desk-status-dock-trailing'], '0px', state);
  }
});

test('resize and history observers coalesce updates and are disposed on reinitialization', () => {
  const h = fixture(); h.api.bindStatusDockLayout();
  assert.equal(h.observers.length, 2);
  h.api.scheduleStatusTipPosition(); h.observers[0].callback(); h.observers[1].callback();
  assert.equal(h.frames.size, 1);
  h.flush(); assert.equal(h.panel.style.left, '936px');
  h.api.bindStatusDockLayout();
  assert.ok(h.observers.slice(0, 2).every(observer => observer.disconnected));
  assert.equal(h.listeners.get('resize').size, 1);
  assert.equal(h.frames.size, 1);
  h.history.classList.contains = name => name === 'is-collapsed';
  h.observers[3].callback(); h.flush();
  assert.equal(h.panel.style.left, '1118px');
});
