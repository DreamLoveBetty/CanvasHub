// Graphite connection geometry: every node side that carries links grows ONE low port
// plate (concave fillet into the card, rounded outer corners) spanning all of its ports;
// ports sit evenly spaced on the plate, lean toward the nodes they connect to, and pick
// the facing sides of the two nodes. Pure functions: the connections controller asks for a
// layout only while the graphite style is on and owns all DOM writes.
(function () {
  const PIPE_HALF = 4;        // half of the 8px graphite pipe
  const CARD_RADIUS = 14;
  const PLATE = Object.freeze({ depth: 9, base: 5, corner: 4, pad: 7 });
  const NECK = 4;             // fillet where a pipe leaves the plate face
  const PORT_GAP = 24;        // distance between neighbouring ports on one plate
  const STRAIGHT_SNAP = 36;   // a near-level single port snaps level so its pipe runs straight
  const MIN_HORIZONTAL_GAP = 60; // room for two 30px connection leads
  const OPPOSITE = Object.freeze({ right: 'left', left: 'right', top: 'bottom', bottom: 'top' });
  const EASE_SLIDE_MS = 90;   // time constant for ports sliding along a side
  const EASE_GROW_MS = 110;   // time constant for a plate growing on / shrinking off a side
  const SETTLED_PX = 0.2;
  // Bottom-right cut-out around a generate node's 72px key; the graphite stylesheet
  // cuts the same nodes (keep NOTCHED_NODES in step with desktop-graphite.css).
  const NOTCH = Object.freeze({ w: 88, h: 88, r: 12 });
  const NOTCHED_NODES = '.desk-node--input, .desk-node--krea2, .desk-node--moss, .desk-node--qwen21, '
    + '.desk-node--topaz, .desk-node--pose, .desk-node--topaz-video, .desk-node--video-control, .desk-node--comfy';
  const notchOf = element => (element?.matches?.(NOTCHED_NODES) ? NOTCH : null);

  const isHorizontal = side => side === 'left' || side === 'right';
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const num = value => Number(value) || 0;

  function rectOf(geometry) {
    return { x: num(geometry?.x), y: num(geometry?.y), w: num(geometry?.width), h: num(geometry?.height) };
  }

  // Facing sides of two rectangles: left/right while there is room for a horizontal
  // run, top/bottom only once the nodes (nearly) stack.
  function facingSides(a, b) {
    const right = b.x - (a.x + a.w), left = a.x - (b.x + b.w);
    const down = b.y - (a.y + a.h), up = a.y - (b.y + b.h);
    const horizontal = Math.max(right, left), vertical = Math.max(down, up);
    const side = horizontal >= MIN_HORIZONTAL_GAP || vertical <= 0 || horizontal >= vertical
      ? (right >= left ? 'right' : 'left')
      : (down >= up ? 'bottom' : 'top');
    return [side, OPPOSITE[side]];
  }

  // Usable range of port centres along one side; `notch` reserves a bottom-right cut-out.
  function edgeRange(rect, side, notch) {
    const pad = CARD_RADIUS + PLATE.base + PLATE.pad + PIPE_HALF + 2;
    const notchPad = notch ? notch.r + PLATE.base + PLATE.pad + PIPE_HALF + 2 : 0;
    if (isHorizontal(side)) {
      const max = notch && side === 'right' ? rect.y + rect.h - notch.h - notchPad : rect.y + rect.h - pad;
      return { min: rect.y + pad, max: Math.max(rect.y + pad, max) };
    }
    const max = notch && side === 'bottom' ? rect.x + rect.w - notch.w - notchPad : rect.x + rect.w - pad;
    return { min: rect.x + pad, max: Math.max(rect.x + pad, max) };
  }

  // Maps (out, along) in a side's local frame to world coordinates; mirrored frames flip arc sweeps.
  function frameOf(rect, side) {
    if (side === 'right') return { at: (o, a) => [rect.x + rect.w + o, a], flip: false };
    if (side === 'left') return { at: (o, a) => [rect.x - o, a], flip: true };
    if (side === 'bottom') return { at: (o, a) => [a, rect.y + rect.h + o], flip: true };
    return { at: (o, a) => [a, rect.y - o], flip: false };
  }
  const point = ([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`;
  const arc = (frame, r, sweep, o, a) => ` A${r},${r} 0 0 ${frame.flip ? 1 - sweep : sweep} ${point(frame.at(o, a))}`;

  // Plate spanning [from, to] along the edge; `amount` (0..1) grows it out of the card.
  function platePath(frame, from, to, amount = 1) {
    const depth = PLATE.depth * amount, base = PLATE.base * amount;
    const corner = Math.min(PLATE.corner, depth / 2);
    const f = frame.at;
    return `M${point(f(-3, from - base))} L${point(f(0, from - base))}${arc(frame, base, 0, base, from)}`
      + ` L${point(f(depth - corner, from))}${arc(frame, corner, 1, depth, from + corner)}`
      + ` L${point(f(depth, to - corner))}${arc(frame, corner, 1, depth - corner, to)}`
      + ` L${point(f(base, to))}${arc(frame, base, 0, 0, to + base)}`
      + ` L${point(f(-3, to + base))} Z`;
  }

  // Small concave fillet where a pipe leaves the plate face.
  function neckPath(frame, along, amount = 1) {
    const out = PLATE.depth * amount, r = NECK * amount, w = PIPE_HALF, f = frame.at;
    return `M${point(f(out - 2, along - w - r))} L${point(f(out, along - w - r))}${arc(frame, r, 0, out + r, along - w)}`
      + ` L${point(f(out + r, along + w))}${arc(frame, r, 0, out, along + w + r)}`
      + ` L${point(f(out - 2, along + w + r))} Z`;
  }

  // Pointer target over a plate spanning [from, to], in the node's local px.
  function plateHit(rect, side, from, to) {
    const inside = 4, outside = PLATE.depth + 6;
    if (side === 'right') return { x: rect.w - inside, y: from - rect.y, w: inside + outside, h: to - from };
    if (side === 'left') return { x: -outside, y: from - rect.y, w: inside + outside, h: to - from };
    if (side === 'bottom') return { x: from - rect.x, y: rect.h - inside, w: to - from, h: inside + outside };
    return { x: from - rect.x, y: -outside, w: to - from, h: inside + outside };
  }

  /** Easing state for layout(); keep one per link layer and drop it to snap. */
  function createMotion() {
    return { time: 0, ends: new Map(), groups: new Map() };
  }

  /**
   * One plate on one side, for transient feedback (hover swell, connection drag).
   * `rect` is {x, y, w, h}; `along` is clamped to the side's usable range.
   * @returns {{ path: string, face: {x:number,y:number}, along: number }}
   */
  function edgePlate(rect, side, along, amount = 1, notch = null) {
    const range = edgeRange(rect, side, notch);
    const at = clamp(along, range.min, range.max);
    const frame = frameOf(rect, side);
    const [x, y] = frame.at(PLATE.depth * amount, at);
    const half = PIPE_HALF + PLATE.pad;
    return { path: amount > 0 ? platePath(frame, at - half, at + half, amount) : '', face: { x, y }, along: at };
  }

  /**
   * @param {Array<{id:string, from:string, to:string}>} edges
   * @param {(nodeId:string) => {x:number,y:number,width:number,height:number}} geometryOf
   * @param {(nodeId:string) => ({w:number,h:number,r:number}|null)} [notchOf]
   * @param {ReturnType<createMotion>|null} [motion] eases ports and plates toward this layout
   * @param {number} [now] timestamp in ms for `motion`
   * @returns {{ routes: Map<string,{from:{x,y},to:{x,y},fromSide:string,toSide:string}>, plates: string,
   *   ports: Map<string, Array<{side:string, incoming:number, hit:{x,y,w,h}}>>, settled: boolean }}
   */
  function layout(edges = [], geometryOf, notchOf = () => null, motion = null, now = 0) {
    const rects = new Map();
    const rect = id => {
      if (!rects.has(id)) rects.set(id, rectOf(geometryOf(id)));
      return rects.get(id);
    };
    const notches = new Map();
    const notch = id => {
      if (!notches.has(id)) notches.set(id, notchOf(id) || null);
      return notches.get(id);
    };
    const ends = [];
    const links = [];
    edges.forEach(edge => {
      if (!edge?.id || !edge.from || !edge.to || edge.from === edge.to) return;
      const a = rect(edge.from), b = rect(edge.to);
      const [fromSide, toSide] = facingSides(a, b);
      const toward = (nodeId, side, other) => {
        const r = edgeRange(rect(nodeId), side, notch(nodeId));
        return clamp(isHorizontal(side) ? other.y + other.h / 2 : other.x + other.w / 2, r.min, r.max);
      };
      const from = { key: `${edge.id}|out`, nodeId: edge.from, side: fromSide, desired: toward(edge.from, fromSide, b) };
      const to = { key: `${edge.id}|in`, nodeId: edge.to, side: toSide, desired: toward(edge.to, toSide, a), incoming: true };
      ends.push(from, to);
      links.push({ edge, from, to });
    });

    const groups = new Map();
    ends.forEach(end => {
      const key = `${end.nodeId}|${end.side}`;
      if (!groups.has(key)) groups.set(key, { nodeId: end.nodeId, side: end.side, ends: [] });
      groups.get(key).ends.push(end);
    });
    groups.forEach(group => {
      const r = edgeRange(rect(group.nodeId), group.side, notch(group.nodeId));
      const list = group.ends.sort((p, q) => p.desired - q.desired);
      const span = (list.length - 1) * PORT_GAP;
      const mean = list.reduce((sum, end) => sum + end.desired, 0) / list.length;
      // Clusters lean toward their partners but stay near the middle of the edge.
      let centre = list.length > 1 ? (r.min + r.max) / 2 + (mean - (r.min + r.max) / 2) * 0.45 : mean;
      centre = span > r.max - r.min ? (r.min + r.max) / 2 : clamp(centre, r.min + span / 2, r.max - span / 2);
      list.forEach((end, index) => { end.desired = centre - span / 2 + index * PORT_GAP; });
      group.single = list.length === 1;
    });
    const groupOf = end => groups.get(`${end.nodeId}|${end.side}`);
    const reachable = (end, value) => {
      const r = edgeRange(rect(end.nodeId), end.side, notch(end.nodeId));
      return value >= r.min && value <= r.max;
    };
    const nearLevel = (own, other) => groupOf(own).single && Math.abs(own.desired - other.desired) < STRAIGHT_SNAP;
    // A single port that cannot reach its partner (edge range) levels the partner's
    // whole cluster instead, when that cluster has room; then singles snap level.
    links.forEach(({ from, to }) => {
      [[from, to], [to, from]].forEach(([own, other]) => {
        if (!nearLevel(own, other) || reachable(own, other.desired) || groupOf(other).single) return;
        const delta = own.desired - other.desired;
        const cluster = groupOf(other).ends;
        if (cluster.every(end => reachable(end, end.desired + delta))) cluster.forEach(end => { end.desired += delta; });
      });
    });
    links.forEach(({ from, to }) => {
      [[from, to], [to, from]].forEach(([own, other]) => {
        if (nearLevel(own, other) && reachable(own, other.desired)) own.desired = other.desired;
      });
    });

    const settled = motion ? ease(motion, now, ends, groups, rect) : true;
    let plates = '';
    const ports = new Map();
    const half = PIPE_HALF + PLATE.pad;
    groups.forEach(group => {
      const r = rect(group.nodeId);
      const frame = frameOf(r, group.side);
      const values = group.ends.map(end => end.desired);
      const from = Math.min(...values) - half, to = Math.max(...values) + half;
      plates += platePath(frame, from, to, group.amount ?? 1);
      values.forEach(value => { plates += neckPath(frame, value, group.amount ?? 1); });
      if (!ports.has(group.nodeId)) ports.set(group.nodeId, []);
      ports.get(group.nodeId).push({
        side: group.side,
        incoming: group.ends.filter(end => end.incoming).length,
        hit: plateHit(r, group.side, from, to),
      });
    });
    (motion?.groups || new Map()).forEach((state, key) => {
      if (groups.has(key) || !rects.has(state.nodeId)) return;
      const r = rect(state.nodeId), base = isHorizontal(state.side) ? r.y : r.x;
      plates += platePath(frameOf(r, state.side), base + state.from, base + state.to, state.amount);
    });
    const routes = new Map();
    const face = end => {
      const [x, y] = frameOf(rect(end.nodeId), end.side).at(PLATE.depth * (groupOf(end).amount ?? 1), end.desired);
      return { x, y };
    };
    links.forEach(({ edge, from, to }) => {
      routes.set(edge.id, { from: face(from), to: face(to), fromSide: from.side, toSide: to.side });
    });
    return { routes, plates, ports, settled };
  }

  // Moves `ends` (port positions) and `groups` (plate amounts) part of the way from the
  // previous frame toward this layout. Positions ease in node-local offsets, so a plate
  // never trails behind its own node. Returns true once nothing is still moving.
  function ease(motion, now, ends, groups, rect) {
    const first = !motion.time;
    const dt = first ? Infinity : Math.max(0, now - motion.time);
    motion.time = now || 1;
    const step = ms => 1 - Math.exp(-dt / ms);
    let settled = true;
    const origin = end => (isHorizontal(end.side) ? rect(end.nodeId).y : rect(end.nodeId).x);
    const liveEnds = new Set();
    ends.forEach(end => {
      const local = end.desired - origin(end);
      const prev = motion.ends.get(end.key);
      let next = local;
      if (prev && prev.side === end.side) next = prev.local + (local - prev.local) * step(EASE_SLIDE_MS);
      if (Math.abs(next - local) < SETTLED_PX) next = local;
      else settled = false;
      motion.ends.set(end.key, { side: end.side, local: next });
      liveEnds.add(end.key);
      end.desired = next + origin(end);
    });
    motion.ends.forEach((_, key) => { if (!liveEnds.has(key)) motion.ends.delete(key); });

    const half = PIPE_HALF + PLATE.pad;
    groups.forEach((group, key) => {
      const prev = motion.groups.get(key);
      let amount = first ? 1 : (prev?.amount ?? 0) + (1 - (prev?.amount ?? 0)) * step(EASE_GROW_MS);
      if (amount > 0.995) amount = 1;
      else settled = false;
      group.amount = amount;
      const r = rect(group.nodeId), base = isHorizontal(group.side) ? r.y : r.x;
      const values = group.ends.map(end => end.desired - base);
      motion.groups.set(key, {
        nodeId: group.nodeId, side: group.side, amount,
        from: Math.min(...values) - half, to: Math.max(...values) + half,
      });
    });
    motion.groups.forEach((state, key) => {
      if (groups.has(key)) return;
      state.amount *= 1 - step(EASE_GROW_MS);
      if (state.amount < 0.02) motion.groups.delete(key);
      else settled = false;
    });
    return settled;
  }

  window.DesktopCanvasPortPlates = Object.freeze({
    PLATE, PORT_GAP, PIPE_HALF, NOTCH, NOTCHED_NODES, notchOf, facingSides, edgeRange, edgePlate, createMotion, layout,
  });
})();
