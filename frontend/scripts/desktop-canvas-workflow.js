// Workflow schema normalization, portable snapshots and file save/load. State replacement remains in the host.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    DEFAULT_COMFY_NODE_HEIGHT,
    DEFAULT_COMFY_NODE_WIDTH,
    DEFAULT_COMFY_PIXEL_HEIGHT,
    DEFAULT_COMFY_PIXEL_WIDTH,
    DEFAULT_GOOGLE_MODEL,
    DEFAULT_IMAGE_GROUP_NODE_HEIGHT,
    DEFAULT_IMAGE_GROUP_NODE_WIDTH,
    DEFAULT_IMAGE_NODE_HEIGHT,
    DEFAULT_IMAGE_NODE_WIDTH,
    DEFAULT_INPUT_NODE_HEIGHT,
    DEFAULT_INPUT_NODE_WIDTH,
    DEFAULT_UPSCALE_NODE_HEIGHT,
    DEFAULT_UPSCALE_NODE_WIDTH,
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    DEFAULT_VIDEO_NODE_HEIGHT,
    DEFAULT_VIDEO_NODE_WIDTH,
    MAX_COMFY_NODE_HEIGHT,
    MAX_COMFY_NODE_WIDTH,
    MAX_SCALE,
    MAX_VIDEO_INFERENCE_NODE_HEIGHT,
    MAX_VIDEO_INFERENCE_NODE_WIDTH,
    MAX_VIDEO_NODE_WIDTH,
    MIN_COMFY_NODE_HEIGHT,
    MIN_COMFY_NODE_WIDTH,
    MIN_SCALE,
    MIN_VIDEO_INFERENCE_NODE_HEIGHT,
    MIN_VIDEO_INFERENCE_NODE_WIDTH,
    MIN_VIDEO_NODE_WIDTH,
    UPSCALE_MODEL_OPTIONS,
    WORKFLOW_SCHEMA,
    WORKFLOW_VERSION,
    applyWorkflowSnapshot,
    audioNodeDefinition,
    musicNodeDefinition,
    topazDefinition,
    cyimgDefinition,
    krea2Definition,
    qwen21Definition,
    videoControlDefinition,
    topazVideoDefinition,
    embedAudioAssets,
    clamp,
    dataUrlValue,
    downloadBlob,
    expandNodeIdsToGroups,
    fitVideoNodeToMedia,
    imageGroupItemSource,
    jsonClone,
    materializePromptDocument,
    materializeTextNode,
    nextTextNodeAlias,
    normalizeComfyPixelSize,
    normalizeImageGroupNodeState,
    normalizeNodeGroupId,
    normalizeNodeGroups,
    normalizeNodeMenuType,
    normalizePromptDocument,
    normalizeVideoInferenceNodeState,
    revokeReferenceUrl,
    sanitizeImageEditFilename,
    sanitizeTextNodeAlias,
    syncVisibleInputNodeStatesToCanvas,
  }) {


    function normalizeWorkflowReference(ref) {
    const item = jsonClone(ref, {});
    if (!item || typeof item !== 'object') return null;
    const dataUrl = dataUrlValue(item.base64) || dataUrlValue(item.imageData) || dataUrlValue(item.url) || dataUrlValue(item.imageUrl);
    if (dataUrl) {
      item.base64 = dataUrl;
      item.imageData = dataUrl;
    }
    if (String(item.url || '').startsWith('blob:')) item.url = dataUrl || '';
    if (String(item.imageUrl || '').startsWith('blob:')) item.imageUrl = '';
    if (!item.url && dataUrl) item.url = dataUrl;
    if (!item.imageUrl && !dataUrl && item.url) item.imageUrl = item.url;
    item.id = String(item.id || item.assetId || item.asset_id || item.taskId || item.task_id || item.url || item.imageUrl || `ref-${Date.now()}`);
    item.name = String(item.name || item.title || item.file || '参考图');
    item.title = String(item.title || item.name || '参考图');
    item.type = String(item.type || item.mimeType || 'image/png');
    return item;
  }

    function normalizeWorkflowReferences(refs) {
    return (Array.isArray(refs) ? refs : [])
      .map(normalizeWorkflowReference)
      .filter(Boolean)
      .slice(0, 8);
  }

    function normalizeWorkflowReferenceMap(map) {
    if (!map || typeof map !== 'object') return {};
    return Object.entries(map).reduce((acc, [nodeId, refs]) => {
      const clean = normalizeWorkflowReferences(refs);
      if (clean.length) acc[nodeId] = clean;
      return acc;
    }, {});
  }

    function normalizeWorkflowParams(params = {}, fallback = DesktopState.state.params || {}) {
    const source = params && typeof params === 'object' ? params : {};
    return {
      ...jsonClone(fallback, {}),
      ...jsonClone(source, {}),
      ratio: DesktopState.normalizeRatio(source.ratio ?? fallback.ratio, '9:16'),
      resolution: DesktopState.normalizeResolution(source.resolution ?? fallback.resolution, '2k'),
      quality: DesktopState.normalizeGptQuality(source.quality ?? fallback.quality, 'auto'),
      imageCount: DesktopState.clamp(source.imageCount ?? source.image_count ?? fallback.imageCount, 1, 8, 1),
      moderation: DesktopState.normalizeModeration(source.moderation ?? fallback.moderation, 'auto'),
      gptTaskType: DesktopState.normalizeGptTaskType(source.gptTaskType ?? source.task_type ?? fallback.gptTaskType, 'image'),
      gptProviderRoute: DesktopState.normalizeGptProviderRoute(source.gptProviderRoute ?? source.gpt_provider_route ?? fallback.gptProviderRoute, 'codex'),
      gptMainModel: DesktopState.normalizeGptMainModel(source.gptMainModel ?? source.main_model ?? fallback.gptMainModel, 'gpt-5.5'),
      reasoningEffort: DesktopState.normalizeReasoningEffort(source.reasoningEffort ?? source.reasoning_effort ?? fallback.reasoningEffort, 'medium'),
      promptMode: DesktopState.normalizePromptMode(source.promptMode ?? source.prompt_mode ?? fallback.promptMode, 'smart'),
      batchMode: DesktopState.normalizeBoolean(source.batchMode ?? source.batch_mode ?? fallback.batchMode, false),
      model: typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(source.model ?? fallback.model ?? DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
        : (source.model ?? fallback.model ?? DEFAULT_GOOGLE_MODEL)
    };
  }

    function normalizeWorkflowNode(node, nodeId) {
    const clean = jsonClone(node, {});
    if (!clean || typeof clean !== 'object') return null;
    const id = String(clean.id || nodeId || '').trim();
    if (!id) return null;
    clean.id = id;
    topazDefinition?.migrate(clean);
    clean.type = normalizeNodeMenuType(clean.type || (id === 'input' ? 'input' : 'image'));
    clean.groupId = normalizeNodeGroupId(clean.groupId);
    if (!clean.groupId) delete clean.groupId;
    clean.x = Number.isFinite(Number(clean.x)) ? Number(clean.x) : 56;
    clean.y = Number.isFinite(Number(clean.y)) ? Number(clean.y) : 72;
    clean.width = Number.isFinite(Number(clean.width))
      ? Number(clean.width)
      : (clean.type === 'input'
        ? DEFAULT_INPUT_NODE_WIDTH
        : (clean.type === 'comfy'
          ? DEFAULT_COMFY_NODE_WIDTH
          : (clean.type === 'video_inference'
            ? DEFAULT_VIDEO_INFERENCE_NODE_WIDTH
            : (clean.type === 'video'
              ? DEFAULT_VIDEO_NODE_WIDTH
              : (clean.type === 'image_group'
                ? DEFAULT_IMAGE_GROUP_NODE_WIDTH
                : (clean.type === 'upscale' ? DEFAULT_UPSCALE_NODE_WIDTH : DEFAULT_IMAGE_NODE_WIDTH))))));
    clean.height = Number.isFinite(Number(clean.height))
      ? Number(clean.height)
      : (clean.type === 'input'
        ? DEFAULT_INPUT_NODE_HEIGHT
        : (clean.type === 'comfy'
          ? DEFAULT_COMFY_NODE_HEIGHT
          : (clean.type === 'video_inference'
            ? DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT
            : (clean.type === 'video'
              ? DEFAULT_VIDEO_NODE_HEIGHT
              : (clean.type === 'image_group'
                ? DEFAULT_IMAGE_GROUP_NODE_HEIGHT
                : (clean.type === 'upscale' ? DEFAULT_UPSCALE_NODE_HEIGHT : DEFAULT_IMAGE_NODE_HEIGHT))))));
    if (clean.type === 'input') {
      clean.width = DEFAULT_INPUT_NODE_WIDTH;
      clean.height = DEFAULT_INPUT_NODE_HEIGHT;
      if (clean.provider === 'comfy' && clean.id !== 'input') {
        clean.type = 'comfy';
        clean.width = DEFAULT_COMFY_NODE_WIDTH;
        clean.height = DEFAULT_COMFY_NODE_HEIGHT;
        clean.workflow = clean.params?.workflow || clean.workflow || '';
        clean.ratio = clean.params?.ratio || clean.ratio || '1:1';
      } else {
        clean.provider = ['gpt', 'google'].includes(clean.provider) ? clean.provider : 'gpt';
      }
      clean.params = normalizeWorkflowParams(clean.params || {}, DesktopState.state.params || {});
      clean.output = {
        archiveEnabled: clean.output?.archiveEnabled !== false,
        telegramEnabled: clean.output?.telegramEnabled !== false
      };
    }
    if (clean.type === 'comfy') {
      clean.width = clamp(clean.width, MIN_COMFY_NODE_WIDTH, MAX_COMFY_NODE_WIDTH);
      clean.height = clamp(clean.height, MIN_COMFY_NODE_HEIGHT, MAX_COMFY_NODE_HEIGHT);
      clean.workflow = String(clean.workflow || clean.params?.workflow || '');
      clean.ratio = DesktopState.normalizeRatio(clean.ratio || clean.params?.ratio, '1:1');
      clean.resolution = DesktopState.normalizeResolution(clean.resolution || clean.params?.resolution, '1k');
      clean.pixelWidth = normalizeComfyPixelSize(clean.pixelWidth || clean.params?.width, DEFAULT_COMFY_PIXEL_WIDTH);
      clean.pixelHeight = normalizeComfyPixelSize(clean.pixelHeight || clean.params?.height, DEFAULT_COMFY_PIXEL_HEIGHT);
      clean.workflowParameters = clean.workflowParameters && typeof clean.workflowParameters === 'object' && !Array.isArray(clean.workflowParameters)
        ? clean.workflowParameters
        : {};
      clean.output = {
        archiveEnabled: true,
        telegramEnabled: clean.output?.telegramEnabled !== false
      };
    }
    if (clean.type === 'video_inference') {
      clean.width = clamp(clean.width, MIN_VIDEO_INFERENCE_NODE_WIDTH, MAX_VIDEO_INFERENCE_NODE_WIDTH);
      clean.height = clamp(clean.height, MIN_VIDEO_INFERENCE_NODE_HEIGHT, MAX_VIDEO_INFERENCE_NODE_HEIGHT);
      normalizeVideoInferenceNodeState(clean);
      clean.output = {
        archiveEnabled: true,
        telegramEnabled: clean.output?.telegramEnabled === true
      };
    }
    if (clean.type === 'text') {
      clean.promptDocument = normalizePromptDocument(clean.promptDocument, clean.text || '');
      clean.text = materializePromptDocument(clean.promptDocument);
      clean.alias = sanitizeTextNodeAlias(clean.alias) || nextTextNodeAlias(clean.id);
      clean.stylePresetId = String(clean.stylePresetId || '');
    }
    if (clean.type === 'image') {
      const dataUrl = dataUrlValue(clean.imageData) || dataUrlValue(clean.base64) || dataUrlValue(clean.imageUrl);
      if (dataUrl) clean.imageData = dataUrl;
      if (String(clean.imageUrl || '').startsWith('blob:')) clean.imageUrl = '';
      clean.imageName = String(clean.imageName || clean.title || '图片节点');
      clean.mimeType = String(clean.mimeType || (dataUrl ? dataUrl.slice(5, dataUrl.indexOf(';')) : 'image/png') || 'image/png');
      clean.aspectRatio = Number(clean.aspectRatio) > 0 ? Number(clean.aspectRatio) : DEFAULT_IMAGE_NODE_WIDTH / DEFAULT_IMAGE_NODE_HEIGHT;
    }
    if (clean.type === 'image_group') {
      normalizeImageGroupNodeState(clean);
      clean.items = clean.items
        .map(item => String(item.imageUrl || '').startsWith('blob:') ? { ...item, imageUrl: '' } : item)
        .filter(imageGroupItemSource);
    }
    if (clean.type === 'audio') audioNodeDefinition.normalizeState(clean);
    if (clean.type === topazDefinition?.TYPE) topazDefinition.normalize(clean);
    if (cyimgDefinition?.TYPES.includes(clean.type)) cyimgDefinition.normalize(clean);
    if (clean.type === krea2Definition?.TYPE) krea2Definition.normalize(clean);
    if (clean.type === qwen21Definition?.TYPE) qwen21Definition.normalize(clean);
    if (clean.type === videoControlDefinition?.TYPE) videoControlDefinition.normalize(clean);
    if (clean.type === topazVideoDefinition?.TYPE) topazVideoDefinition.normalize(clean);
    if (musicNodeDefinition?.TYPES.includes(clean.type)) musicNodeDefinition.normalizeState(clean);
    if (clean.type === 'video') {
      clean.width = clamp(clean.width, MIN_VIDEO_NODE_WIDTH, MAX_VIDEO_NODE_WIDTH);
      clean.height = Math.max(180, Number(clean.height || DEFAULT_VIDEO_NODE_HEIGHT));
      const mediaUrl = String(clean.mediaUrl || clean.videoUrl || '').trim();
      const posterUrl = String(clean.posterUrl || '').trim();
      clean.mediaUrl = mediaUrl.startsWith('blob:') || mediaUrl.startsWith('data:') ? '' : mediaUrl;
      clean.posterUrl = posterUrl.startsWith('blob:') || posterUrl.startsWith('data:') ? '' : posterUrl;
      clean.mediaName = String(clean.mediaName || clean.title || '视频结果');
      clean.mimeType = String(clean.mimeType || 'video/mp4');
      clean.sourceTaskId = String(clean.sourceTaskId || clean.source_task_id || '');
      clean.durationSeconds = Math.max(0, Number(clean.durationSeconds || clean.duration_seconds || 0));
      clean.mediaWidth = Math.max(0, Number(clean.mediaWidth || clean.media_width || 0));
      clean.mediaHeight = Math.max(0, Number(clean.mediaHeight || clean.media_height || 0));
      clean.fps = Math.max(1, Number(clean.fps || 24));
      clean.fileSize = Math.max(0, Number(clean.fileSize || clean.file_size || 0));
      clean.status = DesktopState.isInFlight?.(clean.status) ? 'idle' : String(clean.status || (clean.mediaUrl ? 'succeeded' : 'idle'));
      fitVideoNodeToMedia(clean);
    }
    if (clean.type === 'layout' && Array.isArray(clean.layoutInputImages)) {
      clean.layoutInputImages = clean.layoutInputImages.map(normalizeWorkflowReference).filter(Boolean);
    }
    if (clean.type === 'upscale') {
      clean.width = Number.isFinite(Number(clean.width)) ? Number(clean.width) : DEFAULT_UPSCALE_NODE_WIDTH;
      clean.height = DEFAULT_UPSCALE_NODE_HEIGHT;
      clean.model = UPSCALE_MODEL_OPTIONS.some(item => item.value === clean.model) ? clean.model : '4x-UltraSharp';
      clean.tileSize = DesktopState.clamp(clean.tileSize, 64, 2048, 256);
      clean.tileOverlap = DesktopState.clamp(clean.tileOverlap, 0, 256, 32);
      clean.device = String(clean.device || 'auto');
      clean.output = {
        archiveEnabled: true,
        telegramEnabled: clean.output?.telegramEnabled === true
      };
    }
    return clean;
  }

    function normalizeWorkflowCanvas(canvas = {}) {
    const source = canvas && typeof canvas === 'object' ? canvas : {};
    const sourceNodes = source.nodes && typeof source.nodes === 'object' ? source.nodes : {};
    const nodes = Object.entries(sourceNodes).reduce((acc, [nodeId, node]) => {
      const clean = normalizeWorkflowNode(node, nodeId);
      if (clean) acc[clean.id] = clean;
      return acc;
    }, {});
    if (!nodes.input) {
      nodes.input = { id: 'input', type: 'input', x: 56, y: 72, width: DEFAULT_INPUT_NODE_WIDTH, height: DEFAULT_INPUT_NODE_HEIGHT };
    }
    normalizeNodeGroups(nodes);
    const edges = (Array.isArray(source.edges) ? source.edges : [])
      .map((edge, index) => ({
        id: String(edge?.id || `${edge?.from || 'from'}_${edge?.to || 'to'}_${index}`),
        from: String(edge?.from || ''),
        to: String(edge?.to || ''),
        inputRole: String(edge?.inputRole || edge?.input_role || '') || undefined,
        outputRole: String(edge?.outputRole || edge?.output_role || '') || undefined,
        outputSlot: Number.isFinite(Number(edge?.outputSlot ?? edge?.output_slot))
          ? Number(edge.outputSlot ?? edge.output_slot)
          : undefined
      }))
      .filter(edge => edge.from && edge.to && edge.from !== edge.to && nodes[edge.from] && nodes[edge.to]);
    const selectedNodeIds = expandNodeIdsToGroups(
      (Array.isArray(source.selectedNodeIds) ? source.selectedNodeIds : [source.selectedNodeId])
        .map(item => String(item || ''))
        .filter(nodeId => nodes[nodeId]),
      nodes
    );
    return {
      x: Number.isFinite(Number(source.x)) ? Number(source.x) : 0,
      y: Number.isFinite(Number(source.y)) ? Number(source.y) : 0,
      scale: clamp(Number(source.scale) || 1, MIN_SCALE, MAX_SCALE),
      selectedNodeId: selectedNodeIds[0] || '',
      selectedNodeIds,
      nodes,
      edges
    };
  }

    function normalizeWorkflowOutput(output = {}) {
    const clean = jsonClone(output, {});
    if (!clean || typeof clean !== 'object') return {};
    if (DesktopState.isInFlight?.(clean.status)) {
      clean.status = 'idle';
      clean.stage = '';
      clean.progressText = '';
      clean.progress = 0;
    }
    return clean;
  }

    function normalizeWorkflowOutputs(outputs = {}) {
    if (!outputs || typeof outputs !== 'object') return {};
    return Object.entries(outputs).reduce((acc, [nodeId, output]) => {
      acc[nodeId] = normalizeWorkflowOutput(output);
      return acc;
    }, {});
  }

    function extractWorkflowState(payload = {}) {
    const raw = payload?.schema === WORKFLOW_SCHEMA
      ? payload.state
      : (payload.state || payload.workflow || payload);
    if (!raw || typeof raw !== 'object' || !raw.canvas) {
      throw new Error('工作流文件格式不正确');
    }
    const params = normalizeWorkflowParams(raw.params || {}, DesktopState.state.params || {});
    return {
      provider: ['gpt', 'google'].includes(raw.provider) ? raw.provider : 'gpt',
      inputExpanded: raw.inputExpanded !== false,
      prompt: String(raw.prompt || ''),
      referenceImages: normalizeWorkflowReferences(raw.referenceImages),
      nodeReferenceImages: normalizeWorkflowReferenceMap(raw.nodeReferenceImages),
      params,
      canvas: normalizeWorkflowCanvas(raw.canvas),
      output: {
        ...normalizeWorkflowOutput(raw.output || {}),
        archiveEnabled: raw.output?.archiveEnabled !== false,
        telegramEnabled: raw.output?.telegramEnabled !== false
      },
      outputs: normalizeWorkflowOutputs(raw.outputs || {})
    };
  }

    function revokeWorkflowReferenceUrls(refs) {
    (Array.isArray(refs) ? refs : []).forEach(revokeReferenceUrl);
  }

    function revokeCurrentWorkflowObjectUrls() {
    revokeWorkflowReferenceUrls(DesktopState.state.referenceImages);
    Object.values(DesktopState.state.nodeReferenceImages || {}).forEach(revokeWorkflowReferenceUrls);
  }

    function buildWorkflowSnapshot() {
    syncVisibleInputNodeStatesToCanvas();
    DesktopState.saveSettings();
    const state = DesktopState.state;
    return extractWorkflowState({
      provider: state.provider,
      inputExpanded: state.inputExpanded,
      prompt: state.prompt,
      referenceImages: state.referenceImages,
      nodeReferenceImages: state.nodeReferenceImages,
      params: state.params,
      canvas: state.canvas,
      output: state.output,
      outputs: state.outputs
    });
  }

    function workflowTitleFromSnapshot(snapshot) {
    const textNode = Object.values(snapshot.canvas?.nodes || {})
      .find(node => node.type === 'text' && materializeTextNode(node).trim());
    const title = String(textNode?.alias || materializeTextNode(textNode) || 'canvas-workflow').trim().slice(0, 36);
    return sanitizeImageEditFilename(title, 'canvas-workflow');
  }

    function workflowTimestamp() {
    const now = new Date();
    const pad = value => String(value).padStart(2, '0');
    return [
      now.getFullYear(),
      pad(now.getMonth() + 1),
      pad(now.getDate())
    ].join('') + '-' + [pad(now.getHours()), pad(now.getMinutes())].join('');
  }

    function normalizeWorkflowFilename(name, fallback = 'canvas-workflow') {
    const clean = sanitizeImageEditFilename(name, fallback);
    return /\.(tcflow\.json|json)$/i.test(clean) ? clean : `${clean}.tcflow.json`;
  }

    function defaultWorkflowFilename(payload) {
    return normalizeWorkflowFilename(`${payload.title || 'canvas-workflow'}-${workflowTimestamp()}`);
  }

    function defaultWorkflowSavePath(filename) {
    return `~/Downloads/${normalizeWorkflowFilename(filename || 'canvas-workflow')}`;
  }

    async function chooseWorkflowSaveFile(blob, filename) {
    if (typeof window.showSaveFilePicker !== 'function') return false;
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{
          description: 'TapCanvas 工作流',
          accept: { 'application/json': ['.tcflow.json', '.json'] }
        }]
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return true;
    } catch (error) {
      if (error?.name === 'AbortError') return null;
      return false;
    }
  }

    async function saveWorkflowToCustomPath(payload, filename) {
    if (!window.DesktopApi?.saveWorkflowFileToPath || !window.prompt) return false;
    const targetPath = window.prompt('保存工作流完整路径', defaultWorkflowSavePath(filename));
    if (targetPath === null) return null;
    const cleanPath = String(targetPath || '').trim();
    if (!cleanPath) return null;

    const request = overwrite => window.DesktopApi.saveWorkflowFileToPath({
      path: cleanPath,
      payload,
      overwrite
    });

    try {
      await request(false);
      return true;
    } catch (error) {
      const message = String(error?.message || '');
      if (message.includes('文件已存在') && window.confirm?.('文件已存在，是否覆盖？')) {
        await request(true);
        return true;
      }
      throw error;
    }
  }

    function exportWorkflowSnapshot() {
    const snapshot = buildWorkflowSnapshot();
    return {
      schema: WORKFLOW_SCHEMA,
      version: WORKFLOW_VERSION,
      createdAt: new Date().toISOString(),
      title: workflowTitleFromSnapshot(snapshot),
      app: 'tg-mini-app-img-gen',
      state: snapshot
    };
  }

    async function saveWorkflowFile() {
    const payload = exportWorkflowSnapshot();
    if (Object.values(payload.state.canvas.nodes).some(node => node.type === 'audio')) await embedAudioAssets(payload);
    const filename = defaultWorkflowFilename(payload);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const savedToFile = await chooseWorkflowSaveFile(blob, filename);
    if (savedToFile === null) return null;
    if (!savedToFile) {
      const savedToPath = await saveWorkflowToCustomPath(payload, filename);
      if (savedToPath === null) return null;
      if (!savedToPath) {
        const customName = window.prompt ? window.prompt('保存工作流文件名', filename) : filename;
        if (customName === null) return null;
        downloadBlob(blob, normalizeWorkflowFilename(customName || filename));
      }
    }
    DesktopResults.showTransientMessage('工作流文件已保存。');
    return payload;
  }

    function readWorkflowFile(file) {
    if (!file) return Promise.reject(new Error('请选择工作流文件'));
    if (typeof file.text === 'function') return file.text();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('工作流文件读取失败'));
      reader.readAsText(file, 'utf-8');
    });
  }

    async function loadWorkflowFile(file, options = {}) {
    const raw = await readWorkflowFile(file);
    let parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      throw new Error('工作流 JSON 解析失败');
    }
    return applyWorkflowSnapshot(parsed, options);
  }

    return Object.freeze({
      normalizeWorkflowReference,
      normalizeWorkflowReferences,
      normalizeWorkflowReferenceMap,
      normalizeWorkflowParams,
      normalizeWorkflowNode,
      normalizeWorkflowCanvas,
      normalizeWorkflowOutput,
      normalizeWorkflowOutputs,
      extractWorkflowState,
      revokeWorkflowReferenceUrls,
      revokeCurrentWorkflowObjectUrls,
      buildWorkflowSnapshot,
      workflowTitleFromSnapshot,
      workflowTimestamp,
      normalizeWorkflowFilename,
      defaultWorkflowFilename,
      defaultWorkflowSavePath,
      chooseWorkflowSaveFile,
      saveWorkflowToCustomPath,
      exportWorkflowSnapshot,
      saveWorkflowFile,
      readWorkflowFile,
      loadWorkflowFile,
    });
  }

  window.DesktopCanvasWorkflow = Object.freeze({ create });
})();
