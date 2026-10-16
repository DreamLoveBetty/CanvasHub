(function () {
  // 神灯引擎：面板快照（计算样式烘焙 + 图片内联）+ 逐行翘曲动画，绘制在共享覆盖层画布
  // #deskHistoryGenieCanvas 上。最近记录面板与提示词抽屉经 window.DeskGenieFX 共用；
  // 面板几何、开合状态与运行序号由调用方持有，这里不读取任何面板或业务状态。
  function genieCanvas() {
    return document.getElementById('deskHistoryGenieCanvas');
  }

  const HISTORY_GENIE_DURATION_MS = 500;

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeInOutCubic = t => (
    t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
  );
  const easeInQuad = t => t * t;
  const easeOutQuad = t => 1 - (1 - t) * (1 - t);

  function historyGenieCanvasReady() {
    return Boolean(genieCanvas()?.getContext);
  }

  function setupHistoryGenieCanvas() {
    const canvas = genieCanvas();
    if (!canvas?.getContext) return null;
    const width = window.innerWidth || document.documentElement.clientWidth || 1;
    const height = window.innerHeight || document.documentElement.clientHeight || 1;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.ceil(width * dpr);
    canvas.height = Math.ceil(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { canvas, ctx, width, height };
  }

  function drawHistoryPanelFallback(rect) {
    const canvas = document.createElement('canvas');
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    const radius = 7;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.strokeStyle = 'rgba(180,210,235,0.55)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(radius, 0);
    ctx.lineTo(width - radius, 0);
    ctx.quadraticCurveTo(width, 0, width, radius);
    ctx.lineTo(width, height - radius);
    ctx.quadraticCurveTo(width, height, width - radius, height);
    ctx.lineTo(radius, height);
    ctx.quadraticCurveTo(0, height, 0, height - radius);
    ctx.lineTo(0, radius);
    ctx.quadraticCurveTo(0, 0, radius, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = 'rgba(22,32,43,0.86)';
    ctx.font = '700 14px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.fillText('最近记录', 14, 28);
    for (let y = 54; y < height - 22; y += 52) {
      ctx.fillStyle = 'rgba(255,255,255,0.38)';
      ctx.fillRect(12, y, width - 24, 40);
      ctx.fillStyle = 'rgba(99,113,130,0.28)';
      ctx.fillRect(24, y + 12, width - 72, 5);
      ctx.fillRect(24, y + 24, width - 108, 4);
    }
    return canvas;
  }

  // SVG-as-Image 光栅化时浏览器禁止一切外部加载（缩略图全空白），且主题 CSS 变量
  // 在裸克隆里无法解析（背景全白）——这就是旧版"白板神灯"的成因。
  // 新管线：把每个元素的计算样式烘焙成内联样式（变量/主题全部已解析），
  // 缩略图直接从已加载的 <img> 像素转 dataURL 内联，零网络依赖。
  const GENIE_BAKE_PROPS = [
    'display', 'visibility', 'box-sizing',
    'width', 'height', 'min-width', 'min-height', 'max-width', 'max-height',
    'margin', 'padding', 'border', 'border-radius', 'outline',
    'background-color', 'background-position', 'background-size', 'background-repeat',
    'color', 'font-family', 'font-size', 'font-weight', 'font-style',
    'line-height', 'letter-spacing', 'text-align', 'text-overflow', 'text-transform',
    'white-space', 'word-break', 'overflow', 'overflow-x', 'overflow-y',
    'flex-direction', 'flex-wrap', 'flex-grow', 'flex-shrink', 'flex-basis',
    'align-items', 'align-self', 'justify-content', 'gap',
    'grid-template-columns', 'grid-auto-rows', 'grid-auto-flow',
    'position', 'top', 'right', 'bottom', 'left', 'z-index',
    'opacity', 'box-shadow', 'object-fit', 'object-position',
    'transform', 'transform-origin'
  ];

  function genieBakeElementStyles(source, target, computedStyle = null) {
    const computed = computedStyle || getComputedStyle(source);
    let cssText = '';
    for (const prop of GENIE_BAKE_PROPS) {
      const value = computed.getPropertyValue(prop);
      if (value) cssText += `${prop}:${value};`;
    }
    // 渐变类 background-image 可烘焙；url() 引用（含 mask 图标）在 SVG 图像里无法加载，
    // 直接跳过并同时放弃底色，避免图标变成实心色块
    const backgroundImage = computed.getPropertyValue('background-image');
    const maskImage = computed.getPropertyValue('mask-image') || computed.getPropertyValue('-webkit-mask-image');
    if (maskImage && maskImage.includes('url(')) {
      cssText += 'background:transparent;';
    } else if (backgroundImage && backgroundImage !== 'none' && !backgroundImage.includes('url(')) {
      cssText += `background-image:${backgroundImage};`;
    }
    cssText += 'backdrop-filter:none;-webkit-backdrop-filter:none;transition:none;animation:none;';
    target.style.cssText = cssText;
  }

  function genieInlineImages(sourceRoot, cloneRoot, hiddenSources = null) {
    const sourceImgs = sourceRoot.querySelectorAll('img');
    const cloneImgs = cloneRoot.querySelectorAll('img');
    const count = Math.min(sourceImgs.length, cloneImgs.length);
    for (let i = 0; i < count; i++) {
      const source = sourceImgs[i];
      const clone = cloneImgs[i];
      if (hiddenSources?.has(source)) {
        clone.removeAttribute('src');
        continue;
      }
      try {
        if (source.complete && source.naturalWidth > 0) {
          const rect = source.getBoundingClientRect();
          const width = Math.max(1, Math.round(rect.width || source.naturalWidth));
          const height = Math.max(1, Math.round(rect.height || source.naturalHeight));
          const scale = Math.min(2, window.devicePixelRatio || 1);
          const canvas = document.createElement('canvas');
          canvas.width = width * scale;
          canvas.height = height * scale;
          canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
          clone.src = canvas.toDataURL('image/webp', 0.82);
        } else {
          clone.removeAttribute('src');
          clone.style.background = 'rgba(148,163,184,0.18)';
        }
      } catch (error) {
        clone.removeAttribute('src');
      }
    }
  }

  function genieSnapshotRasterSize(rect, options = {}) {
    const rectWidth = Math.max(1, Math.round(rect.width));
    const rectHeight = Math.max(1, Math.round(rect.height));
    const maxWidth = Math.max(1, Number(options.maxRasterWidth) || rectWidth);
    const maxHeight = Math.max(1, Number(options.maxRasterHeight) || rectHeight);
    const scale = Math.min(1, maxWidth / rectWidth, maxHeight / rectHeight);
    return {
      width: Math.max(1, Math.round(rectWidth * scale)),
      height: Math.max(1, Math.round(rectHeight * scale)),
      rectWidth,
      rectHeight
    };
  }

  async function snapshotHistoryPanel(panel, rect, options = {}) {
    const fallback = () => drawHistoryPanelFallback(rect);
    try {
      const clone = panel.cloneNode(true);
      // 并行遍历原树/克隆树烘焙计算样式（querySelectorAll 返回静态列表，索引一一对应）
      const sourceEls = panel.querySelectorAll('*');
      const cloneEls = clone.querySelectorAll('*');
      genieBakeElementStyles(panel, clone);
      const total = Math.min(sourceEls.length, cloneEls.length);
      const scrollPairs = [];
      const hiddenSources = options.skipHiddenSubtrees ? new WeakSet() : null;
      for (let i = 0; i < total; i++) {
        const source = sourceEls[i];
        const target = cloneEls[i];
        if (hiddenSources?.has(source.parentElement)) {
          hiddenSources.add(source);
          continue;
        }
        const computed = hiddenSources ? getComputedStyle(source) : null;
        if (hiddenSources && (source.hidden || computed.display === 'none')) {
          hiddenSources.add(source);
          target.style.cssText = 'display:none!important;';
          continue;
        }
        genieBakeElementStyles(source, target, computed);
        if (source.scrollTop > 0) scrollPairs.push([target, source.scrollTop]);
      }
      genieInlineImages(panel, clone, hiddenSources);
      // 还原滚动位置：把滚动容器的内容整体上移
      scrollPairs.forEach(([container, scrollTop]) => {
        const inner = document.createElement('div');
        inner.style.transform = `translateY(-${scrollTop}px)`;
        while (container.firstChild) inner.appendChild(container.firstChild);
        container.appendChild(inner);
        container.style.overflow = 'hidden';
      });
      clone.classList.remove('is-collapsed', 'is-genie-closing', 'is-genie-materializing');
      clone.style.position = 'relative';
      clone.style.top = '0';
      clone.style.right = 'auto';
      clone.style.bottom = 'auto';
      clone.style.left = '0';
      clone.style.width = `${Math.round(rect.width)}px`;
      clone.style.height = `${Math.round(rect.height)}px`;
      clone.style.margin = '0';
      clone.style.opacity = '1';
      clone.style.transform = 'none';
      clone.style.animation = 'none';
      clone.style.pointerEvents = 'none';
      clone.querySelector('#deskHistoryExpandBtn')?.remove();
      // 必须用 XMLSerializer：outerHTML 按 HTML 规则序列化（<img> 等空元素不自闭合），
      // 在严格 XML 解析的 SVG blob 里必然报错——旧版神灯从未成功渲染过、一直走白板兜底的根因
      const raster = genieSnapshotRasterSize(rect, options);
      const xhtml = new XMLSerializer().serializeToString(clone);
      const markup = `<svg xmlns="http://www.w3.org/2000/svg" width="${raster.width}" height="${raster.height}" viewBox="0 0 ${raster.rectWidth} ${raster.rectHeight}"><foreignObject width="${raster.rectWidth}" height="${raster.rectHeight}">${xhtml}</foreignObject></svg>`;
      const blob = new Blob([markup], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      try {
        const image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = reject;
          image.src = url;
        });
        const canvas = document.createElement('canvas');
        canvas.width = raster.width;
        canvas.height = raster.height;
        canvas.getContext('2d').drawImage(image, 0, 0);
        return canvas;
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      return fallback();
    }
  }

  function renderHistoryGenieFrame(ctx, source, viewportWidth, viewportHeight, progress, direction, target, panelRect) {
    ctx.clearRect(0, 0, viewportWidth, viewportHeight);
    const sourceWidth = source.width;
    const sourceHeight = source.height;
    const dock = {
      x: target.left + target.width / 2,
      y: target.top + target.height / 2
    };
    const win = {
      x: panelRect.left,
      y: panelRect.top,
      width: panelRect.width,
      height: panelRect.height
    };
    for (let y = 0; y < sourceHeight; y += 1) {
      const row = y / sourceHeight;
      const rowXStart = direction === 'minimize' ? (1 - row) * 0.65 : row * 0.65;
      const xProgress = clamp((progress - rowXStart) / (1 - rowXStart), 0, 1);
      const xEase = easeInOutCubic(xProgress);
      const rowYStart = direction === 'minimize' ? (1 - row) * 0.2 : row * 0.2;
      const yProgress = clamp((progress - rowYStart) / (1 - rowYStart), 0, 1);
      const yEase = easeInQuad(yProgress);
      let left;
      let right;
      let destY;
      const sourceY = y;
      const naturalY = win.y + (y / sourceHeight) * win.height;
      if (direction === 'minimize') {
        left = lerp(win.x, dock.x, xEase);
        right = lerp(win.x + win.width, dock.x, xEase);
        destY = lerp(naturalY, dock.y, yEase);
      } else {
        left = lerp(dock.x, win.x, xEase);
        right = lerp(dock.x, win.x + win.width, xEase);
        destY = lerp(dock.y, naturalY, yEase);
      }
      const rowWidth = right - left;
      if (rowWidth < 0.8) continue;
      ctx.drawImage(source, 0, sourceY, sourceWidth, 1, left, destY, rowWidth, Math.max(1, win.height / sourceHeight));
    }
    const glowRaw = direction === 'minimize' ? progress : 1 - progress;
    if (glowRaw > 0.75) {
      const alpha = easeOutQuad((glowRaw - 0.75) / 0.25) * 0.24;
      const gradient = ctx.createRadialGradient(dock.x, dock.y, 0, dock.x, dock.y, 58);
      gradient.addColorStop(0, `rgba(255,255,255,${alpha})`);
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, viewportWidth, viewportHeight);
    }
  }

  // 通用神灯运行器：最近记录面板与提示词抽屉共用（经 window.DeskGenieFX 暴露）
  function runGenieAnimationCore({ direction, source, targetRect, panelRect, duration = HISTORY_GENIE_DURATION_MS, isCancelled = () => false, onStart, onDone }) {
    const setup = setupHistoryGenieCanvas();
    if (!setup) {
      onStart?.();
      onDone?.();
      return { cancel() {} };
    }
    const { canvas, ctx, width, height } = setup;
    let raf = 0;
    let startedAt = 0;
    const stop = () => {
      if (raf) {
        window.cancelAnimationFrame(raf);
        raf = 0;
      }
      ctx.clearRect(0, 0, width, height);
      canvas.classList.remove('is-active');
    };
    canvas.classList.add('is-active');
    onStart?.();
    const tick = timestamp => {
      raf = 0;
      if (isCancelled()) {
        stop();
        return;
      }
      if (!startedAt) startedAt = timestamp;
      const progress = clamp((timestamp - startedAt) / duration, 0, 1);
      renderHistoryGenieFrame(ctx, source, width, height, progress, direction, targetRect, panelRect);
      if (progress < 1) {
        raf = window.requestAnimationFrame(tick);
        return;
      }
      stop();
      onDone?.();
    };
    raf = window.requestAnimationFrame(tick);
    return { cancel: stop };
  }

  function clearHistoryGenieCanvas() {
    const canvas = genieCanvas();
    if (!canvas?.getContext) return;
    const width = window.innerWidth || document.documentElement.clientWidth || 1;
    const height = window.innerHeight || document.documentElement.clientHeight || 1;
    canvas.classList.remove('is-active');
    canvas.getContext('2d')?.clearRect(0, 0, width, height);
  }

  window.DeskGenieFX = {
    ready: historyGenieCanvasReady,
    snapshotPanel: snapshotHistoryPanel,
    animate: runGenieAnimationCore,
    clear: clearHistoryGenieCanvas,
    durationMs: HISTORY_GENIE_DURATION_MS
  };
})();
