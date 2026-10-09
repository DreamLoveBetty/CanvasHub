const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const scripts = path.resolve(__dirname, '../frontend/scripts');
const window = { DesktopPreferences: { state: { connectionLineStyle: 'curve' } } };
const context = vm.createContext({ window });
for (const name of ['desktop-canvas-geometry', 'desktop-canvas-connections']) {
  vm.runInContext(fs.readFileSync(path.join(scripts, `${name}.js`), 'utf8'), context);
}
const geometry = window.DesktopCanvasGeometry;
const connections = window.DesktopCanvasConnections.create({
  makeClassicCurvePath: (...args) => geometry.makeClassicCurvePath(...args),
  makeSmoothStepPath: (...args) => geometry.makeSmoothStepPath(...args),
});

function anchor(rect, side) {
  if (side === 'top' || side === 'bottom') {
    return { x: rect.x + rect.width / 2, y: rect.y + (side === 'bottom' ? rect.height : 0) };
  }
  return { x: side === 'right' ? rect.x + rect.width : rect.x, y: rect.y + rect.height / 2 };
}

function cubicSegments(d) {
  assert.deepEqual(d.match(/[MLCQ]/g), ['M', 'C'], 'curve mode always uses one cubic, never a node-avoidance detour');
  const tokens = d.match(/[MC]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?/gi);
  let index = 1;
  const point = () => ({ x: Number(tokens[index++]), y: Number(tokens[index++]) });
  let start = point();
  const segments = [];
  while (index < tokens.length) {
    assert.equal(tokens[index++], 'C');
    const segment = [start, point(), point(), point()];
    assert.ok(segment.every(p => Number.isFinite(p.x) && Number.isFinite(p.y)));
    segments.push(segment);
    start = segment[3];
  }
  return segments;
}

function inside(p, rect) {
  const epsilon = 1e-7;
  return p.x > rect.x + epsilon && p.x < rect.x + rect.width - epsilon
    && p.y > rect.y + epsilon && p.y < rect.y + rect.height - epsilon;
}

function checkCurve(fromGeometry, toGeometry, fromSide = 'right', toSide = 'left', endpoints = null) {
  const from = endpoints?.from || anchor(fromGeometry, fromSide);
  const to = endpoints?.to || anchor(toGeometry, toSide);
  const route = { fromGeometry, toGeometry };
  const before = JSON.stringify({ from, to, route });
  const d = connections.makeConnectionPath(from, to, fromSide, toSide, route);
  const segments = cubicSegments(d);
  assert.equal(d, geometry.makeClassicCurvePath(from, to, fromSide, toSide), 'node rectangles must not affect curve routing');
  assert.equal(JSON.stringify({ from, to, route }), before, 'geometry must not mutate graph inputs');
  assert.deepEqual(segments[0][0], from);
  assert.deepEqual(segments.at(-1)[3], to);
  assert.equal(segments[0][1].y, from.y, 'source tangent follows its horizontal port');
  assert.equal(segments.at(-1)[2].y, to.y, 'destination tangent follows its horizontal port');
  assert.ok((segments[0][1].x - from.x) * (fromSide === 'right' ? 1 : -1) >= 0);
  assert.ok((segments.at(-1)[2].x - to.x) * (toSide === 'right' ? 1 : -1) >= 0);
  return segments;
}

function checkStraight(fromGeometry, toGeometry, fromSide = 'right', toSide = 'left') {
  const from = anchor(fromGeometry, fromSide);
  const to = anchor(toGeometry, toSide);
  const route = { fromGeometry, toGeometry };
  const before = JSON.stringify({ from, to, route });
  const d = geometry.makeSmoothStepPath(from, to, fromSide, toSide, route);
  const tokens = d.match(/[MLQ]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?/gi);
  let index = 1;
  const point = () => ({ x: Number(tokens[index++]), y: Number(tokens[index++]) });
  let current = point();
  assert.deepEqual(current, from);
  while (index < tokens.length) {
    const command = tokens[index++];
    assert.ok(command === 'L' || command === 'Q');
    const controls = [current, point()];
    if (command === 'Q') controls.push(point());
    for (let step = 0; step <= 160; step++) {
      const t = step / 160;
      let work = controls;
      while (work.length > 1) {
        work = work.slice(1).map((p, i) => ({ x: work[i].x * (1 - t) + p.x * t, y: work[i].y * (1 - t) + p.y * t }));
      }
      assert.ok(!inside(work[0], fromGeometry) && !inside(work[0], toGeometry), `straight route crosses a node: ${d}`);
    }
    current = controls.at(-1);
  }
  assert.deepEqual(current, to);
  assert.equal(JSON.stringify({ from, to, route }), before, 'straight routing remains pure');
  return d;
}

const model = { x: 1044, y: 62, width: 600, height: 460 };
const image = { x: 988, y: 707, width: 268, height: 477 };

test('reported image-to-video layout uses a direct single cubic without a detour', () => {
  const segments = checkCurve(image, model, 'right', 'left', { from: { x: 1256, y: 945 }, to: { x: 1044, y: 292 } });
  assert.ok(segments[0][1].x <= image.x + image.width + 180, 'curve controls retain their original bounded length');
});

test('model-to-result reverse direction remains a smooth curve', () => checkCurve(model, image));
test('horizontal reverse layouts ignore both node bounds', () => checkCurve(
  { x: 600, y: 50, width: 300, height: 300 }, { x: 50, y: 100, width: 200, height: 220 },
));
test('off-center horizontal reverse ports do not create an exterior corridor', () => checkCurve(
  { x: 600, y: 0, width: 300, height: 300 }, { x: 50, y: 200, width: 200, height: 300 },
  'right', 'left', { from: { x: 900, y: 290 }, to: { x: 50, y: 490 } },
));
test('mirrored left-output/right-input ports keep curve tangents', () => checkCurve(
  { ...image, x: -image.x - image.width }, { ...model, x: -model.x - model.width }, 'left', 'right',
));

for (const gap of [0, 1, 12, 23, 24, 32, 100, 500]) {
  test(`vertically separated cards with ${gap}px gap stay curved in both directions`, () => {
    const lower = { ...image, y: model.y + model.height + gap };
    checkCurve(model, lower);
    checkCurve(lower, model);
  });
}

test('large negative coordinates retain a finite single cubic', () => checkCurve(
  { x: -4000, y: -4000, width: 737, height: 471 }, { x: -3850, y: -5000, width: 300, height: 532 },
));
test('overlapping cards retain finite curve commands even when an endpoint is covered', () => {
  cubicSegments(geometry.makeClassicCurvePath(
    anchor(model, 'right'), anchor({ ...model, x: 1100, y: 100 }, 'left'), 'right', 'left',
    { fromGeometry: model, toGeometry: { ...model, x: 1100, y: 100 } },
  ));
});
test('forward curve serialization and behavior are unchanged', () => {
  const from = { x: 692, y: 554 };
  const to = { x: 1044, y: 292 };
  const route = { fromGeometry: { x: 76, y: 318, width: 616, height: 478 }, toGeometry: model };
  assert.equal(connections.makeConnectionPath(from, to, 'right', 'left', route), 'M 692 554 C 868 554 868 292 1044 292');
});
test('free and snapped pointer previews use the same single cubic', () => {
  const from = { x: 1256, y: 945 };
  const to = { x: 1044, y: 292 };
  const original = geometry.makeClassicCurvePath(from, to);
  assert.deepEqual(original.match(/[MLCQ]/g), ['M', 'C']);
  assert.equal(connections.makeConnectionPath(from, to, 'right', 'left', { fromGeometry: image }), original);
  assert.equal(connections.makeConnectionPath(from, to, 'right', 'left', { fromGeometry: image, toGeometry: model }), original);
});
test('reverse curve serialization no longer depends on a route', () => {
  const from = { x: 200, y: 300 };
  const to = { x: 56, y: 0 };
  const route = { fromGeometry: { x: 100, y: 250, width: 100, height: 100 }, toGeometry: { x: 56, y: -50, width: 500, height: 100 } };
  assert.equal(connections.makeConnectionPath(from, to, 'right', 'left', route), 'M 200 300 C 300 300 -44 0 56 0');
});
test('curve mode never reads rectangle routing data', () => {
  const unreadableRoute = new Proxy({}, { get() { throw new Error('curve mode must not inspect node bounds'); } });
  const from = anchor(image, 'right');
  const to = anchor(model, 'left');
  assert.equal(connections.makeConnectionPath(from, to, 'right', 'left', unreadableRoute), geometry.makeClassicCurvePath(from, to));
});
test('every port side combination retains direct endpoint-normal controls', () => {
  const from = { x: 400, y: 900 };
  const to = { x: 100, y: 40 };
  for (const fromSide of ['left', 'right', 'top', 'bottom']) {
    for (const toSide of ['left', 'right', 'top', 'bottom']) {
      const d = connections.makeConnectionPath(from, to, fromSide, toSide, { fromGeometry: image, toGeometry: model });
      const [a, b, c, e] = cubicSegments(d)[0];
      assert.equal(d, geometry.makeClassicCurvePath(from, to, fromSide, toSide));
      assert.deepEqual(a, from);
      assert.deepEqual(e, to);
      for (const [control, endpoint, side] of [[b, from, fromSide], [c, to, toSide]]) {
        const normal = geometry.portOutwardVector(side);
        const dx = control.x - endpoint.x;
        const dy = control.y - endpoint.y;
        assert.ok(Math.abs(dx * normal.y - dy * normal.x) < 1e-7, 'control remains on the port normal');
        assert.ok(dx * normal.x + dy * normal.y >= 0, 'control points outward');
      }
    }
  }
});
test('straight mode retains its original rounded orthogonal router', () => {
  window.DesktopPreferences.state.connectionLineStyle = 'straight';
  try {
    const from = anchor(image, 'right');
    const to = anchor(model, 'left');
    const route = { fromGeometry: image, toGeometry: model };
    assert.equal(connections.makeConnectionPath(from, to, 'right', 'left', route), geometry.makeSmoothStepPath(from, to, 'right', 'left', route));
    assert.equal(checkStraight(image, model),
      'M 1256 945.5 L 1664 945.5 Q 1674 945.5 1674 935.5 L 1674 624.5 Q 1674 614.5 1664 614.5 L 968 614.5 Q 958 614.5 958 604.5 L 958 302 Q 958 292 968 292 L 1044 292');
    checkStraight(model, image);
    checkStraight({ ...image, x: -image.x - image.width }, { ...model, x: -model.x - model.width }, 'left', 'right');
    checkStraight({ x: 600, y: 50, width: 300, height: 300 }, { x: 50, y: 100, width: 200, height: 220 });
    assert.equal(geometry.makeSmoothStepPath({ x: 0, y: 0 }, { x: 100, y: 100 }),
      'M 0 0 L 40 0 Q 50 0 50 10 L 50 90 Q 50 100 60 100 L 100 100');
  } finally {
    window.DesktopPreferences.state.connectionLineStyle = 'curve';
  }
});
test('moving an endpoint across the other port never changes the curve preference', () => {
  const from = anchor(image, 'right');
  for (const x of [1300, 1257, 1256, 1255, 1044]) {
    const destination = { ...model, x };
    const d = connections.makeConnectionPath(from, anchor(destination, 'left'), 'right', 'left', { fromGeometry: image, toGeometry: destination });
    cubicSegments(d);
    assert.equal(d, geometry.makeClassicCurvePath(from, anchor(destination, 'left')));
    assert.equal(window.DesktopPreferences.state.connectionLineStyle, 'curve');
  }
});
test('seeded disjoint-card corpus ignores rectangles in both directions', () => {
  let seed = 20261002;
  const random = () => ((seed = Math.imul(seed, 1664525) + 1013904223 >>> 0) / 4294967296);
  for (let index = 0; index < 500; index++) {
    const a = { x: Math.round(random() * 4000) - 2000, y: Math.round(random() * 4000) - 2000,
      width: 96 + Math.round(random() * 824), height: 96 + Math.round(random() * 864) };
    const b = { x: a.x + Math.round(random() * a.width / 2), y: a.y + a.height + 1 + Math.round(random() * 500),
      width: a.width + Math.round(random() * 400), height: 96 + Math.round(random() * 864) };
    checkCurve(a, b);
    checkCurve(b, a);
  }
});
test('seeded horizontal reverse corpus ignores rectangles in both directions', () => {
  let seed = 0x20261002;
  const random = () => ((seed = Math.imul(seed, 1664525) + 1013904223 >>> 0) / 4294967296);
  for (let index = 0; index < 300; index++) {
    const left = { x: Math.round(random() * 4000) - 2000, y: Math.round(random() * 4000) - 2000,
      width: 96 + Math.round(random() * 824), height: 96 + Math.round(random() * 864) };
    const right = { x: left.x + left.width + 1 + Math.round(random() * 500), y: left.y + Math.round(random() * 1800) - 900,
      width: 96 + Math.round(random() * 824), height: 96 + Math.round(random() * 864) };
    checkCurve(right, left);
    checkCurve(left, right, 'left', 'right');
  }
});
