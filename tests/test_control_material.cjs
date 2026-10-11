const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const VERSION = '20261010-glass-shadow1';

function load() {
  const context = { window: {}, document: { body: null, activeElement: null, addEventListener() {} } };
  vm.runInNewContext(read('frontend/scripts/desktop-color-bloom.js'), context);
  vm.runInNewContext(read('frontend/scripts/desktop-control-material.js'), context);
  return context.window.DesktopControlMaterial;
}
function fakeBody() {
  const attrs = new Map(), vars = new Map();
  return {
    attrs, vars,
    setAttribute: (k, v) => attrs.set(k, String(v)),
    removeAttribute: k => attrs.delete(k),
    style: { setProperty: (k, v) => vars.set(k, v), removeProperty: k => vars.delete(k) },
  };
}
const control = (field, value, extra = {}) => {
  const el = { dataset: { controlMaterialField: field }, value, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, matches: () => false, ...extra };
  el.closest = () => el;
  return el;
};

test('defaults to the existing look; invalid values normalise; coral accent is the upstream default', () => {
  const M = load();
  assert.deepEqual({ ...M.normalize() }, { ...M.DEFAULTS });
  const prefs = M.normalize({ material: 'chrome', surface: 'wavy', body: 'gold', bodyCustom: 'nope', glass: 'x', glassCustom: '#ABC', accent: '#FF7F50' });
  assert.equal(prefs.material, 'current');
  assert.equal(prefs.surface, 'concave');
  assert.equal(prefs.body, 'default');
  assert.equal(prefs.bodyCustom, '#4f7861');
  assert.equal(prefs.glassCustom, '#aabbcc');
  assert.equal(prefs.accent, null);
});

test('apply: current leaves no attribute or variable behind; Ambient finishes project only their own knobs', () => {
  const M = load(), body = fakeBody();
  M.apply({ material: 'matte', surface: 'convex', body: 'steel', accent: '#2563eb' }, body);
  assert.equal(body.attrs.get('data-control-material'), 'ambient');
  assert.equal(body.attrs.get('data-control-finish'), 'matte');
  assert.equal(body.attrs.get('data-control-surface'), 'convex');
  assert.ok(body.attrs.has('data-control-tinted'));
  assert.equal(body.vars.get('--amb-albedo'), '#24405c');
  assert.equal(body.vars.get('--desk-control-face-ink'), '#ffffff');
  assert.equal(body.vars.get('--amb-highlight-color'), '#2563eb');

  // Surface is Matte-only; Shiny keeps the upstream cap dish.
  M.apply({ material: 'shiny', surface: 'convex' }, body);
  assert.equal(body.attrs.get('data-control-surface'), 'concave');
  assert.equal(body.vars.has('--amb-albedo'), false);
  assert.equal(body.attrs.has('data-control-tinted'), false);

  // Glass takes the tint as light hue/saturation, never an albedo.
  M.apply({ material: 'glass', glass: 'teal', body: 'steel' }, body);
  assert.equal(body.vars.get('--amb-light-hue'), '175');
  assert.equal(body.vars.get('--amb-light-saturation'), '50%');
  assert.equal(body.vars.has('--amb-albedo'), false);

  M.apply({ material: 'current', body: 'steel', accent: '#2563eb' }, body);
  assert.equal(body.attrs.size, 0);
  assert.equal(body.vars.size, 0);
});

test('settings events: selects commit on change, HEX commits only when complete, accent resets to upstream', () => {
  const M = load(), prefs = M.normalize({ material: 'matte' });
  assert.deepEqual({ ...M.patchFromEvent({ type: 'change', target: control('material', 'glass') }, prefs) }, { material: 'glass' });
  assert.equal(M.patchFromEvent({ type: 'input', target: control('material', 'glass') }, prefs), null);
  assert.deepEqual({ ...M.patchFromEvent({ type: 'change', target: control('palette', 'brass') }, prefs) }, { body: 'brass' });
  assert.deepEqual({ ...M.patchFromEvent({ type: 'change', target: control('palette', 'teal') }, M.normalize({ material: 'glass' })) }, { glass: 'teal' });
  const partial = control('hex', '#24');
  assert.equal(M.patchFromEvent({ type: 'input', target: partial }, prefs), null);
  assert.equal(partial.attrs['aria-invalid'], undefined);
  assert.deepEqual({ ...M.patchFromEvent({ type: 'change', target: control('hex', 'f0a') }, prefs) }, { body: 'custom', bodyCustom: '#ff00aa' });
  const bad = control('accent-hex', '#12');
  assert.equal(M.patchFromEvent({ type: 'change', target: bad }, prefs), null);
  assert.equal(bad.attrs['aria-invalid'], 'true');
  const reset = control('x', '', { matches: () => true });
  assert.deepEqual({ ...M.patchFromEvent({ type: 'click', target: reset }, prefs) }, { accent: null });
  const html = M.renderSettings({ material: 'current' });
  assert.match(html, /data-control-material-settings/);
  assert.match(html, /data-control-material-field="surface"[^>]*disabled/);
  // Colour rows: the shared petal picker carries our fields; Current disables them.
  assert.match(html, /<input type="hidden" data-color-bloom-value value="#[0-9A-F]{6}" data-control-material-field="color" disabled>/);
  assert.match(html, /<input type="hidden" data-color-bloom-value value="#FF7F50" data-control-material-field="accent" disabled>/);
  assert.match(html, /data-color-bloom-trigger[^>]*disabled/);
  assert.doesNotMatch(html, /type="color"/);
  const on = M.renderSettings({ material: 'matte', body: 'custom', bodyCustom: '#156ca2' });
  assert.match(on, /data-color-bloom-value value="#156CA2" data-control-material-field="color">/);
  assert.match(on, /class="desk-settings-color-field"><span data-control-material-palette-label>键体颜色<\/span><div class="desk-settings-color-field__group">\s*<select/);
  assert.deepEqual({ ...M.patchFromEvent({ type: 'input', target: control('color', '#156CA2') }, prefs) }, { body: 'custom', bodyCustom: '#156ca2' });
});

test('generated Ambient subset is current, verbatim and never escapes the opt-in scope', () => {
  execFileSync(process.execPath, [path.join(root, 'frontend/tooling/build-ambient-controls.mjs'), '--check'], { stdio: 'pipe' });
  const strip = css => css.replace(/\/\*[\s\S]*?\*\//g, '');
  const selectors = css => {
    const out = []; let depth = 0, start = 0;
    for (let i = 0; i < css.length; i++) {
      if (css[i] === '{') { if (!depth) out.push(css.slice(start, i).trim()); depth++; }
      else if (css[i] === '}') { depth--; if (!depth) start = i + 1; }
    }
    return out;
  };
  const scoped = sel => sel.startsWith('@property') || sel.startsWith('@media') || /^(:where\()?#deskApp\[data-control-material="ambient"\]/.test(sel);
  for (const file of ['frontend/styles/desktop-ambient-controls.css', 'frontend/styles/desktop-control-material.css']) {
    for (const sel of selectors(strip(read(file)))) {
      if (sel.startsWith('@media')) continue;
      // Split the selector list on top-level commas only (selectors nest :is()/:not()).
      const parts = []; let depth = 0, from = 0;
      for (let i = 0; i < sel.length; i++) {
        if (sel[i] === '(') depth++; else if (sel[i] === ')') depth--;
        else if (sel[i] === ',' && !depth) { parts.push(sel.slice(from, i)); from = i + 1; }
      }
      parts.push(sel.slice(from));
      parts.forEach(part => assert.ok(scoped(part.trim()), `${file}: ${part.trim()}`));
    }
  }
  // Inner rules of the reduced-motion block are scoped too.
  assert.match(read('frontend/styles/desktop-control-material.css'), /@media \(prefers-reduced-motion: reduce\) \{\n  #deskApp\[data-control-material="ambient"\]/);
  // Upstream bodies are copied verbatim (spot-check the lighting and dish blocks).
  const upstream = read('frontend/vendor/ambientcss/ambient.css');
  const generated = read('frontend/styles/desktop-ambient-controls.css');
  const body = (css, sel) => { const i = css.indexOf(`\n${sel} {`); return css.slice(css.indexOf('{', i), css.indexOf('\n}', i) + 2); };
  assert.ok(generated.includes(body(upstream, '.ambient')));
  assert.ok(generated.includes(body(read('frontend/vendor/ambientcss/components.css'), '.amb-button-cap::after')));
});

test('desktop.html: body scope id, module before preferences, generated CSS before adapter, cache keys', () => {
  const html = read('frontend/desktop.html');
  assert.match(html, /<body id="deskApp" class="desk-app"/);
  const at = s => html.indexOf(s);
  assert.ok(at(`scripts/desktop-control-material.js?v=${VERSION}`) > 0);
  assert.ok(at('scripts/desktop-color-bloom.js?v=20261010-color-bloom1') > 0 && at('scripts/desktop-color-bloom.js?') < at('scripts/desktop-control-material.js?'));
  assert.ok(at('scripts/desktop-control-material.js?') < at('scripts/desktop-preferences.js?v=20261010-release-26-3-1'));
  assert.ok(at('styles/desktop-progress.css?') < at('styles/desktop-ambient-controls.css?v=20261010-settings-keys1'));
  assert.ok(at('styles/desktop-ambient-controls.css?') < at('styles/desktop-control-material.css?v=20261010-glass-shadow1'));
  assert.ok(at('scripts/desktop-settings.js?v=20261011-progress-preview1') > 0);
  const prefs = read('frontend/scripts/desktop-preferences.js');
  assert.match(prefs, /controlMaterial: state\.controlMaterial/);
  assert.match(prefs, /DesktopControlMaterial\?\.apply\(state\.controlMaterial, document\.body\)/);
  const notices = read('THIRD_PARTY_NOTICES.md');
  assert.match(notices, /Ambient CSS \(commit f829df7\)/);
});

test('every canvas generate action is covered, including ones without .desk-button', () => {
  const scripts = fs.readdirSync(path.join(root, 'frontend/scripts')).filter(f => f.endsWith('.js')).map(f => read(`frontend/scripts/${f}`)).join('\n') + read('frontend/desktop.html');
  const classLists = [...scripts.matchAll(/class="([^"]*\bdesk-generation-action\b[^"]*)"/g)].map(m => m[1].split(/\s+/));
  assert.ok(classLists.some(list => !list.includes('desk-button')), 'fixture: some generate actions skip .desk-button');
  const target = ':is(.desk-button, .desk-node-delete, .desk-generation-action, .desk-key)';
  assert.ok(read('frontend/styles/desktop-ambient-controls.css').includes(`.desk-node ${target}`));
  assert.ok(read('frontend/styles/desktop-control-material.css').includes(`.desk-node ${target}`));
  assert.ok(!read('frontend/styles/desktop-control-material.css').includes('.desk-node :is(.desk-button, .desk-node-delete)'));
});

test('node push buttons opt in through the style-free .desk-key hook; segments, drop zones and the audio transport do not', () => {
  const src = file => read(`frontend/scripts/${file}`);
  const keyed = {
    'desktop-canvas-nodes.js': ['data-image-edit ', 'data-image-view-mask', 'data-image-view-prompt', 'data-layout-open', 'data-layout-quick-export', 'data-pose-open', 'data-pose-connect-input'],
    'desktop-canvas-text-editor.js': ['data-text-action="preset"', 'data-text-action="google-polish"', 'data-text-action="gpt-polish"', 'data-text-action="safe-rewrite"', 'data-text-action="clear"'],
    'desktop-topaz-video-view.js': ['data-topaz-video-import', 'data-topaz-video-workbench'],
    'desktop-video-control-view.js': ['data-control-import'],
    'desktop-canvas-audio.js': ['data-audio-action="import"', 'data-audio-action="download"'],
    'desktop-music-view.js': ['data-music-action="${action}"'],
    'desktop-canvas-image-group-model.js': ['data-image-group-insert-reference', 'data-image-group-ungroup'],
  };
  const buttonWith = (code, marker) => code.split('<button').slice(1).map(tag => tag.slice(0, tag.indexOf('>'))).filter(tag => tag.includes(marker));
  for (const [file, markers] of Object.entries(keyed)) {
    const code = src(file);
    for (const marker of markers) {
      const tags = buttonWith(code, marker);
      assert.ok(tags.length, `${file}: ${marker} rendered`);
      tags.forEach(tag => assert.match(tag, /class="desk-key[ "$]/, `${file}: ${marker}`));
    }
  }
  const unkeyed = {
    'desktop-canvas-model-nodes.js': ['data-provider=', 'data-upload-drop'],
    'desktop-music-view.js': ['data-music-tab='],
    'desktop-canvas-audio.js': ['desk-audio__wheel', 'desk-audio__play', 'desk-audio__round', 'data-audio-action="mute"'],
    'desktop-canvas-nodes.js': ['data-image-upload'],
  };
  for (const [file, markers] of Object.entries(unkeyed))
    for (const marker of markers) buttonWith(src(file), marker).forEach(tag => assert.doesNotMatch(tag, /desk-key/, `${file}: ${marker}`));
  // The hook carries no style of its own: only the opt-in Ambient layers may name it.
  for (const css of fs.readdirSync(path.join(root, 'frontend/styles')).filter(f => f.endsWith('.css') && !['desktop-ambient-controls.css', 'desktop-control-material.css'].includes(f)))
    assert.doesNotMatch(read(`frontend/styles/${css}`), /\.desk-key\b/, css);
});

test('segmented controls opt in through .desk-key-bank (nodes and settings) and read as an Ambient Select bank', () => {
  const banks = {
    'frontend/scripts/desktop-canvas-model-nodes.js': [/<div class="desk-segment desk-key-bank" role="tablist" aria-label="选择模型提供方">/],
    'frontend/desktop.html': [/<div class="desk-segment desk-key-bank" id="deskProviderSegment"/],
    'frontend/scripts/desktop-music-view.js': [/<nav class="desk-music__tabs desk-key-bank"/],
    'frontend/scripts/desktop-settings.js': [/desk-settings-canvas-interaction__segment desk-key-bank/g, /<div class="desk-video-runtime-mode desk-key-bank"/],
    'frontend/scripts/desktop-google-pool.js': [/<div class="desk-segment desk-key-bank desk-google-pool-tabs/],
  };
  for (const [file, patterns] of Object.entries(banks)) for (const pattern of patterns) assert.match(read(file), pattern, file);
  assert.equal(read('frontend/scripts/desktop-settings.js').match(/desk-settings-canvas-interaction__segment desk-key-bank/g).length, 3);
  // The hook carries no style of its own outside the opt-in Ambient layers.
  for (const css of fs.readdirSync(path.join(root, 'frontend/styles')).filter(f => f.endsWith('.css') && !['desktop-ambient-controls.css', 'desktop-control-material.css'].includes(f)))
    assert.doesNotMatch(read(`frontend/styles/${css}`), /\.desk-key-bank\b/, css);
  const S = '#deskApp[data-control-material="ambient"]';
  const BANK = ':is(.desk-node, .desk-settings) .desk-key-bank';
  const K = `${BANK} > button`, ON = `${K}:is(.is-active, [aria-pressed="true"])`;
  const generated = read('frontend/styles/desktop-ambient-controls.css');
  const block = upstream => generated.slice(generated.indexOf(`/* ${upstream} */\n`)).split('{')[0];
  // Select reading: the rail is the upstream groove; lens = ::before, diffuser cap = ::after.
  assert.equal(generated.split(`/* ambient.css: .amb-groove */\n${S} ${BANK},\n`).length - 1, 2, 'both groove blocks reach the rail');
  assert.ok(generated.includes(`/* components.css: .amb-select-lens */\n${S} ${K}::before {`));
  assert.ok(generated.includes(`/* components.css: .amb-select .ambx-key[data-on] .amb-select-lens */\n${S} ${ON}::before {`));
  assert.ok(generated.includes(`/* components.css: .amb-select .ambx-key[data-on] .amb-select-cap */\n${S} ${ON}::after {`));
  assert.ok(generated.includes(`/* components.css: .amb-select .ambx-key[data-on] */\n${S} ${ON} {`));
  for (const glass of ['ambient.css: .ambient', 'ambient.css: .amb-chamfer']) assert.ok(block(glass).includes(`${S} ${K}::after`), glass);
  // Segment keys never take the node key-cap finishes, surface or cap dish.
  for (const nodeOnly of ['ambient.css: .amb-surface', 'ambient.css: .amb-mat-shiny', 'components.css: .amb-button-cap::after'])
    assert.ok(!block(nodeOnly).includes('.desk-key-bank'), nodeOnly);
  const adapter = read('frontend/styles/desktop-control-material.css');
  assert.ok(adapter.includes(`${S} ${BANK} {\n  --amb-thickness: .27;\n  background-color: var(--amb-lume);`));
  assert.ok(adapter.includes(`${S}[data-theme="dark"] ${BANK} {\n  background-color: color-mix(in oklab, var(--amb-lume), black 55%);`));
  assert.ok(adapter.includes(`${S}[data-theme="dark"]:not([data-control-tinted]) ${BANK} {\n  --amb-albedo: #454d4f;`));
  assert.ok(adapter.includes(`${S} ${K}::before,\n${S} ${K}::after {\n  content: "";\n  z-index: -1;`));
  assert.ok(adapter.includes(`${S} ${ON} {\n  color: color-mix(in oklab, var(--_ambx-sel-color), black 68%);`));
  // Upstream rail geometry: 2px ring and rail, bank one ring rounder than its keys.
  assert.ok(adapter.includes(`${S} ${BANK} {\n  padding: var(--ambx-grid-half);\n  gap: var(--ambx-grid-half);\n  border-width: 0;\n  border-radius: calc(var(--ambx-radius-md) + var(--ambx-grid-half));`));
  assert.ok(adapter.includes(`${S} ${K}:not(.is-active):not([aria-pressed="true"]):hover:not(:disabled)`));
  // The shared node key-cap rules no longer list segment keys.
  assert.ok(!adapter.split('/* Segmented controls')[0].replace(/\/\*[\s\S]*?\*\//g, '').includes('.desk-key-bank'));
  assert.match(read('frontend/scripts/desktop-control-material.js'), /只改变画布节点里的按钮，以及节点和设置中心里的分段选择与开关/);
});

test('switches and checkboxes in nodes and settings read as upstream Switch + LED, without markup changes', () => {
  const S = '#deskApp[data-control-material="ambient"]';
  const BOX = 'input[type="checkbox"]:not(.desk-switch > input)';
  const TRACK = `:is(.desk-node, .desk-settings) :is(.desk-switch > span, ${BOX})`;
  const generated = read('frontend/styles/desktop-ambient-controls.css');
  const head = upstream => generated.slice(generated.indexOf(`/* ${upstream} */\n`)).split('{')[0];
  // Track = upstream groove; pill = ambient + fillet + convex (parts/latch.tsx SwitchPill); LED = amb-led.
  assert.ok(head('ambient.css: .amb-fillet').includes(`${S} ${TRACK}::after`));
  assert.ok(head('ambient.css: .ambient').includes(`${S} ${TRACK}::after`));
  assert.ok(head('ambient.css: .amb-surface-convex').includes(`${S} ${TRACK}::after`));
  assert.ok(generated.includes(`/* components.css: .amb-led */\n${S} ${TRACK}::before {`));
  assert.ok(generated.includes('/* components.css: .amb-led-off */'));
  assert.ok(generated.includes('/* components.css: .amb-switch:hover .amb-switch-pill */'));
  const adapter = read('frontend/styles/desktop-control-material.css');
  for (const fragment of [
    `${S} ${TRACK} {\n  --_sw-w: 28px;\n  --_sw-h: 16px;`,
    '  --amb-led-color: var(--amb-highlight-color);',
    '  -webkit-appearance: none;\n  appearance: none;',
    `${S} :is(.desk-node, .desk-settings) :is(.desk-switch > input:checked + span, ${BOX}:checked) {\n  --_sw-on: 1;`,
    '  transform: translateY(-50%) translateX(calc(var(--_sw-on) * (var(--_sw-w) * .48 - var(--_sw-h) * .22)));',
    `${S}[data-theme="dark"] ${TRACK} {\n  background-color: color-mix(in oklab, var(--amb-lume), black 55%);`,
    `${S}[data-theme="dark"] ${TRACK}::after {\n  --amb-albedo: #ff7f50;`,
  ]) assert.ok(adapter.includes(fragment), fragment);
  // No template carries a switch hook: hosts are the existing .desk-switch and native checkboxes.
  const templates = fs.readdirSync(path.join(root, 'frontend/scripts')).filter(f => f.endsWith('.js')).map(f => read(`frontend/scripts/${f}`)).join('\n');
  assert.doesNotMatch(templates, /desk-ambient-switch|desk-switch-led/);
  assert.match(read('frontend/scripts/desktop-control-material.js'), /只改变画布节点里的按钮，以及节点和设置中心里的分段选择与开关/);
});

test('settings-centre action rows take the key caps; primary and danger keep their role without the accent', () => {
  const S = '#deskApp[data-control-material="ambient"]';
  const rows = ['.desk-settings-form__actions', '.desk-settings-account__actions', '.desk-lora-actions', '.desk-qwen21-tools__inspection',
    '.desk-qwen21-tools__model', '.desk-qwen21-tools__progress', '.desk-krea2-tools__model', '.desk-krea2-tools__progress'];
  const T = `:is(.desk-node :is(.desk-button, .desk-node-delete, .desk-generation-action, .desk-key), .desk-settings :is(${rows.join(', ')}) > button, .desk-settings .desk-color-bloom__control > .desk-button)`;
  const generated = read('frontend/styles/desktop-ambient-controls.css');
  for (const block of ['ambient.css: .ambient', 'ambient.css: .amb-surface', 'components.css: .amb-button-cap::after'])
    assert.ok(generated.slice(generated.indexOf(`/* ${block} */`)).split('{')[0].includes(`${S} ${T}`), block);
  // Every settings renderer keeps its commands in one of these rows (checked against the live inventory probe).
  const settings = ['desktop-settings.js', 'desktop-google-pool.js', 'desktop-lora-settings.js', 'desktop-qwen21-tools.js', 'desktop-krea2-tools.js'].map(f => read(`frontend/scripts/${f}`)).join('\n');
  for (const row of ['desk-settings-form__actions', 'desk-settings-account__actions', 'desk-lora-actions']) assert.ok(settings.includes(row), row);
  const adapter = read('frontend/styles/desktop-control-material.css');
  assert.ok(adapter.includes(`${S} ${T}.is-primary {\n  --amb-albedo: #24405c;\n  --desk-control-face-ink: #f4f7fb;`));
  assert.ok(adapter.includes(`${S}[data-control-finish="glass"][data-theme="dark"] ${T}.is-primary {\n  --desk-control-face-ink: #dbe8ff;`));
  assert.ok(adapter.includes(`${S} ${T}.is-danger {\n  --desk-control-face-ink: #c2353b;`));
  // Segments, pickers, select triggers and link-style clears are outside the action-row target.
  assert.doesNotMatch(T, /desk-key-bank|desk-color-bloom__(petal|trigger)|desk-select|secret-clear/);
});

test('glass shadow offset: a glass-only setting scales the pane shadow ring offset and width', () => {
  const M = load(), body = fakeBody();
  assert.equal(M.normalize().glassShadow, '100');
  assert.equal(M.normalize({ glassShadow: 50 }).glassShadow, '50');
  assert.equal(M.normalize({ glassShadow: '33' }).glassShadow, '100', 'only whole-pixel quarter steps');
  M.apply({ material: 'glass', glassShadow: '50' }, body);
  assert.equal(body.vars.get('--desk-glass-shadow'), '0.5');
  M.apply({ material: 'glass', glassShadow: '100' }, body);
  assert.equal(body.vars.has('--desk-glass-shadow'), false, 'upstream default writes nothing');
  M.apply({ material: 'matte', glassShadow: '0' }, body);
  assert.equal(body.vars.has('--desk-glass-shadow'), false, 'other finishes ignore it');
  const control = (field, value) => { const el = { dataset: { controlMaterialField: field }, value, setAttribute() {}, removeAttribute() {}, matches: () => false }; el.closest = () => el; return el; };
  assert.deepEqual({ ...M.patchFromEvent({ type: 'change', target: control('glass-shadow', '25') }, M.normalize({ material: 'glass' })) }, { glassShadow: '25' });
  assert.match(M.renderSettings({ material: 'matte' }), /data-control-material-field="glass-shadow"[^>]*disabled/);
  assert.doesNotMatch(M.renderSettings({ material: 'glass' }), /data-control-material-field="glass-shadow"[^>]*disabled/);
  const adapter = read('frontend/styles/desktop-control-material.css');
  assert.match(adapter, /--_glass-sh-y: calc\(var\(--amb-light-y\) \* -1 \* \(var\(--amb-elevation\) \* 5\.16px \+ var\(--amb-thickness\) \* 5\.12px\) \* var\(--desk-glass-shadow, 1\)\);/);
  assert.match(adapter, /--_glass-ring-w: calc\(var\(--amb-thickness\) \* 4px \* var\(--desk-glass-shadow, 1\)\);/);
});
