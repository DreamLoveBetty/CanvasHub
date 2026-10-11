// Settings preview of the node progress bar: one sample task drawn by its own DesktopProgress
// presenter — the same renderer and materials the canvas uses — so it follows the saved
// style, track height and fill colour exactly. Owns only the sample markup and that
// presenter; the settings host mounts it after rendering, refreshes it when the progress
// preferences change and releases it when the card goes away or the drawer closes.
(function () {
  'use strict';
  const PERCENT = 62;
  const SAMPLE = Object.freeze({
    visible: true, running: true, taskId: 'settings-progress-preview', percent: PERCENT,
    title: '示例任务', detail: '样式预览', elapsedText: '00:42',
  });

  // Classic style reads the legacy capsule markup; canvas styles replace it with their track.
  function html() {
    return `<div class="desk-progress-preview" aria-label="进度条样式预览">
      <div class="desk-progress-float is-visible" data-progress-preview-root role="status" style="--progress-percent:${PERCENT}%">
        <div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar style="width:${PERCENT}%"></span><strong class="desk-progress-float__percent">${PERCENT}%</strong></div><span class="desk-progress-float__stage">${SAMPLE.title} · ${SAMPLE.detail}</span></div>
      </div>
    </div>`;
  }

  function create({ getPreferences, Presenter = window.DesktopProgress } = {}) {
    let presenter = null, root = null;

    function release() {
      presenter?.destroy();
      presenter = null;
      root = null;
    }
    function mount(container) {
      const next = container?.querySelector?.('[data-progress-preview-root]') || null;
      if (next === root) return;
      release();
      if (!next || !Presenter) return;
      root = next;
      presenter = Presenter.create({ getPreferences, getViewport: () => null });
      presenter.update(root, SAMPLE);
    }
    function refresh() {
      presenter?.refreshPreferences();
    }
    return Object.freeze({ mount, refresh, release });
  }

  window.DesktopProgressPreview = Object.freeze({ PERCENT, html, create });
})();
