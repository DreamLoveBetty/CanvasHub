// Model-tools path rows copy the original full path via DesktopCanvas.copyTextToClipboardLocal.
// Empty paths explain where to put .safetensors and must not fake success. No Finder integration.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const files = [
  'frontend/scripts/desktop-moss-tools.js',
  'frontend/scripts/desktop-krea2-tools.js',
  'frontend/scripts/desktop-qwen21-tools.js',
];

test('MOSS, Krea 2 and Qwen 2.1 path rows expose a full-path copy control', () => {
  for (const rel of files) {
    const source = fs.readFileSync(path.join(root, rel), 'utf8');
    assert.match(source, /data-copy-model-path/, `${rel} should have a copy-path button`);
    assert.match(source, /data-model-tools-path/, `${rel} should carry the original full path`);
    assert.match(source, /\.safetensors/, `${rel} empty-copy guidance should mention .safetensors`);
    assert.doesNotMatch(source, /open in Finder|在 Finder 中打开|showItemInFolder|shell\.openPath/i);
  }
  const qwen = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-qwen21-tools.js'), 'utf8');
  assert.match(qwen, /pathRow\('VAE 导入目录'/);
  assert.match(qwen, /const pathRow=[\s\S]*data-copy-model-path/);
});

function loadSettings(copyImpl) {
  const messages = [];
  const copies = [];
  const source = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-settings.js'), 'utf8');
  const emptyCreate = () => ({ create() { return { forget() {}, remember() {}, render() { return ''; }, mount() {}, release() {}, handleClick() { return false; } }; } });
  const context = vm.createContext({
    window: {},
    console,
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    document: { getElementById() { return null; }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } },
    setTimeout() { return 0; },
    clearTimeout() {},
    requestAnimationFrame() { return 0; },
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
  });
  context.window = context;
  context.sessionStorage = context.sessionStorage;
  context.DesktopSettingsDrafts = emptyCreate();
  context.DesktopGooglePool = emptyCreate();
  context.DesktopGoogleWeb = emptyCreate();
  context.DesktopProgressPreview = emptyCreate();
  context.DesktopRunnerSlider = emptyCreate();
  context.DesktopPreferences = { state: {} };
  context.DesktopApi = { googlePool: {}, googleWeb: {} };
  context.DesktopResults = { showTransientMessage(text, tone) { messages.push({ text, tone }); } };
  context.DesktopCanvas = {
    copyTextToClipboardLocal: async (text, successMessage) => {
      copies.push({ text, successMessage });
      if (typeof copyImpl === 'function') return copyImpl(text, successMessage);
      return 'copied';
    },
  };
  vm.runInContext(source, context);
  return { api: context.DesktopSettings, messages, copies };
}

test('copying a full path reuses the clipboard helper; empty path explains the .safetensors directory', async () => {
  const full = '/Users/demo/Library/Application Support/CanvasHub/models/qwen21-base';
  const { api, copies, messages } = loadSettings();
  const copied = await api.copyModelToolsDirectoryPath(full, 'unused');
  assert.equal(copied, 'copied');
  assert.deepEqual(copies, [{ text: full, successMessage: '完整路径已复制。' }]);
  assert.equal(messages.length, 0);

  const empty = await api.copyModelToolsDirectoryPath('', '模型导入目录路径尚未提供。请将源 .safetensors 文件放到该导入目录后再刷新。');
  assert.equal(empty, 'empty');
  assert.equal(copies.length, 1);
  assert.equal(messages[0].text.includes('.safetensors'), true);
  assert.equal(messages[0].text.includes('导入目录'), true);
  assert.notEqual(messages[0].tone, 'success');
});

test('clipboard failure is reported and is not treated as success', async () => {
  const { api, messages } = loadSettings(async () => { throw new Error('clipboard blocked'); });
  const result = await api.copyModelToolsDirectoryPath('/tmp/models', 'unused');
  assert.equal(result, 'failed');
  assert.equal(messages.some(item => String(item.text).includes('clipboard blocked') || String(item.text).includes('复制失败')), true);
  assert.equal(messages.some(item => item.tone === 'success' || String(item.text).includes('已复制')), false);
});
