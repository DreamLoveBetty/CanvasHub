// Music beat snapping frontend: the model's nearest-beat lookup, the API adapter, and the wiring of
// beat ticks, the snap toggle and trim snapping (the drag itself is checked on the served page).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function load(files, extra = {}) {
  const window = { location: { href: 'http://127.0.0.1:18463/desktop.html', origin: 'http://127.0.0.1:18463' } };
  const context = vm.createContext({ window, URL, URLSearchParams, Promise, ...extra });
  for (const file of [].concat(files)) vm.runInContext(read(`frontend/scripts/${file}`), context);
  return context.window;
}

test('nearestBeat picks the closest beat within the tolerance only', () => {
  const { DesktopVideoComposeModel: model } = load(['desktop-video-compose-subtitles.js', 'desktop-video-compose-model.js']);
  const beats = [0.5, 1.0, 1.5, 2.0];
  assert.equal(model.nearestBeat(beats, 1.12, 0.2), 1.0);
  assert.equal(model.nearestBeat(beats, 1.38, 0.2), 1.5);
  assert.equal(model.nearestBeat(beats, 1.25, 0.1), null);
  assert.equal(model.nearestBeat(beats, 0.1, 0.5), 0.5);
  assert.equal(model.nearestBeat(beats, 9, 0.5), null);
  assert.equal(model.nearestBeat([], 1, 1), null);
  assert.equal(model.nearestBeat(undefined, 1, 1), null);
});

test('the API adapter asks by archive URL or uploaded asset and cleans the reply', async () => {
  const calls = [];
  const api = { json: async url => { calls.push(url); return { tempo: '120.4', beats: [0.5, '1.0', null, 'x', 1.5] }; } };
  const { DesktopVideoEditAPI: edit } = load('desktop-video-edit-api.js', { api });
  const byUrl = await edit.compose.musicBeats({ sourceUrl: '/api/assets/audio/file?path=a.flac' });
  await edit.compose.musicBeats({ assetId: 'a'.repeat(64) + '.wav', sourceUrl: 'ignored' });
  assert.deepEqual(calls, ['/api/video_edit/music_beats?source_url=%2Fapi%2Fassets%2Faudio%2Ffile%3Fpath%3Da.flac',
    `/api/video_edit/music_beats?asset_id=${'a'.repeat(64)}.wav`]);
  assert.equal(byUrl.tempo, 120.4);
  assert.deepEqual([...byUrl.beats], [0.5, 1.5]);
});

test('ticks, toggle and snapping are wired; the toggle survives blocked storage', () => {
  const timeline = read('frontend/scripts/desktop-video-compose-timeline.js');
  assert.match(timeline, /class="is-beats"/);
  assert.match(timeline, /BPM/);
  assert.match(timeline, /snapTrim\(clip, k, edge,/);
  assert.match(timeline, /data-tl-snap hidden/);
  assert.match(timeline, /\[\.\.\.beats\.filter\(beat => beat < music\.seconds\), music\.seconds\]/);
  assert.match(timeline, /'配乐结尾' : '卡点'/);
  assert.match(timeline, /showGuide\(next\.beat\)/);
  assert.match(timeline, /showGuide\(null\)/);
  assert.match(timeline, /edge === 'out' \? win\.stop \+ shift : win\.start - shift/);
  assert.match(read('frontend/scripts/desktop-video-compose-view.js'), /data-cb-snap/);
  const controller = read('frontend/scripts/desktop-canvas-video-compose.js');
  assert.match(controller, /api\.compose\.musicBeats\(input\)/);
  assert.match(controller, /musicInput\(s, music\)\s*\.then/);
  assert.match(controller, /try \{ return window\.localStorage\.getItem\(SNAP_KEY\)/);
  assert.match(controller, /try \{ window\.localStorage\.setItem\(SNAP_KEY/);
  assert.match(controller, /snap: snapBeats/);
  assert.match(read('frontend/styles/desktop-video-edit.css'), /desk-video-compose-tl__music \.is-beats/);
});

test('load order and cache keys', () => {
  const html = read('frontend/desktop.html');
  const order = ['desktop-video-edit-api.js', 'desktop-video-compose-model.js', 'desktop-video-compose-timeline.js',
    'desktop-video-compose-view.js', 'desktop-canvas-video-compose.js'];
  const positions = order.map(file => html.indexOf(`scripts/${file}?v=`));
  positions.forEach((at, k) => assert.ok(at > 0, order[k]));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  for (const file of order) assert.ok(hasCacheKey(html, `scripts/${file}`), file);
  assert.ok(hasCacheKey(html, 'styles/desktop-video-edit.css'));
});
