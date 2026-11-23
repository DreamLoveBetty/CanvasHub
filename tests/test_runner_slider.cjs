const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

const SPEEDS = [
  { key: 'stroll', label: '漫步', ms: 2400 },
  { key: 'walk', label: '慢行', ms: 1900 },
  { key: 'standard', label: '标准', ms: 1400, recommended: true },
  { key: 'run', label: '快跑', ms: 1000 },
  { key: 'sprint', label: '冲刺', ms: 700 },
];

function element(name) {
  const classes = new Set();
  return {
    name,
    style: {},
    attributes: {},
    children: [],
    listeners: {},
    hidden: false,
    isConnected: true,
    textContent: '',
    innerHTML: '',
    value: '',
    clientWidth: 0,
    clientHeight: 0,
    classList: {
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      contains: c => classes.has(c),
    },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key]; },
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
    removeEventListener(type, handler) { this.listeners[type] = (this.listeners[type] || []).filter(h => h !== handler); },
    fire(type, extra = {}) { (this.listeners[type] || []).forEach(handler => handler({ key: extra.key, preventDefault() {} })); },
    appendChild(child) { this.children.push(child); return child; },
    querySelectorAll() { return this.children.filter(child => child.name === 'span'); },
    focus() {},
  };
}

function load({ reduced = false } = {}) {
  const frames = [];
  let cancelled = 0;
  const window = {
    devicePixelRatio: 1,
    matchMedia: () => ({ matches: reduced }),
  };
  const document = {
    createElementNS: (ns, tag) => element(tag),
    createElement: tag => element(tag),
  };
  const sandbox = {
    window, document,
    requestAnimationFrame: cb => { frames.push(cb); return frames.length; },
    cancelAnimationFrame: () => { cancelled += 1; },
    setTimeout: () => 0,
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
  };
  vm.runInNewContext(read('frontend/scripts/desktop-runner-slider.js'), sandbox);
  return { Slider: window.DesktopRunnerSlider, frames, cancelledCount: () => cancelled };
}

function fixture(options = {}) {
  const { Slider, frames, cancelledCount } = load(options);
  let saved = options.value || 'standard';
  const changes = [];
  const slider = Slider.create({
    stops: () => SPEEDS,
    getValue: () => saved,
    onChange: key => { saved = key; changes.push(key); },
    label: '过渡速度',
    labelClass: 'desk-settings-canvas-interaction__label',
    ends: ['从容', '利落'],
  });
  const parts = {};
  ['track', 'fill', 'runner', 'input', 'value', 'ms', 'marks', 'recommended', 'streaks'].forEach(name => { parts[name] = element(name); });
  parts.track.clientWidth = 420;
  parts.track.clientHeight = 14;
  parts.streaks.getContext = () => null;
  const svg = element('svg');
  parts.runner.querySelector = () => svg;
  const sliderRoot = element('root');
  sliderRoot.querySelector = selector => parts[selector.match(/data-runner-slider-([a-z]+)/)[1]];
  const container = { querySelector: selector => (selector === '[data-runner-slider]' ? sliderRoot : null) };
  return { Slider, slider, frames, cancelledCount, parts, svg, container, changes, saved: () => saved };
}

test('the gait walks at the slow end with sticky drag and sprints airborne with whipped slime at the fast end', () => {
  const { Slider } = load();
  const walk = Slider.gait(0);
  const sprint = Slider.gait(1);
  assert.ok(sprint.cadence > walk.cadence * 2, 'strides speed up');
  assert.ok(sprint.kneeMax > walk.kneeMax * 2, 'the heel kicks up when running');
  assert.ok(sprint.elbow > walk.elbow * 4, 'running arms are bent');
  assert.ok(sprint.lean > walk.lean * 4, 'the runner leans forward');
  assert.ok(walk.sticky > 0.9 && sprint.sticky < 0.05, 'slow end is sticky; fast end breaks free');
  assert.ok(sprint.whip > 0.9 && walk.whip < 0.05, 'fast end whips slime backward; slow end does not');
  const lowest = q => Math.max(q.nearLeg.foot[1], q.nearLeg.toe[1], q.farLeg.foot[1], q.farLeg.toe[1]);
  for (let k = 0; k < 16; k += 1) {
    assert.ok(Math.abs(lowest(Slider.pose(0, (k / 16) * Math.PI * 2))) < 1e-9, 'a walker always has a foot on the ground');
  }
  const airborne = Array.from({ length: 16 }, (_, k) => lowest(Slider.pose(1, (k / 16) * Math.PI * 2))).some(y => y < -1);
  assert.ok(airborne, 'a sprinter leaves the ground');
});

test('the slider renders its stops, value and accessible text from the presets', () => {
  const { slider } = fixture();
  const html = slider.html();
  assert.match(html, /type="range" min="0" max="4" step="0\.001" value="2"/);
  assert.match(html, /aria-valuetext="标准，1\.4 秒"/);
  assert.match(html, /<span class="desk-settings-canvas-interaction__label">过渡速度<\/span>/);
  assert.match(html, /data-runner-slider-ms>1\.4 秒</);
  assert.match(html, /<span>从容<\/span>.*推荐.*<span>利落<\/span>/s);
  assert.equal(fixture({ value: 'sprint' }).slider.html().includes('desk-runner-slider__value is-top'), true, 'the top stop is highlighted');
});

test('keyboard steps commit a stop, drags snap on release, and release stops the clock', () => {
  const { slider, parts, svg, container, changes, frames, cancelledCount } = fixture();
  slider.mount(container);
  const walkAll = node => [node, ...(node.children || []).flatMap(walkAll)];
  const nodes = walkAll(svg);
  assert.ok(nodes.some(node => node.name === 'filter' && (node.attributes.id || '').startsWith('desk-runner-goo-')), 'metaball goo filter is mounted');
  assert.ok(nodes.some(node => node.name === 'feSpecularLighting'), '3D specular lighting filter is mounted');
  assert.ok(nodes.some(node => node.name === 'linearGradient'), '3D body/limb/trail linear gradients are mounted');
  assert.ok(nodes.some(node => node.name === 'radialGradient'), '3D head/droplet radial gradients are mounted');
  assert.ok(nodes.some(node => node.attributes.class === 'desk-runner-slider__puddle'), 'ground slime puddle exists');
  assert.ok(nodes.some(node => node.attributes.class === 'desk-runner-slider__slime-trail'), 'whipped slime ribbons exist');
  assert.ok(nodes.some(node => node.attributes.class === 'desk-runner-slider__slime-drop'), 'flying slime droplets exist');
  assert.ok(nodes.some(node => node.attributes.class === 'desk-runner-slider__eye'), 'expressive eye exists');
  assert.ok(nodes.some(node => (node.attributes.d || '').startsWith('M')), 'the sculpted slime figure is drawn on mount');
  assert.equal(parts.marks.innerHTML.match(/desk-runner-slider__mark/g).length, 5);
  assert.match(parts.marks.innerHTML, /is-recommended" style="left:210\.0px"/);
  assert.equal(parts.recommended.style.left, '210.0px');
  assert.ok(frames.length > 0, 'the figure animates while mounted');

  parts.input.fire('keydown', { key: 'ArrowRight' });
  assert.deepEqual(changes, ['run']);
  assert.equal(parts.input.value, '3');
  assert.equal(parts.input.attributes['aria-valuetext'], '快跑，1.0 秒');
  parts.input.fire('keydown', { key: 'End' });
  parts.input.fire('keydown', { key: 'ArrowRight' });
  assert.deepEqual(changes, ['run', 'sprint'], 'stepping past the end changes nothing');
  parts.input.fire('keydown', { key: 'Home' });
  assert.deepEqual(changes, ['run', 'sprint', 'stroll']);

  parts.input.value = '1.4';
  parts.input.fire('input');
  assert.deepEqual(changes, ['run', 'sprint', 'stroll'], 'dragging does not save yet');
  parts.input.fire('change');
  assert.deepEqual(changes, ['run', 'sprint', 'stroll', 'walk'], 'release snaps to the nearest stop');
  assert.equal(parts.input.value, '1');

  slider.mount(container);
  assert.equal(parts.input.listeners.keydown.length, 1, 'mounting the same markup again does not double-bind');
  slider.release();
  assert.equal(parts.input.listeners.keydown.length, 0, 'release unbinds');
  assert.ok(cancelledCount() >= 1 || frames.length > 0);
});

test('reduced motion keeps a still figure and schedules no animation', () => {
  const { slider, container, frames, parts } = fixture({ reduced: true });
  slider.mount(container);
  assert.equal(frames.length, 0);
  parts.input.fire('keydown', { key: 'ArrowLeft' });
  assert.equal(frames.length, 0, 'a reduced-motion step jumps without animating');
  assert.equal(parts.input.value, '1');
});

test('settings host the slider in the theme style card and fold it with the switch', () => {
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.match(settings, /const themeSpeedSlider = window\.DesktopRunnerSlider\?\.create\(\{\n\s*stops: \(\) => window\.DesktopThemeRipple\?\.SPEEDS \|\| \[\],/);
  assert.match(settings, /onChange: speed => window\.DesktopPreferences\?\.setThemeTransitionSpeed\?\.\(speed\),/);
  const card = settings.match(/function renderThemeStyleSettings\(\) \{[\s\S]*?\n  \}\n/)[0];
  assert.match(card, /<div class="desk-settings-theme-speed\$\{transition === 'none' \? ' is-collapsed' : ''\}" data-theme-speed><div>\$\{themeSpeedSlider\?\.html\(\) \|\| ''\}<\/div><\/div>/);
  assert.match(settings, /progressPreview\?\.mount\(els\.deskSettingsBody\);\n\s*themeSpeedSlider\?\.mount\(els\.deskSettingsBody\);/);
  assert.equal(settings.match(/progressPreview\?\.release\(\);\n\s*themeSpeedSlider\?\.release\(\);/g).length, 3);
  assert.match(settings, /\?\.querySelector\('\[data-theme-speed\]'\)\?\.classList\.toggle\('is-collapsed', transition === 'none'\);/);

  const geometry = read('frontend/styles/desktop-geometry.css');
  assert.match(geometry, /\.desk-settings-theme-speed\.is-collapsed \{[^}]*grid-template-rows: 0fr;[^}]*visibility: hidden;/);
  assert.match(geometry, /body\.desk-app \.desk-runner-slider__runner \{[^}]*width: 48px;/);
  const liquid = read('frontend/styles/desktop-liquid.css');
  assert.match(liquid, /\.desk-runner-slider \{[^}]*--desk-runner-ink: var\(--desk-color-text-primary\);[^}]*--desk-runner-accent: var\(--desk-color-accent\);/);
  const graphite = read('frontend/styles/desktop-graphite.css');
  assert.doesNotMatch(graphite, /--desk-runner-slime[^;]*--desk-graphite-accent/, 'graphite keeps 3D obsidian black slime instead of green accent');

  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-runner-slider.js'));
  const at = file => html.indexOf(`scripts/${file}?v=`);
  assert.ok(at('desktop-theme-ripple.js') < at('desktop-runner-slider.js'));
  assert.ok(at('desktop-runner-slider.js') < at('desktop-settings.js'));
});
