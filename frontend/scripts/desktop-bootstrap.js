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

  // Each startup step runs on its own: one module throwing (say, on a saved canvas node it
  // cannot render) must not leave history, settings and the rest uninitialised, and the
  // error has to reach the console instead of disappearing into a promise.
  async function initStep(name, run) {
    try {
      await run();
    } catch (error) {
      console.error(`[desktop] ${name} failed during startup`, error);
    }
  }

  function initDesktopApp() {
    if (desktopInitPromise) return desktopInitPromise;
    desktopInitPromise = (async () => {
      await initStep('DesktopState.loadSettings', () => DesktopState.loadSettings());
      await initStep('DesktopState.restoreCanvasBackup', () => DesktopState.restoreCanvasBackup?.());
      await initStep('DesktopState.loadDraft', () => DesktopState.loadDraft());
      await initStep('DesktopState.loadLastTask', () => DesktopState.loadLastTask());

      await initStep('DesktopResults.init', () => DesktopResults.init());
      await initStep('DesktopCanvas.init', () => DesktopCanvas.init());
      await initStep('DesktopHistory.init', () => DesktopHistory.init());
      await initStep('DesktopSettings.init', () => window.DesktopSettings?.init?.());
      await initStep('DesktopPromptDrawer.init', () => window.DesktopPromptDrawer?.init?.());
      await initStep('DesktopPromptAgent.init', () => window.DesktopPromptAgent?.init?.());
      await initStep('DesktopPromptLibrary.init', () => window.DesktopPromptLibrary?.init?.());
      await initStep('DesktopPromptInsert.init', () => window.DesktopPromptInsert?.init?.());
      await initStep('DesktopI18n.apply', () => window.DesktopI18n?.apply?.());
      await initStep('DesktopSelect.init', () => window.DesktopSelect?.init?.());
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
