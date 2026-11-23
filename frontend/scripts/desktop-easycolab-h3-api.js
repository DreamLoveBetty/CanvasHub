// Authenticated EasyColab MiniMax-H3 transport. EasyColab credentials stay server-side.
(function () {
  const json = (path, body) => api.json('/api/easycolab_h3/' + path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });

  async function upload(blob, filename) {
    if (!(blob instanceof Blob) || !blob.size || blob.size > 200 * 1024 * 1024) {
      throw new Error('素材须小于 200 MB');
    }
    const response = await api.request('/api/easycolab_h3/upload?name=' + encodeURIComponent(filename || 'source'), {
      method: 'POST',
      headers: { 'Content-Type': blob.type || 'application/octet-stream' },
      body: blob
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result.upload_token;
  }

  async function sourceBlob(value, kind = 'image') {
    const raw = String(value || '').trim();
    if (!raw) throw new Error('素材地址为空');
    if (raw.startsWith('data:') || raw.startsWith('blob:')) return api.blob(raw);
    const url = new URL(raw, location.href);
    if (url.origin === location.origin) return api.blob(url.pathname + url.search);
    if (kind === 'image') return (await DesktopApi.importImageUrl(url.href)).blob;
    throw new Error('外部音频请先导入到画布');
  }

  let client;
  const getClient = () => client ||= DesktopTasks.createClient({
    domain: 'easycolab_h3',
    submit: body => json('submit', body),
    progress: id => DesktopApi.getStatus(id),
    cancel: id => api.json(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
  });

  const tasks = Object.freeze({
    submit: (...args) => getClient().submit(...args),
    progress: (...args) => getClient().progress(...args),
    cancel: (...args) => getClient().cancel(...args),
    result: (...args) => getClient().result(...args)
  });

  window.DesktopEasyColabH3API = Object.freeze({
    catalog: () => json('catalog'),
    loadModel: modelId => json('load_model', { model_id: modelId }),
    submit: body => json('submit', body),
    job: id => DesktopApi.getStatus(id),
    upload,
    sourceBlob,
    tasks
  });
})();
