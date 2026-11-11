const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function loadLinkFlow() {
  const context = { window: {}, performance: { now: () => 0 }, requestAnimationFrame: () => 0 };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-link-flow.js'), context);
  return context.window.DesktopCanvasLinkFlow;
}

// A progress owner: the node itself or an element inside it.
const ownerIn = nodeId => ({ closest: () => ({ dataset: { nodeId } }) });
const escapeHtml = value => String(value).replace(/"/g, '&quot;');

function harness(clock = 0) {
  const LinkFlow = loadLinkFlow();
  const frames = [];
  let renders = 0;
  const flow = LinkFlow.create({
    requestRender: () => { renders += 1; },
    requestFrame: callback => { frames.push(callback); return frames.length; },
    now: () => clock,
  });
  const flush = () => frames.splice(0).forEach(callback => callback());
  return { LinkFlow, flow, flush, renders: () => renders, frames };
}

test('links into and out of a running node flow; others stay still', () => {
  const { flow, flush, renders } = harness();
  flow.setRunningOwners([ownerIn('gen')]);
  flush();
  assert.equal(renders(), 1);
  assert.equal(flow.isFlowing({ id: 'in', from: 'text', to: 'gen' }), true);
  assert.equal(flow.isFlowing({ id: 'out', from: 'gen', to: 'result' }), true);
  assert.equal(flow.isFlowing({ id: 'other', from: 'text', to: 'idle' }), false);
  assert.deepEqual([...flow.runningNodeIds()], ['gen']);
});

test('the link layer redraws only when the running set changes, once per frame', () => {
  const { flow, flush, renders, frames } = harness();
  flow.setRunningOwners([ownerIn('a')]);
  flow.setRunningOwners([ownerIn('a'), ownerIn('b')]);
  assert.equal(frames.length, 1, 'changes inside one frame share a redraw');
  flush();
  assert.equal(renders(), 1);
  // Progress polls report the same owners every second: no redraw.
  flow.setRunningOwners([ownerIn('b'), ownerIn('a')]);
  flush();
  assert.equal(renders(), 1);
  // Owners outside any node (a detached overlay) are ignored.
  flow.setRunningOwners([ownerIn('a'), ownerIn('b'), { closest: () => null }, null]);
  flush();
  assert.equal(renders(), 1);
  flow.setRunningOwners([]);
  flush();
  assert.equal(renders(), 2);
  assert.equal(flow.isFlowing({ from: 'a', to: 'b' }), false);
});

test('the overlay rides on the link path and keeps one dash phase across redraws', () => {
  const { LinkFlow, flow } = harness(1234.4);
  assert.equal(flow.overlayMarkup({ id: 'e1', from: 'x', to: 'y' }, 'M0 0', escapeHtml), '', 'idle links get no overlay');
  flow.setRunningOwners([ownerIn('y')]);
  const markup = flow.overlayMarkup({ id: 'e"1', from: 'x', to: 'y' }, 'M0 0L10 0', escapeHtml);
  assert.match(markup, /^<path class="desk-link-flow" data-edge-id="e&quot;1" d="M0 0L10 0"/);
  // 1234ms into a 700ms cycle: the redraw starts 534ms into the animation.
  assert.equal(LinkFlow.CYCLE_MS, 700);
  assert.match(markup, /style="animation-delay:-534ms"/);
});

test('flow CSS matches the module clock and graphite draws it inside the pipe', () => {
  const geometry = read('frontend/styles/desktop-canvas-nodes-geometry.css');
  const rule = geometry.match(/:where\(body\.desk-app\[data-theme\]\) \.desk-link-flow \{[^}]*\}/)[0];
  assert.match(rule, /animation: desk-link-flow 700ms linear infinite;/);
  assert.match(rule, /pointer-events: none;/);
  const [dash, gap] = rule.match(/stroke-dasharray: (\d+) (\d+);/).slice(1).map(Number);
  assert.match(geometry, new RegExp(`@keyframes desk-link-flow \\{\\n  from \\{ stroke-dashoffset: ${dash + gap}; \\}\\n  to \\{ stroke-dashoffset: 0; \\}`),
    'one dash period per cycle, moving toward the target');
  assert.match(geometry, /@media \(prefers-reduced-motion: reduce\) \{\n  :where\(body\.desk-app\[data-theme\]\) \.desk-link-flow \{\n    animation: none;/);
  assert.match(read('frontend/styles/desktop-canvas-nodes.css'), /\.desk-link-flow \{\n  stroke: var\(--desk-canvas-flow-solid\);/);

  const graphite = read('frontend/styles/desktop-graphite.css');
  const pipe = graphite.match(/graphite"\] \.desk-link-flow \{[^}]*\}/)[0];
  const [gDash, gGap] = pipe.match(/stroke-dasharray: (\d+) (\d+);/).slice(1).map(Number);
  assert.equal(gDash + gGap, dash + gap, 'graphite keeps the same period so the keyframes fit');
  assert.match(pipe, /vector-effect: none;/);
  assert.match(graphite, /\.desk-link-path:is\(\.is-hovered, \.is-selected\) \+ \.desk-link-flow \{\n  stroke: var\(--desk-graphite-card\);/);
});

test('progress activity drives the flow and the renderer draws it after each link path', () => {
  const progress = read('frontend/scripts/desktop-progress.js');
  assert.match(progress, /onActivityChange\(\[\.\.\.entries\.values\(\)\]\.filter\(entry => entry\.display\.running\)\.map\(entry => entry\.owner\)\);/);
  assert.equal((progress.match(/reportActivity\(\);/g) || []).length, 3, 'update, release and replaceRoot report');
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.match(canvas, /onActivityChange: owners => canvasLinkFlow\.setRunningOwners\(owners\),/);
  assert.match(canvas, /linkFlow: canvasLinkFlow,/);
  const connections = read('frontend/scripts/desktop-canvas-connections.js');
  assert.match(connections, /data-edge-id="\$\{safeEdgeId\}" d="\$\{d\}"><\/path>\n        \$\{linkFlow\?\.overlayMarkup\(edge, d, escapeHtml\) \|\| ''\}/);

  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-canvas-link-flow.js'));
  const at = file => html.indexOf(`scripts/${file}?v=`);
  assert.ok(at('desktop-canvas-link-flow.js') > 0 && at('desktop-canvas-link-flow.js') < at('desktop-canvas.js'));
  for (const file of ['frontend/styles/desktop-canvas-nodes-geometry.css', 'frontend/styles/desktop-liquid.css']) {
    assert.ok(!read(file).includes('desk-link-pulse'), `${file} drops the retired link pulse`);
  }
});
