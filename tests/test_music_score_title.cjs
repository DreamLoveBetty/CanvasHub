const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ABCJS = require('../frontend/vendor/abcjs/abcjs-basic-6.7.0.min.js');
const root = path.resolve(__dirname, '..');
const load = (ctx, name) => vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts', `${name}.js`), 'utf8'), ctx);
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
const source = 'X:1\nT:原谱标题\nC:Composer\nM:4/4\nL:1/4\nQ:1/4=90\nK:C\nC D E F | G A B c |\n';
const ctx = vm.createContext({ window: {} });
load(ctx, 'desktop-state-icon'); load(ctx, 'desktop-music-model'); load(ctx, 'desktop-music-view');
const model = ctx.window.DesktopMusicModel;

test('score title is node-owned, normalized and round-trips with canvas state', () => {
  const score = model.createState('s', 'music_score', {});
  assert.equal(score.scoreTitle, '');
  score.scoreTitle = '星辰与海';
  assert.equal(model.normalizeState(JSON.parse(JSON.stringify(score))).scoreTitle, '星辰与海');
  assert.equal(model.createState('g', 'music_generate', {}).scoreTitle, undefined);
  assert.equal(model.normalizeScoreTitle(null), '');
  assert.equal(model.normalizeScoreTitle('x'.repeat(150)).length, 120);
});

test('override replaces header title only and clearing uses the exact original source', () => {
  const titled = model.scoreAbc(source, '星辰与海');
  assert.match(titled, /^X:1\nT:星辰与海\nC:Composer/m);
  assert.equal(titled.replace('T:星辰与海', 'T:原谱标题'), source);
  assert.equal(model.scoreAbc(source, '  '), source);
  assert.equal(model.scoreAbc('', '星辰与海'), '');
  assert.equal(model.scoreAbc(' \n', '星辰与海'), ' \n');
});

test('adds missing title, preserves CRLF and music, handles a header without X', () => {
  const untitled = source.replace('T:原谱标题\n', '').replace(/\n/g, '\r\n');
  assert.equal(model.scoreAbc(untitled, '新标题'), untitled.replace('X:1\r\n', 'X:1\r\nT:新标题\r\n'));
  assert.equal(model.scoreAbc('M:4/4\nK:C\nC4|', '新标题'), 'T:新标题\nM:4/4\nK:C\nC4|');
});

test('removes old subtitle/continuations without changing body titles or later tunes', () => {
  const abc = source.replace('T:原谱标题\n', 'T:Original\n+:continued\nT:Subtitle\n')
    + 'T:Second section\nC4|\nX:2\nT:Second tune\nK:G\nG4|\n';
  const result = model.scoreAbc(abc, 'New title');
  assert.equal(result, abc.replace('T:Original\n+:continued\nT:Subtitle\n', 'T:New title\n'));
});

test('title cannot inject ABC fields, and percent signs do not hide the rest of the title', () => {
  const result = model.scoreAbc(source, '100% Moon\nK:G\r\nQ:1/4=200\u2028V:evil');
  assert.equal((result.match(/^K:/gm) || []).length, 1);
  const parsed = ABCJS.parseOnly(result)[0];
  assert.match(parsed.metaText.title, /Moon K:G/);
  assert.equal(parsed.metaText.tempo.bpm, 90);
  assert.equal(parsed.lines[0].staff[0].key.root, 'C');
});

test('real ABC parser retains all notes and tempo after a Unicode title change', () => {
  const before = ABCJS.parseOnly(source)[0];
  const after = ABCJS.parseOnly(model.scoreAbc(source, '星辰与海'))[0];
  assert.equal(after.metaText.title, '星辰与海');
  assert.deepEqual(after.metaText.tempo, before.metaText.tempo);
  // Parser source offsets naturally move with the title; compare musical values.
  const notes = tune => tune.lines.flatMap(l => (l.staff || []).flatMap(s => s.voices.flat()))
    .filter(n => n.el_type === 'note').map(({ duration, pitches }) => ({ duration, pitches }));
  assert.deepEqual(notes(after), notes(before));
});

test('title input is labeled, bounded, escaped and exclusive to score visualization', () => {
  const view = ctx.window.DesktopMusicView.create({ model, escapeHtml, stateIcon:ctx.window.DesktopStateIcon });
  const html = view.nodeHtml({ id: 's', type: 'music_score', scoreTitle: '"><img src=x onerror=alert(1)>' });
  assert.match(html, /<label>标题<input[^>]+data-music-field="scoreTitle"/);
  assert.match(html, /maxlength="120"/);
  assert.match(html, /留空沿用原谱标题/);
  assert.doesNotMatch(html, /<img/);
  for (const type of model.TYPES.filter(t => t !== 'music_score')) {
    assert.doesNotMatch(view.nodeHtml({ id: 'n', type }), /data-music-field="scoreTitle"/);
  }
});

test('responsive renderer owns an inner element, not the score scroll viewport', async () => {
  let renderedTarget, renderedAbc;
  const context = vm.createContext({ window: { ABCJS: { renderAbc: (target, abc) => {
    renderedTarget = target; renderedAbc = abc; target.style.paddingBottom = '200%'; return [];
  } } }, document: { createElement: () => ({ style: {} }) } });
  load(context, 'desktop-music-score');
  const paper = { style: {}, isConnected: true, replaceChildren: child => { paper.child = child; } };
  await context.window.DesktopMusicScore.render(paper, model.scoreAbc(source, '标题'));
  assert.equal(renderedTarget, paper.child);
  assert.notEqual(renderedTarget, paper);
  assert.equal(paper.style.paddingBottom, undefined);
  assert.match(renderedAbc, /T:标题/);
});

function controllerFixture(library = async () => {}) {
  const timers = new Map(); let timer = 0, saved;
  const sandbox = vm.createContext({ window: {}, AbortController, URL, document: { activeElement: null },
    setTimeout: fn => { timers.set(++timer, fn); return timer; }, clearTimeout: id => timers.delete(id) });
  for (const name of ['desktop-state-icon', 'desktop-music-model', 'desktop-music-view', 'desktop-music-workflow', 'desktop-canvas-music']) load(sandbox, name);
  const model = sandbox.window.DesktopMusicModel;
  const canvas = { nodes: { original: { id: 'original', type: 'music_generate', resultAbc: source },
    s: model.createState('s', 'music_score', {}) }, edges: [{ from: 'original', to: 's' }] };
  const fields = Object.fromEntries(['error', 'status', 'inputs', 'staff', 'score-source', 'midi-info', 'score-meta']
    .map(name => [`[data-music-${name}]`, { textContent: '', hidden: false, dataset: {}, innerHTML: '', classList: { toggle() {} } }]));
  const handlers = {}, el = { addEventListener: (name, fn) => { handlers[name] = fn; },
    querySelector: selector => fields[selector] || null, querySelectorAll: () => [] };
  const renders = [], exports = [];
  const controller = sandbox.window.DesktopCanvasMusic.create({ model, api: {}, audio: {},
    workflow: sandbox.window.DesktopMusicWorkflow, view: sandbox.window.DesktopMusicView.create({ model, escapeHtml, stateIcon:sandbox.window.DesktopStateIcon }),
    score: { library, render: async (paper, abc, options) => { paper.abc = abc; renders.push({ abc, options }); },
      exportFile: async (kind, paper, abc) => { exports.push({ kind, abc, rendered: paper.abc }); } },
    getCanvas: () => canvas, getNodeState: id => canvas.nodes[id], getNodeElement: id => id === 's' ? el : null,
    saveState: () => { saved = JSON.parse(JSON.stringify(canvas)); }, escapeHtml });
  controller.reconcile();
  return { canvas, controller, renders, exports, fields, get saved() { return saved; },
    input: (field, value) => handlers.input({ target: { dataset: { musicField: field }, type: 'text', value } }),
    click: name => handlers.click({ target: { closest: () => ({ dataset: { musicAction: name } }) }, stopPropagation() {} }),
    save: () => { for (const [id, fn] of [...timers]) { timers.delete(id); fn(); } } };
}

test('controller previews live title, persists it and exports every format without editing upstream', async () => {
  const h = controllerFixture(); await flush();
  h.input('scoreTitle', '星辰与海'); await flush();
  assert.match(h.renders.at(-1).abc, /T:星辰与海/);
  assert.match(h.fields['[data-music-score-source]'].textContent, /T:星辰与海/);
  h.save(); assert.equal(h.saved.nodes.s.scoreTitle, '星辰与海');
  for (const kind of ['abc', 'midi', 'svg', 'png', 'pdf']) {
    // Immediate export without waiting for the deferred save callback.
    h.input('scoreTitle', `新标题 ${kind}`); h.click(`export-${kind}`); await flush();
    assert.match(h.exports.at(-1).abc, new RegExp(`T:新标题 ${kind}`));
    if (['svg', 'png', 'pdf'].includes(kind)) assert.equal(h.exports.at(-1).rendered, h.exports.at(-1).abc);
  }
  assert.equal(h.canvas.nodes.original.resultAbc, source);
  h.input('scoreTitle', ''); await flush();
  assert.equal(h.renders.at(-1).abc, source);
  h.controller.disposeAll();
});

test('lazy renderer uses the latest title for preview/export and ignores disposed nodes', async () => {
  let resolve; const ready = new Promise(r => { resolve = r; });
  const h = controllerFixture(() => ready);
  h.input('scoreTitle', '旧标题'); h.click('export-svg'); h.input('scoreTitle', '最新标题');
  resolve(); await flush();
  assert.equal(h.exports.length, 1);
  assert.match(h.exports[0].rendered, /T:最新标题/);
  assert.ok(h.renders.every(r => r.abc.includes('T:最新标题')));
  h.controller.disposeAll();
  let unblock; const wait = new Promise(r => { unblock = r; });
  const gone = controllerFixture(() => wait);
  gone.input('scoreTitle', '不可写回'); gone.click('export-svg'); gone.controller.disposeAll();
  unblock(); await flush();
  assert.equal(gone.renders.length, 0); assert.equal(gone.exports.length, 0);
});
