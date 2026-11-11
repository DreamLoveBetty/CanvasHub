// Video compose subtitles (phase 3b) frontend: cue rules, SRT import, request/key pieces, the draft
// caption overlay, and the numbers it shares with backend/video_edit/subtitles.py and contracts.py.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function load(files, extra = {}) {
  const context = vm.createContext({ window: {}, Promise, ...extra });
  for (const file of files) vm.runInContext(read(`frontend/scripts/${file}`), context);
  return context.window;
}

const { DesktopVideoComposeSubtitles: subs, DesktopVideoComposeModel: model } = load(['desktop-video-compose-subtitles.js',
  'desktop-video-compose-model.js']);
const cue = (start, end, text = '字幕') => ({ start, end, text });

test('normalize sorts cues, resolves overlaps, drops short ones and validates the style', () => {
  const sub = subs.normalize({ cues: [cue(3, 4, 'b'), cue(0, 3.5, 'a'), cue(5, 5.1, 'tiny'), cue(-2, 1, 'early')],
    style: { size: 'huge', position: 'top', look: 'box', font: '../x.ttf' } });
  // 'early' starts at 0; 'tiny' is lengthened to the minimum; 'a' gives way to 'early' and is left empty.
  assert.deepEqual(plain(sub.cues), [cue(0, 1, 'early'), cue(3, 4, 'b'), cue(5, 5.3, 'tiny')]);
  assert.deepEqual(plain(sub.style), { size: 'medium', position: 'top', look: 'box', font: '' });
  assert.equal(subs.normalize({ style: { font: '思源宋体.ttc' } }).style.font, '思源宋体.ttc');
  assert.deepEqual(plain(subs.normalize(undefined)), { cues: [], style: plain(subs.DEFAULT_STYLE) });
});

test('add fills the free gap at the playhead and refuses inside a cue', () => {
  const sub = subs.normalize({ cues: [cue(3, 4)] });
  assert.equal(subs.add(sub, 0.52, 10), 0);
  assert.deepEqual(plain(sub.cues[0]), { start: 0.5, end: 2.5, text: '' });
  assert.equal(subs.add(sub, 2.9, 10), 1, 'squeezed before the next cue');
  assert.deepEqual([sub.cues[1].start, sub.cues[1].end], [2.7, 3], 'backs off to keep the minimum length');
  assert.equal(subs.add(sub, 3.5, 10), -1, 'inside an existing cue');
  assert.equal(subs.add(sub, 9.9, 10), 3);
  assert.deepEqual([sub.cues[3].start, sub.cues[3].end], [9.7, 10], 'near the end it backs off to keep the minimum');
});

test('place moves within neighbours, keeps the minimum and snaps to 0.05 s', () => {
  const sub = subs.normalize({ cues: [cue(0, 1), cue(2, 3), cue(5, 6)] });
  assert.deepEqual(plain(subs.place(sub, 1, 'move', 0.4, 1.4, 10)), { start: 1, end: 2 }, 'stops at the previous cue');
  assert.deepEqual(plain(subs.place(sub, 1, 'move', 4.83, 5.83, 10)), { start: 4, end: 5 }, 'stops at the next cue');
  assert.deepEqual(plain(subs.place(sub, 1, 'start', 4.9, 5, 10)), { start: 4.7, end: 5 }, 'start keeps the minimum length');
  assert.deepEqual(plain(subs.place(sub, 1, 'end', 4.7, 4.71, 10)), { start: 4.7, end: 5 });
  assert.deepEqual(plain(subs.place(sub, 2, 'end', 5, 12.33, 10)), { start: 5, end: 10 }, 'last cue ends at the render');
  assert.deepEqual(plain(subs.place(sub, 0, 'start', 0.123, 1, 10)), { start: 0.1, end: 1 });
});

test('SRT and VTT import: BOM, CRLF, tags, optional hours, invalid blocks and overlaps', () => {
  const srt = '﻿1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>你好</i>\r\n世界\r\n\r\n2\r\nbroken --> line\r\ntext\r\n\r\n'
    + '3\r\n00:00:02,000 --> 00:00:04,000\r\n{\\an8}重叠\r\n\r\n4\r\n00:00:05,000 --> 00:00:06,000\r\n   \r\n';
  const parsed = subs.parseSrt(srt);
  assert.deepEqual(plain(parsed.cues), [{ start: 1, end: 2, text: '你好\n世界' }, { start: 2, end: 4, text: '重叠' }]);
  assert.equal(parsed.skipped, 2);
  const vtt = subs.parseSrt('WEBVTT\n\n00:01.5 --> 00:03.250 align:start\nhello\n\n01:00:00.000 --> 01:00:01.000\nlate');
  assert.deepEqual(plain(vtt.cues.map(item => [item.start, item.end, item.text])), [[1.5, 3.25, 'hello'], [3600, 3601, 'late']]);
  assert.equal(subs.parseSrt('nothing here').cues.length, 0);
});

test('request and key pieces are null without cues so earlier results keep their keys', () => {
  const sources = { a: { url: '/video/a.mp4', name: 'a.mp4' } };
  const node = model.normalize({ clips: [{ sourceId: 'a' }] });
  const before = model.settingsKey(node, sources, '');
  assert.equal(before.includes('subtitles'), false);
  assert.equal(model.request(node, sources, null).subtitles, null);
  node.subtitles.style.size = 'large';
  assert.equal(model.settingsKey(node, sources, ''), before, 'style alone changes nothing without cues');
  node.subtitles.cues.push(cue(0, 1, ' 第一句 \r\n'));
  const withCue = model.settingsKey(node, sources, '');
  assert.notEqual(withCue, before);
  assert.deepEqual(plain(model.request(node, sources, null).subtitles),
    { cues: [{ start: 0, end: 1, text: '第一句' }], style: { size: 'large', position: 'bottom', look: 'outline', font: '' } });
  node.subtitles.cues[0].text = '第二句';
  assert.notEqual(model.settingsKey(node, sources, ''), withCue, 'text edits mark the render stale');
});

test('blocker mirrors the backend reasons', () => {
  assert.equal(subs.blocker(subs.normalize({ cues: [cue(0, 1)] }), 5), '');
  assert.match(subs.blocker(subs.normalize({ cues: [cue(0, 1, '  ')] }), 5), /第 1 条字幕没有文字/);
  assert.match(subs.blocker(subs.normalize({ cues: [cue(0, 1), cue(4.8, 6)] }), 5), /第 2 条字幕在成片结束之后/);
});

test('the draft caption shows the cue at the playhead and hides for the burned-in result', async () => {
  const { DesktopVideoComposeSubtitlePanel: Panel } = load(['desktop-video-compose-subtitle-panel.js']);
  let loads = 0;
  const captions = Panel.createCaptions({ subtitles: subs, loadFonts: async () => { loads += 1; return { fonts: [], defaultFile: '' }; } });
  const props = {};
  const el = { hidden: true, textContent: '', dataset: {}, style: { setProperty: (name, value) => { props[name] = value; }, fontFamily: '' } };
  const sub = subs.normalize({ cues: [cue(1, 2, ' 上句 \n 下句 ')], style: { size: 'large', position: 'top', look: 'box' } });
  captions.paint(el, sub, 0.5);
  assert.equal(el.hidden, true);
  captions.paint(el, sub, 1.2);
  assert.deepEqual([el.hidden, el.textContent, el.dataset.look, el.dataset.position], [false, '上句\n下句', 'box', 'top']);
  assert.equal(props['--desk-video-subtitle-ratio'], '0.07');
  captions.paint(el, sub, 2);
  assert.equal(el.hidden, true, 'the end is exclusive, like the render');
  captions.paint(el, sub, 1.2, false);
  assert.equal(el.hidden, true, 'the rendered result already carries the subtitles');
  await captions.fonts();
  await captions.fonts();
  assert.equal(loads, 1, 'the font catalog loads once');
});

test('preview numbers and limits match the backend renderer and contract', () => {
  const backend = read('backend/video_edit/subtitles.py');
  const contracts = read('backend/video_edit/contracts.py');
  const sizes = Object.fromEntries([...backend.match(/SIZES = \{([^}]+)\}/)[1].matchAll(/'(\w+)': ([\d.]+)/g)].map(m => [m[1], Number(m[2])]));
  assert.deepEqual(sizes, plain(subs.RATIOS));
  for (const [name, key] of [['MARGIN', 'margin'], ['WRAP', 'wrap'], ['LINE_HEIGHT', 'lineHeight']]) {
    assert.equal(Number(backend.match(new RegExp(`^${name} = ([\\d.]+)`, 'm'))[1]), subs.LAYOUT[key], name);
  }
  assert.match(backend, /'stroke': max\(2, round\(size \* 0\.08\)\)/);
  for (const [name, value] of [['MAX_CUES', subs.MAX_CUES], ['MAX_CUE_CHARS', subs.MAX_CHARS], ['MIN_CUE_SECONDS', subs.MIN_SECONDS]]) {
    assert.equal(Number(contracts.match(new RegExp(`^${name} = ([\\d.]+)`, 'm'))[1]), value, name);
  }
  const geometry = read('frontend/styles/desktop-video-edit-geometry.css');
  const caption = geometry.match(/\.desk-video-compose__caption \{([^}]+)\}/)[1];
  for (const declaration of ['bottom: 8cqh', 'max-width: 86cqw', 'line-height: 1.3',
    'font-size: calc(min(100cqw, 100cqh) * var(--desk-video-subtitle-ratio, 0.055))']) assert.ok(caption.includes(declaration), declaration);
  assert.match(geometry, /\.desk-video-compose__frame \{[^}]*container-type: size/);
  const paint = read('frontend/styles/desktop-video-edit.css');
  assert.match(paint, /\.desk-video-compose__caption \{[^}]*-webkit-text-stroke: 0\.16em var\(--desk-video-subtitle-stroke\)/);
  assert.match(read('frontend/styles/desktop-tokens.css'), /--desk-video-subtitle-box: rgba\(0, 0, 0, 0\.59\)/, '150/255 like BOX_ALPHA');
});

test('the workbench has the subtitle lane, panel and cue editor and the page wires them', () => {
  const html = read('frontend/desktop.html');
  for (const file of ['scripts/desktop-video-compose-subtitles.js', 'scripts/desktop-video-compose-subtitle-panel.js',
    'styles/desktop-video-edit.css', 'styles/desktop-video-edit-geometry.css', 'styles/desktop-tokens.css']) assert.ok(hasCacheKey(html, file), file);
  const view = read('frontend/scripts/desktop-video-compose-view.js');
  for (const hook of ['data-cb-subtitles', 'data-cb-sub-seg', 'data-cb-sub-font', 'data-cb-sub="import"', 'data-cb-sub-file',
    'data-cb-cue-text', 'data-cb-cue="delete"', 'data-compose-caption']) assert.ok(view.includes(hook), hook);
  const timeline = read('frontend/scripts/desktop-video-compose-timeline.js');
  assert.match(timeline, /<span>画面<\/span><span>字幕<\/span><span>配乐<\/span>/);
  assert.match(timeline, /subsLane\.addEventListener\('dblclick'/);
  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.match(canvas, /subtitles: window\.DesktopVideoComposeSubtitles, subtitlePanels: window\.DesktopVideoComposeSubtitlePanel/);
  // Delete inside a workbench removes the selected cue, never the canvas node under the dialog: both
  // canvas Delete paths (capture-phase and the general keydown) skip aria-modal dialogs.
  assert.match(canvas, /const isInModalDialog = target => Boolean\(target\?\.closest\?\.\('\[aria-modal="true"\]'\)\)/);
  assert.match(canvas, /if \(isEditingSelectedNode\(event\.target\) \|\| isInModalDialog\(event\.target\)\) return;/);
  assert.match(canvas, /&& !editingSelectedNode && !isInModalDialog\(event\.target\)\) \{/);
  assert.match(view, /role="dialog" aria-modal="true"/);
  // A cue that starts after the render ends stays reachable: it is drawn pinned to the lane's end.
  assert.match(timeline, /const shownRange = cue => isLate\(cue\) \?/);
  const api = read('frontend/scripts/desktop-video-edit-api.js');
  assert.match(api, /subtitleFonts: \(\) => json\('subtitle_fonts'\)/);
  assert.match(read('frontend/scripts/desktop-canvas-video-compose-recipe.js'), /if \(recipe\.subtitles\) node\.subtitles = recipe\.subtitles;/);
});
