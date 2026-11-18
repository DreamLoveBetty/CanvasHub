// Gallery image preview: Prompt copy button and historical LoRA rows.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const history = read('frontend/scripts/desktop-history.js');
const html = read('frontend/desktop.html');

function extractFunction(source, name) {
  let start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  if (start >= 6 && source.slice(start - 6, start) === 'async ') start -= 6;
  let i = start;
  let parens = 0;
  let seenParen = false;
  for (; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === '(') {
      parens += 1;
      seenParen = true;
    } else if (ch === ')') {
      parens -= 1;
    } else if (ch === '{' && seenParen && parens === 0) {
      break;
    }
  }
  let depth = 0;
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} is not balanced`);
}

function parseMetaRows(htmlText) {
  const rows = {};
  for (const match of htmlText.matchAll(/<span>([^<]*)<\/span>\s*<strong([^>]*)>([^<]*)<\/strong>/g)) {
    rows[match[1]] = { value: match[3], attrs: match[2] };
  }
  return rows;
}

function loadMeta() {
  const names = [
    'escapeHtml',
    'previewProviderKey',
    'assetCanRecordLoras',
    'isDisabledLoraEntry',
    'looksLikeFilesystemPath',
    'previewLoraDisplayName',
    'previewLoraScale',
    'formatPreviewLoraScale',
    'formatPreviewLoraEntry',
    'collectPreviewLoraEntries',
    'getPreviewLoraRow',
    'previewPromptText',
    'hasPreviewPrompt',
    'getPreviewMetaRows',
  ];
  const context = vm.createContext({
    previewAsset: null,
    escapeHtml: undefined,
    galleryAssetModelLabel: (asset, params) => params.main_model || 'unknown',
    galleryAssetResolutionLabel: () => '',
    isRemoteLibraryAsset: () => false,
    assetGenerationTiming: () => null,
    formatGenerationDuration: () => '',
    providerLabel: () => 'GPT',
    orientationLabel: () => '',
    normalizeImageFormat: () => '',
    formatFileSize: () => '',
    parseTags: () => [],
    formatPreviewTime: () => '',
  });
  const code = names.map(name => {
    const fn = extractFunction(history, name);
    return `${fn}; this.${name} = ${name};`;
  }).join('\n');
  vm.runInContext(code, context);
  return context;
}

function rowsFor(asset) {
  const context = loadMeta();
  const htmlText = context.getPreviewMetaRows(asset);
  const parsed = parseMetaRows(htmlText);
  const values = {};
  for (const [key, item] of Object.entries(parsed)) values[key] = item.value;
  return { html: htmlText, parsed, values, lora: context.getPreviewLoraRow(asset) };
}

function loadClipboard(options = {}) {
  const messages = [];
  const created = [];
  let fallbackText = '';
  let fallbackOpen = false;
  const fallbackTextarea = {
    focus() {},
    select() {},
    setSelectionRange() {},
  };
  Object.defineProperty(fallbackTextarea, 'value', {
    get() { return fallbackText; },
    set(value) { fallbackText = String(value || ''); },
    configurable: true,
  });
  let fallbackModal = null;
  const documentRef = {
    getElementById(id) {
      return id === 'deskTextCopyFallback' ? fallbackModal : null;
    },
    querySelector(selector) {
      return selector.includes('data-copy-fallback-text') ? fallbackTextarea : null;
    },
    createElement(tag) {
      const el = {
        tag,
        value: '',
        style: {},
        setAttribute() {},
        focus() {},
        select() {},
        setSelectionRange() {},
      };
      created.push(el);
      return el;
    },
    body: {
      insertAdjacentHTML() {
        fallbackModal = {
          classList: {
            add(name) { if (name === 'is-open') fallbackOpen = true; },
            remove(name) { if (name === 'is-open') fallbackOpen = false; },
          },
          setAttribute() {},
          addEventListener() {},
          querySelector(selector) {
            return selector.includes('data-copy-fallback-text') ? fallbackTextarea : null;
          },
        };
      },
      appendChild() {},
      removeChild() {},
    },
  };
  const writeText = options.writeText || (async text => { options.copied = text; });
  const execCommand = options.execCommand == null ? () => false : options.execCommand;
  const context = {
    window: {
      isSecureContext: options.isSecureContext !== false,
      requestAnimationFrame: fn => fn(),
    },
    document: documentRef,
    navigator: {
      clipboard: options.clipboard === false ? undefined : { writeText },
    },
    DesktopResults: {
      showTransientMessage(message) { messages.push(message); },
    },
    console,
  };
  context.window.navigator = context.navigator;
  context.document.execCommand = execCommand;
  vm.createContext(context);
  const editor = read('frontend/scripts/desktop-canvas-text-editor.js');
  const helperNames = [
    'ensureTextCopyFallback',
    'selectTextCopyFallback',
    'showTextCopyFallback',
    'copyTextWithTemporaryTextarea',
    'copyTextToClipboardLocal',
    'setPolishCopyButtonState',
  ];
  vm.runInContext(
    helperNames.map(name => `${extractFunction(editor, name)}; this.${name} = ${name};`).join('\n'),
    context
  );
  return {
    api: {
      copyTextToClipboardLocal: context.copyTextToClipboardLocal,
      setPolishCopyButtonState: context.setPolishCopyButtonState,
    },
    messages,
    created,
    get fallbackOpen() { return fallbackOpen; },
    get fallbackText() { return fallbackText; },
  };
}

test('Prompt title has a copy mini-button immediately before compare, and cache keys are set', () => {
  assert.match(html, /id="deskGalleryPreviewCopyPromptBtn"/);
  assert.match(html, /desk-gallery-preview__section-actions/);
  const order = html.slice(
    html.indexOf('id="deskGalleryPreviewCopyPromptBtn"'),
    html.indexOf('id="deskGalleryPreviewPromptCompareBtn"') + 'id="deskGalleryPreviewPromptCompareBtn"'.length
  );
  assert.match(order, /deskGalleryPreviewCopyPromptBtn[\s\S]*deskGalleryPreviewPromptCompareBtn/);
  assert.doesNotMatch(history, /await navigator\.clipboard\.writeText\(prompt\)/);
  assert.match(history, /DesktopCanvas\?\.copyTextToClipboardLocal/);
  assert.doesNotMatch(history, /DesktopCanvasTextEditor/);
  assert.match(history, /event\?\.stopPropagation\?\.\(\)/);
  assert.ok(hasCacheKey(html, 'scripts/desktop-history.js'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-canvas-text-editor.js'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-i18n.js'));
  assert.ok(hasCacheKey(html, 'styles/desktop-gallery-geometry.css'));
});

test('multiple historical LoRAs keep names, scale 0, and skip disabled entries', () => {
  const result = rowsFor({
    provider: 'qwen21',
    params: {
      provider: 'qwen21',
      main_model: 'Qwen 2.1 · Base',
      loras: [
        { asset_id: 'a'.repeat(64), name: 'Style A', scale: 0.7 },
        { asset_id: 'b'.repeat(64), name: 'Zero Weight', scale: 0 },
        { asset_id: 'c'.repeat(64), name: 'Disabled', scale: 1.2, enabled: false },
        { asset_id: 'd'.repeat(64), name: 'Skipped', weight: 0.5, disabled: true },
      ],
    },
  });
  assert.equal(result.values['主模型'], 'Qwen 2.1 · Base');
  assert.equal(result.values.LoRA, 'Style A (0.7)\nZero Weight (0)');
  assert.match(result.html, /class="desk-gallery-preview__meta-lora"/);
  assert.doesNotMatch(result.html, /Disabled|Skipped/);
  const keys = Object.keys(result.values);
  assert.ok(keys.indexOf('LoRA') === keys.indexOf('主模型') + 1);
});

test('missing LoRA fields are 未记录 only for capable providers; empty arrays are 未使用', () => {
  const mossMissing = rowsFor({ provider: 'moss', params: { provider: 'moss', main_model: 'MOSS · 标准' } });
  assert.equal(mossMissing.values.LoRA, '未记录');
  const qwenEmpty = rowsFor({ provider: 'qwen21', params: { provider: 'qwen21', loras: [] } });
  assert.equal(qwenEmpty.values.LoRA, '未使用');
  const kreaEmpty = rowsFor({ type: 'krea2', params: { provider: 'krea2-alis-mlx', loras: [] } });
  assert.equal(kreaEmpty.values.LoRA, '未使用');
  const gpt = rowsFor({
    provider: 'gpt',
    params: { gpt_provider_route: 'codex', main_model: 'gpt-5.6-luna', request_endpoint: 'images' },
  });
  assert.equal(gpt.values.LoRA, undefined);
  assert.equal(gpt.lora, '');
  const google = rowsFor({ provider: 'google', params: { provider: 'google-gemini' } });
  assert.equal(google.values.LoRA, undefined);
});

test('adapter roles stay explicit, names are escaped, and absolute paths are not shown', () => {
  const result = rowsFor({
    provider: 'krea2',
    params: {
      provider: 'krea2-alis-mlx',
      loras: [
        { name: '<script>alert(1)</script>', scale: 1 },
        { name: '/secret/models/studio-light.safetensors', scale: 0.8, path: '/secret/models/studio-light.safetensors' },
        { path: 'C:\\Users\\hidden\\lora.safetensors', scale: 1.1 },
      ],
      edit_adapter: { name: 'Identity Edit', scale: 0.95 },
      control_adapter: { name: 'Pose LoKr', scale: 0 },
    },
  });
  assert.equal(
    result.values.LoRA,
    '&lt;script&gt;alert(1)&lt;/script&gt; (1)\nLoRA (0.8)\nLoRA (1.1)\nIdentity Edit · 编辑适配器 (0.95)\nPose LoKr · 控制适配器 (0)'
  );
  assert.doesNotMatch(result.html, /\/secret\/models|C:\\Users|studio-light\.safetensors/);
  assert.match(result.parsed.LoRA.attrs, /title="/);
  assert.match(result.html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
});

test('copy uses the original prompt only and does not report success when the clipboard rejects', async () => {
  const original = 'A quiet studio still life with ceramic cups.\nSecond line & symbols <ok>.';
  const revised = 'A rewritten prompt that must not be copied.';
  const context = loadMeta();
  context.previewAsset = { prompt: original, revisedPrompt: revised, params: { revised_prompt: revised } };
  assert.equal(context.previewPromptText(context.previewAsset), original);
  assert.equal(context.hasPreviewPrompt(context.previewAsset), true);
  assert.equal(context.hasPreviewPrompt({ prompt: '   ' }), false);

  const success = loadClipboard();
  const copied = await success.api.copyTextToClipboardLocal(original, '提示词已复制。');
  assert.equal(copied, 'copied');
  assert.deepEqual(success.messages, ['提示词已复制。']);

  const rejected = loadClipboard({
    writeText: async () => { throw new Error('Permission denied'); },
    execCommand: () => false,
  });
  const status = await rejected.api.copyTextToClipboardLocal(original, '提示词已复制。');
  assert.equal(status, 'manual');
  assert.equal(rejected.fallbackOpen, true);
  assert.equal(rejected.fallbackText, original);
  assert.deepEqual(rejected.messages, ['自动复制受限，已打开手动复制框。']);
  assert.equal(rejected.messages.includes('提示词已复制。'), false);

  const fallbackOk = loadClipboard({
    writeText: async () => { throw new Error('Permission denied'); },
    execCommand: () => true,
  });
  assert.equal(await fallbackOk.api.copyTextToClipboardLocal(original, '提示词已复制。'), 'copied');
  assert.deepEqual(fallbackOk.messages, ['提示词已复制。']);

  const names = ['copyGalleryText', 'copyPreviewPrompt', 'copyPreviewRevisedPrompt', 'previewPromptText', 'hasPreviewPrompt', 'getPreviewPromptComparison'];
  const copyContext = vm.createContext({
    previewAsset: {
      prompt: original,
      revisedPrompt: revised,
      params: { revised_prompt: revised },
    },
    els: { deskGalleryPreviewCopyPromptBtn: { id: 'title-copy' }, deskGalleryPreviewCopyRevisedBtn: { id: 'revised-copy' } },
    window: {
      DesktopCanvas: {
        copyTextToClipboardLocal: async (text, message) => {
          copyContext.calls.push({ text, message });
          return 'copied';
        },
        setPolishCopyButtonState: (button, state) => {
          copyContext.states.push({ id: button?.id, state });
        },
      },
    },
    DesktopResults: { showTransientMessage(message) { copyContext.messages.push(message); } },
    calls: [],
    states: [],
    messages: [],
  });
  vm.runInContext(
    names.map(name => `${extractFunction(history, name)}; this.${name} = ${name};`).join('\n'),
    copyContext
  );
  const promptEvent = { preventDefault() { copyContext.prevented = true; }, stopPropagation() { copyContext.stopped = true; }, currentTarget: { id: 'title-copy' } };
  const promptStatus = await copyContext.copyPreviewPrompt(promptEvent);
  assert.equal(promptStatus, 'copied');
  assert.equal(copyContext.prevented, true);
  assert.equal(copyContext.stopped, true);
  assert.equal(copyContext.calls[0].text, original);
  assert.equal(copyContext.calls[0].message, '提示词已复制。');
  assert.equal(copyContext.calls[0].text.includes(revised), false);

  copyContext.window.DesktopCanvas.copyTextToClipboardLocal = async () => { throw new Error('denied'); };
  copyContext.messages = [];
  const failedEvent = { preventDefault() {}, stopPropagation() {}, currentTarget: { id: 'title-copy' } };
  await assert.rejects(() => copyContext.copyPreviewPrompt(failedEvent));
  assert.deepEqual(copyContext.messages, ['复制失败，请重试。']);
  assert.equal(copyContext.messages.includes('提示词已复制。'), false);
});
