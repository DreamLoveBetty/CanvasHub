// Small, retained SVG layers for reversible state changes. Callers own labels,
// disabled/busy state and all task/media lifecycles; this helper only paints.
(function () {
  function html(icons, initial = 'idle') {
    const keys = Object.keys(icons);
    if (!keys.length || keys.some(key => !/^[a-z][a-z0-9_-]*$/.test(key))) {
      throw new Error('Invalid state icon keys');
    }
    const current = keys.includes(initial) ? initial : keys.includes('idle') ? 'idle' : keys[0];
    // SVG fragments are static, component-owned glyphs, never user content.
    return `<svg class="desk-state-icon" viewBox="0 0 24 24" aria-hidden="true" data-state-icon="${current}">${keys.map(key =>
      `<g class="desk-state-icon__layer${key === current ? ' is-current' : ''}" data-state-icon-layer="${key}"><g class="desk-state-icon__glyph">${icons[key]}</g></g>`
    ).join('')}</svg>`;
  }

  function paint(svg, state) {
    if (!svg) return false;
    if (svg.dataset.stateIcon === state) return false;
    const layers = [...svg.querySelectorAll('[data-state-icon-layer]')];
    const current = layers.find(layer => layer.dataset.stateIconLayer === state)
      || layers.find(layer => layer.dataset.stateIconLayer === 'idle') || layers[0];
    if (!current || svg.dataset.stateIcon === current.dataset.stateIconLayer) return false;
    svg.dataset.stateIcon = current.dataset.stateIconLayer;
    layers.forEach(layer => layer.classList.toggle('is-current', layer === current));
    return true;
  }

  window.DesktopStateIcon = Object.freeze({html, paint});
})();
