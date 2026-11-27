// Pure Kandinsky ImageSR 2.0 state schema, tiling estimate, and connection policy. No DOM or transport.
(function () {
  const TYPE = 'kandinsky_sr';
  const MODEL_ID = 'kandinsky-imagesr-2.0';
  const WIDTH = 480;
  const HEIGHT = 300;
  const TILE_SIZE = 1024;

  const defaults = Object.freeze({
    upscale_factor: 2,
    creativity: 4,
    overlap: 0.25,
  });

  const choices = Object.freeze({
    upscale_factor: Object.freeze([2, 4]),
    overlap: Object.freeze([0.125, 0.25, 0.375]),
  });

  const CREATIVITY_LEVELS = Object.freeze([
    Object.freeze([0, '0 · 极致保真']),
    Object.freeze([1, '1 · 高度保真']),
    Object.freeze([2, '2 · 偏保真']),
    Object.freeze([3, '3 · 轻度增强']),
    Object.freeze([4, '4 · 标准推荐']),
    Object.freeze([5, '5 · 细节增强']),
    Object.freeze([6, '6 · 创意增强']),
    Object.freeze([7, '7 · 强细节重绘']),
    Object.freeze([8, '8 · 最大创意']),
  ]);

  const OVERLAP_OPTIONS = Object.freeze([
    Object.freeze([0.125, '12.5% · 快速']),
    Object.freeze([0.25, '25% · 推荐']),
    Object.freeze([0.375, '37.5% · 细腻']),
  ]);

  function normalizeOptions(raw) {
    const src = raw && typeof raw === 'object' ? raw : {};
    const factorNum = Number(src.upscale_factor ?? src.upscaleFactor);
    const upscale_factor = choices.upscale_factor.includes(factorNum) ? factorNum : defaults.upscale_factor;

    const creativityNum = Number(src.creativity);
    const creativity = Number.isFinite(creativityNum) && src.creativity !== '' && src.creativity !== null && typeof src.creativity !== 'boolean'
      ? Math.max(0, Math.min(8, Math.round(creativityNum)))
      : defaults.creativity;

    const overlapNum = Number(src.overlap);
    const matchedOverlap = choices.overlap.find(v => Math.abs(v - overlapNum) <= 1e-6);
    const overlap = matchedOverlap !== undefined && src.overlap !== '' && src.overlap !== null && typeof src.overlap !== 'boolean'
      ? matchedOverlap
      : defaults.overlap;

    return { upscale_factor, creativity, overlap };
  }

  function normalize(node) {
    node.width = WIDTH;
    node.height = HEIGHT;
    node.model = MODEL_ID;
    node.kandinsky_sr = normalizeOptions(node.kandinsky_sr);
    node.output = {
      archiveEnabled: true,
      telegramEnabled: node.output?.telegramEnabled === true,
    };
    return node;
  }

  function axisPositions(length, tile, stride) {
    if (length <= tile) return 1;
    let count = 0;
    let last = 0;
    for (let pos = 0; pos < length - tile; pos += stride) {
      count += 1;
      last = pos;
    }
    if (count === 0 || last + tile < length) count += 1;
    return count;
  }

  function estimateTiles(width, height, factor = 2, overlap = 0.25) {
    const w = Math.max(1, Math.round(Number(width) || 0));
    const h = Math.max(1, Math.round(Number(height) || 0));
    const f = choices.upscale_factor.includes(Number(factor)) ? Number(factor) : 2;
    const ov = choices.overlap.includes(Number(overlap)) ? Number(overlap) : 0.25;
    const lqTile = Math.floor(TILE_SIZE / f);
    const stride = Math.max(1, Math.floor(lqTile * (1.0 - ov)));
    const paddedW = Math.max(w, lqTile);
    const paddedH = Math.max(h, lqTile);
    return axisPositions(paddedH, lqTile, stride) * axisPositions(paddedW, lqTile, stride);
  }

  const targets = Object.freeze({
    image: Object.freeze([TYPE]),
    layout: Object.freeze([TYPE]),
    pose: Object.freeze([TYPE]),
    input: Object.freeze([TYPE]),
    comfy: Object.freeze([TYPE]),
    krea2: Object.freeze([TYPE]),
    qwen21: Object.freeze([TYPE]),
    moss: Object.freeze([TYPE]),
    [TYPE]: Object.freeze(['image']),
  });

  function policy(from, to) {
    return targets[from?.type]?.includes(to?.type)
      ? { inputRole: 'image', outputRole: 'image', single: true, replaceAllInputs: true }
      : null;
  }

  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M15 3h6v6"/><path d="m21 3-7 7"/><rect x="3" y="10" width="11" height="11" rx="2"/><path d="M7 17l2.5-2.5L12 17"/></svg>';

  window.DesktopKandinskySrModel = Object.freeze({
    TYPE,
    MODEL_ID,
    WIDTH,
    HEIGHT,
    TILE_SIZE,
    defaults,
    choices,
    CREATIVITY_LEVELS,
    OVERLAP_OPTIONS,
    normalizeOptions,
    normalize,
    estimateTiles,
    targets,
    policy,
    ICON,
    menu: Object.freeze({
      type: TYPE,
      title: 'Kandinsky SR 2.0',
      subtitle: '2x / 4x 生成式超分',
      icon: ICON,
    }),
  });
})();
