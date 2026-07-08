// Reference image grid and prompt helpers
  const refGrid = document.getElementById('refGrid');

  function renderGrid() {
    refGrid.innerHTML = '';
    for (let i = 0; i < MAX_IMGS; i++) {
      const imgData = uploadedImages[i];
      const slot = document.createElement('div');
      slot.className = 'ref-slot';
      slot.dataset.idx = i;

      const badge = document.createElement('div');
      badge.className = 'num-badge';
      badge.textContent = i + 1;
      slot.appendChild(badge);

      if (imgData) {
        slot.innerHTML += `
          <img src="${imgData.base64}" class="ref-img">
          <div class="ref-remove" onclick="removeImg(${i}, event)">×</div>
        `;
      } else {
        slot.innerHTML += `
          <div class="plus">+</div>
          <div class="label">上传</div>
        `;
        slot.onclick = () => document.getElementById('fileInput').click();
      }
      refGrid.appendChild(slot);
    }
    document.getElementById('imgCount').textContent = `${uploadedImages.length}/${MAX_IMGS} 张`;
    syncCinematicReferenceState();
    syncCinematicComposerUi();
  }

  function handleFiles(files) {
    if (!files.length) return;
    const remain = MAX_IMGS - uploadedImages.length;
    const count = Math.min(files.length, remain);
    if (count <= 0) {
      alert('Max 8 images.');
      return;
    }

    Array.from(files).slice(0, count).forEach(file => {
      compressImage(file, 2048, 0.85).then(base64 => {
        uploadedImages.push({ id: Date.now() + Math.random(), base64: base64 });
        renderGrid();
      }).catch(err => {
        console.error('Compression failed', err);
        alert('Image processing failed');
      });
    });
    document.getElementById('fileInput').value = '';
  }

  function compressImage(file, maxWidth, quality) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = event => {
        const img = new Image();
        img.src = event.target.result;
        img.onload = () => {
          let w = img.width;
          let h = img.height;

          if (w > maxWidth || h > maxWidth) {
            if (w > h) {
              h = Math.round((h * maxWidth) / w);
              w = maxWidth;
            } else {
              w = Math.round((w * maxWidth) / h);
              h = maxWidth;
            }
          }

          const canvas = document.createElement('canvas');
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, w, h);

          resolve(canvas.toDataURL('image/jpeg', quality));
        };
        img.onerror = error => reject(error);
      };
      reader.onerror = error => reject(error);
    });
  }

  function removeImg(idx, e) {
    e.stopPropagation();
    uploadedImages.splice(idx, 1);
    renderGrid();
  }

  function removeLatestCinematicReference() {
    if (!uploadedImages.length) return false;
    uploadedImages.pop();
    renderGrid();
    return true;
  }

  function clearAllCinematicReferences() {
    if (!uploadedImages.length) return false;
    uploadedImages = [];
    renderGrid();
    return true;
  }

  function cancelCinematicRefClearHold() {
    if (cinematicRefClearHoldTimer) {
      clearTimeout(cinematicRefClearHoldTimer);
      cinematicRefClearHoldTimer = null;
    }
    document.getElementById('cinematicRefClearBtn')?.classList.remove('is-holding');
  }

  function startCinematicRefClearHold(event) {
    if (event) event.preventDefault();
    if (!uploadedImages.length) return;
    cancelCinematicRefClearHold();
    cinematicRefClearHandled = false;
    document.getElementById('cinematicRefClearBtn')?.classList.add('is-holding');
    cinematicRefClearHoldTimer = window.setTimeout(() => {
      cinematicRefClearHandled = clearAllCinematicReferences();
      cancelCinematicRefClearHold();
      if (cinematicRefClearHandled) {
        showStatusMessage('已清空全部参考图。', 'success');
      }
    }, 3000);
  }

  function handleCinematicRefClearClick(event) {
    if (event) event.preventDefault();
    if (cinematicRefClearHandled) {
      cinematicRefClearHandled = false;
      return;
    }
    cancelCinematicRefClearHold();
    if (removeLatestCinematicReference()) {
      showStatusMessage('已删除最近上传的一张参考图。', 'info');
    }
  }

  const EXAMPLE_TEMPLATES = {
    portrait: '一位年轻的亚洲女性，自然妆容，柔和的眼神，穿着简约的白色衬衫，室内窗光，浅景深，人像摄影',
    landscape: '壮丽的自然风光，蓝天白云，翠绿的草地，远处的雪山，清澈的湖泊，广角镜头，高饱和度',
    cyberpunk: '赛博朋克未来城市，霓虹灯牌闪烁，雨夜街道，湿润反光地面，冷色调，高科技低生活氛围'
  };

  let charCountTimer = null;

  function updateCharCount(textareaId, countId) {
    const textarea = document.getElementById(textareaId || 'genPrompt');
    const countEl = document.getElementById(countId || 'genCharCount');
    if (textarea && countEl) {
      const len = textarea.value.length;
      countEl.textContent = len;
      if (len > 9000) {
        countEl.style.color = '#ef4444';
      } else if (len > 7000) {
        countEl.style.color = '#f59e0b';
      } else {
        countEl.style.color = 'var(--muted)';
      }
    }
  }

  function initPromptHelpers() {
    const textareas = ['genPrompt', 'comfyPrompt', 'editPrompt', 'gptPrompt'];
    const counts = ['genCharCount', 'comfyCharCount', 'editCharCount', 'gptCharCount'];

    textareas.forEach((id, idx) => {
      const textarea = document.getElementById(id);
      if (textarea) {
        textarea.addEventListener('input', () => {
          updateCharCount(id, counts[idx]);
          clearTimeout(charCountTimer);
          charCountTimer = setTimeout(() => {}, 500);
        });
        updateCharCount(id, counts[idx]);
      }
    });
  }

  function clearPrompt(targetId) {
    const textarea = document.getElementById(targetId || 'genPrompt');
    if (!textarea) return;
    if (textarea.value.length > 0 && !confirm('确定清空提示词吗？')) return;
    textarea.value = '';
    updateCharCount(targetId, getCounterId(targetId));
    textarea.focus();
  }

  function insertExample(type, targetId) {
    const textarea = document.getElementById(targetId || 'genPrompt');
    if (!textarea) return;
    const template = EXAMPLE_TEMPLATES[type] || '';
    if (template) {
      textarea.value = template;
      updateCharCount(targetId, getCounterId(targetId));
      textarea.focus();
    }
  }

  function getCounterId(textareaId) {
    const map = {
      genPrompt: 'genCharCount',
      comfyPrompt: 'comfyCharCount',
      editPrompt: 'editCharCount',
      gptPrompt: 'gptCharCount'
    };
    return map[textareaId] || 'genCharCount';
  }
