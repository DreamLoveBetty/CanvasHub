// Authenticated 绘栾 transport. Provider Key never enters the browser.
(function () {
  const json = (path, body) => api.json('/api/cyimg/' + path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  async function upload(blob, filename) {
    if (!(blob instanceof Blob) || !blob.size || blob.size > 200 * 1024 * 1024) throw new Error('素材须小于 200 MB');
    const response = await api.request('/api/cyimg/upload?name=' + encodeURIComponent(filename || 'source'), {
      method:'POST', headers:{'Content-Type':blob.type || 'application/octet-stream'}, body:blob
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result.upload_token;
  }
  async function sourceBlob(value, kind='image') {
    const raw = String(value || '').trim();
    if (!raw) throw new Error('素材地址为空');
    if (raw.startsWith('data:') || raw.startsWith('blob:')) return api.blob(raw);
    const url = new URL(raw, location.href);
    if (url.origin === location.origin) return api.blob(url.pathname + url.search);
    if (kind === 'image') return (await DesktopApi.importImageUrl(url.href)).blob;
    throw new Error('外部视频或音频请先导入到画布');
  }
  let client;
  const getClient=()=>client ||= DesktopTasks.createClient({domain:'cyimg',submit:body=>json('submit',body),
    progress:id=>DesktopApi.getStatus(id),cancel:id=>api.json(`/api/tasks/${encodeURIComponent(id)}/cancel`,{method:'POST'})});
  const tasks=Object.freeze({
    submit: (...args)=>getClient().submit(...args),
    progress: (...args)=>getClient().progress(...args),
    cancel: (...args)=>getClient().cancel(...args),
    result: (...args)=>getClient().result(...args)
  });
  window.DesktopCyimgAPI = Object.freeze({catalog:()=>json('catalog'), submit:body=>json('submit',body),
    job:id=>DesktopApi.getStatus(id), upload, sourceBlob, tasks});
})();
