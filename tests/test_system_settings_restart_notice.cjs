// PATCH /api/system/settings returns { ok:true, settings:{ server:{ restart_required } } }.
// If restart is required, toast “已保存，重启后生效” and keep a visible card hint.
// Ordinary saves keep “系统配置已保存。” Tests use fixtures only; no production settings or restart.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-settings.js'), 'utf8');

function loadSettings() {
  const context = vm.createContext({
    window: {},
    console,
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    document: { getElementById() { return null; }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } },
    setTimeout() { return 0; },
    clearTimeout() {},
    requestAnimationFrame(fn) { return 0; },
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
  });
  const emptyCreate = () => ({ create() { return { forget() {}, remember() {}, render() { return ''; }, mount() {}, release() {} }; } });
  context.window = context;
  context.window.sessionStorage = context.sessionStorage;
  context.DesktopSettingsDrafts = { create() { return { forget() {}, remember() {} }; } };
  context.DesktopGooglePool = emptyCreate();
  context.DesktopGoogleWeb = emptyCreate();
  context.DesktopProgressPreview = emptyCreate();
  context.DesktopRunnerSlider = emptyCreate();
  context.DesktopPreferences = { state: {} };
  context.DesktopApi = { googlePool: {}, googleWeb: {} };
  try {
    vm.runInContext(source, context);
  } catch (error) {
    context._loadError = error;
  }
  return context;
}

test('save response with restart_required uses the restart notice and never auto-restarts', () => {
  const context = loadSettings();
  const api = context.DesktopSettings;
  assert.equal(typeof api?.isRestartRequiredFromSettingsSave, 'function', context._loadError?.message || 'helpers should be exported');
  const required = { ok: true, settings: { server: { restart_required: true, host: '0.0.0.0', port: 9999 } } };
  const ordinary = { ok: true, settings: { server: { restart_required: false, host: '127.0.0.1', port: 18463 } } };
  assert.equal(api.isRestartRequiredFromSettingsSave(required), true);
  assert.equal(api.systemSettingsSaveNotice(required), '已保存，重启后生效');
  assert.equal(api.systemSettingsSaveNotice(ordinary), '系统配置已保存。');
  assert.equal(api.systemSettingsSaveNotice({ ok: true, server: { restart_required: true } }), '已保存，重启后生效');

  const messages = [];
  const hint = { hidden: true };
  const card = { querySelector: selector => selector.includes('restart-required') ? hint : null };
  const applied = api.applySystemSettingsSaveResult(required, { notify: (text, tone) => messages.push({ text, tone }), card });
  assert.equal(applied.restartRequired, true);
  assert.deepEqual(messages, [{ text: '已保存，重启后生效', tone: 'success' }]);
  assert.equal(hint.hidden, false);
  messages.length = 0;
  hint.hidden = false;
  api.applySystemSettingsSaveResult(ordinary, { notify: (text, tone) => messages.push({ text, tone }), card });
  assert.deepEqual(messages, [{ text: '系统配置已保存。', tone: 'success' }]);
  assert.equal(hint.hidden, true);
});

test('system card keeps a persistent restart hint and save does not auto-restart', () => {
  assert.match(source, /data-restart-required-hint/);
  assert.match(source, /已保存，重启后生效/);
  const saveStart = source.indexOf('async function saveSystemSettings');
  const saveEnd = source.indexOf('\n  async function verifyPinterestAuth', saveStart);
  const save = source.slice(saveStart, saveEnd);
  assert.match(save, /saveSystemSettings\(payload\)/);
  assert.match(save, /applySystemSettingsSaveResult|已保存，重启后生效/);
  assert.doesNotMatch(save, /location\.reload|restartService|restart_server|postRestart|\/api\/system\/restart/);
});
