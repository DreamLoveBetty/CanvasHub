// 图片编辑器的 Fabric 对象绘制、形状/箭头/标记、颜色与选中对象操作、工具模式和游标；不持有会话或 Fabric canvas。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    IMAGE_EDIT_ASSET_VERSION,
    IMAGE_EDIT_CURSOR_HOTSPOTS,
    createImageEditId,
    getImageEditState,
    getImageEditorCanvas,
    imageEditScreenToCanvasSize,
    imageEditorElRef,
    recordImageEditSnapshot,
    serializeImageEditObject,
    setImageEditStatus,
    updateImageEditToolUi,
    updateImageEditUndoRedoButtons,
  }) {


    function getImageEditToolIcon(tool) {
    const assetVersion = IMAGE_EDIT_ASSET_VERSION;
    const sources = {
      select: `assets/image-editor-icons/select.svg?v=${assetVersion}`,
      brush: `assets/image-editor-icons/brush.svg?v=${assetVersion}`,
      maskBrush: `assets/image-editor-icons/mask.svg?v=${assetVersion}`,
      shape: `assets/image-editor-icons/shape.svg?v=${assetVersion}`,
      arrow: `assets/image-editor-icons/arrow.svg?v=${assetVersion}`,
      text: `assets/image-editor-icons/text.svg?v=${assetVersion}`,
      pin: `assets/image-editor-icons/pin.svg?v=${assetVersion}`,
      eraser: `assets/image-editor-icons/eraser.svg?v=${assetVersion}`
    };
    return sources[tool] || sources.select;
  }

    function getImageEditCursorUrl(imageUrl, hotspotX = 0, hotspotY = 0, fallback = 'crosshair') {
    return `url("${imageUrl}") ${hotspotX} ${hotspotY}, ${fallback}`;
  }

    function getImageEditCursorAsset(tool) {
    const cursorVersion = IMAGE_EDIT_ASSET_VERSION;
    const sources = {
      brush: `/assets/image-editor-cursors/brush.svg?v=${cursorVersion}`,
      maskBrush: `/assets/image-editor-cursors/maskBrush.svg?v=${cursorVersion}`,
      shape: `/assets/image-editor-cursors/shape.svg?v=${cursorVersion}`,
      arrow: `/assets/image-editor-cursors/arrow.svg?v=${cursorVersion}`,
      pin: `/assets/image-editor-cursors/pin.svg?v=${cursorVersion}`,
      eraser: `/assets/image-editor-cursors/eraser.svg?v=${cursorVersion}`
    };
    return sources[tool] || '';
  }

    function getImageEditShapeIcon(shape) {
    switch (shape) {
      case 'rectFilled':
        return `<rect x="5.5" y="5.5" width="13" height="13" rx="2" fill="currentColor" stroke="none"></rect>`;
      case 'ellipseOutline':
        return `<circle cx="12" cy="12" r="6.8" fill="none"></circle>`;
      case 'ellipseFilled':
        return `<circle cx="12" cy="12" r="6.8" fill="currentColor" stroke="none"></circle>`;
      case 'rectOutline':
      default:
        return `<rect x="5.5" y="5.5" width="13" height="13" rx="2" fill="none"></rect>`;
    }
  }

    function applyImageEditObjectControls(object, color = '') {
    if (!object) return object;
    const normalizedColor = normalizeImageEditColor(color || object.stroke || object.fill || '#0b57d0');
    object.set({
      borderColor: normalizedColor,
      cornerColor: '#ffffff',
      cornerStrokeColor: normalizedColor,
      transparentCorners: false,
      cornerSize: imageEditScreenToCanvasSize(8),
      touchCornerSize: imageEditScreenToCanvasSize(26),
      borderScaleFactor: Math.max(1, imageEditScreenToCanvasSize(1))
    });
    return object;
  }

    function getImageEditHexColor(color) {
    const value = String(color || '').trim();
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value) ? value : '';
  }

    function firstImageEditHexColor(...colors) {
    for (const color of colors) {
      const normalizedColor = getImageEditHexColor(color);
      if (normalizedColor) return normalizedColor;
    }
    return '';
  }

    function getImageEditObjectColor(object) {
    if (!object) return '';
    if (object.type === 'activeSelection' && typeof object.getObjects === 'function') {
      const target = object.getObjects().find(item => item?.editRole && item.editRole !== 'baseImage');
      return getImageEditObjectColor(target);
    }
    if (object.editKind === 'pin' && typeof object.getObjects === 'function') {
      const childColors = object.getObjects()
        .flatMap(child => [child?.stroke, child?.fill])
        .filter(Boolean);
      return firstImageEditHexColor(object.annotationColor, ...childColors);
    }
    if (object.editRole === 'mask') {
      return firstImageEditHexColor(object.maskColor, object.stroke, object.fill);
    }
    return firstImageEditHexColor(object.annotationColor, object.stroke, object.fill);
  }

    function getImageEditSelectedObjects(canvas = getImageEditorCanvas()) {
    const activeObject = canvas?.getActiveObject?.();
    if (!activeObject) return [];
    const objects = typeof canvas.getActiveObjects === 'function'
      ? canvas.getActiveObjects()
      : (activeObject.type === 'activeSelection' && typeof activeObject.getObjects === 'function' ? activeObject.getObjects() : [activeObject]);
    const seen = new Set();
    return objects.filter(object => {
      if (!object || object.editRole === 'baseImage' || object.type === 'activeSelection' || seen.has(object)) return false;
      seen.add(object);
      return true;
    });
  }

    function setImageEditPinColor(pin, color) {
    if (!pin || typeof pin.getObjects !== 'function') return;
    pin.getObjects().forEach(child => {
      if (!child) return;
      if (child.type === 'path' || child.path) {
        child.set({ stroke: color, fill: null });
      } else if (child.type === 'text' || typeof child.text === 'string') {
        child.set({ fill: color, stroke: null });
      } else {
        if (child.stroke !== undefined) child.set({ stroke: color });
        if (getImageEditHexColor(child.fill)) child.set({ fill: color });
      }
      child.dirty = true;
    });
    pin.set({ annotationColor: color });
  }

    function imageEditObjectColorSignature(object) {
    return object?.toObject ? JSON.stringify(serializeImageEditObject(object)) : '';
  }

    function setImageEditObjectColor(object, color) {
    if (!object || object.editRole === 'baseImage') return false;
    const normalizedColor = normalizeImageEditColor(color);
    const before = imageEditObjectColorSignature(object);
    if (object.editKind === 'pin') {
      setImageEditPinColor(object, normalizedColor);
    } else if (object.editKind === 'text' || typeof object.text === 'string') {
      object.set({ fill: normalizedColor, annotationColor: normalizedColor });
    } else if (object.editKind === 'rect' || object.editKind === 'ellipse') {
      const nextProps = {
        stroke: normalizedColor,
        annotationColor: normalizedColor
      };
      if (isImageEditShapeFilled(object.shapeMode)) nextProps.fill = normalizedColor;
      object.set(nextProps);
    } else if (object.editRole === 'mask') {
      object.set({
        stroke: normalizedColor,
        fill: object.type === 'path' ? null : normalizedColor,
        maskColor: normalizedColor
      });
    } else {
      const nextProps = { annotationColor: normalizedColor };
      if (object.stroke !== undefined) nextProps.stroke = normalizedColor;
      if (object.editKind !== 'arrow' && object.editKind !== 'brush' && getImageEditHexColor(object.fill)) {
        nextProps.fill = normalizedColor;
      }
      object.set(nextProps);
    }
    applyImageEditObjectControls(object, normalizedColor);
    object.dirty = true;
    object.setCoords?.();
    return before !== imageEditObjectColorSignature(object);
  }

    function setImageEditSelectedObjectsColor(color) {
    const canvas = getImageEditorCanvas();
    const targets = getImageEditSelectedObjects(canvas);
    if (!canvas || !targets.length) return 0;
    const changedCount = targets.reduce((count, object) => (
      setImageEditObjectColor(object, color) ? count + 1 : count
    ), 0);
    if (!changedCount) return 0;
    canvas.requestRenderAll();
    recordImageEditSnapshot('颜色已更新');
    setImageEditStatus(`已更新 ${changedCount} 个对象颜色`, 'info');
    return changedCount;
  }

    function syncImageEditColorFromSelection() {
    const state = getImageEditState();
    const selectedColor = getImageEditSelectedObjects()
      .map(object => getImageEditObjectColor(object))
      .find(Boolean);
    if (!state || !selectedColor) return;
    state.color = normalizeImageEditColor(selectedColor);
    updateImageEditToolUi();
  }

    function handleImageEditSelectionChange() {
    syncImageEditColorFromSelection();
    updateImageEditUndoRedoButtons();
  }

    function normalizeImageEditColor(color) {
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(color || '').trim()) ? String(color).trim() : '#0b57d0';
  }

    function getImageEditObjects(role = '') {
    const canvas = getImageEditorCanvas();
    const objects = canvas?.getObjects?.() || [];
    return role ? objects.filter(object => object?.editRole === role) : objects;
  }

    function removeImageEditObjects(objects = []) {
    const canvas = getImageEditorCanvas();
    if (!canvas) return 0;
    const targets = (Array.isArray(objects) ? objects : [objects]).filter(object => object && object.editRole !== 'baseImage');
    if (!targets.length) return 0;
    targets.forEach(object => canvas.remove(object));
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    return targets.length;
  }

    function createImageEditTextStyle(color) {
    const normalizedColor = normalizeImageEditColor(color);
    return {
      fill: normalizedColor,
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Hiragino Sans GB", sans-serif',
      fontSize: imageEditScreenToCanvasSize(28),
      fontWeight: 700,
      lineHeight: 1.2,
      editable: true,
      hasControls: true,
      hasBorders: true,
      lockScalingX: false,
      lockScalingY: false,
      lockUniScaling: false,
      lockRotation: false,
      padding: imageEditScreenToCanvasSize(4),
      objectCaching: false
    };
  }

    function getImageEditShapeMode(state = getImageEditState()) {
    return ['rectOutline', 'rectFilled', 'ellipseOutline', 'ellipseFilled'].includes(state?.shapeMode)
      ? state.shapeMode
      : 'rectOutline';
  }

    function isImageEditShapeFilled(shapeMode) {
    return String(shapeMode || '').endsWith('Filled');
  }

    function isImageEditShapeEllipse(shapeMode) {
    return String(shapeMode || '').startsWith('ellipse');
  }

    function imageEditShapeKind(shapeMode) {
    return isImageEditShapeEllipse(shapeMode) ? 'ellipse' : 'rect';
  }

    function createImageEditShape(start, color, strokeWidth, shapeMode = 'rectOutline') {
    return isImageEditShapeEllipse(shapeMode)
      ? createImageEditEllipse(start, color, strokeWidth, shapeMode)
      : createImageEditRect(start, color, strokeWidth, shapeMode);
  }

    function createImageEditRect(start, color, strokeWidth, shapeMode = 'rectOutline') {
    const filled = isImageEditShapeFilled(shapeMode);
    const normalizedColor = normalizeImageEditColor(color);
    const canvasStrokeWidth = Math.max(1, Number(strokeWidth) || 1);
    const rect = new fabric.Rect({
      id: createImageEditId('rect'),
      left: start.x,
      top: start.y,
      width: 1,
      height: 1,
      originX: 'left',
      originY: 'top',
      fill: filled ? normalizedColor : 'rgba(255, 255, 255, 0.02)',
      stroke: normalizedColor,
      strokeWidth: filled ? Math.max(1, Math.min(4, canvasStrokeWidth / 3)) : canvasStrokeWidth,
      strokeUniform: true,
      rx: imageEditScreenToCanvasSize(4),
      ry: imageEditScreenToCanvasSize(4),
      selectable: true,
      evented: true,
      erasable: true,
      objectCaching: false,
      editRole: 'annotation',
      editKind: 'rect',
      shapeMode,
      sourceTool: 'shape'
    });
    return applyImageEditObjectControls(rect, normalizedColor);
  }

    function createImageEditEllipse(start, color, strokeWidth, shapeMode = 'ellipseOutline') {
    const filled = isImageEditShapeFilled(shapeMode);
    const normalizedColor = normalizeImageEditColor(color);
    const canvasStrokeWidth = Math.max(1, Number(strokeWidth) || 1);
    const ellipse = new fabric.Ellipse({
      id: createImageEditId('ellipse'),
      left: start.x,
      top: start.y,
      rx: 1,
      ry: 1,
      originX: 'left',
      originY: 'top',
      fill: filled ? normalizedColor : 'rgba(255, 255, 255, 0.02)',
      stroke: normalizedColor,
      strokeWidth: filled ? Math.max(1, Math.min(4, canvasStrokeWidth / 3)) : canvasStrokeWidth,
      strokeUniform: true,
      selectable: true,
      evented: true,
      erasable: true,
      objectCaching: false,
      editRole: 'annotation',
      editKind: 'ellipse',
      shapeMode,
      sourceTool: 'shape'
    });
    return applyImageEditObjectControls(ellipse, normalizedColor);
  }

    function buildImageEditArrowPath(start, end, strokeWidth) {
    const safeEnd = Math.hypot(end.x - start.x, end.y - start.y) < 1
      ? { x: start.x + 1, y: start.y }
      : end;
    const angle = Math.atan2(safeEnd.y - start.y, safeEnd.x - start.x);
    const headLength = Math.max(18, strokeWidth * 2.1);
    const wingAngle = Math.PI / 7;
    const wingA = {
      x: safeEnd.x - headLength * Math.cos(angle - wingAngle),
      y: safeEnd.y - headLength * Math.sin(angle - wingAngle)
    };
    const wingB = {
      x: safeEnd.x - headLength * Math.cos(angle + wingAngle),
      y: safeEnd.y - headLength * Math.sin(angle + wingAngle)
    };
    return `M ${start.x} ${start.y} L ${safeEnd.x} ${safeEnd.y} M ${safeEnd.x} ${safeEnd.y} L ${wingA.x} ${wingA.y} M ${safeEnd.x} ${safeEnd.y} L ${wingB.x} ${wingB.y}`;
  }

    function createImageEditArrow(start, end, color, strokeWidth) {
    const normalizedColor = normalizeImageEditColor(color);
    const canvasStrokeWidth = Math.max(2, Number(strokeWidth) || 2);
    const arrow = new fabric.Path(buildImageEditArrowPath(start, end, canvasStrokeWidth), {
      id: createImageEditId('arrow'),
      fill: null,
      stroke: normalizedColor,
      strokeWidth: canvasStrokeWidth,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      selectable: true,
      evented: true,
      erasable: true,
      strokeUniform: true,
      objectCaching: false,
      editRole: 'annotation',
      editKind: 'arrow',
      sourceTool: 'arrow'
    });
    applyImageEditObjectControls(arrow, normalizedColor);
    arrow.setCoords?.();
    return arrow;
  }

    function updateImageEditArrow(arrow, start, end, color, strokeWidth) {
    if (!arrow) return;
    const canvasStrokeWidth = Math.max(2, Number(strokeWidth) || 2);
    const path = new fabric.Path(buildImageEditArrowPath(start, end, canvasStrokeWidth));
    arrow.set({
      path: path.path,
      left: path.left,
      top: path.top,
      width: path.width,
      height: path.height,
      pathOffset: path.pathOffset,
      stroke: normalizeImageEditColor(color),
      strokeWidth: canvasStrokeWidth
    });
    applyImageEditObjectControls(arrow, color);
    arrow.dirty = true;
    arrow.setCoords?.();
  }

    function createImageEditPin(point, color, label) {
    const fill = normalizeImageEditColor(color);
    const unit = imageEditScreenToCanvasSize(1);
    const pinScale = Math.max(0.85, Math.round((42 / 24) * unit * 8) / 8);
    const labelText = String(label || '');
    const pinPath = 'M15 4.5l-4 4l-4 1.5l-1.5 1.5l7 7l1.5 -1.5l1.5 -4l4 -4 M9 15l-4.5 4.5 M14.5 4l5.5 5.5';
    const labelX = 8;
    const labelY = 9;
    const labelFontSize = labelText.length > 1 ? Math.max(3.8, 7.8 - labelText.length * 0.88) : 8.2;
    const childBase = {
      selectable: false,
      evented: false,
      objectCaching: false,
      noScaleCache: true
    };
    const pinStroke = {
      fill: null,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      ...childBase
    };
    const pin = new fabric.Group([
      new fabric.Path(pinPath, {
        left: 0,
        top: 0,
        originX: 'left',
        originY: 'top',
        stroke: fill,
        strokeWidth: 1,
        ...pinStroke
      }),
      new fabric.Text(labelText, {
        left: labelX,
        top: labelY,
        originX: 'center',
        originY: 'center',
        fill,
        fontFamily: '"SF Pro Rounded", ui-rounded, -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", sans-serif',
        fontSize: labelFontSize,
        fontWeight: 400,
        textAlign: 'center',
        lineHeight: 1,
        charSpacing: 0,
        selectable: false,
        evented: false,
        objectCaching: false,
        noScaleCache: true,
        stroke: null
      })
    ], {
      id: createImageEditId('pin'),
      left: Math.round(point.x - 12 * pinScale),
      top: Math.round(point.y - 12 * pinScale),
      originX: 'left',
      originY: 'top',
      scaleX: pinScale,
      scaleY: pinScale,
      selectable: true,
      evented: true,
      subTargetCheck: true,
      hasControls: true,
      hasBorders: true,
      lockScalingX: false,
      lockScalingY: false,
      lockUniScaling: false,
      lockRotation: false,
      borderColor: fill,
      cornerColor: '#ffffff',
      cornerStrokeColor: fill,
      transparentCorners: false,
      erasable: true,
      objectCaching: false,
      noScaleCache: true,
      editRole: 'annotation',
      editKind: 'pin',
      pinNumber: Number(label) || 0,
      annotationColor: fill,
      label: String(label || ''),
      sourceTool: 'pin'
    });
    return applyImageEditObjectControls(pin, fill);
  }

    function setImageEditObjectMeta(object, role, kind, tool = '') {
    if (!object) return object;
    object.set({
      id: object.id || createImageEditId(kind || role || 'item'),
      editRole: role,
      editKind: kind || role,
      sourceTool: tool || kind || role,
      erasable: role !== 'baseImage',
      objectCaching: false
    });
    return object;
  }

    function getImageEditPinNumber() {
    return getImageEditObjects('annotation')
      .filter(object => object?.editKind === 'pin')
      .reduce((max, pin) => Math.max(max, Number(pin.pinNumber || pin.label || 0) || 0), 0) + 1;
  }

    function setImageEditTool(tool) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    if (tool === 'rect') {
      state.shapeMode = 'rectOutline';
      tool = 'shape';
    } else if (tool === 'ellipse') {
      state.shapeMode = 'ellipseOutline';
      tool = 'shape';
    }
    const nextTool = ['select', 'brush', 'maskBrush', 'shape', 'arrow', 'text', 'pin', 'eraser'].includes(tool) ? tool : 'select';
    state.tool = nextTool;
    canvas.isDrawingMode = nextTool === 'brush' || nextTool === 'maskBrush' || nextTool === 'eraser';
    canvas.selection = false;
    canvas.skipTargetFind = nextTool !== 'select';
    applyImageEditCursor(canvas, nextTool, state);
    if (canvas.isDrawingMode) {
      const brush = nextTool === 'eraser'
        ? (typeof fabric.EraserBrush === 'function' ? new fabric.EraserBrush(canvas) : null)
        : new fabric.PencilBrush(canvas);
      if (!brush) {
        state.tool = 'select';
        canvas.isDrawingMode = false;
        canvas.skipTargetFind = false;
        applyImageEditCursor(canvas, 'select', state);
        throw new Error('当前 Fabric 构建未包含官方橡皮擦模块');
      }
      brush.width = state.brushSize || 22;
      if (nextTool === 'eraser') {
        brush.inverted = false;
        brush.decimate = 0;
        brush.strokeLineCap = 'round';
        brush.strokeLineJoin = 'round';
      } else {
        brush.color = nextTool === 'maskBrush'
          ? 'rgba(255, 106, 34, 0.88)'
          : normalizeImageEditColor(state.color);
        brush.strokeLineCap = 'round';
        brush.strokeLineJoin = 'round';
      }
      canvas.freeDrawingBrush = brush;
    }
    if (nextTool !== 'select' && canvas.getActiveObject?.()) {
      canvas.discardActiveObject();
    }
    setImageEditStatus(
      nextTool === 'select' ? '选择与移动' :
      nextTool === 'brush' ? '画笔涂抹' :
      nextTool === 'maskBrush' ? '蒙版涂抹' :
      nextTool === 'shape' ? `拖拽绘制${getImageEditShapeLabel(state.shapeMode)}` :
      nextTool === 'arrow' ? '拖拽绘制箭头' :
      nextTool === 'text' ? '点击放置文字' :
      nextTool === 'pin' ? '点击放置 pin' : '拖拽擦除标注',
      nextTool === 'eraser' ? 'warn' : 'info'
    );
    updateImageEditToolUi();
    canvas.requestRenderAll();
  }

    function getImageEditCursor(tool, state = getImageEditState()) {
    const selectCursor = 'default';
    const brushCursor = getImageEditCursorUrl(getImageEditCursorAsset('brush'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.brush);
    const maskBrushCursor = getImageEditCursorUrl(getImageEditCursorAsset('maskBrush'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.maskBrush);
    const shapeCursor = getImageEditCursorUrl(getImageEditCursorAsset('shape'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.shape);
    const arrowCursor = getImageEditCursorUrl(getImageEditCursorAsset('arrow'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.arrow);
    const pinCursor = getImageEditCursorUrl(getImageEditCursorAsset('pin'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.pin);
    const eraserCursor = getImageEditCursorUrl(getImageEditCursorAsset('eraser'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.eraser);
    if (tool === 'select') return selectCursor;
    if (tool === 'brush') return brushCursor;
    if (tool === 'maskBrush') return maskBrushCursor;
    if (tool === 'shape') return shapeCursor;
    if (tool === 'arrow') return arrowCursor;
    if (tool === 'text') return 'text';
    if (tool === 'pin') return pinCursor;
    if (tool === 'eraser') return eraserCursor;
    return selectCursor;
  }

    function applyImageEditCursor(canvas, tool, state = getImageEditState()) {
    const cursor = getImageEditCursor(tool, state);
    if (imageEditorElRef.current) {
      imageEditorElRef.current.style.setProperty('--desk-image-edit-cursor', cursor);
    }
    canvas.defaultCursor = cursor;
    canvas.hoverCursor = cursor;
    canvas.moveCursor = cursor;
    canvas.freeDrawingCursor = cursor;
    const cursorTargets = [
      canvas.upperCanvasEl,
      canvas.lowerCanvasEl,
      canvas.wrapperEl,
      canvas.containerClass ? canvas.wrapperEl?.querySelector?.('.canvas-container') : null,
      imageEditorElRef.current?.querySelector('.desk-image-editor__canvas-shell'),
      imageEditorElRef.current?.querySelector('.desk-image-editor__canvas-wrap'),
      imageEditorElRef.current?.querySelector('.desk-image-editor__stage'),
      imageEditorElRef.current
    ].filter(Boolean);
    cursorTargets.forEach(target => {
      target.style.cursor = cursor;
    });
  }

    function getImageEditShapeLabel(shapeMode) {
    return shapeMode === 'rectFilled' ? '实心矩形'
      : shapeMode === 'ellipseOutline' ? '空心圆形'
      : shapeMode === 'ellipseFilled' ? '实心圆形'
      : '空心矩形';
  }

    function setImageEditShapeMode(shapeMode) {
    const state = getImageEditState();
    if (!state) return;
    state.shapeMode = ['rectOutline', 'rectFilled', 'ellipseOutline', 'ellipseFilled'].includes(shapeMode)
      ? shapeMode
      : 'rectOutline';
    setImageEditTool('shape');
  }

    function setImageEditColor(color) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    state.color = normalizeImageEditColor(color);
    const recoloredCount = setImageEditSelectedObjectsColor(state.color);
    const brush = canvas.freeDrawingBrush;
    if (brush && canvas.isDrawingMode && state.tool === 'brush') {
      brush.color = state.color;
    }
    updateImageEditToolUi();
    if (!recoloredCount) setImageEditStatus(`当前颜色 ${state.color}`, 'info');
  }

    function setImageEditBrushSize(value) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    state.brushSize = Math.max(2, Math.min(120, Number(value) || 22));
    if (canvas.freeDrawingBrush) canvas.freeDrawingBrush.width = state.brushSize;
    const sizeInput = imageEditorElRef.current?.querySelector('[data-image-edit-size]');
    if (sizeInput) sizeInput.value = String(state.brushSize);
  }

    return Object.freeze({
      getImageEditToolIcon,
      getImageEditCursorUrl,
      getImageEditCursorAsset,
      getImageEditShapeIcon,
      applyImageEditObjectControls,
      getImageEditHexColor,
      firstImageEditHexColor,
      getImageEditObjectColor,
      getImageEditSelectedObjects,
      setImageEditPinColor,
      imageEditObjectColorSignature,
      setImageEditObjectColor,
      setImageEditSelectedObjectsColor,
      syncImageEditColorFromSelection,
      handleImageEditSelectionChange,
      normalizeImageEditColor,
      getImageEditObjects,
      removeImageEditObjects,
      createImageEditTextStyle,
      getImageEditShapeMode,
      isImageEditShapeFilled,
      isImageEditShapeEllipse,
      imageEditShapeKind,
      createImageEditShape,
      createImageEditRect,
      createImageEditEllipse,
      buildImageEditArrowPath,
      createImageEditArrow,
      updateImageEditArrow,
      createImageEditPin,
      setImageEditObjectMeta,
      getImageEditPinNumber,
      setImageEditTool,
      getImageEditCursor,
      applyImageEditCursor,
      getImageEditShapeLabel,
      setImageEditShapeMode,
      setImageEditColor,
      setImageEditBrushSize,
    });
  }

  window.DesktopCanvasImageEditorTools = Object.freeze({ create });
})();
