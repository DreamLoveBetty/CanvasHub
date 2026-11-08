// Day/night reveal ripple: the wobbling, water-like edge shared by both reveal paths.
// desktop-preferences.js owns the run (timing, cancel, theme state) and calls frame() once
// per animation frame. This module holds the outline maths and the edge band painter, and
// runs the fallback path: an evenodd clip-path cut into the painted overlay. The snapshot
// path (real page, refraction) lives in desktop-theme-ripple-snapshot.js.
(function () {
  const POINTS = 96;
  const MAX_AMPLITUDE = 80;
  const AMPLITUDE_RATIO = 0.16;
  // Integer angular frequencies keep the outline closed; each term drifts at its own speed.
  const WAVES = [
    { frequency: 2, weight: 0.5, speed: 4.6 },
    { frequency: 3, weight: 0.32, speed: -6.8 },
    { frequency: 7, weight: 0.18, speed: 10.2 },
  ];
  // Ten centred strokes of growing width, each clipped to one side of the edge, stack into a
  // band that fades over BAND_REACH px; the CSS colour's alpha is roughly its peak.
  const BAND_STEPS = 10;
  const BAND_REACH = 28;

  function supported() {
    try {
      return Boolean(window.CSS?.supports?.('clip-path', 'path(evenodd, "M0 0H1V1Z")'));
    } catch (e) {
      return false;
    }
  }

  function amplitudeFor(base) {
    return Math.min(MAX_AMPLITUDE, Math.max(0, base) * AMPLITUDE_RATIO);
  }

  function radiusAt(theta, seconds, base, phases) {
    let offset = 0;
    WAVES.forEach((wave, index) => {
      offset += wave.weight * Math.sin(wave.frequency * theta + phases[index] + wave.speed * seconds);
    });
    return Math.max(0, base + amplitudeFor(base) * offset);
  }

  function outline(origin, base, seconds, phases, count = POINTS) {
    const points = [];
    for (let index = 0; index < count; index += 1) {
      const theta = (index / count) * Math.PI * 2;
      const radius = radiusAt(theta, seconds, base, phases);
      points.push([origin.x + Math.cos(theta) * radius, origin.y + Math.sin(theta) * radius]);
    }
    return points;
  }

  const fixed = value => Math.round(value * 10) / 10;

  // Closed quadratic spline through the midpoints, so the edge stays smooth at any radius.
  function blobPath(points) {
    if (!points.length) return '';
    const mid = (a, b) => [fixed((a[0] + b[0]) / 2), fixed((a[1] + b[1]) / 2)];
    const last = points[points.length - 1];
    let path = `M${mid(last, points[0]).join(' ')}`;
    points.forEach((point, index) => {
      const next = points[(index + 1) % points.length];
      path += `Q${fixed(point[0])} ${fixed(point[1])} ${mid(point, next).join(' ')}`;
    });
    return `${path}Z`;
  }

  // Viewport rectangle minus the blob: the overlay keeps the old theme outside the ripple.
  function holePath(width, height, points) {
    return `M0 0H${fixed(width)}V${fixed(height)}H0Z${blobPath(points)}`;
  }

  // The band fades in as the ripple leaves the click point and out before the overlay goes.
  function bandStrength(progress) {
    const p = Math.min(1, Math.max(0, progress));
    return Math.min(1, p / 0.12, (1 - p) / 0.22);
  }

  function randomPhases() {
    return WAVES.map(() => Math.random() * Math.PI * 2);
  }

  // Reach past the farthest corner even where the wobble dips inward.
  function reachFor(endRadius) {
    return endRadius + MAX_AMPLITUDE;
  }

  // Shade/glint/rim band along the edge, on its own viewport canvas. The caller mounts the
  // canvas; colours come from --desk-theme-ripple-* and are read on the first paint, once
  // the canvas is in the document.
  function createEdge({ fromTheme = 'light', width = window.innerWidth, height = window.innerHeight } = {}) {
    const canvas = document.createElement('canvas');
    canvas.className = 'desk-theme-ripple-edge';
    canvas.dataset.from = fromTheme;
    canvas.setAttribute('aria-hidden', 'true');
    const scale = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const context = canvas.getContext('2d');
    let colors = null;

    function readColors() {
      const style = getComputedStyle(canvas);
      return {
        shade: style.getPropertyValue('--desk-theme-ripple-shade').trim() || 'rgba(0, 0, 0, 0.25)',
        glint: style.getPropertyValue('--desk-theme-ripple-glint').trim() || 'rgba(255, 255, 255, 0.1)',
        rim: style.getPropertyValue('--desk-theme-ripple-rim').trim() || 'rgba(255, 255, 255, 0.4)',
      };
    }

    function paint(points, strength) {
      if (!context || !canvas.isConnected) return;
      colors ||= readColors();
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.clearRect(0, 0, width, height);
      if (strength <= 0 || typeof Path2D !== 'function') return;
      const blob = new Path2D(blobPath(points));
      const outside = new Path2D(holePath(width, height, points));
      [[outside, colors.shade], [blob, colors.glint]].forEach(([region, color]) => {
        context.save();
        context.clip(region, 'evenodd');
        context.strokeStyle = color;
        context.globalAlpha = strength / BAND_STEPS;
        for (let step = 1; step <= BAND_STEPS; step += 1) {
          context.lineWidth = (2 * BAND_REACH * step) / BAND_STEPS;
          context.stroke(blob);
        }
        context.restore();
      });
      context.globalAlpha = strength;
      context.lineWidth = 1.25;
      context.strokeStyle = colors.rim;
      context.stroke(blob);
      context.globalAlpha = 1;
    }

    return Object.freeze({ canvas, paint, dispose: () => canvas.remove() });
  }

  // Fallback reveal: a painted stand-in for the outgoing theme with the ripple cut out of it.
  function create({ overlay, origin, endRadius, fromTheme = 'light', phases } = {}) {
    const runPhases = phases || randomPhases();
    const reach = reachFor(endRadius);
    const width = window.innerWidth;
    const height = window.innerHeight;
    const edge = createEdge({ fromTheme, width, height });
    overlay.after(edge.canvas);

    function frame(progress, eased, seconds) {
      const points = outline(origin, reach * eased, seconds, runPhases);
      overlay.style.clipPath = `path(evenodd, "${holePath(width, height, points)}")`;
      edge.paint(points, bandStrength(progress));
    }

    return Object.freeze({ frame, dispose: edge.dispose, canvas: edge.canvas });
  }

  window.DesktopThemeRipple = Object.freeze({
    create,
    createEdge,
    randomPhases,
    reachFor,
    supported,
    radiusAt,
    outline,
    blobPath,
    holePath,
    bandStrength,
    amplitudeFor,
    MAX_AMPLITUDE,
  });
})();
