const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function harness() {
  const frames = [];
  let layoutReads = 0;
  const selections = [];
  const canvas = { scale: 1, nodes: {}, selectedNodeIds: [] };
  for (let i = 0; i < 6; i++) canvas.nodes[`n${i}`] = { id: `n${i}`, x: i * 100, y: 0, width: 80, height: 60 };
  const element = id => ({ get offsetWidth() { layoutReads++; return canvas.nodes[id].width; }, get offsetHeight() { layoutReads++; return canvas.nodes[id].height; } });
  const context = vm.createContext({
    window: {}, document: { querySelectorAll: () => [] },
    requestAnimationFrame: fn => { frames.push(fn); return frames.length; }, cancelAnimationFrame: id => { frames[id - 1] = null; },
  });
  vm.runInContext(read('frontend/scripts/desktop-canvas-selection.js'), context);
  const api = context.window.DesktopCanvasSelection.create({
    getCanvas: () => canvas, els: { deskSelectionMarquee: { style: {}, classList: { add() {}, remove() {} } } },
    getNodeElement: element, getBoundsFromRects: () => null,
    rectsIntersect: (a, b) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y,
    applyNodeLayout() {}, setSelectedNodes: ids => { selections.push([...ids]); canvas.selectedNodeIds = [...ids]; },
    updateLinkPath() {}, saveSettings() {}, showTransientMessage() {}, imageNodeSource() {},
  });
  const flush = () => { const pending = frames.splice(0); pending.forEach(fn => fn && fn()); };
  return { api, flush, selections, frames, reads: () => layoutReads };
}

test('marquee measures node bounds once, folds moves into one update per frame and re-selects only on change', () => {
  const h = harness();
  h.api.beginMarquee();
  const readsAtStart = h.reads();
  assert.equal(readsAtStart, 12, 'width + height of each node, once');
  // Three moves inside one frame → one scheduled update.
  h.api.moveMarquee({ x: 0, y: 0, width: 50, height: 50 });
  h.api.moveMarquee({ x: 0, y: 0, width: 120, height: 50 });
  h.api.moveMarquee({ x: 0, y: 0, width: 150, height: 50 });
  assert.equal(h.frames.length, 1);
  h.flush();
  assert.deepEqual(h.selections, [['n0', 'n1']]);
  // Moves that keep the same set inside the box do not re-apply the selection.
  h.api.moveMarquee({ x: 0, y: 0, width: 160, height: 50 }); h.flush();
  h.api.moveMarquee({ x: 0, y: 0, width: 170, height: 55 }); h.flush();
  assert.equal(h.selections.length, 1);
  h.api.moveMarquee({ x: 0, y: 0, width: 350, height: 50 }); h.flush();
  assert.deepEqual(h.selections.at(-1), ['n0', 'n1', 'n2', 'n3']);
  assert.equal(h.reads(), readsAtStart, 'no layout reads while the box moves');
  // Ending cancels a pending frame.
  h.api.moveMarquee({ x: 0, y: 0, width: 10, height: 10 });
  h.api.endMarquee(); h.flush();
  assert.equal(h.selections.length, 2);
});

test('host routes marquee moves through the session; selection applies rebuild the edge layer once per frame', () => {
  const host = read('frontend/scripts/desktop-canvas.js');
  const move = host.slice(host.indexOf("if (activeInteraction.type === 'marquee') {\n      const pointer = screenToWorld"));
  assert.match(move.slice(0, 600), /moveMarquee\(rect\);\n      return;/);
  assert.doesNotMatch(move.slice(0, 600), /selectNodesInRect\(rect, false\)/);
  assert.match(host, /renderMarquee\(\{ x: pointer\.x, y: pointer\.y, width: 0, height: 0 \}\);\n      beginMarquee\(\);/);
  assert.match(host, /endMarquee\(\);\n      if \(rect\.width < 4/);
  const nodes = read('frontend/scripts/desktop-canvas-nodes.js');
  assert.match(nodes, /if \(!linkPathFrame\) linkPathFrame = requestAnimationFrame\(\(\) => \{ linkPathFrame = 0; updateLinkPath\(\); \}\);/);
  assert.doesNotMatch(nodes, /requestAnimationFrame\(updateLinkPath\)/);
  const html = read('frontend/desktop.html');
  for (const name of ['desktop-canvas', 'desktop-canvas-selection', 'desktop-canvas-nodes'])
    assert.ok(hasCacheKey(html, `scripts/${name}.js`), name);
});
