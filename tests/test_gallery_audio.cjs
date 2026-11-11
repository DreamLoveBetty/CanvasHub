const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

const ITEMS = [
  { id: 'audio_1', path: '2026-11-09/yue_aaaaaaaaaaaa.flac', name: 'yue_aaaaaaaaaaaa.flac', title: 'Mandarin <pop>',
    url: '/api/assets/audio/file?path=2026-11-09%2Fyue_aaaaaaaaaaaa.flac', mime_type: 'audio/flac', format: 'FLAC',
    file_size: 2 * 1024 * 1024, created_at: 1762650000, duration_seconds: 215.6, sample_rate: 48000, channels: 2,
    job_id: 'a'.repeat(32), style: 'Mandarin <pop>, piano, warm', lyrics: '[Verse]\n第一行 <la>', seed: 7, precision: '8bit', has_score: true,
    peaks: Array.from({ length: 64 }, (_, i) => (i % 8) / 8) },
  { id: 'audio_2', path: 'imported/take.wav', name: 'take.wav', title: 'take', url: '/api/assets/audio/file?path=imported%2Ftake.wav',
    mime_type: 'audio/wav', format: 'WAV', file_size: 1000, created_at: 1762600000, duration_seconds: 0, job_id: '', style: '', lyrics: '' },
];

// Minimal DOM: the view writes innerHTML strings, so a few elements with querySelector suffice.
function element() {
  return {
    innerHTML: '', textContent: '', hidden: false, isConnected: true, listeners: {},
    classList: { names: new Set(), add(n) { this.names.add(n); }, remove(n) { this.names.delete(n); } },
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
  };
}

function load({ confirm = true } = {}) {
  const calls = [];
  const list = element(), status = element(), undo = element(), backfill = element();
  backfill.span = element();
  backfill.querySelector = () => backfill.span;
  const grid = element();
  grid.querySelector = selector => ({ '[data-audio-asset-list]': list, '[data-audio-asset-status]': status,
    '[data-audio-asset-undo]': undo, '[data-audio-asset-backfill]': backfill })[selector] || null;
  list.querySelector = () => null;
  const players = [];
  class Audio {
    constructor() { this.paused = true; this.attrs = {}; this.listeners = {}; this.currentTime = 0; this.duration = NaN; players.push(this); }
    set src(value) { this.attrs.src = value; this.currentTime = 0; }
    getAttribute(name) { return this.attrs[name]; }
    removeAttribute(name) { delete this.attrs[name]; }
    load() {}
    pause() { this.paused = true; }
    play() { this.paused = false; return Promise.resolve(); }
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  }
  const window = { confirm: () => confirm };
  const sandbox = { window, Audio, CSS: { escape: value => value }, setTimeout, clearTimeout, AbortController, URL };
  vm.runInNewContext(read('frontend/scripts/desktop-gallery-audio.js'), sandbox);
  const api = {
    listAudioAssets: async options => { calls.push(['list', options]); return { items: ITEMS, stats: { total: 2, total_duration_seconds: 215.6, total_file_size: 2 * 1024 * 1024 + 1000 } }; },
    getUnarchivedAudio: async () => { calls.push(['unarchived']); return { count: 3, enabled: true }; },
    getAudioAssetBlob: async url => { calls.push(['blob', url]); return { type: 'audio/flac', size: 99 }; },
    deleteAudioAssets: async paths => { calls.push(['delete', paths]); return { ok: true, delete_batch_id: 'batch-1', message: '音频已移入废纸篓' }; },
    undoAssetDelete: async ids => { calls.push(['undo', ids]); return { ok: true, restored_files: 5 }; },
    archiveExistingAudio: async () => { calls.push(['archive']); return { archived: 3, failed: 0 }; },
    getAudioPeaks: async path => { calls.push(['peaks', path]); return { peaks: Array(64).fill(0.5) }; },
  };
  const notes = [];
  const view = window.DesktopGalleryAudio.create({
    api,
    sendToCanvas: async result => calls.push(['canvas', result]),
    closeGallery: () => calls.push(['close']),
    notify: message => notes.push(message),
    showError: error => notes.push('error:' + error.message),
    copyText: async text => calls.push(['copy', text]),
    escapeHtml: value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]),
    formatFileSize: bytes => `${bytes} B`,
    formatTime: () => '11-09 10:20',
  });
  const click = (action, itemPath, extra = {}) => {
    const target = { disabled: false, isConnected: true, textContent: '', classList: { add() {}, remove() {} }, dataset: { audioAssetAction: action, path: itemPath }, ...extra };
    grid.listeners.click[0]({ target: { closest: selector => (selector === '[data-audio-asset-action]' ? target : null) } });
    return target;
  };
  const flush = () => new Promise(resolve => setTimeout(resolve, 0));
  return { view, grid, list, status, undo, backfill, calls, notes, players, click, flush, Gallery: window.DesktopGalleryAudio };
}

test('durations and payloads are translated at the adapter boundary', () => {
  const { Gallery } = load();
  assert.equal(Gallery.formatDuration(215.6), '3:36');
  assert.equal(Gallery.formatDuration(3725), '1:02:05');
  assert.equal(Gallery.formatDuration(0), '');
  const item = Gallery.normalize(ITEMS[0]);
  assert.equal(item.durationSeconds, 215.6);
  assert.equal(item.jobId, 'a'.repeat(32));
  assert.equal(item.hasScore, true);
  assert.equal(Gallery.normalize({ seed: null }).seed, null);
  assert.equal(item.title, '第一行 <la>', 'the first sung line names the song');
  assert.equal(item.subtitle, 'Mandarin <pop> · piano · warm');
  assert.equal(item.peaks.length, 64);
  assert.equal(Gallery.normalize({ peaks: [1, 2] }).peaks, null, 'malformed waveforms are dropped');
  assert.equal(Gallery.songTitle('[Intro]\n\n[Verse] 晚风', '', 'x'), '晚风');
  assert.equal(Gallery.songTitle('', '国语流行，女声', 'x'), '国语流行');
  assert.equal(Gallery.songTitle('', '', 'yue_a'), 'yue_a');
  const cover = Gallery.coverArt('2026-11-09/a.flac');
  assert.equal(cover, Gallery.coverArt('2026-11-09/a.flac'), 'cover art is stable per file');
  assert.notEqual(cover, Gallery.coverArt('2026-11-09/b.flac'));
  const hues = new Set(Array.from({ length: 12 }, (_, i) => Math.floor(Number(Gallery.coverArt(`2026-09-17/yue_${i}.flac`).match(/hsl\((\d+)/)[1]) / 30)));
  assert.ok(hues.size >= 6, 'similar paths still spread across the colour wheel');
});

test('mounting lists archived songs, offers the backfill and escapes user text', async () => {
  const { view, grid, list, status, undo, backfill, calls } = load();
  await view.mount(grid);
  assert.ok(grid.classList.names.has('desk-gallery-audio'));
  assert.deepEqual(calls.map(call => call[0]).filter(name => name !== 'peaks'), ['list', 'unarchived']);
  assert.match(list.innerHTML, /<strong class="desk-gallery-audio__title" title="第一行 &lt;la&gt;">第一行 &lt;la&gt;<\/strong>/);
  assert.match(list.innerHTML, /Mandarin &lt;pop&gt; · piano · warm/);
  assert.doesNotMatch(list.innerHTML, /<pop>|<la>/);
  assert.match(list.innerHTML, /desk-gallery-audio__eyebrow">FLAC · 11-09 10:20</);
  assert.match(list.innerHTML, /<span data-audio-asset-time>0:00<\/span><span>3:36<\/span>/);
  assert.match(list.innerHTML, /aria-label="播放 第一行 &lt;la&gt;" aria-pressed="false"/);
  assert.match(list.innerHTML, /aria-label="后退 10 秒" title="后退 10 秒">/);
  assert.doesNotMatch(list.innerHTML, / disabled>/, 'every transport key is live on every card');
  assert.match(grid.innerHTML, /<label class="desk-gallery-search desk-gallery-audio__search">[\s\S]*<input type="search" data-audio-asset-query/, 'the search field is the gallery\'s own');
  assert.doesNotMatch(grid.innerHTML, /desk-input/);
  assert.equal((list.innerHTML.match(/<svg class="desk-gallery-audio__cover|desk-gallery-audio__cover">/g) || []).length, 2);
  assert.match(status.textContent, /^共 2 首 · 总时长 3:36 · 总计 /);
  assert.equal(undo.hidden, true);
  assert.equal(backfill.hidden, false);
  assert.match(backfill.span.textContent, /有 3 首/);
  assert.equal(view.mounted(), true);
});

test('waveforms the archive has not measured are fetched once, one at a time', async () => {
  const { view, grid, calls, flush } = load();
  await view.mount(grid);
  await flush(); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.filter(call => call[0] === 'peaks'))), [['peaks', ITEMS[1].path]]);
  await view.refresh();
  await flush(); await flush();
  assert.equal(calls.filter(call => call[0] === 'peaks').length, 1, 'a refresh keeps the fetched waveform');
});

test('row actions: details, play, canvas, delete with undo, and lyrics copy', async () => {
  const { view, grid, list, undo, calls, notes, players, click, flush } = load();
  await view.mount(grid);
  const song = ITEMS[0].path;

  click('toggle', song);
  assert.match(list.innerHTML, /<pre>\[Verse\]\n第一行 &lt;la&gt;<\/pre>/);
  assert.match(list.innerHTML, /<footer><button type="button" class="desk-button desk-button--danger" data-audio-asset-action="delete"/);
  assert.match(list.innerHTML, /已附 \.abc 侧车/);

  click('play', song);
  await flush();
  assert.equal(players[0].getAttribute('src'), ITEMS[0].url);
  assert.equal(players[0].paused, false);
  assert.match(list.innerHTML, /<article class="desk-gallery-audio__card is-current[^"]*" data-audio-path="2026-11-09\/yue_aaaaaaaaaaaa\.flac">/);
  assert.match(list.innerHTML, /<span class="desk-gallery-audio__eyebrow is-live">/, 'the current card swaps its format line for the live indicator');
  assert.match(list.innerHTML, /aria-label="后退 10 秒" title="后退 10 秒">/);

  click('canvas', song);
  await flush(); await flush();
  const canvas = calls.find(call => call[0] === 'canvas')[1];
  assert.deepEqual(JSON.parse(JSON.stringify(canvas)), {
    blob: { type: 'audio/flac', size: 99 }, url: ITEMS[0].url, name: ITEMS[0].name, mime_type: 'audio/flac',
    file_size: ITEMS[0].file_size, duration_seconds: 215.6, task_id: ITEMS[0].job_id,
  });
  assert.ok(calls.some(call => call[0] === 'close'));
  assert.equal(players[0].paused, true, 'sending to the canvas stops gallery playback');

  click('copy-lyrics', song);
  await flush();
  assert.deepEqual(calls.find(call => call[0] === 'copy'), ['copy', '[Verse]\n第一行 <la>']);

  click('delete', song);
  await flush(); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(call => call[0] === 'delete'))), ['delete', [song]]);
  assert.equal(undo.hidden, false);
  assert.ok(notes.includes('音频已移入废纸篓'));
  view.unmount();
  assert.equal(view.mounted(), false);
  assert.equal(grid.classList.names.has('desk-gallery-audio'), false);
});

test('skipping on a card that is not playing starts it, forward from 10 s in', async () => {
  const { view, grid, list, click, flush, players } = load();
  await view.mount(grid);
  click('forward', ITEMS[0].path);
  await flush();
  assert.equal(players[0].getAttribute('src'), ITEMS[0].url);
  assert.equal(players[0].paused, false);
  players[0].duration = 215.6;
  players[0].listeners.loadedmetadata.forEach(handler => handler());
  assert.ok(Math.abs(players[0].currentTime - 10) < 0.01, `started at ${players[0].currentTime}`);
  click('back', ITEMS[1].path);
  await flush();
  assert.equal(players[0].getAttribute('src'), ITEMS[1].url);
  players[0].listeners.loadedmetadata.forEach(handler => handler());
  assert.equal(players[0].currentTime, 0, 'back starts the other song from the top');
  assert.ok(list.innerHTML.includes(`<article class="desk-gallery-audio__card is-current" data-audio-path="${ITEMS[1].path}">`));
});

test('a declined delete changes nothing', async () => {
  const { view, grid, calls, click, flush } = load({ confirm: false });
  await view.mount(grid);
  click('delete', ITEMS[0].path);
  await flush();
  assert.equal(calls.some(call => call[0] === 'delete'), false);
});

test('the gallery hosts the audio page like LoRA and the canvas owns node creation', () => {
  const html = read('frontend/desktop.html');
  assert.match(html, /data-gallery-view="videos">视频<\/button>\s*<button type="button" id="deskGalleryTabAudio" role="tab"[^>]*data-gallery-view="audio">音频<\/button>/);
  assert.ok(hasCacheKey(html, 'scripts/desktop-gallery-audio.js'));
  assert.ok(hasCacheKey(html, 'styles/desktop-gallery-audio.css'));
  const at = file => html.indexOf(`scripts/${file}?v=`);
  assert.ok(at('desktop-api.js') < at('desktop-gallery-audio.js'));
  assert.ok(at('desktop-gallery-audio.js') < at('desktop-history.js'));

  const history = read('frontend/scripts/desktop-history.js');
  assert.match(history, /if \(galleryView !== 'audio'\) audioGallery\?\.unmount\(\);/);
  assert.match(history, /if \(!audioGallery\?\.mounted\(\)\) \{\n\s*resetGalleryVirtualContent\(els\.deskGalleryGrid\);\n\s*audioGallery\?\.mount\(els\.deskGalleryGrid\);/);
  assert.match(history, /if \(loraGallery\?\.dispose\(\) === false\) return;\n\s*audioGallery\?\.unmount\(\);/);
  assert.match(history, /sendToCanvas: result => DesktopCanvas\.createAudioNodeFromAsset\(result\)/);

  const canvas = read('frontend/scripts/desktop-canvas.js');
  assert.match(canvas, /async function createAudioNodeFromAsset\(result\) \{\n\s*const nodeId = addNode\('audio', getViewportCenterWorldPoint\(\)\);[\s\S]*?await canvasAudio\.setResult\(nodeId, result\);/);

  const api = read('frontend/scripts/desktop-api.js');
  assert.match(api, /`\/api\/assets\/audio\?\$\{params\.toString\(\)\}`/);
  assert.match(api, /'\/api\/assets\/audio\/delete'/);
  assert.match(api, /parsed\.pathname !== '\/api\/assets\/audio\/file'/);
  assert.match(api, /'\/api\/audio\/unarchived'/);
  assert.match(api, /`\/api\/assets\/audio\/peaks\?path=\$\{encodeURIComponent/);

  const css = read('frontend/styles/desktop-gallery-audio.css');
  assert.doesNotMatch(css, /!important/);
  assert.match(css, /\.desk-gallery--audio :is\(\.desk-gallery-inspector, \.desk-gallery-search:not\(\.desk-gallery-audio__search\), \.desk-gallery-filter,.*\.desk-gallery-statsbar\)/);
  assert.match(css, /\.desk-gallery-audio__wave-played \{[^}]*clip-path: inset\(0 calc\(100% - var\(--progress\)\) 0 0\);/);
  assert.match(css, /@media \(prefers-reduced-motion: no-preference\) \{\n\s*\.desk-app \.desk-gallery-audio__card:has/);
  assert.doesNotMatch(css, /desk-gallery-audio__(item|row|text|actions|progress)\b/, 'the old list-row styles are gone');
});
