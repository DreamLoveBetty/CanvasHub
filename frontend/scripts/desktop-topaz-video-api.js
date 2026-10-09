// Authenticated Topaz Video transport; all task state stays in its canvas controller.
(function () {
  const route = action => '/api/topaz_video/' + action;
  const json = (action, body) => api.json(route(action), body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  async function upload(blob, name) {
    if (!(blob instanceof Blob) || !blob.size || blob.size > 200 * 1024 * 1024)
      throw new Error('视频须小于 200 MB');
    const response = await api.request(route('upload') + '?name=' + encodeURIComponent(name || 'source.mp4'),
      {method: 'POST', body: blob});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
    return result;
  }
  function sourceUrl(value) {
    const raw = String(value || '').trim();
    if (/^data:video\/(?:mp4|webm|quicktime|x-matroska)(?:;[^,]*)?,/i.test(raw)) return raw;
    const url = new URL(raw, window.location.href);
    if (url.protocol === 'blob:' && url.origin === window.location.origin && !url.username && !url.password)
      return raw;
    const archived = /^\/video\/[^/]+(?:\/[^/]+)*$/.test(url.pathname);
    const local = ['/api/topaz_video/source', '/api/topaz_video/artifact',
      '/api/video_control/source', '/api/video_control/artifact'].includes(url.pathname);
    if (url.origin !== window.location.origin || url.username || url.password || !(archived || local))
      throw new Error('请导入本地视频，或连接画布视频节点');
    return url.pathname + url.search;
  }
  let client;
  const taskClient = () => client ||= window.DesktopTasks.createClient({
    domain: 'topaz_video', submit: body => json('submit', body),
    progress: id => json('job?id=' + encodeURIComponent(id)),
    cancel: id => json('cancel', {id}),
  });
  const tasks = Object.freeze({
    submit: (...args) => taskClient().submit(...args),
    progress: (...args) => taskClient().progress(...args),
    cancel: (...args) => taskClient().cancel(...args),
    result: (...args) => taskClient().result(...args),
  });
  const raw = command => (...args) => command(...args).then(receipt => receipt.raw);
  window.DesktopTopazVideoAPI = Object.freeze({
    status: () => json('status'), upload, sourceUrl,
    blob: value => api.blob(sourceUrl(value)), tasks,
    submit: raw(tasks.submit), job: raw(tasks.progress), cancel: raw(tasks.cancel),
  });
})();
