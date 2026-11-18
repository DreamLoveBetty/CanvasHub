const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { load, plain } = require('./moss_frontend_fixture.cjs');
const { hasCacheKey } = require('./asset_keys.cjs');

const frontend = path.join(__dirname, '../frontend');
const read = file => fs.readFileSync(path.join(frontend, file), 'utf8');

function workflowFixture() {
  const pass = target => new Proxy(target, {
    get: (own, key) => key in own ? own[key] : (/Definition$/.test(String(key)) ? undefined : value => value)
  });
  const context = load(['desktop-canvas-workflow.js', 'desktop-canvas-prompt-document.js'],
    { DesktopState: { state: { outputs: {} } } });
  const documents = context.window.DesktopCanvasPromptDocument.create({
    PROMPT_DOCUMENT_SCHEMA: 'canvas-prompt', PROMPT_DOCUMENT_VERSION: 1,
    PROMPT_DOCUMENT_MAX_LENGTH: 32000, PROMPT_DOCUMENT_MAX_SEGMENTS: 100,
  });
  return context.window.DesktopCanvasWorkflow.create(pass({
    normalizePromptDocument: documents.normalizePromptDocument, materializePromptDocument: documents.materializePromptDocument,
    jsonClone: (value, fallback) => value === undefined ? fallback : JSON.parse(JSON.stringify(value)),
    normalizeNodeGroups() {}, nextTextNodeAlias: id => id,
  }));
}

const edge = (from, to, id = from + '_' + to) => ({ id, from, to, inputRole: 'prompt', outputRole: 'prompt' });
const readyPE = (id, patch = {}) => ({
  id, type: 'prompt_pe', x: 100, y: 200, width: 440, height: 420, status: 'idle', profile: 'auto',
  sourceText: '三盏纸灯', outputProfile: 'qwen_t2i', output: 'Three paper lanterns.', configKey: 'old-rule',
  model: 'fixture', ...patch,
});

test('workflow import converts a current saved rewrite to ordinary text and preserves downstream prompt order', () => {
  const fixture = {
    nodes: {
      t: { id: 't', type: 'text', text: '三盏纸灯' },
      p: readyPE('p'),
      extra: { id: 'extra', type: 'text', text: 'Soft shadows.' },
      gen: { id: 'gen', type: 'qwen21', mode: 'text' },
    },
    edges: [edge('t','p'), edge('p','gen'), edge('extra','gen')], selectedNodeId: 'p',
  };
  const original = structuredClone(fixture);
  const canvas = workflowFixture().normalizeWorkflowCanvas(fixture);
  assert.equal(canvas.nodes.p?.type, 'text');
  assert.equal(canvas.nodes.p.text, 'Three paper lanterns.');
  assert.equal(canvas.nodes.t.text, '三盏纸灯');
  assert.deepEqual(plain(canvas.nodes.p.promptDocument.segments), [{ type: 'text', text: 'Three paper lanterns.' }]);
  assert.deepEqual([canvas.nodes.p.x, canvas.nodes.p.y, canvas.nodes.p.width, canvas.nodes.p.height], [100, 200, 440, 420]);
  assert.equal(canvas.nodes.p.configKey, undefined);
  assert.equal(canvas.selectedNodeId, 'p');
  assert.deepEqual(plain(canvas.edges.map(({id}) => id)), ['extra_gen', 'p_gen']);
  assert.deepEqual(fixture, original, 'the imported file object must remain untouched');
});

test('stale and blocked PE output is preserved as separate text without resurrecting model bindings', () => {
  const fixture = {
    nodes: {
      t: { id: 't', type: 'text', text: '改过的原文' },
      stale: readyPE('stale', { output: 'Stale caption.', profile: 'moss_caption', outputProfile: 'moss_caption' }),
      empty: readyPE('empty', { output: '   ' }),
      failed: readyPE('failed', { output: 'Previous attempt.', status: 'failed' }),
      moss: { id: 'moss', type: 'moss', promptSource: { kind: 'text_node', nodeId: 'stale' } },
      gen: { id: 'gen', type: 'qwen21' },
    },
    edges: [edge('t','stale'), edge('stale','moss'), edge('empty','gen'), edge('failed','gen')],
    selectedNodeIds: ['stale', 'empty', 't'],
  };
  const canvas = workflowFixture().normalizeWorkflowCanvas(fixture);
  assert.ok(Object.values(canvas.nodes).every(node => node.type !== 'prompt_pe'));
  for (const id of ['stale','empty','failed']) assert.ok(!canvas.nodes[id]);
  const saved = Object.values(canvas.nodes).find(node => node.text === 'Stale caption.');
  assert.equal(saved?.type, 'text');
  assert.ok(Object.values(canvas.nodes).some(node => node.text === 'Previous attempt.'));
  assert.equal(canvas.nodes.moss.promptSource.nodeId, 'stale', 'a stale caption cannot silently become a MOSS binding');
  assert.deepEqual(plain(canvas.edges), []);
  assert.deepEqual(plain(canvas.selectedNodeIds), [saved.id, 't']);
});

test('session restore and workflow import share a repeatable migration; unrelated canvases are left alone', () => {
  const workflow = workflowFixture();
  const fixture = { nodes: { p: readyPE('p'), gen: { id: 'gen', type: 'qwen21' } }, edges: [edge('p','gen')] };
  const startup = workflow.migrateRetiredPromptPENodes(fixture);
  assert.notEqual(startup, fixture);
  assert.equal(fixture.nodes.p.type, 'prompt_pe');
  assert.ok(Object.values(startup.nodes).some(node => node.text === 'Three paper lanterns.'));
  assert.deepEqual(plain(workflow.normalizeWorkflowCanvas(startup)), plain(workflow.normalizeWorkflowCanvas(fixture)));
  assert.equal(workflow.migrateRetiredPromptPENodes(startup), startup);
});

test('desktop loads the migration and text-editor assets, with no dedicated PE view or stylesheet', () => {
  const html = read('desktop.html');
  assert.doesNotMatch(html, /desktop-(?:canvas-prompt-pe|prompt-pe(?:-geometry)?)[.]/);
  for (const file of ['scripts/desktop-canvas-workflow.js', 'scripts/desktop-canvas-text-editor.js']) {
    assert.ok(hasCacheKey(html, file));
    assert.ok(html.indexOf(file) < html.indexOf('scripts/desktop-canvas.js'));
  }
});

test('gallery comparison uses archived PE snapshots without changing the final prompt', () => {
  const source = read('scripts/desktop-history.js');
  const start = source.indexOf('  function getPreviewPromptComparison(');
  assert.notEqual(start, -1, 'gallery needs a PE comparison view');
  const end = source.indexOf('\n  }', start) + 4;
  const compare = vm.runInNewContext(`(${source.slice(start, end).trim()})`);
  const asset = { prompt: 'Actual submitted prompt.', params: { prompt_pe: [{ profile: 'moss_caption',
    source_text: '原来的纸灯', rewritten_prompt: 'A red paper lantern.', model: 'fixture-llm', edited: true }] } };
  const view = compare(asset);
  assert.equal(view.title, 'PE 改写对照');
  for (const value of ['原来的纸灯', 'A red paper lantern.', 'moss_caption', 'fixture-llm', '手动修改']) {
    assert.ok(view.text.includes(value), value);
  }
  assert.equal(asset.prompt, 'Actual submitted prompt.');
  assert.deepEqual(plain(compare({ params: { revised_prompt: 'Existing provider result.' } })),
    { title: 'Revised Prompt', text: 'Existing provider result.' });
});
