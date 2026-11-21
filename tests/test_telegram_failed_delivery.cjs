// telegram_failed must read as "已生成，未发送" and offer an explicit resend
// that reuses retryTask / archive delivery. It must not submit a new generation
// or send Telegram unless the user clicks 补发. No real Telegram in this test.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');

function loadState() {
  const context = vm.createContext({ window: {}, document: {}, localStorage: { getItem() { return null; }, setItem() {} }, console });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/desktop-state.js'), 'utf8'), context);
  return context.DesktopState;
}

test('telegram_failed is labeled 已生成，未发送, and skipping send is not an error', () => {
  const state = loadState();
  assert.equal(state.getStatusLabel('telegram_failed'), '已生成，未发送');
  assert.equal(state.getStatusLabel('succeeded_no_telegram'), '已保存');
  assert.notEqual(state.getStatusLabel('succeeded_no_telegram'), '已生成，未发送');
  assert.notEqual(state.getStatusLabel('succeeded'), '已生成，未发送');
  assert.equal(state.getStatusLabel('failed'), '失败');
});

test('node badges and generate labels distinguish telegram_failed from a normal unsending success', () => {
  const files = [
    'frontend/scripts/desktop-canvas-moss.js',
    'frontend/scripts/desktop-canvas-krea2.js',
    'frontend/scripts/desktop-canvas-qwen21.js',
    'frontend/scripts/desktop-canvas-cyimg.js',
  ].map(rel => ({ rel, source: fs.readFileSync(path.join(root, rel), 'utf8') }));
  for (const { rel, source } of files) {
    assert.match(source, /已生成，未发送/, `${rel} should show 已生成，未发送 for telegram_failed`);
    assert.doesNotMatch(
      source,
      /telegram_failed:'已归档'|telegram_failed: '已归档'|telegram_failed:'发送失败'/,
      `${rel} must not call telegram_failed a normal archive or 发送失败`
    );
    assert.match(source, /再次生成/, `${rel} should offer an explicit 再次生成, not treat the state as a default rerun`);
    assert.match(source, /补发/, `${rel} should offer 补发`);
  }
});

test('补发 calls retryTask, never submit, and ignores a second click while in flight', async () => {
  const calls = [];
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const retryTask = async taskId => {
    calls.push(['retry', taskId]);
    if (calls.length === 1) await blocked;
    return { ok: true, resent: true, task_id: taskId, message: '已补发到 Telegram，未重新生成。' };
  };
  const submit = async () => { calls.push(['submit']); throw new Error('submit should not run'); };
  const messages = [];
  const resend = loadResendHelper({ retryTask, submit, notify: (text, tone) => messages.push({ text, tone }) });
  const first = resend('task-archive');
  const second = resend('task-archive');
  const busy = await second;
  assert.equal(busy.skipped, 'busy');
  assert.deepEqual(calls, [['retry', 'task-archive']]);
  release();
  const result = await first;
  assert.equal(result.resent, true);
  assert.deepEqual(calls, [['retry', 'task-archive']]);
  assert.equal(messages.some(item => item.text.includes('未重新生成') && item.tone === 'success'), true);
});

test('补发 failure is reported and does not start a new generation', async () => {
  const calls = [];
  const resend = loadResendHelper({
    retryTask: async () => {
      calls.push('retry');
      throw new Error('没有可补发的归档文件');
    },
    submit: async () => { calls.push('submit'); },
    notify: (text, tone) => calls.push(['notify', text, tone]),
  });
  await assert.rejects(() => resend('old-history'), /没有可补发的归档文件/);
  assert.deepEqual(calls, ['retry', ['notify', '没有可补发的归档文件', 'error']]);
});

function loadResendHelper({ retryTask, submit, notify }) {
  const context = vm.createContext({
    window: {},
    console,
    document: { getElementById() { return null; }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } },
    DesktopApi: { retryTask, submitTaskConfig: submit, submitBatchConfig: submit },
    DesktopState: {
      state: { outputs: {}, output: {}, canvas: { nodes: {} }, history: [] },
      isInFlight: () => false,
      isFailure: status => status === 'failed' || status === 'telegram_failed',
      isSuccess: () => false,
      getStatusLabel: status => status,
      saveSettings() {},
    },
    DesktopCanvas: { getTaskRegistry: () => ({ register() { return () => {}; } }) },
    DesktopHistory: { loadHistory: async () => [] },
    DesktopTaskOutputAdapter: { create() { return { listCancelable: () => [] }; } },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/desktop-results.js'), 'utf8'), context);
  const fn = context.DesktopResults?.resendArchivedTelegram;
  if (typeof fn !== 'function') {
    return async function missing() {
      throw new Error('DesktopResults.resendArchivedTelegram is not available');
    };
  }
  return taskId => fn(taskId, { retryTask, notify });
}
