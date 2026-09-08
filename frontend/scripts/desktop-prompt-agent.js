(function () {
  const MODE_KEY = 'desktop_prompt_workspace_mode_v1';
  const ACTIVE_RUN_KEY = 'desktop_prompt_agent_active_run_v1';
  const ACTIVE_TASK_KEY = 'desktop_prompt_agent_active_task_v2';
  const TASK_REGISTRY_KEY = 'desktop_prompt_agent_tasks_v2';
  const SNAPSHOT_DB = 'desktop_prompt_agent_v1';
  const SNAPSHOT_DB_VERSION = 2;
  const SNAPSHOT_STORE = 'canvas_snapshots';
  const ACTION_RECEIPT_STORE = 'action_receipts';
  const MAX_IMAGE_REFERENCES = 4;
  const MAX_ACTIVE_TASKS = 24;
  const MAX_TASK_HISTORY = 100;
  const MAX_RAIL_TERMINAL_TASKS = 3;
  const RESTORE_HYDRATE_CONCURRENCY = 4;
  const TASK_POLL_DELAYS = Object.freeze({
    selectedRunning: 850,
    backgroundRunning: 5_000,
    selectedWaiting: 850,
    backgroundWaiting: 10_000,
    selectedIdle: 8_000,
    backgroundIdle: 15_000,
    hiddenSelectedRunning: 5_000,
    hiddenBackground: 30_000
  });
  const CANVAS_FINGERPRINT_IGNORED_KEYS = new Set(['x', 'y', 'scale', 'selectedNodeId', 'selectedNodeIds']);
  const CANVAS_MUTATION_ACTIONS = new Set([
    'update_text_node',
    'apply_prompt_to_input',
    'connect_nodes',
    'submit_generation',
    'submit_video_generation',
    'rollback_canvas'
  ]);
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
    rolled_back: '已回滚',
    draft: '草稿'
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
    snapshots: new Map(),
    tasks: new Map(),
    taskOrder: [],
    selectedTaskKey: '',
    taskCounter: 0,
    persistTimer: 0,
    draftCreationLocked: false,
    switchingTask: false,
    restoringTasks: false,
    restoreRetryTimer: 0,
    restoreAttempts: 0,
    canvasMutationTail: Promise.resolve(),
    canvasMutationOwner: '',
    taskDrawerOpen: false,
    taskSearch: '',
    taskFilter: 'all',
    taskNavigationRenderFrame: 0,
    taskCardMenuKey: '',
    taskDialogMode: '',
    taskDialogTaskKey: '',
    taskDialogReturnFocus: null,
    deletingTask: false
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

  function readJsonStorage(key, fallback) {
    try {
      const parsed = JSON.parse(readStorage(key, ''));
      return parsed ?? fallback;
    } catch (error) {
      return fallback;
    }
  }

  function taskLetter(ordinal) {
    let value = Math.max(1, Number(ordinal || 1));
    let output = '';
    while (value > 0) {
      value -= 1;
      output = String.fromCharCode(65 + (value % 26)) + output;
      value = Math.floor(value / 26);
    }
    return output;
  }

  function createClientTaskId() {
    let seed = '';
    try {
      seed = window.crypto?.randomUUID?.().replace(/[^a-z0-9]/gi, '') || '';
    } catch (error) {}
    if (!seed) seed = `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
    return `AG-${seed.slice(-6).toUpperCase().padStart(6, '0')}`;
  }

  function selectedTask() {
    return state.tasks.get(state.selectedTaskKey) || null;
  }

  function findTaskByRunId(runId) {
    const cleanId = String(runId || '').trim();
    if (!cleanId) return null;
    return state.taskOrder
      .map(key => state.tasks.get(key))
      .find(task => task?.runId === cleanId) || null;
  }

  function compactImageReferences(items = []) {
    return (Array.isArray(items) ? items : []).slice(0, MAX_IMAGE_REFERENCES).map(item => ({
      id: String(item?.id || '').trim(),
      label: String(item?.label || item?.id || '图片节点').trim(),
      sourceNodeId: String(item?.sourceNodeId || item?.nodeId || item?.source_node_id || '').trim(),
      mimeType: String(item?.mimeType || item?.type || 'image/png').trim()
    })).filter(item => item.id && item.sourceNodeId);
  }

  function hydrateImageReferences(items = []) {
    const nodes = getImageNodes();
    return compactImageReferences(items).map(item => {
      const node = nodes.find(candidate => String(candidate.nodeId || '') === item.sourceNodeId);
      return node ? { ...node, ...item } : item;
    });
  }

  function runImageReferences(run = {}) {
    const references = Array.isArray(run?.context?.referenced_images)
      ? run.context.referenced_images
      : [];
    return hydrateImageReferences(references.map((reference, index) => ({
      id: String(reference?.id || `image${index + 1}`),
      label: String(reference?.label || reference?.id || `图片 ${index + 1}`),
      sourceNodeId: String(reference?.source_node_id || reference?.sourceNodeId || ''),
      mimeType: String(reference?.mime_type || reference?.mimeType || 'image/png')
    })));
  }

  function taskClientIdFromRun(run = {}) {
    const stored = String(run?.request?.client?.agent_task_id || '').trim();
    if (stored) return stored;
    const suffix = String(run?.run_id || '').replace(/[^a-z0-9]/gi, '').slice(-6).toUpperCase();
    return `AG-${suffix || createClientTaskId().slice(3)}`;
  }

  function explicitTaskClientIdFromRun(run = {}) {
    return String(run?.request?.client?.agent_task_id || '').trim();
  }

  function normalizeTaskName(value) {
    return String(value || '').replace(/\s+/g, ' ').trim().slice(0, 40);
  }

  function taskNameFromRun(run = {}) {
    return normalizeTaskName(run?.request?.client?.agent_task_name || '');
  }

  function ensureTaskRecord(options = {}) {
    const run = options.run && typeof options.run === 'object' ? options.run : null;
    const runId = String(options.runId || run?.run_id || '').trim();
    const existing = runId ? findTaskByRunId(runId) : state.tasks.get(String(options.key || ''));
    if (existing) {
      if (run) existing.run = { ...(existing.run || {}), ...run };
      if (runId) existing.runId = runId;
      const requestedClientTaskId = String(options.clientTaskId || '').trim();
      if (requestedClientTaskId && !existing.clientTaskId) existing.clientTaskId = requestedClientTaskId;
      const requestedName = normalizeTaskName(options.name || taskNameFromRun(run || {}));
      if (requestedName && !existing.name) existing.name = requestedName;
      const requestedFingerprint = String(options.canvasFingerprint || options.canvas_fingerprint || '').trim();
      if (requestedFingerprint && !existing.canvasFingerprint) existing.canvasFingerprint = requestedFingerprint;
      if (options.canvasDiverged === true || options.canvas_diverged === true) existing.canvasDiverged = true;
      if (Object.prototype.hasOwnProperty.call(options, 'pinned')) existing.pinned = options.pinned === true;
      if (Object.prototype.hasOwnProperty.call(options, 'archived')) existing.archived = options.archived === true;
      if (Object.prototype.hasOwnProperty.call(options, 'shelved')) existing.shelved = options.shelved === true;
      existing.updatedAt = Number(run?.updated_at || options.updatedAt || existing.updatedAt || Date.now() / 1000);
      return existing;
    }

    const ordinal = Math.max(1, Number(options.ordinal || state.taskCounter + 1));
    state.taskCounter = Math.max(state.taskCounter, ordinal);
    const clientTaskId = String(options.clientTaskId || taskClientIdFromRun(run || { run_id: runId }) || createClientTaskId());
    const key = String(options.key || (runId ? `run:${runId}` : `draft:${clientTaskId}`));
    const requestOptions = run?.request?.options || {};
    const task = {
      key,
      clientTaskId,
      name: normalizeTaskName(options.name || taskNameFromRun(run || {})),
      ordinal,
      runId,
      run,
      events: Array.isArray(options.events) ? options.events.slice(-300) : [],
      eventSeq: Number(options.eventSeq || 0),
      actionInFlight: '',
      actionPhase: '',
      actionReceipts: new Map(),
      deleting: false,
      deleted: false,
      polling: false,
      pollTimer: 0,
      loaded: !!options.loaded,
      canvasFingerprint: String(options.canvasFingerprint || options.canvas_fingerprint || ''),
      canvasDiverged: !!(options.canvasDiverged ?? options.canvas_diverged),
      pinned: options.pinned === true,
      archived: options.archived === true,
      shelved: options.shelved === true,
      createdAt: Number(options.createdAt || run?.created_at || Date.now() / 1000),
      updatedAt: Number(options.updatedAt || run?.updated_at || Date.now() / 1000),
      draft: {
        goal: String(options.draft?.goal || run?.goal || ''),
        references: compactImageReferences(options.draft?.references || runImageReferences(run || {})),
        scope: String(options.draft?.scope || requestOptions.scope || 'selection') === 'canvas' ? 'canvas' : 'selection',
        autoGenerate: options.draft?.autoGenerate
          ?? options.draft?.auto_generate
          ?? (requestOptions.auto_generate !== false)
      }
    };
    state.tasks.set(key, task);
    state.taskOrder.push(key);
    return task;
  }

  function taskIdentity(task = selectedTask()) {
    if (!task) return '';
    if (task.name) return task.name;
    const goal = String(task.run?.goal || task.draft?.goal || '').replace(/\s+/g, ' ').trim();
    if (goal) return goal.length > 24 ? `${goal.slice(0, 24)}…` : goal;
    return `任务 ${taskLetter(task.ordinal)}`;
  }

  function taskSystemIdentity(task = selectedTask()) {
    if (!task) return '';
    return `${taskLetter(task.ordinal)} · ${task.clientTaskId}`;
  }

  function taskProgress(task) {
    const steps = Array.isArray(task?.run?.plan?.steps) ? task.run.plan.steps : [];
    if (!steps.length) return '';
    const completed = steps.filter(step => step?.status === 'succeeded').length;
    const current = TERMINAL_STATUSES.has(String(task.run?.status || ''))
      ? completed
      : Math.max(completed, Math.min(steps.length, Number(task.run?.current_step || 0) + 1));
    return `${current}/${steps.length}`;
  }

  function taskTone(task) {
    const status = String(task?.run?.status || (task?.runId ? 'idle' : 'draft'));
    if (!task?.runId) return 'draft';
    if (status === 'running') return 'running';
    if (['awaiting_approval', 'waiting_for_action', 'paused', 'rolling_back'].includes(status)) return 'waiting';
    if (['failed', 'canceled'].includes(status)) return 'failed';
    if (['succeeded', 'rolled_back'].includes(status)) return 'done';
    return 'neutral';
  }

  function taskSummary(task) {
    if (!task?.runId) return '草稿';
    const status = String(task.run?.status || 'idle');
    const progress = taskProgress(task);
    if (status === 'running') return `执行中${progress ? ` · ${progress}` : ''}`;
    if (status === 'waiting_for_action') {
      const actionKey = `${task.runId}:${task.actionInFlight || task.run?.waiting_action_id || ''}`;
      return state.canvasMutationOwner === actionKey ? '正在操作画布' : '等待画布';
    }
    if (status === 'awaiting_approval') return '等待确认';
    if (status === 'paused') return '已暂停';
    if (status === 'rolling_back') return '正在回滚';
    if (status === 'succeeded') return '已完成';
    if (status === 'rolled_back') return '已回滚';
    if (status === 'failed') return '执行失败';
    if (status === 'canceled') return '已取消';
    return statusLabel(status);
  }

  function allTaskRecords() {
    return state.taskOrder.map(key => state.tasks.get(key)).filter(Boolean);
  }

  function taskStatusGroup(task) {
    if (!task?.runId) return 'draft';
    const status = String(task.run?.status || 'idle');
    if (status === 'running') return 'running';
    if (['awaiting_approval', 'waiting_for_action', 'paused', 'rolling_back', 'idle'].includes(status)) return 'waiting';
    if (['succeeded', 'rolled_back'].includes(status)) return 'done';
    if (['failed', 'canceled'].includes(status)) return 'failed';
    return 'waiting';
  }

  function taskGoalPreview(task) {
    const raw = String(task?.run?.goal || task?.draft?.goal || '').replace(/\s+/g, ' ').trim();
    if (!raw) return task?.runId ? '未记录任务目标' : '尚未填写任务目标';
    return raw.length > 72 ? `${raw.slice(0, 72)}…` : raw;
  }

  function taskUpdatedLabel(task) {
    const updatedAt = Number(task?.updatedAt || task?.createdAt || 0) * 1000;
    if (!updatedAt) return '时间未知';
    const delta = Math.max(0, Date.now() - updatedAt);
    if (delta < 60_000) return '刚刚更新';
    if (delta < 3_600_000) return `${Math.max(1, Math.floor(delta / 60_000))} 分钟前`;
    if (delta < 86_400_000) return `${Math.max(1, Math.floor(delta / 3_600_000))} 小时前`;
    const date = new Date(updatedAt);
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hour}:${minute}`;
  }

  function taskNavigationSignature(task) {
    if (!task) return '';
    return JSON.stringify([
      taskIdentity(task),
      task.name || '',
      task.runId || '',
      taskSummary(task),
      taskTone(task),
      taskGoalPreview(task),
      Number(task.updatedAt || 0),
      task.pinned === true,
      task.archived === true,
      task.shelved === true
    ]);
  }

  function taskViewOrder(tasks = allTaskRecords()) {
    return tasks.slice().sort((left, right) => (
      Number(right?.pinned === true) - Number(left?.pinned === true)
      || Number(left?.archived === true) - Number(right?.archived === true)
      || Number(right?.updatedAt || 0) - Number(left?.updatedAt || 0)
      || Number(left?.ordinal || 0) - Number(right?.ordinal || 0)
    ));
  }

  function railTasks() {
    const tasks = allTaskRecords().filter(task => !task.archived && !task.shelved);
    const selected = tasks.find(task => task.key === state.selectedTaskKey);
    const pinnedKeys = new Set(tasks.filter(task => task.pinned).map(task => task.key));
    const active = tasks.filter(task => (
      !task.runId || !TERMINAL_STATUSES.has(String(task.run?.status || 'idle'))
    ));
    const terminal = tasks.filter(task => (
      task.runId && TERMINAL_STATUSES.has(String(task.run?.status || ''))
    )).sort((left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0));
    const visibleKeys = new Set([
      ...pinnedKeys,
      ...active.map(task => task.key),
      ...terminal.slice(0, MAX_RAIL_TERMINAL_TASKS).map(task => task.key)
    ]);
    if (selected) visibleKeys.add(selected.key);

    // Keep the insertion order stable. Selecting a task only moves the Navy
    // selection ring; it never promotes the card to the beginning of the rail.
    return tasks.filter(task => visibleKeys.has(task.key));
  }

  function taskMatchesFilter(task, filter = state.taskFilter) {
    if (filter === 'all') return true;
    if (filter === 'archived') return task.archived === true;
    if (task.archived) return false;
    return taskStatusGroup(task) === filter;
  }

  function filteredDrawerTasks() {
    const query = String(state.taskSearch || '').trim().toLocaleLowerCase();
    return taskViewOrder(allTaskRecords()).filter(task => {
      if (!taskMatchesFilter(task)) return false;
      if (!query) return true;
      return [taskIdentity(task), task.clientTaskId, taskGoalPreview(task), taskSummary(task)]
        .some(value => String(value || '').toLocaleLowerCase().includes(query));
    });
  }

  function taskFilterCounts() {
    const tasks = allTaskRecords();
    return ['all', 'running', 'draft', 'waiting', 'done', 'failed', 'archived'].reduce((counts, filter) => {
      counts[filter] = tasks.filter(task => taskMatchesFilter(task, filter)).length;
      return counts;
    }, {});
  }

  function canArchiveTask(task) {
    if (!task) return false;
    if (task.key === state.selectedTaskKey && (state.creating || state.controlling || state.revising)) return false;
    if (task.archived || !task.runId) return true;
    return TERMINAL_STATUSES.has(String(task.run?.status || ''));
  }

  function canDeleteTask(task) {
    if (!task) return false;
    if (task.deleting || task.deleted) return false;
    if (task.key === state.selectedTaskKey && (state.creating || state.controlling || state.revising)) return false;
    if (!task.runId) return true;
    const status = String(task.run?.status || '');
    return status === 'awaiting_approval' || TERMINAL_STATUSES.has(status);
  }

  function taskDeleteBlockedReason(task) {
    if (!task) return '任务不存在';
    if (task.deleting) return '任务正在删除';
    if (task.key === state.selectedTaskKey && (state.creating || state.controlling || state.revising)) {
      return '当前任务操作尚未完成';
    }
    return '运行中的任务需先取消或等待完成后再删除';
  }

  function taskFocusDescriptor(root) {
    const active = document.activeElement;
    if (!root || !active || !root.contains(active)) return null;
    const menu = active.closest?.('[data-agent-task-menu]');
    if (menu) return { kind: 'menu', key: String(menu.dataset.agentTaskMenu || '') };
    const action = active.closest?.('[data-agent-task-action]');
    if (action) {
      return {
        kind: 'action',
        key: String(action.dataset.agentTaskKey || ''),
        action: String(action.dataset.agentTaskAction || '')
      };
    }
    const select = active.closest?.('[data-agent-task-select]');
    if (select) return { kind: 'select', key: String(select.dataset.agentTaskSelect || '') };
    const card = active.closest?.('[data-agent-task-key]');
    if (card) return { kind: 'card', key: String(card.dataset.agentTaskKey || '') };
    return null;
  }

  function findTaskControl(root, descriptor) {
    if (!root || !descriptor?.key) return null;
    if (descriptor.kind === 'menu') {
      return Array.from(root.querySelectorAll('[data-agent-task-menu]')).find(node => (
        node.dataset.agentTaskMenu === descriptor.key
      )) || null;
    }
    if (descriptor.kind === 'action') {
      return Array.from(root.querySelectorAll('[data-agent-task-action]')).find(node => (
        node.dataset.agentTaskKey === descriptor.key
        && node.dataset.agentTaskAction === descriptor.action
      )) || null;
    }
    const attribute = descriptor.kind === 'select' ? 'data-agent-task-select' : 'data-agent-task-key';
    return Array.from(root.querySelectorAll(`[${attribute}]`)).find(node => (
      node.getAttribute(attribute) === descriptor.key
    )) || null;
  }

  function isTaskNonTerminal(task) {
    if (!task || task.archived) return false;
    return !task.runId || !TERMINAL_STATUSES.has(String(task.run?.status || 'idle'));
  }

  function newestTaskRecords(tasks = []) {
    return tasks.slice().sort((left, right) => (
      Number(right?.updatedAt || 0) - Number(left?.updatedAt || 0)
      || Number(right?.ordinal || 0) - Number(left?.ordinal || 0)
    ));
  }

  function retainedTaskRecordsForStorage() {
    const records = allTaskRecords();
    const selected = state.tasks.get(state.selectedTaskKey) || null;
    const active = newestTaskRecords(records.filter(isTaskNonTerminal));
    const pinned = newestTaskRecords(records.filter(task => task?.pinned === true));
    const newest = newestTaskRecords(records);
    const retainedKeys = new Set();
    const reserve = task => {
      if (!task || retainedKeys.has(task.key) || retainedKeys.size >= MAX_TASK_HISTORY) return;
      retainedKeys.add(task.key);
    };

    // Selected and active work must survive the cap. Under the normal 24-active
    // limit every pin is retained too; if protected metadata is corrupted beyond
    // 100 records, newest active work wins before newest pins deterministically.
    reserve(selected);
    active.forEach(reserve);
    pinned.forEach(reserve);
    newest.forEach(reserve);

    const output = [];
    const emitted = new Set();
    const append = task => {
      if (!task || !retainedKeys.has(task.key) || emitted.has(task.key)) return;
      emitted.add(task.key);
      output.push(task);
    };
    append(selected);
    pinned.forEach(append);
    active.forEach(append);
    newest.forEach(append);
    return output;
  }

  function pruneTaskRegistry() {
    const records = allTaskRecords();
    const protectedKeys = new Set(records.filter(task => (
      task.key === state.selectedTaskKey || task.pinned === true || isTaskNonTerminal(task)
    )).map(task => task.key));
    const safeTerminal = newestTaskRecords(records.filter(task => (
      !protectedKeys.has(task.key)
      && (task.archived || (
        task.runId && TERMINAL_STATUSES.has(String(task.run?.status || ''))
      ))
      && !task.polling
      && !task.actionInFlight
      && !task.actionPhase
    )));
    const safeHistoryBudget = Math.max(0, MAX_TASK_HISTORY - protectedKeys.size);
    const retainedSafeKeys = new Set(safeTerminal.slice(0, safeHistoryBudget).map(task => task.key));
    const removable = safeTerminal.filter(task => !retainedSafeKeys.has(task.key));
    if (!removable.length) return 0;

    const removedKeys = new Set(removable.map(task => task.key));
    removable.forEach(task => {
      window.clearTimeout(task.pollTimer);
      task.pollTimer = 0;
      task.actionReceipts?.clear?.();
      if (task.runId) state.snapshots.delete(task.runId);
      state.tasks.delete(task.key);
    });
    state.taskOrder = state.taskOrder.filter(key => !removedKeys.has(key));
    return removable.length;
  }

  function persistTaskRegistry() {
    window.clearTimeout(state.persistTimer);
    state.persistTimer = 0;
    const prunedCount = pruneTaskRegistry();
    const retainedRecords = retainedTaskRecordsForStorage();
    const tasks = retainedRecords.map(task => {
      return {
        key: task.key,
        client_task_id: task.clientTaskId,
        name: task.name || '',
        ordinal: task.ordinal,
        run_id: task.runId,
        canvas_fingerprint: task.canvasFingerprint || '',
        canvas_diverged: task.canvasDiverged === true,
        pinned: task.pinned === true,
        archived: task.archived === true,
        shelved: task.shelved === true,
        created_at: task.createdAt,
        updated_at: task.updatedAt,
        draft: task.runId ? undefined : {
          goal: String(task.draft?.goal || ''),
          references: compactImageReferences(task.draft?.references || []),
          scope: task.draft?.scope === 'canvas' ? 'canvas' : 'selection',
          auto_generate: task.draft?.autoGenerate !== false
        }
      };
    });
    let registryStored = false;
    try {
      window.localStorage?.setItem(TASK_REGISTRY_KEY, JSON.stringify({ version: 5, tasks }));
      registryStored = true;
    } catch (error) {}
    if (registryStored) {
      const retainedKeys = new Set(retainedRecords.map(task => task.key));
      const retainedSelected = retainedKeys.has(state.selectedTaskKey) ? selectedTask() : null;
      writeStorage(ACTIVE_TASK_KEY, retainedSelected?.key || '');
      writeStorage(ACTIVE_RUN_KEY, retainedSelected?.runId || '');
    }
    if (prunedCount) scheduleTaskNavigationRender();
  }

  function scheduleTaskRegistryPersist() {
    window.clearTimeout(state.persistTimer);
    state.persistTimer = window.setTimeout(persistTaskRegistry, 180);
  }

  function saveSelectedTaskDraft() {
    const task = selectedTask();
    if (!task || task.runId || state.switchingTask) return;
    syncImageReferencesFromEditor();
    task.draft = {
      goal: goalText(),
      references: compactImageReferences(state.imageReferences),
      scope: els.deskAgentScope?.value === 'canvas' ? 'canvas' : 'selection',
      autoGenerate: els.deskAgentAutoGenerate?.checked !== false
    };
    task.updatedAt = Date.now() / 1000;
    scheduleTaskRegistryPersist();
  }

  function renderTaskDrawerList() {
    if (!els.deskAgentTaskList || !state.taskDrawerOpen) return;
    const focus = taskFocusDescriptor(els.deskAgentTaskList);
    const tasks = filteredDrawerTasks();
    els.deskAgentTaskList.innerHTML = tasks.map(task => {
      const selected = task.key === state.selectedTaskKey;
      const identity = taskIdentity(task);
      const summary = taskSummary(task);
      const archiveAllowed = canArchiveTask(task);
      const deleteAllowed = canDeleteTask(task);
      const systemIdentity = taskSystemIdentity(task);
      return `
        <article class="desk-agent-task-list-row${selected ? ' is-selected' : ''}${task.archived ? ' is-archived' : ''}" data-task-tone="${escapeHtml(taskTone(task))}" role="listitem">
          <button type="button" class="desk-agent-task-list-main desk-agent-task-secondary" data-agent-task-select="${escapeHtml(task.key)}" aria-label="${escapeHtml(`${identity}，${summary}`)}"${selected ? ' aria-current="true"' : ''}${task.archived ? ' disabled aria-disabled="true" title="先恢复归档后再打开"' : (task.shelved ? ' title="打开并放回顶部任务轨"' : '')}>
            <i class="desk-agent-task-list-dot" aria-hidden="true"></i>
            <span class="desk-agent-task-list-copy">
              <strong>${escapeHtml(identity)} <em>${escapeHtml(summary)}</em></strong>
              <span>${escapeHtml(taskGoalPreview(task))}</span>
              <small title="${escapeHtml(systemIdentity)}">${escapeHtml(taskUpdatedLabel(task))}${task.archived ? ' · 已归档' : (task.shelved ? ' · 已收纳' : '')}</small>
            </span>
          </button>
          <span class="desk-agent-task-list-actions">
            <button type="button" class="desk-agent-task-row-action desk-agent-task-secondary${task.pinned ? ' is-active' : ''}" data-agent-task-action="pin" data-agent-task-key="${escapeHtml(task.key)}" aria-label="${task.pinned ? '取消置顶' : '置顶'} ${escapeHtml(identity)}" title="${task.pinned ? '取消置顶' : '置顶'}" aria-pressed="${String(task.pinned === true)}"${task.archived ? ' disabled' : ''}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h10M8 3l1 8-3 3h12l-3-3 1-8M12 14v7"></path></svg>
            </button>
            <button type="button" class="desk-agent-task-row-action desk-agent-task-secondary" data-agent-task-action="archive" data-agent-task-key="${escapeHtml(task.key)}" aria-label="${task.archived ? '恢复归档' : '归档'} ${escapeHtml(identity)}" title="${archiveAllowed ? (task.archived ? '恢复归档：重新启用任务' : '归档：移出常规任务，数据不会删除') : '执行中的任务不能归档'}"${archiveAllowed ? '' : ' disabled'}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16v13H4zM3 3h18v4H3zM9 12h6"></path></svg>
            </button>
            <button type="button" class="desk-agent-task-row-action is-danger desk-agent-task-secondary" data-agent-task-action="delete" data-agent-task-key="${escapeHtml(task.key)}" aria-label="删除任务 ${escapeHtml(identity)}" title="${deleteAllowed ? '删除任务' : escapeHtml(taskDeleteBlockedReason(task))}"${deleteAllowed ? '' : ' disabled'}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 3h6l1 4H8l1-4ZM7 7l1 14h8l1-14M10 11v6M14 11v6"></path></svg>
            </button>
          </span>
        </article>
      `;
    }).join('');
    if (els.deskAgentTaskEmpty) els.deskAgentTaskEmpty.hidden = tasks.length > 0;
    if (focus) {
      const target = findTaskControl(els.deskAgentTaskList, focus)
        || els.deskAgentTaskFilters?.querySelector('[data-agent-task-filter].is-active')
        || els.deskAgentTaskSearch;
      target?.focus?.({ preventScroll: true });
    }
  }

  function renderTaskDrawer() {
    const counts = taskFilterCounts();
    const total = counts.all || 0;
    if (els.deskAgentTaskAllCount) els.deskAgentTaskAllCount.textContent = String(total);
    if (els.deskAgentTaskDrawerTotal) els.deskAgentTaskDrawerTotal.textContent = `${total} 个`;
    if (els.deskAgentTaskSearch && els.deskAgentTaskSearch.value !== state.taskSearch) {
      els.deskAgentTaskSearch.value = state.taskSearch;
    }
    els.deskAgentTaskFilters?.querySelectorAll('[data-agent-task-filter]').forEach(button => {
      const filter = String(button.dataset.agentTaskFilter || 'all');
      button.classList.toggle('is-active', filter === state.taskFilter);
      button.setAttribute('aria-pressed', String(filter === state.taskFilter));
      const count = button.querySelector('em');
      if (count) count.textContent = String(counts[filter] || 0);
    });
    renderTaskDrawerList();
  }

  function updateTaskRailNavigation() {
    const track = els.deskAgentTaskTrack;
    if (!track) return;
    const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
    if (els.deskAgentTaskPrev) els.deskAgentTaskPrev.disabled = track.scrollLeft <= 2;
    if (els.deskAgentTaskNext) els.deskAgentTaskNext.disabled = track.scrollLeft >= maxScroll - 2;
  }

  function renderTaskRail() {
    closeTaskCardMenu({ restoreFocus: false });
    if (state.taskNavigationRenderFrame) {
      window.cancelAnimationFrame(state.taskNavigationRenderFrame);
      state.taskNavigationRenderFrame = 0;
    }
    if (!els.deskAgentTaskTrack) return;
    const focus = taskFocusDescriptor(els.deskAgentTaskTrack);
    const tasks = railTasks();
    els.deskAgentTaskTrack.innerHTML = tasks.map(task => {
      const selected = task.key === state.selectedTaskKey;
      const identity = taskIdentity(task);
      const summary = taskSummary(task);
      return `
        <span class="desk-agent-task-card-slot${selected ? ' is-selected' : ''}" role="presentation">
          <button type="button" id="deskAgentTaskTab${escapeHtml(task.ordinal)}" class="desk-agent-task-card${selected ? ' is-selected' : ''}" data-agent-task-key="${escapeHtml(task.key)}" data-task-tone="${escapeHtml(taskTone(task))}" role="tab" aria-controls="deskAgentWorkbench" aria-selected="${String(selected)}" tabindex="${selected ? '0' : '-1'}" aria-label="${escapeHtml(`${identity}，${summary}`)}">
            <i class="desk-agent-task-card__dot" aria-hidden="true"></i>
            <span class="desk-agent-task-card__copy">
              <strong>${escapeHtml(identity)}</strong>
              <em>${escapeHtml(summary)}</em>
            </span>
          </button>
          <button type="button" class="desk-agent-task-card__menu-toggle desk-agent-task-secondary" data-agent-task-menu="${escapeHtml(task.key)}" aria-label="打开 ${escapeHtml(identity)} 的任务操作" title="任务操作" aria-haspopup="menu" aria-expanded="false">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6.25 8 10l4-3.75"></path></svg>
          </button>
        </span>
      `;
    }).join('');
    const selectedCard = findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key: state.selectedTaskKey });
    if (selectedCard?.id) els.deskAgentWorkbench?.setAttribute('aria-labelledby', selectedCard.id);
    if (focus) {
      const target = findTaskControl(els.deskAgentTaskTrack, focus)
        || findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key: state.selectedTaskKey });
      target?.focus?.({ preventScroll: true });
    }
    if (els.deskAgentNewTask) {
      const activeCount = allTaskRecords().filter(task => (
        !task.archived && (!task.runId || !TERMINAL_STATUSES.has(String(task.run?.status || 'draft')))
      )).length;
      els.deskAgentNewTask.disabled = state.draftCreationLocked
        || state.creating
        || state.controlling
        || state.revising
        || activeCount >= MAX_ACTIVE_TASKS;
    }
    renderTaskDrawer();
    window.requestAnimationFrame(updateTaskRailNavigation);
  }

  function scheduleTaskNavigationRender() {
    if (state.taskNavigationRenderFrame) return;
    state.taskNavigationRenderFrame = window.requestAnimationFrame(() => {
      state.taskNavigationRenderFrame = 0;
      renderTaskRail();
    });
  }

  function scrollSelectedTaskIntoView() {
    window.requestAnimationFrame(() => {
      els.deskAgentTaskTrack?.querySelector('.desk-agent-task-card.is-selected')?.scrollIntoView?.({
        block: 'nearest',
        inline: 'nearest'
      });
      updateTaskRailNavigation();
    });
  }

  function setTaskDrawerOpen(open, options = {}) {
    closeTaskCardMenu({ restoreFocus: false });
    const next = open === true;
    const drawerHadFocus = !!els.deskAgentTaskDrawer?.contains(document.activeElement);
    if (!next && drawerHadFocus) {
      const taskKey = String(options.focusTaskKey || state.selectedTaskKey || '');
      const taskCard = taskKey
        ? findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key: taskKey })
        : null;
      (taskCard || els.deskAgentTaskAll)?.focus?.({ preventScroll: true });
    } else if (!next && options.restoreFocus !== false) {
      els.deskAgentTaskAll?.focus?.({ preventScroll: true });
    }
    state.taskDrawerOpen = next;
    els.deskAgentTaskDrawer?.classList.toggle('is-open', next);
    els.deskAgentTaskDrawer?.setAttribute('aria-hidden', String(!next));
    els.deskAgentTaskDrawerBackdrop?.classList.toggle('is-open', next);
    els.deskAgentTaskAll?.setAttribute('aria-expanded', String(next));
    if (next) {
      renderTaskDrawer();
      window.requestAnimationFrame(() => {
        if (!state.taskDrawerOpen) return;
        if (els.deskAgentTaskDrawer?.getAttribute('aria-hidden') !== 'false') return;
        els.deskAgentTaskSearch?.focus?.();
      });
    }
  }

  function scrollTaskRail(direction) {
    const track = els.deskAgentTaskTrack;
    if (!track) return;
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    track.scrollBy({
      left: Number(direction || 0) * Math.max(160, Math.floor(track.clientWidth * 0.72)),
      behavior: reducedMotion ? 'auto' : 'smooth'
    });
    window.setTimeout(updateTaskRailNavigation, reducedMotion ? 0 : 220);
  }

  function closeTaskCardMenu(options = {}) {
    const key = state.taskCardMenuKey;
    const toggle = key
      ? findTaskControl(els.deskAgentTaskTrack, { kind: 'menu', key })
      : null;
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
    state.taskCardMenuKey = '';
    if (els.deskAgentTaskCardMenu) {
      els.deskAgentTaskCardMenu.hidden = true;
      els.deskAgentTaskCardMenu.classList.remove('is-open');
      els.deskAgentTaskCardMenu.style.removeProperty('left');
      els.deskAgentTaskCardMenu.style.removeProperty('top');
    }
    if (options.restoreFocus === true) toggle?.focus?.({ preventScroll: true });
  }

  function openTaskCardMenu(taskKey, toggle) {
    const task = state.tasks.get(String(taskKey || ''));
    if (!task || !toggle || !els.deskAgentTaskCardMenu) return;
    if (state.taskCardMenuKey === task.key && !els.deskAgentTaskCardMenu.hidden) {
      closeTaskCardMenu({ restoreFocus: true });
      return;
    }
    closeTaskCardMenu({ restoreFocus: false });
    state.taskCardMenuKey = task.key;
    toggle.setAttribute('aria-expanded', 'true');
    els.deskAgentTaskCardMenu.hidden = false;
    els.deskAgentTaskCardMenu.classList.add('is-open');
    els.deskAgentTaskCardMenu.dataset.taskKey = task.key;
    if (els.deskAgentTaskCardShelve) {
      const otherTask = allTaskRecords().some(item => item && !item.archived && item.key !== task.key);
      els.deskAgentTaskCardShelve.disabled = task.key === state.selectedTaskKey && !otherTask;
      els.deskAgentTaskCardShelve.title = otherTask ? '收纳到全部任务' : '至少保留一个顶部任务';
    }
    if (els.deskAgentTaskCardDelete) {
      const allowed = canDeleteTask(task);
      els.deskAgentTaskCardDelete.disabled = !allowed;
      els.deskAgentTaskCardDelete.title = allowed ? '删除任务' : taskDeleteBlockedReason(task);
    }
    const body = els.deskPromptDrawer?.querySelector('.desk-prompt-drawer__body');
    const bodyRect = body?.getBoundingClientRect?.();
    const toggleRect = toggle.getBoundingClientRect();
    if (bodyRect) {
      const menuWidth = els.deskAgentTaskCardMenu.offsetWidth || 168;
      const menuHeight = els.deskAgentTaskCardMenu.offsetHeight || 68;
      const left = Math.max(8, Math.min(
        bodyRect.width - menuWidth - 8,
        toggleRect.right - bodyRect.left - menuWidth
      ));
      const top = Math.max(8, Math.min(
        bodyRect.height - menuHeight - 8,
        toggleRect.bottom - bodyRect.top + 4
      ));
      els.deskAgentTaskCardMenu.style.left = `${Math.round(left)}px`;
      els.deskAgentTaskCardMenu.style.top = `${Math.round(top)}px`;
    }
    window.requestAnimationFrame(() => els.deskAgentTaskCardShelve?.focus?.({ preventScroll: true }));
  }

  function setTaskDialogError(message = '') {
    if (!els.deskAgentTaskDialogError) return;
    const clean = String(message || '').trim();
    els.deskAgentTaskDialogError.textContent = clean;
    els.deskAgentTaskDialogError.hidden = !clean;
  }

  function closeTaskDialog(options = {}) {
    if (!state.taskDialogMode) return;
    const returnFocus = state.taskDialogReturnFocus;
    state.taskDialogMode = '';
    state.taskDialogTaskKey = '';
    state.taskDialogReturnFocus = null;
    state.deletingTask = false;
    els.deskAgentTaskDialog?.classList.remove('is-open');
    if (els.deskAgentTaskDialog) els.deskAgentTaskDialog.hidden = true;
    if (els.deskAgentTaskDialogBackdrop) els.deskAgentTaskDialogBackdrop.hidden = true;
    if (els.deskAgentTaskRail) els.deskAgentTaskRail.inert = false;
    if (els.deskAgentStage) els.deskAgentStage.inert = false;
    setTaskDialogError('');
    if (options.restoreFocus !== false) {
      window.requestAnimationFrame(() => {
        if (returnFocus?.isConnected) returnFocus.focus?.({ preventScroll: true });
        else els.deskAgentNewTask?.focus?.({ preventScroll: true });
      });
    }
  }

  function openTaskDialog(mode, options = {}) {
    const nextMode = mode === 'delete' ? 'delete' : 'create';
    const task = nextMode === 'delete' ? state.tasks.get(String(options.taskKey || '')) : null;
    if (nextMode === 'delete' && !canDeleteTask(task)) {
      window.DesktopResults?.showTransientMessage?.(taskDeleteBlockedReason(task), 'warning');
      return false;
    }
    closeTaskCardMenu({ restoreFocus: false });
    state.taskDialogMode = nextMode;
    state.taskDialogTaskKey = task?.key || '';
    state.taskDialogReturnFocus = options.returnFocus || document.activeElement;
    state.deletingTask = false;
    if (els.deskAgentTaskDialogTitle) {
      els.deskAgentTaskDialogTitle.textContent = nextMode === 'create' ? '新建 Agent 任务' : '删除任务';
    }
    if (els.deskAgentTaskDialogDescription) {
      els.deskAgentTaskDialogDescription.textContent = nextMode === 'create'
        ? '为任务填写一个便于识别的名称。'
        : `确定删除“${taskIdentity(task)}”？目标、执行计划和运行记录将被永久删除，生成结果文件仍会保留。`;
    }
    if (els.deskAgentTaskNameField) els.deskAgentTaskNameField.hidden = nextMode !== 'create';
    if (els.deskAgentTaskNameInput) {
      const namingTask = nextMode === 'create';
      els.deskAgentTaskNameInput.value = '';
      // A hidden required control prevents the delete form from submitting.
      // Keep validation active only while the naming field is visible.
      els.deskAgentTaskNameInput.required = namingTask;
      els.deskAgentTaskNameInput.disabled = !namingTask;
    }
    if (els.deskAgentTaskDialogConfirm) {
      els.deskAgentTaskDialogConfirm.textContent = nextMode === 'create' ? '创建任务' : '删除任务';
      els.deskAgentTaskDialogConfirm.classList.toggle('is-danger', nextMode === 'delete');
      els.deskAgentTaskDialogConfirm.disabled = false;
    }
    setTaskDialogError('');
    if (els.deskAgentTaskDialogBackdrop) els.deskAgentTaskDialogBackdrop.hidden = false;
    if (els.deskAgentTaskDialog) {
      els.deskAgentTaskDialog.hidden = false;
      els.deskAgentTaskDialog.classList.add('is-open');
    }
    if (els.deskAgentTaskRail) els.deskAgentTaskRail.inert = true;
    if (els.deskAgentStage) els.deskAgentStage.inert = true;
    window.requestAnimationFrame(() => {
      if (nextMode === 'create') els.deskAgentTaskNameInput?.focus?.();
      else els.deskAgentTaskDialogConfirm?.focus?.();
    });
    return true;
  }

  async function submitTaskDialog(event) {
    event?.preventDefault?.();
    if (state.taskDialogMode === 'create') {
      const name = normalizeTaskName(els.deskAgentTaskNameInput?.value || '');
      if (!name) {
        setTaskDialogError('请填写任务名称。');
        els.deskAgentTaskNameInput?.focus?.();
        return;
      }
      state.draftCreationLocked = true;
      if (els.deskAgentTaskDialogConfirm) els.deskAgentTaskDialogConfirm.disabled = true;
      try {
        const created = createDraftTask({ name, reuseEmpty: false, select: true });
        if (!created) {
          setTaskDialogError(`最多同时保留 ${MAX_ACTIVE_TASKS} 个活跃任务，请先完成、归档或删除其他任务。`);
          return;
        }
        closeTaskDialog({ restoreFocus: false });
        setTaskDrawerOpen(false, { restoreFocus: false });
        window.requestAnimationFrame(() => {
          findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key: created.key })?.focus?.({ preventScroll: true });
        });
      } finally {
        state.draftCreationLocked = false;
        renderTaskRail();
        if (els.deskAgentTaskDialogConfirm && state.taskDialogMode === 'create') {
          els.deskAgentTaskDialogConfirm.disabled = false;
        }
      }
      return;
    }
    if (state.taskDialogMode !== 'delete' || state.deletingTask) return;
    const taskKey = state.taskDialogTaskKey;
    state.deletingTask = true;
    if (els.deskAgentTaskDialogConfirm) {
      els.deskAgentTaskDialogConfirm.disabled = true;
      els.deskAgentTaskDialogConfirm.textContent = '正在删除…';
    }
    try {
      const deleted = await deleteTask(taskKey);
      if (!deleted) return;
      const needsTask = !selectedTask();
      closeTaskDialog({ restoreFocus: !needsTask });
      if (needsTask) window.requestAnimationFrame(() => openTaskDialog('create', { returnFocus: els.deskAgentNewTask }));
    } catch (error) {
      setTaskDialogError(String(error?.message || error || '删除任务失败'));
    } finally {
      state.deletingTask = false;
      if (els.deskAgentTaskDialogConfirm && state.taskDialogMode === 'delete') {
        els.deskAgentTaskDialogConfirm.disabled = false;
        els.deskAgentTaskDialogConfirm.textContent = '删除任务';
      }
    }
  }

  function toggleTaskPinned(taskKey) {
    const task = state.tasks.get(String(taskKey || ''));
    if (!task || task.archived) return;
    task.pinned = !task.pinned;
    if (task.pinned) task.shelved = false;
    persistTaskRegistry();
    renderTaskRail();
    scrollSelectedTaskIntoView();
  }

  function shelveTask(taskKey) {
    const task = state.tasks.get(String(taskKey || ''));
    if (!task || task.archived || task.shelved) return null;
    if (task.key === state.selectedTaskKey && (state.creating || state.controlling || state.revising)) return null;

    const visibleBefore = railTasks();
    const previousIndex = Math.max(0, visibleBefore.findIndex(item => item.key === task.key));
    let fallback = visibleBefore.find(item => item.key !== task.key)
      || allTaskRecords().find(item => item && !item.archived && item.key !== task.key);
    if (task.key === state.selectedTaskKey && !fallback) {
      window.DesktopResults?.showTransientMessage?.('至少保留一个顶部任务；新建任务后即可收纳当前卡片', 'info');
      return null;
    }

    task.shelved = true;
    task.pinned = false;
    if (task.key === state.selectedTaskKey && fallback) {
      fallback.shelved = false;
      const selected = selectTask(fallback.key, { fetch: true });
      if (selected?.key !== fallback.key) {
        task.shelved = false;
        renderTaskRail();
        return null;
      }
    } else {
      persistTaskRegistry();
      renderTaskRail();
    }

    const visibleAfter = railTasks();
    const focusTask = visibleAfter[Math.min(previousIndex, Math.max(0, visibleAfter.length - 1))] || selectedTask();
    return focusTask?.key || '';
  }

  function toggleTaskArchived(taskKey) {
    const task = state.tasks.get(String(taskKey || ''));
    if (!task || !canArchiveTask(task)) return;
    task.archived = !task.archived;
    if (task.archived) task.pinned = false;
    persistTaskRegistry();
    if (task.archived && task.key === state.selectedTaskKey) {
      const fallback = railTasks().find(item => item.key !== task.key);
      if (fallback) selectTask(fallback.key);
      else createDraftTask({ reuseEmpty: false, select: true });
    } else {
      renderTaskRail();
      scrollSelectedTaskIntoView();
    }
  }

  function clearTaskWorkspace() {
    state.selectedTaskKey = '';
    state.runId = '';
    state.run = null;
    state.events = [];
    state.eventSeq = 0;
    state.actionInFlight = '';
    state.actionReceipts = new Map();
    state.imageReferences = [];
    state.approvalRunId = '';
    state.approvalParamsExpanded = false;
    state.approvalManual = false;
    goalEditor?.setDocument?.('', []);
    if (!goalEditor?.setDocument) goalEditor?.setText?.('');
    if (els.deskAgentScope) els.deskAgentScope.value = 'selection';
    if (els.deskAgentAutoGenerate) els.deskAgentAutoGenerate.checked = true;
  }

  async function deleteTask(taskKey) {
    const task = state.tasks.get(String(taskKey || ''));
    if (!canDeleteTask(task)) throw new Error(taskDeleteBlockedReason(task));
    task.deleting = true;
    window.clearTimeout(task.pollTimer);
    task.pollTimer = 0;
    try {
      if (task.runId) await window.DesktopApi.deleteAgentRun(task.runId);

      const previousOrder = state.taskOrder.slice();
      const previousIndex = Math.max(0, previousOrder.indexOf(task.key));
      task.deleted = true;
      task.actionReceipts?.clear?.();
      if (task.runId) {
        state.snapshots.delete(task.runId);
        await deletePersistedTaskData(task.runId);
      }
      state.tasks.delete(task.key);
      state.taskOrder = state.taskOrder.filter(key => key !== task.key);

      if (task.key === state.selectedTaskKey) {
        const remaining = state.taskOrder
          .map(key => state.tasks.get(key))
          .filter(item => item && !item.archived);
        const fallback = remaining[Math.min(previousIndex, Math.max(0, remaining.length - 1))] || remaining[0] || null;
        if (fallback) {
          fallback.shelved = false;
          state.selectedTaskKey = '';
          selectTask(fallback.key, { fetch: true });
        } else {
          clearTaskWorkspace();
          persistTaskRegistry();
          refreshContextPreview();
          render();
        }
      } else {
        persistTaskRegistry();
        renderTaskRail();
      }
      return true;
    } catch (error) {
      task.deleting = false;
      if (task.runId && !task.polling) scheduleTaskPoll(task);
      throw error;
    }
  }

  function loadTaskIntoWorkspace(task) {
    if (!task) return;
    state.switchingTask = true;
    state.runId = task.runId || '';
    state.run = task.run || null;
    state.events = task.events || [];
    state.eventSeq = Number(task.eventSeq || 0);
    state.actionInFlight = task.actionInFlight || '';
    state.actionReceipts = task.actionReceipts || new Map();
    const references = task.runId ? runImageReferences(task.run || {}) : hydrateImageReferences(task.draft?.references || []);
    state.imageReferences = references;
    const text = task.runId ? String(task.run?.goal || '') : String(task.draft?.goal || '');
    goalEditor?.setDocument?.(text, references);
    if (!goalEditor?.setDocument) goalEditor?.setText?.(text);
    const options = task.run?.request?.options || task.draft || {};
    if (els.deskAgentScope) els.deskAgentScope.value = options.scope === 'canvas' ? 'canvas' : 'selection';
    if (els.deskAgentAutoGenerate) {
      els.deskAgentAutoGenerate.checked = options.autoGenerate ?? (options.auto_generate !== false);
    }
    state.approvalRunId = '';
    state.approvalParamsExpanded = false;
    state.approvalManual = false;
    state.switchingTask = false;
  }

  function selectTask(taskKey, options = {}) {
    const task = state.tasks.get(String(taskKey || ''));
    if (!task) return null;
    if (task.archived && options.allowArchived !== true) return selectedTask();
    if (state.creating || state.controlling || state.revising) return selectedTask();
    if (task.key !== state.selectedTaskKey) saveSelectedTaskDraft();
    closeImageMentionMenu();
    task.shelved = false;
    state.selectedTaskKey = task.key;
    loadTaskIntoWorkspace(task);
    persistTaskRegistry();
    refreshContextPreview();
    render();
    rescheduleTaskPolls({ immediateSelected: options.fetch !== false });
    scrollSelectedTaskIntoView();
    return task;
  }

  function createDraftTask(options = {}) {
    if (state.creating || state.controlling || state.revising) return null;
    saveSelectedTaskDraft();
    if (options.reuseEmpty !== false) {
      const reusable = state.taskOrder.map(key => state.tasks.get(key)).find(task => (
        task && !task.archived && !task.runId && !String(task.draft?.goal || '').trim() && !(task.draft?.references || []).length
      ));
      if (reusable) {
        selectTask(reusable.key, { fetch: false });
        return reusable;
      }
    }
    const activeCount = allTaskRecords().filter(task => (
      !task.archived && (!task.runId || !TERMINAL_STATUSES.has(String(task.run?.status || 'draft')))
    )).length;
    if (activeCount >= MAX_ACTIVE_TASKS) return null;
    const task = ensureTaskRecord({
      clientTaskId: createClientTaskId(),
      name: normalizeTaskName(options.name || ''),
      draft: { goal: '', references: [], scope: 'selection', autoGenerate: true }
    });
    persistTaskRegistry();
    if (options.select !== false) selectTask(task.key, { fetch: false });
    return task;
  }

  function collectElements() {
    [
      'deskPromptDrawer',
      'deskPromptDrawerToggle',
      'deskPromptWorkbenchTitle',
      'deskPromptAssistantMode',
      'deskPromptAgentMode',
      'deskAgentHead',
      'deskAgentTaskRail',
      'deskAgentTaskPrev',
      'deskAgentTaskTrack',
      'deskAgentTaskNext',
      'deskAgentTaskAll',
      'deskAgentTaskAllCount',
      'deskAgentNewTask',
      'deskAgentTaskCardMenu',
      'deskAgentTaskCardShelve',
      'deskAgentTaskCardDelete',
      'deskAgentStage',
      'deskAgentTaskDrawerBackdrop',
      'deskAgentTaskDrawer',
      'deskAgentTaskDrawerClose',
      'deskAgentTaskDrawerTotal',
      'deskAgentTaskSearch',
      'deskAgentTaskFilters',
      'deskAgentTaskList',
      'deskAgentTaskEmpty',
      'deskAgentTaskDialogBackdrop',
      'deskAgentTaskDialog',
      'deskAgentTaskDialogForm',
      'deskAgentTaskDialogClose',
      'deskAgentTaskDialogTitle',
      'deskAgentTaskDialogDescription',
      'deskAgentTaskNameField',
      'deskAgentTaskNameInput',
      'deskAgentTaskDialogError',
      'deskAgentTaskDialogCancel',
      'deskAgentTaskDialogConfirm',
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
        if (state.switchingTask) return;
        syncImageReferencesFromEditor();
        refreshContextPreview();
        saveSelectedTaskDraft();
        renderTaskRail();
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
    const modeSwitch = els.deskPromptAssistantMode?.closest('.desk-prompt-mode-switch');
    if (modeSwitch) modeSwitch.dataset.mode = next;
    document.querySelectorAll('[data-prompt-assistant-view]').forEach(node => {
      node.hidden = isAgent;
    });
    document.querySelectorAll('[data-prompt-agent-view]').forEach(node => {
      node.hidden = !isAgent;
    });
    if (!isAgent && state.taskDrawerOpen) setTaskDrawerOpen(false, { restoreFocus: false });
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
    const task = selectedTask();
    if (!task?.runId) reconcileImageReferences();
    const runCanvas = task?.run?.context?.workflow?.state?.canvas;
    const canvas = runCanvas && typeof runCanvas === 'object' ? runCanvas : canvasSnapshotState();
    const nodes = Object.values(canvas.nodes || {}).filter(Boolean);
    const images = nodes.filter(node => node.type === 'image');
    const selected = task?.runId
      ? (Array.isArray(task.run?.context?.selected_node_ids) ? task.run.context.selected_node_ids : selectedNodeIds(canvas))
      : selectedNodeIds(canvas);
    const textNodes = nodes.filter(node => node.type === 'text');
    const hasVideoContext = selected.some(nodeId => ['video_inference', 'video'].includes(canvas.nodes?.[nodeId]?.type))
      || (canvas.edges || []).some(edge => selected.includes(edge.from) && canvas.nodes?.[edge.to]?.type === 'video_inference');
    if (els.deskAgentContextMeta) {
      const identity = taskIdentity(task);
      els.deskAgentContextMeta.textContent = [identity, `${nodes.length} 节点`, `${selected.length} 已选`].filter(Boolean).join(' · ');
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

  function fingerprintValue(value, path = []) {
    if (typeof value === 'string') {
      if (/^data:/i.test(value) && value.length > 160) {
        return `[data:${value.length}:${value.slice(0, 64)}:${value.slice(-64)}]`;
      }
      return value;
    }
    if (value == null || typeof value !== 'object') return value;
    if (Array.isArray(value)) return value.map((item, index) => fingerprintValue(item, [...path, String(index)]));
    const isCanvasRoot = path.length === 1 && path[0] === 'canvas';
    return Object.keys(value).sort().reduce((output, key) => {
      if (isCanvasRoot && CANVAS_FINGERPRINT_IGNORED_KEYS.has(key)) return output;
      output[key] = fingerprintValue(value[key], [...path, key]);
      return output;
    }, {});
  }

  function workflowFingerprint(snapshot = null) {
    const source = snapshot || window.DesktopCanvas?.exportWorkflowSnapshot?.();
    const semanticState = source?.state && typeof source.state === 'object' ? source.state : source;
    if (!semanticState || typeof semanticState !== 'object') return '';
    const canonical = JSON.stringify(fingerprintValue(semanticState));
    let hash = 2166136261;
    for (let index = 0; index < canonical.length; index += 1) {
      hash ^= canonical.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return `wf-${(hash >>> 0).toString(16).padStart(8, '0')}-${canonical.length.toString(36)}`;
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
          agent_task_id: selectedTask()?.clientTaskId || createClientTaskId(),
          agent_task_name: taskIdentity(),
          agent_task_label: taskLetter(selectedTask()?.ordinal || 1),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || ''
        }
      }
    };
  }

  function openSnapshotDatabase() {
    if (!window.indexedDB) return Promise.reject(new Error('IndexedDB unavailable'));
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open(SNAPSHOT_DB, SNAPSHOT_DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(SNAPSHOT_STORE)) db.createObjectStore(SNAPSHOT_STORE, { keyPath: 'run_id' });
        if (!db.objectStoreNames.contains(ACTION_RECEIPT_STORE)) db.createObjectStore(ACTION_RECEIPT_STORE, { keyPath: 'key' });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('IndexedDB open failed'));
    });
  }

  function actionReceiptKey(runId, actionId) {
    return `${String(runId || '')}:${String(actionId || '')}`;
  }

  async function loadPersistedActionReceipt(runId, actionId) {
    try {
      const db = await openSnapshotDatabase();
      const record = await new Promise((resolve, reject) => {
        const transaction = db.transaction(ACTION_RECEIPT_STORE, 'readonly');
        const request = transaction.objectStore(ACTION_RECEIPT_STORE).get(actionReceiptKey(runId, actionId));
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => reject(request.error || new Error('Action receipt read failed'));
      });
      db.close();
      return record;
    } catch (error) {
      return null;
    }
  }

  async function storePersistedActionReceipt(runId, actionId, record = {}) {
    try {
      const db = await openSnapshotDatabase();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction(ACTION_RECEIPT_STORE, 'readwrite');
        transaction.objectStore(ACTION_RECEIPT_STORE).put({
          key: actionReceiptKey(runId, actionId),
          run_id: String(runId || ''),
          action_id: String(actionId || ''),
          updated_at: Date.now(),
          ...record
        });
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error('Action receipt write failed'));
      });
      db.close();
      return true;
    } catch (error) {
      return false;
    }
  }

  async function deletePersistedActionReceipt(runId, actionId) {
    try {
      const db = await openSnapshotDatabase();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction(ACTION_RECEIPT_STORE, 'readwrite');
        transaction.objectStore(ACTION_RECEIPT_STORE).delete(actionReceiptKey(runId, actionId));
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error('Action receipt delete failed'));
      });
      db.close();
    } catch (error) {}
  }

  async function deletePersistedTaskData(runId) {
    const cleanRunId = String(runId || '').trim();
    if (!cleanRunId) return;
    try {
      const db = await openSnapshotDatabase();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction([SNAPSHOT_STORE, ACTION_RECEIPT_STORE], 'readwrite');
        transaction.objectStore(SNAPSHOT_STORE).delete(cleanRunId);
        const receipts = transaction.objectStore(ACTION_RECEIPT_STORE);
        const cursorRequest = receipts.openCursor();
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result;
          if (!cursor) return;
          if (String(cursor.value?.run_id || '') === cleanRunId) cursor.delete();
          cursor.continue();
        };
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error('Task persistence delete failed'));
      });
      db.close();
    } catch (error) {
      console.warn('[PromptAgent] task persistence cleanup failed:', error);
    }
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

  function mergeTaskEvents(task, events) {
    if (!task) return;
    const incoming = Array.isArray(events) ? events : [];
    if (!incoming.length) return;
    const bySeq = new Map((task.events || []).map(event => [Number(event.seq || 0), event]));
    incoming.forEach(event => {
      const seq = Number(event?.seq || 0);
      if (!seq) return;
      bySeq.set(seq, event);
      task.eventSeq = Math.max(Number(task.eventSeq || 0), seq);
    });
    task.events = [...bySeq.values()]
      .sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0))
      .slice(-300);
  }

  function applyRunPayload(payload, task = null) {
    if (!payload?.run_id) return null;
    const existing = task || findTaskByRunId(payload.run_id);
    const target = existing || ensureTaskRecord({ run: payload, loaded: true });
    const navigationBefore = existing ? taskNavigationSignature(target) : '';
    mergeTaskEvents(target, payload.events);
    target.runId = String(payload.run_id);
    const payloadClientTaskId = explicitTaskClientIdFromRun(payload);
    if (payloadClientTaskId || !target.clientTaskId) {
      target.clientTaskId = payloadClientTaskId || taskClientIdFromRun(payload);
    }
    const payloadTaskName = taskNameFromRun(payload);
    if (payloadTaskName && !target.name) target.name = payloadTaskName;
    target.run = { ...(target.run || {}), ...payload, events: target.events };
    target.loaded = true;
    target.updatedAt = Number(payload.updated_at || target.updatedAt || Date.now() / 1000);
    target.draft = {
      goal: String(payload.goal || target.draft?.goal || ''),
      references: compactImageReferences(runImageReferences(target.run)),
      scope: payload.request?.options?.scope === 'canvas' ? 'canvas' : 'selection',
      autoGenerate: payload.request?.options?.auto_generate !== false
    };
    const navigationChanged = navigationBefore !== taskNavigationSignature(target);

    if (target.key === state.selectedTaskKey) {
      state.runId = target.runId;
      state.run = target.run;
      state.events = target.events;
      state.eventSeq = Number(target.eventSeq || 0);
      state.actionInFlight = target.actionInFlight || '';
      state.actionReceipts = target.actionReceipts;
      const options = payload.request?.options;
      if (options && typeof options === 'object') {
        if (els.deskAgentScope) els.deskAgentScope.value = options.scope === 'canvas' ? 'canvas' : 'selection';
        if (els.deskAgentAutoGenerate) els.deskAgentAutoGenerate.checked = options.auto_generate !== false;
      }
      if (els.deskAgentGoal && document.activeElement !== els.deskAgentGoal && !goalText()) {
        restoreGoalFromRun(payload);
      }
      if (navigationChanged) scheduleTaskNavigationRender();
      renderWorkspace();
    } else if (navigationChanged) {
      scheduleTaskNavigationRender();
    }
    if (navigationChanged) scheduleTaskRegistryPersist();
    return target;
  }

  function isRunActive(run = state.run) {
    return !!run?.run_id && !TERMINAL_STATUSES.has(String(run.status || ''));
  }

  function taskPollDelay(task) {
    const status = String(task?.run?.status || 'idle');
    const selected = task?.key === state.selectedTaskKey;
    const hidden = document.visibilityState === 'hidden';
    if (hidden) {
      return selected && ['running', 'rolling_back'].includes(status)
        ? TASK_POLL_DELAYS.hiddenSelectedRunning
        : TASK_POLL_DELAYS.hiddenBackground;
    }
    if (['running', 'rolling_back'].includes(status)) {
      return selected ? TASK_POLL_DELAYS.selectedRunning : TASK_POLL_DELAYS.backgroundRunning;
    }
    if (status === 'waiting_for_action') {
      return selected ? TASK_POLL_DELAYS.selectedWaiting : TASK_POLL_DELAYS.backgroundWaiting;
    }
    return selected ? TASK_POLL_DELAYS.selectedIdle : TASK_POLL_DELAYS.backgroundIdle;
  }

  function scheduleTaskPoll(task, delay = null) {
    if (!task || task.deleted || state.tasks.get(task.key) !== task) return;
    window.clearTimeout(task.pollTimer);
    if (!task.runId) return;
    if (task.loaded && TERMINAL_STATUSES.has(String(task.run?.status || ''))) return;
    const adaptiveDelay = taskPollDelay(task);
    const requestedDelay = Number(delay);
    const hasRequestedDelay = delay !== null && delay !== undefined && Number.isFinite(requestedDelay);
    let nextDelay = hasRequestedDelay ? Math.max(120, requestedDelay) : adaptiveDelay;
    if (document.visibilityState === 'hidden') nextDelay = Math.max(nextDelay, adaptiveDelay);
    task.pollTimer = window.setTimeout(() => {
      task.pollTimer = 0;
      pollTask(task);
    }, nextDelay);
  }

  function schedulePoll(delay = null) {
    const task = selectedTask();
    if (task) scheduleTaskPoll(task, delay);
  }

  function rescheduleTaskPolls(options = {}) {
    allTaskRecords().filter(task => (
      task?.runId && (!task.loaded || isRunActive(task.run))
    )).forEach(task => {
      if (task.polling) return;
      const immediate = options.immediateSelected === true && task.key === state.selectedTaskKey;
      scheduleTaskPoll(task, immediate ? 0 : null);
    });
  }

  async function pollTask(task) {
    if (!task?.runId || task.polling || task.deleted || state.tasks.get(task.key) !== task) return;
    task.polling = true;
    let nextDelay = null;
    try {
      const run = await window.DesktopApi.getAgentRun(task.runId, {
        eventsSince: Number(task.eventSeq || 0),
        eventLimit: 300
      });
      if (task.deleted || state.tasks.get(task.key) !== task) return;
      applyRunPayload(run, task);
      nextDelay = await processWaitingAction(task);
    } catch (error) {
      console.warn(`[PromptAgent] poll failed (${task.runId}):`, error);
    } finally {
      task.polling = false;
      const status = String(task.run?.status || '');
      if (!task.deleted && state.tasks.get(task.key) === task && !TERMINAL_STATUSES.has(status)) {
        scheduleTaskPoll(task, nextDelay);
      }
    }
  }

  async function pollRun() {
    const task = selectedTask();
    if (task) await pollTask(task);
  }

  function actionEventFor(actionId, task = selectedTask()) {
    return (task?.events || []).slice().reverse().find(event => (
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

  async function executeRollback(action, fallbackRunId = '', task = null) {
    const runId = String(action.run_id || action.snapshot_key || fallbackRunId || state.runId || '');
    const currentFingerprint = workflowFingerprint();
    if (!task?.canvasFingerprint || task.canvasDiverged || currentFingerprint !== task.canvasFingerprint) {
      if (task) task.canvasDiverged = true;
      scheduleTaskRegistryPersist();
      throw new Error('画布已被其他任务或手动操作修改，为避免覆盖后续内容，本次整画布回滚已阻止');
    }
    const snapshot = await loadCanvasSnapshot(runId);
    if (!snapshot) throw new Error('本轮执行前的画布快照不存在');
    const restored = window.DesktopCanvas?.applyWorkflowSnapshot?.(snapshot, { confirm: false });
    if (!restored) throw new Error('画布快照恢复失败');
    task.canvasDiverged = false;
    return { restored: true, snapshot_key: runId };
  }

  async function executeClientAction(action, options = {}) {
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
        return executeRollback(action, options.runId, options.task);
      default:
        throw new Error(`不支持的 Agent 画布动作：${action?.type || 'unknown'}`);
    }
  }

  function executeScheduledClientAction(action, task) {
    const actionType = String(action?.type || '');
    if (!CANVAS_MUTATION_ACTIONS.has(actionType)) {
      task.actionPhase = 'remote';
      renderTaskRail();
      return executeClientAction(action, { runId: task.runId });
    }

    const ownerKey = `${task.runId}:${action?.action_id || ''}`;
    const queued = state.canvasMutationTail.catch(() => undefined).then(async () => {
      state.canvasMutationOwner = ownerKey;
      task.actionPhase = 'canvas';
      const beforeFingerprint = workflowFingerprint();
      if (!task.canvasFingerprint || beforeFingerprint !== task.canvasFingerprint) task.canvasDiverged = true;
      renderTaskRail();
      if (task.key === state.selectedTaskKey) renderControls();
      try {
        return await executeClientAction(action, { runId: task.runId, task });
      } finally {
        task.canvasFingerprint = workflowFingerprint();
        scheduleTaskRegistryPersist();
        if (state.canvasMutationOwner === ownerKey) state.canvasMutationOwner = '';
        task.actionPhase = '';
        renderTaskRail();
        if (task.key === state.selectedTaskKey) renderControls();
      }
    });
    state.canvasMutationTail = queued.then(() => undefined, () => undefined);
    return queued;
  }

  async function processWaitingAction(task = selectedTask()) {
    const run = task?.run;
    const actionId = String(run?.waiting_action_id || '');
    if (!actionId || run?.status !== 'waiting_for_action' || task.actionInFlight === actionId) return null;
    const event = actionEventFor(actionId, task);
    const action = event?.payload?.action;
    if (!action) return null;
    task.actionInFlight = actionId;
    if (task.key === state.selectedTaskKey) {
      state.actionInFlight = actionId;
      render();
    } else {
      renderTaskRail();
    }
    try {
      let receipt = task.actionReceipts.get(actionId);
      if (!receipt) {
        const persisted = await loadPersistedActionReceipt(task.runId, actionId);
        if (persisted?.state === 'ready' && persisted.receipt) {
          receipt = persisted.receipt;
        } else if (persisted?.state === 'executing') {
          receipt = {
            ok: false,
            error: '上次画布动作在页面中断时状态不确定，已停止自动重试以避免重复提交生成任务',
            result: { interrupted: true, duplicate_prevented: true }
          };
          await storePersistedActionReceipt(task.runId, actionId, { state: 'ready', receipt });
        } else {
          await storePersistedActionReceipt(task.runId, actionId, {
            state: 'executing',
            action_type: String(action.type || '')
          });
          try {
            const result = await executeScheduledClientAction(action, task);
            receipt = { ok: true, result };
          } catch (error) {
            receipt = { ok: false, error: error?.message || String(error || '桌面动作执行失败'), result: {} };
          }
          await storePersistedActionReceipt(task.runId, actionId, { state: 'ready', receipt });
        }
        task.actionReceipts.set(actionId, receipt);
      }
      const response = await window.DesktopApi.submitAgentAction(task.runId, actionId, receipt);
      task.actionReceipts.delete(actionId);
      await deletePersistedActionReceipt(task.runId, actionId);
      applyRunPayload(response, task);
      if (receipt.ok === false) {
        window.DesktopResults?.showTransientMessage?.(`Agent 动作失败：${receipt.error}`, 'error');
      }
      return 120;
    } catch (error) {
      console.warn('[PromptAgent] action receipt failed:', error);
      return 500;
    } finally {
      task.actionInFlight = '';
      task.actionPhase = '';
      if (task.key === state.selectedTaskKey) {
        state.actionInFlight = '';
        render();
      } else {
        renderTaskRail();
      }
    }
  }

  async function createPlan() {
    const task = selectedTask();
    if (state.creating || !task || task.runId) return;
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
    saveSelectedTaskDraft();
    state.creating = true;
    task.events = [];
    task.eventSeq = 0;
    task.actionReceipts.clear();
    state.events = task.events;
    state.eventSeq = task.eventSeq;
    render();
    try {
      const request = captureAgentRequest(goal);
      const snapshotFingerprint = workflowFingerprint(request.snapshot);
      task.canvasFingerprint = snapshotFingerprint;
      task.canvasDiverged = false;
      const run = await window.DesktopApi.createAgentRun(request.payload);
      task.runId = String(run.run_id || '');
      task.run = run;
      task.loaded = true;
      task.updatedAt = Number(run.updated_at || Date.now() / 1000);
      task.draft = {
        goal,
        references: compactImageReferences(state.imageReferences),
        scope: els.deskAgentScope?.value === 'canvas' ? 'canvas' : 'selection',
        autoGenerate: els.deskAgentAutoGenerate?.checked !== false
      };
      await storeCanvasSnapshot(run.run_id, request.snapshot);
      if (workflowFingerprint() !== snapshotFingerprint) task.canvasDiverged = true;
      applyRunPayload(run, task);
      persistTaskRegistry();
      window.DesktopResults?.showTransientMessage?.('Agent 计划已生成，等待确认。', 'success');
      scheduleTaskPoll(task, 900);
    } catch (error) {
      window.DesktopResults?.showError?.(error);
    } finally {
      state.creating = false;
      render();
    }
  }

  async function controlRun(action, payload = {}) {
    const task = selectedTask();
    if (!task?.runId || state.controlling) return;
    if (action === 'rollback') {
      const currentFingerprint = workflowFingerprint();
      if (!task.canvasFingerprint || task.canvasDiverged || currentFingerprint !== task.canvasFingerprint) {
        task.canvasDiverged = true;
        persistTaskRegistry();
        render();
        window.DesktopResults?.showTransientMessage?.(
          '画布已有其他任务或手动修改，已阻止旧任务覆盖整张画布。',
          'warning'
        );
        return;
      }
    }
    state.controlling = true;
    render();
    try {
      const run = await window.DesktopApi.controlAgentRun(task.runId, action, payload);
      applyRunPayload(run, task);
      scheduleTaskPoll(task, 120);
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
    const task = selectedTask();
    if (state.revising || !task?.runId || task.run?.capabilities?.can_revise !== true) return;
    const instruction = String(els.deskAgentRevisionInput?.value || '').trim();
    if (!instruction) {
      els.deskAgentRevisionInput?.focus?.();
      return;
    }
    state.revising = true;
    renderApproval();
    try {
      const run = await window.DesktopApi.controlAgentRun(task.runId, 'revise', { instruction });
      state.approvalRunId = '';
      state.approvalParamsExpanded = false;
      state.approvalManual = false;
      applyRunPayload(run, task);
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
    if (els.deskAgentEventMeta) {
      els.deskAgentEventMeta.textContent = [taskIdentity(), `${state.events.length} 条`].filter(Boolean).join(' · ');
    }
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
      const summary = steps.length
        ? `${steps.length} 步${plan.generation_requested ? ` · 含${taskLabel}` : ''}`
        : '尚未创建';
      els.deskAgentPlanMeta.textContent = [taskIdentity(), summary].filter(Boolean).join(' · ');
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
    const task = selectedTask();
    const run = state.run;
    const status = String(run?.status || (task?.runId ? 'idle' : 'draft'));
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
    if (els.deskAgentRollback) {
      els.deskAgentRollback.disabled = state.controlling || task?.canvasDiverged || !run?.capabilities?.can_rollback;
      els.deskAgentRollback.title = task?.canvasDiverged ? '画布已有后续修改，不能整画布回滚' : '回滚 Agent 画布修改';
    }
    if (els.deskAgentCancel) els.deskAgentCancel.disabled = state.controlling || !run?.capabilities?.can_cancel;
    const locked = !task || state.creating || state.controlling || state.revising || !!task.runId;
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

  function renderWorkspace() {
    renderControls();
    renderSteps();
    renderApproval();
    renderEvents();
    renderArtifact();
  }

  function render() {
    renderTaskRail();
    renderWorkspace();
  }

  function restoreTaskRegistryFromStorage() {
    const stored = readJsonStorage(TASK_REGISTRY_KEY, {});
    const records = Array.isArray(stored?.tasks) ? stored.tasks.slice(-MAX_TASK_HISTORY) : [];
    records.forEach(record => {
      if (!record || typeof record !== 'object') return;
      ensureTaskRecord({
        key: String(record.key || ''),
        clientTaskId: String(record.client_task_id || ''),
        name: normalizeTaskName(record.name || ''),
        ordinal: Number(record.ordinal || 0),
        runId: String(record.run_id || ''),
        canvasFingerprint: String(record.canvas_fingerprint || ''),
        canvasDiverged: record.canvas_diverged === true,
        pinned: record.pinned === true,
        archived: record.archived === true,
        shelved: record.shelved === true,
        createdAt: Number(record.created_at || 0),
        updatedAt: Number(record.updated_at || 0),
        draft: record.draft || {}
      });
    });

    const preferredKey = readStorage(ACTIVE_TASK_KEY, '');
    const legacyRunId = readStorage(ACTIVE_RUN_KEY, '');
    const preferred = state.tasks.get(preferredKey) || findTaskByRunId(legacyRunId);
    if (preferred && !preferred.archived) {
      state.selectedTaskKey = preferred.key;
    } else {
      state.selectedTaskKey = allTaskRecords().find(task => !task.archived)?.key || '';
    }
  }

  async function settleWithConcurrency(items, limit, worker) {
    const queue = Array.isArray(items) ? items : [];
    const results = new Array(queue.length);
    let cursor = 0;
    const runWorker = async () => {
      while (cursor < queue.length) {
        const index = cursor;
        cursor += 1;
        try {
          results[index] = { status: 'fulfilled', value: await worker(queue[index], index) };
        } catch (error) {
          results[index] = { status: 'rejected', reason: error };
        }
      }
    };
    const workerCount = Math.min(queue.length, Math.max(1, Number(limit || 1)));
    await Promise.all(Array.from({ length: workerCount }, runWorker));
    return results;
  }

  async function resumeHydratedTask(task) {
    if (!task?.runId || task.polling || task.deleted || state.tasks.get(task.key) !== task) return;
    task.polling = true;
    let nextDelay = null;
    try {
      nextDelay = await processWaitingAction(task);
    } catch (error) {
      console.warn(`[PromptAgent] restored action failed (${task.runId}):`, error);
    } finally {
      task.polling = false;
      if (!task.deleted && state.tasks.get(task.key) === task && !TERMINAL_STATUSES.has(String(task.run?.status || ''))) {
        scheduleTaskPoll(task, nextDelay);
      }
    }
  }

  async function restoreActiveRun() {
    if (state.restoreStarted) return;
    window.clearTimeout(state.restoreRetryTimer);
    state.restoreRetryTimer = 0;
    state.restoreStarted = true;
    state.restoringTasks = true;
    let restored = false;
    try {
      const response = await window.DesktopApi.listAgentRuns({ limit: MAX_TASK_HISTORY });
      state.restoreAttempts = 0;
      const runs = Array.isArray(response?.runs) ? response.runs : [];
      runs.forEach(run => {
        const clientTaskId = explicitTaskClientIdFromRun(run);
        let task = findTaskByRunId(run.run_id)
          || (clientTaskId
            ? state.taskOrder.map(key => state.tasks.get(key)).find(item => item?.clientTaskId === clientTaskId && !item.runId)
            : null);
        if (!task) task = ensureTaskRecord({ run, clientTaskId: clientTaskId || taskClientIdFromRun(run), loaded: false });
        task.runId = String(run.run_id || task.runId || '');
        task.run = { ...(task.run || {}), ...run };
        if (clientTaskId || !task.clientTaskId) task.clientTaskId = clientTaskId || taskClientIdFromRun(run);
        const runTaskName = taskNameFromRun(run);
        if (runTaskName && !task.name) task.name = runTaskName;
        task.updatedAt = Number(run.updated_at || task.updatedAt || Date.now() / 1000);
      });

      let task = state.tasks.get(state.selectedTaskKey);
      if (task?.archived) task = null;
      if (!task) {
        const legacyRunId = readStorage(ACTIVE_RUN_KEY, '');
        const legacyTask = findTaskByRunId(legacyRunId);
        task = (legacyTask && !legacyTask.archived ? legacyTask : null)
          || allTaskRecords().find(item => !item.archived && isRunActive(item?.run))
          || allTaskRecords().find(item => !item.archived)
          || createDraftTask({ select: false });
        state.selectedTaskKey = task.key;
      }

      loadTaskIntoWorkspace(task);
      refreshContextPreview();
      render();
      scrollSelectedTaskIntoView();
      persistTaskRegistry();

      const hydrateTargets = state.taskOrder.map(key => state.tasks.get(key)).filter(item => (
        item?.runId && (item.key === state.selectedTaskKey || isRunActive(item.run))
      )).sort((left, right) => (
        Number(right?.key === state.selectedTaskKey) - Number(left?.key === state.selectedTaskKey)
      ));
      await settleWithConcurrency(hydrateTargets, RESTORE_HYDRATE_CONCURRENCY, async item => {
        if (item.polling) return;
        window.clearTimeout(item.pollTimer);
        item.pollTimer = 0;
        item.polling = true;
        let hydrated = false;
        try {
          const run = await window.DesktopApi.getAgentRun(item.runId, { eventsSince: 0, eventLimit: 300 });
          if (item.deleted || state.tasks.get(item.key) !== item) return;
          applyRunPayload(run, item);
          hydrated = true;
        } finally {
          item.polling = false;
          if (hydrated) {
            void resumeHydratedTask(item);
          } else if (!item.loaded || isRunActive(item.run)) {
            scheduleTaskPoll(item);
          }
        }
      });
      restored = true;
    } catch (error) {
      console.warn('[PromptAgent] task restore failed:', error);
      state.restoreStarted = false;
      state.restoreAttempts += 1;
      state.taskOrder.map(key => state.tasks.get(key)).filter(item => item?.runId).forEach(item => {
        scheduleTaskPoll(item);
      });
      const retryDelay = Math.min(12_000, 900 * (2 ** Math.min(4, state.restoreAttempts - 1)));
      state.restoreRetryTimer = window.setTimeout(restoreActiveRun, retryDelay);
    } finally {
      state.restoringTasks = false;
      if (!selectedTask()) createDraftTask({ select: true });
      render();
      if (restored) state.restoreStarted = true;
    }
  }

  function bindEvents() {
    els.deskPromptAssistantMode?.addEventListener('click', () => setMode('assistant'));
    els.deskPromptAgentMode?.addEventListener('click', () => setMode('agent'));
    els.deskAgentTaskTrack?.addEventListener('click', event => {
      const menuToggle = event.target.closest('[data-agent-task-menu]');
      if (menuToggle) {
        event.preventDefault();
        event.stopPropagation();
        openTaskCardMenu(menuToggle.dataset.agentTaskMenu, menuToggle);
        return;
      }
      const button = event.target.closest('[data-agent-task-key]');
      if (!button) return;
      const selected = selectTask(button.dataset.agentTaskKey);
      const key = selected?.key || state.selectedTaskKey;
      findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key })?.focus?.({ preventScroll: true });
    });
    els.deskAgentTaskTrack?.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      if (!event.target.closest('[role="tab"]')) return;
      const keys = railTasks().map(task => task.key);
      if (!keys.length) return;
      const currentIndex = Math.max(0, keys.indexOf(state.selectedTaskKey));
      let nextIndex = currentIndex;
      if (event.key === 'ArrowLeft') nextIndex = Math.max(0, currentIndex - 1);
      if (event.key === 'ArrowRight') nextIndex = Math.min(keys.length - 1, currentIndex + 1);
      if (event.key === 'Home') nextIndex = 0;
      if (event.key === 'End') nextIndex = keys.length - 1;
      event.preventDefault();
      const selected = selectTask(keys[nextIndex]);
      const key = selected?.key || state.selectedTaskKey;
      findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key })?.focus?.({ preventScroll: true });
    });
    els.deskAgentTaskTrack?.addEventListener('scroll', () => {
      closeTaskCardMenu({ restoreFocus: false });
      updateTaskRailNavigation();
    }, { passive: true });
    els.deskAgentTaskCardMenu?.addEventListener('click', event => {
      const action = event.target.closest('[data-agent-card-menu-action]');
      if (!action || action.disabled) return;
      const taskKey = String(els.deskAgentTaskCardMenu?.dataset.taskKey || state.taskCardMenuKey || '');
      const returnFocus = findTaskControl(els.deskAgentTaskTrack, { kind: 'menu', key: taskKey });
      if (action.dataset.agentCardMenuAction === 'shelve') {
        closeTaskCardMenu({ restoreFocus: false });
        const focusKey = shelveTask(taskKey);
        window.requestAnimationFrame(() => {
          const target = focusKey
            ? findTaskControl(els.deskAgentTaskTrack, { kind: 'card', key: focusKey })
            : els.deskAgentTaskAll;
          target?.focus?.({ preventScroll: true });
        });
      }
      if (action.dataset.agentCardMenuAction === 'delete') {
        openTaskDialog('delete', { taskKey, returnFocus });
      }
    });
    els.deskAgentTaskPrev?.addEventListener('click', () => scrollTaskRail(-1));
    els.deskAgentTaskNext?.addEventListener('click', () => scrollTaskRail(1));
    els.deskAgentTaskAll?.addEventListener('click', () => setTaskDrawerOpen(!state.taskDrawerOpen));
    els.deskAgentTaskDrawerClose?.addEventListener('click', () => setTaskDrawerOpen(false));
    els.deskAgentTaskDrawerBackdrop?.addEventListener('click', () => setTaskDrawerOpen(false));
    els.deskAgentTaskSearch?.addEventListener('input', event => {
      state.taskSearch = String(event.target.value || '');
      renderTaskDrawerList();
    });
    els.deskAgentTaskFilters?.addEventListener('click', event => {
      const button = event.target.closest('[data-agent-task-filter]');
      if (!button) return;
      state.taskFilter = String(button.dataset.agentTaskFilter || 'all');
      renderTaskDrawer();
    });
    els.deskAgentTaskList?.addEventListener('click', event => {
      const action = event.target.closest('[data-agent-task-action]');
      if (action) {
        event.preventDefault();
        event.stopPropagation();
        if (action.dataset.agentTaskAction === 'pin') toggleTaskPinned(action.dataset.agentTaskKey);
        if (action.dataset.agentTaskAction === 'archive') toggleTaskArchived(action.dataset.agentTaskKey);
        if (action.dataset.agentTaskAction === 'delete') {
          openTaskDialog('delete', { taskKey: action.dataset.agentTaskKey, returnFocus: action });
        }
        return;
      }
      const button = event.target.closest('[data-agent-task-select]');
      if (!button) return;
      const requestedKey = String(button.dataset.agentTaskSelect || '');
      const selected = selectTask(requestedKey);
      if (selected?.key === requestedKey) {
        setTaskDrawerOpen(false, { focusTaskKey: requestedKey });
      }
    });
    els.deskAgentNewTask?.addEventListener('click', event => {
      if (state.draftCreationLocked || Number(event.detail || 0) > 1) return;
      openTaskDialog('create', { returnFocus: els.deskAgentNewTask });
    });
    els.deskAgentTaskDialogForm?.addEventListener('submit', submitTaskDialog);
    els.deskAgentTaskNameInput?.addEventListener('input', () => setTaskDialogError(''));
    els.deskAgentTaskDialogClose?.addEventListener('click', () => closeTaskDialog());
    els.deskAgentTaskDialogCancel?.addEventListener('click', () => closeTaskDialog());
    els.deskAgentTaskDialogBackdrop?.addEventListener('click', () => closeTaskDialog());
    els.deskAgentCreatePlan?.addEventListener('click', createPlan);
    els.deskAgentScope?.addEventListener('change', saveSelectedTaskDraft);
    els.deskAgentAutoGenerate?.addEventListener('change', saveSelectedTaskDraft);
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
    window.addEventListener('resize', () => {
      closeTaskCardMenu({ restoreFocus: false });
      updateTaskRailNavigation();
    }, { passive: true });
    document.addEventListener('pointerdown', event => {
      if (state.taskCardMenuKey
        && !els.deskAgentTaskCardMenu?.contains(event.target)
        && !event.target.closest?.('[data-agent-task-menu]')) {
        closeTaskCardMenu({ restoreFocus: false });
      }
      if (state.taskDialogMode) return;
      if (!state.taskDrawerOpen) return;
      if (els.deskAgentTaskDrawer?.contains(event.target)) return;
      if (els.deskAgentTaskAll?.contains(event.target)) return;
      setTaskDrawerOpen(false, { restoreFocus: false });
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && state.taskDialogMode) {
        event.preventDefault();
        closeTaskDialog();
        return;
      }
      if (event.key === 'Escape' && state.taskCardMenuKey) {
        event.preventDefault();
        closeTaskCardMenu({ restoreFocus: true });
        return;
      }
      if (event.key === 'Escape' && state.taskDrawerOpen) {
        event.preventDefault();
        setTaskDrawerOpen(false);
      }
    });
    window.addEventListener('pagehide', () => {
      saveSelectedTaskDraft();
      persistTaskRegistry();
    });
    document.addEventListener('visibilitychange', () => {
      const hidden = document.visibilityState === 'hidden';
      if (hidden) {
        saveSelectedTaskDraft();
        persistTaskRegistry();
      }
      rescheduleTaskPolls({ immediateSelected: !hidden });
    });
  }

  function init() {
    collectElements();
    if (!els.deskPromptDrawer || !els.deskAgentWorkbench) return;
    initGoalEditor();
    restoreTaskRegistryFromStorage();
    if (!allTaskRecords().some(task => !task.archived)) createDraftTask({ select: false, reuseEmpty: false });
    if (!state.selectedTaskKey || !state.tasks.has(state.selectedTaskKey) || selectedTask()?.archived) {
      state.selectedTaskKey = allTaskRecords().find(task => !task.archived)?.key || '';
    }
    loadTaskIntoWorkspace(selectedTask());
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
