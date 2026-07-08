// History loading, filters, and classic history rendering
  const HISTORY_INITIAL_PAGE_SIZE = 30;
  const HISTORY_BACKGROUND_PAGE_SIZE = 60;
  const HISTORY_BACKGROUND_DELAY_MS = 1800;
  const HISTORY_START_DELAY_MS = 350;
  let historyLoadPromise = null;
  let historyLoadToken = 0;
  let historyLoadTimer = null;

  function getHistoryMergeKey(item) {
    if (item?.task_id) return `task:${item.task_id}`;
    return `time:${Number(item?.timestamp || 0)}:${item?.type || 'unknown'}`;
  }

  function isPendingHistoryRecord(item) {
    if (item?.__pending) return true;
    const status = String(item?.status || '').toLowerCase();
    const inFlightStatuses = (typeof IN_FLIGHT_TASK_STATUSES !== 'undefined' && Array.isArray(IN_FLIGHT_TASK_STATUSES))
      ? IN_FLIGHT_TASK_STATUSES
      : ['queued', 'preparing', 'processing', 'fallback_running'];
    return !item?.output_file && inFlightStatuses.includes(status);
  }

  function mergeHistoryPageRecords(existingItems, nextItems) {
    const byKey = new Map();

    [...(existingItems || []), ...(nextItems || [])].forEach((item) => {
      const key = getHistoryMergeKey(item);
      const current = byKey.get(key);
      if (!current) {
        byKey.set(key, item);
        return;
      }

      if (isPendingHistoryRecord(current) && !isPendingHistoryRecord(item)) {
        byKey.set(key, item);
      }
    });

    return [...byKey.values()];
  }

  function applyHistoryRecords(items) {
    historyRecords = Array.isArray(items) ? items : [];
    syncHistoryFilterOptions();
    renderHistoryList();
    renderCinematicHistoryStream();
  }

  function addPendingHistoryRecord(options = {}) {
    const taskId = String(options.taskId || options.task_id || '').trim();
    if (!taskId) return null;

    const pendingRecord = {
      task_id: taskId,
      timestamp: Math.floor(Date.now() / 1000),
      type: options.type || 'google',
      status: 'pending',
      prompt: options.prompt || '',
      params: options.params || {},
      error: '',
      __pending: true,
      __pendingText: options.statusText || '任务已提交，正在生成中'
    };

    historyRecords = mergeHistoryPageRecords(historyRecords, [pendingRecord]);
    syncHistoryFilterOptions();
    renderHistoryList();
    renderCinematicHistoryStream();
    return pendingRecord;
  }

  function clearPendingHistoryRecord(taskId) {
    const id = String(taskId || '').trim();
    if (!id) return;
    const nextRecords = historyRecords.filter(item => !(isPendingHistoryRecord(item) && item.task_id === id));
    if (nextRecords.length === historyRecords.length) return;
    historyRecords = nextRecords;
    syncHistoryFilterOptions();
    renderHistoryList();
    renderCinematicHistoryStream();
  }

  function findHistoryItemByIdentity(taskId, timestamp) {
    return historyRecords.find((item) => item?.task_id === taskId && Number(item?.timestamp || 0) === Number(timestamp || 0)) || null;
  }

  function isHistoryAssetMissing(item) {
    return !!item?.__assetMissing;
  }

  function markHistoryAssetMissing(item) {
    if (!item) return;
    item.__assetMissing = true;
  }

  function clearHistoryAssetMissing(item) {
    if (!item) return;
    delete item.__assetMissing;
  }

  function markHistoryAssetMissingByIdentity(taskId, timestamp) {
    const item = findHistoryItemByIdentity(taskId, timestamp);
    if (item) markHistoryAssetMissing(item);
    return item;
  }

  function clearHistoryAssetMissingByIdentity(taskId, timestamp) {
    const item = findHistoryItemByIdentity(taskId, timestamp);
    if (item) clearHistoryAssetMissing(item);
    return item;
  }

  function getHistoryAssetMissingText(item) {
    if (!item?.output_file) return '无可用图片';
    return '文件已丢失';
  }

  function handleHistoryThumbError(img, taskId, timestamp) {
    if (!img) return;
    if (img.dataset.fallback && img.dataset.fallback !== img.src) {
      img.src = img.dataset.fallback;
      img.dataset.fallback = '';
      return;
    }

    const item = markHistoryAssetMissingByIdentity(taskId, timestamp);
    const wrap = img.parentElement;
    img.style.display = 'none';
    if (wrap) {
      wrap.classList.add('is-empty', 'is-missing');
      if (!wrap.querySelector('.history-missing-copy')) {
        const note = document.createElement('span');
        note.className = 'history-missing-copy';
        note.textContent = getHistoryAssetMissingText(item);
        wrap.appendChild(note);
      }
    }
  }

  function handleHistoryThumbLoad(img, taskId, timestamp) {
    if (!img) return;
    clearHistoryAssetMissingByIdentity(taskId, timestamp);
    const wrap = img.parentElement;
    if (wrap) {
      wrap.classList.remove('is-empty', 'is-missing');
      wrap.querySelector('.history-missing-copy')?.remove();
    }
  }

  function loadHistory(options = {}) {
    const force = !!options.force;
    if (historyLoadPromise && !force) return historyLoadPromise;

    const token = ++historyLoadToken;
    setHistoryListMessage('加载中...');
    if (!historyRecords.length) {
      setCinematicHistoryMessage('打开创作台...', '历史记录在后台同步，你可以先开始创作。');
    }

    let loadedRecords = historyRecords.filter(isPendingHistoryRecord);
    let offset = 0;

    const waitForAuth = () => {
      if (typeof waitForMiniappAuthReady === 'function') {
        return waitForMiniappAuthReady().then((ok) => {
          if (ok) return true;
          setHistoryListMessage('请先登录', 'error');
          setCinematicHistoryMessage('需要先登录', '输入访问密码后会自动同步创作记录。');
          return false;
        });
      }
      return Promise.resolve(true);
    };

    const loadPage = (limit, pageOffset) => api.json(`/api/history?limit=${limit}&offset=${pageOffset}`)
      .then(data => (Array.isArray(data.history) ? data.history : []));

    const loadRemainingPages = (nextOffset) => {
      loadPage(HISTORY_BACKGROUND_PAGE_SIZE, nextOffset)
        .then((pageItems) => {
          if (token !== historyLoadToken) return;
          if (!pageItems.length) return;

          loadedRecords = mergeHistoryPageRecords(loadedRecords, pageItems);
          applyHistoryRecords(loadedRecords);

          if (pageItems.length >= HISTORY_BACKGROUND_PAGE_SIZE) {
            window.setTimeout(() => loadRemainingPages(nextOffset + pageItems.length), HISTORY_BACKGROUND_DELAY_MS);
          }
        })
        .catch(() => {
          if (token === historyLoadToken && !historyRecords.length) {
            setHistoryListMessage('加载失败', 'error');
            setCinematicHistoryMessage('创作暂时没加载出来', '稍后再试，或者先在下面继续创作。');
          }
        });
    };

    historyLoadPromise = waitForAuth()
      .then((ok) => {
        if (!ok || token !== historyLoadToken) return [];
        return loadPage(HISTORY_INITIAL_PAGE_SIZE, offset);
      })
      .then((items) => {
        if (token !== historyLoadToken) return historyRecords;
        if (!items.length && typeof isMiniappAuthReady === 'function' && !isMiniappAuthReady()) {
          return historyRecords;
        }
        loadedRecords = mergeHistoryPageRecords(loadedRecords, items);
        applyHistoryRecords(loadedRecords);
        if (items.length >= HISTORY_INITIAL_PAGE_SIZE) {
          window.setTimeout(() => loadRemainingPages(items.length), HISTORY_BACKGROUND_DELAY_MS);
        }
        return historyRecords;
      })
      .catch(() => {
        setHistoryListMessage('加载失败', 'error');
        setCinematicHistoryMessage('创作暂时没加载出来', '稍后再试，或者先在下面继续创作。');
        throw new Error('history_load_failed');
      })
      .finally(() => {
        if (token === historyLoadToken) {
          historyLoadPromise = null;
        }
      });

    return historyLoadPromise;
  }

  function scheduleHistoryLoad(options = {}) {
    if (historyLoadTimer) window.clearTimeout(historyLoadTimer);
    if (!historyRecords.length) {
      setHistoryListMessage('加载中...');
      setCinematicHistoryMessage('可以开始创作', '历史记录会在后台同步，不会阻塞当前输入。');
    }
    historyLoadTimer = window.setTimeout(() => {
      historyLoadTimer = null;
      loadHistory(options).catch(() => {});
    }, HISTORY_START_DELAY_MS);
  }

  function onHistoryFilterChange() {
    historyFilterState.type = document.getElementById('historyTypeFilter')?.value || 'all';
    historyFilterState.status = document.getElementById('historyStatusFilter')?.value || 'all';
    historyFilterState.time = document.getElementById('historyTimeFilter')?.value || 'all';
    historyFilterState.keyword = (document.getElementById('historySearchInput')?.value || '').trim().toLowerCase();
    historyFilterState.ratio = document.getElementById('historyRatioFilter')?.value || 'all';
    historyFilterState.style = document.getElementById('historyStyleFilter')?.value || 'all';
    historyFilterState.resolution = document.getElementById('historyResolutionFilter')?.value || 'all';
    renderHistoryList();
  }

  function resetHistoryFilters() {
    const defaults = {
      historyTypeFilter: 'all',
      historyStatusFilter: 'all',
      historyTimeFilter: 'all',
      historyRatioFilter: 'all',
      historyStyleFilter: 'all',
      historyResolutionFilter: 'all'
    };

    Object.entries(defaults).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.value = val;
    });

    const search = document.getElementById('historySearchInput');
    if (search) search.value = '';

    onHistoryFilterChange();
  }

  function toggleHistoryAdvanced() {
    historyAdvancedOpen = !historyAdvancedOpen;
    const adv = document.getElementById('historyAdvancedFilters');
    if (adv) adv.style.display = historyAdvancedOpen ? 'grid' : 'none';
  }

  function syncHistoryFilterOptions() {
    const ratios = new Set();
    const styles = new Set();
    const resolutions = new Set();

    historyRecords.forEach(item => {
      const p = item?.params || {};
      if (p.ratio) ratios.add(String(p.ratio));
      if (p.style) styles.add(String(p.style));
      if (p.resolution) resolutions.add(String(p.resolution));
    });

    fillSelectOptions('historyRatioFilter', '比例', [...ratios].sort());
    fillSelectOptions('historyStyleFilter', '风格', [...styles].sort());
    fillSelectOptions('historyResolutionFilter', '分辨率', [...resolutions].sort());
  }

  function fillSelectOptions(selectId, label, values) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    const current = sel.value || 'all';
    sel.innerHTML = `<option value="all">${label}: 全部</option>`;
    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
    sel.value = values.includes(current) || current === 'all' ? current : 'all';
  }

  function matchTimeRange(ts, range) {
    if (range === 'all') return true;
    const now = Date.now();
    const t = (ts || 0) * 1000;
    if (range === 'today') {
      const d = new Date(t);
      const n = new Date();
      return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
    }
    if (range === '7d') return now - t <= 7 * 24 * 3600 * 1000;
    if (range === '30d') return now - t <= 30 * 24 * 3600 * 1000;
    return true;
  }

  function applyHistoryFilters(items) {
    return items.filter(item => {
      const params = item?.params || {};
      if (historyFilterState.type !== 'all' && item.type !== historyFilterState.type) return false;
      if (historyFilterState.status !== 'all' && item.status !== historyFilterState.status) return false;
      if (!matchTimeRange(item.timestamp, historyFilterState.time)) return false;
      if (historyFilterState.ratio !== 'all' && String(params.ratio || '') !== historyFilterState.ratio) return false;
      if (historyFilterState.style !== 'all' && String(params.style || '') !== historyFilterState.style) return false;
      if (historyFilterState.resolution !== 'all' && String(params.resolution || '') !== historyFilterState.resolution) return false;

      if (historyFilterState.keyword) {
        const prompt = String(item.prompt || '').toLowerCase();
        const err = String(item.error || '').toLowerCase();
        if (!prompt.includes(historyFilterState.keyword) && !err.includes(historyFilterState.keyword)) {
          return false;
        }
      }
      return true;
    });
  }

  function getGroupLabel(ts) {
    const d = new Date((ts || 0) * 1000);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diffDays = Math.round((today - day) / (24 * 3600 * 1000));
    if (diffDays === 0) return '今天';
    if (diffDays === 1) return '昨天';
    return `${d.getMonth()+1}月${d.getDate()}日`;
  }

  function getHistoryStatusMeta(item) {
    const isSuccess = item.status === 'success';
    const isFailed = item.status === 'failed';
    return {
      icon: isSuccess ? '✅' : (isFailed ? '❌' : '⏳'),
      label: isSuccess ? '成功' : (isFailed ? '失败' : '进行中'),
      className: isSuccess ? 'success' : (isFailed ? 'failed' : 'pending')
    };
  }

  function getHistoryDateMeta(timestamp) {
    const dateObj = new Date((timestamp || 0) * 1000);
    return {
      short: dateObj.toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric' }),
      full: dateObj.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      })
    };
  }

  function getHistoryThumbMeta(item) {
    if (!item) return { src: '', fallback: '' };

    if ((item.type === 'gpt' || item.type === 'gpt-edit') && item.output_file) {
      return {
        src: '/gpt_outputs/' + item.output_file.replace('.png', '_thumb.png'),
        fallback: '/gpt_outputs/' + item.output_file
      };
    }

    if (item.type && item.type.startsWith('google') && item.output_file) {
      return {
        src: '/google_outputs/thumb_' + item.output_file,
        fallback: '/image/' + item.output_file
      };
    }

    if (item.type === 'comfy') {
      const comfyImage = item.params?.comfy_image || {};
      if (comfyImage.filename) {
        const q = new URLSearchParams({
          filename: comfyImage.filename,
          subfolder: comfyImage.subfolder || '',
          type: comfyImage.type || 'output'
        });
        const url = '/api/comfy/image?' + q.toString();
        return { src: url, fallback: url };
      }
    }

    if (item.output_file) {
      return {
        src: '/image/' + item.output_file,
        fallback: '/image/' + item.output_file
      };
    }

    return { src: '', fallback: '' };
  }

  function buildHistoryThumbMarkup(item, typeName, statusMeta) {
    if (isPendingHistoryRecord(item)) {
      return `<div class="history-thumb-wrap is-empty is-pending-task">
        <span class="history-status-dot ${statusMeta.className}">${statusMeta.icon}</span>
      </div>`;
    }

    const thumb = getHistoryThumbMeta(item);
    if (!thumb.src) {
      const missingClass = isHistoryAssetMissing(item) ? ' is-missing' : '';
      const missingText = isHistoryAssetMissing(item) ? `<span class="history-missing-copy">${getHistoryAssetMissingText(item)}</span>` : '';
      return `<div class="history-thumb-wrap is-empty${missingClass}">
        ${missingText}
        <span class="history-status-dot ${statusMeta.className}">${statusMeta.icon}</span>
      </div>`;
    }

    const missingClass = isHistoryAssetMissing(item) ? ' is-missing' : '';
    const missingText = isHistoryAssetMissing(item) ? `<span class="history-missing-copy">${getHistoryAssetMissingText(item)}</span>` : '';
    return `<div class="history-thumb-wrap${missingClass}">
      <img class="history-thumb" src="${thumb.src}" data-fallback="${thumb.fallback || ''}" alt="${typeName}" loading="lazy"
        onload="handleHistoryThumbLoad(this, '${item.task_id || ''}', '${item.timestamp || ''}')"
        onerror="handleHistoryThumbError(this, '${item.task_id || ''}', '${item.timestamp || ''}')">
      ${missingText}
      <span class="history-status-dot ${statusMeta.className}">${statusMeta.icon}</span>
    </div>`;
  }

  function createHistoryGroupTitle(groupLabel) {
    const title = document.createElement('div');
    title.className = 'history-group-title';
    title.textContent = groupLabel;
    return title;
  }

  function createHistoryCard(item, animationIndex) {
    const card = document.createElement('div');
    const dateMeta = getHistoryDateMeta(item.timestamp);
    const statusMeta = getHistoryStatusMeta(item);
    const typeName = HISTORY_TYPE_MAP[item.type] || item.type;
    const isPending = isPendingHistoryRecord(item);

    card.className = `history-card${isPending ? ' is-pending-task' : ''}`;
    card.style.animationDelay = `${Math.min(animationIndex, 24) * 40}ms`;
    if (!isPending) card.onclick = () => openDetailModal(item);
    card.innerHTML = `
      ${buildHistoryThumbMarkup(item, typeName, statusMeta)}
      <div class="history-card-meta">
        <div class="history-type-label">${typeName}</div>
        <div class="history-date" title="${dateMeta.full}">${dateMeta.short}</div>
        <div class="history-status-text ${statusMeta.className}">${isHistoryAssetMissing(item) ? `${statusMeta.label} · 文件缺失` : statusMeta.label}</div>
      </div>
    `;
    return card;
  }

  function renderHistoryList() {
    const list = document.getElementById('sidebarHistoryList');
    const filtered = applyHistoryFilters(historyRecords);

    const count = document.getElementById('historyCount');
    if (count) count.textContent = `${filtered.length} / ${historyRecords.length}`;

    list.innerHTML = '';
    if (historyRecords.length === 0) {
      setHistoryListMessage('暂无记录');
      return;
    }
    if (filtered.length === 0) {
      setHistoryListMessage('无匹配结果，试试放宽筛选条件');
      return;
    }

    let lastGroup = '';
    filtered.forEach(item => {
      const groupLabel = getGroupLabel(item.timestamp);
      if (groupLabel !== lastGroup) {
        lastGroup = groupLabel;
        list.appendChild(createHistoryGroupTitle(groupLabel));
      }
      list.appendChild(createHistoryCard(item, list.children.length));
    });
  }
