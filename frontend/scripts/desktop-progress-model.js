// Pure progress presentation math and validated UI preferences. No DOM, clock ownership or task state.
(function () {
  'use strict';
// Presentation state only. A caller owns the authoritative progress and clock.
const clamp = (n, low = 0, high = 1) => Math.min(high, Math.max(low, n));
const normalizeProgress = n => Number.isFinite(Number(n)) ? clamp(Number(n)) : 0;

class LiquidMotion {
  constructor(value = 0) {
    this.phase = 0;
    this.reset(value);
  }

  reset(value = 0) {
    this.target = this.value = normalizeProgress(value);
    this.velocity = this.energy = 0;
  }

  setTarget(value, reducedMotion = false) {
    const next = normalizeProgress(value);
    if (reducedMotion) { this.reset(next); return; }
    const delta = Math.abs(next - this.target);
    this.target = next;
    if (delta > 0.00001) this.energy = Math.min(1, this.energy + 0.23 + delta * 2.8);
  }

  step(seconds, reducedMotion = false) {
    if (reducedMotion) { this.reset(this.target); return; }
    if (!Number.isFinite(seconds) || seconds <= 0) return;
    // Exact critically damped spring. Small fixed maximum substeps keep the
    // velocity-driven energy envelope consistent at 30 / 60 / 120 Hz.
    let remaining = Math.min(seconds, 0.12);
    while (remaining > 1e-8) {
      const dt = Math.min(remaining, 1 / 240);
      const omega = 10.5;
      const error = this.value - this.target;
      const c = this.velocity + omega * error;
      const attenuation = Math.exp(-omega * dt);
      this.value = clamp(this.target + (error + c * dt) * attenuation);
      this.velocity = (this.velocity - omega * c * dt) * attenuation;
      this.energy = clamp(this.energy * Math.exp(-dt / 0.40) + Math.abs(this.velocity) * dt * 1.45);
      this.phase += dt * (2.5 + this.energy * 2.4);
      remaining -= dt;
    }
    if (Math.abs(this.value - this.target) < 0.00004 && Math.abs(this.velocity) < 0.0003 && this.energy < 0.003) {
      this.value = this.target;
      this.velocity = this.energy = 0;
    }
  }

  get active() {
    return this.energy > 0 || Math.abs(this.value - this.target) > 0.00004 || Math.abs(this.velocity) > 0.0003;
  }
}

// Zero-mean, continuous wave front: animation does not invent extra progress.
// Displacement is a function of local height, never inverse browser/canvas zoom.
function sampleFront({ width, height, progress, energy, phase, amount = 1, samples = 96 }) {
  const p = normalizeProgress(progress);
  const count = Math.max(8, Math.round(samples));
  const values = new Float64Array(count + 1);
  const base = width * p;
  const edgeRoom = Math.min(base, width - base);
  const amplitude = Math.min(height * 0.095 * clamp(energy) * clamp(amount, 0, 1.6), edgeRoom * 0.72);
  let mean = 0;
  for (let i = 0; i <= count; i++) {
    const y = i / count;
    const wave = Math.sin(y * 14.5 - phase) * 0.62
      + Math.sin(y * 25.2 + phase * 0.77 + 1.1) * 0.25
      + Math.cos(y * 7.4 - phase * 0.53) * 0.3;
    values[i] = wave;
    mean += wave * (i === 0 || i === count ? 0.5 : 1);
  }
  mean /= count;
  for (let i = 0; i <= count; i++) values[i] = base + amplitude * (values[i] - mean);
  return values;
}


function dampFlow(flow, position, speed, target, omega, dt) {
  const displacement = flow[position] - target;
  const impulse = flow[speed] + omega * displacement;
  const decay = Math.exp(-omega * dt);
  flow[position] = target + (displacement + impulse * dt) * decay;
  flow[speed] = (flow[speed] - omega * impulse * dt) * decay;
}

// Presentation inertia only. The caller owns progress, task time and the RAF.
// Do not feed discrete progress.energy impulses into the visible wave amplitude.
class FlowMotion {
  constructor() { this.phase = 0; this.reset(); }

  reset() {
    this.energy = this.velocity = 0;
    this.driveSpeed = this.tiltSpeed = 0;
  }

  step(seconds, { running = false, velocity = 0, reduced = false } = {}) {
    if (reduced) { this.reset(); return; }
    const tilt = clamp(velocity, -1, 1);
    const drive = clamp((running ? .68 : 0) + Math.abs(tilt) * 2.2);
    let remaining = clamp(seconds, 0, .12);
    while (remaining > 1e-8) {
      const dt = Math.min(remaining, 1 / 240);
      const oldDrive = this.energy;
      // Exact critically damped response. Target jumps change acceleration,
      // never the visible amplitude/tilt or phase itself.
      dampFlow(this, 'energy', 'driveSpeed', drive, 8, dt);
      dampFlow(this, 'velocity', 'tiltSpeed', tilt, 10, dt);
      this.phase += dt * (oldDrive + this.energy) * 1.5;
      remaining -= dt;
    }
    if (!running && drive === 0 && !this.active) this.reset();
  }

  get active() {
    return this.energy > .0004 || Math.abs(this.driveSpeed) > .002
      || Math.abs(this.velocity) > .0004 || Math.abs(this.tiltSpeed) > .002;
  }
}

// Fill-only color mapping. The empty track and DOM text never pass through it.
function normalizeFillColor(value) {
  if (typeof value !== 'string') return null;
  const match = value.trim().match(/^#?([\da-f]{3}|[\da-f]{6})$/i);
  if (!match) return null;
  const hex = match[1].length === 3 ? [...match[1]].map(c => c + c).join('') : match[1];
  return `#${hex.toUpperCase()}`;
}

function fillHexRgb(hex) {
  const value = normalizeFillColor(hex);
  if (!value) throw new TypeError('Invalid fill color');
  return [1, 3, 5].map(offset => parseInt(value.slice(offset, offset + 2), 16));
}

function fillRgbHsl(rgb) {
  const [r, g, b] = rgb.map(channel => Math.max(0, Math.min(255, channel)) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
  const light = (max + min) / 2;
  if (!delta) return [0, 0, light];
  const hue = max === r ? ((g - b) / delta + 6) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return [hue / 6, delta / (1 - Math.abs(2 * light - 1)), light];
}

function fillHslRgb(hue, saturation, light) {
  const chroma = (1 - Math.abs(2 * light - 1)) * saturation;
  const h = ((hue % 1 + 1) % 1) * 6;
  const x = chroma * (1 - Math.abs(h % 2 - 1));
  const channels = h < 1 ? [chroma, x, 0] : h < 2 ? [x, chroma, 0] : h < 3 ? [0, chroma, x]
    : h < 4 ? [0, x, chroma] : h < 5 ? [x, 0, chroma] : [chroma, 0, x];
  return channels.map(value => (value + light - chroma / 2) * 255);
}

class FillTint {
  constructor(color = null, anchor = '#42B8FA') {
    this.color = normalizeFillColor(color);
    this.anchor = fillRgbHsl(fillHexRgb(anchor));
    this.target = this.color ? fillRgbHsl(fillHexRgb(this.color)) : null;
    this.cssCache = new Map();
  }

  rgb(channels) {
    if (!this.target) return channels;
    const [h, s, l] = fillRgbHsl(channels);
    const [ah, as, al] = this.anchor;
    const [th, ts, tl] = this.target;
    // Retain dimensional shading even for black/white picks. This control is
    // a material base color, not a flat replacement of every highlight pixel.
    const targetLight = Math.max(.08, Math.min(.86, tl));
    const light = l <= al ? l / Math.max(.001, al) * targetLight : targetLight + (l - al) / Math.max(.001, 1 - al) * (1 - targetLight);
    const hueOffset = ((h - ah + 1.5) % 1) - .5;
    const hue = th + Math.max(-.035, Math.min(.035, hueOffset * .35));
    return fillHslRgb(hue, Math.min(1, s * ts / Math.max(.001, as)), light);
  }

  css(hex) {
    if (!this.color) return hex;
    if (!this.cssCache.has(hex)) {
      const rgb = this.rgb(fillHexRgb(hex));
      this.cssCache.set(hex, `rgb(${rgb.map(Math.round).join(',')})`);
    }
    return this.cssCache.get(hex);
  }

  rgba(hex, alpha) {
    return `rgba(${this.rgb(fillHexRgb(hex)).map(Math.round).join(',')},${alpha})`;
  }
}

const ORIGINAL_FILL_TINT = new FillTint();

function classicFillGradient(color) {
  const tint = new FillTint(color, '#1265B5');
  return `linear-gradient(${tint.css('#74acdc')}, ${tint.css('#1265b5')} 48%, ${tint.css('#133b83')})`;
}

const PROGRESS_STYLES = Object.freeze({
  liquid: { label: '液态', english: 'Liquid', track: '#1b1f27', color: '#42B8FA' },
  slosh: { label: '晃动', english: 'Slosh', track: '#10141e', color: '#3487ED' },
  smoke: { label: '烟雾', english: 'Smoke', track: '#140f1e', color: '#D185EF' },
  drops: { label: '微滴', english: 'Drops', track: '#11160e', color: '#9DCF29' },
  bands: { label: '条带', english: 'Bands', track: '#191d23', color: '#8FABD6' },
  threads: { label: '丝线', english: 'Threads', track: '#1b101b', color: '#D15B92' },
  diamond: { label: '棋格', english: 'Diamond', track: '#1c1117', color: '#EF879A' },
  grain: { label: '颗粒', english: 'Grain', track: '#18141f', color: '#A351F0' },
  classic: { label: '经典', english: 'Classic', track: null, color: '#1265B5' },
});


const PROGRESS_HEIGHTS = Object.freeze([36, 48, 56]);
function normalizePreferences(value = {}) {
  const input = value && typeof value === 'object' ? value : {};
  const style = Object.hasOwn(PROGRESS_STYLES, input.style) ? input.style : 'liquid';
  const height = PROGRESS_HEIGHTS.includes(Number(input.height)) ? Number(input.height) : 36;
  const colors = {};
  for (const key of Object.keys(PROGRESS_STYLES)) {
    const color = normalizeFillColor(input.colors?.[key]);
    if (color) colors[key] = color;
  }
  return { style, height, colors };
}
function epochMs(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number * (number < 1e12 ? 1000 : 1) : 0;
}
function knownPercent(value) {
  if (value == null || value === '' || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) ? clamp(number, 0, 100) : null;
}
function formatElapsed(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '00:00';
  const seconds = Math.floor(ms / 1000), hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const pad = n => String(n).padStart(2, '0');
  return (hours ? pad(hours) + ':' : '') + pad(minutes) + ':' + pad(seconds % 60);
}
function normalizeDisplay(value = {}) {
  const text = (v, limit = 500) => String(v ?? '').slice(0, limit);
  const visible = value.visible === true;
  return {
    visible, running: visible && value.running === true,
    taskId: text(value.taskId, 200), percent: knownPercent(value.percent),
    title: text(value.title || '处理中'), detail: text(value.detail),
    valueLabel: text(value.valueLabel, 40),
    startedAt: epochMs(value.startedAt), finishedAt: epochMs(value.finishedAt),
    elapsedText: text(value.elapsedText, 32),
  };
}
function elapsedLabel(display, now) {
  if (display.elapsedText) return display.elapsedText;
  if (!display.startedAt) return '—';
  const end = display.finishedAt || (display.running ? now : display.startedAt);
  return formatElapsed(Math.max(0, end - display.startedAt));
}
window.DesktopProgressModel = Object.freeze({
  clamp, normalizeProgress, LiquidMotion, FlowMotion, sampleFront,
  normalizeFillColor, FillTint, ORIGINAL_FILL_TINT, classicFillGradient,
  PROGRESS_STYLES, PROGRESS_HEIGHTS, normalizePreferences, epochMs,
  knownPercent, formatElapsed, normalizeDisplay, elapsedLabel,
});

})();
