// Temporary image-group paint only. The interaction controller owns time/RAF,
// containment, release and drop. This renderer owns only its overlay-local SVG
// definitions/parameter cache; it never reads image pixels or graph state.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const FLOW_FPS = 30;
  const FLOW_FRAMES = 36;
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const smoothstep = value => { const t = clamp(value, 0, 1); return t * t * (3 - 2 * t); };
  const svgUrl = body => 'data:image/svg+xml,' + encodeURIComponent(
    `<svg xmlns="${NS}" width="230" height="230" viewBox="0 0 230 230">${body}</svg>`);
  // These are synthetic coordinate fields, not photo copies. feImage fragment
  // references do not repaint reliably across HTML/SVG filters in Chromium;
  // self-contained data SVGs share the exact same local field on both surfaces.
  const coordinateUrl = vertical => svgUrl(`<defs><linearGradient id="v" x1="0" y1="0" x2="${vertical ? 0 : 1}" y2="${vertical ? 1 : 0}"><stop stop-color="${vertical ? '#00ff00' : '#ff0000'}"/><stop offset="1" stop-color="#000"/></linearGradient></defs><rect width="230" height="230" fill="url(#v)"/>`);

  function radialWaveUrl(frame) {
    const phase = frame / FLOW_FRAMES;
    const stops = [];
    // sin(k*r - omega*t) travels OUTWARDS; no random seeds or centre jitter.
    // A strictly positive wave and inward sampling vectors expand visible
    // pixels from the centre. Low-frequency masked noise breaks circular rims.
    for (let i = 0; i <= 48; i += 1) {
      const radius = i / 48 * Math.SQRT2 * 115;
      const wave = 0.24 + 0.76 * (0.5 + 0.5 * Math.sin(2 * Math.PI * (radius / 46 - phase)));
      const gray = Math.round(wave * 255);
      stops.push(`<stop offset="${i / 48}" stop-color="rgb(${gray},${gray},${gray})"/>`);
    }
    return svgUrl(`<defs><radialGradient id="w" gradientUnits="userSpaceOnUse" cx="115" cy="115" r="${Math.SQRT2 * 115}">${stops.join('')}</radialGradient></defs><rect width="230" height="230" fill="url(#w)"/>`);
  }

  function create(defs, id, image, outline) {
    const filter = document.createElementNS(NS, 'filter');
    for (const [key, value] of Object.entries({
      id, filterUnits: 'objectBoundingBox', primitiveUnits: 'userSpaceOnUse',
      x: '-65%', y: '-65%', width: '230%', height: '230%', 'color-interpolation-filters': 'sRGB'
    })) filter.setAttribute(key, value);
    filter.innerHTML = `<feOffset in="SourceAlpha" result="pullSeed"/>
      <feGaussianBlur in="pullSeed" result="pullField"/>
      <feColorMatrix in="pullField" type="matrix" result="pullMap"/>
      <feDisplacementMap in="SourceGraphic" in2="pullMap" scale="0" xChannelSelector="R" yChannelSelector="G" result="contactWarped"/>
      <feComponentTransfer in="pullField" result="smearField"><feFuncA type="linear" slope="1" intercept="0"/></feComponentTransfer>
      <feColorMatrix in="smearField" type="matrix" values="0 0 0 1 0  0 0 0 1 0  0 0 0 1 0  0 0 0 0 1" result="flowEnvelope"/>
      <feTurbulence type="fractalNoise" baseFrequency=".02 .03" numOctaves="2" seed="11" result="flowNoise"/>
      <feComponentTransfer in="flowNoise" result="opaqueNoise"><feFuncA type="linear" slope="0" intercept="1"/></feComponentTransfer>
      <feOffset in="opaqueNoise" result="movingNoise"/>
      <feComposite in="movingNoise" in2="flowEnvelope" operator="arithmetic" k1="1" k3="-.5" k4=".5" result="contactNoise"/>
      <feDisplacementMap in="contactWarped" in2="contactNoise" scale="0" xChannelSelector="R" yChannelSelector="G" result="edgeWarped"/>
      <feImage preserveAspectRatio="none" result="xCoordinates"/>
      <feImage preserveAspectRatio="none" result="yCoordinates"/>
      <feComposite in="xCoordinates" in2="yCoordinates" operator="arithmetic" k2="1" k3="1" result="coordinates"/>
      <feImage preserveAspectRatio="none" result="radialWave"/>
      <feComposite in="coordinates" in2="radialWave" operator="arithmetic" k1="1" k3="-.5" k4=".5" result="radialVectors"/>
      <feDisplacementMap in="edgeWarped" in2="radialVectors" scale="0" xChannelSelector="R" yChannelSelector="G" result="warped"/>
      <feGaussianBlur in="warped" result="smear"/>
      <feComposite in="smear" in2="smearField" operator="in" result="softContact"/>
      <feComposite in="warped" in2="smearField" operator="out" result="crisp"/>
      <feComposite in="softContact" in2="crisp" operator="arithmetic" k2="1" k3="1"/>`;
    defs.appendChild(filter);
    const part = name => filter.querySelector(`[result="${name}"]`);
    const xCoordinates = part('xCoordinates'), yCoordinates = part('yCoordinates'), wave = part('radialWave');
    xCoordinates.setAttribute('href', coordinateUrl(false));
    yCoordinates.setAttribute('href', coordinateUrl(true));
    // Initialise the third image before first paint, even at zero radial scale.
    const waves = [radialWaveUrl(0)];
    wave.setAttribute('href', waves[0]);
    return {
      id, image, filter, surfaces: [image, outline].filter(Boolean),
      offset: part('pullSeed'), field: part('pullField'), direction: part('pullMap'),
      warp: part('contactWarped'), noise: part('flowNoise'), noiseShift: part('movingNoise'),
      edgeWarp: part('edgeWarped'), radialWarp: part('warped'), maskAlpha: filter.querySelector('[result="smearField"] feFuncA'),
      smear: part('smear'), wave, fields: [xCoordinates, yCoordinates, wave], waves,
      signature: '', frame: -1, waveFrame: -1, flowSize: 0, enabled: false, animated: false, radialMix: 0
    };
  }

  function render(effect, normal, strength, size, coverage = 0, elapsedMs = 0) {
    const amount = clamp(Number(strength) || 0, 0, 1);
    if (amount < 0.002) {
      if (effect.enabled) effect.surfaces.forEach(surface => surface.style.removeProperty('filter'));
      effect.enabled = effect.animated = false;
      return;
    }
    const length = Math.hypot(normal.x, normal.y) || 1;
    const nx = normal.x / length, ny = normal.y / length;
    const side = Math.max(1, Number(size) || 1), whole = clamp(Number(coverage) || 0, 0, 1);
    // Keep the far side almost untouched while approaching/partly entering.
    // Only late containment spreads the field across the whole photo. Both
    // the spatial mask and radial scale meet continuously at full containment.
    const radialMix = smoothstep((whole - 0.45) / 0.55);
    const coverageKey = whole === 1 ? 'full' : whole === 0 ? 'contact' : String(whole);
    const signature = `${[nx, ny, amount, side].join(':')}:${coverageKey}`;
    if (signature !== effect.signature) {
      effect.offset.setAttribute('dx', String(-nx * side * 0.52 * (1 - whole * 0.4)));
      effect.offset.setAttribute('dy', String(-ny * side * 0.52 * (1 - whole * 0.4)));
      effect.field.setAttribute('stdDeviation', String(side * 0.14));
      effect.direction.setAttribute('values', `0 0 0 ${nx * 0.5} .5  0 0 0 ${ny * 0.5} .5  0 0 0 0 .5  0 0 0 0 1`);
      effect.warp.setAttribute('scale', String(side * 0.62 * (1 - radialMix) * amount));
      effect.noise.setAttribute('baseFrequency', `${1.8 / side} ${2.2 / side}`);
      effect.edgeWarp.setAttribute('scale', String(side * (0.48 + radialMix * 0.12) * amount));
      // Keep the radial gradient below a fold-over: large waves otherwise
      // split the circular alpha into disconnected islands instead of flowing.
      effect.radialWarp.setAttribute('scale', String(side * 0.5 * radialMix * amount));
      effect.maskAlpha.setAttribute('slope', String(1 - radialMix));
      effect.maskAlpha.setAttribute('intercept', String(radialMix));
      effect.smear.setAttribute('stdDeviation', `${side * (0.006 + Math.abs(nx) * 0.028 * (1 - radialMix) + radialMix * 0.02) * amount} ${side * (0.006 + Math.abs(ny) * 0.028 * (1 - radialMix) + radialMix * 0.02) * amount}`);
      effect.fields.forEach(field => {
        for (const [key, value] of Object.entries({ x: -side * 0.65, y: -side * 0.65, width: side * 2.3, height: side * 2.3 })) field.setAttribute(key, String(value));
      });
      effect.signature = signature;
    }
    // At most 36 tiny procedural SVGs per preview, reused after each 1.2s
    // cycle. Time is elapsed wall time, not a count of received RAF callbacks.
    const frame = Math.floor(Math.max(0, Number(elapsedMs) || 0) * FLOW_FPS / 1000) % FLOW_FRAMES;
    if (radialMix > 0 && effect.waveFrame !== frame) {
      effect.waves[frame] ||= radialWaveUrl(frame);
      effect.wave.setAttribute('href', effect.waves[frame]);
      effect.waveFrame = frame;
    }
    if (effect.frame !== frame || effect.flowSize !== side) {
      const phase = frame / FLOW_FRAMES * Math.PI * 2;
      effect.noiseShift.setAttribute('dx', String(side * 0.035 * Math.sin(phase)));
      effect.noiseShift.setAttribute('dy', String(side * 0.035 * Math.cos(phase)));
      effect.frame = frame;
      effect.flowSize = side;
    }
    if (!effect.enabled) effect.surfaces.forEach(surface => { surface.style.filter = `url(#${effect.id})`; });
    effect.enabled = true;
    effect.radialMix = radialMix;
    effect.animated = radialMix > 0;
  }

  window.DesktopCanvasImageGroupLiquidField = Object.freeze({ create, render });
})();
