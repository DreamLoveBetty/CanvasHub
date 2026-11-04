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
const box = (x, y, width = 300, height = 200) => ({ x, y, width, height });

test('links pick the facing sides of the two nodes, including top/bottom', () => {
  const P = loadPlates();
  const nodes = { a: box(0, 0), right: box(600, 0), below: box(0, 500), left: box(-700, 0) };
  const { routes } = P.layout([
    { id: 'e1', from: 'a', to: 'right' },
    { id: 'e2', from: 'a', to: 'below' },
    { id: 'e3', from: 'a', to: 'left' },
  ], id => nodes[id]);
  assert.deepEqual({ ...routes.get('e1'), from: 0, to: 0 }, { from: 0, to: 0, fromSide: 'right', toSide: 'left' });
  assert.equal(routes.get('e2').fromSide, 'bottom');
  assert.equal(routes.get('e2').toSide, 'top');
  assert.equal(routes.get('e3').fromSide, 'left');
  // Diagonal neighbours with room for a horizontal run keep left/right, even when the
  // vertical gap is larger (no pipe hugging the next node's top edge).
  const diagonal = { text: box(-500, -530, 600, 360), input: box(240, 100, 720, 460) };
  const run = P.layout([{ id: 'd', from: 'text', to: 'input' }], id => diagonal[id]).routes.get('d');
  assert.equal(run.fromSide, 'right');
  assert.equal(run.toSide, 'left');
  // Endpoints sit on the plate face, 9px outside the card edge.
  assert.equal(routes.get('e1').from.x, 300 + P.PLATE.depth);
  assert.equal(routes.get('e2').from.y, 200 + P.PLATE.depth);
});

test('ports sharing a side are spaced evenly on one merged plate and lean toward partners', () => {
  const P = loadPlates();
  const nodes = { src: box(0, 0, 300, 400), t1: box(600, -300), t2: box(600, 100), t3: box(600, 500) };
  const edges = ['t1', 't2', 't3'].map((to, i) => ({ id: `e${i}`, from: 'src', to }));
  const { routes, plates } = P.layout(edges, id => nodes[id]);
  const ys = edges.map(edge => routes.get(edge.id).from.y).sort((a, b) => a - b);
  assert.equal(ys[1] - ys[0], P.PORT_GAP);
  assert.equal(ys[2] - ys[1], P.PORT_GAP);
  // One plate path for the shared side plus one neck per port; three single-port targets add three plates.
  const subpaths = plates.match(/M/g).length;
  assert.equal(subpaths, 1 + 3 + 3 + 3);
  const range = P.edgeRange({ x: 0, y: 0, w: 300, h: 400 }, 'right');
  ys.forEach(y => assert.ok(y >= range.min && y <= range.max));
});

test('a near-level single link snaps straight; the input notch keeps ports off the generate key', () => {
  const P = loadPlates();
  const nodes = { a: box(0, 0), b: box(600, 14) };
  const route = P.layout([{ id: 'e', from: 'a', to: 'b' }], id => nodes[id]).routes.get('e');
  assert.equal(route.from.y, route.to.y);

  const notch = { w: 88, h: 88, r: 12 };
  const gen = { gen: box(0, 0, 720, 460), low: box(900, 1000) };
  const low = P.layout([{ id: 'g', from: 'gen', to: 'low' }], id => gen[id], id => (id === 'gen' ? notch : null)).routes.get('g');
  if (low.fromSide === 'right') assert.ok(low.from.y <= 460 - notch.h - notch.r);
  if (low.fromSide === 'bottom') assert.ok(low.from.x <= 720 - notch.w - notch.r);
});

test('a single port at the end of its range levels the partner cluster instead of leaving a jog', () => {
  const P = loadPlates();
  // The text node's lowest reachable port sits just above where the input cluster wants it.
  const nodes = { text: box(-500, -530, 600, 360), other: box(-500, -30, 600, 360), input: box(240, -430, 720, 460) };
  const { routes } = P.layout([
    { id: 'a', from: 'text', to: 'input' },
    { id: 'b', from: 'other', to: 'input' },
  ], id => nodes[id], id => (id === 'input' ? { w: 88, h: 88, r: 12 } : null));
  assert.equal(routes.get('a').from.y, routes.get('a').to.y);
  assert.equal(routes.get('b').to.y - routes.get('a').to.y, P.PORT_GAP);
});

test('a transient plate grows with the swell, stays clear of corners and the notch, and ends on its face', () => {
  const P = loadPlates();
  const rect = { x: 0, y: 0, w: 720, h: 460 };
  const full = P.edgePlate(rect, 'right', 2000, 1, P.NOTCH);
  const range = P.edgeRange(rect, 'right', P.NOTCH);
  assert.equal(full.along, range.max);
  assert.ok(full.along < 460 - P.NOTCH.h);
  assert.deepEqual({ ...full.face }, { x: 720 + P.PLATE.depth, y: range.max });
  assert.equal(P.edgePlate(rect, 'top', -50).along, P.edgeRange(rect, 'top').min);
  assert.equal(P.edgePlate(rect, 'left', 200, 0).path, '');
  assert.match(P.edgePlate(rect, 'bottom', 200, 0.5).path, /^M.* Z$/);
});

test('graphite hover swell, drag preview and notch ring are wired through the injected plate module', () => {
  const ports = read('frontend/scripts/desktop-canvas-port-interaction.js');
  assert.match(ports, /portPlates\.edgePlate\(/);
  assert.match(ports, /style === 'droplet' \|\| plate/);
  const connections = read('frontend/scripts/desktop-canvas-connections.js');
  assert.match(connections, /data-live-connection-plate/);
  assert.match(connections, /snapPlate\?\.face/);
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.equal(canvas.match(/portPlates: window\.DesktopCanvasPortPlates/g).length, 2);
  assert.match(canvas, /'desktop:theme-style-change', refreshFloatingSwellStyle/);
  const css = read('frontend/styles/desktop-graphite.css');
  // Notched nodes are borderless in graphite, so only the notch-shaped ring marks selection.
  assert.match(css, /\.desk-node--video-control\) \{\n  --desk-node-border-width: 0px;/);
  assert.match(css, /\.desk-node-swell-border__paint \{\n  fill: var\(--desk-graphite-card\);/);
  assert.match(css, /\.desk-link-path:is\(\.is-preview, \.is-pending\) \{\n  stroke: var\(--desk-graphite-card\);\n  stroke-width: 8;/);
});

test('self links and incomplete edges are ignored', () => {
  const P = loadPlates();
  const result = P.layout([{ id: 's', from: 'a', to: 'a' }, { id: 'x', from: 'a' }], () => box(0, 0));
  assert.equal(result.routes.size, 0);
  assert.equal(result.plates, '');
});

function loadPreferences(saved) {
  const attrs = el => {
    const map = new Map();
    return Object.assign(el, {
      map,
      setAttribute: (k, v) => map.set(k, String(v)),
      removeAttribute: k => map.delete(k),
      classList: { add() {}, remove() {} },
      dataset: {},
      style: { setProperty() {}, removeProperty() {} },
    });
  };
  const body = attrs({});
  const documentElement = attrs({});
  const events = [];
  const store = new Map([['desktop_ui_preferences_v1', JSON.stringify(saved)]]);
  const context = {
    window: { dispatchEvent: event => events.push(event), addEventListener() {} },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
    document: { readyState: 'complete', body, documentElement, getElementById: () => null, addEventListener() {}, querySelector: () => null },
    setTimeout: () => 0,
    clearTimeout() {},
  };
  context.window.setTimeout = context.setTimeout;
  context.window.clearTimeout = context.clearTimeout;
  vm.runInNewContext(read('frontend/scripts/desktop-preferences.js'), context);
  return { prefs: context.window.DesktopPreferences, body, events, store };
}

test('theme style is persisted, projected onto <body> and independent of light/dark', () => {
  const { prefs, body } = loadPreferences({ theme: 'dark', themeStyle: 'graphite' });
  assert.equal(prefs.state.themeStyle, 'graphite');
  assert.equal(body.map.get('data-desk-style'), 'graphite');
  assert.equal(body.map.get('data-theme'), 'dark');

  const fresh = loadPreferences({ themeStyle: 'neon' });
  assert.equal(fresh.prefs.state.themeStyle, 'liquid');
  assert.equal(fresh.body.map.has('data-desk-style'), false);
  fresh.prefs.setThemeStyle('graphite');
  assert.equal(fresh.body.map.get('data-desk-style'), 'graphite');
  assert.equal(JSON.parse(fresh.store.get('desktop_ui_preferences_v1')).themeStyle, 'graphite');
  assert.equal(fresh.events.at(-1).type, 'desktop:theme-style-change');
  fresh.prefs.setThemeStyle('liquid');
  assert.equal(fresh.body.map.has('data-desk-style'), false);
  assert.equal(fresh.prefs.state.theme, 'light');
});

test('desktop page loads the graphite assets in order and wires the settings card', () => {
  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'styles/desktop-graphite.css'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-canvas-port-plates.js'));
  // Graphite overrides must load after every other desktop stylesheet.
  const graphite = html.indexOf('styles/desktop-graphite.css');
  assert.equal(html.indexOf('<link rel="stylesheet"', graphite), -1);
  assert.ok(html.indexOf('desktop-canvas-port-plates.js') < html.indexOf('desktop-canvas-connections.js'));
  assert.match(html, /saved\?\.themeStyle === 'graphite'/);

  const settings = read('frontend/scripts/desktop-settings.js');
  assert.match(settings, /data-theme-style="graphite"/);
  assert.match(settings, /setThemeStyle/);
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.match(canvas, /'desktop:theme-style-change', updateLinkPath/);
  const css = read('frontend/styles/desktop-graphite.css');
  assert.doesNotMatch(css, /!important/);
  assert.doesNotMatch(css.replace(/\/\*[\s\S]*?\*\//g, ''), /body\.desk-app(?!\[data-desk-style="graphite"\])[\s.:[]/);
});

test('every generate node with a 72px key is notched, in the stylesheet and the plate layout alike', () => {
  const P = loadPlates();
  const classes = P.NOTCHED_NODES.split(',').map(s => s.trim());
  const css = read('frontend/styles/desktop-graphite.css');
  const list = `:is(${classes.join(', ')})`;
  assert.ok(css.includes(`${list}::before {`), 'card layer is cut on every notched node');
  assert.ok(css.includes(`${list}.is-selected::after {`), 'selection ring follows the notch on every notched node');
  assert.match(css, /::before \{[^}]*display: block;/);
  const element = cls => ({ matches: selector => selector.split(',').map(s => s.trim()).includes(cls) });
  assert.equal(P.notchOf(element('.desk-node--pose')), P.NOTCH);
  assert.equal(P.notchOf(element('.desk-node--comfy')), null);
  assert.equal(P.notchOf(null), null);
});

test('ports ease along their side and plates grow in / shrink out when a link switches sides', () => {
  const P = loadPlates();
  const nodes = { a: box(0, 0, 300, 400), b: box(600, -300) };
  const geometry = id => nodes[id];
  const edges = [{ id: 'e', from: 'a', to: 'b' }];
  const motion = P.createMotion();
  const still = P.layout(edges, geometry, undefined, null);
  const first = P.layout(edges, geometry, undefined, motion, 1000);
  assert.equal(first.settled, true, 'the first layout snaps');
  assert.deepEqual(first.routes.get('e'), still.routes.get('e'));

  nodes.b = box(600, 300);
  const target = P.layout(edges, geometry).routes.get('e').from.y;
  const start = first.routes.get('e').from.y;
  const mid = P.layout(edges, geometry, undefined, motion, 1016);
  assert.equal(mid.settled, false);
  const y = mid.routes.get('e').from.y;
  assert.ok(y > start && y < target, `slides part of the way (${start} → ${y} → ${target})`);
  const done = P.layout(edges, geometry, undefined, motion, 3000);
  assert.equal(done.settled, true);
  assert.equal(done.routes.get('e').from.y, target);

  // b moves below a: the link leaves from the bottom; the new plate grows, the old shrinks.
  nodes.b = box(0, 700);
  const switched = P.layout(edges, geometry, undefined, motion, 3016);
  assert.equal(switched.routes.get('e').fromSide, 'bottom');
  assert.ok(switched.routes.get('e').from.y < 400 + P.PLATE.depth, 'growing plate face is still near the card');
  const plates = d => (d.match(/M/g) || []).length;
  assert.ok(plates(switched.plates) > plates(P.layout(edges, geometry).plates), 'old plate is still shrinking');
  const later = P.layout(edges, geometry, undefined, motion, 6000);
  assert.equal(later.settled, true);
  assert.equal(later.plates, P.layout(edges, geometry).plates);
});

test('each linked node reports a pointer target over its plate', () => {
  const P = loadPlates();
  const nodes = { a: box(0, 0), b: box(600, 0) };
  const { ports } = P.layout([{ id: 'e', from: 'a', to: 'b' }], id => nodes[id]);
  const [target] = ports.get('b');
  assert.equal(target.side, 'left');
  assert.equal(target.incoming, 1);
  assert.ok(target.hit.x < 0 && target.hit.x + target.hit.w > 0, 'straddles the card edge');
  assert.ok(target.hit.w >= P.PLATE.depth);
  assert.equal(target.hit.h, 2 * (P.PIPE_HALF + P.PLATE.pad));
  assert.equal(ports.get('a')[0].incoming, 0);

  const css = read('frontend/styles/desktop-graphite.css');
  assert.match(css, /\.desk-port\[data-semantic-port\]\[data-plate-hit\] \{[^}]*left: var\(--desk-graphite-port-x\);/);
  const connections = read('frontend/scripts/desktop-canvas-connections.js');
  assert.match(connections, /syncGraphitePortHits\(layout\.ports\)/);
  assert.match(connections, /prefers-reduced-motion: reduce/);
});

test('domain shells and empty states are flat graphite surfaces in both themes', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  // Liquid dark paints every non-image shell at (0,4,1); graphite shell rules sit above it.
  assert.match(css, /\[data-desk-style="graphite"\] \.desk-canvas \.desk-node--text \{\n  background: var\(--desk-node-text-background\);/);
  assert.match(css, /\[data-desk-style="graphite"\] \.desk-canvas \.desk-node--audio \{[^}]*--desk-audio-button: var\(--desk-graphite-inset\);/);
  ['--desk-node-image-placeholder-background', '--desk-video-preview-background', '--desk-file-card-background'].forEach(token => {
    assert.equal(css.split(`${token}:`).length - 1, 2, `${token} is set for light and dark`);
  });
});

test('pulling a link off a shared graphite plate detaches the grabbed link and keeps its source plate', () => {
  const connections = read('frontend/scripts/desktop-canvas-connections.js');
  const detach = connections.slice(connections.indexOf('function startConnectionDetachDrag'));
  // The grabbed link is the incoming route end nearest the pointer, not simply the newest link.
  assert.match(detach, /graphiteGrabbedIncomingEdge\(nodeId, pointer\) \|\| getDetachableIncomingEdge\(nodeId\)/);
  assert.match(connections, /Math\.hypot\(route\.to\.x - point\.x, route\.to\.y - point\.y\)/);
  // The preview leaves from the source plate face and draws that plate while dragging.
  assert.match(detach, /fromAnchor: graphiteSourcePlate\(sourcePlate\)\?\.face \|\| getAnchor/);
  assert.match(connections, /syncLiveConnectionPlate\(svg, `\$\{sourcePlate\?\.path \|\| ''\}\$\{snapPlate\?\.path \|\| ''\}`\)/);
  assert.match(connections, /activeInteractionRef\.current\.fromAnchor,\n\s+activeInteractionRef\.current\.sourcePlate\n/);
});
