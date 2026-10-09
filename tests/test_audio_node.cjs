const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ROOT = path.resolve(__dirname, '..');
function load(extra = {}) {
  const context = { window: {}, Blob, ...extra };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'frontend/scripts/desktop-canvas-audio.js'), 'utf8'), context);
  return context.window.DesktopCanvasAudio;
}
const api = load();
const iconContext = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'frontend/scripts/desktop-state-icon.js'), 'utf8'), iconContext);
const stateIcon = iconContext.window.DesktopStateIcon;
test('audio node defaults own their geometry, metadata and playback preferences', () => {
  const node = api.createState('audio-example', { x: 10, y: 20 });
  assert.equal(node.type, 'audio');assert.equal(node.width, 800);assert.equal(node.height, 360);
  assert.equal(node.audioAssetId, '');assert.equal(node.mediaUrl, '');assert.equal(node.volume, 0.8);assert.equal(node.loop, false);
  assert.equal(node.durationSeconds, 0);assert.equal(node.peaks.length, 0);
  assert.ok(Object.isFrozen(api));assert.ok(Object.isFrozen(api.MENU_ITEM));
  const negative = api.createState('audio-negative', { x: -100, y: -50 });
  assert.equal(negative.x, -100);assert.equal(negative.y, -50);
});
test('normalization is bounded and does not persist transient URLs or playback', () => {
  const node = { mediaUrl: 'blob:stale', audioAssetId: '../bad', mimeType: 'image/svg+xml', volume: Infinity, peaks: [0.2, 12, NaN, -1], durationSeconds: -3, channels: 99, sampleRate: Infinity, audioData: 'data:text/html;base64,WA==' };
  api.normalizeState(node);
  assert.equal(node.mediaUrl, '');assert.equal(node.audioAssetId, '');assert.equal(node.mimeType, '');
  assert.equal(node.volume, 0.8);assert.deepEqual([...node.peaks], [0.2, 1, 0, 0]);assert.equal(node.durationSeconds, 0);assert.equal(node.channels, 32);assert.equal(node.sampleRate, 0);assert.ok(!('audioData' in node));
  assert.equal(api.normalizeState({ peaks: new Array(1000).fill(1) }).peaks.length, 240);
});
test('supported durable URLs and embedded audio survive workflow normalization', () => {
  for (const mediaUrl of ['/outputs/voice.wav', 'https://example.test/voice.mp3', 'http://localhost:18463/a.wav']) assert.equal(api.normalizeState({ mediaUrl }).mediaUrl, mediaUrl);
  for (const mediaUrl of ['javascript:alert(1)', 'file:///private/audio.wav', '//example.test/a.mp3', 'data:text/html,hi']) assert.equal(api.normalizeState({ mediaUrl }).mediaUrl, '');
  assert.equal(api.normalizeState({ audioData: 'data:audio/wav;base64,UklGRg==' }).audioData, 'data:audio/wav;base64,UklGRg==');
});
test('timeline formatting handles empty, long and invalid durations', () => {
  for (const [input, output] of [[0,'00:00'],[61.9,'01:01'],[3865,'01:04:25'],[Infinity,'00:00'],[-5,'00:00']]) assert.equal(api.formatTime(input), output);
  assert.equal(api.formatSize(0), '—');assert.equal(api.formatSize(1024), '1 KB');assert.equal(api.formatSize(1048576), '1.0 MB');
});
test('waveform is computed from actual samples, across both channels', () => {
  const silent = { numberOfChannels: 1, getChannelData: () => new Float32Array(100) };
  assert.deepEqual([...api.extractPeaks(silent, 4)], [0,0,0,0]);
  const channels = [new Float32Array([0,0.2,0,0.4,0,0.6,0,0.8]),new Float32Array([0,0.1,0,0.5,0,0.1,0,1])];
  const peaks = api.extractPeaks({ numberOfChannels: 2, getChannelData: c => channels[c] }, 4);
  assert.ok(Math.abs(peaks[0] - 0.2) < 1e-6);assert.equal(peaks[1], 0.5);assert.equal(peaks[3], 1);
  assert.equal(api.waveformPath([]), '');assert.ok(!/NaN|Infinity/.test(api.waveformPath([0,0.5,1])));
});
test('node markup exposes real controls and audio-only semantic ports', () => {
  const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const controller = api.create({stateIcon,escapeHtml: escape});
  const html = controller.nodeHtml({ id:'audio-test', mediaName:'<img src=x onerror=alert(1)>' });
  assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));
  assert.equal((html.match(/data-value-type="audio"/g) || []).length, 2);
  for(const action of ['import','play','back','forward','stop','loop','volume-up','volume-down','mute','download']) assert.ok(html.includes(`data-audio-action="${action}"`));
  assert.ok(html.includes('data-audio-needs-media disabled'));assert.ok(html.includes('data-node-drag-ignore'));
  assert.ok(!html.includes('录制'));assert.ok(!html.includes('分割'));
});
test('model input adapter returns typed binary and ignores stale node identity', async () => {
  const original = api.normalizeState({ id:'audio-a', audioAssetId:'audio-test', mediaName:'clip.wav', mimeType:'audio/wav' });
  let node = original;let release;
  const blob = new Blob(['fixture'], { type:'audio/wav' });
  const controller = api.create({stateIcon, getNodeState: () => node, assets: { get: () => new Promise(resolve => { release=resolve; }) } });
  const pending = controller.getInput('audio-a');node = {...original};release(blob);assert.equal(await pending, null);
  const changedSource = controller.getInput('audio-a');node.audioAssetId = 'audio-replacement';release(blob);assert.equal(await changedSource, null);
  const fresh = controller.getInput('audio-a');release(blob);const result=await fresh;
  assert.equal(result.data_type, 'audio');assert.equal(result.blob, blob);assert.equal(result.mime_type,'audio/wav');
});
