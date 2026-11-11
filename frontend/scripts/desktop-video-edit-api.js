// Authenticated video-edit transport (/api/video_edit/*). No canvas state, DOM or polling.
// Requests carry only a served media URL; snake_case stays on this side of the boundary.
(function () {
  const route = action => '/api/video_edit/' + action;
  const json = (action, body) => api.json(route(action), body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const SOURCE_PATHS = ['/api/topaz_video/source', '/api/topaz_video/artifact',
    '/api/video_control/source', '/api/video_control/artifact'];

  // The same-origin path + query of a video the backend can open, or '' (local blobs, other hosts).
  function sourceUrl(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    let url;
    try { url = new URL(raw, window.location.href); } catch (_error) { return ''; }
    if (url.origin !== window.location.origin || url.username || url.password) return '';
    const archived = /^\/video\/[^/]+(?:\/[^/]+)*$/.test(url.pathname);
    if (!archived && !SOURCE_PATHS.includes(url.pathname)) return '';
    url.searchParams.delete('miniappAuth');
    return url.pathname + url.search;
  }

  function required(value) {
    const url = sourceUrl(value);
    if (!url) throw new Error('该视频来源暂不支持剪辑，请先导入或保存到作品库');
    return url;
  }

  const probe = value => json('probe?source_url=' + encodeURIComponent(required(value))).then(info => ({
    width: Number(info.width || 0), height: Number(info.height || 0), fps: Number(info.fps || 0),
    durationSeconds: Number(info.duration_seconds || 0), frameCount: Number(info.frame_count || 0),
    frameTimes: Array.isArray(info.frame_times) ? info.frame_times.map(Number) : [],
    hasAudio: Boolean(info.has_audio), audioCodec: String(info.audio?.codec || ''),
  }));

  async function previewFrame(value, frame, width = 160) {
    const query = new URLSearchParams({source_url: required(value), frame: String(frame), width: String(width)});
    return api.blob(route('preview_frame') + '?' + query);
  }

  // Timeline thumbnails: one JPEG row of `tiles` frames picked evenly by frame index.
  async function filmstrip(value, tiles) {
    const query = new URLSearchParams({source_url: required(value), tiles: String(tiles)});
    return api.blob(route('filmstrip') + '?' + query);
  }

  // A rendered output's `.json` recipe, translated to the canvas' camelCase shape.
  async function composeRecipe(value) {
    const data = await json('compose_recipe?source_url=' + encodeURIComponent(required(value)));
    const spec = data.spec || {}, result = data.result || {}, music = spec.music, subtitles = spec.subtitles;
    return {
      title: String(spec.title || ''), clipVolume: Number(spec.clip_volume ?? 1), output: {...(spec.output || {})},
      clips: (spec.clips || []).map(clip => ({sourceUrl: String(clip.source_url || ''), sourceName: String(clip.source_name || ''),
        startFrame: Number(clip.start_frame || 0), endFrame: Number(clip.end_frame ?? -1), audio: clip.audio !== false,
        speed: Number(clip.speed || 1), transition: {type: String(clip.transition?.type || 'none'),
          duration: Number(clip.transition?.duration || 0.5)}})),
      music: music ? {sourceUrl: String(music.source_url || ''), assetId: String(music.asset_id || ''),
        sourceName: String(music.source_name || ''), volume: Number(music.volume ?? 0.8),
        fadeIn: Number(music.fade_in || 0), fadeOut: Number(music.fade_out ?? 1.5)} : null,
      // Cue and style fields are single words, the same on both sides.
      subtitles: subtitles ? {cues: (subtitles.cues || []).map(cue => ({start: Number(cue.start || 0), end: Number(cue.end || 0),
        text: String(cue.text || '')})), style: {...(subtitles.style || {})}} : null,
      result: {url: String(result.url || ''), filename: String(result.filename || ''), fileSize: Number(result.file_size || 0),
        durationSeconds: Number(result.duration_seconds || 0), width: Number(result.width || 0),
        height: Number(result.height || 0), fps: Number(result.fps || 0)},
    };
  }

  // Compose renders are their own durable jobs; job/cancel dispatch by id on the backend.
  let composeClient;
  const composeCalls = {
    submit: body => json('compose', body),
    job: id => json('job?id=' + encodeURIComponent(id)),
    cancel: id => json('cancel', {id}),
  };
  const compose = Object.freeze({
    ...composeCalls,
    check: body => json('compose_check', body),
    // Automatic subtitles: {recipe, script} -> an in-memory job whose result carries draft cues.
    transcribe: body => json('transcribe', body),
    // A transcribe job's result as draft cues; seconds are already on the output timeline.
    transcribeResult: job => {
      const result = job?.result || {};
      return {cues: (Array.isArray(result.cues) ? result.cues : []).map(cue => ({start: Number(cue.start || 0),
        end: Number(cue.end || 0), text: String(cue.text || '')})), speech: Boolean(result.speech),
        language: String(result.language || '')};
    },
    recipe: composeRecipe,
    // Fonts burned-in subtitles can use: [{file, label, url}] plus the default file.
    subtitleFonts: () => json('subtitle_fonts').then(data => ({
      fonts: (Array.isArray(data.fonts) ? data.fonts : []).map(font => ({file: String(font.file || ''),
        label: String(font.label || font.file || ''), url: String(font.url || '')})).filter(font => font.file),
      defaultFile: String(data.default || ''),
    })),
    tasks: () => composeClient ||= window.DesktopTasks.createClient({
      domain: 'video_compose', submit: composeCalls.submit, progress: composeCalls.job, cancel: composeCalls.cancel,
      artifacts: () => [],
    }),
  });

  let client;
  const taskClient = () => client ||= window.DesktopTasks.createClient({
    domain: 'video_edit', submit: body => json('submit', body),
    progress: id => json('job?id=' + encodeURIComponent(id)),
    cancel: id => json('cancel', {id}),
    artifacts: () => [],
  });
  const tasks = Object.freeze({
    submit: (...args) => taskClient().submit(...args),
    progress: (...args) => taskClient().progress(...args),
    cancel: (...args) => taskClient().cancel(...args),
    result: (...args) => taskClient().result(...args),
  });
  const submit = (kind, value, extra = {}) => tasks.submit({
    kind, source_url: required(value), source_name: String(extra.sourceName || '').slice(0, 160),
    ...(kind === 'frames' ? {frames: extra.frames} : {}),
  });

  window.DesktopVideoEditAPI = Object.freeze({
    status: () => json('status'), sourceUrl, probe, previewFrame, filmstrip, compose, submit, tasks,
    progress: id => tasks.progress(id), cancel: id => tasks.cancel(id),
  });
})();
