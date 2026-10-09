// Paint-only progress renderer. Dimensions are node-local CSS pixels, not inverse canvas zoom.
(function () {
  'use strict';
const { clamp, sampleFront, PROGRESS_STYLES, FillTint, normalizeFillColor, ORIGINAL_FILL_TINT } = window.DesktopProgressModel;
const { PatternEffects, FlowEffects, SLOSH_STOPS, sloshGradientExtent, createBlueFillGradient } = window.DesktopProgressMaterials;

// Cached color / falloff tables, not per-pixel trigonometry or full-bar filters.
// Same colors as the vector body, ordered by distance back from the liquid
// surface. A narrow front tile adds refraction without a dark back seam.
const PALETTE = [...SLOSH_STOPS].reverse().map(([offset, hex]) => [
  1 - offset, ...hex.slice(1).match(/../g).map(channel => parseInt(channel, 16)),
]);
const COLOR_STEPS = 2048;
function liquidColorLookup(tint) {
  const stops = PALETTE.map(([offset, ...rgb]) => [offset, ...tint.rgb(rgb)]);
  const table = new Float32Array((COLOR_STEPS + 1) * 3);
  for (let i = 0; i <= COLOR_STEPS; i++) {
    const x = i / COLOR_STEPS;
    let stop = 0;
    while (stop < stops.length - 2 && x > stops[stop + 1][0]) stop++;
    const a = stops[stop], b = stops[stop + 1];
    const f = clamp((x - a[0]) / (b[0] - a[0]));
    for (let channel = 0; channel < 3; channel++) table[i * 3 + channel] = a[channel + 1] + (b[channel + 1] - a[channel + 1]) * f;
  }
  return table;
}
const COLOR_LUT = liquidColorLookup(ORIGINAL_FILL_TINT);
const FALLOFF_LUT = Float32Array.from({ length: 512 }, (_, i) => Math.exp(-((i / 130) ** 2)));
const halo = n => {
  const index = Math.min(511, Math.abs(n) * 130), lo = Math.floor(index);
  return FALLOFF_LUT[lo] + (FALLOFF_LUT[Math.min(511, lo + 1)] - FALLOFF_LUT[lo]) * (index - lo);
};

class ProgressRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext('2d', { alpha: false });
    this.effects = new PatternEffects();
    this.flow = new FlowEffects();
    this.tile = document.createElement('canvas');
    this.tileContext = this.tile.getContext('2d');
    if (!this.context || !this.tileContext) throw new Error('Canvas2D unavailable');
    this.width = this.height = 0;
    this.image = null;
    this.fillKey = '';
    this.tint = ORIGINAL_FILL_TINT;
    this.colorLookup = COLOR_LUT;
    this.foldLight = [100, 150, 100];
  }

  prepareFill(style, color) {
    const normalized = normalizeFillColor(color);
    const key = `${style}/${normalized || 'original'}`;
    if (this.fillKey === key) return;
    this.fillKey = key;
    this.tint = normalized ? new FillTint(normalized, PROGRESS_STYLES[style].color) : ORIGINAL_FILL_TINT;
    if (style === 'liquid') {
      this.colorLookup = normalized ? liquidColorLookup(this.tint) : COLOR_LUT;
      this.foldLight = normalized ? this.tint.rgb([159, 236, 255]).map(c => c * .59) : [100, 150, 100];
    }
  }

  resize(width, height, pixelRatio = window.devicePixelRatio || 1) {
    this.width = Math.max(1, width);
    this.height = Math.max(1, height);
    this.dpr = clamp(pixelRatio, 1, 2);
    const w = Math.ceil(this.width * this.dpr), h = Math.ceil(this.height * this.dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    // Rasterize only the glowing front, capped at 1.5x; the full canvas and
    // overlay text remain high-DPI. The idle frame allocates nothing afterward.
    this.tileScale = Math.min(this.dpr, 1.5);
    const tw = Math.ceil(this.height * 1.84 * this.tileScale) + 8;
    const th = Math.ceil(this.height * this.tileScale);
    if (this.tile.width !== tw || this.tile.height !== th || !this.image) {
      this.tile.width = tw;
      this.tile.height = th;
      this.image = this.tileContext.createImageData(tw, th);
    }
  }

  draw(motion, amount = 1, style = 'liquid', fillColor = null, flowMotion = null) {
    const ctx = this.context;
    if (!ctx || !this.image || !Object.hasOwn(PROGRESS_STYLES, style)) return;
    this.prepareFill(style, fillColor);
    if (style === 'slosh' || style === 'smoke') {
      const material = flowMotion ? { value: motion.value, energy: flowMotion.energy, phase: flowMotion.phase, velocity: flowMotion.velocity } : motion;
      this.flow.draw(ctx, this.width, this.height, this.dpr, style, material, amount, this.tint, PROGRESS_STYLES[style].track);
      return;
    }
    if (style !== 'liquid') {
      this.effects.draw(ctx, this.width, this.height, this.dpr, style, motion, amount, this.tint);
      return;
    }
    const w = this.width, h = this.height;
    const p = clamp(motion.value);
    // Like Slosh/Smoke, all Liquid geometry AND lighting read the continuous
    // material drive, never the discrete progress.energy/phase impulses.
    const { energy, phase } = flowMotion || motion;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = '#1b1f27';
    ctx.fillRect(0, 0, w, h);
    if (p > 0) {
      const front = sampleFront({ width: w, height: h, progress: p, energy, phase, amount });
      const [, gradientEnd] = sloshGradientExtent(w, h, p);
      ctx.fillStyle = createBlueFillGradient(ctx, w, h, p, this.tint);
      ctx.beginPath();
      ctx.moveTo(0, 0);
      for (let i = 0; i < front.length; i++) ctx.lineTo(front[i], h * i / (front.length - 1));
      ctx.lineTo(0, h);
      ctx.closePath();
      ctx.fill();

      const scale = this.tileScale;
      const tw = this.tile.width, th = this.tile.height;
      const depth = h * 1.43;
      const tileLeft = w * p - h * 1.60;
      const pixels = this.image.data;
      const vigor = energy * clamp(amount, 0, 1.6);
      for (let row = 0; row < th; row++) {
        const y = (row + 0.5) / scale;
        const unitY = y / h;
        const index = clamp(unitY) * (front.length - 1);
        const lo = Math.floor(index), hi = Math.min(front.length - 1, lo + 1);
        const edge = front[lo] + (front[hi] - front[lo]) * (index - lo);
        const slope = (front[hi] - front[Math.max(0, lo - 1)]) / (2 * h / (front.length - 1));
        const normal = 1 / Math.sqrt(1 + slope * slope * 0.7);
        const foldA = h * (0.13 + Math.sin(unitY * 14.0 - phase * 0.8) * 0.045);
        const foldB = h * (0.37 + Math.cos(unitY * 18.2 + phase * 0.6) * 0.082);
        const light = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(unitY * 15.5 - phase));
        const warp = h * vigor * 0.10 * Math.sin(unitY * 15.2 + phase * 0.62);
        for (let col = 0; col < tw; col++) {
          const o = (row * tw + col) * 4;
          const x = tileLeft + (col + 0.5) / scale;
          const d = edge - x;
          const alpha = clamp(d * scale + 0.5);
          if (alpha <= 0 || d > depth + 2) { pixels[o + 3] = 0; continue; }
          const normalized = clamp(d / depth);
          // Follow the surface normal near the rim, but fade that correction
          // into the body. Otherwise steep lobes leave a hard-edged back seam.
          const normalMix = 1 - (1 - normal) * Math.max(0, 1 - d / (h * 0.30));
          const frontMix = (1 - normalized) ** 2;
          const bodyDistance = gradientEnd - x;
          const surfaceDistance = d * normalMix + warp * normalized * (1 - normalized);
          const distance = bodyDistance + (surfaceDistance - bodyDistance) * frontMix;
          const lut = Math.round(clamp(distance / gradientEnd) * COLOR_STEPS) * 3;
          const folds = vigor * light * (
            halo((d - foldA) / (h * 0.052)) * 0.38 +
            halo((d - foldB) / (h * 0.073)) * 0.24
          );
          const grain = ((col * 17 + row * 37) % 7 - 3) * 0.25;
          pixels[o] = this.colorLookup[lut] + folds * this.foldLight[0] + grain;
          pixels[o + 1] = this.colorLookup[lut + 1] + folds * this.foldLight[1] + grain;
          pixels[o + 2] = this.colorLookup[lut + 2] + folds * this.foldLight[2] + grain;
          const backFade = 1 - clamp((normalized - .72) / .28);
          pixels[o + 3] = Math.round(alpha * backFade * backFade * (3 - 2 * backFade) * 255);
        }
      }
      this.tileContext.putImageData(this.image, 0, 0);
      ctx.drawImage(this.tile, tileLeft, 0, tw / scale, h);
    }
    // No black bottom glaze: the long blue gradient remains visible throughout
    // the filled body, and the unfilled track keeps its own exact color.
  }

  destroy() {
    this.effects.destroy();
    this.flow.destroy();
    this.image = null;
    this.tint = ORIGINAL_FILL_TINT;
    this.colorLookup = COLOR_LUT;
    this.fillKey = '';
    this.canvas.width = this.canvas.height = 1;
    this.tile.width = this.tile.height = 1;
  }
}

window.DesktopProgressRenderer = Object.freeze({ ProgressRenderer });
})();
