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

  function previewHtml(manifest) {
    const preview = manifest?.preview || {};
    const firstPage = Array.isArray(preview.pages) ? preview.pages[0] : null;
    const imageUrl = preview.image_url || firstPage?.url || '';
    if (imageUrl) {
      return `<div class="desk-file-preview"><img src="${escapeHtml(imageUrl)}" alt="文件预览"></div>`;
    }
    if (preview.pdf_url) {
      return `<div class="desk-file-preview"><iframe src="${escapeHtml(preview.pdf_url)}" title="PDF 预览"></iframe></div>`;
    }
    const message = preview.message || (preview.status === 'missing_dependency' ? '未检测到预览依赖，文件已保存。' : '暂无预览，文件已保存。');
    return `<div class="desk-file-preview"><div class="desk-file-preview__fallback">${escapeHtml(message)}</div></div>`;
  }

  function layerListHtml(manifest) {
    const layers = manifest?.preview?.layers || [];
    if (!Array.isArray(layers) || !layers.length) return '';
    return `
      <div class="desk-file-layer-list">
        ${layers.slice(0, 12).map(layer => `
          <a class="desk-file-layer" href="${escapeHtml(layer.url)}" target="_blank" rel="noopener">
            <img src="${escapeHtml(layer.url)}" alt="${escapeHtml(layer.name)}">
            <span>${escapeHtml(layer.name)}</span>
          </a>
        `).join('')}
      </div>
    `;
  }

  function render(resultNodeId, output, task) {
    const node = document.querySelector(`.desk-node[data-node-id="${CSS.escape(resultNodeId)}"]`);
    const grid = node?.querySelector('[data-result-grid]');
    if (!grid) return;
    const manifest = output?.fileManifest || task?.file_manifest || output?.params?.file_manifest || null;
    if (!manifest) {
      grid.innerHTML = `
        <div class="desk-file-result-empty">
          <strong>文件会出现在这里</strong>
          <span>${escapeHtml(output?.progressText || '连接 PPT/PSD 模型任务后点击生成。')}</span>
        </div>
      `;
      return;
    }
    const primary = manifest.primary || {};
    const zip = manifest.zip || null;
    const kind = String(manifest.artifact_type || 'file').toUpperCase();
    const pages = Number(manifest.preview?.page_count || 0);
    const layers = Number(manifest.preview?.layer_count || 0);
    const meta = [
      kind,
      pages ? `${pages} 页` : '',
      layers ? `${layers} 图层` : '',
      formatSize(primary.size)
    ].filter(Boolean).join(' · ');
    const archivedLabel = manifest.archived === false ? '本地临时保存' : `${kind} 已归档`;
    grid.innerHTML = `
      <article class="desk-file-card">
        ${previewHtml(manifest)}
        <div class="desk-file-card__main">
          <div class="desk-file-card__title">
            <strong title="${escapeHtml(primary.name || `${kind} 文件`)}">${escapeHtml(primary.name || `${kind} 文件`)}</strong>
            <span>${escapeHtml(meta)}</span>
          </div>
          <div class="desk-file-card__actions">
            ${primary.url ? `<a href="${escapeHtml(primary.url)}" target="_blank" rel="noopener">打开主文件</a>` : ''}
            ${zip?.url ? `<a href="${escapeHtml(zip.url)}" target="_blank" rel="noopener">下载 ZIP</a>` : ''}
            ${manifest.manifest_url ? `<a href="${escapeHtml(manifest.manifest_url)}" target="_blank" rel="noopener">Manifest</a>` : ''}
          </div>
          <div class="desk-file-card__note">${escapeHtml([archivedLabel, manifest.directory_relative || ''].filter(Boolean).join(' / '))}</div>
        </div>
        ${layerListHtml(manifest)}
      </article>
    `;
  }

  function renderActions(resultNodeId, output, resultEls) {
    const manifest = output?.fileManifest || output?.params?.file_manifest || null;
    const primary = manifest?.primary || {};
    if (resultEls?.sendOriginal) {
      resultEls.sendOriginal.disabled = !primary.relative_path;
      if (!resultEls.sendOriginal.dataset.busy) resultEls.sendOriginal.textContent = '发送文件';
    }
    if (resultEls?.copyPrompt) resultEls.copyPrompt.disabled = !output?.prompt && !DesktopState.state.prompt;
  }

  function renderPills(task, resultNodeId, output, wrap) {
    if (!wrap) return;
    const manifest = output?.fileManifest || task?.file_manifest || output?.params?.file_manifest || null;
    const kind = String(manifest?.artifact_type || output?.params?.task_type || '文件').toUpperCase();
    const previewStatus = manifest?.preview?.status || output?.params?.editable_preview_status || '';
    const archived = manifest?.archived !== false;
    const pills = [
      { text: manifest ? `${kind} 已保存` : '等待文件', tone: manifest ? 'success' : '' },
      previewStatus ? { text: `预览 ${previewStatus}`, tone: previewStatus === 'ready' ? 'success' : 'warning' } : null,
      manifest?.zip ? { text: '含 ZIP 附件' } : null,
      manifest ? { text: archived ? '已归档' : '未归档', tone: archived ? 'success' : 'warning' } : null
    ];
    if (DesktopState.isInFlight(task?.status || output?.status)) pills.unshift({ text: '文件生成中', tone: 'busy' });
    wrap.innerHTML = pills.filter(Boolean).map(pill => {
      const tone = pill.tone ? ` class="is-${escapeHtml(pill.tone)}"` : '';
      return `<span${tone}>${escapeHtml(pill.text)}</span>`;
    }).join('');
  }

  window.DesktopFileResults = {
    isFileResultNode,
    render,
    renderActions,
    renderPills
  };
})();
