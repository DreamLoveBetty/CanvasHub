// Global bindings and app bootstrap
  function handleGlobalResize() {
    updateStyleChipFade();
    updateTabIndicator();
    updateCinematicViewportMetrics();
    closeCinematicMenus();
    if (currentCinematicSection === 'records') {
      syncCinematicLatestRecordFocus();
    }
    if (!isMobileSettingsViewport()) {
      closeSettings();
    }
  }

  function handleGlobalKeydown(event) {
    const authOverlay = document.getElementById('authOverlay');
    const authVisible = authOverlay && authOverlay.style.display !== 'none';
    if (event.key === 'Enter' && authVisible) {
      handleManualAuth();
      return;
    }
    if (event.key === 'Escape') {
      if (typeof isCinematicComfyWorkbenchOpen === 'function' && isCinematicComfyWorkbenchOpen()) {
        closeCinematicComfyWorkbench();
        return;
      }
      if (document.getElementById('cinematicViewerPage')?.classList.contains('is-open')) {
        closeCinematicViewer();
        return;
      }
      if (document.getElementById('cinematicMenu')?.classList.contains('open')) {
        setCinematicQuickMenuOpen(false);
        return;
      }
      if (document.getElementById('mainMenu')?.classList.contains('open')) {
        setMainMenuOpen(false);
        return;
      }
      if (document.getElementById('cinematicStyleEditorOverlay')?.classList.contains('is-open')) {
        closeCinematicStyleEditor();
        return;
      }
      if (currentCinematicMenu) {
        closeCinematicMenus();
        return;
      }
      closeSettings();
    }
  }

  function handleGlobalClick(event) {
    if (event.target.closest('.cinematic-menu-wrap')) return;
    closeCinematicMenus();
  }

  function bindGlobalUiEvents() {
    const genStyleScroller = document.getElementById('genStyleChips');
    if (genStyleScroller) {
      genStyleScroller.addEventListener('scroll', updateStyleChipFade, { passive: true });
    }
    window.addEventListener('resize', handleGlobalResize);
    document.addEventListener('keydown', handleGlobalKeydown);
    document.addEventListener('click', handleGlobalClick);
  }

  function assertMiniappScriptContracts() {
    const required = [
      ['switchCinematicSection', 'scripts/cinematic-composer.js'],
      ['syncCinematicComposerUi', 'scripts/cinematic-composer.js'],
      ['syncCinematicReferenceState', 'scripts/cinematic-composer.js'],
      ['applyLayoutMode', 'scripts/preferences.js'],
      ['applyPersistedSettings', 'scripts/preferences.js'],
      ['renderCinematicStyleVault', 'scripts/cinematic-style-vault.js'],
      ['renderCinematicHistoryStream', 'scripts/cinematic-history-stream.js'],
      ['openDetailModal', 'scripts/modal-view.js'],
      ['openCinematicViewer', 'scripts/cinematic-detail.js'],
      ['closeCinematicViewer', 'scripts/cinematic-detail.js']
    ];
    const missing = required.filter(([name]) => typeof (typeof window !== 'undefined' ? window[name] : undefined) !== 'function');
    if (!missing.length) return;
    const detail = missing.map(([name, src]) => name + ' from ' + src).join(', ');
    throw new ReferenceError('Missing Mini App startup dependency: ' + detail);
  }

  function initAppUi() {
    assertMiniappScriptContracts();
    loadUiSettings();
    applySkin(currentSkin, false);
    applyCinematicColorScheme(currentCinematicColorScheme, false);
    renderGrid();
    initPromptHelpers();
    initRatioButtons();
    applyPersistedSettings();
    restorePersistedStages();
    syncFloatingSubmitBar();
    updateCinematicViewportMetrics();
  }

  function bootstrapApp() {
    initAppUi();
    bindGlobalUiEvents();
    requestAnimationFrame(updateCinematicViewportMetrics);
    requestAnimationFrame(updateStyleChipFade);
    requestAnimationFrame(updateTabIndicator);
  }

  bootstrapApp();
