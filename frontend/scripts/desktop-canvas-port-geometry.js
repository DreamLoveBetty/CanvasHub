// Canvas port shape and spring calculations; load before desktop-canvas.js.
// No DOM or application state. Spring and command-array mutations stay on the
// caller-supplied objects, preserving the original animation/path contracts.
(function () {
  const FLOATING_SWELL_SAMPLE_SPACING_PX = 1;
  const FLOATING_SWELL_LENGTH_PX = 38;
  const FLOATING_SWELL_PLATEAU_RATIO = 0.4;
  const FLOATING_SWELL_SHOULDER_RATIO = 0.3;
  const FLOATING_SWELL_VISIBLE_THRESHOLD_PX = 0.25;
  const FLOATING_SWELL_SPRING_STIFFNESS = 300;
  const FLOATING_SWELL_SPRING_DAMPING = 32;
  const FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS = 1 / 30;
  const FLOATING_DROPLET_BASE_HALF_LENGTH_PX = 15;
  const FLOATING_DROPLET_GRAVITY_PULL_PX = 7.2;
  const FLOATING_DROPLET_MOTION_PULL_PX = 4;
  const FLOATING_DROPLET_FLOW_EXTENSION_PX = 8;
  const FLOATING_DROPLET_ACTIVE_PADDING_PX = 5;
  const FLOATING_DROPLET_VELOCITY_NORMALIZER = 520;

  function floatingSwellModulo(value, length) {
    return ((value % length) + length) % length;
  }

  function floatingSwellShortestArcDelta(from, to, length) {
    const direct = floatingSwellModulo(to - from, length);
    return direct > length / 2 ? direct - length : direct;
  }

  function floatingSwellSmootherstep(value) {
    const clamped = Math.min(1, Math.max(0, value));
    return clamped * clamped * clamped * (clamped * (clamped * 6 - 15) + 10);
  }

  function floatingSwellSpringStep(spring, deltaSeconds) {
    const safeDelta = Math.min(
      FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS,
      Math.max(0, Number.isFinite(deltaSeconds) ? deltaSeconds : 0)
    );
    const force = FLOATING_SWELL_SPRING_STIFFNESS * (spring.target - spring.value)
      - FLOATING_SWELL_SPRING_DAMPING * spring.velocity;
    spring.velocity += force * safeDelta;
    spring.value += spring.velocity * safeDelta;
    if (!Number.isFinite(spring.value) || !Number.isFinite(spring.velocity)) {
      spring.value = spring.target;
      spring.velocity = 0;
    }
  }

  function floatingSwellSpringAtRest(spring) {
    return Math.abs(spring.target - spring.value) < 0.001 && Math.abs(spring.velocity) < 0.001;
  }

  function buildFloatingSwellPerimeter(width, height, requestedRadius, offsetX = 0, offsetY = 0) {
    const originX = Number.isFinite(Number(offsetX)) ? Number(offsetX) : 0;
    const originY = Number.isFinite(Number(offsetY)) ? Number(offsetY) : 0;
    const radius = Math.max(0, Math.min(requestedRadius, width / 2, height / 2));
    const horizontal = Math.max(0, width - radius * 2);
    const vertical = Math.max(0, height - radius * 2);
    const quarterArc = Math.PI * radius / 2;
    const segments = [];
    let arcLength = 0;
    const addLine = (length, startX, startY, tx, ty, nx, ny) => {
      if (length <= 0) return;
      segments.push({
        kind: 'line',
        startS: arcLength,
        length,
        pointAt: distance => ({
          x: startX + tx * distance,
          y: startY + ty * distance,
          nx,
          ny,
          tx,
          ty
        })
      });
      arcLength += length;
    };
    const addArc = (centerX, centerY, startAngle) => {
      if (quarterArc <= 0) return;
      segments.push({
        kind: 'arc',
        startS: arcLength,
        length: quarterArc,
        radius,
        pointAt: distance => {
          const angle = startAngle + distance / radius;
          return {
            x: centerX + Math.cos(angle) * radius,
            y: centerY + Math.sin(angle) * radius,
            nx: Math.cos(angle),
            ny: Math.sin(angle),
            tx: -Math.sin(angle),
            ty: Math.cos(angle)
          };
        }
      });
      arcLength += quarterArc;
    };

    if (radius > 0) {
      addLine(horizontal, originX + radius, originY, 1, 0, 0, -1);
      addArc(originX + width - radius, originY + radius, -Math.PI / 2);
      addLine(vertical, originX + width, originY + radius, 0, 1, 1, 0);
      addArc(originX + width - radius, originY + height - radius, 0);
      addLine(horizontal, originX + width - radius, originY + height, -1, 0, 0, 1);
      addArc(originX + radius, originY + height - radius, Math.PI / 2);
      addLine(vertical, originX, originY + height - radius, 0, -1, -1, 0);
      addArc(originX + radius, originY + radius, Math.PI);
    } else {
      addLine(width, originX, originY, 1, 0, 0, -1);
      addLine(height, originX + width, originY, 0, 1, 1, 0);
      addLine(width, originX + width, originY + height, -1, 0, 0, 1);
      addLine(height, originX, originY + height, 0, -1, -1, 0);
    }

    const samples = [];
    segments.forEach(segment => {
      const count = Math.max(1, Math.ceil(segment.length / FLOATING_SWELL_SAMPLE_SPACING_PX));
      for (let index = 0; index < count; index += 1) {
        const distance = index / count * segment.length;
        samples.push({ s: segment.startS + distance, ...segment.pointAt(distance) });
      }
    });
    return { samples, segments, length: arcLength };
  }

  function closestFloatingSwellSample(samples, x, y) {
    let closest = samples[0];
    let closestDistance = Number.POSITIVE_INFINITY;
    samples.forEach(sample => {
      const distance = (sample.x - x) ** 2 + (sample.y - y) ** 2;
      if (distance < closestDistance) {
        closest = sample;
        closestDistance = distance;
      }
    });
    return { sample: closest, distance: Math.sqrt(closestDistance) };
  }

  function floatingSwellPointAt(geometry, arcLength) {
    const normalized = floatingSwellModulo(arcLength, geometry.length);
    const segment = geometry.segments.find(candidate => (
      normalized >= candidate.startS && normalized < candidate.startS + candidate.length
    )) || geometry.segments[geometry.segments.length - 1];
    const local = normalized - segment.startS;
    return { segment, local, point: segment.pointAt(local) };
  }

  function floatingSwellDisplacementAt(arcLength, center, peak, perimeterLength) {
    const distance = Math.abs(floatingSwellShortestArcDelta(arcLength, center, perimeterLength));
    const plateauHalf = FLOATING_SWELL_LENGTH_PX * FLOATING_SWELL_PLATEAU_RATIO / 2;
    if (distance <= plateauHalf) return peak;
    const shoulder = FLOATING_SWELL_LENGTH_PX * FLOATING_SWELL_SHOULDER_RATIO;
    if (distance >= plateauHalf + shoulder) return 0;
    const progress = (distance - plateauHalf) / shoulder;
    const displacement = peak * (1 - floatingSwellSmootherstep(progress));
    return displacement < FLOATING_SWELL_VISIBLE_THRESHOLD_PX ? 0 : displacement;
  }

  function appendFloatingSwellExactPath(commands, geometry, startS, from, to) {
    let cursor = from;
    let iterations = 0;
    const maxIterations = Math.max(32, geometry.segments.length * 4);
    while (cursor < to - 0.0001 && iterations < maxIterations) {
      iterations += 1;
      const located = floatingSwellPointAt(geometry, startS + cursor);
      const available = located.segment.length - located.local;
      const step = Math.min(to - cursor, available);
      if (!Number.isFinite(step) || step <= 0) break;
      const nextCursor = cursor + step;
      if (nextCursor <= cursor) {
        cursor = Math.min(to, cursor + 0.0001);
        continue;
      }
      const end = located.segment.pointAt(located.local + step);
      commands.push(located.segment.kind === 'line'
        ? `L${end.x.toFixed(2)} ${end.y.toFixed(2)}`
        : `A${located.segment.radius.toFixed(2)} ${located.segment.radius.toFixed(2)} 0 0 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`);
      cursor = nextCursor;
    }
  }

  function appendFloatingSwellActivePath(commands, geometry, center, peak, startS, from, to) {
    const length = to - from;
    const count = Math.max(2, Math.ceil(length / FLOATING_SWELL_SAMPLE_SPACING_PX));
    const points = Array.from({ length: count + 1 }, (_, index) => {
      const relative = from + index / count * length;
      const located = floatingSwellPointAt(geometry, startS + relative);
      const displacement = floatingSwellDisplacementAt(
        floatingSwellModulo(startS + relative, geometry.length),
        center,
        peak,
        geometry.length
      );
      return {
        x: located.point.x + located.point.nx * displacement,
        y: located.point.y + located.point.ny * displacement,
        tx: located.point.tx,
        ty: located.point.ty
      };
    });
    for (let index = 0; index < points.length - 1; index += 1) {
      const previous = points[Math.max(0, index - 1)];
      const current = points[index];
      const next = points[index + 1];
      const after = points[Math.min(points.length - 1, index + 2)];
      const chord = Math.hypot(next.x - current.x, next.y - current.y);
      const control1 = index === 0
        ? { x: current.x + current.tx * chord / 3, y: current.y + current.ty * chord / 3 }
        : { x: current.x + (next.x - previous.x) / 6, y: current.y + (next.y - previous.y) / 6 };
      const control2 = index === points.length - 2
        ? { x: next.x - next.tx * chord / 3, y: next.y - next.ty * chord / 3 }
        : { x: next.x - (after.x - current.x) / 6, y: next.y - (after.y - current.y) / 6 };
      commands.push(
        `C${control1.x.toFixed(2)} ${control1.y.toFixed(2)} ${control2.x.toFixed(2)} ${control2.y.toFixed(2)} ${next.x.toFixed(2)} ${next.y.toFixed(2)}`
      );
    }
  }

  function buildFloatingSwellPath(geometry, center, peak) {
    if (!geometry?.segments?.length || geometry.length <= 0) return '';
    if (peak < FLOATING_SWELL_VISIBLE_THRESHOLD_PX) {
      const start = floatingSwellPointAt(geometry, 0).point;
      const commands = [`M${start.x.toFixed(2)} ${start.y.toFixed(2)}`];
      appendFloatingSwellExactPath(commands, geometry, 0, 0, geometry.length);
      commands.push('Z');
      return commands.join(' ');
    }
    const plateauHalf = FLOATING_SWELL_LENGTH_PX * FLOATING_SWELL_PLATEAU_RATIO / 2;
    const shoulder = FLOATING_SWELL_LENGTH_PX * FLOATING_SWELL_SHOULDER_RATIO;
    const activeHalf = plateauHalf + shoulder + 4;
    const startS = floatingSwellModulo(center + geometry.length / 2, geometry.length);
    const relativeCenter = floatingSwellModulo(center - startS, geometry.length);
    const intervalStart = Math.max(0, relativeCenter - activeHalf);
    const intervalEnd = Math.min(geometry.length, relativeCenter + activeHalf);
    const start = floatingSwellPointAt(geometry, startS).point;
    const commands = [`M${start.x.toFixed(2)} ${start.y.toFixed(2)}`];
    appendFloatingSwellExactPath(commands, geometry, startS, 0, intervalStart);
    appendFloatingSwellActivePath(commands, geometry, center, peak, startS, intervalStart, intervalEnd);
    appendFloatingSwellExactPath(commands, geometry, startS, intervalEnd, geometry.length);
    commands.push('Z');
    return commands.join(' ');
  }

  function buildFloatingDropletProfile(geometry, center, positionVelocity) {
    const frame = floatingSwellPointAt(geometry, center).point;
    const gravityNormal = Math.max(-1, Math.min(1, frame.ny));
    const gravityTangent = Math.max(-1, Math.min(1, frame.ty));
    const sideGravity = 1 - Math.abs(gravityNormal);
    const motion = Math.max(-1, Math.min(
      1,
      Number(positionVelocity || 0) / FLOATING_DROPLET_VELOCITY_NORMALIZER
    ));
    const halfLength = Math.max(
      10,
      FLOATING_DROPLET_BASE_HALF_LENGTH_PX - gravityNormal
    );
    return {
      center,
      frame,
      gravityNormal,
      gravityTangent,
      motion,
      halfLength,
      heightFactor: 0.78 + gravityNormal * 0.22 + sideGravity * 0.2,
      crownExponent: 0.82 + gravityNormal * 0.08,
      flow: Math.max(-1, Math.min(1, gravityTangent * 0.86 - motion * 0.72)),
      activeHalf: halfLength + FLOATING_DROPLET_FLOW_EXTENSION_PX + FLOATING_DROPLET_ACTIVE_PADDING_PX
    };
  }

  function floatingDropletPointAt(geometry, arcLength, peak, profile) {
    const located = floatingSwellPointAt(geometry, arcLength);
    const signedDistance = floatingSwellShortestArcDelta(
      profile.center,
      floatingSwellModulo(arcLength, geometry.length),
      geometry.length
    );
    const flowMagnitude = Math.abs(profile.flow);
    const flowsWithPoint = signedDistance * profile.flow >= 0;
    const directionalHalfLength = Math.max(
      6,
      profile.halfLength + (flowsWithPoint
        ? FLOATING_DROPLET_FLOW_EXTENSION_PX * flowMagnitude
        : -FLOATING_DROPLET_FLOW_EXTENSION_PX * 0.24 * flowMagnitude)
    );
    const normalizedDistance = Math.abs(signedDistance) / directionalHalfLength;
    if (!Number.isFinite(normalizedDistance) || normalizedDistance >= 1 || peak <= 0) {
      return {
        x: located.point.x,
        y: located.point.y,
        tx: located.point.tx,
        ty: located.point.ty,
        weight: 0
      };
    }
    const shoulder = Math.max(0, Math.min(
      1,
      1 - floatingSwellSmootherstep(normalizedDistance)
    ));
    const rawWeight = Math.pow(shoulder, profile.crownExponent);
    const weight = Number.isFinite(rawWeight) ? rawWeight : 0;
    const normalDisplacement = peak
      * profile.heightFactor
      * (1 + Math.abs(profile.motion) * 0.08)
      * weight;
    const tangentDisplacement = (
      profile.gravityTangent * FLOATING_DROPLET_GRAVITY_PULL_PX
      - profile.motion * FLOATING_DROPLET_MOTION_PULL_PX
    ) * weight;
    return {
      x: located.point.x
        + located.point.nx * normalDisplacement
        + profile.frame.tx * tangentDisplacement,
      y: located.point.y
        + located.point.ny * normalDisplacement
        + profile.frame.ty * tangentDisplacement,
      tx: located.point.tx,
      ty: located.point.ty,
      weight
    };
  }

  function appendFloatingDropletActivePath(commands, geometry, peak, profile, startS, from, to) {
    const length = to - from;
    const count = Math.max(2, Math.ceil(length / FLOATING_SWELL_SAMPLE_SPACING_PX));
    const points = Array.from({ length: count + 1 }, (_, index) => {
      const relative = from + index / count * length;
      return floatingDropletPointAt(geometry, startS + relative, peak, profile);
    });
    for (let index = 0; index < points.length - 1; index += 1) {
      const previous = points[Math.max(0, index - 1)];
      const current = points[index];
      const next = points[index + 1];
      const after = points[Math.min(points.length - 1, index + 2)];
      const chord = Math.hypot(next.x - current.x, next.y - current.y);
      const control1 = index === 0
        ? { x: current.x + current.tx * chord / 3, y: current.y + current.ty * chord / 3 }
        : { x: current.x + (next.x - previous.x) / 6, y: current.y + (next.y - previous.y) / 6 };
      const control2 = index === points.length - 2
        ? { x: next.x - next.tx * chord / 3, y: next.y - next.ty * chord / 3 }
        : { x: next.x - (after.x - current.x) / 6, y: next.y - (after.y - current.y) / 6 };
      commands.push(
        `C${control1.x.toFixed(2)} ${control1.y.toFixed(2)} ${control2.x.toFixed(2)} ${control2.y.toFixed(2)} ${next.x.toFixed(2)} ${next.y.toFixed(2)}`
      );
    }
  }

  function buildFloatingDropletPath(geometry, center, peak, positionVelocity) {
    if (!geometry?.segments?.length || geometry.length <= 0) return { path: '', anchor: null };
    const profile = buildFloatingDropletProfile(geometry, center, positionVelocity);
    const anchor = floatingDropletPointAt(geometry, center, peak, profile);
    if (peak < FLOATING_SWELL_VISIBLE_THRESHOLD_PX) {
      return { path: buildFloatingSwellPath(geometry, center, 0), anchor };
    }
    const startS = floatingSwellModulo(center + geometry.length / 2, geometry.length);
    const relativeCenter = floatingSwellModulo(center - startS, geometry.length);
    const intervalStart = Math.max(0, relativeCenter - profile.activeHalf);
    const intervalEnd = Math.min(geometry.length, relativeCenter + profile.activeHalf);
    const start = floatingSwellPointAt(geometry, startS).point;
    const commands = [`M${start.x.toFixed(2)} ${start.y.toFixed(2)}`];
    appendFloatingSwellExactPath(commands, geometry, startS, 0, intervalStart);
    appendFloatingDropletActivePath(commands, geometry, peak, profile, startS, intervalStart, intervalEnd);
    appendFloatingSwellExactPath(commands, geometry, startS, intervalEnd, geometry.length);
    commands.push('Z');
    return { path: commands.join(' '), anchor };
  }

  function floatingSwellSide(point) {
    return Math.abs(point.nx) > Math.abs(point.ny)
      ? (point.nx < 0 ? 'left' : 'right')
      : (point.ny < 0 ? 'top' : 'bottom');
  }

  window.DesktopCanvasPortGeometry = Object.freeze({
    FLOATING_SWELL_SAMPLE_SPACING_PX,
    FLOATING_SWELL_LENGTH_PX,
    FLOATING_SWELL_PLATEAU_RATIO,
    FLOATING_SWELL_SHOULDER_RATIO,
    FLOATING_SWELL_VISIBLE_THRESHOLD_PX,
    FLOATING_SWELL_SPRING_STIFFNESS,
    FLOATING_SWELL_SPRING_DAMPING,
    FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS,
    FLOATING_DROPLET_BASE_HALF_LENGTH_PX,
    FLOATING_DROPLET_GRAVITY_PULL_PX,
    FLOATING_DROPLET_MOTION_PULL_PX,
    FLOATING_DROPLET_FLOW_EXTENSION_PX,
    FLOATING_DROPLET_ACTIVE_PADDING_PX,
    FLOATING_DROPLET_VELOCITY_NORMALIZER,
    floatingSwellModulo,
    floatingSwellShortestArcDelta,
    floatingSwellSmootherstep,
    floatingSwellSpringStep,
    floatingSwellSpringAtRest,
    buildFloatingSwellPerimeter,
    closestFloatingSwellSample,
    floatingSwellPointAt,
    floatingSwellDisplacementAt,
    appendFloatingSwellExactPath,
    appendFloatingSwellActivePath,
    buildFloatingSwellPath,
    buildFloatingDropletProfile,
    floatingDropletPointAt,
    appendFloatingDropletActivePath,
    buildFloatingDropletPath,
    floatingSwellSide
  });
})();
