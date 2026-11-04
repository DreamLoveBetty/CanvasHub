// Negative text nodes on the local models: Qwen 2.1 sends them only where true CFG reads them
// (standard preset, CFG > 1); MOSS takes them as plain edges, keeps them out of field bindings,
// folds them into the compile fingerprint and sends `negative_prompt` with compile and generate.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { load, plain, textNode, ports, setup, mount } = require('./moss_frontend_fixture.cjs');
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

test('Qwen 2.1 sends the negative only for the standard preset with CFG > 1', () => {
  const source = read('frontend/scripts/desktop-canvas-qwen21.js');
  const context = vm.createContext({ getNegativePrompt: () => '  blurry ' });
  vm.runInContext(`${extractFunction(source, 'negativeState')} this.state = negativeState;`, context);
  const state = node => plain(context.state({ id: 'q', node }));
  assert.deepEqual([state({ preset: 'standard', guidance: 4 }).active, state({ preset: 'standard', guidance: 4 }).text], [true, 'blurry']);
  assert.equal(state({ preset: 'standard', guidance: 1 }).label, '负面未生效 · 需 CFG > 1');
  assert.equal(state({ preset: 'turbo-8', guidance: 4 }).label, '负面已忽略 · 当前预设不支持');
  context.getNegativePrompt = () => '';
  assert.deepEqual(state({ preset: 'standard', guidance: 4 }), { text: '', active: false, label: '', title: '' });
  assert.match(source, /negative_prompt:negativeState\(s\)\.active\?negativeState\(s\)\.text:''/);
  assert.match(source, /<span data-qwen21-negative hidden><\/span>/);
  assert.match(read('frontend/scripts/desktop-canvas.js'), /getNegativePrompt:nodeId=>canvasPromptDocument\.getConnectedNegativePrompt\(nodeId\)/);
});

test('MOSS negative joins the fingerprint and the requests only when present', () => {
  const calls = [];
  const api = { json: async (pathName, options = {}) => { calls.push(JSON.parse(options.body || '{}')); return { ok: true }; } };
  const context = load(['desktop-moss-model.js', 'desktop-moss-api.js'], { api, DesktopApi: { getStatus: async () => ({}) }, DesktopTasks: {} });
  const M = context.window.DesktopMossModel, A = context.window.DesktopMossAPI;
  const node = M.normalize({ type: 'moss', prompt: '猫' });
  const plainInput = M.resolveTextSources(node, ports());
  const negativeInput = M.resolveTextSources(node, { ...ports(), getNegativePrompt: () => ' 模糊 ' });
  assert.equal(plainInput.negativePrompt, '');
  assert.equal(negativeInput.negativePrompt, '模糊');
  assert.notEqual(plainInput.inputFingerprint, negativeInput.inputFingerprint);
  assert.equal(M.resolveTextSources(node, { ...ports(), getNegativePrompt: () => '' }).inputFingerprint, plainInput.inputFingerprint);
  assert.equal('negative_prompt' in A.compileRequest(node, plainInput), false);
  assert.equal(A.jobRequest(node, negativeInput).negative_prompt, '模糊');
  assert.equal(A.compileRequest(node, negativeInput).negative_prompt, '模糊');
});

test('MOSS keeps negative text nodes as plain edges and submits them', async () => {
  const t = await mount(setup({ text: [textNode('neg', '模糊', { promptRole: 'negative' }), textNode('pos', '一只猫')] }));
  t.connectNodes('neg', 'm');
  assert.equal(t.M.bound(t.moss.promptSource), false, 'a negative node is never bound as the description');
  t.connectNodes('pos', 'm');
  assert.equal(t.moss.promptSource.nodeId, 'pos');
  assert.deepEqual(plain(t.canvas.edges.map(edge => edge.from)), ['neg', 'pos']);
  assert.equal(t.log.notify.length, 0);
  await t.controller.run('m'); await t.settle();
  assert.equal(t.log.submits.length, 1);
  assert.equal(t.log.submits[0].prompt, '一只猫');
  assert.equal(t.log.submits[0].negativePrompt, '模糊');
});

test('a bound source switched to negative blocks the run instead of feeding both branches', async () => {
  const t = await mount(setup({ text: [textNode('pos', '一只猫')] }));
  t.connectNodes('pos', 'm');
  t.canvas.nodes.pos.promptRole = 'negative';
  await t.controller.run('m'); await t.settle();
  assert.equal(t.log.submits.length, 0);
  assert.equal(t.moss.status, 'failed');
});

test('local negative wiring is cache-busted', () => {
  const html = read('frontend/desktop.html');
  for (const asset of ['scripts/desktop-canvas-qwen21.js', 'scripts/desktop-canvas-moss.js', 'scripts/desktop-moss-model.js',
    'scripts/desktop-moss-api.js', 'scripts/desktop-canvas.js']) {
    assert.ok(hasCacheKey(html, asset), asset);
  }
  assert.match(read('frontend/scripts/desktop-canvas.js'), /getNegativeTextNodes:getConnectedNegativeTextNodes,/);
});
