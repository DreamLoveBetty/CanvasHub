// Automatic subtitles frontend: the workbench autosub controller (readiness, confirm, submit, poll,
// apply, cancel), the API adapters, the settings card, and load order / cache keys.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

function load(file, extra = {}) {
  const context = vm.createContext({ window: { localStorage: extra.localStorage }, Promise, setTimeout, clearTimeout,
    JSON, ...extra });
  vm.runInContext(read(`frontend/scripts/${file}`), context);
  return context.window;
}

function fakeRoot() {
  const el = attrs => ({ ...attrs, disabled: false, hidden: false, textContent: '' });
  const span = el({});
  const nodes = {
    '[data-cb-sub="auto"]': el({}),
    '[data-cb-sub-script]': el({ value: 'original' }),
    '[data-cb-auto-status]': el({ querySelector: () => span }),
  };
  return { querySelector: selector => nodes[selector], nodes, span };
}

function setup({ ready = true, jobs, confirmAnswers = [], cues = [] } = {}) {
  const store = new Map();
  const { DesktopVideoComposeAutosub: autosub } = load('desktop-video-compose-autosub.js', {
    localStorage: { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) },
    setTimeout: fn => setImmediate(fn),
  });
  const root = fakeRoot();
  const messages = [], submitted = [], cancelled = [], applied = [], asked = [];
  const queue = [...(jobs || [])];
  const s = { node: { subtitles: { cues } } };
  const api = {
    transcribe: body => { submitted.push(body); return Promise.resolve({ id: 'transcribe_1', status: 'queued' }); },
    job: () => Promise.resolve(queue.length > 1 ? queue.shift() : queue[0]),
    cancel: id => { cancelled.push(id); queue.splice(0, queue.length, { status: 'cancelled' }); return Promise.resolve({}); },
    transcribeResult: job => ({ cues: job.result.cues, speech: job.result.speech }),
  };
  const asr = { status: () => Promise.resolve({ ready, preparation: { status: 'idle' } }) };
  const controller = autosub.create({ root, api, asr, showMessage: message => messages.push(message),
    confirm: message => { asked.push(message); return confirmAnswers.length ? confirmAnswers.shift() : true; },
    current: () => s, request: () => ({ body: { clips: [{ source_url: '/video/a.mp4' }] } }),
    apply: (session, next) => { applied.push(next); session.node.subtitles.cues = next; return true; } });
  return { autosub, controller, root, messages, submitted, cancelled, applied, asked, s, store };
}

const click = action => ({ target: { closest: () => ({ dataset: { cbSub: action } }) } });
async function settle(rounds = 20) { for (let k = 0; k < rounds; k += 1) await new Promise(r => setImmediate(r)); }

test('a finished job applies draft cues and reports how many', async () => {
  const cues = [{ start: 0.2, end: 1, text: '你好' }];
  const t = setup({ jobs: [{ status: 'running', stage: '识别语音并对齐时间', progress_percent: 40 },
    { status: 'succeeded', result: { cues, speech: true } }] });
  t.root.nodes['[data-cb-sub-script]'].value = 'traditional';
  assert.equal(t.controller.click(click('auto')), true);
  await settle();
  assert.deepEqual(JSON.parse(JSON.stringify(t.submitted)), [{ recipe: { clips: [{ source_url: '/video/a.mp4' }] }, script: 'traditional' }]);
  assert.deepEqual(JSON.parse(JSON.stringify(t.applied)), [cues]);
  assert.match(t.messages.at(-1), /已生成 1 条字幕草稿/);
  assert.equal(t.root.nodes['[data-cb-sub="auto"]'].disabled, false);
  assert.equal(t.controller.busy(), false);
});

test('not ready points to the settings center and submits nothing', async () => {
  const t = setup({ ready: false });
  t.controller.click(click('auto'));
  await settle();
  assert.equal(t.submitted.length, 0);
  assert.match(t.messages[0], /设置中心 › 模型工具 › 语音识别/);
});

test('existing cues are only replaced after confirming', async () => {
  const t = setup({ cues: [{ start: 0, end: 1, text: '旧' }], confirmAnswers: [false] });
  t.controller.click(click('auto'));
  await settle();
  assert.match(t.asked[0], /替换现有 1 条字幕/);
  assert.equal(t.submitted.length, 0);
});

test('music only leaves the cues untouched', async () => {
  const t = setup({ jobs: [{ status: 'succeeded', result: { cues: [], speech: false } }] });
  t.controller.click(click('auto'));
  await settle();
  assert.equal(t.applied.length, 0);
  assert.match(t.messages.at(-1), /没有识别到人声/);
});

test('cancel stops the server job and failures surface their error', async () => {
  const t = setup({ jobs: [{ status: 'running', progress_percent: 10 }] });
  t.controller.click(click('auto'));
  await settle(5);
  t.controller.click(click('auto-cancel'));
  await settle(5);
  assert.deepEqual(t.cancelled, ['transcribe_1']);
  await settle();
  assert.equal(t.messages.at(-1), '已取消自动字幕');
  assert.equal(t.controller.busy(), false);
  const failed = setup({ jobs: [{ status: 'failed', error: '语音识别失败：退出码 3' }] });
  failed.controller.click(click('auto'));
  await settle();
  assert.equal(failed.messages.at(-1), '语音识别失败：退出码 3');
});

test('the script choice is remembered per viewer and storage failures are harmless', () => {
  const t = setup();
  t.root.nodes['[data-cb-sub-script]'].value = 'simplified';
  assert.equal(t.controller.change({ target: t.root.nodes['[data-cb-sub-script]'] }), true);
  assert.equal(t.store.get('desk-video-compose-asr-script'), 'simplified');
  const { DesktopVideoComposeAutosub: broken } = load('desktop-video-compose-autosub.js', {
    localStorage: { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } } });
  const root = fakeRoot();
  const controller = broken.create({ root, api: {}, asr: {}, showMessage() {}, current: () => null, request() {}, apply() {} });
  assert.equal(root.nodes['[data-cb-sub-script]'].value, 'original');
  assert.equal(controller.change({ target: root.nodes['[data-cb-sub-script]'] }), true);
});

test('API adapters translate at the boundary', async () => {
  const calls = [];
  const api = { json: (url, options) => { calls.push([url, options?.method || 'GET']);
    return Promise.resolve(url.includes('status') ? { ready: true, engine: 'Qwen3-ASR 1.7B', reasons: [], download_bytes: 7,
      max_seconds: 180, preparation: { status: 'idle' } } : { preparation: { status: 'running' }, already_running: false }); } };
  const { DesktopAsrAPI: asr } = load('desktop-asr-api.js', { api });
  const state = await asr.status();
  assert.equal(state.downloadBytes, 7);
  assert.equal(state.maxSeconds, 180);
  assert.equal((await asr.prepare()).preparation.status, 'running');
  assert.deepEqual(calls, [['/api/asr/status', 'GET'], ['/api/asr/prepare', 'POST']]);
  const edit = read('frontend/scripts/desktop-video-edit-api.js');
  assert.match(edit, /transcribe: body => json\('transcribe', body\)/);
});

test('settings card renders readiness and starts prepare only on click', async () => {
  const { DesktopAsrTools: tools } = load('desktop-asr-tools.js');
  let prepared = 0;
  const api = { status: () => Promise.resolve({ ready: false, engine: 'Qwen3-ASR 1.7B', reasons: ['语音识别环境尚未准备'],
    downloadBytes: 6.5 * 1024 ** 3, maxSeconds: 180, preparation: { status: 'idle' } }),
  prepare: () => { prepared += 1; return Promise.resolve({ preparation: { status: 'running', message: '开始准备' } }); } };
  const card = tools.create({ api, escapeHtml: value => String(value), rerender() {}, notify() {} });
  await card.activate();
  const html = card.render();
  assert.match(html, /data-asr-prepare/);
  assert.match(html, /约 6\.5 GiB/);
  assert.match(html, /语音识别环境尚未准备/);
  assert.equal(prepared, 0);
  assert.equal(card.handleClick({ target: { closest: () => ({}) }, preventDefault() {} }), true);
  await tick();
  assert.equal(prepared, 1);
  card.deactivate();
  clearTimeout(card.state.timer);
});

test('wiring, load order and cache keys', () => {
  const html = read('frontend/desktop.html');
  const order = ['desktop-asr-api.js', 'desktop-asr-tools.js', 'desktop-video-edit-api.js', 'desktop-video-compose-autosub.js',
    'desktop-video-compose-view.js', 'desktop-canvas-video-compose.js', 'desktop-canvas.js', 'desktop-settings.js'];
  const positions = order.map(file => html.indexOf(`scripts/${file}?v=`));
  positions.forEach((at, k) => assert.ok(at > 0, order[k]));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  for (const file of order) assert.ok(hasCacheKey(html, `scripts/${file}`), file);
  const view = read('frontend/scripts/desktop-video-compose-view.js');
  assert.match(view, /data-cb-sub="auto"/);
  assert.match(view, /data-cb-sub-script/);
  const controller = read('frontend/scripts/desktop-canvas-video-compose.js');
  assert.match(controller, /bench\.autosub\.click\(event\) \|\| bench\.panel\.click\(event\)/);
  assert.match(controller, /blocker\(s, snap, \{subtitles: false\}\)/);
  assert.match(read('frontend/scripts/desktop-canvas.js'), /autosubs: window\.DesktopVideoComposeAutosub, asr: window\.DesktopAsrAPI/);
  assert.match(read('frontend/scripts/desktop-settings.js'), /asrTools\?\.handleClick\?\.\(event\)/);
});
