(function () {
  let pollTimer = null;
  const pollTimers = new Map();
  const batchPollTimers = new Map();
  let sidecarStatusTimer = null;
  let transientTimer = null;
  let progressTimerId = null;
  const DEFAULT_STATUS_MESSAGE = '就绪';
  const STATUS_COPY_LABEL = '复制';
  const DEFAULT_RESULT_NODE_ID = 'input';
  let progressTimerResultNodeId = DEFAULT_RESULT_NODE_ID;
  let bottomStatusMessage = DEFAULT_STATUS_MESSAGE;
  let bottomStatusTone = 'info';
  let statusTipOpen = false;
  let statusTipTask = null;
  let statusTipRawText = '';
  let statusTipCopyTimer = null;
  const STATUS_TONE_CLASSES = [
    'desk-status-chip--ok',
    'desk-status-chip--warn',
    'desk-status-chip--error',
    'desk-status-chip--checking'
  ];
  const els = {};

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function toPositiveInt(value, fallback = 0) {
    const parsed = parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  }

  function getTaskParams(task) {
    return task?.params && typeof task.params === 'object' ? task.params : {};
  }

  function getRequestedImageCount(task, output) {
    const params = getTaskParams(task);
    return toPositiveInt(
      task?.requested_image_count || params.image_count || params.imageCount || output?.requestedImageCount,
      toPositiveInt(task?.image_count, toPositiveInt(output?.files?.length, 1))
    );
  }

  function isBrowserFallback(task, output) {
    return false;
  }

  function uniqueFiles(files) {
    return [...new Set((files || []).filter(Boolean))];
  }

  function resultFileToImagePath(task, filename) {
    const safeName = String(filename || '').trim();
    if (!safeName) return '';
    if (/^(?:https?:|data:|blob:)/i.test(safeName) || safeName.startsWith('/image/') || safeName.startsWith('/gpt_outputs/')) {
      return safeName;
    }
    const type = String(task?.type || task?.provider || '').toLowerCase();
    if (type === 'gpt-file' || type === 'layout-export') return '';
    const encoded = safeName.split('/').map(part => encodeURIComponent(part)).join('/');
    return type.startsWith('gpt') ? `/gpt_outputs/${encoded}` : `/image/${encoded}`;
  }

  function normalizeTaskImagePaths(task, resultFiles = []) {
    const explicit = Array.isArray(task?.image_paths) && task.image_paths.length
      ? task.image_paths
      : (Array.isArray(task?.imagePaths) ? task.imagePaths : []);
    const primary = task?.primary_image_path
      || task?.primaryImagePath
      || task?.image_path
      || task?.imagePath
      || task?.result_file
      || task?.output_file
      || task?.primaryFile
      || '';
    if (explicit.length || primary) return uniqueFiles([...explicit, resultFileToImagePath(task, primary)].filter(Boolean));
    return uniqueFiles((resultFiles || []).map(file => resultFileToImagePath(task, file)));
  }

  function collectElements() {
    [
      'deskOutputTitle',
      'deskOutputStatus',
      'deskInputOutputStatus',
      'deskStatusMessage',
      'deskStatusTip',
      'deskStatusTipTitle',
      'deskStatusTipSubtitle',
      'deskStatusTipDisplay',
      'deskStatusTipMeta',
      'deskStatusTipRaw',
      'deskStatusTipCopy',
      'deskStatusTipClose',
      'deskSidecarStatus',
      'deskFallbackStatus',
      'deskArchiveStatus',
      'deskTelegramStatus',
      'deskProgressPercent',
      'deskProgressBar',
      'deskInputProgressPercent',
      'deskInputProgressBar',
      'deskInputProgressStage',
      'deskInputProgressTimer',
      'deskProgressFloat',
      'deskResultGrid',
      'deskSendOriginalBtn',
      'deskOutputPills',
      'deskStopBtn'
    ].forEach(id => {
      els[id] = $(id);
    });
  }

  function setStatusPill(status) {
    const pill = els.deskOutputStatus;
    if (!pill) return;
    pill.classList.remove('is-busy', 'is-success', 'is-error');
    if (DesktopState.isInFlight(status)) pill.classList.add('is-busy');
    if (DesktopState.isSuccess(status)) pill.classList.add('is-success');
    if (DesktopState.isFailure(status)) pill.classList.add('is-error');
    pill.textContent = DesktopState.getStatusLabel(status);
  }

  function getResultNode(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    return document.querySelector(`.desk-node[data-node-id="${CSS.escape(resultNodeId)}"]`);
  }

  function getResultEls(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const node = getResultNode(resultNodeId);
    if (!node) return {};
    const isInputNode = node.classList.contains('desk-node--input');
    return {
      title: node.querySelector('[data-output-title]') || (resultNodeId === 'output' ? els.deskOutputTitle : null),
      status: node.querySelector('[data-output-status]') || (resultNodeId === 'output' ? els.deskOutputStatus : els.deskInputOutputStatus),
      progressPercent: isInputNode ? els.deskInputProgressPercent : (node.querySelector('[data-progress-percent]') || (resultNodeId === 'output' ? els.deskProgressPercent : null)),
      progressBar: isInputNode ? els.deskInputProgressBar : (node.querySelector('[data-progress-bar]') || (resultNodeId === 'output' ? els.deskProgressBar : null)),
      progressWrap: isInputNode ? null : node.querySelector('.desk-progress-wrap'),
      progressStage: isInputNode ? els.deskInputProgressStage : node.querySelector('[data-progress-stage]'),
      progressTimer: isInputNode ? els.deskInputProgressTimer : node.querySelector('[data-progress-timer]'),
      grid: node.querySelector('[data-result-grid]') || (resultNodeId === 'output' ? els.deskResultGrid : null),
      sendOriginal: node.querySelector('[data-send-original]') || (resultNodeId === 'output' ? els.deskSendOriginalBtn : null),
      copyPrompt: node.querySelector('[data-copy-prompt]'),
      pills: node.querySelector('[data-output-pills]') || (resultNodeId === 'output' ? els.deskOutputPills : null)
    };
  }

  function getOutputState(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    if (!DesktopState.state.outputs[resultNodeId]) {
      DesktopState.state.outputs[resultNodeId] = {
        status: 'idle',
        stage: '',
        progressText: '',
        startedAt: 0,
        heartbeatAt: 0,
        createdAt: 0,
        finishedAt: 0,
        files: [],
        imagePaths: [],
        primaryFile: '',
        primaryImagePath: '',
        type: 'gpt',
        error: '',
        taskId: '',
        fileManifest: null,
        selectedFiles: [],
        selectionInitialized: false
      };
    }
    return DesktopState.state.outputs[resultNodeId];
  }

  function taskFromOutputSnapshot(output = {}, taskId = '') {
    return {
      task_id: taskId || output.taskId || output.task_id || '',
      status: output.status || 'idle',
      stage: output.stage || '',
      progress_text: output.progressText || output.progress_text || '',
      progress: Number(output.progress || 0) || 0,
      prompt: output.prompt || '',
      type: output.type || 'gpt',
      params: output.params || {},
      result_file: output.primaryFile || output.result_file || '',
      output_file: output.primaryFile || output.output_file || '',
      result_files: Array.isArray(output.files) ? output.files : [],
      output_files: Array.isArray(output.files) ? output.files : [],
      image_paths: Array.isArray(output.imagePaths) ? output.imagePaths : [],
      requested_image_count: output.requestedImageCount || output.requested_image_count || undefined,
      started_at: output.startedAt || output.started_at || 0,
      heartbeat_at: output.heartbeatAt || output.heartbeat_at || 0,
      created_at: output.createdAt || output.created_at || 0,
      finished_at: output.finishedAt || output.finished_at || 0,
      error: output.error || '',
      display_error: output.displayError || output.display_error || '',
      raw_error: output.rawError || output.raw_error || '',
      error_code: output.errorCode || output.error_code || '',
      error_category: output.errorCategory || output.error_category || '',
      last_run_id: output.lastRunId || output.last_run_id || '',
      run_count: output.runCount || output.run_count || 0,
      file_manifest: output.fileManifest || output.file_manifest || null
    };
  }

  function outputHasVisibleState(output = {}) {
    if (!output || typeof output !== 'object') return false;
    if (DesktopState.isInFlight(output.status)) return true;
    if (DesktopState.isSuccess(output.status) || DesktopState.isFailure(output.status) || String(output.status || '') === 'canceled') return true;
    return Boolean(
      (Array.isArray(output.files) && output.files.length)
      || (Array.isArray(output.imagePaths) && output.imagePaths.length)
      || output.error
      || output.displayError
      || output.progressText
      || output.batchId
    );
  }

  function applyPersistedOutputSnapshot(resultNodeId, output = {}) {
    if (!outputHasVisibleState(output)) return;
    const taskId = output.taskId || output.task_id || '';
    applyTask(taskFromOutputSnapshot(output, taskId), resultNodeId);
  }

  function resetOutputTiming(output) {
    if (!output || typeof output !== 'object') return;
    output.startedAt = 0;
    output.heartbeatAt = 0;
    output.createdAt = 0;
    output.finishedAt = 0;
  }

  function renderBottomStatus() {
    if (!els.deskStatusMessage) return;
    els.deskStatusMessage.textContent = bottomStatusMessage || DEFAULT_STATUS_MESSAGE;
    els.deskStatusMessage.dataset.tone = bottomStatusTone || 'info';
    els.deskStatusMessage.title = '点击查看任务状态详情';
    if (statusTipOpen) renderStatusTip();
  }

  function setBottomStatus(message = DEFAULT_STATUS_MESSAGE, tone = 'info') {
    bottomStatusMessage = message || DEFAULT_STATUS_MESSAGE;
    bottomStatusTone = tone || 'info';
    if (!transientTimer) renderBottomStatus();
  }

  function setStatusChipTone(chip, tone = 'ok') {
    if (!chip) return;
    const safeTone = STATUS_TONE_CLASSES.includes(`desk-status-chip--${tone}`) ? tone : 'ok';
    chip.classList.remove(...STATUS_TONE_CLASSES);
    chip.classList.add(`desk-status-chip--${safeTone}`);
    chip.dataset.tone = safeTone;
  }

  function compactText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function firstStatusLine(value) {
    const line = String(value || '')
      .split(/\r?\n/)
      .map(item => item.trim())
      .find(Boolean) || '';
    return compactText(line);
  }

  function truncateStatusText(value, limit = 180) {
    const text = compactText(value);
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }

  function looksLikeRawFailure(value) {
    const text = String(value || '');
    if (!text) return false;
    if (/[\u4e00-\u9fff]/.test(text) && text.length < 120) return false;
    return /(?:Traceback|HTTPSConnectionPool|HTTPConnectionPool|SSLError|SSLEOFError|Max retries exceeded|Exception|RuntimeError|ValueError|TypeError|Error:|_ssl\.c|api\.[A-Za-z0-9.-]+|\/v\d+\/)/i.test(text);
  }

  function summarizeStatusDisplay(value) {
    return statusDisplayInfo(value).text;
  }

  function statusDisplayInfo(value) {
    const text = String(value || '').trim();
    if (!text) return { text: '', rawSummary: false };
    const firstLine = firstStatusLine(text);
    if (!firstLine) return { text: '', rawSummary: false };
    const rawSummary = looksLikeRawFailure(text);
    return {
      text: rawSummary ? truncateStatusText(firstLine, 170) : truncateStatusText(text, 220),
      rawSummary
    };
  }

  function localizeStatusTipText(value) {
    return window.DesktopI18n?.translate?.(value) || value;
  }

  function formatStatusRaw(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value, null, 2);
      } catch (error) {
        return String(value);
      }
    }
    const text = String(value || '').trim();
    if (!text) return '';
    try {
      const parsed = JSON.parse(text);
      return JSON.stringify(parsed, null, 2);
    } catch (error) {
      return text;
    }
  }

  function readableRoute(value) {
    const route = String(value || '').trim();
    const labels = {
      codex: '本地 Codex',
      chatgpt_pool: '账号池 API',
      third_party_image_api: '第三方 API',
      google_gen: 'Google 生成',
      google_edit: 'Google 编辑',
      gpt_pool: '账号池 API',
      gpt_pool_fallback: 'GPT 托底',
      gpt_pool_fallback_edit: 'GPT 编辑托底',
      codex_edit: 'Codex 编辑',
      third_party_image_api_edit: '第三方编辑 API',
      chatgpt_pool_editable: '账号池文件 API'
    };
    return labels[route] || route;
  }

  function inferStatusRoute(task = null, output = null) {
    const params = getTaskParams(task);
    const explicitRoute = task?.gpt_provider_route
      || task?.provider_route
      || task?.route
      || params.gpt_provider_route
      || params.provider_route
      || params.route
      || output?.params?.gpt_provider_route
      || output?.params?.provider_route
      || output?.params?.route
      || '';
    if (explicitRoute) return explicitRoute;
    const type = String(task?.type || output?.type || '').toLowerCase();
    const provider = String(task?.provider || output?.provider || '').toLowerCase();
    const joined = `${provider} ${type}`;
    if (joined.includes('google-edit')) return 'google_edit';
    if (joined.includes('google')) return 'google_gen';
    if (joined.includes('third_party') || joined.includes('third-party')) return type.includes('edit') ? 'third_party_image_api_edit' : 'third_party_image_api';
    if (joined.includes('pool') || joined.includes('chatgpt')) return 'chatgpt_pool';
    if (joined.includes('codex') || joined.includes('gpt')) return type.includes('edit') ? 'codex_edit' : 'codex';
    return '';
  }

  function statusTipMetaRows(task = null, output = null) {
    const route = inferStatusRoute(task, output);
    const rows = [
      ['状态', DesktopState.getStatusLabel(task?.status || output?.status || 'idle')],
      ['任务 ID', task?.task_id || output?.taskId || DesktopState.state.selectedTaskId || ''],
      ['Run ID', task?.last_run_id || output?.lastRunId || ''],
      ['错误码', task?.error_code || output?.errorCode || ''],
      ['分类', task?.error_category || output?.errorCategory || ''],
      ['线路', readableRoute(route)],
      ['阶段', task?.stage || output?.stage || ''],
      ['次数', task?.run_count ? `${task.run_count}` : '']
    ];
    return rows.filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '');
  }

  function getStatusTipTask() {
    const output = getOutputState(DEFAULT_RESULT_NODE_ID);
    return statusTipTask || {
      task_id: output.taskId || DesktopState.state.selectedTaskId || '',
      status: output.status || 'idle',
      stage: output.stage || '',
      progress_text: output.progressText || bottomStatusMessage,
      progress: output.progress || 0,
      error: output.error || '',
      display_error: output.displayError || '',
      raw_error: output.rawError || '',
      error_code: output.errorCode || '',
      error_category: output.errorCategory || '',
      last_run_id: output.lastRunId || '',
      run_count: output.runCount || 0,
      params: output.params || {}
    };
  }

  function buildStatusTipTask(task = null, output = null) {
    const source = task && typeof task === 'object' ? task : {};
    const liveOutput = output || getOutputState(DEFAULT_RESULT_NODE_ID);
    const sourceValue = (snakeName, camelName, fallback = '') => {
      if (Object.prototype.hasOwnProperty.call(source, snakeName)) return source[snakeName];
      if (camelName && Object.prototype.hasOwnProperty.call(source, camelName)) return source[camelName];
      return fallback;
    };
    return {
      ...source,
      task_id: sourceValue('task_id', 'taskId', liveOutput?.taskId || DesktopState.state.selectedTaskId || ''),
      status: sourceValue('status', '', liveOutput?.status || 'idle'),
      stage: sourceValue('stage', '', liveOutput?.stage || ''),
      progress_text: sourceValue('progress_text', 'message', liveOutput?.progressText || bottomStatusMessage || ''),
      progress: sourceValue('progress', 'progressPercent', liveOutput?.progress || 0),
      error: sourceValue('error', '', liveOutput?.error || ''),
      display_error: sourceValue('display_error', 'displayError', liveOutput?.displayError || ''),
      raw_error: sourceValue('raw_error', 'rawError', liveOutput?.rawError || ''),
      error_code: sourceValue('error_code', 'errorCode', liveOutput?.errorCode || ''),
      error_category: sourceValue('error_category', 'errorCategory', liveOutput?.errorCategory || ''),
      last_run_id: sourceValue('last_run_id', 'lastRunId', liveOutput?.lastRunId || ''),
      run_count: sourceValue('run_count', 'runCount', liveOutput?.runCount || 0),
      type: sourceValue('type', '', liveOutput?.type || ''),
      provider: sourceValue('provider', '', liveOutput?.provider || ''),
      params: getTaskParams(source) || liveOutput?.params || {}
    };
  }

  function updateStatusTipPosition() {
    const panel = els.deskStatusTip;
    const trigger = els.deskStatusMessage;
    if (!panel || !trigger || panel.hidden) return;
    const rect = trigger.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const gap = 10;
    const viewportPadding = 10;
    const width = Math.min(panelRect.width || 360, window.innerWidth - viewportPadding * 2);
    const left = Math.max(
      viewportPadding,
      Math.min(window.innerWidth - width - viewportPadding, rect.left + rect.width / 2 - width / 2)
    );
    const bottom = Math.max(viewportPadding, window.innerHeight - rect.top + gap);
    panel.style.left = `${Math.round(left)}px`;
    panel.style.right = 'auto';
    panel.style.bottom = `${Math.round(bottom)}px`;
  }

  function renderStatusTip() {
    const panel = els.deskStatusTip;
    if (!panel) return;
    const task = getStatusTipTask();
    const output = getOutputState(DEFAULT_RESULT_NODE_ID);
    const status = String(task?.status || output.status || 'idle');
    const displaySource = task?.display_error
      || task?.progress_text
      || task?.message
      || task?.error
      || output.displayError
      || output.progressText
      || bottomStatusMessage
      || DEFAULT_STATUS_MESSAGE;
    const displayInfo = statusDisplayInfo(displaySource);
    const displayMessage = displayInfo.text;
    const raw = formatStatusRaw(
      task?.raw_error
      || task?.rawError
      || task?.error
      || output.rawError
      || output.error
      || task?.progress_text
      || output.progressText
      || ''
    );
    statusTipRawText = [
      displayMessage ? `用户可读信息：${displayMessage}` : '',
      raw ? `原始返回信息：\n${raw}` : '',
      task?.error_code ? `错误码：${task.error_code}` : '',
      task?.error_category ? `错误分类：${task.error_category}` : '',
      task?.task_id ? `task_id：${task.task_id}` : '',
      task?.last_run_id ? `run_id：${task.last_run_id}` : ''
    ].filter(Boolean).join('\n\n');
    if (els.deskStatusTipTitle) els.deskStatusTipTitle.textContent = DesktopState.isFailure(status) ? '生成失败详情' : '任务状态详情';
    if (els.deskStatusTipSubtitle) els.deskStatusTipSubtitle.textContent = task?.task_id ? `#${task.task_id}` : '当前任务';
    if (els.deskStatusTipDisplay) {
      els.deskStatusTipDisplay.textContent = displayMessage || DEFAULT_STATUS_MESSAGE;
      els.deskStatusTipDisplay.closest('.desk-status-tip__summary')?.classList.toggle('is-raw-summary', displayInfo.rawSummary);
    }
    if (els.deskStatusTipRaw) els.deskStatusTipRaw.textContent = raw || '暂无原始返回信息';
    if (els.deskStatusTipMeta) {
      els.deskStatusTipMeta.innerHTML = statusTipMetaRows(task, output)
        .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`)
        .join('');
    }
    resetStatusTipCopyButton();
    panel.dataset.tone = DesktopState.isFailure(status) ? 'error' : (DesktopState.isSuccess(status) ? 'success' : (DesktopState.isInFlight(status) ? 'busy' : 'info'));
    window.requestAnimationFrame(updateStatusTipPosition);
  }

  function openStatusTip() {
    const panel = els.deskStatusTip;
    if (!panel) return;
    statusTipOpen = true;
    panel.hidden = false;
    els.deskStatusMessage?.setAttribute('aria-expanded', 'true');
    renderStatusTip();
  }

  function closeStatusTip() {
    const panel = els.deskStatusTip;
    statusTipOpen = false;
    if (panel) panel.hidden = true;
    els.deskStatusMessage?.setAttribute('aria-expanded', 'false');
  }

  function toggleStatusTip() {
    if (statusTipOpen) closeStatusTip();
    else openStatusTip();
  }

  function setStatusTipCopyState(state) {
    const button = els.deskStatusTipCopy;
    if (!button) return;
    if (!button.dataset.defaultLabel) button.dataset.defaultLabel = STATUS_COPY_LABEL;
    if (statusTipCopyTimer) {
      window.clearTimeout(statusTipCopyTimer);
      statusTipCopyTimer = null;
    }
    button.classList.toggle('is-copied', state === 'copied');
    button.classList.toggle('is-copy-error', state === 'error');
    button.textContent = state === 'copied'
      ? localizeStatusTipText('已复制')
      : state === 'error'
        ? localizeStatusTipText('复制失败')
        : localizeStatusTipText(button.dataset.defaultLabel || STATUS_COPY_LABEL);
    if (state === 'copied' || state === 'error') {
      statusTipCopyTimer = window.setTimeout(() => resetStatusTipCopyButton(), 1600);
    }
  }

  function resetStatusTipCopyButton() {
    const button = els.deskStatusTipCopy;
    if (!button) return;
    if (statusTipCopyTimer) {
      window.clearTimeout(statusTipCopyTimer);
      statusTipCopyTimer = null;
    }
    button.classList.remove('is-copied', 'is-copy-error');
    button.textContent = localizeStatusTipText(button.dataset.defaultLabel || STATUS_COPY_LABEL);
  }

  function setSidecarStatus(text, tone = 'checking', title = '') {
    const chip = els.deskSidecarStatus;
    if (!chip) return;
    setStatusChipTone(chip, tone);
    chip.textContent = text || '账号池 未知';
    chip.title = title || chip.textContent;
  }

  function statusParamEnabled(params, camelName, snakeName, fallbackSelector, fallback = true) {
    if (params && Object.prototype.hasOwnProperty.call(params, camelName)) return params[camelName] !== false;
    if (params && Object.prototype.hasOwnProperty.call(params, snakeName)) return params[snakeName] !== false;
    const fallbackInput = document.querySelector(fallbackSelector);
    return fallbackInput ? Boolean(fallbackInput.checked) : fallback;
  }

  function globalOutputControlParams(params = {}) {
    const source = params && typeof params === 'object' ? params : {};
    const output = DesktopState.state.output || {};
    const hasGlobalArchive = Object.prototype.hasOwnProperty.call(output, 'archiveEnabled');
    const hasGlobalTelegram = Object.prototype.hasOwnProperty.call(output, 'telegramEnabled');
    return {
      ...source,
      archiveEnabled: hasGlobalArchive
        ? output.archiveEnabled !== false
        : statusParamEnabled(source, 'archiveEnabled', 'archive_enabled', '#deskArchiveToggle', true),
      telegramEnabled: hasGlobalTelegram
        ? output.telegramEnabled !== false
        : statusParamEnabled(source, 'telegramEnabled', 'telegram_enabled', '#deskTelegramToggle', true)
    };
  }

  function renderOutputStatusChips(params = {}, status = '') {
    const normalizedStatus = String(status || '').toLowerCase();
    const controls = globalOutputControlParams(params);
    const archiveEnabled = controls.archiveEnabled !== false;
    const telegramEnabled = controls.telegramEnabled !== false;
    if (els.deskFallbackStatus) {
      els.deskFallbackStatus.textContent = 'GPT fallback 可用';
      setStatusChipTone(els.deskFallbackStatus, 'ok');
      els.deskFallbackStatus.title = 'GPT fallback 可用';
    }
    if (els.deskArchiveStatus) {
      els.deskArchiveStatus.textContent = archiveEnabled ? '归档开启' : '归档关闭';
      setStatusChipTone(els.deskArchiveStatus, archiveEnabled ? 'ok' : 'warn');
      els.deskArchiveStatus.title = archiveEnabled ? '结果会保存到归档目录' : '当前任务关闭归档';
    }
    if (els.deskTelegramStatus) {
      const telegramFailed = normalizedStatus === 'telegram_failed';
      els.deskTelegramStatus.textContent = telegramFailed ? 'Telegram 失败' : (telegramEnabled ? 'Telegram 开启' : 'Telegram 关闭');
      setStatusChipTone(els.deskTelegramStatus, telegramFailed ? 'error' : (telegramEnabled ? 'ok' : 'warn'));
      els.deskTelegramStatus.title = telegramFailed
        ? 'Telegram 发送失败'
        : (telegramEnabled ? '结果会发送到 Telegram' : '当前任务关闭 Telegram 发送');
    }
  }

  function getLiveOutputControlParams(params = {}) {
    const source = params && typeof params === 'object' ? params : {};
    return globalOutputControlParams(source);
  }

  function refreshOutputConfigStatus(resultNodeId = DEFAULT_RESULT_NODE_ID, params = null, options = {}) {
    const output = getOutputState(resultNodeId);
    const status = output.status || DesktopState.state.output.status || 'idle';
    const liveParams = getLiveOutputControlParams(params || output.params || {});
    if (options.updateBottom !== false) renderOutputStatusChips(liveParams, status);
    renderPills({ status, params: liveParams }, resultNodeId);
  }

  function renderSidecarStatus(payload) {
    const pool = payload?.chatgpt_pool || payload || {};
    const stats = pool.stats || {};
    const active = Number(stats.active || 0);
    const available = Number(stats.available ?? active);
    const inflight = Number(stats.inflight || 0);
    const limited = Number(stats.limited || 0);
    const abnormal = Number(stats.abnormal || 0);
    const total = Number(stats.total || 0);
    if (!pool.enabled) {
      setSidecarStatus('账号池 未启用', 'warn', 'ChatGPT account-pool sidecar is disabled');
      return;
    }
    if (pool.online) {
      const countText = total > 0 ? ` ${available}/${total}` : '';
      const busyText = inflight > 0 ? ` · 忙 ${inflight}` : '';
      const issueText = limited || abnormal ? ` · 限流/异常 ${limited}/${abnormal}` : '';
      const tone = available > 0 ? 'ok' : 'warn';
      setSidecarStatus(
        `账号池 在线${countText}${busyText}`,
        tone,
        `Sidecar online${total ? `, available ${available}/${total}` : ''}${busyText}${issueText}`
      );
      return;
    }
    setSidecarStatus('账号池 离线', 'error', pool.health_error || 'Sidecar health check failed');
  }

  async function refreshSidecarStatus() {
    if (!window.DesktopApi?.getChatgptPoolStatus) {
      setSidecarStatus('账号池 未加载', 'warn');
      return;
    }
    try {
      const payload = await window.DesktopApi.getChatgptPoolStatus();
      renderSidecarStatus(payload);
    } catch (error) {
      setSidecarStatus('账号池 离线', 'error', error?.message || '账号池状态读取失败');
    }
  }

  function startSidecarStatusPolling() {
    if (sidecarStatusTimer) window.clearInterval(sidecarStatusTimer);
    refreshSidecarStatus();
    sidecarStatusTimer = window.setInterval(refreshSidecarStatus, 30000);
  }

  function setProgress(percent, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const resultEls = getResultEls(resultNodeId);
    const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
    if (resultEls.progressBar) {
      resultEls.progressBar.style.width = `${safePercent}%`;
      resultEls.progressBar.parentElement?.style.setProperty('--progress-percent', `${safePercent}%`);
    }
    const progressPercentValue = resultEls.progressPercent?.querySelector?.('[data-progress-percent-value]') || resultEls.progressPercent;
    if (progressPercentValue) progressPercentValue.textContent = `${safePercent}%`;
  }

  function setProgressVisibility(visible, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const resultEls = getResultEls(resultNodeId);
    const resultNode = getResultNode(resultNodeId);
    const overlay = resultNode?.classList?.contains('desk-node--input') ? els.deskProgressFloat : null;
    if (!resultEls.progressWrap && !overlay) return;
    if (overlay) {
      if (visible) {
        window.DesktopCanvas?.updateInputProgressOverlay?.(resultNodeId);
        overlay.dataset.resultNodeId = resultNodeId;
        overlay.classList.add('is-visible');
        overlay.setAttribute('aria-hidden', 'false');
      } else if (!overlay.dataset.resultNodeId || overlay.dataset.resultNodeId === resultNodeId) {
        overlay.classList.remove('is-visible');
        overlay.setAttribute('aria-hidden', 'true');
      }
    } else {
      resultEls.progressWrap.classList.toggle('is-visible', Boolean(visible));
      resultEls.progressWrap.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }
  }

  function getProgressStartTime(task, output) {
    const startedAt = Number(task?.started_at || output?.startedAt || output?.started_at || 0);
    if (Number.isFinite(startedAt) && startedAt > 0) return startedAt * (startedAt < 1e12 ? 1000 : 1);
    const heartbeatAt = Number(task?.heartbeat_at || output?.heartbeatAt || 0);
    if (Number.isFinite(heartbeatAt) && heartbeatAt > 0) return heartbeatAt * (heartbeatAt < 1e12 ? 1000 : 1);
    const updatedAt = Number(task?.updated_at || task?.created_at || output?.updatedAt || 0);
    if (Number.isFinite(updatedAt) && updatedAt > 0) return updatedAt * (updatedAt < 1e12 ? 1000 : 1);
    return Date.now();
  }

  function formatElapsed(ms) {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutesPart = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) {
      return `${String(hours).padStart(2, '0')}:${String(minutesPart).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }
    const minutesOnly = Math.floor(totalSeconds / 60);
    return `${String(minutesOnly).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  function toEpochMs(value) {
    const numeric = Number(value || 0);
    if (!Number.isFinite(numeric) || numeric <= 0) return 0;
    return numeric < 1e12 ? numeric * 1000 : numeric;
  }

  function updateProgressTimer(resultNodeId = progressTimerResultNodeId || DEFAULT_RESULT_NODE_ID) {
    const output = getOutputState(resultNodeId);
    const task = {
      started_at: output.startedAt,
      heartbeat_at: output.heartbeatAt,
      created_at: output.createdAt
    };
    const resultEls = getResultEls(resultNodeId);
    if (!resultEls.progressTimer) return;
    if (!DesktopState.isInFlight(output.status)) {
      const startedMs = toEpochMs(output.startedAt || output.createdAt);
      const finishedMs = toEpochMs(output.finishedAt || output.heartbeatAt || output.createdAt);
      resultEls.progressTimer.textContent = startedMs && finishedMs
        ? formatElapsed(Math.max(0, finishedMs - startedMs))
        : '00:00';
      return;
    }
    const startTime = getProgressStartTime(task, output);
    resultEls.progressTimer.textContent = formatElapsed(Date.now() - startTime);
  }

  function startProgressTimer(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    progressTimerResultNodeId = resultNodeId || DEFAULT_RESULT_NODE_ID;
    if (progressTimerId) window.clearInterval(progressTimerId);
    updateProgressTimer(progressTimerResultNodeId);
    progressTimerId = window.setInterval(() => updateProgressTimer(progressTimerResultNodeId), 1000);
  }

  function stopProgressTimer(resultNodeId = '') {
    if (resultNodeId && progressTimerResultNodeId !== resultNodeId) return;
    if (!progressTimerId) return;
    window.clearInterval(progressTimerId);
    progressTimerId = null;
  }

  function getPrimaryItem(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const { state } = DesktopState;
    const output = getOutputState(resultNodeId);
    return {
      task_id: output.taskId || state.selectedTaskId,
      primaryFile: output.primaryFile,
      result_file: output.primaryFile,
      output_file: output.primaryFile,
      image_paths: output.imagePaths,
      imagePaths: output.imagePaths,
      type: output.type || state.provider,
      prompt: output.prompt || state.prompt
    };
  }

  function getExportFiles(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const output = getOutputState(resultNodeId);
    if (window.DesktopFileResults?.isFileResultNode?.(resultNodeId)) {
      const primary = output.fileManifest?.primary?.relative_path || output.params?.file_manifest?.primary?.relative_path || output.primaryFile;
      return primary ? [primary] : [];
    }
    const files = Array.isArray(output.files) ? output.files.filter(Boolean) : [];
    if (files.length) {
      const available = new Set(files);
      return uniqueFiles(output.selectedFiles).filter(file => available.has(file));
    }
    return output.primaryFile ? [output.primaryFile] : [];
  }

  function syncSelectedFiles(output, nextFiles) {
    const files = uniqueFiles(nextFiles);
    const previousFiles = uniqueFiles(output.files);
    if (!files.length) {
      output.selectedFiles = [];
      output.selectionInitialized = false;
      return;
    }
    if (!output.selectionInitialized) {
      output.selectedFiles = files;
      output.selectionInitialized = true;
      return;
    }
    const previousFileSet = new Set(previousFiles);
    const nextFileSet = new Set(files);
    const selected = uniqueFiles(output.selectedFiles).filter(file => nextFileSet.has(file));
    files.forEach(file => {
      if (!previousFileSet.has(file) && !selected.includes(file)) selected.push(file);
    });
    output.selectedFiles = selected;
  }

  function toggleSelectedFile(resultNodeId, file) {
    if (!file) return;
    const output = getOutputState(resultNodeId);
    const available = new Set(output.files || []);
    if (!available.has(file)) return;
    const selected = new Set(output.selectedFiles || []);
    if (selected.has(file)) selected.delete(file);
    else selected.add(file);
    output.selectedFiles = uniqueFiles([...selected]).filter(item => available.has(item));
    output.selectionInitialized = true;
    if (window.DesktopFileResults?.isFileResultNode?.(resultNodeId)) {
      window.DesktopFileResults.render(resultNodeId, output, { status: output.status, params: output.params });
    } else {
      renderImages(resultNodeId);
    }
    renderActions(resultNodeId);
    renderPills({ status: output.status, params: output.params }, resultNodeId);
    DesktopState.saveSettings();
  }

  function renderImages(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const resultEls = getResultEls(resultNodeId);
    const grid = resultEls.grid;
    if (!grid) return;
    const output = getOutputState(resultNodeId);
    const paths = output.imagePaths || [];
    const files = output.files || [];
    const displayPaths = paths.slice(0, 8);
    const requestedCount = Math.max(displayPaths.length, toPositiveInt(output.requestedImageCount, displayPaths.length));
    const selected = new Set(output.selectedFiles || []);
    grid.classList.toggle('is-single', displayPaths.length === 1);
    grid.classList.toggle('is-multi', displayPaths.length > 1);
    if (displayPaths.length) grid.dataset.count = String(displayPaths.length);
    else delete grid.dataset.count;
    if (!paths.length) {
      grid.innerHTML = `
        <div class="desk-result-empty">
          <strong>结果会出现在这里</strong>
          <span>连接模型节点后点击生成。</span>
        </div>
      `;
      return;
    }

    grid.innerHTML = displayPaths.map((path, index) => {
      const file = files[index] || '';
      const isSelected = !!file && selected.has(file);
      return `
      <div class="desk-result-card${displayPaths.length === 1 ? ' is-primary' : ''}${isSelected ? ' is-selected' : ''}" data-result-card data-file="${escapeHtml(file)}">
        <img src="${escapeHtml(path)}" alt="生成结果 ${index + 1}">
        ${requestedCount > 1 ? `<span class="desk-result-index">${index + 1}/${requestedCount}</span>` : ''}
        ${file ? `
          <button type="button" class="desk-result-select" data-select-file="${escapeHtml(file)}" aria-pressed="${isSelected ? 'true' : 'false'}" title="${isSelected ? '取消选择' : '选择图片'}" aria-label="${isSelected ? '取消选择' : '选择'}生成结果 ${index + 1}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"></path></svg>
          </button>
        ` : ''}
        <button type="button" class="desk-result-open" data-file="${escapeHtml(file)}" data-path="${escapeHtml(path)}" title="打开原图" aria-label="打开原图 ${index + 1}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M14 5h5v5"></path>
            <path d="M10 14 19 5"></path>
            <path d="M19 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h4"></path>
          </svg>
        </button>
        <button type="button" class="desk-result-to-canvas" data-result-to-canvas="${index}" title="回流到画布" aria-label="把生成结果 ${index + 1} 放到画布">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="4" y="5" width="16" height="14" rx="3"></rect>
            <path d="M9 12h6"></path>
            <path d="M12 9v6"></path>
          </svg>
        </button>
        <button type="button" class="desk-result-edit" data-result-edit="${index}" title="继续编辑" aria-label="继续编辑生成结果 ${index + 1}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 20h4l10-10a2.8 2.8 0 0 0-4-4L4 16v4Z"></path>
            <path d="M13 7l4 4"></path>
          </svg>
        </button>
      </div>
    `;
    }).join('');

    grid.querySelectorAll('[data-result-card]').forEach(card => {
      card.addEventListener('click', event => {
        if (event.target.closest('button')) return;
        toggleSelectedFile(resultNodeId, card.dataset.file || '');
      });
    });

    grid.querySelectorAll('[data-select-file]').forEach(button => {
      button.addEventListener('click', () => {
        toggleSelectedFile(resultNodeId, button.dataset.selectFile || '');
      });
    });

    grid.querySelectorAll('button[data-path]').forEach(button => {
      button.addEventListener('click', () => {
        window.open(button.dataset.path, '_blank', 'noopener');
      });
    });

    grid.querySelectorAll('[data-result-to-canvas]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        const index = toPositiveInt(button.dataset.resultToCanvas, 0);
        window.DesktopCanvas?.createImageNodeFromResult?.(resultNodeId, index)
          ?.catch(error => showError(error, resultNodeId));
      });
    });
    grid.querySelectorAll('[data-result-edit]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        const index = toPositiveInt(button.dataset.resultEdit, 0);
        const path = displayPaths[index] || '';
        const file = files[index] || '';
        window.DesktopCanvas?.continueEditFromHistoryItem?.({
          imageUrl: path,
          title: file || `生成结果 ${index + 1}`,
          file,
          prompt: output.prompt || '',
          taskId: output.taskId || '',
          provider: output.type || '',
          source: 'result-node'
        })?.catch(error => showError(error, resultNodeId));
      });
    });
  }

  function renderActions(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const resultEls = getResultEls(resultNodeId);
    const output = getOutputState(resultNodeId);
    const batchActive = output.batchId && !['completed', 'missing'].includes(String(output.batchStatus || ''));
    const allFiles = uniqueFiles(output.files);
    const selectedFiles = getExportFiles(resultNodeId);
    const hasSelection = selectedFiles.length > 0;
    if (resultEls.sendOriginal) {
      if (window.DesktopFileResults?.isFileResultNode?.(resultNodeId)) {
        window.DesktopFileResults.renderActions(resultNodeId, output, resultEls);
        return;
      }
      if (batchActive) {
        resultEls.sendOriginal.disabled = false;
        resultEls.sendOriginal.textContent = output.batchStatus === 'paused' ? '继续批量' : '暂停批量';
        resultEls.sendOriginal.dataset.batchAction = output.batchStatus === 'paused' ? 'resume' : 'pause';
      } else {
        delete resultEls.sendOriginal.dataset.batchAction;
        resultEls.sendOriginal.disabled = !hasSelection;
        if (!resultEls.sendOriginal.dataset.busy) {
          resultEls.sendOriginal.textContent = '手动发送';
        }
      }
    }
    if (resultEls.copyPrompt) {
      if (batchActive) {
        resultEls.copyPrompt.disabled = false;
        resultEls.copyPrompt.textContent = '取消批量';
        resultEls.copyPrompt.dataset.batchAction = 'cancel';
      } else {
        delete resultEls.copyPrompt.dataset.batchAction;
        resultEls.copyPrompt.textContent = '复制提示词';
        resultEls.copyPrompt.disabled = !output.prompt && !DesktopState.state.prompt;
      }
    }
  }

  function renderPills(task, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const resultEls = getResultEls(resultNodeId);
    const wrap = resultEls.pills;
    if (!wrap) return;
    const status = task?.status || DesktopState.state.output.status;
    const output = getOutputState(resultNodeId);
    if (window.DesktopFileResults?.isFileResultNode?.(resultNodeId)) {
      window.DesktopFileResults.renderPills(task, resultNodeId, output, wrap);
      return;
    }
    const taskParams = getTaskParams(task);
    const params = Object.keys(taskParams).length ? taskParams : (output.params || {});
    const imageCount = output.files?.length || output.imagePaths?.length || 0;
    const requestedCount = Math.max(imageCount, getRequestedImageCount(task, output));
    const selectedCount = getExportFiles(resultNodeId).length;
    const isFallback = isBrowserFallback(task, output);
    const isPartial = imageCount > 0 && requestedCount > imageCount;
    const pills = [
      {
        text: imageCount
          ? (requestedCount > 1 ? `图片 ${imageCount}/${requestedCount}` : '图片 1')
          : '等待结果',
        tone: imageCount && !isPartial ? 'success' : (isPartial ? 'warning' : '')
      },
      imageCount > 1 ? { text: `已选 ${selectedCount}`, tone: selectedCount ? '' : 'warning' } : null,
      params.resolution ? { text: `${String(params.resolution).toUpperCase()} · ${params.ratio || '默认比例'}` } : null,
      isFallback ? { text: '托底中', tone: 'warning' } : null,
      isPartial ? { text: DesktopState.isInFlight(status) ? '部分生成中' : '部分完成', tone: 'warning' } : null
    ];
    if (DesktopState.isInFlight(status)) pills.unshift({ text: imageCount ? '生成中' : '队列处理中', tone: 'busy' });
    if (task?.transport_error_type) pills.push({ text: `传输：${task.transport_error_type}`, tone: 'warning' });
    if (task?.ttfb_ms) pills.push({ text: `TTFB ${task.ttfb_ms}ms` });
    wrap.innerHTML = pills.filter(Boolean).map(pill => {
      const tone = pill.tone ? ` class="is-${escapeHtml(pill.tone)}"` : '';
      return `<span${tone}>${escapeHtml(pill.text)}</span>`;
    }).join('');
  }

  function applyTask(task, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const { state } = DesktopState;
    const output = getOutputState(resultNodeId);
    const status = String(task?.status || 'idle');
    const resultFiles = Array.isArray(task?.result_files) && task.result_files.length
      ? task.result_files
      : (Array.isArray(task?.output_files) ? task.output_files : []);
    const imagePaths = normalizeTaskImagePaths(task, resultFiles);
    const params = getTaskParams(task);
    renderOutputStatusChips(params, status);
    syncSelectedFiles(output, resultFiles);
    const nowSeconds = Math.floor(Date.now() / 1000);
    const incomingStartedAt = Number(task?.started_at || task?.created_at || 0);
    const incomingHeartbeatAt = Number(task?.heartbeat_at || 0);
    const incomingCreatedAt = Number(task?.created_at || 0);
    const incomingFinishedAt = Number(task?.finished_at || 0);

    output.status = status;
    output.stage = task?.stage || '';
    output.progressText = task?.progress_text || task?.message || '';
    output.progress = Math.max(0, Math.min(100, Number(task?.progress ?? task?.progress_percent ?? task?.progressPercent ?? output.progress ?? 0) || 0));
    output.startedAt = incomingStartedAt > 0
      ? incomingStartedAt
      : (incomingCreatedAt > 0 ? incomingCreatedAt : (DesktopState.isInFlight(status) ? (output.startedAt || nowSeconds) : (output.startedAt || 0)));
    output.heartbeatAt = incomingHeartbeatAt > 0 ? incomingHeartbeatAt : (DesktopState.isInFlight(status) ? (output.heartbeatAt || nowSeconds) : 0);
    output.createdAt = incomingCreatedAt > 0
      ? incomingCreatedAt
      : (DesktopState.isInFlight(status) ? (output.createdAt || nowSeconds) : (output.createdAt || 0));
    output.finishedAt = incomingFinishedAt > 0
      ? incomingFinishedAt
      : (DesktopState.isInFlight(status) ? 0 : (incomingCreatedAt > 0 ? incomingCreatedAt : (output.finishedAt || 0)));
    output.files = resultFiles;
    output.imagePaths = imagePaths;
    output.primaryFile = task?.result_file || task?.output_file || resultFiles[0] || '';
    output.primaryImagePath = imagePaths[0] || '';
    output.type = task?.type || output.type || state.provider;
    output.error = task?.error || '';
    output.displayError = task?.display_error || task?.displayError || '';
    output.rawError = task?.raw_error || task?.rawError || '';
    output.errorCode = task?.error_code || task?.errorCode || '';
    output.errorCategory = task?.error_category || task?.errorCategory || '';
    output.lastRunId = task?.last_run_id || task?.lastRunId || '';
    output.runCount = task?.run_count || task?.runCount || 0;
    output.taskId = Object.prototype.hasOwnProperty.call(task || {}, 'task_id') || Object.prototype.hasOwnProperty.call(task || {}, 'taskId')
      ? (task?.task_id || task?.taskId || '')
      : (output.taskId || '');
    output.prompt = task?.prompt || output.prompt || '';
    output.params = params;
    output.fileManifest = task?.file_manifest || params.file_manifest || output.fileManifest || null;
    output.requestedImageCount = getRequestedImageCount(task, output);
    output.isBrowserFallback = isBrowserFallback(task, output);
    output.isPartialResult = resultFiles.length > 0 && output.requestedImageCount > resultFiles.length;

    if (resultNodeId === DEFAULT_RESULT_NODE_ID || resultNodeId === 'output') {
      state.output = { ...state.output, ...output };
      state.selectedTaskId = output.taskId || state.selectedTaskId;
    }

    const resultEls = getResultEls(resultNodeId);
    if (resultEls.title) {
      resultEls.title.textContent = DesktopState.isSuccess(status)
        ? '生成完成'
        : DesktopState.isFailure(status)
          ? '任务失败'
          : status === 'canceled'
            ? '已取消'
            : DesktopState.isInFlight(status)
              ? '正在生成'
              : '等待运行';
    }
    if (resultEls.status) {
      resultEls.status.classList.remove('is-busy', 'is-success', 'is-error', 'is-canceled');
      if (DesktopState.isInFlight(status)) resultEls.status.classList.add('is-busy');
      if (DesktopState.isSuccess(status)) resultEls.status.classList.add('is-success');
      if (DesktopState.isFailure(status)) resultEls.status.classList.add('is-error');
      if (status === 'canceled') resultEls.status.classList.add('is-canceled');
      resultEls.status.textContent = DesktopState.getStatusLabel(status);
    }
    setProgressVisibility(DesktopState.isInFlight(status), resultNodeId);
    setProgress(DesktopState.estimateProgress(task), resultNodeId);
    if (resultEls.progressStage) {
      resultEls.progressStage.textContent = output.progressText || DesktopState.getStatusLabel(status);
    }
    if (resultEls.progressTimer) {
      if (DesktopState.isInFlight(status)) {
        startProgressTimer(resultNodeId);
      } else {
        stopProgressTimer(resultNodeId);
        const startedMs = toEpochMs(output.startedAt || output.createdAt);
        const finishedMs = toEpochMs(output.finishedAt || output.heartbeatAt || output.createdAt);
        resultEls.progressTimer.textContent = startedMs && finishedMs
          ? formatElapsed(Math.max(0, finishedMs - startedMs))
          : '00:00';
      }
    }
    let nextBottomMessage = '';
    let nextBottomTone = '';
    if (DesktopState.isInFlight(status)) {
      nextBottomMessage = output.progressText || DesktopState.getStatusLabel(status);
      nextBottomTone = 'info';
    } else if (DesktopState.isFailure(status)) {
      nextBottomMessage = output.displayError || output.error || output.progressText || DesktopState.getStatusLabel(status);
      nextBottomTone = 'error';
    } else if (status === 'canceled') {
      nextBottomMessage = output.progressText || DesktopState.getStatusLabel(status);
      nextBottomTone = 'info';
    } else if (DesktopState.isSuccess(status)) {
      nextBottomMessage = output.progressText || DesktopState.getStatusLabel(status);
      nextBottomTone = 'success';
    } else if (resultNodeId === DEFAULT_RESULT_NODE_ID || resultNodeId === 'output') {
      nextBottomMessage = DEFAULT_STATUS_MESSAGE;
      nextBottomTone = 'info';
    }
    if (nextBottomTone) {
      statusTipTask = buildStatusTipTask(task, output);
      setBottomStatus(nextBottomMessage, nextBottomTone);
    }
    if (window.DesktopFileResults?.isFileResultNode?.(resultNodeId)) {
      window.DesktopFileResults.render(resultNodeId, output, task);
    } else {
      renderImages(resultNodeId);
    }
    renderActions(resultNodeId);
    renderPills(task, resultNodeId);
    window.DesktopCanvas?.refreshUpscaleNodeMode?.(resultNodeId);
    if (DesktopState.isSuccess(status) && output.imagePaths?.length) {
      window.DesktopCanvas?.runUpscaleChainsForOutput?.(resultNodeId, output)
        ?.then(count => {
          if (count) showTransientMessage(count > 1 ? `${count} 个高清放大节点已开始处理。` : '高清放大节点已开始处理。');
        })
        .catch(() => {});
      window.DesktopCanvas?.populateResultImageNodes?.(resultNodeId, output)
        ?.then(count => {
          if (count) showTransientMessage(count > 1 ? `${count} 个图片节点已更新。` : '图片节点已更新。');
        })
        .catch(() => {});
    }
    DesktopState.saveSettings();
    if (statusTipOpen) renderStatusTip();
  }

  function resetOutput(options = {}) {
    const { state } = DesktopState;
    stopPolling();
    if (!options.keepTaskId) {
      state.selectedTaskId = '';
    }
    state.output.status = 'idle';
    state.output.stage = '';
    state.output.progressText = '';
    state.output.files = [];
    state.output.imagePaths = [];
    state.output.primaryFile = '';
    state.output.primaryImagePath = '';
    state.output.error = '';
    state.output.displayError = '';
    state.output.rawError = '';
    state.output.errorCode = '';
    state.output.errorCategory = '';
    state.output.lastRunId = '';
    state.output.runCount = 0;
    state.output.startedAt = 0;
    state.output.heartbeatAt = 0;
    state.output.createdAt = 0;
    state.output.finishedAt = 0;
    state.outputs[DEFAULT_RESULT_NODE_ID] = {
      ...(state.outputs[DEFAULT_RESULT_NODE_ID] || {}),
      status: 'idle',
      stage: '',
      progressText: '',
      files: [],
      imagePaths: [],
      primaryFile: '',
      primaryImagePath: '',
      error: '',
      displayError: '',
      rawError: '',
      errorCode: '',
      errorCategory: '',
      lastRunId: '',
      runCount: 0,
      taskId: options.keepTaskId ? (state.outputs[DEFAULT_RESULT_NODE_ID]?.taskId || '') : '',
      startedAt: 0,
      heartbeatAt: 0,
      createdAt: 0,
      finishedAt: 0
    };
    statusTipTask = null;
    applyTask({ status: 'idle', progress_text: '尚未提交任务' }, DEFAULT_RESULT_NODE_ID);
    updateProgressTimer(DEFAULT_RESULT_NODE_ID);
  }

  function renderIdleProviderHint() {
    if (DesktopState.state.output.status !== 'idle') return;
    const provider = DesktopState.getProviderLabel(DesktopState.state.provider);
    setBottomStatus(`当前模型：${provider}`, 'info');
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    batchPollTimers.forEach(timer => window.clearTimeout(timer));
    batchPollTimers.clear();
  }

  function stopResultPolling(resultNodeId) {
    const timer = pollTimers.get(resultNodeId);
    if (timer) window.clearTimeout(timer);
    pollTimers.delete(resultNodeId);
  }

  function stopBatchPolling(resultNodeId) {
    const timer = batchPollTimers.get(resultNodeId);
    if (timer) window.clearTimeout(timer);
    batchPollTimers.delete(resultNodeId);
  }

  function schedulePoll(taskId, delay = 1800) {
    stopPolling();
    pollTimer = window.setTimeout(() => pollTask(taskId), delay);
  }

  function scheduleResultPoll(resultNodeId, taskId, delay = 1800) {
    stopResultPolling(resultNodeId);
    pollTimers.set(resultNodeId, window.setTimeout(() => pollResultTask(resultNodeId, taskId), delay));
  }

  function scheduleBatchPoll(resultNodeId, batchId, delay = 1800) {
    stopBatchPolling(resultNodeId);
    batchPollTimers.set(resultNodeId, window.setTimeout(() => pollBatch(resultNodeId, batchId), delay));
  }

  async function pollTask(taskId) {
    if (!taskId) return;
    try {
      const task = await DesktopApi.getStatus(taskId);
      applyTask(task, DEFAULT_RESULT_NODE_ID);
      if (DesktopState.isInFlight(task.status)) {
        schedulePoll(taskId, task.status === 'queued' ? 2400 : 1800);
      } else {
        stopPolling();
        DesktopHistory.loadHistory().catch(() => {});
      }
    } catch (error) {
      showError(error, DEFAULT_RESULT_NODE_ID);
      schedulePoll(taskId, 5000);
    }
  }

  async function pollResultTask(resultNodeId, taskId) {
    if (!taskId) return;
    try {
      const task = await DesktopApi.getStatus(taskId);
      applyTask({ ...task, task_id: taskId }, resultNodeId);
      if (DesktopState.isInFlight(task.status)) {
        scheduleResultPoll(resultNodeId, taskId, task.status === 'queued' ? 2400 : 1800);
      } else {
        stopResultPolling(resultNodeId);
        DesktopHistory.loadHistory().catch(() => {});
      }
    } catch (error) {
      showError(error, resultNodeId);
      scheduleResultPoll(resultNodeId, taskId, 5000);
    }
  }

  function batchProgressText(summary) {
    const counts = summary?.counts || {};
    const total = counts.total || 0;
    const done = (counts.succeeded || 0) + (counts.failed || 0) + (counts.canceled || 0);
    const parts = [`批量 ${done}/${total}`];
    if (counts.processing) parts.push(`生成中 ${counts.processing}`);
    if (counts.queued) parts.push(`排队 ${counts.queued}`);
    if (counts.succeeded) parts.push(`成功 ${counts.succeeded}`);
    if (counts.failed) parts.push(`失败 ${counts.failed}`);
    if (counts.canceled) parts.push(`取消 ${counts.canceled}`);
    return parts.join(' · ');
  }

  function applyBatchSummary(summary, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const output = getOutputState(resultNodeId);
    output.batchId = summary?.batch_id || output.batchId || '';
    output.batchStatus = summary?.status || '';
    output.batchControl = summary?.control || '';
    output.batchCounts = summary?.counts || null;
    const tasks = Array.isArray(summary?.tasks) ? summary.tasks : [];
    const resultFiles = uniqueFiles(tasks.flatMap(task => (
      Array.isArray(task?.result_files) && task.result_files.length
        ? task.result_files
        : (Array.isArray(task?.output_files) ? task.output_files : [])
    )));
    const imagePaths = uniqueFiles(tasks.flatMap(task => normalizeTaskImagePaths(task, (
      Array.isArray(task?.result_files) && task.result_files.length
        ? task.result_files
        : (Array.isArray(task?.output_files) ? task.output_files : [])
    ))));
    syncSelectedFiles(output, resultFiles);
    output.files = resultFiles;
    output.imagePaths = imagePaths;
    output.primaryFile = resultFiles[0] || output.primaryFile || '';
    output.primaryImagePath = imagePaths[0] || output.primaryImagePath || '';
    const counts = summary?.counts || {};
    const completed = summary?.status === 'completed';
    const status = completed ? (counts.failed ? 'failed' : 'succeeded') : 'processing';
    applyTask({
      task_id: output.taskId || output.batchId,
      status,
      progress_text: batchProgressText(summary),
      prompt: output.prompt || '',
      type: output.type || 'batch',
      result_files: resultFiles,
      output_files: resultFiles,
      image_paths: imagePaths,
      requested_image_count: output.requestedImageCount || Math.max(resultFiles.length, imagePaths.length, counts.total || 0),
      params: { batch_id: output.batchId }
    }, resultNodeId);
  }

  async function pollBatch(resultNodeId, batchId) {
    if (!batchId) return;
    try {
      const summary = await DesktopApi.getBatch(batchId);
      applyBatchSummary(summary, resultNodeId);
      if (summary.status !== 'completed' && summary.status !== 'missing') {
        scheduleBatchPoll(resultNodeId, batchId, 2200);
      } else {
        stopBatchPolling(resultNodeId);
        DesktopHistory.loadHistory().catch(() => {});
      }
    } catch (error) {
      showError(error, resultNodeId);
      scheduleBatchPoll(resultNodeId, batchId, 5000);
    }
  }

  function collectRestoreEntries() {
    const taskEntries = [];
    const batchEntries = [];
    const seenTasks = new Set();
    const seenBatches = new Set();
    const outputs = DesktopState.state.outputs || {};

    function addTask(resultNodeId, taskId, output = {}, options = {}) {
      const id = String(taskId || '').trim();
      if (!id) return;
      const key = `${resultNodeId}:${id}`;
      if (seenTasks.has(key)) return;
      seenTasks.add(key);
      taskEntries.push({ resultNodeId, taskId: id, output, force: options.force === true });
    }

    function addBatch(resultNodeId, batchId, output = {}) {
      const id = String(batchId || '').trim();
      if (!id) return;
      const key = `${resultNodeId}:${id}`;
      if (seenBatches.has(key)) return;
      seenBatches.add(key);
      batchEntries.push({ resultNodeId, batchId: id, output });
    }

    Object.entries(outputs).forEach(([resultNodeId, output]) => {
      if (!output || typeof output !== 'object') return;
      const taskId = output.taskId || output.task_id || '';
      if (taskId && outputHasVisibleState(output)) {
        addTask(resultNodeId, taskId, output);
      }
      const batchId = output.batchId || output.batch_id || '';
      const batchStatus = String(output.batchStatus || output.batch_status || '');
      if (batchId && !['completed', 'missing'].includes(batchStatus)) {
        addBatch(resultNodeId, batchId, output);
      }
    });

    const selectedTaskId = String(DesktopState.state.selectedTaskId || '').trim();
    if (selectedTaskId) {
      addTask(DEFAULT_RESULT_NODE_ID, selectedTaskId, outputs[DEFAULT_RESULT_NODE_ID] || {}, { force: true });
    }

    return { taskEntries, batchEntries };
  }

  async function restoreTaskEntry(entry) {
    const { resultNodeId, taskId, output } = entry;
    if (outputHasVisibleState(output)) {
      applyPersistedOutputSnapshot(resultNodeId, output);
    }
    try {
      const task = await DesktopApi.getStatus(taskId);
      applyTask({ ...task, task_id: taskId }, resultNodeId);
      if (DesktopState.isInFlight(task.status)) {
        scheduleResultPoll(resultNodeId, taskId, task.status === 'queued' ? 1800 : 1200);
      } else {
        stopResultPolling(resultNodeId);
        DesktopHistory.loadHistory().catch(() => {});
      }
      return task;
    } catch (error) {
      showError(error, resultNodeId);
      if (DesktopState.isInFlight(output?.status)) {
        scheduleResultPoll(resultNodeId, taskId, 5000);
      }
      throw error;
    }
  }

  async function restoreBatchEntry(entry) {
    const { resultNodeId, batchId, output } = entry;
    if (outputHasVisibleState(output)) {
      applyPersistedOutputSnapshot(resultNodeId, output);
    }
    try {
      const summary = await DesktopApi.getBatch(batchId);
      applyBatchSummary(summary, resultNodeId);
      if (summary.status !== 'completed' && summary.status !== 'missing') {
        scheduleBatchPoll(resultNodeId, batchId, 1600);
      } else {
        stopBatchPolling(resultNodeId);
        DesktopHistory.loadHistory().catch(() => {});
      }
      return summary;
    } catch (error) {
      showError(error, resultNodeId);
      const batchStatus = String(output?.batchStatus || output?.batch_status || '');
      if (batchStatus && !['completed', 'missing'].includes(batchStatus)) {
        scheduleBatchPoll(resultNodeId, batchId, 5000);
      }
      throw error;
    }
  }

  async function restoreActiveTasks() {
    const { taskEntries, batchEntries } = collectRestoreEntries();
    if (!taskEntries.length && !batchEntries.length) return [];
    const results = await Promise.allSettled([
      ...taskEntries.map(restoreTaskEntry),
      ...batchEntries.map(restoreBatchEntry)
    ]);
    return results;
  }

  async function controlBatch(resultNodeId, action) {
    const output = getOutputState(resultNodeId);
    if (!output.batchId) throw new Error('没有正在跟踪的批量任务');
    const summary = await DesktopApi.controlBatch(output.batchId, action);
    applyBatchSummary(summary, resultNodeId);
    showTransientMessage(summary.message || '批量状态已更新。', action === 'cancel' ? 'error' : 'success');
    if (summary.status !== 'completed' && summary.status !== 'missing') {
      scheduleBatchPoll(resultNodeId, output.batchId, 1200);
    } else {
      stopBatchPolling(resultNodeId);
      DesktopHistory.loadHistory().catch(() => {});
    }
    return summary;
  }

  async function submitAndTrack() {
    stopPolling();
    return submitFromResultNode(DEFAULT_RESULT_NODE_ID);
  }

  async function submitFromResultNode(resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const resolvedResultNodeId = DesktopCanvas.resolveResultNodeIdForRun?.(resultNodeId) || resultNodeId;
    stopResultPolling(resolvedResultNodeId);
    stopBatchPolling(resolvedResultNodeId);
    const config = DesktopCanvas.readConfigForResult(resolvedResultNodeId);
    if (!String(config.prompt || '').trim()) {
      throw new Error('请先连接文本节点作为提示词');
    }
    if (config.batchMode) {
      const promptCount = Array.isArray(config.batchPrompts) && config.batchPrompts.length
        ? config.batchPrompts.map(item => String(item || '').trim()).filter(Boolean).length
        : String(config.prompt || '').split(/\n\s*\n|\r?\n/).map(item => item.trim()).filter(Boolean).length;
      if (promptCount < 2) throw new Error('批量模式至少需要 2 条提示词');
    }
    DesktopCanvas.ensureImageOutputsForConfig?.(resolvedResultNodeId, config);
    return submitConfigToResult(config, resolvedResultNodeId);
  }

  async function submitConfigToResult(config, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    stopResultPolling(resultNodeId);
    stopBatchPolling(resultNodeId);
    const pendingOutput = getOutputState(resultNodeId);
    if (config.expectedImageOutputCount) {
      pendingOutput.requestedImageCount = config.expectedImageOutputCount;
    }
    pendingOutput.taskId = '';
    pendingOutput.batchId = '';
    pendingOutput.error = '';
    pendingOutput.displayError = '';
    pendingOutput.rawError = '';
    pendingOutput.errorCode = '';
    pendingOutput.errorCategory = '';
    pendingOutput.fileManifest = null;
    resetOutputTiming(pendingOutput);
    applyTask({
      task_id: '',
      status: 'queued',
      progress_text: '正在提交后台任务...',
      progress: 0,
      prompt: config.prompt,
      type: config.provider,
      params: config.params || {},
      requested_image_count: config.expectedImageOutputCount || undefined
    }, resultNodeId);
    if (config.batchMode) {
      const data = await DesktopApi.submitBatchConfig(config);
      const batchId = data?.batch_id;
      if (!batchId) throw new Error('后端没有返回 batch_id');
      const output = getOutputState(resultNodeId);
      output.batchId = batchId;
      output.taskId = '';
      output.prompt = config.prompt;
      output.type = config.provider;
      resetOutputTiming(output);
      applyBatchSummary(data, resultNodeId);
      scheduleBatchPoll(resultNodeId, batchId, 1200);
      DesktopHistory.loadHistory().catch(() => {});
      return data;
    }
    const data = await DesktopApi.submitTaskConfig(config);
    const taskId = data?.task_id;
    if (!taskId) throw new Error('后端没有返回 task_id');
    const output = getOutputState(resultNodeId);
    output.taskId = taskId;
    output.prompt = config.prompt;
    output.type = config.provider;
    resetOutputTiming(output);
    if (resultNodeId === DEFAULT_RESULT_NODE_ID || resultNodeId === 'output') DesktopState.saveLastTask(taskId);
    applyTask({
      task_id: taskId,
      status: data.status || 'queued',
      progress_text: data.message || '任务已提交，等待生成...',
      progress: Number(data.progress || 0) || 0,
      prompt: config.prompt,
      type: config.provider,
      params: config.params || {}
    }, resultNodeId);
    scheduleResultPoll(resultNodeId, taskId, 900);
    DesktopHistory.loadHistory().catch(() => {});
    return data;
  }

  function trackRetriedTask(task, resultNodeId = DEFAULT_RESULT_NODE_ID) {
    const taskId = task?.task_id || task?.taskId;
    if (!taskId) throw new Error('后端没有返回 task_id');
    stopResultPolling(resultNodeId);
    stopBatchPolling(resultNodeId);
    const requestedCount = Number(task?.requested_image_count || task?.requestedImageCount || 0);
    if (requestedCount > 0) {
      DesktopCanvas.ensureImageOutputsForConfig?.(resultNodeId, {
        nodeId: resultNodeId,
        provider: task.type || task.provider || 'gpt',
        prompt: task.prompt || '',
        imageCount: requestedCount,
        expectedImageOutputCount: requestedCount,
        params: task.params || {}
      });
    }
    const output = getOutputState(resultNodeId);
    output.taskId = taskId;
    output.prompt = task.prompt || output.prompt || '';
    output.type = task.type || output.type || 'gpt';
    resetOutputTiming(output);
    if (resultNodeId === DEFAULT_RESULT_NODE_ID || resultNodeId === 'output') DesktopState.saveLastTask(taskId);
    applyTask({
      ...task,
      task_id: taskId,
      status: task.status || 'queued',
      progress_text: task.message || task.progress_text || '重跑任务已提交，等待生成...'
    }, resultNodeId);
    scheduleResultPoll(resultNodeId, taskId, 900);
    DesktopHistory.loadHistory().catch(() => {});
    return task;
  }

  function showError(error, resultNodeId = DEFAULT_RESULT_NODE_ID, options = {}) {
    const message = error?.message || String(error || '未知错误');
    showTransientMessage(message, 'error');
    const output = getOutputState(resultNodeId);
    const shouldApplyToOutput = options.applyToOutput === true || !output.taskId || DesktopState.isFailure(output.status);
    if (!shouldApplyToOutput) return;
    const task = {
      task_id: '',
      status: 'failed',
      stage: '',
      progress_text: message,
      error: message
    };
    applyTask(task, resultNodeId);
  }

  function showTransientMessage(message, tone = 'info') {
    if (!els.deskStatusMessage) return;
    if (tone === 'error') {
      statusTipTask = buildStatusTipTask({
        status: 'failed',
        progress_text: message || DEFAULT_STATUS_MESSAGE,
        display_error: message || DEFAULT_STATUS_MESSAGE,
        raw_error: message || ''
      });
    }
    els.deskStatusMessage.textContent = message || DEFAULT_STATUS_MESSAGE;
    els.deskStatusMessage.dataset.tone = tone;
    if (statusTipOpen) renderStatusTip();
    if (transientTimer) window.clearTimeout(transientTimer);
    transientTimer = window.setTimeout(() => {
      transientTimer = null;
      renderBottomStatus();
    }, 3600);
  }

  function getCancelableTaskEntries() {
    const entries = [];
    Object.entries(DesktopState.state.outputs || {}).forEach(([resultNodeId, output]) => {
      if (output?.taskId && DesktopState.isInFlight(output.status)) {
        entries.push({ kind: 'task', resultNodeId, taskId: output.taskId });
      }
      if (output?.batchId && !['completed', 'missing'].includes(String(output.batchStatus || ''))) {
        entries.push({ kind: 'batch', resultNodeId, batchId: output.batchId });
      }
    });
    if (DesktopState.state.selectedTaskId && DesktopState.isInFlight(DesktopState.state.output.status)) {
      entries.push({ kind: 'task', resultNodeId: DEFAULT_RESULT_NODE_ID, taskId: DesktopState.state.selectedTaskId });
    }
    const seen = new Set();
    return entries.filter(entry => {
      const key = `${entry.kind}:${entry.resultNodeId}:${entry.taskId || entry.batchId}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  async function cancelActiveTasks() {
    const entries = getCancelableTaskEntries();
    if (!entries.length) {
      showTransientMessage('没有正在生成的任务。');
      return;
    }
    const results = await Promise.allSettled(entries.map(async entry => {
      if (entry.kind === 'batch') {
        const summary = await DesktopApi.controlBatch(entry.batchId, 'cancel');
        applyBatchSummary(summary, entry.resultNodeId);
        stopBatchPolling(entry.resultNodeId);
        return summary;
      }
      const task = await DesktopApi.cancelTask(entry.taskId);
      applyTask({ ...task, task_id: entry.taskId }, entry.resultNodeId);
      stopResultPolling(entry.resultNodeId);
      return task;
    }));
    stopPolling();
    pollTimers.forEach(timer => window.clearTimeout(timer));
    pollTimers.clear();
    batchPollTimers.forEach(timer => window.clearTimeout(timer));
    batchPollTimers.clear();
    const failed = results.filter(result => result.status === 'rejected').length;
    if (failed) {
      showTransientMessage(`${entries.length - failed}/${entries.length} 个任务已取消，${failed} 个取消失败。`);
    } else {
      showTransientMessage(entries.length > 1 ? `${entries.length} 个任务已取消。` : '任务已取消。');
    }
    DesktopHistory.loadHistory().catch(() => {});
  }

  function bindActions() {
    els.deskStatusMessage?.addEventListener('click', event => {
      event.stopPropagation();
      toggleStatusTip();
    });
    els.deskStatusTipClose?.addEventListener('click', event => {
      event.stopPropagation();
      closeStatusTip();
      els.deskStatusMessage?.focus();
    });
    els.deskStatusTipCopy?.addEventListener('click', async event => {
      event.stopPropagation();
      try {
        await navigator.clipboard.writeText(statusTipRawText || els.deskStatusTipRaw?.textContent || '');
        showTransientMessage('状态详情已复制。', 'success');
        setStatusTipCopyState('copied');
      } catch (error) {
        showTransientMessage('复制失败。', 'warning');
        setStatusTipCopyState('error');
      }
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && statusTipOpen) closeStatusTip();
    });
    document.addEventListener('click', event => {
      if (!statusTipOpen) return;
      const panel = els.deskStatusTip;
      const trigger = els.deskStatusMessage;
      if (panel?.contains(event.target) || trigger?.contains(event.target)) return;
      closeStatusTip();
    });
    window.addEventListener('resize', () => {
      if (statusTipOpen) updateStatusTipPosition();
    });

    els.deskStopBtn?.addEventListener('click', async () => {
      try {
        els.deskStopBtn.disabled = true;
        await cancelActiveTasks();
      } catch (error) {
        showError(error);
      } finally {
        els.deskStopBtn.disabled = false;
      }
    });

    document.addEventListener('click', async event => {
      const sendButton = event.target.closest('[data-send-original], #deskSendOriginalBtn');
      if (sendButton) {
        const node = sendButton.closest('.desk-node[data-node-id]');
        const resultNodeId = node?.dataset.nodeId || 'output';
        const batchAction = sendButton.dataset.batchAction;
        if (batchAction) {
          controlBatch(resultNodeId, batchAction).catch(error => showError(error, resultNodeId));
          return;
        }
        try {
          const files = getExportFiles(resultNodeId);
          if (!files.length) throw new Error('没有可发送的原图');
          const baseItem = getPrimaryItem(resultNodeId);
          sendButton.disabled = true;
          sendButton.dataset.busy = '1';
          for (let index = 0; index < files.length; index += 1) {
            const file = files[index];
            sendButton.textContent = files.length > 1 ? `发送中 ${index + 1}/${files.length}` : '发送中';
            await DesktopApi.exportTelegram({
              ...baseItem,
              primaryFile: file,
              result_file: file,
              output_file: file
            });
          }
          showTransientMessage(files.length > 1 ? `${files.length} 张原图已发送到 Telegram。` : '原图已发送到 Telegram。');
        } catch (error) {
          showError(error, resultNodeId);
        } finally {
          delete sendButton.dataset.busy;
          renderActions(resultNodeId);
        }
        return;
      }

      const copyButton = event.target.closest('[data-copy-prompt]');
      if (copyButton) {
        const node = copyButton.closest('.desk-node[data-node-id]');
        const resultNodeId = node?.dataset.nodeId || 'output';
        const batchAction = copyButton.dataset.batchAction;
        if (batchAction) {
          controlBatch(resultNodeId, batchAction).catch(error => showError(error, resultNodeId));
          return;
        }
        try {
          await navigator.clipboard.writeText(getOutputState(resultNodeId).prompt || DesktopState.state.prompt || '');
          showTransientMessage('提示词已复制。');
        } catch (error) {
          showError(new Error('复制失败'), resultNodeId);
        }
        return;
      }

    });
  }

  async function restoreLastTask() {
    return restoreActiveTasks();
  }

  function init() {
    collectElements();
    bindActions();
    const defaultOutput = DesktopState.state.outputs?.[DEFAULT_RESULT_NODE_ID];
    if (defaultOutput?.taskId && outputHasVisibleState(defaultOutput)) {
      applyPersistedOutputSnapshot(DEFAULT_RESULT_NODE_ID, defaultOutput);
    } else {
      resetOutput({ keepTaskId: true });
    }
    startSidecarStatusPolling();
  }

  window.DesktopResults = {
    init,
    submitAndTrack,
    submitFromResultNode,
    submitConfigToResult,
    pollTask,
    restoreLastTask,
    restoreActiveTasks,
    stopPolling,
    showError,
    showTransientMessage,
    refreshSidecarStatus,
    refreshOutputConfigStatus,
    resetOutput,
    renderIdleProviderHint,
    applyTask,
    trackRetriedTask
  };
})();
