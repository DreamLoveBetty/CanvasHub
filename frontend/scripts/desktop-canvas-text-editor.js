// 文本节点 HTML/别名/风格、contenteditable/token/mention/光标、文档编辑与 undo/redo、图片引用 token 迁移冻结刷新、提示词目标适配、剪贴板及润色结果展示/应用/撤销；润色请求 runTextNodeGptPolish 留生成执行模块。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    CUSTOM_TEXT_STYLE_KEY,
    DEFAULT_IMAGE_GROUP_NODE_WIDTH,
    DEFAULT_TEXT_NODE_WIDTH,
    PROMPT_BLOCK_MODULE_LABELS,
    PROMPT_DOCUMENT_HISTORY_LIMIT,
    PROMPT_TOKEN_SELECTOR,
    TEXT_NODE_ALIAS_MAX_LENGTH,
    TEXT_POLISH_VARIANTS,
    TEXT_STYLE_PRESETS,
    activeTextImageMentionRef,
    addNode,
    beginPromptDocumentHistory,
    bumpPromptDocumentVersion,
    clamp,
    clonePromptDocument,
    commitPromptDocumentHistory,
    connectNodes,
    createTextPromptDocument,
    ensureGraphDom,
    ensureTextNodePromptDocument,
    escapeHtml,
    getConnectedImageReferences,
    getImageGroupItem,
    getNodeElement,
    getPromptDocumentHistory,
    getSelectedNodeIds,
    getViewportCenterWorldPoint,
    imageGroupRoleLabel,
    imageReferenceDisplay,
    imageReferenceRole,
    lastPromptTextNodeIdRef,
    listPromptImageNodes,
    materializePromptDocument,
    materializeTextNode,
    normalizeImageGroupRole,
    normalizeImageReferenceSegment,
    normalizePromptBlockSegment,
    normalizePromptDocument,
    promptDocumentFingerprint,
    promptDocumentHasEditorContent,
    selectNode,
    setTextNodePromptMeta,
  }) {
    let externalTextStylePresets = [];
    let textPolishState = null;

    function updatePromptEditorEmptyState(editor, promptDocument) {
    if (!editor) return;
    editor.dataset.empty = promptDocumentHasEditorContent(promptDocument) ? 'false' : 'true';
  }

    function shortPromptBlockLabel(value) {
    const chars = Array.from(String(value || '素材块').trim() || '素材块');
    return chars.length > 16 ? `${chars.slice(0, 16).join('')}…` : chars.join('');
  }

    function promptBlockModuleLabel(moduleType) {
    const key = String(moduleType || 'custom').trim() || 'custom';
    const liveLabel = String(window.DesktopPromptLibrary?.getModuleLabel?.(key) || '').trim();
    return PROMPT_BLOCK_MODULE_LABELS[key] || liveLabel || key || '素材';
  }

    function promptBlockModuleMark(moduleType) {
    const label = promptBlockModuleLabel(moduleType);
    return Array.from(label).find(char => char.trim() && !/[_\-]/.test(char)) || '素';
  }

    function promptBlockTokenHtml(segment) {
    const normalized = normalizePromptBlockSegment(segment);
    const label = shortPromptBlockLabel(normalized.label_snapshot);
    const rawTitle = [normalized.label_snapshot, normalized.content_snapshot].filter(Boolean).join('\n');
    const title = rawTitle.length > 360 ? `${rawTitle.slice(0, 359)}…` : rawTitle;
    const colors = Array.isArray(normalized.color_snapshot) ? normalized.color_snapshot.slice(0, 5) : [];
    const isColor = normalized.module_type === 'color' && colors.length > 0;
    const palette = Array.from({ length: 5 }, (_, index) => colors[index] || colors[colors.length - 1] || '#DCEBFA');
    const colorClass = isColor ? ' desk-prompt-block-token--color' : '';
    const colorData = isColor ? ` data-prompt-block-colors="${escapeHtml(colors.join(','))}"` : '';
    const colorStyle = isColor ? ` style="${palette.map((color, index) => `--prompt-token-color-${index + 1}:${color}`).join(';')}"` : '';
    const moduleLabel = promptBlockModuleLabel(normalized.module_type);
    const moduleClass = isColor ? '' : ' desk-prompt-block-token--categorized';
    const moduleData = isColor ? '' : ` data-prompt-block-module-label="${escapeHtml(moduleLabel)}" data-prompt-block-module-mark="${escapeHtml(promptBlockModuleMark(normalized.module_type))}"`;
    const ariaType = isColor ? '色彩方案' : '提示词素材块';
    const ariaLabel = isColor ? `${ariaType}：${normalized.label_snapshot}` : `${ariaType}，${moduleLabel}：${normalized.label_snapshot}`;
    return `<span class="desk-prompt-block-token${colorClass}${moduleClass}" contenteditable="false" tabindex="0" role="button" aria-haspopup="listbox" aria-expanded="false" data-prompt-block-token="${escapeHtml(normalized.block_id)}" data-prompt-block-instance="${escapeHtml(normalized.instance_id)}" data-prompt-block-instance-id="${escapeHtml(normalized.instance_id)}" data-prompt-block-id="${escapeHtml(normalized.block_id)}" data-prompt-block-module="${escapeHtml(normalized.module_type)}" data-prompt-block-module-type="${escapeHtml(normalized.module_type)}"${moduleData}${colorData}${colorStyle} aria-label="${escapeHtml(ariaLabel)}" title="${escapeHtml(title)}"><span class="desk-prompt-block-token__label">${escapeHtml(label)}</span><span class="desk-prompt-block-token__chevron" aria-hidden="true"><svg viewBox="0 0 12 12"><path d="m3 4.5 3 3 3-3"></path></svg></span></span>`;
  }

    function imageReferenceTokenHtml(segment) {
    const normalized = normalizeImageReferenceSegment(segment);
    const label = imageReferenceDisplay(normalized);
    const liveRole = imageReferenceRole(normalized);
    const roleLabel = imageGroupRoleLabel(liveRole);
    return `<span class="desk-image-reference-token" contenteditable="false" tabindex="0" role="button" data-image-reference-token data-image-reference-instance="${escapeHtml(normalized.instance_id)}" data-image-reference-group="${escapeHtml(normalized.group_id)}" data-image-reference-item="${escapeHtml(normalized.item_id)}" data-image-reference-source-node="${escapeHtml(normalized.source_node_id)}" data-image-reference-role="${escapeHtml(liveRole)}" aria-label="图片引用：${escapeHtml(label)}，${escapeHtml(roleLabel)}" title="引用编号跟随模型实际收图顺序"><span class="desk-image-reference-token__label">${escapeHtml(label)}</span><small>${escapeHtml(roleLabel)}</small></span>`;
  }

    function syncImageReferenceTokenElement(token, segment) {
    if (!token) return;
    const normalized = normalizeImageReferenceSegment(segment);
    const liveRole = imageReferenceRole(normalized);
    const label = imageReferenceDisplay(normalized);
    const roleLabel = imageGroupRoleLabel(liveRole);
    token.dataset.imageReferenceInstance = normalized.instance_id;
    token.dataset.imageReferenceGroup = normalized.group_id;
    token.dataset.imageReferenceItem = normalized.item_id;
    token.dataset.imageReferenceSourceNode = normalized.source_node_id;
    token.dataset.imageReferenceRole = liveRole;
    token.setAttribute('aria-label', `图片引用：${label}，${roleLabel}`);
    token.title = '引用编号跟随模型实际收图顺序';
    token.innerHTML = `<span class="desk-image-reference-token__label">${escapeHtml(label)}</span><small>${escapeHtml(roleLabel)}</small>`;
    token._imageReferenceSegment = normalized;
  }

    function promptDocumentEditorHtml(promptDocument) {
    return normalizePromptDocument(promptDocument).segments.map(segment => {
      if (segment.type === 'prompt_block') return promptBlockTokenHtml(segment);
      if (segment.type === 'image_reference') return imageReferenceTokenHtml(segment);
      return escapeHtml(segment.text || '').replace(/\n/g, '<br>');
    }).join('');
  }

    function promptDocumentFromEditor(editor, nodeState) {
    const existingSegments = normalizePromptDocument(nodeState?.promptDocument, nodeState?.text || '').segments;
    const existingBlocks = new Map(
      existingSegments
        .filter(segment => segment.type === 'prompt_block')
        .map(segment => [segment.instance_id, segment])
    );
    const existingImageReferences = new Map(
      existingSegments
        .filter(segment => segment.type === 'image_reference')
        .map(segment => [segment.instance_id, segment])
    );
    const segments = [];
    const pushText = value => {
      const text = String(value ?? '').replace(/\r\n?/g, '\n').replace(/\u00a0/g, ' ').replace(/\u200b/g, '');
      if (!text) return;
      const previous = segments[segments.length - 1];
      if (previous?.type === 'text') previous.text += text;
      else segments.push({ type: 'text', text });
    };
    const endsWithNewline = () => {
      const previous = segments[segments.length - 1];
      return previous?.type === 'text' && previous.text.endsWith('\n');
    };
    const blockTags = new Set(['DIV', 'P', 'LI', 'SECTION', 'ARTICLE', 'BLOCKQUOTE']);
    const walk = parent => {
      Array.from(parent.childNodes || []).forEach(child => {
        if (child.nodeType === Node.TEXT_NODE) {
          pushText(child.nodeValue || '');
          return;
        }
        if (child.nodeType !== Node.ELEMENT_NODE) return;
        if (child.matches?.('[data-image-reference-token]')) {
          const instanceId = String(child.dataset.imageReferenceInstance || '');
          const segment = child._imageReferenceSegment
            || existingImageReferences.get(instanceId)
            || normalizeImageReferenceSegment({
              instance_id: instanceId,
              group_id: child.dataset.imageReferenceGroup || '',
              item_id: child.dataset.imageReferenceItem || '',
              source_node_id: child.dataset.imageReferenceSourceNode || '',
              role_snapshot: child.dataset.imageReferenceRole || 'reference',
              label_snapshot: child.textContent || ''
            });
          segments.push(normalizeImageReferenceSegment(segment));
          return;
        }
        if (child.matches?.('[data-prompt-block-token]')) {
          const instanceId = String(child.dataset.promptBlockInstance || child.dataset.promptBlockInstanceId || '');
          const segment = child._promptBlockSegment
            || existingBlocks.get(instanceId)
            || normalizePromptBlockSegment({
              instance_id: instanceId,
              block_id: child.dataset.promptBlockId || '',
              module_type: child.dataset.promptBlockModuleType || child.dataset.promptBlockModule || 'custom',
              color_snapshot: String(child.dataset.promptBlockColors || '').split(',').filter(Boolean),
              label_snapshot: child.textContent || '素材块',
              content_snapshot: child.textContent || ''
            });
          segments.push(normalizePromptBlockSegment(segment));
          return;
        }
        if (child.tagName === 'BR') {
          pushText('\n');
          return;
        }
        const blockLike = blockTags.has(child.tagName);
        if (blockLike && segments.length && !endsWithNewline()) pushText('\n');
        walk(child);
        if (blockLike && child.nextSibling && !endsWithNewline()) pushText('\n');
      });
    };
    walk(editor);
    if (!editor.querySelector(PROMPT_TOKEN_SELECTOR) && editor.textContent === '') {
      return createTextPromptDocument('');
    }
    return normalizePromptDocument({ segments }, '');
  }

    function renderPromptDocumentToEditor(editor, promptDocument) {
    if (!editor) return;
    editor.innerHTML = promptDocumentEditorHtml(promptDocument);
    updatePromptEditorEmptyState(editor, promptDocument);
  }

    function setTextNodePromptDocument(node, nodeState, promptDocument, options = {}) {
    if (!nodeState || nodeState.type !== 'text') return null;
    const normalized = normalizePromptDocument(promptDocument, nodeState.text || '');
    const beforeFingerprint = promptDocumentFingerprint(
      ensureTextNodePromptDocument(nodeState),
      nodeState.text || ''
    );
    const afterFingerprint = promptDocumentFingerprint(normalized);
    const changed = beforeFingerprint !== afterFingerprint;
    const historyEntry = changed && options.recordHistory !== false
      ? beginPromptDocumentHistory(nodeState)
      : null;
    nodeState.promptDocument = normalized;
    nodeState.text = materializePromptDocument(normalized);
    const editor = node?.querySelector?.('[data-text-node-input]');
    if (editor) {
      renderPromptDocumentToEditor(editor, normalized);
      if (options.dispatch !== false) {
        editor.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
      }
    }
    if (changed) {
      bumpPromptDocumentVersion(nodeState);
      if (historyEntry) commitPromptDocumentHistory(nodeState, historyEntry);
    }
    if (options.save !== false) DesktopState.saveSettings();
    if (options.notify !== false) notifyTextNodeListChange(nodeState.id);
    return normalized;
  }

    function syncPromptDocumentFromEditor(editor, nodeState, options = {}) {
    if (!editor || !nodeState || nodeState.type !== 'text') return null;
    const beforeFingerprint = promptDocumentFingerprint(
      ensureTextNodePromptDocument(nodeState),
      nodeState.text || ''
    );
    const promptDocument = promptDocumentFromEditor(editor, nodeState);
    const changed = beforeFingerprint !== promptDocumentFingerprint(promptDocument);
    nodeState.promptDocument = promptDocument;
    nodeState.text = materializePromptDocument(promptDocument);
    updatePromptEditorEmptyState(editor, promptDocument);
    if (changed) {
      bumpPromptDocumentVersion(nodeState);
      if (options.preserveRedo !== true) {
        const history = getPromptDocumentHistory(nodeState.id, false);
        if (history) {
          history.redo = [];
          history.redoEligible = false;
        }
      }
    }
    if (options.save !== false) DesktopState.saveSettings();
    if (options.notify !== false) notifyTextNodeListChange(nodeState.id);
    return promptDocument;
  }

    function focusPromptEditorAtEnd(node) {
    const editor = node?.querySelector?.('[data-text-node-input]');
    if (!editor) return;
    editor.focus({ preventScroll: true });
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection = window.getSelection?.();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }

    function undoPromptDocumentChange(node, nodeState, options = {}) {
    const history = getPromptDocumentHistory(nodeState?.id, false);
    const entry = history?.undo?.[history.undo.length - 1];
    if (!entry || !nodeState) return false;
    const currentFingerprint = promptDocumentFingerprint(
      ensureTextNodePromptDocument(nodeState),
      nodeState.text || ''
    );
    if (currentFingerprint !== entry.afterFingerprint) return false;
    if (options.expectedBeforeFingerprint && options.expectedBeforeFingerprint !== entry.beforeFingerprint) return false;
    history.undo.pop();
    history.redo.push(entry);
    history.redoEligible = true;
    setTextNodePromptDocument(node, nodeState, entry.beforeDocument, { recordHistory: false });
    focusPromptEditorAtEnd(node);
    return true;
  }

    function redoPromptDocumentChange(node, nodeState) {
    const history = getPromptDocumentHistory(nodeState?.id, false);
    const entry = history?.redo?.[history.redo.length - 1];
    if (!entry || !history.redoEligible || !nodeState) return false;
    const currentFingerprint = promptDocumentFingerprint(
      ensureTextNodePromptDocument(nodeState),
      nodeState.text || ''
    );
    if (currentFingerprint !== entry.beforeFingerprint) return false;
    history.redo.pop();
    history.undo.push(entry);
    if (history.undo.length > PROMPT_DOCUMENT_HISTORY_LIMIT) history.undo.shift();
    history.redoEligible = history.redo.length > 0;
    setTextNodePromptDocument(node, nodeState, entry.afterDocument, { recordHistory: false });
    focusPromptEditorAtEnd(node);
    return true;
  }

    function handlePromptDocumentHistoryShortcut(event, editor) {
    if ((!event.metaKey && !event.ctrlKey) || event.altKey) return false;
    const key = String(event.key || '').toLowerCase();
    const wantsUndo = key === 'z' && !event.shiftKey;
    const wantsRedo = (key === 'z' && event.shiftKey) || (key === 'y' && event.ctrlKey);
    if (!wantsUndo && !wantsRedo) return false;
    const node = editor?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    const handled = wantsUndo
      ? undoPromptDocumentChange(node, nodeState)
      : redoPromptDocumentChange(node, nodeState);
    if (!handled) return false;
    event.preventDefault();
    event.stopPropagation();
    return true;
  }

    function sanitizeTextNodeAlias(value) {
    return Array.from(String(value || ''))
      .filter(char => /[A-Za-z0-9\u3400-\u9FFF,_-]/u.test(char))
      .join('')
      .slice(0, TEXT_NODE_ALIAS_MAX_LENGTH);
  }

    function nextTextNodeAlias(excludeNodeId = '') {
    const used = new Set(Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node?.type === 'text' && node.id !== excludeNodeId)
      .map(node => sanitizeTextNodeAlias(node.alias))
      .filter(Boolean));
    let index = 1;
    while (used.has(`文本节点-${index}`)) index += 1;
    return `文本节点-${index}`;
  }

    function getTextNodeAlias(node) {
    return sanitizeTextNodeAlias(node?.alias) || nextTextNodeAlias(node?.id || '');
  }

    function textNodeAliasMeasure(value) {
    const units = Array.from(String(value || '')).reduce((total, char) => {
      return total + (/[\u3400-\u9FFF]/u.test(char) ? 2 : 1);
    }, 0);
    return Math.max(4, Math.min(42, units || 4));
  }

    function textNodeAliasStyle(alias) {
    return `--text-node-alias-ch: ${textNodeAliasMeasure(alias)}ch;`;
  }

    function updateTextNodeAliasMetrics(aliasInput) {
    const shell = aliasInput?.closest?.('.desk-text-node__alias');
    if (!shell) return;
    shell.style.setProperty('--text-node-alias-ch', `${textNodeAliasMeasure(aliasInput.value)}ch`);
  }

    function setTextNodeAliasEditing(shell, editing) {
    const aliasInput = shell?.querySelector?.('[data-text-node-alias]');
    const editButton = shell?.querySelector?.('[data-text-node-alias-edit]');
    if (!aliasInput || !editButton) return;
    shell.classList.toggle('is-editing', editing);
    editButton.dataset.aliasMode = editing ? 'apply' : 'edit';
    editButton.setAttribute('aria-label', editing ? '应用文本节点别名' : '编辑文本节点别名');
    editButton.title = editing ? '应用别名' : '编辑别名';
    if (editing) {
      aliasInput.dataset.aliasBeforeEdit = aliasInput.value;
      aliasInput.removeAttribute('readonly');
      aliasInput.removeAttribute('tabindex');
      requestAnimationFrame(() => {
        aliasInput.focus();
        aliasInput.select();
      });
      return;
    }
    aliasInput.setAttribute('readonly', '');
    aliasInput.setAttribute('tabindex', '-1');
    aliasInput.blur();
  }

    function commitTextNodeAliasInput(aliasInput) {
    const node = aliasInput?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    if (!nodeState) return '';
    const alias = sanitizeTextNodeAlias(aliasInput.value) || nextTextNodeAlias(nodeState.id);
    aliasInput.value = alias;
    aliasInput.dataset.aliasBeforeEdit = alias;
    nodeState.alias = alias;
    updateTextNodeAliasMetrics(aliasInput);
    DesktopState.saveSettings();
    notifyTextNodeListChange(nodeState.id);
    return alias;
  }

    function revertTextNodeAliasInput(aliasInput) {
    const node = aliasInput?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    if (!nodeState) return;
    const alias = sanitizeTextNodeAlias(aliasInput.dataset.aliasBeforeEdit) || getTextNodeAlias(nodeState);
    aliasInput.value = alias;
    nodeState.alias = alias;
    updateTextNodeAliasMetrics(aliasInput);
    DesktopState.saveSettings();
    notifyTextNodeListChange(nodeState.id);
  }

    function ensureTextNodeAliases() {
    let changed = false;
    Object.values(DesktopState.state.canvas.nodes).forEach(node => {
      if (node?.type !== 'text') return;
      const alias = getTextNodeAlias(node);
      if (node.alias === alias) return;
      node.alias = alias;
      changed = true;
    });
    if (changed) DesktopState.saveSettings();
  }

    function listTextNodes() {
    return Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node?.type === 'text')
      .map(node => ({
        nodeId: node.id,
        type: 'text',
        alias: getTextNodeAlias(node),
        label: getTextNodeAlias(node),
        text: materializeTextNode(node)
      }));
  }

    function notifyTextNodeListChange(nodeId = '') {
    window.dispatchEvent(new CustomEvent('desktop:canvas-text-nodes-change', {
      detail: { nodeId, nodes: listTextNodes() }
    }));
  }

    function textStylePresetButtonsHtml() {
    return allTextStylePresets().map(item => `
      <button type="button" data-text-style-preset="${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.promptTemplate)}</span>
      </button>
    `).join('');
  }

    function loadCustomTextStylePresets() {
    try {
      const raw = window.localStorage?.getItem(CUSTOM_TEXT_STYLE_KEY);
      const parsed = JSON.parse(raw || '[]');
      return Array.isArray(parsed) ? parsed.filter(item => item?.id && item?.promptTemplate) : [];
    } catch (e) {
      return [];
    }
  }

    function saveCustomTextStylePresets(items) {
    try {
      window.localStorage?.setItem(CUSTOM_TEXT_STYLE_KEY, JSON.stringify(items || []));
    } catch (e) {}
  }

    function allTextStylePresets() {
    const seen = new Set();
    return [...TEXT_STYLE_PRESETS, ...externalTextStylePresets, ...loadCustomTextStylePresets()].filter(item => {
      if (!item?.id || seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  }

    function getTextStylePreset(presetId) {
    return allTextStylePresets().find(item => item.id === presetId) || null;
  }

    function textStyleTagHtml(presetId) {
    const preset = getTextStylePreset(presetId);
    if (!preset) return '';
    return `
      <button type="button" class="desk-text-style-tag" data-text-style-clear title="移除风格标签">
        <span>风格</span>
        <strong>${escapeHtml(preset.title)}</strong>
        <em aria-hidden="true">×</em>
      </button>
    `;
  }

    function getPromptTargetInfo(nodeId = '') {
    const requestedId = typeof nodeId === 'string' ? nodeId : String(nodeId?.nodeId || '');
    const selectedId = requestedId || DesktopState.state.canvas.selectedNodeId || '';
    const selectedNode = DesktopState.state.canvas.nodes[selectedId];
    if (selectedNode?.type === 'text') {
      const alias = getTextNodeAlias(selectedNode);
      return { nodeId: selectedId, type: 'text', alias, label: alias };
    }
    if (selectedNode) {
      return { nodeId: selectedId, type: selectedNode.type || '', label: '请选择文本节点', inactive: true };
    }
    return { nodeId: '', type: '', label: '未绑定文本节点', inactive: true };
  }

    function getPromptTargetText(options = {}) {
    const target = options.target || getPromptTargetInfo(options.nodeId || options);
    if (target.type === 'text') {
      return materializeTextNode(DesktopState.state.canvas.nodes[target.nodeId]);
    }
    return '';
  }

    function fillPromptTarget(text, options = {}) {
    const target = options.target || getPromptTargetInfo(options.nodeId || '');
    const next = String(text || '');
    if (target.type === 'text') {
      const node = getNodeElement(target.nodeId);
      const nodeState = DesktopState.state.canvas.nodes[target.nodeId];
      if (!node || !nodeState) throw new Error('文本节点不存在');
      setTextNodeValue(node, nodeState, next);
      if (options.promptMeta) setTextNodePromptMeta(nodeState, options.promptMeta, next);
      selectNode(target.nodeId);
      return target;
    }
    throw new Error('请先选择文本节点');
  }

    function fillNearestInputPrompt(text, options = {}) {
    const next = String(text || '');
    const nodes = DesktopState.state.canvas.nodes || {};
    const requestedId = String(options.inputNodeId || options.nodeId || '');
    const acceptsPrompt = node => ['input', 'comfy', 'video_inference'].includes(node?.type);
    const selectedInput = getSelectedNodeIds()
      .map(nodeId => nodes[nodeId])
      .find(acceptsPrompt);
    const connectedInput = (DesktopState.state.canvas.edges || [])
      .map(edge => nodes[edge.to])
      .find(acceptsPrompt);
    let inputNode = acceptsPrompt(nodes[requestedId])
      ? nodes[requestedId]
      : (selectedInput
        || connectedInput
        || Object.values(nodes).find(node => node?.type === 'input' && node.id !== 'input')
        || (acceptsPrompt(nodes.input) ? nodes.input : null)
        || Object.values(nodes).find(acceptsPrompt));
    // Workflow snapshots may contain a compatibility-only default input. Resolve
    // against live state and let approved Agent actions explicitly create it.
    if (!inputNode && options.createIfMissing === true) {
      const inputNodeId = addNode('input', getViewportCenterWorldPoint());
      inputNode = DesktopState.state.canvas.nodes[inputNodeId];
    }
    if (!inputNode) throw new Error('画布里没有模型节点');
    const textNodeId = setPromptTextForInputNode(inputNode.id, next, options);
    if (inputNode.id === 'input') DesktopState.state.prompt = '';
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    selectNode(inputNode.id);
    return { nodeId: inputNode.id, textNodeId, type: inputNode.type, label: '模型节点' };
  }

    function createTextNodeWithText(text, worldPoint = null, options = {}) {
    const id = addNode('text', worldPoint || getViewportCenterWorldPoint(0, 120));
    const node = getNodeElement(id);
    const nodeState = DesktopState.state.canvas.nodes[id];
    if (node && nodeState) {
      setTextNodeValue(node, nodeState, text);
      if (options.promptMeta) setTextNodePromptMeta(nodeState, options.promptMeta, text);
    }
    selectNode(id);
    return id;
  }

    function findConnectedTextNodeId(inputNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .find(edge => edge.to === inputNodeId && DesktopState.state.canvas.nodes[edge.from]?.type === 'text')
      ?.from || '';
  }

    function setPromptTextForInputNode(inputNodeId, text, options = {}) {
    const inputNode = DesktopState.state.canvas.nodes[inputNodeId];
    if (!inputNode || !['input', 'comfy', 'video_inference'].includes(inputNode.type)) {
      throw new Error('模型节点不存在');
    }
    const next = String(text || '');
    const connectedTextId = findConnectedTextNodeId(inputNodeId);
    if (connectedTextId) {
      const node = getNodeElement(connectedTextId);
      const nodeState = DesktopState.state.canvas.nodes[connectedTextId];
      if (node && nodeState) {
        setTextNodeValue(node, nodeState, next);
        if (options.promptMeta) setTextNodePromptMeta(nodeState, options.promptMeta, next);
        return connectedTextId;
      }
    }
    const textNodeId = createTextNodeWithText(next, {
      x: inputNode.x - 220,
      y: inputNode.y + Math.min(160, Math.max(70, (inputNode.height || 360) * 0.38))
    });
    connectNodes(textNodeId, inputNodeId, { quiet: !!options.quiet });
    if (options.promptMeta) setTextNodePromptMeta(DesktopState.state.canvas.nodes[textNodeId], options.promptMeta, next);
    return textNodeId;
  }

    function getTextStylePresets() {
    return allTextStylePresets().map(item => ({ ...item }));
  }

    function createTextStylePreset(title, promptTemplate) {
    const cleanTitle = String(title || '').trim() || '自定义风格';
    const cleanTemplate = String(promptTemplate || '').trim();
    if (!cleanTemplate) throw new Error('风格内容为空');
    const now = Date.now();
    const item = {
      id: `custom_${now}`,
      title: cleanTitle.slice(0, 24),
      promptTemplate: cleanTemplate,
      custom: true,
      createdAt: now,
      updatedAt: now
    };
    const custom = loadCustomTextStylePresets();
    custom.push(item);
    saveCustomTextStylePresets(custom.slice(-30));
    document.querySelectorAll('[data-text-style-menu]').forEach(menu => {
      menu.innerHTML = textStylePresetButtonsHtml();
    });
    return item;
  }

    function registerTextStylePresets(items = []) {
    externalTextStylePresets = (Array.isArray(items) ? items : [])
      .map(item => ({
        id: String(item.id || '').trim(),
        title: String(item.title || item.name || '').trim(),
        promptTemplate: String(item.promptTemplate || item.prompt_style || '').trim(),
        description: String(item.description || '').trim(),
        positiveStyle: String(item.positive_style || '').trim(),
        avoid: String(item.avoid || '').trim(),
        bestFor: String(item.best_for || '').trim(),
        external: true
      }))
      .filter(item => item.id && item.title && item.promptTemplate);
    document.querySelectorAll('[data-text-style-menu]').forEach(menu => {
      menu.innerHTML = textStylePresetButtonsHtml();
    });
    return getTextStylePresets();
  }

    function applyTextStylePresetToTarget(presetId, options = {}) {
    const target = options.target || getPromptTargetInfo(options.nodeId || '');
    if (target.type !== 'text' || !target.nodeId) throw new Error('请先选择文本节点');
    const node = getNodeElement(target.nodeId);
    const nodeState = DesktopState.state.canvas.nodes[target.nodeId];
    if (!node || !nodeState) throw new Error('文本节点不存在');
    const preset = setTextNodeStyle(node, nodeState, presetId || '');
    if (preset) {
      DesktopResults.showTransientMessage(`已应用「${preset.title}」风格到文本节点。`);
    } else {
      DesktopResults.showTransientMessage('已移除文本节点风格。');
    }
    return preset;
  }

    function migrateImageReferenceTokensToGroup(groupId, sourceNodeIds = []) {
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    if (!groupNode || groupNode.type !== 'image_group') return 0;
    const allowedSources = new Set(sourceNodeIds.filter(Boolean));
    const itemBySource = new Map(
      groupNode.items
        .filter(item => item.sourceNodeId && (!allowedSources.size || allowedSources.has(item.sourceNodeId)))
        .map(item => [item.sourceNodeId, item])
    );
    if (!itemBySource.size) return 0;
    let migrated = 0;
    Object.values(DesktopState.state.canvas.nodes || {}).forEach(nodeState => {
      if (nodeState?.type !== 'text') return;
      const documentState = ensureTextNodePromptDocument(nodeState);
      let changed = false;
      documentState.segments.forEach(segment => {
        if (segment.type !== 'image_reference' || segment.group_id) return;
        const item = itemBySource.get(segment.source_node_id);
        if (!item) return;
        segment.group_id = groupId;
        segment.item_id = item.itemId;
        segment.role_snapshot = normalizeImageGroupRole(item.role);
        segment.label_snapshot = imageReferenceDisplay(segment);
        changed = true;
        migrated += 1;
      });
      if (!changed) return;
      nodeState.text = materializePromptDocument(documentState);
      renderPromptDocumentToEditor(getNodeElement(nodeState.id)?.querySelector('[data-text-node-input]'), documentState);
      bumpPromptDocumentVersion(nodeState);
      notifyTextNodeListChange(nodeState.id);
    });
    return migrated;
  }

    function freezeImageReferenceTokensMatching(predicate) {
    Object.values(DesktopState.state.canvas.nodes || {}).forEach(nodeState => {
      if (nodeState?.type !== 'text') return;
      const documentState = clonePromptDocument(ensureTextNodePromptDocument(nodeState), nodeState.text || '');
      let changed = false;
      const segments = documentState.segments.map(segment => {
        if (segment.type !== 'image_reference' || !predicate(segment)) return segment;
        changed = true;
        return { type: 'text', text: imageReferenceDisplay(segment) };
      });
      if (!changed) return;
      nodeState.promptDocument = normalizePromptDocument({ ...documentState, segments }, nodeState.text || '');
      nodeState.text = materializePromptDocument(nodeState.promptDocument);
      renderPromptDocumentToEditor(getNodeElement(nodeState.id)?.querySelector('[data-text-node-input]'), nodeState.promptDocument);
      bumpPromptDocumentVersion(nodeState);
      notifyTextNodeListChange(nodeState.id);
    });
  }

    function freezeImageReferenceTokens(groupId) {
    freezeImageReferenceTokensMatching(segment => segment.group_id === groupId);
  }

    function freezeImageReferenceTokensForSourceNode(sourceNodeId) {
    freezeImageReferenceTokensMatching(segment => !segment.group_id && segment.source_node_id === sourceNodeId);
  }

    function refreshImageReferenceTokens(groupId = '') {
    Object.values(DesktopState.state.canvas.nodes || {}).forEach(nodeState => {
      if (nodeState?.type !== 'text') return;
      const documentState = ensureTextNodePromptDocument(nodeState);
      const references = documentState?.segments?.filter(segment => (
        segment.type === 'image_reference' && (!groupId || segment.group_id === groupId)
      )) || [];
      if (!references.length) return;
      references.forEach(segment => {
        segment.role_snapshot = imageReferenceRole(segment);
        segment.label_snapshot = imageReferenceDisplay(segment);
      });
      nodeState.text = materializePromptDocument(documentState);
      const editor = getNodeElement(nodeState.id)?.querySelector('[data-text-node-input]');
      references.forEach(segment => {
        const selector = `[data-image-reference-instance="${CSS.escape(segment.instance_id)}"]`;
        syncImageReferenceTokenElement(editor?.querySelector(selector), segment);
      });
      bumpPromptDocumentVersion(nodeState);
      notifyTextNodeListChange(nodeState.id);
    });
  }

    function resolveImageReferenceTextNode(groupId) {
    const nodes = DesktopState.state.canvas.nodes || {};
    const selectedTextId = getSelectedNodeIds().find(nodeId => nodes[nodeId]?.type === 'text');
    const recentTextId = selectedTextId || (nodes[lastPromptTextNodeIdRef.current]?.type === 'text' ? lastPromptTextNodeIdRef.current : '');
    const targetEdge = (DesktopState.state.canvas.edges || [])
      .find(edge => edge.from === groupId && ['input', 'comfy'].includes(nodes[edge.to]?.type));
    if (targetEdge) {
      const connectedTextId = findConnectedTextNodeId(targetEdge.to);
      if (connectedTextId) return connectedTextId;
      if (recentTextId) {
        connectNodes(recentTextId, targetEdge.to, { quiet: true });
        return recentTextId;
      }
      return setPromptTextForInputNode(targetEdge.to, '', { quiet: true });
    }
    if (recentTextId) return recentTextId;
    const groupNode = nodes[groupId];
    return createTextNodeWithText('', {
      x: (groupNode?.x || 0) + (groupNode?.width || DEFAULT_IMAGE_GROUP_NODE_WIDTH) + 70,
      y: groupNode?.y || 0
    });
  }

    function insertImageReferenceToken(groupId, itemId) {
    const groupNode = DesktopState.state.canvas.nodes[groupId];
    const item = getImageGroupItem(groupId, itemId);
    if (!groupNode || !item) return null;
    const textNodeId = resolveImageReferenceTextNode(groupId);
    const textNode = DesktopState.state.canvas.nodes[textNodeId];
    const textElement = getNodeElement(textNodeId);
    if (!textNode || textNode.type !== 'text' || !textElement) throw new Error('无法创建提示词引用');
    const promptDocument = clonePromptDocument(ensureTextNodePromptDocument(textNode), textNode.text || '');
    const existing = promptDocument.segments.find(segment => (
      segment.type === 'image_reference'
      && segment.group_id === groupId
      && segment.item_id === itemId
    ));
    if (existing) {
      selectNode(textNodeId);
      requestAnimationFrame(() => textElement.querySelector(`[data-image-reference-instance="${CSS.escape(existing.instance_id)}"]`)?.focus?.({ preventScroll: true }));
      DesktopResults.showTransientMessage(`${imageReferenceDisplay(existing)} 已在提示词中。`);
      return existing;
    }
    const visibleText = materializePromptDocument(promptDocument);
    if (visibleText && !/\s$/.test(visibleText)) promptDocument.segments.push({ type: 'text', text: ' ' });
    const segment = normalizeImageReferenceSegment({
      group_id: groupId,
      item_id: item.itemId,
      source_node_id: item.sourceNodeId,
      role_snapshot: item.role,
      label_snapshot: `@图片${groupNode.items.indexOf(item) + 1}`
    });
    promptDocument.segments.push(segment, { type: 'text', text: ' ' });
    setTextNodePromptDocument(textElement, textNode, promptDocument);
    textNodeModelTargetIds(textNodeId).forEach(targetNodeId => {
      const exists = (DesktopState.state.canvas.edges || []).some(edge => edge.from === groupId && edge.to === targetNodeId);
      if (!exists) connectNodes(groupId, targetNodeId, { quiet: true });
    });
    refreshImageReferenceTokens(groupId);
    selectNode(textNodeId);
    requestAnimationFrame(() => textElement.querySelector(`[data-image-reference-instance="${CSS.escape(segment.instance_id)}"]`)?.focus?.({ preventScroll: true }));
    const hasModelTarget = (DesktopState.state.canvas.edges || []).some(edge => edge.from === groupId && ['input', 'comfy'].includes(DesktopState.state.canvas.nodes[edge.to]?.type));
    DesktopResults.showTransientMessage(hasModelTarget
      ? `已插入 ${imageReferenceDisplay(segment)}。`
      : `已插入 ${imageReferenceDisplay(segment)}，请将图片组和文本节点连接到同一模型。`);
    return segment;
  }

    function textNodeHtml(node) {
    const alias = getTextNodeAlias(node);
    const promptDocument = ensureTextNodePromptDocument(node);
    return `
      <section class="desk-node desk-node--text" data-node-id="${node.id}" data-node-drag-handle aria-label="文本节点">
        <div class="desk-text-node__alias" data-text-node-alias-shell style="${textNodeAliasStyle(alias)}">
          <input type="text" data-text-node-alias value="${escapeHtml(alias)}" maxlength="${TEXT_NODE_ALIAS_MAX_LENGTH}" pattern="[A-Za-z0-9\u3400-\u9FFF,_-]{1,${TEXT_NODE_ALIAS_MAX_LENGTH}}" aria-label="文本节点别名" title="支持汉字、英文、数字、-、_、," readonly tabindex="-1">
          <button type="button" data-text-node-alias-edit data-alias-mode="edit" aria-label="编辑文本节点别名" title="编辑别名">
            <svg class="desk-text-node__alias-icon desk-text-node__alias-icon--edit" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 20h9"></path>
              <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"></path>
            </svg>
            <svg class="desk-text-node__alias-icon desk-text-node__alias-icon--apply" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M20 6 9 17l-5-5"></path>
            </svg>
          </button>
        </div>
        <div class="desk-text-node__styles" data-text-style-tags${node.stylePresetId ? '' : ' hidden'}>
          ${textStyleTagHtml(node.stylePresetId)}
        </div>
        <div class="desk-text-node__input" data-text-node-input data-empty="${promptDocumentHasEditorContent(promptDocument) ? 'false' : 'true'}" contenteditable="true" role="textbox" aria-multiline="true" aria-label="输入提示词或片段" data-placeholder="输入提示词或片段" spellcheck="false">${promptDocumentEditorHtml(promptDocument)}</div>
        <div class="desk-text-node__image-mention-menu" data-text-image-mention-menu data-node-drag-ignore hidden role="listbox" aria-label="引用画布图片"></div>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接提示词到模型节点" aria-label="连接文本输出"></button>
        <div class="desk-text-node__drawer" aria-label="文本节点操作">
          <button type="button" data-text-action="preset">预设风格</button>
          <button type="button" data-text-action="google-polish">google 润色</button>
          <button type="button" data-text-action="gpt-polish">Gpt 润色</button>
          <button type="button" data-text-action="safe-rewrite">安全审核版</button>
          <button type="button" data-text-action="clear" aria-label="清空文本节点" title="清空">❌</button>
        </div>
        <div class="desk-text-style-menu" data-text-style-menu hidden aria-label="选择预设风格">
          ${textStylePresetButtonsHtml()}
        </div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放文本节点" aria-hidden="true"></span>
      </section>
    `;
  }

    function setTextStyleMenuOpen(node, open) {
    const menu = node?.querySelector('[data-text-style-menu]');
    if (!menu) return;
    node.classList.toggle('is-style-menu-open', !!open);
    menu.hidden = !open;
  }

    function closeAllTextStyleMenus(exceptNode = null) {
    document.querySelectorAll('.desk-node--text.is-style-menu-open').forEach(node => {
      if (exceptNode && node === exceptNode) return;
      setTextStyleMenuOpen(node, false);
    });
  }

    function setTextNodeValue(node, nodeState, value) {
    const next = String(value || '');
    return setTextNodePromptDocument(node, nodeState, createTextPromptDocument(next));
  }

    function createPromptBlockTokenElement(segment) {
    const normalized = normalizePromptBlockSegment(segment);
    const template = document.createElement('template');
    template.innerHTML = promptBlockTokenHtml(normalized);
    const token = template.content.firstElementChild;
    if (token) token._promptBlockSegment = normalized;
    return token;
  }

    function createImageReferenceTokenElement(segment) {
    const normalized = normalizeImageReferenceSegment(segment);
    const template = document.createElement('template');
    template.innerHTML = imageReferenceTokenHtml(normalized);
    const token = template.content.firstElementChild;
    if (token) token._imageReferenceSegment = normalized;
    return token;
  }

    function isRangeInsidePromptEditor(range, editor) {
    if (!range || !editor) return false;
    try {
      return (range.startContainer === editor || editor.contains(range.startContainer))
        && (range.endContainer === editor || editor.contains(range.endContainer));
    } catch (error) {
      return false;
    }
  }

    function currentPromptEditorRange(editor) {
    const selection = window.getSelection?.();
    if (!selection?.rangeCount) return null;
    const range = selection.getRangeAt(0);
    return isRangeInsidePromptEditor(range, editor) ? range.cloneRange() : null;
  }

    function promptEditorEndRange(editor) {
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    return range;
  }

    function setPromptEditorCaret(range) {
    const selection = window.getSelection?.();
    if (!selection || !range) return;
    selection.removeAllRanges();
    selection.addRange(range);
  }

    function imageMentionCandidateKey(reference = {}) {
    const groupId = String(reference.imageGroupId || reference.groupId || '');
    const itemId = String(reference.imageGroupItemId || reference.itemId || '');
    if (groupId && itemId) return `group:${groupId}:${itemId}`;
    const sourceNodeId = String(reference.sourceNodeId || reference.nodeId || '');
    return sourceNodeId ? `node:${sourceNodeId}` : '';
  }

    function textImageMentionCandidates(textNodeId) {
    const nodes = DesktopState.state.canvas.nodes || {};
    const targetNodeId = textNodeModelTargetIds(textNodeId)[0] || '';
    const connectedReferences = targetNodeId ? getConnectedImageReferences(targetNodeId) : [];
    const connectedOrder = new Map();
    connectedReferences.forEach((reference, index) => {
      if (reference.imageGroupId || nodes[reference.sourceNodeId]?.type === 'image') {
        const key = imageMentionCandidateKey(reference);
        if (key) connectedOrder.set(key, index);
      }
    });
    return listPromptImageNodes()
      .map((reference, canvasIndex) => {
        const key = imageMentionCandidateKey(reference);
        if (!key) return null;
        const connectedIndex = connectedOrder.has(key) ? connectedOrder.get(key) : -1;
        const imageNumber = connectedIndex >= 0
          ? connectedIndex + 1
          : Math.max(1, Number(reference.imageNumber) || canvasIndex + 1);
        const role = normalizeImageGroupRole(reference.imageRole || 'reference');
        return {
          key,
          groupId: String(reference.imageGroupId || ''),
          itemId: String(reference.imageGroupItemId || ''),
          sourceNodeId: String(reference.sourceNodeId || reference.nodeId || ''),
          connectNodeId: String(reference.imageGroupId || reference.nodeId || reference.sourceNodeId || ''),
          imageNumber,
          role,
          roleLabel: imageGroupRoleLabel(role),
          name: String(reference.name || reference.title || reference.label || `图片${imageNumber}`),
          source: String(reference.imageData || reference.base64 || reference.imageUrl || reference.url || ''),
          connected: connectedIndex >= 0,
          canvasIndex
        };
      })
      .filter(Boolean)
      .sort((left, right) => {
        if (left.connected !== right.connected) return left.connected ? -1 : 1;
        if (left.connected && right.connected) return left.imageNumber - right.imageNumber;
        return left.canvasIndex - right.canvasIndex;
      });
  }

    function detectTextImageMention(editor) {
    const range = currentPromptEditorRange(editor);
    if (!range?.collapsed || range.startContainer.nodeType !== Node.TEXT_NODE) return null;
    const textNode = range.startContainer;
    const beforeCaret = String(textNode.nodeValue || '').slice(0, range.startOffset);
    const match = beforeCaret.match(/(^|[\s，,。；;、：:（(【\[])(@([^\s@，,。；;、：:（）()【】\[\]]*))$/);
    if (!match || match[3].length > 64) return null;
    const mentionRange = document.createRange();
    mentionRange.setStart(textNode, range.startOffset - match[2].length);
    mentionRange.setEnd(textNode, range.startOffset);
    return { range: mentionRange, query: match[3] };
  }

    function closeTextImageMention(editor = null) {
    if (!activeTextImageMentionRef.current || (editor && activeTextImageMentionRef.current.editor !== editor)) return;
    const { menu, node } = activeTextImageMentionRef.current;
    if (menu) {
      menu.hidden = true;
      menu.innerHTML = '';
      menu.style.removeProperty('left');
      menu.style.removeProperty('top');
    }
    node?.classList.remove('is-image-mention-open');
    activeTextImageMentionRef.current = null;
  }

    function positionTextImageMentionMenu(state) {
    const { range, menu, node, nodeState } = state;
    if (!range || !menu || !node) return;
    const caretRect = range.getBoundingClientRect();
    const nodeRect = node.getBoundingClientRect();
    const canvasScale = Math.max(0.01, Number(DesktopState.state.canvas.scale) || 1);
    const left = clamp(
      (caretRect.left - nodeRect.left) / canvasScale,
      8,
      Math.max(8, Number(nodeState.width || node.offsetWidth) - 248)
    );
    const top = clamp(
      (caretRect.bottom - nodeRect.top) / canvasScale + 6,
      34,
      Math.max(34, Number(nodeState.height || node.offsetHeight) - 18)
    );
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

    function renderTextImageMentionMenu(state) {
    const { menu, candidates, activeIndex, query } = state;
    if (!menu) return;
    menu.innerHTML = `
      <div class="desk-text-node__image-mention-head">
        <strong>引用图片</strong>
        <span>${query ? `匹配“${escapeHtml(query)}”` : '输入名称筛选'}</span>
      </div>
      <div class="desk-text-node__image-mention-list">
        ${candidates.length ? candidates.map((candidate, index) => `
          <button type="button" data-text-image-mention-pick="${index}" role="option" aria-selected="${index === activeIndex ? 'true' : 'false'}" class="${index === activeIndex ? 'is-active' : ''}">
            <span class="desk-text-node__image-mention-thumb">${candidate.source ? `<img src="${escapeHtml(candidate.source)}" alt="" draggable="false">` : '<i aria-hidden="true">图</i>'}</span>
            <span class="desk-text-node__image-mention-copy">
              <strong>@图片${candidate.imageNumber}<em>${escapeHtml(candidate.roleLabel)}</em></strong>
              <small>${escapeHtml(candidate.name)}</small>
            </span>
            ${candidate.connected ? '<b>已接入</b>' : '<b class="is-muted">未接入</b>'}
          </button>`).join('') : '<p class="desk-text-node__image-mention-empty">没有匹配的图片</p>'}
      </div>`;
    menu.hidden = false;
    state.node.classList.add('is-image-mention-open');
    positionTextImageMentionMenu(state);
  }

    function updateTextImageMention(editor) {
    const node = editor?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    const mention = nodeState?.type === 'text' ? detectTextImageMention(editor) : null;
    if (!mention) {
      closeTextImageMention(editor);
      return false;
    }
    const normalizedQuery = mention.query.trim().toLowerCase();
    const allCandidates = textImageMentionCandidates(nodeState.id);
    const candidates = normalizedQuery
      ? allCandidates.filter(candidate => (
        `图片${candidate.imageNumber} ${candidate.name} ${candidate.roleLabel}`.toLowerCase().includes(normalizedQuery)
      ))
      : allCandidates;
    const previousKey = activeTextImageMentionRef.current?.editor === editor
      ? activeTextImageMentionRef.current.candidates?.[activeTextImageMentionRef.current.activeIndex]?.key
      : '';
    let activeIndex = Math.max(0, candidates.findIndex(candidate => candidate.key === previousKey));
    if (!candidates.length) activeIndex = -1;
    const state = {
      editor,
      node,
      nodeState,
      menu: node.querySelector('[data-text-image-mention-menu]'),
      range: mention.range,
      query: mention.query,
      candidates,
      activeIndex
    };
    activeTextImageMentionRef.current = state;
    renderTextImageMentionMenu(state);
    return true;
  }

    function setTextImageMentionActiveIndex(index) {
    const state = activeTextImageMentionRef.current;
    if (!state?.candidates?.length) return;
    state.activeIndex = (index + state.candidates.length) % state.candidates.length;
    renderTextImageMentionMenu(state);
    state.menu?.querySelector(`[data-text-image-mention-pick="${state.activeIndex}"]`)?.scrollIntoView?.({ block: 'nearest' });
  }

    function ensureTextNodeImageReferenceConnections(textNodeId, targetNodeId) {
    const nodeState = DesktopState.state.canvas.nodes[textNodeId];
    const targetState = DesktopState.state.canvas.nodes[targetNodeId];
    if (nodeState?.type !== 'text' || !['input', 'comfy'].includes(targetState?.type)) return 0;
    const sourceIds = [...new Set(
      (ensureTextNodePromptDocument(nodeState)?.segments || [])
        .filter(segment => segment.type === 'image_reference')
        .map(segment => String(segment.group_id || segment.source_node_id || ''))
        .filter(sourceId => ['image', 'image_group'].includes(DesktopState.state.canvas.nodes[sourceId]?.type))
    )];
    let connected = 0;
    sourceIds.forEach(sourceId => {
      const exists = (DesktopState.state.canvas.edges || []).some(edge => edge.from === sourceId && edge.to === targetNodeId);
      if (exists) return;
      if (connectNodes(sourceId, targetNodeId, { quiet: true })) connected += 1;
    });
    return connected;
  }

    function insertTextImageMentionCandidate(candidateIndex = -1) {
    const state = activeTextImageMentionRef.current;
    if (!state || state.activeIndex < 0) return false;
    const candidate = state.candidates[candidateIndex >= 0 ? candidateIndex : state.activeIndex];
    if (!candidate || !isRangeInsidePromptEditor(state.range, state.editor)) return false;
    const historyEntry = beginPromptDocumentHistory(state.nodeState);
    const segment = normalizeImageReferenceSegment({
      group_id: candidate.groupId,
      item_id: candidate.itemId,
      source_node_id: candidate.sourceNodeId,
      role_snapshot: candidate.role,
      label_snapshot: `@图片${candidate.imageNumber}`
    });
    const token = createImageReferenceTokenElement(segment);
    if (!token) return false;
    const suffix = document.createTextNode(' ');
    const fragment = document.createDocumentFragment();
    fragment.append(token, suffix);
    state.range.deleteContents();
    state.range.insertNode(fragment);
    const caret = document.createRange();
    caret.setStartAfter(suffix);
    caret.collapse(true);
    closeTextImageMention(state.editor);
    selectNode(state.nodeState.id);
    state.editor.focus({ preventScroll: true });
    setPromptEditorCaret(caret);
    syncPromptDocumentFromEditor(state.editor, state.nodeState);
    commitPromptDocumentHistory(state.nodeState, historyEntry);
    textNodeModelTargetIds(state.nodeState.id).forEach(targetNodeId => {
      if (!candidate.connectNodeId) return;
      const exists = (DesktopState.state.canvas.edges || []).some(edge => (
        edge.from === candidate.connectNodeId && edge.to === targetNodeId
      ));
      if (!exists) connectNodes(candidate.connectNodeId, targetNodeId, { quiet: true });
    });
    refreshImageReferenceTokens();
    state.editor.focus({ preventScroll: true });
    setPromptEditorCaret(caret);
    state.editor.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
    DesktopResults.showTransientMessage(`已引用 ${imageReferenceDisplay(segment)}，可继续输入具体要求。`);
    return true;
  }

    function handleTextImageMentionKeydown(event, editor) {
    const state = activeTextImageMentionRef.current;
    if (!state || state.editor !== editor || event.isComposing) return false;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      event.stopPropagation();
      setTextImageMentionActiveIndex(state.activeIndex + (event.key === 'ArrowDown' ? 1 : -1));
      return true;
    }
    if ((event.key === 'Enter' || event.key === 'Tab') && state.activeIndex >= 0) {
      event.preventDefault();
      event.stopPropagation();
      insertTextImageMentionCandidate();
      return true;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeTextImageMention(editor);
      return true;
    }
    return false;
  }

    function resolvePromptTokenEditor(options = {}) {
    const requestedTarget = options.target?.nodeType
      ? options.target.closest?.('[data-text-node-input]')
      : null;
    let editor = requestedTarget?.closest?.('.desk-node--text[data-node-id]') ? requestedTarget : null;
    let node = editor?.closest?.('.desk-node--text[data-node-id]') || null;
    let nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    const requestedInfo = options.targetInfo
      || (!options.target?.nodeType && options.target && typeof options.target === 'object' ? options.target : null);
    const requestedNodeId = String(requestedInfo?.nodeId || options.nodeId || '');
    if ((!nodeState || nodeState.type !== 'text') && requestedNodeId) {
      const candidate = DesktopState.state.canvas.nodes[requestedNodeId];
      if (candidate?.type === 'text') {
        ensureGraphDom();
        node = getNodeElement(requestedNodeId);
        editor = node?.querySelector('[data-text-node-input]') || null;
        nodeState = candidate;
      }
    }
    if (!nodeState || nodeState.type !== 'text') {
      const selectedNodeId = getSelectedNodeIds()
        .find(nodeId => DesktopState.state.canvas.nodes[nodeId]?.type === 'text')
        || (DesktopState.state.canvas.nodes[DesktopState.state.canvas.selectedNodeId]?.type === 'text'
          ? DesktopState.state.canvas.selectedNodeId
          : '');
      if (selectedNodeId) {
        ensureGraphDom();
        node = getNodeElement(selectedNodeId);
        editor = node?.querySelector('[data-text-node-input]') || null;
        nodeState = DesktopState.state.canvas.nodes[selectedNodeId];
      }
    }
    return editor && node && nodeState?.type === 'text' ? { editor, node, nodeState } : null;
  }

    function insertPromptBlockToken(block, options = {}) {
    const resolved = resolvePromptTokenEditor(options);
    if (!resolved) throw new Error('请先选择文本节点');
    const { editor, node, nodeState } = resolved;
    ensureTextNodePromptDocument(nodeState);
    let range = null;
    if (isRangeInsidePromptEditor(options.range, editor)) {
      try { range = options.range.cloneRange(); } catch (error) { range = null; }
    }
    if (!range && options.target?.nodeType && editor === options.target.closest?.('[data-text-node-input]')) {
      range = currentPromptEditorRange(editor);
    }
    const appendToEnd = !range;
    if (!range) range = promptEditorEndRange(editor);
    const segment = normalizePromptBlockSegment(block);
    const token = createPromptBlockTokenElement(segment);
    if (!token) throw new Error('素材块无法插入');
    const currentText = materializeTextNode(nodeState);
    const prefixText = appendToEnd && currentText && !/[\s，,。；;、]$/.test(currentText) ? '，' : '';
    const followingCharacter = range.endContainer.nodeType === Node.TEXT_NODE
      ? String(range.endContainer.nodeValue || '').slice(range.endOffset, range.endOffset + 1)
      : '';
    const suffixText = followingCharacter && /^[\s，,。；;、]/.test(followingCharacter) ? '' : ' ';
    const suffix = suffixText ? document.createTextNode(suffixText) : null;
    const fragment = document.createDocumentFragment();
    if (prefixText) fragment.appendChild(document.createTextNode(prefixText));
    fragment.appendChild(token);
    if (suffix) fragment.appendChild(suffix);
    const historyEntry = beginPromptDocumentHistory(nodeState);
    range.deleteContents();
    range.insertNode(fragment);
    const caret = document.createRange();
    caret.setStartAfter(suffix || token);
    caret.collapse(true);
    selectNode(nodeState.id);
    editor.focus({ preventScroll: true });
    setPromptEditorCaret(caret);
    syncPromptDocumentFromEditor(editor, nodeState);
    commitPromptDocumentHistory(nodeState, historyEntry);
    setTextStyleMenuOpen(node, false);
    editor.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
    return { nodeId: nodeState.id, instanceId: segment.instance_id, token };
  }

    function findPromptBlockTokenElement(instanceId) {
    return Array.from(document.querySelectorAll('[data-prompt-block-token]'))
      .find(token => String(token.dataset.promptBlockInstance || token.dataset.promptBlockInstanceId || '') === String(instanceId || ''))
      || null;
  }

    function replacePromptBlockToken(tokenOrInstance, block) {
    let token = tokenOrInstance?.nodeType
      ? tokenOrInstance.closest?.('[data-prompt-block-token]')
      : findPromptBlockTokenElement(tokenOrInstance);
    const requestedInstanceId = String(
      token?.dataset.promptBlockInstance
      || token?.dataset.promptBlockInstanceId
      || (typeof tokenOrInstance === 'string' ? tokenOrInstance : '')
    );
    if (!requestedInstanceId) throw new Error('素材块实例不存在');
    let node = token?.closest?.('.desk-node--text[data-node-id]') || null;
    let nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    if (!nodeState || nodeState.type !== 'text') {
      nodeState = Object.values(DesktopState.state.canvas.nodes).find(item => (
        item?.type === 'text'
        && normalizePromptDocument(item.promptDocument, item.text || '').segments
          .some(segment => segment.type === 'prompt_block' && segment.instance_id === requestedInstanceId)
      ));
      if (!nodeState) throw new Error('素材块实例不存在');
      ensureGraphDom();
      node = getNodeElement(nodeState.id);
      token = findPromptBlockTokenElement(requestedInstanceId);
    }
    const promptDocument = clonePromptDocument(ensureTextNodePromptDocument(nodeState), nodeState.text || '');
    const index = promptDocument.segments.findIndex(segment => (
      segment.type === 'prompt_block' && segment.instance_id === requestedInstanceId
    ));
    if (index < 0) throw new Error('素材块实例不存在');
    promptDocument.segments[index] = normalizePromptBlockSegment({
      ...(block && typeof block === 'object' ? block : {}),
      instance_id: requestedInstanceId
    });
    setTextNodePromptDocument(node, nodeState, promptDocument);
    selectNode(nodeState.id);
    const nextToken = findPromptBlockTokenElement(requestedInstanceId);
    nextToken?.focus?.({ preventScroll: true });
    return { nodeId: nodeState.id, instanceId: requestedInstanceId, token: nextToken };
  }

    function insertPlainTextIntoPromptEditor(editor, text) {
    const node = editor?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    if (!editor || !nodeState) return false;
    const range = currentPromptEditorRange(editor) || promptEditorEndRange(editor);
    const historyEntry = beginPromptDocumentHistory(nodeState);
    range.deleteContents();
    const textNode = document.createTextNode(String(text || '').replace(/\r\n?/g, '\n'));
    range.insertNode(textNode);
    const caret = document.createRange();
    caret.setStartAfter(textNode);
    caret.collapse(true);
    setPromptEditorCaret(caret);
    syncPromptDocumentFromEditor(editor, nodeState);
    commitPromptDocumentHistory(nodeState, historyEntry);
    editor.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
    return true;
  }

    function adjacentPromptToken(range, editor, direction) {
    if (!range?.collapsed || !isRangeInsidePromptEditor(range, editor)) return null;
    let container = range.startContainer;
    let offset = range.startOffset;
    if (container.nodeType === Node.TEXT_NODE) {
      const length = (container.nodeValue || '').length;
      if ((direction < 0 && offset > 0) || (direction > 0 && offset < length)) return null;
    } else if (container.nodeType === Node.ELEMENT_NODE) {
      const index = direction < 0 ? offset - 1 : offset;
      const direct = container.childNodes[index];
      if (direct) {
        if (direct.nodeType === Node.ELEMENT_NODE && direct.matches?.(PROMPT_TOKEN_SELECTOR)) return direct;
        if (direct.nodeType === Node.TEXT_NODE && (direct.nodeValue || '').length) return null;
      }
    }
    let current = container.nodeType === Node.TEXT_NODE ? container : null;
    if (!current && container !== editor) current = container;
    while (current && current !== editor) {
      const sibling = direction < 0 ? current.previousSibling : current.nextSibling;
      if (sibling) {
        if (sibling.nodeType === Node.ELEMENT_NODE && sibling.matches?.(PROMPT_TOKEN_SELECTOR)) return sibling;
        return null;
      }
      current = current.parentNode;
    }
    return null;
  }

    function handlePromptEditorTokenDelete(event, editor) {
    if (event.key !== 'Backspace' && event.key !== 'Delete') return false;
    const focusedToken = event.target.closest?.(PROMPT_TOKEN_SELECTOR);
    const selection = window.getSelection?.();
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
    const token = focusedToken || adjacentPromptToken(range, editor, event.key === 'Backspace' ? -1 : 1);
    if (!token || !editor.contains(token)) return false;
    event.preventDefault();
    event.stopPropagation();
    const parent = token.parentNode;
    const index = Array.prototype.indexOf.call(parent.childNodes, token);
    const node = editor.closest('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    const historyEntry = beginPromptDocumentHistory(nodeState);
    token.remove();
    const caret = document.createRange();
    caret.setStart(parent, Math.max(0, Math.min(index, parent.childNodes.length)));
    caret.collapse(true);
    editor.focus({ preventScroll: true });
    setPromptEditorCaret(caret);
    if (nodeState) {
      syncPromptDocumentFromEditor(editor, nodeState);
      commitPromptDocumentHistory(nodeState, historyEntry);
    }
    editor.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
    return true;
  }

    function updateTextStyleTag(node, nodeState) {
    const target = node?.querySelector('[data-text-style-tags]');
    if (!target) return;
    const presetId = nodeState?.stylePresetId || '';
    target.innerHTML = textStyleTagHtml(presetId);
    target.hidden = !getTextStylePreset(presetId);
  }

    function setTextNodeStyle(node, nodeState, presetId) {
    const preset = getTextStylePreset(presetId);
    nodeState.stylePresetId = preset ? preset.id : '';
    updateTextStyleTag(node, nodeState);
    DesktopState.saveSettings();
    return preset;
  }

    function selectTextNodePreset(node, nodeState, presetId) {
    const preset = setTextNodeStyle(node, nodeState, presetId);
    if (!preset) return;
    setTextStyleMenuOpen(node, false);
    DesktopResults.showTransientMessage(`已选择「${preset.title}」风格。`);
  }

    function clearTextNodeStyle(node, nodeState) {
    const hadStyle = !!nodeState.stylePresetId;
    setTextNodeStyle(node, nodeState, '');
    if (hadStyle) DesktopResults.showTransientMessage('已移除风格标签。');
  }

    function ensureTextCopyFallback() {
    let modal = document.getElementById('deskTextCopyFallback');
    if (modal) return modal;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="desk-text-copy-fallback" id="deskTextCopyFallback" aria-hidden="true">
        <div class="desk-text-copy-fallback__panel desk-glass">
          <header>
            <div>
              <p>Clipboard</p>
              <h2>手动复制</h2>
            </div>
            <button type="button" data-copy-fallback-close title="关闭" aria-label="关闭">×</button>
          </header>
          <p class="desk-text-copy-fallback__hint">系统剪贴板受限，文本已选中。</p>
          <textarea data-copy-fallback-text readonly></textarea>
          <footer>
            <button type="button" data-copy-fallback-select>重新选中</button>
            <button type="button" class="is-primary" data-copy-fallback-close>完成</button>
          </footer>
        </div>
      </div>
    `);
    modal = document.getElementById('deskTextCopyFallback');
    modal?.addEventListener('click', event => {
      if (event.target === modal || event.target.closest('[data-copy-fallback-close]')) {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        return;
      }
      if (event.target.closest('[data-copy-fallback-select]')) {
        event.preventDefault();
        selectTextCopyFallback();
      }
    });
    return modal;
  }

    function selectTextCopyFallback() {
    const textarea = document.querySelector('#deskTextCopyFallback [data-copy-fallback-text]');
    if (!textarea) return;
    textarea.focus({ preventScroll: true });
    textarea.select();
    try { textarea.setSelectionRange(0, textarea.value.length); } catch (e) {}
  }

    function showTextCopyFallback(text) {
    const modal = ensureTextCopyFallback();
    const textarea = modal.querySelector('[data-copy-fallback-text]');
    if (textarea) textarea.value = String(text || '');
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    window.requestAnimationFrame(() => selectTextCopyFallback());
  }

    function copyTextWithTemporaryTextarea(value) {
    const ta = document.createElement('textarea');
    const previousFocus = document.activeElement;
    ta.value = value;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.width = '1px';
    ta.style.height = '1px';
    ta.style.padding = '0';
    ta.style.border = '0';
    ta.style.opacity = '0.01';
    ta.style.zIndex = '-1';
    document.body.appendChild(ta);
    try {
      ta.focus({ preventScroll: true });
      ta.select();
      ta.setSelectionRange(0, value.length);
      return document.execCommand && document.execCommand('copy') === true;
    } catch (e) {
      return false;
    } finally {
      document.body.removeChild(ta);
      if (previousFocus && typeof previousFocus.focus === 'function') {
        try { previousFocus.focus({ preventScroll: true }); } catch (e) {}
      }
    }
  }

    async function copyTextToClipboardLocal(text, successMessage = '已复制') {
    const value = String(text || '');
    if (!value) {
      DesktopResults.showTransientMessage('暂无可复制内容。');
      return 'empty';
    }
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        DesktopResults.showTransientMessage(successMessage);
        return 'copied';
      } catch (e) {}
    }
    if (copyTextWithTemporaryTextarea(value)) {
      DesktopResults.showTransientMessage(successMessage);
      return 'copied';
    }
    showTextCopyFallback(value);
    DesktopResults.showTransientMessage('自动复制受限，已打开手动复制框。');
    return 'manual';
  }

    function setPolishCopyButtonState(button, state) {
    if (!button) return;
    const labels = {
      idle: button.dataset.copyDefaultLabel || '复制当前',
      copying: '复制中',
      copied: '已复制',
      manual: '手动复制',
      empty: '无内容',
      failed: '复制受限'
    };
    if (!button.dataset.copyDefaultLabel) button.dataset.copyDefaultLabel = button.textContent.trim() || '复制当前';
    if (button._copyFeedbackTimer) window.clearTimeout(button._copyFeedbackTimer);
    button.dataset.copyState = state;
    button.textContent = labels[state] || labels.idle;
    button.setAttribute('aria-live', 'polite');
    button.setAttribute('aria-busy', state === 'copying' ? 'true' : 'false');
    if (state !== 'copying') button.disabled = false;
    if (state === 'copied' || state === 'manual' || state === 'empty' || state === 'failed') {
      button._copyFeedbackTimer = window.setTimeout(() => {
        button.dataset.copyState = 'idle';
        button.textContent = button.dataset.copyDefaultLabel || '复制当前';
        button.setAttribute('aria-busy', 'false');
      }, state === 'manual' ? 2200 : 1500);
    }
  }

    function ensureTextPolishModal() {
    let modal = document.getElementById('deskTextPolishModal');
    if (modal) return modal;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="desk-text-polish-modal" id="deskTextPolishModal" aria-hidden="true">
        <div class="desk-text-polish-modal__panel desk-glass">
          <header class="desk-text-polish-modal__header">
            <div class="desk-text-polish-modal__title">
              <p>Prompt Skill</p>
              <h2>GPT 润色结果</h2>
            </div>
            <button type="button" class="desk-text-polish-modal__close" data-polish-close title="关闭" aria-label="关闭"></button>
          </header>
          <div class="desk-text-polish-modal__grid" role="listbox" aria-label="润色候选提示">
            ${TEXT_POLISH_VARIANTS.map(item => `
              <button type="button" class="desk-text-polish-modal__card${item.id === 'full' ? ' is-active' : ''}" data-polish-variant-card data-polish-variant="${item.id}" aria-pressed="${item.id === 'full' ? 'true' : 'false'}">
                <span class="desk-text-polish-modal__card-head">
                  <strong>${escapeHtml(item.title)}</strong>
                  <em data-polish-count="${item.id}">0 字</em>
                </span>
                <span class="desk-text-polish-modal__card-hint">${escapeHtml(item.hint)}</span>
                <span class="desk-text-polish-modal__card-text" data-polish-card-text="${item.id}"></span>
              </button>
            `).join('')}
          </div>
          <footer class="desk-text-polish-modal__footer">
            <div class="desk-text-polish-modal__meta" data-polish-meta></div>
            <div class="desk-text-polish-modal__actions">
              <button type="button" class="desk-text-polish-modal__copy" data-polish-copy>复制当前</button>
              <button type="button" data-polish-undo hidden>撤销应用</button>
              <button type="button" data-polish-create data-polish-create-node>新建文本节点</button>
              <button type="button" class="is-primary" data-polish-apply data-polish-apply-current>应用到当前节点</button>
              <button type="button" class="desk-text-polish-modal__done is-primary" data-polish-close>完成</button>
            </div>
          </footer>
        </div>
      </div>
    `);
    modal = document.getElementById('deskTextPolishModal');
    modal?.addEventListener('click', event => {
      if (event.target === modal || event.target.closest('[data-polish-close]')) {
        closeTextPolishModal();
        return;
      }
      const variantButton = event.target.closest('[data-polish-variant-card]');
      if (variantButton) {
        event.preventDefault();
        applyTextPolishVariant(variantButton.dataset.polishVariant || 'full');
        return;
      }
      const copyButton = event.target.closest('[data-polish-copy]');
      if (copyButton) {
        event.preventDefault();
        setPolishCopyButtonState(copyButton, 'copying');
        copyTextToClipboardLocal(getTextPolishVariantText(textPolishState?.variant || 'full'), '当前提示词已复制。')
          .then(status => setPolishCopyButtonState(copyButton, status || 'failed'))
          .catch(() => setPolishCopyButtonState(copyButton, 'failed'));
        return;
      }
      if (event.target.closest('[data-polish-apply-current]')) {
        event.preventDefault();
        applyCurrentTextPolishVariant();
        return;
      }
      if (event.target.closest('[data-polish-create-node]')) {
        event.preventDefault();
        createTextNodeFromPolishVariant();
        return;
      }
      if (event.target.closest('[data-polish-undo]')) {
        event.preventDefault();
        undoAppliedTextPolish();
      }
    });
    document.addEventListener('prompt-editor:change', event => {
      if (!textPolishState || !modal?.classList.contains('is-open')) return;
      const changedNodeId = event.target?.closest?.('.desk-node--text[data-node-id]')?.dataset.nodeId || '';
      if (changedNodeId === textPolishState.nodeId) renderTextPolishModal();
    });
    return modal;
  }

    function closeTextPolishModal() {
    const modal = document.getElementById('deskTextPolishModal');
    modal?.classList.remove('is-open');
    modal?.setAttribute('aria-hidden', 'true');
  }

    function getTextPolishVariantText(variant) {
    if (!textPolishState) return '';
    if (variant === 'compact') return textPolishState.compactPrompt || '';
    if (variant === 'original') return textPolishState.originalText || '';
    return textPolishState.fullPrompt || '';
  }

    function renderTextPolishModal() {
    const modal = ensureTextPolishModal();
    const meta = modal.querySelector('[data-polish-meta]');
    const variant = textPolishState?.variant || 'full';
    TEXT_POLISH_VARIANTS.forEach(item => {
      const text = getTextPolishVariantText(item.id);
      const cardText = modal.querySelector(`[data-polish-card-text="${item.id}"]`);
      const count = modal.querySelector(`[data-polish-count="${item.id}"]`);
      if (cardText) cardText.textContent = text || '暂无内容';
      if (count) count.textContent = `${Array.from(text || '').length} 字`;
    });
    modal.querySelectorAll('[data-polish-variant-card]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.polishVariant === variant);
      button.setAttribute('aria-pressed', button.dataset.polishVariant === variant ? 'true' : 'false');
    });
    const targetNodeState = DesktopState.state.canvas.nodes[textPolishState?.nodeId || ''];
    const targetNodeExists = !!targetNodeState;
    const currentFingerprint = targetNodeState
      ? promptDocumentFingerprint(ensureTextNodePromptDocument(targetNodeState), targetNodeState.text || '')
      : '';
    const expectedFingerprint = textPolishState?.applied
      ? textPolishState.appliedFingerprint
      : textPolishState?.sourceFingerprint;
    const targetChanged = !!targetNodeExists
      && !!expectedFingerprint
      && currentFingerprint !== expectedFingerprint;
    const currentText = getTextPolishVariantText(variant);
    const applyButton = modal.querySelector('[data-polish-apply-current]');
    const createButton = modal.querySelector('[data-polish-create-node]');
    const undoButton = modal.querySelector('[data-polish-undo]');
    if (applyButton) applyButton.disabled = !targetNodeExists || !currentText || targetChanged;
    if (createButton) createButton.disabled = !currentText;
    if (undoButton) {
      undoButton.hidden = !textPolishState?.applied || !targetNodeExists;
      undoButton.disabled = !textPolishState?.applied || !targetNodeExists || targetChanged;
      undoButton.title = targetChanged ? '文本节点已继续编辑，不能覆盖当前内容' : '';
    }
    if (meta) {
      const modules = (textPolishState?.modules || []).join(' / ');
      const model = textPolishState?.model || '';
      const applied = textPolishState?.applied && !targetChanged ? '已应用到当前节点，可撤销' : '';
      const changed = targetChanged ? '文本节点已修改，请重新润色或新建节点' : '';
      meta.textContent = [model, modules, applied, changed].filter(Boolean).join(' · ');
    }
  }

    function applyTextPolishVariant(variant) {
    if (!textPolishState) return;
    const normalized = TEXT_POLISH_VARIANTS.some(item => item.id === variant) ? variant : 'full';
    textPolishState.variant = normalized;
    renderTextPolishModal();
  }

    function applyCurrentTextPolishVariant() {
    if (!textPolishState) return false;
    const node = getNodeElement(textPolishState.nodeId);
    const nodeState = DesktopState.state.canvas.nodes[textPolishState.nodeId];
    const text = getTextPolishVariantText(textPolishState.variant || 'full');
    if (!node || !nodeState) {
      DesktopResults.showTransientMessage('原文本节点已不存在。', 'warning');
      renderTextPolishModal();
      return false;
    }
    if (!text) return false;
    const currentFingerprint = promptDocumentFingerprint(
      ensureTextNodePromptDocument(nodeState),
      nodeState.text || ''
    );
    const expectedFingerprint = textPolishState.applied
      ? textPolishState.appliedFingerprint
      : textPolishState.sourceFingerprint;
    if (expectedFingerprint && currentFingerprint !== expectedFingerprint) {
      DesktopResults.showTransientMessage('文本节点已继续编辑，请重新润色或新建节点。', 'warning');
      renderTextPolishModal();
      return false;
    }
    const variant = textPolishState.variant || 'full';
    const nextDocument = variant === 'original'
      ? clonePromptDocument(textPolishState.originalDocument, textPolishState.originalText)
      : createTextPromptDocument(text);
    setTextNodePromptDocument(node, nodeState, nextDocument);
    const restoredOriginal = variant === 'original';
    textPolishState.applied = !restoredOriginal;
    textPolishState.appliedVariant = restoredOriginal ? '' : variant;
    textPolishState.appliedFingerprint = restoredOriginal
      ? ''
      : promptDocumentFingerprint(ensureTextNodePromptDocument(nodeState), nodeState.text || '');
    selectNode(nodeState.id);
    renderTextPolishModal();
    DesktopResults.showTransientMessage(restoredOriginal
      ? '已恢复润色前的结构化内容。'
      : '润色结果已应用到当前文本节点。');
    return true;
  }

    function createTextNodeFromPolishVariant() {
    if (!textPolishState) return '';
    const text = getTextPolishVariantText(textPolishState.variant || 'full');
    if (!text) return '';
    const source = DesktopState.state.canvas.nodes[textPolishState.nodeId];
    const worldPoint = source
      ? { x: source.x + source.width + DEFAULT_TEXT_NODE_WIDTH / 2 + 48, y: source.y + source.height / 2 }
      : null;
    const nodeId = createTextNodeWithText(text, worldPoint);
    const createdNode = DesktopState.state.canvas.nodes[nodeId];
    const createdElement = getNodeElement(nodeId);
    if (createdNode && createdElement && textPolishState.variant === 'original') {
      setTextNodePromptDocument(
        createdElement,
        createdNode,
        clonePromptDocument(textPolishState.originalDocument, textPolishState.originalText)
      );
    }
    if (createdNode && createdElement && source?.stylePresetId) {
      createdNode.stylePresetId = source.stylePresetId;
      updateTextStyleTag(createdElement, createdNode);
      DesktopState.saveSettings();
    }
    DesktopResults.showTransientMessage('已新建未连接的文本节点。');
    return nodeId;
  }

    function undoAppliedTextPolish() {
    if (!textPolishState?.applied) return false;
    const node = getNodeElement(textPolishState.nodeId);
    const nodeState = DesktopState.state.canvas.nodes[textPolishState.nodeId];
    if (!node || !nodeState) {
      DesktopResults.showTransientMessage('原文本节点已不存在。', 'warning');
      renderTextPolishModal();
      return false;
    }
    const currentFingerprint = promptDocumentFingerprint(
      ensureTextNodePromptDocument(nodeState),
      nodeState.text || ''
    );
    if (!textPolishState.appliedFingerprint || currentFingerprint !== textPolishState.appliedFingerprint) {
      DesktopResults.showTransientMessage('文本节点已继续编辑，未覆盖当前内容。', 'warning');
      renderTextPolishModal();
      return false;
    }
    setTextNodePromptDocument(node, nodeState, clonePromptDocument(textPolishState.originalDocument, textPolishState.originalText));
    textPolishState.applied = false;
    textPolishState.appliedVariant = '';
    textPolishState.appliedFingerprint = '';
    selectNode(nodeState.id);
    renderTextPolishModal();
    DesktopResults.showTransientMessage('已恢复润色前的结构化内容。');
    return true;
  }

    function openTextPolishModal(payload) {
    textPolishState = {
      nodeId: payload.nodeId,
      originalText: payload.originalText || '',
      originalDocument: clonePromptDocument(payload.originalDocument, payload.originalText || ''),
      sourceFingerprint: payload.sourceFingerprint
        || promptDocumentFingerprint(payload.originalDocument, payload.originalText || ''),
      fullPrompt: payload.fullPrompt || '',
      compactPrompt: payload.compactPrompt || payload.fullPrompt || '',
      modules: payload.modules || [],
      model: payload.model || '',
      variant: 'full',
      applied: false,
      appliedVariant: '',
      appliedFingerprint: ''
    };
    const modal = ensureTextPolishModal();
    renderTextPolishModal();
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
  }

    function textNodeModelTargetIds(textNodeId) {
    const nodes = DesktopState.state.canvas.nodes || {};
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === textNodeId && ['input', 'comfy'].includes(nodes[edge.to]?.type))
      .map(edge => edge.to);
  }

    return Object.freeze({
      updatePromptEditorEmptyState,
      shortPromptBlockLabel,
      promptBlockModuleLabel,
      promptBlockModuleMark,
      promptBlockTokenHtml,
      imageReferenceTokenHtml,
      syncImageReferenceTokenElement,
      promptDocumentEditorHtml,
      promptDocumentFromEditor,
      renderPromptDocumentToEditor,
      setTextNodePromptDocument,
      syncPromptDocumentFromEditor,
      focusPromptEditorAtEnd,
      undoPromptDocumentChange,
      redoPromptDocumentChange,
      handlePromptDocumentHistoryShortcut,
      sanitizeTextNodeAlias,
      nextTextNodeAlias,
      getTextNodeAlias,
      textNodeAliasMeasure,
      textNodeAliasStyle,
      updateTextNodeAliasMetrics,
      setTextNodeAliasEditing,
      commitTextNodeAliasInput,
      revertTextNodeAliasInput,
      ensureTextNodeAliases,
      listTextNodes,
      notifyTextNodeListChange,
      textStylePresetButtonsHtml,
      loadCustomTextStylePresets,
      saveCustomTextStylePresets,
      allTextStylePresets,
      getTextStylePreset,
      textStyleTagHtml,
      getPromptTargetInfo,
      getPromptTargetText,
      fillPromptTarget,
      fillNearestInputPrompt,
      createTextNodeWithText,
      findConnectedTextNodeId,
      setPromptTextForInputNode,
      getTextStylePresets,
      createTextStylePreset,
      registerTextStylePresets,
      applyTextStylePresetToTarget,
      migrateImageReferenceTokensToGroup,
      freezeImageReferenceTokensMatching,
      freezeImageReferenceTokens,
      freezeImageReferenceTokensForSourceNode,
      refreshImageReferenceTokens,
      resolveImageReferenceTextNode,
      insertImageReferenceToken,
      textNodeHtml,
      setTextStyleMenuOpen,
      closeAllTextStyleMenus,
      setTextNodeValue,
      createPromptBlockTokenElement,
      createImageReferenceTokenElement,
      isRangeInsidePromptEditor,
      currentPromptEditorRange,
      promptEditorEndRange,
      setPromptEditorCaret,
      imageMentionCandidateKey,
      textImageMentionCandidates,
      detectTextImageMention,
      closeTextImageMention,
      positionTextImageMentionMenu,
      renderTextImageMentionMenu,
      updateTextImageMention,
      setTextImageMentionActiveIndex,
      ensureTextNodeImageReferenceConnections,
      insertTextImageMentionCandidate,
      handleTextImageMentionKeydown,
      resolvePromptTokenEditor,
      insertPromptBlockToken,
      findPromptBlockTokenElement,
      replacePromptBlockToken,
      insertPlainTextIntoPromptEditor,
      adjacentPromptToken,
      handlePromptEditorTokenDelete,
      updateTextStyleTag,
      setTextNodeStyle,
      selectTextNodePreset,
      clearTextNodeStyle,
      ensureTextCopyFallback,
      selectTextCopyFallback,
      showTextCopyFallback,
      copyTextWithTemporaryTextarea,
      copyTextToClipboardLocal,
      setPolishCopyButtonState,
      ensureTextPolishModal,
      closeTextPolishModal,
      getTextPolishVariantText,
      renderTextPolishModal,
      applyTextPolishVariant,
      applyCurrentTextPolishVariant,
      createTextNodeFromPolishVariant,
      undoAppliedTextPolish,
      openTextPolishModal,
      textNodeModelTargetIds,
    });
  }

  window.DesktopCanvasTextEditor = Object.freeze({ create });
})();
