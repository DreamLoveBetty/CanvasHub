const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, 'frontend/scripts', name), 'utf8');
const fixture = engine => ({
  base_model_directory: `/synthetic/${engine}/base`, import_directory: `/synthetic/${engine}/imports`,
  import_models: [{source_name: 'source.safetensors', file_size: 4096}],
  models: [{id: 'builtin', name: 'Synthetic Base', ready: true, builtin: true, precision: '8bit'}],
  runtime: {environment_ready: true, source_ready: true}, conversion: {status: 'idle'},
});
function controller(engine, api = {}) {
  const sandbox = {window: {dispatchEvent() {}}, CustomEvent: class {}, setTimeout: () => 1, clearTimeout() {}};
  vm.runInNewContext(read(`desktop-${engine}-tools.js`), sandbox);
  const name = engine === 'krea2' ? 'DesktopKrea2Tools' : 'DesktopQwen21Tools';
  return sandbox.window[name].create({api});
}
function click(attribute) {
  return {preventDefault() {}, target: {closest: () => ({matches: selector => selector === `[${attribute}]`, dataset: {}})}};
}

for (const engine of ['krea2', 'qwen21']) {
  test(`${engine}: idle conversion form keeps configuration and actions, not static guidance or empty inspection`, async () => {
    const tool = controller(engine, {modelTools: async () => fixture(engine)});
    assert.match(tool.render(), /打开页面后读取本地模型目录/);
    await tool.activate();
    const html = tool.render();
    for (const field of ['sourcePath', 'modelName', 'precision']) assert.ok(html.includes(`data-${engine}-tool-field="${field}"`));
    for (const action of ['inspect', 'convert']) assert.ok(html.includes(`data-${engine}-model-${action}`));
    assert.match(html, /source\.safetensors/);
    assert.doesNotMatch(html, /先检查文件头|将源文件放入|scaled-FP8|weight_scale|comfy_quant|检查不会载入完整模型/);
    assert.ok(!html.includes(`desk-${engine}-tools__inspection`));
    tool.deactivate();
  });

  test(`${engine}: actual inspection details and incompatible gating remain in the main form`, async () => {
    const tool = controller(engine, {modelTools: async () => fixture(engine)});
    await tool.activate();
    for (const compatible of [true, false]) {
      tool.state.inspection = {compatible_candidate: compatible, message: '<actual result>', source_name: '<source>.safetensors',
        file_size: 4096, tensor_count: 7, dtypes: ['F16'], source_format: 'ComfyUI scaled-FP8 E4M3FN'};
      const html = tool.render();
      assert.match(html, /&lt;actual result&gt;/);
      assert.match(html, /&lt;source&gt;\.safetensors/);
      assert.match(html, /7 tensors/);
      assert.match(html, /数据类型：F16 · 源格式：ComfyUI scaled-FP8 E4M3FN/);
      assert.ok(html.includes(`desk-${engine}-tools__inspection ${compatible ? 'is-ok' : 'is-warn'}`));
      assert.equal(html.includes(`data-${engine}-model-convert disabled`), !compatible);
    }
    tool.deactivate();
  });

  test(`${engine}: queue, conversion, completion and errors stay visible and escaped`, async () => {
    const data = fixture(engine), tool = controller(engine, {modelTools: async () => data});
    await tool.activate();
    const states = {queued: '排队中', waiting: '等待资源', running: '转换中', succeeded: '已完成', failed: '失败', canceled: '已取消'};
    for (const [status, label] of Object.entries(states)) {
      data.conversion = {status, progress: 37, message: `<${status}>`, error: status === 'failed' ? '<real error>' : ''};
      const html = tool.render(), active = ['queued', 'waiting', 'running'].includes(status);
      assert.ok(html.includes(`<strong>${label}</strong>`));
      assert.ok(html.includes(`&lt;${status}&gt;`));
      assert.match(html, /width:37%/);
      assert.equal(html.includes(`data-${engine}-convert-cancel`), active);
      assert.equal(html.includes(`data-${engine}-model-convert disabled`), active);
      if (status === 'failed') assert.match(html, /<small>&lt;real error&gt;<\/small>/);
      assert.doesNotMatch(html, /先检查文件头|将源文件放入/);
    }
    tool.deactivate();
  });

  test(`${engine}: inspect, submit and cancel still use the same domain API and draft`, async () => {
    const data = fixture(engine), calls = [];
    const tool = controller(engine, {
      modelTools: async () => data,
      inspectModel: async source => {calls.push(['inspect', source]); return {inspection: {compatible_candidate: true, message: 'Synthetic inspection', suggested_name: 'Synthetic name'}};},
      convertModel: async payload => {calls.push(['convert', JSON.parse(JSON.stringify(payload))]); return {conversion: {status: 'queued', progress: 0, message: 'Synthetic queue'}};},
      cancelModelConversion: async () => {calls.push(['cancel']); return {conversion: {status: 'canceled', message: 'Synthetic canceled'}};},
    });
    await tool.activate();
    tool.handleClick(click(`data-${engine}-model-inspect`));
    await new Promise(resolve => setImmediate(resolve));
    assert.match(tool.render(), /Synthetic inspection/);
    assert.equal(tool.state.draft.modelName, 'Synthetic name');
    tool.handleClick(click(`data-${engine}-model-convert`));
    await new Promise(resolve => setImmediate(resolve));
    assert.match(tool.render(), /Synthetic queue/);
    assert.equal(tool.state.busy, false);
    tool.handleClick(click(`data-${engine}-convert-cancel`));
    await new Promise(resolve => setImmediate(resolve));
    assert.match(tool.render(), /Synthetic canceled/);
    assert.deepEqual(calls, [['inspect', 'source.safetensors'], ['convert', {
      source_path: 'source.safetensors', model_name: 'Synthetic name', precision: '8bit',
    }], ['cancel']]);
    tool.deactivate();
  });
}

test('Qwen VAE and preparation retain actionable current state but move static instructions out', async () => {
  const data = {...fixture('qwen21'), vae: {selected_id: 'builtin', models: [{id: 'builtin', name: '<current VAE>', format: 'mflux'}],
    imports: [{source_name: 'vae.safetensors', file_size: 4096}], errors: ['<VAE error>']}};
  data.runtime.environment_ready = false;
  const tool = controller('qwen21', {modelTools: async () => data});
  await tool.activate();
  let html = tool.render();
  assert.match(html, /当前：&lt;current VAE&gt;。/);
  assert.match(html, /&lt;VAE error&gt;/);
  assert.match(html, /首次使用需要准备 Qwen 固定源码与共享模型/);
  for (const command of ['prepare', 'vae-select', 'vae-refresh', 'vae-import'])
    assert.ok(html.includes(`data-qwen21-${command === 'prepare' ? 'tools-prepare' : command}`));
  assert.doesNotMatch(html, /应用后用于新提交|无需重命名|固定 Qwen 2.1 配置|共用画布 Python 环境/);
  data.preparation = {status: 'running', message: '<Preparing resources>'};
  html = tool.render();
  assert.match(html, /&lt;Preparing resources&gt;/);
  assert.match(html, /data-qwen21-tools-prepare disabled/);
  tool.deactivate();
});

test('the existing model-tools help drawer owns all moved guidance, without a second panel or state owner', () => {
  const source = read('desktop-settings.js');
  const match = source.match(/'model-tools': (\{[\s\S]*?\n    \}),\n    comfy:/);
  assert.ok(match, 'model-tools contextual help exists');
  const help = vm.runInNewContext(`(${match[1]})`);
  assert.equal(help.title, '模型工具');
  const content = JSON.stringify(help);
  for (const phrase of ['刷新设置页', '检查不会载入完整模型', 'weight_scale/comfy_quant', 'transformer/model.diffusion_model',
    'FP8', '不会恢复已损失的精度', 'Qwen 1', '旧 Edit', 'LoRA', 'GGUF', 'Krea 2', 'MLX 8-bit', 'Mixed 4/8-bit',
    '刷新目录', '0.safetensors', '不量化、不覆盖原版', '已排队或正在生成的任务保留原选择', 'RGBA VAE', '不升级 Krea2 / YuE 依赖'])
    assert.ok(content.includes(phrase), `help preserves ${phrase}`);
  for (const section of help.sections) {
    assert.equal(section.length, 2);
    assert.ok(section[0].length && section[1].length);
    assert.ok(section[1].every(item => typeof item === 'string' && item.length > 0));
  }
  assert.match(source, /function renderSettingsInfoContent\(help\)/);
  assert.match(source, /els\.deskSettingsInfoTipContent\.innerHTML = renderSettingsInfoContent\(help\)/);
  assert.match(source, /if \(settingsInfoTipOpen\) \{\s*closeSettingsInfoTip\(\);\s*return;/);
});
