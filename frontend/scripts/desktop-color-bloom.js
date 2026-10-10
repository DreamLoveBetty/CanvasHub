// Petal colour picker ("花朵取色器"): a swatch trigger + HEX field that opens a flower of
// preset petals with an arched lightness slider. Shared by the prompt library's colour
// schemes and the settings centre. Owns only its own markup, open/close state, petal and
// lightness interaction; the host owns the value's meaning and persistence.
//
// Host contract: the committed value lives in a hidden <input data-color-bloom-value> that
// carries the host's own attributes (name / data-* field). Picking a petal or moving the
// lightness slider writes that input and dispatches bubbling `input` (live) and `change`
// (commit) events on it, so hosts keep their existing form handlers. Typing in the HEX
// field is left to the host (it validates/commits); the picker only previews complete
// values. After a host changes the value or disabled state, it calls refresh(root).
(function () {
  const PETALS = [
    ...['#F7C13F', '#F2A23C', '#EE8440', '#E96544', '#E84C3F', '#E03E66', '#D23C92', '#A24FC8', '#7B5FD4', '#4E72D6', '#3DA1B8', '#5FB95B']
      .map((color, index) => ({ key: `outer-${index}`, ring: 'outer', color })),
    ...['#F6E6A4', '#F4D0B0', '#F1C1C4', '#E3C4DE', '#CCC9EC', '#C6E0C9']
      .map((color, index) => ({ key: `inner-${index}`, ring: 'inner', color })),
    { key: 'center', ring: 'center', color: '#FFFFFF' },
  ];
  const LIGHTNESS_MIN = 4;
  const LIGHTNESS_MAX = 96;
  let instances = 0;

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value) || 0));
  const normalizeHue = value => ((Number(value) % 360) + 360) % 360;
  // '#RRGGBB' (upper case) for a complete 6-digit value, otherwise ''.
  function normalize(value) {
    const text = String(value ?? '').trim();
    const hex = text.startsWith('#') ? text : `#${text}`;
    return /^#[0-9a-f]{6}$/i.test(hex) ? hex.toUpperCase() : '';
  }
  const safeColor = value => normalize(value) || '#000000';

  function hexToHsl(value) {
    const hex = safeColor(value).slice(1);
    const [r, g, b] = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16) / 255);
    const max = Math.max(r, g, b); const min = Math.min(r, g, b); const delta = max - min;
    let h = 0;
    if (delta) {
      if (max === r) h = 60 * (((g - b) / delta) % 6);
      else if (max === g) h = 60 * ((b - r) / delta + 2);
      else h = 60 * ((r - g) / delta + 4);
    }
    const l = (max + min) / 2;
    const s = delta ? delta / (1 - Math.abs(2 * l - 1)) : 0;
    return { h: normalizeHue(h), s: s * 100, l: l * 100 };
  }
  function hslToHex(h, s, l) {
    const hue = normalizeHue(h); const saturation = clamp(s, 0, 100) / 100; const lightness = clamp(l, 0, 100) / 100;
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const x = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
    const m = lightness - chroma / 2;
    const channels = hue < 60 ? [chroma, x, 0] : hue < 120 ? [x, chroma, 0] : hue < 180 ? [0, chroma, x] : hue < 240 ? [0, x, chroma] : hue < 300 ? [x, 0, chroma] : [chroma, 0, x];
    return `#${channels.map(channel => Math.round((channel + m) * 255).toString(16).padStart(2, '0')).join('')}`.toUpperCase();
  }
  function hueDistance(first, second) {
    const delta = Math.abs(normalizeHue(first) - normalizeHue(second));
    return Math.min(delta, 360 - delta);
  }
  function selectedPetalKey(color) {
    const current = hexToHsl(color);
    if (current.s < 8) return 'center';
    return PETALS.filter(petal => petal.ring !== 'center').reduce((best, petal) => {
      const candidate = hexToHsl(petal.color);
      const score = hueDistance(current.h, candidate.h) + Math.abs(current.s - candidate.s) * .55;
      return !best || score < best.score ? { key: petal.key, score } : best;
    }, null)?.key || 'center';
  }
  // Marker position on the arched track (SVG viewBox 0 0 64 148, arc r=118 from y=12 to 136).
  function lightnessPoint(lightness) {
    const t = clamp((100 - lightness) / 100, 0, 1);
    const radius = 118;
    const halfChord = 62;
    const centerY = 74;
    const centerX = 12 - Math.sqrt(radius ** 2 - halfChord ** 2);
    const y = 12 + halfChord * 2 * t;
    return { x: centerX + Math.sqrt(Math.max(0, radius ** 2 - (y - centerY) ** 2)), y };
  }

  // options: value, label (what the colour is for), hexAttrs / valueAttrs (host attributes
  // for the HEX field and the hidden value input), hexClass, disabled, after (extra
  // control-row markup such as a reset button), hint.
  function html({ value, label = '颜色', hexAttrs = '', valueAttrs = '', hexClass = '', disabled = false, after = '', hint = '点选花瓣 · 拖动调明暗' } = {}) {
    const color = safeColor(value);
    const hsl = hexToHsl(color);
    const tone = hslToHex(hsl.h, hsl.s, 50);
    const marker = lightnessPoint(hsl.l);
    const selectedKey = selectedPetalKey(color);
    const id = `deskColorBloom${++instances}`;
    const name = escapeHtml(label);
    const petals = PETALS.map((petal, index) => {
      const ringItems = PETALS.filter(item => item.ring === petal.ring);
      const ringIndex = ringItems.findIndex(item => item.key === petal.key);
      const angle = petal.ring === 'center' ? 0 : -Math.PI / 2 + (ringIndex / ringItems.length) * Math.PI * 2;
      const radius = petal.ring === 'outer' ? 68 : petal.ring === 'inner' ? 36 : 0;
      const x = Math.cos(angle) * radius;
      const y = Math.sin(angle) * radius;
      const layer = petal.ring === 'outer' ? 2 + ringIndex : petal.ring === 'inner' ? 20 + ringIndex : 30;
      return `<button type="button" class="desk-color-bloom__petal is-${petal.ring}" data-color-bloom-petal="${petal.color}" data-bloom-petal-key="${petal.key}" aria-label="选择颜色 ${petal.color}" aria-pressed="${selectedKey === petal.key}" tabindex="-1" style="--bloom-petal:${petal.color};--bloom-offset-x:${x.toFixed(3)}px;--bloom-offset-y:${y.toFixed(3)}px;--bloom-size:45px;--bloom-order:${index};--bloom-layer:${layer}"><span class="desk-color-bloom__petal-disc" aria-hidden="true"></span></button>`;
    }).join('');
    const off = disabled ? ' disabled' : '';
    return `<div class="desk-color-bloom" data-color-bloom style="--desk-color-bloom-color:${color};--desk-color-bloom-tone:${tone};--bloom-marker-x:${marker.x.toFixed(2)}px;--bloom-marker-y:${marker.y.toFixed(2)}px">
      <div class="desk-color-bloom__control"><button type="button" class="desk-color-bloom__trigger" data-color-bloom-trigger aria-label="打开花朵取色器：${name}，当前 ${color}" aria-expanded="false" aria-controls="${id}"${off}><span aria-hidden="true"></span></button><input class="desk-color-bloom__hex${hexClass ? ` ${escapeHtml(hexClass)}` : ''}" value="${color}" maxlength="7" spellcheck="false" autocomplete="off"${hexAttrs ? ` ${hexAttrs}` : ''}${off}>${after}</div>
      <input type="hidden" data-color-bloom-value value="${color}"${valueAttrs ? ` ${valueAttrs}` : ''}${off}>
      <div class="desk-color-bloom__popover" id="${id}" role="dialog" aria-label="花朵取色器：${name}" aria-hidden="true">
        <div class="desk-color-bloom__stage"><div class="desk-color-bloom__flower"><span class="desk-color-bloom__field" aria-hidden="true"></span>${petals}</div><div class="desk-color-bloom__lightness" data-color-bloom-lightness role="slider" aria-label="${name}明度" aria-valuemin="${LIGHTNESS_MIN}" aria-valuemax="${LIGHTNESS_MAX}" aria-valuenow="${Math.round(hsl.l)}" aria-valuetext="明度 ${Math.round(hsl.l)}%" tabindex="-1"><svg viewBox="0 0 64 148" aria-hidden="true"><defs><linearGradient id="${id}Lightness" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF"></stop><stop offset=".38" style="stop-color:var(--desk-color-bloom-tone)"></stop><stop offset=".62" style="stop-color:var(--desk-color-bloom-tone)"></stop><stop offset="1" stop-color="#050505"></stop></linearGradient></defs><path class="desk-color-bloom__lightness-shadow" d="M12 12 A118 118 0 0 1 12 136"></path><path class="desk-color-bloom__lightness-track" d="M12 12 A118 118 0 0 1 12 136" stroke="url(#${id}Lightness)"></path></svg><span class="desk-color-bloom__lightness-marker" aria-hidden="true"><i></i></span></div></div>
        <div class="desk-color-bloom__footer"><span class="desk-color-bloom__current" aria-hidden="true"></span><strong data-color-bloom-label>${color}</strong><small>${escapeHtml(hint)}</small></div>
      </div>
    </div>`;
  }

  const blooms = root => !root ? [] : [...(root.matches?.('[data-color-bloom]') ? [root] : []), ...root.querySelectorAll('[data-color-bloom]')];
  const valueInput = bloom => bloom.querySelector('[data-color-bloom-value]');

  // Visuals only (swatches, petal selection, slider) — never touches the stored value.
  function paint(bloom, value) {
    const color = safeColor(value);
    const hsl = hexToHsl(color);
    const marker = lightnessPoint(hsl.l);
    bloom.style.setProperty('--desk-color-bloom-color', color);
    bloom.style.setProperty('--desk-color-bloom-tone', hslToHex(hsl.h, hsl.s, 50));
    bloom.style.setProperty('--bloom-marker-x', `${marker.x.toFixed(2)}px`);
    bloom.style.setProperty('--bloom-marker-y', `${marker.y.toFixed(2)}px`);
    const label = bloom.querySelector('[data-color-bloom-label]');
    if (label) label.textContent = color;
    const trigger = bloom.querySelector('[data-color-bloom-trigger]');
    trigger?.setAttribute('aria-label', (trigger.getAttribute('aria-label') || '').replace(/当前 #[0-9A-F]{6}$/i, `当前 ${color}`));
    const slider = bloom.querySelector('[data-color-bloom-lightness]');
    slider?.setAttribute('aria-valuenow', String(Math.round(hsl.l)));
    slider?.setAttribute('aria-valuetext', `明度 ${Math.round(hsl.l)}%`);
    const selectedKey = selectedPetalKey(color);
    bloom.querySelectorAll('[data-bloom-petal-key]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.bloomPetalKey === selectedKey)));
  }

  // Visible area the popover can use: the viewport cut by every clipping ancestor.
  function clipRect(el) {
    const rect = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
      const box = node.getBoundingClientRect();
      rect.left = Math.max(rect.left, box.left); rect.top = Math.max(rect.top, box.top);
      rect.right = Math.min(rect.right, box.right); rect.bottom = Math.min(rect.bottom, box.bottom);
    }
    return rect;
  }
  // Default placement is below, left-aligned; flip only when that would be clipped.
  function place(bloom) {
    bloom.classList.remove('is-align-end', 'is-above');
    const popover = bloom.querySelector('.desk-color-bloom__popover');
    if (!popover) return;
    const area = clipRect(bloom), host = bloom.getBoundingClientRect(), box = popover.getBoundingClientRect();
    if (box.right > area.right && host.right - box.width >= area.left) bloom.classList.add('is-align-end');
    if (box.bottom > area.bottom && host.top - box.height - 7 >= area.top) bloom.classList.add('is-above');
  }

  function setOpen(bloom, open, { focus = false } = {}) {
    const trigger = bloom.querySelector('[data-color-bloom-trigger]');
    if (open && trigger?.disabled) return;
    if (open) place(bloom);
    bloom.classList.toggle('is-open', open);
    trigger?.setAttribute('aria-expanded', String(open));
    bloom.querySelector('.desk-color-bloom__popover')?.setAttribute('aria-hidden', String(!open));
    bloom.querySelectorAll('[data-color-bloom-petal], [data-color-bloom-lightness]').forEach(el => { el.tabIndex = open ? 0 : -1; });
    if (!focus) return;
    // The popover's visibility transitions from hidden, so the petal may not take focus on
    // the first frame; retry briefly.
    const target = open ? bloom.querySelector('[data-color-bloom-petal][aria-pressed="true"]') : trigger;
    let tries = 0;
    const attempt = () => {
      if (!target || bloom.classList.contains('is-open') !== open) return;
      target.focus?.({ preventScroll: true });
      if (document.activeElement !== target && ++tries < 10) requestAnimationFrame(attempt);
    };
    requestAnimationFrame(attempt);
  }

  // Host-side value or disabled changes → visuals, HEX field and trigger follow the hidden input.
  function refresh(root) {
    for (const bloom of blooms(root)) {
      const input = valueInput(bloom);
      if (!input) continue;
      const color = safeColor(input.value);
      const hex = bloom.querySelector('.desk-color-bloom__hex');
      if (hex && document.activeElement !== hex) hex.value = color;
      const trigger = bloom.querySelector('[data-color-bloom-trigger]');
      if (trigger) trigger.disabled = input.disabled;
      if (input.disabled) setOpen(bloom, false);
      paint(bloom, color);
    }
  }

  // Programmatic value change. emit: false (silent) | true (input + change events).
  function setValue(bloom, value, { emit = false } = {}) {
    const color = normalize(value);
    const input = bloom && valueInput(bloom);
    if (!color || !input) return false;
    input.value = color;
    const hex = bloom.querySelector('.desk-color-bloom__hex');
    if (hex) { hex.value = color; hex.removeAttribute('aria-invalid'); }
    paint(bloom, color);
    if (emit) {
      input.dispatchEvent(new Event('input', { bubbles: true }));
      if (emit !== 'input') input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return true;
  }

  // Closes every open picker inside root; true when one was open (hosts use it for Escape).
  function close(root = document, options = {}) {
    let closed = false;
    blooms(root).forEach(bloom => { if (bloom.classList.contains('is-open')) { setOpen(bloom, false, options); closed = true; } });
    return closed;
  }

  function setLightness(bloom, lightness, emit) {
    const current = hexToHsl(valueInput(bloom)?.value);
    setValue(bloom, hslToHex(current.h, current.s, clamp(lightness, LIGHTNESS_MIN, LIGHTNESS_MAX)), { emit });
  }
  function lightnessFromPointer(slider, clientY) {
    const bounds = slider.getBoundingClientRect();
    if (!bounds.height) return null;
    const trackStart = bounds.top + bounds.height * (12 / 148);
    const trackEnd = bounds.top + bounds.height * (136 / 148);
    return 100 - clamp((clientY - trackStart) / Math.max(1, trackEnd - trackStart), 0, 1) * 100;
  }
  function beginLightnessDrag(event, slider, bloom) {
    if (event.button > 0) return;
    event.preventDefault();
    slider.focus?.({ preventScroll: true });
    slider.classList.add('is-dragging');
    let moved = false;
    const apply = clientY => { const value = lightnessFromPointer(slider, clientY); if (value !== null) { moved = true; setLightness(bloom, value, 'input'); } };
    apply(event.clientY);
    const move = pointerEvent => apply(pointerEvent.clientY);
    const end = () => {
      slider.classList.remove('is-dragging');
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      if (moved) valueInput(bloom)?.dispatchEvent(new Event('change', { bubbles: true }));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
  }

  // One delegated listener set for every picker on the page; hosts wire nothing.
  document.addEventListener('click', event => {
    const bloom = event.target.closest?.('[data-color-bloom]');
    blooms(document).forEach(other => { if (other !== bloom && other.classList.contains('is-open')) setOpen(other, false); });
    if (!bloom) return;
    if (event.target.closest('[data-color-bloom-trigger]')) {
      setOpen(bloom, !bloom.classList.contains('is-open'), { focus: true });
      return;
    }
    const petal = event.target.closest('[data-color-bloom-petal]');
    if (petal) setValue(bloom, petal.dataset.colorBloomPetal, { emit: true });
  });
  document.addEventListener('pointerdown', event => {
    const slider = event.target.closest?.('[data-color-bloom-lightness]');
    const bloom = slider?.closest('[data-color-bloom]');
    if (bloom?.classList.contains('is-open')) beginLightnessDrag(event, slider, bloom);
  });
  document.addEventListener('input', event => {
    // Live preview of a complete typed HEX; committing it stays with the host.
    if (!event.target.matches?.('.desk-color-bloom__hex')) return;
    const color = normalize(event.target.value);
    if (color) paint(event.target.closest('[data-color-bloom]'), color);
  });
  document.addEventListener('keydown', event => {
    const bloom = event.target.closest?.('[data-color-bloom]');
    if (!bloom) return;
    if (event.key === 'Escape' && bloom.classList.contains('is-open')) {
      // Close only the picker; the surrounding panel/drawer keeps its own Escape.
      event.preventDefault();
      event.stopPropagation();
      setOpen(bloom, false, { focus: true });
      return;
    }
    const slider = event.target.closest('[data-color-bloom-lightness]');
    if (!slider || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = hexToHsl(valueInput(bloom)?.value).l;
    const step = event.shiftKey ? 5 : 2;
    setLightness(bloom, event.key === 'Home' ? LIGHTNESS_MAX : event.key === 'End' ? LIGHTNESS_MIN : current + (['ArrowUp', 'ArrowRight'].includes(event.key) ? step : -step), true);
  }, true);

  window.DesktopColorBloom = Object.freeze({ PETALS, normalize, hexToHsl, hslToHex, selectedPetalKey, lightnessPoint, html, refresh, setValue, close });
})();
