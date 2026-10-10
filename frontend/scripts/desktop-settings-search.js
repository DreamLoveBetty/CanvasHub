// Settings search: a card index across every settings category, keyword matching and
// the results listbox. Owns no settings data or navigation — the settings host supplies
// each category's card HTML (rendered from data it already loaded) and moves to the
// chosen card. Index building is pure apart from parsing into an inert <template>.
(function () {
  const FIELD_SELECTOR = [
    'label > span:first-child',
    '.desk-settings-kv > span',
    '.desk-settings-path span',
    '.desk-settings-secret-field__label > span',
    '.desk-settings-secret-field > span',
    '.desk-settings-color-field > span',
    '.desk-settings-form__section-title strong',
    '.desk-settings-canvas-interaction__label',
    'summary span',
  ].join(', ');

  const normalize = text => String(text ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  // categories: [{ tab, label, group, html }] → [{ tab, tabLabel, group, cardIndex, title, fields }]
  function buildIndex(categories, doc = document) {
    const template = doc.createElement('template');
    const entries = [];
    for (const category of categories) {
      template.innerHTML = category.html || '';
      template.content.querySelectorAll('.desk-settings-card').forEach((card, cardIndex) => {
        const title = card.querySelector('header h3, h3')?.textContent.trim() || category.label;
        const fields = [...card.querySelectorAll(FIELD_SELECTOR)]
          .filter(el => !el.closest('[aria-hidden="true"]'))
          .map(el => el.textContent.replace(/\s+/g, ' ').trim())
          .filter(text => text && text.length <= 40);
        // Hints are searchable (lower rank) but never shown as the matched field.
        const notes = [...card.querySelectorAll('.desk-settings-form__hint')].map(el => el.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean);
        entries.push({ tab: category.tab, tabLabel: category.label, group: category.group || '', cardIndex, title, fields: [...new Set(fields)], notes });
      });
    }
    return entries;
  }

  // Every whitespace-separated term must appear in the card (title, fields or category).
  // Title hits rank first; the first field containing a term is reported as the hit.
  function search(entries, query, limit = 12) {
    const terms = normalize(query).split(' ').filter(Boolean);
    if (!terms.length) return [];
    const hits = [];
    for (const entry of entries) {
      const title = normalize(entry.title), category = normalize(entry.tabLabel);
      const fields = entry.fields.map(normalize);
      const notes = (entry.notes || []).map(normalize);
      const all = [title, category, ...fields, ...notes].join(' ');
      if (!terms.every(term => all.includes(term))) continue;
      const titleHits = terms.filter(term => title.includes(term)).length;
      const fieldIndex = fields.findIndex(field => terms.some(term => field.includes(term)));
      const inNotesOnly = !titleHits && fieldIndex < 0 && !terms.some(term => category.includes(term));
      hits.push({ entry, field: fieldIndex >= 0 ? entry.fields[fieldIndex] : '', viaNote: inNotesOnly || (fieldIndex < 0 && !titleHits && notes.some(note => terms.some(term => note.includes(term)))), score: titleHits * 10 + (fieldIndex >= 0 ? 2 : 0) + (inNotesOnly ? 0 : 1) });
    }
    return hits.sort((a, b) => b.score - a.score).slice(0, limit);
  }

  function highlight(text, query) {
    let html = escapeHtml(text);
    for (const term of normalize(query).split(' ').filter(Boolean)) {
      const safe = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      html = html.replace(new RegExp(`(${safe})(?![^<]*>)`, 'ig'), '<mark>$1</mark>');
    }
    return html;
  }

  // Wires the search box. getIndex() is called lazily per query so the index always
  // reflects the latest loaded settings; onSelect(hit) performs navigation.
  function create({ input, results, getIndex, onSelect }) {
    if (!input || !results) return null;
    let hits = [], active = -1;
    const controller = new AbortController();
    const { signal } = controller;

    function setOpen(open) {
      results.hidden = !open;
      input.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) input.removeAttribute('aria-activedescendant');
    }
    function paintActive() {
      results.querySelectorAll('[role="option"]').forEach((option, index) => {
        option.classList.toggle('is-active', index === active);
        option.setAttribute('aria-selected', index === active ? 'true' : 'false');
      });
      if (active >= 0) {
        input.setAttribute('aria-activedescendant', `deskSettingsSearchOption${active}`);
        results.querySelector(`#deskSettingsSearchOption${active}`)?.scrollIntoView({ block: 'nearest' });
      }
    }
    function render() {
      const query = input.value;
      if (!normalize(query)) { hits = []; results.innerHTML = ''; setOpen(false); return; }
      hits = search(getIndex() || [], query);
      active = hits.length ? 0 : -1;
      results.innerHTML = hits.length
        ? hits.map((hit, index) => `<div class="desk-settings-search__option" role="option" id="deskSettingsSearchOption${index}" data-search-index="${index}" aria-selected="false">
            <span class="desk-settings-search__path">${escapeHtml(hit.entry.tabLabel)} ›</span>
            <strong>${highlight(hit.entry.title, query)}</strong>
            ${hit.field ? `<small>${highlight(hit.field, query)}</small>` : hit.viaNote ? '<small>说明中提及</small>' : ''}
          </div>`).join('')
        : '<div class="desk-settings-search__empty">没有匹配的设置</div>';
      setOpen(true);
      paintActive();
    }
    function choose(index) {
      const hit = hits[index];
      if (!hit) return;
      setOpen(false);
      onSelect?.(hit);
    }

    input.addEventListener('input', render, { signal });
    input.addEventListener('focus', () => { if (normalize(input.value)) render(); }, { signal });
    input.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (results.hidden) { render(); return event.preventDefault(); }
        event.preventDefault();
        if (!hits.length) return;
        active = (active + (event.key === 'ArrowDown' ? 1 : -1) + hits.length) % hits.length;
        paintActive();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        choose(active >= 0 ? active : 0);
      } else if (event.key === 'Escape' && (!results.hidden || input.value)) {
        // First Escape clears the search; the drawer handles the next one.
        event.preventDefault();
        event.stopPropagation();
        input.value = '';
        render();
      }
    }, { signal });
    // pointerdown keeps focus in the input until the choice is applied.
    results.addEventListener('pointerdown', event => {
      const option = event.target.closest('[data-search-index]');
      if (!option) return;
      event.preventDefault();
      choose(Number(option.dataset.searchIndex));
    }, { signal });
    input.addEventListener('blur', () => setOpen(false), { signal });

    return Object.freeze({
      clear() { input.value = ''; render(); },
      close() { setOpen(false); },
      destroy() { controller.abort(); },
    });
  }

  window.DesktopSettingsSearch = Object.freeze({ buildIndex, search, highlight, normalize, create });
})();
