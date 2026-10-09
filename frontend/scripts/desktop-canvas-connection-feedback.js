// Transient connection presentation only. No graph mutations or persistence.
// Connections supplies the nearest valid port, successful manual commits and
// targeted edge geometry; the host wires node disposal. Load before the host.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const RECOIL_MS = 300;
  const CONFIRM_MS = 480;
  const ARC_POSE_MS = 80;
  const ARC_SEGMENTS = 8;
  const ZERO = Object.freeze({ x: 0, y: 0 });
  let effectId = 0;

  function arcNoise(index, pose) {
    // Deterministic key poses: fast angular motion without frame-rate-dependent
    // random jumps, separate timers, or opacity flashes.
    const seed = Math.sin((index + 1) * 12.9898 + (pose + 1) * 78.233) * 43758.5453;
    return (seed - Math.floor(seed)) * 2 - 1;
  }

  function impactDirection(approach) {
    if (!Number.isFinite(approach?.x) || !Number.isFinite(approach?.y) || approach.x <= 0) return { x: 1, y: 0 };
    // The settled input faces left. Preserve approach slope but keep the inward
    // normal dominant for grazing/body drops; no rotation or saved-coordinate edits.
    const slope = Math.max(-0.4, Math.min(0.4, approach.y / approach.x));
    const length = Math.hypot(1, slope);
    return { x: 1 / length, y: slope / length };
  }

  function create({ activeInteractionRef, getNodeState, getNodeElement,
    getEdgeVisualPath, refreshNodeConnectionGeometry, prefersReducedMotion }) {
    let proximity = null, impact = null, frameId = 0, listening = false;
    const motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const svgElement = (name, attrs = {}) => {
      const el = document.createElementNS(NS, name);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
      return el;
    };
    const onVisibility = () => { if (document.hidden) clear(); };
    const onMotion = () => clear();
    // Any new manipulation takes precedence over a still-playing confirmation.
    const onPointerDown = () => clearImpact();
    const onKeyDown = event => { if (event.key === 'Escape') clear(); };

    function syncLifecycle() {
      const needed = Boolean(proximity || impact);
      if (needed === listening) return;
      listening = needed;
      const method = needed ? 'addEventListener' : 'removeEventListener';
      document[method]('visibilitychange', onVisibility);
      window[method]('blur', clear);
      window[method]('pagehide', clear);
      window[method]('pointerdown', onPointerDown, true);
      window[method]('keydown', onKeyDown, true);
      motionQuery?.[method]('change', onMotion);
      if (!needed && frameId) { cancelAnimationFrame(frameId); frameId = 0; }
    }

    function makeOverlay(nodeElement, className) {
      const width = nodeElement.offsetWidth, height = nodeElement.offsetHeight;
      const root = svgElement('svg', { class: className, 'aria-hidden': 'true',
        width, height, viewBox: `0 0 ${width} ${height}` });
      root.style.left = `${-nodeElement.clientLeft}px`;
      root.style.top = `${-nodeElement.clientTop}px`;
      nodeElement.appendChild(root);
      return root;
    }

    function clearProximity() {
      proximity?.root.remove();
      proximity = null;
      syncLifecycle();
    }

    function clearImpact() {
      const state = impact;
      if (!state) return;
      impact = null; // Offset must resolve to zero before restoring attached wires.
      clearTimeout(state.timer);
      state.animations.forEach(animation => animation.cancel());
      state.nodeElement.style.translate = state.originalTranslate;
      state.root.remove();
      state.wire?.remove();
      refreshNodeConnectionGeometry(state.nodeId);
      syncLifecycle();
    }

    function clear() { clearProximity(); clearImpact(); }
    function discardNode(nodeElement) {
      const id = nodeElement?.dataset.nodeId;
      if (proximity && (proximity.nodeElement === nodeElement || proximity.fromNodeId === id)) clearProximity();
      if (impact && (impact.nodeElement === nodeElement || impact.fromNodeId === id)) clearImpact();
    }
    function getNodeVisualOffset(nodeId) { return impact?.nodeId === nodeId ? impact.offset : ZERO; }
    function schedule() { if (!frameId) frameId = requestAnimationFrame(frame); }

    function drawArc(state, timestamp) {
      const { anchor, pointer } = state;
      const dx = anchor.x - pointer.x, dy = anchor.y - pointer.y;
      const length = Math.hypot(dx, dy) || 1;
      const settling = state.phase === 'snapped';
      const settle = settling ? Math.max(0, 1 - (timestamp - state.snappedAt) / 100) : 1;
      const amplitude = (2.2 + 4 * state.strength) * settle;
      const phase = Math.max(0, timestamp - state.started) / ARC_POSE_MS;
      const pose = Math.floor(phase), fraction = phase - pose;
      const blend = fraction * fraction * (3 - 2 * fraction);
      const points = Array.from({ length: ARC_SEGMENTS + 1 }, (_, index) => {
        const t = index / ARC_SEGMENTS;
        // Sparse bends read as an arc, with continuous interpolation between
        // 80ms key poses. The envelope pins both ends to the free tip and port.
        const shape = arcNoise(index, pose) * (1 - blend) + arcNoise(index, pose + 1) * blend;
        const wave = Math.sin(Math.PI * t) * shape * amplitude;
        return `${index ? 'L' : 'M'} ${(pointer.x + dx * t - dy / length * wave).toFixed(3)} ${(pointer.y + dy * t + dx / length * wave).toFixed(3)}`;
      });
      const d = points.join(' ');
      state.layers.forEach(layer => layer.setAttribute('d', d));
      state.arc.style.opacity = String(settle);
      return !settling || settle > 0;
    }

    function updateProximity(target) {
      const interaction = activeInteractionRef.current;
      if (!target || document.hidden || interaction?.type !== 'connect'
        || !getNodeState(interaction.fromNodeId) || !target.port.isConnected || !target.nodeElement.isConnected) {
        clearProximity(); return;
      }
      const { nodeElement, port, rect } = target;
      const scale = rect.width / port.offsetWidth;
      if (!(scale > 0 && Number.isFinite(scale))) { clearProximity(); return; }
      if (proximity?.port !== port) {
        clearProximity();
        const root = makeOverlay(nodeElement, 'desk-connection-proximity');
        const arc = svgElement('g', { class: 'desk-connection-proximity__arc' });
        const layers = ['halo', 'wave', 'core'].map(layer => svgElement('path', { class: `desk-connection-proximity__${layer}` }));
        layers.forEach(layer => arc.appendChild(layer));
        const ring = svgElement('ellipse', { class: 'desk-connection-proximity__ring', rx: 4, ry: 9 });
        root.appendChild(arc); root.appendChild(ring);
        proximity = { root, arc, layers, ring, nodeElement, port, fromNodeId: interaction.fromNodeId,
          started: performance.now(), phase: '', strength: 0 };
        syncLifecycle();
      }
      const state = proximity, nodeRect = nodeElement.getBoundingClientRect();
      const x = target.side === 'right' ? rect.right : target.side === 'left' ? rect.left : (rect.left + rect.right) / 2;
      const y = target.side === 'top' ? rect.top : target.side === 'bottom' ? rect.bottom : (rect.top + rect.bottom) / 2;
      state.anchor = { x: (x - nodeRect.left) / scale, y: (y - nodeRect.top) / scale };
      // Keep the last free tip during the short snap-settling phase.
      if (target.phase !== 'snapped' || !state.pointer) {
        state.pointer = { x: (target.pointer.x - nodeRect.left) / scale, y: (target.pointer.y - nodeRect.top) / scale };
        state.strength = target.strength;
      }
      if (target.phase === 'snapped' && state.phase !== 'snapped') state.snappedAt = performance.now();
      state.phase = target.phase;
      state.root.dataset.phase = state.phase;
      state.ring.setAttribute('cx', state.anchor.x); state.ring.setAttribute('cy', state.anchor.y);
      if (prefersReducedMotion()) {
        state.arc.style.opacity = '0'; // Static port highlight; magnetic capture is unchanged.
      } else if (drawArc(state, performance.now())) schedule();
    }

    function playCommit({ edgeId, fromNodeId, toNodeId, approach }) {
      clear();
      const nodeElement = getNodeElement(toNodeId), node = getNodeState(toNodeId);
      const path = getEdgeVisualPath(edgeId);
      if (document.hidden || !node || !nodeElement?.isConnected || !path?.isConnected) return;
      const reduced = prefersReducedMotion();
      const root = makeOverlay(nodeElement, 'desk-connection-impact');
      const width = nodeElement.offsetWidth, height = nodeElement.offsetHeight;
      const radius = Math.min(width / 2, height / 2, parseFloat(getComputedStyle(nodeElement).borderTopLeftRadius) || 8);
      const ring = svgElement('ellipse', { class: 'desk-connection-impact__ring', cx: 0, cy: height / 2, rx: 5, ry: 10 });
      root.appendChild(ring);
      const state = { nodeId: toNodeId, fromNodeId, edgeId, nodeElement, node, root, offset: ZERO, direction: impactDirection(approach),
        originalTranslate: nodeElement.style.translate, animations: [], timer: 0, started: performance.now() };
      impact = state;
      syncLifecycle();
      if (reduced || typeof root.animate !== 'function') {
        state.timer = setTimeout(clearImpact, 220);
        return;
      }
      // Local radial bloom + layered strokes emulate a soft light tail without
      // filtering the node/controls or allocating a node-sized blur surface.
      const gradientId = `desk-connection-bloom-${++effectId}`;
      const defs = svgElement('defs');
      const gradient = svgElement('radialGradient', { id: gradientId });
      for (const [offset, opacity] of [[0, 0.34], [0.38, 0.14], [1, 0]]) {
        gradient.appendChild(svgElement('stop', { offset, 'stop-color': 'currentColor', 'stop-opacity': opacity }));
      }
      defs.appendChild(gradient); root.appendChild(defs);
      const bloom = svgElement('ellipse', { class: 'desk-connection-impact__bloom', cx: 0, cy: height / 2,
        rx: 38, ry: 42, fill: `url(#${gradientId})`, stroke: 'none' });
      bloom.style.transformOrigin = `0px ${height / 2}px`;
      root.appendChild(bloom);
      state.animations.push(bloom.animate([
        { transform: 'scale(.55)', opacity: 0.7 },
        { transform: 'scale(1)', opacity: 1, offset: 0.17 },
        { transform: 'scale(1.2)', opacity: 0 }
      ], { duration: RECOIL_MS, easing: 'ease-out', fill: 'forwards' }));
      const top = `M 0 ${height / 2} L 0 ${radius} Q 0 0 ${radius} 0 L ${width - radius} 0 Q ${width} 0 ${width} ${radius} L ${width} ${height / 2}`;
      const bottom = `M 0 ${height / 2} L 0 ${height - radius} Q 0 ${height} ${radius} ${height} L ${width - radius} ${height} Q ${width} ${height} ${width} ${height - radius} L ${width} ${height / 2}`;
      for (const d of [top, bottom]) {
        for (const [layer, width, length, opacity] of [
          ['halo', 12, 0.10, 0.08], ['tail', 4, 0.12, 0.22], ['core', 1.6, 0.045, 0.9]
        ]) {
          const wave = svgElement('path', { class: `desk-connection-impact__wave desk-connection-impact__wave--${layer}`,
            d, pathLength: 1, 'stroke-width': width, 'stroke-dasharray': `${length} 2` });
          root.appendChild(wave);
          // Each layer has the same leading edge, with a softer/longer tail.
          // A gap longer than the path prevents a second dash flashing at its end.
          state.animations.push(wave.animate([
            { strokeDashoffset: String(length), opacity },
            { opacity, offset: 0.1 },
            { opacity: opacity * 0.55, offset: 0.42 },
            { strokeDashoffset: String(length - 1.1), opacity: 0 }
          ], { duration: CONFIRM_MS, easing: 'linear', fill: 'forwards' }));
        }
      }
      ring.style.transformOrigin = `0px ${height / 2}px`;
      state.animations.push(ring.animate([
        { transform: 'scale(.7)', opacity: 0.8 }, { transform: 'scale(2)', opacity: 0 }
      ], { duration: RECOIL_MS, easing: 'ease-out', fill: 'forwards' }));
      state.wire = svgElement('path', { class: 'desk-connection-commit-wire', d: path.getAttribute('d') });
      path.parentNode.appendChild(state.wire);
      state.animations.push(state.wire.animate([{ opacity: 0.75 }, { opacity: 0 }], { duration: RECOIL_MS, fill: 'forwards' }));
      state.timer = setTimeout(clearImpact, CONFIRM_MS);
      // Contact lights immediately; position is continuous at t=0. The first RAF
      // already has outward velocity, not a delayed ease-in or an instant 3px jump.
      renderRecoil(state, 0);
      schedule();
    }

    function renderRecoil(state, t) {
      // Damped impulse: ~5.5px at 51ms, one <1px return overshoot, C1 taper
      // to exact rest at 300ms. No frame-rate-dependent integration or mutation.
      const tail = Math.max(0, Math.min(1, (t - 0.55) / 0.45));
      const taper = 1 - tail * tail * (3 - 2 * tail);
      const distance = t < 1 ? 11.4 * Math.exp(-3.5 * t) * Math.sin(2 * Math.PI * t) * taper : 0;
      const x = distance * state.direction.x || 0, y = distance * state.direction.y || 0;
      state.offset = { x, y };
      state.nodeElement.style.translate = t < 1 ? `${x}px ${y}px` : state.originalTranslate;
      refreshNodeConnectionGeometry(state.nodeId);
      const path = getEdgeVisualPath(state.edgeId);
      if (path && state.wire?.isConnected) state.wire.setAttribute('d', path.getAttribute('d'));
      return t < 1;
    }

    function frame(timestamp) {
      frameId = 0;
      let moving = false;
      if (proximity) {
        const state = proximity;
        if (!state.root.isConnected || !state.nodeElement.isConnected || !state.port.isConnected || state.port.disabled || state.port.hidden
          || !getNodeState(state.fromNodeId) || activeInteractionRef.current?.type !== 'connect'
          || !state.nodeElement.classList.contains('is-compatible-target')) clearProximity();
        else if (!prefersReducedMotion()) moving = drawArc(state, timestamp);
      }
      if (impact) {
        const state = impact;
        if (!state.root.isConnected || !state.nodeElement.isConnected || getNodeState(state.nodeId) !== state.node
          || !getNodeState(state.fromNodeId) || !getEdgeVisualPath(state.edgeId)?.isConnected) clearImpact();
        else {
          const t = Math.min(1, Math.max(0, (timestamp - state.started) / RECOIL_MS));
          moving = renderRecoil(state, t) || moving;
        }
      }
      if (moving) schedule();
    }

    return Object.freeze({ updateProximity, clearProximity, playCommit, clear, discardNode, getNodeVisualOffset });
  }
  window.DesktopCanvasConnectionFeedback = Object.freeze({ create });
})();
