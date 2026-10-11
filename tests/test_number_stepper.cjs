const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function load() {
  const context = { window: {}, Node: { ELEMENT_NODE: 1, DOCUMENT_NODE: 9 }, Event: class { constructor(type, init) { this.type = type; this.bubbles = !!init?.bubbles; } },
    document: { readyState: 'loading', addEventListener() {} } };
  vm.runInNewContext(read('frontend/scripts/desktop-number-stepper.js'), context);
  return context.window.DesktopNumberStepper;
}

// Minimal number field: stepUp/stepDown clamp to min/max like the browser; step="any" throws.
function field({ value = '1', min = '', max = '', step = '1', disabled = false } = {}) {
  const events = [];
  const clamp = n => Math.min(max === '' ? Infinity : Number(max), Math.max(min === '' ? -Infinity : Number(min), n));
  const move = sign => { if (step === 'any') throw new Error('InvalidStateError'); this_.value = String(clamp(Number(this_.value) + sign * Number(step))); };
  const this_ = { value, min, max, disabled, readOnly: false, events,
    stepUp: () => move(1), stepDown: () => move(-1), dispatchEvent: e => events.push(`${e.type}${e.bubbles ? '' : '!'}`) };
  return this_;
}

test('step: native step semantics, input then change, nothing at a bound or when disabled', () => {
  const S = load();
  const count = field({ value: '3', min: '1', max: '4' });
  assert.equal(S.step(count, 'up'), true);
  assert.equal(count.value, '4');
  assert.deepEqual(count.events, ['input', 'change'], 'bubbling input then change, like the native arrows');
  assert.equal(S.step(count, 'up'), false, 'at max');
  assert.equal(count.events.length, 2, 'no events without a change');
  const scale = field({ value: '0.75', step: '0.05', min: '0', max: '2' });
  S.step(scale, 'down');
  assert.equal(Number(scale.value).toFixed(2), '0.70');
  const off = field({ disabled: true });
  assert.equal(S.step(off, 'up'), false);
  assert.equal(off.value, '1');
  const any = field({ value: '0', step: 'any', min: '0', max: '1' });
  assert.equal(S.step(any, 'up'), true, 'step="any" falls back to ±1 within bounds');
  assert.equal(any.value, '1');
  assert.equal(S.step(any, 'up'), false);
});

test('module: scope, button order inside labels, hold-repeat guard and capture-phase press', () => {
  const source = read('frontend/scripts/desktop-number-stepper.js');
  assert.equal(load().SELECTOR, ':is(.desk-node, .desk-settings, .desk-layout-inspector, .desk-topaz-video-workbench__panel) input[type="number"]:not([data-stepper="off"])');
  assert.match(source, /wrapper\.append\(input, button\('down'\), button\('up'\)\)/, 'field first so a wrapping <label> still labels it');
  assert.match(source, /document\.createElement\('div'\)/, 'not a span: node CSS styles `label > span` as the caption');
  assert.match(source, /el\.tabIndex = -1/);
  assert.match(source, /!control\.isConnected/, 'repeat stops when a host re-render detaches the button');
  assert.match(source, /addEventListener\('pointerdown', onPointerDown, true\)/);
  // Narrow LoRA strength columns opt out.
  assert.match(read('frontend/scripts/desktop-canvas-qwen21.js'), /data-stepper="off" data-qwen21-lora-scale/);
  assert.match(read('frontend/scripts/desktop-canvas-krea2.js'), /data-stepper="off" data-krea2-lora-scale/);
  // Workbench: 0.01 s timeline points and slider-paired parameters keep plain fields.
  const workbench = read('frontend/scripts/desktop-topaz-video-workbench.js');
  assert.match(workbench, /data-stepper="off" data-tvwb-start-number/);
  assert.match(workbench, /data-stepper="off" data-tvwb-end-number/);
  assert.match(workbench, /<input type="number" data-stepper="off" min="\$\{esc\(field\.min\)\}"/);
});

test('styles: spin arrows hidden, buttons inside the field, settings and fixed-width hosts accept the wrapper', () => {
  const css = read('frontend/styles/desktop-number-stepper.css');
  assert.match(css, /:is\(\.desk-node, \.desk-settings, \.desk-layout-inspector, \.desk-topaz-video-workbench\) input\[type="number"\]::-webkit-inner-spin-button/);
  assert.match(css, /appearance: textfield;/);
  assert.match(css, /\.desk-stepper > input\[type="number"\] \{\n  width: 100%;\n  padding-inline: 30px;\n  text-align: center;/);
  assert.match(css, /\.desk-stepper:has\(> input:is\(:disabled, \[readonly\]\)\) \.desk-stepper__button \{\n  opacity: 0\.35;\n  pointer-events: none;/);
  assert.match(read('frontend/styles/desktop-geometry.css'), /label:has\(> input:not\(\[type="file"\]\):not\(\[type="hidden"\]\), > select, > \.desk-select-shell, > \.desk-stepper\)/);
  assert.match(read('frontend/styles/desktop-video-control.css'), /\.desk-video-control__options :is\(input\[type=number\], \.desk-stepper\) \{ width:100px; \}/);
  const controls = read('frontend/styles/desktop-controls.css');
  assert.match(controls, /body\.desk-app\[data-theme\] \.desk-number \{\n  font-size: 12px;\n\}/);
  // ComfyUI parameter fields get the shared control frame instead of the browser's 2px inset.
  assert.match(controls, /body\.desk-app\[data-theme\] \.desk-comfy-parameter-field \.desk-input \{\n  color: var\(--desk-color-control-ink\);\n  background: var\(--desk-color-control-bg\);\n  border: 1px solid var\(--desk-color-control-border\);/);
});

test('select menus: quiet rows with an LED on the chosen one, not a filled command button', () => {
  const css = read('frontend/styles/desktop-controls.css');
  const M = 'body.desk-app[data-theme] .desk-select-menu:not([data-select-variant="image-group-role"])';
  const rule = selector => { const at = css.indexOf(`${selector} {`); assert.ok(at >= 0, selector); return css.slice(at, css.indexOf('}', at)); };
  assert.match(rule(`${M} .desk-select-option`), /font-weight: 500;/);
  assert.match(rule(`${M} .desk-select-option::before`), /width: 6px;[\s\S]*background: var\(--desk-select-led\);/);
  const selected = rule(`${M} .desk-select-option.is-selected:not(:disabled)`);
  assert.match(selected, /--desk-select-led: color-mix\(in oklab, var\(--desk-color-accent\), white 12%\);/);
  assert.match(selected, /font-weight: 650;/);
  assert.doesNotMatch(selected, /action-primary/);
  assert.match(css, /data-theme="dark"\] \.desk-select-menu:not\(\[data-select-variant="image-group-role"\]\) \.desk-select-option\.is-selected:not\(:disabled\) \{\n  --desk-select-led: #ff7f50;/);
});

test('desktop.html: stepper stylesheet after the field materials, script loaded, cache keys', () => {
  const html = read('frontend/desktop.html');
  const at = s => html.indexOf(s);
  assert.ok(hasCacheKey(html, 'styles/desktop-number-stepper.css') && hasCacheKey(html, 'scripts/desktop-number-stepper.js'));
  assert.ok(at('styles/desktop-number-stepper.css?') > at('styles/desktop-control-material.css?'));
  assert.ok(at('styles/desktop-number-stepper.css?') > at('styles/desktop-geometry.css?'));
  for (const asset of ['scripts/desktop-topaz-video-workbench.js', 'styles/desktop-controls.css', 'styles/desktop-geometry.css', 'styles/desktop-video-control.css', 'scripts/desktop-canvas-qwen21.js', 'scripts/desktop-canvas-krea2.js'])
    assert.ok(hasCacheKey(html, asset), asset);
});
