// Canvas2D materials from the accepted standalone study. Bounded reusable textures; no RAF or tasks.
(function () {
  'use strict';
const { clamp, normalizeProgress, ORIGINAL_FILL_TINT, PROGRESS_STYLES } = window.DesktopProgressModel;

// Deterministic across frames and sizes: the material never randomly flickers.
function materialNoise(index, salt = 0) {
  let x = (Math.imul(index + 1, 0x45d9f3b) ^ Math.imul(salt + 1, 0x27d4eb2d)) >>> 0;
  x = Math.imul(x ^ (x >>> 16), 0x45d9f3b) >>> 0;
  x = (x ^ (x >>> 16)) >>> 0;
  return x / 4294967296;
}

function materialFront({ progress, width, height, index, energy = 0, phase = 0, amount = 1, spread = 0.12 }) {
  const p = clamp(progress);
  if (p === 0 || p === 1) return p * width;
  const room = Math.min(width * p, width * (1 - p));
  const amplitude = Math.min(height * spread, room * 0.85);
  const fixed = (materialNoise(index, 11) - .5) * .6;
  const wave = Math.sin(index * 1.79 + phase * 1.18) * .60 + Math.cos(index * .37 - phase * .8) * .25;
  return clamp(width * p + amplitude * (fixed + wave * clamp(energy) * clamp(amount, 0, 1.6)), 0, width);
}

function materialGeometry(width, height) {
  return {
    bands: 10,
    threadGap: Math.max(1.45, height / 65),
    cellSize: Math.max(5, height / 10),
    feather: Math.min(width * .15, height * .36),
  };
}

// Shares the explicit drawing surface from the renderer. Only one cached
// texture per preview is retained; no additional RAF or hidden live canvases.
class PatternEffects {
  constructor() { this.texture = null; this.key = ''; }

  destroy() {
    if (this.texture) this.texture.width = this.texture.height = 1;
    this.texture = null;
    this.key = '';
  }

  textureFor(kind, width, height, pixelRatio, tint = ORIGINAL_FILL_TINT) {
    const ratio = Math.min(pixelRatio, 1.5);
    const key = `${kind}/${width}/${height}/${ratio}/${tint.color || 'original'}`;
    if (key === this.key) return this.texture;
    this.destroy();
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(width * ratio);
    canvas.height = Math.ceil(height * ratio);
    const ctx = canvas.getContext('2d');
    if (kind === 'grain') {
      const image = ctx.createImageData(canvas.width, canvas.height);
      const pixels = image.data;
      // A small lookup table per new texture, never per-pixel HSL on active
      // frames. Both texture size and color participate in cache invalidation.
      let tintedGrain = null;
      if (tint.color) {
        tintedGrain = new Float32Array(256 * 16 * 3);
        for (let a = 0; a < 256; a++) {
          for (let s = 0; s < 16; s++) {
            tintedGrain.set(tint.rgb([65 + a / 255 * 98 + s / 15 * 82, 26 + a / 255 * 55 + s / 15 * 154, 110 + a / 255 * 130 + s / 15 * 50]), (a * 16 + s) * 3);
          }
        }
      }
      for (let i = 0; i < pixels.length / 4; i++) {
        const a = materialNoise(i, 5), b = materialNoise(i, 9);
        const sparkle = b > .968 ? (b - .968) / .032 : 0;
        if (tintedGrain) {
          const offset = (Math.round(a * 255) * 16 + Math.round(sparkle * 15)) * 3;
          pixels[i * 4] = tintedGrain[offset];
          pixels[i * 4 + 1] = tintedGrain[offset + 1];
          pixels[i * 4 + 2] = tintedGrain[offset + 2];
        } else {
          pixels[i * 4] = 65 + a * 98 + sparkle * 82;
          pixels[i * 4 + 1] = 26 + a * 55 + sparkle * 154;
          pixels[i * 4 + 2] = 110 + a * 130 + sparkle * 50;
        }
        pixels[i * 4 + 3] = 255;
      }
      ctx.putImageData(image, 0, 0);
    } else {
      ctx.scale(ratio, ratio);
      ctx.fillStyle = tint.css('#13210b');
      ctx.fillRect(0, 0, width, height);
      const spacing = Math.max(1.55, height / 70);
      const columns = Math.ceil(width / spacing), rows = Math.ceil(height / spacing);
      const palette = ['#558f17', '#9dcf29', '#c8f65a', '#dafa79', '#7db923', '#ebffb1'].map(color => tint.css(color));
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < columns; x++) {
          const index = y * columns + x;
          const density = materialNoise(index, 2);
          if (density < .16) continue;
          const dx = (x + materialNoise(index, 8)) * spacing;
          const dy = (y + materialNoise(index, 10)) * spacing;
          ctx.fillStyle = palette[Math.floor(materialNoise(index, 3) * palette.length)];
          const size = .43 + materialNoise(index, 1) * .54;
          ctx.fillRect(dx, dy, size, size * (1.1 + density));
        }
      }
    }
    this.texture = canvas;
    this.key = key;
    return canvas;
  }

  draw(ctx, width, height, pixelRatio, kind, motion, amount, tint = ORIGINAL_FILL_TINT) {
    const style = PROGRESS_STYLES[kind];
    if (!style || kind === 'classic' || kind === 'liquid') return;
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = style.track;
    ctx.fillRect(0, 0, width, height);
    const p = clamp(motion.value);
    if (p <= 0) return;
    const args = { ctx, width, height, motion, amount, p, tint };
    if (kind === 'bands') this.bands(args);
    else if (kind === 'threads') this.threads(args);
    else if (kind === 'diamond') this.diamond(args);
    else this.textured({ ...args, pixelRatio, kind });
    ctx.globalAlpha = 1;
    // Gentle center shade protects overlaid white text on luminous textures.
    const glaze = ctx.createLinearGradient(0, 0, 0, height);
    glaze.addColorStop(0, 'rgba(0,0,0,0)');
    glaze.addColorStop(.47, 'rgba(1,5,14,.16)');
    glaze.addColorStop(1, 'rgba(0,0,0,.035)');
    ctx.fillStyle = glaze;
    ctx.fillRect(0, 0, width, height);
  }

  bands({ ctx, width, height, motion, amount, p, tint }) {
    const rows = materialGeometry(width, height).bands;
    const step = height / rows;
    for (let row = 0; row < rows; row++) {
      const edge = materialFront({ width, height, progress: p, index: row, energy: motion.energy, phase: motion.phase, amount, spread: .14 });
      const depth = Math.min(edge, height * 1.6);
      const gradient = ctx.createLinearGradient(edge - depth, 0, edge, 0);
      gradient.addColorStop(0, tint.css('#090f1c'));
      gradient.addColorStop(.35, tint.css('#14253f'));
      gradient.addColorStop(.68, tint.css('#405e84'));
      gradient.addColorStop(.90, tint.css(row % 3 === 0 ? '#b8d3f4' : '#8fabd6'));
      gradient.addColorStop(1, tint.css('#e0f2ff'));
      ctx.fillStyle = gradient;
      ctx.fillRect(0, row * step, edge, step + .25);
      const shine = .3 + materialNoise(row, 5) * .55;
      ctx.fillStyle = tint.rgba('#eff8ff', shine);
      const tipWidth = Math.min(edge, Math.max(1, height * .026));
      ctx.fillRect(edge - tipWidth, row * step, tipWidth, step + .25);
    }
  }

  threads({ ctx, width, height, motion, amount, p, tint }) {
    const gap = materialGeometry(width, height).threadGap;
    const rows = Math.ceil(height / gap);
    for (let row = 0; row < rows; row++) {
      const edge = materialFront({ width, height, progress: p, index: row, energy: motion.energy, phase: motion.phase, amount, spread: .29 });
      const y = row * gap + gap * .5;
      const depth = Math.min(edge, height * .93);
      const gradient = ctx.createLinearGradient(Math.max(0, edge - depth), 0, edge, 0);
      gradient.addColorStop(0, tint.css('#823247'));
      gradient.addColorStop(.64, tint.css('#d15b92'));
      gradient.addColorStop(.9, tint.css('#f295c5'));
      gradient.addColorStop(1, tint.css('#fff0fa'));
      ctx.strokeStyle = gradient;
      ctx.globalAlpha = .12;
      ctx.lineWidth = gap * 1.3;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(edge, y); ctx.stroke();
      ctx.globalAlpha = .56 + materialNoise(row, 12) * .42;
      ctx.lineWidth = Math.max(.55, gap * .34);
      ctx.stroke();
      ctx.globalAlpha = .7;
      ctx.strokeStyle = tint.css('#ffe2f6');
      ctx.lineWidth = Math.max(.6, gap * .37);
      ctx.beginPath(); ctx.moveTo(Math.max(0, edge - height * .022), y); ctx.lineTo(edge, y); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  diamond({ ctx, width, height, motion, amount, p, tint }) {
    const cell = materialGeometry(width, height).cellSize;
    const columns = Math.ceil(width / cell), rows = Math.ceil(height / cell);
    const palette = ['#f29486', '#d0657b', '#ef879a', '#aa5069', '#f9ae95', '#da6d87'].map(color => tint.css(color));
    for (let row = 0; row < rows; row++) {
      const edge = materialFront({ width, height, progress: p, index: row, energy: motion.energy, phase: motion.phase, amount, spread: .16 });
      for (let col = 0; col < columns; col++) {
        const x = col * cell;
        if (x >= edge) break;
        const y = row * cell;
        const index = row * columns + col;
        const revealed = clamp((edge - x) / cell);
        const checker = (row + col) % 2 === 0;
        if (checker) {
          const inset = .5 + (1 - revealed) * cell * .22;
          ctx.globalAlpha = revealed * (.78 + materialNoise(index, 13) * .2);
          ctx.fillStyle = palette[Math.floor(materialNoise(index, 2) * palette.length)];
          ctx.fillRect(x + inset, y + inset, Math.max(0, cell - inset * 2), Math.max(0, cell - inset * 2));
        } else {
          ctx.globalAlpha = .33 * revealed;
          ctx.fillStyle = tint.css('#723747');
          ctx.fillRect(x + .5, y + .5, Math.min(cell - 1, edge - x), cell - 1);
          ctx.globalAlpha = .20 * revealed;
          ctx.strokeStyle = tint.css('#ca7c82');
          ctx.lineWidth = .5;
          ctx.strokeRect(x + .5, y + .5, Math.min(cell - 1, edge - x), cell - 1);
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  textured({ ctx, width, height, pixelRatio, kind, motion, amount, p, tint }) {
    const texture = this.textureFor(kind, width, height, pixelRatio, tint);
    const edge = width * p;
    const room = Math.min(edge, width - edge);
    const feather = Math.min(materialGeometry(width, height).feather, room * .9);
    const rowHeight = Math.max(1, height / 75);
    const rows = Math.ceil(height / rowHeight);
    // Vary the dissolve boundary gently per horizontal strip. Textures remain
    // cached: active frames only composite a narrow moving boundary.
    ctx.save();
    ctx.beginPath();
    for (let row = 0; row < rows; row++) {
      const end = materialFront({ width, height, progress: p, index: row, energy: motion.energy, phase: motion.phase, amount, spread: .045 });
      ctx.rect(0, row * rowHeight, Math.min(width, end + feather), rowHeight + .1);
    }
    ctx.clip();
    ctx.drawImage(texture, 0, 0, width, height);
    ctx.restore();
    if (p < 1) {
      const color = kind === 'drops' ? '17,22,14' : '24,20,31';
      const gradient = ctx.createLinearGradient(edge - feather, 0, edge + feather, 0);
      gradient.addColorStop(0, `rgba(${color},0)`);
      gradient.addColorStop(.43, `rgba(${color},.28)`);
      gradient.addColorStop(1, `rgba(${color},1)`);
      ctx.fillStyle = gradient;
      ctx.fillRect(Math.max(0, edge - feather), 0, width - Math.max(0, edge - feather), height);
      // Sparse leading motes: bounded to the transition region, not a particle
      // system that keeps the whole bar awake after progress has settled.
      const count = Math.ceil(height * (kind === 'drops' ? 1.7 : 2.4));
      for (let i = 0; i < count; i++) {
        const r = materialNoise(i, 23);
        const travel = Math.sin(motion.phase * 1.3 + i * .81) * motion.energy * amount;
        const x = clamp(edge + (r - .36) * feather * 1.7 + travel * feather * .09, 0, width);
        const y = materialNoise(i, 24) * height;
        ctx.globalAlpha = (1 - r) * (kind === 'drops' ? .75 : .64);
        ctx.fillStyle = tint.css(kind === 'drops' ? '#d7ff83' : '#e7c7ff');
        const size = kind === 'drops' ? .55 + materialNoise(i, 6) * .8 : .65;
        ctx.fillRect(x, y, size, kind === 'drops' ? size * 1.6 : size);
      }
    }
    ctx.globalAlpha = 1;
  }
}


// Continuous materials receive a smoothed presentation drive from the caller.
// No RAF, timers, full surface filters or task state live in this module.
function sampleSloshFront({ width, height, progress, energy = 0, phase = 0, amount = 1, velocity = 0 }) {
  const count = 64, p = normalizeProgress(progress), center = width * p;
  const room = Math.min(center, width - center);
  const amplitude = Math.min(height * .22 * (.16 + .84 * clamp(energy)) * clamp(amount, 0, 1.6), room * .55);
  const points = new Float64Array(count + 1);
  const lean = Math.sin(phase * .95 + .35) * .65 + Math.tanh(velocity * 2) * .35;
  let mean = 0;
  for (let i = 0; i <= count; i++) {
    const y = i / count;
    const wave = (y - .5) * lean + Math.sin(y * Math.PI * 1.55 - phase * .72) * .42;
    points[i] = wave;
    mean += wave * (i === 0 || i === count ? .5 : 1);
  }
  mean /= count;
  for (let i = 0; i <= count; i++) points[i] = center + amplitude * (points[i] - mean);
  return points;
}

const SMOKE_NOISE_SIZE = 128;
const SMOKE_NOISE = Float32Array.from({ length: SMOKE_NOISE_SIZE ** 2 }, (_, index) => {
  let hash = Math.imul(index + 17, 0x45d9f3b) >>> 0;
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b) >>> 0;
  return ((hash ^ (hash >>> 16)) >>> 0) / 4294967296;
});
const flowSmooth = x => { const t = clamp(x); return t * t * (3 - 2 * t); };

// Spread blue through the entire filled region, not a short highlight over an
// almost-black solid base. These stops are horizontal, not a dark bottom glaze.
const SLOSH_STOPS = Object.freeze([
  [0, '#123b83'], [.28, '#164c9d'], [.56, '#1a64c2'],
  [.78, '#278ee2'], [.93, '#59bbf5'], [1, '#a3e4ff'],
]);
function sloshGradientExtent(width, height, progress) {
  return [0, Math.max(1, width * normalizeProgress(progress) + height * .06)];
}

// Liquid and Slosh share the full-depth blue body; their surface geometry and
// refraction remain different. This does not allocate a full-width pixel field.
function createBlueFillGradient(ctx, width, height, progress, tint = ORIGINAL_FILL_TINT) {
  const [start, end] = sloshGradientExtent(width, height, progress);
  const gradient = ctx.createLinearGradient(start, 0, end, 0);
  for (const [offset, color] of SLOSH_STOPS) gradient.addColorStop(offset, tint.css(color));
  return gradient;
}

function smokeNoise(x, y) {
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = flowSmooth(x - ix), fy = flowSmooth(y - iy);
  const x0 = ix & 127, x1 = (ix + 1) & 127, y0 = (iy & 127) * 128, y1 = ((iy + 1) & 127) * 128;
  const a = SMOKE_NOISE[y0 + x0] * (1 - fx) + SMOKE_NOISE[y0 + x1] * fx;
  const b = SMOKE_NOISE[y1 + x0] * (1 - fx) + SMOKE_NOISE[y1 + x1] * fx;
  return a * (1 - fy) + b * fy;
}

// Back-trace the material, not just the shape of the edge. A texture feature
// travels RIGHT by .46/3.1 band units, and UP by .12/4.3 heights per phase unit.
// Coupled domain warps produce rolling folds; finer layers shear slowly instead
// of choosing random noise every frame (which would look like flicker).
function sampleSmokeTransport(distance, y, phase) {
  const u = -distance * 3.1 - phase * .46;
  const v = y * 4.3 + phase * .12;
  const curl = smokeNoise(u * .78 + 8.2, v * .82 + 3.7) - .5;
  const turn = smokeNoise(u * .9 - 6.3, v * .88) - .5;
  const x = u + curl * 2.15, z = v + turn * 1.65;
  return smokeNoise(x * 1.18, z * 1.06) * .58
    + smokeNoise(x * 2.65 + 11 - phase * .035, z * 2.3 - 2) * .29
    + smokeNoise(x * 5.2 - 7, z * 5.1 + 5 + phase * .025) * .13;
}

// Density combines a connected billowing body with separate, translucent
// forward wisps. The advected structures thin out as they leave the emitter;
// this is not just an animated signed-distance contour at a fixed boundary.
function sampleSmokeDensity(distance, y, phase, energy = 0, amount = 1) {
  if (distance >= 1.1) return 1;
  if (distance <= -.8) return 0;
  const texture = sampleSmokeTransport(distance, y, phase);
  const strength = (.55 + .45 * clamp(energy)) * clamp(amount, 0, 1.6);
  const outer = flowSmooth((distance + .8) / .55);
  const body = flowSmooth((distance + .12 + (texture - .5) * 1.18 * strength) / .68);
  const wisp = flowSmooth((texture - (.43 - distance * .13)) / .27)
    * outer * flowSmooth((.65 - distance) / .6) * .7 * Math.min(1, strength);
  const density = body + (1 - body) * wisp;
  const solid = flowSmooth((distance - .65) / .45);
  return density + (1 - density) * solid;
}

function flowRasterSize(width, height, pixelRatio = 1) {
  const scale = clamp(pixelRatio, 1, 1.25);
  return {
    width: Math.min(256, Math.max(2, Math.ceil(Math.min(width, height * 2.28) * scale))),
    height: Math.min(192, Math.max(2, Math.ceil(height * scale))),
  };
}

const SMOKE_STOPS = [
  [0, 111, 57, 155, 0], [.15, 139, 74, 190, .13], [.33, 175, 101, 218, .52],
  [.55, 218, 143, 245, .9], [.74, 247, 180, 255, 1], [.90, 253, 196, 255, 1], [1, 255, 208, 255, 1],
];

function buildSmokeLookup(tint) {
  const stops = SMOKE_STOPS.map(([position,r,g,b,alpha]) => [position, ...tint.rgb([r,g,b]), alpha]);
  const table = new Uint8ClampedArray(1025 * 4);
  for (let i = 0; i <= 1024; i++) {
    const value = i / 1024;
    let stop = 0;
    while (stop < stops.length - 2 && value > stops[stop + 1][0]) stop++;
    const a = stops[stop], b = stops[stop + 1], mix = (value - a[0]) / (b[0] - a[0]);
    for (let c = 0; c < 4; c++) table[i * 4 + c] = (a[c+1] + (b[c+1] - a[c+1]) * mix) * (c === 3 ? 255 : 1);
  }
  return table;
}

function traceFlowFront(ctx, front, height, offset = null) {
  ctx.beginPath();
  for (let i = 0; i < front.length; i++) {
    const y = i / (front.length - 1), x = front[i] - (offset ? offset(y) : 0);
    if (i === 0) ctx.moveTo(x, 0); else ctx.lineTo(x, y * height);
  }
}

class FlowEffects {
  constructor() {
    this.smokeCanvas = null;
    this.smokeContext = null;
    this.smokeImage = null;
    this.palette = null;
    this.paletteKey = '';
  }

  draw(ctx, width, height, dpr, kind, motion, amount = 1, tint = ORIGINAL_FILL_TINT, track = '#10141e') {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = track;
    ctx.fillRect(0, 0, width, height);
    if (motion.value <= 0) return;
    if (kind === 'slosh') this.slosh(ctx, width, height, motion, amount, tint);
    else if (kind === 'smoke') this.smoke(ctx, width, height, dpr, motion, amount, tint);
    ctx.globalAlpha = 1;
  }

  slosh(ctx, width, height, motion, amount, tint) {
    const front = sampleSloshFront({ width, height, progress: motion.value, energy: motion.energy, phase: motion.phase, amount, velocity: motion.velocity || 0 });
    traceFlowFront(ctx, front, height);
    ctx.lineTo(0, height); ctx.lineTo(0, 0); ctx.closePath();
    ctx.save(); ctx.clip();
    const body = createBlueFillGradient(ctx, width, height, motion.value, tint);
    ctx.fillStyle = body; ctx.fillRect(0,0,width,height);
    // Folds follow the surface, but vary in depth across its height. Wide low
    // alpha strokes form refraction bands without a blur/filter layer.
    for (const [depthFactor, alpha, breadth] of [[.43,.19,.12],[.22,.24,.07],[.07,.24,.04]]) {
      traceFlowFront(ctx, front, height, y => height * depthFactor * (1 + Math.sin(y * 5.2 + motion.phase * .37 + depthFactor * 4) * .35));
      ctx.strokeStyle = tint.css('#408aff');
      for (const [spread,weight] of [[1.8,.025],[1.45,.045],[1.1,.07],[.8,.10],[.55,.13],[.32,.15],[.14,.11]]) {
        ctx.lineWidth = Math.max(.45, height * breadth * spread);
        ctx.globalAlpha = alpha * weight;
        ctx.stroke();
      }
    }
    traceFlowFront(ctx, front, height);
    for (const [breadth,alpha,color] of [[.12,.12,'#7cc8ff'],[.048,.3,'#81caff'],[.009,.85,'#c2e5ff']]) {
      ctx.lineWidth = Math.max(.7,height * breadth);
      ctx.globalAlpha = alpha; ctx.strokeStyle = tint.css(color); ctx.stroke();
    }
    ctx.restore(); ctx.globalAlpha = 1;
  }

  smoke(ctx, width, height, dpr, motion, amount, tint) {
    const p = clamp(motion.value), edge = width * p;
    ctx.fillStyle = tint.css('#ffd0ff');
    if (p === 1) { ctx.fillRect(0,0,width,height); return; }
    const band = Math.min(height * 1.2, edge * .9, (width - edge) * .9);
    if (band <= .001) { ctx.fillRect(0,0,edge,height); return; }
    const left = edge - band * 1.1, span = band * 1.9;
    ctx.fillRect(0,0,Math.max(0,left + .5),height);
    const size = flowRasterSize(width,height,dpr);
    if (!this.smokeCanvas) {
      this.smokeCanvas = document.createElement('canvas');
      this.smokeContext = this.smokeCanvas.getContext('2d');
    }
    if (!this.smokeImage || this.smokeCanvas.width !== size.width || this.smokeCanvas.height !== size.height) {
      this.smokeCanvas.width = size.width; this.smokeCanvas.height = size.height;
      this.smokeImage = this.smokeContext.createImageData(size.width,size.height);
    }
    const key = tint.color || 'original';
    if (this.paletteKey !== key) { this.palette = buildSmokeLookup(tint); this.paletteKey = key; }
    const pixels = this.smokeImage.data;
    for (let row = 0; row < size.height; row++) {
      const y = (row + .5) / size.height;
      for (let col = 0; col < size.width; col++) {
        const distance = 1.1 - (col + .5) / size.width * 1.9;
        const density = sampleSmokeDensity(distance,y,motion.phase,motion.energy,amount);
        const index = Math.round(density * 1024) * 4, offset = (row * size.width + col) * 4;
        pixels[offset] = this.palette[index]; pixels[offset+1] = this.palette[index+1];
        pixels[offset+2] = this.palette[index+2]; pixels[offset+3] = this.palette[index+3];
      }
    }
    this.smokeContext.putImageData(this.smokeImage,0,0);
    ctx.drawImage(this.smokeCanvas,left,0,span,height);
  }

  destroy() {
    if (this.smokeCanvas) this.smokeCanvas.width = this.smokeCanvas.height = 1;
    this.smokeCanvas = this.smokeContext = this.smokeImage = this.palette = null;
    this.paletteKey = '';
  }
}

window.DesktopProgressMaterials = Object.freeze({
  PatternEffects, FlowEffects, SLOSH_STOPS, sloshGradientExtent, createBlueFillGradient,
  materialNoise, materialFront, materialGeometry, sampleSloshFront,
  smokeNoise, sampleSmokeTransport, sampleSmokeDensity, flowRasterSize,
});

})();
