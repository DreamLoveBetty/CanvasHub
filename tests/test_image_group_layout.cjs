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
