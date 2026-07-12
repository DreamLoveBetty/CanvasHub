(function () {
  const els = {};
  const WORLD_WIDTH = 1440;
  const WORLD_HEIGHT = 820;
  const MIN_SCALE = 0.3;
  const MAX_SCALE = 1.8;
  const ZOOM_PRESETS = [0.3, 0.5, 0.75];
  const DEFAULT_CANVAS_SCALE = 0.75;
  const MIN_NODE_WIDTH = 360;
  const MIN_NODE_HEIGHT = 260;
  const MAX_NODE_WIDTH = 760;
  const MAX_NODE_HEIGHT = 760;
  const MIN_IMAGE_NODE_WIDTH = 96;
  const MAX_IMAGE_NODE_WIDTH = 760;
  const MIN_TEXT_NODE_WIDTH = 220;
  const MIN_TEXT_NODE_HEIGHT = 120;
  const MAX_TEXT_NODE_WIDTH = 680;
  const MAX_TEXT_NODE_HEIGHT = 520;
  const DEFAULT_TEXT_NODE_WIDTH = 600;
  const DEFAULT_TEXT_NODE_HEIGHT = 360;
  const DEFAULT_IMAGE_NODE_WIDTH = 600;
  const DEFAULT_IMAGE_NODE_HEIGHT = 400;
  const DEFAULT_INPUT_NODE_WIDTH = 720;
  const DEFAULT_INPUT_NODE_HEIGHT = 460;
  const DEFAULT_FILE_OUTPUT_NODE_WIDTH = 458;
  const DEFAULT_FILE_OUTPUT_NODE_HEIGHT = 420;
  const DEFAULT_UPSCALE_NODE_WIDTH = 360;
  const DEFAULT_UPSCALE_NODE_HEIGHT = 180;
  const LOCKED_INPUT_NODE_WIDTH = DEFAULT_INPUT_NODE_WIDTH;
  const LOCKED_INPUT_NODE_HEIGHT = DEFAULT_INPUT_NODE_HEIGHT;
  const MIN_INPUT_NODE_WIDTH = 560;
  const MAX_INPUT_NODE_WIDTH = 920;
  const DEFAULT_IMAGE_LONGEST_SIDE = 520;
  const TEXT_NODE_DRAG_EDGE_PX = 6;
  const TEXT_NODE_ALIAS_MAX_LENGTH = 24;
  const LINK_VIEWBOX = '-3000 -3000 8000 8000';
  const SNAP_THRESHOLD_PX = 9;
  const PORT_RADIUS = 7;
  const CANVAS_PAN_DRAG_THRESHOLD_PX = 3;
  const CANVAS_CONTEXTMENU_SUPPRESS_MS = 450;
  const CANVAS_INTERACTION_BLOCK_SELECTOR = [
    '.desk-node',
    '.desk-node-palette',
    '.desk-gallery-panel',
    '.desk-settings',
    '.desk-selection-group',
    '.desk-selection-toolbar',
    '.desk-zoom-controls',
    '.desk-workflow-dock-toggle',
    '.desk-workflow-dock-panel'
  ].join(', ');
  const CANVAS_RIGHT_PAN_BLOCK_SELECTOR = [
    '.desk-node-palette',
    '.desk-gallery-panel',
    '.desk-settings',
    '.desk-selection-group',
    '.desk-selection-toolbar',
    '.desk-zoom-controls',
    '.desk-workflow-dock-toggle',
    '.desk-workflow-dock-panel'
  ].join(', ');
  const CANVAS_RIGHT_PAN_CONTROL_SELECTOR = [
    'button',
    'input',
    'textarea',
    'select',
    'a',
    '[contenteditable="true"]',
    '.desk-port',
    '[data-node-resize-handle]',
    '[data-upload-drop]'
  ].join(', ');
  const IMAGE_EDIT_MIN_ZOOM = 0.02;
  const IMAGE_EDIT_MAX_ZOOM = 4;
  const IMAGE_EDIT_ZOOM_STEP = 1.2;
  const WORKFLOW_SCHEMA = 'tg-mini-app-img-gen.desktop-workflow';
  const WORKFLOW_VERSION = 1;
  const PLATFORM_INFO = (() => {
    const nav = window.navigator || {};
    return {
      platform: String(nav.platform || '').toLowerCase(),
      userAgentPlatform: String(nav.userAgentData?.platform || '').toLowerCase(),
      userAgent: String(nav.userAgent || '').toLowerCase()
    };
  })();
  const IS_WINDOWS_PLATFORM = PLATFORM_INFO.platform.includes('win')
    || PLATFORM_INFO.userAgentPlatform.includes('windows')
    || PLATFORM_INFO.userAgent.includes('windows');
  const IS_MAC_PLATFORM = !IS_WINDOWS_PLATFORM && (
    PLATFORM_INFO.platform.includes('mac')
    || PLATFORM_INFO.userAgentPlatform.includes('mac')
    || PLATFORM_INFO.userAgent.includes('macintosh')
    || PLATFORM_INFO.userAgent.includes('mac os x')
  );
  let textPolishState = null;
  const TEXT_POLISH_VARIANTS = [
    { id: 'full', title: '完整提示', hint: '结构完整，适合直接投喂模型' },
    { id: 'compact', title: '简化提示', hint: '保留核心画面，适合快速迭代' },
    { id: 'original', title: '原始碎片', hint: '恢复润色前的文本节点内容' }
  ];
  const ASPECT_RATIO_OPTIONS = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '9:21', '21:9'];
  const DEFAULT_GOOGLE_MODEL = 'gemini-3.1-flash-image';
  const GOOGLE_MODEL_OPTIONS = [
    { value: 'gemini-3-pro-image', label: 'Pro' },
    { value: 'gemini-3.1-flash-image', label: 'Flash' }
  ];
  const GPT_MAIN_MODEL_OPTIONS = [
    { value: 'gpt-5.6-sol', label: 'GPT-5.6 Sol' },
    { value: 'gpt-5.6-terra', label: 'GPT-5.6 Terra' },
    { value: 'gpt-5.6-luna', label: 'GPT-5.6 Luna' },
    { value: 'gpt-5.5', label: 'GPT-5.5' },
    { value: 'gpt-5.4', label: 'GPT-5.4' },
    { value: 'gpt-5.4-mini', label: 'GPT-5.4 Mini' }
  ];
  const GPT_REASONING_OPTIONS = [
    { value: 'none', label: '关闭' },
    { value: 'low', label: '低' },
    { value: 'medium', label: '中' },
    { value: 'high', label: '高' },
    { value: 'xhigh', label: '超高' },
    { value: 'max', label: '最大' },
    { value: 'ultra', label: '极限' }
  ];
  const GPT_PROVIDER_ROUTE_OPTIONS = [
    { value: 'codex', label: '本地 Codex' },
    { value: 'chatgpt_pool', label: '账号池 API' },
    { value: 'third_party_image_api', label: '第三方 API' }
  ];
  const GPT_ROUTE_PRESENTATION = {
    codex: { modelLabel: '主模型', engineLabel: 'GPT Image 2' },
    chatgpt_pool: { modelLabel: '主模型', engineLabel: 'ChatGPT Image' },
    third_party_image_api: { modelLabel: '生图模型', engineLabel: 'gpt-image-2' }
  };
  const GPT_TASK_TYPE_OPTIONS = [
    { value: 'image', label: '图片' },
    { value: 'ppt', label: 'PPT' },
    { value: 'psd', label: 'PSD' }
  ];
  const GPT_PROMPT_MODE_OPTIONS = [
    { value: 'smart', label: '智能理解' },
    { value: 'web_search', label: '联网检索' },
    { value: 'faithful', label: '忠实原文' }
  ];
  const UPSCALE_MODEL_OPTIONS = [
    { value: '4x-UltraSharp', label: 'UltraSharp' },
    { value: '4x-AnimeSharp', label: 'AnimeSharp' }
  ];
  const NODE_MENU_ITEMS = [
    {
      type: 'input',
      title: '模型输入',
      subtitle: '模型与提示词',
      icon: '<svg class="desk-node-icon desk-node-icon--input" viewBox="0 0 24 24"><g class="desk-node-icon__frame"><path d="M3 8V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3"></path></g><g class="desk-node-icon__enter"><path d="m10 16 4-4-4-4"></path><path d="M3 12h11"></path></g></svg>'
    },
    {
      type: 'file_output',
      title: '文件结果',
      subtitle: 'PPT / PSD',
      icon: '<svg class="desk-node-icon desk-node-icon--files" viewBox="0 0 24 24"><path class="desk-node-icon__file-front" d="M15 2h-4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8"></path><path class="desk-node-icon__file-front" d="M16.706 2.706A2.4 2.4 0 0 0 15 2v5a1 1 0 0 0 1 1h5a2.4 2.4 0 0 0-.706-1.706z"></path><path class="desk-node-icon__file-back" d="M5 7a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h8a2 2 0 0 0 1.732-1"></path></svg>'
    },
    {
      type: 'image',
      title: '图片节点',
      subtitle: '参考图输入',
      icon: '<svg class="desk-node-icon desk-node-icon--image" viewBox="0 0 24 24"><g class="desk-node-icon__image-body"><path d="M21 11.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7.5"></path><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path><circle cx="9" cy="9" r="2"></circle></g><g class="desk-node-icon__plus"><path d="M16 5h6"></path><path d="M19 2v6"></path></g></svg>'
    },
    {
      type: 'upscale',
      title: '高清放大',
      subtitle: '4x 本地超分',
      icon: '<svg class="desk-node-icon desk-node-icon--upscale" viewBox="0 0 24 24"><g class="desk-node-icon__upscale-arrow"><path d="M16 3h5v5"></path><path d="m21 3-5 5"></path></g><g class="desk-node-icon__upscale-frame"><path d="M17 21h2a2 2 0 0 0 2-2"></path><path d="M21 12v3"></path><path d="M3 7V5a2 2 0 0 1 2-2"></path><path d="m5 21 4.144-4.144a1.21 1.21 0 0 1 1.712 0L13 19"></path><path d="M9 3h3"></path><rect x="3" y="11" width="10" height="10" rx="1"></rect></g></svg>'
    },
    {
      type: 'pose',
      title: '姿态参考',
      subtitle: '多角色机位参考',
      icon: '<svg class="desk-node-icon desk-node-icon--pose" viewBox="0 0 24 24"><g class="desk-node-icon__pose-body"><circle cx="12" cy="5" r="1"></circle><path d="m9 20 3-6 3 6"></path><path d="m6 8 6 2 6-2"></path><path d="M12 10v4"></path></g></svg>'
    },
    {
      type: 'text',
      title: '文本节点',
      subtitle: '提示词处理',
      icon: '<svg class="desk-node-icon desk-node-icon--text" viewBox="0 0 24 24"><g class="desk-node-icon__scan-frame"><path d="M3 7V5a2 2 0 0 1 2-2h2"></path><path d="M17 3h2a2 2 0 0 1 2 2v2"></path><path d="M21 17v2a2 2 0 0 1-2 2h-2"></path><path d="M7 21H5a2 2 0 0 1-2-2v-2"></path></g><g class="desk-node-icon__text-lines"><path d="M7 8h8"></path><path d="M7 12h10"></path><path d="M7 16h6"></path></g></svg>'
    },
    {
      type: 'layout',
      title: '排版节点',
      subtitle: '图文版面',
      icon: '<svg class="desk-node-icon desk-node-icon--layout" viewBox="0 0 24 24"><rect class="desk-node-icon__layout-frame" width="18" height="18" x="3" y="3" rx="2"></rect><g class="desk-node-icon__layout-panels"><path d="M3 9h18"></path><path d="M9 21V9"></path></g></svg>'
    }
  ];
  const TEXT_STYLE_PRESETS = [
    { id: 'raw', title: 'Raw', promptTemplate: '主体清晰，构图自然，保留真实质感，光影克制，细节干净。' },
    { id: 'real', title: '超写实', promptTemplate: 'photorealistic, 8k, highly detailed, sharp focus, cinematic lighting, photography, masterpiece' },
    { id: 'king_hu', title: '胡金铨', promptTemplate: 'Cinematic Wuxia Aesthetic (King Hu Style), Moon-white & Pale Cyan palette, high-class grey tones. Tyndall morning light piercing through heavy mist, golden backlight halo. Ancient temple gate, mossy stone steps, bamboo forest. Cold porcelain glass skin, jet black ink-like hair with wet dew texture. Ink wash painting negative space, film grain, wide shot, 1970s martial arts masterpiece.' },
    { id: 'shadow', title: '皮影戏风格', promptTemplate: 'Shadow-play Aesthetic (Ying Style), Teal and Ink scheme, low saturation, high contrast between deep blacks and wet highlights. Cold-toned porcelain skin, high slanted Duo-ma bun, ebony hairpin. Rembrandt lighting, cold side light & golden rim light. Minimalist Zen space, giant translucent rice paper screens, wet ink brushstrokes, rainy atmosphere. Cinnabar dot, Song-style layered silk gauze texture.' },
    { id: 'dunhuang', title: '敦煌', promptTemplate: 'Dunhuang Mural (Rock Color Aesthetic), Opulent Gold & Lapis Lazuli palette, high contrast warm shadows. Radiant Tang-style porcelain skin, double-loop Wang-xian bun, gold filigree hairpins. Rock color texture, weathered mural surface. Divine god rays in cavern, amber candlelight. Ancient grotto atmosphere, flying ribbons, golden clover huadian, epic religious solemnity.' },
    { id: 'candlelight', title: '烛光肖像', promptTemplate: 'Cinematic candlelight portrait: Sony A7R IV with 50mm f/1.2 lens, multiple white candles as natural light source, dramatic chiaroscuro lighting with strong side light contouring, deep layered shadows. Ultra-realistic digital art, photorealistic with Unreal Engine 5 CG cinematic rendering. Extremely detailed skin texture with visible pores, subtle sheen of sweat/oil on skin surface, realistic subsurface scattering (SSS) translucency. 8K ultra-high resolution, ray-traced lighting quality, hyper-detailed micro textures including knitted fabric fibers, velvet plush texture, light scattering on different materials. Classical, mysterious, elegant atmosphere with suppressed luxury, warm brown candlelight interwoven with deep purple and ash grey shadows.' },
    { id: '3d_info', title: '3D 信息图', promptTemplate: '3D infographic poster, C4D claymorphism style, vertical layout, centered composition, matte plastic and soft clay texture, soft diffuse lighting, no harsh highlights, 3D infographic aesthetic, pop art influence, soft glowing 3d icons, similar to Behance 3D illustrations and Apple skeuomorphic icons' },
    { id: 'sketchnote', title: '知识卡片', promptTemplate: '请根据以下输入内容，生成一张手绘涂鸦风格的读书笔记信息图，并严格遵循以下风格：1. 整体风格与媒介：采用充满活力的手绘涂鸦笔记 (Sketchnote) 风格，专业知识笔记的学霸风格，不要太卡通。黑色使用深棕、橙黄或海军蓝，轻微水彩进行填色，并搭配柔和的黑色或深棕色细线等勾勒轮廓。竖版 (3:4) 构图。2. 配色方案（关键）：整张图都应该是彩色的，采用明亮、清新、和谐的色彩组合（海军蓝#1E3A8A、浅蓝#60A5FA、金色#F59E0B、奶油色背景#FEFCE8）。背景应有淡淡纸张纹理的米色，或者直接留白，但画面主体必须是五彩斑斓的。颜色填充应模仿彩铅或水彩的质感，带有自然的笔触感，而不是均匀的数字平涂。3. 线条特征：所有轮廓线都必须是不完美、略带抖动的手绘线条，给人一种柔软、亲切的感觉。4. 字体风格：所有文字都必须是彩色的手写体，绝对不要使用任何电脑字体。标题和关键词使用加粗的、或带有简单边框的手写艺术字来突出。正文和注释使用清晰、自然的个人笔记手写体。5. 插图与图标：所有图形元素必须是充满色彩的、简单的涂鸦/简笔画（colorful doodle/stick figure）风格。使用手绘的彩色箭头、框线、项目符号和分割线来组织信息。6. 内容处理：信息精炼，通过关键词加粗、手绘框等方式突出重点。如有故事人物，用此风格的可爱彩色涂鸦形象替代。话语与输入内容保持一致。7. 绘制使用中文绘制成为完整的信息卡输出，尽可能使用 PINCH 的展示方式，将所有内容排版在一页，需要清晰可读，所有中文必须孤立文字图层处理，输出高分辨率 4k。输入内容：' }
  ];
  const CUSTOM_TEXT_STYLE_KEY = 'desktop_custom_text_style_presets_v1';
  let activeInteraction = null;
  let pendingUploadNodeId = 'input';
  let pendingFileMode = 'reference';
  let pendingImageNodeCenter = null;
  let pendingImageTargetNodeId = '';
  let contextMenuPoint = null;
  let contextMenuEl = null;
  let contextMenuConnectionSourceId = '';
  let suppressCanvasContextMenuUntil = 0;
  let imageEditorEl = null;
  let imageEditorCanvas = null;
  let activeImageEdit = null;
  let imageEditorThemeObserver = null;
  let externalTextStylePresets = [];
  let gptModelCatalog = null;
  let nodeGroupSequence = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function sanitizeTextNodeAlias(value) {
    return Array.from(String(value || ''))
      .filter(char => /[A-Za-z0-9\u3400-\u9FFF,_-]/u.test(char))
      .join('')
      .slice(0, TEXT_NODE_ALIAS_MAX_LENGTH);
  }

  function nextTextNodeAlias(excludeNodeId = '') {
    const used = new Set(Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node?.type === 'text' && node.id !== excludeNodeId)
      .map(node => sanitizeTextNodeAlias(node.alias))
      .filter(Boolean));
    let index = 1;
    while (used.has(`文本节点-${index}`)) index += 1;
    return `文本节点-${index}`;
  }

  function getTextNodeAlias(node) {
    return sanitizeTextNodeAlias(node?.alias) || nextTextNodeAlias(node?.id || '');
  }

  function textNodeAliasMeasure(value) {
    const units = Array.from(String(value || '')).reduce((total, char) => {
      return total + (/[\u3400-\u9FFF]/u.test(char) ? 2 : 1);
    }, 0);
    return Math.max(4, Math.min(42, units || 4));
  }

  function textNodeAliasStyle(alias) {
    return `--text-node-alias-ch: ${textNodeAliasMeasure(alias)}ch;`;
  }

  function updateTextNodeAliasMetrics(aliasInput) {
    const shell = aliasInput?.closest?.('.desk-text-node__alias');
    if (!shell) return;
    shell.style.setProperty('--text-node-alias-ch', `${textNodeAliasMeasure(aliasInput.value)}ch`);
  }

  function setTextNodeAliasEditing(shell, editing) {
    const aliasInput = shell?.querySelector?.('[data-text-node-alias]');
    const editButton = shell?.querySelector?.('[data-text-node-alias-edit]');
    if (!aliasInput || !editButton) return;
    shell.classList.toggle('is-editing', editing);
    editButton.dataset.aliasMode = editing ? 'apply' : 'edit';
    editButton.setAttribute('aria-label', editing ? '应用文本节点别名' : '编辑文本节点别名');
    editButton.title = editing ? '应用别名' : '编辑别名';
    if (editing) {
      aliasInput.dataset.aliasBeforeEdit = aliasInput.value;
      aliasInput.removeAttribute('readonly');
      aliasInput.removeAttribute('tabindex');
      requestAnimationFrame(() => {
        aliasInput.focus();
        aliasInput.select();
      });
      return;
    }
    aliasInput.setAttribute('readonly', '');
    aliasInput.setAttribute('tabindex', '-1');
    aliasInput.blur();
  }

  function commitTextNodeAliasInput(aliasInput) {
    const node = aliasInput?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    if (!nodeState) return '';
    const alias = sanitizeTextNodeAlias(aliasInput.value) || nextTextNodeAlias(nodeState.id);
    aliasInput.value = alias;
    aliasInput.dataset.aliasBeforeEdit = alias;
    nodeState.alias = alias;
    updateTextNodeAliasMetrics(aliasInput);
    DesktopState.saveSettings();
    notifyTextNodeListChange(nodeState.id);
    return alias;
  }

  function revertTextNodeAliasInput(aliasInput) {
    const node = aliasInput?.closest?.('.desk-node--text[data-node-id]');
    const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
    if (!nodeState) return;
    const alias = sanitizeTextNodeAlias(aliasInput.dataset.aliasBeforeEdit) || getTextNodeAlias(nodeState);
    aliasInput.value = alias;
    nodeState.alias = alias;
    updateTextNodeAliasMetrics(aliasInput);
    DesktopState.saveSettings();
    notifyTextNodeListChange(nodeState.id);
  }

  function ensureTextNodeAliases() {
    let changed = false;
    Object.values(DesktopState.state.canvas.nodes).forEach(node => {
      if (node?.type !== 'text') return;
      const alias = getTextNodeAlias(node);
      if (node.alias === alias) return;
      node.alias = alias;
      changed = true;
    });
    if (changed) DesktopState.saveSettings();
  }

  function listTextNodes() {
    return Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node?.type === 'text')
      .map(node => ({
        nodeId: node.id,
        type: 'text',
        alias: getTextNodeAlias(node),
        label: getTextNodeAlias(node),
        text: String(node.text || '')
      }));
  }

  function notifyTextNodeListChange(nodeId = '') {
    window.dispatchEvent(new CustomEvent('desktop:canvas-text-nodes-change', {
      detail: { nodeId, nodes: listTextNodes() }
    }));
  }

  function ratioOptionsHtml(selected = '9:16') {
    return ASPECT_RATIO_OPTIONS.map(ratio => `<option${ratio === selected ? ' selected' : ''}>${ratio}</option>`).join('');
  }

  function googleModelOptionsHtml(selected = DEFAULT_GOOGLE_MODEL) {
    const normalized = typeof DesktopState.normalizeGoogleModel === 'function'
      ? DesktopState.normalizeGoogleModel(selected, DEFAULT_GOOGLE_MODEL)
      : (String(selected || '').trim() || DEFAULT_GOOGLE_MODEL);
    return GOOGLE_MODEL_OPTIONS
      .map(item => `<option value="${escapeHtml(item.value)}"${item.value === normalized ? ' selected' : ''}>${escapeHtml(item.label)}</option>`)
      .join('');
  }

  function imageCountOptionsHtml(selected = 2) {
    const current = DesktopState.clamp(selected, 1, 8, 2);
    return Array.from({ length: 8 }, (_, index) => {
      const count = index + 1;
      return `<option value="${count}"${count === current ? ' selected' : ''}>${count}张</option>`;
    }).join('');
  }

  function optionListHtml(options, selected) {
    const selectedValue = String(selected ?? '');
    return options
      .map(item => `<option value="${escapeHtml(item.value)}"${String(item.value) === selectedValue ? ' selected' : ''}>${escapeHtml(item.label)}</option>`)
      .join('');
  }

  function fallbackGptModelOptions(route) {
    if (route === 'chatgpt_pool') {
      return [{ value: 'gpt-5-5', label: 'GPT-5.5' }];
    }
    if (route === 'third_party_image_api') {
      return [{ value: 'gpt-image-2', label: 'gpt-image-2' }];
    }
    return GPT_MAIN_MODEL_OPTIONS;
  }

  function gptRouteCatalog(route) {
    const normalized = DesktopState.normalizeGptProviderRoute(route, 'codex');
    return gptModelCatalog?.routes?.[normalized] || null;
  }

  function gptModelOptionsForRoute(route) {
    const catalog = gptRouteCatalog(route);
    if (catalog?.available === false) return [];
    const models = Array.isArray(catalog?.models) ? catalog.models : [];
    const options = models
      .filter(item => item?.image_generation !== false)
      .map(item => ({
        value: DesktopState.normalizeGptMainModel(item?.id, ''),
        label: String(item?.label || item?.id || '').trim()
      }))
      .filter(item => item.value && item.label);
    if (catalog) return options;
    return fallbackGptModelOptions(DesktopState.normalizeGptProviderRoute(route, 'codex'));
  }

  function gptModelCatalogEntry(route, model) {
    const models = gptRouteCatalog(route)?.models;
    if (!Array.isArray(models)) return null;
    return models.find(item => String(item?.id || '') === String(model || '')) || null;
  }

  function reasoningOption(value) {
    const normalized = String(value || '').trim().toLowerCase();
    const known = GPT_REASONING_OPTIONS.find(item => item.value === normalized);
    return known || (normalized ? { value: normalized, label: normalized } : null);
  }

  function gptReasoningOptionsForModel(route, model) {
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const catalog = gptRouteCatalog(normalizedRoute);
    if (!catalog) return normalizedRoute === 'codex' ? GPT_REASONING_OPTIONS : [];
    const entry = gptModelCatalogEntry(normalizedRoute, model);
    return (Array.isArray(entry?.reasoning_efforts) ? entry.reasoning_efforts : [])
      .map(reasoningOption)
      .filter(Boolean);
  }

  function selectedReasoningForModel(params, route, model, options) {
    const values = new Set(options.map(item => item.value));
    const current = DesktopState.normalizeReasoningEffort(params?.reasoningEffort, 'medium');
    const modelDefault = DesktopState.normalizeReasoningEffort(
      gptModelCatalogEntry(route, model)?.default_reasoning_effort,
      'medium'
    );
    return [current, modelDefault, 'medium', options[0]?.value]
      .find(value => value && values.has(value)) || options[0]?.value || 'none';
  }

  function updateGptRoutePresentation(node, route) {
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const catalog = gptRouteCatalog(normalizedRoute);
    const fallback = GPT_ROUTE_PRESENTATION[normalizedRoute] || GPT_ROUTE_PRESENTATION.codex;
    const modelLabel = normalizedRoute === 'third_party_image_api'
      ? String(catalog?.model_field_label || fallback.modelLabel)
      : fallback.modelLabel;
    const engineLabel = String(catalog?.image_engine?.label || catalog?.image_engine?.id || fallback.engineLabel);
    const label = node.querySelector('[data-gpt-model-field-label]');
    const engine = node.querySelector('[data-gpt-image-engine]');
    if (label) label.textContent = modelLabel;
    if (engine) {
      engine.textContent = engineLabel;
      engine.title = `生图引擎：${engineLabel}`;
    }
    node.dataset.gptModelRole = String(catalog?.model_role || '');
  }

  function applyGptReasoningToNode(node, route, model) {
    const select = node?.querySelector('[data-field="reasoningEffort"], #deskReasoningEffortSelect');
    const params = inputParamsForNode(node);
    if (!select || !params) return 'none';
    const options = gptReasoningOptionsForModel(route, model);
    const selected = selectedReasoningForModel(params, route, model, options);
    select.innerHTML = options.length
      ? optionListHtml(options, selected)
      : '<option value="none">不适用</option>';
    select.value = selected;
    select.disabled = !options.length;
    select.title = options.length ? '' : '当前线路不使用推理强度';
    params.reasoningEffort = selected;
    window.DesktopSelect?.refresh?.(select);
    return selected;
  }

  function selectedGptModelForRoute(params, route, options = gptModelOptionsForRoute(route)) {
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const values = new Set(options.map(item => item.value));
    const routeSelected = DesktopState.normalizeGptMainModel(params?.gptModelsByRoute?.[normalizedRoute], '');
    const current = DesktopState.normalizeGptMainModel(params?.gptMainModel, '');
    const routeDefault = DesktopState.normalizeGptMainModel(gptRouteCatalog(normalizedRoute)?.default_model, '');
    return [routeSelected, current, routeDefault, options[0]?.value]
      .find(value => value && values.has(value)) || options[0]?.value || '';
  }

  function inputParamsForNode(node) {
    if (!node) return null;
    if (node.dataset.nodeId === 'input') return DesktopState.state.params;
    const nodeState = DesktopState.state.canvas.nodes[node.dataset.nodeId];
    if (!nodeState || nodeState.type !== 'input') return null;
    nodeState.params = nodeState.params || {};
    return nodeState.params;
  }

  function applyGptModelRouteToNode(node, route, { rememberPrevious = true } = {}) {
    if (!node) return '';
    const normalizedRoute = DesktopState.normalizeGptProviderRoute(route, 'codex');
    const select = node.querySelector('[data-field="gptMainModel"], #deskGptMainModelSelect');
    const params = inputParamsForNode(node);
    if (!select || !params) return '';
    params.gptModelsByRoute = params.gptModelsByRoute && typeof params.gptModelsByRoute === 'object'
      ? { ...params.gptModelsByRoute }
      : {};
    const previousRoute = DesktopState.normalizeGptProviderRoute(select.dataset.modelRoute, '');
    if (rememberPrevious && previousRoute && previousRoute !== normalizedRoute && select.value) {
      params.gptModelsByRoute[previousRoute] = DesktopState.normalizeGptMainModel(select.value, params.gptModelsByRoute[previousRoute] || 'gpt-5.5');
    }
    const options = gptModelOptionsForRoute(normalizedRoute);
    const optionValues = new Set(options.map(item => item.value));
    const currentSelection = DesktopState.normalizeGptMainModel(select.value, '');
    const selected = previousRoute === normalizedRoute && optionValues.has(currentSelection)
      ? currentSelection
      : selectedGptModelForRoute(params, normalizedRoute, options);
    const catalog = gptRouteCatalog(normalizedRoute);
    select.innerHTML = options.length
      ? optionListHtml(options, selected)
      : '<option value="">无可用模型</option>';
    select.value = selected;
    select.dataset.modelRoute = normalizedRoute;
    select.disabled = !options.length || catalog?.available === false;
    select.title = String(catalog?.warning || '');
    params.gptMainModel = selected || '';
    if (selected) params.gptModelsByRoute[normalizedRoute] = selected;
    updateGptRoutePresentation(node, normalizedRoute);
    applyGptReasoningToNode(node, normalizedRoute, selected);
    window.DesktopSelect?.refresh?.(select);
    return selected;
  }

  function applyGptModelCatalog(payload = {}) {
    if (payload?.routes && typeof payload.routes === 'object') {
      gptModelCatalog = payload;
    }
    document.querySelectorAll('.desk-node--input[data-node-id]').forEach(node => {
      const route = node.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect')?.value || 'codex';
      applyGptModelRouteToNode(node, route, { rememberPrevious: false });
    });
    DesktopState.saveSettings();
    window.requestAnimationFrame(() => window.DesktopSelect?.refreshAll?.());
    return gptModelCatalog;
  }

  function ratioFromAspect(aspectRatio, fallback = '1:1') {
    const ratioValue = Number(aspectRatio || 1);
    if (!Number.isFinite(ratioValue) || ratioValue <= 0) return fallback;
    const ratioToNumber = ratio => {
      const [w, h] = String(ratio).split(':').map(Number);
      return w && h ? w / h : 1;
    };
    return ASPECT_RATIO_OPTIONS
      .map(ratio => ({ ratio, diff: Math.abs(ratioToNumber(ratio) - ratioValue) }))
      .sort((a, b) => a.diff - b.diff)[0]?.ratio || fallback;
  }

  function textStylePresetButtonsHtml() {
    return allTextStylePresets().map(item => `
      <button type="button" data-text-style-preset="${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.promptTemplate)}</span>
      </button>
    `).join('');
  }

  function loadCustomTextStylePresets() {
    try {
      const raw = window.localStorage?.getItem(CUSTOM_TEXT_STYLE_KEY);
      const parsed = JSON.parse(raw || '[]');
      return Array.isArray(parsed) ? parsed.filter(item => item?.id && item?.promptTemplate) : [];
    } catch (e) {
      return [];
    }
  }

  function saveCustomTextStylePresets(items) {
    try {
      window.localStorage?.setItem(CUSTOM_TEXT_STYLE_KEY, JSON.stringify(items || []));
    } catch (e) {}
  }

  function allTextStylePresets() {
    const seen = new Set();
    return [...TEXT_STYLE_PRESETS, ...externalTextStylePresets, ...loadCustomTextStylePresets()].filter(item => {
      if (!item?.id || seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  }

  function getTextStylePreset(presetId) {
    return allTextStylePresets().find(item => item.id === presetId) || null;
  }

  function textStyleTagHtml(presetId) {
    const preset = getTextStylePreset(presetId);
    if (!preset) return '';
    return `
      <button type="button" class="desk-text-style-tag" data-text-style-clear title="移除风格标签">
        <span>风格</span>
        <strong>${escapeHtml(preset.title)}</strong>
        <em aria-hidden="true">×</em>
      </button>
    `;
  }

  function updateProviderParamVisibility(root, provider = 'gpt') {
    const current = ['gpt', 'google', 'comfy'].includes(provider) ? provider : 'gpt';
    root?.querySelectorAll('[data-provider-param]').forEach(item => {
      const scopes = String(item.dataset.providerParam || '').split(/\s+/).filter(Boolean);
      item.hidden = scopes.length > 0 && !scopes.includes(current);
    });
  }

  function updateAllProviderParamVisibility() {
    document.querySelectorAll('.desk-node--input[data-node-id]').forEach(node => {
      const provider = node.dataset.nodeId === 'input'
        ? DesktopState.state.provider
        : getProviderFromNode(node);
      updateProviderParamVisibility(node, provider);
    });
  }

  function collectElements() {
    [
      'deskProviderSegment',
      'deskRatioSelect',
      'deskResolutionSelect',
      'deskModelSelect',
      'deskQualitySelect',
      'deskCountInput',
      'deskModerationSelect',
      'deskGptTaskTypeSelect',
      'deskGptProviderRouteSelect',
      'deskGptMainModelSelect',
      'deskReasoningEffortSelect',
      'deskPromptModeSelect',
      'deskBatchMode',
      'deskToggleInputBtn',
      'deskInputNode',
      'deskInputDrawer',
      'deskUploadDrop',
      'deskFileInput',
      'deskReferenceThumbs',
      'deskArchiveToggle',
      'deskTelegramToggle',
      'deskRunBtn',
      'deskImportBtn',
      'deskPromptClearBtn',
      'deskNewBtn',
      'deskConnectModeBtn',
      'deskNodeToolBtn',
      'deskNodePalette',
      'deskCanvasViewport',
      'deskCanvasWorld',
      'deskSelectionMarquee',
      'deskSelectionBounds',
      'deskSelectionCount',
      'deskSelectionGroupBtn',
      'deskSelectionToolbar',
      'deskSmartGuideX',
      'deskSmartGuideY',
      'deskLinkPath',
      'deskLinkMotion',
      'deskZoomOutBtn',
      'deskZoomInBtn',
      'deskZoomResetBtn',
      'deskZoomLabel',
      'deskZoomPresetMenu',
      'deskWorkflowDockToggle',
      'deskWorkflowDockPanel',
      'deskWorkflowSaveBtn',
      'deskWorkflowLoadBtn',
      'deskWorkflowFileInput',
      'deskMiniMapPinBtn',
      'deskMiniMap',
      'deskMiniMapWorld',
      'deskMiniMapViewport',
      'deskOutputNode'
    ].forEach(id => {
      els[id] = $(id);
    });
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function getNodeState(nodeId) {
    return DesktopState.state.canvas.nodes[nodeId];
  }

  function getNodeElement(nodeId) {
    return document.querySelector(`.desk-node[data-node-id="${CSS.escape(nodeId)}"]`);
  }

  function normalizeNodeGroupId(value) {
    const normalized = String(value || '').trim();
    return /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(normalized) ? normalized : '';
  }

  function normalizeNodeGroups(nodes = DesktopState.state.canvas.nodes) {
    const groups = new Map();
    let changed = false;
    Object.values(nodes || {}).forEach(node => {
      if (!node || typeof node !== 'object') return;
      const groupId = normalizeNodeGroupId(node.groupId);
      if (!groupId) {
        if (Object.prototype.hasOwnProperty.call(node, 'groupId')) {
          delete node.groupId;
          changed = true;
        }
        return;
      }
      if (node.groupId !== groupId) {
        node.groupId = groupId;
        changed = true;
      }
      groups.set(groupId, (groups.get(groupId) || 0) + 1);
    });
    Object.values(nodes || {}).forEach(node => {
      const groupId = normalizeNodeGroupId(node?.groupId);
      if (!groupId || (groups.get(groupId) || 0) >= 2) return;
      delete node.groupId;
      changed = true;
    });
    return changed;
  }

  function getNodeIdsInGroup(groupId, nodes = DesktopState.state.canvas.nodes) {
    const normalized = normalizeNodeGroupId(groupId);
    if (!normalized) return [];
    return Object.keys(nodes || {}).filter(nodeId => normalizeNodeGroupId(nodes[nodeId]?.groupId) === normalized);
  }

  function expandNodeIdsToGroups(nodeIds, nodes = DesktopState.state.canvas.nodes) {
    const expanded = [];
    const seen = new Set();
    const append = nodeId => {
      if (!nodes?.[nodeId] || seen.has(nodeId)) return;
      seen.add(nodeId);
      expanded.push(nodeId);
    };
    (nodeIds || []).forEach(nodeId => {
      if (!nodes?.[nodeId]) return;
      append(nodeId);
      getNodeIdsInGroup(nodes[nodeId]?.groupId, nodes).forEach(append);
    });
    return expanded;
  }

  function normalizeCanvasGroupsAndSelection() {
    const canvas = DesktopState.state.canvas;
    const groupsChanged = normalizeNodeGroups(canvas.nodes);
    const selected = Array.isArray(canvas.selectedNodeIds)
      ? canvas.selectedNodeIds
      : (canvas.selectedNodeId ? [canvas.selectedNodeId] : []);
    const expanded = expandNodeIdsToGroups(selected, canvas.nodes);
    const selectionChanged = expanded.length !== selected.length
      || expanded.some((nodeId, index) => nodeId !== selected[index]);
    canvas.selectedNodeIds = expanded;
    canvas.selectedNodeId = expanded[0] || '';
    return groupsChanged || selectionChanged;
  }

  function createNodeGroupId() {
    let groupId = '';
    do {
      nodeGroupSequence += 1;
      groupId = `group_${Date.now().toString(36)}_${nodeGroupSequence.toString(36)}`;
    } while (getNodeIdsInGroup(groupId).length);
    return groupId;
  }

  function getSelectionGroupState(nodeIds = getSelectedNodeIds()) {
    const selectedIds = [...new Set((nodeIds || []).filter(nodeId => DesktopState.state.canvas.nodes[nodeId]))];
    if (selectedIds.length < 2) return { grouped: false, groupId: '', memberIds: selectedIds };
    const groupId = normalizeNodeGroupId(DesktopState.state.canvas.nodes[selectedIds[0]]?.groupId);
    if (!groupId || selectedIds.some(nodeId => normalizeNodeGroupId(DesktopState.state.canvas.nodes[nodeId]?.groupId) !== groupId)) {
      return { grouped: false, groupId: '', memberIds: selectedIds };
    }
    const memberIds = getNodeIdsInGroup(groupId);
    const selected = new Set(selectedIds);
    const grouped = memberIds.length === selectedIds.length && memberIds.every(nodeId => selected.has(nodeId));
    return { grouped, groupId: grouped ? groupId : '', memberIds: selectedIds };
  }

  function getSelectedNodeIds() {
    const canvas = DesktopState.state.canvas;
    const selected = Array.isArray(canvas.selectedNodeIds) ? canvas.selectedNodeIds : (canvas.selectedNodeId ? [canvas.selectedNodeId] : []);
    return selected.filter(nodeId => !!DesktopState.state.canvas.nodes[nodeId]);
  }

  function getEditableKeyboardTarget(target) {
    return target?.closest?.('input, textarea, select, [contenteditable="true"]') || null;
  }

  function isEditableKeyboardTarget(target) {
    return !!getEditableKeyboardTarget(target);
  }

  function getCanvasNodeIdForElement(element) {
    const node = element?.closest?.('.desk-node[data-node-id]');
    return node?.dataset.nodeId || '';
  }

  function isEditingSelectedNode(target) {
    const editable = getEditableKeyboardTarget(target);
    if (!editable) return false;
    const editableNodeId = getCanvasNodeIdForElement(editable);
    if (!editableNodeId) return true;
    const selectedIds = getSelectedNodeIds();
    if (!selectedIds.length) return true;
    return selectedIds.includes(editableNodeId);
  }

  function blurEditableFocusOutsideSelection(selectedIds) {
    const activeEditable = getEditableKeyboardTarget(document.activeElement);
    if (!activeEditable) return;
    const activeNodeId = getCanvasNodeIdForElement(activeEditable);
    if (!activeNodeId) return;
    if (selectedIds.includes(activeNodeId)) return;
    activeEditable.blur?.();
  }

  function focusCanvasViewport() {
    if (!els.deskCanvasViewport) return;
    try {
      els.deskCanvasViewport.focus({ preventScroll: true });
    } catch (e) {
      els.deskCanvasViewport.focus();
    }
  }

  function nodeIdsForKeyboardDelete(event) {
    const selectedIds = getSelectedNodeIds();
    if (selectedIds.length) return selectedIds;
    const eventNode = event.target?.closest?.('.desk-node[data-node-id]');
    if (eventNode?.dataset.nodeId && DesktopState.state.canvas.nodes[eventNode.dataset.nodeId]) {
      return [eventNode.dataset.nodeId];
    }
    const focusedNode = document.activeElement?.closest?.('.desk-node[data-node-id]');
    if (focusedNode?.dataset.nodeId && DesktopState.state.canvas.nodes[focusedNode.dataset.nodeId]) {
      return [focusedNode.dataset.nodeId];
    }
    const selectedDomNode = document.querySelector('.desk-node.is-selected[data-node-id]');
    if (selectedDomNode?.dataset.nodeId && DesktopState.state.canvas.nodes[selectedDomNode.dataset.nodeId]) {
      return [selectedDomNode.dataset.nodeId];
    }
    return [];
  }

  function handleCanvasDeleteKeydown(event) {
    if (event.defaultPrevented) return;
    if (event.key !== 'Delete' && event.key !== 'Backspace') return;
    const imageEditorCanvas = getImageEditorCanvas();
    const imageEditModalOpen = Boolean(imageEditorEl?.classList.contains('is-open'));
    if (imageEditorCanvas && imageEditModalOpen) {
      const activeObject = imageEditorCanvas.getActiveObject?.();
      if (activeObject && activeObject.editRole !== 'baseImage' && !activeObject.isEditing) {
        event.preventDefault();
        event.stopPropagation();
        removeImageEditObjects(imageEditorCanvas.getActiveObjects?.() || [activeObject]);
        recordImageEditSnapshot('已删除对象');
        return;
      }
    }
    if (isEditingSelectedNode(event.target)) return;
    const nodeIds = nodeIdsForKeyboardDelete(event);
    if (!nodeIds.length) return;
    event.preventDefault();
    event.stopPropagation();
    getEditableKeyboardTarget(event.target)?.blur?.();
    nodeIds.forEach((nodeId, index) => removeNode(nodeId, {
      clearSelection: true,
      focusCanvas: index === nodeIds.length - 1
    }));
  }

  function getNodeReferenceStore() {
    if (!DesktopState.state.nodeReferenceImages || typeof DesktopState.state.nodeReferenceImages !== 'object') {
      DesktopState.state.nodeReferenceImages = {};
    }
    return DesktopState.state.nodeReferenceImages;
  }

  function getReferenceUrl(image) {
    return String(image?.url || image?.imageUrl || image?.imageData || image?.base64 || '').trim();
  }

  function isObjectUrl(url) {
    return String(url || '').startsWith('blob:');
  }

  function revokeReferenceUrl(image) {
    const url = getReferenceUrl(image);
    if (isObjectUrl(url)) URL.revokeObjectURL(url);
  }

  function referenceKey(image) {
    return String(image?.id || image?.assetId || image?.taskId || image?.imageUrl || image?.url || image?.base64 || image?.name || '').trim();
  }

  function setSelectedNodes(nodeIds, save = true) {
    const uniqueIds = expandNodeIdsToGroups(
      [...new Set((nodeIds || []).filter(nodeId => !!DesktopState.state.canvas.nodes[nodeId]))]
    );
    DesktopState.state.canvas.selectedNodeIds = uniqueIds;
    DesktopState.state.canvas.selectedNodeId = uniqueIds[0] || '';
    blurEditableFocusOutsideSelection(uniqueIds);
    applyNodeSelection();
    window.dispatchEvent(new CustomEvent('desktop:canvas-selection-change', {
      detail: {
        selectedNodeId: DesktopState.state.canvas.selectedNodeId,
        selectedNodeIds: [...uniqueIds],
        selectedTextNodeId: uniqueIds.find(nodeId => DesktopState.state.canvas.nodes[nodeId]?.type === 'text') || ''
      }
    }));
    if (save) DesktopState.saveSettings();
  }

  function getActiveTool() {
    return document.querySelector('.desk-rail__item.is-active[data-tool]')?.dataset.tool || 'select';
  }

  function isSelectToolActive() {
    return getActiveTool() === 'select';
  }

  function updateCanvasToolCursor(useSelectCursor = false) {
    els.deskCanvasViewport?.classList.toggle('is-select-tool', useSelectCursor && isSelectToolActive());
  }

  function applyCanvasTransform() {
    const canvas = DesktopState.state.canvas;
    if (els.deskCanvasViewport) {
      const gridSize = 20 * canvas.scale;
      const gridX = ((canvas.x % gridSize) + gridSize) % gridSize;
      const gridY = ((canvas.y % gridSize) + gridSize) % gridSize;
      els.deskCanvasViewport.style.setProperty('--canvas-grid-size', `${gridSize}px`);
      els.deskCanvasViewport.style.setProperty('--canvas-grid-x', `${gridX}px`);
      els.deskCanvasViewport.style.setProperty('--canvas-grid-y', `${gridY}px`);
    }
    if (els.deskCanvasWorld) {
      els.deskCanvasWorld.style.transform = `translate3d(${canvas.x}px, ${canvas.y}px, 0) scale(${canvas.scale})`;
    }
    if (els.deskZoomLabel) {
      els.deskZoomLabel.textContent = `${Math.round(canvas.scale * 100)}%`;
    }
    updateZoomPresetButtons();
    renderMiniMap();
    updateSelectionToolbar();
    updateInputProgressOverlay();
  }

  function applyNodeLayout(nodeId) {
    const node = getNodeElement(nodeId);
    const nodeState = getNodeState(nodeId);
    if (!node || !nodeState) return;
    if (nodeState.type === 'input') {
      nodeState.width = LOCKED_INPUT_NODE_WIDTH;
      nodeState.height = LOCKED_INPUT_NODE_HEIGHT;
    }
    if (nodeState.type === 'file_output') {
      nodeState.width = DEFAULT_FILE_OUTPUT_NODE_WIDTH;
      nodeState.height = DEFAULT_FILE_OUTPUT_NODE_HEIGHT;
    }
    if (nodeState.type === 'upscale') {
      nodeState.width = DEFAULT_UPSCALE_NODE_WIDTH;
      nodeState.height = DEFAULT_UPSCALE_NODE_HEIGHT;
    }
    node.style.left = `${nodeState.x}px`;
    node.style.top = `${nodeState.y}px`;
    node.style.width = `${nodeState.width}px`;
    node.style.height = `${nodeState.height}px`;
    renderMiniMap();
    updateSelectionToolbar();
    if (nodeState.type === 'input') updateInputProgressOverlay();
  }

  function updateInputProgressOverlay(nodeId = '') {
    const overlay = document.getElementById('deskProgressFloat');
    if (!overlay) return;
    const targetNodeId = nodeId || overlay.dataset.nodeId || 'input';
    const node = getNodeState(targetNodeId);
    if (!node || node.type !== 'input') return;
    overlay.dataset.nodeId = targetNodeId;
    overlay.style.left = `${node.x}px`;
    overlay.style.top = `${node.y + node.height + 2}px`;
    overlay.style.width = `${node.width}px`;
  }

  function applyAllNodeLayouts() {
    ensureGraphDom();
    updateAllProviderParamVisibility();
    Object.keys(DesktopState.state.canvas.nodes).forEach(applyNodeLayout);
    Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node.type === 'input')
      .forEach(node => renderNodeReferenceThumbs(node.id));
    Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node.type === 'upscale')
      .forEach(node => refreshUpscaleNodeMode(node.id));
    applyNodeSelection();
    updateLinkPath();
    updateInputProgressOverlay();
  }

  function ensureDefaultModelOutputState() {
    if (!DesktopState.state.outputs || typeof DesktopState.state.outputs !== 'object') {
      DesktopState.state.outputs = {};
    }
    if (!DesktopState.state.outputs.input) {
      DesktopState.state.outputs.input = {
        status: 'idle',
        stage: '',
        progressText: '',
        progress: 0,
        files: [],
        imagePaths: [],
        primaryFile: '',
        primaryImagePath: '',
        type: 'gpt',
        error: '',
        taskId: '',
        fileManifest: null,
        selectedFiles: [],
        selectionInitialized: false
      };
    }
  }

  function migrateResultNodesToModelOutputs() {
    ensureDefaultModelOutputState();
    const nodes = DesktopState.state.canvas.nodes || {};
    const edges = Array.isArray(DesktopState.state.canvas.edges) ? DesktopState.state.canvas.edges : [];
    const outputIds = Object.values(nodes)
      .filter(node => node?.type === 'output')
      .map(node => node.id);
    if (!outputIds.length && !nodes.output) return false;

    const outputSet = new Set(outputIds);
    let changed = false;
    const nextEdges = [];
    const existingPairs = new Set();
    edges.forEach(edge => {
      const from = nodes[edge.from];
      const to = nodes[edge.to];
      if (from?.type === 'input' && outputSet.has(edge.to)) {
        changed = true;
        return;
      }
      if (outputSet.has(edge.from) && to?.type === 'image') {
        const sourceInput = edges.find(item => item.to === edge.from && nodes[item.from]?.type === 'input')?.from || 'input';
        if (nodes[sourceInput]?.type === 'input') {
          const key = `${sourceInput}->${edge.to}`;
          if (!existingPairs.has(key)) {
            nextEdges.push({
              id: `${sourceInput}_${edge.to}_${Date.now()}_${nextEdges.length}`,
              from: sourceInput,
              to: edge.to,
              outputSlot: edge.outputSlot
            });
            existingPairs.add(key);
          }
        }
        changed = true;
        return;
      }
      if (outputSet.has(edge.from) || outputSet.has(edge.to)) {
        changed = true;
        return;
      }
      const key = `${edge.from}->${edge.to}`;
      if (!existingPairs.has(key)) {
        nextEdges.push(edge);
        existingPairs.add(key);
      }
    });

    outputIds.forEach(outputId => {
      const outputState = DesktopState.state.outputs?.[outputId];
      if (outputState && outputId === 'output') {
        DesktopState.state.outputs.input = {
          ...DesktopState.state.outputs.input,
          ...outputState
        };
      }
      delete nodes[outputId];
      delete DesktopState.state.outputs[outputId];
      changed = true;
    });

    DesktopState.state.canvas.edges = nextEdges;
    if (DesktopState.state.canvas.selectedNodeId && !nodes[DesktopState.state.canvas.selectedNodeId]) {
      DesktopState.state.canvas.selectedNodeId = '';
      DesktopState.state.canvas.selectedNodeIds = [];
    }
    if (changed) DesktopState.saveSettings();
    return changed;
  }

  function migrateLegacyPromptDraftToTextNode() {
    const prompt = String(DesktopState.state.prompt || '').trim();
    if (!prompt || !DesktopState.state.canvas.nodes.input) return false;
    const hasPromptTextNode = getConnectedTextNodes('input')
      .some(node => String(node.text || '').trim() === prompt);
    if (!hasPromptTextNode) {
      setPromptTextForInputNode('input', prompt, { quiet: true });
    }
    DesktopState.state.prompt = '';
    DesktopState.saveDraft();
    DesktopState.saveSettings();
    return true;
  }

  function setNodePaletteOpen(open) {
    els.deskNodePalette?.classList.toggle('is-open', !!open);
    els.deskNodeToolBtn?.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function nodeMenuButtonHtml(item) {
    return `
      <button type="button" data-add-node="${escapeHtml(item.type)}">
        <span class="desk-node-palette__icon" aria-hidden="true">${item.icon}</span>
        <span>
          <strong>${escapeHtml(item.title)}</strong>
          <em>${escapeHtml(item.subtitle)}</em>
        </span>
      </button>
    `;
  }

  function getConnectableNodeMenuItems(fromNodeId) {
    const fromType = DesktopState.state.canvas.nodes[fromNodeId]?.type;
    const targetTypes = fromType === 'input'
      ? ['image', 'file_output', 'upscale']
      : (fromType === 'output'
        ? ['image']
        : (fromType === 'image'
          ? ['input', 'layout', 'pose', 'upscale']
          : (fromType === 'upscale'
            ? ['image']
            : ((fromType === 'layout' || fromType === 'pose') ? ['input', 'upscale'] : (fromType === 'text' ? ['input'] : [])))));
    return NODE_MENU_ITEMS.filter(item => targetTypes.includes(item.type));
  }

  function renderContextMenuItems(items, title = '') {
    const menu = ensureContextMenu();
    const safeItems = items?.length ? items : NODE_MENU_ITEMS;
    menu.innerHTML = `${title ? `<div class="desk-node-context-menu__title">${escapeHtml(title)}</div>` : ''}${safeItems.map(nodeMenuButtonHtml).join('')}`;
    menu.querySelectorAll('[data-add-node]').forEach(button => {
      button.draggable = false;
    });
  }

  function ensureContextMenu() {
    if (contextMenuEl) return contextMenuEl;
    contextMenuEl = document.createElement('div');
    contextMenuEl.id = 'deskNodeContextMenu';
    contextMenuEl.className = 'desk-node-palette desk-node-context-menu desk-glass';
    contextMenuEl.setAttribute('aria-label', '添加节点');
    document.body.appendChild(contextMenuEl);
    renderContextMenuItems(NODE_MENU_ITEMS);
    contextMenuEl.addEventListener('click', event => {
      const button = event.target.closest('[data-add-node]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const nodeId = addNodeFromMenu(button.dataset.addNode || 'input', contextMenuPoint || getViewportCenterWorldPoint());
      if (contextMenuConnectionSourceId) {
        connectNodes(contextMenuConnectionSourceId, nodeId);
      }
      hideContextMenu();
    });
    return contextMenuEl;
  }

  function hideContextMenu() {
    contextMenuEl?.classList.remove('is-open');
    contextMenuPoint = null;
    contextMenuConnectionSourceId = '';
  }

  function openContextMenu(event, options = {}) {
    const menu = ensureContextMenu();
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    if (!rect) return;
    contextMenuConnectionSourceId = options.connectionSourceId || '';
    contextMenuPoint = screenToWorld(event.clientX, event.clientY);
    const items = contextMenuConnectionSourceId ? getConnectableNodeMenuItems(contextMenuConnectionSourceId) : NODE_MENU_ITEMS;
    renderContextMenuItems(items, options.title || '');
    menu.classList.add('is-open');
    const menuWidth = menu.offsetWidth || 168;
    const menuHeight = menu.offsetHeight || 260;
    const x = Math.min(window.innerWidth - menuWidth - 10, Math.max(10, event.clientX + 6));
    const y = Math.min(window.innerHeight - menuHeight - 10, Math.max(10, event.clientY + 6));
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
  }

  function selectNode(nodeId) {
    if (nodeId && !DesktopState.state.canvas.nodes[nodeId]) return;
    setSelectedNodes(nodeId ? [nodeId] : []);
  }

  function getPromptTargetInfo(nodeId = '') {
    const requestedId = typeof nodeId === 'string' ? nodeId : String(nodeId?.nodeId || '');
    const selectedId = requestedId || DesktopState.state.canvas.selectedNodeId || '';
    const selectedNode = DesktopState.state.canvas.nodes[selectedId];
    if (selectedNode?.type === 'text') {
      const alias = getTextNodeAlias(selectedNode);
      return { nodeId: selectedId, type: 'text', alias, label: alias };
    }
    if (selectedNode) {
      return { nodeId: selectedId, type: selectedNode.type || '', label: '请选择文本节点', inactive: true };
    }
    return { nodeId: '', type: '', label: '未绑定文本节点', inactive: true };
  }

  function getPromptTargetText(options = {}) {
    const target = options.target || getPromptTargetInfo(options.nodeId || options);
    if (target.type === 'text') {
      return DesktopState.state.canvas.nodes[target.nodeId]?.text || '';
    }
    return '';
  }

  function fillPromptTarget(text, options = {}) {
    const target = options.target || getPromptTargetInfo(options.nodeId || '');
    const next = String(text || '');
    if (target.type === 'text') {
      const node = getNodeElement(target.nodeId);
      const nodeState = DesktopState.state.canvas.nodes[target.nodeId];
      if (!node || !nodeState) throw new Error('文本节点不存在');
      setTextNodeValue(node, nodeState, next);
      selectNode(target.nodeId);
      return target;
    }
    throw new Error('请先选择文本节点');
  }

  function fillNearestInputPrompt(text) {
    const next = String(text || '');
    const firstInput = Object.values(DesktopState.state.canvas.nodes).find(node => node.type === 'input');
    if (!firstInput) throw new Error('画布里没有模型节点');
    setPromptTextForInputNode(firstInput.id, next);
    if (firstInput.id === 'input') DesktopState.state.prompt = '';
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    selectNode(firstInput.id);
    return { nodeId: firstInput.id, type: 'input', label: '模型节点' };
  }

  function createTextNodeWithText(text, worldPoint = null) {
    const id = addNode('text', worldPoint || getViewportCenterWorldPoint(0, 120));
    const node = getNodeElement(id);
    const nodeState = DesktopState.state.canvas.nodes[id];
    if (node && nodeState) setTextNodeValue(node, nodeState, text);
    selectNode(id);
    return id;
  }

  function findConnectedTextNodeId(inputNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .find(edge => edge.to === inputNodeId && DesktopState.state.canvas.nodes[edge.from]?.type === 'text')
      ?.from || '';
  }

  function setPromptTextForInputNode(inputNodeId, text, options = {}) {
    const inputNode = DesktopState.state.canvas.nodes[inputNodeId];
    if (!inputNode || inputNode.type !== 'input') throw new Error('模型节点不存在');
    const next = String(text || '');
    const connectedTextId = findConnectedTextNodeId(inputNodeId);
    if (connectedTextId) {
      const node = getNodeElement(connectedTextId);
      const nodeState = DesktopState.state.canvas.nodes[connectedTextId];
      if (node && nodeState) {
        setTextNodeValue(node, nodeState, next);
        return connectedTextId;
      }
    }
    const textNodeId = createTextNodeWithText(next, {
      x: inputNode.x - 220,
      y: inputNode.y + Math.min(160, Math.max(70, (inputNode.height || 360) * 0.38))
    });
    connectNodes(textNodeId, inputNodeId, { quiet: !!options.quiet });
    return textNodeId;
  }

  function getTextStylePresets() {
    return allTextStylePresets().map(item => ({ ...item }));
  }

  function createTextStylePreset(title, promptTemplate) {
    const cleanTitle = String(title || '').trim() || '自定义风格';
    const cleanTemplate = String(promptTemplate || '').trim();
    if (!cleanTemplate) throw new Error('风格内容为空');
    const now = Date.now();
    const item = {
      id: `custom_${now}`,
      title: cleanTitle.slice(0, 24),
      promptTemplate: cleanTemplate,
      custom: true,
      createdAt: now,
      updatedAt: now
    };
    const custom = loadCustomTextStylePresets();
    custom.push(item);
    saveCustomTextStylePresets(custom.slice(-30));
    document.querySelectorAll('[data-text-style-menu]').forEach(menu => {
      menu.innerHTML = textStylePresetButtonsHtml();
    });
    return item;
  }

  function registerTextStylePresets(items = []) {
    externalTextStylePresets = (Array.isArray(items) ? items : [])
      .map(item => ({
        id: String(item.id || '').trim(),
        title: String(item.title || item.name || '').trim(),
        promptTemplate: String(item.promptTemplate || item.prompt_style || '').trim(),
        description: String(item.description || '').trim(),
        positiveStyle: String(item.positive_style || '').trim(),
        avoid: String(item.avoid || '').trim(),
        bestFor: String(item.best_for || '').trim(),
        external: true
      }))
      .filter(item => item.id && item.title && item.promptTemplate);
    document.querySelectorAll('[data-text-style-menu]').forEach(menu => {
      menu.innerHTML = textStylePresetButtonsHtml();
    });
    return getTextStylePresets();
  }

  function applyTextStylePresetToTarget(presetId, options = {}) {
    const target = options.target || getPromptTargetInfo(options.nodeId || '');
    if (target.type !== 'text' || !target.nodeId) throw new Error('请先选择文本节点');
    const node = getNodeElement(target.nodeId);
    const nodeState = DesktopState.state.canvas.nodes[target.nodeId];
    if (!node || !nodeState) throw new Error('文本节点不存在');
    const preset = setTextNodeStyle(node, nodeState, presetId || '');
    if (preset) {
      DesktopResults.showTransientMessage(`已应用「${preset.title}」风格到文本节点。`);
    } else {
      DesktopResults.showTransientMessage('已移除文本节点风格。');
    }
    return preset;
  }

  function applyNodeSelection() {
    const selectedIds = getSelectedNodeIds();
    const selected = new Set(selectedIds);
    document.querySelectorAll('.desk-node[data-node-id]').forEach(node => {
      const isSelected = selected.has(node.dataset.nodeId);
      const groupId = normalizeNodeGroupId(DesktopState.state.canvas.nodes[node.dataset.nodeId]?.groupId);
      node.classList.toggle('is-selected', isSelected);
      node.classList.toggle('is-grouped', Boolean(groupId));
      if (groupId) node.dataset.nodeGroupId = groupId;
      else delete node.dataset.nodeGroupId;
      if (!isSelected && node.classList.contains('desk-node--text')) {
        setTextStyleMenuOpen(node, false);
      }
      if (node.classList.contains('desk-node--input')) {
        const drawer = node.querySelector('.desk-node__drawer');
        if (drawer) drawer.style.display = 'grid';
      }
    });
    updateSelectionToolbar();
    requestAnimationFrame(updateLinkPath);
  }

  function getAnchor(nodeId, side) {
    const node = getNodeState(nodeId);
    if (!node) return { x: 0, y: 0 };
    const el = getNodeElement(nodeId);
    const width = el?.offsetWidth || node.width;
    const height = el?.offsetHeight || node.height;
    return {
      x: side === 'right' ? node.x + width - PORT_RADIUS - 8 : node.x + PORT_RADIUS + 8,
      y: node.y + height * 0.5
    };
  }

  function updateLinkPath() {
    const svg = document.querySelector('.desk-link-layer');
    if (!svg) return;
    svg.setAttribute('viewBox', LINK_VIEWBOX);
    const edges = DesktopState.state.canvas.edges || [];
    const selectedNodeId = DesktopState.state.canvas.selectedNodeId || '';
    svg.innerHTML = edges.map((edge, index) => {
      const from = getAnchor(edge.from, 'right');
      const to = getAnchor(edge.to, 'left');
      const d = makeCurvePath(from, to);
      const isRelated = selectedNodeId && (edge.from === selectedNodeId || edge.to === selectedNodeId);
      const relatedClass = isRelated ? ' is-related' : '';
      return `
        <path class="desk-link-path${relatedClass}" data-edge-id="${edge.id}" d="${d}"></path>
        <circle class="desk-link-pulse${relatedClass}" r="5">
          <animateMotion dur="${2.4 + index * 0.2}s" repeatCount="indefinite" path="${d}"></animateMotion>
        </circle>
      `;
    }).join('');
    renderMiniMap();
  }

  function getNodeBounds(nodeState) {
    const el = getNodeElement(nodeState.id);
    return {
      x: nodeState.x,
      y: nodeState.y,
      width: el?.offsetWidth || nodeState.width,
      height: el?.offsetHeight || nodeState.height
    };
  }

  function getNodeBoundsById(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    return node ? getNodeBounds(node) : null;
  }

  function getBoundsFromRects(rects) {
    if (!rects.length) return null;
    const left = Math.min(...rects.map(rect => rect.x));
    const top = Math.min(...rects.map(rect => rect.y));
    const right = Math.max(...rects.map(rect => rect.x + rect.width));
    const bottom = Math.max(...rects.map(rect => rect.y + rect.height));
    return {
      x: left,
      y: top,
      width: right - left,
      height: bottom - top,
      right,
      bottom,
      centerX: left + (right - left) / 2,
      centerY: top + (bottom - top) / 2
    };
  }

  function getBoundsForNodeIds(nodeIds) {
    return getBoundsFromRects((nodeIds || []).map(getNodeBoundsById).filter(Boolean));
  }

  function getSelectionUnits(nodeIds = getSelectedNodeIds()) {
    const units = [];
    const byKey = new Map();
    (nodeIds || []).forEach(nodeId => {
      const node = DesktopState.state.canvas.nodes[nodeId];
      if (!node) return;
      const groupId = normalizeNodeGroupId(node.groupId);
      const key = groupId ? `group:${groupId}` : `node:${nodeId}`;
      let unit = byKey.get(key);
      if (!unit) {
        unit = { key, groupId, nodeIds: [] };
        byKey.set(key, unit);
        units.push(unit);
      }
      unit.nodeIds.push(nodeId);
    });
    return units.map(unit => ({
      ...unit,
      bounds: getBoundsForNodeIds(unit.nodeIds)
    })).filter(unit => unit.bounds);
  }

  function moveSelectionUnit(unit, dx, dy) {
    unit.nodeIds.forEach(nodeId => {
      const node = DesktopState.state.canvas.nodes[nodeId];
      if (!node) return;
      node.x += dx;
      node.y += dy;
      applyNodeLayout(nodeId);
    });
    unit.bounds = {
      ...unit.bounds,
      x: unit.bounds.x + dx,
      y: unit.bounds.y + dy,
      right: unit.bounds.right + dx,
      bottom: unit.bounds.bottom + dy,
      centerX: unit.bounds.centerX + dx,
      centerY: unit.bounds.centerY + dy
    };
  }

  function selectionGroupShortcutLabel() {
    return IS_MAC_PLATFORM ? 'Command+G' : 'Ctrl+G';
  }

  function worldRectToCanvasRect(rect) {
    const canvas = DesktopState.state.canvas;
    return {
      left: canvas.x + rect.x * canvas.scale,
      top: canvas.y + rect.y * canvas.scale,
      width: rect.width * canvas.scale,
      height: rect.height * canvas.scale
    };
  }

  function updateSelectionToolbar() {
    if (!els.deskSelectionToolbar) return;
    const selectedIds = getSelectedNodeIds();
    if (selectedIds.length < 2) {
      els.deskSelectionToolbar.classList.remove('is-active');
      els.deskSelectionBounds?.classList.remove('is-active', 'is-grouped');
      return;
    }
    const bounds = getBoundsForNodeIds(selectedIds);
    if (!bounds) return;
    const groupState = getSelectionGroupState(selectedIds);
    const units = getSelectionUnits(selectedIds);
    const rect = worldRectToCanvasRect(bounds);
    if (els.deskSelectionBounds) {
      els.deskSelectionBounds.style.left = `${rect.left}px`;
      els.deskSelectionBounds.style.top = `${rect.top}px`;
      els.deskSelectionBounds.style.width = `${rect.width}px`;
      els.deskSelectionBounds.style.height = `${rect.height}px`;
      els.deskSelectionBounds.classList.add('is-active');
      els.deskSelectionBounds.classList.toggle('is-grouped', groupState.grouped);
    }
    if (els.deskSelectionCount) {
      els.deskSelectionCount.textContent = `${selectedIds.length} 个节点`;
    }
    if (els.deskSelectionGroupBtn) {
      const label = groupState.grouped ? '解除群组' : '群组';
      const title = groupState.grouped
        ? `解除选中节点的群组 (${selectionGroupShortcutLabel()})`
        : `将选中的节点设为群组 (${selectionGroupShortcutLabel()})`;
      els.deskSelectionGroupBtn.textContent = label;
      els.deskSelectionGroupBtn.dataset.mode = groupState.grouped ? 'ungroup' : 'group';
      els.deskSelectionGroupBtn.setAttribute('aria-label', title);
      els.deskSelectionGroupBtn.title = title;
    }
    els.deskSelectionToolbar.querySelectorAll('[data-align]').forEach(button => {
      const minimumUnits = String(button.dataset.align || '').startsWith('distribute-') ? 3 : 2;
      button.disabled = units.length < minimumUnits;
    });
    els.deskSelectionToolbar.style.left = `${Math.max(8, rect.left)}px`;
    els.deskSelectionToolbar.style.top = `${Math.max(8, rect.top - 42)}px`;
    els.deskSelectionToolbar.classList.add('is-active');
  }

  function renderMarquee(worldRect) {
    if (!els.deskSelectionMarquee) return;
    const rect = worldRectToCanvasRect(worldRect);
    els.deskSelectionMarquee.style.left = `${rect.left}px`;
    els.deskSelectionMarquee.style.top = `${rect.top}px`;
    els.deskSelectionMarquee.style.width = `${rect.width}px`;
    els.deskSelectionMarquee.style.height = `${rect.height}px`;
    els.deskSelectionMarquee.classList.add('is-active');
  }

  function hideMarquee() {
    els.deskSelectionMarquee?.classList.remove('is-active');
  }

  function hideSmartGuides() {
    els.deskSmartGuideX?.classList.remove('is-active');
    els.deskSmartGuideY?.classList.remove('is-active');
  }

  function applySelectionLayout() {
    getSelectedNodeIds().forEach(applyNodeLayout);
    updateLinkPath();
    updateSelectionToolbar();
    DesktopState.saveSettings();
  }

  function toggleSelectionGroup() {
    const selectedIds = getSelectedNodeIds();
    if (selectedIds.length < 2) return false;
    const groupState = getSelectionGroupState(selectedIds);
    if (groupState.grouped) {
      selectedIds.forEach(nodeId => {
        delete DesktopState.state.canvas.nodes[nodeId].groupId;
      });
      setSelectedNodes(selectedIds, false);
      DesktopState.saveSettings();
      DesktopResults.showTransientMessage('已解除节点群组。');
      return true;
    }

    const groupId = createNodeGroupId();
    selectedIds.forEach(nodeId => {
      DesktopState.state.canvas.nodes[nodeId].groupId = groupId;
    });
    setSelectedNodes(selectedIds, false);
    DesktopState.saveSettings();
    DesktopResults.showTransientMessage(`已将 ${selectedIds.length} 个节点设为群组。`);
    return true;
  }

  function alignSelection(action) {
    const selectedIds = getSelectedNodeIds();
    if (selectedIds.length < 2) return;
    const bounds = getBoundsForNodeIds(selectedIds);
    if (!bounds) return;
    const units = getSelectionUnits(selectedIds);
    if (units.length < 2) return;

    if (action === 'left') units.forEach(unit => moveSelectionUnit(unit, bounds.x - unit.bounds.x, 0));
    if (action === 'hcenter') units.forEach(unit => moveSelectionUnit(unit, bounds.centerX - unit.bounds.centerX, 0));
    if (action === 'right') units.forEach(unit => moveSelectionUnit(unit, bounds.right - unit.bounds.right, 0));
    if (action === 'top') units.forEach(unit => moveSelectionUnit(unit, 0, bounds.y - unit.bounds.y));
    if (action === 'vcenter') units.forEach(unit => moveSelectionUnit(unit, 0, bounds.centerY - unit.bounds.centerY));
    if (action === 'bottom') units.forEach(unit => moveSelectionUnit(unit, 0, bounds.bottom - unit.bounds.bottom));

    if (action === 'distribute-x' && units.length >= 3) {
      const ordered = [...units].sort((a, b) => a.bounds.x - b.bounds.x);
      const totalWidth = ordered.reduce((sum, unit) => sum + unit.bounds.width, 0);
      const gap = (bounds.width - totalWidth) / Math.max(1, ordered.length - 1);
      let x = bounds.x;
      ordered.forEach(unit => {
        moveSelectionUnit(unit, x - unit.bounds.x, 0);
        x += unit.bounds.width + gap;
      });
    }

    if (action === 'distribute-y' && units.length >= 3) {
      const ordered = [...units].sort((a, b) => a.bounds.y - b.bounds.y);
      const totalHeight = ordered.reduce((sum, unit) => sum + unit.bounds.height, 0);
      const gap = (bounds.height - totalHeight) / Math.max(1, ordered.length - 1);
      let y = bounds.y;
      ordered.forEach(unit => {
        moveSelectionUnit(unit, 0, y - unit.bounds.y);
        y += unit.bounds.height + gap;
      });
    }

    applySelectionLayout();
  }

  function showSmartGuides(guides) {
    const canvas = DesktopState.state.canvas;
    if (els.deskSmartGuideX) {
      if (Number.isFinite(guides?.x)) {
        els.deskSmartGuideX.style.left = `${canvas.x + guides.x * canvas.scale}px`;
        els.deskSmartGuideX.classList.add('is-active');
      } else {
        els.deskSmartGuideX.classList.remove('is-active');
      }
    }
    if (els.deskSmartGuideY) {
      if (Number.isFinite(guides?.y)) {
        els.deskSmartGuideY.style.top = `${canvas.y + guides.y * canvas.scale}px`;
        els.deskSmartGuideY.classList.add('is-active');
      } else {
        els.deskSmartGuideY.classList.remove('is-active');
      }
    }
  }

  function renderMiniMap() {
    if (!els.deskMiniMap || !els.deskMiniMapWorld || !els.deskMiniMapViewport || !els.deskCanvasViewport) return;
    const nodes = Object.values(DesktopState.state.canvas.nodes || {});
    const canvas = DesktopState.state.canvas;
    const viewportRect = els.deskCanvasViewport.getBoundingClientRect();
    const mapWidth = els.deskMiniMap.clientWidth || 156;
    const mapHeight = els.deskMiniMap.clientHeight || 92;
    const viewportWorld = {
      x: -canvas.x / canvas.scale,
      y: -canvas.y / canvas.scale,
      width: viewportRect.width / canvas.scale,
      height: viewportRect.height / canvas.scale
    };
    const bounds = nodes.map(getNodeBounds);
    const minX = Math.min(viewportWorld.x, ...bounds.map(item => item.x), 0) - 140;
    const minY = Math.min(viewportWorld.y, ...bounds.map(item => item.y), 0) - 120;
    const maxX = Math.max(viewportWorld.x + viewportWorld.width, ...bounds.map(item => item.x + item.width), WORLD_WIDTH) + 140;
    const maxY = Math.max(viewportWorld.y + viewportWorld.height, ...bounds.map(item => item.y + item.height), WORLD_HEIGHT) + 120;
    const worldWidth = Math.max(1, maxX - minX);
    const worldHeight = Math.max(1, maxY - minY);
    const mapScale = Math.min(mapWidth / worldWidth, mapHeight / worldHeight);
    const offsetX = (mapWidth - worldWidth * mapScale) / 2;
    const offsetY = (mapHeight - worldHeight * mapScale) / 2;

    const toMapRect = rect => ({
      left: offsetX + (rect.x - minX) * mapScale,
      top: offsetY + (rect.y - minY) * mapScale,
      width: Math.max(4, rect.width * mapScale),
      height: Math.max(3, rect.height * mapScale)
    });

    els.deskMiniMapWorld.innerHTML = nodes.map(node => {
      const rect = toMapRect(getNodeBounds(node));
      const typeClass = node.type === 'output'
        ? 'is-output'
        : (node.type === 'file_output' ? 'is-output' : (node.type === 'image' ? 'is-image' : (node.type === 'pose' ? 'is-pose' : (node.type === 'text' ? 'is-text' : 'is-input'))));
      return `<span class="desk-minimap__node ${typeClass}" style="left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px"></span>`;
    }).join('');

    const viewport = toMapRect(viewportWorld);
    els.deskMiniMapViewport.style.left = `${viewport.left}px`;
    els.deskMiniMapViewport.style.top = `${viewport.top}px`;
    els.deskMiniMapViewport.style.width = `${Math.max(12, viewport.width)}px`;
    els.deskMiniMapViewport.style.height = `${Math.max(10, viewport.height)}px`;
  }

  function cssPxValue(element, propertyName, fallback = 0) {
    if (!element || !window.getComputedStyle) return fallback;
    const value = window.getComputedStyle(element).getPropertyValue(propertyName);
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function getMiniMapTargetHeight(controls, pinned) {
    if (!controls) return 0;
    const controlsStyle = window.getComputedStyle?.(controls);
    const row = controls.querySelector('.desk-zoom-row');
    const rowHeight = row?.getBoundingClientRect?.().height || 0;
    const padding = cssPxValue(controls, 'padding-top') + cssPxValue(controls, 'padding-bottom');
    const border = cssPxValue(controls, 'border-top-width') + cssPxValue(controls, 'border-bottom-width');
    const gap = pinned
      ? (cssPxValue(controls, 'row-gap', Number.NaN) || cssPxValue(controls, 'gap', 0))
      : 0;
    const openHeight = pinned ? cssPxValue(controls, '--desk-minimap-open-height', 92) : 0;
    return Math.ceil(padding + border + gap + rowHeight + openHeight);
  }

  function dispatchMiniMapLayoutChange(pinned, controls) {
    window.dispatchEvent(new CustomEvent('desktop:minimap-layout-change', {
      detail: {
        pinned: !!pinned,
        targetHeight: getMiniMapTargetHeight(controls, !!pinned)
      }
    }));
  }

  function setMiniMapPinned(pinned) {
    const controls = els.deskMiniMapPinBtn?.closest('.desk-zoom-controls');
    const nextPinned = !!pinned;
    controls?.classList.toggle('is-pinned', nextPinned);
    els.deskMiniMapPinBtn?.setAttribute('aria-pressed', nextPinned ? 'true' : 'false');
    renderMiniMap();
    dispatchMiniMapLayoutChange(nextPinned, controls);
    window.setTimeout(() => dispatchMiniMapLayoutChange(nextPinned, controls), 220);
  }

  function getRectFromPoints(start, end) {
    const x = Math.min(start.x, end.x);
    const y = Math.min(start.y, end.y);
    return {
      x,
      y,
      width: Math.abs(end.x - start.x),
      height: Math.abs(end.y - start.y)
    };
  }

  function rectsIntersect(a, b) {
    return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
  }

  function selectNodesInRect(rect, save = false) {
    const selected = Object.keys(DesktopState.state.canvas.nodes).filter(nodeId => {
      const bounds = getNodeBoundsById(nodeId);
      return bounds && rectsIntersect(rect, bounds);
    });
    setSelectedNodes(selected, save);
  }

  function getMovedBounds(groupIds, positions, dx, dy) {
    return getBoundsFromRects(groupIds.map(nodeId => {
      const node = DesktopState.state.canvas.nodes[nodeId];
      const base = positions[nodeId];
      if (!node || !base) return null;
      return {
        x: base.x + dx,
        y: base.y + dy,
        width: getNodeElement(nodeId)?.offsetWidth || node.width,
        height: getNodeElement(nodeId)?.offsetHeight || node.height
      };
    }).filter(Boolean));
  }

  function resolveSnap(groupIds, positions, dx, dy) {
    const movingBounds = getMovedBounds(groupIds, positions, dx, dy);
    if (!movingBounds) return { dx, dy, guides: {} };
    const threshold = SNAP_THRESHOLD_PX / DesktopState.state.canvas.scale;
    const others = Object.keys(DesktopState.state.canvas.nodes)
      .filter(nodeId => !groupIds.includes(nodeId))
      .map(getNodeBoundsById)
      .filter(Boolean);
    const movingX = [
      { value: movingBounds.x, kind: 'left' },
      { value: movingBounds.centerX, kind: 'center' },
      { value: movingBounds.right, kind: 'right' }
    ];
    const movingY = [
      { value: movingBounds.y, kind: 'top' },
      { value: movingBounds.centerY, kind: 'center' },
      { value: movingBounds.bottom, kind: 'bottom' }
    ];
    const targetX = others.flatMap(rect => [rect.x, rect.x + rect.width / 2, rect.x + rect.width]);
    const targetY = others.flatMap(rect => [rect.y, rect.y + rect.height / 2, rect.y + rect.height]);
    let snapX = null;
    let snapY = null;
    movingX.forEach(anchor => {
      targetX.forEach(target => {
        const diff = target - anchor.value;
        if (Math.abs(diff) <= threshold && (!snapX || Math.abs(diff) < Math.abs(snapX.diff))) {
          snapX = { diff, target };
        }
      });
    });
    movingY.forEach(anchor => {
      targetY.forEach(target => {
        const diff = target - anchor.value;
        if (Math.abs(diff) <= threshold && (!snapY || Math.abs(diff) < Math.abs(snapY.diff))) {
          snapY = { diff, target };
        }
      });
    });
    return {
      dx: dx + (snapX?.diff || 0),
      dy: dy + (snapY?.diff || 0),
      guides: {
        x: snapX?.target,
        y: snapY?.target
      }
    };
  }

  function makeCurvePath(from, to) {
    const distance = Math.max(110, Math.abs(to.x - from.x) * 0.48);
    return `M ${from.x} ${from.y} C ${from.x + distance} ${from.y}, ${to.x - distance} ${to.y}, ${to.x} ${to.y}`;
  }

  function renderConnectionPreview(fromNodeId, pointer) {
    const svg = document.querySelector('.desk-link-layer');
    if (!svg) return;
    updateLinkPath();
    const from = getAnchor(fromNodeId, 'right');
    const d = makeCurvePath(from, pointer);
    svg.insertAdjacentHTML('beforeend', `<path class="desk-link-path is-preview" d="${d}"></path>`);
  }

  function nextNodeId(type) {
    const prefix = type === 'file_output'
      ? 'file_output'
      : (type === 'image' ? 'image' : (type === 'upscale' ? 'upscale' : (type === 'pose' ? 'pose' : (type === 'layout' ? 'layout' : (type === 'text' ? 'text' : 'input')))));
    let id = '';
    do {
      const unique = globalThis.crypto?.randomUUID?.()?.replaceAll('-', '')
        || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
      id = `${prefix}_${unique}`;
    } while (DesktopState.state.canvas.nodes[id]);
    return id;
  }

  function createNodeState(type) {
    type = normalizeNodeMenuType(type);
    const id = nextNodeId(type);
    const count = Object.keys(DesktopState.state.canvas.nodes).length;
    const defaultWidth = type === 'file_output'
      ? DEFAULT_FILE_OUTPUT_NODE_WIDTH
      : (type === 'upscale' ? DEFAULT_UPSCALE_NODE_WIDTH : (type === 'layout' ? 320 : (type === 'pose' ? 340 : (type === 'text' ? DEFAULT_TEXT_NODE_WIDTH : DEFAULT_INPUT_NODE_WIDTH))));
    const defaultHeight = type === 'file_output'
      ? DEFAULT_FILE_OUTPUT_NODE_HEIGHT
      : (type === 'upscale' ? DEFAULT_UPSCALE_NODE_HEIGHT : (type === 'layout' ? 300 : (type === 'pose' ? 300 : (type === 'text' ? DEFAULT_TEXT_NODE_HEIGHT : DEFAULT_INPUT_NODE_HEIGHT))));
    const node = {
      id,
      type,
      x: type === 'file_output' ? 820 + count * 28 : 92 + count * 28,
      y: 92 + count * 24,
      width: defaultWidth,
      height: defaultHeight
    };
    if (type === 'input') {
      node.width = LOCKED_INPUT_NODE_WIDTH;
      node.height = LOCKED_INPUT_NODE_HEIGHT;
    }
    if (type === 'text') {
      node.text = '';
      node.stylePresetId = '';
      node.alias = nextTextNodeAlias();
    }
    if (type === 'image') {
      node.width = DEFAULT_IMAGE_NODE_WIDTH;
      node.height = DEFAULT_IMAGE_NODE_HEIGHT;
      node.aspectRatio = DEFAULT_IMAGE_NODE_WIDTH / DEFAULT_IMAGE_NODE_HEIGHT;
      node.imageData = '';
      node.imageUrl = '';
      node.imageName = '空图片节点';
      node.mimeType = 'image/png';
    }
    if (type === 'layout') {
      node.layoutTitle = '新排版画布';
      node.layoutPreview = '';
      node.layoutExport = '';
    }
    if (type === 'pose') {
      node.mode = 'director_stage';
      node.poseTitle = '姿态参考';
      node.poseData = {};
      node.legacyPoseData = {};
      node.directorData = createDefaultDirectorData();
      node.backgroundImage = null;
      node.backgroundName = '';
      node.backgroundSource = '';
      node.backgroundSourceNodeId = '';
      node.backgroundMeta = null;
      node.previewImage = '';
      node.exportImage = '';
      node.exportMode = 'mannequin_only';
      node.humanConfig = { skeletonVisible: true };
      node.camera = {};
      node.lights = [];
      node.status = 'idle';
      node.error = '';
    }
    if (type === 'upscale') {
      node.model = '4x-UltraSharp';
      node.tileSize = 256;
      node.tileOverlap = 32;
      node.device = 'auto';
      node.output = { archiveEnabled: true, telegramEnabled: false };
    }
    DesktopState.state.canvas.nodes[id] = node;
    if (type === 'input' || type === 'file_output' || type === 'upscale') {
      DesktopState.state.outputs[id] = {
        status: 'idle',
        stage: '',
        progressText: '',
        progress: 0,
        files: [],
        imagePaths: [],
        primaryFile: '',
        primaryImagePath: '',
        type: type === 'upscale' ? 'upscale' : 'gpt',
        error: '',
        taskId: '',
        fileManifest: null,
        selectedFiles: [],
        selectionInitialized: false
      };
    }
    return node;
  }

  function createDefaultDirectorData() {
    const controls = {
      torsoTwist: 0,
      headYaw: 0,
      leftShoulderSide: 0,
      leftShoulderFront: 8,
      leftElbow: 6,
      rightShoulderSide: 8,
      rightShoulderFront: 0,
      rightElbow: 6,
      leftHipSide: 2,
      leftHipFront: 0,
      leftKnee: 0,
      rightHipSide: 2,
      rightHipFront: 0,
      rightKnee: 0
    };
    return {
      version: 5,
      characters: [
        {
          id: 'char_a',
          name: '角色A',
          modelKey: 'mixamo_xbot',
          bodyPreset: 'female_proxy',
          color: '#4F8EF7',
          position: [-0.7, 0, 0],
          rotation: [0, 0, 0],
          scale: 1,
          posePreset: 'stand',
          boneControls: { ...controls }
        },
        {
          id: 'char_b',
          name: '角色B',
          modelKey: 'mixamo_ybot',
          bodyPreset: 'male_proxy',
          color: '#F25F5C',
          position: [0.7, 0, 0],
          rotation: [0, 0, 0],
          scale: 1,
          posePreset: 'stand',
          boneControls: { ...controls }
        }
      ],
      props: [],
      cameras: [
        {
          id: 'camera_01',
          name: '机位1',
          position: [0, 2.1, 5.4],
          target: [0, 1.45, 0],
          fov: 45,
          aspect: '16:9',
          thumbnail: ''
        }
      ],
      activeCameraId: 'camera_01',
      selectedId: 'char_a',
      viewMode: 'director'
    };
  }

  function inputNodeHtml(nodeId) {
    const nodeState = DesktopState.state.canvas.nodes[nodeId] || {};
    const defaults = nodeId === 'input'
      ? (DesktopState.state.params || {})
      : (nodeState.params || DesktopState.state.params || {});
    const provider = ['gpt', 'google', 'comfy'].includes(nodeState.provider)
      ? nodeState.provider
      : (nodeId === 'input' ? DesktopState.state.provider : 'gpt');
    const outputControls = nodeId === 'input'
      ? (DesktopState.state.output || {})
      : (nodeState.output || DesktopState.state.output || {});
    const archiveChecked = outputControls.archiveEnabled !== false;
    const telegramChecked = outputControls.telegramEnabled !== false;
    const batchChecked = !!(defaults.batchMode ?? nodeState.batchMode);
    const gptRoute = DesktopState.normalizeGptProviderRoute(defaults.gptProviderRoute, 'codex');
    const gptModelOptions = gptModelOptionsForRoute(gptRoute);
    const selectedGptModel = selectedGptModelForRoute(defaults, gptRoute, gptModelOptions);
    const routeCatalog = gptRouteCatalog(gptRoute);
    const routePresentation = GPT_ROUTE_PRESENTATION[gptRoute] || GPT_ROUTE_PRESENTATION.codex;
    const modelFieldLabel = gptRoute === 'third_party_image_api'
      ? String(routeCatalog?.model_field_label || routePresentation.modelLabel)
      : routePresentation.modelLabel;
    const imageEngineLabel = String(routeCatalog?.image_engine?.label || routeCatalog?.image_engine?.id || routePresentation.engineLabel);
    const reasoningOptions = gptReasoningOptionsForModel(gptRoute, selectedGptModel);
    const selectedReasoning = selectedReasoningForModel(defaults, gptRoute, selectedGptModel, reasoningOptions);
    return `
      <section class="desk-node desk-node--input desk-glass" data-node-id="${nodeId}" aria-label="模型输入节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow">模型输入</p>
            <h1>选择模型并组织提示词</h1>
          </div>
          <div class="desk-node-tools">
            <span class="desk-status-pill" data-output-status>空闲</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${nodeId}" title="连接到图片节点" aria-label="连接输出"></button>
        <button type="button" class="desk-port desk-port--in desk-port--image-in" data-port="in" data-node-id="${nodeId}" title="连接图片或文本节点到这里" aria-label="连接图片或文本输入"></button>
        <div class="desk-segment" role="tablist" aria-label="选择模型提供方">
          <button type="button" class="${provider === 'gpt' ? 'is-active' : ''}" data-provider="gpt">GPT</button>
          <button type="button" class="${provider === 'google' ? 'is-active' : ''}" data-provider="google">Google</button>
          <button type="button" class="${provider === 'comfy' ? 'is-active' : ''}" data-provider="comfy">Comfy</button>
        </div>
        <div class="desk-param-grid" aria-label="模型参数">
          <label data-provider-param="gpt google comfy"><span>画幅</span><select class="desk-select" data-field="ratio">${ratioOptionsHtml(defaults.ratio || '9:16')}</select></label>
          <label data-provider-param="gpt google"><span>分辨率</span><select class="desk-select" data-field="resolution">${optionListHtml([{ value: '1k', label: '1k' }, { value: '2k', label: '2k' }, { value: '4k', label: '4k' }], defaults.resolution || '2k')}</select></label>
          <label data-provider-param="google" hidden><span>模型</span><select class="desk-select" data-field="model">${googleModelOptionsHtml(defaults.model || DEFAULT_GOOGLE_MODEL)}</select></label>
          <label data-provider-param="gpt"><span>质量</span><select class="desk-select" data-field="quality">${optionListHtml([{ value: 'auto', label: 'auto' }, { value: 'low', label: 'low' }, { value: 'medium', label: 'medium' }, { value: 'high', label: 'high' }], defaults.quality || 'auto')}</select></label>
          <label data-provider-param="gpt"><span>数量</span><select class="desk-select" data-field="imageCount">${imageCountOptionsHtml(defaults.imageCount || 2)}</select></label>
          <label data-provider-param="gpt"><span>审核</span><select class="desk-select" data-field="moderation">${optionListHtml([{ value: 'auto', label: 'auto' }, { value: 'low', label: 'low' }], defaults.moderation || 'auto')}</select></label>
        </div>
        <div class="desk-prompt-mode" data-provider-param="gpt" aria-label="提示词理解方式">
          <label>
            <span>类型</span>
            <select class="desk-select" data-field="gptTaskType">${optionListHtml(GPT_TASK_TYPE_OPTIONS, defaults.gptTaskType || 'image')}</select>
          </label>
          <label>
            <span>线路</span>
            <select class="desk-select" data-field="gptProviderRoute">${optionListHtml(GPT_PROVIDER_ROUTE_OPTIONS, gptRoute)}</select>
          </label>
          <label class="desk-gpt-model-field">
            <span class="desk-gpt-model-caption"><b data-gpt-model-field-label>${escapeHtml(modelFieldLabel)}</b><small data-gpt-image-engine title="生图引擎：${escapeHtml(imageEngineLabel)}">${escapeHtml(imageEngineLabel)}</small></span>
            <select class="desk-select" data-field="gptMainModel" data-model-route="${escapeHtml(gptRoute)}">${optionListHtml(gptModelOptions, selectedGptModel)}</select>
          </label>
          <label>
            <span>推理强度</span>
            <select class="desk-select" data-field="reasoningEffort"${reasoningOptions.length ? '' : ' disabled'}>${reasoningOptions.length ? optionListHtml(reasoningOptions, selectedReasoning) : '<option value="none">不适用</option>'}</select>
          </label>
          <label>
            <span>理解方式</span>
            <select class="desk-select" data-field="promptMode">${optionListHtml(GPT_PROMPT_MODE_OPTIONS, defaults.promptMode || 'smart')}</select>
          </label>
        </div>
        <div class="desk-node__drawer">
          <div class="desk-prompt-panel desk-prompt-panel--references">
            <span class="desk-panel-title">输入参考</span>
            <div class="desk-reference-strip">
              <button type="button" class="desk-upload desk-upload--square" data-upload-drop title="上传参考图">
                <span>+</span>
                <small>参考图</small>
              </button>
              <div class="desk-thumb-row" data-reference-thumbs aria-label="参考图缩略图"></div>
            </div>
            <div class="desk-node-hint">连接文本节点作为提示词，手动上传图片或连接[图片,姿态,排版节点]作为参考图。</div>
          </div>
        </div>
        <div class="desk-input-footer">
          <div class="desk-pill-row" data-output-pills><span>等待输出图片节点</span></div>
          <div class="desk-output-controls desk-output-controls--input">
            <label class="desk-switch"><input type="checkbox" ${archiveChecked ? 'checked' : ''} data-output-archive><span></span><em>自动归档</em></label>
            <label class="desk-switch"><input type="checkbox" ${telegramChecked ? 'checked' : ''} data-output-telegram><span></span><em>发送到 Telegram</em></label>
            <label class="desk-switch"><input type="checkbox" ${batchChecked ? 'checked' : ''} data-field="batchMode"><span></span><em>批量</em></label>
          </div>
          <button type="button" class="desk-button desk-button--primary desk-manual-send" data-send-original disabled>手动发送</button>
          <div class="desk-action-row">
            <button type="button" class="desk-button desk-button--generate" data-result-run title="生成" aria-label="生成">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"></path>
              </svg>
            </button>
          </div>
        </div>
        <span class="desk-resize-handle desk-resize-handle--locked" aria-hidden="true"></span>
      </section>
    `;
  }

  function fileOutputNodeHtml(nodeId) {
    return `
      <section class="desk-node desk-node--file-output desk-glass" data-node-id="${nodeId}" aria-label="文件结果节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div class="desk-file-node-heading">
            <span class="desk-file-node-heading__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M8 3.5h6.8L19 7.7V19a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 19V5A1.5 1.5 0 0 1 8 3.5Z"></path>
                <path d="M14.5 3.8V8h4.2"></path>
                <path d="M9.5 12h6"></path>
                <path d="M9.5 15.5h4.5"></path>
              </svg>
            </span>
            <div>
              <p class="desk-node__eyebrow">文件结果</p>
              <h2 data-output-title>等待 PPT / PSD</h2>
            </div>
          </div>
          <div class="desk-node-tools">
            <span class="desk-status-pill" data-output-status>空闲</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${nodeId}" title="连接模型节点到这里" aria-label="连接输入"></button>
        <div class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true">
          <div class="desk-progress-copy">
            <span data-progress-stage>正在生成文件</span>
            <span><strong data-progress-percent>0%</strong><em data-progress-timer>00:00</em></span>
          </div>
          <div class="desk-progress"><span data-progress-bar></span></div>
        </div>
        <div class="desk-file-result" data-result-grid>
          <div class="desk-file-result-empty">
            <div class="desk-file-result-empty__icon" aria-hidden="true">
              <svg viewBox="0 0 48 48">
                <path class="desk-file-empty-back" d="M11 13.5h16l8 8V39H11z"></path>
                <path class="desk-file-empty-front" d="M17 8.5h15l7 7V34H17z"></path>
                <path class="desk-file-empty-fold" d="M31.5 9v7h7"></path>
                <path class="desk-file-empty-line" d="M22 22h11M22 27h8"></path>
              </svg>
            </div>
            <span class="desk-file-result-empty__kicker">文件收件箱</span>
            <strong>文件会出现在这里</strong>
            <span>从模型节点生成 PPT/PSD，结果会自动汇入这里。</span>
            <div class="desk-file-result-empty__types" aria-label="支持 PPT 和 PSD"><span>PPT</span><i></i><span>PSD</span></div>
          </div>
        </div>
        <div class="desk-file-output-footer">
          <div class="desk-file-output-source"><i aria-hidden="true"></i><span>由模型节点生成</span></div>
          <div class="desk-pill-row" data-output-pills><span>等待文件任务</span></div>
        </div>
        <span class="desk-resize-handle desk-resize-handle--locked" aria-hidden="true"></span>
      </section>
    `;
  }

  function upscaleNodeHtml(node) {
    const model = node.model || '4x-UltraSharp';
    const tileSize = DesktopState.clamp(node.tileSize || 256, 64, 2048, 256);
    const tileOverlap = DesktopState.clamp(node.tileOverlap || 32, 0, 256, 32);
    const manualMode = isManualUpscaleFlow(node.id);
    const telegramChecked = node.output?.telegramEnabled === true;
    return `
      <section class="desk-node desk-node--upscale desk-glass" data-node-id="${node.id}" aria-label="高清放大节点" data-i18n-aria="upscaleNodeAria">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow" data-i18n="upscaleEyebrow">高清放大</p>
            <h2 data-i18n="upscaleTitle">4x 本地超分</h2>
          </div>
          <div class="desk-node-tools">
            <span class="desk-status-pill" data-output-status>空闲</span>
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--upscale-in" data-port="in" data-node-id="${node.id}" title="连接图片到这里" aria-label="连接图片输入" data-i18n-title="upscaleInputTitle" data-i18n-aria="upscaleInputAria"></button>
        <button type="button" class="desk-port desk-port--out desk-port--upscale-out" data-port="out" data-node-id="${node.id}" title="连接到图片节点" aria-label="连接高清输出" data-i18n-title="upscaleOutputTitle" data-i18n-aria="upscaleOutputAria"></button>
        <div class="desk-upscale-controls">
          <label><span data-i18n="upscaleModelLabel">模型</span><select class="desk-select" data-upscale-field="model">${optionListHtml(UPSCALE_MODEL_OPTIONS, model)}</select></label>
          <label><span data-i18n="upscaleTileLabel">分块</span><select class="desk-select" data-upscale-field="tileSize">${optionListHtml([{ value: '192', label: '192' }, { value: '256', label: '256' }, { value: '384', label: '384' }, { value: '512', label: '512' }], tileSize)}</select></label>
          <label><span data-i18n="upscaleOverlapLabel">重叠</span><select class="desk-select" data-upscale-field="tileOverlap">${optionListHtml([{ value: '16', label: '16' }, { value: '32', label: '32' }, { value: '64', label: '64' }, { value: '96', label: '96' }], tileOverlap)}</select></label>
        </div>
        <div class="desk-progress-wrap desk-progress-float desk-upscale-progress" aria-label="高清放大进度" data-i18n-aria="upscaleProgressAria" aria-hidden="true">
          <div class="desk-progress-float__panel">
            <div class="desk-progress-float__bar">
              <span data-progress-bar></span>
              <strong class="desk-progress-float__percent" data-progress-percent>
                <span data-progress-percent-value>0%</span>
                <span class="desk-progress-float__timer" data-progress-timer>00:00</span>
              </strong>
            </div>
            <span class="desk-progress-float__stage" data-progress-stage data-i18n="upscaleProgressWaiting">等待图片</span>
          </div>
        </div>
        <div class="desk-action-row desk-upscale-actions${manualMode ? ' is-visible' : ''}" data-upscale-actions aria-hidden="${manualMode ? 'false' : 'true'}">
          <label class="desk-switch desk-upscale-telegram">
            <input type="checkbox" ${telegramChecked ? 'checked' : ''} data-output-telegram>
            <span></span>
            <em data-i18n="sendTelegram">发送到 Telegram</em>
          </label>
          <button type="button" class="desk-button desk-button--generate desk-upscale-run" data-result-run title="高清放大" aria-label="高清放大" data-i18n-title="upscaleRunTitle" data-i18n-aria="upscaleRunAria">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"></path>
            </svg>
          </button>
        </div>
      </section>
    `;
  }

  function imageNodeSource(node) {
    return node?.imageData || node?.imageUrl || '';
  }

  function listPromptImageNodes() {
    return Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node?.type === 'image' && imageNodeSource(node))
      .map((node, index) => {
        const source = imageNodeSource(node);
        const label = node.imageName || node.sourceTitle || `图片节点 ${index + 1}`;
        return {
          nodeId: node.id,
          id: `image-node:${node.id}`,
          type: 'image',
          label,
          name: node.imageName || label,
          title: node.sourceTitle || label,
          sourceNodeId: node.id,
          imageData: node.imageData || '',
          imageUrl: node.imageUrl || '',
          url: node.imageUrl || source,
          base64: node.imageData || '',
          mimeType: node.mimeType || 'image/png',
          prompt: node.sourcePrompt || '',
          file: node.sourceFile || '',
          source: node.sourceKind || 'image-node'
        };
      });
  }

  function imageNodePlaceholderHtml() {
    return `
        <div class="desk-image-node__placeholder">
          <div class="desk-image-node__placeholder-copy">
            <strong>空图片节点</strong>
            <span>连接结果或上传图片</span>
          </div>
          <button type="button" class="desk-image-node__empty-upload" data-image-upload title="上传图片" aria-label="上传图片">
            <span aria-hidden="true">+</span>
          </button>
        </div>`;
  }

  function imageNodeToolsHtml(node) {
    if (!imageNodeSource(node)) return '';
    const hasMask = !!node.editState?.hasMask
      || !!node.editState?.maskData
      || !!node.editState?.maskOverlayData
      || !!node.editState?.projectJson?.hasMask;
    const hasPrompt = !!String(node.editState?.editPrompt || '').trim();
    return `
      <div class="desk-image-node__tools" aria-label="图片操作">
        <button type="button" data-image-edit title="编辑图片">编辑</button>
        ${hasMask ? '<button type="button" data-image-view-mask title="查看蒙版">蒙版</button>' : ''}
        ${hasPrompt ? '<button type="button" data-image-view-prompt title="查看说明">说明</button>' : ''}
      </div>`;
  }

  function imageNodeHtml(node) {
    const rawSrc = imageNodeSource(node);
    const src = escapeHtml(rawSrc);
    const name = escapeHtml(node.imageName || '图片节点');
    return `
      <section class="desk-node desk-node--image ${rawSrc ? 'has-image' : 'is-empty'}" data-node-id="${node.id}" data-node-drag-handle aria-label="图片节点">
        ${src ? `<img src="${src}" alt="${name}" draggable="false">` : imageNodePlaceholderHtml()}
        ${imageNodeToolsHtml(node)}
        <button type="button" class="desk-port desk-port--in desk-port--image-in" data-port="in" data-node-id="${node.id}" title="连接模型输出到这里" aria-label="连接图片输入"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接到可接入图片的节点" aria-label="连接图片输出"></button>
        <span class="desk-resize-handle" data-node-resize-handle title="按比例缩放图片" aria-hidden="true"></span>
      </section>
    `;
  }

  const IMAGE_EDIT_ASSET_VERSION = '20260703-image-editor-object-recolor1';
  const IMAGE_EDIT_UI_SCALE = 0.75;
  const IMAGE_EDIT_CURSOR_HOTSPOTS = {
    brush: [4, 21],
    maskBrush: [12, 12],
    shape: [12, 12],
    arrow: [17, 7],
    pin: [5, 20],
    eraser: [7, 17]
  };

  function getImageEditToolIcon(tool) {
    const assetVersion = IMAGE_EDIT_ASSET_VERSION;
    const sources = {
      select: `assets/image-editor-icons/select.svg?v=${assetVersion}`,
      brush: `assets/image-editor-icons/brush.svg?v=${assetVersion}`,
      maskBrush: `assets/image-editor-icons/mask.svg?v=${assetVersion}`,
      shape: `assets/image-editor-icons/shape.svg?v=${assetVersion}`,
      arrow: `assets/image-editor-icons/arrow.svg?v=${assetVersion}`,
      text: `assets/image-editor-icons/text.svg?v=${assetVersion}`,
      pin: `assets/image-editor-icons/pin.svg?v=${assetVersion}`,
      eraser: `assets/image-editor-icons/eraser.svg?v=${assetVersion}`
    };
    return sources[tool] || sources.select;
  }

  function getImageEditCursorUrl(imageUrl, hotspotX = 0, hotspotY = 0, fallback = 'crosshair') {
    return `url("${imageUrl}") ${hotspotX} ${hotspotY}, ${fallback}`;
  }

  function getImageEditCursorAsset(tool) {
    const cursorVersion = IMAGE_EDIT_ASSET_VERSION;
    const sources = {
      brush: `/assets/image-editor-cursors/brush.svg?v=${cursorVersion}`,
      maskBrush: `/assets/image-editor-cursors/maskBrush.svg?v=${cursorVersion}`,
      shape: `/assets/image-editor-cursors/shape.svg?v=${cursorVersion}`,
      arrow: `/assets/image-editor-cursors/arrow.svg?v=${cursorVersion}`,
      pin: `/assets/image-editor-cursors/pin.svg?v=${cursorVersion}`,
      eraser: `/assets/image-editor-cursors/eraser.svg?v=${cursorVersion}`
    };
    return sources[tool] || '';
  }

  function getImageEditShapeIcon(shape) {
    switch (shape) {
      case 'rectFilled':
        return `<rect x="5.5" y="5.5" width="13" height="13" rx="2" fill="currentColor" stroke="none"></rect>`;
      case 'ellipseOutline':
        return `<circle cx="12" cy="12" r="6.8" fill="none"></circle>`;
      case 'ellipseFilled':
        return `<circle cx="12" cy="12" r="6.8" fill="currentColor" stroke="none"></circle>`;
      case 'rectOutline':
      default:
        return `<rect x="5.5" y="5.5" width="13" height="13" rx="2" fill="none"></rect>`;
    }
  }

  function textNodeHtml(node) {
    const alias = getTextNodeAlias(node);
    return `
      <section class="desk-node desk-node--text" data-node-id="${node.id}" data-node-drag-handle aria-label="文本节点">
        <div class="desk-text-node__alias" data-text-node-alias-shell style="${textNodeAliasStyle(alias)}">
          <input type="text" data-text-node-alias value="${escapeHtml(alias)}" maxlength="${TEXT_NODE_ALIAS_MAX_LENGTH}" pattern="[A-Za-z0-9\u3400-\u9FFF,_-]{1,${TEXT_NODE_ALIAS_MAX_LENGTH}}" aria-label="文本节点别名" title="支持汉字、英文、数字、-、_、," readonly tabindex="-1">
          <button type="button" data-text-node-alias-edit data-alias-mode="edit" aria-label="编辑文本节点别名" title="编辑别名">
            <svg class="desk-text-node__alias-icon desk-text-node__alias-icon--edit" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 20h9"></path>
              <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"></path>
            </svg>
            <svg class="desk-text-node__alias-icon desk-text-node__alias-icon--apply" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M20 6 9 17l-5-5"></path>
            </svg>
          </button>
        </div>
        <div class="desk-text-node__styles" data-text-style-tags${node.stylePresetId ? '' : ' hidden'}>
          ${textStyleTagHtml(node.stylePresetId)}
        </div>
        <textarea class="desk-text-node__input" data-text-node-input placeholder="输入提示词或片段">${escapeHtml(node.text || '')}</textarea>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接提示词到模型节点" aria-label="连接文本输出"></button>
        <div class="desk-text-node__drawer" aria-label="文本节点操作">
          <button type="button" data-text-action="preset">预设风格</button>
          <button type="button" data-text-action="google-polish">google 润色</button>
          <button type="button" data-text-action="gpt-polish">Gpt 润色</button>
          <button type="button" data-text-action="safe-rewrite">安全审核版</button>
          <button type="button" data-text-action="clear" aria-label="清空文本节点" title="清空">❌</button>
        </div>
        <div class="desk-text-style-menu" data-text-style-menu hidden aria-label="选择预设风格">
          ${textStylePresetButtonsHtml()}
        </div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放文本节点" aria-hidden="true"></span>
      </section>
    `;
  }

  function layoutNodeHtml(node) {
    const preview = escapeHtml(node.layoutPreview || node.layoutExport || '');
    const inputCount = getLayoutInputCount(node.id);
    const presetLabel = escapeHtml(node.layoutPresetLabel || (node.layoutDraftId ? '已保存草稿' : '选择尺寸模板'));
    return `
      <section class="desk-node desk-node--layout desk-glass" data-node-id="${node.id}" aria-label="排版节点">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow">排版节点</p>
            <h2>图文版面</h2>
          </div>
          <div class="desk-node-tools">
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--layout-in" data-port="in" data-node-id="${node.id}" title="连接图片节点到排版" aria-label="连接图片输入"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${node.id}" title="连接到可接入图片的节点" aria-label="连接排版输出"></button>
        <div class="desk-layout-node-preview" data-layout-preview>
          ${preview ? `<img src="${preview}" alt="排版预览">` : '<span>尚未排版</span>'}
        </div>
        <div class="desk-layout-node-actions">
          <button type="button" class="is-primary" data-layout-open>打开排版</button>
          <button type="button" data-layout-quick-export>更新预览</button>
        </div>
        <div class="desk-pill-row"><span>Fabric.js</span><span>${presetLabel}</span><span data-layout-input-count>${inputCount ? `已接入 ${inputCount} 张图` : '可接入图片'}</span></div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放节点" aria-hidden="true"></span>
      </section>
    `;
  }

  function getPoseInputImages(poseNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === poseNodeId)
      .map(edge => normalizeImageSourceFromNode(DesktopState.state.canvas.nodes[edge.from]))
      .filter(Boolean);
  }

  function poseStatusText(node, preview, backgroundCount) {
    if (node.error) return `错误：${node.error}`;
    if (preview) return '已导出参考图';
    return backgroundCount ? `已接入 ${backgroundCount} 张参考图` : '等待姿态编辑';
  }

  function poseDisplayTitle(node = {}, fallback = '姿态参考') {
    const title = String(node.poseTitle || fallback);
    return title === '3D 导演台' ? '姿态参考' : title;
  }

  function poseNodeHtml(node) {
    const preview = escapeHtml(node.previewImage || node.exportImage || '');
    const inputCount = getPoseInputImages(node.id).length;
    const backgroundCount = inputCount + (node.backgroundImage ? 1 : 0);
    const statusText = poseStatusText(node, preview, backgroundCount);
    const title = node.mode === 'director_stage' ? poseDisplayTitle(node) : (node.poseTitle || '姿态节点');
    const eyebrow = node.mode === 'director_stage' ? 'Pose Reference' : 'Pose Node';
    const emptyTitle = node.mode === 'director_stage' ? '姿态参考' : 'Pose Studio Lite';
    const emptyHint = node.mode === 'director_stage' ? '多角色低模人偶 / 机位截图' : '打开编辑器调整姿态';
    return `
      <section class="desk-node desk-node--pose desk-glass" data-node-id="${node.id}" aria-label="${escapeHtml(title)}">
        <div class="desk-node__header" data-node-drag-handle>
          <div>
            <p class="desk-node__eyebrow">${escapeHtml(eyebrow)}</p>
            <h2>${escapeHtml(title)}</h2>
          </div>
          <div class="desk-node-tools">
            <button type="button" class="desk-node-delete" data-node-delete title="删除节点" aria-label="删除节点">删</button>
          </div>
        </div>
        <button type="button" class="desk-port desk-port--in desk-port--pose-in" data-port="in" data-node-id="${node.id}" title="连接图片作为背景参考" aria-label="连接姿态参考输入"></button>
        <button type="button" class="desk-port desk-port--out desk-port--pose-out" data-port="out" data-node-id="${node.id}" title="连接到模型节点作为参考图" aria-label="连接姿态输出"></button>
        <div class="desk-pose-node-preview" data-pose-preview>
          ${preview ? `<img src="${preview}" alt="姿态预览">` : `<span><strong>${escapeHtml(emptyTitle)}</strong><em>${escapeHtml(emptyHint)}</em></span>`}
        </div>
        <div class="desk-pose-node-actions">
          <button type="button" class="is-primary" data-pose-open>打开编辑器</button>
          <button type="button" data-pose-connect-input>接入模型</button>
        </div>
        <div class="desk-pill-row"><span data-pose-status>${escapeHtml(statusText)}</span><span data-pose-input-count>${backgroundCount ? `背景 ${backgroundCount}` : '可接入背景'}</span></div>
        <span class="desk-resize-handle" data-node-resize-handle title="缩放节点" aria-hidden="true"></span>
      </section>
    `;
  }

  function ensureGraphDom() {
    const world = els.deskCanvasWorld;
    if (!world) return;
    world.querySelectorAll('.desk-node[data-node-id]').forEach(node => {
      if (!DesktopState.state.canvas.nodes[node.dataset.nodeId]) node.remove();
    });
    Object.entries(DesktopState.state.canvas.nodes).forEach(([nodeId, node]) => {
      if (getNodeElement(nodeId)) return;
      if (node.type === 'output') return;
      const html = node.type === 'file_output'
        ? fileOutputNodeHtml(nodeId)
        : (node.type === 'image'
          ? imageNodeHtml(node)
          : (node.type === 'upscale' ? upscaleNodeHtml(node) : (node.type === 'pose' ? poseNodeHtml(node) : (node.type === 'layout' ? layoutNodeHtml(node) : (node.type === 'text' ? textNodeHtml(node) : inputNodeHtml(nodeId))))));
      world.insertAdjacentHTML('beforeend', html);
    });
  }

  function screenToWorld(clientX, clientY) {
    const rect = els.deskCanvasViewport.getBoundingClientRect();
    const canvas = DesktopState.state.canvas;
    return {
      x: (clientX - rect.left - canvas.x) / canvas.scale,
      y: (clientY - rect.top - canvas.y) / canvas.scale
    };
  }

  function getViewportCenterWorldPoint(offsetX = 0, offsetY = 0) {
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    return rect
      ? screenToWorld(rect.left + rect.width / 2 + offsetX, rect.top + rect.height / 2 + offsetY)
      : { x: 360 + offsetX, y: 260 + offsetY };
  }

  function getPrimaryModelNodeId() {
    const nodes = DesktopState.state.canvas.nodes || {};
    const selectedInput = getSelectedNodeIds().find(nodeId => nodes[nodeId]?.type === 'input');
    if (selectedInput) return selectedInput;
    if (nodes.input?.type === 'input') return 'input';
    return Object.values(nodes).find(node => node?.type === 'input')?.id || '';
  }

  function getPrimaryModelBounds() {
    const primaryModelId = getPrimaryModelNodeId();
    if (primaryModelId) return getNodeBoundsById(primaryModelId);
    const nodeBounds = Object.values(DesktopState.state.canvas.nodes || {})
      .map(node => node ? getNodeBounds(node) : null)
      .filter(Boolean);
    return getBoundsFromRects(nodeBounds);
  }

  function centerCanvasOnBounds(bounds, scale = DesktopState.state.canvas.scale) {
    const rect = els.deskCanvasViewport?.getBoundingClientRect?.();
    if (!rect || !bounds) return false;
    const canvas = DesktopState.state.canvas;
    const worldRect = els.deskCanvasWorld?.getBoundingClientRect?.();
    const worldBaseLeft = worldRect ? worldRect.left - canvas.x : rect.left;
    const worldBaseTop = worldRect ? worldRect.top - canvas.y : rect.top;
    const nextScale = clamp(scale, MIN_SCALE, MAX_SCALE);
    const centerX = bounds.x + bounds.width / 2;
    const centerY = bounds.y + bounds.height / 2;
    canvas.x = rect.left + rect.width / 2 - worldBaseLeft - centerX * nextScale;
    canvas.y = rect.top + rect.height / 2 - worldBaseTop - centerY * nextScale;
    return true;
  }

  function centerCanvasOnPrimaryModel(scale = DesktopState.state.canvas.scale) {
    return centerCanvasOnBounds(getPrimaryModelBounds(), scale);
  }

  function setCanvasScale(nextScale, anchorClientX, anchorClientY) {
    const canvas = DesktopState.state.canvas;
    const previousScale = canvas.scale;
    const scale = clamp(nextScale, MIN_SCALE, MAX_SCALE);
    if (Math.abs(scale - previousScale) < 0.001) return;

    const rect = els.deskCanvasViewport.getBoundingClientRect();
    const anchorX = anchorClientX == null ? rect.left + rect.width / 2 : anchorClientX;
    const anchorY = anchorClientY == null ? rect.top + rect.height / 2 : anchorClientY;
    const worldPoint = screenToWorld(anchorX, anchorY);

    canvas.scale = scale;
    canvas.x = anchorX - rect.left - worldPoint.x * scale;
    canvas.y = anchorY - rect.top - worldPoint.y * scale;
    applyCanvasTransform();
    DesktopState.saveSettings();
  }

  function setCanvasScaleCenteredOnPrimary(nextScale) {
    const canvas = DesktopState.state.canvas;
    const scale = clamp(nextScale, MIN_SCALE, MAX_SCALE);
    canvas.scale = scale;
    if (!centerCanvasOnPrimaryModel(scale)) {
      canvas.x = 0;
      canvas.y = 0;
    }
    applyCanvasTransform();
    DesktopState.saveSettings();
  }

  function resetCanvasView() {
    const canvas = DesktopState.state.canvas;
    canvas.scale = DEFAULT_CANVAS_SCALE;
    if (!centerCanvasOnPrimaryModel(DEFAULT_CANVAS_SCALE)) {
      canvas.x = 0;
      canvas.y = 0;
    }
    applyCanvasTransform();
    DesktopState.saveSettings();
  }

  function setZoomPresetMenuOpen(open) {
    if (!els.deskZoomPresetMenu || !els.deskZoomLabel) return;
    const nextOpen = !!open;
    updateZoomPresetButtons();
    els.deskZoomPresetMenu.hidden = !nextOpen;
    els.deskZoomLabel.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
  }

  function updateZoomPresetButtons() {
    if (!els.deskZoomPresetMenu) return;
    const currentScale = Number(DesktopState.state.canvas.scale || 1);
    els.deskZoomPresetMenu.querySelectorAll('[data-zoom-preset]').forEach(button => {
      const preset = Number(button.dataset.zoomPreset);
      const isActive = Number.isFinite(preset) && Math.abs(currentScale - preset) < 0.01;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-checked', isActive ? 'true' : 'false');
    });
  }

  function toggleZoomPresetMenu() {
    setZoomPresetMenuOpen(!!els.deskZoomPresetMenu?.hidden);
  }

  function applyZoomPreset(scale) {
    if (!ZOOM_PRESETS.includes(scale)) return;
    setZoomPresetMenuOpen(false);
    setCanvasScaleCenteredOnPrimary(scale);
    focusCanvasViewport();
  }

  function resetNodeLayout() {
    DesktopState.state.canvas.nodes = {
      input: { id: 'input', type: 'input', x: 56, y: 72, width: DEFAULT_INPUT_NODE_WIDTH, height: DEFAULT_INPUT_NODE_HEIGHT }
    };
    DesktopState.state.canvas.edges = [];
    DesktopState.state.nodeReferenceImages = {};
    document.querySelectorAll('.desk-node[data-node-id]:not(#deskInputNode)').forEach(node => node.remove());
    ensureDefaultModelOutputState();
    applyAllNodeLayouts();
    DesktopState.saveSettings();
  }

  function syncFormFromState() {
    const { state } = DesktopState;
    if (els.deskRatioSelect) els.deskRatioSelect.value = state.params.ratio;
    if (els.deskResolutionSelect) els.deskResolutionSelect.value = state.params.resolution;
    if (els.deskModelSelect) {
      els.deskModelSelect.value = typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(state.params.model, DEFAULT_GOOGLE_MODEL)
        : (state.params.model || DEFAULT_GOOGLE_MODEL);
    }
    if (els.deskQualitySelect) els.deskQualitySelect.value = state.params.quality;
    if (els.deskCountInput) els.deskCountInput.value = DesktopState.clamp(state.params.imageCount, 1, 8, 2);
    if (els.deskModerationSelect) els.deskModerationSelect.value = state.params.moderation;
    const normalizedTaskType = DesktopState.normalizeGptTaskType(state.params.gptTaskType, 'image');
    if (normalizedTaskType !== 'image') state.params.gptProviderRoute = 'chatgpt_pool';
    if (normalizedTaskType === 'image' && state.params.useThirdPartyApi && state.params.gptProviderRoute !== 'third_party_image_api') {
      state.params.gptProviderRoute = 'third_party_image_api';
      state.params.useThirdPartyApi = false;
    }
    if (els.deskGptTaskTypeSelect) els.deskGptTaskTypeSelect.value = normalizedTaskType;
    const routeSelect = els.deskGptProviderRouteSelect || els.deskInputNode?.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    if (routeSelect) routeSelect.value = state.params.gptProviderRoute || 'codex';
    if (els.deskReasoningEffortSelect) els.deskReasoningEffortSelect.value = state.params.reasoningEffort || 'medium';
    applyGptModelRouteToNode(els.deskInputNode, routeSelect?.value || state.params.gptProviderRoute || 'codex', { rememberPrevious: false });
    if (els.deskPromptModeSelect) els.deskPromptModeSelect.value = DesktopState.normalizePromptMode(state.params.promptMode, 'smart');
    if (els.deskBatchMode) els.deskBatchMode.checked = !!state.params.batchMode;
    applyPromptModeToNode(els.deskInputNode, state.params.promptMode || 'smart');
    applyGptTaskTypeToNode(els.deskInputNode, normalizedTaskType);

    document.querySelectorAll('#deskProviderSegment button').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.provider === state.provider);
    });
    updateAllProviderParamVisibility();

    applyNodeSelection();
    applyCanvasTransform();
    applyAllNodeLayouts();
    updateInputProgressOverlay();
    syncOutputControlsToNodes(state.output, { save: false });
  }

  function setInputExpanded(expanded) {
    const { state } = DesktopState;
    state.inputExpanded = !!expanded;
    if (state.inputExpanded) selectNode('input');
    DesktopState.saveSettings();
  }

  function readFormToState() {
    const { state } = DesktopState;
    upgradeGptRouteControls(els.deskInputNode);
    const routeSelect = els.deskGptProviderRouteSelect || els.deskInputNode?.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    const outputControls = readOutputControlsFromNode(els.deskInputNode, state.output);
    state.params.ratio = DesktopState.normalizeRatio(els.deskRatioSelect?.value, '9:16');
    state.params.resolution = DesktopState.normalizeResolution(els.deskResolutionSelect?.value, '2k');
    state.params.model = typeof DesktopState.normalizeGoogleModel === 'function'
      ? DesktopState.normalizeGoogleModel(els.deskModelSelect?.value || state.params.model || DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
      : (els.deskModelSelect?.value || state.params.model || DEFAULT_GOOGLE_MODEL);
    state.params.quality = DesktopState.normalizeGptQuality(els.deskQualitySelect?.value, 'auto');
    state.params.imageCount = DesktopState.clamp(els.deskCountInput?.value, 1, 8, 1);
    state.params.moderation = DesktopState.normalizeModeration(els.deskModerationSelect?.value, 'auto');
    state.params.gptTaskType = DesktopState.normalizeGptTaskType(els.deskGptTaskTypeSelect?.value, 'image');
    state.params.gptProviderRoute = state.params.gptTaskType === 'image'
      ? DesktopState.normalizeGptProviderRoute(routeSelect?.value, 'codex')
      : 'chatgpt_pool';
    state.params.useThirdPartyApi = state.params.gptProviderRoute === 'third_party_image_api';
    state.params.reasoningEffort = DesktopState.normalizeReasoningEffort(els.deskReasoningEffortSelect?.value, state.params.reasoningEffort || 'medium');
    applyGptModelRouteToNode(els.deskInputNode, state.params.gptProviderRoute);
    state.params.gptMainModel = DesktopState.normalizeGptMainModel(els.deskGptMainModelSelect?.value, 'gpt-5.5');
    state.params.gptModelsByRoute = {
      ...(state.params.gptModelsByRoute || {}),
      [state.params.gptProviderRoute]: state.params.gptMainModel
    };
    state.params.reasoningEffort = DesktopState.normalizeReasoningEffort(els.deskReasoningEffortSelect?.value, 'medium');
    state.params.promptMode = DesktopState.normalizePromptMode(els.deskPromptModeSelect?.value, getPromptModeFromNode(els.deskInputNode, 'smart'));
    state.params.batchMode = !!els.deskBatchMode?.checked;
    applyGptTaskTypeToNode(els.deskInputNode, state.params.gptTaskType);
    syncOutputControlsToNodes(outputControls, { save: false });
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    window.DesktopResults?.refreshOutputConfigStatus?.('input', outputControls);
    return state;
  }

  function readOutputControlsFromNode(node, fallback = {}) {
    const archiveToggle = node?.querySelector('[data-output-archive]');
    const telegramToggle = node?.querySelector('[data-output-telegram]');
    return {
      archiveEnabled: archiveToggle ? archiveToggle.checked !== false : fallback?.archiveEnabled !== false,
      telegramEnabled: telegramToggle ? telegramToggle.checked !== false : fallback?.telegramEnabled !== false
    };
  }

  function syncInputNodeStateFromDom(node) {
    const nodeId = node?.dataset?.nodeId || '';
    const nodeState = nodeId ? DesktopState.state.canvas.nodes[nodeId] : null;
    if (!node || !nodeState || nodeState.type !== 'input') return null;
    if (nodeId === 'input') {
      readFormToState();
      return nodeState;
    }
    const taskType = DesktopState.normalizeGptTaskType(node.querySelector('[data-field="gptTaskType"]')?.value, 'image');
    const route = taskType === 'image'
      ? DesktopState.normalizeGptProviderRoute(node.querySelector('[data-field="gptProviderRoute"]')?.value, 'codex')
      : 'chatgpt_pool';
    nodeState.params = nodeState.params || {};
    nodeState.params.reasoningEffort = DesktopState.normalizeReasoningEffort(
      node.querySelector('[data-field="reasoningEffort"]')?.value,
      nodeState.params.reasoningEffort || 'medium'
    );
    applyGptModelRouteToNode(node, route);
    const routeModels = {
      ...(nodeState.params?.gptModelsByRoute || {}),
      [route]: DesktopState.normalizeGptMainModel(node.querySelector('[data-field="gptMainModel"]')?.value, 'gpt-5.5')
    };
    nodeState.provider = getProviderFromNode(node);
    nodeState.params = {
      ratio: DesktopState.normalizeRatio(node.querySelector('[data-field="ratio"]')?.value, '9:16'),
      resolution: DesktopState.normalizeResolution(node.querySelector('[data-field="resolution"]')?.value, '2k'),
      model: typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
        : (node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL),
      quality: DesktopState.normalizeGptQuality(node.querySelector('[data-field="quality"]')?.value, 'auto'),
      imageCount: DesktopState.clamp(node.querySelector('[data-field="imageCount"]')?.value, 1, 8, 1),
      moderation: DesktopState.normalizeModeration(node.querySelector('[data-field="moderation"]')?.value, 'auto'),
      gptTaskType: taskType,
      gptProviderRoute: route,
      useThirdPartyApi: route === 'third_party_image_api',
      gptMainModel: DesktopState.normalizeGptMainModel(node.querySelector('[data-field="gptMainModel"]')?.value, 'gpt-5.5'),
      gptModelsByRoute: routeModels,
      reasoningEffort: DesktopState.normalizeReasoningEffort(node.querySelector('[data-field="reasoningEffort"]')?.value, 'medium'),
      promptMode: getPromptModeFromNode(node, 'smart'),
      batchMode: !!node.querySelector('[data-field="batchMode"]')?.checked
    };
    nodeState.batchMode = !!nodeState.params.batchMode;
    nodeState.output = readOutputControlsFromNode(node, nodeState.output || DesktopState.state.output);
    return nodeState;
  }

  function syncVisibleInputNodeStatesToCanvas() {
    document.querySelectorAll('.desk-node--input[data-node-id]').forEach(syncInputNodeStateFromDom);
  }

  function readOutputControlsForTask(inputNodeId, resultNodeId = inputNodeId) {
    const inputNode = getNodeElement(inputNodeId);
    const resultNode = resultNodeId && resultNodeId !== inputNodeId ? getNodeElement(resultNodeId) : null;
    const inputControls = readOutputControlsFromNode(inputNode, DesktopState.state.output);
    return resultNode
      ? readOutputControlsFromNode(resultNode, inputControls)
      : inputControls;
  }

  function syncOutputControlsToNodes(controls = DesktopState.state.output, options = {}) {
    const normalized = {
      archiveEnabled: controls?.archiveEnabled !== false,
      telegramEnabled: controls?.telegramEnabled !== false
    };
    DesktopState.state.output.archiveEnabled = normalized.archiveEnabled;
    DesktopState.state.output.telegramEnabled = normalized.telegramEnabled;
    Object.values(DesktopState.state.outputs || {}).forEach(output => {
      if (!output) return;
      output.params = {
        ...(output.params || {}),
        ...normalized
      };
    });
    document.querySelectorAll('.desk-node[data-node-id]').forEach(node => {
      const archiveToggle = node.querySelector('[data-output-archive]');
      const telegramToggle = node.querySelector('[data-output-telegram]');
      if (node.classList.contains('desk-node--upscale')) {
        const upscaleNode = DesktopState.state.canvas.nodes[node.dataset.nodeId || ''];
        if (archiveToggle) archiveToggle.checked = true;
        if (telegramToggle) telegramToggle.checked = upscaleNode?.output?.telegramEnabled === true;
        return;
      }
      if (archiveToggle) archiveToggle.checked = normalized.archiveEnabled;
      if (telegramToggle) telegramToggle.checked = normalized.telegramEnabled;
    });
    window.DesktopResults?.refreshOutputConfigStatus?.('input', normalized, {
      updateBottom: options.updateBottom !== false
    });
    if (options.save !== false) DesktopState.saveSettings();
    return normalized;
  }

  function syncOutputControlsFromNode(node) {
    if (!node) return;
    const nodeId = node.dataset.nodeId || 'input';
    const nodeState = DesktopState.state.canvas.nodes[nodeId];
    const controls = readOutputControlsFromNode(node, nodeState?.output || DesktopState.state.output);
    if (!DesktopState.state.outputs[nodeId]) DesktopState.state.outputs[nodeId] = {};
    DesktopState.state.outputs[nodeId].params = {
      ...(DesktopState.state.outputs[nodeId].params || {}),
      ...controls
    };
    if (nodeState?.type === 'upscale') {
      nodeState.output = {
        archiveEnabled: true,
        telegramEnabled: controls.telegramEnabled === true
      };
      DesktopState.state.outputs[nodeId].params.archiveEnabled = true;
      DesktopState.state.outputs[nodeId].params.telegramEnabled = nodeState.output.telegramEnabled;
      DesktopState.saveSettings();
      return;
    }
    syncOutputControlsToNodes(controls, {
      updateBottom: node.classList.contains('desk-node--input')
    });
  }

  function startPan(event) {
    const isLeftButton = event.button === 0;
    const isRightButton = event.button === 2;
    if (!isLeftButton && !isRightButton) return;
    const startedOnNode = !!event.target.closest('.desk-node');
    if (isLeftButton) {
      if (event.target.closest(CANVAS_INTERACTION_BLOCK_SELECTOR)) return;
    } else if (
      event.target.closest(CANVAS_RIGHT_PAN_BLOCK_SELECTOR)
      || event.target.closest(CANVAS_RIGHT_PAN_CONTROL_SELECTOR)
    ) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    hideContextMenu();
    if (isLeftButton && isSelectToolActive() && !event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
      const pointer = screenToWorld(event.clientX, event.clientY);
      activeInteraction = {
        type: 'marquee',
        startWorldX: pointer.x,
        startWorldY: pointer.y,
        currentWorldX: pointer.x,
        currentWorldY: pointer.y
      };
      hideSmartGuides();
      setSelectedNodes([], false);
      renderMarquee({ x: pointer.x, y: pointer.y, width: 0, height: 0 });
      return;
    }
    if (isLeftButton) selectNode('');
    const canvas = DesktopState.state.canvas;
    activeInteraction = {
      type: 'pan',
      pointerButton: isRightButton ? 'right' : 'left',
      pointerId: event.pointerId,
      startedOnNode,
      startX: event.clientX,
      startY: event.clientY,
      canvasX: canvas.x,
      canvasY: canvas.y,
      moved: false
    };
    try {
      els.deskCanvasViewport?.setPointerCapture?.(event.pointerId);
    } catch {}
    els.deskCanvasViewport.classList.add('is-panning');
  }

  function startRightMousePanFallback(event) {
    if (event.button !== 2 || activeInteraction) return;
    const target = event.target;
    if (
      target.closest(CANVAS_RIGHT_PAN_BLOCK_SELECTOR)
      || target.closest(CANVAS_RIGHT_PAN_CONTROL_SELECTOR)
    ) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    hideContextMenu();
    const canvas = DesktopState.state.canvas;
    activeInteraction = {
      type: 'pan',
      pointerButton: 'right',
      mouseFallback: true,
      startedOnNode: !!target.closest('.desk-node'),
      startX: event.clientX,
      startY: event.clientY,
      canvasX: canvas.x,
      canvasY: canvas.y,
      moved: false
    };
    els.deskCanvasViewport?.classList.add('is-panning');
  }

  function moveMouseInteractionFallback(event) {
    if (!activeInteraction?.mouseFallback) return;
    moveInteraction(event);
  }

  function endMouseInteractionFallback(event) {
    if (!activeInteraction?.mouseFallback) return;
    endInteraction(event);
  }

  function isTextNodeDragEdge(event, node) {
    if (!node?.classList?.contains('desk-node--text')) return false;
    if (event.target.closest('button, input, select, [data-text-style-menu], [data-node-resize-handle], .desk-port')) return false;
    const rect = node.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    return (
      x <= TEXT_NODE_DRAG_EDGE_PX
      || x >= rect.width - TEXT_NODE_DRAG_EDGE_PX
      || y <= TEXT_NODE_DRAG_EDGE_PX
      || y >= rect.height - TEXT_NODE_DRAG_EDGE_PX
    );
  }

  function startNodeDrag(event, options = {}) {
    if (event.button !== 0) return;
    if (!options.force && event.target.closest('button, input, textarea, select')) return;
    const node = event.target.closest('.desk-node[data-node-id]');
    if (!node) return;
    event.preventDefault();
    const nodeId = node.dataset.nodeId;
    const selectedIds = getSelectedNodeIds();
    const groupIds = selectedIds.includes(nodeId) && selectedIds.length > 1 ? selectedIds : [nodeId];
    const nodeState = getNodeState(nodeId);
    const pointer = screenToWorld(event.clientX, event.clientY);
    activeInteraction = {
      type: 'node-drag',
      nodeId,
      groupIds,
      nodePositions: Object.fromEntries(groupIds.map(id => {
        const item = getNodeState(id);
        return [id, { x: item.x, y: item.y }];
      })),
      groupBounds: getBoundsForNodeIds(groupIds),
      startWorldX: pointer.x,
      startWorldY: pointer.y,
      nodeX: nodeState.x,
      nodeY: nodeState.y
    };
    node.classList.add('is-dragging');
  }

  function startNodeResize(event) {
    if (event.button !== 0) return;
    const node = event.target.closest('.desk-node[data-node-id]');
    if (!node) return;
    const nodeState = getNodeState(node.dataset.nodeId);
    if (nodeState?.type === 'input') return;
    event.preventDefault();
    event.stopPropagation();
    const nodeId = node.dataset.nodeId;
    const resizeState = getNodeState(nodeId);
    const pointer = screenToWorld(event.clientX, event.clientY);
    activeInteraction = {
      type: 'node-resize',
      nodeId,
      startWorldX: pointer.x,
      startWorldY: pointer.y,
      width: resizeState.width,
      height: resizeState.height,
      aspectRatio: resizeState.aspectRatio || (resizeState.width / Math.max(1, resizeState.height))
    };
    node.classList.add('is-resizing');
  }

  function moveInteraction(event) {
    if (!activeInteraction) return;
    event.preventDefault();

    if (activeInteraction.type === 'pan') {
      const canvas = DesktopState.state.canvas;
      const dx = event.clientX - activeInteraction.startX;
      const dy = event.clientY - activeInteraction.startY;
      if (Math.hypot(dx, dy) > CANVAS_PAN_DRAG_THRESHOLD_PX) {
        activeInteraction.moved = true;
      }
      canvas.x = activeInteraction.canvasX + dx;
      canvas.y = activeInteraction.canvasY + dy;
      applyCanvasTransform();
      return;
    }

    if (activeInteraction.type === 'connect') {
      activeInteraction.pointer = screenToWorld(event.clientX, event.clientY);
      renderConnectionPreview(activeInteraction.fromNodeId, activeInteraction.pointer);
      return;
    }

    if (activeInteraction.type === 'marquee') {
      const pointer = screenToWorld(event.clientX, event.clientY);
      activeInteraction.currentWorldX = pointer.x;
      activeInteraction.currentWorldY = pointer.y;
      const rect = getRectFromPoints(
        { x: activeInteraction.startWorldX, y: activeInteraction.startWorldY },
        { x: pointer.x, y: pointer.y }
      );
      renderMarquee(rect);
      selectNodesInRect(rect, false);
      return;
    }

    const nodeState = getNodeState(activeInteraction.nodeId);
    const pointer = screenToWorld(event.clientX, event.clientY);

    if (activeInteraction.type === 'node-drag') {
      const rawDx = pointer.x - activeInteraction.startWorldX;
      const rawDy = pointer.y - activeInteraction.startWorldY;
      const snap = resolveSnap(activeInteraction.groupIds || [activeInteraction.nodeId], activeInteraction.nodePositions || {}, rawDx, rawDy);
      (activeInteraction.groupIds || [activeInteraction.nodeId]).forEach(nodeId => {
        const item = getNodeState(nodeId);
        const base = activeInteraction.nodePositions?.[nodeId];
        if (!item || !base) return;
        item.x = base.x + snap.dx;
        item.y = base.y + snap.dy;
        applyNodeLayout(nodeId);
      });
      showSmartGuides(snap.guides);
      updateLinkPath();
      return;
    }

    if (activeInteraction.type === 'node-resize') {
      if (nodeState.type === 'image') {
        const dx = pointer.x - activeInteraction.startWorldX;
        const dy = pointer.y - activeInteraction.startWorldY;
        const aspectRatio = Math.max(0.08, activeInteraction.aspectRatio || 1);
        const delta = Math.abs(dx) >= Math.abs(dy) ? dx : dy * aspectRatio;
        nodeState.width = clamp(activeInteraction.width + delta, MIN_IMAGE_NODE_WIDTH, MAX_IMAGE_NODE_WIDTH);
        nodeState.height = nodeState.width / aspectRatio;
        if (nodeState.height > MAX_IMAGE_NODE_WIDTH) {
          nodeState.height = MAX_IMAGE_NODE_WIDTH;
          nodeState.width = nodeState.height * aspectRatio;
        }
        nodeState.aspectRatio = aspectRatio;
      } else if (nodeState.type === 'text') {
        nodeState.width = clamp(activeInteraction.width + pointer.x - activeInteraction.startWorldX, MIN_TEXT_NODE_WIDTH, MAX_TEXT_NODE_WIDTH);
        nodeState.height = clamp(activeInteraction.height + pointer.y - activeInteraction.startWorldY, MIN_TEXT_NODE_HEIGHT, MAX_TEXT_NODE_HEIGHT);
      } else if (nodeState.type === 'input') {
        nodeState.width = LOCKED_INPUT_NODE_WIDTH;
        nodeState.height = LOCKED_INPUT_NODE_HEIGHT;
      } else {
        nodeState.width = clamp(activeInteraction.width + pointer.x - activeInteraction.startWorldX, MIN_NODE_WIDTH, MAX_NODE_WIDTH);
        nodeState.height = clamp(activeInteraction.height + pointer.y - activeInteraction.startWorldY, MIN_NODE_HEIGHT, MAX_NODE_HEIGHT);
      }
      applyNodeLayout(activeInteraction.nodeId);
      updateLinkPath();
    }
  }

  function endInteraction(event) {
    if (!activeInteraction) return;
    if (activeInteraction.type === 'connect') {
      finishConnectionDrag(event);
      activeInteraction = null;
      return;
    }
    if (activeInteraction.type === 'marquee') {
      const rect = getRectFromPoints(
        { x: activeInteraction.startWorldX, y: activeInteraction.startWorldY },
        { x: activeInteraction.currentWorldX, y: activeInteraction.currentWorldY }
      );
      if (rect.width < 4 / DesktopState.state.canvas.scale && rect.height < 4 / DesktopState.state.canvas.scale) {
        setSelectedNodes([]);
      } else {
        selectNodesInRect(rect, true);
      }
      hideMarquee();
      activeInteraction = null;
      return;
    }
    const interaction = activeInteraction;
    getNodeElement(interaction.nodeId)?.classList.remove('is-dragging', 'is-resizing');
    els.deskCanvasViewport?.classList.remove('is-panning');
    try {
      if (interaction.pointerId != null) {
        els.deskCanvasViewport?.releasePointerCapture?.(interaction.pointerId);
      }
    } catch {}
    hideSmartGuides();
    activeInteraction = null;
    DesktopState.saveSettings();
    if (interaction.type === 'pan' && interaction.pointerButton === 'right') {
      suppressCanvasContextMenuUntil = Date.now() + CANVAS_CONTEXTMENU_SUPPRESS_MS;
      if (!interaction.moved && !interaction.startedOnNode && event?.type === 'pointerup') {
        openContextMenu(event);
      }
    }
  }

  function handleCanvasWheel(event) {
    const insideNode = !!event.target.closest('.desk-node');
    if (insideNode && !event.metaKey && !event.ctrlKey && !event.altKey) return;
    event.preventDefault();

    const canvas = DesktopState.state.canvas;
    const shouldZoom = event.metaKey || event.ctrlKey || event.altKey || (!IS_MAC_PLATFORM && !event.shiftKey);
    if (shouldZoom) {
      const primaryDelta = Math.abs(event.deltaY || 0) >= Math.abs(event.deltaX || 0) ? event.deltaY : event.deltaX;
      if (!primaryDelta) return;
      const factor = primaryDelta > 0 ? 0.92 : 1.08;
      setCanvasScale(canvas.scale * factor, event.clientX, event.clientY);
      return;
    }

    if (IS_MAC_PLATFORM) {
      canvas.x -= event.deltaX;
      canvas.y -= event.deltaY;
    } else {
      const panX = event.deltaX || event.deltaY;
      canvas.x -= panX;
      if (event.deltaX && event.deltaY) canvas.y -= event.deltaY;
    }
    applyCanvasTransform();
    DesktopState.saveSettings();
  }

  function renderReferenceThumbs() {
    renderNodeReferenceThumbs('input');
  }

  function referenceSourceLabel(image) {
    const source = String(image?.source || '').toLowerCase();
    if (source.includes('set')) return '候选';
    if (source.includes('layout')) return '排版';
    if (source.includes('image-node')) return '图片';
    if (source.includes('upload')) return '上传';
    if (source.includes('gallery') || source.includes('asset') || source.includes('history')) return '图库';
    if (image?.assetId || image?.asset_id || image?.taskId) return '图库';
    return isObjectUrl(getReferenceUrl(image)) ? '上传' : '参考';
  }

  function openReferenceImage(image) {
    const url = getReferenceUrl(image);
    if (!url) return;
    window.open(url, '_blank', 'noopener');
  }

  function moveReference(nodeId, index, delta) {
    const refs = getNodeReferenceImages(nodeId);
    const nextIndex = index + delta;
    if (nextIndex < 0 || nextIndex >= refs.length) return;
    [refs[index], refs[nextIndex]] = [refs[nextIndex], refs[index]];
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
  }

  function removeReferenceAt(nodeId, index) {
    const refs = getNodeReferenceImages(nodeId);
    const image = refs[index];
    if (!image) return;
    revokeReferenceUrl(image);
    refs.splice(index, 1);
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
  }

  function clearNodeReferences(nodeId) {
    const refs = getNodeReferenceImages(nodeId);
    refs.forEach(revokeReferenceUrl);
    if (nodeId === 'input') {
      DesktopState.state.referenceImages = [];
    } else {
      delete getNodeReferenceStore()[nodeId];
    }
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
    DesktopResults.showTransientMessage('参考图槽已清空。');
  }

  function renderReferenceItem(nodeId, image, index, total) {
    const item = document.createElement('div');
    const url = getReferenceUrl(image);
    const title = image?.title || image?.name || `参考图 ${index + 1}`;
    item.className = 'desk-thumb';
    item.innerHTML = `
      <img src="${escapeHtml(url)}" alt="${escapeHtml(title)}">
      <span class="desk-thumb__badge">${escapeHtml(referenceSourceLabel(image))}</span>
      <div class="desk-thumb__actions">
        <button type="button" data-ref-action="open" title="打开原图" aria-label="打开原图">↗</button>
        <button type="button" data-ref-action="left" title="左移" aria-label="左移"${index <= 0 ? ' disabled' : ''}>‹</button>
        <button type="button" data-ref-action="right" title="右移" aria-label="右移"${index >= total - 1 ? ' disabled' : ''}>›</button>
        <button type="button" data-ref-action="remove" title="移除参考图" aria-label="移除参考图">×</button>
      </div>
    `;
    item.querySelectorAll('button').forEach(button => {
      button.addEventListener('pointerdown', event => event.stopPropagation());
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        const action = button.dataset.refAction;
        if (action === 'open') openReferenceImage(image);
        if (action === 'left') moveReference(nodeId, index, -1);
        if (action === 'right') moveReference(nodeId, index, 1);
        if (action === 'remove') removeReferenceAt(nodeId, index);
      });
    });
    return item;
  }

  function getProviderFromNode(node) {
    return node?.querySelector('.desk-segment button.is-active')?.dataset.provider || 'gpt';
  }

  function getPromptModeFromNode(node, fallback = 'smart') {
    return DesktopState.normalizePromptMode(
      node?.querySelector('[data-field="promptMode"], #deskPromptModeSelect')?.value
        || node?.querySelector('.desk-prompt-mode button.is-active')?.dataset.promptMode,
      fallback
    );
  }

  function applyPromptModeToNode(node, mode) {
    const normalized = DesktopState.normalizePromptMode(mode, 'smart');
    const select = node?.querySelector('[data-field="promptMode"], #deskPromptModeSelect');
    if (select) select.value = normalized;
    node?.querySelectorAll('.desk-prompt-mode button[data-prompt-mode]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.promptMode === normalized);
    });
  }

  function upgradeGptRouteControls(node) {
    if (!node) return;
    const promptMode = node.querySelector('.desk-prompt-mode');
    if (!promptMode) return;
    let legacyThirdPartyChecked = false;
    node.querySelectorAll('#deskThirdPartyApiToggle, #gptThirdPartyApiToggle, [data-field="useThirdPartyApi"]').forEach(control => {
      legacyThirdPartyChecked = legacyThirdPartyChecked || !!control.checked;
      control.closest('label')?.remove();
    });
    promptMode.querySelectorAll('label').forEach(label => {
      const labelText = label.querySelector('span')?.textContent?.trim() || '';
      const checkbox = label.querySelector('input[type="checkbox"]');
      if (checkbox && /第三方\s*4K/.test(labelText)) {
        legacyThirdPartyChecked = legacyThirdPartyChecked || checkbox.checked;
        label.remove();
      }
    });

    let routeSelect = node.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    if (!routeSelect) {
      const routeSelectId = node.dataset.nodeId === 'input' ? ' id="deskGptProviderRouteSelect"' : '';
      const routeLabel = document.createElement('label');
      routeLabel.innerHTML = `<span>线路</span><select${routeSelectId} class="desk-select" data-field="gptProviderRoute">${optionListHtml(GPT_PROVIDER_ROUTE_OPTIONS, 'codex')}</select>`;
      const typeLabel = promptMode.querySelector('[data-field="gptTaskType"], #deskGptTaskTypeSelect')?.closest('label');
      if (typeLabel?.nextSibling) {
        promptMode.insertBefore(routeLabel, typeLabel.nextSibling);
      } else {
        promptMode.appendChild(routeLabel);
      }
      routeSelect = routeLabel.querySelector('[data-field="gptProviderRoute"]');
    }
    if (routeSelect) {
      GPT_PROVIDER_ROUTE_OPTIONS.forEach(item => {
        if (Array.from(routeSelect.options).some(option => option.value === item.value)) return;
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = item.label;
        routeSelect.appendChild(option);
      });
    }
    if (legacyThirdPartyChecked && routeSelect && DesktopState.normalizeGptProviderRoute(routeSelect.value, 'codex') === 'codex') {
      routeSelect.value = 'third_party_image_api';
    }
  }

  function applyGptTaskTypeToNode(node, taskType) {
    if (!node) return 'image';
    upgradeGptRouteControls(node);
    const normalized = DesktopState.normalizeGptTaskType(taskType, 'image');
    const typeSelect = node.querySelector('[data-field="gptTaskType"], #deskGptTaskTypeSelect');
    const routeSelect = node.querySelector('[data-field="gptProviderRoute"], #deskGptProviderRouteSelect');
    if (typeSelect) typeSelect.value = normalized;
    if (routeSelect) {
      const locked = normalized !== 'image';
      if (locked) routeSelect.value = 'chatgpt_pool';
      routeSelect.disabled = locked;
      routeSelect.title = locked ? 'PPT/PSD 任务只能走账号池 Web API 线路' : '';
      applyGptModelRouteToNode(node, routeSelect.value);
    }
    node.classList.toggle('is-editable-file-task', normalized !== 'image');
    return normalized;
  }

  function setTextStyleMenuOpen(node, open) {
    const menu = node?.querySelector('[data-text-style-menu]');
    if (!menu) return;
    node.classList.toggle('is-style-menu-open', !!open);
    menu.hidden = !open;
  }

  function closeAllTextStyleMenus(exceptNode = null) {
    document.querySelectorAll('.desk-node--text.is-style-menu-open').forEach(node => {
      if (exceptNode && node === exceptNode) return;
      setTextStyleMenuOpen(node, false);
    });
  }

  function setTextNodeValue(node, nodeState, value) {
    const next = String(value || '');
    nodeState.text = next;
    const input = node.querySelector('[data-text-node-input]');
    if (input) input.value = next;
    DesktopState.saveSettings();
  }

  function updateTextStyleTag(node, nodeState) {
    const target = node?.querySelector('[data-text-style-tags]');
    if (!target) return;
    const presetId = nodeState?.stylePresetId || '';
    target.innerHTML = textStyleTagHtml(presetId);
    target.hidden = !getTextStylePreset(presetId);
  }

  function setTextNodeStyle(node, nodeState, presetId) {
    const preset = getTextStylePreset(presetId);
    nodeState.stylePresetId = preset ? preset.id : '';
    updateTextStyleTag(node, nodeState);
    DesktopState.saveSettings();
    return preset;
  }

  function selectTextNodePreset(node, nodeState, presetId) {
    const preset = setTextNodeStyle(node, nodeState, presetId);
    if (!preset) return;
    setTextStyleMenuOpen(node, false);
    DesktopResults.showTransientMessage(`已选择「${preset.title}」风格。`);
  }

  function clearTextNodeStyle(node, nodeState) {
    const hadStyle = !!nodeState.stylePresetId;
    setTextNodeStyle(node, nodeState, '');
    if (hadStyle) DesktopResults.showTransientMessage('已移除风格标签。');
  }

  function ensureTextCopyFallback() {
    let modal = document.getElementById('deskTextCopyFallback');
    if (modal) return modal;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="desk-text-copy-fallback" id="deskTextCopyFallback" aria-hidden="true">
        <div class="desk-text-copy-fallback__panel desk-glass">
          <header>
            <div>
              <p>Clipboard</p>
              <h2>手动复制</h2>
            </div>
            <button type="button" data-copy-fallback-close title="关闭" aria-label="关闭">×</button>
          </header>
          <p class="desk-text-copy-fallback__hint">系统剪贴板受限，文本已选中。</p>
          <textarea data-copy-fallback-text readonly></textarea>
          <footer>
            <button type="button" data-copy-fallback-select>重新选中</button>
            <button type="button" class="is-primary" data-copy-fallback-close>完成</button>
          </footer>
        </div>
      </div>
    `);
    modal = document.getElementById('deskTextCopyFallback');
    modal?.addEventListener('click', event => {
      if (event.target === modal || event.target.closest('[data-copy-fallback-close]')) {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        return;
      }
      if (event.target.closest('[data-copy-fallback-select]')) {
        event.preventDefault();
        selectTextCopyFallback();
      }
    });
    return modal;
  }

  function selectTextCopyFallback() {
    const textarea = document.querySelector('#deskTextCopyFallback [data-copy-fallback-text]');
    if (!textarea) return;
    textarea.focus({ preventScroll: true });
    textarea.select();
    try { textarea.setSelectionRange(0, textarea.value.length); } catch (e) {}
  }

  function showTextCopyFallback(text) {
    const modal = ensureTextCopyFallback();
    const textarea = modal.querySelector('[data-copy-fallback-text]');
    if (textarea) textarea.value = String(text || '');
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    window.requestAnimationFrame(() => selectTextCopyFallback());
  }

  function copyTextWithTemporaryTextarea(value) {
    const ta = document.createElement('textarea');
    const previousFocus = document.activeElement;
    ta.value = value;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.width = '1px';
    ta.style.height = '1px';
    ta.style.padding = '0';
    ta.style.border = '0';
    ta.style.opacity = '0.01';
    ta.style.zIndex = '-1';
    document.body.appendChild(ta);
    try {
      ta.focus({ preventScroll: true });
      ta.select();
      ta.setSelectionRange(0, value.length);
      return document.execCommand && document.execCommand('copy') === true;
    } catch (e) {
      return false;
    } finally {
      document.body.removeChild(ta);
      if (previousFocus && typeof previousFocus.focus === 'function') {
        try { previousFocus.focus({ preventScroll: true }); } catch (e) {}
      }
    }
  }

  async function copyTextToClipboardLocal(text, successMessage = '已复制') {
    const value = String(text || '');
    if (!value) {
      DesktopResults.showTransientMessage('暂无可复制内容。');
      return 'empty';
    }
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        DesktopResults.showTransientMessage(successMessage);
        return 'copied';
      } catch (e) {}
    }
    if (copyTextWithTemporaryTextarea(value)) {
      DesktopResults.showTransientMessage(successMessage);
      return 'copied';
    }
    showTextCopyFallback(value);
    DesktopResults.showTransientMessage('自动复制受限，已打开手动复制框。');
    return 'manual';
  }

  function setPolishCopyButtonState(button, state) {
    if (!button) return;
    const labels = {
      idle: button.dataset.copyDefaultLabel || '复制当前',
      copying: '复制中',
      copied: '已复制',
      manual: '手动复制',
      empty: '无内容',
      failed: '复制受限'
    };
    if (!button.dataset.copyDefaultLabel) button.dataset.copyDefaultLabel = button.textContent.trim() || '复制当前';
    if (button._copyFeedbackTimer) window.clearTimeout(button._copyFeedbackTimer);
    button.dataset.copyState = state;
    button.textContent = labels[state] || labels.idle;
    button.setAttribute('aria-live', 'polite');
    button.setAttribute('aria-busy', state === 'copying' ? 'true' : 'false');
    if (state !== 'copying') button.disabled = false;
    if (state === 'copied' || state === 'manual' || state === 'empty' || state === 'failed') {
      button._copyFeedbackTimer = window.setTimeout(() => {
        button.dataset.copyState = 'idle';
        button.textContent = button.dataset.copyDefaultLabel || '复制当前';
        button.setAttribute('aria-busy', 'false');
      }, state === 'manual' ? 2200 : 1500);
    }
  }

  function ensureTextPolishModal() {
    let modal = document.getElementById('deskTextPolishModal');
    if (modal) return modal;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="desk-text-polish-modal" id="deskTextPolishModal" aria-hidden="true">
        <div class="desk-text-polish-modal__panel desk-glass">
          <header class="desk-text-polish-modal__header">
            <div class="desk-text-polish-modal__title">
              <p>Prompt Skill</p>
              <h2>GPT 润色结果</h2>
            </div>
            <button type="button" class="desk-text-polish-modal__close" data-polish-close title="关闭" aria-label="关闭"></button>
          </header>
          <div class="desk-text-polish-modal__grid" role="listbox" aria-label="润色候选提示">
            ${TEXT_POLISH_VARIANTS.map(item => `
              <button type="button" class="desk-text-polish-modal__card${item.id === 'full' ? ' is-active' : ''}" data-polish-variant-card data-polish-variant="${item.id}" aria-pressed="${item.id === 'full' ? 'true' : 'false'}">
                <span class="desk-text-polish-modal__card-head">
                  <strong>${escapeHtml(item.title)}</strong>
                  <em data-polish-count="${item.id}">0 字</em>
                </span>
                <span class="desk-text-polish-modal__card-hint">${escapeHtml(item.hint)}</span>
                <span class="desk-text-polish-modal__card-text" data-polish-card-text="${item.id}"></span>
              </button>
            `).join('')}
          </div>
          <footer class="desk-text-polish-modal__footer">
            <div class="desk-text-polish-modal__meta" data-polish-meta></div>
            <div class="desk-text-polish-modal__actions">
              <button type="button" class="desk-text-polish-modal__copy" data-polish-copy>复制当前</button>
              <button type="button" class="desk-text-polish-modal__done is-primary" data-polish-close>完成</button>
            </div>
          </footer>
        </div>
      </div>
    `);
    modal = document.getElementById('deskTextPolishModal');
    modal?.addEventListener('click', event => {
      if (event.target === modal || event.target.closest('[data-polish-close]')) {
        closeTextPolishModal();
        return;
      }
      const variantButton = event.target.closest('[data-polish-variant-card]');
      if (variantButton) {
        event.preventDefault();
        applyTextPolishVariant(variantButton.dataset.polishVariant || 'full');
        return;
      }
      const copyButton = event.target.closest('[data-polish-copy]');
      if (copyButton) {
        event.preventDefault();
        setPolishCopyButtonState(copyButton, 'copying');
        copyTextToClipboardLocal(getTextPolishVariantText(textPolishState?.variant || 'full'), '当前提示词已复制。')
          .then(status => setPolishCopyButtonState(copyButton, status || 'failed'))
          .catch(() => setPolishCopyButtonState(copyButton, 'failed'));
      }
    });
    return modal;
  }

  function closeTextPolishModal() {
    const modal = document.getElementById('deskTextPolishModal');
    modal?.classList.remove('is-open');
    modal?.setAttribute('aria-hidden', 'true');
  }

  function getTextPolishVariantText(variant) {
    if (!textPolishState) return '';
    if (variant === 'compact') return textPolishState.compactPrompt || '';
    if (variant === 'original') return textPolishState.originalText || '';
    return textPolishState.fullPrompt || '';
  }

  function renderTextPolishModal() {
    const modal = ensureTextPolishModal();
    const meta = modal.querySelector('[data-polish-meta]');
    const variant = textPolishState?.variant || 'full';
    TEXT_POLISH_VARIANTS.forEach(item => {
      const text = getTextPolishVariantText(item.id);
      const cardText = modal.querySelector(`[data-polish-card-text="${item.id}"]`);
      const count = modal.querySelector(`[data-polish-count="${item.id}"]`);
      if (cardText) cardText.textContent = text || '暂无内容';
      if (count) count.textContent = `${Array.from(text || '').length} 字`;
    });
    modal.querySelectorAll('[data-polish-variant-card]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.polishVariant === variant);
      button.setAttribute('aria-pressed', button.dataset.polishVariant === variant ? 'true' : 'false');
    });
    if (meta) {
      const modules = (textPolishState?.modules || []).join(' / ');
      const model = textPolishState?.model || '';
      meta.textContent = [model, modules].filter(Boolean).join(' · ');
    }
  }

  function applyTextPolishVariant(variant) {
    if (!textPolishState) return;
    const node = getNodeElement(textPolishState.nodeId);
    const nodeState = DesktopState.state.canvas.nodes[textPolishState.nodeId];
    if (!node || !nodeState) return;
    const normalized = TEXT_POLISH_VARIANTS.some(item => item.id === variant) ? variant : 'full';
    const text = getTextPolishVariantText(normalized);
    textPolishState.variant = normalized;
    setTextNodeValue(node, nodeState, text || '');
    renderTextPolishModal();
  }

  function openTextPolishModal(payload) {
    textPolishState = {
      nodeId: payload.nodeId,
      originalText: payload.originalText || '',
      fullPrompt: payload.fullPrompt || '',
      compactPrompt: payload.compactPrompt || payload.fullPrompt || '',
      modules: payload.modules || [],
      model: payload.model || '',
      variant: 'full'
    };
    const modal = ensureTextPolishModal();
    renderTextPolishModal();
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
  }

  async function runTextNodeGptPolish(node, nodeState, triggerButton) {
    const originalText = String(nodeState.text || node.querySelector('[data-text-node-input]')?.value || '').trim();
    if (!originalText) {
      DesktopResults.showTransientMessage('先在文本节点里输入提示词片段。');
      return;
    }
    if (!window.DesktopApi?.polishPromptText) {
      throw new Error('润色 API 未加载');
    }
    const previousLabel = triggerButton?.textContent || '';
    if (triggerButton) {
      triggerButton.disabled = true;
      triggerButton.textContent = '润色中';
    }
    try {
      const result = await window.DesktopApi.polishPromptText({ text: originalText });
      const fullPrompt = String(result.full_prompt || '').trim();
      const compactPrompt = String(result.compact_prompt || fullPrompt).trim();
      if (!fullPrompt) throw new Error('润色结果为空');
      setTextNodeValue(node, nodeState, fullPrompt);
      openTextPolishModal({
        nodeId: node.dataset.nodeId,
        originalText,
        fullPrompt,
        compactPrompt,
        modules: result.modules || [],
        model: result.model || ''
      });
      DesktopResults.showTransientMessage('已回填完整提示词。');
    } finally {
      if (triggerButton) {
        triggerButton.disabled = false;
        triggerButton.textContent = previousLabel || 'Gpt 润色';
      }
    }
  }

  function composePromptWithTextStyles(prompt, styleIds = []) {
    let result = String(prompt || '').trim();
    const seen = new Set();
    (styleIds || []).forEach(styleId => {
      const preset = getTextStylePreset(styleId);
      if (!preset || seen.has(preset.id)) return;
      seen.add(preset.id);
      const template = String(preset.promptTemplate || '').trim();
      if (!template) return;
      if (preset.id === 'sketchnote') {
        result = result ? `${template}${result}` : template;
      } else {
        result = result ? `${result}\n\n${template}` : template;
      }
    });
    return result;
  }

  function normalizeImageSourceFromNode(node) {
    if (!node || node.type !== 'image') return null;
    const source = node.imageData || node.imageUrl || '';
    if (!source) return null;
    return {
      id: node.sourceAssetId || `image-node:${node.id}`,
      assetId: node.sourceAssetId || '',
      sourceNodeId: node.id,
      name: node.imageName || `${node.id}.png`,
      title: node.sourceTitle || node.imageName || `${node.id}.png`,
      prompt: node.sourcePrompt || '',
      file: node.sourceFile || '',
      taskId: node.sourceTaskId || '',
      provider: node.sourceProvider || '',
      type: node.mimeType || 'image/png',
      url: node.imageUrl || source,
      base64: node.imageData || '',
      imageData: node.imageData || '',
      imageUrl: node.imageUrl || '',
      source: node.sourceKind || 'image-node'
    };
  }

  function normalizePoseReferenceFromNode(node) {
    if (!node || node.type !== 'pose') return null;
    const source = node.exportImage || node.previewImage || '';
    if (!source) return null;
    return {
      id: `pose-node:${node.id}`,
      assetId: '',
      sourceNodeId: node.id,
      name: `${poseDisplayTitle(node, node.id)}.png`,
      title: poseDisplayTitle(node, '姿态参考图'),
      prompt: '3D mannequin pose reference',
      file: '',
      taskId: '',
      provider: '',
      type: 'image/png',
      url: source,
      base64: source.startsWith('data:') ? source : '',
      imageData: source.startsWith('data:') ? source : '',
      imageUrl: source.startsWith('data:') ? '' : source,
      source: 'pose-node'
    };
  }

  function getLayoutInputImages(layoutNodeId) {
    const layoutNode = DesktopState.state.canvas.nodes[layoutNodeId];
    if (!layoutNode || layoutNode.type !== 'layout') return [];
    const direct = Array.isArray(layoutNode.layoutInputImages)
      ? layoutNode.layoutInputImages.map((image, index) => ({
        id: image.id || `direct:${image.taskId || image.imageUrl || image.name || index}`,
        name: image.name || image.title || '输入图片',
        type: image.type || image.mimeType || 'image/png',
        url: image.imageUrl || image.url || image.imageData || image.base64 || '',
        base64: image.imageData || image.base64 || '',
        imageData: image.imageData || image.base64 || '',
        imageUrl: image.imageUrl || image.url || '',
        taskId: image.taskId || '',
        source: image.source || 'layout'
      }))
      : [];
    const fromEdges = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === layoutNodeId)
      .map(edge => normalizeImageSourceFromNode(DesktopState.state.canvas.nodes[edge.from]))
      .filter(Boolean);
    const seen = new Set();
    return [...direct, ...fromEdges].filter(item => {
      const key = item.id || item.url || item.base64 || item.name;
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function getLayoutInputCount(layoutNodeId) {
    return getLayoutInputImages(layoutNodeId).length;
  }

  function updateLayoutInputCount(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'layout') return;
    const el = getNodeElement(nodeId);
    const target = el?.querySelector('[data-layout-input-count]');
    if (!target) return;
    const count = getLayoutInputCount(nodeId);
    target.textContent = count ? `已接入 ${count} 张图` : '可接入图片';
  }

  function getConnectedImageReferences(inputNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === inputNodeId)
      .map(edge => DesktopState.state.canvas.nodes[edge.from])
      .filter(node => (node?.type === 'image' && (node.imageData || node.imageUrl)) || (node?.type === 'layout' && node.layoutExport) || (node?.type === 'pose' && (node.exportImage || node.previewImage)))
      .map(node => {
        if (node.type === 'image') return normalizeImageSourceFromNode(node);
        if (node.type === 'pose') return normalizePoseReferenceFromNode(node);
        return {
          id: `layout:${node.id}`,
          sourceNodeId: node.id,
          name: `${node.id}.png`,
          title: node.layoutTitle || `${node.id}.png`,
          type: 'image/png',
          url: node.layoutExport,
          base64: node.layoutExport,
          imageData: node.layoutExport,
          imageUrl: '',
          source: 'layout'
        };
      })
      .filter(Boolean);
  }

  function getConnectedTextNodes(inputNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === inputNodeId)
      .map(edge => DesktopState.state.canvas.nodes[edge.from])
      .filter(node => node?.type === 'text');
  }

  function splitBatchPromptItems(prompt) {
    return String(prompt || '')
      .split(/\n\s*\n|\r?\n/)
      .map(item => item.trim())
      .filter(Boolean);
  }

  function getBatchPromptItems(inputNodeId) {
    const textNodes = getConnectedTextNodes(inputNodeId);
    const nodePrompts = textNodes
      .map(node => ({
        text: String(node.text || '').trim(),
        styleId: node.stylePresetId || ''
      }))
      .filter(item => item.text);
    if (nodePrompts.length > 1) {
      return nodePrompts.map(item => composePromptWithTextStyles(item.text, [item.styleId].filter(Boolean)));
    }
    if (nodePrompts.length === 1) {
      const parts = splitBatchPromptItems(nodePrompts[0].text);
      return parts.map(part => composePromptWithTextStyles(part, [nodePrompts[0].styleId].filter(Boolean)));
    }
    return [];
  }

  function mergePromptWithConnectedText(prompt, inputNodeId) {
    const textNodes = getConnectedTextNodes(inputNodeId);
    const styleIds = textNodes.map(node => node.stylePresetId || '').filter(Boolean);
    const basePrompt = [
      ...textNodes.map(node => String(node.text || '').trim()).filter(Boolean),
      String(prompt || '').trim()
    ]
      .filter(Boolean)
      .join('\n\n');
    return composePromptWithTextStyles(basePrompt, styleIds);
  }

  function getVisibleInputPrompt(inputNodeId) {
    return mergePromptWithConnectedText('', inputNodeId);
  }

  function readInputNodeConfig(nodeId) {
    const node = getNodeElement(nodeId);
    if (!node) throw new Error('模型节点不存在');
    if (nodeId === 'input') {
      readFormToState();
      const batchPrompts = getBatchPromptItems(nodeId);
      return {
        nodeId,
        prompt: getVisibleInputPrompt(nodeId),
        batchPrompts,
        provider: DesktopState.state.provider,
        params: { ...DesktopState.state.params },
        batchMode: !!DesktopState.state.params.batchMode,
        referenceImages: [...DesktopState.state.referenceImages, ...getConnectedImageReferences(nodeId)]
      };
    }

    const batchPrompts = getBatchPromptItems(nodeId);
    return {
      nodeId,
      prompt: getVisibleInputPrompt(nodeId),
      batchPrompts,
      provider: getProviderFromNode(node),
      batchMode: !!node.querySelector('[data-field="batchMode"]')?.checked,
      params: {
        ratio: node.querySelector('[data-field="ratio"]')?.value || '9:16',
        resolution: node.querySelector('[data-field="resolution"]')?.value || '2k',
        model: typeof DesktopState.normalizeGoogleModel === 'function'
          ? DesktopState.normalizeGoogleModel(node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
          : (node.querySelector('[data-field="model"]')?.value || DEFAULT_GOOGLE_MODEL),
        quality: node.querySelector('[data-field="quality"]')?.value || 'auto',
        imageCount: node.querySelector('[data-field="imageCount"]')?.value || 1,
        moderation: node.querySelector('[data-field="moderation"]')?.value || 'auto',
        gptTaskType: applyGptTaskTypeToNode(node, node.querySelector('[data-field="gptTaskType"]')?.value),
        gptProviderRoute: DesktopState.normalizeGptTaskType(node.querySelector('[data-field="gptTaskType"]')?.value, 'image') === 'image'
          ? DesktopState.normalizeGptProviderRoute(node.querySelector('[data-field="gptProviderRoute"]')?.value, 'codex')
          : 'chatgpt_pool',
        useThirdPartyApi: DesktopState.normalizeGptProviderRoute(node.querySelector('[data-field="gptProviderRoute"]')?.value, 'codex') === 'third_party_image_api',
        gptMainModel: DesktopState.normalizeGptMainModel(node.querySelector('[data-field="gptMainModel"]')?.value, 'gpt-5.5'),
        reasoningEffort: DesktopState.normalizeReasoningEffort(node.querySelector('[data-field="reasoningEffort"]')?.value, 'medium'),
        promptMode: getPromptModeFromNode(node, 'smart')
      },
      referenceImages: [...getNodeReferenceImages(nodeId), ...getConnectedImageReferences(nodeId)]
    };
  }

  function syncUpscaleNodeStateFromDom(node) {
    const nodeId = node?.dataset?.nodeId || '';
    const nodeState = nodeId ? DesktopState.state.canvas.nodes[nodeId] : null;
    if (!node || !nodeState || nodeState.type !== 'upscale') return null;
    nodeState.model = node.querySelector('[data-upscale-field="model"]')?.value || nodeState.model || '4x-UltraSharp';
    nodeState.tileSize = DesktopState.clamp(node.querySelector('[data-upscale-field="tileSize"]')?.value, 64, 2048, 256);
    nodeState.tileOverlap = DesktopState.clamp(node.querySelector('[data-upscale-field="tileOverlap"]')?.value, 0, 256, 32);
    nodeState.device = 'auto';
    nodeState.output = readOutputControlsFromNode(node, nodeState.output || { archiveEnabled: true, telegramEnabled: false });
    nodeState.output.archiveEnabled = true;
    return nodeState;
  }

  function getIncomingUpscaleEdges(nodeId, type = '') {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.to === nodeId && DesktopState.state.canvas.nodes[edge.from])
      .filter(edge => !type || DesktopState.state.canvas.nodes[edge.from]?.type === type);
  }

  function getOutgoingUpscaleImageEdges(nodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image');
  }

  function isManualUpscaleFlow(nodeId) {
    return getIncomingUpscaleEdges(nodeId, 'image').length > 0 && getOutgoingUpscaleImageEdges(nodeId).length > 0;
  }

  function refreshUpscaleNodeMode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'upscale' || !el) return;
    const manualMode = isManualUpscaleFlow(nodeId);
    const actions = el.querySelector('[data-upscale-actions]');
    const output = DesktopState.state.outputs?.[nodeId] || {};
    const isBusy = DesktopState.isInFlight?.(output.status);
    el.classList.toggle('has-manual-upscale-flow', manualMode);
    if (actions) {
      actions.classList.toggle('is-visible', manualMode);
      actions.setAttribute('aria-hidden', manualMode ? 'false' : 'true');
    }
    el.querySelectorAll('[data-output-telegram]').forEach(input => {
      input.disabled = !manualMode || isBusy;
    });
    el.querySelectorAll('[data-result-run]').forEach(button => {
      button.disabled = !manualMode || isBusy;
    });
  }

  function updateUpscaleInputCount(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'upscale' || !el) return;
    refreshUpscaleNodeMode(nodeId);
  }

  function readUpscaleNodeConfigForReference(nodeId, firstRef, options = {}) {
    const node = getNodeElement(nodeId);
    const nodeState = syncUpscaleNodeStateFromDom(node);
    if (!node || !nodeState) throw new Error('高清放大节点不存在');
    if (!firstRef) throw new Error('请先连接一张图片到高清放大节点');
    const model = nodeState.model || '4x-UltraSharp';
    return {
      nodeId,
      prompt: options.prompt || `高清放大：${firstRef.title || firstRef.name || model}`,
      provider: 'upscale',
      batchMode: false,
      expectedImageOutputCount: 1,
      params: {
        model,
        tileSize: nodeState.tileSize || 256,
        tileOverlap: nodeState.tileOverlap || 32,
        device: nodeState.device || 'auto',
        archiveEnabled: true,
        telegramEnabled: options.telegramEnabled !== undefined
          ? options.telegramEnabled === true
          : nodeState.output?.telegramEnabled === true
      },
      referenceImages: [firstRef]
    };
  }

  function readUpscaleNodeConfig(nodeId) {
    const refs = getConnectedImageReferences(nodeId);
    if (!refs.length) throw new Error('请先连接一张图片到高清放大节点');
    return readUpscaleNodeConfigForReference(nodeId, refs[0]);
  }

  function findInputForResult(resultNodeId) {
    const edge = (DesktopState.state.canvas.edges || []).find(item => item.to === resultNodeId);
    if (edge && getNodeElement(edge.from)) return edge.from;
    return '';
  }

  function resolveResultNodeIdForRun(nodeId = 'input') {
    const directNode = DesktopState.state.canvas.nodes[nodeId];
    if (directNode?.type !== 'input') return nodeId;
    const node = getNodeElement(nodeId);
    const storedTaskType = nodeId === 'input'
      ? DesktopState.state.params?.gptTaskType
      : directNode.params?.gptTaskType;
    const taskType = DesktopState.normalizeGptTaskType(
      node?.querySelector('[data-field="gptTaskType"]')?.value || storedTaskType,
      'image'
    );
    if (taskType === 'image') return nodeId;
    const edge = (DesktopState.state.canvas.edges || []).find(item => (
      item.from === nodeId
      && DesktopState.state.canvas.nodes[item.to]?.type === 'file_output'
    ));
    if (!edge) throw new Error('PPT/PSD 请先把模型节点连接到文件结果节点。');
    return edge.to;
  }

  function readConfigForResult(resultNodeId) {
    const directNode = DesktopState.state.canvas.nodes[resultNodeId];
    if (directNode?.type === 'upscale') {
      return readUpscaleNodeConfig(resultNodeId);
    }
    if (directNode?.type === 'input') {
      const config = readInputNodeConfig(resultNodeId);
      const taskType = DesktopState.normalizeGptTaskType(config.params?.gptTaskType, 'image');
      if (taskType !== 'image') {
        throw new Error('PPT/PSD 请先把模型节点连接到文件结果节点。');
      }
      const outputControls = readOutputControlsForTask(resultNodeId);
      config.params = {
        ...(config.params || {}),
        archiveEnabled: outputControls.archiveEnabled !== false,
        telegramEnabled: outputControls.telegramEnabled !== false
      };
      return config;
    }
    const inputNodeId = findInputForResult(resultNodeId);
    if (!inputNodeId) throw new Error('请先手动连接模型节点到文件结果节点');
    const config = readInputNodeConfig(inputNodeId);
    const resultType = DesktopState.state.canvas.nodes[resultNodeId]?.type;
    const taskType = DesktopState.normalizeGptTaskType(config.params?.gptTaskType, 'image');
    if (resultType === 'file_output' && taskType === 'image') {
      throw new Error('文件结果节点只接收 PPT/PSD，请直接从模型节点生成图片任务。');
    }
    if (resultType === 'output' && taskType !== 'image') {
      throw new Error('PPT/PSD 请连接到文件结果节点。');
    }
    const outputControls = readOutputControlsForTask(inputNodeId, resultNodeId);
    config.params = {
      ...(config.params || {}),
      archiveEnabled: outputControls.archiveEnabled !== false,
      telegramEnabled: outputControls.telegramEnabled !== false
    };
    return config;
  }

  function batchPromptItemsForConfig(config) {
    const explicit = Array.isArray(config?.batchPrompts)
      ? config.batchPrompts.map(item => String(item || '').trim()).filter(Boolean)
      : [];
    return explicit.length ? explicit : splitBatchPromptItems(config?.prompt);
  }

  function imageCountForProvider(config) {
    const provider = String(config?.provider || 'gpt');
    if (provider === 'gpt') {
      return DesktopState.clamp(config?.params?.imageCount, 1, 8, 1);
    }
    return 1;
  }

  function expectedImageOutputCount(config) {
    const explicit = Number(config?.expectedImageOutputCount || config?.requestedImageCount || 0);
    if (explicit > 0) return Math.max(1, Math.floor(explicit));
    const taskType = DesktopState.normalizeGptTaskType(config?.params?.gptTaskType, 'image');
    if (taskType !== 'image') return 0;
    const promptCount = config?.batchMode ? batchPromptItemsForConfig(config).length : 1;
    return Math.max(1, promptCount || 1) * imageCountForProvider(config);
  }

  function getConnectedOutputImageNodeIds(modelNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === modelNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image')
      .sort((a, b) => {
        const aSlot = Number.isFinite(Number(a.outputSlot)) ? Number(a.outputSlot) : Number.MAX_SAFE_INTEGER;
        const bSlot = Number.isFinite(Number(b.outputSlot)) ? Number(b.outputSlot) : Number.MAX_SAFE_INTEGER;
        if (aSlot !== bSlot) return aSlot - bSlot;
        return String(a.id || '').localeCompare(String(b.id || ''));
      })
      .map(edge => edge.to);
  }

  function getConnectedUpscaleNodeIds(modelNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === modelNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'upscale')
      .map(edge => edge.to);
  }

  function getRunnableUpscaleNodeIds(modelNodeId) {
    return getConnectedUpscaleNodeIds(modelNodeId)
      .filter(nodeId => getOutgoingUpscaleImageEdges(nodeId).length > 0);
  }

  function getOutputImageEdges(modelNodeId) {
    return (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === modelNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image')
      .sort((a, b) => {
        const aSlot = Number.isFinite(Number(a.outputSlot)) ? Number(a.outputSlot) : Number.MAX_SAFE_INTEGER;
        const bSlot = Number.isFinite(Number(b.outputSlot)) ? Number(b.outputSlot) : Number.MAX_SAFE_INTEGER;
        if (aSlot !== bSlot) return aSlot - bSlot;
        return String(a.id || '').localeCompare(String(b.id || ''));
      });
  }

  function isEmptyAutoOutputImageNode(node) {
    return node?.type === 'image'
      && node.sourceKind === 'model-output'
      && !node.imageData
      && !node.imageUrl
      && !node.sourceFile
      && !node.sourceTaskId
      && !node.sourceAssetId;
  }

  function pruneExtraEmptyOutputImages(modelNodeId, keepCount) {
    const edges = getOutputImageEdges(modelNodeId);
    let changed = false;
    edges.slice(Math.max(0, keepCount)).forEach(edge => {
      const node = DesktopState.state.canvas.nodes[edge.to];
      if (!isEmptyAutoOutputImageNode(node)) return;
      delete DesktopState.state.canvas.nodes[edge.to];
      const element = getNodeElement(edge.to);
      if (element) element.remove();
      changed = true;
    });
    if (changed) {
      DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || [])
        .filter(edge => DesktopState.state.canvas.nodes[edge.from] && DesktopState.state.canvas.nodes[edge.to]);
    }
    return changed;
  }

  function assignImageOutputSlots(modelNodeId) {
    const edges = getOutputImageEdges(modelNodeId);
    edges.forEach((edge, index) => {
      edge.outputSlot = index;
    });
    return edges.map(edge => edge.to);
  }

  function ratioToMeta(ratio = '1:1') {
    const [w, h] = String(ratio || '1:1').split(':').map(Number);
    const width = Number.isFinite(w) && w > 0 ? w : 1;
    const height = Number.isFinite(h) && h > 0 ? h : 1;
    return { width, height };
  }

  function outputNodeCenterForSlot(modelNodeId, slotIndex, config) {
    const model = DesktopState.state.canvas.nodes[modelNodeId];
    const bounds = getNodeBoundsById(modelNodeId) || { x: model?.x || 120, y: model?.y || 120, width: model?.width || 512, height: model?.height || 360 };
    const meta = ratioToMeta(config?.params?.ratio || '1:1');
    const size = getImageNodeSize(meta);
    const columns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(Math.max(1, expectedImageOutputCount(config))))));
    const col = slotIndex % columns;
    const row = Math.floor(slotIndex / columns);
    return {
      x: bounds.x + bounds.width + 180 + col * (size.width + 32) + size.width / 2,
      y: bounds.y + 82 + row * (size.height + 32) + size.height / 2
    };
  }

  function modelOutputPopOrigin(modelNodeId) {
    const anchor = getAnchor(modelNodeId, 'right');
    return {
      x: anchor.x + 10,
      y: anchor.y
    };
  }

  function createOutputImageNode(modelNodeId, slotIndex, config) {
    const meta = ratioToMeta(config?.params?.ratio || '1:1');
    const nodeId = insertImageNode({
      imageName: `生成结果 ${slotIndex + 1}`,
      mimeType: 'image/png',
      source: 'model-output',
      meta
    }, outputNodeCenterForSlot(modelNodeId, slotIndex, config), {
      popIndex: slotIndex,
      popOrigin: modelOutputPopOrigin(modelNodeId)
    });
    const edgeId = connectNodes(modelNodeId, nodeId, { outputSlot: slotIndex, quiet: true });
    const edge = (DesktopState.state.canvas.edges || []).find(item => item.id === edgeId);
    if (edge) edge.outputSlot = slotIndex;
    return nodeId;
  }

  function ensureImageOutputsForConfig(resultNodeId, config) {
    const modelNodeId = DesktopState.state.canvas.nodes[resultNodeId]?.type === 'input'
      ? resultNodeId
      : (config?.nodeId || findInputForResult(resultNodeId));
    if (!modelNodeId || DesktopState.state.canvas.nodes[modelNodeId]?.type !== 'input') return [];
    const expected = expectedImageOutputCount(config);
    config.expectedImageOutputCount = expected;
    if (!expected) return [];
    const existing = getConnectedOutputImageNodeIds(modelNodeId);
    if (getRunnableUpscaleNodeIds(modelNodeId).length && !existing.length) {
      return [];
    }
    pruneExtraEmptyOutputImages(modelNodeId, expected);
    for (let index = existing.length; index < expected; index += 1) {
      existing.push(createOutputImageNode(modelNodeId, index, config));
    }
    const ordered = assignImageOutputSlots(modelNodeId);
    updateLinkPath();
    DesktopState.saveSettings();
    return ordered.slice(0, expected);
  }

  function addNode(type, worldPoint) {
    const nodeType = normalizeNodeMenuType(type);
    const node = createNodeState(nodeType);
    if (worldPoint) {
      node.x = worldPoint.x - node.width / 2;
      node.y = worldPoint.y - node.height / 2;
    }
    ensureGraphDom();
    applyNodeLayout(node.id);
    if (nodeType !== 'upscale' && getNodeElement(node.id)?.querySelector('[data-output-archive], [data-output-telegram]')) {
      syncOutputControlsToNodes(DesktopState.state.output, { save: false });
    }
    if (nodeType === 'image') triggerImageNodePopIn(node.id, 0);
    updateLinkPath();
    DesktopState.saveSettings();
    return node.id;
  }

  function normalizeNodeMenuType(type) {
    return ['input', 'file_output', 'layout', 'text', 'image', 'pose', 'upscale'].includes(type) ? type : 'input';
  }

  function addNodeFromMenu(type, worldPoint) {
    const nodeType = normalizeNodeMenuType(type);
    const id = addNode(nodeType, worldPoint || getViewportCenterWorldPoint());
    selectNode(id);
    return id;
  }

  function removeNode(nodeId, options = {}) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node) return;
    const nodeEl = getNodeElement(nodeId);
    if (nodeEl?.contains(document.activeElement)) {
      document.activeElement?.blur?.();
    }
    nodeEl?.remove();
    delete DesktopState.state.canvas.nodes[nodeId];
    delete DesktopState.state.outputs[nodeId];
    const refs = nodeId === 'input' ? DesktopState.state.referenceImages : (getNodeReferenceStore()[nodeId] || []);
    refs.forEach(revokeReferenceUrl);
    if (nodeId === 'input') DesktopState.state.referenceImages = [];
    delete getNodeReferenceStore()[nodeId];
    normalizeNodeGroups();
    setSelectedNodes(options.clearSelection ? [] : getSelectedNodeIds().filter(id => id !== nodeId), false);
    const affectedLayoutIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .map(edge => edge.to)
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'layout');
    const affectedPoseIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .map(edge => edge.to)
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'pose');
    const affectedUpscaleIds = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === nodeId || edge.to === nodeId)
      .flatMap(edge => [edge.from, edge.to])
      .filter(id => DesktopState.state.canvas.nodes[id]?.type === 'upscale');
    DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || []).filter(edge => edge.from !== nodeId && edge.to !== nodeId);
    window.dispatchEvent(new CustomEvent('desktop:canvas-node-removed', { detail: { nodeId } }));
    if (node.type === 'text') notifyTextNodeListChange(nodeId);
    affectedLayoutIds.forEach(updateLayoutInputCount);
    affectedPoseIds.forEach(refreshPoseNode);
    affectedUpscaleIds.forEach(updateUpscaleInputCount);
    updateLinkPath();
    DesktopState.saveSettings();
    if (options.focusCanvas) focusCanvasViewport();
  }

  function connectNodes(fromNodeId, toNodeId, options = {}) {
    const from = DesktopState.state.canvas.nodes[fromNodeId];
    const to = DesktopState.state.canvas.nodes[toNodeId];
    const modelToResult = from?.type === 'input' && (to?.type === 'output' || to?.type === 'file_output');
    const modelToImage = from?.type === 'input' && to?.type === 'image';
    const modelToUpscale = from?.type === 'input' && to?.type === 'upscale';
    const imageToInput = from?.type === 'image' && to?.type === 'input';
    const imageToLayout = from?.type === 'image' && to?.type === 'layout';
    const imageToPoseReference = from?.type === 'image' && to?.type === 'pose';
    const imageToUpscale = from?.type === 'image' && to?.type === 'upscale';
    const layoutToInput = from?.type === 'layout' && to?.type === 'input';
    const layoutToUpscale = from?.type === 'layout' && to?.type === 'upscale';
    const poseToInput = from?.type === 'pose' && to?.type === 'input';
    const poseToUpscale = from?.type === 'pose' && to?.type === 'upscale';
    const textToInput = from?.type === 'text' && to?.type === 'input';
    const outputToImage = from?.type === 'output' && to?.type === 'image';
    const upscaleToImage = from?.type === 'upscale' && to?.type === 'image';
    if (!from || !to || (!modelToResult && !modelToImage && !modelToUpscale && !imageToInput && !imageToLayout && !imageToPoseReference && !imageToUpscale && !layoutToInput && !layoutToUpscale && !poseToInput && !poseToUpscale && !textToInput && !outputToImage && !upscaleToImage)) {
      if (!options.quiet) DesktopResults.showTransientMessage('当前支持：模型到图片/文件结果/高清放大，图片到模型/排版/姿态参考/高清放大，排版/姿态参考/文本到模型，高清放大到图片。');
      return '';
    }
    DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || []).filter(edge => {
      if (modelToResult) return edge.to !== toNodeId;
      if (modelToImage) return edge.to !== toNodeId;
      if (outputToImage) return edge.to !== toNodeId;
      if (upscaleToImage) return edge.to !== toNodeId;
      return !(edge.from === fromNodeId && edge.to === toNodeId);
    });
    const edgeId = `${fromNodeId}_${toNodeId}_${Date.now()}`;
    DesktopState.state.canvas.edges.push({
      id: edgeId,
      from: fromNodeId,
      to: toNodeId,
      outputSlot: Number.isFinite(Number(options.outputSlot)) ? Number(options.outputSlot) : undefined
    });
    document.querySelectorAll('.desk-port.is-connecting').forEach(item => item.classList.remove('is-connecting'));
    updateLinkPath();
    if (imageToLayout) {
      updateLayoutInputCount(toNodeId);
      DesktopLayoutEditor?.syncConnectedImages?.(toNodeId)
        ?.then(imported => {
          DesktopResults.showTransientMessage(imported ? '图片已填入排版模板。' : '图片已接入排版节点，打开排版会自动导入。');
        })
        .catch(() => {
          DesktopResults.showTransientMessage('图片已接入排版节点，打开排版会自动导入。');
        });
    } else if (imageToPoseReference) {
      refreshPoseNode(toNodeId);
      DesktopResults.showTransientMessage('图片已接入姿态参考节点，可作为背景参考。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (imageToUpscale || layoutToUpscale || poseToUpscale) {
      updateUpscaleInputCount(toNodeId);
      DesktopResults.showTransientMessage('图片已接入高清放大节点。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (poseToInput) {
      DesktopResults.showTransientMessage('姿态参考节点已接入模型，导出后会作为参考图。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (textToInput) {
      if (!options.quiet) DesktopResults.showTransientMessage('文本节点已接入模型提示词。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (modelToImage) {
      assignImageOutputSlots(fromNodeId);
      if (!options.quiet) DesktopResults.showTransientMessage('图片节点已接入模型输出。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (modelToUpscale) {
      updateUpscaleInputCount(toNodeId);
      if (!options.quiet) DesktopResults.showTransientMessage('高清放大已接入模型输出，模型完成后会自动放大。');
      DesktopState.saveSettings();
      return edgeId;
    } else if (outputToImage) {
      const output = DesktopState.state.outputs?.[fromNodeId];
      if (output?.imagePaths?.length) {
        setImageNodeFromResult(toNodeId, fromNodeId, output, options.outputSlot || 0).catch(error => DesktopResults.showError(error));
        DesktopResults.showTransientMessage('结果图已回填到图片节点。');
      } else {
        DesktopResults.showTransientMessage('已连接；结果节点生成完成后会自动填入图片节点。');
      }
      DesktopState.saveSettings();
      return edgeId;
    } else if (upscaleToImage) {
      refreshUpscaleNodeMode(fromNodeId);
      const output = DesktopState.state.outputs?.[fromNodeId];
      if (output?.imagePaths?.length) {
        setImageNodeFromResult(toNodeId, fromNodeId, output, options.outputSlot || 0).catch(error => DesktopResults.showError(error));
        DesktopResults.showTransientMessage('高清结果已回填到图片节点。');
      } else {
        DesktopResults.showTransientMessage('已连接；高清放大完成后会自动填入图片节点。');
      }
      DesktopState.saveSettings();
      return edgeId;
    } else {
      DesktopState.saveSettings();
      return edgeId;
    }
    DesktopState.saveSettings();
    return edgeId;
  }

  function handleRemovedEdges(removedEdges = []) {
    const layoutIds = new Set();
    const poseIds = new Set();
    const upscaleIds = new Set();
    const modelOutputIds = new Set();
    removedEdges.forEach(edge => {
      const from = DesktopState.state.canvas.nodes[edge.from];
      const to = DesktopState.state.canvas.nodes[edge.to];
      if (to?.type === 'layout') layoutIds.add(edge.to);
      if (to?.type === 'pose') poseIds.add(edge.to);
      if (to?.type === 'upscale') upscaleIds.add(edge.to);
      if (from?.type === 'upscale') upscaleIds.add(edge.from);
      if (from?.type === 'input' && to?.type === 'image') modelOutputIds.add(edge.from);
    });
    modelOutputIds.forEach(assignImageOutputSlots);
    layoutIds.forEach(updateLayoutInputCount);
    poseIds.forEach(refreshPoseNode);
    upscaleIds.forEach(updateUpscaleInputCount);
  }

  function removeEdgesById(edgeIds = [], options = {}) {
    const ids = new Set(edgeIds.filter(Boolean));
    if (!ids.size) return [];
    const removed = [];
    DesktopState.state.canvas.edges = (DesktopState.state.canvas.edges || []).filter(edge => {
      if (!ids.has(edge.id)) return true;
      removed.push(edge);
      return false;
    });
    if (!removed.length) return [];
    handleRemovedEdges(removed);
    updateLinkPath();
    if (!options.quiet) DesktopResults.showTransientMessage('连接已解除。');
    DesktopState.saveSettings();
    return removed;
  }

  function getDetachableIncomingEdge(toNodeId) {
    return [...(DesktopState.state.canvas.edges || [])]
      .reverse()
      .find(edge => edge.to === toNodeId && DesktopState.state.canvas.nodes[edge.from] && DesktopState.state.canvas.nodes[edge.to]);
  }

  function startConnectionDrag(event, button) {
    if (event.button !== 0) return;
    const nodeId = button.dataset.nodeId;
    const port = button.dataset.port;
    if (port !== 'out') return;
    event.preventDefault();
    event.stopPropagation();
    document.querySelectorAll('.desk-port.is-connecting').forEach(item => item.classList.remove('is-connecting'));
    button.classList.add('is-connecting');
    activeInteraction = {
      type: 'connect',
      fromNodeId: nodeId,
      pointer: screenToWorld(event.clientX, event.clientY)
    };
    renderConnectionPreview(nodeId, activeInteraction.pointer);
    const nodeType = DesktopState.state.canvas.nodes[nodeId]?.type;
    DesktopResults.showTransientMessage(nodeType === 'image'
      ? '拖到模型、排版或姿态参考节点左侧圆点后松开。'
      : (nodeType === 'output'
        ? '拖到图片节点上后松开。'
        : (nodeType === 'layout' || nodeType === 'text' || nodeType === 'pose' ? '拖到模型节点左侧圆点后松开。' : '拖到图片节点左侧圆点，或空白处创建输出图片。')));
  }

  function startConnectionDetachDrag(event, button) {
    if (event.button !== 0) return;
    const nodeId = button.dataset.nodeId;
    const port = button.dataset.port;
    if (port !== 'in') return;
    const edge = getDetachableIncomingEdge(nodeId);
    if (!edge) return;
    event.preventDefault();
    event.stopPropagation();
    removeEdgesById([edge.id], { quiet: true });
    document.querySelectorAll('.desk-port.is-connecting').forEach(item => item.classList.remove('is-connecting'));
    button.classList.add('is-connecting');
    activeInteraction = {
      type: 'connect',
      fromNodeId: edge.from,
      detachedEdge: edge,
      reconnecting: true,
      pointer: screenToWorld(event.clientX, event.clientY)
    };
    renderConnectionPreview(edge.from, activeInteraction.pointer);
    DesktopResults.showTransientMessage('连接已拉开，拖到其它输入端点可重连，松开空白处则解除。');
  }

  function outputImageReference(output, index, sourceNodeId) {
    const imageUrl = output?.imagePaths?.[index] || output?.primaryImagePath || '';
    if (!imageUrl) return null;
    const file = output?.files?.[index] || output?.primaryFile || imageUrl.split('/').pop() || '';
    return {
      id: `model-output:${output?.taskId || imageUrl}:${index}`,
      sourceNodeId,
      name: file || `生成结果 ${index + 1}.png`,
      title: file || `生成结果 ${index + 1}`,
      type: 'image/png',
      url: imageUrl,
      base64: '',
      imageData: '',
      imageUrl,
      taskId: output?.taskId || '',
      prompt: output?.prompt || '',
      file,
      source: 'model-output'
    };
  }

  let upscaleComponentInstallPromise = null;

  async function ensureUpscaleComponent(modelName) {
    const catalog = await DesktopApi.getUpscaleModels();
    const model = (catalog.models || []).find(item => item.id === modelName);
    if (model?.available) return catalog;
    if (upscaleComponentInstallPromise) return upscaleComponentInstallPromise;

    const component = catalog.component || {};
    if (!component.configured) {
      throw new Error('高清放大组件下载源尚未配置。');
    }

    upscaleComponentInstallPromise = (async () => {
      DesktopResults.showTransientMessage('首次使用，正在下载高清放大组件...', 'busy');
      await DesktopApi.installUpscaleComponent();
      const deadline = Date.now() + 45 * 60 * 1000;
      let lastProgressBucket = -1;
      while (Date.now() < deadline) {
        const status = await DesktopApi.getUpscaleComponentStatus();
        if (status.status === 'failed') throw new Error(status.error || '高清放大组件安装失败');
        if (status.installed && status.status === 'ready') {
          const refreshed = await DesktopApi.getUpscaleModels();
          const readyModel = (refreshed.models || []).find(item => item.id === modelName);
          if (!readyModel?.available) throw new Error(`高清放大模型不可用：${modelName}`);
          DesktopResults.showTransientMessage('高清放大组件安装完成。', 'success');
          return refreshed;
        }
        const progressBucket = Math.floor(Number(status.progress || 0) * 10);
        if (progressBucket !== lastProgressBucket && progressBucket > 0) {
          lastProgressBucket = progressBucket;
          DesktopResults.showTransientMessage(`高清放大组件下载中 ${Math.min(100, progressBucket * 10)}%`, 'busy');
        }
        await new Promise(resolve => window.setTimeout(resolve, 1000));
      }
      throw new Error('高清放大组件下载超时，请稍后重试。');
    })().finally(() => {
      upscaleComponentInstallPromise = null;
    });
    return upscaleComponentInstallPromise;
  }

  async function submitUpscaleReference(upscaleNodeId, reference, options = {}) {
    const config = readUpscaleNodeConfigForReference(upscaleNodeId, reference, {
      prompt: options.prompt || `高清放大：${reference?.title || reference?.name || '生成结果'}`,
      telegramEnabled: false
    });
    await ensureUpscaleComponent(config.params?.model || '4x-UltraSharp');
    return DesktopResults.submitConfigToResult(config, upscaleNodeId);
  }

  async function runUpscaleChainsForOutput(resultNodeId, output) {
    if (!resultNodeId || !output?.imagePaths?.length) return 0;
    const resultNode = DesktopState.state.canvas.nodes[resultNodeId];
    if (resultNode?.type === 'upscale') return 0;
    if (String(output?.type || '').toLowerCase() === 'upscale') return 0;
    const modelNodeId = resultNode?.type === 'input'
      ? resultNodeId
      : findInputForResult(resultNodeId);
    if (!modelNodeId || DesktopState.state.canvas.nodes[modelNodeId]?.type !== 'input') return 0;
    const upscaleNodeIds = getRunnableUpscaleNodeIds(modelNodeId);
    if (!upscaleNodeIds.length) return 0;

    let submitted = 0;
    for (const upscaleNodeId of upscaleNodeIds) {
      const node = DesktopState.state.canvas.nodes[upscaleNodeId];
      const reference = outputImageReference(output, 0, modelNodeId);
      const sourceKey = `${output?.taskId || output?.primaryImagePath || reference?.imageUrl || ''}:${upscaleNodeId}`;
      if (!node || node.type !== 'upscale' || !reference || !sourceKey || node.autoUpscaleSourceKey === sourceKey) continue;
      node.autoUpscaleSourceKey = sourceKey;
      refreshUpscaleNodeMode(upscaleNodeId);
      submitted += 1;
      submitUpscaleReference(upscaleNodeId, reference, {
        prompt: `高清放大：${reference.title || '生成结果'}`
      }).catch(error => {
        node.autoUpscaleSourceKey = '';
        DesktopResults.showError(error, upscaleNodeId);
      });
    }
    if (submitted) DesktopState.saveSettings();
    return submitted;
  }

  async function populateResultImageNodes(resultNodeId, output) {
    if (!resultNodeId || !output?.imagePaths?.length) return 0;
    const targets = (DesktopState.state.canvas.edges || [])
      .filter(edge => edge.from === resultNodeId && DesktopState.state.canvas.nodes[edge.to]?.type === 'image')
      .sort((a, b) => {
        const aSlot = Number.isFinite(Number(a.outputSlot)) ? Number(a.outputSlot) : Number.MAX_SAFE_INTEGER;
        const bSlot = Number.isFinite(Number(b.outputSlot)) ? Number(b.outputSlot) : Number.MAX_SAFE_INTEGER;
        if (aSlot !== bSlot) return aSlot - bSlot;
        return String(a.id || '').localeCompare(String(b.id || ''));
      })
      .map(edge => edge.to);
    let count = 0;
    const limit = Math.min(targets.length, output.imagePaths.length);
    for (let index = 0; index < limit; index += 1) {
      if (await setImageNodeFromResult(targets[index], resultNodeId, output, index)) count += 1;
    }
    return count;
  }

  function refreshLayoutNode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || !el) return;
    const preview = el.querySelector('[data-layout-preview]');
    if (!preview) return;
    const src = node.layoutPreview || node.layoutExport || '';
    preview.innerHTML = src ? `<img src="${escapeHtml(src)}" alt="排版预览">` : '<span>尚未排版</span>';
    updateLayoutInputCount(nodeId);
    renderMiniMap();
  }

  function refreshPoseNode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'pose' || !el) return;
    const preview = el.querySelector('[data-pose-preview]');
    const inputCountTarget = el.querySelector('[data-pose-input-count]');
    const statusTarget = el.querySelector('[data-pose-status]');
    const src = node.previewImage || node.exportImage || '';
    const inputCount = getPoseInputImages(nodeId).length;
    const backgroundCount = inputCount + (node.backgroundImage ? 1 : 0);
    if (preview) {
      preview.innerHTML = src
        ? `<img src="${escapeHtml(src)}" alt="姿态预览">`
        : '<span><strong>姿态参考</strong><em>打开编辑器调整姿态</em></span>';
    }
    if (inputCountTarget) inputCountTarget.textContent = backgroundCount ? `背景 ${backgroundCount}` : '可接入背景';
    if (statusTarget) {
      statusTarget.textContent = poseStatusText(node, src, backgroundCount);
    }
    renderMiniMap();
  }

  function connectPoseToDefaultInput(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'pose') return;
    const targetInputId = findDefaultInputNodeId();
    if (!targetInputId) {
      DesktopResults.showTransientMessage('没有可接入的模型节点。');
      return;
    }
    connectNodes(nodeId, targetInputId);
    selectNode(nodeId);
    updateLinkPath();
  }

  function finishConnectionDrag(event) {
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const port = target?.closest?.('.desk-port[data-port="in"]');
    if (port) {
      connectNodes(activeInteraction.fromNodeId, port.dataset.nodeId);
      return;
    }
    const sourceNode = DesktopState.state.canvas.nodes[activeInteraction.fromNodeId];
    if (sourceNode?.type === 'output' || sourceNode?.type === 'input' || sourceNode?.type === 'upscale') {
      const imageNode = target?.closest?.('.desk-node--image[data-node-id]');
      if (imageNode) {
        connectNodes(activeInteraction.fromNodeId, imageNode.dataset.nodeId);
        return;
      }
    }
    document.querySelectorAll('.desk-port.is-connecting').forEach(item => item.classList.remove('is-connecting'));
    updateLinkPath();
    if (activeInteraction.reconnecting) {
      DesktopResults.showTransientMessage('连接已解除。');
      return;
    }
    const items = getConnectableNodeMenuItems(activeInteraction.fromNodeId);
    const viewportRect = els.deskCanvasViewport?.getBoundingClientRect();
    const isInsideViewport = !!viewportRect
      && event.clientX >= viewportRect.left
      && event.clientX <= viewportRect.right
      && event.clientY >= viewportRect.top
      && event.clientY <= viewportRect.bottom;
    const isBlankCanvas = !target?.closest?.('.desk-node, .desk-node-palette, .desk-gallery-panel, .desk-settings, .desk-selection-toolbar, .desk-zoom-controls, .desk-workflow-dock-toggle, .desk-workflow-dock-panel');
    if (items.length && isInsideViewport && isBlankCanvas) {
      openContextMenu(event, {
        connectionSourceId: activeInteraction.fromNodeId,
        title: '可接入节点'
      });
      DesktopResults.showTransientMessage('选择一个节点继续连接。');
      return;
    }
    DesktopResults.showTransientMessage('连接已取消。');
  }

  function toggleNodeDrawer(node) {
    const drawer = node.querySelector('.desk-node__drawer');
    const button = node.querySelector('[data-toggle-node], #deskToggleInputBtn');
    if (!drawer) return;
    if (node.classList.contains('desk-node--input')) {
      drawer.style.display = 'grid';
      node.classList.remove('is-expanded');
      return;
    }
    const expanded = drawer.style.display === 'none';
    drawer.style.display = expanded ? 'grid' : 'none';
    node.classList.toggle('is-expanded', expanded);
    if (button) button.textContent = expanded ? '收起' : '展开';
  }

  function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('图片读取失败'));
      reader.readAsDataURL(file);
    });
  }

  function readImageMeta(dataUrl) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => resolve({
        width: img.naturalWidth || 1,
        height: img.naturalHeight || 1
      });
      img.onerror = () => resolve({ width: 1, height: 1 });
      img.src = dataUrl;
    });
  }

  async function imageUrlToDataUrl(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) throw new Error('历史图片读取失败');
    const blob = await response.blob();
    return fileToDataUrl(blob);
  }

  function refreshImageNode(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'image' || !el) return;
    const src = imageNodeSource(node);
    el.classList.toggle('has-image', !!src);
    el.classList.toggle('is-empty', !src);
    const tools = el.querySelector('.desk-image-node__tools');
    const nextToolsHtml = imageNodeToolsHtml(node);
    if (!src) {
      if (tools) tools.remove();
      return;
    }
    if (tools) {
      tools.outerHTML = nextToolsHtml;
    } else {
      const firstPort = el.querySelector('.desk-port');
      if (firstPort) {
        firstPort.insertAdjacentHTML('beforebegin', nextToolsHtml);
      } else {
        el.insertAdjacentHTML('beforeend', nextToolsHtml);
      }
    }
  }

  function refreshImageNodeContent(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const el = getNodeElement(nodeId);
    if (!node || node.type !== 'image' || !el) return;
    const src = node.imageData || node.imageUrl || '';
    const existingImage = el.querySelector('img');
    const existingPlaceholder = el.querySelector('.desk-image-node__placeholder');
    if (src) {
      if (existingImage) {
        existingImage.src = src;
        existingImage.alt = node.imageName || '图片节点';
      } else {
        existingPlaceholder?.insertAdjacentHTML('beforebegin', `<img src="${escapeHtml(src)}" alt="${escapeHtml(node.imageName || '图片节点')}" draggable="false">`);
        existingPlaceholder?.remove();
      }
    } else if (existingPlaceholder) {
      existingPlaceholder.outerHTML = imageNodePlaceholderHtml();
    } else {
      existingImage?.insertAdjacentHTML('afterend', imageNodePlaceholderHtml());
      existingImage?.remove();
    }
    refreshImageNode(nodeId);
    applyNodeLayout(nodeId);
  }

  function ensureImageEditor() {
    if (imageEditorEl) return imageEditorEl;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="desk-image-editor" id="deskImageEditor" aria-hidden="true">
        <div class="desk-image-editor__panel" role="dialog" aria-modal="true" aria-label="图片编辑">
          <header class="desk-image-editor__bar">
            <div class="desk-image-editor__bar-copy">
              <h2 data-image-edit-title>图片编辑</h2>
              <div class="desk-image-editor__status" data-image-edit-status>就绪</div>
            </div>
            <div class="desk-image-editor__bar-actions">
              <button type="button" class="desk-image-editor__icon-btn" data-image-edit-undo title="撤销" aria-label="撤销">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14 4 9l5-5"></path><path d="M5 9h8a6 6 0 1 1 0 12H8"></path></svg>
              </button>
              <button type="button" class="desk-image-editor__icon-btn" data-image-edit-redo title="重做" aria-label="重做">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 14 20 9l-5-5"></path><path d="M19 9h-8a6 6 0 1 0 0 12h5"></path></svg>
              </button>
              <button type="button" class="desk-image-editor__close" data-image-edit-close title="关闭" aria-label="关闭">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>
              </button>
            </div>
          </header>
          <div class="desk-image-editor__body">
            <section class="desk-image-editor__stage">
              <aside class="desk-image-editor__rail desk-image-editor__rail--top" aria-label="编辑工具">
                <div class="desk-image-editor__tool-grid">
                  ${[
                    ['select', '选择'],
                    ['brush', '画笔'],
                    ['maskBrush', '蒙版'],
                    ['shape', '形状'],
                    ['arrow', '箭头'],
                    ['text', '文字'],
                    ['pin', 'Pin'],
                    ['eraser', '橡皮']
                  ].map(([tool, label]) => `
                    <button type="button" class="desk-image-editor__tool" data-image-edit-tool="${tool}" title="${label}" aria-label="${label}">
                      <img class="desk-image-editor__tool-icon" src="${getImageEditToolIcon(tool)}" alt="" aria-hidden="true" draggable="false">
                      <span>${label}</span>
                    </button>
                  `).join('')}
                </div>
                <div class="desk-image-editor__swatch-group">
                  <div class="desk-image-editor__label">颜色</div>
                  <div class="desk-image-editor__swatches" data-image-edit-swatches>
                    ${['#0b57d0', '#ff6a22', '#11a36c', '#8b5cf6', '#111827', '#ffffff'].map((color, index) => `
                      <button type="button" class="desk-image-editor__swatch${index === 0 ? ' is-active' : ''}" data-image-edit-color="${color}" title="${color}" aria-label="${color}" style="--desk-swatch:${color}"></button>
                    `).join('')}
                  </div>
                </div>
                <div class="desk-image-editor__shape-options">
                  <div class="desk-image-editor__label">形状</div>
                  <div class="desk-image-editor__shape-grid">
                  ${[
                      ['rectOutline', '空心矩形'],
                      ['rectFilled', '实心矩形'],
                      ['ellipseOutline', '空心圆形'],
                      ['ellipseFilled', '实心圆形']
                    ].map(([shape, label], index) => `
                      <button type="button" class="desk-image-editor__shape${index === 0 ? ' is-active' : ''}" data-image-edit-shape="${shape}" title="${label}" aria-label="${label}" aria-pressed="${index === 0 ? 'true' : 'false'}">
                        <svg viewBox="0 0 24 24" aria-hidden="true">${getImageEditShapeIcon(shape)}</svg>
                      </button>
                    `).join('')}
                  </div>
                </div>
                <label class="desk-image-editor__range">
                  <span>笔触</span>
                  <input type="range" min="2" max="120" value="22" data-image-edit-size>
                </label>
                <div class="desk-image-editor__zoom" aria-label="图片缩放">
                  <button type="button" class="desk-image-editor__zoom-btn" data-image-edit-zoom-out title="缩小" aria-label="缩小">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"></path></svg>
                  </button>
                  <output class="desk-image-editor__zoom-label" data-image-edit-zoom-label>适配</output>
                  <button type="button" class="desk-image-editor__zoom-btn" data-image-edit-zoom-in title="放大" aria-label="放大">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
                  </button>
                  <button type="button" class="desk-image-editor__button desk-image-editor__button--compact" data-image-edit-zoom-fit title="适配图片">适配</button>
                </div>
                <div class="desk-image-editor__stack desk-image-editor__stack--utility">
                  <button type="button" class="desk-image-editor__button" data-image-edit-clear-annotations>清空标注</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-clear-mask>清空蒙版</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-import>导入图片</button>
                </div>
              </aside>
              <div class="desk-image-editor__canvas-shell">
                <div class="desk-image-editor__canvas-wrap">
                  <canvas data-image-edit-fabric></canvas>
                </div>
              </div>
              <aside class="desk-image-editor__rail desk-image-editor__rail--bottom" aria-label="导出">
                <div class="desk-image-editor__stack desk-image-editor__stack--bundle">
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-annotated>导出合成图</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-node>导出到桌面节点</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-mask>导出 mask</button>
                  <button type="button" class="desk-image-editor__button" data-image-edit-export-json>导出 JSON</button>
                </div>
                <p class="desk-image-editor__source" data-image-edit-source hidden>未载入图片</p>
                <input type="file" accept="image/*" data-image-edit-import-input hidden>
              </aside>
            </section>
          </div>
        </div>
      </div>
    `);
    imageEditorEl = document.getElementById('deskImageEditor');
    imageEditorEl?.style.setProperty('--desk-image-editor-ui-scale', String(IMAGE_EDIT_UI_SCALE));
    bindImageEditorEvents(imageEditorEl);
    return imageEditorEl;
  }

  function getImageEditorCanvasElement() {
    return imageEditorEl?.querySelector('[data-image-edit-fabric]');
  }

  function getImageEditorCanvas() {
    return imageEditorCanvas;
  }

  function getImageEditorCanvasShell() {
    return imageEditorEl?.querySelector('.desk-image-editor__canvas-shell');
  }

  function getImageEditorCanvasWrap() {
    return imageEditorEl?.querySelector('.desk-image-editor__canvas-wrap');
  }

  function applyImageEditCanvasPanOffset(x = 0, y = 0) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    const wrap = getImageEditorCanvasWrap();
    const nextX = Number.isFinite(Number(x)) ? Number(x) : 0;
    const nextY = Number.isFinite(Number(y)) ? Number(y) : 0;
    if (wrap) wrap.style.transform = '';
    if (canvas?.viewportTransform) {
      const cssScale = getImageEditCanvasCssScale(canvas);
      const viewport = canvas.viewportTransform.slice();
      viewport[4] = nextX / cssScale;
      viewport[5] = nextY / cssScale;
      const clamped = clampImageEditViewportTransform(canvas, viewport);
      canvas.setViewportTransform(clamped);
      if (state) {
        state.canvasPanX = clamped[4] * cssScale;
        state.canvasPanY = clamped[5] * cssScale;
      }
      canvas.requestRenderAll?.();
      return;
    }
    if (state) {
      state.canvasPanX = nextX;
      state.canvasPanY = nextY;
    }
  }

  function clampImageEditZoom(value, fallback = 1) {
    const numeric = Number(value);
    const next = Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
    return Math.max(IMAGE_EDIT_MIN_ZOOM, Math.min(IMAGE_EDIT_MAX_ZOOM, next));
  }

  function getImageEditDisplaySize(width, height) {
    const sourceWidth = Math.max(1, Number(width) || 1);
    const sourceHeight = Math.max(1, Number(height) || 1);
    const shell = getImageEditorCanvasShell();
    const availableWidth = Math.max(240, (shell?.clientWidth || (window.innerWidth - 220)) - 32);
    const availableHeight = Math.max(220, (shell?.clientHeight || (window.innerHeight - 190)) - 32);
    const fitScale = Math.min(1, availableWidth / sourceWidth, availableHeight / sourceHeight);
    const state = getImageEditState();
    let imageScale = fitScale;
    if (state) {
      state.fitScale = fitScale;
      if (state.zoomMode === 'manual') {
        imageScale = clampImageEditZoom(state.displayZoom, fitScale);
        state.displayZoom = imageScale;
      } else {
        state.zoomMode = 'fit';
        state.displayZoom = fitScale;
      }
    }
    return {
      width: Math.max(1, Math.round(sourceWidth * fitScale)),
      height: Math.max(1, Math.round(sourceHeight * fitScale)),
      scale: imageScale,
      fitScale
    };
  }

  function getImageEditCanvasCssScale(canvas = getImageEditorCanvas()) {
    if (!canvas?.lowerCanvasEl) return 1;
    const rect = canvas.lowerCanvasEl.getBoundingClientRect?.();
    const sourceWidth = Math.max(1, Number(canvas.getWidth?.() || canvas.lowerCanvasEl.width || 1));
    const cssWidth = Math.max(1, Number(rect?.width || sourceWidth));
    return Math.max(0.01, cssWidth / sourceWidth);
  }

  function getImageEditViewportCenter(canvas = getImageEditorCanvas()) {
    if (!canvas) return null;
    const viewport = canvas.viewportTransform || [1, 0, 0, 1, 0, 0];
    const zoom = Math.max(0.01, Number(viewport[0] || canvas.getZoom?.() || 1));
    return {
      x: ((canvas.getWidth?.() || 1) / 2 - Number(viewport[4] || 0)) / zoom,
      y: ((canvas.getHeight?.() || 1) / 2 - Number(viewport[5] || 0)) / zoom
    };
  }

  function clampImageEditViewportTransform(canvas, transform) {
    if (!canvas) return transform || [1, 0, 0, 1, 0, 0];
    const viewport = (transform || canvas.viewportTransform || [1, 0, 0, 1, 0, 0]).slice();
    const zoom = Math.max(0.01, Number(viewport[0] || 1));
    const width = Math.max(1, Number(canvas.getWidth?.() || 1));
    const height = Math.max(1, Number(canvas.getHeight?.() || 1));
    if (zoom <= 1) {
      viewport[4] = (width - width * zoom) / 2;
      viewport[5] = (height - height * zoom) / 2;
    } else {
      viewport[4] = Math.min(0, Math.max(width - width * zoom, Number(viewport[4] || 0)));
      viewport[5] = Math.min(0, Math.max(height - height * zoom, Number(viewport[5] || 0)));
    }
    return viewport;
  }

  function applyImageEditViewportZoom(canvas, viewportZoom, center = null) {
    if (!canvas) return;
    const zoom = Math.max(0.01, Number(viewportZoom) || 1);
    const width = Math.max(1, Number(canvas.getWidth?.() || 1));
    const height = Math.max(1, Number(canvas.getHeight?.() || 1));
    const focus = center || { x: width / 2, y: height / 2 };
    let viewport = [zoom, 0, 0, zoom, width / 2 - focus.x * zoom, height / 2 - focus.y * zoom];
    viewport = clampImageEditViewportTransform(canvas, viewport);
    canvas.setViewportTransform(viewport);
    const state = getImageEditState();
    if (state) {
      const cssScale = getImageEditCanvasCssScale(canvas);
      state.canvasPanX = viewport[4] * cssScale;
      state.canvasPanY = viewport[5] * cssScale;
    }
  }

  function refreshImageEditObjectControls() {
    const canvas = getImageEditorCanvas();
    if (!canvas) return;
    canvas.getObjects()
      .filter(object => object?.editRole && object.editRole !== 'baseImage')
      .forEach(object => applyImageEditObjectControls(object, object.stroke || object.fill || object.annotationColor || object.maskColor || '#0b57d0'));
  }

  function updateImageEditZoomUi() {
    const state = getImageEditState();
    const zoomLabel = imageEditorEl?.querySelector('[data-image-edit-zoom-label]');
    const zoomOut = imageEditorEl?.querySelector('[data-image-edit-zoom-out]');
    const zoomIn = imageEditorEl?.querySelector('[data-image-edit-zoom-in]');
    const zoomFit = imageEditorEl?.querySelector('[data-image-edit-zoom-fit]');
    if (!state) return;
    const zoom = clampImageEditZoom(state.displayZoom || state.fitScale || 1, state.fitScale || 1);
    if (zoomLabel) zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
    if (zoomOut) zoomOut.disabled = zoom <= IMAGE_EDIT_MIN_ZOOM + 0.001;
    if (zoomIn) zoomIn.disabled = zoom >= IMAGE_EDIT_MAX_ZOOM - 0.001;
    if (zoomFit) zoomFit.disabled = state.zoomMode === 'fit';
  }

  function applyImageEditCanvasDisplaySize(canvas, width, height, options = {}) {
    if (!canvas) return;
    const sourceWidth = Math.max(1, Math.round(Number(width) || canvas.getWidth() || 1));
    const sourceHeight = Math.max(1, Math.round(Number(height) || canvas.getHeight() || 1));
    const center = options.center || (options.preserveViewport === false ? null : getImageEditViewportCenter(canvas));
    const display = getImageEditDisplaySize(sourceWidth, sourceHeight);
    canvas.setDimensions({ width: sourceWidth, height: sourceHeight }, { backstoreOnly: true });
    canvas.setDimensions({ width: display.width, height: display.height }, { cssOnly: true });
    if (canvas.wrapperEl) {
      canvas.wrapperEl.style.setProperty('width', `${display.width}px`, 'important');
      canvas.wrapperEl.style.setProperty('height', `${display.height}px`, 'important');
      canvas.wrapperEl.style.setProperty('max-width', 'none', 'important');
      canvas.wrapperEl.style.setProperty('max-height', 'none', 'important');
    }
    [canvas.lowerCanvasEl, canvas.upperCanvasEl].forEach(canvasEl => {
      if (!canvasEl) return;
      canvasEl.style.setProperty('width', `${display.width}px`, 'important');
      canvasEl.style.setProperty('height', `${display.height}px`, 'important');
      canvasEl.style.setProperty('max-width', 'none', 'important');
      canvasEl.style.setProperty('max-height', 'none', 'important');
    });
    const sourceEl = getImageEditorCanvasElement();
    if (sourceEl) {
      sourceEl.style.setProperty('width', `${display.width}px`, 'important');
      sourceEl.style.setProperty('height', `${display.height}px`, 'important');
    }
    const viewportZoom = display.fitScale > 0 ? display.scale / display.fitScale : 1;
    applyImageEditViewportZoom(canvas, viewportZoom, center);
    canvas.calcOffset?.();
    refreshImageEditObjectControls();
    canvas.requestRenderAll?.();
    updateImageEditZoomUi();
  }

  function setImageEditZoom(value, mode = 'manual') {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    const center = mode === 'fit' ? null : getImageEditViewportCenter(canvas);
    if (mode === 'fit') {
      state.zoomMode = 'fit';
      state.displayZoom = state.fitScale || 1;
    } else {
      state.zoomMode = 'manual';
      state.displayZoom = clampImageEditZoom(value, state.displayZoom || state.fitScale || 1);
    }
    applyImageEditCanvasDisplaySize(canvas, state.sourceWidth, state.sourceHeight, {
      center,
      preserveViewport: mode !== 'fit'
    });
    updateImageEditZoomUi();
  }

  function getImageEditCanvasDisplayScale(canvas = getImageEditorCanvas()) {
    const cssScale = getImageEditCanvasCssScale(canvas);
    const viewportZoom = Math.max(0.01, Number(canvas?.getZoom?.() || 1));
    return Math.max(0.01, cssScale * viewportZoom);
  }

  function imageEditScreenToCanvasSize(value, canvas = getImageEditorCanvas()) {
    const numeric = Math.max(0, Number(value) || 0);
    return numeric / getImageEditCanvasDisplayScale(canvas);
  }

  function applyImageEditObjectControls(object, color = '') {
    if (!object) return object;
    const normalizedColor = normalizeImageEditColor(color || object.stroke || object.fill || '#0b57d0');
    object.set({
      borderColor: normalizedColor,
      cornerColor: '#ffffff',
      cornerStrokeColor: normalizedColor,
      transparentCorners: false,
      cornerSize: imageEditScreenToCanvasSize(8),
      touchCornerSize: imageEditScreenToCanvasSize(26),
      borderScaleFactor: Math.max(1, imageEditScreenToCanvasSize(1))
    });
    return object;
  }

  function getImageEditHexColor(color) {
    const value = String(color || '').trim();
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value) ? value : '';
  }

  function firstImageEditHexColor(...colors) {
    for (const color of colors) {
      const normalizedColor = getImageEditHexColor(color);
      if (normalizedColor) return normalizedColor;
    }
    return '';
  }

  function getImageEditObjectColor(object) {
    if (!object) return '';
    if (object.type === 'activeSelection' && typeof object.getObjects === 'function') {
      const target = object.getObjects().find(item => item?.editRole && item.editRole !== 'baseImage');
      return getImageEditObjectColor(target);
    }
    if (object.editKind === 'pin' && typeof object.getObjects === 'function') {
      const childColors = object.getObjects()
        .flatMap(child => [child?.stroke, child?.fill])
        .filter(Boolean);
      return firstImageEditHexColor(object.annotationColor, ...childColors);
    }
    if (object.editRole === 'mask') {
      return firstImageEditHexColor(object.maskColor, object.stroke, object.fill);
    }
    return firstImageEditHexColor(object.annotationColor, object.stroke, object.fill);
  }

  function getImageEditSelectedObjects(canvas = getImageEditorCanvas()) {
    const activeObject = canvas?.getActiveObject?.();
    if (!activeObject) return [];
    const objects = typeof canvas.getActiveObjects === 'function'
      ? canvas.getActiveObjects()
      : (activeObject.type === 'activeSelection' && typeof activeObject.getObjects === 'function' ? activeObject.getObjects() : [activeObject]);
    const seen = new Set();
    return objects.filter(object => {
      if (!object || object.editRole === 'baseImage' || object.type === 'activeSelection' || seen.has(object)) return false;
      seen.add(object);
      return true;
    });
  }

  function setImageEditPinColor(pin, color) {
    if (!pin || typeof pin.getObjects !== 'function') return;
    pin.getObjects().forEach(child => {
      if (!child) return;
      if (child.type === 'path' || child.path) {
        child.set({ stroke: color, fill: null });
      } else if (child.type === 'text' || typeof child.text === 'string') {
        child.set({ fill: color, stroke: null });
      } else {
        if (child.stroke !== undefined) child.set({ stroke: color });
        if (getImageEditHexColor(child.fill)) child.set({ fill: color });
      }
      child.dirty = true;
    });
    pin.set({ annotationColor: color });
  }

  function imageEditObjectColorSignature(object) {
    return object?.toObject ? JSON.stringify(serializeImageEditObject(object)) : '';
  }

  function setImageEditObjectColor(object, color) {
    if (!object || object.editRole === 'baseImage') return false;
    const normalizedColor = normalizeImageEditColor(color);
    const before = imageEditObjectColorSignature(object);
    if (object.editKind === 'pin') {
      setImageEditPinColor(object, normalizedColor);
    } else if (object.editKind === 'text' || typeof object.text === 'string') {
      object.set({ fill: normalizedColor, annotationColor: normalizedColor });
    } else if (object.editKind === 'rect' || object.editKind === 'ellipse') {
      const nextProps = {
        stroke: normalizedColor,
        annotationColor: normalizedColor
      };
      if (isImageEditShapeFilled(object.shapeMode)) nextProps.fill = normalizedColor;
      object.set(nextProps);
    } else if (object.editRole === 'mask') {
      object.set({
        stroke: normalizedColor,
        fill: object.type === 'path' ? null : normalizedColor,
        maskColor: normalizedColor
      });
    } else {
      const nextProps = { annotationColor: normalizedColor };
      if (object.stroke !== undefined) nextProps.stroke = normalizedColor;
      if (object.editKind !== 'arrow' && object.editKind !== 'brush' && getImageEditHexColor(object.fill)) {
        nextProps.fill = normalizedColor;
      }
      object.set(nextProps);
    }
    applyImageEditObjectControls(object, normalizedColor);
    object.dirty = true;
    object.setCoords?.();
    return before !== imageEditObjectColorSignature(object);
  }

  function setImageEditSelectedObjectsColor(color) {
    const canvas = getImageEditorCanvas();
    const targets = getImageEditSelectedObjects(canvas);
    if (!canvas || !targets.length) return 0;
    const changedCount = targets.reduce((count, object) => (
      setImageEditObjectColor(object, color) ? count + 1 : count
    ), 0);
    if (!changedCount) return 0;
    canvas.requestRenderAll();
    recordImageEditSnapshot('颜色已更新');
    setImageEditStatus(`已更新 ${changedCount} 个对象颜色`, 'info');
    return changedCount;
  }

  function syncImageEditColorFromSelection() {
    const state = getImageEditState();
    const selectedColor = getImageEditSelectedObjects()
      .map(object => getImageEditObjectColor(object))
      .find(Boolean);
    if (!state || !selectedColor) return;
    state.color = normalizeImageEditColor(selectedColor);
    updateImageEditToolUi();
  }

  function handleImageEditSelectionChange() {
    syncImageEditColorFromSelection();
    updateImageEditUndoRedoButtons();
  }

  function getImageEditorPromptInput() {
    return null;
  }

  function getImageEditorStatusEl() {
    return imageEditorEl?.querySelector('[data-image-edit-status]');
  }

  function getImageEditorSourceEl() {
    return imageEditorEl?.querySelector('[data-image-edit-source]');
  }

  function getImageEditCustomProps() {
    return ['id', 'editRole', 'editKind', 'shapeMode', 'maskRole', 'label', 'pinNumber', 'sourceTool', 'strokeKind', 'annotationColor', 'maskColor', 'sourceNodeId', 'erasable'];
  }

  function cloneImageEditValue(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }

  function createImageEditId(prefix = 'image-edit') {
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function sanitizeImageEditFilename(name, fallback = 'image-edit') {
    return String(name || fallback)
      .trim()
      .replace(/[\\/:*?"<>|]+/g, '-')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '') || fallback;
  }

  function downloadDataUrl(dataUrl, filename) {
    if (!dataUrl) throw new Error('没有可下载的内容');
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = filename;
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    try {
      downloadDataUrl(url, filename);
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 500);
    }
  }

  function downloadJsonObject(payload, filename) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    downloadBlob(blob, filename);
  }

  function jsonClone(value, fallback = null) {
    try {
      return JSON.parse(JSON.stringify(value ?? fallback));
    } catch (error) {
      return fallback;
    }
  }

  function dataUrlValue(value) {
    const text = String(value || '').trim();
    return text.startsWith('data:') ? text : '';
  }

  function normalizeWorkflowReference(ref) {
    const item = jsonClone(ref, {});
    if (!item || typeof item !== 'object') return null;
    const dataUrl = dataUrlValue(item.base64) || dataUrlValue(item.imageData) || dataUrlValue(item.url) || dataUrlValue(item.imageUrl);
    if (dataUrl) {
      item.base64 = dataUrl;
      item.imageData = dataUrl;
    }
    if (String(item.url || '').startsWith('blob:')) item.url = dataUrl || '';
    if (String(item.imageUrl || '').startsWith('blob:')) item.imageUrl = '';
    if (!item.url && dataUrl) item.url = dataUrl;
    if (!item.imageUrl && !dataUrl && item.url) item.imageUrl = item.url;
    item.id = String(item.id || item.assetId || item.asset_id || item.taskId || item.task_id || item.url || item.imageUrl || `ref-${Date.now()}`);
    item.name = String(item.name || item.title || item.file || '参考图');
    item.title = String(item.title || item.name || '参考图');
    item.type = String(item.type || item.mimeType || 'image/png');
    return item;
  }

  function normalizeWorkflowReferences(refs) {
    return (Array.isArray(refs) ? refs : [])
      .map(normalizeWorkflowReference)
      .filter(Boolean)
      .slice(0, 8);
  }

  function normalizeWorkflowReferenceMap(map) {
    if (!map || typeof map !== 'object') return {};
    return Object.entries(map).reduce((acc, [nodeId, refs]) => {
      const clean = normalizeWorkflowReferences(refs);
      if (clean.length) acc[nodeId] = clean;
      return acc;
    }, {});
  }

  function normalizeWorkflowParams(params = {}, fallback = DesktopState.state.params || {}) {
    const source = params && typeof params === 'object' ? params : {};
    return {
      ...jsonClone(fallback, {}),
      ...jsonClone(source, {}),
      ratio: DesktopState.normalizeRatio(source.ratio ?? fallback.ratio, '9:16'),
      resolution: DesktopState.normalizeResolution(source.resolution ?? fallback.resolution, '2k'),
      quality: DesktopState.normalizeGptQuality(source.quality ?? fallback.quality, 'auto'),
      imageCount: DesktopState.clamp(source.imageCount ?? source.image_count ?? fallback.imageCount, 1, 8, 1),
      moderation: DesktopState.normalizeModeration(source.moderation ?? fallback.moderation, 'auto'),
      gptTaskType: DesktopState.normalizeGptTaskType(source.gptTaskType ?? source.task_type ?? fallback.gptTaskType, 'image'),
      gptProviderRoute: DesktopState.normalizeGptProviderRoute(source.gptProviderRoute ?? source.gpt_provider_route ?? fallback.gptProviderRoute, 'codex'),
      gptMainModel: DesktopState.normalizeGptMainModel(source.gptMainModel ?? source.main_model ?? fallback.gptMainModel, 'gpt-5.5'),
      reasoningEffort: DesktopState.normalizeReasoningEffort(source.reasoningEffort ?? source.reasoning_effort ?? fallback.reasoningEffort, 'medium'),
      promptMode: DesktopState.normalizePromptMode(source.promptMode ?? source.prompt_mode ?? fallback.promptMode, 'smart'),
      batchMode: DesktopState.normalizeBoolean(source.batchMode ?? source.batch_mode ?? fallback.batchMode, false),
      model: typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(source.model ?? fallback.model ?? DEFAULT_GOOGLE_MODEL, DEFAULT_GOOGLE_MODEL)
        : (source.model ?? fallback.model ?? DEFAULT_GOOGLE_MODEL)
    };
  }

  function normalizeWorkflowNode(node, nodeId) {
    const clean = jsonClone(node, {});
    if (!clean || typeof clean !== 'object') return null;
    const id = String(clean.id || nodeId || '').trim();
    if (!id) return null;
    clean.id = id;
    clean.type = normalizeNodeMenuType(clean.type || (id === 'input' ? 'input' : 'image'));
    clean.groupId = normalizeNodeGroupId(clean.groupId);
    if (!clean.groupId) delete clean.groupId;
    clean.x = Number.isFinite(Number(clean.x)) ? Number(clean.x) : 56;
    clean.y = Number.isFinite(Number(clean.y)) ? Number(clean.y) : 72;
    clean.width = Number.isFinite(Number(clean.width)) ? Number(clean.width) : (clean.type === 'input' ? DEFAULT_INPUT_NODE_WIDTH : (clean.type === 'upscale' ? DEFAULT_UPSCALE_NODE_WIDTH : DEFAULT_IMAGE_NODE_WIDTH));
    clean.height = Number.isFinite(Number(clean.height)) ? Number(clean.height) : (clean.type === 'input' ? DEFAULT_INPUT_NODE_HEIGHT : (clean.type === 'upscale' ? DEFAULT_UPSCALE_NODE_HEIGHT : DEFAULT_IMAGE_NODE_HEIGHT));
    if (clean.type === 'input') {
      clean.width = DEFAULT_INPUT_NODE_WIDTH;
      clean.height = DEFAULT_INPUT_NODE_HEIGHT;
      clean.provider = ['gpt', 'google', 'comfy'].includes(clean.provider) ? clean.provider : 'gpt';
      clean.params = normalizeWorkflowParams(clean.params || {}, DesktopState.state.params || {});
      clean.output = {
        archiveEnabled: clean.output?.archiveEnabled !== false,
        telegramEnabled: clean.output?.telegramEnabled !== false
      };
    }
    if (clean.type === 'text') {
      clean.text = String(clean.text || '');
      clean.alias = sanitizeTextNodeAlias(clean.alias) || nextTextNodeAlias(clean.id);
      clean.stylePresetId = String(clean.stylePresetId || '');
    }
    if (clean.type === 'image') {
      const dataUrl = dataUrlValue(clean.imageData) || dataUrlValue(clean.base64) || dataUrlValue(clean.imageUrl);
      if (dataUrl) clean.imageData = dataUrl;
      if (String(clean.imageUrl || '').startsWith('blob:')) clean.imageUrl = '';
      clean.imageName = String(clean.imageName || clean.title || '图片节点');
      clean.mimeType = String(clean.mimeType || (dataUrl ? dataUrl.slice(5, dataUrl.indexOf(';')) : 'image/png') || 'image/png');
      clean.aspectRatio = Number(clean.aspectRatio) > 0 ? Number(clean.aspectRatio) : DEFAULT_IMAGE_NODE_WIDTH / DEFAULT_IMAGE_NODE_HEIGHT;
    }
    if (clean.type === 'layout' && Array.isArray(clean.layoutInputImages)) {
      clean.layoutInputImages = clean.layoutInputImages.map(normalizeWorkflowReference).filter(Boolean);
    }
    if (clean.type === 'upscale') {
      clean.width = Number.isFinite(Number(clean.width)) ? Number(clean.width) : DEFAULT_UPSCALE_NODE_WIDTH;
      clean.height = DEFAULT_UPSCALE_NODE_HEIGHT;
      clean.model = UPSCALE_MODEL_OPTIONS.some(item => item.value === clean.model) ? clean.model : '4x-UltraSharp';
      clean.tileSize = DesktopState.clamp(clean.tileSize, 64, 2048, 256);
      clean.tileOverlap = DesktopState.clamp(clean.tileOverlap, 0, 256, 32);
      clean.device = String(clean.device || 'auto');
      clean.output = {
        archiveEnabled: true,
        telegramEnabled: clean.output?.telegramEnabled === true
      };
    }
    return clean;
  }

  function normalizeWorkflowCanvas(canvas = {}) {
    const source = canvas && typeof canvas === 'object' ? canvas : {};
    const sourceNodes = source.nodes && typeof source.nodes === 'object' ? source.nodes : {};
    const nodes = Object.entries(sourceNodes).reduce((acc, [nodeId, node]) => {
      const clean = normalizeWorkflowNode(node, nodeId);
      if (clean) acc[clean.id] = clean;
      return acc;
    }, {});
    if (!nodes.input) {
      nodes.input = { id: 'input', type: 'input', x: 56, y: 72, width: DEFAULT_INPUT_NODE_WIDTH, height: DEFAULT_INPUT_NODE_HEIGHT };
    }
    normalizeNodeGroups(nodes);
    const edges = (Array.isArray(source.edges) ? source.edges : [])
      .map(edge => ({
        from: String(edge?.from || ''),
        to: String(edge?.to || '')
      }))
      .filter(edge => edge.from && edge.to && edge.from !== edge.to && nodes[edge.from] && nodes[edge.to]);
    const selectedNodeIds = expandNodeIdsToGroups(
      (Array.isArray(source.selectedNodeIds) ? source.selectedNodeIds : [source.selectedNodeId])
        .map(item => String(item || ''))
        .filter(nodeId => nodes[nodeId]),
      nodes
    );
    return {
      x: Number.isFinite(Number(source.x)) ? Number(source.x) : 0,
      y: Number.isFinite(Number(source.y)) ? Number(source.y) : 0,
      scale: clamp(Number(source.scale) || 1, MIN_SCALE, MAX_SCALE),
      selectedNodeId: selectedNodeIds[0] || '',
      selectedNodeIds,
      nodes,
      edges
    };
  }

  function normalizeWorkflowOutput(output = {}) {
    const clean = jsonClone(output, {});
    if (!clean || typeof clean !== 'object') return {};
    if (DesktopState.isInFlight?.(clean.status)) {
      clean.status = 'idle';
      clean.stage = '';
      clean.progressText = '';
      clean.progress = 0;
    }
    return clean;
  }

  function normalizeWorkflowOutputs(outputs = {}) {
    if (!outputs || typeof outputs !== 'object') return {};
    return Object.entries(outputs).reduce((acc, [nodeId, output]) => {
      acc[nodeId] = normalizeWorkflowOutput(output);
      return acc;
    }, {});
  }

  function extractWorkflowState(payload = {}) {
    const raw = payload?.schema === WORKFLOW_SCHEMA
      ? payload.state
      : (payload.state || payload.workflow || payload);
    if (!raw || typeof raw !== 'object' || !raw.canvas) {
      throw new Error('工作流文件格式不正确');
    }
    const params = normalizeWorkflowParams(raw.params || {}, DesktopState.state.params || {});
    return {
      provider: ['gpt', 'google', 'comfy'].includes(raw.provider) ? raw.provider : 'gpt',
      inputExpanded: raw.inputExpanded !== false,
      prompt: String(raw.prompt || ''),
      referenceImages: normalizeWorkflowReferences(raw.referenceImages),
      nodeReferenceImages: normalizeWorkflowReferenceMap(raw.nodeReferenceImages),
      params,
      canvas: normalizeWorkflowCanvas(raw.canvas),
      output: {
        ...normalizeWorkflowOutput(raw.output || {}),
        archiveEnabled: raw.output?.archiveEnabled !== false,
        telegramEnabled: raw.output?.telegramEnabled !== false
      },
      outputs: normalizeWorkflowOutputs(raw.outputs || {})
    };
  }

  function revokeWorkflowReferenceUrls(refs) {
    (Array.isArray(refs) ? refs : []).forEach(revokeReferenceUrl);
  }

  function revokeCurrentWorkflowObjectUrls() {
    revokeWorkflowReferenceUrls(DesktopState.state.referenceImages);
    Object.values(DesktopState.state.nodeReferenceImages || {}).forEach(revokeWorkflowReferenceUrls);
  }

  function buildWorkflowSnapshot() {
    syncVisibleInputNodeStatesToCanvas();
    DesktopState.saveSettings();
    const state = DesktopState.state;
    return extractWorkflowState({
      provider: state.provider,
      inputExpanded: state.inputExpanded,
      prompt: state.prompt,
      referenceImages: state.referenceImages,
      nodeReferenceImages: state.nodeReferenceImages,
      params: state.params,
      canvas: state.canvas,
      output: state.output,
      outputs: state.outputs
    });
  }

  function workflowTitleFromSnapshot(snapshot) {
    const textNode = Object.values(snapshot.canvas?.nodes || {})
      .find(node => node.type === 'text' && String(node.text || '').trim());
    const title = String(textNode?.alias || textNode?.text || 'canvas-workflow').trim().slice(0, 36);
    return sanitizeImageEditFilename(title, 'canvas-workflow');
  }

  function workflowTimestamp() {
    const now = new Date();
    const pad = value => String(value).padStart(2, '0');
    return [
      now.getFullYear(),
      pad(now.getMonth() + 1),
      pad(now.getDate())
    ].join('') + '-' + [pad(now.getHours()), pad(now.getMinutes())].join('');
  }

  function normalizeWorkflowFilename(name, fallback = 'canvas-workflow') {
    const clean = sanitizeImageEditFilename(name, fallback);
    return /\.(tcflow\.json|json)$/i.test(clean) ? clean : `${clean}.tcflow.json`;
  }

  function defaultWorkflowFilename(payload) {
    return normalizeWorkflowFilename(`${payload.title || 'canvas-workflow'}-${workflowTimestamp()}`);
  }

  function defaultWorkflowSavePath(filename) {
    return `~/Downloads/${normalizeWorkflowFilename(filename || 'canvas-workflow')}`;
  }

  async function chooseWorkflowSaveFile(blob, filename) {
    if (typeof window.showSaveFilePicker !== 'function') return false;
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{
          description: 'TapCanvas 工作流',
          accept: { 'application/json': ['.tcflow.json', '.json'] }
        }]
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return true;
    } catch (error) {
      if (error?.name === 'AbortError') return null;
      return false;
    }
  }

  async function saveWorkflowToCustomPath(payload, filename) {
    if (!window.DesktopApi?.saveWorkflowFileToPath || !window.prompt) return false;
    const targetPath = window.prompt('保存工作流完整路径', defaultWorkflowSavePath(filename));
    if (targetPath === null) return null;
    const cleanPath = String(targetPath || '').trim();
    if (!cleanPath) return null;

    const request = overwrite => window.DesktopApi.saveWorkflowFileToPath({
      path: cleanPath,
      payload,
      overwrite
    });

    try {
      await request(false);
      return true;
    } catch (error) {
      const message = String(error?.message || '');
      if (message.includes('文件已存在') && window.confirm?.('文件已存在，是否覆盖？')) {
        await request(true);
        return true;
      }
      throw error;
    }
  }

  function exportWorkflowSnapshot() {
    const snapshot = buildWorkflowSnapshot();
    return {
      schema: WORKFLOW_SCHEMA,
      version: WORKFLOW_VERSION,
      createdAt: new Date().toISOString(),
      title: workflowTitleFromSnapshot(snapshot),
      app: 'tg-mini-app-img-gen',
      state: snapshot
    };
  }

  async function saveWorkflowFile() {
    const payload = exportWorkflowSnapshot();
    const filename = defaultWorkflowFilename(payload);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const savedToFile = await chooseWorkflowSaveFile(blob, filename);
    if (savedToFile === null) return null;
    if (!savedToFile) {
      const savedToPath = await saveWorkflowToCustomPath(payload, filename);
      if (savedToPath === null) return null;
      if (!savedToPath) {
        const customName = window.prompt ? window.prompt('保存工作流文件名', filename) : filename;
        if (customName === null) return null;
        downloadBlob(blob, normalizeWorkflowFilename(customName || filename));
      }
    }
    DesktopResults.showTransientMessage('工作流文件已保存。');
    return payload;
  }

  function applyWorkflowSnapshot(payload, options = {}) {
    const next = extractWorkflowState(payload);
    if (options.confirm !== false && window.confirm && !window.confirm('加载工作流会替换当前画布，继续？')) {
      return false;
    }
    revokeCurrentWorkflowObjectUrls();
    DesktopState.state.provider = next.provider;
    DesktopState.state.inputExpanded = next.inputExpanded;
    DesktopState.state.prompt = next.prompt;
    DesktopState.state.referenceImages = next.referenceImages;
    DesktopState.state.nodeReferenceImages = next.nodeReferenceImages;
    DesktopState.state.params = next.params;
    DesktopState.state.canvas = next.canvas;
    DesktopState.state.output = {
      ...DesktopState.state.output,
      ...next.output
    };
    DesktopState.state.outputs = {
      ...next.outputs
    };
    ensureDefaultModelOutputState();
    document.querySelectorAll('.desk-node[data-node-id]:not(#deskInputNode)').forEach(node => node.remove());
    ensureTextNodeAliases();
    syncFormFromState();
    renderReferenceThumbs();
    applyAllNodeLayouts();
    notifyTextNodeListChange(DesktopState.state.canvas.selectedNodeId || '');
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    DesktopResults.renderIdleProviderHint?.();
    DesktopResults.showTransientMessage('工作流已加载。');
    return true;
  }

  function readWorkflowFile(file) {
    if (!file) return Promise.reject(new Error('请选择工作流文件'));
    if (typeof file.text === 'function') return file.text();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('工作流文件读取失败'));
      reader.readAsText(file, 'utf-8');
    });
  }

  async function loadWorkflowFile(file, options = {}) {
    const raw = await readWorkflowFile(file);
    let parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      throw new Error('工作流 JSON 解析失败');
    }
    return applyWorkflowSnapshot(parsed, options);
  }

  function normalizeImageEditColor(color) {
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(color || '').trim()) ? String(color).trim() : '#0b57d0';
  }

  function getImageEditState() {
    return activeImageEdit || null;
  }

  function setImageEditStatus(message = '就绪', tone = 'info') {
    const el = getImageEditorStatusEl();
    if (!el) return;
    el.dataset.tone = tone || 'info';
    el.textContent = message || '就绪';
  }

  function updateImageEditSourceLabel() {
    const el = getImageEditorSourceEl();
    const state = getImageEditState();
    if (!el || !state) return;
    const parts = [];
    if (state.sourceName) parts.push(state.sourceName);
    if (state.sourceWidth && state.sourceHeight) parts.push(`${state.sourceWidth} × ${state.sourceHeight}`);
    if (state.projectJson?.annotationCount !== undefined) parts.push(`${state.projectJson.annotationCount} 个标注`);
    if (state.projectJson?.maskCount !== undefined) parts.push(`${state.projectJson.maskCount} 个蒙版对象`);
    el.textContent = parts.join(' · ') || '已载入图片';
  }

  function updateImageEditUndoRedoButtons() {
    const state = getImageEditState();
    const undoBtn = imageEditorEl?.querySelector('[data-image-edit-undo]');
    const redoBtn = imageEditorEl?.querySelector('[data-image-edit-redo]');
    if (undoBtn) undoBtn.disabled = !state || !state.undoStack || state.undoStack.length <= 1;
    if (redoBtn) redoBtn.disabled = !state || !state.redoStack || state.redoStack.length === 0;
  }

  function isImageEditDarkTheme() {
    return String(document.body?.dataset?.theme || '').toLowerCase() === 'dark';
  }

  function syncImageEditToolIconFilters() {
    if (!imageEditorEl) return;
    const darkTheme = isImageEditDarkTheme();
    imageEditorEl.querySelectorAll('[data-image-edit-tool]').forEach(button => {
      const icon = button.querySelector('.desk-image-editor__tool-icon');
      if (!icon) return;
      const isActive = button.classList.contains('is-active');
      icon.style.filter = darkTheme || isActive ? 'brightness(0) invert(1)' : 'none';
    });
  }

  function ensureImageEditorThemeObserver() {
    if (imageEditorThemeObserver || !document.body) return;
    imageEditorThemeObserver = new MutationObserver(() => syncImageEditToolIconFilters());
    imageEditorThemeObserver.observe(document.body, { attributes: true, attributeFilter: ['data-theme'] });
  }

  function updateImageEditToolUi() {
    const state = getImageEditState();
    if (!state || !imageEditorEl) return;
    imageEditorEl.querySelectorAll('[data-image-edit-tool]').forEach(button => {
      const active = String(button.dataset.imageEditTool || '') === state.tool;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    imageEditorEl.querySelectorAll('[data-image-edit-color]').forEach(button => {
      const active = normalizeImageEditColor(button.dataset.imageEditColor) === state.color;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    imageEditorEl.querySelectorAll('[data-image-edit-shape]').forEach(button => {
      const active = String(button.dataset.imageEditShape || '') === getImageEditShapeMode(state);
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const sizeInput = imageEditorEl.querySelector('[data-image-edit-size]');
    if (sizeInput) sizeInput.value = String(state.brushSize || 22);
    syncImageEditToolIconFilters();
    updateImageEditZoomUi();
    updateImageEditSourceLabel();
    updateImageEditUndoRedoButtons();
  }

  function getImageEditObjects(role = '') {
    const canvas = getImageEditorCanvas();
    const objects = canvas?.getObjects?.() || [];
    return role ? objects.filter(object => object?.editRole === role) : objects;
  }

  function removeImageEditObjects(objects = []) {
    const canvas = getImageEditorCanvas();
    if (!canvas) return 0;
    const targets = (Array.isArray(objects) ? objects : [objects]).filter(object => object && object.editRole !== 'baseImage');
    if (!targets.length) return 0;
    targets.forEach(object => canvas.remove(object));
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    return targets.length;
  }

  function createImageEditTextStyle(color) {
    const normalizedColor = normalizeImageEditColor(color);
    return {
      fill: normalizedColor,
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Hiragino Sans GB", sans-serif',
      fontSize: imageEditScreenToCanvasSize(28),
      fontWeight: 700,
      lineHeight: 1.2,
      editable: true,
      hasControls: true,
      hasBorders: true,
      lockScalingX: false,
      lockScalingY: false,
      lockUniScaling: false,
      lockRotation: false,
      padding: imageEditScreenToCanvasSize(4),
      objectCaching: false
    };
  }

  function getImageEditShapeMode(state = getImageEditState()) {
    return ['rectOutline', 'rectFilled', 'ellipseOutline', 'ellipseFilled'].includes(state?.shapeMode)
      ? state.shapeMode
      : 'rectOutline';
  }

  function isImageEditShapeFilled(shapeMode) {
    return String(shapeMode || '').endsWith('Filled');
  }

  function isImageEditShapeEllipse(shapeMode) {
    return String(shapeMode || '').startsWith('ellipse');
  }

  function imageEditShapeKind(shapeMode) {
    return isImageEditShapeEllipse(shapeMode) ? 'ellipse' : 'rect';
  }

  function createImageEditShape(start, color, strokeWidth, shapeMode = 'rectOutline') {
    return isImageEditShapeEllipse(shapeMode)
      ? createImageEditEllipse(start, color, strokeWidth, shapeMode)
      : createImageEditRect(start, color, strokeWidth, shapeMode);
  }

  function createImageEditRect(start, color, strokeWidth, shapeMode = 'rectOutline') {
    const filled = isImageEditShapeFilled(shapeMode);
    const normalizedColor = normalizeImageEditColor(color);
    const canvasStrokeWidth = Math.max(1, Number(strokeWidth) || 1);
    const rect = new fabric.Rect({
      id: createImageEditId('rect'),
      left: start.x,
      top: start.y,
      width: 1,
      height: 1,
      originX: 'left',
      originY: 'top',
      fill: filled ? normalizedColor : 'rgba(255, 255, 255, 0.02)',
      stroke: normalizedColor,
      strokeWidth: filled ? Math.max(1, Math.min(4, canvasStrokeWidth / 3)) : canvasStrokeWidth,
      strokeUniform: true,
      rx: imageEditScreenToCanvasSize(4),
      ry: imageEditScreenToCanvasSize(4),
      selectable: true,
      evented: true,
      erasable: true,
      objectCaching: false,
      editRole: 'annotation',
      editKind: 'rect',
      shapeMode,
      sourceTool: 'shape'
    });
    return applyImageEditObjectControls(rect, normalizedColor);
  }

  function createImageEditEllipse(start, color, strokeWidth, shapeMode = 'ellipseOutline') {
    const filled = isImageEditShapeFilled(shapeMode);
    const normalizedColor = normalizeImageEditColor(color);
    const canvasStrokeWidth = Math.max(1, Number(strokeWidth) || 1);
    const ellipse = new fabric.Ellipse({
      id: createImageEditId('ellipse'),
      left: start.x,
      top: start.y,
      rx: 1,
      ry: 1,
      originX: 'left',
      originY: 'top',
      fill: filled ? normalizedColor : 'rgba(255, 255, 255, 0.02)',
      stroke: normalizedColor,
      strokeWidth: filled ? Math.max(1, Math.min(4, canvasStrokeWidth / 3)) : canvasStrokeWidth,
      strokeUniform: true,
      selectable: true,
      evented: true,
      erasable: true,
      objectCaching: false,
      editRole: 'annotation',
      editKind: 'ellipse',
      shapeMode,
      sourceTool: 'shape'
    });
    return applyImageEditObjectControls(ellipse, normalizedColor);
  }

  function buildImageEditArrowPath(start, end, strokeWidth) {
    const safeEnd = Math.hypot(end.x - start.x, end.y - start.y) < 1
      ? { x: start.x + 1, y: start.y }
      : end;
    const angle = Math.atan2(safeEnd.y - start.y, safeEnd.x - start.x);
    const headLength = Math.max(18, strokeWidth * 2.1);
    const wingAngle = Math.PI / 7;
    const wingA = {
      x: safeEnd.x - headLength * Math.cos(angle - wingAngle),
      y: safeEnd.y - headLength * Math.sin(angle - wingAngle)
    };
    const wingB = {
      x: safeEnd.x - headLength * Math.cos(angle + wingAngle),
      y: safeEnd.y - headLength * Math.sin(angle + wingAngle)
    };
    return `M ${start.x} ${start.y} L ${safeEnd.x} ${safeEnd.y} M ${safeEnd.x} ${safeEnd.y} L ${wingA.x} ${wingA.y} M ${safeEnd.x} ${safeEnd.y} L ${wingB.x} ${wingB.y}`;
  }

  function createImageEditArrow(start, end, color, strokeWidth) {
    const normalizedColor = normalizeImageEditColor(color);
    const canvasStrokeWidth = Math.max(2, Number(strokeWidth) || 2);
    const arrow = new fabric.Path(buildImageEditArrowPath(start, end, canvasStrokeWidth), {
      id: createImageEditId('arrow'),
      fill: null,
      stroke: normalizedColor,
      strokeWidth: canvasStrokeWidth,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      selectable: true,
      evented: true,
      erasable: true,
      strokeUniform: true,
      objectCaching: false,
      editRole: 'annotation',
      editKind: 'arrow',
      sourceTool: 'arrow'
    });
    applyImageEditObjectControls(arrow, normalizedColor);
    arrow.setCoords?.();
    return arrow;
  }

  function updateImageEditArrow(arrow, start, end, color, strokeWidth) {
    if (!arrow) return;
    const canvasStrokeWidth = Math.max(2, Number(strokeWidth) || 2);
    const path = new fabric.Path(buildImageEditArrowPath(start, end, canvasStrokeWidth));
    arrow.set({
      path: path.path,
      left: path.left,
      top: path.top,
      width: path.width,
      height: path.height,
      pathOffset: path.pathOffset,
      stroke: normalizeImageEditColor(color),
      strokeWidth: canvasStrokeWidth
    });
    applyImageEditObjectControls(arrow, color);
    arrow.dirty = true;
    arrow.setCoords?.();
  }

  function createImageEditPin(point, color, label) {
    const fill = normalizeImageEditColor(color);
    const unit = imageEditScreenToCanvasSize(1);
    const pinScale = Math.max(0.85, Math.round((42 / 24) * unit * 8) / 8);
    const labelText = String(label || '');
    const pinPath = 'M15 4.5l-4 4l-4 1.5l-1.5 1.5l7 7l1.5 -1.5l1.5 -4l4 -4 M9 15l-4.5 4.5 M14.5 4l5.5 5.5';
    const labelX = 8;
    const labelY = 9;
    const labelFontSize = labelText.length > 1 ? Math.max(3.8, 7.8 - labelText.length * 0.88) : 8.2;
    const childBase = {
      selectable: false,
      evented: false,
      objectCaching: false,
      noScaleCache: true
    };
    const pinStroke = {
      fill: null,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      ...childBase
    };
    const pin = new fabric.Group([
      new fabric.Path(pinPath, {
        left: 0,
        top: 0,
        originX: 'left',
        originY: 'top',
        stroke: fill,
        strokeWidth: 1,
        ...pinStroke
      }),
      new fabric.Text(labelText, {
        left: labelX,
        top: labelY,
        originX: 'center',
        originY: 'center',
        fill,
        fontFamily: '"SF Pro Rounded", ui-rounded, -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", sans-serif',
        fontSize: labelFontSize,
        fontWeight: 400,
        textAlign: 'center',
        lineHeight: 1,
        charSpacing: 0,
        selectable: false,
        evented: false,
        objectCaching: false,
        noScaleCache: true,
        stroke: null
      })
    ], {
      id: createImageEditId('pin'),
      left: Math.round(point.x - 12 * pinScale),
      top: Math.round(point.y - 12 * pinScale),
      originX: 'left',
      originY: 'top',
      scaleX: pinScale,
      scaleY: pinScale,
      selectable: true,
      evented: true,
      subTargetCheck: true,
      hasControls: true,
      hasBorders: true,
      lockScalingX: false,
      lockScalingY: false,
      lockUniScaling: false,
      lockRotation: false,
      borderColor: fill,
      cornerColor: '#ffffff',
      cornerStrokeColor: fill,
      transparentCorners: false,
      erasable: true,
      objectCaching: false,
      noScaleCache: true,
      editRole: 'annotation',
      editKind: 'pin',
      pinNumber: Number(label) || 0,
      annotationColor: fill,
      label: String(label || ''),
      sourceTool: 'pin'
    });
    return applyImageEditObjectControls(pin, fill);
  }

  function setImageEditObjectMeta(object, role, kind, tool = '') {
    if (!object) return object;
    object.set({
      id: object.id || createImageEditId(kind || role || 'item'),
      editRole: role,
      editKind: kind || role,
      sourceTool: tool || kind || role,
      erasable: role !== 'baseImage',
      objectCaching: false
    });
    return object;
  }

  function getImageEditPinNumber() {
    return getImageEditObjects('annotation')
      .filter(object => object?.editKind === 'pin')
      .reduce((max, pin) => Math.max(max, Number(pin.pinNumber || pin.label || 0) || 0), 0) + 1;
  }

  function serializeImageEditObject(object) {
    if (!object?.toObject) return null;
    const json = object.toObject(getImageEditCustomProps());
    if (object.erasable !== undefined) {
      json.erasable = object.erasable;
    }
    if (object.eraser?.toObject) {
      json.eraser = object.eraser.toObject(getImageEditCustomProps());
    }
    return json;
  }

  function serializeImageEditCanvas() {
    const canvas = getImageEditorCanvas();
    if (!canvas) return null;
    const json = canvas.toJSON(getImageEditCustomProps());
    json.objects = (canvas.getObjects?.() || [])
      .filter(object => object?.editRole !== 'baseImage')
      .map(object => serializeImageEditObject(object))
      .filter(Boolean);
    return json;
  }

  function buildImageEditProjectJson(state = getImageEditState()) {
    const canvas = getImageEditorCanvas();
    if (!canvas || !state) return null;
    return {
      version: 1,
      source: {
        nodeId: state.nodeId || '',
        name: state.sourceName || '',
        mimeType: state.sourceMimeType || 'image/png',
        width: state.sourceWidth || canvas.getWidth() || 1,
        height: state.sourceHeight || canvas.getHeight() || 1
      },
      canvasJson: serializeImageEditCanvas(),
      tool: state.tool || 'select',
      color: state.color || '#0b57d0',
      shapeMode: getImageEditShapeMode(state),
      brushSize: state.brushSize || 22,
      pinCounter: getImageEditPinNumber(),
      hasMask: Boolean(getImageEditObjects('mask').length || state.legacyMaskDataUrl),
      maskCount: getImageEditObjects('mask').length,
      annotationCount: getImageEditObjects('annotation').length
    };
  }

  function createImageEditSnapshot(state = getImageEditState()) {
    if (!state) return null;
    return {
      canvasJson: serializeImageEditCanvas(),
      prompt: String(getImageEditorPromptInput()?.value || '').trim(),
      tool: state.tool || 'select',
      color: state.color || '#0b57d0',
      shapeMode: getImageEditShapeMode(state),
      brushSize: state.brushSize || 22,
      legacyMaskDataUrl: state.legacyMaskDataUrl || '',
      sourceName: state.sourceName || '',
      sourceWidth: state.sourceWidth || 1,
      sourceHeight: state.sourceHeight || 1
    };
  }

  function imageEditSnapshotKey(snapshot) {
    return snapshot ? JSON.stringify(snapshot) : '';
  }

  function resetImageEditHistory(snapshot = null) {
    const state = getImageEditState();
    if (!state) return;
    state.undoStack = [];
    state.redoStack = [];
    state.historyKey = '';
    if (snapshot) {
      state.undoStack.push(cloneImageEditValue(snapshot));
      state.historyKey = imageEditSnapshotKey(snapshot);
    }
    updateImageEditUndoRedoButtons();
  }

  function recordImageEditSnapshot(label = '') {
    const state = getImageEditState();
    if (!state || state.restoring) return;
    const snapshot = createImageEditSnapshot();
    if (!snapshot) return;
    const key = imageEditSnapshotKey(snapshot);
    if (!key || key === state.historyKey) return;
    state.undoStack.push(snapshot);
    if (state.undoStack.length > state.historyLimit) state.undoStack.shift();
    state.redoStack = [];
    state.historyKey = key;
    state.projectJson = buildImageEditProjectJson(state);
    updateImageEditSourceLabel();
    updateImageEditUndoRedoButtons();
    if (label) setImageEditStatus(`${label}，可继续编辑`, 'info');
  }

  async function loadFabricImage(src) {
    if (!src) return null;
    return new Promise((resolve, reject) => {
      fabric.Image.fromURL(src, image => {
        if (!image) {
          reject(new Error('图片加载失败'));
          return;
        }
        resolve(image);
      }, { crossOrigin: 'anonymous' });
    });
  }

  async function loadImageEditSource(sourceDataUrl, width, height, overlayJson = null, legacyMaskDataUrl = '') {
    const canvas = ensureImageEditFabricCanvas();
    const canvasWidth = Math.max(1, Math.round(Number(width) || 1));
    const canvasHeight = Math.max(1, Math.round(Number(height) || 1));
    canvas.clear();
    applyImageEditCanvasPanOffset(0, 0);
    applyImageEditCanvasDisplaySize(canvas, canvasWidth, canvasHeight, { preserveViewport: false });
    canvas.backgroundColor = 'transparent';
    if (overlayJson?.objects?.length) {
      await new Promise(resolve => {
        canvas.loadFromJSON(cloneImageEditValue(overlayJson), () => resolve());
      });
      canvas.getObjects().forEach(object => {
        if (object?.editRole && object.editRole !== 'baseImage') {
          object.set({
            erasable: true,
            objectCaching: false
          });
          applyImageEditObjectControls(object, object.stroke || object.fill || object.annotationColor || object.maskColor || '#0b57d0');
          object.setCoords?.();
        }
      });
    }
    const image = await loadFabricImage(sourceDataUrl);
    if (!image) throw new Error('图片加载失败');
    const baseWidth = canvasWidth || image.width || 1;
    const baseHeight = canvasHeight || image.height || 1;
    image.set({
      left: 0,
      top: 0,
      originX: 'left',
      originY: 'top',
      selectable: false,
      evented: false,
      hasControls: false,
      hasBorders: false,
      lockMovementX: true,
      lockMovementY: true,
      lockScalingX: true,
      lockScalingY: true,
      lockRotation: true,
      hoverCursor: 'default',
      editRole: 'baseImage',
      editKind: 'baseImage',
      sourceTool: 'baseImage',
      erasable: false,
      objectCaching: false
    });
    image.scaleX = baseWidth / Math.max(1, image.width || baseWidth);
    image.scaleY = baseHeight / Math.max(1, image.height || baseHeight);
    canvas.add(image);
    canvas.sendToBack(image);
    const hasMaskObjectInJson = Array.isArray(overlayJson?.objects)
      && overlayJson.objects.some(object => object?.editRole === 'mask');
    if (legacyMaskDataUrl && !hasMaskObjectInJson) {
      const legacyMask = await loadFabricImage(legacyMaskDataUrl);
      if (legacyMask) {
        legacyMask.set({
          left: 0,
          top: 0,
          originX: 'left',
          originY: 'top',
          selectable: false,
          evented: false,
          hasControls: false,
          hasBorders: false,
          lockMovementX: true,
          lockMovementY: true,
          lockScalingX: true,
          lockScalingY: true,
          lockRotation: true,
          hoverCursor: 'default',
          editRole: 'mask',
          editKind: 'legacyMask',
          sourceTool: 'mask',
          erasable: true,
          objectCaching: false
        });
        legacyMask.scaleX = baseWidth / Math.max(1, legacyMask.width || baseWidth);
        legacyMask.scaleY = baseHeight / Math.max(1, legacyMask.height || baseHeight);
        canvas.add(legacyMask);
      }
    }
    canvas.requestRenderAll();
    canvas.calcOffset?.();
    return image;
  }

  async function restoreImageEditSnapshot(snapshot) {
    const state = getImageEditState();
    if (!state || !snapshot) return;
    state.restoring = true;
    try {
      await loadImageEditSource(state.sourceDataUrl, state.sourceWidth, state.sourceHeight, snapshot.canvasJson, snapshot.legacyMaskDataUrl || '');
      state.legacyMaskDataUrl = snapshot.legacyMaskDataUrl || state.legacyMaskDataUrl || '';
      state.tool = snapshot.tool || state.tool || 'select';
      state.color = normalizeImageEditColor(snapshot.color || state.color);
      state.shapeMode = getImageEditShapeMode(snapshot);
      state.brushSize = Math.max(2, Math.min(120, Number(snapshot.brushSize || state.brushSize) || 22));
      setImageEditTool(state.tool);
      setImageEditBrushSize(state.brushSize);
      state.historyKey = imageEditSnapshotKey(snapshot);
      updateImageEditToolUi();
      updateImageEditUndoRedoButtons();
    } finally {
      state.restoring = false;
    }
  }

  function ensureImageEditFabricCanvas() {
    if (imageEditorCanvas) return imageEditorCanvas;
    const canvasEl = getImageEditorCanvasElement();
    if (!canvasEl || !window.fabric) throw new Error('Fabric.js 未加载');
    imageEditorCanvas = new fabric.Canvas(canvasEl, {
      preserveObjectStacking: true,
      selection: true,
      backgroundColor: 'transparent',
      enableRetinaScaling: false,
      renderOnAddRemove: true
    });
    imageEditorCanvas.on('mouse:down', event => {
      const state = getImageEditState();
      if (!state) return;
      const tool = state.tool || 'select';
      const pointer = imageEditorCanvas.getPointer(event.e);
      state.lastPointer = pointer;
      state.panning = false;
      state.panStart = null;
      state.panScrollStart = null;
      state.panOffsetStart = null;
      const isPrimaryButton = !event?.e || event.e.button === 0;
      if (tool === 'eraser') {
        return;
      }
      if (tool === 'select' && isPrimaryButton) {
        const target = imageEditorCanvas.findTarget?.(event.e, false);
        if (!target || target.editRole === 'baseImage') {
          state.panning = true;
          state.panStart = { x: event.e?.clientX || 0, y: event.e?.clientY || 0 };
          state.panOffsetStart = { x: state.canvasPanX || 0, y: state.canvasPanY || 0 };
          imageEditorCanvas.discardActiveObject();
          imageEditorCanvas.requestRenderAll();
          event.e?.preventDefault?.();
          event.e?.stopPropagation?.();
          return;
        }
      }
      if (tool === 'text') {
        const object = new fabric.IText('双击输入', {
          id: createImageEditId('text'),
          left: pointer.x,
          top: pointer.y,
          originX: 'left',
          originY: 'top',
          ...createImageEditTextStyle(state.color),
          editRole: 'annotation',
          editKind: 'text',
          sourceTool: 'text',
          erasable: true
        });
        applyImageEditObjectControls(object, state.color);
        imageEditorCanvas.add(object);
        imageEditorCanvas.setActiveObject(object);
        imageEditorCanvas.requestRenderAll();
        setImageEditTool('select');
        recordImageEditSnapshot('已添加文字');
        setImageEditStatus('已添加文字，拖动控制点可调整大小，双击可编辑', 'info');
        return;
      }
      if (tool === 'pin') {
        const object = createImageEditPin(pointer, state.color, getImageEditPinNumber());
        imageEditorCanvas.add(object);
        imageEditorCanvas.setActiveObject(object);
        imageEditorCanvas.requestRenderAll();
        recordImageEditSnapshot('已添加 pin');
        setImageEditStatus('已添加 pin，可继续点击放置下一个', 'info');
        return;
      }
      if (tool === 'select') return;
      state.drafting = true;
      state.draftTool = tool;
      state.draftStart = pointer;
      if (tool === 'shape') {
        state.draftObject = createImageEditShape(pointer, state.color, state.brushSize, getImageEditShapeMode(state));
      } else if (tool === 'arrow') {
        state.draftObject = createImageEditArrow(pointer, pointer, state.color, state.brushSize);
      } else {
        state.draftObject = null;
      }
      if (state.draftObject) {
        imageEditorCanvas.add(state.draftObject);
        imageEditorCanvas.setActiveObject(state.draftObject);
      }
      imageEditorCanvas.requestRenderAll();
    });
    imageEditorCanvas.on('mouse:move', event => {
      const state = getImageEditState();
      if (!state) return;
      if (state.panning && state.panStart && state.panOffsetStart) {
        const dx = (event.e?.clientX || 0) - state.panStart.x;
        const dy = (event.e?.clientY || 0) - state.panStart.y;
        applyImageEditCanvasPanOffset(state.panOffsetStart.x + dx, state.panOffsetStart.y + dy);
        event.e?.preventDefault?.();
        event.e?.stopPropagation?.();
        return;
      }
      if (!state.drafting || !state.draftObject || !state.draftStart) return;
      const pointer = imageEditorCanvas.getPointer(event.e);
      if (!pointer) return;
      state.lastPointer = pointer;
      const start = state.draftStart;
      const left = Math.min(pointer.x, start.x);
      const top = Math.min(pointer.y, start.y);
      const width = Math.abs(pointer.x - start.x);
      const height = Math.abs(pointer.y - start.y);
      if (state.draftTool === 'shape' && !isImageEditShapeEllipse(getImageEditShapeMode(state))) {
        state.draftObject.set({ left, top, width, height });
      } else if (state.draftTool === 'shape') {
        state.draftObject.set({ left, top, rx: Math.max(1, width / 2), ry: Math.max(1, height / 2) });
      } else if (state.draftTool === 'arrow') {
        updateImageEditArrow(state.draftObject, start, pointer, state.color, state.brushSize);
      }
      state.draftObject.setCoords?.();
      imageEditorCanvas.requestRenderAll();
    });
    imageEditorCanvas.on('mouse:up', event => {
      const state = getImageEditState();
      if (!state) return;
      if (state.panning) {
        state.panning = false;
        state.panStart = null;
        state.panScrollStart = null;
        state.panOffsetStart = null;
        return;
      }
      if (state.drafting && state.draftObject) {
        const object = state.draftObject;
        const start = state.draftStart;
        const end = event?.e ? imageEditorCanvas.getPointer(event.e) : (state.lastPointer || start);
        const minShapeSize = imageEditScreenToCanvasSize(3);
        if (state.draftTool === 'shape' && object.editKind === 'rect' && (Number(object.width) < minShapeSize || Number(object.height) < minShapeSize)) {
          imageEditorCanvas.remove(object);
        } else if (state.draftTool === 'shape' && object.editKind === 'ellipse' && (Number(object.rx) < minShapeSize / 2 || Number(object.ry) < minShapeSize / 2)) {
          imageEditorCanvas.remove(object);
        } else if (state.draftTool === 'arrow' && Math.hypot((end?.x || start.x) - start.x, (end?.y || start.y) - start.y) < imageEditScreenToCanvasSize(3)) {
          imageEditorCanvas.remove(object);
        } else if (state.draftTool === 'arrow') {
          updateImageEditArrow(object, start, end || start, state.color, state.brushSize);
        }
        imageEditorCanvas.requestRenderAll();
        recordImageEditSnapshot('已更新');
      }
      state.draftObject = null;
      state.draftStart = null;
      state.draftTool = '';
      state.drafting = false;
    });
    imageEditorCanvas.on('path:created', event => {
      const state = getImageEditState();
      const path = event?.path;
      if (!state || !path) return;
      if (state.tool === 'eraser') {
        window.setTimeout(() => {
          const activeState = getImageEditState();
          if (!activeState || activeState !== state || activeState.restoring) return;
          recordImageEditSnapshot('已擦除标注');
        }, 48);
        return;
      }
      const isMask = state.tool === 'maskBrush';
      setImageEditObjectMeta(path, isMask ? 'mask' : 'annotation', isMask ? 'maskStroke' : 'brush', state.tool);
      path.set({
        fill: null,
        stroke: isMask ? 'rgba(255, 106, 34, 0.9)' : normalizeImageEditColor(state.color),
        strokeWidth: state.brushSize,
        strokeLineCap: 'round',
        strokeLineJoin: 'round',
        opacity: 1
      });
      applyImageEditObjectControls(path, isMask ? '#ffffff' : state.color);
      path.setCoords?.();
      imageEditorCanvas.requestRenderAll();
      recordImageEditSnapshot(isMask ? '已添加蒙版' : '已添加涂抹');
    });
    imageEditorCanvas.on('object:modified', event => {
      const state = getImageEditState();
      const target = event?.target;
      if (!state || state.restoring || !target || target.editRole === 'baseImage') return;
      recordImageEditSnapshot('已修改对象');
    });
    imageEditorCanvas.on('object:removed', event => {
      const state = getImageEditState();
      const target = event?.target;
      if (!state || state.restoring || !target || target.editRole === 'baseImage') return;
      recordImageEditSnapshot('已删除对象');
    });
    imageEditorCanvas.on('selection:created', handleImageEditSelectionChange);
    imageEditorCanvas.on('selection:updated', handleImageEditSelectionChange);
    imageEditorCanvas.on('selection:cleared', updateImageEditUndoRedoButtons);
    imageEditorCanvas.on('text:editing:exited', () => recordImageEditSnapshot('文字已更新'));
    if (!imageEditorCanvas.__imageEditPanBound) {
      imageEditorCanvas.__imageEditPanBound = true;
      const clearPanState = () => {
        const state = getImageEditState();
        if (!state) return;
        state.panning = false;
        state.panStart = null;
        state.panScrollStart = null;
        state.panOffsetStart = null;
      };
      window.addEventListener('pointerup', clearPanState, { passive: true });
      window.addEventListener('pointercancel', clearPanState, { passive: true });
    }
    if (!imageEditorCanvas.__imageEditResizeBound) {
      imageEditorCanvas.__imageEditResizeBound = true;
      window.addEventListener('resize', () => {
        const state = getImageEditState();
        if (!state || !imageEditorEl?.classList.contains('is-open')) return;
        applyImageEditCanvasDisplaySize(imageEditorCanvas, state.sourceWidth, state.sourceHeight);
      }, { passive: true });
    }
    return imageEditorCanvas;
  }

  function setImageEditTool(tool) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    if (tool === 'rect') {
      state.shapeMode = 'rectOutline';
      tool = 'shape';
    } else if (tool === 'ellipse') {
      state.shapeMode = 'ellipseOutline';
      tool = 'shape';
    }
    const nextTool = ['select', 'brush', 'maskBrush', 'shape', 'arrow', 'text', 'pin', 'eraser'].includes(tool) ? tool : 'select';
    state.tool = nextTool;
    canvas.isDrawingMode = nextTool === 'brush' || nextTool === 'maskBrush' || nextTool === 'eraser';
    canvas.selection = false;
    canvas.skipTargetFind = nextTool !== 'select';
    applyImageEditCursor(canvas, nextTool, state);
    if (canvas.isDrawingMode) {
      const brush = nextTool === 'eraser'
        ? (typeof fabric.EraserBrush === 'function' ? new fabric.EraserBrush(canvas) : null)
        : new fabric.PencilBrush(canvas);
      if (!brush) {
        state.tool = 'select';
        canvas.isDrawingMode = false;
        canvas.skipTargetFind = false;
        applyImageEditCursor(canvas, 'select', state);
        throw new Error('当前 Fabric 构建未包含官方橡皮擦模块');
      }
      brush.width = state.brushSize || 22;
      if (nextTool === 'eraser') {
        brush.inverted = false;
        brush.decimate = 0;
        brush.strokeLineCap = 'round';
        brush.strokeLineJoin = 'round';
      } else {
        brush.color = nextTool === 'maskBrush'
          ? 'rgba(255, 106, 34, 0.88)'
          : normalizeImageEditColor(state.color);
        brush.strokeLineCap = 'round';
        brush.strokeLineJoin = 'round';
      }
      canvas.freeDrawingBrush = brush;
    }
    if (nextTool !== 'select' && canvas.getActiveObject?.()) {
      canvas.discardActiveObject();
    }
    setImageEditStatus(
      nextTool === 'select' ? '选择与移动' :
      nextTool === 'brush' ? '画笔涂抹' :
      nextTool === 'maskBrush' ? '蒙版涂抹' :
      nextTool === 'shape' ? `拖拽绘制${getImageEditShapeLabel(state.shapeMode)}` :
      nextTool === 'arrow' ? '拖拽绘制箭头' :
      nextTool === 'text' ? '点击放置文字' :
      nextTool === 'pin' ? '点击放置 pin' : '拖拽擦除标注',
      nextTool === 'eraser' ? 'warn' : 'info'
    );
    updateImageEditToolUi();
    canvas.requestRenderAll();
  }

  function getImageEditCursor(tool, state = getImageEditState()) {
    const selectCursor = 'default';
    const brushCursor = getImageEditCursorUrl(getImageEditCursorAsset('brush'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.brush);
    const maskBrushCursor = getImageEditCursorUrl(getImageEditCursorAsset('maskBrush'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.maskBrush);
    const shapeCursor = getImageEditCursorUrl(getImageEditCursorAsset('shape'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.shape);
    const arrowCursor = getImageEditCursorUrl(getImageEditCursorAsset('arrow'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.arrow);
    const pinCursor = getImageEditCursorUrl(getImageEditCursorAsset('pin'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.pin);
    const eraserCursor = getImageEditCursorUrl(getImageEditCursorAsset('eraser'), ...IMAGE_EDIT_CURSOR_HOTSPOTS.eraser);
    if (tool === 'select') return selectCursor;
    if (tool === 'brush') return brushCursor;
    if (tool === 'maskBrush') return maskBrushCursor;
    if (tool === 'shape') return shapeCursor;
    if (tool === 'arrow') return arrowCursor;
    if (tool === 'text') return 'text';
    if (tool === 'pin') return pinCursor;
    if (tool === 'eraser') return eraserCursor;
    return selectCursor;
  }

  function applyImageEditCursor(canvas, tool, state = getImageEditState()) {
    const cursor = getImageEditCursor(tool, state);
    if (imageEditorEl) {
      imageEditorEl.style.setProperty('--desk-image-edit-cursor', cursor);
    }
    canvas.defaultCursor = cursor;
    canvas.hoverCursor = cursor;
    canvas.moveCursor = cursor;
    canvas.freeDrawingCursor = cursor;
    const cursorTargets = [
      canvas.upperCanvasEl,
      canvas.lowerCanvasEl,
      canvas.wrapperEl,
      canvas.containerClass ? canvas.wrapperEl?.querySelector?.('.canvas-container') : null,
      imageEditorEl?.querySelector('.desk-image-editor__canvas-shell'),
      imageEditorEl?.querySelector('.desk-image-editor__canvas-wrap'),
      imageEditorEl?.querySelector('.desk-image-editor__stage'),
      imageEditorEl
    ].filter(Boolean);
    cursorTargets.forEach(target => {
      target.style.cursor = cursor;
    });
  }

  function getImageEditShapeLabel(shapeMode) {
    return shapeMode === 'rectFilled' ? '实心矩形'
      : shapeMode === 'ellipseOutline' ? '空心圆形'
      : shapeMode === 'ellipseFilled' ? '实心圆形'
      : '空心矩形';
  }

  function setImageEditShapeMode(shapeMode) {
    const state = getImageEditState();
    if (!state) return;
    state.shapeMode = ['rectOutline', 'rectFilled', 'ellipseOutline', 'ellipseFilled'].includes(shapeMode)
      ? shapeMode
      : 'rectOutline';
    setImageEditTool('shape');
  }

  function setImageEditColor(color) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    state.color = normalizeImageEditColor(color);
    const recoloredCount = setImageEditSelectedObjectsColor(state.color);
    const brush = canvas.freeDrawingBrush;
    if (brush && canvas.isDrawingMode && state.tool === 'brush') {
      brush.color = state.color;
    }
    updateImageEditToolUi();
    if (!recoloredCount) setImageEditStatus(`当前颜色 ${state.color}`, 'info');
  }

  function setImageEditBrushSize(value) {
    const state = getImageEditState();
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return;
    state.brushSize = Math.max(2, Math.min(120, Number(value) || 22));
    if (canvas.freeDrawingBrush) canvas.freeDrawingBrush.width = state.brushSize;
    const sizeInput = imageEditorEl?.querySelector('[data-image-edit-size]');
    if (sizeInput) sizeInput.value = String(state.brushSize);
  }

  async function exportImageEditAnnotatedDataUrl() {
    const canvas = getImageEditorCanvas();
    if (!canvas) return '';
    const hidden = [];
    const previousViewport = canvas.viewportTransform?.slice?.() || [1, 0, 0, 1, 0, 0];
    canvas.getObjects().forEach(object => {
      if (object.editRole === 'mask') {
        hidden.push([object, object.visible]);
        object.visible = false;
      }
    });
    canvas.discardActiveObject();
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    canvas.renderAll();
    const dataUrl = canvas.toDataURL({ format: 'png', multiplier: 1, enableRetinaScaling: false });
    hidden.forEach(([object, visible]) => {
      object.visible = visible;
    });
    canvas.setViewportTransform(previousViewport);
    canvas.requestRenderAll();
    return dataUrl;
  }

  async function exportImageEditAnnotatedToNode() {
    const state = getImageEditState();
    if (!state?.nodeId) throw new Error('没有可导出的编辑项目');
    const dataUrl = await exportImageEditAnnotatedDataUrl();
    if (!dataUrl) throw new Error('没有可导出的合成图');
    await saveImageEditState(state);
    const meta = await readImageMeta(dataUrl);
    const sourceNode = DesktopState.state.canvas.nodes[state.nodeId] || {};
    const sourceBounds = getNodeBoundsById(state.nodeId);
    const center = sourceBounds
      ? { x: sourceBounds.x + sourceBounds.width + 260, y: sourceBounds.y + sourceBounds.height / 2 }
      : getViewportCenterWorldPoint(320, 0);
    const baseName = sanitizeImageEditFilename(state.sourceName || sourceNode.imageName || state.nodeId || 'annotated');
    const nodeId = insertImageNode({
      imageData: dataUrl,
      imageName: `${baseName}-annotated.png`,
      mimeType: 'image/png',
      taskId: sourceNode.sourceTaskId || '',
      assetId: sourceNode.sourceAssetId || '',
      prompt: String(getImageEditorPromptInput()?.value || '').trim(),
      title: `${sourceNode.imageName || state.sourceName || state.nodeId} 标注图`,
      file: `${baseName}-annotated.png`,
      provider: sourceNode.sourceProvider || '',
      source: 'image-editor-export',
      meta
    }, center, {
      popOrigin: sourceBounds
        ? { x: sourceBounds.x + sourceBounds.width / 2, y: sourceBounds.y + sourceBounds.height / 2 }
        : null
    });
    closeImageEditor();
    DesktopResults.showTransientMessage('合成图已导出到桌面图片节点。');
    return nodeId;
  }

  async function exportImageEditMaskDataUrl(state = getImageEditState()) {
    const canvas = getImageEditorCanvas();
    if (!state || !canvas) return '';
    const maskObjects = getImageEditObjects('mask');
    if (!maskObjects.length) return state.legacyMaskDataUrl || '';
    const maskCanvasEl = document.createElement('canvas');
    maskCanvasEl.width = canvas.getWidth();
    maskCanvasEl.height = canvas.getHeight();
    const maskCanvas = new fabric.StaticCanvas(maskCanvasEl, {
      width: canvas.getWidth(),
      height: canvas.getHeight(),
      backgroundColor: '#000000',
      enableRetinaScaling: false,
      renderOnAddRemove: false
    });
    const serializedMasks = maskObjects
      .map(object => serializeImageEditObject(object))
      .filter(Boolean);
    const clones = await new Promise(resolve => {
      fabric.util.enlivenObjects(serializedMasks, items => resolve(items || []));
    });
    clones.forEach(object => {
      object.set({
        selectable: false,
        evented: false,
        objectCaching: false,
        fill: object.type === 'path' ? null : '#ffffff',
        stroke: '#ffffff',
        opacity: 1
      });
      maskCanvas.add(object);
    });
    maskCanvas.renderAll();
    return maskCanvasEl.toDataURL('image/png');
  }

  function clearImageEditorMask() {
    const state = getImageEditState();
    if (!state) return;
    const removed = removeImageEditObjects(getImageEditObjects('mask'));
    state.legacyMaskDataUrl = '';
    state.projectJson = buildImageEditProjectJson();
    if (removed) recordImageEditSnapshot('蒙版已清空');
  }

  function clearImageEditorAnnotations() {
    const state = getImageEditState();
    if (!state) return;
    const removed = removeImageEditObjects(getImageEditObjects('annotation'));
    state.projectJson = buildImageEditProjectJson();
    if (removed) recordImageEditSnapshot('标注已清空');
  }

  function closeImageEditor() {
    const currentState = activeImageEdit;
    if (currentState) {
      saveImageEditState(currentState).catch(() => {});
    }
    activeImageEdit = null;
    imageEditorEl?.classList.remove('is-open');
    imageEditorEl?.setAttribute('aria-hidden', 'true');
  }

  async function saveImageEditState(editState = activeImageEdit) {
    if (!editState?.nodeId) return null;
    const node = DesktopState.state.canvas.nodes[editState.nodeId];
    if (!node) return null;
    const prompt = String(getImageEditorPromptInput()?.value || '').trim();
    const maskData = await exportImageEditMaskDataUrl(editState);
    const projectJson = buildImageEditProjectJson(editState);
    node.editState = {
      ...(node.editState || {}),
      editPrompt: prompt,
      hasMask: !!projectJson?.hasMask || !!maskData,
      maskData,
      maskOverlayData: maskData,
      projectJson
    };
    DesktopState.saveSettings();
    refreshImageNode(editState.nodeId);
    return node.editState;
  }

  function buildImageEditPrompt(note, hasMask) {
    const clean = String(note || '').trim();
    if (!clean) return '';
    return hasMask
      ? `只编辑蒙版透明区域对应的局部对象，未被蒙版覆盖的角色、姿态、光照、背景和构图必须保持不变。\n\n编辑要求：${clean}`
      : clean;
  }

  async function openImageEditor(nodeId) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'image') return;
    const modal = ensureImageEditor();
    const promptInput = getImageEditorPromptInput();
    const title = modal.querySelector('[data-image-edit-title]');
    const source = node.imageData || node.imageUrl || '';
    if (!source) throw new Error('图片节点没有可编辑的图片');
    const meta = await readImageMeta(source);
    const projectJson = cloneImageEditValue(node.editState?.projectJson || null);
    activeImageEdit = {
      nodeId,
      sourceDataUrl: source,
      sourceName: node.imageName || node.sourceTitle || node.id,
      sourceMimeType: node.mimeType || 'image/png',
      sourceWidth: meta.width || 1,
      sourceHeight: meta.height || 1,
      tool: projectJson?.tool || 'select',
      brushSize: Math.max(2, Math.min(120, Number(projectJson?.brushSize || 22) || 22)),
      color: normalizeImageEditColor(projectJson?.color || '#0b57d0'),
      shapeMode: getImageEditShapeMode(projectJson || {}),
      pinCounter: Number(projectJson?.pinCounter || 0) || 1,
      displayZoom: 0,
      fitScale: 1,
      zoomMode: 'fit',
      legacyMaskDataUrl: node.editState?.maskData || node.editState?.maskOverlayData || '',
      projectJson: null,
      undoStack: [],
      redoStack: [],
      historyKey: '',
      historyLimit: 60,
      restoring: false,
      panning: false,
      panStart: null,
      panScrollStart: null,
      panOffsetStart: null,
      canvasPanX: 0,
      canvasPanY: 0,
      drafting: false,
      draftStart: null,
      draftObject: null,
      draftTool: '',
      lastPointer: null
    };
    if (title) title.textContent = '图片编辑';
    if (promptInput) promptInput.value = node.editState?.editPrompt || '';
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    ensureImageEditorThemeObserver();
    setImageEditStatus('载入图片中', 'info');
    await loadImageEditSource(source, activeImageEdit.sourceWidth, activeImageEdit.sourceHeight, null, activeImageEdit.legacyMaskDataUrl || '');
    const canvas = ensureImageEditFabricCanvas();
    if (projectJson?.canvasJson?.objects?.length) {
      activeImageEdit.restoring = true;
      try {
        await restoreImageEditSnapshot({
          canvasJson: projectJson.canvasJson,
          tool: projectJson.tool || activeImageEdit.tool,
          color: projectJson.color || activeImageEdit.color,
          shapeMode: projectJson.shapeMode || activeImageEdit.shapeMode,
          brushSize: projectJson.brushSize || activeImageEdit.brushSize,
          legacyMaskDataUrl: node.editState?.maskData || node.editState?.maskOverlayData || ''
        });
      } finally {
        activeImageEdit.restoring = false;
      }
    }
    activeImageEdit.projectJson = buildImageEditProjectJson();
    resetImageEditHistory(createImageEditSnapshot());
    setImageEditBrushSize(activeImageEdit.brushSize);
    setImageEditTool(activeImageEdit.tool || 'select');
    window.requestAnimationFrame(() => {
      applyImageEditCanvasDisplaySize(canvas, activeImageEdit.sourceWidth, activeImageEdit.sourceHeight);
      canvas.calcOffset?.();
      canvas.requestRenderAll();
      updateImageEditToolUi();
      clearImageEditorStatusToDefault();
    });
  }

  function clearImageEditorStatusToDefault() {
    setImageEditStatus('就绪', 'info');
  }

  async function restoreImageEditSnapshotFromState(state, snapshot) {
    if (!state || !snapshot) return;
    await restoreImageEditSnapshot(snapshot);
    state.legacyMaskDataUrl = snapshot.legacyMaskDataUrl || state.legacyMaskDataUrl || '';
  }

  function bindImageEditorEvents(modal) {
    modal.querySelector('[data-image-edit-close]')?.addEventListener('click', closeImageEditor);
    modal.addEventListener('pointerdown', event => {
      if (event.target === modal) closeImageEditor();
    });
    modal.querySelectorAll('[data-image-edit-tool]').forEach(button => {
      button.addEventListener('click', () => setImageEditTool(button.dataset.imageEditTool || 'select'));
    });
    modal.querySelectorAll('[data-image-edit-color]').forEach(button => {
      button.addEventListener('click', () => setImageEditColor(button.dataset.imageEditColor || '#0b57d0'));
    });
    modal.querySelectorAll('[data-image-edit-shape]').forEach(button => {
      button.addEventListener('click', () => setImageEditShapeMode(button.dataset.imageEditShape || 'rectOutline'));
    });
    modal.querySelector('[data-image-edit-size]')?.addEventListener('input', event => {
      setImageEditBrushSize(event.target.value);
    });
    modal.querySelector('[data-image-edit-zoom-out]')?.addEventListener('click', () => {
      const state = getImageEditState();
      if (!state) return;
      setImageEditZoom((state.displayZoom || state.fitScale || 1) / IMAGE_EDIT_ZOOM_STEP, 'manual');
    });
    modal.querySelector('[data-image-edit-zoom-in]')?.addEventListener('click', () => {
      const state = getImageEditState();
      if (!state) return;
      setImageEditZoom((state.displayZoom || state.fitScale || 1) * IMAGE_EDIT_ZOOM_STEP, 'manual');
    });
    modal.querySelector('[data-image-edit-zoom-fit]')?.addEventListener('click', () => {
      setImageEditZoom(0, 'fit');
    });
    modal.querySelector('[data-image-edit-clear-mask]')?.addEventListener('click', clearImageEditorMask);
    modal.querySelector('[data-image-edit-clear-annotations]')?.addEventListener('click', clearImageEditorAnnotations);
    modal.querySelector('[data-image-edit-undo]')?.addEventListener('click', async () => {
      const state = getImageEditState();
      if (!state || state.undoStack.length <= 1) return;
      const current = state.undoStack.pop();
      if (current) state.redoStack.push(current);
      const previous = state.undoStack[state.undoStack.length - 1];
      if (!previous) return;
      state.restoring = true;
      try {
        await restoreImageEditSnapshot(previous);
        state.historyKey = imageEditSnapshotKey(previous);
        updateImageEditUndoRedoButtons();
        setImageEditStatus('已撤销', 'info');
      } finally {
        state.restoring = false;
      }
    });
    modal.querySelector('[data-image-edit-redo]')?.addEventListener('click', async () => {
      const state = getImageEditState();
      if (!state || !state.redoStack.length) return;
      const next = state.redoStack.pop();
      if (!next) return;
      state.undoStack.push(next);
      state.restoring = true;
      try {
        await restoreImageEditSnapshot(next);
        state.historyKey = imageEditSnapshotKey(next);
        updateImageEditUndoRedoButtons();
        setImageEditStatus('已重做', 'info');
      } finally {
        state.restoring = false;
      }
    });
    modal.querySelector('[data-image-edit-export-annotated]')?.addEventListener('click', () => {
      exportImageEditAnnotatedDataUrl()
        .then(dataUrl => {
          if (!dataUrl) throw new Error('没有可导出的合成图');
          const state = getImageEditState();
          downloadDataUrl(dataUrl, `${sanitizeImageEditFilename(state?.sourceName || 'annotated')}-annotated.png`);
          setImageEditStatus('合成图已导出', 'success');
        })
        .catch(error => DesktopResults.showError(error));
    });
    modal.querySelector('[data-image-edit-export-mask]')?.addEventListener('click', () => {
      exportImageEditMaskDataUrl()
        .then(dataUrl => {
          if (!dataUrl) throw new Error('没有可导出的 mask');
          const state = getImageEditState();
          downloadDataUrl(dataUrl, `${sanitizeImageEditFilename(state?.sourceName || 'mask')}-mask.png`);
          setImageEditStatus('mask 已导出', 'success');
        })
        .catch(error => DesktopResults.showError(error));
    });
    modal.querySelector('[data-image-edit-export-node]')?.addEventListener('click', () => {
      exportImageEditAnnotatedToNode()
        .catch(error => DesktopResults.showError(error));
    });
    modal.querySelector('[data-image-edit-export-json]')?.addEventListener('click', () => {
      const projectJson = buildImageEditProjectJson();
      if (!projectJson) return;
      const state = getImageEditState();
      downloadJsonObject(projectJson, `${sanitizeImageEditFilename(state?.sourceName || 'project')}-project.json`);
      setImageEditStatus('项目 JSON 已导出', 'success');
    });
    modal.querySelector('[data-image-edit-import]')?.addEventListener('click', () => {
      modal.querySelector('[data-image-edit-import-input]')?.click();
    });
    modal.querySelector('[data-image-edit-import-input]')?.addEventListener('change', event => {
      const file = Array.from(event.target.files || []).find(item => item.type.startsWith('image/'));
      event.target.value = '';
      if (!file) return;
      const state = getImageEditState();
      if (!state) return;
      fileToDataUrl(file)
        .then(async dataUrl => {
          const meta = await readImageMeta(dataUrl);
          state.sourceDataUrl = dataUrl;
          state.sourceName = file.name || state.sourceName;
          state.sourceMimeType = file.type || 'image/png';
          state.sourceWidth = meta.width || 1;
          state.sourceHeight = meta.height || 1;
          state.displayZoom = 0;
          state.fitScale = 1;
          state.zoomMode = 'fit';
          await loadImageEditSource(dataUrl, state.sourceWidth, state.sourceHeight, null);
          state.tool = 'select';
          state.projectJson = buildImageEditProjectJson();
          resetImageEditHistory(createImageEditSnapshot());
          updateImageEditToolUi();
          setImageEditTool('select');
          setImageEditStatus('已导入新背景图', 'success');
        })
        .catch(error => DesktopResults.showError(error));
    });
  }

  async function submitImageEditor() {
    const currentState = activeImageEdit;
    const node = currentState?.nodeId ? DesktopState.state.canvas.nodes[currentState.nodeId] : null;
    if (!node || node.type !== 'image') throw new Error('图片节点不存在');
    const targetOutputId = (DesktopState.state.canvas.edges || [])
      .find(edge => edge.from === node.id && DesktopState.state.canvas.nodes[edge.to]?.type === 'input')
      ?.to;
    if (!targetOutputId) throw new Error('请先把图片节点连接到模型节点，再提交编辑');
    const editState = await saveImageEditState(currentState) || {};
    const prompt = buildImageEditPrompt(editState.editPrompt, !!editState.maskData || !!editState.projectJson?.hasMask);
    if (!prompt) throw new Error('请先填写编辑说明');
    const sourceDataUrl = node.imageData || await imageUrlToDataUrl(node.imageUrl);
    const annotatedDataUrl = await exportImageEditAnnotatedDataUrl();
    const ratio = ratioFromAspect(node.aspectRatio || (node.width / Math.max(1, node.height)), DesktopState.state.params.ratio || '1:1');
    const referenceImages = [{
      id: node.sourceAssetId || `image-node:${node.id}`,
      name: node.imageName || `${node.id}.png`,
      type: node.mimeType || 'image/png',
      url: sourceDataUrl,
      base64: sourceDataUrl,
      imageData: sourceDataUrl,
      imageUrl: sourceDataUrl,
      taskId: node.sourceTaskId || '',
      assetId: node.sourceAssetId || '',
      title: node.sourceTitle || node.imageName || `${node.id}.png`,
      prompt: node.sourcePrompt || '',
      source: 'image-node-edit',
      file: node.sourceFile || '',
      sourceNodeId: node.id
    }];
    if (annotatedDataUrl) {
      referenceImages.push({
        id: `${node.id}:annotated`,
        name: `${sanitizeImageEditFilename(node.imageName || node.id)}-annotated.png`,
        type: 'image/png',
        url: annotatedDataUrl,
        base64: annotatedDataUrl,
        imageData: annotatedDataUrl,
        imageUrl: annotatedDataUrl,
        taskId: node.sourceTaskId || '',
        assetId: node.sourceAssetId || '',
        title: `${node.imageName || node.id} 标注图`,
        prompt: editState.editPrompt || '',
        source: 'image-node-annotated',
        file: `${sanitizeImageEditFilename(node.imageName || node.id)}-annotated.png`,
        sourceNodeId: node.id
      });
    }
    const config = {
      prompt,
      provider: 'gpt',
      params: {
        ...DesktopState.state.params,
        ratio,
        imageCount: 1,
        promptMode: DesktopState.state.params.promptMode || 'smart'
      },
      referenceImages,
      mask: editState.maskData || ''
    };
    closeImageEditor();
    ensureImageOutputsForConfig(targetOutputId, config);
    return DesktopResults.submitConfigToResult(config, targetOutputId);
  }

  function getImageNodeSize(meta) {
    const aspectRatio = Math.max(0.08, (meta?.width || 1) / Math.max(1, meta?.height || 1));
    const longestSide = DEFAULT_IMAGE_LONGEST_SIDE;
    let width = aspectRatio >= 1 ? longestSide : longestSide * aspectRatio;
    let height = aspectRatio >= 1 ? longestSide / aspectRatio : longestSide;
    if (width < MIN_IMAGE_NODE_WIDTH) {
      width = MIN_IMAGE_NODE_WIDTH;
      height = width / aspectRatio;
    }
    if (height > MAX_IMAGE_NODE_WIDTH) {
      height = MAX_IMAGE_NODE_WIDTH;
      width = height * aspectRatio;
    }
    return { width, height, aspectRatio };
  }

  function getImageNodeCenter(clientX, clientY) {
    if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
      return screenToWorld(clientX, clientY);
    }
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    return rect
      ? screenToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2)
      : { x: 260, y: 220 };
  }

  function triggerImageNodePopIn(nodeId, index = 0, options = {}) {
    const node = getNodeElement(nodeId);
    if (!node) return;
    const bounds = getNodeBoundsById(nodeId);
    const origin = options.popOrigin || null;
    const hasOrigin = bounds
      && Number.isFinite(Number(origin?.x))
      && Number.isFinite(Number(origin?.y));
    const dx = hasOrigin
      ? Number(origin.x) - (bounds.x + bounds.width / 2)
      : -42 - Math.min(140, Math.max(0, index) * 8);
    const dy = hasOrigin
      ? Number(origin.y) - (bounds.y + bounds.height / 2)
      : -72 - (Math.max(0, index) % 4) * 12;
    const rot = ((Math.max(0, index) % 5) - 2) * 3;
    node.style.setProperty('--desk-pop-x', `${dx}px`);
    node.style.setProperty('--desk-pop-y', `${dy}px`);
    node.style.setProperty('--desk-pop-rot', `${rot}deg`);
    node.style.setProperty('--desk-pop-delay', `${Math.min(280, Math.max(0, index) * 60)}ms`);
    node.classList.remove('is-pop-enter');
    void node.offsetWidth;
    node.classList.add('is-pop-enter');
    const cleanup = () => {
      node.classList.remove('is-pop-enter');
      node.style.removeProperty('--desk-pop-x');
      node.style.removeProperty('--desk-pop-y');
      node.style.removeProperty('--desk-pop-rot');
      node.style.removeProperty('--desk-pop-delay');
      node.removeEventListener('animationend', cleanup);
    };
    node.addEventListener('animationend', cleanup);
  }

  function insertImageNode(source, center, options = {}) {
    const size = getImageNodeSize(source.meta);
    const count = Object.keys(DesktopState.state.canvas.nodes).length;
    const id = nextNodeId('image');
    const node = {
      id,
      type: 'image',
      x: center.x - size.width / 2 + count * 14,
      y: center.y - size.height / 2 + count * 10,
      width: size.width,
      height: size.height,
      aspectRatio: size.aspectRatio,
      imageData: source.imageData || '',
      imageUrl: source.imageUrl || '',
      imageName: source.imageName || '图片节点',
      mimeType: source.mimeType || 'image/png',
      sourceTaskId: source.taskId || '',
      sourceAssetId: source.assetId || source.asset_id || '',
      sourcePrompt: source.prompt || '',
      sourceTitle: source.title || source.imageName || '',
      sourceFile: source.file || '',
      sourceProvider: source.provider || '',
      sourceKind: source.source || ''
    };
    DesktopState.state.canvas.nodes[id] = node;
    ensureGraphDom();
    applyNodeLayout(id);
    selectNode(id);
    triggerImageNodePopIn(id, options.popIndex || 0, options);
    updateLinkPath();
    DesktopState.saveSettings();
    return id;
  }

  async function createImageNodeFromFiles(files, center = null) {
    const file = Array.from(files || []).find(item => item.type.startsWith('image/'));
    if (!file) return '';
    const imageData = await fileToDataUrl(file);
    const meta = await readImageMeta(imageData);
    return insertImageNode({
      imageData,
      imageName: file.name,
      mimeType: file.type || 'image/png',
      meta
    }, center || getImageNodeCenter());
  }

  async function replaceImageNodeFromFiles(nodeId, files) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const file = Array.from(files || []).find(item => item.type.startsWith('image/'));
    if (!node || node.type !== 'image' || !file) return '';
    const imageData = await fileToDataUrl(file);
    const meta = await readImageMeta(imageData);
    node.imageData = imageData;
    node.imageUrl = '';
    node.imageName = file.name || '图片节点';
    node.mimeType = file.type || 'image/png';
    node.aspectRatio = Math.max(0.08, (meta.width || 1) / Math.max(1, meta.height || 1));
    if (!node.width || !node.height) {
      const size = getImageNodeSize(meta);
      node.width = size.width;
      node.height = size.height;
    } else {
      node.height = node.width / node.aspectRatio;
    }
    node.sourceKind = 'upload';
    node.sourceTaskId = '';
    node.sourceAssetId = '';
    node.sourcePrompt = '';
    node.sourceTitle = file.name || '';
    node.sourceFile = file.name || '';
    node.sourceProvider = '';
    node.editState = {};
    refreshImageNodeContent(nodeId);
    DesktopState.saveSettings();
    return nodeId;
  }

  async function setImageNodeFromResult(nodeId, resultNodeId, output, index = 0) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'image' || !output?.imagePaths?.length) return false;
    const safeIndex = Math.max(0, Number(index) || 0);
    const imageUrl = output.imagePaths[safeIndex] || output.imagePaths[0];
    const primaryFile = output.files?.[safeIndex] || output.primaryFile || imageUrl.split('/').pop() || '';
    node.imageData = '';
    node.imageUrl = imageUrl;
    node.imageName = primaryFile || '生成结果';
    node.mimeType = 'image/png';
    node.sourceKind = 'result-node';
    node.sourceTaskId = output.taskId || '';
    node.sourceAssetId = '';
    node.sourcePrompt = output.prompt || '';
    node.sourceTitle = primaryFile || '生成结果';
    node.sourceFile = primaryFile || '';
    node.sourceProvider = output.type || '';
    node.editState = {};
    try {
      const meta = await readImageMeta(imageUrl);
      node.aspectRatio = Math.max(0.08, (meta.width || 1) / Math.max(1, meta.height || 1));
      if (!node.width || !node.height) {
        const size = getImageNodeSize(meta);
        node.width = size.width;
        node.height = size.height;
      } else {
        node.height = node.width / node.aspectRatio;
      }
    } catch (e) {}
    refreshImageNodeContent(nodeId);
    updateLinkPath();
    DesktopState.saveSettings();
    return true;
  }

  async function createImageNodeFromResult(resultNodeId = 'output', index = 0) {
    const output = DesktopState.state.outputs?.[resultNodeId] || (resultNodeId === 'output' ? DesktopState.state.output : null);
    const safeIndex = Math.max(0, Number(index) || 0);
    const imageUrl = output?.imagePaths?.[safeIndex] || output?.primaryImagePath || output?.imagePaths?.[0] || '';
    if (!imageUrl) throw new Error('结果节点没有可回流的图片');
    const meta = await readImageMeta(imageUrl);
    const sourceBounds = getNodeBoundsById(resultNodeId);
    const center = sourceBounds
      ? {
          x: sourceBounds.x + sourceBounds.width + 210,
          y: sourceBounds.y + Math.min(sourceBounds.height * 0.5, 280)
        }
      : getViewportCenterWorldPoint(360, 0);
    const file = output?.files?.[safeIndex] || output?.primaryFile || imageUrl.split('/').pop() || '';
    const nodeId = insertImageNode({
      imageUrl,
      imageName: file || '生成结果',
      mimeType: 'image/png',
      taskId: output?.taskId || '',
      prompt: output?.prompt || '',
      title: file || '生成结果',
      file,
      provider: output?.type || '',
      source: 'result-node',
      meta
    }, center);
    DesktopResults.showTransientMessage('结果图已回流到画布。');
    return nodeId;
  }

  async function createImageNodeFromHistoryItem(item, clientX, clientY) {
    const imageUrl = String(item?.imageUrl || item?.imagePath || '').trim();
    if (!imageUrl) throw new Error('这条历史记录没有可拖入画布的图片');
    let imageData = '';
    try {
      imageData = await imageUrlToDataUrl(imageUrl);
    } catch (error) {
      imageData = '';
      DesktopResults.showTransientMessage('已创建图片节点；该历史图暂不能作为参考图提交。');
    }
    const displayUrl = imageData || imageUrl;
    const meta = await readImageMeta(displayUrl);
    return insertImageNode({
      imageData,
      imageUrl,
      imageName: item?.title || item?.prompt || item?.taskId || '历史图片',
      mimeType: imageData.startsWith('data:') ? imageData.slice(5, imageData.indexOf(';')) : 'image/png',
      taskId: item?.taskId || '',
      assetId: item?.assetId || item?.asset_id || item?.id || '',
      prompt: item?.prompt || '',
      title: item?.title || '',
      file: item?.file || '',
      provider: item?.provider || '',
      source: item?.source || 'gallery',
      meta
    }, getImageNodeCenter(clientX, clientY));
  }

  async function continueEditFromHistoryItem(item, clientX, clientY) {
    const imageNodeId = await createImageNodeFromHistoryItem(item, clientX, clientY);
    const inputNodeId = findDefaultInputNodeId();
    connectNodes(imageNodeId, inputNodeId);
    await openImageEditor(imageNodeId);
    DesktopResults.showTransientMessage('已创建继续编辑流程。');
    return { imageNodeId, inputNodeId };
  }

  async function attachHistoryImageToLayout(item, layoutNodeId) {
    const layoutNode = DesktopState.state.canvas.nodes[layoutNodeId];
    if (!layoutNode || layoutNode.type !== 'layout') throw new Error('排版节点不存在');
    const imageUrl = String(item?.imageUrl || item?.imagePath || '').trim();
    if (!imageUrl) throw new Error('这条历史记录没有可接入排版的图片');
    const sourceId = `history:${item?.taskId || imageUrl}`;
    layoutNode.layoutInputImages = Array.isArray(layoutNode.layoutInputImages) ? layoutNode.layoutInputImages : [];
    const exists = layoutNode.layoutInputImages.some(image => image.id === sourceId || image.imageUrl === imageUrl);
    if (!exists) {
      layoutNode.layoutInputImages.push({
        id: sourceId,
        assetId: item?.assetId || item?.asset_id || item?.id || '',
        taskId: item?.taskId || '',
        name: item?.title || item?.prompt || '历史图片',
        type: 'image/png',
        imageUrl,
        imageData: '',
        prompt: item?.prompt || '',
        source: item?.source || 'gallery'
      });
    }
    selectNode(layoutNodeId);
    updateLayoutInputCount(layoutNodeId);
    DesktopState.saveSettings();
    DesktopResults.showTransientMessage(exists ? '这张图片已在排版节点中。' : '历史图片已接入排版节点。');
  }

  async function addFiles(files) {
    const nextFiles = Array.from(files || []).filter(file => file.type.startsWith('image/'));
    if (!nextFiles.length) return;
    const remaining = Math.max(0, 8 - DesktopState.state.referenceImages.length);
    const selected = nextFiles.slice(0, remaining);
    const images = await Promise.all(selected.map(async file => ({
      id: `upload:${file.name}:${file.size}:${file.lastModified || Date.now()}`,
      name: file.name,
      type: file.type,
      url: URL.createObjectURL(file),
      base64: await fileToDataUrl(file),
      imageData: '',
      imageUrl: '',
      source: 'upload'
    })));
    DesktopState.state.referenceImages.push(...images);
    renderReferenceThumbs();
    DesktopState.saveSettings();
  }

  function getNodeReferenceImages(nodeId) {
    if (nodeId === 'input') return DesktopState.state.referenceImages;
    const store = getNodeReferenceStore();
    if (!store[nodeId]) store[nodeId] = [];
    return store[nodeId];
  }

  function findDefaultInputNodeId() {
    const selectedNodeId = DesktopState.state.canvas.selectedNodeId;
    if (DesktopState.state.canvas.nodes[selectedNodeId]?.type === 'input') return selectedNodeId;
    if (DesktopState.state.canvas.nodes.input?.type === 'input') return 'input';
    const input = Object.values(DesktopState.state.canvas.nodes || {}).find(node => node.type === 'input');
    return input?.id || addNode('input', getViewportCenterWorldPoint(-260, 0));
  }

  function referenceFromHistoryItem(item) {
    const imageUrl = String(item?.imageUrl || item?.imagePath || item?.url || item?.base64 || '').trim();
    if (!imageUrl) return null;
    return {
      id: item?.id || `asset:${item?.taskId || imageUrl}`,
      name: item?.title || item?.file || item?.prompt || '图库参考图',
      type: item?.mimeType || 'image/png',
      url: imageUrl,
      base64: String(imageUrl).startsWith('data:') ? imageUrl : '',
      imageUrl,
      imageData: String(imageUrl).startsWith('data:') ? imageUrl : '',
      taskId: item?.taskId || '',
      assetId: item?.assetId || item?.asset_id || item?.id || '',
      title: item?.title || item?.name || '图库参考图',
      prompt: item?.prompt || '',
      source: item?.source || (item?.assetId || item?.asset_id || item?.id ? 'gallery' : 'history'),
      file: item?.file || ''
    };
  }

  function addReferenceItemsToNode(nodeId, items) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'input') throw new Error('模型节点不存在');
    const refs = getNodeReferenceImages(nodeId);
    const payloads = (Array.isArray(items) ? items : [items]).map(referenceFromHistoryItem).filter(Boolean);
    if (!payloads.length) {
      DesktopResults.showTransientMessage('没有可接入模型节点的图片。');
      return 0;
    }

    let added = 0;
    const seen = new Set(refs.map(referenceKey).filter(Boolean));
    for (const item of payloads) {
      if (refs.length >= 8) break;
      const key = referenceKey(item);
      if (key && seen.has(key)) continue;
      refs.push(item);
      if (key) seen.add(key);
      added += 1;
    }
    renderNodeReferenceThumbs(nodeId);
    selectNode(nodeId);
    DesktopState.saveSettings();
    return added;
  }

  async function attachHistoryImagesToInput(items, inputNodeId = '') {
    const targetInputId = inputNodeId || findDefaultInputNodeId();
    const added = addReferenceItemsToNode(targetInputId, items);
    const refs = getNodeReferenceImages(targetInputId);
    if (!added) {
      DesktopResults.showTransientMessage(refs.length >= 8 ? '模型节点参考图已满，最多 8 张。' : '这些图片已在模型节点参考图里。');
      return targetInputId;
    }
    DesktopResults.showTransientMessage(added > 1 ? `${added} 张图片已接入模型节点参考图。` : '图片已接入模型节点参考图。');
    return targetInputId;
  }

  function providerFromAsset(asset, fallback = 'gpt') {
    const raw = String(asset?.provider || asset?.type || '').toLowerCase();
    if (raw.includes('gpt')) return 'gpt';
    if (raw.includes('google') || raw.includes('gemini')) return 'google';
    if (raw.includes('comfy')) return 'comfy';
    return fallback;
  }

  function firstParam(asset, keys) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    for (const key of keys) {
      const value = params[key] ?? asset?.[key];
      if (value !== undefined && value !== null && String(value).trim()) return value;
    }
    return '';
  }

  function extractAssetModelConfig(asset, fallbackParams = DesktopState.state.params) {
    const provider = providerFromAsset(asset, DesktopState.state.provider || 'gpt');
    const rawQuality = firstParam(asset, ['quality']);
    const resolution = firstParam(asset, ['resolution', 'image_size', 'imageSize', 'size'])
      || (['1k', '2k', '4k'].includes(String(rawQuality || '').toLowerCase()) ? rawQuality : '');
    const routeFromAsset = DesktopState.normalizeGptProviderRoute(firstParam(asset, ['gpt_provider_route', 'gptProviderRoute', 'provider_route', 'providerRoute']), fallbackParams.gptProviderRoute || 'codex');
    const legacyThirdParty = DesktopState.normalizeBoolean(firstParam(asset, ['use_third_party_api', 'useThirdPartyApi', 'third_party_api', 'thirdPartyApi']), fallbackParams.useThirdPartyApi || false);
    const gptProviderRoute = legacyThirdParty && routeFromAsset === 'codex' ? 'third_party_image_api' : routeFromAsset;
    return {
      prompt: String(asset?.prompt || '').trim(),
      provider,
      params: {
        ratio: DesktopState.normalizeRatio(firstParam(asset, ['ratio', 'aspect_ratio', 'aspectRatio']), fallbackParams.ratio || '9:16'),
        resolution: DesktopState.normalizeResolution(resolution, fallbackParams.resolution || '2k'),
        quality: DesktopState.normalizeGptQuality(rawQuality, fallbackParams.quality || 'auto'),
        imageCount: DesktopState.clamp(firstParam(asset, ['image_count', 'imageCount', 'count', 'n']) || asset?.total || fallbackParams.imageCount || 1, 1, 8, DesktopState.clamp(fallbackParams.imageCount || 1, 1, 8, 1)),
        moderation: DesktopState.normalizeModeration(firstParam(asset, ['moderation']), fallbackParams.moderation || 'auto'),
        promptMode: DesktopState.normalizePromptMode(firstParam(asset, ['prompt_mode', 'promptMode']), fallbackParams.promptMode || 'smart'),
        gptTaskType: DesktopState.normalizeGptTaskType(firstParam(asset, ['task_type', 'taskType', 'gpt_task_type', 'gptTaskType']), fallbackParams.gptTaskType || 'image'),
        gptProviderRoute,
        useThirdPartyApi: gptProviderRoute === 'third_party_image_api',
        gptMainModel: DesktopState.normalizeGptMainModel(firstParam(asset, ['main_model', 'mainModel']), fallbackParams.gptMainModel || 'gpt-5.5'),
        reasoningEffort: DesktopState.normalizeReasoningEffort(firstParam(asset, ['reasoning_effort', 'reasoningEffort']), fallbackParams.reasoningEffort || 'medium'),
        model: firstParam(asset, ['model', 'modelAlias']) || fallbackParams.model || ''
      }
    };
  }

  function shouldOverwritePrompt(currentPrompt, nextPrompt) {
    const current = String(currentPrompt || '').trim();
    const next = String(nextPrompt || '').trim();
    if (!next) return false;
    if (!current || current === next) return true;
    return window.confirm('模型节点已有提示词，是否用这张图的提示词覆盖？');
  }

  function applyProviderToNode(node, provider) {
    node.querySelectorAll('.desk-segment button[data-provider]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.provider === provider);
    });
  }

  function applyAssetConfigToInput(asset, options = {}) {
    if (!asset) {
      DesktopResults.showTransientMessage('没有可套用的图片参数。');
      return '';
    }
    const mode = options.mode || 'all';
    const targetInputId = options.inputNodeId || findDefaultInputNodeId();
    const node = getNodeElement(targetInputId);
    const nodeState = DesktopState.state.canvas.nodes[targetInputId];
    if (!node || nodeState?.type !== 'input') throw new Error('模型节点不存在');

    const applyPrompt = mode === 'all' || mode === 'prompt';
    const applyParams = mode === 'all' || mode === 'params';
    const config = extractAssetModelConfig(asset, targetInputId === 'input' ? DesktopState.state.params : {});
    const currentPrompt = getVisibleInputPrompt(targetInputId);

    if (applyPrompt && config.prompt && shouldOverwritePrompt(currentPrompt, config.prompt)) {
      setPromptTextForInputNode(targetInputId, config.prompt);
      if (targetInputId === 'input') DesktopState.state.prompt = '';
    }

    if (applyParams) {
      if (targetInputId === 'input') {
        DesktopState.state.provider = config.provider;
        DesktopState.state.params = {
          ...DesktopState.state.params,
          ...config.params
        };
        syncFormFromState();
      } else {
        applyProviderToNode(node, config.provider);
        const fieldValues = {
          ratio: config.params.ratio,
          resolution: config.params.resolution,
          quality: config.params.quality,
          imageCount: config.params.imageCount,
          moderation: config.params.moderation,
          gptTaskType: config.params.gptTaskType,
          gptProviderRoute: config.params.gptProviderRoute,
          gptMainModel: config.params.gptMainModel,
          reasoningEffort: config.params.reasoningEffort,
          promptMode: config.params.promptMode
        };
        Object.entries(fieldValues).forEach(([field, value]) => {
          const input = node.querySelector(`[data-field="${field}"]`);
          if (!input) return;
          if (input.type === 'checkbox') {
            input.checked = !!value;
          } else {
            input.value = value;
          }
        });
        applyPromptModeToNode(node, config.params.promptMode);
        applyGptTaskTypeToNode(node, config.params.gptTaskType);
      }
    } else if (targetInputId === 'input') {
      DesktopState.saveDraft();
    }

    selectNode(targetInputId);
    DesktopResults.renderIdleProviderHint?.();
    DesktopState.saveSettings();
    DesktopState.saveDraft();
    DesktopResults.showTransientMessage(mode === 'prompt' ? '提示词已套用到模型节点。' : (mode === 'params' ? '参数已套用到模型节点。' : '提示词和参数已套用到模型节点。'));
    return targetInputId;
  }

  function getThumbWrapForNode(nodeId) {
    if (nodeId === 'input') return els.deskReferenceThumbs;
    return getNodeElement(nodeId)?.querySelector('[data-reference-thumbs]');
  }

  function renderNodeReferenceThumbs(nodeId) {
    const wrap = getThumbWrapForNode(nodeId);
    if (!wrap) return;
    const refs = getNodeReferenceImages(nodeId);
    wrap.innerHTML = '';
    refs.forEach((image, index) => {
      wrap.appendChild(renderReferenceItem(nodeId, image, index, refs.length));
    });
    if (refs.length) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'desk-thumb-clear';
      clear.title = '清空参考图槽';
      clear.setAttribute('aria-label', '清空参考图槽');
      clear.textContent = '清空';
      clear.addEventListener('pointerdown', event => event.stopPropagation());
      clear.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        clearNodeReferences(nodeId);
      });
      wrap.appendChild(clear);
    }
  }

  async function addFilesToNode(nodeId, files) {
    const nextFiles = Array.from(files || []).filter(file => file.type.startsWith('image/'));
    if (!nextFiles.length) return;
    const refs = getNodeReferenceImages(nodeId);
    const remaining = Math.max(0, 8 - refs.length);
    if (!remaining) {
      DesktopResults.showTransientMessage('最多支持 8 张参考图。');
      return;
    }
    const selected = nextFiles.slice(0, remaining);
    const images = await Promise.all(selected.map(async file => ({
      id: `upload:${file.name}:${file.size}:${file.lastModified || Date.now()}`,
      name: file.name,
      type: file.type,
      url: URL.createObjectURL(file),
      base64: await fileToDataUrl(file),
      imageData: '',
      imageUrl: '',
      source: 'upload'
    })));
    refs.push(...images);
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
  }

  function clearDraft() {
    DesktopState.state.prompt = '';
    DesktopState.state.referenceImages.forEach(revokeReferenceUrl);
    DesktopState.state.referenceImages = [];
    renderReferenceThumbs();
    DesktopState.saveSettings();
    DesktopState.saveDraft();
  }

  function hasHistoryDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('application/x-desktop-history-image');
  }

  function hasGalleryDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('application/x-desktop-gallery-images');
  }

  function getHistoryDragPayload(dataTransfer) {
    if (!hasHistoryDragPayload(dataTransfer)) return null;
    try {
      return JSON.parse(dataTransfer.getData('application/x-desktop-history-image') || '{}');
    } catch (e) {
      return null;
    }
  }

  function getGalleryDragPayload(dataTransfer) {
    if (!hasGalleryDragPayload(dataTransfer)) return [];
    try {
      const parsed = JSON.parse(dataTransfer.getData('application/x-desktop-gallery-images') || '[]');
      return Array.isArray(parsed) ? parsed.filter(item => item?.imageUrl || item?.imagePath) : [];
    } catch (e) {
      return [];
    }
  }

  function findDefaultLayoutNodeId() {
    const selectedNodeId = DesktopState.state.canvas.selectedNodeId;
    if (DesktopState.state.canvas.nodes[selectedNodeId]?.type === 'layout') return selectedNodeId;
    const layout = Object.values(DesktopState.state.canvas.nodes || {}).find(node => node.type === 'layout');
    if (layout) return layout.id;
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    const center = rect
      ? screenToWorld(rect.left + rect.width / 2 + 130, rect.top + rect.height / 2)
      : { x: 520, y: 280 };
    return addNode('layout', center);
  }

  async function attachHistoryImagesToLayout(items, layoutNodeId = '') {
    const payloads = (Array.isArray(items) ? items : [items]).filter(item => item?.imageUrl || item?.imagePath);
    if (!payloads.length) {
      DesktopResults.showTransientMessage('没有可接入排版的图片。');
      return '';
    }
    const targetLayoutId = layoutNodeId || findDefaultLayoutNodeId();
    for (const item of payloads) {
      await attachHistoryImageToLayout(item, targetLayoutId);
    }
    selectNode(targetLayoutId);
    updateLayoutInputCount(targetLayoutId);
    DesktopLayoutEditor?.syncConnectedImages?.(targetLayoutId).catch(() => {});
    DesktopResults.showTransientMessage(payloads.length > 1 ? `${payloads.length} 张图片已接入排版节点。` : '图片已接入排版节点。');
    return targetLayoutId;
  }

  async function createImageNodesFromHistoryItems(items, clientX, clientY) {
    const payloads = (Array.isArray(items) ? items : [items]).filter(item => item?.imageUrl || item?.imagePath);
    let created = 0;
    for (let index = 0; index < payloads.length; index += 1) {
      const x = Number.isFinite(clientX) ? clientX + index * 28 : undefined;
      const y = Number.isFinite(clientY) ? clientY + index * 24 : undefined;
      await createImageNodeFromHistoryItem(payloads[index], x, y);
      created += 1;
    }
    return created;
  }

  function hasAddNodeDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('application/x-desktop-add-node');
  }

  function getAddNodeDragPayload(dataTransfer) {
    if (!hasAddNodeDragPayload(dataTransfer)) return null;
    try {
      return JSON.parse(dataTransfer.getData('application/x-desktop-add-node') || '{}');
    } catch (e) {
      return null;
    }
  }

  function setWorkflowDockOpen(open) {
    const next = !!open;
    els.deskWorkflowDockPanel?.classList.toggle('is-open', next);
    els.deskWorkflowDockPanel?.setAttribute('aria-hidden', next ? 'false' : 'true');
    els.deskWorkflowDockToggle?.setAttribute('aria-expanded', next ? 'true' : 'false');
  }

  function toggleWorkflowDock() {
    setWorkflowDockOpen(els.deskWorkflowDockToggle?.getAttribute('aria-expanded') !== 'true');
  }

  function isWorkflowDockEventTarget(target) {
    return !!target?.closest?.('.desk-workflow-dock-toggle, .desk-workflow-dock-panel');
  }

  function bindEvents() {
    document.querySelectorAll('.desk-rail__item[data-tool]').forEach(button => {
      button.addEventListener('click', () => {
        document.querySelectorAll('.desk-rail__item[data-tool]').forEach(item => item.classList.toggle('is-active', item === button));
        const tool = button.dataset.tool;
        updateCanvasToolCursor(tool === 'select');
        if (tool === 'select') {
          setNodePaletteOpen(false);
          selectNode('');
          return;
        }
        if (tool === 'node') {
          setNodePaletteOpen(!els.deskNodePalette?.classList.contains('is-open'));
          return;
        }
        if (tool === 'gallery') {
          setNodePaletteOpen(false);
          window.DesktopHistory?.openGallery?.().catch(error => DesktopResults.showError(error));
          return;
        }
        if (tool === 'settings') {
          setNodePaletteOpen(false);
          window.openDesktopSettingsPanel?.();
        }
      });
    });

    els.deskNodePalette?.addEventListener('click', event => {
      const button = event.target.closest('[data-add-node]');
      if (!button) return;
      addNodeFromMenu(button.dataset.addNode || 'input', getViewportCenterWorldPoint());
      setNodePaletteOpen(false);
    });
    els.deskNodePalette?.querySelectorAll('[data-add-node]').forEach(button => {
      button.draggable = true;
    });
    els.deskNodePalette?.addEventListener('dragstart', event => {
      const button = event.target.closest('[data-add-node]');
      if (!button) return;
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData('application/x-desktop-add-node', JSON.stringify({
        type: button.dataset.addNode || 'input'
      }));
    });

    document.addEventListener('pointerdown', event => {
      if (event.target.closest('#deskNodePalette, #deskNodeContextMenu, #deskNodeToolBtn')) return;
      setNodePaletteOpen(false);
      hideContextMenu();
      if (!event.target.closest('.desk-node--text, #deskPromptDrawer')) {
        const selectedIds = getSelectedNodeIds();
        const pointerNodeId = getCanvasNodeIdForElement(event.target);
        const pointerInsideSelection = pointerNodeId && selectedIds.includes(pointerNodeId);
        const selectedTextNode = selectedIds
          .map(nodeId => DesktopState.state.canvas.nodes[nodeId])
          .some(node => node?.type === 'text');
        if (selectedTextNode && !pointerInsideSelection) selectNode('');
      }
    });

    els.deskCanvasWorld?.addEventListener('click', event => {
      const aliasEditButton = event.target.closest('[data-text-node-alias-edit]');
      if (aliasEditButton) {
        const shell = aliasEditButton.closest('.desk-text-node__alias');
        const node = aliasEditButton.closest('.desk-node--text[data-node-id]');
        const aliasInput = shell?.querySelector('[data-text-node-alias]');
        if (!shell || !node || !aliasInput) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        if (aliasEditButton.dataset.aliasMode === 'apply') {
          commitTextNodeAliasInput(aliasInput);
          setTextNodeAliasEditing(shell, false);
        } else {
          setTextNodeAliasEditing(shell, true);
        }
        return;
      }

      const stylePresetButton = event.target.closest('[data-text-style-preset]');
      if (stylePresetButton) {
        const node = stylePresetButton.closest('.desk-node--text[data-node-id]');
        const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
        if (!node || !nodeState) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        selectTextNodePreset(node, nodeState, stylePresetButton.dataset.textStylePreset || '');
        return;
      }

      const styleClearButton = event.target.closest('[data-text-style-clear]');
      if (styleClearButton) {
        const node = styleClearButton.closest('.desk-node--text[data-node-id]');
        const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
        if (!node || !nodeState) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        clearTextNodeStyle(node, nodeState);
        return;
      }

      const textAction = event.target.closest('[data-text-action]');
      if (textAction) {
        const node = textAction.closest('.desk-node--text[data-node-id]');
        const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
        if (!node || !nodeState) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        if (textAction.dataset.textAction === 'preset') {
          const nextOpen = !node.classList.contains('is-style-menu-open');
          closeAllTextStyleMenus(node);
          setTextStyleMenuOpen(node, nextOpen);
          return;
        }
        if (textAction.dataset.textAction === 'clear') {
          setTextNodeValue(node, nodeState, '');
          clearTextNodeStyle(node, nodeState);
          setTextStyleMenuOpen(node, false);
          DesktopResults.showTransientMessage('文本节点已清空。');
          return;
        }
        setTextStyleMenuOpen(node, false);
        if (textAction.dataset.textAction === 'gpt-polish') {
          runTextNodeGptPolish(node, nodeState, textAction).catch(error => DesktopResults.showError(error));
          return;
        }
        if (textAction.dataset.textAction === 'safe-rewrite') {
          if (window.DesktopPromptDrawer?.generateSafeRewriteForTextNode) {
            window.DesktopPromptDrawer.generateSafeRewriteForTextNode(node.dataset.nodeId);
          } else {
            DesktopResults.showTransientMessage('提示词助手尚未加载，无法生成安全审核版。', 'warning');
          }
          return;
        }
        const label = textAction.textContent.trim();
        DesktopResults.showTransientMessage(`${label} 会在文本节点工作流中接入。`);
        return;
      }

      const poseOpenButton = event.target.closest('[data-pose-open]');
      if (poseOpenButton) {
        const node = poseOpenButton.closest('.desk-node--pose[data-node-id]');
        if (!node) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        const nodeState = DesktopState.state.canvas.nodes[node.dataset.nodeId];
        if (!window.DesktopPoseStudio?.open || !nodeState) {
          DesktopResults.showTransientMessage('Pose Studio Lite 正在加载，请稍后再试。');
          return;
        }
        if (nodeState.mode === 'director_stage' && nodeState.poseTitle === '3D 导演台') {
          nodeState.poseTitle = '姿态参考';
        }
        window.DesktopPoseStudio.open({
          nodeId: node.dataset.nodeId,
          node: nodeState,
          backgroundImages: getPoseInputImages(node.dataset.nodeId),
          onUpdate: patch => {
            if (!patch || typeof patch !== 'object') return;
            if (patch.backgroundImage !== undefined) nodeState.backgroundImage = patch.backgroundImage || '';
            if (patch.backgroundName !== undefined) nodeState.backgroundName = patch.backgroundName || '';
            if (patch.backgroundSource !== undefined) nodeState.backgroundSource = patch.backgroundSource || '';
            if (patch.backgroundSourceNodeId !== undefined) nodeState.backgroundSourceNodeId = patch.backgroundSourceNodeId || '';
            if (patch.backgroundMeta !== undefined) nodeState.backgroundMeta = patch.backgroundMeta || null;
            if (patch.mode !== undefined) nodeState.mode = patch.mode || nodeState.mode || 'director_stage';
            if (patch.poseTitle !== undefined) nodeState.poseTitle = patch.poseTitle || nodeState.poseTitle || '姿态参考';
            if (patch.directorData !== undefined) nodeState.directorData = patch.directorData || {};
            if (patch.poseData !== undefined) nodeState.poseData = patch.poseData || {};
            if (patch.humanConfig !== undefined) nodeState.humanConfig = patch.humanConfig || {};
            refreshPoseNode(node.dataset.nodeId);
            DesktopState.saveSettings();
          },
          onExport: result => {
            const resultMode = result.mode || nodeState.mode || 'director_stage';
            const isDirectorStage = resultMode === 'director_stage';
            nodeState.mode = resultMode;
            nodeState.poseTitle = result.poseTitle || nodeState.poseTitle || (isDirectorStage ? '姿态参考' : '姿态编辑器');
            nodeState.poseData = result.poseData || {};
            if (isDirectorStage) {
              nodeState.directorData = result.directorData || nodeState.directorData || {};
            } else {
              delete nodeState.directorData;
            }
            nodeState.previewImage = result.imageData || '';
            nodeState.exportImage = result.imageData || '';
            nodeState.exportMode = result.exportMode || (isDirectorStage ? 'mannequin_only' : 'pose_reference');
            nodeState.backgroundImage = result.backgroundImage || nodeState.backgroundImage || '';
            nodeState.backgroundName = result.backgroundName || nodeState.backgroundName || '';
            nodeState.backgroundSource = result.backgroundSource || nodeState.backgroundSource || '';
            nodeState.backgroundSourceNodeId = result.backgroundSourceNodeId || nodeState.backgroundSourceNodeId || '';
            nodeState.backgroundMeta = result.backgroundMeta || nodeState.backgroundMeta || null;
            nodeState.camera = result.camera || {};
            nodeState.lights = result.lights || [];
            nodeState.humanConfig = result.poseData?.humanConfig || nodeState.humanConfig || {};
            nodeState.status = 'exported';
            nodeState.error = '';
            refreshPoseNode(node.dataset.nodeId);
            DesktopState.saveSettings();
            DesktopResults.showTransientMessage('姿态参考图已导出到节点。');
          }
        });
        return;
      }

      const poseConnectButton = event.target.closest('[data-pose-connect-input]');
      if (poseConnectButton) {
        const node = poseConnectButton.closest('.desk-node--pose[data-node-id]');
        if (!node) return;
        event.preventDefault();
        event.stopPropagation();
        connectPoseToDefaultInput(node.dataset.nodeId);
        return;
      }

      const deleteButton = event.target.closest('[data-node-delete]');
      if (deleteButton) {
        const node = deleteButton.closest('.desk-node[data-node-id]');
        event.preventDefault();
        event.stopPropagation();
        deleteButton.blur?.();
        removeNode(node?.dataset.nodeId, { clearSelection: true, focusCanvas: true });
        return;
      }

      const imageEditButton = event.target.closest('[data-image-edit]');
      if (imageEditButton) {
        const node = imageEditButton.closest('.desk-node--image[data-node-id]');
        if (!node) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        openImageEditor(node.dataset.nodeId).catch(error => DesktopResults.showError(error));
        return;
      }

      const imageViewButton = event.target.closest('[data-image-view-mask], [data-image-view-prompt]');
      if (imageViewButton) {
        const node = imageViewButton.closest('.desk-node--image[data-node-id]');
        if (!node) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(node.dataset.nodeId);
        openImageEditor(node.dataset.nodeId).catch(error => DesktopResults.showError(error));
        return;
      }

      const imageUploadButton = event.target.closest('[data-image-upload]');
      if (imageUploadButton) {
        const node = imageUploadButton.closest('.desk-node--image[data-node-id]');
        if (!node) return;
        event.preventDefault();
        event.stopPropagation();
        pendingFileMode = 'image-node-replace';
        pendingImageTargetNodeId = node.dataset.nodeId;
        selectNode(node.dataset.nodeId);
        els.deskFileInput?.click();
        return;
      }

      const uploadButton = event.target.closest('[data-upload-drop], #deskUploadDrop');
      if (uploadButton) {
        const node = uploadButton.closest('.desk-node[data-node-id]');
        pendingUploadNodeId = node?.dataset.nodeId || 'input';
        pendingFileMode = 'reference';
        selectNode(pendingUploadNodeId);
        els.deskFileInput?.click();
        return;
      }

      const runButton = event.target.closest('[data-result-run]');
      if (runButton) {
        const node = runButton.closest('.desk-node[data-node-id]');
        if (node) selectNode(node.dataset.nodeId);
        if (node) DesktopResults.submitFromResultNode(node.dataset.nodeId).catch(error => DesktopResults.showError(error, node.dataset.nodeId));
        return;
      }

      const layoutOpenButton = event.target.closest('[data-layout-open], [data-layout-quick-export]');
      if (layoutOpenButton) {
        const layoutNode = layoutOpenButton.closest('.desk-node[data-node-id]');
        if (layoutNode) {
          selectNode(layoutNode.dataset.nodeId);
          window.DesktopLayoutEditor?.open?.(layoutNode.dataset.nodeId, {
            exportOnOpen: layoutOpenButton.hasAttribute('data-layout-quick-export')
          });
        }
        return;
      }

      const toggleButton = event.target.closest('[data-toggle-node]');
      if (toggleButton) {
        const node = toggleButton.closest('.desk-node[data-node-id]');
        if (node) toggleNodeDrawer(node);
        return;
      }

      const providerButton = event.target.closest('.desk-segment button[data-provider]');
      const node = event.target.closest('.desk-node[data-node-id]');
      if (node) selectNode(node.dataset.nodeId);
      if (!event.target.closest('.desk-node--text')) closeAllTextStyleMenus();
      const promptModeButton = event.target.closest('.desk-prompt-mode button[data-prompt-mode]');
      if (promptModeButton) {
        const modeWrap = promptModeButton.closest('.desk-prompt-mode');
        modeWrap?.querySelectorAll('button[data-prompt-mode]').forEach(item => item.classList.toggle('is-active', item === promptModeButton));
        if (node?.dataset.nodeId === 'input') {
          DesktopState.state.params.promptMode = DesktopState.normalizePromptMode(promptModeButton.dataset.promptMode, 'smart');
          applyPromptModeToNode(node, DesktopState.state.params.promptMode);
          DesktopState.saveSettings();
        }
        return;
      }
      if (!providerButton) return;
      const segment = providerButton.closest('.desk-segment');
      segment?.querySelectorAll('button[data-provider]').forEach(item => item.classList.toggle('is-active', item === providerButton));
      updateProviderParamVisibility(node, providerButton.dataset.provider);
      if (node?.dataset.nodeId === 'input') {
        DesktopState.state.provider = providerButton.dataset.provider;
        DesktopResults.renderIdleProviderHint();
        DesktopState.saveSettings();
      } else if (node?.classList.contains('desk-node--input')) {
        syncInputNodeStateFromDom(node);
        DesktopState.saveSettings();
      }
    });

    els.deskCanvasWorld?.addEventListener('input', event => {
      const taskTypeSelect = event.target.closest('select[data-field="gptTaskType"]');
      if (taskTypeSelect) {
        const inputNode = taskTypeSelect.closest('.desk-node--input[data-node-id]');
        applyGptTaskTypeToNode(inputNode, taskTypeSelect.value);
        syncInputNodeStateFromDom(inputNode);
        DesktopState.saveSettings();
        return;
      }
      const routeSelect = event.target.closest('select[data-field="gptProviderRoute"]');
      if (routeSelect) {
        const routeNode = routeSelect.closest('.desk-node--input[data-node-id]');
        applyGptModelRouteToNode(routeNode, routeSelect.value);
        if (routeNode?.dataset.nodeId === 'input') {
          DesktopState.state.params.gptProviderRoute = DesktopState.normalizeGptProviderRoute(routeSelect.value, 'codex');
          DesktopState.state.params.useThirdPartyApi = DesktopState.state.params.gptProviderRoute === 'third_party_image_api';
          DesktopState.saveSettings();
          DesktopState.saveDraft();
        } else {
          syncInputNodeStateFromDom(routeNode);
          DesktopState.saveSettings();
        }
        return;
      }
      const inputField = event.target.closest('.desk-node--input[data-node-id] [data-field]');
      if (inputField) {
        const inputNode = inputField.closest('.desk-node--input[data-node-id]');
        syncInputNodeStateFromDom(inputNode);
        DesktopState.saveSettings();
        return;
      }
      const upscaleField = event.target.closest('.desk-node--upscale[data-node-id] [data-upscale-field]');
      if (upscaleField) {
        syncUpscaleNodeStateFromDom(upscaleField.closest('.desk-node--upscale[data-node-id]'));
        DesktopState.saveSettings();
        return;
      }
      const aliasInput = event.target.closest('[data-text-node-alias]');
      if (aliasInput) {
        if (aliasInput.readOnly) return;
        const node = aliasInput.closest('.desk-node--text[data-node-id]');
        const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
        if (!nodeState) return;
        const alias = sanitizeTextNodeAlias(aliasInput.value);
        if (aliasInput.value !== alias) aliasInput.value = alias;
        nodeState.alias = alias;
        updateTextNodeAliasMetrics(aliasInput);
        DesktopState.saveSettings();
        notifyTextNodeListChange(nodeState.id);
        return;
      }
      const input = event.target.closest('[data-text-node-input]');
      if (!input) return;
      const node = input.closest('.desk-node--text[data-node-id]');
      const nodeState = node ? DesktopState.state.canvas.nodes[node.dataset.nodeId] : null;
      if (!nodeState) return;
      nodeState.text = input.value;
      setTextStyleMenuOpen(node, false);
      DesktopState.saveSettings();
    });

    els.deskCanvasWorld?.addEventListener('change', event => {
      const outputToggle = event.target.closest('[data-output-archive], [data-output-telegram]');
      if (outputToggle) {
        syncOutputControlsFromNode(outputToggle.closest('.desk-node[data-node-id]'));
        return;
      }
      const aliasInput = event.target.closest('[data-text-node-alias]');
      if (aliasInput) {
        commitTextNodeAliasInput(aliasInput);
        setTextNodeAliasEditing(aliasInput.closest('.desk-text-node__alias'), false);
        return;
      }
      const taskTypeSelect = event.target.closest('select[data-field="gptTaskType"]');
      if (taskTypeSelect) {
        const inputNode = taskTypeSelect.closest('.desk-node--input[data-node-id]');
        applyGptTaskTypeToNode(inputNode, taskTypeSelect.value);
        syncInputNodeStateFromDom(inputNode);
        DesktopState.saveSettings();
      }
      const routeSelect = event.target.closest('select[data-field="gptProviderRoute"]');
      if (routeSelect) {
        const routeNode = routeSelect.closest('.desk-node--input[data-node-id]');
        applyGptModelRouteToNode(routeNode, routeSelect.value);
        if (routeNode?.dataset.nodeId === 'input') readFormToState();
        else {
          syncInputNodeStateFromDom(routeNode);
          DesktopState.saveSettings();
        }
      }
      const inputField = event.target.closest('.desk-node--input[data-node-id] [data-field]');
      if (inputField && !taskTypeSelect && !routeSelect) {
        const inputNode = inputField.closest('.desk-node--input[data-node-id]');
        syncInputNodeStateFromDom(inputNode);
        DesktopState.saveSettings();
      }
      const upscaleField = event.target.closest('.desk-node--upscale[data-node-id] [data-upscale-field]');
      if (upscaleField) {
        syncUpscaleNodeStateFromDom(upscaleField.closest('.desk-node--upscale[data-node-id]'));
        DesktopState.saveSettings();
      }
    });

    els.deskProviderSegment?.addEventListener('click', event => {
      const btn = event.target.closest('button[data-provider]');
      if (!btn) return;
      DesktopState.state.provider = btn.dataset.provider;
      syncFormFromState();
      updateProviderParamVisibility(els.deskInputNode, btn.dataset.provider);
      DesktopResults.renderIdleProviderHint();
      DesktopState.saveSettings();
    });

    ['deskRatioSelect', 'deskResolutionSelect', 'deskModelSelect', 'deskQualitySelect', 'deskCountInput', 'deskModerationSelect', 'deskGptTaskTypeSelect', 'deskGptProviderRouteSelect', 'deskGptMainModelSelect', 'deskReasoningEffortSelect', 'deskPromptModeSelect', 'deskBatchMode', 'deskArchiveToggle', 'deskTelegramToggle'].forEach(id => {
      els[id]?.addEventListener('change', readFormToState);
      els[id]?.addEventListener('input', readFormToState);
    });

    els.deskRunBtn?.addEventListener('click', () => {
      addNode('input');
    });
    els.deskConnectModeBtn?.addEventListener('click', () => {
      document.querySelectorAll('.desk-port.is-connecting').forEach(item => item.classList.remove('is-connecting'));
      DesktopResults.showTransientMessage('按住模型节点右侧圆点，拖到图片节点左侧圆点。');
    });

    els.deskImportBtn?.addEventListener('click', () => {
      const selectedNodeId = DesktopState.state.canvas.selectedNodeId;
      const selectedNode = selectedNodeId ? DesktopState.state.canvas.nodes[selectedNodeId] : null;
      pendingUploadNodeId = selectedNode?.type === 'input' ? selectedNodeId : 'input';
      pendingFileMode = 'reference';
      selectNode(pendingUploadNodeId);
      els.deskFileInput?.click();
    });
    els.deskFileInput?.addEventListener('change', event => {
      const files = event.target.files;
      if (pendingFileMode === 'image-node') {
        createImageNodeFromFiles(files, pendingImageNodeCenter).catch(error => DesktopResults.showError(error));
      } else if (pendingFileMode === 'image-node-replace') {
        replaceImageNodeFromFiles(pendingImageTargetNodeId, files).catch(error => DesktopResults.showError(error));
      } else {
        addFilesToNode(pendingUploadNodeId || 'input', files).catch(error => DesktopResults.showError(error));
      }
      pendingFileMode = 'reference';
      pendingImageNodeCenter = null;
      pendingImageTargetNodeId = '';
      event.target.value = '';
    });

    els.deskUploadDrop?.addEventListener('dragover', event => {
      event.preventDefault();
      els.deskUploadDrop.classList.add('is-dragover');
    });
    els.deskUploadDrop?.addEventListener('dragleave', () => {
      els.deskUploadDrop.classList.remove('is-dragover');
    });
    els.deskUploadDrop?.addEventListener('drop', event => {
      event.preventDefault();
      els.deskUploadDrop.classList.remove('is-dragover');
      addFilesToNode('input', event.dataTransfer.files).catch(error => DesktopResults.showError(error));
    });

    els.deskPromptClearBtn?.addEventListener('click', clearDraft);
    els.deskNewBtn?.addEventListener('click', () => {
      clearDraft();
      DesktopResults.resetOutput();
      resetNodeLayout();
    });

    els.deskCanvasViewport?.addEventListener('pointerdown', startPan);
    els.deskCanvasViewport?.addEventListener('mousedown', startRightMousePanFallback, true);
    els.deskCanvasViewport?.addEventListener('contextmenu', event => {
      if (Date.now() < suppressCanvasContextMenuUntil || (activeInteraction?.type === 'pan' && activeInteraction.pointerButton === 'right')) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (event.target.closest(CANVAS_INTERACTION_BLOCK_SELECTOR)) return;
      event.preventDefault();
      event.stopPropagation();
      setNodePaletteOpen(false);
      openContextMenu(event);
    });
    els.deskCanvasViewport?.addEventListener('wheel', handleCanvasWheel, { passive: false });
    els.deskCanvasViewport?.addEventListener('dragover', event => {
      if (!hasHistoryDragPayload(event.dataTransfer) && !hasGalleryDragPayload(event.dataTransfer) && !hasAddNodeDragPayload(event.dataTransfer)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
      els.deskCanvasViewport.classList.add('is-history-dragover');
    });
    els.deskCanvasViewport?.addEventListener('dragleave', event => {
      if (els.deskCanvasViewport.contains(event.relatedTarget)) return;
      els.deskCanvasViewport.classList.remove('is-history-dragover');
    });
    els.deskCanvasViewport?.addEventListener('drop', event => {
      const addNodePayload = getAddNodeDragPayload(event.dataTransfer);
      if (addNodePayload) {
        event.preventDefault();
        event.stopPropagation();
        els.deskCanvasViewport.classList.remove('is-history-dragover');
        if (addNodePayload.type === 'image') {
          pendingFileMode = 'image-node';
          els.deskFileInput?.click();
          return;
        }
        const type = ['file_output', 'layout', 'text', 'pose', 'upscale'].includes(addNodePayload.type) ? addNodePayload.type : 'input';
        const pointer = screenToWorld(event.clientX, event.clientY);
        selectNode(addNode(type, pointer));
        setNodePaletteOpen(false);
        return;
      }
      const galleryPayloads = getGalleryDragPayload(event.dataTransfer);
      if (galleryPayloads.length) {
        event.preventDefault();
        event.stopPropagation();
        els.deskCanvasViewport.classList.remove('is-history-dragover');
        const targetInput = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('.desk-node--input[data-node-id]');
        if (targetInput) {
          attachHistoryImagesToInput(galleryPayloads, targetInput.dataset.nodeId).catch(error => DesktopResults.showError(error));
          return;
        }
        const targetLayout = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('.desk-node--layout[data-node-id]');
        if (targetLayout) {
          attachHistoryImagesToLayout(galleryPayloads, targetLayout.dataset.nodeId).catch(error => DesktopResults.showError(error));
          return;
        }
        createImageNodesFromHistoryItems(galleryPayloads, event.clientX, event.clientY).catch(error => DesktopResults.showError(error));
        return;
      }

      const payload = getHistoryDragPayload(event.dataTransfer);
      if (!payload) return;
      event.preventDefault();
      event.stopPropagation();
      els.deskCanvasViewport.classList.remove('is-history-dragover');
      const targetInput = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('.desk-node--input[data-node-id]');
      if (targetInput) {
        attachHistoryImagesToInput(payload, targetInput.dataset.nodeId).catch(error => DesktopResults.showError(error));
        return;
      }
      const targetLayout = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('.desk-node--layout[data-node-id]');
      if (targetLayout) {
        attachHistoryImageToLayout(payload, targetLayout.dataset.nodeId).catch(error => DesktopResults.showError(error));
        return;
      }
      createImageNodeFromHistoryItem(payload, event.clientX, event.clientY).catch(error => DesktopResults.showError(error));
    });
    els.deskSelectionToolbar?.addEventListener('pointerdown', event => {
      event.stopPropagation();
    });
    els.deskSelectionGroupBtn?.addEventListener('pointerdown', event => {
      event.stopPropagation();
    });
    els.deskSelectionGroupBtn?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      toggleSelectionGroup();
    });
    els.deskSelectionToolbar?.addEventListener('click', event => {
      const button = event.target.closest('[data-align]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      alignSelection(button.dataset.align);
    });
    els.deskCanvasWorld?.addEventListener('pointerdown', event => {
      const aliasShell = event.target.closest('.desk-text-node__alias');
      if (aliasShell) {
        const node = aliasShell.closest('.desk-node--text[data-node-id]');
        if (node) selectNode(node.dataset.nodeId);
        if (event.target.closest('[data-text-node-alias-edit]')) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        const aliasInput = aliasShell.querySelector('[data-text-node-alias]');
        if (aliasInput?.readOnly) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
      }
      const detachPortButton = event.target.closest('.desk-port[data-port="in"]');
      if (detachPortButton && getDetachableIncomingEdge(detachPortButton.dataset.nodeId)) {
        selectNode(detachPortButton.dataset.nodeId);
        startConnectionDetachDrag(event, detachPortButton);
        return;
      }
      const portButton = event.target.closest('.desk-port[data-port="out"]');
      if (portButton) {
        selectNode(portButton.dataset.nodeId);
        startConnectionDrag(event, portButton);
        return;
      }
    if (event.target.closest('[data-node-resize-handle]')) {
      const node = event.target.closest('.desk-node[data-node-id]');
      if (node) selectNode(node.dataset.nodeId);
      if (DesktopState.state.canvas.nodes[node?.dataset.nodeId || '']?.type === 'input') return;
      startNodeResize(event);
      return;
      }
      if (event.target.closest('[data-node-drag-handle]')) {
        const node = event.target.closest('.desk-node[data-node-id]');
        if (node && !getSelectedNodeIds().includes(node.dataset.nodeId)) selectNode(node.dataset.nodeId);
        startNodeDrag(event, { force: isTextNodeDragEdge(event, node) });
      }
    });
    window.addEventListener('pointermove', moveInteraction);
    window.addEventListener('pointerup', endInteraction);
    window.addEventListener('pointercancel', endInteraction);
    window.addEventListener('mousemove', moveMouseInteractionFallback, true);
    window.addEventListener('mouseup', endMouseInteractionFallback, true);
    window.addEventListener('resize', renderMiniMap);
    document.addEventListener('keydown', handleCanvasDeleteKeydown, true);

    els.deskZoomOutBtn?.addEventListener('click', () => {
      setCanvasScale(DesktopState.state.canvas.scale * 0.9);
    });
    els.deskZoomInBtn?.addEventListener('click', () => {
      setCanvasScale(DesktopState.state.canvas.scale * 1.1);
    });
    els.deskZoomResetBtn?.addEventListener('click', resetCanvasView);
    els.deskZoomLabel?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      toggleZoomPresetMenu();
    });
    els.deskZoomLabel?.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      event.stopPropagation();
      toggleZoomPresetMenu();
    });
    els.deskZoomPresetMenu?.addEventListener('click', event => {
      const button = event.target.closest('[data-zoom-preset]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      applyZoomPreset(Number(button.dataset.zoomPreset));
    });
    document.addEventListener('click', event => {
      if (event.target.closest('#deskZoomLabel, #deskZoomPresetMenu')) return;
      setZoomPresetMenuOpen(false);
    });
    els.deskWorkflowDockToggle?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      toggleWorkflowDock();
    });
    els.deskWorkflowSaveBtn?.addEventListener('click', event => {
      event.stopPropagation();
      saveWorkflowFile()
        .then(saved => {
          if (saved) setWorkflowDockOpen(false);
        })
        .catch(error => DesktopResults.showError(error));
    });
    els.deskWorkflowLoadBtn?.addEventListener('click', event => {
      event.stopPropagation();
      els.deskWorkflowFileInput?.click();
    });
    els.deskWorkflowFileInput?.addEventListener('change', event => {
      const file = Array.from(event.target.files || [])[0];
      loadWorkflowFile(file)
        .catch(error => DesktopResults.showError(error))
        .finally(() => {
          event.target.value = '';
          setWorkflowDockOpen(false);
        });
    });
    els.deskMiniMapPinBtn?.addEventListener('click', () => {
      const controls = els.deskMiniMapPinBtn.closest('.desk-zoom-controls');
      const pinned = !controls?.classList.contains('is-pinned');
      setMiniMapPinned(pinned);
    });

    document.addEventListener('keydown', event => {
      if (event.defaultPrevented) return;
      if (event.key === 'Escape') {
        hideContextMenu();
        setZoomPresetMenuOpen(false);
        setWorkflowDockOpen(false);
      }
      const aliasInput = event.target.closest('[data-text-node-alias]');
      if (aliasInput && !aliasInput.readOnly) {
        if (event.key === 'Enter') {
          event.preventDefault();
          commitTextNodeAliasInput(aliasInput);
          setTextNodeAliasEditing(aliasInput.closest('.desk-text-node__alias'), false);
          return;
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          revertTextNodeAliasInput(aliasInput);
          setTextNodeAliasEditing(aliasInput.closest('.desk-text-node__alias'), false);
          return;
        }
      }
      const editingSelectedNode = isEditingSelectedNode(event.target);
      const groupModifier = IS_MAC_PLATFORM ? event.metaKey : event.ctrlKey;
      if (
        groupModifier
        && !event.altKey
        && !event.shiftKey
        && String(event.key || '').toLowerCase() === 'g'
        && !editingSelectedNode
        && getSelectedNodeIds().length >= 2
      ) {
        event.preventDefault();
        event.stopPropagation();
        if (!event.repeat) toggleSelectionGroup();
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && !editingSelectedNode) {
        const selectedNodeIds = nodeIdsForKeyboardDelete(event);
        if (selectedNodeIds.length) {
          event.preventDefault();
          event.stopPropagation();
          getEditableKeyboardTarget(event.target)?.blur?.();
          selectedNodeIds.forEach((nodeId, index) => removeNode(nodeId, {
            clearSelection: true,
            focusCanvas: index === selectedNodeIds.length - 1
          }));
        }
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        readFormToState();
        DesktopResults.submitAndTrack().catch(error => DesktopResults.showError(error));
      }
    });
    document.addEventListener('click', event => {
      if (!isWorkflowDockEventTarget(event.target)) setWorkflowDockOpen(false);
    });
  }

  function init() {
    collectElements();
    migrateResultNodesToModelOutputs();
    migrateLegacyPromptDraftToTextNode();
    ensureTextNodeAliases();
    const groupsChanged = normalizeCanvasGroupsAndSelection();
    syncFormFromState();
    renderReferenceThumbs();
    updateCanvasToolCursor(false);
    bindEvents();
    if (DesktopState.state.runtimeConfig.resetCanvasViewOnLoad) {
      DesktopState.state.runtimeConfig.resetCanvasViewOnLoad = false;
      setCanvasScaleCenteredOnPrimary(DesktopState.DEFAULT_CANVAS_SCALE || DEFAULT_CANVAS_SCALE);
    } else {
      applyCanvasTransform();
    }
    if (groupsChanged) DesktopState.saveSettings();
  }

  window.DesktopCanvas = {
    init,
    readFormToState,
    syncFormFromState,
    applyGptModelCatalog,
    renderReferenceThumbs,
    applyCanvasTransform,
    applyAllNodeLayouts,
    resetCanvasView,
    exportWorkflowSnapshot,
    applyWorkflowSnapshot,
    saveWorkflowFile,
    loadWorkflowFile,
    resolveResultNodeIdForRun,
    readConfigForResult,
    updateInputProgressOverlay,
    connectNodes,
    addNode,
    removeNode,
    selectNode,
    getPromptTargetInfo,
    getPromptTargetText,
    fillPromptTarget,
    fillNearestInputPrompt,
    createTextNodeWithText,
    listTextNodes,
    listPromptImageNodes,
    getTextStylePresets,
    createTextStylePreset,
    registerTextStylePresets,
    applyTextStylePresetToTarget,
    refreshLayoutNode,
    getLayoutInputImages,
    createImageNodeFromHistoryItem,
    continueEditFromHistoryItem,
    createImageNodesFromHistoryItems,
    attachHistoryImagesToInput,
    applyAssetConfigToInput,
    attachHistoryImagesToLayout,
    ensureImageOutputsForConfig,
    populateResultImageNodes,
    runUpscaleChainsForOutput,
    refreshUpscaleNodeMode,
    createImageNodeFromResult
  };
})();
