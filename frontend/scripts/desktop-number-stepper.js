// Number stepper: replaces the browser's spin arrows on the number fields of canvas nodes
// and the settings centre with a − / + pair inside the field. Owns only that wrapper and
// its buttons; the field keeps its own attributes, value and handlers.
//
// Host contract: nothing to call. Number fields rendered inside .desk-node / .desk-settings
// are wrapped as soon as they are inserted (MutationObserver, before paint). A step uses
// the field's own stepUp()/stepDown(), so min / max / step are honoured, and dispatches
// bubbling `input` and `change` like the native arrows do. Holding a button repeats until
// release or until a host re-render detaches it. Fields too narrow for the pair opt out
// with data-stepper="off" (their native arrows are still hidden by the stylesheet).
//
// The buttons come after the field so a wrapping <label> still labels the field, and they
// stay out of the tab order: the keyboard keeps ArrowUp / ArrowDown on the field itself.
(function () {
  'use strict';
  const SELECTOR = ':is(.desk-node, .desk-settings) input[type="number"]:not([data-stepper="off"])';
  const REPEAT_DELAY = 400;
  const REPEAT_INTERVAL = 70;

  const ICON = {
    down: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 8h8"/></svg>',
    up: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 8h8M8 4v8"/></svg>',
  };

  function button(direction) {
    const el = document.createElement('button');
    el.type = 'button';
    el.tabIndex = -1;
    el.className = `desk-stepper__button desk-stepper__button--${direction}`;
    el.dataset.stepper = direction;
    el.setAttribute('aria-label', direction === 'up' ? '增加' : '减少');
    el.innerHTML = ICON[direction];
    return el;
  }

  function enhance(input) {
    if (!input || input.parentElement?.classList.contains('desk-stepper')) return false;
    const focused = document.activeElement === input;
    // A <div>, not a <span>: node stylesheets style `label > span` as the field caption.
    const wrapper = document.createElement('div');
    wrapper.className = 'desk-stepper';
    input.before(wrapper);
    wrapper.append(input, button('down'), button('up'));
    if (focused) input.focus({ preventScroll: true });
    return true;
  }

  function enhanceIn(root = document) {
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    if (root.matches?.(SELECTOR)) enhance(root);
    root.querySelectorAll?.(SELECTOR).forEach(enhance);
  }

  // Returns true when the value changed; events follow the native arrow order.
  function step(input, direction) {
    if (!input || input.disabled || input.readOnly) return false;
    const before = input.value;
    try {
      if (direction === 'up') input.stepUp(); else input.stepDown();
    } catch {
      // step="any" has no step base; move by one within min / max.
      const value = Number(input.value) || 0;
      const next = value + (direction === 'up' ? 1 : -1);
      const min = input.min === '' ? -Infinity : Number(input.min);
      const max = input.max === '' ? Infinity : Number(input.max);
      input.value = String(Math.min(max, Math.max(min, next)));
    }
    if (input.value === before) return false;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  let hold = null;
  function stopHold() {
    if (!hold) return;
    clearTimeout(hold.timer);
    hold = null;
  }

  function onPointerDown(event) {
    const control = event.target.closest?.('.desk-stepper__button');
    if (!control || event.button !== 0) return;
    const input = control.parentElement?.querySelector('input');
    // Keep focus where it is (usually the field) and stop the canvas from treating this
    // as the start of a pan or node drag.
    event.preventDefault();
    stopHold();
    if (!step(input, control.dataset.stepper)) return;
    const repeat = () => {
      if (!hold || !control.isConnected || !step(input, control.dataset.stepper)) return stopHold();
      hold.timer = setTimeout(repeat, REPEAT_INTERVAL);
    };
    hold = { timer: setTimeout(repeat, REPEAT_DELAY) };
  }

  function init() {
    if (!document.body?.classList.contains('desk-app')) return;
    enhanceIn(document);
    new MutationObserver(mutations => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach(node => {
          if (node.nodeType === Node.ELEMENT_NODE && !node.classList.contains('desk-stepper')) enhanceIn(node);
        });
      }
    }).observe(document.body, { childList: true, subtree: true });
    // Capture: node bodies may stop pointerdown from bubbling to the document.
    document.addEventListener('pointerdown', onPointerDown, true);
    for (const type of ['pointerup', 'pointercancel', 'blur']) window.addEventListener(type, stopHold);
    // Pointer steps already happened on pointerdown; a click without a pointer press
    // (assistive technology, detail 0) steps once.
    document.addEventListener('click', event => {
      const control = event.target.closest?.('.desk-stepper__button');
      if (!control) return;
      event.preventDefault();
      if (event.detail === 0) step(control.parentElement?.querySelector('input'), control.dataset.stepper);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();

  window.DesktopNumberStepper = Object.freeze({ SELECTOR, enhance, enhanceIn, step });
})();
