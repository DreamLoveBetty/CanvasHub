// Day/night reveal ripple, snapshot path: a View Transition keeps the real outgoing page
// outside the ripple, the incoming page is clipped to the wobbling outline, and both layers
// are refracted along the edge by an SVG displacement filter.
// desktop-preferences.js owns the run and calls frame()/dispose() exactly as for the
// fallback overlay in desktop-theme-ripple.js, whose outline maths and edge painter this
// path shares. The clip is a paused Web Animation on ::view-transition-new(root) scrubbed
// per frame (writing a property on <html> instead would restyle the whole document every
// frame); the displacement map is a small canvas re-encoded each frame into the feImage.
(function () {
  const FILTER_ID = 'deskThemeRippleRefraction';
  const EDGE_NAME = 'desk-theme-ripple-edge';
  const ROOT_FLAG = 'themeRipple';
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MAP_WIDTH = 256;
  const ANGLES = 360;
  const BAND = 64;
  // feDisplacementMap scale: pixels shift by at most half of it (~28px). Keep
  // REFRACTION / 2 * REFRACTION_GAIN / BAND near 1, or the steepest part of the ring folds
  // pixels over each other and text smears instead of bending.
  const REFRACTION = 56;
  const REFRACTION_GAIN = 2.3;
  const CLIP_KEYFRAMES = 84;
  const CLIP_POINTS = 64;
  // The hold animation keeps the transition alive past the run, which ends it explicitly.
  const HOLD_MARGIN_MS = 600;

  const ripple = () => window.DesktopThemeRipple;

  function supported() {
    return typeof document.startViewTransition === 'function'
      && typeof document.documentElement?.animate === 'function'
      && Boolean(ripple()?.supported?.());
  }

  // Per-run lookup tables for the low-resolution displacement map.
  function createField(origin, width, height, mapWidth = MAP_WIDTH) {
    const columns = mapWidth;
    const rows = Math.max(1, Math.round((mapWidth * height) / width));
    const count = columns * rows;
    const field = {
      columns, rows,
      distance: new Float32Array(count),
      angle: new Uint16Array(count),
      dirX: new Float32Array(count),
      dirY: new Float32Array(count),
    };
    const stepX = width / columns;
    const stepY = height / rows;
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const index = row * columns + column;
        const x = (column + 0.5) * stepX - origin.x;
        const y = (row + 0.5) * stepY - origin.y;
        const distance = Math.hypot(x, y) || 1;
        let theta = Math.atan2(y, x);
        if (theta < 0) theta += Math.PI * 2;
        field.distance[index] = distance;
        field.dirX[index] = x / distance;
        field.dirY[index] = y / distance;
        field.angle[index] = Math.floor((theta / (Math.PI * 2)) * ANGLES) % ANGLES;
      }
    }
    return field;
  }

  // Radial push that is zero on the edge itself and peaks just inside/outside it, like a
  // lens ring: R/G carry x/y displacement around the neutral 128, everything else is still.
  function fillDisplacement(field, radii, strength, data, band = BAND) {
    for (let index = 0, offset = 0; index < field.distance.length; index += 1, offset += 4) {
      const u = (field.distance[index] - radii[field.angle[index]]) / band;
      const push = u > -3 && u < 3 ? -u * Math.exp(-u * u) * REFRACTION_GAIN * strength : 0;
      data[offset] = 128 + 127 * push * field.dirX[index];
      data[offset + 1] = 128 + 127 * push * field.dirY[index];
      data[offset + 2] = 128;
      data[offset + 3] = 255;
    }
    return data;
  }

  function clipKeyframes(origin, reach, duration, ease, phases, steps = CLIP_KEYFRAMES) {
    const R = ripple();
    const frames = [];
    for (let step = 0; step <= steps; step += 1) {
      const progress = step / steps;
      const points = R.outline(origin, reach * ease(progress), (progress * duration) / 1000, phases, CLIP_POINTS);
      frames.push({ clipPath: `path("${R.blobPath(points)}")` });
    }
    return frames;
  }

  function filterSvg(width, height) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'desk-theme-ripple-filter');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.innerHTML = `<filter id="${FILTER_ID}" x="0" y="0" width="${width}" height="${height}"`
      + ' filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" color-interpolation-filters="sRGB">'
      + `<feImage x="0" y="0" width="${width}" height="${height}" preserveAspectRatio="none" result="map"/>`
      + `<feDisplacementMap in="SourceGraphic" in2="map" scale="${REFRACTION}" xChannelSelector="R" yChannelSelector="G"/>`
      + '</filter>';
    return svg;
  }

  function create({ origin, endRadius, fromTheme = 'light', duration, ease, apply, phases } = {}) {
    const R = ripple();
    const runPhases = phases || R.randomPhases();
    const reach = R.reachFor(endRadius);
    const width = window.innerWidth;
    const height = window.innerHeight;
    const root = document.documentElement;
    const field = createField(origin, width, height);
    const map = document.createElement('canvas');
    map.width = field.columns;
    map.height = field.rows;
    const mapContext = map.getContext('2d');
    const image = mapContext.createImageData(field.columns, field.rows);
    const radii = new Float32Array(ANGLES);
    const svg = filterSvg(width, height);
    const feImage = svg.querySelector('feImage');
    const edge = R.createEdge({ fromTheme, width, height });
    edge.canvas.style.viewTransitionName = EDGE_NAME;
    let clip = null;
    let hold = null;
    let pending = null;
    let disposed = false;

    function cleanup() {
      clip?.cancel();
      hold?.cancel();
      edge.dispose();
      svg.remove();
      if (root.dataset[ROOT_FLAG] === 'snapshot') delete root.dataset[ROOT_FLAG];
    }

    function frame(progress, eased, seconds) {
      if (disposed) return;
      if (!clip) {
        pending = [progress, eased, seconds];
        return;
      }
      clip.currentTime = progress * duration;
      const base = reach * eased;
      for (let index = 0; index < ANGLES; index += 1) {
        radii[index] = R.radiusAt((index / ANGLES) * Math.PI * 2, seconds, base, runPhases);
      }
      const strength = R.bandStrength(progress);
      fillDisplacement(field, radii, strength, image.data);
      mapContext.putImageData(image, 0, 0);
      feImage.setAttribute('href', map.toDataURL());
      edge.paint(R.outline(origin, base, seconds, runPhases), strength);
    }

    document.body.appendChild(svg);
    root.dataset[ROOT_FLAG] = 'snapshot';
    const transition = document.startViewTransition(() => {
      apply();
      if (!disposed) document.body.appendChild(edge.canvas);
    });
    transition.ready.then(() => {
      if (disposed) return;
      hold = root.animate([{ opacity: 1 }, { opacity: 1 }], {
        duration: duration + HOLD_MARGIN_MS,
        pseudoElement: '::view-transition-group(root)',
      });
      clip = root.animate(clipKeyframes(origin, reach, duration, ease, runPhases), {
        duration,
        fill: 'both',
        pseudoElement: '::view-transition-new(root)',
      });
      clip.pause();
      if (pending) frame(...pending);
    }).catch(() => {});
    // A skipped transition (hidden tab, a newer transition) still runs apply(); just tidy up.
    transition.finished.catch(() => {}).finally(cleanup);

    function dispose() {
      if (disposed) return;
      disposed = true;
      transition.skipTransition();
      cleanup();
    }

    return Object.freeze({ frame, dispose, canvas: edge.canvas });
  }

  window.DesktopThemeRippleSnapshot = Object.freeze({
    create,
    supported,
    createField,
    fillDisplacement,
    clipKeyframes,
    FILTER_ID,
    EDGE_NAME,
  });
})();
