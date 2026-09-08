(function () {
  let authenticatedDataStarted = false;
  let desktopInitPromise = null;

  function afterAuthReady(callback) {
    if (typeof waitForMiniappAuthReady === 'function') {
      waitForMiniappAuthReady(9000).then(ok => {
        if (ok) callback();
      });
      return;
    }
    callback();
  }

  function loadAuthenticatedDesktopData() {
    if (authenticatedDataStarted) return;
    if (!window.DesktopCanvas) {
      initDesktopApp().then(loadAuthenticatedDesktopData).catch(() => {});
      return;
    }
    authenticatedDataStarted = true;

    DesktopApi.getGptConfig()
      .then(config => {
        DesktopState.applyGptRuntimeConfig(config);
        DesktopCanvas.syncFormFromState();
      })
      .catch(() => {});
    DesktopApi.getGptModels?.()
      .then(catalog => DesktopCanvas.applyGptModelCatalog?.(catalog))
      .catch(() => {});
    DesktopHistory.loadHistory().catch(() => {});
    DesktopResults.restoreLastTask().catch(() => {});
  }

  function bindGlobalKeys() {
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        DesktopResults.stopPolling();
      }
    });
  }

  function initDesktopApp() {
    if (desktopInitPromise) return desktopInitPromise;
    desktopInitPromise = (async () => {
      DesktopState.loadSettings();
      await DesktopState.restoreCanvasBackup?.();
      DesktopState.loadDraft();
      DesktopState.loadLastTask();

      DesktopResults.init();
      DesktopCanvas.init();
      DesktopHistory.init();
      window.DesktopSettings?.init?.();
      window.DesktopPromptDrawer?.init?.();
      window.DesktopPromptAgent?.init?.();
      window.DesktopPromptLibrary?.init?.();
      window.DesktopPromptInsert?.init?.();
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

      afterAuthReady(loadAuthenticatedDesktopData);
    })();
    return desktopInitPromise;
  }

  window.addEventListener('miniapp:auth-state-change', event => {
    if (event.detail?.state !== 'authenticated') {
      authenticatedDataStarted = false;
      return;
    }
    initDesktopApp().then(loadAuthenticatedDesktopData).catch(() => {});
  });

  window.addEventListener('pagehide', () => {
    try { DesktopState.saveSettings({ flushCanvasBackup: true }); } catch (e) {}
  });

  window.addEventListener('desktop:language-change', () => {
    try {
      DesktopCanvas.syncFormFromState?.();
      DesktopResults.renderIdleProviderHint?.();
      window.DesktopSettings?.render?.();
      window.DesktopPromptDrawer?.render?.();
      window.DesktopPromptAgent?.render?.();
      window.DesktopPromptLibrary?.render?.();
    } catch (e) {}
    window.DesktopI18n?.apply?.();
    window.DesktopSelect?.refreshAll?.();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { initDesktopApp().catch(() => {}); }, { once: true });
  } else {
    initDesktopApp().catch(() => {});
  }
})();
