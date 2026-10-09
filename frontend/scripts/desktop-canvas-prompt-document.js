// 提示词文档 schema/segments 规范化、图片引用语义解析、物化和忠实度、版本/历史模型、生成元数据及连接文本提示词编排；不读取编辑 DOM、不调用 Provider API。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    PROMPT_BLOCK_MAX_CONTENT_LENGTH,
    PROMPT_BLOCK_MAX_ID_LENGTH,
    PROMPT_BLOCK_MAX_LABEL_LENGTH,
    PROMPT_DOCUMENT_HISTORY_LIMIT,
    PROMPT_DOCUMENT_MAX_LENGTH,
    PROMPT_DOCUMENT_MAX_SEGMENTS,
    PROMPT_DOCUMENT_SCHEMA,
    PROMPT_DOCUMENT_VERSION,
    getConnectedImageReferences,
    getImageGroupItem,
    getTextStylePreset,
    imageGroupRolePromptBlock,
    jsonClone,
    listPromptImageNodes,
    normalizeImageGroupRole,
    promptDocumentHistories,
    promptDocumentVersions,
  }) {
    let promptBlockInstanceSequence = 0;
    let imageReferenceInstanceSequence = 0;

    function createPromptBlockInstanceId() {
    promptBlockInstanceSequence += 1;
    const unique = globalThis.crypto?.randomUUID?.()?.replaceAll('-', '')
      || `${Date.now().toString(36)}${promptBlockInstanceSequence.toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    return `prompt_block_${unique}`;
  }

    function createImageReferenceInstanceId() {
    imageReferenceInstanceSequence += 1;
    const unique = globalThis.crypto?.randomUUID?.()?.replaceAll('-', '')
      || `${Date.now().toString(36)}${imageReferenceInstanceSequence.toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    return `image_reference_${unique}`;
  }

    function imageReferenceRole(segment = {}) {
    const groupId = String(segment.group_id ?? segment.groupId ?? '');
    const itemId = String(segment.item_id ?? segment.itemId ?? '');
    const sourceNodeId = String(segment.source_node_id ?? segment.sourceNodeId ?? '');
    const item = getImageGroupItem(groupId, itemId, sourceNodeId);
    return normalizeImageGroupRole(item?.role || segment.role_snapshot || segment.roleSnapshot);
  }

    function imageReferenceTargetNodeId(segment = {}, sourceId = '') {
    const nodes = DesktopState.state.canvas.nodes || {};
    const edges = DesktopState.state.canvas.edges || [];
    const instanceId = String(segment.instance_id ?? segment.instanceId ?? '');
    const owner = instanceId
      ? Object.values(nodes).find(node => (
        node?.type === 'text'
        && Array.isArray(node.promptDocument?.segments)
        && node.promptDocument.segments.some(item => (
          item?.type === 'image_reference'
          && String(item.instance_id ?? item.instanceId ?? '') === instanceId
        ))
      ))
      : null;
    const ownerTargets = owner
      ? edges
        .filter(edge => edge.from === owner.id && ['input', 'comfy'].includes(nodes[edge.to]?.type))
        .map(edge => edge.to)
      : [];
    const sharedTarget = ownerTargets.find(targetId => edges.some(edge => edge.from === sourceId && edge.to === targetId));
    if (sharedTarget) return sharedTarget;
    return edges.find(edge => edge.from === sourceId && ['input', 'comfy'].includes(nodes[edge.to]?.type))?.to || '';
  }

    function imageReferenceNumber(segment = {}) {
    const groupId = String(segment.group_id ?? segment.groupId ?? '');
    const itemId = String(segment.item_id ?? segment.itemId ?? '');
    const sourceNodeId = String(segment.source_node_id ?? segment.sourceNodeId ?? '');
    const group = DesktopState.state.canvas.nodes[groupId];
    const item = getImageGroupItem(groupId, itemId, sourceNodeId);
    const sourceId = group && item ? groupId : sourceNodeId;
    const targetNodeId = sourceId ? imageReferenceTargetNodeId(segment, sourceId) : '';
    if (targetNodeId) {
      const globalIndex = getConnectedImageReferences(targetNodeId).findIndex(reference => (
        group && item
          ? reference.imageGroupId === groupId && reference.imageGroupItemId === item.itemId
          : !reference.imageGroupId && reference.sourceNodeId === sourceNodeId
      ));
      if (globalIndex >= 0) return globalIndex + 1;
    }
    if (group && item) return Math.max(0, group.items.indexOf(item)) + 1;
    const snapshot = String(segment.label_snapshot ?? segment.labelSnapshot ?? '').trim();
    const snapshotMatch = snapshot.match(/图片\s*(\d{1,3})/);
    return snapshotMatch ? Math.max(1, Number(snapshotMatch[1]) || 1) : 0;
  }

    function imageReferenceDisplay(segment = {}) {
    const imageNumber = imageReferenceNumber(segment);
    if (imageNumber > 0) return `@图片${imageNumber}`;
    const snapshot = String(segment.label_snapshot ?? segment.labelSnapshot ?? '').trim();
    if (snapshot.startsWith('@')) return snapshot;
    const snapshotMatch = snapshot.match(/图片\s*(\d{1,3})/);
    if (snapshotMatch) return `@图片${Math.max(1, Number(snapshotMatch[1]) || 1)}`;
    const sourceNodeId = String(segment.source_node_id ?? segment.sourceNodeId ?? '');
    const sourceNode = DesktopState.state.canvas.nodes[sourceNodeId];
    if (sourceNode?.type === 'image') {
      const allImages = listPromptImageNodes();
      const imageIndex = allImages.findIndex(item => !item.imageGroupId && item.sourceNodeId === sourceNodeId);
      if (imageIndex >= 0) return `@图片${imageIndex + 1}`;
    }
    return '@图片';
  }

    function normalizeImageReferenceSegment(segment = {}, fallback = {}) {
    const source = segment && typeof segment === 'object' ? segment : {};
    const base = fallback && typeof fallback === 'object' ? fallback : {};
    const normalized = {
      type: 'image_reference',
      instance_id: truncatePromptValue(
        source.instance_id ?? source.instanceId ?? base.instance_id ?? base.instanceId ?? createImageReferenceInstanceId(),
        PROMPT_BLOCK_MAX_ID_LENGTH
      ) || createImageReferenceInstanceId(),
      group_id: truncatePromptValue(source.group_id ?? source.groupId ?? base.group_id ?? base.groupId ?? '', PROMPT_BLOCK_MAX_ID_LENGTH),
      item_id: truncatePromptValue(source.item_id ?? source.itemId ?? base.item_id ?? base.itemId ?? '', PROMPT_BLOCK_MAX_ID_LENGTH),
      source_node_id: truncatePromptValue(
        source.source_node_id ?? source.sourceNodeId ?? base.source_node_id ?? base.sourceNodeId ?? '',
        PROMPT_BLOCK_MAX_ID_LENGTH
      ),
      role_snapshot: normalizeImageGroupRole(
        source.role_snapshot ?? source.roleSnapshot ?? source.role ?? base.role_snapshot ?? base.roleSnapshot ?? base.role
      ),
      label_snapshot: truncatePromptValue(
        source.label_snapshot ?? source.labelSnapshot ?? base.label_snapshot ?? base.labelSnapshot ?? '',
        PROMPT_BLOCK_MAX_LABEL_LENGTH
      )
    };
    if (!normalized.label_snapshot) normalized.label_snapshot = imageReferenceDisplay(normalized);
    return normalized;
  }

    function truncatePromptValue(value, maxLength) {
    const text = String(value ?? '');
    return text.length > maxLength ? text.slice(0, maxLength) : text;
  }

    function createTextPromptDocument(value = '') {
    return {
      schema: PROMPT_DOCUMENT_SCHEMA,
      version: PROMPT_DOCUMENT_VERSION,
      segments: [{ type: 'text', text: truncatePromptValue(value, PROMPT_DOCUMENT_MAX_LENGTH) }]
    };
  }

    function normalizePromptBlockSegment(segment = {}, fallback = {}) {
    const source = segment && typeof segment === 'object' ? segment : {};
    const base = fallback && typeof fallback === 'object' ? fallback : {};
    const blockId = source.block_id ?? source.blockId ?? source.id ?? base.block_id ?? base.blockId ?? base.id ?? '';
    const content = truncatePromptValue(
      source.content_snapshot
      ?? source.contentSnapshot
      ?? source.content
      ?? source.compact_content
      ?? source.english_content
      ?? base.content_snapshot
      ?? base.contentSnapshot
      ?? base.content
      ?? base.compact_content
      ?? base.english_content
      ?? '',
      PROMPT_BLOCK_MAX_CONTENT_LENGTH
    );
    const label = truncatePromptValue(
      source.label_snapshot
      ?? source.labelSnapshot
      ?? source.name
      ?? source.label
      ?? base.label_snapshot
      ?? base.labelSnapshot
      ?? base.name
      ?? base.label
      ?? content.slice(0, 24)
      ?? '素材块',
      PROMPT_BLOCK_MAX_LABEL_LENGTH
    ).trim() || '素材块';
    const rawBlockVersion = source.block_version
      ?? source.blockVersion
      ?? source.version
      ?? source.updated_at
      ?? source.updatedAt
      ?? base.block_version
      ?? base.blockVersion
      ?? base.version
      ?? base.updated_at
      ?? base.updatedAt
      ?? 1;
    const moduleType = truncatePromptValue(
      source.module_type ?? source.moduleType ?? base.module_type ?? base.moduleType ?? 'custom',
      PROMPT_BLOCK_MAX_ID_LENGTH
    ) || 'custom';
    const rawColors = source.color_snapshot
      ?? source.colorSnapshot
      ?? source.colors
      ?? base.color_snapshot
      ?? base.colorSnapshot
      ?? base.colors
      ?? [];
    const colorCandidates = Array.isArray(rawColors) ? rawColors : String(rawColors || '').split(',');
    const colorSnapshot = colorCandidates
      .map(value => String(value || '').trim().toUpperCase())
      .filter(value => /^#[0-9A-F]{6}$/.test(value))
      .slice(0, 5);
    if (moduleType === 'color' && !colorSnapshot.length) {
      colorSnapshot.push(...(content.match(/#[0-9A-F]{6}/ig) || []).map(value => value.toUpperCase()).slice(0, 5));
    }
    const sourceRuleSnapshot = (
      source.source_rule_snapshot
      ?? source.sourceRuleSnapshot
      ?? base.source_rule_snapshot
      ?? base.sourceRuleSnapshot
      ?? {}
    );
    const sourceRule = sourceRuleSnapshot && typeof sourceRuleSnapshot === 'object'
      ? sourceRuleSnapshot
      : {};
    const sourceKind = truncatePromptValue(
      source.source_kind
      ?? source.sourceKind
      ?? source.source
      ?? base.source_kind
      ?? base.sourceKind
      ?? base.source
      ?? sourceRule.source_kind
      ?? '',
      PROMPT_BLOCK_MAX_ID_LENGTH
    );
    const fidelityMarker = truncatePromptValue(
      source.fidelity_marker
      ?? source.fidelityMarker
      ?? base.fidelity_marker
      ?? base.fidelityMarker
      ?? sourceRule.fidelity_marker
      ?? '',
      PROMPT_BLOCK_MAX_LABEL_LENGTH
    ).trim();
    const bundleId = truncatePromptValue(
      source.bundle_id
      ?? source.bundleId
      ?? base.bundle_id
      ?? base.bundleId
      ?? sourceRule.bundle_id
      ?? '',
      PROMPT_BLOCK_MAX_ID_LENGTH
    );
    const rawBundleModules = (
      source.bundle_modules
      ?? source.bundleModules
      ?? base.bundle_modules
      ?? base.bundleModules
      ?? sourceRule.selected_modules
      ?? sourceRule.selectedModules
      ?? []
    );
    const bundleModules = [...new Set(
      (Array.isArray(rawBundleModules) ? rawBundleModules : [])
        .map(value => truncatePromptValue(value, PROMPT_BLOCK_MAX_ID_LENGTH).trim())
        .filter(Boolean)
    )].slice(0, 19);
    const rawBundleSize = Number(
      source.bundle_size
      ?? source.bundleSize
      ?? base.bundle_size
      ?? base.bundleSize
      ?? sourceRule.module_count
      ?? sourceRule.moduleCount
      ?? bundleModules.length
      ?? 0
    );
    const bundleSize = Number.isFinite(rawBundleSize)
      ? Math.max(0, Math.min(19, Math.round(rawBundleSize)))
      : bundleModules.length;
    const rawSourceGeometry = (
      source.source_geometry
      ?? source.sourceGeometry
      ?? base.source_geometry
      ?? base.sourceGeometry
      ?? sourceRule.source_geometry
      ?? {}
    );
    const sourceWidth = Number(rawSourceGeometry?.width || 0);
    const sourceHeight = Number(rawSourceGeometry?.height || 0);
    const sourceGeometry = rawSourceGeometry && typeof rawSourceGeometry === 'object'
      ? {
          width: Number.isFinite(sourceWidth) ? Math.max(0, sourceWidth) : 0,
          height: Number.isFinite(sourceHeight) ? Math.max(0, sourceHeight) : 0,
          recommended_ratio: truncatePromptValue(
            rawSourceGeometry.recommended_ratio ?? rawSourceGeometry.recommendedRatio ?? '',
            24
          )
        }
      : {};
    const explicitFidelityLocked = (
      source.fidelity_locked
      ?? source.fidelityLocked
      ?? base.fidelity_locked
      ?? base.fidelityLocked
    );
    const fidelityLocked = explicitFidelityLocked === undefined || explicitFidelityLocked === null
      ? Boolean(fidelityMarker || sourceKind === 'pinterest_split')
      : Boolean(explicitFidelityLocked);
    return {
      type: 'prompt_block',
      instance_id: truncatePromptValue(
        source.instance_id ?? source.instanceId ?? base.instance_id ?? base.instanceId ?? createPromptBlockInstanceId(),
        PROMPT_BLOCK_MAX_ID_LENGTH
      ) || createPromptBlockInstanceId(),
      block_id: truncatePromptValue(blockId === null || blockId === undefined ? '' : blockId, PROMPT_BLOCK_MAX_ID_LENGTH),
      module_type: moduleType,
      label_snapshot: label,
      content_snapshot: content,
      color_snapshot: colorSnapshot,
      block_version: (typeof rawBlockVersion === 'number' || typeof rawBlockVersion === 'string') ? rawBlockVersion : 1,
      source_kind: sourceKind,
      bundle_id: bundleId,
      bundle_size: bundleSize,
      bundle_modules: bundleModules,
      fidelity_locked: fidelityLocked,
      fidelity_marker: fidelityMarker,
      source_geometry: sourceGeometry
    };
  }

    function normalizePromptDocument(promptDocument, fallbackText = '') {
    const sourceSegments = Array.isArray(promptDocument?.segments) ? promptDocument.segments : null;
    const schemaSupported = !promptDocument?.schema || promptDocument.schema === PROMPT_DOCUMENT_SCHEMA;
    const parsedVersion = promptDocument?.version === undefined || promptDocument?.version === null
      ? PROMPT_DOCUMENT_VERSION
      : Number(promptDocument.version);
    const versionSupported = Number.isFinite(parsedVersion) && parsedVersion === PROMPT_DOCUMENT_VERSION;
    if (!sourceSegments || !sourceSegments.length || !schemaSupported || !versionSupported) {
      return createTextPromptDocument(fallbackText);
    }
    const segments = [];
    let recognizedSegments = 0;
    let remainingLength = PROMPT_DOCUMENT_MAX_LENGTH;
    const pushText = value => {
      if (remainingLength <= 0) return;
      const text = truncatePromptValue(
        String(value ?? '').replace(/\r\n?/g, '\n'),
        remainingLength
      );
      remainingLength -= text.length;
      const previous = segments[segments.length - 1];
      if (previous?.type === 'text') previous.text += text;
      else segments.push({ type: 'text', text });
    };
    sourceSegments.slice(0, PROMPT_DOCUMENT_MAX_SEGMENTS).forEach(segment => {
      if (!segment || typeof segment !== 'object') return;
      if (segment.type === 'image_reference') {
        if (remainingLength <= 0) return;
        const reference = normalizeImageReferenceSegment(segment);
        const visibleText = truncatePromptValue(imageReferenceDisplay(reference), remainingLength);
        reference.label_snapshot = reference.label_snapshot || visibleText;
        remainingLength -= visibleText.length;
        segments.push(reference);
        recognizedSegments += 1;
        return;
      }
      if (segment.type === 'prompt_block') {
        if (remainingLength <= 0) return;
        const block = normalizePromptBlockSegment(segment);
        block.content_snapshot = truncatePromptValue(block.content_snapshot, remainingLength);
        remainingLength -= block.content_snapshot.length;
        segments.push(block);
        recognizedSegments += 1;
        return;
      }
      if (segment.type === 'text' || segment.text !== undefined) {
        pushText(segment.text ?? '');
        recognizedSegments += 1;
        return;
      }
      if (segment.value !== undefined || segment.content !== undefined) {
        pushText(segment.value ?? segment.content ?? '');
        recognizedSegments += 1;
      }
    });
    if (!recognizedSegments) return createTextPromptDocument(fallbackText);
    if (!segments.length) segments.push({ type: 'text', text: '' });
    return {
      schema: PROMPT_DOCUMENT_SCHEMA,
      version: PROMPT_DOCUMENT_VERSION,
      segments
    };
  }

    function materializePromptDocument(promptDocument) {
    return (Array.isArray(promptDocument?.segments) ? promptDocument.segments : [])
      .map(segment => {
        if (segment?.type === 'prompt_block') return String(segment.content_snapshot || '');
        if (segment?.type === 'image_reference') return imageReferenceDisplay(segment);
        return String(segment?.text || '');
      })
      .join('');
  }

    function promptDocumentFidelityHeader(promptDocument) {
    const lockedSegments = (Array.isArray(promptDocument?.segments) ? promptDocument.segments : [])
      .filter(segment => (
        segment?.type === 'prompt_block'
        && segment.fidelity_locked
        && String(segment.bundle_id || '').trim()
      ));
    if (!lockedSegments.length) return '';
    const groups = new Map();
    lockedSegments.forEach(segment => {
      const bundleId = String(segment.bundle_id || '').trim();
      if (!groups.has(bundleId)) groups.set(bundleId, []);
      groups.get(bundleId).push(segment);
    });
    // A single generated prompt must never claim that two different source
    // images are "the same reference image" or inherit an arbitrary ratio.
    if (groups.size !== 1) return '';
    const completeBundle = [...groups.values()].find(segments => {
      const expectedModules = [...new Set(
        segments.flatMap(segment => Array.isArray(segment.bundle_modules) ? segment.bundle_modules : [])
          .map(value => String(value || '').trim())
          .filter(Boolean)
      )];
      const expectedSize = Math.max(
        expectedModules.length,
        ...segments.map(segment => Math.max(0, Number(segment.bundle_size || 0)))
      );
      const presentModules = new Set(
        segments.map(segment => String(segment.module_type || '').trim()).filter(Boolean)
      );
      if (expectedSize < 3) return false;
      if (expectedModules.length) return expectedModules.every(moduleType => presentModules.has(moduleType));
      return presentModules.size >= expectedSize;
    });
    if (!completeBundle) return '';
    const marker = completeBundle
      .map(segment => String(segment.fidelity_marker || '').trim())
      .find(Boolean)
      || '【同图忠实复现｜高保真模块】';
    const geometry = completeBundle
      .map(segment => segment.source_geometry)
      .find(value => value && typeof value === 'object')
      || {};
    const width = Math.max(0, Number(geometry.width || 0));
    const height = Math.max(0, Number(geometry.height || 0));
    const recommendedRatio = String(geometry.recommended_ratio || geometry.recommendedRatio || '').trim();
    const geometryConstraint = recommendedRatio
      ? `保持原图${width > 0 && height > 0 ? ` ${width}×${height}` : ''}的画幅、主体占比和边缘裁切关系，生成参数优先使用 ${recommendedRatio}。`
      : '保持原图画幅、主体占比和边缘裁切关系。';
    const ratioLock = recommendedRatio ? `【原图比例：${recommendedRatio}】` : '';
    return [
      marker,
      ratioLock,
      '以下素材块共同描述同一张参考图，必须作为一个完整提示词整体执行。',
      '每个素材块都是可见事实硬约束，不是创作灵感；优先执行具体的数量、年龄范围、几何比例、坐标、裁切、类别、材质和纹理，不得改写成常见近似款。',
      '忠实保持主体数量、身份与年龄感、脸部或物体几何比例、服装或产品结构、材质纹理、姿态、构图、镜头、光线、色彩和背景空间关系。',
      '禁止自动美化、年轻化、瘦身、改脸、替换服装或材质、简化背景、新增对象或改变关键空间关系；近距离人像不得自动补出伸向镜头的自拍前臂、手掌或手机。',
      geometryConstraint
    ].join('');
  }

    function clonePromptDocument(promptDocument, fallbackText = '') {
    return normalizePromptDocument(jsonClone(promptDocument, null), fallbackText);
  }

    function ensureTextNodePromptDocument(node) {
    if (!node || node.type !== 'text') return null;
    const normalized = normalizePromptDocument(node.promptDocument, node.text || '');
    const text = materializePromptDocument(normalized);
    node.promptDocument = normalized;
    node.text = text;
    return normalized;
  }

    function promptDocumentFingerprint(promptDocument, fallbackText = '') {
    return JSON.stringify(normalizePromptDocument(promptDocument, fallbackText));
  }

    function getPromptDocumentVersion(nodeStateOrId) {
    const nodeId = typeof nodeStateOrId === 'string' ? nodeStateOrId : nodeStateOrId?.id;
    return nodeId ? (promptDocumentVersions.get(nodeId) || 0) : 0;
  }

    function bumpPromptDocumentVersion(nodeState) {
    if (!nodeState?.id) return 0;
    const version = getPromptDocumentVersion(nodeState) + 1;
    promptDocumentVersions.set(nodeState.id, version);
    return version;
  }

    function getPromptDocumentHistory(nodeId, create = true) {
    if (!nodeId) return null;
    let history = promptDocumentHistories.get(nodeId);
    if (!history && create) {
      history = { undo: [], redo: [], redoEligible: false };
      promptDocumentHistories.set(nodeId, history);
    }
    return history || null;
  }

    function beginPromptDocumentHistory(nodeState) {
    if (!nodeState || nodeState.type !== 'text') return null;
    const beforeDocument = clonePromptDocument(ensureTextNodePromptDocument(nodeState), nodeState.text || '');
    return {
      beforeDocument,
      beforeFingerprint: promptDocumentFingerprint(beforeDocument)
    };
  }

    function commitPromptDocumentHistory(nodeState, entry) {
    if (!entry || !nodeState?.id) return null;
    const afterDocument = clonePromptDocument(ensureTextNodePromptDocument(nodeState), nodeState.text || '');
    const afterFingerprint = promptDocumentFingerprint(afterDocument);
    if (entry.beforeFingerprint === afterFingerprint) return null;
    const history = getPromptDocumentHistory(nodeState.id);
    const committed = { ...entry, afterDocument, afterFingerprint };
    const previous = history.undo[history.undo.length - 1];
    if (!previous
      || previous.beforeFingerprint !== committed.beforeFingerprint
      || previous.afterFingerprint !== committed.afterFingerprint) {
      history.undo.push(committed);
      if (history.undo.length > PROMPT_DOCUMENT_HISTORY_LIMIT) history.undo.shift();
    }
    history.redo = [];
    history.redoEligible = false;
    return committed;
  }

    function clearPromptDocumentHistory(nodeId) {
    promptDocumentHistories.delete(nodeId);
    promptDocumentVersions.delete(nodeId);
  }

    function promptDocumentHasEditorContent(promptDocument) {
    return normalizePromptDocument(promptDocument).segments.some(segment => (
      segment.type === 'prompt_block'
      || segment.type === 'image_reference'
      || String(segment.text || '').trim().length > 0
    ));
  }

    function materializeTextNode(node) {
    const promptDocument = ensureTextNodePromptDocument(node);
    return promptDocument ? materializePromptDocument(promptDocument) : '';
  }

    function ensureTextNodePromptDocuments() {
    let changed = false;
    Object.values(DesktopState.state.canvas.nodes || {}).forEach(node => {
      if (node?.type !== 'text') return;
      const previousDocument = JSON.stringify(node.promptDocument || null);
      const previousText = String(node.text || '');
      ensureTextNodePromptDocument(node);
      if (previousDocument !== JSON.stringify(node.promptDocument) || previousText !== node.text) changed = true;
    });
    return changed;
  }

    function normalizePromptGenerationMeta(value) {
    const source = value && typeof value === 'object' ? value : {};
    const allowed = [
      'skill_id', 'source_repository', 'source_commit', 'source_path',
      'compiler_version', 'schema_version', 'mode', 'reference_image_used',
      'provider', 'model', 'reasoning_effort', 'repair_applied', 'verified_files',
      'bilingual_output', 'minimum_shot_count'
    ];
    return Object.fromEntries(allowed
      .filter(key => source[key] !== undefined && source[key] !== null && source[key] !== '')
      .map(key => [key, source[key]]));
  }

    function promptTextFingerprint(value) {
    let hash = 2166136261;
    for (const char of String(value || '')) {
      hash ^= char.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  }

    function setTextNodePromptMeta(nodeState, value, promptText = '') {
    if (!nodeState) return;
    const meta = normalizePromptGenerationMeta(value);
    if (Object.keys(meta).length) {
      nodeState.promptMeta = meta;
      nodeState.promptMetaFingerprint = promptTextFingerprint(promptText);
    } else {
      delete nodeState.promptMeta;
      delete nodeState.promptMetaFingerprint;
    }
  }

    function composePromptWithTextStyles(prompt, styleIds = []) {
    let result = String(prompt || '').trim();
    const seen = new Set();
    (styleIds || []).forEach(styleId => {
      const preset = getTextStylePreset(styleId);
      if (!preset || seen.has(preset.id)) return;
      seen.add(preset.id);
      const template = String(preset.promptTemplate || '').trim();
      if (!template) return;
      if (preset.id === 'sketchnote') {
        result = result ? `${template}${result}` : template;
      } else {
        result = result ? `${result}\n\n${template}` : template;
      }
    });
    return result;
  }

    function getConnectedTextNodes(inputNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === inputNodeId)
      .map(edge => DesktopState.state.canvas.nodes[edge.from])
      .filter(node => node?.type === 'text');
  }

    function splitBatchPromptItems(prompt) {
    return String(prompt || '')
      .split(/\n\s*\n|\r?\n/)
      .map(item => item.trim())
      .filter(Boolean);
  }

    function getBatchPromptItems(inputNodeId) {
    const textNodes = getConnectedTextNodes(inputNodeId);
    const imageRoleBlock = imageGroupRolePromptBlock(inputNodeId);
    const nodePrompts = textNodes
      .map(node => {
        const promptDocument = ensureTextNodePromptDocument(node);
        return {
          text: promptDocument ? materializePromptDocument(promptDocument).trim() : '',
          fidelityHeader: promptDocumentFidelityHeader(promptDocument),
          styleId: node.stylePresetId || ''
        };
      })
      .filter(item => item.text);
    if (nodePrompts.length > 1) {
      return nodePrompts.map(item => composePromptWithTextStyles(
        [item.fidelityHeader, imageRoleBlock, item.text].filter(Boolean).join('\n\n'),
        [item.styleId].filter(Boolean)
      ));
    }
    if (nodePrompts.length === 1) {
      const parts = splitBatchPromptItems(nodePrompts[0].text);
      return parts.map(part => composePromptWithTextStyles(
        [nodePrompts[0].fidelityHeader, imageRoleBlock, part].filter(Boolean).join('\n\n'),
        [nodePrompts[0].styleId].filter(Boolean)
      ));
    }
    return [];
  }

    function mergePromptWithConnectedText(prompt, inputNodeId) {
    const textNodes = getConnectedTextNodes(inputNodeId);
    const styleIds = textNodes.map(node => node.stylePresetId || '').filter(Boolean);
    const promptDocuments = textNodes
      .map(node => ensureTextNodePromptDocument(node))
      .filter(Boolean);
    const combinedFidelityHeader = promptDocumentFidelityHeader({
      segments: promptDocuments.flatMap(document => Array.isArray(document.segments) ? document.segments : [])
    });
    const imageRoleBlock = imageGroupRolePromptBlock(inputNodeId);
    const basePrompt = [
      combinedFidelityHeader,
      imageRoleBlock,
      ...textNodes.map(node => materializeTextNode(node).trim()).filter(Boolean),
      String(prompt || '').trim()
    ]
      .filter(Boolean)
      .join('\n\n');
    return composePromptWithTextStyles(basePrompt, styleIds);
  }

    function getVisibleInputPrompt(inputNodeId) {
    return mergePromptWithConnectedText('', inputNodeId);
  }

    return Object.freeze({
      createPromptBlockInstanceId,
      createImageReferenceInstanceId,
      imageReferenceRole,
      imageReferenceTargetNodeId,
      imageReferenceNumber,
      imageReferenceDisplay,
      normalizeImageReferenceSegment,
      truncatePromptValue,
      createTextPromptDocument,
      normalizePromptBlockSegment,
      normalizePromptDocument,
      materializePromptDocument,
      promptDocumentFidelityHeader,
      clonePromptDocument,
      ensureTextNodePromptDocument,
      promptDocumentFingerprint,
      getPromptDocumentVersion,
      bumpPromptDocumentVersion,
      getPromptDocumentHistory,
      beginPromptDocumentHistory,
      commitPromptDocumentHistory,
      clearPromptDocumentHistory,
      promptDocumentHasEditorContent,
      materializeTextNode,
      ensureTextNodePromptDocuments,
      normalizePromptGenerationMeta,
      promptTextFingerprint,
      setTextNodePromptMeta,
      composePromptWithTextStyles,
      getConnectedTextNodes,
      splitBatchPromptItems,
      getBatchPromptItems,
      mergePromptWithConnectedText,
      getVisibleInputPrompt,
    });
  }

  window.DesktopCanvasPromptDocument = Object.freeze({ create });
})();
