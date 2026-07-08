(function () {
  const SELECT_SELECTOR = 'body.desk-app select:not([multiple]):not([data-desk-select-ignore])';
  const registry = new WeakMap();
  const states = new Set();
  let bodyObserver = null;
  let idSeed = 0;
  let refreshScheduled = false;
  let settersPatched = false;

  function nextId() {
    idSeed += 1;
    return `desk-select-${idSeed}`;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }

  function visibleText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function selectedOption(select) {
    return select?.options?.[select.selectedIndex] || null;
  }

  function optionLabel(option) {
    return visibleText(option?.textContent || option?.label || option?.value || '');
  }

  function patchSelectSetters() {
    if (settersPatched || typeof HTMLSelectElement === 'undefined') return;
    settersPatched = true;
    const descriptors = {};
    ['value', 'selectedIndex'].forEach(key => {
      const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, key);
      if (!descriptor || typeof descriptor.set !== 'function' || typeof descriptor.get !== 'function') return;
      descriptors[key] = descriptor;
      Object.defineProperty(HTMLSelectElement.prototype, key, {
        configurable: descriptor.configurable !== false,
        enumerable: descriptor.enumerable,
        get() {
          return descriptor.get.call(this);
        },
        set(nextValue) {
          descriptor.set.call(this, nextValue);
          scheduleRefreshAll();
        },
      });
    });
    if (descriptors.value || descriptors.selectedIndex) {
      Object.defineProperty(HTMLSelectElement.prototype, '__deskSelectPatched', {
        configurable: true,
        value: true,
      });
    }
  }

  function inferVariant(select) {
    if (select.id === 'deskLanguageSelect' || select.closest('.desk-language-picker')) return 'language';
    if (select.classList.contains('desk-gallery-filter')) return 'gallery';
    if (select.closest('.desk-prompt-node-picker')) return 'prompt';
    if (select.closest('.desk-layout-actions')) return 'layout-actions';
    if (select.closest('.desk-layout-inspector')) return 'layout-inspector';
    if (select.closest('.desk-director-field')) return 'director';
    return 'default';
  }

  function usesAnchoredMenu(select) {
    return !!select?.closest?.('.desk-canvas-world .desk-node');
  }

  function inheritedScale(element) {
    if (!element) return 1;
    const rect = element.getBoundingClientRect();
    const width = element.offsetWidth || 0;
    const height = element.offsetHeight || 0;
    const widthScale = width > 0 ? rect.width / width : 0;
    const heightScale = height > 0 ? rect.height / height : 0;
    const scale = widthScale || heightScale || 1;
    return Number.isFinite(scale) && scale > 0 ? scale : 1;
  }

  function getState(select) {
    return registry.get(select) || null;
  }

  function renderTrigger(state) {
    const { select, shell, trigger, valueEl } = state;
    const option = selectedOption(select);
    const text = optionLabel(option) || visibleText(select.getAttribute('aria-label')) || 'Select';
    valueEl.textContent = text;
    trigger.title = text;
    trigger.disabled = !!select.disabled;
    trigger.setAttribute('aria-disabled', select.disabled ? 'true' : 'false');
    trigger.setAttribute('aria-label', select.getAttribute('aria-label') || text);
    shell.classList.toggle('is-disabled', !!select.disabled);
    shell.dataset.selectValue = select.value || '';

    if (select.id === 'deskLayoutFontFamilySelect') {
      trigger.style.fontFamily = select.style.fontFamily || '';
    } else {
      trigger.style.fontFamily = '';
    }
  }

  function collectOptions(select) {
    const items = [];
    let optionIndex = 0;
    Array.from(select.children).forEach(child => {
      if (child.tagName === 'OPTGROUP') {
        const label = visibleText(child.getAttribute('label'));
        if (label) items.push({ type: 'group', label });
        Array.from(child.children).forEach(option => {
          if (option.tagName !== 'OPTION') return;
          items.push({
            type: 'option',
            option,
            optionIndex,
            value: option.value,
            label: optionLabel(option),
            disabled: option.disabled || child.disabled,
            selected: option.selected,
          });
          optionIndex += 1;
        });
        return;
      }
      if (child.tagName !== 'OPTION') return;
      items.push({
        type: 'option',
        option: child,
        optionIndex,
        value: child.value,
        label: optionLabel(child),
        disabled: child.disabled,
        selected: child.selected,
      });
      optionIndex += 1;
    });
    return items;
  }

  function enabledOptionIndexes(state) {
    return state.items
      .filter(item => item.type === 'option' && !item.disabled)
      .map(item => item.optionIndex);
  }

  function optionId(state, optionIndex) {
    return `${state.id}-option-${optionIndex}`;
  }

  function renderMenu(state) {
    state.items = collectOptions(state.select);
    const selectedIndex = state.select.selectedIndex;
    state.menu.innerHTML = state.items.map(item => {
      if (item.type === 'group') {
        return `<div class="desk-select-group-label">${escapeHtml(item.label)}</div>`;
      }
      const selected = item.optionIndex === selectedIndex;
      const disabled = item.disabled ? ' disabled aria-disabled="true"' : '';
      const selectedAttrs = selected ? ' is-selected" aria-selected="true"' : '" aria-selected="false"';
      return `<button type="button" class="desk-select-option${selectedAttrs} role="option" id="${optionId(state, item.optionIndex)}" data-option-index="${item.optionIndex}"${disabled}>${escapeHtml(item.label)}</button>`;
    }).join('');
    state.menu.setAttribute('aria-label', state.select.getAttribute('aria-label') || state.trigger.getAttribute('aria-label') || 'Select');
  }

  function setHighlighted(state, optionIndex, options = {}) {
    const enabled = enabledOptionIndexes(state);
    const next = enabled.includes(optionIndex) ? optionIndex : enabled[0];
    state.highlightIndex = Number.isFinite(next) ? next : -1;
    state.menu.querySelectorAll('.desk-select-option').forEach(button => {
      const active = Number(button.dataset.optionIndex) === state.highlightIndex;
      button.classList.toggle('is-highlighted', active);
      if (active && options.scroll !== false) {
        button.scrollIntoView({ block: 'nearest' });
      }
    });
    if (state.highlightIndex >= 0) {
      state.trigger.setAttribute('aria-activedescendant', optionId(state, state.highlightIndex));
    } else {
      state.trigger.removeAttribute('aria-activedescendant');
    }
  }

  function moveHighlight(state, delta) {
    const enabled = enabledOptionIndexes(state);
    if (!enabled.length) return;
    const current = enabled.indexOf(state.highlightIndex);
    const base = current >= 0 ? current : enabled.indexOf(state.select.selectedIndex);
    const next = enabled[(Math.max(0, base) + delta + enabled.length) % enabled.length];
    setHighlighted(state, next);
  }

  function placeAnchoredMenu(state) {
    const rect = state.trigger.getBoundingClientRect();
    const margin = 8;
    const scale = inheritedScale(state.trigger);
    const minWidth = state.variant === 'prompt' ? 160 : 132;
    const shellWidth = state.shell.offsetWidth || state.trigger.offsetWidth || minWidth;
    const viewportMaxWidth = Math.max(minWidth, Math.floor((window.innerWidth - margin * 2) / scale));
    const menuWidth = Math.min(Math.max(shellWidth, minWidth), Math.min(320, viewportMaxWidth));
    const menuScreenWidth = menuWidth * scale;
    const availableBelow = window.innerHeight - rect.bottom - margin;
    const availableAbove = rect.top - margin;
    const viewportMaxHeight = Math.max(96, Math.floor((Math.max(availableBelow, availableAbove) - 4) / scale));
    const maxHeight = Math.min(280, viewportMaxHeight);
    const measuredHeight = Math.min(state.menu.scrollHeight, maxHeight);
    const measuredScreenHeight = measuredHeight * scale;
    const opensUp = availableBelow < Math.min(measuredScreenHeight, 180 * scale) && availableAbove > availableBelow;
    const alignRight = rect.left + menuScreenWidth > window.innerWidth - margin && rect.right - menuScreenWidth >= margin;

    state.menu.style.width = `${Math.round(menuWidth)}px`;
    state.menu.style.minWidth = `${Math.round(minWidth)}px`;
    state.menu.style.maxWidth = `${Math.round(viewportMaxWidth)}px`;
    state.menu.style.maxHeight = `${Math.round(maxHeight)}px`;
    state.menu.style.left = alignRight ? 'auto' : '0px';
    state.menu.style.right = alignRight ? '0px' : 'auto';
    state.menu.style.top = opensUp ? 'auto' : 'calc(100% + 4px)';
    state.menu.style.bottom = opensUp ? 'calc(100% + 4px)' : 'auto';
    state.menu.classList.toggle('is-above', opensUp);
  }

  function placeMenu(state) {
    if (!state.open) return;
    if (state.menuMode === 'anchored') {
      placeAnchoredMenu(state);
      return;
    }
    const rect = state.trigger.getBoundingClientRect();
    const margin = 8;
    const minWidth = Math.max(rect.width, state.variant === 'prompt' ? 160 : 132);
    const maxWidth = Math.max(minWidth, Math.min(320, window.innerWidth - margin * 2));
    const width = Math.min(Math.max(minWidth, rect.width), window.innerWidth - margin * 2);
    const availableBelow = window.innerHeight - rect.bottom - margin;
    const availableAbove = rect.top - margin;
    const maxHeight = Math.max(120, Math.min(280, Math.max(availableBelow, availableAbove) - 4));

    state.menu.style.width = `${Math.round(width)}px`;
    state.menu.style.minWidth = `${Math.round(minWidth)}px`;
    state.menu.style.maxWidth = `${Math.round(maxWidth)}px`;
    state.menu.style.maxHeight = `${Math.round(maxHeight)}px`;

    const measuredHeight = Math.min(state.menu.scrollHeight, maxHeight);
    const opensUp = availableBelow < Math.min(measuredHeight, 180) && availableAbove > availableBelow;
    const top = opensUp ? rect.top - measuredHeight - 4 : rect.bottom + 4;
    const left = Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin);

    state.menu.style.left = `${Math.round(left)}px`;
    state.menu.style.top = `${Math.round(Math.max(margin, top))}px`;
    state.menu.classList.toggle('is-above', opensUp);
  }

  function close(state, options = {}) {
    if (!state?.open) return;
    state.open = false;
    state.shell.classList.remove('is-open');
    state.anchorRoot?.classList.remove('is-select-open');
    state.stackRoot?.classList.remove('is-select-open');
    state.trigger.setAttribute('aria-expanded', 'false');
    state.trigger.removeAttribute('aria-activedescendant');
    state.menu.hidden = true;
    state.menu.classList.remove('is-open');
    if (options.focus) state.trigger.focus({ preventScroll: true });
  }

  function closeAll(except = null) {
    states.forEach(state => {
      if (state !== except) close(state);
    });
  }

  function open(state) {
    if (!state || state.select.disabled) return;
    closeAll(state);
    refresh(state.select);
    renderMenu(state);
    state.open = true;
    state.shell.classList.add('is-open');
    state.anchorRoot?.classList.add('is-select-open');
    state.stackRoot?.classList.add('is-select-open');
    state.trigger.setAttribute('aria-expanded', 'true');
    state.menu.hidden = false;
    state.menu.classList.add('is-open');
    const selected = state.select.selectedIndex >= 0 ? state.select.selectedIndex : enabledOptionIndexes(state)[0];
    setHighlighted(state, selected, { scroll: false });
    placeMenu(state);
    requestAnimationFrame(() => {
      placeMenu(state);
      setHighlighted(state, state.highlightIndex, { scroll: true });
    });
  }

  function choose(state, optionIndex) {
    if (!state) return;
    const option = state.select.options[optionIndex];
    if (!option || option.disabled || state.select.disabled) return;
    const before = state.select.selectedIndex;
    state.select.selectedIndex = optionIndex;
    renderTrigger(state);
    renderMenu(state);
    close(state, { focus: true });
    if (before !== optionIndex) {
      state.select.dispatchEvent(new Event('input', { bubbles: true }));
      state.select.dispatchEvent(new Event('change', { bubbles: true }));
      requestAnimationFrame(() => refresh(state.select));
    }
  }

  function findByPrefix(state, key) {
    const now = Date.now();
    state.searchBuffer = now - state.lastSearchAt > 700 ? key : `${state.searchBuffer || ''}${key}`;
    state.lastSearchAt = now;
    const prefix = state.searchBuffer.toLowerCase();
    const enabled = state.items.filter(item => item.type === 'option' && !item.disabled);
    const current = enabled.findIndex(item => item.optionIndex === state.highlightIndex);
    const ordered = [...enabled.slice(current + 1), ...enabled.slice(0, current + 1)];
    const match = ordered.find(item => item.label.toLowerCase().startsWith(prefix));
    if (match) setHighlighted(state, match.optionIndex);
  }

  function handleTriggerKeydown(state, event) {
    if (state.select.disabled) return;
    const key = event.key;
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      event.preventDefault();
      if (!state.open) {
        open(state);
      } else {
        moveHighlight(state, key === 'ArrowDown' ? 1 : -1);
      }
      return;
    }
    if (key === 'Home' || key === 'End') {
      event.preventDefault();
      if (!state.open) open(state);
      const enabled = enabledOptionIndexes(state);
      setHighlighted(state, key === 'Home' ? enabled[0] : enabled[enabled.length - 1]);
      return;
    }
    if (key === 'Enter' || key === ' ') {
      event.preventDefault();
      if (!state.open) {
        open(state);
        return;
      }
      choose(state, state.highlightIndex);
      return;
    }
    if (key === 'Escape' && state.open) {
      event.preventDefault();
      close(state, { focus: true });
      return;
    }
    if (key.length === 1 && /\S/.test(key)) {
      if (!state.open) open(state);
      findByPrefix(state, key);
    }
  }

  function refresh(select) {
    const state = getState(select);
    if (!state) return;
    renderTrigger(state);
    if (state.open) {
      renderMenu(state);
      setHighlighted(state, state.select.selectedIndex, { scroll: false });
      placeMenu(state);
    }
  }

  function destroy(state) {
    if (!state) return;
    close(state);
    states.delete(state);
    state.observer?.disconnect();
    state.anchorRoot?.classList.remove('desk-select-anchor-root', 'is-select-open');
    state.stackRoot?.classList.remove('desk-select-stack-root', 'is-select-open');
    state.shell?.remove();
    state.menu?.remove();
    state.select.classList.remove('desk-select-native');
    if (state.originalTabindex == null) {
      state.select.removeAttribute('tabindex');
    } else {
      state.select.setAttribute('tabindex', state.originalTabindex);
    }
    state.select.removeAttribute('data-desk-select-enhanced');
  }

  function createShell(select) {
    const id = nextId();
    const variant = inferVariant(select);
    const menuMode = usesAnchoredMenu(select) ? 'anchored' : 'fixed';
    const anchorRoot = menuMode === 'anchored' ? select.closest('label') : null;
    const stackRoot = menuMode === 'anchored'
      ? select.closest('.desk-param-grid, .desk-prompt-mode, .desk-prompt-panel, .desk-upload-panel, .desk-node__drawer')
      : null;
    const shell = document.createElement('span');
    shell.className = 'desk-select-shell';
    shell.dataset.selectId = select.id || '';
    shell.dataset.selectVariant = variant;
    shell.dataset.menuMode = menuMode;
    shell.classList.toggle('is-anchored', menuMode === 'anchored');

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'desk-select-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', `${id}-menu`);

    const valueEl = document.createElement('span');
    valueEl.className = 'desk-select-value';
    const chev = document.createElement('span');
    chev.className = 'desk-select-chev';
    chev.setAttribute('aria-hidden', 'true');
    trigger.append(valueEl, chev);
    shell.append(trigger);

    const menu = document.createElement('div');
    menu.className = 'desk-select-menu';
    menu.id = `${id}-menu`;
    menu.hidden = true;
    menu.setAttribute('role', 'listbox');
    if (menuMode === 'anchored') {
      anchorRoot?.classList.add('desk-select-anchor-root');
      stackRoot?.classList.add('desk-select-stack-root');
      shell.appendChild(menu);
    } else {
      document.body.appendChild(menu);
    }
    select.insertAdjacentElement('afterend', shell);

    const state = {
      id,
      select,
      shell,
      trigger,
      valueEl,
      menu,
      variant,
      menuMode,
      anchorRoot,
      stackRoot,
      items: [],
      open: false,
      highlightIndex: -1,
      searchBuffer: '',
      lastSearchAt: 0,
      originalTabindex: select.getAttribute('tabindex'),
      observer: null,
    };

    trigger.addEventListener('click', event => {
      event.preventDefault();
      state.open ? close(state, { focus: true }) : open(state);
    });
    trigger.addEventListener('keydown', event => handleTriggerKeydown(state, event));
    select.addEventListener('change', () => refresh(select));
    select.addEventListener('input', () => refresh(select));
    menu.addEventListener('click', event => {
      const button = event.target.closest('.desk-select-option');
      if (!button || button.disabled) return;
      choose(state, Number(button.dataset.optionIndex));
    });
    menu.addEventListener('pointerdown', event => {
      if (event.target.closest('.desk-select-option')) event.preventDefault();
    });

    state.observer = new MutationObserver(() => scheduleRefreshAll());
    state.observer.observe(select, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['disabled', 'aria-label', 'class', 'style'],
    });

    return state;
  }

  function enhance(select) {
    if (!select || registry.has(select) || select.matches('[data-desk-select-ignore]')) return null;
    if (!document.body?.classList.contains('desk-app')) return null;
    const state = createShell(select);
    select.dataset.deskSelectEnhanced = '1';
    select.classList.add('desk-select-native');
    select.setAttribute('tabindex', '-1');
    registry.set(select, state);
    states.add(state);
    refresh(select);
    return state;
  }

  function enhanceIn(root = document) {
    const scope = root?.nodeType === Node.ELEMENT_NODE || root?.nodeType === Node.DOCUMENT_NODE ? root : document;
    if (scope.matches?.(SELECT_SELECTOR)) enhance(scope);
    scope.querySelectorAll?.(SELECT_SELECTOR).forEach(enhance);
  }

  function cleanupDisconnected() {
    states.forEach(state => {
      if (!state.select.isConnected) destroy(state);
    });
  }

  function refreshAll() {
    cleanupDisconnected();
    states.forEach(state => refresh(state.select));
  }

  function scheduleRefreshAll() {
    if (refreshScheduled) return;
    refreshScheduled = true;
    requestAnimationFrame(() => {
      refreshScheduled = false;
      enhanceIn(document);
      refreshAll();
    });
  }

  function init() {
    if (!document.body?.classList.contains('desk-app')) return;
    patchSelectSetters();
    enhanceIn(document);
    refreshAll();
    if (!bodyObserver) {
      bodyObserver = new MutationObserver(mutations => {
        let shouldScan = false;
        mutations.forEach(mutation => {
          mutation.addedNodes?.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE && (node.matches?.('select') || node.querySelector?.('select'))) {
              shouldScan = true;
            }
          });
        });
        if (shouldScan) scheduleRefreshAll();
      });
      bodyObserver.observe(document.body, { childList: true, subtree: true });
    }
  }

  document.addEventListener('pointerdown', event => {
    const target = event.target;
    states.forEach(state => {
      if (!state.open) return;
      if (state.shell.contains(target) || state.menu.contains(target)) return;
      close(state);
    });
  }, true);

  window.addEventListener('resize', () => states.forEach(placeMenu));
  window.addEventListener('scroll', () => states.forEach(placeMenu), true);
  window.addEventListener('desktop:language-change', () => window.setTimeout(scheduleRefreshAll, 0));
  window.addEventListener('desktop:theme-change', () => states.forEach(placeMenu));

  window.DesktopSelect = {
    init,
    enhance,
    refresh,
    refreshAll: scheduleRefreshAll,
    closeAll,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
