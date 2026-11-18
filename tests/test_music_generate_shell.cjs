const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function loadPlates() {
  const context = { window: {} };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-port-plates.js'), context);
  return context.window.DesktopCanvasPortPlates;
}

function loadMusicView() {
  const context = { window: {} };
  vm.runInNewContext(read('frontend/scripts/desktop-music-model.js'), context);
  vm.runInNewContext(read('frontend/scripts/desktop-music-view.js'), context);
  const model = context.window.DesktopMusicModel;
  const stateIcon = { html: () => '<svg data-stub="icon"></svg>', paint(node, icon) { if (node) node.dataset.stateIcon = icon; } };
  return { model, view: context.window.DesktopMusicView.create({ model, escapeHtml: value => String(value ?? ''), stateIcon }) };
}

function classListOf(html) {
  const match = html.match(/<section class="([^"]+)"/);
  assert.ok(match, 'node root is a section');
  return match[1].split(/\s+/);
}

function collectGenerateNodeClasses() {
  const scriptsDir = path.join(root, 'frontend/scripts');
  const files = fs.readdirSync(scriptsDir).filter(name => name.endsWith('.js'));
  const found = new Map();
  for (const name of files) {
    const source = read(`frontend/scripts/${name}`);
    if (!source.includes('desk-generation-action')) continue;
    const classes = [...source.matchAll(/class="([^"]*\bdesk-node\b[^"]*)"/g)].map(match => match[1]);
    // A file may define several node types; keep those templates that also mention the 72px key.
    const chunks = source.split(/return\s+`/);
    for (const chunk of chunks) {
      if (!/\bdesk-generation-action\b/.test(chunk)) continue;
      const section = chunk.match(/class="([^"]*\bdesk-node--[\w-]+[^"]*)"/);
      if (!section) continue;
      for (const cls of section[1].split(/\s+/).filter(item => /^desk-node--[a-z0-9-]+$/.test(item))) {
        found.set(`.${cls}`, name);
      }
    }
  }
  return found;
}

test('mlx-Yue generate node uses the public glass shell and 72px generate key', () => {
  const { model, view } = loadMusicView();
  const generate = view.nodeHtml(model.createState('g', 'music_generate', {}));
  const classes = classListOf(generate);
  assert.ok(classes.includes('desk-node'));
  assert.ok(classes.includes('desk-node--music'));
  assert.ok(classes.includes('desk-node--music-generate'));
  assert.ok(classes.includes('desk-glass'), 'generate node must share the public glass shell with Qwen');
  assert.match(generate, /class="desk-input-footer desk-music__generation-footer"/);
  assert.match(generate, /<div class="desk-action-row"><button type="button" class="desk-music__generate desk-generation-action"/);
  assert.doesNotMatch(generate, /desk-music__primary/, 'the 72px key must not use the stretched domain primary style');
  assert.match(generate, /desk-generation-action__label" data-music-run-label>开始生成/);
  assert.match(generate, /data-music-action="run"/);
  assert.match(generate, /<select class="desk-select" data-music-field="operation"/);
  assert.match(generate, /<select class="desk-select" data-music-field="audioFormat"/);
  assert.match(generate, /type="number"[^>]*class="desk-number"|class="desk-number"[^>]*type="number"/);
  assert.match(generate, /data-music-field="songId"[^>]*class="desk-number"|class="desk-number"[^>]*data-music-field="songId"/);

  for (const kind of ['music_transcribe', 'music_abc', 'music_score', 'music_compare']) {
    const html = view.nodeHtml(model.createState(kind[0], kind, {}));
    const list = classListOf(html);
    assert.ok(list.includes('desk-node--music'));
    assert.ok(!list.includes('desk-node--music-generate'), kind);
    assert.ok(!list.includes('desk-generation-action') || kind === 'never', kind);
    assert.doesNotMatch(html, /desk-generation-action/, `${kind} has no 72px generate key`);
  }
});

test('run/cancel/completed/failed stay on the same notched generate key', () => {
  const { model, view } = loadMusicView();
  const button = {
    disabled: false,
    className: 'desk-music__generate desk-generation-action',
    dataset: {},
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    querySelector(selector) {
      if (selector === 'svg') return { dataset: {} };
      if (selector === '[data-music-run-label]') return this.label;
      return null;
    }
  };
  button.label = { textContent: '开始生成' };
  const states = [
    { status: 'running', expectBusy: true },
    { status: 'succeeded', expectBusy: false },
    { status: 'failed', expectBusy: false },
    { status: 'canceled', expectBusy: false }
  ];
  for (const item of states) {
    view.paintRunButton(button, model.generationButtonState({ status: item.status }));
    assert.equal(button.className, 'desk-music__generate desk-generation-action', item.status);
    assert.equal(button.attrs['aria-busy'], String(item.expectBusy), item.status);
    assert.ok(button.label.textContent.length > 0, item.status);
  }
});

test('Yue generate shell follows public tokens; generic music buttons do not restyle the 72px key', () => {
  const css = read('frontend/styles/desktop-music.css');
  const shell = css.slice(0, css.indexOf('body.desk-app .desk-music__header'));
  assert.match(shell, /\.desk-node--music:not\(\.desk-node--music-generate\)::before \{ display:none;/);
  assert.doesNotMatch(shell, /\.desk-node--music::before \{ display:none;/);
  assert.match(shell, /\.desk-node--music:not\(\.desk-node--music-generate\) \{[^}]*background:var\(--desk-node-sheen-background\),var\(--desk-node-glass-background\)/);
  // The generate node itself must not paint a private rectangular fill or hide the shared ::before.
  const generateShell = [...shell.matchAll(/body\.desk-app \.desk-node--music(?:[^{:][^{]*)?\{[^}]+\}/g)]
    .map(match => match[0])
    .filter(rule => !rule.includes(':not(.desk-node--music-generate)') && !rule.includes('[hidden]'));
  assert.ok(generateShell.length >= 1, 'shared layout rule for all music nodes remains');
  for (const rule of generateShell) {
    assert.doesNotMatch(rule, /background\s*:/, rule);
    assert.doesNotMatch(rule, /#[0-9a-fA-F]{3,8}\b/, rule);
    assert.doesNotMatch(rule, /display\s*:\s*none/, rule);
  }
  assert.match(
    css,
    /\.desk-node--music:not\(\.desk-node--music-generate\) \.desk-music__body button:not\(\.desk-select-option\):not\(\.desk-stepper__button\):not\(\.desk-generation-action\) \{/
  );
  assert.match(css, /\.desk-node--music:not\(\.desk-node--music-generate\) \.desk-music__body button\.desk-music__primary:not\(\.desk-generation-action\) \{/);
  assert.match(css, /\.desk-music__generation-footer \{[^}]*min-height:72px/);
  assert.match(css, /\.desk-node--music-generate \{[^}]*padding:14px/);
  assert.match(css, /\.desk-node--music-generate \.desk-music__body \{[^}]*padding:0/);
  assert.doesNotMatch(css, /\.desk-music__generation-footer \{[^}]*padding:4px 2px 0/);
  assert.doesNotMatch(css, /\.desk-music__generation-params[^}]*height:34px/);
  assert.doesNotMatch(css, /\.desk-music__generation-format[^}]*height:34px/);
});

test('every 72px generate key is on the shared notch list, except already documented non-graphite keys', () => {
  const P = loadPlates();
  const classes = P.NOTCHED_NODES.split(',').map(item => item.trim());
  const css = read('frontend/styles/desktop-graphite.css');
  const list = `:is(${classes.join(', ')})`;
  assert.ok(css.includes(`${list}::before {`), 'stylesheet and plate list stay in step');
  assert.ok(classes.includes('.desk-node--music-generate'));
  assert.ok(!classes.includes('.desk-node--music'));

  // Known 72px keys that are not part of the graphite generate-notch family.
  const allowedUnnotched = new Set(['.desk-node--cyimg']);
  const { model, view } = loadMusicView();
  const rendered = classListOf(view.nodeHtml(model.createState('g', 'music_generate', {})))
    .filter(name => name.startsWith('desk-node--'))
    .map(name => `.${name}`);
  const generated = collectGenerateNodeClasses();
  for (const cls of rendered) generated.set(cls, 'desktop-music-view.js (rendered)');
  const leftovers = [...generated.keys()].filter(cls => {
    if (allowedUnnotched.has(cls) || cls === '.desk-node--music') return false;
    return !classes.includes(cls);
  });
  assert.ok(rendered.includes('.desk-node--music-generate'));
  assert.deepEqual(leftovers, [], `generate keys missing from NOTCHED_NODES: ${leftovers.join(', ')}`);
});

test('cache keys for the Yue shell and notch wiring are bumped together', () => {
  const html = read('frontend/desktop.html');
  for (const file of [
    'styles/desktop-music.css',
    'scripts/desktop-music-view.js',
    'styles/desktop-graphite.css',
    'scripts/desktop-canvas-port-plates.js'
  ]) {
    assert.ok(hasCacheKey(html, file), file);
  }
});
