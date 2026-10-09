// Expanded Topaz Video editor. It owns transient playback/editor state only;
// the canvas controller remains the owner of node state, uploads and jobs.
(function () {
  function create({model, api, escapeHtml, stateIcon, inspector}) {
    const esc = value => escapeHtml(String(value ?? ''));
    const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    let root = null;
    let current = null;
    let drag = null;
    const state = {
      duration: 0, fps: 30, start: 0, end: 5, position: 0, resultStart: 0, resultTimeScale: 1, exportSelection: false,
      compare: 50, mode: 'compare', tab: 'adjustments', zoom: 1, panX: 0, panY: 0,
      muted: true, timelineZoom: 1, sidebarCollapsed: false, activeWorkflowPreset: '',
      filmstripUrl: '', filmstripToken: 0,
    };
    const WORKFLOW_PRESETS = Object.freeze([
      {id: 'enhance-2x', label: '高清 2×', detail: '通用放大', choices: [['artemis', 2], ['rhea', 2], ['theia-v4', 2], ['gaia', 2]]},
      {id: 'enhance-4x', label: '高清 4×', detail: '大幅放大', choices: [['rhea', 4], ['proteus-v4', 4]]},
      {id: 'portrait', label: '人像修复', detail: '脸部与低质素材', choices: [['iris', 1]]},
      {id: 'denoise', label: '强力降噪', detail: '保留纹理', choices: [['nyx-v3', 1], ['nyx-v3', 2]]},
      {id: 'animation', label: '动画高清', detail: '动画与 CG', choices: [['gaia-animation', 2], ['gaia', 2]]},
      {id: 'fidelity', label: '高保真', detail: '轻修复、保真', choices: [['theia-v4', 2], ['theia-v4', 1]]},
      {id: 'starlight', label: '星光修复', detail: '扩散式细节重建', choices: [['precise-26', 2]]},
      {id: 'general', label: '通用增强', detail: '不改变尺寸', choices: [['proteus-v4', 1], ['rhea', 1]]},
    ]);
    const q = selector => root?.querySelector(selector);
    const PLAY_ICONS = Object.freeze({play: '<path d="m9 5 11 7-11 7z"/>', pause: '<path d="M7 5h3v14H7zM14 5h3v14h-3z"/>'});
    const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
    const frameDuration = () => 1 / Math.max(1, finite(state.fps, 30));
    const selectionFloor = duration => Math.min(duration, Math.max(.04, frameDuration()));

    function clock(seconds, frames = false) {
      const value = Math.max(0, finite(seconds));
      const hours = Math.floor(value / 3600);
      const minutes = Math.floor(value / 60) % 60;
      const secs = Math.floor(value) % 60;
      const base = [hours, minutes, secs].map(number => String(number).padStart(2, '0')).join(':');
      const fps = Math.max(1, Math.round(finite(state.fps, 30)));
      return frames ? base + ':' + String(Math.min(fps - 1, Math.floor((value % 1) * fps))).padStart(2, '0') : base;
    }

    function artifact(job) {
      const item = job?.artifacts?.find(entry => entry.name === 'result/enhanced.mp4')
        || job?.artifacts?.find(entry => /\.mp4$/i.test(entry.name || ''));
      return item?.url ? {url: api.sourceUrl(item.url), name: item.name.split('/').pop()} : null;
    }

    function ensureRoot() {
      if (root) return;
      root = document.createElement('div');
      root.className = 'desk-topaz-video-workbench';
      root.hidden = true;
      root.innerHTML = `<div class="desk-topaz-video-workbench__scrim" data-tvwb-close></div>
        <section class="desk-topaz-video-workbench__dialog" role="dialog" aria-modal="true" aria-label="Topaz 视频增强工作台">
          <header class="desk-topaz-video-workbench__header">
            <span class="desk-topaz-video-workbench__brand">${model.ICON}</span>
            <div class="desk-topaz-video-workbench__heading"><strong>Topaz 视频增强工作台</strong><small data-tvwb-source-name>未连接视频</small></div>
            <div class="desk-topaz-video-workbench__preview-configs" aria-label="预览配置">
              <button type="button" data-tvwb-preview-config="source">原片</button>
              <button type="button" class="is-active" data-tvwb-preview-config="current"><span>配置 1</span><small data-tvwb-config-model>当前模型</small></button>
            </div>
            <span class="desk-topaz-video-workbench__status" data-tvwb-status>就绪</span>
            <button type="button" data-tvwb-refresh title="重新检测本机模型与滤镜">刷新运行时</button>
            <button type="button" data-tvwb-import>更换视频</button>
            <button type="button" class="desk-topaz-video-workbench__sidebar-toggle" data-tvwb-sidebar-toggle aria-pressed="false" title="收起参数面板">›</button>
            <button type="button" class="desk-topaz-video-workbench__close" data-tvwb-close aria-label="关闭工作台">×</button>
          </header>
          <div class="desk-topaz-video-workbench__layout">
            <main class="desk-topaz-video-workbench__stage">
              <div class="desk-topaz-video-workbench__viewer-toolbar">
                <div class="desk-topaz-video-workbench__modes" role="group" aria-label="预览模式">
                  <button type="button" data-tvwb-mode="original" title="仅显示原片">原片</button>
                  <button type="button" class="is-active" data-tvwb-mode="compare" title="拖动分割线对比">分割</button>
                  <button type="button" data-tvwb-mode="side" title="并排同步对比">并排</button>
                  <button type="button" data-tvwb-mode="result" title="仅显示处理后">处理后</button>
                </div>
                <div class="desk-topaz-video-workbench__viewer-tools">
                  <button type="button" data-tvwb-mute aria-pressed="true" title="打开原片声音">静音</button>
                  <button type="button" data-tvwb-zoom-level="1" class="is-active">适应</button>
                  <button type="button" data-tvwb-zoom-level="2">200%</button>
                  <button type="button" class="desk-topaz-video-workbench__zoom" data-tvwb-zoom aria-pressed="false" title="放大对比视频"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5M10.5 7.5v6M7.5 10.5h6"/></svg><span>放大</span></button>
                </div>
                <span data-tvwb-view-meta>等待视频</span>
              </div>
              <div class="desk-topaz-video-workbench__viewer" data-tvwb-viewer>
                <video playsinline preload="metadata" data-tvwb-source-video></video>
                <div class="desk-topaz-video-workbench__result-layer" data-tvwb-result-layer><video muted playsinline preload="metadata" data-tvwb-result-video></video></div>
                <div class="desk-topaz-video-workbench__divider" data-tvwb-divider role="separator" aria-label="拖动对比分割线" aria-orientation="vertical" aria-valuemin="0" aria-valuemax="100" tabindex="0"><span aria-hidden="true">↔</span></div>
                <span class="desk-topaz-video-workbench__media-label is-original">原片</span><span class="desk-topaz-video-workbench__media-label is-result">处理后</span>
                <div class="desk-topaz-video-workbench__empty" data-tvwb-empty><strong>尚未生成预览</strong><span>先在时间轴选择区间，再生成一段预览进行同步对比</span></div>
              </div>
              <div class="desk-topaz-video-workbench__transport">
                <span data-tvwb-current>00:00:00:00</span>
                <div><button type="button" data-tvwb-jump="start" aria-label="跳至入点">|‹</button><button type="button" data-tvwb-step="-1" aria-label="上一帧">‹</button><button type="button" class="desk-topaz-video-workbench__play" data-tvwb-play aria-label="播放">${stateIcon.html(PLAY_ICONS, 'play')}</button><button type="button" data-tvwb-step="1" aria-label="下一帧">›</button><button type="button" data-tvwb-jump="end" aria-label="跳至出点">›|</button></div>
                <span data-tvwb-duration>00:00:00:00</span>
              </div>
              <div class="desk-topaz-video-workbench__timeline">
                <div class="desk-topaz-video-workbench__timeline-head">
                  <div class="desk-topaz-video-workbench__trim-tools" role="group" aria-label="选区工具">
                    <button type="button" data-tvwb-mark="start" title="在播放头设置入点（I）">[</button>
                    <button type="button" data-tvwb-mark="end" title="在播放头设置出点（O）">]</button>
                    <button type="button" data-tvwb-mark="clear" title="清除选区">×</button>
                  </div>
                  <strong>预览选区</strong><span>入点 <input type="number" min="0" step="0.01" data-tvwb-start-number> 秒</span><span>出点 <input type="number" min="0" step="0.01" data-tvwb-end-number> 秒</span><em data-tvwb-selection-length>5.00 秒</em>
                  <label class="desk-topaz-video-workbench__timeline-zoom"><span>缩放</span><input type="range" min="1" max="4" step="1" value="1" data-tvwb-timeline-zoom><output data-tvwb-timeline-zoom-label>1×</output></label>
                </div>
                <div class="desk-topaz-video-workbench__timeline-scroll" data-tvwb-timeline-scroll>
                  <div class="desk-topaz-video-workbench__timeline-track" data-tvwb-timeline-track>
                    <div class="desk-topaz-video-workbench__timeline-editor" data-tvwb-timeline tabindex="0" aria-label="视频时间轴">
                      <div class="desk-topaz-video-workbench__filmstrip" data-tvwb-filmstrip><div class="desk-topaz-video-workbench__filmstrip-placeholder"></div></div>
                      <div class="desk-topaz-video-workbench__timeline-shade is-before" data-tvwb-shade-start></div>
                      <div class="desk-topaz-video-workbench__timeline-shade is-after" data-tvwb-shade-end></div>
                      <div class="desk-topaz-video-workbench__selection" data-tvwb-selection>
                        <button type="button" class="is-start" data-tvwb-trim="start" aria-label="拖动预览入点"></button>
                        <button type="button" class="is-end" data-tvwb-trim="end" aria-label="拖动预览出点"></button>
                      </div>
                      <div class="desk-topaz-video-workbench__playhead" data-tvwb-playhead-marker aria-hidden="true"><span></span></div>
                    </div>
                    <div class="desk-topaz-video-workbench__ruler" data-tvwb-ruler></div>
                  </div>
                </div>
                <div class="desk-topaz-video-workbench__queues" aria-label="任务队列">
                  <span><b>预览队列</b><i data-tvwb-preview-queue>空闲</i></span>
                  <span><b>素材</b><i data-tvwb-source-queue>当前视频</i></span>
                  <span><b>导出队列</b><i data-tvwb-export-queue>空闲</i></span>
                </div>
              </div>
            </main>
            <aside class="desk-topaz-video-workbench__sidebar">
              <nav><button type="button" class="is-active" data-tvwb-tab="adjustments">调整</button><button type="button" data-tvwb-tab="output">编码设置</button></nav>
              <div class="desk-topaz-video-workbench__panel" data-tvwb-panel></div>
              <div class="desk-topaz-video-workbench__job" data-tvwb-job hidden><div><span data-tvwb-job-bar></span></div><strong data-tvwb-job-percent>处理中</strong><small data-tvwb-job-stage>正在准备</small></div>
              <footer><label class="desk-topaz-video-workbench__export-scope"><input type="checkbox" data-tvwb-export-selection>仅导出选区</label><button type="button" class="is-preview" data-tvwb-preview>预览选区</button><button type="button" class="is-export" data-tvwb-export>导出完整视频</button><small>停止、进度与错误由画布底部统一任务控制管理</small></footer>
            </aside>
          </div>
        </section>`;
      document.body.appendChild(root);
      bind();
    }

    function meta() { return current?.catalog?.find(item => item.id === current.node.model); }

    function option(value, label, active, disabled = false) {
      return `<option value="${esc(value)}"${String(value) === String(active) ? ' selected' : ''}${disabled ? ' disabled' : ''}>${esc(label)}</option>`;
    }

    function resolveWorkflowPreset(preset) {
      const catalog = current?.catalog || [];
      for (const [modelId, scale] of preset.choices) {
        const entry = catalog.find(item => item.id === modelId);
        if (entry?.available && entry.scales.includes(scale)) return {entry, scale};
      }
      return null;
    }

    function workflowPresetCards() {
      return WORKFLOW_PRESETS.map(preset => {
        const resolved = resolveWorkflowPreset(preset);
        const active = state.activeWorkflowPreset === preset.id;
        const modelLabel = resolved?.entry?.label || '本机模型未就绪';
        return `<button type="button" class="desk-topaz-video-workbench__preset${active ? ' is-active' : ''}" data-tvwb-workflow-preset="${esc(preset.id)}" data-tvwb-available="${resolved ? 'true' : 'false'}"${resolved ? '' : ' disabled'}>
          <strong>${esc(preset.label)}</strong><span>${esc(preset.detail)}</span><small>${esc(modelLabel)}</small>
        </button>`;
      }).join('');
    }

    function parameterControls(selected) {
      if (!selected?.parameters?.length) return '<p class="desk-topaz-video-workbench__no-params">此模型使用固定参数，无需额外调节。</p>';
      return selected.parameters.map(field => `<label><span>${esc(field.label)}</span><div><input type="range" min="${esc(field.min)}" max="${esc(field.max)}" step="${esc(field.step > 0 ? field.step : 'any')}" value="${esc(current.node.modelParams[field.key])}" data-tvwb-param-range="${esc(field.key)}"><input type="number" min="${esc(field.min)}" max="${esc(field.max)}" step="${esc(field.step > 0 ? field.step : 'any')}" value="${esc(current.node.modelParams[field.key])}" data-tvwb-param-number="${esc(field.key)}"></div></label>`).join('');
    }

    function renderOutputPanel(panel) {
      panel.innerHTML = inspector.output(current.node, current.source, current.runtimeStatus);
    }

    function renderAdjustmentsPanel(panel) {
      const selected = meta();
      const models = current.catalog || [];
      const modelOptions = models.map(item => option(item.id,
        item.label + (item.available ? item.verified ? '' : ' · 建议短测' : ' · 不可用'), current.node.model, !item.available)).join('');
      const scaleOptions = (selected?.scales || []).map(value => option(value, value + '×', current.node.scale)).join('');
      const presetOptions = model.PRESETS.map(item => option(item.id, item.label, current.node.presetId)).join('');
      const source = current.source || {};
      const width = Math.max(0, finite(source.width)) * (current.node.enhancementEnabled ? Math.max(1, finite(current.node.scale, 1)) : 1);
      const height = Math.max(0, finite(source.height)) * (current.node.enhancementEnabled ? Math.max(1, finite(current.node.scale, 1)) : 1);
      panel.innerHTML = `<section class="desk-topaz-video-workbench__settings">
        <details data-tvwb-section="presets"><summary class="desk-topaz-video-workbench__section-title"><strong>内置预设</strong><span>按素材用途选择</span></summary>
        <div class="desk-topaz-video-workbench__preset-grid">${workflowPresetCards()}</div></details>
        <details data-tvwb-section="enhancement" class="desk-topaz-video-workbench__adjustment is-enabled"><summary><span><strong>增强</strong><small>${width && height ? `输出 ${width} × ${height}` : '高清修复与放大'}</small></span><i>${current.node.enhancementEnabled ? '已启用' : '已关闭'}</i></summary>
          <div class="desk-topaz-video-workbench__adjustment-body">
            ${inspector.toggle('enhancement', 'enabled', '启用增强与放大', current.node.enhancementEnabled)}
            <label><span>AI 模型</span><select data-tvwb-model>${modelOptions}</select></label>
            <div class="desk-topaz-video-workbench__setting-row"><label><span>参数模式</span><select data-tvwb-preset>${presetOptions}</select></label><label><span>输出倍率</span><select data-tvwb-scale>${scaleOptions}</select></label></div>
            <div class="desk-topaz-video-workbench__parameter-list">${parameterControls(selected)}</div>
            <div class="desk-topaz-video-workbench__model-note"><strong>${esc(selected?.label || current.node.model)}</strong><p>${esc(selected?.reason || (selected?.verified ? '本机短片导出已验证。' : '模型资源已就绪，建议先生成短选区预览。'))}</p></div>
          </div>
        </details>
        <div class="desk-topaz-video-workbench__filter-stack">
          ${inspector.filters(current.node, current.runtimeStatus)}
        </div>
      </section>`;
    }

    function renderPanel() {
      if (!current) return;
      const panel = q('[data-tvwb-panel]');
      const scrollTop = panel.scrollTop;
      const focused = panel.contains(document.activeElement) ? document.activeElement : null;
      const focusedGroup = focused?.dataset?.tvwbProcessing;
      const focusedKey = focused?.dataset?.tvwbKey;
      const sections = [...panel.querySelectorAll('details')].map(item => [item.dataset.tvwbSection || item.dataset.tvwbFeature, item.open]);
      if (state.tab === 'output') renderOutputPanel(panel);
      else renderAdjustmentsPanel(panel);
      for (const [key, open] of sections) {
        const item = panel.querySelector(`[data-tvwb-section="${key}"],[data-tvwb-feature="${key}"]`);
        if (item) item.open = open;
      }
      panel.scrollTop = scrollTop;
      if (focusedGroup && focusedKey) {
        const replacement = [...panel.querySelectorAll('[data-tvwb-processing]')].find(input =>
          input.dataset.tvwbProcessing === focusedGroup && input.dataset.tvwbKey === focusedKey);
        if (replacement && !replacement.disabled) replacement.focus({preventScroll: true});
      }
      const configModel = q('[data-tvwb-config-model]');
      if (configModel) configModel.textContent = current.node.enhancementEnabled === false ? '仅滤镜 / 编码' : meta()?.label || '当前模型';
    }

    function updateTabs() {
      root.querySelectorAll('[data-tvwb-tab]').forEach(button => button.classList.toggle('is-active', button.dataset.tvwbTab === state.tab));
      renderPanel(); updateBusy();
    }

    function mediaBand() {
      const viewer = q('[data-tvwb-viewer]');
      const video = q('[data-tvwb-source-video]');
      const rect = viewer?.getBoundingClientRect();
      if (!rect?.width || !rect?.height) return null;
      const width = video?.videoWidth || finite(current?.source?.width);
      const height = video?.videoHeight || finite(current?.source?.height);
      if (!(width > 0 && height > 0)) return {rect, left: 0, top: 0, width: rect.width, height: rect.height};
      const fit = Math.min(rect.width / width, rect.height / height);
      const bandWidth = width * fit * state.zoom, bandHeight = height * fit * state.zoom;
      const rawLeft = (rect.width - bandWidth) / 2 + state.panX;
      const rawTop = (rect.height - bandHeight) / 2 + state.panY;
      const left = clamp(rawLeft, 0, rect.width), top = clamp(rawTop, 0, rect.height);
      const right = clamp(rawLeft + bandWidth, 0, rect.width), bottom = clamp(rawTop + bandHeight, 0, rect.height);
      return {rect, left, top, width: Math.max(0, right - left), height: Math.max(0, bottom - top), rawLeft, rawTop, bandWidth, bandHeight};
    }

    function clampPan() {
      const viewer = q('[data-tvwb-viewer]'), video = q('[data-tvwb-source-video]');
      const rect = viewer?.getBoundingClientRect();
      const width = video?.videoWidth || finite(current?.source?.width);
      const height = video?.videoHeight || finite(current?.source?.height);
      if (!rect?.width || !rect?.height || !(width > 0 && height > 0) || state.zoom <= 1) {
        state.panX = 0; state.panY = 0; return;
      }
      const fit = Math.min(rect.width / width, rect.height / height);
      const overflowX = Math.max(0, (width * fit * state.zoom - rect.width) / 2);
      const overflowY = Math.max(0, (height * fit * state.zoom - rect.height) / 2);
      state.panX = clamp(state.panX, -overflowX, overflowX);
      state.panY = clamp(state.panY, -overflowY, overflowY);
    }

    function updateZoom() {
      if (!current) return;
      clampPan();
      const transform = `translate3d(${state.panX}px,${state.panY}px,0) scale(${state.zoom})`;
      q('[data-tvwb-source-video]').style.transform = transform;
      q('[data-tvwb-result-video]').style.transform = transform;
      const viewer = q('[data-tvwb-viewer]');
      viewer.classList.toggle('is-zoomed', state.zoom > 1);
      const button = q('[data-tvwb-zoom]');
      const zoomed = state.zoom > 1;
      button.classList.toggle('is-active', zoomed); button.setAttribute('aria-pressed', String(zoomed));
      button.title = zoomed ? '还原适应视图' : '放大对比视频';
      button.querySelector('span').textContent = zoomed ? '还原' : '放大';
      root.querySelectorAll('[data-tvwb-zoom-level]').forEach(control =>
        control.classList.toggle('is-active', Number(control.dataset.tvwbZoomLevel) === state.zoom));
      updateCompare();
    }

    function toggleZoom() {
      state.zoom = state.zoom > 1 ? 1 : 2;
      if (state.zoom === 1) {state.panX = 0; state.panY = 0;}
      updateZoom();
    }

    function applyPan(clientX, clientY) {
      if (drag?.kind !== 'pan') return;
      state.panX = drag.startPanX + clientX - drag.startX;
      state.panY = drag.startPanY + clientY - drag.startY;
      updateZoom();
    }

    function updateCompare() {
      if (!current) return;
      const hasResult = Boolean(current.result?.url);
      if (!hasResult && state.mode !== 'original') state.mode = 'original';
      const viewer = q('[data-tvwb-viewer]');
      viewer.classList.toggle('is-side-by-side', state.mode === 'side' && hasResult);
      // The seam expresses how much of the original remains on the left;
      // the processed layer is revealed from the seam to the right.
      const amount = state.mode === 'original' ? 100 : state.mode === 'result' ? 0 : clamp(state.compare, 0, 100);
      const band = mediaBand();
      const layer = q('[data-tvwb-result-layer]');
      const divider = q('[data-tvwb-divider]');
      if (state.mode === 'side' && hasResult) {
        layer.style.clipPath = 'none';
      } else if (band) {
        const seam = band.left + band.width * amount / 100;
        layer.style.clipPath = `inset(0 0 0 ${Math.max(0, seam)}px)`;
        divider.style.left = seam + 'px'; divider.style.top = band.top + 'px'; divider.style.height = band.height + 'px';
      } else {
        layer.style.clipPath = `inset(0 0 0 ${amount}%)`;
        divider.style.left = amount + '%'; divider.style.top = '0'; divider.style.height = '100%';
      }
      root.querySelectorAll('[data-tvwb-mode]').forEach(button => {
        button.classList.toggle('is-active', button.dataset.tvwbMode === state.mode);
        button.disabled = !hasResult && button.dataset.tvwbMode !== 'original';
      });
      divider.hidden = state.mode !== 'compare' || !hasResult;
      divider.setAttribute('aria-valuenow', String(Math.round(state.compare)));
      divider.setAttribute('aria-valuetext', `原片 ${Math.round(state.compare)}%，处理后 ${Math.round(100 - state.compare)}%`);
      q('.desk-topaz-video-workbench__media-label.is-result').hidden = !hasResult;
      q('[data-tvwb-empty]').hidden = Boolean(current?.source?.url) && (state.mode === 'original' || hasResult);
      root.querySelectorAll('[data-tvwb-preview-config]').forEach(button => button.classList.toggle('is-active',
        button.dataset.tvwbPreviewConfig === (state.mode === 'original' ? 'source' : 'current')));
    }

    function revealAt(clientX) {
      const band = mediaBand();
      if (!band?.width) return;
      state.compare = clamp((clientX - band.rect.left - band.left) / band.width * 100, 0, 100);
      updateCompare();
    }

    function renderRuler(duration) {
      const ruler = q('[data-tvwb-ruler]');
      if (!ruler) return;
      const labels = Array.from({length: 5}, (_, index) => `<span>${clock(duration * index / 4)}</span>`).join('');
      if (ruler.dataset.labels !== labels) {ruler.dataset.labels = labels; ruler.innerHTML = labels;}
    }

    function updateTimeline() {
      if (!current) return;
      const duration = Math.max(.01, state.duration || finite(current.source?.duration) || 5);
      const floor = selectionFloor(duration);
      state.start = clamp(state.start, 0, Math.max(0, duration - floor));
      state.end = clamp(state.end, Math.min(duration, state.start + floor), duration);
      if (state.end < state.start) state.end = state.start;
      state.position = clamp(state.position, state.start, state.end);
      const startNumber = q('[data-tvwb-start-number]'), endNumber = q('[data-tvwb-end-number]');
      startNumber.max = String(duration); startNumber.value = state.start.toFixed(2);
      endNumber.max = String(duration); endNumber.value = state.end.toFixed(2);
      q('[data-tvwb-selection-length]').textContent = (state.end - state.start).toFixed(2) + ' 秒';
      const left = state.start / duration * 100, right = state.end / duration * 100;
      q('[data-tvwb-selection]').style.left = left + '%';
      q('[data-tvwb-selection]').style.width = Math.max(0, right - left) + '%';
      q('[data-tvwb-shade-start]').style.width = left + '%';
      q('[data-tvwb-shade-end]').style.left = right + '%';
      q('[data-tvwb-shade-end]').style.width = Math.max(0, 100 - right) + '%';
      q('[data-tvwb-playhead-marker]').style.left = state.position / duration * 100 + '%';
      q('[data-tvwb-current]').textContent = clock(state.position, true);
      q('[data-tvwb-duration]').textContent = clock(duration, true);
      q('[data-tvwb-timeline-track]').style.width = `${Math.max(1, state.timelineZoom) * 100}%`;
      q('[data-tvwb-timeline-zoom-label]').textContent = state.timelineZoom + '×';
      renderRuler(duration);
    }

    function markSelection(kind) {
      const duration = Math.max(.01, state.duration || finite(current?.source?.duration) || 5);
      const floor = selectionFloor(duration);
      if (kind === 'start') {
        state.start = clamp(state.position, 0, Math.max(0, state.end - floor));
      } else if (kind === 'end') {
        state.end = clamp(state.position, Math.min(duration, state.start + floor), duration);
      } else {
        state.start = 0; state.end = duration;
      }
      state.position = clamp(state.position, state.start, state.end);
      seek(state.position);
    }

    function setMuted(muted) {
      state.muted = Boolean(muted);
      const source = q('[data-tvwb-source-video]');
      if (source) source.muted = state.muted;
      const button = q('[data-tvwb-mute]');
      if (button) {
        button.textContent = state.muted ? '静音' : '有声';
        button.title = state.muted ? '打开原片声音' : '关闭原片声音';
        button.setAttribute('aria-pressed', String(state.muted));
        button.classList.toggle('is-active', !state.muted);
      }
    }

    function applyWorkflowPreset(id) {
      const preset = WORKFLOW_PRESETS.find(item => item.id === id);
      const resolved = preset && resolveWorkflowPreset(preset);
      if (!resolved) return;
      state.activeWorkflowPreset = preset.id;
      patch({model: resolved.entry.id, scale: resolved.scale, presetId: 'recommended',
        processing: {group: 'enhancement', key: 'enabled', value: true}});
    }

    function timelineTime(clientX, rect) {
      const duration = Math.max(.01, state.duration || finite(current?.source?.duration) || 5);
      return clamp((clientX - rect.left) / Math.max(1, rect.width) * duration, 0, duration);
    }

    function applyTimelineDrag(clientX) {
      if (drag?.kind !== 'timeline') return;
      const duration = Math.max(.01, state.duration || finite(current?.source?.duration) || 5);
      const floor = selectionFloor(duration), value = timelineTime(clientX, drag.rect);
      if (drag.mode === 'start') {
        state.start = clamp(value, 0, Math.max(0, state.end - floor));
        if (state.position < state.start) seek(state.start); else updateTimeline();
      } else if (drag.mode === 'end') {
        state.end = clamp(value, Math.min(duration, state.start + floor), duration);
        if (state.position > state.end) seek(state.end); else updateTimeline();
      } else {pause(); seek(clamp(value, state.start, state.end));}
    }

    function seek(position, {fromVideo = false} = {}) {
      if (!current) return;
      state.position = clamp(finite(position), state.start, state.end);
      const source = q('[data-tvwb-source-video]'), result = q('[data-tvwb-result-video]');
      // This is an explicit scrub/frame-step, not a playback drift correction.
      // A fixed 35/80 ms deadband skips frames at 30–120 fps.
      if (!fromVideo && source.readyState >= 1 && Math.abs(source.currentTime - state.position) > .001) source.currentTime = state.position;
      if (result.src && result.readyState >= 1) {
        const relative = clamp((state.position - state.resultStart) * state.resultTimeScale, 0, Math.max(0, result.duration || state.end - state.start));
        if (Math.abs(result.currentTime - relative) > .001) result.currentTime = relative;
      }
      updateTimeline();
    }

    function paintPlayback() {
      const source = q('[data-tvwb-source-video]');
      const playing = Boolean(source?.src && !source.paused && !source.ended);
      const button = q('[data-tvwb-play]');
      if (!button) return;
      stateIcon.paint(button.querySelector('svg'), playing ? 'pause' : 'play');
      button.setAttribute('aria-label', playing ? '暂停' : '播放');
    }

    function pause() {
      q('[data-tvwb-source-video]')?.pause(); q('[data-tvwb-result-video]')?.pause();
      paintPlayback();
    }

    async function togglePlay() {
      const source = q('[data-tvwb-source-video]'), result = q('[data-tvwb-result-video]');
      if (!source?.src) return;
      if (!source.paused) {pause(); return;}
      if (state.position >= state.end - frameDuration()) seek(state.start);
      try {
        source.playbackRate = 1 / state.resultTimeScale;
        result.playbackRate = 1;
        await source.play();
        if (result.src && state.position >= state.resultStart) result.play().catch(() => {});
        paintPlayback();
      } catch (_error) { pause(); }
    }

    function resetRangeFromContext() {
      const duration = Math.max(.01, state.duration || finite(current?.source?.duration) || 5);
      const floor = selectionFloor(duration);
      const savedStart = Math.max(0, finite(current?.node?.previewStartSeconds));
      const savedDuration = Math.max(0, finite(current?.node?.previewDurationSeconds));
      state.start = clamp(savedStart, 0, Math.max(0, duration - floor));
      const wanted = savedDuration > 0 ? savedDuration : Math.min(5, duration - state.start);
      state.end = clamp(state.start + Math.max(floor, wanted), Math.min(duration, state.start + floor), duration);
      state.position = state.start;
    }

    function applySourceMetadata({resetRange = false} = {}) {
      if (!current) return;
      const video = q('[data-tvwb-source-video]');
      const duration = finite(video?.duration) > 0 ? finite(video.duration) : finite(current.source?.duration);
      if (duration > 0) state.duration = duration;
      const sourceFps = finite(current.source?.fps); if (sourceFps > 0) state.fps = sourceFps;
      if (resetRange) resetRangeFromContext();
      updateTimeline(); updateViewMeta(); updateCompare();
      if (resetRange) seek(state.start);
    }

    function loadSource(source) {
      const video = q('[data-tvwb-source-video]');
      q('[data-tvwb-source-name]').textContent = source?.name || '未连接视频';
      q('[data-tvwb-source-queue]').textContent = source?.name || '等待素材';
      if (!source?.url) {
        pause(); video.removeAttribute('src'); video.dataset.url = ''; video.load();
        state.duration = 0; updateTimeline(); return;
      }
      if (video.dataset.url !== source.url) {
        pause(); state.zoom = 1; state.panX = 0; state.panY = 0;
        video.dataset.url = source.url; video.src = source.url; video.load(); buildFilmstrip(source.url); updateZoom();
      }
      setMuted(state.muted);
    }

    function loadResult(result) {
      const video = q('[data-tvwb-result-video]'), empty = q('[data-tvwb-empty]');
      if (!result?.url) {
        state.resultTimeScale = 1;
        video.removeAttribute('src'); video.dataset.url = ''; video.load(); empty.hidden = false; updateCompare(); return;
      }
      state.resultStart = Math.max(0, finite(result.startSeconds));
      state.resultTimeScale = Math.max(1, finite(result.timeScale, 1));
      if (video.dataset.url !== result.url) {video.dataset.url = result.url; video.src = result.url; video.load(); state.mode = 'compare';}
      empty.hidden = true; updateCompare(); seek(state.position);
    }

    function updateBusy() {
      if (!current) return;
      const busy = current.busy || {};
      const active = Boolean(busy.pending) || model.active(busy.status);
      const label = busy.kind === 'preview' && active ? '预览处理中' : model.labels[busy.status] || '就绪';
      q('[data-tvwb-status]').textContent = label; q('[data-tvwb-status]').classList.toggle('is-busy', active);
      q('[data-tvwb-preview]').disabled = active || !current.source?.url;
      q('[data-tvwb-export]').disabled = active || !current.source?.url;
      q('[data-tvwb-import]').disabled = active;
      q('[data-tvwb-refresh]').disabled = active;
      q('[data-tvwb-export-selection]').disabled = active;
      root.querySelectorAll('[data-tvwb-processing]').forEach(control => {control.disabled = active || control.dataset.tvwbUnavailable === 'true';});
      q('[data-tvwb-zoom]').disabled = !current.source?.url;
      root.querySelectorAll('[data-tvwb-model],[data-tvwb-scale],[data-tvwb-preset],[data-tvwb-param-range],[data-tvwb-param-number]')
        .forEach(control => {control.disabled = active || current.node.enhancementEnabled === false;});
      const jobBox = q('[data-tvwb-job]'); jobBox.hidden = !active;
      const percent = finite(busy.job?.progress_percent, 0);
      q('[data-tvwb-job-bar]').style.width = (busy.job?.progress_percent == null ? 28 : clamp(percent, 0, 100)) + '%';
      q('[data-tvwb-job-percent]').textContent = busy.job?.progress_percent == null ? label : Math.round(percent) + '%';
      q('[data-tvwb-job-stage]').textContent = busy.pending ? '正在提交素材…' : String(busy.job?.progress_message || busy.job?.stage || label);
      q('[data-tvwb-preview]').textContent = active && busy.kind === 'preview' ? '正在生成预览…' : '预览选区';
      q('[data-tvwb-export]').textContent = active && busy.kind !== 'preview' ? '正在导出…' : state.exportSelection ? '导出选区' : '导出完整视频';
      q('[data-tvwb-preview-queue]').textContent = busy.kind === 'preview' && active ? label : current.result?.stale ? '设置已更改 · 预览待更新'
        : current.result?.job?.spec?.task_kind === 'preview' ? '已完成' : '空闲';
      q('[data-tvwb-export-queue]').textContent = busy.kind !== 'preview' && active ? label
        : current.node?.status === 'succeeded' ? '已完成' : '空闲';
      root.querySelectorAll('[data-tvwb-workflow-preset]').forEach(control => {
        control.disabled = active || control.dataset.tvwbAvailable !== 'true';
      });
    }

    function updateViewMeta() {
      const source = q('[data-tvwb-source-video]');
      const width = source?.videoWidth || current?.source?.width || 0;
      const height = source?.videoHeight || current?.source?.height || 0;
      const fps = finite(current?.source?.fps) || state.fps;
      q('[data-tvwb-view-meta]').textContent = width && height
        ? `${width} × ${height} · ${Number(fps.toFixed(2))} fps · ${clock(state.duration)}` : clock(state.duration);
    }

    function updateContext(next = {}) {
      if (!current) return;
      const previousCatalog = current.catalog;
      const previousSourceUrl = current.source?.url || '';
      const previousResultUrl = current.result?.url || '';
      const previousResultStart = finite(current.result?.startSeconds);
      Object.assign(current, next);
      if (next.catalog && next.catalog !== previousCatalog) renderPanel();
      if (hasOwn(next, 'source')) {
        if ((current.source?.url || '') !== previousSourceUrl) loadSource(current.source);
        else q('[data-tvwb-source-name]').textContent = current.source?.name || '未连接视频';
        if (!state.duration && finite(current.source?.duration) > 0) applySourceMetadata();
      }
      if (hasOwn(next, 'result')) {
        const nextUrl = current.result?.url || '', nextStart = finite(current.result?.startSeconds);
        if (nextUrl !== previousResultUrl || nextStart !== previousResultStart) loadResult(current.result);
      }
      updateBusy(); updateViewMeta(); updateTimeline(); updateCompare();
    }

    async function buildFilmstrip(url) {
      const own = ++state.filmstripToken;
      state.filmstripUrl = url;
      const container = q('[data-tvwb-filmstrip]');
      container.classList.remove('is-unavailable');
      container.innerHTML = Array.from({length: 10}, () => '<canvas width="160" height="84"></canvas>').join('');
      const canvases = [...container.querySelectorAll('canvas')];
      const video = document.createElement('video');
      video.muted = true; video.preload = 'metadata'; video.playsInline = true; video.src = url;
      const once = (name, timeout = 12000) => new Promise((resolve, reject) => {
        const timer = setTimeout(() => {cleanup(); reject(new Error('timeout'));}, timeout);
        const cleanup = () => {clearTimeout(timer); video.removeEventListener(name, done); video.removeEventListener('error', fail);};
        const done = () => {cleanup(); resolve();}, fail = () => {cleanup(); reject(new Error('video'));};
        video.addEventListener(name, done, {once: true}); video.addEventListener('error', fail, {once: true});
      });
      try {
        await once('loadedmetadata');
        const duration = Math.max(.01, video.duration || state.duration || 1);
        for (let index = 0; index < canvases.length; index++) {
          if (own !== state.filmstripToken || !current) return;
          const target = Math.min(Math.max(0, duration - .03), duration * index / Math.max(1, canvases.length - 1));
          if (Math.abs(video.currentTime - target) > .005) {video.currentTime = target; await once('seeked', 5000);}
          const canvas = canvases[index], context = canvas.getContext('2d');
          if (!context || !video.videoWidth || !video.videoHeight) continue;
          const scale = Math.max(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
          const width = video.videoWidth * scale, height = video.videoHeight * scale;
          context.drawImage(video, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
        }
      } catch (_error) {container.classList.add('is-unavailable');}
      finally {video.removeAttribute('src'); video.load();}
    }

    function patch(change) {
      if (!current) return;
      current.onPatch?.(change); renderPanel(); updateBusy();
    }

    function parameterKey(input) { return input.dataset.tvwbParamRange || input.dataset.tvwbParamNumber || ''; }

    function syncParameterDraft(input) {
      const key = parameterKey(input);
      if (!key || input.value === '') return;
      const field = meta()?.parameters.find(item => item.key === key), value = Number(input.value);
      if (!field || !Number.isFinite(value)) return;
      root.querySelectorAll(`[data-tvwb-param-range="${key}"],[data-tvwb-param-number="${key}"]`)
        .forEach(peer => {if (peer !== input) peer.value = String(value);});
      const preset = q('[data-tvwb-preset]'); if (preset) preset.value = 'custom';
    }

    function commitParameter(input) {
      const key = parameterKey(input);
      if (!key) return;
      const field = meta()?.parameters.find(item => item.key === key);
      let value = Number(input.value);
      if (!field || !Number.isFinite(value)) {renderPanel(); updateBusy(); return;}
      value = clamp(value, field.min, field.max);
      root.querySelectorAll(`[data-tvwb-param-range="${key}"],[data-tvwb-param-number="${key}"]`).forEach(peer => {peer.value = String(value);});
      state.activeWorkflowPreset = '';
      current.onPatch?.({parameter: {key, value}, presetId: 'custom'});
      const preset = q('[data-tvwb-preset]'); if (preset) preset.value = 'custom';
    }

    function endDrag(event) {
      if (!drag || (event && drag.id !== event.pointerId)) return;
      const active = drag; drag = null;
      try {active.target.releasePointerCapture(active.id);} catch (_error) { /* Capture may already be gone. */ }
      root.classList.remove('is-dragging-divider', 'is-dragging-timeline', 'is-dragging-viewer');
    }

    function bind() {
      root.addEventListener('click', event => {
        event.stopPropagation();
        const target = event.target;
        if (target.closest('[data-tvwb-close]')) {close(); return;}
        const mode = target.closest('[data-tvwb-mode]'); if (mode) {state.mode = mode.dataset.tvwbMode; updateCompare(); return;}
        const previewConfig = target.closest('[data-tvwb-preview-config]');
        if (previewConfig) {
          state.mode = previewConfig.dataset.tvwbPreviewConfig === 'source' ? 'original' : current?.result?.url ? 'compare' : 'original';
          updateCompare(); return;
        }
        const workflowPreset = target.closest('[data-tvwb-workflow-preset]');
        if (workflowPreset && !workflowPreset.disabled) {applyWorkflowPreset(workflowPreset.dataset.tvwbWorkflowPreset); return;}
        const zoomLevel = target.closest('[data-tvwb-zoom-level]');
        if (zoomLevel) {
          state.zoom = Number(zoomLevel.dataset.tvwbZoomLevel) || 1;
          if (state.zoom === 1) {state.panX = 0; state.panY = 0;}
          updateZoom(); return;
        }
        if (target.closest('[data-tvwb-zoom]')) {toggleZoom(); return;}
        if (target.closest('[data-tvwb-mute]')) {setMuted(!state.muted); return;}
        const mark = target.closest('[data-tvwb-mark]'); if (mark) {markSelection(mark.dataset.tvwbMark); return;}
        if (target.closest('[data-tvwb-sidebar-toggle]')) {
          state.sidebarCollapsed = !state.sidebarCollapsed;
          root.classList.toggle('is-sidebar-collapsed', state.sidebarCollapsed);
          const button = q('[data-tvwb-sidebar-toggle]');
          button.setAttribute('aria-pressed', String(state.sidebarCollapsed));
          button.title = state.sidebarCollapsed ? '展开参数面板' : '收起参数面板';
          button.textContent = state.sidebarCollapsed ? '‹' : '›';
          return;
        }
        const tab = target.closest('[data-tvwb-tab]'); if (tab) {state.tab = tab.dataset.tvwbTab; updateTabs(); return;}
        if (target.closest('[data-tvwb-play]')) {togglePlay(); return;}
        const step = target.closest('[data-tvwb-step]');
        if (step) {pause(); seek(state.position + Number(step.dataset.tvwbStep) * frameDuration()); return;}
        const jump = target.closest('[data-tvwb-jump]');
        if (jump) {pause(); seek(jump.dataset.tvwbJump === 'start' ? state.start : state.end); return;}
        if (target.closest('[data-tvwb-refresh]')) {current?.onRefresh?.(); return;}
        if (target.closest('[data-tvwb-import]')) {current?.onImport?.(); return;}
        if (target.closest('[data-tvwb-preview]')) {
          const duration = Math.max(selectionFloor(Math.max(.01, state.duration || 5)), state.end - state.start);
          current?.onPreview?.({startSeconds: state.start, maxSeconds: duration}); return;
        }
        if (target.closest('[data-tvwb-export]')) current?.onExport?.(state.exportSelection ? {startSeconds: state.start, maxSeconds: state.end - state.start} : undefined);
      });

      root.addEventListener('input', event => {
        const input = event.target;
        if (input.matches('[data-tvwb-start-number]') && input.value !== '') {
          const floor = selectionFloor(Math.max(.01, state.duration || 5));
          state.start = clamp(Number(input.value), 0, Math.max(0, state.end - floor));
          if (state.position < state.start) seek(state.start); else updateTimeline(); return;
        }
        if (input.matches('[data-tvwb-end-number]') && input.value !== '') {
          const duration = Math.max(.01, state.duration || Number(input.max) || 5), floor = selectionFloor(duration);
          state.end = clamp(Number(input.value), Math.min(duration, state.start + floor), duration);
          if (state.position > state.end) seek(state.end); else updateTimeline(); return;
        }
        if (input.matches('[data-tvwb-timeline-zoom]')) {
          state.timelineZoom = clamp(Math.round(Number(input.value) || 1), 1, 4);
          updateTimeline(); return;
        }
        if (parameterKey(input)) syncParameterDraft(input);
      });

      root.addEventListener('change', event => {
        const input = event.target;
        if (input.matches('[data-tvwb-export-selection]')) {state.exportSelection = input.checked; updateBusy(); return;}
        const processing = inspector.change(input);
        if (processing) {patch(processing); return;}
        if (input.matches('[data-tvwb-model]')) {state.activeWorkflowPreset = ''; patch({model: input.value}); return;}
        if (input.matches('[data-tvwb-scale]')) {state.activeWorkflowPreset = ''; patch({scale: Number(input.value)}); return;}
        if (input.matches('[data-tvwb-preset]')) {state.activeWorkflowPreset = ''; patch({presetId: input.value}); return;}
        if (parameterKey(input)) commitParameter(input);
      });

      root.addEventListener('pointerdown', event => {
        event.stopPropagation();
        if (event.button !== 0 || drag) return;
        const divider = event.target.closest('[data-tvwb-divider]');
        if (divider && state.mode === 'compare' && current?.result?.url) {
          drag = {kind: 'divider', id: event.pointerId, target: divider};
          try {divider.setPointerCapture(event.pointerId);} catch (_error) { /* Synthetic pointer. */ }
          root.classList.add('is-dragging-divider'); revealAt(event.clientX); event.preventDefault(); return;
        }
        const viewer = event.target.closest('[data-tvwb-viewer]');
        if (viewer && state.zoom > 1) {
          drag = {kind: 'pan', id: event.pointerId, target: viewer, startX: event.clientX, startY: event.clientY,
            startPanX: state.panX, startPanY: state.panY};
          try {viewer.setPointerCapture(event.pointerId);} catch (_error) { /* Synthetic pointer. */ }
          root.classList.add('is-dragging-viewer'); event.preventDefault(); return;
        }
        const timeline = event.target.closest('[data-tvwb-timeline]');
        if (timeline) {
          const trim = event.target.closest('[data-tvwb-trim]');
          drag = {kind: 'timeline', mode: trim?.dataset.tvwbTrim || 'playhead', id: event.pointerId,
            target: timeline, rect: timeline.getBoundingClientRect()};
          try {timeline.setPointerCapture(event.pointerId);} catch (_error) { /* Synthetic pointer. */ }
          root.classList.add('is-dragging-timeline'); applyTimelineDrag(event.clientX);
          timeline.focus({preventScroll: true}); event.preventDefault();
        }
      });
      root.addEventListener('pointermove', event => {
        if (!drag || drag.id !== event.pointerId) return;
        if (drag.kind === 'divider') revealAt(event.clientX);
        else if (drag.kind === 'pan') applyPan(event.clientX, event.clientY);
        else applyTimelineDrag(event.clientX);
      });
      ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => root.addEventListener(type, endDrag));

      root.addEventListener('keydown', event => {
        const divider = event.target.closest?.('[data-tvwb-divider]');
        if (divider && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          if (event.key === 'Home') state.compare = 0;
          else if (event.key === 'End') state.compare = 100;
          else state.compare = clamp(state.compare + (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 10 : 1), 0, 100);
          updateCompare(); event.preventDefault(); event.stopPropagation();
          return;
        }
        if (event.target.closest?.('input,select,button,textarea')) return;
        const key = String(event.key || '').toLowerCase();
        if (key === ' ' || key === 'k') {togglePlay(); event.preventDefault();}
        else if (key === 'i') {markSelection('start'); event.preventDefault();}
        else if (key === 'o') {markSelection('end'); event.preventDefault();}
        else if (key === 'arrowleft' || key === 'arrowright') {
          pause(); seek(state.position + (key === 'arrowleft' ? -1 : 1) * frameDuration()); event.preventDefault();
        }
      });
      root.addEventListener('wheel', event => event.stopPropagation(), {passive: true});
      root.addEventListener('dragstart', event => event.preventDefault());

      const source = q('[data-tvwb-source-video]');
      source.addEventListener('loadedmetadata', () => applySourceMetadata({resetRange: true}));
      source.addEventListener('timeupdate', () => {
        if (!current) return;
        if (source.currentTime >= state.end - Math.min(.015, frameDuration() / 2)) {pause(); seek(state.end); return;}
        state.position = clamp(source.currentTime, state.start, state.end);
        const result = q('[data-tvwb-result-video]');
        if (result.src && result.readyState >= 1) {
          const relative = clamp((state.position - state.resultStart) * state.resultTimeScale, 0, Math.max(0, result.duration || state.end - state.start));
          if (Math.abs(result.currentTime - relative) > .12) result.currentTime = relative;
        }
        updateTimeline();
      });
      source.addEventListener('pause', () => {
        q('[data-tvwb-result-video]')?.pause();
        paintPlayback();
      });
      source.addEventListener('play', paintPlayback);
      source.addEventListener('ended', paintPlayback);
      q('[data-tvwb-result-video]').addEventListener('loadedmetadata', () => {updateCompare(); seek(state.position, {fromVideo: true});});
      document.addEventListener('keydown', event => {if (!root.hidden && event.key === 'Escape') close();});
      if (typeof ResizeObserver === 'function') new ResizeObserver(() => {clampPan(); updateZoom();}).observe(q('[data-tvwb-viewer]'));
      else window.addEventListener('resize', () => {clampPan(); updateZoom();});
    }

    function open(context) {
      ensureRoot(); current = context;
      state.duration = Math.max(0, finite(context.source?.duration));
      state.fps = finite(context.source?.fps) > 0 ? finite(context.source.fps) : 30;
      state.resultStart = Math.max(0, finite(context.result?.startSeconds));
      state.resultTimeScale = Math.max(1, finite(context.result?.timeScale, 1));
      state.exportSelection = false;
      state.zoom = 1; state.panX = 0; state.panY = 0; state.timelineZoom = 1;
      state.mode = context.result?.url ? 'compare' : 'original'; state.tab = 'adjustments';
      state.activeWorkflowPreset = ''; state.sidebarCollapsed = false;
      resetRangeFromContext(); root.hidden = false;
      document.body.classList.add('desk-topaz-video-workbench-open');
      root.classList.remove('is-sidebar-collapsed');
      q('[data-tvwb-export-selection]').checked = false;
      renderPanel(); loadSource(context.source); loadResult(context.result);
      applySourceMetadata({resetRange: true}); setMuted(true); updateZoom(); updateBusy(); updateTimeline(); updateViewMeta();
      q('[data-tvwb-close]').focus();
    }

    function update(id, next) {if (current?.id === id) updateContext(next);}
    function close() {
      if (!root || root.hidden) return;
      pause(); endDrag(); root.hidden = true; document.body.classList.remove('desk-topaz-video-workbench-open');
      state.filmstripToken++; const closing = current; current = null; closing?.onClose?.();
    }
    function dispose(id) {if (!id || current?.id === id) close();}
    return Object.freeze({open, update, close, dispose, artifact});
  }
  window.DesktopTopazVideoWorkbench = Object.freeze({create});
})();
