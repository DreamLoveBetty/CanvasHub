// Prompt sources in the gallery workspace: the synced prompt-source libraries, their tabs,
// taxonomy filters, sync runs and the virtualised source card list.
// desktop-history.js owns the gallery view, search, selection, card events and the virtual
// grid; it passes them in explicitly and reads source state only through the returned API.
(function () {
  function create({
    bindGalleryCardEvents, disposeGalleryVirtualContainer, els, escapeHtml,
    formatPreviewTime, galleryMessage, normalizeGalleryAsset, parseTags, preferredThumbUrl,
    renderGallery, renderGallerySelection, renderGalleryStats, renderVirtualGalleryCards,
    resetGalleryRenderLimit, scheduleGalleryRender, scheduleGalleryVirtualRender,
    selectedGalleryIds, getGalleryView, getGalleryQuery, getGalleryTag,
    getGalleryVirtualDataRevision
  }) {
    let promptSources = [];
    let promptSourceItems = [];
    let promptSourceFilter = 'all';
    let promptSourceTaxonomyFilters = { style: '', subject: '', type: '' };
    let promptSourceTaxonomyFacets = { style: [], subject: [], type: [] };
    let promptSourceTaxonomyCollapsed = true;
    let promptSourceTotal = 0;
    let promptSourceSyncRunId = '';
    let promptSourceSyncRun = null;
    let lastPromptSourceSyncRun = null;
    let promptSourceSyncTimer = null;

    let promptSourceVisibleItemsCache = { revision: -1, items: [] };
    const PROMPT_SOURCE_TAXONOMY_GROUPS = [
      ['style', '风格'],
      ['subject', '主体'],
      ['type', '类型']
    ];

    function normalizeTaxonomy(value) {
      const source = value && typeof value === 'object' ? value : {};
      return {
        style: parseTags(source.style || []),
        subject: parseTags(source.subject || []),
        type: parseTags(source.type || [])
      };
    }

    function normalizeTaxonomyFacets(value) {
      const source = value && typeof value === 'object' ? value : {};
      const result = { style: [], subject: [], type: [] };
      PROMPT_SOURCE_TAXONOMY_GROUPS.forEach(([key]) => {
        const seen = new Set();
        result[key] = (Array.isArray(source[key]) ? source[key] : [])
          .map(item => {
            const label = String(item?.label || item?.value || '').trim();
            const facetValue = String(item?.value || label).trim();
            if (!label || !facetValue || seen.has(facetValue)) return null;
            seen.add(facetValue);
            return {
              value: facetValue,
              label,
              count: Number(item?.count || 0)
            };
          })
          .filter(Boolean);
      });
      return result;
    }

    function normalizePromptSourceItem(item) {
      const taxonomy = normalizeTaxonomy(item?.taxonomy || item?.promptTaxonomy);
      return normalizeGalleryAsset({
        ...item,
        id: item?.itemId || item?.item_id || item?.id || '',
        asset_id: item?.itemId || item?.item_id || item?.id || '',
        taskId: item?.itemId || item?.id || '',
        title: item?.title || '远程提示词',
        imageUrl: item?.imageUrl || item?.image_url || '',
        imagePath: item?.imagePath || item?.imageUrl || '',
        thumbUrl: preferredThumbUrl(item?.thumbUrl || item?.thumb_url, item?.imageUrl || item?.image_url || ''),
        imagePaths: Array.isArray(item?.imagePaths) ? item.imagePaths : (Array.isArray(item?.image_paths) ? item.image_paths : []),
        sourceSlug: item?.sourceSlug || item?.source_slug || '',
        sourceName: item?.sourceName || item?.source_name || '',
        repoUrl: item?.repoUrl || item?.repo_url || '',
        sourceUrl: item?.sourceUrl || item?.source_url || '',
        provider: 'remote',
        providerLabel: item?.sourceName || item?.source_name || '远程源',
        sourceKind: 'remote_source',
        hasTaskRecord: false,
        favorite: false,
        hidden: false,
        tags: parseTags(item?.tags),
        taxonomy,
        promptTaxonomy: taxonomy,
        params: {
          ...(item?.params || {}),
          source_kind: 'remote_prompt',
          prompt_source: item?.sourceSlug || item?.source_slug || '',
          source_repo: item?.repoUrl || item?.repo_url || '',
          source_url: item?.sourceUrl || item?.source_url || ''
        }
      });
    }

    function normalizePromptSourceRun(run) {
      if (!run || typeof run !== 'object') return null;
      const progressPercent = Number(run.progress_percent ?? run.progressPercent ?? 0);
      return {
        ...run,
        runId: String(run.run_id || run.runId || ''),
        sourceSlug: String(run.source_slug || run.sourceSlug || ''),
        status: String(run.status || '').trim(),
        phase: String(run.phase || '').trim(),
        message: String(run.message || '').trim(),
        currentSource: String(run.current_source || run.currentSource || ''),
        currentSourceName: String(run.current_source_name || run.currentSourceName || ''),
        sourceIndex: Number(run.source_index ?? run.sourceIndex ?? 0),
        totalSources: Number(run.total_sources ?? run.totalSources ?? 0),
        processedItems: Number(run.processed_items ?? run.processedItems ?? 0),
        totalItems: Number(run.total_items ?? run.totalItems ?? 0),
        processedImages: Number(run.processed_images ?? run.processedImages ?? 0),
        totalImages: Number(run.total_images ?? run.totalImages ?? 0),
        itemCount: Number(run.item_count ?? run.itemCount ?? 0),
        imageCount: Number(run.image_count ?? run.imageCount ?? 0),
        errorCount: Number(run.error_count ?? run.errorCount ?? 0),
        startedAt: Number(run.started_at ?? run.startedAt ?? 0),
        finishedAt: Number(run.finished_at ?? run.finishedAt ?? 0),
        progressPercent: Math.max(0, Math.min(100, Number.isFinite(progressPercent) ? progressPercent : 0))
      };
    }

    function pickLatestPromptSourceRun(sources, latestRun) {
      const candidates = [normalizePromptSourceRun(latestRun)];
      (Array.isArray(sources) ? sources : []).forEach(source => {
        candidates.push(normalizePromptSourceRun(source?.lastRun));
      });
      return candidates
        .filter(Boolean)
        .sort((a, b) => Math.max(b.finishedAt, b.startedAt) - Math.max(a.finishedAt, a.startedAt))[0] || null;
    }

    function getVisiblePromptSourceItems() {
      if (promptSourceVisibleItemsCache.revision === getGalleryVirtualDataRevision()) {
        return promptSourceVisibleItemsCache.items;
      }
      const query = getGalleryQuery().trim().toLowerCase();
      const tagQuery = getGalleryTag().trim().replace(/^#/, '').toLowerCase();
      const items = promptSourceItems.filter(asset => {
        const taxonomy = normalizeTaxonomy(asset.taxonomy || asset.promptTaxonomy);
        if (promptSourceFilter !== 'all' && asset.params?.prompt_source !== promptSourceFilter && asset.sourceSlug !== promptSourceFilter) return false;
        if (promptSourceTaxonomyFilters.style && !taxonomy.style.includes(promptSourceTaxonomyFilters.style)) return false;
        if (promptSourceTaxonomyFilters.subject && !taxonomy.subject.includes(promptSourceTaxonomyFilters.subject)) return false;
        if (promptSourceTaxonomyFilters.type && !taxonomy.type.includes(promptSourceTaxonomyFilters.type)) return false;
        const tags = (tagQuery || query) ? parseTags(asset.tags) : [];
        if (tagQuery && !tags.some(tag => tag.toLowerCase().includes(tagQuery))) return false;
        if (!query) return true;
        const haystack = [
          asset.title,
          asset.prompt,
          asset.providerLabel,
          asset.file,
          asset.sourceUrl,
          tags.join(' ')
        ].filter(Boolean).join(' ').toLowerCase();
        return haystack.includes(query);
      });
      promptSourceVisibleItemsCache = { revision: getGalleryVirtualDataRevision(), items };
      return items;
    }

    function promptSourceSummaryChips() {
      const itemCount = promptSources.reduce((sum, source) => sum + Number(source.itemCount || 0), 0);
      const imageCount = promptSources.reduce((sum, source) => sum + Number(source.imageCount || 0), 0);
      const staleCount = promptSources.reduce((sum, source) => sum + Number(source.staleItemCount || source.stale_item_count || 0), 0);
      const activeSource = promptSourceFilter === 'all'
        ? null
        : promptSources.find(source => source.slug === promptSourceFilter);
      const activeName = promptSourceFilter === 'all'
        ? '全部远程源'
        : (activeSource?.name || '远程源');
      const activeItems = activeSource ? Number(activeSource.itemCount || 0) : Number(promptSourceTotal || itemCount);
      const activeImages = activeSource ? Number(activeSource.imageCount || 0) : imageCount;
      const activeStale = activeSource ? Number(activeSource.staleItemCount || activeSource.stale_item_count || 0) : staleCount;
      const activePath = activeSource?.localPath || activeSource?.local_path || '';
      const activeRun = normalizePromptSourceRun(promptSourceSyncRun || lastPromptSourceSyncRun);
      const syncLabel = activeRun?.status === 'running' ? `同步 ${Math.max(1, Math.round(activeRun.progressPercent || 1))}%` : '';
      const chips = [
        { label: activeName, type: 'name' },
        promptSourceFilter === 'all' ? { label: `源 ${promptSources.length.toLocaleString('zh-CN')}` } : null,
        { label: `条目 ${activeItems.toLocaleString('zh-CN')}` },
        { label: `本地图 ${activeImages.toLocaleString('zh-CN')}` },
        activeStale ? { label: `已删 ${activeStale.toLocaleString('zh-CN')}` } : null,
        activePath ? { label: `路径 ${activePath}`, type: 'path' } : null,
        ...PROMPT_SOURCE_TAXONOMY_GROUPS
          .map(([key, label]) => promptSourceTaxonomyFilters[key] ? { label: `${label} ${promptSourceTaxonomyFilters[key]}` } : null),
        syncLabel ? { label: syncLabel, type: 'sync' } : null
      ].filter(Boolean);
      return chips.map(item => {
        const typeClass = item.type ? ` desk-prompt-source-chip--${item.type}` : '';
        return `<span class="desk-prompt-source-chip${typeClass}" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>`;
      }).join('');
    }

    function renderPromptSourceTabs() {
      const buttons = [
        `<button type="button" class="${promptSourceFilter === 'all' ? 'is-active' : ''}" data-prompt-source-filter="all">全部</button>`,
        ...promptSources.map(source => `
        <button type="button" class="${promptSourceFilter === source.slug ? 'is-active' : ''}" data-prompt-source-filter="${escapeHtml(source.slug)}" title="${escapeHtml(source.localPath || '')}">
          ${escapeHtml(source.name)}
        </button>
      `)
      ];
      return `<div class="desk-prompt-source-tabs"><i class="desk-prompt-source-tabs__slider" aria-hidden="true"></i>${buttons.join('')}</div>`;
    }

    function renderPromptSourceTaxonomyFilters() {
      const activeFilters = PROMPT_SOURCE_TAXONOMY_GROUPS
        .map(([key, label]) => promptSourceTaxonomyFilters[key] ? `${label}: ${promptSourceTaxonomyFilters[key]}` : '')
        .filter(Boolean);
      const hasActiveFilters = activeFilters.length > 0;
      const rows = PROMPT_SOURCE_TAXONOMY_GROUPS.map(([key, label]) => {
        const facets = Array.isArray(promptSourceTaxonomyFacets[key]) ? promptSourceTaxonomyFacets[key] : [];
        const activeValue = promptSourceTaxonomyFilters[key] || '';
        const buttons = [
          `<button type="button" class="${activeValue ? '' : 'is-active'}" data-prompt-taxonomy-group="${escapeHtml(key)}" data-prompt-taxonomy-value="">全部</button>`,
          ...facets.map(facet => `
          <button type="button" class="${activeValue === facet.value ? 'is-active' : ''}" data-prompt-taxonomy-group="${escapeHtml(key)}" data-prompt-taxonomy-value="${escapeHtml(facet.value)}">
            ${escapeHtml(facet.label)} <span>${Number(facet.count || 0).toLocaleString('zh-CN')}</span>
          </button>
        `)
        ];
        return `
        <div class="desk-prompt-source-taxonomy__row">
          <strong>${escapeHtml(label)}</strong>
          <div>${buttons.join('')}</div>
        </div>
      `;
      });
      return `
      <div class="desk-prompt-source-taxonomy ${promptSourceTaxonomyCollapsed ? 'is-collapsed' : ''}">
        <div class="desk-prompt-source-taxonomy__head">
          <button type="button" data-prompt-taxonomy-toggle>
            ${promptSourceTaxonomyCollapsed ? '展开分类' : '收起分类'}
          </button>
          <span>${hasActiveFilters ? escapeHtml(activeFilters.join(' / ')) : '风格 / 主体 / 类型'}</span>
          ${hasActiveFilters ? '<button type="button" data-prompt-taxonomy-clear>清除</button>' : ''}
        </div>
        ${promptSourceTaxonomyCollapsed ? '' : `<div class="desk-prompt-source-taxonomy__body">${rows.join('')}</div>`}
      </div>
    `;
    }

    function renderPromptSourceSyncStatus() {
      const run = normalizePromptSourceRun(promptSourceSyncRun || lastPromptSourceSyncRun);
      if (!run || run.status !== 'running') return '';
      const isRunning = run.status === 'running';
      const percent = isRunning ? Math.max(1, Math.round(run.progressPercent || 1)) : 100;
      const title = isRunning
        ? `同步中 ${percent}%`
        : `${run.status === 'succeeded' ? '同步完成' : (run.status === 'canceled' ? '已停止同步' : '同步结束')} · ${formatPreviewTime(run.finishedAt)}`;
      const sourceText = run.currentSourceName
        ? `${run.currentSourceName}${run.totalSources ? ` ${run.sourceIndex || 1}/${run.totalSources}` : ''}`
        : (run.sourceSlug === 'all' ? '全部远程源' : '远程源');
      const itemText = run.totalItems
        ? `条目 ${run.processedItems}/${run.totalItems}`
        : (run.itemCount ? `条目 ${run.itemCount}` : '');
      const imageText = run.totalImages
        ? `图片 ${run.processedImages}/${run.totalImages}`
        : (run.imageCount ? `图片 ${run.imageCount}` : '');
      const errorText = run.errorCount ? `失败 ${run.errorCount}` : '';
      const detail = [run.phase, sourceText, itemText, imageText, errorText].filter(Boolean).join(' · ');
      const message = run.message ? run.message.slice(0, 140) : '';
      return `
      <div class="desk-prompt-source-sync ${isRunning ? 'is-running' : 'is-done'}">
        <div class="desk-prompt-source-sync__top">
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(detail)}</span>
        </div>
        <div class="desk-prompt-source-sync__bar" aria-hidden="true">
          <i style="width: ${percent}%"></i>
        </div>
        ${message ? `<em>${escapeHtml(message)}</em>` : ''}
      </div>
    `;
    }

    function renderPromptSourceHeader() {
      const activeRun = normalizePromptSourceRun(promptSourceSyncRun);
      const isRunning = activeRun?.status === 'running';
      return `
      <section class="desk-prompt-source-head">
        <div class="desk-prompt-source-head__main">
          <div>
            <strong>远程源资料库</strong>
            <div class="desk-prompt-source-head__meta">${promptSourceSummaryChips()}</div>
          </div>
        </div>
        <div class="desk-prompt-source-actions">
          ${isRunning ? `<button type="button" class="is-danger" data-prompt-source-stop="${escapeHtml(activeRun.runId || promptSourceSyncRunId || '')}">停止同步</button>` : ''}
          ${promptSourceFilter !== 'all' ? `<button type="button" data-prompt-source-sync="${escapeHtml(promptSourceFilter)}">同步当前</button>` : ''}
          <button type="button" data-prompt-source-sync="all">同步全部</button>
          <button type="button" data-prompt-source-refresh>刷新</button>
        </div>
      </section>
    `;
    }

    function renderPromptSources() {
      const grid = els.deskGalleryGrid;
      if (!grid) return;
      disposeGalleryVirtualContainer(grid.querySelector('[data-prompt-source-scroll]'));
      const items = getVisiblePromptSourceItems();
      grid.innerHTML = [
        `<div class="desk-prompt-source-controls">
        ${renderPromptSourceHeader()}
        ${renderPromptSourceTabs()}
        ${renderPromptSourceTaxonomyFilters()}
        ${renderPromptSourceSyncStatus()}
      </div>`,
        `<div class="desk-prompt-source-scroll" data-prompt-source-scroll>
        ${items.length ? '' : '<div class="desk-gallery-empty">还没有同步远程源，或没有匹配的提示词。</div>'}
      </div>`
      ].join('');
      if (items.length) {
        const scroller = grid.querySelector('[data-prompt-source-scroll]');
        renderVirtualGalleryCards(scroller, items, {
          revision: getGalleryVirtualDataRevision(),
          viewKey: 'sources',
        });
      }
      bindPromptSourceEvents();
      bindGalleryCardEvents();
      schedulePromptSourceTabSlider();
    }

    function schedulePromptSourceTabSlider() {
      if (getGalleryView() !== 'sources') return;
      window.requestAnimationFrame(updatePromptSourceTabSlider);
    }

    function updatePromptSourceTabSlider() {
      const tabs = els.deskGalleryGrid?.querySelector('.desk-prompt-source-tabs');
      const slider = tabs?.querySelector('.desk-prompt-source-tabs__slider');
      const active = tabs?.querySelector('button.is-active');
      if (!tabs || !slider || !active) return;
      slider.style.setProperty('--prompt-source-slider-x', `${active.offsetLeft}px`);
      slider.style.setProperty('--prompt-source-slider-w', `${active.offsetWidth}px`);
    }

    function bindPromptSourceEvents() {
      els.deskGalleryGrid?.querySelectorAll('[data-prompt-source-filter]').forEach(button => {
        button.addEventListener('click', () => {
          promptSourceFilter = button.dataset.promptSourceFilter || 'all';
          promptSourceTaxonomyFilters = { style: '', subject: '', type: '' };
          promptSourceTaxonomyCollapsed = true;
          resetGalleryRenderLimit();
          loadPromptSourceItems().catch(error => DesktopResults.showError(error));
        });
      });
      els.deskGalleryGrid?.querySelector('.desk-prompt-source-tabs')?.addEventListener('scroll', schedulePromptSourceTabSlider, { passive: true });
      els.deskGalleryGrid?.querySelector('[data-prompt-taxonomy-toggle]')?.addEventListener('click', () => {
        promptSourceTaxonomyCollapsed = !promptSourceTaxonomyCollapsed;
        renderGallery();
      });
      els.deskGalleryGrid?.querySelector('[data-prompt-taxonomy-clear]')?.addEventListener('click', () => {
        promptSourceTaxonomyFilters = { style: '', subject: '', type: '' };
        promptSourceTaxonomyCollapsed = true;
        resetGalleryRenderLimit();
        loadPromptSourceItems().catch(error => DesktopResults.showError(error));
      });
      els.deskGalleryGrid?.querySelectorAll('[data-prompt-taxonomy-group]').forEach(button => {
        button.addEventListener('click', () => {
          const group = button.dataset.promptTaxonomyGroup || '';
          if (!Object.prototype.hasOwnProperty.call(promptSourceTaxonomyFilters, group)) return;
          promptSourceTaxonomyFilters = {
            ...promptSourceTaxonomyFilters,
            [group]: button.dataset.promptTaxonomyValue || ''
          };
          resetGalleryRenderLimit();
          loadPromptSourceItems().catch(error => DesktopResults.showError(error));
        });
      });
      els.deskGalleryGrid?.querySelectorAll('[data-prompt-source-sync]').forEach(button => {
        button.addEventListener('click', () => {
          const source = button.dataset.promptSourceSync || 'all';
          syncPromptSources(source, button).catch(error => DesktopResults.showError(error));
        });
      });
      els.deskGalleryGrid?.querySelectorAll('[data-prompt-source-stop]').forEach(button => {
        button.addEventListener('click', () => {
          stopPromptSourceSync(button.dataset.promptSourceStop || promptSourceSyncRunId, button).catch(error => DesktopResults.showError(error));
        });
      });
      els.deskGalleryGrid?.querySelector('[data-prompt-source-refresh]')?.addEventListener('click', () => {
        refreshPromptSources().catch(error => DesktopResults.showError(error));
      });
      els.deskGalleryGrid?.querySelector('[data-prompt-source-scroll]')?.addEventListener('scroll', event => {
        scheduleGalleryVirtualRender(event.currentTarget);
      }, { passive: true });
    }

    async function loadPromptSources() {
      if (!DesktopApi.getPromptSources) return promptSources;
      const data = await DesktopApi.getPromptSources();
      promptSources = Array.isArray(data.sources) ? data.sources : [];
      const latestRun = pickLatestPromptSourceRun(promptSources, data.latestRun);
      if (latestRun?.status === 'running') {
        promptSourceSyncRun = latestRun;
        promptSourceSyncRunId = latestRun.runId || promptSourceSyncRunId;
        if (promptSourceSyncRunId && !promptSourceSyncTimer) {
          promptSourceSyncTimer = window.setTimeout(() => {
            pollPromptSourceRun(promptSourceSyncRunId).catch(error => DesktopResults.showError(error));
          }, 600);
        }
      } else if (latestRun && promptSourceSyncRun?.status !== 'running') {
        promptSourceSyncRun = latestRun;
        lastPromptSourceSyncRun = latestRun;
        promptSourceSyncRunId = '';
      }
      if (getGalleryView() === 'sources') scheduleGalleryRender();
      return promptSources;
    }

    async function loadPromptSourceItems() {
      if (!DesktopApi.getPromptSourceItems) return promptSourceItems;
      const source = promptSourceFilter === 'all' ? '' : promptSourceFilter;
      const pageSize = 1000;
      const baseOptions = {
        source,
        query: getGalleryQuery(),
        tag: getGalleryTag(),
        style: promptSourceTaxonomyFilters.style,
        subject: promptSourceTaxonomyFilters.subject,
        type: promptSourceTaxonomyFilters.type
      };
      const firstPage = await DesktopApi.getPromptSourceItems({
        ...baseOptions,
        limit: pageSize,
        offset: 0
      });
      const total = Number(firstPage.total || 0);
      const pages = [firstPage];
      for (let offset = pageSize; total && offset < total; offset += pageSize) {
        pages.push(await DesktopApi.getPromptSourceItems({
          ...baseOptions,
          limit: pageSize,
          offset
        }));
      }
      promptSourceItems = pages
        .flatMap(page => Array.isArray(page.items) ? page.items : [])
        .map(normalizePromptSourceItem);
      promptSourceTaxonomyFacets = normalizeTaxonomyFacets(firstPage.taxonomyFacets || firstPage.taxonomy_facets);
      promptSourceTotal = total || promptSourceItems.length;
      selectedGalleryIds.forEach(id => {
        if (id.startsWith('remote_') && !promptSourceItems.some(asset => asset.id === id)) selectedGalleryIds.delete(id);
      });
      if (getGalleryView() === 'sources') scheduleGalleryRender({ selection: true });
      return promptSourceItems;
    }

    async function refreshPromptSources() {
      resetGalleryRenderLimit();
      await loadPromptSources();
      await loadPromptSourceItems();
    }

    async function pollPromptSourceRun(runId) {
      if (!runId || !DesktopApi.getPromptSourceRun) return;
      const data = await DesktopApi.getPromptSourceRun(runId);
      const run = normalizePromptSourceRun(data.run || {});
      if (!run) return;
      promptSourceSyncRun = run;
      if (getGalleryView() === 'sources') {
        renderGallery();
        renderGallerySelection();
      } else {
        renderGalleryStats();
      }
      if (run.status === 'running') {
        galleryMessage(`远程源同步中：${Math.max(1, Math.round(run.progressPercent || 1))}%`);
        if (promptSourceSyncTimer) window.clearTimeout(promptSourceSyncTimer);
        promptSourceSyncTimer = window.setTimeout(() => {
          pollPromptSourceRun(runId).catch(error => DesktopResults.showError(error));
        }, 1800);
        return;
      }
      promptSourceSyncRunId = '';
      if (promptSourceSyncTimer) {
        window.clearTimeout(promptSourceSyncTimer);
        promptSourceSyncTimer = null;
      }
      promptSourceSyncRun = run;
      lastPromptSourceSyncRun = run;
      await refreshPromptSources();
      const itemCount = Number(run.itemCount || 0);
      const imageCount = Number(run.imageCount || 0);
      const finishedAt = formatPreviewTime(run.finishedAt);
      galleryMessage(run.status === 'succeeded'
        ? `远程源同步完成：${finishedAt}，${itemCount} 条提示词，${imageCount} 张图片。`
        : (run.status === 'canceled'
          ? `远程源同步已停止：${finishedAt}。`
          : `远程源同步结束：${finishedAt}，${run.message || '有部分失败'}`));
    }

    async function stopPromptSourceSync(runId = '', button = null) {
      const cleanRunId = String(runId || promptSourceSyncRunId || '').trim();
      if (!cleanRunId || !DesktopApi.stopPromptSourceSync) return;
      const originalText = button?.textContent || '';
      try {
        if (button) {
          button.disabled = true;
          button.textContent = '停止中';
        }
        await DesktopApi.stopPromptSourceSync(cleanRunId);
        promptSourceSyncRun = normalizePromptSourceRun({
          ...(promptSourceSyncRun || {}),
          run_id: cleanRunId,
          status: 'running',
          phase: '停止中',
          message: '正在停止远程源同步'
        });
        galleryMessage('已请求停止远程源同步。');
        if (getGalleryView() === 'sources') renderGallery();
        if (!promptSourceSyncTimer) {
          promptSourceSyncTimer = window.setTimeout(() => {
            pollPromptSourceRun(cleanRunId).catch(error => DesktopResults.showError(error));
          }, 600);
        }
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = originalText;
        }
      }
    }

    async function syncPromptSources(source = 'all', button = null) {
      if (!DesktopApi.syncPromptSource) return;
      const originalText = button?.textContent || '';
      try {
        if (button) {
          button.disabled = true;
          button.textContent = source === 'all' ? '同步中' : '拉取中';
        }
        promptSourceSyncRun = normalizePromptSourceRun({
          source_slug: source,
          status: 'running',
          phase: '准备同步',
          message: '同步任务已创建，正在连接远程源',
          started_at: Math.floor(Date.now() / 1000),
          total_sources: source === 'all' ? promptSources.length : 1,
          progress_percent: 1
        });
        if (getGalleryView() === 'sources') renderGallery();
        const result = await DesktopApi.syncPromptSource(source);
        promptSourceSyncRunId = result.run_id || '';
        promptSourceSyncRun = normalizePromptSourceRun({
          ...promptSourceSyncRun,
          run_id: promptSourceSyncRunId,
          message: '同步任务已开始，正在计算进度'
        });
        if (getGalleryView() === 'sources') renderGallery();
        galleryMessage('远程源同步已开始，正在计算进度。');
        if (promptSourceSyncRunId) await pollPromptSourceRun(promptSourceSyncRunId);
      } catch (error) {
        promptSourceSyncRunId = '';
        promptSourceSyncRun = null;
        if (getGalleryView() === 'sources') renderGallery();
        throw error;
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = originalText;
        }
      }
    }

    function invalidatePromptSourceVisibleItems() {
      promptSourceVisibleItemsCache = { revision: -1, items: [] };
    }

    return {
      load: loadPromptSources,
      refresh: refreshPromptSources,
      render: renderPromptSources,
      visibleItems: getVisiblePromptSourceItems,
      items: () => promptSourceItems,
      scheduleTabSlider: schedulePromptSourceTabSlider,
      invalidateVisibleCache: invalidatePromptSourceVisibleItems
    };
  }

  window.DesktopGalleryPromptSources = { create };
})();
