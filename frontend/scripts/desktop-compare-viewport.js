(function (root) {
  'use strict';
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  // Both originals use contain at the same center, then the SAME view transform.
  // The reveal mask translates separately; it must never scale the clipping edge.
  function geometry(size, images, view = { zoom: 1, x: 0, y: 0 }) {
    const { width, height } = size;
    if (!(width > 0 && height > 0)) return null;
    let fitWidth = 0, fitHeight = 0, pixelZoom = 1;
    images.forEach((img, index) => {
      if (!(img?.naturalWidth > 0 && img?.naturalHeight > 0)) return;
      const fit = Math.min(width / img.naturalWidth, height / img.naturalHeight);
      fitWidth = Math.max(fitWidth, img.naturalWidth * fit);
      fitHeight = Math.max(fitHeight, img.naturalHeight * fit);
      if (index === 0) pixelZoom = 1 / fit;
    });
    fitWidth ||= width; fitHeight ||= height;
    const minZoom = Math.min(.1, pixelZoom), maxZoom = Math.max(16, pixelZoom * 4);
    const zoom = clamp(Number(view.zoom) || 1, minZoom, maxZoom);
    const xLimit = Math.max(0, (fitWidth * zoom - width) / 2);
    const yLimit = Math.max(0, (fitHeight * zoom - height) / 2);
    const x = clamp(Number(view.x) || 0, -xLimit, xLimit);
    const y = clamp(Number(view.y) || 0, -yLimit, yLimit);
    const left = Math.max(0, (width - fitWidth * zoom) / 2 + x);
    const right = Math.min(width, (width + fitWidth * zoom) / 2 + x);
    const top = Math.max(0, (height - fitHeight * zoom) / 2 + y);
    const bottom = Math.min(height, (height + fitHeight * zoom) / 2 + y);
    return { zoom, x, y, minZoom, maxZoom, pixelZoom,
      band: { left, top, width: right - left, height: bottom - top } };
  }

  function zoomAt(view, next, point, size) {
    const ratio = next / view.zoom;
    const ax = point.x - size.width / 2, ay = point.y - size.height / 2;
    return { zoom: next, x: ax - (ax - view.x) * ratio, y: ay - (ay - view.y) * ratio };
  }

  function create({ stage, base, top, overlay, divider, range }) {
    if (!stage || !base || !top || !overlay || !divider || !range) return null;
    const images = [top, base]; // A is the left reveal layer, B is the background.
    const toolbar = stage.querySelector('[data-compare-tools]');
    const readout = stage.querySelector('[data-compare-zoom-value]');
    const listeners = [];
    let active = false, frame = 0, view = { zoom: 1, x: 0, y: 0 };
    let percent = 50, drag = null, pixelMode = false;
    const size = () => stage.getBoundingClientRect();
    const measure = rect => geometry(rect, images, view);
    const listen = (node, type, callback, options) => {
      node?.addEventListener(type, callback, options);
      listeners.push(() => node?.removeEventListener(type, callback, options));
    };

    function paint() {
      frame = 0;
      if (!active) return;
      const rect = size(), g = measure(rect);
      if (!g) return;
      view = { zoom: g.zoom, x: g.x, y: g.y };
      const band = g.band;
      const seam = band.left + band.width * percent / 100;
      const hidden = rect.width - seam;
      // Translate the overlay left, compensate in the top image BEFORE scaling.
      overlay.style.transform = `translateX(-${hidden}px)`;
      base.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
      top.style.transform = `translate(${hidden + view.x}px, ${view.y}px) scale(${view.zoom})`;
      divider.style.left = '0';
      divider.style.transform = `translateX(${seam - .5}px)`;
      divider.style.top = `${band.top}px`;
      divider.style.bottom = 'auto';
      divider.style.height = `${band.height}px`;
      range.value = String(percent);
      range.setAttribute('aria-valuetext', `图片 A ${Math.round(percent)}%，图片 B ${Math.round(100 - percent)}%`);
      stage.classList.toggle('is-zoomed', view.zoom > 1.001);
      if (readout) readout.textContent = `${Number(view.zoom.toFixed(2))}×`;
      toolbar?.querySelectorAll('[data-compare-zoom]').forEach(button => {
        const action = button.dataset.compareZoom;
        button.disabled = action === 'in' ? view.zoom >= g.maxZoom : action === 'out' ? view.zoom <= g.minZoom
          : action === 'pixel' ? !top.naturalWidth : false;
      });
    }

    function schedule() {
      if (active && !frame) frame = root.requestAnimationFrame(paint);
    }

    function endDrag() {
      if (drag) {
        const id = drag.id;
        drag = null;
        try { stage.releasePointerCapture(id); } catch (_) { /* Capture may already be lost. */ }
      }
      stage.classList.remove('is-panning');
    }

    function zoomTo(next, point) {
      const rect = size(), g = measure(rect);
      if (!g) return;
      view = zoomAt(g, clamp(next, g.minZoom, g.maxZoom),
        point || { x: rect.width / 2, y: rect.height / 2 }, rect);
      schedule();
    }

    function command(action) {
      endDrag();
      pixelMode = action === 'pixel';
      if (action === 'fit') { view = { zoom: 1, x: 0, y: 0 }; schedule(); }
      else if (action === 'pixel') {
        view = { zoom: measure(size())?.pixelZoom || 1, x: 0, y: 0 }; schedule();
      } else zoomTo(view.zoom * (action === 'in' ? 1.25 : 1 / 1.25));
    }

    function reveal(clientX, rect) {
      const g = measure(rect);
      if (g?.band.width) percent = clamp((clientX - rect.left - g.band.left) / g.band.width * 100, 0, 100);
      schedule();
    }

    listen(toolbar, 'click', event => {
      const button = event.target.closest('[data-compare-zoom]');
      if (button && !button.disabled) command(button.dataset.compareZoom);
    });
    listen(range, 'input', event => { percent = clamp(Number(event.target.value) || 0, 0, 100); schedule(); });
    listen(stage, 'wheel', event => {
      if (!active || toolbar?.contains(event.target)) return;
      event.preventDefault(); endDrag(); pixelMode = false;
      const rect = size();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
      zoomTo(view.zoom * Math.exp(-clamp(delta, -240, 240) * .003),
        { x: event.clientX - rect.left, y: event.clientY - rect.top });
    }, { passive: false });
    listen(stage, 'pointerdown', event => {
      if (!active || event.button !== 0 || drag || toolbar?.contains(event.target)) return;
      const rect = size(), g = measure(rect);
      if (!g) return;
      view = { zoom: g.zoom, x: g.x, y: g.y };
      const seam = g.band.left + g.band.width * percent / 100;
      const atSeam = Math.abs(event.clientX - rect.left - seam) <= 16;
      const mode = view.zoom > 1.001 && !atSeam ? 'pan' : 'reveal';
      drag = { id: event.pointerId, mode, rect, x: event.clientX, y: event.clientY, view: { ...view } };
      try { stage.setPointerCapture(event.pointerId); } catch (_) { /* Synthetic pointer. */ }
      stage.focus({ preventScroll: true });
      stage.classList.toggle('is-panning', mode === 'pan');
      if (mode === 'reveal') reveal(event.clientX, rect);
      event.preventDefault();
    });
    listen(stage, 'pointermove', event => {
      if (!drag || drag.id !== event.pointerId) return;
      if (drag.mode === 'reveal') reveal(event.clientX, drag.rect);
      else {
        view = { ...drag.view, x: drag.view.x + event.clientX - drag.x, y: drag.view.y + event.clientY - drag.y };
        schedule();
      }
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => listen(stage, type, event => {
      if (drag?.id === event.pointerId) endDrag();
    }));
    listen(stage, 'dblclick', event => {
      if (toolbar?.contains(event.target)) return;
      event.preventDefault(); command(Math.abs(view.zoom - 1) < .001 ? 'pixel' : 'fit');
    });
    listen(stage, 'keydown', event => {
      if (event.target === range) return; // Native range retains arrow-key reveal control.
      const action = { '+': 'in', '=': 'in', '-': 'out', '0': 'fit', '1': 'pixel' }[event.key];
      if (action) { event.preventDefault(); command(action); }
    });
    listen(stage, 'dragstart', event => event.preventDefault());
    const resized = () => {
      if (!active) return;
      endDrag();
      if (pixelMode) view.zoom = measure(size())?.pixelZoom || 1;
      schedule();
    };
    images.forEach(img => listen(img, 'load', resized));
    const observer = typeof root.ResizeObserver === 'function' ? new root.ResizeObserver(resized) : null;
    observer?.observe(stage);
    if (!observer) listen(root, 'resize', resized);

    function close() {
      active = false; endDrag();
      if (frame) root.cancelAnimationFrame(frame);
      frame = 0;
    }
    return Object.freeze({
      open({ preserve = false } = {}) {
        endDrag(); active = true;
        if (!preserve) { view = { zoom: 1, x: 0, y: 0 }; percent = 50; pixelMode = false; }
        else pixelMode = false; // Swap preserves the shared view, not A's old pixel density.
        schedule();
      },
      close,
      destroy() { close(); observer?.disconnect(); listeners.forEach(remove => remove()); }
    });
  }
  root.DesktopCompareViewport = Object.freeze({ create, geometry, zoomAt });
})(window);
