// Comfy node layout: the workflow card list keeps a constant 1.5-card height while the node is
// resized, so only the workflow-input panel absorbs height changes. Card height follows the
// auto-filled column width (4:3 thumbnails), so the list is measured whenever its width changes
// and the result is written to --desk-comfy-workflow-list-height. Owns no state beyond observers.
(function () {
  const LIST_SELECTOR = '[data-comfy-workflow-list]';
  const CARD_SELECTOR = '.desk-comfy-workflow-card';
  const HEIGHT_PROPERTY = '--desk-comfy-workflow-list-height';
  const VISIBLE_CARDS = 1.5;

  // One full card, the row gap, half of the next row and the list's own padding.
  function listHeight(cardHeight, rowGap, padding) {
    return Math.round(cardHeight * VISIBLE_CARDS + rowGap + padding);
  }

  function create({root = () => document} = {}) {
    let widths = new WeakMap();
    const observed = new Set();
    let observer = null;

    function sync(list) {
      if (!list?.isConnected) return;
      const card = list.querySelector(CARD_SELECTOR);
      if (!card) {
        list.style.removeProperty(HEIGHT_PROPERTY);
        return;
      }
      const style = getComputedStyle(list);
      const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      list.style.setProperty(HEIGHT_PROPERTY, `${listHeight(card.offsetHeight, parseFloat(style.rowGap) || 0, padding)}px`);
    }

    // Writing the height resizes the list again; only a width change re-measures.
    function onResize(entries) {
      entries.forEach(entry => {
        const width = Math.round(entry.contentRect.width);
        if (widths.get(entry.target) === width) return;
        widths.set(entry.target, width);
        sync(entry.target);
      });
    }

    function reconcile() {
      if (typeof ResizeObserver !== 'function') return;
      observer ||= new ResizeObserver(onResize);
      observed.forEach(list => {
        if (list.isConnected) return;
        observer.unobserve(list);
        observed.delete(list);
      });
      root().querySelectorAll(LIST_SELECTOR).forEach(list => {
        if (observed.has(list)) return;
        observed.add(list);
        observer.observe(list);
      });
    }

    function disposeAll() {
      observer?.disconnect();
      observed.clear();
      widths = new WeakMap();
    }

    return Object.freeze({sync, reconcile, disposeAll});
  }

  window.DesktopCanvasComfyLayout = Object.freeze({create, listHeight, VISIBLE_CARDS});
})();
