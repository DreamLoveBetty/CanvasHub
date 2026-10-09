// Synthetic DOM/events only; actual browser gesture checks live under tests/local.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = file => fs.readFileSync(path.join(__dirname, '../frontend', file), 'utf8');
const host = read('scripts/desktop-canvas.js');

function fixture() {
  let now = 1000, focuses = 0, saves = 0;
  const dismissed = [];
  const oldControl = { id: 'previous-control' };
  const document = { activeElement: oldControl };
  const viewport = { classList: { add() {}, remove() {} }, setPointerCapture() {}, releasePointerCapture() {},
    focus(options) { assert.equal(options.preventScroll, true); focuses++; document.activeElement = viewport; } };
  const canvas = { x: 30, y: 50, scale: 1 };
  const context = vm.createContext({ window: {}, document, Date: { now: () => now } });
  vm.runInContext(read('scripts/desktop-canvas-viewport.js'), context);
  const api = context.window.DesktopCanvasViewport.create({ getCanvas: () => canvas,
    els: { deskCanvasViewport: viewport }, constants: {}, focusCanvasViewport: () => viewport.focus({ preventScroll: true }) });
  Object.assign(context, { els: { deskCanvasViewport: viewport }, canvasViewport: api,
    DesktopState: { state: { canvas }, saveSettings() { saves++; } }, activeInteraction: null,
    CANVAS_INTERACTION_BLOCK_SELECTOR: 'left-block', CANVAS_RIGHT_PAN_BLOCK_SELECTOR: 'right-block',
    CANVAS_RIGHT_PAN_CONTROL_SELECTOR: 'control', CANVAS_CONTEXTMENU_SUPPRESS_MS: 450,
    focusCanvasViewport: () => viewport.focus({ preventScroll: true }), hideContextMenu() {}, clearSelectedEdge() {},
    setZoomPresetMenuOpen: open => dismissed.push(['zoom', open]), setWorkflowDockOpen: open => dismissed.push(['workflow', open]),
    isSelectToolActive: () => false, selectNode() {}, hideSmartGuides() {}, flushCanvasPanTransform() {},
    screenToWorld: (x, y) => ({ x, y }), setSelectedNodes() {}, renderMarquee() {},
    getNodeElement: () => null, clearImageGroupProximity() {}, openContextMenu() {},
    canvasCollision: {}, suppressCanvasContextMenuUntil: 0 });
  for (const name of ['startPan', 'startRightMousePanFallback', 'endInteraction']) {
    const start = host.indexOf(`  function ${name}(`);
    const end = host.indexOf('\n  function ', start + 1);
    vm.runInContext(host.slice(start, end), context);
  }
  const pointer = (extra = {}) => ({ type: 'pointerdown', button: 0, pointerId: 7, clientX: 100, clientY: 150,
    target: { closest: () => null }, preventDefault() { this.prevented = true; }, stopPropagation() {}, ...extra });
  const click = (extra = {}) => ({ type: 'click', button: 0, pointerId: 7, detail: 1,
    preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; }, ...extra });
  const start = extra => context.startPan(pointer(extra));
  const end = extra => context.endInteraction(pointer({ type: 'pointerup', ...extra }));
  return { api, context, viewport, document, oldControl, pointer, click, start, end, dismissed,
    advance: ms => { now += ms; }, get focuses() { return focuses; }, get saves() { return saves; } };
}

test('accepted left/trackpad and right pans transfer focus before movement', () => {
  for (const button of [0, 2]) {
    const h = fixture(); h.start({ button });
    assert.equal(h.context.activeInteraction.type, 'pan');
    assert.equal(h.document.activeElement, h.viewport);
    assert.equal(h.focuses, 1);
    assert.deepEqual(h.dismissed, [['zoom', false], ['workflow', false]]);
  }
});

test('marquee takes focus too; mouse fallback preserves right pan focus ownership', () => {
  const h = fixture(); h.context.isSelectToolActive = () => true; h.start();
  assert.equal(h.context.activeInteraction.type, 'marquee');
  assert.equal(h.document.activeElement, h.viewport);
  const fallback = fixture(); fallback.context.startRightMousePanFallback(fallback.pointer({ button: 2, type: 'mousedown' }));
  assert.equal(fallback.context.activeInteraction.mouseFallback, true);
  assert.equal(fallback.document.activeElement, fallback.viewport);
});

test('clicks on controls and panels do not lose focus or become pans', () => {
  for (const [button, blocked] of [[0, 'left-block'], [2, 'right-block'], [2, 'control']]) {
    const h = fixture(); h.start({ button, target: { closest: selector => selector === blocked ? {} : null } });
    assert.equal(h.context.activeInteraction, null);
    assert.equal(h.document.activeElement, h.oldControl);
    assert.equal(h.focuses, 0);
    assert.deepEqual(h.dismissed, []);
  }
});

test('a moved primary pan consumes its release click before any node action runs', () => {
  const h = fixture(); h.start(); h.context.activeInteraction.moved = true; h.end();
  assert.equal(h.context.activeInteraction, null); assert.equal(h.saves, 1);
  const event = h.click();
  assert.equal(h.api.handlePostPanClick(event), true);
  assert.equal(event.prevented, true); assert.equal(event.stopped, true);
  assert.equal(h.api.handlePostPanClick(h.click()), false, 'only the trailing click is consumed');
});

test('the next real pointerdown immediately restores ordinary clicking', () => {
  const h = fixture(); h.start(); h.context.activeInteraction.moved = true; h.end();
  h.api.resetPanClickGuard();
  assert.equal(h.api.handlePostPanClick(h.click()), false);
});

test('stationary presses, right pans and pointer cancellation never arm a primary click guard', () => {
  for (const kind of ['stationary', 'right', 'cancel']) {
    const h = fixture(), button = kind === 'right' ? 2 : 0;
    h.start({ button }); h.context.activeInteraction.moved = kind !== 'stationary';
    h.end({ button, type: kind === 'cancel' ? 'pointercancel' : 'pointerup' });
    assert.equal(h.api.handlePostPanClick(h.click()), false, kind);
  }
});

test('keyboard/programmatic clicks and unrelated pointers are not swallowed', () => {
  const h = fixture(); h.start(); h.context.activeInteraction.moved = true; h.end();
  for (const extra of [{ detail: 0, pointerId: -1 }, { pointerId: 12 }, { button: 2 }]) {
    const event = h.click(extra);
    assert.equal(h.api.handlePostPanClick(event), false); assert.equal(event.prevented, undefined);
  }
});

test('mouse compatibility click is handled and an unused guard expires', () => {
  const h = fixture(); h.start(); h.context.activeInteraction.moved = true; h.end();
  assert.equal(h.api.handlePostPanClick(h.click({ pointerId: undefined })), true);
  h.start(); h.context.activeInteraction.moved = true; h.end(); h.advance(1000);
  assert.equal(h.api.handlePostPanClick(h.click()), false);
});

test('host binds release-click handling in capture phase, clears on a fresh press and busts changed assets', () => {
  assert.match(host, /deskCanvasViewport\?\.addEventListener\('click', canvasViewport\.handlePostPanClick, true\)/);
  assert.match(host, /addEventListener\('pointerdown', \(\) => \{\s*canvasViewport\.resetPanClickGuard\(\);\s*setNodePaletteOpen\(false\);\s*\}, true\)/);
  const html = read('desktop.html');
  for (const name of ['desktop-canvas', 'desktop-canvas-viewport']) {
    assert.ok(html.includes(`${name}.js?v=${name === 'desktop-canvas' ? '20261007-node-progress4' : '20261006-pan-click-guard1'}`), name);
  }
});
