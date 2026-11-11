// One-click beat cutting (desktop-video-compose-beatfit.js): every clip ends on a beat on the output
// timeline, in points stay, transitions and speed are honoured, short sources fall back, and the
// workbench wiring (music panel buttons, undo, load order, cache keys).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const window = {};
const context = vm.createContext({ window, Promise });
for (const file of ['desktop-video-compose-subtitles.js', 'desktop-video-compose-model.js', 'desktop-video-compose-beatfit.js']) {
  vm.runInContext(read(`frontend/scripts/${file}`), context);
}
const model = window.DesktopVideoComposeModel;
const fit = window.DesktopVideoComposeBeatFit.create({ model });

const probe = (seconds, fps = 30) => ({ fps, width: 1920, height: 1080,
  frameTimes: Array.from({ length: Math.round(seconds * fps) }, (_v, i) => i / fps) });
const clip = (seconds, extra = {}) => ({ probe: probe(seconds), startFrame: 0, endFrame: -1, speed: 1,
  transition: { type: 'none', duration: 0.5 }, ...extra });
const beatsAt = (bpm, offset = 0.2, until = 60) => {
  const out = [];
  for (let t = offset; t < until; t += 60 / bpm) out.push(Math.round(t * 1000) / 1000);
  return out;
};
// Output end of every clip after applying a plan.
function ends(clips, result) {
  const applied = clips.map((c, k) => (result.ends[k] === undefined ? c : { ...c, endFrame: result.ends[k] }));
  const wins = applied.map(c => model.clipWindow(c.probe, c.startFrame, c.endFrame));
  return model.timing(applied, wins).segments.map(s => s.from + s.length);
}
const nearBeat = (beats, time, tolerance = 1 / 30) => beats.some(beat => Math.abs(beat - time) <= tolerance);

test('every clip ends on a beat, n beats apart', () => {
  const beats = beatsAt(120);
  const clips = [clip(6), clip(5), clip(7)];
  const result = fit.plan(clips, beats, 4);
  assert.equal(result.aligned, 3);
  assert.deepEqual([...result.missed], []);
  const out = ends(clips, result);
  out.forEach(time => assert.ok(nearBeat(beats, time), String(time)));
  assert.ok(Math.abs(out[1] - out[0] - 2) < 0.05);
  assert.ok(Math.abs(out[2] - out[1] - 2) < 0.05);
});

test('nearest keeps each clip close to its current length', () => {
  const beats = beatsAt(100);
  const clips = [clip(10, { endFrame: 99 }), clip(10, { endFrame: 129 })];
  const out = ends(clips, fit.plan(clips, beats, 'nearest'));
  out.forEach(time => assert.ok(nearBeat(beats, time)));
  assert.ok(Math.abs(out[0] - 3.333) < 0.35);
});

test('speed and transitions still land on beats; in points do not move', () => {
  const beats = beatsAt(90, 0.5);
  const clips = [clip(8, { startFrame: 30, speed: 1.5, transition: { type: 'fade', duration: 0.5 } }),
    clip(8, { transition: { type: 'fadeblack', duration: 1 } }), clip(8)];
  const result = fit.plan(clips, beats, 2);
  assert.equal(result.aligned, 3);
  ends(clips, result).forEach(time => assert.ok(nearBeat(beats, time, 0.03), String(time)));
});

test('a short source ends on its last reachable beat; one that reaches none keeps its trim', () => {
  const beats = beatsAt(60, 0.2);
  const clips = [clip(2.5), clip(20)];
  const result = fit.plan(clips, beats, 8);
  assert.deepEqual([...result.short], [0]);
  assert.ok(nearBeat(beats, ends(clips, result)[0]));
  const lonely = fit.plan([clip(3)], [10, 11, 12, 13], 4);
  assert.deepEqual([...lonely.missed], [0]);
  assert.equal(lonely.ends[0], undefined);
  assert.equal(fit.plan([clip(3)], [], 4).aligned, 0);
});

test('workbench wiring, load order and cache keys', () => {
  const view = read('frontend/scripts/desktop-video-compose-view.js');
  assert.match(view, /data-cb-beatfit/);
  const controller = read('frontend/scripts/desktop-canvas-video-compose.js');
  assert.match(controller, /beatfit\.plan\(/);
  assert.match(controller, /beatUndo/);
  assert.match(read('frontend/scripts/desktop-canvas.js'), /beatfits: window\.DesktopVideoComposeBeatFit/);
  const html = read('frontend/desktop.html');
  const order = ['desktop-video-compose-model.js', 'desktop-video-compose-beatfit.js', 'desktop-canvas-video-compose.js'];
  const positions = order.map(file => html.indexOf(`scripts/${file}?v=`));
  positions.forEach((at, k) => assert.ok(at > 0, order[k]));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  for (const file of order) assert.ok(hasCacheKey(html, `scripts/${file}`), file);
});
