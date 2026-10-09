// Optional "control material" for canvas-node buttons (Ambient CSS skin).
// Owns: preference schema/normalisation, projection onto <body> attributes and
// variables, and its Settings → System card. Storage stays in DesktopPreferences;
// the visual rules live in desktop-ambient-controls.css (generated) and
// desktop-control-material.css. No node module, API or workflow state is touched.
(function () {
  const MATERIALS = Object.freeze({
    current: { label: '现有', english: 'Current' },
    matte: { label: '哑光', english: 'Matte' },
    shiny: { label: '微光泽', english: 'Shiny' },
    glass: { label: '磨砂玻璃', english: 'Glass' },
  });
  const SURFACES = Object.freeze({
    concave: { label: '凹面 · 碟形（默认）' },
    flat: { label: '平面' },
    convex: { label: '凸面' },
  });
  // Pinned upstream presets (ambientcss f829df7 apps/demo Material Colour).
  const BODY_PRESETS = Object.freeze({
    default: { label: 'Default · 默认' },
    oxide: { label: 'Oxide · 氧化红', hex: '#7a3b2e' },
    steel: { label: 'Steel · 钢蓝', hex: '#24405c' },
    brass: { label: 'Brass · 黄铜', hex: '#8a6a1f' },
    custom: { label: '自定义' },
  });
  const GLASS_PRESETS = Object.freeze({
    default: { label: 'Default · 默认' },
    violet: { label: 'Violet · 紫罗兰', hue: 280, saturation: 55 },
    amber: { label: 'Amber · 琥珀', hue: 35, saturation: 60 },
    teal: { label: 'Teal · 青绿', hue: 175, saturation: 50 },
    custom: { label: '自定义' },
  });
  const UPSTREAM_ACCENT = '#ff7f50';
  const DEFAULTS = Object.freeze({ material: 'current', surface: 'concave', body: 'default', bodyCustom: '#4f7861', glass: 'default', glassCustom: '#58adc9', accent: null });
  const MANAGED_VARS = ['--amb-albedo', '--amb-light-hue', '--amb-light-saturation', '--amb-highlight-color', '--desk-control-face-ink', '--desk-control-hover-ink'];

  function normalizeHex(value) {
    const hex = String(value ?? '').trim().replace(/^#/, '');
    if (/^[\da-f]{6}$/i.test(hex)) return `#${hex.toLowerCase()}`;
    if (/^[\da-f]{3}$/i.test(hex)) return `#${[...hex].map(c => c + c).join('').toLowerCase()}`;
    return null;
  }
  const pick = (table, value, fallback) => (Object.hasOwn(table, value) ? value : fallback);
  function normalize(value = {}) {
    const source = value && typeof value === 'object' ? value : {};
    return {
      material: pick(MATERIALS, source.material, DEFAULTS.material),
      surface: pick(SURFACES, source.surface, DEFAULTS.surface),
      body: pick(BODY_PRESETS, source.body, DEFAULTS.body),
      bodyCustom: normalizeHex(source.bodyCustom) || DEFAULTS.bodyCustom,
      glass: pick(GLASS_PRESETS, source.glass, DEFAULTS.glass),
      glassCustom: normalizeHex(source.glassCustom) || DEFAULTS.glassCustom,
      accent: normalizeHex(source.accent) === UPSTREAM_ACCENT ? null : normalizeHex(source.accent),
    };
  }

  function luminance(hex) {
    const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  }
  function contrast(a, b) {
    const x = luminance(a), y = luminance(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  function hexToHueSaturation(hex) {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min, lightness = (max + min) / 2;
    let hue = 0;
    if (delta) hue = (max === r ? (g - b) / delta : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4) * 60;
    return { hue: (hue + 360) % 360, saturation: delta ? (delta / (1 - Math.abs(2 * lightness - 1))) * 100 : 0 };
  }
  function hslToHex(hue, saturation, lightness = 50) {
    const s = saturation / 100, l = lightness / 100, chroma = (1 - Math.abs(2 * l - 1)) * s, h = (((hue % 360) + 360) % 360) / 60;
    const x = chroma * (1 - Math.abs((h % 2) - 1)), m = l - chroma / 2;
    const rgb = h < 1 ? [chroma, x, 0] : h < 2 ? [x, chroma, 0] : h < 3 ? [0, chroma, x] : h < 4 ? [0, x, chroma] : h < 5 ? [x, 0, chroma] : [chroma, 0, x];
    return '#' + rgb.map(c => Math.round((c + m) * 255).toString(16).padStart(2, '0')).join('');
  }
  const round = value => String(Number(value.toFixed(3)));

  // Body attributes + inline variables for one preference snapshot. Pure apart from
  // writing to `body`, so tests can pass a stub element.
  function apply(value, body = document.body) {
    const prefs = normalize(value);
    if (!body) return prefs;
    const on = prefs.material !== 'current';
    MANAGED_VARS.forEach(name => body.style?.removeProperty?.(name));
    ['data-control-material', 'data-control-finish', 'data-control-surface', 'data-control-tinted'].forEach(name => body.removeAttribute?.(name));
    if (!on) return prefs;
    body.setAttribute('data-control-material', 'ambient');
    body.setAttribute('data-control-finish', prefs.material);
    body.setAttribute('data-control-surface', prefs.material === 'matte' ? prefs.surface : 'concave');
    const accent = prefs.accent || UPSTREAM_ACCENT;
    if (prefs.accent) body.style.setProperty('--amb-highlight-color', prefs.accent);
    if (prefs.material === 'glass') {
      const preset = GLASS_PRESETS[prefs.glass];
      if (prefs.glass !== 'default') {
        const tint = prefs.glass === 'custom' ? hexToHueSaturation(prefs.glassCustom) : preset;
        body.style.setProperty('--amb-light-hue', round(tint.hue));
        body.style.setProperty('--amb-light-saturation', `${round(tint.saturation)}%`);
      }
    } else if (prefs.body !== 'default') {
      // Same rule as the demo: label ink by contrast; hover ink falls back to it.
      const hex = prefs.body === 'custom' ? prefs.bodyCustom : BODY_PRESETS[prefs.body].hex;
      const ink = contrast(hex, '#ffffff') > contrast(hex, '#171922') ? '#ffffff' : '#171922';
      body.setAttribute('data-control-tinted', '');
      body.style.setProperty('--amb-albedo', hex);
      body.style.setProperty('--desk-control-face-ink', ink);
      body.style.setProperty('--desk-control-hover-ink', contrast(hex, accent) >= 4.5 ? accent : ink);
    }
    return prefs;
  }

  // ---- Settings → System card ------------------------------------------------
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const options = (table, selected, text = item => item.label) => Object.entries(table).map(([key, item]) => `<option value="${key}"${key === selected ? ' selected' : ''}>${esc(text(item))}</option>`).join('');
  function colorOf(prefs) {
    if (prefs.material === 'glass') {
      if (prefs.glass === 'custom') return prefs.glassCustom;
      const { hue, saturation } = prefs.glass === 'default' ? { hue: 234, saturation: 15 } : GLASS_PRESETS[prefs.glass];
      return hslToHex(hue, saturation);
    }
    return prefs.body === 'custom' ? prefs.bodyCustom : BODY_PRESETS[prefs.body].hex || '#eaeaea';
  }
  const paletteOptions = prefs => (prefs.material === 'glass' ? options(GLASS_PRESETS, prefs.glass) : options(BODY_PRESETS, prefs.body));
  function renderSettings(value) {
    const prefs = normalize(value);
    const off = prefs.material === 'current';
    const glass = prefs.material === 'glass';
    const swatch = colorOf(prefs);
    const accent = prefs.accent || UPSTREAM_ACCENT;
    return `<div class="desk-settings-form" data-control-material-settings>
      <label><span>按钮材质</span><select class="desk-select" data-control-material-field="material" aria-label="节点按钮材质">${options(MATERIALS, prefs.material, item => `${item.label} · ${item.english}`)}</select></label>
      <label><span>按键表面</span><select class="desk-select" data-control-material-field="surface" aria-label="按键表面"${prefs.material === 'matte' ? '' : ' disabled'}>${options(SURFACES, prefs.surface)}</select></label>
      <label><span data-control-material-palette-label>${glass ? '玻璃染色' : '键体颜色'}</span><select class="desk-select" data-control-material-field="palette" aria-label="颜色预设"${off ? ' disabled' : ''}>${paletteOptions(prefs)}</select></label>
      <div class="desk-settings-secret-field"><span>自定义颜色</span><div class="desk-settings-progress-color">
        <input type="color" value="${esc(swatch)}" data-control-material-field="color" aria-label="自定义${glass ? '玻璃染色' : '键体颜色'}"${off ? ' disabled' : ''}>
        <input class="desk-input" type="text" value="${esc(swatch.toUpperCase())}" data-control-material-field="hex" aria-label="自定义颜色 HEX" spellcheck="false" maxlength="7"${off ? ' disabled' : ''}>
      </div></div>
      <div class="desk-settings-secret-field"><span>强调色 · 悬停 / 焦点</span><div class="desk-settings-progress-color">
        <input type="color" value="${esc(accent)}" data-control-material-field="accent" aria-label="强调色"${off ? ' disabled' : ''}>
        <input class="desk-input" type="text" value="${esc(accent.toUpperCase())}" data-control-material-field="accent-hex" aria-label="强调色 HEX" spellcheck="false" maxlength="7"${off ? ' disabled' : ''}>
        <button type="button" class="desk-button" data-control-material-accent-reset${off || !prefs.accent ? ' disabled' : ''}>默认</button>
      </div></div>
      <p class="desk-settings-form__hint">只改变画布节点里的按钮外观，即时生效并保存在本浏览器。表面效果只与哑光叠加；磨砂玻璃在节点很多时较耗性能。材质来自 Ambient CSS（MIT）。</p>
    </div>`;
  }

  // Returns the preference patch for a settings event, or null when the event is not
  // ours / not committable yet (invalid HEX keeps the last valid look).
  function patchFromEvent(event, value) {
    const control = event.target?.closest?.('[data-control-material-field], [data-control-material-accent-reset]');
    if (!control) return null;
    const prefs = normalize(value);
    if (control.matches('[data-control-material-accent-reset]')) return event.type === 'click' ? { accent: null } : null;
    const field = control.dataset.controlMaterialField;
    if (field === 'material' || field === 'surface') return event.type === 'change' ? { [field]: control.value } : null;
    if (field === 'palette') return event.type === 'change' ? { [prefs.material === 'glass' ? 'glass' : 'body']: control.value } : null;
    const typed = field === 'hex' || field === 'accent-hex';
    // While typing, only a complete 6-digit HEX commits; #RGB is accepted on change.
    if (typed && event.type === 'input' && !/^#?[\da-f]{6}$/i.test(control.value.trim())) {
      control.removeAttribute('aria-invalid');
      return null;
    }
    const hex = normalizeHex(control.value);
    control.setAttribute('aria-invalid', String(!hex));
    if (!hex) return null;
    if (field === 'accent' || field === 'accent-hex') return { accent: hex };
    return prefs.material === 'glass' ? { glass: 'custom', glassCustom: hex } : { body: 'custom', bodyCustom: hex };
  }

  // Refresh an existing card in place (keeps focus/scroll and other System cards' drafts).
  function syncSettings(card, value) {
    if (!card) return;
    const prefs = normalize(value);
    const off = prefs.material === 'current';
    const glass = prefs.material === 'glass';
    const swatch = colorOf(prefs);
    const accent = prefs.accent || UPSTREAM_ACCENT;
    const field = name => card.querySelector(`[data-control-material-field="${name}"]`);
    const label = card.querySelector('[data-control-material-palette-label]');
    if (label) label.textContent = glass ? '玻璃染色' : '键体颜色';
    const set = (name, val, disabled) => {
      const el = field(name);
      if (!el) return;
      if (document.activeElement !== el || el.type === 'color' || el.tagName === 'SELECT') el.value = val;
      el.disabled = disabled;
      el.removeAttribute('aria-invalid');
    };
    const palette = field('palette');
    if (palette) palette.innerHTML = paletteOptions(prefs);
    set('material', prefs.material, false);
    set('surface', prefs.surface, prefs.material !== 'matte');
    set('palette', glass ? prefs.glass : prefs.body, off);
    set('color', swatch, off);
    set('hex', swatch.toUpperCase(), off);
    set('accent', accent, off);
    set('accent-hex', accent.toUpperCase(), off);
    const reset = card.querySelector('[data-control-material-accent-reset]');
    if (reset) reset.disabled = off || !prefs.accent;
    ['material', 'surface', 'palette'].forEach(name => { const el = field(name); if (el) window.DesktopSelect?.refresh?.(el); });
  }

  window.DesktopControlMaterial = Object.freeze({
    MATERIALS, SURFACES, BODY_PRESETS, GLASS_PRESETS, UPSTREAM_ACCENT, DEFAULTS,
    normalize, normalizeHex, apply, renderSettings, syncSettings, patchFromEvent,
  });
})();
