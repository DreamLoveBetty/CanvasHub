// Shared descriptive data and authenticated transport. No canvas or gallery ownership.
(function () {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function create({getClient}) {
    const records = new Map(), listeners = new Set();
    const changed = () => listeners.forEach(listener => listener());
    const remember = item => { if (item?.asset_id) records.set(item.asset_id, item); return item; };
    const get = (action, params = {}) => getClient().json('/api/lora/' + action + '?' + new URLSearchParams(params));
    const post = (action, body) => getClient().json('/api/lora/' + action, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body || {})});
    async function mutation(action, body) {
      const result = await post(action, body); remember(result.item); changed(); return result;
    }
    return Object.freeze({
      async list(params = {}) { const result = await get('list', params); (result.items || []).forEach(remember); return result; },
      async detail(id) { return remember((await get('detail', {asset_id:id})).item); },
      peek:id => records.get(id),
      subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
      changed,
      update:(item, changes, resetFields = []) => mutation('update', {asset_id:item.asset_id, revision:item.revision, changes, reset_fields:resetFields}),
      bind:(id, url) => mutation('bind-source', {asset_id:id, url}),
      sync:ids => post('sync', {asset_ids:ids}),
      syncState:() => get('sync-state'),
      settings:changes => changes === undefined ? get('settings') : post('settings', changes),
      clearCache:() => mutation('clear-cache'),
      deleteWeight:(id, engine) => mutation('delete-weight', {asset_id:id, engine}),
      deletePreview:(id, previewId) => mutation('preview-delete', {asset_id:id, preview_id:previewId}),
      async upload(id, blob) {
        if (!(blob instanceof Blob) || !blob.size || blob.size > 16 * 1024**2) throw new Error('示例图须为 16 MB 以内的图片');
        const response = await getClient().request('/api/lora/preview-import?asset_id=' + encodeURIComponent(id), {method:'POST', headers:{'Content-Type':blob.type || 'application/octet-stream'}, body:blob});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '示例图保存失败');
        remember(result.item); changed(); return result;
      },
      async imageBlob(value) {
        const url = new URL(value, location.href);
        if (url.origin !== location.origin) throw new Error('只能从本地图片资产复制示例图');
        return getClient().blob(url.pathname + url.search);
      },
      mediaUrl:value => window.miniappMediaUrl?.(value) || value,
    });
  }
  // Preserve phrase spelling; do not infer trigger words from filename/training tags.
  function parseWords(value) { return [...new Set(String(value || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean))]; }
  function appendWords(text, words) {
    const current = String(text || '');
    const normalized = [...new Set(words.map(x => String(x).trim()).filter(Boolean))];
    const hasPhrase = phrase => {
      let start = 0, index;
      const wordChar = char => Boolean(char && /[\p{L}\p{N}_]/u.test(char));
      while ((index = current.indexOf(phrase, start)) !== -1) {
        if (!(wordChar(phrase[0]) && wordChar(current[index - 1])) &&
            !(wordChar(phrase.at(-1)) && wordChar(current[index + phrase.length]))) return true;
        start = index + 1;
      }
      return false;
    };
    const added = normalized.filter(word => !hasPhrase(word));
    return {added, suffix:added.length ? (current.trim() ? '\n' : '') + added.join(', ') : ''};
  }
  window.DesktopLoRAData = Object.freeze({create, esc, parseWords, appendWords});
})();
