// Pure WeMM-Video understanding state and connection contract. No DOM or transport.
(function () {
  const TYPE = 'video_understand';
  const WIDTH = 720;
  const HEIGHT = 460;

  const MODES = Object.freeze({
    storyboard: Object.freeze({
      label: '电影拉片 · 分镜反推',
      subtitle: '切镜锚点 + 画面 + 台词',
      fps: 1.5,
      maxFrames: 96,
      totalPixels: 4194304,
      maxTokens: 6144,
      shotAnchors: true,
      promptPlaceholder: '可选补充要求，例如：侧重分析运镜轴线或打光风格…',
      promptRequired: false,
    }),
    prompt_reverse: Object.freeze({
      label: '视频提示词反推',
      subtitle: '画面主体 · 光影 · 运镜提示词',
      fps: 1.0,
      maxFrames: 64,
      totalPixels: 2097152,
      maxTokens: 2048,
      shotAnchors: false,
      promptPlaceholder: '可选目标风格或用途，例如：输出适合 H3 / Wan 的提示词…',
      promptRequired: false,
    }),
    h3_prompt: Object.freeze({
      label: 'H3 提示词反推',
      subtitle: 'MiniMax H3 多模态时间轴 + 声景 + 配乐',
      fps: 2.0,
      maxFrames: 96,
      totalPixels: 4194304,
      maxTokens: 4096,
      shotAnchors: true,
      promptPlaceholder: '可选改写要求，例如：按 I2VA 首帧模式输出 / 按 Ref2VA 六段式 / 替换人物服装…',
      promptRequired: false,
    }),
    summary: Object.freeze({
      label: '音画摘要与台词',
      subtitle: '剧情概览 · 时间线 · 对白记录',
      fps: 1.0,
      maxFrames: 64,
      totalPixels: 2097152,
      maxTokens: 3072,
      shotAnchors: false,
      promptPlaceholder: '可选关注点，例如：重点整理人物对话与情绪转折…',
      promptRequired: false,
    }),
    custom: Object.freeze({
      label: '自定义分析',
      subtitle: '任意音画问答与结构化提取',
      fps: 1.0,
      maxFrames: 64,
      totalPixels: 2097152,
      maxTokens: 2048,
      shotAnchors: false,
      promptPlaceholder: '输入分析问题，或连接上游文本节点传入指令…',
      promptRequired: true,
    }),
  });

  const PIXEL_CHOICES = Object.freeze([
    [1048576, '1M · 轻量'],
    [2097152, '2M · 均衡'],
    [4194304, '4M · 精细'],
    [8388608, '8M · 超精'],
  ]);

  const active = status => ['submitting', 'queued', 'running', 'cancelling'].includes(String(status || ''));

  const clampNum = (value, lo, hi, fallback) => {
    const num = Number(value);
    return Number.isFinite(num) ? Math.max(lo, Math.min(hi, num)) : fallback;
  };

  const clampInt = (value, lo, hi, fallback) => {
    const num = Number(value);
    return Number.isFinite(num) ? Math.max(lo, Math.min(hi, Math.round(num))) : fallback;
  };

  function normalize(node) {
    node.width = WIDTH;
    node.height = HEIGHT;
    const mode = MODES[node.mode] ? node.mode : 'storyboard';
    const defaults = MODES[mode];
    node.mode = mode;
    node.prompt = String(node.prompt || '').slice(0, 8000);
    node.useAudio = node.useAudio !== false;
    node.thinking = node.thinking === true;
    node.shotAnchors = typeof node.shotAnchors === 'boolean' ? node.shotAnchors : Boolean(defaults.shotAnchors);
    node.fps = Math.round(clampNum(node.fps, 0.25, 4.0, defaults.fps) * 100) / 100;
    node.maxFrames = clampInt(node.maxFrames, 4, 128, defaults.maxFrames);
    node.totalPixels = clampInt(node.totalPixels, 262144, 8388608, defaults.totalPixels);
    node.maxTokens = clampInt(node.maxTokens, 128, 8192, defaults.maxTokens);
    node.advancedOpen = node.advancedOpen === true;
    node.jobId = /^[a-f0-9]{32}$/.test(String(node.jobId || '')) ? String(node.jobId) : '';
    node.resultJobId = /^[a-f0-9]{32}$/.test(String(node.resultJobId || '')) ? String(node.resultJobId) : '';
    node.status = String(node.status || 'idle');
    return node;
  }

  function applyModeDefaults(node, nextMode) {
    const mode = MODES[nextMode] ? nextMode : 'storyboard';
    const defaults = MODES[mode];
    node.mode = mode;
    node.fps = defaults.fps;
    node.maxFrames = defaults.maxFrames;
    node.totalPixels = defaults.totalPixels;
    node.maxTokens = defaults.maxTokens;
    node.shotAnchors = defaults.shotAnchors;
    return normalize(node);
  }

  function request(node, videoUrl, connectedPrompt = '') {
    const cleanPrompt = String(connectedPrompt || '').trim() || String(node.prompt || '').trim();
    return {
      video_url: String(videoUrl || '').trim(),
      mode: node.mode,
      prompt: cleanPrompt,
      use_audio: Boolean(node.useAudio),
      thinking: Boolean(node.thinking),
      shot_anchors: Boolean(node.shotAnchors),
      fps: Number(node.fps),
      max_frames: Number(node.maxFrames),
      total_pixels: Number(node.totalPixels),
      max_tokens: Number(node.maxTokens),
    };
  }

  const targets = Object.freeze({
    video: Object.freeze([TYPE]),
    text: Object.freeze([TYPE]),
    [TYPE]: Object.freeze(['text']),
  });

  function policy(from, to, _options = {}, edges = []) {
    if (!from || !to) return null;
    if (from.type === 'video' && to.type === TYPE) {
      return { inputRole: 'video', outputRole: 'video', single: true };
    }
    if (from.type === 'text' && to.type === TYPE) {
      if ((edges || []).some(edge => edge.from === to.id && edge.to === from.id)) {
        return { reject: '该文本节点已是当前视频理解的输出节点，不能回连为输入' };
      }
      return { inputRole: 'prompt', outputRole: 'prompt', single: true };
    }
    if (from.type === TYPE && to.type === 'text') {
      if ((edges || []).some(edge => edge.from === to.id && edge.to === from.id)) {
        return { reject: '该文本节点已是当前视频理解的输入指令，不能回连为输出' };
      }
      return { inputRole: 'text_output', outputRole: 'text', single: false, replaceAllInputs: false };
    }
    return null;
  }

  const labels = Object.freeze({
    idle: '就绪',
    submitting: '提交中',
    queued: '排队中',
    running: '分析中',
    cancelling: '停止中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已停止',
    interrupted: '已中断',
  });

  const stageLabel = stage => ({
    shots: '切镜检测',
    load: '加载模型',
    encode: '编码音画',
    prefill: 'Prefill',
    generate: '生成分析',
    save: '保存结果',
    done: '分析完成',
    '等待本地处理': '等待处理',
    '准备本地处理': '准备处理',
    '等待本地推理资源': '等待资源',
  })[stage] || stage;

  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="14" height="14" rx="2.5"/><path d="m8.5 8.5 5 2.5-5 2.5z"/><path d="M17 10h2.5A1.5 1.5 0 0 1 21 11.5v7a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 9 18.5V18"/></svg>';

  window.DesktopVideoUnderstandModel = Object.freeze({
    TYPE,
    WIDTH,
    HEIGHT,
    MODES,
    PIXEL_CHOICES,
    active,
    normalize,
    applyModeDefaults,
    request,
    targets,
    policy,
    labels,
    stageLabel,
    ICON,
    menu: Object.freeze({
      type: TYPE,
      title: '视频理解',
      subtitle: 'WeMM · 拉片 / 反推',
      icon: ICON,
    }),
  });
})();
