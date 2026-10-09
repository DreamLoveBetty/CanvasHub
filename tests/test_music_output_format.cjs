const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({window: {}});
for (const name of ['desktop-state-icon', 'desktop-music-model', 'desktop-music-view']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts', name + '.js'), 'utf8'), context);
}
const model = context.window.DesktopMusicModel;
const view = context.window.DesktopMusicView.create({model, stateIcon:context.window.DesktopStateIcon, escapeHtml: value => String(value ?? '')});
const create = () => model.createState('g', 'music_generate', {});
const files = ['flac', 'wav'].map(fmt => ({kind: 'audio', name: `result/audio.${fmt}`, url: `/${fmt}`}));

test('old workflow defaults FLAC; WAV survives JSON normalization', () => {
  assert.equal(create().audioFormat, 'flac');
  const node = {...create(), audioFormat: 'wav'};
  assert.equal(model.normalizeState(JSON.parse(JSON.stringify(node))).audioFormat, 'wav');
  node.audioFormat = 'mp3';
  assert.equal(model.normalizeState(node).audioFormat, 'flac');
});
test('format maps to export spec, not SongRequest; plan omits audio setting', () => {
  const node = {...create(), audioFormat: 'wav'};
  const input = {style: 'pop', lyrics: 'synthetic lyrics'};
  assert.equal(model.generationRequest(node, input).audio_format, 'wav');
  assert.equal(model.generationRequest(node, input).request.audio_format, undefined);
  node.operation = 'plan';
  assert.equal(model.generationRequest(node, input).audio_format, undefined);
});
test('selected completed-job format beats manifest order', () => {
  assert.equal(model.audioArtifact(files, {audio_format: 'wav'}).url, '/wav');
  assert.equal(model.audioArtifact([...files].reverse(), {audio_format: 'flac'}).url, '/flac');
  assert.equal(model.audioArtifact([...files].reverse()).url, '/flac');
  assert.equal(model.audioArtifact([files[1]]).url, '/wav');
  assert.equal(model.audioArtifact([files[0]], {audio_format: 'wav'}), undefined);
  assert.equal(model.audioArtifact(), undefined);
});
test('generation shows FLAC/WAV but no file buttons, preserving result data', () => {
  const node = {...create(), status: 'succeeded', artifacts: files, audioFormat: 'wav'};
  const html = view.nodeHtml(node);
  assert.match(html, /data-music-field="audioFormat"/);
  assert.match(html, /value="wav" selected/);
  assert.match(html, /desk-music__generation-format"><label>生成格式<select data-music-field="audioFormat"/);
  const params = html.split('desk-music__generation-params">')[1].split('</div>')[0];
  assert.doesNotMatch(params, /audioFormat/);
  assert.equal([...params.matchAll(/<label>/g)].length, 8);
  assert.doesNotMatch(html, /音频格式/);
  assert.doesNotMatch(html, /data-music-artifacts|data-music-download|<details/);
  assert.doesNotMatch(html, /data-music-job-status|data-music-elapsed|data-music-error/);
  assert.match(html, /data-music-progress/);
  assert.equal(node.artifacts, files);
  const transcribe = view.nodeHtml(model.createState('t', 'music_transcribe', {}));
  assert.doesNotMatch(transcribe, /data-music-field="audioFormat"/);
  assert.match(transcribe, /data-music-artifacts/);
});
