// Node lifecycle, palette and non-model node presentation. Host retains shared event dispatch and graph render scheduling.
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  // Sidebar presentation only: the shared catalog and connection picker stay flat.
  const NODE_PALETTE_GROUPS = [
    { id: 'image', title: '图像节点', types: ['image', 'input', 'krea2', 'qwen21', 'cyimg_image', 'pose'] },
    { id: 'video', title: '视频节点', types: ['video', 'video_inference', 'cyimg_video', 'video_control'] },
    { id: 'audio', title: '音频节点', types: ['audio', 'music_generate', 'music_transcribe', 'music_abc', 'music_score', 'music_compare'] },
    { id: 'enhance', title: '增强放大节点', types: ['upscale', 'topaz', 'topaz_video'] },
    { id: 'general', title: '通用节点', types: ['text', 'comfy', 'file_output', 'layout'] }
  ];

  function create({
    DEFAULT_COMFY_NODE_HEIGHT,
    DEFAULT_COMFY_NODE_WIDTH,
    DEFAULT_COMFY_PIXEL_HEIGHT,
    DEFAULT_COMFY_PIXEL_WIDTH,
    DEFAULT_FILE_OUTPUT_NODE_HEIGHT,
    DEFAULT_FILE_OUTPUT_NODE_WIDTH,
    DEFAULT_IMAGE_GROUP_NODE_HEIGHT,
    DEFAULT_IMAGE_GROUP_NODE_WIDTH,
    DEFAULT_IMAGE_NODE_HEIGHT,
    DEFAULT_IMAGE_NODE_WIDTH,
    DEFAULT_INPUT_NODE_HEIGHT,
    DEFAULT_INPUT_NODE_WIDTH,
    DEFAULT_TEXT_NODE_HEIGHT,
    DEFAULT_TEXT_NODE_WIDTH,
    DEFAULT_UPSCALE_NODE_HEIGHT,
    DEFAULT_UPSCALE_NODE_WIDTH,
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    DEFAULT_VIDEO_NODE_HEIGHT,
    DEFAULT_VIDEO_NODE_WIDTH,
    IMAGE_GROUP_LAYOUT_VERSION,
    LOCKED_INPUT_NODE_HEIGHT,
    LOCKED_INPUT_NODE_WIDTH,
    NODE_MENU_ITEMS,
    ORDINARY_MENU_CLOSE_FALLBACK_MS,
    progressView,
    applyAllNodeLayouts,
    audioNode,
    audioNodeDefinition,
    musicNode,
    musicNodeDefinition,
    topazNode,
    topazDefinition,
    cyimgNode,
    cyimgDefinition,
    krea2Node,
    krea2Definition,
    qwen21Node,
    qwen21Definition,
    videoControlNode,
    videoControlDefinition,
    topazVideoNode,
    topazVideoDefinition,
    clearPromptDocumentHistory,
    comfyNodeHtml,
    comfyWorkflowCatalogRef,
    comfyWorkflowDefaultSize,
    connectNodes,
    createTextPromptDocument,
    discardFloatingSwellState,
    els,
    ensureNodeEdgeHandles,
    escapeHtml,
    fileOutputNodeHtml,
    findDefaultInputNodeId,
    focusCanvasViewport,
    freezeImageReferenceTokens,
    freezeImageReferenceTokensForSourceNode,
    getConnectedTextNodes,
    getNodeElement,
    getNodeReferenceStore,
    getNodeState,
    getSelectedNodeIds,
    getViewportCenterWorldPoint,
    imageGroupNodeHtml,
    inputNodeHtml,
    materializeTextNode,
    nextTextNodeAlias,
    nodePaletteCloseTimerRef,
    normalizeComfyPixelSize,
    normalizeImageSourceFromNode,
    normalizeNodeGroupId,
    normalizeNodeGroups,
    normalizeVideoInferenceNodeState,
    notifyTextNodeListChange,
    refreshImageReferenceTokens,
    refreshVideoInferenceNode,
    refreshVideoNode,
    renderMiniMap,
    revokeReferenceUrl,
    scheduleCanvasGraphRender,
    selectNode,
    setPromptTextForInputNode,
    setSelectedNodes,
    setTextStyleMenuOpen,
    stopVideoTaskPolling,
    syncOutputControlsToNodes,
    textNodeHtml,
    triggerImageNodePopIn,
    updateInputProgressOverlay,
    updateLinkPath,
    updateSelectionToolbar,
    updateUpscaleInputCount,
    upscaleNodeHtml,
    videoInferenceNodeHtml,
    videoNodeHtml,
  }) {


    function applyNodeLayout(nodeId, options = {}) {
    const node = getNodeElement(nodeId);
    const nodeState = getNodeState(nodeId);
    if (!node || !nodeState) return;
    if (nodeState.type === 'input') {
      nodeState.width = LOCKED_INPUT_NODE_WIDTH;
      nodeState.height = LOCKED_INPUT_NODE_HEIGHT;
    }
    if (nodeState.type === 'audio') {
      nodeState.width = audioNodeDefinition.WIDTH;
      nodeState.height = audioNodeDefinition.HEIGHT;
    }
    if (nodeState.type === topazDefinition?.TYPE) topazDefinition.normalize(nodeState);
    if (cyimgDefinition?.TYPES.includes(nodeState.type)) cyimgDefinition.normalize(nodeState);
    if (nodeState.type === krea2Definition?.TYPE) krea2Definition.normalize(nodeState);
    if (nodeState.type === qwen21Definition?.TYPE) qwen21Definition.normalize(nodeState);
    if (nodeState.type === videoControlDefinition?.TYPE) videoControlDefinition.normalize(nodeState);
    if (nodeState.type === topazVideoDefinition?.TYPE) topazVideoDefinition.normalize(nodeState);
    if (musicNodeDefinition?.TYPES.includes(nodeState.type)) musicNodeDefinition.normalizeState(nodeState);
    if (nodeState.type === 'file_output') {
      nodeState.width = DEFAULT_FILE_OUTPUT_NODE_WIDTH;
      nodeState.height = DEFAULT_FILE_OUTPUT_NODE_HEIGHT;
    }
    if (nodeState.type === 'upscale') {
      nodeState.width = DEFAULT_UPSCALE_NODE_WIDTH;
      nodeState.height = DEFAULT_UPSCALE_NODE_HEIGHT;
    }
    node.style.left = `${nodeState.x}px`;
    node.style.top = `${nodeState.y}px`;
    node.style.width = `${nodeState.width}px`;
    node.style.height = `${nodeState.height}px`;
    if (options.deferGraph) {
      scheduleCanvasGraphRender();
      return;
    }
    renderMiniMap();
    updateSelectionToolbar();
    if (nodeState.type === 'input') updateInputProgressOverlay();
  }

    function ensureDefaultModelOutputState() {
    if (!DesktopState.state.outputs || typeof DesktopState.state.outputs !== 'object') {
      DesktopState.state.outputs = {};
    }
    if (!DesktopState.state.outputs.input) {
      DesktopState.state.outputs.input = {
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
        taskId: '',
        fileManifest: null,
        selectedFiles: [],
        selectionInitialized: false
      };
    }
  }

    function migrateResultNodesToModelOutputs() {
    ensureDefaultModelOutputState();
    const nodes = DesktopState.state.canvas.nodes || {};
    const edges = Array.isArray(DesktopState.state.canvas.edges) ? DesktopState.state.canvas.edges : [];
    const outputIds = Object.values(nodes)
      .filter(node => node?.type === 'output')
      .map(node => node.id);
    if (!outputIds.length && !nodes.output) return false;

    const outputSet = new Set(outputIds);
    let changed = false;
    const nextEdges = [];
    const existingPairs = new Set();
    edges.forEach(edge => {
      const from = nodes[edge.from];
      const to = nodes[edge.to];
      if (from?.type === 'input' && outputSet.has(edge.to)) {
        changed = true;
        return;
      }
      if (outputSet.has(edge.from) && to?.type === 'image') {
        const sourceInput = edges.find(item => item.to === edge.from && nodes[item.from]?.type === 'input')?.from || 'input';
        if (nodes[sourceInput]?.type === 'input') {
          const key = `${sourceInput}->${edge.to}`;
          if (!existingPairs.has(key)) {
            nextEdges.push({
              id: `${sourceInput}_${edge.to}_${Date.now()}_${nextEdges.length}`,
              from: sourceInput,
              to: edge.to,
              outputSlot: edge.outputSlot
            });
            existingPairs.add(key);
          }
        }
        changed = true;
        return;
      }
      if (outputSet.has(edge.from) || outputSet.has(edge.to)) {
        changed = true;
        return;
      }
      const key = `${edge.from}->${edge.to}`;
      if (!existingPairs.has(key)) {
        nextEdges.push(edge);
        existingPairs.add(key);
      }
    });

    outputIds.forEach(outputId => {
      const outputState = DesktopState.state.outputs?.[outputId];
      if (outputState && outputId === 'output') {
        DesktopState.state.outputs.input = {
          ...DesktopState.state.outputs.input,
          ...outputState
        };
      }
      delete nodes[outputId];
      delete DesktopState.state.outputs[outputId];
      changed = true;
    });

    DesktopState.state.canvas.edges = nextEdges;
    if (DesktopState.state.canvas.selectedNodeId && !nodes[DesktopState.state.canvas.selectedNodeId]) {
      DesktopState.state.canvas.selectedNodeId = '';
      DesktopState.state.canvas.selectedNodeIds = [];
    }
    if (changed) DesktopState.saveSettings();
    return changed;
  }

    function migrateLegacyPromptDraftToTextNode() {
    const prompt = String(DesktopState.state.prompt || '').trim();
    if (!prompt || !DesktopState.state.canvas.nodes.input) return false;
    const hasPromptTextNode = getConnectedTextNodes('input')
      .some(node => materializeTextNode(node).trim() === prompt);
    if (!hasPromptTextNode) {
      setPromptTextForInputNode('input', prompt, { quiet: true });
    }
    DesktopState.state.prompt = '';
    DesktopState.saveDraft();
    DesktopState.saveSettings();
    return true;
  }

    function setNodePaletteOpen(open) {
    const palette = els.deskNodePalette;
    if (palette && open) {
      if (nodePaletteCloseTimerRef.current) {
        window.clearTimeout(nodePaletteCloseTimerRef.current);
        nodePaletteCloseTimerRef.current = 0;
      }
      if (!palette.classList.contains('is-open')) {
        palette.classList.add('is-closing');
        void palette.offsetWidth;
        palette.classList.remove('is-closing');
        palette.classList.add('is-open');
      }
    } else if (palette?.classList.contains('is-open')) {
      if (palette.contains(document.activeElement)) els.deskNodeToolBtn?.focus();
      palette.classList.remove('is-open');
      palette.classList.add('is-closing');
      if (nodePaletteCloseTimerRef.current) window.clearTimeout(nodePaletteCloseTimerRef.current);
      nodePaletteCloseTimerRef.current = window.setTimeout(() => {
        nodePaletteCloseTimerRef.current = 0;
        if (!palette.classList.contains('is-open')) palette.classList.remove('is-closing');
      }, ORDINARY_MENU_CLOSE_FALLBACK_MS);
    }
    els.deskNodeToolBtn?.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

    function nodeMenuButtonHtml(item) {
    const searchValue = `${item.title || ''} ${item.subtitle || ''} ${item.type || ''}`.toLowerCase();
    return `
      <button type="button" data-add-node="${escapeHtml(item.type)}" data-node-menu-search="${escapeHtml(searchValue)}">
        <span class="desk-node-palette__icon" aria-hidden="true">${item.icon}</span>
        <span class="desk-node-palette__copy">
          <strong title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</strong>
          <em title="${escapeHtml(item.subtitle)}">${escapeHtml(item.subtitle)}</em>
        </span>
      </button>
    `;
  }

    function renderNodePaletteItems() {
    const palette = els.deskNodePalette;
    if (!palette) return;
    const previousGroups = [...palette.querySelectorAll('[data-node-menu-group]')];
    const openGroupId = previousGroups.find(group => group.open)?.dataset.nodeMenuGroup;
    const remaining = new Map(NODE_MENU_ITEMS.map(item => [item.type, item]));
    const groups = NODE_PALETTE_GROUPS.map(group => {
      const items = group.types.flatMap(type => {
        const item = remaining.get(type);
        remaining.delete(type);
        return item ? [item] : [];
      });
      return { ...group, items };
    });
    // New catalog entries must remain reachable before a category is assigned.
    groups.find(group => group.id === 'general').items.push(...remaining.values());
    palette.innerHTML = groups.filter(group => group.items.length).map((group, index) => {
      const open = previousGroups.length ? group.id === openGroupId : index === 0;
      return `
        <details class="desk-node-palette__group" data-node-menu-group="${group.id}" name="desk-node-palette-groups"${open ? ' open' : ''}>
          <summary class="desk-node-palette__category">
            <span class="desk-node-palette__category-title" data-i18n="nodePaletteGroup_${group.id}">${escapeHtml(group.title)}</span>
            <span class="desk-node-palette__count" aria-hidden="true">${group.items.length}</span>
            <svg class="desk-node-palette__chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"></path></svg>
          </summary>
          <div class="desk-node-palette__items">${group.items.map(nodeMenuButtonHtml).join('')}</div>
        </details>
      `;
    }).join('');
    palette.querySelectorAll('[data-add-node]').forEach(button => { button.draggable = true; });
  }

    function applyNodeSelection() {
    const selectedIds = getSelectedNodeIds();
    const selected = new Set(selectedIds);
    document.querySelectorAll('.desk-node[data-node-id]').forEach(node => {
      const isSelected = selected.has(node.dataset.nodeId);
      const groupId = normalizeNodeGroupId(DesktopState.state.canvas.nodes[node.dataset.nodeId]?.groupId);
      node.classList.toggle('is-selected', isSelected);
      node.classList.toggle('is-grouped', Boolean(groupId));
      if (groupId) node.dataset.nodeGroupId = groupId;
      else delete node.dataset.nodeGroupId;
      if (!isSelected && node.classList.contains('desk-node--text')) {
        setTextStyleMenuOpen(node, false);
      }
      if (node.classList.contains('desk-node--input')) {
        const drawer = node.querySelector('.desk-node__drawer');
        if (drawer) drawer.style.display = 'grid';
      }
    });
    updateSelectionToolbar();
    requestAnimationFrame(updateLinkPath);
  }

    function nextNodeId(type) {
    const prefix = type === topazDefinition?.TYPE ? type : type === krea2Definition?.TYPE ? type : type === qwen21Definition?.TYPE ? type : cyimgDefinition?.TYPES.includes(type) ? type : type === videoControlDefinition?.TYPE ? type : type === topazVideoDefinition?.TYPE ? type : musicNodeDefinition?.TYPES.includes(type) ? type : type === 'audio' ? 'audio' : type === 'file_output'
      ? 'file_output'
      : (type === 'image_group'
        ? 'image_group'
      : (type === 'comfy'
        ? 'comfy'
        : (type === 'video_inference'
          ? 'video_inference'
          : (type === 'video'
            ? 'video'
            : (type === 'image' ? 'image' : (type === 'upscale' ? 'upscale' : (type === 'pose' ? 'pose' : (type === 'layout' ? 'layout' : (type === 'text' ? 'text' : 'input')))))))));
    let id = '';
    do {
      const unique = globalThis.crypto?.randomUUID?.()?.replaceAll('-', '')
        || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
      id = `${prefix}_${unique}`;
    } while (DesktopState.state.canvas.nodes[id]);
    return id;
  }

    function createNodeState(type) {
    type = normalizeNodeMenuType(type);
    const id = nextNodeId(type);
    const count = Object.keys(DesktopState.state.canvas.nodes).length;
    const defaultWidth = type === 'file_output'
      ? DEFAULT_FILE_OUTPUT_NODE_WIDTH
      : (type === 'image_group'
        ? DEFAULT_IMAGE_GROUP_NODE_WIDTH
      : (type === 'comfy'
        ? DEFAULT_COMFY_NODE_WIDTH
        : (type === 'video_inference'
          ? DEFAULT_VIDEO_INFERENCE_NODE_WIDTH
          : (type === 'video'
            ? DEFAULT_VIDEO_NODE_WIDTH
            : (type === 'upscale' ? DEFAULT_UPSCALE_NODE_WIDTH : (type === 'layout' ? 320 : (type === 'pose' ? 340 : (type === 'text' ? DEFAULT_TEXT_NODE_WIDTH : DEFAULT_INPUT_NODE_WIDTH))))))));
    const defaultHeight = type === 'file_output'
      ? DEFAULT_FILE_OUTPUT_NODE_HEIGHT
      : (type === 'image_group'
        ? DEFAULT_IMAGE_GROUP_NODE_HEIGHT
      : (type === 'comfy'
        ? DEFAULT_COMFY_NODE_HEIGHT
        : (type === 'video_inference'
          ? DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT
          : (type === 'video'
            ? DEFAULT_VIDEO_NODE_HEIGHT
            : (type === 'upscale' ? DEFAULT_UPSCALE_NODE_HEIGHT : (type === 'layout' ? 300 : (type === 'pose' ? 300 : (type === 'text' ? DEFAULT_TEXT_NODE_HEIGHT : DEFAULT_INPUT_NODE_HEIGHT))))))));
    const node = {
      id,
      type,
      x: type === 'file_output' ? 820 + count * 28 : 92 + count * 28,
      y: 92 + count * 24,
      width: defaultWidth,
      height: defaultHeight
    };
    if (type === topazDefinition?.TYPE) topazDefinition.normalize(node);
    if (cyimgDefinition?.TYPES.includes(type)) cyimgDefinition.normalize(node);
    if (type === krea2Definition?.TYPE) krea2Definition.normalize(node);
    if (type === qwen21Definition?.TYPE) qwen21Definition.normalize(node);
    if (type === videoControlDefinition?.TYPE) videoControlDefinition.normalize(node);
    if (type === topazVideoDefinition?.TYPE) topazVideoDefinition.normalize(node);
    if (type === 'audio') Object.assign(node, audioNodeDefinition.createState(id, { x: node.x, y: node.y }));
    if (musicNodeDefinition?.TYPES.includes(type)) Object.assign(node, musicNodeDefinition.createState(id, type, { x: node.x, y: node.y }));
    if (type === 'input') {
      node.width = LOCKED_INPUT_NODE_WIDTH;
      node.height = LOCKED_INPUT_NODE_HEIGHT;
    }
    if (type === 'comfy') {
      node.workflow = comfyWorkflowCatalogRef.current.default_workflow || comfyWorkflowCatalogRef.current.workflows?.[0] || '';
      const workflowMeta = comfyWorkflowCatalogRef.current.items?.find(item => item.id === node.workflow);
      const defaultSize = comfyWorkflowDefaultSize(workflowMeta);
      node.pixelWidth = defaultSize.width;
      node.pixelHeight = defaultSize.height;
      node.ratio = workflowMeta?.default_ratio || '1:1';
      node.resolution = '1k';
      node.workflowParameters = {};
      node.output = { archiveEnabled: true, telegramEnabled: true };
    }
    if (type === 'video_inference') {
      normalizeVideoInferenceNodeState(node);
      node.width = DEFAULT_VIDEO_INFERENCE_NODE_WIDTH;
      node.height = DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT;
      node.output = { archiveEnabled: true, telegramEnabled: false };
    }
    if (type === 'text') {
      node.text = '';
      node.promptDocument = createTextPromptDocument('');
      node.stylePresetId = '';
      node.alias = nextTextNodeAlias();
    }
    if (type === 'image') {
      node.width = DEFAULT_IMAGE_NODE_WIDTH;
      node.height = DEFAULT_IMAGE_NODE_HEIGHT;
      node.aspectRatio = DEFAULT_IMAGE_NODE_WIDTH / DEFAULT_IMAGE_NODE_HEIGHT;
      node.imageData = '';
      node.imageUrl = '';
      node.imageName = '空图片节点';
      node.mimeType = 'image/png';
    }
    if (type === 'image_group') {
      node.width = DEFAULT_IMAGE_GROUP_NODE_WIDTH;
      node.height = DEFAULT_IMAGE_GROUP_NODE_HEIGHT;
      node.imageGroupLayoutVersion = IMAGE_GROUP_LAYOUT_VERSION;
      node.title = '图片组';
      node.items = [];
      node.memberEdges = [];
      node.originX = node.x;
      node.originY = node.y;
    }
    if (type === 'video') {
      node.width = DEFAULT_VIDEO_NODE_WIDTH;
      node.height = DEFAULT_VIDEO_NODE_HEIGHT;
      node.mediaUrl = '';
      node.posterUrl = '';
      node.mediaName = '视频结果';
      node.mimeType = 'video/mp4';
      node.sourceTaskId = '';
      node.durationSeconds = 0;
      node.mediaWidth = 0;
      node.mediaHeight = 0;
      node.fps = 24;
      node.fileSize = 0;
      node.status = 'idle';
    }
    if (type === 'layout') {
      node.layoutTitle = '新排版画布';
      node.layoutPreview = '';
      node.layoutExport = '';
    }
    if (type === 'pose') {
      node.mode = 'director_stage';
      node.poseTitle = '姿态参考';
      node.poseData = {};
      node.legacyPoseData = {};
      node.directorData = createDefaultDirectorData();
      node.backgroundImage = null;
      node.backgroundName = '';
      node.backgroundSource = '';
      node.backgroundSourceNodeId = '';
      node.backgroundMeta = null;
      node.previewImage = '';
      node.exportImage = '';
      node.exportMode = 'mannequin_only';
      node.humanConfig = { skeletonVisible: true };
      node.camera = {};
      node.lights = [];
      node.status = 'idle';
      node.error = '';
    }
    if (type === 'upscale') {
      node.model = '4x-UltraSharp';
      node.tileSize = 256;
      node.tileOverlap = 32;
      node.device = 'auto';
      node.output = { archiveEnabled: true, telegramEnabled: false };
    }
    DesktopState.state.canvas.nodes[id] = node;
    if (type === topazDefinition?.TYPE || type === 'input' || type === 'comfy' || type === 'file_output' || type === 'upscale' || type === 'video_inference') {
      DesktopState.state.outputs[id] = {
        status: 'idle',
        stage: '',
        progressText: '',
        progress: 0,
        files: [],
        imagePaths: [],
        primaryFile: '',
        primaryImagePath: '',
        type: type === topazDefinition?.TYPE ? 'topaz' : type === 'upscale' ? 'upscale' : (type === 'comfy' ? 'comfy' : (type === 'video_inference' ? 'video' : 'gpt')),
        error: '',
        taskId: '',
        fileManifest: null,
        selectedFiles: [],
        selectionInitialized: false
      };
    }
    return node;
  }

    function createDefaultDirectorData() {
    const controls = {
      torsoTwist: 0,
      headYaw: 0,
      leftShoulderSide: 0,
      leftShoulderFront: 8,
      leftElbow: 6,
      rightShoulderSide: 8,
      rightShoulderFront: 0,
      rightElbow: 6,
      leftHipSide: 2,
      leftHipFront: 0,
      leftKnee: 0,
      rightHipSide: 2,
      rightHipFront: 0,
      rightKnee: 0
    };
    return {
      version: 5,
      characters: [
        {
          id: 'char_a',
          name: '角色A',
          modelKey: 'mixamo_xbot',
          bodyPreset: 'female_proxy',
          color: '#4F8EF7',
          position: [-0.7, 0, 0],
          rotation: [0, 0, 0],
          scale: 1,
          posePreset: 'stand',
          boneControls: { ...controls }
        },
        {
          id: 'char_b',
          name: '角色B',
          modelKey: 'mixamo_ybot',
          bodyPreset: 'male_proxy',
          color: '#F25F5C',
          position: [0.7, 0, 0],
          rotation: [0, 0, 0],
          scale: 1,
          posePreset: 'stand',
          boneControls: { ...controls }
        }
      ],
      props: [],
      cameras: [
        {
          id: 'camera_01',
          name: '机位1',
          position: [0, 2.1, 5.4],
          target: [0, 1.45, 0],
          fov: 45,
          aspect: '16:9',
          thumbnail: ''
        }
      ],
      activeCameraId: 'camera_01',
      selectedId: 'char_a',
      viewMode: 'director'
    };
  }

    function imageNodeSource(node) {
    return node?.imageData || node?.imageUrl || '';
  }

    function imageNodePlaceholderHtml() {
    return `
        <div class="desk-image-node__placeholder">
          <div class="desk-image-node__placeholder-copy">
            <strong>空图片节点</strong>
            <span>连接结果或上传图片</span>
          </div>
          <button type="button" class="desk-image-node__empty-upload" data-image-upload title="上传图片" aria-label="上传图片">
            <span aria-hidden="true">+</span>
          </button>
        </div>`;
  }

    function imageNodeToolsHtml(node) {
    if (!imageNodeSource(node)) return '';
    const hasMask = !!node.editState?.hasMask
      || !!node.editState?.maskData
      || !!node.editState?.maskOverlayData
      || !!node.editState?.projectJson?.hasMask;
    const hasPrompt = !!String(node.editState?.editPrompt || '').trim();
    return `
      <div class="desk-image-node__tools" aria-label="图片操作">
        <button type="button" data-image-edit title="编辑图片">编辑</button>
        ${hasMask ? '<button type="button" data-image-view-mask title="查看蒙版">蒙版</button>' : ''}
        ${hasPrompt ? '<button type="button" data-image-view-prompt title="查看说明">说明</button>' : ''}
      </div>`;
  }

    function imageNodeHtml(node) {
    const rawSrc = imageNodeSource(node);
    const src = escapeHtml(rawSrc);
    const name = escapeHtml(node.imageName || '图片节点');
    return `
      <section class="desk-node desk-node--image ${rawSrc ? 'has-image' : 'is-empty'}" data-node-id="${node.id}" data-node-drag-handle aria-label="图片节点">
        ${src ? `<img src="${src}" alt="${name}" draggable="false">` : imageNodePlaceholderHtml()}
        ${imageNodeToolsHtml(node)}
        <button type="button" class="desk-port desk-port--in desk-port--image-in" data-port="in" data-node-id="${node.id}" title="连接模型输出到这里" aria-label="连接图片输入"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接到可接入图片的节点" aria-label="连接图片输出"></button>
        <span class="desk-resize-handle" data-node-resize-handle title="按比例缩放图片" aria-hidden="true"></span>
      </section>
    `;
  }

    function layoutNodeHtml(node) {
    const preview = escapeHtml(node.layoutPreview || node.layoutExport || '');
    const inputCount = getLayoutInputCount(node.id);
    const presetLabel = escapeHtml(node.layoutPresetLabel || (node.layoutDraftId ? '已保存草稿' : '选择尺寸模板'));
    return `
      <section class="desk-node desk-node--layout desk-glass" data-node-id="${node.id}" aria-label="排版节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow">排版节点</p>
            <h2>图文版面</h2>
          </div>
          <div class="desk-node-tools">
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--layout-in" data-port="in" data-node-id="${node.id}" title="连接图片节点到排版" aria-label="连接图片输入"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接到可接入图片的节点" aria-label="连接排版输出"></button>
        <div class="desk-layout-node-preview" data-layout-preview>
          ${preview ? `<img src="${preview}" alt="排版预览">` : '<span>尚未排版</span>'}
        </div>
        <div class="desk-layout-node-actions">
          <button type="button" class="is-primary" data-layout-open>打开排版</button>
          <button type="button" data-layout-quick-export>更新预览</button>
        </div>
        <div class="desk-pill-row"><span>Fabric.js</span><span>${presetLabel}</span><span data-layout-input-count>${inputCount ? `已接入 ${inputCount} 张图` : '可接入图片'}</span></div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放节点" aria-hidden="true"></span>
      </section>
    `;
  }

    function getPoseInputImages(poseNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === poseNodeId)
      .map(edge => normalizeImageSourceFromNode(DesktopState.state.canvas.nodes[edge.from]))
      .filter(Boolean);
  }

    function poseStatusText(node, preview, backgroundCount) {
    if (node.error) return `错误：${node.error}`;
    if (preview) return '已导出参考图';
    return backgroundCount ? `已接入 ${backgroundCount} 张参考图` : '等待姿态编辑';
  }

    function poseDisplayTitle(node = {}, fallback = '姿态参考') {
    const title = String(node.poseTitle || fallback);
    return title === '3D 导演台' ? '姿态参考' : title;
  }

    function poseNodeHtml(node) {
    const preview = escapeHtml(node.previewImage || node.exportImage || '');
    const inputCount = getPoseInputImages(node.id).length;
    const backgroundCount = inputCount + (node.backgroundImage ? 1 : 0);
    const statusText = poseStatusText(node, preview, backgroundCount);
    const title = node.mode === 'director_stage' ? poseDisplayTitle(node) : (node.poseTitle || '姿态节点');
    const eyebrow = node.mode === 'director_stage' ? 'Pose Reference' : 'Pose Node';
    const emptyTitle = node.mode === 'director_stage' ? '姿态参考' : 'Pose Studio Lite';
    const emptyHint = node.mode === 'director_stage' ? '多角色低模人偶 / 机位截图' : '打开编辑器调整姿态';
    return `
      <section class="desk-node desk-node--pose desk-glass" data-node-id="${node.id}" aria-label="${escapeHtml(title)}">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow">${escapeHtml(eyebrow)}</p>
            <h2>${escapeHtml(title)}</h2>
          </div>
          <div class="desk-node-tools">
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--pose-in" data-port="in" data-node-id="${node.id}" title="连接图片作为背景参考" aria-label="连接姿态参考输入"></button>
        <button type="button" class="desk-port desk-port--out desk-port--pose-out" data-port="out" data-node-id="${node.id}" title="连接到模型节点作为参考图" aria-label="连接姿态输出"></button>
        <div class="desk-pose-node-preview" data-pose-preview>
          ${preview ? `<img src="${preview}" alt="姿态预览">` : `<span><strong>${escapeHtml(emptyTitle)}</strong><em>${escapeHtml(emptyHint)}</em></span>`}
        </div>
        <div class="desk-pose-node-actions">
          <button type="button" class="is-primary" data-pose-open>打开编辑器</button>
          <button type="button" data-pose-connect-input>接入模型</button>
        </div>
        <div class="desk-pill-row"><span data-pose-status>${escapeHtml(statusText)}</span><span data-pose-input-count>${backgroundCount ? `背景 ${backgroundCount}` : '可接入背景'}</span></div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放节点" aria-hidden="true"></span>
      </section>
    `;
  }

    function nodeHtmlForState(nodeId, node) {
    if (node.type === topazDefinition?.TYPE) return topazNode.nodeHtml(node);
    if (node.type === krea2Definition?.TYPE) return krea2Node.nodeHtml(node);
    if (node.type === qwen21Definition?.TYPE) return qwen21Node.nodeHtml(node);
    if (cyimgDefinition?.TYPES.includes(node.type)) return cyimgNode.nodeHtml(node);
    if (node.type === videoControlDefinition?.TYPE) return videoControlNode.nodeHtml(node);
    if (node.type === topazVideoDefinition?.TYPE) return topazVideoNode.nodeHtml(node);
    if (musicNodeDefinition?.TYPES.includes(node.type)) return musicNode.nodeHtml(node);
    if (node.type === 'audio') return audioNode.nodeHtml(node);
    if (node.type === 'file_output') return fileOutputNodeHtml(nodeId);
    if (node.type === 'image_group') return imageGroupNodeHtml(node);
    if (node.type === 'image') return imageNodeHtml(node);
    if (node.type === 'video') return videoNodeHtml(node);
    if (node.type === 'video_inference') return videoInferenceNodeHtml(node);
    if (node.type === 'comfy') return comfyNodeHtml(node);
    if (node.type === 'upscale') return upscaleNodeHtml(node);
    if (node.type === 'pose') return poseNodeHtml(node);
    if (node.type === 'layout') return layoutNodeHtml(node);
    if (node.type === 'text') return textNodeHtml(node);
    return inputNodeHtml(nodeId);
  }

    function ensureGraphDom() {
    const world = els.deskCanvasWorld;
    if (!world) return;
    world.querySelectorAll('.desk-node[data-node-id]').forEach(node => {
      if (!DesktopState.state.canvas.nodes[node.dataset.nodeId]) {
        progressView?.releaseWithin(node);
        discardFloatingSwellState(node);
        node.remove();
      }
    });
    Object.entries(DesktopState.state.canvas.nodes).forEach(([nodeId, node]) => {
      topazDefinition?.migrate(node);
      if (getNodeElement(nodeId)) return;
      if (node.type === 'output') return;
      const html = nodeHtmlForState(nodeId, node);
      world.insertAdjacentHTML('beforeend', html);
    });
    world.querySelectorAll('.desk-node[data-node-id]').forEach(ensureNodeEdgeHandles);
    audioNode.reconcile();
    musicNode?.reconcile();
    videoControlNode?.reconcile();
    topazVideoNode?.reconcile();
    topazNode?.reconcile();
    cyimgNode?.reconcile();
    krea2Node?.reconcile();
    qwen21Node?.reconcile();
  }

    function resetNodeLayout() {
    progressView?.clear();
    musicNode?.disposeAll();
    videoControlNode?.disposeAll(true);
    topazVideoNode?.disposeAll(true);
    cyimgNode?.disposeAll();
    krea2Node?.disposeAll();
    qwen21Node?.disposeAll();
    audioNode.disposeAll();
    DesktopState.state.canvas.nodes = {
      input: { id: 'input', type: 'input', x: 56, y: 72, width: DEFAULT_INPUT_NODE_WIDTH, height: DEFAULT_INPUT_NODE_HEIGHT }
    };
    DesktopState.state.canvas.edges = [];
    DesktopState.state.nodeReferenceImages = {};
    document.querySelectorAll('.desk-node[data-node-id]:not(#deskInputNode)').forEach(node => node.remove());
    ensureDefaultModelOutputState();
    applyAllNodeLayouts();
    DesktopState.saveSettings({ criticalCanvas: true });
  }

    function getLayoutInputImages(layoutNodeId) {
    const layoutNode = DesktopState.state.canvas.nodes[layoutNodeId];
    if (!layoutNode || layoutNode.type !== 'layout') return [];
    const direct = Array.isArray(layoutNode.layoutInputImages)
      ? layoutNode.layoutInputImages.map((image, index) => ({
        id: image.id || `direct:${image.taskId || image.imageUrl || image.name || index}`,
        name: image.name || image.title || '输入图片',
        type: image.type || image.mimeType || 'image/png',
        url: image.imageUrl || image.url || image.imageData || image.base64 || '',
        base64: image.imageData || image.base64 || '',
        imageData: image.imageData || image.base64 || '',
        imageUrl: image.imageUrl || image.url || '',
        taskId: image.taskId || '',
        source: image.source || 'layout'
      }))
      : [];
    const fromEdges = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === layoutNodeId)
      .map(edge => normalizeImageSourceFromNode(DesktopState.state.canvas.nodes[edge.from]))
      .filter(Boolean);
    const seen = new Set();
    return [...direct, ...fromEdges].filter(item => {
      const key = item.id || item.url || item.base64 || item.name;
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

    function getLayoutInputCount(layoutNodeId) {
    return getLayoutInputImages(layoutNodeId).length;
  }

    function updateLayoutInputCount(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'layout') return;
    const el = getNodeElement(nodeId);
    const target = el?.querySelector('[data-layout-input-count]');
    if (!target) return;
    const count = getLayoutInputCount(nodeId);
    target.textContent = count ? `已接入 ${count} 张图` : '可接入图片';
  }

    function addNode(type, worldPoint) {
    const nodeType = normalizeNodeMenuType(type);
    const node = createNodeState(nodeType);
    if (worldPoint) {
      node.x = worldPoint.x - node.width / 2;
      node.y = worldPoint.y - node.height / 2;
    }
    ensureGraphDom();
    applyNodeLayout(node.id);
    if (nodeType !== 'upscale' && getNodeElement(node.id)?.querySelector('[data-output-archive], [data-output-telegram]')) {
      syncOutputControlsToNodes(DesktopState.state.output, { save: false });
    }
    if (nodeType === 'image') triggerImageNodePopIn(node.id, 0);
    updateLinkPath();
    DesktopState.saveSettings();
    return node.id;
  }

    function normalizeNodeMenuType(type) {
    if (type === videoControlDefinition?.TYPE) return type;
    if (type === topazVideoDefinition?.TYPE) return type;
    if (type === topazDefinition?.TYPE) return type;
    if (type === krea2Definition?.TYPE) return type;
    if (type === qwen21Definition?.TYPE) return type;
    if (cyimgDefinition?.TYPES.includes(type)) return type;
    if (musicNodeDefinition?.TYPES.includes(type)) return type;
    return ['input', 'comfy', 'video_inference', 'video', 'audio', 'file_output', 'layout', 'text', 'image', 'image_group', 'pose', 'upscale'].includes(type) ? type : 'input';
  }

    function addNodeFromMenu(type, worldPoint) {
    const nodeType = normalizeNodeMenuType(type);
    const id = addNode(nodeType, worldPoint || getViewportCenterWorldPoint());
    selectNode(id);
    return id;
  }

    function removeNode(nodeId, options = {}) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node) return;
    if (node.type === videoControlDefinition?.TYPE) videoControlNode.dispose(nodeId, true);
    if (node.type === topazVideoDefinition?.TYPE) topazVideoNode.dispose(nodeId, true);
    if (cyimgDefinition?.TYPES.includes(node.type)) cyimgNode.dispose(nodeId);
    if (node.type === krea2Definition?.TYPE) krea2Node.dispose(nodeId);
    if (node.type === qwen21Definition?.TYPE) qwen21Node.dispose(nodeId);
    if (node.type === 'audio') audioNode.dispose(nodeId);
    if (musicNodeDefinition?.TYPES.includes(node.type)) musicNode.dispose(nodeId);
    if (node.type === 'video_inference') stopVideoTaskPolling(nodeId);
    if (node.type === 'image_group') freezeImageReferenceTokens(nodeId);
    if (node.type === 'image') freezeImageReferenceTokensForSourceNode(nodeId);
    const nodeEl = getNodeElement(nodeId);
    progressView?.releaseWithin(nodeEl);
    if (nodeEl?.contains(document.activeElement)) {
      document.activeElement?.blur?.();
    }
    discardFloatingSwellState(nodeEl);
    nodeEl?.remove();
    clearPromptDocumentHistory(nodeId);
    delete DesktopState.state.canvas.nodes[nodeId];
    delete DesktopState.state.outputs[nodeId];
    const refs = nodeId === 'input' ? DesktopState.state.referenceImages : (getNodeReferenceStore()[nodeId] || []);
    refs.forEach(revokeReferenceUrl);
    if (nodeId === 'input') DesktopState.state.referenceImages = [];
    delete getNodeReferenceStore()[nodeId];
    normalizeNodeGroups();
    setSelectedNodes(options.clearSelection ? [] : getSelectedNodeIds().filter(id => id !== nodeId), false);
    const affectedLayoutIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .map(edge => edge.to)
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'layout');
    const affectedPoseIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .map(edge => edge.to)
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'pose');
    const affectedUpscaleIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .flatMap(edge => [edge.from, edge.to])
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'upscale');
    const affectedVideoInferenceIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .flatMap(edge => [edge.from, edge.to])
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'video_inference');
    const affectedVideoIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .flatMap(edge => [edge.from, edge.to])
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'video');
    DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || []).filter(edge => edge.from !== nodeId && edge.to !== nodeId);
    refreshImageReferenceTokens();
    window.dispatchEvent(new CustomEvent('desktop:canvas-node-removed', { detail: { nodeId } }));
    if (node.type === 'text') notifyTextNodeListChange(nodeId);
    affectedLayoutIds.forEach(updateLayoutInputCount);
    affectedPoseIds.forEach(refreshPoseNode);
    affectedUpscaleIds.forEach(updateUpscaleInputCount);
    affectedVideoInferenceIds.forEach(refreshVideoInferenceNode);
    affectedVideoIds.forEach(refreshVideoNode);
    updateLinkPath();
    DesktopState.saveSettings(node.type === 'image_group' ? { criticalCanvas: true } : undefined);
    if (options.focusCanvas) focusCanvasViewport();
  }

    function refreshLayoutNode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || !el) return;
    const preview = el.querySelector('[data-layout-preview]');
    if (!preview) return;
    const src = node.layoutPreview || node.layoutExport || '';
    preview.innerHTML = src ? `<img src="${escapeHtml(src)}" alt="排版预览">` : '<span>尚未排版</span>';
    updateLayoutInputCount(nodeId);
    renderMiniMap();
  }

    function refreshPoseNode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'pose' || !el) return;
    const preview = el.querySelector('[data-pose-preview]');
    const inputCountTarget = el.querySelector('[data-pose-input-count]');
    const statusTarget = el.querySelector('[data-pose-status]');
    const src = node.previewImage || node.exportImage || '';
    const inputCount = getPoseInputImages(nodeId).length;
    const backgroundCount = inputCount + (node.backgroundImage ? 1 : 0);
    if (preview) {
      preview.innerHTML = src
        ? `<img src="${escapeHtml(src)}" alt="姿态预览">`
        : '<span><strong>姿态参考</strong><em>打开编辑器调整姿态</em></span>';
    }
    if (inputCountTarget) inputCountTarget.textContent = backgroundCount ? `背景 ${backgroundCount}` : '可接入背景';
    if (statusTarget) {
      statusTarget.textContent = poseStatusText(node, src, backgroundCount);
    }
    renderMiniMap();
  }

    function connectPoseToDefaultInput(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'pose') return;
    const targetInputId = findDefaultInputNodeId();
    if (!targetInputId) {
      DesktopResults.showTransientMessage('没有可接入的模型节点。');
      return;
    }
    connectNodes(nodeId, targetInputId);
    selectNode(nodeId);
    updateLinkPath();
  }

    function toggleNodeDrawer(node) {
    const drawer = node.querySelector('.desk-node__drawer');
    const button = node.querySelector('[data-toggle-node], #deskToggleInputBtn');
    if (!drawer) return;
    if (node.classList.contains('desk-node--input')) {
      drawer.style.display = 'grid';
      node.classList.remove('is-expanded');
      return;
    }
    const expanded = drawer.style.display === 'none';
    drawer.style.display = expanded ? 'grid' : 'none';
    node.classList.toggle('is-expanded', expanded);
    if (button) button.textContent = expanded ? '收起' : '展开';
  }

    function refreshImageNode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'image' || !el) return;
    const src = imageNodeSource(node);
    el.classList.toggle('has-image', !!src);
    el.classList.toggle('is-empty', !src);
    const tools = el.querySelector('.desk-image-node__tools');
    const nextToolsHtml = imageNodeToolsHtml(node);
    if (!src) {
      if (tools) tools.remove();
      return;
    }
    if (tools) {
      tools.outerHTML = nextToolsHtml;
    } else {
      const firstPort = el.querySelector('.desk-port');
      if (firstPort) {
        firstPort.insertAdjacentHTML('beforebegin', nextToolsHtml);
      } else {
        el.insertAdjacentHTML('beforeend', nextToolsHtml);
      }
    }
  }

    function refreshImageNodeContent(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'image' || !el) return;
    const src = node.imageData || node.imageUrl || '';
    const existingImage = el.querySelector('img');
    const existingPlaceholder = el.querySelector('.desk-image-node__placeholder');
    if (src) {
      if (existingImage) {
        existingImage.src = src;
        existingImage.alt = node.imageName || '图片节点';
      } else {
        existingPlaceholder?.insertAdjacentHTML('beforebegin', `<img src="${escapeHtml(src)}" alt="${escapeHtml(node.imageName || '图片节点')}" draggable="false">`);
        existingPlaceholder?.remove();
      }
    } else if (existingPlaceholder) {
      existingPlaceholder.outerHTML = imageNodePlaceholderHtml();
    } else {
      existingImage?.insertAdjacentHTML('afterend', imageNodePlaceholderHtml());
      existingImage?.remove();
    }
    refreshImageNode(nodeId);
    applyNodeLayout(nodeId);
  }

    function migrateLegacyComfyProviders() {
    let changed = false;
    const state = DesktopState.state;
    Object.values(state.canvas.nodes || {}).forEach(node => {
      if (!node || node.id === 'input' || node.type !== 'input' || node.provider !== 'comfy') return;
      node.type = 'comfy';
      node.workflow = node.params?.workflow || node.workflow || '';
      node.ratio = node.params?.ratio || node.ratio || '1:1';
      node.resolution = node.params?.resolution || node.resolution || '1k';
      node.pixelWidth = normalizeComfyPixelSize(node.params?.width, DEFAULT_COMFY_PIXEL_WIDTH);
      node.pixelHeight = normalizeComfyPixelSize(node.params?.height, DEFAULT_COMFY_PIXEL_HEIGHT);
      node.width = DEFAULT_COMFY_NODE_WIDTH;
      node.height = DEFAULT_COMFY_NODE_HEIGHT;
      node.output = { archiveEnabled: true, telegramEnabled: node.output?.telegramEnabled !== false };
      changed = true;
    });
    if (state.provider !== 'comfy') return changed;
    const primary = state.canvas.nodes.input;
    if (!primary) {
      state.provider = 'gpt';
      return true;
    }
    const comfy = createNodeState('comfy');
    comfy.x = primary.x + primary.width + 84;
    comfy.y = primary.y;
    comfy.workflow = state.params.workflow || comfy.workflow || '';
    comfy.ratio = state.params.ratio || '1:1';
    comfy.resolution = state.params.resolution || '1k';
    comfy.pixelWidth = normalizeComfyPixelSize(state.params.width, comfy.pixelWidth || DEFAULT_COMFY_PIXEL_WIDTH);
    comfy.pixelHeight = normalizeComfyPixelSize(state.params.height, comfy.pixelHeight || DEFAULT_COMFY_PIXEL_HEIGHT);
    state.canvas.edges = (state.canvas.edges || []).map(edge => ({
      ...edge,
      from: edge.from === 'input' ? comfy.id : edge.from,
      to: edge.to === 'input' ? comfy.id : edge.to
    }));
    if (state.referenceImages?.length) {
      state.nodeReferenceImages[comfy.id] = state.referenceImages;
      state.referenceImages = [];
    }
    if (state.outputs?.input) {
      state.outputs[comfy.id] = { ...state.outputs.input, type: 'comfy' };
      state.outputs.input = { status: 'idle', stage: '', progressText: '', progress: 0, files: [], imagePaths: [], primaryFile: '', primaryImagePath: '', type: 'gpt', error: '', taskId: '' };
    }
    state.provider = 'gpt';
    primary.provider = 'gpt';
    changed = true;
    return changed;
  }

    return Object.freeze({
      applyNodeLayout,
      ensureDefaultModelOutputState,
      migrateResultNodesToModelOutputs,
      migrateLegacyPromptDraftToTextNode,
      setNodePaletteOpen,
      nodeMenuButtonHtml,
      renderNodePaletteItems,
      applyNodeSelection,
      nextNodeId,
      createNodeState,
      createDefaultDirectorData,
      imageNodeSource,
      imageNodePlaceholderHtml,
      imageNodeToolsHtml,
      imageNodeHtml,
      layoutNodeHtml,
      getPoseInputImages,
      poseStatusText,
      poseDisplayTitle,
      poseNodeHtml,
      nodeHtmlForState,
      ensureGraphDom,
      resetNodeLayout,
      getLayoutInputImages,
      getLayoutInputCount,
      updateLayoutInputCount,
      addNode,
      normalizeNodeMenuType,
      addNodeFromMenu,
      removeNode,
      refreshLayoutNode,
      refreshPoseNode,
      connectPoseToDefaultInput,
      toggleNodeDrawer,
      refreshImageNode,
      refreshImageNodeContent,
      migrateLegacyComfyProviders,
    });
  }

  window.DesktopCanvasNodes = Object.freeze({ create });
})();
