// Under the Images API the local Codex route calls gpt-image-2 directly: the input node locks
// reasoning effort (keeping a valid submitted value) and relabels the main model as the
// account-pool fallback model. Prompt mode stays editable (web search still runs first).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const source = read('frontend/scripts/desktop-canvas-model-nodes.js');

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} is not balanced`);
}

const REASONING = ['low', 'medium', 'high'].map(value => ({ value, label: value }));
const FUNCTIONS = [
  'optionListHtml', 'gptRouteCatalog', 'gptModelCatalogEntry', 'reasoningOption', 'codexUsesImagesApi',
  'modelReasoningOptions', 'gptReasoningOptionsForModel', 'selectedReasoningForModel', 'lockedReasoningValue',
  'updateGptRoutePresentation', 'applyGptReasoningToNode',
];

function load(endpoint, params = { reasoningEffort: 'high' }) {
  const catalog = {
    routes: {
      codex: {
        request_endpoint: endpoint,
        image_engine: { label: 'GPT Image 2' },
        models: [{ id: 'gpt-5.6-luna', reasoning_efforts: ['low', 'medium', 'high'], default_reasoning_effort: 'medium' }],
      },
      chatgpt_pool: { models: [{ id: 'gpt-5.6-luna', reasoning_efforts: [] }] },
    },
  };
  const context = vm.createContext({
    window: {},
    escapeHtml: value => String(value ?? ''),
    GPT_REASONING_OPTIONS: REASONING,
    GPT_ROUTE_PRESENTATION: { codex: { modelLabel: '主模型', engineLabel: 'GPT Image 2' }, chatgpt_pool: { modelLabel: '主模型', engineLabel: 'ChatGPT Image' } },
    gptModelCatalogRef: { current: catalog },
    inputParamsForNode: () => params,
    DesktopState: {
      normalizeGptProviderRoute: (route, fallback) => route || fallback,
      normalizeReasoningEffort: (value, fallback) => (['none', 'low', 'medium', 'high'].includes(value) ? value : fallback),
    },
  });
  vm.runInContext(`${FUNCTIONS.map(extractFunction).join('\n')}\nthis.api = { applyGptReasoningToNode, updateGptRoutePresentation, gptReasoningOptionsForModel };`, context);
  return { api: context.api, params };
}

function fakeNode() {
  const select = { innerHTML: '', value: '', disabled: false, title: '' };
  const label = { textContent: '', title: '' };
  const engine = { textContent: '', title: '' };
  return {
    dataset: {},
    select,
    label,
    querySelector: selector => (selector.includes('reasoningEffort') ? select : (selector.includes('field-label') ? label : engine)),
  };
}

test('Images API locks reasoning but keeps a valid effort as the submitted value', () => {
  const { api, params } = load('images');
  const node = fakeNode();
  const value = api.applyGptReasoningToNode(node, 'codex', 'gpt-5.6-luna');
  assert.equal(value, 'high');
  assert.equal(node.select.disabled, true);
  assert.equal(node.select.innerHTML, '<option value="high">不适用</option>');
  assert.match(node.select.title, /Images API/);
  assert.equal(params.reasoningEffort, 'high');
});

test('an effort the model does not accept falls back to the model default while locked', () => {
  const { api } = load('images', { reasoningEffort: 'none' });
  assert.equal(api.applyGptReasoningToNode(fakeNode(), 'codex', 'gpt-5.6-luna'), 'medium');
});

test('Responses API keeps reasoning editable with the model options', () => {
  const { api } = load('responses');
  const node = fakeNode();
  assert.equal(api.applyGptReasoningToNode(node, 'codex', 'gpt-5.6-luna'), 'high');
  assert.equal(node.select.disabled, false);
  assert.match(node.select.innerHTML, /value="low"[\s\S]*value="high" selected/);
});

test('the main model is relabelled as the fallback model only for Codex via the Images API', () => {
  const images = load('images').api;
  const node = fakeNode();
  images.updateGptRoutePresentation(node, 'codex');
  assert.equal(node.label.textContent, '托底模型');
  assert.match(node.label.title, /账号池托底/);

  const poolNode = fakeNode();
  images.updateGptRoutePresentation(poolNode, 'chatgpt_pool');
  assert.equal(poolNode.label.textContent, '主模型');

  const responsesNode = fakeNode();
  load('responses').api.updateGptRoutePresentation(responsesNode, 'codex');
  assert.equal(responsesNode.label.textContent, '主模型');
  assert.equal(responsesNode.label.title, '');
});

test('prompt mode stays editable, labels are translated and the node script is cache-busted', () => {
  assert.doesNotMatch(source, /data-field="promptMode"[^>]*disabled/);
  const i18n = read('frontend/scripts/desktop-i18n.js');
  for (const text of ['托底模型', 'Images API 直连 gpt-image-2，不使用推理强度', 'Images API 直连 gpt-image-2，不使用主模型；仅在账号池托底时使用']) {
    assert.ok(i18n.includes(`'${text}':`), text);
  }
  assert.ok(hasCacheKey(read('frontend/desktop.html'), 'scripts/desktop-canvas-model-nodes.js'));
});
