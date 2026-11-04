// Text-node prompt roles and Comfy input slots: negative text nodes never join positive prompts,
// feed Comfy `[负面]` or a GPT/Google constraint, are skipped by the prompt agent; tagged Comfy
// workflows map connected images/videos onto ordered slots with auto-fill, explicit picks and gaps.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} is not balanced`);
}

const canvas = {
  nodes: {
    comfy: { id: 'comfy', type: 'comfy' },
    pos: { id: 'pos', type: 'text', text: 'harbor at dawn' },
    neg: { id: 'neg', type: 'text', text: 'blurry', promptRole: 'negative' },
    neg2: { id: 'neg2', type: 'text', text: 'watermark', promptRole: 'negative' },
  },
  edges: [{ from: 'neg', to: 'comfy' }, { from: 'pos', to: 'comfy' }, { from: 'neg2', to: 'comfy' }],
};

function promptRoleContext() {
  const source = read('frontend/scripts/desktop-canvas-prompt-document.js');
  const context = vm.createContext({ DesktopState: { state: { canvas } }, materializeTextNode: node => node.text });
  const names = ['isNegativeTextNode', 'connectedTextNodesByRole', 'getConnectedTextNodes',
    'getConnectedNegativeTextNodes', 'getConnectedNegativePrompt', 'foldNegativeConstraint'];
  vm.runInContext(`${names.map(name => extractFunction(source, name)).join('\n')}
    this.api = { ${names.join(', ')} };`, context);
  return context.api;
}

test('negative text nodes are split from positive prompts', () => {
  const api = promptRoleContext();
  assert.deepEqual(api.getConnectedTextNodes('comfy').map(node => node.id), ['pos']);
  assert.deepEqual(api.getConnectedNegativeTextNodes('comfy').map(node => node.id), ['neg', 'neg2']);
  assert.equal(api.getConnectedNegativePrompt('comfy'), 'blurry\n\nwatermark');
  assert.equal(api.foldNegativeConstraint('a cat', 'blurry'), 'a cat\n\n负面约束：blurry');
  assert.equal(api.foldNegativeConstraint('a cat', ''), 'a cat');
  assert.equal(api.foldNegativeConstraint('a cat\n\n负面约束：blurry', 'blurry'), 'a cat\n\n负面约束：blurry');
});

test('GPT / Google fold negatives and Comfy sends them only when the workflow takes them', () => {
  const source = read('frontend/scripts/desktop-canvas-generation-config.js');
  const input = extractFunction(source, 'readInputNodeConfig');
  assert.equal((input.match(/prompt: foldNegativeConstraint\(getVisibleInputPrompt\(nodeId\), negativePrompt\)/g) || []).length, 2);
  assert.equal((input.match(/getBatchPromptItems\(nodeId\)\.map\(item => foldNegativeConstraint\(item, negativePrompt\)\)/g) || []).length, 2);
  const comfy = extractFunction(source, 'readComfyNodeConfig');
  assert.match(comfy, /negativePrompt: selected\?\.accepts_negative \? getConnectedNegativePrompt\(nodeId\) : ''/);
  assert.match(comfy, /imageSlotOrder: slotted \? slots\.imageSlotOrder : null/);
  assert.match(comfy, /if \(!slotted && selected\?\.accepts_image && !references\.length\)/);
  const api = read('frontend/scripts/desktop-api.js');
  assert.match(api, /negative_prompt: config\.negativePrompt \|\| ''/);
  assert.match(api, /images: slotImages \|\| images\.slice\(0, 8\)/);
});

function slotHarness(saved) {
  const context = vm.createContext({ window: {} });
  vm.runInContext(read('frontend/scripts/desktop-canvas-comfy-inputs.js'), context);
  const node = { id: 'comfy', type: 'comfy', comfyInputSlots: saved ? { 'wf.json': saved } : undefined };
  const images = [
    { sourceNodeId: 'imgA', title: 'A.png' },
    { sourceNodeId: 'grp', imageGroupId: 'grp', imageGroupItemId: 'i1', imageNumber: 1 },
    { sourceNodeId: 'grp', imageGroupId: 'grp', imageGroupItemId: 'i2', imageNumber: 2 },
  ];
  const videos = [{ nodeId: 'vid', name: 'in.mp4', url: '/video/in.mp4' }];
  const api = context.window.DesktopCanvasComfyInputs.create({
    getNodeState: () => node,
    getConnectedImageReferences: () => images,
    getConnectedVideoReferences: () => videos,
    escapeHtml: value => String(value),
  });
  const meta = { id: 'wf.json', input_slots: [
    { key: 'image:1', kind: 'image', label: '参考图1' },
    { key: 'image:2', kind: 'image', label: '参考图2' },
    { key: 'video:1', kind: 'video', label: '视频' },
  ] };
  return { api, node, meta };
}

const plain = value => JSON.parse(JSON.stringify(value));

test('slots auto-fill in connection order', () => {
  const { api, meta } = slotHarness();
  const config = plain(api.readConfig('comfy', meta));
  assert.deepEqual(config.referenceImages.map(item => item.sourceNodeId), ['imgA', 'grp']);
  assert.deepEqual(config.imageSlotOrder, [0, 1]);
  assert.deepEqual(config.videoSlotOrder, [0]);
});

test('explicit picks win, auto slots take the rest, none leaves a gap', () => {
  const { api, meta } = slotHarness({ 'image:1': 'group:grp:i2', 'video:1': 'none' });
  const config = plain(api.readConfig('comfy', meta));
  assert.deepEqual(config.referenceImages.map(item => item.imageGroupItemId || item.sourceNodeId), ['i2', 'imgA']);
  assert.deepEqual(config.videoSlotOrder, [-1]);
  assert.deepEqual(config.referenceVideos, []);
});

test('stale picks fall back to auto-fill and assignments are stored per workflow', () => {
  const { api, node, meta } = slotHarness({ 'image:2': 'node:gone' });
  assert.deepEqual(plain(api.readConfig('comfy', meta)).imageSlotOrder, [0, 1]);
  api.assign('comfy', 'wf.json', 'image:2', 'node:imgA');
  api.assign('comfy', 'wf.json', 'video:1', '');
  assert.deepEqual(plain(node.comfyInputSlots), { 'wf.json': { 'image:2': 'node:imgA' } });
  const html = api.html('comfy', meta);
  assert.match(html, /data-comfy-input-slot="image:1"/);
  assert.match(html, /自动（图片组 · 图1）/);
  assert.match(html, /<option value="node:imgA" selected>A\.png<\/option>/);
  assert.match(html, /不传入，沿用工作流原值/);
});

test('text node role toggle, link styling and agent targeting skip negatives', () => {
  const editor = read('frontend/scripts/desktop-canvas-text-editor.js');
  const elementCalls = [];
  const element = {
    classList: { toggle: (name, on) => elementCalls.push([name, on]) },
    querySelector: selector => (selector === '[data-text-node-role]'
      ? (element.badge ||= { hidden: true })
      : { setAttribute: (name, value) => elementCalls.push([name, value]) }),
  };
  const context = vm.createContext({ DesktopState: { state: { canvas } } });
  vm.runInContext(`${extractFunction(editor, 'setTextNodePromptRole')}
    ${extractFunction(editor, 'findConnectedTextNodeId')}
    this.setRole = setTextNodePromptRole; this.findText = findConnectedTextNodeId;`, context);
  const state = { id: 't' };
  context.setRole(element, state, true);
  assert.equal(state.promptRole, 'negative');
  assert.equal(element.badge.hidden, false);
  assert.deepEqual(elementCalls, [['is-negative-prompt', true], ['aria-pressed', 'true']]);
  context.setRole(element, state, false);
  assert.equal('promptRole' in state, false);
  assert.equal(context.findText('comfy'), 'pos');
  assert.match(editor, /data-text-action="negative" aria-pressed=/);

  assert.match(read('frontend/scripts/desktop-canvas-connections.js'), /promptRole === 'negative' \? ' is-negative-prompt' : ''/);
  assert.match(read('frontend/scripts/desktop-prompt-agent.js'), /nodes\[item\.from\]\.promptRole !== 'negative'/);
  const workflow = read('frontend/scripts/desktop-canvas-workflow.js');
  assert.match(workflow, /if \(clean\.promptRole !== 'negative'\) delete clean\.promptRole;/);
  assert.match(workflow, /delete clean\.comfyInputSlots;/);
});

test('module loads before the canvas host, is wired in, and styles use tokens', () => {
  const html = read('frontend/desktop.html');
  const moduleIndex = html.indexOf('scripts/desktop-canvas-comfy-inputs.js');
  assert.ok(moduleIndex > 0 && moduleIndex < html.indexOf('scripts/desktop-canvas.js?'));
  for (const asset of ['scripts/desktop-canvas-comfy-inputs.js', 'scripts/desktop-canvas.js', 'scripts/desktop-canvas-text-editor.js',
    'scripts/desktop-canvas-prompt-document.js', 'scripts/desktop-prompt-agent.js', 'styles/desktop-tokens.css',
    'styles/desktop-canvas-nodes.css']) {
    assert.ok(hasCacheKey(html, asset), asset);
  }
  const host = read('frontend/scripts/desktop-canvas.js');
  assert.match(host, /window\.DesktopCanvasComfyInputs\.create\(/);
  assert.match(host, /canvasComfyInputs\.assign\(nodeState\.id, nodeState\.workflow, comfyInputSlot\.dataset\.comfyInputSlot, comfyInputSlot\.value\)/);
  assert.match(host, /textAction\.dataset\.textAction === 'negative'/);
  const tokens = read('frontend/styles/desktop-tokens.css');
  assert.equal((tokens.match(/--desk-node-text-negative-border:/g) || []).length, 2, 'light and dark tokens');
  assert.match(read('frontend/styles/desktop-canvas-nodes.css'), /\.desk-link-path\.is-negative-prompt \{\n  stroke: var\(--desk-node-text-negative-border\);/);
});
