// Music graph/data contract; pure functions, no DOM, model loading or image state.
(function () {
  const ICON = '<svg viewBox="0 0 24 24" class="desk-node-icon" aria-hidden="true"><path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/></svg>';
  const definitions = {
    music_generate: { title: 'mlx-Yue 音乐生成', subtitle: '风格 + 歌词 → 歌曲', width: 720, height: 460, kind: 'MODEL' },
    music_transcribe: { title: '音频转谱', subtitle: '音频 → ABC / MIDI', width: 380, height: 460, kind: 'TRANSCRIBE' },
    music_abc: { title: 'ABC 乐谱编辑', subtitle: '编辑 · 校验 · 整理', width: 510, height: 560, kind: 'ABC' },
    music_score: { title: '乐谱可视化', subtitle: '五线谱与导出', width: 700, height: 615, kind: 'SCORE' },
    music_compare: { title: '结果对比', subtitle: '音频 · 乐谱 · 参数', width: 650, height: 525, kind: 'COMPARE' },
  };
  const TYPES = Object.keys(definitions);
  const TARGETS = Object.freeze({
    text: ['music_generate'], audio: ['music_transcribe', 'music_compare'],
    music_generate: ['audio', 'music_abc', 'music_score', 'music_compare'],
    music_transcribe: ['music_abc', 'music_score', 'music_generate', 'music_compare'],
    music_abc: ['music_generate', 'music_score', 'music_compare'],
    music_score: ['music_compare'], music_compare: [],
  });
  const DEFAULT_ABC = 'X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=90\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nV: Ins clef=treble name="Ins Melody" snm="Inst."\nK:C\n% verse\nV: Vocal\n"C"C8 D8 E8 G8 |\nV: Ins\nZ |\n';
  const active = status => ['queued', 'running', 'cancelling'].includes(status);
  const normalizeScoreTitle = value => typeof value === 'string'
    ? value.replace(/[\u0000-\u001f\u007f\u2028\u2029]/g, ' ').slice(0, 120) : '';
  // A score-node title is a local metadata override, never a source-score edit.
  function scoreAbc(abc, title) {
    const heading = normalizeScoreTitle(title).trim();
    if (!heading || !abc.trim()) return abc;
    const newline = abc.includes('\r\n') ? '\r\n' : '\n';
    const tune = /^X:[^\r\n]*(?:\r?\n|$)/m.exec(abc);
    const start = tune ? tune.index + tune[0].length : 0;
    const boundary = /^[KX]:/m.exec(abc.slice(start));
    const end = boundary ? start + boundary.index : abc.length;
    // Replace only first-tune header titles (including +: continuations).
    // Body T: sections and subsequent tunes are left byte-for-byte intact.
    const header = abc.slice(start, end).replace(/^T:[^\r\n]*(?:\r?\n|$)(?:^\+:[^\r\n]*(?:\r?\n|$))*/gm, '');
    const escaped = heading.replace(/\\/g, '\\\\').replace(/%/g, '\\%');
    const prefix = abc.slice(0, start);
    return prefix + (prefix && !prefix.endsWith('\n') ? newline : '')
      + `T:${escaped}${newline}` + header + abc.slice(end);
  }
  function normalizeState(node) {
    const def = definitions[node.type]; if (!def) return node;
    node.width = def.width; node.height = def.height;
    // Preserve legacy inline content in old snapshots, but never use it as a hidden input.
    node.style = String(node.style || '').slice(0, 8192); node.lyrics = String(node.lyrics || '').slice(0, 32768);
    node.abc = String(node.abc || '').slice(0, 131072); node.resultAbc = String(node.resultAbc || '').slice(0, 131072);
    node.cot = ['full', 'melody', 'off'].includes(node.cot) ? node.cot : 'full';
    node.operation = node.operation === 'plan' ? 'plan' : 'generate';
    node.precision = node.precision === 'bf16' ? 'bf16' : '8bit';
    node.audioFormat = node.audioFormat === 'wav' ? 'wav' : 'flac';
    node.seed = Number.isSafeInteger(node.seed) && node.seed >= -1 ? node.seed : 831001;
    node.cfgScale = node.cfgScale == null || node.cfgScale === '' ? '' : Number(node.cfgScale);
    node.odeSteps = Number.isInteger(node.odeSteps) && node.odeSteps > 0 && node.odeSteps <= 128 ? node.odeSteps : 32;
    // Keep legacy overrides in snapshots only; new canvas requests use native sampling defaults.
    node.abcSampling = String(node.abcSampling || '{}').slice(0, 8192);
    node.semanticSampling = String(node.semanticSampling || '{}').slice(0, 8192);
    node.transcribeTask = ['full', 'melody-full', 'melody-vocal'].includes(node.transcribeTask) ? node.transcribeTask : 'full';
    node.preset = node.preset === 'paper' ? 'paper' : 'default';
    node.maxSeconds = Number(node.maxSeconds) > 0 && Number(node.maxSeconds) <= 1800 ? Number(node.maxSeconds) : 300;
    node.jobId = /^[a-f0-9]{32}$/.test(String(node.jobId || '')) ? node.jobId : '';
    node.resultJobId = /^[a-f0-9]{32}$/.test(String(node.resultJobId || '')) ? node.resultJobId : '';
    node.status = String(node.status || 'idle'); node.syncPlayback = node.syncPlayback !== false;
    node.tab = String(node.tab || (node.type === 'music_compare' ? 'audio' : 'edit'));
    node.voice = ['Vocal', 'Ins'].includes(node.voice) ? node.voice : 'all';
    node.scoreScale = Math.max(.5, Math.min(2, Number(node.scoreScale) || 1));
    if (node.type === 'music_score') node.scoreTitle = normalizeScoreTitle(node.scoreTitle);
    return node;
  }
  function createState(id, type, position) { return normalizeState({ id, type, ...position }); }
  function policy(from, to, options = {}, edges = []) {
    if (!TARGETS[from?.type]?.includes(to?.type)) return null;
    let inputRole = 'score';
    if (to.type === 'music_compare') inputRole = 'comparison';
    else if (from.type === 'text') inputRole = ['style', 'lyrics'].includes(options.inputRole) ? options.inputRole
      : edges.some(e => e.to === to.id && e.inputRole === 'lyrics' && e.from !== from.id) ? 'style' : 'lyrics';
    else if (from.type === 'audio' || to.type === 'audio') inputRole = 'audio';
    return { inputRole, outputRole: inputRole === 'audio' ? 'audio' : from.type === 'text' ? 'text' : 'score', single: to.type !== 'music_compare' };
  }
  function generationRequest(node, inputs = {}) {
    const style = typeof inputs.style === 'string' ? inputs.style : '';
    const lyrics = typeof inputs.lyrics === 'string' ? inputs.lyrics : '';
    const missing = [[style, '音乐风格'], [lyrics, '歌词']].filter(([value]) => !value.trim()).map(([, label]) => label);
    if (missing.length) throw new Error(`请接入并填写${missing.join('、')}文本节点`);
    // Omit sampling overrides: YuE's GenerationConfig owns both defaults, not the UI.
    const request = { style, lyrics, cot: node.cot,
      seed: node.seed, id: 'song', generation_config: { ode_steps: node.odeSteps } };
    if (node.cfgScale !== '') request.cfg_scale = Number(node.cfgScale);
    if (inputs.abc) request.abc = inputs.abc;
    if (request.cot === 'off' && request.abc) throw new Error('off 模式不接受 ABC，请断开乐谱连线或切换模式');
    return { operation: node.operation, precision: node.precision,
      ...(node.operation === 'generate' ? { audio_format: node.audioFormat === 'wav' ? 'wav' : 'flac' } : {}), request };
  }
  // Always use the completed job's format, not controls edited while it was running.
  function audioArtifact(files = [], spec = {}) {
    const format = spec?.audio_format || 'flac';
    return (files || []).find(f => f.kind === 'audio' && f.name.endsWith(`/audio.${format}`))
      || (!spec?.audio_format ? (files || []).find(f => f.kind === 'audio') : undefined);
  }
  // Derived presentation only. Actual job state stays in the music controller;
  // pre-submit failures/cancellation are transient and do not rewrite old results.
  function generationButtonState(node, { submitting = false, cancelRequested = false, phase = '', outcome = '' } = {}) {
    const state = cancelRequested ? 'cancelling' : submitting ? (phase ? 'waiting' : 'submitting')
      : active(node.status) ? node.status : outcome || node.status || 'idle';
    const states = {
      idle: ['开始生成', 'idle', false, '开始生成音乐或乐谱'],
      submitting: ['提交中', 'busy', true, '正在提交音乐任务'],
      waiting: ['等待转谱', 'busy', true, phase || '等待上游转谱'],
      queued: ['排队中', 'busy', true, '音乐任务排队中'],
      running: ['生成中', 'busy', true, '正在生成音乐或乐谱'],
      cancelling: ['停止中', 'busy', true, '正在停止任务'],
      succeeded: ['已完成', 'success', false, '生成已完成，点击重新生成'],
      partial: ['结果截断', 'warning', false, '结果截断，点击重新生成'],
      failed: ['重试生成', 'error', false, '生成失败，点击重试'],
      interrupted: ['重试生成', 'error', false, '任务已中断，点击重试'],
      cancelled: ['已停止', 'stopped', false, '任务已停止，点击重新生成'],
    };
    const resolved = Object.hasOwn(states, state) ? state : 'idle';
    const [label, icon, busy, title] = states[resolved];
    return { state: resolved, label, icon, busy, title };
  }
  function generationProgress(node, job, button, { now = Date.now(), submittedAt = 0 } = {}) {
    const matches = Boolean(job && job.id === node.jobId);
    const pending = ['submitting', 'waiting'].includes(button.state);
    const observation = !pending && matches ? job.progress || {} : {};
    const stages = { 'Resolving model files': '检查模型', 'Verifying model files': '校验模型',
      'Using provided score': '读取参考乐谱', 'Planning score': '规划乐谱', 'Generating song': '生成音乐语义',
      'Synthesizing audio': '声学合成', 'Loading MLX audio decoder': '加载音频解码器', 'Decoding audio': '解码音频' };
    const rawStage = String(!pending && matches ? job.stage || '' : '');
    const phase = stages[rawStage] || (/^Loading .* model$/.test(rawStage) ? '加载音乐模型' : rawStage);
    let stage = button.state === 'running' ? phase || '音乐推理中' : button.title;
    let value = button.label;
    let percent = null;
    if (button.state === 'running') {
      const { completed, total, unit } = observation;
      if (Number.isSafeInteger(completed) && Number.isSafeInteger(total) && completed >= 0 && total > 0 && completed <= total) {
        percent = Math.round(completed / total * 100);
        value = `阶段 ${percent}%`;
        stage += ` · ${completed}/${total} ${unit === 'steps' ? '步' : unit === 'chunks' ? '块' : '项'}（当前阶段）`;
      } else if (Number.isSafeInteger(observation.tokens) && observation.tokens >= 0) {
        stage += ` · 已生成 ${observation.tokens} tokens`;
      }
    }
    const time = Number(matches && !pending ? job.started_at || job.created_at : 0) * 1000 || submittedAt;
    const seconds = time > 0 && Number.isFinite(time) ? Math.max(0, Math.floor((now - time) / 1000)) : 0;
    const elapsed = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    return { visible: button.busy, percent, value, stage, elapsed };
  }
  // Presentation adapter only. Audio receipts never enter the image output store.
  function taskFeedback(node, job, button, { pending = false, error = '', publishing = false } = {}) {
    const receipt = !pending && job?.id === node.jobId ? job : null;
    const operation = node.type === 'music_transcribe' ? '音频转谱'
      : (receipt?.spec?.operation || node.operation) === 'plan' ? '乐谱生成' : '音乐生成';
    const state = button.state;
    const stages = { idle: '就绪', submitting: '正在提交', waiting: '等待上游转谱', queued: '排队中',
      running: generationProgress(node, receipt, button).stage, cancelling: '正在停止',
      succeeded: '已完成', partial: '结果截断，已保留部分结果', failed: '生成失败，点击查看详情',
      interrupted: '任务已中断，点击查看详情', cancelled: '已停止' };
    const summary = error ? (publishing ? '结果接入失败，点击查看详情' : '操作失败，点击查看详情')
      : publishing ? '正在接入生成结果' : stages[state] || button.label;
    const tone = error || ['failed', 'interrupted'].includes(state) ? 'error'
      : state === 'partial' ? 'warning' : state === 'succeeded' && !publishing ? 'success' : 'info';
    const status = error ? 'failed' : publishing ? 'processing' : ({ running: 'processing', submitting: 'preparing',
      waiting: 'preparing', cancelling: 'processing', cancelled: 'canceled', interrupted: 'failed', partial: 'succeeded' })[state] || state;
    const elapsed = receipt?.finished_at && receipt?.started_at
      ? Math.max(0, Math.round(receipt.finished_at - receipt.started_at)) : 0;
    const raw = { operation, status: error ? 'operation_failed' : state,
      ...(receipt?.stage ? { stage: receipt.stage } : {}),
      ...(receipt?.progress ? { progress: receipt.progress } : {}) };
    return { message: `${operation} · ${summary}`, tone, task: {
      task_id: receipt?.id || '', node_id: node.id,
      node_title: `${node.alias || definitions[node.type]?.title || operation} · ${node.id.slice(-6)}`,
      operation_label: operation, status, status_label: error ? '操作失败' : ({ failed: '失败', interrupted: '已中断', partial: '结果截断' })[state] || button.label,
      detail_title: `${operation}${tone === 'error' ? '失败详情' : '日志'}`,
      provider_route: 'mlx_yue', stage: summary, progress_text: `${operation} · ${summary}`,
      raw_detail: JSON.stringify(raw, null, 2) + (error || receipt?.error ? `\n\n${error || receipt.error}` : ''),
      elapsed_text: elapsed ? `${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒` : '',
    } };
  }
  window.DesktopMusicModel = Object.freeze({ definitions, TYPES, TARGETS, DEFAULT_ABC, active, normalizeState, normalizeScoreTitle, scoreAbc, createState, policy, generationRequest, audioArtifact, generationButtonState, generationProgress, taskFeedback,
    MENU_ITEMS: TYPES.map(type => Object.freeze({ type, title: definitions[type].title, subtitle: definitions[type].subtitle, icon: ICON })), ICON });
})();
