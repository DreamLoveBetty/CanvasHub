// Model node templates, model catalog and form adapters for existing GPT/Google/Comfy/video/file/upscale controls. No task submission.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    ASPECT_RATIO_OPTIONS,
    COMFY_PIXEL_STEP,
    DEFAULT_COMFY_PIXEL_HEIGHT,
    DEFAULT_COMFY_PIXEL_WIDTH,
    DEFAULT_GOOGLE_MODEL,
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    DEFAULT_VIDEO_NODE_HEIGHT,
    DEFAULT_VIDEO_NODE_WIDTH,
    GOOGLE_MODEL_OPTIONS,
    GPT_MAIN_MODEL_OPTIONS,
    GPT_PROMPT_MODE_OPTIONS,
    GPT_PROVIDER_ROUTE_OPTIONS,
    GPT_REASONING_OPTIONS,
    GPT_ROUTE_PRESENTATION,
    GPT_TASK_TYPE_OPTIONS,
    MAX_COMFY_PIXEL_SIZE,
    MAX_VIDEO_INFERENCE_NODE_HEIGHT,
    MAX_VIDEO_INFERENCE_NODE_WIDTH,
    MAX_VIDEO_NODE_HEIGHT,
    MAX_VIDEO_NODE_WIDTH,
    MIN_COMFY_PIXEL_SIZE,
    MIN_VIDEO_INFERENCE_NODE_HEIGHT,
    MIN_VIDEO_INFERENCE_NODE_WIDTH,
    MIN_VIDEO_NODE_HEIGHT,
    MIN_VIDEO_NODE_WIDTH,
    UPSCALE_MODEL_OPTIONS,
    VIDEO_INFERENCE_LAYOUT_VERSION,
    VIDEO_NODE_LAYOUT_VERSION,
    applyAllNodeLayouts,
    applyCanvasTransform,
    applyNodeLayout,
    applyNodeSelection,
    clamp,
    comfyWorkflowCatalogRef,
    discardFloatingSwellState,
    els,
    ensureNodeEdgeHandles,
    escapeHtml,
    getConnectedImageReferences,
    getConnectedTextNodes,
    getNodeElement,
    gptModelCatalogRef,
    progressView,
    selectNode,
    updateInputProgressOverlay,
    updateLinkPath,
  }) {


    function ratioOptionsHtml(selected = '9:16') {
    return ASPECT_RATIO_OPTIONS.map(ratio => `<option${ratio === selected ? ' selected' : ''}>${ratio}</option>`).join('');
  }

    function googleModelOptionsHtml(selected = DEFAULT_GOOGLE_MODEL) {
    const normalized = typeof DesktopState.normalizeGoogleModel === 'function'
      ? DesktopState.normalizeGoogleModel(selected, DEFAULT_GOOGLE_MODEL)
      : (String(selected || '').trim() || DEFAULT_GOOGLE_MODEL);
    return GOOGLE_MODEL_OPTIONS
      .map(item => `<option value="${escapeHtml(item.value)}"${item.value === normalized ? ' selected' : ''}>${escapeHtml(item.label)}</option>`)
      .join('');
  }

    function imageCountOptionsHtml(selected = 2) {
    const current = DesktopState.clamp(selected, 1, 8, 2);
    return Array.from({ length: 8 }, (_, index) => {
      const count = index + 1;
      return `<option value="${count}"${count === current ? ' selected' : ''}>${count}张</option>`;
    }).join('');
  }

    function optionListHtml(options, selected) {
    const selectedValue = String(selected ?? '');
    return options
      .map(item => `<option value="${escapeHtml(item.value)}"${String(item.value) === selectedValue ? ' selected' : ''}>${escapeHtml(item.label)}</option>`)
      .join('');
  }

    function fallbackGptModelOptions(route) {
    if (route === 'chatgpt_pool') {
      return [{ value: 'gpt-5-5', label: 'GPT-5.5' }];
    }
    if (route === 'third_party_image_api') {
      return [{ value: 'gpt-image-2', label: 'gpt-image-2' }];
    }
    return GPT_MAIN_MODEL_OPTIONS;
  }

    function gptRouteCatalog(route) {
    const normalized = DesktopState.normalizeGptProviderRoute(route, 'codex');
    return gptModelCatalogRef.current?.routes?.[normalized] || null;
  }

    function gptModelOptionsForRoute(route) {
    const catalog = gptRouteCatalog(route);
    if (catalog?.available === false) return [];
    const models = Array.isArray(catalog?.models) ? catalog.models : [];
    const options = models
      .filter(item => item?.image_generation !== false)
      .map(item => ({
        value: DesktopState.normalizeGptMainModel(item?.id, ''),
        label: String(item?.label || item?.id || '').trim()
      }))
      .filter(item => item.value && item.label);
    if (catalog) return options;
    return fallbackGptModelOptions(DesktopState.normalizeGptProviderRoute(route, 'codex'));
  }

    function gptModelCatalogEntry(route, model) {
    const models = gptRouteCatalog(route)?.models;
    if (!Array.isArray(models)) return null;
    return models.find(item => String(item?.id || '') === String(model || '')) || null;
  }

    function reasoningOption(value) {
    const normalized = String(value || '').trim().toLowerCase();
    const known = GPT_REASONING_OPTIONS.find(item => item.value === normalized);
    return known || (normalized ? { value: normalized, label: normalized } : null);
  }

    function gptReasoningOptionsForModel(route, model) {
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const catalog = gptRouteCatalog(normalizedRoute);
    if (!catalog) return normalizedRoute === 'codex' ? GPT_REASONING_OPTIONS : [];
    const entry = gptModelCatalogEntry(normalizedRoute, model);
    return (Array.isArray(entry?.reasoning_efforts) ? entry.reasoning_efforts : [])
      .map(reasoningOption)
      .filter(Boolean);
  }

    function selectedReasoningForModel(params, route, model, options) {
    const values = new Set(options.map(item => item.value));
    const current = DesktopState.normalizeReasoningEffort(params?.reasoningEffort, 'medium');
    const modelDefault = DesktopState.normalizeReasoningEffort(
      gptModelCatalogEntry(route, model)?.default_reasoning_effort,
      'medium'
    );
    return [current, modelDefault, 'medium', options[0]?.value]
      .find(value => value && values.has(value)) || options[0]?.value || 'none';
  }

    function updateGptRoutePresentation(node, route) {
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const catalog = gptRouteCatalog(normalizedRoute);
    const fallback = GPT_ROUTE_PRESENTATION[normalizedRoute] || GPT_ROUTE_PRESENTATION.codex;
    const modelLabel = normalizedRoute === 'third_party_image_api'
      ? String(catalog?.model_field_label || fallback.modelLabel)
      : fallback.modelLabel;
    const engineLabel = String(catalog?.image_engine?.label || catalog?.image_engine?.id || fallback.engineLabel);
    const label = node.querySelector('[data-gpt-model-field-label]');
    const engine = node.querySelector('[data-gpt-image-engine]');
    if (label) label.textContent = modelLabel;
    if (engine) {
      engine.textContent = engineLabel;
      engine.title = `生图引擎：${engineLabel}`;
    }
    node.dataset.gptModelRole = String(catalog?.model_role || '');
  }

    function applyGptReasoningToNode(node, route, model) {
    const select = node?.querySelector('[data-field="reasoningEffort"], #deskReasoningEffortSelect');
    const params = inputParamsForNode(node);
    if (!select || !params) return 'none';
    const options = gptReasoningOptionsForModel(route, model);
    const selected = selectedReasoningForModel(params, route, model, options);
    select.innerHTML = options.length
      ? optionListHtml(options, selected)
      : '<option value="none">不适用</option>';
    select.value = selected;
    select.disabled = !options.length;
    select.title = options.length ? '' : '当前线路不使用推理强度';
    params.reasoningEffort = selected;
    window.DesktopSelect?.refresh?.(select);
    return selected;
  }

    function selectedGptModelForRoute(params, route, options = gptModelOptionsForRoute(route)) {
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const values = new Set(options.map(item => item.value));
    const routeSelected = DesktopState.normalizeGptMainModel(params?.gptModelsByRoute?.[normalizedRoute], '');
    const current = DesktopState.normalizeGptMainModel(params?.gptMainModel, '');
    const routeDefault = DesktopState.normalizeGptMainModel(gptRouteCatalog(normalizedRoute)?.default_model, '');
    return [routeSelected, current, routeDefault, options[0]?.value]
      .find(value => value && values.has(value)) || options[0]?.value || '';
  }

    function inputParamsForNode(node) {
    if (!node) return null;
    if (node.dataset.nodeId === 'input') return DesktopState.state.params;
    const nodeState = DesktopState.state.canvas.nodes[node.dataset.nodeId];
    if (!nodeState || nodeState.type !== 'input') return null;
    nodeState.params = nodeState.params || {};
    return nodeState.params;
  }

    function applyGptModelRouteToNode(node, route, { rememberPrevious = true } = {}) {
    if (!node) return '';
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const select = node.querySelector('[data-field="gptMainModel"], #deskGptMainModelSelect');
    const params = inputParamsForNode(node);
    if (!select || !params) return '';
    params.gptModelsByRoute = params.gptModelsByRoute && typeof params.gptModelsByRoute === 'object'
      ? { ...params.gptModelsByRoute }
      : {};
    const previousRoute = DesktopState.normalizeGptProviderRoute(select.dataset.modelRoute, '');
    if (rememberPrevious && previousRoute && previousRoute !== normalizedRoute && select.value) {
      params.gptModelsByRoute[previousRoute] = DesktopState.normalizeGptMainModel(select.value, params.gptModelsByRoute[previousRoute] || 'gpt-5.5');
    }
    const options = gptModelOptionsForRoute(normalizedRoute);
    const optionValues = new Set(options.map(item => item.value));
    const currentSelection = DesktopState.normalizeGptMainModel(select.value, '');
    const selected = previousRoute === normalizedRoute && optionValues.has(currentSelection)
      ? currentSelection
      : selectedGptModelForRoute(params, normalizedRoute, options);
    const catalog = gptRouteCatalog(normalizedRoute);
    select.innerHTML = options.length
      ? optionListHtml(options, selected)
      : '<option value="">无可用模型</option>';
    select.value = selected;
    select.dataset.modelRoute = normalizedRoute;
    select.disabled = !options.length || catalog?.available === false;
    select.title = String(catalog?.warning || '');
    params.gptMainModel = selected || '';
    if (selected) params.gptModelsByRoute[normalizedRoute] = selected;
    updateGptRoutePresentation(node, normalizedRoute);
    applyGptReasoningToNode(node, normalizedRoute, selected);
    window.DesktopSelect?.refresh?.(select);
    return selected;
  }

    function applyGptModelCatalog(payload = {}) {
    if (payload?.routes && typeof payload.routes === 'object') {
      gptModelCatalogRef.current = payload;
    }
    document.querySelectorAll('.desk-node--input[data-node-id]').forEach(node => {
      const route = node.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect')?.value || 'codex';
      applyGptModelRouteToNode(node, route, { rememberPrevious: false });
    });
    DesktopState.saveSettings();
    window.requestAnimationFrame(() => window.DesktopSelect?.refreshAll?.());
    return gptModelCatalogRef.current;
  }

    function ratioFromAspect(aspectRatio, fallback = '1:1') {
    const ratioValue = Number(aspectRatio || 1);
    if (!Number.isFinite(ratioValue) || ratioValue <= 0) return fallback;
    const ratioToNumber = ratio => {
      const [w, h] = String(ratio).split(':').map(Number);
      return w && h ? w / h : 1;
    };
    return ASPECT_RATIO_OPTIONS
      .map(ratio => ({ ratio, diff: Math.abs(ratioToNumber(ratio) - ratioValue) }))
      .sort((a, b) => a.diff - b.diff)[0]?.ratio || fallback;
  }

    function updateProviderParamVisibility(root, provider = 'gpt') {
    const current = ['gpt', 'google'].includes(provider) ? provider : 'gpt';
    root?.querySelectorAll('[data-provider-param]').forEach(item => {
      const scopes = String(item.dataset.providerParam || '').split(/\s+/).filter(Boolean);
      item.hidden = scopes.length > 0 && !scopes.includes(current);
    });
  }

    function updateAllProviderParamVisibility() {
    document.querySelectorAll('.desk-node--input[data-node-id]').forEach(node => {
      const provider = node.dataset.nodeId === 'input'
        ? DesktopState.state.provider
        : getProviderFromNode(node);
      updateProviderParamVisibility(node, provider);
    });
  }

    function videoConfigApi() {
    return window.DesktopVideoConfig || null;
  }

    function migrateVideoInferenceNodeLayout(node = {}) {
    let changed = false;
    if (Number(node.videoLayoutVersion || 0) < VIDEO_INFERENCE_LAYOUT_VERSION) {
      const width = Number(node.width);
      const height = Number(node.height);
      const usesLegacyLayout = !Number.isFinite(width)
        || !Number.isFinite(height)
        || (width <= 620 && height >= 540);
      if (usesLegacyLayout) {
        node.width = DEFAULT_VIDEO_INFERENCE_NODE_WIDTH;
        node.height = DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT;
      }
      node.videoLayoutVersion = VIDEO_INFERENCE_LAYOUT_VERSION;
      changed = true;
    }
    const normalizedWidth = clamp(Number(node.width) || DEFAULT_VIDEO_INFERENCE_NODE_WIDTH, MIN_VIDEO_INFERENCE_NODE_WIDTH, MAX_VIDEO_INFERENCE_NODE_WIDTH);
    const normalizedHeight = clamp(Number(node.height) || DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT, MIN_VIDEO_INFERENCE_NODE_HEIGHT, MAX_VIDEO_INFERENCE_NODE_HEIGHT);
    if (node.width !== normalizedWidth || node.height !== normalizedHeight) changed = true;
    node.width = normalizedWidth;
    node.height = normalizedHeight;
    return changed;
  }

    function normalizeVideoInferenceNodeState(node = {}) {
    if (videoConfigApi()?.normalizeNode) {
      videoConfigApi().normalizeNode(node);
    } else {
      node.provider = 'minimax_h3';
      node.mode = node.mode === 'reference_to_video' ? 'reference_to_video' : 'image_to_video';
      node.durationSeconds = Number(node.durationSeconds || 15);
      node.aspectRatio = node.aspectRatio || '3:4';
      node.pixelBudgetMp = Number(node.pixelBudgetMp || 0.8);
      node.pixelWidth = Number(node.pixelWidth || 768);
      node.pixelHeight = Number(node.pixelHeight || 1024);
      node.accelerationMode = node.accelerationMode || 'first_block_cache';
      node.firstBlockCacheThreshold = Number(node.firstBlockCacheThreshold || 0.08);
      node.steps = Number(node.steps || 20);
      node.crf = Number(node.crf || 23);
      delete node.denoise;
      delete node.seed;
    }
    migrateVideoInferenceNodeLayout(node);
    return node;
  }

    function inputNodeHtml(nodeId) {
    const nodeState = DesktopState.state.canvas.nodes[nodeId] || {};
    const defaults = nodeId === 'input'
      ? (DesktopState.state.params || {})
      : (nodeState.params || DesktopState.state.params || {});
    const provider = ['gpt', 'google'].includes(nodeState.provider)
      ? nodeState.provider
      : (nodeId === 'input' ? DesktopState.state.provider : 'gpt');
    const outputControls = nodeId === 'input'
      ? (DesktopState.state.output || {})
      : (nodeState.output || DesktopState.state.output || {});
    const archiveChecked = outputControls.archiveEnabled !== false;
    const telegramChecked = outputControls.telegramEnabled !== false;
    const batchChecked = !!(defaults.batchMode ?? nodeState.batchMode);
    const gptRoute = DesktopState.normalizeGptProviderRoute(defaults.gptProviderRoute, 'codex');
    const gptModelOptions = gptModelOptionsForRoute(gptRoute);
    const selectedGptModel = selectedGptModelForRoute(defaults, gptRoute, gptModelOptions);
    const routeCatalog = gptRouteCatalog(gptRoute);
    const routePresentation = GPT_ROUTE_PRESENTATION[gptRoute] || GPT_ROUTE_PRESENTATION.codex;
    const modelFieldLabel = gptRoute === 'third_party_image_api'
      ? String(routeCatalog?.model_field_label || routePresentation.modelLabel)
      : routePresentation.modelLabel;
    const imageEngineLabel = String(routeCatalog?.image_engine?.label || routeCatalog?.image_engine?.id || routePresentation.engineLabel);
    const reasoningOptions = gptReasoningOptionsForModel(gptRoute, selectedGptModel);
    const selectedReasoning = selectedReasoningForModel(defaults, gptRoute, selectedGptModel, reasoningOptions);
    return `
      <section class="desk-node desk-node--input desk-glass" data-node-id="${nodeId}" aria-label="模型输入节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow">模型输入</p>
            <h1>选择模型并组织提示词</h1>
          </div>
          <div class="desk-node-tools">
            <span class="desk-status-pill" data-output-status>空闲</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${nodeId}" title="连接到图片节点" aria-label="连接输出"></button>
        <button type="button" class="desk-port desk-port--in desk-port--image-in" data-port="in" data-node-id="${nodeId}" title="连接图片或文本节点到这里" aria-label="连接图片或文本输入"></button>
        <div class="desk-segment" role="tablist" aria-label="选择模型提供方">
          <button type="button" class="${provider === 'gpt' ? 'is-active' : ''}" data-provider="gpt">GPT</button>
          <button type="button" class="${provider === 'google' ? 'is-active' : ''}" data-provider="google">Google</button>
        </div>
        <div class="desk-param-grid" aria-label="模型参数">
          <label data-provider-param="gpt google"><span>画幅</span><select class="desk-select" data-field="ratio">${ratioOptionsHtml(defaults.ratio || '9:16')}</select></label>
          <label data-provider-param="gpt google"><span>分辨率</span><select class="desk-select" data-field="resolution">${optionListHtml([{ value: '1k', label: '1k' }, { value: '2k', label: '2k' }, { value: '4k', label: '4k' }], defaults.resolution || '2k')}</select></label>
          <label data-provider-param="google" hidden><span>线路</span><select class="desk-select" data-field="googleProviderRoute">${optionListHtml([{value: 'third_party', label: '第三方 API'}, {value: 'google_pool', label: 'Google OAuth'}], defaults.googleProviderRoute || 'third_party')}</select></label>
          <label data-provider-param="google" hidden><span>模型</span><select class="desk-select" data-field="model">${googleModelOptionsHtml(defaults.model || DEFAULT_GOOGLE_MODEL)}</select></label>
          <label data-provider-param="gpt"><span>质量</span><select class="desk-select" data-field="quality">${optionListHtml([{ value: 'auto', label: 'auto' }, { value: 'low', label: 'low' }, { value: 'medium', label: 'medium' }, { value: 'high', label: 'high' }], defaults.quality || 'auto')}</select></label>
          <label data-provider-param="gpt"><span>数量</span><select class="desk-select" data-field="imageCount">${imageCountOptionsHtml(defaults.imageCount || 2)}</select></label>
          <label data-provider-param="gpt"><span>审核</span><select class="desk-select" data-field="moderation">${optionListHtml([{ value: 'auto', label: 'auto' }, { value: 'low', label: 'low' }], defaults.moderation || 'auto')}</select></label>
        </div>
        <div class="desk-prompt-mode" data-provider-param="gpt" aria-label="提示词理解方式">
          <label>
            <span>类型</span>
            <select class="desk-select" data-field="gptTaskType">${optionListHtml(GPT_TASK_TYPE_OPTIONS, defaults.gptTaskType || 'image')}</select>
          </label>
          <label>
            <span>线路</span>
            <select class="desk-select" data-field="gptProviderRoute">${optionListHtml(GPT_PROVIDER_ROUTE_OPTIONS, gptRoute)}</select>
          </label>
          <label class="desk-gpt-model-field">
            <span class="desk-gpt-model-caption"><b data-gpt-model-field-label>${escapeHtml(modelFieldLabel)}</b><small data-gpt-image-engine title="生图引擎：${escapeHtml(imageEngineLabel)}">${escapeHtml(imageEngineLabel)}</small></span>
            <select class="desk-select" data-field="gptMainModel" data-model-route="${escapeHtml(gptRoute)}">${optionListHtml(gptModelOptions, selectedGptModel)}</select>
          </label>
          <label>
            <span>推理强度</span>
            <select class="desk-select" data-field="reasoningEffort"${reasoningOptions.length ? '' : ' disabled'}>${reasoningOptions.length ? optionListHtml(reasoningOptions, selectedReasoning) : '<option value="none">不适用</option>'}</select>
          </label>
          <label>
            <span>理解方式</span>
            <select class="desk-select" data-field="promptMode">${optionListHtml(GPT_PROMPT_MODE_OPTIONS, defaults.promptMode || 'smart')}</select>
          </label>
        </div>
        <div class="desk-node__drawer">
          <div class="desk-prompt-panel desk-prompt-panel--references">
            <span class="desk-panel-title">输入参考</span>
            <div class="desk-reference-strip">
              <button type="button" class="desk-upload desk-upload--square" data-upload-drop title="上传参考图">
                <span>+</span>
                <small>参考图</small>
              </button>
              <div class="desk-thumb-row" data-reference-thumbs aria-label="参考图缩略图"></div>
            </div>
            <div class="desk-node-hint">连接文本节点作为提示词，手动上传图片或连接[图片,姿态,排版节点]作为参考图。</div>
          </div>
        </div>
        <div class="desk-input-footer">
          <div class="desk-pill-row" data-output-pills><span>等待输出图片节点</span></div>
          <div class="desk-output-controls desk-output-controls--input">
            <label class="desk-switch"><input type="checkbox" ${archiveChecked ? 'checked' : ''} data-output-archive><span></span><em>自动归档</em></label>
            <label class="desk-switch"><input type="checkbox" ${telegramChecked ? 'checked' : ''} data-output-telegram><span></span><em>发送到 Telegram</em></label>
            <label class="desk-switch"><input type="checkbox" ${batchChecked ? 'checked' : ''} data-field="batchMode"><span></span><em>批量</em></label>
          </div>
          <button type="button" class="desk-button desk-button--primary desk-manual-send" data-send-original disabled>手动发送</button>
          <div class="desk-action-row">
            <button type="button" class="desk-generation-action" data-result-run title="开始生成" aria-label="开始生成">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="m13.5 2-9 12h6l-1 8 10-13h-7z"></path>
              </svg>
              <span class="desk-generation-action__label">开始生成</span>
            </button>
          </div>
        </div>
        <span class="desk-resize-handle desk-resize-handle--locked" aria-hidden="true"></span>
      </section>
    `;
  }

    function comfyWorkflowCardsHtml(selectedWorkflow = '') {
    const items = Array.isArray(comfyWorkflowCatalogRef.current.items) ? comfyWorkflowCatalogRef.current.items : [];
    const visible = items.filter(item => item.enabled || item.id === selectedWorkflow);
    if (!visible.length) {
      return '<div class="desk-comfy-node__empty">设置中心还没有启用工作流</div>';
    }
    return visible.map(item => `
      <button type="button" class="desk-comfy-workflow-card${item.id === selectedWorkflow ? ' is-selected' : ''}${item.enabled ? '' : ' is-disabled'}" data-comfy-workflow="${escapeHtml(item.id)}" role="option" aria-selected="${item.id === selectedWorkflow ? 'true' : 'false'}">
        <span class="desk-comfy-workflow-card__thumb">${item.thumbnail_url ? `<img src="${escapeHtml(item.thumbnail_url)}" alt="">` : '<i></i><i></i><i></i>'}</span>
        <span class="desk-comfy-workflow-card__copy"><strong>${escapeHtml(item.label || item.id)}</strong><small>${escapeHtml(item.summary || item.id)}</small></span>
        <span class="desk-comfy-workflow-card__check" aria-hidden="true">✓</span>
      </button>
    `).join('');
  }

    function comfyWorkflowParameterOverrides(node, workflowId = node?.workflow || '') {
    if (!node || !workflowId) return {};
    if (!node.workflowParameters || typeof node.workflowParameters !== 'object' || Array.isArray(node.workflowParameters)) {
      node.workflowParameters = {};
    }
    const overrides = node.workflowParameters[workflowId];
    return overrides && typeof overrides === 'object' && !Array.isArray(overrides) ? overrides : {};
  }

    function normalizeComfyPixelSize(value, fallback = DEFAULT_COMFY_PIXEL_WIDTH) {
    const fallbackNumber = Number.isFinite(Number(fallback)) ? Number(fallback) : DEFAULT_COMFY_PIXEL_WIDTH;
    const number = Number.isFinite(Number(value)) ? Number(value) : fallbackNumber;
    return clamp(Math.round(number / COMFY_PIXEL_STEP) * COMFY_PIXEL_STEP, MIN_COMFY_PIXEL_SIZE, MAX_COMFY_PIXEL_SIZE);
  }

    function comfyWorkflowDefaultSize(workflowMeta) {
    return {
      width: normalizeComfyPixelSize(workflowMeta?.default_width, DEFAULT_COMFY_PIXEL_WIDTH),
      height: normalizeComfyPixelSize(workflowMeta?.default_height, DEFAULT_COMFY_PIXEL_HEIGHT)
    };
  }

    function comfyParameterValueHtml(parameter, value) {
    const parameterId = escapeHtml(parameter.id || '');
    const type = String(parameter.type || 'text');
    if (type === 'boolean') {
      return `<input type="checkbox" data-comfy-param="${parameterId}" data-comfy-param-type="boolean"${value ? ' checked' : ''}>`;
    }
    if (type === 'select') {
      const options = Array.isArray(parameter.options) ? parameter.options : [];
      return `<select class="desk-select" data-comfy-param="${parameterId}" data-comfy-param-type="select">${options.map(option => optionListHtml([{ value: option, label: option }], value)).join('')}</select>`;
    }
    if (type === 'number') {
      const min = Number.isFinite(Number(parameter.min)) ? ` min="${escapeHtml(parameter.min)}"` : '';
      const max = Number.isFinite(Number(parameter.max)) ? ` max="${escapeHtml(parameter.max)}"` : '';
      const step = Number.isFinite(Number(parameter.step)) ? ` step="${escapeHtml(parameter.step)}"` : '';
      return `<input class="desk-input" type="number"${min}${max}${step} value="${escapeHtml(value)}" data-comfy-param="${parameterId}" data-comfy-param-type="number">`;
    }
    return `<input class="desk-input" type="text" value="${escapeHtml(value)}" data-comfy-param="${parameterId}" data-comfy-param-type="text">`;
  }

    function comfyParameterPickerHtml(parameters, overrides) {
    const available = parameters.filter(parameter => !Object.prototype.hasOwnProperty.call(overrides, parameter.id));
    if (!available.length) {
      return '<select class="desk-select" data-comfy-param-picker disabled><option>没有更多可添加参数</option></select>';
    }
    const groups = [];
    available.forEach(parameter => {
      let group = groups.find(item => item.nodeId === parameter.node_id);
      if (!group) {
        group = {
          nodeId: parameter.node_id,
          title: parameter.node_title || parameter.class_type || `节点 ${parameter.node_id}`,
          parameters: []
        };
        groups.push(group);
      }
      group.parameters.push(parameter);
    });
    return `<select class="desk-select" data-comfy-param-picker aria-label="添加工作流参数">
      <option value="">＋ 选择需要添加的参数</option>
      ${groups.map(group => `<optgroup label="${escapeHtml(`${group.title} · #${group.nodeId}`)}">${group.parameters.map(parameter => `<option value="${escapeHtml(parameter.id)}">${escapeHtml(parameter.label || parameter.input_name || parameter.id)}</option>`).join('')}</optgroup>`).join('')}
    </select>`;
  }

    function comfyWorkflowParametersHtml(node, workflowMeta) {
    const parameters = Array.isArray(workflowMeta?.parameters) ? workflowMeta.parameters : [];
    const overrides = comfyWorkflowParameterOverrides(node, workflowMeta?.id || node?.workflow || '');
    const activeParameters = parameters.filter(parameter => Object.prototype.hasOwnProperty.call(overrides, parameter.id));
    const defaultSize = comfyWorkflowDefaultSize(workflowMeta);
    node.pixelWidth = normalizeComfyPixelSize(node?.pixelWidth, defaultSize.width);
    node.pixelHeight = normalizeComfyPixelSize(node?.pixelHeight, defaultSize.height);
    const groups = [];
    activeParameters.forEach(parameter => {
      let group = groups.find(item => item.nodeId === parameter.node_id);
      if (!group) {
        group = { nodeId: parameter.node_id, title: parameter.node_title || parameter.class_type || `节点 ${parameter.node_id}`, parameters: [] };
        groups.push(group);
      }
      group.parameters.push(parameter);
    });
    return `
      <div class="desk-comfy-parameter-panel" data-comfy-parameter-panel>
        <div class="desk-comfy-parameter-panel__head">
          <span>工作流参数</span>
          <small>${parameters.length ? `已添加 ${activeParameters.length} / 可选 ${parameters.length}` : '暂无可选参数'} <button type="button" data-comfy-params-reset>恢复默认</button></small>
        </div>
        <div class="desk-comfy-parameter-scroll">
          <section class="desk-comfy-parameter-group desk-comfy-parameter-group--size">
            <header><strong>基础输入</strong><small>像素值需被 8 整除</small></header>
            <div class="desk-comfy-parameter-grid">
              <label class="desk-comfy-parameter-field"><span>宽度（像素）</span><input class="desk-input" type="number" min="${MIN_COMFY_PIXEL_SIZE}" max="${MAX_COMFY_PIXEL_SIZE}" step="${COMFY_PIXEL_STEP}" value="${escapeHtml(node.pixelWidth)}" data-comfy-field="pixelWidth"></label>
              <label class="desk-comfy-parameter-field"><span>高度（像素）</span><input class="desk-input" type="number" min="${MIN_COMFY_PIXEL_SIZE}" max="${MAX_COMFY_PIXEL_SIZE}" step="${COMFY_PIXEL_STEP}" value="${escapeHtml(node.pixelHeight)}" data-comfy-field="pixelHeight"></label>
            </div>
            <div class="desk-comfy-parameter-bindings"><span>提示词来自接入的文本节点</span>${workflowMeta?.accepts_image ? '<span>图像来自接入的图像节点</span>' : ''}</div>
          </section>
          <section class="desk-comfy-parameter-group desk-comfy-parameter-group--picker">
            <header><strong>添加参数</strong><small>仅添加需要调整的项目</small></header>
            ${comfyParameterPickerHtml(parameters, overrides)}
          </section>
          ${groups.map(group => `
            <section class="desk-comfy-parameter-group">
              <header><strong>${escapeHtml(group.title)}</strong><small>#${escapeHtml(group.nodeId)}</small></header>
              <div class="desk-comfy-parameter-grid desk-comfy-parameter-grid--optional">
                ${group.parameters.map(parameter => {
                  const value = overrides[parameter.id];
                  const parameterLabel = parameter.label || parameter.input_name || parameter.id;
                  return `<div class="desk-comfy-parameter-field" title="${escapeHtml(parameter.input_name || parameter.id)}"><span>${escapeHtml(parameterLabel)}</span><div class="desk-comfy-parameter-field__control">${comfyParameterValueHtml(parameter, value)}<button type="button" data-comfy-param-remove="${escapeHtml(parameter.id)}" title="移除参数" aria-label="移除${escapeHtml(parameterLabel)}"><span aria-hidden="true">−</span></button></div></div>`;
                }).join('')}
              </div>
            </section>
          `).join('') || '<div class="desk-comfy-parameter-panel__empty">当前仅使用基础输入。可从“添加参数”中选择需要调整的高级参数。</div>'}
        </div>
      </div>`;
  }

    function comfyNodeHtml(node) {
    const output = node.output || { archiveEnabled: true, telegramEnabled: true };
    const selectedWorkflow = node.workflow || comfyWorkflowCatalogRef.current.default_workflow || comfyWorkflowCatalogRef.current.workflows?.[0] || '';
    if (!node.workflow && selectedWorkflow) node.workflow = selectedWorkflow;
    const selectedMeta = (comfyWorkflowCatalogRef.current.items || []).find(item => item.id === selectedWorkflow);
    return `
      <section class="desk-node desk-node--comfy desk-glass" data-node-id="${node.id}" aria-label="Comfy 工作流节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div><p class="desk-node__eyebrow">Comfy 工作流</p><h2>选择并运行本地工作流</h2></div>
          <div class="desk-node-tools"><span class="desk-status-pill" data-output-status>空闲</span><button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button></div>
        </div>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接到图片或高清放大节点" aria-label="连接输出"></button>
        <button type="button" class="desk-port desk-port--in desk-port--image-in" data-port="in" data-node-id="${node.id}" title="连接文本、图片、姿态或排版节点" aria-label="连接输入"></button>
        <div class="desk-comfy-node__section-head"><span>工作流</span><small data-comfy-workflow-count>${(comfyWorkflowCatalogRef.current.items || []).filter(item => item.enabled).length} 个</small></div>
        <div class="desk-comfy-workflow-list" data-comfy-workflow-list role="listbox" aria-label="选择 Comfy 工作流">${comfyWorkflowCardsHtml(selectedWorkflow)}</div>
        <div class="desk-comfy-node__params">
          ${comfyWorkflowParametersHtml(node, selectedMeta)}
        </div>
        <div class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true">
          <div class="desk-progress-copy"><span data-progress-stage>等待 ComfyUI</span><span><strong data-progress-percent>0%</strong><em data-progress-timer>00:00</em></span></div>
          <div class="desk-progress"><span data-progress-bar></span></div>
        </div>
        <div class="desk-comfy-node__footer">
          <div class="desk-comfy-node__footer-main">
            <div class="desk-comfy-node__inputs" data-comfy-input-summary>文本 0 · 图片 0</div>
            <div class="desk-output-controls">
              <label class="desk-switch"><input type="checkbox" checked disabled data-output-archive><span></span><em>自动归档</em></label>
              <label class="desk-switch"><input type="checkbox" ${output.telegramEnabled !== false ? 'checked' : ''} data-output-telegram><span></span><em>Telegram</em></label>
            </div>
          </div>
          <button type="button" class="desk-button desk-button--generate" data-result-run title="运行 Comfy 工作流" aria-label="运行 Comfy 工作流"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"></path></svg></button>
        </div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放 Comfy 节点" aria-hidden="true"></span>
      </section>
    `;
  }

    function refreshComfyNode(nodeId) {
    const state = DesktopState.state.canvas.nodes[nodeId];
    const element = getNodeElement(nodeId);
    if (!state || state.type !== 'comfy' || !element) return;
    const available = (comfyWorkflowCatalogRef.current.items || []).filter(item => item.enabled || item.id === state.workflow);
    if (!state.workflow && available.length) {
      state.workflow = comfyWorkflowCatalogRef.current.default_workflow || available[0].id;
      const selectedMeta = available.find(item => item.id === state.workflow);
      const defaultSize = comfyWorkflowDefaultSize(selectedMeta);
      state.pixelWidth = defaultSize.width;
      state.pixelHeight = defaultSize.height;
      state.ratio = selectedMeta?.default_ratio || state.ratio || '1:1';
    }
    const list = element.querySelector('[data-comfy-workflow-list]');
    if (list) list.innerHTML = comfyWorkflowCardsHtml(state.workflow || '');
    const count = element.querySelector('[data-comfy-workflow-count]');
    if (count) count.textContent = `${(comfyWorkflowCatalogRef.current.items || []).filter(item => item.enabled).length} 个`;
    const textCount = getConnectedTextNodes(nodeId).length;
    const imageCount = getConnectedImageReferences(nodeId).length;
    const summary = element.querySelector('[data-comfy-input-summary]');
    if (summary) summary.textContent = `文本 ${textCount} · 图片 ${imageCount}`;
    const parameterPanel = element.querySelector('[data-comfy-parameter-panel]');
    const workflowMeta = (comfyWorkflowCatalogRef.current.items || []).find(item => item.id === state.workflow);
    if (parameterPanel) parameterPanel.outerHTML = comfyWorkflowParametersHtml(state, workflowMeta);
  }

    async function loadComfyWorkflowCatalog() {
    if (!window.DesktopApi?.getComfyWorkflows) return comfyWorkflowCatalogRef.current;
    const payload = await window.DesktopApi.getComfyWorkflows(true);
    if (payload?.ok !== false) comfyWorkflowCatalogRef.current = payload || comfyWorkflowCatalogRef.current;
    Object.values(DesktopState.state.canvas.nodes || {}).filter(node => node.type === 'comfy').forEach(node => refreshComfyNode(node.id));
    return comfyWorkflowCatalogRef.current;
  }

    function videoInputRoleForSource(sourceType) {
    if (sourceType === 'text') return 'prompt';
    if (sourceType === 'video') return 'reference_video';
    if (['image', 'layout', 'pose'].includes(sourceType)) return 'first_frame';
    return '';
  }

    function videoInferenceInputSummary(nodeId) {
    const incoming = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === nodeId)
      .map(edge => ({ edge, node: DesktopState.state.canvas.nodes[edge.from] }))
      .filter(item => item.node);
    const byRole = role => incoming.find(item => (item.edge.inputRole || videoInputRoleForSource(item.node.type)) === role);
    return {
      prompt: byRole('prompt') || null,
      firstFrame: byRole('first_frame') || null,
      referenceVideo: byRole('reference_video') || null,
      incoming
    };
  }

    function videoRuntimePresentation() {
    const status = videoConfigApi()?.getRuntimeStatus?.() || null;
    if (!status || status.checked === false) return { tone: 'unknown', label: '服务未检测' };
    if (status.online) return { tone: 'online', label: `服务在线${status.version ? ` · ${status.version}` : ''}` };
    return { tone: 'offline', label: '服务离线' };
  }

    function videoTaskTimerLabel(output = {}) {
    const startedAt = Number(output.startedAt || 0);
    if (!startedAt) return '00:00';
    const startedMs = startedAt < 10_000_000_000 ? startedAt * 1000 : startedAt;
    const finishedAt = Number(output.finishedAt || 0);
    const finishedMs = finishedAt ? (finishedAt < 10_000_000_000 ? finishedAt * 1000 : finishedAt) : Date.now();
    const totalSeconds = Math.max(0, Math.floor((finishedMs - startedMs) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return hours > 0
      ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

    function videoDurationOptions(node) {
    const range = videoConfigApi()?.getDurationRange?.() || { minimum: 1, maximum: 15 };
    const candidates = [5, 10, 15].filter(value => value >= range.minimum && value <= range.maximum);
    const current = Number(node.durationSeconds || 15);
    if (!candidates.includes(current) && current >= range.minimum && current <= range.maximum) candidates.push(current);
    return candidates.sort((a, b) => a - b).map(value => ({ value, label: `${value} 秒` }));
  }

    function videoAspectOptions() {
    const ratios = videoConfigApi()?.ASPECT_RATIOS || ['16:9', '9:16', '3:4', '4:3', '2:3', '3:2', '1:1', '21:9', '9:21'];
    return ratios.map(value => ({ value, label: value }));
  }

    function videoQualityOptions(node) {
    const presets = videoConfigApi()?.availablePresets?.(node.aspectRatio) || [{ megapixels: 0.8, width: 768, height: 1024 }];
    return presets.map(item => ({
      value: String(item.megapixels),
      label: `${Number(item.megapixels).toFixed(1)} MP · ${item.width}×${item.height}`
    }));
  }

    function videoAccelerationOptions() {
    return [
      { value: 'off', label: '标准模式 · 不加速' },
      { value: 'first_block_cache', label: '快速模式 · FirstBlockCache' },
      { value: 'sol_attn', label: '实验模式 · Sol-Attn' },
      { value: 'combined', label: '实验模式 · 组合加速' }
    ];
  }

    function videoInferenceNodeHtml(rawNode) {
    const node = normalizeVideoInferenceNodeState(rawNode);
    const inputs = videoInferenceInputSummary(node.id);
    const runtime = videoRuntimePresentation();
    const output = DesktopState.state.outputs?.[node.id] || {};
    const taskStatus = String(output.status || 'idle');
    const isBusy = DesktopState.isInFlight?.(taskStatus) === true;
    const statusLabel = DesktopState.getStatusLabel?.(taskStatus) || '空闲';
    const progress = Math.max(0, Math.min(100, Number(output.progress || 0)));
    const progressStage = String(output.progressText || output.stage || (isBusy ? 'H3 视频生成中...' : '等待 H3 Runtime'));
    const promptLabel = inputs.prompt?.node?.alias || (inputs.prompt ? '已连接文本节点' : '等待文本节点');
    const frameLabel = inputs.firstFrame ? '已连接' : '等待图片节点';
    const dimensionMultiple = videoConfigApi()?.getDimensionMultiple?.() || 32;
    const accelerationLabel = videoConfigApi()?.accelerationLabel?.(node) || '快速模式 · FBC 0.08';
    return `
      <section class="desk-node desk-node--video-inference desk-glass" data-node-id="${node.id}" aria-label="MiniMax H3 视频生成节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div class="desk-video-node__heading">
            <span class="desk-video-node__icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="14" height="14" rx="3"></rect><path d="m17 10 4-2v8l-4-2"></path><path d="m9 9 4 3-4 3z"></path></svg></span>
            <div><p class="desk-node__eyebrow">视频生成</p><h2>MiniMax H3</h2></div>
          </div>
          <div class="desk-node-tools">
            <span class="desk-video-runtime-pill is-${runtime.tone}" data-video-runtime-status>${escapeHtml(runtime.label)}</span>
            <span class="desk-status-pill" data-output-status>${escapeHtml(statusLabel)}</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--video-in" data-port="in" data-node-id="${node.id}" title="连接提示词、首帧或参考视频" aria-label="连接视频生成输入"></button>
        <button type="button" class="desk-port desk-port--out desk-port--video-out" data-port="out" data-node-id="${node.id}" title="连接到视频结果节点" aria-label="连接视频输出"></button>
        <div class="desk-video-node__inputs" aria-label="视频生成输入">
          <div class="${inputs.prompt ? 'is-connected' : ''}"><i></i><span>提示词</span><strong>${escapeHtml(promptLabel)}</strong></div>
          <div class="${inputs.firstFrame ? 'is-connected' : ''}"><i></i><span>首帧</span><strong>${escapeHtml(frameLabel)}</strong></div>
        </div>
        <div class="desk-video-node__fields">
          <label><span>模式</span><select class="desk-select" data-video-field="mode">${optionListHtml([
            { value: 'image_to_video', label: '图生视频' },
            { value: 'reference_to_video', label: '参考驱动' }
          ], node.mode)}</select></label>
          <label><span>时长</span><select class="desk-select" data-video-field="durationSeconds">${optionListHtml(videoDurationOptions(node), node.durationSeconds)}</select></label>
          <label><span>画幅</span><select class="desk-select" data-video-field="aspectRatio">${optionListHtml(videoAspectOptions(), node.aspectRatio)}</select></label>
          <label class="desk-video-node__quality"><span>质量（像素量）<small data-video-actual-size title="宽高均为 ${dimensionMultiple} 倍数">${node.pixelWidth}×${node.pixelHeight}</small></span><select class="desk-select" data-video-field="pixelBudgetMp">${optionListHtml(videoQualityOptions(node), node.pixelBudgetMp)}</select></label>
        </div>
        <div class="desk-video-node__advanced" data-video-advanced aria-label="高级参数">
          <label><span>采样步数</span><input class="desk-input" type="number" min="1" max="100" step="1" value="${node.steps}" data-video-field="steps"></label>
          <label><span>视频 CRF</span><input class="desk-input" type="number" min="0" max="51" step="1" value="${node.crf}" data-video-field="crf"></label>
          <label class="desk-video-node__threshold"><span>FBC 阈值</span><input class="desk-input" type="number" min="0.001" max="1" step="0.01" value="${node.firstBlockCacheThreshold}" data-video-field="firstBlockCacheThreshold"${node.accelerationMode === 'first_block_cache' || node.accelerationMode === 'combined' ? '' : ' disabled'}></label>
          <label><span>加速模式</span><select class="desk-select" data-video-field="accelerationMode" title="${escapeHtml(accelerationLabel)}">${optionListHtml(videoAccelerationOptions(), node.accelerationMode)}</select></label>
        </div>
        <div class="desk-progress-float desk-video-node__progress${isBusy ? ' is-visible' : ''}" aria-label="视频生成进度" aria-hidden="${isBusy ? 'false' : 'true'}">
          <div class="desk-progress-float__panel">
            <div class="desk-progress-float__bar" style="--progress-percent:${progress}%">
              <span data-progress-bar style="width:${progress}%"></span>
              <strong class="desk-progress-float__percent" data-progress-percent>
                <span data-progress-percent-value>${Math.round(progress)}%</span>
                <span class="desk-progress-float__timer" data-progress-timer>${videoTaskTimerLabel(output)}</span>
              </strong>
            </div>
            <span class="desk-progress-float__stage" data-progress-stage>${escapeHtml(progressStage)}</span>
          </div>
        </div>
        <div class="desk-video-node__footer">
          <span data-video-node-hint>${escapeHtml(isBusy ? progressStage : (output.error || (inputs.prompt && inputs.firstFrame ? '输入已就绪' : '连接提示词与首帧后生成')))}</span>
          <div class="desk-video-node__action">
            ${isBusy
              ? `<button type="button" class="desk-status-stop desk-video-node__run desk-video-node__run--cancel" data-video-run data-video-cancel="true" title="取消正在生成的视频任务" aria-label="取消正在生成的视频任务">
                  <span class="desk-status-stop__icon" aria-hidden="true"></span>
                  <span class="desk-status-stop__text">取消任务</span>
                </button>`
              : `<button type="button" class="desk-button desk-button--generate desk-video-node__run desk-video-node__run--generate" data-video-run title="生成视频" aria-label="生成视频">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"></path></svg>
                </button>`}
          </div>
        </div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放视频生成节点" aria-hidden="true"></span>
      </section>
    `;
  }

    function videoNodeSource(node) {
    return String(node?.mediaUrl || '').trim();
  }

    function videoMediaAspectRatio(node) {
    const mediaWidth = Number(node?.mediaWidth || 0);
    const mediaHeight = Number(node?.mediaHeight || 0);
    if (mediaWidth > 0 && mediaHeight > 0) return mediaWidth / mediaHeight;
    const storedRatio = Number(node?.aspectRatio || 0);
    if (storedRatio > 0) return storedRatio;
    const width = Number(node?.width || 0);
    const height = Number(node?.height || 0);
    return width > 0 && height > 0 ? width / height : DEFAULT_VIDEO_NODE_WIDTH / DEFAULT_VIDEO_NODE_HEIGHT;
  }

    function fitVideoNodeToMedia(node, options = {}) {
    const mediaWidth = Number(node?.mediaWidth || 0);
    const mediaHeight = Number(node?.mediaHeight || 0);
    if (!node || mediaWidth <= 0 || mediaHeight <= 0) return false;

    const aspectRatio = mediaWidth / mediaHeight;
    const oldWidth = Math.max(1, Number(node.width || DEFAULT_VIDEO_NODE_WIDTH));
    const oldHeight = Math.max(1, Number(node.height || DEFAULT_VIDEO_NODE_HEIGHT));
    const currentRatio = oldWidth / oldHeight;
    node.aspectRatio = aspectRatio;
    node.videoLayoutVersion = VIDEO_NODE_LAYOUT_VERSION;
    if (!options.force && Math.abs(currentRatio - aspectRatio) < 0.001) return false;

    const longestSide = Math.max(oldWidth, oldHeight);
    let width = aspectRatio >= 1 ? longestSide : longestSide * aspectRatio;
    let height = aspectRatio >= 1 ? longestSide / aspectRatio : longestSide;
    const growScale = Math.max(MIN_VIDEO_NODE_WIDTH / width, MIN_VIDEO_NODE_HEIGHT / height, 1);
    width *= growScale;
    height *= growScale;
    const shrinkScale = Math.min(MAX_VIDEO_NODE_WIDTH / width, MAX_VIDEO_NODE_HEIGHT / height, 1);
    width *= shrinkScale;
    height *= shrinkScale;
    width = Math.round(width * 100) / 100;
    height = Math.round(height * 100) / 100;

    if (options.preserveCenter !== false) {
      node.x = Number(node.x || 0) + (oldWidth - width) / 2;
      node.y = Number(node.y || 0) + (oldHeight - height) / 2;
    }
    node.width = width;
    node.height = height;
    return true;
  }

    function formatVideoDuration(seconds) {
    const value = Number(seconds || 0);
    return value > 0 ? `${value.toFixed(value % 1 ? 2 : 0)} 秒` : '等待视频';
  }

    function videoNodeHtml(node) {
    const rawSource = videoNodeSource(node);
    const source = escapeHtml(typeof window.miniappMediaUrl === 'function' ? window.miniappMediaUrl(rawSource) : rawSource);
    const poster = escapeHtml(typeof window.miniappMediaUrl === 'function' ? window.miniappMediaUrl(node.posterUrl || '') : (node.posterUrl || ''));
    const dimensions = node.mediaWidth && node.mediaHeight ? `${node.mediaWidth}×${node.mediaHeight}` : '尺寸待定';
    const nodeStatus = String(node.status || 'idle');
    const busy = DesktopState.isInFlight?.(nodeStatus) === true;
    const emptyTitle = nodeStatus === 'failed' ? '视频生成失败' : (busy ? 'MiniMax H3 正在生成' : '视频会出现在这里');
    const emptyHint = nodeStatus === 'failed'
      ? (node.error || '请返回生成节点查看错误')
      : (busy ? (node.progressText || '任务进度会自动同步') : '连接 MiniMax H3 节点作为输出');
    return `
      <section class="desk-node desk-node--video ${rawSource ? 'has-video' : 'is-empty'}" data-node-id="${node.id}" data-node-drag-handle aria-label="视频结果节点">
        <div class="desk-video-result__preview">
          ${source
            ? `<video controls preload="metadata" data-node-drag-ignore${poster ? ` poster="${poster}"` : ''} src="${source}"></video>`
            : `<div class="desk-video-result__empty${busy ? ' is-busy' : ''}"><span aria-hidden="true">▶</span><strong>${escapeHtml(emptyTitle)}</strong><small>${escapeHtml(emptyHint)}</small></div>`}
        </div>
        ${rawSource ? `<div class="desk-video-result__meta" title="${escapeHtml(formatVideoDuration(node.durationSeconds))} · ${escapeHtml(dimensions)} · ${Number(node.fps || 24)}fps" aria-label="视频信息：${escapeHtml(formatVideoDuration(node.durationSeconds))}，${escapeHtml(dimensions)}，${Number(node.fps || 24)}fps"><span>${escapeHtml(dimensions)}</span><i></i><span>${Number(node.fps || 24)}fps</span></div>` : ''}
        <button type="button" class="desk-port desk-port--in desk-port--video-result-in" data-port="in" data-node-id="${node.id}" title="连接视频生成输出" aria-label="连接视频输入"></button>
        <button type="button" class="desk-port desk-port--out desk-port--video-result-out" data-port="out" data-node-id="${node.id}" title="作为参考视频连接到其他节点" aria-label="连接视频输出"></button>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放视频节点" aria-hidden="true"></span>
      </section>
    `;
  }

    function refreshVideoInferenceNode(nodeId) {
    const state = DesktopState.state.canvas.nodes[nodeId];
    const element = getNodeElement(nodeId);
    if (!state || state.type !== 'video_inference' || !element) return;
    const wasSelected = element.classList.contains('is-selected');
    discardFloatingSwellState(element);
    element.outerHTML = videoInferenceNodeHtml(state);
    const replacement = getNodeElement(nodeId);
    const progressRoot = replacement?.querySelector('.desk-video-node__progress');
    progressView?.replaceRoot(element.querySelector('.desk-video-node__progress'), progressRoot, replacement);
    const output = DesktopState.state.outputs?.[nodeId] || {};
    const running = DesktopState.isInFlight(output.status);
    progressView?.update(progressRoot, { visible: running, running, taskId: output.taskId,
      percent: output.stage === 'submitting' ? null : output.progress, title: output.progressText || '视频生成中',
      detail: 'MiniMax H3', startedAt: output.startedAt, finishedAt: output.finishedAt }, replacement);
    if (wasSelected) replacement?.classList.add('is-selected');
    ensureNodeEdgeHandles(replacement);
    applyNodeLayout(nodeId);
    updateLinkPath();
  }

    function refreshVideoNode(nodeId) {
    const state = DesktopState.state.canvas.nodes[nodeId];
    const element = getNodeElement(nodeId);
    if (!state || state.type !== 'video' || !element) return;
    fitVideoNodeToMedia(state);
    const wasSelected = element.classList.contains('is-selected');
    discardFloatingSwellState(element);
    element.outerHTML = videoNodeHtml(state);
    const replacement = getNodeElement(nodeId);
    if (wasSelected) replacement?.classList.add('is-selected');
    ensureNodeEdgeHandles(replacement);
    applyNodeLayout(nodeId);
    updateLinkPath();
    const video = replacement?.querySelector('video');
    if (!video) return;
    const syncMetadata = () => {
      if (!video.isConnected || getNodeElement(nodeId)?.querySelector('video') !== video) return;
      const current = DesktopState.state.canvas.nodes[nodeId];
      if (!current || current.type !== 'video') return;
      const mediaWidth = Number(video.videoWidth || 0);
      const mediaHeight = Number(video.videoHeight || 0);
      const duration = Number(video.duration || 0);
      let changed = false;
      if (mediaWidth > 0 && mediaHeight > 0 && (current.mediaWidth !== mediaWidth || current.mediaHeight !== mediaHeight)) {
        current.mediaWidth = mediaWidth;
        current.mediaHeight = mediaHeight;
        changed = true;
      }
      if (Number.isFinite(duration) && duration > 0 && !current.durationSeconds) {
        current.durationSeconds = duration;
        changed = true;
      }
      const geometryChanged = fitVideoNodeToMedia(current);
      if (!changed && !geometryChanged) return;
      refreshVideoNode(nodeId);
      DesktopState.saveSettings();
    };
    if (video.readyState >= 1) syncMetadata();
    else video.addEventListener('loadedmetadata', syncMetadata, { once: true });
  }

    function syncVideoInferenceNodeStateFromDom(element) {
    const nodeId = element?.dataset?.nodeId || '';
    const node = nodeId ? DesktopState.state.canvas.nodes[nodeId] : null;
    if (!element || !node || node.type !== 'video_inference') return null;
    node.mode = element.querySelector('[data-video-field="mode"]')?.value || node.mode || 'image_to_video';
    node.durationSeconds = Number(element.querySelector('[data-video-field="durationSeconds"]')?.value || node.durationSeconds || 15);
    node.aspectRatio = element.querySelector('[data-video-field="aspectRatio"]')?.value || node.aspectRatio || '3:4';
    node.pixelBudgetMp = Number(element.querySelector('[data-video-field="pixelBudgetMp"]')?.value || node.pixelBudgetMp || 0.8);
    node.accelerationMode = element.querySelector('[data-video-field="accelerationMode"]')?.value || node.accelerationMode || 'first_block_cache';
    node.steps = Number(element.querySelector('[data-video-field="steps"]')?.value || node.steps || 20);
    node.crf = Number(element.querySelector('[data-video-field="crf"]')?.value || node.crf || 23);
    node.firstBlockCacheThreshold = Number(
      element.querySelector('[data-video-field="firstBlockCacheThreshold"]')?.value
      || node.firstBlockCacheThreshold
      || 0.08
    );
    normalizeVideoInferenceNodeState(node);
    const actualSize = element.querySelector('[data-video-actual-size]');
    if (actualSize) actualSize.textContent = `${node.pixelWidth}×${node.pixelHeight}`;
    return node;
  }

    function fileOutputNodeHtml(nodeId) {
    return `
      <section class="desk-node desk-node--file-output desk-glass" data-node-id="${nodeId}" aria-label="文件结果节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div class="desk-file-node-heading">
            <span class="desk-file-node-heading__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M8 3.5h6.8L19 7.7V19a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 19V5A1.5 1.5 0 0 1 8 3.5Z"></path>
                <path d="M14.5 3.8V8h4.2"></path>
                <path d="M9.5 12h6"></path>
                <path d="M9.5 15.5h4.5"></path>
              </svg>
            </span>
            <div>
              <p class="desk-node__eyebrow">文件结果</p>
              <h2 data-output-title>等待 PPT / PSD</h2>
            </div>
          </div>
          <div class="desk-node-tools">
            <span class="desk-status-pill" data-output-status>空闲</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${nodeId}" title="连接模型节点到这里" aria-label="连接输入"></button>
        <div class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true">
          <div class="desk-progress-copy">
            <span data-progress-stage>正在生成文件</span>
            <span><strong data-progress-percent>0%</strong><em data-progress-timer>00:00</em></span>
          </div>
          <div class="desk-progress"><span data-progress-bar></span></div>
        </div>
        <div class="desk-file-result" data-result-grid>
          <div class="desk-file-result-empty">
            <div class="desk-file-result-empty__icon" aria-hidden="true">
              <svg viewBox="0 0 48 48">
                <path class="desk-file-empty-back" d="M11 13.5h16l8 8V39H11z"></path>
                <path class="desk-file-empty-front" d="M17 8.5h15l7 7V34H17z"></path>
                <path class="desk-file-empty-fold" d="M31.5 9v7h7"></path>
                <path class="desk-file-empty-line" d="M22 22h11M22 27h8"></path>
              </svg>
            </div>
            <span class="desk-file-result-empty__kicker">文件收件箱</span>
            <strong>文件会出现在这里</strong>
            <span>从模型节点生成 PPT/PSD，结果会自动汇入这里。</span>
            <div class="desk-file-result-empty__types" aria-label="支持 PPT 和 PSD"><span>PPT</span><i></i><span>PSD</span></div>
          </div>
        </div>
        <div class="desk-file-output-footer">
          <div class="desk-file-output-source"><i aria-hidden="true"></i><span>由模型节点生成</span></div>
          <div class="desk-pill-row" data-output-pills><span>等待文件任务</span></div>
        </div>
        <span class="desk-resize-handle desk-resize-handle--locked" aria-hidden="true"></span>
      </section>
    `;
  }

    function upscaleNodeHtml(node) {
    const model = node.model || '4x-UltraSharp';
    const tileSize = DesktopState.clamp(node.tileSize || 256, 64, 2048, 256);
    const tileOverlap = DesktopState.clamp(node.tileOverlap || 32, 0, 256, 32);
    const manualMode = isManualUpscaleFlow(node.id);
    const telegramChecked = node.output?.telegramEnabled === true;
    return `
      <section class="desk-node desk-node--upscale desk-glass" data-node-id="${node.id}" aria-label="高清放大节点" data-i18n-aria="upscaleNodeAria">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow" data-i18n="upscaleEyebrow">高清放大</p>
            <h2 data-i18n="upscaleTitle">本地高清放大</h2>
          </div>
          <div class="desk-node-tools">
            <span class="desk-status-pill" data-output-status>空闲</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--upscale-in" data-port="in" data-node-id="${node.id}" title="连接图片到这里" aria-label="连接图片输入" data-i18n-title="upscaleInputTitle" data-i18n-aria="upscaleInputAria"></button>
        <button type="button" class="desk-port desk-port--out desk-port--upscale-out" data-port="out" data-node-id="${node.id}" title="连接到图片节点" aria-label="连接高清输出" data-i18n-title="upscaleOutputTitle" data-i18n-aria="upscaleOutputAria"></button>
        <div class="desk-upscale-controls">
          <label><span data-i18n="upscaleModelLabel">模型</span><select class="desk-select" data-upscale-field="model">${optionListHtml(UPSCALE_MODEL_OPTIONS, model)}</select></label>
          <label><span data-i18n="upscaleTileLabel">分块</span><select class="desk-select" data-upscale-field="tileSize">${optionListHtml([{ value: '192', label: '192' }, { value: '256', label: '256' }, { value: '384', label: '384' }, { value: '512', label: '512' }], tileSize)}</select></label>
          <label><span data-i18n="upscaleOverlapLabel">重叠</span><select class="desk-select" data-upscale-field="tileOverlap">${optionListHtml([{ value: '16', label: '16' }, { value: '32', label: '32' }, { value: '64', label: '64' }, { value: '96', label: '96' }], tileOverlap)}</select></label>
        </div>
        <div class="desk-progress-wrap desk-progress-float desk-upscale-progress" aria-label="高清放大进度" data-i18n-aria="upscaleProgressAria" aria-hidden="true">
          <div class="desk-progress-float__panel">
            <div class="desk-progress-float__bar">
              <span data-progress-bar></span>
              <strong class="desk-progress-float__percent" data-progress-percent>
                <span data-progress-percent-value>0%</span>
                <span class="desk-progress-float__timer" data-progress-timer>00:00</span>
              </strong>
            </div>
            <span class="desk-progress-float__stage" data-progress-stage data-i18n="upscaleProgressWaiting">等待图片</span>
          </div>
        </div>
        <div class="desk-action-row desk-upscale-actions${manualMode ? ' is-visible' : ''}" data-upscale-actions aria-hidden="${manualMode ? 'false' : 'true'}">
          <label class="desk-switch desk-upscale-telegram">
            <input type="checkbox" ${telegramChecked ? 'checked' : ''} data-output-telegram>
            <span></span>
            <em data-i18n="sendTelegram">发送到 Telegram</em>
          </label>
          <button type="button" class="desk-button desk-button--generate desk-upscale-run" data-result-run title="高清放大" aria-label="高清放大" data-i18n-title="upscaleRunTitle" data-i18n-aria="upscaleRunAria">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"></path>
            </svg>
          </button>
        </div>
      </section>
    `;
  }

    function syncFormFromState() {
    const { state } = DesktopState;
    if (els.deskRatioSelect) els.deskRatioSelect.value = state.params.ratio;
    if (els.deskResolutionSelect) els.deskResolutionSelect.value = state.params.resolution;
    if (els.deskModelSelect) {
      els.deskModelSelect.value = typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(state.params.model, DEFAULT_GOOGLE_MODEL)
        : (state.params.model || DEFAULT_GOOGLE_MODEL);
    }
    const googleRoute = els.deskInputNode?.querySelector('[data-field="googleProviderRoute"]');
    if (googleRoute) googleRoute.value = state.params.googleProviderRoute === 'google_pool' ? 'google_pool' : 'third_party';
    if (els.deskQualitySelect) els.deskQualitySelect.value = state.params.quality;
    if (els.deskCountInput) els.deskCountInput.value = DesktopState.clamp(state.params.imageCount, 1, 8, 2);
    if (els.deskModerationSelect) els.deskModerationSelect.value = state.params.moderation;
    const normalizedTaskType = DesktopState.normalizeGptTaskType(state.params.gptTaskType, 'image');
    if (normalizedTaskType === 'ppt') state.params.gptProviderRoute = 'chatgpt_pool';
    if (normalizedTaskType !== 'ppt' && state.params.useThirdPartyApi && state.params.gptProviderRoute !== 'third_party_image_api') {
      state.params.gptProviderRoute = 'third_party_image_api';
      state.params.useThirdPartyApi = false;
    }
    if (els.deskGptTaskTypeSelect) els.deskGptTaskTypeSelect.value = normalizedTaskType;
    const routeSelect = els.deskGptProviderRouteSelect || els.deskInputNode?.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    if (routeSelect) routeSelect.value = state.params.gptProviderRoute || 'codex';
    if (els.deskReasoningEffortSelect) els.deskReasoningEffortSelect.value = state.params.reasoningEffort || 'medium';
    applyGptModelRouteToNode(els.deskInputNode, routeSelect?.value || state.params.gptProviderRoute || 'codex', { rememberPrevious: false });
    if (els.deskPromptModeSelect) els.deskPromptModeSelect.value = DesktopState.normalizePromptMode(state.params.promptMode, 'smart');
    if (els.deskBatchMode) els.deskBatchMode.checked = !!state.params.batchMode;
    applyPromptModeToNode(els.deskInputNode, state.params.promptMode || 'smart');
    applyGptTaskTypeToNode(els.deskInputNode, normalizedTaskType);

    document.querySelectorAll('#deskProviderSegment button').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.provider === state.provider);
    });
    updateAllProviderParamVisibility();

    applyNodeSelection();
    applyCanvasTransform();
    applyAllNodeLayouts();
    updateInputProgressOverlay();
    syncOutputControlsToNodes(state.output, { save: false });
  }

    function setInputExpanded(expanded) {
    const { state } = DesktopState;
    state.inputExpanded = !!expanded;
    if (state.inputExpanded) selectNode('input');
    DesktopState.saveSettings();
  }

    function readFormToState() {
    const { state } = DesktopState;
    upgradeGptRouteControls(els.deskInputNode);
    const routeSelect = els.deskGptProviderRouteSelect || els.deskInputNode?.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    const outputControls = readOutputControlsFromNode(els.deskInputNode, state.output);
    state.params.ratio = DesktopState.normalizeRatio(els.deskRatioSelect?.value, '9:16');
    state.params.resolution = DesktopState.normalizeResolution(els.deskResolutionSelect?.value, '2k');
    state.params.model = typeof DesktopState.normalizeGoogleModel === 'function'
      ? DesktopState.normalizeGoogleModel(els.deskModelSelect?.value || state.params.model || DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
      : (els.deskModelSelect?.value || state.params.model || DEFAULT_GOOGLE_MODEL);
    state.params.googleProviderRoute = els.deskInputNode?.querySelector('[data-field="googleProviderRoute"]')?.value === 'google_pool' ? 'google_pool' : 'third_party';
    state.params.quality = DesktopState.normalizeGptQuality(els.deskQualitySelect?.value, 'auto');
    state.params.imageCount = DesktopState.clamp(els.deskCountInput?.value, 1, 8, 1);
    state.params.moderation = DesktopState.normalizeModeration(els.deskModerationSelect?.value, 'auto');
    state.params.gptTaskType = DesktopState.normalizeGptTaskType(els.deskGptTaskTypeSelect?.value, 'image');
    state.params.gptProviderRoute = state.params.gptTaskType === 'ppt'
      ? 'chatgpt_pool'
      : DesktopState.normalizeGptProviderRoute(routeSelect?.value, 'codex');
    state.params.useThirdPartyApi = state.params.gptProviderRoute === 'third_party_image_api';
    state.params.reasoningEffort = DesktopState.normalizeReasoningEffort(els.deskReasoningEffortSelect?.value, state.params.reasoningEffort || 'medium');
    applyGptModelRouteToNode(els.deskInputNode, state.params.gptProviderRoute);
    state.params.gptMainModel = DesktopState.normalizeGptMainModel(els.deskGptMainModelSelect?.value, 'gpt-5.5');
    state.params.gptModelsByRoute = {
      ...(state.params.gptModelsByRoute || {}),
      [state.params.gptProviderRoute]: state.params.gptMainModel
    };
    state.params.reasoningEffort = DesktopState.normalizeReasoningEffort(els.deskReasoningEffortSelect?.value, 'medium');
    state.params.promptMode = DesktopState.normalizePromptMode(els.deskPromptModeSelect?.value, getPromptModeFromNode(els.deskInputNode, 'smart'));
    state.params.batchMode = !!els.deskBatchMode?.checked;
    applyGptTaskTypeToNode(els.deskInputNode, state.params.gptTaskType);
    syncOutputControlsToNodes(outputControls, { save: false });
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    window.DesktopResults?.refreshOutputConfigStatus?.('input', outputControls);
    return state;
  }

    function readOutputControlsFromNode(node, fallback = {}) {
    const archiveToggle = node?.querySelector('[data-output-archive]');
    const telegramToggle = node?.querySelector('[data-output-telegram]');
    return {
      archiveEnabled: archiveToggle ? archiveToggle.checked !== false : fallback?.archiveEnabled !== false,
      telegramEnabled: telegramToggle ? telegramToggle.checked !== false : fallback?.telegramEnabled !== false
    };
  }

    function syncInputNodeStateFromDom(node) {
    const nodeId = node?.dataset?.nodeId || '';
    const nodeState = nodeId ? DesktopState.state.canvas.nodes[nodeId] : null;
    if (!node || !nodeState || nodeState.type !== 'input') return null;
    if (nodeId === 'input') {
      readFormToState();
      return nodeState;
    }
    const taskType = DesktopState.normalizeGptTaskType(node.querySelector('[data-field="gptTaskType"]')?.value, 'image');
    const route = taskType === 'ppt'
      ? 'chatgpt_pool'
      : DesktopState.normalizeGptProviderRoute(node.querySelector('[data-field="gptProviderRoute"]')?.value, 'codex');
    nodeState.params = nodeState.params || {};
    nodeState.params.reasoningEffort = DesktopState.normalizeReasoningEffort(
      node.querySelector('[data-field="reasoningEffort"]')?.value,
      nodeState.params.reasoningEffort || 'medium'
    );
    applyGptModelRouteToNode(node, route);
    const routeModels = {
      ...(nodeState.params?.gptModelsByRoute || {}),
      [route]: DesktopState.normalizeGptMainModel(node.querySelector('[data-field="gptMainModel"]')?.value, 'gpt-5.5')
    };
    nodeState.provider = getProviderFromNode(node);
    nodeState.params = {
      ratio: DesktopState.normalizeRatio(node.querySelector('[data-field="ratio"]')?.value, '9:16'),
      resolution: DesktopState.normalizeResolution(node.querySelector('[data-field="resolution"]')?.value, '2k'),
      model: typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
        : (node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL),
      quality: DesktopState.normalizeGptQuality(node.querySelector('[data-field="quality"]')?.value, 'auto'),
      imageCount: DesktopState.clamp(node.querySelector('[data-field="imageCount"]')?.value, 1, 8, 1),
      moderation: DesktopState.normalizeModeration(node.querySelector('[data-field="moderation"]')?.value, 'auto'),
      gptTaskType: taskType,
      gptProviderRoute: route,
      googleProviderRoute: node.querySelector('[data-field="googleProviderRoute"]')?.value === 'google_pool' ? 'google_pool' : 'third_party',
      useThirdPartyApi: route === 'third_party_image_api',
      gptMainModel: DesktopState.normalizeGptMainModel(node.querySelector('[data-field="gptMainModel"]')?.value, 'gpt-5.5'),
      gptModelsByRoute: routeModels,
      reasoningEffort: DesktopState.normalizeReasoningEffort(node.querySelector('[data-field="reasoningEffort"]')?.value, 'medium'),
      promptMode: getPromptModeFromNode(node, 'smart'),
      batchMode: !!node.querySelector('[data-field="batchMode"]')?.checked
    };
    nodeState.batchMode = !!nodeState.params.batchMode;
    nodeState.output = readOutputControlsFromNode(node, nodeState.output || DesktopState.state.output);
    return nodeState;
  }

    function syncVisibleInputNodeStatesToCanvas() {
    document.querySelectorAll('.desk-node--input[data-node-id]').forEach(syncInputNodeStateFromDom);
  }

    function readOutputControlsForTask(inputNodeId, resultNodeId = inputNodeId) {
    const inputNode = getNodeElement(inputNodeId);
    const resultNode = resultNodeId && resultNodeId !== inputNodeId ? getNodeElement(resultNodeId) : null;
    const inputControls = readOutputControlsFromNode(inputNode, DesktopState.state.output);
    return resultNode
      ? readOutputControlsFromNode(resultNode, inputControls)
      : inputControls;
  }

    function syncOutputControlsToNodes(controls = DesktopState.state.output, options = {}) {
    const normalized = {
      archiveEnabled: controls?.archiveEnabled !== false,
      telegramEnabled: controls?.telegramEnabled !== false
    };
    DesktopState.state.output.archiveEnabled = normalized.archiveEnabled;
    DesktopState.state.output.telegramEnabled = normalized.telegramEnabled;
    Object.values(DesktopState.state.outputs || {}).forEach(output => {
      if (!output) return;
      output.params = {
        ...(output.params || {}),
        ...normalized
      };
    });
    document.querySelectorAll('.desk-node[data-node-id]').forEach(node => {
      const archiveToggle = node.querySelector('[data-output-archive]');
      const telegramToggle = node.querySelector('[data-output-telegram]');
      if (node.classList.contains('desk-node--upscale')) {
        const upscaleNode = DesktopState.state.canvas.nodes[node.dataset.nodeId || ''];
        if (archiveToggle) archiveToggle.checked = true;
        if (telegramToggle) telegramToggle.checked = upscaleNode?.output?.telegramEnabled === true;
        return;
      }
      if (node.classList.contains('desk-node--comfy')) {
        const comfyNode = DesktopState.state.canvas.nodes[node.dataset.nodeId || ''];
        if (archiveToggle) archiveToggle.checked = true;
        if (telegramToggle) telegramToggle.checked = comfyNode?.output?.telegramEnabled !== false;
        return;
      }
      if (archiveToggle) archiveToggle.checked = normalized.archiveEnabled;
      if (telegramToggle) telegramToggle.checked = normalized.telegramEnabled;
    });
    window.DesktopResults?.refreshOutputConfigStatus?.('input', normalized, {
      updateBottom: options.updateBottom !== false
    });
    if (options.save !== false) DesktopState.saveSettings();
    return normalized;
  }

    function syncOutputControlsFromNode(node) {
    if (!node) return;
    const nodeId = node.dataset.nodeId || 'input';
    const nodeState = DesktopState.state.canvas.nodes[nodeId];
    const controls = readOutputControlsFromNode(node, nodeState?.output || DesktopState.state.output);
    if (!DesktopState.state.outputs[nodeId]) DesktopState.state.outputs[nodeId] = {};
    DesktopState.state.outputs[nodeId].params = {
      ...(DesktopState.state.outputs[nodeId].params || {}),
      ...controls
    };
    if (nodeState?.type === 'upscale' || nodeState?.type === 'comfy') {
      nodeState.output = {
        archiveEnabled: true,
        telegramEnabled: nodeState.type === 'upscale' ? controls.telegramEnabled === true : controls.telegramEnabled !== false
      };
      DesktopState.state.outputs[nodeId].params.archiveEnabled = true;
      DesktopState.state.outputs[nodeId].params.telegramEnabled = nodeState.output.telegramEnabled;
      DesktopState.saveSettings();
      return;
    }
    syncOutputControlsToNodes(controls, {
      updateBottom: node.classList.contains('desk-node--input')
    });
  }

    function getProviderFromNode(node) {
    return node?.querySelector('.desk-segment button.is-active')?.dataset.provider || 'gpt';
  }

    function getPromptModeFromNode(node, fallback = 'smart') {
    return DesktopState.normalizePromptMode(
      node?.querySelector('[data-field="promptMode"], #deskPromptModeSelect')?.value
        || node?.querySelector('.desk-prompt-mode button.is-active')?.dataset.promptMode,
      fallback
    );
  }

    function applyPromptModeToNode(node, mode) {
    const normalized = DesktopState.normalizePromptMode(mode, 'smart');
    const select = node?.querySelector('[data-field="promptMode"], #deskPromptModeSelect');
    if (select) select.value = normalized;
    node?.querySelectorAll('.desk-prompt-mode button[data-prompt-mode]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.promptMode === normalized);
    });
  }

    function upgradeGptRouteControls(node) {
    if (!node) return;
    const promptMode = node.querySelector('.desk-prompt-mode');
    if (!promptMode) return;
    let legacyThirdPartyChecked = false;
    node.querySelectorAll('#deskThirdPartyApiToggle, #gptThirdPartyApiToggle, [data-field="useThirdPartyApi"]').forEach(control => {
      legacyThirdPartyChecked = legacyThirdPartyChecked || !!control.checked;
      control.closest('label')?.remove();
    });
    promptMode.querySelectorAll('label').forEach(label => {
      const labelText = label.querySelector('span')?.textContent?.trim() || '';
      const checkbox = label.querySelector('input[type="checkbox"]');
      if (checkbox && /第三方\s*4K/.test(labelText)) {
        legacyThirdPartyChecked = legacyThirdPartyChecked || checkbox.checked;
        label.remove();
      }
    });

    let routeSelect = node.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    if (!routeSelect) {
      const routeSelectId = node.dataset.nodeId === 'input' ? ' id="deskGptProviderRouteSelect"' : '';
      const routeLabel = document.createElement('label');
      routeLabel.innerHTML = `<span>线路</span><select${routeSelectId} class="desk-select" data-field="gptProviderRoute">${optionListHtml(GPT_PROVIDER_ROUTE_OPTIONS, 'codex')}</select>`;
      const typeLabel = promptMode.querySelector('[data-field="gptTaskType"], #deskGptTaskTypeSelect')?.closest('label');
      if (typeLabel?.nextSibling) {
        promptMode.insertBefore(routeLabel, typeLabel.nextSibling);
      } else {
        promptMode.appendChild(routeLabel);
      }
      routeSelect = routeLabel.querySelector('[data-field="gptProviderRoute"]');
    }
    if (routeSelect) {
      GPT_PROVIDER_ROUTE_OPTIONS.forEach(item => {
        if (Array.from(routeSelect.options).some(option => option.value === item.value)) return;
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = item.label;
        routeSelect.appendChild(option);
      });
    }
    if (legacyThirdPartyChecked && routeSelect && DesktopState.normalizeGptProviderRoute(routeSelect.value, 'codex') === 'codex') {
      routeSelect.value = 'third_party_image_api';
    }
  }

    function applyGptTaskTypeToNode(node, taskType) {
    if (!node) return 'image';
    upgradeGptRouteControls(node);
    const normalized = DesktopState.normalizeGptTaskType(taskType, 'image');
    const typeSelect = node.querySelector('[data-field="gptTaskType"], #deskGptTaskTypeSelect');
    const routeSelect = node.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    if (typeSelect) typeSelect.value = normalized;
    if (routeSelect) {
      const locked = normalized === 'ppt';
      if (locked) routeSelect.value = 'chatgpt_pool';
      routeSelect.disabled = locked;
      routeSelect.title = locked ? 'PPT 任务只能走账号池 Web API 线路' : '';
      applyGptModelRouteToNode(node, routeSelect.value);
    }
    node.classList.toggle('is-editable-file-task', normalized !== 'image');
    return normalized;
  }

    function syncUpscaleNodeStateFromDom(node) {
    const nodeId = node?.dataset?.nodeId || '';
    const nodeState = nodeId ? DesktopState.state.canvas.nodes[nodeId] : null;
    if (!node || !nodeState || nodeState.type !== 'upscale') return null;
    nodeState.model = node.querySelector('[data-upscale-field="model"]')?.value || nodeState.model || '4x-UltraSharp';
    nodeState.tileSize = DesktopState.clamp(node.querySelector('[data-upscale-field="tileSize"]')?.value, 64, 2048, 256);
    nodeState.tileOverlap = DesktopState.clamp(node.querySelector('[data-upscale-field="tileOverlap"]')?.value, 0, 256, 32);
    nodeState.device = 'auto';
    nodeState.output = readOutputControlsFromNode(node, nodeState.output || { archiveEnabled: true, telegramEnabled: false });
    nodeState.output.archiveEnabled = true;
    return nodeState;
  }

    function getIncomingUpscaleEdges(nodeId, type = '') {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === nodeId && DesktopState.state.canvas.nodes[edge.from])
      .filter(edge => !type || DesktopState.state.canvas.nodes[edge.from]?.type === type);
  }

    function getOutgoingUpscaleImageEdges(nodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image');
  }

    function isManualUpscaleFlow(nodeId) {
    return getIncomingUpscaleEdges(nodeId, 'image').length > 0 && getOutgoingUpscaleImageEdges(nodeId).length > 0;
  }

    function refreshUpscaleNodeMode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'upscale' || !el) return;
    const manualMode = isManualUpscaleFlow(nodeId);
    const actions = el.querySelector('[data-upscale-actions]');
    const output = DesktopState.state.outputs?.[nodeId] || {};
    const isBusy = DesktopState.isInFlight?.(output.status);
    el.classList.toggle('has-manual-upscale-flow', manualMode);
    if (actions) {
      actions.classList.toggle('is-visible', manualMode);
      actions.setAttribute('aria-hidden', manualMode ? 'false' : 'true');
    }
    el.querySelectorAll('[data-output-telegram]').forEach(input => {
      input.disabled = !manualMode || isBusy;
    });
    el.querySelectorAll('[data-result-run]').forEach(button => {
      button.disabled = !manualMode || isBusy;
    });
  }

    function updateUpscaleInputCount(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'upscale' || !el) return;
    refreshUpscaleNodeMode(nodeId);
  }

    return Object.freeze({
      ratioOptionsHtml,
      googleModelOptionsHtml,
      imageCountOptionsHtml,
      optionListHtml,
      fallbackGptModelOptions,
      gptRouteCatalog,
      gptModelOptionsForRoute,
      gptModelCatalogEntry,
      reasoningOption,
      gptReasoningOptionsForModel,
      selectedReasoningForModel,
      updateGptRoutePresentation,
      applyGptReasoningToNode,
      selectedGptModelForRoute,
      inputParamsForNode,
      applyGptModelRouteToNode,
      applyGptModelCatalog,
      ratioFromAspect,
      updateProviderParamVisibility,
      updateAllProviderParamVisibility,
      videoConfigApi,
      migrateVideoInferenceNodeLayout,
      normalizeVideoInferenceNodeState,
      inputNodeHtml,
      comfyWorkflowCardsHtml,
      comfyWorkflowParameterOverrides,
      normalizeComfyPixelSize,
      comfyWorkflowDefaultSize,
      comfyParameterValueHtml,
      comfyParameterPickerHtml,
      comfyWorkflowParametersHtml,
      comfyNodeHtml,
      refreshComfyNode,
      loadComfyWorkflowCatalog,
      videoInputRoleForSource,
      videoInferenceInputSummary,
      videoRuntimePresentation,
      videoTaskTimerLabel,
      videoDurationOptions,
      videoAspectOptions,
      videoQualityOptions,
      videoAccelerationOptions,
      videoInferenceNodeHtml,
      videoNodeSource,
      videoMediaAspectRatio,
      fitVideoNodeToMedia,
      formatVideoDuration,
      videoNodeHtml,
      refreshVideoInferenceNode,
      refreshVideoNode,
      syncVideoInferenceNodeStateFromDom,
      fileOutputNodeHtml,
      upscaleNodeHtml,
      syncFormFromState,
      setInputExpanded,
      readFormToState,
      readOutputControlsFromNode,
      syncInputNodeStateFromDom,
      syncVisibleInputNodeStatesToCanvas,
      readOutputControlsForTask,
      syncOutputControlsToNodes,
      syncOutputControlsFromNode,
      getProviderFromNode,
      getPromptModeFromNode,
      applyPromptModeToNode,
      upgradeGptRouteControls,
      applyGptTaskTypeToNode,
      syncUpscaleNodeStateFromDom,
      getIncomingUpscaleEdges,
      getOutgoingUpscaleImageEdges,
      isManualUpscaleFlow,
      refreshUpscaleNodeMode,
      updateUpscaleInputCount,
    });
  }

  window.DesktopCanvasModelNodes = Object.freeze({ create });
})();
