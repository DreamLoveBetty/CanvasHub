// Presentation for the five music-domain nodes. No requests or persisted state here.
(function () {
  function create({ model, escapeHtml: e, stateIcon, progressView }) {
    const runIcons = {
      idle: '<path d="m13.5 2-9 12h6l-1 8 10-13h-7z" fill="currentColor"/>',
      busy: '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" opacity=".25"/><path d="M12 4a8 8 0 0 1 8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
      success: '<path d="m5 12 4 4L19 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
      error: '<path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
      warning: '<path d="M12 4 3 20h18z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 10v4m0 3v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
      stopped: '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/>',
    };
    function paintRunButton(button, state) {
      button.disabled = state.busy;
      button.setAttribute('aria-busy', String(state.busy));
      button.setAttribute('aria-label', state.title);
      button.title = state.title;
      // Retain glyph layers; unchanged polls keep the spinner continuous.
      if (button.dataset.generationIcon !== state.icon) {
        const icon = button.querySelector('svg');
        stateIcon.paint(icon, state.icon);
        button.dataset.generationIcon = state.icon;
      }
      button.dataset.generationState = state.state;
      const label = button.querySelector('[data-music-run-label]');
      if (label) label.textContent = state.label;
    }
    function paintProgress(root, state) {
      const overlay = root.querySelector('[data-music-progress]');
      if (!overlay) return;
      overlay.classList.toggle('is-visible', state.visible);
      overlay.classList.toggle('is-indeterminate', state.percent === null);
      overlay.setAttribute('aria-hidden', String(!state.visible));
      overlay.setAttribute('aria-valuetext', `${state.stage}，已用时 ${state.elapsed}`);
      if (state.percent === null) overlay.removeAttribute('aria-valuenow');
      else overlay.setAttribute('aria-valuenow', String(state.percent));
      overlay.title = state.stage;
      const bar = overlay.querySelector('.desk-progress-float__bar');
      bar.style.setProperty('--progress-percent', `${state.percent ?? 50}%`);
      overlay.querySelector('[data-progress-bar]').style.width = `${state.percent ?? 30}%`;
      overlay.querySelector('[data-progress-percent-value]').textContent = state.value;
      overlay.querySelector('[data-progress-timer]').textContent = state.elapsed;
      overlay.querySelector('[data-progress-stage]').textContent = state.stage;
      progressView?.update(overlay, { visible: state.visible, running: state.visible,
        percent: state.percent, valueLabel: state.value, title: state.stage,
        detail: 'mlx-YuE · 音乐生成', elapsedText: state.elapsed }, root);
    }
    const progress = `<div class="desk-progress-float desk-music__progress" data-music-progress role="progressbar" aria-label="音乐生成进度" aria-valuemin="0" aria-valuemax="100" aria-hidden="true">
      <div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar></span>
      <strong class="desk-progress-float__percent"><span data-progress-percent-value>提交中</span><span class="desk-progress-float__timer" data-progress-timer>00:00</span></strong></div>
      <span class="desk-progress-float__stage" data-progress-stage></span></div></div>`;
    const input = (key, label, value, attrs = '') => `<label>${label}<input data-music-field="${key}" value="${e(value)}" ${attrs}></label>`;
    const select = (key, label, value, items) => `<label>${label}<select data-music-field="${key}">${items.map(([v, t]) => `<option value="${e(v)}" ${String(v) === String(value) ? 'selected' : ''}>${e(t)}</option>`).join('')}</select></label>`;
    const button = (action, label, primary = false) => `<button type="button" data-music-action="${action}" ${primary ? 'class="desk-music__primary"' : ''}>${label}</button>`;
    const artifacts = `<div class="desk-music__artifacts" data-music-artifacts></div>`;
    const errorNotice = `<p class="desk-music__error" data-music-error role="alert" hidden></p>`;
    const tabs = (items, active) => `<nav class="desk-music__tabs" aria-label="节点视图">${items.map(([key, label]) => `<button type="button" data-music-tab="${key}" aria-pressed="${key === active}">${label}</button>`).join('')}</nav>`;
    function generation(n) {
      return `<div class="desk-music__generation-content">
        <div class="desk-music__grid desk-music__generation-params">${select('operation', '任务', n.operation, [['generate', '生成歌曲'], ['plan', '只生成乐谱']])}${select('cot', '生成模式', n.cot, [['full', 'full · 旋律 + 和弦'], ['melody', 'melody · 旋律'], ['off', 'off · 直接生成']])}
        ${select('precision', 'AR 精度', n.precision, [['8bit', '8bit · 推荐'], ['bf16', 'bf16']])}${select('odeSteps', 'ODE 步数', n.odeSteps, [[8, '极速 · 8 步'], [32, '标准 · 32 步'], ...(![8, 32].includes(n.odeSteps) ? [[n.odeSteps, `${n.odeSteps} 步`]] : [])])}
        ${input('cfgScale', 'CFG（留空用默认）', n.cfgScale, 'type="number" min="0" max="20" step="0.01" placeholder="模型默认" title="full/melody: 1.0；off: 1.01"')}${input('seed', '种子（−1 随机）', n.seed, 'type="number" min="-1" max="9007199254740991" step="1"')}${input('odeSteps', '自定义 ODE 步数', n.odeSteps, 'type="number" min="1" max="128" step="1"')}${input('songId', '任务标识', n.songId || 'song', 'maxlength="180"')}</div>
        <section class="desk-music__generation-inputs"><h4>输入参考</h4>
        <div class="desk-music__generation-reference-row"><div class="desk-music__connections" data-music-inputs>接入风格、歌词两个文本节点；ABC 可选</div><div class="desk-music__generation-format">${select('audioFormat', '生成格式', n.audioFormat, [['flac', 'FLAC'], ['wav', 'WAV']])}</div></div>
        <p class="desk-music__muted">音频参考：音频节点 → 音频转谱 → 本节点（ABC）</p></section>
        </div>
        <div class="desk-music__generation-footer">
        <div class="desk-music__actions"><button type="button" class="desk-music__primary desk-music__generate desk-generation-action" data-music-action="run" aria-label="开始生成" title="开始生成音乐或乐谱">${stateIcon.html(runIcons)}<span class="desk-generation-action__label" data-music-run-label>开始生成</span></button></div></div>`;
    }
    function transcribe(n) {
      return `<div class="desk-music__connections" data-music-inputs>连接一个音频素材节点</div>
        ${select('transcribeTask', '转谱内容', n.transcribeTask, [['full', 'full · 旋律 + 和弦'], ['melody-full', 'melody-full · 完整旋律'], ['melody-vocal', 'melody-vocal · 人声旋律']])}
        <div class="desk-music__grid">${select('preset', '窗口预设', n.preset, [['default', 'default'], ['paper', 'paper']])}${input('maxSeconds', '最多处理（秒）', n.maxSeconds, 'type="number" min="1" max="1800"')}</div>
        <p class="desk-music__muted">人声旋律是转谱目标，不会分离或输出人声音轨。</p>
        <div class="desk-music__formats"><span>ABC</span><span>MIDI</span><span>LAB</span><span>JSON</span></div>
        <div class="desk-music__actions" data-music-standalone-actions>${button('run', '开始转谱', true)}</div>
        <p class="desk-music__muted" data-music-chain-hint hidden>由下游音乐生成自动执行转谱</p>${artifacts}`;
    }
    function editor(n) {
      return `${tabs([['edit', '编辑'], ['check', '校验'], ['tools', '工具']], n.tab)}
        <div class="desk-music__connections" data-music-inputs>ABC 素材 / 生成乐谱</div>
        <div class="desk-music__editor"><pre data-music-lines aria-hidden="true">1</pre><textarea data-music-field="abc" spellcheck="false" aria-label="ABC 乐谱文本" maxlength="131072">${e(n.abc)}</textarea></div>
        <div class="desk-music__actions">${button('validate', '校验 YuE 方言')}${button('import-abc', '导入 ABC')}${button('export-abc', '下载 ABC')}</div>
        <div data-music-tools ${n.tab !== 'tools' ? 'hidden' : ''} class="desk-music__actions">${button('template', '插入示例')}${button('strip-chords', '移除和弦')}</div>
        <input type="file" data-music-abc-file accept=".abc,.txt" hidden><p class="desk-music__notice" data-music-validation>未校验 · 编辑后需重新校验</p>`;
    }
    function score(n) {
      return `${tabs([['staff', '五线谱'], ['abc', 'ABC'], ['midi', 'MIDI']], ['staff', 'abc', 'midi'].includes(n.tab) ? n.tab : 'staff')}
        <div class="desk-music__connections" data-music-inputs>连接 ABC 编辑、音乐生成或转谱节点</div>
        <div class="desk-music__score-title">${input('scoreTitle', '标题', n.scoreTitle, 'type="text" maxlength="120" placeholder="留空沿用原谱标题" autocomplete="off"')}</div>
        <div class="desk-music__score-tools">${select('voice', '声部', n.voice, [['all', '全部'], ['Vocal', 'Vocal'], ['Ins', 'Ins']])}<span data-music-score-meta>调号 / 拍号 / 速度</span>${button('zoom-out', '−')}${button('zoom-in', '+')}</div>
        <div class="desk-music__paper" data-music-staff></div><pre class="desk-music__source" data-music-score-source hidden></pre>
        <p data-music-midi-info hidden>将当前 ABC 导出为 MIDI。通用 MIDI 文件导入暂未接入。</p>
        <div class="desk-music__actions">${button('export-png', 'PNG')}${button('export-svg', 'SVG')}${button('export-pdf', '打印 / PDF')}${button('export-midi', 'MIDI')}${button('export-abc', 'ABC')}</div>`;
    }
    function compare(n) {
      return `${tabs([['audio', '音频对比'], ['score', '乐谱对比'], ['params', '参数对比']], n.tab)}
        <div class="desk-music__connections" data-music-inputs>连接两份或更多音频 / 音乐结果</div>
        <div class="desk-music__compare" data-music-compare></div>
        <div class="desk-music__actions"><label class="desk-music__check"><input type="checkbox" data-music-field="syncPlayback" ${n.syncPlayback ? 'checked' : ''}>同步播放</label>${button('play-compare', '播放 A / B')}${button('stop-compare', '停止')}${button('refresh-compare', '刷新')}</div>
        <label>添加对比项<select data-music-add-source><option value="">选择画布中的音频或乐谱…</option></select></label>`;
    }
    function nodeHtml(n) {
      model.normalizeState(n); const def = model.definitions[n.type], id = e(n.id);
      const body = ({ music_generate: generation, music_transcribe: transcribe, music_abc: editor, music_score: score, music_compare: compare })[n.type](n);
      return `<section class="desk-node desk-node--music" data-node-id="${id}" data-music-kind="${e(n.type)}" data-i18n-skip>
        <header class="desk-music__header" data-node-drag-handle><span class="desk-music__icon">${model.ICON}</span><div><strong>${def.title}</strong><small>${def.kind}</small></div><span class="desk-status-pill" data-music-status>就绪</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除${def.title}">删</button></header>
        <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${id}" aria-label="${def.title}输入端点"></button>
        ${n.type === 'music_compare' ? '' : `<button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${id}" aria-label="${def.title}输出端点"></button>`}
        <div class="desk-music__body" data-node-drag-ignore>${body}${['music_generate', 'music_transcribe'].includes(n.type) ? '' : errorNotice}</div>${n.type === 'music_generate' ? progress : ''}</section>`;
    }
    return Object.freeze({ nodeHtml, paintRunButton, paintProgress });
  }
  window.DesktopMusicView = Object.freeze({ create });
})();
