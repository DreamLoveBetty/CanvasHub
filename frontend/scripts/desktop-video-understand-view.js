// Presentation only for the WeMM-Video understanding node; shared visual tokens and 72px key shell.
(function () {
  const icons = {
    idle: '<path d="M13 2 4 14h7l-1 8 10-13h-7z"/>',
    busy: '<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>',
    succeeded: '<path fill="none" stroke="currentColor" stroke-width="2.5" d="m4 12 5 5L20 6"/>',
    failed: '<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M18 6 6 18"/>',
  };

  function create({ model, escapeHtml: e, stateIcon, progressView }) {
    const modeOptions = selected => Object.entries(model.MODES)
      .map(([key, cfg]) => `<option value="${e(key)}" ${key === selected ? 'selected' : ''}>${e(cfg.label)}</option>`)
      .join('');

    const pixelOptions = selected => model.PIXEL_CHOICES
      .map(([val, label]) => `<option value="${val}" ${Number(val) === Number(selected) ? 'selected' : ''}>${e(label)}</option>`)
      .join('');

    function html(node) {
      const modeCfg = model.MODES[node.mode] || model.MODES.storyboard;
      return `<section class="desk-node desk-node--video-understand" data-node-id="${e(node.id)}" data-node-drag-handle aria-label="WeMM 视频理解">
      <header class="desk-video-understand__header">
        <span class="desk-video-understand__icon">${model.ICON}</span>
        <div><strong>WeMM 视频理解</strong><small>6-bit · 画面 + 音轨</small></div>
        <span class="desk-status-pill" data-understand-status>就绪</span>
        <button type="button" class="desk-node-delete" data-node-delete aria-label="删除视频理解节点" title="删除视频理解节点"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button>
      </header>
      <div class="desk-video-understand__body" data-node-drag-ignore>
        <div class="desk-video-understand__banner" data-understand-env-banner hidden>
          <span data-understand-env-text>视频理解环境尚未就绪，请先下载 6-bit 模型</span>
          <button type="button" class="desk-key" data-understand-open-settings>前往准备</button>
        </div>
        <div class="desk-video-understand__controls">
          <label class="desk-video-understand__mode">分析模式<select data-understand-field="mode">${modeOptions(node.mode)}</select></label>
          <div class="desk-video-understand__toggles">
            <label><input type="checkbox" data-understand-field="useAudio" ${node.useAudio ? 'checked' : ''}>含音轨</label>
            <label><input type="checkbox" data-understand-field="thinking" ${node.thinking ? 'checked' : ''}>Thinking</label>
            <label><input type="checkbox" data-understand-field="shotAnchors" ${node.shotAnchors ? 'checked' : ''}>切镜锚点</label>
          </div>
          <button type="button" class="desk-key desk-video-understand__adv-toggle" data-understand-advanced-toggle aria-expanded="${node.advancedOpen ? 'true' : 'false'}">高级参数</button>
        </div>
        <div class="desk-video-understand__advanced" data-understand-advanced ${node.advancedOpen ? '' : 'hidden'}>
          <label>抽帧 FPS<input type="number" step="0.25" min="0.25" max="4" data-understand-field="fps" value="${e(node.fps)}"></label>
          <label>最大帧数<input type="number" step="4" min="4" max="128" data-understand-field="maxFrames" value="${e(node.maxFrames)}"></label>
          <label>像素预算<select data-understand-field="totalPixels">${pixelOptions(node.totalPixels)}</select></label>
          <label>最大输出 Token<input type="number" step="256" min="128" max="8192" data-understand-field="maxTokens" value="${e(node.maxTokens)}"></label>
        </div>
        <div class="desk-video-understand__prompt-wrap">
          <div class="desk-video-understand__prompt-chip" data-understand-prompt-chip hidden></div>
          <textarea class="desk-video-understand__prompt" rows="2" data-understand-field="prompt" placeholder="${e(modeCfg.promptPlaceholder)}">${e(node.prompt)}</textarea>
        </div>
        <div class="desk-video-understand__input">
          <span data-understand-source>连接视频节点，或导入本地视频</span>
          <button type="button" class="desk-key" data-understand-import>导入视频</button>
          <input type="file" data-understand-file accept="video/mp4,video/quicktime,video/webm,.mov,.mp4,.webm" hidden>
        </div>
        <div class="desk-video-understand__footer">
          <small data-understand-footer-hint>本地推理 · 输出到文本节点</small>
          <button type="button" class="desk-video-understand__generate desk-generation-action" data-understand-run aria-label="开始分析">${stateIcon.html(icons)}<span class="desk-generation-action__label">开始分析</span></button>
        </div>
      </div>
      <button class="desk-port desk-port--in" type="button" data-port="in" data-node-id="${e(node.id)}" aria-label="视频或指令输入"></button>
      <button class="desk-port desk-port--out" type="button" data-port="out" data-node-id="${e(node.id)}" aria-label="文本结果输出"></button>
      <div class="desk-video-understand__progress" hidden data-understand-progress role="status"><span data-understand-stage></span><div><i></i></div></div>
      </section>`;
    }

    function paint(el, node, job, { pending = false, envStatus = null, promptSourceText = null } = {}) {
      const busy = pending || model.active(node.status);
      const state = pending ? 'submitting' : node.status;
      const pill = el.querySelector('[data-understand-status]');
      if (pill) {
        pill.textContent = model.labels[state] || '就绪';
        pill.classList.toggle('is-success', ['succeeded', 'idle'].includes(state));
      }

      const banner = el.querySelector('[data-understand-env-banner]');
      if (banner) {
        const showBanner = Boolean(envStatus && !envStatus.ready);
        banner.hidden = !showBanner;
        if (showBanner) {
          const reason = envStatus.preparation?.status === 'running'
            ? (envStatus.preparation.message || '正在准备视频理解环境…')
            : (envStatus.reasons?.[0] || '视频理解环境尚未准备');
          const txt = banner.querySelector('[data-understand-env-text]');
          if (txt) txt.textContent = reason;
        }
      }

      const adv = el.querySelector('[data-understand-advanced]');
      const advBtn = el.querySelector('[data-understand-advanced-toggle]');
      if (adv) adv.hidden = !node.advancedOpen;
      if (advBtn) advBtn.setAttribute('aria-expanded', String(Boolean(node.advancedOpen)));

      const modeCfg = model.MODES[node.mode] || model.MODES.storyboard;
      const chip = el.querySelector('[data-understand-prompt-chip]');
      const textarea = el.querySelector('[data-understand-field="prompt"]');
      const hasUpstreamPrompt = promptSourceText !== null;
      if (chip) {
        chip.hidden = !hasUpstreamPrompt;
        if (hasUpstreamPrompt) {
          const preview = String(promptSourceText || '').trim();
          chip.textContent = preview
            ? `已接入上游文本节点：${preview.slice(0, 48)}${preview.length > 48 ? '…' : ''}`
            : '已接入上游文本节点（当前为空）';
        }
      }
      if (textarea) {
        textarea.placeholder = modeCfg.promptPlaceholder;
        textarea.disabled = busy || hasUpstreamPrompt;
      }

      el.querySelectorAll('[data-understand-field]:not([data-understand-field="prompt"]), [data-understand-import]')
        .forEach(item => { item.disabled = busy; });

      const button = el.querySelector('[data-understand-run]');
      if (button) {
        button.disabled = busy;
        button.setAttribute('aria-busy', String(busy));
        button.dataset.understandState = state;
        const icon = busy ? 'busy' : state === 'succeeded' ? 'succeeded' : ['failed', 'interrupted'].includes(state) ? 'failed' : 'idle';
        if (button.dataset.understandIcon !== icon) {
          stateIcon.paint(button.querySelector('svg'), icon);
          button.dataset.understandIcon = icon;
        }
        const label = busy
          ? model.labels[state]
          : (state === 'failed' || state === 'interrupted') ? '重试分析'
          : state === 'succeeded' ? '已完成'
          : '开始分析';
        const span = button.querySelector('span');
        if (span) span.textContent = label;
        button.setAttribute('aria-label', label);
        button.title = state === 'succeeded' ? '分析完成，点击重新分析' : label;
      }

      const bar = el.querySelector('[data-understand-progress]');
      if (bar) {
        bar.hidden = !busy;
        const stageText = pending
          ? '提交分析任务…'
          : (job?.progress_message || model.stageLabel(job?.stage) || model.labels[state]);
        const stageEl = el.querySelector('[data-understand-stage]');
        if (stageEl) stageEl.textContent = stageText;
        progressView?.update(bar, {
          visible: busy,
          running: busy,
          taskId: pending ? '' : job?.id,
          percent: pending ? null : job?.progress_percent,
          title: pending ? '提交分析任务…' : model.stageLabel(job?.stage) || model.labels[state],
          detail: 'WeMM · 视频理解',
          startedAt: pending ? 0 : job?.started_at || job?.created_at,
          finishedAt: job?.finished_at,
        }, el);
      }
    }

    return { html, paint };
  }

  window.DesktopVideoUnderstandView = Object.freeze({ create });
})();
