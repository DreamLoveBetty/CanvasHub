const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

// The geometry constants live in desktop-canvas.js; evaluate that block on its own.
function constants() {
  const canvas = read('frontend/scripts/desktop-canvas.js');
  const start = canvas.indexOf('  const DEFAULT_IMAGE_NODE_WIDTH');
  const end = canvas.indexOf('  const IMAGE_GROUP_PROXIMITY_DISTANCE_PX');
  assert.ok(start > 0 && end > start, 'image group constant block');
  const names = [...canvas.slice(start, end).matchAll(/const (\w+) =/g)].map(match => match[1]);
  const sandbox = {};
  vm.runInNewContext(`${canvas.slice(start, end)}\nresult = { ${names.join(', ')} };`, sandbox);
  return sandbox.result;
}

function model(C) {
  const sandbox = { window: {}, globalThis: {} };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-image-group-model.js'), sandbox);
  return sandbox.window.DesktopCanvasImageGroupModel.create({
    ...C,
    IMAGE_GROUP_ROLES: [{ value: 'reference', label: '参考' }],
    IMAGE_GROUP_ROLE_INSTRUCTIONS: {},
    clamp: (value, min, max) => Math.min(max, Math.max(min, value)),
    dataUrlValue: value => String(value || ''),
    escapeHtml: value => String(value ?? ''),
    jsonClone: value => JSON.parse(JSON.stringify(value)),
    imageNodeSource: node => node?.imageUrl || '',
  });
}

const near = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1e-6, `${label}: ${actual} != ${expected}`);

test('thumbnails fill the mother card: one even spacing on every side, initial height unchanged', () => {
  const C = constants();
  const M = model(C);
  const pad = C.IMAGE_GROUP_PADDING_PX;
  // Same 201.6px node (288px mother card) as before the thumbnails grew.
  near(C.DEFAULT_IMAGE_GROUP_NODE_HEIGHT, C.imageGroupUiSize(336), 'default height');
  near(M.imageGroupNodeHeight(2), C.DEFAULT_IMAGE_GROUP_NODE_HEIGHT, 'two-item height');
  near(C.IMAGE_GROUP_THUMB_PX, C.IMAGE_GROUP_MOTHER_HEIGHT_PX - pad * 2, 'thumbnail fills the card height');
  near(C.IMAGE_GROUP_THUMB_STEP_PX - C.IMAGE_GROUP_THUMB_PX, pad, 'gap between thumbnails');
  near(C.IMAGE_GROUP_ROW_STEP_PX - C.IMAGE_GROUP_THUMB_PX, pad, 'gap between rows');
  for (const count of [2, 3, 4, 6, 12]) {
    const width = M.naturalImageGroupNodeWidth(count);
    const columns = M.imageGroupColumnCount(count);
    const rows = M.imageGroupRowCount(count);
    const first = M.imageGroupThumbPosition(0);
    const lastColumn = M.imageGroupThumbPosition(columns - 1);
    const lastRow = M.imageGroupThumbPosition((rows - 1) * C.IMAGE_GROUP_MAX_COLUMNS);
    near(first.left, pad, `left edge (${count})`);
    near(first.top - C.IMAGE_GROUP_MOTHER_TOP_PX, pad, `top edge (${count})`);
    near(width - (lastColumn.left + C.IMAGE_GROUP_THUMB_PX), pad, `right edge (${count})`);
    near(C.IMAGE_GROUP_MOTHER_TOP_PX + M.imageGroupMotherHeight(count) - (lastRow.top + C.IMAGE_GROUP_THUMB_PX), pad, `bottom edge (${count})`);
  }
  // Card and thumbnail corners stay concentric across the spacing.
  near(C.IMAGE_GROUP_MOTHER_RADIUS_PX, C.IMAGE_GROUP_THUMB_RADIUS_PX + pad, 'concentric radius');
  // Connection swells grow from the thumbnails' footprint, the visible body without a panel.
  for (const count of [2, 6]) {
    const body = M.imageGroupContentBounds({ items: Array.from({ length: count }, (_, i) => ({ itemId: String(i) })) });
    near(body.x, pad, `body x (${count})`);
    near(body.y, C.IMAGE_GROUP_MOTHER_TOP_PX + pad, `body y (${count})`);
    near(body.x + body.width, M.compactImageGroupNodeWidth(count) - pad, `body right (${count})`);
    near(body.y + body.height, C.IMAGE_GROUP_MOTHER_TOP_PX + M.imageGroupMotherHeight(count) - pad, `body bottom (${count})`);
    near(body.radius, C.IMAGE_GROUP_THUMB_RADIUS_PX, 'body radius');
  }
});

test('the group shows only its thumbnails: no title, count or panel; it moves by a grip', () => {
  const C = constants();
  const M = model(C);
  const html = M.imageGroupNodeHtml({
    id: 'g1', type: 'image_group', x: 0, y: 0,
    items: [{ itemId: 'a', imageUrl: '/a.png' }, { itemId: 'b', imageUrl: '/b.png' }],
  });
  assert.doesNotMatch(html, /desk-image-group__identity|data-image-group-count|<strong>图片组<\/strong>|\d+ 张<\/span>/);
  assert.match(html, /aria-label="图片组，2 张图片"/, 'the accessible name keeps the count');
  // No liquid panel (silhouette, goo filter, shells) and no dropdown; the role is a chip.
  assert.doesNotMatch(html, /desk-image-group__silhouette|data-image-group-liquid-base|data-image-group-goo|<select|item-actions/);
  // The role is a display-only tag; tapping the thumbnail opens the picker.
  assert.equal(html.match(/<span class="desk-image-group__role" data-image-group-role-label aria-hidden="true">参考<\/span>/g)?.length, 2);
  assert.equal(html.match(/data-role="reference" aria-haspopup="menu"/g)?.length, 2);
  assert.doesNotMatch(html, /data-image-group-role-trigger/);
  // The mother is not a drag handle any more; the grip in the node actions is, and it is
  // not a button (buttons never start a node drag) nor inside a drag-ignore container.
  assert.doesNotMatch(html, /desk-image-group__mother[^>]*data-node-drag-handle/);
  assert.match(html, /<div class="desk-image-group__node-actions" aria-label="图片组操作">\s*<span class="desk-key desk-image-group__grip" data-node-drag-handle/);
  const interaction = read('frontend/scripts/desktop-canvas-image-group-interaction.js');
  assert.doesNotMatch(interaction, /transition__identity|identityInset|identityTop|IMAGE_GROUP_IDENTITY_WIDTH_PX/);
  assert.doesNotMatch(interaction, /mother-shape|liquid-svg|data-image-group-goo-item|data-image-group-liquid-base|\.blob\b/);
  for (const file of ['desktop-image-group-geometry.css', 'desktop-image-group.css', 'desktop-image-group-interaction.css', 'desktop-tokens.css', 'desktop-performance.css', 'desktop-motion.css', 'desktop-controls.css']) {
    assert.doesNotMatch(read(`frontend/styles/${file}`), /image-group__identity|image-group-transition__identity|image-group(-transition)?-(title|meta)-ink|liquid-label-in|image-group__silhouette|image-group__liquid|transition__liquid-svg|mother-shape|image-group-(liquid-fill|silhouette-filter|pan-shadow)|image-group__item-actions|image-group-role-(trigger|menu|option|native|chevron)|data-select-variant="image-group-role"\]\s*[.:{]/, file);
  }
  assert.doesNotMatch(read('frontend/scripts/desktop-select.js'), /image-group/);
});

test('the stylesheet mirrors the model geometry', () => {
  const C = constants();
  const base = value => +(value / C.IMAGE_GROUP_UI_SCALE).toFixed(4);
  const css = read('frontend/styles/desktop-image-group-geometry.css');
  const rule = selector => {
    const start = css.indexOf(`body.desk-app[data-theme] ${selector} {`);
    assert.ok(start >= 0, selector);
    return css.slice(start, css.indexOf('}', start));
  };
  const px = value => `calc(${value}px * var(--desk-image-group-ui-scale))`;
  const items = rule('.desk-image-group__items');
  assert.ok(items.includes(`top: ${px(base(C.IMAGE_GROUP_MOTHER_TOP_PX + C.IMAGE_GROUP_PADDING_PX))};`), 'items top');
  assert.ok(items.includes(`left: ${px(base(C.IMAGE_GROUP_PADDING_PX))};`), 'items left');
  assert.ok(items.includes(`repeat(var(--desk-image-group-columns, 2), ${px(base(C.IMAGE_GROUP_THUMB_STEP_PX))})`), 'column step');
  assert.ok(items.includes(`grid-auto-rows: ${px(base(C.IMAGE_GROUP_ROW_STEP_PX))};`), 'row step');
  assert.ok(rule('.desk-image-group__item').includes(`width: ${px(base(C.IMAGE_GROUP_THUMB_PX))};`), 'item width');
  const thumb = rule('.desk-image-group__thumb');
  assert.ok(thumb.includes(`height: ${px(base(C.IMAGE_GROUP_THUMB_PX))};`), 'thumb height');
  assert.ok(thumb.includes(`border-radius: ${px(base(C.IMAGE_GROUP_THUMB_RADIUS_PX))};`), 'thumb radius');
  // The selection frame hugs the thumbnails' footprint (what the connection swell rides),
  // outset by the line's own 3px so the swell's 2px outset lands on the line.
  const frame = rule('.desk-image-group__mother::after');
  const outset = ' - var(--desk-image-group-selection-outset)';
  assert.ok(frame.includes(`inset: calc(${base(C.IMAGE_GROUP_MOTHER_TOP_PX + C.IMAGE_GROUP_PADDING_PX)}px * var(--desk-image-group-ui-scale)${outset})\n    calc(${base(C.IMAGE_GROUP_PADDING_PX)}px * var(--desk-image-group-ui-scale)${outset});`), 'frame inset');
  assert.ok(frame.includes(`border-radius: calc(${base(C.IMAGE_GROUP_THUMB_RADIUS_PX)}px * var(--desk-image-group-ui-scale) + var(--desk-image-group-selection-outset));`), 'frame radius');
  assert.match(read('frontend/styles/desktop-canvas-nodes-geometry.css'), /--desk-image-group-selection-outset: 3px;/);
  assert.match(read('frontend/scripts/desktop-canvas.js'), /const IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX = 2;/);
  // Node actions: bare buttons (no tray) right-aligned with the thumbnails, just above the frame.
  const actions = rule('.desk-image-group__node-actions');
  assert.ok(actions.includes(`right: ${px(base(C.IMAGE_GROUP_PADDING_PX))};`), 'actions right edge');
  assert.ok(actions.includes('top: calc(-8px * var(--desk-image-group-ui-scale) - var(--desk-image-group-selection-outset));'), 'actions sit on the frame');
  assert.doesNotMatch(actions, /padding|border|background/);
  assert.doesNotMatch(read('frontend/styles/desktop-image-group.css') + read('frontend/styles/desktop-tokens.css'), /node-actions-(background|border|shadow)/);
  // Group/ungroup transition layers round like the thumbnails.
  const percent = `${(C.IMAGE_GROUP_THUMB_RADIUS_PX / C.IMAGE_GROUP_THUMB_PX * 100).toFixed(4)}%`;
  assert.equal(css.split(`border-radius: ${percent};`).length - 1, 2, percent);
});

// Runs removeImageGroupItem against a fake host and records what it asked the host to do.
function deletionHarness(C, itemIds, { removeGroup = () => true } = {}) {
  const calls = [];
  const items = itemIds.map(itemId => ({ itemId, sourceNodeId: `node_${itemId}`, role: 'reference', imageUrl: `/${itemId}.png` }));
  const group = {
    id: 'g1', type: 'image_group', x: 40, y: 60, items,
    memberEdges: [{ id: 'e1', from: 'node_b', to: 'text1' }, { id: 'e2', from: 'node_a', to: 'text1' }],
  };
  const edges = [{ id: 'out', from: 'g1', to: 'model1' }];
  const sandbox = {
    window: {}, globalThis: {}, requestAnimationFrame: run => { calls.push('flip'); run(); },
    DesktopState: {
      state: { canvas: { nodes: { g1: group }, edges } },
      saveSettings: options => calls.push(['save', options.criticalCanvas]),
    },
    DesktopResults: { showTransientMessage: message => calls.push(['message', message]) },
  };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-image-group-model.js'), sandbox);
  const M = sandbox.window.DesktopCanvasImageGroupModel.create({
    ...C,
    IMAGE_GROUP_ROLES: [{ value: 'reference', label: '参考' }],
    IMAGE_GROUP_ROLE_INSTRUCTIONS: {},
    animateImageGroupItemFlip: () => calls.push('animate'),
    applyNodeLayout: id => calls.push(['layout', id, group.width, group.height]),
    captureImageGroupItemRects: () => new Map(),
    clamp: (value, min, max) => Math.min(max, Math.max(min, value)),
    dataUrlValue: value => String(value || ''),
    ensureNodeEdgeHandles: () => {},
    escapeHtml: value => String(value ?? ''),
    freezeImageReferenceTokensForGroupItem: (groupId, item) => { calls.push(['freeze', groupId, item.itemId]); return item.itemId === 'b' ? 2 : 0; },
    getNodeElement: () => ({ querySelector: () => ({}), querySelectorAll: () => [], setAttribute: () => {}, style: { setProperty: () => {} } }),
    jsonClone: value => JSON.parse(JSON.stringify(value)),
    imageNodeSource: node => node?.imageUrl || '',
    onImageGroupItemsChanged: id => calls.push(['graph', id]),
    refreshImageReferenceTokens: id => calls.push(['tokens', id]),
    removeImageGroupNode: id => { calls.push(['remove-group', id]); return removeGroup(); },
    updateLinkPath: () => calls.push('links'),
  });
  return { M, group, edges, calls };
}

test('a one-image group hugs its thumbnail and links leave from the frame line', () => {
  const C = constants();
  const M = model(C);
  near(C.MIN_IMAGE_GROUP_NODE_WIDTH, C.IMAGE_GROUP_PADDING_PX * 2 + C.IMAGE_GROUP_THUMB_PX, 'minimum width');
  assert.equal(M.imageGroupColumnCount(1), 1);
  near(M.compactImageGroupNodeWidth(1), C.MIN_IMAGE_GROUP_NODE_WIDTH, 'one-image width');
  near(M.compactImageGroupNodeWidth(2), C.DEFAULT_IMAGE_GROUP_NODE_WIDTH, 'two-image width unchanged');
  const body = M.imageGroupContentBounds({ items: [{ itemId: 'a' }] });
  near(body.width, C.IMAGE_GROUP_THUMB_PX, 'frame body hugs the thumbnail');
  const geometry = read('frontend/styles/desktop-canvas-nodes-geometry.css');
  const scale = geometry.match(/--desk-image-group-ui-scale: ([.\d]+);/)[1];
  near(Number(scale), C.IMAGE_GROUP_UI_SCALE, 'css scale');
  assert.ok(geometry.includes('min-width: calc(288px * var(--desk-image-group-ui-scale));'));
  assert.match(geometry, /\.desk-node--image-group\.desk-node--edge-handles > \.desk-port\[data-semantic-port\]\[data-port-side="right"\] \{\n  right: calc\(var\(--desk-image-group-frame-inset\) - 8px\);/);

  const nodes = { g1: { id: 'g1', type: 'image_group', x: 100, y: 50, width: 400, height: 200, items: [{ itemId: 'a' }] } };
  const sandbox = { window: {}, globalThis: {}, DesktopState: { state: { canvas: { nodes } } } };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-connections.js'), sandbox);
  const connections = sandbox.window.DesktopCanvasConnections.create({
    IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX: C.IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX,
    getNodeElement: () => null,
    getNodeState: id => nodes[id],
    imageGroupContentBounds: node => M.imageGroupContentBounds(node),
    normalizePortSide: side => side,
  });
  const anchor = connections.getAnchor('g1', 'right');
  near(anchor.x, 100 + body.x + body.width + C.IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX, 'anchor on the frame line');
  near(anchor.y, 50 + body.y + body.height / 2, 'anchor at the frame middle');
});

test('the settled bulge sits on the frame line and the number badge stays inside it', () => {
  const nodes = read('frontend/styles/desktop-canvas-nodes-geometry.css');
  assert.ok(nodes.includes('--desk-node-settled-port-inset: var(--desk-image-group-frame-inset);'));
  assert.ok(nodes.includes('right: calc(var(--desk-node-settled-port-inset, 0px) - 7px);'), 'pill bulge');
  assert.ok(nodes.includes('right: calc(var(--desk-node-settled-port-inset, 0px) - 9px);'), 'droplet bulge');
  const css = read('frontend/styles/desktop-image-group-geometry.css');
  const badge = css.slice(css.indexOf('.desk-image-group__thumb strong {'));
  assert.match(badge, /right: calc\(12px \* var\(--desk-image-group-ui-scale\)\);\s+bottom: calc\(12px \* var\(--desk-image-group-ui-scale\)\);/);
  const chip = css.slice(css.indexOf('.desk-image-group-transition__chip strong {'));
  assert.match(chip, /right: calc\(var\(--desk-image-group-chip-unit\) \* 12\);\s+bottom: calc\(var\(--desk-image-group-chip-unit\) \* 12\);/);
});

test('deleting one image renumbers the rest and keeps the downstream edge', () => {
  const C = constants();
  const { M, group, edges, calls } = deletionHarness(C, ['a', 'b', 'c']);
  const threeWide = M.compactImageGroupNodeWidth(3);
  assert.equal(M.removeImageGroupItem('g1', 'b'), true);
  assert.deepEqual(group.items.map(item => item.itemId), ['a', 'c']);
  assert.deepEqual(edges.map(edge => edge.id), ['out']);
  // Ungrouping must not rebuild edges of the deleted image.
  assert.deepEqual(group.memberEdges.map(edge => edge.id), ['e2']);
  const html = M.imageGroupItemsHtml(group);
  assert.match(html, /data-image-group-item="a" data-image-group-label="图片1"/);
  assert.match(html, /data-image-group-item="c" data-image-group-label="图片2"/);
  assert.ok(group.width < threeWide, 'the node narrows');
  assert.equal(group.width, M.compactImageGroupNodeWidth(2));
  // The deleted image's tokens freeze before the survivors' tokens renumber.
  const names = calls.map(call => Array.isArray(call) ? call[0] : call);
  assert.ok(names.indexOf('freeze') < names.indexOf('tokens'));
  for (const step of ['layout', 'graph', 'links', 'save', 'animate']) assert.ok(names.includes(step), step);
  assert.ok(calls.some(call => call[0] === 'save' && call[1] === true), 'critical canvas save');
  assert.match(calls.find(call => call[0] === 'message')[1], /已从图片组删除图片2，当前共 2 张。提示词中 2 处引用/);
});

test('crossing a row boundary shrinks the node height', () => {
  const C = constants();
  const { M, group } = deletionHarness(C, ['a', 'b', 'c', 'd', 'e']);
  const twoRows = M.imageGroupNodeHeight(5);
  M.removeImageGroupItem('g1', 'e');
  assert.equal(group.height, M.imageGroupNodeHeight(4));
  assert.ok(group.height < twoRows);
});

test('one image stays a group; deleting it asks the host to remove the group', () => {
  const C = constants();
  const { M, group, calls } = deletionHarness(C, ['a', 'b']);
  assert.equal(M.removeImageGroupItem('g1', 'a'), true);
  assert.deepEqual(group.items.map(item => item.itemId), ['b']);
  assert.ok(!calls.some(call => call[0] === 'remove-group'));
  assert.equal(M.removeImageGroupItem('g1', 'b'), true);
  assert.deepEqual(calls.filter(call => call[0] === 'remove-group'), [['remove-group', 'g1']]);
  // The host owns the group: a declined confirmation leaves the image in place.
  const declined = deletionHarness(C, ['a'], { removeGroup: () => false });
  assert.equal(declined.M.removeImageGroupItem('g1', 'a'), false);
  assert.equal(declined.group.items.length, 1);
});

test('an unknown item changes nothing', () => {
  const C = constants();
  const { M, group, calls } = deletionHarness(C, ['a', 'b']);
  assert.equal(M.removeImageGroupItem('g1', 'missing'), false);
  assert.equal(M.removeImageGroupItem('nope', 'a'), false);
  assert.equal(group.items.length, 2);
  assert.deepEqual(calls, []);
});

test('the host refreshes comfy image counts when a group shrinks', () => {
  assert.match(read('frontend/scripts/desktop-canvas.js'), /onImageGroupItemsChanged: groupId => \{[\s\S]*?refreshComfyNode\(edge\.to\)[\s\S]*?notifyDomainGraphChanged\(\);/);
});

test('the delete button is a labelled sibling of the sort handle, clear of the tag and badge', () => {
  const C = constants();
  const M = model(C);
  const html = M.imageGroupItemHtml({ id: 'g1' }, { itemId: 'a', imageUrl: '/a.png', role: 'reference' }, 1);
  assert.match(html, /<button type="button" class="desk-image-group__delete" data-image-group-item-delete title="从图片组删除" aria-label="从图片组删除图片2">/);
  // Outside the thumbnail, so a press never starts the sort gesture or the role picker.
  assert.doesNotMatch(html.slice(html.indexOf('data-image-group-sort-handle'), html.indexOf('</div>')), /item-delete/);
  const css = read('frontend/styles/desktop-image-group-geometry.css');
  const rule = css.slice(css.indexOf('body.desk-app[data-theme] .desk-image-group__delete {'));
  assert.match(rule.slice(0, rule.indexOf('}')), /bottom: [^;]+;\s+left: /);
  assert.match(css, /:not\(\.is-picking\) :is\(\.desk-image-group__insert, \.desk-image-group__delete\) \{\n  opacity: 1;/);
  assert.match(read('frontend/styles/desktop-image-group-interaction.css'), /\.is-sorting :is\([^)]*\.desk-image-group__delete\)/);
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.match(canvas, /event\.detail > 1 \|\| draggedImageGroupItem/, 'double clicks and live sorts delete nothing');
  assert.match(read('frontend/scripts/desktop-canvas-text-editor.js'), /IMAGE_REFERENCE_DELETED_TEXT = '（已删除图片）'/);
});
