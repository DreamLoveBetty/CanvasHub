// Shared app state and constants
  const DEFAULT_GOOGLE_MODEL = 'gemini-3.1-flash-image';
  const GOOGLE_MODEL_ALIASES = {
    'gemini-3-pro-image-preview': 'gemini-3-pro-image',
    'gemini-3.1-flash-image-preview': 'gemini-3.1-flash-image'
  };

  function normalizeGoogleModel(value, fallback = DEFAULT_GOOGLE_MODEL) {
    const normalized = String(value || '').trim();
    return GOOGLE_MODEL_ALIASES[normalized] || normalized || fallback;
  }

  let genState = { style: 'raw', ratio: '1:1', quality: '2k', model: DEFAULT_GOOGLE_MODEL };
  let editState = { quality: 'hd', ratio: 'auto', feature: 'edit', model: DEFAULT_GOOGLE_MODEL };
  let gptState = { ratio: '9:16', resolution: '1k', quality: 'auto', imageCount: 1, moderation: 'auto', gptProviderRoute: 'codex' };
  let comfyState = { ratio: '1:1', workflow: '' };
  const DEFAULT_SKIN = 'skeuo-tech';
  const DEFAULT_LAYOUT_MODE = 'classic';
  const DEFAULT_CINEMATIC_COLOR_SCHEME = 'aether-gold';
  const LEGACY_DEFAULT_SKIN = 'cassette-light';
  const THEME_SCHEMA_VERSION = 2;
  let currentSkin = document.documentElement.dataset.skin || DEFAULT_SKIN;
  let currentLayoutMode = document.documentElement.dataset.layout || DEFAULT_LAYOUT_MODE;
  let currentCinematicColorScheme = document.documentElement.dataset.cinematicColorScheme || DEFAULT_CINEMATIC_COLOR_SCHEME;
  let currentCinematicSection = 'records';
  let currentCinematicProvider = 'google';
  let cinematicStylePinned = false;
  let cinematicPinnedStyleId = '';
  let cinematicActiveStyleLabel = '';
  let cinematicStyleSearch = '';
  let cinematicCustomStyles = [];
  let cinematicStyleOverrides = {};
  let currentCinematicStyleEditorId = null;
  let currentCinematicStyleEditorBuiltin = false;
  let cinematicRevealState = {
    provider: false,
    model: false,
    quality: false,
    gptQuality: false,
    gptCount: false,
    gptModeration: false
  };
  let currentSettingsPanel = null;
  const SETTINGS_STORAGE_KEY = 'miniapp_ui_settings_v1';
  const AVAILABLE_SKINS = ['skeuo-tech', 'cassette-light', 'garden', 'midnight', 'paper'];
  const AVAILABLE_LAYOUT_MODES = ['classic', 'cinematic'];
  const AVAILABLE_CINEMATIC_COLOR_SCHEMES = ['aether-gold', 'production-suite', 'cinematic-lens'];
  const AVAILABLE_CINEMATIC_SECTIONS = ['records', 'discover', 'spell'];
  const AVAILABLE_CINEMATIC_PROVIDERS = ['google', 'comfyui', 'gpt'];
  const CINEMATIC_COLOR_SCHEME_OPTIONS = [
    {
      id: 'aether-gold',
      title: '琥珀片场',
      subtitle: '保留当前的金色电影感基调'
    },
    {
      id: 'production-suite',
      title: 'Production Suite',
      subtitle: '工业橙，像剪辑控制台一样干练'
    },
    {
      id: 'cinematic-lens',
      title: 'Cinematic Lens',
      subtitle: '暗夜绿，更冷静的胶片工作室气质'
    }
  ];
  const DEFAULT_CINEMATIC_STYLE_LIBRARY = [
    { id: 'raw', engineStyle: 'raw', title: 'Raw', description: '保留主体原始质感，适合先搭结构和氛围。', promptTemplate: '主体清晰，构图自然，保留真实质感，光影克制，细节干净。', badge: 'Raw', status: '基础底片', model: DEFAULT_GOOGLE_MODEL, quality: '2k', ratio: '1:1' },
    { id: 'real', engineStyle: 'real', title: '超写实', description: '偏摄影成像和真实材质，适合商业画面。', promptTemplate: '超写实摄影，真实肤质与材质，高动态范围，自然光影，商业级细节。', badge: 'Real', status: '高保真', model: DEFAULT_GOOGLE_MODEL, quality: '4k', ratio: '4:5' },
    { id: 'king_hu', engineStyle: 'king_hu', title: '胡金铨', description: '竹林、留白和武侠动势，电影感更强。', promptTemplate: '胡金铨式东方武侠电影感，竹林与留白，人物身法轻盈，镜头叙事克制。', badge: 'King Hu', status: '东方叙事', model: DEFAULT_GOOGLE_MODEL, quality: '2k', ratio: '16:9' },
    { id: 'shadow', engineStyle: 'shadow', title: '皮影戏风格', description: '高反差剪影与舞台光，适合强图形语言。', promptTemplate: '皮影戏式高反差剪影，边缘清晰，戏剧舞台光，东方叙事氛围。', badge: 'Shadow', status: '戏剧化', model: DEFAULT_GOOGLE_MODEL, quality: '2k', ratio: '16:9' },
    { id: 'dunhuang', engineStyle: 'dunhuang', title: '敦煌', description: '壁画色层与飞天气息，适合东方神话气质。', promptTemplate: '敦煌壁画色彩与飞天意象，矿物色层，东方神话气息，古典装饰细节。', badge: 'Dunhuang', status: '壁画色谱', model: DEFAULT_GOOGLE_MODEL, quality: '2k', ratio: '3:4' },
    { id: 'candlelight', engineStyle: 'candlelight', title: '烛光肖像', description: '暖色低照度人像，适合情绪和近景特写。', promptTemplate: '烛光电影肖像，暖金色低照度，面部光影细腻，情绪化近景。', badge: 'Candle', status: '光影人像', model: DEFAULT_GOOGLE_MODEL, quality: '2k', ratio: '4:5' },
    { id: '3d_info', engineStyle: '3d_info', title: '3D 信息图', description: '结构清晰、信息密度高，适合解释型画面。', promptTemplate: '3D 信息图风格，结构清晰，图文层级明确，解释性强，背景干净。', badge: '3D Info', status: '信息表达', model: DEFAULT_GOOGLE_MODEL, quality: '2k', ratio: '1:1' },
    { id: 'sketchnote', engineStyle: 'sketchnote', title: '知识卡片', description: '偏手绘与笔记感，适合概念整理和轻说明。', promptTemplate: '手绘知识卡片风格，像速写笔记，图文结合，轻松清晰，留有注释感。', badge: 'Sketch', status: '笔记语气', model: DEFAULT_GOOGLE_MODEL, quality: '1k', ratio: '4:5' }
  ];
  const CINEMATIC_MODEL_MAP = {
    pro: 'gemini-3-pro-image',
    fast: 'gemini-3.1-flash-image'
  };
  const CINEMATIC_GEN_QUALITY_OPTIONS = ['1k', '2k', '4k'];
  const CINEMATIC_EDIT_QUALITY_OPTIONS = ['standard', 'hd'];
  const CINEMATIC_RATIO_OPTIONS = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '9:21', '21:9'];
  const SUBMIT_BUTTON_DEFAULTS = {
    btnGen: '✨ 立即生成',
    btnComfy: '🧩 立即生成',
    btnGpt: '🤖 后台生成并发送',
    btnEdit: '✏️ 立即生成'
  };
  const STAGE_TASK_STORAGE_KEYS = {
    gen: 'last_gen_task_id',
    comfy: 'last_comfy_task_id',
    gpt: 'last_gpt_task_id',
    edit: 'last_edit_task_id'
  };
  const STAGE_BUTTON_IDS = {
    gen: 'btnGen',
    comfy: 'btnComfy',
    gpt: 'btnGpt',
    edit: 'btnEdit'
  };
  const STAGE_KEYS = ['gen', 'comfy', 'gpt', 'edit'];
  const STAGE_TYPE_MAP = {
    gen: ['google-gen'],
    comfy: ['comfy'],
    gpt: ['gpt', 'gpt-edit'],
    edit: ['google-edit']
  };
  const IN_FLIGHT_TASK_STATUSES = ['queued', 'preparing', 'processing', 'fallback_running'];
  const STAGE_COPY = {
    gen: {
      idle: {
        hint: '提交后，进度会在这里显示。',
        body: '这里会接住排队、生成中和完成结果。'
      },
      busy: {
        hint: '任务已提交，正在生成。',
        body: '保持当前页面，也能看到状态继续往前走。'
      },
      success: {
        hint: '这次生成已完成。',
        body: '作品已经进历史记录，可以直接回看。'
      },
      error: {
        hint: '这次没有顺利完成。',
        body: '换一下提示词、风格或比例，再试一张。'
      }
    },
    comfy: {
      idle: {
        hint: '提交后，作品会出现在这里。',
        body: '完成后可以直接在这个舞台里看结果。'
      },
      busy: {
        hint: 'ComfyUI 正在跑工作流。',
        body: '节点执行和图片回传还要一点时间。'
      },
      success: {
        hint: '作品已经回来了。',
        body: '现在就能在这里看，也能去历史里再回看。'
      },
      error: {
        hint: '这次没有顺利出图。',
        body: '先检查工作流、输入图和远端服务，再重试。'
      }
    },
    gpt: {
      idle: {
        hint: '提交后台任务后，这里会给反馈。',
        body: '任务提交后，会提示是否进入后台处理。'
      },
      busy: {
        hint: '后台任务已经排上队。',
        body: '就算离开页面，它也会继续往下跑。'
      },
      success: {
        hint: '后台任务提交成功。',
        body: '接下来会继续自动处理，并发到 Telegram。'
      },
      error: {
        hint: '后台任务提交失败。',
        body: '稍后再试，或先看一下网络和代理设置。'
      }
    },
    edit: {
      idle: {
        hint: '提交编辑后，这里会显示状态。',
        body: '上传参考图并提交后，结果会在这里接住。'
      },
      busy: {
        hint: '编辑任务已经提交。',
        body: '素材越多、指令越复杂，通常会更久一点。'
      },
      success: {
        hint: '编辑任务提交成功。',
        body: '接下来作品会继续生成，并进入历史记录。'
      },
      error: {
        hint: '编辑任务提交失败。',
        body: '检查参考图、编辑指令和网络后再试。'
      }
    }
  };

  let uploadedImages = [];
  let currentCinematicMenu = null;
  let cinematicRefClearHoldTimer = null;
  let cinematicRefClearHandled = false;
  const MAX_IMGS = 8;

  let historyRecords = [];
  let historyAdvancedOpen = false;
  const historyFilterState = {
    type: 'all',
    status: 'all',
    time: 'all',
    keyword: '',
    ratio: 'all',
    style: 'all',
    resolution: 'all'
  };

  const HISTORY_TYPE_MAP = {
    'gpt': 'GPT',
    'gpt-edit': 'GPT Edit',
    'google-gen': 'Generate',
    'google-edit': 'Edit',
    'comfy': 'Comfy'
  };

  function setHistoryListMessage(message, tone = 'muted') {
    const list = document.getElementById('sidebarHistoryList');
    if (!list) return;
    list.innerHTML = `<div class="history-list-message${tone === 'error' ? ' is-error' : ''}">${message}</div>`;
  }

  function setCinematicHistoryMessage(title, body = '') {
    const list = document.getElementById('cinematicHistoryList');
    if (!list) return;
    list.innerHTML = `
      <div class="cinematic-empty-state">
        <strong>${title}</strong>
        <p>${body || ''}</p>
      </div>
    `;
  }
