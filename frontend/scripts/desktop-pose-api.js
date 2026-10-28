// Authenticated transport for the pose scene domain. Never sends paths or arbitrary URLs.
(function () {
  const ARTIFACT = /^\/api\/pose\/export\/artifact\?id=[a-f0-9]{32}$/;
  async function status() { return api.json('/api/pose/assets/status'); }
  // Mannequin GLB of a body preset, or of a recognised body (pose_capture domain, low mesh only).
  async function glb(lod = 'low', body = 'neutral') {
    if (!['low', 'mid'].includes(lod)) throw new Error('未知人偶精细度');
    const model = window.DesktopPoseModel, capture = model.captureBodyId(body);
    if (!capture && !model.isPresetBody(body)) throw new Error('未知人偶体型');
    const response = await api.request(capture ? '/api/pose_capture/body?id=' + capture : `/api/pose/glb?lod=${lod}&body=${body}`);
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try { message = (await response.json()).error || message; } catch (_error) { /* binary or empty body */ }
      throw new Error(message);
    }
    return response.arrayBuffer();
  }
  async function exportImage({image, pass, camera = '', scene = null}) {
    if (!String(image || '').startsWith('data:image/png;base64,')) throw new Error('导出图片必须为 PNG');
    const result = await api.json('/api/pose/export/image', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image, pass, camera, scene})});
    if (!ARTIFACT.test(String(result?.url || ''))) throw new Error('姿态导出返回无效地址');
    return result;
  }
  // Photo and video recognition (GEM-X lite). Media is uploaded as bytes; the server never fetches URLs.
  const capture = Object.freeze({
    status: () => api.json('/api/pose_capture/status'),
    async upload(blob, name = 'photo', kind = 'image') {
      const limit = kind === 'video' ? 200 : 20;
      if (!(blob instanceof Blob) || !blob.size || blob.size > limit * 1024 * 1024) throw new Error(`${kind === 'video' ? '视频' : '图片'}须小于 ${limit} MB`);
      const response = await api.request('/api/pose_capture/upload?name=' + encodeURIComponent(name), {method: 'POST', body: blob});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      return result;
    },
    submit: body => api.json('/api/pose_capture/submit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}),
    job: id => api.json('/api/pose_capture/job?id=' + encodeURIComponent(id)),
    // A video recognition's pose sequence (large; fetched once per job, not with every poll).
    result: id => api.json('/api/pose_capture/result?id=' + encodeURIComponent(id)),
    // Bytes of a connected image or video node: inline data or blob URLs locally, same-origin paths with auth.
    async mediaBlob(url) {
      const value = String(url || '');
      if (/^data:(image|video)\//.test(value) || value.startsWith('blob:')) return (await fetch(value)).blob();
      const parsed = new URL(value, window.location.href);
      if (parsed.origin !== window.location.origin) throw new Error('请先把外部图片导入画布再识别');
      return api.blob(parsed.pathname + parsed.search);
    },
    cancel: id => api.json('/api/pose_capture/cancel', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id})}),
  });
  // Pose video export: frames go up one by one in order, then the server encodes them with ffmpeg.
  const post = (url, body) => api.json(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const video = Object.freeze({
    start: body => post('/api/pose/export/video/start', body),
    async frame(id, index, blob) {
      const response = await api.request(`/api/pose/export/video/frame?id=${encodeURIComponent(id)}&index=${index}`, {method: 'POST', body: blob});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      return result;
    },
    finish: id => post('/api/pose/export/video/finish', {id}),
    cancel: id => post('/api/pose/export/video/cancel', {id}),
    job: id => api.json('/api/pose/export/video/job?id=' + encodeURIComponent(id)),
  });
  window.DesktopPoseAPI = Object.freeze({status, glb, exportImage, capture, video, isArtifactUrl: url => ARTIFACT.test(String(url || ''))});
})();
