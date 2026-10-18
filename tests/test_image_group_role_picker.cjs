const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const source = read('frontend/scripts/desktop-canvas-image-group-role-picker.js');
const ROLES = [
  { value: 'reference', label: '参考', short: '参考' },
  { value: 'subject', label: '主体参考', short: '主体' },
  { value: 'clothing', label: '服饰参考', short: '服饰' },
  { value: 'style', label: '风格参考', short: '风格' },
  { value: 'composition', label: '构图参考', short: '构图' },
  { value: 'background', label: '背景参考', short: '背景' },
];

// Just enough DOM for the picker: elements are matched by the attributes the module asks for.
function fakeElement(attrs = {}) {
  const el = {
    attrs: { ...attrs }, dataset: {}, children: [], removed: false, focused: 0, html: '',
    classes: new Set(),
    classList: { add: c => el.classes.add(c), remove: c => el.classes.delete(c), contains: c => el.classes.has(c) },
    get isConnected() { return !el.removed; },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return el.attrs[k] ?? null; },
    focus() { el.focused += 1; sandbox.document.activeElement = el; },
    remove() { el.removed = true; },
  };
  return el;
}

let sandbox;
function fixture({ reduced = false } = {}) {
  const frames = [];
  const timers = [];
  sandbox = {
    window: { setTimeout: (fn, ms) => timers.push({ fn, ms }) },
    requestAnimationFrame: fn => frames.push(fn),
    document: {
      activeElement: null, filters: 0,
      getElementById: id => (sandbox.document.filters && id === 'desk-image-group-picker-goo' ? {} : null),
      body: { insertAdjacentHTML: (_, html) => { if (html.includes('desk-image-group-picker-goo')) sandbox.document.filters += 1; } },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  const picked = [];
  const picker = sandbox.window.DesktopCanvasImageGroupRolePicker.create({
    IMAGE_GROUP_ROLES: ROLES,
    escapeHtml: value => String(value ?? ''),
    imageGroupGooeyFilterPrimitivesHtml: () => '<feGaussianBlur stdDeviation="6"></feGaussianBlur>',
    normalizeImageGroupRole: value => (ROLES.some(role => role.value === value) ? value : 'reference'),
    onSelect: (item, role) => picked.push({ item, role }),
    prefersReducedMotion: () => reduced,
  });

  const item = fakeElement();
  item.dataset.imageGroupItem = 'item-a';
  item.dataset.imageGroupLabel = '图片2';
  item.dataset.role = 'subject';
  const label = { textContent: '主体' };
  const thumb = { closest: selector => (selector.includes('[data-image-group-sort-handle]') ? thumb : null) };
  let overlay = null;
  let options = [];
  item.insertAdjacentHTML = (_, html) => {
    overlay = fakeElement();
    overlay.html = html;
    overlay.getBoundingClientRect = () => { overlay.flushed = (overlay.flushed || 0) + 1; return {}; };
    options = [...html.matchAll(/data-image-group-role-option="(\w+)"/g)].map(match => {
      const option = fakeElement();
      option.dataset.imageGroupRoleOption = match[1];
      option.closest = selector => (selector.includes('[data-image-group-role-option]') ? option : selector.includes('[data-image-group-role-picker]') ? overlay : null);
      return option;
    });
    overlay.querySelector = selector => (selector === '.is-current' ? options.find(o => o.dataset.imageGroupRoleOption === item.dataset.role) : options[0]);
    overlay.querySelectorAll = () => options;
  };
  item.querySelector = selector => (selector === '[data-image-group-role-label]' ? label : overlay);
  item.contains = node => node === thumb;
  item.matches = selector => selector === '[data-image-group-item]';
  const outside = { closest: () => null };
  const runFrames = () => { while (frames.length) frames.shift()(); };
  const runTimers = () => { while (timers.length) timers.shift().fn(); };
  return { picker, item, thumb, label, picked, get overlay() { return overlay; }, get options() { return options; }, outside, runFrames, runTimers };
}

test('options sit on an even ring around the thumbnail centre, clockwise from the top', () => {
  const ctx = { window: {} };
  vm.runInNewContext(source, ctx);
  const { ringPosition, RING_RADIUS } = ctx.window.DesktopCanvasImageGroupRolePicker;
  const ring = ROLES.map((_, index) => ringPosition(index, ROLES.length));
  ring.forEach(point => assert.ok(Math.abs(Math.hypot(point.x, point.y) - RING_RADIUS) < 0.01));
  assert.deepEqual({ ...ring[0] }, { x: 0, y: -RING_RADIUS });
  assert.ok(ring[1].x > 0 && ring[1].y < 0, 'second option is to the upper right');
  assert.ok(Math.abs(ring[3].y - RING_RADIUS) < 0.01, 'fourth option is straight below');
  // 52px buttons on the ring stay inside the 240px thumbnail, and neighbours keep a gap the
  // goo (blur 6 at the 0.6 UI scale) cannot bridge at rest.
  const css = read('frontend/styles/desktop-image-group-geometry.css');
  assert.match(css, /\.desk-image-group-picker__buttons > button\) \{[^}]*width: calc\(52px \* var\(--desk-image-group-ui-scale\)\);/);
  assert.ok(RING_RADIUS + 26 < 120, 'inside the thumbnail');
  assert.ok(Math.hypot(ring[1].x - ring[0].x, ring[1].y - ring[0].y) - 52 >= 24, 'resting gap');
});

test('options are icons with the full role name as their label, one icon per role', () => {
  const ctx = { window: {} };
  vm.runInNewContext(source, ctx);
  const { ROLE_ICONS } = ctx.window.DesktopCanvasImageGroupRolePicker;
  assert.deepEqual(Object.keys(ROLE_ICONS).sort(), ROLES.map(role => role.value).sort());
  assert.equal(new Set(Object.values(ROLE_ICONS)).size, ROLES.length, 'distinct icons');
  const f = fixture();
  f.picker.tap(f.item);
  ROLES.forEach(role => {
    const button = f.overlay.html.match(new RegExp(`<button[^>]*data-image-group-role-option="${role.value}"[^>]*>([\\s\\S]*?)</button>`));
    assert.ok(button, role.value);
    assert.match(button[0], new RegExp(`aria-label="${role.label}"`));
    assert.match(button[1], /^<svg viewBox="0 0 24 24" aria-hidden="true">/);
    assert.doesNotMatch(button[1].replace(/<[^>]+>/g, ''), /\S/, 'no visible text');
  });
});

test('the picker has no trigger button of its own: the model renders a display-only tag', () => {
  const { picker } = fixture();
  assert.equal(picker.triggerHtml, undefined);
  const model = read('frontend/scripts/desktop-canvas-image-group-model.js');
  assert.match(model, /<span class="desk-image-group__role" data-image-group-role-label aria-hidden="true">/);
  assert.match(model, /data-role="\$\{escapeHtml\(role\)\}" aria-haspopup="menu"/);
  assert.doesNotMatch(model + source, /data-image-group-role-trigger/);
});

test('opening springs the options out after the closed pose is painted; the current role is checked', () => {
  const f = fixture();
  f.picker.tap(f.item);
  assert.match(f.overlay.html, /role="menu" aria-label="图片2的参考用途"/);
  assert.equal(f.options.length, 6);
  ROLES.forEach((role, index) => {
    const tag = f.overlay.html.match(new RegExp(`<button[^>]*data-image-group-role-option="${role.value}"[^>]*>`))[0];
    assert.match(tag, new RegExp(`--i:${index + 1};`));
    assert.match(tag, new RegExp(`aria-checked="${role.value === 'subject'}"`));
  });
  // Goo blobs mirror the buttons one-for-one (plus the centre), sharing --i/--x/--y.
  assert.equal(f.overlay.html.match(/<span (class="is-center" )?style="--i:/g).length, 7);
  assert.ok(f.item.classes.has('is-picking'));
  assert.ok(!f.overlay.classes.has('is-open'), 'not open before the frames run');
  assert.equal(f.overlay.flushed, 1, 'the closed pose is style-flushed before opening');
  f.runFrames();
  assert.ok(f.overlay.classes.has('is-open'));
  assert.equal(f.options.find(o => o.dataset.imageGroupRoleOption === 'subject').focused, 1, 'focus lands on the current role');
  // The goo filter is created once, on first use.
  f.picker.close({ immediate: true });
  f.picker.tap(f.item);
  assert.equal(sandbox.document.filters, 1);
});

test('choosing an option commits through onSelect, relabels the tag and closes back to the image', () => {
  const f = fixture();
  f.picker.tap(f.item);
  f.runFrames();
  const style = f.options.find(o => o.dataset.imageGroupRoleOption === 'style');
  assert.equal(f.picker.handleClick({ target: style }), true);
  assert.deepEqual(f.picked.map(entry => entry.role), ['style']);
  assert.equal(f.picked[0].item, f.item);
  assert.equal(f.label.textContent, '风格');
  assert.equal(f.item.dataset.role, 'style');
  assert.equal(f.item.attrs['aria-description'], '参考用途：风格参考');
  assert.ok(!f.item.classes.has('is-picking'));
  assert.ok(f.item.focused >= 1, 'focus returns to the image');
  assert.ok(!f.overlay.classes.has('is-open'), 'collapses first');
  assert.ok(!f.overlay.removed, 'removed only after the collapse');
  f.runTimers();
  assert.ok(f.overlay.removed);
  assert.equal(f.picker.isOpen(), false);
});

test('Escape and outside presses close; arrows move between options; inside presses do not close', () => {
  const f = fixture();
  f.picker.tap(f.item);
  f.runFrames();
  const keys = key => {
    const event = { key, prevented: false, preventDefault() { this.prevented = true; } };
    return { handled: f.picker.handleKeydown(event), event };
  };
  sandbox.document.activeElement = f.options[1];
  assert.equal(keys('ArrowRight').handled, true);
  assert.equal(sandbox.document.activeElement, f.options[2]);
  keys('ArrowLeft'); keys('ArrowLeft');
  assert.equal(sandbox.document.activeElement, f.options[0]);
  keys('ArrowLeft');
  assert.equal(sandbox.document.activeElement, f.options[5], 'wraps around the ring');
  assert.equal(keys('Tab').handled, false, 'other keys pass through');
  f.picker.handlePointerDown({ target: { closest: s => (s.includes('[data-image-group-role-picker]') ? f.overlay : null) } });
  assert.equal(f.picker.isOpen(), true);
  const { handled, event } = keys('Escape');
  assert.equal(handled, true); assert.ok(event.prevented);
  assert.equal(f.picker.isOpen(), false);
  assert.equal(keys('Escape').handled, false, 'closed pickers ignore keys');

  const g = fixture();
  g.picker.tap(g.item);
  g.picker.handlePointerDown({ target: g.outside });
  assert.equal(g.picker.isOpen(), false);

  // Pressing the open picker's own image closes it, and the tap that follows does not reopen it.
  const h = fixture();
  h.picker.tap(h.item);
  h.runFrames();
  h.picker.handlePointerDown({ target: h.thumb });
  assert.equal(h.picker.isOpen(), false);
  h.picker.tap(h.item);
  assert.equal(h.picker.isOpen(), false);
  h.picker.handlePointerDown({ target: h.outside });
  h.picker.tap(h.item);
  assert.equal(h.picker.isOpen(), true, 'a later tap opens it again');
});

test('Enter or Space on a focused image opens its picker; other targets and keys pass through', () => {
  const f = fixture();
  const key = (target, value) => {
    const event = { key: value, target, prevented: false, preventDefault() { this.prevented = true; } };
    return { handled: f.picker.handleKeydown(event), event };
  };
  assert.equal(key({ matches: () => false }, 'Enter').handled, false);
  assert.equal(key(f.item, 'a').handled, false);
  const { handled, event } = key(f.item, ' ');
  assert.equal(handled, true); assert.ok(event.prevented);
  assert.equal(f.picker.isOpen(), true);
});

test('reduced motion opens and closes without the spring or the delayed cleanup', () => {
  const f = fixture({ reduced: true });
  f.picker.tap(f.item);
  assert.ok(f.overlay.classes.has('is-open'));
  f.picker.tap(f.item);
  assert.ok(f.overlay.removed, 'tapping the image again closes at once');
});

test('host wiring: loaded before the host, created before the model, keys handled before canvas deletes', () => {
  const html = read('frontend/desktop.html');
  const order = ['desktop-canvas-image-group-interaction.js', 'desktop-canvas-image-group-role-picker.js', 'scripts/desktop-canvas.js'];
  order.forEach(asset => assert.ok(hasCacheKey(html, asset.startsWith('scripts/') ? asset : `scripts/${asset}`), asset));
  const positions = order.map(asset => html.indexOf(asset));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.ok(canvas.indexOf('DesktopCanvasImageGroupRolePicker.create(') < canvas.indexOf('DesktopCanvasImageGroupModel.create('));
  assert.match(canvas, /onImageGroupItemTap: item => canvasImageGroupRolePicker\.tap\(item\)/);
  // The sort gesture reports a press without a drag as a tap.
  const interaction = read('frontend/scripts/desktop-canvas-image-group-interaction.js');
  assert.match(interaction, /if \(!cancelled && !sortState\.moved\) onImageGroupItemTap\?\.\(sortState\.itemEntries\[sortState\.fromIndex\]\?\.element\);/);
  assert.match(canvas, /onSelect: setImageGroupItemRole/);
  const pickerKeys = canvas.indexOf('canvasImageGroupRolePicker.handleKeydown(event)');
  const deleteKeys = canvas.indexOf("document.addEventListener('keydown', handleCanvasDeleteKeydown, true)");
  assert.ok(pickerKeys > 0 && deleteKeys > pickerKeys);
  assert.match(canvas, /canvasImageGroupRolePicker\.handleKeydown\(event\)\) event\.stopImmediatePropagation\(\)/);
  // The module binds nothing itself.
  assert.doesNotMatch(source, /addEventListener/);
});

test('options are frosted glass over the photo; the goo stays opaque and the layer fades as a whole', () => {
  const paint = read('frontend/styles/desktop-image-group.css');
  const geometry = read('frontend/styles/desktop-image-group-geometry.css');
  const tokens = read('frontend/styles/desktop-tokens.css');
  const buttons = paint.slice(paint.indexOf('.desk-image-group-picker__buttons > button {'));
  assert.match(buttons, /^[^}]*background: var\(--desk-image-group-picker-glass\);/);
  assert.match(buttons, /^[^}]*backdrop-filter: var\(--desk-image-group-picker-backdrop\);\n\s*-webkit-backdrop-filter: var\(--desk-image-group-picker-backdrop\);/);
  // The glass lives on the buttons, outside the goo-filtered layer (a filtered ancestor
  // would cut the backdrop off from the photo).
  assert.match(paint, /\.desk-image-group-picker__goo \{\n  filter: url\(#desk-image-group-picker-goo\);\n\}/);
  assert.match(geometry, /\.desk-image-group-picker\.is-open \.desk-image-group-picker__goo \{\n  opacity: var\(--desk-image-group-picker-goo-opacity\);/);
  // Opaque blobs in both themes: a translucent blob would fall below the goo threshold.
  const fills = [...tokens.matchAll(/--desk-image-group-picker-fill: ([^;]+);/g)].map(match => match[1]);
  assert.equal(fills.length, 2);
  fills.forEach(fill => assert.match(fill, /^#[0-9a-f]{6}$/i, fill));
  for (const name of ['glass', 'glass-edge', 'glass-shadow', 'backdrop', 'goo-opacity'])
    assert.equal(tokens.split(`--desk-image-group-picker-${name}:`).length - 1, 2, name);
  assert.doesNotMatch(tokens + paint, /--desk-image-group-picker-shadow/);
  // The current role keeps its accent ring and the glass depth.
  assert.match(paint, /\.desk-image-group-picker__option\.is-current \{\n  box-shadow: inset 0 0 0 2px var\(--desk-image-group-picker-current-ink\), var\(--desk-image-group-picker-glass-shadow\);/);
});
