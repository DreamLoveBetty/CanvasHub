const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function loadMusicView() {
  const context = { window: {} };
  vm.runInNewContext(read('frontend/scripts/desktop-music-model.js'), context);
  vm.runInNewContext(read('frontend/scripts/desktop-music-view.js'), context);
  const model = context.window.DesktopMusicModel;
  const stateIcon = { html: () => '<svg data-stub="icon"></svg>', paint(node, icon) { if (node) node.dataset.stateIcon = icon; } };
  return { model, view: context.window.DesktopMusicView.create({ model, escapeHtml: value => String(value ?? ''), stateIcon }) };
}

function declarationBlock(css, selectorRe) {
  const match = css.match(selectorRe);
  assert.ok(match, `missing rule ${selectorRe}`);
  return match[0];
}

test('Yue generate footer follows Qwen public action-row geometry, not a 16px translate patch', () => {
  const { model, view } = loadMusicView();
  const html = view.nodeHtml(model.createState('g', 'music_generate', {}));
  assert.match(html, /<footer class="desk-input-footer desk-music__generation-footer">/);
  assert.match(html, /<div class="desk-action-row">/);
  // No Telegram / Qwen pills on the Yue footer.
  assert.doesNotMatch(html, /data-qwen21-telegram|desk-pill-row|发送到 Telegram/);

  const qwen = read('frontend/styles/desktop-qwen21.css');
  const music = read('frontend/styles/desktop-music.css');
  const geometry = read('frontend/styles/desktop-canvas-nodes-geometry.css');
  const graphite = read('frontend/styles/desktop-graphite.css');

  assert.match(qwen, /\.desk-node--qwen21 \{[^}]*padding:14px/);
  assert.match(qwen, /\.desk-qwen21__body \{[^}]*gap:4px/);
  assert.doesNotMatch(qwen, /\.desk-qwen21__body \{[^}]*padding:/);
  assert.match(qwen, /\.desk-qwen21__footer \{[^}]*min-height:72px/);

  assert.match(music, /\.desk-node--music-generate \{[^}]*padding:14px/);
  assert.match(music, /\.desk-node--music-generate \.desk-music__body \{[^}]*padding:0/);
  assert.match(music, /\.desk-music__generation-footer \{[^}]*min-height:72px/);
  assert.doesNotMatch(music, /\.desk-music__generation-footer \{[^}]*padding:/);

  const footer = declarationBlock(
    geometry,
    /:where\(body\.desk-app\[data-theme\]\) \.desk-input-footer \{[^}]+\}/
  );
  assert.match(footer, /position:\s*relative/);
  const action = declarationBlock(
    geometry,
    /:where\(body\.desk-app\[data-theme\]\) \.desk-input-footer \.desk-action-row \{[^}]+\}/
  );
  assert.match(action, /position:\s*absolute/);
  assert.match(action, /right:\s*0/);
  assert.match(action, /bottom:\s*0/);

  const graphiteFooter = declarationBlock(
    graphite,
    /body\.desk-app\[data-desk-style="graphite"\] :is\(\.desk-node--input, \.desk-node--krea2, \.desk-node--moss, \.desk-node--qwen21, \.desk-node--music-generate\) \.desk-input-footer \.desk-action-row \{[^}]+\}/
  );
  assert.match(graphiteFooter, /right:\s*-6px/);
  assert.match(graphiteFooter, /bottom:\s*-6px/);
  assert.doesNotMatch(
    graphite,
    /\.desk-node--music-generate\) \.desk-generation-action \{[^}]*translate:\s*8px 8px/
  );

  const key = declarationBlock(
    geometry,
    /body\.desk-app\[data-theme\] \.desk-node \.desk-generation-action \{[^}]+\}/
  );
  assert.match(key, /width:\s*72px/);
  assert.match(key, /height:\s*72px/);
  assert.match(key, /box-sizing:\s*border-box/);

  // Expected final inset from the node border box:
  // Graphite: node padding 14px + action-row right/bottom -6px = 8px.
  // Liquid: node padding 14px + action-row right/bottom 0 = 14px.
  assert.equal(14 + (-6), 8);
  assert.equal(14 + 0, 14);
});

test('Yue generate fields inherit public control tokens; domain 9px/glass/34px rules stay off that node', () => {
  const { model, view } = loadMusicView();
  const generate = view.nodeHtml(model.createState('g', 'music_generate', {}));
  const transcribe = view.nodeHtml(model.createState('t', 'music_transcribe', {}));

  for (const field of ['operation', 'cot', 'precision', 'odeSteps', 'audioFormat']) {
    assert.match(generate, new RegExp(`<select class="desk-select" data-music-field="${field}"`));
  }
  assert.match(generate, /class="desk-number"[^>]*data-music-field="cfgScale"|data-music-field="cfgScale"[^>]*class="desk-number"/);
  assert.match(generate, /class="desk-number"[^>]*data-music-field="songId"|data-music-field="songId"[^>]*class="desk-number"/);
  assert.doesNotMatch(transcribe, /class="desk-select"/, 'non-generate music nodes keep domain markup');

  const music = read('frontend/styles/desktop-music.css');
  const controls = read('frontend/styles/desktop-controls.css');
  const liquid = read('frontend/styles/desktop-liquid.css');
  const tokens = read('frontend/styles/desktop-tokens.css');
  const graphite = read('frontend/styles/desktop-graphite.css');

  const domainFields = declarationBlock(
    music,
    /body\.desk-app \.desk-node--music:not\(\.desk-node--music-generate\) \.desk-music__body input:not\(\[type=checkbox\]\),body\.desk-app \.desk-node--music:not\(\.desk-node--music-generate\) \.desk-music__body select,body\.desk-app \.desk-node--music:not\(\.desk-node--music-generate\) \.desk-music__body textarea \{[^}]+\}/
  );
  assert.match(domainFields, /border-radius:9px/);
  assert.match(domainFields, /background:var\(--desk-node-glass-background\)/);
  assert.doesNotMatch(music, /body\.desk-app \.desk-music__body input:not\(\[type=checkbox\]\),body\.desk-app \.desk-music__body select/);

  const domainButtons = declarationBlock(
    music,
    /body\.desk-app \.desk-node--music:not\(\.desk-node--music-generate\) \.desk-music__body button:not\(\.desk-select-option\):not\(\.desk-stepper__button\):not\(\.desk-generation-action\) \{[^}]+\}/
  );
  assert.match(domainButtons, /border-radius:9px/);
  assert.doesNotMatch(music, /generation-params[^}]*height:34px/);
  assert.doesNotMatch(music, /generation-format[^}]*height:34px/);

  assert.match(tokens, /--desk-radius-control:\s*4px/);
  assert.match(tokens, /--desk-control-height-md:\s*32px/);
  const radiusAlias = read('frontend/styles/desktop-geometry.css');
  assert.match(radiusAlias, /--desk-radius:\s*var\(--desk-radius-control\)/);

  const numberGeom = declarationBlock(liquid, /\.desk-select,\n\.desk-number \{[^}]+\}/);
  assert.match(numberGeom, /height:\s*32px/);
  assert.match(numberGeom, /border-radius:\s*var\(--desk-radius\)/);

  const triggerGeom = declarationBlock(liquid, /^\.desk-select-trigger \{[^}]+\}/m);
  assert.match(triggerGeom, /height:\s*32px/);
  assert.match(triggerGeom, /border-radius:\s*var\(--desk-radius\)/);

  const triggerPaint = declarationBlock(
    controls,
    /body\.desk-app\[data-theme\] \.desk-select-shell:not\(\[data-select-variant="language"\]\):not\(\[data-select-variant="image-group-role"\]\) \.desk-select-trigger \{[^}]+\}/
  );
  assert.match(triggerPaint, /background:\s*var\(--desk-color-control-bg\)/);
  assert.match(triggerPaint, /border-color:\s*var\(--desk-color-control-border\)/);
  assert.match(triggerPaint, /box-shadow:\s*var\(--desk-shadow-button\)/);

  const numberPaint = declarationBlock(
    controls,
    /body\.desk-app\[data-theme\] \.auth-password-input,\nbody\.desk-app\[data-theme\] \.desk-select,\nbody\.desk-app\[data-theme\] \.desk-number,\nbody\.desk-app\[data-theme\] \.desk-prompt-panel textarea \{[^}]+\}/
  );
  assert.match(numberPaint, /background:\s*var\(--desk-color-control-bg\)/);
  assert.match(numberPaint, /border-color:\s*var\(--desk-color-control-border\)/);

  assert.match(graphite, /--desk-color-control-bg:\s*var\(--desk-graphite-inset\)/);
  assert.match(graphite, /--desk-color-control-border:\s*transparent/);
  assert.match(graphite, /body\.desk-app\[data-desk-style="graphite"\] \{[^}]*--desk-graphite-inset:\s*#eeeeea/);
  assert.match(graphite, /body\.desk-app\[data-desk-style="graphite"\]\[data-theme="dark"\] \{[^}]*--desk-graphite-inset:\s*#2f2f2f/);
});
