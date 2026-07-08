// Detail modal rendering and clipboard helpers
  function openDetailModal(item) {
    if (currentLayoutMode === 'cinematic') {
      openCinematicViewer(item);
      return;
    }

    currentModalItem = item;
    currentModalDownloadUrl = getHistoryImageSource(item);
    const mo = document.getElementById('detailModal');
    const imgEl = document.getElementById('modalImg');
    const loadingEl = document.getElementById('modalImgLoading');
    const emptyEl = document.getElementById('modalImgEmpty');
    const hintEl = document.getElementById('modalImageHint');
    const stageEl = document.getElementById('modalStage');
    updateModalActions(item);
    mo.classList.toggle('is-cinematic', currentLayoutMode === 'cinematic');

    document.getElementById('modalTitle').textContent = currentLayoutMode === 'cinematic' ? '作品预览' : '任务详情';
    document.getElementById('modalType').textContent = item.type;
    document.getElementById('modalTime').textContent = new Date(item.timestamp * 1000).toLocaleString();
    setModalDuration(item);
    setModalStatus(item.status);
    document.getElementById('modalPrompt').textContent = item.prompt;
    resetModalCopyButton();
    syncModalModelRow(item);
    syncModalStyleRow(item);
    resetModalImageStage();
    imgEl.onerror = null;

    if (item.output_file) {
      let path = '';
      let thumbPath = '';
      let previewPath = '';
      let previewReady = false;

      const showMissingAssetState = () => {
        markHistoryAssetMissing(item);
        imgEl.removeAttribute('src');
        imgEl.style.display = 'none';
        imgEl.onclick = null;
        if (stageEl) stageEl.onclick = null;
        loadingEl.style.display = 'none';
        updateModalActions(item);
        if (emptyEl) {
          emptyEl.textContent = '原始图片文件已丢失，当前仅保留这条记录的文字与参数。';
          emptyEl.style.display = 'flex';
        }
        if (hintEl) hintEl.style.display = 'none';
        if (stageEl) stageEl.dataset.hasImage = 'false';
      };

      const canToggleOriginal = () => !!(path && previewPath && path !== previewPath);
      const setModalImage = (src) => {
        if (!imgEl || !src) return;
        imgEl.src = src;
        imgEl.style.display = 'block';
        if (emptyEl) emptyEl.style.display = 'none';
        if (stageEl) stageEl.dataset.hasImage = 'true';
      };
      imgEl.onerror = showMissingAssetState;

      if (item.type === 'gpt' || item.type === 'gpt-edit') {
        path = '/gpt_outputs/' + item.output_file;
        thumbPath = '/gpt_outputs/' + item.output_file.replace('.png', '_thumb.png');
        loadingEl.style.display = 'inline-flex';
        const testImg = new Image();
        testImg.src = thumbPath;
        testImg.onload = () => {
          previewPath = thumbPath;
          previewReady = true;
          setModalImage(thumbPath);
          showPreview();
        };
        testImg.onerror = () => {
          previewPath = path;
          previewReady = true;
          setModalImage(path);
          showPreview();
        };
      } else if (item.type.startsWith('google')) {
        path = '/image/' + item.output_file;
        thumbPath = '/google_outputs/thumb_' + item.output_file;
        loadingEl.style.display = 'inline-flex';
        const testImg = new Image();
        testImg.src = thumbPath;
        testImg.onload = () => {
          previewPath = thumbPath;
          previewReady = true;
          setModalImage(thumbPath);
          showPreview();
        };
        testImg.onerror = () => {
          previewPath = path;
          previewReady = true;
          setModalImage(path);
          showPreview();
        };
      } else if (item.type === 'comfy') {
        const comfyImage = item.params?.comfy_image || {};
        if (comfyImage.filename) {
          const q = new URLSearchParams({
            filename: comfyImage.filename,
            subfolder: comfyImage.subfolder || '',
            type: comfyImage.type || 'output'
          });
          path = '/api/comfy/image?' + q.toString();
          thumbPath = path;
        }
        if (path) {
          previewPath = path;
          previewReady = true;
          setModalImage(path);
        } else {
          imgEl.style.display = 'none';
        }
      } else {
        path = '/image/' + item.output_file;
        previewPath = path;
        previewReady = true;
        setModalImage(path);
      }

      currentModalDownloadUrl = path || currentModalDownloadUrl;

      let showingOriginal = false;
      let originalLoaded = false;
      const handleStageToggle = (event) => {
        if (event?.target?.closest?.('#modalCinematicActions')) return;
        if (!showingOriginal) {
          loadOriginal();
        } else {
          showPreview();
        }
      };

      const syncToggleBinding = () => {
        const canToggle = canToggleOriginal();
        imgEl.onclick = canToggle ? handleStageToggle : null;
        if (stageEl) stageEl.onclick = canToggle ? handleStageToggle : null;
      };

      const showPreview = () => {
        setModalImage(previewPath);
        loadingEl.style.display = 'none';
        showingOriginal = false;
        if (hintEl) {
          hintEl.style.display = 'inline-flex';
          hintEl.textContent = canToggleOriginal() ? '预览图 · 点击查看原图' : '当前图像预览';
        }
        imgEl.title = canToggleOriginal() ? '点击查看原图' : '';
        imgEl.style.cursor = canToggleOriginal() ? 'pointer' : 'default';
        if (stageEl) {
          stageEl.title = canToggleOriginal() ? '点击查看原图' : '';
          stageEl.style.cursor = canToggleOriginal() ? 'pointer' : 'default';
        }
        syncToggleBinding();
      };

      const loadOriginal = () => {
        if (!path || !canToggleOriginal()) {
          showPreview();
          return;
        }
        if (originalLoaded) {
          setModalImage(path);
          loadingEl.style.display = 'none';
          showingOriginal = true;
          if (hintEl) hintEl.textContent = '原图已显示 · 点击返回预览';
          imgEl.title = '点击返回预览图';
          imgEl.style.cursor = 'pointer';
          return;
        }
        loadingEl.style.display = 'block';
        const originalImg = new Image();
        originalImg.src = path;
        originalImg.onload = () => {
          originalLoaded = true;
          showingOriginal = true;
          setModalImage(path);
          loadingEl.style.display = 'none';
          if (hintEl) {
            hintEl.style.display = 'inline-flex';
            hintEl.textContent = '原图已显示 · 点击返回预览';
          }
          imgEl.title = '点击返回预览图';
          imgEl.style.cursor = 'pointer';
          if (stageEl) {
            stageEl.title = '点击返回预览图';
            stageEl.style.cursor = 'pointer';
          }
        };
        originalImg.onerror = () => {
          if (previewPath && previewPath !== path) {
            loadingEl.textContent = '原图加载失败';
            setTimeout(() => {
              loadingEl.style.display = 'none';
              loadingEl.textContent = '正在加载原图...';
            }, 1500);
            return;
          }
          showMissingAssetState();
        };
      };

      if (previewReady) {
        showPreview();
      }
      syncToggleBinding();
    } else {
      imgEl.style.display = 'none';
      if (emptyEl) emptyEl.style.display = 'flex';
      if (hintEl) hintEl.style.display = 'none';
    }

    const errEl = document.getElementById('modalError');
    if (item.error) {
      errEl.textContent = '错误信息: ' + item.error;
      errEl.style.display = 'block';
    } else {
      errEl.style.display = 'none';
    }

    mo.classList.add('open');
  }

  function copyModalPrompt() {
    const promptEl = document.getElementById('modalPrompt');
    const text = (promptEl?.textContent || '').trim();
    if (!text) {
      alert('暂无提示词');
      return;
    }

    const btn = document.getElementById('copyPromptBtn');
    const markCopied = () => {
      if (!btn) return;
      const prev = btn.textContent;
      btn.textContent = '已复制';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = prev || '复制';
        btn.classList.remove('copied');
      }, 1200);
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(markCopied).catch(() => fallbackCopy(text, markCopied));
    } else {
      fallbackCopy(text, markCopied);
    }
  }

  function fallbackCopy(text, done) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
    if (done) done();
  }

  function copyTextToClipboard(text, successMessage = '已复制') {
    if (!text) {
      showStatusMessage('暂无可复制内容。', 'info');
      return;
    }
    const done = () => showStatusMessage(successMessage, 'success');
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }
