// Unsaved settings edits. The settings body is re-rendered from the last diagnostics on tab
// switches, model refreshes, connection tests and OAuth status updates; without this, any field
// typed but not yet saved snapped back to the server value. Owns only the draft values: the
// settings host tracks input, restores after each render and forgets a card once it is saved.
// Load before desktop-settings.js; no I/O.
(function () {
  'use strict';
  // Fields that are persisted by a save button. Live preferences (progress, control material)
  // apply instantly and OAuth paste boxes are consumed by their own flows, so neither is drafted.
  const KEY_ATTRIBUTES = ['data-system-setting-field', 'data-gpt-provider-field'];
  const FIELD_SELECTOR = KEY_ATTRIBUTES.map(name => `[${name}]`).join(', ');

  function fieldKey(field) {
    const name = KEY_ATTRIBUTES.find(attribute => field.hasAttribute(attribute));
    return name ? `${name}=${field.getAttribute(name)}` : '';
  }

  const draftable = field => field && field.type !== 'hidden' && field.type !== 'file' && fieldKey(field);
  const readValue = field => (field.type === 'checkbox' ? field.checked : field.value);

  function create({ refreshSelect = select => window.DesktopSelect?.refresh?.(select) } = {}) {
    const drafts = new Map();

    function track(event) {
      const field = event.target?.closest?.(FIELD_SELECTOR);
      if (draftable(field)) drafts.set(fieldKey(field), readValue(field));
    }

    // A draft equal to the freshly rendered value is in sync and dropped; passwords never come
    // back from the server, so theirs stay until the card is saved.
    function restore(root) {
      if (!drafts.size || !root) return;
      root.querySelectorAll(FIELD_SELECTOR).forEach(field => {
        if (!draftable(field)) return;
        const key = fieldKey(field);
        if (!drafts.has(key)) return;
        const value = drafts.get(key);
        if (readValue(field) === value) {
          if (field.type !== 'password') drafts.delete(key);
          return;
        }
        if (field.type === 'checkbox') field.checked = Boolean(value);
        else field.value = value;
        if (field.tagName === 'SELECT') refreshSelect(field);
      });
    }

    function forget(root, selector = FIELD_SELECTOR) {
      root?.querySelectorAll(selector).forEach(field => drafts.delete(fieldKey(field)));
    }

    return Object.freeze({ track, restore, forget, get size() { return drafts.size; } });
  }

  window.DesktopSettingsDrafts = Object.freeze({ create, FIELD_SELECTOR });
})();
