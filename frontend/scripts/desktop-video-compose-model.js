// Pure video-compose state and connection contract: clip order/trim/speed/transition, music and output settings,
// the snake_case recipe for /api/video_edit/compose and the client mirror of the backend's
// clip-window and output-size math. Subtitle cues are normalized by desktop-video-compose-subtitles.js
// (loaded first). No DOM, transport or canvas access.
(function () {
  const Subtitles = window.DesktopVideoComposeSubtitles;
  const TYPE = 'video_compose';
  const WIDTH = 300, HEIGHT = 318;
  const MAX_CLIPS = 20, MAX_SECONDS = 180, MIN_CLIP_SECONDS = 0.5;
  const ASPECTS = Object.freeze([['source', '跟随首段'], ['16:9', '16:9'], ['9:16', '9:16'], ['1:1', '1:1'], ['4:5', '4:5']]);
  const RESOLUTIONS = Object.freeze([[720, '720p'], [1080, '1080p']]);
  const FRAME_RATES = Object.freeze([[24, '24'], [30, '30']]);
  const FITS = Object.freeze([['crop', '裁切填满'], ['pad', '加黑边'], ['blur', '模糊背景']]);
  const ENCODERS = Object.freeze([['quality', '画质优先'], ['fast', '快速']]);
  const FADES = Object.freeze([[0, '无'], [0.5, '0.5 秒'], [1, '1 秒'], [1.5, '1.5 秒'], [2, '2 秒']]);
  // Phase 3, mirrors backend contracts: per-clip speed and the transition into the next clip.
  const SPEEDS = Object.freeze([[0.5, '0.5×'], [0.75, '0.75×'], [1, '1×'], [1.25, '1.25×'], [1.5, '1.5×'], [2, '2×']]);
  const TRANSITIONS = Object.freeze([['none', '无'], ['fade', '叠化'], ['fadeblack', '黑场'], ['wipeleft', '擦除']]);
  const TRANSITION_SECONDS = Object.freeze([[0.5, '0.5 秒'], [1, '1 秒']]);
  const OUTPUT_DEFAULTS = Object.freeze({aspect: 'source', resolution: 1080, fps: 30, fit: 'crop', encoder: 'quality'});
  const RATIOS = Object.freeze({'16:9': [16, 9], '9:16': [9, 16], '1:1': [1, 1], '4:5': [4, 5]});
  // Downstream nodes that accept a rendered compose result as their video source.
  const CONSUMERS = Object.freeze(['topaz_video', 'video_control', 'comfy']);

  const active = status => ['submitting', 'queued', 'running', 'cancelling'].includes(status);
  const pick = (value, options, fallback) => options.some(([key]) => String(key) === String(value))
    ? options.find(([key]) => String(key) === String(value))[0] : fallback;
  const bounded = (value, lo, hi, fallback) => Number.isFinite(Number(value)) ? Math.min(hi, Math.max(lo, Number(value))) : fallback;
  const whole = (value, lo, fallback) => Number.isInteger(value) && value >= lo ? value : fallback;
  const id32 = value => /^[a-f0-9]{32}$/.test(value || '') ? value : '';

  function normalizeClip(clip) {
    const start = whole(clip?.startFrame, 0, 0);
    let end = whole(clip?.endFrame, -1, -1);
    if (end !== -1 && end < start) end = -1;
    const transition = clip?.transition || {};
    return {sourceId: String(clip?.sourceId || ''), startFrame: start, endFrame: end, audio: clip?.audio !== false,
      speed: pick(clip?.speed, SPEEDS, 1),
      transition: {type: pick(transition.type, TRANSITIONS, 'none'), duration: pick(transition.duration, TRANSITION_SECONDS, 0.5)}};
  }

  function normalizeResult(result) {
    if (!result || typeof result !== 'object' || !/^\/video\/video_compose_[\w.-]+\.mp4$/.test(String(result.url || ''))) return null;
    return {url: result.url, filename: String(result.filename || result.url.split('/').pop()), key: String(result.key || ''),
      fileSize: bounded(result.fileSize, 0, 1e12, 0), durationSeconds: bounded(result.durationSeconds, 0, 3600, 0),
      width: bounded(result.width, 0, 8192, 0), height: bounded(result.height, 0, 8192, 0), fps: bounded(result.fps, 0, 120, 0),
      jobId: id32(result.jobId)};
  }

  function normalize(node) {
    node.width = WIDTH; node.height = HEIGHT;
    node.title = String(node.title || '视频合成').slice(0, 80);
    const seen = new Set();
    node.clips = (Array.isArray(node.clips) ? node.clips : []).map(normalizeClip)
      .filter(clip => clip.sourceId && !seen.has(clip.sourceId) && seen.add(clip.sourceId)).slice(0, MAX_CLIPS);
    node.clipVolume = bounded(node.clipVolume, 0, 1.5, 1);
    const music = node.music || {};
    node.music = {volume: bounded(music.volume, 0, 1.5, 0.8), fadeIn: pick(music.fadeIn, FADES, 0), fadeOut: pick(music.fadeOut, FADES, 1.5)};
    const output = node.output || {};
    node.output = {aspect: pick(output.aspect, ASPECTS, OUTPUT_DEFAULTS.aspect), resolution: pick(output.resolution, RESOLUTIONS, 1080),
      fps: pick(output.fps, FRAME_RATES, 30), fit: pick(output.fit, FITS, 'crop'), encoder: pick(output.encoder, ENCODERS, 'quality')};
    node.subtitles = Subtitles.normalize(node.subtitles);
    node.jobId = id32(node.jobId);
    node.status = String(node.status || 'idle');
    node.submittedKey = String(node.submittedKey || '');
    node.result = normalizeResult(node.result);
    // The output port: a rendered compose node is a video source for downstream nodes.
    if (node.result) Object.assign(node, {mediaUrl: node.result.url, mediaName: node.result.filename, mimeType: 'video/mp4'});
    else { delete node.mediaUrl; delete node.mediaName; delete node.mimeType; }
    return node;
  }

  // Keep clip order and trims for videos still connected; append new connections in edge order.
  function syncClips(node, sourceIds) {
    const ids = [...new Set(sourceIds)].slice(0, MAX_CLIPS);
    const kept = node.clips.filter(clip => ids.includes(clip.sourceId));
    const known = new Set(kept.map(clip => clip.sourceId));
    const added = ids.filter(id => !known.has(id)).map(sourceId => normalizeClip({sourceId}));
    const next = [...kept, ...added];
    const changed = next.length !== node.clips.length || next.some((clip, index) => clip !== node.clips[index]);
    node.clips = next;
    return changed;
  }

  function moveClip(node, from, to) {
    if (from === to || !node.clips[from]) return false;
    const [clip] = node.clips.splice(from, 1);
    node.clips.splice(Math.max(0, Math.min(node.clips.length, to)), 0, clip);
    return true;
  }

  // Mirrors backend/video_edit/plan.clip_window: [start, end] inclusive, the last frame lasts one gap.
  function clipWindow(probe, startFrame, endFrame) {
    const times = probe?.frameTimes || [];
    const count = times.length;
    if (!count) return null;
    const start = Math.min(Math.max(0, startFrame), count - 1);
    const end = endFrame === -1 ? count - 1 : Math.min(Math.max(start, endFrame), count - 1);
    const gap = end > 0 ? times[end] - times[end - 1] : 1 / Math.max(probe.fps || 30, 1);
    const stop = end + 1 < count ? times[end + 1] : times[end] + gap;
    return {startFrame: start, endFrame: end, frames: end - start + 1, start: times[start], stop,
      seconds: Math.round((stop - times[start]) * 1e6) / 1e6};
  }

  const round6 = value => Math.round(value * 1e6) / 1e6;

  // Mirrors plan.output_seconds / transition_cuts / total_seconds. clips: [{speed, transition}];
  // wins: clipWindow per clip or null (not probed yet; it then counts 0 s and takes no transition).
  // segments are the draft pieces: each clip loses half of each overlap, so they butt end to end.
  function timing(clips, wins) {
    const lengths = clips.map((clip, k) => wins[k] ? round6(wins[k].seconds / (clip.speed || 1)) : 0);
    const cuts = clips.slice(0, -1).map((clip, k) => {
      const type = clip.transition?.type || 'none';
      if (type === 'none' || !wins[k] || !wins[k + 1]) return 0;
      return round6(Math.min(clip.transition.duration, lengths[k] / 2, lengths[k + 1] / 2));
    });
    let from = 0;
    const segments = lengths.map((length, k) => {
      const head = k ? cuts[k - 1] / 2 : 0, tail = k < cuts.length ? cuts[k] / 2 : 0;
      const segment = {from, length: Math.max(0, length - head - tail), head, tail};
      from += segment.length;
      return segment;
    });
    return {lengths, cuts, segments, total: round6(lengths.reduce((a, b) => a + b, 0) - cuts.reduce((a, b) => a + b, 0))};
  }

  // Beat (sorted seconds) nearest to `time` within `tolerance` seconds, or null. Snapping only: the
  // music starts with the output, so music seconds and output seconds are the same.
  function nearestBeat(beats, time, tolerance) {
    let lo = 0, hi = (beats || []).length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (beats[mid] < time) lo = mid + 1; else hi = mid; }
    const best = [beats?.[lo - 1], beats?.[lo]].filter(Number.isFinite)
      .reduce((a, b) => a === null || Math.abs(b - time) < Math.abs(a - time) ? b : a, null);
    return best !== null && Math.abs(best - time) <= tolerance ? best : null;
  }

  // Mirrors plan.output_size: short side = resolution, even dimensions, long side <= 3840.
  function outputSize(output, probe) {
    const [across, down] = RATIOS[output.aspect] || [Math.max(1, probe?.width || 16), Math.max(1, probe?.height || 9)];
    let width = across >= down ? output.resolution * across / down : output.resolution;
    let height = across >= down ? output.resolution : output.resolution * down / across;
    const scale = Math.min(1, 3840 / Math.max(width, height));
    const even = value => Math.max(2, Math.round(value * scale / 2) * 2);
    return {width: even(width), height: even(height)};
  }

  // Speed and a transition join a clip's entry only when set (the last clip's never counts), so
  // phase-2 results keep their key, as the backend keeps their file names.
  const clipExtras = (clip, last) => [...(clip.speed !== 1 ? [{speed: clip.speed}] : []),
    ...(!last && clip.transition.type !== 'none' ? [{transition: [clip.transition.type, clip.transition.duration]}] : [])];

  // Everything that changes the rendered file. sources: sourceId -> {url}; musicKey: '' when none.
  // Subtitles join only when there are cues, like speed and transitions.
  function settingsKey(node, sources, musicKey) {
    const subtitles = Subtitles.key(node.subtitles);
    return JSON.stringify({clips: node.clips.map((clip, k) => [sources[clip.sourceId]?.url || clip.sourceId,
      clip.startFrame, clip.endFrame, clip.audio, ...clipExtras(clip, k === node.clips.length - 1)]),
    clipVolume: node.clipVolume, output: node.output,
    music: musicKey ? [musicKey, node.music.volume, node.music.fadeIn, node.music.fadeOut] : null,
    ...(subtitles ? {subtitles} : {})});
  }

  // sources: sourceId -> {url, name}; music: {sourceUrl | assetId, name} or null.
  function request(node, sources, music) {
    return {
      title: node.title,
      clips: node.clips.map(clip => ({source_url: sources[clip.sourceId].url, source_name: sources[clip.sourceId].name || '',
        start_frame: clip.startFrame, end_frame: clip.endFrame, audio: clip.audio, speed: clip.speed,
        transition: {type: clip.transition.type, duration: clip.transition.duration}})),
      clip_volume: node.clipVolume,
      music: music ? {...(music.assetId ? {asset_id: music.assetId} : {source_url: music.sourceUrl}), source_name: music.name || '',
        volume: node.music.volume, fade_in: node.music.fadeIn, fade_out: node.music.fadeOut} : null,
      output: {...node.output},
      subtitles: Subtitles.request(node.subtitles),
    };
  }

  function resultFromJob(job, key) {
    const result = job?.result || {};
    return normalizeResult({url: result.url, filename: result.filename, fileSize: result.file_size,
      durationSeconds: result.duration_seconds, width: result.width, height: result.height, fps: result.fps, key, jobId: job?.id});
  }

  const isVideoSource = node => node?.type === 'video' || (node?.type === TYPE && Boolean(node.mediaUrl));
  const targets = Object.freeze({video: [TYPE], audio: [TYPE], [TYPE]: CONSUMERS});
  function policy(from, to) {
    if (to?.type === TYPE && from?.type === 'video') return {inputRole: 'clip', outputRole: 'video'};
    if (to?.type === TYPE && from?.type === 'audio') return {inputRole: 'music', outputRole: 'audio', single: true};
    if (from?.type === TYPE && CONSUMERS.includes(to?.type)) {
      return {inputRole: 'video', outputRole: 'video', single: to.type !== 'comfy'};
    }
    return null;
  }

  const labels = Object.freeze({idle: '未合成', submitting: '提交中', queued: '排队中', running: '合成中', cancelling: '停止中',
    succeeded: '成片 ✓', failed: '合成失败', cancelled: '已停止', interrupted: '已中断'});
  const ICON = '<svg viewBox="0 0 24 24" class="desk-node-icon" aria-hidden="true"><rect x="2.5" y="6" width="7" height="12" rx="1.5"/><rect x="11" y="6" width="5" height="12" rx="1.5"/><path d="M17.5 6h2.5a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5h-2.5"/></svg>';

  window.DesktopVideoComposeModel = Object.freeze({
    TYPE, WIDTH, HEIGHT, MAX_CLIPS, MAX_SECONDS, MIN_CLIP_SECONDS, SUBTITLE_MIN_SECONDS: Subtitles.MIN_SECONDS, ASPECTS, RESOLUTIONS, FRAME_RATES, FITS, ENCODERS, FADES,
    SPEEDS, TRANSITIONS, TRANSITION_SECONDS,
    CONSUMERS, active, normalize, syncClips, moveClip, clipWindow, timing, nearestBeat, outputSize, settingsKey, request, resultFromJob,
    isVideoSource, targets, policy, labels, ICON,
    menu: Object.freeze({type: TYPE, title: '视频合成', subtitle: '拼接片段 · 裁切 · 配乐', icon: ICON}),
  });
})();
