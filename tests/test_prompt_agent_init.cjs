const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

// A stand-in for any DOM node or host object: every property is another stand-in,
// every call returns one, and assigned values read back. It only has to let
// init() walk its real render path; the assertions are about exceptions.
function stub() {
  const values = new Map();
  const proxy = new Proxy(function () {}, {
    get(target, key) {
      if (values.has(key)) return values.get(key);
      if (key === 'then') return undefined;
      if (key === Symbol.iterator) return function* () {};
      if (key === Symbol.toPrimitive) return () => '';
      if (key === 'length') return 0;
      if (typeof key === 'symbol') return undefined;
      const child = stub();
      values.set(key, child);
      return child;
    },
    set(target, key, value) {
      values.set(key, value);
      return true;
    },
    apply() {
      return stub();
    }
  });
  return proxy;
}

function fixture() {
  const storage = new Map();
  const ctx = vm.createContext({
    console,
    URL,
    URLSearchParams,
    structuredClone,
    setTimeout: () => 0,
    clearTimeout() {},
    queueMicrotask,
    requestAnimationFrame: () => 0,
    cancelAnimationFrame() {},
    localStorage: {
      getItem: key => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key)
    },
    document: stub(),
    getComputedStyle: () => stub()
  });
  ctx.window = ctx;
  ctx.sessionStorage = ctx.localStorage;
  ctx.addEventListener = () => {};
  ctx.removeEventListener = () => {};
  ctx.isMiniappAuthReady = () => false;
  ctx.waitForMiniappAuthReady = () => new Promise(() => {});
  ctx.document.visibilityState = 'visible';
  for (const name of ['DesktopState', 'DesktopCanvas', 'DesktopApi', 'DesktopResults', 'DesktopPromptDrawer', 'DesktopI18n']) {
    ctx[name] = stub();
  }
  const source = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-prompt-agent.js'), 'utf8');
  vm.runInContext(source, ctx, { filename: 'desktop-prompt-agent.js' });
  return { ctx };
}

// desktop-bootstrap.js runs every module init() in one chain before it loads history.
// An exception here leaves the history panel on its "sign in to sync" placeholder.
test('prompt agent init and render complete without throwing', () => {
  const { ctx } = fixture();
  assert.equal(typeof ctx.DesktopPromptAgent?.init, 'function');
  ctx.DesktopPromptAgent.init();
  ctx.DesktopPromptAgent.render();
});
