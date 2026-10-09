const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, 'frontend', 'scripts', name + '.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
const clone = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; };
const traceback = 'Traceback (most recent call last):\n  File "synthetic/lyra/nar.py", line 730\n    mx.eval(first)\nRuntimeError: [METAL] Impacting Interactivity';
function fixture() {
  const elements = new Map(), timers = new Map(), copies = [], feedback = [], nodes = {}, jobs = new Map();
  let timerId = 0, jobId = 0;
  const element = () => ({ textContent: '', innerHTML: '', hidden: true, style: {}, dataset: {}, listeners: {},
    classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, focus() {}, contains: () => false,
    getBoundingClientRect: () => ({ width: 360, top: 800, left: 200, height: 400 }),
    closest: () => ({ classList: { toggle() {} } }), addEventListener(name, cb) { this.listeners[name] = cb; } });
  for (const name of ['Message', 'Tip', 'TipTitle', 'TipSubtitle', 'TipDisplay', 'TipMeta', 'TipRaw', 'TipCopy', 'TipClose']) elements.set('deskStatus' + name, element());
  const c = vm.createContext({ console, AbortController, URL, CSS: { escape: String }, innerWidth: 1200, innerHeight: 900,
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; }, clearTimeout: id => timers.delete(id),
    setInterval: () => ++timerId, clearInterval() {},
    requestAnimationFrame(fn) { const id = ++timerId; timers.set(id, { fn, ms: -1 }); return id; },
    cancelAnimationFrame: id => timers.delete(id), addEventListener() {}, removeEventListener() {},
    document: { getElementById: id => elements.get(id) || null, querySelector: () => null, querySelectorAll: () => [], addEventListener() {} },
    localStorage: { getItem: () => null, setItem() {} }, navigator: { clipboard: { writeText: async text => copies.push(text) } } });
  c.window = c;
  for (const name of ['desktop-tasks', 'desktop-task-output-adapter', 'desktop-state', 'desktop-results', 'desktop-state-icon', 'desktop-music-model', 'desktop-music-view', 'desktop-music-workflow', 'desktop-canvas-music']) vm.runInContext(read(name), c);
  const taskRegistry = c.DesktopTasks.createRegistry({reportStatus: entry => c.DesktopResults.reportTaskStatus(entry)});
  c.DesktopCanvas = {getTaskRegistry: () => taskRegistry};
  c.DesktopResults.init();
  const image = { task_id: 'image-job', status: 'succeeded', progress_text: '图片已保存', type: 'google-gen' };
  c.DesktopResults.applyTask(image, 'input');
  const canvas = { nodes: {}, edges: [] }, model = c.DesktopMusicModel;
  const api = {
    submit: async spec => { const job = { id: (++jobId).toString(16).padStart(32, '0'), status: 'queued', stage: '等待音频引擎', spec, artifacts: [] }; jobs.set(job.id, job); return clone(job); },
    job: async id => clone(jobs.get(id)),
    cancel: async id => { Object.assign(jobs.get(id), { status: 'cancelled', stage: 'cancelled' }); return clone(jobs.get(id)); },
  };
  const controller = c.DesktopCanvasMusic.create({ model, api, workflow: c.DesktopMusicWorkflow,
    view: c.DesktopMusicView.create({ model, stateIcon:c.DesktopStateIcon, escapeHtml: String }), score: {}, audio: {},
    getCanvas: () => canvas, getNodeState: id => canvas.nodes[id], getNodeElement: id => nodes[id],
    materializeText: () => 'synthetic text', saveState() {}, escapeHtml: String,
    reportStatus: entry => { feedback.push(clone(entry)); c.DesktopResults.reportTaskStatus(entry); } });
  function add(id = 'music1', extra = {}) {
    const node = canvas.nodes[id] = Object.assign(model.createState(id, 'music_generate', {}), extra);
    const fields = { '[data-music-status]': element(), '[data-music-inputs]': element() };
    nodes[id] = { addEventListener() {}, querySelectorAll: () => [], querySelector: selector => fields[selector] || null };
    for (const role of ['style', 'lyrics']) { canvas.nodes[id + role] = { id: id + role, type: 'text' }; canvas.edges.push({ from: id + role, to: id, inputRole: role }); }
    controller.reconcile(); return node;
  }
  const expire = ms => { for (const [id, timer] of [...timers]) if (timer.ms === ms) { timers.delete(id); timer.fn(); } };
  return { c, model, controller, add, api, jobs, canvas, feedback, elements, copies,
    click: async name => elements.get('deskStatus' + name).listeners.click({ stopPropagation() {} }),
    poll: async () => { expire(2500); await flush(); }, expire,
    last: () => feedback.at(-1), message: () => elements.get('deskStatusMessage').textContent };
}

test('music reports reach existing details/copy without creating or modifying image outputs', async () => {
  const h = fixture(), before = JSON.stringify(h.c.DesktopState.state.outputs), node = h.add();
  await h.controller.run(node.id); await flush();
  assert.match(h.message(), /音乐生成 · 排队中/);
  const job = h.jobs.get(node.jobId);
  Object.assign(job, { status: 'running', stage: 'Synthesizing audio', progress: { completed: 4, total: 8, unit: 'steps' } });
  await h.poll(); assert.match(h.message(), /声学合成 · 4\/8 步/);
  const count = h.feedback.length; await h.poll(); assert.equal(h.feedback.length, count, 'unchanged polls do not replace newer notices');
  Object.assign(job, { status: 'failed', stage: 'failed', error: traceback }); await h.poll();
  assert.match(h.message(), /音乐生成 · 生成失败/); assert.doesNotMatch(h.message(), /Traceback|nar.py/);
  await h.click('Message');
  assert.match(h.elements.get('deskStatusTipRaw').textContent, /mx.eval\(first\)\nRuntimeError/);
  assert.equal(h.elements.get('deskStatusTip').dataset.extended, 'true');
  assert.match(h.elements.get('deskStatusTipMeta').innerHTML, /本地 mlx-Yue/);
  assert.doesNotMatch(h.elements.get('deskStatusTipMeta').innerHTML, /Google 生成|账号池 API/);
  await h.click('TipCopy'); h.expire(3600);
  assert.match(h.copies[0], /Impacting Interactivity/); assert.match(h.copies[0], new RegExp(job.id));
  assert.match(h.message(), /音乐生成 · 生成失败/);
  assert.equal(JSON.stringify(h.c.DesktopState.state.outputs), before);
  h.controller.disposeAll();
});

test('new validation failure and submission cannot borrow previous job ID/error', async () => {
  const h = fixture(), node = h.add(); await h.controller.run(node.id); await flush();
  Object.assign(h.jobs.get(node.jobId), { status: 'failed', error: traceback }); await h.poll();
  h.canvas.edges = []; await h.controller.run(node.id);
  assert.equal(h.last().task.task_id, ''); assert.match(h.last().task.raw_detail, /音乐风格、歌词/);
  assert.doesNotMatch(h.last().task.raw_detail, /Impacting Interactivity/);
  const count = h.feedback.length; await h.controller.run(node.id); assert.ok(h.feedback.length > count, 'repeated explicit attempts report again');
  h.controller.disposeAll();
});

test('task success waits for publication and publication errors remain only in shared details', async () => {
  const h = fixture(), node = h.add(); await h.controller.run(node.id); await flush();
  const gate = deferred(); h.api.blob = () => gate.promise;
  Object.assign(h.jobs.get(node.jobId), { status: 'succeeded', stage: 'succeeded', artifacts: [{ kind: 'audio', name: 'result/audio.flac', url: '/api/audio/artifact?id=fixture', file_size: 10 }] });
  await h.poll(); assert.match(h.message(), /正在接入生成结果/); assert.notEqual(h.last().tone, 'success');
  gate.resolve({}); await flush(); // No graph addNode in this fixture -> publication failure.
  assert.match(h.message(), /结果接入失败/); assert.equal(h.last().tone, 'error');
  h.controller.disposeAll();
});

test('cancel, partial and interrupted receipts have distinct summaries and details', async () => {
  const h = fixture(), node = h.add(); await h.controller.run(node.id); await flush();
  await h.controller.getCancelableTasks()[0].cancel(); await flush();
  assert.match(h.message(), /已停止/); assert.equal(h.last().task.status, 'canceled');
  for (const [state, tone, message] of [['partial', 'warning', /结果截断/], ['interrupted', 'error', /已中断/], ['succeeded', 'success', /已完成/]]) {
    await h.controller.run(node.id); await flush(); Object.assign(h.jobs.get(node.jobId), { status: state, stage: state });
    await h.poll(); assert.match(h.message(), message); assert.equal(h.last().tone, tone);
  }
  h.controller.disposeAll();
});

test('selected node rebinds details, repeated polls do not steal them, disposed replies do nothing', async () => {
  const h = fixture(), a = h.add('first'), b = h.add('second');
  await h.controller.run(a.id); await h.controller.run(b.id); await flush();
  h.controller.showStatus(a.id); assert.equal(h.last().task.node_id, a.id);
  const count = h.feedback.length; await h.poll(); assert.equal(h.feedback.length, count);
  h.c.DesktopResults.applyTask({ task_id: 'next-image', status: 'failed', error: 'ImageError', progress_text: '图像失败', type: 'gpt' }, 'image2');
  await h.click('Message'); assert.equal(h.elements.get('deskStatusTipRaw').textContent, 'ImageError');
  assert.equal(h.elements.get('deskStatusTip').dataset.extended, 'false');
  h.controller.showStatus(b.id); assert.match(h.elements.get('deskStatusTipSubtitle').textContent, new RegExp(b.jobId));
  const gate = deferred(); h.api.job = () => gate.promise; await h.poll();
  h.controller.disposeAll(); const finalCount = h.feedback.length;
  gate.resolve({ id: b.jobId, status: 'failed', error: 'stale' }); await flush();
  assert.equal(h.feedback.length, finalCount);
});

test('a rejected old poll cannot attach its error to a newly submitted task', async () => {
  const h = fixture(), gate = deferred(), realJob = h.api.job, oldId = 'b'.repeat(32);
  h.api.job = id => id === oldId ? gate.promise : realJob(id);
  const node = h.add('replaced', { jobId: oldId, status: 'failed' });
  await h.controller.run(node.id); await flush();
  const newId = node.jobId; assert.notEqual(newId, oldId);
  gate.reject(Error('OLD_NETWORK_ERROR')); await flush();
  assert.equal(h.last().task.task_id, newId);
  assert.ok(h.feedback.every(f => !f.task.raw_detail.includes('OLD_NETWORK_ERROR')));
  h.controller.disposeAll();
});

test('waiting/plan/transcription status labels remain audio-owned and do not leak request text', () => {
  const h = fixture();
  for (const [type, operation, expected] of [['music_generate', 'generate', '音乐生成'], ['music_generate', 'plan', '乐谱生成'], ['music_transcribe', 'transcribe', '音频转谱']]) {
    const node = h.model.createState('node', type, {}); node.operation = operation; node.jobId = 'old';
    const old = { id: 'old', status: 'failed', error: 'OLD_ERROR', spec: { request: { style: 'PRIVATE_STYLE', lyrics: 'PRIVATE_LYRICS' } } };
    const button = h.model.generationButtonState(node, { submitting: true, phase: '等待上游转谱' });
    const result = h.model.taskFeedback(node, old, button, { pending: true });
    assert.match(result.message, new RegExp(expected)); assert.equal(result.task.task_id, '');
    assert.equal(result.task.status, 'preparing');
    assert.doesNotMatch(JSON.stringify(result), /OLD_ERROR|PRIVATE_STYLE|PRIVATE_LYRICS/);
  }
  h.controller.disposeAll();
});

test('poll read failures recover and open audio details survive ordinary transient notices', async () => {
  const h = fixture(), node = h.add(); await h.controller.run(node.id); await flush();
  const realJob = h.api.job; h.api.job = async () => { throw Error('network unavailable'); }; await h.poll();
  assert.match(h.last().task.raw_detail, /读取任务失败：network unavailable/);
  await h.click('Message'); const raw = h.elements.get('deskStatusTipRaw').textContent;
  h.c.DesktopResults.showTransientMessage('已复制', 'success');
  assert.equal(h.elements.get('deskStatusTipRaw').textContent, raw);
  h.expire(3600); assert.match(h.message(), /操作失败/);
  h.api.job = realJob; await h.poll(); assert.match(h.message(), /排队中/);
  assert.doesNotMatch(h.elements.get('deskStatusTipRaw').textContent, /network unavailable/);
  h.controller.disposeAll();
});

test('restored failed audio receipt reports details after reload without node-local errors', async () => {
  const h = fixture(), id = 'a'.repeat(32);
  h.jobs.set(id, { id, status: 'failed', error: traceback, stage: 'failed', artifacts: [] });
  const node = h.add('restored', { jobId: id, status: 'failed' }); await flush();
  assert.equal(h.last().task.task_id, id); assert.match(h.last().task.raw_detail, /Impacting Interactivity/);
  const view = h.c.DesktopMusicView.create({ model: h.model, stateIcon:h.c.DesktopStateIcon, escapeHtml: String });
  for (const type of ['music_generate', 'music_transcribe']) {
    const html = view.nodeHtml({ ...node, type });
    assert.doesNotMatch(html, /data-music-error|data-music-job-status|data-music-elapsed|generation-feedback/);
    assert.match(html, /data-music-status/); assert.match(html, /data-music-action="run"/);
  }
  h.controller.disposeAll();
});
