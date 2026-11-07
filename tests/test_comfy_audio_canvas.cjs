// Comfy audio inputs and switchable workflows on the canvas: audio nodes connect into Comfy nodes,
// fill `[参考音频N]` slots, upload through /api/comfy/upload_audio, and switchable workflows label an
// unfilled slot "不传入" because the backend detaches it instead of keeping the workflow's value.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function audioModule(canvas) {
  const context = vm.createContext({ window: {} });
  vm.runInContext(read('frontend/scripts/desktop-canvas-comfy-audio.js'), context);
  const refreshed = [], messages = [];
  const api = context.window.DesktopCanvasComfyAudio.create({
    getCanvas: () => canvas, getNodeState: id => canvas.nodes[id],
    refreshComfyNode: id => refreshed.push(id), showMessage: text => messages.push(text),
  });
  return { api, module: context.window.DesktopCanvasComfyAudio, refreshed, messages };
}

test('audio nodes connect into Comfy and expose asset-store or URL sources', () => {
  const canvas = {
    nodes: {
      comfy: { id: 'comfy', type: 'comfy' },
      local: { id: 'local', type: 'audio', audioAssetId: 'audio-1', mediaName: 'voice.wav' },
      result: { id: 'result', type: 'audio', mediaUrl: '/audio/song.mp3' },
      empty: { id: 'empty', type: 'audio' },
      img: { id: 'img', type: 'image' },
    },
    edges: [{ from: 'local', to: 'comfy' }, { from: 'result', to: 'comfy' }, { from: 'empty', to: 'comfy' }, { from: 'img', to: 'comfy' }],
  };
  const { api, module, refreshed, messages } = audioModule(canvas);
  assert.deepEqual(plain(module.targets), { audio: ['comfy'] });
  assert.deepEqual(plain(module.policy({ type: 'audio' }, { type: 'comfy' })), { inputRole: 'audio', outputRole: 'audio' });
  assert.equal(module.policy({ type: 'comfy' }, { type: 'audio' }), null);
  assert.deepEqual(plain(api.connectedAudioReferences('comfy')), [
    { nodeId: 'local', assetId: 'audio-1', url: '', name: 'voice.wav' },
    { nodeId: 'result', assetId: '', url: '/audio/song.mp3', name: '音频' },
  ]);
  assert.equal(api.connectedAudioCount('comfy'), 3);
  api.connections.changed('local', 'comfy');
  api.connections.changed('img', 'comfy');
  assert.deepEqual(refreshed, ['comfy']);
  assert.equal(messages.length, 1);
});

function slotHarness(meta, saved) {
  const context = vm.createContext({ window: {} });
  vm.runInContext(read('frontend/scripts/desktop-canvas-comfy-inputs.js'), context);
  const node = { id: 'comfy', type: 'comfy', comfyInputSlots: saved ? { [meta.id]: saved } : undefined };
  const api = context.window.DesktopCanvasComfyInputs.create({
    getNodeState: () => node,
    getConnectedImageReferences: () => [{ sourceNodeId: 'imgA', title: 'A.png' }],
    getConnectedVideoReferences: () => [],
    getConnectedAudioReferences: () => [{ nodeId: 'aud', name: 'voice.wav', assetId: 'audio-1', url: '' }],
    escapeHtml: value => String(value),
  });
  return { api, node };
}

const META = { id: 'h3.json', switchable: true, input_slots: [
  { key: 'image:1', kind: 'image', label: '参考图1' },
  { key: 'image:2', kind: 'image', label: '参考图2' },
  { key: 'audio:1', kind: 'audio', label: '音频' },
] };

test('audio slots auto-fill and switchable workflows label gaps as 不传入', () => {
  const { api } = slotHarness(META);
  const config = plain(api.readConfig('comfy', META));
  assert.deepEqual(config.imageSlotOrder, [0, -1]);
  assert.deepEqual(config.audioSlotOrder, [0]);
  assert.deepEqual(config.referenceAudios.map(item => item.nodeId), ['aud']);
  const html = api.html('comfy', META);
  assert.match(html, /data-comfy-input-slot="audio:1"/);
  assert.match(html, /自动（voice\.wav）/);
  assert.match(html, />不传入<\/option>/);
  assert.doesNotMatch(html, /沿用工作流原值/);
  const { api: picked } = slotHarness(META, { 'audio:1': 'none' });
  assert.deepEqual(plain(picked.readConfig('comfy', META)).audioSlotOrder, [-1]);
  const { api: legacy } = slotHarness({ ...META, switchable: false });
  assert.match(legacy.html('comfy', { ...META, switchable: false }), /不传入，沿用工作流原值/);
});

test('submission uploads audio per slot and the config carries audio slots', () => {
  const apiSource = read('frontend/scripts/desktop-api.js');
  assert.match(apiSource, /uploadedAudios\.push\(await uploadComfyAudio\(client, reference\)\)/);
  assert.match(apiSource, /const audios = Array\.isArray\(config\.audioSlotOrder\) \? bySlot\(config\.audioSlotOrder, uploadedAudios\) : \[\];/);
  assert.match(apiSource, /\/api\/comfy\/upload_audio\?name=/);
  assert.match(apiSource, /window\.DesktopAudioAssets\.get\(reference\.assetId\)/);
  assert.match(apiSource, /url\.origin !== window\.location\.origin\) throw new Error\('请连接本地音频节点'\)/);
  const config = read('frontend/scripts/desktop-canvas-generation-config.js');
  assert.match(config, /referenceAudios: audioReferences,/);
  assert.match(config, /audioSlotOrder: slotted \? slots\.audioSlotOrder : null/);
});

test('module loads after comfy video, before inputs and the canvas host, and is wired in', () => {
  const html = read('frontend/desktop.html');
  const order = ['scripts/desktop-canvas-comfy-video.js', 'scripts/desktop-canvas-comfy-audio.js',
    'scripts/desktop-canvas-comfy-inputs.js', 'scripts/desktop-canvas.js'].map(asset => html.indexOf(asset));
  assert.ok(order.every(index => index > 0), order.join(','));
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  for (const asset of ['scripts/desktop-canvas-comfy-audio.js', 'scripts/desktop-canvas-comfy-inputs.js', 'scripts/desktop-api.js']) {
    assert.ok(hasCacheKey(html, asset), asset);
  }
  const host = read('frontend/scripts/desktop-canvas.js');
  assert.match(host, /window\.DesktopCanvasComfyAudio\.create\(/);
  assert.match(host, /getConnectedAudioReferences: nodeId => canvasComfyAudio\.connectedAudioReferences\(nodeId\)/);
  assert.match(host, /canvasComfyVideo\.connections, canvasComfyAudio\.connections\)/);
  assert.match(read('frontend/scripts/desktop-canvas-model-nodes.js'), /\$\{audioCount \? ` · 音频 \$\{audioCount\}` : ''\}/);
});

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

test('switch parameters render first as a select / checkbox group without a node id', () => {
  const source = read('frontend/scripts/desktop-canvas-model-nodes.js');
  const context = vm.createContext({
    escapeHtml: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
  });
  const names = ['optionListHtml', 'comfyParameterValueHtml', 'comfyParameterGroupsHtml'];
  vm.runInContext(`${names.map(name => extractFunction(source, name)).join('\n')}; this.render = comfyParameterGroupsHtml;`, context);
  const base = { node_id: '__switches__', node_title: '工作流开关', class_type: 'WorkflowSwitch' };
  const html = context.render([
    { ...base, id: 'switch:branch', label: '生成模式', type: 'select', options: ['自动', '文生', '图生'], default: '自动' },
    { ...base, id: 'switch:toggle:二采', label: '二采', type: 'boolean', default: true },
    { node_id: '552', node_title: '步数', id: '552:value', label: 'value', type: 'number', default: 8 },
  ], parameter => parameter.default, false);
  assert.match(html, /<strong>工作流开关<\/strong><\/header>/);
  assert.match(html, /<small>#552<\/small>/);
  assert.match(html, /<select class="desk-select" data-comfy-param="switch:branch" data-comfy-param-type="select">/);
  assert.match(html, /data-comfy-param="switch:toggle:二采" data-comfy-param-type="boolean" checked/);
  assert.ok(html.indexOf('switch:branch') < html.indexOf('552:value'));
});
