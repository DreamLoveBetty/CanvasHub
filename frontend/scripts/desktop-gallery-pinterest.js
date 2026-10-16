// Pinterest boards in the gallery workspace: the local board library and its sync status,
// board and pin downloads, the analysis and split modals, and the Pinterest stats line.
// desktop-history.js owns the gallery view, search, selection, preview and card rendering;
// it passes them in explicitly and reads Pinterest state only through the returned API.
(function () {
  function create({
    bindGalleryCardEvents, closeGallery, copyPinterestSplitText, els, escapeHtml,
    galleryError, mediaUrl, normalizeGalleryAsset, parseTags, renderGalleryImageCard,
    renderGallerySelection, renderGalleryStats, selectedGalleryIds, setPreviewAsset,
    getGalleryView, getGalleryQuery, getPreviewAsset
  }) {
    let pinterestBoards = [];
    let pinterestPins = [];
    let pinterestProfile = {};
    let pinterestActiveBoardId = '';
    let pinterestLibraryMeta = {};
    let pinterestLoading = false;
    let pinterestError = '';
    let pinterestRequestId = 0;
    let pinterestSyncStatus = {};
    let pinterestSyncChecking = false;
    let pinterestSyncRequestId = 0;
    let pinterestSyncPromise = null;
    let pinterestSyncTipBoardId = '';
    let pinterestBoardDownloadRun = null;
    let pinterestBoardDownloadTimer = null;
    let pinterestBoardDownloadHideTimer = null;
    const pinterestPinDownloads = new Set();
    const pinterestAnalyzingPins = new Set();
    const pinterestSplittingPins = new Set();
    let pinterestAnalysisAsset = null;
    let pinterestAnalysisPrompt = '';
    let pinterestAnalysisReturnFocus = null;
    let pinterestSplitAsset = null;
    let pinterestSplitCandidates = [];
    let pinterestSplitBusy = false;
    let pinterestSplitAction = '';
    let pinterestSplitMode = 'text';
    let pinterestSplitStatus = '';
    let pinterestSplitAnalysisId = '';
    let pinterestSplitRule = null;
    let pinterestSplitSourceGeometry = null;
    let pinterestSplitPrimaryType = '';
    let pinterestSplitSaveManifest = null;
    let pinterestSplitProgressTimer = null;
    let pinterestSplitStartedAt = 0;
    let pinterestSplitReturnFocus = null;
    let pinterestSplitRequestId = 0;
    const PINTEREST_LIBRARY_LIMIT = 5000;
    const PINTEREST_TERMINAL_HIDE_MS = 1100;
    const PINTEREST_SYNC_TIP_STORAGE_PREFIX = 'desk_pinterest_sync_tip_seen_v1:';
    const PINTEREST_SPLIT_MODULE_LABELS = {
      goal: '生成目标',
      identity: '身份',
      appearance: '外貌',
      body_shape: '体形身材',
      pose: '动作姿态',
      expression: '表情视线',
      clothing: '服装造型',
      makeup_hair: '妆发',
      accessories: '配饰',
      subject: '主体',
      scene: '场景环境',
      composition: '构图',
      camera: '视角与镜头',
      lighting: '光线',
      color: '色彩',
      style: '视觉风格',
      material: '材质细节',
      quality: '质量要求',
      constraints: '负面约束',
      custom: '自定义素材'
    };

    function normalizePinterestPin(item) {
      const remoteImageUrl = item?.remote_image_url || item?.remoteImageUrl || item?.image_url || item?.imageUrl || '';
      const localImageUrl = item?.local_image_url || item?.localImageUrl || '';
      const localThumbUrl = item?.local_thumb_url || item?.localThumbUrl || '';
      const analysisPrompt = String(item?.analysis_prompt || item?.analysisPrompt || '').trim();
      const analyzed = Boolean(item?.analyzed || analysisPrompt);
      return normalizeGalleryAsset({
        ...item,
        id: item?.id || item?.pin_id || '',
        asset_id: item?.id || item?.pin_id || '',
        taskId: item?.pin_id || item?.id || '',
        pinId: item?.pin_id || item?.pinId || '',
        title: item?.title || 'Pinterest Pin',
        prompt: analysisPrompt || item?.prompt || item?.description || '',
        analysisPrompt,
        analysis_prompt: analysisPrompt,
        analyzed,
        analyzedAt: item?.analyzed_at || item?.analyzedAt || '',
        analysisPromptRelativePath: item?.analysis_prompt_relative_path || item?.analysisPromptRelativePath || '',
        imageUrl: localImageUrl || remoteImageUrl,
        imagePath: localImageUrl || remoteImageUrl,
        thumbUrl: localThumbUrl || localImageUrl || item?.thumb_url || item?.thumbUrl || remoteImageUrl,
        remoteImageUrl,
        remoteThumbUrl: item?.thumb_url || item?.thumbUrl || remoteImageUrl,
        localCached: Boolean(item?.local_cached ?? item?.localCached),
        localImageUrl,
        localThumbUrl,
        localRelativePath: item?.local_relative_path || item?.localRelativePath || '',
        localDownloadedAt: item?.local_downloaded_at || item?.localDownloadedAt || '',
        localFileSize: Number(item?.local_file_size || item?.localFileSize || 0),
        provider: 'pinterest',
        providerLabel: 'Pinterest',
        sourceKind: 'pinterest',
        sourceUrl: item?.source_url || item?.sourceUrl || '',
        createdAt: item?.created_at || item?.createdAt || 0,
        boardId: item?.board_id || item?.boardId || '',
        boardName: item?.board_name || item?.boardName || '',
        boardUrl: item?.board_url || item?.boardUrl || '',
        externalUrl: item?.external_url || item?.externalUrl || '',
        favorite: false,
        hidden: false,
        hasTaskRecord: false,
        tags: parseTags(item?.tags),
        params: {
          ...(item?.params || {}),
          source_kind: 'pinterest',
          source_url: item?.source_url || item?.sourceUrl || '',
          board_id: item?.board_id || item?.boardId || '',
          board_name: item?.board_name || item?.boardName || ''
        }
      });
    }

    function getVisiblePinterestPins() {
      const query = getGalleryQuery().trim().toLowerCase();
      return pinterestPins.filter(asset => {
        if (pinterestActiveBoardId && asset.boardId !== pinterestActiveBoardId) return false;
        if (!query) return true;
        const haystack = [
          asset.title,
          asset.prompt,
          asset.boardName,
          asset.sourceUrl,
          asset.externalUrl,
          ...parseTags(asset.tags)
        ].filter(Boolean).join(' ').toLowerCase();
        return haystack.includes(query);
      });
    }

    function activePinterestDownloadRun(boardId = pinterestActiveBoardId) {
      const run = pinterestBoardDownloadRun;
      return run && String(run.board_id || '') === String(boardId || '') ? run : null;
    }

    function pinterestSyncedCount(run) {
      return Math.max(0, Number(run?.downloaded || 0) + Number(run?.already_cached || 0));
    }

    function pinterestStatusCount(source, keys = []) {
      for (const key of keys) {
        const value = source?.[key];
        if (Array.isArray(value)) return value.length;
        if (value !== undefined && value !== null && value !== '') {
          const count = Number(value);
          if (Number.isFinite(count)) return Math.max(0, count);
        }
      }
      return 0;
    }

    function pinterestActionableUpdateCount(source) {
      if (!source) return 0;
      const explicitKeys = [
        'actionable_unsynced_count',
        'actionable_updates',
        'actionable_count',
        'syncable_count',
        'available_unsynced_count'
      ];
      for (const key of explicitKeys) {
        if (source[key] !== undefined && source[key] !== null) {
          return pinterestStatusCount(source, [key]);
        }
      }
      if (Array.isArray(source.boards)) {
        return source.boards.reduce(
          (sum, board) => sum + pinterestActionableUpdateCount(board),
          0
        );
      }
      if (
        source.remote_discovered_count !== undefined
        && source.local_count !== undefined
      ) {
        const discovered = pinterestStatusCount(source, ['remote_discovered_count']);
        const local = pinterestStatusCount(source, ['local_count']);
        const localOnly = pinterestStatusCount(source, ['local_only_count']);
        return Math.max(0, discovered - local + localOnly);
      }
      const total = pinterestStatusCount(source, ['unsynced_count']);
      const unavailable = pinterestStatusCount(source, [
        'unavailable_count',
        'unavailable_unsynced_count',
        'unavailable'
      ]);
      const unresolved = pinterestStatusCount(source, [
        'unresolved_count',
        'unresolved_unsynced_count',
        'unresolved'
      ]);
      return Math.max(0, total - unavailable - unresolved);
    }

    function pinterestBoardPendingCount(board) {
      if (!board) return 0;
      const statusBoard = pinterestSyncStatus.boards?.find(
        item => String(item.id || '') === String(board.id || '')
      );
      return pinterestActionableUpdateCount(statusBoard || board);
    }

    function pinterestBoardCountLabel(board) {
      const localCount = Math.max(0, Number(board?.local_count ?? board?.cached_count ?? 0));
      const remoteCount = Math.max(0, Number(
        board?.remote_discovered_count
        ?? board?.remote_reported_count
        ?? board?.pin_count
        ?? localCount
      ));
      return pinterestSyncStatus.checked_at && remoteCount > localCount
        ? `${localCount}/${remoteCount}`
        : String(localCount);
    }

    function pinterestSyncTipStorageKey() {
      const username = String(
        pinterestSyncStatus.profile?.username
        || pinterestProfile.username
        || 'default'
      ).trim().toLowerCase() || 'default';
      return `${PINTEREST_SYNC_TIP_STORAGE_PREFIX}${username}`;
    }

    function maybeOpenPinterestSyncTip(board) {
      const boardId = String(board?.id || '');
      if (
        !boardId
        || pinterestActionableUpdateCount(pinterestSyncStatus) <= 0
        || pinterestBoardPendingCount(board) <= 0
      ) return;
      if (pinterestSyncTipBoardId === boardId) return;
      try {
        if (window.localStorage?.getItem(pinterestSyncTipStorageKey()) === '1') return;
        window.localStorage?.setItem(pinterestSyncTipStorageKey(), '1');
      } catch (error) {
        // Private browsing or disabled storage should not block the update hint.
      }
      pinterestSyncTipBoardId = boardId;
    }

    function pinterestRunIsActive(run) {
      return ['preparing', 'running'].includes(String(run?.status || ''));
    }

    function renderPinterestBoardDownload(run, activeBoard) {
      if (!activeBoard) return '';
      const running = pinterestRunIsActive(run);
      const preparing = run?.status === 'preparing' || run?.phase === 'discovering';
      const blockedByOtherBoard = !running && pinterestRunIsActive(pinterestBoardDownloadRun);
      const synced = pinterestSyncedCount(run);
      const runTotal = Math.max(0, Number(run?.total || 0));
      const boardTotal = Math.max(0, Number(
        activeBoard.remote_discovered_count
        ?? activeBoard.remote_reported_count
        ?? activeBoard.pin_count
        ?? 0
      ));
      const total = runTotal || boardTotal;
      const progress = Math.max(0, Math.min(100, total ? (synced * 100 / total) : Number(run?.progress_percent || 0)));
      const pendingCount = pinterestBoardPendingCount(activeBoard);
      const hasUpdates = pendingCount > 0 && !running && !blockedByOtherBoard;
      const showTip = !run && hasUpdates && pinterestSyncTipBoardId === String(activeBoard.id || '');
      const runStatus = ['preparing', 'running', 'completed', 'partial', 'failed'].includes(String(run?.status || ''))
        ? String(run.status)
        : 'running';
      const summary = run
        ? (
            pinterestRunIsActive(run)
              ? (preparing ? '准备同步图板' : `已同步 ${synced}/${total}`)
              : (run.message || `已同步 ${synced}/${total}`)
          )
        : (pendingCount ? `发现 ${pendingCount} 张待同步图片` : '本地图板已是最新');
      const buttonTitle = run
        ? summary
        : (
            blockedByOtherBoard
              ? '另一个 Pinterest 图板正在同步'
              : (
                  pendingCount
                    ? `发现 ${pendingCount} 张待同步图片，点击同步整个图板`
                    : '同步整个图板到本地'
                )
          );
      const idleLabel = blockedByOtherBoard ? '正在同步其他图板' : '同步图板';
      return `
      <div class="desk-pinterest-download-control">
        <button type="button" class="desk-pinterest-download-board${run ? ` has-progress is-${runStatus}` : ''}${running ? ' is-active' : ''}${preparing && runStatus !== 'preparing' ? ' is-preparing' : ''}${hasUpdates ? ' has-updates' : ''}" data-pinterest-download-board="${escapeHtml(activeBoard.id)}" style="--pinterest-sync-progress:${progress}" ${running || blockedByOtherBoard ? 'disabled' : ''} title="${escapeHtml(buttonTitle)}" aria-label="${escapeHtml(buttonTitle)}">
          ${run ? `
            <svg class="desk-pinterest-download-board__progress" viewBox="0 0 120 32" preserveAspectRatio="none" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress)}" aria-label="${escapeHtml(summary)}" data-pinterest-sync-progress>
              <rect class="desk-pinterest-download-board__track" x="2" y="2" width="116" height="28" rx="14" pathLength="100"></rect>
              <rect class="desk-pinterest-download-board__value" x="2" y="2" width="116" height="28" rx="14" pathLength="100"></rect>
            </svg>
          ` : ''}
          <span class="desk-pinterest-download-board__content${run ? ' is-progress' : ''}">
            ${run ? `
              <strong data-pinterest-sync-percent>${Math.round(progress)}%</strong>
              <span data-pinterest-sync-count>${synced}/${total} 张</span>
            ` : `
              <svg class="desk-pinterest-download-board__icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5M4 18v-5h5M18.5 9A7 7 0 0 0 6.1 6.1L4 8M5.5 15a7 7 0 0 0 12.4 2.9L20 16"></path></svg>
              <span data-pinterest-sync-label>${escapeHtml(idleLabel)}</span>
            `}
          </span>
        </button>
        ${showTip ? `
          <div class="desk-pinterest-sync-tip" data-pinterest-sync-tip role="status">
            <span>远程有 ${pendingCount} 张图片需要同步到本地</span>
            <button type="button" data-pinterest-sync-tip-close title="关闭提示" aria-label="关闭提示">
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 6 8 8m0-8-8 8"></path></svg>
            </button>
          </div>
        ` : ''}
      </div>
    `;
    }

    function rerenderPinterestPreservingScroll() {
      const previous = els.deskGalleryGrid?.querySelector('[data-pinterest-scroll]')?.scrollTop || 0;
      renderPinterestLibrary();
      const next = els.deskGalleryGrid?.querySelector('[data-pinterest-scroll]');
      if (next) next.scrollTop = previous;
    }

    function clearPinterestBoardDownloadHideTimer() {
      if (!pinterestBoardDownloadHideTimer) return;
      window.clearTimeout(pinterestBoardDownloadHideTimer);
      pinterestBoardDownloadHideTimer = null;
    }

    function schedulePinterestBoardDownloadHide(run) {
      clearPinterestBoardDownloadHideTimer();
      const runId = String(run?.run_id || '');
      const boardId = String(run?.board_id || '');
      pinterestBoardDownloadHideTimer = window.setTimeout(() => {
        pinterestBoardDownloadHideTimer = null;
        const current = pinterestBoardDownloadRun;
        const matchesRun = current && (
          (runId && String(current.run_id || '') === runId)
          || (!runId && String(current.board_id || '') === boardId)
        );
        if (!matchesRun || !['completed', 'partial', 'failed'].includes(String(current.status || ''))) return;
        pinterestBoardDownloadRun = null;
        if (getGalleryView() === 'pinterest') {
          rerenderPinterestPreservingScroll();
          renderGalleryStats();
        }
      }, PINTEREST_TERMINAL_HIDE_MS);
    }

    function updatePinterestDownloadControls() {
      const run = activePinterestDownloadRun();
      if (!run) return;
      const button = els.deskGalleryGrid?.querySelector('[data-pinterest-download-board]');
      const running = pinterestRunIsActive(run);
      const preparing = run.status === 'preparing' || run.phase === 'discovering';
      if (button) {
        button.disabled = running;
        const runStatus = ['preparing', 'running', 'completed', 'partial', 'failed'].includes(String(run.status || ''))
          ? String(run.status)
          : 'running';
        button.classList.remove('is-preparing', 'is-running', 'is-completed', 'is-partial', 'is-failed');
        button.classList.add('has-progress', `is-${runStatus}`);
        button.classList.toggle('is-active', running);
        button.classList.toggle('is-preparing', preparing);
        const synced = pinterestSyncedCount(run);
        const activeBoard = pinterestBoards.find(board => String(board.id || '') === String(run.board_id || ''));
        const total = Math.max(
          0,
          Number(run.total || 0)
          || Number(
            activeBoard?.remote_discovered_count
            ?? activeBoard?.remote_reported_count
            ?? activeBoard?.pin_count
            ?? 0
          )
        );
        const safeProgress = Math.max(0, Math.min(
          100,
          total ? (synced * 100 / total) : Number(run.progress_percent || 0)
        ));
        const roundedProgress = Math.round(safeProgress);
        button.style.setProperty('--pinterest-sync-progress', String(safeProgress));
        const progress = button.querySelector('[data-pinterest-sync-progress]');
        if (progress) progress.setAttribute('aria-valuenow', String(roundedProgress));
        const percent = button.querySelector('[data-pinterest-sync-percent]');
        if (percent) percent.textContent = `${roundedProgress}%`;
        const count = button.querySelector('[data-pinterest-sync-count]');
        if (count) count.textContent = `${synced}/${total} 张`;
        const summary = running
          ? (preparing ? '准备同步图板' : `已同步 ${synced}/${total}`)
          : (run.message || '');
        if (progress) progress.setAttribute('aria-label', summary);
        button.title = summary;
        button.setAttribute('aria-label', summary);
      }
    }

    function applyPinterestPinCache(pin, cache = {}) {
      if (!pin || !cache.local_cached) return;
      pin.remoteImageUrl = pin.remoteImageUrl || pin.imageUrl || '';
      pin.remoteThumbUrl = pin.remoteThumbUrl || pin.thumbUrl || pin.remoteImageUrl;
      pin.localCached = true;
      pin.localImageUrl = cache.local_image_url || '';
      pin.localThumbUrl = cache.local_thumb_url || pin.localImageUrl;
      pin.localRelativePath = cache.local_relative_path || '';
      pin.localDownloadedAt = cache.local_downloaded_at || '';
      pin.localFileSize = Number(cache.local_file_size || 0);
      pin.imageUrl = pin.localImageUrl || pin.imageUrl;
      pin.imagePath = pin.imageUrl;
      pin.thumbUrl = pin.localThumbUrl || pin.imageUrl;
      pinterestLibraryMeta.cached_count = pinterestPins.filter(item => item.localCached).length;
    }

    async function downloadPinterestPinToLocal(pinId, button = null) {
      const cleanPinId = String(pinId || '').trim();
      const pin = pinterestPins.find(item => String(item.pinId || item.taskId || '').replace(/^pinterest_/, '') === cleanPinId);
      if (!pin || !pin.boardId || pinterestPinDownloads.has(cleanPinId)) return;
      pinterestPinDownloads.add(cleanPinId);
      if (button) {
        button.disabled = true;
        button.title = '正在下载';
        button.setAttribute('aria-label', '正在下载');
      }
      try {
        const data = await DesktopApi.downloadPinterestPin({
          boardId: pin.boardId,
          pinId: cleanPinId
        });
        applyPinterestPinCache(pin, data.cache || {});
        rerenderPinterestPreservingScroll();
        renderGalleryStats();
        DesktopResults.showTransientMessage(data.cache?.already_cached ? '图片已在本地。' : 'Pinterest 图片已下载到本地。');
      } finally {
        pinterestPinDownloads.delete(cleanPinId);
        if (button?.isConnected && !pin.localCached) button.disabled = false;
      }
    }

    function pinterestAnalysisMainPrompt(result = {}) {
      const candidates = Array.isArray(result.candidates)
        ? result.candidates
        : [result.candidate].filter(Boolean);
      const main = candidates.find(item => item?.kind === 'image_analysis_main')
        || candidates.find(item => item?.text)
        || {};
      return String(
        main.text
        || result.analysis?.prompt_blocks?.main_prompt_no_text
        || result.analysis?.promptBlocks?.mainPromptNoText
        || ''
      ).trim();
    }

    function pinterestAssetHasAnalysis(asset) {
      return Boolean(asset?.analyzed && String(asset?.analysisPrompt || '').trim());
    }

    function applyPinterestAnalysisPrompt(asset, prompt, saved = {}) {
      if (!asset) return;
      const persistedPrompt = String(saved.analysis_prompt || saved.analysisPrompt || prompt || '').trim();
      asset.prompt = persistedPrompt;
      asset.analysisPrompt = persistedPrompt;
      asset.analysis_prompt = persistedPrompt;
      asset.analyzed = Boolean(persistedPrompt);
      asset.analyzedAt = saved.analyzed_at || saved.analyzedAt || asset.analyzedAt || '';
      asset.analysisPromptRelativePath = (
        saved.analysis_prompt_relative_path
        || saved.analysisPromptRelativePath
        || asset.analysisPromptRelativePath
        || ''
      );
      if (
        getPreviewAsset()
        && (getPreviewAsset().id || getPreviewAsset().asset_id) === (asset.id || asset.asset_id)
      ) {
        setPreviewAsset(asset, false);
      }
    }

    function updatePinterestAnalyzeButton(pinId, busy) {
      const cleanPinId = String(pinId || '');
      const asset = pinterestPins.find(item => (
        String(item.pinId || item.taskId || item.id || '').replace(/^pinterest_/, '') === cleanPinId
      ));
      const analyzed = pinterestAssetHasAnalysis(asset);
      const idleTitle = analyzed
        ? '已生成主提示词，点击可重新分析'
        : '分析图片并生成主提示词';
      els.deskGalleryGrid?.querySelectorAll?.('[data-pinterest-analyze-pin]').forEach(button => {
        if (button.dataset.pinterestAnalyzePin !== cleanPinId) return;
        button.disabled = !!busy || !asset?.imageUrl;
        button.classList.toggle('is-analyzing', !!busy);
        button.classList.toggle('is-analyzed', analyzed);
        button.setAttribute('aria-busy', busy ? 'true' : 'false');
        button.setAttribute('aria-label', busy ? '正在生成主提示词' : idleTitle);
        button.title = busy ? '正在生成主提示词' : idleTitle;
        const label = button.querySelector('span');
        if (label) label.textContent = busy ? '分析中' : (analyzed ? '已分析' : '分析');
      });
    }

    function pinterestSplitSourcePrompt(asset) {
      return String(
        asset?.analysisPrompt
        || asset?.analysis_prompt
        || asset?.prompt
        || asset?.description
        || ''
      ).trim();
    }

    function pinterestSplitSourceImage(asset) {
      return String(
        asset?.localImageUrl
        || asset?.imageUrl
        || asset?.remoteImageUrl
        || ''
      ).trim();
    }

    function pinterestSplitCanRun(asset) {
      return Boolean(pinterestSplitSourcePrompt(asset) || pinterestSplitSourceImage(asset));
    }

    function pinterestSplitModuleLabel(moduleType) {
      const cleanType = String(moduleType || '').trim();
      return window.DesktopPromptLibrary?.getModuleLabel?.(cleanType)
        || PINTEREST_SPLIT_MODULE_LABELS[cleanType]
        || cleanType
        || '自定义素材';
    }

    function pinterestSplitSelectedCandidates() {
      return pinterestSplitCandidates.filter(candidate => candidate?.selected && String(candidate.content || '').trim());
    }

    function pinterestSplitGeometrySummary(geometry = pinterestSplitSourceGeometry) {
      if (!geometry || typeof geometry !== 'object') return '';
      const width = Number(geometry.width || 0);
      const height = Number(geometry.height || 0);
      const recommendedRatio = String(geometry.recommended_ratio || geometry.recommendedRatio || '').trim();
      const sourceSize = width > 0 && height > 0 ? `${width}×${height}` : '';
      if (sourceSize && recommendedRatio) return `原图 ${sourceSize} · 推荐生成比例 ${recommendedRatio}`;
      if (recommendedRatio) return `推荐生成比例 ${recommendedRatio}`;
      return sourceSize ? `原图 ${sourceSize}` : '';
    }

    function composePinterestFidelityPrompt(selected = pinterestSplitSelectedCandidates()) {
      const blocks = (Array.isArray(selected) ? selected : [])
        .map(block => {
          const content = String(block?.content || '').replace(/\s+/g, ' ').trim();
          if (!content) return '';
          return `【${pinterestSplitModuleLabel(block?.module_type)}】${content}`;
        })
        .filter(Boolean);
      if (!blocks.length) return '';
      const geometry = pinterestSplitSourceGeometry && typeof pinterestSplitSourceGeometry === 'object'
        ? pinterestSplitSourceGeometry
        : {};
      const width = Number(geometry.width || 0);
      const height = Number(geometry.height || 0);
      const recommendedRatio = String(geometry.recommended_ratio || geometry.recommendedRatio || '').trim();
      const geometryConstraint = recommendedRatio
        ? `保持原图${width > 0 && height > 0 ? ` ${width}×${height}` : ''}的画幅与裁切关系，生成参数优先使用 ${recommendedRatio}，不要改成更宽或更窄的比例。`
        : '保持原图画幅、主体占比与边缘裁切关系，不要擅自扩宽画面。';
      const ratioLock = recommendedRatio ? `【原图比例：${recommendedRatio}】` : '';
      const fidelityLock = [
        '【同图忠实复现｜高保真模块】',
        ratioLock,
        '以下模块共同描述同一张参考图，必须作为一个完整提示词整体执行。',
        '每个模块都是可见事实硬约束，不是创作灵感；优先执行具体的数量、年龄范围、几何比例、坐标、裁切、类别、材质和纹理，不得改写成常见近似款。',
        '忠实保持主体数量、可见年龄感与成熟度、脸部或物体几何比例、体型与体量、服装或产品结构、材质纹理、姿态、构图、裁切、镜头、光线、色彩、背景地标和可见文字关系。',
        '禁止自动美化、年轻化、瘦身、改脸、替换服装或材质、简化背景、新增对象及改变关键空间关系；近距离人像不得自动补出伸向镜头的自拍前臂、手掌或手机。',
        geometryConstraint,
      ].join('');
      return `${fidelityLock}${blocks.join('；')}`.replace(/\s+/g, ' ').trim();
    }

    function updatePinterestSplitButton(pinId, busy) {
      const cleanPinId = String(pinId || '');
      const asset = pinterestPins.find(item => (
        String(item.pinId || item.taskId || item.id || '').replace(/^pinterest_/, '') === cleanPinId
      ));
      const hasPrompt = Boolean(pinterestSplitSourcePrompt(asset));
      const hasImage = Boolean(pinterestSplitSourceImage(asset));
      const canRun = hasPrompt || hasImage;
      const title = busy
        ? (hasImage ? '正在按高保真模块分析图片' : '正在按高保真模块拆分现有提示词')
        : (!canRun
          ? '这张图片没有可用于拆分的提示词或图片资源'
          : (hasImage
            ? '直接分析图片并按高保真模块提取素材'
            : '图片不可用，按高保真模块拆分现有提示词'));
      els.deskGalleryGrid?.querySelectorAll?.('[data-pinterest-split-pin]').forEach(button => {
        if (button.dataset.pinterestSplitPin !== cleanPinId) return;
        button.disabled = Boolean(busy) || !canRun;
        button.classList.toggle('is-splitting', Boolean(busy));
        button.setAttribute('aria-busy', busy ? 'true' : 'false');
        button.setAttribute('aria-label', title);
        button.title = title;
        const label = button.querySelector('span');
        if (label) label.textContent = busy ? '拆分中' : '拆分';
      });
    }

    function renderPinterestSplitModal() {
      const results = els.deskPinterestSplitResults;
      const selectedCount = pinterestSplitSelectedCandidates().length;
      if (results) {
        if (pinterestSplitBusy && pinterestSplitAction === 'extract') {
          const analyzingImage = pinterestSplitMode === 'image';
          results.innerHTML = `
          <div class="desk-pinterest-split-modal__loading">
            <span aria-hidden="true"></span>
            <strong>${analyzingImage ? '正在按模块分析图片' : '正在拆分提示词'}</strong>
            <p>${analyzingImage ? '将直接读取图片视觉信息，并按高保真模块生成素材；人像会独立提取体形身材。' : '将按高保真模块整理可复用内容。'}</p>
          </div>
        `;
        } else if (pinterestSplitCandidates.length) {
          results.innerHTML = pinterestSplitCandidates.map((candidate, index) => `
          <label class="desk-pinterest-split-modal__candidate${candidate.selected ? ' is-selected' : ''}">
            <input type="checkbox" data-pinterest-split-candidate="${index}" ${candidate.selected ? 'checked' : ''} ${pinterestSplitBusy ? 'disabled' : ''}>
            <span class="desk-pinterest-split-modal__candidate-check" aria-hidden="true"></span>
            <span class="desk-pinterest-split-modal__candidate-copy">
              <strong>${escapeHtml(candidate.name || pinterestSplitModuleLabel(candidate.module_type))}</strong>
              <em>${escapeHtml(pinterestSplitModuleLabel(candidate.module_type))}</em>
              <span>${escapeHtml(candidate.content || '')}</span>
            </span>
          </label>
        `).join('');
        } else {
          results.innerHTML = `
          <div class="desk-pinterest-split-modal__empty">
            <strong>没有可用素材块</strong>
            <span>请重新分析图片或检查当前提示词。</span>
          </div>
        `;
        }
      }
      if (els.deskPinterestSplitStatus) {
        els.deskPinterestSplitStatus.textContent = pinterestSplitStatus
          || (pinterestSplitCandidates.length ? `已选 ${selectedCount} 个素材块。` : '正在准备素材块拆分。');
      }
      if (els.deskPinterestSplitCopyBtn) {
        els.deskPinterestSplitCopyBtn.disabled = pinterestSplitBusy || !selectedCount;
      }
      if (els.deskPinterestSplitSaveBtn) {
        els.deskPinterestSplitSaveBtn.disabled = pinterestSplitBusy || !selectedCount;
        els.deskPinterestSplitSaveBtn.textContent = pinterestSplitBusy && pinterestSplitAction === 'save'
          ? '正在存储…'
          : '存储到素材块';
      }
    }

    function stopPinterestSplitProgress() {
      if (pinterestSplitProgressTimer) window.clearInterval(pinterestSplitProgressTimer);
      pinterestSplitProgressTimer = null;
      pinterestSplitStartedAt = 0;
    }

    function updatePinterestSplitProgress() {
      if (!pinterestSplitBusy || pinterestSplitAction !== 'extract' || !pinterestSplitStartedAt) return;
      const elapsed = Math.max(0, Math.floor((Date.now() - pinterestSplitStartedAt) / 1000));
      const elapsedLabel = elapsed >= 60
        ? `${Math.floor(elapsed / 60)} 分 ${String(elapsed % 60).padStart(2, '0')} 秒`
        : `${elapsed} 秒`;
      let message = '';
      if (pinterestSplitMode !== 'image') {
        message = `正在拆分提示词 · 已用 ${elapsedLabel}`;
      } else if (elapsed < 20) {
        message = `正在读取图片和识别主体 · 已用 ${elapsedLabel}`;
      } else if (elapsed < 90) {
        message = `正在建立构图、人物/物体和材质视觉锚点 · 已用 ${elapsedLabel}`;
      } else if (elapsed < 240) {
        message = `正在按高保真模块细化并核对防漂移约束 · 已用 ${elapsedLabel}`;
      } else {
        message = `模型正在输出高细节视觉蓝图，请继续等待 · 已用 ${elapsedLabel}`;
      }
      pinterestSplitStatus = message;
      if (els.deskPinterestSplitStatus) els.deskPinterestSplitStatus.textContent = message;
    }

    function startPinterestSplitProgress() {
      stopPinterestSplitProgress();
      pinterestSplitStartedAt = Date.now();
      updatePinterestSplitProgress();
      pinterestSplitProgressTimer = window.setInterval(updatePinterestSplitProgress, 1000);
    }

    function openPinterestSplitModal(asset, trigger = null) {
      pinterestSplitAsset = asset || null;
      pinterestSplitReturnFocus = trigger || null;
      if (els.deskPinterestSplitImg) {
        const imageUrl = mediaUrl(asset?.thumbUrl || asset?.imageUrl || '');
        els.deskPinterestSplitImg.src = imageUrl;
        els.deskPinterestSplitImg.alt = asset?.title || 'Pinterest 图片';
        els.deskPinterestSplitImg.hidden = !imageUrl;
      }
      if (els.deskPinterestSplitTitle) {
        els.deskPinterestSplitTitle.textContent = asset?.title || 'Pinterest 图片';
      }
      if (els.deskPinterestSplitMeta) {
        els.deskPinterestSplitMeta.textContent = [
          asset?.boardName || 'Pinterest',
          '按高保真模块拆分'
        ].filter(Boolean).join(' · ');
      }
      if (!els.deskPinterestSplitModal) return;
      els.deskPinterestSplitModal.hidden = false;
      els.deskPinterestSplitModal.setAttribute('aria-hidden', 'false');
      renderPinterestSplitModal();
      window.requestAnimationFrame(() => {
        els.deskPinterestSplitModal?.classList.add('is-open');
        els.deskPinterestSplitModal?.querySelector?.('[data-pinterest-split-candidate], #deskPinterestSplitCloseBtn')?.focus?.({ preventScroll: true });
      });
    }

    function closePinterestSplitModal(options = {}) {
      const modal = els.deskPinterestSplitModal;
      if (!modal || modal.hidden) return false;
      if (pinterestSplitBusy && !options.force) return false;
      pinterestSplitRequestId += 1;
      modal.classList.remove('is-open');
      modal.setAttribute('aria-hidden', 'true');
      modal.hidden = true;
      if (els.deskPinterestSplitImg) {
        els.deskPinterestSplitImg.removeAttribute('src');
        els.deskPinterestSplitImg.alt = '';
      }
      pinterestSplitAsset = null;
      pinterestSplitCandidates = [];
      pinterestSplitBusy = false;
      pinterestSplitAction = '';
      pinterestSplitMode = 'text';
      pinterestSplitStatus = '';
      pinterestSplitAnalysisId = '';
      pinterestSplitRule = null;
      pinterestSplitSourceGeometry = null;
      pinterestSplitPrimaryType = '';
      pinterestSplitSaveManifest = null;
      stopPinterestSplitProgress();
      if (options.restoreFocus !== false && pinterestSplitReturnFocus?.isConnected) {
        pinterestSplitReturnFocus.focus?.({ preventScroll: true });
      }
      pinterestSplitReturnFocus = null;
      return true;
    }

    async function splitPinterestPrompt(asset, trigger = null) {
      if (!asset || asset.sourceKind !== 'pinterest') throw new Error('Pinterest 图片不存在');
      const prompt = pinterestSplitSourcePrompt(asset);
      const imageSource = pinterestSplitSourceImage(asset);
      if (!prompt && !imageSource) throw new Error('这张图片没有可用于拆分的提示词或图片资源');
      const pinId = String(asset.pinId || asset.taskId || asset.id || '').replace(/^pinterest_/, '');
      if (!pinId || pinterestSplittingPins.has(pinId)) return;
      if (!window.DesktopApi?.extractPromptBlocks) throw new Error('素材块拆分组件尚未加载');

      const requestId = ++pinterestSplitRequestId;
      pinterestSplittingPins.add(pinId);
      pinterestSplitCandidates = [];
      pinterestSplitAnalysisId = '';
      pinterestSplitRule = null;
      pinterestSplitSourceGeometry = null;
      pinterestSplitPrimaryType = '';
      pinterestSplitSaveManifest = null;
      pinterestSplitBusy = true;
      pinterestSplitAction = 'extract';
      pinterestSplitMode = imageSource ? 'image' : 'text';
      pinterestSplitStatus = imageSource
        ? '正在读取图片，并按高保真模块直接分析。'
        : '图片不可用，正在按高保真模块拆分现有提示词。';
      openPinterestSplitModal(asset, trigger);
      startPinterestSplitProgress();
      updatePinterestSplitButton(pinId, true);

      try {
        let payload;
        if (imageSource) {
          if (!window.DesktopApi?.imageUrlToDataUri) throw new Error('图片读取组件尚未加载');
          const dataUrl = await window.DesktopApi.imageUrlToDataUri(mediaUrl(imageSource));
          if (!dataUrl) throw new Error('图片读取失败');
          payload = {
            mode: 'image',
            module_scope: 'generic_19',
            message: '先完整理解这张 Pinterest 图片，再严格按高保真模块提取可独立复用的图像生成提示词素材。人物、人像、时尚或角色图片只要身体区域可见，就必须把体形身材作为独立模块，不能混入外貌或姿态。只返回模块素材，不返回普通“分析”功能的主提示词或分析报告。',
            images: [{
              id: `pinterest_${pinId}`,
              label: asset.title || 'Pinterest 图片',
              data_url: dataUrl,
              role: 'primary'
            }]
          };
        } else {
          payload = {
            mode: 'text',
            module_scope: 'generic_19',
            text: prompt
          };
        }
        const result = await window.DesktopApi.extractPromptBlocks(payload);
        if (requestId !== pinterestSplitRequestId) return;
        pinterestSplitAnalysisId = String(result?.analysis_id || result?.analysisId || '').trim();
        pinterestSplitRule = result?.split_rule && typeof result.split_rule === 'object'
          ? result.split_rule
          : null;
        pinterestSplitSourceGeometry = result?.source_geometry && typeof result.source_geometry === 'object'
          ? result.source_geometry
          : null;
        pinterestSplitPrimaryType = String(result?.primary_type || result?.primaryType || '').trim();
        pinterestSplitCandidates = (Array.isArray(result?.blocks) ? result.blocks : [])
          .map(block => ({
            name: String(block?.name || '').trim().slice(0, 120),
            module_type: String(block?.module_type || 'custom').trim() || 'custom',
            content: String(block?.content || '').trim(),
            compact_content: String(block?.compact_content || '').trim(),
            english_content: String(block?.english_content || '').trim(),
            applicable_types: Array.isArray(block?.applicable_types) ? block.applicable_types : [],
            tags: Array.isArray(block?.tags) ? block.tags : [],
            selected: true
          }))
          .filter(block => block.content);
        if (!pinterestSplitCandidates.length) throw new Error('没有得到可保存的素材块');
        const geometrySummary = pinterestSplitGeometrySummary();
        const coverage = Number(result?.anchor_coverage ?? result?.fidelity_score);
        const coverageSummary = Number.isFinite(coverage) && coverage > 0
          ? ` · 视觉锚点覆盖 ${Math.round(coverage <= 1 ? coverage * 100 : coverage)}%`
          : '';
        pinterestSplitStatus = `已拆分 ${pinterestSplitCandidates.length} 个素材块${geometrySummary ? ` · ${geometrySummary}` : ''}${coverageSummary}，请选择存储或直接复制。`;
        if (els.deskPinterestSplitMeta) {
          els.deskPinterestSplitMeta.textContent = [
            asset?.boardName || 'Pinterest',
            pinterestSplitPrimaryType ? `类型 ${pinterestSplitPrimaryType}` : '',
            geometrySummary,
            '高保真 19 模块',
          ].filter(Boolean).join(' · ');
        }
        if (result?.warning) {
          DesktopResults.showTransientMessage(result.warning, 'warning');
        }
      } catch (error) {
        if (requestId !== pinterestSplitRequestId) return;
        pinterestSplitCandidates = [];
        pinterestSplitStatus = error?.message || String(error);
        throw error;
      } finally {
        stopPinterestSplitProgress();
        pinterestSplittingPins.delete(pinId);
        updatePinterestSplitButton(pinId, false);
        if (requestId === pinterestSplitRequestId) {
          pinterestSplitBusy = false;
          pinterestSplitAction = '';
          renderPinterestSplitModal();
        }
      }
    }

    async function copyPinterestSplitCandidates() {
      const selected = pinterestSplitSelectedCandidates();
      if (!selected.length) throw new Error('请选择至少一个素材块');
      pinterestSplitBusy = true;
      pinterestSplitAction = 'copy';
      pinterestSplitStatus = '正在复制选中的素材块。';
      renderPinterestSplitModal();
      try {
        await copyPinterestSplitText(composePinterestFidelityPrompt(selected));
        closePinterestSplitModal({ force: true });
        DesktopResults.showTransientMessage(`已复制 ${selected.length} 个素材块。`, 'success');
      } catch (error) {
        pinterestSplitBusy = false;
        pinterestSplitAction = '';
        pinterestSplitStatus = error?.message || String(error);
        renderPinterestSplitModal();
        throw error;
      }
    }

    async function savePinterestSplitCandidates() {
      const asset = pinterestSplitAsset;
      const selected = pinterestSplitSelectedCandidates();
      if (!asset || !selected.length) throw new Error('请选择至少一个素材块');
      if (!window.DesktopApi?.savePromptBlock) throw new Error('素材块保存组件尚未加载');

      pinterestSplitBusy = true;
      pinterestSplitAction = 'save';
      pinterestSplitStatus = `正在存储 ${selected.length} 个素材块。`;
      renderPinterestSplitModal();
      try {
        const pinId = String(asset.pinId || asset.taskId || asset.id || '').replace(/^pinterest_/, '');
        const sourceTags = ['Pinterest', asset.boardName].filter(Boolean);
        const splitRule = pinterestSplitRule && typeof pinterestSplitRule === 'object'
          ? pinterestSplitRule
          : { id: 'generic_19', name: '通用高保真模块', version: 6 };
        const sourceRuleSnapshot = {
          ...splitRule,
          bundle_id: pinterestSplitAnalysisId,
          pin_id: pinId,
          source_kind: 'pinterest',
          source_image: pinterestSplitSourceImage(asset),
          source_geometry: pinterestSplitSourceGeometry || {},
          primary_type: pinterestSplitPrimaryType,
          fidelity_marker: '【同图忠实复现｜高保真模块】',
        };
        if (!pinterestSplitSaveManifest) {
          pinterestSplitSaveManifest = {
            bundleId: pinterestSplitAnalysisId,
            entries: selected.map((block, index) => ({ block, index })),
            selectedModules: selected.map(block => String(block.module_type || 'custom')),
          };
        }
        const manifest = pinterestSplitSaveManifest;
        const selectedModuleTypes = manifest.selectedModules;
        const outcomes = await Promise.allSettled(selected.map((block, moduleOrder) => window.DesktopApi.savePromptBlock({
          ...block,
          applicable_types: [...new Set([
            ...(Array.isArray(block.applicable_types) ? block.applicable_types : []),
            pinterestSplitPrimaryType,
          ].filter(Boolean))].slice(0, 8),
          tags: [...new Set([...(block.tags || []), ...sourceTags])].slice(0, 12),
          source: 'pinterest_split',
          source_rule_id: String(splitRule.id || 'generic_19'),
          source_rule_version: Number(splitRule.version || 6),
          source_rule_snapshot: {
            ...sourceRuleSnapshot,
            bundle_id: manifest.bundleId || sourceRuleSnapshot.bundle_id,
            module_order: manifest.entries.find(entry => entry.block === block)?.index ?? moduleOrder,
            module_count: manifest.entries.length,
            selected_modules: selectedModuleTypes,
          },
        })));
        const savedIndexes = new Set();
        const saved = [];
        outcomes.forEach((outcome, index) => {
          const block = outcome.status === 'fulfilled' ? outcome.value?.block : null;
          if (!block?.id) return;
          saved.push(block);
          savedIndexes.add(index);
        });
        if (!saved.length) {
          throw outcomes.find(outcome => outcome.status === 'rejected')?.reason || new Error('素材块保存失败');
        }
        window.DesktopPromptInsert?.refresh?.();
        const failed = selected.length - saved.length;
        if (!failed) {
          closePinterestSplitModal({ force: true });
          DesktopResults.showTransientMessage(`已存储 ${saved.length} 个素材块。`, 'success');
          return;
        }
        const savedCandidates = new Set(
          [...savedIndexes].map(index => selected[index])
        );
        pinterestSplitCandidates = pinterestSplitCandidates.filter(candidate => !savedCandidates.has(candidate));
        pinterestSplitStatus = `已存储 ${saved.length} 个素材块，剩余 ${failed} 个可重试。`;
        DesktopResults.showTransientMessage(pinterestSplitStatus, 'warning');
      } catch (error) {
        pinterestSplitStatus = error?.message || String(error);
        throw error;
      } finally {
        if (!els.deskPinterestSplitModal?.hidden) {
          pinterestSplitBusy = false;
          pinterestSplitAction = '';
          renderPinterestSplitModal();
        }
      }
    }

    function currentPinterestAnalysisPrompt() {
      return String(els.deskPinterestAnalysisPrompt?.value || pinterestAnalysisPrompt || '').trim();
    }

    function openPinterestAnalysisModal(asset, prompt, trigger = null) {
      pinterestAnalysisAsset = asset || null;
      pinterestAnalysisPrompt = String(prompt || '').trim();
      pinterestAnalysisReturnFocus = trigger || null;
      if (els.deskPinterestAnalysisImg) {
        const imageUrl = mediaUrl(asset?.thumbUrl || asset?.imageUrl || '');
        els.deskPinterestAnalysisImg.src = imageUrl;
        els.deskPinterestAnalysisImg.alt = asset?.title || 'Pinterest 图片';
        els.deskPinterestAnalysisImg.hidden = !imageUrl;
      }
      if (els.deskPinterestAnalysisTitle) {
        els.deskPinterestAnalysisTitle.textContent = asset?.title || 'Pinterest 图片分析';
      }
      if (els.deskPinterestAnalysisMeta) {
        els.deskPinterestAnalysisMeta.textContent = [
          asset?.boardName || 'Pinterest',
          asset?.dimensions || '',
          asset?.format || ''
        ].filter(Boolean).join(' · ');
      }
      if (els.deskPinterestAnalysisPrompt) {
        els.deskPinterestAnalysisPrompt.value = pinterestAnalysisPrompt;
      }
      if (els.deskPinterestAnalysisTarget) {
        const target = window.DesktopCanvas?.getPromptTargetInfo?.() || {};
        els.deskPinterestAnalysisTarget.textContent = target.type === 'text' && target.nodeId
          ? `发送后将写入当前文本节点「${target.label || '文本节点'}」。`
          : '当前未选择文本节点，发送时会在画布上新建一个文本节点。';
      }
      if (els.deskPinterestAnalysisModal) {
        els.deskPinterestAnalysisModal.hidden = false;
        els.deskPinterestAnalysisModal.setAttribute('aria-hidden', 'false');
        window.requestAnimationFrame(() => {
          els.deskPinterestAnalysisModal?.classList.add('is-open');
          els.deskPinterestAnalysisPrompt?.focus?.({ preventScroll: true });
        });
      }
    }

    function closePinterestAnalysisModal(options = {}) {
      const modal = els.deskPinterestAnalysisModal;
      if (!modal || modal.hidden) return;
      modal.classList.remove('is-open');
      modal.setAttribute('aria-hidden', 'true');
      modal.hidden = true;
      if (els.deskPinterestAnalysisImg) {
        els.deskPinterestAnalysisImg.removeAttribute('src');
        els.deskPinterestAnalysisImg.alt = '';
      }
      pinterestAnalysisAsset = null;
      pinterestAnalysisPrompt = '';
      if (options.restoreFocus !== false && pinterestAnalysisReturnFocus?.isConnected) {
        pinterestAnalysisReturnFocus.focus?.({ preventScroll: true });
      }
      pinterestAnalysisReturnFocus = null;
    }

    async function copyPinterestAnalysisPrompt() {
      const prompt = currentPinterestAnalysisPrompt();
      if (!prompt) throw new Error('没有可复制的提示词');
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(prompt);
      } else {
        const textarea = els.deskPinterestAnalysisPrompt;
        textarea?.focus?.();
        textarea?.select?.();
        if (!document.execCommand?.('copy')) throw new Error('复制失败');
      }
      const button = els.deskPinterestAnalysisCopyBtn;
      if (button) {
        button.textContent = '已复制';
        window.setTimeout(() => {
          if (button.isConnected) button.textContent = '复制提示词';
        }, 1100);
      }
      DesktopResults.showTransientMessage('主提示词已复制。', 'success');
    }

    function sendPinterestAnalysisToTextNode() {
      const prompt = currentPinterestAnalysisPrompt();
      if (!prompt) throw new Error('没有可发送的提示词');
      const canvas = window.DesktopCanvas;
      const target = canvas?.getPromptTargetInfo?.() || {};
      let message = '';
      if (target.type === 'text' && target.nodeId) {
        canvas.fillPromptTarget?.(prompt, { target });
        message = `主提示词已发送到「${target.label || '文本节点'}」。`;
      } else {
        const nodeId = canvas?.createTextNodeWithText?.(prompt);
        if (!nodeId) throw new Error('无法新建文本节点');
        canvas.selectNode?.(nodeId);
        message = '已新建文本节点并写入主提示词。';
      }
      closePinterestAnalysisModal({ restoreFocus: false });
      closeGallery();
      DesktopResults.showTransientMessage(message, 'success');
    }

    async function analyzePinterestAsset(asset, button = null) {
      if (!asset || asset.sourceKind !== 'pinterest') throw new Error('Pinterest 图片不存在');
      const pinId = String(asset.pinId || asset.taskId || asset.id || '').replace(/^pinterest_/, '');
      if (!pinId || pinterestAnalyzingPins.has(pinId)) return;
      if (pinterestAnalyzingPins.size) {
        DesktopResults.showTransientMessage('已有一张 Pinterest 图片正在分析，请稍候。', 'warning');
        return;
      }
      if (
        pinterestAssetHasAnalysis(asset)
        && typeof window.confirm === 'function'
        && !window.confirm('这张图片已有分析提示词。确认重新分析并覆盖同目录下的 image.md 吗？')
      ) {
        return;
      }
      const source = String(asset.localImageUrl || asset.imageUrl || asset.remoteImageUrl || '').trim();
      if (!source) throw new Error('这张 Pinterest 图片没有可分析的本地资源');
      pinterestAnalyzingPins.add(pinId);
      updatePinterestAnalyzeButton(pinId, true);
      try {
        const isDirectProviderUrl = /^https?:\/\//i.test(source);
        let imagePayload = {
          id: `pinterest_${pinId}`,
          label: asset.title || 'Pinterest 图片',
          role: 'primary'
        };
        if (isDirectProviderUrl) {
          imagePayload.imageUrl = source;
        } else {
          if (!window.DesktopApi?.imageUrlToDataUri) throw new Error('图片读取组件尚未加载');
          imagePayload.dataUrl = await DesktopApi.imageUrlToDataUri(mediaUrl(source));
        }
        const target = window.DesktopCanvas?.getPromptTargetInfo?.() || {};
        const result = await DesktopApi.analyzePromptImage({
          message: '分析这张 Pinterest 参考图，生成可直接用于图像生成的主提示词。',
          images: [imagePayload],
          target: target.type === 'text' ? target : {},
          style: {},
          keep_text: false
        });
        const prompt = pinterestAnalysisMainPrompt(result);
        if (!prompt) throw new Error('图片分析完成，但没有生成主提示词');
        if (!DesktopApi.savePinterestPrompt) throw new Error('Pinterest 提示词保存组件尚未加载');
        const saved = await DesktopApi.savePinterestPrompt({
          boardId: asset.boardId,
          pinId,
          prompt
        });
        applyPinterestAnalysisPrompt(asset, prompt, saved);
        openPinterestAnalysisModal(asset, asset.analysisPrompt, button);
        DesktopResults.showTransientMessage('Pinterest 图片分析已完成。', 'success');
        return { ...result, pinterest_prompt: saved };
      } finally {
        pinterestAnalyzingPins.delete(pinId);
        updatePinterestAnalyzeButton(pinId, false);
      }
    }

    async function pollPinterestBoardDownload(runId) {
      if (!runId || !DesktopApi.getPinterestDownloadStatus) return;
      try {
        const data = await DesktopApi.getPinterestDownloadStatus(runId);
        pinterestBoardDownloadRun = data.run || null;
        updatePinterestDownloadControls();
        if (pinterestRunIsActive(pinterestBoardDownloadRun)) {
          pinterestBoardDownloadTimer = window.setTimeout(() => {
            pollPinterestBoardDownload(runId).catch(error => DesktopResults.showError(error));
          }, 800);
          return;
        }
        pinterestBoardDownloadTimer = null;
        const run = pinterestBoardDownloadRun;
        if (!run) {
          if (getGalleryView() === 'pinterest') rerenderPinterestPreservingScroll();
          throw new Error('Pinterest 图板同步任务未返回状态');
        }
        if (run.status === 'completed') {
          DesktopResults.showTransientMessage(run.message || 'Pinterest 图板已同步。');
        } else {
          DesktopResults.showError(new Error(run.message || 'Pinterest 图板未全部同步'));
        }
        schedulePinterestBoardDownloadHide(run);
        await loadPinterestLibrary({ checkRemote: false });
        await checkPinterestSyncStatus({ force: true });
      } catch (error) {
        pinterestBoardDownloadTimer = null;
        if (pinterestRunIsActive(pinterestBoardDownloadRun)) {
          pinterestBoardDownloadRun = null;
          if (getGalleryView() === 'pinterest') rerenderPinterestPreservingScroll();
        }
        throw error;
      }
    }

    async function downloadPinterestBoardToLocal(boardId) {
      const cleanBoardId = String(boardId || '').trim();
      if (!cleanBoardId || !DesktopApi.downloadPinterestBoard) return;
      if (pinterestRunIsActive(pinterestBoardDownloadRun)) return;
      if (pinterestBoardDownloadTimer) {
        window.clearTimeout(pinterestBoardDownloadTimer);
        pinterestBoardDownloadTimer = null;
      }
      clearPinterestBoardDownloadHideTimer();
      pinterestSyncTipBoardId = '';
      const board = pinterestBoards.find(item => String(item.id || '') === cleanBoardId) || {};
      const total = Math.max(0, Number(
        board.remote_discovered_count
        ?? board.remote_reported_count
        ?? board.pin_count
        ?? 0
      ));
      pinterestBoardDownloadRun = {
        run_id: '',
        board_id: cleanBoardId,
        board_name: String(board.name || ''),
        status: 'preparing',
        started_at: new Date().toISOString(),
        total,
        processed: 0,
        downloaded: 0,
        already_cached: 0,
        failed: 0,
        progress_percent: 0,
        message: '准备同步 Pinterest 图板'
      };
      rerenderPinterestPreservingScroll();
      try {
        const data = await DesktopApi.downloadPinterestBoard(cleanBoardId, { refresh: true });
        const run = data.run || null;
        if (!run?.run_id) throw new Error('Pinterest 图板同步任务启动失败');
        pinterestBoardDownloadRun = run;
        rerenderPinterestPreservingScroll();
        await pollPinterestBoardDownload(run.run_id);
      } catch (error) {
        if (
          pinterestBoardDownloadRun?.status === 'preparing'
          && String(pinterestBoardDownloadRun.board_id || '') === cleanBoardId
        ) {
          pinterestBoardDownloadRun = null;
        }
        if (getGalleryView() === 'pinterest') rerenderPinterestPreservingScroll();
        throw error;
      }
    }

    function renderPinterestLibrary() {
      const grid = els.deskGalleryGrid;
      if (!grid) return;
      renderGalleryStats();
      if (pinterestLoading) {
        grid.innerHTML = `
        <div class="desk-pinterest-state is-loading">
          <span aria-hidden="true"></span>
          <strong>正在读取 Pinterest 图库</strong>
        </div>
      `;
        return;
      }
      if (pinterestError) {
        grid.innerHTML = `
        <div class="desk-pinterest-state is-error">
          <strong>加载失败</strong>
          <span>${escapeHtml(pinterestError)}</span>
          <button type="button" data-pinterest-retry>重试</button>
        </div>
      `;
        grid.querySelector('[data-pinterest-retry]')?.addEventListener('click', () => {
          loadPinterestLibrary({ refresh: true }).catch(error => DesktopResults.showError(error));
        });
        return;
      }
      if (pinterestLibraryMeta.enabled === false) {
        grid.innerHTML = `
        <div class="desk-pinterest-state">
          <strong>Pinterest 图库未启用</strong>
          <button type="button" data-pinterest-open-settings>打开设置</button>
        </div>
      `;
        grid.querySelector('[data-pinterest-open-settings]')?.addEventListener('click', () => {
          closeGallery();
          window.DesktopSettings?.open?.();
        });
        return;
      }

      const activeBoard = pinterestBoards.find(board => board.id === pinterestActiveBoardId);
      const pins = getVisiblePinterestPins();
      const profileName = pinterestProfile.name || pinterestProfile.username || 'Pinterest';
      const profileHandle = pinterestProfile.username ? `@${pinterestProfile.username}` : '';
      const authLabel = pinterestSyncStatus.source_mode === 'authenticated_browser' ? '已连接' : '本地缓存';
      const boardDownloadRun = activePinterestDownloadRun(activeBoard?.id);
      const firstPendingBoard = (
        activeBoard && pinterestBoardPendingCount(activeBoard) > 0
          ? activeBoard
          : pinterestBoards.find(board => pinterestBoardPendingCount(board) > 0)
      );
      maybeOpenPinterestSyncTip(firstPendingBoard);
      const showAllUpdatesTip = !activeBoard
        && firstPendingBoard
        && pinterestSyncTipBoardId === String(firstPendingBoard.id || '');
      const allLocalCount = pinterestPins.length;
      const allRemoteCount = Number(
        pinterestSyncStatus.remote_discovered_count
        ?? pinterestSyncStatus.remote_reported_count
        ?? allLocalCount
      );
      const allCountLabel = pinterestSyncStatus.checked_at && allRemoteCount > allLocalCount
        ? `${allLocalCount}/${allRemoteCount}`
        : String(allLocalCount);
      const boardButtons = [
        `<button type="button" class="${pinterestActiveBoardId ? '' : 'is-active'}${pinterestActionableUpdateCount(pinterestSyncStatus) ? ' has-updates' : ''}" data-pinterest-board="">
        <span class="desk-pinterest-board__cover is-all">P</span>
        <span><strong>全部</strong><em>${escapeHtml(allCountLabel)}</em></span>
      </button>`,
        ...pinterestBoards.map(board => `
        <button type="button" class="${board.id === pinterestActiveBoardId ? 'is-active' : ''}${pinterestBoardPendingCount(board) ? ' has-updates' : ''}" data-pinterest-board="${escapeHtml(board.id)}">
          ${board.cover_url
            ? `<img class="desk-pinterest-board__cover" src="${escapeHtml(board.cover_url)}" alt="" loading="lazy">`
            : '<span class="desk-pinterest-board__cover">P</span>'}
          <span><strong>${escapeHtml(board.name || '未命名图板')}</strong><em>${escapeHtml(pinterestBoardCountLabel(board))}</em></span>
        </button>
      `)
      ].join('');
      grid.innerHTML = `
      <div class="desk-pinterest-head">
        <div class="desk-pinterest-head__identity">
          ${pinterestProfile.url ? `
            <a class="desk-pinterest-profile-home-link" href="${escapeHtml(pinterestProfile.url)}" target="_blank" rel="noreferrer noopener" title="在 Pinterest 打开主页" aria-label="在 Pinterest 打开主页" data-pinterest-profile-home>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.02 0C5.4 0 .03 5.37.03 11.99c0 5.08 3.16 9.42 7.62 11.17-.11-.95-.2-2.4.04-3.44.22-.94 1.41-5.97 1.41-5.97s-.36-.72-.36-1.78c0-1.67.97-2.91 2.17-2.91 1.02 0 1.52.77 1.52 1.69 0 1.03-.66 2.57-1 4-.28 1.2.6 2.17 1.78 2.17 2.13 0 3.77-2.25 3.77-5.5 0-2.87-2.06-4.88-5.01-4.88-3.41 0-5.42 2.56-5.42 5.21 0 1.03.4 2.14.89 2.74.1.12.11.22.08.34-.09.38-.29 1.2-.33 1.36-.05.23-.17.27-.4.17-1.5-.7-2.43-2.88-2.43-4.64 0-3.78 2.75-7.25 7.92-7.25 4.16 0 7.39 2.96 7.39 6.92 0 4.13-2.6 7.45-6.21 7.45-1.21 0-2.36-.63-2.75-1.38l-.75 2.85c-.27 1.04-1 2.35-1.49 3.14 1.12.35 2.32.54 3.55.54 6.62 0 11.99-5.37 11.99-11.99C24.01 5.37 18.64 0 12.02 0Z"></path></svg>
            </a>
          ` : `
            <span class="desk-pinterest-profile-home-link is-static" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M12.02 0C5.4 0 .03 5.37.03 11.99c0 5.08 3.16 9.42 7.62 11.17-.11-.95-.2-2.4.04-3.44.22-.94 1.41-5.97 1.41-5.97s-.36-.72-.36-1.78c0-1.67.97-2.91 2.17-2.91 1.02 0 1.52.77 1.52 1.69 0 1.03-.66 2.57-1 4-.28 1.2.6 2.17 1.78 2.17 2.13 0 3.77-2.25 3.77-5.5 0-2.87-2.06-4.88-5.01-4.88-3.41 0-5.42 2.56-5.42 5.21 0 1.03.4 2.14.89 2.74.1.12.11.22.08.34-.09.38-.29 1.2-.33 1.36-.05.23-.17.27-.4.17-1.5-.7-2.43-2.88-2.43-4.64 0-3.78 2.75-7.25 7.92-7.25 4.16 0 7.39 2.96 7.39 6.92 0 4.13-2.6 7.45-6.21 7.45-1.21 0-2.36-.63-2.75-1.38l-.75 2.85c-.27 1.04-1 2.35-1.49 3.14 1.12.35 2.32.54 3.55.54 6.62 0 11.99-5.37 11.99-11.99C24.01 5.37 18.64 0 12.02 0Z"></path></svg>
            </span>
          `}
          <div>
            <strong>${escapeHtml(profileName)}</strong>
            <em>${escapeHtml([profileHandle, authLabel].filter(Boolean).join(' · '))}</em>
          </div>
        </div>
        <div class="desk-pinterest-head__actions">
          ${renderPinterestBoardDownload(boardDownloadRun, activeBoard)}
          ${showAllUpdatesTip ? `
            <div class="desk-pinterest-sync-tip desk-pinterest-sync-tip--all" data-pinterest-sync-tip role="status">
              <span>远程有 ${pinterestActionableUpdateCount(pinterestSyncStatus)} 张图片需要同步，请选择带红点的图板</span>
              <button type="button" data-pinterest-sync-tip-close title="关闭提示" aria-label="关闭提示">
                <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 6 8 8m0-8-8 8"></path></svg>
              </button>
            </div>
          ` : ''}
        </div>
      </div>
      <div class="desk-pinterest-boards" aria-label="Pinterest 图板">${boardButtons}</div>
      <div class="desk-pinterest-scroll" data-pinterest-scroll>
        <div class="desk-pinterest-grid">
          ${pins.length
            ? pins.map((pin, index) => renderGalleryImageCard(pin, index)).join('')
            : `<div class="desk-gallery-empty">${escapeHtml(
                activeBoard && pinterestBoardPendingCount(activeBoard)
                  ? `图板「${activeBoard.name}」暂无本地图片，请点击“同步图板”`
                  : (activeBoard ? `图板「${activeBoard.name}」暂无本地图片` : '本地暂无已同步的 Pinterest 图片')
              )}</div>`}
        </div>
      </div>
    `;
      grid.querySelectorAll('[data-pinterest-board]').forEach(button => {
        button.addEventListener('click', () => {
          const boardId = button.dataset.pinterestBoard || '';
          if (boardId === pinterestActiveBoardId) return;
          pinterestActiveBoardId = boardId;
          pinterestSyncTipBoardId = '';
          const nextBoard = pinterestBoards.find(board => board.id === pinterestActiveBoardId);
          maybeOpenPinterestSyncTip(nextBoard);
          rerenderPinterestPreservingScroll();
          renderGalleryStats();
          renderGallerySelection();
        });
      });
      grid.querySelector('[data-pinterest-sync-tip-close]')?.addEventListener('click', () => {
        pinterestSyncTipBoardId = '';
        rerenderPinterestPreservingScroll();
      });
      grid.querySelector('[data-pinterest-download-board]')?.addEventListener('click', event => {
        const boardId = event.currentTarget.dataset.pinterestDownloadBoard || '';
        pinterestSyncTipBoardId = '';
        downloadPinterestBoardToLocal(boardId).catch(error => DesktopResults.showError(error));
      });
      bindGalleryCardEvents();
    }

    function mergePinterestBoardStatus(localBoards = pinterestBoards, statusBoards = pinterestSyncStatus.boards) {
      const localCounts = new Map();
      pinterestPins.forEach(pin => {
        const boardId = String(pin.boardId || '');
        if (boardId) localCounts.set(boardId, Number(localCounts.get(boardId) || 0) + 1);
      });
      const localById = new Map(
        (Array.isArray(localBoards) ? localBoards : [])
          .filter(board => board?.id)
          .map(board => [String(board.id), board])
      );
      const statusById = new Map(
        (Array.isArray(statusBoards) ? statusBoards : [])
          .filter(board => board?.id)
          .map(board => [String(board.id), board])
      );
      const orderedIds = [
        ...statusById.keys(),
        ...[...localById.keys()].filter(boardId => !statusById.has(boardId))
      ];
      return orderedIds.map(boardId => {
        const local = localById.get(boardId) || {};
        const status = statusById.get(boardId) || {};
        const localCount = Number(localCounts.get(boardId) || status.local_count || local.cached_count || 0);
        const remoteReported = Number(status.remote_reported_count ?? local.pin_count ?? localCount);
        return {
          ...local,
          ...status,
          id: boardId,
          name: status.name || local.name || boardId,
          url: status.url || local.url || '',
          path: status.path || local.path || '',
          cover_url: local.cover_url || '',
          local_count: localCount,
          cached_count: localCount,
          pin_count: remoteReported,
          remote_reported_count: remoteReported,
          unsynced_count: Number(status.unsynced_count || 0),
          actionable_unsynced_count: pinterestActionableUpdateCount(status)
        };
      });
    }

    function applyPinterestSyncStatus(data) {
      pinterestSyncStatus = data && typeof data === 'object' ? data : {};
      if (!pinterestActionableUpdateCount(pinterestSyncStatus)) {
        pinterestSyncTipBoardId = '';
      }
      pinterestBoards = mergePinterestBoardStatus(pinterestBoards, pinterestSyncStatus.boards);
      const remoteProfile = pinterestSyncStatus.profile && typeof pinterestSyncStatus.profile === 'object'
        ? pinterestSyncStatus.profile
        : {};
      pinterestProfile = {
        ...pinterestProfile,
        ...remoteProfile,
        image_url: pinterestProfile.image_url || ''
      };
      pinterestLibraryMeta = {
        ...pinterestLibraryMeta,
        auth_configured: pinterestSyncStatus.auth_configured ?? pinterestLibraryMeta.auth_configured,
        auth_status: pinterestSyncStatus.auth_status || pinterestLibraryMeta.auth_status,
        source_mode: 'local_cache',
        remote_checked: Boolean(pinterestSyncStatus.checked_at),
        remote_error: '',
        remote_total: Number(
          pinterestSyncStatus.remote_discovered_count
          ?? pinterestSyncStatus.remote_reported_count
          ?? 0
        ),
        cached_count: pinterestPins.length
      };
      const activeBoard = pinterestBoards.find(board => board.id === pinterestActiveBoardId);
      const firstPendingBoard = (
        activeBoard && pinterestBoardPendingCount(activeBoard) > 0
          ? activeBoard
          : pinterestBoards.find(board => pinterestBoardPendingCount(board) > 0)
      );
      maybeOpenPinterestSyncTip(firstPendingBoard);
    }

    async function checkPinterestSyncStatus(options = {}) {
      if (!DesktopApi.getPinterestSyncStatus) return pinterestSyncStatus;
      const checkedAt = Date.parse(String(pinterestSyncStatus.checked_at || ''));
      if (
        !options.force
        && !options.refresh
        && Number.isFinite(checkedAt)
        && Date.now() - checkedAt < 60 * 1000
      ) {
        return pinterestSyncStatus;
      }
      if (pinterestSyncPromise) {
        if (!options.force) return pinterestSyncPromise;
        await pinterestSyncPromise;
      }
      const requestId = ++pinterestSyncRequestId;
      pinterestSyncChecking = true;
      if (getGalleryView() === 'pinterest') renderGalleryStats();
      pinterestSyncPromise = (async () => {
        try {
          const data = await DesktopApi.getPinterestSyncStatus({
            limit: PINTEREST_LIBRARY_LIMIT,
            refresh: Boolean(options.refresh)
          });
          if (requestId !== pinterestSyncRequestId) return pinterestSyncStatus;
          applyPinterestSyncStatus(data);
          if (getGalleryView() === 'pinterest') {
            rerenderPinterestPreservingScroll();
            renderGallerySelection();
          }
          return pinterestSyncStatus;
        } catch (error) {
          if (requestId === pinterestSyncRequestId) {
            pinterestLibraryMeta = {
              ...pinterestLibraryMeta,
              remote_error: error?.message || String(error)
            };
          }
          return pinterestSyncStatus;
        } finally {
          if (requestId === pinterestSyncRequestId) {
            pinterestSyncChecking = false;
            pinterestSyncPromise = null;
            if (getGalleryView() === 'pinterest') renderGalleryStats();
          }
        }
      })();
      return pinterestSyncPromise;
    }

    async function loadPinterestLibrary(options = {}) {
      if (!DesktopApi.getPinterestLibrary) return pinterestPins;
      const requestId = ++pinterestRequestId;
      const showLoading = !pinterestLibraryMeta.local_only && !pinterestPins.length;
      pinterestLoading = showLoading;
      pinterestError = '';
      if (getGalleryView() === 'pinterest' && showLoading) renderPinterestLibrary();
      try {
        const data = await DesktopApi.getPinterestLibrary({
          limit: PINTEREST_LIBRARY_LIMIT,
          localOnly: true
        });
        if (requestId !== pinterestRequestId) return pinterestPins;
        const localBoards = Array.isArray(data.boards) ? data.boards : [];
        pinterestProfile = data.profile && typeof data.profile === 'object' ? data.profile : {};
        pinterestPins = (Array.isArray(data.pins) ? data.pins : []).map(normalizePinterestPin);
        pinterestLibraryMeta = data || {};
        pinterestBoards = mergePinterestBoardStatus(localBoards, pinterestSyncStatus.boards);
        if (pinterestActiveBoardId && !pinterestBoards.some(board => board.id === pinterestActiveBoardId)) {
          pinterestActiveBoardId = '';
        }
        selectedGalleryIds.forEach(id => {
          if (id.startsWith('pinterest_') && !pinterestPins.some(pin => pin.id === id)) selectedGalleryIds.delete(id);
        });
        if (options.checkRemote !== false) {
          window.setTimeout(() => {
            checkPinterestSyncStatus({ refresh: Boolean(options.refresh) }).catch(() => {});
          }, 0);
        }
        return pinterestPins;
      } catch (error) {
        if (requestId === pinterestRequestId) pinterestError = error?.message || String(error);
        throw error;
      } finally {
        if (requestId === pinterestRequestId) {
          pinterestLoading = false;
          if (getGalleryView() === 'pinterest') {
            renderPinterestLibrary();
            renderGallerySelection();
          }
        }
      }
    }

    function bindPinterestModalEvents() {
      els.deskPinterestAnalysisCopyBtn?.addEventListener('click', () => {
        copyPinterestAnalysisPrompt().catch(error => galleryError(error, '复制提示词失败'));
      });
      els.deskPinterestAnalysisSendBtn?.addEventListener('click', () => {
        try {
          sendPinterestAnalysisToTextNode();
        } catch (error) {
          galleryError(error, '发送到文本节点失败');
        }
      });
      els.deskPinterestAnalysisCloseBtn?.addEventListener('click', () => closePinterestAnalysisModal());
      els.deskPinterestAnalysisModal?.addEventListener('click', event => {
        if (
          event.target === els.deskPinterestAnalysisModal
          || event.target?.closest?.('[data-pinterest-analysis-backdrop]')
        ) {
          closePinterestAnalysisModal();
        }
      });
      els.deskPinterestSplitResults?.addEventListener('change', event => {
        const checkbox = event.target?.closest?.('[data-pinterest-split-candidate]');
        if (!checkbox || pinterestSplitBusy) return;
        const candidate = pinterestSplitCandidates[Number(checkbox.dataset.pinterestSplitCandidate)];
        if (!candidate) return;
        candidate.selected = checkbox.checked;
        checkbox.closest('.desk-pinterest-split-modal__candidate')
          ?.classList.toggle('is-selected', checkbox.checked);
        const selectedCount = pinterestSplitSelectedCandidates().length;
        pinterestSplitStatus = `已选 ${selectedCount} 个素材块。`;
        if (els.deskPinterestSplitStatus) {
          els.deskPinterestSplitStatus.textContent = pinterestSplitStatus;
        }
        if (els.deskPinterestSplitCopyBtn) {
          els.deskPinterestSplitCopyBtn.disabled = !selectedCount;
        }
        if (els.deskPinterestSplitSaveBtn) {
          els.deskPinterestSplitSaveBtn.disabled = !selectedCount;
        }
      });
      els.deskPinterestSplitCopyBtn?.addEventListener('click', () => {
        copyPinterestSplitCandidates().catch(error => galleryError(error, '复制素材块失败'));
      });
      els.deskPinterestSplitSaveBtn?.addEventListener('click', () => {
        savePinterestSplitCandidates().catch(error => galleryError(error, '存储素材块失败'));
      });
      els.deskPinterestSplitCloseBtn?.addEventListener('click', () => closePinterestSplitModal());
      els.deskPinterestSplitModal?.addEventListener('click', event => {
        if (
          event.target === els.deskPinterestSplitModal
          || event.target?.closest?.('[data-pinterest-split-backdrop]')
        ) {
          closePinterestSplitModal();
        }
      });
    }

    function renderPinterestGalleryStats() {
      const authStatus = pinterestSyncStatus.auth_status || pinterestLibraryMeta.auth_status;
      const authLabel = authStatus === 'authenticated'
        ? '已登录'
        : ((pinterestSyncStatus.auth_configured || pinterestLibraryMeta.auth_configured) ? '待验证' : '公开资料');
      const localCount = pinterestPins.length;
      const remoteChecked = Boolean(pinterestSyncStatus.checked_at);
      const remoteCount = Number(
        pinterestSyncStatus.remote_discovered_count
        ?? pinterestSyncStatus.remote_reported_count
        ?? 0
      );
      const remoteReportedCount = Number(pinterestSyncStatus.remote_reported_count || remoteCount);
      const platformCountGap = Math.max(0, remoteReportedCount - remoteCount);
      const pendingCount = pinterestActionableUpdateCount(pinterestSyncStatus);
      const unavailableCount = pinterestStatusCount(pinterestSyncStatus, [
        'unavailable_count',
        'unavailable_unsynced_count',
        'unavailable'
      ]);
      const unresolvedCount = pinterestStatusCount(pinterestSyncStatus, [
        'unresolved_count',
        'unresolved_unsynced_count',
        'unresolved'
      ]);
      const remoteError = String(pinterestLibraryMeta.remote_error || '');
      els.deskGalleryStats.innerHTML = [
        `图板 ${Number(pinterestBoards.length || 0).toLocaleString('zh-CN')}`,
        `当前 ${Number(getVisiblePinterestPins().length || 0).toLocaleString('zh-CN')}`,
        `本地 ${Number(localCount).toLocaleString('zh-CN')}`,
        pinterestSyncChecking
          ? '远程 检查中'
          : (
              remoteError
                ? '远程检查失败'
                : (remoteChecked ? `远程 ${remoteCount.toLocaleString('zh-CN')}` : '远程 未检查')
            ),
        pendingCount ? `待同步 ${pendingCount.toLocaleString('zh-CN')}` : null,
        unavailableCount ? `不可同步 ${unavailableCount.toLocaleString('zh-CN')}` : null,
        unresolvedCount ? `待解析 ${unresolvedCount.toLocaleString('zh-CN')}` : null,
        platformCountGap ? `平台统计差 ${platformCountGap.toLocaleString('zh-CN')}` : null,
        authLabel,
        '本地缓存'
      ].filter(Boolean).map(item => `<span>${escapeHtml(item)}</span>`).join('');
    }

    function refreshPinterestLibrary() {
      if (!pinterestLibraryMeta.ok && !pinterestLoading) {
        loadPinterestLibrary().catch(error => DesktopResults.showError(error));
      } else {
        renderPinterestLibrary();
        checkPinterestSyncStatus().catch(() => {});
      }
    }

    return {
      load: loadPinterestLibrary,
      render: renderPinterestLibrary,
      refresh: refreshPinterestLibrary,
      checkSyncStatus: checkPinterestSyncStatus,
      renderStats: renderPinterestGalleryStats,
      bindModalEvents: bindPinterestModalEvents,
      pins: () => pinterestPins,
      visiblePins: getVisiblePinterestPins,
      closeAnalysisModal: closePinterestAnalysisModal,
      closeSplitModal: closePinterestSplitModal,
      analyze: analyzePinterestAsset,
      split: splitPinterestPrompt,
      downloadPin: downloadPinterestPinToLocal,
      isPinDownloading: pinId => pinterestPinDownloads.has(pinId),
      isPinAnalyzing: pinId => pinterestAnalyzingPins.has(pinId),
      isPinSplitting: pinId => pinterestSplittingPins.has(pinId),
      splitSourceImage: pinterestSplitSourceImage,
      splitCanRun: pinterestSplitCanRun
    };
  }

  window.DesktopGalleryPinterest = { create };
})();
