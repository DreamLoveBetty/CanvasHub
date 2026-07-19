(function () {
  'use strict';

  const MAX_ANALYSIS_EDGE = 240;
  const MAX_CANDIDATES = 18;
  const MAX_SOURCE_EDGE = 10000;
  const MAX_SOURCE_PIXELS = 36_000_000;
  const HEADER_READ_BYTES = 2 * 1024 * 1024;
  const ROLE_LABELS = ['主色', '辅色', '点缀色', '浅中性色', '深中性色'];

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, Number(value) || 0));
  }

  function channelHex(value) {
    return Math.round(clamp(value, 0, 255)).toString(16).padStart(2, '0');
  }

  function rgbToHex(rgb) {
    return `#${channelHex(rgb.r)}${channelHex(rgb.g)}${channelHex(rgb.b)}`.toUpperCase();
  }

  function rgbToHsl(rgb) {
    const r = clamp(rgb.r, 0, 255) / 255;
    const g = clamp(rgb.g, 0, 255) / 255;
    const b = clamp(rgb.b, 0, 255) / 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const delta = max - min;
    let h = 0;
    if (delta) {
      if (max === r) h = 60 * (((g - b) / delta) % 6);
      else if (max === g) h = 60 * ((b - r) / delta + 2);
      else h = 60 * ((r - g) / delta + 4);
    }
    const l = (max + min) / 2;
    const s = delta ? delta / (1 - Math.abs(2 * l - 1)) : 0;
    return { h: (h + 360) % 360, s: s * 100, l: l * 100 };
  }

  function hslToHex(hue, saturation, lightness) {
    const h = ((Number(hue) % 360) + 360) % 360;
    const s = clamp(saturation, 0, 100) / 100;
    const l = clamp(lightness, 0, 100) / 100;
    const chroma = (1 - Math.abs(2 * l - 1)) * s;
    const x = chroma * (1 - Math.abs((h / 60) % 2 - 1));
    const m = l - chroma / 2;
    const values = h < 60 ? [chroma, x, 0]
      : h < 120 ? [x, chroma, 0]
        : h < 180 ? [0, chroma, x]
          : h < 240 ? [0, x, chroma]
            : h < 300 ? [x, 0, chroma]
              : [chroma, 0, x];
    return rgbToHex({ r: (values[0] + m) * 255, g: (values[1] + m) * 255, b: (values[2] + m) * 255 });
  }

  function linearChannel(value) {
    const channel = clamp(value, 0, 255) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }

  function rgbToOklab(rgb) {
    const r = linearChannel(rgb.r);
    const g = linearChannel(rgb.g);
    const b = linearChannel(rgb.b);
    const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
    const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
    const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
    const lRoot = Math.cbrt(l);
    const mRoot = Math.cbrt(m);
    const sRoot = Math.cbrt(s);
    return {
      l: 0.2104542553 * lRoot + 0.793617785 * mRoot - 0.0040720468 * sRoot,
      a: 1.9779984951 * lRoot - 2.428592205 * mRoot + 0.4505937099 * sRoot,
      b: 0.0259040371 * lRoot + 0.7827717662 * mRoot - 0.808675766 * sRoot,
    };
  }

  function colorDistance(first, second) {
    if (!first || !second) return 1;
    return Math.hypot(first.l - second.l, first.a - second.a, first.b - second.b);
  }

  function hueDistance(first, second) {
    const delta = Math.abs(Number(first || 0) - Number(second || 0)) % 360;
    return Math.min(delta, 360 - delta);
  }

  async function sourceToBlob(source) {
    if (source instanceof Blob) return source;
    const url = typeof source === 'string' ? source : source?.src;
    if (!url) throw new Error('没有可分析的图片');
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`图片读取失败 (${response.status})`);
    return response.blob();
  }

  function jpegDimensions(bytes) {
    if (bytes[0] !== 0xFF || bytes[1] !== 0xD8) return null;
    const startOfFrame = new Set([0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF]);
    let offset = 2;
    while (offset + 8 < bytes.length) {
      if (bytes[offset] !== 0xFF) { offset += 1; continue; }
      while (offset < bytes.length && bytes[offset] === 0xFF) offset += 1;
      const marker = bytes[offset++];
      if (marker === 0xD9 || marker === 0xDA) break;
      if (marker === 0x01 || (marker >= 0xD0 && marker <= 0xD7)) continue;
      if (offset + 1 >= bytes.length) break;
      const length = (bytes[offset] << 8) | bytes[offset + 1];
      if (length < 2 || offset + length > bytes.length) break;
      if (startOfFrame.has(marker) && length >= 7) {
        return {
          width: (bytes[offset + 5] << 8) | bytes[offset + 6],
          height: (bytes[offset + 3] << 8) | bytes[offset + 4],
        };
      }
      offset += length;
    }
    return null;
  }

  function webpDimensions(bytes) {
    if (bytes.length < 30 || String.fromCharCode(...bytes.slice(0, 4)) !== 'RIFF' || String.fromCharCode(...bytes.slice(8, 12)) !== 'WEBP') return null;
    const chunk = String.fromCharCode(...bytes.slice(12, 16));
    if (chunk === 'VP8X') {
      return {
        width: 1 + bytes[24] + (bytes[25] << 8) + (bytes[26] << 16),
        height: 1 + bytes[27] + (bytes[28] << 8) + (bytes[29] << 16),
      };
    }
    if (chunk === 'VP8 ' && bytes[23] === 0x9D && bytes[24] === 0x01 && bytes[25] === 0x2A) {
      return {
        width: (bytes[26] | (bytes[27] << 8)) & 0x3FFF,
        height: (bytes[28] | (bytes[29] << 8)) & 0x3FFF,
      };
    }
    if (chunk === 'VP8L' && bytes[20] === 0x2F) {
      const bits = bytes[21] | (bytes[22] << 8) | (bytes[23] << 16) | (bytes[24] << 24);
      return { width: 1 + (bits & 0x3FFF), height: 1 + ((bits >>> 14) & 0x3FFF) };
    }
    return null;
  }

  function encodedImageDimensions(bytes) {
    const pngSignature = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
    if (bytes.length >= 24 && pngSignature.every((value, index) => bytes[index] === value)) {
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      return { width: view.getUint32(16), height: view.getUint32(20) };
    }
    return jpegDimensions(bytes) || webpDimensions(bytes);
  }

  async function readAndValidateSourceDimensions(blob) {
    const header = new Uint8Array(await blob.slice(0, HEADER_READ_BYTES).arrayBuffer());
    const dimensions = encodedImageDimensions(header);
    if (!dimensions?.width || !dimensions?.height) throw new Error('无法在解码前读取图片尺寸');
    const pixels = dimensions.width * dimensions.height;
    if (dimensions.width > MAX_SOURCE_EDGE || dimensions.height > MAX_SOURCE_EDGE || pixels > MAX_SOURCE_PIXELS) {
      throw new Error('图片尺寸过大，请使用长边不超过 10000px 且总像素不超过 3600 万的图片');
    }
    return dimensions;
  }

  function decodeImageElement(blob) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.onload = () => resolve({
        drawable: image,
        width: image.naturalWidth,
        height: image.naturalHeight,
        close: () => URL.revokeObjectURL(url),
      });
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error('当前图片格式无法解析'));
      };
      image.src = url;
    });
  }

  async function decodeImage(blob, targetSize) {
    if (typeof createImageBitmap === 'function') {
      try {
        const bitmap = await createImageBitmap(blob, {
          imageOrientation: 'from-image',
          resizeWidth: targetSize.width,
          resizeHeight: targetSize.height,
          resizeQuality: 'high',
        });
        return { drawable: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close?.() };
      } catch (error) {}
    }
    return decodeImageElement(blob);
  }

  function pixelModeWeight(mode, saturation, x, y, width, height) {
    if (mode === 'vivid') return 0.42 + Math.max(0.08, saturation) * 2.25;
    if (mode !== 'subject') return 1;
    const normalizedX = (x + 0.5) / Math.max(1, width) - 0.5;
    const normalizedY = (y + 0.5) / Math.max(1, height) - 0.5;
    const centrality = 1 - Math.min(1, Math.hypot(normalizedX, normalizedY) / 0.7072);
    return 0.62 + 1.9 * centrality ** 1.6;
  }

  function buildHistogram(imageData, width, height, mode) {
    const bins = new Map();
    let totalPopulation = 0;
    let totalScore = 0;
    for (let index = 0; index < imageData.length; index += 4) {
      const alpha = imageData[index + 3] / 255;
      if (alpha < 0.5) continue;
      const r = imageData[index];
      const g = imageData[index + 1];
      const b = imageData[index + 2];
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const saturation = max ? (max - min) / max : 0;
      const pixel = index / 4;
      const x = pixel % width;
      const y = Math.floor(pixel / width);
      const population = alpha;
      const score = alpha * pixelModeWeight(mode, saturation, x, y, width, height);
      const key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
      const bin = bins.get(key) || { population: 0, score: 0, r: 0, g: 0, b: 0 };
      bin.population += population;
      bin.score += score;
      bin.r += r * population;
      bin.g += g * population;
      bin.b += b * population;
      bins.set(key, bin);
      totalPopulation += population;
      totalScore += score;
    }
    if (totalPopulation < 16) throw new Error('图片中没有足够的可见颜色');
    return { bins: [...bins.values()], totalPopulation, totalScore };
  }

  function binRgb(bin) {
    const divisor = Math.max(0.0001, bin.population);
    return { r: bin.r / divisor, g: bin.g / divisor, b: bin.b / divisor };
  }

  function clusterHistogram(histogram, mode) {
    const sorted = histogram.bins
      .filter(bin => bin.population > 0)
      .sort((first, second) => second.score - first.score);
    const clusters = [];
    const threshold = mode === 'vivid' ? 0.045 : 0.052;
    const nearestCluster = lab => {
      let match = null;
      let distance = Infinity;
      clusters.forEach(cluster => {
        const candidateDistance = colorDistance(lab, cluster.lab);
        if (candidateDistance < distance) { distance = candidateDistance; match = cluster; }
      });
      return { match, distance };
    };
    const mergeBin = (cluster, bin) => {
      cluster.population += bin.population;
      cluster.score += bin.score;
      cluster.r += bin.r;
      cluster.g += bin.g;
      cluster.b += bin.b;
      cluster.lab = rgbToOklab(binRgb(cluster));
    };
    sorted.forEach(bin => {
      const rgb = binRgb(bin);
      const lab = rgbToOklab(rgb);
      const nearest = nearestCluster(lab);
      if (nearest.match && (nearest.distance <= threshold || clusters.length >= 42)) {
        mergeBin(nearest.match, bin);
      } else if (clusters.length < 42) {
        clusters.push({ ...bin, lab });
      }
    });

    const candidates = clusters.map(cluster => {
      const rgb = binRgb(cluster);
      return {
        color: rgbToHex(rgb),
        population: cluster.population,
        ratio: cluster.population / histogram.totalPopulation,
        weightedRatio: cluster.score / Math.max(0.0001, histogram.totalScore),
        hsl: rgbToHsl(rgb),
        lab: rgbToOklab(rgb),
      };
    }).sort((first, second) => second.weightedRatio - first.weightedRatio);

    const selected = candidates.slice(0, 14);
    const special = [
      candidates.reduce((best, item) => !best || item.hsl.l > best.hsl.l ? item : best, null),
      candidates.reduce((best, item) => !best || item.hsl.l < best.hsl.l ? item : best, null),
      candidates.reduce((best, item) => !best || item.hsl.s > best.hsl.s ? item : best, null),
    ];
    special.filter(Boolean).forEach(item => {
      if (!selected.some(candidate => candidate.color === item.color)) selected.push(item);
    });
    return selected.slice(0, MAX_CANDIDATES);
  }

  function bestCandidate(candidates, score) {
    return candidates.reduce((best, item) => {
      const value = score(item);
      return !best || value > best.value ? { item, value } : best;
    }, null)?.item || null;
  }

  function derivedCandidate(base, role) {
    const source = base?.hsl || { h: 210, s: 55, l: 50 };
    const settings = {
      secondary: { h: source.h, s: source.s < 8 ? 0 : Math.max(12, source.s * 0.76), l: clamp(source.l + 14, 28, 76) },
      accent: { h: source.h, s: source.s < 8 ? 0 : clamp(source.s + 8, 18, 88), l: clamp(source.l - 14, 22, 64) },
      light: { h: source.h, s: Math.min(16, source.s * 0.22), l: 93 },
      dark: { h: source.h, s: Math.min(28, source.s * 0.36), l: 16 },
    }[role];
    const color = hslToHex(settings.h, settings.s, settings.l);
    const rgb = {
      r: parseInt(color.slice(1, 3), 16),
      g: parseInt(color.slice(3, 5), 16),
      b: parseInt(color.slice(5, 7), 16),
    };
    return { color, population: 0, ratio: null, weightedRatio: 0, hsl: rgbToHsl(rgb), lab: rgbToOklab(rgb), derived: true };
  }

  function inferRoles(candidates) {
    const filtered = candidates.filter(item => item.ratio >= 0.0005);
    const usable = filtered.length ? filtered : candidates.filter(Boolean);
    if (!usable.length) throw new Error('没有足够的候选颜色');
    const chromatic = usable.filter(item => item.hsl.s >= 18 && item.hsl.l >= 10 && item.hsl.l <= 92);
    const primaryPool = chromatic.length ? chromatic : usable.filter(item => item.hsl.l >= 10 && item.hsl.l <= 90);
    const primary = bestCandidate(primaryPool.length ? primaryPool : usable, item => {
      const middleTone = 1 - Math.min(0.6, Math.abs(item.hsl.l - 50) / 100);
      return item.weightedRatio * (0.72 + item.hsl.s / 260) * middleTone;
    }) || usable[0] || candidates[0];

    const secondaryPool = usable.filter(item => item !== primary && colorDistance(item.lab, primary?.lab) >= 0.055);
    const secondary = bestCandidate(secondaryPool, item => item.weightedRatio * (0.72 + colorDistance(item.lab, primary.lab) * 2.2) * (0.78 + item.hsl.s / 260))
      || derivedCandidate(primary, 'secondary');

    const accentPool = usable.filter(item => item !== primary && item !== secondary && colorDistance(item.lab, primary?.lab) >= 0.07);
    const chromaticAccentPool = accentPool.filter(item => item.hsl.s >= Math.max(24, primary.hsl.s * 0.85) && item.hsl.l >= 16 && item.hsl.l <= 82);
    const accent = bestCandidate(chromaticAccentPool.length ? chromaticAccentPool : accentPool, item => {
      const distinction = Math.min(0.6, colorDistance(item.lab, primary.lab));
      const middleTone = 1 - Math.min(0.5, Math.abs(item.hsl.l - 50) / 100);
      return (0.12 + item.weightedRatio) * (0.42 + item.hsl.s / 38) * (0.65 + distinction * 2.4) * middleTone;
    }) || derivedCandidate(primary, 'accent');

    const used = new Set([primary?.color, secondary?.color, accent?.color]);
    const lightPool = usable.filter(item => !used.has(item.color) && item.hsl.l >= 66 && item.hsl.s <= 42);
    const light = bestCandidate(lightPool, item => item.weightedRatio * (0.8 + item.hsl.l / 100) * (1.25 - item.hsl.s / 150))
      || derivedCandidate(primary, 'light');
    used.add(light.color);
    const darkPool = usable.filter(item => !used.has(item.color) && item.hsl.l <= 40 && item.hsl.s <= 48);
    const dark = bestCandidate(darkPool, item => item.weightedRatio * (1.45 - item.hsl.l / 100) * (1.25 - item.hsl.s / 180))
      || derivedCandidate(primary, 'dark');

    return [primary, secondary, accent, light, dark].map((item, index) => ({
      key: ['primary', 'secondary', 'accent', 'light', 'dark'][index],
      label: ROLE_LABELS[index],
      color: item.color,
      ratio: item.ratio,
      source: item.derived ? 'derived' : 'image',
    }));
  }

  function distinctHues(candidates) {
    const hues = [];
    candidates
      .filter(item => item.hsl.s >= 22 && item.ratio >= 0.003)
      .sort((first, second) => second.weightedRatio - first.weightedRatio)
      .forEach(item => {
        if (hues.length >= 6) return;
        if (!hues.some(hue => hueDistance(hue, item.hsl.h) < 15)) hues.push(item.hsl.h);
      });
    return hues;
  }

  function inferFormula(candidates) {
    const hues = distinctHues(candidates);
    if (hues.length <= 1) return 'monochromatic';
    const distances = [];
    for (let first = 0; first < hues.length; first += 1) {
      for (let second = first + 1; second < hues.length; second += 1) distances.push(hueDistance(hues[first], hues[second]));
    }
    const maxDistance = Math.max(...distances);
    if (maxDistance <= 68) return 'analogous';
    if (hues.length >= 4) {
      const sorted = hues.slice().sort((a, b) => a - b).slice(0, 4);
      const gaps = sorted.map((hue, index) => (sorted[(index + 1) % sorted.length] - hue + 360) % 360);
      if (gaps.every(gap => gap >= 62 && gap <= 118)) return 'square';
      if (distances.filter(distance => distance >= 150).length >= 2) return 'tetradic';
    }
    if (hues.length >= 3) {
      const triad = hues.slice(0, 3).sort((a, b) => a - b);
      const gaps = triad.map((hue, index) => (triad[(index + 1) % triad.length] - hue + 360) % 360);
      if (gaps.every(gap => gap >= 82 && gap <= 158)) return 'triadic';
      const fromPrimary = hues.slice(1).map(hue => hueDistance(hues[0], hue));
      if (fromPrimary.length >= 2 && fromPrimary.slice(0, 2).every(distance => distance >= 135 && distance <= 225)) return 'split_complementary';
    }
    if (maxDistance >= 145) return 'complementary';
    return 'analogous';
  }

  function inferTemperature(candidates) {
    let score = 0;
    let weight = 0;
    candidates.forEach(item => {
      if (item.hsl.s < 8) return;
      const chromaWeight = item.weightedRatio * (item.hsl.s / 100);
      score += Math.cos((item.hsl.h - 38) * Math.PI / 180) * chromaWeight;
      weight += chromaWeight;
    });
    if (!weight) return 'auto';
    const normalized = score / weight;
    return normalized >= 0.18 ? 'warm' : normalized <= -0.18 ? 'cool' : 'auto';
  }

  function weightedLightnessQuantile(candidates, quantile) {
    const values = candidates.filter(item => item.ratio >= 0.001).slice().sort((a, b) => a.hsl.l - b.hsl.l);
    const total = values.reduce((sum, item) => sum + item.ratio, 0);
    let current = 0;
    for (const item of values) {
      current += item.ratio;
      if (current >= total * quantile) return item.hsl.l;
    }
    return values.at(-1)?.hsl.l || 50;
  }

  function inferContrast(candidates) {
    const low = weightedLightnessQuantile(candidates, 0.12);
    const high = weightedLightnessQuantile(candidates, 0.88);
    const range = high - low;
    const total = candidates.reduce((sum, item) => sum + item.ratio, 0) || 1;
    const averageSaturation = candidates.reduce((sum, item) => sum + item.hsl.s * item.ratio, 0) / total;
    if (range >= 56) return 'high';
    if (range <= 30 && averageSaturation <= 46) return 'soft';
    return 'balanced';
  }

  async function analyze(source, options = {}) {
    const mode = ['balanced', 'subject', 'vivid'].includes(options.mode) ? options.mode : 'balanced';
    const blob = await sourceToBlob(source);
    if (!blob.size) throw new Error('图片内容为空');
    const sourceDimensions = await readAndValidateSourceDimensions(blob);
    const scale = Math.min(1, MAX_ANALYSIS_EDGE / Math.max(sourceDimensions.width, sourceDimensions.height));
    const targetSize = {
      width: Math.max(1, Math.round(sourceDimensions.width * scale)),
      height: Math.max(1, Math.round(sourceDimensions.height * scale)),
    };
    const decoded = await decodeImage(blob, targetSize);
    try {
      if (!decoded.width || !decoded.height) throw new Error('无法读取图片尺寸');
      const width = targetSize.width;
      const height = targetSize.height;
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d', { alpha: true, willReadFrequently: true });
      if (!context) throw new Error('浏览器无法创建图片分析画布');
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'high';
      context.drawImage(decoded.drawable, 0, 0, width, height);
      const pixels = context.getImageData(0, 0, width, height).data;
      const histogram = buildHistogram(pixels, width, height, mode);
      const candidates = clusterHistogram(histogram, mode);
      if (!candidates.length) throw new Error('没有提取到有效颜色');
      return {
        mode,
        width: sourceDimensions.width,
        height: sourceDimensions.height,
        roles: inferRoles(candidates),
        candidates: candidates.map(item => ({
          color: item.color,
          ratio: item.ratio,
          population: Math.round(item.population),
          saturation: item.hsl.s,
          lightness: item.hsl.l,
        })),
        temperature: inferTemperature(candidates),
        contrast: inferContrast(candidates),
        formula: inferFormula(candidates),
      };
    } finally {
      decoded.close?.();
    }
  }

  window.DesktopColorExtractor = { analyze };
})();
