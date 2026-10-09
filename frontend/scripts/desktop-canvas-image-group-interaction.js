// 图片组 FLIP/成组解组转场、手势排序、proximity dwell/live preview/release/drop 生命周期及组内焦点交互；通过模型回调提交实际成组/排序。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    IMAGE_GROUP_BASE_THUMB_PX,
    IMAGE_GROUP_IDENTITY_WIDTH_PX,
    IMAGE_GROUP_MAX_COLUMNS,
    IMAGE_GROUP_MAX_ITEMS,
    IMAGE_GROUP_MOTHER_HEIGHT_PX,
    IMAGE_GROUP_MOTHER_RADIUS_PX,
    IMAGE_GROUP_MOTHER_TOP_PX,
    IMAGE_GROUP_PROXIMITY_CONTACT_PX,
    IMAGE_GROUP_PROXIMITY_DISTANCE_PX,
    IMAGE_GROUP_PROXIMITY_DROP_MS,
    IMAGE_GROUP_PROXIMITY_DROP_PX,
    IMAGE_GROUP_PROXIMITY_DWELL_MS,
    IMAGE_GROUP_PROXIMITY_RELEASE_MS,
    IMAGE_GROUP_PROXIMITY_RELEASE_PX,
    IMAGE_GROUP_ROW_STEP_PX,
    IMAGE_GROUP_THUMB_PX,
    IMAGE_GROUP_THUMB_STEP_PX,
    IMAGE_GROUP_TRANSITION_THUMB_PX,
    activeInteractionRef,
    appendImageNodeToGroup,
    clamp,
    createImageGroupFromNodes,
    draggedImageGroupItemRef,
    getNodeElement,
    getSelectedNodeIds,
    hideSmartGuides,
    imageGroupGooeyFilterPrimitivesHtml,
    imageGroupItemSource,
    imageGroupLiquidField,
    imageGroupMotherHeight,
    imageGroupUiSize,
    imageNodeSource,
    naturalImageGroupNodeWidth,
    normalizeImageGroupNodeState,
    prefersReducedMotion,
    reorderImageGroupItemToIndex,
    screenToWorld,
    selectNode,
    sortImageNodesForGroup,
  }) {
    let imageGroupSortFrameId = 0;
    const imageGroupSortCleanupTimers = new WeakMap();

    function captureImageNodeTransitionSources(nodes) {
    return nodes.map(node => {
      const element = getNodeElement(node.id);
      const rect = element?.getBoundingClientRect?.();
      return rect ? {
        sourceNodeId: node.id,
        source: imageNodeSource(node),
        rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
      } : null;
    }).filter(Boolean);
  }

    function orderTransitionSourcesForNodes(sources, nodes) {
    const byNodeId = new Map((sources || []).map(source => [source.sourceNodeId, source]));
    return nodes.map(node => byNodeId.get(node.id)).filter(Boolean);
  }

    function captureImageGroupItemRects(groupId) {
    const element = getNodeElement(groupId);
    if (!element) return new Map();
    return new Map(Array.from(element.querySelectorAll('[data-image-group-item]')).map(item => {
      const snapshot = target => {
        if (!target) return null;
        const rect = target.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      };
      const blob = element.querySelector(`[data-image-group-goo-item="${CSS.escape(item.dataset.imageGroupItem)}"]`);
      return [item.dataset.imageGroupItem, {
        item: snapshot(item),
        blob: snapshot(blob)
      }];
    }));
  }

    function animateImageGroupItemFlip(groupId, before) {
    if (prefersReducedMotion()) return;
    const element = getNodeElement(groupId);
    const canvasScale = Math.max(0.01, Number(DesktopState.state.canvas.scale) || 1);
    element?.querySelectorAll('[data-image-group-item]').forEach(item => {
      const previousEntry = before.get(item.dataset.imageGroupItem);
      const previous = previousEntry?.item || previousEntry;
      if (!previous || !item.animate) return;
      const rect = item.getBoundingClientRect();
      const dx = (
        previous.left + previous.width / 2 - rect.left - rect.width / 2
      ) / canvasScale;
      const dy = (
        previous.top + previous.height / 2 - rect.top - rect.height / 2
      ) / canvasScale;
      const scaleX = previous.width / Math.max(1, rect.width);
      const scaleY = previous.height / Math.max(1, rect.height);
      if (!dx && !dy && scaleX === 1 && scaleY === 1) return;
      item.animate([
        { transform: `translate(${dx}px, ${dy}px) scale(${scaleX}, ${scaleY})`, zIndex: 3 },
        { transform: 'translate(0, 0)', zIndex: 3 }
      ], { duration: 360, easing: 'cubic-bezier(.2,.8,.2,1)' });
      const blob = element.querySelector(`[data-image-group-goo-item="${CSS.escape(item.dataset.imageGroupItem)}"]`);
      const previousBlob = previousEntry?.blob;
      if (blob?.animate && previousBlob) {
        const blobRect = blob.getBoundingClientRect();
        const blobDx = (
          previousBlob.left + previousBlob.width / 2 - blobRect.left - blobRect.width / 2
        ) / canvasScale;
        const blobDy = (
          previousBlob.top + previousBlob.height / 2 - blobRect.top - blobRect.height / 2
        ) / canvasScale;
        const blobScaleX = previousBlob.width / Math.max(1, blobRect.width);
        const blobScaleY = previousBlob.height / Math.max(1, blobRect.height);
        if (blobDx || blobDy || blobScaleX !== 1 || blobScaleY !== 1) {
          blob.animate([
            { transform: `translate(${blobDx}px, ${blobDy}px) scale(${Math.max(blobScaleX, blobScaleY)})` },
            { transform: 'translate(0, 0) scale(1)' }
          ], { duration: 420, easing: 'cubic-bezier(.2,.8,.2,1)' });
        }
      }
    });
  }

    function imageGroupSortTransform(sortState, entry, screenDx, screenDy = 0, scale = 1, blobTransform = null) {
    const dx = screenDx / sortState.canvasScale;
    const dy = screenDy / sortState.canvasScale;
    entry.element.style.transform = `translate3d(${dx}px, ${dy}px, 0) scale(${scale})`;
    if (entry.blob) {
      const blobDx = (blobTransform?.screenDx ?? screenDx) / sortState.canvasScale;
      const blobDy = (blobTransform?.screenDy ?? screenDy) / sortState.canvasScale;
      const blobScale = blobTransform?.scale ?? scale;
      entry.blob.style.transform = `translate(${blobDx}px, ${blobDy}px) scale(${blobScale})`;
    }
  }

    function beginImageGroupItemSort(event) {
    if (event.button !== 0 || event.isPrimary === false || draggedImageGroupItemRef.current) return;
    const handle = event.target.closest('[data-image-group-sort-handle]');
    const itemElement = handle?.closest('[data-image-group-item]');
    const groupElement = itemElement?.closest('.desk-node--image-group[data-node-id]');
    if (!handle || !itemElement || !groupElement || groupElement.classList.contains('is-sorting')) return;
    const itemElements = Array.from(groupElement.querySelectorAll('[data-image-group-item]'));
    if (itemElements.length < 2) return;
    const itemId = itemElement.dataset.imageGroupItem;
    const fromIndex = itemElements.findIndex(item => item.dataset.imageGroupItem === itemId);
    if (fromIndex < 0) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (!getSelectedNodeIds().includes(groupElement.dataset.nodeId)) selectNode(groupElement.dataset.nodeId);
    const pendingCleanup = imageGroupSortCleanupTimers.get(groupElement);
    if (pendingCleanup) window.clearTimeout(pendingCleanup);
    imageGroupSortCleanupTimers.delete(groupElement);

    const itemEntries = itemElements.map((element, index) => {
      const rect = element.getBoundingClientRect();
      return {
        itemId: element.dataset.imageGroupItem,
        element,
        index,
        rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
        blob: groupElement.querySelector(`[data-image-group-goo-item="${CSS.escape(element.dataset.imageGroupItem)}"]`)
      };
    });
    draggedImageGroupItemRef.current = {
      groupId: groupElement.dataset.nodeId,
      itemId,
      pointerId: event.pointerId,
      handle,
      groupElement,
      itemEntries,
      fromIndex,
      targetIndex: fromIndex,
      startClientX: event.clientX,
      startClientY: event.clientY,
      clientX: event.clientX,
      clientY: event.clientY,
      canvasScale: Math.max(0.01, Number(DesktopState.state.canvas.scale) || 1),
      moved: false
    };
    itemElement.classList.add('is-dragging');
    itemElement.setAttribute('aria-grabbed', 'true');
    groupElement.classList.add('is-sorting');
    document.body.classList.add('desk-image-group-sorting');
    try {
      handle.setPointerCapture?.(event.pointerId);
    } catch {}
  }

    function renderImageGroupItemSortFrame(sortState) {
    if (!sortState) return;
    const dx = sortState.clientX - sortState.startClientX;
    const dy = sortState.clientY - sortState.startClientY;
    if (!sortState.moved && Math.hypot(dx, dy) < 4) return;
    sortState.moved = true;

    const draggedEntry = sortState.itemEntries[sortState.fromIndex];
    const draggedCenter = {
      x: draggedEntry.rect.left + draggedEntry.rect.width / 2 + dx,
      y: draggedEntry.rect.top + draggedEntry.rect.height / 2 + dy
    };
    const remaining = sortState.itemEntries.filter(entry => entry.itemId !== sortState.itemId);
    const closestSlot = sortState.itemEntries.reduce((winner, entry) => {
      const centerX = entry.rect.left + entry.rect.width / 2;
      const centerY = entry.rect.top + entry.rect.height / 2;
      const distance = Math.hypot(draggedCenter.x - centerX, draggedCenter.y - centerY);
      return !winner || distance < winner.distance ? { index: entry.index, distance } : winner;
    }, null);
    sortState.targetIndex = clamp(closestSlot?.index ?? sortState.fromIndex, 0, sortState.itemEntries.length - 1);
    sortState.groupElement.dataset.sortTargetIndex = String(sortState.targetIndex);

    const previewOrder = remaining.map(entry => entry.itemId);
    previewOrder.splice(sortState.targetIndex, 0, sortState.itemId);
    sortState.itemEntries.forEach(entry => {
      if (entry.itemId === sortState.itemId) {
        const targetSlot = sortState.itemEntries[sortState.targetIndex]?.rect;
        imageGroupSortTransform(sortState, entry, dx, dy, 1.06, {
          screenDx: (targetSlot?.left ?? entry.rect.left) - entry.rect.left,
          screenDy: (targetSlot?.top ?? entry.rect.top) - entry.rect.top,
          scale: 1
        });
        return;
      }
      const previewIndex = previewOrder.indexOf(entry.itemId);
      const targetSlot = sortState.itemEntries[previewIndex]?.rect;
      imageGroupSortTransform(
        sortState,
        entry,
        (targetSlot?.left ?? entry.rect.left) - entry.rect.left,
        (targetSlot?.top ?? entry.rect.top) - entry.rect.top
      );
    });
  }

    function moveImageGroupItemSort(event) {
    const sortState = draggedImageGroupItemRef.current;
    if (!sortState || event.pointerId !== sortState.pointerId) return;
    event.preventDefault();
    sortState.clientX = event.clientX;
    sortState.clientY = event.clientY;
    if (imageGroupSortFrameId) return;
    imageGroupSortFrameId = requestAnimationFrame(() => {
      imageGroupSortFrameId = 0;
      if (draggedImageGroupItemRef.current === sortState) renderImageGroupItemSortFrame(sortState);
    });
  }

    function clearImageGroupItemSortState(sortState, delay = 0) {
    document.body.classList.remove('desk-image-group-sorting');
    sortState.groupElement?.removeAttribute('data-sort-target-index');
    const groupElement = sortState.groupElement;
    const previousTimer = groupElement ? imageGroupSortCleanupTimers.get(groupElement) : 0;
    if (previousTimer) window.clearTimeout(previousTimer);
    const clearGroup = timerId => {
      if (!groupElement) return;
      if (timerId && imageGroupSortCleanupTimers.get(groupElement) !== timerId) return;
      imageGroupSortCleanupTimers.delete(groupElement);
      if (draggedImageGroupItemRef.current?.groupElement !== groupElement) groupElement.classList.remove('is-sorting');
    };
    if (delay > 0 && groupElement) {
      const timerId = window.setTimeout(() => clearGroup(timerId), delay);
      imageGroupSortCleanupTimers.set(groupElement, timerId);
    } else {
      clearGroup(0);
    }
    sortState.itemEntries.forEach(entry => {
      entry.element.classList.remove('is-dragging');
      entry.element.removeAttribute('aria-grabbed');
      entry.element.style.removeProperty('transform');
      entry.blob?.style.removeProperty('transform');
    });
  }

    function returnImageGroupItemSort(sortState) {
    const reducedMotion = prefersReducedMotion();
    const duration = reducedMotion ? 0 : 240;
    sortState.itemEntries.forEach(entry => {
      const itemTransform = entry.element.style.transform;
      const blobTransform = entry.blob?.style.transform;
      if (duration && itemTransform && itemTransform !== 'none') {
        entry.element.animate([
          { transform: itemTransform },
          { transform: 'translate3d(0, 0, 0) scale(1)' }
        ], { duration, easing: 'cubic-bezier(.2,.8,.2,1)' });
      }
      if (duration && entry.blob && blobTransform && blobTransform !== 'none') {
        entry.blob.animate([
          { transform: blobTransform },
          { transform: 'translate(0, 0) scale(1)' }
        ], { duration: duration + 60, easing: 'cubic-bezier(.2,.8,.2,1)' });
      }
    });
    clearImageGroupItemSortState(sortState, duration ? duration + 70 : 0);
  }

    function endImageGroupItemSort(event, cancelled = false) {
    const sortState = draggedImageGroupItemRef.current;
    if (!sortState || (event?.pointerId != null && event.pointerId !== sortState.pointerId)) return;
    event?.preventDefault?.();
    try {
      sortState.handle.releasePointerCapture?.(sortState.pointerId);
    } catch {}
    if (imageGroupSortFrameId) {
      cancelAnimationFrame(imageGroupSortFrameId);
      imageGroupSortFrameId = 0;
      renderImageGroupItemSortFrame(sortState);
    }
    draggedImageGroupItemRef.current = null;

    const shouldCommit = !cancelled && sortState.moved && sortState.targetIndex !== sortState.fromIndex;
    if (!shouldCommit) {
      returnImageGroupItemSort(sortState);
      return;
    }
    const before = captureImageGroupItemRects(sortState.groupId);
    const reordered = reorderImageGroupItemToIndex(
      sortState.groupId,
      sortState.itemId,
      sortState.targetIndex,
      before
    );
    if (!reordered) {
      returnImageGroupItemSort(sortState);
      return;
    }
    const settleDuration = prefersReducedMotion() ? 0 : 460;
    clearImageGroupItemSortState(sortState, settleDuration);
  }

    function ensureGlobalImageGroupGooeyFilter() {
    const id = 'desk-image-group-transition-gooey';
    if (document.getElementById(id)) return id;
    document.body.insertAdjacentHTML('beforeend', `
      <svg class="desk-image-group__global-filter" aria-hidden="true">
        <defs>
          <filter id="${id}" x="-45%" y="-45%" width="190%" height="190%" color-interpolation-filters="sRGB">${imageGroupGooeyFilterPrimitivesHtml()}</filter>
        </defs>
      </svg>`);
    return id;
  }

    function cappedTransitionRect(rect, maxSide = IMAGE_GROUP_TRANSITION_THUMB_PX) {
    const width = Math.max(32, Number(rect?.width) || 32);
    const height = Math.max(32, Number(rect?.height) || 32);
    const side = clamp(Math.min(width, height, maxSide), 38, maxSide);
    return {
      left: Number(rect?.left || 0) + (width - side) / 2,
      top: Number(rect?.top || 0) + (height - side) / 2,
      width: side,
      height: side
    };
  }

    function animateImageTransition(pairs, focusRect, options = {}) {
    if (!pairs.length || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const filterId = ensureGlobalImageGroupGooeyFilter();
    const overlay = document.createElement('div');
    overlay.className = 'desk-image-group-transition';
    const gooLayer = document.createElement('div');
    gooLayer.className = 'desk-image-group-transition__goo';
    gooLayer.style.filter = `url(#${filterId})`;
    const imageLayer = document.createElement('div');
    imageLayer.className = 'desk-image-group-transition__images';
    overlay.append(gooLayer, imageLayer);
    document.body.appendChild(overlay);
    const duration = options.duration || 560;
    const animations = [];
    pairs.forEach((pair, index) => {
      const start = cappedTransitionRect(pair.from);
      const end = cappedTransitionRect(pair.to);
      const spread = Math.min(34, start.width * 0.52);
      const midX = Number(focusRect?.left || 0) + Number(focusRect?.width || 0) / 2 - start.width / 2
        + (index - (pairs.length - 1) / 2) * spread;
      const midY = Number(focusRect?.top || 0) + Number(focusRect?.height || 0) / 2 - start.height / 2;
      const dx = end.left - start.left;
      const dy = end.top - start.top;
      const midDx = midX - start.left + (index - (pairs.length - 1) / 2) * 5;
      const midDy = midY - start.top;
      const scaleX = end.width / start.width;
      const scaleY = end.height / start.height;
      const delay = index * 24;
      const blob = document.createElement('span');
      blob.style.left = `${start.left}px`;
      blob.style.top = `${start.top}px`;
      blob.style.width = `${start.width}px`;
      blob.style.height = `${start.height}px`;
      gooLayer.appendChild(blob);
      const image = document.createElement('img');
      image.src = pair.source;
      image.alt = '';
      image.style.left = `${start.left}px`;
      image.style.top = `${start.top}px`;
      image.style.width = `${start.width}px`;
      image.style.height = `${start.height}px`;
      imageLayer.appendChild(image);
      const keyframes = [
        { transform: 'translate(0, 0) scale(1)', opacity: 0.98, offset: 0 },
        { transform: `translate(${midDx}px, ${midDy}px) scale(.92)`, opacity: 1, offset: 0.64 },
        { transform: `translate(${dx}px, ${dy}px) scale(${scaleX}, ${scaleY})`, opacity: 0.98, offset: 1 }
      ];
      animations.push(blob.animate(keyframes, { duration, delay, fill: 'forwards', easing: 'cubic-bezier(.2,.78,.18,1)' }));
      animations.push(image.animate(keyframes, { duration, delay, fill: 'forwards', easing: 'cubic-bezier(.2,.78,.18,1)' }));
    });
    Promise.allSettled(animations.map(animation => animation.finished)).finally(() => overlay.remove());
    window.setTimeout(() => overlay.remove(), duration + pairs.length * 24 + 180);
  }

    function animateImagesIntoGroup(sources, groupId) {
    const groupElement = getNodeElement(groupId);
    if (!groupElement || !sources.length) return;
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    const fallbackTargets = Array.from(groupElement.querySelectorAll('[data-image-group-item] .desk-image-group__thumb'));
    const pairs = sources.map((source, index) => ({
      source: source.source,
      from: source.rect,
      to: (() => {
        const item = groupNode?.items?.find(candidate => candidate.sourceNodeId === source.sourceNodeId);
        const target = item
          ? groupElement.querySelector(`[data-image-group-item="${CSS.escape(item.itemId)}"] .desk-image-group__thumb`)
          : fallbackTargets[index];
        return target?.getBoundingClientRect?.() || groupElement.getBoundingClientRect();
      })()
    }));
    const focusRect = groupElement.getBoundingClientRect();
    groupElement.animate?.([
      { opacity: 0, transform: 'scale(.92)' },
      { opacity: 0, transform: 'scale(.96)', offset: 0.55 },
      { opacity: 1, transform: 'scale(1)' }
    ], { duration: 650, easing: 'cubic-bezier(.2,.8,.2,1)' });
    animateImageTransition(pairs, focusRect);
  }

    function animateImagesOutOfGroup(sources, restoredNodes) {
    if (!sources.length || !restoredNodes.length) return;
    const targetRects = restoredNodes.map(node => getNodeElement(node.id)?.getBoundingClientRect?.()).filter(Boolean);
    const focusRect = sources.reduce((acc, source) => ({
      left: Math.min(acc.left, source.rect.left),
      top: Math.min(acc.top, source.rect.top),
      right: Math.max(acc.right, source.rect.right),
      bottom: Math.max(acc.bottom, source.rect.bottom)
    }), { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity });
    const normalizedFocus = {
      left: focusRect.left,
      top: focusRect.top,
      width: Math.max(1, focusRect.right - focusRect.left),
      height: Math.max(1, focusRect.bottom - focusRect.top)
    };
    animateImageTransition(sources.map((source, index) => ({
      source: source.source,
      from: source.rect,
      to: targetRects[index] || source.rect
    })), normalizedFocus, { duration: 560 });
  }

    function rectGapDistance(first, second) {
    const dx = Math.max(first.left - second.right, second.left - first.right, 0);
    const dy = Math.max(first.top - second.bottom, second.top - first.bottom, 0);
    return Math.hypot(dx, dy);
  }

    function mergeAnchorBetweenRects(first, second) {
    const firstCenterX = first.left + first.width / 2;
    const firstCenterY = first.top + first.height / 2;
    const secondCenterX = second.left + second.width / 2;
    const secondCenterY = second.top + second.height / 2;
    const firstPoint = {
      x: clamp(secondCenterX, first.left, first.right),
      y: clamp(secondCenterY, first.top, first.bottom)
    };
    const secondPoint = {
      x: clamp(firstCenterX, second.left, second.right),
      y: clamp(firstCenterY, second.top, second.bottom)
    };
    return {
      x: (firstPoint.x + secondPoint.x) / 2,
      y: (firstPoint.y + secondPoint.y) / 2
    };
  }

    function eligibleImageGroupProximityTarget(node, sourceNodeId, excludedIds) {
    if (!node || node.id === sourceNodeId || excludedIds.has(node.id)) return false;
    if (node.type === 'image') return Boolean(imageNodeSource(node));
    return node.type === 'image_group'
      && node.items?.length < IMAGE_GROUP_MAX_ITEMS
      && node.items.some(imageGroupItemSource);
  }

    function findImageGroupProximityCandidate(interaction, threshold = IMAGE_GROUP_PROXIMITY_DISTANCE_PX) {
    if (interaction?.type !== 'node-drag' || interaction.groupIds?.length !== 1) return null;
    const sourceNode = DesktopState.state.canvas.nodes[interaction.nodeId];
    const sourceElement = getNodeElement(interaction.nodeId);
    if (sourceNode?.type !== 'image' || !imageNodeSource(sourceNode) || !sourceElement) return null;
    const sourceRect = sourceElement.getBoundingClientRect();
    const excludedIds = new Set(interaction.groupIds || [interaction.nodeId]);
    let winner = null;
    Object.values(DesktopState.state.canvas.nodes || {}).forEach(node => {
      if (!eligibleImageGroupProximityTarget(node, interaction.nodeId, excludedIds)) return;
      const element = getNodeElement(node.id);
      if (!element) return;
      const targetRect = element.getBoundingClientRect();
      const distance = rectGapDistance(sourceRect, targetRect);
      if (distance > threshold) return;
      const score = distance - (node.type === 'image_group' ? 0.25 : 0);
      if (!winner || score < winner.score) winner = { nodeId: node.id, distance, score, sourceRect, targetRect };
    });
    return winner;
  }

    function positionImageGroupDwellIndicator(indicator, sourceRect, targetRect) {
    if (!indicator || !sourceRect || !targetRect) return;
    const anchor = mergeAnchorBetweenRects(sourceRect, targetRect);
    indicator.style.left = `${anchor.x}px`;
    indicator.style.top = `${anchor.y}px`;
  }

    function createImageGroupDwellIndicator(sourceRect, targetRect) {
    const indicator = document.createElement('div');
    indicator.className = 'desk-image-group-dwell';
    indicator.setAttribute('aria-hidden', 'true');
    indicator.style.setProperty('--desk-image-group-dwell-ms', `${IMAGE_GROUP_PROXIMITY_DWELL_MS}ms`);
    indicator.innerHTML = `
      <svg viewBox="0 0 36 36">
        <circle class="desk-image-group-dwell__track" cx="18" cy="18" r="15"></circle>
        <circle class="desk-image-group-dwell__progress" cx="18" cy="18" r="15" pathLength="1"></circle>
      </svg>
      <span></span>`;
    positionImageGroupDwellIndicator(indicator, sourceRect, targetRect);
    document.body.appendChild(indicator);
    return indicator;
  }

    function imageGroupProximityPreviewEntries(sourceNodeId, targetNodeId) {
    const sourceNode = DesktopState.state.canvas.nodes[sourceNodeId];
    const targetNode = DesktopState.state.canvas.nodes[targetNodeId];
    const sourceElement = getNodeElement(sourceNodeId);
    const targetElement = getNodeElement(targetNodeId);
    if (!sourceNode || !targetNode || !sourceElement || !targetElement) return [];
    if (targetNode.type === 'image') {
      return sortImageNodesForGroup([sourceNode, targetNode]).map(node => ({
        sourceNodeId: node.id,
        source: imageNodeSource(node),
        rect: getNodeElement(node.id)?.getBoundingClientRect?.(),
        incoming: node.id === sourceNodeId
      })).filter(entry => entry.source && entry.rect);
    }
    if (targetNode.type !== 'image_group') return [];
    normalizeImageGroupNodeState(targetNode);
    const entries = targetNode.items.map(item => ({
      sourceNodeId: item.sourceNodeId,
      source: imageGroupItemSource(item),
      rect: targetElement.querySelector(`[data-image-group-item="${CSS.escape(item.itemId)}"] .desk-image-group__thumb`)?.getBoundingClientRect?.(),
      incoming: false
    })).filter(entry => entry.source && entry.rect);
    entries.push({
      sourceNodeId,
      source: imageNodeSource(sourceNode),
      rect: sourceElement.getBoundingClientRect(),
      incoming: true
    });
    return entries;
  }

    function setImageGroupPreviewChipUnit(chip, side) {
    chip?.style.setProperty('--desk-image-group-chip-unit', `${Math.max(0.1, Number(side) || 0) / IMAGE_GROUP_BASE_THUMB_PX}px`);
  }

    function liveImageGroupSmoothstep(value) {
    const t = clamp(Number(value) || 0, 0, 1);
    return t * t * (3 - 2 * t);
  }

    function liveImageGroupEase(value) {
    const t = clamp(Number(value) || 0, 0, 1);
    return 1 - Math.pow(1 - t, 3);
  }

    function liveImageGroupRoundedRectContact(point, rect, cornerRadius) {
    const right = Number.isFinite(rect.right) ? rect.right : rect.left + rect.width;
    const bottom = Number.isFinite(rect.bottom) ? rect.bottom : rect.top + rect.height;
    const radius = clamp(Number(cornerRadius) || 0, 0, Math.min(rect.width, rect.height) / 2);
    const coreLeft = rect.left + radius;
    const coreRight = right - radius;
    const coreTop = rect.top + radius;
    const coreBottom = bottom - radius;
    const corePoint = {
      x: clamp(point.x, coreLeft, coreRight),
      y: clamp(point.y, coreTop, coreBottom)
    };
    const dx = point.x - corePoint.x;
    const dy = point.y - corePoint.y;
    const length = Math.hypot(dx, dy);
    if (length > 0.001) {
      const normal = { x: dx / length, y: dy / length };
      return {
        surface: {
          x: corePoint.x + normal.x * radius,
          y: corePoint.y + normal.y * radius
        },
        normal,
        distance: length - radius
      };
    }
    const edges = [
      { distance: point.x - rect.left, surface: { x: rect.left, y: point.y }, normal: { x: -1, y: 0 } },
      { distance: right - point.x, surface: { x: right, y: point.y }, normal: { x: 1, y: 0 } },
      { distance: point.y - rect.top, surface: { x: point.x, y: rect.top }, normal: { x: 0, y: -1 } },
      { distance: bottom - point.y, surface: { x: point.x, y: bottom }, normal: { x: 0, y: 1 } }
    ];
    const nearest = edges.reduce((winner, edge) => edge.distance < winner.distance ? edge : winner);
    return { surface: nearest.surface, normal: nearest.normal, distance: -Math.max(0, nearest.distance) };
  }

    function liveImageGroupApproachContact(sourcePoint, targetPoint, rect, cornerRadius) {
    const directContact = liveImageGroupRoundedRectContact(sourcePoint, rect, cornerRadius);
    if (directContact.distance >= 0) return directContact;
    let dx = sourcePoint.x - targetPoint.x;
    let dy = sourcePoint.y - targetPoint.y;
    let length = Math.hypot(dx, dy);
    if (length < 0.001) {
      dx = sourcePoint.x < rect.left + rect.width / 2 ? -1 : 1;
      dy = 0;
      length = 1;
    }
    const normal = { x: dx / length, y: dy / length };
    const reach = Math.hypot(rect.width, rect.height) + Math.max(0, Number(cornerRadius) || 0) + 1;
    return liveImageGroupRoundedRectContact({
      x: rect.left + rect.width / 2 + normal.x * reach,
      y: rect.top + rect.height / 2 + normal.y * reach
    }, rect, cornerRadius);
  }

    function liveImageGroupChip(entry, imageLayer, incoming = false) {
    const chip = document.createElement('div');
    chip.className = `desk-image-group-transition__chip${incoming ? ' is-incoming' : ''}`;
    const image = document.createElement('img');
    image.src = entry.source;
    image.alt = '';
    image.draggable = false;
    const badge = document.createElement('strong');
    badge.textContent = '1';
    chip.append(image, badge);
    imageLayer.appendChild(chip);
    return { ...entry, chip, image, badge };
  }

    function createLiveImageGroupLiquify(defs, id, image, outline) {
    return imageGroupLiquidField.create(defs, id, image, outline);
  }

    function renderLiveImageGroupLiquify(effect, normal, strength, size, coverage = 0, elapsedMs = 0) {
    imageGroupLiquidField.render(effect, normal, strength, size, coverage, elapsedMs);
  }

    function liveImageGroupLiquidCoverage(center, rect, radius, cornerRadius) {
    const contact = liveImageGroupRoundedRectContact(center, rect, cornerRadius);
    return liveImageGroupSmoothstep(-contact.distance / Math.max(1, radius));
  }

    function liveImageGroupMotherPath(rect, radius, contact, strength, size) {
    const { left, top, width, height } = rect;
    const right = left + width, bottom = top + height;
    const r = clamp(radius, 0, Math.min(width, height) / 2);
    const amount = clamp(Number(strength) || 0, 0, 1);
    if (amount < 0.002) {
      return `M ${left + r} ${top} H ${right - r} A ${r} ${r} 0 0 1 ${right} ${top + r}`
        + ` V ${bottom - r} A ${r} ${r} 0 0 1 ${right - r} ${bottom}`
        + ` H ${left + r} A ${r} ${r} 0 0 1 ${left} ${bottom - r}`
        + ` V ${top + r} A ${r} ${r} 0 0 1 ${left + r} ${top} Z`;
    }
    // Pull only the contact neighbourhood toward the incoming droplet. The
    // same contact normal/strength drives the photo in the opposite direction.
    // Sampling is bounded (<= 304 points); the shared goo filter smooths the
    // contour before drawing its edge. No clip or whole-card scale is used.
    const side = Math.max(1, Number(size) || 1);
    const length = Math.hypot(contact.normal.x, contact.normal.y) || 1;
    const nx = contact.normal.x / length, ny = contact.normal.y / length;
    const points = [];
    const point = (x, y) => {
      const dx = x - contact.surface.x, dy = y - contact.surface.y;
      const tangent = (-ny * dx + nx * dy) / (side * 0.38);
      const depth = (nx * dx + ny * dy) / (side * 0.4);
      const pull = side * 0.22 * amount * Math.exp(-0.5 * (tangent * tangent + depth * depth));
      points.push(`${(x + nx * pull).toFixed(3)} ${(y + ny * pull).toFixed(3)}`);
    };
    const line = (ax, ay, bx, by) => {
      const count = clamp(Math.ceil(Math.hypot(bx - ax, by - ay) / Math.max(2, side * 0.06)), 1, 64);
      for (let i = 0; i < count; i += 1) point(ax + (bx - ax) * i / count, ay + (by - ay) * i / count);
    };
    const corner = (cx, cy, start) => {
      for (let i = 0; i < 12; i += 1) {
        const angle = start + i / 12 * Math.PI / 2;
        point(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
      }
    };
    line(left + r, top, right - r, top); corner(right - r, top + r, -Math.PI / 2);
    line(right, top + r, right, bottom - r); corner(right - r, bottom - r, 0);
    line(right - r, bottom, left + r, bottom); corner(left + r, bottom - r, Math.PI / 2);
    line(left, bottom - r, left, top + r); corner(left + r, top + r, Math.PI);
    return `M ${points.join(' L ')} Z`;
  }

    function liveImageGroupSlotPosition(preview, index) {
    const normalizedIndex = Math.max(0, Math.round(Number(index) || 0));
    const column = normalizedIndex % IMAGE_GROUP_MAX_COLUMNS;
    const row = Math.floor(normalizedIndex / IMAGE_GROUP_MAX_COLUMNS);
    const left = preview.baseLeft + preview.thumbStart + column * preview.step;
    const top = preview.baseTop + preview.rowInset + row * preview.rowStep;
    return {
      left,
      top,
      x: left + preview.thumbSize / 2,
      y: top + preview.thumbSize / 2
    };
  }

    function liveImageGroupSlotIndex(preview, center) {
    const count = preview.targetItems.length;
    if (!count) return 0;
    const point = typeof center === 'number' ? { x: center, y: preview.baseTop + preview.rowInset } : center;
    let winner = { index: 0, distance: Number.POSITIVE_INFINITY };
    for (let index = 0; index <= count; index += 1) {
      const slot = liveImageGroupSlotPosition(preview, index);
      const distance = Math.hypot((point?.x || 0) - slot.x, (point?.y || 0) - slot.y);
      if (distance < winner.distance) winner = { index, distance };
    }
    return winner.index;
  }

    function liveImageGroupSlotCenter(preview, index) {
    const position = liveImageGroupSlotPosition(preview, index);
    return { x: position.x, y: position.y };
  }

    function renderLiveImageGroupPreview(preview, now = performance.now(), immediate = false) {
    if (!preview?.active) return;
    const elapsed = Math.max(0, now - preview.introStartedAt);
    const intro = preview.committing || preview.reducedMotion
      ? 1
      : liveImageGroupEase(clamp(elapsed / preview.introDuration, 0, 1));
    const pointerCenter = {
      x: preview.pointerX,
      y: preview.pointerY
    };
    const body = {
      left: preview.baseLeft,
      top: preview.baseTop,
      width: preview.currentWidth,
      height: preview.currentHeight,
      right: preview.baseLeft + preview.currentWidth,
      bottom: preview.baseTop + preview.currentHeight
    };
    const contact = liveImageGroupRoundedRectContact(pointerCenter, body, preview.motherRadius);
    const gap = contact.distance - preview.incomingRadius;
    preview.targetStrength = !preview.releasing && gap < IMAGE_GROUP_PROXIMITY_CONTACT_PX
      ? liveImageGroupSmoothstep(1 - gap / IMAGE_GROUP_PROXIMITY_CONTACT_PX)
      : 0;
    // Preserve the approach direction once inside; nearest-edge changes must
    // not flip the whole-image smear as the pointer crosses the board centre.
    if (preview.targetStrength > 0.01 && contact.distance >= 0) preview.lastContact = { ...contact };
    preview.insertionIndex = liveImageGroupSlotIndex(preview, pointerCenter);
    preview.dropActive = !preview.releasing && gap <= IMAGE_GROUP_PROXIMITY_DROP_PX;
    preview.overlay.classList.toggle('is-drop-active', preview.dropActive);
    preview.targetWidth = preview.dropActive ? preview.finalWidth : preview.baseWidth;
    preview.targetHeight = preview.dropActive ? preview.finalHeight : preview.baseHeight;
    if (preview.reducedMotion) {
      preview.currentStrength = preview.targetStrength;
      preview.releaseStrength = preview.targetStrength;
      preview.currentWidth = preview.targetWidth;
      preview.currentHeight = preview.targetHeight;
    } else if (immediate) {
      preview.currentWidth += (preview.targetWidth - preview.currentWidth) * 0.28;
      if (Math.abs(preview.targetWidth - preview.currentWidth) < 0.35) preview.currentWidth = preview.targetWidth;
      preview.currentHeight += (preview.targetHeight - preview.currentHeight) * 0.28;
      if (Math.abs(preview.targetHeight - preview.currentHeight) < 0.35) preview.currentHeight = preview.targetHeight;
    }

    const open = preview.dropActive;
    preview.targetItems.forEach((item, index) => {
      const slot = index + (open && index >= preview.insertionIndex ? 1 : 0);
      const slotPosition = liveImageGroupSlotPosition(preview, slot);
      item.chip.style.left = `${slotPosition.left}px`;
      item.chip.style.top = `${slotPosition.top}px`;
      item.chip.style.width = `${preview.thumbSize}px`;
      item.chip.style.height = `${preview.thumbSize}px`;
      setImageGroupPreviewChipUnit(item.chip, preview.thumbSize);
      const startScale = item.startSide / Math.max(1, preview.thumbSize);
      item.chip.style.transform = `scale(${startScale + (1 - startScale) * intro})`;
      item.badge.textContent = String(slot + 1);
    });

    const slotCenter = liveImageGroupSlotCenter(preview, preview.insertionIndex);
    let incomingCenter;
    let incomingSize;
    if (preview.committing) {
      const progress = liveImageGroupEase(preview.commitProgress || 0);
      incomingCenter = {
        x: preview.dropStartCenter.x + (slotCenter.x - preview.dropStartCenter.x) * progress,
        y: preview.dropStartCenter.y + (slotCenter.y - preview.dropStartCenter.y) * progress
      };
      incomingSize = preview.dropStartSize + (preview.thumbSize - preview.dropStartSize) * progress;
    } else {
      incomingCenter = pointerCenter;
      incomingSize = preview.introStartSide + (preview.thumbSize - preview.introStartSide) * intro;
    }
    preview.incomingCenter = incomingCenter;
    preview.incomingSize = incomingSize;
    preview.incoming.chip.style.left = `${incomingCenter.x - incomingSize / 2}px`;
    preview.incoming.chip.style.top = `${incomingCenter.y - incomingSize / 2}px`;
    preview.incoming.chip.style.width = `${incomingSize}px`;
    preview.incoming.chip.style.height = `${incomingSize}px`;
    setImageGroupPreviewChipUnit(preview.incoming.chip, incomingSize);
    preview.incoming.badge.textContent = String(preview.insertionIndex + 1);

    const coverage = liveImageGroupLiquidCoverage(incomingCenter, {
      left: preview.baseLeft, top: preview.baseTop,
      width: preview.currentWidth, height: preview.currentHeight
    }, incomingSize / 2, preview.motherRadius);
    preview.liquidCoverage = preview.committing ? Math.max(preview.dropLiquidCoverage || 0, coverage) : coverage;
    // The bridge/mother may settle during drop, but the PHOTO remains liquid
    // for every visible drop frame. Clarity belongs to the completed node.
    preview.liquidStrength = preview.reducedMotion ? 0
      : preview.committing ? preview.dropLiquidStrength
      : preview.releasing ? preview.currentStrength
      : Math.max(preview.currentStrength, preview.liquidCoverage);
    const strength = preview.currentStrength * (1 - preview.liquidCoverage);
    const renderContact = preview.lastContact || contact;
    const normal = renderContact.normal || { x: 1, y: 0 };
    const sourceSurface = {
      x: incomingCenter.x - normal.x * Math.max(1, incomingSize / 2),
      y: incomingCenter.y - normal.y * Math.max(1, incomingSize / 2)
    };
    const targetSurface = renderContact.surface;
    const px = -normal.y;
    const py = normal.x;
    const half = Math.max(1, 1.5 + strength * 7.5);
    const sourceHalf = Math.max(1, 1 + strength * 5.5);
    const midX = (sourceSurface.x + targetSurface.x) / 2;
    const midY = (sourceSurface.y + targetSurface.y) / 2;
    const neck = `M ${targetSurface.x + px * half} ${targetSurface.y + py * half}`
      + ` C ${midX + px * half * 0.7} ${midY + py * half * 0.7}, ${midX + px * sourceHalf * 0.7} ${midY + py * sourceHalf * 0.7}, ${sourceSurface.x + px * sourceHalf} ${sourceSurface.y + py * sourceHalf}`
      + ` L ${sourceSurface.x - px * sourceHalf} ${sourceSurface.y - py * sourceHalf}`
      + ` C ${midX - px * sourceHalf * 0.7} ${midY - py * sourceHalf * 0.7}, ${midX - px * half * 0.7} ${midY - py * half * 0.7}, ${targetSurface.x - px * half} ${targetSurface.y - py * half} Z`;
    preview.bridge.setAttribute('d', neck);
    preview.bridgeHalo.setAttribute('d', neck);
    preview.bridge.style.opacity = String(clamp(strength * 1.12, 0, 1));
    preview.bridgeHalo.style.opacity = String(clamp(strength * 0.34, 0, 0.34));
    preview.contactBlob.setAttribute('cx', String(targetSurface.x));
    preview.contactBlob.setAttribute('cy', String(targetSurface.y));
    preview.contactBlob.setAttribute('r', String(Math.max(1, 3 + strength * 10)));
    preview.contactBlob.style.opacity = String(clamp(strength * 0.9, 0, 0.9));
    // Procedural flow must run in thumbnail-local coordinates for both HTML
    // and SVG. A global SVG cx/cy would sample a different noise phase and
    // leave a mismatched ring/shadow even if the same filter ID were used.
    preview.incomingShape.setAttribute('transform', `translate(${incomingCenter.x - incomingSize / 2} ${incomingCenter.y - incomingSize / 2})`);
    preview.incomingShape.setAttribute('cx', String(incomingSize / 2));
    preview.incomingShape.setAttribute('cy', String(incomingSize / 2));
    // Match the HTML image's border-box alpha exactly, rather than keeping an
    // oversized, undeformed circle visible behind it.
    preview.incomingShape.setAttribute('r', String(Math.max(1, incomingSize / 2)));

    const deformation = preview.reducedMotion ? 0 : strength;
    renderLiveImageGroupLiquify(preview.liquify, normal, preview.liquidStrength, incomingSize, preview.liquidCoverage, Math.max(0, now - preview.introStartedAt));
    preview.overlay.dataset.contactAxis = Math.abs(normal.x) > Math.abs(normal.y) ? 'x' : 'y';
    preview.overlay.dataset.contactSide = normal.x < -0.35 ? 'left' : normal.x > 0.35 ? 'right' : normal.y < 0 ? 'top' : 'bottom';
    preview.identity.style.left = `${preview.baseLeft + preview.identityInset}px`;
    preview.identity.style.top = `${preview.baseTop + preview.identityTop}px`;
    preview.identity.querySelector('span').textContent = `${preview.targetItems.length + (preview.dropActive ? 1 : 0)} 张`;
    preview.base.setAttribute('d', liveImageGroupMotherPath({
      left: preview.baseLeft, top: preview.baseTop,
      width: preview.currentWidth, height: preview.currentHeight
    }, preview.motherRadius, renderContact, deformation, incomingSize));
  }

    function startLiveImageGroupPreviewFrame(preview) {
    if (!preview?.active || preview.raf) return;
    if (preview.reducedMotion) {
      renderLiveImageGroupPreview(preview, performance.now(), true);
      return;
    }
    preview.lastFrame = performance.now();
    const tick = now => {
      preview.raf = 0;
      if (!preview.active) return;
      const dt = Math.max(0.001, Math.min(0.05, (now - preview.lastFrame) / 1000));
      preview.lastFrame = now;
      if (!preview.committing) {
        const target = preview.targetStrength || 0;
        if (target >= preview.currentStrength) {
          preview.currentStrength += (target - preview.currentStrength) * Math.min(1, dt * 18);
          preview.releaseStartedAt = 0;
        } else if (target > 0.01) {
          preview.currentStrength += (target - preview.currentStrength) * Math.min(1, dt * 8);
          preview.releaseStartedAt = 0;
        } else if (preview.currentStrength > 0.001) {
          if (!preview.releaseStartedAt) {
            preview.releaseStartedAt = now;
            preview.releaseStrength = preview.currentStrength;
          }
          const releaseProgress = clamp((now - preview.releaseStartedAt) / IMAGE_GROUP_PROXIMITY_RELEASE_MS, 0, 1);
          preview.currentStrength = preview.releaseStrength * Math.pow(1 - releaseProgress, 2);
        }
        if (target > 0.01) preview.releaseStrength = Math.max(preview.releaseStrength, preview.currentStrength, target);
      }
      const widthDelta = preview.targetWidth - preview.currentWidth;
      preview.currentWidth += widthDelta * Math.min(1, dt * 12);
      if (Math.abs(widthDelta) < 0.2) preview.currentWidth = preview.targetWidth;
      const heightDelta = preview.targetHeight - preview.currentHeight;
      preview.currentHeight += heightDelta * Math.min(1, dt * 12);
      if (Math.abs(heightDelta) < 0.2) preview.currentHeight = preview.targetHeight;
      renderLiveImageGroupPreview(preview, now, false);
      const introActive = !preview.committing && now - preview.introStartedAt < preview.introDuration + 20;
      const strengthActive = Math.abs((preview.targetStrength || 0) - preview.currentStrength) >= 0.002
        || (preview.targetStrength <= 0.01 && preview.currentStrength >= 0.001);
      const sizeActive = Math.abs(preview.targetWidth - preview.currentWidth) >= 0.2
        || Math.abs(preview.targetHeight - preview.currentHeight) >= 0.2;
      if (introActive || strengthActive || sizeActive || preview.releasing || preview.liquify.animated) {
        preview.raf = requestAnimationFrame(tick);
      }
    };
    preview.raf = requestAnimationFrame(tick);
  }

    function createImageGroupProximityPreview(sourceNodeId, targetNodeId, interaction) {
    const entries = imageGroupProximityPreviewEntries(sourceNodeId, targetNodeId);
    if (entries.length < 2) return null;
    const sourceRect = getNodeElement(sourceNodeId)?.getBoundingClientRect?.();
    const targetElement = getNodeElement(targetNodeId);
    const targetRect = targetElement?.getBoundingClientRect?.();
    if (!sourceRect || !targetRect) return null;
    const targetNode = DesktopState.state.canvas.nodes[targetNodeId];
    const targetBodyRect = targetNode?.type === 'image_group'
      ? targetElement.querySelector('[data-image-group-liquid-base]')?.getBoundingClientRect?.()
      : null;
    const incomingEntry = entries.find(entry => entry.incoming);
    const targetEntries = entries.filter(entry => !entry.incoming);
    if (!incomingEntry || !targetEntries.length) return null;
    const canvasScale = Math.max(0.01, Number(DesktopState.state.canvas.scale) || 1);
    const thumbSize = targetBodyRect ? Math.max(24, targetEntries[0].rect.width) : IMAGE_GROUP_THUMB_PX * canvasScale;
    const step = targetBodyRect && targetEntries.length > 1
      ? Math.max(thumbSize * 0.58, Math.abs(targetEntries[1].rect.left - targetEntries[0].rect.left))
      : IMAGE_GROUP_THUMB_STEP_PX * canvasScale;
    const rowStep = targetBodyRect && targetEntries.length > IMAGE_GROUP_MAX_COLUMNS
      ? Math.max(thumbSize, Math.abs(targetEntries[IMAGE_GROUP_MAX_COLUMNS].rect.top - targetEntries[0].rect.top))
      : IMAGE_GROUP_ROW_STEP_PX * canvasScale;
    const thumbStart = targetBodyRect
      ? Math.max(8, targetEntries[0].rect.left - targetBodyRect.left)
      : IMAGE_GROUP_IDENTITY_WIDTH_PX * canvasScale;
    const rowInset = targetBodyRect
      ? Math.max(0, targetEntries[0].rect.top - targetBodyRect.top)
      : (IMAGE_GROUP_MOTHER_HEIGHT_PX - IMAGE_GROUP_THUMB_PX) / 2 * canvasScale;
    const motherHeight = targetBodyRect?.height || imageGroupMotherHeight(targetEntries.length) * canvasScale;
    const finalHeight = imageGroupMotherHeight(targetEntries.length + 1) * canvasScale;
    const motherRadius = IMAGE_GROUP_MOTHER_RADIUS_PX * canvasScale;
    const baseWidth = targetBodyRect?.width || naturalImageGroupNodeWidth(targetEntries.length) * canvasScale;
    const finalWidth = naturalImageGroupNodeWidth(targetEntries.length + 1) * canvasScale;
    const rawAnchor = targetBodyRect
      ? { x: targetBodyRect.left + targetBodyRect.width / 2, y: targetBodyRect.top + targetBodyRect.height / 2 }
      : mergeAnchorBetweenRects(sourceRect, targetRect);
    const baseLeft = targetBodyRect
      ? targetBodyRect.left
      : clamp(rawAnchor.x - baseWidth / 2, 18, Math.max(18, window.innerWidth - baseWidth - 18));
    const baseTop = targetBodyRect
      ? targetBodyRect.top
      : clamp(rawAnchor.y - motherHeight / 2, 18, Math.max(18, window.innerHeight - motherHeight - 18));
    const baseRect = { left: baseLeft, top: baseTop, width: baseWidth, height: motherHeight };
    const sourceCenter = {
      x: sourceRect.left + sourceRect.width / 2,
      y: sourceRect.top + sourceRect.height / 2
    };
    const targetCenter = {
      x: targetRect.left + targetRect.width / 2,
      y: targetRect.top + targetRect.height / 2
    };
    const pointerAtReady = {
      x: Number.isFinite(interaction?.lastClientX) ? interaction.lastClientX : sourceCenter.x,
      y: Number.isFinite(interaction?.lastClientY) ? interaction.lastClientY : sourceCenter.y
    };
    const initialContact = liveImageGroupApproachContact(pointerAtReady, targetCenter, baseRect, motherRadius);
    const incomingRadius = thumbSize / 2 + imageGroupUiSize(4);
    const introStart = cappedTransitionRect(sourceRect, IMAGE_GROUP_TRANSITION_THUMB_PX);
    const transitionId = `desk-image-group-proximity-gooey-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    const overlay = document.createElement('div');
    overlay.className = 'desk-image-group-transition desk-image-group-transition--proximity';
    const liquidSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    liquidSvg.classList.add('desk-image-group-transition__liquid-svg');
    liquidSvg.setAttribute('viewBox', `0 0 ${window.innerWidth} ${window.innerHeight}`);
    liquidSvg.setAttribute('preserveAspectRatio', 'none');
    liquidSvg.innerHTML = `<defs><filter id="${transitionId}" filterUnits="userSpaceOnUse" x="-80" y="-80" width="${window.innerWidth + 160}" height="${window.innerHeight + 160}" color-interpolation-filters="sRGB">${imageGroupGooeyFilterPrimitivesHtml()}</filter></defs><g class="desk-image-group-transition__liquid-surface" filter="url(#${transitionId})"></g>`;
    const liquidSurface = liquidSvg.querySelector('.desk-image-group-transition__liquid-surface');
    const base = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    base.classList.add('desk-image-group-transition__mother-shape');
    liquidSurface.appendChild(base);
    const bridgeHalo = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    bridgeHalo.classList.add('desk-image-group-transition__bridge-halo');
    const bridge = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    bridge.classList.add('desk-image-group-transition__bridge');
    const contactBlob = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    contactBlob.classList.add('desk-image-group-transition__contact');
    const incomingShape = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    incomingShape.classList.add('desk-image-group-transition__incoming-shape');
    liquidSurface.append(bridgeHalo, bridge, contactBlob, incomingShape);
    const identity = document.createElement('div');
    identity.className = 'desk-image-group-transition__identity';
    const identityScale = clamp(canvasScale, 0.35, 1.45);
    identity.style.setProperty('--desk-image-group-transition-scale', String(identityScale));
    identity.innerHTML = `<strong>图片组</strong><span>${targetEntries.length} 张</span>`;
    const imageLayer = document.createElement('div');
    imageLayer.className = 'desk-image-group-transition__images';
    overlay.append(liquidSvg, identity, imageLayer);
    document.body.appendChild(overlay);
    const targetItems = targetEntries.map(entry => {
      const item = liveImageGroupChip(entry, imageLayer);
      item.startSide = Math.max(thumbSize, cappedTransitionRect(entry.rect, IMAGE_GROUP_TRANSITION_THUMB_PX).width);
      setImageGroupPreviewChipUnit(item.chip, thumbSize);
      return item;
    });
    const incoming = liveImageGroupChip(incomingEntry, imageLayer, true);
    const liquify = createLiveImageGroupLiquify(liquidSvg.querySelector('defs'), `${transitionId}-texture`, incoming.image, incomingShape);
    const preview = {
      overlay, base, bridge, bridgeHalo, contactBlob, incomingShape, identity,
      targetItems, incoming, liquify, targetNodeId, sourceNodeId,
      baseLeft, baseTop, baseWidth, baseHeight: motherHeight,
      currentWidth: baseWidth, targetWidth: baseWidth, finalWidth,
      currentHeight: motherHeight, targetHeight: motherHeight, finalHeight,
      motherHeight, motherRadius, thumbSize, thumbStart, step, rowInset, rowStep,
      identityInset: imageGroupUiSize(24) * canvasScale,
      identityTop: imageGroupUiSize(20) * canvasScale,
      incomingRadius, introStartSide: introStart.width,
      pointerX: pointerAtReady.x,
      pointerY: pointerAtReady.y,
      introStartedAt: performance.now(), introDuration: 250,
      currentStrength: 0, releaseStrength: 0, releaseStartedAt: 0, targetStrength: 0,
      insertionIndex: targetItems.length, dropActive: false, lastContact: initialContact,
      active: true, raf: 0, committing: false, commitProgress: 0, releasing: false,
      reducedMotion: prefersReducedMotion(),
      incomingCenter: pointerAtReady, incomingSize: introStart.width, dropStartSize: introStart.width,
      positionWorld: null
    };
    const position = screenToWorld(baseLeft, baseTop - IMAGE_GROUP_MOTHER_TOP_PX * canvasScale);
    preview.positionWorld = { x: position.x, y: position.y };
    renderLiveImageGroupPreview(preview, performance.now(), true);
    startLiveImageGroupPreviewFrame(preview);
    return preview;
  }

    function clearImageGroupProximity(interaction, options = {}) {
    const proximity = interaction?.imageGroupProximity;
    if (!proximity) return;
    window.clearTimeout(proximity.timer);
    window.clearTimeout(proximity.releaseTimer);
    proximity.indicator?.remove();
    if (proximity.preview) {
      proximity.preview.active = false;
      if (proximity.preview.raf) cancelAnimationFrame(proximity.preview.raf);
      proximity.preview.raf = 0;
      if (!options.preserveOverlay) proximity.preview.overlay?.remove();
    }
    getNodeElement(interaction.nodeId)?.classList.remove('is-image-group-proximity-source', 'is-image-group-proximity-ready');
    getNodeElement(proximity.targetNodeId)?.classList.remove('is-image-group-proximity-target', 'is-image-group-proximity-ready');
    interaction.imageGroupProximity = null;
  }

    function releaseImageGroupProximity(interaction) {
    const proximity = interaction?.imageGroupProximity;
    const preview = proximity?.preview;
    if (!proximity?.ready || !preview || proximity.releasing) return;
    if (preview.reducedMotion) {
      clearImageGroupProximity(interaction);
      return;
    }
    proximity.releasing = true;
    preview.releasing = true;
    preview.dropActive = false;
    preview.targetStrength = 0;
    preview.targetWidth = preview.baseWidth;
    preview.targetHeight = preview.baseHeight;
    preview.releaseStrength = preview.currentStrength;
    preview.releaseStartedAt = 0;
    preview.overlay?.classList.remove('is-drop-active');
    preview.overlay?.setAttribute('data-releasing', 'true');
    startLiveImageGroupPreviewFrame(preview);
    proximity.releaseTimer = window.setTimeout(() => {
      if (activeInteractionRef.current !== interaction || interaction.imageGroupProximity !== proximity) return;
      clearImageGroupProximity(interaction);
    }, IMAGE_GROUP_PROXIMITY_RELEASE_MS + 45);
  }

    function beginImageGroupProximity(interaction, candidate) {
    clearImageGroupProximity(interaction);
    const sourceElement = getNodeElement(interaction.nodeId);
    const targetElement = getNodeElement(candidate.nodeId);
    if (!sourceElement || !targetElement) return;
    sourceElement.classList.add('is-image-group-proximity-source');
    targetElement.classList.add('is-image-group-proximity-target');
    const proximity = {
      targetNodeId: candidate.nodeId,
      indicator: createImageGroupDwellIndicator(candidate.sourceRect, candidate.targetRect),
      timer: 0,
      releaseTimer: 0,
      ready: false,
      releasing: false,
      preview: null
    };
    interaction.imageGroupProximity = proximity;
    proximity.timer = window.setTimeout(() => {
      if (activeInteractionRef.current !== interaction || interaction.imageGroupProximity !== proximity) return;
      const current = findImageGroupProximityCandidate(interaction, IMAGE_GROUP_PROXIMITY_RELEASE_PX);
      if (current?.nodeId !== proximity.targetNodeId) {
        clearImageGroupProximity(interaction);
        return;
      }
      proximity.ready = true;
      proximity.readyClientX = interaction.lastClientX;
      proximity.readyClientY = interaction.lastClientY;
      proximity.indicator?.remove();
      proximity.indicator = null;
      hideSmartGuides();
      sourceElement.classList.add('is-image-group-proximity-ready');
      targetElement.classList.add('is-image-group-proximity-ready');
      proximity.preview = createImageGroupProximityPreview(interaction.nodeId, proximity.targetNodeId, interaction);
      if (!proximity.preview) clearImageGroupProximity(interaction);
    }, IMAGE_GROUP_PROXIMITY_DWELL_MS);
  }

    function updateImageGroupProximity(interaction) {
    const existing = interaction?.imageGroupProximity;
    if (existing?.ready) {
      const current = findImageGroupProximityCandidate(interaction, IMAGE_GROUP_PROXIMITY_RELEASE_PX);
      if (!current || current.nodeId !== existing.targetNodeId) {
        releaseImageGroupProximity(interaction);
        return;
      }
      if (existing.releasing) {
        existing.releasing = false;
        window.clearTimeout(existing.releaseTimer);
        existing.releaseTimer = 0;
        existing.preview.releasing = false;
        existing.preview.overlay?.removeAttribute('data-releasing');
      }
      if (existing.preview) {
        existing.preview.pointerX = interaction.lastClientX;
        existing.preview.pointerY = interaction.lastClientY;
        renderLiveImageGroupPreview(existing.preview, performance.now(), true);
        startLiveImageGroupPreviewFrame(existing.preview);
      }
      return;
    }
    const threshold = existing ? IMAGE_GROUP_PROXIMITY_RELEASE_PX : IMAGE_GROUP_PROXIMITY_DISTANCE_PX;
    const candidate = findImageGroupProximityCandidate(interaction, threshold);
    if (!candidate) {
      clearImageGroupProximity(interaction);
      return;
    }
    if (existing?.targetNodeId === candidate.nodeId) {
      positionImageGroupDwellIndicator(existing.indicator, candidate.sourceRect, candidate.targetRect);
      return;
    }
    beginImageGroupProximity(interaction, candidate);
  }

    function animateImageGroupProximityDrop(interaction) {
    const proximity = interaction?.imageGroupProximity;
    const preview = proximity?.preview;
    if (!proximity?.ready || !preview?.dropActive || preview.committing) return false;
    preview.committing = true;
    if (preview.raf) cancelAnimationFrame(preview.raf);
    preview.raf = 0;
    preview.dropStartCenter = { ...preview.incomingCenter };
    preview.dropStartSize = preview.incomingSize;
    preview.dropStartStrength = preview.currentStrength;
    preview.dropLiquidStrength = Math.max(preview.currentStrength, preview.targetStrength || 0, preview.liquidStrength || 0);
    preview.dropLiquidCoverage = preview.liquidCoverage || 0;
    preview.commitProgress = 0;
    if (preview.reducedMotion) {
      preview.commitProgress = 1;
      commitImageGroupProximity(interaction);
      return true;
    }
    const started = performance.now();
    const tick = now => {
      const progress = clamp((now - started) / IMAGE_GROUP_PROXIMITY_DROP_MS, 0, 1);
      preview.commitProgress = progress;
      preview.currentStrength = preview.dropStartStrength * (1 - liveImageGroupSmoothstep(progress));
      preview.currentWidth += (preview.finalWidth - preview.currentWidth) * Math.min(1, 0.12 + progress * 0.18);
      preview.currentHeight += (preview.finalHeight - preview.currentHeight) * Math.min(1, 0.12 + progress * 0.18);
      renderLiveImageGroupPreview(preview, now, false);
      if (progress < 1) {
        preview.raf = requestAnimationFrame(tick);
        return;
      }
      preview.raf = 0;
      commitImageGroupProximity(interaction);
    };
    preview.raf = requestAnimationFrame(tick);
    return true;
  }

    function commitImageGroupProximity(interaction) {
    const proximity = interaction?.imageGroupProximity;
    const preview = proximity?.preview;
    if (!proximity?.ready || !preview) return '';
    const sourceNode = DesktopState.state.canvas.nodes[interaction.nodeId];
    const targetNode = DesktopState.state.canvas.nodes[proximity.targetNodeId];
    const insertIndex = preview.insertionIndex;
    const positionWorld = preview.positionWorld;
    const fakeInteraction = { nodeId: interaction.nodeId, imageGroupProximity: proximity };
    clearImageGroupProximity(fakeInteraction, { preserveOverlay: true });
    let groupId = '';
    if (sourceNode?.type === 'image' && targetNode?.type === 'image') {
      const targetIds = preview.targetItems.map(item => item.sourceNodeId);
      const orderedNodeIds = [...targetIds.slice(0, insertIndex), sourceNode.id, ...targetIds.slice(insertIndex)];
      groupId = createImageGroupFromNodes([targetNode, sourceNode], {
        orderedNodeIds, positionWorld, skipTransition: true, quiet: true
      });
    } else if (sourceNode?.type === 'image' && targetNode?.type === 'image_group') {
      groupId = appendImageNodeToGroup(sourceNode.id, targetNode.id, {
        insertIndex, positionWorld, preserveLeft: true, skipTransition: true, quiet: true
      });
    }
    preview.overlay?.remove();
    if (groupId) {
      const count = DesktopState.state.canvas.nodes[groupId]?.items?.length || 0;
      DesktopResults.showTransientMessage(`已通过拖拽融合为图片组，当前共 ${count} 张。`);
    }
    return groupId;
  }

    function activateImageGroupReferenceItem(activeItem) {
    if (!activeItem) return;
    const focused = document.activeElement;
    let shouldCloseSelect = false;
    document.querySelectorAll('.desk-image-group__item').forEach(item => {
      if (item === activeItem) return;
      if (item.querySelector('.desk-select-shell.is-open')) shouldCloseSelect = true;
      if (focused && item.contains(focused)) focused.blur?.();
    });
    if (shouldCloseSelect) window.DesktopSelect?.closeAll?.();
  }

    return Object.freeze({
      captureImageNodeTransitionSources,
      orderTransitionSourcesForNodes,
      captureImageGroupItemRects,
      animateImageGroupItemFlip,
      imageGroupSortTransform,
      beginImageGroupItemSort,
      renderImageGroupItemSortFrame,
      moveImageGroupItemSort,
      clearImageGroupItemSortState,
      returnImageGroupItemSort,
      endImageGroupItemSort,
      ensureGlobalImageGroupGooeyFilter,
      cappedTransitionRect,
      animateImageTransition,
      animateImagesIntoGroup,
      animateImagesOutOfGroup,
      rectGapDistance,
      mergeAnchorBetweenRects,
      eligibleImageGroupProximityTarget,
      findImageGroupProximityCandidate,
      positionImageGroupDwellIndicator,
      createImageGroupDwellIndicator,
      imageGroupProximityPreviewEntries,
      setImageGroupPreviewChipUnit,
      liveImageGroupSmoothstep,
      liveImageGroupEase,
      liveImageGroupRoundedRectContact,
      liveImageGroupApproachContact,
      liveImageGroupChip,
      createLiveImageGroupLiquify,
      renderLiveImageGroupLiquify,
      liveImageGroupLiquidCoverage,
      liveImageGroupMotherPath,
      liveImageGroupSlotPosition,
      liveImageGroupSlotIndex,
      liveImageGroupSlotCenter,
      renderLiveImageGroupPreview,
      startLiveImageGroupPreviewFrame,
      createImageGroupProximityPreview,
      clearImageGroupProximity,
      releaseImageGroupProximity,
      beginImageGroupProximity,
      updateImageGroupProximity,
      animateImageGroupProximityDrop,
      commitImageGroupProximity,
      activateImageGroupReferenceItem,
    });
  }

  window.DesktopCanvasImageGroupInteraction = Object.freeze({ create });
})();
