// Regression: desktop-bootstrap.js used to run every startup init() in one chain whose errors
// were swallowed, so a single module throwing (e.g. DesktopCanvas.init on a saved node it cannot
// render) left the canvas empty, history on "sign in to sync" and nothing in the console.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend/scripts/desktop-bootstrap.js'), 'utf8');

function boot({ failing = [] } = {}) {
  const calls = [];
  const errors = [];
  const step = name => () => {
    calls.push(name);
    if (failing.includes(name)) throw new Error(`${name} exploded`);
  };
  const module = (prefix, ...methods) => Object.fromEntries(methods.map(method => [method, step(`${prefix}.${method}`)]));
  const window = {
    addEventListener() {},
    DesktopSettings: module('DesktopSettings', 'init'),
    DesktopPromptDrawer: module('DesktopPromptDrawer', 'init'),
    DesktopPromptAgent: module('DesktopPromptAgent', 'init'),
    DesktopPromptLibrary: module('DesktopPromptLibrary', 'init'),
    DesktopPromptInsert: module('DesktopPromptInsert', 'init'),
    DesktopI18n: module('DesktopI18n', 'apply'),
    DesktopSelect: module('DesktopSelect', 'init'),
  };
  const keydownListeners = [];
  const context = vm.createContext({
    window,
    document: {
      readyState: 'complete',
      addEventListener(type, handler) {
        if (type === 'keydown') keydownListeners.push(handler);
      },
    },
    console: { error: (...args) => errors.push(args) },
    DesktopState: module('DesktopState', 'loadSettings', 'restoreCanvasBackup', 'loadDraft', 'loadLastTask'),
    DesktopResults: module('DesktopResults', 'init', 'stopPolling'),
    DesktopCanvas: module('DesktopCanvas', 'init'),
    DesktopHistory: { ...module('DesktopHistory', 'init'), loadHistory: () => Promise.resolve([]) },
    DesktopApi: {},
    waitForMiniappAuthReady: () => new Promise(() => {}),
  });
  vm.runInContext(source, context, { filename: 'desktop-bootstrap.js' });
  return { calls, errors, keydownListeners };
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0));

test('a module that throws during startup does not stop the modules after it', async () => {
  const { calls, errors } = boot({ failing: ['DesktopCanvas.init'] });
  await settle();
  for (const name of ['DesktopHistory.init', 'DesktopSettings.init', 'DesktopPromptAgent.init', 'DesktopPromptLibrary.init', 'DesktopSelect.init']) {
    assert.ok(calls.includes(name), `${name} still runs`);
  }
  assert.equal(errors.length, 1);
  assert.match(String(errors[0][0]), /DesktopCanvas\.init/);
  assert.match(String(errors[0][1]?.message), /DesktopCanvas\.init exploded/);
});

test('startup keeps its order and reports nothing when every module succeeds', async () => {
  const { calls, errors } = boot();
  await settle();
  assert.deepEqual(errors, []);
  assert.ok(calls.indexOf('DesktopState.restoreCanvasBackup') < calls.indexOf('DesktopCanvas.init'));
  assert.ok(calls.indexOf('DesktopCanvas.init') < calls.indexOf('DesktopHistory.init'));
});


function fireEscape(listeners) {
  const event = { key: 'Escape', defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, stopImmediatePropagation() {} };
  for (const handler of listeners) handler(event);
  return event;
}

test('Escape while closing panels does not stop task polling', async () => {
  const { calls, errors, keydownListeners } = boot();
  await settle();
  assert.deepEqual(errors, []);
  const before = calls.filter(name => name === 'DesktopResults.stopPolling').length;
  fireEscape(keydownListeners);
  assert.equal(
    calls.filter(name => name === 'DesktopResults.stopPolling').length,
    before,
    'closing a panel with Escape must not call stopPolling'
  );
});
