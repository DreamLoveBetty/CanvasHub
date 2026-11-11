// Running links: while a node shows in-flight progress, every link into or out of it
// carries a dashed flow drawn over the link path, moving from source to target.
// Owns only the set of running node ids. The progress view reports which elements
// hold running progress; the connection renderer asks which edges flow and draws
// the overlay through overlayMarkup(). Each redraw restarts CSS animations, so the
// overlay gets a negative delay that keeps the dash phase on one shared clock.
(function () {
  'use strict';

  // Must match the animation-duration of .desk-link-flow (desktop-canvas-nodes-geometry.css).
  const CYCLE_MS = 700;

  function create({ requestRender, requestFrame = callback => requestAnimationFrame(callback),
    now = () => performance.now() }) {
    let running = new Set();
    let frame = 0;

    function scheduleRender() {
      if (frame) return;
      frame = requestFrame(() => { frame = 0; requestRender(); });
    }

    function nodeIdOf(element) {
      return element?.closest?.('.desk-node[data-node-id]')?.dataset.nodeId || '';
    }

    // owners: the elements whose progress is running (a node or something inside one).
    function setRunningOwners(owners) {
      const next = new Set();
      for (const owner of owners || []) {
        const id = nodeIdOf(owner);
        if (id) next.add(id);
      }
      if (next.size === running.size && [...next].every(id => running.has(id))) return;
      running = next;
      scheduleRender();
    }

    function isFlowing(edge) {
      return Boolean(edge) && (running.has(edge.from) || running.has(edge.to));
    }

    function phaseDelay() {
      return `-${Math.round(now() % CYCLE_MS)}ms`;
    }

    function overlayMarkup(edge, d, escapeHtml) {
      if (!isFlowing(edge)) return '';
      return `<path class="desk-link-flow" data-edge-id="${escapeHtml(edge.id)}" d="${d}" style="animation-delay:${phaseDelay()}"></path>`;
    }

    return Object.freeze({
      setRunningOwners,
      isFlowing,
      overlayMarkup,
      runningNodeIds: () => new Set(running),
    });
  }

  window.DesktopCanvasLinkFlow = Object.freeze({ create, CYCLE_MS });
})();
