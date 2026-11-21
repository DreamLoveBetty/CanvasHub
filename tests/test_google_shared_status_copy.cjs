// Google web (index.html) shared poller must distinguish delivery outcomes.
// Tests drive the real mapping + pollTaskStatus with fixtures; no real Telegram or generation.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');

function loadShared() {
  const toasts = [];
  const stages = [];
  const histories = [];
  const pendingClears = [];
  const context = vm.createContext({
    console,
    setTimeout() { return 0; },
    clearTimeout() {},
    document: {
      getElementById() { return null; },
      querySelectorAll() { return []; },
      createElement() {
        return { id: '', className: '', textContent: '', style: {}, classList: { toggle() {} }, remove() {} };
      },
      body: { appendChild() {} },
    },
    api: {
      json: async () => context._task,
    },
    setStageStatusText(key, message, tone) { stages.push({ key, message, tone }); },
    setStageState() {},
    setSubmitButtonState() {},
    loadHistory() { histories.push('load'); },
    clearRememberedStageTask() {},
    clearPendingHistoryRecord(taskId) { pendingClears.push(taskId); },
    isTaskInFlight(status) {
      return ['queued', 'preparing', 'processing', 'fallback_running'].includes(String(status || ''));
    },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/provider-google-shared.js'), 'utf8'), context);
  const originalToast = context.showStatusMessage;
  context.showStatusMessage = (message, type) => {
    toasts.push({ message, type });
    return originalToast?.(message, type);
  };
  return { context, toasts, stages, histories, pendingClears };
}

async function pollTerminal(task) {
  const harness = loadShared();
  harness.context._task = { task_id: 'task-1', ...task };
  harness.context.pollTaskStatus('task-1', { dataset: {} }, 'gen');
  await Promise.resolve();
  await Promise.resolve();
  return harness;
}

function delivery(harness, task) {
  const fn = harness.context.describeGoogleSharedTerminalStatus;
  assert.equal(typeof fn, 'function', 'describeGoogleSharedTerminalStatus should be exported for the poller to use');
  return fn(task);
}

test('succeeded stays a normal sent/completed success', async () => {
  const harness = await pollTerminal({ status: 'succeeded' });
  const mapped = delivery(harness, { status: 'succeeded' });
  assert.equal(mapped.toastType, 'success');
  assert.match(mapped.toast, /生成成功/);
  assert.equal(mapped.stageTone, 'success');
  assert.match(mapped.stageText, /进入历史记录|生成完成/);
  assert.doesNotMatch(mapped.toast + mapped.stageText, /发送失败|已生成，未发送|生成失败/);
  assert.equal(harness.stages.at(-1)?.tone, 'success');
  assert.equal(harness.stages.at(-1)?.message, mapped.stageText);
  assert.equal(harness.toasts.at(-1)?.type, 'success');
  assert.equal(harness.toasts.at(-1)?.message, mapped.toast);
  assert.deepEqual(harness.histories, ['load']);
  assert.deepEqual(harness.pendingClears, []);
});

test('succeeded_no_telegram is a normal saved success, not a send failure', async () => {
  const harness = await pollTerminal({ status: 'succeeded_no_telegram' });
  const mapped = delivery(harness, { status: 'succeeded_no_telegram' });
  assert.equal(mapped.toastType, 'success');
  assert.match(mapped.toast, /生成成功/);
  assert.equal(mapped.stageTone, 'success');
  assert.doesNotMatch(mapped.toast, /发送失败|Telegram 失败|已生成，未发送|生成失败/);
  assert.doesNotMatch(mapped.stageText, /发送失败|Telegram 失败|已生成，未发送|生成失败/);
  assert.match(mapped.stageText, /已保存|进入历史记录|生成完成/);
  assert.equal(harness.stages.at(-1)?.tone, 'success');
  assert.equal(harness.stages.at(-1)?.message, mapped.stageText);
  assert.equal(harness.toasts.at(-1)?.type, 'success');
  assert.deepEqual(harness.histories, ['load']);
  assert.deepEqual(harness.pendingClears, []);
});

test('telegram_failed is 已生成，未发送, with the reason in the visible detail, not 生成失败', async () => {
  const reason = 'Telegram 连接超时';
  const harness = await pollTerminal({ status: 'telegram_failed', error: reason });
  const mapped = delivery(harness, { status: 'telegram_failed', error: reason });
  assert.match(mapped.toast, /已生成，未发送/);
  assert.match(mapped.stageText, /已生成，未发送/);
  assert.match(mapped.toast + mapped.stageText, /Telegram 连接超时/);
  assert.doesNotMatch(mapped.toast, /生成失败/);
  assert.doesNotMatch(mapped.stageText, /生成失败，请稍后重试|❌ 生成失败/);
  assert.notEqual(mapped.toastType, 'success');
  assert.notEqual(mapped.stageTone, 'error');
  assert.notEqual(mapped.toastType, 'error');
  assert.equal(harness.stages.at(-1)?.message, mapped.stageText);
  assert.equal(harness.toasts.at(-1)?.type, mapped.toastType);
  assert.equal(harness.toasts.at(-1)?.message, mapped.toast);
  assert.deepEqual(harness.pendingClears, ['task-1']);
  assert.deepEqual(harness.histories, []);
});

test('failed stays a generation error and is not relabeled as 已生成，未发送', async () => {
  const harness = await pollTerminal({ status: 'failed', error: '模型服务不可用' });
  const mapped = delivery(harness, { status: 'failed', error: '模型服务不可用' });
  assert.equal(mapped.toastType, 'error');
  assert.equal(mapped.stageTone, 'error');
  assert.match(mapped.toast, /生成失败/);
  assert.match(mapped.toast, /模型服务不可用/);
  assert.match(mapped.stageText, /模型服务不可用/);
  assert.doesNotMatch(mapped.toast, /已生成，未发送/);
  assert.doesNotMatch(mapped.stageText, /已生成，未发送/);
  assert.equal(harness.stages.at(-1)?.tone, 'error');
  assert.equal(harness.toasts.at(-1)?.type, 'error');
  assert.deepEqual(harness.pendingClears, ['task-1']);
  assert.deepEqual(harness.histories, []);
});

test('stage restore UI uses the same delivery wording, including telegram_failed vs skipped send', () => {
  const context = vm.createContext({
    console,
    window: {},
    document: { getElementById() { return null; }, querySelectorAll() { return []; }, addEventListener() {} },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    api: { json: async () => ({}) },
    setSubmitButtonState() {},
    IN_FLIGHT_TASK_STATUSES: ['queued', 'preparing', 'processing', 'fallback_running'],
    STAGE_TASK_STORAGE_KEYS: { gen: 'genTask', edit: 'editTask', gpt: 'gptTask' },
    STAGE_BUTTON_IDS: { gen: 'btn-gen', edit: 'btn-edit', gpt: 'btn-gpt' },
    SUBMIT_BUTTON_DEFAULTS: {},
    STAGE_TYPE_MAP: { gen: ['google-gen'], edit: ['google-edit'], gpt: ['gpt'] },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/stage-runtime.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/provider-google-shared.js'), 'utf8'), context);
  const ui = context.getStageTaskUi;
  assert.equal(typeof ui, 'function');
  const skipped = ui('gen', { status: 'succeeded_no_telegram' });
  assert.equal(skipped.tone, 'success');
  assert.doesNotMatch(skipped.message, /发送失败|Telegram 失败|已生成，未发送|生成失败/);
  const unsent = ui('gen', { status: 'telegram_failed', error: 'chat_id 无效' });
  assert.match(unsent.message, /已生成，未发送/);
  assert.match(unsent.message, /chat_id 无效/);
  assert.notEqual(unsent.tone, 'error');
  assert.doesNotMatch(unsent.message, /生成失败/);
  const failed = ui('edit', { status: 'failed', error: '编辑失败' });
  assert.equal(failed.tone, 'error');
  assert.match(failed.message, /编辑失败/);
  assert.doesNotMatch(failed.message, /已生成，未发送/);
  const ok = ui('gen', { status: 'succeeded' });
  assert.equal(ok.tone, 'success');
  assert.doesNotMatch(ok.message, /已生成，未发送|发送失败|生成失败/);
});
