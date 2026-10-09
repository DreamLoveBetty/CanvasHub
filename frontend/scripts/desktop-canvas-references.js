// 模型参考图的当前状态存取、来源归一化、连线采集/排序、缩略图交互、去重/上限、历史图库附件/排版接入和资产参数套用。提示词文档 token/mention 语义不在本模块。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    addNode,
    applyGptTaskTypeToNode,
    applyPromptModeToNode,
    els,
    escapeHtml,
    getNodeElement,
    getViewportCenterWorldPoint,
    getVisibleInputPrompt,
    imageGroupItemSource,
    imageNodeSource,
    normalizeImageSourceFromGroupItem,
    poseDisplayTitle,
    screenToWorld,
    selectNode,
    setPromptTextForInputNode,
    syncFormFromState,
    updateLayoutInputCount,
  }) {


    function getNodeReferenceStore() {
    if (!DesktopState.state.nodeReferenceImages || typeof DesktopState.state.nodeReferenceImages !== 'object') {
      DesktopState.state.nodeReferenceImages = {};
    }
    return DesktopState.state.nodeReferenceImages;
  }

    function getReferenceUrl(image) {
    return String(image?.url || image?.imageUrl || image?.imageData || image?.base64 || '').trim();
  }

    function isObjectUrl(url) {
    return String(url || '').startsWith('blob:');
  }

    function revokeReferenceUrl(image) {
    const url = getReferenceUrl(image);
    if (isObjectUrl(url)) URL.revokeObjectURL(url);
  }

    function referenceKey(image) {
    return String(image?.id || image?.assetId || image?.taskId || image?.imageUrl || image?.url || image?.base64 || image?.name || '').trim();
  }

    function listPromptImageNodes() {
    let imageIndex = 0;
    return Object.values(DesktopState.state.canvas.nodes)
      .flatMap(node => {
        if (node?.type === 'image_group') {
          return (node.items || []).map((item, index) => {
            const reference = normalizeImageSourceFromGroupItem(item, node, index);
            if (!reference) return null;
            imageIndex += 1;
            return {
              ...reference,
              nodeId: node.id,
              id: `image-group:${node.id}:${item.itemId}`,
              type: 'image',
              label: `图片${index + 1} · ${item.imageName || `图片节点 ${imageIndex}`}`
            };
          }).filter(Boolean);
        }
        if (node?.type !== 'image' || !imageNodeSource(node)) return [];
        imageIndex += 1;
        const source = imageNodeSource(node);
        const label = node.imageName || node.sourceTitle || `图片节点 ${imageIndex}`;
        return [{
          nodeId: node.id,
          id: `image-node:${node.id}`,
          type: 'image',
          label,
          name: node.imageName || label,
          title: node.sourceTitle || label,
          sourceNodeId: node.id,
          imageData: node.imageData || '',
          imageUrl: node.imageUrl || '',
          url: node.imageUrl || source,
          base64: node.imageData || '',
          mimeType: node.mimeType || 'image/png',
          prompt: node.sourcePrompt || '',
          file: node.sourceFile || '',
          source: node.sourceKind || 'image-node'
        }];
      });
  }

    function listPromptVideoNodes() {
    let videoIndex = 0;
    return Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node?.type === 'video' && String(node.mediaUrl || node.videoUrl || '').trim())
      .map(node => {
        videoIndex += 1;
        const mediaUrl = String(node.mediaUrl || node.videoUrl || '').trim();
        const label = node.mediaName || node.sourceTitle || `视频节点 ${videoIndex}`;
        return {
          nodeId: node.id,
          id: `video-node:${node.id}`,
          type: 'video',
          mediaKind: 'video',
          label,
          name: node.mediaName || label,
          title: node.sourceTitle || label,
          sourceNodeId: node.id,
          mediaUrl,
          videoUrl: mediaUrl,
          url: mediaUrl,
          posterUrl: String(node.posterUrl || '').trim(),
          previewUrl: String(node.posterUrl || '').trim(),
          mimeType: node.mimeType || 'video/mp4',
          durationSeconds: Math.max(0, Number(node.durationSeconds || 0)),
          mediaWidth: Math.max(0, Number(node.mediaWidth || 0)),
          mediaHeight: Math.max(0, Number(node.mediaHeight || 0)),
          fps: Math.max(1, Number(node.fps || 24)),
          fileSize: Math.max(0, Number(node.fileSize || 0)),
          sourceTaskId: String(node.sourceTaskId || ''),
          source: node.sourceKind || 'video-node'
        };
      });
  }

    function listPromptMediaNodes() {
    return [
      ...listPromptImageNodes().map(item => ({ ...item, mediaKind: 'image' })),
      ...listPromptVideoNodes()
    ];
  }

    function renderReferenceThumbs() {
    renderNodeReferenceThumbs('input');
  }

    function referenceSourceLabel(image) {
    const source = String(image?.source || '').toLowerCase();
    if (source.includes('set')) return '候选';
    if (source.includes('layout')) return '排版';
    if (source.includes('image-node')) return '图片';
    if (source.includes('upload')) return '上传';
    if (source.includes('gallery') || source.includes('asset') || source.includes('history')) return '图库';
    if (image?.assetId || image?.asset_id || image?.taskId) return '图库';
    return isObjectUrl(getReferenceUrl(image)) ? '上传' : '参考';
  }

    function openReferenceImage(image) {
    const url = getReferenceUrl(image);
    if (!url) return;
    window.open(url, '_blank', 'noopener');
  }

    function moveReference(nodeId, index, delta) {
    const refs = getNodeReferenceImages(nodeId);
    const nextIndex = index + delta;
    if (nextIndex < 0 || nextIndex >= refs.length) return;
    [refs[index], refs[nextIndex]] = [refs[nextIndex], refs[index]];
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
  }

    function removeReferenceAt(nodeId, index) {
    const refs = getNodeReferenceImages(nodeId);
    const image = refs[index];
    if (!image) return;
    revokeReferenceUrl(image);
    refs.splice(index, 1);
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
  }

    function clearNodeReferences(nodeId) {
    const refs = getNodeReferenceImages(nodeId);
    refs.forEach(revokeReferenceUrl);
    if (nodeId === 'input') {
      DesktopState.state.referenceImages = [];
    } else {
      delete getNodeReferenceStore()[nodeId];
    }
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
    DesktopResults.showTransientMessage('参考图槽已清空。');
  }

    function renderReferenceItem(nodeId, image, index, total) {
    const item = document.createElement('div');
    const url = getReferenceUrl(image);
    const title = image?.title || image?.name || `参考图 ${index + 1}`;
    item.className = 'desk-thumb';
    item.innerHTML = `
      <img src="${escapeHtml(url)}" alt="${escapeHtml(title)}">
      <span class="desk-thumb__badge">${escapeHtml(referenceSourceLabel(image))}</span>
      <div class="desk-thumb__actions">
        <button type="button" data-ref-action="open" title="打开原图" aria-label="打开原图">↗</button>
        <button type="button" data-ref-action="left" title="左移" aria-label="左移"${index <= 0 ? ' disabled' : ''}>‹</button>
        <button type="button" data-ref-action="right" title="右移" aria-label="右移"${index >= total - 1 ? ' disabled' : ''}>›</button>
        <button type="button" data-ref-action="remove" title="移除参考图" aria-label="移除参考图">×</button>
      </div>
    `;
    item.querySelectorAll('button').forEach(button => {
      button.addEventListener('pointerdown', event => event.stopPropagation());
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        const action = button.dataset.refAction;
        if (action === 'open') openReferenceImage(image);
        if (action === 'left') moveReference(nodeId, index, -1);
        if (action === 'right') moveReference(nodeId, index, 1);
        if (action === 'remove') removeReferenceAt(nodeId, index);
      });
    });
    return item;
  }

    function normalizeImageSourceFromNode(node) {
    if (!node || node.type !== 'image') return null;
    const source = node.imageData || node.imageUrl || '';
    if (!source) return null;
    return {
      id: node.sourceAssetId || `image-node:${node.id}`,
      assetId: node.sourceAssetId || '',
      sourceNodeId: node.id,
      name: node.imageName || `${node.id}.png`,
      title: node.sourceTitle || node.imageName || `${node.id}.png`,
      prompt: node.sourcePrompt || '',
      file: node.sourceFile || '',
      taskId: node.sourceTaskId || '',
      provider: node.sourceProvider || '',
      type: node.mimeType || 'image/png',
      url: node.imageUrl || source,
      base64: node.imageData || '',
      imageData: node.imageData || '',
      imageUrl: node.imageUrl || '',
      source: node.sourceKind || 'image-node'
    };
  }

    function normalizePoseReferenceFromNode(node) {
    if (!node || node.type !== 'pose') return null;
    const source = node.exportImage || node.previewImage || '';
    if (!source) return null;
    return {
      id: `pose-node:${node.id}`,
      assetId: '',
      sourceNodeId: node.id,
      name: `${poseDisplayTitle(node, node.id)}.png`,
      title: poseDisplayTitle(node, '姿态参考图'),
      prompt: '3D mannequin pose reference',
      file: '',
      taskId: '',
      provider: '',
      type: 'image/png',
      url: source,
      base64: source.startsWith('data:') ? source : '',
      imageData: source.startsWith('data:') ? source : '',
      imageUrl: source.startsWith('data:') ? '' : source,
      source: 'pose-node'
    };
  }

    function getConnectedImageReferences(inputNodeId) {
    const incoming = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === inputNodeId)
      .map(edge => DesktopState.state.canvas.nodes[edge.from]);
    const prioritized = incoming.some(node => node?.type === 'image_group')
      ? [...incoming.filter(node => node?.type === 'image_group'), ...incoming.filter(node => node?.type !== 'image_group')]
      : incoming;
    return prioritized
      .filter(node => (
        (node?.type === 'image' && (node.imageData || node.imageUrl))
        || (node?.type === 'image_group' && node.items?.some(imageGroupItemSource))
        || (node?.type === 'layout' && node.layoutExport)
        || (node?.type === 'pose' && (node.exportImage || node.previewImage))
      ))
      .flatMap(node => {
        if (node.type === 'image') return normalizeImageSourceFromNode(node);
        if (node.type === 'image_group') {
          return node.items.map((item, index) => normalizeImageSourceFromGroupItem(item, node, index)).filter(Boolean);
        }
        if (node.type === 'pose') return normalizePoseReferenceFromNode(node);
        return {
          id: `layout:${node.id}`,
          sourceNodeId: node.id,
          name: `${node.id}.png`,
          title: node.layoutTitle || `${node.id}.png`,
          type: 'image/png',
          url: node.layoutExport,
          base64: node.layoutExport,
          imageData: node.layoutExport,
          imageUrl: '',
          source: 'layout'
        };
      })
      .filter(Boolean);
  }

    function mergeNodeReferenceImages(nodeId, directReferences = []) {
    const connected = getConnectedImageReferences(nodeId);
    const hasImageGroup = (DesktopState.state.canvas.edges || []).some(edge => (
      edge.to === nodeId && DesktopState.state.canvas.nodes[edge.from]?.type === 'image_group'
    ));
    return hasImageGroup
      ? [...connected, ...(directReferences || [])]
      : [...(directReferences || []), ...connected];
  }

    async function attachHistoryImageToLayout(item, layoutNodeId) {
    const layoutNode = DesktopState.state.canvas.nodes[layoutNodeId];
    if (!layoutNode || layoutNode.type !== 'layout') throw new Error('排版节点不存在');
    const imageUrl = String(item?.imageUrl || item?.imagePath || '').trim();
    if (!imageUrl) throw new Error('这条历史记录没有可接入排版的图片');
    const sourceId = `history:${item?.taskId || imageUrl}`;
    layoutNode.layoutInputImages = Array.isArray(layoutNode.layoutInputImages) ? layoutNode.layoutInputImages : [];
    const exists = layoutNode.layoutInputImages.some(image => image.id === sourceId || image.imageUrl === imageUrl);
    if (!exists) {
      layoutNode.layoutInputImages.push({
        id: sourceId,
        assetId: item?.assetId || item?.asset_id || item?.id || '',
        taskId: item?.taskId || '',
        name: item?.title || item?.prompt || '历史图片',
        type: 'image/png',
        imageUrl,
        imageData: '',
        prompt: item?.prompt || '',
        source: item?.source || 'gallery'
      });
    }
    selectNode(layoutNodeId);
    updateLayoutInputCount(layoutNodeId);
    DesktopState.saveSettings();
    DesktopResults.showTransientMessage(exists ? '这张图片已在排版节点中。' : '历史图片已接入排版节点。');
  }

    function getNodeReferenceImages(nodeId) {
    if (nodeId === 'input') return DesktopState.state.referenceImages;
    const store = getNodeReferenceStore();
    if (!store[nodeId]) store[nodeId] = [];
    return store[nodeId];
  }

    function findDefaultInputNodeId() {
    const selectedNodeId = DesktopState.state.canvas.selectedNodeId;
    if (DesktopState.state.canvas.nodes[selectedNodeId]?.type === 'input') return selectedNodeId;
    if (DesktopState.state.canvas.nodes.input?.type === 'input') return 'input';
    const input = Object.values(DesktopState.state.canvas.nodes || {}).find(node => node.type === 'input');
    return input?.id || addNode('input', getViewportCenterWorldPoint(-260, 0));
  }

    function referenceFromHistoryItem(item) {
    const imageUrl = String(item?.imageUrl || item?.imagePath || item?.url || item?.base64 || '').trim();
    if (!imageUrl) return null;
    return {
      id: item?.id || `asset:${item?.taskId || imageUrl}`,
      name: item?.title || item?.file || item?.prompt || '图库参考图',
      type: item?.mimeType || 'image/png',
      url: imageUrl,
      base64: String(imageUrl).startsWith('data:') ? imageUrl : '',
      imageUrl,
      imageData: String(imageUrl).startsWith('data:') ? imageUrl : '',
      taskId: item?.taskId || '',
      assetId: item?.assetId || item?.asset_id || item?.id || '',
      title: item?.title || item?.name || '图库参考图',
      prompt: item?.prompt || '',
      source: item?.source || (item?.assetId || item?.asset_id || item?.id ? 'gallery' : 'history'),
      file: item?.file || ''
    };
  }

    function addReferenceItemsToNode(nodeId, items) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'input') throw new Error('模型节点不存在');
    const refs = getNodeReferenceImages(nodeId);
    const payloads = (Array.isArray(items) ? items : [items]).map(referenceFromHistoryItem).filter(Boolean);
    if (!payloads.length) {
      DesktopResults.showTransientMessage('没有可接入模型节点的图片。');
      return 0;
    }

    let added = 0;
    const seen = new Set(refs.map(referenceKey).filter(Boolean));
    for (const item of payloads) {
      if (refs.length >= 8) break;
      const key = referenceKey(item);
      if (key && seen.has(key)) continue;
      refs.push(item);
      if (key) seen.add(key);
      added += 1;
    }
    renderNodeReferenceThumbs(nodeId);
    selectNode(nodeId);
    DesktopState.saveSettings();
    return added;
  }

    async function attachHistoryImagesToInput(items, inputNodeId = '') {
    const targetInputId = inputNodeId || findDefaultInputNodeId();
    const added = addReferenceItemsToNode(targetInputId, items);
    const refs = getNodeReferenceImages(targetInputId);
    if (!added) {
      DesktopResults.showTransientMessage(refs.length >= 8 ? '模型节点参考图已满，最多 8 张。' : '这些图片已在模型节点参考图里。');
      return targetInputId;
    }
    DesktopResults.showTransientMessage(added > 1 ? `${added} 张图片已接入模型节点参考图。` : '图片已接入模型节点参考图。');
    return targetInputId;
  }

    function providerFromAsset(asset, fallback = 'gpt') {
    const raw = String(asset?.provider || asset?.type || '').toLowerCase();
    if (raw.includes('gpt')) return 'gpt';
    if (raw.includes('google') || raw.includes('gemini')) return 'google';
    if (raw.includes('comfy')) return 'comfy';
    return fallback;
  }

    function firstParam(asset, keys) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    for (const key of keys) {
      const value = params[key] ?? asset?.[key];
      if (value !== undefined && value !== null && String(value).trim()) return value;
    }
    return '';
  }

    function extractAssetModelConfig(asset, fallbackParams = DesktopState.state.params) {
    const provider = providerFromAsset(asset, DesktopState.state.provider || 'gpt');
    const rawQuality = firstParam(asset, ['quality']);
    const resolution = firstParam(asset, ['resolution', 'image_size', 'imageSize', 'size'])
      || (['1k', '2k', '4k'].includes(String(rawQuality || '').toLowerCase()) ? rawQuality : '');
    const routeFromAsset = DesktopState.normalizeGptProviderRoute(firstParam(asset, ['gpt_provider_route', 'gptProviderRoute', 'provider_route', 'providerRoute']), fallbackParams.gptProviderRoute || 'codex');
    const legacyThirdParty = DesktopState.normalizeBoolean(firstParam(asset, ['use_third_party_api', 'useThirdPartyApi', 'third_party_api', 'thirdPartyApi']), fallbackParams.useThirdPartyApi || false);
    const gptProviderRoute = legacyThirdParty && routeFromAsset === 'codex' ? 'third_party_image_api' : routeFromAsset;
    return {
      prompt: String(asset?.prompt || '').trim(),
      provider,
      params: {
        ratio: DesktopState.normalizeRatio(firstParam(asset, ['ratio', 'aspect_ratio', 'aspectRatio']), fallbackParams.ratio || '9:16'),
        resolution: DesktopState.normalizeResolution(resolution, fallbackParams.resolution || '2k'),
        quality: DesktopState.normalizeGptQuality(rawQuality, fallbackParams.quality || 'auto'),
        imageCount: DesktopState.clamp(firstParam(asset, ['image_count', 'imageCount', 'count', 'n']) || asset?.total || fallbackParams.imageCount || 1, 1, 8, DesktopState.clamp(fallbackParams.imageCount || 1, 1, 8, 1)),
        moderation: DesktopState.normalizeModeration(firstParam(asset, ['moderation']), fallbackParams.moderation || 'auto'),
        promptMode: DesktopState.normalizePromptMode(firstParam(asset, ['prompt_mode', 'promptMode']), fallbackParams.promptMode || 'smart'),
        gptTaskType: DesktopState.normalizeGptTaskType(firstParam(asset, ['task_type', 'taskType', 'gpt_task_type', 'gptTaskType']), fallbackParams.gptTaskType || 'image'),
        gptProviderRoute,
        googleProviderRoute: firstParam(asset, ['google_provider_route', 'googleProviderRoute']) === 'google_pool' ? 'google_pool' : 'third_party',
        useThirdPartyApi: gptProviderRoute === 'third_party_image_api',
        gptMainModel: DesktopState.normalizeGptMainModel(firstParam(asset, ['main_model', 'mainModel']), fallbackParams.gptMainModel || 'gpt-5.5'),
        reasoningEffort: DesktopState.normalizeReasoningEffort(firstParam(asset, ['reasoning_effort', 'reasoningEffort']), fallbackParams.reasoningEffort || 'medium'),
        model: firstParam(asset, ['model', 'modelAlias']) || fallbackParams.model || ''
      }
    };
  }

    function shouldOverwritePrompt(currentPrompt, nextPrompt) {
    const current = String(currentPrompt || '').trim();
    const next = String(nextPrompt || '').trim();
    if (!next) return false;
    if (!current || current === next) return true;
    return window.confirm('模型节点已有提示词，是否用这张图的提示词覆盖？');
  }

    function applyProviderToNode(node, provider) {
    node.querySelectorAll('.desk-segment button[data-provider]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.provider === provider);
    });
  }

    function applyAssetConfigToInput(asset, options = {}) {
    if (!asset) {
      DesktopResults.showTransientMessage('没有可套用的图片参数。');
      return '';
    }
    const mode = options.mode || 'all';
    const targetInputId = options.inputNodeId || findDefaultInputNodeId();
    const node = getNodeElement(targetInputId);
    const nodeState = DesktopState.state.canvas.nodes[targetInputId];
    if (!node || nodeState?.type !== 'input') throw new Error('模型节点不存在');

    const applyPrompt = mode === 'all' || mode === 'prompt';
    const applyParams = mode === 'all' || mode === 'params';
    const config = extractAssetModelConfig(asset, targetInputId === 'input' ? DesktopState.state.params : {});
    const currentPrompt = getVisibleInputPrompt(targetInputId);

    if (applyPrompt && config.prompt && shouldOverwritePrompt(currentPrompt, config.prompt)) {
      setPromptTextForInputNode(targetInputId, config.prompt);
      if (targetInputId === 'input') DesktopState.state.prompt = '';
    }

    if (applyParams) {
      if (targetInputId === 'input') {
        DesktopState.state.provider = config.provider;
        DesktopState.state.params = {
          ...DesktopState.state.params,
          ...config.params
        };
        syncFormFromState();
      } else {
        applyProviderToNode(node, config.provider);
        const fieldValues = {
          ratio: config.params.ratio,
          resolution: config.params.resolution,
          quality: config.params.quality,
          imageCount: config.params.imageCount,
          moderation: config.params.moderation,
          gptTaskType: config.params.gptTaskType,
          gptProviderRoute: config.params.gptProviderRoute,
          googleProviderRoute: config.params.googleProviderRoute,
          gptMainModel: config.params.gptMainModel,
          reasoningEffort: config.params.reasoningEffort,
          promptMode: config.params.promptMode
        };
        Object.entries(fieldValues).forEach(([field, value]) => {
          const input = node.querySelector(`[data-field="${field}"]`);
          if (!input) return;
          if (input.type === 'checkbox') {
            input.checked = !!value;
          } else {
            input.value = value;
          }
        });
        applyPromptModeToNode(node, config.params.promptMode);
        applyGptTaskTypeToNode(node, config.params.gptTaskType);
      }
    } else if (targetInputId === 'input') {
      DesktopState.saveDraft();
    }

    selectNode(targetInputId);
    DesktopResults.renderIdleProviderHint?.();
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    DesktopResults.showTransientMessage(mode === 'prompt' ? '提示词已套用到模型节点。' : (mode === 'params' ? '参数已套用到模型节点。' : '提示词和参数已套用到模型节点。'));
    return targetInputId;
  }

    function getThumbWrapForNode(nodeId) {
    if (nodeId === 'input') return els.deskReferenceThumbs;
    return getNodeElement(nodeId)?.querySelector('[data-reference-thumbs]');
  }

    function renderNodeReferenceThumbs(nodeId) {
    const wrap = getThumbWrapForNode(nodeId);
    if (!wrap) return;
    const refs = getNodeReferenceImages(nodeId);
    wrap.innerHTML = '';
    refs.forEach((image, index) => {
      wrap.appendChild(renderReferenceItem(nodeId, image, index, refs.length));
    });
    if (refs.length) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'desk-thumb-clear';
      clear.title = '清空参考图槽';
      clear.setAttribute('aria-label', '清空参考图槽');
      clear.textContent = '清空';
      clear.addEventListener('pointerdown', event => event.stopPropagation());
      clear.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        clearNodeReferences(nodeId);
      });
      wrap.appendChild(clear);
    }
  }

    function findDefaultLayoutNodeId() {
    const selectedNodeId = DesktopState.state.canvas.selectedNodeId;
    if (DesktopState.state.canvas.nodes[selectedNodeId]?.type === 'layout') return selectedNodeId;
    const layout = Object.values(DesktopState.state.canvas.nodes || {}).find(node => node.type === 'layout');
    if (layout) return layout.id;
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    const center = rect
      ? screenToWorld(rect.left + rect.width / 2 + 130, rect.top + rect.height / 2)
      : { x: 520, y: 280 };
    return addNode('layout', center);
  }

    async function attachHistoryImagesToLayout(items, layoutNodeId = '') {
    const payloads = (Array.isArray(items) ? items : [items]).filter(item => item?.imageUrl || item?.imagePath);
    if (!payloads.length) {
      DesktopResults.showTransientMessage('没有可接入排版的图片。');
      return '';
    }
    const targetLayoutId = layoutNodeId || findDefaultLayoutNodeId();
    for (const item of payloads) {
      await attachHistoryImageToLayout(item, targetLayoutId);
    }
    selectNode(targetLayoutId);
    updateLayoutInputCount(targetLayoutId);
    DesktopLayoutEditor?.syncConnectedImages?.(targetLayoutId).catch(() => {});
    DesktopResults.showTransientMessage(payloads.length > 1 ? `${payloads.length} 张图片已接入排版节点。` : '图片已接入排版节点。');
    return targetLayoutId;
  }

    return Object.freeze({
      getNodeReferenceStore,
      getReferenceUrl,
      isObjectUrl,
      revokeReferenceUrl,
      referenceKey,
      listPromptImageNodes,
      listPromptVideoNodes,
      listPromptMediaNodes,
      renderReferenceThumbs,
      referenceSourceLabel,
      openReferenceImage,
      moveReference,
      removeReferenceAt,
      clearNodeReferences,
      renderReferenceItem,
      normalizeImageSourceFromNode,
      normalizePoseReferenceFromNode,
      getConnectedImageReferences,
      mergeNodeReferenceImages,
      attachHistoryImageToLayout,
      getNodeReferenceImages,
      findDefaultInputNodeId,
      referenceFromHistoryItem,
      addReferenceItemsToNode,
      attachHistoryImagesToInput,
      providerFromAsset,
      firstParam,
      extractAssetModelConfig,
      shouldOverwritePrompt,
      applyProviderToNode,
      applyAssetConfigToInput,
      getThumbWrapForNode,
      renderNodeReferenceThumbs,
      findDefaultLayoutNodeId,
      attachHistoryImagesToLayout,
    });
  }

  window.DesktopCanvasReferences = Object.freeze({ create });
})();
