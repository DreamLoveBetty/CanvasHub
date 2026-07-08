// Cinematic composer, dock menus, and section switching

  function getCinematicTypeLabel(item) {
    const map = {
      'google-gen': '图像生成',
      'google-edit': '图片编辑',
      'gpt': 'GPT 任务',
      'gpt-edit': 'GPT 编辑',
      'comfy': 'ComfyUI'
    };
    return map[item?.type] || '创作记录';
  }

  function getCinematicPrimaryBadge(item) {
    const params = item?.params || {};
    if (params.model) {
      const model = typeof normalizeGoogleModel === 'function'
        ? normalizeGoogleModel(params.model)
        : String(params.model || '').trim();
      if (model === 'gemini-3-pro-image') return 'PRO';
      if (model === 'gemini-3.1-flash-image') return 'FLASH';
      return model
        .replace('gemini-', '')
        .replace('-image-preview', '')
        .replace('-image', '')
        .replace('-preview', '')
        .replace(/\./g, '-')
        .toUpperCase();
    }
    if (item?.type === 'gpt' || item?.type === 'gpt-edit') return 'GPT-IMAGE';
    if (item?.type === 'comfy') return 'WORKFLOW';
    return 'RAW';
  }

  function getCinematicSecondaryBadge(item) {
    const params = item?.params || {};
    if ((item?.type === 'gpt' || item?.type === 'gpt-edit') && (params.resolution || params.quality)) {
      return [params.resolution, params.quality]
        .filter(Boolean)
        .map(v => String(v).toUpperCase())
        .join(' / ');
    }
    if (params.ratio) return String(params.ratio).toUpperCase();
    if (params.quality === 'hd') return 'HD';
    if (params.quality === 'standard') return 'STD';
    if (params.quality) return String(params.quality).toUpperCase();
    return item?.status === 'success' ? 'READY' : item?.status === 'failed' ? 'FAILED' : 'PENDING';
  }

  function getCinematicSourceLabel(item) {
    if (item?.type === 'google-edit') return '编辑流';
    if (item?.type === 'google-gen') return '生成流';
    if (item?.type === 'gpt') return '后台发送';
    if (item?.type === 'gpt-edit') return 'GPT 编辑';
    if (item?.type === 'comfy') return '本地工作流';
    return '创作记录';
  }

  function hydrateCinematicPrompt(prompt) {
    const textarea = document.getElementById('cinematicPrompt');
    if (!textarea) return;
    textarea.value = prompt || '';
    syncCinematicPromptState();
  }

  function syncCinematicReferenceState() {
    const strip = document.getElementById('cinematicRefStrip');
    if (!strip) return;

    strip.innerHTML = '';
    strip.hidden = uploadedImages.length === 0;

    if (uploadedImages.length === 0) {
      return;
    }

    strip.hidden = false;
    uploadedImages.slice(0, MAX_IMGS).forEach((item, index) => {
      const thumb = document.createElement('div');
      thumb.className = 'cinematic-ref-thumb';
      thumb.innerHTML = `
        <img src="${item.base64}" alt="参考图 ${index + 1}">
        <span class="cinematic-ref-thumb-index">${index + 1}</span>
      `;
      strip.appendChild(thumb);
    });
  }

  function getCinematicMenuParts(key) {
    const suffix = key.charAt(0).toUpperCase() + key.slice(1);
    return {
      wrap: document.getElementById(`cinematic${suffix}Wrap`),
      button: document.getElementById(`cinematic${suffix}Btn`),
      menu: document.getElementById(`cinematic${suffix}Menu`)
    };
  }

  function setCinematicPillLabel(button, label) {
    const valueEl = button?.querySelector('.cinematic-pill-value');
    if (valueEl) {
      valueEl.textContent = label;
      return;
    }
    if (button) button.textContent = label;
  }

  function decorateCinematicRatioOption(button) {
    if (!button || button.dataset.decorated === 'true') return;

    const ratioValue = (button.dataset.ratio || button.textContent || '').trim();
    if (!ratioValue.includes(':')) return;

    const [wRaw, hRaw] = ratioValue.split(':').map(v => Number(v) || 1);
    const maxSide = 12;
    let width = maxSide;
    let height = maxSide;
    if (wRaw >= hRaw) {
      height = Math.max(5, Math.round((hRaw / wRaw) * maxSide));
    } else {
      width = Math.max(5, Math.round((wRaw / hRaw) * maxSide));
    }

    button.dataset.decorated = 'true';
    button.innerHTML = `
      <span class="cinematic-ratio-chip">
        <span class="cinematic-ratio-visual" style="--crw:${width};--crh:${height}">
          <span class="cinematic-ratio-frame"></span>
        </span>
        <span class="cinematic-ratio-label">${ratioValue}</span>
      </span>
    `;
  }

  function initCinematicRatioMenuVisuals() {
    document.querySelectorAll('#cinematicRatioMenu .cinematic-pop-option[data-ratio]').forEach((button) => {
      decorateCinematicRatioOption(button);
    });
  }

  function syncCinematicMenuSelection(menu, selector, currentValue) {
    menu?.querySelectorAll(selector).forEach((option) => {
      const activeValue = Object.values(option.dataset || {})[0] || '';
      option.classList.toggle('is-active', activeValue === String(currentValue));
    });
  }

  function setCinematicMenu(nextMenu) {
    currentCinematicMenu = nextMenu;
    ['provider', 'model', 'quality', 'ratio', 'gptQuality', 'gptCount', 'gptModeration'].forEach((key) => {
      const { wrap, button, menu } = getCinematicMenuParts(key);
      const shouldOpen = Boolean(wrap && !wrap.hidden && menu && key === currentCinematicMenu);
      if (menu) menu.hidden = !shouldOpen;
      button?.classList.toggle('is-open', shouldOpen);
      wrap?.classList.toggle('is-open', shouldOpen);
    });
  }

  function closeCinematicMenus() {
    setCinematicMenu(null);
  }

  function toggleCinematicMenu(key, event) {
    if (event) event.stopPropagation();
    const { wrap } = getCinematicMenuParts(key);
    if (!wrap || wrap.hidden) return;
    setCinematicMenu(currentCinematicMenu === key ? null : key);
  }

  function selectCinematicProvider(provider, event) {
    if (event) event.stopPropagation();
    currentCinematicProvider = normalizeCinematicProvider(provider);
    cinematicRevealState.provider = true;
    cinematicRevealState.model = false;
    cinematicRevealState.quality = false;
    cinematicRevealState.gptQuality = false;
    cinematicRevealState.gptCount = false;
    cinematicRevealState.gptModeration = false;
    closeCinematicMenus();
    syncCinematicComposerUi();
    saveUiSettings();
  }

  function selectCinematicGoogleModel(modelKey, event) {
    if (event) event.stopPropagation();
    if (normalizeCinematicProvider(currentCinematicProvider) !== 'google') return;
    const nextModel = modelKey === 'flash' ? CINEMATIC_MODEL_MAP.fast : CINEMATIC_MODEL_MAP.pro;
    pickModel('gen', nextModel);
    pickModel('edit', nextModel);
    cinematicRevealState.model = true;
    cinematicRevealState.quality = false;
    closeCinematicMenus();
    syncCinematicComposerUi();
  }

  function selectCinematicQuality(quality, event) {
    if (event) event.stopPropagation();
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    if (provider === 'google') {
      pickGenQuality(quality);
      pickQuality(quality === '1k' ? 'standard' : 'hd');
    } else if (provider === 'gpt') {
      pickResolutionGpt(quality);
      cinematicRevealState.gptQuality = false;
      cinematicRevealState.gptCount = false;
      cinematicRevealState.gptModeration = false;
    } else {
      return;
    }
    cinematicRevealState.quality = true;
    closeCinematicMenus();
    syncCinematicComposerUi();
  }

  function selectCinematicGptQuality(quality, event) {
    if (event) event.stopPropagation();
    if (normalizeCinematicProvider(currentCinematicProvider) !== 'gpt') return;
    pickQualityGpt(quality);
    cinematicRevealState.gptQuality = true;
    cinematicRevealState.gptCount = uploadedImages.length === 0;
    cinematicRevealState.gptModeration = true;
    closeCinematicMenus();
    syncCinematicComposerUi();
  }

  function selectCinematicGptCount(count, event) {
    if (event) event.stopPropagation();
    if (normalizeCinematicProvider(currentCinematicProvider) !== 'gpt') return;
    pickImageCountGpt(count);
    cinematicRevealState.gptCount = true;
    cinematicRevealState.gptModeration = true;
    closeCinematicMenus();
    syncCinematicComposerUi();
  }

  function setCinematicGptCountFromSlider(count, shouldSave = false) {
    if (normalizeCinematicProvider(currentCinematicProvider) !== 'gpt') return;
    pickImageCountGpt(count);
    cinematicRevealState.gptCount = true;
    cinematicRevealState.gptModeration = true;
    syncCinematicComposerUi();
    if (shouldSave) saveUiSettings();
  }

  function selectCinematicGptModeration(moderation, event) {
    if (event) event.stopPropagation();
    if (normalizeCinematicProvider(currentCinematicProvider) !== 'gpt') return;
    pickModerationGpt(moderation);
    cinematicRevealState.gptModeration = true;
    closeCinematicMenus();
    syncCinematicComposerUi();
  }

  function selectCinematicRatio(ratio, event) {
    if (event) event.stopPropagation();
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    const usingEditFlow = provider === 'google' && uploadedImages.length > 0;
    if (provider === 'google') {
      if (usingEditFlow) {
        pickRatioEdit(ratio);
      } else {
        pickRatioGen(ratio);
      }
    } else if (provider === 'gpt') {
      pickRatioGpt(ratio);
      cinematicRevealState.gptQuality = true;
      cinematicRevealState.gptCount = false;
      cinematicRevealState.gptModeration = false;
    } else {
      pickRatioComfy(ratio);
    }
    closeCinematicMenus();
    syncCinematicComposerUi();
  }

  function getCinematicGoogleModelKey() {
    const model = typeof normalizeGoogleModel === 'function'
      ? normalizeGoogleModel(genState.model)
      : String(genState.model || '').trim();
    return model === CINEMATIC_MODEL_MAP.fast ? 'fast' : 'pro';
  }

  function syncCinematicComposerUi() {
    initCinematicRatioMenuVisuals();
    const promptEl = document.getElementById('cinematicPrompt');
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    const usingGoogle = provider === 'google';
    const usingEditFlow = usingGoogle && uploadedImages.length > 0;
    const usingGptEditFlow = provider === 'gpt' && uploadedImages.length > 0;
    const currentQuality = provider === 'gpt'
      ? (gptState.resolution || '1k')
      : (genState.quality || '2k');
    const providerBtn = document.getElementById('cinematicProviderBtn');
    const providerWrap = document.getElementById('cinematicProviderWrap');
    const modelBtn = document.getElementById('cinematicModelBtn');
    const modelWrap = document.getElementById('cinematicModelWrap');
    const qualityBtn = document.getElementById('cinematicQualityBtn');
    const qualityWrap = document.getElementById('cinematicQualityWrap');
    const gptQualityBtn = document.getElementById('cinematicGptQualityBtn');
    const gptQualityWrap = document.getElementById('cinematicGptQualityWrap');
    const gptCountBtn = document.getElementById('cinematicGptCountBtn');
    const gptCountWrap = document.getElementById('cinematicGptCountWrap');
    const gptCountSlider = document.getElementById('cinematicGptCountSlider');
    const gptCountRange = document.getElementById('cinematicGptCountRange');
    const gptCountValue = document.getElementById('cinematicGptCountValue');
    const gptModerationBtn = document.getElementById('cinematicGptModerationBtn');
    const gptModerationWrap = document.getElementById('cinematicGptModerationWrap');
    const ratioBtn = document.getElementById('cinematicRatioBtn');
    const ratioWrap = document.getElementById('cinematicRatioWrap');
    const submitBtn = document.getElementById('cinematicSubmitBtn');
    const styleChip = document.getElementById('cinematicStyleChip');
    const clearPromptChip = document.getElementById('cinematicClearPromptChip');
    const clearBtn = document.getElementById('cinematicRefClearBtn');
    const modelKey = getCinematicGoogleModelKey();
    const showProvider = true;
    const showModel = usingGoogle && cinematicRevealState.provider;
    const showQuality = usingGoogle
      ? (cinematicRevealState.provider && cinematicRevealState.model)
      : provider === 'gpt'
        ? cinematicRevealState.provider
        : false;
    const showGptQuality = provider === 'gpt' && cinematicRevealState.gptQuality;
    const showGptCount = provider === 'gpt' && !usingGptEditFlow && cinematicRevealState.gptCount;
    const showGptModeration = provider === 'gpt' && cinematicRevealState.gptModeration;
    const showRatio = usingGoogle
      ? (cinematicRevealState.provider && cinematicRevealState.model && cinematicRevealState.quality)
      : provider === 'gpt'
        ? cinematicRevealState.quality
        : false;

    if (providerBtn) {
      const providerLabelMap = {
        google: 'Google',
        comfyui: 'ComfyUI',
        gpt: 'GPT'
      };
      setCinematicPillLabel(providerBtn, providerLabelMap[provider] || 'Google');
      providerWrap.hidden = !showProvider;
      syncCinematicMenuSelection(document.getElementById('cinematicProviderMenu'), '[data-provider]', provider);
    }

    if (modelBtn) {
      modelWrap.hidden = !showModel;
      setCinematicPillLabel(modelBtn, modelKey === 'fast' ? 'Flash' : 'Pro');
      syncCinematicMenuSelection(document.getElementById('cinematicModelMenu'), '[data-model]', modelKey);
    }

    if (qualityBtn) {
      qualityWrap.hidden = !showQuality;
      setCinematicPillLabel(qualityBtn, String(currentQuality || '2k').toUpperCase());
      syncCinematicMenuSelection(document.getElementById('cinematicQualityMenu'), '[data-quality]', currentQuality);
    }

    if (gptQualityBtn) {
      const currentGptQuality = String(gptState.quality || 'auto').trim().toLowerCase();
      gptQualityWrap.hidden = !showGptQuality;
      setCinematicPillLabel(gptQualityBtn, currentGptQuality.charAt(0).toUpperCase() + currentGptQuality.slice(1));
      syncCinematicMenuSelection(document.getElementById('cinematicGptQualityMenu'), '[data-gpt-quality]', currentGptQuality);
    }

    if (gptCountBtn) {
      const currentGptCount = Math.max(1, Math.min(8, parseInt(gptState.imageCount || 1, 10) || 1));
      gptCountWrap.hidden = true;
      setCinematicPillLabel(gptCountBtn, `${currentGptCount} 张`);
      syncCinematicMenuSelection(document.getElementById('cinematicGptCountMenu'), '[data-gpt-count]', currentGptCount);
    }

    if (gptCountSlider) {
      const currentGptCount = Math.max(1, Math.min(8, parseInt(gptState.imageCount || 1, 10) || 1));
      gptCountSlider.hidden = !showGptCount;
      if (gptCountRange && String(gptCountRange.value) !== String(currentGptCount)) {
        gptCountRange.value = String(currentGptCount);
      }
      if (gptCountValue) gptCountValue.textContent = `${currentGptCount} 张`;
      const pct = ((currentGptCount - 1) / 7) * 100;
      gptCountSlider.style.setProperty('--count-progress', `${pct}%`);
    }

    if (gptModerationBtn) {
      const currentGptModeration = String(gptState.moderation || 'auto').trim().toLowerCase() === 'low' ? 'low' : 'auto';
      gptModerationWrap.hidden = !showGptModeration;
      setCinematicPillLabel(gptModerationBtn, `审核 ${currentGptModeration.charAt(0).toUpperCase() + currentGptModeration.slice(1)}`);
      syncCinematicMenuSelection(document.getElementById('cinematicGptModerationMenu'), '[data-gpt-moderation]', currentGptModeration);
    }

    if (ratioBtn) {
      const currentRatio = provider === 'google'
        ? (usingEditFlow ? editState.ratio : genState.ratio)
        : provider === 'gpt'
          ? gptState.ratio
          : comfyState.ratio;
      ratioWrap.hidden = !showRatio;
      setCinematicPillLabel(ratioBtn, currentRatio === 'auto' ? 'AUTO' : (currentRatio || '1:1'));
      syncCinematicMenuSelection(document.getElementById('cinematicRatioMenu'), '[data-ratio]', currentRatio === 'auto' ? '1:1' : (currentRatio || '1:1'));
    }

    if (submitBtn) {
      if (provider === 'google') {
        submitBtn.textContent = usingEditFlow ? '✎' : '✦';
        submitBtn.title = usingEditFlow ? '提交 Google 编辑' : '提交 Google 生成';
      } else if (provider === 'gpt') {
        submitBtn.textContent = 'G';
        submitBtn.title = usingGptEditFlow ? '提交 GPT 编辑任务' : '提交 GPT 生成任务';
      } else {
        submitBtn.textContent = '◈';
        submitBtn.title = '打开 ComfyUI 工作台';
      }
      submitBtn.classList.toggle('is-letter', provider === 'gpt');
    }

    if (styleChip) {
      const shouldShowStyleChip = usingGoogle && cinematicStylePinned && !!cinematicActiveStyleLabel;
      styleChip.hidden = !shouldShowStyleChip;
      if (shouldShowStyleChip) {
        styleChip.textContent = cinematicActiveStyleLabel;
        styleChip.title = `当前风格：${cinematicActiveStyleLabel}，点击可清除`;
      }
    }

    if (clearPromptChip) {
      const hasPrompt = !!String(promptEl?.value || '').trim();
      clearPromptChip.hidden = !hasPrompt;
    }

    if (clearBtn) {
      clearBtn.disabled = uploadedImages.length === 0;
      clearBtn.title = uploadedImages.length === 0
        ? '暂无参考图'
        : '单击删除最近一张，长按 3 秒清空全部参考图';
    }

    if (promptEl && !promptEl.dataset.userEdited) {
      const fallbackPrompt = provider === 'google'
        ? (usingEditFlow ? (document.getElementById('editPrompt')?.value || '') : (document.getElementById('genPrompt')?.value || ''))
        : provider === 'gpt'
          ? (document.getElementById('gptPrompt')?.value || '')
          : (document.getElementById('comfyPrompt')?.value || '');
      if (!promptEl.value && fallbackPrompt) {
        promptEl.value = fallbackPrompt;
      }
    }

    const activeMenuWrap = currentCinematicMenu ? getCinematicMenuParts(currentCinematicMenu).wrap : null;
    if (!activeMenuWrap || activeMenuWrap.hidden) {
      closeCinematicMenus();
    }

    syncCinematicReferenceState();
    updateLayoutControls();
  }

  function switchCinematicSection(section, persist = true) {
    const previousSection = currentCinematicSection;
    currentCinematicSection = normalizeCinematicSection(section);
    if (document.getElementById('cinematicMenu')?.classList.contains('open')) {
      setCinematicQuickMenuOpen(false);
    }
    updateCinematicViewportMetrics();
    const recordsActive = currentCinematicSection === 'records';
    const discoverActive = currentCinematicSection === 'discover';
    const spellActive = currentCinematicSection === 'spell';
    const main = document.querySelector('.cinematic-main');

    document.querySelector('.cinematic-composer-dock')?.toggleAttribute('hidden', !recordsActive);
    document.getElementById('cinematicRecordsSection')?.classList.toggle('is-active', recordsActive);
    document.getElementById('cinematicDiscoverSection')?.classList.toggle('is-active', discoverActive);
    document.getElementById('cinematicSpellSection')?.classList.toggle('is-active', spellActive);
    document.getElementById('cinematicTopRecords')?.classList.toggle('is-active', recordsActive);
    document.getElementById('cinematicTopDiscover')?.classList.toggle('is-active', discoverActive);
    document.getElementById('cinematicTopSpell')?.classList.toggle('is-active', spellActive);
    document.getElementById('cinematicBottomRecords')?.classList.toggle('is-active', recordsActive);
    document.getElementById('cinematicBottomDiscover')?.classList.toggle('is-active', discoverActive);
    document.getElementById('cinematicBottomSpell')?.classList.toggle('is-active', spellActive);

    if (recordsActive && !historyRecords.length) {
      scheduleHistoryLoad();
    } else if (recordsActive) {
      syncCinematicLatestRecordFocus({ force: previousSection !== 'records' });
    } else if (main) {
      requestAnimationFrame(() => {
        main.scrollTop = 0;
      });
    }

    if (persist) saveUiSettings();
  }

  function isCinematicMainNearBottom(main, threshold = 80) {
    if (!main) return true;
    return main.scrollHeight - main.clientHeight - main.scrollTop <= threshold;
  }

  function syncCinematicLatestRecordFocus(options = {}) {
    if (currentCinematicSection !== 'records') return;
    const force = !!options.force;
    requestAnimationFrame(() => {
      updateCinematicViewportMetrics();
      scrollCinematicRecordsToLatest({ force });
      requestAnimationFrame(() => {
        updateCinematicViewportMetrics();
        scrollCinematicRecordsToLatest({ force });
      });
    });
  }

  function scrollCinematicRecordsToLatest(options = {}) {
    if (currentCinematicSection !== 'records') return;
    const main = document.querySelector('.cinematic-main');
    if (!main) return;
    if (!options.force && !isCinematicMainNearBottom(main)) return;
    main.scrollTop = main.scrollHeight;
  }

  function updateCinematicViewportMetrics() {
    const shell = document.getElementById('cinematicShell');
    const dock = document.querySelector('.cinematic-composer-dock');
    const nav = document.querySelector('.cinematic-bottom-nav');
    const main = document.querySelector('.cinematic-main');
    const list = document.getElementById('cinematicHistoryList');
    const latestCard = document.querySelector('#cinematicHistoryList .cinematic-record-card:last-child');
    if (!shell || !dock || !nav || !main) return;

    const mainRect = main.getBoundingClientRect();
    const dockRect = dock.getBoundingClientRect();
    const navRect = nav.getBoundingClientRect();
    const navOffsetFromBottom = Math.max(0, Math.ceil(window.innerHeight - navRect.top));
    const navHeight = Math.max(0, Math.ceil(navRect.height || 0));
    const occlusionTop = Math.min(dockRect.top || window.innerHeight, navRect.top || window.innerHeight);
    const overlayGap = Math.max(0, Math.ceil(mainRect.bottom - occlusionTop));
    const baseGap = Math.max(190, overlayGap + 16);
    let nextGap = baseGap;

    if (latestCard) {
      const latestCardHeight = Math.ceil(latestCard.getBoundingClientRect().height || 0);
      if (latestCardHeight > 0) {
        const mainPaddingTop = Math.ceil(parseFloat(window.getComputedStyle(main).paddingTop || '0') || 0);
        const streamGap = list
          ? Math.ceil(parseFloat(window.getComputedStyle(list).rowGap || window.getComputedStyle(list).gap || '0') || 0)
          : 0;
        const focusInset = Math.max(4, Math.min(12, streamGap > 0 ? streamGap - 4 : mainPaddingTop));
        const focusGap = Math.max(0, Math.round(main.clientHeight - latestCardHeight - focusInset));
        nextGap = Math.max(baseGap, focusGap);
      }
    }

    document.documentElement.style.setProperty('--cinematic-bottom-nav-offset', `${navOffsetFromBottom}px`);
    document.documentElement.style.setProperty('--cinematic-bottom-nav-height', `${navHeight}px`);
    document.documentElement.style.setProperty('--cinematic-records-bottom-gap', `${nextGap}px`);
  }

  function openCinematicReferencePicker() {
    document.getElementById('fileInput')?.click();
  }

  function cycleCinematicProvider() {
    const currentIndex = AVAILABLE_CINEMATIC_PROVIDERS.indexOf(normalizeCinematicProvider(currentCinematicProvider));
    currentCinematicProvider = AVAILABLE_CINEMATIC_PROVIDERS[(currentIndex + 1 + AVAILABLE_CINEMATIC_PROVIDERS.length) % AVAILABLE_CINEMATIC_PROVIDERS.length];
    cinematicRevealState.provider = true;
    cinematicRevealState.model = false;
    cinematicRevealState.quality = false;
    cinematicRevealState.gptQuality = false;
    cinematicRevealState.gptCount = false;
    cinematicRevealState.gptModeration = false;
    syncCinematicComposerUi();
    saveUiSettings();
  }

  function cycleCinematicGoogleModel() {
    if (normalizeCinematicProvider(currentCinematicProvider) !== 'google') return;
    const model = getCinematicGoogleModelKey() === 'fast' ? CINEMATIC_MODEL_MAP.pro : CINEMATIC_MODEL_MAP.fast;
    pickModel('gen', model);
    pickModel('edit', model);
    syncCinematicComposerUi();
  }

  function cycleCinematicQuality() {
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    if (provider === 'google') {
      const idx = CINEMATIC_GEN_QUALITY_OPTIONS.indexOf(genState.quality);
      const next = CINEMATIC_GEN_QUALITY_OPTIONS[(idx + 1 + CINEMATIC_GEN_QUALITY_OPTIONS.length) % CINEMATIC_GEN_QUALITY_OPTIONS.length];
      pickGenQuality(next);
      pickQuality(next === '1k' ? 'standard' : 'hd');
    } else if (provider === 'gpt') {
      const idx = CINEMATIC_GEN_QUALITY_OPTIONS.indexOf(gptState.resolution || '1k');
      const next = CINEMATIC_GEN_QUALITY_OPTIONS[(idx + 1 + CINEMATIC_GEN_QUALITY_OPTIONS.length) % CINEMATIC_GEN_QUALITY_OPTIONS.length];
      pickResolutionGpt(next);
      cinematicRevealState.gptQuality = false;
      cinematicRevealState.gptCount = false;
      cinematicRevealState.gptModeration = false;
    } else {
      return;
    }
    cinematicRevealState.quality = true;
    syncCinematicComposerUi();
  }

  function cycleCinematicRatio() {
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    const usingEditFlow = provider === 'google' && uploadedImages.length > 0;
    const currentRatio = provider === 'google'
      ? (usingEditFlow ? editState.ratio : genState.ratio)
      : provider === 'gpt'
        ? gptState.ratio
        : comfyState.ratio;
    const normalized = currentRatio === 'auto' ? '1:1' : currentRatio;
    const idx = CINEMATIC_RATIO_OPTIONS.indexOf(normalized);
    const next = CINEMATIC_RATIO_OPTIONS[(idx + 1 + CINEMATIC_RATIO_OPTIONS.length) % CINEMATIC_RATIO_OPTIONS.length];
    if (provider === 'google') {
      if (usingEditFlow) {
        pickRatioEdit(next);
      } else {
        pickRatioGen(next);
      }
    } else if (provider === 'gpt') {
      pickRatioGpt(next);
      cinematicRevealState.gptQuality = true;
      cinematicRevealState.gptCount = false;
      cinematicRevealState.gptModeration = false;
    } else {
      pickRatioComfy(next);
    }
    syncCinematicComposerUi();
  }

  function syncCinematicPromptState() {
    const prompt = document.getElementById('cinematicPrompt')?.value || '';
    const textarea = document.getElementById('cinematicPrompt');
    if (textarea) textarea.dataset.userEdited = prompt ? 'true' : '';
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    if (provider === 'google' && uploadedImages.length > 0) {
      setTextareaValue('editPrompt', prompt);
    } else if (provider === 'google') {
      setTextareaValue('genPrompt', prompt);
    } else if (provider === 'gpt') {
      setTextareaValue('gptPrompt', prompt);
    } else {
      setTextareaValue('comfyPrompt', prompt);
    }
    syncCinematicComposerUi();
  }

  function clearCurrentCinematicPrompt() {
    const textarea = document.getElementById('cinematicPrompt');
    if (!textarea) return;
    textarea.value = '';
    textarea.dataset.userEdited = '';
    syncCinematicPromptState();
    syncCinematicComposerUi();
    textarea.focus();
  }

  function setCinematicPromptText(nextPrompt) {
    const textarea = document.getElementById('cinematicPrompt');
    if (!textarea) return;
    textarea.value = String(nextPrompt || '').trim();
    textarea.dataset.userEdited = textarea.value ? 'true' : '';
    syncCinematicPromptState();
    textarea.focus();
  }

  function openClassicEditFromCinematic() {
    applyLayoutMode('classic', true);
    openGoogleSubview('edit');
    const prompt = document.getElementById('cinematicPrompt')?.value || '';
    if (prompt) setTextareaValue('editPrompt', prompt);
    setMainMenuOpen(false);
  }

  function submitCinematicComposer() {
    const promptEl = document.getElementById('cinematicPrompt');
    const prompt = (promptEl?.value || '').trim();
    const provider = normalizeCinematicProvider(currentCinematicProvider);
    if (!promptEl || !prompt) {
      if (promptEl) promptEl.focus();
      return;
    }

    syncCinematicPromptState();
    switchCinematicSection('records');

    if (provider === 'google') {
      if (uploadedImages.length > 0) {
        setTextareaValue('editPrompt', prompt);
        submitEdit();
        return;
      }

      setTextareaValue('genPrompt', prompt);
      submitGen();
      return;
    }

    if (provider === 'gpt') {
      setTextareaValue('gptPrompt', prompt);
      if (uploadedImages.length > 0) {
        submitGptEdit();
        return;
      }
      submitGpt();
      return;
    }

    applyLayoutMode('classic', true);
    switchTab('comfy');
    setTextareaValue('comfyPrompt', prompt);
    if (uploadedImages.length > 0 && typeof comfyImageData !== 'undefined') {
      comfyImageData = uploadedImages[0].base64;
      const preview = document.getElementById('comfyPreview');
      const placeholder = document.getElementById('comfyUploadPlaceholder');
      const removeBtn = document.getElementById('comfyRemoveImg');
      if (preview) {
        preview.src = comfyImageData;
        preview.style.display = 'block';
      }
      if (placeholder) placeholder.style.display = 'none';
      if (removeBtn) removeBtn.style.display = 'block';
    }
    showStatusMessage('已切到 ComfyUI 工作台，请先选择工作流。', 'info');
  }
