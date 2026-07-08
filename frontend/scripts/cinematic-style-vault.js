// Cinematic discover space and style vault
  function getCinematicStyleBadgeLabel(style) {
    const styleBadgeMap = {
      raw: 'Raw',
      real: 'Real',
      king_hu: 'King',
      shadow: 'Shadow',
      dunhuang: 'Dunhuang',
      candlelight: 'Candle',
      '3d_info': '3D',
      sketchnote: 'Sketch'
    };
    return styleBadgeMap[style] || getModalStyleLabel(style);
  }

  function getResolvedCinematicStyleLibrary() {
    return DEFAULT_CINEMATIC_STYLE_LIBRARY.map((item) => ({
      ...item,
      ...(cinematicStyleOverrides[item.id] || {}),
      builtin: true
    })).concat(
      (cinematicCustomStyles || []).map((item) => ({
        ...item,
        builtin: false
      }))
    );
  }

  function getCinematicStyleChipText(label) {
    const trimmed = String(label || '').trim();
    if (!trimmed) return '';
    if (/[\u4e00-\u9fff]/.test(trimmed)) return trimmed.slice(0, 4);
    const firstWord = trimmed.split(/\s+/)[0] || trimmed;
    return firstWord.slice(0, 10);
  }

  function getDefaultCinematicStyleEditorData() {
    const currentPrompt = (document.getElementById('cinematicPrompt')?.value || '').trim();
    return {
      title: '',
      description: '',
      promptTemplate: currentPrompt,
      engineStyle: genState.style || 'raw',
      model: genState.model || CINEMATIC_MODEL_MAP.fast,
      quality: genState.quality || '2k',
      ratio: genState.ratio || '1:1',
      status: '自定义收藏'
    };
  }

  function fillCinematicStyleEditor(data, mode = 'create') {
    const titleEl = document.getElementById('cinematicStyleEditorTitle');
    const saveBtn = document.getElementById('cinematicStyleEditorSaveBtn');
    const nameEl = document.getElementById('cinematicStyleEditorName');
    const descEl = document.getElementById('cinematicStyleEditorDesc');
    const promptEl = document.getElementById('cinematicStyleEditorPrompt');
    const engineEl = document.getElementById('cinematicStyleEditorEngine');
    const modelEl = document.getElementById('cinematicStyleEditorModel');
    const qualityEl = document.getElementById('cinematicStyleEditorQuality');
    const ratioEl = document.getElementById('cinematicStyleEditorRatio');

    if (titleEl) titleEl.textContent = mode === 'edit' ? '编辑风格' : '创建风格';
    if (saveBtn) {
      saveBtn.textContent = mode === 'edit' ? '保存修改' : '保存风格';
      saveBtn.disabled = false;
    }
    if (nameEl) nameEl.value = data.title || '';
    if (descEl) descEl.value = data.description || '';
    if (promptEl) promptEl.value = data.promptTemplate || '';
    if (engineEl) engineEl.value = data.engineStyle || 'raw';
    if (modelEl) modelEl.value = data.model || CINEMATIC_MODEL_MAP.fast;
    if (qualityEl) qualityEl.value = data.quality || '2k';
    if (ratioEl) ratioEl.value = data.ratio || '1:1';
  }

  function openCinematicStyleEditor(mode = 'create', styleId = null) {
    const overlay = document.getElementById('cinematicStyleEditorOverlay');
    if (!overlay) return;

    currentCinematicStyleEditorId = null;
    currentCinematicStyleEditorBuiltin = false;

    if (mode === 'edit' && styleId) {
      const target = getResolvedCinematicStyleLibrary().find(item => item.id === styleId);
      if (!target) return;
      currentCinematicStyleEditorId = styleId;
      currentCinematicStyleEditorBuiltin = !!target.builtin;
      fillCinematicStyleEditor(target, 'edit');
    } else {
      fillCinematicStyleEditor(getDefaultCinematicStyleEditorData(), 'create');
    }

    overlay.classList.add('is-open');
    document.body.classList.add('settings-open');
    requestAnimationFrame(() => {
      document.getElementById('cinematicStyleEditorName')?.focus();
    });
  }

  function closeCinematicStyleEditor() {
    const overlay = document.getElementById('cinematicStyleEditorOverlay');
    if (!overlay) return;
    overlay.classList.remove('is-open');
    document.body.classList.remove('settings-open');
    currentCinematicStyleEditorId = null;
    currentCinematicStyleEditorBuiltin = false;
  }

  function handleCinematicStyleEditorOverlay(event) {
    if (event.target === event.currentTarget) {
      closeCinematicStyleEditor();
    }
  }

  function readCinematicStyleEditorForm() {
    return {
      title: (document.getElementById('cinematicStyleEditorName')?.value || '').trim(),
      description: (document.getElementById('cinematicStyleEditorDesc')?.value || '').trim(),
      promptTemplate: (document.getElementById('cinematicStyleEditorPrompt')?.value || '').trim(),
      engineStyle: document.getElementById('cinematicStyleEditorEngine')?.value || 'raw',
      model: document.getElementById('cinematicStyleEditorModel')?.value || CINEMATIC_MODEL_MAP.fast,
      quality: document.getElementById('cinematicStyleEditorQuality')?.value || '2k',
      ratio: document.getElementById('cinematicStyleEditorRatio')?.value || '1:1'
    };
  }

  function maybeApplyCinematicStyleTemplate(style, options = {}) {
    const textarea = document.getElementById('cinematicPrompt');
    if (!textarea) return false;

    const nextTemplate = String(style?.promptTemplate || '').trim();
    if (!nextTemplate) return false;

    const currentPrompt = String(textarea.value || '').trim();
    const previousTemplate = String(options.previousTemplate || '').trim();
    const shouldApply = !currentPrompt || (!!previousTemplate && currentPrompt === previousTemplate);
    if (!shouldApply) return false;

    textarea.value = nextTemplate;
    syncCinematicPromptState();
    return true;
  }

  async function saveCinematicStyleEditor() {
    const form = readCinematicStyleEditorForm();
    if (!form.title) {
      document.getElementById('cinematicStyleEditorName')?.focus();
      return;
    }
    const existingStyle = currentCinematicStyleEditorId
      ? getResolvedCinematicStyleLibrary().find(item => item.id === currentCinematicStyleEditorId)
      : null;
    const previousTemplate = existingStyle?.promptTemplate || '';
    const saveBtn = document.getElementById('cinematicStyleEditorSaveBtn');

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中...';
    }

    const payload = {
      title: form.title,
      description: form.description || '一张新的自定义风格卡。',
      promptTemplate: form.promptTemplate,
      engineStyle: form.engineStyle,
      model: form.model,
      quality: form.quality,
      ratio: form.ratio,
      badge: getCinematicStyleChipText(form.title),
      status: currentCinematicStyleEditorBuiltin ? '系统风格' : '自定义收藏'
    };

    if (currentCinematicStyleEditorId) {
      if (currentCinematicStyleEditorBuiltin) {
        cinematicStyleOverrides[currentCinematicStyleEditorId] = {
          ...(cinematicStyleOverrides[currentCinematicStyleEditorId] || {}),
          ...payload
        };
      } else {
        cinematicCustomStyles = cinematicCustomStyles.map((item) => (
          item.id === currentCinematicStyleEditorId ? { ...item, ...payload } : item
        ));
      }
      showStatusMessage('风格卡已更新。', 'success');
    } else {
      cinematicCustomStyles.push({
        id: `custom_${Date.now()}`,
        ...payload
      });
      cinematicStyleSearch = '';
      showStatusMessage('新风格已加入发现空间。', 'success');
    }

    if (currentCinematicStyleEditorId && cinematicPinnedStyleId === currentCinematicStyleEditorId && cinematicStylePinned) {
      cinematicActiveStyleLabel = getCinematicStyleChipText(payload.badge || payload.title);
      pickModel('gen', payload.model || CINEMATIC_MODEL_MAP.fast);
      pickModel('edit', payload.model || CINEMATIC_MODEL_MAP.fast);
      pickGenQuality(payload.quality || '2k');
      pickQuality((payload.quality || '2k') === '1k' ? 'standard' : 'hd');
      pickRatioGen(payload.ratio || '1:1');
      pickRatioEdit(payload.ratio || '1:1');
      pickStyle(payload.engineStyle || 'raw');
      maybeApplyCinematicStyleTemplate(payload, { previousTemplate });
    }

    renderCinematicStyleVault();
    saveUiSettings();
    closeCinematicStyleEditor();
  }

  function renderCinematicStyleVault() {
    const grid = document.getElementById('cinematicStyleGrid');
    const empty = document.getElementById('cinematicStyleEmpty');
    const searchInput = document.getElementById('cinematicStyleSearch');
    if (!grid || !empty) return;
    if (searchInput && searchInput.value !== cinematicStyleSearch) {
      searchInput.value = cinematicStyleSearch;
    }

    const keyword = String(cinematicStyleSearch || '').trim().toLowerCase();
    const styles = getResolvedCinematicStyleLibrary().filter((item) => {
      if (!keyword) return true;
      return [item.title, item.description, item.badge, item.status, item.promptTemplate]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(keyword));
    });

    grid.innerHTML = '';
    empty.hidden = styles.length > 0;
    grid.hidden = styles.length === 0;

    styles.forEach((item) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'cinematic-style-card';
      card.dataset.style = item.engineStyle || item.id || 'raw';
      card.addEventListener('click', () => applyCinematicDiscoverStyle(item.id));

      const preview = document.createElement('div');
      preview.className = 'cinematic-style-preview';
      const tag = document.createElement('span');
      tag.className = 'cinematic-style-tag';
      tag.textContent = item.badge || getCinematicStyleBadgeLabel(item.engineStyle || item.id);
      preview.appendChild(tag);

      const title = document.createElement('strong');
      title.textContent = item.title;
      const desc = document.createElement('span');
      desc.textContent = item.description;

      const foot = document.createElement('div');
      foot.className = 'cinematic-style-foot';
      const status = document.createElement('em');
      status.className = 'cinematic-style-status';
      status.textContent = item.status || (item.builtin ? '系统风格' : '自定义收藏');
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'cinematic-style-edit';
      editBtn.textContent = '✎';
      editBtn.title = '编辑风格';
      editBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        editCinematicDiscoverStyle(item.id);
      });
      foot.appendChild(status);
      foot.appendChild(editBtn);

      card.appendChild(preview);
      card.appendChild(title);
      card.appendChild(desc);
      card.appendChild(foot);
      grid.appendChild(card);
    });
  }

  function handleCinematicStyleSearch(value) {
    cinematicStyleSearch = value || '';
    renderCinematicStyleVault();
  }

  function createCinematicDiscoverStyle() {
    openCinematicStyleEditor('create');
  }

  function editCinematicDiscoverStyle(styleId) {
    openCinematicStyleEditor('edit', styleId);
  }

  function clearPinnedCinematicStyle() {
    cinematicStylePinned = false;
    cinematicPinnedStyleId = '';
    cinematicActiveStyleLabel = '';
    pickStyle('raw');
    syncCinematicComposerUi();
    saveUiSettings();
    showStatusMessage('风格已清除。', 'info');
  }

  function applyCinematicDiscoverStyle(styleId) {
    const styles = getResolvedCinematicStyleLibrary();
    const target = styles.find(item => item.id === styleId);
    if (!target) return;
    currentCinematicProvider = 'google';
    cinematicStylePinned = true;
    cinematicPinnedStyleId = styleId;
    cinematicActiveStyleLabel = getCinematicStyleChipText(target.badge || target.title);
    cinematicRevealState.provider = true;
    cinematicRevealState.model = true;
    cinematicRevealState.quality = true;
    pickModel('gen', target.model || CINEMATIC_MODEL_MAP.fast);
    pickModel('edit', target.model || CINEMATIC_MODEL_MAP.fast);
    pickGenQuality(target.quality || '2k');
    pickQuality((target.quality || '2k') === '1k' ? 'standard' : 'hd');
    pickRatioGen(target.ratio || '1:1');
    pickRatioEdit(target.ratio || '1:1');
    pickStyle(target.engineStyle || target.id || 'raw');
    maybeApplyCinematicStyleTemplate(target);
    switchCinematicSection('records');
    saveUiSettings();
    showStatusMessage(`已切换到 ${target.title}，继续在创作区输入提示词即可。`, 'success');
  }
