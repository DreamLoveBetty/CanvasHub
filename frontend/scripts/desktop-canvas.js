(function () {
  const els = {};
  const WORLD_WIDTH = 1440;
  const WORLD_HEIGHT = 820;
  const MIN_SCALE = 0.1;
  const MAX_SCALE = 1.8;
  const ZOOM_PRESETS = [0.1, 0.2, 0.3, 0.5, 0.75];
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
  const IMAGE_GROUP_UI_SCALE = 0.6;
  const imageGroupUiSize = value => value * IMAGE_GROUP_UI_SCALE;
  const IMAGE_GROUP_MAX_ITEMS = 12;
  const IMAGE_GROUP_MAX_COLUMNS = 4;
  const IMAGE_GROUP_BASE_THUMB_PX = 168;
  const IMAGE_GROUP_MOTHER_HEIGHT_PX = imageGroupUiSize(288);
  const IMAGE_GROUP_MOTHER_TOP_PX = imageGroupUiSize(24);
  const IMAGE_GROUP_MOTHER_RADIUS_PX = imageGroupUiSize(32);
  const IMAGE_GROUP_IDENTITY_WIDTH_PX = imageGroupUiSize(168);
  const IMAGE_GROUP_THUMB_PX = imageGroupUiSize(IMAGE_GROUP_BASE_THUMB_PX);
  const IMAGE_GROUP_THUMB_STEP_PX = imageGroupUiSize(128);
  const IMAGE_GROUP_ROW_STEP_PX = imageGroupUiSize(228);
  const IMAGE_GROUP_TRAILING_SPACE_PX = imageGroupUiSize(48);
  const IMAGE_GROUP_LIQUID_SHELL_PX = imageGroupUiSize(216);
  const IMAGE_GROUP_FILTER_OUTSET_PX = imageGroupUiSize(144);
  const IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX = 2;
  const DEFAULT_IMAGE_GROUP_NODE_WIDTH = IMAGE_GROUP_IDENTITY_WIDTH_PX
    + IMAGE_GROUP_THUMB_PX
    + IMAGE_GROUP_THUMB_STEP_PX
    + IMAGE_GROUP_TRAILING_SPACE_PX;
  const DEFAULT_IMAGE_GROUP_NODE_HEIGHT = IMAGE_GROUP_MOTHER_HEIGHT_PX + IMAGE_GROUP_MOTHER_TOP_PX * 2;
  const MIN_IMAGE_GROUP_NODE_WIDTH = DEFAULT_IMAGE_GROUP_NODE_WIDTH;
  const MAX_IMAGE_GROUP_NODE_WIDTH = IMAGE_GROUP_IDENTITY_WIDTH_PX
    + IMAGE_GROUP_THUMB_PX
    + (IMAGE_GROUP_MAX_COLUMNS - 1) * IMAGE_GROUP_THUMB_STEP_PX
    + IMAGE_GROUP_TRAILING_SPACE_PX;
  const IMAGE_GROUP_LAYOUT_VERSION = 9;
  const IMAGE_GROUP_PROXIMITY_DISTANCE_PX = 88;
  const IMAGE_GROUP_PROXIMITY_RELEASE_PX = 122;
  const IMAGE_GROUP_PROXIMITY_DWELL_MS = 620;
  const IMAGE_GROUP_TRANSITION_THUMB_PX = imageGroupUiSize(68);
  const IMAGE_GROUP_PROXIMITY_CONTACT_PX = 52;
  const IMAGE_GROUP_PROXIMITY_DROP_PX = 28;
  const IMAGE_GROUP_PROXIMITY_RELEASE_MS = 380;
  const IMAGE_GROUP_PROXIMITY_DROP_MS = 400;
  const DEFAULT_INPUT_NODE_WIDTH = 720;
  const DEFAULT_INPUT_NODE_HEIGHT = 460;
  const DEFAULT_COMFY_NODE_WIDTH = 420;
  const DEFAULT_COMFY_NODE_HEIGHT = 640;
  const MIN_COMFY_NODE_WIDTH = 360;
  const MIN_COMFY_NODE_HEIGHT = 480;
  const MAX_COMFY_NODE_WIDTH = 900;
  const MAX_COMFY_NODE_HEIGHT = 960;
  const DEFAULT_VIDEO_INFERENCE_NODE_WIDTH = 720;
  const DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT = 380;
  const MIN_VIDEO_INFERENCE_NODE_WIDTH = 660;
  const MIN_VIDEO_INFERENCE_NODE_HEIGHT = 320;
  const MAX_VIDEO_INFERENCE_NODE_WIDTH = 960;
  const MAX_VIDEO_INFERENCE_NODE_HEIGHT = 720;
  const VIDEO_INFERENCE_LAYOUT_VERSION = 2;
  const DEFAULT_VIDEO_NODE_WIDTH = 320;
  const DEFAULT_VIDEO_NODE_HEIGHT = 470;
  const MIN_VIDEO_NODE_WIDTH = 220;
  const MIN_VIDEO_NODE_HEIGHT = 180;
  const MAX_VIDEO_NODE_WIDTH = 720;
  const MAX_VIDEO_NODE_HEIGHT = 960;
  const VIDEO_NODE_LAYOUT_VERSION = 1;
  const DEFAULT_COMFY_PIXEL_WIDTH = 1024;
  const DEFAULT_COMFY_PIXEL_HEIGHT = 1024;
  const MIN_COMFY_PIXEL_SIZE = 64;
  const MAX_COMFY_PIXEL_SIZE = 8192;
  const COMFY_PIXEL_STEP = 8;
  const DEFAULT_FILE_OUTPUT_NODE_WIDTH = 458;
  const DEFAULT_FILE_OUTPUT_NODE_HEIGHT = 420;
  const DEFAULT_UPSCALE_NODE_WIDTH = 360;
  const DEFAULT_UPSCALE_NODE_HEIGHT = 180;
  const LOCKED_INPUT_NODE_WIDTH = DEFAULT_INPUT_NODE_WIDTH;
  const LOCKED_INPUT_NODE_HEIGHT = DEFAULT_INPUT_NODE_HEIGHT;
  const MIN_INPUT_NODE_WIDTH = 560;
  const MAX_INPUT_NODE_WIDTH = 920;
  const DEFAULT_IMAGE_LONGEST_SIDE = 520;
  const MAX_EXTERNAL_IMAGE_IMPORTS = 8;
  const LOCAL_IMAGE_EXTENSION_MIME = Object.freeze({
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    jfif: 'image/jpeg',
    webp: 'image/webp',
    gif: 'image/gif',
    bmp: 'image/bmp',
    avif: 'image/avif',
    svg: 'image/svg+xml',
    ico: 'image/x-icon'
  });
  const LOCAL_IMAGE_MIME_EXTENSION = Object.freeze({
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/webp': 'webp',
    'image/gif': 'gif',
    'image/bmp': 'bmp',
    'image/avif': 'avif',
    'image/svg+xml': 'svg',
    'image/x-icon': 'ico',
    'image/vnd.microsoft.icon': 'ico'
  });
  const SUPPORTED_LOCAL_IMAGE_TEXT = 'PNG、JPG、WebP、GIF、BMP、AVIF、SVG 或 ICO';
  const TEXT_NODE_DRAG_EDGE_PX = 6;
  const TEXT_NODE_ALIAS_MAX_LENGTH = 24;
  const LINK_VIEWBOX = '-3000 -3000 8000 8000';
  const SNAP_THRESHOLD_PX = 9;
  const CONNECTION_LEAD_LENGTH = window.DesktopCanvasGeometry.CONNECTION_LEAD_LENGTH;
  const CONNECTION_CORNER_RADIUS = window.DesktopCanvasGeometry.CONNECTION_CORNER_RADIUS;
  const FLOATING_PORT_TRACKING_MARGIN_PX = 36;
  const FLOATING_SWELL_BORDER_PADDING_PX = 36;
  const FLOATING_SWELL_SAMPLE_SPACING_PX = window.DesktopCanvasPortGeometry.FLOATING_SWELL_SAMPLE_SPACING_PX;
  const FLOATING_SWELL_PEAK_PX = 7;
  const FLOATING_SWELL_LINK_OVERLAP_SCREEN_PX = 1.25;
  const FLOATING_SWELL_LENGTH_PX = window.DesktopCanvasPortGeometry.FLOATING_SWELL_LENGTH_PX;
  const FLOATING_SWELL_PLATEAU_RATIO = window.DesktopCanvasPortGeometry.FLOATING_SWELL_PLATEAU_RATIO;
  const FLOATING_SWELL_SHOULDER_RATIO = window.DesktopCanvasPortGeometry.FLOATING_SWELL_SHOULDER_RATIO;
  const FLOATING_SWELL_VISIBLE_THRESHOLD_PX = window.DesktopCanvasPortGeometry.FLOATING_SWELL_VISIBLE_THRESHOLD_PX;
  const FLOATING_SWELL_EDGE_INSET_PX = 12;
  const FLOATING_SWELL_EDGE_OUTSET_PX = 20;
  const FLOATING_SWELL_SPRING_STIFFNESS = window.DesktopCanvasPortGeometry.FLOATING_SWELL_SPRING_STIFFNESS;
  const FLOATING_SWELL_SPRING_DAMPING = window.DesktopCanvasPortGeometry.FLOATING_SWELL_SPRING_DAMPING;
  const FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS = window.DesktopCanvasPortGeometry.FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS;
  const FLOATING_DROPLET_PEAK_PX = 9;
  const FLOATING_DROPLET_BASE_HALF_LENGTH_PX = window.DesktopCanvasPortGeometry.FLOATING_DROPLET_BASE_HALF_LENGTH_PX;
  const FLOATING_DROPLET_GRAVITY_PULL_PX = window.DesktopCanvasPortGeometry.FLOATING_DROPLET_GRAVITY_PULL_PX;
  const FLOATING_DROPLET_MOTION_PULL_PX = window.DesktopCanvasPortGeometry.FLOATING_DROPLET_MOTION_PULL_PX;
  const FLOATING_DROPLET_FLOW_EXTENSION_PX = window.DesktopCanvasPortGeometry.FLOATING_DROPLET_FLOW_EXTENSION_PX;
  const FLOATING_DROPLET_ACTIVE_PADDING_PX = window.DesktopCanvasPortGeometry.FLOATING_DROPLET_ACTIVE_PADDING_PX;
  const FLOATING_DROPLET_VELOCITY_NORMALIZER = window.DesktopCanvasPortGeometry.FLOATING_DROPLET_VELOCITY_NORMALIZER;
  const CANVAS_PAN_DRAG_THRESHOLD_PX = 3;
  const CANVAS_CONTEXTMENU_SUPPRESS_MS = 450;
  const CANVAS_WHEEL_GESTURE_END_MS = 160;
  const CANVAS_COMPACT_ZOOM_THRESHOLD = 0.72;
  const CANVAS_OVERVIEW_ZOOM_THRESHOLD = 0.5;
  const ORDINARY_MENU_CLOSE_FALLBACK_MS = 240;
  const CANVAS_INTERACTION_BLOCK_SELECTOR = [
    '.desk-node',
    '.desk-link-interaction',
    '.desk-edge-menu',
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
    '.desk-link-interaction',
    '.desk-edge-menu',
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
  const WORKFLOW_VERSION = 3;
  const PROMPT_DOCUMENT_SCHEMA = 'tg-mini-app-img-gen.prompt-document';
  const PROMPT_DOCUMENT_VERSION = 1;
  const PROMPT_DOCUMENT_MAX_SEGMENTS = 2000;
  const PROMPT_DOCUMENT_MAX_LENGTH = 1000000;
  const PROMPT_BLOCK_MAX_CONTENT_LENGTH = 200000;
  const PROMPT_BLOCK_MAX_LABEL_LENGTH = 240;
  const PROMPT_BLOCK_MAX_ID_LENGTH = 160;
  const PROMPT_DOCUMENT_HISTORY_LIMIT = 50;
  const PROMPT_TOKEN_SELECTOR = '[data-prompt-block-token], [data-image-reference-token]';
  const IMAGE_GROUP_ROLES = Object.freeze([
    { value: 'reference', label: '参考' },
    { value: 'subject', label: '主体参考' },
    { value: 'clothing', label: '服饰参考' },
    { value: 'style', label: '风格参考' },
    { value: 'composition', label: '构图参考' },
    { value: 'background', label: '背景参考' }
  ]);
  const IMAGE_GROUP_ROLE_INSTRUCTIONS = Object.freeze({
    reference: '作为通用视觉参考，仅参考用户明确指定的内容。',
    subject: '保持主体身份、外形和关键特征。',
    clothing: '参考服装款式、剪裁、层次、配色、面料纹理和配饰，不继承人物身份、脸部、姿态及背景。',
    style: '仅参考视觉风格、色彩、光影和材质，不继承主体。',
    composition: '仅参考机位、景别、主体位置和空间布局。',
    background: '仅参考场景、环境和空间氛围，不继承前景主体。'
  });
  const IMAGE_GROUP_ROLE_PRIORITY_NOTE = '正文中通过 @图片N 指定的明确要求优先于以上默认用途。';
  const PROMPT_BLOCK_MODULE_LABELS = Object.freeze({
    raw: '原始提示词',
    custom: '自定义',
    identity: '身份',
    appearance: '外貌',
    body_shape: '体形身材',
    pose: '动作姿态',
    expression: '表情视线',
    clothing: '服装造型',
    makeup_hair: '妆发',
    accessories: '配饰',
    subject: '主体',
    scene: '场景环境',
    composition: '构图',
    camera: '视角与镜头',
    lighting: '光线',
    color: '色彩',
    style: '视觉风格',
    material: '材质细节',
    quality: '质量要求',
    constraints: '负面约束',
    goal: '生成目标'
  });
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
  // textPolishState is owned by DesktopCanvasTextEditor.
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
    { value: '4x-UltraSharp', label: 'UltraSharp · 4×' },
    { value: '4x-AnimeSharp', label: 'AnimeSharp · 4×' }
  ];
  let comfyWorkflowCatalog = { workflows: [], items: [], default_workflow: '' };
  const NODE_MENU_ITEMS = [
    window.DesktopTopazModel.menu,
    window.DesktopKrea2Model.MENU_ITEM,
    window.DesktopQwen21Model.MENU_ITEM,
    ...window.DesktopCyimgModel.MENU_ITEMS,
    {
      type: 'input',
      title: '模型输入',
      subtitle: '模型与提示词',
      icon: '<svg class="desk-node-icon desk-node-icon--input" viewBox="0 0 24 24"><g class="desk-node-icon__frame"><path d="M3 8V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3"></path></g><g class="desk-node-icon__enter"><path d="m10 16 4-4-4-4"></path><path d="M3 12h11"></path></g></svg>'
    },
    {
      type: 'comfy',
      title: 'Comfy 工作流',
      subtitle: '本地工作流执行',
      icon: '<svg class="desk-node-icon desk-node-icon--comfy" viewBox="0 0 24 24"><path d="M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3Z"></path><path d="M8 9h8M8 13h5M8 17h7"></path><circle cx="17" cy="13" r="1.5"></circle></svg>'
    },
    {
      type: 'video_inference',
      title: '视频生成',
      subtitle: 'MiniMax H3 推理',
      icon: '<svg class="desk-node-icon desk-node-icon--video-inference" viewBox="0 0 24 24"><rect x="3" y="5" width="14" height="14" rx="3"></rect><path d="m17 10 4-2v8l-4-2"></path><path d="m9 9 4 3-4 3z"></path></svg>'
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
      type: 'video',
      title: '视频节点',
      subtitle: '视频素材与结果',
      icon: '<svg class="desk-node-icon desk-node-icon--video" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"></rect><path d="m10 9 5 3-5 3z"></path></svg>'
    },
    window.DesktopCanvasAudio.MENU_ITEM,
    window.DesktopVideoControlModel.menu,
    window.DesktopTopazVideoModel.menu,
    ...window.DesktopMusicModel.MENU_ITEMS,
    {
      type: 'upscale',
      title: '高清放大',
      subtitle: '本地高清放大',
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
  const canvasViewport = window.DesktopCanvasViewport.create({
    // Resolve current state even when workflow loading replaces the canvas.
    getCanvas: () => DesktopState.state.canvas,
    els,
    clamp,
    getSelectedNodeIds,
    getNodeBounds,
    getNodeBoundsById,
    getBoundsFromRects,
    updateSelectionToolbar,
    positionEdgeMenu,
    updateInputProgressOverlay,
    focusCanvasViewport,
    saveSettings: () => DesktopState.saveSettings(),
    constants: {
      WORLD_WIDTH, WORLD_HEIGHT, MIN_SCALE, MAX_SCALE, ZOOM_PRESETS,
      DEFAULT_CANVAS_SCALE, CANVAS_WHEEL_GESTURE_END_MS,
      CANVAS_COMPACT_ZOOM_THRESHOLD, CANVAS_OVERVIEW_ZOOM_THRESHOLD, IS_MAC_PLATFORM
    }
  });
  let canvasGraphFrameId = 0;
  // connectionPreviewFrameId is owned by DesktopCanvasConnections.
  // pendingConnectionPreview is owned by DesktopCanvasConnections.
  let pendingConnectionDropPoint = null;
  let pendingUploadNodeId = 'input';
  let pendingFileMode = 'reference';
  let pendingImageNodeCenter = null;
  let pendingImageTargetNodeId = '';
  // contextMenuPoint is owned by DesktopCanvasConnections.
  let contextMenuEl = null;
  // contextMenuCloseTimer is owned by DesktopCanvasConnections.
  let nodePaletteCloseTimer = 0;
  let contextMenuConnectionSourceId = '';
  let contextMenuConnectionSourceSide = 'right';
  let contextMenuConnectionSourceAnchor = null;
  // contextMenuConnectionEndPoint is owned by DesktopCanvasConnections.
  let selectedEdgeId = '';
  let hoveredEdgeId = '';
  let edgeMenuEl = null;
  // edgeMenuAnchorWorld is owned by DesktopCanvasConnections.
  let suppressCanvasContextMenuUntil = 0;
  let imageEditorEl = null;
  let imageEditorCanvas = null;
  let activeImageEdit = null;
  // imageEditorThemeObserver is owned by DesktopCanvasImageEditor.
  // externalTextStylePresets is owned by DesktopCanvasTextEditor.
  let gptModelCatalog = null;
  const canvasSelection = window.DesktopCanvasSelection.create({
    // Read the current canvas on each call: workflow loading replaces this object.
    getCanvas: () => DesktopState.state.canvas,
    els,
    getNodeElement,
    getBoundsFromRects,
    rectsIntersect,
    applyNodeLayout,
    setSelectedNodes,
    updateLinkPath,
    saveSettings: () => DesktopState.saveSettings(),
    showTransientMessage: message => DesktopResults.showTransientMessage(message),
    imageNodeSource,
    IS_MAC_PLATFORM,
    IMAGE_GROUP_MAX_ITEMS,
    SNAP_THRESHOLD_PX
  });
  // promptBlockInstanceSequence is owned by DesktopCanvasPromptDocument.
  // imageGroupItemSequence is owned by DesktopCanvasImageGroupModel.
  // imageReferenceInstanceSequence is owned by DesktopCanvasPromptDocument.
  let activeTextImageMention = null;
  let lastPromptTextNodeId = '';
  let draggedImageGroupItem = null;
  // imageGroupSortFrameId is owned by DesktopCanvasImageGroupInteraction.
  let lastCanvasPointer = null;
  // imageGroupSortCleanupTimers is owned by DesktopCanvasImageGroupInteraction.
  const promptDocumentHistories = new Map();
  const promptDocumentVersions = new Map();
  const videoTaskPollTimers = new Map();

  function $(id) {
    return document.getElementById(id);
  }

  function prefersReducedMotion() {
    try {
      return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);
    } catch (e) {
      return false;
    }
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

  function createPromptBlockInstanceId() {
    return canvasPromptDocument.createPromptBlockInstanceId();
  }

  function createImageGroupItemId() {
    return canvasImageGroupModel.createImageGroupItemId();
  }

  function createImageReferenceInstanceId() {
    return canvasPromptDocument.createImageReferenceInstanceId();
  }

  function normalizeImageGroupRole(value, fallback = 'reference') {
    return canvasImageGroupModel.normalizeImageGroupRole(value, fallback);
  }

  function imageGroupRoleLabel(value) {
    return canvasImageGroupModel.imageGroupRoleLabel(value);
  }

  function imageGroupRoleInstruction(value) {
    return canvasImageGroupModel.imageGroupRoleInstruction(value);
  }

  function getImageGroupItem(groupId, itemId, sourceNodeId = '') {
    return canvasImageGroupModel.getImageGroupItem(groupId, itemId, sourceNodeId);
  }

  function imageReferenceRole(segment = {}) {
    return canvasPromptDocument.imageReferenceRole(segment);
  }

  function imageReferenceTargetNodeId(segment = {}, sourceId = '') {
    return canvasPromptDocument.imageReferenceTargetNodeId(segment, sourceId);
  }

  function imageReferenceNumber(segment = {}) {
    return canvasPromptDocument.imageReferenceNumber(segment);
  }

  function imageReferenceDisplay(segment = {}) {
    return canvasPromptDocument.imageReferenceDisplay(segment);
  }

  function normalizeImageReferenceSegment(segment = {}, fallback = {}) {
    return canvasPromptDocument.normalizeImageReferenceSegment(segment, fallback);
  }

  function truncatePromptValue(value, maxLength) {
    return canvasPromptDocument.truncatePromptValue(value, maxLength);
  }

  function createTextPromptDocument(value = '') {
    return canvasPromptDocument.createTextPromptDocument(value);
  }

  function normalizePromptBlockSegment(segment = {}, fallback = {}) {
    return canvasPromptDocument.normalizePromptBlockSegment(segment, fallback);
  }

  function normalizePromptDocument(promptDocument, fallbackText = '') {
    return canvasPromptDocument.normalizePromptDocument(promptDocument, fallbackText);
  }

  function materializePromptDocument(promptDocument) {
    return canvasPromptDocument.materializePromptDocument(promptDocument);
  }

  function promptDocumentFidelityHeader(promptDocument) {
    return canvasPromptDocument.promptDocumentFidelityHeader(promptDocument);
  }

  function clonePromptDocument(promptDocument, fallbackText = '') {
    return canvasPromptDocument.clonePromptDocument(promptDocument, fallbackText);
  }

  function ensureTextNodePromptDocument(node) {
    return canvasPromptDocument.ensureTextNodePromptDocument(node);
  }

  function promptDocumentFingerprint(promptDocument, fallbackText = '') {
    return canvasPromptDocument.promptDocumentFingerprint(promptDocument, fallbackText);
  }

  function getPromptDocumentVersion(nodeStateOrId) {
    return canvasPromptDocument.getPromptDocumentVersion(nodeStateOrId);
  }

  function bumpPromptDocumentVersion(nodeState) {
    return canvasPromptDocument.bumpPromptDocumentVersion(nodeState);
  }

  function getPromptDocumentHistory(nodeId, create = true) {
    return canvasPromptDocument.getPromptDocumentHistory(nodeId, create);
  }

  function beginPromptDocumentHistory(nodeState) {
    return canvasPromptDocument.beginPromptDocumentHistory(nodeState);
  }

  function commitPromptDocumentHistory(nodeState, entry) {
    return canvasPromptDocument.commitPromptDocumentHistory(nodeState, entry);
  }

  function clearPromptDocumentHistory(nodeId) {
    return canvasPromptDocument.clearPromptDocumentHistory(nodeId);
  }

  function promptDocumentHasEditorContent(promptDocument) {
    return canvasPromptDocument.promptDocumentHasEditorContent(promptDocument);
  }

  function updatePromptEditorEmptyState(editor, promptDocument) {
    return canvasTextEditor.updatePromptEditorEmptyState(editor, promptDocument);
  }

  function materializeTextNode(node) {
    return canvasPromptDocument.materializeTextNode(node);
  }

  function ensureTextNodePromptDocuments() {
    return canvasPromptDocument.ensureTextNodePromptDocuments();
  }

  function shortPromptBlockLabel(value) {
    return canvasTextEditor.shortPromptBlockLabel(value);
  }

  function promptBlockModuleLabel(moduleType) {
    return canvasTextEditor.promptBlockModuleLabel(moduleType);
  }

  function promptBlockModuleMark(moduleType) {
    return canvasTextEditor.promptBlockModuleMark(moduleType);
  }

  function promptBlockTokenHtml(segment) {
    return canvasTextEditor.promptBlockTokenHtml(segment);
  }

  function imageReferenceTokenHtml(segment) {
    return canvasTextEditor.imageReferenceTokenHtml(segment);
  }

  function syncImageReferenceTokenElement(token, segment) {
    return canvasTextEditor.syncImageReferenceTokenElement(token, segment);
  }

  function promptDocumentEditorHtml(promptDocument) {
    return canvasTextEditor.promptDocumentEditorHtml(promptDocument);
  }

  function promptDocumentFromEditor(editor, nodeState) {
    return canvasTextEditor.promptDocumentFromEditor(editor, nodeState);
  }

  function renderPromptDocumentToEditor(editor, promptDocument) {
    return canvasTextEditor.renderPromptDocumentToEditor(editor, promptDocument);
  }

  function setTextNodePromptDocument(node, nodeState, promptDocument, options = {}) {
    return canvasTextEditor.setTextNodePromptDocument(node, nodeState, promptDocument, options);
  }

  function syncPromptDocumentFromEditor(editor, nodeState, options = {}) {
    return canvasTextEditor.syncPromptDocumentFromEditor(editor, nodeState, options);
  }

  function focusPromptEditorAtEnd(node) {
    return canvasTextEditor.focusPromptEditorAtEnd(node);
  }

  function undoPromptDocumentChange(node, nodeState, options = {}) {
    return canvasTextEditor.undoPromptDocumentChange(node, nodeState, options);
  }

  function redoPromptDocumentChange(node, nodeState) {
    return canvasTextEditor.redoPromptDocumentChange(node, nodeState);
  }

  function handlePromptDocumentHistoryShortcut(event, editor) {
    return canvasTextEditor.handlePromptDocumentHistoryShortcut(event, editor);
  }

  function sanitizeTextNodeAlias(value) {
    return canvasTextEditor.sanitizeTextNodeAlias(value);
  }

  function nextTextNodeAlias(excludeNodeId = '') {
    return canvasTextEditor.nextTextNodeAlias(excludeNodeId);
  }

  function getTextNodeAlias(node) {
    return canvasTextEditor.getTextNodeAlias(node);
  }

  function textNodeAliasMeasure(value) {
    return canvasTextEditor.textNodeAliasMeasure(value);
  }

  function textNodeAliasStyle(alias) {
    return canvasTextEditor.textNodeAliasStyle(alias);
  }

  function updateTextNodeAliasMetrics(aliasInput) {
    return canvasTextEditor.updateTextNodeAliasMetrics(aliasInput);
  }

  function setTextNodeAliasEditing(shell, editing) {
    return canvasTextEditor.setTextNodeAliasEditing(shell, editing);
  }

  function commitTextNodeAliasInput(aliasInput) {
    return canvasTextEditor.commitTextNodeAliasInput(aliasInput);
  }

  function revertTextNodeAliasInput(aliasInput) {
    return canvasTextEditor.revertTextNodeAliasInput(aliasInput);
  }

  function ensureTextNodeAliases() {
    return canvasTextEditor.ensureTextNodeAliases();
  }

  function listTextNodes() {
    return canvasTextEditor.listTextNodes();
  }

  function notifyTextNodeListChange(nodeId = '') {
    return canvasTextEditor.notifyTextNodeListChange(nodeId);
  }

  function ratioOptionsHtml(selected = '9:16') {
    return canvasModelNodes.ratioOptionsHtml(selected);
  }

  function googleModelOptionsHtml(selected = DEFAULT_GOOGLE_MODEL) {
    return canvasModelNodes.googleModelOptionsHtml(selected);
  }

  function imageCountOptionsHtml(selected = 2) {
    return canvasModelNodes.imageCountOptionsHtml(selected);
  }

  function optionListHtml(options, selected) {
    return canvasModelNodes.optionListHtml(options, selected);
  }

  function fallbackGptModelOptions(route) {
    return canvasModelNodes.fallbackGptModelOptions(route);
  }

  function gptRouteCatalog(route) {
    return canvasModelNodes.gptRouteCatalog(route);
  }

  function gptModelOptionsForRoute(route) {
    return canvasModelNodes.gptModelOptionsForRoute(route);
  }

  function gptModelCatalogEntry(route, model) {
    return canvasModelNodes.gptModelCatalogEntry(route, model);
  }

  function reasoningOption(value) {
    return canvasModelNodes.reasoningOption(value);
  }

  function gptReasoningOptionsForModel(route, model) {
    return canvasModelNodes.gptReasoningOptionsForModel(route, model);
  }

  function selectedReasoningForModel(params, route, model, options) {
    return canvasModelNodes.selectedReasoningForModel(params, route, model, options);
  }

  function updateGptRoutePresentation(node, route) {
    return canvasModelNodes.updateGptRoutePresentation(node, route);
  }

  function applyGptReasoningToNode(node, route, model) {
    return canvasModelNodes.applyGptReasoningToNode(node, route, model);
  }

  function selectedGptModelForRoute(params, route, options = gptModelOptionsForRoute(route)) {
    return canvasModelNodes.selectedGptModelForRoute(params, route, options);
  }

  function inputParamsForNode(node) {
    return canvasModelNodes.inputParamsForNode(node);
  }

  function applyGptModelRouteToNode(node, route, { rememberPrevious = true } = {}) {
    return canvasModelNodes.applyGptModelRouteToNode(node, route, { rememberPrevious });
  }

  function applyGptModelCatalog(payload = {}) {
    return canvasModelNodes.applyGptModelCatalog(payload);
  }

  function ratioFromAspect(aspectRatio, fallback = '1:1') {
    return canvasModelNodes.ratioFromAspect(aspectRatio, fallback);
  }

  function textStylePresetButtonsHtml() {
    return canvasTextEditor.textStylePresetButtonsHtml();
  }

  function loadCustomTextStylePresets() {
    return canvasTextEditor.loadCustomTextStylePresets();
  }

  function saveCustomTextStylePresets(items) {
    return canvasTextEditor.saveCustomTextStylePresets(items);
  }

  function allTextStylePresets() {
    return canvasTextEditor.allTextStylePresets();
  }

  function getTextStylePreset(presetId) {
    return canvasTextEditor.getTextStylePreset(presetId);
  }

  function textStyleTagHtml(presetId) {
    return canvasTextEditor.textStyleTagHtml(presetId);
  }

  function updateProviderParamVisibility(root, provider = 'gpt') {
    return canvasModelNodes.updateProviderParamVisibility(root, provider);
  }

  function updateAllProviderParamVisibility() {
    return canvasModelNodes.updateAllProviderParamVisibility();
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
    return window.DesktopCanvasGeometry.clamp(value, min, max);
  }

  function imageGroupColumnCount(itemCount = 0) {
    return canvasImageGroupModel.imageGroupColumnCount(itemCount);
  }

  function imageGroupRowCount(itemCount = 0) {
    return canvasImageGroupModel.imageGroupRowCount(itemCount);
  }

  function naturalImageGroupNodeWidth(itemCount = 0) {
    return canvasImageGroupModel.naturalImageGroupNodeWidth(itemCount);
  }

  function compactImageGroupNodeWidth(itemCount = 0) {
    return canvasImageGroupModel.compactImageGroupNodeWidth(itemCount);
  }

  function imageGroupMotherHeight(itemCount = 0) {
    return canvasImageGroupModel.imageGroupMotherHeight(itemCount);
  }

  function imageGroupNodeHeight(itemCount = 0) {
    return canvasImageGroupModel.imageGroupNodeHeight(itemCount);
  }

  function imageGroupThumbPosition(index = 0) {
    return canvasImageGroupModel.imageGroupThumbPosition(index);
  }

  function getNodeState(nodeId) {
    return DesktopState.state.canvas.nodes[nodeId];
  }

  function getNodeElement(nodeId) {
    return document.querySelector(`.desk-node[data-node-id="${CSS.escape(nodeId)}"]`);
  }

  function normalizeNodeGroupId(value) {
    return canvasSelection.normalizeNodeGroupId(value);
  }

  function normalizeNodeGroups(nodes = DesktopState.state.canvas.nodes) {
    return canvasSelection.normalizeNodeGroups(nodes);
  }

  function getNodeIdsInGroup(groupId, nodes = DesktopState.state.canvas.nodes) {
    return canvasSelection.getNodeIdsInGroup(groupId, nodes);
  }

  function expandNodeIdsToGroups(nodeIds, nodes = DesktopState.state.canvas.nodes) {
    return canvasSelection.expandNodeIdsToGroups(nodeIds, nodes);
  }

  function normalizeCanvasGroupsAndSelection() {
    return canvasSelection.normalizeCanvasGroupsAndSelection();
  }

  function createNodeGroupId() {
    return canvasSelection.createNodeGroupId();
  }

  function getSelectionGroupState(nodeIds = getSelectedNodeIds()) {
    return canvasSelection.getSelectionGroupState(nodeIds);
  }

  function getSelectedNodeIds() {
    return canvasSelection.getSelectedNodeIds();
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
    if (selectedEdgeId) {
      const edgeId = selectedEdgeId;
      event.preventDefault();
      event.stopPropagation();
      removeEdgesById([edgeId]);
      focusCanvasViewport();
      return;
    }
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
    return canvasReferences.getNodeReferenceStore();
  }

  function getReferenceUrl(image) {
    return canvasReferences.getReferenceUrl(image);
  }

  function isObjectUrl(url) {
    return canvasReferences.isObjectUrl(url);
  }

  function revokeReferenceUrl(image) {
    return canvasReferences.revokeReferenceUrl(image);
  }

  function referenceKey(image) {
    return canvasReferences.referenceKey(image);
  }

  function setSelectedNodes(nodeIds, save = true) {
    const uniqueIds = expandNodeIdsToGroups(
      [...new Set((nodeIds || []).filter(nodeId => !!DesktopState.state.canvas.nodes[nodeId]))]
    );
    if (uniqueIds.length && selectedEdgeId) {
      selectedEdgeId = '';
      hoveredEdgeId = '';
      hideEdgeMenu();
    }
    DesktopState.state.canvas.selectedNodeIds = uniqueIds;
    DesktopState.state.canvas.selectedNodeId = uniqueIds[0] || '';
    const selectedTextNodeId = uniqueIds.find(nodeId => DesktopState.state.canvas.nodes[nodeId]?.type === 'text') || '';
    if (selectedTextNodeId) lastPromptTextNodeId = selectedTextNodeId;
    blurEditableFocusOutsideSelection(uniqueIds);
    applyNodeSelection();
    window.dispatchEvent(new CustomEvent('desktop:canvas-selection-change', {
      detail: {
        selectedNodeId: DesktopState.state.canvas.selectedNodeId,
        selectedNodeIds: [...uniqueIds],
        selectedTextNodeId
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

  function applyCanvasTransform(options = {}) {
    return canvasViewport.applyCanvasTransform(options);
  }

  function scheduleCanvasPanTransform() {
    return canvasViewport.scheduleCanvasPanTransform();
  }

  function flushCanvasPanTransform() {
    return canvasViewport.flushCanvasPanTransform();
  }

  function scheduleCanvasGraphRender() {
    if (canvasGraphFrameId) return;
    canvasGraphFrameId = requestAnimationFrame(() => {
      canvasGraphFrameId = 0;
      updateLinkPath();
      updateSelectionToolbar();
      updateInputProgressOverlay();
    });
  }

  function flushCanvasGraphRender() {
    if (canvasGraphFrameId) cancelAnimationFrame(canvasGraphFrameId);
    canvasGraphFrameId = 0;
    updateLinkPath();
    updateSelectionToolbar();
    updateInputProgressOverlay();
  }

  function updateCanvasZoomLabel() {
    return canvasViewport.updateCanvasZoomLabel();
  }

  function finishCanvasWheelGesture(options = {}) {
    return canvasViewport.finishCanvasWheelGesture(options);
  }

  function scheduleCanvasWheelGestureEnd() {
    return canvasViewport.scheduleCanvasWheelGestureEnd();
  }

  function applyNodeLayout(nodeId, options = {}) {
    return canvasNodes.applyNodeLayout(nodeId, options);
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
    Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node.type === 'comfy')
      .forEach(node => refreshComfyNode(node.id));
    Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node.type === 'video_inference')
      .forEach(node => refreshVideoInferenceNode(node.id));
    Object.values(DesktopState.state.canvas.nodes)
      .filter(node => node.type === 'video')
      .forEach(node => refreshVideoNode(node.id));
    applyNodeSelection();
    updateLinkPath();
    updateInputProgressOverlay();
  }

  function ensureDefaultModelOutputState() {
    return canvasNodes.ensureDefaultModelOutputState();
  }

  function migrateResultNodesToModelOutputs() {
    return canvasNodes.migrateResultNodesToModelOutputs();
  }

  function migrateLegacyPromptDraftToTextNode() {
    return canvasNodes.migrateLegacyPromptDraftToTextNode();
  }

  function setNodePaletteOpen(open) {
    return canvasNodes.setNodePaletteOpen(open);
  }

  function nodeMenuButtonHtml(item) {
    return canvasNodes.nodeMenuButtonHtml(item);
  }

  function renderNodePaletteItems() {
    return canvasNodes.renderNodePaletteItems();
  }

  function filterContextMenuItems(menu, query = '') {
    return canvasConnections.filterContextMenuItems(menu, query);
  }

  function getConnectableNodeMenuItems(fromNodeId) {
    return canvasConnections.getConnectableNodeMenuItems(fromNodeId);
  }

  function renderContextMenuItems(items, title = '') {
    return canvasConnections.renderContextMenuItems(items, title);
  }

  function ensureContextMenu() {
    return canvasConnections.ensureContextMenu();
  }

  function finishContextMenuClose() {
    return canvasConnections.finishContextMenuClose();
  }

  function hideContextMenu(options = {}) {
    return canvasConnections.hideContextMenu(options);
  }

  function openContextMenu(event, options = {}) {
    return canvasConnections.openContextMenu(event, options);
  }

  function getCanvasEdge(edgeId) {
    return canvasConnections.getCanvasEdge(edgeId);
  }

  function ensureEdgeMenu() {
    return canvasConnections.ensureEdgeMenu();
  }

  function hideEdgeMenu() {
    return canvasConnections.hideEdgeMenu();
  }

  function clearSelectedEdge(options = {}) {
    return canvasConnections.clearSelectedEdge(options);
  }

  function positionEdgeMenu(edgeId = selectedEdgeId) {
    return canvasConnections.positionEdgeMenu(edgeId);
  }

  function openEdgeMenu(edgeId, anchorEvent = null) {
    return canvasConnections.openEdgeMenu(edgeId, anchorEvent);
  }

  function selectNode(nodeId) {
    if (nodeId && !DesktopState.state.canvas.nodes[nodeId]) return;
    setSelectedNodes(nodeId ? [nodeId] : []);
  }

  function getPromptTargetInfo(nodeId = '') {
    return canvasTextEditor.getPromptTargetInfo(nodeId);
  }

  function getPromptTargetText(options = {}) {
    return canvasTextEditor.getPromptTargetText(options);
  }

  function normalizePromptGenerationMeta(value) {
    return canvasPromptDocument.normalizePromptGenerationMeta(value);
  }

  function promptTextFingerprint(value) {
    return canvasPromptDocument.promptTextFingerprint(value);
  }

  function setTextNodePromptMeta(nodeState, value, promptText = '') {
    return canvasPromptDocument.setTextNodePromptMeta(nodeState, value, promptText);
  }

  function fillPromptTarget(text, options = {}) {
    return canvasTextEditor.fillPromptTarget(text, options);
  }

  function fillNearestInputPrompt(text, options = {}) {
    return canvasTextEditor.fillNearestInputPrompt(text, options);
  }

  function createTextNodeWithText(text, worldPoint = null, options = {}) {
    return canvasTextEditor.createTextNodeWithText(text, worldPoint, options);
  }

  function findConnectedTextNodeId(inputNodeId) {
    return canvasTextEditor.findConnectedTextNodeId(inputNodeId);
  }

  function setPromptTextForInputNode(inputNodeId, text, options = {}) {
    return canvasTextEditor.setPromptTextForInputNode(inputNodeId, text, options);
  }

  function getTextStylePresets() {
    return canvasTextEditor.getTextStylePresets();
  }

  function createTextStylePreset(title, promptTemplate) {
    return canvasTextEditor.createTextStylePreset(title, promptTemplate);
  }

  function registerTextStylePresets(items = []) {
    return canvasTextEditor.registerTextStylePresets(items);
  }

  function applyTextStylePresetToTarget(presetId, options = {}) {
    return canvasTextEditor.applyTextStylePresetToTarget(presetId, options);
  }

  function applyNodeSelection() {
    return canvasNodes.applyNodeSelection();
  }

  function normalizePortSide(value, fallback = 'right') {
    return window.DesktopCanvasGeometry.normalizePortSide(value, fallback);
  }

  function oppositePortSide(side) {
    return window.DesktopCanvasGeometry.oppositePortSide(side);
  }

  function getNodeGeometry(nodeId) {
    return canvasConnections.getNodeGeometry(nodeId);
  }

  function getAnchor(nodeId, side = 'right') {
    return canvasConnections.getAnchor(nodeId, side);
  }

  function dominantPortSide(fromPoint, toPoint) {
    return window.DesktopCanvasGeometry.dominantPortSide(fromPoint, toPoint);
  }

  function resolveConnectionSides() {
    return canvasConnections.resolveConnectionSides();
  }

  function updateSettledConnectionPorts(edges = []) {
    return canvasConnections.updateSettledConnectionPorts(edges);
  }

  function contextMenuConnectionPreviewPath() {
    return canvasConnections.contextMenuConnectionPreviewPath();
  }

  function refreshContextMenuConnectionPreview() {
    return canvasConnections.refreshContextMenuConnectionPreview();
  }

  function updateLinkPath() {
    return canvasConnections.updateLinkPath();
  }

  function setHoveredEdge(edgeId = '') {
    return canvasConnections.setHoveredEdge(edgeId);
  }

  function bindLinkLayerInteractions() {
    return canvasConnections.bindLinkLayerInteractions();
  }

  function getNodeBounds(nodeState) {
    return canvasSelection.getNodeBounds(nodeState);
  }

  function getNodeBoundsById(nodeId) {
    return canvasSelection.getNodeBoundsById(nodeId);
  }

  function getBoundsFromRects(rects) {
    return window.DesktopCanvasGeometry.getBoundsFromRects(rects);
  }

  function getBoundsForNodeIds(nodeIds) {
    return canvasSelection.getBoundsForNodeIds(nodeIds);
  }

  function getSelectionUnits(nodeIds = getSelectedNodeIds()) {
    return canvasSelection.getSelectionUnits(nodeIds);
  }

  function moveSelectionUnit(unit, dx, dy) {
    return canvasSelection.moveSelectionUnit(unit, dx, dy);
  }

  function selectionGroupShortcutLabel() {
    return canvasSelection.selectionGroupShortcutLabel();
  }

  function worldRectToCanvasRect(rect) {
    return canvasSelection.worldRectToCanvasRect(rect);
  }

  function updateSelectionToolbar() {
    return canvasSelection.updateSelectionToolbar();
  }

  function renderMarquee(worldRect) {
    return canvasSelection.renderMarquee(worldRect);
  }

  function hideMarquee() {
    return canvasSelection.hideMarquee();
  }

  function hideSmartGuides() {
    return canvasSelection.hideSmartGuides();
  }

  function applySelectionLayout() {
    return canvasSelection.applySelectionLayout();
  }

  function toggleSelectionGroup() {
    return canvasSelection.toggleSelectionGroup();
  }

  function sortImageNodesForGroup(nodes = []) {
    return canvasImageGroupModel.sortImageNodesForGroup(nodes);
  }

  function imageNodesForGroupSelection() {
    return canvasImageGroupModel.imageNodesForGroupSelection();
  }

  function captureImageNodeTransitionSources(nodes) {
    return canvasImageGroupInteraction.captureImageNodeTransitionSources(nodes);
  }

  function nextCanvasEdgeId(fromNodeId, toNodeId, suffix = '') {
    return canvasImageGroupModel.nextCanvasEdgeId(fromNodeId, toNodeId, suffix);
  }

  function orderTransitionSourcesForNodes(sources, nodes) {
    return canvasImageGroupInteraction.orderTransitionSourcesForNodes(sources, nodes);
  }

  function createImageGroupFromNodes(nodes, options = {}) {
    return canvasImageGroupModel.createImageGroupFromNodes(nodes, options);
  }

  function createImageGroupFromSelection() {
    return canvasImageGroupModel.createImageGroupFromSelection();
  }

  function appendImageNodeToGroup(imageNodeId, groupId, options = {}) {
    return canvasImageGroupModel.appendImageNodeToGroup(imageNodeId, groupId, options);
  }

  function migrateImageReferenceTokensToGroup(groupId, sourceNodeIds = []) {
    return canvasTextEditor.migrateImageReferenceTokensToGroup(groupId, sourceNodeIds);
  }

  function freezeImageReferenceTokensMatching(predicate) {
    return canvasTextEditor.freezeImageReferenceTokensMatching(predicate);
  }

  function freezeImageReferenceTokens(groupId) {
    return canvasTextEditor.freezeImageReferenceTokens(groupId);
  }

  function freezeImageReferenceTokensForSourceNode(sourceNodeId) {
    return canvasTextEditor.freezeImageReferenceTokensForSourceNode(sourceNodeId);
  }

  function refreshImageReferenceTokens(groupId = '') {
    return canvasTextEditor.refreshImageReferenceTokens(groupId);
  }

  function imageNodeStateFromGroupItem(item, groupNode, index) {
    return canvasImageGroupModel.imageNodeStateFromGroupItem(item, groupNode, index);
  }

  function ungroupImageGroup(groupId) {
    return canvasImageGroupModel.ungroupImageGroup(groupId);
  }

  function captureImageGroupItemRects(groupId) {
    return canvasImageGroupInteraction.captureImageGroupItemRects(groupId);
  }

  function animateImageGroupItemFlip(groupId, before) {
    return canvasImageGroupInteraction.animateImageGroupItemFlip(groupId, before);
  }

  function reorderImageGroupItemToIndex(groupId, itemId, targetIndex, before = null) {
    return canvasImageGroupModel.reorderImageGroupItemToIndex(groupId, itemId, targetIndex, before);
  }

  function reorderImageGroupItem(groupId, itemId, targetItemId, placeAfter = false) {
    return canvasImageGroupModel.reorderImageGroupItem(groupId, itemId, targetItemId, placeAfter);
  }

  function imageGroupSortTransform(sortState, entry, screenDx, screenDy = 0, scale = 1, blobTransform = null) {
    return canvasImageGroupInteraction.imageGroupSortTransform(sortState, entry, screenDx, screenDy, scale, blobTransform);
  }

  function beginImageGroupItemSort(event) {
    return canvasImageGroupInteraction.beginImageGroupItemSort(event);
  }

  function renderImageGroupItemSortFrame(sortState) {
    return canvasImageGroupInteraction.renderImageGroupItemSortFrame(sortState);
  }

  function moveImageGroupItemSort(event) {
    return canvasImageGroupInteraction.moveImageGroupItemSort(event);
  }

  function clearImageGroupItemSortState(sortState, delay = 0) {
    return canvasImageGroupInteraction.clearImageGroupItemSortState(sortState, delay);
  }

  function returnImageGroupItemSort(sortState) {
    return canvasImageGroupInteraction.returnImageGroupItemSort(sortState);
  }

  function endImageGroupItemSort(event, cancelled = false) {
    return canvasImageGroupInteraction.endImageGroupItemSort(event, cancelled);
  }

  function resolveImageReferenceTextNode(groupId) {
    return canvasTextEditor.resolveImageReferenceTextNode(groupId);
  }

  function insertImageReferenceToken(groupId, itemId) {
    return canvasTextEditor.insertImageReferenceToken(groupId, itemId);
  }

  function imageGroupGooeyFilterPrimitivesHtml() {
    return canvasImageGroupModel.imageGroupGooeyFilterPrimitivesHtml();
  }

  function ensureGlobalImageGroupGooeyFilter() {
    return canvasImageGroupInteraction.ensureGlobalImageGroupGooeyFilter();
  }

  function cappedTransitionRect(rect, maxSide = IMAGE_GROUP_TRANSITION_THUMB_PX) {
    return canvasImageGroupInteraction.cappedTransitionRect(rect, maxSide);
  }

  function animateImageTransition(pairs, focusRect, options = {}) {
    return canvasImageGroupInteraction.animateImageTransition(pairs, focusRect, options);
  }

  function animateImagesIntoGroup(sources, groupId) {
    return canvasImageGroupInteraction.animateImagesIntoGroup(sources, groupId);
  }

  function animateImagesOutOfGroup(sources, restoredNodes) {
    return canvasImageGroupInteraction.animateImagesOutOfGroup(sources, restoredNodes);
  }

  function rectGapDistance(first, second) {
    return canvasImageGroupInteraction.rectGapDistance(first, second);
  }

  function mergeAnchorBetweenRects(first, second) {
    return canvasImageGroupInteraction.mergeAnchorBetweenRects(first, second);
  }

  function eligibleImageGroupProximityTarget(node, sourceNodeId, excludedIds) {
    return canvasImageGroupInteraction.eligibleImageGroupProximityTarget(node, sourceNodeId, excludedIds);
  }

  function findImageGroupProximityCandidate(interaction, threshold = IMAGE_GROUP_PROXIMITY_DISTANCE_PX) {
    return canvasImageGroupInteraction.findImageGroupProximityCandidate(interaction, threshold);
  }

  function positionImageGroupDwellIndicator(indicator, sourceRect, targetRect) {
    return canvasImageGroupInteraction.positionImageGroupDwellIndicator(indicator, sourceRect, targetRect);
  }

  function createImageGroupDwellIndicator(sourceRect, targetRect) {
    return canvasImageGroupInteraction.createImageGroupDwellIndicator(sourceRect, targetRect);
  }

  function imageGroupProximityPreviewEntries(sourceNodeId, targetNodeId) {
    return canvasImageGroupInteraction.imageGroupProximityPreviewEntries(sourceNodeId, targetNodeId);
  }

  function setImageGroupPreviewChipUnit(chip, side) {
    return canvasImageGroupInteraction.setImageGroupPreviewChipUnit(chip, side);
  }

  /*
   * Live proximity preview
   *
   * One-shot image transitions used by ungrouping remain separate. The live
   * proximity path has its own lifecycle: after the 620ms dwell the pointer is
   * still a normal node drag, while this overlay becomes the crisp content
   * layer and the SVG becomes the liquid silhouette layer.
   */
  function liveImageGroupSmoothstep(value) {
    return canvasImageGroupInteraction.liveImageGroupSmoothstep(value);
  }

  function liveImageGroupEase(value) {
    return canvasImageGroupInteraction.liveImageGroupEase(value);
  }

  function liveImageGroupRoundedRectContact(point, rect, cornerRadius) {
    return canvasImageGroupInteraction.liveImageGroupRoundedRectContact(point, rect, cornerRadius);
  }

  function liveImageGroupApproachContact(sourcePoint, targetPoint, rect, cornerRadius) {
    return canvasImageGroupInteraction.liveImageGroupApproachContact(sourcePoint, targetPoint, rect, cornerRadius);
  }

  function liveImageGroupChip(entry, imageLayer, incoming = false) {
    return canvasImageGroupInteraction.liveImageGroupChip(entry, imageLayer, incoming);
  }

  function liveImageGroupMask(normal, strength) {
    return canvasImageGroupInteraction.liveImageGroupMask(normal, strength);
  }

  function liveImageGroupSlotPosition(preview, index) {
    return canvasImageGroupInteraction.liveImageGroupSlotPosition(preview, index);
  }

  function liveImageGroupSlotIndex(preview, center) {
    return canvasImageGroupInteraction.liveImageGroupSlotIndex(preview, center);
  }

  function liveImageGroupSlotCenter(preview, index) {
    return canvasImageGroupInteraction.liveImageGroupSlotCenter(preview, index);
  }

  function renderLiveImageGroupPreview(preview, now = performance.now(), immediate = false) {
    return canvasImageGroupInteraction.renderLiveImageGroupPreview(preview, now, immediate);
  }

  function startLiveImageGroupPreviewFrame(preview) {
    return canvasImageGroupInteraction.startLiveImageGroupPreviewFrame(preview);
  }

  function createImageGroupProximityPreview(sourceNodeId, targetNodeId, interaction) {
    return canvasImageGroupInteraction.createImageGroupProximityPreview(sourceNodeId, targetNodeId, interaction);
  }

  function clearImageGroupProximity(interaction, options = {}) {
    return canvasImageGroupInteraction.clearImageGroupProximity(interaction, options);
  }

  function releaseImageGroupProximity(interaction) {
    return canvasImageGroupInteraction.releaseImageGroupProximity(interaction);
  }

  function beginImageGroupProximity(interaction, candidate) {
    return canvasImageGroupInteraction.beginImageGroupProximity(interaction, candidate);
  }

  function updateImageGroupProximity(interaction) {
    return canvasImageGroupInteraction.updateImageGroupProximity(interaction);
  }

  function animateImageGroupProximityDrop(interaction) {
    return canvasImageGroupInteraction.animateImageGroupProximityDrop(interaction);
  }

  function commitImageGroupProximity(interaction) {
    return canvasImageGroupInteraction.commitImageGroupProximity(interaction);
  }

  function alignSelection(action) {
    return canvasSelection.alignSelection(action);
  }

  function showSmartGuides(guides) {
    return canvasSelection.showSmartGuides(guides);
  }

  function renderMiniMap() {
    return canvasViewport.renderMiniMap();
  }

  function cssPxValue(element, propertyName, fallback = 0) {
    return canvasViewport.cssPxValue(element, propertyName, fallback);
  }

  function getMiniMapTargetHeight(controls, pinned) {
    return canvasViewport.getMiniMapTargetHeight(controls, pinned);
  }

  function dispatchMiniMapLayoutChange(pinned, controls) {
    return canvasViewport.dispatchMiniMapLayoutChange(pinned, controls);
  }

  function setMiniMapPinned(pinned) {
    return canvasViewport.setMiniMapPinned(pinned);
  }

  function getRectFromPoints(start, end) {
    return window.DesktopCanvasGeometry.getRectFromPoints(start, end);
  }

  function rectsIntersect(a, b) {
    return window.DesktopCanvasGeometry.rectsIntersect(a, b);
  }

  function selectNodesInRect(rect, save = false) {
    return canvasSelection.selectNodesInRect(rect, save);
  }

  function getMovedBounds(groupIds, positions, dx, dy) {
    return canvasSelection.getMovedBounds(groupIds, positions, dx, dy);
  }

  function resolveSnap(groupIds, positions, dx, dy, options = {}) {
    return canvasSelection.resolveSnap(groupIds, positions, dx, dy, options);
  }

  function offsetPointForPort(point, side, distance = CONNECTION_LEAD_LENGTH) {
    return window.DesktopCanvasGeometry.offsetPointForPort(point, side, distance);
  }

  function compactOrthogonalPoints(points) {
    return window.DesktopCanvasGeometry.compactOrthogonalPoints(points);
  }

  function roundedOrthogonalPath(points, radius = CONNECTION_CORNER_RADIUS) {
    return window.DesktopCanvasGeometry.roundedOrthogonalPath(points, radius);
  }

  function getBackwardConnectionDetourY(fromGeometry, toGeometry, fromLead, toLead) {
    return window.DesktopCanvasGeometry.getBackwardConnectionDetourY(fromGeometry, toGeometry, fromLead, toLead);
  }

  function makeSmoothStepPath(from, to, fromSide = 'right', toSide = 'left', route = null) {
    return window.DesktopCanvasGeometry.makeSmoothStepPath(from, to, fromSide, toSide, route);
  }

  function connectionLineStyle() {
    return canvasConnections.connectionLineStyle();
  }

  function portOutwardVector(side) {
    return window.DesktopCanvasGeometry.portOutwardVector(side);
  }

  function classicCurveControlOffset(axisDistance, crossDistance) {
    return window.DesktopCanvasGeometry.classicCurveControlOffset(axisDistance, crossDistance);
  }

  function makeClassicCurvePath(from, to, fromSide = 'right', toSide = 'left', route = null) {
    return window.DesktopCanvasGeometry.makeClassicCurvePath(from, to, fromSide, toSide, route);
  }

  function makeConnectionPath(from, to, fromSide = 'right', toSide = 'left', route = null) {
    return canvasConnections.makeConnectionPath(from, to, fromSide, toSide, route);
  }

  function ensureLiveConnectionPreviewPath(svg) {
    return canvasConnections.ensureLiveConnectionPreviewPath(svg);
  }

  function flushConnectionPreviewFrame() {
    return canvasConnections.flushConnectionPreviewFrame();
  }

  function scheduleConnectionPreviewFrame() {
    return canvasConnections.scheduleConnectionPreviewFrame();
  }

  function clearLiveConnectionPreview() {
    return canvasConnections.clearLiveConnectionPreview();
  }

  function renderConnectionPreview(fromNodeId, pointer, fromSide = 'right', fromAnchor = null) {
    return canvasConnections.renderConnectionPreview(fromNodeId, pointer, fromSide, fromAnchor);
  }

  function videoConfigApi() {
    return canvasModelNodes.videoConfigApi();
  }

  function migrateVideoInferenceNodeLayout(node = {}) {
    return canvasModelNodes.migrateVideoInferenceNodeLayout(node);
  }

  function normalizeVideoInferenceNodeState(node = {}) {
    return canvasModelNodes.normalizeVideoInferenceNodeState(node);
  }

  function nextNodeId(type) {
    return canvasNodes.nextNodeId(type);
  }

  function createNodeState(type) {
    return canvasNodes.createNodeState(type);
  }

  function createDefaultDirectorData() {
    return canvasNodes.createDefaultDirectorData();
  }

  function inputNodeHtml(nodeId) {
    return canvasModelNodes.inputNodeHtml(nodeId);
  }

  function comfyWorkflowCardsHtml(selectedWorkflow = '') {
    return canvasModelNodes.comfyWorkflowCardsHtml(selectedWorkflow);
  }

  function comfyWorkflowParameterOverrides(node, workflowId = node?.workflow || '') {
    return canvasModelNodes.comfyWorkflowParameterOverrides(node, workflowId);
  }

  function normalizeComfyPixelSize(value, fallback = DEFAULT_COMFY_PIXEL_WIDTH) {
    return canvasModelNodes.normalizeComfyPixelSize(value, fallback);
  }

  function comfyWorkflowDefaultSize(workflowMeta) {
    return canvasModelNodes.comfyWorkflowDefaultSize(workflowMeta);
  }

  function comfyParameterValueHtml(parameter, value) {
    return canvasModelNodes.comfyParameterValueHtml(parameter, value);
  }

  function comfyParameterPickerHtml(parameters, overrides) {
    return canvasModelNodes.comfyParameterPickerHtml(parameters, overrides);
  }

  function comfyWorkflowParametersHtml(node, workflowMeta) {
    return canvasModelNodes.comfyWorkflowParametersHtml(node, workflowMeta);
  }

  function comfyNodeHtml(node) {
    return canvasModelNodes.comfyNodeHtml(node);
  }

  function refreshComfyNode(nodeId) {
    return canvasModelNodes.refreshComfyNode(nodeId);
  }

  function loadComfyWorkflowCatalog() {
    return canvasModelNodes.loadComfyWorkflowCatalog(...arguments);
  }

  function videoInputRoleForSource(sourceType) {
    return canvasModelNodes.videoInputRoleForSource(sourceType);
  }

  function videoInferenceInputSummary(nodeId) {
    return canvasModelNodes.videoInferenceInputSummary(nodeId);
  }

  function videoRuntimePresentation() {
    return canvasModelNodes.videoRuntimePresentation();
  }

  function videoTaskTimerLabel(output = {}) {
    return canvasModelNodes.videoTaskTimerLabel(output);
  }

  function videoDurationOptions(node) {
    return canvasModelNodes.videoDurationOptions(node);
  }

  function videoAspectOptions() {
    return canvasModelNodes.videoAspectOptions();
  }

  function videoQualityOptions(node) {
    return canvasModelNodes.videoQualityOptions(node);
  }

  function videoAccelerationOptions() {
    return canvasModelNodes.videoAccelerationOptions();
  }

  function videoInferenceNodeHtml(rawNode) {
    return canvasModelNodes.videoInferenceNodeHtml(rawNode);
  }

  function videoNodeSource(node) {
    return canvasModelNodes.videoNodeSource(node);
  }

  function videoMediaAspectRatio(node) {
    return canvasModelNodes.videoMediaAspectRatio(node);
  }

  function fitVideoNodeToMedia(node, options = {}) {
    return canvasModelNodes.fitVideoNodeToMedia(node, options);
  }

  function formatVideoDuration(seconds) {
    return canvasModelNodes.formatVideoDuration(seconds);
  }

  function videoNodeHtml(node) {
    return canvasModelNodes.videoNodeHtml(node);
  }

  function refreshVideoInferenceNode(nodeId) {
    return canvasModelNodes.refreshVideoInferenceNode(nodeId);
  }

  function refreshVideoNode(nodeId) {
    return canvasModelNodes.refreshVideoNode(nodeId);
  }

  function syncVideoInferenceNodeStateFromDom(element) {
    return canvasModelNodes.syncVideoInferenceNodeStateFromDom(element);
  }

  function connectedVideoFirstFrame(nodeId) {
    return canvasGenerationConfig.connectedVideoFirstFrame(nodeId);
  }

  function readVideoInferenceNodeConfig(nodeId) {
    return canvasGenerationConfig.readVideoInferenceNodeConfig(nodeId);
  }

  function ensureVideoResultForInference(nodeId) {
    return canvasGeneration.ensureVideoResultForInference(nodeId);
  }

  function videoTaskOutputState(nodeId) {
    return canvasGeneration.videoTaskOutputState(nodeId);
  }

  function connectedVideoResultNodeId(nodeId) {
    return canvasGeneration.connectedVideoResultNodeId(nodeId);
  }

  function isVideoTaskTerminal(status) {
    return canvasGeneration.isVideoTaskTerminal(status);
  }

  function stopVideoTaskPolling(nodeId) {
    return canvasGeneration.stopVideoTaskPolling(nodeId);
  }

  function applyVideoTaskState(nodeId, task = {}, explicitResultId = '') {
    return canvasGeneration.applyVideoTaskState(nodeId, task, explicitResultId);
  }

  function scheduleVideoTaskPoll(nodeId, taskId, delay = 2000) {
    return canvasGeneration.scheduleVideoTaskPoll(nodeId, taskId, delay);
  }

  function pollVideoTask(nodeId, taskId) {
    return canvasGeneration.pollVideoTask(...arguments);
  }

  function cancelVideoInferenceTask(nodeId) {
    return canvasGeneration.cancelVideoInferenceTask(...arguments);
  }

  function runVideoInferenceNode(nodeId) {
    return canvasGeneration.runVideoInferenceNode(...arguments);
  }

  function restoreVideoTaskPolling() {
    return canvasGeneration.restoreVideoTaskPolling();
  }

  function loadVideoRuntimeContext() {
    return canvasGeneration.loadVideoRuntimeContext(...arguments);
  }

  function fileOutputNodeHtml(nodeId) {
    return canvasModelNodes.fileOutputNodeHtml(nodeId);
  }

  function upscaleNodeHtml(node) {
    return canvasModelNodes.upscaleNodeHtml(node);
  }

  function imageNodeSource(node) {
    return canvasNodes.imageNodeSource(node);
  }

  function imageGroupItemSource(item) {
    return canvasImageGroupModel.imageGroupItemSource(item);
  }

  function normalizeImageGroupItem(item = {}, index = 0) {
    return canvasImageGroupModel.normalizeImageGroupItem(item, index);
  }

  function normalizeImageGroupNodeState(node = {}) {
    return canvasImageGroupModel.normalizeImageGroupNodeState(node);
  }

  function createImageGroupItemFromNode(node, index = 0) {
    return canvasImageGroupModel.createImageGroupItemFromNode(node, index);
  }

  function normalizeImageSourceFromGroupItem(item, groupNode, index = 0) {
    return canvasImageGroupModel.normalizeImageSourceFromGroupItem(item, groupNode, index);
  }

  function imageGroupRoleOptionsHtml(selected) {
    return canvasImageGroupModel.imageGroupRoleOptionsHtml(selected);
  }

  function imageGroupItemHtml(groupNode, item, index) {
    return canvasImageGroupModel.imageGroupItemHtml(groupNode, item, index);
  }

  function imageGroupItemsHtml(groupNode) {
    return canvasImageGroupModel.imageGroupItemsHtml(groupNode);
  }

  function imageGroupGooeyBlobsHtml(groupNode) {
    return canvasImageGroupModel.imageGroupGooeyBlobsHtml(groupNode);
  }

  function imageGroupNodeHtml(node) {
    return canvasImageGroupModel.imageGroupNodeHtml(node);
  }

  function refreshImageGroupNode(groupId) {
    return canvasImageGroupModel.refreshImageGroupNode(groupId);
  }

  function listPromptImageNodes() {
    return canvasReferences.listPromptImageNodes();
  }

  function listPromptVideoNodes() {
    return canvasReferences.listPromptVideoNodes();
  }

  function listPromptMediaNodes() {
    return canvasReferences.listPromptMediaNodes();
  }

  function imageNodePlaceholderHtml() {
    return canvasNodes.imageNodePlaceholderHtml();
  }

  function imageNodeToolsHtml(node) {
    return canvasNodes.imageNodeToolsHtml(node);
  }

  function imageNodeHtml(node) {
    return canvasNodes.imageNodeHtml(node);
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
    return canvasImageEditorTools.getImageEditToolIcon(tool);
  }

  function getImageEditCursorUrl(imageUrl, hotspotX = 0, hotspotY = 0, fallback = 'crosshair') {
    return canvasImageEditorTools.getImageEditCursorUrl(imageUrl, hotspotX, hotspotY, fallback);
  }

  function getImageEditCursorAsset(tool) {
    return canvasImageEditorTools.getImageEditCursorAsset(tool);
  }

  function getImageEditShapeIcon(shape) {
    return canvasImageEditorTools.getImageEditShapeIcon(shape);
  }

  function textNodeHtml(node) {
    return canvasTextEditor.textNodeHtml(node);
  }

  function layoutNodeHtml(node) {
    return canvasNodes.layoutNodeHtml(node);
  }

  function getPoseInputImages(poseNodeId) {
    return canvasNodes.getPoseInputImages(poseNodeId);
  }

  function poseStatusText(node, preview, backgroundCount) {
    return canvasNodes.poseStatusText(node, preview, backgroundCount);
  }

  function poseDisplayTitle(node = {}, fallback = '姿态参考') {
    return canvasNodes.poseDisplayTitle(node, fallback);
  }

  function poseNodeHtml(node) {
    return canvasNodes.poseNodeHtml(node);
  }

  // floatingSwellStates is owned by DesktopCanvasPortInteraction.
  // floatingSwellFrameId is owned by DesktopCanvasPortInteraction.
  // floatingSwellLastFrame is owned by DesktopCanvasPortInteraction.

  function floatingSwellModulo(value, length) {
    return window.DesktopCanvasPortGeometry.floatingSwellModulo(value, length);
  }

  function floatingSwellShortestArcDelta(from, to, length) {
    return window.DesktopCanvasPortGeometry.floatingSwellShortestArcDelta(from, to, length);
  }

  function floatingSwellSmootherstep(value) {
    return window.DesktopCanvasPortGeometry.floatingSwellSmootherstep(value);
  }

  function floatingSwellSpringStep(spring, deltaSeconds) {
    return window.DesktopCanvasPortGeometry.floatingSwellSpringStep(spring, deltaSeconds);
  }

  function floatingSwellSpringAtRest(spring) {
    return window.DesktopCanvasPortGeometry.floatingSwellSpringAtRest(spring);
  }

  function buildFloatingSwellPerimeter(width, height, requestedRadius, offsetX = 0, offsetY = 0) {
    return window.DesktopCanvasPortGeometry.buildFloatingSwellPerimeter(width, height, requestedRadius, offsetX, offsetY);
  }

  function closestFloatingSwellSample(samples, x, y) {
    return window.DesktopCanvasPortGeometry.closestFloatingSwellSample(samples, x, y);
  }

  function floatingSwellPointAt(geometry, arcLength) {
    return window.DesktopCanvasPortGeometry.floatingSwellPointAt(geometry, arcLength);
  }

  function floatingSwellDisplacementAt(arcLength, center, peak, perimeterLength) {
    return window.DesktopCanvasPortGeometry.floatingSwellDisplacementAt(arcLength, center, peak, perimeterLength);
  }

  function appendFloatingSwellExactPath(commands, geometry, startS, from, to) {
    return window.DesktopCanvasPortGeometry.appendFloatingSwellExactPath(commands, geometry, startS, from, to);
  }

  function appendFloatingSwellActivePath(commands, geometry, center, peak, startS, from, to) {
    return window.DesktopCanvasPortGeometry.appendFloatingSwellActivePath(commands, geometry, center, peak, startS, from, to);
  }

  // The source interaction deforms the rounded-rectangle perimeter itself;
  // inactive spans remain exact lines/arcs and only the swell span is sampled.
  function buildFloatingSwellPath(geometry, center, peak) {
    return window.DesktopCanvasPortGeometry.buildFloatingSwellPath(geometry, center, peak);
  }

  function connectionSwellStyle() {
    return canvasPortInteraction.connectionSwellStyle();
  }

  function buildFloatingDropletProfile(geometry, center, positionVelocity) {
    return window.DesktopCanvasPortGeometry.buildFloatingDropletProfile(geometry, center, positionVelocity);
  }

  function floatingDropletPointAt(geometry, arcLength, peak, profile) {
    return window.DesktopCanvasPortGeometry.floatingDropletPointAt(geometry, arcLength, peak, profile);
  }

  function appendFloatingDropletActivePath(commands, geometry, peak, profile, startS, from, to) {
    return window.DesktopCanvasPortGeometry.appendFloatingDropletActivePath(commands, geometry, peak, profile, startS, from, to);
  }

  function buildFloatingDropletPath(geometry, center, peak, positionVelocity) {
    return window.DesktopCanvasPortGeometry.buildFloatingDropletPath(geometry, center, peak, positionVelocity);
  }

  function floatingSwellSide(point) {
    return window.DesktopCanvasPortGeometry.floatingSwellSide(point);
  }

  function floatingSwellBounds(nodeElement) {
    return canvasPortInteraction.floatingSwellBounds(nodeElement);
  }

  function updateFloatingSwellGeometry(state) {
    return canvasPortInteraction.updateFloatingSwellGeometry(state);
  }

  function ensureFloatingSwellState(nodeElement, floatingPort) {
    return canvasPortInteraction.ensureFloatingSwellState(nodeElement, floatingPort);
  }

  function floatingSwellConnectionAnchor(node, side, anchorX, anchorY) {
    return canvasPortInteraction.floatingSwellConnectionAnchor(node, side, anchorX, anchorY);
  }

  function syncFloatingDropletConnectionAnchor(state, side, anchorX, anchorY) {
    return canvasPortInteraction.syncFloatingDropletConnectionAnchor(state, side, anchorX, anchorY);
  }

  function renderFloatingSwellState(state) {
    return canvasPortInteraction.renderFloatingSwellState(state);
  }

  function renderReducedMotionFloatingSwells() {
    return canvasPortInteraction.renderReducedMotionFloatingSwells();
  }

  function animateFloatingSwells(timestamp) {
    return canvasPortInteraction.animateFloatingSwells(timestamp);
  }

  function scheduleFloatingSwellFrame() {
    return canvasPortInteraction.scheduleFloatingSwellFrame();
  }

  function refreshFloatingSwellStyle() {
    return canvasPortInteraction.refreshFloatingSwellStyle();
  }

  function setFloatingSwellTarget(state, sample, visible) {
    return canvasPortInteraction.setFloatingSwellTarget(state, sample, visible);
  }

  function releaseFloatingSwell(nodeElement) {
    return canvasPortInteraction.releaseFloatingSwell(nodeElement);
  }

  function holdFloatingSwell(floatingPort) {
    return canvasPortInteraction.holdFloatingSwell(floatingPort);
  }

  function discardFloatingSwellState(nodeElement) {
    return canvasPortInteraction.discardFloatingSwellState(nodeElement);
  }

  function ensureNodeEdgeHandles(nodeElement) {
    return canvasPortInteraction.ensureNodeEdgeHandles(nodeElement);
  }

  function syncNodeEdgeStroke(nodeElement) {
    return canvasPortInteraction.syncNodeEdgeStroke(nodeElement);
  }

  function clearFloatingConnectionPort(exceptNodeId = '') {
    return canvasPortInteraction.clearFloatingConnectionPort(exceptNodeId);
  }

  function updateFloatingConnectionPort(clientX, clientY) {
    return canvasPortInteraction.updateFloatingConnectionPort(clientX, clientY);
  }

  function getConnectionPortAnchor(nodeId, port, side = 'right') {
    return canvasPortInteraction.getConnectionPortAnchor(nodeId, port, side);
  }

  function nodeHtmlForState(nodeId, node) {
    return canvasNodes.nodeHtmlForState(nodeId, node);
  }

  function ensureGraphDom() {
    return canvasNodes.ensureGraphDom();
  }

  function screenToWorld(clientX, clientY) {
    return canvasViewport.screenToWorld(clientX, clientY);
  }

  function getViewportCenterWorldPoint(offsetX = 0, offsetY = 0) {
    return canvasViewport.getViewportCenterWorldPoint(offsetX, offsetY);
  }

  function getPrimaryModelNodeId() {
    return canvasViewport.getPrimaryModelNodeId();
  }

  function getPrimaryModelBounds() {
    return canvasViewport.getPrimaryModelBounds();
  }

  function centerCanvasOnBounds(bounds, scale = DesktopState.state.canvas.scale) {
    return canvasViewport.centerCanvasOnBounds(bounds, scale);
  }

  function centerCanvasOnPrimaryModel(scale = DesktopState.state.canvas.scale) {
    return canvasViewport.centerCanvasOnPrimaryModel(scale);
  }

  function setCanvasScale(nextScale, anchorClientX, anchorClientY, options = {}) {
    return canvasViewport.setCanvasScale(nextScale, anchorClientX, anchorClientY, options);
  }

  function setCanvasScaleCenteredOnPrimary(nextScale) {
    return canvasViewport.setCanvasScaleCenteredOnPrimary(nextScale);
  }

  function resetCanvasView() {
    return canvasViewport.resetCanvasView();
  }

  function setZoomPresetMenuOpen(open) {
    return canvasViewport.setZoomPresetMenuOpen(open);
  }

  function updateZoomPresetButtons() {
    return canvasViewport.updateZoomPresetButtons();
  }

  function toggleZoomPresetMenu() {
    return canvasViewport.toggleZoomPresetMenu();
  }

  function applyZoomPreset(scale) {
    return canvasViewport.applyZoomPreset(scale);
  }

  function resetNodeLayout() {
    return canvasNodes.resetNodeLayout();
  }

  function syncFormFromState() {
    return canvasModelNodes.syncFormFromState();
  }

  function setInputExpanded(expanded) {
    return canvasModelNodes.setInputExpanded(expanded);
  }

  function readFormToState() {
    return canvasModelNodes.readFormToState();
  }

  function readOutputControlsFromNode(node, fallback = {}) {
    return canvasModelNodes.readOutputControlsFromNode(node, fallback);
  }

  function syncInputNodeStateFromDom(node) {
    return canvasModelNodes.syncInputNodeStateFromDom(node);
  }

  function syncVisibleInputNodeStatesToCanvas() {
    return canvasModelNodes.syncVisibleInputNodeStatesToCanvas();
  }

  function readOutputControlsForTask(inputNodeId, resultNodeId = inputNodeId) {
    return canvasModelNodes.readOutputControlsForTask(inputNodeId, resultNodeId);
  }

  function syncOutputControlsToNodes(controls = DesktopState.state.output, options = {}) {
    return canvasModelNodes.syncOutputControlsToNodes(controls, options);
  }

  function syncOutputControlsFromNode(node) {
    return canvasModelNodes.syncOutputControlsFromNode(node);
  }

  function startPan(event) {
    const isLeftButton = event.button === 0;
    const isRightButton = event.button === 2;
    if (!isLeftButton && !isRightButton) return;
    if (canvasViewport.isWheelGestureActive()) finishCanvasWheelGesture();
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
    // We cancel native pointer focus, so explicitly leave the last node control
    // before starting a canvas gesture (including trackpad primary dragging).
    focusCanvasViewport();
    hideContextMenu();
    setZoomPresetMenuOpen(false);
    setWorkflowDockOpen(false);
    clearSelectedEdge();
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
    focusCanvasViewport();
    hideContextMenu();
    setZoomPresetMenuOpen(false);
    setWorkflowDockOpen(false);
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
    if (event.target.closest('button, input, select, [contenteditable="true"], [data-text-style-menu], [data-node-resize-handle], .desk-port')) return false;
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

  function shouldIgnoreNodeDragTarget(event) {
    const target = event.target;
    if (target.closest('button, input, textarea, select, audio, [contenteditable="true"]')) return true;
    const video = target.closest('video');
    if (!video) return Boolean(target.closest('[data-node-drag-ignore]'));
    const videoNode = video.closest('.desk-node--video');
    if (!videoNode) return true;

    const videoRect = video.getBoundingClientRect();
    const nodeRect = videoNode.getBoundingClientRect();
    const visibleTop = Math.max(videoRect.top, nodeRect.top);
    const visibleBottom = Math.min(videoRect.bottom, nodeRect.bottom);
    const visibleHeight = Math.max(0, visibleBottom - visibleTop);
    const nativeControlsHeight = Math.min(54, Math.max(36, visibleHeight * 0.14));
    return event.clientY >= visibleBottom - nativeControlsHeight;
  }

  function startNodeDrag(event, options = {}) {
    if (event.button !== 0) return;
    if (!options.force && shouldIgnoreNodeDragTarget(event)) return;
    const node = event.target.closest('.desk-node[data-node-id]');
    if (!node) return;
    canvasCollision.settle();
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
      lastClientX: event.clientX,
      lastClientY: event.clientY,
      nodeX: nodeState.x,
      nodeY: nodeState.y
    };
    node.classList.add('is-dragging');
    canvasCollision.begin(activeInteraction);
  }

  function startNodeResize(event) {
    if (event.button !== 0) return;
    const node = event.target.closest('.desk-node[data-node-id]');
    if (!node) return;
    canvasCollision.settle();
    const nodeState = getNodeState(node.dataset.nodeId);
    if (nodeState?.type === 'input') return;
    event.preventDefault();
    event.stopPropagation();
    clearFloatingConnectionPort();
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
      aspectRatio: resizeState.type === 'image'
        ? (resizeState.aspectRatio || (resizeState.width / Math.max(1, resizeState.height)))
        : (resizeState.type === 'video'
          ? videoMediaAspectRatio(resizeState)
          : (resizeState.width / Math.max(1, resizeState.height)))
    };
    node.classList.add('is-resizing');
  }

  function moveInteraction(event) {
    if (!activeInteraction) {
      updateFloatingConnectionPort(event.clientX, event.clientY);
      return;
    }
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
      scheduleCanvasPanTransform();
      return;
    }

    if (activeInteraction.type === 'connect') {
      activeInteraction.pointer = screenToWorld(event.clientX, event.clientY);
      renderConnectionPreview(
        activeInteraction.fromNodeId,
        activeInteraction.pointer,
        activeInteraction.fromSide,
        activeInteraction.fromAnchor
      );
      pendingConnectionDropPoint = { x: event.clientX, y: event.clientY };
      scheduleConnectionPreviewFrame();
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
      activeInteraction.lastClientX = event.clientX;
      activeInteraction.lastClientY = event.clientY;
      const rawDx = pointer.x - activeInteraction.startWorldX;
      const rawDy = pointer.y - activeInteraction.startWorldY;
      const snap = resolveSnap(activeInteraction.groupIds || [activeInteraction.nodeId], activeInteraction.nodePositions || {}, rawDx, rawDy, {
        excludeNodeIds: canvasCollision.displacedIds()
      });
      (activeInteraction.groupIds || [activeInteraction.nodeId]).forEach(nodeId => {
        const item = getNodeState(nodeId);
        const base = activeInteraction.nodePositions?.[nodeId];
        if (!item || !base) return;
        item.x = base.x + snap.dx;
        item.y = base.y + snap.dy;
        applyNodeLayout(nodeId, { deferGraph: true });
      });
      showSmartGuides(snap.guides);
      if (activeInteraction.imageGroupProximity?.ready) {
        hideSmartGuides();
        updateImageGroupProximity(activeInteraction);
      } else if (!activeInteraction.imageGroupProximityCooldown) {
        updateImageGroupProximity(activeInteraction);
      } else if (!findImageGroupProximityCandidate(activeInteraction, IMAGE_GROUP_PROXIMITY_RELEASE_PX)) {
        activeInteraction.imageGroupProximityCooldown = false;
      }
      canvasCollision.update(activeInteraction, { exemptNodeId: activeInteraction.imageGroupProximity?.targetNodeId });
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
      } else if (nodeState.type === 'comfy') {
        nodeState.width = clamp(activeInteraction.width + pointer.x - activeInteraction.startWorldX, MIN_COMFY_NODE_WIDTH, MAX_COMFY_NODE_WIDTH);
        nodeState.height = clamp(activeInteraction.height + pointer.y - activeInteraction.startWorldY, MIN_COMFY_NODE_HEIGHT, MAX_COMFY_NODE_HEIGHT);
      } else if (nodeState.type === 'video_inference') {
        nodeState.width = clamp(activeInteraction.width + pointer.x - activeInteraction.startWorldX, MIN_VIDEO_INFERENCE_NODE_WIDTH, MAX_VIDEO_INFERENCE_NODE_WIDTH);
        nodeState.height = clamp(activeInteraction.height + pointer.y - activeInteraction.startWorldY, MIN_VIDEO_INFERENCE_NODE_HEIGHT, MAX_VIDEO_INFERENCE_NODE_HEIGHT);
      } else if (nodeState.type === 'video') {
        const dx = pointer.x - activeInteraction.startWorldX;
        const dy = pointer.y - activeInteraction.startWorldY;
        const aspectRatio = Math.max(0.05, activeInteraction.aspectRatio || videoMediaAspectRatio(nodeState));
        const delta = Math.abs(dx) >= Math.abs(dy) ? dx : dy * aspectRatio;
        const minWidth = Math.max(MIN_VIDEO_NODE_WIDTH, MIN_VIDEO_NODE_HEIGHT * aspectRatio);
        const maxWidth = Math.min(MAX_VIDEO_NODE_WIDTH, MAX_VIDEO_NODE_HEIGHT * aspectRatio);
        nodeState.width = clamp(activeInteraction.width + delta, Math.min(minWidth, maxWidth), Math.max(minWidth, maxWidth));
        nodeState.height = nodeState.width / aspectRatio;
        nodeState.aspectRatio = aspectRatio;
      } else if (nodeState.type === 'input') {
        nodeState.width = LOCKED_INPUT_NODE_WIDTH;
        nodeState.height = LOCKED_INPUT_NODE_HEIGHT;
      } else {
        nodeState.width = clamp(activeInteraction.width + pointer.x - activeInteraction.startWorldX, MIN_NODE_WIDTH, MAX_NODE_WIDTH);
        nodeState.height = clamp(activeInteraction.height + pointer.y - activeInteraction.startWorldY, MIN_NODE_HEIGHT, MAX_NODE_HEIGHT);
      }
      applyNodeLayout(activeInteraction.nodeId, { deferGraph: true });
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
    const shouldAnimateImageGroupDrop = interaction.type === 'node-drag'
      && event?.type === 'pointerup'
      && interaction.imageGroupProximity?.ready
      && interaction.imageGroupProximity?.preview?.dropActive;
    const collisionPending = interaction.type === 'node-drag' && canvasCollision.end({
      cancelled: event?.type === 'pointercancel', immediate: Boolean(shouldAnimateImageGroupDrop)
    });
    if (interaction.type === 'pan') {
      canvasViewport.suppressClickAfterPan(event, interaction.moved);
      flushCanvasPanTransform();
    }
    if (interaction.type === 'node-drag' || interaction.type === 'node-resize') flushCanvasGraphRender();
    getNodeElement(interaction.nodeId)?.classList.remove('is-dragging', 'is-resizing');
    els.deskCanvasViewport?.classList.remove('is-panning');
    try {
      if (interaction.pointerId != null) {
        els.deskCanvasViewport?.releasePointerCapture?.(interaction.pointerId);
      }
    } catch {}
    hideSmartGuides();
    activeInteraction = null;
    if (shouldAnimateImageGroupDrop && animateImageGroupProximityDrop(interaction)) {
      return;
    }
    clearImageGroupProximity(interaction);
    if (!collisionPending) DesktopState.saveSettings();
    if (interaction.type === 'pan' && interaction.pointerButton === 'right') {
      suppressCanvasContextMenuUntil = Date.now() + CANVAS_CONTEXTMENU_SUPPRESS_MS;
      if (!interaction.moved && !interaction.startedOnNode && event?.type === 'pointerup') {
        openContextMenu(event);
      }
    }
  }

  function handleCanvasWheel(event) {
    return canvasViewport.handleCanvasWheel(event);
  }

  function renderReferenceThumbs() {
    return canvasReferences.renderReferenceThumbs();
  }

  function referenceSourceLabel(image) {
    return canvasReferences.referenceSourceLabel(image);
  }

  function openReferenceImage(image) {
    return canvasReferences.openReferenceImage(image);
  }

  function moveReference(nodeId, index, delta) {
    return canvasReferences.moveReference(nodeId, index, delta);
  }

  function removeReferenceAt(nodeId, index) {
    return canvasReferences.removeReferenceAt(nodeId, index);
  }

  function clearNodeReferences(nodeId) {
    return canvasReferences.clearNodeReferences(nodeId);
  }

  function renderReferenceItem(nodeId, image, index, total) {
    return canvasReferences.renderReferenceItem(nodeId, image, index, total);
  }

  function getProviderFromNode(node) {
    return canvasModelNodes.getProviderFromNode(node);
  }

  function getPromptModeFromNode(node, fallback = 'smart') {
    return canvasModelNodes.getPromptModeFromNode(node, fallback);
  }

  function applyPromptModeToNode(node, mode) {
    return canvasModelNodes.applyPromptModeToNode(node, mode);
  }

  function upgradeGptRouteControls(node) {
    return canvasModelNodes.upgradeGptRouteControls(node);
  }

  function applyGptTaskTypeToNode(node, taskType) {
    return canvasModelNodes.applyGptTaskTypeToNode(node, taskType);
  }

  function setTextStyleMenuOpen(node, open) {
    return canvasTextEditor.setTextStyleMenuOpen(node, open);
  }

  function closeAllTextStyleMenus(exceptNode = null) {
    return canvasTextEditor.closeAllTextStyleMenus(exceptNode);
  }

  function setTextNodeValue(node, nodeState, value) {
    return canvasTextEditor.setTextNodeValue(node, nodeState, value);
  }

  function createPromptBlockTokenElement(segment) {
    return canvasTextEditor.createPromptBlockTokenElement(segment);
  }

  function createImageReferenceTokenElement(segment) {
    return canvasTextEditor.createImageReferenceTokenElement(segment);
  }

  function isRangeInsidePromptEditor(range, editor) {
    return canvasTextEditor.isRangeInsidePromptEditor(range, editor);
  }

  function currentPromptEditorRange(editor) {
    return canvasTextEditor.currentPromptEditorRange(editor);
  }

  function promptEditorEndRange(editor) {
    return canvasTextEditor.promptEditorEndRange(editor);
  }

  function setPromptEditorCaret(range) {
    return canvasTextEditor.setPromptEditorCaret(range);
  }

  function imageMentionCandidateKey(reference = {}) {
    return canvasTextEditor.imageMentionCandidateKey(reference);
  }

  function textImageMentionCandidates(textNodeId) {
    return canvasTextEditor.textImageMentionCandidates(textNodeId);
  }

  function detectTextImageMention(editor) {
    return canvasTextEditor.detectTextImageMention(editor);
  }

  function closeTextImageMention(editor = null) {
    return canvasTextEditor.closeTextImageMention(editor);
  }

  function positionTextImageMentionMenu(state) {
    return canvasTextEditor.positionTextImageMentionMenu(state);
  }

  function renderTextImageMentionMenu(state) {
    return canvasTextEditor.renderTextImageMentionMenu(state);
  }

  function updateTextImageMention(editor) {
    return canvasTextEditor.updateTextImageMention(editor);
  }

  function setTextImageMentionActiveIndex(index) {
    return canvasTextEditor.setTextImageMentionActiveIndex(index);
  }

  function ensureTextNodeImageReferenceConnections(textNodeId, targetNodeId) {
    return canvasTextEditor.ensureTextNodeImageReferenceConnections(textNodeId, targetNodeId);
  }

  function insertTextImageMentionCandidate(candidateIndex = -1) {
    return canvasTextEditor.insertTextImageMentionCandidate(candidateIndex);
  }

  function handleTextImageMentionKeydown(event, editor) {
    return canvasTextEditor.handleTextImageMentionKeydown(event, editor);
  }

  function resolvePromptTokenEditor(options = {}) {
    return canvasTextEditor.resolvePromptTokenEditor(options);
  }

  function insertPromptBlockToken(block, options = {}) {
    return canvasTextEditor.insertPromptBlockToken(block, options);
  }

  function findPromptBlockTokenElement(instanceId) {
    return canvasTextEditor.findPromptBlockTokenElement(instanceId);
  }

  function replacePromptBlockToken(tokenOrInstance, block) {
    return canvasTextEditor.replacePromptBlockToken(tokenOrInstance, block);
  }

  function insertPlainTextIntoPromptEditor(editor, text) {
    return canvasTextEditor.insertPlainTextIntoPromptEditor(editor, text);
  }

  function adjacentPromptToken(range, editor, direction) {
    return canvasTextEditor.adjacentPromptToken(range, editor, direction);
  }

  function handlePromptEditorTokenDelete(event, editor) {
    return canvasTextEditor.handlePromptEditorTokenDelete(event, editor);
  }

  function updateTextStyleTag(node, nodeState) {
    return canvasTextEditor.updateTextStyleTag(node, nodeState);
  }

  function setTextNodeStyle(node, nodeState, presetId) {
    return canvasTextEditor.setTextNodeStyle(node, nodeState, presetId);
  }

  function selectTextNodePreset(node, nodeState, presetId) {
    return canvasTextEditor.selectTextNodePreset(node, nodeState, presetId);
  }

  function clearTextNodeStyle(node, nodeState) {
    return canvasTextEditor.clearTextNodeStyle(node, nodeState);
  }

  function ensureTextCopyFallback() {
    return canvasTextEditor.ensureTextCopyFallback();
  }

  function selectTextCopyFallback() {
    return canvasTextEditor.selectTextCopyFallback();
  }

  function showTextCopyFallback(text) {
    return canvasTextEditor.showTextCopyFallback(text);
  }

  function copyTextWithTemporaryTextarea(value) {
    return canvasTextEditor.copyTextWithTemporaryTextarea(value);
  }

  function copyTextToClipboardLocal(text, successMessage = undefined) {
    return canvasTextEditor.copyTextToClipboardLocal(...arguments);
  }

  function setPolishCopyButtonState(button, state) {
    return canvasTextEditor.setPolishCopyButtonState(button, state);
  }

  function ensureTextPolishModal() {
    return canvasTextEditor.ensureTextPolishModal();
  }

  function closeTextPolishModal() {
    return canvasTextEditor.closeTextPolishModal();
  }

  function getTextPolishVariantText(variant) {
    return canvasTextEditor.getTextPolishVariantText(variant);
  }

  function renderTextPolishModal() {
    return canvasTextEditor.renderTextPolishModal();
  }

  function applyTextPolishVariant(variant) {
    return canvasTextEditor.applyTextPolishVariant(variant);
  }

  function applyCurrentTextPolishVariant() {
    return canvasTextEditor.applyCurrentTextPolishVariant();
  }

  function createTextNodeFromPolishVariant() {
    return canvasTextEditor.createTextNodeFromPolishVariant();
  }

  function undoAppliedTextPolish() {
    return canvasTextEditor.undoAppliedTextPolish();
  }

  function openTextPolishModal(payload) {
    return canvasTextEditor.openTextPolishModal(payload);
  }

  function runTextNodeGptPolish(node, nodeState, triggerButton) {
    return canvasGeneration.runTextNodeGptPolish(...arguments);
  }

  function composePromptWithTextStyles(prompt, styleIds = []) {
    return canvasPromptDocument.composePromptWithTextStyles(prompt, styleIds);
  }

  function normalizeImageSourceFromNode(node) {
    return canvasReferences.normalizeImageSourceFromNode(node);
  }

  function normalizePoseReferenceFromNode(node) {
    return canvasReferences.normalizePoseReferenceFromNode(node);
  }

  function getLayoutInputImages(layoutNodeId) {
    return canvasNodes.getLayoutInputImages(layoutNodeId);
  }

  function getLayoutInputCount(layoutNodeId) {
    return canvasNodes.getLayoutInputCount(layoutNodeId);
  }

  function updateLayoutInputCount(nodeId) {
    return canvasNodes.updateLayoutInputCount(nodeId);
  }

  function getConnectedImageReferences(inputNodeId) {
    return canvasReferences.getConnectedImageReferences(inputNodeId);
  }

  function imageGroupRoleEntriesForTarget(targetNodeId) {
    return canvasImageGroupModel.imageGroupRoleEntriesForTarget(targetNodeId);
  }

  function imageGroupRolePromptBlock(targetNodeId) {
    return canvasImageGroupModel.imageGroupRolePromptBlock(targetNodeId);
  }

  function textNodeModelTargetIds(textNodeId) {
    return canvasTextEditor.textNodeModelTargetIds(textNodeId);
  }

  function mergeNodeReferenceImages(nodeId, directReferences = []) {
    return canvasReferences.mergeNodeReferenceImages(nodeId, directReferences);
  }

  function getConnectedTextNodes(inputNodeId) {
    return canvasPromptDocument.getConnectedTextNodes(inputNodeId);
  }

  function splitBatchPromptItems(prompt) {
    return canvasPromptDocument.splitBatchPromptItems(prompt);
  }

  function getBatchPromptItems(inputNodeId) {
    return canvasPromptDocument.getBatchPromptItems(inputNodeId);
  }

  function mergePromptWithConnectedText(prompt, inputNodeId) {
    return canvasPromptDocument.mergePromptWithConnectedText(prompt, inputNodeId);
  }

  function getVisibleInputPrompt(inputNodeId) {
    return canvasPromptDocument.getVisibleInputPrompt(inputNodeId);
  }

  function readInputNodeConfig(nodeId) {
    return canvasGenerationConfig.readInputNodeConfig(nodeId);
  }

  function readComfyNodeConfig(nodeId) {
    return canvasGenerationConfig.readComfyNodeConfig(nodeId);
  }

  function syncUpscaleNodeStateFromDom(node) {
    return canvasModelNodes.syncUpscaleNodeStateFromDom(node);
  }

  function getIncomingUpscaleEdges(nodeId, type = '') {
    return canvasModelNodes.getIncomingUpscaleEdges(nodeId, type);
  }

  function getOutgoingUpscaleImageEdges(nodeId) {
    return canvasModelNodes.getOutgoingUpscaleImageEdges(nodeId);
  }

  function isManualUpscaleFlow(nodeId) {
    return canvasModelNodes.isManualUpscaleFlow(nodeId);
  }

  function refreshUpscaleNodeMode(nodeId) {
    return canvasModelNodes.refreshUpscaleNodeMode(nodeId);
  }

  function updateUpscaleInputCount(nodeId) {
    return canvasModelNodes.updateUpscaleInputCount(nodeId);
  }

  function readUpscaleNodeConfigForReference(nodeId, firstRef, options = {}) {
    return canvasGenerationConfig.readUpscaleNodeConfigForReference(nodeId, firstRef, options);
  }

  function readUpscaleNodeConfig(nodeId) {
    return canvasGenerationConfig.readUpscaleNodeConfig(nodeId);
  }

  function findInputForResult(resultNodeId) {
    return canvasGenerationConfig.findInputForResult(resultNodeId);
  }

  function resolveResultNodeIdForRun(nodeId = 'input') {
    return canvasGenerationConfig.resolveResultNodeIdForRun(nodeId);
  }

  function readConfigForResult(resultNodeId) {
    if (getNodeState(resultNodeId)?.type === 'topaz') return canvasTopaz.readConfig(resultNodeId);
    return canvasGenerationConfig.readConfigForResult(resultNodeId);
  }

  function batchPromptItemsForConfig(config) {
    return canvasGenerationConfig.batchPromptItemsForConfig(config);
  }

  function imageCountForProvider(config) {
    return canvasGenerationConfig.imageCountForProvider(config);
  }

  function expectedImageOutputCount(config) {
    return canvasGenerationConfig.expectedImageOutputCount(config);
  }

  function getConnectedOutputImageNodeIds(modelNodeId) {
    return canvasGenerationConfig.getConnectedOutputImageNodeIds(modelNodeId);
  }

  function getConnectedUpscaleNodeIds(modelNodeId) {
    return canvasGenerationConfig.getConnectedUpscaleNodeIds(modelNodeId);
  }

  function getRunnableUpscaleNodeIds(modelNodeId) {
    return canvasGenerationConfig.getRunnableUpscaleNodeIds(modelNodeId);
  }

  function getOutputImageEdges(modelNodeId) {
    return canvasGenerationConfig.getOutputImageEdges(modelNodeId);
  }

  function isEmptyAutoOutputImageNode(node) {
    return canvasGenerationConfig.isEmptyAutoOutputImageNode(node);
  }

  function pruneExtraEmptyOutputImages(modelNodeId, keepCount) {
    return canvasGeneration.pruneExtraEmptyOutputImages(modelNodeId, keepCount);
  }

  function assignImageOutputSlots(modelNodeId) {
    return canvasGeneration.assignImageOutputSlots(modelNodeId);
  }

  function ratioToMeta(ratio = '1:1') {
    return canvasGenerationConfig.ratioToMeta(ratio);
  }

  function outputNodeCenterForSlot(modelNodeId, slotIndex, config) {
    return canvasGeneration.outputNodeCenterForSlot(modelNodeId, slotIndex, config);
  }

  function modelOutputPopOrigin(modelNodeId) {
    return canvasGeneration.modelOutputPopOrigin(modelNodeId);
  }

  function createOutputImageNode(modelNodeId, slotIndex, config) {
    return canvasGeneration.createOutputImageNode(modelNodeId, slotIndex, config);
  }

  function ensureImageOutputsForConfig(resultNodeId, config) {
    return canvasGeneration.ensureImageOutputsForConfig(resultNodeId, config);
  }

  function addNode(type, worldPoint) {
    return canvasNodes.addNode(type, worldPoint);
  }

  function normalizeNodeMenuType(type) {
    return canvasNodes.normalizeNodeMenuType(type);
  }

  function addNodeFromMenu(type, worldPoint) {
    return canvasNodes.addNodeFromMenu(type, worldPoint);
  }

  function removeNode(nodeId, options = {}) {
    return canvasNodes.removeNode(nodeId, options);
  }

  function connectNodes(fromNodeId, toNodeId, options = {}) {
    return canvasConnections.connectNodes(fromNodeId, toNodeId, options);
  }

  function handleRemovedEdges(removedEdges = []) {
    return canvasConnections.handleRemovedEdges(removedEdges);
  }

  function removeEdgesById(edgeIds = [], options = {}) {
    return canvasConnections.removeEdgesById(edgeIds, options);
  }

  function getDetachableIncomingEdge(toNodeId) {
    return canvasConnections.getDetachableIncomingEdge(toNodeId);
  }

  function clearConnectionDragVisuals() {
    return canvasConnections.clearConnectionDragVisuals();
  }

  function markCompatibleConnectionTargets(fromNodeId) {
    return canvasConnections.markCompatibleConnectionTargets(fromNodeId);
  }

  function updateConnectionDropTarget(clientX, clientY) {
    return canvasConnections.updateConnectionDropTarget(clientX, clientY);
  }

  function startConnectionDrag(event, button) {
    return canvasConnections.startConnectionDrag(event, button);
  }

  function startConnectionDetachDrag(event, button) {
    return canvasConnections.startConnectionDetachDrag(event, button);
  }

  function outputImageReference(output, index, sourceNodeId) {
    return canvasGenerationConfig.outputImageReference(output, index, sourceNodeId);
  }

  // upscaleComponentInstallPromise is owned by DesktopCanvasGeneration.

  function ensureUpscaleComponent(modelName) {
    return canvasGeneration.ensureUpscaleComponent(...arguments);
  }

  function submitUpscaleReference(upscaleNodeId, reference, options = undefined) {
    return canvasGeneration.submitUpscaleReference(...arguments);
  }

  function runUpscaleChainsForOutput(resultNodeId, output) {
    return Promise.all([canvasGeneration.runUpscaleChainsForOutput(...arguments), canvasTopaz.runChains(...arguments)]).then(counts => counts.reduce((a,b) => a+b,0));
  }

  function populateResultImageNodes(resultNodeId, output) {
    return canvasGeneration.populateResultImageNodes(...arguments);
  }

  function refreshLayoutNode(nodeId) {
    return canvasNodes.refreshLayoutNode(nodeId);
  }

  function refreshPoseNode(nodeId) {
    return canvasNodes.refreshPoseNode(nodeId);
  }

  function connectPoseToDefaultInput(nodeId) {
    return canvasNodes.connectPoseToDefaultInput(nodeId);
  }

  function finishConnectionDrag(event) {
    return canvasConnections.finishConnectionDrag(event);
  }

  function toggleNodeDrawer(node) {
    return canvasNodes.toggleNodeDrawer(node);
  }

  function fileToDataUrl(file) {
    return canvasMediaImport.fileToDataUrl(file);
  }

  function readImageMeta(dataUrl) {
    return canvasMediaImport.readImageMeta(dataUrl);
  }

  function readImageMetaStrict(dataUrl, filename = '') {
    return canvasMediaImport.readImageMetaStrict(dataUrl, filename);
  }

  function localImageExtension(filename = '') {
    return canvasMediaImport.localImageExtension(filename);
  }

  function localImageMimeFromName(filename = '') {
    return canvasMediaImport.localImageMimeFromName(filename);
  }

  function localImageFilename(file, mimeType, fallbackPrefix = '图片') {
    return canvasMediaImport.localImageFilename(file, mimeType, fallbackPrefix);
  }

  function sniffLocalImageMime(blob) {
    return canvasMediaImport.sniffLocalImageMime(...arguments);
  }

  function prepareLocalImageFile(file, fallbackPrefix = undefined) {
    return canvasMediaImport.prepareLocalImageFile(...arguments);
  }

  function imageUrlToDataUrl(url) {
    return canvasMediaImport.imageUrlToDataUrl(...arguments);
  }

  function refreshImageNode(nodeId) {
    return canvasNodes.refreshImageNode(nodeId);
  }

  function refreshImageNodeContent(nodeId) {
    return canvasNodes.refreshImageNodeContent(nodeId);
  }

  function ensureImageEditor() {
    return canvasImageEditor.ensureImageEditor();
  }

  function getImageEditorCanvasElement() {
    return canvasImageEditor.getImageEditorCanvasElement();
  }

  function getImageEditorCanvas() {
    return canvasImageEditor.getImageEditorCanvas();
  }

  function getImageEditorCanvasShell() {
    return canvasImageEditor.getImageEditorCanvasShell();
  }

  function getImageEditorCanvasWrap() {
    return canvasImageEditor.getImageEditorCanvasWrap();
  }

  function applyImageEditCanvasPanOffset(x = 0, y = 0) {
    return canvasImageEditor.applyImageEditCanvasPanOffset(x, y);
  }

  function clampImageEditZoom(value, fallback = 1) {
    return canvasImageEditor.clampImageEditZoom(value, fallback);
  }

  function getImageEditDisplaySize(width, height) {
    return canvasImageEditor.getImageEditDisplaySize(width, height);
  }

  function getImageEditCanvasCssScale(canvas = getImageEditorCanvas()) {
    return canvasImageEditor.getImageEditCanvasCssScale(canvas);
  }

  function getImageEditViewportCenter(canvas = getImageEditorCanvas()) {
    return canvasImageEditor.getImageEditViewportCenter(canvas);
  }

  function clampImageEditViewportTransform(canvas, transform) {
    return canvasImageEditor.clampImageEditViewportTransform(canvas, transform);
  }

  function applyImageEditViewportZoom(canvas, viewportZoom, center = null) {
    return canvasImageEditor.applyImageEditViewportZoom(canvas, viewportZoom, center);
  }

  function refreshImageEditObjectControls() {
    return canvasImageEditor.refreshImageEditObjectControls();
  }

  function updateImageEditZoomUi() {
    return canvasImageEditor.updateImageEditZoomUi();
  }

  function applyImageEditCanvasDisplaySize(canvas, width, height, options = {}) {
    return canvasImageEditor.applyImageEditCanvasDisplaySize(canvas, width, height, options);
  }

  function setImageEditZoom(value, mode = 'manual') {
    return canvasImageEditor.setImageEditZoom(value, mode);
  }

  function getImageEditCanvasDisplayScale(canvas = getImageEditorCanvas()) {
    return canvasImageEditor.getImageEditCanvasDisplayScale(canvas);
  }

  function imageEditScreenToCanvasSize(value, canvas = getImageEditorCanvas()) {
    return canvasImageEditor.imageEditScreenToCanvasSize(value, canvas);
  }

  function applyImageEditObjectControls(object, color = '') {
    return canvasImageEditorTools.applyImageEditObjectControls(object, color);
  }

  function getImageEditHexColor(color) {
    return canvasImageEditorTools.getImageEditHexColor(color);
  }

  function firstImageEditHexColor(...colors) {
    return canvasImageEditorTools.firstImageEditHexColor(...colors);
  }

  function getImageEditObjectColor(object) {
    return canvasImageEditorTools.getImageEditObjectColor(object);
  }

  function getImageEditSelectedObjects(canvas = getImageEditorCanvas()) {
    return canvasImageEditorTools.getImageEditSelectedObjects(canvas);
  }

  function setImageEditPinColor(pin, color) {
    return canvasImageEditorTools.setImageEditPinColor(pin, color);
  }

  function imageEditObjectColorSignature(object) {
    return canvasImageEditorTools.imageEditObjectColorSignature(object);
  }

  function setImageEditObjectColor(object, color) {
    return canvasImageEditorTools.setImageEditObjectColor(object, color);
  }

  function setImageEditSelectedObjectsColor(color) {
    return canvasImageEditorTools.setImageEditSelectedObjectsColor(color);
  }

  function syncImageEditColorFromSelection() {
    return canvasImageEditorTools.syncImageEditColorFromSelection();
  }

  function handleImageEditSelectionChange() {
    return canvasImageEditorTools.handleImageEditSelectionChange();
  }

  function getImageEditorPromptInput() {
    return canvasImageEditor.getImageEditorPromptInput();
  }

  function getImageEditorStatusEl() {
    return canvasImageEditor.getImageEditorStatusEl();
  }

  function getImageEditorSourceEl() {
    return canvasImageEditor.getImageEditorSourceEl();
  }

  function getImageEditCustomProps() {
    return canvasImageEditor.getImageEditCustomProps();
  }

  function cloneImageEditValue(value) {
    return canvasImageEditor.cloneImageEditValue(value);
  }

  function createImageEditId(prefix = 'image-edit') {
    return canvasImageEditor.createImageEditId(prefix);
  }

  function sanitizeImageEditFilename(name, fallback = 'image-edit') {
    return canvasImageEditor.sanitizeImageEditFilename(name, fallback);
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
    return canvasWorkflow.normalizeWorkflowReference(ref);
  }

  function normalizeWorkflowReferences(refs) {
    return canvasWorkflow.normalizeWorkflowReferences(refs);
  }

  function normalizeWorkflowReferenceMap(map) {
    return canvasWorkflow.normalizeWorkflowReferenceMap(map);
  }

  function normalizeWorkflowParams(params = {}, fallback = DesktopState.state.params || {}) {
    return canvasWorkflow.normalizeWorkflowParams(params, fallback);
  }

  function normalizeWorkflowNode(node, nodeId) {
    return canvasWorkflow.normalizeWorkflowNode(node, nodeId);
  }

  function normalizeWorkflowCanvas(canvas = {}) {
    return canvasWorkflow.normalizeWorkflowCanvas(canvas);
  }

  function normalizeWorkflowOutput(output = {}) {
    return canvasWorkflow.normalizeWorkflowOutput(output);
  }

  function normalizeWorkflowOutputs(outputs = {}) {
    return canvasWorkflow.normalizeWorkflowOutputs(outputs);
  }

  function extractWorkflowState(payload = {}) {
    return canvasWorkflow.extractWorkflowState(payload);
  }

  function revokeWorkflowReferenceUrls(refs) {
    return canvasWorkflow.revokeWorkflowReferenceUrls(refs);
  }

  function revokeCurrentWorkflowObjectUrls() {
    return canvasWorkflow.revokeCurrentWorkflowObjectUrls();
  }

  function buildWorkflowSnapshot() {
    return canvasWorkflow.buildWorkflowSnapshot();
  }

  function workflowTitleFromSnapshot(snapshot) {
    return canvasWorkflow.workflowTitleFromSnapshot(snapshot);
  }

  function workflowTimestamp() {
    return canvasWorkflow.workflowTimestamp();
  }

  function normalizeWorkflowFilename(name, fallback = 'canvas-workflow') {
    return canvasWorkflow.normalizeWorkflowFilename(name, fallback);
  }

  function defaultWorkflowFilename(payload) {
    return canvasWorkflow.defaultWorkflowFilename(payload);
  }

  function defaultWorkflowSavePath(filename) {
    return canvasWorkflow.defaultWorkflowSavePath(filename);
  }

  function chooseWorkflowSaveFile(blob, filename) {
    return canvasWorkflow.chooseWorkflowSaveFile(...arguments);
  }

  function saveWorkflowToCustomPath(payload, filename) {
    return canvasWorkflow.saveWorkflowToCustomPath(...arguments);
  }

  function exportWorkflowSnapshot() {
    return canvasWorkflow.exportWorkflowSnapshot();
  }

  function saveWorkflowFile() {
    return canvasWorkflow.saveWorkflowFile(...arguments);
  }

  function applyWorkflowSnapshot(payload, options = {}) {
    const next = extractWorkflowState(payload);
    if (options.confirm !== false && window.confirm && !window.confirm('加载工作流会替换当前画布，继续？')) {
      return false;
    }
    canvasCollision.cancel();
    canvasProgress.clear();
    if (activeInteraction?.type === 'node-drag') {
      clearImageGroupProximity(activeInteraction);
      activeInteraction = null;
    }
    canvasAudio.disposeAll();
    canvasMusic.disposeAll();
    canvasVideoControl.disposeAll(true);
    canvasTopazVideo.disposeAll(true);
    canvasCyimg.disposeAll();
    canvasKrea2.disposeAll(); canvasQwen21.disposeAll();
    revokeCurrentWorkflowObjectUrls();
    promptDocumentHistories.clear();
    promptDocumentVersions.clear();
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
    DesktopState.saveSettings({ criticalCanvas: true });
    DesktopState.saveDraft();
    DesktopResults.renderIdleProviderHint?.();
    DesktopResults.showTransientMessage('工作流已加载。');
    return true;
  }

  function readWorkflowFile(file) {
    return canvasWorkflow.readWorkflowFile(file);
  }

  function loadWorkflowFile(file, options = undefined) {
    return canvasWorkflow.loadWorkflowFile(...arguments);
  }

  function normalizeImageEditColor(color) {
    return canvasImageEditorTools.normalizeImageEditColor(color);
  }

  function getImageEditState() {
    return canvasImageEditor.getImageEditState();
  }

  function setImageEditStatus(message = '就绪', tone = 'info') {
    return canvasImageEditor.setImageEditStatus(message, tone);
  }

  function updateImageEditSourceLabel() {
    return canvasImageEditor.updateImageEditSourceLabel();
  }

  function updateImageEditUndoRedoButtons() {
    return canvasImageEditor.updateImageEditUndoRedoButtons();
  }

  function isImageEditDarkTheme() {
    return canvasImageEditor.isImageEditDarkTheme();
  }

  function syncImageEditToolIconFilters() {
    return canvasImageEditor.syncImageEditToolIconFilters();
  }

  function ensureImageEditorThemeObserver() {
    return canvasImageEditor.ensureImageEditorThemeObserver();
  }

  function updateImageEditToolUi() {
    return canvasImageEditor.updateImageEditToolUi();
  }

  function getImageEditObjects(role = '') {
    return canvasImageEditorTools.getImageEditObjects(role);
  }

  function removeImageEditObjects(objects = []) {
    return canvasImageEditorTools.removeImageEditObjects(objects);
  }

  function createImageEditTextStyle(color) {
    return canvasImageEditorTools.createImageEditTextStyle(color);
  }

  function getImageEditShapeMode(state = getImageEditState()) {
    return canvasImageEditorTools.getImageEditShapeMode(state);
  }

  function isImageEditShapeFilled(shapeMode) {
    return canvasImageEditorTools.isImageEditShapeFilled(shapeMode);
  }

  function isImageEditShapeEllipse(shapeMode) {
    return canvasImageEditorTools.isImageEditShapeEllipse(shapeMode);
  }

  function imageEditShapeKind(shapeMode) {
    return canvasImageEditorTools.imageEditShapeKind(shapeMode);
  }

  function createImageEditShape(start, color, strokeWidth, shapeMode = 'rectOutline') {
    return canvasImageEditorTools.createImageEditShape(start, color, strokeWidth, shapeMode);
  }

  function createImageEditRect(start, color, strokeWidth, shapeMode = 'rectOutline') {
    return canvasImageEditorTools.createImageEditRect(start, color, strokeWidth, shapeMode);
  }

  function createImageEditEllipse(start, color, strokeWidth, shapeMode = 'ellipseOutline') {
    return canvasImageEditorTools.createImageEditEllipse(start, color, strokeWidth, shapeMode);
  }

  function buildImageEditArrowPath(start, end, strokeWidth) {
    return canvasImageEditorTools.buildImageEditArrowPath(start, end, strokeWidth);
  }

  function createImageEditArrow(start, end, color, strokeWidth) {
    return canvasImageEditorTools.createImageEditArrow(start, end, color, strokeWidth);
  }

  function updateImageEditArrow(arrow, start, end, color, strokeWidth) {
    return canvasImageEditorTools.updateImageEditArrow(arrow, start, end, color, strokeWidth);
  }

  function createImageEditPin(point, color, label) {
    return canvasImageEditorTools.createImageEditPin(point, color, label);
  }

  function setImageEditObjectMeta(object, role, kind, tool = '') {
    return canvasImageEditorTools.setImageEditObjectMeta(object, role, kind, tool);
  }

  function getImageEditPinNumber() {
    return canvasImageEditorTools.getImageEditPinNumber();
  }

  function serializeImageEditObject(object) {
    return canvasImageEditor.serializeImageEditObject(object);
  }

  function serializeImageEditCanvas() {
    return canvasImageEditor.serializeImageEditCanvas();
  }

  function buildImageEditProjectJson(state = getImageEditState()) {
    return canvasImageEditor.buildImageEditProjectJson(state);
  }

  function createImageEditSnapshot(state = getImageEditState()) {
    return canvasImageEditor.createImageEditSnapshot(state);
  }

  function imageEditSnapshotKey(snapshot) {
    return canvasImageEditor.imageEditSnapshotKey(snapshot);
  }

  function resetImageEditHistory(snapshot = null) {
    return canvasImageEditor.resetImageEditHistory(snapshot);
  }

  function recordImageEditSnapshot(label = '') {
    return canvasImageEditor.recordImageEditSnapshot(label);
  }

  function loadFabricImage(src) {
    return canvasImageEditor.loadFabricImage(...arguments);
  }

  function loadImageEditSource(sourceDataUrl, width, height, overlayJson = undefined, legacyMaskDataUrl = undefined) {
    return canvasImageEditor.loadImageEditSource(...arguments);
  }

  function restoreImageEditSnapshot(snapshot) {
    return canvasImageEditor.restoreImageEditSnapshot(...arguments);
  }

  function ensureImageEditFabricCanvas() {
    return canvasImageEditor.ensureImageEditFabricCanvas();
  }

  function setImageEditTool(tool) {
    return canvasImageEditorTools.setImageEditTool(tool);
  }

  function getImageEditCursor(tool, state = getImageEditState()) {
    return canvasImageEditorTools.getImageEditCursor(tool, state);
  }

  function applyImageEditCursor(canvas, tool, state = getImageEditState()) {
    return canvasImageEditorTools.applyImageEditCursor(canvas, tool, state);
  }

  function getImageEditShapeLabel(shapeMode) {
    return canvasImageEditorTools.getImageEditShapeLabel(shapeMode);
  }

  function setImageEditShapeMode(shapeMode) {
    return canvasImageEditorTools.setImageEditShapeMode(shapeMode);
  }

  function setImageEditColor(color) {
    return canvasImageEditorTools.setImageEditColor(color);
  }

  function setImageEditBrushSize(value) {
    return canvasImageEditorTools.setImageEditBrushSize(value);
  }

  function exportImageEditAnnotatedDataUrl() {
    return canvasImageEditor.exportImageEditAnnotatedDataUrl(...arguments);
  }

  function exportImageEditAnnotatedToNode() {
    return canvasImageEditor.exportImageEditAnnotatedToNode(...arguments);
  }

  function exportImageEditMaskDataUrl(state = undefined) {
    return canvasImageEditor.exportImageEditMaskDataUrl(...arguments);
  }

  function clearImageEditorMask() {
    return canvasImageEditor.clearImageEditorMask();
  }

  function clearImageEditorAnnotations() {
    return canvasImageEditor.clearImageEditorAnnotations();
  }

  function closeImageEditor() {
    return canvasImageEditor.closeImageEditor();
  }

  function saveImageEditState(editState = undefined) {
    return canvasImageEditor.saveImageEditState(...arguments);
  }

  function buildImageEditPrompt(note, hasMask) {
    return canvasImageEditor.buildImageEditPrompt(note, hasMask);
  }

  function openImageEditor(nodeId) {
    return canvasImageEditor.openImageEditor(...arguments);
  }

  function clearImageEditorStatusToDefault() {
    return canvasImageEditor.clearImageEditorStatusToDefault();
  }

  function restoreImageEditSnapshotFromState(state, snapshot) {
    return canvasImageEditor.restoreImageEditSnapshotFromState(...arguments);
  }

  function bindImageEditorEvents(modal) {
    return canvasImageEditor.bindImageEditorEvents(modal);
  }

  function submitImageEditor() {
    return canvasGeneration.submitImageEditor(...arguments);
  }

  function getImageNodeSize(meta) {
    return canvasMediaImport.getImageNodeSize(meta);
  }

  function getImageNodeCenter(clientX, clientY) {
    return canvasMediaImport.getImageNodeCenter(clientX, clientY);
  }

  function triggerImageNodePopIn(nodeId, index = 0, options = {}) {
    return canvasMediaImport.triggerImageNodePopIn(nodeId, index, options);
  }

  function insertImageNode(source, center, options = {}) {
    return canvasMediaImport.insertImageNode(source, center, options);
  }

  function createImageNodeFromFiles(files, center = undefined, options = undefined) {
    return canvasMediaImport.createImageNodeFromFiles(...arguments);
  }

  function createImageNodesFromFiles(files, clientX, clientY, options = undefined) {
    return canvasMediaImport.createImageNodesFromFiles(...arguments);
  }

  function externalImageNameFromUrl(source) {
    return canvasMediaImport.externalImageNameFromUrl(source);
  }

  function prepareExternalImageSource(source, fallbackPrefix = undefined) {
    return canvasMediaImport.prepareExternalImageSource(...arguments);
  }

  function createImageNodesFromExternalSources(sources, clientX, clientY, options = undefined) {
    return canvasMediaImport.createImageNodesFromExternalSources(...arguments);
  }

  function addExternalImageSourcesToNode(nodeId, sources, options = undefined) {
    return canvasMediaImport.addExternalImageSourcesToNode(...arguments);
  }

  function replaceImageNodeFromFiles(nodeId, files) {
    return canvasMediaImport.replaceImageNodeFromFiles(...arguments);
  }

  function setImageNodeFromResult(nodeId, resultNodeId, output, index = undefined) {
    return canvasMediaImport.setImageNodeFromResult(...arguments);
  }

  function createImageNodeFromResult(resultNodeId = undefined, index = undefined) {
    return canvasMediaImport.createImageNodeFromResult(...arguments);
  }

  function createImageNodeFromHistoryItem(item, clientX, clientY) {
    return canvasMediaImport.createImageNodeFromHistoryItem(...arguments);
  }

  function continueEditFromHistoryItem(item, clientX, clientY) {
    return canvasMediaImport.continueEditFromHistoryItem(...arguments);
  }

  function attachHistoryImageToLayout(item, layoutNodeId) {
    return canvasReferences.attachHistoryImageToLayout(...arguments);
  }

  function addFiles(files) {
    return canvasMediaImport.addFiles(...arguments);
  }

  function getNodeReferenceImages(nodeId) {
    return canvasReferences.getNodeReferenceImages(nodeId);
  }

  function findDefaultInputNodeId() {
    return canvasReferences.findDefaultInputNodeId();
  }

  function referenceFromHistoryItem(item) {
    return canvasReferences.referenceFromHistoryItem(item);
  }

  function addReferenceItemsToNode(nodeId, items) {
    return canvasReferences.addReferenceItemsToNode(nodeId, items);
  }

  function attachHistoryImagesToInput(items, inputNodeId = undefined) {
    return canvasReferences.attachHistoryImagesToInput(...arguments);
  }

  function providerFromAsset(asset, fallback = 'gpt') {
    return canvasReferences.providerFromAsset(asset, fallback);
  }

  function firstParam(asset, keys) {
    return canvasReferences.firstParam(asset, keys);
  }

  function extractAssetModelConfig(asset, fallbackParams = DesktopState.state.params) {
    return canvasReferences.extractAssetModelConfig(asset, fallbackParams);
  }

  function shouldOverwritePrompt(currentPrompt, nextPrompt) {
    return canvasReferences.shouldOverwritePrompt(currentPrompt, nextPrompt);
  }

  function applyProviderToNode(node, provider) {
    return canvasReferences.applyProviderToNode(node, provider);
  }

  function applyAssetConfigToInput(asset, options = {}) {
    return canvasReferences.applyAssetConfigToInput(asset, options);
  }

  function getThumbWrapForNode(nodeId) {
    return canvasReferences.getThumbWrapForNode(nodeId);
  }

  function renderNodeReferenceThumbs(nodeId) {
    return canvasReferences.renderNodeReferenceThumbs(nodeId);
  }

  function addFilesToNode(nodeId, files) {
    return canvasMediaImport.addFilesToNode(...arguments);
  }

  function isLocalImageFile(file) {
    return canvasMediaImport.isLocalImageFile(file);
  }

  function hasLocalFileDragPayload(dataTransfer) {
    return canvasMediaImport.hasLocalFileDragPayload(dataTransfer);
  }

  function hasLocalImageDragPayload(dataTransfer) {
    return canvasMediaImport.hasLocalImageDragPayload(dataTransfer);
  }

  function getLocalDragFiles(dataTransfer) {
    return canvasMediaImport.getLocalDragFiles(dataTransfer);
  }

  function hasExternalImageTextDragPayload(dataTransfer) {
    return canvasMediaImport.hasExternalImageTextDragPayload(dataTransfer);
  }

  function hasExternalImageDragPayload(dataTransfer) {
    return canvasMediaImport.hasExternalImageDragPayload(dataTransfer);
  }

  function readDroppedString(dataTransfer, mimeType) {
    return canvasMediaImport.readDroppedString(dataTransfer, mimeType);
  }

  function normalizeExternalImageUrl(value, allowRelative = false) {
    return canvasMediaImport.normalizeExternalImageUrl(value, allowRelative);
  }

  function imageSourcesFromHtml(html) {
    return canvasMediaImport.imageSourcesFromHtml(html);
  }

  function getExternalImageSources(dataTransfer) {
    return canvasMediaImport.getExternalImageSources(...arguments);
  }

  function captureExternalImageTransfer(dataTransfer) {
    return canvasMediaImport.captureExternalImageTransfer(dataTransfer);
  }

  function importCapturedImages(captured, options = undefined) {
    return canvasMediaImport.importCapturedImages(...arguments);
  }

  function hasClipboardImagePayload(dataTransfer) {
    return canvasMediaImport.hasClipboardImagePayload(dataTransfer);
  }

  function isEditablePasteTarget(target) {
    return canvasMediaImport.isEditablePasteTarget(target);
  }

  function handleCanvasImagePaste(event) {
    return canvasMediaImport.handleCanvasImagePaste(event);
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
    return canvasMediaImport.hasHistoryDragPayload(dataTransfer);
  }

  function hasGalleryDragPayload(dataTransfer) {
    return canvasMediaImport.hasGalleryDragPayload(dataTransfer);
  }

  function getHistoryDragPayload(dataTransfer) {
    return canvasMediaImport.getHistoryDragPayload(dataTransfer);
  }

  function getGalleryDragPayload(dataTransfer) {
    return canvasMediaImport.getGalleryDragPayload(dataTransfer);
  }

  function findDefaultLayoutNodeId() {
    return canvasReferences.findDefaultLayoutNodeId();
  }

  function attachHistoryImagesToLayout(items, layoutNodeId = undefined) {
    return canvasReferences.attachHistoryImagesToLayout(...arguments);
  }

  function createImageNodesFromHistoryItems(items, clientX, clientY) {
    return canvasMediaImport.createImageNodesFromHistoryItems(...arguments);
  }

  function createVideoNodeFromAsset(item, clientX, clientY) {
    return canvasMediaImport.createVideoNodeFromAsset(item, clientX, clientY);
  }

  function hasAddNodeDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('application/x-desktop-add-node');
  }

  function activateImageGroupReferenceItem(activeItem) {
    return canvasImageGroupInteraction.activateImageGroupReferenceItem(activeItem);
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
    bindLinkLayerInteractions();
    document.addEventListener('pointerdown', event => {
      if (els.deskCanvasViewport?.contains(event.target)) {
        lastCanvasPointer = { x: event.clientX, y: event.clientY };
      } else {
        lastCanvasPointer = null;
      }
    }, true);
    els.deskCanvasViewport?.addEventListener('pointermove', event => {
      lastCanvasPointer = { x: event.clientX, y: event.clientY };
    });
    els.deskCanvasWorld?.addEventListener('pointerover', event => {
      const item = event.target.closest?.('.desk-node--image-group [data-image-group-item]');
      if (!item || (event.relatedTarget && item.contains(event.relatedTarget))) return;
      activateImageGroupReferenceItem(item);
    });
    document.addEventListener('paste', handleCanvasImagePaste);
    document.querySelectorAll('.desk-rail__item[data-tool]').forEach(button => {
      button.addEventListener('click', () => {
        clearSelectedEdge();
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
          if (window.DesktopPromptLibrary?.close?.() === false) {
            document.querySelectorAll('.desk-rail__item[data-tool]').forEach(item => item.classList.toggle('is-active', item.dataset.tool === 'prompts'));
            return;
          }
          window.DesktopSettings?.close?.();
          window.DesktopHistory?.openGallery?.().catch(error => DesktopResults.showError(error));
          return;
        }
        if (tool === 'prompts') {
          setNodePaletteOpen(false);
          window.DesktopPromptLibrary?.open?.().catch(error => DesktopResults.showError(error));
          return;
        }
        if (tool === 'settings') {
          setNodePaletteOpen(false);
          if (window.DesktopPromptLibrary?.close?.() === false) {
            document.querySelectorAll('.desk-rail__item[data-tool]').forEach(item => item.classList.toggle('is-active', item.dataset.tool === 'prompts'));
            return;
          }
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
    els.deskNodePalette?.addEventListener('dragstart', event => {
      const button = event.target.closest('[data-add-node]');
      if (!button) return;
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData('application/x-desktop-add-node', JSON.stringify({
        type: button.dataset.addNode || 'input'
      }));
    });

    document.addEventListener('pointerdown', event => {
      if (activeTextImageMention
        && !activeTextImageMention.menu?.contains(event.target)
        && !activeTextImageMention.editor?.contains(event.target)) {
        closeTextImageMention();
      }
      if (event.target.closest('#deskNodePalette, #deskNodeContextMenu, #deskNodeToolBtn, #deskEdgeMenu, [data-edge-interaction]')) return;
      clearSelectedEdge();
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
      const imageMentionButton = event.target.closest('[data-text-image-mention-pick]');
      if (imageMentionButton) {
        event.preventDefault();
        event.stopPropagation();
        insertTextImageMentionCandidate(Number(imageMentionButton.dataset.textImageMentionPick));
        return;
      }
      const imageGroupUngroupButton = event.target.closest('[data-image-group-ungroup]');
      if (imageGroupUngroupButton) {
        const groupElement = imageGroupUngroupButton.closest('.desk-node--image-group[data-node-id]');
        if (!groupElement) return;
        event.preventDefault();
        event.stopPropagation();
        ungroupImageGroup(groupElement.dataset.nodeId);
        return;
      }
      const imageReferenceButton = event.target.closest('[data-image-group-insert-reference]');
      if (imageReferenceButton) {
        const groupElement = imageReferenceButton.closest('.desk-node--image-group[data-node-id]');
        const itemElement = imageReferenceButton.closest('[data-image-group-item]');
        if (!groupElement || !itemElement) return;
        event.preventDefault();
        event.stopPropagation();
        insertImageReferenceToken(groupElement.dataset.nodeId, itemElement.dataset.imageGroupItem);
        return;
      }
      const videoRunButton = event.target.closest('[data-video-run]');
      if (videoRunButton) {
        const nodeElement = videoRunButton.closest('.desk-node--video-inference[data-node-id]');
        if (!nodeElement) return;
        event.preventDefault();
        event.stopPropagation();
        selectNode(nodeElement.dataset.nodeId);
        const originalTitle = videoRunButton.getAttribute('title') || '';
        videoRunButton.disabled = true;
        videoRunButton.classList.add('is-pending');
        videoRunButton.setAttribute('aria-busy', 'true');
        videoRunButton.setAttribute('title', videoRunButton.dataset.videoCancel === 'true' ? '正在取消视频任务…' : '正在检测视频服务…');
        runVideoInferenceNode(nodeElement.dataset.nodeId)
          .catch(error => DesktopResults.showError(error, nodeElement.dataset.nodeId))
          .finally(() => {
            if (!videoRunButton.isConnected) return;
            videoRunButton.disabled = false;
            videoRunButton.classList.remove('is-pending');
            videoRunButton.removeAttribute('aria-busy');
            videoRunButton.setAttribute('title', originalTitle);
          });
        return;
      }
      const comfyParamsReset = event.target.closest('[data-comfy-params-reset]');
      if (comfyParamsReset) {
        const nodeElement = comfyParamsReset.closest('.desk-node--comfy[data-node-id]');
        const nodeState = nodeElement ? DesktopState.state.canvas.nodes[nodeElement.dataset.nodeId] : null;
        if (!nodeState) return;
        event.preventDefault();
        event.stopPropagation();
        if (nodeState.workflowParameters && typeof nodeState.workflowParameters === 'object') {
          delete nodeState.workflowParameters[nodeState.workflow];
        }
        const workflowMeta = (comfyWorkflowCatalog.items || []).find(item => item.id === nodeState.workflow);
        const defaultSize = comfyWorkflowDefaultSize(workflowMeta);
        nodeState.pixelWidth = defaultSize.width;
        nodeState.pixelHeight = defaultSize.height;
        nodeState.ratio = workflowMeta?.default_ratio || '1:1';
        nodeState.resolution = '1k';
        refreshComfyNode(nodeState.id);
        DesktopState.saveSettings();
        return;
      }
      const comfyParameterRemove = event.target.closest('[data-comfy-param-remove]');
      if (comfyParameterRemove) {
        const nodeElement = comfyParameterRemove.closest('.desk-node--comfy[data-node-id]');
        const nodeState = nodeElement ? DesktopState.state.canvas.nodes[nodeElement.dataset.nodeId] : null;
        if (!nodeState?.workflow) return;
        event.preventDefault();
        event.stopPropagation();
        const bucket = nodeState.workflowParameters?.[nodeState.workflow];
        if (bucket && typeof bucket === 'object') {
          delete bucket[comfyParameterRemove.dataset.comfyParamRemove || ''];
          if (!Object.keys(bucket).length) delete nodeState.workflowParameters[nodeState.workflow];
        }
        refreshComfyNode(nodeState.id);
        DesktopState.saveSettings();
        return;
      }
      const comfyWorkflowButton = event.target.closest('[data-comfy-workflow]');
      if (comfyWorkflowButton) {
        const nodeElement = comfyWorkflowButton.closest('.desk-node--comfy[data-node-id]');
        const nodeState = nodeElement ? DesktopState.state.canvas.nodes[nodeElement.dataset.nodeId] : null;
        if (!nodeState) return;
        event.preventDefault();
        event.stopPropagation();
        nodeState.workflow = comfyWorkflowButton.dataset.comfyWorkflow || '';
        const meta = (comfyWorkflowCatalog.items || []).find(item => item.id === nodeState.workflow);
        const defaultSize = comfyWorkflowDefaultSize(meta);
        nodeState.pixelWidth = defaultSize.width;
        nodeState.pixelHeight = defaultSize.height;
        if (meta?.default_ratio) nodeState.ratio = meta.default_ratio;
        nodeState.resolution = '1k';
        refreshComfyNode(nodeState.id);
        selectNode(nodeState.id);
        DesktopState.saveSettings();
        return;
      }
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
      const videoField = event.target.closest('.desk-node--video-inference[data-node-id] [data-video-field]');
      if (videoField) {
        syncVideoInferenceNodeStateFromDom(videoField.closest('.desk-node--video-inference[data-node-id]'));
        DesktopState.saveSettings();
        return;
      }
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
      const comfyParameter = event.target.closest('.desk-node--comfy[data-node-id] [data-comfy-param]');
      if (comfyParameter) {
        const nodeElement = comfyParameter.closest('.desk-node--comfy[data-node-id]');
        const nodeState = DesktopState.state.canvas.nodes[nodeElement?.dataset.nodeId || ''];
        if (!nodeState?.workflow) return;
        const workflowMeta = (comfyWorkflowCatalog.items || []).find(item => item.id === nodeState.workflow);
        const parameterMeta = (workflowMeta?.parameters || []).find(item => item.id === comfyParameter.dataset.comfyParam);
        if (!parameterMeta) return;
        if (!nodeState.workflowParameters || typeof nodeState.workflowParameters !== 'object' || Array.isArray(nodeState.workflowParameters)) {
          nodeState.workflowParameters = {};
        }
        const bucket = nodeState.workflowParameters[nodeState.workflow] && typeof nodeState.workflowParameters[nodeState.workflow] === 'object'
          ? nodeState.workflowParameters[nodeState.workflow]
          : {};
        let value = comfyParameter.type === 'checkbox' ? comfyParameter.checked : comfyParameter.value;
        if (parameterMeta.type === 'number') value = Number(value);
        bucket[parameterMeta.id] = value;
        nodeState.workflowParameters[nodeState.workflow] = bucket;
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
      syncPromptDocumentFromEditor(input, nodeState);
      setTextStyleMenuOpen(node, false);
      updateTextImageMention(input);
    });

    els.deskCanvasWorld?.addEventListener('paste', event => {
      const editor = event.target.closest?.('[data-text-node-input][contenteditable="true"]');
      if (!editor) return;
      event.preventDefault();
      const text = event.clipboardData?.getData('text/plain') || '';
      insertPlainTextIntoPromptEditor(editor, text);
    });

    els.deskCanvasWorld?.addEventListener('keydown', event => {
      const editor = event.target.closest?.('[data-text-node-input][contenteditable="true"]');
      if (!editor) return;
      if (handleTextImageMentionKeydown(event, editor)) return;
      if (handlePromptDocumentHistoryShortcut(event, editor)) return;
      handlePromptEditorTokenDelete(event, editor);
    });
    els.deskCanvasWorld?.addEventListener('keyup', event => {
      const editor = event.target.closest?.('[data-text-node-input][contenteditable="true"]');
      if (editor && !event.isComposing && event.key !== 'Escape') updateTextImageMention(editor);
    });
    els.deskCanvasWorld?.addEventListener('mouseup', event => {
      const editor = event.target.closest?.('[data-text-node-input][contenteditable="true"]');
      if (editor) updateTextImageMention(editor);
    });

    els.deskCanvasWorld?.addEventListener('change', event => {
      const imageGroupRole = event.target.closest('[data-image-group-role]');
      if (imageGroupRole) {
        const groupElement = imageGroupRole.closest('.desk-node--image-group[data-node-id]');
        const itemElement = imageGroupRole.closest('[data-image-group-item]');
        const item = getImageGroupItem(groupElement?.dataset.nodeId, itemElement?.dataset.imageGroupItem);
        if (!groupElement || !item) return;
        item.role = normalizeImageGroupRole(imageGroupRole.value);
        refreshImageReferenceTokens(groupElement.dataset.nodeId);
        DesktopState.saveSettings({ criticalCanvas: true });
        return;
      }
      const videoField = event.target.closest('.desk-node--video-inference[data-node-id] [data-video-field]');
      if (videoField) {
        const nodeElement = videoField.closest('.desk-node--video-inference[data-node-id]');
        const nodeState = syncVideoInferenceNodeStateFromDom(nodeElement);
        if (nodeState) refreshVideoInferenceNode(nodeState.id);
        DesktopState.saveSettings();
        return;
      }
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
      const comfyField = event.target.closest('.desk-node--comfy[data-node-id] [data-comfy-field]');
      if (comfyField) {
        const nodeElement = comfyField.closest('.desk-node--comfy[data-node-id]');
        const nodeState = DesktopState.state.canvas.nodes[nodeElement?.dataset.nodeId || ''];
        if (nodeState) {
          const workflowMeta = (comfyWorkflowCatalog.items || []).find(item => item.id === nodeState.workflow);
          const defaultSize = comfyWorkflowDefaultSize(workflowMeta);
          const isWidth = comfyField.dataset.comfyField === 'pixelWidth';
          const value = normalizeComfyPixelSize(comfyField.value, isWidth ? defaultSize.width : defaultSize.height);
          if (isWidth) nodeState.pixelWidth = value;
          else nodeState.pixelHeight = value;
          comfyField.value = String(value);
          DesktopState.saveSettings();
        }
        return;
      }
      const comfyParameterPicker = event.target.closest('.desk-node--comfy[data-node-id] [data-comfy-param-picker]');
      if (comfyParameterPicker) {
        const parameterId = comfyParameterPicker.value || '';
        const nodeElement = comfyParameterPicker.closest('.desk-node--comfy[data-node-id]');
        const nodeState = DesktopState.state.canvas.nodes[nodeElement?.dataset.nodeId || ''];
        if (!parameterId || !nodeState?.workflow) return;
        const workflowMeta = (comfyWorkflowCatalog.items || []).find(item => item.id === nodeState.workflow);
        const parameterMeta = (workflowMeta?.parameters || []).find(item => item.id === parameterId);
        if (!parameterMeta) return;
        if (!nodeState.workflowParameters || typeof nodeState.workflowParameters !== 'object' || Array.isArray(nodeState.workflowParameters)) {
          nodeState.workflowParameters = {};
        }
        const bucket = nodeState.workflowParameters[nodeState.workflow] && typeof nodeState.workflowParameters[nodeState.workflow] === 'object'
          ? nodeState.workflowParameters[nodeState.workflow]
          : {};
        bucket[parameterMeta.id] = parameterMeta.default;
        nodeState.workflowParameters[nodeState.workflow] = bucket;
        refreshComfyNode(nodeState.id);
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
      clearConnectionDragVisuals();
      DesktopResults.showTransientMessage('按住节点边缘胶囊拖动；落在空白处可新建节点并自动连接。');
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
      event.stopPropagation();
      els.deskUploadDrop.classList.remove('is-dragover');
      const captured = captureExternalImageTransfer(event.dataTransfer);
      importCapturedImages(captured, {
        referenceNodeId: 'input',
        source: 'external-upload',
        fallbackPrefix: '拖入参考图'
      }).catch(error => DesktopResults.showError(error));
    });

    els.deskPromptClearBtn?.addEventListener('click', clearDraft);
    els.deskNewBtn?.addEventListener('click', () => {
      clearDraft();
      DesktopResults.resetOutput();
      resetNodeLayout();
    });

    // A fresh press must not inherit a prior drag's release-click guard. Capture
    // also dismisses the palette before node/viewport gestures stop bubbling.
    els.deskCanvasViewport?.addEventListener('pointerdown', () => {
      canvasViewport.resetPanClickGuard();
      setNodePaletteOpen(false);
    }, true);
    els.deskCanvasViewport?.addEventListener('click', canvasViewport.handlePostPanClick, true);
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
      const hasKnownCanvasPayload = hasHistoryDragPayload(event.dataTransfer)
        || hasGalleryDragPayload(event.dataTransfer)
        || hasAddNodeDragPayload(event.dataTransfer);
      const hasExternalImages = hasExternalImageDragPayload(event.dataTransfer);
      if (!hasKnownCanvasPayload && !hasExternalImages) return;
      event.preventDefault();
      const acceptsDrop = hasKnownCanvasPayload
        || hasLocalImageDragPayload(event.dataTransfer)
        || hasExternalImageTextDragPayload(event.dataTransfer);
      event.dataTransfer.dropEffect = acceptsDrop ? 'copy' : 'none';
      els.deskCanvasViewport.classList.toggle('is-history-dragover', acceptsDrop);
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
        const type = [window.DesktopTopazModel.TYPE, window.DesktopKrea2Model.TYPE, window.DesktopQwen21Model.TYPE, ...window.DesktopCyimgModel.TYPES, window.DesktopVideoControlModel.TYPE, window.DesktopTopazVideoModel.TYPE, ...window.DesktopMusicModel.TYPES, 'file_output', 'video_inference', 'video', 'audio', 'layout', 'text', 'pose', 'upscale'].includes(addNodePayload.type) ? addNodePayload.type : 'input';
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
      if (payload) {
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
        return;
      }

      if (!hasExternalImageDragPayload(event.dataTransfer)) return;
      event.preventDefault();
      event.stopPropagation();
      els.deskCanvasViewport.classList.remove('is-history-dragover');
      const captured = captureExternalImageTransfer(event.dataTransfer);
      const uploadTarget = event.target.closest?.('[data-upload-drop], #deskUploadDrop');
      const inputNode = uploadTarget?.closest?.('.desk-node--input[data-node-id]');
      importCapturedImages(captured, {
        clientX: event.clientX,
        clientY: event.clientY,
        referenceNodeId: uploadTarget ? (inputNode?.dataset.nodeId || 'input') : '',
        source: uploadTarget ? 'external-upload' : 'external-drop',
        fileSource: 'upload',
        fallbackPrefix: uploadTarget ? '拖入参考图' : '拖入图片',
        successLabel: '拖入图片'
      }).catch(error => DesktopResults.showError(error));
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
      const imageGroupButton = event.target.closest('[data-create-image-group]');
      if (imageGroupButton) {
        event.preventDefault();
        event.stopPropagation();
        createImageGroupFromSelection();
        return;
      }
      const button = event.target.closest('[data-align]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      alignSelection(button.dataset.align);
    });
    els.deskCanvasWorld?.addEventListener('pointerdown', beginImageGroupItemSort);
    window.addEventListener('pointermove', moveImageGroupItemSort, { passive: false });
    window.addEventListener('pointerup', event => endImageGroupItemSort(event));
    window.addEventListener('pointercancel', event => endImageGroupItemSort(event, true));
    els.deskCanvasWorld?.addEventListener('pointerdown', event => {
      if (event.target.closest('[data-text-image-mention-pick]')) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
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
      const resizeHandle = event.target.closest('[data-node-resize-handle]');
      if (resizeHandle) {
        const node = resizeHandle.closest('.desk-node[data-node-id]');
        if (node) selectNode(node.dataset.nodeId);
        if (DesktopState.state.canvas.nodes[node?.dataset.nodeId || '']?.type === 'input') return;
        startNodeResize(event);
        return;
      }
      const detachPortButton = event.target.closest('.desk-port[data-port="in"]');
      if (detachPortButton && getDetachableIncomingEdge(detachPortButton.dataset.nodeId)) {
        selectNode(detachPortButton.dataset.nodeId);
        startConnectionDetachDrag(event, detachPortButton);
        return;
      }
      const portButton = event.target.closest('.desk-port[data-port="out"]');
      if (portButton) {
        const sourceNode = getNodeElement(portButton.dataset.nodeId);
        if (!sourceNode?.classList.contains('desk-node--text')) selectNode(portButton.dataset.nodeId);
        startConnectionDrag(event, portButton);
        return;
      }
      if (event.target.closest('[data-node-drag-handle]')) {
        const node = event.target.closest('.desk-node[data-node-id]');
        if (node && !getSelectedNodeIds().includes(node.dataset.nodeId)) selectNode(node.dataset.nodeId);
        startNodeDrag(event, { force: isTextNodeDragEdge(event, node) });
      }
    });
    window.addEventListener('pointermove', moveInteraction);
    window.addEventListener('pagehide', event => { if (!event.persisted) canvasProgress.destroy(); canvasAudio.disposeAll(); canvasMusic.disposeAll(); canvasVideoControl.disposeAll(); canvasTopazVideo.disposeAll(); canvasCyimg.disposeAll(); canvasKrea2.disposeAll(); canvasQwen21.disposeAll(); });
    window.addEventListener('desktop:progress-preferences-change', canvasProgress.refreshPreferences);
    window.addEventListener('pageshow', () => { canvasAudio.reconcile(); canvasMusic.reconcile(); canvasVideoControl.reconcile(); canvasTopazVideo.reconcile(); canvasCyimg.reconcile(); canvasKrea2.reconcile(); canvasQwen21.reconcile(); });
    window.addEventListener('pointerup', endInteraction);
    window.addEventListener('pointercancel', endInteraction);
    window.addEventListener('blur', () => {
      if (activeInteraction?.type === 'connect'
        || (activeInteraction?.type === 'node-drag' && window.DesktopPreferences?.state?.canvasCollisionEnabled === true)) {
        endInteraction({ type: 'pointercancel' });
      }
    });
    els.deskCanvasViewport?.addEventListener('pointerleave', () => {
      if (!activeInteraction) clearFloatingConnectionPort();
    });
    window.addEventListener('mousemove', moveMouseInteractionFallback, true);
    window.addEventListener('mouseup', endMouseInteractionFallback, true);
    window.addEventListener('resize', () => {
      canvasViewport.endMiniMapNavigation(null, { focus: false });
      renderMiniMap();
      positionEdgeMenu();
    });
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
    els.deskMiniMap?.addEventListener('pointerdown', event => {
      if (!activeInteraction && !draggedImageGroupItem) canvasViewport.beginMiniMapNavigation(event);
    });
    window.addEventListener('pointermove', canvasViewport.moveMiniMapNavigation, { passive: false });
    window.addEventListener('pointerup', canvasViewport.endMiniMapNavigation);
    window.addEventListener('pointercancel', canvasViewport.endMiniMapNavigation);
    els.deskMiniMap?.addEventListener('lostpointercapture', canvasViewport.endMiniMapNavigation);
    els.deskMiniMap?.addEventListener('keydown', canvasViewport.handleMiniMapKeydown);
    window.addEventListener('blur', () => canvasViewport.endMiniMapNavigation());
    window.addEventListener('pagehide', () => canvasViewport.endMiniMapNavigation(null, { focus: false }));

    document.addEventListener('keydown', event => {
      if (event.defaultPrevented) return;
      if (event.key === 'Escape' && draggedImageGroupItem) {
        event.preventDefault();
        event.stopPropagation();
        endImageGroupItemSort(null, true);
        return;
      }
      if (event.key === 'Escape') {
        if (activeInteraction?.type === 'connect'
          || (activeInteraction?.type === 'node-drag' && window.DesktopPreferences?.state?.canvasCollisionEnabled === true)) {
          event.preventDefault();
          endInteraction({ type: 'pointercancel' });
          return;
        }
        hideContextMenu();
        setNodePaletteOpen(false);
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

  function migrateLegacyComfyProviders() {
    return canvasNodes.migrateLegacyComfyProviders();
  }

  function init() {
    collectElements();
    canvasProgress.refreshPreferences();
    renderNodePaletteItems();
    const comfyMigrated = migrateLegacyComfyProviders();
    const videoLayoutMigrated = Object.values(DesktopState.state.canvas.nodes || {}).reduce((changed, node) => (
      node?.type === 'video_inference' ? migrateVideoInferenceNodeLayout(node) || changed : changed
    ), false);
    migrateResultNodesToModelOutputs();
    const promptDocumentsChanged = ensureTextNodePromptDocuments();
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
    loadComfyWorkflowCatalog().catch(() => {});
    loadVideoRuntimeContext().catch(() => {});
    restoreVideoTaskPolling();
    window.addEventListener('desktop:comfy-workflows-updated', event => {
      if (event.detail) comfyWorkflowCatalog = event.detail;
      Object.values(DesktopState.state.canvas.nodes || {}).filter(node => node.type === 'comfy').forEach(node => refreshComfyNode(node.id));
    });
    window.addEventListener('desktop:connection-swell-style-change', refreshFloatingSwellStyle);
    window.addEventListener('desktop:connection-line-style-change', updateLinkPath);
    window.addEventListener('desktop:canvas-collision-change', () => canvasCollision.settle());
    window.addEventListener('desktop:canvas-text-nodes-change', () => { canvasMusic.graphChanged(); canvasVideoControl.graphChanged(); canvasTopazVideo.graphChanged(); canvasCyimg.graphChanged(); canvasKrea2.graphChanged(); canvasQwen21.graphChanged(); });
    window.addEventListener('desktop:canvas-selection-change', event => { taskRegistry.showStatus(event.detail?.selectedNodeId); });
    window.addEventListener('desktop:canvas-node-removed', () => { canvasMusic.graphChanged(); canvasVideoControl.graphChanged(); canvasTopazVideo.graphChanged(); canvasCyimg.graphChanged(); canvasKrea2.graphChanged(); canvasQwen21.graphChanged(); });
    window.addEventListener('desktop:video-runtime-status-updated', () => {
      Object.values(DesktopState.state.canvas.nodes || {})
        .filter(node => node.type === 'video_inference')
        .forEach(node => refreshVideoInferenceNode(node.id));
    });
    window.addEventListener('desktop:video-capabilities-updated', () => {
      Object.values(DesktopState.state.canvas.nodes || {})
        .filter(node => node.type === 'video_inference')
        .forEach(node => {
          normalizeVideoInferenceNodeState(node);
          refreshVideoInferenceNode(node.id);
        });
    });
    window.addEventListener('miniapp:auth-state-change', event => {
      if (event.detail?.authenticated) {
        loadComfyWorkflowCatalog().catch(() => {});
        loadVideoRuntimeContext().catch(() => {});
      }
    });
    if (groupsChanged || promptDocumentsChanged || comfyMigrated || videoLayoutMigrated) DesktopState.saveSettings();
  }

  // Domain controllers are assembled after shared state, before the public compatibility API.
  const canvasCollision = window.DesktopCanvasCollision.create({
    getCanvas: () => DesktopState.state.canvas,
    isEnabled: () => window.DesktopPreferences?.state?.canvasCollisionEnabled === true,
    getBounds: getNodeBoundsById,
    applyLayout: nodeId => applyNodeLayout(nodeId, { deferGraph: true }),
    renderGraph: flushCanvasGraphRender,
    save: () => DesktopState.saveSettings(),
    requestFrame: callback => requestAnimationFrame(callback),
    cancelFrame: frameId => cancelAnimationFrame(frameId),
    reducedMotion: prefersReducedMotion,
  });
  const taskRegistry = window.DesktopTasks.createRegistry({
    reportStatus: feedback => DesktopResults.reportTaskStatus(feedback),
  });
  const stateIcon = window.DesktopStateIcon;
  const canvasProgress = window.DesktopProgress.create({
    getPreferences: () => window.DesktopPreferences.state.progress,
    getViewport: () => els.deskCanvasViewport,
    isInteracting: () => els.deskCanvasViewport?.matches('.is-panning, .is-wheel-transforming'),
  });
  const canvasAudio = window.DesktopCanvasAudio.create({
    stateIcon,
    assets: window.DesktopAudioAssets,
    meters: window.DesktopAudioMeter,
    getNodeState,
    getNodeElement,
    saveState: () => DesktopState.saveSettings({ criticalCanvas: true }),
    escapeHtml,
  });
  const canvasMusic = window.DesktopCanvasMusic.create({
    model: window.DesktopMusicModel, api: window.DesktopMusicAPI, score: window.DesktopMusicScore,
    workflow: window.DesktopMusicWorkflow,
    view: window.DesktopMusicView.create({ model: window.DesktopMusicModel, escapeHtml, stateIcon, progressView: canvasProgress }),
    getCanvas: () => DesktopState.state.canvas, getNodeState, getNodeElement,
    materializeText: materializeTextNode, audio: canvasAudio, addNode, connectNodes,
    reportStatus: feedback => taskRegistry.report('music', feedback),
    saveState: () => DesktopState.saveSettings({ criticalCanvas: true }), escapeHtml,
  });
  const canvasTopaz = window.DesktopCanvasTopaz.create({
    model: window.DesktopTopazModel, stateIcon, loadCatalog: () => DesktopApi.getTopazModels(), getState: () => DesktopState.state, getNodeElement,
    getReferences: getConnectedImageReferences, outputReference: outputImageReference,
    save: () => DesktopState.saveSettings(), setImageFromResult: setImageNodeFromResult,
    ensureOutputs: ensureImageOutputsForConfig,
    submit: (...args) => DesktopResults.submitConfigToResult(...args),
    showError: (...args) => DesktopResults.showError(...args)
  });
  const canvasCyimg = window.DesktopCanvasCyimg.create({
    progressView: canvasProgress,
    model:window.DesktopCyimgModel, api:window.DesktopCyimgAPI,
    getCanvas:()=>DesktopState.state.canvas, getNodeState,getNodeElement,
    getImageReferences:getConnectedImageReferences, getTextNodes:getConnectedTextNodes,
    materializeText:materializeTextNode, audioAssets:window.DesktopAudioAssets,
    addNode,connectNodes,setImageFromResult:setImageNodeFromResult,refreshVideoNode,
    saveState:()=>DesktopState.saveSettings({criticalCanvas:true}),
    reportStatus:feedback=>taskRegistry.report('cyimg',feedback),
  });
  const canvasLoRA = window.DesktopCanvasLoRA.create({
    getCanvas: () => DesktopState.state.canvas, getNodeState, getNodeElement,
    getTextNodes: getConnectedTextNodes, materializeText: materializeTextNode,
    cloneDocument: clonePromptDocument, setDocument: setTextNodePromptDocument,
    addNode, removeNode, connectNodes, getSelectedIds: getSelectedNodeIds,
    getController: type => type === 'krea2' ? canvasKrea2 : canvasQwen21
  });
  const loraView = window.DesktopLoRAView.create({
    library: DesktopApi.lora, assets: options => DesktopApi.getAssets(options),
    listTargets: canvasLoRA.listTargets, addToNode: canvasLoRA.addToNode,
    triggerTargets: canvasLoRA.listTextTargets, insertTriggers: canvasLoRA.insertTriggers,
    notify: message => DesktopResults.showTransientMessage(message)
  });
  const canvasKrea2 = window.DesktopCanvasKrea2.create({
    progressView: canvasProgress,
    model:window.DesktopKrea2Model, api:window.DesktopKrea2API,
    loraLibrary: DesktopApi.lora, loraView,
    getCanvas:()=>DesktopState.state.canvas, getNodeState,getNodeElement,
    getImageReferences:getConnectedImageReferences, getTextNodes:getConnectedTextNodes,
    materializeText:materializeTextNode, addNode,connectNodes,
    setImageFromResult:setImageNodeFromResult,
    saveState:()=>DesktopState.saveSettings({criticalCanvas:true}),
    reportStatus:feedback=>taskRegistry.report('krea2',feedback),
  });
  const canvasQwen21 = window.DesktopCanvasQwen21.create({
    progressView: canvasProgress,
    model:window.DesktopQwen21Model, api:window.DesktopQwen21API,
    loraLibrary: DesktopApi.lora, loraView,
    getCanvas:()=>DesktopState.state.canvas, getNodeState,getNodeElement,
    getImageReferences:getConnectedImageReferences, getTextNodes:getConnectedTextNodes,
    materializeText:materializeTextNode, addNode,connectNodes,
    setImageFromResult:setImageNodeFromResult,applyNodeLayout,updateLinkPath,
    saveState:()=>DesktopState.saveSettings({criticalCanvas:true}),
    reportStatus:feedback=>taskRegistry.report('qwen21',feedback),
  });
  const canvasVideoControl = window.DesktopCanvasVideoControl.create({
    model: window.DesktopVideoControlModel, api: window.DesktopVideoControlAPI,
    view: window.DesktopVideoControlView.create({ model: window.DesktopVideoControlModel, escapeHtml, stateIcon, progressView: canvasProgress }),
    getCanvas: () => DesktopState.state.canvas, getNodeState, getNodeElement, addNode, connectNodes, refreshVideoNode,
    saveState: () => DesktopState.saveSettings({ criticalCanvas: true }),
    reportStatus: feedback => taskRegistry.report('video_control', feedback),
  });
  const topazVideoWorkbench = window.DesktopTopazVideoWorkbench.create({
    inspector: window.DesktopTopazVideoInspector.create({pipeline: window.DesktopTopazVideoPipeline, escapeHtml}),
    model: window.DesktopTopazVideoModel, api: window.DesktopTopazVideoAPI, escapeHtml, stateIcon,
  });
  const canvasTopazVideo = window.DesktopCanvasTopazVideo.create({
    pipeline: window.DesktopTopazVideoPipeline,
    model: window.DesktopTopazVideoModel, api: window.DesktopTopazVideoAPI,
    view: window.DesktopTopazVideoView.create({ model: window.DesktopTopazVideoModel, escapeHtml, stateIcon, progressView: canvasProgress }),
    workbench: topazVideoWorkbench,
    getCanvas: () => DesktopState.state.canvas, getNodeState, getNodeElement, addNode, connectNodes, refreshVideoNode,
    saveState: () => DesktopState.saveSettings({ criticalCanvas: true }),
    reportStatus: feedback => taskRegistry.report('topaz_video', feedback),
  });
  taskRegistry.register('music', {client: () => window.DesktopMusicAPI.tasks,
    listCancelable: canvasMusic.getCancelableTasks, showStatus: canvasMusic.showStatus});
  taskRegistry.register('video_control', {client: () => window.DesktopVideoControlAPI.tasks,
    listCancelable: canvasVideoControl.getCancelableTasks, showStatus: canvasVideoControl.showStatus});
  taskRegistry.register('topaz_video', {client: () => window.DesktopTopazVideoAPI.tasks,
    listCancelable: canvasTopazVideo.getCancelableTasks, showStatus: canvasTopazVideo.showStatus});
  taskRegistry.register('cyimg', {client: () => window.DesktopCyimgAPI.tasks,
    showStatus: canvasCyimg.showStatus});
  taskRegistry.register('krea2', {client: () => window.DesktopKrea2API.tasks,
    listCancelable: canvasKrea2.getCancelableTasks, showStatus: canvasKrea2.showStatus});
  taskRegistry.register('qwen21', {client: () => window.DesktopQwen21API.tasks,
    listCancelable: canvasQwen21.getCancelableTasks, showStatus: canvasQwen21.showStatus});
  const canvasWorkflow = window.DesktopCanvasWorkflow.create({
    DEFAULT_COMFY_NODE_HEIGHT,
    DEFAULT_COMFY_NODE_WIDTH,
    DEFAULT_COMFY_PIXEL_HEIGHT,
    DEFAULT_COMFY_PIXEL_WIDTH,
    DEFAULT_GOOGLE_MODEL,
    DEFAULT_IMAGE_GROUP_NODE_HEIGHT,
    DEFAULT_IMAGE_GROUP_NODE_WIDTH,
    DEFAULT_IMAGE_NODE_HEIGHT,
    DEFAULT_IMAGE_NODE_WIDTH,
    DEFAULT_INPUT_NODE_HEIGHT,
    DEFAULT_INPUT_NODE_WIDTH,
    DEFAULT_UPSCALE_NODE_HEIGHT,
    DEFAULT_UPSCALE_NODE_WIDTH,
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    DEFAULT_VIDEO_NODE_HEIGHT,
    DEFAULT_VIDEO_NODE_WIDTH,
    MAX_COMFY_NODE_HEIGHT,
    MAX_COMFY_NODE_WIDTH,
    MAX_SCALE,
    MAX_VIDEO_INFERENCE_NODE_HEIGHT,
    MAX_VIDEO_INFERENCE_NODE_WIDTH,
    MAX_VIDEO_NODE_WIDTH,
    MIN_COMFY_NODE_HEIGHT,
    MIN_COMFY_NODE_WIDTH,
    MIN_SCALE,
    MIN_VIDEO_INFERENCE_NODE_HEIGHT,
    MIN_VIDEO_INFERENCE_NODE_WIDTH,
    MIN_VIDEO_NODE_WIDTH,
    UPSCALE_MODEL_OPTIONS,
    WORKFLOW_SCHEMA,
    WORKFLOW_VERSION,
    applyWorkflowSnapshot,
    audioNodeDefinition: window.DesktopCanvasAudio,
    musicNodeDefinition: window.DesktopMusicModel,
    topazDefinition: window.DesktopTopazModel,
    cyimgDefinition: window.DesktopCyimgModel,
    krea2Definition: window.DesktopKrea2Model,
    qwen21Definition: window.DesktopQwen21Model,
    videoControlDefinition: window.DesktopVideoControlModel,
    topazVideoDefinition: window.DesktopTopazVideoModel,
    embedAudioAssets: window.DesktopAudioAssets.embedWorkflowAssets,
    clamp,
    dataUrlValue,
    downloadBlob,
    expandNodeIdsToGroups,
    fitVideoNodeToMedia,
    imageGroupItemSource,
    jsonClone,
    materializePromptDocument,
    materializeTextNode,
    nextTextNodeAlias,
    normalizeComfyPixelSize,
    normalizeImageGroupNodeState,
    normalizeNodeGroupId,
    normalizeNodeGroups,
    normalizeNodeMenuType,
    normalizePromptDocument,
    normalizeVideoInferenceNodeState,
    revokeReferenceUrl,
    sanitizeImageEditFilename,
    sanitizeTextNodeAlias,
    syncVisibleInputNodeStatesToCanvas,
  });

  const canvasPromptDocument = window.DesktopCanvasPromptDocument.create({
    PROMPT_BLOCK_MAX_CONTENT_LENGTH,
    PROMPT_BLOCK_MAX_ID_LENGTH,
    PROMPT_BLOCK_MAX_LABEL_LENGTH,
    PROMPT_DOCUMENT_HISTORY_LIMIT,
    PROMPT_DOCUMENT_MAX_LENGTH,
    PROMPT_DOCUMENT_MAX_SEGMENTS,
    PROMPT_DOCUMENT_SCHEMA,
    PROMPT_DOCUMENT_VERSION,
    getConnectedImageReferences,
    getImageGroupItem,
    getTextStylePreset,
    imageGroupRolePromptBlock,
    jsonClone,
    listPromptImageNodes,
    normalizeImageGroupRole,
    promptDocumentHistories,
    promptDocumentVersions,
  });

  const canvasTextEditor = window.DesktopCanvasTextEditor.create({
    CUSTOM_TEXT_STYLE_KEY,
    DEFAULT_IMAGE_GROUP_NODE_WIDTH,
    DEFAULT_TEXT_NODE_WIDTH,
    PROMPT_BLOCK_MODULE_LABELS,
    PROMPT_DOCUMENT_HISTORY_LIMIT,
    PROMPT_TOKEN_SELECTOR,
    TEXT_NODE_ALIAS_MAX_LENGTH,
    TEXT_POLISH_VARIANTS,
    TEXT_STYLE_PRESETS,
    activeTextImageMentionRef: { get current() { return activeTextImageMention; }, set current(value) { activeTextImageMention = value; } },
    addNode,
    beginPromptDocumentHistory,
    bumpPromptDocumentVersion,
    clamp,
    clonePromptDocument,
    commitPromptDocumentHistory,
    connectNodes,
    createTextPromptDocument,
    ensureGraphDom,
    ensureTextNodePromptDocument,
    escapeHtml,
    getConnectedImageReferences,
    getImageGroupItem,
    getNodeElement,
    getPromptDocumentHistory,
    getSelectedNodeIds,
    getViewportCenterWorldPoint,
    imageGroupRoleLabel,
    imageReferenceDisplay,
    imageReferenceRole,
    lastPromptTextNodeIdRef: { get current() { return lastPromptTextNodeId; }, set current(value) { lastPromptTextNodeId = value; } },
    listPromptImageNodes,
    materializePromptDocument,
    materializeTextNode,
    normalizeImageGroupRole,
    normalizeImageReferenceSegment,
    normalizePromptBlockSegment,
    normalizePromptDocument,
    promptDocumentFingerprint,
    promptDocumentHasEditorContent,
    selectNode,
    setTextNodePromptMeta,
  });

  const canvasImageGroupModel = window.DesktopCanvasImageGroupModel.create({
    DEFAULT_IMAGE_NODE_HEIGHT,
    DEFAULT_IMAGE_NODE_WIDTH,
    IMAGE_GROUP_FILTER_OUTSET_PX,
    IMAGE_GROUP_IDENTITY_WIDTH_PX,
    IMAGE_GROUP_LAYOUT_VERSION,
    IMAGE_GROUP_LIQUID_SHELL_PX,
    IMAGE_GROUP_MAX_COLUMNS,
    IMAGE_GROUP_MAX_ITEMS,
    IMAGE_GROUP_MOTHER_HEIGHT_PX,
    IMAGE_GROUP_MOTHER_RADIUS_PX,
    IMAGE_GROUP_MOTHER_TOP_PX,
    IMAGE_GROUP_ROLES,
    IMAGE_GROUP_ROLE_INSTRUCTIONS,
    IMAGE_GROUP_ROLE_PRIORITY_NOTE,
    IMAGE_GROUP_ROW_STEP_PX,
    IMAGE_GROUP_THUMB_PX,
    IMAGE_GROUP_THUMB_STEP_PX,
    IMAGE_GROUP_TRAILING_SPACE_PX,
    MAX_IMAGE_GROUP_NODE_WIDTH,
    MIN_IMAGE_GROUP_NODE_WIDTH,
    animateImageGroupItemFlip,
    animateImagesIntoGroup,
    animateImagesOutOfGroup,
    applyNodeLayout,
    captureImageGroupItemRects,
    captureImageNodeTransitionSources,
    clamp,
    dataUrlValue,
    discardFloatingSwellState,
    ensureGraphDom,
    ensureNodeEdgeHandles,
    escapeHtml,
    freezeImageReferenceTokens,
    getBoundsForNodeIds,
    getConnectedImageReferences,
    getNodeElement,
    getSelectedNodeIds,
    imageNodeSource,
    jsonClone,
    migrateImageReferenceTokensToGroup,
    nextNodeId,
    normalizeNodeGroups,
    orderTransitionSourcesForNodes,
    refreshImageReferenceTokens,
    setSelectedNodes,
    updateLinkPath,
  });

  const canvasImageGroupInteraction = window.DesktopCanvasImageGroupInteraction.create({
    IMAGE_GROUP_BASE_THUMB_PX,
    IMAGE_GROUP_IDENTITY_WIDTH_PX,
    IMAGE_GROUP_MAX_COLUMNS,
    IMAGE_GROUP_MAX_ITEMS,
    IMAGE_GROUP_MOTHER_HEIGHT_PX,
    IMAGE_GROUP_MOTHER_RADIUS_PX,
    IMAGE_GROUP_MOTHER_TOP_PX,
    IMAGE_GROUP_PROXIMITY_CONTACT_PX,
    IMAGE_GROUP_PROXIMITY_DISTANCE_PX,
    IMAGE_GROUP_PROXIMITY_DROP_MS,
    IMAGE_GROUP_PROXIMITY_DROP_PX,
    IMAGE_GROUP_PROXIMITY_DWELL_MS,
    IMAGE_GROUP_PROXIMITY_RELEASE_MS,
    IMAGE_GROUP_PROXIMITY_RELEASE_PX,
    IMAGE_GROUP_ROW_STEP_PX,
    IMAGE_GROUP_THUMB_PX,
    IMAGE_GROUP_THUMB_STEP_PX,
    IMAGE_GROUP_TRANSITION_THUMB_PX,
    activeInteractionRef: { get current() { return activeInteraction; }, set current(value) { activeInteraction = value; } },
    appendImageNodeToGroup,
    clamp,
    createImageGroupFromNodes,
    draggedImageGroupItemRef: { get current() { return draggedImageGroupItem; }, set current(value) { draggedImageGroupItem = value; } },
    getNodeElement,
    getSelectedNodeIds,
    hideSmartGuides,
    imageGroupGooeyFilterPrimitivesHtml,
    imageGroupItemSource,
    imageGroupLiquidField: window.DesktopCanvasImageGroupLiquidField,
    imageGroupMotherHeight,
    imageGroupUiSize,
    imageNodeSource,
    naturalImageGroupNodeWidth,
    normalizeImageGroupNodeState,
    prefersReducedMotion,
    reorderImageGroupItemToIndex,
    screenToWorld,
    selectNode,
    sortImageNodesForGroup,
  });

  const canvasImageEditorTools = window.DesktopCanvasImageEditorTools.create({
    IMAGE_EDIT_ASSET_VERSION,
    IMAGE_EDIT_CURSOR_HOTSPOTS,
    createImageEditId,
    getImageEditState,
    getImageEditorCanvas,
    imageEditScreenToCanvasSize,
    imageEditorElRef: { get current() { return imageEditorEl; }, set current(value) { imageEditorEl = value; } },
    recordImageEditSnapshot,
    serializeImageEditObject,
    setImageEditStatus,
    updateImageEditToolUi,
    updateImageEditUndoRedoButtons,
  });

  const canvasImageEditor = window.DesktopCanvasImageEditor.create({
    IMAGE_EDIT_MAX_ZOOM,
    IMAGE_EDIT_MIN_ZOOM,
    IMAGE_EDIT_UI_SCALE,
    IMAGE_EDIT_ZOOM_STEP,
    activeImageEditRef: { get current() { return activeImageEdit; }, set current(value) { activeImageEdit = value; } },
    applyImageEditObjectControls,
    createImageEditArrow,
    createImageEditPin,
    createImageEditShape,
    createImageEditTextStyle,
    downloadDataUrl,
    downloadJsonObject,
    fileToDataUrl,
    getImageEditObjects,
    getImageEditPinNumber,
    getImageEditShapeIcon,
    getImageEditShapeMode,
    getImageEditToolIcon,
    getNodeBoundsById,
    getViewportCenterWorldPoint,
    handleImageEditSelectionChange,
    imageEditorCanvasRef: { get current() { return imageEditorCanvas; }, set current(value) { imageEditorCanvas = value; } },
    imageEditorElRef: { get current() { return imageEditorEl; }, set current(value) { imageEditorEl = value; } },
    insertImageNode,
    isImageEditShapeEllipse,
    normalizeImageEditColor,
    readImageMeta,
    refreshImageNode,
    removeImageEditObjects,
    setImageEditBrushSize,
    setImageEditColor,
    setImageEditObjectMeta,
    setImageEditShapeMode,
    setImageEditTool,
    updateImageEditArrow,
  });

  const canvasMediaImport = window.DesktopCanvasMediaImport.create({
    DEFAULT_IMAGE_LONGEST_SIDE,
    LOCAL_IMAGE_EXTENSION_MIME,
    LOCAL_IMAGE_MIME_EXTENSION,
    MAX_EXTERNAL_IMAGE_IMPORTS,
    MAX_IMAGE_NODE_WIDTH,
    MIN_IMAGE_NODE_WIDTH,
    SUPPORTED_LOCAL_IMAGE_TEXT,
    addNode,
    applyNodeLayout,
    connectNodes,
    els,
    ensureGraphDom,
    findDefaultInputNodeId,
    fitVideoNodeToMedia,
    getNodeBoundsById,
    getNodeElement,
    getNodeReferenceImages,
    getViewportCenterWorldPoint,
    lastCanvasPointerRef: { get current() { return lastCanvasPointer; }, set current(value) { lastCanvasPointer = value; } },
    nextNodeId,
    openImageEditor,
    refreshImageNodeContent,
    refreshVideoNode,
    renderNodeReferenceThumbs,
    renderReferenceThumbs,
    screenToWorld,
    selectNode,
    updateLinkPath,
  });

  const canvasReferences = window.DesktopCanvasReferences.create({
    addNode,
    applyGptTaskTypeToNode,
    applyPromptModeToNode,
    els,
    escapeHtml,
    getNodeElement,
    getViewportCenterWorldPoint,
    getVisibleInputPrompt,
    imageGroupItemSource,
    imageNodeSource,
    normalizeImageSourceFromGroupItem,
    poseDisplayTitle,
    screenToWorld,
    selectNode,
    setPromptTextForInputNode,
    syncFormFromState,
    updateLayoutInputCount,
  });

  const canvasNodes = window.DesktopCanvasNodes.create({
    progressView: canvasProgress,
    DEFAULT_COMFY_NODE_HEIGHT,
    DEFAULT_COMFY_NODE_WIDTH,
    DEFAULT_COMFY_PIXEL_HEIGHT,
    DEFAULT_COMFY_PIXEL_WIDTH,
    DEFAULT_FILE_OUTPUT_NODE_HEIGHT,
    DEFAULT_FILE_OUTPUT_NODE_WIDTH,
    DEFAULT_IMAGE_GROUP_NODE_HEIGHT,
    DEFAULT_IMAGE_GROUP_NODE_WIDTH,
    DEFAULT_IMAGE_NODE_HEIGHT,
    DEFAULT_IMAGE_NODE_WIDTH,
    DEFAULT_INPUT_NODE_HEIGHT,
    DEFAULT_INPUT_NODE_WIDTH,
    DEFAULT_TEXT_NODE_HEIGHT,
    DEFAULT_TEXT_NODE_WIDTH,
    DEFAULT_UPSCALE_NODE_HEIGHT,
    DEFAULT_UPSCALE_NODE_WIDTH,
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    DEFAULT_VIDEO_NODE_HEIGHT,
    DEFAULT_VIDEO_NODE_WIDTH,
    IMAGE_GROUP_LAYOUT_VERSION,
    LOCKED_INPUT_NODE_HEIGHT,
    LOCKED_INPUT_NODE_WIDTH,
    NODE_MENU_ITEMS,
    ORDINARY_MENU_CLOSE_FALLBACK_MS,
    applyAllNodeLayouts,
    audioNode: canvasAudio,
    musicNode: canvasMusic,
    topazNode: canvasTopaz,
    cyimgNode: canvasCyimg,
    krea2Node: canvasKrea2,
    qwen21Node: canvasQwen21,
    videoControlNode: canvasVideoControl,
    topazVideoNode: canvasTopazVideo,
    audioNodeDefinition: window.DesktopCanvasAudio,
    musicNodeDefinition: window.DesktopMusicModel,
    topazDefinition: window.DesktopTopazModel,
    cyimgDefinition: window.DesktopCyimgModel,
    krea2Definition: window.DesktopKrea2Model,
    qwen21Definition: window.DesktopQwen21Model,
    videoControlDefinition: window.DesktopVideoControlModel,
    topazVideoDefinition: window.DesktopTopazVideoModel,
    clearPromptDocumentHistory,
    comfyNodeHtml,
    comfyWorkflowCatalogRef: { get current() { return comfyWorkflowCatalog; }, set current(value) { comfyWorkflowCatalog = value; } },
    comfyWorkflowDefaultSize,
    connectNodes,
    createTextPromptDocument,
    discardFloatingSwellState,
    els,
    ensureNodeEdgeHandles,
    escapeHtml,
    fileOutputNodeHtml,
    findDefaultInputNodeId,
    focusCanvasViewport,
    freezeImageReferenceTokens,
    freezeImageReferenceTokensForSourceNode,
    getConnectedTextNodes,
    getNodeElement,
    getNodeReferenceStore,
    getNodeState,
    getSelectedNodeIds,
    getViewportCenterWorldPoint,
    imageGroupNodeHtml,
    inputNodeHtml,
    materializeTextNode,
    nextTextNodeAlias,
    nodePaletteCloseTimerRef: { get current() { return nodePaletteCloseTimer; }, set current(value) { nodePaletteCloseTimer = value; } },
    normalizeComfyPixelSize,
    normalizeImageSourceFromNode,
    normalizeNodeGroupId,
    normalizeNodeGroups,
    normalizeVideoInferenceNodeState,
    notifyTextNodeListChange,
    refreshImageReferenceTokens,
    refreshVideoInferenceNode,
    refreshVideoNode,
    renderMiniMap,
    revokeReferenceUrl,
    scheduleCanvasGraphRender,
    selectNode,
    setPromptTextForInputNode,
    setSelectedNodes,
    setTextStyleMenuOpen,
    stopVideoTaskPolling,
    syncOutputControlsToNodes,
    textNodeHtml,
    triggerImageNodePopIn,
    updateInputProgressOverlay,
    updateLinkPath,
    updateSelectionToolbar,
    updateUpscaleInputCount,
    upscaleNodeHtml,
    videoInferenceNodeHtml,
    videoNodeHtml,
  });

  const canvasModelNodes = window.DesktopCanvasModelNodes.create({
    progressView: canvasProgress,
    ASPECT_RATIO_OPTIONS,
    COMFY_PIXEL_STEP,
    DEFAULT_COMFY_PIXEL_HEIGHT,
    DEFAULT_COMFY_PIXEL_WIDTH,
    DEFAULT_GOOGLE_MODEL,
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    DEFAULT_VIDEO_NODE_HEIGHT,
    DEFAULT_VIDEO_NODE_WIDTH,
    GOOGLE_MODEL_OPTIONS,
    GPT_MAIN_MODEL_OPTIONS,
    GPT_PROMPT_MODE_OPTIONS,
    GPT_PROVIDER_ROUTE_OPTIONS,
    GPT_REASONING_OPTIONS,
    GPT_ROUTE_PRESENTATION,
    GPT_TASK_TYPE_OPTIONS,
    MAX_COMFY_PIXEL_SIZE,
    MAX_VIDEO_INFERENCE_NODE_HEIGHT,
    MAX_VIDEO_INFERENCE_NODE_WIDTH,
    MAX_VIDEO_NODE_HEIGHT,
    MAX_VIDEO_NODE_WIDTH,
    MIN_COMFY_PIXEL_SIZE,
    MIN_VIDEO_INFERENCE_NODE_HEIGHT,
    MIN_VIDEO_INFERENCE_NODE_WIDTH,
    MIN_VIDEO_NODE_HEIGHT,
    MIN_VIDEO_NODE_WIDTH,
    UPSCALE_MODEL_OPTIONS,
    VIDEO_INFERENCE_LAYOUT_VERSION,
    VIDEO_NODE_LAYOUT_VERSION,
    applyAllNodeLayouts,
    applyCanvasTransform,
    applyNodeLayout,
    applyNodeSelection,
    clamp,
    comfyWorkflowCatalogRef: { get current() { return comfyWorkflowCatalog; }, set current(value) { comfyWorkflowCatalog = value; } },
    discardFloatingSwellState,
    els,
    ensureNodeEdgeHandles,
    escapeHtml,
    getConnectedImageReferences,
    getConnectedTextNodes,
    getNodeElement,
    gptModelCatalogRef: { get current() { return gptModelCatalog; }, set current(value) { gptModelCatalog = value; } },
    selectNode,
    updateInputProgressOverlay,
    updateLinkPath,
  });

  const canvasConnections = window.DesktopCanvasConnections.create({
    domainConnections: window.DesktopCanvasConnections.combineDomains(canvasMusic.connections, canvasVideoControl.connections, canvasTopazVideo.connections, canvasTopaz.connections, canvasCyimg.connections, canvasKrea2.connections, canvasQwen21.connections),
    LINK_VIEWBOX,
    NODE_MENU_ITEMS,
    ORDINARY_MENU_CLOSE_FALLBACK_MS,
    activeInteractionRef: { get current() { return activeInteraction; }, set current(value) { activeInteraction = value; } },
    addNodeFromMenu,
    assignImageOutputSlots,
    clamp,
    clearFloatingConnectionPort,
    clearConnectionProximity: () => canvasConnectionFeedback.clearProximity(),
    getNodeVisualOffset: nodeId => canvasConnectionFeedback.getNodeVisualOffset(nodeId),
    playConnectionCommit: receipt => canvasConnectionFeedback.playCommit(receipt),
    contextMenuConnectionSourceAnchorRef: { get current() { return contextMenuConnectionSourceAnchor; }, set current(value) { contextMenuConnectionSourceAnchor = value; } },
    contextMenuConnectionSourceIdRef: { get current() { return contextMenuConnectionSourceId; }, set current(value) { contextMenuConnectionSourceId = value; } },
    contextMenuConnectionSourceSideRef: { get current() { return contextMenuConnectionSourceSide; }, set current(value) { contextMenuConnectionSourceSide = value; } },
    contextMenuElRef: { get current() { return contextMenuEl; }, set current(value) { contextMenuEl = value; } },
    dominantPortSide,
    edgeMenuElRef: { get current() { return edgeMenuEl; }, set current(value) { edgeMenuEl = value; } },
    els,
    ensureTextNodeImageReferenceConnections,
    escapeHtml,
    focusCanvasViewport,
    getConnectionPortAnchor,
    getNodeElement,
    getNodeState,
    getViewportCenterWorldPoint,
    holdFloatingSwell,
    hoveredEdgeIdRef: { get current() { return hoveredEdgeId; }, set current(value) { hoveredEdgeId = value; } },
    makeClassicCurvePath,
    makeSmoothStepPath,
    nodeMenuButtonHtml,
    normalizePortSide,
    oppositePortSide,
    pendingConnectionDropPointRef: { get current() { return pendingConnectionDropPoint; }, set current(value) { pendingConnectionDropPoint = value; } },
    refreshComfyNode,
    refreshImageReferenceTokens,
    refreshPoseNode,
    refreshUpscaleNodeMode,
    refreshVideoInferenceNode,
    refreshVideoNode,
    releaseFloatingSwell,
    renderMiniMap,
    screenToWorld,
    selectedEdgeIdRef: { get current() { return selectedEdgeId; }, set current(value) { selectedEdgeId = value; } },
    setImageNodeFromResult,
    setSelectedNodes,
    syncNodeEdgeStroke,
    updateLayoutInputCount,
    updateConnectionProximity: target => canvasConnectionFeedback.updateProximity(target),
    updateUpscaleInputCount,
    videoInputRoleForSource,
  });

  const canvasConnectionFeedback = window.DesktopCanvasConnectionFeedback.create({
    activeInteractionRef: { get current() { return activeInteraction; } },
    getNodeState,
    getNodeElement,
    getEdgeVisualPath: edgeId => canvasConnections.getEdgeVisualPath(edgeId),
    refreshNodeConnectionGeometry: nodeId => canvasConnections.refreshNodeConnectionGeometry(nodeId),
    prefersReducedMotion,
  });

  const canvasPortInteraction = window.DesktopCanvasPortInteraction.create({
    discardConnectionFeedback: nodeElement => canvasConnectionFeedback.discardNode(nodeElement),
    FLOATING_DROPLET_PEAK_PX,
    FLOATING_PORT_TRACKING_MARGIN_PX,
    FLOATING_SWELL_BORDER_PADDING_PX,
    FLOATING_SWELL_EDGE_INSET_PX,
    FLOATING_SWELL_EDGE_OUTSET_PX,
    FLOATING_SWELL_LINK_OVERLAP_SCREEN_PX,
    FLOATING_SWELL_MAX_FRAME_DELTA_SECONDS,
    FLOATING_SWELL_PEAK_PX,
    FLOATING_SWELL_VISIBLE_THRESHOLD_PX,
    IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX,
    activeInteractionRef: { get current() { return activeInteraction; }, set current(value) { activeInteraction = value; } },
    buildFloatingDropletPath,
    buildFloatingSwellPath,
    buildFloatingSwellPerimeter,
    clamp,
    closestFloatingSwellSample,
    contextMenuConnectionSourceAnchorRef: { get current() { return contextMenuConnectionSourceAnchor; }, set current(value) { contextMenuConnectionSourceAnchor = value; } },
    contextMenuConnectionSourceIdRef: { get current() { return contextMenuConnectionSourceId; }, set current(value) { contextMenuConnectionSourceId = value; } },
    contextMenuConnectionSourceSideRef: { get current() { return contextMenuConnectionSourceSide; }, set current(value) { contextMenuConnectionSourceSide = value; } },
    contextMenuElRef: { get current() { return contextMenuEl; }, set current(value) { contextMenuEl = value; } },
    els,
    floatingSwellModulo,
    floatingSwellPointAt,
    floatingSwellShortestArcDelta,
    floatingSwellSide,
    floatingSwellSpringAtRest,
    floatingSwellSpringStep,
    getAnchor,
    getNodeState,
    normalizePortSide,
    portOutwardVector,
    prefersReducedMotion,
    refreshContextMenuConnectionPreview,
    renderConnectionPreview,
  });

  const canvasGenerationConfig = window.DesktopCanvasGenerationConfig.create({
    DEFAULT_GOOGLE_MODEL,
    applyGptTaskTypeToNode,
    comfyWorkflowCatalogRef: { get current() { return comfyWorkflowCatalog; }, set current(value) { comfyWorkflowCatalog = value; } },
    comfyWorkflowDefaultSize,
    comfyWorkflowParameterOverrides,
    findConnectedTextNodeId,
    getBatchPromptItems,
    getConnectedImageReferences,
    getNodeElement,
    getNodeReferenceImages,
    getOutgoingUpscaleImageEdges,
    getPromptModeFromNode,
    getProviderFromNode,
    getVisibleInputPrompt,
    mergeNodeReferenceImages,
    normalizeComfyPixelSize,
    normalizePromptGenerationMeta,
    promptTextFingerprint,
    readFormToState,
    readOutputControlsForTask,
    readOutputControlsFromNode,
    splitBatchPromptItems,
    syncUpscaleNodeStateFromDom,
    syncVideoInferenceNodeStateFromDom,
    videoInferenceInputSummary,
  });

  const canvasGeneration = window.DesktopCanvasGeneration.create({
    DEFAULT_VIDEO_INFERENCE_NODE_HEIGHT,
    DEFAULT_VIDEO_INFERENCE_NODE_WIDTH,
    activeImageEditRef: { get current() { return activeImageEdit; }, set current(value) { activeImageEdit = value; } },
    addNode,
    applyNodeLayout,
    buildImageEditPrompt,
    clonePromptDocument,
    closeImageEditor,
    connectNodes,
    ensureTextNodePromptDocument,
    expectedImageOutputCount,
    exportImageEditAnnotatedDataUrl,
    findInputForResult,
    fitVideoNodeToMedia,
    getAnchor,
    getConnectedOutputImageNodeIds,
    getImageNodeSize,
    getNodeBoundsById,
    getNodeElement,
    getOutputImageEdges,
    getRunnableUpscaleNodeIds,
    imageUrlToDataUrl,
    insertImageNode,
    isEmptyAutoOutputImageNode,
    materializePromptDocument,
    normalizeVideoInferenceNodeState,
    openTextPolishModal,
    outputImageReference,
    promptDocumentFingerprint,
    ratioFromAspect,
    ratioToMeta,
    readUpscaleNodeConfigForReference,
    readVideoInferenceNodeConfig,
    refreshUpscaleNodeMode,
    refreshVideoInferenceNode,
    refreshVideoNode,
    sanitizeImageEditFilename,
    saveImageEditState,
    setImageNodeFromResult,
    updateLinkPath,
    videoConfigApi,
    videoTaskPollTimers,
  });

  window.DesktopCanvas = {
    updateTaskProgress: canvasProgress.update,
    listLoRATargets: canvasLoRA.listTargets,
    addLoRAToNode: canvasLoRA.addToNode,
    listLoRATextTargets: canvasLoRA.listTextTargets,
    insertLoRATriggers: canvasLoRA.insertTriggers,
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
    readVideoInferenceNodeConfig,
    runVideoInferenceNode,
    cancelVideoInferenceTask,
    getTaskRegistry: () => taskRegistry,
    refreshVideoInferenceNode,
    refreshVideoNode,
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
    insertPromptBlockToken,
    replacePromptBlockToken,
    materializePromptDocument,
    listTextNodes,
    listPromptImageNodes,
    listPromptVideoNodes,
    listPromptMediaNodes,
    getTextStylePresets,
    createTextStylePreset,
    registerTextStylePresets,
    applyTextStylePresetToTarget,
    refreshLayoutNode,
    getLayoutInputImages,
    createImageNodeFromHistoryItem,
    continueEditFromHistoryItem,
    createImageNodesFromHistoryItems,
    createVideoNodeFromAsset,
    runMusicNode: canvasMusic.run,
    getCancelableMusicTasks: canvasMusic.getCancelableTasks,
    refreshTaskNode: nodeId => { refreshUpscaleNodeMode(nodeId); canvasTopaz.paint(nodeId); },
    getCancelableVideoControlTasks: canvasVideoControl.getCancelableTasks,
    runVideoControlNode: canvasVideoControl.run,
    getCancelableTopazVideoTasks: canvasTopazVideo.getCancelableTasks,
    runTopazVideoNode: canvasTopazVideo.run,
    setAudioNodeResult: canvasAudio.setResult,
    getAudioNodeInput: canvasAudio.getInput,
    importAudioNodeFile: canvasAudio.importFile,
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
