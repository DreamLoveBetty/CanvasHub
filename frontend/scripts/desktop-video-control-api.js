// Internal authenticated transport. Never sends arbitrary URL/path to the worker.
(function () {
  const json = (action, body) => api.json('/api/video_control/' + action, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  async function upload(blob, name) {
    if (!(blob instanceof Blob) || !blob.size || blob.size > 200 * 1024 * 1024) throw new Error('视频须小于 200 MB');
    const response = await api.request('/api/video_control/upload?name=' + encodeURIComponent(name || 'source.mp4'), { method:'POST', body:blob });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }
  function sourceUrl(value) {
    const url = new URL(String(value), window.location.href);
    // Generated videos use a basename; gallery videos include root/date/folder segments.
    // Both are served by the same authenticated, archive-root-confined /video/ route.
    const videoPath = /^\/video\/[^/]+(?:\/[^/]+)*$/.test(url.pathname);
    if (url.origin !== window.location.origin || url.username || url.password || !(videoPath
      || ['/api/video_control/artifact', '/api/video_control/source', '/api/topaz_video/artifact', '/api/topaz_video/source'].includes(url.pathname))) throw new Error('请导入本地视频，或连接画布生成的视频结果');
    return url.pathname + url.search;
  }
  let client;
  const getClient = () => client ||= window.DesktopTasks.createClient({
    domain: 'video_control', submit: body => json('submit', body),
    progress: id => json('job?id=' + encodeURIComponent(id)), cancel: id => json('cancel', { id }),
  });
  const tasks = Object.freeze({submit: (...args) => getClient().submit(...args), progress: (...args) => getClient().progress(...args),
    cancel: (...args) => getClient().cancel(...args), result: (...args) => getClient().result(...args)});
  const originalReceipt = command => (...args) => command(...args).then(receipt => receipt.raw);
  window.DesktopVideoControlAPI = Object.freeze({ upload, sourceUrl,
    blob: value => api.blob(sourceUrl(value)), tasks, submit: originalReceipt(tasks.submit),
    job: originalReceipt(tasks.progress), cancel: originalReceipt(tasks.cancel) });
})();
