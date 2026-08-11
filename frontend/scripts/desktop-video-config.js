(function () {
  const DIMENSION_MULTIPLE = 32;
  const FALLBACK_MAX_PIXELS = 1344 * 768;

  const PRESETS = Object.freeze({
    '16:9': [
      [0.2, 608, 352], [0.3, 736, 416], [0.4, 864, 480], [0.5, 960, 544],
      [0.6, 1056, 608], [0.7, 1152, 640], [0.8, 1216, 672], [0.9, 1280, 736],
      [1.0, 1344, 768], [1.1, 1376, 768], [1.3, 1504, 832], [1.5, 1664, 928],
      [1.9, 1824, 1024], [2.1, 1920, 1088]
    ],
    '9:16': [
      [0.2, 352, 608], [0.3, 416, 736], [0.4, 480, 864], [0.5, 544, 960],
      [0.6, 608, 1056], [0.7, 640, 1152], [0.8, 672, 1216], [0.9, 736, 1280],
      [1.0, 768, 1344], [1.1, 768, 1376], [1.3, 832, 1504], [1.5, 928, 1664],
      [1.9, 1024, 1824], [2.1, 1088, 1920]
    ],
    '3:4': [
      [0.4, 576, 768], [0.6, 672, 896], [0.8, 768, 1024], [1.0, 864, 1152],
      [1.2, 960, 1280], [1.5, 1056, 1408], [1.8, 1152, 1536], [2.1, 1248, 1664]
    ],
    '4:3': [
      [0.4, 768, 576], [0.6, 896, 672], [0.8, 1024, 768], [1.0, 1152, 864],
      [1.2, 1280, 960], [1.5, 1408, 1056], [1.8, 1536, 1152], [2.1, 1664, 1248]
    ],
    '2:3': [
      [0.5, 576, 864], [0.6, 640, 960], [0.7, 704, 1056], [0.9, 768, 1152],
      [1.0, 832, 1248], [1.2, 896, 1344], [1.4, 960, 1440], [1.6, 1024, 1536],
      [1.8, 1088, 1632], [2.0, 1152, 1728]
    ],
    '3:2': [
      [0.5, 864, 576], [0.6, 960, 640], [0.7, 1056, 704], [0.9, 1152, 768],
      [1.0, 1248, 832], [1.2, 1344, 896], [1.4, 1440, 960], [1.6, 1536, 1024],
      [1.8, 1632, 1088], [2.0, 1728, 1152]
    ],
    '1:1': [
      [0.4, 640, 640], [0.5, 736, 736], [0.7, 832, 832], [0.9, 928, 928],
      [1.0, 1024, 1024], [1.3, 1120, 1120], [1.5, 1216, 1216],
      [1.7, 1312, 1312], [2.0, 1408, 1408]
    ],
    '21:9': [
      [0.4, 960, 416], [0.5, 1088, 480], [0.6, 1216, 512], [0.8, 1344, 576],
      [1.0, 1536, 672], [1.2, 1664, 704], [1.4, 1792, 768], [1.6, 1888, 832],
      [1.7, 2016, 864], [2.0, 2176, 928]
    ],
    '9:21': [
      [0.4, 416, 960], [0.5, 480, 1088], [0.6, 512, 1216], [0.8, 576, 1344],
      [1.0, 672, 1536], [1.2, 704, 1664], [1.4, 768, 1792], [1.6, 832, 1888],
      [1.7, 864, 2016], [2.0, 928, 2176]
    ]
  });

  const ASPECT_RATIOS = Object.freeze(Object.keys(PRESETS));
  const ACCELERATION_MODES = Object.freeze(['off', 'first_block_cache', 'sol_attn', 'combined']);
  let capabilities = null;
  let runtimeStatus = null;

  function finiteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function clamp(value, minimum, maximum, fallback) {
    const number = finiteNumber(value, fallback);
    return Math.max(minimum, Math.min(maximum, number));
  }

  function asPreset(item) {
    return {
      megapixels: item[0],
      width: item[1],
      height: item[2],
      pixels: item[1] * item[2]
    };
  }

  function rawCapabilities(payload) {
    if (!payload || typeof payload !== 'object') return null;
    return payload.capabilities && typeof payload.capabilities === 'object'
      ? payload.capabilities
      : payload;
  }

  function getMaxPixels() {
    const raw = rawCapabilities(capabilities);
    const maxPixels = finiteNumber(raw?.constraints?.max_pixels, FALLBACK_MAX_PIXELS);
    return Math.max(DIMENSION_MULTIPLE * DIMENSION_MULTIPLE, maxPixels);
  }

  function getDimensionMultiple() {
    const raw = rawCapabilities(capabilities);
    return Math.max(1, Math.round(finiteNumber(raw?.constraints?.dimension_multiple, DIMENSION_MULTIPLE)));
  }

  function getDurationRange() {
    const raw = rawCapabilities(capabilities);
    const range = raw?.constraints?.duration_seconds || {};
    const minimum = Math.max(1, finiteNumber(range.min, 1));
    const maximum = Math.max(minimum, finiteNumber(range.max, 15));
    return { minimum, maximum };
  }

  function normalizeAspectRatio(value, fallback = '3:4') {
    const ratio = String(value || '').trim();
    return ASPECT_RATIOS.includes(ratio) ? ratio : fallback;
  }

  function availablePresets(aspectRatio, maxPixels = getMaxPixels()) {
    const ratio = normalizeAspectRatio(aspectRatio);
    const limit = Math.max(1, finiteNumber(maxPixels, FALLBACK_MAX_PIXELS));
    const all = (PRESETS[ratio] || PRESETS['3:4']).map(asPreset);
    const supported = all.filter(item => item.pixels <= limit);
    return supported.length ? supported : [all[0]];
  }

  function resolvePreset(aspectRatio, megapixels, maxPixels = getMaxPixels()) {
    const ratio = normalizeAspectRatio(aspectRatio);
    const presets = availablePresets(ratio, maxPixels);
    const requested = finiteNumber(megapixels, ratio === '3:4' ? 0.8 : presets[0].megapixels);
    let best = presets[0];
    let bestDelta = Math.abs(best.megapixels - requested);
    presets.forEach(item => {
      const delta = Math.abs(item.megapixels - requested);
      if (delta < bestDelta || (Math.abs(delta - bestDelta) < 1e-9 && item.megapixels < best.megapixels)) {
        best = item;
        bestDelta = delta;
      }
    });
    return { ...best, aspectRatio: ratio };
  }

  function normalizeAccelerationMode(value, fallback = 'first_block_cache') {
    const mode = String(value || '').trim().toLowerCase();
    return ACCELERATION_MODES.includes(mode) ? mode : fallback;
  }

  function normalizeNode(node = {}) {
    const durationRange = getDurationRange();
    node.provider = 'minimax_h3';
    node.mode = String(node.mode || 'image_to_video') === 'reference_to_video'
      ? 'reference_to_video'
      : 'image_to_video';
    node.durationSeconds = clamp(node.durationSeconds ?? node.duration_seconds, durationRange.minimum, durationRange.maximum, 15);
    node.aspectRatio = normalizeAspectRatio(node.aspectRatio ?? node.aspect_ratio, '3:4');
    const preset = resolvePreset(node.aspectRatio, node.pixelBudgetMp ?? node.pixel_budget_mp ?? 0.8);
    node.pixelBudgetMp = preset.megapixels;
    node.pixelWidth = preset.width;
    node.pixelHeight = preset.height;
    node.accelerationMode = normalizeAccelerationMode(node.accelerationMode ?? node.acceleration_mode, 'first_block_cache');
    node.firstBlockCacheThreshold = clamp(
      node.firstBlockCacheThreshold ?? node.first_block_cache_threshold,
      0.001,
      1,
      0.08
    );
    node.steps = Math.round(clamp(node.steps, 1, 100, 20));
    node.crf = Math.round(clamp(node.crf, 0, 51, 23));
    delete node.denoise;
    delete node.seed;
    delete node.advancedExpanded;
    delete node.advanced_expanded;
    return node;
  }

  function setCapabilities(payload) {
    capabilities = payload && typeof payload === 'object' ? payload : null;
    window.dispatchEvent(new CustomEvent('desktop:video-capabilities-updated', {
      detail: getCapabilitySnapshot()
    }));
    return getCapabilitySnapshot();
  }

  function setRuntimeStatus(payload) {
    runtimeStatus = payload && typeof payload === 'object' ? payload : null;
    window.dispatchEvent(new CustomEvent('desktop:video-runtime-status-updated', {
      detail: runtimeStatus
    }));
    return runtimeStatus;
  }

  function getCapabilitySnapshot() {
    const raw = rawCapabilities(capabilities) || {};
    return {
      ...raw,
      runtime_online: Boolean(capabilities?.runtime_online ?? runtimeStatus?.online),
      source: capabilities?.source || (capabilities ? 'runtime' : 'fallback'),
      constraints: {
        ...(raw.constraints || {}),
        dimension_multiple: getDimensionMultiple(),
        max_pixels: getMaxPixels(),
        duration_seconds: {
          min: getDurationRange().minimum,
          max: getDurationRange().maximum
        }
      }
    };
  }

  function getRuntimeStatus() {
    return runtimeStatus;
  }

  function accelerationLabel(node = {}) {
    const mode = normalizeAccelerationMode(node.accelerationMode ?? node.acceleration_mode);
    if (mode === 'off') return '标准模式 · 不加速';
    if (mode === 'first_block_cache') {
      return `快速模式 · FBC ${finiteNumber(node.firstBlockCacheThreshold, 0.08).toFixed(2)}`;
    }
    if (mode === 'sol_attn') return '实验模式 · Sol-Attn';
    return '实验模式 · FBC + Sol-Attn';
  }

  window.DesktopVideoConfig = {
    PRESETS,
    ASPECT_RATIOS,
    ACCELERATION_MODES,
    FALLBACK_MAX_PIXELS,
    normalizeAspectRatio,
    normalizeAccelerationMode,
    normalizeNode,
    availablePresets,
    resolvePreset,
    setCapabilities,
    setRuntimeStatus,
    getCapabilitySnapshot,
    getRuntimeStatus,
    getMaxPixels,
    getDimensionMultiple,
    getDurationRange,
    accelerationLabel
  };
})();
