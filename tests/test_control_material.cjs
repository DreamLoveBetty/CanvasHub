const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const VERSION = '20261009-control-material1';

function load() {
  const context = { window: {}, document: { body: null, activeElement: null } };
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
      sel.split(/,(?![^(]*\))/).forEach(part => assert.ok(scoped(part.trim()), `${file}: ${part.trim()}`));
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
  assert.ok(at('scripts/desktop-control-material.js?') < at('scripts/desktop-preferences.js?v=20261010-release-26-3-1'));
  assert.ok(at('styles/desktop-progress.css?') < at('styles/desktop-ambient-controls.css?v=20261009-control-material2'));
  assert.ok(at('styles/desktop-ambient-controls.css?') < at('styles/desktop-control-material.css?v=20261009-control-material3'));
  assert.ok(at('scripts/desktop-settings.js?v=20261009-settings-drawer2') > 0);
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
  const target = ':is(.desk-button, .desk-node-delete, .desk-generation-action)';
  assert.ok(read('frontend/styles/desktop-ambient-controls.css').includes(`.desk-node ${target}`));
  assert.ok(read('frontend/styles/desktop-control-material.css').includes(`.desk-node ${target}`));
  assert.ok(!read('frontend/styles/desktop-control-material.css').includes('.desk-node :is(.desk-button, .desk-node-delete)'));
});
