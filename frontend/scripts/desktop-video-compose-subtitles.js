// Pure subtitle state for the compose node (phase 3b): cues on the output timeline (seconds), one
// style, SRT/VTT import and the snake_case piece of the compose request. Mirrors the limits in
// backend/video_edit/contracts.py and the layout numbers in backend/video_edit/subtitles.py (font
// size = short side × SIZE ratio, wrap width, margin, line height) so the draft overlay matches
// the burned-in render. No DOM, transport or canvas access.
(function () {
  const MAX_CUES = 100, MAX_CHARS = 80, MIN_SECONDS = 0.3, DEFAULT_SECONDS = 2, SNAP = 0.05;
  const SIZES = Object.freeze([['small', '小'], ['medium', '中'], ['large', '大']]);
  const POSITIONS = Object.freeze([['bottom', '底部'], ['top', '顶部']]);
  const LOOKS = Object.freeze([['outline', '描边'], ['box', '底框']]);
  const DEFAULT_STYLE = Object.freeze({size: 'medium', position: 'bottom', look: 'outline', font: ''});
  // backend subtitles.SIZES / MARGIN / WRAP / LINE_HEIGHT; stroke = 8% of the font size.
  const RATIOS = Object.freeze({small: 0.045, medium: 0.055, large: 0.07});
  const LAYOUT = Object.freeze({margin: 0.08, wrap: 0.86, lineHeight: 1.3, stroke: 0.08});
  const FONT_NAME = /^[^/\\\0:]{1,160}\.(ttf|otf|ttc)$/i;

  const pick = (value, options, fallback) => options.some(([key]) => key === value) ? value : fallback;
  const ms = value => Math.round(value * 1000) / 1000;
  const snap = value => Math.round(value / SNAP) * SNAP;
  // Same clean-up as contracts.subtitles_request: per-line trim, no CR, at most MAX_CHARS.
  const cleanText = value => String(value ?? '').replace(/\r/g, '').split('\n').map(line => line.trim()).join('\n')
    .replace(/^\n+|\n+$/g, '').slice(0, MAX_CHARS);

  function normalize(value) {
    const style = value?.style || {};
    const cues = (Array.isArray(value?.cues) ? value.cues : []).map(cue => {
      const start = Math.max(0, Number(cue?.start) || 0);
      return {start: ms(start), end: ms(Math.max(start + MIN_SECONDS, Number(cue?.end) || 0)), text: String(cue?.text ?? '').slice(0, MAX_CHARS)};
    }).sort((a, b) => a.start - b.start).slice(0, MAX_CUES);
    // Overlaps (hand-edited or legacy data) give way to the later cue's start.
    for (let k = 0; k + 1 < cues.length; k += 1) {
      if (cues[k].end > cues[k + 1].start) cues[k].end = Math.max(cues[k].start, cues[k + 1].start);
    }
    return {cues: cues.filter(cue => cue.end - cue.start >= MIN_SECONDS - 1e-6), style: {
      size: pick(style.size, SIZES, DEFAULT_STYLE.size), position: pick(style.position, POSITIONS, DEFAULT_STYLE.position),
      look: pick(style.look, LOOKS, DEFAULT_STYLE.look), font: FONT_NAME.test(String(style.font || '')) ? String(style.font) : ''}};
  }

  // Index of the cue showing at `time` (start inclusive, end exclusive), else -1.
  const cueAt = (cues, time) => cues.findIndex(cue => time >= cue.start && time < cue.end);

  // Room around `time`: the gap between neighbouring cues that contains it, bounded by [0, total].
  function gapAt(cues, time, total) {
    const before = cues.filter(cue => cue.end <= time + 1e-6).pop();
    const after = cues.find(cue => cue.start >= time - 1e-6 && cue.start > (before?.end ?? -1));
    return {from: before ? before.end : 0, to: after ? after.start : Math.max(total, time)};
  }

  // A new cue at `time` filling up to DEFAULT_SECONDS of the free gap there; returns its index or -1.
  function add(sub, time, total, text = '') {
    if (sub.cues.length >= MAX_CUES || cueAt(sub.cues, time) >= 0) return -1;
    const gap = gapAt(sub.cues, time, total);
    let start = Math.max(gap.from, ms(snap(time)));
    if (gap.to - start < MIN_SECONDS) start = gap.to - MIN_SECONDS;
    if (start < gap.from - 1e-6) return -1;
    const cue = {start: ms(start), end: ms(Math.min(gap.to, start + DEFAULT_SECONDS)), text};
    const index = sub.cues.findIndex(other => other.start > cue.start);
    sub.cues.splice(index < 0 ? sub.cues.length : index, 0, cue);
    return index < 0 ? sub.cues.length - 1 : index;
  }

  // Move or resize cue k within its neighbours (snapped, at least MIN_SECONDS, not past `limit`).
  // edge: 'move' | 'start' | 'end'; returns the cue's new {start, end}.
  function place(sub, k, edge, start, end, limit) {
    const cue = sub.cues[k];
    const lo = k ? sub.cues[k - 1].end : 0;
    const hi = k + 1 < sub.cues.length ? sub.cues[k + 1].start : Math.max(limit, cue.end);
    let a = snap(start), b = snap(end);
    if (edge === 'move') {
      const length = cue.end - cue.start;
      a = Math.min(Math.max(lo, a), hi - length);
      b = a + length;
    } else if (edge === 'start') {
      a = Math.min(Math.max(lo, a), cue.end - MIN_SECONDS);
      b = cue.end;
    } else {
      b = Math.max(Math.min(hi, b), cue.start + MIN_SECONDS);
      a = cue.start;
    }
    cue.start = ms(Math.max(lo, a));
    cue.end = ms(b);
    return {start: cue.start, end: cue.end};
  }

  const TIME = /(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})/;
  const seconds = match => (Number(match[1] || 0) * 3600) + Number(match[2]) * 60 + Number(match[3])
    + Number(match[4].padEnd(3, '0')) / 1000;

  // SRT or WebVTT text -> {cues, skipped}; tags are dropped, text is trimmed to MAX_CHARS.
  function parseSrt(text) {
    const cues = [];
    let skipped = 0;
    String(text || '').replace(/^﻿/, '').replace(/\r\n?/g, '\n').split(/\n\s*\n/).forEach(block => {
      const lines = block.split('\n');
      const at = lines.findIndex(line => line.includes('-->'));
      if (at < 0) return;
      const [left, right] = lines[at].split('-->');
      const from = TIME.exec(left), to = TIME.exec(right || '');
      const body = cleanText(lines.slice(at + 1).join('\n').replace(/<[^>]*>/g, '').replace(/\{\\[^}]*\}/g, ''));
      if (!from || !to || !body) { skipped += 1; return; }
      cues.push({start: seconds(from), end: seconds(to), text: body});
    });
    const sub = normalize({cues});
    return {cues: sub.cues, skipped: skipped + cues.length - sub.cues.length};
  }

  // Request piece and settings-key piece: null without cues, so earlier results keep their keys.
  const request = sub => sub.cues.length ? {cues: sub.cues.map(cue => ({start: cue.start, end: cue.end, text: cleanText(cue.text)})),
    style: {...sub.style}} : null;
  const key = sub => sub.cues.length ? [sub.cues.map(cue => [cue.start, cue.end, cleanText(cue.text)]), sub.style] : null;

  // Why these cues cannot render against `total` output seconds (the backend gives the same reasons).
  function blocker(sub, total) {
    const empty = sub.cues.findIndex(cue => !cleanText(cue.text));
    if (empty >= 0) return `第 ${empty + 1} 条字幕没有文字`;
    const late = sub.cues.findIndex(cue => cue.start >= total - MIN_SECONDS + 1e-6);
    if (late >= 0) return `第 ${late + 1} 条字幕在成片结束之后（成片 ${total.toFixed(2)} 秒），请调整字幕时间`;
    return '';
  }

  window.DesktopVideoComposeSubtitles = Object.freeze({
    MAX_CUES, MAX_CHARS, MIN_SECONDS, SNAP, SIZES, POSITIONS, LOOKS, DEFAULT_STYLE, RATIOS, LAYOUT,
    normalize, cueAt, gapAt, add, place, parseSrt, request, key, blocker, cleanText,
  });
})();
