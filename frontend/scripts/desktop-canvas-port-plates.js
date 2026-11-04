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
  // Bottom-right cut-out around the model-input node's 72px generate key.
  const INPUT_NOTCH = Object.freeze({ w: 88, h: 88, r: 12 });

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
  function neckPath(frame, along) {
    const out = PLATE.depth, r = NECK, w = PIPE_HALF, f = frame.at;
    return `M${point(f(out - 2, along - w - r))} L${point(f(out, along - w - r))}${arc(frame, r, 0, out + r, along - w)}`
      + ` L${point(f(out + r, along + w))}${arc(frame, r, 0, out, along + w + r)}`
      + ` L${point(f(out - 2, along + w + r))} Z`;
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
   * @returns {{ routes: Map<string,{from:{x,y},to:{x,y},fromSide:string,toSide:string}>, plates: string }}
   */
  function layout(edges = [], geometryOf, notchOf = () => null) {
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
      const from = { nodeId: edge.from, side: fromSide, desired: toward(edge.from, fromSide, b) };
      const to = { nodeId: edge.to, side: toSide, desired: toward(edge.to, toSide, a) };
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

    let plates = '';
    groups.forEach(group => {
      const frame = frameOf(rect(group.nodeId), group.side);
      const values = group.ends.map(end => end.desired);
      plates += platePath(frame, Math.min(...values) - PIPE_HALF - PLATE.pad, Math.max(...values) + PIPE_HALF + PLATE.pad);
      values.forEach(value => { plates += neckPath(frame, value); });
    });
    const routes = new Map();
    const face = end => {
      const [x, y] = frameOf(rect(end.nodeId), end.side).at(PLATE.depth, end.desired);
      return { x, y };
    };
    links.forEach(({ edge, from, to }) => {
      routes.set(edge.id, { from: face(from), to: face(to), fromSide: from.side, toSide: to.side });
    });
    return { routes, plates };
  }

  window.DesktopCanvasPortPlates = Object.freeze({ PLATE, PORT_GAP, PIPE_HALF, INPUT_NOTCH, facingSides, edgeRange, edgePlate, layout });
})();
