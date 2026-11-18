const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function load() {
  const context = { window: {}, console };
  vm.runInNewContext(read('frontend/scripts/desktop-history-results.js'), context);
  return context.window.DesktopHistoryResults;
}

test('history helper: deleting one image of a batch keeps the other and the task', () => {
  const H = load();
  const item = {
    task_id: 't1',
    status: 'success',
    result_files: ['a.png', 'b.png'],
    result_file: 'a.png',
    output_files: ['a.png', 'b.png'],
    image_paths: ['/image/a.png', '/image/b.png']
  };
  const next = H.applyRemovedHistoryFiles(item, H.fileKeysFrom(['/image/a.png', 'a.png']));
  assert.deepEqual(next.result_files, ['b.png']);
  assert.equal(next.result_file, 'b.png');
  assert.deepEqual(next.image_paths, ['/image/b.png']);
  assert.equal(next.missing_result_files, false);
  assert.equal(H.shouldShowHistoryRow(next, { hasVisibleImage: true }), true);
});

test('history helper: deleting the last file keeps an audit row without a thumb path', () => {
  const H = load();
  const failed = H.applyRemovedHistoryFiles({
    task_id: 't-fail',
    status: 'failed',
    result_files: ['gone.png'],
    result_file: 'gone.png',
    image_paths: ['/image/gone.png']
  }, ['gone.png']);
  assert.deepEqual(failed.result_files, []);
  assert.equal(failed.result_file, '');
  assert.equal(failed.missing_result_files, true);
  assert.equal(H.shouldShowHistoryRow(failed, { hasVisibleImage: false, isInFlight: false }), true, 'failed task with deleted files stays visible as 无图');

  const succeeded = H.applyRemovedHistoryFiles({
    task_id: 't-ok',
    status: 'success',
    result_files: ['gone.png'],
    result_file: 'gone.png',
    image_paths: ['/image/gone.png']
  }, ['GONE.PNG']);
  assert.equal(succeeded.missing_result_files, true);
  assert.equal(H.shouldShowHistoryRow(succeeded, { hasVisibleImage: false }), true);

  const neverHad = { task_id: 't-empty', status: 'failed', result_files: [], result_file: '', image_paths: [] };
  assert.equal(H.shouldShowHistoryRow(neverHad, { hasVisibleImage: false, isInFlight: false }), false, 'failed tasks that never had files stay hidden');
  assert.equal(H.shouldShowHistoryRow({ status: 'queued' }, { hasVisibleImage: false, isInFlight: true }), true);
  assert.equal(H.shouldShowHistoryRow(neverHad, { isFileItem: true, hasVisibleImage: true }), false, 'ppt/psd still excluded');
});

test('history helper: encoded URLs match stored basenames', () => {
  const H = load();
  assert.equal(H.fileKey('/image/foo%20bar.png?w=420'), 'foo bar.png');
  const next = H.applyRemovedHistoryItems([
    { result_files: ['foo bar.png'], result_file: 'foo bar.png', image_paths: ['/image/foo%20bar.png'] }
  ], ['/image/foo%20bar.png?w=420']);
  assert.deepEqual(next[0].result_files, []);
  assert.equal(next[0].missing_result_files, true);
});

test('desktop-history.js uses the helper after delete and on reload, and keeps 无图 instead of an img', () => {
  const history = read('frontend/scripts/desktop-history.js');
  assert.match(history, /rememberRemovedHistoryFiles/);
  assert.match(history, /renderHistory\(DesktopState\.state\.history\)/);
  assert.match(history, /historyItemsForDisplay\(Array\.isArray\(data\.history\)/);
  assert.match(history, /DesktopHistoryResults\.shouldShowHistoryRow/);
  assert.match(history, /sessionRemovedHistoryFiles\.delete\(key\)/);
  assert.match(history, /imagePath \? `<img src=.*data-fallback/s);
  assert.match(history, /: '无图'}/);
  // Do not treat a generic img error as a deleted file (401/network must not become 无图).
  const errorHandler = history.match(/list\.querySelectorAll\('img\[data-fallback\]'\)[\s\S]{0,400}/);
  assert.ok(errorHandler, 'fallback error hook still exists');
  assert.doesNotMatch(errorHandler[0], /无图|missing_result_files|display\s*=\s*'none'/);
});

test('cache key and history module order', () => {
  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-history-results.js'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-history.js'));
  const resultsAt = html.search(/scripts\/desktop-history-results\.js\?v=/);
  const historyAt = html.search(/scripts\/desktop-history\.js\?v=/);
  assert.ok(resultsAt !== -1 && resultsAt < historyAt, 'results helper must load before desktop-history.js');
});

test('comfy video tasks matching the 11/15 sidebar cards are not rendered as image rows', () => {
  const H = load();
  // De-identified copy of the live /api/history shape: type=comfy, comfy_output_kind=video,
  // succeeded_no_telegram ("已保存"), empty image_paths, result_files still list the mp4.
  const liveShape = {
    task_id: 'fixture-comfy-video-20261115',
    status: 'succeeded_no_telegram',
    type: 'comfy',
    prompt: 'For the target...',
    params: { comfy_output_kind: 'video', width: 1248, height: 1664, fps: 24, duration_seconds: 15.792 },
    result_file: 'comfy_fixture_selfliftAvatar_00006-audio.mp4',
    result_files: ['comfy_fixture_selfliftAvatar_00006-audio.mp4'],
    output_files: ['comfy_fixture_selfliftAvatar_00006-audio.mp4'],
    image_paths: [],
    image_count: 0,
    video_paths: ['/video/comfy_fixture_selfliftAvatar_00006-audio.mp4'],
    video_path: '/video/comfy_fixture_selfliftAvatar_00006-audio.mp4',
    video_count: 1,
    created_at: 1794754284
  };

  const legacyIsVideo = item => {
    const type = String(item?.type || '').toLowerCase();
    return type === 'minimax-h3-video' || type.includes('h3-video');
  };
  assert.equal(legacyIsVideo(liveShape), false, 'old type-only check missed comfy videos');
  // Old flattenHistoryItems used result_files even when image_paths was empty, inventing /image/*.mp4.
  assert.equal(`/image/${liveShape.result_file}`, '/image/comfy_fixture_selfliftAvatar_00006-audio.mp4');

  assert.equal(H.isVideoHistoryItem(liveShape), true);
  assert.equal(
    H.shouldShowHistoryRow(liveShape, { hasVisibleImage: true }),
    false,
    'comfy videos must leave the image sidebar even if flatten invented a thumb'
  );
  assert.equal(H.isVideoHistoryItem({ type: 'minimax-h3-video', video_paths: ['/video/a.mp4'] }), true);
  assert.equal(H.isVideoHistoryItem({ type: 'cyimg-video', result_files: ['clip.mp4'] }), true);
  assert.equal(H.isVideoHistoryItem({
    type: 'comfy',
    params: { comfy_output_kind: 'image' },
    result_files: ['still.png'],
    image_paths: ['/image/still.png']
  }), false);
  assert.equal(H.shouldShowHistoryRow({
    type: 'comfy',
    params: { comfy_output_kind: 'image' },
    result_files: ['still.png'],
    image_paths: ['/image/still.png']
  }, { hasVisibleImage: true }), true);

  const history = read('frontend/scripts/desktop-history.js');
  assert.match(history, /DesktopHistoryResults\.isVideoHistoryItem/);
  assert.match(history, /if \(isVideoHistoryItem\(item\) \|\| isFileHistoryItem\(item\)\) return \[\];/);
});
