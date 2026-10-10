// Compact-node presentation for local video enhancement. The full editor lives
// in desktop-topaz-video-workbench.js; this module never owns jobs or media.
(function () {
  const icons = {
    idle: '<path d="M13 2 4 14h7l-1 8 10-13h-7z"/>',
    busy: '<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>',
    succeeded: '<path fill="none" stroke="currentColor" stroke-width="2.5" d="m4 12 5 5L20 6"/>',
    failed: '<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M18 6 6 18"/>',
  };
  function create({model, escapeHtml: e, stateIcon, progressView}) {
    const esc = value => e(String(value ?? ''));
    function options(items, current, value = item => item.id, label = item => item.label) {
      return items.map(item => `<option value="${esc(value(item))}"${String(value(item)) === String(current) ? ' selected' : ''}>${esc(label(item))}</option>`).join('');
    }
    function fields(node, catalog) {
      const models = catalog?.length ? catalog : model.MODELS.map(([id, label]) => ({id, label}));
      const meta = catalog?.find(item => item.id === node.model);
      const scales = meta?.scales || [];
      const modelOptions = options(models, node.model, item => item.id,
        item => item.label + (item.available === false ? ' · 不可用' : item.available === true && !item.verified ? ' · 待验证' : ''));
      return `<div class="desk-topaz-video__grid">
        <label class="desk-topaz-video__model"><span>模型</span><select data-topaz-video-model aria-label="视频增强模型">${modelOptions}</select></label>
        <label><span>预设</span><select data-topaz-video-preset aria-label="视频增强预设">${options(model.PRESETS, node.presetId)}</select></label>
        <label><span>放大倍数</span><select data-topaz-video-scale aria-label="放大倍数"${scales.length ? '' : ' disabled'}>${scales.length ? options(scales, node.scale, v => v, v => v + '×') : '<option>—</option>'}</select></label>
        <label><span>处理范围</span><select data-topaz-video-scope aria-label="处理范围"><option value="full"${node.maxSeconds === 0 ? ' selected' : ''}>全片</option><option value="clip"${node.maxSeconds > 0 ? ' selected' : ''}>前 N 秒</option></select></label>
        <label><span>短测秒数</span><input data-topaz-video-seconds aria-label="短测秒数" type="number" min="1" max="600" step="1" value="${esc(node.maxSeconds || 15)}"${node.maxSeconds === 0 ? ' disabled' : ''}></label>
      </div>`;
    }
    function html(node) {
      return `<section class="desk-node desk-node--topaz-video" data-node-id="${esc(node.id)}" aria-label="Topaz 视频增强节点">
        <header class="desk-topaz-video__header" data-node-drag-handle><span class="desk-topaz-video__icon">${model.ICON}</span><div><strong>Topaz 视频增强</strong><small>VIDEO ENHANCEMENT · LOCAL</small></div><span class="desk-status-pill" data-topaz-video-status>检测中</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除视频增强节点">删</button></header>
        <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接视频输入"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接增强视频"></button>
        <div class="desk-topaz-video__body" data-node-drag-ignore>
          <div class="desk-topaz-video__fields">${fields(node, null)}</div>
          <div class="desk-topaz-video__source-row"><div class="desk-topaz-video__source-copy"><span data-topaz-video-source>连接视频节点，或导入本地视频</span><small data-topaz-video-availability>正在检查本机模型资源…</small></div><button type="button" class="desk-key" data-topaz-video-import>导入视频</button><input type="file" data-topaz-video-file accept="video/mp4,video/quicktime,video/webm,.mkv" hidden></div>
          <footer class="desk-topaz-video__footer"><button type="button" class="desk-key desk-topaz-video__workbench" data-topaz-video-workbench><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z"/></svg><span>展开工作台</span></button><span class="desk-topaz-video__local-note">本地处理 · 保留原音频</span><button type="button" class="desk-generation-action desk-topaz-video__generate" data-topaz-video-run disabled aria-label="开始增强">${stateIcon.html(icons)}<span class="desk-generation-action__label">开始增强</span></button></footer>
        </div>
        <div class="desk-progress-float desk-topaz-video__progress" data-topaz-video-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar data-topaz-video-bar></span><strong class="desk-progress-float__percent" data-topaz-video-percent>等待任务</strong></div><span class="desk-progress-float__stage" data-topaz-video-stage>等待任务</span></div></div>
      </section>`;
    }
    function renderFields(el, node, catalog) {
      const container = el.querySelector('.desk-topaz-video__fields');
      if (container) container.innerHTML = fields(node, catalog);
    }
    function paint(el, node, job, pending, catalog, catalogError = '', display = {}) {
      const meta = catalog?.find(item => item.id === node.model);
      const ready = node.enhancementEnabled === false ? display.processingReady === true : meta?.available === true && meta.scales.includes(node.scale);
      const busy = Boolean(pending) || model.active(display.status || node.status);
      const state = pending ? 'submitting' : display.status || node.status;
      const badge = el.querySelector('[data-topaz-video-status]');
      badge.textContent = busy && display.kind === 'preview' ? '预览中' : busy || state !== 'idle' ? model.labels[state] || '就绪'
        : !catalog ? '检测中' : ready ? '就绪' : '不可用';
      badge.classList.toggle('is-success', !busy && (state === 'succeeded' || state === 'idle' && ready));
      const hint = el.querySelector('[data-topaz-video-availability]');
      hint.textContent = catalogError || (node.enhancementEnabled === false && ready ? '增强已关闭 · 仅执行所选滤镜与编码' : !catalog ? '正在检查本机模型资源…'
        : !meta ? '所选模型不在本机目录中'
          : !meta.available ? meta.reason || '模型资源或运行路径尚不可用'
            : meta.verified ? '本机短片导出已验证' : '模型资源已就绪，尚待本机视频导出验证');
      hint.classList.toggle('is-unavailable', !ready);
      const button = el.querySelector('[data-topaz-video-run]');
      button.disabled = busy || !ready;
      button.dataset.topazVideoState = state;
      button.setAttribute('aria-busy', String(busy));
      const icon = busy ? 'busy' : state === 'succeeded' ? 'succeeded' : state === 'failed' || state === 'interrupted' ? 'failed' : 'idle';
      if (button.dataset.topazVideoIcon !== icon) {
        stateIcon.paint(button.querySelector('svg'), icon);
        button.dataset.topazVideoIcon = icon;
      }
      const label = busy ? display.kind === 'preview' ? '生成预览' : model.labels[state] || '处理中'
        : state === 'succeeded' ? '已完成' : state === 'failed' || state === 'interrupted' ? '重试增强' : '开始增强';
      button.querySelector('span').textContent = label;
      button.setAttribute('aria-label', label);
      const localNote = el.querySelector('.desk-topaz-video__local-note');
      if (localNote) localNote.textContent = node.encodingOptions?.audio === 'mute' ? '本地处理 · 无音轨输出' : '本地处理 · 保留原音频';
      const progress = el.querySelector('[data-topaz-video-progress]');
      progress.hidden = !busy;
      progress.classList.toggle('is-visible', busy);
      const amount = Number(job?.progress_percent);
      const known = job?.progress_percent != null && Number.isFinite(amount);
      progress.classList.toggle('is-indeterminate', !known);
      progress.style.setProperty('--progress-percent', known ? Math.max(0, Math.min(100, amount)) + '%' : '35%');
      el.querySelector('[data-topaz-video-bar]').style.width = known ? Math.max(0, Math.min(100, amount)) + '%' : '30%';
      el.querySelector('[data-topaz-video-percent]').textContent = known ? Math.round(amount) + '%' : '处理中';
      el.querySelector('[data-topaz-video-stage]').textContent = pending ? '提交素材…' : String(job?.progress_message || job?.stage || model.labels[state] || '');
      progressView?.update(progress, { visible: busy, running: busy, taskId: pending ? '' : job?.id,
        percent: pending ? null : (known ? amount : null),
        title: pending ? '提交素材…' : String(job?.progress_message || job?.stage || model.labels[state] || '处理中'),
        detail: display.kind === 'preview' ? 'Topaz · 生成预览' : 'Topaz · 视频增强',
        startedAt: pending ? 0 : job?.started_at || job?.created_at, finishedAt: job?.finished_at }, el);
      el.querySelectorAll('.desk-topaz-video__fields :is(input,select),[data-topaz-video-import],[data-topaz-video-workbench]').forEach(input => {
        input.disabled = busy || (input.hasAttribute('data-topaz-video-scale') && !meta?.scales?.length)
          || (input.hasAttribute('data-topaz-video-seconds') && node.maxSeconds === 0);
      });
    }
    return Object.freeze({html, renderFields, paint});
  }
  window.DesktopTopazVideoView = Object.freeze({create});
})();
