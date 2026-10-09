// Internal transport to the app's local audio worker, not an external Provider connection.
// Auth/cookies/errors remain owned by auth-api.js.
(function () {
  const json = (path, body) => api.json('/api/audio/' + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  async function upload(blob, name) {
    if (!(blob instanceof Blob) || !blob.size || blob.size > 100 * 1024 * 1024) throw new Error('音频大小须为 1 字节至 100 MB');
    const response = await api.request('/api/audio/upload?name=' + encodeURIComponent(name), { method: 'POST', body: blob });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }
  function artifactUrl(value) {
    const url = new URL(String(value), window.location.href);
    if (url.origin !== window.location.origin || url.pathname !== '/api/audio/artifact') {
      throw new Error('音频服务仅接受本机产物；外部音频请先下载并导入素材节点');
    }
    return url.pathname + url.search;
  }
  let client;
  const getClient = () => client ||= window.DesktopTasks.createClient({
    domain: 'music', submit: body => json('submit', body),
    progress: id => json('job?id=' + encodeURIComponent(id)), cancel: id => json('cancel', { id }),
  });
  const tasks = Object.freeze({submit: (...args) => getClient().submit(...args), progress: (...args) => getClient().progress(...args),
    cancel: (...args) => getClient().cancel(...args), result: (...args) => getClient().result(...args)});
  const originalReceipt = command => (...args) => command(...args).then(receipt => receipt.raw);
  window.DesktopMusicAPI = Object.freeze({
    tasks, submit: originalReceipt(tasks.submit),
    job: originalReceipt(tasks.progress), cancel: originalReceipt(tasks.cancel),
    score: body => json('score', body), upload,
    blob: url => api.blob(artifactUrl(url)), text: async url => (await api.blob(artifactUrl(url))).text(),
  });
})();
