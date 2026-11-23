// Stepped speed slider whose thumb is a sculpted viscous slime humanoid:
// at the slowest end it trudges heavily through thick sticky slime tethered to a pooled puddle,
// and as speed increases it stretches into an aerodynamic sprint with whipped slime ribbons
// and flying droplets flung behind. Owns its markup, biomechanics, procedural SVG + track
// canvas rendering, and IntersectionObserver-gated animation clock.
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const PAD = 10;
  // ViewBox anchored with y = 0 on the ground plane; +x is forward (right), -y is up.
  // SVG uses overflow:visible so whipped sprint tendrils and flying blobs stream freely behind.
  const VIEWBOX = { x: -50, y: -50, width: 72, height: 55 };
  const RUNNER_WIDTH = 48;
  const RUNNER_SCALE = RUNNER_WIDTH / VIEWBOX.width;
  const L_THIGH = 10.6;
  const L_SHIN = 10.6;
  const L_TORSO = 13.4;
  const L_UPPER = 7.4;
  const L_FORE = 7.0;
  const HEAD_R = 5.8;
  let instanceCounter = 0;

  const rad = degrees => (degrees * Math.PI) / 180;
  const lerp = (a, b, t) => a + (b - a) * t;
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  const fixed = n => (Number.isFinite(n) ? n : 0).toFixed(2);

  // s = 0 viscous sticky trudge … 1 full aerodynamic slime sprint.
  function gait(s) {
    const t = clamp(s, 0, 1);
    const g = smooth(0.22, 0.78, t);
    const sticky = 1 - smooth(0.06, 0.56, t);
    const whip = smooth(0.4, 1, t);
    return {
      g,
      sticky,
      whip,
      thigh: rad(lerp(29, 57, t)),
      kneeMin: rad(lerp(8, 22, g)),
      kneeMax: rad(lerp(64, 144, g)),
      lean: rad(lerp(7.0, 32.5, Math.pow(t, 1.18))),
      arm: rad(lerp(28, 64, t)),
      elbow: rad(lerp(16, 98, g)),
      elbowSwing: rad(lerp(6, 22, g)),
      lift: lerp(0, 4.4, g),
      cadence: lerp(0.62, 2.65, t),
    };
  }

  // At slow speed, warp stride phase so each foot lingers stuck in the puddle,
  // peels upward with heavy viscous hesitation, then settles softly back down.
  function viscousPhase(phase, sticky) {
    if (sticky <= 0.001) return phase;
    return phase - sticky * 0.3 * Math.sin(2 * phase);
  }

  function leg(p, phase) {
    const ph = viscousPhase(phase, p.sticky);
    const thigh = p.thigh * Math.sin(ph);
    // At slow sticky speed, peak knee peel slightly earlier as the rear foot pulls out of the puddle.
    const swing = Math.max(0, Math.cos(ph + lerp(0.36, 0.54, p.sticky)));
    const kneeCurve = Math.pow(swing, lerp(1.38, 1.2, p.g));
    const knee = p.kneeMin + (p.kneeMax - p.kneeMin) * kneeCurve;
    const kneeAt = [L_THIGH * Math.sin(thigh), L_THIGH * Math.cos(thigh)];
    const shin = thigh - knee;
    const foot = [kneeAt[0] + L_SHIN * Math.sin(shin), kneeAt[1] + L_SHIN * Math.cos(shin)];
    const toeLen = lerp(3.6, 4.0, p.g);
    const toe = [foot[0] + toeLen * Math.cos(shin), foot[1] - toeLen * Math.sin(shin)];
    return { knee: kneeAt, foot, toe, swing };
  }

  function arm(p, shoulder, phase) {
    const ph = viscousPhase(phase, p.sticky);
    const reachForward = p.sticky * rad(8);
    const upper = p.lean * 0.4 + p.arm * Math.sin(ph) + reachForward;
    const bend = p.elbow + p.elbowSwing * Math.max(0, Math.sin(ph));
    const elbow = [shoulder[0] + L_UPPER * Math.sin(upper), shoulder[1] + L_UPPER * Math.cos(upper)];
    const hand = [elbow[0] + L_FORE * Math.sin(upper + bend), elbow[1] + L_FORE * Math.cos(upper + bend)];
    return { elbow, hand };
  }

  // Joint positions with y = 0 on the ground: at s = 0 a foot stays grounded in the puddle;
  // at s = 1 the sprinter drives cleanly into an airborne flight phase.
  function pose(s, phase) {
    const p = gait(s);
    const near = leg(p, phase);
    const far = leg(p, phase + Math.PI);
    const lowest = Math.max(near.foot[1], near.toe[1], far.foot[1], far.toe[1]);
    const flight = p.lift * (0.5 - 0.5 * Math.cos(2 * phase));
    const hip = [0, -lowest - flight];
    const at = point => [hip[0] + point[0], hip[1] + point[1]];
    const stepPulse = Math.cos(2 * phase);
    const squash = p.sticky * (0.16 + 0.08 * stepPulse) - p.whip * (0.06 + 0.05 * Math.sin(2 * phase));
    const torsoLen = L_TORSO * (1 - squash * 0.22);
    const leanDynamic = p.lean + p.sticky * rad(5.5 * Math.max(0, -stepPulse));
    const shoulder = [hip[0] + torsoLen * Math.sin(leanDynamic), hip[1] - torsoLen * Math.cos(leanDynamic)];
    const headLean = leanDynamic * lerp(0.65, 0.94, p.whip);
    const headDist = HEAD_R + lerp(1.1, 2.0, p.whip);
    const head = [shoulder[0] + headDist * Math.sin(headLean), shoulder[1] - headDist * Math.cos(headLean) + p.sticky * 0.85];
    return {
      hip,
      shoulder,
      head,
      lean: leanDynamic,
      sticky: p.sticky,
      whip: p.whip,
      g: p.g,
      squash,
      nearLeg: { knee: at(near.knee), foot: at(near.foot), toe: at(near.toe), swing: near.swing },
      farLeg: { knee: at(far.knee), foot: at(far.foot), toe: at(far.toe), swing: far.swing },
      nearArm: arm(p, shoulder, phase + Math.PI),
      farArm: arm(p, shoulder, phase),
    };
  }

  const polyline = points => 'M' + points.map(pt => `${fixed(pt[0])} ${fixed(pt[1])}`).join('L');

  // Guaranteed convex, non-self-intersecting tapered quad connecting circle A(rA) -> B(rB).
  // Paired with round-capped core strokes + joint circles, limbs stay 100% solid at every angle.
  function taperedBridge(a, rA, b, rB) {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const d = Math.hypot(dx, dy) || 0.001;
    const nx = -dy / d;
    const ny = dx / d;
    return [
      `M${fixed(a[0] + nx * rA)} ${fixed(a[1] + ny * rA)}`,
      `L${fixed(b[0] + nx * rB)} ${fixed(b[1] + ny * rB)}`,
      `L${fixed(b[0] - nx * rB)} ${fixed(b[1] - ny * rB)}`,
      `L${fixed(a[0] - nx * rA)} ${fixed(a[1] - ny * rA)}Z`,
    ].join('');
  }

  function circleD(c, r) {
    const x = c[0];
    const y = c[1];
    return `M${fixed(x - r)} ${fixed(y)}A${fixed(r)} ${fixed(r)} 0 1 0 ${fixed(x + r)} ${fixed(y)}A${fixed(r)} ${fixed(r)} 0 1 0 ${fixed(x - r)} ${fixed(y)}Z`;
  }

  // Sculpted organic limb (thigh + shin + rounded foot blob, or upper arm + forearm + rounded mitt).
  function sculptedLegPath(hip, legData, fat) {
    const rHip = 3.2 * fat;
    const rKnee = 2.45 * fat;
    const rAnkle = 2.25 * fat;
    const rToe = 2.0 * fat;
    return (
      taperedBridge(hip, rHip, legData.knee, rKnee) +
      taperedBridge(legData.knee, rKnee, legData.foot, rAnkle) +
      taperedBridge(legData.foot, rAnkle, legData.toe, rToe) +
      circleD(legData.knee, rKnee) +
      circleD(legData.foot, rAnkle) +
      circleD(legData.toe, rToe)
    );
  }

  function sculptedArmPath(shoulder, armData, fat) {
    const rSh = 2.5 * fat;
    const rEl = 2.0 * fat;
    const rHand = 2.1 * fat;
    return (
      taperedBridge(shoulder, rSh, armData.elbow, rEl) +
      taperedBridge(armData.elbow, rEl, armData.hand, rHand) +
      circleD(armData.elbow, rEl) +
      circleD(armData.hand, rHand)
    );
  }

  // Plump pear/teardrop slime torso with convex belly and organic joint caps.
  function torsoPath(hip, shoulder, squash, whip) {
    const dx = shoulder[0] - hip[0];
    const dy = shoulder[1] - hip[1];
    const d = Math.hypot(dx, dy) || 0.001;
    const nx = -dy / d;
    const ny = dx / d;
    const sign = nx >= 0 ? 1 : -1;
    const cx = nx * sign;
    const cy = ny * sign;
    const rHip = 5.0 * (1 + squash * 0.24) * (1 - whip * 0.12);
    const rSh = 4.2 * (1 - squash * 0.05) * (1 + whip * 0.08);
    const hFront = [hip[0] + cx * rHip, hip[1] + cy * rHip];
    const hBack = [hip[0] - cx * rHip, hip[1] - cy * rHip];
    const sFront = [shoulder[0] + cx * rSh, shoulder[1] + cy * rSh];
    const sBack = [shoulder[0] - cx * rSh, shoulder[1] - cy * rSh];
    const belly = [
      (hFront[0] + sFront[0]) * 0.5 + cx * (1.2 + squash * 1.9),
      (hFront[1] + sFront[1]) * 0.5 + cy * (1.2 + squash * 1.9),
    ];
    const back = [
      (hBack[0] + sBack[0]) * 0.5 - cx * (0.4 + whip * 1.4),
      (hBack[1] + sBack[1]) * 0.5 - cy * (0.4 + whip * 1.4),
    ];
    return (
      `M${fixed(hFront[0])} ${fixed(hFront[1])}` +
      `Q${fixed(belly[0])} ${fixed(belly[1])} ${fixed(sFront[0])} ${fixed(sFront[1])}` +
      `L${fixed(sBack[0])} ${fixed(sBack[1])}` +
      `Q${fixed(back[0])} ${fixed(back[1])} ${fixed(hBack[0])} ${fixed(hBack[1])}Z` +
      circleD(hip, rHip) +
      circleD(shoulder, rSh)
    );
  }

  // Deformable slime head: heavy/drooping when stuck in goo, swept aerodynamic teardrop crest when sprinting.
  function headPath(head, lean, squash, sticky, whip, clock) {
    const cx = head[0];
    const cy = head[1];
    const rx = HEAD_R * (1 + squash * 0.2 + whip * 0.2);
    const ry = HEAD_R * (1 - squash * 0.14 - whip * 0.12);
    const sag = sticky * 1.05;
    const tailPull = whip * (5.8 + 1.2 * Math.sin(clock * 16));
    const tailLift = -whip * (1.8 + 0.8 * Math.cos(clock * 14));
    const cos = Math.cos(lean * 0.44);
    const sin = Math.sin(lean * 0.44);
    const rot = (x, y) => [cx + x * cos - y * sin, cy + x * sin + y * cos];
    const top = rot(0.45 * whip, -ry);
    const front = rot(rx, 0.35 * sag);
    const chin = rot(0.3, ry + sag * 0.65);
    const back = rot(-rx - tailPull, tailLift + 0.3 * sag);
    const k = 0.56;
    const c1 = rot(rx * k + 0.65 * whip, -ry);
    const c2 = rot(rx, -ry * k);
    const c3 = rot(rx, ry * k + sag * 0.4);
    const c4 = rot(rx * k, ry + sag * 0.65);
    const c5 = rot(-rx * k - tailPull * 0.35, ry + sag * 0.5);
    const c6 = rot(-rx - tailPull * 0.85, ry * 0.45 + tailLift * 0.5);
    const c7 = rot(-rx - tailPull * 0.85, -ry * 0.55 + tailLift * 0.7);
    const c8 = rot(-rx * k - tailPull * 0.2, -ry);
    return [
      `M${fixed(top[0])} ${fixed(top[1])}`,
      `C${fixed(c1[0])} ${fixed(c1[1])} ${fixed(c2[0])} ${fixed(c2[1])} ${fixed(front[0])} ${fixed(front[1])}`,
      `C${fixed(c3[0])} ${fixed(c3[1])} ${fixed(c4[0])} ${fixed(c4[1])} ${fixed(chin[0])} ${fixed(chin[1])}`,
      `C${fixed(c5[0])} ${fixed(c5[1])} ${fixed(c6[0])} ${fixed(c6[1])} ${fixed(back[0])} ${fixed(back[1])}`,
      `C${fixed(c7[0])} ${fixed(c7[1])} ${fixed(c8[0])} ${fixed(c8[1])} ${fixed(top[0])} ${fixed(top[1])}Z`,
    ].join('');
  }

  // Sculpted hourglass-necked viscous goo bridge gluing a foot/toe to the ground puddle.
  // Shows crisp negative space around the pinched waist while keeping melted fillets at foot and ground.
  function stickyStrandPath(foot, anchorX, sticky, { groundY = 1.25, thin = false } = {}) {
    if (sticky <= 0.02) return '';
    const liftH = Math.max(0, groundY - foot[1]);
    const maxStretch = lerp(5.5, 17.5, sticky);
    if (liftH > maxStretch) return '';
    if (liftH <= 1.35) {
      if (thin) return '';
      const fw = 2.4 * sticky;
      const bw = 4.2 * sticky;
      return `M${fixed(foot[0] - fw)} ${fixed(foot[1] - 0.3)}L${fixed(anchorX - bw)} ${fixed(groundY)}L${fixed(anchorX + bw)} ${fixed(groundY)}L${fixed(foot[0] + fw)} ${fixed(foot[1] - 0.3)}Z`;
    }
    const tension = clamp((liftH - 1.35) / Math.max(1, maxStretch - 1.35), 0, 1);
    const scale = thin ? 0.58 : 1;
    const topW = lerp(2.45, 1.35, tension) * scale * (0.65 + 0.35 * sticky);
    const botW = lerp(4.1, 2.2, tension) * scale * (0.65 + 0.35 * sticky);
    const waistW = Math.max(thin ? 0.58 : 0.78, lerp(1.55, 0.74, Math.pow(tension, 0.72)) * scale * sticky);
    const midY = lerp(foot[1], groundY, 0.56);
    const midX = lerp(foot[0], anchorX, 0.54);
    const fx = foot[0];
    const fy = foot[1] - 0.25;
    return [
      `M${fixed(fx - topW)} ${fixed(fy)}`,
      `Q${fixed(midX - waistW)} ${fixed(midY)} ${fixed(anchorX - botW)} ${fixed(groundY)}`,
      `L${fixed(anchorX + botW)} ${fixed(groundY)}`,
      `Q${fixed(midX + waistW)} ${fixed(midY)} ${fixed(fx + topW)} ${fixed(fy)}Z`,
    ].join('');
  }

  // Dynamic whipped slime ribbon streaming backward behind the sprinting character.
  function whippedRibbonPath(anchor, len, baseR, amp, freq, phaseOff, droop, clock) {
    if (len < 1.5 || baseR < 0.45) return '';
    const steps = 6;
    const upper = [];
    const lower = [];
    for (let i = 0; i <= steps; i += 1) {
      const t = i / steps;
      const x = anchor[0] - len * t;
      const wave = Math.sin(clock * freq - t * 4.8 + phaseOff) * amp * t * (0.3 + 0.7 * t);
      const y = anchor[1] + wave + droop * t * t;
      const bulge = 1 + 0.2 * Math.sin(clock * (freq * 0.85) - t * 7.0 + phaseOff);
      const r = Math.max(0.75, baseR * Math.pow(1 - t, 0.92) * bulge);
      upper.push([x, y - r]);
      lower.push([x, y + r]);
    }
    let d = `M${fixed(upper[0][0])} ${fixed(upper[0][1])}`;
    for (let i = 1; i < upper.length; i += 1) {
      const prev = upper[i - 1];
      const cur = upper[i];
      d += `Q${fixed((prev[0] + cur[0]) * 0.5)} ${fixed((prev[1] + cur[1]) * 0.5)} ${fixed(cur[0])} ${fixed(cur[1])}`;
    }
    const tip = lower[lower.length - 1];
    d += `L${fixed(tip[0])} ${fixed(tip[1])}`;
    for (let i = lower.length - 2; i >= 0; i -= 1) {
      const prev = lower[i + 1];
      const cur = lower[i];
      d += `Q${fixed((prev[0] + cur[0]) * 0.5)} ${fixed((prev[1] + cur[1]) * 0.5)} ${fixed(cur[0])} ${fixed(cur[1])}`;
    }
    return `${d}Z`;
  }

  // Aerodynamic teardrop slime globule elongated along its backward flight vector.
  function dropletPath(cx, cy, rx, ry) {
    if (rx < 0.4 || ry < 0.3) return '';
    return [
      `M${fixed(cx + rx)} ${fixed(cy)}`,
      `C${fixed(cx + rx * 0.55)} ${fixed(cy - ry * 1.08)} ${fixed(cx - rx * 0.45)} ${fixed(cy - ry * 0.86)} ${fixed(cx - rx)} ${fixed(cy)}`,
      `C${fixed(cx - rx * 0.45)} ${fixed(cy + ry * 0.86)} ${fixed(cx + rx * 0.55)} ${fixed(cy + ry * 1.08)} ${fixed(cx + rx)} ${fixed(cy)}Z`,
    ].join('');
  }

  function createFigure(svg) {
    const instanceId = ++instanceCounter;
    const filterId = `desk-runner-goo-${instanceId}`;
    const farFilterId = `desk-runner-far-goo-${instanceId}`;
    const bodyGradId = `desk-runner-body-grad-${instanceId}`;
    const headGradId = `desk-runner-head-grad-${instanceId}`;
    const farGradId = `desk-runner-far-grad-${instanceId}`;
    const trailGradId = `desk-runner-trail-grad-${instanceId}`;
    const dropGradId = `desk-runner-drop-grad-${instanceId}`;
    const el = (parent, tag, attrs = {}) => {
      const node = document.createElementNS(NS, tag);
      Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, value));
      parent.appendChild(node);
      return node;
    };
    const addGrad = (defs, tag, attrs, stops) => {
      const grad = el(defs, tag, attrs);
      stops.forEach(([offset, color]) => el(grad, 'stop', { offset, 'stop-color': color }));
      return grad;
    };

    // Volumetric 3D obsidian metaball filters & semantic theme-reactive material gradients.
    const defs = el(svg, 'defs');
    const filter = el(defs, 'filter', {
      id: filterId,
      filterUnits: 'userSpaceOnUse',
      x: '-156',
      y: '-76',
      width: '204',
      height: '96',
      'color-interpolation-filters': 'sRGB',
    });
    el(filter, 'feGaussianBlur', { in: 'SourceGraphic', stdDeviation: '0.76', result: 'blur' });
    el(filter, 'feColorMatrix', {
      in: 'blur',
      mode: 'matrix',
      values: '1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -5.8',
      result: 'goo',
    });
    el(filter, 'feGaussianBlur', { in: 'goo', stdDeviation: '1.45', result: 'bump' });
    const specLight = el(filter, 'feSpecularLighting', {
      in: 'bump',
      surfaceScale: '2.8',
      specularConstant: '0.82',
      specularExponent: '20',
      'lighting-color': '#edf3ff',
      result: 'spec',
    });
    el(specLight, 'feDistantLight', { azimuth: '228', elevation: '52' });
    el(filter, 'feComposite', { in: 'spec', in2: 'goo', operator: 'in', result: 'specMask' });
    el(filter, 'feComposite', {
      in: 'specMask',
      in2: 'goo',
      operator: 'arithmetic',
      k1: '0',
      k2: '0.54',
      k3: '1',
      k4: '0',
    });

    const farFilter = el(defs, 'filter', {
      id: farFilterId,
      filterUnits: 'userSpaceOnUse',
      x: '-156',
      y: '-76',
      width: '204',
      height: '96',
      'color-interpolation-filters': 'sRGB',
    });
    el(farFilter, 'feGaussianBlur', { in: 'SourceGraphic', stdDeviation: '0.76', result: 'blur' });
    el(farFilter, 'feColorMatrix', {
      in: 'blur',
      mode: 'matrix',
      values: '1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -5.8',
      result: 'goo',
    });

    addGrad(defs, 'linearGradient', { id: bodyGradId, x1: '18%', y1: '6%', x2: '84%', y2: '96%' }, [
      ['0%', 'var(--desk-runner-slime-lit)'],
      ['32%', 'var(--desk-runner-slime-mid)'],
      ['74%', 'var(--desk-runner-slime-core)'],
      ['100%', 'var(--desk-runner-slime-bounce)'],
    ]);
    addGrad(defs, 'radialGradient', { id: headGradId, cx: '42%', cy: '34%', fx: '34%', fy: '24%', r: '72%' }, [
      ['0%', 'var(--desk-runner-slime-lit)'],
      ['38%', 'var(--desk-runner-slime-mid)'],
      ['80%', 'var(--desk-runner-slime-core)'],
      ['100%', 'var(--desk-runner-slime-bounce)'],
    ]);
    addGrad(defs, 'linearGradient', { id: farGradId, x1: '20%', y1: '0%', x2: '80%', y2: '100%' }, [
      ['0%', 'var(--desk-runner-slime-deep-lit)'],
      ['45%', 'var(--desk-runner-slime-deep)'],
      ['100%', 'var(--desk-runner-slime-core)'],
    ]);
    addGrad(defs, 'linearGradient', { id: trailGradId, x1: '88%', y1: '12%', x2: '8%', y2: '92%' }, [
      ['0%', 'var(--desk-runner-slime-lit)'],
      ['42%', 'var(--desk-runner-slime-trail)'],
      ['100%', 'var(--desk-runner-slime-core)'],
    ]);
    addGrad(defs, 'radialGradient', { id: dropGradId, cx: '56%', cy: '36%', fx: '64%', fy: '26%', r: '68%' }, [
      ['0%', 'var(--desk-runner-slime-lit)'],
      ['46%', 'var(--desk-runner-slime-mid)'],
      ['100%', 'var(--desk-runner-slime-core)'],
    ]);

    // Ground contact shadow + subtle outer rim halo for crisp separation on dark/light tracks.
    const shadowEl = el(svg, 'ellipse', { class: 'desk-runner-slider__shadow', cy: '2.1' });
    const haloGroup = el(svg, 'g', { class: 'desk-runner-slider__halo-group' });
    const haloStrokes = el(haloGroup, 'path', {
      class: 'desk-runner-slider__halo',
      fill: 'none',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    });
    const haloHead = el(haloGroup, 'path', { class: 'desk-runner-slider__halo-head' });

    // Layer 1: Recessed far limbs + far sticky goo bridge for front-to-back 3D depth separation.
    const farGroup = el(svg, 'g', { class: 'desk-runner-slider__far-group', filter: `url(#${farFilterId})` });
    const farLimbs = el(farGroup, 'path', { class: 'desk-runner-slider__slime-far', fill: `url(#${farGradId})` });
    const farStrand = el(farGroup, 'path', { class: 'desk-runner-slider__slime-far', fill: `url(#${farGradId})` });

    // Layer 2: Primary 3D shaded obsidian metaball slime body (puddle + strands + drip + body + whipped ribbons).
    const bodyFill = `url(#${bodyGradId})`;
    const trailFill = `url(#${trailGradId})`;
    const gooGroup = el(svg, 'g', { class: 'desk-runner-slider__goo-group', filter: `url(#${filterId})` });
    const puddle = el(gooGroup, 'ellipse', { class: 'desk-runner-slider__puddle', cy: '1.45', fill: bodyFill });
    const puddleLumpL = el(gooGroup, 'ellipse', { class: 'desk-runner-slider__puddle', cy: '1.15', fill: bodyFill });
    const puddleLumpR = el(gooGroup, 'ellipse', { class: 'desk-runner-slider__puddle', cy: '1.2', fill: bodyFill });
    const nearStrand = el(gooGroup, 'path', { class: 'desk-runner-slider__slime', fill: bodyFill });
    const toeStrand = el(gooGroup, 'path', { class: 'desk-runner-slider__slime', fill: bodyFill });
    const hangDrip = el(gooGroup, 'path', { class: 'desk-runner-slider__slime', fill: bodyFill });
    const ribbonHead = el(gooGroup, 'path', { class: 'desk-runner-slider__slime-trail', fill: trailFill });
    const ribbonBack = el(gooGroup, 'path', { class: 'desk-runner-slider__slime-trail', fill: trailFill });
    const ribbonHeel = el(gooGroup, 'path', { class: 'desk-runner-slider__slime-trail', fill: trailFill });
    const torsoEl = el(gooGroup, 'path', { class: 'desk-runner-slider__slime', fill: bodyFill });
    const nearLimbs = el(gooGroup, 'path', { class: 'desk-runner-slider__slime', fill: bodyFill });
    const headEl = el(gooGroup, 'path', { class: 'desk-runner-slider__slime', fill: `url(#${headGradId})` });

    // Layer 2b: Crisp detached flying 3D obsidian droplets trailing far behind the sprinter.
    const sprayGroup = el(svg, 'g', { class: 'desk-runner-slider__spray-group' });
    const droplets = Array.from({ length: 7 }, () => el(sprayGroup, 'path', {
      class: 'desk-runner-slider__slime-drop',
      fill: `url(#${dropGradId})`,
    }));

    // Layer 3: Crisp unfiltered surface specular gloss, studio rim contour, droplet glints, and eye.
    const detailGroup = el(svg, 'g', { class: 'desk-runner-slider__detail-group' });
    const rimArc = el(detailGroup, 'path', { class: 'desk-runner-slider__rim', fill: 'none', 'stroke-linecap': 'round' });
    const headGloss = el(detailGroup, 'path', { class: 'desk-runner-slider__gloss', fill: 'none', 'stroke-linecap': 'round' });
    const headGlossDot = el(detailGroup, 'circle', { class: 'desk-runner-slider__drop-glint', r: '0.68' });
    const bodyGloss = el(detailGroup, 'path', { class: 'desk-runner-slider__gloss', fill: 'none', 'stroke-linecap': 'round' });
    const puddleGloss = el(detailGroup, 'path', { class: 'desk-runner-slider__gloss', fill: 'none', 'stroke-linecap': 'round' });
    const strandGloss = el(detailGroup, 'path', { class: 'desk-runner-slider__gloss', fill: 'none', 'stroke-linecap': 'round' });
    const dripGlint = el(detailGroup, 'circle', { class: 'desk-runner-slider__drop-glint', r: '0.5' });
    const eyeEl = el(detailGroup, 'path', { class: 'desk-runner-slider__eye', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    const eyeGlint = el(detailGroup, 'circle', { class: 'desk-runner-slider__eye-glint', r: '0.55' });
    const dropGlints = Array.from({ length: 5 }, () => el(detailGroup, 'circle', { class: 'desk-runner-slider__drop-glint', r: '0.72' }));

    return function draw(s, phase, clock) {
      const q = pose(s, phase);
      const { sticky, whip, squash } = q;

      // Sculpted 100%-solid organic limbs (never self-intersecting, smooth metaball joints).
      const limbFat = 1 + sticky * 0.14 - whip * 0.06;
      const farLegD = sculptedLegPath(q.hip, q.farLeg, limbFat * 0.94);
      const farArmD = sculptedArmPath(q.shoulder, q.farArm, limbFat * 0.92);
      farLimbs.setAttribute('d', farLegD + farArmD);

      const nearLegD = sculptedLegPath(q.hip, q.nearLeg, limbFat);
      const nearArmD = sculptedArmPath(q.shoulder, q.nearArm, limbFat);
      const torsoD = torsoPath(q.hip, q.shoulder, squash, whip);
      const headD = headPath(q.head, q.lean, squash, sticky, whip, clock);

      torsoEl.setAttribute('d', torsoD);
      nearLimbs.setAttribute('d', nearLegD + nearArmD);
      headEl.setAttribute('d', headD);

      // Clean skeleton halo strokes behind solid body/limbs (tight margin, never leaks inside).
      const skelD =
        polyline([q.hip, q.farLeg.knee, q.farLeg.foot, q.farLeg.toe]) +
        polyline([q.hip, q.nearLeg.knee, q.nearLeg.foot, q.nearLeg.toe]) +
        polyline([q.hip, q.shoulder]) +
        polyline([q.shoulder, q.nearArm.elbow, q.nearArm.hand]);
      haloStrokes.setAttribute('d', skelD);
      haloHead.setAttribute('d', headD);

      // Ground contact shadow beneath feet/puddle: widens when stuck in slime, narrows slightly when airborne.
      const groundLow = Math.max(q.nearLeg.foot[1], q.nearLeg.toe[1], q.farLeg.foot[1], q.farLeg.toe[1]);
      const flightClearance = Math.max(0, -groundLow);
      const shadowCx = q.hip[0] * 0.35 + (q.nearLeg.foot[0] + q.farLeg.foot[0]) * 0.32 - sticky * 0.8;
      const shadowRx = Math.max(5.0, lerp(8.6, 18.8, sticky) * (1 - clamp(flightClearance / 15, 0, 0.42)));
      const shadowRy = lerp(1.35, 2.35, sticky);
      shadowEl.setAttribute('cx', fixed(shadowCx));
      shadowEl.setAttribute('rx', fixed(shadowRx));
      shadowEl.setAttribute('ry', fixed(shadowRy));
      shadowEl.setAttribute('opacity', fixed(clamp(0.92 - flightClearance * 0.08, 0.34, 0.96)));

      // Ground-hugging slime puddle: flat viscous pool gluing both feet at slow speed; vanishes when sprinting.
      const puddleStrength = sticky * 0.96 + (1 - whip) * 0.08;
      const puddleRx = lerp(2.0, 16.5, sticky) + Math.sin(clock * 2.2) * 0.7 * sticky;
      const puddleRy = lerp(0.45, 2.25, sticky) + Math.cos(clock * 2.2) * 0.2 * sticky;
      const puddleCx = (q.nearLeg.foot[0] + q.farLeg.foot[0]) * 0.35 + sticky * 0.4;
      puddle.setAttribute('cx', fixed(puddleCx));
      puddle.setAttribute('rx', fixed(Math.max(0.1, puddleRx)));
      puddle.setAttribute('ry', fixed(Math.max(0.1, puddleRy)));
      puddle.setAttribute('opacity', fixed(clamp(puddleStrength, 0, 1)));

      puddleLumpL.setAttribute('cx', fixed(puddleCx - puddleRx * 0.62));
      puddleLumpL.setAttribute('rx', fixed(Math.max(0.1, 4.2 * sticky)));
      puddleLumpL.setAttribute('ry', fixed(Math.max(0.1, 1.55 * sticky)));
      puddleLumpL.setAttribute('opacity', fixed(sticky));

      puddleLumpR.setAttribute('cx', fixed(puddleCx + puddleRx * 0.58));
      puddleLumpR.setAttribute('rx', fixed(Math.max(0.1, 3.8 * sticky)));
      puddleLumpR.setAttribute('ry', fixed(Math.max(0.1, 1.45 * sticky)));
      puddleLumpR.setAttribute('opacity', fixed(sticky));

      // Distinct pinched hourglass goo tethers pulling taut from lifting heel & toe back to the puddle.
      const nearAnchorX = q.nearLeg.foot[0] - 2.6 * sticky;
      const farAnchorX = q.farLeg.foot[0] - 2.4 * sticky;
      nearStrand.setAttribute('d', stickyStrandPath(q.nearLeg.foot, nearAnchorX, sticky));
      farStrand.setAttribute('d', stickyStrandPath(q.farLeg.foot, farAnchorX, sticky * 0.92));

      const liftingLeg = q.nearLeg.foot[1] < q.farLeg.foot[1] ? q.nearLeg : q.farLeg;
      const toeAnchorX = liftingLeg.toe[0] - 4.4 * sticky;
      toeStrand.setAttribute('d', stickyStrandPath(liftingLeg.toe, toeAnchorX, sticky * 0.92, { thin: true }));

      // Wet highlight along the stretched sticky foot strand when visibly pulled up.
      if (sticky > 0.25 && liftingLeg.foot[1] < -2.4) {
        const ax = liftingLeg.foot[0] - 2.5 * sticky;
        const mx = lerp(liftingLeg.foot[0], ax, 0.52) + 0.4;
        const my = lerp(liftingLeg.foot[1], 1.1, 0.52);
        strandGloss.setAttribute('d', `M${fixed(liftingLeg.foot[0] + 0.25)} ${fixed(liftingLeg.foot[1] + 0.7)} Q${fixed(mx)} ${fixed(my)} ${fixed(ax + 0.4)} ${fixed(-0.3)}`);
        strandGloss.setAttribute('stroke-width', '0.75');
        strandGloss.setAttribute('opacity', fixed(sticky * 0.58));
      } else {
        strandGloss.setAttribute('d', '');
        strandGloss.setAttribute('opacity', '0');
      }

      // Slow-crawl graceful teardrop pendant drip clinging beneath the trailing hand.
      if (sticky > 0.16) {
        const dripCycle = (clock * 0.52) % 1;
        const wrist = q.nearArm.hand;
        const dripLen = (3.8 + 4.4 * Math.sin(dripCycle * Math.PI)) * sticky;
        const dripTip = [wrist[0] - 0.5, Math.min(-0.8, wrist[1] + dripLen)];
        const tipR = (1.15 + 0.45 * dripCycle) * sticky;
        const neckMid = [lerp(wrist[0], dripTip[0], 0.52), lerp(wrist[1], dripTip[1], 0.52)];
        hangDrip.setAttribute(
          'd',
          taperedBridge(wrist, 1.05 * sticky, neckMid, 0.52 * sticky) +
          taperedBridge(neckMid, 0.52 * sticky, dripTip, tipR * 0.85) +
          circleD(dripTip, tipR)
        );
        hangDrip.setAttribute('opacity', fixed(sticky * 0.96));
        dripGlint.setAttribute('cx', fixed(dripTip[0] + tipR * 0.28));
        dripGlint.setAttribute('cy', fixed(dripTip[1] - tipR * 0.26));
        dripGlint.setAttribute('r', fixed(Math.max(0.25, tipR * 0.3)));
        dripGlint.setAttribute('opacity', fixed(sticky * 0.72));
      } else {
        hangDrip.setAttribute('d', '');
        hangDrip.setAttribute('opacity', '0');
        dripGlint.setAttribute('opacity', '0');
      }

      // High-speed whipped slime ribbons streaming off head crown, upper back, and kicking heel.
      const headAnchor = [q.head[0] - HEAD_R * 0.5, q.head[1] - 1.3];
      const backAnchor = [q.shoulder[0] - 2.0, q.shoulder[1] + 2.2];
      const rearFoot = q.nearLeg.foot[0] < q.farLeg.foot[0] ? q.nearLeg.foot : q.farLeg.foot;
      const heelAnchor = [rearFoot[0] - 1.0, Math.min(-2.2, rearFoot[1] - 0.6)];

      const headRibbonLen = lerp(0, 39, whip) + smooth(0.28, 0.68, s) * 5.0;
      const backRibbonLen = lerp(0, 33, whip);
      const heelRibbonLen = lerp(0, 29, Math.pow(whip, 0.85));

      ribbonHead.setAttribute('d', whippedRibbonPath(headAnchor, headRibbonLen, lerp(1.6, 3.8, whip), 3.6 * whip, 17, 0.2, 1.2, clock));
      ribbonBack.setAttribute('d', whippedRibbonPath(backAnchor, backRibbonLen, 3.2 * whip, 3.0 * whip, 15, 2.0, 2.0, clock));
      ribbonHeel.setAttribute('d', whippedRibbonPath(heelAnchor, heelRibbonLen, 2.8 * whip, 2.4 * whip, 19, 3.9, -0.8, clock));

      // Unfiltered crisp detached slime blobs flung backward off the whipped ribbons!
      const emitters = [
        { pt: [headAnchor[0] - headRibbonLen * 0.74, headAnchor[1] + 0.3], speed: 1.45, dist: 46, r: 2.75, sag: 3.8, off: 0.06 },
        { pt: [headAnchor[0] - headRibbonLen * 0.88, headAnchor[1] - 1.0], speed: 1.85, dist: 58, r: 2.1, sag: 3.0, off: 0.46 },
        { pt: [headAnchor[0] - headRibbonLen * 0.68, headAnchor[1] + 1.4], speed: 2.2, dist: 68, r: 1.65, sag: 2.5, off: 0.82 },
        { pt: [backAnchor[0] - backRibbonLen * 0.72, backAnchor[1] + 0.6], speed: 1.38, dist: 48, r: 2.6, sag: 4.2, off: 0.24 },
        { pt: [backAnchor[0] - backRibbonLen * 0.86, backAnchor[1] - 0.5], speed: 2.0, dist: 62, r: 1.9, sag: 2.8, off: 0.68 },
        { pt: [heelAnchor[0] - heelRibbonLen * 0.68, heelAnchor[1] - 0.5], speed: 1.65, dist: 44, r: 2.4, sag: 1.5, off: 0.36 },
        { pt: [heelAnchor[0] - heelRibbonLen * 0.84, heelAnchor[1] - 1.4], speed: 2.1, dist: 56, r: 1.75, sag: 2.1, off: 0.78 },
      ];
      const dropStrength = smooth(0.4, 0.95, s);
      droplets.forEach((node, i) => {
        if (dropStrength <= 0.02) {
          node.setAttribute('d', '');
          if (i < dropGlints.length) dropGlints[i].setAttribute('opacity', '0');
          return;
        }
        const e = emitters[i];
        const u = (clock * e.speed + e.off) % 1;
        const cx = e.pt[0] - u * e.dist * dropStrength;
        const cy = Math.min(-0.8, e.pt[1] + u * u * e.sag + Math.sin(u * Math.PI * 2 + i) * 1.15);
        const fade = Math.sin(clamp(u, 0.05, 1) * Math.PI);
        const r = e.r * dropStrength * (0.52 + 0.64 * (1 - u)) * Math.min(1, fade * 2.8);
        const rx = r * (1.58 + u * 0.72);
        const ry = r * (0.9 - u * 0.14);
        node.setAttribute('d', dropletPath(cx, cy, rx, ry));
        node.setAttribute('opacity', fixed(clamp(dropStrength * (1 - u * 0.65), 0, 0.98)));
        if (i < dropGlints.length) {
          dropGlints[i].setAttribute('cx', fixed(cx + rx * 0.24));
          dropGlints[i].setAttribute('cy', fixed(cy - ry * 0.26));
          dropGlints[i].setAttribute('r', fixed(Math.max(0.32, r * 0.28)));
          dropGlints[i].setAttribute('opacity', fixed(dropStrength * (1 - u * 0.85) * 0.86));
        }
      });

      // Unfiltered crisp wet gel highlights (dual-point crown specular + chest sheen + puddle + studio back rim).
      const hgX = q.head[0] + 1.05;
      const hgY = q.head[1] - HEAD_R * 0.54 + squash * 0.55;
      headGloss.setAttribute('d', `M${fixed(hgX - 1.45)} ${fixed(hgY + 0.1)} Q${fixed(hgX + 0.45)} ${fixed(hgY - 1.1)} ${fixed(hgX + 2.2)} ${fixed(hgY + 0.85)}`);
      headGloss.setAttribute('stroke-width', '1.22');
      headGlossDot.setAttribute('cx', fixed(hgX - 2.95));
      headGlossDot.setAttribute('cy', fixed(hgY + 1.25));
      headGlossDot.setAttribute('r', '0.56');

      const tdx = q.shoulder[0] - q.hip[0];
      const tdy = q.shoulder[1] - q.hip[1];
      const td = Math.hypot(tdx, tdy) || 0.001;
      const sx = tdx / td;
      const sy = tdy / td;
      const fx = (-tdy / td) >= 0 ? -tdy / td : tdy / td;
      const fy = (-tdy / td) >= 0 ? tdx / td : -tdx / td;

      // Soft studio rim along upper-back spine ridge (opposite side from chest catchlight — never crosses).
      const rimS = [lerp(q.shoulder[0], q.hip[0], 0.22) - fx * 3.1, lerp(q.shoulder[1], q.hip[1], 0.22) - fy * 3.1];
      const rimM = [lerp(q.shoulder[0], q.hip[0], 0.52) - fx * 3.7, lerp(q.shoulder[1], q.hip[1], 0.52) - fy * 3.7];
      const rimE = [lerp(q.shoulder[0], q.hip[0], 0.8) - fx * 3.3, lerp(q.shoulder[1], q.hip[1], 0.8) - fy * 3.3];
      rimArc.setAttribute('d', `M${fixed(rimS[0])} ${fixed(rimS[1])} Q${fixed(rimM[0])} ${fixed(rimM[1])} ${fixed(rimE[0])} ${fixed(rimE[1])}`);
      rimArc.setAttribute('stroke-width', '0.85');
      rimArc.setAttribute('opacity', fixed(0.85 - whip * 0.35));

      // Specular chest highlight rotated along the leaning spine axis.
      const chestMid = [lerp(q.hip[0], q.shoulder[0], 0.58) + fx * 1.85, lerp(q.hip[1], q.shoulder[1], 0.58) + fy * 1.85];
      const bgTop = [chestMid[0] + sx * 2.15, chestMid[1] + sy * 2.15];
      const bgCtrl = [chestMid[0] + fx * 0.72, chestMid[1] + fy * 0.72];
      const bgBot = [chestMid[0] - sx * 2.25, chestMid[1] - sy * 2.25];
      bodyGloss.setAttribute('d', `M${fixed(bgTop[0])} ${fixed(bgTop[1])} Q${fixed(bgCtrl[0])} ${fixed(bgCtrl[1])} ${fixed(bgBot[0])} ${fixed(bgBot[1])}`);
      bodyGloss.setAttribute('stroke-width', '1.15');

      puddleGloss.setAttribute(
        'd',
        `M${fixed(puddleCx - puddleRx * 0.44)} 0.45 Q${fixed(puddleCx - puddleRx * 0.04)} -0.15 ${fixed(puddleCx + puddleRx * 0.38)} 0.5`
      );
      puddleGloss.setAttribute('stroke-width', '0.95');
      puddleGloss.setAttribute('opacity', fixed(sticky * 0.6));

      // Expressive face eye: heavy effortful squint when stuck -> bright alert jog -> fierce swept sprint eye.
      const eyeX = q.head[0] + HEAD_R * (0.44 + 0.08 * whip);
      const eyeY = q.head[1] - 0.2 + sticky * 1.1 - whip * 0.45;
      if (sticky > 0.48) {
        eyeEl.setAttribute('d', `M${fixed(eyeX - 1.4)} ${fixed(eyeY - 0.85)} L${fixed(eyeX + 0.9)} ${fixed(eyeY + 0.1)} L${fixed(eyeX - 1.1)} ${fixed(eyeY + 0.95)}`);
        eyeEl.setAttribute('fill', 'none');
        eyeEl.setAttribute('stroke-width', '1.25');
        eyeGlint.setAttribute('opacity', '0');
      } else if (whip > 0.45) {
        eyeEl.setAttribute('d', `M${fixed(eyeX - 1.6)} ${fixed(eyeY - 0.75)} Q${fixed(eyeX + 0.4)} ${fixed(eyeY - 0.95)} ${fixed(eyeX + 1.5)} ${fixed(eyeY + 0.2)} Q${fixed(eyeX - 0.2)} ${fixed(eyeY + 0.85)} ${fixed(eyeX - 1.6)} ${fixed(eyeY - 0.75)}Z`);
        eyeEl.setAttribute('fill', 'currentColor');
        eyeEl.setAttribute('stroke-width', '0.4');
        eyeGlint.setAttribute('cx', fixed(eyeX + 0.35));
        eyeGlint.setAttribute('cy', fixed(eyeY - 0.25));
        eyeGlint.setAttribute('opacity', '0.85');
      } else {
        eyeEl.setAttribute('d', `M${fixed(eyeX - 1.1)} ${fixed(eyeY)} A1.1 1.35 0 1 0 ${fixed(eyeX + 1.1)} ${fixed(eyeY)} A1.1 1.35 0 1 0 ${fixed(eyeX - 1.1)} ${fixed(eyeY)}Z`);
        eyeEl.setAttribute('fill', 'currentColor');
        eyeEl.setAttribute('stroke-width', '0');
        eyeGlint.setAttribute('cx', fixed(eyeX + 0.35));
        eyeGlint.setAttribute('cy', fixed(eyeY - 0.45));
        eyeGlint.setAttribute('opacity', '0.9');
      }
    };
  }

  function create({ stops = [], getValue = () => null, onChange = () => {}, label = '', labelClass = '', ends = ['', ''] } = {}) {
    const list = () => (typeof stops === 'function' ? stops() : stops) || [];
    const lastIndex = () => Math.max(0, list().length - 1);
    const indexOf = key => {
      const index = list().findIndex(stop => stop.key === key);
      if (index >= 0) return index;
      const recommended = list().findIndex(stop => stop.recommended);
      return recommended >= 0 ? recommended : 0;
    };
    const seconds = ms => `${(Math.round(ms / 100) / 10).toFixed(1)} 秒`;
    const valueText = stop => `${stop.label}，${seconds(stop.ms)}`;
    let active = null;

    function html() {
      const items = list();
      if (!items.length) return '';
      const index = indexOf(getValue());
      const stop = items[index];
      const labelHtml = label ? `<span class="${escapeHtml(labelClass)}">${escapeHtml(label)}</span>` : '';
      return `<div class="desk-runner-slider" data-runner-slider>
        <div class="desk-runner-slider__head">
          <span class="desk-runner-slider__name">${labelHtml}<span class="desk-runner-slider__value${index === items.length - 1 ? ' is-top' : ''}" data-runner-slider-value><span>${escapeHtml(stop.label)}</span></span></span>
          <span class="desk-runner-slider__ms" data-runner-slider-ms>${seconds(stop.ms)}</span>
        </div>
        <div class="desk-runner-slider__track" data-runner-slider-track>
          <div class="desk-runner-slider__fill" data-runner-slider-fill><canvas data-runner-slider-streaks></canvas></div>
          <div class="desk-runner-slider__marks" data-runner-slider-marks></div>
          <div class="desk-runner-slider__runner" data-runner-slider-runner><svg viewBox="${VIEWBOX.x} ${VIEWBOX.y} ${VIEWBOX.width} ${VIEWBOX.height}" aria-hidden="true" focusable="false"></svg></div>
          <input class="desk-runner-slider__input" data-runner-slider-input type="range" min="0" max="${items.length - 1}" step="0.001" value="${index}" aria-label="${escapeHtml(label)}" aria-valuetext="${escapeHtml(valueText(stop))}">
        </div>
        <div class="desk-runner-slider__below"><span>${escapeHtml(ends[0])}</span><span class="desk-runner-slider__recommended" data-runner-slider-recommended>推荐</span><span>${escapeHtml(ends[1])}</span></div>
      </div>`;
    }

    function mount(container) {
      const root = container?.querySelector?.('[data-runner-slider]') || null;
      if (root === active?.root) return;
      release();
      if (root) active = start(root);
    }

    function release() {
      active?.stop();
      active = null;
    }

    // Re-read the saved value (another window or a reset changed it).
    function sync() {
      active?.setTarget(indexOf(getValue()));
    }

    function start(root) {
      const q = selector => root.querySelector(`[data-runner-slider-${selector}]`);
      const track = q('track');
      const fill = q('fill');
      const runner = q('runner');
      const input = q('input');
      const valueEl = q('value');
      const msEl = q('ms');
      const marks = q('marks');
      const recommendedLabel = q('recommended');
      const canvas = q('streaks');
      const context = canvas.getContext?.('2d') || null;
      const draw = createFigure(runner.querySelector('svg'));
      const reduced = Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);
      let target = indexOf(getValue());
      let visual = target;
      let shown = target;
      let dragging = false;
      let visible = true;
      let frameId = 0;
      let lastTime = 0;
      let phase = 0;
      let clock = 0;
      let width = 0;
      let height = 0;
      let streakColor = '';
      let slimeColor = '';
      let themeKey = '';
      const cleanups = [];
      const listen = (target_, type, handler) => { target_.addEventListener(type, handler); cleanups.push(() => target_.removeEventListener(type, handler)); };

      const xFor = value => PAD + (value / Math.max(1, lastIndex())) * Math.max(0, width - PAD * 2);

      function layout() {
        width = track.clientWidth;
        height = track.clientHeight;
        const items = list();
        const recommended = items.findIndex(stop => stop.recommended);
        marks.innerHTML = items.map((stop, i) => `<span class="${i === recommended ? 'desk-runner-slider__mark is-recommended' : 'desk-runner-slider__mark'}" style="left:${xFor(i).toFixed(1)}px"></span>`).join('');
        if (recommended >= 0) recommendedLabel.style.left = `${xFor(recommended).toFixed(1)}px`;
        recommendedLabel.hidden = recommended < 0;
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = Math.max(1, Math.round(width * dpr));
        canvas.height = Math.max(1, Math.round(height * dpr));
        context?.setTransform(dpr, 0, 0, dpr, 0, 0);
        streakColor = '';
        slimeColor = '';
        render();
      }

      function showStop(index) {
        if (index === shown) return;
        shown = index;
        const stop = list()[index];
        if (!stop) return;
        valueEl.classList.toggle('is-top', index === lastIndex());
        input.setAttribute('aria-valuetext', valueText(stop));
        if (reduced) {
          valueEl.innerHTML = '';
          const still = document.createElement('span');
          still.textContent = stop.label;
          valueEl.appendChild(still);
          return;
        }
        valueEl.querySelectorAll('span').forEach(old => { old.classList.add('is-leaving'); setTimeout(() => old.remove(), 320); });
        const next = document.createElement('span');
        next.textContent = stop.label;
        next.className = 'is-entering';
        valueEl.appendChild(next);
        requestAnimationFrame(() => requestAnimationFrame(() => next.classList.remove('is-entering')));
      }

      function msAt(value) {
        const items = list();
        const i = Math.min(items.length - 2, Math.floor(value));
        if (i < 0) return items[0]?.ms || 0;
        return lerp(items[i].ms, items[i + 1].ms, value - i);
      }

      // Track-surface slime wake: slow creeping viscous sheen at s->0; whipped liquid droplets at s->1.
      function paintStreaks(x, s) {
        if (!context) return;
        context.clearRect(0, 0, width, height);
        const currentThemeKey = `${document.body?.dataset?.theme || ''}:${document.body?.dataset?.deskStyle || ''}`;
        const computed = (!streakColor || !slimeColor || currentThemeKey !== themeKey) ? getComputedStyle(root) : null;
        if (computed) {
          streakColor = computed.getPropertyValue('--desk-runner-mark').trim() || '#fff';
          slimeColor = computed.getPropertyValue('--desk-runner-slime').trim() || streakColor;
          themeKey = currentThemeKey;
        }

        const sticky = 1 - smooth(0.06, 0.56, s);
        if (sticky > 0.02) {
          context.fillStyle = slimeColor;
          for (let i = 0; i < 4; i += 1) {
            const drift = (clock * (4 + i * 1.4) + i * 11) % 36;
            const cx = x - 6 - drift;
            if (cx < 2) continue;
            const cy = 2.6 + (i % 2) * 3.2;
            const rx = 5 + (i % 3) * 2.5;
            context.globalAlpha = sticky * 0.28 * (1 - drift / 36);
            context.beginPath();
            context.ellipse(cx, cy, rx, 1.9, 0, 0, Math.PI * 2);
            context.fill();
          }
        }

        const strength = smooth(0.5, 1, s);
        if (strength > 0.02) {
          context.lineCap = 'round';
          for (let i = 0; i < 11; i += 1) {
            const speed = 105 + ((i * 43) % 85);
            const y = 2.6 + ((i * 2.9) % Math.max(1, height - 5.2));
            const length = 12 + ((i * 11) % 22);
            const travel = (clock * speed + i * 47) % Math.max(44, x + 12);
            const start = x - 16 - travel;
            const fade = clamp((start - 4) / 34) * clamp(1 - travel / Math.max(64, x + 8));
            const isSlime = i % 2 === 0;
            context.globalAlpha = strength * (isSlime ? 0.52 : 0.34) * fade;
            context.fillStyle = isSlime ? slimeColor : streakColor;
            context.strokeStyle = isSlime ? slimeColor : streakColor;
            context.lineWidth = isSlime ? 1.8 : 1.3;
            context.beginPath();
            context.moveTo(start, y);
            context.lineTo(start + length * 0.7, y);
            context.stroke();
            context.beginPath();
            context.ellipse(start + length * 0.78, y, 2.6 + (i % 2) * 0.9, 1.35 + (i % 2) * 0.35, 0, 0, Math.PI * 2);
            context.fill();
          }
        }
        context.globalAlpha = 1;
      }

      function render() {
        const s = visual / Math.max(1, lastIndex());
        const x = xFor(visual);
        // Gentle end-cap bias keeps the wide sticky puddle and leaning sprint head comfortably inside track bounds.
        const endBias = s < 0.5 ? (1 - s * 2) * 3.0 : -(s - 0.5) * 2 * 5.0;
        runner.style.left = `${(x + endBias + VIEWBOX.x * RUNNER_SCALE).toFixed(1)}px`;
        fill.style.width = `${Math.max(height, x + 7).toFixed(1)}px`;
        draw(s, reduced ? 0.9 : phase, reduced ? 0.35 : clock);
        paintStreaks(x, reduced ? 0 : s);
        showStop(Math.round(visual));
        msEl.textContent = seconds(msAt(visual));
      }

      function frame(now) {
        frameId = 0;
        const dt = lastTime ? Math.min(0.05, (now - lastTime) / 1000) : 0;
        lastTime = now;
        visual = dragging ? target : visual + (target - visual) * (1 - Math.exp(-dt * 14));
        if (Math.abs(target - visual) < 0.0005) visual = target;
        const s = visual / Math.max(1, lastIndex());
        phase = (phase + dt * gait(s).cadence * Math.PI * 2) % (Math.PI * 4);
        clock += dt;
        render();
        schedule();
      }
      function schedule() {
        if (frameId || !visible || !root.isConnected) return;
        // Reduced motion: only move while the thumb is still settling.
        if (reduced && visual === target && !dragging) return;
        frameId = requestAnimationFrame(frame);
      }

      function setTarget(index, { commit = false } = {}) {
        target = clamp(index, 0, lastIndex());
        input.value = String(target);
        const targetStop = list()[Math.round(target)];
        if (targetStop) input.setAttribute('aria-valuetext', valueText(targetStop));
        if (reduced && !dragging) visual = target;
        if (commit) {
          const stop = list()[Math.round(target)];
          if (stop && stop.key !== getValue()) onChange(stop.key);
        }
        render();
        schedule();
      }

      listen(input, 'input', () => { dragging = true; target = Number(input.value); schedule(); });
      const settle = () => {
        if (!dragging) return;
        dragging = false;
        setTarget(Math.round(Number(input.value)), { commit: true });
      };
      listen(input, 'change', settle);
      listen(input, 'pointerup', settle);
      listen(input, 'pointercancel', settle);
      listen(input, 'keydown', (event) => {
        const step = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[event.key];
        const jump = { Home: 0, End: lastIndex() }[event.key];
        if (step === undefined && jump === undefined) return;
        event.preventDefault();
        setTarget(jump !== undefined ? jump : Math.round(target) + step, { commit: true });
      });

      if (typeof ResizeObserver === 'function') {
        const resize = new ResizeObserver(() => layout());
        resize.observe(track);
        cleanups.push(() => resize.disconnect());
      }
      // Only animate while on screen: a collapsed row or a closed page stops the clock.
      if (typeof IntersectionObserver === 'function') {
        const seen = new IntersectionObserver((entries) => {
          visible = entries.some(entry => entry.isIntersecting);
          if (visible) { lastTime = 0; schedule(); }
        });
        seen.observe(root);
        cleanups.push(() => seen.disconnect());
      }

      layout();
      schedule();

      return {
        root,
        setTarget: index => setTarget(index),
        stop() {
          if (frameId) cancelAnimationFrame(frameId);
          frameId = 0;
          cleanups.splice(0).forEach(cleanup => cleanup());
        },
      };
    }

    return Object.freeze({ html, mount, release, sync });
  }

  window.DesktopRunnerSlider = Object.freeze({ create, gait, pose });
})();
