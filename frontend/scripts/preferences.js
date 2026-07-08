// Theme, layout, and persisted UI preferences
  function isMobileSettingsViewport() {
    return window.matchMedia('(max-width: 768px)').matches;
  }

  function normalizeSkin(skin) {
    return AVAILABLE_SKINS.includes(skin) ? skin : DEFAULT_SKIN;
  }

  function normalizeLayoutMode(mode) {
    return AVAILABLE_LAYOUT_MODES.includes(mode) ? mode : DEFAULT_LAYOUT_MODE;
  }

  function normalizeCinematicColorScheme(scheme) {
    return AVAILABLE_CINEMATIC_COLOR_SCHEMES.includes(scheme) ? scheme : DEFAULT_CINEMATIC_COLOR_SCHEME;
  }

  function normalizeCinematicSection(section) {
    return AVAILABLE_CINEMATIC_SECTIONS.includes(section) ? section : 'records';
  }

  function normalizeCinematicProvider(provider) {
    return AVAILABLE_CINEMATIC_PROVIDERS.includes(provider) ? provider : 'google';
  }

  function resolveGoogleModel(value, fallback = DEFAULT_GOOGLE_MODEL) {
    if (typeof normalizeGoogleModel === 'function') {
      return normalizeGoogleModel(value, fallback);
    }
    const normalized = String(value || '').trim();
    return normalized || fallback;
  }

  function resolveStoredSkin(skin, themeVersion) {
    const normalized = normalizeSkin(skin);
    if ((themeVersion == null || themeVersion < THEME_SCHEMA_VERSION) && normalized === LEGACY_DEFAULT_SKIN) {
      return DEFAULT_SKIN;
    }
    return normalized;
  }

  function updateSkinControls() {
    const select = document.getElementById('skinSelect');
    if (select && select.value !== currentSkin) {
      select.value = currentSkin;
    }
  }

  function updateLayoutControls() {
    const select = document.getElementById('layoutModeSelect');
    if (select && select.value !== currentLayoutMode) {
      select.value = currentLayoutMode;
    }
    const shell = document.getElementById('cinematicShell');
    if (shell) {
      shell.setAttribute('aria-hidden', currentLayoutMode === 'cinematic' ? 'false' : 'true');
    }
  }

  function applyCinematicColorScheme(scheme, persist = true) {
    currentCinematicColorScheme = normalizeCinematicColorScheme(scheme);
    document.documentElement.dataset.cinematicColorScheme = currentCinematicColorScheme;
    if (typeof syncCinematicColorSchemeControls === 'function') {
      syncCinematicColorSchemeControls();
    }
    if (persist) saveUiSettings();
  }

  function applySkin(skin, persist = true) {
    currentSkin = normalizeSkin(skin);
    document.documentElement.dataset.skin = currentSkin;
    updateSkinControls();
    if (persist) saveUiSettings();
  }

  function setSkin(skin) {
    applySkin(skin, true);
  }

  function applyLayoutMode(mode, persist = true) {
    currentLayoutMode = normalizeLayoutMode(mode);
    document.documentElement.dataset.layout = currentLayoutMode;
    updateLayoutControls();
    syncFloatingSubmitBar();

    if (currentLayoutMode === 'cinematic') {
      if (typeof setMainMenuOpen === 'function') {
        setMainMenuOpen(false);
      }
      switchCinematicSection(currentCinematicSection, false);
      renderCinematicStyleVault();
      syncCinematicComposerUi();
      renderCinematicHistoryStream();
      if (!historyRecords.length) {
        scheduleHistoryLoad();
      }
    } else if (typeof setCinematicQuickMenuOpen === 'function') {
      setCinematicQuickMenuOpen(false);
    }

    if (persist) saveUiSettings();
  }

  function setLayoutMode(mode) {
    applyLayoutMode(mode, true);
  }

  function saveUiSettings() {
    genState.model = resolveGoogleModel(genState.model);
    editState.model = resolveGoogleModel(editState.model);
    const payload = {
      themeVersion: THEME_SCHEMA_VERSION,
      theme: currentSkin,
      layoutMode: currentLayoutMode,
      cinematicColorScheme: currentCinematicColorScheme,
      cinematicSection: currentCinematicSection,
      cinematicProvider: currentCinematicProvider,
      cinematicStylePinned,
      cinematicPinnedStyleId,
      cinematicActiveStyleLabel,
      cinematicCustomStyles,
      cinematicStyleOverrides,
      gen: genState,
      edit: editState,
      gpt: gptState,
      comfy: comfyState
    };
    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload));
    } catch (e) {}
    syncCinematicComposerUi();
  }

  function loadUiSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        if (typeof parsed.theme === 'string') {
          currentSkin = resolveStoredSkin(parsed.theme, parsed.themeVersion);
        }
        if (typeof parsed.layoutMode === 'string') {
          currentLayoutMode = normalizeLayoutMode(parsed.layoutMode);
        }
        if (typeof parsed.cinematicColorScheme === 'string') {
          currentCinematicColorScheme = normalizeCinematicColorScheme(parsed.cinematicColorScheme);
        }
        if (typeof parsed.cinematicSection === 'string') {
          currentCinematicSection = normalizeCinematicSection(parsed.cinematicSection);
        }
        if (typeof parsed.cinematicProvider === 'string') {
          currentCinematicProvider = normalizeCinematicProvider(parsed.cinematicProvider);
        }
        if (typeof parsed.cinematicStylePinned === 'boolean') {
          cinematicStylePinned = parsed.cinematicStylePinned;
        }
        if (typeof parsed.cinematicPinnedStyleId === 'string') {
          cinematicPinnedStyleId = parsed.cinematicPinnedStyleId;
        }
        if (typeof parsed.cinematicActiveStyleLabel === 'string') {
          cinematicActiveStyleLabel = parsed.cinematicActiveStyleLabel;
        }
        if (Array.isArray(parsed.cinematicCustomStyles)) {
          cinematicCustomStyles = parsed.cinematicCustomStyles;
        }
        if (parsed.cinematicStyleOverrides && typeof parsed.cinematicStyleOverrides === 'object') {
          cinematicStyleOverrides = parsed.cinematicStyleOverrides;
        }
        genState = { ...genState, ...(parsed.gen || {}) };
        editState = { ...editState, ...(parsed.edit || {}) };
        genState.model = resolveGoogleModel(genState.model);
        editState.model = resolveGoogleModel(editState.model);
        gptState = { ...gptState, ...(parsed.gpt || {}) };
        comfyState = { ...comfyState, ...(parsed.comfy || {}) };
        if (
          parsed.theme !== currentSkin ||
          parsed.themeVersion !== THEME_SCHEMA_VERSION ||
          parsed.layoutMode !== currentLayoutMode ||
          parsed.cinematicColorScheme !== currentCinematicColorScheme ||
          parsed.cinematicSection !== currentCinematicSection ||
          parsed.cinematicProvider !== currentCinematicProvider
        ) {
          saveUiSettings();
        }
      }
    } catch (e) {}
  }

  function applyPersistedSettings() {
    const genModelSelect = document.getElementById('genModelSelect');
    const genQualitySelect = document.getElementById('genQuality');
    const editFeatureSelect = document.getElementById('editFeature');
    const editQualitySelect = document.getElementById('editQuality');
    const genModel = resolveGoogleModel(genState.model);
    const editModel = resolveGoogleModel(editState.model);

    applySkin(currentSkin, false);
    applyCinematicColorScheme(currentCinematicColorScheme, false);
    applyLayoutMode(currentLayoutMode, false);

    genState.model = genModel;
    editState.model = editModel;
    if (genModelSelect) genModelSelect.value = genModel;
    if (genQualitySelect) genQualitySelect.value = genState.quality || '2k';
    if (editFeatureSelect) editFeatureSelect.value = editState.feature || 'edit';
    if (editQualitySelect) editQualitySelect.value = editState.quality || 'hd';

    pickModel('gen', genModel);
    pickGenQuality(genState.quality || '2k');
    pickStyle(genState.style || 'raw');
    pickRatioGen(genState.ratio || '1:1');

    pickModel('edit', editModel);
    pickQuality(editState.quality || 'hd');
    pickFeature(editState.feature || 'edit');
    pickRatioEdit(editState.ratio || 'auto');

    pickRatioGpt(gptState.ratio || '9:16');
    pickResolutionGpt(gptState.resolution || '1k');
    pickQualityGpt(gptState.quality || 'auto');
    pickImageCountGpt(gptState.imageCount || 1);
    pickModerationGpt(gptState.moderation || 'auto');
    if (typeof pickProviderRouteGpt === 'function') {
      pickProviderRouteGpt(gptState.gptProviderRoute || (gptState.useThirdPartyApi ? 'third_party_image_api' : 'codex'));
    }
    pickRatioComfy(comfyState.ratio || '1:1');
    renderCinematicStyleVault();
    switchCinematicSection(currentCinematicSection, false);
    syncCinematicComposerUi();
  }
