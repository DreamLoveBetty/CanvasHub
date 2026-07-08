(function () {
  const els = {};
  const MAX_IMAGE_ATTACHMENTS = 4;
  const HIDDEN_ANALYSIS_MODULE_IDS = new Set(['main', 'visual_summary', 'text_markdown']);
  const SESSION_STORAGE_KEY = 'desktop_prompt_drawer_session_v2';
  const SESSION_SCHEMA_VERSION = 2;
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
    imageAnalysisMode: false,
    imageAnalysis: null,
    analysisModules: [],
    ocrText: '',
    textRegions: [],
    keepImageText: false,
    mentionQuery: '',
    expandedCandidateId: '',
    modalMode: '',
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
      'deskPromptImageAnalysisToggle',
      'deskPromptChatSend',
      'deskPromptGenerateVersions',
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

  function imageAttachmentKey(item = {}) {
    return String(item.sourceNodeId || item.nodeId || item.source_node_id || item.dataUrl || item.imageData || item.imageUrl || item.url || item.id || '').trim();
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
      'id', 'kind', 'label', 'badge', 'text', 'base_text', 'baseText',
      'language', 'task_type', 'taskType', 'intent', 'risk_score',
      'riskScore', 'risk_level', 'riskLevel', 'risk_flags', 'riskFlags',
      'changed_terms', 'changedTerms', 'warnings', 'adapter'
    ];
    const output = {};
    keys.forEach(key => {
      if (candidate[key] !== undefined) output[key] = safeSessionClone(candidate[key]);
    });
    if (!output.text) output.text = truncateForSession(candidate.text || '');
    return output;
  }

  function sanitizeSessionAttachment(item = {}) {
    const source = item.imageUrl || item.url || '';
    return {
      id: String(item.id || '').trim(),
      label: String(item.label || item.id || '').trim(),
      imageUrl: String(source || '').startsWith('data:image/') ? '' : String(source || '').trim(),
      url: String(source || '').startsWith('data:image/') ? '' : String(source || '').trim(),
      sourceNodeId: String(item.sourceNodeId || item.nodeId || item.source_node_id || '').trim(),
      mimeType: String(item.mimeType || item.type || 'image/png').trim(),
      role: String(item.role || '').trim()
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
      imageAnalysisMode: !!state.imageAnalysisMode,
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
        || snapshot.imageAttachments.length;
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
      state.imageAnalysisMode = !!parsed.imageAnalysisMode;
      state.imageAnalysis = parsed.imageAnalysis || null;
      state.analysisModules = Array.isArray(parsed.analysisModules) ? parsed.analysisModules : [];
      state.ocrText = String(parsed.ocrText || '');
      state.textRegions = Array.isArray(parsed.textRegions) ? normalizeTextRegions(parsed.textRegions) : [];
      state.keepImageText = !!parsed.keepImageText;
      state.expandedCandidateId = String(parsed.expandedCandidateId || '');
      if (parsed.editorText && promptEditor?.setText) {
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
        mimeType: String(node.dataset.mimeType || 'image/png').trim()
      }))
      .filter(item => item.id);
  }

  function normalizeAttachmentFromChip(chip = {}) {
    const node = chip.sourceNodeId ? getImageNodes().find(item => item.nodeId === chip.sourceNodeId) : null;
    const src = chip.imageSrc || node?.imageData || node?.imageUrl || node?.url || '';
    const isDataUrl = src.startsWith('data:image/');
    return {
      id: chip.id,
      label: chip.id,
      dataUrl: isDataUrl ? src : (node?.imageData || ''),
      imageData: isDataUrl ? src : (node?.imageData || ''),
      imageUrl: isDataUrl ? '' : src,
      url: src,
      sourceNodeId: chip.sourceNodeId || node?.nodeId || '',
      mimeType: chip.mimeType || node?.mimeType || node?.type || 'image/png',
      role: chip.id === 'image1' ? 'primary' : 'fusion_reserved'
    };
  }

  function syncImageAttachmentsFromEditor() {
    const chips = editorAttachments();
    const chipIds = new Set(chips.map(item => item.id));
    state.imageAttachments = state.imageAttachments.filter(item => chipIds.has(item.id));
    chips.forEach(chip => {
      const existing = state.imageAttachments.find(item => item.id === chip.id);
      if (existing) {
        const isDataUrl = chip.imageSrc?.startsWith('data:image/');
        existing.sourceNodeId = existing.sourceNodeId || chip.sourceNodeId;
        existing.url = existing.url || chip.imageSrc;
        existing.imageUrl = existing.imageUrl || (isDataUrl ? '' : chip.imageSrc);
        existing.dataUrl = existing.dataUrl || (isDataUrl ? chip.imageSrc : '');
        existing.imageData = existing.imageData || (isDataUrl ? chip.imageSrc : '');
        existing.mimeType = existing.mimeType || chip.mimeType || 'image/png';
        return;
      }
      state.imageAttachments.push(normalizeAttachmentFromChip(chip));
    });
  }

  function nextImageAttachmentId() {
    const used = new Set(state.imageAttachments.map(item => String(item.id || '')));
    for (let index = 1; index <= MAX_IMAGE_ATTACHMENTS; index += 1) {
      const id = `image${index}`;
      if (!used.has(id)) return id;
    }
    return `image${state.imageAttachments.length + 1}`;
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
    const source = raw.dataUrl || raw.data_url || raw.imageData || raw.base64 || raw.imageUrl || raw.url || '';
    if (!source) return null;
    const key = imageAttachmentKey(raw);
    const existing = state.imageAttachments.find(item => imageAttachmentKey(item) === key);
    if (existing) {
      promptEditor?.insertAttachment?.(existing, { replaceMention: options.replaceMention !== false });
      render();
      return existing;
    }
    if (state.imageAttachments.length >= MAX_IMAGE_ATTACHMENTS) {
      window.DesktopResults?.showTransientMessage?.(`最多先选择 ${MAX_IMAGE_ATTACHMENTS} 张图片。`, 'warning');
      return null;
    }
    const id = options.id || nextImageAttachmentId();
    const item = {
      id,
      label: String(raw.label || raw.name || raw.title || id).trim() || id,
      dataUrl: raw.dataUrl || raw.data_url || raw.imageData || raw.base64 || '',
      imageData: raw.imageData || raw.base64 || raw.dataUrl || raw.data_url || '',
      imageUrl: raw.imageUrl || raw.url || '',
      url: raw.imageUrl || raw.url || raw.imageData || raw.base64 || raw.dataUrl || raw.data_url || '',
      sourceNodeId: raw.sourceNodeId || raw.nodeId || raw.source_node_id || '',
      mimeType: raw.mimeType || raw.type || 'image/png',
      role: state.imageAttachments.length ? 'fusion_reserved' : 'primary'
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
    const nodes = getImageNodes()
      .filter(node => {
        if (!query) return true;
        return `${node.label || ''} ${node.name || ''} ${node.nodeId || ''}`.toLowerCase().includes(query);
      })
      .slice(0, 8);
    const columns = Math.max(1, Math.min(nodes.length || 1, 3));
    els.deskPromptImageMenu.style.setProperty('--desk-prompt-image-menu-cols', String(columns));
    els.deskPromptImageMenu.dataset.imageCount = String(nodes.length);
    if (!nodes.length) {
      els.deskPromptImageMenu.innerHTML = '<div class="desk-prompt-image-menu__empty">没有图片节点</div>';
    } else {
      els.deskPromptImageMenu.innerHTML = nodes.map(node => `
        <button type="button" data-prompt-pick-image-node="${escapeHtml(node.nodeId)}" aria-label="引用图片节点" title="引用图片节点">
          <img src="${escapeHtml(node.imageData || node.imageUrl || node.url)}" alt="">
        </button>
      `).join('');
    }
    els.deskPromptImageMenu.hidden = false;
  }

  async function attachImageNode(nodeId) {
    const node = getImageNodes().find(item => item.nodeId === nodeId);
    if (!node) return;
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

  function resetPromptDrawerHandleEyes() {
    setPromptDrawerHandleEyesOffset(0, 0);
  }

  function updatePromptDrawerHandleEyes(event) {
    if (!state.open || !els.deskPromptDrawerToggle) return;
    if (event?.pointerType && event.pointerType !== 'mouse') return;
    const rect = els.deskPromptDrawerToggle.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const driftX = clamp((event.clientX - centerX) * 0.03, -2.2, 2.2);
    const driftY = clamp((event.clientY - centerY) * 0.02, -1.6, 1.6);
    setPromptDrawerHandleEyesOffset(driftX, driftY);
  }

  function setOpen(open) {
    state.open = !!open;
    els.deskPromptDrawer?.classList.toggle('is-open', state.open);
    els.deskPromptDrawer?.setAttribute('aria-expanded', state.open ? 'true' : 'false');
    resetPromptDrawerHandleEyes();
    if (state.open) window.setTimeout(focusEditor, 40);
    render();
  }

  function renderTarget() {
    const target = getTarget();
    const active = target.type === 'text' && target.nodeId;
    const nodes = getTextNodes();
    if (els.deskPromptDrawerTarget) els.deskPromptDrawerTarget.textContent = active ? target.label : '未选择文本节点';
    if (els.deskPromptDrawerMeta) els.deskPromptDrawerMeta.textContent = '选择文本节点';
    if (els.deskPromptNodeSelect) {
      els.deskPromptNodeSelect.innerHTML = [
        `<option value="">${nodes.length ? '请选择文本节点' : '画布中没有文本节点'}</option>`,
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
    if (!hasTextTarget()) {
      els.deskPromptChatMessages.innerHTML = `
        <div class="desk-prompt-chat__empty">
          <span>${state.imageAttachments.length ? '可打开图片分析并发送；应用结果时会自动新建文本节点。' : '选择文本节点继续讨论，或用 @ 引用画布图片节点进行分析。'}</span>
          <button type="button" data-prompt-create-text>新建文本节点</button>
        </div>
      `;
      return;
    }
    els.deskPromptChatMessages.innerHTML = '<div class="desk-prompt-chat__empty">先讨论方向；确定后再生成正式提示词版本。</div>';
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

  function candidateAdapterMetaHtml(item = {}) {
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
    const expanded = forceExpanded || state.expandedCandidateId === (item.id || String(index));
    return `
      <article class="desk-prompt-candidate ${expanded ? 'is-expanded' : ''}" data-candidate-index="${index}">
        <header>
          <strong>${escapeHtml(item.label || '提示词版本')}</strong>
          ${item.badge ? `<em>${escapeHtml(item.badge)}</em>` : ''}
        </header>
        ${candidateAdapterMetaHtml(item)}
        <p>${escapeHtml(item.text)}</p>
        <div>
          ${forceExpanded ? '' : `<button type="button" data-candidate-action="toggle" data-candidate-index="${index}" aria-expanded="${expanded ? 'true' : 'false'}">${expanded ? '收起' : '展开'}</button>`}
          <button type="button" data-candidate-action="apply-text" data-candidate-index="${index}" ${canApply ? '' : 'disabled'}>应用到文本节点</button>
          <button type="button" data-candidate-action="copy" data-candidate-index="${index}">复制</button>
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
    const candidate = state.candidates.find(item => item.kind === 'image_analysis_main') || state.candidates[0];
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
    if (state.candidates.length) {
      els.deskPromptCandidateList.innerHTML = [
        ...state.candidates.map((candidate, index) => candidateCard(candidate, index)),
        analysisModulesHtml()
      ].filter(Boolean).join('');
      return;
    }
    if (state.analysisModules.length) {
      els.deskPromptCandidateList.innerHTML = analysisModulesHtml({ includeMain: true });
      return;
    }
    if (!hasTextTarget()) {
      els.deskPromptCandidateList.innerHTML = '<div class="desk-prompt-candidates__empty">用 @ 引用画布图片节点并打开“图片分析”，或绑定文本节点生成版本。</div>';
      return;
    }
    els.deskPromptCandidateList.innerHTML = '<div class="desk-prompt-candidates__empty">点击“生成版本”后，正式提示词会以卡片形式出现在这里。</div>';
  }

  function modalCandidatesHtml() {
    if (state.candidates.length || state.analysisModules.length) {
      const candidateHtml = state.candidates
        .map((candidate, index) => candidateCard(candidate, index, true, { forceExpanded: true }))
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
    if (!hasTextTarget()) {
      return '<div class="desk-prompt-candidates__empty">用 @ 引用画布图片节点并打开“图片分析”，或绑定文本节点生成版本。</div>';
    }
    return '<div class="desk-prompt-candidates__empty">点击“生成版本”后，正式提示词会以卡片形式出现在这里。</div>';
  }

  function renderBusy() {
    syncImageAttachmentsFromEditor();
    const busy = state.busyChat || state.busyVersions;
    const imageMode = !!state.imageAnalysisMode;
    if (els.deskPromptChatSend) {
      els.deskPromptChatSend.disabled = busy || (imageMode ? !state.imageAttachments.length : !hasTextTarget());
      els.deskPromptChatSend.textContent = state.busyChat ? (imageMode ? '分析中' : '思考中') : '发送';
    }
    if (els.deskPromptGenerateVersions) {
      els.deskPromptGenerateVersions.disabled = busy || imageMode || !hasTextTarget();
      els.deskPromptGenerateVersions.textContent = state.busyVersions ? '生成中' : '生成版本';
    }
    if (els.deskPromptChatRefresh) {
      els.deskPromptChatRefresh.disabled = busy || imageMode || !hasTextTarget();
      els.deskPromptChatRefresh.textContent = state.busyVersions ? '生成中' : '重新生成';
    }
    if (els.deskPromptImageAnalysisToggle) {
      els.deskPromptImageAnalysisToggle.checked = imageMode;
      els.deskPromptImageAnalysisToggle.disabled = busy;
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
      els.deskPromptModalTitle.textContent = state.modalMode === 'chat' ? '讨论记录' : '分析结果';
    }
    if (!els.deskPromptModalContent) return;
    els.deskPromptModalContent.classList.toggle('is-chat', state.modalMode === 'chat');
    els.deskPromptModalContent.classList.toggle('is-versions', state.modalMode === 'versions');
    els.deskPromptModalContent.innerHTML = state.modalMode === 'chat' ? modalChatHtml() : modalCandidatesHtml();
  }

  function openModal(mode) {
    state.modalMode = mode;
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

  async function imageAttachmentPayloads() {
    syncImageAttachmentsFromEditor();
    const items = state.imageAttachments.slice(0, 1);
    const payloads = [];
    for (const item of items) {
      let dataUrl = item.dataUrl || item.imageData || '';
      const source = item.imageUrl || item.url || '';
      if (!dataUrl && source && window.DesktopApi?.imageUrlToDataUri) {
        dataUrl = await window.DesktopApi.imageUrlToDataUri(source);
      }
      if (!dataUrl && source?.startsWith('data:image/')) dataUrl = source;
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

  async function submitImageAnalysis() {
    const message = editorText();
    const images = await imageAttachmentPayloads();
    if (!images.length) {
      window.DesktopResults?.showTransientMessage?.('请先用 @ 选择画布图片节点。', 'warning');
      return;
    }
    state.busyChat = true;
    state.messages.push({ role: 'user', text: message || `分析 ${images.map(item => item.id).join('、')}` });
    render();
    try {
      const target = getTarget();
      const result = await DesktopApi.analyzePromptImage({
        message,
        images,
        target: target?.type === 'text' ? target : {},
        style: {},
        keep_text: false
      });
      normalizeAnalysisResult(result);
      persistPromptVersions(state.candidates, {
        message: message || '图片分析',
        target: target?.type === 'text' ? target : {},
        style: {}
      });
      state.messages.push({
        role: 'assistant',
        text: `图片分析完成，已生成 ${state.candidates.length || 1} 个主候选和 ${state.analysisModules.length} 个结构化模块。`
      });
      clearEditor({ keepAttachments: true });
      closeImageMentionMenu();
      window.DesktopResults?.showTransientMessage?.('图片分析已完成。', 'success');
    } catch (error) {
      const errorMessage = error?.message || String(error || '图片分析失败');
      state.messages.push({ role: 'assistant', text: `图片分析失败：${errorMessage}` });
      if (window.DesktopResults?.showTransientMessage) {
        window.DesktopResults.showTransientMessage(`图片分析失败：${errorMessage}`, 'error');
      } else {
        window.DesktopResults?.showError?.(error);
      }
    } finally {
      state.busyChat = false;
      render();
    }
  }

  async function submitAssistantChat(messageOverride = '') {
    if (state.imageAnalysisMode) {
      await submitImageAnalysis();
      return;
    }
    if (!ensureTextTarget()) return;
    const target = getTarget();
    const message = String(messageOverride || editorText() || '').trim();
    const prompt = String(currentPromptText(target) || '').trim();
    if (!message) {
      window.DesktopResults?.showTransientMessage?.('请输入要讨论的方向。', 'warning');
      return;
    }
    state.busyChat = true;
    state.messages.push({ role: 'user', text: message });
    state.messages.push({ role: 'assistant', text: '', streaming: true });
    const assistantIndex = state.messages.length - 1;
    resetAssistantTyping(assistantIndex);
    render();
    let streamedText = '';
    let streamStarted = false;
    const payload = {
      message,
      prompt,
      target,
      style: {},
      history: state.messages.slice(0, -2).slice(-8)
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
    if (!ensureTextTarget()) return;
    const target = getTarget();
    const message = String(messageOverride || editorText() || latestUserMessage('按当前讨论方向整理成正式提示词版本')).trim();
    const prompt = String(currentPromptText(target) || '').trim();
    if (!message && !prompt) {
      window.DesktopResults?.showTransientMessage?.('文本节点为空，请先输入内容或讨论方向。', 'warning');
      return;
    }
    state.busyVersions = true;
    render();
    try {
      const result = await DesktopApi.generatePromptVersions({
        message,
        prompt,
        target,
        style: {}
      });
      state.candidates = (Array.isArray(result.candidates) ? result.candidates : [])
        .filter(item => item?.kind !== 'original');
      state.imageAnalysis = null;
      state.analysisModules = [];
      state.ocrText = '';
      state.textRegions = [];
      state.keepImageText = false;
      state.expandedCandidateId = '';
      persistPromptVersions(state.candidates, {
        message,
        target,
        style: {}
      });
      state.messages.push({
        role: 'assistant',
        text: result.warning ? `正式版本已生成，但润色链路有降级：${result.warning}` : `已生成 ${state.candidates.length} 个正式提示词版本。`
      });
      clearEditor({ keepAttachments: true });
      window.DesktopResults?.showTransientMessage?.('提示词版本已生成。', 'success');
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

  async function handleCandidateAction(action, index) {
    const candidate = candidateByIndex(index);
    if (!candidate?.text) return;
    if (action === 'toggle') {
      const key = candidate.id || String(index);
      state.expandedCandidateId = state.expandedCandidateId === key ? '' : key;
      renderCandidates();
      return;
    }
    if (action === 'copy') {
      await copyText(candidate.text);
      return;
    }
    if (action === 'apply-text') {
      const textForNode = candidateTextForTextNode(candidate);
      if (hasTextTarget()) {
        window.DesktopCanvas?.fillPromptTarget?.(textForNode, { target: getTarget() });
        window.DesktopResults?.showTransientMessage?.('已应用到文本节点。', 'success');
        return;
      }
      const nodeId = window.DesktopCanvas?.createTextNodeWithText?.(textForNode);
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
      if (!nodeId) return;
      if (bindTextNode(nodeId)) window.DesktopCanvas?.selectNode?.(nodeId);
    });
    els.deskPromptChatSend?.addEventListener('click', () => submitAssistantChat());
    els.deskPromptGenerateVersions?.addEventListener('click', () => generatePromptVersions());
    els.deskPromptChatRefresh?.addEventListener('click', () => generatePromptVersions(latestUserMessage('重新生成正式提示词版本')));
    els.deskPromptImageAnalysisToggle?.addEventListener('change', () => {
      state.imageAnalysisMode = !!els.deskPromptImageAnalysisToggle?.checked;
      renderBusy();
      schedulePromptDrawerSessionSave();
    });
    els.deskPromptImageMenu?.addEventListener('click', event => {
      const button = event.target.closest('[data-prompt-pick-image-node]');
      if (!button) return;
      attachImageNode(button.dataset.promptPickImageNode).catch(error => window.DesktopResults?.showError?.(error));
    });
    els.deskPromptChatMessages?.addEventListener('click', event => {
      if (event.target.closest('[data-prompt-create-text]')) createTextNode();
    });
    els.deskPromptChatExpand?.addEventListener('click', () => openModal('chat'));
    els.deskPromptVersionsExpand?.addEventListener('click', () => openModal('versions'));
    els.deskPromptCandidateList?.addEventListener('click', event => {
      const button = event.target.closest('[data-candidate-action]');
      if (button) {
        handleCandidateAction(button.dataset.candidateAction, button.dataset.candidateIndex).catch(error => window.DesktopResults?.showError?.(error));
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
      const button = event.target.closest('[data-candidate-action]');
      if (!button) return;
      handleCandidateAction(button.dataset.candidateAction, button.dataset.candidateIndex).catch(error => window.DesktopResults?.showError?.(error));
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
