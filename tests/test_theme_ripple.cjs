const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function fakeContext2d() {
  const calls = [];
  const record = name => (...args) => calls.push([name, ...args]);
  return {
    calls,
    setTransform: record('setTransform'),
    clearRect: record('clearRect'),
    save: record('save'),
    restore: record('restore'),
    clip: record('clip'),
    stroke: record('stroke'),
  };
}

function load({ supportsPath = true } = {}) {
  const appended = [];
  const context2d = fakeContext2d();
  const window = {
    innerWidth: 1000,
    innerHeight: 600,
    devicePixelRatio: 2,
    CSS: { supports: (property, value) => supportsPath && property === 'clip-path' && value.startsWith('path(') },
  };
  const document = {
    createElement: () => ({
      dataset: {},
      setAttribute() {},
      getContext: () => context2d,
      remove() { this.removed = true; },
    }),
  };
  const sandbox = {
    window,
    document,
    Path2D: class { constructor(d) { this.d = d; } },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
  };
  vm.runInNewContext(read('frontend/scripts/desktop-theme-ripple.js'), sandbox);
  return { Ripple: window.DesktopThemeRipple, context2d, appended };
}

test('the ripple outline wobbles within a bounded band and stays a closed loop', () => {
  const { Ripple } = load();
  const phases = [0.4, 1.7, 2.9];
  assert.ok(Math.abs(Ripple.amplitudeFor(100) - 16) < 1e-9, 'small ripples wobble in proportion to their size');
  assert.equal(Ripple.amplitudeFor(2000), Ripple.MAX_AMPLITUDE, 'large ripples are capped');
  assert.equal(Ripple.radiusAt(0, 0, 0, phases), 0, 'nothing is revealed at the click point yet');
  const radii = Array.from({ length: 360 }, (_, i) => Ripple.radiusAt((i / 360) * Math.PI * 2, 0.5, 400, phases));
  assert.ok(Math.max(...radii) - Math.min(...radii) > 10, 'the edge is not a plain circle');
  assert.ok(radii.every(r => Math.abs(r - 400) <= Ripple.MAX_AMPLITUDE), 'wobble never exceeds the cap');
  assert.ok(Math.abs(Ripple.radiusAt(0, 0.5, 400, phases) - Ripple.radiusAt(Math.PI * 2, 0.5, 400, phases)) < 1e-9);
  assert.notEqual(Ripple.radiusAt(1, 0.2, 400, phases), Ripple.radiusAt(1, 0.4, 400, phases), 'the edge moves over time');
});

test('the overlay hole is the viewport minus a smooth closed blob', () => {
  const { Ripple } = load();
  const points = Ripple.outline({ x: 100, y: 50 }, 200, 0.3, [0, 0, 0], 12);
  assert.equal(points.length, 12);
  const blob = Ripple.blobPath(points);
  assert.match(blob, /^M[-\d.]+ [-\d.]+(Q[-\d.]+ [-\d.]+ [-\d.]+ [-\d.]+){12}Z$/);
  assert.equal(Ripple.holePath(1000, 600, points), `M0 0H1000V600H0Z${blob}`);
  assert.equal(Ripple.bandStrength(0), 0);
  assert.equal(Ripple.bandStrength(0.5), 1);
  assert.equal(Ripple.bandStrength(1), 0, 'the band is gone before the overlay is removed');
});

test('a run clips the overlay, paints the edge band and cleans up its canvas', () => {
  const { Ripple, context2d } = load();
  assert.equal(Ripple.supported(), true);
  assert.equal(load({ supportsPath: false }).Ripple.supported(), false);
  let inserted = null;
  const overlay = { style: {}, after: node => { inserted = node; node.isConnected = true; } };
  const run = Ripple.create({ overlay, origin: { x: 980, y: 20 }, endRadius: 1000, fromTheme: 'dark', phases: [0, 0, 0] });
  assert.equal(inserted, run.canvas, 'the edge canvas follows the overlay so it paints above it');
  assert.equal(run.canvas.className, 'desk-theme-ripple-edge');
  assert.equal(run.canvas.dataset.from, 'dark');
  assert.deepEqual([run.canvas.width, run.canvas.height], [2000, 1200]);
  run.frame(0.5, 0.875, 0.48);
  assert.match(overlay.style.clipPath, /^path\(evenodd, "M0 0H1000V600H0ZM.+Z"\)$/);
  const strokes = context2d.calls.filter(([name]) => name === 'stroke').length;
  assert.equal(strokes, 21, 'ten shade passes, ten glint passes and the rim');
  run.dispose();
  assert.equal(run.canvas.removed, true);
  // A detached edge (snapshot path before its update callback) paints nothing.
  const detached = Ripple.createEdge({ fromTheme: 'light', width: 1000, height: 600 });
  const before = context2d.calls.length;
  detached.paint(Ripple.outline({ x: 0, y: 0 }, 300, 0, [0, 0, 0]), 1);
  assert.equal(context2d.calls.length, before);
  assert.equal(Ripple.reachFor(1000), 1000 + Ripple.MAX_AMPLITUDE);
});

test('preferences drive the ripple and the overlay no longer uses a radial mask', () => {
  const preferences = read('frontend/scripts/desktop-preferences.js');
  assert.match(preferences, /if \(!window\.DesktopThemeRipple\?\.supported\?\.\(\)\) return false;/);
  assert.match(preferences, /window\.DesktopThemeRipple\.create\(\{ overlay, origin, endRadius, fromTheme: previousTheme \}\)/);
  assert.match(preferences, /run\.ripple\.frame\(progress, easeThemeReveal\(progress\), \(now - startedAt\) \/ 1000\);/);
  assert.match(preferences, /run\.ripple\?\.dispose\(\);\n\s*run\.overlay\?\.remove\(\);/);
  assert.doesNotMatch(preferences, /--theme-reveal-(x|y|radius)/);

  const liquid = read('frontend/styles/desktop-liquid.css');
  const overlayRule = liquid.match(/\n\.desk-theme-reveal-overlay \{[^}]*\}/)[0];
  assert.doesNotMatch(overlayRule, /mask|--theme-reveal/);
  assert.match(liquid, /\.desk-theme-ripple-edge \{[^}]*--desk-theme-ripple-shade:[^}]*--desk-theme-ripple-glint:[^}]*--desk-theme-ripple-rim:/);
  assert.match(liquid, /\.desk-theme-ripple-edge\[data-from="dark"\] \{/);
  assert.match(read('frontend/styles/desktop-geometry.css'), /body\.desk-app \.desk-theme-ripple-edge \{[^}]*z-index: var\(--desk-layer-theme-reveal\);[^}]*pointer-events: none;/);

  const graphite = read('frontend/styles/desktop-graphite.css');
  assert.match(graphite, /body\.desk-app\[data-desk-style="graphite"\] \.desk-theme-reveal-overlay \{\n\s*background: #e6e6e2;/);
  assert.match(graphite, /body\.desk-app\[data-desk-style="graphite"\] \.desk-theme-reveal-overlay\[data-theme="dark"\] \{\n\s*background: #232323;/);

  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-theme-ripple.js'));
  const at = file => html.indexOf(`scripts/${file}?v=`);
  assert.ok(at('desktop-theme-ripple.js') > 0 && at('desktop-theme-ripple.js') < at('desktop-preferences.js'));
});

function loadPreferences(stored = {}, extraWindow = {}) {
  const storage = { desktop_ui_preferences_v1: JSON.stringify(stored) };
  const element = () => {
    const attributes = {};
    const classes = new Set();
    return {
      attributes,
      classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) },
      setAttribute(name, value) { attributes[name] = String(value); },
      removeAttribute(name) { delete attributes[name]; },
      style: { setProperty() {}, removeProperty() {} },
    };
  };
  const ripples = [];
  const window = {
    innerWidth: 1000,
    innerHeight: 600,
    requestAnimationFrame: () => 1,
    cancelAnimationFrame() {},
    setTimeout: () => 1,
    clearTimeout() {},
    matchMedia: () => ({ matches: false }),
    dispatchEvent() {},
    DesktopThemeRipple: { supported: () => true, create: () => { ripples.push('fallback'); return { frame() {}, dispose() {} }; } },
    ...extraWindow,
  };
  const document = {
    body: element(),
    documentElement: element(),
    getElementById: () => null,
    createElement: () => ({ ...element(), dataset: {}, remove() {} }),
  };
  document.body.appendChild = () => {};
  document.body.after = () => {};
  const sandbox = {
    window, document,
    localStorage: { getItem: key => storage[key] ?? null, setItem: (key, value) => { storage[key] = value; } },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    performance: { now: () => 0 },
  };
  vm.runInNewContext(read('frontend/scripts/desktop-preferences.js'), sandbox);
  window.DesktopPreferences.init();
  return { Preferences: window.DesktopPreferences, document, ripples, saved: () => JSON.parse(storage.desktop_ui_preferences_v1) };
}

test('the switch animation preference turns the day/night ripple off and persists', () => {
  const ripple = loadPreferences();
  assert.equal(ripple.Preferences.state.themeTransition, 'ripple', 'the ripple is the default');
  ripple.Preferences.setTheme('dark');
  assert.deepEqual(ripple.ripples, ['fallback'], 'the default switch plays the reveal');

  const off = loadPreferences({ themeTransition: 'none' });
  assert.equal(off.Preferences.state.themeTransition, 'none');
  off.Preferences.setTheme('dark');
  assert.deepEqual(off.ripples, [], 'no reveal when the animation is off');
  assert.equal(off.document.documentElement.attributes['data-theme'], 'dark', 'the theme still switches at once');

  off.Preferences.setThemeTransition('ripple');
  assert.equal(off.saved().themeTransition, 'ripple');
  off.Preferences.setThemeTransition('bogus');
  assert.equal(off.Preferences.state.themeTransition, 'ripple', 'unknown values fall back to the ripple');
  assert.equal(loadPreferences({ themeTransition: 'sparkle' }).Preferences.state.themeTransition, 'ripple');

  const settings = read('frontend/scripts/desktop-settings.js');
  const card = settings.match(/function renderThemeStyleSettings\(\) \{[\s\S]*?\n  \}\n/)[0];
  assert.match(card, /data-theme-transition="ripple"[^>]*>水波</);
  assert.match(card, /data-theme-transition="none"[^>]*>关闭</);
  assert.match(settings, /window\.DesktopPreferences\?\.setThemeTransition\?\.\(transition\);/);
  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-settings.js'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-preferences.js'));
});

test('the reveal speed preset sets the run duration and the clock waits for the snapshot', () => {
  const { Ripple } = load();
  assert.deepEqual(JSON.parse(JSON.stringify(Ripple.SPEEDS.map(speed => [speed.key, speed.ms]))), [['stroll', 2400], ['walk', 1900], ['standard', 1400], ['run', 1000], ['sprint', 700]]);
  assert.equal(Ripple.SPEEDS.find(speed => speed.recommended).key, 'standard', 'the original timing is the recommended stop');
  assert.equal(Ripple.normalizeSpeed('SPRINT'), 'sprint');
  assert.equal(Ripple.durationFor('warp'), 1400, 'unknown speeds fall back to standard');

  const frames = [];
  const runs = [];
  let ready = false;
  const snapshot = {
    supported: () => true,
    create: options => {
      const run = { options, progress: [], frame: (progress) => run.progress.push(progress), dispose() {}, isReady: () => ready };
      runs.push(run);
      return run;
    },
  };
  const { Preferences, saved } = loadPreferences({ themeTransitionSpeed: 'sprint' }, {
    DesktopThemeRipple: { ...Ripple, create: () => assert.fail('the snapshot path is preferred') },
    DesktopThemeRippleSnapshot: snapshot,
    requestAnimationFrame: cb => { frames.push(cb); return frames.length; },
  });
  assert.equal(Preferences.state.themeTransitionSpeed, 'sprint');
  Preferences.setTheme('dark');
  assert.equal(runs[0].options.duration, 700, 'the snapshot animates over the chosen preset');
  const step = now => frames.splice(0).forEach(cb => cb(now));
  step(1000);
  step(1900);
  assert.deepEqual(runs[0].progress, [], 'no frame while the new theme is still being captured');
  ready = true;
  step(2000);
  step(2350);
  assert.deepEqual(runs[0].progress, [0, 0.5], 'the clock starts at the first showable frame');

  Preferences.setThemeTransitionSpeed('stroll');
  assert.equal(saved().themeTransitionSpeed, 'stroll');
  Preferences.setThemeTransitionSpeed('bogus');
  assert.equal(Preferences.state.themeTransitionSpeed, 'standard');
});
