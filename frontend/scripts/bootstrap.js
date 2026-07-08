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

  function initAppUi() {
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
