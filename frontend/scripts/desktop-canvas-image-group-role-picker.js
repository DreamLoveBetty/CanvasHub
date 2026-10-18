// 图片组参考用途的 Morph 选单：点击缩略图（或在图片上按 Enter/空格）后，选项以缩略图为中心环形弹开，
// 靠近时液态相融（liquid-gooey morph）。左上角的用途只是标签。
// The host owns events and state: it forwards taps (from the sort gesture), clicks, keys and outside
// pointers, and commits the role in onSelect.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  // Ring around the thumbnail centre, clockwise from the top, in base (unscaled) px: with
  // 52px buttons it stays inside the 240px thumbnail (82 + 26 < 120).
  const RING_RADIUS = 82;
  const RING_START_DEG = -90;
  const FILTER_ID = 'desk-image-group-picker-goo';
  // Long enough for the collapse to land before cleanup.
  const CLOSE_MS = 320;
  // One stroke icon per role (24-unit grid); the full role name is the button's label/title.
  const ROLE_ICONS = Object.freeze({
    // General reference: an eye (look at it).
    reference: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"></path><circle cx="12" cy="12" r="3"></circle>',
    // Subject: a person.
    subject: '<circle cx="12" cy="8" r="3.6"></circle><path d="M4.5 20.5c1.4-3.8 4.2-5.7 7.5-5.7s6.1 1.9 7.5 5.7"></path>',
    // Clothing: a shirt.
    clothing: '<path d="M8.5 3.5 4 6.3l1.8 3.9 2.2-1v11.3h8V9.2l2.2 1 1.8-3.9-4.5-2.8c-.6 1.5-2 2.4-3.5 2.4s-2.9-.9-3.5-2.4z"></path>',
    // Style: a painter's palette.
    style: '<path d="M12 3.2a8.8 8.8 0 1 0 0 17.6c1 0 1.5-.7 1.5-1.4 0-1-.8-1.3-.8-2.2 0-.9.7-1.5 1.6-1.5h1.9a4.6 4.6 0 0 0 4.6-4.6c0-4.4-3.9-7.9-8.8-7.9z"></path><circle cx="7.6" cy="11.2" r="1"></circle><circle cx="10" cy="7.4" r="1"></circle><circle cx="14.6" cy="7.4" r="1"></circle>',
    // Composition: a rule-of-thirds frame.
    composition: '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"></rect><path d="M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17"></path>',
    // Background: a landscape behind the frame.
    background: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"></rect><path d="m3.8 17 4.8-5 3.6 3.6 2.6-2.6 5.4 4.6"></path><circle cx="15.5" cy="8.8" r="1.4"></circle>'
  });

  function ringPosition(index, count) {
    const angle = (RING_START_DEG + (360 / count) * index) * Math.PI / 180;
    return {
      x: Math.round(Math.cos(angle) * RING_RADIUS * 100) / 100,
      y: Math.round(Math.sin(angle) * RING_RADIUS * 100) / 100
    };
  }

  function create({
    IMAGE_GROUP_ROLES,
    escapeHtml,
    imageGroupGooeyFilterPrimitivesHtml,
    normalizeImageGroupRole,
    onSelect,
    prefersReducedMotion
  }) {
    let current = null;
    // A press on the open picker's own thumbnail closes it; the tap that follows must not reopen it.
    let swallowTapFor = null;

    function ensureFilter() {
      if (document.getElementById(FILTER_ID)) return;
      document.body.insertAdjacentHTML('beforeend', `
        <svg class="desk-image-group__global-filter" aria-hidden="true">
          <defs>
            <filter id="${FILTER_ID}" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">${imageGroupGooeyFilterPrimitivesHtml()}</filter>
          </defs>
        </svg>`);
    }

    function roleEntry(role) {
      return IMAGE_GROUP_ROLES.find(item => item.value === role) || { value: 'reference', label: '参考', short: '参考' };
    }

    function pickerHtml(role, label) {
      const normalized = normalizeImageGroupRole(role);
      const slot = (index, position) => `--i:${index};--x:${position.x};--y:${position.y}`;
      const options = IMAGE_GROUP_ROLES.map((item, index) => ({ item, position: ringPosition(index, IMAGE_GROUP_ROLES.length), order: index + 1 }));
      const blobs = [`<span class="is-center" style="${slot(0, { x: 0, y: 0 })}"></span>`]
        .concat(options.map(({ position, order }) => `<span style="${slot(order, position)}"></span>`))
        .join('');
      const buttons = options.map(({ item, position, order }) => {
        const checked = item.value === normalized;
        const icon = ROLE_ICONS[item.value] || ROLE_ICONS.reference;
        return `<button type="button" class="desk-image-group-picker__option${checked ? ' is-current' : ''}" role="menuitemradio" aria-checked="${checked}" aria-label="${escapeHtml(item.label)}" data-image-group-role-option="${escapeHtml(item.value)}" title="${escapeHtml(item.label)}" style="${slot(order, position)}"><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg></button>`;
      }).join('');
      return `
        <div class="desk-image-group-picker" data-image-group-role-picker role="menu" aria-label="${escapeHtml(label)}的参考用途">
          <div class="desk-image-group-picker__goo" aria-hidden="true">${blobs}</div>
          <div class="desk-image-group-picker__buttons">
            <button type="button" class="desk-image-group-picker__close" data-image-group-role-close aria-label="收起参考用途" style="${slot(0, { x: 0, y: 0 })}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg></button>
            ${buttons}
          </div>
        </div>`;
    }

    function isOpen() {
      return Boolean(current?.overlay?.isConnected && !current.closing);
    }

    function close({ focusItem = false, immediate = false } = {}) {
      const state = current;
      if (!state) return;
      current = null;
      state.closing = true;
      state.item?.classList.remove('is-picking');
      if (focusItem && state.item?.isConnected) state.item.focus({ preventScroll: true });
      if (immediate || prefersReducedMotion() || !state.overlay?.isConnected) {
        state.overlay?.remove();
        return;
      }
      state.overlay.classList.remove('is-open');
      window.setTimeout(() => state.overlay.remove(), CLOSE_MS);
    }

    function open(item) {
      if (!item?.dataset?.imageGroupItem) return;
      close({ immediate: true });
      ensureFilter();
      const label = item.dataset.imageGroupLabel || '图片';
      item.insertAdjacentHTML('beforeend', pickerHtml(item.dataset.role || 'reference', label));
      const overlay = item.querySelector(':scope > [data-image-group-role-picker]');
      current = { item, overlay, closing: false };
      item.classList.add('is-picking');
      const focusTarget = overlay.querySelector('.is-current') || overlay.querySelector('[data-image-group-role-option]');
      if (prefersReducedMotion()) {
        overlay.classList.add('is-open');
        focusTarget?.focus({ preventScroll: true });
        return;
      }
      // The closed pose must have a computed style before the spring has something to leave:
      // flush it now, then open on the next frame.
      overlay.getBoundingClientRect();
      requestAnimationFrame(() => {
        if (current?.overlay !== overlay) return;
        overlay.classList.add('is-open');
        focusTarget?.focus({ preventScroll: true });
      });
    }

    // A tap on a thumbnail (a press without a drag, reported by the sort gesture) toggles its picker.
    function tap(item) {
      const swallowed = swallowTapFor === item;
      swallowTapFor = null;
      if (swallowed) return;
      if (current?.item === item && isOpen()) {
        close({ focusItem: true });
        return;
      }
      open(item);
    }

    // Clicks inside an open picker: an option commits, the centre button closes.
    function handleClick(event) {
      if (!event.target.closest?.('[data-image-group-role-picker]')) return false;
      const option = event.target.closest('[data-image-group-role-option]');
      if (option && current) {
        const role = normalizeImageGroupRole(option.dataset.imageGroupRoleOption);
        const { item } = current;
        onSelect(item, role);
        item.dataset.role = role;
        const entry = roleEntry(role);
        const tag = item.querySelector('[data-image-group-role-label]');
        if (tag) tag.textContent = entry.short;
        item.setAttribute('aria-description', `参考用途：${entry.label}`);
        close({ focusItem: true });
        return true;
      }
      if (event.target.closest('[data-image-group-role-close]')) close({ focusItem: true });
      return true;
    }

    function handlePointerDown(event) {
      swallowTapFor = null;
      if (!current) return;
      if (event.target.closest?.('[data-image-group-role-picker]')) return;
      const thumb = event.target.closest?.('[data-image-group-sort-handle]');
      if (thumb && current.item.contains(thumb)) swallowTapFor = current.item;
      close();
    }

    function handleKeydown(event) {
      if (!isOpen()) {
        // Enter or Space on a focused thumbnail opens its picker (the keyboard counterpart of a tap).
        const item = event.target?.matches?.('[data-image-group-item]') ? event.target : null;
        if (!item || (event.key !== 'Enter' && event.key !== ' ')) return false;
        event.preventDefault();
        open(item);
        return true;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        close({ focusItem: true });
        return true;
      }
      if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return false;
      const options = Array.from(current.overlay.querySelectorAll('[data-image-group-role-option]'));
      if (!options.length) return false;
      const index = options.indexOf(document.activeElement);
      const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1;
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? options.length - 1
          : (Math.max(0, index) + step + options.length) % options.length;
      event.preventDefault();
      options[next].focus({ preventScroll: true });
      return true;
    }

    return Object.freeze({ open, close, tap, isOpen, handleClick, handlePointerDown, handleKeydown });
  }

  window.DesktopCanvasImageGroupRolePicker = Object.freeze({ create, ringPosition, RING_RADIUS, ROLE_ICONS });
})();
