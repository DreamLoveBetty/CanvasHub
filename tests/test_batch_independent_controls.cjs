// Batch pause/resume/cancel stay independent of 复制提示词 and 手动发送.
// Cancel-batch and stop-all use window.confirm and do nothing when dismissed.
// Tests use fixtures only; they never send Telegram or cancel production tasks.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

test('generation nodes keep a real copy-prompt button beside send, plus independent batch controls', () => {
  const files = ['frontend/desktop.html', 'frontend/scripts/desktop-canvas-model-nodes.js'];
  for (const rel of files) {
    const source = read(rel);
    assert.match(source, /data-copy-prompt/, `${rel} must include 复制提示词`);
    assert.match(source, /data-send-original/, `${rel} must keep 手动发送`);
    assert.match(source, /data-batch-pause/, `${rel} must include an independent pause/resume control`);
    assert.match(source, /data-batch-cancel/, `${rel} must include an independent cancel-batch control`);
    const copyIdx = source.indexOf('data-copy-prompt');
    const sendIdx = source.indexOf('data-send-original');
    const pauseIdx = source.indexOf('data-batch-pause');
    assert.notEqual(copyIdx, sendIdx);
    assert.notEqual(pauseIdx, sendIdx);
    assert.notEqual(pauseIdx, copyIdx);
  }
  const results = read('frontend/scripts/desktop-results.js');
  assert.doesNotMatch(results, /sendOriginal\.textContent = output\.batchStatus === 'paused' \? '继续批量'/);
  assert.doesNotMatch(results, /copyPrompt\.textContent = '取消批量'/);
});

function button(label) {
  return {
    textContent: label,
    hidden: true,
    disabled: true,
    dataset: {},
  };
}

function loadResults(overrides = {}) {
  const controlBatchCalls = [];
  const cancelAllCalls = [];
  const messages = [];
  let release;
  const blocked = overrides.block ? new Promise(resolve => { release = resolve; }) : null;
  const context = vm.createContext({
    confirm() { return true; },
    setTimeout(fn, delay) { return 0; },
    clearTimeout() {},
    CSS: { escape: value => String(value) },
    console,
    document: {
      getElementById() { return null; },
      addEventListener() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
    },
    navigator: { clipboard: { writeText: async () => {} } },
    DesktopApi: {
      controlBatch: async (batchId, action) => {
        controlBatchCalls.push({ batchId, action });
        if (blocked && action === (overrides.blockAction || 'pause')) await blocked;
        return {
          batch_id: batchId,
          status: action === 'cancel' ? 'completed' : (action === 'pause' ? 'paused' : 'running'),
          control: action,
          counts: { total: 4, succeeded: 1, queued: 2, processing: 1, failed: 0, canceled: 0 },
          tasks: [],
          message: '批量状态已更新。',
        };
      },
      getBatch: async () => ({}),
      retryTask: async () => ({}),
    },
    DesktopState: {
      state: {
        outputs: {
          input: {
            status: 'processing',
            batchId: 'batch-1',
            batchStatus: 'running',
            batchCounts: { total: 4, succeeded: 1, queued: 2, processing: 1, failed: 0, canceled: 0 },
            files: ['a.png'],
            imagePaths: ['a.png'],
            selectedFiles: ['a.png'],
            prompt: 'a cat',
          },
        },
        output: {},
        canvas: { nodes: {} },
        history: [],
        prompt: 'a cat',
      },
      isInFlight: () => true,
      isFailure: () => false,
      isSuccess: () => false,
      getStatusLabel: status => status,
      estimateProgress: () => 0,
      getProviderLabel: provider => provider || '',
      saveSettings() {},
      saveLastTask() {},
    },
    DesktopCanvas: {
      getTaskRegistry: () => ({
        listCancelable: () => overrides.entries || [
          { key: 'generation:task:t1', cancel: async () => {} },
          { key: 'generation:batch:batch-1', cancel: async () => {} },
        ],
        cancelAll: async () => {
          cancelAllCalls.push('cancelAll');
          if (blocked && overrides.blockCancelAll) await blocked;
          return { total: 2, failed: 0, results: [] };
        },
      }),
      getTaskRegistryForTest: true,
    },
    DesktopHistory: { loadHistory: async () => [] },
    DesktopTaskOutputAdapter: { create() { return { listCancelable: () => [] }; } },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/desktop-results.js'), 'utf8'), context);
  context._calls = { controlBatchCalls, cancelAllCalls, messages, release };
  const originalNotify = context.DesktopResults?.showTransientMessage;
  if (context.DesktopResults) {
    // showTransientMessage is already bound internally; capture via DesktopState side channel if needed
  }
  return context;
}

test('batch actions stay on their own buttons; send and copy keep their labels', () => {
  const context = loadResults();
  const sync = context.DesktopResults?.syncExportAndBatchActions;
  assert.equal(typeof sync, 'function', 'syncExportAndBatchActions should be exported');
  const resultEls = {
    sendOriginal: button('手动发送'),
    copyPrompt: button('复制提示词'),
    batchControls: { hidden: true },
    batchPause: button('暂停批量'),
    batchCancel: button('取消批量'),
  };
  sync(resultEls, context.DesktopState.state.outputs.input, { selectedCount: 1, prompt: 'a cat' });
  assert.equal(resultEls.sendOriginal.textContent, '手动发送');
  assert.equal(resultEls.sendOriginal.disabled, false);
  assert.equal(resultEls.sendOriginal.dataset.batchAction, undefined);
  assert.equal(resultEls.copyPrompt.textContent, '复制提示词');
  assert.equal(resultEls.copyPrompt.disabled, false);
  assert.equal(resultEls.copyPrompt.dataset.batchAction, undefined);
  assert.equal(resultEls.batchPause.hidden, false);
  assert.equal(resultEls.batchPause.textContent, '暂停批量');
  assert.equal(resultEls.batchPause.dataset.batchAction, 'pause');
  assert.equal(resultEls.batchCancel.hidden, false);
  resultEls.batchPause.textContent = 'x';
  sync(resultEls, { ...context.DesktopState.state.outputs.input, batchStatus: 'paused' }, { selectedCount: 1, prompt: 'a cat' });
  assert.equal(resultEls.batchPause.textContent, '继续批量');
  assert.equal(resultEls.batchPause.dataset.batchAction, 'resume');
  assert.equal(resultEls.sendOriginal.textContent, '手动发送');
  sync(resultEls, { ...context.DesktopState.state.outputs.input, batchId: '', batchStatus: 'completed' }, { selectedCount: 1, prompt: 'a cat' });
  assert.equal(resultEls.batchPause.hidden, true);
  assert.equal(resultEls.batchCancel.hidden, true);
  assert.equal(resultEls.batchControls.hidden, true);
});

test('dismissing cancel-batch or stop-all confirm does not change tasks; confirm states the scope', async () => {
  const context = loadResults();
  const seen = [];
  const dismissed = await context.DesktopResults.controlBatch('input', 'cancel', { confirm: message => { seen.push(message); return false; } });
  assert.equal(dismissed.skipped, 'dismissed');
  assert.deepEqual(context._calls.controlBatchCalls, []);
  assert.match(seen[0], /4/);
  assert.match(seen[0], /剩余 3/);
  assert.match(seen[0], /已完成 1/);
  assert.match(seen[0], /已生成的结果会保留/);

  const stopSeen = [];
  const stopDismissed = await context.DesktopResults.cancelActiveTasks({ confirm: message => { stopSeen.push(message); return false; } });
  assert.equal(stopDismissed.skipped, 'dismissed');
  assert.deepEqual(context._calls.cancelAllCalls, []);
  assert.match(stopSeen[0], /将影响 4 个任务/);
  assert.match(stopSeen[0], /批量 1 组剩余 3 个/);
  assert.match(stopSeen[0], /已生成的结果会保留/);
});

test('confirmed cancel/stop run once, and a second click while in flight is ignored', async () => {
  const context = loadResults({ block: true, blockAction: 'pause', blockCancelAll: true });
  const first = context.DesktopResults.controlBatch('input', 'pause', { confirm: () => true });
  const second = await context.DesktopResults.controlBatch('input', 'pause', { confirm: () => true });
  assert.equal(second.skipped, 'busy');
  assert.equal(context._calls.controlBatchCalls.length, 1);
  context._calls.release();
  await first;
  assert.equal(context._calls.controlBatchCalls.length, 1);

  const context2 = loadResults({ block: true, blockCancelAll: true });
  const stopFirst = context2.DesktopResults.cancelActiveTasks({ confirm: () => true });
  const stopSecond = await context2.DesktopResults.cancelActiveTasks({ confirm: () => true });
  assert.equal(stopSecond.skipped, 'busy');
  context2._calls.release();
  const stopped = await stopFirst;
  assert.deepEqual(context2._calls.cancelAllCalls, ['cancelAll']);
  assert.equal(stopped.total, 2);
});
