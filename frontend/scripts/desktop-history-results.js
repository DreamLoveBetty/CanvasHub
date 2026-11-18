// Pure helpers for recent-history file membership after an asset is deleted.
// No DOM, API or prompt work. Used by desktop-history.js and official tests.
(function () {
  function fileKey(name) {
    const raw = String(name || '').trim();
    if (!raw) return '';
    const path = raw.split('?')[0].split('#')[0].replace(/\\/g, '/');
    const base = path.split('/').pop() || '';
    try {
      return decodeURIComponent(base).toLowerCase();
    } catch (_error) {
      return base.toLowerCase();
    }
  }

  function fileKeysFrom(value) {
    const keys = new Set();
    const add = item => {
      if (Array.isArray(item)) {
        item.forEach(add);
        return;
      }
      const key = fileKey(item);
      if (key) keys.add(key);
    };
    add(value);
    return keys;
  }

  function recordedHistoryFiles(item) {
    const files = Array.isArray(item?.result_files) && item.result_files.length
      ? item.result_files
      : (Array.isArray(item?.output_files) && item.output_files.length ? item.output_files : []);
    const primary = item?.result_file || item?.output_file || item?.primaryFile || '';
    const paths = Array.isArray(item?.image_paths) ? item.image_paths : (Array.isArray(item?.imagePaths) ? item.imagePaths : []);
    const names = files.length ? files : (primary ? [primary] : []);
    return { files: names, primary, paths };
  }

  function applyRemovedHistoryFiles(item, removedKeys) {
    const removed = removedKeys instanceof Set ? removedKeys : fileKeysFrom(removedKeys);
    const recorded = recordedHistoryFiles(item);
    if (!recorded.files.length && !recorded.paths.length) return item;
    const keepName = name => !removed.has(fileKey(name));
    const files = recorded.files.filter(keepName);
    const paths = recorded.paths.filter(keepName);
    const primary = keepName(recorded.primary) ? recorded.primary : (files[0] || '');
    const missing = recorded.files.length > 0 && files.length === 0;
    if (files.length === recorded.files.length && paths.length === recorded.paths.length && primary === recorded.primary && !missing) {
      return item;
    }
    return {
      ...item,
      result_files: files,
      output_files: files,
      result_file: primary,
      output_file: primary,
      image_paths: paths,
      image_count: files.length,
      missing_result_files: missing || !!item.missing_result_files
    };
  }

  function applyRemovedHistoryItems(items, removedKeys) {
    const removed = removedKeys instanceof Set ? removedKeys : fileKeysFrom(removedKeys);
    if (!removed.size) return Array.isArray(items) ? items : [];
    return (Array.isArray(items) ? items : []).map(item => applyRemovedHistoryFiles(item, removed));
  }

  const VIDEO_FILE_RE = /\.(mp4|webm|mov|m4v)(?:$|[?#])/i;

  function isVideoHistoryItem(item) {
    const type = String(item?.type || '').toLowerCase();
    if (type === 'minimax-h3-video' || type.includes('h3-video') || type === 'cyimg-video') return true;
    const params = item?.params && typeof item.params === 'object' ? item.params : {};
    if (type === 'comfy' && String(params.comfy_output_kind || '').toLowerCase() === 'video') return true;
    if (Array.isArray(item?.video_paths) && item.video_paths.length) return true;
    if (item?.video_path) return true;
    const recorded = recordedHistoryFiles(item);
    const names = recorded.files.length ? recorded.files : (recorded.primary ? [recorded.primary] : []);
    return names.length > 0 && names.every(name => VIDEO_FILE_RE.test(String(name || '')));
  }

  function shouldShowHistoryRow(item, { isFileItem = false, isVideoItem = false, isInFlight = false, hasVisibleImage = false } = {}) {
    if (isFileItem || isVideoItem || isVideoHistoryItem(item)) return false;
    if (hasVisibleImage) return true;
    if (item?.missing_result_files) return true;
    const recorded = recordedHistoryFiles(item);
    if (recorded.files.length === 0 && recorded.paths.length === 0 && isInFlight) return true;
    return false;
  }

  window.DesktopHistoryResults = Object.freeze({
    fileKey,
    fileKeysFrom,
    recordedHistoryFiles,
    applyRemovedHistoryFiles,
    applyRemovedHistoryItems,
    isVideoHistoryItem,
    shouldShowHistoryRow
  });
})();
