// ComfyUI title tags on the canvas: the Comfy node shows the workflow's default prompt and tag
// warnings, hides size fields when the workflow decides size, and runs on the default prompt
// when no text node is connected.
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

function renderParameters(meta) {
  const source = read('frontend/scripts/desktop-canvas-model-nodes.js');
  const context = vm.createContext({
    MIN_COMFY_PIXEL_SIZE: 64, MAX_COMFY_PIXEL_SIZE: 4096, COMFY_PIXEL_STEP: 8,
    escapeHtml: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    comfyWorkflowParameterOverrides: () => ({}),
    comfyWorkflowDefaultSize: () => ({ width: 1024, height: 1024 }),
    normalizeComfyPixelSize: (value, fallback) => Number(value) || fallback,
    comfyParameterPickerHtml: () => '<select data-comfy-param-picker></select>',
    comfyParameterValueHtml: (parameter, value) => `<input data-comfy-param="${parameter.id}" value="${value}">`,
    comfyInputSlotsHtml: () => '<div class="desk-comfy-input-slots">slots</div>',
  });
  const functions = ['comfySizeGridHtml', 'comfyParameterGroupsHtml', 'comfyTaggedInputsHtml', 'comfyWorkflowParametersHtml']
    .map(name => extractFunction(source, name)).join('\n');
  vm.runInContext(`${functions}; this.render = comfyWorkflowParametersHtml;`, context);
  return context.render({ id: 'c1' }, meta);
}

test('tagged workflow shows slots, default prompt, warnings and a locked size', () => {
  const html = renderParameters({ id: 'ltx.json', tag_mode: 'tags', size_editable: false, accepts_negative: true,
    default_prompt: 'slow <dolly> in', tag_warnings: ['#7 遮罩 未标记 [参考图]，不会接收画布图片'], parameters: [] });
  assert.match(html, /工作流输入/);
  assert.doesNotMatch(html, /data-comfy-field="pixelWidth"|data-comfy-param-picker/);
  assert.match(html, /尺寸由工作流决定/);
  assert.match(html, /未接入时使用工作流默认/);
  assert.match(html, /负面提示词来自标为负面的文本节点/);
  assert.match(html, /<p class="desk-comfy-default-prompt" title="slow &lt;dolly> in">slow &lt;dolly> in<\/p>/);
  assert.match(html, /desk-comfy-tag-warnings/);
  assert.match(html, /desk-comfy-input-slots/);
});

test('tagged [参数] fields are listed directly with defaults and no remove buttons', () => {
  const html = renderParameters({ id: 'sd.json', tag_mode: 'tags', size_editable: true, parameters: [
    { id: '4:steps', node_id: '4', node_title: '採樣', input_name: 'steps', label: '步数', type: 'number', default: 28 },
  ] });
  assert.match(html, /data-comfy-field="pixelWidth"/);
  assert.match(html, /<strong>採樣<\/strong>/);
  assert.match(html, /data-comfy-param="4:steps" value="28"/);
  assert.doesNotMatch(html, /data-comfy-param-remove/);
});

test('auto workflows keep editable size and the plain prompt binding', () => {
  const html = renderParameters({ id: 'sd15.json', parameters: [] });
  assert.match(html, /data-comfy-field="pixelWidth"/);
  assert.match(html, /data-comfy-field="pixelHeight"/);
  assert.match(html, /提示词来自接入的文本节点</);
  assert.doesNotMatch(html, /desk-comfy-default-prompt|desk-comfy-tag-warnings|desk-comfy-input-slots/);
  assert.match(html, /data-comfy-param-picker/);
  assert.match(renderParameters({ id: 'x', accepts_text: false, parameters: [] }), /工作流不接收提示词/);
});

test('run config falls back to the workflow default prompt', () => {
  const source = read('frontend/scripts/desktop-canvas-generation-config.js');
  const body = extractFunction(source, 'readComfyNodeConfig');
  assert.match(body, /getVisibleInputPrompt\(nodeId\) \|\| ''\)\.trim\(\) \|\| String\(selected\?\.default_prompt \|\| ''\)\.trim\(\)/);
});

test('styles live in their owning files and assets carry cache keys', () => {
  assert.match(read('frontend/styles/desktop-canvas-nodes-geometry.css'), /\.desk-comfy-default-prompt \{/);
  assert.match(read('frontend/styles/desktop-liquid.css'), /\.desk-comfy-tag-warnings \{\n  color: var\(--desk-status-warning-soft-ink\)/);
  const html = read('frontend/desktop.html');
  for (const asset of ['scripts/desktop-canvas-model-nodes.js', 'scripts/desktop-canvas-generation-config.js',
    'styles/desktop-liquid.css', 'styles/desktop-canvas-nodes-geometry.css']) {
    assert.ok(hasCacheKey(html, asset), asset);
  }
});
