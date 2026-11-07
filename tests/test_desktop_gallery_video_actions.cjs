'use strict';
// The video page drops the selection basket: the source switch sits on the stats row and each expanded
// video carries its own save-to-set / hide / delete actions; videos in sets stay image-only for tools.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

test('video source switch lives in the stats bar with a hidden source', () => {
  const html = read('frontend/desktop.html');
  const bar = html.slice(html.indexOf('id="deskGalleryStatsBar"'), html.indexOf('<div class="desk-gallery__body">'));
  assert.ok(bar.includes('id="deskGalleryStats"') && bar.includes('id="deskGalleryVideoSource"'));
  for (const source of ['generated', 'imported', 'all', 'hidden']) {
    assert.ok(bar.includes(`data-gallery-video-source="${source}"`), source);
  }
  const toolbar = html.slice(html.indexOf('desk-gallery__toolbar'), html.indexOf('id="deskGalleryStatsBar"'));
  assert.ok(!toolbar.includes('deskGalleryVideoSource'));
  for (const asset of ['scripts/desktop-gallery-videos.js', 'scripts/desktop-history.js', 'scripts/desktop-api.js',
    'styles/desktop-gallery-geometry.css', 'styles/desktop-liquid.css', 'styles/desktop-lora.css']) {
    assert.ok(hasCacheKey(html, asset), asset);
  }
});

test('expanded video offers save-to-set, hide and delete with undo', () => {
  const videos = read('frontend/scripts/desktop-gallery-videos.js');
  for (const attr of ['data-gallery-video-save-set', 'data-gallery-video-hide', 'data-gallery-video-delete', 'data-gallery-video-undo']) {
    assert.ok(videos.includes(attr), attr);
  }
  assert.match(videos, /DesktopApi\.deleteVideoAssets\(\[video\.path\]\)/);
  assert.match(videos, /DesktopApi\.updateAssetMeta\(video\.assetId, \{ hidden: !video\.hidden \}\)/);
  assert.match(videos, /DesktopApi\.undoAssetDelete\(lastVideoDeleteBatchIds\)/);
  assert.match(videos, /mediaKind: 'video'/);
  const api = read('frontend/scripts/desktop-api.js');
  assert.match(api, /'\/api\/assets\/videos\/delete'/);
  assert.match(api, /^\s+deleteVideoAssets,$/m);
});

test('video page hides the basket and sets keep tools image-only', () => {
  const geometry = read('frontend/styles/desktop-gallery-geometry.css');
  assert.match(geometry, /\.desk-gallery--videos \.desk-gallery-inspector \{\s*display: none;/);
  assert.match(geometry, /\.desk-gallery-statsbar\[hidden\] \+ \.desk-gallery__body/);
  assert.ok(!geometry.includes('.desk-gallery-stats[hidden]'));
  assert.ok(read('frontend/styles/desktop-lora.css').includes('.desk-gallery-statsbar)'));
  const history = read('frontend/scripts/desktop-history.js');
  assert.match(history, /toggle\('desk-gallery--videos', galleryView === 'videos'\)/);
  assert.match(history, /async function saveVideoToSet\(snapshot\)/);
  assert.match(history, /function setImageAssets\(assets\)/);
  assert.match(history, /window\.open\(mediaUrl\(asset\.videoUrl\), '_blank', 'noopener'\)/);
});
