// The gallery's spec facets: record status, orientation, resolution and format. Each facet is
// single-choice, facets combine with AND, and they stack on top of the scope select (time,
// provider, marks) that desktop-history.js owns. Owns only the facet values and the popover;
// the host reads them through params() for /api/assets and matches() for local filtering.
// Load before desktop-history.js; no I/O.
(function () {
  'use strict';
  const FACETS = [
    { key: 'record', label: '记录', options: [['linked', '有记录'], ['orphan', '仅归档'], ['missing_history', '未归档记录']] },
    { key: 'orientation', label: '方向', options: [['landscape', '横图'], ['portrait', '竖图'], ['square', '方图']] },
    { key: 'resolution', label: '分辨率', options: [['1k', '1K'], ['2k', '2K'], ['4k', '4K']] },
    { key: 'format', label: '格式', options: [['png', 'PNG'], ['jpg', 'JPG'], ['webp', 'WEBP']] },
  ];
  const KEYS = FACETS.map(facet => facet.key);
  const normalizeFormat = value => {
    const format = String(value || '').toLowerCase();
    return format === 'jpeg' ? 'jpg' : format;
  };

  function create({ root, escapeHtml, onChange }) {
    const values = Object.fromEntries(KEYS.map(key => [key, '']));
    const toggle = root?.querySelector('[data-gallery-facets-toggle]');
    const panel = root?.querySelector('[data-gallery-facets-panel]');

    const activeCount = () => KEYS.filter(key => values[key]).length;

    function renderToggle() {
      if (!toggle) return;
      const count = activeCount();
      const badge = toggle.querySelector('em');
      if (badge) {
        badge.hidden = !count;
        badge.textContent = String(count);
      }
      toggle.classList.toggle('is-active', count > 0);
      toggle.setAttribute('aria-expanded', panel && !panel.hidden ? 'true' : 'false');
    }

    function renderPanel() {
      if (!panel) return;
      panel.innerHTML = FACETS.map(facet => `
        <div class="desk-gallery-facets__group" role="group" aria-label="${escapeHtml(facet.label)}">
          <span>${escapeHtml(facet.label)}</span>
          <div class="desk-gallery-facets__options">
            ${facet.options.map(([value, label]) => {
              const pressed = values[facet.key] === value;
              return `<button type="button" data-facet-key="${facet.key}" data-facet-value="${value}" aria-pressed="${pressed}"${pressed ? ' class="is-active"' : ''}>${escapeHtml(label)}</button>`;
            }).join('')}
          </div>
        </div>
      `).join('') + `
        <div class="desk-gallery-facets__foot">
          <button type="button" data-facet-clear${activeCount() ? '' : ' disabled'}>清除规格</button>
        </div>`;
    }

    function render() {
      renderToggle();
      if (panel && !panel.hidden) renderPanel();
    }

    function open() {
      if (!panel) return;
      renderPanel();
      panel.hidden = false;
      renderToggle();
      panel.querySelector('button')?.focus();
    }

    function close({ focus = false } = {}) {
      if (!panel || panel.hidden) return;
      panel.hidden = true;
      renderToggle();
      if (focus) toggle?.focus();
    }

    // Choosing the active value again clears that facet.
    function set(key, value, { notify = true } = {}) {
      if (!KEYS.includes(key)) return;
      const next = values[key] === value ? '' : String(value || '');
      if (values[key] === next) return;
      values[key] = next;
      render();
      if (notify) onChange?.();
    }

    function clear({ notify = true } = {}) {
      if (!activeCount()) return;
      KEYS.forEach(key => { values[key] = ''; });
      render();
      if (notify) onChange?.();
    }

    function params() {
      return {
        source: values.record,
        orientation: values.orientation,
        resolution: values.resolution,
        format: values.format,
      };
    }

    function matches(asset) {
      if (!asset) return false;
      if (values.record === 'linked' && !asset.hasTaskRecord) return false;
      if (values.record === 'orphan' && asset.hasTaskRecord) return false;
      if (values.record === 'missing_history' && !asset.missingArchive) return false;
      if (values.orientation && asset.orientation !== values.orientation) return false;
      if (values.resolution && String(asset.resolution || '').toLowerCase() !== values.resolution) return false;
      if (values.format && normalizeFormat(asset.format) !== values.format) return false;
      return true;
    }

    function setHidden(hidden) {
      if (!root) return;
      root.hidden = Boolean(hidden);
      if (hidden) close();
    }

    toggle?.addEventListener('click', () => {
      if (panel?.hidden) open();
      else close();
    });
    panel?.addEventListener('click', event => {
      const option = event.target.closest('[data-facet-key]');
      if (option) {
        set(option.dataset.facetKey, option.dataset.facetValue);
        panel.querySelector(`[data-facet-key="${option.dataset.facetKey}"][data-facet-value="${option.dataset.facetValue}"]`)?.focus();
        return;
      }
      if (event.target.closest('[data-facet-clear]')) {
        clear();
        toggle?.focus();
      }
    });
    root?.addEventListener('keydown', event => {
      if (event.key === 'Escape' && panel && !panel.hidden) {
        event.stopPropagation();
        close({ focus: true });
      }
    });
    document.addEventListener('pointerdown', event => {
      if (panel && !panel.hidden && !root.contains(event.target)) close();
    }, true);

    renderToggle();
    return Object.freeze({
      set, clear, close, params, matches, setHidden, render,
      value: key => values[key] || '',
      get activeCount() { return activeCount(); },
    });
  }

  window.DesktopGalleryFacets = Object.freeze({ create, FACETS });
})();
