// Floating liquid/droplet ports and connection anchors. Connection policy/distances belong to connections.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    FLOATING_DROPLET_PEAK_PX,
    FLOATING_PORT_TRACKING_MARGIN_PX,
    FLOATING_SWELL_BORDER_PADDING_PX,
    FLOATING_SWELL_EDGE_INSET_PX,
    FLOATING_SWELL_EDGE_OUTSET_PX,
    FLOATING_SWELL_LINK_OVERLAP_SCREEN_PX,
    FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS,
    FLOATING_SWELL_PEAK_PX,
    FLOATING_SWELL_VISIBLE_THRESHOLD_PX,
    IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX,
    activeInteractionRef,
    buildFloatingDropletPath,
    buildFloatingSwellPath,
    buildFloatingSwellPerimeter,
    clamp,
    closestFloatingSwellSample,
    contextMenuConnectionSourceAnchorRef,
    contextMenuConnectionSourceIdRef,
    contextMenuConnectionSourceSideRef,
    contextMenuElRef,
    els,
    discardConnectionFeedback,
    floatingSwellModulo,
    floatingSwellPointAt,
    floatingSwellShortestArcDelta,
    floatingSwellSide,
    floatingSwellSpringAtRest,
    floatingSwellSpringStep,
    getAnchor,
    getNodeState,
    normalizePortSide,
    portOutwardVector,
    prefersReducedMotion,
    refreshContextMenuConnectionPreview,
    renderConnectionPreview,
  }) {
    const floatingSwellStates = new Set();
    let floatingSwellFrameId = 0;
    let floatingSwellLastFrame = 0;
    function connectionSwellStyle() {
    return window.DesktopPreferences?.state?.connectionSwellStyle === 'droplet'
      ? 'droplet'
      : 'liquid';
  }

    function floatingSwellBounds(nodeElement) {
    const style = getComputedStyle(nodeElement);
    const radius = Math.max(0, parseFloat(style.borderTopLeftRadius) || 0);
    const borderLeft = Math.max(0, parseFloat(style.borderLeftWidth) || 0);
    const borderTop = Math.max(0, parseFloat(style.borderTopWidth) || 0);
    const length = value => Math.max(0, parseFloat(value) || 0);
    // offsetWidth/Height round fractional sizes (notably liquid image groups).
    // Resolved CSS sizes preserve subpixels without including canvas transforms.
    const cssWidth = length(style.width), cssHeight = length(style.height);
    const horizontalInset = style.boxSizing === 'border-box' ? 0
      : borderLeft + length(style.borderRightWidth) + length(style.paddingLeft) + length(style.paddingRight);
    const verticalInset = style.boxSizing === 'border-box' ? 0
      : borderTop + length(style.borderBottomWidth) + length(style.paddingTop) + length(style.paddingBottom);
    const nodeWidth = cssWidth ? cssWidth + horizontalInset : nodeElement.offsetWidth || Number(getNodeState(nodeElement.dataset.nodeId)?.width || 0);
    const nodeHeight = cssHeight ? cssHeight + verticalInset : nodeElement.offsetHeight || Number(getNodeState(nodeElement.dataset.nodeId)?.height || 0);
    const liquidBase = nodeElement.matches('.desk-node--image-group')
      ? nodeElement.querySelector('[data-image-group-liquid-base]')
      : null;
    if (!liquidBase) {
      return { nodeWidth, nodeHeight, borderLeft, borderTop, x: 0, y: 0, width: nodeWidth, height: nodeHeight, radius };
    }
    const baseX = clamp(Number(liquidBase.getAttribute('x')) || 0, 0, nodeWidth);
    const baseY = clamp(Number(liquidBase.getAttribute('y')) || 0, 0, nodeHeight);
    const baseWidth = clamp(Number(liquidBase.getAttribute('width')) || nodeWidth, 0, nodeWidth - baseX);
    const baseHeight = clamp(Number(liquidBase.getAttribute('height')) || nodeHeight, 0, nodeHeight - baseY);
    const baseRadius = Math.max(0, Number(liquidBase.getAttribute('rx')) || radius);
    const outset = IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX;
    return {
      nodeWidth,
      nodeHeight,
      borderLeft,
      borderTop,
      x: baseX - outset,
      y: baseY - outset,
      width: baseWidth + outset * 2,
      height: baseHeight + outset * 2,
      radius: baseRadius + outset
    };
  }

    function updateFloatingSwellGeometry(state) {
    const nodeElement = state.nodeElement;
    const bounds = floatingSwellBounds(nodeElement);
    if (
      state.geometry
      && state.width === bounds.nodeWidth
      && state.height === bounds.nodeHeight
      && state.borderLeft === bounds.borderLeft
      && state.borderTop === bounds.borderTop
      && state.geometryX === bounds.x
      && state.geometryY === bounds.y
      && state.geometryWidth === bounds.width
      && state.geometryHeight === bounds.height
      && Math.abs(state.radius - bounds.radius) < 0.01
    ) return;
    state.width = bounds.nodeWidth;
    state.height = bounds.nodeHeight;
    state.borderLeft = bounds.borderLeft;
    state.borderTop = bounds.borderTop;
    state.geometryX = bounds.x;
    state.geometryY = bounds.y;
    state.geometryWidth = bounds.width;
    state.geometryHeight = bounds.height;
    state.radius = bounds.radius;
    state.geometry = buildFloatingSwellPerimeter(
      bounds.width,
      bounds.height,
      bounds.radius,
      bounds.x,
      bounds.y
    );
    const padding = FLOATING_SWELL_BORDER_PADDING_PX;
    state.svg.setAttribute('viewBox', `${-padding} ${-padding} ${bounds.nodeWidth + padding * 2} ${bounds.nodeHeight + padding * 2}`);
    // Geometry/anchors use the border box; absolute children start at the padding
    // box. Percent sizes would shrink the SVG by the node's borders and distort
    // its viewBox, leaving the swell detached/inset, especially on thick frames.
    state.svg.style.left = `${-padding - bounds.borderLeft}px`;
    state.svg.style.top = `${-padding - bounds.borderTop}px`;
    state.svg.style.width = `${bounds.nodeWidth + padding * 2}px`;
    state.svg.style.height = `${bounds.nodeHeight + padding * 2}px`;
    state.paintRect.setAttribute('x', String(-padding));
    state.paintRect.setAttribute('y', String(-padding));
    state.paintRect.setAttribute('width', String(bounds.nodeWidth + padding * 2));
    state.paintRect.setAttribute('height', String(bounds.nodeHeight + padding * 2));
    state.innerRect.setAttribute('x', String(bounds.x));
    state.innerRect.setAttribute('y', String(bounds.y));
    state.innerRect.setAttribute('width', String(bounds.width));
    state.innerRect.setAttribute('height', String(bounds.height));
    state.innerRect.setAttribute('rx', String(bounds.radius));
    if (!Number.isFinite(state.position.value) || state.position.value < 0 || state.position.value >= state.geometry.length) {
      const initial = closestFloatingSwellSample(
        state.geometry.samples,
        bounds.x + bounds.width,
        bounds.y + bounds.height / 2
      ).sample;
      state.position.value = initial.s;
      state.position.target = initial.s;
      state.position.velocity = 0;
    } else {
      state.position.value = floatingSwellModulo(state.position.value, state.geometry.length);
      state.position.target = floatingSwellModulo(state.position.target, state.geometry.length);
    }
  }

    function ensureFloatingSwellState(nodeElement, floatingPort) {
    let state = nodeElement._floatingSwellState;
    if (!state) {
      const maskId = `desk-node-swell-mask-${String(nodeElement.dataset.nodeId || 'node').replace(/[^a-zA-Z0-9_-]/g, '-')}`;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.classList.add('desk-node-swell-border');
      svg.setAttribute('aria-hidden', 'true');
      svg.setAttribute('focusable', 'false');
      svg.innerHTML = `
        <defs>
          <mask id="${maskId}" maskUnits="userSpaceOnUse" mask-type="luminance">
            <path data-swell-mask-path fill="#ffffff"></path>
            <rect data-swell-inner fill="#000000"></rect>
          </mask>
        </defs>
        <rect class="desk-node-swell-border__paint" data-swell-paint mask="url(#${maskId})"></rect>
      `;
      nodeElement.insertBefore(svg, nodeElement.firstChild);
      state = {
        nodeElement,
        floatingPort,
        svg,
        maskPath: svg.querySelector('[data-swell-mask-path]'),
        innerRect: svg.querySelector('[data-swell-inner]'),
        paintRect: svg.querySelector('[data-swell-paint]'),
        geometry: null,
        width: 0,
        height: 0,
        geometryX: 0,
        geometryY: 0,
        geometryWidth: 0,
        geometryHeight: 0,
        radius: 0,
        amplitude: { value: 0, velocity: 0, target: 0 },
        position: { value: Number.NaN, velocity: 0, target: Number.NaN }
      };
      nodeElement._floatingSwellState = state;
      floatingSwellStates.add(state);
    } else {
      state.floatingPort = floatingPort;
    }
    updateFloatingSwellGeometry(state);
    return state;
  }

    function floatingSwellConnectionAnchor(node, side, anchorX, anchorY) {
    const scale = Math.max(0.01, Number(DesktopState.state.canvas.scale) || 1);
    const inward = FLOATING_SWELL_LINK_OVERLAP_SCREEN_PX / scale;
    const outward = portOutwardVector(side);
    return {
      x: node.x + anchorX - outward.x * inward,
      y: node.y + anchorY - outward.y * inward
    };
  }

    function syncFloatingDropletConnectionAnchor(state, side, anchorX, anchorY) {
    const nodeId = state.nodeElement.dataset.nodeId || '';
    const node = getNodeState(nodeId);
    if (!node) return;
    const worldAnchor = floatingSwellConnectionAnchor(node, side, anchorX, anchorY);
    if (
      activeInteractionRef.current?.type === 'connect'
      && activeInteractionRef.current.fromNodeId === nodeId
      && state.floatingPort.classList.contains('is-connecting')
    ) {
      activeInteractionRef.current.fromSide = side;
      activeInteractionRef.current.fromAnchor = worldAnchor;
      if (activeInteractionRef.current.pointer) {
        renderConnectionPreview(nodeId, activeInteractionRef.current.pointer, side, worldAnchor);
      }
    }
    if (
      contextMenuConnectionSourceIdRef.current === nodeId
      && contextMenuElRef.current?.classList.contains('is-open')
      && state.floatingPort.classList.contains('is-pending')
    ) {
      contextMenuConnectionSourceSideRef.current = side;
      contextMenuConnectionSourceAnchorRef.current = worldAnchor;
      refreshContextMenuConnectionPreview();
    }
  }

    function renderFloatingSwellState(state) {
    updateFloatingSwellGeometry(state);
    const geometry = state.geometry;
    if (!geometry?.samples?.length) return;
    const style = connectionSwellStyle();
    const amplitude = Math.max(0, Math.min(1, state.amplitude.value));
    const peak = amplitude * (style === 'droplet' ? FLOATING_DROPLET_PEAK_PX : FLOATING_SWELL_PEAK_PX);
    const located = floatingSwellPointAt(geometry, state.position.value).point;
    const droplet = style === 'droplet'
      ? buildFloatingDropletPath(geometry, state.position.value, peak, state.position.velocity)
      : null;
    const path = droplet?.path || buildFloatingSwellPath(geometry, state.position.value, peak);
    state.maskPath.setAttribute('d', path);
    const visible = state.amplitude.target > 0 || peak >= FLOATING_SWELL_VISIBLE_THRESHOLD_PX;
    state.nodeElement.classList.toggle('is-swell-visible', visible);
    state.nodeElement.dataset.connectionSwellStyle = style;
    const anchorX = droplet?.anchor?.x ?? (located.x + located.nx * FLOATING_SWELL_PEAK_PX);
    const anchorY = droplet?.anchor?.y ?? (located.y + located.ny * FLOATING_SWELL_PEAK_PX);
    const side = floatingSwellSide(located);
    state.floatingPort.dataset.portSide = side;
    state.floatingPort.dataset.anchorX = String(anchorX);
    state.floatingPort.dataset.anchorY = String(anchorY);
    state.floatingPort.style.setProperty('--desk-floating-x', `${anchorX - state.borderLeft}px`);
    state.floatingPort.style.setProperty('--desk-floating-y', `${anchorY - state.borderTop}px`);
    const sideLabel = { left: '左侧', right: '右侧', top: '上方', bottom: '下方' }[side];
    state.floatingPort.title = `从节点${sideLabel}创建连接`;
    state.floatingPort.setAttribute('aria-label', state.floatingPort.title);
    if (style === 'droplet') {
      syncFloatingDropletConnectionAnchor(state, side, anchorX, anchorY);
    }
  }

    function renderReducedMotionFloatingSwells() {
    if (floatingSwellFrameId) cancelAnimationFrame(floatingSwellFrameId);
    floatingSwellFrameId = 0;
    floatingSwellLastFrame = 0;
    floatingSwellStates.forEach(state => {
      if (!state.nodeElement.isConnected) {
        floatingSwellStates.delete(state);
        return;
      }
      state.amplitude.value = state.amplitude.target;
      state.amplitude.velocity = 0;
      if (Number.isFinite(state.position.target)) state.position.value = state.position.target;
      state.position.velocity = 0;
      renderFloatingSwellState(state);
    });
  }

    function animateFloatingSwells(timestamp) {
    floatingSwellFrameId = 0;
    if (prefersReducedMotion()) {
      renderReducedMotionFloatingSwells();
      return;
    }
    const deltaSeconds = floatingSwellLastFrame
      ? Math.min(FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS, Math.max(0, (timestamp - floatingSwellLastFrame) / 1000))
      : 1 / 60;
    floatingSwellLastFrame = timestamp;
    let moving = false;
    floatingSwellStates.forEach(state => {
      if (!state.nodeElement.isConnected) {
        floatingSwellStates.delete(state);
        return;
      }
      const restingHidden = state.amplitude.target === 0
        && state.amplitude.value < 0.001
        && Math.abs(state.amplitude.velocity) < 0.001
        && !state.nodeElement.classList.contains('is-swell-visible');
      if (restingHidden) return;
      floatingSwellSpringStep(state.amplitude, deltaSeconds);
      state.amplitude.value = Math.min(1, Math.max(0, state.amplitude.value));
      if ((state.amplitude.value === 0 && state.amplitude.velocity < 0)
        || (state.amplitude.value === 1 && state.amplitude.velocity > 0)) {
        state.amplitude.velocity = 0;
      }
      const originalTarget = state.position.target;
      const delta = floatingSwellShortestArcDelta(state.position.value, originalTarget, state.geometry.length);
      state.position.target = state.position.value + delta;
      floatingSwellSpringStep(state.position, deltaSeconds);
      state.position.value = floatingSwellModulo(state.position.value, state.geometry.length);
      state.position.target = originalTarget;
      renderFloatingSwellState(state);
      const positionMoving = Math.abs(floatingSwellShortestArcDelta(
        state.position.value,
        state.position.target,
        state.geometry.length
      )) >= 0.001 || Math.abs(state.position.velocity) >= 0.001;
      moving = moving || !floatingSwellSpringAtRest(state.amplitude) || positionMoving;
    });
    if (moving) {
      floatingSwellFrameId = requestAnimationFrame(animateFloatingSwells);
    } else {
      floatingSwellLastFrame = 0;
    }
  }

    function scheduleFloatingSwellFrame() {
    if (prefersReducedMotion()) {
      renderReducedMotionFloatingSwells();
      return;
    }
    if (!floatingSwellFrameId) floatingSwellFrameId = requestAnimationFrame(animateFloatingSwells);
  }

    function refreshFloatingSwellStyle() {
    floatingSwellStates.forEach(state => {
      if (state.nodeElement.isConnected) renderFloatingSwellState(state);
    });
    scheduleFloatingSwellFrame();
  }

    function setFloatingSwellTarget(state, sample, visible) {
    if (!state || !sample) return;
    if (visible && state.amplitude.value < 0.005 && state.amplitude.target === 0) {
      state.position.value = sample.s;
      state.position.velocity = 0;
    }
    state.position.target = sample.s;
    state.amplitude.target = visible ? 1 : 0;
    scheduleFloatingSwellFrame();
  }

    function releaseFloatingSwell(nodeElement) {
    const state = nodeElement?._floatingSwellState;
    if (!state) return;
    const held = state.floatingPort.classList.contains('is-connecting')
      || state.floatingPort.classList.contains('is-pending');
    if (!held) state.amplitude.target = 0;
    scheduleFloatingSwellFrame();
  }

    function holdFloatingSwell(floatingPort) {
    const nodeElement = floatingPort?.closest?.('.desk-node[data-node-id]');
    const state = nodeElement?._floatingSwellState;
    if (!state) return;
    if (!floatingPort.dataset.edgeHandle) {
      const side = normalizePortSide(floatingPort.dataset.portSide, 'right');
      const target = side === 'left'
        ? { x: 0, y: state.height / 2 }
        : { x: state.width, y: state.height / 2 };
      const sample = closestFloatingSwellSample(state.geometry.samples, target.x, target.y).sample;
      if (state.amplitude.value < 0.005) {
        state.position.value = sample.s;
        state.position.velocity = 0;
      }
      state.position.target = sample.s;
    }
    state.amplitude.target = 1;
    scheduleFloatingSwellFrame();
  }

    function discardFloatingSwellState(nodeElement) {
    discardConnectionFeedback?.(nodeElement);
    const state = nodeElement?._floatingSwellState;
    if (!state) return;
    floatingSwellStates.delete(state);
    delete nodeElement._floatingSwellState;
  }

    function ensureNodeEdgeHandles(nodeElement) {
    if (!nodeElement?.dataset?.nodeId) return;
    const nodeId = nodeElement.dataset.nodeId;
    // Remove the first implementation's fixed top/bottom handles if an already
    // mounted page is refreshed through hot replacement.
    nodeElement.querySelectorAll('.desk-port[data-edge-handle]:not(.desk-port--floating)').forEach(port => port.remove());
    const inputPorts = Array.from(nodeElement.querySelectorAll('.desk-port[data-port="in"]'));
    const outputPorts = Array.from(nodeElement.querySelectorAll('.desk-port[data-port="out"]:not([data-edge-handle])'));
    inputPorts.forEach(port => {
      port.dataset.portSide = normalizePortSide(port.dataset.portSide, 'left');
      port.dataset.semanticPort = 'true';
    });
    outputPorts.forEach(port => {
      port.dataset.portSide = normalizePortSide(port.dataset.portSide, 'right');
      port.dataset.semanticPort = 'true';
    });
    if (!inputPorts.length && !outputPorts.length) return;
    nodeElement.classList.add('desk-node--edge-handles');
    ['left', 'right'].forEach(side => {
      if (nodeElement.querySelector(`.desk-node-settled-port[data-settled-side="${side}"]`)) return;
      const settledPort = document.createElement('span');
      settledPort.className = `desk-node-settled-port desk-node-settled-port--${side}`;
      settledPort.dataset.settledSide = side;
      settledPort.setAttribute('aria-hidden', 'true');
      nodeElement.appendChild(settledPort);
    });
    if (!outputPorts.length) return;
    let floatingPort = nodeElement.querySelector('.desk-port--floating[data-edge-handle]');
    if (!floatingPort) {
      floatingPort = document.createElement('button');
      floatingPort.type = 'button';
      floatingPort.className = 'desk-port desk-port--floating';
      floatingPort.dataset.port = 'out';
      floatingPort.dataset.portSide = 'right';
      floatingPort.dataset.nodeId = nodeId;
      floatingPort.dataset.edgeHandle = 'true';
      floatingPort.title = '从节点边缘创建连接';
      floatingPort.setAttribute('aria-label', floatingPort.title);
      nodeElement.appendChild(floatingPort);
    }
    const state = ensureFloatingSwellState(nodeElement, floatingPort);
    renderFloatingSwellState(state);
  }

    function syncNodeEdgeStroke(nodeElement) {
    if (!nodeElement) return;
    nodeElement.style.setProperty('--desk-node-edge-stroke', 'var(--desk-node-selection-stroke)');
  }

    function clearFloatingConnectionPort(exceptNodeId = '') {
    document.querySelectorAll('.desk-node.is-port-proximity').forEach(nodeElement => {
      if (nodeElement.dataset.nodeId === exceptNodeId) return;
      nodeElement.classList.remove('is-port-proximity');
    });
    floatingSwellStates.forEach(state => {
      if (state.nodeElement.dataset.nodeId !== exceptNodeId) releaseFloatingSwell(state.nodeElement);
    });
  }

    function updateFloatingConnectionPort(clientX, clientY) {
    if (activeInteractionRef.current || contextMenuElRef.current?.classList.contains('is-open')) return;
    const viewportRect = els.deskCanvasViewport?.getBoundingClientRect();
    if (
      !viewportRect
      || clientX < viewportRect.left
      || clientX > viewportRect.right
      || clientY < viewportRect.top
      || clientY > viewportRect.bottom
    ) {
      clearFloatingConnectionPort();
      return;
    }
    let best = null;
    document.querySelectorAll('.desk-node--edge-handles[data-node-id]').forEach(nodeElement => {
      const floatingPort = nodeElement.querySelector('.desk-port--floating[data-edge-handle]');
      if (!floatingPort) return;
      const rect = nodeElement.getBoundingClientRect();
      if (
        clientX < rect.left - FLOATING_PORT_TRACKING_MARGIN_PX
        || clientX > rect.right + FLOATING_PORT_TRACKING_MARGIN_PX
        || clientY < rect.top - FLOATING_PORT_TRACKING_MARGIN_PX
        || clientY > rect.bottom + FLOATING_PORT_TRACKING_MARGIN_PX
      ) return;
      const localWidth = nodeElement.offsetWidth || 1;
      const localHeight = nodeElement.offsetHeight || 1;
      const state = ensureFloatingSwellState(nodeElement, floatingPort);
      const scaleX = rect.width / localWidth;
      const scaleY = rect.height / localHeight;
      const localX = (clientX - rect.left) / scaleX;
      const localY = (clientY - rect.top) / scaleY;
      const nearest = closestFloatingSwellSample(state.geometry.samples, localX, localY);
      const screenScale = Math.min(scaleX, scaleY);
      const outwardDistance = (localX - nearest.sample.x) * nearest.sample.nx
        + (localY - nearest.sample.y) * nearest.sample.ny;
      const edgeDepth = outwardDistance > 0
        ? FLOATING_SWELL_EDGE_OUTSET_PX
        : FLOATING_SWELL_EDGE_INSET_PX;
      if (nearest.distance * screenScale > edgeDepth) return;
      const screenDistance = nearest.distance * screenScale;
      if (!best || screenDistance < best.distance) {
        best = { nodeElement, floatingPort, state, sample: nearest.sample, distance: screenDistance };
      }
    });
    if (!best) {
      clearFloatingConnectionPort();
      return;
    }
    clearFloatingConnectionPort(best.nodeElement.dataset.nodeId);
    const { nodeElement, state, sample } = best;
    setFloatingSwellTarget(state, sample, true);
    syncNodeEdgeStroke(nodeElement);
    nodeElement.classList.add('is-port-proximity');
  }

    function getConnectionPortAnchor(nodeId, port, side = 'right') {
    const node = getNodeState(nodeId);
    if (!node || !port?.dataset?.edgeHandle) return getAnchor(nodeId, side);
    const anchorX = Number(port.dataset.anchorX);
    const anchorY = Number(port.dataset.anchorY);
    if (!Number.isFinite(anchorX) || !Number.isFinite(anchorY)) return getAnchor(nodeId, side);
    return floatingSwellConnectionAnchor(node, side, anchorX, anchorY);
  }

    return Object.freeze({
      connectionSwellStyle,
      floatingSwellBounds,
      updateFloatingSwellGeometry,
      ensureFloatingSwellState,
      floatingSwellConnectionAnchor,
      syncFloatingDropletConnectionAnchor,
      renderFloatingSwellState,
      renderReducedMotionFloatingSwells,
      animateFloatingSwells,
      scheduleFloatingSwellFrame,
      refreshFloatingSwellStyle,
      setFloatingSwellTarget,
      releaseFloatingSwell,
      holdFloatingSwell,
      discardFloatingSwellState,
      ensureNodeEdgeHandles,
      syncNodeEdgeStroke,
      clearFloatingConnectionPort,
      updateFloatingConnectionPort,
      getConnectionPortAnchor,
    });
  }

  window.DesktopCanvasPortInteraction = Object.freeze({ create });
})();
