// Existing generation execution, video polling/cancel, image-editor submission, output allocation and upscale chaining. Preserve API calls, ordering and failure boundaries.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    activeImageEditRef,
    addNode,
    applyNodeLayout,
    buildImageEditPrompt,
    clonePromptDocument,
    closeImageEditor,
    connectNodes,
    ensureTextNodePromptDocument,
    expectedImageOutputCount,
    exportImageEditAnnotatedDataUrl,
    findInputForResult,
    fitVideoNodeToMedia,
    getAnchor,
    getConnectedOutputImageNodeIds,
    getImageNodeSize,
    getNodeBoundsById,
    getNodeElement,
    getOutputImageEdges,
    getRunnableUpscaleNodeIds,
    imageUrlToDataUrl,
    insertImageNode,
    isEmptyAutoOutputImageNode,
    materializePromptDocument,
    normalizeVideoInferenceNodeState,
    openTextPolishModal,
    outputImageReference,
    promptDocumentFingerprint,
    ratioFromAspect,
    ratioToMeta,
    readUpscaleNodeConfigForReference,
    readVideoInferenceNodeConfig,
    refreshUpscaleNodeMode,
    refreshVideoInferenceNode,
    refreshVideoNode,
    sanitizeImageEditFilename,
    saveImageEditState,
    setImageNodeFromResult,
    updateLinkPath,
    videoConfigApi,
    videoTaskPollTimers,
  }) {
    let upscaleComponentInstallPromise = null;

    function ensureVideoResultForInference(nodeId) {
    const existing = (DesktopState.state.canvas.edges || [])
      .find(edge => edge.from === nodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'video');
    if (existing) return existing.to;
    const source = DesktopState.state.canvas.nodes[nodeId];
    const targetId = addNode('video', {
      x: Number(source?.x || 0) + Number(source?.width || DEFAULT_VIDEO_INFERENCE_NODE_WIDTH) + 220,
      y: Number(source?.y || 0) + Number(source?.height || DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT) / 2
    });
    const target = DesktopState.state.canvas.nodes[targetId];
    if (source && target) {
      target.x = source.x + source.width + 80;
      target.y = source.y + 32;
      applyNodeLayout(targetId);
    }
    connectNodes(nodeId, targetId, { quiet: true });
    return targetId;
  }

    function videoTaskOutputState(nodeId) {
    if (!DesktopState.state.outputs || typeof DesktopState.state.outputs !== 'object') {
      DesktopState.state.outputs = {};
    }
    if (!DesktopState.state.outputs[nodeId] || typeof DesktopState.state.outputs[nodeId] !== 'object') {
      DesktopState.state.outputs[nodeId] = {
        status: 'idle',
        stage: '',
        progressText: '',
        progress: 0,
        error: '',
        taskId: '',
        type: 'video'
      };
    }
    return DesktopState.state.outputs[nodeId];
  }

    function connectedVideoResultNodeId(nodeId) {
    return (DesktopState.state.canvas.edges || [])
      .find(edge => edge.from === nodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'video')?.to || '';
  }

    function isVideoTaskTerminal(status) {
    return ['succeeded', 'succeeded_no_telegram', 'failed', 'canceled', 'cancelled'].includes(String(status || '').toLowerCase());
  }

    function stopVideoTaskPolling(nodeId) {
    const timer = videoTaskPollTimers.get(nodeId);
    if (timer) window.clearTimeout(timer);
    videoTaskPollTimers.delete(nodeId);
  }

    function applyVideoTaskState(nodeId, task = {}, explicitResultId = '') {
    const output = videoTaskOutputState(nodeId);
    const status = String(task.status || output.status || 'idle');
    const params = task.params && typeof task.params === 'object' ? task.params : (output.params || {});
    output.taskId = String(task.task_id || output.taskId || '');
    output.status = status;
    output.stage = String(task.stage || output.stage || '');
    output.progressText = String(task.progress_text || task.message || output.progressText || '');
    output.progress = Math.max(0, Math.min(100, Number(task.progress ?? output.progress ?? 0)));
    output.error = String(task.display_error || task.error || (status === 'failed' ? output.progressText : '') || '');
    output.params = params;
    output.startedAt = Number(task.started_at || output.startedAt || 0);
    output.finishedAt = Number(task.finished_at || output.finishedAt || 0);

    const resultNodeId = explicitResultId || connectedVideoResultNodeId(nodeId);
    const resultNode = resultNodeId ? DesktopState.state.canvas.nodes[resultNodeId] : null;
    if (resultNode?.type === 'video') {
      resultNode.sourceTaskId = output.taskId;
      resultNode.status = ['succeeded', 'succeeded_no_telegram'].includes(status) ? 'succeeded' : status;
      resultNode.progress = output.progress;
      resultNode.progressText = output.progressText;
      resultNode.error = output.error;
      const metadata = task.video_metadata && typeof task.video_metadata === 'object' ? task.video_metadata : params;
      const resultFile = String(task.result_file || task.output_file || params.video_filename || '').trim();
      const videoPath = String(task.video_path || params.video_url || '').trim();
      if (videoPath || (resultFile && ['succeeded', 'succeeded_no_telegram'].includes(status))) {
        resultNode.mediaUrl = videoPath || `/video/${encodeURIComponent(resultFile)}`;
        resultNode.mediaName = resultFile || 'MiniMax H3 视频';
        resultNode.mimeType = 'video/mp4';
        resultNode.durationSeconds = Number(metadata.duration_seconds || resultNode.durationSeconds || 0);
        resultNode.mediaWidth = Number(metadata.width || resultNode.mediaWidth || 0);
        resultNode.mediaHeight = Number(metadata.height || resultNode.mediaHeight || 0);
        resultNode.fps = Number(metadata.fps || resultNode.fps || 24);
        resultNode.fileSize = Number(metadata.video_size_bytes || resultNode.fileSize || 0);
        fitVideoNodeToMedia(resultNode);
      }
      refreshVideoNode(resultNodeId);
    }
    refreshVideoInferenceNode(nodeId);
    DesktopState.saveSettings();
    return { output, resultNodeId, status };
  }

    function scheduleVideoTaskPoll(nodeId, taskId, delay = 2000) {
    stopVideoTaskPolling(nodeId);
    videoTaskPollTimers.set(nodeId, window.setTimeout(() => {
      pollVideoTask(nodeId, taskId).catch(() => {});
    }, delay));
  }

    async function pollVideoTask(nodeId, taskId) {
    if (!nodeId || !taskId || !DesktopState.state.canvas.nodes[nodeId]) return null;
    try {
      const task = await window.DesktopApi.getStatus(taskId);
      const applied = applyVideoTaskState(nodeId, task);
      if (DesktopState.isInFlight?.(applied.status)) {
        scheduleVideoTaskPoll(nodeId, taskId, applied.status === 'queued' ? 2500 : 1800);
      } else {
        stopVideoTaskPolling(nodeId);
        if (['succeeded', 'succeeded_no_telegram'].includes(applied.status)) {
          DesktopResults.showTransientMessage('MiniMax H3 视频已生成并归档。', 'success');
          window.DesktopHistory?.loadHistory?.().catch(() => {});
        } else if (applied.status === 'failed') {
          DesktopResults.showTransientMessage(task.display_error || task.error || 'H3 视频生成失败', 'error');
        }
      }
      return task;
    } catch (error) {
      const output = videoTaskOutputState(nodeId);
      if (DesktopState.isInFlight?.(output.status)) {
        output.progressText = '任务状态同步失败，正在重试...';
        refreshVideoInferenceNode(nodeId);
        scheduleVideoTaskPoll(nodeId, taskId, 5000);
      }
      throw error;
    }
  }

    async function cancelVideoInferenceTask(nodeId) {
    const output = videoTaskOutputState(nodeId);
    const taskId = String(output.taskId || '').trim();
    if (!taskId || !DesktopState.isInFlight?.(output.status)) return null;
    output.progressText = '正在取消 H3 视频任务...';
    refreshVideoInferenceNode(nodeId);
    const outputs = DesktopState.state.outputs;
    const task = await window.DesktopApi.cancelTask(taskId);
    if (DesktopState.state.outputs !== outputs || outputs[nodeId] !== output || output.taskId !== taskId) return task;
    stopVideoTaskPolling(nodeId);
    applyVideoTaskState(nodeId, { ...task, status: task.status || 'canceled', task_id: taskId });
    DesktopResults.showTransientMessage('H3 视频任务已取消。', 'warning');
    return task;
  }

    async function runVideoInferenceNode(nodeId) {
    const currentOutput = videoTaskOutputState(nodeId);
    if (DesktopState.isInFlight?.(currentOutput.status)) {
      return cancelVideoInferenceTask(nodeId);
    }
    const config = readVideoInferenceNodeConfig(nodeId);
    if (!window.DesktopApi?.getVideoRuntimeStatus) throw new Error('视频 Runtime API 尚未加载');
    const status = await window.DesktopApi.getVideoRuntimeStatus(true);
    videoConfigApi()?.setRuntimeStatus?.(status);
    Object.values(DesktopState.state.canvas.nodes || {})
      .filter(node => node.type === 'video_inference')
      .forEach(node => refreshVideoInferenceNode(node.id));
    if (!status?.online) {
      throw new Error(status?.message || status?.error || 'H3 Runtime 离线，请在设置中心配置本机或局域网服务');
    }
    const resultNodeId = ensureVideoResultForInference(nodeId);
    const output = videoTaskOutputState(nodeId);
    output.taskId = '';
    output.status = 'queued';
    output.stage = 'submitting';
    output.progressText = '正在上传首帧并提交 H3 任务...';
    output.progress = 1;
    output.error = '';
    output.startedAt = Date.now();
    output.finishedAt = 0;
    output.params = { ...(config.params || {}) };
    const resultNode = DesktopState.state.canvas.nodes[resultNodeId];
    if (resultNode) {
      resultNode.status = 'queued';
      resultNode.progress = 1;
      resultNode.progressText = output.progressText;
      resultNode.error = '';
    }
    refreshVideoInferenceNode(nodeId);
    refreshVideoNode(resultNodeId);
    DesktopState.saveSettings();
    try {
      const response = await window.DesktopApi.submitVideoTask(config);
      const taskId = String(response?.task_id || '').trim();
      if (!taskId) throw new Error('后端没有返回 H3 task_id');
      output.taskId = taskId;
      output.status = response.status || 'queued';
      output.progressText = response.message || 'H3 视频任务已提交';
      if (resultNode) resultNode.sourceTaskId = taskId;
      applyVideoTaskState(nodeId, { ...response, task_id: taskId }, resultNodeId);
      scheduleVideoTaskPoll(nodeId, taskId, 900);
      DesktopResults.showTransientMessage('MiniMax H3 视频任务已提交，节点会持续显示进度。', 'success');
      return response;
    } catch (error) {
      applyVideoTaskState(nodeId, {
        status: 'failed',
        stage: 'submit_failed',
        progress: 100,
        progress_text: error?.message || 'H3 视频任务提交失败',
        error: error?.message || String(error || '')
      }, resultNodeId);
      throw error;
    }
  }

    function restoreVideoTaskPolling() {
    Object.values(DesktopState.state.canvas.nodes || {})
      .filter(node => node?.type === 'video_inference')
      .forEach(node => {
        const output = videoTaskOutputState(node.id);
        const taskId = String(output.taskId || '').trim();
        if (taskId && DesktopState.isInFlight?.(output.status)) {
          scheduleVideoTaskPoll(node.id, taskId, 250);
        }
      });
  }

    async function loadVideoRuntimeContext() {
    if (!window.DesktopApi) return null;
    const [capabilities, status] = await Promise.all([
      window.DesktopApi.getVideoRuntimeCapabilities?.().catch(() => null),
      window.DesktopApi.getVideoRuntimeStatus?.(true).catch(() => null)
    ]);
    if (capabilities) videoConfigApi()?.setCapabilities?.(capabilities);
    if (status) videoConfigApi()?.setRuntimeStatus?.(status);
    Object.values(DesktopState.state.canvas.nodes || {})
      .filter(node => node.type === 'video_inference')
      .forEach(node => {
        normalizeVideoInferenceNodeState(node);
        refreshVideoInferenceNode(node.id);
      });
    DesktopState.saveSettings();
    return { capabilities, status };
  }

    async function runTextNodeGptPolish(node, nodeState, triggerButton) {
    const originalDocument = clonePromptDocument(ensureTextNodePromptDocument(nodeState), nodeState.text || '');
    const originalText = materializePromptDocument(originalDocument).trim();
    if (!originalText) {
      DesktopResults.showTransientMessage('先在文本节点里输入提示词片段。');
      return;
    }
    if (!window.DesktopApi?.polishPromptText) {
      throw new Error('润色 API 未加载');
    }
    const previousLabel = triggerButton?.textContent || '';
    if (triggerButton) {
      triggerButton.disabled = true;
      triggerButton.textContent = '润色中';
    }
    try {
      const result = await window.DesktopApi.polishPromptText({ text: originalText });
      const fullPrompt = String(result.full_prompt || '').trim();
      const compactPrompt = String(result.compact_prompt || fullPrompt).trim();
      if (!fullPrompt) throw new Error('润色结果为空');
      openTextPolishModal({
        nodeId: node.dataset.nodeId,
        originalText,
        originalDocument,
        sourceFingerprint: promptDocumentFingerprint(originalDocument, originalText),
        fullPrompt,
        compactPrompt,
        modules: result.modules || [],
        model: result.model || ''
      });
      DesktopResults.showTransientMessage('润色完成，请选择版本后应用。');
    } finally {
      if (triggerButton) {
        triggerButton.disabled = false;
        triggerButton.textContent = previousLabel || 'Gpt 润色';
      }
    }
  }

    function pruneExtraEmptyOutputImages(modelNodeId, keepCount) {
    const edges = getOutputImageEdges(modelNodeId);
    let changed = false;
    edges.slice(Math.max(0, keepCount)).forEach(edge => {
      const node = DesktopState.state.canvas.nodes[edge.to];
      if (!isEmptyAutoOutputImageNode(node)) return;
      delete DesktopState.state.canvas.nodes[edge.to];
      const element = getNodeElement(edge.to);
      if (element) element.remove();
      changed = true;
    });
    if (changed) {
      DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || [])
        .filter(edge => DesktopState.state.canvas.nodes[edge.from] && DesktopState.state.canvas.nodes[edge.to]);
    }
    return changed;
  }

    function assignImageOutputSlots(modelNodeId) {
    const edges = getOutputImageEdges(modelNodeId);
    edges.forEach((edge, index) => {
      edge.outputSlot = index;
    });
    return edges.map(edge => edge.to);
  }

    function outputNodeCenterForSlot(modelNodeId, slotIndex, config) {
    const model = DesktopState.state.canvas.nodes[modelNodeId];
    const bounds = getNodeBoundsById(modelNodeId) || { x: model?.x || 120, y: model?.y || 120, width: model?.width || 512, height: model?.height || 360 };
    const meta = ratioToMeta(config?.params?.ratio || '1:1');
    const size = getImageNodeSize(meta);
    const columns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(Math.max(1, expectedImageOutputCount(config))))));
    const col = slotIndex % columns;
    const row = Math.floor(slotIndex / columns);
    return {
      x: bounds.x + bounds.width + 180 + col * (size.width + 32) + size.width / 2,
      y: bounds.y + 82 + row * (size.height + 32) + size.height / 2
    };
  }

    function modelOutputPopOrigin(modelNodeId) {
    const anchor = getAnchor(modelNodeId, 'right');
    return {
      x: anchor.x + 10,
      y: anchor.y
    };
  }

    function createOutputImageNode(modelNodeId, slotIndex, config) {
    const meta = ratioToMeta(config?.params?.ratio || '1:1');
    const nodeId = insertImageNode({
      imageName: `生成结果 ${slotIndex + 1}`,
      mimeType: 'image/png',
      source: 'model-output',
      meta
    }, outputNodeCenterForSlot(modelNodeId, slotIndex, config), {
      popIndex: slotIndex,
      popOrigin: modelOutputPopOrigin(modelNodeId)
    });
    const edgeId = connectNodes(modelNodeId, nodeId, { outputSlot: slotIndex, quiet: true });
    const edge = (DesktopState.state.canvas.edges || []).find(item => item.id === edgeId);
    if (edge) edge.outputSlot = slotIndex;
    return nodeId;
  }

    function ensureImageOutputsForConfig(resultNodeId, config) {
    const directType = DesktopState.state.canvas.nodes[resultNodeId]?.type;
    const modelNodeId = directType === 'input' || directType === 'comfy'
      ? resultNodeId
      : (config?.nodeId || findInputForResult(resultNodeId));
    if (!modelNodeId || !['input', 'comfy', 'topaz'].includes(DesktopState.state.canvas.nodes[modelNodeId]?.type)) return [];
    const expected = expectedImageOutputCount(config);
    config.expectedImageOutputCount = expected;
    if (!expected) return [];
    const existing = getConnectedOutputImageNodeIds(modelNodeId);
    if (getRunnableUpscaleNodeIds(modelNodeId).length && !existing.length) {
      return [];
    }
    pruneExtraEmptyOutputImages(modelNodeId, expected);
    for (let index = existing.length; index < expected; index += 1) {
      existing.push(createOutputImageNode(modelNodeId, index, config));
    }
    const ordered = assignImageOutputSlots(modelNodeId);
    updateLinkPath();
    DesktopState.saveSettings();
    return ordered.slice(0, expected);
  }

    async function ensureUpscaleComponent(modelName) {
    if (String(modelName || '').startsWith('topaz-')) throw new Error('Topaz 已迁移为独立节点，请使用 Topaz Gigapixel 节点');
    const catalog = await DesktopApi.getUpscaleModels();
    const model = (catalog.models || []).find(item => item.id === modelName);
    if (model?.available) return catalog;
    if (upscaleComponentInstallPromise) return upscaleComponentInstallPromise;

    const component = catalog.component || {};
    if (!component.configured) {
      throw new Error('高清放大组件下载源尚未配置。');
    }

    upscaleComponentInstallPromise = (async () => {
      DesktopResults.showTransientMessage('首次使用，正在下载高清放大组件...', 'busy');
      await DesktopApi.installUpscaleComponent();
      const deadline = Date.now() + 45 * 60 * 1000;
      let lastProgressBucket = -1;
      while (Date.now() < deadline) {
        const status = await DesktopApi.getUpscaleComponentStatus();
        if (status.status === 'failed') throw new Error(status.error || '高清放大组件安装失败');
        if (status.installed && status.status === 'ready') {
          const refreshed = await DesktopApi.getUpscaleModels();
          const readyModel = (refreshed.models || []).find(item => item.id === modelName);
          if (!readyModel?.available) throw new Error(`高清放大模型不可用：${modelName}`);
          DesktopResults.showTransientMessage('高清放大组件安装完成。', 'success');
          return refreshed;
        }
        const progressBucket = Math.floor(Number(status.progress || 0) * 10);
        if (progressBucket !== lastProgressBucket && progressBucket > 0) {
          lastProgressBucket = progressBucket;
          DesktopResults.showTransientMessage(`高清放大组件下载中 ${Math.min(100, progressBucket * 10)}%`, 'busy');
        }
        await new Promise(resolve => window.setTimeout(resolve, 1000));
      }
      throw new Error('高清放大组件下载超时，请稍后重试。');
    })().finally(() => {
      upscaleComponentInstallPromise = null;
    });
    return upscaleComponentInstallPromise;
  }

    async function submitUpscaleReference(upscaleNodeId, reference, options = {}) {
    const config = readUpscaleNodeConfigForReference(upscaleNodeId, reference, {
      prompt: options.prompt || `高清放大：${reference?.title || reference?.name || '生成结果'}`,
      telegramEnabled: false
    });
    await ensureUpscaleComponent(config.params?.model || '4x-UltraSharp');
    return DesktopResults.submitConfigToResult(config, upscaleNodeId);
  }

    async function runUpscaleChainsForOutput(resultNodeId, output) {
    if (!resultNodeId || !output?.imagePaths?.length) return 0;
    const resultNode = DesktopState.state.canvas.nodes[resultNodeId];
    if (resultNode?.type === 'upscale') return 0;
    if (String(output?.type || '').toLowerCase() === 'upscale') return 0;
    const modelNodeId = resultNode?.type === 'input' || resultNode?.type === 'comfy'
      ? resultNodeId
      : findInputForResult(resultNodeId);
    if (!modelNodeId || !['input', 'comfy'].includes(DesktopState.state.canvas.nodes[modelNodeId]?.type)) return 0;
    const upscaleNodeIds = getRunnableUpscaleNodeIds(modelNodeId);
    if (!upscaleNodeIds.length) return 0;

    let submitted = 0;
    for (const upscaleNodeId of upscaleNodeIds) {
      const node = DesktopState.state.canvas.nodes[upscaleNodeId];
      const reference = outputImageReference(output, 0, modelNodeId);
      const sourceKey = `${output?.taskId || output?.primaryImagePath || reference?.imageUrl || ''}:${upscaleNodeId}`;
      if (!node || node.type !== 'upscale' || !reference || !sourceKey || node.autoUpscaleSourceKey === sourceKey) continue;
      node.autoUpscaleSourceKey = sourceKey;
      refreshUpscaleNodeMode(upscaleNodeId);
      submitted += 1;
      submitUpscaleReference(upscaleNodeId, reference, {
        prompt: `高清放大：${reference.title || '生成结果'}`
      }).catch(error => {
        node.autoUpscaleSourceKey = '';
        DesktopResults.showError(error, upscaleNodeId);
      });
    }
    if (submitted) DesktopState.saveSettings();
    return submitted;
  }

    async function populateResultImageNodes(resultNodeId, output) {
    if (!resultNodeId || !output?.imagePaths?.length) return 0;
    const targets = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === resultNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image')
      .sort((a, b) => {
        const aSlot = Number.isFinite(Number(a.outputSlot)) ? Number(a.outputSlot) : Number.MAX_SAFE_INTEGER;
        const bSlot = Number.isFinite(Number(b.outputSlot)) ? Number(b.outputSlot) : Number.MAX_SAFE_INTEGER;
        if (aSlot !== bSlot) return aSlot - bSlot;
        return String(a.id || '').localeCompare(String(b.id || ''));
      })
      .map(edge => edge.to);
    let count = 0;
    const limit = Math.min(targets.length, output.imagePaths.length);
    for (let index = 0; index < limit; index += 1) {
      if (await setImageNodeFromResult(targets[index], resultNodeId, output, index)) count += 1;
    }
    return count;
  }

    async function submitImageEditor() {
    const currentState = activeImageEditRef.current;
    const node = currentState?.nodeId ? DesktopState.state.canvas.nodes[currentState.nodeId] : null;
    if (!node || node.type !== 'image') throw new Error('图片节点不存在');
    const targetOutputId = (DesktopState.state.canvas.edges || [])
      .find(edge => edge.from === node.id && DesktopState.state.canvas.nodes[edge.to]?.type === 'input')
      ?.to;
    if (!targetOutputId) throw new Error('请先把图片节点连接到模型节点，再提交编辑');
    const editState = await saveImageEditState(currentState) || {};
    const prompt = buildImageEditPrompt(editState.editPrompt, !!editState.maskData || !!editState.projectJson?.hasMask);
    if (!prompt) throw new Error('请先填写编辑说明');
    const sourceDataUrl = node.imageData || await imageUrlToDataUrl(node.imageUrl);
    const annotatedDataUrl = await exportImageEditAnnotatedDataUrl();
    const ratio = ratioFromAspect(node.aspectRatio || (node.width / Math.max(1, node.height)), DesktopState.state.params.ratio || '1:1');
    const referenceImages = [{
      id: node.sourceAssetId || `image-node:${node.id}`,
      name: node.imageName || `${node.id}.png`,
      type: node.mimeType || 'image/png',
      url: sourceDataUrl,
      base64: sourceDataUrl,
      imageData: sourceDataUrl,
      imageUrl: sourceDataUrl,
      taskId: node.sourceTaskId || '',
      assetId: node.sourceAssetId || '',
      title: node.sourceTitle || node.imageName || `${node.id}.png`,
      prompt: node.sourcePrompt || '',
      source: 'image-node-edit',
      file: node.sourceFile || '',
      sourceNodeId: node.id
    }];
    if (annotatedDataUrl) {
      referenceImages.push({
        id: `${node.id}:annotated`,
        name: `${sanitizeImageEditFilename(node.imageName || node.id)}-annotated.png`,
        type: 'image/png',
        url: annotatedDataUrl,
        base64: annotatedDataUrl,
        imageData: annotatedDataUrl,
        imageUrl: annotatedDataUrl,
        taskId: node.sourceTaskId || '',
        assetId: node.sourceAssetId || '',
        title: `${node.imageName || node.id} 标注图`,
        prompt: editState.editPrompt || '',
        source: 'image-node-annotated',
        file: `${sanitizeImageEditFilename(node.imageName || node.id)}-annotated.png`,
        sourceNodeId: node.id
      });
    }
    const config = {
      prompt,
      provider: 'gpt',
      params: {
        ...DesktopState.state.params,
        ratio,
        imageCount: 1,
        promptMode: DesktopState.state.params.promptMode || 'smart'
      },
      referenceImages,
      mask: editState.maskData || ''
    };
    closeImageEditor();
    ensureImageOutputsForConfig(targetOutputId, config);
    return DesktopResults.submitConfigToResult(config, targetOutputId);
  }

    return Object.freeze({
      ensureVideoResultForInference,
      videoTaskOutputState,
      connectedVideoResultNodeId,
      isVideoTaskTerminal,
      stopVideoTaskPolling,
      applyVideoTaskState,
      scheduleVideoTaskPoll,
      pollVideoTask,
      cancelVideoInferenceTask,
      runVideoInferenceNode,
      restoreVideoTaskPolling,
      loadVideoRuntimeContext,
      runTextNodeGptPolish,
      pruneExtraEmptyOutputImages,
      assignImageOutputSlots,
      outputNodeCenterForSlot,
      modelOutputPopOrigin,
      createOutputImageNode,
      ensureImageOutputsForConfig,
      ensureUpscaleComponent,
      submitUpscaleReference,
      runUpscaleChainsForOutput,
      populateResultImageNodes,
      submitImageEditor,
    });
  }

  window.DesktopCanvasGeneration = Object.freeze({ create });
})();
