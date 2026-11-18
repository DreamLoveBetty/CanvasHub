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
  const SIDE_SPLIT = 12;      // half gap between a side's incoming and outgoing plates
  const EASE_SLIDE_MS = 90;   // time constant for ports sliding along a side
  const EASE_GROW_MS = 110;   // time constant for a plate growing on / shrinking off a side
  const SETTLED_PX = 0.2;
  // Bottom-right cut-out around a generate node's 72px key; the graphite stylesheet
  // cuts the same nodes (keep NOTCHED_NODES in step with desktop-graphite.css).
  const NOTCH = Object.freeze({ w: 88, h: 88, r: 12 });
  const NOTCHED_NODES = '.desk-node--input, .desk-node--krea2, .desk-node--moss, .desk-node--qwen21, '
    + '.desk-node--topaz, .desk-node--pose, .desk-node--topaz-video, .desk-node--video-control, .desk-node--comfy, '
    + '.desk-node--music-generate';
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

  // A node takes links in on its left and sends them out on its right, however the nodes
  // move: an incoming end never lands on the right side, an outgoing end never on the
  // left. Such an end turns to the top or bottom, whichever faces its partner.
  function portSide(side, incoming, own, other) {
    if (side !== (incoming ? 'right' : 'left')) return side;
    return other.y + other.h / 2 < own.y + own.h / 2 ? 'top' : 'bottom';
  }

  /** Facing sides of a link's source `a` and target `b`, kept off each node's opposite-direction side. */
  function portSides(a, b) {
    const [fromSide, toSide] = facingSides(a, b);
    return [portSide(fromSide, false, a, b), portSide(toSide, true, b, a)];
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

  // Plate height at |u| px from its centre: flat face, rounded outer corners, concave
  // base fillets into the card - the same cross-section platePath draws on a straight side.
  function plateProfile(u, depth, base, corner) {
    const half = PIPE_HALF + PLATE.pad;
    if (u <= half - corner) return depth;
    if (u <= half) return depth - corner + Math.sqrt(Math.max(0, corner * corner - (u - half + corner) ** 2));
    if (u < half + base) return base - Math.sqrt(Math.max(0, base * base - (half + base - u) ** 2));
    return 0;
  }

  /**
   * The hover plate laid along a node's rounded outline, so it travels round the corners
   * instead of hopping from one side to the next. `pointAt(s)` gives {x, y, nx, ny}
   * (outward normal) at arc length `s`; `center` is the plate's arc position.
   * @returns {{ path: string, face: {x:number,y:number} }}
   */
  function perimeterPlate(pointAt, center, amount = 1) {
    const at = pointAt(center);
    const face = { x: at.x + at.nx * PLATE.depth, y: at.y + at.ny * PLATE.depth };
    if (!(amount > 0)) return { path: '', face };
    const depth = PLATE.depth * amount, base = PLATE.base * amount;
    const corner = Math.min(PLATE.corner, depth / 2);
    const reach = PIPE_HALF + PLATE.pad + base;
    const step = 0.25;
    const count = Math.ceil(reach * 2 / step);
    const offset = (u, out) => {
      const p = pointAt(center + u);
      return point([p.x + p.nx * out, p.y + p.ny * out]);
    };
    const points = Array.from({ length: count + 1 }, (_, index) => {
      const u = -reach + index * reach * 2 / count;
      return offset(u, plateProfile(Math.abs(u), depth, base, corner));
    });
    return { path: `M${offset(-reach, -3)} L${points.join(' L')} L${offset(reach, -3)} Z`, face };
  }

  /**
   * 1 away from a notched node's bottom-right cut-out, easing to 0 within `fade` px of
   * the zone where edgeRange stops ports, so a travelling plate sinks into the card there.
   */
  function notchFade(rect, notch, x, y, fade = 16) {
    if (!notch) return 1;
    const pad = notch.r + PLATE.base + PLATE.pad + PIPE_HALF + 2;
    const into = Math.min(x - (rect.x + rect.w - notch.w - pad), y - (rect.y + rect.h - notch.h - pad));
    if (into <= 0) return 1;
    const t = clamp(into / fade, 0, 1);
    return 1 - t * t * (3 - 2 * t);
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
   * An edge with `toOnly` is a link still being dragged: only its target end takes a
   * port (and makes room on that plate); its source end is laid out as a lone port that
   * draws nothing, so the drag can show where the link will land before it is made.
   * @param {Array<{id:string, from:string, to:string, toOnly?:boolean}>} edges
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
      const [fromSide, toSide] = portSides(a, b);
      const from = { key: `${edge.id}|out`, nodeId: edge.from, side: fromSide, partner: b };
      const to = { key: `${edge.id}|in`, nodeId: edge.to, side: toSide, partner: a, incoming: true };
      if (!edge.toOnly) ends.push(from);
      ends.push(to);
      links.push({ edge, from, to });
    });

    // Incoming and outgoing ends never share a plate. Where both meet on a top/bottom side,
    // inputs keep to the half nearer the input (left) side and outputs to the other half.
    const groupKey = end => `${end.nodeId}|${end.side}|${end.incoming ? 'in' : 'out'}`;
    const occupied = new Set(ends.map(groupKey));
    const rangeOf = end => {
      const r = edgeRange(rect(end.nodeId), end.side, notch(end.nodeId));
      if (!occupied.has(`${end.nodeId}|${end.side}|${end.incoming ? 'out' : 'in'}`)) return r;
      const mid = (r.min + r.max) / 2;
      return end.incoming
        ? { min: r.min, max: Math.max(r.min, mid - SIDE_SPLIT) }
        : { min: Math.min(r.max, mid + SIDE_SPLIT), max: r.max };
    };
    links.forEach(({ from, to }) => [from, to].forEach(end => {
      const r = rangeOf(end), other = end.partner;
      end.desired = clamp(isHorizontal(end.side) ? other.y + other.h / 2 : other.x + other.w / 2, r.min, r.max);
    }));

    const groups = new Map();
    ends.forEach(end => {
      const key = groupKey(end);
      if (!groups.has(key)) groups.set(key, { nodeId: end.nodeId, side: end.side, ends: [] });
      groups.get(key).ends.push(end);
    });
    groups.forEach(group => {
      const r = rangeOf(group.ends[0]);
      const list = group.ends.sort((p, q) => p.desired - q.desired);
      const span = (list.length - 1) * PORT_GAP;
      const mean = list.reduce((sum, end) => sum + end.desired, 0) / list.length;
      // Clusters lean toward their partners but stay near the middle of the edge.
      let centre = list.length > 1 ? (r.min + r.max) / 2 + (mean - (r.min + r.max) / 2) * 0.45 : mean;
      centre = span > r.max - r.min ? (r.min + r.max) / 2 : clamp(centre, r.min + span / 2, r.max - span / 2);
      list.forEach((end, index) => { end.desired = centre - span / 2 + index * PORT_GAP; });
      group.single = list.length === 1;
    });
    const groupOf = end => groups.get(groupKey(end));
    const single = end => groupOf(end)?.single ?? true; // an ungrouped (preview) end acts as a lone port
    const reachable = (end, value) => {
      const r = rangeOf(end);
      return value >= r.min && value <= r.max;
    };
    const nearLevel = (own, other) => single(own) && Math.abs(own.desired - other.desired) < STRAIGHT_SNAP;
    // A single port that cannot reach its partner (edge range) levels the partner's
    // whole cluster instead, when that cluster has room; then singles snap level.
    links.forEach(({ from, to }) => {
      [[from, to], [to, from]].forEach(([own, other]) => {
        if (!nearLevel(own, other) || reachable(own, other.desired) || single(other)) return;
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
      const [x, y] = frameOf(rect(end.nodeId), end.side).at(PLATE.depth * (groupOf(end)?.amount ?? 1), end.desired);
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
    PLATE, PORT_GAP, PIPE_HALF, NOTCH, NOTCHED_NODES, notchOf, facingSides, portSides, edgeRange, edgePlate, perimeterPlate, notchFade, createMotion, layout,
  });
})();
