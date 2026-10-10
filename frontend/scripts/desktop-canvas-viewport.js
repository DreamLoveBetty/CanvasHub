// Canvas viewport, zoom gestures and minimap. Load before desktop-canvas.js.
// The host keeps input-event bindings, node/edge operations and persistence.
// Read live state through getCanvas(); deferred frames must not retain an old canvas.
(function () {
  function create({
    getCanvas, els, clamp, getSelectedNodeIds, getNodeBounds, getNodeBoundsById,
    getBoundsFromRects, updateSelectionToolbar, positionEdgeMenu,
    updateInputProgressOverlay, focusCanvasViewport, saveSettings,
    constants: {
      WORLD_WIDTH, WORLD_HEIGHT, MIN_SCALE, MAX_SCALE, ZOOM_PRESETS,
      DEFAULT_CANVAS_SCALE, CANVAS_WHEEL_GESTURE_END_MS,
      CANVAS_COMPACT_ZOOM_THRESHOLD, CANVAS_OVERVIEW_ZOOM_THRESHOLD, IS_MAC_PLATFORM
    }
  }) {
    let canvasPanFrameId = 0;
    let canvasWheelEndTimer = 0;
    let canvasWheelGestureActive = false;
    let miniMapProjection = null;
    let miniMapNavigation = null;
    let panClickGuard = null;

    function resetPanClickGuard() {
      panClickGuard = null;
    }

    function suppressClickAfterPan(event, moved) {
      // Canceling pointerdown suppresses compatibility mouse events, not click.
      // Only a completed primary drag owns a release click; never gate a new
      // physical press or a keyboard/programmatic activation on an idle timer.
      panClickGuard = moved && event?.type === 'pointerup' && event.button === 0
        ? { pointerId: event.pointerId, expiresAt: Date.now() + 350 }
        : null;
    }

    function handlePostPanClick(event) {
      if (!panClickGuard) return false;
      if (Date.now() > panClickGuard.expiresAt) {
        resetPanClickGuard();
        return false;
      }
      if (event.button !== 0 || event.detail === 0) return false;
      if (event.pointerId > 0 && panClickGuard.pointerId != null
        && event.pointerId !== panClickGuard.pointerId) return false;
      resetPanClickGuard();
      event.preventDefault();
      event.stopImmediatePropagation();
      return true;
    }

    function applyCanvasTransform(options = {}) {
      const canvas = getCanvas();
      if (els.deskCanvasViewport) {
        const gridSize = 20 * canvas.scale;
        const gridX = ((canvas.x % gridSize) + gridSize) % gridSize;
        const gridY = ((canvas.y % gridSize) + gridSize) % gridSize;
        els.deskCanvasViewport.style.setProperty('--canvas-grid-size', `${gridSize}px`);
        els.deskCanvasViewport.style.setProperty('--canvas-grid-x', `${gridX}px`);
        els.deskCanvasViewport.style.setProperty('--canvas-grid-y', `${gridY}px`);
      }
      if (els.deskCanvasWorld) {
        // Do not mirror the scale into an inherited custom property here: every
        // descendant would restyle on each zoom frame (nothing reads it).
        const zoomTier = canvas.scale < CANVAS_OVERVIEW_ZOOM_THRESHOLD
          ? 'overview'
          : canvas.scale < CANVAS_COMPACT_ZOOM_THRESHOLD
            ? 'compact'
            : 'detail';
        if (els.deskCanvasWorld.dataset.zoomTier !== zoomTier) {
          els.deskCanvasWorld.dataset.zoomTier = zoomTier;
        }
        els.deskCanvasWorld.style.transform = `translate3d(${canvas.x}px, ${canvas.y}px, 0) scale(${canvas.scale})`;
      }
      if (options.transformOnly) {
        if (getSelectedNodeIds().length >= 2) updateSelectionToolbar();
        return;
      }
      positionEdgeMenu();
      if (els.deskZoomLabel) {
        els.deskZoomLabel.textContent = `${Math.round(canvas.scale * 100)}%`;
      }
      updateZoomPresetButtons();
      renderMiniMap();
      updateSelectionToolbar();
      updateInputProgressOverlay();
    }

    function scheduleCanvasPanTransform() {
      if (canvasPanFrameId) return;
      canvasPanFrameId = requestAnimationFrame(() => {
        canvasPanFrameId = 0;
        applyCanvasTransform({ transformOnly: !miniMapNavigation });
      });
    }

    function flushCanvasPanTransform() {
      if (canvasPanFrameId) cancelAnimationFrame(canvasPanFrameId);
      canvasPanFrameId = 0;
      applyCanvasTransform();
    }

    function updateCanvasZoomLabel() {
      if (!els.deskZoomLabel) return;
      els.deskZoomLabel.textContent = `${Math.round(getCanvas().scale * 100)}%`;
    }

    function finishCanvasWheelGesture(options = {}) {
      if (canvasWheelEndTimer) clearTimeout(canvasWheelEndTimer);
      canvasWheelEndTimer = 0;
      if (!canvasWheelGestureActive) return;
      canvasWheelGestureActive = false;
      flushCanvasPanTransform();
      els.deskCanvasViewport?.classList.remove('is-wheel-transforming');
      if (options.save !== false) saveSettings();
    }

    function scheduleCanvasWheelGestureEnd() {
      if (!canvasWheelGestureActive) {
        canvasWheelGestureActive = true;
        els.deskCanvasViewport?.classList.add('is-wheel-transforming');
      }
      if (canvasWheelEndTimer) clearTimeout(canvasWheelEndTimer);
      canvasWheelEndTimer = setTimeout(finishCanvasWheelGesture, CANVAS_WHEEL_GESTURE_END_MS);
    }

    function getCanvasWorldOrigin(canvas = getCanvas()) {
      const viewport = els.deskCanvasViewport, world = els.deskCanvasWorld;
      // Layout offsets are independent of the CSS transform; do not infer an
      // origin from a DOMRect that may still reflect the previous pan frame.
      if (world && world.offsetParent === viewport) {
        return { x: (viewport.clientLeft || 0) + world.offsetLeft - (viewport.scrollLeft || 0),
          y: (viewport.clientTop || 0) + world.offsetTop - (viewport.scrollTop || 0) };
      }
      const rect = viewport?.getBoundingClientRect();
      const worldRect = world?.getBoundingClientRect?.();
      return { x: worldRect && rect ? worldRect.left - rect.left - canvas.x : 0,
        y: worldRect && rect ? worldRect.top - rect.top - canvas.y : 0 };
    }

    function getMiniMapViewportWorld(canvas) {
      const viewportRect = els.deskCanvasViewport.getBoundingClientRect();
      const origin = getCanvasWorldOrigin(canvas);
      return {
        x: (-canvas.x - origin.x) / canvas.scale,
        y: (-canvas.y - origin.y) / canvas.scale,
        width: viewportRect.width / canvas.scale,
        height: viewportRect.height / canvas.scale
      };
    }

    function calculateMiniMapProjection(nodes, viewportWorld, mapWidth, mapHeight) {
      const bounds = nodes.map(getNodeBounds);
      const minX = Math.min(viewportWorld.x, ...bounds.map(item => item.x), 0) - 140;
      const minY = Math.min(viewportWorld.y, ...bounds.map(item => item.y), 0) - 120;
      const maxX = Math.max(viewportWorld.x + viewportWorld.width, ...bounds.map(item => item.x + item.width), WORLD_WIDTH) + 140;
      const maxY = Math.max(viewportWorld.y + viewportWorld.height, ...bounds.map(item => item.y + item.height), WORLD_HEIGHT) + 120;
      const worldWidth = Math.max(1, maxX - minX);
      const worldHeight = Math.max(1, maxY - minY);
      const mapScale = Math.min(mapWidth / worldWidth, mapHeight / worldHeight);
      const offsetX = (mapWidth - worldWidth * mapScale) / 2;
      const offsetY = (mapHeight - worldHeight * mapScale) / 2;
      return { minX, minY, mapWidth, mapHeight, mapScale, offsetX, offsetY };
    }

    function renderMiniMap() {
      if (!els.deskMiniMap || !els.deskMiniMapWorld || !els.deskMiniMapViewport || !els.deskCanvasViewport) return;
      const canvas = getCanvas();
      // A workflow load replaces the canvas object. The identity below is only
      // a gesture guard; all geometry and writes still resolve live state.
      if (miniMapNavigation && miniMapNavigation.canvas !== canvas) clearMiniMapNavigation();
      const nodes = Object.values(canvas.nodes || {});
      const viewportWorld = getMiniMapViewportWorld(canvas);
      const mapWidth = els.deskMiniMap.clientWidth || 156;
      const mapHeight = els.deskMiniMap.clientHeight || 92;
      // Freeze the projection while dragging: bounds include the viewport, so
      // recomputing them on every move would make the map chase the pointer.
      miniMapProjection = miniMapNavigation?.projection
        || calculateMiniMapProjection(nodes, viewportWorld, mapWidth, mapHeight);
      const { minX, minY, mapScale, offsetX, offsetY } = miniMapProjection;

      const toMapRect = rect => ({
        left: offsetX + (rect.x - minX) * mapScale,
        top: offsetY + (rect.y - minY) * mapScale,
        width: Math.max(4, rect.width * mapScale),
        height: Math.max(3, rect.height * mapScale)
      });

      els.deskMiniMapWorld.innerHTML = nodes.map(node => {
        const rect = toMapRect(getNodeBounds(node));
        const typeClass = node.type === 'output'
          ? 'is-output'
          : (node.type === 'file_output'
            ? 'is-output'
            : (node.type === 'video'
              ? 'is-video'
              : (node.type === 'video_inference'
                ? 'is-video-inference'
                : ((node.type === 'image' || node.type === 'image_group') ? 'is-image' : (node.type === 'pose' ? 'is-pose' : (node.type === 'text' ? 'is-text' : 'is-input'))))));
        return `<span class="desk-minimap__node ${typeClass}" style="left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px"></span>`;
      }).join('');

      const viewport = toMapRect(viewportWorld);
      els.deskMiniMapViewport.style.left = `${viewport.left}px`;
      els.deskMiniMapViewport.style.top = `${viewport.top}px`;
      els.deskMiniMapViewport.style.width = `${Math.max(12, viewport.width)}px`;
      els.deskMiniMapViewport.style.height = `${Math.max(10, viewport.height)}px`;
    }

    function miniMapWorldPoint(event, projection) {
      const map = els.deskMiniMap;
      const rect = map?.getBoundingClientRect();
      if (!projection || !rect?.width || !rect.height || !map.clientHeight
        || !Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return null;
      const borderX = map.clientLeft || 0;
      const borderY = map.clientTop || 0;
      const x = clamp((event.clientX - rect.left) / rect.width * (map.offsetWidth || map.clientWidth + borderX * 2) - borderX, 0, projection.mapWidth);
      const y = clamp((event.clientY - rect.top) / rect.height * (map.offsetHeight || map.clientHeight + borderY * 2) - borderY, 0, projection.mapHeight);
      return { x: projection.minX + (x - projection.offsetX) / projection.mapScale,
        y: projection.minY + (y - projection.offsetY) / projection.mapScale };
    }

    function navigateMiniMapToPoint(point) {
      const canvas = getCanvas();
      const previousX = canvas.x, previousY = canvas.y;
      const rect = els.deskCanvasViewport.getBoundingClientRect();
      // Use the gesture's untransformed origin: DOM translation can lag live
      // x/y by one RAF when several pointer moves arrive in the same frame.
      canvas.x = rect.width / 2 - miniMapNavigation.origin.x - point.x * canvas.scale;
      canvas.y = rect.height / 2 - miniMapNavigation.origin.y - point.y * canvas.scale;
      return canvas.x !== previousX || canvas.y !== previousY;
    }

    function beginMiniMapNavigation(event) {
      if (event.button !== 0 || event.isPrimary === false || miniMapNavigation) return false;
      if (!miniMapWorldPoint(event, miniMapProjection)) return false;
      finishCanvasWheelGesture();
      // Click the projection the user actually sees. Re-measuring here could
      // shift its coordinates while the map's expand animation is settling.
      const point = miniMapWorldPoint(event, miniMapProjection);
      if (!point) return false;
      event.preventDefault();
      event.stopPropagation();
      setZoomPresetMenuOpen(false);
      const canvas = getCanvas(), origin = getCanvasWorldOrigin(canvas);
      miniMapNavigation = { pointerId: event.pointerId, canvas, origin, projection: miniMapProjection, changed: false };
      els.deskMiniMap.classList.add('is-navigating');
      els.deskMiniMap.focus?.({ preventScroll: true });
      els.deskMiniMap.setPointerCapture?.(event.pointerId);
      miniMapNavigation.changed = navigateMiniMapToPoint(point);
      applyCanvasTransform();
      return true;
    }

    function moveMiniMapNavigation(event) {
      if (!miniMapNavigation || event.pointerId !== miniMapNavigation.pointerId) return false;
      if (miniMapNavigation.canvas !== getCanvas()) {
        endMiniMapNavigation(null, { save: false, focus: false });
        return false;
      }
      const point = miniMapWorldPoint(event, miniMapNavigation.projection);
      if (!point) return false;
      event.preventDefault();
      miniMapNavigation.changed = navigateMiniMapToPoint(point) || miniMapNavigation.changed;
      scheduleCanvasPanTransform();
      return true;
    }

    function clearMiniMapNavigation() {
      const navigation = miniMapNavigation;
      miniMapNavigation = null;
      els.deskMiniMap?.classList.remove('is-navigating');
      if (navigation && els.deskMiniMap?.hasPointerCapture?.(navigation.pointerId)) {
        els.deskMiniMap.releasePointerCapture(navigation.pointerId);
      }
      return navigation;
    }

    function endMiniMapNavigation(event = null, options = {}) {
      if (!miniMapNavigation || (event?.pointerId != null && event.pointerId !== miniMapNavigation.pointerId)) return false;
      const navigation = clearMiniMapNavigation();
      flushCanvasPanTransform();
      if (navigation.canvas === getCanvas()) {
        if (navigation.changed && options.save !== false) saveSettings();
        if (options.focus !== false) focusCanvasViewport();
      }
      return true;
    }

    function handleMiniMapKeydown(event) {
      if (event.key === 'Escape' && miniMapNavigation) {
        event.preventDefault();
        event.stopPropagation();
        endMiniMapNavigation();
        return;
      }
      const directions = { ArrowLeft: [1, 0], ArrowRight: [-1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
      const direction = directions[event.key];
      if (!direction || !els.deskMiniMap?.clientHeight) return;
      event.preventDefault();
      event.stopPropagation();
      endMiniMapNavigation(null, { focus: false });
      finishCanvasWheelGesture();
      const rect = els.deskCanvasViewport.getBoundingClientRect();
      const canvas = getCanvas(), step = event.shiftKey ? 0.5 : 0.1;
      canvas.x += direction[0] * rect.width * step;
      canvas.y += direction[1] * rect.height * step;
      applyCanvasTransform();
      saveSettings();
    }

    function cssPxValue(element, propertyName, fallback = 0) {
      if (!element || !window.getComputedStyle) return fallback;
      const value = window.getComputedStyle(element).getPropertyValue(propertyName);
      const parsed = parseFloat(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function getMiniMapTargetHeight(controls, pinned) {
      if (!controls) return 0;
      const controlsStyle = window.getComputedStyle?.(controls);
      const row = controls.querySelector('.desk-zoom-row');
      const rowHeight = row?.getBoundingClientRect?.().height || 0;
      const padding = cssPxValue(controls, 'padding-top') + cssPxValue(controls, 'padding-bottom');
      const border = cssPxValue(controls, 'border-top-width') + cssPxValue(controls, 'border-bottom-width');
      const gap = pinned
        ? (cssPxValue(controls, 'row-gap', Number.NaN) || cssPxValue(controls, 'gap', 0))
        : 0;
      const openHeight = pinned ? cssPxValue(controls, '--desk-minimap-open-height', 92) : 0;
      return Math.ceil(padding + border + gap + rowHeight + openHeight);
    }

    function dispatchMiniMapLayoutChange(pinned, controls) {
      window.dispatchEvent(new CustomEvent('desktop:minimap-layout-change', {
        detail: {
          pinned: !!pinned,
          targetHeight: getMiniMapTargetHeight(controls, !!pinned)
        }
      }));
    }

    function setMiniMapPinned(pinned) {
      const controls = els.deskMiniMapPinBtn?.closest('.desk-zoom-controls');
      const nextPinned = !!pinned;
      if (!nextPinned) endMiniMapNavigation();
      controls?.classList.toggle('is-pinned', nextPinned);
      els.deskMiniMapPinBtn?.setAttribute('aria-pressed', nextPinned ? 'true' : 'false');
      els.deskMiniMap?.setAttribute('tabindex', nextPinned ? '0' : '-1');
      els.deskMiniMap?.setAttribute('aria-hidden', nextPinned ? 'false' : 'true');
      renderMiniMap();
      dispatchMiniMapLayoutChange(nextPinned, controls);
      window.setTimeout(() => {
        renderMiniMap();
        dispatchMiniMapLayoutChange(!!controls?.classList.contains('is-pinned'), controls);
      }, 220);
    }

    function screenToWorld(clientX, clientY) {
      const rect = els.deskCanvasViewport.getBoundingClientRect();
      const canvas = getCanvas();
      return {
        x: (clientX - rect.left - canvas.x) / canvas.scale,
        y: (clientY - rect.top - canvas.y) / canvas.scale
      };
    }

    function getViewportCenterWorldPoint(offsetX = 0, offsetY = 0) {
      const rect = els.deskCanvasViewport?.getBoundingClientRect();
      return rect
        ? screenToWorld(rect.left + rect.width / 2 + offsetX, rect.top + rect.height / 2 + offsetY)
        : { x: 360 + offsetX, y: 260 + offsetY };
    }

    function getPrimaryModelNodeId() {
      const nodes = getCanvas().nodes || {};
      const selectedInput = getSelectedNodeIds().find(nodeId => nodes[nodeId]?.type === 'input');
      if (selectedInput) return selectedInput;
      if (nodes.input?.type === 'input') return 'input';
      return Object.values(nodes).find(node => node?.type === 'input')?.id || '';
    }

    function getPrimaryModelBounds() {
      const primaryModelId = getPrimaryModelNodeId();
      if (primaryModelId) return getNodeBoundsById(primaryModelId);
      const nodeBounds = Object.values(getCanvas().nodes || {})
        .map(node => node ? getNodeBounds(node) : null)
        .filter(Boolean);
      return getBoundsFromRects(nodeBounds);
    }

    function centerCanvasOnBounds(bounds, scale = getCanvas().scale) {
      const rect = els.deskCanvasViewport?.getBoundingClientRect?.();
      if (!rect || !bounds) return false;
      const canvas = getCanvas();
      const origin = getCanvasWorldOrigin(canvas);
      const nextScale = clamp(scale, MIN_SCALE, MAX_SCALE);
      const centerX = bounds.x + bounds.width / 2;
      const centerY = bounds.y + bounds.height / 2;
      canvas.x = rect.width / 2 - origin.x - centerX * nextScale;
      canvas.y = rect.height / 2 - origin.y - centerY * nextScale;
      return true;
    }

    function centerCanvasOnPrimaryModel(scale = getCanvas().scale) {
      return centerCanvasOnBounds(getPrimaryModelBounds(), scale);
    }

    function setCanvasScale(nextScale, anchorClientX, anchorClientY, options = {}) {
      endMiniMapNavigation(null, { focus: false });
      const canvas = getCanvas();
      const previousScale = canvas.scale;
      const scale = clamp(nextScale, MIN_SCALE, MAX_SCALE);
      if (Math.abs(scale - previousScale) < 0.001) return false;

      const rect = els.deskCanvasViewport.getBoundingClientRect();
      const anchorX = anchorClientX == null ? rect.left + rect.width / 2 : anchorClientX;
      const anchorY = anchorClientY == null ? rect.top + rect.height / 2 : anchorClientY;
      const worldPoint = screenToWorld(anchorX, anchorY);

      canvas.scale = scale;
      canvas.x = anchorX - rect.left - worldPoint.x * scale;
      canvas.y = anchorY - rect.top - worldPoint.y * scale;
      if (options.deferTransform) {
        updateCanvasZoomLabel();
        scheduleCanvasPanTransform();
      } else {
        applyCanvasTransform();
      }
      if (options.save !== false) saveSettings();
      return true;
    }

    function setCanvasScaleCenteredOnPrimary(nextScale) {
      endMiniMapNavigation(null, { focus: false });
      const canvas = getCanvas();
      const scale = clamp(nextScale, MIN_SCALE, MAX_SCALE);
      canvas.scale = scale;
      if (!centerCanvasOnPrimaryModel(scale)) {
        canvas.x = 0;
        canvas.y = 0;
      }
      applyCanvasTransform();
      saveSettings();
    }

    function resetCanvasView() {
      endMiniMapNavigation(null, { focus: false });
      const canvas = getCanvas();
      canvas.scale = DEFAULT_CANVAS_SCALE;
      if (!centerCanvasOnPrimaryModel(DEFAULT_CANVAS_SCALE)) {
        canvas.x = 0;
        canvas.y = 0;
      }
      applyCanvasTransform();
      saveSettings();
    }

    function setZoomPresetMenuOpen(open) {
      if (!els.deskZoomPresetMenu || !els.deskZoomLabel) return;
      const nextOpen = !!open;
      updateZoomPresetButtons();
      els.deskZoomPresetMenu.hidden = !nextOpen;
      els.deskZoomLabel.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    }

    function updateZoomPresetButtons() {
      if (!els.deskZoomPresetMenu) return;
      const currentScale = Number(getCanvas().scale || 1);
      els.deskZoomPresetMenu.querySelectorAll('[data-zoom-preset]').forEach(button => {
        const preset = Number(button.dataset.zoomPreset);
        const isActive = Number.isFinite(preset) && Math.abs(currentScale - preset) < 0.01;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-checked', isActive ? 'true' : 'false');
      });
    }

    function toggleZoomPresetMenu() {
      setZoomPresetMenuOpen(!!els.deskZoomPresetMenu?.hidden);
    }

    function applyZoomPreset(scale) {
      if (!ZOOM_PRESETS.includes(scale)) return;
      setZoomPresetMenuOpen(false);
      setCanvasScaleCenteredOnPrimary(scale);
      focusCanvasViewport();
    }

    function handleCanvasWheel(event) {
      const insideNode = !!event.target.closest('.desk-node');
      if (insideNode && !event.metaKey && !event.ctrlKey && !event.altKey) return;
      event.preventDefault();
      endMiniMapNavigation(null, { focus: false });

      const canvas = getCanvas();
      const shouldZoom = event.metaKey || event.ctrlKey || event.altKey || (!IS_MAC_PLATFORM && !event.shiftKey);
      if (shouldZoom) {
        const primaryDelta = Math.abs(event.deltaY || 0) >= Math.abs(event.deltaX || 0) ? event.deltaY : event.deltaX;
        if (!primaryDelta) return;
        const factor = primaryDelta > 0 ? 0.92 : 1.08;
        const changed = setCanvasScale(canvas.scale * factor, event.clientX, event.clientY, {
          deferTransform: true,
          save: false
        });
        if (changed) scheduleCanvasWheelGestureEnd();
        return;
      }

      if (IS_MAC_PLATFORM) {
        canvas.x -= event.deltaX;
        canvas.y -= event.deltaY;
      } else {
        const panX = event.deltaX || event.deltaY;
        canvas.x -= panX;
        if (event.deltaX && event.deltaY) canvas.y -= event.deltaY;
      }
      scheduleCanvasWheelGestureEnd();
      scheduleCanvasPanTransform();
    }

    function isWheelGestureActive() {
      return canvasWheelGestureActive;
    }

    return Object.freeze({
      resetPanClickGuard,
      suppressClickAfterPan,
      handlePostPanClick,
      applyCanvasTransform,
      scheduleCanvasPanTransform,
      flushCanvasPanTransform,
      updateCanvasZoomLabel,
      finishCanvasWheelGesture,
      scheduleCanvasWheelGestureEnd,
      renderMiniMap,
      beginMiniMapNavigation,
      moveMiniMapNavigation,
      endMiniMapNavigation,
      handleMiniMapKeydown,
      cssPxValue,
      getMiniMapTargetHeight,
      dispatchMiniMapLayoutChange,
      setMiniMapPinned,
      screenToWorld,
      getViewportCenterWorldPoint,
      getPrimaryModelNodeId,
      getPrimaryModelBounds,
      centerCanvasOnBounds,
      centerCanvasOnPrimaryModel,
      setCanvasScale,
      setCanvasScaleCenteredOnPrimary,
      resetCanvasView,
      setZoomPresetMenuOpen,
      updateZoomPresetButtons,
      toggleZoomPresetMenu,
      applyZoomPreset,
      handleCanvasWheel,
      isWheelGestureActive
    });
  }

  window.DesktopCanvasViewport = Object.freeze({ create });
})();
