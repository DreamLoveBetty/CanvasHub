// Stepped speed slider whose thumb is a stick figure: it strolls at the slow end and sprints
// at the fast end, blending its gait continuously while dragged. Owns its markup, the gait
// maths, the figure drawing and its own animation clock. The host passes the stops and the
// value through callbacks, renders html(), then mounts it after rendering and releases it
// when the markup goes away. A native range input carries focus, keyboard and screen readers.
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const PAD = 10;
  // The figure is drawn in a viewBox around its hip; the svg box is that viewBox scaled.
  const VIEWBOX = { x: -60, y: -50, width: 84, height: 56 };
  const RUNNER_WIDTH = 48;
  const RUNNER_SCALE = RUNNER_WIDTH / VIEWBOX.width;
  const STROKE_WEIGHT = 1.35;
  const L_THIGH = 10.5, L_SHIN = 10.5, L_TORSO = 13, L_UPPER = 7.5, L_FORE = 7, HEAD_R = 4.4;

  const rad = degrees => (degrees * Math.PI) / 180;
  const lerp = (a, b, t) => a + (b - a) * t;
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

  // s = 0 stroll … 1 sprint. g is how much of a running pose the figure has.
  function gait(s) {
    const g = smooth(0.22, 0.78, s);
    return {
      g,
      thigh: rad(lerp(21, 50, s)),
      kneeMin: rad(lerp(4, 22, g)),
      kneeMax: rad(lerp(52, 128, g)),
      lean: rad(lerp(3, 19, Math.pow(s, 1.15))),
      arm: rad(lerp(30, 58, s)),
      elbow: rad(lerp(16, 92, g)),
      elbowSwing: rad(lerp(6, 20, g)),
      lift: lerp(0, 3.6, g),
      cadence: lerp(0.95, 2.5, s),
    };
  }

  function leg(p, phase) {
    const thigh = p.thigh * Math.sin(phase);
    const swing = Math.max(0, Math.cos(phase + 0.4));
    const knee = p.kneeMin + (p.kneeMax - p.kneeMin) * Math.pow(swing, 1.35);
    const kneeAt = [L_THIGH * Math.sin(thigh), L_THIGH * Math.cos(thigh)];
    const shin = thigh - knee;
    const foot = [kneeAt[0] + L_SHIN * Math.sin(shin), kneeAt[1] + L_SHIN * Math.cos(shin)];
    const toe = [foot[0] + 3.2 * Math.cos(shin), foot[1] - 3.2 * Math.sin(shin)];
    return { knee: kneeAt, foot, toe };
  }

  function arm(p, shoulder, phase) {
    const upper = p.lean * 0.35 + p.arm * Math.sin(phase);
    const bend = p.elbow + p.elbowSwing * Math.max(0, Math.sin(phase));
    const elbow = [shoulder[0] + L_UPPER * Math.sin(upper), shoulder[1] + L_UPPER * Math.cos(upper)];
    const hand = [elbow[0] + L_FORE * Math.sin(upper + bend), elbow[1] + L_FORE * Math.cos(upper + bend)];
    return { elbow, hand };
  }

  // Joint positions with y = 0 on the ground: the lowest foot stays down, running adds flight.
  function pose(s, phase) {
    const p = gait(s);
    const near = leg(p, phase);
    const far = leg(p, phase + Math.PI);
    const lowest = Math.max(near.foot[1], near.toe[1], far.foot[1], far.toe[1]);
    const hip = [0, -lowest - p.lift * (0.5 - 0.5 * Math.cos(2 * phase))];
    const at = point => [hip[0] + point[0], hip[1] + point[1]];
    const shoulder = [hip[0] + L_TORSO * Math.sin(p.lean), hip[1] - L_TORSO * Math.cos(p.lean)];
    const headLean = p.lean * 0.75;
    return {
      hip,
      shoulder,
      head: [shoulder[0] + (HEAD_R + 2) * Math.sin(headLean), shoulder[1] - (HEAD_R + 2) * Math.cos(headLean)],
      nearLeg: { knee: at(near.knee), foot: at(near.foot), toe: at(near.toe) },
      farLeg: { knee: at(far.knee), foot: at(far.foot), toe: at(far.toe) },
      nearArm: arm(p, shoulder, phase + Math.PI),
      farArm: arm(p, shoulder, phase),
    };
  }

  const fixed = n => n.toFixed(2);
  const polyline = points => 'M' + points.map(point => `${fixed(point[0])} ${fixed(point[1])}`).join('L');

  function createFigure(svg) {
    const add = (tag, attrs) => {
      const node = document.createElementNS(NS, tag);
      Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, value));
      svg.appendChild(node);
      return node;
    };
    const line = { fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
    const w = STROKE_WEIGHT;
    const streaks = [0, 1, 2].map(() => add('line', { class: 'desk-runner-slider__streak', 'stroke-width': 1.6 * w, 'stroke-linecap': 'round' }));
    const halo = add('path', { ...line, class: 'desk-runner-slider__halo', 'stroke-width': 6.2 * w });
    const haloHead = add('circle', { class: 'desk-runner-slider__halo-head', r: HEAD_R + 1.8 });
    const far = add('path', { ...line, class: 'desk-runner-slider__limb is-far', 'stroke-width': 2.4 * w });
    const body = add('path', { ...line, class: 'desk-runner-slider__limb', 'stroke-width': 2.6 * w });
    const head = add('circle', { class: 'desk-runner-slider__head', r: HEAD_R });
    const near = add('path', { ...line, class: 'desk-runner-slider__limb', 'stroke-width': 2.6 * w });
    return function draw(s, phase, clock) {
      const q = pose(s, phase);
      const farD = polyline([q.hip, q.farLeg.knee, q.farLeg.foot, q.farLeg.toe]) + polyline([q.shoulder, q.farArm.elbow, q.farArm.hand]);
      const bodyD = polyline([q.hip, q.shoulder]);
      const nearD = polyline([q.hip, q.nearLeg.knee, q.nearLeg.foot, q.nearLeg.toe]) + polyline([q.shoulder, q.nearArm.elbow, q.nearArm.hand]);
      far.setAttribute('d', farD);
      body.setAttribute('d', bodyD);
      near.setAttribute('d', nearD);
      halo.setAttribute('d', farD + bodyD + nearD);
      [head, haloHead].forEach(node => { node.setAttribute('cx', fixed(q.head[0])); node.setAttribute('cy', fixed(q.head[1])); });
      // Speed lines trail the figure on the fastest stretch only.
      const strength = smooth(0.72, 1, s);
      streaks.forEach((streak, i) => {
        const y = -30 + i * 8 - (i === 1 ? 1 : 0);
        const length = (10 + i * 3) * strength;
        const drift = (clock * (1.6 + i * 0.35)) % 1;
        const end = -11 - drift * 16;
        streak.setAttribute('x1', fixed(end - length));
        streak.setAttribute('x2', fixed(end));
        streak.setAttribute('y1', fixed(y));
        streak.setAttribute('y2', fixed(y));
        streak.setAttribute('opacity', fixed(strength * (1 - drift) * 0.85));
      });
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

      function paintStreaks(x, s) {
        if (!context) return;
        context.clearRect(0, 0, width, height);
        const strength = smooth(0.72, 1, s);
        if (strength <= 0) return;
        if (!streakColor) streakColor = getComputedStyle(root).getPropertyValue('--desk-runner-mark').trim() || '#fff';
        context.strokeStyle = streakColor;
        context.lineCap = 'round';
        for (let i = 0; i < 9; i += 1) {
          const speed = 90 + ((i * 37) % 70);
          const y = 3 + ((i * 3) % Math.max(1, height - 6));
          const length = 18 + ((i * 13) % 26);
          const start = x - 30 - ((clock * speed + i * 53) % (x + 20));
          context.globalAlpha = strength * (0.18 + ((i * 7) % 5) * 0.06) * clamp((start - 6) / 40);
          context.lineWidth = 1.4 + (i % 3) * 0.5;
          context.beginPath();
          context.moveTo(start, y);
          context.lineTo(start + length, y);
          context.stroke();
        }
        context.globalAlpha = 1;
      }

      function render() {
        const s = visual / Math.max(1, lastIndex());
        const x = xFor(visual);
        runner.style.left = `${(x + VIEWBOX.x * RUNNER_SCALE).toFixed(1)}px`;
        fill.style.width = `${Math.max(height, x + 7).toFixed(1)}px`;
        draw(s, reduced ? 0.9 : phase, clock);
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
