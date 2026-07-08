// Shared shell navigation and view chrome
  function updateStyleChipFade() {
    const wrap = document.getElementById('genStyleChipsWrap');
    const scroller = document.getElementById('genStyleChips');
    if (!wrap || !scroller) return;

    const maxScroll = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
    const left = scroller.scrollLeft;
    const threshold = 2;

    wrap.classList.toggle('has-left', left > threshold);
    wrap.classList.toggle('has-right', left < maxScroll - threshold);
  }

  function updateTabIndicator(activeTab) {
    const indicator = document.getElementById('tabsIndicator');
    const tabs = document.querySelector('.tabs');
    const target = activeTab || document.querySelector('.tabs .tab.active');
    if (!indicator || !tabs || !target) return;
    const targetLeft = target.offsetLeft;
    const targetWidth = target.offsetWidth;
    const ready = indicator.dataset.ready === 'true';

    if (!ready) {
      indicator.classList.remove('is-ready', 'is-moving');
      indicator.style.width = `${targetWidth}px`;
      indicator.style.transform = `translateX(${targetLeft}px)`;
      indicator.dataset.ready = 'true';
      indicator.dataset.left = String(targetLeft);
      indicator.dataset.width = String(targetWidth);
      requestAnimationFrame(() => indicator.classList.add('is-ready'));
      return;
    }

    indicator.classList.add('is-moving');
    clearTimeout(updateTabIndicator._timer);
    indicator.style.width = `${targetWidth}px`;
    indicator.style.transform = `translateX(${targetLeft}px)`;
    updateTabIndicator._timer = setTimeout(() => {
      indicator.classList.remove('is-moving');
    }, 680);

    indicator.dataset.left = String(targetLeft);
    indicator.dataset.width = String(targetWidth);
  }

  function getActiveViewKey() {
    if (document.getElementById('view-comfy')?.classList.contains('active')) return 'comfy';
    if (document.getElementById('view-gpt')?.classList.contains('active')) return 'gpt';
    if (document.getElementById('view-edit')?.classList.contains('active')) return 'edit';
    if (document.getElementById('view-gen')?.classList.contains('active')) return 'gen';
    return '';
  }

  function syncFloatingSubmitBar() {
    const bar = document.getElementById('globalSubmitBar');
    if (!bar) return;

    const activeKey = getActiveViewKey();
    const shouldHide = !activeKey || currentLayoutMode === 'cinematic';

    bar.classList.toggle('is-hidden', shouldHide);
    bar.querySelectorAll('.submit-action').forEach(button => {
      const isVisible = !shouldHide && button.id === STAGE_BUTTON_IDS[activeKey];
      button.classList.toggle('is-visible', isVisible);
    });
  }

  function activateView(viewId) {
    closeSettings();
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    const nextView = document.getElementById(viewId);
    if (!nextView) return;
    nextView.classList.add('active');
    syncFloatingSubmitBar();
  }

  function openSettings(key) {
    if (!isMobileSettingsViewport()) return;
    const panel = document.getElementById(`settingsPanel-${key}`);
    const overlay = document.getElementById('settingsOverlay');
    if (!panel || !overlay) return;
    if (currentSettingsPanel === panel.id) {
      closeSettings();
      return;
    }
    closeSettings();
    panel.classList.add('open');
    overlay.classList.add('open');
    document.body.classList.add('settings-open');
    const trigger = document.querySelector(`.settings-trigger[data-settings-key="${key}"]`);
    if (trigger) trigger.classList.add('is-open');
    currentSettingsPanel = panel.id;
  }

  function closeSettings() {
    document.querySelectorAll('.settings-panel.open').forEach(panel => panel.classList.remove('open'));
    document.querySelectorAll('.settings-trigger.is-open').forEach(trigger => trigger.classList.remove('is-open'));
    const overlay = document.getElementById('settingsOverlay');
    if (overlay) overlay.classList.remove('open');
    document.body.classList.remove('settings-open');
    currentSettingsPanel = null;
  }

  function setSubmitButtonState(btnId, { busy = false, label = '' } = {}) {
    const btn = typeof btnId === 'string' ? document.getElementById(btnId) : btnId;
    if (!btn) return null;
    btn.disabled = !!busy;
    btn.classList.toggle('is-working', !!busy);
    btn.textContent = label || SUBMIT_BUTTON_DEFAULTS[btn.id] || btn.textContent;

    if (btn.id === 'btnGen' || btn.id === 'btnEdit') {
      const cinematicBtn = document.getElementById('cinematicSubmitBtn');
      if (cinematicBtn) {
        cinematicBtn.disabled = !!busy;
      }
    }

    return btn;
  }

  function setTabActive(tabId) {
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    const tab = document.getElementById(tabId);
    if (tab) tab.classList.add('active');
    return tab;
  }

  function closeGoogleDrawer() {
    const drawer = document.getElementById('googleDrawer');
    const googleTab = document.getElementById('tab-google');
    if (drawer) drawer.classList.remove('open');
    if (googleTab) googleTab.classList.remove('drawer-open');
  }

  function setGoogleDrawerOpen(isOpen) {
    const drawer = document.getElementById('googleDrawer');
    const googleTab = document.getElementById('tab-google');
    if (drawer) drawer.classList.toggle('open', isOpen);
    if (googleTab) googleTab.classList.toggle('drawer-open', isOpen);
  }

  function getSelectedGoogleSubview() {
    const activeOption = document.querySelector('.drawer-option.active');
    return activeOption?.textContent?.trim().toLowerCase() === 'edit' ? 'edit' : 'gen';
  }

  function activateGoogleTab(view = 'gen') {
    const googleTab = setTabActive('tab-google');
    localStorage.setItem('currentView', 'google');
    activateView('view-' + view);
    requestAnimationFrame(() => updateTabIndicator(googleTab));
    if (view === 'gen') {
      requestAnimationFrame(updateStyleChipFade);
    }
    return googleTab;
  }

  function setMainMenuOpen(isOpen) {
    const menu = document.getElementById('mainMenu');
    const overlay = document.getElementById('mainMenuOverlay');
    if (menu) menu.classList.toggle('open', isOpen);
    if (overlay) overlay.classList.toggle('open', isOpen);
  }

  function getCinematicColorSchemeMeta(scheme = currentCinematicColorScheme) {
    return CINEMATIC_COLOR_SCHEME_OPTIONS.find((item) => item.id === normalizeCinematicColorScheme(scheme))
      || CINEMATIC_COLOR_SCHEME_OPTIONS[0];
  }

  function syncCinematicColorSchemeControls() {
    const activeScheme = normalizeCinematicColorScheme(currentCinematicColorScheme);
    const currentLabel = document.getElementById('cinematicColorSystemCurrent');
    const meta = getCinematicColorSchemeMeta(activeScheme);

    if (currentLabel) {
      currentLabel.textContent = meta.title;
    }

    document.querySelectorAll('[data-cinematic-color-scheme-option]').forEach((button) => {
      const isActive = button.dataset.cinematicColorSchemeOption === activeScheme;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function setCinematicQuickMenuOpen(isOpen) {
    const menu = document.getElementById('cinematicMenu');
    const overlay = document.getElementById('cinematicMenuOverlay');
    const nav = document.querySelector('.cinematic-bottom-nav');
    if (menu) menu.classList.toggle('open', isOpen);
    if (overlay) overlay.classList.toggle('open', isOpen);
    if (nav) nav.classList.toggle('is-menu-open', isOpen);
    document.querySelectorAll('[data-cinematic-menu-trigger]').forEach(trigger => {
      trigger.classList.toggle('is-active', isOpen);
    });
  }

  function setSidebarOpen(isOpen) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.toggle('open', isOpen);
    if (overlay) overlay.classList.toggle('open', isOpen);
    if (isOpen) scheduleHistoryLoad();
  }

  function hideAllViews() {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    syncFloatingSubmitBar();
  }

  function toggleGoogleDrawer() {
    const googleTab = document.getElementById('tab-google');
    const wasActive = googleTab && googleTab.classList.contains('active');

    if (googleTab && !wasActive) {
      activateGoogleTab(getSelectedGoogleSubview());
    }

    const drawer = document.getElementById('googleDrawer');
    const isOpen = !(drawer && drawer.classList.contains('open'));
    setGoogleDrawerOpen(isOpen);
  }

  function selectGoogleOption(opt, evt) {
    closeGoogleDrawer();
    document.querySelectorAll('.drawer-option').forEach(el => el.classList.remove('active'));
    const target = evt?.currentTarget || evt?.target;
    if (target) target.classList.add('active');
    activateGoogleTab(opt);
  }

  function switchView(view) {
    localStorage.setItem('currentView', view);
    closeGoogleDrawer();
    closeSettings();

    if (view === 'google') {
      activateGoogleTab('gen');
      return;
    }

    switchTab(view);
  }

  function openWorkspace(view) {
    applyLayoutMode('classic', true);
    switchView(view);
    setMainMenuOpen(false);
  }

  function switchToClassicFromCinematicMenu() {
    applyLayoutMode('classic', true);
    setCinematicQuickMenuOpen(false);
    showStatusMessage('已切回 Classic 工作台。', 'success');
  }

  function setCinematicColorScheme(scheme) {
    const nextScheme = normalizeCinematicColorScheme(scheme);
    const prevScheme = normalizeCinematicColorScheme(currentCinematicColorScheme);
    applyCinematicColorScheme(nextScheme, true);
    if (prevScheme !== nextScheme) {
      showStatusMessage(`Cinematic 已切换到 ${getCinematicColorSchemeMeta(nextScheme).title}。`, 'success');
    }
  }

  function openHistoryFromMenu() {
    if (currentLayoutMode === 'cinematic') {
      switchCinematicSection('records');
      setCinematicQuickMenuOpen(false);
      if (!historyRecords.length) {
        scheduleHistoryLoad();
      }
      return;
    }
    setSidebarOpen(true);
    setMainMenuOpen(false);
  }

  function switchTab(t) {
    closeGoogleDrawer();
    closeSettings();
    localStorage.setItem('currentView', t);

    const nextTab = setTabActive('tab-' + t);
    if (nextTab) {
      requestAnimationFrame(() => updateTabIndicator(nextTab));
    }

    if (t === 'comfy') {
      activateView('view-comfy');
      loadComfyWorkflows();
    } else if (t === 'gpt') {
      activateView('view-gpt');
    }
  }

  function toggleMainMenu() {
    closeSettings();
    closeGoogleDrawer();
    const menu = document.getElementById('mainMenu');
    setMainMenuOpen(!(menu && menu.classList.contains('open')));
  }

  function toggleCinematicQuickMenu() {
    closeSettings();
    const menu = document.getElementById('cinematicMenu');
    setCinematicQuickMenuOpen(!(menu && menu.classList.contains('open')));
  }

  function toggleSidebar() {
    closeSettings();
    const sidebar = document.getElementById('sidebar');
    setSidebarOpen(!(sidebar && sidebar.classList.contains('open')));
  }
