// Independent EasyColab MiniMax-H3 canvas nodes. Prompt and media come from canvas connections only.
(function () {
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const terminal = s => ['succeeded', 'succeeded_no_telegram', 'failed', 'telegram_failed', 'canceled'].includes(s);

  const FALLBACK_FRAME_PRESETS = [
    { value: 56, label: '56 帧 · ~2.3 秒' },
    { value: 73, label: '73 帧 · ~3.0 秒' },
    { value: 90, label: '90 帧 · ~3.8 秒 (4s)' },
    { value: 124, label: '124 帧 · ~5.2 秒 (5s)' },
    { value: 192, label: '192 帧 · ~8.0 秒 (8s)' },
    { value: 243, label: '243 帧 · ~10.1 秒 (10s)' },
    { value: 294, label: '294 帧 · ~12.3 秒 (12s)' },
    { value: 362, label: '362 帧 · ~15.1 秒 (15s)' }
  ];

  const FALLBACK_VIDEO_SIZES = [
    { value: '1056x608', label: '1056×608 · 16:9 H3 黄金画幅', width: 1056, height: 608 },
    { value: '832x480', label: '832×480 · 16:9 横屏标准', width: 832, height: 480 },
    { value: '1280x720', label: '1280×720 · 16:9 720P 高清', width: 1280, height: 720 },
    { value: '1344x768', label: '1344×768 · 16:9 电影宽屏', width: 1344, height: 768 },
    { value: '480x832', label: '480×832 · 9:16 竖屏标准', width: 480, height: 832 },
    { value: '608x1056', label: '608×1056 · 9:16 H3 竖屏', width: 608, height: 1056 },
    { value: '720x1280', label: '720×1280 · 9:16 720P 竖屏', width: 720, height: 1280 },
    { value: '640x640', label: '640×640 · 1:1 方形', width: 640, height: 640 }
  ];

  const FALLBACK_IMAGE_SIZES = [
    { value: '2048x2048', label: '2048×2048 · 1:1 4MP 超清推荐', width: 2048, height: 2048 },
    { value: '4096x4096', label: '4096×4096 · 1:1 16MP 原生 4K', width: 4096, height: 4096 },
    { value: '5472x3072', label: '5472×3072 · 16:9 16MP 电影 4K', width: 5472, height: 3072 },
    { value: '3072x5472', label: '3072×5472 · 9:16 16MP 竖版 4K', width: 3072, height: 5472 },
    { value: '4736x3552', label: '4736×3552 · 4:3 16MP 商业 4K', width: 4736, height: 3552 },
    { value: '3552x4736', label: '3552×4736 · 3:4 16MP 人像 4K', width: 3552, height: 4736 },
    { value: '1344x768', label: '1344×768 · 16:9 快速预览', width: 1344, height: 768 },
    { value: '1024x1024', label: '1024×1024 · 1:1 快速预览', width: 1024, height: 1024 }
  ];

  const FALLBACK_MODELS = {
    video: [
      {
        id: 'minimax_h3_10eros_max',
        kind: 'video',
        label: '10Eros-Max (H3 无限制 · 8 步)',
        short_label: '10Eros-Max',
        default_mode: 'multiref',
        modes: [
          { id: 'multiref', label: '多图 + 声纹参考', max_images: 9, max_audios: 1, requires_media: true },
          { id: 'fl2va', label: '首尾帧生视频', max_images: 2, max_audios: 0, requires_media: true },
          { id: 't2va', label: '文生音视频', max_images: 0, max_audios: 0, requires_media: false }
        ],
        defaults: { width: 1056, height: 608, num_frames: 124, num_inference_steps: 8, fps: 24, ref_image_size: 'match', seed: -1, batch_count: 1 },
        steps_range: { min: 4, max: 20, step: 1, fixed: false },
        supports_audio_ref: true,
        supports_ref_image_size: true,
        supports_corrector: false,
        supports_negative: true,
        supports_soundscape: true,
        size_presets: FALLBACK_VIDEO_SIZES,
        frame_presets: FALLBACK_FRAME_PRESETS
      },
      {
        id: 'minimax_h3_sulphur3',
        kind: 'video',
        label: 'Sulphur-3 (H3 无限制 · 修正器)',
        short_label: 'Sulphur-3',
        default_mode: 't2va',
        modes: [
          { id: 't2va', label: '文生有声视频', max_images: 0, max_audios: 0, requires_media: false },
          { id: 'fl2va', label: '首尾帧生视频', max_images: 2, max_audios: 0, requires_media: true }
        ],
        defaults: {
          width: 1056, height: 608, num_frames: 124, num_inference_steps: 20, fps: 24,
          corrector_enabled: true, corrector_strength: 1.0, corrector_budget_fraction: 0.5,
          corrector_start_step: 0, corrector_end_step: -1, seed: -1, batch_count: 1
        },
        steps_range: { min: 8, max: 40, step: 1, fixed: false },
        supports_audio_ref: false,
        supports_ref_image_size: false,
        supports_corrector: true,
        supports_negative: true,
        supports_soundscape: true,
        size_presets: FALLBACK_VIDEO_SIZES,
        frame_presets: FALLBACK_FRAME_PRESETS
      },
      {
        id: 'minimax_h3',
        kind: 'video',
        label: 'MiniMax-H3 (33B BF16 原生)',
        short_label: 'MiniMax-H3',
        default_mode: 't2va',
        modes: [
          { id: 't2va', label: '文生音视频', max_images: 0, max_audios: 0, requires_media: false },
          { id: 'fl2va', label: '首尾帧生视频', max_images: 2, max_audios: 0, requires_media: true }
        ],
        defaults: { width: 832, height: 480, num_frames: 124, num_inference_steps: 35, fps: 24, seed: -1, batch_count: 1 },
        steps_range: { min: 10, max: 60, step: 1, fixed: false },
        supports_audio_ref: false,
        supports_ref_image_size: false,
        supports_corrector: false,
        supports_negative: true,
        supports_soundscape: true,
        size_presets: FALLBACK_VIDEO_SIZES,
        frame_presets: FALLBACK_FRAME_PRESETS
      }
    ],
    image: [
      {
        id: 'minimax_h3_image',
        kind: 'image',
        label: 'MiniMax-H3-Image (33B · 4K)',
        short_label: 'H3-Image 4K',
        default_mode: 't2i',
        modes: [
          { id: 't2i', label: '6 步原生 4K 文生图', max_images: 0, max_audios: 0, requires_media: false },
          { id: 'i2i_edit', label: '多参考图指令修图', max_images: 2, max_audios: 0, requires_media: true }
        ],
        defaults: { width: 2048, height: 2048, num_inference_steps: 6, seed: -1, batch_count: 1 },
        steps_range: { min: 6, max: 6, step: 1, fixed: true },
        supports_audio_ref: false,
        supports_ref_image_size: false,
        supports_corrector: false,
        supports_negative: false,
        supports_soundscape: false,
        size_presets: FALLBACK_IMAGE_SIZES,
        frame_presets: []
      }
    ]
  };

  function create({
    model: M,
    api,
    progressView,
    getCanvas,
    getNodeState,
    getNodeElement,
    getImageReferences,
    getTextNodes,
    getNegativeTextNodes,
    materializeText,
    audioAssets,
    addNode,
    connectNodes,
    setImageFromResult,
    refreshVideoNode,
    updateLinkPath,
    saveState,
    reportStatus
  }) {
    const sessions = new Map();
    let catalog = null;
    let catalogPromise = null;
    let catalogError = '';

    const catalogBuckets = () => catalog?.models || FALLBACK_MODELS;
    const allChoices = () => {
      const buckets = catalogBuckets();
      return [...(buckets.video || []), ...(buckets.image || [])];
    };
    const selected = node => allChoices().find(item => item.id === node.modelId) || allChoices()[0] || null;
    const activeKind = node => {
      const item = selected(node);
      if (item?.kind) return item.kind;
      return M.modelKind ? M.modelKind(node) : (node.type === 'easycolab_h3_video' ? 'video' : 'image');
    };
    const live = s => sessions.get(s.id) === s && getNodeState(s.id) === s.node && getNodeElement(s.id) === s.el;

    function modeFor(node, item) {
      if (!item) return null;
      const saved = String(node.parameters?.task_mode || item.default_mode || '');
      return (item.modes || []).find(m => m.id === saved) || (item.modes || [])[0] || null;
    }

    function sizeValueFor(node, item) {
      if (node.parameters?.custom_size) return 'custom';
      const defaults = item?.defaults || {};
      const width = Number(node.parameters?.width || defaults.width || 1056);
      const height = Number(node.parameters?.height || defaults.height || 608);
      const key = `${width}x${height}`;
      const presets = item?.size_presets || [];
      if (presets.some(p => p.value === key)) return key;
      return node.parameters?.width && node.parameters?.height ? 'custom' : (presets[0]?.value || key);
    }

    function paramValue(node, item, name) {
      const stored = node.parameters?.[name];
      if (stored !== undefined && stored !== '') return stored;
      return item?.defaults?.[name];
    }

    function modelOptions(node) {
      const buckets = catalogBuckets();
      const videos = buckets.video || [];
      const images = buckets.image || [];
      const renderGroup = (label, list) => !list.length ? '' : `<optgroup label="${esc(label)}">${
        list.map(item => `<option value="${esc(item.id)}"${item.id === node.modelId ? ' selected' : ''}>${esc(item.label)}</option>`).join('')
      }</optgroup>`;
      return renderGroup('音视频模型 (Video + Audio)', videos) + renderGroup('4K 图像模型 (Image)', images);
    }

    function fieldsHtml(node) {
      const item = selected(node);
      if (!item) return '';
      const mode = modeFor(node, item);
      const video = item.kind === 'video';
      const blocks = [];

      blocks.push(
        `<label><span>任务模式</span><select class="desk-select" data-easycolab-h3-field="task_mode">${
          (item.modes || []).map(m => `<option value="${esc(m.id)}"${m.id === mode?.id ? ' selected' : ''}>${esc(m.label)}</option>`).join('')
        }</select></label>`
      );

      const currentSize = sizeValueFor(node, item);
      blocks.push(
        `<label><span>分辨率预设</span><select class="desk-select" data-easycolab-h3-field="size">${
          (item.size_presets || []).map(p => `<option value="${esc(p.value)}"${p.value === currentSize ? ' selected' : ''}>${esc(p.label)}</option>`).join('')
        }<option value="custom"${currentSize === 'custom' ? ' selected' : ''}>自定义宽高 (32 倍数)</option></select></label>`
      );

      if (currentSize === 'custom') {
        const w = Number(paramValue(node, item, 'width') || item.defaults.width);
        const h = Number(paramValue(node, item, 'height') || item.defaults.height);
        const maxDim = video ? 1920 : 5472;
        const minDim = video ? 256 : 512;
        blocks.push(
          `<label><span>宽度 (${minDim}~${maxDim})</span><input type="number" min="${minDim}" max="${maxDim}" step="32" data-easycolab-h3-field="width" value="${esc(w)}"></label>`
        );
        blocks.push(
          `<label><span>高度 (${minDim}~${maxDim})</span><input type="number" min="${minDim}" max="${maxDim}" step="32" data-easycolab-h3-field="height" value="${esc(h)}"></label>`
        );
      }

      if (video) {
        const frames = M.snapFrames(paramValue(node, item, 'num_frames'));
        const fps = Number(paramValue(node, item, 'fps') ?? item.defaults.fps ?? 24);
        const stepsCfg = item.steps_range || { min: 4, max: 60, step: 1 };
        const steps = Number(paramValue(node, item, 'num_inference_steps') ?? item.defaults.num_inference_steps);
        blocks.push(
          `<label><span>视频总帧数 (17k+5)</span><select class="desk-select" data-easycolab-h3-field="num_frames">${
            (item.frame_presets || FALLBACK_FRAME_PRESETS).map(p => `<option value="${esc(p.value)}"${Number(p.value) === frames ? ' selected' : ''}>${esc(p.label)}</option>`).join('')
          }</select></label>`
        );
        blocks.push(
          `<label><span>采样步数 (${stepsCfg.min}~${stepsCfg.max})</span><input type="number" min="${stepsCfg.min}" max="${stepsCfg.max}" step="${stepsCfg.step || 1}" data-easycolab-h3-field="num_inference_steps" value="${esc(steps)}"></label>`
        );
        blocks.push(
          `<label><span>帧率 (FPS)</span><input type="number" min="12" max="60" step="1" data-easycolab-h3-field="fps" value="${esc(fps)}"></label>`
        );
      } else {
        blocks.push(
          `<label><span>采样步数</span><span class="desk-easycolab-h3__readonly">6 步 · PDD 蒸馏固定</span></label>`
        );
      }

      if (item.supports_ref_image_size && mode?.id === 'multiref') {
        const refSize = String(paramValue(node, item, 'ref_image_size') || 'match');
        blocks.push(
          `<label><span>参考图缩放</span><select class="desk-select" data-easycolab-h3-field="ref_image_size">${
            [
              { value: 'match', label: 'match · 原图适配' },
              { value: 'max', label: 'max · 2048 高精面部' }
            ].map(o => `<option value="${o.value}"${o.value === refSize ? ' selected' : ''}>${o.label}</option>`).join('')
          }</select></label>`
        );
      }

      const seed = Number(paramValue(node, item, 'seed') ?? -1);
      const batch = Number(paramValue(node, item, 'batch_count') ?? 1);
      blocks.push(
        `<label><span>随机种子 (-1 随机)</span><input type="number" min="-1" max="2147483647" step="1" data-easycolab-h3-field="seed" value="${esc(seed)}"></label>`
      );
      blocks.push(
        `<label><span>批量连抽</span><select class="desk-select" data-easycolab-h3-field="batch_count">${
          [1, 2, 3, 4].map(n => `<option value="${n}"${n === batch ? ' selected' : ''}>${n} ${video ? '条' : '张'}</option>`).join('')
        }</select></label>`
      );

      if (item.supports_corrector) {
        const corrEnabled = paramValue(node, item, 'corrector_enabled') !== false;
        const corrStrength = Number(paramValue(node, item, 'corrector_strength') ?? 1.0);
        const corrBudget = Number(paramValue(node, item, 'corrector_budget_fraction') ?? 0.5);
        const corrStart = Number(paramValue(node, item, 'corrector_start_step') ?? 0);
        const corrEnd = Number(paramValue(node, item, 'corrector_end_step') ?? -1);
        blocks.push(
          `<div class="desk-easycolab-h3__corrector">
            <div class="desk-easycolab-h3__corrector-head">
              <label class="desk-easycolab-h3__check"><input type="checkbox" data-easycolab-h3-field="corrector_enabled" ${corrEnabled ? 'checked' : ''}><span>启用 s3_corrector 速度残差修正器</span></label>
            </div>
            ${corrEnabled ? `<div class="desk-easycolab-h3__corrector-grid">
              <label><span>修正强度 (0~1.5)</span><input type="number" min="0" max="1.5" step="0.05" data-easycolab-h3-field="corrector_strength" value="${esc(corrStrength)}"></label>
              <label><span>预算比例 (0~1)</span><input type="number" min="0" max="1" step="0.05" data-easycolab-h3-field="corrector_budget_fraction" value="${esc(corrBudget)}"></label>
              <label><span>起始步数</span><input type="number" min="0" max="40" step="1" data-easycolab-h3-field="corrector_start_step" value="${esc(corrStart)}"></label>
              <label><span>结束步 (-1 全程)</span><input type="number" min="-1" max="40" step="1" data-easycolab-h3-field="corrector_end_step" value="${esc(corrEnd)}"></label>
            </div>` : ''}
          </div>`
        );
      }

      if (item.supports_soundscape) {
        const soundscape = String(node.parameters?.soundscape_prompt || '');
        const music = String(node.parameters?.music_prompt || '');
        blocks.push(
          `<label class="desk-easycolab-h3__wide"><span>环境音效与台词对白（可选）</span><input type="text" maxlength="2000" placeholder="例如：海浪拍岸声、脚步声、角色用中文轻声说台词" data-easycolab-h3-field="soundscape_prompt" value="${esc(soundscape)}"></label>`
        );
        blocks.push(
          `<label class="desk-easycolab-h3__wide"><span>背景音乐风格（可选）</span><input type="text" maxlength="2000" placeholder="例如：温暖大提琴与柔和钢琴铺底" data-easycolab-h3-field="music_prompt" value="${esc(music)}"></label>`
        );
      }

      if (item.supports_negative) {
        const negative = String(node.parameters?.negative_prompt || '');
        blocks.push(
          `<label class="desk-easycolab-h3__wide"><span>反向提示词 Negative（可选，自动合并已连接的负面文本节点）</span><input type="text" maxlength="4000" placeholder="例如：模糊、畸变、水印、多余肢体、画面闪烁" data-easycolab-h3-field="negative_prompt" value="${esc(negative)}"></label>`
        );
      }

      return blocks.join('');
    }

    function nodeHtml(node) {
      M.normalize(node);
      const item = selected(node);
      const video = activeKind(node) === 'video';
      const title = video ? 'MiniMax H3 视频' : 'MiniMax H3 图像';
      const sub = item?.short_label ? `EasyColab · ${item.short_label}` : 'EasyColab · MiniMax H3';
      return `<section class="desk-node desk-node--easycolab-h3 desk-node--${esc(node.type)} desk-glass" data-node-id="${esc(node.id)}" aria-label="${title}节点">
        <header class="desk-easycolab-h3__header" data-node-drag-handle>
          <span class="desk-easycolab-h3__icon" data-easycolab-h3-icon>${video ? M.ICON_VIDEO : M.ICON_IMAGE}</span>
          <div><strong data-easycolab-h3-title>${title}</strong><small data-easycolab-h3-subtitle>${esc(sub)}</small></div>
          <span class="desk-status-pill" data-easycolab-h3-status>检测中</span>
          <button class="desk-node-delete" data-node-delete aria-label="删除${title}节点" title="删除${title}节点"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button>
        </header>
        <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接提示词与参考素材"></button>
        <button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接生成结果"></button>
        <div class="desk-easycolab-h3__body" data-node-drag-ignore>
          <label class="desk-easycolab-h3__model"><span>EasyColab 模型</span><select class="desk-select" data-easycolab-h3-model>${modelOptions(node)}</select></label>
          <div class="desk-easycolab-h3__slots" data-easycolab-h3-slots></div>
          <div class="desk-easycolab-h3__fields" data-easycolab-h3-fields>${fieldsHtml(node)}</div>
          <div class="desk-easycolab-h3__inputs" data-easycolab-h3-source-hint>连接文本节点作为主提示词，连接图片或音频节点作为参考</div>
          <footer class="desk-easycolab-h3__footer">
            <div>
              <small data-easycolab-h3-runtime>等待检查 EasyColab 状态</small>
              <div class="desk-easycolab-h3__toggles">
                <label class="desk-easycolab-h3__telegram"><input type="checkbox" data-easycolab-h3-telegram ${node.telegramEnabled ? 'checked' : ''}>发送到 Telegram</label>
                <label class="desk-easycolab-h3__telegram"><input type="checkbox" data-easycolab-h3-autosleep ${node.parameters?.auto_sleep ? 'checked' : ''}>完成后休眠省 CU</label>
              </div>
            </div>
            <div class="desk-easycolab-h3__actions">
              <button type="button" class="desk-button" data-easycolab-h3-load hidden>加载模型</button>
              <button type="button" class="desk-generation-action desk-easycolab-h3__run" data-easycolab-h3-run title="开始生成" aria-label="开始生成"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13.5 2-9 12h6l-1 8 10-13h-7z"></path></svg><span class="desk-generation-action__label">开始生成</span></button>
              <button type="button" class="desk-button" data-easycolab-h3-resend hidden>补发</button>
            </div>
          </footer>
        </div>
        <div class="desk-progress-float desk-easycolab-h3__progress" data-easycolab-h3-progress hidden role="status">
          <div class="desk-progress-float__panel">
            <div class="desk-progress-float__bar"><span data-easycolab-h3-bar></span><strong class="desk-progress-float__percent" data-easycolab-h3-percent>处理中</strong></div>
            <span data-easycolab-h3-stage>EasyColab H3 任务进行中</span>
          </div>
        </div>
      </section>`;
    }

    function incoming(s, type) {
      return (getCanvas().edges || [])
        .filter(edge => edge.to === s.id)
        .map(edge => getNodeState(edge.from))
        .filter(node => node?.type === type);
    }

    function modelLoaded(item) {
      if (!item || !catalog?.connected) return false;
      return Array.isArray(catalog.loaded_model_ids) && catalog.loaded_model_ids.includes(item.id);
    }

    function renderSlots(s, item, mode) {
      const container = s.el.querySelector('[data-easycolab-h3-slots]');
      if (!container) return;
      const texts = getTextNodes(s.id);
      const negTexts = typeof getNegativeTextNodes === 'function' ? getNegativeTextNodes(s.id) : [];
      const refs = getImageReferences(s.id);
      const audios = incoming(s, 'audio');
      const chips = [];

      chips.push(`<span class="desk-easycolab-h3__slot${texts.length ? ' is-ready' : ' is-missing'}"><b>主提示词</b><em>${texts.length ? `已连 ${texts.length} 个文本` : '请连文本节点'}</em></span>`);

      if (mode?.id === 'multiref') {
        const count = refs.length;
        const cap = mode.max_images || 9;
        const picSummary = count
          ? refs.slice(0, 3).map((_, idx) => `&lt;Picture ${idx + 1}&gt;`).join(' ') + (count > 3 ? ` …共 ${count} 张` : '')
          : '可连 1~9 张图';
        chips.push(`<span class="desk-easycolab-h3__slot${count ? ' is-ready' : ''}"><b>多图参考 (${count}/${cap})</b><em>${picSummary}</em></span>`);
        const audioName = audios[0]?.mediaName ? esc(String(audios[0].mediaName).slice(0, 20)) : '可选 · 连音频节点';
        chips.push(`<span class="desk-easycolab-h3__slot${audios.length ? ' is-ready' : ''}"><b>声纹 &lt;Audio 1&gt;</b><em>${audioName}</em></span>`);
      } else if (mode?.id === 'fl2va') {
        const firstLabel = refs[0] ? esc(String(refs[0].name || '图片 1').slice(0, 18)) : '必需 · 连图片 1';
        const lastLabel = refs[1] ? esc(String(refs[1].name || '图片 2').slice(0, 18)) : '可选 · 连图片 2';
        chips.push(`<span class="desk-easycolab-h3__slot${refs[0] ? ' is-ready' : ' is-missing'}"><b>首帧</b><em>${firstLabel}</em></span>`);
        chips.push(`<span class="desk-easycolab-h3__slot${refs[1] ? ' is-ready' : ''}"><b>尾帧</b><em>${lastLabel}</em></span>`);
      } else if (mode?.id === 'i2i_edit') {
        const p1 = refs[0] ? esc(String(refs[0].name || '图片 1').slice(0, 18)) : '必需 · 连图片 1';
        const p2 = refs[1] ? esc(String(refs[1].name || '图片 2').slice(0, 18)) : '可选 · 连图片 2';
        chips.push(`<span class="desk-easycolab-h3__slot${refs[0] ? ' is-ready' : ' is-missing'}"><b>&lt;Picture 1&gt;</b><em>${p1}</em></span>`);
        chips.push(`<span class="desk-easycolab-h3__slot${refs[1] ? ' is-ready' : ''}"><b>&lt;Picture 2&gt;</b><em>${p2}</em></span>`);
      }

      if (item?.supports_negative && negTexts.length > 0) {
        chips.push(`<span class="desk-easycolab-h3__slot is-ready"><b>负面文本</b><em>已连 ${negTexts.length} 个</em></span>`);
      }

      container.innerHTML = chips.join('');
    }

    function syncHeight(s) {
      if (!live(s)) return;
      s.el.style.height = 'auto';
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => {
          if (!live(s)) return;
          const measured = Math.round(s.el.offsetHeight || 0);
          if (measured > 200 && Math.abs((s.node.height || 0) - measured) > 4) {
            s.node.height = measured;
            updateLinkPath?.();
          }
        });
      }
    }

    function paint(s) {
      if (!live(s)) return;
      const node = s.node;
      const busy = Boolean(s.pending) || M.active(node.status);
      const item = selected(node);
      const mode = modeFor(node, item);
      const video = activeKind(node) === 'video';
      const loaded = modelLoaded(item);

      const iconEl = s.el.querySelector('[data-easycolab-h3-icon]');
      const titleEl = s.el.querySelector('[data-easycolab-h3-title]');
      const subtitleEl = s.el.querySelector('[data-easycolab-h3-subtitle]');
      if (iconEl) iconEl.innerHTML = video ? M.ICON_VIDEO : M.ICON_IMAGE;
      if (titleEl) titleEl.textContent = video ? 'MiniMax H3 视频' : 'MiniMax H3 图像';
      if (subtitleEl) subtitleEl.textContent = item?.short_label ? `EasyColab · ${item.short_label}` : 'EasyColab · MiniMax H3';

      renderSlots(s, item, mode);

      const badge = s.el.querySelector('[data-easycolab-h3-status]');
      const statusText = {
        idle: loaded ? '已就绪' : (catalog?.connected ? '待加载' : '待连接'),
        submitting: '提交中',
        queued: '处理中',
        processing: '处理中',
        running: '处理中',
        succeeded: '已完成',
        succeeded_no_telegram: '已归档',
        telegram_failed: '已生成，未发送',
        failed: '失败',
        canceled: '已停止'
      };
      badge.textContent = busy
        ? (statusText[node.status] || '处理中')
        : catalogError
          ? '服务异常'
          : !catalog
            ? '检测中'
            : !catalog.configured
              ? '待配置'
              : !catalog.connected
                ? '未连接'
                : (statusText[node.status] || '就绪');
      badge.classList.toggle(
        'is-success',
        !busy && ['idle', 'succeeded', 'succeeded_no_telegram'].includes(node.status) && Boolean(item) && Boolean(catalog?.connected) && loaded
      );

      const loadBtn = s.el.querySelector('[data-easycolab-h3-load]');
      if (loadBtn) {
        const showLoad = Boolean(catalog?.connected && item && !loaded && !busy);
        loadBtn.hidden = !showLoad;
        loadBtn.disabled = Boolean(s.loadingModel || catalog?.gpu?.is_loading_vram);
        loadBtn.textContent = s.loadingModel || catalog?.gpu?.is_loading_vram ? '加载中…' : '加载模型';
      }

      const button = s.el.querySelector('[data-easycolab-h3-run]');
      button.disabled = busy || !item;
      button.setAttribute('aria-busy', String(busy));
      button.querySelector('span').textContent = busy
        ? '生成中'
        : node.status === 'telegram_failed'
          ? '再次生成'
          : node.status === 'failed'
            ? '重试生成'
            : '开始生成';

      const resendBtn = s.el.querySelector('[data-easycolab-h3-resend]');
      if (resendBtn) {
        resendBtn.hidden = node.status !== 'telegram_failed';
        resendBtn.disabled = Boolean(busy || s.pending);
      }

      const hint = s.el.querySelector('[data-easycolab-h3-source-hint]');
      if (catalogError) {
        hint.textContent = catalogError;
      } else if (catalog && !catalog.configured) {
        hint.textContent = '请先在设置 → 第三方 API 中填写 EasyColab 服务地址，或先唤醒本地会话';
      } else if (catalog && !catalog.connected) {
        hint.textContent = catalog.connection_error || '未连接到 EasyColab 服务';
      } else {
        hint.textContent = item?.summary || '输出口按当前模型自动对接图片或视频节点';
      }

      const runtimeEl = s.el.querySelector('[data-easycolab-h3-runtime]');
      if (runtimeEl) {
        if (catalog?.connected) {
          const gpu = catalog.gpu || {};
          const gpuName = gpu.gpu_name || 'Colab GPU';
          const vram = gpu.vram_total_gb ? `${Number(gpu.vram_free_gb || 0).toFixed(1)}/${Number(gpu.vram_total_gb).toFixed(0)} GB 可用` : '';
          const stateLabel = loaded ? '显存已就绪' : (catalog.auto_load_model ? '提交时自动加载' : '需先加载模型');
          runtimeEl.textContent = [gpuName, vram, stateLabel].filter(Boolean).join(' · ');
        } else if (catalog?.configured) {
          runtimeEl.textContent = 'EasyColab 服务离线或等待连接';
        } else {
          runtimeEl.textContent = '未配置 EasyColab 连接';
        }
      }

      const progress = s.el.querySelector('[data-easycolab-h3-progress]');
      progress.hidden = !busy;
      if (busy) {
        s.el.querySelector('[data-easycolab-h3-bar]').style.width = `${Math.max(8, Math.min(96, Number(s.job?.progress || 15)))}%`;
        s.el.querySelector('[data-easycolab-h3-stage]').textContent = s.job?.progress_text || 'EasyColab H3 任务进行中';
        s.el.querySelector('[data-easycolab-h3-percent]').textContent = s.job?.progress ? `${s.job.progress}%` : '处理中';
      }
      const task = s.pending ? null : s.job;
      progressView?.update(progress, {
        visible: busy,
        running: busy,
        taskId: node.jobId,
        percent: task?.progress ?? null,
        title: task?.progress_text || (s.pending ? '正在上传素材并提交' : 'EasyColab H3 任务进行中'),
        detail: item?.label || (video ? 'MiniMax H3 视频' : 'MiniMax H3 图像'),
        startedAt: task?.started_at || task?.created_at || s.progressStartedAt,
        finishedAt: task?.finished_at
      }, s.el);

      s.el.querySelectorAll('.desk-easycolab-h3__body :is(input,select)').forEach(input => {
        input.disabled = busy;
      });
      syncHeight(s);
    }

    function renderCatalog(s) {
      if (!live(s)) return;
      const list = allChoices();
      if (list.length && !list.some(item => item.id === s.node.modelId)) {
        s.node.modelId = M.DEFAULT_MODEL_ID[s.node.type] || list[0].id;
      }
      s.el.querySelector('[data-easycolab-h3-model]').innerHTML = modelOptions(s.node);
      s.el.querySelector('[data-easycolab-h3-fields]').innerHTML = fieldsHtml(s.node);
      window.DesktopSelect?.enhanceIn?.(s.el);
      window.DesktopSelect?.refreshAll?.();
      paint(s);
    }

    function loadCatalog() {
      if (catalogPromise) return catalogPromise;
      catalogPromise = api.catalog()
        .then(value => {
          catalog = value;
          catalogError = '';
          sessions.forEach(renderCatalog);
          return value;
        })
        .catch(error => {
          catalogError = error.message || 'EasyColab 目录加载失败';
          sessions.forEach(paint);
          throw error;
        })
        .finally(() => {
          catalogPromise = null;
        });
      return catalogPromise;
    }

    function feedback(s, message = '', tone = 'info') {
      if (!live(s)) return;
      const task = s.job || {};
      const stage = message || task.progress_text || task.error || 'EasyColab H3 任务';
      const title = activeKind(s.node) === 'video' ? 'MiniMax H3 视频' : 'MiniMax H3 图像';
      reportStatus({
        message: `${title} · ${stage}`,
        tone,
        task: {
          ...task,
          task_id: s.node.jobId || '',
          node_id: s.id,
          node_title: `${title} · ${s.id.slice(-6)}`,
          operation_label: 'EasyColab H3 生成',
          provider_route: 'easycolab_h3',
          status: s.node.status,
          status_label: stage,
          detail_title: 'EasyColab MiniMax H3 任务状态',
          progress_text: stage,
          raw_detail: task.error || message || stage
        }
      });
    }

    async function publish(s, task, onlyTarget = '') {
      if (!live(s) || !task?.result_files?.length || s.publishing) return;
      const targetType = (task.type === 'easycolab-h3-video' || task.video_paths?.length) ? 'video' : 'image';
      const paths = targetType === 'video' ? task.video_paths : task.image_paths;
      if (!paths?.length) return;
      s.publishing = true;
      try {
        const edges = (getCanvas().edges || []).filter(e => e.from === s.id && getNodeState(e.to)?.type === targetType);
        if (onlyTarget && !edges.some(e => e.to === onlyTarget)) return;
        if (!onlyTarget) {
          for (let i = edges.length; i < paths.length; i++) {
            const source = s.node;
            const id = addNode(targetType, { x: source.x + source.width + 260, y: source.y + 110 + i * 215 });
            connectNodes(s.id, id, { quiet: true, outputSlot: i });
            edges.push((getCanvas().edges || []).find(e => e.from === s.id && e.to === id));
          }
        }
        const targets = onlyTarget ? edges.filter(e => e.to === onlyTarget) : edges;
        for (let index = 0; index < targets.length; index++) {
          const edge = targets[index];
          const target = getNodeState(edge?.to);
          const slot = Number.isInteger(Number(edge?.outputSlot)) ? Number(edge.outputSlot) : edges.indexOf(edge);
          const mediaPath = paths[slot] || paths[0];
          if (!target || !mediaPath) continue;
          if (targetType === 'image') {
            await setImageFromResult(target.id, s.id, {
              imagePaths: paths,
              files: task.result_files,
              primaryFile: task.result_file,
              taskId: task.task_id,
              prompt: task.prompt,
              type: 'easycolab_h3'
            }, slot);
          } else {
            const ext = mediaPath.split(/[?#]/, 1)[0].split('.').pop().toLowerCase();
            const mimeType = { mov: 'video/quicktime', webm: 'video/webm' }[ext] || 'video/mp4';
            Object.assign(target, {
              mediaUrl: mediaPath,
              mediaName: task.result_files[slot] || task.result_file || 'MiniMax H3 视频',
              mimeType,
              status: 'succeeded',
              sourceTaskId: task.task_id
            });
            refreshVideoNode(target.id);
          }
        }
        s.node.resultJobId = task.task_id;
        saveState();
      } finally {
        s.publishing = false;
      }
    }

    async function poll(s) {
      clearTimeout(s.timer);
      const id = s.node.jobId;
      const epoch = s.epoch || 0;
      if (!id || !live(s)) return;
      try {
        const task = await api.job(id);
        if (!live(s) || s.node.jobId !== id || (s.epoch || 0) !== epoch) return;
        s.job = task;
        s.node.status = task.status;
        if (task.result_files?.length && ['succeeded', 'succeeded_no_telegram', 'telegram_failed'].includes(task.status)) {
          await publish(s, task);
        }
        paint(s);
        feedback(s, '', task.error ? 'error' : (task.status === 'succeeded' ? 'success' : 'info'));
        saveState();
        if (!terminal(task.status)) s.timer = setTimeout(() => poll(s), 3000);
      } catch (error) {
        if (!live(s) || s.node.jobId !== id || (s.epoch || 0) !== epoch) return;
        s.notice = error.message;
        paint(s);
        feedback(s, error.message, 'error');
        if (!terminal(s.node.status)) s.timer = setTimeout(() => poll(s), 5000);
      }
    }

    async function uploadSources(s, mode) {
      const result = { image: [], audio: [] };
      const maxImages = Number(mode?.max_images || 0);
      const maxAudios = Number(mode?.max_audios || 0);

      if (maxImages > 0) {
        const refs = getImageReferences(s.id);
        if (refs.length > maxImages) {
          throw new Error(`当前模式最多支持 ${maxImages} 张参考图`);
        }
        for (const ref of refs) {
          const source = ref.base64 || ref.imageData || ref.imageUrl || ref.url;
          if (!source) continue;
          const blob = await api.sourceBlob(source, 'image');
          result.image.push(await api.upload(blob, ref.name || 'reference.png'));
        }
      }

      if (maxAudios > 0) {
        const audioNodes = incoming(s, 'audio');
        if (audioNodes.length > maxAudios) {
          throw new Error(`当前模式最多支持 ${maxAudios} 段声纹音频`);
        }
        for (const audioNode of audioNodes) {
          let blob = await audioAssets?.get?.(audioNode.audioAssetId);
          if (!blob && audioNode.mediaUrl) {
            blob = await api.sourceBlob(audioNode.mediaUrl, 'audio');
          }
          if (blob) {
            result.audio.push(await api.upload(blob, audioNode.mediaName || 'voice_seed.wav'));
          }
        }
      }

      if (mode?.id === 'fl2va' && !result.image.length) {
        throw new Error('首尾帧模式需要至少连接 1 张参考图');
      }
      if (mode?.id === 'multiref' && !result.image.length && !result.audio.length) {
        throw new Error('多图参考模式需要至少连接 1 张参考图或 1 段音频');
      }
      if (mode?.id === 'i2i_edit' && !result.image.length) {
        throw new Error('指令修图模式需要至少连接 1 张参考图');
      }
      return result;
    }

    async function requestModelLoad(s) {
      const item = selected(s.node);
      if (!item || s.loadingModel) return;
      s.loadingModel = true;
      paint(s);
      try {
        const res = await api.loadModel(item.id);
        feedback(s, res.message || `已请求加载 ${item.short_label} 到显存`, 'info');
        setTimeout(() => { loadCatalog().catch(() => {}); }, 2500);
      } catch (error) {
        feedback(s, error.message || '加载模型失败', 'error');
      } finally {
        s.loadingModel = false;
        if (live(s)) paint(s);
      }
    }

    async function run(id) {
      const s = sessions.get(id);
      if (!s || s.pending || M.active(s.node.status)) return;
      s.progressStartedAt = Date.now();
      try {
        if (!catalog) await loadCatalog();
        if (!catalog?.configured) {
          throw new Error('请先在设置中填写 EasyColab 服务地址，或先唤醒本地会话');
        }
        const item = selected(s.node);
        if (!item) throw new Error('请先选择 EasyColab MiniMax H3 模型');
        const mode = modeFor(s.node, item);
        const texts = getTextNodes(s.id).map(node => materializeText(node)).filter(Boolean);
        const prompt = texts.map(v => String(v || '').trim()).filter(Boolean).join('\n\n');
        if (!prompt) throw new Error('请连接含有提示词的文本节点');

        const connectedNeg = item.supports_negative && typeof getNegativeTextNodes === 'function'
          ? getNegativeTextNodes(s.id).map(node => String(materializeText(node) || '').trim()).filter(Boolean)
          : [];
        const inlineNeg = item.supports_negative ? String(s.node.parameters?.negative_prompt || '').trim() : '';
        const negativePrompt = [...connectedNeg, ...(inlineNeg ? [inlineNeg] : [])].join('\n\n');

        s.pending = true;
        s.node.status = 'submitting';
        s.notice = '';
        paint(s);
        feedback(s, '正在上传参考素材并提交任务');

        const tokens = await uploadSources(s, mode);
        if (!live(s)) return;

        const sizeKey = sizeValueFor(s.node, item);
        let width = Number(paramValue(s.node, item, 'width') || item.defaults.width);
        let height = Number(paramValue(s.node, item, 'height') || item.defaults.height);
        if (sizeKey !== 'custom') {
          const [wRaw, hRaw] = sizeKey.split('x').map(Number);
          if (wRaw > 0 && hRaw > 0) {
            width = wRaw;
            height = hRaw;
          }
        }
        const parameters = {
          task_mode: mode.id,
          width,
          height,
          seed: Number(paramValue(s.node, item, 'seed') ?? -1),
          batch_count: Number(paramValue(s.node, item, 'batch_count') ?? 1),
          auto_sleep: s.node.parameters?.auto_sleep === true
        };

        if (item.kind === 'video') {
          parameters.num_frames = M.snapFrames(paramValue(s.node, item, 'num_frames'));
          parameters.num_inference_steps = Number(paramValue(s.node, item, 'num_inference_steps') ?? item.defaults.num_inference_steps);
          parameters.fps = Number(paramValue(s.node, item, 'fps') ?? item.defaults.fps ?? 24);
          if (s.node.parameters?.soundscape_prompt) {
            parameters.soundscape_prompt = String(s.node.parameters.soundscape_prompt);
          }
          if (s.node.parameters?.music_prompt) {
            parameters.music_prompt = String(s.node.parameters.music_prompt);
          }
          if (item.supports_ref_image_size) {
            parameters.ref_image_size = String(paramValue(s.node, item, 'ref_image_size') || 'match');
          }
          if (item.supports_corrector) {
            parameters.corrector_enabled = paramValue(s.node, item, 'corrector_enabled') !== false;
            parameters.corrector_strength = Number(paramValue(s.node, item, 'corrector_strength') ?? 1.0);
            parameters.corrector_budget_fraction = Number(paramValue(s.node, item, 'corrector_budget_fraction') ?? 0.5);
            parameters.corrector_start_step = Number(paramValue(s.node, item, 'corrector_start_step') ?? 0);
            parameters.corrector_end_step = Number(paramValue(s.node, item, 'corrector_end_step') ?? -1);
          }
        }

        const reply = await api.submit({
          kind: item.kind,
          model_id: item.id,
          task_mode: mode.id,
          prompt,
          negative_prompt: negativePrompt,
          parameters,
          image_upload_tokens: tokens.image,
          audio_upload_tokens: tokens.audio,
          telegram_enabled: s.node.telegramEnabled,
          auto_sleep: s.node.parameters?.auto_sleep === true
        });
        if (!live(s)) return;
        s.node.jobId = reply.task_id;
        s.node.resultJobId = '';
        s.node.status = reply.status || 'queued';
        saveState();
      } catch (error) {
        if (live(s)) {
          s.node.status = 'failed';
          s.notice = error.message;
          feedback(s, error.message, 'error');
        }
      } finally {
        if (live(s)) {
          s.pending = false;
          paint(s);
          saveState();
          if (s.node.jobId && M.active(s.node.status)) poll(s);
        }
      }
    }

    function applyFieldChange(node, input) {
      const key = input.dataset.easycolabH3Field;
      if (!key) return false;
      if (key === 'size') {
        if (input.value === 'custom') {
          node.parameters.custom_size = true;
          return true;
        }
        node.parameters.custom_size = false;
        const [w, h] = String(input.value || '').split('x').map(Number);
        if (w > 0 && h > 0) {
          node.parameters.width = w;
          node.parameters.height = h;
        }
        return true;
      }
      if (key === 'task_mode' || key === 'corrector_enabled') {
        node.parameters[key] = input.type === 'checkbox' ? input.checked : input.value;
        return true;
      }
      if (input.type === 'checkbox') {
        node.parameters[key] = input.checked;
      } else if (input.type === 'number' || key === 'num_frames' || key === 'batch_count') {
        node.parameters[key] = Number(input.value);
      } else {
        node.parameters[key] = input.value;
      }
      return false;
    }

    function mount(node) {
      const el = getNodeElement(node.id);
      if (!el || sessions.has(node.id)) return;
      M.normalize(node);
      const s = { id: node.id, node, el, abort: new AbortController() };
      sessions.set(node.id, s);

      el.addEventListener('click', event => {
        if (event.target.closest('[data-easycolab-h3-resend]')) {
          const taskId = s.node.jobId || s.node.resultJobId || s.job?.task_id || s.job?.id;
          if (!taskId) {
            feedback(s, '没有可补发的任务。', 'error');
            return;
          }
          const resendBtn = s.el.querySelector('[data-easycolab-h3-resend]');
          if (resendBtn) resendBtn.disabled = true;
          const done = window.DesktopResults?.resendArchivedTelegram?.(taskId);
          if (!done) {
            feedback(s, '补发接口不可用', 'error');
            paint(s);
            return;
          }
          Promise.resolve(done)
            .then(task => {
              if (task?.skipped === 'busy') return;
              if (task?.resent) {
                s.node.status = task.status || 'succeeded';
                if (s.job) s.job = { ...s.job, ...task, status: s.node.status };
              }
            })
            .catch(error => feedback(s, error.message, 'error'))
            .finally(() => { if (live(s)) paint(s); });
          return;
        }
        if (event.target.closest('[data-easycolab-h3-load]')) {
          requestModelLoad(s);
          return;
        }
        if (event.target.closest('[data-easycolab-h3-run]')) {
          run(s.id);
        }
      }, { signal: s.abort.signal });

      el.addEventListener('change', event => {
        const input = event.target;
        if (input.matches('[data-easycolab-h3-model]')) {
          node.modelId = input.value;
          const item = selected(node);
          if (item) {
            node.parameters.task_mode = item.default_mode;
            node.parameters.num_inference_steps = item.defaults.num_inference_steps;
            node.parameters.width = item.defaults.width;
            node.parameters.height = item.defaults.height;
            node.parameters.custom_size = false;
            if (item.defaults.fps) node.parameters.fps = item.defaults.fps;
          }
          renderCatalog(s);
          saveState();
          return;
        }
        if (input.matches('[data-easycolab-h3-telegram]')) {
          node.telegramEnabled = input.checked;
          saveState();
          paint(s);
          return;
        }
        if (input.matches('[data-easycolab-h3-autosleep]')) {
          node.parameters.auto_sleep = input.checked;
          saveState();
          paint(s);
          return;
        }
        if (input.dataset.easycolabH3Field) {
          const rebuild = applyFieldChange(node, input);
          if (rebuild) renderCatalog(s);
          else paint(s);
          saveState();
        }
      }, { signal: s.abort.signal });

      if (node.status === 'submitting' && !node.jobId) node.status = 'failed';
      renderCatalog(s);
      if (node.jobId) poll(s);
      if (!catalog) loadCatalog().catch(() => {});
    }

    function dispose(id) {
      const s = sessions.get(id);
      if (!s) return;
      progressView?.releaseWithin(s.el);
      sessions.delete(id);
      s.abort.abort();
      clearTimeout(s.timer);
    }

    function disposeAll() {
      [...sessions.keys()].forEach(dispose);
    }

    function reconcile() {
      [...sessions.values()].forEach(s => { if (!live(s)) dispose(s.id); });
      Object.values(getCanvas().nodes).filter(n => M.TYPES.includes(n.type)).forEach(mount);
    }

    function graphChanged() {
      sessions.forEach(paint);
    }

    function connected(from, to) {
      const s = sessions.get(from);
      if (s?.job?.result_files?.length && !s.publishing) {
        publish(s, s.job, to).catch(error => feedback(s, error.message, 'error'));
      }
      graphChanged();
    }

    function getCancelableTasks() {
      const list = [];
      sessions.forEach(s => {
        if (!live(s) || !s.node.jobId || !M.active(s.node.status)) return;
        list.push({
          domain: 'easycolab_h3',
          taskId: s.node.jobId,
          label: activeKind(s.node) === 'video' ? 'MiniMax H3 视频' : 'MiniMax H3 图像',
          applyReceipt: receipt => {
            if (!live(s)) return;
            s.node.status = receipt?.status || 'canceled';
            s.job = { ...(s.job || {}), ...(receipt || {}), status: s.node.status };
            paint(s);
            saveState();
          }
        });
      });
      return list;
    }

    window.addEventListener('desktop:easycolab-h3-settings-updated', () => {
      Promise.resolve(catalogPromise).catch(() => {}).then(loadCatalog).catch(() => {});
    });

    return Object.freeze({
      nodeHtml,
      reconcile,
      dispose,
      disposeAll,
      run,
      graphChanged,
      getCancelableTasks,
      showStatus: id => {
        const s = sessions.get(id);
        if (s && (s.job || s.notice)) feedback(s, s.notice || '');
      },
      connections: {
        targets: M.targets,
        policy: M.policy,
        changed: connected,
        removed: graphChanged
      }
    });
  }

  window.DesktopCanvasEasyColabH3 = Object.freeze({ create });
})();
