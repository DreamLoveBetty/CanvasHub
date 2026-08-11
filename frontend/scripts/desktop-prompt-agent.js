(function () {
  const MODE_KEY = 'desktop_prompt_workspace_mode_v1';
  const ACTIVE_RUN_KEY = 'desktop_prompt_agent_active_run_v1';
  const SNAPSHOT_DB = 'desktop_prompt_agent_v1';
  const SNAPSHOT_STORE = 'canvas_snapshots';
  const MAX_IMAGE_REFERENCES = 4;
  const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'canceled', 'rolled_back']);
  const RESULT_NODE_TYPES = new Set(['input', 'output', 'file_output', 'comfy', 'upscale', 'video_inference']);
  const GENERATION_NODE_TYPES = new Set(['input', 'comfy', 'upscale', 'video_inference']);
  const STATUS_LABELS = {
    idle: '待命',
    awaiting_approval: '等待确认',
    running: '执行中',
    waiting_for_action: '正在操作画布',
    paused: '已暂停',
    rolling_back: '正在回滚',
    succeeded: '已完成',
    failed: '执行失败',
    canceled: '已取消',
    rolled_back: '已回滚'
  };
  const EVENT_LABELS = {
    plan_created: '执行计划已创建',
    plan_revised: '生成决策已更新',
    run_approved: '计划已批准',
    run_started: 'Agent 开始执行',
    run_paused: 'Agent 已暂停',
    run_resumed: 'Agent 已继续',
    run_canceled: 'Agent 已取消',
    run_completed: 'Agent 已完成',
    run_failed: 'Agent 执行失败',
    step_started: '步骤开始',
    step_completed: '步骤完成',
    action_required: '请求画布动作',
    action_result: '画布动作回执',
    generation_progress: '生成任务进度',
    rollback_requested: '请求回滚画布',
    rollback_completed: '画布已回滚',
    rollback_failed: '画布回滚失败'
  };
  const els = {};
  let goalEditor = null;
  const state = {
    mode: 'assistant',
    runId: '',
    run: null,
    events: [],
    eventSeq: 0,
    creating: false,
    controlling: false,
    revising: false,
    polling: false,
    pollTimer: 0,
    restoreStarted: false,
    actionInFlight: '',
    approvalRunId: '',
    approvalParamsExpanded: false,
    approvalManual: false,
    mentionQuery: '',
    imageReferences: [],
    actionReceipts: new Map(),
    snapshots: new Map()
  };

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function readStorage(key, fallback = '') {
    try {
      return window.localStorage?.getItem(key) || fallback;
    } catch (error) {
      return fallback;
    }
  }

  function writeStorage(key, value) {
    try {
      if (value) window.localStorage?.setItem(key, String(value));
      else window.localStorage?.removeItem(key);
    } catch (error) {}
  }

  function collectElements() {
    [
      'deskPromptDrawer',
      'deskPromptDrawerToggle',
      'deskPromptWorkbenchTitle',
      'deskPromptAssistantMode',
      'deskPromptAgentMode',
      'deskAgentHead',
      'deskAgentStatus',
      'deskAgentPause',
      'deskAgentPauseIcon',
      'deskAgentRollback',
      'deskAgentCancel',
      'deskAgentWorkbench',
      'deskAgentContextMeta',
      'deskAgentContext',
      'deskAgentGoalWrap',
      'deskAgentGoal',
      'deskAgentImageMenu',
      'deskAgentScope',
      'deskAgentAutoGenerate',
      'deskAgentCreatePlan',
      'deskAgentPlanMeta',
      'deskAgentSteps',
      'deskAgentApproval',
      'deskAgentApprovalTitle',
      'deskAgentApprovalHint',
      'deskAgentDecision',
      'deskAgentDecisionText',
      'deskAgentDecisionBasis',
      'deskAgentDecisionAttention',
      'deskAgentParamsToggle',
      'deskAgentRevisionForm',
      'deskAgentRevisionInput',
      'deskAgentRevisionSubmit',
      'deskAgentRevisionSubmitLabel',
      'deskAgentParams',
      'deskAgentProviderGpt',
      'deskAgentProviderGoogle',
      'deskAgentRatio',
      'deskAgentResolution',
      'deskAgentQuality',
      'deskAgentImageCount',
      'deskAgentArchiveEnabled',
      'deskAgentTelegramEnabled',
      'deskAgentApprove',
      'deskAgentEventMeta',
      'deskAgentEvents',
      'deskAgentArtifact',
      'deskAgentArtifactTitle',
      'deskAgentArtifactText'
    ].forEach(id => {
      els[id] = $(id);
    });
  }

  function getImageNodes() {
    return window.DesktopCanvas?.listPromptImageNodes?.() || [];
  }

  function goalText() {
    return goalEditor?.getText?.() || String(els.deskAgentGoal?.textContent || '').trim();
  }

  function imageReferenceKey(item = {}) {
    return String(item.sourceNodeId || item.nodeId || item.source_node_id || item.id || '').trim();
  }

  function editorImageReferences() {
    return goalEditor?.getAttachments?.() || [];
  }

  function syncImageReferencesFromEditor() {
    const nodes = getImageNodes();
    const chips = editorImageReferences();
    state.imageReferences = chips.map(chip => {
      const existing = state.imageReferences.find(item => item.id === chip.id);
      const sourceNodeId = chip.sourceNodeId || existing?.sourceNodeId || '';
      const node = nodes.find(item => item.nodeId === sourceNodeId);
      const source = chip.imageSrc || node?.imageData || node?.imageUrl || node?.url || '';
      const isDataUrl = source.startsWith('data:image/');
      return {
        ...existing,
        id: chip.id,
        label: existing?.label || node?.label || chip.id,
        sourceNodeId: sourceNodeId || node?.nodeId || '',
        imageData: node?.imageData || (isDataUrl ? source : ''),
        imageUrl: node?.imageUrl || (isDataUrl ? '' : source),
        url: node?.url || source,
        mimeType: chip.mimeType || existing?.mimeType || node?.mimeType || 'image/png'
      };
    }).filter(item => item.id && item.sourceNodeId);
  }

  function nextImageReferenceId() {
    const used = new Set(state.imageReferences.map(item => String(item.id || '')));
    for (let index = 1; index <= MAX_IMAGE_REFERENCES; index += 1) {
      const id = `image${index}`;
      if (!used.has(id)) return id;
    }
    return `image${state.imageReferences.length + 1}`;
  }

  function closeImageMentionMenu(options = {}) {
    state.mentionQuery = '';
    if (!options.fromEditor) goalEditor?.clearMention?.();
    if (els.deskAgentImageMenu) {
      els.deskAgentImageMenu.hidden = true;
      els.deskAgentImageMenu.innerHTML = '';
    }
  }

  function renderImageMentionMenu() {
    if (!els.deskAgentImageMenu || !goalEditor?.hasMention?.()) return;
    const query = String(state.mentionQuery || '').trim().toLowerCase();
    const nodes = getImageNodes()
      .filter(node => {
        if (!query) return true;
        return `${node.label || ''} ${node.name || ''} ${node.nodeId || ''}`.toLowerCase().includes(query);
      })
      .slice(0, 8);
    const columns = Math.max(1, Math.min(nodes.length || 1, 3));
    els.deskAgentImageMenu.style.setProperty('--desk-prompt-image-menu-cols', String(columns));
    els.deskAgentImageMenu.dataset.imageCount = String(nodes.length);
    els.deskAgentImageMenu.innerHTML = nodes.length
      ? nodes.map(node => `
          <button type="button" data-agent-pick-image-node="${escapeHtml(node.nodeId)}" aria-label="引用 ${escapeHtml(node.label || '图片节点')}" title="引用 ${escapeHtml(node.label || '图片节点')}">
            <img src="${escapeHtml(node.imageData || node.imageUrl || node.url)}" alt="">
          </button>
        `).join('')
      : '<div class="desk-prompt-image-menu__empty">没有图片节点</div>';
    els.deskAgentImageMenu.hidden = false;
  }

  function addImageReference(raw = {}) {
    const sourceNodeId = String(raw.sourceNodeId || raw.nodeId || raw.source_node_id || '').trim();
    const source = raw.imageData || raw.dataUrl || raw.imageUrl || raw.url || '';
    if (!sourceNodeId || !source) return null;
    const existing = state.imageReferences.find(item => imageReferenceKey(item) === sourceNodeId);
    if (existing) {
      goalEditor?.removeAttachment?.(existing.id, { silent: true });
      goalEditor?.insertAttachment?.(existing, { replaceMention: true });
      closeImageMentionMenu();
      return existing;
    }
    if (state.imageReferences.length >= MAX_IMAGE_REFERENCES) {
      closeImageMentionMenu();
      window.DesktopResults?.showTransientMessage?.(`Agent 最多引用 ${MAX_IMAGE_REFERENCES} 张图片。`, 'warning');
      return null;
    }
    const item = {
      id: nextImageReferenceId(),
      label: String(raw.label || raw.name || raw.title || '图片节点').trim(),
      sourceNodeId,
      imageData: raw.imageData || raw.dataUrl || '',
      imageUrl: raw.imageUrl || '',
      url: raw.url || raw.imageUrl || raw.imageData || raw.dataUrl || '',
      mimeType: raw.mimeType || raw.type || 'image/png'
    };
    state.imageReferences.push(item);
    goalEditor?.insertAttachment?.(item, { replaceMention: true });
    closeImageMentionMenu();
    refreshContextPreview();
    return item;
  }

  function removeImageReference(id) {
    state.imageReferences = state.imageReferences.filter(item => item.id !== String(id || ''));
    goalEditor?.removeAttachment?.(id, { silent: true });
    refreshContextPreview();
  }

  function attachImageNode(nodeId) {
    const node = getImageNodes().find(item => item.nodeId === String(nodeId || ''));
    if (!node) return;
    addImageReference(node);
  }

  function reconcileImageReferences() {
    const nodeIds = new Set(getImageNodes().map(item => String(item.nodeId || '')));
    const next = state.imageReferences.filter(item => nodeIds.has(String(item.sourceNodeId || '')));
    if (next.length === state.imageReferences.length) return;
    state.imageReferences = next;
    goalEditor?.setAttachments?.(state.imageReferences);
  }

  function restoreGoalFromRun(payload = {}) {
    const references = Array.isArray(payload.context?.referenced_images)
      ? payload.context.referenced_images
      : [];
    const nodes = getImageNodes();
    state.imageReferences = references.slice(0, MAX_IMAGE_REFERENCES).map((reference, index) => {
      const sourceNodeId = String(reference?.source_node_id || reference?.sourceNodeId || '').trim();
      const node = nodes.find(item => item.nodeId === sourceNodeId);
      if (!node) return null;
      return {
        ...node,
        id: String(reference.id || `image${index + 1}`),
        label: String(reference.label || node.label || `图片 ${index + 1}`),
        sourceNodeId
      };
    }).filter(Boolean);
    if (goalEditor?.setDocument) {
      goalEditor.setDocument(payload.goal || '', state.imageReferences);
    } else {
      goalEditor?.setText?.(payload.goal || '');
    }
  }

  function initGoalEditor() {
    if (!els.deskAgentGoal || !window.DesktopPromptEditor?.create) return;
    goalEditor = window.DesktopPromptEditor.create({
      root: els.deskAgentGoal,
      menu: els.deskAgentImageMenu,
      onMention({ query }) {
        state.mentionQuery = String(query || '');
        renderImageMentionMenu();
      },
      onMentionClose() {
        closeImageMentionMenu({ fromEditor: true });
      },
      onChange() {
        syncImageReferencesFromEditor();
        refreshContextPreview();
      },
      onRemoveAttachment(id) {
        removeImageReference(id);
      },
      onSubmit() {
        createPlan();
      }
    });
  }

  function setMode(mode, options = {}) {
    const next = mode === 'agent' ? 'agent' : 'assistant';
    state.mode = next;
    writeStorage(MODE_KEY, next);
    const isAgent = next === 'agent';
    els.deskPromptDrawer?.classList.toggle('is-agent', isAgent);
    els.deskPromptDrawer?.setAttribute('aria-label', isAgent ? 'Agent 工作台' : '提示词助手');
    if (els.deskPromptWorkbenchTitle) els.deskPromptWorkbenchTitle.textContent = isAgent ? 'Agent 工作台' : '提示词助手';
    if (els.deskPromptDrawerToggle) {
      els.deskPromptDrawerToggle.title = isAgent ? 'Agent 工作台' : '提示词助手';
      els.deskPromptDrawerToggle.setAttribute('aria-label', isAgent ? '展开或收起 Agent 工作台' : '展开或收起提示词助手');
    }
    els.deskPromptAssistantMode?.classList.toggle('is-active', !isAgent);
    els.deskPromptAgentMode?.classList.toggle('is-active', isAgent);
    els.deskPromptAssistantMode?.setAttribute('aria-selected', String(!isAgent));
    els.deskPromptAgentMode?.setAttribute('aria-selected', String(isAgent));
    document.querySelectorAll('[data-prompt-assistant-view]').forEach(node => {
      node.hidden = isAgent;
    });
    document.querySelectorAll('[data-prompt-agent-view]').forEach(node => {
      node.hidden = !isAgent;
    });
    if (isAgent) {
      refreshContextPreview();
      render();
      if (options.open !== false) window.DesktopPromptDrawer?.setOpen?.(true);
    }
  }

  function canvasSnapshotState() {
    return window.DesktopState?.state?.canvas || { nodes: {}, edges: [] };
  }

  function selectedNodeIds(canvas = canvasSnapshotState()) {
    const ids = Array.isArray(canvas.selectedNodeIds) ? canvas.selectedNodeIds.filter(Boolean) : [];
    if (!ids.length && canvas.selectedNodeId) ids.push(canvas.selectedNodeId);
    return [...new Set(ids)];
  }

  function refreshContextPreview() {
    reconcileImageReferences();
    const canvas = canvasSnapshotState();
    const nodes = Object.values(canvas.nodes || {}).filter(Boolean);
    const images = nodes.filter(node => node.type === 'image' && (node.imageData || node.imageUrl));
    const selected = selectedNodeIds(canvas);
    const textNodes = nodes.filter(node => node.type === 'text');
    const hasVideoContext = selected.some(nodeId => ['video_inference', 'video'].includes(canvas.nodes?.[nodeId]?.type))
      || (canvas.edges || []).some(edge => selected.includes(edge.from) && canvas.nodes?.[edge.to]?.type === 'video_inference');
    if (els.deskAgentContextMeta) {
      els.deskAgentContextMeta.textContent = `${nodes.length} 节点 · ${selected.length} 已选`;
    }
    if (els.deskAgentContext) {
      els.deskAgentContext.innerHTML = [
        `<span>${selected.length ? `已选 ${selected.length}` : '未选择节点'}</span>`,
        ...(hasVideoContext ? ['<span>MiniMax H3 · I2VA</span>'] : []),
        ...(state.imageReferences.length ? [`<span>引用 ${state.imageReferences.length}</span>`] : []),
        `<span>图片 ${images.length}</span>`,
        `<span>文本 ${textNodes.length}</span>`
      ].join('');
    }
  }

  function cleanContextString(value) {
    const text = String(value || '');
    if (/^data:/i.test(text)) return '[client-held data]';
    if (/^blob:/i.test(text)) return '[client-held blob]';
    if (!/(?:miniappAuth|authToken)=/i.test(text)) return text;
    return text
      .replace(/([?&])(?:miniappAuth|authToken)=[^&#]*/gi, '$1')
      .replace(/[?&]$/, '')
      .replace('?&', '?');
  }

  function sanitizeWorkflowForServer(snapshot) {
    return JSON.parse(JSON.stringify(snapshot, (key, value) => {
      if (typeof value === 'string') return cleanContextString(value);
      return value;
    }));
  }

  function resolveResultNodeId(snapshot) {
    const canvas = snapshot?.state?.canvas || {};
    const nodes = canvas.nodes || {};
    const edges = Array.isArray(canvas.edges) ? canvas.edges : [];
    const selectedIds = selectedNodeIds(canvas);
    const selectedResultId = selectedIds.find(nodeId => RESULT_NODE_TYPES.has(nodes[nodeId]?.type));
    if (selectedResultId) return selectedResultId;

    const selectedVideoSourceId = selectedIds
      .map(nodeId => edges.find(edge => edge.to === nodeId && nodes[nodeId]?.type === 'video' && nodes[edge.from]?.type === 'video_inference')?.from)
      .find(Boolean);
    if (selectedVideoSourceId) return selectedVideoSourceId;

    const selectedTargetId = selectedIds
      .map(nodeId => edges.find(edge => edge.from === nodeId && GENERATION_NODE_TYPES.has(nodes[edge.to]?.type))?.to)
      .find(Boolean);
    if (selectedTargetId) return selectedTargetId;

    const connectedResultIds = [...new Set(edges
      .filter(edge => ['text', 'image'].includes(nodes[edge.from]?.type) && GENERATION_NODE_TYPES.has(nodes[edge.to]?.type))
      .map(edge => edge.to))];
    const connectedDynamicId = connectedResultIds.find(nodeId => nodeId !== 'input');
    if (connectedDynamicId) return connectedDynamicId;
    if (connectedResultIds.length) return connectedResultIds[0];

    const generationNodes = Object.values(nodes).filter(node => GENERATION_NODE_TYPES.has(node?.type));
    const dynamicNode = generationNodes.find(node => node.id !== 'input');
    if (dynamicNode?.id) return dynamicNode.id;
    if (nodes.input?.type === 'input') return 'input';
    return Object.values(nodes).find(node => RESULT_NODE_TYPES.has(node?.type))?.id || 'input';
  }

  function captureAgentRequest(goal) {
    syncImageReferencesFromEditor();
    const snapshot = window.DesktopCanvas?.exportWorkflowSnapshot?.();
    if (!snapshot?.state?.canvas) throw new Error('无法读取当前画布');
    const resultNodeId = resolveResultNodeId(snapshot);
    const resultNode = snapshot.state.canvas.nodes?.[resultNodeId] || null;
    const isVideoTask = resultNode?.type === 'video_inference';
    let config = null;
    try {
      config = isVideoTask
        ? (window.DesktopCanvas?.readVideoInferenceNodeConfig?.(resultNodeId) || null)
        : (window.DesktopCanvas?.readConfigForResult?.(resultNodeId) || null);
    } catch (error) {}
    if (isVideoTask && !config) {
      config = {
        provider: 'minimax_h3',
        prompt: '',
        params: {
          mode: resultNode.mode || 'image_to_video',
          durationSeconds: Number(resultNode.durationSeconds || 15),
          aspectRatio: resultNode.aspectRatio || '3:4',
          pixelBudgetMp: Number(resultNode.pixelBudgetMp || 0.8),
          width: Number(resultNode.pixelWidth || 768),
          height: Number(resultNode.pixelHeight || 1024),
          accelerationMode: resultNode.accelerationMode || 'first_block_cache',
          firstBlockCacheThreshold: Number(resultNode.firstBlockCacheThreshold || 0.08),
          steps: Number(resultNode.steps || 20),
          crf: Number(resultNode.crf || 23)
        }
      };
    }
    const target = window.DesktopCanvas?.getPromptTargetInfo?.() || {};
    const params = { ...(config?.params || snapshot.state.params || {}) };
    const output = snapshot.state.output || {};
    const currentPrompt = String(
      (target.type === 'text' ? window.DesktopCanvas?.getPromptTargetText?.({ target }) : '')
      || config?.prompt
      || snapshot.state.prompt
      || ''
    ).trim();
    const canvasNodeIds = new Set(Object.keys(snapshot.state.canvas.nodes || {}));
    const referencedImages = state.imageReferences
      .filter(item => canvasNodeIds.has(String(item.sourceNodeId || '')))
      .slice(0, MAX_IMAGE_REFERENCES)
      .map(item => ({
        id: String(item.id || ''),
        label: String(item.label || item.id || '图片节点'),
        source_node_id: String(item.sourceNodeId || ''),
        mime_type: String(item.mimeType || 'image/png')
      }));
    const context = {
      workflow: sanitizeWorkflowForServer(snapshot),
      target: {
        node_id: target.nodeId || '',
        type: target.type || '',
        label: target.label || ''
      },
      current_prompt: currentPrompt,
      task_domain: isVideoTask ? 'video' : 'image',
      model_family: isVideoTask ? 'minimax_h3' : '',
      generation_node_id: resultNodeId,
      video_node_id: isVideoTask ? resultNodeId : '',
      provider: config?.provider || snapshot.state.provider || 'gpt',
      params,
      output: {
        archive_enabled: params.archiveEnabled ?? params.archive_enabled ?? (output.archiveEnabled !== false),
        telegram_enabled: params.telegramEnabled ?? params.telegram_enabled ?? (output.telegramEnabled !== false)
      },
      result_node_id: resultNodeId,
      selected_node_ids: selectedNodeIds(snapshot.state.canvas),
      referenced_image_node_ids: referencedImages.map(item => item.source_node_id),
      referenced_images: referencedImages
    };
    return {
      snapshot,
      payload: {
        goal,
        context,
        options: {
          scope: els.deskAgentScope?.value === 'canvas' ? 'canvas' : 'selection',
          auto_generate: els.deskAgentAutoGenerate?.checked !== false,
          image_count: Number(params.imageCount ?? params.image_count ?? 1) || 1
        },
        client: {
          surface: 'desktop',
          schema_version: 2,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || ''
        }
      }
    };
  }

  function openSnapshotDatabase() {
    if (!window.indexedDB) return Promise.reject(new Error('IndexedDB unavailable'));
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open(SNAPSHOT_DB, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(SNAPSHOT_STORE)) db.createObjectStore(SNAPSHOT_STORE, { keyPath: 'run_id' });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('IndexedDB open failed'));
    });
  }

  async function storeCanvasSnapshot(runId, snapshot) {
    state.snapshots.set(runId, snapshot);
    try {
      const db = await openSnapshotDatabase();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction(SNAPSHOT_STORE, 'readwrite');
        transaction.objectStore(SNAPSHOT_STORE).put({ run_id: runId, saved_at: Date.now(), snapshot });
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error || new Error('Snapshot write failed'));
      });
      db.close();
    } catch (error) {
      console.warn('[PromptAgent] canvas snapshot persistence failed:', error);
    }
  }

  async function loadCanvasSnapshot(runId) {
    if (state.snapshots.has(runId)) return state.snapshots.get(runId);
    const db = await openSnapshotDatabase();
    const record = await new Promise((resolve, reject) => {
      const transaction = db.transaction(SNAPSHOT_STORE, 'readonly');
      const request = transaction.objectStore(SNAPSHOT_STORE).get(runId);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error || new Error('Snapshot read failed'));
    });
    db.close();
    if (record?.snapshot) state.snapshots.set(runId, record.snapshot);
    return record?.snapshot || null;
  }

  function mergeEvents(events) {
    const bySeq = new Map(state.events.map(event => [Number(event.seq || 0), event]));
    (Array.isArray(events) ? events : []).forEach(event => {
      const seq = Number(event?.seq || 0);
      if (!seq) return;
      bySeq.set(seq, event);
      state.eventSeq = Math.max(state.eventSeq, seq);
    });
    state.events = [...bySeq.values()].sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0)).slice(-300);
  }

  function applyRunPayload(payload) {
    if (!payload?.run_id) return;
    mergeEvents(payload.events);
    state.runId = payload.run_id;
    state.run = { ...(state.run || {}), ...payload, events: state.events };
    writeStorage(ACTIVE_RUN_KEY, state.runId);
    const options = payload.request?.options;
    if (options && typeof options === 'object') {
      if (els.deskAgentScope) {
        els.deskAgentScope.value = options.scope === 'canvas' ? 'canvas' : 'selection';
      }
      if (els.deskAgentAutoGenerate) {
        els.deskAgentAutoGenerate.checked = options.auto_generate !== false;
      }
    }
    if (els.deskAgentGoal && document.activeElement !== els.deskAgentGoal && !goalText()) {
      restoreGoalFromRun(payload);
    }
    render();
  }

  function isRunActive(run = state.run) {
    return !!run?.run_id && !TERMINAL_STATUSES.has(String(run.status || ''));
  }

  function schedulePoll(delay = 800) {
    window.clearTimeout(state.pollTimer);
    if (!state.runId) return;
    state.pollTimer = window.setTimeout(pollRun, Math.max(120, delay));
  }

  async function pollRun() {
    if (state.polling || !state.runId) return;
    state.polling = true;
    try {
      const run = await window.DesktopApi.getAgentRun(state.runId, { eventsSince: state.eventSeq, eventLimit: 300 });
      applyRunPayload(run);
      await processWaitingAction();
    } catch (error) {
      console.warn('[PromptAgent] poll failed:', error);
    } finally {
      state.polling = false;
      const status = String(state.run?.status || '');
      if (!TERMINAL_STATUSES.has(status)) {
        schedulePoll(status === 'waiting_for_action' ? 300 : 850);
      }
    }
  }

  function actionEventFor(actionId) {
    return state.events.slice().reverse().find(event => (
      event.event_type === 'action_required'
      && event.payload?.action?.action_id === actionId
    ));
  }

  async function imagePayloadForNode(node, index) {
    let dataUrl = String(node?.imageData || node?.base64 || '');
    const source = String(node?.imageUrl || node?.url || '');
    if (!dataUrl && source) dataUrl = await window.DesktopApi.imageUrlToDataUri(source);
    if (!dataUrl) throw new Error(`无法读取图片节点：${node?.label || node?.nodeId || index + 1}`);
    return {
      id: `image${index + 1}`,
      label: node.label || node.title || `图片 ${index + 1}`,
      dataUrl,
      imageData: dataUrl,
      sourceNodeId: node.nodeId || node.sourceNodeId || '',
      mimeType: node.mimeType || 'image/png',
      role: index === 0 ? 'primary' : 'fusion_reserved'
    };
  }

  async function executeAnalyzeImages(action) {
    const wanted = new Set((action.image_node_ids || []).map(String));
    const nodes = (window.DesktopCanvas?.listPromptImageNodes?.() || [])
      .filter(node => !wanted.size || wanted.has(String(node.nodeId || node.sourceNodeId || '')))
      .slice(0, 4);
    if (!nodes.length) throw new Error('画布中没有可分析的图片节点');
    const images = [];
    for (let index = 0; index < nodes.length; index += 1) {
      images.push(await imagePayloadForNode(nodes[index], index));
    }
    const result = await window.DesktopApi.analyzePromptImage({
      message: action.message || action.goal || '分析画布参考图',
      images,
      target: {},
      style: {},
      keep_text: false
    });
    return {
      analysis: result?.analysis && typeof result.analysis === 'object' ? result.analysis : {},
      candidates: (Array.isArray(result?.candidates) ? result.candidates : [result?.candidate])
        .filter(candidate => candidate?.text)
        .slice(0, 4)
        .map(candidate => ({
          id: candidate.id || '',
          label: candidate.label || '',
          kind: candidate.kind || '',
          text: String(candidate.text || '')
        }))
    };
  }

  async function executeCompileH3Prompt(action) {
    const firstFrameNodeId = String(action.first_frame_node_id || '');
    const firstFrameNode = (window.DesktopCanvas?.listPromptImageNodes?.() || [])
      .find(node => String(node.nodeId || node.sourceNodeId || '') === firstFrameNodeId);
    if (!firstFrameNode) throw new Error('H3 I2VA 需要连接一张可读取的首帧图片');
    const firstFrame = await imagePayloadForNode(firstFrameNode, 0);
    const analysis = action.analysis && typeof action.analysis === 'object' ? action.analysis : {};
    const analysisText = Object.keys(analysis).length
      ? `首帧分析：\n${JSON.stringify(analysis, null, 2)}`
      : '';
    const result = await window.DesktopApi?.compileVideoPrompt?.({
      prompt: String(action.current_prompt || ''),
      instruction: [String(action.goal || ''), analysisText].filter(Boolean).join('\n\n'),
      mode: action.mode || 'image_to_video',
      duration_seconds: Number(action.duration_seconds || 15),
      aspect_ratio: action.aspect_ratio || '3:4',
      first_frame: {
        data_url: firstFrame.dataUrl,
        source_node_id: firstFrame.sourceNodeId,
        label: firstFrame.label,
        role: 'first_frame'
      }
    });
    const prompt = String(result?.prompt || result?.candidate?.text || '').trim();
    if (!prompt) throw new Error('H3 提示词编译没有返回可用内容');
    return {
      prompt,
      validation: result.validation || {},
      provenance: result.provenance || {},
      mode: result.mode || 'I2VA'
    };
  }

  function executeUpdateTextNode(action) {
    const target = window.DesktopCanvas?.fillPromptTarget?.(action.text || '', {
      nodeId: action.node_id || '',
      promptMeta: action.prompt_meta || {}
    });
    if (!target?.nodeId) throw new Error('文本节点更新失败');
    return { node_id: target.nodeId };
  }

  function executeApplyPrompt(action) {
    const requestedInputId = String(action.input_node_id || '');
    const target = window.DesktopCanvas?.fillNearestInputPrompt?.(action.text || '', {
      inputNodeId: requestedInputId,
      promptMeta: action.prompt_meta || {}
    });
    const snapshot = window.DesktopCanvas?.exportWorkflowSnapshot?.();
    const inputId = String(target?.nodeId || requestedInputId || 'input');
    const nodes = snapshot?.state?.canvas?.nodes || {};
    const edge = (snapshot?.state?.canvas?.edges || []).find(item => item.to === inputId && nodes[item.from]?.type === 'text');
    const textNodeId = String(target?.textNodeId || edge?.from || '');
    if (!textNodeId) throw new Error('提示词已写入，但没有找到对应文本节点');
    return { node_id: textNodeId, input_node_id: inputId };
  }

  function executeConnectNodes(action) {
    const edgeId = window.DesktopCanvas?.connectNodes?.(action.from_node_id, action.to_node_id, {
      quiet: true,
      inputRole: action.input_role || undefined
    });
    if (!edgeId) throw new Error('节点连接失败');
    return { edge_id: edgeId, from_node_id: action.from_node_id, to_node_id: action.to_node_id };
  }

  function normalizeActionParams(params = {}) {
    const next = { ...params };
    const aliases = {
      image_count: 'imageCount',
      archive_enabled: 'archiveEnabled',
      telegram_enabled: 'telegramEnabled',
      prompt_mode: 'promptMode',
      gpt_provider_route: 'gptProviderRoute',
      main_model: 'gptMainModel',
      reasoning_effort: 'reasoningEffort'
    };
    Object.entries(aliases).forEach(([source, target]) => {
      if (next[source] !== undefined) next[target] = next[source];
    });
    return next;
  }

  async function executeSubmitGeneration(action) {
    const resultNodeId = String(action.result_node_id || 'input');
    const current = window.DesktopCanvas?.readConfigForResult?.(resultNodeId);
    if (!current) throw new Error('无法读取模型节点配置');
    const params = {
      ...(current.params || {}),
      ...normalizeActionParams(action.params || {})
    };
    const config = {
      ...current,
      provider: action.provider || current.provider || 'gpt',
      prompt: String(action.prompt || current.prompt || '').trim(),
      params
    };
    if (!config.prompt) throw new Error('Agent 没有生成可提交的提示词');
    if (config.provider === 'gpt') {
      config.expectedImageOutputCount = Math.max(1, Number(params.imageCount || 1));
    }
    window.DesktopCanvas?.ensureImageOutputsForConfig?.(resultNodeId, config);
    const response = await window.DesktopResults?.submitConfigToResult?.(config, resultNodeId);
    const taskId = String(response?.task_id || response?.taskId || '');
    if (!taskId) throw new Error('生成任务没有返回 task_id');
    return { task_id: taskId, result_node_id: resultNodeId };
  }

  async function executeSubmitVideoGeneration(action) {
    const videoNodeId = String(action.video_node_id || action.generation_node_id || action.result_node_id || '');
    if (!videoNodeId) throw new Error('Agent 没有找到 MiniMax H3 视频节点');
    const response = await window.DesktopCanvas?.runVideoInferenceNode?.(videoNodeId);
    const taskId = String(response?.task_id || response?.taskId || '');
    if (!taskId) throw new Error('视频生成任务没有返回 task_id');
    return { task_id: taskId, video_node_id: videoNodeId, result_node_id: videoNodeId, artifact_type: 'video' };
  }

  async function executeRollback(action) {
    const runId = String(action.run_id || action.snapshot_key || state.runId || '');
    const snapshot = await loadCanvasSnapshot(runId);
    if (!snapshot) throw new Error('本轮执行前的画布快照不存在');
    const restored = window.DesktopCanvas?.applyWorkflowSnapshot?.(snapshot, { confirm: false });
    if (!restored) throw new Error('画布快照恢复失败');
    return { restored: true, snapshot_key: runId };
  }

  async function executeClientAction(action) {
    switch (String(action?.type || '')) {
      case 'analyze_images':
        return executeAnalyzeImages(action);
      case 'compile_h3_prompt':
        return executeCompileH3Prompt(action);
      case 'update_text_node':
        return executeUpdateTextNode(action);
      case 'apply_prompt_to_input':
        return executeApplyPrompt(action);
      case 'connect_nodes':
        return executeConnectNodes(action);
      case 'submit_generation':
        return executeSubmitGeneration(action);
      case 'submit_video_generation':
        return executeSubmitVideoGeneration(action);
      case 'rollback_canvas':
        return executeRollback(action);
      default:
        throw new Error(`不支持的 Agent 画布动作：${action?.type || 'unknown'}`);
    }
  }

  async function processWaitingAction() {
    const run = state.run;
    const actionId = String(run?.waiting_action_id || '');
    if (!actionId || run.status !== 'waiting_for_action' || state.actionInFlight === actionId) return;
    const event = actionEventFor(actionId);
    const action = event?.payload?.action;
    if (!action) return;
    state.actionInFlight = actionId;
    render();
    try {
      let receipt = state.actionReceipts.get(actionId);
      if (!receipt) {
        try {
          const result = await executeClientAction(action);
          receipt = { ok: true, result };
        } catch (error) {
          receipt = { ok: false, error: error?.message || String(error || '桌面动作执行失败'), result: {} };
        }
        state.actionReceipts.set(actionId, receipt);
      }
      const response = await window.DesktopApi.submitAgentAction(run.run_id, actionId, receipt);
      state.actionReceipts.delete(actionId);
      applyRunPayload(response);
      if (receipt.ok === false) {
        window.DesktopResults?.showTransientMessage?.(`Agent 动作失败：${receipt.error}`, 'error');
      }
      schedulePoll(120);
    } catch (error) {
      console.warn('[PromptAgent] action receipt failed:', error);
      schedulePoll(500);
    } finally {
      state.actionInFlight = '';
      render();
    }
  }

  async function createPlan() {
    if (state.creating || isRunActive()) return;
    closeImageMentionMenu();
    const goal = goalText();
    if (!goal) {
      window.DesktopResults?.showTransientMessage?.('请先填写 Agent 目标。', 'warning');
      els.deskAgentGoal?.focus?.();
      return;
    }
    if (goal.length > 2000) {
      window.DesktopResults?.showTransientMessage?.('Agent 目标最多 2000 个字符。', 'warning');
      els.deskAgentGoal?.focus?.();
      return;
    }
    state.creating = true;
    state.events = [];
    state.eventSeq = 0;
    render();
    try {
      const request = captureAgentRequest(goal);
      const run = await window.DesktopApi.createAgentRun(request.payload);
      await storeCanvasSnapshot(run.run_id, request.snapshot);
      applyRunPayload(run);
      window.DesktopResults?.showTransientMessage?.('Agent 计划已生成，等待确认。', 'success');
      schedulePoll(900);
    } catch (error) {
      window.DesktopResults?.showError?.(error);
    } finally {
      state.creating = false;
      render();
    }
  }

  async function controlRun(action, payload = {}) {
    if (!state.runId || state.controlling) return;
    state.controlling = true;
    render();
    try {
      const run = await window.DesktopApi.controlAgentRun(state.runId, action, payload);
      applyRunPayload(run);
      schedulePoll(120);
    } catch (error) {
      window.DesktopResults?.showError?.(error);
    } finally {
      state.controlling = false;
      render();
    }
  }

  function setSelectValue(select, value, fallback) {
    if (!select) return;
    const requested = String(value ?? '');
    const available = [...select.options].some(option => option.value === requested);
    select.value = available ? requested : String(fallback);
  }

  function approvalBoolean(value, fallback = true) {
    if (value === undefined || value === null) return fallback;
    return ![false, 0, '0', 'false', 'off'].includes(value);
  }

  function isVideoRun(run = state.run) {
    const confirmation = run?.plan?.confirmation || {};
    return run?.plan?.task_domain === 'video'
      || confirmation.task_domain === 'video'
      || confirmation.provider === 'minimax_h3';
  }

  function approvalDraftFromRun(run) {
    const confirmation = run?.plan?.confirmation || {};
    const approval = run?.request?.approval || {};
    const params = approval.params && typeof approval.params === 'object' ? approval.params : {};
    const imageCount = Number(params.image_count ?? params.imageCount ?? approval.image_count ?? approval.imageCount ?? confirmation.image_count ?? 1);
    return {
      provider: String(approval.provider || confirmation.provider || 'gpt').toLowerCase() === 'google' ? 'google' : 'gpt',
      ratio: params.ratio ?? approval.ratio ?? confirmation.ratio ?? '1:1',
      resolution: params.resolution ?? approval.resolution ?? confirmation.resolution ?? '2k',
      quality: params.quality ?? approval.quality ?? confirmation.quality ?? 'auto',
      imageCount: Math.max(1, Math.min(8, Number.isFinite(imageCount) ? Math.floor(imageCount) : 1)),
      archiveEnabled: approvalBoolean(
        params.archive_enabled ?? params.archiveEnabled ?? approval.archive_enabled ?? confirmation.archive_enabled,
        true
      ),
      telegramEnabled: approvalBoolean(
        params.telegram_enabled ?? params.telegramEnabled ?? approval.telegram_enabled ?? confirmation.telegram_enabled,
        true
      )
    };
  }

  function currentApprovalProvider() {
    return els.deskAgentProviderGoogle?.classList.contains('is-active') ? 'google' : 'gpt';
  }

  function approvalDraftFromControls() {
    const provider = currentApprovalProvider();
    return {
      provider,
      ratio: els.deskAgentRatio?.value || '1:1',
      resolution: String(els.deskAgentResolution?.value || '2k').toLowerCase(),
      quality: String(els.deskAgentQuality?.value || 'auto').toLowerCase(),
      imageCount: provider === 'google'
        ? 1
        : Math.max(1, Math.min(8, Number(els.deskAgentImageCount?.value || 1))),
      archiveEnabled: els.deskAgentArchiveEnabled?.checked !== false,
      telegramEnabled: els.deskAgentTelegramEnabled?.checked !== false
    };
  }

  function decisionAttention(draft = approvalDraftFromControls()) {
    if (isVideoRun()) return [];
    const attention = [];
    if (draft.resolution === '4k') attention.push('4K');
    if (draft.imageCount > 1) attention.push(`${draft.imageCount} 张`);
    if (draft.telegramEnabled) attention.push('Telegram');
    return attention;
  }

  function formatDecision(draft = approvalDraftFromControls()) {
    if (isVideoRun()) {
      const confirmation = state.run?.plan?.confirmation || {};
      const mode = String(confirmation.h3_mode || confirmation.mode || 'I2VA').toUpperCase();
      const duration = Number(confirmation.duration_seconds || 15);
      const aspectRatio = String(confirmation.aspect_ratio || confirmation.ratio || '3:4');
      const pixelBudget = Number(confirmation.pixel_budget_mp || 0.8);
      const durationLabel = Number.isInteger(duration) ? String(duration) : String(Number(duration.toFixed(2)));
      const acceleration = {
        off: '标准模式',
        first_block_cache: 'FirstBlockCache',
        sol_attn: 'Sol-Attn',
        combined: '组合加速'
      }[String(confirmation.acceleration_mode || '')] || '沿用节点设置';
      return ['MiniMax H3', mode, `${durationLabel} 秒`, aspectRatio, `${pixelBudget} MP`, acceleration].join(' · ');
    }
    const qualityLabels = { auto: '自动质量', low: '低质量', medium: '中等质量', high: '高质量' };
    const parts = [
      draft.provider === 'google' ? 'Google' : 'GPT',
      draft.ratio,
      draft.resolution.toUpperCase()
    ];
    if (draft.provider === 'gpt') parts.push(qualityLabels[draft.quality] || '自动质量');
    parts.push(
      `${draft.imageCount} 张`,
      draft.archiveEnabled ? '自动归档' : '不归档',
      draft.telegramEnabled ? '发送 Telegram' : '不发送 Telegram'
    );
    return parts.join(' · ');
  }

  function updateDecisionView() {
    const draft = approvalDraftFromControls();
    const confirmation = state.run?.plan?.confirmation || {};
    if (els.deskAgentDecisionText) els.deskAgentDecisionText.textContent = formatDecision(draft);
    if (els.deskAgentDecisionBasis) {
      const basis = Array.isArray(confirmation.decision_basis) ? confirmation.decision_basis.filter(Boolean) : [];
      els.deskAgentDecisionBasis.textContent = state.approvalManual
        ? '已使用高级调整'
        : String(basis[0] || '沿用当前模型节点设置');
    }
    if (els.deskAgentDecisionAttention) {
      const notes = Array.isArray(confirmation.decision_notes) ? confirmation.decision_notes.filter(Boolean) : [];
      const impacts = decisionAttention(draft);
      const text = [...notes, ...(impacts.length ? [`需确认：${impacts.join('、')}`] : [])].join(' · ');
      els.deskAgentDecisionAttention.textContent = text;
      els.deskAgentDecisionAttention.hidden = !text;
    }
  }

  function setApprovalProvider(provider, options = {}) {
    const next = provider === 'google' ? 'google' : 'gpt';
    const previous = currentApprovalProvider();
    [els.deskAgentProviderGpt, els.deskAgentProviderGoogle].forEach(button => {
      if (!button) return;
      const active = button.dataset.agentProvider === next;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-checked', String(active));
    });
    if (els.deskAgentImageCount) {
      if (next === 'google') {
        if (previous === 'gpt') els.deskAgentImageCount.dataset.gptValue = els.deskAgentImageCount.value || '1';
        els.deskAgentImageCount.value = '1';
      } else if (previous === 'google' && options.restoreCount !== false) {
        setSelectValue(els.deskAgentImageCount, els.deskAgentImageCount.dataset.gptValue || '1', '1');
      }
    }
    if (options.manual) state.approvalManual = true;
    updateApprovalControlState();
    updateApprovalHint();
  }

  function syncApprovalControls(run) {
    const runId = String(run?.run_id || '');
    if (state.approvalRunId === runId) return;
    state.approvalRunId = runId;
    state.approvalParamsExpanded = false;
    state.approvalManual = false;
    if (!runId) return;
    if (isVideoRun(run)) return;
    const draft = approvalDraftFromRun(run);
    setSelectValue(els.deskAgentRatio, draft.ratio, '1:1');
    setSelectValue(els.deskAgentResolution, String(draft.resolution).toLowerCase(), '2k');
    setSelectValue(els.deskAgentQuality, String(draft.quality).toLowerCase(), 'auto');
    setSelectValue(els.deskAgentImageCount, draft.imageCount, '1');
    if (els.deskAgentImageCount) els.deskAgentImageCount.dataset.gptValue = String(draft.imageCount);
    if (els.deskAgentArchiveEnabled) els.deskAgentArchiveEnabled.checked = draft.archiveEnabled;
    if (els.deskAgentTelegramEnabled) els.deskAgentTelegramEnabled.checked = draft.telegramEnabled;
    setApprovalProvider(draft.provider, { restoreCount: false });
  }

  function updateApprovalControlState() {
    const generationRequested = state.run?.plan?.generation_requested === true;
    const videoRun = isVideoRun();
    const editable = generationRequested
      && !videoRun
      && !state.controlling
      && !state.revising
      && state.run?.capabilities?.can_approve === true;
    const isGpt = currentApprovalProvider() === 'gpt';
    [els.deskAgentProviderGpt, els.deskAgentProviderGoogle].forEach(button => {
      if (button) button.disabled = !editable;
    });
    [els.deskAgentRatio, els.deskAgentResolution, els.deskAgentArchiveEnabled, els.deskAgentTelegramEnabled].forEach(control => {
      if (control) control.disabled = !editable;
    });
    [els.deskAgentQuality, els.deskAgentImageCount].forEach(control => {
      if (control) control.disabled = !editable || !isGpt;
    });
    els.deskAgentParams?.querySelectorAll('[data-agent-gpt-only]').forEach(field => {
      field.classList.toggle('is-disabled', !isGpt);
    });
    if (els.deskAgentParamsToggle) {
      els.deskAgentParamsToggle.hidden = videoRun;
      els.deskAgentParamsToggle.disabled = !editable;
      els.deskAgentParamsToggle.setAttribute('aria-expanded', String(state.approvalParamsExpanded));
    }
    const revisionEditable = generationRequested
      && !state.controlling
      && !state.revising
      && state.run?.capabilities?.can_approve === true;
    if (els.deskAgentRevisionInput) els.deskAgentRevisionInput.disabled = !revisionEditable;
    if (els.deskAgentRevisionSubmit) els.deskAgentRevisionSubmit.disabled = !revisionEditable;
    if (els.deskAgentRevisionSubmitLabel) {
      els.deskAgentRevisionSubmitLabel.textContent = state.revising ? '更新中' : '更新';
    }
  }

  function updateApprovalHint() {
    if (!els.deskAgentApprovalHint) return;
    if (state.run?.plan?.generation_requested !== true) {
      els.deskAgentApprovalHint.textContent = '本轮不提交生成任务';
      return;
    }
    if (isVideoRun()) {
      els.deskAgentApprovalHint.textContent = '确认后将编译提示词并提交视频任务';
      updateDecisionView();
      return;
    }
    const attention = decisionAttention();
    els.deskAgentApprovalHint.textContent = attention.length
      ? `确认 ${attention.join(' · ')}`
      : '可直接批准';
    updateDecisionView();
  }

  function toggleApprovalParams() {
    if (els.deskAgentParamsToggle?.disabled) return;
    state.approvalParamsExpanded = !state.approvalParamsExpanded;
    renderApproval();
  }

  async function reviseDecision(event) {
    event?.preventDefault?.();
    if (state.revising || !state.runId || state.run?.capabilities?.can_revise !== true) return;
    const instruction = String(els.deskAgentRevisionInput?.value || '').trim();
    if (!instruction) {
      els.deskAgentRevisionInput?.focus?.();
      return;
    }
    state.revising = true;
    renderApproval();
    try {
      const run = await window.DesktopApi.controlAgentRun(state.runId, 'revise', { instruction });
      state.approvalRunId = '';
      state.approvalParamsExpanded = false;
      state.approvalManual = false;
      applyRunPayload(run);
      if (els.deskAgentRevisionInput) els.deskAgentRevisionInput.value = '';
      window.DesktopResults?.showTransientMessage?.('Agent 已更新生成决策。', 'success');
    } catch (error) {
      window.DesktopResults?.showError?.(error);
    } finally {
      state.revising = false;
      renderApproval();
    }
  }

  function approveRun() {
    const generationRequested = state.run?.plan?.generation_requested === true;
    if (isVideoRun()) {
      state.approvalParamsExpanded = false;
      return controlRun('approve', { approval: {} });
    }
    const draft = approvalDraftFromControls();
    const approval = generationRequested ? {
      provider: draft.provider,
      params: {
        ratio: draft.ratio,
        resolution: draft.resolution,
        quality: draft.quality,
        image_count: draft.imageCount,
        archive_enabled: draft.archiveEnabled,
        telegram_enabled: draft.telegramEnabled
      }
    } : {};
    state.approvalParamsExpanded = false;
    return controlRun('approve', { approval });
  }

  function togglePause() {
    if (state.run?.capabilities?.can_resume) return controlRun('resume');
    return controlRun('pause');
  }

  function statusLabel(status) {
    return STATUS_LABELS[String(status || '')] || String(status || '待命');
  }

  function stepStatus(step, index, run) {
    const raw = String(step?.status || 'pending');
    if (raw !== 'pending') return raw;
    if (run?.status === 'awaiting_approval' && index === 0) return 'awaiting';
    return 'pending';
  }

  function stepStatusLabel(status) {
    return {
      pending: '等待',
      awaiting: '待批准',
      running: '执行中',
      succeeded: '完成',
      failed: '失败'
    }[status] || status;
  }

  function renderSteps() {
    if (!els.deskAgentSteps) return;
    const steps = Array.isArray(state.run?.plan?.steps) ? state.run.plan.steps : [];
    if (!steps.length) {
      els.deskAgentSteps.innerHTML = '<div class="desk-agent-empty">填写目标后生成计划。计划确认前不会修改画布或提交生成任务。</div>';
      return;
    }
    els.deskAgentSteps.innerHTML = steps.map((step, index) => {
      const status = stepStatus(step, index, state.run);
      const dot = status === 'succeeded' ? '✓' : (status === 'failed' ? '!' : String(index + 1));
      return `
        <div class="desk-agent-step is-${escapeHtml(status)}">
          <span class="desk-agent-step__dot">${escapeHtml(dot)}</span>
          <div class="desk-agent-step__copy">
            <strong>${escapeHtml(step.title || step.kind || `步骤 ${index + 1}`)}</strong>
            <span>${escapeHtml(step.description || step.tool || '')}</span>
          </div>
          <span class="desk-agent-step__state">${escapeHtml(stepStatusLabel(status))}</span>
        </div>
      `;
    }).join('');
  }

  function formatEventTime(createdAt) {
    const value = Number(createdAt || 0);
    if (!value) return '';
    try {
      return new Date(value * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (error) {
      return '';
    }
  }

  function renderEvents() {
    if (!els.deskAgentEvents) return;
    const events = state.events.slice(-40).reverse();
    if (els.deskAgentEventMeta) els.deskAgentEventMeta.textContent = `${state.events.length} 条`;
    if (!events.length) {
      els.deskAgentEvents.innerHTML = '<div class="desk-agent-empty">运行开始后，这里会记录计划、画布动作和生成进度。</div>';
      return;
    }
    els.deskAgentEvents.innerHTML = events.map(event => `
      <div class="desk-agent-event is-${escapeHtml(event.status || 'idle')}">
        <i aria-hidden="true"></i>
        <div class="desk-agent-event__copy">
          <strong>${escapeHtml(EVENT_LABELS[event.event_type] || event.event_type || 'Agent 事件')}</strong>
          <span>${escapeHtml(event.message || statusLabel(event.status))}</span>
        </div>
        <time>${escapeHtml(formatEventTime(event.created_at))}</time>
      </div>
    `).join('');
  }

  function renderApproval() {
    const run = state.run;
    const plan = run?.plan || {};
    const steps = Array.isArray(plan.steps) ? plan.steps : [];
    const hasDecision = !!steps.length && plan.generation_requested === true;
    syncApprovalControls(run);
    if (els.deskAgentPlanMeta) {
      const taskLabel = isVideoRun(run) ? '视频生成' : '图片生成';
      els.deskAgentPlanMeta.textContent = steps.length
        ? `${steps.length} 步${plan.generation_requested ? ` · 含${taskLabel}` : ''}`
        : '尚未创建';
    }
    if (els.deskAgentApprovalTitle) {
      els.deskAgentApprovalTitle.textContent = run?.status === 'awaiting_approval'
        ? (hasDecision ? 'Agent 已完成决策' : '需要确认后执行')
        : (run ? statusLabel(run.status) : '先生成计划');
    }
    if (els.deskAgentDecision) els.deskAgentDecision.hidden = !hasDecision;
    if (els.deskAgentRevisionForm) {
      els.deskAgentRevisionForm.hidden = isVideoRun(run) || !hasDecision || run?.status !== 'awaiting_approval';
    }
    if (els.deskAgentParams) {
      els.deskAgentParams.hidden = isVideoRun(run)
        || !hasDecision
        || !state.approvalParamsExpanded
        || run?.capabilities?.can_approve !== true;
    }
    updateApprovalHint();
    updateApprovalControlState();
    if (els.deskAgentApprove) {
      els.deskAgentApprove.disabled = state.controlling || state.revising || !run?.capabilities?.can_approve;
    }
  }

  function renderArtifact() {
    const run = state.run;
    const result = run?.result || {};
    const prompt = String(result.prompt || '');
    const taskId = String(result.task_id || run?.task_id || '');
    let title = '尚无产物';
    let text = '批准计划后，提示词和生成任务会在这里更新。';
    if (run?.error) {
      title = statusLabel(run.status);
      text = String(run.error);
    } else if (taskId) {
      title = `${isVideoRun(run) ? '视频任务' : '图片任务'} · ${taskId.slice(-12)}`;
      text = prompt || '任务已提交到现有生成队列。';
    } else if (prompt) {
      title = '提示词已整理';
      text = prompt;
    } else if (run) {
      title = statusLabel(run.status);
      text = String(run.plan?.summary || run.goal || '');
    }
    if (els.deskAgentArtifactTitle) els.deskAgentArtifactTitle.textContent = title;
    if (els.deskAgentArtifactText) els.deskAgentArtifactText.textContent = text;
  }

  function renderControls() {
    const run = state.run;
    const status = String(run?.status || 'idle');
    if (els.deskAgentStatus) {
      els.deskAgentStatus.dataset.status = status;
      const label = els.deskAgentStatus.querySelector('span');
      if (label) label.textContent = state.actionInFlight ? '正在操作画布' : statusLabel(status);
    }
    const canResume = !!run?.capabilities?.can_resume;
    const canPause = !!run?.capabilities?.can_pause;
    if (els.deskAgentPause) {
      els.deskAgentPause.disabled = state.controlling || (!canPause && !canResume);
      els.deskAgentPause.title = canResume ? '继续 Agent' : '暂停 Agent';
      els.deskAgentPause.setAttribute('aria-label', canResume ? '继续 Agent' : '暂停 Agent');
    }
    if (els.deskAgentPauseIcon) {
      els.deskAgentPauseIcon.classList.toggle('desk-icon--pause', !canResume);
      els.deskAgentPauseIcon.classList.toggle('desk-icon--play', canResume);
    }
    if (els.deskAgentRollback) els.deskAgentRollback.disabled = state.controlling || !run?.capabilities?.can_rollback;
    if (els.deskAgentCancel) els.deskAgentCancel.disabled = state.controlling || !run?.capabilities?.can_cancel;
    const locked = state.creating || state.controlling || isRunActive(run);
    if (els.deskAgentGoal) {
      els.deskAgentGoal.setAttribute('contenteditable', String(!locked));
      els.deskAgentGoal.setAttribute('aria-disabled', String(locked));
      els.deskAgentGoal.classList.toggle('is-disabled', locked);
    }
    if (locked) closeImageMentionMenu();
    if (els.deskAgentScope) els.deskAgentScope.disabled = locked;
    if (els.deskAgentAutoGenerate) els.deskAgentAutoGenerate.disabled = locked;
    if (els.deskAgentCreatePlan) {
      els.deskAgentCreatePlan.disabled = locked;
      const label = els.deskAgentCreatePlan.querySelector('span:last-child');
      if (label) label.textContent = state.creating ? '正在创建' : '生成计划';
    }
  }

  function render() {
    renderControls();
    renderSteps();
    renderApproval();
    renderEvents();
    renderArtifact();
  }

  async function restoreActiveRun() {
    if (state.restoreStarted) return;
    state.restoreStarted = true;
    const runId = readStorage(ACTIVE_RUN_KEY, '');
    if (!runId) return;
    state.runId = runId;
    try {
      const run = await window.DesktopApi.getAgentRun(runId, { eventsSince: 0, eventLimit: 300 });
      applyRunPayload(run);
      await processWaitingAction();
      if (!TERMINAL_STATUSES.has(String(run.status || ''))) schedulePoll(500);
    } catch (error) {
      console.warn('[PromptAgent] restore failed:', error);
      state.runId = '';
      writeStorage(ACTIVE_RUN_KEY, '');
    }
  }

  function bindEvents() {
    els.deskPromptAssistantMode?.addEventListener('click', () => setMode('assistant'));
    els.deskPromptAgentMode?.addEventListener('click', () => setMode('agent'));
    els.deskAgentCreatePlan?.addEventListener('click', createPlan);
    els.deskAgentApprove?.addEventListener('click', approveRun);
    [els.deskAgentProviderGpt, els.deskAgentProviderGoogle].forEach(button => {
      button?.addEventListener('click', () => {
        if (!button.disabled) setApprovalProvider(button.dataset.agentProvider, { manual: true });
      });
    });
    els.deskAgentParamsToggle?.addEventListener('click', toggleApprovalParams);
    els.deskAgentRevisionForm?.addEventListener('submit', reviseDecision);
    els.deskAgentParams?.addEventListener('change', () => {
      state.approvalManual = true;
      updateApprovalHint();
    });
    els.deskAgentPause?.addEventListener('click', togglePause);
    els.deskAgentRollback?.addEventListener('click', () => controlRun('rollback'));
    els.deskAgentCancel?.addEventListener('click', () => controlRun('cancel'));
    els.deskAgentImageMenu?.addEventListener('click', event => {
      const button = event.target.closest('[data-agent-pick-image-node]');
      if (!button) return;
      attachImageNode(button.dataset.agentPickImageNode);
    });
    ['desktop:canvas-selection-change', 'desktop:canvas-text-nodes-change', 'desktop:canvas-node-removed'].forEach(name => {
      window.addEventListener(name, refreshContextPreview);
    });
    window.addEventListener('miniapp:auth-state-change', event => {
      if (event.detail?.authenticated) restoreActiveRun();
    });
  }

  function init() {
    collectElements();
    if (!els.deskPromptDrawer || !els.deskAgentWorkbench) return;
    initGoalEditor();
    const savedMode = readStorage(MODE_KEY, 'assistant');
    setMode(savedMode === 'agent' ? 'agent' : 'assistant', { open: false });
    refreshContextPreview();
    render();
    bindEvents();
    if (typeof window.isMiniappAuthReady === 'function' && window.isMiniappAuthReady()) {
      restoreActiveRun();
    } else if (typeof window.waitForMiniappAuthReady === 'function') {
      window.waitForMiniappAuthReady(9000).then(ok => {
        if (ok) restoreActiveRun();
      });
    }
  }

  window.DesktopPromptAgent = {
    init,
    setMode,
    render,
    refreshContext: refreshContextPreview,
    poll: pollRun
  };
})();
