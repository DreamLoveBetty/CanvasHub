(function () {
  function afterAuthReady(callback) {
    if (typeof waitForMiniappAuthReady === 'function') {
      waitForMiniappAuthReady(9000).then(ok => {
        if (ok) callback();
      });
      return;
    }
    callback();
  }

  function bindGlobalKeys() {
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        DesktopResults.stopPolling();
      }
    });
  }

  function initDesktopApp() {
    DesktopState.loadSettings();
    DesktopState.loadDraft();
    DesktopState.loadLastTask();

    DesktopResults.init();
    DesktopCanvas.init();
    DesktopHistory.init();
    window.DesktopSettings?.init?.();
    window.DesktopPromptDrawer?.init?.();
    window.DesktopI18n?.apply?.();
    window.DesktopSelect?.init?.();
    bindGlobalKeys();

    window.loadHistory = function () {
      return DesktopHistory.loadHistory()
        .then(items => {
          DesktopResults.restoreLastTask().catch(() => {});
          return items;
        });
    };

    afterAuthReady(() => {
      DesktopApi.getGptConfig()
        .then(config => {
          DesktopState.applyGptRuntimeConfig(config);
          DesktopCanvas.syncFormFromState();
        })
        .catch(() => {});
      DesktopHistory.loadHistory().catch(() => {});
      DesktopResults.restoreLastTask().catch(() => {});
    });
  }

  window.addEventListener('desktop:language-change', () => {
    try {
      DesktopCanvas.syncFormFromState?.();
      DesktopResults.renderIdleProviderHint?.();
      window.DesktopSettings?.render?.();
      window.DesktopPromptDrawer?.render?.();
    } catch (e) {}
    window.DesktopI18n?.apply?.();
    window.DesktopSelect?.refreshAll?.();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDesktopApp, { once: true });
  } else {
    initDesktopApp();
  }
})();
