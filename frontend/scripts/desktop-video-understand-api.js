// Authenticated transport for WeMM-Video understanding (/api/video_understand/* + /api/video/upload).
(function () {
  const json = (action, body) => api.json('/api/video_understand/' + action, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  const preparation = raw => ({
    status: String(raw?.status || 'idle'),
    stage: String(raw?.stage || ''),
    message: String(raw?.message || ''),
    downloaded: Number(raw?.downloaded || 0),
    total: Number(raw?.total || 0),
  });

  function status() {
    return api.json('/api/video_understand/status').then(data => ({
      ok: Boolean(data?.ok),
      engine: String(data?.engine || ''),
      modelVariant: String(data?.model_variant || ''),
      ready: Boolean(data?.ready),
      reasons: Array.isArray(data?.reasons) ? data.reasons.map(String) : [],
      preparedAt: Number(data?.prepared_at || 0),
      downloadBytes: Number(data?.download_bytes || 0),
      preparation: preparation(data?.preparation),
      modes: data?.modes && typeof data.modes === 'object' ? data.modes : {},
    }));
  }

  function prepare() {
    return api.json('/api/video_understand/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }).then(data => ({
      preparation: preparation(data?.preparation),
      alreadyRunning: Boolean(data?.already_running),
    }));
  }

  function sourceUrl(value) {
    const url = new URL(String(value), window.location.href);
    const videoPath = /^\/video\/[^/]+(?:\/[^/]+)*$/.test(url.pathname);
    const sourcePaths = [
      '/api/video_control/artifact',
      '/api/video_control/source',
      ...(window.DesktopLocalExtensions?.videoSourcePaths?.() || []),
    ];
    if (
      url.origin !== window.location.origin
      || url.username
      || url.password
      || !(videoPath || sourcePaths.includes(url.pathname))
    ) {
      throw new Error('请导入本地视频，或连接画布已有的视频节点');
    }
    return url.pathname + url.search;
  }

  async function uploadVideo(file, name) {
    if (window.DesktopApi?.uploadVideo) {
      return window.DesktopApi.uploadVideo(file, name);
    }
    if (!(file instanceof Blob) || !file.size) throw new Error('视频文件为空');
    if (file.size > 200 * 1024 * 1024) throw new Error('视频须小于 200 MB');
    const response = await api.request('/api/video/upload?name=' + encodeURIComponent(name || file.name || 'video.mp4'), {
      method: 'POST',
      body: file,
    });
    let payload = {};
    try { payload = await response.json(); } catch (error) {}
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    return {
      mediaUrl: String(payload.url || ''),
      mediaName: String(payload.name || ''),
      mimeType: String(payload.mime_type || 'video/mp4'),
      mediaWidth: Number(payload.width || 0),
      mediaHeight: Number(payload.height || 0),
      fps: Number(payload.fps || 0),
      durationSeconds: Number(payload.duration_seconds || 0),
      fileSize: Number(payload.file_size || 0),
    };
  }

  let client;
  const getClient = () => client ||= window.DesktopTasks.createClient({
    domain: 'video_understand',
    submit: body => json('submit', body),
    progress: id => json('job?id=' + encodeURIComponent(id)),
    cancel: id => json('cancel', { id }),
  });

  const tasks = Object.freeze({
    submit: (...args) => getClient().submit(...args),
    progress: (...args) => getClient().progress(...args),
    cancel: (...args) => getClient().cancel(...args),
    result: (...args) => getClient().result(...args),
  });

  const originalReceipt = command => (...args) => command(...args).then(receipt => receipt.raw);

  window.DesktopVideoUnderstandAPI = Object.freeze({
    status,
    prepare,
    sourceUrl,
    uploadVideo,
    tasks,
    submit: originalReceipt(tasks.submit),
    job: originalReceipt(tasks.progress),
    cancel: originalReceipt(tasks.cancel),
  });
})();
