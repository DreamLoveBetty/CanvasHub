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
  // A target to the left is never fed from the source's input side: the link turns to
  // the bottom (level partner) instead, and enters the target off its output side too.
  assert.equal(routes.get('e3').fromSide, 'bottom');
  assert.equal(routes.get('e3').toSide, 'bottom');
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

test('however the nodes move, inputs stay off the output side and never merge with output plates', () => {
  const P = loadPlates();
  // The screenshot case: an image group feeding a model sits up and to the right of it,
  // while the model also sends a result further right.
  const nodes = { model: box(0, 0, 720, 460), group: box(900, -700, 360, 600), result: box(1100, 300, 300, 200) };
  const edges = [{ id: 'ref', from: 'group', to: 'model' }, { id: 'out', from: 'model', to: 'result' }];
  const { routes, ports } = P.layout(edges, id => nodes[id]);
  assert.equal(routes.get('out').fromSide, 'right');
  assert.notEqual(routes.get('ref').toSide, 'right', 'the incoming reference does not join the output plate');
  assert.equal(routes.get('ref').toSide, 'top');
  assert.notEqual(routes.get('ref').fromSide, 'left');
  const r = ({ x, y, width, height }) => ({ x, y, w: width, h: height });
  assert.deepEqual([...P.portSides(r(nodes.group), r(nodes.model))], ['bottom', 'top']);
  assert.deepEqual([...P.facingSides(r(nodes.group), r(nodes.model))], ['left', 'right'], 'what plain facing would have picked');
  const plates = ports.get('model');
  assert.ok(plates.every(plate => plate.side !== 'right' || plate.incoming === 0));
  // Sweep the upstream node all around the model: no incoming end ever on the right, no
  // outgoing end ever on the left, for either node.
  for (let angle = 0; angle < 360; angle += 15) {
    const t = angle * Math.PI / 180;
    const moved = { ...nodes, group: box(180 + Math.cos(t) * 1200, -70 + Math.sin(t) * 900, 360, 600) };
    const laid = P.layout(edges, id => moved[id]).routes;
    laid.forEach(route => {
      assert.notEqual(route.toSide, 'right', `incoming on the output side at ${angle}°`);
      assert.notEqual(route.fromSide, 'left', `outgoing on the input side at ${angle}°`);
    });
  }
});

test('an input and an output on the same top or bottom side get separate plates on separate halves', () => {
  const P = loadPlates();
  // Both partners sit straight below the model: the input arrives on its bottom, the output leaves from it.
  const nodes = { model: box(0, 0, 720, 460), src: box(200, 900), dst: box(260, 900) };
  const { routes, ports } = P.layout([
    { id: 'in', from: 'src', to: 'model' },
    { id: 'out', from: 'model', to: 'dst' },
  ], id => nodes[id]);
  assert.equal(routes.get('in').toSide, 'bottom');
  assert.equal(routes.get('out').fromSide, 'bottom');
  const bottom = ports.get('model').filter(plate => plate.side === 'bottom');
  assert.equal(bottom.length, 2, 'two plates, not one merged plate');
  const [input, output] = [bottom.find(p => p.incoming), bottom.find(p => !p.incoming)];
  assert.ok(input.hit.x + input.hit.w <= output.hit.x, 'the input plate keeps to the left of the output plate');
  assert.ok(routes.get('in').to.x < 360 && routes.get('out').from.x > 360);
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

test('the hover plate travels round a corner without jumping and keeps its straight-side cross-section', () => {
  const P = loadPlates();
  const context = { window: {} };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-port-geometry.js'), context);
  const G = context.window.DesktopCanvasPortGeometry;
  const geometry = G.buildFloatingSwellPerimeter(300, 200, 14);
  const pointAt = s => G.floatingSwellPointAt(geometry, s).point;
  // Walk the whole outline in 1px steps: the face never moves further than the outline does
  // (plus the turn of the normal on a corner), and every corner is crossed on the way.
  let previous = P.perimeterPlate(pointAt, 0).face, longest = 0;
  for (let s = 1; s <= geometry.length; s += 1) {
    const face = P.perimeterPlate(pointAt, s).face;
    longest = Math.max(longest, Math.hypot(face.x - previous.x, face.y - previous.y));
    previous = face;
  }
  assert.ok(longest < 1 + P.PLATE.depth / 14 + 0.01, `face hopped ${longest.toFixed(2)}px in one 1px step`);
  // On a straight run it is the same plate edgePlate draws on that side.
  const side = 14 + 150;
  const located = pointAt(side);
  assert.equal(located.ny, -1);
  const straight = P.perimeterPlate(pointAt, side);
  assert.deepEqual({ ...straight.face }, { x: located.x, y: -P.PLATE.depth });
  const ys = [...straight.path.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map(m => Number(m[2]));
  assert.equal(Math.min(...ys), -P.PLATE.depth);
  assert.equal(Math.max(...ys), 3, 'the plate closes 3px inside the card');
  assert.equal(P.perimeterPlate(pointAt, 40, 0).path, '');
});

test('a travelling plate sinks into the card over the notch and comes back after it', () => {
  const P = loadPlates();
  const rect = { x: 0, y: 0, w: 720, h: 460 };
  const range = P.edgeRange(rect, 'right', P.NOTCH);
  assert.equal(P.notchFade(rect, null, 720, 450), 1);
  assert.equal(P.notchFade(rect, P.NOTCH, 720, range.max), 1, 'full height wherever edgeRange still allows a port');
  const half = P.notchFade(rect, P.NOTCH, 720, range.max + 8);
  assert.ok(half > 0 && half < 1);
  assert.equal(P.notchFade(rect, P.NOTCH, 720, range.max + 16), 0);
  assert.equal(P.notchFade(rect, P.NOTCH, 650, 460), 0, 'gone along the notched bottom too');
  assert.equal(P.notchFade(rect, P.NOTCH, 300, 460), 1);
});

test('graphite hover swell, drag preview and notch ring are wired through the injected plate module', () => {
  const ports = read('frontend/scripts/desktop-canvas-port-interaction.js');
  assert.match(ports, /portPlates\.perimeterPlate\(s => floatingSwellPointAt\(state\.geometry, s\)\.point, state\.position\.value, amount\)/);
  assert.match(ports, /portPlates\.notchFade\(/);
  assert.doesNotMatch(ports, /portPlates\.edgePlate\(/, 'the hover plate no longer parks at the side ends');
  assert.match(ports, /style === 'droplet' \|\| plate/);
  const connections = read('frontend/scripts/desktop-canvas-connections.js');
  assert.match(connections, /data-live-connection-plate/);
  assert.match(connections, /const destination = previewRoute\?\.to \|\| /, 'a snapped drag ends on its future port');
  assert.doesNotMatch(connections, /graphiteSnapPlate|snapPlate/, 'no separate plate at the pointer level any more');
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.equal(canvas.match(/portPlates: window\.DesktopCanvasPortPlates/g).length, 2);
  assert.match(canvas, /'desktop:theme-style-change', refreshFloatingSwellStyle/);
  const css = read('frontend/styles/desktop-graphite.css');
  // Notched nodes are borderless in graphite, so only the notch-shaped ring marks selection.
  assert.match(css, /\.desk-node--music-generate\) \{\n  --desk-node-border-width: 0px;/);
  assert.match(css, /\.desk-node-swell-border__paint \{\n  fill: var\(--desk-graphite-card\);/);
  assert.match(css, /\.desk-link-path:is\(\.is-preview, \.is-pending\) \{\n  stroke: var\(--desk-graphite-card\);\n  stroke-width: 8;/);
});

test('a snapped drag lands exactly where the made link will sit, making room on the shared plate', () => {
  const P = loadPlates();
  const nodes = { target: box(1200, 0, 720, 460), old: box(0, 700), dragged: box(0, -300), lone: box(0, 1400) };
  const geometryOf = id => nodes[id];
  const existing = [{ id: 'old', from: 'old', to: 'target' }];
  const before = P.layout(existing, geometryOf);
  const preview = P.layout([...existing, { id: 'p', from: 'dragged', to: 'target', toOnly: true }], geometryOf);
  const made = P.layout([...existing, { id: 'new', from: 'dragged', to: 'target' }], geometryOf);
  assert.deepEqual({ ...preview.routes.get('p').to }, { ...made.routes.get('new').to });
  assert.deepEqual({ ...preview.routes.get('old').to }, { ...made.routes.get('old').to }, 'the old port already made room');
  assert.notDeepEqual({ ...before.routes.get('old').to }, { ...preview.routes.get('old').to });
  assert.equal(Math.abs(preview.routes.get('p').to.y - preview.routes.get('old').to.y), P.PORT_GAP, 'one shared plate');
  // The dragged source grows nothing until the link is made (its swell is the source end).
  assert.equal(preview.ports.has('dragged'), false);
  assert.equal(made.ports.has('dragged'), true);
  // A level partner still pulls a lone preview port straight, as it will once made.
  const level = { target: box(1200, 0, 720, 460), side: box(0, 120) };
  const levelOf = id => level[id];
  assert.deepEqual(
    { ...P.layout([{ id: 'p', from: 'side', to: 'target', toOnly: true }], levelOf).routes.get('p').to },
    { ...P.layout([{ id: 'n', from: 'side', to: 'target' }], levelOf).routes.get('n').to });
});

test('a snapped drag joins the layout as a target-only preview link and gives the room back after', () => {
  const connections = read('frontend/scripts/desktop-canvas-connections.js');
  assert.match(connections, /\{ id: GRAPHITE_PREVIEW_EDGE_ID, \.\.\.graphitePreviewLink, toOnly: true \}/);
  assert.match(connections, /const previewRoute = syncGraphitePreviewLink\(preview\.fromNodeId, snap\);/);
  // Magnetic capture measures the input port's plate hit: it must not follow the preview,
  // or making room would carry the target away from the pointer and drop the snap.
  assert.match(connections, /if \(!graphitePreviewLink\) syncGraphitePortHits\(layout\.ports\);/);
  assert.equal(connections.match(/syncGraphitePortHits\(layout\.ports\)/g).length, 1);
  const clear = connections.slice(connections.indexOf('function clearLiveConnectionPreview'));
  assert.match(clear.slice(0, 1200), /graphitePreviewLink = null;\n\s+scheduleGraphiteRefresh\(\);/);
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
  assert.equal(P.notchOf(element('.desk-node--comfy')), P.NOTCH);
  assert.equal(P.notchOf(element('.desk-node--music-generate')), P.NOTCH);
  assert.equal(P.notchOf(element('.desk-node--music')), null, 'other music nodes have no generate key');
  assert.equal(P.notchOf(element('.desk-node--upscale')), null);
  assert.equal(P.notchOf(null), null);
  assert.ok(css.includes(
    ':is(.desk-node--input, .desk-node--krea2, .desk-node--moss, .desk-node--qwen21, .desk-node--music-generate) .desk-input-footer .desk-action-row {\n  right: -6px;\n  bottom: -6px;'
  ), 'music generate key uses the shared 14px-padding action-row notch offset');
  assert.ok(css.includes(
    ':is(.desk-node--topaz, .desk-node--pose, .desk-node--topaz-video, .desk-node--video-control, .desk-node--video-understand, .desk-node--easycolab-h3) .desk-generation-action {\n  translate: 8px 8px;'
  ), '16px-padding flow-footer keys keep the translate offset');
  assert.equal(css.includes('.desk-node--music-generate) .desk-generation-action {\n  translate: 8px 8px;'), false);
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
  assert.match(connections, /syncLiveConnectionPlate\(svg, sourcePlate\?\.path \|\| ''\)/);
  assert.match(connections, /activeInteractionRef\.current\.fromAnchor,\n\s+activeInteractionRef\.current\.sourcePlate\n/);
});

test('app chrome uses one graphite token set and flat, unfrosted panels in both themes', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  // Chrome tokens sit at (0,3,1) so they beat the liquid dark token blocks for either theme.
  const chrome = css.slice(css.indexOf('body.desk-app[data-desk-style="graphite"][data-theme] {'));
  assert.ok(chrome.length < css.length, 'chrome token block exists');
  const block = chrome.slice(0, chrome.indexOf('\n}\n'));
  [
    '--desk-settings-panel-background',
    '--desk-canvas-zoom-background',
    '--desk-canvas-palette-background',
    '--desk-canvas-menu-background',
    '--desk-canvas-edge-menu-background',
    '--desk-release-panel-background',
    '--desk-status-tip-background',
    '--desk-shell-titlebar-band-display',
  ].forEach(token => assert.match(block, new RegExp(`${token}:`), `${token} is mapped for the chrome`));
  assert.doesNotMatch(block, /rgba?\(|#[0-9a-f]{3,6}\b/i, 'chrome tokens only reference the graphite palette');
  // The sheet shares the canvas colour; dark loses its shadow, so a hairline frames it.
  assert.match(block, /--desk-settings-panel-border: var\(--desk-graphite-line\);/);

  // Liquid dark paints the side panels and menus directly at (0,3,1); graphite restates them.
  assert.match(css, /:is\(\.desk-rail, \.desk-node-palette:not\(\.desk-node-context-menu\), \.desk-history:not\(\.is-collapsed\), \.desk-zoom-controls\) \{[^}]*backdrop-filter: none;/);
  assert.match(css, /\[data-theme\] \.desk-node-context-menu \{[^}]*box-shadow: var\(--desk-canvas-menu-shadow\);/);
  assert.match(css, /\[data-theme\] \.desk-node-context-menu__cap strong \{\n  color: var\(--desk-canvas-menu-cap-ink\);/);
  assert.match(css, /\[data-theme\] \.desk-history-item\.is-selected \{[^}]*border-color: var\(--desk-graphite-accent\);/);
  assert.match(css, /:is\(\.desk-status-chip, \.desk-status-stop, \.desk-release__trigger, \.desk-settings--workbench\) \{[^}]*backdrop-filter: none;/);
});

test('graphite swaps the default Ambient coral for its accent but keeps a custom accent', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  // Beats the upstream `--amb-highlight-color: coral` on #deskApp[data-control-material="ambient"];
  // a custom accent is written inline on <body> and so still wins.
  assert.match(css, /#deskApp\[data-control-material="ambient"\]\[data-desk-style="graphite"\] \{\n  --amb-highlight-color: var\(--desk-graphite-accent\);/);
  assert.match(css, /\[data-desk-style="graphite"\]\[data-theme="dark"\] :is\(\.desk-node, \.desk-settings\) :is\(\.desk-switch > span, input\[type="checkbox"\]:not\(\.desk-switch > input\)\)::after \{\n  --amb-albedo: var\(--desk-graphite-ink-2\);/);
  assert.match(css, /\.desk-select-option\.is-selected:not\(:disabled\) \{\n  --desk-select-led: var\(--desk-graphite-accent\);/);
  const material = read('frontend/scripts/desktop-control-material.js');
  assert.match(material, /if \(prefs\.accent\) body\.style\.setProperty\('--amb-highlight-color', prefs\.accent\);/);
});

test('asset library, prompt library and prompt assistant share a second graphite token block', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  const head = 'body.desk-app[data-desk-style="graphite"][data-theme] {';
  const first = css.indexOf(head);
  const second = css.indexOf(head, first + head.length);
  assert.ok(second > first, 'phase 4 token block follows the chrome block');
  const block = css.slice(second, css.indexOf('\n}\n', second));
  [
    '--desk-gallery-panel-background',
    '--desk-gallery-card-surface-paint',
    '--desk-prompt-assistant-panel-background',
    '--desk-prompt-assistant-field-focus-border',
    '--desk-agent-switch-background',
    '--desk-agent-workbench-background',
    '--desk-agent-task-draft-background',
    '--desk-agent-task-drawer-background',
  ].forEach(token => assert.match(block, new RegExp(`${token}:`), `${token} is mapped`));
  assert.doesNotMatch(block, /rgba?\(|#[0-9a-f]{3,6}\b/i, 'phase 4 tokens only reference the graphite palette');
  // Semantic status colours and Pinterest brand red keep their upstream values.
  [
    '--desk-agent-task-failed-',
    '--desk-agent-waiting-',
    '--desk-agent-running-',
    '--desk-agent-failure-',
    '--desk-agent-danger-',
    '--desk-agent-task-draft-dot',
    '--desk-gallery-pinterest-brand-',
  ].forEach(prefix => assert.ok(!block.includes(`${prefix}`), `${prefix} is left to upstream`));
});

test('graphite restates the liquid-painted gallery keys, prompt library and drawer glass', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  // Gallery keys sit on #deskApp so they beat liquid's ID selectors; delete uses the model red.
  assert.match(css, /#deskApp\[data-desk-style="graphite"\] :is\(\n  #deskGalleryDeleteBtn,[^{]*\) \{\n  color: var\(--desk-graphite-model\);/);
  assert.match(css, /#deskApp\[data-desk-style="graphite"\] :is\(\n  #deskGallerySaveSetBtn,[^{]*\) \{\n  color: var\(--desk-graphite-accent\);/);
  // Prompt library rules sit one attribute above liquid's (0,3,1) light and dark blocks.
  const P = 'body\\.desk-app\\[data-desk-style="graphite"\\]\\[data-theme\\]';
  assert.match(css, new RegExp(`${P} \\.desk-prompt-library__nav button\\.is-active \\{[^}]*background: var\\(--desk-graphite-card\\);`));
  assert.match(css, new RegExp(`${P} \\.desk-prompt-library \\{[^}]*backdrop-filter: none;`));
  // Editor fields sit inset on the card editor so they stay visible.
  assert.match(css, /\.desk-prompt-inspiration-preview pre\n\) \{\n  background: var\(--desk-graphite-inset\);/);
  assert.match(css, new RegExp(`${P} :is\\(\\n  \\.desk-prompt-drawer__body,\\n  \\.desk-prompt-drawer\\.is-open \\.desk-prompt-drawer__body\\n\\) \\{\\n  -webkit-backdrop-filter: none;\\n  backdrop-filter: none;`));
  assert.ok(!/!important/.test(css), 'graphite never needs !important');
});

function hexLuminance(hex) {
  const channel = value => {
    const v = parseInt(value, 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const h = hex.replace('#', '');
  return 0.2126 * channel(h.slice(0, 2)) + 0.7152 * channel(h.slice(2, 4)) + 0.0722 * channel(h.slice(4, 6));
}
function contrast(a, b) {
  const [x, y] = [hexLuminance(a), hexLuminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function graphiteTokens(css, dark) {
  const head = dark
    ? 'body.desk-app[data-desk-style="graphite"][data-theme="dark"] {'
    : 'body.desk-app[data-desk-style="graphite"] {';
  const start = css.indexOf(head);
  const block = css.slice(start, css.indexOf('\n}', start));
  return Object.fromEntries([...block.matchAll(/--desk-graphite-([\w-]+): (#[0-9a-f]{6});/g)].map(m => [m[1], m[2]]));
}

test('graphite secondary text stays readable on its card and inset surfaces; faint is kept for disabled', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  for (const dark of [false, true]) {
    const t = graphiteTokens(css, dark);
    // Meta labels are 10-11px: at least 4:1 on the card and 3.9:1 on the inset well.
    assert.ok(contrast(t.muted, t.card) >= 4.5, `muted on card (${dark ? 'dark' : 'light'})`);
    assert.ok(contrast(t.muted, t.inset) >= 3.9, `muted on inset (${dark ? 'dark' : 'light'})`);
    assert.ok(contrast(t['accent-ink'], t.card) >= 4.5, `status ok ink on card (${dark ? 'dark' : 'light'})`);
    // Disabled and placeholder ink stays a step quieter than muted.
    assert.ok(contrast(t.faint, t.card) < contrast(t.muted, t.card), 'faint is quieter than muted');
  }
  for (const token of ['--desk-color-text-placeholder', '--desk-color-text-disabled', '--desk-action-primary-disabled-ink', '--desk-node-manual-send-disabled-ink']) {
    assert.match(css, new RegExp(`${token}: var\\(--desk-graphite-faint\\);`));
  }
  assert.match(css, /--desk-status-ok-ink: var\(--desk-graphite-accent-ink\);/);
});

test('the model badge paints from tokens, and graphite restates them in its accent', () => {
  const liquid = read('frontend/styles/desktop-liquid.css');
  const rule = liquid.match(/\.desk-gpt-model-caption small \{[^}]*\}/)[0];
  assert.match(rule, /color: var\(--desk-model-badge-ink\);/);
  assert.match(rule, /background: var\(--desk-model-badge-background\);/);
  assert.ok(!/#[0-9a-f]{3,6}|rgba\(/i.test(rule), 'no literal colours in the badge rule');
  assert.ok(!/data-theme="dark"\] \.desk-gpt-model-caption small/.test(liquid), 'dark set lives in the tokens');
  const tokens = read('frontend/styles/desktop-tokens.css');
  assert.equal((tokens.match(/--desk-model-badge-ink: /g) || []).length, 2, 'light and dark token sets');
  assert.match(read('frontend/styles/desktop-graphite.css'), /--desk-model-badge-ink: var\(--desk-graphite-accent-ink\);/);
});

test('graphite gives the gallery audio cards neutral surfaces and the teal accent', () => {
  const css = read('frontend/styles/desktop-graphite.css');
  const light = css.match(/body\.desk-app\[data-desk-style="graphite"\] \.desk-gallery-audio \{[^}]*\}/)[0];
  const dark = css.match(/body\.desk-app\[data-desk-style="graphite"\]\[data-theme="dark"\] \.desk-gallery-audio \{[^}]*\}/)[0];
  assert.match(light, /--desk-gallery-audio-surface: var\(--desk-graphite-card\);/);
  assert.match(light, /--desk-gallery-audio-accent: var\(--desk-graphite-accent\);/);
  assert.match(dark, /--desk-gallery-audio-on-accent: #[0-9a-f]{6};/);
  // The play key's shading follows the accent instead of a literal orange-brown.
  const audio = read('frontend/styles/desktop-gallery-audio.css');
  assert.ok(!/rgba\(120, 32, 0/.test(audio));
  assert.match(audio, /--desk-gallery-audio-accent-shade: #782000;/);
});
