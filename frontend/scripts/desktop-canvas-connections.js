// Connection rules, menus, SVG links and connection drag lifecycle. Host dispatches pointer events; port animation is a separate controller.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  const CONNECTION_SNAP_RADIUS_PX = 8;
  const CONNECTION_PROXIMITY_RADIUS_PX = 20;
  // One compatibility contract for menus, highlighting, magnetic capture and
  // final edge creation. Legacy output nodes remain valid even without a menu item.
  const CONNECTION_TARGET_TYPES = Object.freeze({
    __proto__: null,
    input: Object.freeze(['image', 'file_output', 'upscale', 'output']),
    comfy: Object.freeze(['image', 'upscale']),
    video_inference: Object.freeze(['video']),
    video: Object.freeze(['video_inference']),
    // The independent music domain extends audio targets; image/video accept none.
    audio: Object.freeze([]),
    image_group: Object.freeze(['input', 'comfy']),
    output: Object.freeze(['image']),
    image: Object.freeze(['input', 'comfy', 'video_inference', 'layout', 'pose', 'upscale']),
    upscale: Object.freeze(['image']),
    layout: Object.freeze(['input', 'comfy', 'video_inference', 'upscale']),
    pose: Object.freeze(['input', 'comfy', 'video_inference', 'upscale']),
    text: Object.freeze(['input', 'comfy', 'video_inference'])
  });

  function create({
    LINK_VIEWBOX,
    NODE_MENU_ITEMS,
    domainConnections,
    ORDINARY_MENU_CLOSE_FALLBACK_MS,
    activeInteractionRef,
    addNodeFromMenu,
    assignImageOutputSlots,
    clamp,
    clearFloatingConnectionPort,
    clearConnectionProximity,
    contextMenuConnectionSourceAnchorRef,
    contextMenuConnectionSourceIdRef,
    contextMenuConnectionSourceSideRef,
    contextMenuElRef,
    dominantPortSide,
    edgeMenuElRef,
    els,
    ensureTextNodeImageReferenceConnections,
    escapeHtml,
    focusCanvasViewport,
    getConnectionPortAnchor,
    getNodeElement,
    getNodeState,
    getNodeVisualOffset,
    playConnectionCommit,
    getViewportCenterWorldPoint,
    holdFloatingSwell,
    hoveredEdgeIdRef,
    makeClassicCurvePath,
    makeSmoothStepPath,
    nodeMenuButtonHtml,
    normalizePortSide,
    oppositePortSide,
    pendingConnectionDropPointRef,
    refreshComfyNode,
    refreshImageReferenceTokens,
    refreshPoseNode,
    refreshUpscaleNodeMode,
    refreshVideoInferenceNode,
    refreshVideoNode,
    releaseFloatingSwell,
    renderMiniMap,
    screenToWorld,
    selectedEdgeIdRef,
    setImageNodeFromResult,
    setSelectedNodes,
    syncNodeEdgeStroke,
    updateLayoutInputCount,
    updateConnectionProximity,
    updateUpscaleInputCount,
    videoInputRoleForSource,
  }) {
    let contextMenuPoint = null;
    let contextMenuCloseTimer = 0;
    let contextMenuConnectionEndPoint = null;
    let edgeMenuAnchorWorld = null;
    let connectionPreviewFrameId = 0;
    let pendingConnectionPreview = null;
    let connectionPointerClient = null;
    let connectionSnapTarget = null;
    let connectionApproachPoint = null;
    const edgeVisuals = new Map();
    const nodeEdgeVisuals = new Map();
    const targetsFor = type => [...(CONNECTION_TARGET_TYPES[type] || []), ...(domainConnections?.targets[type] || [])];

    function filterContextMenuItems(menu, query = '') {
    const normalized = String(query || '').trim().toLowerCase();
    let visibleCount = 0;
    menu?.querySelectorAll?.('[data-add-node]').forEach(button => {
      const visible = !normalized || String(button.dataset.nodeMenuSearch || '').includes(normalized);
      button.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    const empty = menu?.querySelector?.('[data-node-context-empty]');
    if (empty) empty.hidden = visibleCount > 0;
    return visibleCount;
  }

    function getConnectableNodeMenuItems(fromNodeId) {
    const fromType = DesktopState.state.canvas.nodes[fromNodeId]?.type;
    const targetTypes = targetsFor(fromType);
    return NODE_MENU_ITEMS.filter(item => targetTypes.includes(item.type));
  }

    function canConnectNodes(fromNodeId, toNodeId) {
    if (!fromNodeId || !toNodeId || fromNodeId === toNodeId) return false;
    const from = getNodeState(fromNodeId);
    const to = getNodeState(toNodeId);
    return Boolean(from && to && targetsFor(from.type).includes(to.type));
  }

    function renderContextMenuItems(items, title = '') {
    const menu = ensureContextMenu();
    const safeItems = Array.isArray(items) ? items : NODE_MENU_ITEMS;
    const isConnectionMenu = Boolean(contextMenuConnectionSourceIdRef.current);
    menu.classList.toggle('is-connection-menu', isConnectionMenu);
    menu.innerHTML = `
      <div class="desk-node-context-menu__cap" aria-hidden="true">
        <strong>${escapeHtml(title || '添加节点')}</strong>
        ${isConnectionMenu ? '<span>自动连接</span>' : ''}
      </div>
      <label class="desk-node-context-menu__search">
        <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="4.75"></circle><path d="m12 12 4 4"></path></svg>
        <input type="search" autocomplete="off" spellcheck="false" placeholder="搜索节点…" aria-label="搜索可添加节点" data-node-context-search>
      </label>
      <div class="desk-node-context-menu__items" data-node-context-items>${safeItems.map(nodeMenuButtonHtml).join('')}</div>
      <div class="desk-node-context-menu__empty" data-node-context-empty hidden>没有匹配节点</div>
    `;
    menu.querySelectorAll('[data-add-node]').forEach(button => {
      button.draggable = false;
    });
    const search = menu.querySelector('[data-node-context-search]');
    search?.addEventListener('input', () => filterContextMenuItems(menu, search.value));
  }

    function ensureContextMenu() {
    if (contextMenuElRef.current) return contextMenuElRef.current;
    contextMenuElRef.current = document.createElement('div');
    contextMenuElRef.current.id = 'deskNodeContextMenu';
    contextMenuElRef.current.className = 'desk-node-palette desk-node-context-menu desk-glass';
    contextMenuElRef.current.setAttribute('aria-label', '添加节点');
    document.body.appendChild(contextMenuElRef.current);
    renderContextMenuItems(NODE_MENU_ITEMS);
    contextMenuElRef.current.addEventListener('click', event => {
      const button = event.target.closest('[data-add-node]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const worldPoint = contextMenuPoint || getViewportCenterWorldPoint();
      const connectionSourceId = contextMenuConnectionSourceIdRef.current;
      hideContextMenu({ updateLinks: false });
      const nodeId = addNodeFromMenu(button.dataset.addNode || 'input', worldPoint);
      if (connectionSourceId) connectNodes(connectionSourceId, nodeId);
    });
    contextMenuElRef.current.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        hideContextMenu();
        focusCanvasViewport();
        return;
      }
      const buttons = Array.from(contextMenuElRef.current.querySelectorAll('[data-add-node]')).filter(button => !button.hidden);
      if (!buttons.length) return;
      if (event.key === 'Enter' && event.target.matches('[data-node-context-search]')) {
        event.preventDefault();
        buttons[0].click();
        return;
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      event.preventDefault();
      const currentIndex = buttons.indexOf(document.activeElement);
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      const nextIndex = currentIndex < 0
        ? (direction > 0 ? 0 : buttons.length - 1)
        : (currentIndex + direction + buttons.length) % buttons.length;
      buttons[nextIndex].focus();
    });
    contextMenuElRef.current.addEventListener('transitionend', event => {
      if (event.target !== contextMenuElRef.current || event.propertyName !== 'opacity') return;
      if (!contextMenuElRef.current.classList.contains('is-open')) finishContextMenuClose();
    });
    return contextMenuElRef.current;
  }

    function finishContextMenuClose() {
    if (!contextMenuElRef.current || contextMenuElRef.current.classList.contains('is-open')) return;
    if (contextMenuCloseTimer) {
      window.clearTimeout(contextMenuCloseTimer);
      contextMenuCloseTimer = 0;
    }
    contextMenuElRef.current.classList.remove('is-closing');
  }

    function hideContextMenu(options = {}) {
    const hadPendingConnection = Boolean(contextMenuConnectionSourceIdRef.current && contextMenuPoint);
    const pendingSourceNode = contextMenuConnectionSourceIdRef.current
      ? getNodeElement(contextMenuConnectionSourceIdRef.current)
      : null;
    if (contextMenuElRef.current?.classList.contains('is-open')) {
      contextMenuElRef.current.classList.remove('is-open');
      contextMenuElRef.current.classList.add('is-closing');
      if (contextMenuCloseTimer) window.clearTimeout(contextMenuCloseTimer);
      contextMenuCloseTimer = window.setTimeout(finishContextMenuClose, ORDINARY_MENU_CLOSE_FALLBACK_MS);
    }
    document.querySelectorAll('.desk-port.is-pending').forEach(item => item.classList.remove('is-pending'));
    releaseFloatingSwell(pendingSourceNode);
    contextMenuPoint = null;
    contextMenuConnectionSourceIdRef.current = '';
    contextMenuConnectionSourceSideRef.current = 'right';
    contextMenuConnectionSourceAnchorRef.current = null;
    contextMenuConnectionEndPoint = null;
    if (hadPendingConnection && options.updateLinks !== false) updateLinkPath();
  }

    function openContextMenu(event, options = {}) {
    clearSelectedEdge({ update: false });
    const menu = ensureContextMenu();
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    if (!rect) return;
    contextMenuConnectionSourceIdRef.current = options.connectionSourceId || '';
    contextMenuConnectionSourceSideRef.current = normalizePortSide(options.connectionSourceSide, 'right');
    contextMenuConnectionSourceAnchorRef.current = options.connectionSourceAnchor
      ? { x: Number(options.connectionSourceAnchor.x || 0), y: Number(options.connectionSourceAnchor.y || 0) }
      : null;
    contextMenuPoint = screenToWorld(event.clientX, event.clientY);
    const items = contextMenuConnectionSourceIdRef.current ? getConnectableNodeMenuItems(contextMenuConnectionSourceIdRef.current) : NODE_MENU_ITEMS;
    renderContextMenuItems(items, options.title || '添加节点');
    if (contextMenuCloseTimer) {
      window.clearTimeout(contextMenuCloseTimer);
      contextMenuCloseTimer = 0;
    }
    menu.classList.remove('is-open');
    menu.classList.add('is-closing');
    const menuWidth = menu.offsetWidth || 224;
    const menuHeight = menu.offsetHeight || 320;
    const x = Math.min(window.innerWidth - menuWidth - 10, Math.max(10, event.clientX - 12));
    const y = Math.min(window.innerHeight - menuHeight - 10, Math.max(34, event.clientY - 12));
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    menu.style.setProperty('--desk-context-origin-x', `${Math.max(0, event.clientX - x)}px`);
    if (contextMenuConnectionSourceIdRef.current) {
      const coveredHeadX = Math.max(x + 12, Math.min(x + menuWidth - 12, event.clientX));
      const coveredHeadY = Math.max(y + 12, Math.min(y + menuHeight - 12, event.clientY));
      contextMenuConnectionEndPoint = screenToWorld(coveredHeadX, coveredHeadY);
    }
    if (contextMenuConnectionSourceIdRef.current) {
      const sourceNode = getNodeElement(contextMenuConnectionSourceIdRef.current);
      const sourcePort = sourceNode?.querySelector?.(`.desk-port[data-edge-handle][data-port-side="${contextMenuConnectionSourceSideRef.current}"]`)
        || sourceNode?.querySelector?.(`.desk-port[data-port="out"][data-port-side="${contextMenuConnectionSourceSideRef.current}"]`)
        || sourceNode?.querySelector?.('.desk-port[data-port="out"]');
      sourcePort?.classList.add('is-pending');
      holdFloatingSwell(sourcePort);
    }
    void menu.offsetWidth;
    menu.classList.remove('is-closing');
    menu.classList.add('is-open');
    updateLinkPath();
    requestAnimationFrame(() => menu.querySelector('[data-node-context-search]')?.focus?.({ preventScroll: true }));
  }

    function getCanvasEdge(edgeId) {
    const normalized = String(edgeId || '').trim();
    if (!normalized) return null;
    return (DesktopState.state.canvas.edges || []).find(edge => edge.id === normalized) || null;
  }

    function ensureEdgeMenu() {
    if (edgeMenuElRef.current) return edgeMenuElRef.current;
    edgeMenuElRef.current = document.createElement('div');
    edgeMenuElRef.current.id = 'deskEdgeMenu';
    edgeMenuElRef.current.className = 'desk-edge-menu desk-glass';
    edgeMenuElRef.current.setAttribute('role', 'menu');
    edgeMenuElRef.current.setAttribute('aria-label', '连线操作');
    edgeMenuElRef.current.setAttribute('aria-hidden', 'true');
    edgeMenuElRef.current.innerHTML = `
      <button type="button" class="desk-edge-menu__delete" data-edge-delete role="menuitem">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 5.5h13"></path><path d="M7 5.5V3.8h6v1.7"></path><path d="m5.5 5.5.7 10.2h7.6l.7-10.2"></path><path d="M8.2 8.2v4.9M11.8 8.2v4.9"></path></svg>
        <span>删除连线</span>
      </button>
    `;
    edgeMenuElRef.current.addEventListener('pointerdown', event => {
      event.stopPropagation();
    });
    edgeMenuElRef.current.addEventListener('click', event => {
      const button = event.target.closest('[data-edge-delete]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const edgeId = edgeMenuElRef.current.dataset.edgeId || selectedEdgeIdRef.current;
      if (edgeId) {
        removeEdgesById([edgeId]);
        focusCanvasViewport();
      }
    });
    edgeMenuElRef.current.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      clearSelectedEdge();
      focusCanvasViewport();
    });
    document.body.appendChild(edgeMenuElRef.current);
    return edgeMenuElRef.current;
  }

    function hideEdgeMenu() {
    if (!edgeMenuElRef.current) return;
    edgeMenuElRef.current.classList.remove('is-open');
    edgeMenuElRef.current.setAttribute('aria-hidden', 'true');
    delete edgeMenuElRef.current.dataset.edgeId;
    edgeMenuAnchorWorld = null;
  }

    function clearSelectedEdge(options = {}) {
    const hadSelection = Boolean(selectedEdgeIdRef.current || hoveredEdgeIdRef.current || edgeMenuElRef.current?.classList.contains('is-open'));
    selectedEdgeIdRef.current = '';
    hoveredEdgeIdRef.current = '';
    hideEdgeMenu();
    if (hadSelection && options.update !== false) updateLinkPath();
  }

    function positionEdgeMenu(edgeId = selectedEdgeIdRef.current) {
    if (!edgeMenuElRef.current?.classList.contains('is-open') || !edgeId) return;
    const viewportRect = els.deskCanvasViewport?.getBoundingClientRect();
    const canvas = DesktopState.state.canvas;
    let anchorX = 0;
    let anchorY = 0;
    if (edgeMenuAnchorWorld && viewportRect) {
      anchorX = viewportRect.left + canvas.x + edgeMenuAnchorWorld.x * canvas.scale;
      anchorY = viewportRect.top + canvas.y + edgeMenuAnchorWorld.y * canvas.scale;
    } else {
      const path = Array.from(document.querySelectorAll('.desk-link-path[data-edge-id]'))
        .find(item => item.dataset.edgeId === edgeId);
      if (!path) return;
      try {
        const point = path.getPointAtLength(path.getTotalLength() / 2);
        const screenPoint = new DOMPoint(point.x, point.y).matrixTransform(path.getScreenCTM());
        anchorX = screenPoint.x;
        anchorY = screenPoint.y;
      } catch (e) {
        return;
      }
    }
    const menuWidth = edgeMenuElRef.current.offsetWidth || 112;
    const menuHeight = edgeMenuElRef.current.offsetHeight || 38;
    const below = anchorY + 6;
    const above = anchorY - menuHeight - 6;
    const x = clamp(anchorX - menuWidth / 2, 10, window.innerWidth - menuWidth - 10);
    const y = below + menuHeight <= window.innerHeight - 10 ? below : Math.max(10, above);
    edgeMenuElRef.current.style.left = `${x}px`;
    edgeMenuElRef.current.style.top = `${y}px`;
    edgeMenuElRef.current.style.setProperty('--desk-edge-menu-anchor-x', `${clamp(anchorX - x, 9, menuWidth - 9)}px`);
    edgeMenuElRef.current.classList.toggle('is-above', y < anchorY);
  }

    function openEdgeMenu(edgeId, anchorEvent = null) {
    const edge = getCanvasEdge(edgeId);
    if (!edge) return;
    hideContextMenu();
    setSelectedNodes([], false);
    selectedEdgeIdRef.current = edge.id;
    hoveredEdgeIdRef.current = edge.id;
    edgeMenuAnchorWorld = Number.isFinite(anchorEvent?.clientX) && Number.isFinite(anchorEvent?.clientY)
      ? screenToWorld(anchorEvent.clientX, anchorEvent.clientY)
      : null;
    const menu = ensureEdgeMenu();
    menu.dataset.edgeId = edge.id;
    menu.classList.add('is-open');
    menu.setAttribute('aria-hidden', 'false');
    updateLinkPath();
    requestAnimationFrame(() => {
      positionEdgeMenu(edge.id);
      menu.querySelector('[data-edge-delete]')?.focus?.({ preventScroll: true });
    });
  }

    function getNodeGeometry(nodeId) {
    const node = getNodeState(nodeId);
    if (!node) return { x: 0, y: 0, width: 0, height: 0, centerX: 0, centerY: 0 };
    const el = getNodeElement(nodeId);
    const width = el?.offsetWidth || Number(node.width) || 0;
    const height = el?.offsetHeight || Number(node.height) || 0;
    const offset = getNodeVisualOffset?.(nodeId);
    const x = node.x + (offset?.x || 0), y = node.y + (offset?.y || 0);
    return { x, y, width, height, centerX: x + width / 2, centerY: y + height / 2 };
  }

    function getAnchor(nodeId, side = 'right') {
    const geometry = getNodeGeometry(nodeId);
    const normalizedSide = normalizePortSide(side);
    if (normalizedSide === 'left') return { x: geometry.x, y: geometry.centerY };
    if (normalizedSide === 'top') return { x: geometry.centerX, y: geometry.y };
    if (normalizedSide === 'bottom') return { x: geometry.centerX, y: geometry.y + geometry.height };
    return { x: geometry.x + geometry.width, y: geometry.centerY };
  }

    function resolveConnectionSides() {
    // Once committed, an edge keeps its workflow direction regardless of where
    // either node is moved: source output on the right, target input on the left.
    return { fromSide: 'right', toSide: 'left' };
  }

    function updateSettledConnectionPorts(edges = []) {
    document.querySelectorAll('.desk-node[data-node-id]').forEach(nodeElement => {
      nodeElement.classList.remove('has-settled-port-left', 'has-settled-port-right');
      nodeElement.querySelectorAll('.desk-port[data-semantic-port]').forEach(port => port.classList.remove('is-settled'));
    });
    edges.forEach(edge => {
      const sides = resolveConnectionSides(edge.from, edge.to);
      const fromNode = getNodeElement(edge.from);
      const toNode = getNodeElement(edge.to);
      syncNodeEdgeStroke(fromNode);
      syncNodeEdgeStroke(toNode);
      fromNode?.classList.add(`has-settled-port-${sides.fromSide}`);
      toNode?.classList.add(`has-settled-port-${sides.toSide}`);
      const outputPort = fromNode?.querySelector('.desk-port[data-semantic-port][data-port="out"]');
      const inputPort = toNode?.querySelector('.desk-port[data-semantic-port][data-port="in"]');
      if (outputPort) {
        outputPort.dataset.portSide = sides.fromSide;
        outputPort.classList.add('is-settled');
      }
      if (inputPort) {
        inputPort.dataset.portSide = sides.toSide;
        inputPort.classList.add('is-settled');
      }
    });
  }

    function contextMenuConnectionPreviewPath() {
    if (!contextMenuConnectionSourceIdRef.current || !contextMenuPoint || !contextMenuElRef.current?.classList.contains('is-open')) return '';
    const from = contextMenuConnectionSourceAnchorRef.current
      || getAnchor(contextMenuConnectionSourceIdRef.current, contextMenuConnectionSourceSideRef.current);
    const connectionEndPoint = contextMenuConnectionEndPoint || contextMenuPoint;
    const sourceGeometry = getNodeGeometry(contextMenuConnectionSourceIdRef.current);
    const toSide = oppositePortSide(dominantPortSide(
      { x: sourceGeometry.centerX, y: sourceGeometry.centerY },
      connectionEndPoint
    ));
    return makeConnectionPath(from, connectionEndPoint, contextMenuConnectionSourceSideRef.current, toSide, {
      fromGeometry: sourceGeometry
    });
  }

    function refreshContextMenuConnectionPreview() {
    const svg = document.querySelector('.desk-link-layer');
    if (!svg) return;
    const d = contextMenuConnectionPreviewPath();
    let path = svg.querySelector('[data-context-connection-preview]');
    if (!d) {
      path?.remove();
      return;
    }
    if (!path) {
      path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.classList.add('desk-link-path', 'is-preview', 'is-pending');
      path.dataset.contextConnectionPreview = 'true';
      svg.appendChild(path);
    }
    path.setAttribute('d', d);
  }

    function updateLinkPath() {
    const svg = document.querySelector('.desk-link-layer');
    if (!svg) return;
    svg.setAttribute('viewBox', LINK_VIEWBOX);
    const edges = DesktopState.state.canvas.edges || [];
    if (selectedEdgeIdRef.current && !edges.some(edge => edge.id === selectedEdgeIdRef.current)) {
      selectedEdgeIdRef.current = '';
      hideEdgeMenu();
    }
    if (hoveredEdgeIdRef.current && !edges.some(edge => edge.id === hoveredEdgeIdRef.current)) hoveredEdgeIdRef.current = '';
    updateSettledConnectionPorts(edges);
    const selectedNodeId = DesktopState.state.canvas.selectedNodeId || '';
    const edgeMarkup = edges.map(edge => {
      const sides = resolveConnectionSides(edge.from, edge.to);
      const from = getAnchor(edge.from, sides.fromSide);
      const to = getAnchor(edge.to, sides.toSide);
      const d = makeConnectionPath(from, to, sides.fromSide, sides.toSide, {
        fromGeometry: getNodeGeometry(edge.from),
        toGeometry: getNodeGeometry(edge.to)
      });
      const isRelated = selectedNodeId && (edge.from === selectedNodeId || edge.to === selectedNodeId);
      const relatedClass = isRelated ? ' is-related' : '';
      const selectedClass = selectedEdgeIdRef.current === edge.id ? ' is-selected' : '';
      const hoveredClass = hoveredEdgeIdRef.current === edge.id ? ' is-hovered' : '';
      const safeEdgeId = escapeHtml(edge.id);
      return `
        <path class="desk-link-path${relatedClass}${selectedClass}${hoveredClass}" data-edge-id="${safeEdgeId}" d="${d}"></path>
        <path class="desk-link-hit desk-link-interaction${selectedClass}" data-edge-id="${safeEdgeId}" data-edge-interaction d="${d}"></path>
      `;
    }).join('');
    const pendingPath = contextMenuConnectionPreviewPath();
    const pendingMarkup = pendingPath
      ? `<path class="desk-link-path is-preview is-pending" data-context-connection-preview="true" d="${pendingPath}"></path>`
      : '';
    svg.innerHTML = `${edgeMarkup}${pendingMarkup}`;
    indexEdgeVisuals(svg, edges);
    if (activeInteractionRef.current?.type === 'connect' && activeInteractionRef.current.pointer) {
      renderConnectionPreview(
        activeInteractionRef.current.fromNodeId,
        activeInteractionRef.current.pointer,
        activeInteractionRef.current.fromSide,
        activeInteractionRef.current.fromAnchor
      );
    }
    if (edgeMenuElRef.current?.classList.contains('is-open')) requestAnimationFrame(() => positionEdgeMenu());
    renderMiniMap();
  }

    // Rebuilt only with the settled SVG. A recoil frame visits the affected
    // node's adjacency list, never all nodes/edges or node form controls.
    function indexEdgeVisuals(svg, edges) {
    edgeVisuals.clear();
    nodeEdgeVisuals.clear();
    const paths = new Map();
    svg.querySelectorAll('[data-edge-id]').forEach(path => {
      const id = path.dataset.edgeId;
      if (!paths.has(id)) paths.set(id, []);
      paths.get(id).push(path);
    });
    edges.forEach(edge => {
      const record = { edge, paths: paths.get(edge.id) || [] };
      edgeVisuals.set(edge.id, record);
      [edge.from, edge.to].forEach(id => {
        if (!nodeEdgeVisuals.has(id)) nodeEdgeVisuals.set(id, []);
        nodeEdgeVisuals.get(id).push(record);
      });
    });
  }

    function getEdgeVisualPath(edgeId) {
    return edgeVisuals.get(edgeId)?.paths.find(path => path.classList.contains('desk-link-path')) || null;
  }

    function refreshNodeConnectionGeometry(nodeId) {
    const geometries = new Map();
    const geometry = id => {
      if (!geometries.has(id)) geometries.set(id, getNodeGeometry(id));
      return geometries.get(id);
    };
    (nodeEdgeVisuals.get(nodeId) || []).forEach(({ edge, paths }) => {
      if (!paths.some(path => path.isConnected)) return;
      const a = geometry(edge.from), b = geometry(edge.to);
      const d = makeConnectionPath({ x: a.x + a.width, y: a.centerY }, { x: b.x, y: b.centerY }, 'right', 'left', {
        fromGeometry: a, toGeometry: b
      });
      paths.forEach(path => { if (path.getAttribute('d') !== d) path.setAttribute('d', d); });
    });
  }

    function setHoveredEdge(edgeId = '') {
    const normalized = getCanvasEdge(edgeId)?.id || '';
    if (hoveredEdgeIdRef.current === normalized) return;
    hoveredEdgeIdRef.current = normalized;
    const svg = document.querySelector('.desk-link-layer');
    svg?.querySelectorAll('[data-edge-id]').forEach(element => {
      element.classList.toggle('is-hovered', Boolean(normalized && element.dataset.edgeId === normalized));
    });
  }

    function bindLinkLayerInteractions() {
    const svg = document.querySelector('.desk-link-layer');
    if (!svg || svg.dataset.edgeInteractionsBound === 'true') return;
    svg.dataset.edgeInteractionsBound = 'true';
    const interactiveForEvent = event => event.target?.closest?.('[data-edge-interaction][data-edge-id]') || null;
    svg.addEventListener('pointerdown', event => {
      const interactive = interactiveForEvent(event);
      if (!interactive || (event.button !== 0 && event.button !== 2)) return;
      event.preventDefault();
      event.stopPropagation();
    });
    svg.addEventListener('click', event => {
      const interactive = interactiveForEvent(event);
      if (!interactive) return;
      event.preventDefault();
      event.stopPropagation();
      openEdgeMenu(interactive.dataset.edgeId || '', event);
    });
    svg.addEventListener('contextmenu', event => {
      const interactive = interactiveForEvent(event);
      if (!interactive) return;
      event.preventDefault();
      event.stopPropagation();
      openEdgeMenu(interactive.dataset.edgeId || '', event);
    });
    svg.addEventListener('pointerover', event => {
      const interactive = interactiveForEvent(event);
      if (!interactive) return;
      setHoveredEdge(interactive.dataset.edgeId || '');
    });
    svg.addEventListener('pointerout', event => {
      const interactive = interactiveForEvent(event);
      if (!interactive) return;
      const nextInteractive = event.relatedTarget?.closest?.('[data-edge-interaction][data-edge-id]');
      if (nextInteractive?.dataset.edgeId === interactive.dataset.edgeId) return;
      if (selectedEdgeIdRef.current !== interactive.dataset.edgeId) setHoveredEdge('');
    });
  }

    function connectionLineStyle() {
    return window.DesktopPreferences?.state?.connectionLineStyle === 'curve'
      ? 'curve'
      : 'straight';
  }

    function makeConnectionPath(from, to, fromSide = 'right', toSide = 'left', route = null) {
    if (connectionLineStyle() === 'curve') {
      return makeClassicCurvePath(from, to, fromSide, toSide, route);
    }
    return makeSmoothStepPath(from, to, fromSide, toSide, route);
  }

    function ensureLiveConnectionPreviewPath(svg) {
    let path = svg?.querySelector('[data-live-connection-preview]');
    if (path || !svg) return path;
    path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.classList.add('desk-link-path', 'is-preview');
    path.dataset.liveConnectionPreview = 'true';
    svg.appendChild(path);
    return path;
  }

    function flushConnectionPreviewFrame() {
    connectionPreviewFrameId = 0;
    const point = pendingConnectionDropPointRef.current || connectionPointerClient;
    pendingConnectionDropPointRef.current = null;
    if (point) updateConnectionDropTarget(point.x, point.y);
    const svg = document.querySelector('.desk-link-layer');
    const preview = pendingConnectionPreview;
    if (svg && preview) {
      const normalizedFromSide = normalizePortSide(preview.fromSide, 'right');
      const sourceGeometry = getNodeGeometry(preview.fromNodeId);
      const snap = connectionSnapTarget;
      const toSide = snap?.side || oppositePortSide(dominantPortSide(
        { x: sourceGeometry.centerX, y: sourceGeometry.centerY },
        preview.pointer
      ));
      const destination = snap ? getAnchor(snap.nodeId, toSide) : preview.pointer;
      const from = preview.fromAnchor || getAnchor(preview.fromNodeId, normalizedFromSide);
      const d = makeConnectionPath(from, destination, normalizedFromSide, toSide, {
        fromGeometry: sourceGeometry,
        ...(snap ? { toGeometry: getNodeGeometry(snap.nodeId) } : {})
      });
      ensureLiveConnectionPreviewPath(svg)?.setAttribute('d', d);
    }
  }

    function scheduleConnectionPreviewFrame() {
    if (!connectionPreviewFrameId) connectionPreviewFrameId = requestAnimationFrame(flushConnectionPreviewFrame);
  }

    function clearLiveConnectionPreview() {
    if (connectionPreviewFrameId) cancelAnimationFrame(connectionPreviewFrameId);
    connectionPreviewFrameId = 0;
    pendingConnectionPreview = null;
    pendingConnectionDropPointRef.current = null;
    connectionPointerClient = null;
    connectionApproachPoint = null;
    connectionSnapTarget = null;
    clearConnectionProximity?.();
    document.querySelector('.desk-link-layer [data-live-connection-preview]')?.remove();
  }

    function renderConnectionPreview(fromNodeId, pointer, fromSide = 'right', fromAnchor = null) {
    const svg = document.querySelector('.desk-link-layer');
    if (!svg) return;
    pendingConnectionPreview = {
      fromNodeId,
      pointer: { x: Number(pointer?.x) || 0, y: Number(pointer?.y) || 0 },
      fromSide,
      fromAnchor: fromAnchor ? { x: Number(fromAnchor.x) || 0, y: Number(fromAnchor.y) || 0 } : null
    };
    scheduleConnectionPreviewFrame();
  }

    function connectNodes(fromNodeId, toNodeId, options = {}) {
    const from = DesktopState.state.canvas.nodes[fromNodeId];
    const to = DesktopState.state.canvas.nodes[toNodeId];
    const modelToResult = from?.type === 'input' && (to?.type === 'output' || to?.type === 'file_output');
    const modelToImage = from?.type === 'input' && to?.type === 'image';
    const modelToUpscale = from?.type === 'input' && to?.type === 'upscale';
    const comfyToImage = from?.type === 'comfy' && to?.type === 'image';
    const comfyToUpscale = from?.type === 'comfy' && to?.type === 'upscale';
    const imageToComfy = from?.type === 'image' && to?.type === 'comfy';
    const imageGroupToInput = from?.type === 'image_group' && to?.type === 'input';
    const imageGroupToComfy = from?.type === 'image_group' && to?.type === 'comfy';
    const imageToLayout = from?.type === 'image' && to?.type === 'layout';
    const imageToPoseReference = from?.type === 'image' && to?.type === 'pose';
    const imageToUpscale = from?.type === 'image' && to?.type === 'upscale';
    const layoutToComfy = from?.type === 'layout' && to?.type === 'comfy';
    const layoutToUpscale = from?.type === 'layout' && to?.type === 'upscale';
    const poseToInput = from?.type === 'pose' && to?.type === 'input';
    const poseToComfy = from?.type === 'pose' && to?.type === 'comfy';
    const poseToUpscale = from?.type === 'pose' && to?.type === 'upscale';
    const textToInput = from?.type === 'text' && to?.type === 'input';
    const textToComfy = from?.type === 'text' && to?.type === 'comfy';
    const textToVideoInference = from?.type === 'text' && to?.type === 'video_inference';
    const imageToVideoInference = from?.type === 'image' && to?.type === 'video_inference';
    const layoutToVideoInference = from?.type === 'layout' && to?.type === 'video_inference';
    const poseToVideoInference = from?.type === 'pose' && to?.type === 'video_inference';
    const videoToVideoInference = from?.type === 'video' && to?.type === 'video_inference';
    const videoInferenceToVideo = from?.type === 'video_inference' && to?.type === 'video';
    const outputToImage = from?.type === 'output' && to?.type === 'image';
    const upscaleToImage = from?.type === 'upscale' && to?.type === 'image';
    const videoInputConnection = textToVideoInference || imageToVideoInference || layoutToVideoInference || poseToVideoInference || videoToVideoInference;
    if (!canConnectNodes(fromNodeId, toNodeId)) {
      if (!options.quiet) DesktopResults.showTransientMessage('当前节点类型不能这样连接。视频生成可接入文本、图片、姿态、排版或视频节点。');
      return '';
    }
    const domainPolicy = domainConnections?.policy(from, to, options, DesktopState.state.canvas.edges || []);
    const inputRole = String(domainPolicy?.inputRole || options.inputRole || (videoInputConnection ? videoInputRoleForSource(from.type) : '')).trim();
    DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || []).filter(edge => {
      if (domainPolicy?.replaceAllInputs && edge.to === toNodeId) return false;
      if (domainPolicy?.single && edge.to === toNodeId && edge.inputRole === inputRole) return false;
      if (modelToResult) return edge.to !== toNodeId;
      if (modelToImage || comfyToImage) return edge.to !== toNodeId;
      if (videoInferenceToVideo) return edge.to !== toNodeId;
      if (videoInputConnection && inputRole) {
        const edgeSource = DesktopState.state.canvas.nodes[edge.from];
        const edgeRole = edge.inputRole || videoInputRoleForSource(edgeSource?.type);
        return !(edge.to === toNodeId && edgeRole === inputRole);
      }
      if (outputToImage) return edge.to !== toNodeId;
      if (upscaleToImage) return edge.to !== toNodeId;
      return !(edge.from === fromNodeId && edge.to === toNodeId);
    });
    const edgeId = `${fromNodeId}_${toNodeId}_${Date.now()}`;
    DesktopState.state.canvas.edges.push({
      id: edgeId,
      from: fromNodeId,
      to: toNodeId,
      inputRole: inputRole || undefined,
      outputRole: domainPolicy?.outputRole || (videoInferenceToVideo ? 'video' : undefined),
      outputSlot: Number.isFinite(Number(options.outputSlot)) ? Number(options.outputSlot) : undefined
    });
    if (textToInput || textToComfy) ensureTextNodeImageReferenceConnections(fromNodeId, toNodeId);
    refreshImageReferenceTokens();
    document.querySelectorAll('.desk-port.is-connecting').forEach(item => item.classList.remove('is-connecting'));
    updateLinkPath();
    if (domainPolicy) {
      domainConnections.changed(fromNodeId, toNodeId);
      DesktopState.saveSettings();
      return edgeId;
    }
    if (imageToLayout) {
      updateLayoutInputCount(toNodeId);
      DesktopLayoutEditor?.syncConnectedImages?.(toNodeId)
        ?.then(imported => {
          DesktopResults.showTransientMessage(imported ? '图片已填入排版模板。' : '图片已接入排版节点，打开排版会自动导入。');
        })
        .catch(() => {
          DesktopResults.showTransientMessage('图片已接入排版节点，打开排版会自动导入。');
        });
    } else if (imageToPoseReference) {
      refreshPoseNode(toNodeId);
      DesktopResults.showTransientMessage('图片已接入姿态参考节点，可作为背景参考。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (imageToUpscale || layoutToUpscale || poseToUpscale) {
      updateUpscaleInputCount(toNodeId);
      DesktopResults.showTransientMessage('图片已接入高清放大节点。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (videoInputConnection) {
      refreshVideoInferenceNode(toNodeId);
      if (!options.quiet) {
        const label = inputRole === 'prompt' ? '提示词' : (inputRole === 'first_frame' ? '首帧' : '参考视频');
        DesktopResults.showTransientMessage(`${label}已接入 MiniMax H3 节点。`);
      }
      DesktopState.saveSettings();
      return edgeId;
    } else if (videoInferenceToVideo) {
      refreshVideoInferenceNode(fromNodeId);
      refreshVideoNode(toNodeId);
      if (!options.quiet) DesktopResults.showTransientMessage('视频结果节点已接入 MiniMax H3 输出。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (imageToComfy || imageGroupToComfy || layoutToComfy || poseToComfy || textToComfy) {
      refreshComfyNode(toNodeId);
      if (!options.quiet) DesktopResults.showTransientMessage('输入已接入 Comfy 工作流节点。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (imageGroupToInput) {
      if (!options.quiet) DesktopResults.showTransientMessage(`图片组已按当前顺序接入，共 ${from.items?.length || 0} 张。`);
      DesktopState.saveSettings();
      return edgeId;
    } else if (poseToInput) {
      DesktopResults.showTransientMessage('姿态参考节点已接入模型，导出后会作为参考图。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (textToInput) {
      if (!options.quiet) DesktopResults.showTransientMessage('文本节点已接入模型提示词。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (modelToImage || comfyToImage) {
      assignImageOutputSlots(fromNodeId);
      if (!options.quiet) DesktopResults.showTransientMessage('图片节点已接入生成输出。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (modelToUpscale || comfyToUpscale) {
      updateUpscaleInputCount(toNodeId);
      if (!options.quiet) DesktopResults.showTransientMessage('高清放大已接入模型输出，模型完成后会自动放大。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (outputToImage) {
      const output = DesktopState.state.outputs?.[fromNodeId];
      if (output?.imagePaths?.length) {
        setImageNodeFromResult(toNodeId, fromNodeId, output, options.outputSlot || 0).catch(error => DesktopResults.showError(error));
        DesktopResults.showTransientMessage('结果图已回填到图片节点。');
      } else {
        DesktopResults.showTransientMessage('已连接；结果节点生成完成后会自动填入图片节点。');
      }
      DesktopState.saveSettings();
      return edgeId;
    } else if (upscaleToImage) {
      refreshUpscaleNodeMode(fromNodeId);
      const output = DesktopState.state.outputs?.[fromNodeId];
      if (output?.imagePaths?.length) {
        setImageNodeFromResult(toNodeId, fromNodeId, output, options.outputSlot || 0).catch(error => DesktopResults.showError(error));
        DesktopResults.showTransientMessage('高清结果已回填到图片节点。');
      } else {
        DesktopResults.showTransientMessage('已连接；高清放大完成后会自动填入图片节点。');
      }
      DesktopState.saveSettings();
      return edgeId;
    } else {
      DesktopState.saveSettings();
      return edgeId;
    }
    DesktopState.saveSettings();
    return edgeId;
  }

    function handleRemovedEdges(removedEdges = []) {
    domainConnections?.removed(removedEdges);
    const layoutIds = new Set();
    const poseIds = new Set();
    const upscaleIds = new Set();
    const modelOutputIds = new Set();
    const comfyIds = new Set();
    const videoInferenceIds = new Set();
    const videoIds = new Set();
    removedEdges.forEach(edge => {
      const from = DesktopState.state.canvas.nodes[edge.from];
      const to = DesktopState.state.canvas.nodes[edge.to];
      if (to?.type === 'layout') layoutIds.add(edge.to);
      if (to?.type === 'pose') poseIds.add(edge.to);
      if (to?.type === 'upscale') upscaleIds.add(edge.to);
      if (from?.type === 'upscale') upscaleIds.add(edge.from);
      if ((from?.type === 'input' || from?.type === 'comfy') && to?.type === 'image') modelOutputIds.add(edge.from);
      if (to?.type === 'comfy') comfyIds.add(edge.to);
      if (to?.type === 'video_inference') videoInferenceIds.add(edge.to);
      if (from?.type === 'video_inference') videoInferenceIds.add(edge.from);
      if (to?.type === 'video') videoIds.add(edge.to);
    });
    modelOutputIds.forEach(assignImageOutputSlots);
    layoutIds.forEach(updateLayoutInputCount);
    poseIds.forEach(refreshPoseNode);
    upscaleIds.forEach(updateUpscaleInputCount);
    comfyIds.forEach(refreshComfyNode);
    videoInferenceIds.forEach(refreshVideoInferenceNode);
    videoIds.forEach(refreshVideoNode);
    refreshImageReferenceTokens();
  }

    function removeEdgesById(edgeIds = [], options = {}) {
    const ids = new Set(edgeIds.filter(Boolean));
    if (!ids.size) return [];
    if (ids.has(selectedEdgeIdRef.current)) {
      selectedEdgeIdRef.current = '';
      hideEdgeMenu();
    }
    if (ids.has(hoveredEdgeIdRef.current)) hoveredEdgeIdRef.current = '';
    const removed = [];
    DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || []).filter(edge => {
      if (!ids.has(edge.id)) return true;
      removed.push(edge);
      return false;
    });
    if (!removed.length) return [];
    handleRemovedEdges(removed);
    updateLinkPath();
    if (!options.quiet) DesktopResults.showTransientMessage('连接已解除。');
    DesktopState.saveSettings();
    return removed;
  }

    function getDetachableIncomingEdge(toNodeId) {
    return [...(DesktopState.state.canvas.edges || [])]
      .reverse()
      .find(edge => edge.to === toNodeId && DesktopState.state.canvas.nodes[edge.from] && DesktopState.state.canvas.nodes[edge.to]);
  }

    function clearConnectionDragVisuals() {
    clearLiveConnectionPreview();
    document.querySelectorAll('.desk-port.is-connecting, .desk-port.is-drop-target').forEach(item => {
      item.classList.remove('is-connecting', 'is-drop-target');
    });
    document.querySelectorAll('.desk-node.is-connection-drop-target').forEach(item => item.classList.remove('is-connection-drop-target'));
    document.querySelectorAll('.desk-node.is-compatible-target').forEach(item => item.classList.remove('is-compatible-target'));
    document.querySelectorAll('.desk-port[data-semantic-port][data-port="in"]').forEach(port => {
      port.dataset.portSide = 'left';
    });
    clearFloatingConnectionPort();
    els.deskCanvasViewport?.classList.remove('is-connecting');
  }

    function markCompatibleConnectionTargets(fromNodeId) {
    document.querySelectorAll('.desk-node[data-node-id]').forEach(nodeElement => {
      const isCompatible = canConnectNodes(fromNodeId, nodeElement.dataset.nodeId);
      nodeElement.classList.toggle('is-compatible-target', isCompatible);
      if (isCompatible) {
        syncNodeEdgeStroke(nodeElement);
        const inputPort = nodeElement.querySelector('.desk-port[data-semantic-port][data-port="in"]');
        if (inputPort) inputPort.dataset.portSide = resolveConnectionSides(fromNodeId, nodeElement.dataset.nodeId).toSide;
      }
    });
  }

    function findNearestConnectionTarget(fromNodeId, clientX, clientY, radius) {
    if (!fromNodeId) return null;
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return null;
    const viewport = els.deskCanvasViewport?.getBoundingClientRect();
    if (!viewport || clientX < viewport.left || clientX > viewport.right
      || clientY < viewport.top || clientY > viewport.bottom) return null;
    const hit = document.elementFromPoint(clientX, clientY);
    if (hit?.closest?.('.desk-node-palette, .desk-gallery-panel, .desk-gallery, .desk-settings, .desk-selection-toolbar, .desk-zoom-controls, .desk-workflow-dock-toggle, .desk-workflow-dock-panel')) return null;
    const hitNode = hit?.closest?.('.desk-node[data-node-id]');
    let nearest = null;
    document.querySelectorAll('.desk-node.is-compatible-target[data-node-id]').forEach(nodeElement => {
      const nodeId = nodeElement.dataset.nodeId;
      if (!canConnectNodes(fromNodeId, nodeId)) return;
      // Do not attract through another node that covers this input port.
      if (hitNode && hitNode !== nodeElement) return;
      const port = nodeElement.querySelector('.desk-port[data-semantic-port][data-port="in"]');
      if (!port || port.disabled || port.hidden) return;
      const rect = port.getBoundingClientRect();
      if (!(rect.width > 0 && rect.height > 0)) return;
      // DOM bounds are already screen-scaled: both proximity halos are independent of
      // canvas zoom, port size and devicePixelRatio. Use Euclidean corner distance.
      const dx = Math.max(rect.left - clientX, 0, clientX - rect.right);
      const dy = Math.max(rect.top - clientY, 0, clientY - rect.bottom);
      const distance = Math.hypot(dx, dy);
      if (distance > radius || (nearest && distance >= nearest.distance)) return;
      const portHit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
      if (portHit?.closest?.('.desk-node[data-node-id]') !== nodeElement) return;
      nearest = { nodeId, nodeElement, port, rect, side: normalizePortSide(port.dataset.portSide, 'left'), distance };
    });
    return nearest;
  }

    function findConnectionSnapTarget(fromNodeId, clientX, clientY) {
    return findNearestConnectionTarget(fromNodeId, clientX, clientY, CONNECTION_SNAP_RADIUS_PX);
  }

    function updateConnectionDropTarget(clientX, clientY) {
    connectionPointerClient = { x: clientX, y: clientY };
    const fromNodeId = activeInteractionRef.current?.type === 'connect'
      ? activeInteractionRef.current.fromNodeId : '';
    // One geometry/policy scan per preview frame, not a second particle hit-test.
    const nearest = findNearestConnectionTarget(fromNodeId, clientX, clientY, CONNECTION_PROXIMITY_RADIUS_PX);
    connectionSnapTarget = nearest && nearest.distance <= CONNECTION_SNAP_RADIUS_PX ? nearest : null;
    // Keep the last free tip through magnetic capture. Commit presentation uses
    // this direction only; no new hit test, graph state or pointer-velocity loop.
    if (!nearest || nearest.distance >= CONNECTION_PROXIMITY_RADIUS_PX) connectionApproachPoint = null;
    else if (!connectionSnapTarget || connectionApproachPoint?.nodeId !== nearest.nodeId) {
      connectionApproachPoint = { nodeId: nearest.nodeId, ...screenToWorld(clientX, clientY) };
    }
    updateConnectionProximity?.(nearest && nearest.distance < CONNECTION_PROXIMITY_RADIUS_PX ? {
      ...nearest, pointer: { x: clientX, y: clientY },
      phase: connectionSnapTarget ? 'snapped' : 'near',
      strength: Math.max(0, (nearest.distance - CONNECTION_SNAP_RADIUS_PX)
        / (CONNECTION_PROXIMITY_RADIUS_PX - CONNECTION_SNAP_RADIUS_PX))
    } : null);
    document.querySelectorAll('.desk-port.is-drop-target').forEach(item => item.classList.remove('is-drop-target'));
    document.querySelectorAll('.desk-node.is-connection-drop-target').forEach(item => item.classList.remove('is-connection-drop-target'));
    const target = document.elementFromPoint(clientX, clientY);
    const compatibleNode = connectionSnapTarget
      ? getNodeElement(connectionSnapTarget.nodeId)
      : target?.closest?.('.desk-node.is-compatible-target[data-node-id]');
    if (!compatibleNode || !canConnectNodes(fromNodeId, compatibleNode.dataset.nodeId)) return;
    compatibleNode.classList.add('is-connection-drop-target');
    compatibleNode.querySelector('.desk-port[data-semantic-port][data-port="in"]')?.classList.add('is-drop-target');
  }

    function startConnectionDrag(event, button) {
    if (event.button !== 0) return;
    const nodeId = button.dataset.nodeId;
    const port = button.dataset.port;
    if (port !== 'out') return;
    const fromSide = normalizePortSide(button.dataset.portSide, 'right');
    const fromAnchor = getConnectionPortAnchor(nodeId, button, fromSide);
    syncNodeEdgeStroke(getNodeElement(nodeId));
    event.preventDefault();
    event.stopPropagation();
    hideContextMenu();
    clearConnectionDragVisuals();
    button.classList.add('is-connecting');
    holdFloatingSwell(button);
    els.deskCanvasViewport?.classList.add('is-connecting');
    activeInteractionRef.current = {
      type: 'connect',
      fromNodeId: nodeId,
      fromSide,
      fromAnchor,
      pointer: screenToWorld(event.clientX, event.clientY)
    };
    markCompatibleConnectionTargets(nodeId);
    renderConnectionPreview(nodeId, activeInteractionRef.current.pointer, activeInteractionRef.current.fromSide, activeInteractionRef.current.fromAnchor);
    const nodeType = DesktopState.state.canvas.nodes[nodeId]?.type;
    DesktopResults.showTransientMessage(nodeType === 'image'
      ? '拖到兼容的模型、排版或姿态参考节点后松开。'
      : (nodeType === 'output'
        ? '拖到图片节点上后松开。'
        : (nodeType === 'layout' || nodeType === 'text' || nodeType === 'pose' ? '拖到兼容的模型节点后松开。' : '拖到兼容节点，或空白处创建并自动连接。')));
  }

    function startConnectionDetachDrag(event, button) {
    if (event.button !== 0) return;
    const nodeId = button.dataset.nodeId;
    const port = button.dataset.port;
    if (port !== 'in') return;
    const edge = getDetachableIncomingEdge(nodeId);
    if (!edge) return;
    event.preventDefault();
    event.stopPropagation();
    removeEdgesById([edge.id], { quiet: true });
    hideContextMenu();
    clearConnectionDragVisuals();
    const sides = resolveConnectionSides(edge.from, edge.to);
    const sourcePort = getNodeElement(edge.from)?.querySelector?.(`.desk-port[data-port="out"][data-port-side="${sides.fromSide}"]`)
      || getNodeElement(edge.from)?.querySelector?.('.desk-port[data-port="out"]');
    sourcePort?.classList.add('is-connecting');
    els.deskCanvasViewport?.classList.add('is-connecting');
    activeInteractionRef.current = {
      type: 'connect',
      fromNodeId: edge.from,
      fromSide: sides.fromSide,
      fromAnchor: getAnchor(edge.from, sides.fromSide),
      detachedEdge: edge,
      reconnecting: true,
      pointer: screenToWorld(event.clientX, event.clientY)
    };
    markCompatibleConnectionTargets(edge.from);
    renderConnectionPreview(edge.from, activeInteractionRef.current.pointer, activeInteractionRef.current.fromSide, activeInteractionRef.current.fromAnchor);
    DesktopResults.showTransientMessage('连接已拉开，拖到其它输入端点可重连，松开空白处则解除。');
  }

    function commitDraggedConnection(fromNodeId, toNodeId, entryPoint) {
    const anchor = getAnchor(toNodeId, 'left');
    const approach = { x: anchor.x - entryPoint.x, y: anchor.y - entryPoint.y };
    const edgeId = connectNodes(fromNodeId, toNodeId);
    // Programmatic/restore connections never animate; previews/cancels are not commits.
    if (edgeId) playConnectionCommit?.({ edgeId, fromNodeId, toNodeId, approach });
  }

    function finishConnectionDrag(event) {
    const interaction = activeInteractionRef.current;
    if (interaction?.type !== 'connect') return;
    if (event?.type === 'pointercancel') {
      activeInteractionRef.current = null;
      clearConnectionDragVisuals();
      updateLinkPath();
      return;
    }
    // Recheck release coordinates and live node types, even if pointerup happens
    // before the queued preview frame or without a final pointermove.
    const snappedTarget = findConnectionSnapTarget(interaction.fromNodeId, event.clientX, event.clientY);
    // End the drag before any link redraw can schedule another live preview.
    // Keep the source locally for reconnects and the add-node context menu.
    activeInteractionRef.current = null;
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const compatibleNode = target?.closest?.('.desk-node.is-compatible-target[data-node-id]');
    const compatibleNodeId = compatibleNode?.dataset?.nodeId || '';
    const port = target?.closest?.('.desk-port[data-port="in"]');
    const portNodeId = port?.closest?.('.desk-node.is-compatible-target[data-node-id]')?.dataset?.nodeId || '';
    const approachPoint = connectionApproachPoint;
    const releasePoint = screenToWorld(event.clientX, event.clientY);
    const commitTo = nodeId => commitDraggedConnection(interaction.fromNodeId, nodeId,
      approachPoint?.nodeId === nodeId ? approachPoint : releasePoint);
    clearConnectionDragVisuals();
    if (snappedTarget || portNodeId || compatibleNodeId) {
      commitTo(snappedTarget?.nodeId || portNodeId || compatibleNodeId);
      return;
    }
    const sourceNode = DesktopState.state.canvas.nodes[interaction.fromNodeId];
    if (sourceNode?.type === 'output' || sourceNode?.type === 'input' || sourceNode?.type === 'comfy' || sourceNode?.type === 'upscale') {
      const imageNode = target?.closest?.('.desk-node--image[data-node-id]');
      if (imageNode) {
        commitTo(imageNode.dataset.nodeId);
        return;
      }
    }
    updateLinkPath();
    if (interaction.reconnecting) {
      DesktopResults.showTransientMessage('连接已解除。');
      return;
    }
    const items = getConnectableNodeMenuItems(interaction.fromNodeId);
    const viewportRect = els.deskCanvasViewport?.getBoundingClientRect();
    const isInsideViewport = !!viewportRect
      && event.clientX >= viewportRect.left
      && event.clientX <= viewportRect.right
      && event.clientY >= viewportRect.top
      && event.clientY <= viewportRect.bottom;
    const isBlankCanvas = !target?.closest?.('.desk-node, .desk-node-palette, .desk-gallery-panel, .desk-settings, .desk-selection-toolbar, .desk-zoom-controls, .desk-workflow-dock-toggle, .desk-workflow-dock-panel');
    if (items.length && isInsideViewport && isBlankCanvas) {
      openContextMenu(event, {
        connectionSourceId: interaction.fromNodeId,
        connectionSourceSide: interaction.fromSide,
        connectionSourceAnchor: interaction.fromAnchor,
        title: '添加节点'
      });
      DesktopResults.showTransientMessage('选择一个节点继续连接。');
      return;
    }
    DesktopResults.showTransientMessage('连接已取消。');
  }

    return Object.freeze({
      filterContextMenuItems,
      getConnectableNodeMenuItems,
      canConnectNodes,
      renderContextMenuItems,
      ensureContextMenu,
      finishContextMenuClose,
      hideContextMenu,
      openContextMenu,
      getCanvasEdge,
      ensureEdgeMenu,
      hideEdgeMenu,
      clearSelectedEdge,
      positionEdgeMenu,
      openEdgeMenu,
      getNodeGeometry,
      getEdgeVisualPath,
      refreshNodeConnectionGeometry,
      getAnchor,
      resolveConnectionSides,
      updateSettledConnectionPorts,
      contextMenuConnectionPreviewPath,
      refreshContextMenuConnectionPreview,
      updateLinkPath,
      setHoveredEdge,
      bindLinkLayerInteractions,
      connectionLineStyle,
      makeConnectionPath,
      ensureLiveConnectionPreviewPath,
      flushConnectionPreviewFrame,
      scheduleConnectionPreviewFrame,
      clearLiveConnectionPreview,
      renderConnectionPreview,
      connectNodes,
      handleRemovedEdges,
      removeEdgesById,
      getDetachableIncomingEdge,
      clearConnectionDragVisuals,
      markCompatibleConnectionTargets,
      findConnectionSnapTarget,
      updateConnectionDropTarget,
      startConnectionDrag,
      startConnectionDetachDrag,
      finishConnectionDrag,
    });
  }

  // Explicit domain composition: domains keep their own contracts/state.
  function combineDomains(...domains) {
    const targets = {};
    domains.forEach(d => Object.entries(d.targets).forEach(([type, values]) => {
      targets[type] = [...new Set([...(targets[type] || []), ...values])];
    }));
    return { targets, policy: (...args) => domains.map(d => d.policy(...args)).find(Boolean),
      changed: (...args) => domains.forEach(d => d.changed(...args)),
      removed: (...args) => domains.forEach(d => d.removed(...args)) };
  }
  window.DesktopCanvasConnections = Object.freeze({ create, combineDomains });
})();
