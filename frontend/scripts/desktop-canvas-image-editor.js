// 图片编辑器模态 UI、视口缩放、Fabric 生命周期/鼠标交互、项目序列化、历史快照、蒙版与标注导出、会话打开保存关闭。真实生成提交保留宿主。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    IMAGE_EDIT_MAX_ZOOM,
    IMAGE_EDIT_MIN_ZOOM,
    IMAGE_EDIT_UI_SCALE,
    IMAGE_EDIT_ZOOM_STEP,
    activeImageEditRef,
    applyImageEditObjectControls,
    createImageEditArrow,
    createImageEditPin,
    createImageEditShape,
    createImageEditTextStyle,
    downloadDataUrl,
    downloadJsonObject,
    fileToDataUrl,
    getImageEditObjects,
    getImageEditPinNumber,
    getImageEditShapeIcon,
    getImageEditShapeMode,
    getImageEditToolIcon,
    getNodeBoundsById,
    getViewportCenterWorldPoint,
    handleImageEditSelectionChange,
    imageEditorCanvasRef,
    imageEditorElRef,
    insertImageNode,
    isImageEditShapeEllipse,
    normalizeImageEditColor,
    readImageMeta,
    refreshImageNode,
    removeImageEditObjects,
    setImageEditBrushSize,
    setImageEditColor,
    setImageEditObjectMeta,
    setImageEditShapeMode,
    setImageEditTool,
    updateImageEditArrow,
  }) {
    let imageEditorThemeObserver = null;

    function ensureImageEditor() {
    if (imageEditorElRef.current) return imageEditorElRef.current;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="desk-image-editor" id="deskImageEditor" aria-hidden="true">
        <div class="desk-image-editor__panel" role="dialog" aria-modal="true" aria-label="图片编辑">
          <header class="desk-image-editor__bar">
            <div class="desk-image-editor__bar-copy">
              <h2 data-image-edit-title>图片编辑</h2>
              <div class="desk-image-editor__status" data-image-edit-status>就绪</div>
            </div>
            <div class="desk-image-editor__bar-actions">
              <button type="button" class="desk-image-editor__icon-btn" data-image-edit-undo title="撤销" aria-label="撤销">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14 4 9l5-5"></path><path d="M5 9h8a6 6 0 1 1 0 12H8"></path></svg>
              </button>
              <button type="button" class="desk-image-editor__icon-btn" data-image-edit-redo title="重做" aria-label="重做">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 14 20 9l-5-5"></path><path d="M19 9h-8a6 6 0 1 0 0 12h5"></path></svg>
              </button>
              <button type="button" class="desk-image-editor__close" data-image-edit-close title="关闭" aria-label="关闭">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>
              </button>
            </div>
          </header>
          <div class="desk-image-editor__body">
            <section class="desk-image-editor__stage">
              <aside class="desk-image-editor__rail desk-image-editor__rail--top" aria-label="编辑工具">
                <div class="desk-image-editor__tool-grid">
                  ${[
                    ['select', '选择'],
                    ['brush', '画笔'],
                    ['maskBrush', '蒙版'],
                    ['shape', '形状'],
                    ['arrow', '箭头'],
                    ['text', '文字'],
                    ['pin', 'Pin'],
                    ['eraser', '橡皮']
                  ].map(([tool, label]) => `
                    <button type="button" class="desk-image-editor__tool" data-image-edit-tool="${tool}" title="${label}" aria-label="${label}">
                      <img class="desk-image-editor__tool-icon" src="${getImageEditToolIcon(tool)}" alt="" aria-hidden="true" draggable="false">
                      <span>${label}</span>
                    </button>
                  `).join('')}
                </div>
                <div class="desk-image-editor__swatch-group">
                  <div class="desk-image-editor__label">颜色</div>
                  <div class="desk-image-editor__swatches" data-image-edit-swatches>
                    ${['#0b57d0', '#ff6a22', '#11a36c', '#8b5cf6', '#111827', '#ffffff'].map((color, index) => `
                      <button type="button" class="desk-image-editor__swatch${index === 0 ? ' is-active' : ''}" data-image-edit-color="${color}" title="${color}" aria-label="${color}" style="--desk-swatch:${color}"></button>
                    `).join('')}
                  </div>
                </div>
                <div class="desk-image-editor__shape-options">
                  <div class="desk-image-editor__label">形状</div>
                  <div class="desk-image-editor__shape-grid">
                  ${[
                      ['rectOutline', '空心矩形'],
                      ['rectFilled', '实心矩形'],
                      ['ellipseOutline', '空心圆形'],
                      ['ellipseFilled', '实心圆形']
                    ].map(([shape, label], index) => `
                      <button type="button" class="desk-image-editor__shape${index === 0 ? ' is-active' : ''}" data-image-edit-shape="${shape}" title="${label}" aria-label="${label}" aria-pressed="${index === 0 ? 'true' : 'false'}">
                        <svg viewBox="0 0 24 24" aria-hidden="true">${getImageEditShapeIcon(shape)}</svg>
                      </button>
                    `).join('')}
                  </div>
                </div>
                <label class="desk-image-editor__range">
                  <span>笔触</span>
                  <input type="range" min="2" max="120" value="22" data-image-edit-size>
                </label>
                <div class="desk-image-editor__zoom" aria-label="图片缩放">
                  <button type="button" class="desk-image-editor__zoom-btn" data-image-edit-zoom-out title="缩小" aria-label="缩小">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"></path></svg>
                  </button>
                  <output class="desk-image-editor__zoom-label" data-image-edit-zoom-label>适配</output>
                  <button type="button" class="desk-image-editor__zoom-btn" data-image-edit-zoom-in title="放大" aria-label="放大">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
                  </button>
                  <button type="button" class="desk-image-editor__button desk-image-editor__button--compact" data-image-edit-zoom-fit title="适配图片">适配</button>
                </div>
                <div class="desk-image-editor__stack desk-image-editor__stack--utility">
                  <button type="button" class="desk-image-editor__button" data-image-edit-clear-annotations>清空标注</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-clear-mask>清空蒙版</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-import>导入图片</button>
                </div>
              </aside>
              <div class="desk-image-editor__canvas-shell">
                <div class="desk-image-editor__canvas-wrap">
                  <canvas data-image-edit-fabric></canvas>
                </div>
              </div>
              <aside class="desk-image-editor__rail desk-image-editor__rail--bottom" aria-label="导出">
                <div class="desk-image-editor__stack desk-image-editor__stack--bundle">
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-annotated>导出合成图</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-node>导出到桌面节点</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-mask>导出 mask</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-json>导出 JSON</button>
                </div>
                <p class="desk-image-editor__source" data-image-edit-source hidden>未载入图片</p>
                <input type="file" accept="image/*" data-image-edit-import-input hidden>
              </aside>
            </section>
          </div>
        </div>
      </div>
    `);
    imageEditorElRef.current = document.getElementById('deskImageEditor');
    imageEditorElRef.current?.style.setProperty('--desk-image-editor-ui-scale', String(IMAGE_EDIT_UI_SCALE));
    bindImageEditorEvents(imageEditorElRef.current);
    return imageEditorElRef.current;
  }

    function getImageEditorCanvasElement() {
    return imageEditorElRef.current?.querySelector('[data-image-edit-fabric]');
  }

    function getImageEditorCanvas() {
    return imageEditorCanvasRef.current;
  }

    function getImageEditorCanvasShell() {
    return imageEditorElRef.current?.querySelector('.desk-image-editor__canvas-shell');
  }

    function getImageEditorCanvasWrap() {
    return imageEditorElRef.current?.querySelector('.desk-image-editor__canvas-wrap');
  }

    function applyImageEditCanvasPanOffset(x = 0, y = 0) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    const wrap = getImageEditorCanvasWrap();
    const nextX = Number.isFinite(Number(x)) ? Number(x) : 0;
    const nextY = Number.isFinite(Number(y)) ? Number(y) : 0;
    if (wrap) wrap.style.transform = '';
    if (canvas?.viewportTransform) {
      const cssScale = getImageEditCanvasCssScale(canvas);
      const viewport = canvas.viewportTransform.slice();
      viewport[4] = nextX / cssScale;
      viewport[5] = nextY / cssScale;
      const clamped = clampImageEditViewportTransform(canvas, viewport);
      canvas.setViewportTransform(clamped);
      if (state) {
        state.canvasPanX = clamped[4] * cssScale;
        state.canvasPanY = clamped[5] * cssScale;
      }
      canvas.requestRenderAll?.();
      return;
    }
    if (state) {
      state.canvasPanX = nextX;
      state.canvasPanY = nextY;
    }
  }

    function clampImageEditZoom(value, fallback = 1) {
    const numeric = Number(value);
    const next = Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
    return Math.max(IMAGE_EDIT_MIN_ZOOM, Math.min(IMAGE_EDIT_MAX_ZOOM, next));
  }

    function getImageEditDisplaySize(width, height) {
    const sourceWidth = Math.max(1, Number(width) || 1);
    const sourceHeight = Math.max(1, Number(height) || 1);
    const shell = getImageEditorCanvasShell();
    const availableWidth = Math.max(240, (shell?.clientWidth || (window.innerWidth - 220)) - 32);
    const availableHeight = Math.max(220, (shell?.clientHeight || (window.innerHeight - 190)) - 32);
    const fitScale = Math.min(1, availableWidth / sourceWidth, availableHeight / sourceHeight);
    const state = getImageEditState();
    let imageScale = fitScale;
    if (state) {
      state.fitScale = fitScale;
      if (state.zoomMode === 'manual') {
        imageScale = clampImageEditZoom(state.displayZoom, fitScale);
        state.displayZoom = imageScale;
      } else {
        state.zoomMode = 'fit';
        state.displayZoom = fitScale;
      }
    }
    return {
      width: Math.max(1, Math.round(sourceWidth * fitScale)),
      height: Math.max(1, Math.round(sourceHeight * fitScale)),
      scale: imageScale,
      fitScale
    };
  }

    function getImageEditCanvasCssScale(canvas = getImageEditorCanvas()) {
    if (!canvas?.lowerCanvasEl) return 1;
    const rect = canvas.lowerCanvasEl.getBoundingClientRect?.();
    const sourceWidth = Math.max(1, Number(canvas.getWidth?.() || canvas.lowerCanvasEl.width || 1));
    const cssWidth = Math.max(1, Number(rect?.width || sourceWidth));
    return Math.max(0.01, cssWidth / sourceWidth);
  }

    function getImageEditViewportCenter(canvas = getImageEditorCanvas()) {
    if (!canvas) return null;
    const viewport = canvas.viewportTransform || [1, 0, 0, 1, 0, 0];
    const zoom = Math.max(0.01, Number(viewport[0] || canvas.getZoom?.() || 1));
    return {
      x: ((canvas.getWidth?.() || 1) / 2 - Number(viewport[4] || 0)) / zoom,
      y: ((canvas.getHeight?.() || 1) / 2 - Number(viewport[5] || 0)) / zoom
    };
  }

    function clampImageEditViewportTransform(canvas, transform) {
    if (!canvas) return transform || [1, 0, 0, 1, 0, 0];
    const viewport = (transform || canvas.viewportTransform || [1, 0, 0, 1, 0, 0]).slice();
    const zoom = Math.max(0.01, Number(viewport[0] || 1));
    const width = Math.max(1, Number(canvas.getWidth?.() || 1));
    const height = Math.max(1, Number(canvas.getHeight?.() || 1));
    if (zoom <= 1) {
      viewport[4] = (width - width * zoom) / 2;
      viewport[5] = (height - height * zoom) / 2;
    } else {
      viewport[4] = Math.min(0, Math.max(width - width * zoom, Number(viewport[4] || 0)));
      viewport[5] = Math.min(0, Math.max(height - height * zoom, Number(viewport[5] || 0)));
    }
    return viewport;
  }

    function applyImageEditViewportZoom(canvas, viewportZoom, center = null) {
    if (!canvas) return;
    const zoom = Math.max(0.01, Number(viewportZoom) || 1);
    const width = Math.max(1, Number(canvas.getWidth?.() || 1));
    const height = Math.max(1, Number(canvas.getHeight?.() || 1));
    const focus = center || { x: width / 2, y: height / 2 };
    let viewport = [zoom, 0, 0, zoom, width / 2 - focus.x * zoom, height / 2 - focus.y * zoom];
    viewport = clampImageEditViewportTransform(canvas, viewport);
    canvas.setViewportTransform(viewport);
    const state = getImageEditState();
    if (state) {
      const cssScale = getImageEditCanvasCssScale(canvas);
      state.canvasPanX = viewport[4] * cssScale;
      state.canvasPanY = viewport[5] * cssScale;
    }
  }

    function refreshImageEditObjectControls() {
    const canvas = getImageEditorCanvas();
    if (!canvas) return;
    canvas.getObjects()
      .filter(object => object?.editRole && object.editRole !== 'baseImage')
      .forEach(object => applyImageEditObjectControls(object, object.stroke || object.fill || object.annotationColor || object.maskColor || '#0b57d0'));
  }

    function updateImageEditZoomUi() {
    const state = getImageEditState();
    const zoomLabel = imageEditorElRef.current?.querySelector('[data-image-edit-zoom-label]');
    const zoomOut = imageEditorElRef.current?.querySelector('[data-image-edit-zoom-out]');
    const zoomIn = imageEditorElRef.current?.querySelector('[data-image-edit-zoom-in]');
    const zoomFit = imageEditorElRef.current?.querySelector('[data-image-edit-zoom-fit]');
    if (!state) return;
    const zoom = clampImageEditZoom(state.displayZoom || state.fitScale || 1, state.fitScale || 1);
    if (zoomLabel) zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
    if (zoomOut) zoomOut.disabled = zoom <= IMAGE_EDIT_MIN_ZOOM + 0.001;
    if (zoomIn) zoomIn.disabled = zoom >= IMAGE_EDIT_MAX_ZOOM - 0.001;
    if (zoomFit) zoomFit.disabled = state.zoomMode === 'fit';
  }

    function applyImageEditCanvasDisplaySize(canvas, width, height, options = {}) {
    if (!canvas) return;
    const sourceWidth = Math.max(1, Math.round(Number(width) || canvas.getWidth() || 1));
    const sourceHeight = Math.max(1, Math.round(Number(height) || canvas.getHeight() || 1));
    const center = options.center || (options.preserveViewport === false ? null : getImageEditViewportCenter(canvas));
    const display = getImageEditDisplaySize(sourceWidth, sourceHeight);
    canvas.setDimensions({ width: sourceWidth, height: sourceHeight }, { backstoreOnly: true });
    canvas.setDimensions({ width: display.width, height: display.height }, { cssOnly: true });
    if (canvas.wrapperEl) {
      canvas.wrapperEl.style.setProperty('width', `${display.width}px`, 'important');
      canvas.wrapperEl.style.setProperty('height', `${display.height}px`, 'important');
      canvas.wrapperEl.style.setProperty('max-width', 'none', 'important');
      canvas.wrapperEl.style.setProperty('max-height', 'none', 'important');
    }
    [canvas.lowerCanvasEl, canvas.upperCanvasEl].forEach(canvasEl => {
      if (!canvasEl) return;
      canvasEl.style.setProperty('width', `${display.width}px`, 'important');
      canvasEl.style.setProperty('height', `${display.height}px`, 'important');
      canvasEl.style.setProperty('max-width', 'none', 'important');
      canvasEl.style.setProperty('max-height', 'none', 'important');
    });
    const sourceEl = getImageEditorCanvasElement();
    if (sourceEl) {
      sourceEl.style.setProperty('width', `${display.width}px`, 'important');
      sourceEl.style.setProperty('height', `${display.height}px`, 'important');
    }
    const viewportZoom = display.fitScale > 0 ? display.scale / display.fitScale : 1;
    applyImageEditViewportZoom(canvas, viewportZoom, center);
    canvas.calcOffset?.();
    refreshImageEditObjectControls();
    canvas.requestRenderAll?.();
    updateImageEditZoomUi();
  }

    function setImageEditZoom(value, mode = 'manual') {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    const center = mode === 'fit' ? null : getImageEditViewportCenter(canvas);
    if (mode === 'fit') {
      state.zoomMode = 'fit';
      state.displayZoom = state.fitScale || 1;
    } else {
      state.zoomMode = 'manual';
      state.displayZoom = clampImageEditZoom(value, state.displayZoom || state.fitScale || 1);
    }
    applyImageEditCanvasDisplaySize(canvas, state.sourceWidth, state.sourceHeight, {
      center,
      preserveViewport: mode !== 'fit'
    });
    updateImageEditZoomUi();
  }

    function getImageEditCanvasDisplayScale(canvas = getImageEditorCanvas()) {
    const cssScale = getImageEditCanvasCssScale(canvas);
    const viewportZoom = Math.max(0.01, Number(canvas?.getZoom?.() || 1));
    return Math.max(0.01, cssScale * viewportZoom);
  }

    function imageEditScreenToCanvasSize(value, canvas = getImageEditorCanvas()) {
    const numeric = Math.max(0, Number(value) || 0);
    return numeric / getImageEditCanvasDisplayScale(canvas);
  }

    function getImageEditorPromptInput() {
    return null;
  }

    function getImageEditorStatusEl() {
    return imageEditorElRef.current?.querySelector('[data-image-edit-status]');
  }

    function getImageEditorSourceEl() {
    return imageEditorElRef.current?.querySelector('[data-image-edit-source]');
  }

    function getImageEditCustomProps() {
    return ['id', 'editRole', 'editKind', 'shapeMode', 'maskRole', 'label', 'pinNumber', 'sourceTool', 'strokeKind', 'annotationColor', 'maskColor', 'sourceNodeId', 'erasable'];
  }

    function cloneImageEditValue(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }

    function createImageEditId(prefix = 'image-edit') {
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

    function sanitizeImageEditFilename(name, fallback = 'image-edit') {
    return String(name || fallback)
      .trim()
      .replace(/[\\/:*?"<>|]+/g, '-')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '') || fallback;
  }

    function getImageEditState() {
    return activeImageEditRef.current || null;
  }

    function setImageEditStatus(message = '就绪', tone = 'info') {
    const el = getImageEditorStatusEl();
    if (!el) return;
    el.dataset.tone = tone || 'info';
    el.textContent = message || '就绪';
  }

    function updateImageEditSourceLabel() {
    const el = getImageEditorSourceEl();
    const state = getImageEditState();
    if (!el || !state) return;
    const parts = [];
    if (state.sourceName) parts.push(state.sourceName);
    if (state.sourceWidth && state.sourceHeight) parts.push(`${state.sourceWidth} × ${state.sourceHeight}`);
    if (state.projectJson?.annotationCount !== undefined) parts.push(`${state.projectJson.annotationCount} 个标注`);
    if (state.projectJson?.maskCount !== undefined) parts.push(`${state.projectJson.maskCount} 个蒙版对象`);
    el.textContent = parts.join(' · ') || '已载入图片';
  }

    function updateImageEditUndoRedoButtons() {
    const state = getImageEditState();
    const undoBtn = imageEditorElRef.current?.querySelector('[data-image-edit-undo]');
    const redoBtn = imageEditorElRef.current?.querySelector('[data-image-edit-redo]');
    if (undoBtn) undoBtn.disabled = !state || !state.undoStack || state.undoStack.length <= 1;
    if (redoBtn) redoBtn.disabled = !state || !state.redoStack || state.redoStack.length === 0;
  }

    function isImageEditDarkTheme() {
    return String(document.body?.dataset?.theme || '').toLowerCase() === 'dark';
  }

    function syncImageEditToolIconFilters() {
    if (!imageEditorElRef.current) return;
    const darkTheme = isImageEditDarkTheme();
    imageEditorElRef.current.querySelectorAll('[data-image-edit-tool]').forEach(button => {
      const icon = button.querySelector('.desk-image-editor__tool-icon');
      if (!icon) return;
      const isActive = button.classList.contains('is-active');
      icon.style.filter = darkTheme || isActive ? 'brightness(0) invert(1)' : 'none';
    });
  }

    function ensureImageEditorThemeObserver() {
    if (imageEditorThemeObserver || !document.body) return;
    imageEditorThemeObserver = new MutationObserver(() => syncImageEditToolIconFilters());
    imageEditorThemeObserver.observe(document.body, { attributes: true, attributeFilter: ['data-theme'] });
  }

    function updateImageEditToolUi() {
    const state = getImageEditState();
    if (!state || !imageEditorElRef.current) return;
    imageEditorElRef.current.querySelectorAll('[data-image-edit-tool]').forEach(button => {
      const active = String(button.dataset.imageEditTool || '') === state.tool;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    imageEditorElRef.current.querySelectorAll('[data-image-edit-color]').forEach(button => {
      const active = normalizeImageEditColor(button.dataset.imageEditColor) === state.color;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    imageEditorElRef.current.querySelectorAll('[data-image-edit-shape]').forEach(button => {
      const active = String(button.dataset.imageEditShape || '') === getImageEditShapeMode(state);
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const sizeInput = imageEditorElRef.current.querySelector('[data-image-edit-size]');
    if (sizeInput) sizeInput.value = String(state.brushSize || 22);
    syncImageEditToolIconFilters();
    updateImageEditZoomUi();
    updateImageEditSourceLabel();
    updateImageEditUndoRedoButtons();
  }

    function serializeImageEditObject(object) {
    if (!object?.toObject) return null;
    const json = object.toObject(getImageEditCustomProps());
    if (object.erasable !== undefined) {
      json.erasable = object.erasable;
    }
    if (object.eraser?.toObject) {
      json.eraser = object.eraser.toObject(getImageEditCustomProps());
    }
    return json;
  }

    function serializeImageEditCanvas() {
    const canvas = getImageEditorCanvas();
    if (!canvas) return null;
    const json = canvas.toJSON(getImageEditCustomProps());
    json.objects = (canvas.getObjects?.() || [])
      .filter(object => object?.editRole !== 'baseImage')
      .map(object => serializeImageEditObject(object))
      .filter(Boolean);
    return json;
  }

    function buildImageEditProjectJson(state = getImageEditState()) {
    const canvas = getImageEditorCanvas();
    if (!canvas || !state) return null;
    return {
      version: 1,
      source: {
        nodeId: state.nodeId || '',
        name: state.sourceName || '',
        mimeType: state.sourceMimeType || 'image/png',
        width: state.sourceWidth || canvas.getWidth() || 1,
        height: state.sourceHeight || canvas.getHeight() || 1
      },
      canvasJson: serializeImageEditCanvas(),
      tool: state.tool || 'select',
      color: state.color || '#0b57d0',
      shapeMode: getImageEditShapeMode(state),
      brushSize: state.brushSize || 22,
      pinCounter: getImageEditPinNumber(),
      hasMask: Boolean(getImageEditObjects('mask').length || state.legacyMaskDataUrl),
      maskCount: getImageEditObjects('mask').length,
      annotationCount: getImageEditObjects('annotation').length
    };
  }

    function createImageEditSnapshot(state = getImageEditState()) {
    if (!state) return null;
    return {
      canvasJson: serializeImageEditCanvas(),
      prompt: String(getImageEditorPromptInput()?.value || '').trim(),
      tool: state.tool || 'select',
      color: state.color || '#0b57d0',
      shapeMode: getImageEditShapeMode(state),
      brushSize: state.brushSize || 22,
      legacyMaskDataUrl: state.legacyMaskDataUrl || '',
      sourceName: state.sourceName || '',
      sourceWidth: state.sourceWidth || 1,
      sourceHeight: state.sourceHeight || 1
    };
  }

    function imageEditSnapshotKey(snapshot) {
    return snapshot ? JSON.stringify(snapshot) : '';
  }

    function resetImageEditHistory(snapshot = null) {
    const state = getImageEditState();
    if (!state) return;
    state.undoStack = [];
    state.redoStack = [];
    state.historyKey = '';
    if (snapshot) {
      state.undoStack.push(cloneImageEditValue(snapshot));
      state.historyKey = imageEditSnapshotKey(snapshot);
    }
    updateImageEditUndoRedoButtons();
  }

    function recordImageEditSnapshot(label = '') {
    const state = getImageEditState();
    if (!state || state.restoring) return;
    const snapshot = createImageEditSnapshot();
    if (!snapshot) return;
    const key = imageEditSnapshotKey(snapshot);
    if (!key || key === state.historyKey) return;
    state.undoStack.push(snapshot);
    if (state.undoStack.length > state.historyLimit) state.undoStack.shift();
    state.redoStack = [];
    state.historyKey = key;
    state.projectJson = buildImageEditProjectJson(state);
    updateImageEditSourceLabel();
    updateImageEditUndoRedoButtons();
    if (label) setImageEditStatus(`${label}，可继续编辑`, 'info');
  }

    async function loadFabricImage(src) {
    if (!src) return null;
    return new Promise((resolve, reject) => {
      fabric.Image.fromURL(src, image => {
        if (!image) {
          reject(new Error('图片加载失败'));
          return;
        }
        resolve(image);
      }, { crossOrigin: 'anonymous' });
    });
  }

    async function loadImageEditSource(sourceDataUrl, width, height, overlayJson = null, legacyMaskDataUrl = '') {
    const canvas = ensureImageEditFabricCanvas();
    const canvasWidth = Math.max(1, Math.round(Number(width) || 1));
    const canvasHeight = Math.max(1, Math.round(Number(height) || 1));
    canvas.clear();
    applyImageEditCanvasPanOffset(0, 0);
    applyImageEditCanvasDisplaySize(canvas, canvasWidth, canvasHeight, { preserveViewport: false });
    canvas.backgroundColor = 'transparent';
    if (overlayJson?.objects?.length) {
      await new Promise(resolve => {
        canvas.loadFromJSON(cloneImageEditValue(overlayJson), () => resolve());
      });
      canvas.getObjects().forEach(object => {
        if (object?.editRole && object.editRole !== 'baseImage') {
          object.set({
            erasable: true,
            objectCaching: false
          });
          applyImageEditObjectControls(object, object.stroke || object.fill || object.annotationColor || object.maskColor || '#0b57d0');
          object.setCoords?.();
        }
      });
    }
    const image = await loadFabricImage(sourceDataUrl);
    if (!image) throw new Error('图片加载失败');
    const baseWidth = canvasWidth || image.width || 1;
    const baseHeight = canvasHeight || image.height || 1;
    image.set({
      left: 0,
      top: 0,
      originX: 'left',
      originY: 'top',
      selectable: false,
      evented: false,
      hasControls: false,
      hasBorders: false,
      lockMovementX: true,
      lockMovementY: true,
      lockScalingX: true,
      lockScalingY: true,
      lockRotation: true,
      hoverCursor: 'default',
      editRole: 'baseImage',
      editKind: 'baseImage',
      sourceTool: 'baseImage',
      erasable: false,
      objectCaching: false
    });
    image.scaleX = baseWidth / Math.max(1, image.width || baseWidth);
    image.scaleY = baseHeight / Math.max(1, image.height || baseHeight);
    canvas.add(image);
    canvas.sendToBack(image);
    const hasMaskObjectInJson = Array.isArray(overlayJson?.objects)
      && overlayJson.objects.some(object => object?.editRole === 'mask');
    if (legacyMaskDataUrl && !hasMaskObjectInJson) {
      const legacyMask = await loadFabricImage(legacyMaskDataUrl);
      if (legacyMask) {
        legacyMask.set({
          left: 0,
          top: 0,
          originX: 'left',
          originY: 'top',
          selectable: false,
          evented: false,
          hasControls: false,
          hasBorders: false,
          lockMovementX: true,
          lockMovementY: true,
          lockScalingX: true,
          lockScalingY: true,
          lockRotation: true,
          hoverCursor: 'default',
          editRole: 'mask',
          editKind: 'legacyMask',
          sourceTool: 'mask',
          erasable: true,
          objectCaching: false
        });
        legacyMask.scaleX = baseWidth / Math.max(1, legacyMask.width || baseWidth);
        legacyMask.scaleY = baseHeight / Math.max(1, legacyMask.height || baseHeight);
        canvas.add(legacyMask);
      }
    }
    canvas.requestRenderAll();
    canvas.calcOffset?.();
    return image;
  }

    async function restoreImageEditSnapshot(snapshot) {
    const state = getImageEditState();
    if (!state || !snapshot) return;
    state.restoring = true;
    try {
      await loadImageEditSource(state.sourceDataUrl, state.sourceWidth, state.sourceHeight, snapshot.canvasJson, snapshot.legacyMaskDataUrl || '');
      state.legacyMaskDataUrl = snapshot.legacyMaskDataUrl || state.legacyMaskDataUrl || '';
      state.tool = snapshot.tool || state.tool || 'select';
      state.color = normalizeImageEditColor(snapshot.color || state.color);
      state.shapeMode = getImageEditShapeMode(snapshot);
      state.brushSize = Math.max(2, Math.min(120, Number(snapshot.brushSize || state.brushSize) || 22));
      setImageEditTool(state.tool);
      setImageEditBrushSize(state.brushSize);
      state.historyKey = imageEditSnapshotKey(snapshot);
      updateImageEditToolUi();
      updateImageEditUndoRedoButtons();
    } finally {
      state.restoring = false;
    }
  }

    function ensureImageEditFabricCanvas() {
    if (imageEditorCanvasRef.current) return imageEditorCanvasRef.current;
    const canvasEl = getImageEditorCanvasElement();
    if (!canvasEl || !window.fabric) throw new Error('Fabric.js 未加载');
    imageEditorCanvasRef.current = new fabric.Canvas(canvasEl, {
      preserveObjectStacking: true,
      selection: true,
      backgroundColor: 'transparent',
      enableRetinaScaling: false,
      renderOnAddRemove: true
    });
    imageEditorCanvasRef.current.on('mouse:down', event => {
      const state = getImageEditState();
      if (!state) return;
      const tool = state.tool || 'select';
      const pointer = imageEditorCanvasRef.current.getPointer(event.e);
      state.lastPointer = pointer;
      state.panning = false;
      state.panStart = null;
      state.panScrollStart = null;
      state.panOffsetStart = null;
      const isPrimaryButton = !event?.e || event.e.button === 0;
      if (tool === 'eraser') {
        return;
      }
      if (tool === 'select' && isPrimaryButton) {
        const target = imageEditorCanvasRef.current.findTarget?.(event.e, false);
        if (!target || target.editRole === 'baseImage') {
          state.panning = true;
          state.panStart = { x: event.e?.clientX || 0, y: event.e?.clientY || 0 };
          state.panOffsetStart = { x: state.canvasPanX || 0, y: state.canvasPanY || 0 };
          imageEditorCanvasRef.current.discardActiveObject();
          imageEditorCanvasRef.current.requestRenderAll();
          event.e?.preventDefault?.();
          event.e?.stopPropagation?.();
          return;
        }
      }
      if (tool === 'text') {
        const object = new fabric.IText('双击输入', {
          id: createImageEditId('text'),
          left: pointer.x,
          top: pointer.y,
          originX: 'left',
          originY: 'top',
          ...createImageEditTextStyle(state.color),
          editRole: 'annotation',
          editKind: 'text',
          sourceTool: 'text',
          erasable: true
        });
        applyImageEditObjectControls(object, state.color);
        imageEditorCanvasRef.current.add(object);
        imageEditorCanvasRef.current.setActiveObject(object);
        imageEditorCanvasRef.current.requestRenderAll();
        setImageEditTool('select');
        recordImageEditSnapshot('已添加文字');
        setImageEditStatus('已添加文字，拖动控制点可调整大小，双击可编辑', 'info');
        return;
      }
      if (tool === 'pin') {
        const object = createImageEditPin(pointer, state.color, getImageEditPinNumber());
        imageEditorCanvasRef.current.add(object);
        imageEditorCanvasRef.current.setActiveObject(object);
        imageEditorCanvasRef.current.requestRenderAll();
        recordImageEditSnapshot('已添加 pin');
        setImageEditStatus('已添加 pin，可继续点击放置下一个', 'info');
        return;
      }
      if (tool === 'select') return;
      state.drafting = true;
      state.draftTool = tool;
      state.draftStart = pointer;
      if (tool === 'shape') {
        state.draftObject = createImageEditShape(pointer, state.color, state.brushSize, getImageEditShapeMode(state));
      } else if (tool === 'arrow') {
        state.draftObject = createImageEditArrow(pointer, pointer, state.color, state.brushSize);
      } else {
        state.draftObject = null;
      }
      if (state.draftObject) {
        imageEditorCanvasRef.current.add(state.draftObject);
        imageEditorCanvasRef.current.setActiveObject(state.draftObject);
      }
      imageEditorCanvasRef.current.requestRenderAll();
    });
    imageEditorCanvasRef.current.on('mouse:move', event => {
      const state = getImageEditState();
      if (!state) return;
      if (state.panning && state.panStart && state.panOffsetStart) {
        const dx = (event.e?.clientX || 0) - state.panStart.x;
        const dy = (event.e?.clientY || 0) - state.panStart.y;
        applyImageEditCanvasPanOffset(state.panOffsetStart.x + dx, state.panOffsetStart.y + dy);
        event.e?.preventDefault?.();
        event.e?.stopPropagation?.();
        return;
      }
      if (!state.drafting || !state.draftObject || !state.draftStart) return;
      const pointer = imageEditorCanvasRef.current.getPointer(event.e);
      if (!pointer) return;
      state.lastPointer = pointer;
      const start = state.draftStart;
      const left = Math.min(pointer.x, start.x);
      const top = Math.min(pointer.y, start.y);
      const width = Math.abs(pointer.x - start.x);
      const height = Math.abs(pointer.y - start.y);
      if (state.draftTool === 'shape' && !isImageEditShapeEllipse(getImageEditShapeMode(state))) {
        state.draftObject.set({ left, top, width, height });
      } else if (state.draftTool === 'shape') {
        state.draftObject.set({ left, top, rx: Math.max(1, width / 2), ry: Math.max(1, height / 2) });
      } else if (state.draftTool === 'arrow') {
        updateImageEditArrow(state.draftObject, start, pointer, state.color, state.brushSize);
      }
      state.draftObject.setCoords?.();
      imageEditorCanvasRef.current.requestRenderAll();
    });
    imageEditorCanvasRef.current.on('mouse:up', event => {
      const state = getImageEditState();
      if (!state) return;
      if (state.panning) {
        state.panning = false;
        state.panStart = null;
        state.panScrollStart = null;
        state.panOffsetStart = null;
        return;
      }
      if (state.drafting && state.draftObject) {
        const object = state.draftObject;
        const start = state.draftStart;
        const end = event?.e ? imageEditorCanvasRef.current.getPointer(event.e) : (state.lastPointer || start);
        const minShapeSize = imageEditScreenToCanvasSize(3);
        if (state.draftTool === 'shape' && object.editKind === 'rect' && (Number(object.width) < minShapeSize || Number(object.height) < minShapeSize)) {
          imageEditorCanvasRef.current.remove(object);
        } else if (state.draftTool === 'shape' && object.editKind === 'ellipse' && (Number(object.rx) < minShapeSize / 2 || Number(object.ry) < minShapeSize / 2)) {
          imageEditorCanvasRef.current.remove(object);
        } else if (state.draftTool === 'arrow' && Math.hypot((end?.x || start.x) - start.x, (end?.y || start.y) - start.y) < imageEditScreenToCanvasSize(3)) {
          imageEditorCanvasRef.current.remove(object);
        } else if (state.draftTool === 'arrow') {
          updateImageEditArrow(object, start, end || start, state.color, state.brushSize);
        }
        imageEditorCanvasRef.current.requestRenderAll();
        recordImageEditSnapshot('已更新');
      }
      state.draftObject = null;
      state.draftStart = null;
      state.draftTool = '';
      state.drafting = false;
    });
    imageEditorCanvasRef.current.on('path:created', event => {
      const state = getImageEditState();
      const path = event?.path;
      if (!state || !path) return;
      if (state.tool === 'eraser') {
        window.setTimeout(() => {
          const activeState = getImageEditState();
          if (!activeState || activeState !== state || activeState.restoring) return;
          recordImageEditSnapshot('已擦除标注');
        }, 48);
        return;
      }
      const isMask = state.tool === 'maskBrush';
      setImageEditObjectMeta(path, isMask ? 'mask' : 'annotation', isMask ? 'maskStroke' : 'brush', state.tool);
      path.set({
        fill: null,
        stroke: isMask ? 'rgba(255, 106, 34, 0.9)' : normalizeImageEditColor(state.color),
        strokeWidth: state.brushSize,
        strokeLineCap: 'round',
        strokeLineJoin: 'round',
        opacity: 1
      });
      applyImageEditObjectControls(path, isMask ? '#ffffff' : state.color);
      path.setCoords?.();
      imageEditorCanvasRef.current.requestRenderAll();
      recordImageEditSnapshot(isMask ? '已添加蒙版' : '已添加涂抹');
    });
    imageEditorCanvasRef.current.on('object:modified', event => {
      const state = getImageEditState();
      const target = event?.target;
      if (!state || state.restoring || !target || target.editRole === 'baseImage') return;
      recordImageEditSnapshot('已修改对象');
    });
    imageEditorCanvasRef.current.on('object:removed', event => {
      const state = getImageEditState();
      const target = event?.target;
      if (!state || state.restoring || !target || target.editRole === 'baseImage') return;
      recordImageEditSnapshot('已删除对象');
    });
    imageEditorCanvasRef.current.on('selection:created', handleImageEditSelectionChange);
    imageEditorCanvasRef.current.on('selection:updated', handleImageEditSelectionChange);
    imageEditorCanvasRef.current.on('selection:cleared', updateImageEditUndoRedoButtons);
    imageEditorCanvasRef.current.on('text:editing:exited', () => recordImageEditSnapshot('文字已更新'));
    if (!imageEditorCanvasRef.current.__imageEditPanBound) {
      imageEditorCanvasRef.current.__imageEditPanBound = true;
      const clearPanState = () => {
        const state = getImageEditState();
        if (!state) return;
        state.panning = false;
        state.panStart = null;
        state.panScrollStart = null;
        state.panOffsetStart = null;
      };
      window.addEventListener('pointerup', clearPanState, { passive: true });
      window.addEventListener('pointercancel', clearPanState, { passive: true });
    }
    if (!imageEditorCanvasRef.current.__imageEditResizeBound) {
      imageEditorCanvasRef.current.__imageEditResizeBound = true;
      window.addEventListener('resize', () => {
        const state = getImageEditState();
        if (!state || !imageEditorElRef.current?.classList.contains('is-open')) return;
        applyImageEditCanvasDisplaySize(imageEditorCanvasRef.current, state.sourceWidth, state.sourceHeight);
      }, { passive: true });
    }
    return imageEditorCanvasRef.current;
  }

    async function exportImageEditAnnotatedDataUrl() {
    const canvas = getImageEditorCanvas();
    if (!canvas) return '';
    const hidden = [];
    const previousViewport = canvas.viewportTransform?.slice?.() || [1, 0, 0, 1, 0, 0];
    canvas.getObjects().forEach(object => {
      if (object.editRole === 'mask') {
        hidden.push([object, object.visible]);
        object.visible = false;
      }
    });
    canvas.discardActiveObject();
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    canvas.renderAll();
    const dataUrl = canvas.toDataURL({ format: 'png', multiplier: 1, enableRetinaScaling: false });
    hidden.forEach(([object, visible]) => {
      object.visible = visible;
    });
    canvas.setViewportTransform(previousViewport);
    canvas.requestRenderAll();
    return dataUrl;
  }

    async function exportImageEditAnnotatedToNode() {
    const state = getImageEditState();
    if (!state?.nodeId) throw new Error('没有可导出的编辑项目');
    const dataUrl = await exportImageEditAnnotatedDataUrl();
    if (!dataUrl) throw new Error('没有可导出的合成图');
    await saveImageEditState(state);
    const meta = await readImageMeta(dataUrl);
    const sourceNode = DesktopState.state.canvas.nodes[state.nodeId] || {};
    const sourceBounds = getNodeBoundsById(state.nodeId);
    const center = sourceBounds
      ? { x: sourceBounds.x + sourceBounds.width + 260, y: sourceBounds.y + sourceBounds.height / 2 }
      : getViewportCenterWorldPoint(320, 0);
    const baseName = sanitizeImageEditFilename(state.sourceName || sourceNode.imageName || state.nodeId || 'annotated');
    const nodeId = insertImageNode({
      imageData: dataUrl,
      imageName: `${baseName}-annotated.png`,
      mimeType: 'image/png',
      taskId: sourceNode.sourceTaskId || '',
      assetId: sourceNode.sourceAssetId || '',
      prompt: String(getImageEditorPromptInput()?.value || '').trim(),
      title: `${sourceNode.imageName || state.sourceName || state.nodeId} 标注图`,
      file: `${baseName}-annotated.png`,
      provider: sourceNode.sourceProvider || '',
      source: 'image-editor-export',
      meta
    }, center, {
      popOrigin: sourceBounds
        ? { x: sourceBounds.x + sourceBounds.width / 2, y: sourceBounds.y + sourceBounds.height / 2 }
        : null
    });
    closeImageEditor();
    DesktopResults.showTransientMessage('合成图已导出到桌面图片节点。');
    return nodeId;
  }

    async function exportImageEditMaskDataUrl(state = getImageEditState()) {
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return '';
    const maskObjects = getImageEditObjects('mask');
    if (!maskObjects.length) return state.legacyMaskDataUrl || '';
    const maskCanvasEl = document.createElement('canvas');
    maskCanvasEl.width = canvas.getWidth();
    maskCanvasEl.height = canvas.getHeight();
    const maskCanvas = new fabric.StaticCanvas(maskCanvasEl, {
      width: canvas.getWidth(),
      height: canvas.getHeight(),
      backgroundColor: '#000000',
      enableRetinaScaling: false,
      renderOnAddRemove: false
    });
    const serializedMasks = maskObjects
      .map(object => serializeImageEditObject(object))
      .filter(Boolean);
    const clones = await new Promise(resolve => {
      fabric.util.enlivenObjects(serializedMasks, items => resolve(items || []));
    });
    clones.forEach(object => {
      object.set({
        selectable: false,
        evented: false,
        objectCaching: false,
        fill: object.type === 'path' ? null : '#ffffff',
        stroke: '#ffffff',
        opacity: 1
      });
      maskCanvas.add(object);
    });
    maskCanvas.renderAll();
    return maskCanvasEl.toDataURL('image/png');
  }

    function clearImageEditorMask() {
    const state = getImageEditState();
    if (!state) return;
    const removed = removeImageEditObjects(getImageEditObjects('mask'));
    state.legacyMaskDataUrl = '';
    state.projectJson = buildImageEditProjectJson();
    if (removed) recordImageEditSnapshot('蒙版已清空');
  }

    function clearImageEditorAnnotations() {
    const state = getImageEditState();
    if (!state) return;
    const removed = removeImageEditObjects(getImageEditObjects('annotation'));
    state.projectJson = buildImageEditProjectJson();
    if (removed) recordImageEditSnapshot('标注已清空');
  }

    function closeImageEditor() {
    const currentState = activeImageEditRef.current;
    if (currentState) {
      saveImageEditState(currentState).catch(() => {});
    }
    activeImageEditRef.current = null;
    imageEditorElRef.current?.classList.remove('is-open');
    imageEditorElRef.current?.setAttribute('aria-hidden', 'true');
  }

    async function saveImageEditState(editState = activeImageEditRef.current) {
    if (!editState?.nodeId) return null;
    const node = DesktopState.state.canvas.nodes[editState.nodeId];
    if (!node) return null;
    const prompt = String(getImageEditorPromptInput()?.value || '').trim();
    const maskData = await exportImageEditMaskDataUrl(editState);
    const projectJson = buildImageEditProjectJson(editState);
    node.editState = {
      ...(node.editState || {}),
      editPrompt: prompt,
      hasMask: !!projectJson?.hasMask || !!maskData,
      maskData,
      maskOverlayData: maskData,
      projectJson
    };
    DesktopState.saveSettings();
    refreshImageNode(editState.nodeId);
    return node.editState;
  }

    function buildImageEditPrompt(note, hasMask) {
    const clean = String(note || '').trim();
    if (!clean) return '';
    return hasMask
      ? `只编辑蒙版透明区域对应的局部对象，未被蒙版覆盖的角色、姿态、光照、背景和构图必须保持不变。\n\n编辑要求：${clean}`
      : clean;
  }

    async function openImageEditor(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'image') return;
    const modal = ensureImageEditor();
    const promptInput = getImageEditorPromptInput();
    const title = modal.querySelector('[data-image-edit-title]');
    const source = node.imageData || node.imageUrl || '';
    if (!source) throw new Error('图片节点没有可编辑的图片');
    const meta = await readImageMeta(source);
    const projectJson = cloneImageEditValue(node.editState?.projectJson || null);
    activeImageEditRef.current = {
      nodeId,
      sourceDataUrl: source,
      sourceName: node.imageName || node.sourceTitle || node.id,
      sourceMimeType: node.mimeType || 'image/png',
      sourceWidth: meta.width || 1,
      sourceHeight: meta.height || 1,
      tool: projectJson?.tool || 'select',
      brushSize: Math.max(2, Math.min(120, Number(projectJson?.brushSize || 22) || 22)),
      color: normalizeImageEditColor(projectJson?.color || '#0b57d0'),
      shapeMode: getImageEditShapeMode(projectJson || {}),
      pinCounter: Number(projectJson?.pinCounter || 0) || 1,
      displayZoom: 0,
      fitScale: 1,
      zoomMode: 'fit',
      legacyMaskDataUrl: node.editState?.maskData || node.editState?.maskOverlayData || '',
      projectJson: null,
      undoStack: [],
      redoStack: [],
      historyKey: '',
      historyLimit: 60,
      restoring: false,
      panning: false,
      panStart: null,
      panScrollStart: null,
      panOffsetStart: null,
      canvasPanX: 0,
      canvasPanY: 0,
      drafting: false,
      draftStart: null,
      draftObject: null,
      draftTool: '',
      lastPointer: null
    };
    if (title) title.textContent = '图片编辑';
    if (promptInput) promptInput.value = node.editState?.editPrompt || '';
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    ensureImageEditorThemeObserver();
    setImageEditStatus('载入图片中', 'info');
    await loadImageEditSource(source, activeImageEditRef.current.sourceWidth, activeImageEditRef.current.sourceHeight, null, activeImageEditRef.current.legacyMaskDataUrl || '');
    const canvas = ensureImageEditFabricCanvas();
    if (projectJson?.canvasJson?.objects?.length) {
      activeImageEditRef.current.restoring = true;
      try {
        await restoreImageEditSnapshot({
          canvasJson: projectJson.canvasJson,
          tool: projectJson.tool || activeImageEditRef.current.tool,
          color: projectJson.color || activeImageEditRef.current.color,
          shapeMode: projectJson.shapeMode || activeImageEditRef.current.shapeMode,
          brushSize: projectJson.brushSize || activeImageEditRef.current.brushSize,
          legacyMaskDataUrl: node.editState?.maskData || node.editState?.maskOverlayData || ''
        });
      } finally {
        activeImageEditRef.current.restoring = false;
      }
    }
    activeImageEditRef.current.projectJson = buildImageEditProjectJson();
    resetImageEditHistory(createImageEditSnapshot());
    setImageEditBrushSize(activeImageEditRef.current.brushSize);
    setImageEditTool(activeImageEditRef.current.tool || 'select');
    window.requestAnimationFrame(() => {
      applyImageEditCanvasDisplaySize(canvas, activeImageEditRef.current.sourceWidth, activeImageEditRef.current.sourceHeight);
      canvas.calcOffset?.();
      canvas.requestRenderAll();
      updateImageEditToolUi();
      clearImageEditorStatusToDefault();
    });
  }

    function clearImageEditorStatusToDefault() {
    setImageEditStatus('就绪', 'info');
  }

    async function restoreImageEditSnapshotFromState(state, snapshot) {
    if (!state || !snapshot) return;
    await restoreImageEditSnapshot(snapshot);
    state.legacyMaskDataUrl = snapshot.legacyMaskDataUrl || state.legacyMaskDataUrl || '';
  }

    function bindImageEditorEvents(modal) {
    modal.querySelector('[data-image-edit-close]')?.addEventListener('click', closeImageEditor);
    modal.addEventListener('pointerdown', event => {
      if (event.target === modal) closeImageEditor();
    });
    modal.querySelectorAll('[data-image-edit-tool]').forEach(button => {
      button.addEventListener('click', () => setImageEditTool(button.dataset.imageEditTool || 'select'));
    });
    modal.querySelectorAll('[data-image-edit-color]').forEach(button => {
      button.addEventListener('click', () => setImageEditColor(button.dataset.imageEditColor || '#0b57d0'));
    });
    modal.querySelectorAll('[data-image-edit-shape]').forEach(button => {
      button.addEventListener('click', () => setImageEditShapeMode(button.dataset.imageEditShape || 'rectOutline'));
    });
    modal.querySelector('[data-image-edit-size]')?.addEventListener('input', event => {
      setImageEditBrushSize(event.target.value);
    });
    modal.querySelector('[data-image-edit-zoom-out]')?.addEventListener('click', () => {
      const state = getImageEditState();
      if (!state) return;
      setImageEditZoom((state.displayZoom || state.fitScale || 1) / IMAGE_EDIT_ZOOM_STEP, 'manual');
    });
    modal.querySelector('[data-image-edit-zoom-in]')?.addEventListener('click', () => {
      const state = getImageEditState();
      if (!state) return;
      setImageEditZoom((state.displayZoom || state.fitScale || 1) * IMAGE_EDIT_ZOOM_STEP, 'manual');
    });
    modal.querySelector('[data-image-edit-zoom-fit]')?.addEventListener('click', () => {
      setImageEditZoom(0, 'fit');
    });
    modal.querySelector('[data-image-edit-clear-mask]')?.addEventListener('click', clearImageEditorMask);
    modal.querySelector('[data-image-edit-clear-annotations]')?.addEventListener('click', clearImageEditorAnnotations);
    modal.querySelector('[data-image-edit-undo]')?.addEventListener('click', async () => {
      const state = getImageEditState();
      if (!state || state.undoStack.length <= 1) return;
      const current = state.undoStack.pop();
      if (current) state.redoStack.push(current);
      const previous = state.undoStack[state.undoStack.length - 1];
      if (!previous) return;
      state.restoring = true;
      try {
        await restoreImageEditSnapshot(previous);
        state.historyKey = imageEditSnapshotKey(previous);
        updateImageEditUndoRedoButtons();
        setImageEditStatus('已撤销', 'info');
      } finally {
        state.restoring = false;
      }
    });
    modal.querySelector('[data-image-edit-redo]')?.addEventListener('click', async () => {
      const state = getImageEditState();
      if (!state || !state.redoStack.length) return;
      const next = state.redoStack.pop();
      if (!next) return;
      state.undoStack.push(next);
      state.restoring = true;
      try {
        await restoreImageEditSnapshot(next);
        state.historyKey = imageEditSnapshotKey(next);
        updateImageEditUndoRedoButtons();
        setImageEditStatus('已重做', 'info');
      } finally {
        state.restoring = false;
      }
    });
    modal.querySelector('[data-image-edit-export-annotated]')?.addEventListener('click', () => {
      exportImageEditAnnotatedDataUrl()
        .then(dataUrl => {
          if (!dataUrl) throw new Error('没有可导出的合成图');
          const state = getImageEditState();
          downloadDataUrl(dataUrl, `${sanitizeImageEditFilename(state?.sourceName || 'annotated')}-annotated.png`);
          setImageEditStatus('合成图已导出', 'success');
        })
        .catch(error => DesktopResults.showError(error));
    });
    modal.querySelector('[data-image-edit-export-mask]')?.addEventListener('click', () => {
      exportImageEditMaskDataUrl()
        .then(dataUrl => {
          if (!dataUrl) throw new Error('没有可导出的 mask');
          const state = getImageEditState();
          downloadDataUrl(dataUrl, `${sanitizeImageEditFilename(state?.sourceName || 'mask')}-mask.png`);
          setImageEditStatus('mask 已导出', 'success');
        })
        .catch(error => DesktopResults.showError(error));
    });
    modal.querySelector('[data-image-edit-export-node]')?.addEventListener('click', () => {
      exportImageEditAnnotatedToNode()
        .catch(error => DesktopResults.showError(error));
    });
    modal.querySelector('[data-image-edit-export-json]')?.addEventListener('click', () => {
      const projectJson = buildImageEditProjectJson();
      if (!projectJson) return;
      const state = getImageEditState();
      downloadJsonObject(projectJson, `${sanitizeImageEditFilename(state?.sourceName || 'project')}-project.json`);
      setImageEditStatus('项目 JSON 已导出', 'success');
    });
    modal.querySelector('[data-image-edit-import]')?.addEventListener('click', () => {
      modal.querySelector('[data-image-edit-import-input]')?.click();
    });
    modal.querySelector('[data-image-edit-import-input]')?.addEventListener('change', event => {
      const file = Array.from(event.target.files || []).find(item => item.type.startsWith('image/'));
      event.target.value = '';
      if (!file) return;
      const state = getImageEditState();
      if (!state) return;
      fileToDataUrl(file)
        .then(async dataUrl => {
          const meta = await readImageMeta(dataUrl);
          state.sourceDataUrl = dataUrl;
          state.sourceName = file.name || state.sourceName;
          state.sourceMimeType = file.type || 'image/png';
          state.sourceWidth = meta.width || 1;
          state.sourceHeight = meta.height || 1;
          state.displayZoom = 0;
          state.fitScale = 1;
          state.zoomMode = 'fit';
          await loadImageEditSource(dataUrl, state.sourceWidth, state.sourceHeight, null);
          state.tool = 'select';
          state.projectJson = buildImageEditProjectJson();
          resetImageEditHistory(createImageEditSnapshot());
          updateImageEditToolUi();
          setImageEditTool('select');
          setImageEditStatus('已导入新背景图', 'success');
        })
        .catch(error => DesktopResults.showError(error));
    });
  }

    return Object.freeze({
      ensureImageEditor,
      getImageEditorCanvasElement,
      getImageEditorCanvas,
      getImageEditorCanvasShell,
      getImageEditorCanvasWrap,
      applyImageEditCanvasPanOffset,
      clampImageEditZoom,
      getImageEditDisplaySize,
      getImageEditCanvasCssScale,
      getImageEditViewportCenter,
      clampImageEditViewportTransform,
      applyImageEditViewportZoom,
      refreshImageEditObjectControls,
      updateImageEditZoomUi,
      applyImageEditCanvasDisplaySize,
      setImageEditZoom,
      getImageEditCanvasDisplayScale,
      imageEditScreenToCanvasSize,
      getImageEditorPromptInput,
      getImageEditorStatusEl,
      getImageEditorSourceEl,
      getImageEditCustomProps,
      cloneImageEditValue,
      createImageEditId,
      sanitizeImageEditFilename,
      getImageEditState,
      setImageEditStatus,
      updateImageEditSourceLabel,
      updateImageEditUndoRedoButtons,
      isImageEditDarkTheme,
      syncImageEditToolIconFilters,
      ensureImageEditorThemeObserver,
      updateImageEditToolUi,
      serializeImageEditObject,
      serializeImageEditCanvas,
      buildImageEditProjectJson,
      createImageEditSnapshot,
      imageEditSnapshotKey,
      resetImageEditHistory,
      recordImageEditSnapshot,
      loadFabricImage,
      loadImageEditSource,
      restoreImageEditSnapshot,
      ensureImageEditFabricCanvas,
      exportImageEditAnnotatedDataUrl,
      exportImageEditAnnotatedToNode,
      exportImageEditMaskDataUrl,
      clearImageEditorMask,
      clearImageEditorAnnotations,
      closeImageEditor,
      saveImageEditState,
      buildImageEditPrompt,
      openImageEditor,
      clearImageEditorStatusToDefault,
      restoreImageEditSnapshotFromState,
      bindImageEditorEvents,
    });
  }

  window.DesktopCanvasImageEditor = Object.freeze({ create });
})();
