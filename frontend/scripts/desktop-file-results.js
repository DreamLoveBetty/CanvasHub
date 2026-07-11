(function () {
  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function isFileResultNode(resultNodeId) {
    return DesktopState.state.canvas.nodes?.[resultNodeId]?.type === 'file_output';
  }

  function formatSize(bytes) {
    const value = Number(bytes || 0);
    if (!Number.isFinite(value) || value <= 0) return '';
    if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
    if (value >= 1024) return `${Math.round(value / 1024)} KB`;
    return `${value} B`;
  }

  function getManifest(output, task) {
    return output?.fileManifest || task?.file_manifest || output?.params?.file_manifest || null;
  }

  function artifactKind(manifest, output, task) {
    const params = task?.params || output?.params || {};
    const value = String(
      manifest?.artifact_type
      || params.gpt_task_type
      || params.gptTaskType
      || params.task_type
      || 'file'
    ).toLowerCase();
    if (value === 'ppt' || value === 'psd') return value.toUpperCase();
    return 'PPT / PSD';
  }

  function fileIconHtml() {
    return `
      <div class="desk-file-result-empty__icon" aria-hidden="true">
        <svg viewBox="0 0 48 48">
          <path class="desk-file-empty-back" d="M11 13.5h16l8 8V39H11z"></path>
          <path class="desk-file-empty-front" d="M17 8.5h15l7 7V34H17z"></path>
          <path class="desk-file-empty-fold" d="M31.5 9v7h7"></path>
          <path class="desk-file-empty-line" d="M22 22h11M22 27h8"></path>
        </svg>
      </div>
    `;
  }

  function setNodeHeading(node, status, hasManifest) {
    const title = node?.querySelector('[data-output-title]');
    if (!title) return;
    title.textContent = hasManifest
      ? '文件结果已就绪'
      : DesktopState.isFailure(status)
        ? '文件任务失败'
        : status === 'canceled'
          ? '文件任务已取消'
          : DesktopState.isInFlight(status)
            ? '正在生成文件'
            : '等待 PPT / PSD';
  }

  function emptyStateHtml(output, task, kind) {
    const status = String(task?.status || output?.status || 'idle');
    const isBusy = DesktopState.isInFlight(status);
    const isFailure = DesktopState.isFailure(status);
    const isCanceled = status === 'canceled';
    const title = isBusy
      ? '正在接收模型节点的文件任务'
      : isFailure
        ? '文件任务失败'
        : isCanceled
          ? '文件任务已取消'
          : '文件会出现在这里';
    const message = isBusy
      ? (output?.progressText || task?.progress_text || '模型正在整理文件结构与预览。')
      : isFailure
        ? (output?.displayError || output?.error || task?.display_error || task?.error || '文件没有生成完成，请回到模型节点重试。')
        : isCanceled
          ? (output?.progressText || '任务已取消，可从模型节点重新生成。')
          : '从模型节点生成 PPT/PSD，结果会自动汇入这里。';
    const stateClass = isBusy ? ' is-busy' : (isFailure ? ' is-error' : (isCanceled ? ' is-canceled' : ''));
    return `
      <div class="desk-file-result-empty${stateClass}">
        ${fileIconHtml()}
        <span class="desk-file-result-empty__kicker">文件收件箱</span>
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(message)}</span>
        <div class="desk-file-result-empty__types" aria-label="支持 PPT 和 PSD">
          <span${kind === 'PPT' ? ' class="is-active"' : ''}>PPT</span>
          <i></i>
          <span${kind === 'PSD' ? ' class="is-active"' : ''}>PSD</span>
        </div>
      </div>
    `;
  }

  function previewHtml(manifest, kind) {
    const preview = manifest?.preview || {};
    const firstPage = Array.isArray(preview.pages) ? preview.pages[0] : null;
    const imageUrl = preview.image_url || firstPage?.url || '';
    if (imageUrl) {
      return `
        <div class="desk-file-preview">
          <img src="${escapeHtml(imageUrl)}" alt="文件预览">
          <span class="desk-file-preview__badge">${escapeHtml(kind)} 预览</span>
        </div>
      `;
    }
    if (preview.pdf_url) {
      return `
        <div class="desk-file-preview">
          <iframe src="${escapeHtml(preview.pdf_url)}" title="PDF 预览"></iframe>
          <span class="desk-file-preview__badge">${escapeHtml(kind)} 预览</span>
        </div>
      `;
    }
    const message = preview.message || (preview.status === 'missing_dependency' ? '未检测到预览依赖，文件已保存。' : '暂无预览，文件已保存。');
    return `<div class="desk-file-preview"><div class="desk-file-preview__fallback">${escapeHtml(message)}</div></div>`;
  }

  function previewListHtml(manifest) {
    const layers = manifest?.preview?.layers || [];
    const pages = manifest?.preview?.pages || [];
    const isLayerList = Array.isArray(layers) && layers.length;
    const items = isLayerList
      ? layers.map((item, index) => ({
        ...item,
        name: item.name || `图层 ${index + 1}`,
        itemType: 'PNG 图层'
      })).filter(item => item.url)
      : (Array.isArray(pages) && pages.length > 1
        ? pages.map((item, index) => ({
          ...item,
          name: item.name || `第 ${index + 1} 页`,
          itemType: '页面预览'
        })).filter(item => item.url)
        : []);
    if (!items.length) return '';
    const label = isLayerList ? '图层预览' : '页面预览';
    return `
      <div class="desk-file-preview-list">
        <div class="desk-file-preview-list__head">
          <span class="desk-file-preview-list__label">${label}</span>
          <em>${items.length} 项</em>
        </div>
        <div class="desk-file-layer-list" role="list">
          ${items.slice(0, 12).map((item, index) => `
          <a class="desk-file-layer" href="${escapeHtml(item.url)}" target="_blank" rel="noopener" role="listitem" title="${escapeHtml(item.name)}">
            <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.name)}">
            <span class="desk-file-layer__copy">
              <strong>${escapeHtml(item.name)}</strong>
              <em>${escapeHtml(item.itemType)}</em>
            </span>
            <i>${String(index + 1).padStart(2, '0')}</i>
          </a>
          `).join('')}
        </div>
      </div>
    `;
  }

  function render(resultNodeId, output, task) {
    const node = document.querySelector(`.desk-node[data-node-id="${CSS.escape(resultNodeId)}"]`);
    const grid = node?.querySelector('[data-result-grid]');
    if (!grid) return;
    const manifest = getManifest(output, task);
    const status = String(task?.status || output?.status || 'idle');
    const kind = artifactKind(manifest, output, task);
    setNodeHeading(node, status, Boolean(manifest));
    grid.classList.toggle('is-busy', DesktopState.isInFlight(status));
    grid.classList.toggle('is-error', DesktopState.isFailure(status));
    grid.classList.toggle('has-result', Boolean(manifest));
    if (!manifest) {
      grid.innerHTML = emptyStateHtml(output, task, kind);
      return;
    }
    const primary = manifest.primary || {};
    const zip = manifest.zip || null;
    const pages = Number(manifest.preview?.page_count || 0);
    const layers = Number(manifest.preview?.layer_count || 0);
    const meta = [
      pages ? `${pages} 页` : '',
      layers ? `${layers} 图层` : '',
      formatSize(primary.size),
      manifest.archived === false ? '本地临时' : '已归档'
    ].filter(Boolean).join(' · ');
    grid.innerHTML = `
      <article class="desk-file-card">
        ${previewHtml(manifest, kind)}
        ${previewListHtml(manifest)}
        <footer class="desk-file-card__footer">
          <div class="desk-file-card__main">
            <span class="desk-file-card__kind">${escapeHtml(kind)}</span>
            <div class="desk-file-card__title">
              <strong title="${escapeHtml(primary.name || `${kind} 文件`)}">${escapeHtml(primary.name || `${kind} 文件`)}</strong>
              <span>${escapeHtml(meta)}</span>
            </div>
          </div>
          <div class="desk-file-card__actions">
            ${primary.url ? `<a href="${escapeHtml(primary.url)}" target="_blank" rel="noopener">打开主文件</a>` : ''}
            ${zip?.url ? `<a href="${escapeHtml(zip.url)}" target="_blank" rel="noopener">下载 ZIP</a>` : ''}
            ${manifest.manifest_url ? `<a href="${escapeHtml(manifest.manifest_url)}" target="_blank" rel="noopener">Manifest</a>` : ''}
          </div>
        </footer>
      </article>
    `;
  }

  function renderPills(task, resultNodeId, output, wrap) {
    if (!wrap) return;
    const manifest = getManifest(output, task);
    const status = String(task?.status || output?.status || 'idle');
    const kind = artifactKind(manifest, output, task);
    const previewStatus = manifest?.preview?.status || output?.params?.editable_preview_status || '';
    const archived = manifest?.archived !== false;
    const previewLabels = {
      ready: '预览已就绪',
      pending: '预览处理中',
      missing_dependency: '预览依赖缺失',
      failed: '预览失败'
    };
    const mainPill = DesktopState.isInFlight(status)
      ? { text: '文件生成中', tone: 'busy' }
      : DesktopState.isFailure(status)
        ? { text: '文件任务失败', tone: 'warning' }
        : status === 'canceled'
          ? { text: '文件任务已取消', tone: 'warning' }
          : manifest
            ? { text: '文件结果已就绪', tone: 'success' }
            : { text: '等待文件' };
    const archivePill = manifest
      ? {
        text: manifest?.zip
          ? (archived ? 'ZIP · 已归档' : 'ZIP · 未归档')
          : (archived ? '已归档' : '未归档'),
        tone: archived ? 'success' : 'warning'
      }
      : null;
    const pills = [
      mainPill,
      kind !== 'PPT / PSD' ? { text: kind } : null,
      previewStatus && previewStatus !== 'ready'
        ? { text: previewLabels[previewStatus] || `预览 ${previewStatus}`, tone: 'warning' }
        : null,
      archivePill
    ];
    wrap.innerHTML = pills.filter(Boolean).map(pill => {
      const tone = pill.tone ? ` class="is-${escapeHtml(pill.tone)}"` : '';
      return `<span${tone}>${escapeHtml(pill.text)}</span>`;
    }).join('');
  }

  window.DesktopFileResults = {
    isFileResultNode,
    render,
    renderPills
  };
})();
