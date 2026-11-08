const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function load({ viewTransitions = true } = {}) {
  const log = [];
  const animations = [];
  const transitions = [];
  const element = tag => ({
    tag,
    dataset: {},
    style: {},
    attributes: {},
    isConnected: false,
    setAttribute(name, value) { this.attributes[name] = value; },
    getAttribute(name) { return this.attributes[name]; },
    remove() { this.isConnected = false; log.push(['remove', this.className || this.attributes.class || tag]); },
    getContext: () => ({
      createImageData: (w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }),
      putImageData: image => { if (!image || !image.data) throw new TypeError('not ImageData'); log.push(['putImageData']); },
      setTransform() {}, clearRect() {}, save() {}, restore() {}, clip() {}, stroke() {},
    }),
    toDataURL: () => 'data:image/png;base64,MAP',
  });
  const feImage = element('feImage');
  const documentElement = {
    dataset: {},
    animate(keyframes, options) {
      const animation = {
        keyframes, options, currentTime: 0, playState: 'running',
        pause() { this.playState = 'paused'; },
        cancel() { this.playState = 'idle'; log.push(['cancel', options.pseudoElement]); },
      };
      animations.push(animation);
      return animation;
    },
  };
  const document = {
    documentElement,
    body: { appendChild(node) { node.isConnected = true; log.push(['append', node.className || node.attributes.class]); } },
    createElement: tag => element(tag),
    createElementNS: (ns, tag) => {
      const svg = element(tag);
      Object.defineProperty(svg, 'innerHTML', { set(value) { svg.markup = value; } });
      svg.querySelector = selector => (selector === 'feImage' ? feImage : null);
      return svg;
    },
  };
  if (viewTransitions) {
    document.startViewTransition = update => {
      const ready = deferred();
      const finished = deferred();
      const transition = {
        update, ready, finished,
        skipped: false,
        skipTransition() { this.skipped = true; finished.resolve(); },
        get readyPromise() { return ready.promise; },
      };
      transitions.push(transition);
      return { ready: ready.promise, finished: finished.promise, skipTransition: () => transition.skipTransition() };
    };
  }
  const window = {
    innerWidth: 1000,
    innerHeight: 600,
    devicePixelRatio: 1,
    CSS: { supports: () => true },
  };
  const sandbox = {
    window, document,
    Path2D: class { constructor(d) { this.d = d; } },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
  };
  vm.runInNewContext(read('frontend/scripts/desktop-theme-ripple.js'), sandbox);
  vm.runInNewContext(read('frontend/scripts/desktop-theme-ripple-snapshot.js'), sandbox);
  return { Snapshot: window.DesktopThemeRippleSnapshot, Ripple: window.DesktopThemeRipple, document, log, animations, transitions, feImage };
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const ease = p => p;

test('the displacement map pushes only a ring around the edge and stays neutral elsewhere', () => {
  const { Snapshot } = load();
  const field = Snapshot.createField({ x: 500, y: 300 }, 1000, 600, 100);
  assert.deepEqual([field.columns, field.rows], [100, 60]);
  const radii = new Float32Array(360).fill(200);
  const data = Snapshot.fillDisplacement(field, radii, 1, new Uint8ClampedArray(100 * 60 * 4), 40);
  const at = (x, y) => { const i = (Math.floor(y / 10) * 100 + Math.floor(x / 10)) * 4; return [data[i], data[i + 1], data[i + 2], data[i + 3]]; };
  assert.deepEqual(at(505, 305), [128, 128, 128, 255], 'the click point is untouched');
  assert.deepEqual(at(995, 305), [128, 128, 128, 255], 'far outside the ring is untouched');
  const inside = at(675, 305);   // ~175px from the centre: just inside the edge, pushed outward
  const outside = at(725, 305);  // ~225px: just outside, pulled back inward
  assert.ok(inside[0] > 140 && outside[0] < 116, `${inside[0]} / ${outside[0]}`);
  const silent = Snapshot.fillDisplacement(field, radii, 0, new Uint8ClampedArray(100 * 60 * 4), 40);
  assert.ok(silent.every((value, index) => (index % 4 === 3 ? value === 255 : value === 128)), 'zero strength is a neutral map');
});

test('clip keyframes trace the wobbling outline from nothing to past the corners', () => {
  const { Snapshot } = load();
  const frames = Snapshot.clipKeyframes({ x: 0, y: 0 }, 1200, 1400, ease, [0, 0, 0], 4);
  assert.equal(frames.length, 5);
  assert.ok(frames.every(frame => /^path\("M.+Z"\)$/.test(frame.clipPath)));
  assert.match(frames[0].clipPath, /^path\("M0 0Q0 0 0 0/, 'starts as a point at the origin');
  assert.notEqual(frames[2].clipPath, frames[3].clipPath);
});

test('a snapshot run applies the theme in the transition, scrubs the clip and cleans up', async () => {
  const { Snapshot, document, log, animations, transitions, feImage } = load();
  assert.equal(Snapshot.supported(), true);
  assert.equal(load({ viewTransitions: false }).Snapshot.supported(), false);
  let applied = 0;
  const run = Snapshot.create({ origin: { x: 980, y: 20 }, endRadius: 1000, fromTheme: 'light', duration: 1400, ease, apply: () => { applied += 1; }, phases: [0, 0, 0] });
  assert.equal(document.documentElement.dataset.themeRipple, 'snapshot');
  assert.equal(run.canvas.style.viewTransitionName, Snapshot.EDGE_NAME);
  run.frame(0.1, 0.1, 0.14);
  assert.equal(animations.length, 0, 'frames before ready are buffered');
  transitions[0].update();
  assert.equal(applied, 1);
  assert.equal(run.canvas.isConnected, true, 'the edge joins the new state inside the update callback');
  transitions[0].ready.resolve();
  await flush();
  const [hold, clip] = animations;
  assert.equal(hold.options.pseudoElement, '::view-transition-group(root)');
  assert.ok(hold.options.duration > 1400, 'the hold outlives the run');
  assert.equal(clip.options.pseudoElement, '::view-transition-new(root)');
  assert.equal(clip.playState, 'paused');
  assert.equal(clip.currentTime, 140, 'the buffered frame is replayed once ready');
  assert.equal(feImage.getAttribute('href'), 'data:image/png;base64,MAP');
  run.frame(0.5, 0.5, 0.7);
  assert.equal(clip.currentTime, 700);
  run.dispose();
  assert.equal(transitions[0].skipped, true);
  assert.equal(clip.playState, 'idle');
  assert.equal(document.documentElement.dataset.themeRipple, undefined);
  assert.equal(run.canvas.isConnected, false);
  assert.ok(log.some(([name, what]) => name === 'remove' && what === 'desk-theme-ripple-filter'));
  run.frame(0.9, 0.9, 1.2);
  assert.equal(clip.currentTime, 700, 'frames after dispose are ignored');
});

test('a run disposed before its update callback still applies the theme but mounts nothing', async () => {
  const { Snapshot, transitions } = load();
  let applied = 0;
  const run = Snapshot.create({ origin: { x: 0, y: 0 }, endRadius: 500, duration: 1400, ease, apply: () => { applied += 1; } });
  run.dispose();
  transitions[0].update();
  assert.equal(applied, 1);
  assert.equal(run.canvas.isConnected, false);
});

test('preferences prefer the snapshot path, fall back to the overlay and never freeze', () => {
  const preferences = read('frontend/scripts/desktop-preferences.js');
  assert.match(preferences, /const useSnapshot = Boolean\(snapshot\?\.supported\?\.\(\)\);/);
  assert.match(preferences, /apply: \(\) => \{\n\s*if \(state\.theme === targetTheme\) applyTheme\(targetTheme\);/);
  assert.match(preferences, /if \(!useSnapshot\) applyTheme\(targetTheme\);/);
  assert.match(preferences, /catch \(error\) \{\n\s*\/\/ Never leave the page frozen mid-reveal[^\n]*\n\s*finishThemeReveal\(run, true\);/);

  const liquid = read('frontend/styles/desktop-liquid.css');
  assert.match(liquid, /:root\[data-theme-ripple="snapshot"\]::view-transition-old\(root\),\n:root\[data-theme-ripple="snapshot"\]::view-transition-new\(root\) \{[^}]*animation: none;[^}]*mix-blend-mode: normal;[^}]*filter: url\(#deskThemeRippleRefraction\);/);
  assert.match(read('frontend/styles/desktop-geometry.css'), /body\.desk-app \.desk-theme-ripple-filter \{[^}]*position: fixed;/);

  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-theme-ripple-snapshot.js'));
  const at = file => html.indexOf(`scripts/${file}?v=`);
  assert.ok(at('desktop-theme-ripple.js') < at('desktop-theme-ripple-snapshot.js'));
  assert.ok(at('desktop-theme-ripple-snapshot.js') < at('desktop-preferences.js'));
});
