// Local drag avoidance: geometry plus a short-lived animation session.
// No storage/DOM globals; the host injects live state, layout, frames and persistence.
(function () {
  const GAP = 24;
  const EPSILON = 0.01;
  const SETTLE_DISTANCE = 0.25;
  const FOLLOW_TIME_MS = 65;

  function overlaps(a, b, gap) {
    return a.x < b.x + b.width + gap - EPSILON
      && a.x + a.width > b.x - gap + EPSILON
      && a.y < b.y + b.height + gap - EPSILON
      && a.y + a.height > b.y - gap + EPSILON;
  }

  function separation(a, b, side, gap) {
    if (side === 'right') return { x: a.x + a.width + gap - b.x, y: 0 };
    if (side === 'left') return { x: a.x - gap - b.width - b.x, y: 0 };
    if (side === 'bottom') return { x: 0, y: a.y + a.height + gap - b.y };
    return { x: 0, y: a.y - gap - b.height - b.y };
  }

  function chooseSide(a, b, delta, previous, gap) {
    const preferred = Math.abs(delta.x) >= Math.abs(delta.y)
      ? (delta.x < 0 ? 'left' : 'right') : (delta.y < 0 ? 'top' : 'bottom');
    return ['right', 'left', 'bottom', 'top'].map(side => {
      const move = separation(a, b, side, gap);
      const weight = (side === preferred ? 0.8 : 1) * (side === previous ? 0.85 : 1);
      return { side, cost: (Math.abs(move.x) + Math.abs(move.y)) * weight };
    }).sort((a, b) => a.cost - b.cost)[0].side;
  }

  // Place passive bodies after pinned drag roots. A body only moves relative to
  // already placed obstacles, in one direction per solve: finite, no push-back loop.
  // Unaffected existing overlaps are deliberately not globally reflowed.
  function solve(rects, movingIds, options = {}) {
    const moving = new Set(movingIds);
    const exempt = new Set(options.exemptIds || []);
    const gap = options.gap ?? GAP;
    const delta = options.delta || { x: 0, y: 0 };
    const directions = new Map(options.directions || []);
    const groups = new Map();
    const roots = [];
    const positions = new Map();
    for (const rect of rects) {
      if (![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) || rect.width <= 0 || rect.height <= 0) continue;
      if (moving.has(rect.id)) {
        roots.push({ ...rect, active: true, moved: false });
        continue;
      }
      const key = rect.groupId ? `group:${rect.groupId}` : `node:${rect.id}`;
      const body = groups.get(key) || { key, members: [], exempt: false };
      body.members.push(rect);
      body.exempt ||= exempt.has(rect.id);
      groups.set(key, body);
    }
    const bodies = Array.from(groups.values()).map(body => {
      const x = Math.min(...body.members.map(r => r.x));
      const y = Math.min(...body.members.map(r => r.y));
      return { ...body, x, y, startX: x, startY: y,
        width: Math.max(...body.members.map(r => r.x + r.width)) - x,
        height: Math.max(...body.members.map(r => r.y + r.height)) - y,
        active: false, moved: false };
    });
    const horizontal = Math.abs(delta.x) >= Math.abs(delta.y);
    const sign = (horizontal ? delta.x : delta.y) < 0 ? -1 : 1;
    const score = body => sign * (horizontal ? body.x + body.width / 2 : body.y + body.height / 2);
    bodies.sort((a, b) => score(a) - score(b) || a.key.localeCompare(b.key));
    // Merge candidates are stationary obstacles for other pushed bodies, but may
    // intentionally overlap a dragged image. They never initiate a collision chain.
    const placed = [...roots, ...bodies.filter(body => body.exempt)];
    for (const body of bodies) {
      if (body.exempt) continue;
      let side = null;
      for (let pass = 0; pass <= placed.length; pass++) {
        const obstacle = placed.find(other => (body.moved || other.active || other.moved)
          && overlaps(other, body, gap));
        if (!obstacle) break;
        side ||= chooseSide(obstacle, body, delta, directions.get(body.key), gap);
        const offset = separation(obstacle, body, side, gap);
        body.x += offset.x;
        body.y += offset.y;
        body.moved = true;
      }
      if (body.moved) {
        directions.set(body.key, side);
        body.members.forEach(member => positions.set(member.id, {
          x: member.x + body.x - body.startX, y: member.y + body.y - body.startY
        }));
      }
      placed.push(body);
    }
    return { positions, directions };
  }

  function create({ getCanvas, isEnabled, getBounds, applyLayout, renderGraph,
    save, requestFrame, cancelFrame, reducedMotion }) {
    let session = null;
    let frameId = null;

    function valid() {
      if (!session) return false;
      if (getCanvas() !== session.canvas) {
        cancel();
        return false;
      }
      return true;
    }

    function cancel() {
      if (frameId !== null) cancelFrame(frameId);
      frameId = null;
      session = null;
    }

    function nodeFor(id) {
      const node = getCanvas().nodes[id];
      return node && node === session.originals.get(id)?.node ? node : null;
    }

    function remember(id, node) {
      if (session.originals.has(id)) return;
      const bounds = getBounds(id);
      session.originals.set(id, { node, x: node.x, y: node.y,
        width: bounds?.width || node.width, height: bounds?.height || node.height });
    }

    function hasPending() {
      return Array.from(session.targets).some(([id, target]) => {
        const node = nodeFor(id);
        return node && (Math.abs(target.x - node.x) > EPSILON || Math.abs(target.y - node.y) > EPSILON);
      });
    }

    function applyTargets(alpha) {
      let changed = false;
      for (const [id, target] of session.targets) {
        const node = nodeFor(id);
        if (!node || session.moving.has(id)) continue;
        const dx = target.x - node.x, dy = target.y - node.y;
        if (!dx && !dy) continue;
        const close = Math.hypot(dx, dy) < SETTLE_DISTANCE;
        node.x = close ? target.x : node.x + dx * alpha;
        node.y = close ? target.y : node.y + dy * alpha;
        applyLayout(id);
        changed = true;
      }
      if (changed) renderGraph();
    }

    function tick(now) {
      frameId = null;
      if (!valid()) return;
      const dt = session.lastTime == null ? 16.67 : Math.max(1, Math.min(64, now - session.lastTime));
      session.lastTime = now;
      applyTargets(reducedMotion() ? 1 : 1 - Math.exp(-dt / FOLLOW_TIME_MS));
      if (hasPending()) schedule();
      else if (session.ending) {
        cancel();
        save();
      }
    }

    function schedule(resetClock = false) {
      if (frameId !== null) return;
      if (resetClock) session.lastTime = null;
      frameId = requestFrame(tick);
    }

    function settle() {
      if (!valid()) return;
      const shouldSave = session.ending;
      applyTargets(1);
      cancel();
      if (shouldSave) save();
    }

    function begin(interaction) {
      settle();
      if (!isEnabled() || interaction?.type !== 'node-drag') return;
      session = { canvas: getCanvas(), moving: new Set(interaction.groupIds || [interaction.nodeId]),
        originals: new Map(), targets: new Map(), displaced: new Set(), directions: new Map(),
        lastTime: null, ending: false, last: { x: interaction.nodeX, y: interaction.nodeY } };
      Object.entries(getCanvas().nodes).forEach(([id, node]) => remember(id, node));
      // A preference can be enabled during a drag: cancellation still restores its start.
      for (const id of session.moving) {
        const original = session.originals.get(id), base = interaction.nodePositions?.[id];
        if (original && base) Object.assign(original, base);
      }
    }

    function update(interaction, options = {}) {
      if (!isEnabled()) { settle(); return; }
      if (!valid()) begin(interaction);
      if (!valid() || session.ending) return;
      const source = nodeFor(interaction.nodeId);
      if (!source) { cancel(); return; }
      const delta = { x: source.x - session.last.x, y: source.y - session.last.y };
      session.last = { x: source.x, y: source.y };
      if (Math.abs(delta.x) + Math.abs(delta.y) < EPSILON) return;
      const exempt = getCanvas().nodes[options.exemptNodeId];
      const exemptIds = Object.keys(getCanvas().nodes).filter(id => id === options.exemptNodeId
        || (exempt?.groupId && getCanvas().nodes[id].groupId === exempt.groupId));
      exemptIds.forEach(id => session.targets.delete(id));
      const rects = Object.entries(getCanvas().nodes).map(([id, node]) => {
        remember(id, node);
        const original = session.originals.get(id);
        const position = session.moving.has(id) ? node : session.targets.get(id) || node;
        return { id, x: position.x, y: position.y, width: original.width, height: original.height, groupId: node.groupId };
      });
      const result = solve(rects, session.moving, { delta, exemptIds, directions: session.directions });
      session.directions = result.directions;
      for (const [id, target] of result.positions) {
        session.targets.set(id, target);
        session.displaced.add(id);
      }
      if (hasPending()) schedule(true);
    }

    // true means this controller owns the final save after its animation finishes.
    function end({ cancelled = false, immediate = false } = {}) {
      if (!valid()) return false;
      if (cancelled) {
        for (const id of new Set([...session.moving, ...session.displaced])) {
          const node = nodeFor(id), original = session.originals.get(id);
          if (!node || !original) continue;
          node.x = original.x; node.y = original.y;
          applyLayout(id);
        }
        cancel();
        renderGraph();
        return false;
      }
      if (immediate) { settle(); return false; }
      session.ending = true;
      if (!hasPending()) { cancel(); return false; }
      schedule();
      return true;
    }

    function displacedIds() {
      return valid() ? Array.from(session.displaced) : [];
    }

    return Object.freeze({ begin, update, end, settle, cancel, displacedIds });
  }

  window.DesktopCanvasCollision = Object.freeze({ solve, create });
})();
