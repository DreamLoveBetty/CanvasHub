// 图片组 item/角色及尺寸规范化、组建/添加/解组及边迁移、持久排序、节点 HTML/刷新、实际模型图片角色约束；转场及 token DOM 由宿主回调接入。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    DEFAULT_IMAGE_NODE_HEIGHT,
    DEFAULT_IMAGE_NODE_WIDTH,
    IMAGE_GROUP_FILTER_OUTSET_PX,
    IMAGE_GROUP_IDENTITY_WIDTH_PX,
    IMAGE_GROUP_LAYOUT_VERSION,
    IMAGE_GROUP_LIQUID_SHELL_PX,
    IMAGE_GROUP_MAX_COLUMNS,
    IMAGE_GROUP_MAX_ITEMS,
    IMAGE_GROUP_MOTHER_HEIGHT_PX,
    IMAGE_GROUP_MOTHER_RADIUS_PX,
    IMAGE_GROUP_MOTHER_TOP_PX,
    IMAGE_GROUP_ROLES,
    IMAGE_GROUP_ROLE_INSTRUCTIONS,
    IMAGE_GROUP_ROLE_PRIORITY_NOTE,
    IMAGE_GROUP_ROW_STEP_PX,
    IMAGE_GROUP_THUMB_PX,
    IMAGE_GROUP_THUMB_STEP_PX,
    IMAGE_GROUP_TRAILING_SPACE_PX,
    MAX_IMAGE_GROUP_NODE_WIDTH,
    MIN_IMAGE_GROUP_NODE_WIDTH,
    animateImageGroupItemFlip,
    animateImagesIntoGroup,
    animateImagesOutOfGroup,
    applyNodeLayout,
    captureImageGroupItemRects,
    captureImageNodeTransitionSources,
    clamp,
    dataUrlValue,
    discardFloatingSwellState,
    ensureGraphDom,
    ensureNodeEdgeHandles,
    escapeHtml,
    freezeImageReferenceTokens,
    getBoundsForNodeIds,
    getConnectedImageReferences,
    getNodeElement,
    getSelectedNodeIds,
    imageNodeSource,
    jsonClone,
    migrateImageReferenceTokensToGroup,
    nextNodeId,
    normalizeNodeGroups,
    orderTransitionSourcesForNodes,
    refreshImageReferenceTokens,
    setSelectedNodes,
    updateLinkPath,
  }) {
    let imageGroupItemSequence = 0;

    function createImageGroupItemId() {
    imageGroupItemSequence += 1;
    const unique = globalThis.crypto?.randomUUID?.()?.replaceAll('-', '')
      || `${Date.now().toString(36)}${imageGroupItemSequence.toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    return `image_group_item_${unique}`;
  }

    function normalizeImageGroupRole(value, fallback = 'reference') {
    const raw = String(value || '').trim().toLowerCase();
    // “细节参考”曾经没有清晰的边界。旧数据按通用参考迁移，避免误判为服饰参考。
    const normalized = raw === 'detail' ? 'reference' : raw;
    if (IMAGE_GROUP_ROLES.some(item => item.value === normalized)) return normalized;
    const normalizedFallback = String(fallback || '').trim().toLowerCase();
    return IMAGE_GROUP_ROLES.some(item => item.value === normalizedFallback) ? normalizedFallback : 'reference';
  }

    function imageGroupRoleLabel(value) {
    const normalized = normalizeImageGroupRole(value);
    return IMAGE_GROUP_ROLES.find(item => item.value === normalized)?.label || '参考';
  }

    function imageGroupRoleInstruction(value) {
    return IMAGE_GROUP_ROLE_INSTRUCTIONS[normalizeImageGroupRole(value)]
      || IMAGE_GROUP_ROLE_INSTRUCTIONS.reference;
  }

    function getImageGroupItem(groupId, itemId, sourceNodeId = '') {
    const group = DesktopState.state.canvas.nodes[String(groupId || '')];
    if (!group || group.type !== 'image_group' || !Array.isArray(group.items)) return null;
    return group.items.find(item => (
      (itemId && item.itemId === itemId)
      || (sourceNodeId && item.sourceNodeId === sourceNodeId)
    )) || null;
  }

    function imageGroupColumnCount(itemCount = 0) {
    return clamp(Math.max(2, Number(itemCount) || 0), 2, IMAGE_GROUP_MAX_COLUMNS);
  }

    function imageGroupRowCount(itemCount = 0) {
    return Math.max(1, Math.ceil(Math.max(1, Number(itemCount) || 0) / IMAGE_GROUP_MAX_COLUMNS));
  }

    function naturalImageGroupNodeWidth(itemCount = 0) {
    const columns = imageGroupColumnCount(itemCount);
    return IMAGE_GROUP_IDENTITY_WIDTH_PX
      + IMAGE_GROUP_THUMB_PX
      + Math.max(0, columns - 1) * IMAGE_GROUP_THUMB_STEP_PX
      + IMAGE_GROUP_TRAILING_SPACE_PX;
  }

    function compactImageGroupNodeWidth(itemCount = 0) {
    return clamp(
      naturalImageGroupNodeWidth(Math.max(2, Number(itemCount) || 0)),
      MIN_IMAGE_GROUP_NODE_WIDTH,
      MAX_IMAGE_GROUP_NODE_WIDTH
    );
  }

    function imageGroupMotherHeight(itemCount = 0) {
    return IMAGE_GROUP_MOTHER_HEIGHT_PX
      + Math.max(0, imageGroupRowCount(itemCount) - 1) * IMAGE_GROUP_ROW_STEP_PX;
  }

    function imageGroupNodeHeight(itemCount = 0) {
    return IMAGE_GROUP_MOTHER_TOP_PX * 2 + imageGroupMotherHeight(itemCount);
  }

    function imageGroupThumbPosition(index = 0) {
    const normalizedIndex = Math.max(0, Number(index) || 0);
    const column = normalizedIndex % IMAGE_GROUP_MAX_COLUMNS;
    const row = Math.floor(normalizedIndex / IMAGE_GROUP_MAX_COLUMNS);
    return {
      left: IMAGE_GROUP_IDENTITY_WIDTH_PX + column * IMAGE_GROUP_THUMB_STEP_PX,
      top: IMAGE_GROUP_MOTHER_TOP_PX
        + (IMAGE_GROUP_MOTHER_HEIGHT_PX - IMAGE_GROUP_THUMB_PX) / 2
        + row * IMAGE_GROUP_ROW_STEP_PX,
      column,
      row
    };
  }

    function sortImageNodesForGroup(nodes = []) {
    return [...nodes].sort((a, b) => {
      const aCenterY = a.y + a.height / 2;
      const bCenterY = b.y + b.height / 2;
      const rowTolerance = Math.min(a.height, b.height) * 0.35;
      return Math.abs(aCenterY - bCenterY) <= rowTolerance ? a.x - b.x : a.y - b.y;
    });
  }

    function imageNodesForGroupSelection() {
    const selected = getSelectedNodeIds()
      .map(nodeId => DesktopState.state.canvas.nodes[nodeId])
      .filter(Boolean);
    if (
      selected.length < 2
      || selected.length > IMAGE_GROUP_MAX_ITEMS
      || selected.some(node => node.type !== 'image' || !imageNodeSource(node))
    ) return [];
    return sortImageNodesForGroup(selected);
  }

    function nextCanvasEdgeId(fromNodeId, toNodeId, suffix = '') {
    return `${fromNodeId}_${toNodeId}_${Date.now()}_${suffix || Math.random().toString(36).slice(2, 7)}`;
  }

    function createImageGroupFromNodes(nodes, options = {}) {
    const uniqueIds = new Set();
    const candidates = (nodes || []).filter(node => {
      if (node?.type !== 'image' || !imageNodeSource(node) || uniqueIds.has(node.id)) return false;
      uniqueIds.add(node.id);
      return true;
    });
    const requestedOrder = Array.isArray(options.orderedNodeIds) ? options.orderedNodeIds : [];
    const byId = new Map(candidates.map(node => [node.id, node]));
    const imageNodes = (requestedOrder.length
      ? requestedOrder.map(nodeId => byId.get(nodeId)).filter(Boolean).concat(candidates.filter(node => !requestedOrder.includes(node.id)))
      : sortImageNodesForGroup(candidates)).slice(0, IMAGE_GROUP_MAX_ITEMS);
    if (imageNodes.length < 2) return '';
    const memberIds = new Set(imageNodes.map(node => node.id));
    const bounds = getBoundsForNodeIds([...memberIds]);
    if (!bounds) return '';
    const transitionSources = orderTransitionSourcesForNodes(options.transitionSources, imageNodes);
    const resolvedTransitionSources = transitionSources.length === imageNodes.length
      ? transitionSources
      : captureImageNodeTransitionSources(imageNodes);
    const groupId = nextNodeId('image_group');
    const width = compactImageGroupNodeWidth(imageNodes.length);
    const height = imageGroupNodeHeight(imageNodes.length);
    const groupNode = normalizeImageGroupNodeState({
      id: groupId,
      type: 'image_group',
      title: '图片组',
      x: Number.isFinite(Number(options.positionWorld?.x))
        ? Number(options.positionWorld.x)
        : bounds.centerX - width / 2,
      y: Number.isFinite(Number(options.positionWorld?.y))
        ? Number(options.positionWorld.y)
        : bounds.centerY - height / 2,
      width,
      height,
      items: imageNodes.map(createImageGroupItemFromNode),
      memberEdges: (DesktopState.state.canvas.edges || [])
        .filter(edge => memberIds.has(edge.from) || memberIds.has(edge.to))
        .map(edge => ({ ...edge }))
    });
    groupNode.originX = groupNode.x;
    groupNode.originY = groupNode.y;

    const migratedTargets = new Set();
    const nextEdges = [];
    (DesktopState.state.canvas.edges || []).forEach(edge => {
      if (memberIds.has(edge.to)) return;
      if (memberIds.has(edge.from)) {
        const target = DesktopState.state.canvas.nodes[edge.to];
        if (!['input', 'comfy'].includes(target?.type) || migratedTargets.has(edge.to)) return;
        migratedTargets.add(edge.to);
        nextEdges.push({
          ...edge,
          id: nextCanvasEdgeId(groupId, edge.to, migratedTargets.size),
          from: groupId,
          outputSlot: undefined
        });
        return;
      }
      nextEdges.push(edge);
    });

    imageNodes.forEach(node => {
      const element = getNodeElement(node.id);
      discardFloatingSwellState(element);
      element?.remove();
      delete DesktopState.state.canvas.nodes[node.id];
      delete DesktopState.state.outputs[node.id];
    });
    DesktopState.state.canvas.nodes[groupId] = groupNode;
    DesktopState.state.canvas.edges = nextEdges;
    normalizeNodeGroups();
    ensureGraphDom();
    applyNodeLayout(groupId);
    migrateImageReferenceTokensToGroup(groupId);
    refreshImageReferenceTokens(groupId);
    setSelectedNodes([groupId], false);
    updateLinkPath();
    DesktopState.saveSettings({ criticalCanvas: true });
    if (!options.skipTransition) requestAnimationFrame(() => animateImagesIntoGroup(resolvedTransitionSources, groupId));
    if (!options.quiet) {
      DesktopResults.showTransientMessage(`已组成图片组，当前顺序为图片1至图片${imageNodes.length}。`);
    }
    return groupId;
  }

    function createImageGroupFromSelection() {
    const selectedCount = getSelectedNodeIds().length;
    if (selectedCount > IMAGE_GROUP_MAX_ITEMS) {
      DesktopResults.showTransientMessage(`一个图片组最多支持 ${IMAGE_GROUP_MAX_ITEMS} 张图片。`);
      return '';
    }
    const imageNodes = imageNodesForGroupSelection();
    if (imageNodes.length < 2) {
      DesktopResults.showTransientMessage('请选择至少两个已有图片的图片节点。');
      return '';
    }
    return createImageGroupFromNodes(imageNodes);
  }

    function appendImageNodeToGroup(imageNodeId, groupId, options = {}) {
    const imageNode = DesktopState.state.canvas.nodes[imageNodeId];
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    if (imageNode?.type !== 'image' || !imageNodeSource(imageNode) || groupNode?.type !== 'image_group') return '';
    normalizeImageGroupNodeState(groupNode);
    if (groupNode.items.length >= IMAGE_GROUP_MAX_ITEMS) {
      if (!options.quiet) DesktopResults.showTransientMessage(`图片组最多支持 ${IMAGE_GROUP_MAX_ITEMS} 张图片。`);
      return '';
    }
    const transitionSources = (options.transitionSources || []).filter(source => source?.sourceNodeId === imageNodeId);
    const resolvedTransitionSources = transitionSources.length
      ? transitionSources
      : captureImageNodeTransitionSources([imageNode]);
    const oldX = groupNode.x;
    const oldCenterX = groupNode.x + groupNode.width / 2;
    const imageEdges = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === imageNodeId || edge.to === imageNodeId)
      .map(edge => ({ ...edge }));
    const memberEdgeKeys = new Set((groupNode.memberEdges || []).map(edge => `${edge.id}:${edge.from}:${edge.to}`));
    imageEdges.forEach(edge => {
      const key = `${edge.id}:${edge.from}:${edge.to}`;
      if (!memberEdgeKeys.has(key)) groupNode.memberEdges.push(edge);
    });

    const nextEdges = [];
    const groupTargets = new Set((DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === groupId)
      .map(edge => edge.to));
    (DesktopState.state.canvas.edges || []).forEach(edge => {
      if (edge.from !== imageNodeId && edge.to !== imageNodeId) {
        nextEdges.push(edge);
        return;
      }
      if (edge.from !== imageNodeId) return;
      const target = DesktopState.state.canvas.nodes[edge.to];
      if (!['input', 'comfy'].includes(target?.type) || groupTargets.has(edge.to)) return;
      groupTargets.add(edge.to);
      nextEdges.push({
        ...edge,
        id: nextCanvasEdgeId(groupId, edge.to, groupTargets.size),
        from: groupId,
        outputSlot: undefined
      });
    });

    const newItem = createImageGroupItemFromNode(imageNode, groupNode.items.length);
    const requestedIndex = Number(options.insertIndex);
    const insertIndex = Number.isFinite(requestedIndex)
      ? clamp(Math.round(requestedIndex), 0, groupNode.items.length)
      : groupNode.items.length;
    groupNode.items.splice(insertIndex, 0, newItem);
    normalizeImageGroupNodeState(groupNode);
    if (Number.isFinite(Number(options.positionWorld?.x))) {
      groupNode.x = Number(options.positionWorld.x);
    } else if (options.preserveLeft) {
      groupNode.x = oldX;
    } else {
      groupNode.x = oldCenterX - groupNode.width / 2;
    }
    if (Number.isFinite(Number(options.positionWorld?.y))) groupNode.y = Number(options.positionWorld.y);
    groupNode.originX += groupNode.x - oldX;
    DesktopState.state.canvas.edges = nextEdges;
    discardFloatingSwellState(getNodeElement(imageNodeId));
    getNodeElement(imageNodeId)?.remove();
    delete DesktopState.state.canvas.nodes[imageNodeId];
    delete DesktopState.state.outputs[imageNodeId];
    refreshImageGroupNode(groupId);
    applyNodeLayout(groupId);
    migrateImageReferenceTokensToGroup(groupId, [imageNodeId]);
    refreshImageReferenceTokens(groupId);
    setSelectedNodes([groupId], false);
    updateLinkPath();
    DesktopState.saveSettings({ criticalCanvas: true });
    if (!options.skipTransition) requestAnimationFrame(() => animateImagesIntoGroup(resolvedTransitionSources, groupId));
    if (!options.quiet) {
      DesktopResults.showTransientMessage(`已加入图片组，当前共 ${groupNode.items.length} 张。`);
    }
    return groupId;
  }

    function imageNodeStateFromGroupItem(item, groupNode, index) {
    const requestedId = String(item.sourceNodeId || '');
    const id = requestedId && !DesktopState.state.canvas.nodes[requestedId] ? requestedId : nextNodeId('image');
    const deltaX = groupNode.x - groupNode.originX;
    const deltaY = groupNode.y - groupNode.originY;
    return {
      id,
      type: 'image',
      x: item.originalX + deltaX,
      y: item.originalY + deltaY,
      width: item.originalWidth,
      height: item.originalHeight,
      aspectRatio: item.aspectRatio,
      imageData: item.imageData || '',
      imageUrl: item.imageUrl || '',
      imageName: item.imageName || `图片${index + 1}`,
      mimeType: item.mimeType || 'image/png',
      sourceAssetId: item.sourceAssetId || '',
      sourceTitle: item.sourceTitle || '',
      sourcePrompt: item.sourcePrompt || '',
      sourceFile: item.sourceFile || '',
      sourceTaskId: item.sourceTaskId || '',
      sourceProvider: item.sourceProvider || '',
      sourceKind: item.sourceKind || 'image-group',
      editState: item.editState
    };
  }

    function ungroupImageGroup(groupId) {
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    if (!groupNode || groupNode.type !== 'image_group') return [];
    normalizeImageGroupNodeState(groupNode);
    const groupElement = getNodeElement(groupId);
    const transitionSources = groupNode.items.map(item => {
      const rect = groupElement?.querySelector(`[data-image-group-item="${CSS.escape(item.itemId)}"] .desk-image-group__thumb`)?.getBoundingClientRect?.();
      return rect ? { sourceNodeId: item.sourceNodeId, source: imageGroupItemSource(item), rect } : null;
    }).filter(Boolean);
    freezeImageReferenceTokens(groupId);

    const restoredNodes = groupNode.items.map((item, index) => imageNodeStateFromGroupItem(item, groupNode, index));
    const restoredIdBySource = new Map(groupNode.items.map((item, index) => [item.sourceNodeId, restoredNodes[index].id]));
    const currentGroupEdges = (DesktopState.state.canvas.edges || []).filter(edge => edge.from === groupId || edge.to === groupId);
    const nextEdges = (DesktopState.state.canvas.edges || []).filter(edge => edge.from !== groupId && edge.to !== groupId);
    const edgeKeys = new Set(nextEdges.map(edge => `${edge.from}->${edge.to}:${edge.inputRole || ''}`));
    const pushEdge = edge => {
      if (!edge.from || !edge.to || !DesktopState.state.canvas.nodes[edge.from] && !restoredNodes.some(node => node.id === edge.from)) return;
      if (!DesktopState.state.canvas.nodes[edge.to] && !restoredNodes.some(node => node.id === edge.to)) return;
      const key = `${edge.from}->${edge.to}:${edge.inputRole || ''}`;
      if (edgeKeys.has(key)) return;
      edgeKeys.add(key);
      nextEdges.push({ ...edge, id: nextCanvasEdgeId(edge.from, edge.to) });
    };

    delete DesktopState.state.canvas.nodes[groupId];
    restoredNodes.forEach(node => { DesktopState.state.canvas.nodes[node.id] = node; });
    currentGroupEdges.filter(edge => edge.from === groupId).forEach(edge => {
      restoredNodes.forEach(node => pushEdge({ ...edge, from: node.id, to: edge.to, outputSlot: undefined }));
    });
    (groupNode.memberEdges || []).forEach(edge => {
      const originalFromWasMember = restoredIdBySource.has(edge.from);
      const originalToWasMember = restoredIdBySource.has(edge.to);
      if (originalFromWasMember && ['input', 'comfy'].includes(DesktopState.state.canvas.nodes[edge.to]?.type)) return;
      if (!originalFromWasMember && !originalToWasMember) return;
      pushEdge({
        ...edge,
        from: restoredIdBySource.get(edge.from) || edge.from,
        to: restoredIdBySource.get(edge.to) || edge.to
      });
    });
    DesktopState.state.canvas.edges = nextEdges;
    discardFloatingSwellState(groupElement);
    groupElement?.remove();
    ensureGraphDom();
    restoredNodes.forEach(node => applyNodeLayout(node.id));
    setSelectedNodes(restoredNodes.map(node => node.id), false);
    updateLinkPath();
    DesktopState.saveSettings({ criticalCanvas: true });
    requestAnimationFrame(() => animateImagesOutOfGroup(transitionSources, restoredNodes));
    DesktopResults.showTransientMessage(`已解除图片组，恢复 ${restoredNodes.length} 个图片节点。`);
    return restoredNodes.map(node => node.id);
  }

    function reorderImageGroupItemToIndex(groupId, itemId, targetIndex, before = null) {
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    if (!groupNode || groupNode.type !== 'image_group') return false;
    const fromIndex = groupNode.items.findIndex(item => item.itemId === itemId);
    if (fromIndex < 0) return false;
    const nextIndex = clamp(Math.round(Number(targetIndex) || 0), 0, groupNode.items.length - 1);
    if (fromIndex === nextIndex) return false;
    const previousRects = before instanceof Map ? before : captureImageGroupItemRects(groupId);
    const [item] = groupNode.items.splice(fromIndex, 1);
    groupNode.items.splice(nextIndex, 0, item);
    refreshImageGroupNode(groupId);
    refreshImageReferenceTokens(groupId);
    requestAnimationFrame(() => animateImageGroupItemFlip(groupId, previousRects));
    DesktopState.saveSettings({ criticalCanvas: true });
    return true;
  }

    function reorderImageGroupItem(groupId, itemId, targetItemId, placeAfter = false) {
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    if (!groupNode || groupNode.type !== 'image_group' || itemId === targetItemId) return false;
    const remaining = groupNode.items.filter(item => item.itemId !== itemId);
    let targetIndex = remaining.findIndex(item => item.itemId === targetItemId);
    if (targetIndex < 0) return false;
    if (placeAfter) targetIndex += 1;
    return reorderImageGroupItemToIndex(groupId, itemId, targetIndex);
  }

    function imageGroupGooeyFilterPrimitivesHtml() {
    return `
      <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur"></feGaussianBlur>
      <feColorMatrix in="blur" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -7" result="goo"></feColorMatrix>
      <feComposite in="SourceGraphic" in2="goo" operator="atop" result="shape"></feComposite>
      <feColorMatrix in="shape" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 60 -29.5" result="bin"></feColorMatrix>
      <feMorphology in="bin" operator="dilate" radius="1" result="edge-spread"></feMorphology>
      <feFlood flood-color="rgba(0, 0, 0, 0.08)" result="edge-color"></feFlood>
      <feComposite in="edge-color" in2="edge-spread" operator="in" result="edge"></feComposite>
      <feMerge><feMergeNode in="edge"></feMergeNode><feMergeNode in="shape"></feMergeNode></feMerge>`;
  }

    function imageGroupItemSource(item) {
    return item?.imageData || item?.imageUrl || '';
  }

    function normalizeImageGroupItem(item = {}, index = 0) {
    const clean = jsonClone(item, {});
    const sourceNodeId = String(clean.sourceNodeId || clean.source_node_id || clean.nodeId || '').trim();
    const dataUrl = dataUrlValue(clean.imageData) || dataUrlValue(clean.base64) || dataUrlValue(clean.imageUrl);
    const rawImageUrl = String(clean.imageUrl || clean.url || '').trim();
    const imageUrl = rawImageUrl.startsWith('data:') ? '' : rawImageUrl;
    return {
      itemId: String(clean.itemId || clean.item_id || createImageGroupItemId()),
      sourceNodeId,
      role: normalizeImageGroupRole(clean.role, index === 0 ? 'subject' : 'reference'),
      imageData: dataUrl || '',
      imageUrl,
      imageName: String(clean.imageName || clean.name || clean.title || `图片${index + 1}`),
      mimeType: String(clean.mimeType || clean.type || (dataUrl ? dataUrl.slice(5, dataUrl.indexOf(';')) : 'image/png') || 'image/png'),
      sourceAssetId: String(clean.sourceAssetId || clean.assetId || clean.asset_id || ''),
      sourceTitle: String(clean.sourceTitle || clean.title || ''),
      sourcePrompt: String(clean.sourcePrompt || clean.prompt || ''),
      sourceFile: String(clean.sourceFile || clean.file || ''),
      sourceTaskId: String(clean.sourceTaskId || clean.taskId || clean.task_id || ''),
      sourceProvider: String(clean.sourceProvider || clean.provider || ''),
      sourceKind: String(clean.sourceKind || clean.source || 'image-group'),
      aspectRatio: Number(clean.aspectRatio) > 0 ? Number(clean.aspectRatio) : DEFAULT_IMAGE_NODE_WIDTH / DEFAULT_IMAGE_NODE_HEIGHT,
      originalX: Number.isFinite(Number(clean.originalX)) ? Number(clean.originalX) : 0,
      originalY: Number.isFinite(Number(clean.originalY)) ? Number(clean.originalY) : 0,
      originalWidth: Number.isFinite(Number(clean.originalWidth)) ? Number(clean.originalWidth) : DEFAULT_IMAGE_NODE_WIDTH,
      originalHeight: Number.isFinite(Number(clean.originalHeight)) ? Number(clean.originalHeight) : DEFAULT_IMAGE_NODE_HEIGHT,
      editState: clean.editState && typeof clean.editState === 'object' ? clean.editState : undefined
    };
  }

    function normalizeImageGroupNodeState(node = {}) {
    const seen = new Set();
    node.items = (Array.isArray(node.items) ? node.items : [])
      .map(normalizeImageGroupItem)
      .filter(item => {
        if (!imageGroupItemSource(item) || seen.has(item.itemId)) return false;
        seen.add(item.itemId);
        return true;
      })
      .slice(0, IMAGE_GROUP_MAX_ITEMS);
    node.title = String(node.title || '图片组').slice(0, 32);
    node.width = compactImageGroupNodeWidth(node.items.length);
    node.height = imageGroupNodeHeight(node.items.length);
    node.imageGroupLayoutVersion = IMAGE_GROUP_LAYOUT_VERSION;
    node.originX = Number.isFinite(Number(node.originX)) ? Number(node.originX) : Number(node.x || 0);
    node.originY = Number.isFinite(Number(node.originY)) ? Number(node.originY) : Number(node.y || 0);
    node.memberEdges = Array.isArray(node.memberEdges) ? node.memberEdges.map(edge => ({ ...edge })) : [];
    return node;
  }

    function createImageGroupItemFromNode(node, index = 0) {
    return normalizeImageGroupItem({
      itemId: createImageGroupItemId(),
      sourceNodeId: node.id,
      role: index === 0 ? 'subject' : 'reference',
      imageData: node.imageData || '',
      imageUrl: node.imageUrl || '',
      imageName: node.imageName || `图片${index + 1}`,
      mimeType: node.mimeType || 'image/png',
      sourceAssetId: node.sourceAssetId || '',
      sourceTitle: node.sourceTitle || '',
      sourcePrompt: node.sourcePrompt || '',
      sourceFile: node.sourceFile || '',
      sourceTaskId: node.sourceTaskId || '',
      sourceProvider: node.sourceProvider || '',
      sourceKind: node.sourceKind || 'image-node',
      aspectRatio: node.aspectRatio,
      originalX: node.x,
      originalY: node.y,
      originalWidth: node.width,
      originalHeight: node.height,
      editState: node.editState
    }, index);
  }

    function normalizeImageSourceFromGroupItem(item, groupNode, index = 0) {
    const source = imageGroupItemSource(item);
    if (!source) return null;
    return {
      id: item.sourceAssetId || `image-group:${groupNode.id}:${item.itemId}`,
      assetId: item.sourceAssetId || '',
      sourceNodeId: item.sourceNodeId || groupNode.id,
      imageGroupId: groupNode.id,
      imageGroupItemId: item.itemId,
      imageNumber: index + 1,
      imageRole: normalizeImageGroupRole(item.role),
      name: item.imageName || `图片${index + 1}.png`,
      title: item.sourceTitle || item.imageName || `图片${index + 1}`,
      prompt: item.sourcePrompt || '',
      file: item.sourceFile || '',
      taskId: item.sourceTaskId || '',
      provider: item.sourceProvider || '',
      type: item.mimeType || 'image/png',
      url: item.imageUrl || source,
      base64: item.imageData || '',
      imageData: item.imageData || '',
      imageUrl: item.imageUrl || '',
      source: item.sourceKind || 'image-group'
    };
  }

    function imageGroupRoleOptionsHtml(selected) {
    const normalized = normalizeImageGroupRole(selected);
    return IMAGE_GROUP_ROLES.map(item => (
      `<option value="${item.value}"${item.value === normalized ? ' selected' : ''}>${item.label}</option>`
    )).join('');
  }

    function imageGroupItemHtml(groupNode, item, index) {
    const source = escapeHtml(imageGroupItemSource(item));
    const label = `图片${index + 1}`;
    return `
      <article class="desk-image-group__item" tabindex="0" data-node-drag-ignore data-image-group-item="${escapeHtml(item.itemId)}" aria-label="${label}：${escapeHtml(item.imageName || '')}">
        <div class="desk-image-group__thumb" data-image-group-sort-handle title="拖拽调整图片顺序">
          <img src="${source}" alt="${escapeHtml(item.imageName || label)}" draggable="false">
          <strong aria-label="${label}">${index + 1}</strong>
        </div>
        <div class="desk-image-group__item-actions">
          <select data-image-group-role aria-label="${label}的参考用途">${imageGroupRoleOptionsHtml(item.role)}</select>
          <button type="button" class="desk-key" data-image-group-insert-reference title="插入提示词引用" aria-label="将${label}插入提示词">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"></path><path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"></path></svg>
          </button>
        </div>
      </article>`;
  }

    function imageGroupItemsHtml(groupNode) {
    return groupNode.items.map((item, index) => imageGroupItemHtml(groupNode, item, index)).join('');
  }

    function imageGroupGooeyBlobsHtml(groupNode) {
    const shellInset = (IMAGE_GROUP_LIQUID_SHELL_PX - IMAGE_GROUP_THUMB_PX) / 2;
    return groupNode.items.map((item, index) => {
      const position = imageGroupThumbPosition(index);
      return `<rect class="desk-image-group__liquid-item" data-image-group-goo-item="${escapeHtml(item.itemId)}" x="${position.left - shellInset}" y="${position.top - shellInset}" width="${IMAGE_GROUP_LIQUID_SHELL_PX}" height="${IMAGE_GROUP_LIQUID_SHELL_PX}" rx="${IMAGE_GROUP_LIQUID_SHELL_PX / 2}"></rect>`;
    }).join('');
  }

    function imageGroupNodeHtml(node) {
    normalizeImageGroupNodeState(node);
    const filterId = `desk-image-group-gooey-${node.id}`;
    const filterWidth = node.width + IMAGE_GROUP_FILTER_OUTSET_PX * 2;
    const filterHeight = node.height + IMAGE_GROUP_FILTER_OUTSET_PX * 2;
    const motherHeight = imageGroupMotherHeight(node.items.length);
    const columns = imageGroupColumnCount(node.items.length);
    return `
      <section class="desk-node desk-node--image-group" data-node-id="${node.id}" aria-label="图片组，${node.items.length} 张图片" style="--desk-image-group-mother-radius:${IMAGE_GROUP_MOTHER_RADIUS_PX}px;--desk-image-group-columns:${columns}">
        <svg class="desk-image-group__silhouette" data-image-group-silhouette aria-hidden="true" viewBox="0 0 ${node.width} ${node.height}" preserveAspectRatio="none">
          <defs>
            <filter id="${escapeHtml(filterId)}" data-image-group-filter filterUnits="userSpaceOnUse" x="-${IMAGE_GROUP_FILTER_OUTSET_PX}" y="-${IMAGE_GROUP_FILTER_OUTSET_PX}" width="${filterWidth}" height="${filterHeight}" color-interpolation-filters="sRGB">${imageGroupGooeyFilterPrimitivesHtml()}</filter>
          </defs>
          <g class="desk-image-group__liquid" filter="url(#${escapeHtml(filterId)})" data-image-group-goo>
            <rect class="desk-image-group__liquid-base" data-image-group-liquid-base x="0" y="${IMAGE_GROUP_MOTHER_TOP_PX}" width="${node.width}" height="${motherHeight}" rx="${IMAGE_GROUP_MOTHER_RADIUS_PX}"></rect>
            ${imageGroupGooeyBlobsHtml(node)}
          </g>
        </svg>
        <div class="desk-image-group__mother desk-image-group__body" data-node-drag-handle>
          <div class="desk-image-group__identity" aria-hidden="true">
            <strong>图片组</strong>
            <span data-image-group-count>${node.items.length} 张</span>
          </div>
          <div class="desk-image-group__items" data-image-group-items>${imageGroupItemsHtml(node)}</div>
        </div>
        <div class="desk-image-group__node-actions" data-node-drag-ignore aria-label="图片组操作">
          <button type="button" class="desk-key" data-image-group-ungroup title="解除图片组" aria-label="解除图片组">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="8" height="8" rx="2"></rect><rect x="13" y="11" width="8" height="8" rx="2"></rect><path d="m10 15-2 2 2 2M14 9l2-2-2-2"></path></svg>
          </button>
          <button type="button" class="desk-node-delete" data-node-delete title="删除图片组" aria-label="删除图片组">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg>
          </button>
        </div>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="按图片编号连接到模型节点" aria-label="连接图片组输出"></button>
      </section>`;
  }

    function refreshImageGroupNode(groupId) {
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    const element = getNodeElement(groupId);
    if (!groupNode || groupNode.type !== 'image_group' || !element) return;
    normalizeImageGroupNodeState(groupNode);
    const items = element.querySelector('[data-image-group-items]');
    const goo = element.querySelector('[data-image-group-goo]');
    const count = element.querySelector('[data-image-group-count]');
    const silhouette = element.querySelector('[data-image-group-silhouette]');
    const filter = element.querySelector('[data-image-group-filter]');
    const motherHeight = imageGroupMotherHeight(groupNode.items.length);
    if (items) items.innerHTML = imageGroupItemsHtml(groupNode);
    if (goo) {
      goo.innerHTML = `<rect class="desk-image-group__liquid-base" data-image-group-liquid-base x="0" y="${IMAGE_GROUP_MOTHER_TOP_PX}" width="${groupNode.width}" height="${motherHeight}" rx="${IMAGE_GROUP_MOTHER_RADIUS_PX}"></rect>${imageGroupGooeyBlobsHtml(groupNode)}`;
    }
    if (count) count.textContent = `${groupNode.items.length} 张`;
    silhouette?.setAttribute('viewBox', `0 0 ${groupNode.width} ${groupNode.height}`);
    filter?.setAttribute('width', String(groupNode.width + IMAGE_GROUP_FILTER_OUTSET_PX * 2));
    filter?.setAttribute('height', String(groupNode.height + IMAGE_GROUP_FILTER_OUTSET_PX * 2));
    element.querySelector('[data-image-group-liquid-base]')?.setAttribute('width', String(groupNode.width));
    element.querySelector('[data-image-group-liquid-base]')?.setAttribute('height', String(motherHeight));
    element.style.setProperty('--desk-image-group-mother-radius', `${IMAGE_GROUP_MOTHER_RADIUS_PX}px`);
    element.style.setProperty('--desk-image-group-columns', String(imageGroupColumnCount(groupNode.items.length)));
    element.setAttribute('aria-label', `图片组，${groupNode.items.length} 张图片`);
    ensureNodeEdgeHandles(element);
    updateLinkPath();
  }

    function imageGroupRoleEntriesForTarget(targetNodeId) {
    return getConnectedImageReferences(targetNodeId)
      .map((reference, index) => ({ reference, imageNumber: index + 1 }))
      .filter(entry => entry.reference.imageGroupId && entry.reference.imageGroupItemId)
      .map(entry => ({
        targetNodeId,
        groupId: entry.reference.imageGroupId,
        itemId: entry.reference.imageGroupItemId,
        sourceNodeId: entry.reference.sourceNodeId || '',
        imageNumber: entry.imageNumber,
        role: normalizeImageGroupRole(entry.reference.imageRole),
        roleLabel: imageGroupRoleLabel(entry.reference.imageRole),
        instruction: imageGroupRoleInstruction(entry.reference.imageRole),
        name: entry.reference.name || entry.reference.title || `图片${entry.imageNumber}`
      }));
  }

    function imageGroupRolePromptBlock(targetNodeId) {
    const entries = imageGroupRoleEntriesForTarget(targetNodeId);
    if (!entries.length) return '';
    return [
      '【图片参考关系】',
      ...entries.map(entry => `图片${entry.imageNumber}：${entry.roleLabel}。${entry.instruction}`),
      IMAGE_GROUP_ROLE_PRIORITY_NOTE
    ].join('\n');
  }

    return Object.freeze({
      createImageGroupItemId,
      normalizeImageGroupRole,
      imageGroupRoleLabel,
      imageGroupRoleInstruction,
      getImageGroupItem,
      imageGroupColumnCount,
      imageGroupRowCount,
      naturalImageGroupNodeWidth,
      compactImageGroupNodeWidth,
      imageGroupMotherHeight,
      imageGroupNodeHeight,
      imageGroupThumbPosition,
      sortImageNodesForGroup,
      imageNodesForGroupSelection,
      nextCanvasEdgeId,
      createImageGroupFromNodes,
      createImageGroupFromSelection,
      appendImageNodeToGroup,
      imageNodeStateFromGroupItem,
      ungroupImageGroup,
      reorderImageGroupItemToIndex,
      reorderImageGroupItem,
      imageGroupGooeyFilterPrimitivesHtml,
      imageGroupItemSource,
      normalizeImageGroupItem,
      normalizeImageGroupNodeState,
      createImageGroupItemFromNode,
      normalizeImageSourceFromGroupItem,
      imageGroupRoleOptionsHtml,
      imageGroupItemHtml,
      imageGroupItemsHtml,
      imageGroupGooeyBlobsHtml,
      imageGroupNodeHtml,
      refreshImageGroupNode,
      imageGroupRoleEntriesForTarget,
      imageGroupRolePromptBlock,
    });
  }

  window.DesktopCanvasImageGroupModel = Object.freeze({ create });
})();
