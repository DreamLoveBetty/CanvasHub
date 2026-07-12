(function () {
  const SETTINGS_KEY = 'desktop_canvas_settings_v1';
  const DRAFT_KEY = 'desktop_canvas_draft_v1';
  const LAST_TASK_KEY = 'desktop_canvas_last_task_v1';
  const DEFAULT_INPUT_NODE_WIDTH = 720;
  const DEFAULT_INPUT_NODE_HEIGHT = 460;
  const DEFAULT_CANVAS_SCALE = 0.75;
  const CANVAS_VIEW_VERSION = 2;

  const statusLabels = {
    idle: '空闲',
    queued: '排队中',
    preparing: '准备中',
    processing: '生成中',
    fallback_running: '托底中',
    succeeded: '已完成',
    success: '已完成',
    succeeded_no_telegram: '已保存',
    canceled: '已取消',
    failed: '失败',
    telegram_failed: '发送失败'
  };

  const providerLabels = {
    gpt: 'GPT',
    google: 'Google',
    comfy: 'Comfy'
  };

  const state = {
    auth: 'checking',
    provider: 'gpt',
    inputExpanded: true,
    selectedTaskId: '',
    selectedHistoryId: '',
    prompt: '',
    referenceImages: [],
    nodeReferenceImages: {},
    params: {
      ratio: '9:16',
      resolution: '2k',
      quality: 'auto',
      imageCount: 2,
      moderation: 'auto',
      gptTaskType: 'image',
      promptMode: 'smart',
      gptProviderRoute: 'codex',
      gptMainModel: 'gpt-5.5',
      gptModelsByRoute: {
        codex: 'gpt-5.5',
        chatgpt_pool: 'gpt-5-5',
        third_party_image_api: 'gpt-image-2'
      },
      reasoningEffort: 'medium',
      model: 'gemini-3.1-flash-image',
      workflow: '',
      batchMode: false
    },
    output: {
      status: 'idle',
      stage: '',
      progressText: '',
      progress: 0,
      files: [],
      imagePaths: [],
      primaryFile: '',
      primaryImagePath: '',
      type: 'gpt',
      telegramEnabled: true,
      archiveEnabled: true,
      error: ''
    },
    outputs: {
      input: {
        status: 'idle',
        stage: '',
        progressText: '',
        progress: 0,
        files: [],
        imagePaths: [],
        primaryFile: '',
        primaryImagePath: '',
        type: 'gpt',
        error: '',
        taskId: ''
      }
    },
    history: [],
    queueCount: 0,
    todayCount: 0,
    runtimeConfig: {
      hasSavedGptMainModel: false,
      hasSavedReasoningEffort: false,
      resetCanvasViewOnLoad: false
    },
    canvas: {
      x: 0,
      y: 0,
      scale: DEFAULT_CANVAS_SCALE,
      selectedNodeId: '',
      nodes: {
        input: { id: 'input', type: 'input', x: 56, y: 72, width: DEFAULT_INPUT_NODE_WIDTH, height: DEFAULT_INPUT_NODE_HEIGHT }
      },
      edges: []
    }
  };

  function clamp(value, min, max, fallback) {
    const parsed = parseInt(value, 10);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, parsed));
  }

  function normalizeRatio(value, fallback = '9:16') {
    const allowed = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '9:21', '21:9'];
    return allowed.includes(String(value || '').trim()) ? String(value).trim() : fallback;
  }

  function normalizeResolution(value, fallback = '2k') {
    const normalized = String(value || '').trim().toLowerCase();
    return ['1k', '2k', '4k'].includes(normalized) ? normalized : fallback;
  }

  function normalizeGptQuality(value, fallback = 'auto') {
    const normalized = String(value || '').trim().toLowerCase();
    return ['auto', 'low', 'medium', 'high'].includes(normalized) ? normalized : fallback;
  }

  function normalizeModeration(value, fallback = 'auto') {
    const normalized = String(value || '').trim().toLowerCase();
    return normalized === 'low' ? 'low' : fallback;
  }

  function normalizePromptMode(value, fallback = 'smart') {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'faithful' || normalized === 'literal') return 'faithful';
    if (normalized === 'web_search' || normalized === 'search' || normalized === 'research') return 'web_search';
    if (normalized === 'smart') return 'smart';
    return fallback;
  }

  function normalizeGptTaskType(value, fallback = 'image') {
    const normalized = String(value || '').trim().toLowerCase();
    if (['ppt', 'powerpoint', 'presentation'].includes(normalized)) return 'ppt';
    if (['psd', 'photoshop'].includes(normalized)) return 'psd';
    if (['image', 'img', 'generation'].includes(normalized)) return 'image';
    return fallback;
  }

  function normalizeGptProviderRoute(value, fallback = 'codex') {
    const normalized = String(value || '').trim().toLowerCase();
    if (['managed_codex_oauth', 'managed_codex', 'managed_oauth', 'codex_oauth', 'oauth_codex'].includes(normalized)) return 'codex';
    if (['chatgpt_pool', 'pool', 'sidecar', 'web_api', 'account_pool'].includes(normalized)) return 'chatgpt_pool';
    if (['third_party_image_api', 'third_party_api', 'third_party', 'external_api', 'yunwu'].includes(normalized)) return 'third_party_image_api';
    if (['codex', 'local', 'local_codex'].includes(normalized)) return 'codex';
    return fallback;
  }

  function normalizeBoolean(value, fallback = false) {
    if (typeof value === 'boolean') return value;
    if (value == null || value === '') return !!fallback;
    const normalized = String(value).trim().toLowerCase();
    if (['1', 'true', 'yes', 'on', 'enabled', '开启'].includes(normalized)) return true;
    if (['0', 'false', 'no', 'off', 'disabled', '关闭'].includes(normalized)) return false;
    return !!fallback;
  }

  function normalizeGptMainModel(value, fallback = 'gpt-5.5') {
    const normalized = String(value || '').trim();
    return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(normalized) ? normalized : fallback;
  }

  function normalizeGoogleModel(value, fallback = 'gemini-3.1-flash-image') {
    const normalized = String(value || '').trim();
    if (normalized === 'gemini-3-pro-image-preview') return 'gemini-3-pro-image';
    if (normalized === 'gemini-3.1-flash-image-preview') return 'gemini-3.1-flash-image';
    return normalized || fallback;
  }

  function normalizeReasoningEffort(value, fallback = 'medium') {
    const normalized = String(value || '').trim().toLowerCase();
    return ['none', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'].includes(normalized) ? normalized : fallback;
  }

  function getStatusLabel(status) {
    return statusLabels[String(status || 'idle')] || String(status || '空闲');
  }

  function getProviderLabel(provider) {
    return providerLabels[String(provider || 'gpt')] || provider;
  }

  function isInFlight(status) {
    return ['queued', 'preparing', 'processing', 'fallback_running'].includes(String(status || ''));
  }

  function isSuccess(status) {
    return ['succeeded', 'success', 'succeeded_no_telegram'].includes(String(status || ''));
  }

  function isFailure(status) {
    return ['failed', 'telegram_failed'].includes(String(status || ''));
  }

  function estimateProgress(task) {
    const status = String(task?.status || state.output.status || 'idle');
    const stage = String(task?.stage || state.output.stage || '');
    if (isSuccess(status)) return 100;
    if (isFailure(status)) return 100;
    if (status === 'canceled') return 100;
    const explicitProgress = Number(
      task?.progress ?? task?.progress_percent ?? task?.progressPercent ?? state.output.progress
    );
    if (Number.isFinite(explicitProgress) && explicitProgress > 0) {
      const normalized = explicitProgress <= 1 ? explicitProgress * 100 : explicitProgress;
      return Math.max(1, Math.min(99, Math.round(normalized)));
    }
    if (status === 'queued') return 12;
    if (status === 'preparing') return 24;
    if (status === 'fallback_running') return 66;
    if (stage.includes('sending') || stage.includes('telegram')) return 88;
    if (stage === 'upscaling') {
      const text = String(task?.progress_text || '');
      const match = text.match(/(\d+)\s*\/\s*(\d+)/);
      if (match) {
        const done = Math.max(0, parseInt(match[1], 10) || 0);
        const total = Math.max(1, parseInt(match[2], 10) || 1);
        return Math.max(18, Math.min(92, Math.round(18 + (done / total) * 72)));
      }
      return 36;
    }
    if (stage === 'generating_images') {
      const text = String(task?.progress_text || '');
      const match = text.match(/(\d+)\s*\/\s*(\d+)/);
      if (match) {
        const done = Math.max(0, parseInt(match[1], 10) || 0);
        const total = Math.max(1, parseInt(match[2], 10) || 1);
        return Math.max(52, Math.min(86, Math.round(52 + (done / total) * 34)));
      }
      return 72;
    }
    if (stage.includes('calling')) return 52;
    if (status === 'processing') return 68;
    return 0;
  }

  function referenceUrl(ref) {
    return String(ref?.url || ref?.imageUrl || '').trim();
  }

  function isPersistableReference(ref) {
    const url = referenceUrl(ref);
    if (!url) return false;
    return !url.startsWith('blob:') && !url.startsWith('data:');
  }

  function sanitizeReference(ref) {
    if (!isPersistableReference(ref)) return null;
    const url = referenceUrl(ref);
    return {
      id: String(ref?.id || ref?.assetId || ref?.taskId || url),
      assetId: String(ref?.assetId || ref?.asset_id || ref?.id || ''),
      taskId: String(ref?.taskId || ref?.task_id || ''),
      name: String(ref?.name || ref?.title || ref?.file || '参考图'),
      title: String(ref?.title || ref?.name || '参考图'),
      prompt: String(ref?.prompt || ''),
      type: String(ref?.type || ref?.mimeType || 'image/png'),
      source: String(ref?.source || ''),
      file: String(ref?.file || ''),
      url,
      imageUrl: url,
      base64: '',
      imageData: ''
    };
  }

  function sanitizeReferences(refs) {
    return (Array.isArray(refs) ? refs : [])
      .map(sanitizeReference)
      .filter(Boolean)
      .slice(0, 8);
  }

  function sanitizeReferenceMap(map) {
    if (!map || typeof map !== 'object') return {};
    return Object.entries(map).reduce((acc, [nodeId, refs]) => {
      const clean = sanitizeReferences(refs);
      if (clean.length) acc[nodeId] = clean;
      return acc;
    }, {});
  }

  function sanitizeOutputState(output) {
    if (!output || typeof output !== 'object') return output;
    const message = String(output.displayError || output.error || output.progressText || '');
    const hasStaleLocalUpscaleError = output.taskId
      && String(output.status || '') === 'failed'
      && /请先连接(?:或上传)?一张图片/.test(message);
    if (!hasStaleLocalUpscaleError) return output;
    return {
      ...output,
      status: 'idle',
      stage: '',
      progressText: '',
      progress: 0,
      error: '',
      displayError: '',
      rawError: '',
      errorCode: '',
      errorCategory: '',
      taskId: ''
    };
  }

  function sanitizeOutputMap(outputs) {
    if (!outputs || typeof outputs !== 'object') return {};
    return Object.entries(outputs).reduce((acc, [nodeId, output]) => {
      acc[nodeId] = sanitizeOutputState(output);
      return acc;
    }, {});
  }

  function saveSettings() {
    state.params.model = normalizeGoogleModel(state.params.model);
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({
        canvasViewVersion: CANVAS_VIEW_VERSION,
        provider: state.provider,
        inputExpanded: state.inputExpanded,
        referenceImages: sanitizeReferences(state.referenceImages),
        nodeReferenceImages: sanitizeReferenceMap(state.nodeReferenceImages),
        params: { ...state.params, model: normalizeGoogleModel(state.params.model) },
        canvas: state.canvas,
        output: {
          telegramEnabled: state.output.telegramEnabled,
          archiveEnabled: state.output.archiveEnabled
        },
        outputs: state.outputs
      }));
    } catch (e) {}
  }

  function loadSettings() {
    try {
      const parsed = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
      const resetCanvasView = Number(parsed.canvasViewVersion || 0) < CANVAS_VIEW_VERSION;
      state.runtimeConfig.resetCanvasViewOnLoad = resetCanvasView;
      if (parsed.provider) state.provider = parsed.provider;
      if (typeof parsed.inputExpanded === 'boolean') state.inputExpanded = parsed.inputExpanded;
      if (Array.isArray(parsed.referenceImages)) {
        state.referenceImages = sanitizeReferences(parsed.referenceImages);
      }
      if (parsed.nodeReferenceImages && typeof parsed.nodeReferenceImages === 'object') {
        state.nodeReferenceImages = sanitizeReferenceMap(parsed.nodeReferenceImages);
      }
      if (parsed.params && typeof parsed.params === 'object') {
        state.runtimeConfig.hasSavedGptMainModel = Object.prototype.hasOwnProperty.call(parsed.params, 'gptMainModel');
        state.runtimeConfig.hasSavedReasoningEffort = Object.prototype.hasOwnProperty.call(parsed.params, 'reasoningEffort');
        state.params = { ...state.params, ...parsed.params };
        state.params.model = normalizeGoogleModel(state.params.model);
        state.params.gptModelsByRoute = {
          codex: normalizeGptMainModel(state.params.gptModelsByRoute?.codex || state.params.gptMainModel, 'gpt-5.5'),
          chatgpt_pool: normalizeGptMainModel(state.params.gptModelsByRoute?.chatgpt_pool, 'gpt-5-5'),
          third_party_image_api: normalizeGptMainModel(state.params.gptModelsByRoute?.third_party_image_api, 'gpt-image-2')
        };
      }
      if (parsed.canvas && typeof parsed.canvas === 'object') {
        const parsedNodes = parsed.canvas.nodes && typeof parsed.canvas.nodes === 'object'
          ? parsed.canvas.nodes
          : null;
        state.canvas = {
          ...state.canvas,
          ...parsed.canvas,
          nodes: parsedNodes ? { ...parsedNodes } : state.canvas.nodes,
          selectedNodeId: parsed.canvas.selectedNodeId || '',
          edges: Array.isArray(parsed.canvas.edges) ? parsed.canvas.edges : []
        };
        Object.keys(state.canvas.nodes).forEach((nodeId) => {
          const node = state.canvas.nodes[nodeId];
          node.id = node.id || nodeId;
          node.type = node.type || (nodeId.startsWith('output') ? 'output' : 'input');
          if (node.type === 'input' && (Number(node.height) || 0) !== DEFAULT_INPUT_NODE_HEIGHT) {
            node.height = DEFAULT_INPUT_NODE_HEIGHT;
          }
          if (node.type === 'input' && (Number(node.width) || 0) !== DEFAULT_INPUT_NODE_WIDTH) {
            node.width = DEFAULT_INPUT_NODE_WIDTH;
          }
        });
      }
      if (resetCanvasView) state.canvas.scale = DEFAULT_CANVAS_SCALE;
      if (parsed.outputs && typeof parsed.outputs === 'object') {
        state.outputs = { ...state.outputs, ...sanitizeOutputMap(parsed.outputs) };
      }
      if (parsed.output && typeof parsed.output === 'object') {
        state.output.telegramEnabled = parsed.output.telegramEnabled !== false;
        state.output.archiveEnabled = parsed.output.archiveEnabled !== false;
      }
    } catch (e) {}
  }

  function saveDraft() {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        prompt: state.prompt,
        updatedAt: Date.now()
      }));
    } catch (e) {}
  }

  function loadDraft() {
    try {
      const parsed = JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}');
      if (typeof parsed.prompt === 'string') state.prompt = parsed.prompt;
    } catch (e) {}
  }

  function applyGptRuntimeConfig(config = {}) {
    const provider = config.gpt_provider || config;
    const defaultModel = normalizeGptMainModel(provider.image_main_model, state.params.gptMainModel || 'gpt-5.5');
    const defaultEffort = normalizeReasoningEffort(provider.reasoning_effort, state.params.reasoningEffort || 'medium');
    if (!state.runtimeConfig.hasSavedGptMainModel) {
      state.params.gptMainModel = defaultModel;
    }
    if (!state.runtimeConfig.hasSavedReasoningEffort) {
      state.params.reasoningEffort = defaultEffort;
    }
  }

  function saveLastTask(taskId) {
    if (!taskId) return;
    state.selectedTaskId = taskId;
    try {
      localStorage.setItem(LAST_TASK_KEY, taskId);
    } catch (e) {}
  }

  function loadLastTask() {
    try {
      state.selectedTaskId = localStorage.getItem(LAST_TASK_KEY) || '';
    } catch (e) {}
  }

  window.DesktopState = {
    state,
    DEFAULT_CANVAS_SCALE,
    clamp,
    normalizeRatio,
    normalizeResolution,
    normalizeGoogleModel,
    normalizeGptQuality,
    normalizeModeration,
    normalizePromptMode,
    normalizeGptTaskType,
    normalizeGptProviderRoute,
    normalizeBoolean,
    normalizeGptMainModel,
    normalizeReasoningEffort,
    getStatusLabel,
    getProviderLabel,
    isInFlight,
    isSuccess,
    isFailure,
    estimateProgress,
    saveSettings,
    loadSettings,
    saveDraft,
    loadDraft,
    applyGptRuntimeConfig,
    saveLastTask,
    loadLastTask
  };
})();
