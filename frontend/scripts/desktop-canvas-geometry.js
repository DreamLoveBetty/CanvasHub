// Stateless canvas geometry. Loaded before desktop-canvas.js in source and builds.
// Keep coercion, path serialization, and rectangle edge semantics compatible.
(function () {
  const CONNECTION_LEAD_LENGTH = 30;
  const CONNECTION_CORNER_RADIUS = 10;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function normalizePortSide(value, fallback = 'right') {
    const normalized = String(value || '').toLowerCase();
    return ['left', 'right', 'top', 'bottom'].includes(normalized) ? normalized : fallback;
  }

  function oppositePortSide(side) {
    return ({ left: 'right', right: 'left', top: 'bottom', bottom: 'top' })[normalizePortSide(side)] || 'left';
  }

  function dominantPortSide(fromPoint, toPoint) {
    const dx = Number(toPoint?.x || 0) - Number(fromPoint?.x || 0);
    const dy = Number(toPoint?.y || 0) - Number(fromPoint?.y || 0);
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 'right' : 'left';
    return dy >= 0 ? 'bottom' : 'top';
  }

  function getBoundsFromRects(rects) {
    if (!rects.length) return null;
    const left = Math.min(...rects.map(rect => rect.x));
    const top = Math.min(...rects.map(rect => rect.y));
    const right = Math.max(...rects.map(rect => rect.x + rect.width));
    const bottom = Math.max(...rects.map(rect => rect.y + rect.height));
    return {
      x: left,
      y: top,
      width: right - left,
      height: bottom - top,
      right,
      bottom,
      centerX: left + (right - left) / 2,
      centerY: top + (bottom - top) / 2
    };
  }

  function getRectFromPoints(start, end) {
    const x = Math.min(start.x, end.x);
    const y = Math.min(start.y, end.y);
    return {
      x,
      y,
      width: Math.abs(end.x - start.x),
      height: Math.abs(end.y - start.y)
    };
  }

  function rectsIntersect(a, b) {
    return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
  }

  function offsetPointForPort(point, side, distance = CONNECTION_LEAD_LENGTH) {
    const normalizedSide = normalizePortSide(side);
    if (normalizedSide === 'left') return { x: point.x - distance, y: point.y };
    if (normalizedSide === 'top') return { x: point.x, y: point.y - distance };
    if (normalizedSide === 'bottom') return { x: point.x, y: point.y + distance };
    return { x: point.x + distance, y: point.y };
  }

  function compactOrthogonalPoints(points) {
    const compact = [];
    points.forEach(point => {
      const previous = compact[compact.length - 1];
      if (!previous || previous.x !== point.x || previous.y !== point.y) compact.push(point);
    });
    let index = 1;
    while (index < compact.length - 1) {
      const before = compact[index - 1];
      const current = compact[index];
      const after = compact[index + 1];
      if ((before.x === current.x && current.x === after.x) || (before.y === current.y && current.y === after.y)) {
        compact.splice(index, 1);
      } else {
        index += 1;
      }
    }
    return compact;
  }

  function roundedOrthogonalPath(points, radius = CONNECTION_CORNER_RADIUS) {
    const compact = compactOrthogonalPoints(points);
    if (compact.length < 2) return '';
    let path = `M ${compact[0].x} ${compact[0].y}`;
    for (let index = 1; index < compact.length - 1; index += 1) {
      const before = compact[index - 1];
      const corner = compact[index];
      const after = compact[index + 1];
      const beforeLength = Math.hypot(corner.x - before.x, corner.y - before.y);
      const afterLength = Math.hypot(after.x - corner.x, after.y - corner.y);
      const cornerRadius = Math.min(radius, beforeLength / 2, afterLength / 2);
      if (!cornerRadius) {
        path += ` L ${corner.x} ${corner.y}`;
        continue;
      }
      const beforePoint = {
        x: corner.x - ((corner.x - before.x) / beforeLength) * cornerRadius,
        y: corner.y - ((corner.y - before.y) / beforeLength) * cornerRadius
      };
      const afterPoint = {
        x: corner.x + ((after.x - corner.x) / afterLength) * cornerRadius,
        y: corner.y + ((after.y - corner.y) / afterLength) * cornerRadius
      };
      path += ` L ${beforePoint.x} ${beforePoint.y} Q ${corner.x} ${corner.y} ${afterPoint.x} ${afterPoint.y}`;
    }
    const last = compact[compact.length - 1];
    return `${path} L ${last.x} ${last.y}`;
  }

  function getBackwardConnectionDetourY(fromGeometry, toGeometry, fromLead, toLead) {
    const fromTop = fromGeometry.y;
    const fromBottom = fromGeometry.y + fromGeometry.height;
    const toTop = toGeometry.y;
    const toBottom = toGeometry.y + toGeometry.height;
    const minimumGap = CONNECTION_CORNER_RADIUS * 2 + 4;

    if (toTop - fromBottom >= minimumGap) return (fromBottom + toTop) / 2;
    if (fromTop - toBottom >= minimumGap) return (toBottom + fromTop) / 2;

    const topY = Math.min(fromTop, toTop) - CONNECTION_LEAD_LENGTH;
    const bottomY = Math.max(fromBottom, toBottom) + CONNECTION_LEAD_LENGTH;
    const topCost = Math.abs(fromLead.y - topY) + Math.abs(toLead.y - topY);
    const bottomCost = Math.abs(fromLead.y - bottomY) + Math.abs(toLead.y - bottomY);
    return topCost <= bottomCost ? topY : bottomY;
  }

  function makeSmoothStepPath(from, to, fromSide = 'right', toSide = 'left', route = null, cornerRadius = CONNECTION_CORNER_RADIUS) {
    const normalizedFromSide = normalizePortSide(fromSide, 'right');
    const normalizedToSide = normalizePortSide(toSide, 'left');
    const fromLead = offsetPointForPort(from, normalizedFromSide);
    const toLead = offsetPointForPort(to, normalizedToSide);
    const fromHorizontal = normalizedFromSide === 'left' || normalizedFromSide === 'right';
    const toHorizontal = normalizedToSide === 'left' || normalizedToSide === 'right';
    const points = [from, fromLead];

    if (fromHorizontal && toHorizontal) {
      const isBackward = (
        normalizedFromSide === 'right'
        && normalizedToSide === 'left'
        && fromLead.x > toLead.x
      ) || (
        normalizedFromSide === 'left'
        && normalizedToSide === 'right'
        && fromLead.x < toLead.x
      );
      const fromGeometry = route?.fromGeometry;
      const toGeometry = route?.toGeometry;
      if (isBackward && fromGeometry && toGeometry) {
        const leftCorridorX = Math.min(fromGeometry.x, toGeometry.x) - CONNECTION_LEAD_LENGTH;
        const rightCorridorX = Math.max(
          fromGeometry.x + fromGeometry.width,
          toGeometry.x + toGeometry.width
        ) + CONNECTION_LEAD_LENGTH;
        const fromCorridorX = normalizedFromSide === 'right' ? rightCorridorX : leftCorridorX;
        const toCorridorX = normalizedToSide === 'right' ? rightCorridorX : leftCorridorX;
        const detourY = getBackwardConnectionDetourY(fromGeometry, toGeometry, fromLead, toLead);
        points.push(
          { x: fromCorridorX, y: fromLead.y },
          { x: fromCorridorX, y: detourY },
          { x: toCorridorX, y: detourY },
          { x: toCorridorX, y: toLead.y }
        );
      } else {
        let middleX = (fromLead.x + toLead.x) / 2;
        if (normalizedFromSide === normalizedToSide) {
          middleX = normalizedFromSide === 'right'
            ? Math.max(fromLead.x, toLead.x) + CONNECTION_LEAD_LENGTH
            : Math.min(fromLead.x, toLead.x) - CONNECTION_LEAD_LENGTH;
        }
        points.push({ x: middleX, y: fromLead.y }, { x: middleX, y: toLead.y });
      }
    } else if (!fromHorizontal && !toHorizontal) {
      let middleY = (fromLead.y + toLead.y) / 2;
      if (normalizedFromSide === normalizedToSide) {
        middleY = normalizedFromSide === 'bottom'
          ? Math.max(fromLead.y, toLead.y) + CONNECTION_LEAD_LENGTH
          : Math.min(fromLead.y, toLead.y) - CONNECTION_LEAD_LENGTH;
      }
      points.push({ x: fromLead.x, y: middleY }, { x: toLead.x, y: middleY });
    } else if (fromHorizontal) {
      points.push({ x: toLead.x, y: fromLead.y });
    } else {
      points.push({ x: fromLead.x, y: toLead.y });
    }

    points.push(toLead, to);
    return roundedOrthogonalPath(points, cornerRadius);
  }

  function portOutwardVector(side) {
    const normalizedSide = normalizePortSide(side);
    if (normalizedSide === 'left') return { x: -1, y: 0 };
    if (normalizedSide === 'top') return { x: 0, y: -1 };
    if (normalizedSide === 'bottom') return { x: 0, y: 1 };
    return { x: 1, y: 0 };
  }

  function classicCurveControlOffset(axisDistance, crossDistance) {
    if (axisDistance >= 0) return clamp(axisDistance * 0.5, 0, 180);
    const reverseOffset = 22
      + Math.sqrt(Math.abs(axisDistance)) * 4.5
      + Math.min(Math.abs(crossDistance) * 0.08, 36);
    return clamp(reverseOffset, 28, 180);
  }

  // Curve style uses endpoints and port normals only; route stays in the public
  // signature for compatibility but node-boundary avoidance belongs to straight mode.
  function makeClassicCurvePath(from, to, fromSide = 'right', toSide = 'left', route = null) {
    const normalizedFromSide = normalizePortSide(fromSide, 'right');
    const normalizedToSide = normalizePortSide(toSide, 'left');
    const fromVector = portOutwardVector(normalizedFromSide);
    const toVector = portOutwardVector(normalizedToSide);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const fromAxisDistance = dx * fromVector.x + dy * fromVector.y;
    const toAxisDistance = -dx * toVector.x - dy * toVector.y;
    const fromCrossDistance = fromVector.x ? dy : dx;
    const toCrossDistance = toVector.x ? dy : dx;
    const fromOffset = classicCurveControlOffset(fromAxisDistance, fromCrossDistance);
    const toOffset = classicCurveControlOffset(toAxisDistance, toCrossDistance);
    const fromControl = {
      x: from.x + fromVector.x * fromOffset,
      y: from.y + fromVector.y * fromOffset
    };
    const toControl = {
      x: to.x + toVector.x * toOffset,
      y: to.y + toVector.y * toOffset
    };

    return `M ${from.x} ${from.y} C ${fromControl.x} ${fromControl.y} ${toControl.x} ${toControl.y} ${to.x} ${to.y}`;
  }

  window.DesktopCanvasGeometry = Object.freeze({
    CONNECTION_LEAD_LENGTH,
    CONNECTION_CORNER_RADIUS,
    clamp,
    normalizePortSide,
    oppositePortSide,
    dominantPortSide,
    getBoundsFromRects,
    getRectFromPoints,
    rectsIntersect,
    offsetPointForPort,
    compactOrthogonalPoints,
    roundedOrthogonalPath,
    getBackwardConnectionDetourY,
    makeSmoothStepPath,
    portOutwardVector,
    classicCurveControlOffset,
    makeClassicCurvePath
  });
})();
