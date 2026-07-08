// Result stage restoration and shared ratio UI
  function rememberStageTask(key, taskId) {
    if (!key || !taskId) return;
    const storageKey = STAGE_TASK_STORAGE_KEYS[key];
    if (storageKey) localStorage.setItem(storageKey, taskId);
  }

  function getRememberedStageTask(key) {
    const storageKey = STAGE_TASK_STORAGE_KEYS[key];
    return storageKey ? (localStorage.getItem(storageKey) || '') : '';
  }

  function clearRememberedStageTask(key) {
    const storageKey = STAGE_TASK_STORAGE_KEYS[key];
    if (storageKey) localStorage.removeItem(storageKey);
  }

  function isTaskInFlight(status) {
    return IN_FLIGHT_TASK_STATUSES.includes(String(status || '').toLowerCase());
  }

  function getStageElements(key) {
    return {
      stage: document.getElementById(`${key}Result`),
      hint: document.getElementById(`${key}StageHint`),
      status: document.getElementById(`${key}Status`),
      empty: document.getElementById(`${key}EmptyState`),
      image: document.getElementById(`${key}Image`),
      action: document.getElementById(`${key}StageAction`)
    };
  }

  function updateStageAction(key, state = 'idle') {
    const { action } = getStageElements(key);
    if (!action) return;
    const hasTask = !!getRememberedStageTask(key);
    const isVisible = hasTask && state !== 'idle';
    action.classList.toggle('is-visible', isVisible);
    if (!isVisible) return;

    const successLabel = (key === 'gen' || key === 'comfy') ? '查看最近作品' : '查看最近任务';
    const label = state === 'success' ? successLabel : '查看最近任务';
    action.textContent = label;
  }

  async function ensureHistoryLoaded() {
    if (Array.isArray(historyRecords) && historyRecords.length > 0) {
      return historyRecords;
    }
    await loadHistory();
    return historyRecords;
  }

  function findRecentStageItem(key) {
    const rememberedTaskId = getRememberedStageTask(key);
    const items = Array.isArray(historyRecords) ? [...historyRecords] : [];
    if (!items.length) return null;

    if (rememberedTaskId) {
      const matched = items.find(item => item.task_id === rememberedTaskId);
      if (matched) return matched;
    }

    const allowedTypes = STAGE_TYPE_MAP[key] || [];
    return items
      .filter(item => allowedTypes.includes(item.type))
      .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))[0] || null;
  }

  async function openRecentStageResult(key) {
    try {
      await ensureHistoryLoaded();
      let item = findRecentStageItem(key);
      if (!item) {
        await loadHistory();
        item = findRecentStageItem(key);
      }
      if (!item) {
        showStatusMessage('最近任务还没同步出来，再等一下。', 'info');
        return;
      }
      openDetailModal(item);
    } catch (e) {
      showStatusMessage('最近任务暂时打不开，请稍后再试。', 'error');
    }
  }

  function getStageTaskUi(key, task = {}) {
    const rawStatus = String(task.status || '').toLowerCase();
    const progressText = task.progress_text || task.message || '';
    const errorText = task.error || progressText || '任务处理失败，请稍后重试。';

    if (isTaskInFlight(rawStatus)) {
      const busyLabel = rawStatus === 'queued'
        ? '⏳ 排队中...'
        : rawStatus === 'preparing'
          ? '⏳ 准备中...'
          : rawStatus === 'fallback_running'
            ? '🛟 托底中...'
            : '⏳ 处理中...';
      const busyText = progressText || (
        rawStatus === 'queued'
          ? '任务已进入队列，正在等待处理。'
          : rawStatus === 'preparing'
            ? '任务正在准备参数，请稍候。'
            : rawStatus === 'fallback_running'
            ? '主路由失败，正在切换账号池托底。'
              : '任务正在处理中，请稍候。'
      );
      return {
        state: 'busy',
        tone: 'busy',
        message: busyText,
        buttonLabel: busyLabel,
        buttonBusy: true
      };
    }

    if (['succeeded', 'succeeded_no_telegram', 'success'].includes(rawStatus)) {
      const successText = progressText || (
        key === 'gpt'
          ? '后台任务已完成，图片会自动发送到 Telegram。'
          : key === 'edit'
            ? '编辑任务已完成，结果已进入历史记录。'
            : '任务已完成，结果已进入历史记录。'
      );
      return {
        state: 'success',
        tone: 'success',
        message: successText,
        buttonLabel: SUBMIT_BUTTON_DEFAULTS[STAGE_BUTTON_IDS[key]],
        buttonBusy: false
      };
    }

    if (['failed', 'telegram_failed'].includes(rawStatus)) {
      return {
        state: 'error',
        tone: 'error',
        message: errorText,
        buttonLabel: SUBMIT_BUTTON_DEFAULTS[STAGE_BUTTON_IDS[key]],
        buttonBusy: false
      };
    }

    return {
      state: 'idle',
      tone: 'busy',
      message: '',
      buttonLabel: SUBMIT_BUTTON_DEFAULTS[STAGE_BUTTON_IDS[key]],
      buttonBusy: false
    };
  }

  function applyTaskToStage(key, task = {}) {
    const ui = getStageTaskUi(key, task);
    if (ui.message) {
      setStageStatusText(key, ui.message, ui.tone);
    }
    setStageState(key, {
      busy: ui.state === 'busy',
      statusVisible: ui.state !== 'idle',
      imageVisible: false,
      state: ui.state
    });
    setSubmitButtonState(STAGE_BUTTON_IDS[key], {
      busy: ui.buttonBusy,
      label: ui.buttonLabel
    });
  }

  function startStagePolling(key, taskId, status) {
    if (!isTaskInFlight(status)) return;
    if (key === 'comfy') {
      pollComfy(taskId);
      return;
    }
    pollTaskStatus(taskId, document.getElementById(STAGE_BUTTON_IDS[key]), key);
  }

  function resetStageUi(key) {
    setStageState(key, { busy: false, statusVisible: false, imageVisible: false, state: 'idle' });
  }

  async function restoreStageFromTask(key) {
    const taskId = getRememberedStageTask(key);
    if (!taskId) return;

    try {
      const task = await api.json('/api/status/' + taskId);
      applyTaskToStage(key, task);
      startStagePolling(key, taskId, task.status);
      if (!isTaskInFlight(task.status)) {
        clearRememberedStageTask(key);
      }
    } catch (e) {
      try {
        await loadHistory();
        const item = findRecentStageItem(key);
        if (item) {
          const normalizedStatus = item.status === 'success' ? 'succeeded' : item.status;
          applyTaskToStage(key, {
            status: normalizedStatus,
            error: item.error,
            progress_text: item.progress_text
          });
          return;
        }
      } catch (_) {}
      clearRememberedStageTask(key);
      resetStageUi(key);
      setSubmitButtonState(STAGE_BUTTON_IDS[key], { busy: false });
    }
  }

  function restorePersistedStages() {
    STAGE_KEYS.forEach(resetStageUi);
    STAGE_KEYS.forEach((key) => restoreStageFromTask(key));
  }

  function setStageStatusText(key, message, tone = 'busy') {
    const { status } = getStageElements(key);
    if (!status) return;
    status.textContent = message || '';
    status.dataset.tone = tone;
  }

  function setStageState(key, { busy = false, statusVisible = false, imageVisible = false, state = '' } = {}) {
    const { stage, hint, status, image, empty } = getStageElements(key);
    const resolvedState = state || (busy ? 'busy' : imageVisible ? 'success' : statusVisible ? 'success' : 'idle');
    const stageCopy = (STAGE_COPY[key] && STAGE_COPY[key][resolvedState]) || (STAGE_COPY[key] && STAGE_COPY[key].idle) || null;

    if (stage) {
      stage.classList.toggle('is-busy', !!busy);
      stage.dataset.state = resolvedState;
    }
    if (hint && stageCopy) {
      hint.textContent = stageCopy.hint;
    }
    if (status) {
      status.classList.toggle('is-visible', !!statusVisible);
      if (!statusVisible) {
        status.dataset.tone = 'busy';
      }
    }
    if (image) image.classList.toggle('is-visible', !!imageVisible);
    if (empty) {
      empty.dataset.tone = resolvedState;
      if (stageCopy) empty.textContent = stageCopy.body;
      const shouldShowEmpty = key === 'comfy' ? (!busy && !imageVisible) : !imageVisible;
      empty.style.display = shouldShowEmpty ? 'block' : 'none';
    }
    updateStageAction(key, resolvedState);
  }

  function setComfyStatusText(message, tone = 'busy') {
    setStageStatusText('comfy', message, tone);
  }

  function setComfyStageState(options = {}) {
    setStageState('comfy', options);
  }

  function decorateRatioButton(button) {
    if (!button || button.dataset.decorated === 'true') return;

    const rawText = (button.textContent || '').trim();
    const isAuto = /auto|自动/i.test(rawText);
    const ratioValue = button.dataset.ratioValue || (isAuto ? 'auto' : rawText);
    const visualKey = isAuto ? 'auto' : ratioValue;
    button.dataset.ratioValue = ratioValue;
    button.dataset.decorated = 'true';

    let visual = '<span class="ratio-visual auto"></span>';
    if (visualKey !== 'auto' && visualKey.includes(':')) {
      const [wRaw, hRaw] = visualKey.split(':').map(v => Number(v) || 1);
      const maxSide = 16;
      let width = maxSide;
      let height = maxSide;
      if (wRaw >= hRaw) {
        height = Math.max(6, Math.round((hRaw / wRaw) * maxSide));
      } else {
        width = Math.max(6, Math.round((wRaw / hRaw) * maxSide));
      }
      visual = `<span class="ratio-visual" style="--rw:${width};--rh:${height}"><span class="ratio-visual-frame"></span></span>`;
    }

    const label = isAuto ? '自动' : ratioValue;
    button.innerHTML = `<span class="ratio-btn-inner">${visual}<span class="ratio-label">${label}</span></span>`;
  }

  function initRatioButtons() {
    document.querySelectorAll('.ratio-section .r-btn, .ratio-section .btn-auto').forEach((button) => {
      if (/auto|自动/i.test((button.textContent || '').trim()) && !button.dataset.ratioValue) {
        button.dataset.ratioValue = button.id === 'r-auto' ? 'auto' : '1:1';
      }
      decorateRatioButton(button);
    });
  }

  function syncRatioButtons(selector, val) {
    document.querySelectorAll(selector).forEach((button) => {
      const selected = (button.dataset.ratioValue || '').trim() === val;
      button.classList.toggle('selected', selected);
      if (button.classList.contains('btn-auto')) {
        button.classList.toggle('outline', !selected);
      }
    });
  }
