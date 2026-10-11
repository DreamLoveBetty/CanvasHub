// Portable viewport regressions: synthetic DOM/state, no storage, browser or services.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, 'frontend', name), 'utf8');
const host = read('scripts/desktop-canvas.js');
const constants = {
  WORLD_WIDTH: 1440, WORLD_HEIGHT: 820,
  MIN_SCALE: Number(host.match(/const MIN_SCALE = ([\d.]+);/)[1]),
  MAX_SCALE: Number(host.match(/const MAX_SCALE = ([\d.]+);/)[1]),
  ZOOM_PRESETS: JSON.parse(host.match(/const ZOOM_PRESETS = (\[[^;]+\]);/)[1]),
  DEFAULT_CANVAS_SCALE: 0.75, CANVAS_WHEEL_GESTURE_END_MS: 160,
  CANVAS_COMPACT_ZOOM_THRESHOLD: 0.72, CANVAS_OVERVIEW_ZOOM_THRESHOLD: 0.5,
  IS_MAC_PLATFORM: true
};
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} != ${expected}`);
function element() {
  const classes = new Set();
  return { style: { setProperty(key, value) { this[key] = value; }, getPropertyValue(key) { return this[key] || ''; } },
    dataset: {}, attrs: {}, hidden: true,
    classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
      toggle(x, on) { if (on) classes.add(x); else classes.delete(x); } },
    setAttribute(key, value) { this.attrs[key] = value; }
  };
}
function fixture({ scale = 0.75, origin = { x: 0, y: 0 } } = {}) {
  let canvas = { x: 70, y: 45, scale, selectedNodeIds: ['a'], selectedNodeId: 'a',
    nodes: { a: { id: 'a', type: 'input', x: -900, y: -700, width: 300, height: 200 },
      b: { id: 'b', type: 'image', x: 3500, y: 2400, width: 400, height: 250 } },
    edges: [{ id: 'a-b', from: 'a', to: 'b' }] };
  const frames = new Map(), timers = new Map(), captured = new Set(), events = [];
  let sequence = 0, saves = 0, focuses = 0;
  const els = Object.fromEntries(['deskCanvasViewport', 'deskCanvasWorld', 'deskZoomLabel', 'deskZoomPresetMenu',
    'deskMiniMap', 'deskMiniMapWorld', 'deskMiniMapViewport', 'deskMiniMapPinBtn'].map(name => [name, element()]));
  const viewportRect = { left: 25, top: 36, width: 1200, height: 800 };
  els.deskCanvasViewport.getBoundingClientRect = () => viewportRect;
  Object.assign(els.deskCanvasWorld, { offsetParent: els.deskCanvasViewport, offsetLeft: origin.x, offsetTop: origin.y });
  els.deskCanvasWorld.getBoundingClientRect = () => {
    const transform = els.deskCanvasWorld.style.transform?.match(/translate3d\(([-\d.]+)px, ([-\d.]+)px/);
    return { left: viewportRect.left + origin.x + Number(transform?.[1] || 0) - (els.deskCanvasViewport.scrollLeft || 0),
      top: viewportRect.top + origin.y + Number(transform?.[2] || 0) - (els.deskCanvasViewport.scrollTop || 0) };
  };
  const map = els.deskMiniMap;
  Object.assign(map, { clientWidth: 198, clientHeight: 90, offsetWidth: 200, offsetHeight: 92, clientLeft: 1, clientTop: 1 });
  map.getBoundingClientRect = () => ({ left: 1100, top: 870, width: 200, height: 92 });
  map.setPointerCapture = id => captured.add(id);
  map.hasPointerCapture = id => captured.has(id);
  map.releasePointerCapture = id => captured.delete(id);
  const controls = element();
  controls.querySelector = () => ({ getBoundingClientRect: () => ({ height: 28 }) });
  els.deskMiniMapPinBtn.closest = () => controls;
  const buttons = constants.ZOOM_PRESETS.map(preset => { const button = element(); button.dataset.zoomPreset = String(preset); return button; });
  els.deskZoomPresetMenu.querySelectorAll = () => buttons;
  const context = vm.createContext({ window: { setTimeout: fn => { timers.set(++sequence, fn); return sequence; },
    getComputedStyle: () => ({ getPropertyValue: () => '' }), dispatchEvent: event => events.push(event) },
    setTimeout: fn => { timers.set(++sequence, fn); return sequence; }, clearTimeout: id => timers.delete(id),
    requestAnimationFrame: fn => { frames.set(++sequence, fn); return sequence; }, cancelAnimationFrame: id => frames.delete(id),
    CustomEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } }
  });
  vm.runInContext(read('scripts/desktop-canvas-viewport.js'), context);
  const bounds = node => ({ x: node.x, y: node.y, width: node.width, height: node.height });
  const api = context.window.DesktopCanvasViewport.create({ getCanvas: () => canvas, els, constants,
    clamp: (value, min, max) => Math.max(min, Math.min(max, value)), getSelectedNodeIds: () => canvas.selectedNodeIds,
    getNodeBounds: bounds, getNodeBoundsById: id => bounds(canvas.nodes[id]), getBoundsFromRects: rects => rects[0],
    updateSelectionToolbar() {}, positionEdgeMenu() {}, updateInputProgressOverlay() {},
    focusCanvasViewport: () => focuses++, saveSettings: () => saves++ });
  const flush = () => { for (const [id, callback] of [...frames]) { frames.delete(id); callback(); } };
  const pointer = (x = 80, y = 30, extra = {}) => ({ button: 0, isPrimary: true, pointerId: 7,
    clientX: 1101 + x, clientY: 871 + y, preventDefault() { this.prevented = true; }, stopPropagation() {}, ...extra });
  const worldAt = (x, y) => {
    // Invert the actual rendered view frame instead of repeating the projection algorithm.
    const view = els.deskMiniMapViewport.style;
    const mapScale = parseFloat(view.width) / (viewportRect.width / canvas.scale);
    return { x: (-origin.x - canvas.x + (els.deskCanvasViewport.scrollLeft || 0)) / canvas.scale + (x - parseFloat(view.left)) / mapScale,
      y: (-origin.y - canvas.y + (els.deskCanvasViewport.scrollTop || 0)) / canvas.scale + (y - parseFloat(view.top)) / mapScale };
  };
  const center = () => ({ x: (viewportRect.width / 2 - origin.x - canvas.x + (els.deskCanvasViewport.scrollLeft || 0)) / canvas.scale,
    y: (viewportRect.height / 2 - origin.y - canvas.y + (els.deskCanvasViewport.scrollTop || 0)) / canvas.scale });
  api.applyCanvasTransform();
  return { api, els, map, controls, buttons, frames, timers, captured, events, pointer, flush, worldAt, center,
    get canvas() { return canvas; }, replace(value) { canvas = value; },
    get saves() { return saves; }, get focuses() { return focuses; } };
}

test('all zoom entry points share a 10% floor and keep the anchor stable', () => {
  const h = fixture(), anchor = h.api.screenToWorld(340, 260);
  h.api.setCanvasScale(0.01, 340, 260);
  assert.equal(h.canvas.scale, 0.1);
  const after = h.api.screenToWorld(340, 260); near(after.x, anchor.x); near(after.y, anchor.y);
  assert.equal(h.els.deskZoomLabel.textContent, '10%');
  assert.equal(h.els.deskCanvasWorld.dataset.zoomTier, 'overview');
  h.api.setCanvasScale(999); assert.equal(h.canvas.scale, 1.8);
  for (const preset of [0.1, 0.2, 0.3, 0.5, 0.75]) {
    h.api.applyZoomPreset(preset); assert.equal(h.canvas.scale, preset);
    assert.equal(h.buttons.find(button => Number(button.dataset.zoomPreset) === preset).attrs['aria-checked'], 'true');
  }
  h.api.resetCanvasView(); assert.equal(h.canvas.scale, 0.75);
});

for (const scale of [0.1, 0.3, 0.75, 1.8]) {
  test(`clicking a letterboxed minimap centers the world point at ${scale * 100}% without changing the graph`, () => {
    const h = fixture({ scale }), graph = JSON.stringify([h.canvas.nodes, h.canvas.edges, h.canvas.selectedNodeIds]);
    const point = h.worldAt(45, 65), event = h.pointer(45, 65);
    assert.equal(h.api.beginMiniMapNavigation(event), true); assert.equal(event.prevented, true);
    h.api.endMiniMapNavigation(h.pointer(45, 65, { type: 'pointerup' }));
    near(h.center().x, point.x); near(h.center().y, point.y);
    assert.equal(h.canvas.scale, scale); assert.equal(h.saves, 1); assert.equal(h.focuses, 1);
    assert.equal(JSON.stringify([h.canvas.nodes, h.canvas.edges, h.canvas.selectedNodeIds]), graph);
    assert.equal(h.captured.size, 0); assert.equal(h.frames.size, 0);
  });
}

test('minimap projection includes a nonzero world origin, negative nodes and CSS-scaled map borders', () => {
  const h = fixture({ origin: { x: 8, y: 12 } }), point = h.worldAt(15, 12);
  h.map.getBoundingClientRect = () => ({ left: 1100, top: 870, width: 400, height: 184 });
  h.api.beginMiniMapNavigation(h.pointer(15, 12, { clientX: 1100 + 16 * 2, clientY: 870 + 13 * 2 }));
  h.api.endMiniMapNavigation(); near(h.center().x, point.x); near(h.center().y, point.y);
});

test('a click uses the visible projection rather than silently reprojecting during map expansion', () => {
  const h = fixture(), point = h.worldAt(50, 30);
  h.map.clientHeight = 60; h.map.offsetHeight = 62;
  h.map.getBoundingClientRect = () => ({ left: 1100, top: 870, width: 200, height: 62 });
  h.api.beginMiniMapNavigation(h.pointer(50, 30)); h.api.endMiniMapNavigation();
  near(h.center().x, point.x); near(h.center().y, point.y);
});

test('transitional DOM bounds do not shift the layout origin or miscenter a minimap node', () => {
  const h = fixture({ scale: 0.1 });
  // A queued pan frame can still expose an older transform than live state.
  h.els.deskCanvasWorld.getBoundingClientRect = () => ({ left: 5025, top: 4036 });
  h.api.applyCanvasTransform();
  const first = h.els.deskMiniMapWorld.innerHTML.match(/left:([\d.-]+)px;top:([\d.-]+)px/);
  h.api.beginMiniMapNavigation(h.pointer(Number(first[1]), Number(first[2])));
  h.api.endMiniMapNavigation();
  near(h.center().x, h.canvas.nodes.a.x); near(h.center().y, h.canvas.nodes.a.y);
});

test('layout origin accounts for a preexisting native scroll offset', () => {
  const h = fixture(); h.els.deskCanvasViewport.scrollLeft = 162; h.els.deskCanvasViewport.scrollTop = 101;
  h.api.applyCanvasTransform();
  const point = h.worldAt(60, 45); h.api.beginMiniMapNavigation(h.pointer(60, 45)); h.api.endMiniMapNavigation();
  near(h.center().x, point.x); near(h.center().y, point.y);
});

test('map expansion finishes with real dimensions and rapid pin toggles dispatch only the current layout', () => {
  const h = fixture(); h.map.clientHeight = 0; h.api.setMiniMapPinned(true);
  const before = h.els.deskMiniMapWorld.innerHTML;
  h.map.clientHeight = 70;
  for (const [id, callback] of [...h.timers]) { h.timers.delete(id); callback(); }
  assert.notEqual(h.els.deskMiniMapWorld.innerHTML, before);
  h.api.setMiniMapPinned(false); h.api.setMiniMapPinned(true); h.api.setMiniMapPinned(false);
  const count = h.events.length;
  for (const callback of h.timers.values()) callback();
  assert.ok(h.events.slice(count).every(event => event.detail.pinned === false));
});

test('dragging keeps the original map projection even when moving beyond the old visible bounds', () => {
  const h = fixture(), first = h.worldAt(20, 15), last = h.worldAt(198, 90);
  const nodes = h.els.deskMiniMapWorld.innerHTML;
  h.api.beginMiniMapNavigation(h.pointer(20, 15)); near(h.center().x, first.x);
  assert.equal(h.captured.has(7), true);
  h.api.moveMiniMapNavigation(h.pointer(150, 70)); h.api.moveMiniMapNavigation(h.pointer(180, 80));
  assert.equal(h.frames.size, 1); h.flush();
  assert.equal(h.els.deskMiniMapWorld.innerHTML, nodes);
  h.api.moveMiniMapNavigation(h.pointer(1000, 400)); h.flush();
  near(h.center().x, last.x); near(h.center().y, last.y);
  assert.equal(h.saves, 0);
  h.api.endMiniMapNavigation(h.pointer(1000, 400, { type: 'pointerup' }));
  assert.equal(h.saves, 1); assert.equal(h.map.classList.contains('is-navigating'), false);
  h.api.endMiniMapNavigation(); assert.equal(h.saves, 1);
});

test('right click, secondary touch, hidden maps and nonfinite positions do not navigate', () => {
  const h = fixture(), before = JSON.stringify(h.canvas);
  for (const extra of [{ button: 2 }, { isPrimary: false }, { clientX: NaN }, { clientY: Infinity }]) {
    assert.equal(h.api.beginMiniMapNavigation(h.pointer(30, 30, extra)), false);
  }
  h.map.clientHeight = 0;
  assert.equal(h.api.beginMiniMapNavigation(h.pointer()), false);
  assert.equal(JSON.stringify(h.canvas), before); assert.equal(h.saves, 0);
});

test('other pointers cannot hijack or end the active navigation', () => {
  const h = fixture(); h.api.beginMiniMapNavigation(h.pointer()); const before = JSON.stringify(h.canvas);
  assert.equal(h.api.moveMiniMapNavigation(h.pointer(30, 15, { pointerId: 8 })), false);
  assert.equal(h.api.endMiniMapNavigation(h.pointer(30, 15, { pointerId: 8 })), false);
  assert.equal(JSON.stringify(h.canvas), before); assert.equal(h.captured.has(7), true);
  h.api.endMiniMapNavigation(); assert.equal(h.saves, 1);
});

test('Escape ends the active map gesture and subsequent pointer moves do not move the view', () => {
  const h = fixture(); h.api.beginMiniMapNavigation(h.pointer());
  const key = { key: 'Escape', preventDefault() { this.prevented = true; }, stopPropagation() {} };
  h.api.handleMiniMapKeydown(key);
  assert.equal(key.prevented, true); assert.equal(h.captured.size, 0); assert.equal(h.saves, 1);
  const before = JSON.stringify(h.canvas);
  assert.equal(h.api.moveMiniMapNavigation(h.pointer(120, 70)), false);
  assert.equal(JSON.stringify(h.canvas), before);
});

for (const reason of ['pointercancel', 'lostpointercapture', 'blur', 'collapse']) {
  test(`navigation releases capture and pending frames on ${reason}`, () => {
    const h = fixture(); h.api.beginMiniMapNavigation(h.pointer()); h.api.moveMiniMapNavigation(h.pointer(100, 60));
    if (reason === 'collapse') h.api.setMiniMapPinned(false);
    else h.api.endMiniMapNavigation(reason === 'blur' ? null : h.pointer(0, 0, { type: reason }));
    assert.equal(h.frames.size, 0); assert.equal(h.captured.size, 0);
    assert.equal(h.saves, 1); assert.equal(h.map.classList.contains('is-navigating'), false);
  });
}

test('replacing a workflow during navigation never changes or saves either graph from a stale pointer', () => {
  const h = fixture(); h.api.beginMiniMapNavigation(h.pointer()); h.api.moveMiniMapNavigation(h.pointer(100, 60));
  const old = JSON.stringify(h.canvas), replacement = { ...h.canvas, x: -88, y: -99, scale: 0.1, nodes: {}, edges: [] };
  h.replace(replacement); const before = JSON.stringify(replacement); h.flush();
  assert.equal(h.api.moveMiniMapNavigation(h.pointer(20, 20)), false);
  assert.equal(JSON.stringify(replacement), before); assert.equal(old.includes('3500'), true);
  assert.equal(h.captured.size, 0); assert.equal(h.saves, 0);
  assert.equal(h.els.deskZoomLabel.textContent, '10%');
  h.api.beginMiniMapNavigation(h.pointer(30, 30)); h.api.endMiniMapNavigation(); assert.equal(h.saves, 1);
});

test('zoom cancels navigation and finishes a wheel gesture before a new map click', () => {
  const h = fixture(); h.api.beginMiniMapNavigation(h.pointer()); h.api.setCanvasScale(0.1);
  assert.equal(h.captured.size, 0); assert.equal(h.map.classList.contains('is-navigating'), false);
  h.api.handleCanvasWheel({ target: { closest: () => false }, ctrlKey: true, deltaY: -200, clientX: 300, clientY: 200, preventDefault() {} });
  assert.equal(h.api.isWheelGestureActive(), true);
  h.api.beginMiniMapNavigation(h.pointer(40, 40)); assert.equal(h.api.isWheelGestureActive(), false);
  assert.equal(h.timers.size, 0); h.api.endMiniMapNavigation();
});

test('keyboard navigation pans by visible distance and collapsed maps are excluded from focus', () => {
  const h = fixture(); h.api.setMiniMapPinned(true); assert.equal(h.map.attrs.tabindex, '0');
  assert.equal(h.map.attrs['aria-hidden'], 'false');
  const before = { x: h.canvas.x, y: h.canvas.y };
  const key = key => ({ key, preventDefault() { this.prevented = true; }, stopPropagation() {} });
  const right = key('ArrowRight'); h.api.handleMiniMapKeydown(right); assert.equal(right.prevented, true);
  near(h.canvas.x, before.x - 120); near(h.canvas.y, before.y);
  h.api.handleMiniMapKeydown({ ...key('ArrowUp'), shiftKey: true }); near(h.canvas.y, before.y + 400);
  h.api.handleMiniMapKeydown(key('z')); assert.equal(h.saves, 2);
  h.api.setMiniMapPinned(false); assert.equal(h.map.attrs.tabindex, '-1'); assert.equal(h.map.attrs['aria-hidden'], 'true');
});

test('workflow import uses the same floor and preserves a 10% saved view', () => {
  const context = vm.createContext({ window: {} });
  vm.runInContext(read('scripts/desktop-canvas-workflow.js'), context);
  const api = context.window.DesktopCanvasWorkflow.create({ ...constants, DEFAULT_INPUT_NODE_WIDTH: 720, DEFAULT_INPUT_NODE_HEIGHT: 460,
    clamp: (value, min, max) => Math.max(min, Math.min(max, value)), normalizeNodeGroups() {}, expandNodeIdsToGroups: ids => ids });
  for (const [scale, expected] of [[0.1, 0.1], [0.2, 0.2], [0.01, 0.1], [2, 1.8]]) {
    const loaded = api.normalizeWorkflowCanvas({ x: -123, y: -456, scale });
    assert.equal(loaded.scale, expected); assert.equal(loaded.x, -123); assert.equal(loaded.y, -456);
  }
});

test('served HTML wires the existing controller, includes the new presets and busts all changed assets', () => {
  const html = read('desktop.html');
  for (const [scale, text] of [['0.1', '10%'], ['0.2', '20%'], ['0.3', '30%'], ['0.5', '50%'], ['0.75', '75%']]) {
    assert.ok(new RegExp(`data-zoom-preset="${scale.replace('.', '\\.')}"[^>]*>${text}`).test(html), text);
  }
  for (const asset of ['scripts/desktop-canvas.js', 'scripts/desktop-canvas-viewport.js',
    'scripts/desktop-canvas-image-group-interaction.js', 'scripts/desktop-i18n.js', 'styles/desktop-canvas-nodes.css', 'styles/desktop-geometry.css']) {
    const version = asset === 'styles/desktop-geometry.css' ? '20261010-color-bloom1'
      : asset === 'styles/desktop-canvas-nodes.css' ? '20261007-connection-arc1'
      : asset === 'scripts/desktop-canvas.js' ? '20261010-marquee-frame1'
      : asset === 'scripts/desktop-canvas-viewport.js'
      ? '20261009-zoom-style-cost1'
      : ['scripts/desktop-i18n.js', 'styles/desktop-canvas-nodes.css'].includes(asset)
        ? '20261006-node-palette-groups1' : '20261005-minimap-navigation2';
    assert.ok(html.includes(`${asset}?v=${version}`), asset);
  }
  for (const handler of ['beginMiniMapNavigation', 'moveMiniMapNavigation', 'endMiniMapNavigation', 'handleMiniMapKeydown']) {
    assert.ok(host.includes(`canvasViewport.${handler}`), handler);
  }
  assert.ok(read('styles/desktop-canvas-nodes.css').includes('touch-action: none;'));
  assert.match(read('styles/desktop-canvas-nodes.css'), /\.desk-canvas\s*\{[^}]*overflow: clip;/);
  assert.match(read('styles/desktop-geometry.css'), /\.desk-zoom-controls:has\(\.desk-zoom-presets:not\(\[hidden\]\)\)\s*\{\s*z-index: var\(--desk-layer-chrome\);/);
  assert.match(read('scripts/desktop-canvas-image-group-interaction.js'), /const canvasScale = Math\.max\(0\.01, Number\(DesktopState\.state\.canvas\.scale\) \|\| 1\);/);
  assert.doesNotMatch(read('scripts/desktop-canvas-image-group-interaction.js'), /Math\.max\(0\.3, Number\(DesktopState\.state\.canvas\.scale\)/);
});

// Inheritance is a browser/CSS behavior, not simulated by the DOM fixture above.
// Guard its declaration here; served-page traces cover style invalidation cost.
for (const [name, initial] of [['x', '0px'], ['y', '0px'], ['size', '20px']]) {
  test(`camera grid ${name} is a typed, non-inherited viewport property`, () => {
    const css = read('styles/desktop-performance.css');
    const declarations = [...css.matchAll(new RegExp(`@property --canvas-grid-${name}\\s*\\{([^}]+)\\}`, 'g'))];
    assert.equal(declarations.length, 1, 'register the runtime property exactly once');
    const declaration = declarations[0][1];
    assert.match(declaration, /syntax:\s*["']<length>["']\s*;/);
    assert.match(declaration, /inherits:\s*false\s*;/);
    assert.match(declaration, new RegExp(`initial-value:\\s*${initial}\\s*;`));
  });
}

for (const scale of [0.1, 0.3, 0.75, 1.8]) {
  test(`pan keeps grid phase aligned at ${scale * 100}% without rebuilding minimap nodes`, () => {
    const h = fixture({ scale });
    const graph = JSON.stringify([h.canvas.nodes, h.canvas.edges]);
    const miniMap = h.els.deskMiniMapWorld.innerHTML;
    h.canvas.x = -81.125; h.canvas.y = -39.875;
    h.api.scheduleCanvasPanTransform(); h.api.scheduleCanvasPanTransform();
    assert.equal(h.frames.size, 1); h.flush();
    const style = h.els.deskCanvasViewport.style, size = 20 * scale;
    near(parseFloat(style['--canvas-grid-size']), size);
    near(parseFloat(style['--canvas-grid-x']), ((h.canvas.x % size) + size) % size);
    near(parseFloat(style['--canvas-grid-y']), ((h.canvas.y % size) + size) % size);
    assert.equal(h.els.deskCanvasWorld.style.transform, `translate3d(-81.125px, -39.875px, 0) scale(${scale})`);
    assert.equal(h.els.deskMiniMapWorld.innerHTML, miniMap);
    assert.equal(JSON.stringify([h.canvas.nodes, h.canvas.edges]), graph);
    assert.equal(h.saves, 0);
  });
}

test('desktop loads the cache-busted non-inherited grid contract', () => {
  assert.ok(read('desktop.html').includes('styles/desktop-performance.css?v=20261006-canvas-grid-isolation1'));
});
