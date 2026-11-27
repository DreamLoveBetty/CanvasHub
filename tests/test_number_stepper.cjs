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
  assert.equal(load().SELECTOR, ':is(.desk-node, .desk-settings, .desk-layout-inspector) input[type="number"]:not([data-stepper="off"])');
  assert.match(source, /wrapper\.append\(input, button\('down'\), button\('up'\)\)/, 'field first so a wrapping <label> still labels it');
  assert.match(source, /document\.createElement\('div'\)/, 'not a span: node CSS styles `label > span` as the caption');
  assert.match(source, /el\.tabIndex = -1/);
  assert.match(source, /!control\.isConnected/, 'repeat stops when a host re-render detaches the button');
  assert.match(source, /addEventListener\('pointerdown', onPointerDown, true\)/);
  // Narrow LoRA strength columns opt out.
  assert.match(read('frontend/scripts/desktop-canvas-qwen21.js'), /data-stepper="off" data-qwen21-lora-scale/);
  assert.match(read('frontend/scripts/desktop-canvas-krea2.js'), /data-stepper="off" data-krea2-lora-scale/);
});

test('styles: spin arrows hidden, buttons inside the field, settings and fixed-width hosts accept the wrapper', () => {
  const css = read('frontend/styles/desktop-number-stepper.css');
  assert.match(css, /:is\(\.desk-node, \.desk-settings, \.desk-layout-inspector\) input\[type="number"\]::-webkit-inner-spin-button/);
  assert.match(css, /appearance: textfield;/);
  assert.match(css, /\.desk-stepper > input\[type="number"\] \{\n  width: 100%;\n  padding-inline: 30px;\n  text-align: center;/);
  assert.match(css, /\.desk-stepper:has\(> input:is\(:disabled, \[readonly\]\)\) \.desk-stepper__button \{\n  opacity: 0\.35;\n  pointer-events: none;/);
  assert.match(read('frontend/styles/desktop-geometry.css'), /label:has\(> input:not\(\[type="file"\]\):not\(\[type="hidden"\]\), > select, > \.desk-select-shell, > \.desk-stepper\)/);
  assert.match(read('frontend/styles/desktop-video-control.css'), /\.desk-video-control__options :is\(input\[type=number\], \.desk-stepper\) \{ width:100px; \}/);
  const controls = read('frontend/styles/desktop-controls.css');
  assert.match(controls, /body\.desk-app\[data-theme\] \.desk-number \{\n  font-size: var\(--desk-font-size-label\);\n\}/);
  // ComfyUI parameter fields get the shared control frame instead of the browser's 2px inset.
  assert.match(controls, /body\.desk-app\[data-theme\] \.desk-comfy-parameter-field \.desk-input \{\n  color: var\(--desk-color-control-ink\);\n  background: var\(--desk-color-control-bg\);\n  border: 1px solid var\(--desk-color-control-border\);/);
});

test('select menus: quiet rows with an LED on the chosen one, not a filled command button', () => {
  const css = read('frontend/styles/desktop-controls.css');
  const M = 'body.desk-app[data-theme] .desk-select-menu:not([data-select-variant="image-group-role"])';
  const rule = selector => { const at = css.indexOf(`${selector} {`); assert.ok(at >= 0, selector); return css.slice(at, css.indexOf('}', at)); };
  assert.match(rule(`${M} .desk-select-option`), /font-weight: var\(--desk-font-weight-medium\);/);
  assert.match(rule(`${M} .desk-select-option::before`), /width: 6px;[\s\S]*background: var\(--desk-select-led\);/);
  const selected = rule(`${M} .desk-select-option.is-selected:not(:disabled)`);
  assert.match(selected, /--desk-select-led: color-mix\(in oklab, var\(--desk-color-accent\), white 12%\);/);
  assert.match(selected, /font-weight: var\(--desk-font-weight-semibold\);/);
  assert.doesNotMatch(selected, /action-primary/);
  assert.match(css, /data-theme="dark"\] \.desk-select-menu:not\(\[data-select-variant="image-group-role"\]\) \.desk-select-option\.is-selected:not\(:disabled\) \{\n  --desk-select-led: #ff7f50;/);
});

test('desktop.html: stepper stylesheet after the field materials, script loaded, cache keys', () => {
  const html = read('frontend/desktop.html');
  const at = s => html.indexOf(s);
  assert.ok(hasCacheKey(html, 'styles/desktop-number-stepper.css') && hasCacheKey(html, 'scripts/desktop-number-stepper.js'));
  assert.ok(at('styles/desktop-number-stepper.css?') > at('styles/desktop-control-material.css?'));
  assert.ok(at('styles/desktop-number-stepper.css?') > at('styles/desktop-geometry.css?'));
  for (const asset of ['styles/desktop-controls.css', 'styles/desktop-geometry.css', 'styles/desktop-video-control.css', 'scripts/desktop-canvas-qwen21.js', 'scripts/desktop-canvas-krea2.js'])
    assert.ok(hasCacheKey(html, asset), asset);
});

test('Yue music number fields reuse desk-number and do not restyle stepper buttons as separate squares', () => {
  const view = read('frontend/scripts/desktop-music-view.js');
  const css = read('frontend/styles/desktop-music.css');
  const stepper = read('frontend/styles/desktop-number-stepper.css');
  const html = read('frontend/desktop.html');
  // type=number fields always get the public desk-number class. The generate
  // task-id text field also uses that public field class so it shares paint and
  // 32px/4px geometry; the stepper still wraps only input[type=number].
  assert.match(view, /\\btype="number"\/\.test\(attrs\) \? 'desk-number'/);
  assert.match(view, /input\('cfgScale', 'CFG（留空用默认）', n\.cfgScale, 'type="number" min="0" max="20" step="0.01"/);
  assert.match(view, /input\('seed', '种子（−1 随机）', n\.seed, 'type="number" min="-1" max="9007199254740991" step="1"'\)/);
  assert.match(view, /input\('odeSteps', '自定义 ODE 步数', n\.odeSteps, 'type="number" min="1" max="128" step="1"'\)/);
  assert.match(view, /input\('maxSeconds', '最多处理（秒）', n\.maxSeconds, 'type="number" min="1" max="1800"'\)/);
  assert.match(view, /input\('songId', '任务标识', n\.songId \|\| 'song', 'maxlength="180"', 'desk-number'\)/);
  // The music body button skin must not win over the in-field stepper buttons.
  assert.match(css, /button:not\(\.desk-select-option\):not\(\.desk-stepper__button\)/);
  assert.doesNotMatch(css, /generation-params :is\(input,select,\.desk-select-trigger,\.desk-stepper\)/);
  assert.match(stepper, /\.desk-stepper__button \{[\s\S]*?border: 0;/);
  assert.match(stepper, /background: transparent;/);
  assert.ok(hasCacheKey(html, 'styles/desktop-music.css'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-music-view.js'));
});
