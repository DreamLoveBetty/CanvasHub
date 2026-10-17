// Image-group "melt" paint: the incoming photo and its neighbour run molten into each
// other where they touch. A vanilla port of the image melt in liquid-gooey
// (packages/liquid-gooey/src/imageMelt.tsx, MIT, Copyright (c) 2026 Jakub; see
// frontend/vendor/liquid-gooey/). Pure paint: the interaction controller owns time,
// the single RAF, partner choice and the eased proximity; this module never reads
// graph state, starts timers or queries the DOM. The SVG covers only the pair's
// bounding box plus the reach of its filters.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const DEFAULTS = Object.freeze({
    blur: 7, contrast: 40, reach: 0.8, fade: 17, warp: 0,
    mix: 1, mixBlur: 8, gravity: 1.9, waviness: 12
  });
  // liquid-gooey's pixel tunings target 84px cards; they scale with the card size.
  const BASE_SIZE = 84;
  let sequence = 0;

  const el = (name, attrs = {}, children = []) => {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    children.forEach(child => node.appendChild(child));
    return node;
  };
  const set = (node, attrs) => {
    for (const [key, value] of Object.entries(attrs)) {
      const text = String(value);
      if (node.getAttribute(key) !== text) node.setAttribute(key, text);
    }
  };
  const round = (value, step = 10) => Math.round(value * step) / step;
  const sizeScale = (a, b) => Math.max(0.05, Math.min(a.w, b.w) / BASE_SIZE);

  /** Proximity target of a pair: 0 apart .. 1 touching (liquid-gooey's smoothstep). */
  function proximity(a, b, opts = DEFAULTS) {
    const ca = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
    const cb = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
    const gap = Math.max(0, Math.hypot(
      Math.max(Math.abs(ca.x - cb.x) - (a.w + b.w) / 2, 0),
      Math.max(Math.abs(ca.y - cb.y) - (a.h + b.h) / 2, 0)));
    const blur = (Number(opts.blur) || DEFAULTS.blur) * sizeScale(a, b);
    const near = Math.max(0, Math.min(1, 1 - gap / Math.max(8, blur * 2.6)));
    return near * near * (3 - 2 * near);
  }

  function create(container) {
    const id = `desk-image-group-melt-${++sequence}`;
    const svg = el('svg', { 'aria-hidden': 'true', focusable: 'false', class: 'desk-image-group-melt' });
    svg.style.cssText = 'position:absolute;left:0;top:0;overflow:visible;pointer-events:none';
    const card = key => {
      const imageRect = el('rect', { fill: `url(#${id}-p${key})` });
      return { group: el('g', {}, [imageRect]), imageRect };
    };
    const imageA = el('image', { preserveAspectRatio: 'xMidYMid slice' });
    const imageB = el('image', { preserveAspectRatio: 'xMidYMid slice' });
    const patternA = el('pattern', { id: `${id}-pa`, patternUnits: 'userSpaceOnUse' }, [imageA]);
    const patternB = el('pattern', { id: `${id}-pb`, patternUnits: 'userSpaceOnUse' }, [imageB]);

    // Molten layer: goo on colour (wide colour blur clipped to the goo silhouette).
    const gooBlur = el('feGaussianBlur', { in: 'SourceGraphic', result: 'b' });
    const gooMatrix = el('feColorMatrix', { in: 'b', type: 'matrix', result: 'goo' });
    const gooColor = el('feGaussianBlur', { in: 'SourceGraphic', result: 'bc' });
    const gooNoise = el('feTurbulence', { type: 'fractalNoise', numOctaves: 2, seed: 4, result: 'wn' });
    const gooWarp = el('feDisplacementMap', { in: 'mix', in2: 'wn', xChannelSelector: 'R', yChannelSelector: 'G', result: 'warped' });
    const goo = el('filter', { id: `${id}-goo`, x: '-15%', y: '-15%', width: '130%', height: '130%', 'color-interpolation-filters': 'sRGB' }, [
      gooBlur, gooMatrix, gooColor,
      el('feComposite', { in: 'bc', in2: 'goo', operator: 'in', result: 'mix' }),
      gooNoise, gooWarp,
      el('feComposite', { in: 'warped', in2: 'warped', operator: 'over', result: 's1' }),
      el('feComposite', { in: 's1', in2: 's1', operator: 'over', result: 's2' }),
      el('feComposite', { in: 's2', in2: 's2', operator: 'over', result: 'solid' }),
      el('feGaussianBlur', { in: 'solid', stdDeviation: 0.6 })
    ]);
    const softBlur = el('feGaussianBlur', {});
    const soft = el('filter', { id: `${id}-soft`, x: '-60%', y: '-60%', width: '220%', height: '220%' }, [softBlur]);
    // Marble layer: nested large-scale displacements fold the two palettes into streaks.
    const marbleColor = el('feGaussianBlur', { in: 'SourceGraphic', result: 'c' });
    const marbleNoise1 = el('feTurbulence', { type: 'fractalNoise', numOctaves: 2, seed: 5, result: 'n1' });
    const marbleWarp1 = el('feDisplacementMap', { in: 'c', in2: 'n1', xChannelSelector: 'R', yChannelSelector: 'G', result: 'd1' });
    const marbleNoise2 = el('feTurbulence', { type: 'fractalNoise', numOctaves: 2, seed: 11, result: 'n2' });
    const marbleWarp2 = el('feDisplacementMap', { in: 'd1', in2: 'n2', xChannelSelector: 'R', yChannelSelector: 'G', result: 'd2' });
    const marbleShapeBlur = el('feGaussianBlur', { in: 'SourceGraphic', result: 'mb' });
    const marbleShapeMatrix = el('feColorMatrix', { in: 'mb', type: 'matrix', result: 'mg' });
    const marbleShapeNoise = el('feTurbulence', { type: 'fractalNoise', numOctaves: 2, seed: 4, result: 'mwn' });
    const marbleShapeWarp = el('feDisplacementMap', { in: 'mg', in2: 'mwn', xChannelSelector: 'R', yChannelSelector: 'G', result: 'mshape' });
    const marble = el('filter', { id: `${id}-marble`, x: '-25%', y: '-25%', width: '150%', height: '150%', 'color-interpolation-filters': 'sRGB' }, [
      marbleColor, marbleNoise1, marbleWarp1, marbleNoise2, marbleWarp2,
      el('feComposite', { in: 'd2', in2: 'd2', operator: 'over', result: 'm1' }),
      el('feComposite', { in: 'm1', in2: 'm1', operator: 'over', result: 'm2' }),
      el('feGaussianBlur', { in: 'm2', stdDeviation: 0.6, result: 'marble' }),
      marbleShapeBlur, marbleShapeMatrix, marbleShapeNoise, marbleShapeWarp,
      el('feComposite', { in: 'marble', in2: 'mshape', operator: 'in' })
    ]);
    const marbleEllipse = el('ellipse', { fill: '#fff' });
    const marbleMask = el('mask', { id: `${id}-marblemask`, maskUnits: 'userSpaceOnUse', x: 0, y: 0 }, [
      el('g', { filter: `url(#${id}-soft)` }, [marbleEllipse])
    ]);
    const edgeBlur = el('feGaussianBlur', {});
    const edge = el('filter', { id: `${id}-edge`, x: '-40%', y: '-40%', width: '180%', height: '180%' }, [edgeBlur]);
    // Crisp faces: each card minus a blurred seam-spanning erase ellipse; apart, a card
    // is exactly a card.
    const faceMask = key => {
      const shape = el('rect', { fill: '#fff' });
      const shapeGroup = el('g', {}, [shape]);
      const erase = el('ellipse', { fill: '#000' });
      const mask = el('mask', { id: `${id}-m${key}`, maskUnits: 'userSpaceOnUse', x: 0, y: 0 }, [
        el('g', { filter: `url(#${id}-edge)` }, [shapeGroup]),
        el('g', { filter: `url(#${id}-soft)` }, [erase])
      ]);
      return { mask, shape, shapeGroup, erase };
    };
    const maskA = faceMask('a');
    const maskB = faceMask('b');
    svg.appendChild(el('defs', {}, [patternA, patternB, goo, soft, marble, marbleMask, edge, maskA.mask, maskB.mask]));

    const molten = [card('a'), card('b')];
    const marbled = [card('a'), card('b')];
    const crispA = card('a');
    const crispB = card('b');
    const marbleLayer = el('g', { mask: `url(#${id}-marblemask)` }, [
      el('g', { filter: `url(#${id}-marble)` }, marbled.map(item => item.group))
    ]);
    svg.append(
      el('g', { filter: `url(#${id}-goo)` }, molten.map(item => item.group)),
      marbleLayer,
      el('g', { mask: `url(#${id}-ma)` }, [crispA.group]),
      el('g', { mask: `url(#${id}-mb)` }, [crispB.group])
    );
    container.appendChild(svg);
    const cardsA = [molten[0], marbled[0], crispA];
    const cardsB = [molten[1], marbled[1], crispB];
    const sources = ['', ''];

    /**
     * a, b: { x, y, w, h, r, src } in the container's coordinates.
     * prox: eased 0..1 from the controller. Returns the painted box.
     */
    function update({ a, b, prox, opts = DEFAULTS }) {
      const o = { ...DEFAULTS, ...opts };
      const amount = Math.max(0, Math.min(1, Number(prox) || 0));
      const k = sizeScale(a, b);
      const blur = o.blur * k, fade = o.fade * k, mixBlur = o.mixBlur * k, warp = o.warp * k;
      const intercept = Math.round((0.5 - o.contrast * (5 / 12)) * 100) / 100;
      const matrix = `1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 ${o.contrast} ${intercept}`;
      const blurEff = round(2 * k + (blur - 2 * k) * amount);
      const warpEff = round(warp * amount);
      const colorBlur = round(blurEff * 2.5);
      const edgeSoft = round(0.4 + (2 * k + blur * 0.8) * amount);
      const mixAmt = Math.round(o.mix * amount * 100) / 100;
      const baseFrequency = (2 + o.waviness * 1.2) / 1000 / Math.max(0.25, k);

      // Bounding box of the pair plus what can paint outside the cards: the goo blur
      // and the face edge blur. The marble pass is clipped into the goo silhouette and
      // the fade blurs only masks, so neither reaches further out.
      const pad = Math.ceil(Math.max(blurEff, edgeSoft) * 3 + warpEff + 4);
      const ox = Math.floor(Math.min(a.x, b.x) - pad);
      const oy = Math.floor(Math.min(a.y, b.y) - pad);
      const width = Math.ceil(Math.max(a.x + a.w, b.x + b.w) + pad) - ox;
      const height = Math.ceil(Math.max(a.y + a.h, b.y + b.h) + pad) - oy;
      svg.style.transform = `translate(${ox}px, ${oy}px)`;
      set(svg, { width, height, viewBox: `0 0 ${width} ${height}` });
      const A = { ...a, x: a.x - ox, y: a.y - oy };
      const B = { ...b, x: b.x - ox, y: b.y - oy };

      const ca = { x: A.x + A.w / 2, y: A.y + A.h / 2 };
      const cb = { x: B.x + B.w / 2, y: B.y + B.h / 2 };
      const rA = Math.hypot(A.w, A.h) / 2 * o.reach * amount;
      const rB = Math.hypot(B.w, B.h) / 2 * o.reach * amount;
      const seam = { x: round((ca.x + cb.x) / 2, 100), y: round((ca.y + cb.y) / 2, 100) };
      const dx = cb.x - ca.x, dy = cb.y - ca.y, distance = Math.max(1e-3, Math.hypot(dx, dy));
      const tx = -dy / distance, ty = dx / distance;
      const overlapX = Math.max(0, (A.w + B.w) / 2 - Math.abs(dx));
      const overlapY = Math.max(0, (A.h + B.h) / 2 - Math.abs(dy));
      const tanHalf = 0.5 * (overlapX * Math.abs(tx) + overlapY * Math.abs(ty)) * amount;
      const rotate = `rotate(${Math.round(Math.atan2(ty, tx) * 180 / Math.PI)}, ${seam.x}, ${seam.y})`;

      const place = (cards, g, pattern, image, index) => {
        set(pattern, { width: g.w, height: g.h });
        set(image, { width: g.w, height: g.h });
        if (sources[index] !== g.src) {
          image.setAttribute('href', g.src);
          sources[index] = g.src;
        }
        cards.forEach(item => {
          set(item.group, { transform: `translate(${round(g.x, 100)}, ${round(g.y, 100)})` });
          set(item.imageRect, { width: g.w, height: g.h, rx: g.r });
        });
      };
      place(cardsA, A, patternA, imageA, 0);
      place(cardsB, B, patternB, imageB, 1);

      set(gooBlur, { stdDeviation: blurEff });
      set(gooMatrix, { values: matrix });
      set(gooColor, { stdDeviation: colorBlur });
      set(gooNoise, { baseFrequency });
      set(gooWarp, { scale: warpEff });
      set(softBlur, { stdDeviation: fade });
      set(edgeBlur, { stdDeviation: edgeSoft });
      const marbleOn = mixAmt > 0.01;
      marbleLayer.style.display = marbleOn ? '' : 'none';
      if (marbleOn) {
        set(marbleColor, { stdDeviation: mixBlur });
        set(marbleNoise1, { baseFrequency: 0.011 / Math.max(0.25, k) });
        set(marbleNoise2, { baseFrequency: 0.019 / Math.max(0.25, k) });
        set(marbleWarp1, { scale: round(mixAmt * 90 * k) });
        set(marbleWarp2, { scale: round(mixAmt * 50 * k) });
        set(marbleShapeBlur, { stdDeviation: blurEff });
        set(marbleShapeMatrix, { values: matrix });
        set(marbleShapeNoise, { baseFrequency });
        set(marbleShapeWarp, { scale: warpEff });
        set(marbleMask, { width, height });
        set(marbleEllipse, {
          cx: seam.x, cy: seam.y, transform: rotate,
          rx: round((rA + rB) / 2 + tanHalf, 100), ry: round((rA + rB) / 2 * o.gravity, 100)
        });
      }
      for (const [mask, g, r] of [[maskA, A, rB], [maskB, B, rA]]) {
        set(mask.mask, { width, height });
        set(mask.shapeGroup, { transform: `translate(${round(g.x, 100)}, ${round(g.y, 100)})` });
        set(mask.shape, { width: g.w, height: g.h, rx: g.r });
        set(mask.erase, { cx: seam.x, cy: seam.y, rx: round(r + tanHalf, 100), ry: round(r, 100), transform: rotate });
      }
      return { x: ox, y: oy, width, height };
    }

    return Object.freeze({
      update,
      setVisible(visible) { svg.style.display = visible ? '' : 'none'; },
      destroy() { svg.remove(); }
    });
  }

  window.DesktopCanvasImageGroupMelt = Object.freeze({ create, proximity, DEFAULTS });
})();
