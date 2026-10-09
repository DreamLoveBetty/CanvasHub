// Shared canvas progress presentation. Callers own task receipts and visibility.
// No task API, graph state, mutation observer, simulated percent or per-node RAF.
(function () {
  'use strict';
  const M = window.DesktopProgressModel;

  function create({ getPreferences, getViewport, isInteracting = () => false,
    Renderer = window.DesktopProgressRenderer.ProgressRenderer } = {}) {
    const entries = new Map();
    let preferences = M.normalizePreferences(getPreferences?.());
    let observer = null, resizeObserver = null, frame = 0, clock = 0;
    let cursor = 0, destroyed = false;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const reduced = () => reduce?.matches === true;
    const visible = entry => !document.hidden && entry.inView && entry.root.isConnected;
    const animated = entry => preferences.style !== 'classic' && !entry.failed && visible(entry)
      && !reduced() && (entry.display.running || entry.motion.active || entry.flow.active);
    const wantsFrame = entry => preferences.style !== 'classic' && visible(entry)
      && (entry.dirty || animated(entry));

    function element(tag, className, parent) {
      const el = document.createElement(tag);
      el.className = className;
      parent?.appendChild(el);
      return el;
    }

    function initObservers() {
      if (!observer && window.IntersectionObserver) {
        observer = new window.IntersectionObserver(changes => {
          // Process every entry in time order: a pan can enter AND leave in one batch.
          for (const change of changes) {
            const entry = entries.get(change.target);
            if (!entry) continue;
            entry.inView = change.isIntersecting;
            entry.lastPaint = 0;
            if (entry.inView) { entry.dirty = true; paintText(entry); }
          }
          schedule();
        }, { root: getViewport?.() || null });
      }
      if (!resizeObserver && window.ResizeObserver) {
        resizeObserver = new window.ResizeObserver(changes => {
          for (const change of changes) {
            const entry = entries.get(change.target);
            if (!entry) continue;
            // Untransformed content box: canvas zoom must not shrink the waves.
            entry.width = change.contentRect.width;
            entry.dirty = entry.measure = true;
          }
          schedule();
        });
      }
    }

    function removeMaterial(entry) {
      entry.renderer?.destroy();
      entry.renderer = null;
      entry.track?.remove();
      entry.track = null;
      entry.root.classList.remove('desk-progress-material');
      entry.root.style.removeProperty('--desk-progress-height');
      entry.root.removeAttribute('data-progress-style');
      entry.root.removeAttribute('data-progress-size');
      entry.failed = false;
    }

    function restoreClassicFill(entry) {
      if (entry.classicBar) entry.classicBar.style.background = entry.classicBackground;
      entry.classicBar = null;
    }

    function syncStyle(entry) {
      restoreClassicFill(entry);
      const { style, height, colors } = preferences;
      if (style === 'classic') {
        removeMaterial(entry);
        if (colors.classic) {
          const bar = entry.root.querySelector('[data-progress-bar], [data-cyimg-bar]');
          if (bar) {
            entry.classicBar = bar;
            entry.classicBackground = bar.style.background;
            bar.style.background = M.classicFillGradient(colors.classic);
          }
        }
        return;
      }
      if (!entry.track) {
        entry.track = element('div', 'desk-progress-material__track', entry.root);
        // Music already exposes an accessible progressbar on its legacy root.
        // Keep that domain-owned contract instead of nesting two progressbars.
        const ownsSemantics = entry.root.getAttribute('role') !== 'progressbar';
        entry.track.setAttribute('role', ownsSemantics ? 'progressbar' : 'presentation');
        entry.track.setAttribute('aria-live', 'off'); // Do not announce the clock every second.
        if (ownsSemantics) {
          entry.track.setAttribute('aria-valuemin', '0');
          entry.track.setAttribute('aria-valuemax', '100');
        }
        entry.canvas = element('canvas', 'desk-progress-material__canvas', entry.track);
        entry.canvas.width = entry.canvas.height = 1;
        entry.canvas.setAttribute('aria-hidden', 'true');
        const copy = element('div', 'desk-progress-material__copy', entry.track);
        entry.title = element('strong', 'desk-progress-material__title', copy);
        const meta = element('div', 'desk-progress-material__meta', copy);
        entry.detail = element('span', 'desk-progress-material__detail', meta);
        entry.time = element('span', 'desk-progress-material__time', meta);
        entry.value = element('strong', 'desk-progress-material__value', entry.track);
      }
      entry.root.classList.add('desk-progress-material');
      entry.root.dataset.progressStyle = style;
      entry.root.dataset.progressSize = String(height);
      entry.root.style.setProperty('--desk-progress-height', `${height}px`);
      entry.track.style.backgroundColor = M.PROGRESS_STYLES[style].track;
      entry.dirty = entry.measure = true;
      paintText(entry);
    }

    function paintText(entry) {
      if (!entry.track) return;
      const d = entry.display, elapsed = M.elapsedLabel(d, Date.now());
      const set = (el, text) => { if (el.textContent !== text) el.textContent = text; };
      set(entry.title, d.title);
      set(entry.detail, d.detail);
      entry.detail.hidden = !d.detail;
      set(entry.time, elapsed === '—' ? '用时 —' : `已用时 ${elapsed}`);
      set(entry.value, d.valueLabel || (d.percent === null ? '处理中' : `${Math.round(d.percent)}%`));
      entry.track.title = [d.title, d.detail, `已用时 ${elapsed}`].filter(Boolean).join(' · ');
      // Unknown and stage-local progress retain their meaning; never invent ETA/percent.
      if (entry.track.getAttribute('role') === 'progressbar') {
        entry.track.setAttribute('aria-label', d.title);
        entry.track.setAttribute('aria-valuetext', [entry.value.textContent, d.detail].filter(Boolean).join(' · '));
        if (d.percent === null) entry.track.removeAttribute('aria-valuenow');
        else entry.track.setAttribute('aria-valuenow', String(d.percent));
      }
      entry.track.classList.toggle('is-indeterminate', d.percent === null);
    }

    function update(root, display, owner = root) {
      if (destroyed || !root) return;
      const next = M.normalizeDisplay(display);
      if (!next.visible) { release(root); return; }
      let entry = entries.get(root);
      if (!entry) {
        initObservers();
        entry = { root, owner, display: next, motion: new M.LiquidMotion((next.percent ?? 35) / 100),
          flow: new M.FlowMotion(), inView: !observer, dirty: true, measure: true,
          width: 0, lastPaint: 0, renderer: null, track: null };
        entries.set(root, entry);
        observer?.observe(root);
        resizeObserver?.observe(root);
        syncStyle(entry);
      } else {
        if (next.taskId !== entry.display.taskId) {
          entry.motion.reset((next.percent ?? 35) / 100);
          entry.flow.reset();
        }
        entry.display = next;
        entry.owner = owner;
        entry.motion.setTarget((next.percent ?? 35) / 100, reduced());
        entry.dirty = true;
        paintText(entry);
      }
      schedule();
    }

    function draw(entry, now) {
      const dt = entry.lastPaint ? Math.min(.12, (now - entry.lastPaint) / 1000) : 1 / 60;
      entry.lastPaint = now;
      entry.motion.step(dt, reduced());
      entry.flow.step(dt, { running: entry.display.running, velocity: entry.motion.velocity, reduced: reduced() });
      if (!entry.renderer && !entry.failed) {
        try { entry.renderer = new Renderer(entry.canvas); }
        catch (_) { entry.failed = true; entry.canvas.hidden = true; }
      }
      const { style, height, colors } = preferences;
      if (entry.renderer) {
        try {
          if (entry.measure) {
            // Read layout only when first shown or resized, never on each animation frame.
            const width = entry.width || entry.root.clientWidth;
            entry.renderer.resize(Math.max(1, width), height);
            entry.measure = false;
          }
          // Non-fluid materials also use the continuous drive instead of restart impulses.
          const material = { value: entry.motion.value, velocity: entry.flow.velocity,
            energy: entry.flow.energy, phase: entry.flow.phase };
          entry.renderer.draw(material, 1, style, colors[style] || null, entry.flow);
        } catch (_) {
          // A lost/failed canvas must not stop the scheduler for every other node.
          entry.renderer.destroy();
          entry.renderer = null;
          entry.failed = true;
          entry.canvas.hidden = true;
        }
      }
      if (!entry.renderer) {
        // Canvas unavailable: legible static fill, no retry loop or blank progress.
        const color = colors[style] || M.PROGRESS_STYLES[style].color;
        entry.track.style.background = `linear-gradient(90deg, ${color} ${entry.motion.target * 100}%, ${M.PROGRESS_STYLES[style].track} 0)`;
      }
      entry.dirty = false;
    }

    function tick(now) {
      frame = 0;
      const candidates = [];
      for (const entry of entries.values()) {
        if (!entry.root.isConnected || !entry.owner?.isConnected) { release(entry.root); continue; }
        if (wantsFrame(entry)) candidates.push(entry);
      }
      // One fair, bounded scheduler. Pan/zoom gets priority; idle nodes cost no frames.
      const interval = isInteracting() || candidates.length > 8 ? 1000 / 30 : 1000 / 60;
      const started = performance.now();
      for (let count = 0; count < candidates.length; count++) {
        const entry = candidates[(cursor + count) % candidates.length];
        if (entry.dirty || now - entry.lastPaint >= interval - .5) draw(entry, now);
        if (performance.now() - started >= 4) { cursor += count + 1; break; }
      }
      schedule();
    }

    function schedule() {
      if (destroyed) return;
      const all = [...entries.values()];
      const needsFrame = all.some(wantsFrame);
      if (needsFrame && !frame) frame = window.requestAnimationFrame(tick);
      if (!needsFrame && frame) { window.cancelAnimationFrame(frame); frame = 0; }
      const needsClock = preferences.style !== 'classic' && all.some(entry => visible(entry)
        && entry.display.running && entry.display.startedAt && !entry.display.elapsedText);
      if (needsClock && !clock) clock = window.setTimeout(() => {
        clock = 0;
        for (const entry of entries.values()) if (visible(entry)) paintText(entry);
        schedule();
      }, 1000);
      if (!needsClock && clock) { window.clearTimeout(clock); clock = 0; }
    }

    function release(root) {
      const entry = entries.get(root);
      if (!entry) return;
      entries.delete(root);
      observer?.unobserve(root);
      resizeObserver?.unobserve(root);
      restoreClassicFill(entry);
      removeMaterial(entry);
      if (!entries.size) {
        window.cancelAnimationFrame(frame); frame = 0;
        window.clearTimeout(clock); clock = 0;
      }
    }
    function releaseWithin(root) {
      if (!root) return;
      for (const entry of entries.values()) {
        if (entry.root === root || entry.owner === root || root.contains(entry.root) || root.contains(entry.owner)) release(entry.root);
      }
      schedule();
    }
    // Some legacy node views replace their shell on polling. Move the material,
    // not its spring/phase/clock; otherwise every receipt would restart the wave.
    function replaceRoot(previous, next, owner = next) {
      const entry = entries.get(previous);
      if (!entry || !next) return;
      entries.delete(previous);
      observer?.unobserve(previous); resizeObserver?.unobserve(previous);
      restoreClassicFill(entry);
      entry.root = next; entry.owner = owner;
      entry.width = 0; entry.inView = !observer;
      entries.set(next, entry);
      if (entry.track) next.appendChild(entry.track);
      syncStyle(entry);
      observer?.observe(next); resizeObserver?.observe(next);
      schedule();
    }
    function clear() { [...entries.keys()].forEach(release); }
    function refreshPreferences() {
      preferences = M.normalizePreferences(getPreferences?.());
      for (const entry of entries.values()) { entry.lastPaint = 0; syncStyle(entry); }
      schedule();
    }
    function resume() {
      for (const entry of entries.values()) {
        entry.lastPaint = 0;
        entry.dirty = entry.measure = true;
        if (reduced()) { entry.motion.reset(entry.motion.target); entry.flow.reset(); }
        if (!document.hidden) paintText(entry);
      }
      schedule();
    }
    function destroy() {
      clear(); destroyed = true;
      observer?.disconnect(); resizeObserver?.disconnect();
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('resize', resume);
      reduce?.removeEventListener?.('change', resume);
    }
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('resize', resume);
    reduce?.addEventListener?.('change', resume);
    return Object.freeze({ update, replaceRoot, releaseWithin, clear, refreshPreferences, destroy });
  }
  window.DesktopProgress = Object.freeze({ create });
})();
