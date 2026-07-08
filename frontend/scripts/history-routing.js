// History-to-composer routing and refill helpers
  function closeSidebarIfOpen() {
    const sb = document.getElementById('sidebar');
    if (sb && sb.classList.contains('open')) {
      setSidebarOpen(false);
    }
  }

  function openGoogleSubview(view) {
    closeGoogleDrawer();
    document.querySelectorAll('.drawer-option').forEach(el => {
      const label = (el.textContent || '').trim().toLowerCase();
      const targetLabel = view === 'gen' ? 'generate' : view;
      const isActive = label === targetLabel;
      el.classList.toggle('active', isActive);
    });
    activateGoogleTab(view);
  }

  function getActivePromptId() {
    if (currentLayoutMode === 'cinematic') return 'cinematicPrompt';
    if (document.getElementById('view-comfy')?.classList.contains('active')) return 'comfyPrompt';
    if (document.getElementById('view-gpt')?.classList.contains('active')) return 'gptPrompt';
    if (document.getElementById('view-edit')?.classList.contains('active')) return 'editPrompt';
    return 'genPrompt';
  }

  function setTextareaValue(textareaId, value) {
    const textarea = document.getElementById(textareaId);
    if (!textarea) return;
    textarea.value = value || '';
    updateCharCount(textareaId, getCounterId(textareaId));
  }

  function continueEditFromItem(item, options = {}) {
    const { notify = true, fallbackToParamsOnly = false } = options;
    if (!item) return Promise.resolve();
    const imageUrl = getHistoryImageSource(item);
    if (!imageUrl) {
      showStatusMessage('这条记录还没有可继续编辑的图片。', 'info');
      return Promise.resolve();
    }

    showStatusMessage('正在把作品带到编辑区...', 'info');
    return loadImageAsDataUrl(imageUrl)
      .then((base64) => {
        uploadedImages = [{ id: Date.now(), base64 }];
        renderGrid();
        openGoogleSubview('edit');
        setTextareaValue('editPrompt', item.prompt || '');
        if (item.params?.ratio) pickRatioEdit(item.params.ratio);
        hydrateCinematicPrompt(item.prompt || '');
        syncCinematicComposerUi();
        if (notify) {
          showStatusMessage('作品已带入 Edit，可以继续调整。', 'success');
        }
      })
      .catch((error) => {
        const failedByMissingFile = String(error?.message || '').includes('HTTP 404');
        if (failedByMissingFile) {
          markHistoryAssetMissing(item);
          if (fallbackToParamsOnly) {
            return refillGoogleEditWithoutImage(item, { notify });
          }
          showStatusMessage('这条记录的图片文件已丢失，暂时无法继续编辑。', 'error');
          return { missingAsset: true };
        }
        showStatusMessage('图片暂时没加载出来，稍后再试。', 'error');
      });
  }

  function refillGoogleEditWithoutImage(item, options = {}) {
    const { notify = true } = options;
    if (!item) return Promise.resolve({ missingAsset: true });

    markHistoryAssetMissing(item);
    if (uploadedImages.length) {
      uploadedImages = [];
      renderGrid();
    } else {
      syncCinematicComposerUi();
    }

    return applyGoogleEditItemToComposer(item).then(() => {
      if (notify) {
        showStatusMessage('原始图片文件已丢失，已回填提示词和参数，请重新上传参考图。', 'info');
      }
      return { missingAsset: true };
    });
  }

  function applyGptItemToComposer(item) {
    switchTab('gpt');
    setTextareaValue('gptPrompt', item.prompt || '');
    if (item.params?.ratio) pickRatioGpt(item.params.ratio);
    if (item.params?.resolution) pickResolutionGpt(item.params.resolution);
    if (item.params?.quality) pickQualityGpt(item.params.quality);
    if (item.params?.image_count) pickImageCountGpt(item.params.image_count);
    if (item.params?.moderation) pickModerationGpt(item.params.moderation);
    return Promise.resolve();
  }

  function applyComfyItemToComposer(item) {
    switchTab('comfy');
    setTextareaValue('comfyPrompt', item.prompt || '');
    if (item.params?.ratio) pickRatioComfy(item.params.ratio);
    if (item.params?.workflow) {
      pickComfyWorkflow(item.params.workflow);
    }
    return loadComfyWorkflows().then(() => {
      const sel = document.getElementById('comfyWorkflow');
      if (sel && item.params?.workflow) sel.value = item.params.workflow;
    });
  }

  function applyGoogleEditItemToComposer(item) {
    openGoogleSubview('edit');
    setTextareaValue('editPrompt', item.prompt || '');
    if (item.params?.ratio) pickRatioEdit(item.params.ratio);
    if (item.params?.feature) pickFeature(item.params.feature);
    if (item.params?.quality) pickQuality(item.params.quality);
    if (item.params?.model) pickModel('edit', item.params.model);
    return Promise.resolve();
  }

  function applyGoogleGenItemToComposer(item) {
    openGoogleSubview('gen');
    setTextareaValue('genPrompt', item.prompt || '');
    if (item.params?.style) pickStyle(item.params.style);
    if (item.params?.ratio) pickRatioGen(item.params.ratio);
    if (item.params?.quality) pickGenQuality(item.params.quality);
    if (item.params?.model) pickModel('gen', item.params.model);
    return Promise.resolve();
  }

  function applyItemToComposer(item) {
    if (!item) return Promise.resolve();
    if (item.type === 'gpt' || item.type === 'gpt-edit') return applyGptItemToComposer(item);
    if (item.type === 'comfy') return applyComfyItemToComposer(item);
    if (item.type === 'google-edit') return applyGoogleEditItemToComposer(item);
    return applyGoogleGenItemToComposer(item);
  }

  function syncCinematicStyleStateFromHistory(styleValue) {
    const normalizedStyle = String(styleValue || 'raw').trim() || 'raw';
    if (normalizedStyle === 'raw') {
      cinematicStylePinned = false;
      cinematicPinnedStyleId = '';
      cinematicActiveStyleLabel = '';
      pickStyle('raw');
      return;
    }

    const library = getResolvedCinematicStyleLibrary();
    const matched = library.find((item) => item.id === normalizedStyle || item.engineStyle === normalizedStyle);
    cinematicStylePinned = true;
    cinematicPinnedStyleId = matched?.id || '';
    cinematicActiveStyleLabel = getCinematicStyleChipText(
      matched?.badge || getCinematicStyleBadgeLabel(normalizedStyle)
    );
    pickStyle(normalizedStyle);
  }

  function syncCinematicComposerFromHistoryItem(item) {
    if (!item) return;

    const ratio = item.params?.ratio || null;

    if (item.type === 'gpt' || item.type === 'gpt-edit') {
      currentCinematicProvider = 'gpt';
      cinematicRevealState.provider = true;
      cinematicRevealState.model = false;
      cinematicRevealState.quality = true;
      cinematicRevealState.gptQuality = true;
      cinematicRevealState.gptCount = item.type === 'gpt';
      cinematicRevealState.gptModeration = true;
      if (ratio) pickRatioGpt(ratio);
      if (item.params?.resolution) pickResolutionGpt(item.params.resolution);
      if (item.params?.quality) pickQualityGpt(item.params.quality);
      if (item.params?.image_count) pickImageCountGpt(item.params.image_count);
      if (item.params?.moderation) pickModerationGpt(item.params.moderation);
      return;
    }

    if (item.type === 'comfy') {
      currentCinematicProvider = 'comfyui';
      cinematicRevealState.provider = true;
      cinematicRevealState.model = false;
      cinematicRevealState.quality = false;
      if (ratio) pickRatioComfy(ratio);
      if (item.params?.workflow) pickComfyWorkflow(item.params.workflow);
      return;
    }

    if (item.type !== 'google-gen' && item.type !== 'google-edit') return;

    currentCinematicProvider = 'google';
    cinematicRevealState.provider = true;
    cinematicRevealState.model = true;
    cinematicRevealState.quality = true;

    const model = item.params?.model || null;

    if (model) {
      pickModel('gen', model);
      pickModel('edit', model);
    }

    if (item.type === 'google-edit') {
      const editQuality = item.params?.quality || 'hd';
      pickQuality(editQuality);
      pickGenQuality(editQuality === 'standard' ? '1k' : '2k');
      if (ratio) {
        pickRatioEdit(ratio);
        pickRatioGen(ratio);
      }
      syncCinematicStyleStateFromHistory('raw');
      return;
    }

    const genQuality = item.params?.quality || null;
    if (genQuality) {
      pickGenQuality(genQuality);
      pickQuality(genQuality === '1k' ? 'standard' : 'hd');
    }
    if (ratio) {
      pickRatioGen(ratio);
      pickRatioEdit(ratio);
    }
    syncCinematicStyleStateFromHistory(item.params?.style || 'raw');
  }

  function retryCinematicHistoryItem(item) {
    if (!item) return;
    const wantsEdit = item.type === 'google-edit' && getHistoryImageSource(item);
    const runner = wantsEdit
      ? (isHistoryAssetMissing(item)
        ? refillGoogleEditWithoutImage(item, { notify: false })
        : continueEditFromItem(item, { notify: false, fallbackToParamsOnly: true }))
      : applyItemToComposer(item);
    return Promise.resolve(runner).then((result) => {
      const missingAsset = !!result?.missingAsset;
      syncCinematicComposerFromHistoryItem(item);
      hydrateCinematicPrompt(item.prompt || '');
      switchCinematicSection('records');
      syncCinematicComposerUi();
      showStatusMessage(
        missingAsset
          ? '原始图片文件已丢失，已回填提示词和参数，请重新上传参考图。'
          : '参数已经带回新布局。',
        missingAsset ? 'info' : 'success'
      );
    });
  }

  function copyHistoryPromptToCinematic(item) {
    if (!item?.prompt) {
      showStatusMessage('这条记录没有提示词可复制。', 'info');
      return;
    }
    hydrateCinematicPrompt(item.prompt);
    switchCinematicSection('records');
    syncCinematicComposerUi();
    copyTextToClipboard(item.prompt, '提示词已复制');
  }

  function getHistoryImageSource(item) {
    if (!item || !item.output_file) return '';
    if (item.type === 'gpt' || item.type === 'gpt-edit') return '/gpt_outputs/' + item.output_file;
    if (item.type === 'comfy') {
      const comfyImage = item.params?.comfy_image || {};
      if (comfyImage.filename) {
        const q = new URLSearchParams({
          filename: comfyImage.filename,
          subfolder: comfyImage.subfolder || '',
          type: comfyImage.type || 'output'
        });
        return '/api/comfy/image?' + q.toString();
      }
      return '';
    }
    return '/image/' + item.output_file;
  }

  function loadImageAsDataUrl(url) {
    return fetch(url)
      .then(resp => {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.blob();
      })
      .then(blob => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      }));
  }
