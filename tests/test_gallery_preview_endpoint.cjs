// The gallery preview parameter panel shows the local Codex request endpoint in the route row,
// and hides the main model / reasoning effort when the Images API (gpt-image-2 direct) was used.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const history = read('frontend/scripts/desktop-history.js');

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

function loadMetaRows() {
  const context = vm.createContext({
    escapeHtml: value => String(value),
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
  vm.runInContext(`${extractFunction(history, 'getPreviewMetaRows')}; this.getPreviewMetaRows = getPreviewMetaRows;`, context);
  return params => {
    const html = context.getPreviewMetaRows({ params, hasTaskRecord: true });
    const rows = {};
    for (const match of html.matchAll(/<span>([^<]*)<\/span>\s*<strong>([^<]*)<\/strong>/g)) rows[match[1]] = match[2];
    return rows;
  };
}

const baseParams = { gpt_provider_route: 'codex', main_model: 'gpt-5.6-luna', reasoning_effort: 'medium' };

test('Images API records show the endpoint and the model actually used', () => {
  const rows = loadMetaRows()({ ...baseParams, request_endpoint: 'images' });
  assert.equal(rows['线路'], '本地 Codex · Images API');
  assert.equal(rows.Model, 'gpt-image-2');
  assert.equal(rows['主模型'], undefined);
  assert.equal(rows['推理强度'], undefined);
});

test('Responses API records keep the main model and reasoning effort', () => {
  const rows = loadMetaRows()({ ...baseParams, request_endpoint: 'responses' });
  assert.equal(rows['线路'], '本地 Codex · Responses API');
  assert.equal(rows.Model, 'gpt-5.6-luna');
  assert.equal(rows['主模型'], 'gpt-5.6-luna');
  assert.equal(rows['推理强度'], 'medium');
});

test('older records without an endpoint and pool records are unchanged', () => {
  const metaRows = loadMetaRows();
  const legacy = metaRows(baseParams);
  assert.equal(legacy['线路'], '本地 Codex');
  assert.equal(legacy['主模型'], 'gpt-5.6-luna');
  assert.equal(metaRows({ ...baseParams, gpt_provider_route: 'chatgpt_pool' })['线路'], '账号池 API');
});

test('endpoint route labels are translated and the history script cache key is set', () => {
  const i18n = read('frontend/scripts/desktop-i18n.js');
  assert.match(i18n, /'本地 Codex · Images API': 'Local Codex · Images API'/);
  assert.match(i18n, /'本地 Codex · Responses API': 'Local Codex · Responses API'/);
  assert.ok(hasCacheKey(read('frontend/desktop.html'), 'scripts/desktop-history.js'));
});
