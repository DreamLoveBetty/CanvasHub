// Detail modal button actions
  function updateModalActions(item) {
    const retryBtn = document.getElementById('modalRetryBtn');
    const reuseBtn = document.getElementById('modalReuseBtn');
    const editBtn = document.getElementById('modalEditBtn');
    const cinematicActions = document.getElementById('modalCinematicActions');
    const downloadBtn = document.getElementById('modalDownloadBtn');
    const cinematicEditBtn = document.getElementById('modalCinematicEditBtn');
    if (!retryBtn || !reuseBtn || !editBtn || !cinematicActions || !downloadBtn || !cinematicEditBtn) return;
    const hasImage = !!getHistoryImageSource(item) && !isHistoryAssetMissing(item);

    const labels = {
      'google-gen': '回填到 Generate',
      'google-edit': '回填到 Edit',
      'gpt': '回填到 GPT',
      'gpt-edit': '回填到 GPT Edit',
      'comfy': '回填到 Comfy'
    };
    retryBtn.textContent = labels[item.type] || '回填重试';
    reuseBtn.classList.toggle('is-hidden', !item.prompt);
    editBtn.classList.toggle('is-hidden', !hasImage);
    cinematicActions.classList.toggle('is-visible', currentLayoutMode === 'cinematic');
    downloadBtn.classList.toggle('is-hidden', !hasImage);
    cinematicEditBtn.classList.toggle('is-hidden', !hasImage);
  }

  function closeModal() {
    const modal = document.getElementById('detailModal');
    modal.classList.remove('open', 'is-cinematic');
    const imgEl = document.getElementById('modalImg');
    const loadingEl = document.getElementById('modalImgLoading');
    const hintEl = document.getElementById('modalImageHint');
    const emptyEl = document.getElementById('modalImgEmpty');
    if (imgEl) {
      imgEl.onclick = null;
      imgEl.style.cursor = 'default';
      imgEl.title = '';
    }
    if (loadingEl) {
      loadingEl.style.display = 'none';
      loadingEl.textContent = '正在加载原图...';
    }
    if (hintEl) hintEl.style.display = 'none';
    if (emptyEl) emptyEl.style.display = 'none';
    currentModalItem = null;
    currentModalDownloadUrl = '';
  }

  function downloadModalImage() {
    const url = currentModalDownloadUrl || getHistoryImageSource(currentModalItem);
    if (!url) {
      showStatusMessage('这条记录没有可下载的图片。', 'info');
      return;
    }
    const link = document.createElement('a');
    link.href = url;
    link.download = currentModalItem?.output_file || 'image.png';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function retryFromModal() {
    if (!currentModalItem) return;
    const item = currentModalItem;
    closeModal();
    const task = currentLayoutMode === 'cinematic' ? Promise.resolve(retryCinematicHistoryItem(item)) : applyItemToComposer(item);
    Promise.resolve(task).then(() => {
      closeSidebarIfOpen();
      if (currentLayoutMode !== 'cinematic') {
        showStatusMessage('参数已经带回对应模块。', 'success');
      }
    });
  }

  function reusePromptFromModal() {
    if (!currentModalItem || !currentModalItem.prompt) return;
    const promptId = getActivePromptId();
    setTextareaValue(promptId, currentModalItem.prompt);
    if (promptId === 'cinematicPrompt') {
      switchCinematicSection('records');
      syncCinematicPromptState();
      syncCinematicComposerUi();
    }
    closeModal();
    closeSidebarIfOpen();
    const textarea = document.getElementById(promptId);
    if (textarea) textarea.focus();
    showStatusMessage('提示词已经带回当前模块。', 'success');
  }

  function continueEditFromModal() {
    if (!currentModalItem) return;
    continueEditFromItem(currentModalItem).then(() => {
      closeModal();
      closeSidebarIfOpen();
      const textarea = document.getElementById('editPrompt');
      if (textarea) textarea.focus();
    });
  }
