// Speech-recognition (ASR) environment transport (/api/asr/*): status and the user-triggered prepare.
// Recognition itself runs through the video-edit domain (DesktopVideoEditAPI.compose.transcribe).
(function () {
  const preparation = raw => ({status: String(raw?.status || 'idle'), stage: String(raw?.stage || ''),
    message: String(raw?.message || ''), downloaded: Number(raw?.downloaded || 0), total: Number(raw?.total || 0)});

  const status = () => api.json('/api/asr/status').then(data => ({
    ready: Boolean(data.ready), engine: String(data.engine || ''),
    reasons: Array.isArray(data.reasons) ? data.reasons.map(String) : [],
    preparedAt: Number(data.prepared_at || 0), downloadBytes: Number(data.download_bytes || 0),
    maxSeconds: Number(data.max_seconds || 0), preparation: preparation(data.preparation),
  }));

  const prepare = () => api.json('/api/asr/prepare', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
    .then(data => ({preparation: preparation(data.preparation), alreadyRunning: Boolean(data.already_running)}));

  window.DesktopAsrAPI = Object.freeze({status, prepare});
})();
