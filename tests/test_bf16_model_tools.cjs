const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8');

for (const engine of ['krea2', 'qwen21']) {
  test(`${engine}: BF16 is opt-in and request, estimate, busy state and provenance stay consistent`, async () => {
    const calls = [], events = [], data = {
      import_models: [{source_name: 'source.safetensors', file_size: 1024}], conversion: {status: 'idle'},
      runtime: {environment_ready: true, source_ready: true},
      models: [{id: 'existing', name: 'Existing', ready: true, builtin: true, precision: '8bit'},
        {id: 'portrait-bf16', name: '<Portrait>', precision: 'bf16', ready: true, source_format: 'comfy-scaled-fp8-e4m3fn', requantized: false}],
    };
    const sandbox = {window: {dispatchEvent: event => events.push(event.type)},
      CustomEvent: class {constructor(type) {this.type = type;}}, setTimeout: () => 1, clearTimeout() {}};
    vm.runInNewContext(read(`desktop-${engine}-tools.js`), sandbox);
    let renders = 0;
    const tool = sandbox.window[engine === 'krea2' ? 'DesktopKrea2Tools' : 'DesktopQwen21Tools'].create({
      rerender: () => renders++, api: {modelTools: async () => data,
        convertModel: async payload => {calls.push(payload); return {conversion: {status: 'queued'}};}},
    });
    await tool.activate();
    assert.equal(tool.state.draft.precision, '8bit');
    assert.match(tool.render(), /<span>输出精度<\/span>/);
    assert.match(tool.render(), /value="8bit" selected/);
    assert.match(tool.render(), /value="bf16">MLX BF16 · 不量化/);
    if (engine === 'qwen21') assert.doesNotMatch(tool.render(), /mixed-4-8/);
    tool.state.inspection = {compatible_candidate: true, estimated_outputs: {'8bit': 8 * 1024**3, bf16: 16 * 1024**3}};
    const before = renders;
    tool.handleInput({target: {closest: () => ({dataset: {[`${engine}ToolField`]: 'precision'}, value: 'bf16'})}});
    assert.equal(tool.state.draft.precision, 'bf16');
    assert.equal(renders, before + 1);
    assert.match(tool.render(), /value="bf16" selected/);
    assert.match(tool.render(), /预计 Transformer：16.0 GiB · 共享组件不变/);
    assert.match(tool.render(), /FP8 源解码/);
    assert.doesNotMatch(tool.render(), /FP8 源重新量化/);
    assert.match(tool.render(), /&lt;Portrait&gt;/);
    tool.handleClick({preventDefault() {}, target: {closest: () => ({
      matches: selector => selector === `[data-${engine}-model-convert]`, dataset: {},
    })}});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.length, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), {source_path: 'source.safetensors', model_name: '', precision: 'bf16'});
    assert.match(tool.render(), new RegExp(`data-${engine}-tool-field="precision" disabled`));
    data.conversion = {status: 'succeeded', model: data.models[1]};
    await tool.refresh(true);
    assert.ok(events.includes(`${engine}-models-changed`));
    assert.equal(tool.state.draft.precision, 'bf16');
    tool.deactivate();
  });
}

test('Krea workflow preserves BF16 model IDs while new or invalid nodes retain 8-bit defaults', () => {
  const sandbox = {window: {}};
  vm.runInNewContext(read('desktop-krea2-model.js'), sandbox);
  const model = sandbox.window.DesktopKrea2Model;
  const node = {type: 'krea2', baseModelId: 'portrait-bf16', precision: 'bf16'};
  model.normalize(node);
  assert.equal(node.precision, 'bf16'); assert.equal(node.baseModelId, 'portrait-bf16');
  model.normalize(node); assert.equal(node.precision, 'bf16');
  const empty = {type: 'krea2', precision: 'bf16'};
  model.normalize(empty);
  assert.equal(empty.precision, '8bit'); assert.equal(empty.baseModelId, model.DEFAULT_MODEL_ID);
});

test('Qwen dropdown uses the catalog label so BF16 models of the same name remain distinguishable', () => {
  assert.match(read('desktop-canvas-qwen21.js'), /item\.label\|\|item\.name\|\|item\.id/);
  assert.match(read('desktop-settings.js'), /BF16 仅导出 Transformer/);
  assert.match(read('desktop-settings.js'), /共享文本编码器仍为 8-bit/);
});
