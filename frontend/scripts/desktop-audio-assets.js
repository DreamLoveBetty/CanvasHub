// Audio binaries live outside canvas JSON. No Provider, auth or canvas dependency.
(function () {
  const MAX_FILE_BYTES = 100 * 1024 * 1024;
  const DB_NAME = 'canvashub_audio_assets_v1';
  const STORE = 'assets';
  let databasePromise = null;

  function openDatabase() {
    if (!databasePromise) {
      databasePromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' });
        request.onsuccess = () => {
          const db = request.result;
          db.onversionchange = () => { db.close(); databasePromise = null; };
          resolve(db);
        };
        request.onerror = () => reject(new Error('音频本地存储不可用，请检查浏览器存储空间'));
        request.onblocked = () => reject(new Error('音频存储正在更新，请关闭其他画布页面后重试'));
      }).catch(error => { databasePromise = null; throw error; });
    }
    return databasePromise;
  }

  async function transaction(mode, action) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = action(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = tx.onabort = () => reject(new Error('音频保存失败，请检查本地存储空间'));
    });
  }

  async function put(blob) {
    if (!(blob instanceof Blob) || !blob.size || blob.size > MAX_FILE_BYTES) {
      throw new Error('请选择不超过 100 MB 的音频文件');
    }
    if (!/^audio\/[a-z0-9.+-]+$/i.test(blob.type)) throw new Error('音频文件需要有效的 audio MIME 类型');
    const id = `audio-${crypto.randomUUID()}`;
    await transaction('readwrite', store => store.put({ id, blob, createdAt: Date.now() }));
    return id;
  }

  async function get(id) {
    if (!id) return null;
    const record = await transaction('readonly', store => store.get(id));
    return record?.blob instanceof Blob ? record.blob : null;
  }

  function remove(id) {
    return transaction('readwrite', store => store.delete(id));
  }

  function toDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error('音频文件读取失败'));
      reader.readAsDataURL(blob);
    });
  }

  function fromDataUrl(value) {
    const match = /^data:(audio\/[a-z0-9.+-]+);base64,([a-z0-9+/]*={0,2})$/i.exec(String(value || ''));
    if (!match || !match[2].length || match[2].length > Math.ceil(MAX_FILE_BYTES / 3) * 4) {
      throw new Error('工作流中的音频数据无效或超过 100 MB');
    }
    const binary = atob(match[2]);
    if (!binary.length || binary.length > MAX_FILE_BYTES) throw new Error('音频文件大小无效');
    return new Blob([Uint8Array.from(binary, c => c.charCodeAt(0))], { type: match[1].toLowerCase() });
  }

  // Called only by the existing async file-save flow; sync snapshots stay lightweight.
  async function embedWorkflowAssets(payload) {
    const nodes = Object.values(payload?.state?.canvas?.nodes || {});
    for (const node of nodes) {
      if (node.type !== 'audio' || node.audioData || !node.audioAssetId) continue;
      const blob = await get(node.audioAssetId);
      if (!blob) throw new Error(`“${node.mediaName || '音频'}”的本地文件已丢失，请重新导入后保存工作流`);
      node.audioData = await toDataUrl(blob);
      node.audioAssetId = '';
    }
    return payload;
  }

  window.DesktopAudioAssets = Object.freeze({ MAX_FILE_BYTES, put, get, remove, toDataUrl, fromDataUrl, embedWorkflowAssets });
})();
