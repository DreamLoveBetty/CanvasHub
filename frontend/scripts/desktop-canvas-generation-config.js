// Generation request/output configuration adapters, including existing form-to-state synchronization, provider normalization and reference ordering.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    DEFAULT_GOOGLE_MODEL,
    applyGptTaskTypeToNode,
    comfyWorkflowCatalogRef,
    comfyWorkflowDefaultSize,
    comfyWorkflowParameterOverrides,
    foldNegativeConstraint,
    getBatchPromptItems,
    getComfyInputSlots,
    getConnectedImageReferences,
    getConnectedNegativePrompt,
    getConnectedVideoReferences,
    getNodeElement,
    getNodeReferenceImages,
    getOutgoingUpscaleImageEdges,
    getPromptModeFromNode,
    getProviderFromNode,
    getVisibleInputPrompt,
    mergeNodeReferenceImages,
    normalizeComfyPixelSize,
    readFormToState,
    readOutputControlsForTask,
    readOutputControlsFromNode,
    splitBatchPromptItems,
    syncUpscaleNodeStateFromDom,
  }) {


    function readInputNodeConfig(nodeId) {
    const node = getNodeElement(nodeId);
    if (!node) throw new Error('模型节点不存在');
    if (nodeId === 'input') {
      readFormToState();
      const negativePrompt = getConnectedNegativePrompt(nodeId);
      const batchPrompts = getBatchPromptItems(nodeId).map(item => foldNegativeConstraint(item, negativePrompt));
      return {
        nodeId,
        prompt: foldNegativeConstraint(getVisibleInputPrompt(nodeId), negativePrompt),
        batchPrompts,
        provider: DesktopState.state.provider,
        params: { ...DesktopState.state.params },
        batchMode: !!DesktopState.state.params.batchMode,
        referenceImages: mergeNodeReferenceImages(nodeId, DesktopState.state.referenceImages)
      };
    }

    // GPT / Google have no negative-prompt parameter: negative text nodes become a trailing constraint.
    const negativePrompt = getConnectedNegativePrompt(nodeId);
    const batchPrompts = getBatchPromptItems(nodeId).map(item => foldNegativeConstraint(item, negativePrompt));
    return {
      nodeId,
      prompt: foldNegativeConstraint(getVisibleInputPrompt(nodeId), negativePrompt),
      batchPrompts,
      provider: getProviderFromNode(node),
      batchMode: !!node.querySelector('[data-field="batchMode"]')?.checked,
      params: {
        ratio: node.querySelector('[data-field="ratio"]')?.value || '9:16',
        resolution: node.querySelector('[data-field="resolution"]')?.value || '2k',
        model: typeof DesktopState.normalizeGoogleModel === 'function'
          ? DesktopState.normalizeGoogleModel(node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
          : (node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL),
        googleProviderRoute: DesktopState.normalizeGoogleProviderRoute(node.querySelector('[data-field="googleProviderRoute"]')?.value),
        quality: node.querySelector('[data-field="quality"]')?.value || 'auto',
        imageCount: node.querySelector('[data-field="imageCount"]')?.value || 1,
        moderation: node.querySelector('[data-field="moderation"]')?.value || 'auto',
        gptTaskType: applyGptTaskTypeToNode(node, node.querySelector('[data-field="gptTaskType"]')?.value),
        gptProviderRoute: DesktopState.normalizeGptTaskType(node.querySelector('[data-field="gptTaskType"]')?.value, 'image') === 'ppt'
          ? 'chatgpt_pool'
          : DesktopState.normalizeGptProviderRoute(node.querySelector('[data-field="gptProviderRoute"]')?.value, 'codex'),
        useThirdPartyApi: DesktopState.normalizeGptProviderRoute(node.querySelector('[data-field="gptProviderRoute"]')?.value, 'codex') === 'third_party_image_api',
        gptMainModel: DesktopState.normalizeGptMainModel(node.querySelector('[data-field="gptMainModel"]')?.value, 'gpt-5.5'),
        reasoningEffort: DesktopState.normalizeReasoningEffort(node.querySelector('[data-field="reasoningEffort"]')?.value, 'medium'),
        promptMode: getPromptModeFromNode(node, 'smart')
      },
      referenceImages: mergeNodeReferenceImages(nodeId, getNodeReferenceImages(nodeId))
    };
  }

    function readComfyNodeConfig(nodeId) {
    const element = getNodeElement(nodeId);
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!element || !node || node.type !== 'comfy') throw new Error('Comfy 工作流节点不存在');
    const selected = (comfyWorkflowCatalogRef.current.items || []).find(item => item.id === node.workflow);
    if (!node.workflow) throw new Error('请先在 Comfy 节点中选择工作流');
    if (selected && !selected.enabled) throw new Error('当前 Comfy 工作流已停用，请在设置中心重新启用或选择其他工作流');
    // Title-tagged workflows map sources onto ordered slots; an empty slot keeps the workflow's own value.
    const slotted = selected?.tag_mode === 'tags';
    const slots = slotted ? getComfyInputSlots(nodeId, selected) : null;
    const connectedReferences = getConnectedImageReferences(nodeId);
    const references = slotted ? slots.referenceImages : (selected
      ? (selected.accepts_image
        ? connectedReferences.slice(0, Math.max(1, Number(selected.max_images || 1)))
        : [])
      : connectedReferences.slice(0, 1));
    if (!slotted && selected?.accepts_image && !references.length) throw new Error('当前 Comfy 工作流需要连接一张参考图');
    const videoReferences = slotted ? slots.referenceVideos : (selected?.accepts_video
      ? getConnectedVideoReferences(nodeId).slice(0, Math.max(1, Number(selected.max_videos || 1)))
      : []);
    if (!slotted && selected?.accepts_video && !videoReferences.length) throw new Error('当前 Comfy 工作流需要连接一个视频节点');
    const audioReferences = slotted ? slots.referenceAudios : [];
    const outputKind = selected?.output_kind === 'video' ? 'video' : 'image';
    const connectedPrompt = String(getVisibleInputPrompt(nodeId) || '').trim() || String(selected?.default_prompt || '').trim();
    if (selected?.accepts_text !== false && !connectedPrompt) throw new Error('请连接一个包含提示词的文本节点');
    const prompt = selected?.accepts_text === false ? (selected?.label || 'ComfyUI 工作流') : connectedPrompt;
    const defaultSize = comfyWorkflowDefaultSize(selected);
    node.pixelWidth = normalizeComfyPixelSize(element.querySelector('[data-comfy-field="pixelWidth"]')?.value, node.pixelWidth || defaultSize.width);
    node.pixelHeight = normalizeComfyPixelSize(element.querySelector('[data-comfy-field="pixelHeight"]')?.value, node.pixelHeight || defaultSize.height);
    node.output = readOutputControlsFromNode(element, node.output || { archiveEnabled: true, telegramEnabled: true });
    node.output.archiveEnabled = true;
    return {
      nodeId,
      prompt,
      provider: 'comfy',
      batchMode: false,
      outputKind,
      expectedImageOutputCount: outputKind === 'video' ? 0 : Math.max(1, Number(selected?.output_count || 1)),
      params: {
        workflow: node.workflow,
        workflowParameters: { ...comfyWorkflowParameterOverrides(node, node.workflow) },
        width: node.pixelWidth,
        height: node.pixelHeight,
        archiveEnabled: true,
        telegramEnabled: node.output.telegramEnabled !== false
      },
      negativePrompt: selected?.accepts_negative ? getConnectedNegativePrompt(nodeId) : '',
      referenceImages: references,
      referenceVideos: videoReferences,
      referenceAudios: audioReferences,
      imageSlotOrder: slotted ? slots.imageSlotOrder : null,
      videoSlotOrder: slotted ? slots.videoSlotOrder : null,
      audioSlotOrder: slotted ? slots.audioSlotOrder : null
    };
  }

    function readUpscaleNodeConfigForReference(nodeId, firstRef, options = {}) {
    const node = getNodeElement(nodeId);
    const nodeState = syncUpscaleNodeStateFromDom(node);
    if (!node || !nodeState) throw new Error('高清放大节点不存在');
    if (!firstRef) throw new Error('请先连接一张图片到高清放大节点');
    const model = nodeState.model || '4x-UltraSharp';
    return {
      nodeId,
      prompt: options.prompt || `高清放大：${firstRef.title || firstRef.name || model}`,
      provider: 'upscale',
      batchMode: false,
      expectedImageOutputCount: 1,
      params: {
        model,
        tileSize: nodeState.tileSize || 256,
        tileOverlap: nodeState.tileOverlap || 32,
        device: nodeState.device || 'auto',
        archiveEnabled: true,
        telegramEnabled: options.telegramEnabled !== undefined
          ? options.telegramEnabled === true
          : nodeState.output?.telegramEnabled === true
      },
      referenceImages: [firstRef]
    };
  }

    function readUpscaleNodeConfig(nodeId) {
    const refs = getConnectedImageReferences(nodeId);
    if (!refs.length) throw new Error('请先连接一张图片到高清放大节点');
    return readUpscaleNodeConfigForReference(nodeId, refs[0]);
  }

    function findInputForResult(resultNodeId) {
    const edge = (DesktopState.state.canvas.edges || []).find(item => item.to === resultNodeId);
    if (edge && getNodeElement(edge.from)) return edge.from;
    return '';
  }

    function resolveResultNodeIdForRun(nodeId = 'input') {
    const directNode = DesktopState.state.canvas.nodes[nodeId];
    if (directNode?.type !== 'input') return nodeId;
    const node = getNodeElement(nodeId);
    const storedTaskType = nodeId === 'input'
      ? DesktopState.state.params?.gptTaskType
      : directNode.params?.gptTaskType;
    const taskType = DesktopState.normalizeGptTaskType(
      node?.querySelector('[data-field="gptTaskType"]')?.value || storedTaskType,
      'image'
    );
    if (taskType === 'image') return nodeId;
    const edge = (DesktopState.state.canvas.edges || []).find(item => (
      item.from === nodeId
      && DesktopState.state.canvas.nodes[item.to]?.type === 'file_output'
    ));
    if (!edge) throw new Error('PPT/PSD 请先把模型节点连接到文件结果节点。');
    return edge.to;
  }

    function readConfigForResult(resultNodeId) {
    const directNode = DesktopState.state.canvas.nodes[resultNodeId];
    if (directNode?.type === 'upscale') {
      return readUpscaleNodeConfig(resultNodeId);
    }
    if (directNode?.type === 'comfy') {
      return readComfyNodeConfig(resultNodeId);
    }
    if (directNode?.type === 'input') {
      const config = readInputNodeConfig(resultNodeId);
      const taskType = DesktopState.normalizeGptTaskType(config.params?.gptTaskType, 'image');
      if (taskType !== 'image') {
        throw new Error('PPT/PSD 请先把模型节点连接到文件结果节点。');
      }
      const outputControls = readOutputControlsForTask(resultNodeId);
      config.params = {
        ...(config.params || {}),
        archiveEnabled: outputControls.archiveEnabled !== false,
        telegramEnabled: outputControls.telegramEnabled !== false
      };
      return config;
    }
    const inputNodeId = findInputForResult(resultNodeId);
    if (!inputNodeId) throw new Error('请先手动连接模型节点到文件结果节点');
    const config = readInputNodeConfig(inputNodeId);
    const resultType = DesktopState.state.canvas.nodes[resultNodeId]?.type;
    const taskType = DesktopState.normalizeGptTaskType(config.params?.gptTaskType, 'image');
    if (resultType === 'file_output' && taskType === 'image') {
      throw new Error('文件结果节点只接收 PPT/PSD，请直接从模型节点生成图片任务。');
    }
    if (resultType === 'output' && taskType !== 'image') {
      throw new Error('PPT/PSD 请连接到文件结果节点。');
    }
    const outputControls = readOutputControlsForTask(inputNodeId, resultNodeId);
    config.params = {
      ...(config.params || {}),
      archiveEnabled: outputControls.archiveEnabled !== false,
      telegramEnabled: outputControls.telegramEnabled !== false
    };
    return config;
  }

    function batchPromptItemsForConfig(config) {
    const explicit = Array.isArray(config?.batchPrompts)
      ? config.batchPrompts.map(item => String(item || '').trim()).filter(Boolean)
      : [];
    return explicit.length ? explicit : splitBatchPromptItems(config?.prompt);
  }

    function imageCountForProvider(config) {
    const provider = String(config?.provider || 'gpt');
    if (provider === 'gpt') {
      return DesktopState.clamp(config?.params?.imageCount, 1, 8, 1);
    }
    return 1;
  }

    function expectedImageOutputCount(config) {
    if (config?.outputKind === 'video') return 0;
    const explicit = Number(config?.expectedImageOutputCount || config?.requestedImageCount || 0);
    if (explicit > 0) return Math.max(1, Math.floor(explicit));
    const taskType = DesktopState.normalizeGptTaskType(config?.params?.gptTaskType, 'image');
    if (taskType !== 'image') return 0;
    const promptCount = config?.batchMode ? batchPromptItemsForConfig(config).length : 1;
    return Math.max(1, promptCount || 1) * imageCountForProvider(config);
  }

    function getConnectedOutputImageNodeIds(modelNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === modelNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image')
      .sort((a, b) => {
        const aSlot = Number.isFinite(Number(a.outputSlot)) ? Number(a.outputSlot) : Number.MAX_SAFE_INTEGER;
        const bSlot = Number.isFinite(Number(b.outputSlot)) ? Number(b.outputSlot) : Number.MAX_SAFE_INTEGER;
        if (aSlot !== bSlot) return aSlot - bSlot;
        return String(a.id || '').localeCompare(String(b.id || ''));
      })
      .map(edge => edge.to);
  }

    function getConnectedUpscaleNodeIds(modelNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === modelNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'upscale')
      .map(edge => edge.to);
  }

    function getRunnableUpscaleNodeIds(modelNodeId) {
    return getConnectedUpscaleNodeIds(modelNodeId)
      .filter(nodeId => getOutgoingUpscaleImageEdges(nodeId).length > 0);
  }

    function getOutputImageEdges(modelNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === modelNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image')
      .sort((a, b) => {
        const aSlot = Number.isFinite(Number(a.outputSlot)) ? Number(a.outputSlot) : Number.MAX_SAFE_INTEGER;
        const bSlot = Number.isFinite(Number(b.outputSlot)) ? Number(b.outputSlot) : Number.MAX_SAFE_INTEGER;
        if (aSlot !== bSlot) return aSlot - bSlot;
        return String(a.id || '').localeCompare(String(b.id || ''));
      });
  }

    function isEmptyAutoOutputImageNode(node) {
    return node?.type === 'image'
      && node.sourceKind === 'model-output'
      && !node.imageData
      && !node.imageUrl
      && !node.sourceFile
      && !node.sourceTaskId
      && !node.sourceAssetId;
  }

    function ratioToMeta(ratio = '1:1') {
    const [w, h] = String(ratio || '1:1').split(':').map(Number);
    const width = Number.isFinite(w) && w > 0 ? w : 1;
    const height = Number.isFinite(h) && h > 0 ? h : 1;
    return { width, height };
  }

    function outputImageReference(output, index, sourceNodeId) {
    const imageUrl = output?.imagePaths?.[index] || output?.primaryImagePath || '';
    if (!imageUrl) return null;
    const file = output?.files?.[index] || output?.primaryFile || imageUrl.split('/').pop() || '';
    return {
      id: `model-output:${output?.taskId || imageUrl}:${index}`,
      sourceNodeId,
      name: file || `生成结果 ${index + 1}.png`,
      title: file || `生成结果 ${index + 1}`,
      type: 'image/png',
      url: imageUrl,
      base64: '',
      imageData: '',
      imageUrl,
      taskId: output?.taskId || '',
      prompt: output?.prompt || '',
      file,
      source: 'model-output'
    };
  }

    return Object.freeze({
      readInputNodeConfig,
      readComfyNodeConfig,
      readUpscaleNodeConfigForReference,
      readUpscaleNodeConfig,
      findInputForResult,
      resolveResultNodeIdForRun,
      readConfigForResult,
      batchPromptItemsForConfig,
      imageCountForProvider,
      expectedImageOutputCount,
      getConnectedOutputImageNodeIds,
      getConnectedUpscaleNodeIds,
      getRunnableUpscaleNodeIds,
      getOutputImageEdges,
      isEmptyAutoOutputImageNode,
      ratioToMeta,
      outputImageReference,
    });
  }

  window.DesktopCanvasGenerationConfig = Object.freeze({ create });
})();
