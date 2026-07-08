// Cinematic detail modal helpers
  let currentModalItem = null;
  let currentModalDownloadUrl = '';
  let currentCinematicViewerItem = null;
  let currentCinematicViewerDownloadUrl = '';
  let currentCinematicViewerScrollTop = 0;
  let currentCinematicViewerRequestToken = 0;

  function getCinematicViewerElements() {
    return {
      page: document.getElementById('cinematicViewerPage'),
      image: document.getElementById('cinematicViewerImg'),
      empty: document.getElementById('cinematicViewerEmpty'),
      loading: document.getElementById('cinematicViewerLoading'),
      status: document.getElementById('cinematicViewerStatus'),
      download: document.getElementById('cinematicViewerDownloadBtn'),
      edit: document.getElementById('cinematicViewerEditBtn')
    };
  }

  function setCinematicViewerStatus(text) {
    const { status } = getCinematicViewerElements();
    if (status) status.textContent = text || '';
  }

  function setCinematicViewerLoadingProgress(progress) {
    const { loading } = getCinematicViewerElements();
    if (!loading) return;
    const percent = Number.isFinite(progress) ? Math.max(0, Math.min(100, Math.round(progress))) : null;
    loading.classList.toggle('is-indeterminate', percent === null);
    loading.innerHTML = `
      <span>${percent === null ? '正在加载预览图...' : `正在加载预览图 ${percent}%`}</span>
      <i><b style="width:${percent === null ? 42 : percent}%"></b></i>
    `;
  }

  function setCinematicViewerActionState(hasOriginalImage) {
    const { download, edit } = getCinematicViewerElements();
    const shouldDisable = !hasOriginalImage;
    if (download) download.disabled = shouldDisable;
    if (edit) edit.disabled = shouldDisable;
  }

  function resetCinematicViewerStage() {
    const { image, empty, loading } = getCinematicViewerElements();
    if (image) {
      image.hidden = true;
      image.classList.remove('is-preview-blur');
      image.removeAttribute('src');
    }
    if (empty) {
      empty.hidden = true;
      empty.textContent = '这条记录暂时没有可查看的图片。';
    }
    if (loading) {
      loading.hidden = true;
      loading.classList.remove('is-indeterminate');
      loading.textContent = '正在加载预览图...';
    }
    setCinematicViewerActionState(false);
    setCinematicViewerStatus('ORIGINAL FRAME');
  }

  function setCinematicViewerOpen(open) {
    const { page } = getCinematicViewerElements();
    if (!page) return;
    page.classList.toggle('is-open', !!open);
    page.setAttribute('aria-hidden', open ? 'false' : 'true');
  }

  function showCinematicViewerImage(src, options = {}) {
    const { image, empty } = getCinematicViewerElements();
    if (!image || !src) return;
    image.src = src;
    image.classList.toggle('is-preview-blur', !!options.preview);
    image.hidden = false;
    if (empty) empty.hidden = true;
  }

  function showCinematicViewerEmpty(message) {
    const { image, empty, loading } = getCinematicViewerElements();
    if (image) {
      image.hidden = true;
      image.removeAttribute('src');
    }
    if (loading) loading.hidden = true;
    if (empty) {
      empty.hidden = false;
      empty.textContent = message || '这条记录暂时没有可查看的图片。';
    }
    setCinematicViewerActionState(false);
  }

  function getCinematicViewerDisplayUrl(item, originalUrl) {
    if (!item || !originalUrl) return originalUrl || '';
    if ((item.type === 'gpt' || item.type === 'gpt-edit') && item.output_file) {
      const filename = String(item.output_file || '');
      if (filename.toLowerCase().endsWith('.png')) {
        return `/gpt_outputs/${filename.replace(/\.png$/i, '_preview.png')}`;
      }
    }
    return originalUrl;
  }

  function openCinematicViewer(item) {
    if (!item) return;

    const { image, loading } = getCinematicViewerElements();
    const main = document.querySelector('.cinematic-main');
    const previewMeta = getHistoryThumbMeta(item);
    const originalUrl = getHistoryImageSource(item);
    const displayUrl = getCinematicViewerDisplayUrl(item, originalUrl);
    const previewUrl = previewMeta.src || previewMeta.fallback || displayUrl || originalUrl;
    const hasPreviewFallback = !!(previewUrl && displayUrl && previewUrl !== displayUrl);
    const requestToken = ++currentCinematicViewerRequestToken;

    currentCinematicViewerItem = item;
    currentCinematicViewerDownloadUrl = '';
    currentCinematicViewerScrollTop = main ? main.scrollTop : 0;

    closeCinematicMenus();
    if (document.getElementById('cinematicMenu')?.classList.contains('open')) {
      setCinematicQuickMenuOpen(false);
    }

    resetCinematicViewerStage();
    setCinematicViewerOpen(true);

    if (!originalUrl) {
      showCinematicViewerEmpty('这条记录没有可查看的图片。');
      setCinematicViewerStatus('NO IMAGE SOURCE');
      return;
    }

    currentCinematicViewerDownloadUrl = originalUrl;
    setCinematicViewerActionState(true);
    if (loading) loading.hidden = false;
    setCinematicViewerLoadingProgress(null);
    setCinematicViewerStatus(hasPreviewFallback ? 'LOADING 2K PREVIEW' : 'LOADING PREVIEW');

    if (hasPreviewFallback) {
      showCinematicViewerImage(previewUrl, { preview: true });
      if (loading) loading.hidden = false;

      const previewImage = new Image();
      previewImage.src = previewUrl;
      previewImage.onload = () => {
        if (requestToken !== currentCinematicViewerRequestToken || currentCinematicViewerDownloadUrl) return;
        showCinematicViewerImage(previewUrl, { preview: true });
        if (loading) loading.hidden = false;
        setCinematicViewerLoadingProgress(null);
        setCinematicViewerStatus('LOADING 2K PREVIEW');
      };
      previewImage.onerror = () => {
        if (requestToken !== currentCinematicViewerRequestToken || currentCinematicViewerDownloadUrl) return;
        if (loading) loading.hidden = false;
      };
    }

    const displayImage = new Image();
    displayImage.src = displayUrl;
    displayImage.onload = () => {
      if (requestToken !== currentCinematicViewerRequestToken) return;
      showCinematicViewerImage(displayUrl);
      if (loading) loading.hidden = true;
      clearHistoryAssetMissing(item);
      setCinematicViewerActionState(true);
      setCinematicViewerStatus('2K PREVIEW READY');
    };
    displayImage.onerror = () => {
      if (requestToken !== currentCinematicViewerRequestToken) return;
      if (loading) loading.hidden = true;
      if (hasPreviewFallback) {
        showCinematicViewerImage(previewUrl, { preview: true });
        setCinematicViewerStatus('THUMB PREVIEW · EXPORT ORIGINAL');
        setCinematicViewerActionState(true);
        return;
      }
      showCinematicViewerEmpty('预览图暂时加载失败，可以直接导出原图到 Telegram 查看。');
      setCinematicViewerActionState(true);
      setCinematicViewerStatus('PREVIEW FAILED · EXPORT ORIGINAL');
    };
  }

  function closeCinematicViewer() {
    const main = document.querySelector('.cinematic-main');
    currentCinematicViewerRequestToken += 1;
    setCinematicViewerOpen(false);
    resetCinematicViewerStage();
    currentCinematicViewerItem = null;
    currentCinematicViewerDownloadUrl = '';
    if (main) {
      requestAnimationFrame(() => {
        main.scrollTop = currentCinematicViewerScrollTop;
      });
    }
  }

  async function downloadCinematicViewerImage() {
    const url = currentCinematicViewerDownloadUrl;
    if (!url || !currentCinematicViewerItem?.output_file) {
      showStatusMessage('这条记录没有可导出的原图。', 'info');
      return;
    }

    const { download } = getCinematicViewerElements();
    const previousHtml = download ? download.innerHTML : '';
    if (download) {
      download.disabled = true;
      download.innerHTML = '<span class="cinematic-viewer-action-icon">...</span><span class="cinematic-viewer-action-label">SENDING</span>';
    }

    try {
      await api.json('/api/history/export_tg', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: currentCinematicViewerItem.task_id || '',
          type: currentCinematicViewerItem.type || '',
          output_file: currentCinematicViewerItem.output_file || '',
          prompt: currentCinematicViewerItem.prompt || ''
        })
      });
      showStatusMessage('原图已发送到 Telegram。', 'success');
    } catch (error) {
      showStatusMessage(error?.message || '发送到 Telegram 失败。', 'error');
    } finally {
      if (download) {
        download.disabled = false;
        download.innerHTML = previousHtml;
      }
    }
  }

  function continueEditFromCinematicViewer() {
    if (!currentCinematicViewerItem || !currentCinematicViewerDownloadUrl) {
      showStatusMessage('原图还没有准备好，暂时无法继续编辑。', 'info');
      return;
    }
    continueEditFromItem(currentCinematicViewerItem).then(() => {
      closeCinematicViewer();
      const textarea = document.getElementById('cinematicPrompt');
      if (textarea) textarea.focus();
    });
  }

  function openCinematicViewerOptions() {
    showStatusMessage('更多查看页操作待开发。', 'info');
  }

  function setModalDuration(item) {
    const durationEl = document.getElementById('modalDuration');
    if (!durationEl) return;
    if (item.duration) {
      const mins = Math.floor(item.duration / 60);
      const secs = item.duration % 60;
      durationEl.textContent = mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`;
      return;
    }
    durationEl.textContent = '—';
  }

  function setModalStatus(status) {
    const statusEl = document.getElementById('modalStatus');
    if (!statusEl) return;
    statusEl.classList.remove('success', 'failed', 'pending');
    if (status === 'success') {
      statusEl.textContent = '成功';
      statusEl.classList.add('success');
    } else if (status === 'failed') {
      statusEl.textContent = '失败';
      statusEl.classList.add('failed');
    } else {
      statusEl.textContent = '进行中';
      statusEl.classList.add('pending');
    }
  }

  function resetModalCopyButton() {
    const copyBtn = document.getElementById('copyPromptBtn');
    if (!copyBtn) return;
    copyBtn.textContent = '复制';
    copyBtn.classList.remove('copied');
  }

  function syncModalModelRow(item) {
    const modelEl = document.getElementById('modalModel');
    const modelRow = document.getElementById('modalModelRow');
    if (!modelEl || !modelRow) return;
    const model = item.params?.model || item.model || null;
    if (model) {
      modelEl.textContent = model;
      modelRow.style.display = 'flex';
      return;
    }
    modelRow.style.display = 'none';
  }

  function getModalStyleLabel(style) {
    const styleNameMap = {
      raw: 'Raw',
      king_hu: '胡金铨武侠风',
      shadow: '皮影戏风格',
      dunhuang: '敦煌壁画风',
      candlelight: '烛光电影感',
      real: '超写实摄影',
      '3d_info': '3D 信息图',
      sketchnote: '手绘笔记风'
    };
    return styleNameMap[style] || style;
  }

  function syncModalStyleRow(item) {
    const styleEl = document.getElementById('modalStyle');
    const styleRow = document.getElementById('modalStyleRow');
    if (!styleEl || !styleRow) return;
    const style = item.params?.style || item.style || null;
    if (style && style !== 'raw') {
      styleEl.textContent = getModalStyleLabel(style);
      styleRow.style.display = 'flex';
      return;
    }
    styleRow.style.display = 'none';
  }

  function resetModalImageStage() {
    const imgEl = document.getElementById('modalImg');
    const loadingEl = document.getElementById('modalImgLoading');
    const emptyEl = document.getElementById('modalImgEmpty');
    const hintEl = document.getElementById('modalImageHint');
    const stageEl = document.getElementById('modalStage');

    if (stageEl) {
      stageEl.dataset.hasImage = 'false';
      stageEl.onclick = null;
      stageEl.style.cursor = 'default';
      stageEl.title = '';
    }
    if (imgEl) {
      imgEl.style.display = 'none';
      imgEl.removeAttribute('src');
      imgEl.onclick = null;
      imgEl.style.cursor = 'default';
      imgEl.title = '';
    }
    if (loadingEl) {
      loadingEl.style.display = 'none';
      loadingEl.textContent = '正在加载原图...';
    }
    if (emptyEl) {
      emptyEl.style.display = 'flex';
      emptyEl.textContent = '这条记录暂时没有可预览的图片。';
    }
    if (hintEl) {
      hintEl.style.display = 'none';
      hintEl.textContent = '预览图 · 点击查看原图';
    }
  }
