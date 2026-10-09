(function () {
  const els = {};
  const MAX_IMAGE_ATTACHMENTS = 4;
  const MAX_VIDEO_ATTACHMENTS = 2;
  const MAX_MEDIA_ATTACHMENTS = 4;
  const HIDDEN_ANALYSIS_MODULE_IDS = new Set(['main', 'visual_summary', 'text_markdown']);
  const SESSION_STORAGE_KEY = 'desktop_prompt_drawer_session_v2';
  const SESSION_SCHEMA_VERSION = 5;
  const ASSISTANT_TASK_MODES = new Set(['conversation', 'image_analysis', 'video_prompt']);
  const MAX_SESSION_MESSAGES = 80;
  const MAX_SESSION_CANDIDATES = 40;
  let promptEditor = null;
  let sessionRestored = false;
  let sessionSaveTimer = 0;
  const state = {
    open: false,
    busyChat: false,
    busyVersions: false,
    boundTextNodeId: '',
    candidates: [],
    messages: [],
    imageAttachments: [],
    taskMode: 'conversation',
    resultMode: '',
    imageAnalysis: null,
    analysisModules: [],
    ocrText: '',
    textRegions: [],
    keepImageText: false,
    mentionQuery: '',
    expandedCandidateId: '',
    modalMode: '',
    modalCandidateLanguage: 'zh',
    modalOffsetX: 0,
    modalOffsetY: 0
  };
  const modalDrag = {
    active: false,
    pointerId: null,
    startClientX: 0,
    startClientY: 0,
    startOffsetX: 0,
    startOffsetY: 0,
    startRect: null
  };
  const streamTyping = {
    messageIndex: -1,
    queue: [],
    timer: 0,
    idleResolvers: []
  };

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

  function collectElements() {
    [
      'deskPromptDrawer',
      'deskPromptDrawerToggle',
      'deskPromptDrawerTarget',
      'deskPromptDrawerMeta',
      'deskPromptNodeSelect',
      'deskPromptDrawerClear',
      'deskPromptChatMessages',
      'deskPromptChatTextWrap',
      'deskPromptImageMenu',
      'deskPromptChatInput',
      'deskPromptTaskMode',
      'deskPromptImageAnalysisToggle',
      'deskPromptChatSend',
      'deskPromptGenerateVersions',
      'deskPromptCandidatesTitle',
      'deskPromptChatExpand',
      'deskPromptVersionsExpand',
      'deskPromptChatRefresh',
      'deskPromptCandidateList',
      'deskPromptModal',
      'deskPromptModalTitle',
      'deskPromptModalContent',
      'deskPromptModalClose'
    ].forEach(id => {
      els[id] = $(id);
    });
    els.deskPromptModalPanel = els.deskPromptModal?.querySelector('.desk-prompt-modal__panel') || null;
    els.deskPromptModalDragHandle = els.deskPromptModal?.querySelector('[data-prompt-modal-drag-handle]') || null;
  }

  function normalizeAssistantTaskMode(value) {
    const mode = String(value || '').trim().toLowerCase();
    return ASSISTANT_TASK_MODES.has(mode) ? mode : 'conversation';
  }

  function isImageAnalysisMode() {
    return state.taskMode === 'image_analysis';
  }

  function isVideoPromptMode() {
    return state.taskMode === 'video_prompt';
  }

  function inferResultTaskMode(candidates = state.candidates, analysisModules = state.analysisModules) {
    if (state.imageAnalysis || (analysisModules || []).length || (candidates || []).some(item => ['image_analysis_main', 'video_analysis_main'].includes(item?.kind))) {
      return 'image_analysis';
    }
    if ((candidates || []).some(item => /^h3(?:_|$)/i.test(String(item?.kind || '')) || String(item?.mode || '').toUpperCase() === 'I2VA')) {
      return 'video_prompt';
    }
    return (candidates || []).length ? 'conversation' : '';
  }

  function getTarget() {
    const target = state.boundTextNodeId
      ? window.DesktopCanvas?.getPromptTargetInfo?.(state.boundTextNodeId)
      : window.DesktopCanvas?.getPromptTargetInfo?.();
    if (target?.type === 'text' && target.nodeId) {
      return target;
    }
    return { nodeId: '', type: '', label: '未绑定文本节点', inactive: true };
  }

  function bindTextNode(nodeId) {
    const target = window.DesktopCanvas?.getPromptTargetInfo?.(nodeId);
    if (target?.type !== 'text' || !target.nodeId) return false;
    state.boundTextNodeId = target.nodeId;
    render();
    return true;
  }

  function hasTextTarget() {
    return getTarget().type === 'text' && !!getTarget().nodeId;
  }

  function getStylePresets() {
    return window.DesktopCanvas?.getTextStylePresets?.() || [];
  }

  function getTextNodes() {
    return window.DesktopCanvas?.listTextNodes?.() || [];
  }

  function currentPromptText(target = getTarget()) {
    return window.DesktopCanvas?.getPromptTargetText?.({ target }) || '';
  }

  function getImageNodes() {
    return window.DesktopCanvas?.listPromptImageNodes?.() || [];
  }

  function getMediaNodes() {
    return window.DesktopCanvas?.listPromptMediaNodes?.()
      || [
        ...getImageNodes().map(item => ({ ...item, mediaKind: 'image' })),
        ...(window.DesktopCanvas?.listPromptVideoNodes?.() || [])
      ];
  }

  function attachmentMediaKind(item = {}) {
    return window.DesktopPromptMedia?.mediaKind?.(item)
      || (String(item.mediaKind || item.media_kind || '').toLowerCase() === 'video'
        || String(item.mimeType || item.mime_type || '').toLowerCase().startsWith('video/') ? 'video' : 'image');
  }

  function canvasState() {
    return window.DesktopState?.state?.canvas || { nodes: {}, edges: [] };
  }

  function selectedCanvasNodeIds(canvas = canvasState()) {
    const ids = Array.isArray(canvas.selectedNodeIds) ? canvas.selectedNodeIds.filter(Boolean) : [];
    if (!ids.length && canvas.selectedNodeId) ids.push(canvas.selectedNodeId);
    return [...new Set(ids.map(id => String(id || '')).filter(Boolean))];
  }

  function isMiniMaxH3VideoNode(node = {}) {
    if (node?.type !== 'video_inference') return false;
    const provider = String(node.provider || 'minimax_h3').trim().toLowerCase();
    return provider === 'minimax_h3';
  }

  function videoInputRole(edge = {}, sourceNode = {}) {
    const explicit = String(edge.inputRole || edge.input_role || '').trim();
    if (explicit) return explicit;
    if (sourceNode.type === 'text') return 'prompt';
    if (['image', 'layout', 'pose'].includes(sourceNode.type)) return 'first_frame';
    if (sourceNode.type === 'video') return 'reference_video';
    return '';
  }

  function h3VideoNodeForTarget(target = getTarget()) {
    if (target?.type !== 'text' || !target.nodeId) return null;
    const canvas = canvasState();
    const nodes = canvas.nodes || {};
    const candidates = (Array.isArray(canvas.edges) ? canvas.edges : [])
      .filter(edge => edge?.from === target.nodeId)
      .map(edge => nodes[edge.to])
      .filter(isMiniMaxH3VideoNode);
    if (!candidates.length) return null;
    const selected = new Set(selectedCanvasNodeIds(canvas));
    return candidates.find(node => selected.has(node.id)) || candidates[0];
  }

  function preferredH3VideoNode() {
    const canvas = canvasState();
    const nodes = canvas.nodes || {};
    const candidates = Object.values(nodes).filter(isMiniMaxH3VideoNode);
    if (!candidates.length) return null;
    const selected = new Set(selectedCanvasNodeIds(canvas));
    return candidates.find(node => selected.has(node.id))
      || (candidates.length === 1 ? candidates[0] : null);
  }

  function h3FirstFrameNode(videoNodeId) {
    if (!videoNodeId) return null;
    const canvas = canvasState();
    const nodes = canvas.nodes || {};
    const incoming = (Array.isArray(canvas.edges) ? canvas.edges : [])
      .filter(edge => edge?.to === videoNodeId)
      .map(edge => ({ edge, node: nodes[edge.from] }))
      .filter(item => item.node);
    return incoming.find(item => videoInputRole(item.edge, item.node) === 'first_frame')?.node || null;
  }

  function h3ReferenceMetadata(item = {}, source = 'canvas') {
    const sourceNodeId = String(item.sourceNodeId || item.nodeId || item.source_node_id || item.id || '').trim();
    const label = String(item.label || item.imageName || item.sourceTitle || item.name || '首帧').trim();
    return {
      role: 'first_frame',
      source,
      source_node_id: sourceNodeId,
      reference_id: String(item.id || sourceNodeId || 'first_frame').trim(),
      label,
      mime_type: String(item.mimeType || item.mime_type || 'image/png').trim()
    };
  }

  function h3TaskContext(target = getTarget(), options = {}) {
    const standalone = !!options.standalone;
    const videoNode = h3VideoNodeForTarget(target) || (standalone ? preferredH3VideoNode() : null);
    if (!videoNode && !standalone) return null;
    const attachedFirstFrame = state.imageAttachments.find(item => attachmentMediaKind(item) === 'image') || null;
    const connectedFirstFrame = h3FirstFrameNode(videoNode?.id);
    const firstFrame = attachedFirstFrame
      ? h3ReferenceMetadata(attachedFirstFrame, 'mention')
      : (connectedFirstFrame ? h3ReferenceMetadata(connectedFirstFrame, 'canvas') : null);
    return {
      task_domain: 'video',
      target_model: 'minimax_h3',
      provider: 'minimax_h3',
      mode: 'I2VA',
      inference_mode: String(videoNode?.mode || 'image_to_video'),
      video_node_id: String(videoNode?.id || ''),
      text_node_id: String(target.nodeId || ''),
      duration_seconds: Number(videoNode?.durationSeconds || videoNode?.duration_seconds || 15),
      aspect_ratio: String(videoNode?.aspectRatio || videoNode?.aspect_ratio || '3:4'),
      first_frame_node_id: String(firstFrame?.source_node_id || ''),
      first_frame: firstFrame
    };
  }

  function activeH3TaskContext(target = getTarget()) {
    return isVideoPromptMode() ? h3TaskContext(target, { standalone: true }) : null;
  }

  function imageAttachmentKey(item = {}) {
    return String(item.sourceNodeId || item.nodeId || item.source_node_id || item.dataUrl || item.imageData || item.imageUrl || item.mediaUrl || item.videoUrl || item.url || item.id || '').trim();
  }

  function editorText() {
    return promptEditor?.getText?.() || String(els.deskPromptChatInput?.textContent || '').trim();
  }

  function truncateForSession(value, maxLength = 30000) {
    const text = String(value || '');
    if (text.length <= maxLength) return text;
    return `${text.slice(0, maxLength)}\n\n…[已截断，完整内容请重新生成或查看已保存版本]`;
  }

  function safeSessionClone(value, depth = 0) {
    if (value == null) return value;
    if (typeof value === 'string') return truncateForSession(value);
    if (typeof value === 'number' || typeof value === 'boolean') return value;
    if (depth > 5) return null;
    if (Array.isArray(value)) return value.slice(0, 120).map(item => safeSessionClone(item, depth + 1));
    if (typeof value === 'object') {
      const output = {};
      Object.entries(value).slice(0, 120).forEach(([key, item]) => {
        if (typeof item === 'function') return;
        output[key] = safeSessionClone(item, depth + 1);
      });
      return output;
    }
    return null;
  }

  function sanitizeSessionMessage(message = {}) {
    const role = message.role === 'user' ? 'user' : 'assistant';
    return {
      role,
      text: truncateForSession(message.text || ''),
      streaming: false
    };
  }

  function sanitizeSessionCandidate(candidate = {}) {
    const keys = [
      'id', 'kind', 'label', 'badge', 'text', 'text_en', 'text_zh',
      'textEn', 'textZh', 'display_text', 'displayText', 'base_text', 'baseText',
      'language', 'task_type', 'taskType', 'intent', 'risk_score',
      'riskScore', 'risk_level', 'riskLevel', 'risk_flags', 'riskFlags',
      'changed_terms', 'changedTerms', 'warnings', 'adapter', 'meta',
      'mode', 'skill', 'validation', 'provenance'
    ];
    const output = {};
    keys.forEach(key => {
      if (candidate[key] !== undefined) output[key] = safeSessionClone(candidate[key]);
    });
    if (!output.text) output.text = truncateForSession(candidate.text || '');
    return output;
  }

  function sanitizeSessionAttachment(item = {}) {
    const kind = attachmentMediaKind(item);
    const source = kind === 'video'
      ? (item.mediaUrl || item.videoUrl || item.url || '')
      : (item.imageUrl || item.url || '');
    const poster = item.posterUrl || item.previewUrl || '';
    return {
      id: String(item.id || '').trim(),
      label: String(item.label || item.id || '').trim(),
      mediaKind: kind,
      imageUrl: kind === 'image' && !String(source || '').startsWith('data:image/') ? String(source || '').trim() : '',
      mediaUrl: kind === 'video' ? String(source || '').trim() : '',
      videoUrl: kind === 'video' ? String(source || '').trim() : '',
      posterUrl: String(poster || '').trim(),
      previewUrl: String(poster || '').trim(),
      url: String(source || '').startsWith('data:image/') ? '' : String(source || '').trim(),
      sourceNodeId: String(item.sourceNodeId || item.nodeId || item.source_node_id || '').trim(),
      mimeType: String(item.mimeType || item.type || (kind === 'video' ? 'video/mp4' : 'image/png')).trim(),
      role: String(item.role || '').trim(),
      durationSeconds: Number(item.durationSeconds || item.duration_seconds || 0),
      mediaWidth: Number(item.mediaWidth || item.width || 0),
      mediaHeight: Number(item.mediaHeight || item.height || 0),
      fps: Number(item.fps || 0),
      fileSize: Number(item.fileSize || item.file_size || 0),
      sourceTaskId: String(item.sourceTaskId || item.source_task_id || '')
    };
  }

  function promptDrawerSessionSnapshot() {
    syncImageAttachmentsFromEditor();
    return {
      version: SESSION_SCHEMA_VERSION,
      savedAt: Date.now(),
      open: !!state.open,
      boundTextNodeId: state.boundTextNodeId || '',
      messages: state.messages.slice(-MAX_SESSION_MESSAGES).map(sanitizeSessionMessage),
      candidates: state.candidates.slice(0, MAX_SESSION_CANDIDATES).map(sanitizeSessionCandidate),
      imageAttachments: state.imageAttachments.map(sanitizeSessionAttachment).filter(item => item.id),
      taskMode: normalizeAssistantTaskMode(state.taskMode),
      resultMode: state.resultMode ? normalizeAssistantTaskMode(state.resultMode) : '',
      imageAnalysisMode: isImageAnalysisMode(),
      imageAnalysis: safeSessionClone(state.imageAnalysis),
      analysisModules: safeSessionClone(state.analysisModules || []),
      ocrText: truncateForSession(state.ocrText || ''),
      textRegions: safeSessionClone(state.textRegions || []),
      keepImageText: !!state.keepImageText,
      expandedCandidateId: state.expandedCandidateId || '',
      editorText: truncateForSession(editorText() || '')
    };
  }

  function savePromptDrawerSessionNow() {
    if (!sessionRestored || !window.localStorage) return;
    try {
      const snapshot = promptDrawerSessionSnapshot();
      const hasContent = snapshot.messages.length
        || snapshot.candidates.length
        || snapshot.analysisModules.length
        || snapshot.editorText
        || snapshot.imageAttachments.length
        || snapshot.taskMode !== 'conversation';
      if (!hasContent && !snapshot.open && !snapshot.boundTextNodeId) {
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
        return;
      }
      window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(snapshot));
    } catch (error) {
      console.warn('[PromptDrawer] session save failed:', error);
    }
  }

  function schedulePromptDrawerSessionSave() {
    if (!sessionRestored) return;
    window.clearTimeout(sessionSaveTimer);
    sessionSaveTimer = window.setTimeout(savePromptDrawerSessionNow, 180);
  }

  function clearPromptDrawerSession() {
    window.clearTimeout(sessionSaveTimer);
    try {
      window.localStorage?.removeItem(SESSION_STORAGE_KEY);
    } catch (error) {
      console.warn('[PromptDrawer] session clear failed:', error);
    }
  }

  function restorePromptDrawerSession() {
    if (!window.localStorage) {
      sessionRestored = true;
      return;
    }
    try {
      const parsed = JSON.parse(window.localStorage.getItem(SESSION_STORAGE_KEY) || 'null');
      if (!parsed || typeof parsed !== 'object') {
        sessionRestored = true;
        return;
      }
      const textNodeIds = new Set(getTextNodes().map(node => node.nodeId));
      if (parsed.boundTextNodeId && textNodeIds.has(parsed.boundTextNodeId)) {
        state.boundTextNodeId = parsed.boundTextNodeId;
      }
      state.open = !!parsed.open;
      state.messages = Array.isArray(parsed.messages)
        ? parsed.messages.slice(-MAX_SESSION_MESSAGES).map(sanitizeSessionMessage)
        : [];
      state.candidates = Array.isArray(parsed.candidates)
        ? parsed.candidates.slice(0, MAX_SESSION_CANDIDATES).map(sanitizeSessionCandidate).filter(item => item.text)
        : [];
      state.imageAttachments = Array.isArray(parsed.imageAttachments)
        ? parsed.imageAttachments.map(sanitizeSessionAttachment).filter(item => item.id)
        : [];
      state.taskMode = normalizeAssistantTaskMode(
        parsed.taskMode || (parsed.imageAnalysisMode ? 'image_analysis' : 'conversation')
      );
      state.imageAnalysis = parsed.imageAnalysis || null;
      state.analysisModules = Array.isArray(parsed.analysisModules) ? parsed.analysisModules : [];
      state.ocrText = String(parsed.ocrText || '');
      state.textRegions = Array.isArray(parsed.textRegions) ? normalizeTextRegions(parsed.textRegions) : [];
      state.keepImageText = !!parsed.keepImageText;
      state.expandedCandidateId = String(parsed.expandedCandidateId || '');
      state.resultMode = parsed.resultMode
        ? normalizeAssistantTaskMode(parsed.resultMode)
        : inferResultTaskMode(state.candidates, state.analysisModules);
      if (promptEditor?.setDocument) {
        const attachments = state.imageAttachments.map(item => ({
          ...normalizeAttachmentFromChip({
            id: item.id,
            sourceNodeId: item.sourceNodeId,
            imageSrc: item.imageUrl || item.posterUrl || item.previewUrl || item.url,
            mediaSrc: item.mediaUrl || item.videoUrl || item.url,
            mediaKind: item.mediaKind,
            mimeType: item.mimeType
          }),
          label: item.label
        }));
        promptEditor.setDocument(parsed.editorText || '', attachments);
      } else if (parsed.editorText && promptEditor?.setText) {
        promptEditor.setText(parsed.editorText);
      }
    } catch (error) {
      console.warn('[PromptDrawer] session restore failed:', error);
    } finally {
      sessionRestored = true;
    }
  }

  function clearEditor(options = {}) {
    if (promptEditor?.clearText && options.keepAttachments) {
      promptEditor.clearText({ keepAttachments: true });
    } else if (promptEditor?.clear) {
      promptEditor.clear();
    } else if (els.deskPromptChatInput) {
      els.deskPromptChatInput.textContent = '';
    }
  }

  function focusEditor() {
    if (promptEditor?.focus) {
      promptEditor.focus();
    } else {
      els.deskPromptChatInput?.focus?.({ preventScroll: true });
    }
  }

  function editorAttachments() {
    if (promptEditor?.getAttachments) return promptEditor.getAttachments();
    return Array.from(els.deskPromptChatInput?.querySelectorAll?.('.desk-prompt-editor__image') || [])
      .map(node => ({
        id: String(node.dataset.promptImageId || '').trim(),
        sourceNodeId: String(node.dataset.sourceNodeId || '').trim(),
        imageSrc: String(node.dataset.imageSrc || node.querySelector('img')?.getAttribute('src') || '').trim(),
        mediaSrc: String(node.dataset.mediaSrc || '').trim(),
        mediaKind: String(node.dataset.mediaKind || 'image').trim(),
        mimeType: String(node.dataset.mimeType || (node.dataset.mediaKind === 'video' ? 'video/mp4' : 'image/png')).trim()
      }))
      .filter(item => item.id);
  }

  function normalizeAttachmentFromChip(chip = {}) {
    const node = chip.sourceNodeId ? getMediaNodes().find(item => item.nodeId === chip.sourceNodeId) : null;
    const kind = attachmentMediaKind({ ...node, ...chip });
    const src = kind === 'video'
      ? (chip.mediaSrc || node?.mediaUrl || node?.videoUrl || node?.url || '')
      : (chip.imageSrc || node?.imageData || node?.imageUrl || node?.url || '');
    const isDataUrl = src.startsWith('data:image/');
    return {
      id: chip.id,
      label: chip.id,
      mediaKind: kind,
      dataUrl: kind === 'image' ? (isDataUrl ? src : (node?.imageData || '')) : '',
      imageData: kind === 'image' ? (isDataUrl ? src : (node?.imageData || '')) : '',
      imageUrl: kind === 'image' && !isDataUrl ? src : '',
      mediaUrl: kind === 'video' ? src : '',
      videoUrl: kind === 'video' ? src : '',
      posterUrl: node?.posterUrl || chip.imageSrc || '',
      previewUrl: node?.previewUrl || node?.posterUrl || chip.imageSrc || '',
      url: src,
      sourceNodeId: chip.sourceNodeId || node?.nodeId || '',
      mimeType: chip.mimeType || node?.mimeType || (kind === 'video' ? 'video/mp4' : 'image/png'),
      role: kind === 'image' ? (chip.id === 'image1' ? 'primary' : 'fusion_reserved') : 'analysis_reference',
      durationSeconds: Number(node?.durationSeconds || 0),
      mediaWidth: Number(node?.mediaWidth || 0),
      mediaHeight: Number(node?.mediaHeight || 0),
      fps: Number(node?.fps || 0),
      fileSize: Number(node?.fileSize || 0),
      sourceTaskId: String(node?.sourceTaskId || '')
    };
  }

  function syncImageAttachmentsFromEditor() {
    const chips = editorAttachments();
    const chipIds = new Set(chips.map(item => item.id));
    state.imageAttachments = state.imageAttachments.filter(item => chipIds.has(item.id));
    chips.forEach(chip => {
      const existing = state.imageAttachments.find(item => item.id === chip.id);
      if (existing) {
        const kind = attachmentMediaKind({ ...existing, ...chip });
        const isDataUrl = kind === 'image' && chip.imageSrc?.startsWith('data:image/');
        existing.sourceNodeId = existing.sourceNodeId || chip.sourceNodeId;
        existing.mediaKind = kind;
        existing.url = existing.url || chip.mediaSrc || chip.imageSrc;
        existing.mediaUrl = existing.mediaUrl || (kind === 'video' ? chip.mediaSrc : '');
        existing.videoUrl = existing.videoUrl || existing.mediaUrl;
        existing.imageUrl = existing.imageUrl || (kind === 'image' && !isDataUrl ? chip.imageSrc : '');
        existing.dataUrl = existing.dataUrl || (isDataUrl ? chip.imageSrc : '');
        existing.imageData = existing.imageData || (isDataUrl ? chip.imageSrc : '');
        existing.posterUrl = existing.posterUrl || (kind === 'video' ? chip.imageSrc : '');
        existing.previewUrl = existing.previewUrl || existing.posterUrl;
        existing.mimeType = existing.mimeType || chip.mimeType || (kind === 'video' ? 'video/mp4' : 'image/png');
        return;
      }
      state.imageAttachments.push(normalizeAttachmentFromChip(chip));
    });
  }

  function nextImageAttachmentId(kind = 'image') {
    const prefix = kind === 'video' ? 'video' : 'image';
    const used = new Set(state.imageAttachments.map(item => String(item.id || '')));
    for (let index = 1; index <= MAX_MEDIA_ATTACHMENTS; index += 1) {
      const id = `${prefix}${index}`;
      if (!used.has(id)) return id;
    }
    return `${prefix}${state.imageAttachments.length + 1}`;
  }

  function closeImageMentionMenu(options = {}) {
    state.mentionQuery = '';
    if (!options.fromEditor) promptEditor?.clearMention?.();
    if (els.deskPromptImageMenu) {
      els.deskPromptImageMenu.hidden = true;
      els.deskPromptImageMenu.innerHTML = '';
    }
  }

  function addImageAttachment(raw = {}, options = {}) {
    const kind = attachmentMediaKind(raw);
    const source = kind === 'video'
      ? (raw.mediaUrl || raw.media_url || raw.videoUrl || raw.video_url || raw.url || '')
      : (raw.dataUrl || raw.data_url || raw.imageData || raw.base64 || raw.imageUrl || raw.url || '');
    if (!source) return null;
    const key = imageAttachmentKey(raw);
    const existing = state.imageAttachments.find(item => imageAttachmentKey(item) === key);
    if (existing) {
      promptEditor?.insertAttachment?.(existing, { replaceMention: options.replaceMention !== false });
      render();
      return existing;
    }
    if (state.imageAttachments.length >= MAX_MEDIA_ATTACHMENTS) {
      window.DesktopResults?.showTransientMessage?.(`最多先选择 ${MAX_MEDIA_ATTACHMENTS} 个媒体引用。`, 'warning');
      return null;
    }
    if (kind === 'video' && state.imageAttachments.filter(item => attachmentMediaKind(item) === 'video').length >= MAX_VIDEO_ATTACHMENTS) {
      window.DesktopResults?.showTransientMessage?.(`最多同时引用 ${MAX_VIDEO_ATTACHMENTS} 个视频。`, 'warning');
      return null;
    }
    const id = options.id || nextImageAttachmentId(kind);
    const item = {
      id,
      label: String(raw.label || raw.name || raw.title || id).trim() || id,
      mediaKind: kind,
      dataUrl: kind === 'image' ? (raw.dataUrl || raw.data_url || raw.imageData || raw.base64 || '') : '',
      imageData: kind === 'image' ? (raw.imageData || raw.base64 || raw.dataUrl || raw.data_url || '') : '',
      imageUrl: kind === 'image' ? (raw.imageUrl || raw.url || '') : '',
      mediaUrl: kind === 'video' ? source : '',
      videoUrl: kind === 'video' ? source : '',
      posterUrl: raw.posterUrl || raw.poster_url || '',
      previewUrl: raw.previewUrl || raw.preview_url || raw.posterUrl || raw.poster_url || '',
      url: source,
      sourceNodeId: raw.sourceNodeId || raw.nodeId || raw.source_node_id || '',
      mimeType: raw.mimeType || raw.mime_type || (kind === 'video' ? 'video/mp4' : 'image/png'),
      role: kind === 'image'
        ? (state.imageAttachments.some(value => attachmentMediaKind(value) === 'image') ? 'fusion_reserved' : 'primary')
        : 'analysis_reference',
      durationSeconds: Number(raw.durationSeconds || raw.duration_seconds || 0),
      mediaWidth: Number(raw.mediaWidth || raw.media_width || raw.width || 0),
      mediaHeight: Number(raw.mediaHeight || raw.media_height || raw.height || 0),
      fps: Number(raw.fps || 0),
      fileSize: Number(raw.fileSize || raw.file_size || 0),
      sourceTaskId: String(raw.sourceTaskId || raw.source_task_id || '')
    };
    state.imageAttachments.push(item);
    promptEditor?.insertAttachment?.(item, { replaceMention: options.replaceMention !== false });
    render();
    return item;
  }

  function removeImageAttachment(id) {
    const cleanId = String(id || '');
    state.imageAttachments = state.imageAttachments.filter(item => item.id !== cleanId);
    promptEditor?.removeAttachment?.(cleanId, { silent: true });
    render();
  }

  function renderImageAttachments() {
    promptEditor?.setAttachments?.(state.imageAttachments);
    els.deskPromptChatTextWrap?.classList.toggle('has-image-token', state.imageAttachments.length > 0);
  }

  function renderImageMentionMenu() {
    if (!els.deskPromptImageMenu || !promptEditor?.hasMention?.()) return;
    const query = String(state.mentionQuery || '').trim().toLowerCase();
    const nodes = getMediaNodes()
      .filter(node => {
        if (!query) return true;
        return `${node.label || ''} ${node.name || ''} ${node.nodeId || ''}`.toLowerCase().includes(query);
      })
      .slice(0, 8);
    const columns = Math.max(1, Math.min(nodes.length || 1, 3));
    els.deskPromptImageMenu.style.setProperty('--desk-prompt-image-menu-cols', String(columns));
    els.deskPromptImageMenu.dataset.imageCount = String(nodes.filter(node => attachmentMediaKind(node) === 'image').length);
    els.deskPromptImageMenu.dataset.videoCount = String(nodes.filter(node => attachmentMediaKind(node) === 'video').length);
    if (!nodes.length) {
      els.deskPromptImageMenu.innerHTML = '<div class="desk-prompt-image-menu__empty">没有图片或视频节点</div>';
    } else {
      els.deskPromptImageMenu.innerHTML = nodes.map(node => {
        const kind = attachmentMediaKind(node);
        const videoSrc = typeof window.miniappMediaUrl === 'function' ? window.miniappMediaUrl(node.mediaUrl || node.videoUrl || node.url || '') : (node.mediaUrl || node.videoUrl || node.url || '');
        const poster = typeof window.miniappMediaUrl === 'function' ? window.miniappMediaUrl(node.posterUrl || node.previewUrl || '') : (node.posterUrl || node.previewUrl || '');
        const preview = kind === 'video'
          ? (poster ? `<img src="${escapeHtml(poster)}" alt="">` : `<video src="${escapeHtml(videoSrc)}" muted playsinline preload="metadata"></video>`)
          : `<img src="${escapeHtml(node.imageData || node.imageUrl || node.url)}" alt="">`;
        return `
        <button type="button" data-prompt-pick-media-node="${escapeHtml(node.nodeId)}" data-media-kind="${kind}" aria-label="引用${kind === 'video' ? '视频' : '图片'}节点" title="引用${kind === 'video' ? '视频（用于分析）' : '图片'}节点">
          ${preview}
          <span class="desk-prompt-image-menu__kind" aria-hidden="true">${kind === 'video' ? '视频' : '图片'}</span>
        </button>
      `;
      }).join('');
    }
    els.deskPromptImageMenu.hidden = false;
  }

  async function attachImageNode(nodeId) {
    const node = getMediaNodes().find(item => item.nodeId === nodeId);
    if (!node) return;
    if (attachmentMediaKind(node) === 'video') {
      addImageAttachment({ ...node, sourceNodeId: node.nodeId }, { replaceMention: true });
      closeImageMentionMenu();
      return;
    }
    const source = node.imageData || node.imageUrl || node.url || '';
    let dataUrl = node.imageData || '';
    if (!dataUrl && source && window.DesktopApi?.imageUrlToDataUri) {
      dataUrl = await window.DesktopApi.imageUrlToDataUri(source);
    }
    addImageAttachment({
      ...node,
      dataUrl: dataUrl || source,
      imageData: dataUrl || node.imageData || '',
      imageUrl: node.imageUrl || (dataUrl ? '' : source),
      sourceNodeId: node.nodeId
    }, { replaceMention: true });
    closeImageMentionMenu();
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function setPromptDrawerHandleEyesOffset(x, y) {
    if (!els.deskPromptDrawerToggle) return;
    els.deskPromptDrawerToggle.style.setProperty('--desk-prompt-handle-eye-shift-x', `${Number(x || 0).toFixed(2)}px`);
    els.deskPromptDrawerToggle.style.setProperty('--desk-prompt-handle-eye-shift-y', `${Number(y || 0).toFixed(2)}px`);
  }

  // 眼睛跟随是 document 级 pointermove：必须 rAF 合并 + 缓存把手矩形，
  // 否则每个指针事件一次 getBoundingClientRect 强制回流，会拖慢全应用的拖拽交互（如图片对比滑杆）
  let handleEyesRaf = 0;
  let handleEyesPoint = null;
  let handleEyesRect = null;
  let handleEyesRectAt = 0;

  function resetPromptDrawerHandleEyes() {
    if (handleEyesRaf) {
      window.cancelAnimationFrame(handleEyesRaf);
      handleEyesRaf = 0;
    }
    handleEyesPoint = null;
    setPromptDrawerHandleEyesOffset(0, 0);
  }

  function updatePromptDrawerHandleEyes(event) {
    if (!state.open || !els.deskPromptDrawerToggle) return;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) {
      resetPromptDrawerHandleEyes();
      return;
    }
    if (event?.pointerType && event.pointerType !== 'mouse') return;
    handleEyesPoint = { x: event.clientX, y: event.clientY };
    if (handleEyesRaf) return;
    handleEyesRaf = window.requestAnimationFrame(() => {
      handleEyesRaf = 0;
      const point = handleEyesPoint;
      if (!point || !state.open || !els.deskPromptDrawerToggle) return;
      const now = performance.now();
      if (!handleEyesRect || now - handleEyesRectAt > 300) {
        handleEyesRect = els.deskPromptDrawerToggle.getBoundingClientRect();
        handleEyesRectAt = now;
      }
      const rect = handleEyesRect;
      if (!rect.width || !rect.height) return;
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const driftX = clamp((point.x - centerX) * 0.03, -2.2, 2.2);
      const driftY = clamp((point.y - centerY) * 0.02, -1.6, 1.6);
      setPromptDrawerHandleEyesOffset(driftX, driftY);
    });
  }

  function applyPromptDrawerOpenState(open) {
    state.open = !!open;
    handleEyesRect = null;
    els.deskPromptDrawer?.classList.toggle('is-open', state.open);
    els.deskPromptDrawer?.setAttribute('aria-expanded', state.open ? 'true' : 'false');
    resetPromptDrawerHandleEyes();
    if (state.open && !els.deskPromptDrawer?.classList.contains('is-agent')) {
      window.setTimeout(focusEditor, 40);
    }
    render();
  }

  let promptGenieRunId = 0;
  let promptGenieHandle = null;

  function stopPromptGenieAnimation() {
    promptGenieHandle?.cancel?.();
    promptGenieHandle = null;
    els.deskPromptDrawer?.classList.remove('is-genie-anim', 'is-genie-hidden');
  }

  function promptGenieConfig(drawer) {
    const isAgent = drawer?.classList.contains('is-agent');
    return {
      duration: isAgent ? 320 : 500,
      snapshot: {
        skipHiddenSubtrees: true,
        maxRasterWidth: isAgent ? 720 : 960,
        maxRasterHeight: isAgent ? 280 : 360
      }
    };
  }

  function promptDrawerCollapsedRect() {
    // 收起态：87×21 药丸，水平居中，bottom 35px（与 .desk-prompt-drawer 基础样式一致）
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const width = 87;
    const height = 21;
    return {
      left: Math.max(0, (viewportWidth - width) / 2),
      top: Math.max(0, viewportHeight - 35 - height),
      width,
      height
    };
  }

  async function animatePromptGenieClose(runId) {
    const drawer = els.deskPromptDrawer;
    const fx = window.DeskGenieFX;
    const genie = promptGenieConfig(drawer);
    const panelRect = drawer.getBoundingClientRect();
    const source = await fx.snapshotPanel(drawer, panelRect, genie.snapshot);
    if (runId !== promptGenieRunId) return;
    let completed = false;
    const handle = fx.animate({
      direction: 'minimize',
      source,
      targetRect: promptDrawerCollapsedRect(),
      panelRect,
      duration: genie.duration,
      isCancelled: () => runId !== promptGenieRunId,
      onStart: () => {
        drawer.classList.add('is-genie-anim');
        applyPromptDrawerOpenState(false);
      },
      onDone: () => {
        completed = true;
        if (runId === promptGenieRunId) promptGenieHandle = null;
        drawer.classList.remove('is-genie-anim');
      }
    });
    if (!completed && runId === promptGenieRunId) promptGenieHandle = handle;
  }

  async function animatePromptGenieOpen(runId) {
    const drawer = els.deskPromptDrawer;
    const fx = window.DeskGenieFX;
    const genie = promptGenieConfig(drawer);
    // 先无过渡地切到展开布局并整体隐形，待快照就绪再播翘曲
    drawer.classList.add('is-genie-anim', 'is-genie-hidden');
    applyPromptDrawerOpenState(true);
    await new Promise(resolve => window.requestAnimationFrame(resolve));
    if (runId !== promptGenieRunId) {
      drawer.classList.remove('is-genie-anim', 'is-genie-hidden');
      return;
    }
    const panelRect = drawer.getBoundingClientRect();
    const source = await fx.snapshotPanel(drawer, panelRect, genie.snapshot);
    if (runId !== promptGenieRunId) {
      drawer.classList.remove('is-genie-anim', 'is-genie-hidden');
      return;
    }
    let completed = false;
    const handle = fx.animate({
      direction: 'open',
      source,
      targetRect: promptDrawerCollapsedRect(),
      panelRect,
      duration: genie.duration,
      isCancelled: () => runId !== promptGenieRunId,
      onStart: () => {},
      onDone: () => {
        completed = true;
        if (runId === promptGenieRunId) promptGenieHandle = null;
        drawer.classList.remove('is-genie-anim', 'is-genie-hidden');
      }
    });
    if (!completed && runId === promptGenieRunId) promptGenieHandle = handle;
  }

  function setOpen(open, animate = true) {
    const next = !!open;
    const fx = window.DeskGenieFX;
    if (next === state.open && !promptGenieHandle) return;
    const runId = ++promptGenieRunId;
    stopPromptGenieAnimation();
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    if (!animate || reducedMotion || !fx?.ready?.() || !els.deskPromptDrawer) {
      applyPromptDrawerOpenState(next);
      return;
    }
    if (next) {
      animatePromptGenieOpen(runId).catch(() => {
        if (runId !== promptGenieRunId) return;
        applyPromptDrawerOpenState(true);
        stopPromptGenieAnimation();
      });
    } else {
      animatePromptGenieClose(runId).catch(() => {
        if (runId !== promptGenieRunId) return;
        applyPromptDrawerOpenState(false);
        stopPromptGenieAnimation();
      });
    }
  }

  function taskModeCopy(mode = state.taskMode) {
    if (mode === 'image_analysis') {
      return {
        candidateTitle: '媒体分析',
        placeholder: '输入分析要求，并用 @ 选择要分析的图片或视频。',
        emptyMessage: '用 @ 引用画布图片或视频开始分析。',
        emptyCandidate: '分析结果会显示在这里。',
        sendLabel: '分析媒体',
        sendTitle: '调用图片或视频分析',
        generateLabel: '',
        meta: '参考媒体分析'
      };
    }
    if (mode === 'video_prompt') {
      return {
        candidateTitle: 'H3 视频提示词',
        placeholder: '描述视频动作、镜头与声音，输入 @ 可引用首帧图片或参考视频。',
        emptyMessage: '开始讨论 MiniMax H3 视频方向。',
        emptyCandidate: '生成的视频提示词会显示在这里。',
        sendLabel: '讨论',
        sendTitle: '发送消息，与助手讨论 MiniMax H3 视频方向；不会直接生成正式提示词',
        generateLabel: '生成视频提示词',
        meta: 'MiniMax H3 · I2VA'
      };
    }
    return {
      candidateTitle: '图片提示词',
      placeholder: '输入讨论内容，或输入 @ 选择画布图片/视频节点。',
      emptyMessage: '开始讨论图片提示词方向。',
      emptyCandidate: '生成的图片提示词会显示在这里。',
      sendLabel: '发送',
      sendTitle: '讨论图片提示词方向',
      generateLabel: '生成图片提示词',
      meta: '普通会话'
    };
  }

  function setAssistantTaskMode(mode, options = {}) {
    const nextMode = normalizeAssistantTaskMode(mode);
    if (nextMode === state.taskMode) return;
    state.taskMode = nextMode;
    closeImageMentionMenu();
    render();
    if (options.focus !== false) window.setTimeout(focusEditor, 0);
  }

  function hasGenerationSeed(target = getTarget()) {
    return [
      editorText(),
      target?.type === 'text' ? currentPromptText(target) : '',
      latestUserMessage('')
    ].some(value => !!String(value || '').trim());
  }

  function renderTarget() {
    const target = getTarget();
    const active = target.type === 'text' && target.nodeId;
    const taskContext = activeH3TaskContext(target);
    const modeCopy = taskModeCopy();
    const nodes = getTextNodes();
    if (els.deskPromptDrawerTarget) els.deskPromptDrawerTarget.textContent = active ? target.label : '未选择文本节点';
    if (els.deskPromptDrawerMeta) {
      els.deskPromptDrawerMeta.textContent = taskContext
        ? `MiniMax H3 · ${taskContext.mode} · ${taskContext.duration_seconds}s · ${taskContext.aspect_ratio}`
        : (active ? modeCopy.meta : `${modeCopy.meta} · 无需文本节点`);
    }
    if (els.deskPromptNodeSelect) {
      els.deskPromptNodeSelect.innerHTML = [
        `<option value="">${nodes.length ? '不绑定文本节点' : '画布中没有文本节点'}</option>`,
        ...nodes.map(node => `<option value="${escapeHtml(node.nodeId)}">${escapeHtml(node.alias || node.label || '文本节点')}</option>`)
      ].join('');
      els.deskPromptNodeSelect.value = active ? target.nodeId : '';
      els.deskPromptNodeSelect.disabled = nodes.length === 0;
    }
  }

  function renderMessages() {
    if (!els.deskPromptChatMessages) return;
    if (state.messages.length) {
      const startIndex = Math.max(0, state.messages.length - 10);
      els.deskPromptChatMessages.innerHTML = chatMessagesHtml(state.messages.slice(startIndex), startIndex);
      els.deskPromptChatMessages.scrollTop = els.deskPromptChatMessages.scrollHeight;
      return;
    }
    const modeCopy = taskModeCopy();
    let createButton = '';
    if (!hasTextTarget()) {
      createButton = '<button type="button" data-prompt-create-text title="可选">新建文本节点</button>';
    }
    els.deskPromptChatMessages.innerHTML = `
      <div class="desk-prompt-chat__empty">
        <span>${escapeHtml(modeCopy.emptyMessage)}</span>
        ${createButton}
      </div>
    `;
  }

  function chatMessagesHtml(messages, startIndex = 0) {
    return messages.map((item, index) => `
      <div class="desk-prompt-chat__message is-${escapeHtml(item.role)} ${item.streaming ? 'is-streaming' : ''}" data-prompt-message-index="${startIndex + index}">
        <span>${escapeHtml(item.role === 'user' ? '你' : '助手')}</span>
        <p>${escapeHtml(item.text)}</p>
      </div>
    `).join('');
  }

  function modalChatHtml() {
    return state.messages.length
      ? chatMessagesHtml(state.messages, 0)
      : '<div class="desk-prompt-chat__empty">还没有讨论记录。</div>';
  }

  function isH3PromptCandidate(item = {}) {
    const meta = item.meta && typeof item.meta === 'object' ? item.meta : {};
    return /^h3(?:_|$)/i.test(String(item.kind || ''))
      || String(item.kind || '').toLowerCase().includes('minimax_h3')
      || String(item.mode || meta.mode || '').toUpperCase() === 'I2VA';
  }

  function candidateTextForLanguage(item = {}, language = 'zh') {
    const canonical = String(item.text_en || item.textEn || item.text || '').trim();
    if (language === 'en') return canonical;
    if (!isH3PromptCandidate(item)) return String(item.text || canonical).trim();
    return String(
      item.text_zh
      || item.textZh
      || item.display_text
      || item.displayText
      || canonical
    ).trim();
  }

  function candidateLanguageSwitchHtml(item = {}, index = 0, options = {}) {
    if (!options.forceExpanded || !isH3PromptCandidate(item)) return '';
    const textZh = candidateTextForLanguage(item, 'zh');
    const textEn = candidateTextForLanguage(item, 'en');
    if (!textZh || !textEn || textZh === textEn) return '';
    const language = options.displayLanguage === 'en' ? 'en' : 'zh';
    return `
      <span class="desk-prompt-candidate__language-switch" role="radiogroup" aria-label="提示词显示语言">
        <button type="button" data-candidate-language="zh" data-candidate-index="${index}" role="radio" aria-checked="${language === 'zh' ? 'true' : 'false'}" class="${language === 'zh' ? 'is-active' : ''}" title="显示中文">中文</button>
        <button type="button" data-candidate-language="en" data-candidate-index="${index}" role="radio" aria-checked="${language === 'en' ? 'true' : 'false'}" class="${language === 'en' ? 'is-active' : ''}" title="Display English">EN</button>
      </span>
    `;
  }

  function candidateAdapterMetaHtml(item = {}) {
    const meta = item.meta && typeof item.meta === 'object' ? item.meta : {};
    const provenance = item.provenance && typeof item.provenance === 'object'
      ? item.provenance
      : (meta.provenance && typeof meta.provenance === 'object' ? meta.provenance : {});
    const isH3 = isH3PromptCandidate(item);
    if (isH3) {
      const validation = item.validation && typeof item.validation === 'object'
        ? item.validation
        : (meta.validation && typeof meta.validation === 'object' ? meta.validation : {});
      const warnings = Array.isArray(validation.warnings) ? validation.warnings : [];
      const errors = Array.isArray(validation.errors) ? validation.errors : [];
      const skill = String(
        item.skill
        || meta.skill
        || meta.skill_id
        || provenance.skill_id
        || provenance.skill
        || 'MiniMax 官方 Skill'
      ).trim();
      const mode = String(item.mode || meta.mode || 'I2VA').trim().toUpperCase();
      const duration = Number(meta.duration_seconds || meta.timeline_end_seconds || 0);
      const shotCount = Number(meta.shot_count || 0);
      const validationLabel = validation.valid === true
        ? (warnings.length ? `校验通过（${warnings.length} 条提示）` : '校验通过')
        : (validation.valid === false
          ? `校验未通过${errors.length ? `（${errors.length} 项）` : ''}`
          : (warnings.length ? `校验提示 ${warnings.length}` : '已校验'));
      const timelineLabel = duration > 0
        ? `${Number.isInteger(duration) ? duration : duration.toFixed(2)}s${shotCount > 0 ? ` · ${shotCount} Shot` : ''}`
        : '';
      return `<small class="desk-prompt-candidate__meta">${[skill, mode, timelineLabel, validationLabel].filter(Boolean).map(escapeHtml).join(' · ')}</small>`;
    }
    const hasAdapterMeta = item.kind === 'safe_rewrite' || item.risk_score !== undefined || item.riskScore !== undefined;
    if (!hasAdapterMeta) return '';
    const taskType = item.task_type || item.taskType || {};
    const taskLabel = typeof taskType === 'string' ? taskType : (taskType.label || taskType.id || '');
    const changedCount = Array.isArray(item.changed_terms) ? item.changed_terms.length : (Array.isArray(item.changedTerms) ? item.changedTerms.length : 0);
    const warningCount = Array.isArray(item.warnings) ? item.warnings.length : 0;
    const riskScore = item.risk_score ?? item.riskScore ?? 0;
    const riskLevel = item.risk_level || item.riskLevel || '';
    const parts = [
      `风险 ${riskScore}${riskLevel ? `/${riskLevel}` : ''}`,
      taskLabel,
      changedCount ? `替换 ${changedCount}` : '',
      warningCount ? `提示 ${warningCount}` : ''
    ].filter(Boolean);
    return parts.length ? `<small class="desk-prompt-candidate__meta">${parts.map(escapeHtml).join(' · ')}</small>` : '';
  }

  function candidateCard(item, index, canApply = true, options = {}) {
    const forceExpanded = !!options.forceExpanded;
    const alwaysExpanded = forceExpanded || isH3PromptCandidate(item);
    const expanded = alwaysExpanded || state.expandedCandidateId === (item.id || String(index));
    const applyLabel = hasTextTarget() ? '应用到文本节点' : '新建文本节点';
    const displayLanguage = forceExpanded
      ? (options.displayLanguage === 'en' ? 'en' : 'zh')
      : (isH3PromptCandidate(item) ? 'zh' : 'en');
    const displayText = candidateTextForLanguage(item, displayLanguage);
    const languageSwitch = candidateLanguageSwitchHtml(item, index, {
      forceExpanded,
      displayLanguage
    });
    return `
      <article class="desk-prompt-candidate ${expanded ? 'is-expanded' : ''}" data-candidate-index="${index}">
        <header>
          <strong>${escapeHtml(item.label || '提示词版本')}</strong>
          <span class="desk-prompt-candidate__head-tools">
            ${languageSwitch}
            ${item.badge ? `<em>${escapeHtml(item.badge)}</em>` : ''}
          </span>
        </header>
        ${candidateAdapterMetaHtml(item)}
        <p class="desk-prompt-candidate__prompt" data-prompt-language="${escapeHtml(displayLanguage)}">${escapeHtml(displayText)}</p>
        <div>
          ${alwaysExpanded ? '' : `<button type="button" data-candidate-action="toggle" data-candidate-index="${index}" aria-expanded="${expanded ? 'true' : 'false'}">${expanded ? '收起' : '展开'}</button>`}
          <button type="button" data-candidate-action="apply-text" data-candidate-index="${index}" ${canApply ? '' : 'disabled'}>${applyLabel}</button>
          <button type="button" data-candidate-action="copy" data-candidate-index="${index}" data-candidate-view-language="${escapeHtml(displayLanguage)}">复制</button>
          <button type="button" data-candidate-action="save-style" data-candidate-index="${index}">另存风格</button>
        </div>
      </article>
    `;
  }

  function analysisModuleCard(module = {}) {
    const kind = module.kind || '';
    const text = module.text || (module.json ? JSON.stringify(module.json, null, 2) : '');
    const isJson = kind === 'json' || module.id === 'full_json';
    return `
      <article class="desk-prompt-analysis-module is-${escapeHtml(kind || 'text')}">
        <header>
          <strong>${escapeHtml(module.title || '分析模块')}</strong>
          ${module.editable ? '<em>可编辑</em>' : ''}
        </header>
        ${isJson ? `<pre>${escapeHtml(text)}</pre>` : `<p>${escapeHtml(text || '暂无内容')}</p>`}
      </article>
    `;
  }

  function analysisModulesHtml(options = {}) {
    const includeMain = !!options.includeMain;
    const modules = state.analysisModules.filter(module => includeMain || module.id !== 'main');
    if (!modules.length) return '';
    return modules.map(module => analysisModuleCard(module)).join('');
  }

  function normalizeTextRegions(regions = []) {
    if (!Array.isArray(regions)) return [];
    return regions
      .map((region, index) => {
        const id = String(region?.id || `T${index + 1}`).trim().toUpperCase();
        const text = String(region?.text || region?.original_text || region?.originalText || '').trim();
        if (!text) return null;
        return {
          id: /^T\d+$/.test(id) ? id : `T${index + 1}`,
          text,
          role: String(region?.role || region?.label || '文字').trim(),
          position: String(region?.position || region?.placement || '').trim(),
          anchor: String(region?.anchor || '').trim(),
          alignment: String(region?.alignment || region?.align || '').trim(),
          size: String(region?.size || region?.scale || '').trim(),
          style: String(region?.style || region?.font_style || region?.fontStyle || '').trim()
        };
      })
      .filter(Boolean);
  }

  function cleanOcrText(text = '') {
    const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
    if (lines[0]?.trim().startsWith('```')) lines.shift();
    if (lines[lines.length - 1]?.trim().startsWith('```')) lines.pop();
    if (lines[0]?.trim().toLowerCase() === 'markdown') lines.shift();
    return lines.join('\n').trim();
  }

  function formatTextRegionsForEditor(regions = [], fallbackText = '') {
    const normalized = normalizeTextRegions(regions);
    if (!normalized.length) return cleanOcrText(fallbackText);
    return normalized.map(region => {
      const meta = [
        region.role,
        region.position ? `位置：${region.position}` : '',
        region.alignment ? `对齐：${region.alignment}` : '',
        region.size ? `字号：${region.size}` : '',
        region.style ? `样式：${region.style}` : ''
      ].filter(Boolean).join('｜');
      return `${region.id}｜${meta}\n${region.text}`.trim();
    }).join('\n\n');
  }

  function parseEditedTextRegions(text = '', regions = []) {
    const cleaned = cleanOcrText(text);
    const normalized = normalizeTextRegions(regions);
    if (!cleaned) return [];
    const matches = Array.from(cleaned.matchAll(/(^|\n)(T\d+)\s*[｜|:：-]?\s*([^\n]*)\n([\s\S]*?)(?=\n\s*T\d+\s*[｜|:：-]?|\s*$)/g));
    if (matches.length) {
      return matches.map(match => {
        const id = String(match[2] || '').toUpperCase();
        const region = normalized.find(item => item.id === id) || { id };
        return {
          ...region,
          id,
          text: String(match[4] || '').trim()
        };
      }).filter(item => item.text);
    }
    const blocks = cleaned.split(/\n\s*\n+/).map(item => item.trim()).filter(Boolean);
    return blocks.map((block, index) => ({
      ...(normalized[index] || { id: `T${index + 1}`, role: '文字' }),
      text: block
    }));
  }

  function textRegionPlacementPrompt() {
    const regions = parseEditedTextRegions(state.ocrText, state.textRegions);
    if (!regions.length) return '';
    const lines = regions.map(region => {
      const meta = [
        region.position ? `位置：${region.position}` : '',
        region.alignment ? `对齐：${region.alignment}` : '',
        region.size ? `字号：${region.size}` : '',
        region.style ? `样式：${region.style}` : '',
        region.role ? `用途：${region.role}` : ''
      ].filter(Boolean).join('；');
      return `${region.id}：${meta || '按该槽位位置描述'}；文字内容：「${region.text}」`;
    });
    return [
      '生成图中文字，并严格按以下文字槽位映射；每个槽位只使用对应文字内容，不要新增其它可读文字。',
      ...lines
    ].join('\n');
  }

  function textBaseForKeepText(base = '') {
    return String(base || '')
      .replace(/画面无可读文字。?/g, '')
      .replace(/不要生成任何可读文字[^。\n]*。?/g, '')
      .trim();
  }

  function stripTrailingNegativePrompt(text = '') {
    return String(text || '')
      .replace(/\s*(?:^|\n+)负面(?:约束|提示词)?[：:][\s\S]*$/u, '')
      .trim();
  }

  function negativePromptForCandidate(candidate = {}) {
    if (candidate.kind !== 'image_analysis_main') return '';
    return String(state.imageAnalysis?.prompt_blocks?.negative_prompt || '').trim();
  }

  function candidateTextForTextNode(candidate = {}) {
    const text = String(candidate.text || '').trim();
    const negativePrompt = negativePromptForCandidate(candidate);
    if (!negativePrompt) return text;
    const base = stripTrailingNegativePrompt(text) || text;
    if (base.includes(negativePrompt)) return base;
    return `${base}\n\n负面约束：${negativePrompt}`.trim();
  }

  function updateImageTextCandidate() {
    const candidate = state.candidates.find(item => item.kind === 'image_analysis_main');
    if (!candidate) return;
    const rawBase = String(candidate.base_text || candidate.baseText || candidate.text || '').trim();
    const base = stripTrailingNegativePrompt(rawBase) || rawBase;
    candidate.base_text = base;
    const placementPrompt = textRegionPlacementPrompt();
    if (state.keepImageText && placementPrompt) {
      candidate.text = `${textBaseForKeepText(base) || base}\n\n${placementPrompt}`;
      candidate.badge = '保留文字';
    } else {
      candidate.text = base;
      candidate.badge = '默认不含文字';
    }
  }

  function renderCandidates() {
    if (!els.deskPromptCandidateList) return;
    const showsCurrentMode = !state.resultMode || state.resultMode === state.taskMode;
    if (state.candidates.length) {
      if (showsCurrentMode) {
        els.deskPromptCandidateList.innerHTML = [
          ...state.candidates.map((candidate, index) => candidateCard(candidate, index)),
          analysisModulesHtml()
        ].filter(Boolean).join('');
        return;
      }
    }
    if (showsCurrentMode && state.analysisModules.length) {
      els.deskPromptCandidateList.innerHTML = analysisModulesHtml({ includeMain: true });
      return;
    }
    if (!hasTextTarget()) {
      els.deskPromptCandidateList.innerHTML = `<div class="desk-prompt-candidates__empty">${escapeHtml(taskModeCopy().emptyCandidate)}</div>`;
      return;
    }
    els.deskPromptCandidateList.innerHTML = `<div class="desk-prompt-candidates__empty">${escapeHtml(taskModeCopy().emptyCandidate)}</div>`;
  }

  function modalCandidatesHtml() {
    const showsCurrentMode = !state.resultMode || state.resultMode === state.taskMode;
    if (showsCurrentMode && (state.candidates.length || state.analysisModules.length)) {
      const candidateHtml = state.candidates
        .map((candidate, index) => candidateCard(candidate, index, true, {
          forceExpanded: true,
          displayLanguage: state.modalCandidateLanguage
        }))
        .join('');
      const analysisControls = state.analysisModules.length ? `
        <section class="desk-prompt-analysis-editor">
          <label class="desk-prompt-image-switch desk-prompt-image-switch--text">
            <input type="checkbox" data-analysis-keep-text ${state.keepImageText ? 'checked' : ''}>
            <span></span>
            <em>保留图中文字</em>
          </label>
          <textarea data-analysis-ocr-text placeholder="这里编辑 OCR 文字，打开保留图中文字后会追加到主候选。">${escapeHtml(state.ocrText || '')}</textarea>
        </section>
      ` : '';
      return [
        candidateHtml,
        analysisControls,
        analysisModulesHtml({ includeMain: true })
      ].filter(Boolean).join('');
    }
    return `<div class="desk-prompt-candidates__empty">${escapeHtml(taskModeCopy().emptyCandidate)}</div>`;
  }

  function renderBusy() {
    syncImageAttachmentsFromEditor();
    const busy = state.busyChat || state.busyVersions;
    const imageMode = isImageAnalysisMode();
    const modeCopy = taskModeCopy();
    const target = getTarget();
    const canGenerate = hasGenerationSeed(target);
    if (els.deskPromptTaskMode) {
      els.deskPromptTaskMode.dataset.mode = state.taskMode;
      els.deskPromptTaskMode.querySelectorAll('[data-prompt-task-mode]').forEach(button => {
        const active = button.dataset.promptTaskMode === state.taskMode;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-checked', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
        button.disabled = busy;
      });
    }
    if (els.deskPromptImageAnalysisToggle) {
      els.deskPromptImageAnalysisToggle.checked = imageMode;
      els.deskPromptImageAnalysisToggle.disabled = busy;
    }
    if (els.deskPromptChatInput) {
      els.deskPromptChatInput.dataset.placeholder = modeCopy.placeholder;
      els.deskPromptChatInput.setAttribute('aria-label', modeCopy.placeholder);
    }
    if (els.deskPromptCandidatesTitle) {
      els.deskPromptCandidatesTitle.textContent = modeCopy.candidateTitle;
    }
    if (els.deskPromptChatSend) {
      els.deskPromptChatSend.disabled = busy || (imageMode ? !state.imageAttachments.length : !editorText().trim());
      els.deskPromptChatSend.textContent = state.busyChat
        ? (imageMode ? '分析中' : '思考中')
        : modeCopy.sendLabel;
      els.deskPromptChatSend.title = modeCopy.sendTitle;
    }
    if (els.deskPromptGenerateVersions) {
      els.deskPromptGenerateVersions.hidden = imageMode;
      els.deskPromptGenerateVersions.disabled = busy || imageMode || !canGenerate;
      els.deskPromptGenerateVersions.textContent = state.busyVersions
        ? '生成中'
        : modeCopy.generateLabel;
      els.deskPromptGenerateVersions.title = isVideoPromptMode()
        ? '调用 MiniMax H3 官方 Skill 编译视频提示词'
        : '生成图片提示词版本';
      els.deskPromptGenerateVersions.parentElement?.classList.toggle('is-single-action', imageMode);
      if (els.deskPromptGenerateVersions.parentElement) {
        els.deskPromptGenerateVersions.parentElement.dataset.taskMode = state.taskMode;
      }
    }
    if (els.deskPromptChatRefresh) {
      els.deskPromptChatRefresh.disabled = busy || (imageMode ? !state.imageAttachments.length : !canGenerate);
      els.deskPromptChatRefresh.textContent = (state.busyChat || state.busyVersions) ? '生成中' : '重新生成';
    }
  }

  function render() {
    renderTarget();
    renderMessages();
    updateImageTextCandidate();
    renderImageAttachments();
    renderCandidates();
    renderModal();
    renderBusy();
    schedulePromptDrawerSessionSave();
  }

  function renderModal() {
    if (!els.deskPromptModal || !state.modalMode) return;
    if (els.deskPromptModalTitle) {
      els.deskPromptModalTitle.textContent = state.modalMode === 'chat'
        ? '讨论记录'
        : taskModeCopy().candidateTitle;
    }
    if (!els.deskPromptModalContent) return;
    els.deskPromptModalContent.classList.toggle('is-chat', state.modalMode === 'chat');
    els.deskPromptModalContent.classList.toggle('is-versions', state.modalMode === 'versions');
    els.deskPromptModalContent.innerHTML = state.modalMode === 'chat' ? modalChatHtml() : modalCandidatesHtml();
  }

  function setModalCandidateLanguage(language) {
    const nextLanguage = language === 'en' ? 'en' : 'zh';
    if (state.modalCandidateLanguage === nextLanguage) return;
    const scrollTop = els.deskPromptModalContent?.scrollTop || 0;
    state.modalCandidateLanguage = nextLanguage;
    renderModal();
    if (els.deskPromptModalContent) els.deskPromptModalContent.scrollTop = scrollTop;
  }

  function openModal(mode) {
    state.modalMode = mode;
    if (mode === 'versions') state.modalCandidateLanguage = 'zh';
    state.modalOffsetX = 0;
    state.modalOffsetY = 0;
    applyModalPosition();
    if (els.deskPromptModal) {
      els.deskPromptModal.hidden = false;
      els.deskPromptModal.classList.add('is-open');
    }
    renderModal();
    schedulePromptDrawerSessionSave();
    window.setTimeout(() => els.deskPromptModalClose?.focus({ preventScroll: true }), 30);
  }

  function closeModal() {
    state.modalMode = '';
    stopModalDrag();
    if (els.deskPromptModal) {
      els.deskPromptModal.classList.remove('is-open');
      els.deskPromptModal.hidden = true;
    }
    if (els.deskPromptModalContent) els.deskPromptModalContent.innerHTML = '';
    schedulePromptDrawerSessionSave();
  }

  function applyModalPosition() {
    if (!els.deskPromptModalPanel) return;
    const x = Math.round(state.modalOffsetX || 0);
    const y = Math.round(state.modalOffsetY || 0);
    els.deskPromptModalPanel.style.transform = x || y ? `translate3d(${x}px, ${y}px, 0)` : '';
  }

  function clampModalOffset(rawX, rawY) {
    const rect = modalDrag.startRect;
    if (!rect) return { x: rawX, y: rawY };
    const margin = 12;
    const minX = modalDrag.startOffsetX + margin - rect.left;
    const maxX = modalDrag.startOffsetX + window.innerWidth - margin - rect.right;
    const minY = modalDrag.startOffsetY + margin - rect.top;
    const maxY = modalDrag.startOffsetY + window.innerHeight - margin - rect.bottom;
    return {
      x: Math.min(Math.max(rawX, minX), maxX),
      y: Math.min(Math.max(rawY, minY), maxY)
    };
  }

  function startModalDrag(event) {
    if (!els.deskPromptModalPanel || !state.modalMode || event.button !== 0) return;
    if (event.target.closest('button, input, select, textarea, a')) return;
    modalDrag.active = true;
    modalDrag.pointerId = event.pointerId;
    modalDrag.startClientX = event.clientX;
    modalDrag.startClientY = event.clientY;
    modalDrag.startOffsetX = state.modalOffsetX || 0;
    modalDrag.startOffsetY = state.modalOffsetY || 0;
    modalDrag.startRect = els.deskPromptModalPanel.getBoundingClientRect();
    els.deskPromptModalPanel.classList.add('is-dragging');
    els.deskPromptModalDragHandle?.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function handleModalDrag(event) {
    if (!modalDrag.active || event.pointerId !== modalDrag.pointerId) return;
    const next = clampModalOffset(
      modalDrag.startOffsetX + event.clientX - modalDrag.startClientX,
      modalDrag.startOffsetY + event.clientY - modalDrag.startClientY
    );
    state.modalOffsetX = next.x;
    state.modalOffsetY = next.y;
    applyModalPosition();
    event.preventDefault();
  }

  function stopModalDrag(event = null) {
    if (!modalDrag.active) return;
    if (event && event.pointerId !== modalDrag.pointerId) return;
    els.deskPromptModalPanel?.classList.remove('is-dragging');
    if (event) {
      els.deskPromptModalDragHandle?.releasePointerCapture?.(event.pointerId);
    }
    modalDrag.active = false;
    modalDrag.pointerId = null;
    modalDrag.startRect = null;
  }

  function ensureTextTarget() {
    if (hasTextTarget()) return true;
    window.DesktopResults?.showTransientMessage?.('请先选择文本节点，或新建文本节点。', 'warning');
    render();
    return false;
  }

  function latestUserMessage(fallback = '') {
    return state.messages.filter(item => item.role === 'user').slice(-1)[0]?.text || fallback;
  }

  function resolveAssistantTypingIdle() {
    const resolvers = streamTyping.idleResolvers.splice(0);
    resolvers.forEach(resolve => resolve());
  }

  function clearAssistantTypingTimer() {
    if (!streamTyping.timer) return;
    window.clearInterval(streamTyping.timer);
    streamTyping.timer = 0;
  }

  function updateAssistantMessageDom(index) {
    const message = state.messages[index];
    if (!message) return;
    document.querySelectorAll(`[data-prompt-message-index="${index}"] p`).forEach(node => {
      node.textContent = message.text || '';
    });
    if (els.deskPromptChatMessages) {
      els.deskPromptChatMessages.scrollTop = els.deskPromptChatMessages.scrollHeight;
    }
    if (state.modalMode === 'chat' && els.deskPromptModalContent) {
      els.deskPromptModalContent.scrollTop = els.deskPromptModalContent.scrollHeight;
    }
  }

  function appendAssistantStreamText(index, text) {
    if (!state.messages[index]) return;
    state.messages[index].text = `${state.messages[index].text || ''}${text}`;
    updateAssistantMessageDom(index);
  }

  function runAssistantTypingFrame() {
    if (!streamTyping.queue.length) {
      clearAssistantTypingTimer();
      resolveAssistantTypingIdle();
      return;
    }
    appendAssistantStreamText(streamTyping.messageIndex, streamTyping.queue.shift());
  }

  function resetAssistantTyping(index) {
    clearAssistantTypingTimer();
    streamTyping.messageIndex = index;
    streamTyping.queue = [];
    resolveAssistantTypingIdle();
  }

  function enqueueAssistantTyping(index, text) {
    const chars = Array.from(String(text || ''));
    if (!chars.length) return;
    if (streamTyping.messageIndex !== index) resetAssistantTyping(index);
    streamTyping.queue.push(...chars);
    if (!streamTyping.timer) {
      streamTyping.timer = window.setInterval(runAssistantTypingFrame, 18);
    }
  }

  function waitAssistantTypingIdle(index) {
    if (streamTyping.messageIndex !== index || (!streamTyping.queue.length && !streamTyping.timer)) {
      return Promise.resolve();
    }
    return new Promise(resolve => {
      streamTyping.idleResolvers.push(resolve);
    });
  }

  function stopAssistantTyping(index, options = {}) {
    if (streamTyping.messageIndex !== index) return;
    if (options.flush && streamTyping.queue.length) {
      appendAssistantStreamText(index, streamTyping.queue.join(''));
    }
    clearAssistantTypingTimer();
    streamTyping.queue = [];
    streamTyping.messageIndex = -1;
    resolveAssistantTypingIdle();
  }

  async function imageAttachmentPayloads(options = {}) {
    syncImageAttachmentsFromEditor();
    const items = state.imageAttachments
      .filter(item => attachmentMediaKind(item) === 'image')
      .slice(0, options.limit || 1);
    const payloads = [];
    for (const item of items) {
      let dataUrl = item.dataUrl || item.imageData || '';
      const source = item.imageUrl || item.url || '';
      if (!dataUrl && source && window.DesktopApi?.imageUrlToDataUri) {
        dataUrl = await window.DesktopApi.imageUrlToDataUri(source);
      }
      if (!dataUrl && source?.startsWith('data:image/')) dataUrl = source;
      if (options.strict && dataUrl && !dataUrl.startsWith('data:image/')) {
        dataUrl = await window.DesktopApi?.imageUrlToDataUri?.(dataUrl);
      }
      if (options.strict && !String(dataUrl || '').startsWith('data:image/')) {
        throw new Error(`无法读取引用图片 ${item.id}，请重新用 @ 选择图片。`);
      }
      if (!dataUrl) continue;
      payloads.push({
        id: item.id,
        label: item.label,
        dataUrl,
        imageData: dataUrl,
        sourceNodeId: item.sourceNodeId || '',
        mimeType: item.mimeType || 'image/png',
        role: item.role || 'primary'
      });
    }
    return payloads;
  }

  async function videoAttachmentPayloads(options = {}) {
    syncImageAttachmentsFromEditor();
    const items = state.imageAttachments
      .filter(item => attachmentMediaKind(item) === 'video')
      .slice(0, options.limit || MAX_VIDEO_ATTACHMENTS);
    if (!items.length) return [];
    if (!window.DesktopPromptMedia?.sampleVideoReferences) {
      throw new Error('视频抽帧模块尚未加载，请刷新页面后重试。');
    }
    return window.DesktopPromptMedia.sampleVideoReferences(items, {
      onProgress(progress) {
        const label = progress.video?.label || `视频 ${progress.videoIndex || 1}`;
        window.DesktopResults?.showTransientMessage?.(
          `正在抽取 ${label}：${progress.completed}/${progress.total} 帧`,
          'info'
        );
      }
    });
  }

  function h3CompileReference(image = {}) {
    const dataUrl = String(image.dataUrl || image.data_url || image.imageData || '').trim();
    if (!dataUrl) return null;
    return {
      id: String(image.id || 'first_frame'),
      role: 'first_frame',
      label: String(image.label || image.id || '首帧'),
      source_node_id: String(image.sourceNodeId || image.source_node_id || ''),
      mime_type: String(image.mimeType || image.mime_type || 'image/png'),
      data_url: dataUrl
    };
  }

  async function h3CompileFirstFrame(taskContext = {}) {
    const mentioned = await imageAttachmentPayloads();
    if (mentioned.length) return h3CompileReference(mentioned[0]);
    const sourceNodeId = String(taskContext.first_frame_node_id || '').trim();
    if (!sourceNodeId) return null;
    const image = getImageNodes().find(item => String(item.nodeId || item.sourceNodeId || item.id || '') === sourceNodeId);
    if (!image) return null;
    let dataUrl = String(image.dataUrl || image.imageData || '').trim();
    const source = String(image.imageUrl || image.url || '').trim();
    if (!dataUrl && source && window.DesktopApi?.imageUrlToDataUri) {
      dataUrl = await window.DesktopApi.imageUrlToDataUri(source);
    }
    return h3CompileReference({
      ...image,
      id: image.id || sourceNodeId,
      sourceNodeId,
      dataUrl
    });
  }

  function normalizeH3PromptCandidates(result = {}, taskContext = {}) {
    const rootValidation = result.validation && typeof result.validation === 'object' ? result.validation : {};
    const rootProvenance = result.provenance && typeof result.provenance === 'object' ? result.provenance : {};
    const rawCandidates = Array.isArray(result.candidates) && result.candidates.length
      ? result.candidates
      : (result.candidate ? [result.candidate] : (result.prompt ? [{
          text: result.prompt,
          text_en: result.prompt_en || result.prompt,
          text_zh: result.prompt_zh || ''
        }] : []));
    return rawCandidates
      .map((candidate, index) => {
        const textEn = String(
          candidate?.text_en
          || candidate?.textEn
          || candidate?.text
          || candidate?.prompt
          || result.prompt_en
          || result.prompt
          || ''
        ).trim();
        const textZh = String(
          candidate?.text_zh
          || candidate?.textZh
          || candidate?.display_text
          || candidate?.displayText
          || result.prompt_zh
          || ''
        ).trim();
        if (!textEn) return null;
        const candidateMeta = candidate.meta && typeof candidate.meta === 'object' ? candidate.meta : {};
        const validation = candidate.validation && typeof candidate.validation === 'object'
          ? candidate.validation
          : (candidateMeta.validation && typeof candidateMeta.validation === 'object' ? candidateMeta.validation : rootValidation);
        const provenance = candidate.provenance && typeof candidate.provenance === 'object'
          ? candidate.provenance
          : (candidateMeta.provenance && typeof candidateMeta.provenance === 'object' ? candidateMeta.provenance : rootProvenance);
        const mode = String(candidate.mode || candidateMeta.mode || result.mode || taskContext.mode || 'I2VA').toUpperCase();
        const skill = String(
          candidate.skill
          || candidateMeta.skill
          || candidateMeta.skill_id
          || provenance.skill_id
          || provenance.skill
          || 'MiniMax 官方 Skill'
        );
        return {
          ...candidate,
          id: candidate.id || `h3_prompt_${Date.now()}_${index + 1}`,
          kind: candidate.kind || 'h3_i2va',
          label: candidate.label || `MiniMax H3 · ${mode}`,
          badge: candidate.badge || 'H3',
          text: textEn,
          text_en: textEn,
          text_zh: textZh || textEn,
          display_text: textZh || textEn,
          mode,
          skill,
          validation,
          provenance,
          meta: {
            ...candidateMeta,
            mode,
            skill,
            duration_seconds: candidateMeta.duration_seconds ?? taskContext.duration_seconds,
            aspect_ratio: candidateMeta.aspect_ratio || taskContext.aspect_ratio,
            validation,
            provenance
          },
          adapter: {
            ...(candidate.adapter || {}),
            target_model: 'minimax_h3',
            mode,
            skill,
            validation,
            provenance
          }
        };
      })
      .filter(Boolean);
  }

  function normalizeAnalysisResult(result = {}) {
    const candidates = Array.isArray(result.candidates)
      ? result.candidates.filter(item => item?.text)
      : [result.candidate].filter(item => item?.text);
    state.candidates = candidates.map((candidate, index) => ({
      ...candidate,
      id: candidate.id || `image_analysis_candidate_${index + 1}`,
      base_text: candidate.base_text || candidate.baseText || candidate.text || ''
    }));
    state.imageAnalysis = result.analysis || null;
    const rawModules = Array.isArray(result.modules) ? result.modules : [];
    const ocrModule = rawModules.find(module => module.id === 'text_markdown');
    state.analysisModules = rawModules.filter(module => !HIDDEN_ANALYSIS_MODULE_IDS.has(module?.id));
    state.textRegions = normalizeTextRegions(result.analysis?.text_regions || result.analysis?.textRegions || []);
    state.ocrText = formatTextRegionsForEditor(state.textRegions, String(ocrModule?.text || result.analysis?.text_markdown || ''));
    state.keepImageText = false;
    const first = state.candidates[0];
    state.expandedCandidateId = first ? (first.id || '0') : '';
  }

  async function submitImageAnalysis(messageOverride = '') {
    const message = String(messageOverride || editorText() || '').trim();
    syncImageAttachmentsFromEditor();
    if (!state.imageAttachments.length) {
      window.DesktopResults?.showTransientMessage?.('请先用 @ 选择画布图片或视频节点。', 'warning');
      return;
    }
    state.busyChat = true;
    render();
    let images = [];
    let videos = [];
    try {
      images = await imageAttachmentPayloads();
      videos = await videoAttachmentPayloads();
    } catch (error) {
      state.busyChat = false;
      window.DesktopResults?.showError?.(error);
      render();
      return;
    }
    if (!images.length && !videos.length) {
      state.busyChat = false;
      window.DesktopResults?.showTransientMessage?.('请先用 @ 选择画布图片或视频节点。', 'warning');
      render();
      return;
    }
    const referencedIds = [...images, ...videos].map(item => item.id).join('、');
    state.messages.push({ role: 'user', text: message || `分析 ${referencedIds}` });
    render();
    try {
      const target = getTarget();
      const analysisPayload = {
        message,
        images,
        videos,
        target: target?.type === 'text' ? target : {},
        style: {},
        keep_text: false
      };
      const result = videos.length
        ? await DesktopApi.analyzePromptVideo(analysisPayload)
        : await DesktopApi.analyzePromptImage(analysisPayload);
      normalizeAnalysisResult(result);
      state.resultMode = 'image_analysis';
      persistPromptVersions(state.candidates, {
        message: message || (videos.length ? '视频分析' : '图片分析'),
        target: target?.type === 'text' ? target : {},
        style: {}
      });
      state.messages.push({
        role: 'assistant',
        text: `${videos.length ? '视频' : '图片'}分析完成，已生成 ${state.candidates.length || 1} 个主候选和 ${state.analysisModules.length} 个结构化模块。`
      });
      clearEditor({ keepAttachments: true });
      closeImageMentionMenu();
      window.DesktopResults?.showTransientMessage?.(`${videos.length ? '视频' : '图片'}分析已完成。`, 'success');
    } catch (error) {
      const errorMessage = error?.message || String(error || '媒体分析失败');
      state.messages.push({ role: 'assistant', text: `媒体分析失败：${errorMessage}` });
      if (window.DesktopResults?.showTransientMessage) {
        window.DesktopResults.showTransientMessage(`媒体分析失败：${errorMessage}`, 'error');
      } else {
        window.DesktopResults?.showError?.(error);
      }
    } finally {
      state.busyChat = false;
      render();
    }
  }

  async function submitAssistantChat(messageOverride = '') {
    if (isImageAnalysisMode()) {
      await submitImageAnalysis(messageOverride);
      return;
    }
    const target = getTarget();
    const targetPayload = target?.type === 'text' ? target : {};
    const message = String(messageOverride || editorText() || '').trim();
    const prompt = String(target?.type === 'text' ? currentPromptText(target) : '').trim();
    if (!message) {
      window.DesktopResults?.showTransientMessage?.('请输入要讨论的方向。', 'warning');
      return;
    }
    state.busyChat = true;
    render();
    let images;
    let videos;
    try {
      images = (await imageAttachmentPayloads({ limit: MAX_IMAGE_ATTACHMENTS, strict: true })).map(item => ({
        id: item.id,
        label: item.label,
        data_url: item.dataUrl,
        source_node_id: item.sourceNodeId,
        mime_type: item.mimeType
      }));
      videos = await videoAttachmentPayloads({ limit: MAX_VIDEO_ATTACHMENTS });
    } catch (error) {
      state.busyChat = false;
      window.DesktopResults?.showError?.(error);
      render();
      return;
    }
    state.messages.push({ role: 'user', text: message });
    state.messages.push({ role: 'assistant', text: '', streaming: true });
    const assistantIndex = state.messages.length - 1;
    resetAssistantTyping(assistantIndex);
    render();
    let streamedText = '';
    let streamStarted = false;
    syncImageAttachmentsFromEditor();
    const taskContext = activeH3TaskContext(target);
    const payload = {
      message,
      prompt,
      images,
      videos,
      target: targetPayload,
      style: {},
      history: state.messages.slice(0, -2).slice(-8),
      ...(taskContext ? { task_context: taskContext } : {})
    };
    try {
      const result = await DesktopApi.promptAssistantChatStream(payload, {
        onDelta(text) {
          if (!text) return;
          streamStarted = true;
          streamedText += text;
          enqueueAssistantTyping(assistantIndex, text);
        }
      });
      const finalText = String(result?.reply || result?.message || streamedText || '我没有拿到有效回复。');
      if (finalText.startsWith(streamedText) && finalText.length > streamedText.length) {
        enqueueAssistantTyping(assistantIndex, finalText.slice(streamedText.length));
      }
      await waitAssistantTypingIdle(assistantIndex);
      if (state.messages[assistantIndex]?.text !== finalText) {
        state.messages[assistantIndex].text = finalText;
        updateAssistantMessageDom(assistantIndex);
      }
      if (state.messages[assistantIndex]) state.messages[assistantIndex].streaming = false;
      clearEditor({ keepAttachments: true });
    } catch (error) {
      if (!streamStarted) {
        stopAssistantTyping(assistantIndex);
        if (state.messages[assistantIndex]?.role === 'assistant') {
          state.messages.splice(assistantIndex, 1);
        }
        render();
        try {
          const result = await DesktopApi.promptAssistantChat(payload);
          state.messages.push({ role: 'assistant', text: result.reply || result.message || '我没有拿到有效回复。' });
          clearEditor({ keepAttachments: true });
        } catch (fallbackError) {
          window.DesktopResults?.showError?.(fallbackError);
        }
      } else {
        await waitAssistantTypingIdle(assistantIndex);
        if (state.messages[assistantIndex]) state.messages[assistantIndex].streaming = false;
        window.DesktopResults?.showError?.(error);
      }
    } finally {
      state.busyChat = false;
      render();
    }
  }

  async function generatePromptVersions(messageOverride = '') {
    if (isImageAnalysisMode()) {
      await submitImageAnalysis(messageOverride);
      return;
    }
    const target = getTarget();
    const targetPayload = target?.type === 'text' ? target : {};
    const prompt = String(target?.type === 'text' ? currentPromptText(target) : '').trim();
    const directMessage = String(messageOverride || editorText() || '').trim();
    const previousMessage = String(latestUserMessage('') || '').trim();
    if (!directMessage && !previousMessage && !prompt) {
      window.DesktopResults?.showTransientMessage?.('请先输入内容或讨论方向。', 'warning');
      return;
    }
    const message = directMessage || previousMessage || (isVideoPromptMode()
      ? '按当前内容生成 MiniMax H3 视频提示词。'
      : '按当前内容生成图片提示词。');
    state.busyVersions = true;
    render();
    try {
      syncImageAttachmentsFromEditor();
      const taskContext = activeH3TaskContext(target);
      let result;
      if (taskContext) {
        const firstFrame = await h3CompileFirstFrame(taskContext);
        result = await DesktopApi.compileVideoPrompt({
          target_model: 'minimax_h3',
          operation: 'compose',
          mode: 'I2VA',
          instruction: message,
          message,
          user_prompt: prompt,
          prompt,
          target: targetPayload,
          task_context: taskContext,
          duration_seconds: taskContext.duration_seconds,
          aspect_ratio: taskContext.aspect_ratio,
          first_frame: firstFrame,
          history: state.messages.slice(-8)
        });
        state.candidates = normalizeH3PromptCandidates(result, taskContext);
      } else {
        result = await DesktopApi.generatePromptVersions({
          message,
          prompt,
          target: targetPayload,
          style: {}
        });
        state.candidates = (Array.isArray(result.candidates) ? result.candidates : [])
          .filter(item => item?.kind !== 'original');
      }
      if (!state.candidates.length) throw new Error(taskContext ? 'H3 提示词编译没有返回有效结果。' : '没有返回有效提示词版本。');
      state.resultMode = taskContext ? 'video_prompt' : 'conversation';
      state.imageAnalysis = null;
      state.analysisModules = [];
      state.ocrText = '';
      state.textRegions = [];
      state.keepImageText = false;
      state.expandedCandidateId = '';
      persistPromptVersions(state.candidates, {
        message,
        target: targetPayload,
        style: {}
      });
      const validation = taskContext
        ? ((result.validation && typeof result.validation === 'object' ? result.validation : null)
          || (state.candidates[0]?.validation && typeof state.candidates[0].validation === 'object' ? state.candidates[0].validation : null))
        : null;
      const validationWarnings = Array.isArray(validation?.warnings) ? validation.warnings.length : 0;
      state.messages.push({
        role: 'assistant',
        text: taskContext
          ? (validation?.valid === false
            ? `H3 · I2VA 提示词已生成，但未通过格式校验。`
            : (validation?.valid === true
              ? `H3 · I2VA 提示词已生成${validationWarnings ? `，有 ${validationWarnings} 条校验提示` : '并通过校验'}。`
              : `H3 · I2VA 提示词已生成。`))
          : (result.warning ? `正式版本已生成，但润色链路有降级：${result.warning}` : `已生成 ${state.candidates.length} 个正式提示词版本。`)
      });
      clearEditor({ keepAttachments: true });
      window.DesktopResults?.showTransientMessage?.(taskContext ? 'H3 视频提示词已生成。' : '图片提示词已生成。', 'success');
    } catch (error) {
      window.DesktopResults?.showError?.(error);
    } finally {
      state.busyVersions = false;
      render();
    }
  }

  function prependCandidate(candidate) {
    if (!candidate?.text) return;
    const key = String(candidate.kind || '') + ':' + String(candidate.text || '');
    state.candidates = [
      candidate,
      ...state.candidates.filter(item => `${item.kind || ''}:${item.text || ''}` !== key)
    ].slice(0, 10);
  }

  async function generateSafeRewrite(messageOverride = '') {
    if (!ensureTextTarget()) return;
    state.taskMode = 'conversation';
    const target = getTarget();
    const prompt = String(currentPromptText(target) || '').trim();
    if (!prompt) {
      window.DesktopResults?.showTransientMessage?.('文本节点为空，无法生成安全审核版。', 'warning');
      return;
    }
    const message = String(messageOverride || '按安全审核版生成可直接投喂的改写提示词。').trim();
    state.busyVersions = true;
    state.messages.push({ role: 'user', text: message });
    render();
    try {
      const result = await DesktopApi.safeRewritePrompt({
        message,
        prompt,
        target,
        style: {}
      });
      const candidates = Array.isArray(result.candidates)
        ? result.candidates.filter(candidate => candidate?.text)
        : [result.candidate].filter(candidate => candidate?.text);
      if (!candidates.length) throw new Error('安全审核版没有返回有效提示词。');
      state.imageAnalysis = null;
      state.analysisModules = [];
      state.ocrText = '';
      state.textRegions = [];
      state.keepImageText = false;
      candidates.slice().reverse().forEach(candidate => prependCandidate(candidate));
      state.resultMode = 'conversation';
      persistPromptVersions(candidates, {
        message,
        target,
        style: {}
      });
      state.expandedCandidateId = candidates[0].id || 'safe_rewrite';
      state.messages.push({ role: 'assistant', text: '已生成安全审核版中文和英文提示词，可复制或应用到文本节点。' });
      clearEditor({ keepAttachments: true });
      window.DesktopResults?.showTransientMessage?.('安全审核版中文和英文提示词已生成。', 'success');
    } catch (error) {
      window.DesktopResults?.showError?.(error);
    } finally {
      state.busyVersions = false;
      render();
    }
  }

  async function generateSafeRewriteForTextNode(nodeId = '') {
    const target = window.DesktopCanvas?.getPromptTargetInfo?.(nodeId);
    if (target?.type !== 'text' || !target.nodeId) {
      window.DesktopResults?.showTransientMessage?.('请先选择有效文本节点。', 'warning');
      return;
    }
    state.boundTextNodeId = target.nodeId;
    setOpen(true);
    await generateSafeRewrite('按安全审核版生成可直接投喂的改写提示词。');
  }

  async function copyText(text) {
    await navigator.clipboard.writeText(text);
    window.DesktopResults?.showTransientMessage?.('提示词已复制。', 'success');
  }

  function persistPromptVersions(candidates, meta = {}) {
    if (!window.DesktopApi?.savePromptVersion) return;
    (candidates || []).forEach(candidate => {
      window.DesktopApi.savePromptVersion({
        type: candidate.kind || 'custom',
        label: candidate.label || candidate.kind || 'Prompt Version',
        text: candidate.text || '',
        source_message: meta.message || '',
        target: meta.target || {},
        style: meta.style || {},
        language: candidate.language || '',
        task_type: candidate.task_type || candidate.taskType || {},
        intent: candidate.intent || {},
        risk_score: candidate.risk_score ?? candidate.riskScore,
        risk_level: candidate.risk_level || candidate.riskLevel || '',
        risk_flags: candidate.risk_flags || candidate.riskFlags || [],
        changed_terms: candidate.changed_terms || candidate.changedTerms || [],
        warnings: candidate.warnings || [],
        adapter: candidate.adapter || {}
      }).catch(() => {});
    });
  }

  function candidateByIndex(index) {
    return state.candidates[Number(index || 0)] || null;
  }

  function collectStylePresetInput(seed = {}) {
    const name = window.prompt?.('风格名称', seed.name || seed.title || '自定义风格') || '';
    if (!name.trim()) return null;
    const description = window.prompt?.('风格说明', seed.description || '') ?? '';
    const promptStyle = window.prompt?.('风格提示词', seed.prompt_style || seed.promptTemplate || seed.positive_style || seed.text || '') || '';
    if (!promptStyle.trim()) return null;
    const avoid = window.prompt?.('避免项', seed.avoid || '') ?? '';
    const bestFor = window.prompt?.('适用场景', seed.best_for || seed.bestFor || '') ?? '';
    return {
      id: seed.id || '',
      name: name.trim(),
      description: String(description || '').trim(),
      positive_style: String(seed.positive_style || promptStyle).trim(),
      avoid: String(avoid || '').trim(),
      best_for: String(bestFor || '').trim(),
      prompt_style: promptStyle.trim(),
      tags: Array.isArray(seed.tags) ? seed.tags : [],
      source: seed.source || 'prompt_drawer'
    };
  }

  async function saveStylePresetDraft(seed = {}) {
    const payload = collectStylePresetInput(seed);
    if (!payload) return null;
    if (!payload.id) delete payload.id;
    if (window.DesktopApi?.saveStylePreset) {
      const result = await window.DesktopApi.saveStylePreset(payload);
      const presets = result?.preset ? [result.preset] : [];
      const merged = window.DesktopCanvas?.registerTextStylePresets?.([
        ...getStylePresets().filter(item => item.external),
        ...presets
      ]) || [];
      window.DesktopResults?.showTransientMessage?.(`风格预设已保存。当前 ${merged.length} 个预设。`, 'success');
      return result?.preset || null;
    }
    const preset = window.DesktopCanvas?.createTextStylePreset?.(payload.name, payload.prompt_style);
    window.DesktopResults?.showTransientMessage?.('风格预设已保存。', 'success');
    return preset || null;
  }

  async function handleCandidateAction(action, index, options = {}) {
    const candidate = candidateByIndex(index);
    if (!candidate?.text) return;
    if (action === 'toggle') {
      const key = candidate.id || String(index);
      state.expandedCandidateId = state.expandedCandidateId === key ? '' : key;
      renderCandidates();
      return;
    }
    if (action === 'copy') {
      const language = options.viewLanguage === 'en' ? 'en' : 'zh';
      await copyText(candidateTextForLanguage(candidate, language));
      return;
    }
    if (action === 'apply-text') {
      const textForNode = candidateTextForTextNode(candidate);
      const promptMeta = candidate.provenance || candidate.meta?.provenance || {};
      if (hasTextTarget()) {
        if (Object.keys(promptMeta).length) {
          window.DesktopCanvas?.fillPromptTarget?.(textForNode, { target: getTarget(), promptMeta });
        } else {
          window.DesktopCanvas?.fillPromptTarget?.(textForNode, { target: getTarget() });
        }
        window.DesktopResults?.showTransientMessage?.('已应用到文本节点。', 'success');
        return;
      }
      const nodeId = Object.keys(promptMeta).length
        ? window.DesktopCanvas?.createTextNodeWithText?.(textForNode, null, { promptMeta })
        : window.DesktopCanvas?.createTextNodeWithText?.(textForNode);
      if (!nodeId) {
        window.DesktopResults?.showTransientMessage?.('无法新建文本节点。', 'warning');
        return;
      }
      bindTextNode(nodeId);
      window.DesktopCanvas?.selectNode?.(nodeId);
      window.DesktopResults?.showTransientMessage?.('已新建文本节点并应用结果。', 'success');
      return;
    }
    if (action === 'save-style') {
      await saveStylePresetDraft({
        name: candidate.label || '自定义风格',
        prompt_style: candidate.text,
        positive_style: candidate.text,
        source: 'prompt_drawer_candidate'
      });
    }
  }

  async function syncProjectStylePresets() {
    if (!window.DesktopApi?.getStylePresets) return;
    try {
      const result = await window.DesktopApi.getStylePresets();
      window.DesktopCanvas?.registerTextStylePresets?.(result.presets || []);
    } catch (e) {}
  }

  function createTextNode() {
    const draft = editorText();
    const nodeId = window.DesktopCanvas?.createTextNodeWithText?.(draft);
    if (nodeId) bindTextNode(nodeId);
    clearEditor();
    window.DesktopResults?.showTransientMessage?.('已新建文本节点。', 'success');
    render();
  }

  function initPromptEditor() {
    if (!els.deskPromptChatInput || !window.DesktopPromptEditor?.create) return;
    promptEditor = window.DesktopPromptEditor.create({
      root: els.deskPromptChatInput,
      menu: els.deskPromptImageMenu,
      onMention({ query }) {
        state.mentionQuery = String(query || '');
        renderImageMentionMenu();
      },
      onMentionClose() {
        closeImageMentionMenu({ fromEditor: true });
      },
      onChange() {
        syncImageAttachmentsFromEditor();
        schedulePromptDrawerSessionSave();
        renderBusy();
      },
      onRemoveAttachment(id) {
        removeImageAttachment(id);
      },
      onSubmit() {
        submitAssistantChat();
      }
    });
  }

  function bindEvents() {
    els.deskPromptDrawerToggle?.addEventListener('click', () => setOpen(!state.open));
    els.deskPromptDrawerToggle?.addEventListener('focus', resetPromptDrawerHandleEyes);
    els.deskPromptDrawerClear?.addEventListener('click', () => {
      state.messages = [];
      state.candidates = [];
      state.resultMode = '';
      state.imageAttachments = [];
      state.imageAnalysis = null;
      state.analysisModules = [];
      state.ocrText = '';
      state.textRegions = [];
      state.keepImageText = false;
      state.expandedCandidateId = '';
      closeImageMentionMenu();
      clearEditor();
      clearPromptDrawerSession();
      render();
    });
    els.deskPromptNodeSelect?.addEventListener('change', () => {
      const nodeId = String(els.deskPromptNodeSelect.value || '');
      if (!nodeId) {
        state.boundTextNodeId = '';
        render();
        return;
      }
      if (bindTextNode(nodeId)) window.DesktopCanvas?.selectNode?.(nodeId);
    });
    els.deskPromptChatSend?.addEventListener('click', () => submitAssistantChat());
    els.deskPromptGenerateVersions?.addEventListener('click', () => generatePromptVersions());
    els.deskPromptChatRefresh?.addEventListener('click', () => {
      const fallback = isImageAnalysisMode()
        ? '重新分析当前图片。'
        : (isVideoPromptMode() ? '重新生成视频提示词。' : '重新生成图片提示词。');
      generatePromptVersions(latestUserMessage(fallback));
    });
    els.deskPromptTaskMode?.addEventListener('click', event => {
      const button = event.target.closest('[data-prompt-task-mode]');
      if (!button || button.disabled) return;
      setAssistantTaskMode(button.dataset.promptTaskMode);
    });
    els.deskPromptTaskMode?.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const buttons = Array.from(els.deskPromptTaskMode.querySelectorAll('[data-prompt-task-mode]:not(:disabled)'));
      if (!buttons.length) return;
      const currentIndex = Math.max(0, buttons.findIndex(button => button.dataset.promptTaskMode === state.taskMode));
      const nextIndex = event.key === 'Home'
        ? 0
        : (event.key === 'End'
          ? buttons.length - 1
          : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length);
      setAssistantTaskMode(buttons[nextIndex].dataset.promptTaskMode, { focus: false });
      buttons[nextIndex].focus();
      event.preventDefault();
    });
    els.deskPromptImageAnalysisToggle?.addEventListener('change', () => {
      setAssistantTaskMode(els.deskPromptImageAnalysisToggle.checked ? 'image_analysis' : 'conversation');
    });
    els.deskPromptImageMenu?.addEventListener('click', event => {
      const button = event.target.closest('[data-prompt-pick-media-node]');
      if (!button) return;
      attachImageNode(button.dataset.promptPickMediaNode).catch(error => window.DesktopResults?.showError?.(error));
    });
    els.deskPromptChatMessages?.addEventListener('click', event => {
      if (event.target.closest('[data-prompt-create-text]')) createTextNode();
    });
    els.deskPromptChatExpand?.addEventListener('click', () => openModal('chat'));
    els.deskPromptVersionsExpand?.addEventListener('click', () => openModal('versions'));
    els.deskPromptCandidateList?.addEventListener('click', event => {
      const button = event.target.closest('[data-candidate-action]');
      if (button) {
        handleCandidateAction(button.dataset.candidateAction, button.dataset.candidateIndex, {
          viewLanguage: button.dataset.candidateViewLanguage
        }).catch(error => window.DesktopResults?.showError?.(error));
        return;
      }
      const keepText = event.target.closest('[data-analysis-keep-text]');
      if (keepText) {
        state.keepImageText = !!keepText.checked;
        updateImageTextCandidate();
        renderCandidates();
        renderModal();
        schedulePromptDrawerSessionSave();
      }
    });
    els.deskPromptModal?.addEventListener('input', event => {
      const textarea = event.target.closest('[data-analysis-ocr-text]');
      if (!textarea) return;
      state.ocrText = String(textarea.value || '');
      updateImageTextCandidate();
      renderCandidates();
      schedulePromptDrawerSessionSave();
    });
    els.deskPromptModal?.addEventListener('change', event => {
      const keepText = event.target.closest('[data-analysis-keep-text]');
      if (!keepText) return;
      state.keepImageText = !!keepText.checked;
      updateImageTextCandidate();
      renderCandidates();
      renderModal();
      schedulePromptDrawerSessionSave();
    });
    document.addEventListener('pointermove', updatePromptDrawerHandleEyes, { passive: true });
    els.deskPromptModal?.addEventListener('click', event => {
      const languageButton = event.target.closest('[data-candidate-language]');
      if (languageButton) {
        setModalCandidateLanguage(languageButton.dataset.candidateLanguage);
        return;
      }
      const button = event.target.closest('[data-candidate-action]');
      if (!button) return;
      handleCandidateAction(button.dataset.candidateAction, button.dataset.candidateIndex, {
        viewLanguage: button.dataset.candidateViewLanguage
      }).catch(error => window.DesktopResults?.showError?.(error));
    });
    els.deskPromptModalClose?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      closeModal();
    });
    els.deskPromptModalDragHandle?.addEventListener('pointerdown', startModalDrag);
    document.addEventListener('pointermove', handleModalDrag);
    document.addEventListener('pointerup', stopModalDrag);
    document.addEventListener('pointercancel', stopModalDrag);
    window.addEventListener('desktop:canvas-selection-change', event => {
      const textNodeId = String(event.detail?.selectedTextNodeId || '');
      if (textNodeId) {
        bindTextNode(textNodeId);
      } else if (state.open) {
        renderTarget();
      }
    });
    window.addEventListener('desktop:canvas-node-removed', event => {
      if (event.detail?.nodeId === state.boundTextNodeId) {
        state.boundTextNodeId = '';
        render();
        return;
      }
      renderTarget();
    });
    window.addEventListener('desktop:canvas-text-nodes-change', () => renderTarget());
  }

  function init() {
    collectElements();
    initPromptEditor();
    const initialTarget = window.DesktopCanvas?.getPromptTargetInfo?.();
    if (initialTarget?.type === 'text') state.boundTextNodeId = initialTarget.nodeId;
    restorePromptDrawerSession();
    els.deskPromptDrawer?.classList.toggle('is-open', state.open);
    els.deskPromptDrawer?.setAttribute('aria-expanded', state.open ? 'true' : 'false');
    resetPromptDrawerHandleEyes();
    render();
    bindEvents();
    window.addEventListener('beforeunload', savePromptDrawerSessionNow);
    syncProjectStylePresets();
  }

  window.DesktopPromptDrawer = { init, setOpen, render, generateSafeRewriteForTextNode };
})();
