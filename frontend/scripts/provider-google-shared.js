// Google provider shared pickers, toasts, and polling
  function pickStyle(val) {
    genState.style = val;
    let activeBtn = null;
    document.querySelectorAll('#genStyleChips .style-chip').forEach(btn => {
      const isActive = btn.dataset.style === val;
      btn.classList.toggle('selected', isActive);
      if (isActive) activeBtn = btn;
    });

    if (activeBtn) {
      activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
    setTimeout(updateStyleChipFade, 120);
    genState.model = typeof normalizeGoogleModel === 'function'
      ? normalizeGoogleModel(genState.model)
      : genState.model;
    saveUiSettings();
  }

  function pickRatioGen(val) {
    syncRatioButtons('#view-gen .r-btn, #view-gen .btn-auto', val);
    genState.ratio = val;
    saveUiSettings();
  }

  function pickGenQuality(val) {
    genState.quality = val;
    const sel = document.getElementById('genQuality');
    if (sel && sel.value !== val) sel.value = val;
    saveUiSettings();
  }

  function pickQuality(val, sourceEl) {
    document.querySelectorAll('#view-edit .quality-group .q-btn').forEach(b => b.classList.remove('selected'));
    editState.quality = val;
    if (sourceEl && sourceEl.value !== val) sourceEl.value = val;
    const sel = document.getElementById('editQuality');
    if (sel && sel.value !== val) sel.value = val;
    saveUiSettings();
  }

  function pickFeature(val) {
    editState.feature = val;
    console.log('Feature selected:', val);
    const sel = document.getElementById('editFeature');
    if (sel && sel.value !== val) sel.value = val;
    saveUiSettings();
  }

  function pickRatioEdit(val) {
    syncRatioButtons('#view-edit .ratio-section .r-btn, #view-edit .btn-auto', val);
    editState.ratio = val;
    saveUiSettings();
  }

  function simpleHash(input) {
    let h = 0;
    for (let i = 0; i < input.length; i++) {
      h = ((h << 5) - h) + input.charCodeAt(i);
      h |= 0;
    }
    return Math.abs(h).toString(16);
  }

  function buildGenIdempotencyKey(payload) {
    const canonical = JSON.stringify({
      prompt: payload.prompt || '',
      style: payload.style || 'raw',
      ratio: payload.ratio || '1:1',
      quality: payload.quality || '2k',
      model: typeof normalizeGoogleModel === 'function'
        ? normalizeGoogleModel(payload.model)
        : (payload.model || 'gemini-3.1-flash-image'),
      subject: payload.subject || ''
    });
    return 'gen:' + simpleHash(canonical);
  }

  function pickModel(type, model) {
    const nextModel = typeof normalizeGoogleModel === 'function'
      ? normalizeGoogleModel(model)
      : String(model || '').trim();
    if (type === 'gen') {
      genState.model = nextModel;
      const sel = document.getElementById('genModelSelect');
      if (sel && sel.value !== nextModel) sel.value = nextModel;
    } else {
      editState.model = nextModel;
    }

    const typeInputs = document.querySelectorAll(`.model-option input[name="${type}Model"]`);
    typeInputs.forEach((input) => {
      const opt = input.closest('.model-option');
      if (!opt) return;
      opt.classList.toggle('active', input.value === nextModel);
      input.checked = input.value === nextModel;
    });

    saveUiSettings();
  }

  function clearComposerPrompts(promptIds = []) {
    const seen = new Set();
    promptIds.forEach((id) => {
      if (!id || seen.has(id)) return;
      seen.add(id);
      setTextareaValue(id, '');
    });

    const cinematicPrompt = document.getElementById('cinematicPrompt');
    if (cinematicPrompt) {
      cinematicPrompt.value = '';
      cinematicPrompt.dataset.userEdited = '';
    }

    syncCinematicComposerUi();
  }

  function resetGoogleGenerateComposer() {
    pickStyle('raw');
    pickRatioGen('1:1');
    pickGenQuality('2k');
    pickModel('gen', 'gemini-3.1-flash-image');
    clearComposerPrompts(['genPrompt']);
  }

  function resetGoogleEditComposer() {
    pickQuality('hd');
    pickFeature('edit');
    pickRatioEdit('auto');
    pickModel('edit', 'gemini-3.1-flash-image');
    clearComposerPrompts(['editPrompt']);
  }

  function resetGptComposer() {
    pickRatioGpt('9:16');
    pickResolutionGpt('1k');
    pickQualityGpt('auto');
    pickImageCountGpt(1);
    pickModerationGpt('auto');
    clearComposerPrompts(['gptPrompt']);
  }

  const VALID_IMAGE_RATIOS = new Set(['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '9:21', '21:9']);
  const VALID_GPT_RESOLUTIONS = new Set(['1k', '2k', '4k']);
  const VALID_GPT_QUALITIES = new Set(['auto', 'low', 'medium', 'high']);
  const VALID_GOOGLE_QUALITIES = new Set(['1k', '2k', '4k']);
  const pollingTaskIds = {};
  const pollingTimers = {};

  function normalizeImageRatio(value, fallback = '1:1') {
    const ratio = String(value || '').trim().toLowerCase();
    return VALID_IMAGE_RATIOS.has(ratio) ? ratio : fallback;
  }

  function normalizeGoogleQuality(value, fallback = '2k') {
    const quality = String(value || '').trim().toLowerCase();
    if (quality === 'hd') return '4k';
    if (quality === 'standard' || quality === 'normal') return '1k';
    return VALID_GOOGLE_QUALITIES.has(quality) ? quality : fallback;
  }

  function normalizeGptResolution(value, fallback = '1k') {
    const resolution = String(value || '').trim().toLowerCase();
    return VALID_GPT_RESOLUTIONS.has(resolution) ? resolution : fallback;
  }

  function normalizeGptQuality(value, fallback = 'auto') {
    const quality = String(value || '').trim().toLowerCase();
    return VALID_GPT_QUALITIES.has(quality) ? quality : fallback;
  }

  function normalizeGptModeration(value, fallback = 'auto') {
    return String(value || '').trim().toLowerCase() === 'low' ? 'low' : fallback;
  }

  function normalizeGptImageCount(value, fallback = 1) {
    const count = parseInt(value, 10);
    return Number.isFinite(count) ? Math.max(1, Math.min(8, count)) : fallback;
  }

  function showStatusMessage(message, type = 'info') {
    const oldMsg = document.getElementById('statusMessage');
    if (oldMsg) oldMsg.remove();

    const msgEl = document.createElement('div');
    msgEl.id = 'statusMessage';
    msgEl.className = 'status-toast ' + type;
    msgEl.textContent = message;
    const color = type === 'error'
      ? { bg: 'linear-gradient(180deg, rgba(255,249,248,0.96), rgba(255,236,233,0.96))', text: '#b95d55' }
      : type === 'success'
        ? { bg: 'linear-gradient(180deg, rgba(248,255,250,0.96), rgba(231,245,236,0.96))', text: '#3f7a56' }
        : { bg: 'linear-gradient(180deg, rgba(252,255,253,0.96), rgba(236,245,239,0.96))', text: '#43695a' };
    msgEl.style.background = color.bg;
    msgEl.style.color = color.text;
    document.body.appendChild(msgEl);

    if (type !== 'error') {
      setTimeout(() => {
        if (msgEl.parentNode) msgEl.remove();
      }, 3000);
    }
  }

  function pollTaskStatus(taskId, btn, stageKey = 'gen') {
    pollingTaskIds[stageKey] = taskId;
    if (pollingTimers[stageKey]) {
      clearTimeout(pollingTimers[stageKey]);
      pollingTimers[stageKey] = null;
    }

    const poll = () => {
      api.json('/api/status/' + taskId)
        .then(task => {
          if (!task || pollingTaskIds[stageKey] !== taskId) return;

          const status = task.status;
          const message = task.progress_text || task.message || '';

          if (status === 'queued') {
            showStatusMessage('✅ 已提交图片生成任务，请等待...', 'info');
            setStageStatusText(stageKey, '已提交任务，正在进入队列...', 'busy');
            setStageState(stageKey, { busy: true, statusVisible: true, state: 'busy' });
            setSubmitButtonState(btn, { busy: true, label: '⏳ 排队中...' });
          } else if (status === 'preparing') {
            showStatusMessage('🎨 正在准备...', 'info');
            setStageStatusText(stageKey, '正在准备生成参数...', 'busy');
            setStageState(stageKey, { busy: true, statusVisible: true, state: 'busy' });
            setSubmitButtonState(btn, { busy: true, label: '⏳ 准备中...' });
          } else if (status === 'processing' || status === 'fallback_running') {
            if (message) {
              showStatusMessage('🔄 ' + message, 'info');
            }
            setStageStatusText(stageKey, message || '正在生成中...', 'busy');
            setStageState(stageKey, { busy: true, statusVisible: true, state: 'busy' });
            setSubmitButtonState(btn, { busy: true, label: '⏳ 生成中...' });
          } else if (status === 'succeeded' || status === 'succeeded_no_telegram') {
            showStatusMessage('✅ 生成成功！', 'success');
            setStageStatusText(stageKey, status === 'succeeded_no_telegram' ? '图片已生成，但 Telegram 发送失败。' : '生成完成，作品已进入历史记录。', 'success');
            setStageState(stageKey, { busy: false, statusVisible: true, state: 'success' });
            setSubmitButtonState(btn, { busy: false });
            pollingTaskIds[stageKey] = null;
            clearRememberedStageTask(stageKey);
            loadHistory();
          } else if (status === 'failed' || status === 'telegram_failed') {
            showStatusMessage('❌ 生成失败：' + (task.error || '未知错误'), 'error');
            setStageStatusText(stageKey, task.error || '生成失败，请稍后重试。', 'error');
            setStageState(stageKey, { busy: false, statusVisible: true, state: 'error' });
            setSubmitButtonState(btn, { busy: false });
            clearPendingHistoryRecord(taskId);
            pollingTaskIds[stageKey] = null;
            clearRememberedStageTask(stageKey);
          }

          if (isTaskInFlight(status)) {
            pollingTimers[stageKey] = setTimeout(poll, 2000);
          }
        })
        .catch(err => {
          console.error('Poll error:', err);
          if (String(err?.message || err || '').includes('Task not found')) {
            pollingTaskIds[stageKey] = null;
            clearRememberedStageTask(stageKey);
            clearPendingHistoryRecord(taskId);
            resetStageUi(stageKey);
            setSubmitButtonState(btn, { busy: false });
            return;
          }
          pollingTimers[stageKey] = setTimeout(poll, 3000);
        });
    };

    poll();
  }
