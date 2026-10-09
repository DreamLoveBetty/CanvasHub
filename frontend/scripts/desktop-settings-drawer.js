// Settings drawer width: drag / keyboard resizing of the left-docked settings centre,
// clamped to the viewport and persisted through DesktopPreferences. Owns no settings
// content, tabs or open/close state (desktop-settings.js keeps those).
(function () {
  const MIN = 560;
  const MAX = 1100;
  const DEFAULT = 760;
  const STEP = 20;
  // Space the drawer cannot take: rail on the left plus a gutter on the right.
  const RESERVED = 72 + 24;

  function normalizeWidth(value) {
    const width = Number(value);
    return Number.isFinite(width) ? Math.round(Math.max(MIN, Math.min(MAX, width))) : DEFAULT;
  }

  // The stored preference stays as chosen; the displayed width also respects the window.
  function displayWidth(value, viewportWidth) {
    const room = Math.max(MIN, Number(viewportWidth) - RESERVED);
    return Math.min(normalizeWidth(value), room);
  }

  function create({ panel, handle, getWidth, setWidth, viewportWidth = () => window.innerWidth, requestFrame = window.requestAnimationFrame.bind(window) }) {
    if (!panel || !handle) return null;
    const controller = new AbortController();
    const { signal } = controller;
    let current = displayWidth(getWidth(), viewportWidth());
    let drag = null, frame = 0;

    function apply(width) {
      current = displayWidth(width, viewportWidth());
      panel.style.setProperty('--desk-settings-width', `${current}px`);
      handle.setAttribute('aria-valuenow', String(current));
      handle.setAttribute('aria-valuetext', `${current} 像素`);
    }
    function commit(width) {
      apply(width);
      setWidth(normalizeWidth(current));
    }

    handle.setAttribute('aria-valuemin', String(MIN));
    handle.setAttribute('aria-valuemax', String(MAX));
    apply(getWidth());

    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      handle.setPointerCapture?.(event.pointerId);
      drag = { id: event.pointerId, startX: event.clientX, startWidth: current, next: current };
      panel.classList.add('is-resizing');
    }, { signal });
    handle.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.id) return;
      drag.next = drag.startWidth + (event.clientX - drag.startX);
      // One style write per frame, however many pointer events arrive.
      if (!frame) frame = requestFrame(() => { frame = 0; if (drag) apply(drag.next); });
    }, { signal });
    const finish = event => {
      if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.id)) return;
      const next = drag.next;
      drag = null;
      panel.classList.remove('is-resizing');
      commit(next);
    };
    handle.addEventListener('pointerup', finish, { signal });
    handle.addEventListener('pointercancel', finish, { signal });
    handle.addEventListener('dblclick', () => commit(DEFAULT), { signal });
    handle.addEventListener('keydown', event => {
      const next = { ArrowLeft: current - STEP, ArrowRight: current + STEP, Home: MIN, End: MAX }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      commit(next);
    }, { signal });
    window.addEventListener('resize', () => apply(getWidth()), { signal });

    return Object.freeze({
      width: () => current,
      refresh: () => apply(getWidth()),
      destroy: () => { controller.abort(); panel.classList.remove('is-resizing'); },
    });
  }

  window.DesktopSettingsDrawer = Object.freeze({ MIN, MAX, DEFAULT, STEP, normalizeWidth, displayWidth, create });
})();
