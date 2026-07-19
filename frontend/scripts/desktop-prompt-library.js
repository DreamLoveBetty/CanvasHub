(function () {
  const $ = id => document.getElementById(id);
  const els = {};
  const INSPIRATION_PAGE_SIZE = 200;
  const COLOR_FAVORITES_KEY = 'desk_prompt_color_favorites_v1';
  const COLOR_CUSTOM_KEY = 'desk_prompt_custom_colors_v1';
  const COLOR_CATEGORIES = [
    { id: 'warm', label: '暖色氛围', icon: '暖' },
    { id: 'cool', label: '冷色氛围', icon: '冷' },
    { id: 'neutral', label: '中性色调', icon: '中' },
    { id: 'vivid', label: '高饱和', icon: '亮' },
    { id: 'muted', label: '低饱和', icon: '柔' },
    { id: 'cinematic', label: '电影感', icon: '影' },
  ];
  const COLOR_SCHEMES = [
    { id: 'coral-sunrise', name: '珊瑚日出', description: '珊瑚红与明亮金黄组成有亲和力的活力暖调。', colors: ['#EF476F', '#FF7F50', '#FFD166', '#FFF1D6', '#22333B'], categories: ['warm', 'vivid'], scenes: ['美妆海报', '夏日活动', '生活方式'], tags: ['暖色', '活力', '商业'], prompt: '色彩方案采用珊瑚红、暖橙与明亮金黄，奶油白作为大面积留白，深青灰稳定文字和阴影；整体明快、热情、有亲和力，保持暖色主导与清晰层级。' },
    { id: 'amber-theater', name: '琥珀剧场', description: '深酒红、焦糖与琥珀金营造浓郁戏剧光感。', colors: ['#321B1B', '#7A2525', '#C15F2A', '#E6A756', '#F5E3C3'], categories: ['warm', 'cinematic'], scenes: ['电影海报', '餐饮品牌', '复古肖像'], tags: ['暖色', '戏剧', '质感'], prompt: '色彩方案以深酒红和暗棕为阴影基底，焦糖橙与琥珀金作为主要光色，浅香槟色控制高光；形成浓郁、克制的戏剧氛围和电影级明暗层次。' },
    { id: 'citrus-market', name: '柑橘市集', description: '橘黄、青柠和叶绿构成清爽直接的消费视觉。', colors: ['#FF6B35', '#FFB703', '#D9ED92', '#52B788', '#1B4332'], categories: ['warm', 'vivid'], scenes: ['食品包装', '市集活动', '社媒物料'], tags: ['清新', '食物', '高饱和'], prompt: '色彩方案使用鲜橙与金黄建立食欲和活力，以青柠浅绿过渡，叶绿和深森林绿平衡画面；色彩清爽、明亮、自然，适合年轻化消费视觉。' },
    { id: 'vintage-film', name: '复古胶片', description: '褪色砖红、芥末黄与灰青复现温和胶片质感。', colors: ['#9E4F3F', '#D29B52', '#E7D9B4', '#6F8A82', '#303B3A'], categories: ['warm', 'muted', 'cinematic'], scenes: ['人文纪实', '咖啡品牌', '旅行画面'], tags: ['复古', '胶片', '低饱和'], prompt: '色彩方案采用褪色砖红、芥末黄和灰青色，搭配旧纸米白与深灰绿；降低整体饱和度和对比，保留温暖颗粒感，呈现自然、怀旧的胶片色彩。' },
    { id: 'porcelain-mist', name: '青瓷薄雾', description: '雾青、浅瓷白和墨绿组成安静通透的东方冷调。', colors: ['#DDEBE7', '#A7C7C0', '#5F8F86', '#2F5D57', '#F7F8F4'], categories: ['cool', 'muted'], scenes: ['东方美学', '护肤产品', '静物摄影'], tags: ['冷色', '东方', '克制'], prompt: '色彩方案以雾青和浅青瓷色为主，墨绿用于细节与文字，柔和瓷白承担留白；整体低饱和、通透、安静，强调东方审美和细腻材质。' },
    { id: 'deep-sea-neon', name: '深海电光', description: '深海蓝与高亮青绿形成锐利的数字视觉。', colors: ['#071A2B', '#0B3C5D', '#00A8A8', '#4DEEEA', '#D8FFFF'], categories: ['cool', 'vivid', 'cinematic'], scenes: ['科技发布', '游戏视觉', '音乐封面'], tags: ['科技', '霓虹', '高对比'], prompt: '色彩方案以深海蓝和藏青作为大面积暗部，高亮青绿与电光蓝用于发光边缘和关键焦点，冰白点亮信息；整体冷峻、锐利，具有深海般纵深与数字霓虹质感。' },
    { id: 'alpine-lake', name: '高山湖泊', description: '湖蓝、松针绿和雪白构成清冽自然的层次。', colors: ['#EAF4F4', '#A8DADC', '#4D908E', '#2D6A4F', '#1D3557'], categories: ['cool', 'muted'], scenes: ['户外品牌', '风景摄影', '健康生活'], tags: ['自然', '清冽', '户外'], prompt: '色彩方案使用雪白与浅湖蓝表现空气感，中层采用灰青色，松针绿和深山蓝稳住远景与文字；整体清冽、自然、层次分明，避免过度饱和。' },
    { id: 'arctic-tech', name: '极地科技', description: '冰白、冷灰蓝与深靛蓝适合清晰精密的信息表达。', colors: ['#F5F9FC', '#C9D8E6', '#7EA3C4', '#24527A', '#102A43'], categories: ['cool', 'neutral'], scenes: ['科技产品', '数据界面', '企业视觉'], tags: ['理性', '专业', '科技'], prompt: '色彩方案以冰白和冷灰蓝构成干净背景，中蓝建立信息层级，深靛蓝用于核心文字和结构；整体理性、精密、清晰，呈现可信赖的现代科技气质。' },
    { id: 'concrete-silver', name: '水泥银灰', description: '多层次银灰搭配炭黑，呈现冷静的工业秩序。', colors: ['#F2F3F4', '#CACFD2', '#909497', '#515A5A', '#1C2833'], categories: ['neutral', 'muted'], scenes: ['建筑画册', '工业产品', '极简版式'], tags: ['中性', '工业', '极简'], prompt: '色彩方案使用从银白到水泥灰的连续层次，并以炭黑建立最大对比；不引入明显色相，突出结构、材质和留白，整体冷静、精确、具有工业秩序。' },
    { id: 'graphite-mono', name: '石墨单色', description: '石墨黑、纸白和中间灰构成高识别度的单色系统。', colors: ['#111111', '#343434', '#737373', '#BDBDBD', '#F4F4F2'], categories: ['neutral'], scenes: ['时尚大片', '字体海报', '作品集'], tags: ['黑白', '单色', '高对比'], prompt: '色彩方案限定为石墨黑、炭灰、中灰、浅灰和纸白，通过明度而非色相建立层级；保持轮廓利落、留白明确，呈现经典、克制的高对比单色视觉。' },
    { id: 'morandi-garden', name: '莫兰迪花园', description: '灰粉、鼠尾草与雾蓝组合出温柔平衡的低饱和色域。', colors: ['#C9A9A6', '#D8C7B5', '#A8B5A2', '#8FA3AD', '#545B62'], categories: ['neutral', 'muted'], scenes: ['家居软装', '女性品牌', '生活摄影'], tags: ['柔和', '低饱和', '生活感'], prompt: '色彩方案采用灰粉、浅灰褐、鼠尾草绿与雾蓝，深灰仅用于必要的视觉锚点；统一降低饱和度和反差，营造温柔、耐看、平衡的生活美学。' },
    { id: 'cream-black-gold', name: '奶油黑金', description: '柔和象牙白、墨黑与克制金色形成高级商业对比。', colors: ['#F7F1E3', '#D6C6A5', '#B08D57', '#34312D', '#111111'], categories: ['neutral', 'warm'], scenes: ['奢侈品', '珠宝静物', '高端邀请函'], tags: ['高级', '金色', '商业'], prompt: '色彩方案以象牙白和柔和米色承担大面积背景，墨黑建立清晰结构，古金色仅用于小面积高光和关键细节；整体克制、精致，避免金色泛滥。' },
    { id: 'urban-red-blue', name: '都市红蓝', description: '信号红与深蓝在冷灰背景上形成直接的现代张力。', colors: ['#E63946', '#F1FAEE', '#A8DADC', '#457B9D', '#1D3557'], categories: ['neutral', 'vivid'], scenes: ['品牌海报', '体育视觉', '信息图表'], tags: ['现代', '对比', '品牌'], prompt: '色彩方案使用信号红作为小面积强焦点，深蓝构成稳定主色，浅灰蓝与暖白负责背景和信息分区；整体清晰、现代、有节奏，保持红蓝面积比例克制。' },
    { id: 'violet-noir', name: '紫夜金属', description: '暗紫、蓝黑与冷银高光呈现神秘的夜间质感。', colors: ['#12101C', '#2D1E46', '#654A8E', '#A7A3C2', '#E8E7F0'], categories: ['cool', 'cinematic'], scenes: ['香水广告', '音乐视觉', '夜景时尚'], tags: ['神秘', '夜色', '金属'], prompt: '色彩方案以蓝黑和暗紫构成大面积夜色，中紫控制层次，冷银灰与微亮白塑造金属高光；整体神秘、精致、具有电影夜景的纵深感。' },
    { id: 'desert-cinema', name: '荒漠电影', description: '沙岩、铁锈与深青阴影组成宽银幕式的大地色。', colors: ['#E2C290', '#C67C4E', '#8C3F2B', '#35524A', '#172A2A'], categories: ['warm', 'muted', 'cinematic'], scenes: ['旅行电影', '汽车广告', '叙事概念图'], tags: ['大地色', '宽银幕', '叙事'], prompt: '色彩方案以沙岩浅褐和铁锈红表现受光区域，深青绿与近黑青色压住阴影；降低高光饱和度，保留冷暖对照，形成辽阔、粗粝的宽银幕电影感。' },
  ];
  const COLOR_FORMULAS = [
    { id: 'monochromatic', label: '单色', en: 'Monochromatic', description: '同一色相改变明度与饱和度，最安全统一。', offsets: [0, 0, 0, 0, 0] },
    { id: 'analogous', label: '类似色', en: 'Analogous', description: '选取色轮相邻色，柔和、自然、氛围连贯。', offsets: [0, 30, -30, 15, -15] },
    { id: 'complementary', label: '互补色', en: 'Complementary', description: '使用色轮对向色建立强对比，适合强调 CTA。', offsets: [0, 180, 0, 180, 0] },
    { id: 'split_complementary', label: '分裂互补', en: 'Split-Complementary', description: '主色搭配互补色两侧色相，醒目但更易平衡。', offsets: [0, 150, 210, 30, -30] },
    { id: 'triadic', label: '三色', en: 'Triadic', description: '三个等距色相形成活泼且均衡的视觉。', offsets: [0, 120, 240, 0, 120] },
    { id: 'tetradic', label: '四色', en: 'Tetradic', description: '两组互补色组成矩形，丰富但需要明确主次。', offsets: [0, 60, 180, 240, 0] },
    { id: 'square', label: '方形', en: 'Square', description: '四个等距色相构成动态、现代的大胆组合。', offsets: [0, 90, 180, 270, 0] },
  ];
  const COLOR_INDUSTRIES = [
    { id: 'uiux', label: 'UI / UX 设计', base: '#2563EB', formula: 'monochromatic', scenes: ['界面系统', '数据产品', '交互组件'], tags: ['UI/UX', '可访问性', '产品设计'] },
    { id: 'graphic', label: '平面设计', base: '#E84A5F', formula: 'split_complementary', scenes: ['品牌海报', '视觉物料', '出版设计'], tags: ['平面', '品牌', '视觉传达'] },
    { id: 'web', label: '网页设计', base: '#0F766E', formula: 'analogous', scenes: ['网页界面', '落地页', '内容站点'], tags: ['网页', '数字产品', '响应式'] },
    { id: 'product', label: '产品设计', base: '#334155', formula: 'monochromatic', scenes: ['工业产品', '产品界面', '设计系统'], tags: ['产品', '专业', '系统化'] },
    { id: 'brand', label: '品牌设计', base: '#6D28D9', formula: 'triadic', scenes: ['品牌系统', '营销活动', '包装设计'], tags: ['品牌', '识别度', '商业'] },
    { id: 'fashion', label: '时尚与年轻品牌', base: '#EC4899', formula: 'complementary', scenes: ['时尚视觉', '年轻品牌', '社媒活动'], tags: ['时尚', '年轻', '高识别度'] },
    { id: 'illustration', label: '插画与创意', base: '#F97316', formula: 'analogous', scenes: ['商业插画', '角色视觉', '创意海报'], tags: ['插画', '创意', '叙事'] },
    { id: 'finance', label: '科技与金融', base: '#1D4ED8', formula: 'monochromatic', scenes: ['金融产品', '科技品牌', '企业视觉'], tags: ['科技', '金融', '可信赖'] },
    { id: 'health', label: '健康与自然', base: '#2F855A', formula: 'analogous', scenes: ['健康产品', '自然品牌', '环保视觉'], tags: ['健康', '自然', '可持续'] },
  ];
  const BLOOM_PETALS = [
    ...['#F7C13F', '#F2A23C', '#EE8440', '#E96544', '#E84C3F', '#E03E66', '#D23C92', '#A24FC8', '#7B5FD4', '#4E72D6', '#3DA1B8', '#5FB95B']
      .map((color, index) => ({ key: `outer-${index}`, ring: 'outer', color })),
    ...['#F6E6A4', '#F4D0B0', '#F1C1C4', '#E3C4DE', '#CCC9EC', '#C6E0C9']
      .map((color, index) => ({ key: `inner-${index}`, ring: 'inner', color })),
    { key: 'center', ring: 'center', color: '#FFFFFF' },
  ];
  function newColorAnalysisState() {
    return {
      open: false,
      busy: false,
      requestId: 0,
      sourceBlob: null,
      previewUrl: '',
      previewObjectUrl: '',
      fileName: '',
      sourceKind: '',
      mode: 'balanced',
      result: null,
      error: '',
    };
  }
  const state = {
    workspace: 'blocks',
    blocks: [],
    templates: [],
    colors: [],
    sources: [],
    inspiration: [],
    selected: { blocks: '', templates: '', colors: '', inspiration: '' },
    category: { blocks: 'all', templates: 'all', colors: 'all', inspiration: 'all' },
    favoriteOnly: false,
    loading: false,
    inspirationLoaded: false,
    inspirationTotal: 0,
    inspirationFilterKey: '',
    inspirationRequestId: 0,
    inspirationLoading: false,
    inspirationLoadingMore: false,
    inspirationSearchTimer: 0,
    inspirationImageIndex: {},
    blockDraft: null,
    blockBaseline: null,
    blockSaveBusy: false,
    blockWriteAction: '',
    blockSaveCounter: 0,
    ruleDraft: null,
    ruleBaseline: null,
    ruleSaveBusy: false,
    ruleWriteAction: '',
    colorDraft: null,
    colorDraftBaseline: null,
    colorBloomOpen: false,
    colorAnalysis: newColorAnalysisState(),
    extractorFocus: null,
    extractorSessionCounter: 0,
    extractorFileCounter: 0,
    extractorDrafts: { text: null, image: null },
    extractor: {
      open: false,
      mode: 'text',
      busy: false,
      busyAction: '',
      text: '',
      direction: '',
      primaryType: '',
      imageData: '',
      imageName: '',
      imageType: '',
      candidates: [],
      error: '',
      sourceTitle: '',
    },
  };

  const TYPE_ICONS = {
    all: '⌘', portrait: '人', landscape: '景', product: '物', food: '食', architecture: '筑',
    interior: '室', character: '角', scene_concept: '境', animal: '宠', fashion: '装', storyboard: '镜',
    illustration: '画', poster: '报', social: '媒', infographic: '图', three_d: '3D', pattern: '纹'
  };
  const TYPE_LABELS = {
    portrait: '人像人物', landscape: '风景自然', product: '商品电商', food: '美食餐饮', architecture: '建筑外观',
    interior: '室内空间', character: '角色设计', scene_concept: '场景概念', animal: '动物宠物', fashion: '服装时尚',
    storyboard: '影视分镜', illustration: '插画漫画', poster: '海报与 KV', social: '品牌社媒', infographic: '信息图表',
    three_d: '3D 视觉', pattern: '图案纹理'
  };
  const MODULE_LABELS = {
    raw: '原始提示词', custom: '自定义', identity: '身份', appearance: '外貌', pose: '动作姿态', expression: '表情视线',
    clothing: '服装造型', makeup_hair: '妆发', accessories: '配饰', subject: '主体', scene: '场景环境', composition: '构图',
    camera: '视角与镜头', lighting: '光线', color: '色彩', style: '视觉风格', material: '材质细节', quality: '质量要求',
    constraints: '负面约束', goal: '生成目标'
  };

  function collectElements() {
    [
      'deskPromptLibraryPanel', 'deskPromptLibraryNewBtn',
      'deskPromptLibraryRefreshBtn', 'deskPromptLibraryCloseBtn', 'deskPromptLibraryTabs', 'deskPromptLibraryNav',
      'deskPromptLibrarySearchInput', 'deskPromptLibraryFavoriteFilter', 'deskPromptLibraryListTitle',
      'deskPromptLibraryCount', 'deskPromptLibraryList', 'deskPromptLibraryEditor', 'deskPromptLibraryWorkspace'
    ].forEach(id => { els[id] = $(id); });
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }
  function cleanText(value) { return String(value || '').trim(); }
  function safeColor(value) { const color = String(value || '').toUpperCase(); return /^#[0-9A-F]{6}$/.test(color) ? color : '#000000'; }
  function colorTextColor(value) {
    const color = safeColor(value).slice(1);
    const channels = [0, 2, 4].map(index => parseInt(color.slice(index, index + 2), 16) / 255).map(channel => channel <= .03928 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
    return (.2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2]) > .38 ? '#17202A' : '#FFFFFF';
  }
  function clamp(value, min, max) { return Math.min(max, Math.max(min, Number(value) || 0)); }
  function normalizeHue(value) { return ((Number(value) % 360) + 360) % 360; }
  function hexToHsl(value) {
    const hex = safeColor(value).slice(1);
    const [r, g, b] = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16) / 255);
    const max = Math.max(r, g, b); const min = Math.min(r, g, b); const delta = max - min;
    let h = 0;
    if (delta) {
      if (max === r) h = 60 * (((g - b) / delta) % 6);
      else if (max === g) h = 60 * ((b - r) / delta + 2);
      else h = 60 * ((r - g) / delta + 4);
    }
    const l = (max + min) / 2;
    const s = delta ? delta / (1 - Math.abs(2 * l - 1)) : 0;
    return { h: normalizeHue(h), s: s * 100, l: l * 100 };
  }
  function hslToHex(h, s, l) {
    const hue = normalizeHue(h); const saturation = clamp(s, 0, 100) / 100; const lightness = clamp(l, 0, 100) / 100;
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const x = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
    const m = lightness - chroma / 2;
    let channels = hue < 60 ? [chroma, x, 0] : hue < 120 ? [x, chroma, 0] : hue < 180 ? [0, chroma, x] : hue < 240 ? [0, x, chroma] : hue < 300 ? [x, 0, chroma] : [chroma, 0, x];
    return `#${channels.map(channel => Math.round((channel + m) * 255).toString(16).padStart(2, '0')).join('')}`.toUpperCase();
  }
  function hueDistance(first, second) {
    const delta = Math.abs(normalizeHue(first) - normalizeHue(second));
    return Math.min(delta, 360 - delta);
  }
  function bloomSelectedPetalKey(color) {
    const current = hexToHsl(color);
    if (current.s < 8) return 'center';
    return BLOOM_PETALS.filter(petal => petal.ring !== 'center').reduce((best, petal) => {
      const candidate = hexToHsl(petal.color);
      const score = hueDistance(current.h, candidate.h) + Math.abs(current.s - candidate.s) * .55;
      return !best || score < best.score ? { key: petal.key, score } : best;
    }, null)?.key || 'center';
  }
  function bloomLightnessPoint(lightness) {
    const t = clamp((100 - lightness) / 100, 0, 1);
    const radius = 118;
    const halfChord = 62;
    const centerY = 74;
    const centerX = 12 - Math.sqrt(radius ** 2 - halfChord ** 2);
    const y = 12 + halfChord * 2 * t;
    return {
      x: centerX + Math.sqrt(Math.max(0, radius ** 2 - (y - centerY) ** 2)),
      y,
    };
  }
  function colorLuminance(value) {
    const hex = safeColor(value).slice(1);
    const channels = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16) / 255).map(channel => channel <= .03928 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
    return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
  }
  function contrastRatio(foreground, background) {
    const values = [colorLuminance(foreground), colorLuminance(background)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
  }
  function colorFormula(id) { return COLOR_FORMULAS.find(item => item.id === id) || COLOR_FORMULAS[0]; }
  function colorIndustry(id) { return COLOR_INDUSTRIES.find(item => item.id === id) || COLOR_INDUSTRIES[0]; }
  function blendHue(hue, target, amount) {
    const delta = ((normalizeHue(target) - normalizeHue(hue) + 540) % 360) - 180;
    return normalizeHue(hue + delta * amount);
  }
  function generateFormulaColors(baseColor, formulaId, contrast = 'balanced', neutralBalance = true, temperature = 'auto') {
    const base = hexToHsl(baseColor);
    const formula = colorFormula(formulaId);
    const contrastSettings = {
      soft: { saturation: -18, lightness: [4, 13, -5, 23, -20] },
      balanced: { saturation: 0, lightness: [0, 12, -8, 32, -28] },
      high: { saturation: 10, lightness: [-4, 18, -14, 42, -36] },
    }[contrast] || { saturation: 0, lightness: [0, 12, -8, 32, -28] };
    const baseLightness = clamp(base.l, 34, 62);
    const colors = formula.offsets.map((offset, index) => hslToHex(
      index && temperature !== 'auto' ? blendHue(base.h + offset, temperature === 'warm' ? 35 : 210, .18) : base.h + offset,
      base.s + contrastSettings.saturation - (index > 2 ? 8 : 0),
      baseLightness + contrastSettings.lightness[index]
    ));
    if (neutralBalance) {
      colors[3] = hslToHex(base.h, Math.min(16, base.s * .22), contrast === 'high' ? 96 : 92);
      colors[4] = hslToHex(base.h, Math.min(28, base.s * .36), contrast === 'soft' ? 24 : 16);
    }
    return colors.map(safeColor);
  }
  function inferColorCategories(colors) {
    const values = colors.map(hexToHsl);
    const averageSaturation = values.reduce((sum, item) => sum + item.s, 0) / Math.max(1, values.length);
    const warm = values.filter(item => item.h <= 75 || item.h >= 330).length;
    const cool = values.filter(item => item.h >= 150 && item.h <= 285).length;
    const categories = [warm > cool ? 'warm' : cool > warm ? 'cool' : 'neutral'];
    if (averageSaturation >= 58) categories.push('vivid');
    if (averageSaturation <= 42) categories.push('muted');
    const lightness = values.map(item => item.l);
    if (Math.min(...lightness) <= 22 && Math.max(...lightness) >= 78 && averageSaturation >= 32) categories.push('cinematic');
    return Array.from(new Set(categories));
  }
  function draftDescription(draft) {
    const formula = colorFormula(draft.formula); const industry = colorIndustry(draft.industry);
    const temperature = draft.temperature === 'warm' ? '偏暖' : draft.temperature === 'cool' ? '偏冷' : '冷暖均衡';
    return `${formula.label}配色，以 ${safeColor(draft.base_color)} 为基色，${temperature}，面向${industry.label}的可复用色彩系统。`;
  }
  function draftPrompt(draft) {
    const formula = colorFormula(draft.formula); const industry = colorIndustry(draft.industry); const colors = draft.colors.map(safeColor);
    const ratio = draft.use_ratio ? '按照 60% 主色、30% 辅色、10% 点缀色控制核心色彩比例；' : '';
    const neutral = draft.neutral_balance ? '使用浅色与深色中性色平衡背景、文字和留白；' : '';
    const temperature = draft.temperature === 'warm' ? '整体保持暖色倾向；' : draft.temperature === 'cool' ? '整体保持冷色倾向；' : '';
    return `色彩方案采用${formula.label}（${formula.en}）公式，以 ${colors[0]} 为主色、${colors[1]} 为辅色、${colors[2]} 为点缀色，配套 ${colors[3]} 与 ${colors[4]}。${ratio}${neutral}${temperature}适用于${industry.label}，保持清晰主次、稳定可读性与一致的品牌情绪。`;
  }
  function normalizeCustomColor(item) {
    if (!item || typeof item !== 'object') return null;
    const colors = (Array.isArray(item.colors) ? item.colors : []).filter(color => /^#[0-9a-f]{6}$/i.test(String(color || ''))).slice(0, 5).map(safeColor);
    if (colors.length < 3) return null;
    while (colors.length < 5) colors.push(colors[colors.length - 1]);
    const industry = colorIndustry(item.industry).id; const formula = colorFormula(item.formula).id;
    return {
      id: cleanText(item.id).slice(0, 100) || `custom-color-${Date.now().toString(36)}`,
      name: cleanText(item.name).slice(0, 100) || '自定义配色',
      description: cleanText(item.description).slice(0, 500) || '手动创建的自定义配色方案。',
      colors,
      categories: inferColorCategories(colors),
      scenes: parseTags(item.scenes).slice(0, 8),
      tags: parseTags(item.tags).slice(0, 12),
      prompt: cleanText(item.prompt).slice(0, 4000) || '使用此配色方案并保持明确的色彩层级。',
      industry,
      formula,
      base_color: safeColor(item.base_color || colors[0]),
      contrast: ['soft', 'balanced', 'high'].includes(item.contrast) ? item.contrast : 'balanced',
      temperature: ['auto', 'warm', 'cool'].includes(item.temperature) ? item.temperature : 'auto',
      neutral_balance: item.neutral_balance !== false,
      use_ratio: item.use_ratio !== false,
      custom: true,
    };
  }
  function loadColorSchemes() {
    let favorites = new Set();
    let custom = [];
    try {
      const stored = JSON.parse(window.localStorage?.getItem(COLOR_FAVORITES_KEY) || '[]');
      if (Array.isArray(stored)) favorites = new Set(stored.map(String));
    } catch (error) {}
    try {
      const stored = JSON.parse(window.localStorage?.getItem(COLOR_CUSTOM_KEY) || '[]');
      if (Array.isArray(stored)) custom = stored.map(normalizeCustomColor).filter(Boolean);
    } catch (error) {}
    const builtIn = COLOR_SCHEMES.map(item => ({ ...item, colors: item.colors.map(safeColor), custom: false }));
    state.colors = [...custom, ...builtIn].map(item => ({ ...item, favorite: favorites.has(item.id) }));
    if (!state.selected.colors) state.selected.colors = itemId(state.colors[0]);
  }
  function saveColorFavorites() {
    try { window.localStorage?.setItem(COLOR_FAVORITES_KEY, JSON.stringify(state.colors.filter(item => item.favorite).map(item => item.id))); }
    catch (error) {}
  }
  function saveCustomColors() {
    try { window.localStorage?.setItem(COLOR_CUSTOM_KEY, JSON.stringify(state.colors.filter(item => item.custom).map(item => ({ ...item, favorite: undefined })))); }
    catch (error) { throw new Error('无法保存自定义配色方案'); }
  }
  function createColorDraft(source = null, duplicate = false) {
    const industry = source ? colorIndustry(source.industry) : COLOR_INDUSTRIES[0];
    const inferredFormula = source?.formula || (source?.categories?.includes('neutral') ? 'monochromatic' : source?.categories?.includes('vivid') ? 'split_complementary' : 'analogous');
    const formula = source ? colorFormula(inferredFormula) : colorFormula(industry.formula);
    const draft = {
      id: source && !duplicate ? itemId(source) : '',
      name: source ? `${source.name}${duplicate ? ' 副本' : ''}` : '',
      industry: industry.id,
      formula: formula.id,
      base_color: safeColor(source?.base_color || source?.colors?.[0] || industry.base),
      contrast: source?.contrast || 'balanced',
      temperature: source?.temperature || 'auto',
      neutral_balance: source?.neutral_balance !== false,
      use_ratio: source?.use_ratio !== false,
      colors: source?.colors?.length ? source.colors.slice(0, 5).map(safeColor) : [],
      description: cleanText(source?.description),
      scenes: source?.scenes || industry.scenes,
      tags: source?.tags || industry.tags,
      prompt: cleanText(source?.prompt),
      custom: true,
    };
    if (!draft.colors.length) draft.colors = generateFormulaColors(draft.base_color, draft.formula, draft.contrast, draft.neutral_balance, draft.temperature);
    if (!draft.description) draft.description = draftDescription(draft);
    if (!draft.prompt) draft.prompt = draftPrompt(draft);
    return draft;
  }
  function colorDraftFingerprint(draft) {
    if (!draft) return '';
    return JSON.stringify({ ...draft, colors: (draft.colors || []).map(safeColor), scenes: parseTags(draft.scenes), tags: parseTags(draft.tags) });
  }
  function setColorDraft(draft) {
    resetColorAnalysis();
    state.colorDraft = JSON.parse(JSON.stringify(draft));
    state.colorDraftBaseline = colorDraftFingerprint(state.colorDraft);
    state.colorBloomOpen = false;
  }
  function newExtractorState(mode = 'text', options = {}) {
    return { open: false, mode, busy: false, busyAction: '', text: options.text || '', direction: '', primaryType: options.primaryType || '', ruleId: options.ruleId || '', splitRule: options.splitRule || null, imageData: '', imageName: '', imageType: '', candidates: [], error: '', sourceTitle: options.sourceTitle || '' };
  }
  function extractorHasWork(extractor) {
    return !!(extractor && (extractor.text || extractor.direction || extractor.imageData || extractor.candidates?.length));
  }
  function allExtractorStates() {
    return Array.from(new Set([state.extractor, state.extractorDrafts.text, state.extractorDrafts.image].filter(Boolean)));
  }
  function isWriteBusy() {
    return state.blockSaveBusy || state.ruleSaveBusy || (state.extractor.busy && state.extractor.busyAction === 'save');
  }
  function guardWriteBusy() {
    if (!isWriteBusy()) return false;
    notify(state.ruleSaveBusy ? '正在保存拆分规则，请稍候。' : '正在保存素材块，请稍候。', 'warning');
    return true;
  }
  function updateWriteControls() {
    const writeBusy = isWriteBusy();
    if (els.deskPromptLibraryNewBtn) els.deskPromptLibraryNewBtn.disabled = writeBusy;
    if (els.deskPromptLibraryRefreshBtn) els.deskPromptLibraryRefreshBtn.disabled = writeBusy;
    if (els.deskPromptLibraryCloseBtn) els.deskPromptLibraryCloseBtn.disabled = writeBusy;
  }
  function parseTags(value) {
    const items = Array.isArray(value) ? value : String(value || '').split(/[,，;；\n]+/);
    return items.map(item => cleanText(item).replace(/^#+/, '')).filter((item, index, all) => item && all.indexOf(item) === index).slice(0, 30);
  }
  function formatDate(timestamp) {
    if (!Number(timestamp)) return '';
    try { return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(new Date(Number(timestamp) * 1000)); }
    catch (error) { return ''; }
  }
  function notify(message, tone = 'success') { window.DesktopResults?.showTransientMessage?.(message, tone); }
  function reportError(error, fallback = '素材块操作失败') {
    console.error('[PromptLibrary]', error);
    if (window.DesktopResults?.showError) window.DesktopResults.showError(error instanceof Error ? error : new Error(String(error || fallback)));
    else notify(`${fallback}：${error?.message || error || '未知错误'}`, 'error');
  }
  function setBusy(button, busy) { if (button) button.disabled = !!busy; }
  function typeLabel(id) { return TYPE_LABELS[id] || state.templates.find(item => item.primary_type === id)?.name || id || '通用'; }
  function moduleLabel(id) {
    for (const template of state.templates) {
      const found = (template.modules || []).find(item => item.key === id);
      if (found) return found.label;
    }
    return MODULE_LABELS[id] || id || '自定义';
  }
  function itemId(item) { return String(item?.id || item?.itemId || item?.slug || ''); }
  function currentItem() {
    const list = state.workspace === 'blocks' ? state.blocks : state.workspace === 'templates' ? state.templates : state.workspace === 'colors' ? state.colors : state.inspiration;
    return list.find(item => itemId(item) === state.selected[state.workspace]) || null;
  }
  function sourceImageUrl(path) {
    const value = cleanText(path);
    if (!value) return '';
    if (/^(?:data:|https?:|\/)/i.test(value)) return value;
    return `/source_image/${value.split('/').map(part => encodeURIComponent(part)).join('/')}`;
  }
  function sourceImages(item) {
    const candidates = [
      item?.imageUrl,
      item?.imagePath,
      ...(Array.isArray(item?.imageUrls) ? item.imageUrls : []),
      ...(Array.isArray(item?.imagePaths) ? item.imagePaths.map(sourceImageUrl) : []),
    ];
    const seen = new Set();
    const images = [];
    candidates.map(sourceImageUrl).filter(Boolean).forEach(url => {
      let key = url;
      try { key = decodeURIComponent(new URL(url, window.location.origin).pathname); } catch (error) { try { key = decodeURIComponent(url); } catch (decodeError) {} }
      if (seen.has(key)) return;
      seen.add(key); images.push(url);
    });
    return images;
  }
  function sourceImage(item) {
    const images = sourceImages(item);
    const index = Math.max(0, Math.min(images.length - 1, Number(state.inspirationImageIndex[itemId(item)] || 0)));
    return images[index] || item?.thumbUrl || '';
  }
  function sourceThumb(item) { return item?.thumbUrl || item?.imageUrl || item?.imagePath || ''; }
  function refreshSelects() { requestAnimationFrame(() => window.DesktopSelect?.refreshAll?.()); }

  function typeOptions(selected, includeAuto = false) {
    return `${includeAuto ? `<option value="" ${selected ? '' : 'selected'}>自动判断</option>` : ''}${state.templates.map(template => `<option value="${escapeHtml(template.primary_type)}" ${template.primary_type === selected ? 'selected' : ''}>${escapeHtml(template.name)}</option>`).join('')}`;
  }
  function moduleTypeOptions(selected) {
    const modules = new Map();
    state.templates.forEach(template => (template.modules || []).forEach(module => modules.set(module.key, module.label)));
    Object.entries(MODULE_LABELS).forEach(([key, label]) => modules.set(key, label));
    return Array.from(modules.entries()).map(([id, label]) => `<option value="${escapeHtml(id)}" ${id === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('');
  }
  function countsBy(items, key) {
    const counts = {};
    items.forEach(item => { const value = item?.[key] || 'other'; counts[value] = (counts[value] || 0) + 1; });
    return counts;
  }
  function navButton(id, label, count, icon) {
    const active = state.category[state.workspace] === id;
    return `<button type="button" class="${active ? 'is-active' : ''}" data-prompt-category="${escapeHtml(id)}">
      <span class="desk-prompt-library__nav-icon">${escapeHtml(icon || TYPE_ICONS[id] || '·')}</span>
      <span>${escapeHtml(label)}</span>${Number.isFinite(count) ? `<span class="desk-prompt-library__nav-count">${count}</span>` : ''}
    </button>`;
  }

  function renderNav() {
    if (!els.deskPromptLibraryNav) return;
    if (state.workspace === 'blocks') {
      const counts = countsBy(state.blocks, 'module_type');
      const preferred = ['identity', 'appearance', 'pose', 'expression', 'clothing', 'makeup_hair', 'accessories', 'subject', 'scene', 'composition', 'camera', 'lighting', 'color', 'style', 'material', 'quality', 'constraints', 'custom'];
      const keys = Object.keys(counts).sort((a, b) => (preferred.indexOf(a) < 0 ? 99 : preferred.indexOf(a)) - (preferred.indexOf(b) < 0 ? 99 : preferred.indexOf(b)) || moduleLabel(a).localeCompare(moduleLabel(b), 'zh-CN'));
      els.deskPromptLibraryNav.innerHTML = `<div class="desk-prompt-library__nav-group"><div class="desk-prompt-library__nav-label">素材模块</div>
        ${navButton('all', '全部素材块', state.blocks.length, '/')}
        ${keys.map(key => navButton(key, moduleLabel(key), counts[key], moduleLabel(key).slice(0, 1))).join('')}</div>`;
      return;
    }
    if (state.workspace === 'templates') {
      const systemRules = state.templates.filter(item => item.system);
      els.deskPromptLibraryNav.innerHTML = `<div class="desk-prompt-library__nav-group"><div class="desk-prompt-library__nav-label">内容类型</div>
        ${navButton('all', '全部规则', state.templates.length, '⌘')}
        ${systemRules.map(item => navButton(item.primary_type, item.name, null, TYPE_ICONS[item.primary_type])).join('')}</div>`;
      return;
    }
    if (state.workspace === 'colors') {
      const counts = {};
      state.colors.forEach(item => (item.categories || []).forEach(category => { counts[category] = (counts[category] || 0) + 1; }));
      els.deskPromptLibraryNav.innerHTML = `<div class="desk-prompt-library__nav-group"><div class="desk-prompt-library__nav-label">色彩气质</div>
        ${navButton('all', '全部方案', state.colors.length, '#')}
        ${COLOR_CATEGORIES.map(category => navButton(category.id, category.label, counts[category.id] || 0, category.icon)).join('')}</div>`;
      return;
    }
    const total = state.sources.reduce((sum, source) => sum + Number(source.itemCount || 0), 0);
    els.deskPromptLibraryNav.innerHTML = `<div class="desk-prompt-library__nav-group"><div class="desk-prompt-library__nav-label">提示词来源</div>
      ${navButton('all', '全部来源', total, '∞')}
      ${state.sources.map(source => navButton(source.slug, source.name, Number(source.itemCount || 0), '↗')).join('')}</div>`;
  }

  function filteredItems() {
    const query = cleanText(els.deskPromptLibrarySearchInput?.value).toLowerCase();
    const category = state.category[state.workspace];
    const source = state.workspace === 'blocks' ? state.blocks : state.workspace === 'templates' ? state.templates : state.workspace === 'colors' ? state.colors : state.inspiration;
    if (state.workspace === 'inspiration') return source;
    return source.filter(item => {
      if (state.workspace === 'blocks' && category !== 'all' && item.module_type !== category) return false;
      if (state.workspace === 'templates' && category !== 'all' && item.primary_type !== category) return false;
      if (state.workspace === 'colors' && category !== 'all' && !(item.categories || []).includes(category)) return false;
      if (state.favoriteOnly && ['blocks', 'colors'].includes(state.workspace) && !item.favorite) return false;
      if (!query) return true;
      return [item.name, item.title, item.content, item.prompt, item.description, item.module_type, item.primary_type, ...(item.colors || []), ...(item.scenes || []), ...(item.tags || [])].join('\n').toLowerCase().includes(query);
    });
  }
  function reconcileColorSelection() {
    if (state.workspace !== 'colors') return;
    const items = filteredItems();
    if (!items.some(item => itemId(item) === state.selected.colors)) state.selected.colors = itemId(items[0]);
  }

  function rowHtml(item) {
    const id = itemId(item);
    const selected = state.selected[state.workspace] === id;
    if (state.workspace === 'colors') {
      return `<button type="button" class="desk-prompt-library-row desk-prompt-library-row--color ${selected ? 'is-selected' : ''}" data-prompt-item-id="${escapeHtml(id)}">
        <span class="desk-prompt-library-row__main"><span class="desk-prompt-library-row__palette" aria-label="${escapeHtml(item.colors.join('、'))}">${item.colors.map(color => `<i style="background:${safeColor(color)}"></i>`).join('')}</span><span class="desk-prompt-library-row__title"><strong data-i18n-skip>${escapeHtml(item.name)}</strong>${item.favorite ? '<span class="desk-prompt-library-row__star">★</span>' : ''}</span><span class="desk-prompt-library-row__preview" data-i18n-skip>${escapeHtml(item.description)}</span><span class="desk-prompt-library-row__meta">${item.custom ? '<span>自定义</span>' : ''}${(item.tags || []).slice(0, item.custom ? 1 : 2).map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</span></span>
        <span class="desk-prompt-library-row__side"><span>${item.colors.length} 色</span><span class="desk-prompt-library-row__insert" data-prompt-row-action="primary"># 插入</span></span>
      </button>`;
    }
    if (state.workspace === 'inspiration') {
      const thumb = sourceThumb(item);
      return `<button type="button" class="desk-prompt-library-row desk-prompt-library-row--inspiration ${selected ? 'is-selected' : ''}" data-prompt-item-id="${escapeHtml(id)}">
        <span class="desk-prompt-library-row__thumb">${thumb ? `<img src="${escapeHtml(thumb)}" alt="" loading="lazy" decoding="async">` : '<span>无图</span>'}</span>
        <span class="desk-prompt-library-row__main"><span class="desk-prompt-library-row__title"><strong data-i18n-skip>${escapeHtml(item.title || '远程提示词')}</strong></span><span class="desk-prompt-library-row__preview" data-i18n-skip>${escapeHtml(item.prompt || '暂无提示词')}</span><span class="desk-prompt-library-row__meta"><span>${escapeHtml(item.sourceName || item.sourceSlug || '远程源')}</span>${(item.tags || []).slice(0, 1).map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</span></span>
        <span class="desk-prompt-library-row__side"><span>${escapeHtml(formatDate(item.updatedAt))}</span><span class="desk-prompt-library-row__insert" data-prompt-row-action="primary">拆分</span></span>
      </button>`;
    }
    const isBlock = state.workspace === 'blocks';
    const title = isBlock ? item.name : item.name;
    const preview = isBlock ? (item.compact_content || item.content) : item.description;
    const meta = isBlock
      ? [moduleLabel(item.module_type), ...(item.applicable_types || []).slice(0, 1).map(typeLabel), ...(item.tags || []).slice(0, 1)]
      : [`${(item.modules || []).filter(module => module.enabled !== false).length} 个模块`, item.system ? '内置规则' : `自定义 v${Number(item.version || 1)}`];
    const side = isBlock ? (item.use_count ? `${item.use_count} 次` : formatDate(item.updated_at)) : '';
    return `<button type="button" class="desk-prompt-library-row ${selected ? 'is-selected' : ''}" data-prompt-item-id="${escapeHtml(id)}">
      <span class="desk-prompt-library-row__main"><span class="desk-prompt-library-row__title"><strong data-i18n-skip>${escapeHtml(title || '未命名')}</strong>${item.favorite ? '<span class="desk-prompt-library-row__star">★</span>' : ''}</span><span class="desk-prompt-library-row__preview" data-i18n-skip>${escapeHtml(preview || '暂无内容')}</span><span class="desk-prompt-library-row__meta">${meta.filter(Boolean).map(value => `<span>${escapeHtml(value)}</span>`).join('')}</span></span>
      <span class="desk-prompt-library-row__side"><span>${escapeHtml(side)}</span><span class="desk-prompt-library-row__insert" data-prompt-row-action="primary">${isBlock ? '/ 插入' : '拆分'}</span></span>
    </button>`;
  }

  function renderList() {
    if (!els.deskPromptLibraryList) return;
    const titles = { blocks: '可复用素材块', templates: '拆分规则', colors: '色彩方案', inspiration: '灵感条目' };
    if (els.deskPromptLibraryListTitle) els.deskPromptLibraryListTitle.textContent = titles[state.workspace];
    if (state.loading || (state.workspace === 'inspiration' && state.inspirationLoading && !state.inspiration.length)) {
      els.deskPromptLibraryList.innerHTML = '<div class="desk-prompt-library__empty">正在读取…</div>';
      if (els.deskPromptLibraryCount) els.deskPromptLibraryCount.textContent = '读取中';
      return;
    }
    const items = filteredItems();
    const total = state.workspace === 'inspiration' ? Math.max(items.length, state.inspirationTotal) : items.length;
    if (els.deskPromptLibraryCount) els.deskPromptLibraryCount.textContent = total > items.length ? `${items.length} / ${total} 项` : `${items.length} 项`;
    els.deskPromptLibraryList.innerHTML = items.length
      ? `${items.map(rowHtml).join('')}${state.workspace === 'inspiration' && total > items.length ? `<button type="button" class="desk-prompt-library__load-more" data-prompt-load-more ${state.inspirationLoadingMore ? 'disabled' : ''}>${state.inspirationLoadingMore ? '正在读取…' : `再显示 ${Math.min(INSPIRATION_PAGE_SIZE, total - items.length)} 项`}</button>` : ''}`
      : '<div class="desk-prompt-library__empty">当前分类暂无内容。</div>';
  }

  function newBlock(moduleType = '') {
    return { id: '', name: '', module_type: moduleType || (state.category.blocks !== 'all' ? state.category.blocks : 'identity'), content: '', compact_content: '', english_content: '', applicable_types: [], tags: [], favorite: false };
  }
  function createModeTabsHtml(mode) {
    const tabs = [
      { id: 'manual', label: '手动新建', icon: '<path d="M12 5v14M5 12h14"></path>' },
      { id: 'text', label: '拆分提示词', icon: '<path d="M4 6h16M4 12h10M4 18h7"></path><path d="m17 15 3 3-3 3"></path>' },
      { id: 'image', label: '解析图片', icon: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><circle cx="9" cy="10" r="2"></circle><path d="m3 17 5-5 4 4 3-3 6 6"></path>' },
    ];
    return `<div class="desk-prompt-create__modes" role="tablist" aria-label="素材块创建方式">${tabs.map(tab => `<button type="button" id="deskPromptCreateMode${tab.id[0].toUpperCase()}${tab.id.slice(1)}" role="tab" tabindex="${mode === tab.id ? '0' : '-1'}" data-prompt-create-mode="${tab.id}" aria-selected="${mode === tab.id ? 'true' : 'false'}" aria-controls="deskPromptCreatePanel" ${state.extractor.busy || state.blockSaveBusy ? 'disabled' : ''}><svg viewBox="0 0 24 24" aria-hidden="true">${tab.icon}</svg><span>${tab.label}</span></button>`).join('')}</div>`;
  }
  function blockFormHtml(block) {
    const sourceRule = block.source_rule_snapshot || {};
    const ruleTrace = block.source_rule_id
      ? `<div class="desk-prompt-help"><strong>来源规则</strong> · ${escapeHtml(sourceRule.name || block.source_rule_id)}${block.source_rule_version ? ` · v${Number(block.source_rule_version)}` : ''}</div>`
      : '';
    return `<form class="desk-prompt-editor-form" data-prompt-block-form autocomplete="off" ${state.blockSaveBusy ? 'inert aria-busy="true"' : ''}>
      <input type="hidden" name="id" value="${escapeHtml(block.id || '')}">
      <div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>名称</span><input name="name" maxlength="120" value="${escapeHtml(block.name || '')}" placeholder="例如：克制微笑" required></label><label class="desk-prompt-field"><span>所属模块</span><select name="module_type">${moduleTypeOptions(block.module_type)}</select></label></div>
      <label class="desk-prompt-field"><span>完整内容</span><textarea name="content" placeholder="可直接插入提示词的内容" required>${escapeHtml(block.content || '')}</textarea></label>
      <div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>精简版本</span><textarea name="compact_content" placeholder="可选">${escapeHtml(block.compact_content || '')}</textarea></label><label class="desk-prompt-field"><span>英文版本</span><textarea name="english_content" placeholder="可选">${escapeHtml(block.english_content || '')}</textarea></label></div>
      <div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>适用类型</span><input name="applicable_types" value="${escapeHtml((block.applicable_types || []).join(', '))}" placeholder="portrait, poster；留空代表通用"></label><label class="desk-prompt-field"><span>标签</span><input name="tags" value="${escapeHtml((block.tags || []).join(', '))}" placeholder="常用, 商业"></label></div>
      ${ruleTrace}
      <div class="desk-prompt-editor-actions"><button type="submit" class="is-primary" ${state.blockSaveBusy ? 'disabled' : ''}>${state.blockSaveBusy ? (state.blockWriteAction === 'delete' ? '正在删除…' : '正在保存…') : '保存素材块'}</button><button type="button" data-prompt-action="insert-block" ${state.blockSaveBusy ? 'disabled' : ''}>/ 插入</button><button type="button" data-prompt-action="copy-block" ${state.blockSaveBusy ? 'disabled' : ''}>复制</button></div>
    </form>`;
  }
  function blockEditorHtml(block) {
    const isNew = !block.id;
    const createMode = isNew && state.extractor.open ? state.extractor.mode : 'manual';
    const createTitles = { manual: block.name || moduleLabel(block.module_type), text: '拆分完整提示词', image: '解析图片为素材块' };
    const labelledBy = `deskPromptCreateMode${createMode[0].toUpperCase()}${createMode.slice(1)}`;
    const content = !isNew
      ? blockFormHtml(block)
      : createMode === 'manual'
      ? `<section id="deskPromptCreatePanel" role="tabpanel" aria-labelledby="${labelledBy}">${blockFormHtml(block)}</section>`
      : `<section class="desk-prompt-extractor desk-prompt-extractor--inline" id="deskPromptCreatePanel" role="tabpanel" aria-labelledby="${labelledBy}">${state.extractor.candidates.length ? extractorResultsHtml() : extractorInputHtml()}</section>`;
    return `<div class="desk-prompt-editor-pane ${isNew && createMode !== 'manual' ? 'desk-prompt-editor-pane--extractor' : ''}">
      <div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">${isNew ? '新建素材块' : '编辑素材块'}</span><h3 data-i18n-skip>${escapeHtml(isNew ? createTitles[createMode] : (block.name || moduleLabel(block.module_type)))}</h3></div><div class="desk-prompt-editor-pane__head-actions">${createMode === 'manual' ? `<button type="button" data-prompt-action="toggle-block-favorite" aria-pressed="${block.favorite ? 'true' : 'false'}" title="收藏" ${state.blockSaveBusy ? 'disabled' : ''}>★</button>` : ''}${block.id ? `<button type="button" class="is-danger" data-prompt-action="delete-block" ${state.blockSaveBusy ? 'disabled' : ''}>${state.blockSaveBusy && state.blockWriteAction === 'delete' ? '删除中…' : '删除'}</button>` : ''}</div></div>
      ${isNew ? createModeTabsHtml(createMode) : ''}
      ${content}
    </div>`;
  }

  function rulePayload(rule) {
    return {
      id: cleanText(rule?.id),
      base_template_id: cleanText(rule?.base_template_id),
      primary_type: cleanText(rule?.primary_type),
      name: cleanText(rule?.name),
      description: cleanText(rule?.description),
      modules: (rule?.modules || []).map(module => ({
        key: cleanText(module.key),
        label: cleanText(module.label),
        hint: cleanText(module.hint),
        required: !!module.required,
        enabled: module.enabled !== false,
        kind: ['common', 'specific', 'custom'].includes(module.kind) ? module.kind : 'custom',
      })),
      options: {
        granularity: ['compact', 'balanced', 'detailed'].includes(rule?.options?.granularity) ? rule.options.granularity : 'balanced',
        max_blocks: Math.max(3, Math.min(30, Number(rule?.options?.max_blocks) || 18)),
      },
    };
  }
  function ruleFingerprint(rule) { return JSON.stringify(rulePayload(rule)); }
  function setRuleDraft(rule) {
    state.ruleDraft = JSON.parse(JSON.stringify(rule));
    state.ruleBaseline = ruleFingerprint(state.ruleDraft);
  }
  function baseRule(rule) {
    const baseId = cleanText(rule?.base_template_id) || (rule?.system ? itemId(rule) : '');
    return state.templates.find(item => item.system && itemId(item) === baseId)
      || state.templates.find(item => item.system && item.primary_type === rule?.primary_type)
      || null;
  }
  function createRuleDraft(source) {
    const base = baseRule(source) || source;
    const editing = source && !source.system;
    return {
      id: editing ? itemId(source) : '',
      base_template_id: itemId(base),
      primary_type: source?.primary_type || base?.primary_type || '',
      name: editing ? source.name : `${source?.name || base?.name || '拆分规则'} · 自定义`,
      description: editing ? source.description : (source?.description || base?.description || ''),
      version: editing ? Number(source.version || 1) : 0,
      modules: (source?.modules || base?.modules || []).map(module => ({ ...module, enabled: module.enabled !== false, locked_key: true })),
      options: { granularity: 'balanced', max_blocks: 18, ...(source?.options || base?.options || {}) },
      system: false,
    };
  }
  function syncRuleDraftFromForm() {
    const form = els.deskPromptLibraryEditor?.querySelector('[data-rule-form]');
    if (!form || !state.ruleDraft) return state.ruleDraft;
    const draft = state.ruleDraft;
    draft.name = cleanText(form.querySelector('[name="rule_name"]')?.value);
    draft.description = cleanText(form.querySelector('[name="rule_description"]')?.value);
    draft.options = {
      granularity: cleanText(form.querySelector('[name="rule_granularity"]')?.value) || 'balanced',
      max_blocks: Math.max(3, Math.min(30, Number(form.querySelector('[name="rule_max_blocks"]')?.value) || 18)),
    };
    form.querySelectorAll('[data-rule-module-index]').forEach(row => {
      const module = draft.modules[Number(row.dataset.ruleModuleIndex)];
      if (!module) return;
      module.key = cleanText(row.querySelector('[name="rule_module_key"]')?.value).toLowerCase().replace(/[-\s]+/g, '_');
      module.label = cleanText(row.querySelector('[name="rule_module_label"]')?.value);
      module.hint = cleanText(row.querySelector('[name="rule_module_hint"]')?.value);
      module.enabled = !!row.querySelector('[name="rule_module_enabled"]')?.checked;
      module.required = !!row.querySelector('[name="rule_module_required"]')?.checked;
    });
    return draft;
  }
  function hasUnsavedRuleChanges() {
    if (!state.ruleDraft) return false;
    syncRuleDraftFromForm();
    return ruleFingerprint(state.ruleDraft) !== state.ruleBaseline;
  }
  function confirmRuleDiscard() {
    if (!hasUnsavedRuleChanges()) return true;
    return !window.confirm || window.confirm('当前拆分规则有未保存修改，确定放弃吗？');
  }
  function discardRuleDraft() {
    state.ruleDraft = null;
    state.ruleBaseline = null;
    state.ruleSaveBusy = false;
    state.ruleWriteAction = '';
  }
  function startRuleDraft(source) {
    if (!source || (state.ruleDraft && !confirmRuleDiscard())) return false;
    setRuleDraft(createRuleDraft(source));
    state.workspace = 'templates';
    render();
    requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector('[name="rule_name"]')?.focus?.({ preventScroll: true }));
    return true;
  }
  function ruleModuleEditorHtml(module, index, total) {
    const custom = module.kind === 'custom';
    return `<article class="desk-prompt-rule-module ${module.enabled === false ? 'is-disabled' : ''}" data-rule-module-index="${index}">
      <div class="desk-prompt-rule-module__order"><button type="button" data-prompt-action="move-rule-module" data-direction="up" title="上移" aria-label="上移 ${escapeHtml(module.label || module.key)}" ${index === 0 || state.ruleSaveBusy ? 'disabled' : ''}>↑</button><button type="button" data-prompt-action="move-rule-module" data-direction="down" title="下移" aria-label="下移 ${escapeHtml(module.label || module.key)}" ${index === total - 1 || state.ruleSaveBusy ? 'disabled' : ''}>↓</button></div>
      <div class="desk-prompt-rule-module__fields"><div class="desk-prompt-field-grid is-three"><label class="desk-prompt-field"><span>模块 Key</span><input name="rule_module_key" value="${escapeHtml(module.key)}" pattern="[a-z][a-z0-9_]{1,63}" ${module.locked_key ? 'readonly' : ''} required></label><label class="desk-prompt-field"><span>显示名称</span><input name="rule_module_label" value="${escapeHtml(module.label)}" maxlength="80" required></label><div class="desk-prompt-rule-module__checks"><label><input type="checkbox" name="rule_module_enabled" ${module.enabled !== false ? 'checked' : ''}>启用</label><label><input type="checkbox" name="rule_module_required" ${module.required ? 'checked' : ''}>重点</label></div></div><label class="desk-prompt-field"><span>拆分说明</span><input name="rule_module_hint" value="${escapeHtml(module.hint || '')}" maxlength="500"></label></div>
      ${custom ? `<button type="button" class="desk-prompt-rule-module__delete" data-prompt-action="delete-rule-module" title="删除自定义模块" aria-label="删除 ${escapeHtml(module.label || module.key)}" ${state.ruleSaveBusy ? 'disabled' : ''}>×</button>` : ''}
    </article>`;
  }
  function ruleDraftEditorHtml(draft) {
    return `<div class="desk-prompt-editor-pane desk-prompt-editor-pane--rule-draft"><div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">${draft.id ? '编辑自定义规则' : '新建自定义规则'}</span><h3>${escapeHtml(draft.name || '未命名拆分规则')}</h3><p>${escapeHtml(typeLabel(draft.primary_type))} · 基于系统规则</p></div></div>
      <form class="desk-prompt-rule-form" data-rule-form autocomplete="off" ${state.ruleSaveBusy ? 'inert aria-busy="true"' : ''}>
        <div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>规则名称</span><input name="rule_name" value="${escapeHtml(draft.name || '')}" maxlength="120" required></label><label class="desk-prompt-field"><span>内容类型</span><input value="${escapeHtml(typeLabel(draft.primary_type))}" readonly></label></div>
        <label class="desk-prompt-field"><span>规则说明</span><textarea name="rule_description" maxlength="500">${escapeHtml(draft.description || '')}</textarea></label>
        <div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>拆分粒度</span><select name="rule_granularity"><option value="compact" ${draft.options?.granularity === 'compact' ? 'selected' : ''}>精简</option><option value="balanced" ${draft.options?.granularity === 'balanced' ? 'selected' : ''}>均衡</option><option value="detailed" ${draft.options?.granularity === 'detailed' ? 'selected' : ''}>详细</option></select></label><label class="desk-prompt-field"><span>最多素材块</span><input type="number" name="rule_max_blocks" min="3" max="30" step="1" value="${Math.max(3, Math.min(30, Number(draft.options?.max_blocks) || 18))}"></label></div>
        <section class="desk-prompt-rule-builder"><header><div><strong>模块结构</strong><span>${draft.modules.filter(module => module.enabled !== false).length} / ${draft.modules.length} 个启用</span></div><button type="button" data-prompt-action="add-rule-module" ${state.ruleSaveBusy || draft.modules.length >= 40 ? 'disabled' : ''}>+ 新增模块</button></header><div class="desk-prompt-rule-builder__list">${draft.modules.map((module, index) => ruleModuleEditorHtml(module, index, draft.modules.length)).join('')}</div></section>
        <div class="desk-prompt-editor-actions desk-prompt-rule-form__actions"><button type="submit" class="is-primary" ${state.ruleSaveBusy ? 'disabled' : ''}>${state.ruleSaveBusy ? '正在保存…' : '保存规则'}</button><button type="button" data-prompt-action="reset-rule-draft" ${state.ruleSaveBusy ? 'disabled' : ''}>恢复系统结构</button><button type="button" data-prompt-action="cancel-rule-draft" ${state.ruleSaveBusy ? 'disabled' : ''}>取消</button>${draft.id ? `<button type="button" class="is-danger" data-prompt-action="delete-rule-draft" ${state.ruleSaveBusy ? 'disabled' : ''}>删除规则</button>` : ''}</div>
      </form></div>`;
  }
  function templateEditorHtml(template) {
    if (!template) return emptyEditor('选择一条拆分规则');
    const enabled = (template.modules || []).filter(item => item.enabled !== false);
    const common = enabled.filter(item => item.kind !== 'specific');
    const specific = enabled.filter(item => item.kind === 'specific');
    const badge = template.system ? '内置规则' : `自定义 · v${Number(template.version || 1)}`;
    return `<div class="desk-prompt-editor-pane"><div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">${badge}</span><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.description || '')}</p></div><div class="desk-prompt-editor-pane__head-actions"><button type="button" data-prompt-action="edit-rule">${template.system ? '自定义此规则' : '编辑规则'}</button><span class="desk-prompt-type-badge">${escapeHtml(template.primary_type)}</span></div></div>
      <div class="desk-prompt-template"><div class="desk-prompt-template__stats"><div><strong>${enabled.length}</strong><span>启用模块</span></div><div><strong>${specific.length}</strong><span>类型专属</span></div><div><strong>${enabled.filter(item => item.required).length}</strong><span>重点模块</span></div></div>
      <section class="desk-prompt-section"><div class="desk-prompt-section-title"><strong>通用模块</strong></div><div class="desk-prompt-template__module-list">${common.map(item => `<span title="${escapeHtml(item.hint)}">${escapeHtml(item.label)}</span>`).join('')}</div></section>
      <section class="desk-prompt-section"><div class="desk-prompt-section-title"><strong>${escapeHtml(template.name)}专属模块</strong></div><div class="desk-prompt-template__module-list">${specific.map(item => `<span class="is-specific" title="${escapeHtml(item.hint)}">${escapeHtml(item.label)}</span>`).join('')}</div></section>
      <button type="button" class="desk-prompt-template__create is-primary" data-prompt-action="extract-by-template">按此规则拆分提示词</button></div></div>`;
  }
  function addRuleModule() {
    const draft = syncRuleDraftFromForm();
    if (!draft || draft.modules.length >= 40) return;
    const used = new Set(draft.modules.map(module => module.key));
    let index = 1;
    while (used.has(`custom_module_${index}`)) index += 1;
    draft.modules.push({ key: `custom_module_${index}`, label: '自定义模块', hint: '', required: false, enabled: true, kind: 'custom', locked_key: false });
    renderEditor();
    requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector(`[data-rule-module-index="${draft.modules.length - 1}"] [name="rule_module_key"]`)?.focus?.({ preventScroll: true }));
  }
  function moveRuleModule(button) {
    const draft = syncRuleDraftFromForm();
    const row = button.closest('[data-rule-module-index]');
    const index = Number(row?.dataset.ruleModuleIndex);
    const offset = button.dataset.direction === 'up' ? -1 : 1;
    const next = index + offset;
    if (!draft || !Number.isInteger(index) || next < 0 || next >= draft.modules.length) return;
    [draft.modules[index], draft.modules[next]] = [draft.modules[next], draft.modules[index]];
    renderEditor();
    requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector(`[data-rule-module-index="${next}"] [data-direction="${button.dataset.direction}"]`)?.focus?.({ preventScroll: true }));
  }
  function deleteRuleModule(button) {
    const draft = syncRuleDraftFromForm();
    const index = Number(button.closest('[data-rule-module-index]')?.dataset.ruleModuleIndex);
    if (!draft?.modules[index] || draft.modules[index].kind !== 'custom') return;
    draft.modules.splice(index, 1);
    renderEditor();
  }
  function resetRuleDraft() {
    const draft = syncRuleDraftFromForm();
    const base = baseRule(draft);
    if (!draft || !base) return;
    if (window.confirm && !window.confirm('恢复系统规则的模块结构和拆分参数？规则名称与说明会保留。')) return;
    draft.modules = (base.modules || []).map(module => ({ ...module, enabled: module.enabled !== false, locked_key: true }));
    draft.options = { granularity: 'balanced', max_blocks: 18, ...(base.options || {}) };
    renderEditor();
  }
  async function saveRuleDraft(event) {
    event?.preventDefault?.();
    if (state.ruleSaveBusy) return;
    const form = els.deskPromptLibraryEditor?.querySelector('[data-rule-form]');
    if (form && !form.reportValidity()) return;
    const payload = rulePayload(syncRuleDraftFromForm());
    if (!payload.name) { notify('请输入拆分规则名称。', 'warning'); return; }
    const keys = new Set();
    for (const module of payload.modules) {
      if (!/^[a-z][a-z0-9_]{1,63}$/.test(module.key)) { notify(`模块 Key 无效：${module.key || '空值'}`, 'warning'); return; }
      if (keys.has(module.key)) { notify(`模块 Key 重复：${module.key}`, 'warning'); return; }
      keys.add(module.key);
    }
    if (!payload.modules.some(module => module.enabled)) { notify('至少启用一个模块。', 'warning'); return; }
    state.ruleSaveBusy = true;
    state.ruleWriteAction = 'save';
    renderEditor();
    try {
      const result = await window.DesktopApi.savePromptTemplate(payload);
      const template = result?.template;
      if (!template?.id) throw new Error('服务未返回拆分规则');
      state.templates = [template, ...state.templates.filter(item => itemId(item) !== template.id)];
      state.selected.templates = template.id;
      discardRuleDraft();
      render();
      notify(payload.id ? `拆分规则已更新至 v${template.version}。` : '自定义拆分规则已创建。');
    } catch (error) {
      state.ruleSaveBusy = false;
      state.ruleWriteAction = '';
      renderEditor();
      reportError(error, '拆分规则保存失败');
    }
  }
  async function deleteRuleDraft() {
    const draft = syncRuleDraftFromForm();
    if (!draft?.id || state.ruleSaveBusy) return;
    if (window.confirm && !window.confirm(`确定删除“${draft.name || '自定义拆分规则'}”？`)) return;
    state.ruleSaveBusy = true;
    state.ruleWriteAction = 'delete';
    renderEditor();
    try {
      await window.DesktopApi.deletePromptTemplate(draft.id);
      state.templates = state.templates.filter(item => itemId(item) !== draft.id);
      const fallback = baseRule(draft) || state.templates.find(item => item.system && item.primary_type === draft.primary_type) || state.templates[0];
      state.selected.templates = itemId(fallback);
      discardRuleDraft();
      render();
      notify('自定义拆分规则已删除。');
    } catch (error) {
      state.ruleSaveBusy = false;
      state.ruleWriteAction = '';
      renderEditor();
      reportError(error, '拆分规则删除失败');
    }
  }
  function colorContrastHtml(colors) {
    const values = colors.map(safeColor);
    const textRatio = contrastRatio(values[4], values[3]);
    const accentRatio = contrastRatio(values[0], values[3]);
    return `<div class="desk-prompt-color-draft__contrast"><span><strong>${textRatio.toFixed(1)}:1</strong> 深色 / 浅色 <em class="${textRatio >= 4.5 ? 'is-pass' : 'is-review'}">${textRatio >= 4.5 ? 'AA 通过' : '需调整'}</em></span><span><strong>${accentRatio.toFixed(1)}:1</strong> 主色 / 浅色 <em class="${accentRatio >= 3 ? 'is-pass' : 'is-review'}">${accentRatio >= 3 ? '大字号可用' : '装饰色'}</em></span></div>`;
  }
  function colorBloomPickerHtml(value) {
    const color = safeColor(value);
    const hsl = hexToHsl(color);
    const tone = hslToHex(hsl.h, hsl.s, 50);
    const marker = bloomLightnessPoint(hsl.l);
    const selectedKey = bloomSelectedPetalKey(color);
    const open = !!state.colorBloomOpen;
    const petals = BLOOM_PETALS.map((petal, index) => {
      const ringItems = BLOOM_PETALS.filter(item => item.ring === petal.ring);
      const ringIndex = ringItems.findIndex(item => item.key === petal.key);
      const angle = petal.ring === 'center' ? 0 : -Math.PI / 2 + (ringIndex / ringItems.length) * Math.PI * 2;
      const radius = petal.ring === 'outer' ? 68 : petal.ring === 'inner' ? 36 : 0;
      const size = 45;
      const x = Math.cos(angle) * radius;
      const y = Math.sin(angle) * radius;
      const layer = petal.ring === 'outer' ? 2 + ringIndex : petal.ring === 'inner' ? 20 + ringIndex : 30;
      const selected = selectedKey === petal.key;
      return `<button type="button" class="desk-prompt-bloom__petal is-${petal.ring}" data-prompt-action="select-color-bloom-petal" data-bloom-color="${petal.color}" data-bloom-petal-key="${petal.key}" aria-label="选择颜色 ${petal.color}" aria-pressed="${selected}" tabindex="${open ? '0' : '-1'}" style="--bloom-petal:${petal.color};--bloom-offset-x:${x.toFixed(3)}px;--bloom-offset-y:${y.toFixed(3)}px;--bloom-size:${size}px;--bloom-order:${index};--bloom-layer:${layer}"><span class="desk-prompt-bloom__petal-disc" aria-hidden="true"></span></button>`;
    }).join('');
    return `<div class="desk-prompt-bloom ${open ? 'is-open' : ''}" data-bloom-picker style="--desk-prompt-bloom-color:${color};--desk-prompt-bloom-tone:${tone};--bloom-marker-x:${marker.x.toFixed(2)}px;--bloom-marker-y:${marker.y.toFixed(2)}px">
      <div class="desk-prompt-bloom__control"><button type="button" class="desk-prompt-bloom__trigger" data-prompt-action="toggle-color-bloom" aria-label="打开花朵基色取色器，当前 ${color}" aria-expanded="${open}" aria-controls="deskPromptBloomPopover"><span aria-hidden="true"></span></button><input name="color_base_hex" value="${color}" maxlength="7" spellcheck="false" aria-label="基色色值"></div>
      <input type="hidden" name="color_base_picker" value="${color}">
      <div class="desk-prompt-bloom__popover" id="deskPromptBloomPopover" role="dialog" aria-label="花朵基色取色器" aria-hidden="${!open}">
        <div class="desk-prompt-bloom__stage"><div class="desk-prompt-bloom__flower"><span class="desk-prompt-bloom__field" aria-hidden="true"></span>${petals}</div><div class="desk-prompt-bloom__lightness" data-bloom-lightness role="slider" aria-label="基色明度" aria-valuemin="4" aria-valuemax="96" aria-valuenow="${Math.round(hsl.l)}" aria-valuetext="明度 ${Math.round(hsl.l)}%" tabindex="${open ? '0' : '-1'}"><svg viewBox="0 0 64 148" aria-hidden="true"><defs><linearGradient id="deskPromptBloomLightnessGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF"></stop><stop offset=".38" style="stop-color:var(--desk-prompt-bloom-tone)"></stop><stop offset=".62" style="stop-color:var(--desk-prompt-bloom-tone)"></stop><stop offset="1" stop-color="#050505"></stop></linearGradient></defs><path class="desk-prompt-bloom__lightness-shadow" d="M12 12 A118 118 0 0 1 12 136"></path><path class="desk-prompt-bloom__lightness-track" d="M12 12 A118 118 0 0 1 12 136"></path></svg><span class="desk-prompt-bloom__lightness-marker" aria-hidden="true"><i></i></span></div></div>
        <div class="desk-prompt-bloom__footer"><span class="desk-prompt-bloom__current" aria-hidden="true"></span><strong data-bloom-value>${color}</strong><small>点选花瓣 · 拖动调明暗</small></div>
      </div>
    </div>`;
  }
  function colorAnalysisSummary(result) {
    const temperature = { auto: '冷暖均衡', warm: '偏暖', cool: '偏冷' }[result?.temperature] || '冷暖均衡';
    const contrast = { soft: '柔和低对比', balanced: '均衡对比', high: '鲜明高对比' }[result?.contrast] || '均衡对比';
    return `${temperature} · ${contrast} · ${colorFormula(result?.formula).label}`;
  }
  function colorAnalysisStatusHtml(analysis) {
    if (analysis.busy) return `<div class="desk-prompt-color-analysis__status" role="status"><span class="desk-prompt-color-analysis__spinner" aria-hidden="true"></span><div><strong>正在分析图片色彩</strong><span>计算像素占比、视觉重心与明暗层级</span></div></div>`;
    if (analysis.error) return `<div class="desk-prompt-color-analysis__status is-error" role="alert"><div><strong>分析未完成</strong><span>${escapeHtml(analysis.error)}</span></div><button type="button" data-prompt-action="retry-color-analysis" ${colorAnalysisHasSource(analysis) ? '' : 'disabled'}>重新分析</button></div>`;
    const result = analysis.result;
    if (!result?.roles?.length) return '<div class="desk-prompt-color-analysis__empty"><strong>选择一张图片开始分析</strong><span>图片仅在本地浏览器中缩小采样，不会上传到模型服务。</span></div>';
    return `<div class="desk-prompt-color-analysis__status is-success" role="status"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="m8 12 2.5 2.5L16.5 9"></path></svg><div><strong>已同步到下方色值微调</strong><span>${escapeHtml(colorAnalysisSummary(result))} · 可继续修改每个色值</span></div></div>`;
  }
  function colorAnalysisHtml() {
    const analysis = state.colorAnalysis;
    if (!analysis.open) return '';
    const hasSource = colorAnalysisHasSource(analysis);
    const controlsDisabled = colorAnalysisSourceLocked(analysis) ? 'disabled' : '';
    const sourceLabel = analysis.sourceKind === 'clipboard' ? '剪贴板图片' : '本地图片';
    const preview = hasSource
      ? `<img src="${escapeHtml(analysis.previewUrl)}" alt="待分析图片预览"><span><strong>${escapeHtml(sourceLabel)}</strong><small>${escapeHtml(analysis.fileName || '待分析图片')}</small></span>`
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"></rect><circle cx="9" cy="10" r="2"></circle><path d="m3 17 5-5 4 4 3-3 6 6"></path></svg><span><strong>选择图片</strong><small>点击、拖入或粘贴</small></span>';
    const modes = [
      { id: 'balanced', label: '均衡', title: '兼顾像素占比与颜色差异' },
      { id: 'subject', label: '突出主体', title: '提高画面中心区域的分析权重' },
      { id: 'vivid', label: '鲜明色彩', title: '提高高饱和颜色的分析权重' },
    ];
    return `<div class="desk-prompt-color-analysis" data-color-analysis><input type="file" name="color_analysis_image" accept="image/png,image/jpeg,image/webp" hidden><div class="desk-prompt-color-analysis__source"><button type="button" class="desk-prompt-color-analysis__drop ${hasSource ? 'has-image' : ''} ${colorAnalysisSourceLocked(analysis) ? 'is-busy' : ''}" data-color-analysis-drop data-prompt-action="pick-color-analysis-file" aria-label="${hasSource ? '更换待分析图片' : '选择待分析图片'}" ${controlsDisabled}>${preview}</button><div class="desk-prompt-color-analysis__controls"><div class="desk-prompt-color-analysis__intro"><div><strong>图片色彩分析</strong><span>分析完成后自动写入下方色值微调</span></div>${hasSource ? `<button type="button" data-prompt-action="clear-color-analysis" title="移除图片" aria-label="移除分析图片" ${controlsDisabled}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 7l1 13h6l1-13"></path></svg></button>` : ''}</div><div class="desk-prompt-color-analysis__modes" role="group" aria-label="图片颜色提取模式">${modes.map(mode => `<button type="button" data-color-analysis-mode="${mode.id}" data-prompt-action="set-color-analysis-mode" aria-pressed="${analysis.mode === mode.id}" title="${mode.title}" ${controlsDisabled}>${mode.label}</button>`).join('')}</div></div></div>${colorAnalysisStatusHtml(analysis)}</div>`;
  }
  function colorDraftEditorHtml(draft) {
    const colors = draft.colors.map(safeColor);
    const formula = colorFormula(draft.formula);
    const roles = ['主色 · 60%', '辅色 · 30%', '点缀 · 10%', '浅中性色', '深中性色'];
    const colorTuneSummary = state.colorAnalysis.result?.roles?.length
      ? `图片提取已同步 · ${colorAnalysisSummary(state.colorAnalysis.result)}`
      : '可直接修改生成结果';
    return `<div class="desk-prompt-editor-pane desk-prompt-editor-pane--color-draft"><div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">${draft.id ? '编辑自定义配色' : '手动创建配色'}</span><h3>${escapeHtml(draft.name || '未命名配色方案')}</h3><p>选择行业与色轮公式生成起点，再直接调整每一个色值。</p></div></div>
      <form class="desk-prompt-color-draft" data-color-draft-form autocomplete="off">
        <section class="desk-prompt-color-draft__section"><div class="desk-prompt-color-draft__section-head"><div><strong>基本设置</strong><span>定义方案用途和生成基色</span></div><button type="button" class="desk-prompt-color-draft__image-action ${state.colorAnalysis.open ? 'is-active' : ''}" data-prompt-action="toggle-color-analysis" aria-expanded="${state.colorAnalysis.open}"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"></rect><circle cx="9" cy="10" r="2"></circle><path d="m3 17 5-5 4 4 3-3 6 6"></path><path d="M18 3v4M16 5h4"></path></svg><span>${state.colorAnalysis.open ? '收起图片分析' : '从图片提取'}</span></button></div><div class="desk-prompt-color-draft__basics"><label class="desk-prompt-field"><span>方案名称</span><input name="color_name" maxlength="100" value="${escapeHtml(draft.name)}" placeholder="例如：清爽科技蓝" required></label><label class="desk-prompt-field"><span>设计行业</span><select name="color_industry">${COLOR_INDUSTRIES.map(item => `<option value="${item.id}" ${item.id === draft.industry ? 'selected' : ''}>${escapeHtml(item.label)}</option>`).join('')}</select></label><div class="desk-prompt-field desk-prompt-field--bloom" role="group" aria-labelledby="deskPromptBloomLabel"><span id="deskPromptBloomLabel">基色</span>${colorBloomPickerHtml(draft.base_color)}</div><label class="desk-prompt-field"><span>色温倾向</span><select name="color_temperature"><option value="auto" ${draft.temperature === 'auto' ? 'selected' : ''}>冷暖均衡</option><option value="warm" ${draft.temperature === 'warm' ? 'selected' : ''}>暖色倾向 · 活力亲切</option><option value="cool" ${draft.temperature === 'cool' ? 'selected' : ''}>冷色倾向 · 专业冷静</option></select></label><label class="desk-prompt-field"><span>明度 / 饱和度对比</span><select name="color_contrast"><option value="soft" ${draft.contrast === 'soft' ? 'selected' : ''}>柔和低对比 · 优雅高级</option><option value="balanced" ${draft.contrast === 'balanced' ? 'selected' : ''}>均衡对比 · 通用商业</option><option value="high" ${draft.contrast === 'high' ? 'selected' : ''}>鲜明高对比 · 活力醒目</option></select></label></div>${colorAnalysisHtml()}</section>
        <section class="desk-prompt-color-draft__section"><div class="desk-prompt-color-draft__section-head"><div><strong>色轮公式</strong><span>行业标准的色相组合规则</span></div><em>${escapeHtml(formula.en)}</em></div><div class="desk-prompt-color-formula-grid">${COLOR_FORMULAS.map(item => `<label><input type="radio" name="color_formula" value="${item.id}" ${item.id === draft.formula ? 'checked' : ''}><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.en)}</small><em>${escapeHtml(item.description)}</em></span></label>`).join('')}</div></section>
        <section class="desk-prompt-color-draft__section"><div class="desk-prompt-color-draft__section-head"><div><strong>实用规则</strong><span>用比例和中性色控制视觉层级</span></div></div><div class="desk-prompt-color-draft__rules"><label><input type="checkbox" name="color_use_ratio" ${draft.use_ratio ? 'checked' : ''}><span><strong>60-30-10 黄金比例</strong><small>主色 60% · 辅色 30% · 点缀色 10%</small></span></label><label><input type="checkbox" name="color_neutral_balance" ${draft.neutral_balance ? 'checked' : ''}><span><strong>自动加入中性色</strong><small>以低饱和浅色和深色保障留白与可读性</small></span></label></div><div class="desk-prompt-color-draft__generate-actions"><button type="button" class="desk-prompt-color-draft__generate" data-prompt-action="apply-color-industry"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7" width="18" height="13" rx="2"></rect><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"></path></svg><span>应用行业推荐</span></button><button type="button" class="desk-prompt-color-draft__generate" data-prompt-action="generate-color-draft"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3-1.7 4.6a2 2 0 0 1-1.2 1.2L5 10.3l4.1 1.5a2 2 0 0 1 1.2 1.2L12 17.7l1.7-4.7a2 2 0 0 1 1.2-1.2l4.1-1.5-4.1-1.5a2 2 0 0 1-1.2-1.2Z"></path><path d="M5 3v3M3.5 4.5h3M19 17v4M17 19h4"></path></svg><span>按公式生成配色</span></button></div></section>
        <section class="desk-prompt-color-draft__section"><div class="desk-prompt-color-draft__section-head"><div><strong>色值微调</strong><span>${escapeHtml(colorTuneSummary)}</span></div><em>HEX</em></div><div class="desk-prompt-color-draft__ratio ${draft.use_ratio ? '' : 'is-even'}" aria-label="${draft.use_ratio ? '60-30-10 比例预览' : '等比例配色预览'}"><span style="--desk-prompt-color:${colors[0]};--desk-prompt-color-ink:${colorTextColor(colors[0])}"><b>${draft.use_ratio ? '60%' : '主色'}</b></span><span style="--desk-prompt-color:${colors[1]};--desk-prompt-color-ink:${colorTextColor(colors[1])}"><b>${draft.use_ratio ? '30%' : '辅色'}</b></span><span style="--desk-prompt-color:${colors[2]};--desk-prompt-color-ink:${colorTextColor(colors[2])}"><b>${draft.use_ratio ? '10%' : '点缀'}</b></span></div><div class="desk-prompt-color-draft__colors">${colors.map((color, index) => `<div><label style="--desk-prompt-color:${color};--desk-prompt-color-ink:${colorTextColor(color)}"><input type="color" name="color_picker_${index}" value="${color}" data-color-draft-index="${index}" aria-label="${roles[index]}颜色"><span>${roles[index]}</span></label><input name="color_hex_${index}" value="${color}" maxlength="7" spellcheck="false" data-color-draft-index="${index}" aria-label="${roles[index]}色值"></div>`).join('')}</div>${colorContrastHtml(colors)}</section>
        <section class="desk-prompt-color-draft__section"><div class="desk-prompt-color-draft__section-head"><div><strong>描述与提示词</strong><span>保存后可搜索、复制并插入文本节点</span></div></div><label class="desk-prompt-field"><span>方案描述</span><textarea name="color_description" maxlength="500">${escapeHtml(draft.description)}</textarea></label><label class="desk-prompt-field"><span>提示词片段</span><textarea name="color_prompt" maxlength="4000" required>${escapeHtml(draft.prompt)}</textarea></label><div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>适用场景</span><input name="color_scenes" value="${escapeHtml(parseTags(draft.scenes).join(', '))}" placeholder="界面系统, 品牌海报"></label><label class="desk-prompt-field"><span>标签</span><input name="color_tags" value="${escapeHtml(parseTags(draft.tags).join(', '))}" placeholder="科技, 专业, 高对比"></label></div></section>
        <div class="desk-prompt-editor-actions"><button type="submit" class="is-primary">保存配色方案</button><button type="button" data-prompt-action="cancel-color-draft">取消</button>${draft.id ? '<button type="button" class="is-danger" data-prompt-action="delete-color-draft">删除</button>' : ''}</div>
      </form></div>`;
  }
  function colorEditorHtml(item) {
    if (!item) return emptyEditor('选择一个色彩方案');
    const colorValues = item.colors.map(safeColor);
    const formula = item.formula ? colorFormula(item.formula) : null;
    return `<div class="desk-prompt-editor-pane desk-prompt-editor-pane--color"><div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">${item.custom ? `自定义 · ${escapeHtml(formula?.label || '手动配色')}` : '色彩方案'}</span><h3 data-i18n-skip>${escapeHtml(item.name)}</h3><p data-i18n-skip>${escapeHtml(item.description)}</p></div><div class="desk-prompt-editor-pane__head-actions"><button type="button" data-prompt-action="duplicate-color" title="以此方案为起点">以此为起点</button>${item.custom ? '<button type="button" data-prompt-action="edit-color">编辑</button>' : ''}<button type="button" data-prompt-action="toggle-color-favorite" aria-pressed="${item.favorite ? 'true' : 'false'}" title="${item.favorite ? '取消收藏' : '收藏'}" aria-label="${item.favorite ? '取消收藏' : '收藏'} ${escapeHtml(item.name)}">★</button></div></div>
      <div class="desk-prompt-color"><section class="desk-prompt-section"><div class="desk-prompt-section-title"><strong>配色预览</strong><em>点击色块复制 HEX</em></div><div class="desk-prompt-color__preview">${colorValues.map((color, index) => `<button type="button" data-color-value="${color}" title="复制 ${color}" aria-label="复制色值 ${color}" style="--desk-prompt-color:${color};--desk-prompt-color-ink:${colorTextColor(color)}"><span>${color}</span><small>${index === 0 ? '主色' : index === colorValues.length - 1 ? '锚点色' : `辅色 ${index}`}</small></button>`).join('')}</div></section>
      <section class="desk-prompt-section"><div class="desk-prompt-section-title"><strong>适用场景</strong></div><div class="desk-prompt-color__scenes">${(item.scenes || []).map(scene => `<span>${escapeHtml(scene)}</span>`).join('')}</div></section>
      <section class="desk-prompt-section"><div class="desk-prompt-section-title"><strong>提示词片段</strong></div><pre class="desk-prompt-color__prompt" data-i18n-skip>${escapeHtml(item.prompt)}</pre></section>
      <div class="desk-prompt-editor-actions"><button type="button" class="is-primary" data-prompt-action="insert-color">插入文本节点</button><button type="button" data-prompt-action="copy-color-prompt">复制提示词</button><button type="button" data-prompt-action="copy-color-values">复制全部色值</button></div></div></div>`;
  }
  function inspirationEditorHtml(item) {
    if (!item) return emptyEditor('选择一条灵感');
    const images = sourceImages(item);
    const image = sourceImage(item);
    const activeImageIndex = Math.max(0, images.indexOf(image));
    return `<div class="desk-prompt-editor-pane desk-prompt-editor-pane--inspiration"><div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">${escapeHtml(item.sourceName || '远程提示词源')}</span><h3 data-i18n-skip>${escapeHtml(item.title || '远程提示词')}</h3><p>${escapeHtml((item.tags || []).join(' · '))}</p></div></div>
      <div class="desk-prompt-inspiration-preview">${image ? `<div class="desk-prompt-inspiration-preview__media"><img class="desk-prompt-inspiration-preview__image" src="${escapeHtml(image)}" alt="${escapeHtml(item.title || '')}" decoding="async">${images.length > 1 ? `<span class="desk-prompt-inspiration-preview__counter">${activeImageIndex + 1} / ${images.length}</span>` : ''}<button type="button" data-prompt-action="open-source-image" title="查看原图" aria-label="查看原图"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"></path></svg></button></div>${images.length > 1 ? `<div class="desk-prompt-inspiration-preview__thumbs" aria-label="灵感图片"><div>${images.map((url, index) => `<button type="button" class="${index === activeImageIndex ? 'is-active' : ''}" data-prompt-action="select-inspiration-image" data-image-index="${index}" aria-label="查看第 ${index + 1} 张图片" aria-pressed="${index === activeImageIndex}"><img src="${escapeHtml(url)}" alt="" loading="lazy" decoding="async"></button>`).join('')}</div></div>` : ''}` : '<div class="desk-prompt-inspiration-preview__missing">暂无图片</div>'}<pre data-i18n-skip>${escapeHtml(item.prompt || '暂无提示词内容')}</pre>
      <div class="desk-prompt-editor-actions"><button type="button" class="is-primary" data-prompt-action="split-inspiration">拆分为素材块</button><button type="button" data-prompt-action="save-inspiration-block">整段存为素材块</button><button type="button" data-prompt-action="copy-inspiration">复制</button></div></div></div>`;
  }
  function emptyEditor(title) {
    return `<div class="desk-prompt-editor-pane"><div class="desk-prompt-editor-pane__head"><div><span class="desk-prompt-editor-pane__eyebrow">Prompt Blocks</span><h3>${escapeHtml(title)}</h3></div></div></div>`;
  }

  function blockFingerprint(block) {
    if (!block) return '';
    return JSON.stringify({
      id: cleanText(block.id),
      name: cleanText(block.name),
      module_type: cleanText(block.module_type) || 'custom',
      content: cleanText(block.content),
      compact_content: cleanText(block.compact_content),
      english_content: cleanText(block.english_content),
      applicable_types: parseTags(block.applicable_types),
      tags: parseTags(block.tags),
      favorite: !!block.favorite,
    });
  }
  function setBlockDraft(block) {
    state.blockDraft = JSON.parse(JSON.stringify(block));
    state.blockBaseline = blockFingerprint(state.blockDraft);
  }
  function hasUnsavedBlockChanges() {
    if (!state.blockDraft) return false;
    if (state.extractor.open) syncExtractor();
    if (allExtractorStates().some(extractorHasWork)) return true;
    const form = els.deskPromptLibraryEditor?.querySelector('[data-prompt-block-form]');
    if (form) syncBlockDraftFromForm();
    return blockFingerprint(state.blockDraft) !== state.blockBaseline;
  }
  function confirmBlockDiscard() {
    if (!hasUnsavedBlockChanges()) return true;
    return !window.confirm || window.confirm('当前素材块有未保存修改，确定放弃吗？');
  }
  function discardBlockDraft() {
    state.blockSaveCounter += 1;
    state.blockSaveBusy = false;
    state.blockWriteAction = '';
    state.blockDraft = null;
    state.blockBaseline = null;
    resetExtractorState();
  }
  function syncColorDraftFromForm() {
    const form = els.deskPromptLibraryEditor?.querySelector('[data-color-draft-form]');
    if (!form || !state.colorDraft) return state.colorDraft;
    const draft = state.colorDraft;
    draft.name = cleanText(form.querySelector('[name="color_name"]')?.value);
    draft.industry = colorIndustry(form.querySelector('[name="color_industry"]')?.value).id;
    draft.formula = colorFormula(form.querySelector('[name="color_formula"]:checked')?.value).id;
    const baseHex = cleanText(form.querySelector('[name="color_base_hex"]')?.value);
    const basePicker = cleanText(form.querySelector('[name="color_base_picker"]')?.value);
    draft.base_color = /^#[0-9a-f]{6}$/i.test(baseHex) ? safeColor(baseHex) : safeColor(basePicker);
    draft.contrast = ['soft', 'balanced', 'high'].includes(form.querySelector('[name="color_contrast"]')?.value) ? form.querySelector('[name="color_contrast"]').value : 'balanced';
    draft.temperature = ['auto', 'warm', 'cool'].includes(form.querySelector('[name="color_temperature"]')?.value) ? form.querySelector('[name="color_temperature"]').value : 'auto';
    draft.neutral_balance = !!form.querySelector('[name="color_neutral_balance"]')?.checked;
    draft.use_ratio = !!form.querySelector('[name="color_use_ratio"]')?.checked;
    draft.colors = Array.from({ length: 5 }, (_, index) => {
      const hex = cleanText(form.querySelector(`[name="color_hex_${index}"]`)?.value);
      const picker = cleanText(form.querySelector(`[name="color_picker_${index}"]`)?.value);
      return /^#[0-9a-f]{6}$/i.test(hex) ? safeColor(hex) : safeColor(picker);
    });
    draft.description = cleanText(form.querySelector('[name="color_description"]')?.value);
    draft.prompt = cleanText(form.querySelector('[name="color_prompt"]')?.value);
    draft.scenes = parseTags(form.querySelector('[name="color_scenes"]')?.value);
    draft.tags = parseTags(form.querySelector('[name="color_tags"]')?.value);
    return draft;
  }
  function updateColorBloomVisual(form, value) {
    const color = safeColor(value);
    const bloom = form?.querySelector('[data-bloom-picker]');
    if (!bloom) return;
    const hsl = hexToHsl(color);
    const marker = bloomLightnessPoint(hsl.l);
    bloom.style.setProperty('--desk-prompt-bloom-color', color);
    bloom.style.setProperty('--desk-prompt-bloom-tone', hslToHex(hsl.h, hsl.s, 50));
    bloom.style.setProperty('--bloom-marker-x', `${marker.x.toFixed(2)}px`);
    bloom.style.setProperty('--bloom-marker-y', `${marker.y.toFixed(2)}px`);
    const hex = form.querySelector('[name="color_base_hex"]');
    const picker = form.querySelector('[name="color_base_picker"]');
    const valueLabel = bloom.querySelector('[data-bloom-value]');
    const trigger = bloom.querySelector('.desk-prompt-bloom__trigger');
    const slider = bloom.querySelector('[data-bloom-lightness]');
    if (hex) hex.value = color;
    if (picker) picker.value = color;
    if (valueLabel) valueLabel.textContent = color;
    if (trigger) trigger.setAttribute('aria-label', `打开花朵基色取色器，当前 ${color}`);
    if (slider) {
      slider.setAttribute('aria-valuenow', String(Math.round(hsl.l)));
      slider.setAttribute('aria-valuetext', `明度 ${Math.round(hsl.l)}%`);
    }
    const selectedKey = bloomSelectedPetalKey(color);
    bloom.querySelectorAll('[data-bloom-petal-key]').forEach(button => button.setAttribute('aria-pressed', button.dataset.bloomPetalKey === selectedKey ? 'true' : 'false'));
  }
  function setColorDraftBaseColor(value) {
    const color = safeColor(value);
    const form = els.deskPromptLibraryEditor?.querySelector('[data-color-draft-form]');
    const draft = syncColorDraftFromForm();
    if (!form || !draft) return false;
    const previousAutoDescription = draftDescription(draft);
    const previousAutoPrompt = draftPrompt(draft);
    const updateDescription = draft.description === previousAutoDescription;
    const updatePrompt = draft.prompt === previousAutoPrompt;
    draft.base_color = color;
    if (updateDescription) {
      draft.description = draftDescription(draft);
      const input = form.querySelector('[name="color_description"]');
      if (input) input.value = draft.description;
    }
    if (updatePrompt) {
      draft.prompt = draftPrompt(draft);
      const input = form.querySelector('[name="color_prompt"]');
      if (input) input.value = draft.prompt;
    }
    updateColorBloomVisual(form, color);
    return true;
  }
  function setBloomLightness(lightness) {
    if (!state.colorDraft) return;
    const current = hexToHsl(state.colorDraft.base_color);
    setColorDraftBaseColor(hslToHex(current.h, current.s, clamp(lightness, 4, 96)));
  }
  function setBloomLightnessFromPointer(slider, clientY) {
    const bounds = slider?.getBoundingClientRect();
    if (!bounds?.height) return;
    const trackStart = bounds.top + bounds.height * (12 / 148);
    const trackEnd = bounds.top + bounds.height * (136 / 148);
    const ratio = clamp((clientY - trackStart) / Math.max(1, trackEnd - trackStart), 0, 1);
    setBloomLightness(100 - ratio * 100);
  }
  function beginBloomLightnessDrag(event, slider) {
    if (!slider || event.button > 0) return;
    event.preventDefault();
    slider.focus?.({ preventScroll: true });
    slider.classList.add('is-dragging');
    setBloomLightnessFromPointer(slider, event.clientY);
    const move = pointerEvent => setBloomLightnessFromPointer(slider, pointerEvent.clientY);
    const end = () => {
      slider.classList.remove('is-dragging');
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
  }
  function resetColorAnalysis() {
    const previous = state.colorAnalysis;
    if (previous?.previewObjectUrl) URL.revokeObjectURL(previous.previewObjectUrl);
    const next = newColorAnalysisState();
    next.requestId = Number(previous?.requestId || 0) + 1;
    state.colorAnalysis = next;
  }
  function colorAnalysisFocusTarget(analysis = state.colorAnalysis) {
    if (analysis?.error) return '[data-prompt-action="retry-color-analysis"]';
    return '[data-color-analysis-drop]';
  }
  function activeColorAnalysisModeTarget() {
    const mode = document.activeElement?.closest?.('[data-color-analysis-mode]')?.dataset.colorAnalysisMode;
    return ['balanced', 'subject', 'vivid'].includes(mode) ? `[data-color-analysis-mode="${mode}"]` : '';
  }
  function shouldRestoreColorAnalysisFocus() {
    const active = document.activeElement;
    return !active || active === document.body || !!active.closest?.('[data-color-analysis]');
  }
  function renderColorAnalysis(focusSelector = '') {
    if (!state.colorDraft || !state.colorAnalysis.open) return;
    const current = els.deskPromptLibraryEditor?.querySelector('[data-color-analysis]');
    if (!current) return;
    current.outerHTML = colorAnalysisHtml();
    if (focusSelector) {
      requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector(focusSelector)?.focus?.({ preventScroll: true }));
    }
  }
  function captureColorDraftFocus() {
    const active = document.activeElement;
    if (!active || !els.deskPromptLibraryEditor?.contains(active)) return null;
    const customSelect = active.closest?.('.desk-select-shell')?.previousElementSibling;
    const field = customSelect?.name ? customSelect : active;
    if (!field?.name) return null;
    return {
      name: field.name,
      customSelect: field !== active,
      selectionStart: Number.isFinite(active.selectionStart) ? active.selectionStart : null,
      selectionEnd: Number.isFinite(active.selectionEnd) ? active.selectionEnd : null,
    };
  }
  function renderColorDraftPreservingFocus(fallbackSelector = '') {
    const focus = captureColorDraftFocus();
    const restoreFallback = !focus && shouldRestoreColorAnalysisFocus() ? fallbackSelector : '';
    const scrollTop = els.deskPromptLibraryEditor?.scrollTop || 0;
    renderEditor();
    if (els.deskPromptLibraryEditor) els.deskPromptLibraryEditor.scrollTop = scrollTop;
    requestAnimationFrame(() => {
      let target = focus?.name ? els.deskPromptLibraryEditor?.querySelector(`[name="${focus.name}"]`) : null;
      if (target && focus.customSelect) target = target.nextElementSibling?.querySelector('.desk-select-trigger') || target;
      if (!target && restoreFallback) target = els.deskPromptLibraryEditor?.querySelector(restoreFallback);
      target?.focus?.({ preventScroll: true });
      if (focus && Number.isFinite(focus.selectionStart) && target?.setSelectionRange) {
        target.setSelectionRange(focus.selectionStart, focus.selectionEnd ?? focus.selectionStart);
      }
    });
  }
  function colorAnalysisHasSource(analysis = state.colorAnalysis) {
    return !!analysis?.sourceBlob;
  }
  function colorAnalysisSourceLocked(analysis = state.colorAnalysis) {
    return !!analysis?.busy;
  }
  function toggleColorAnalysis() {
    if (!state.colorDraft) return;
    syncColorDraftFromForm();
    const analysis = state.colorAnalysis;
    analysis.open = !analysis.open;
    state.colorBloomOpen = false;
    renderEditor();
    requestAnimationFrame(() => {
      const selector = analysis.open ? colorAnalysisFocusTarget(analysis) : '[data-prompt-action="toggle-color-analysis"]';
      els.deskPromptLibraryEditor?.querySelector(selector)?.focus?.({ preventScroll: true });
    });
  }
  function applyColorAnalysisResult(result) {
    const draft = syncColorDraftFromForm();
    if (!draft || !result?.roles?.length) return false;
    const previousAutoDescription = draftDescription(draft);
    const previousAutoPrompt = draftPrompt(draft);
    const updateDescription = draft.description === previousAutoDescription;
    const updatePrompt = draft.prompt === previousAutoPrompt;
    draft.colors = result.roles.slice(0, 5).map(role => safeColor(role.color));
    draft.base_color = draft.colors[0];
    draft.formula = colorFormula(result.formula).id;
    draft.temperature = ['auto', 'warm', 'cool'].includes(result.temperature) ? result.temperature : 'auto';
    draft.contrast = ['soft', 'balanced', 'high'].includes(result.contrast) ? result.contrast : 'balanced';
    draft.neutral_balance = true;
    draft.use_ratio = true;
    if (updateDescription) draft.description = draftDescription(draft);
    if (updatePrompt) draft.prompt = draftPrompt(draft);
    state.colorBloomOpen = false;
    return true;
  }
  async function runColorAnalysis() {
    const analysis = state.colorAnalysis;
    if (analysis.busy) return;
    const source = analysis.sourceBlob;
    if (!source) return;
    const modeFocusTarget = activeColorAnalysisModeTarget();
    syncColorDraftFromForm();
    const requestId = ++analysis.requestId;
    let applied = false;
    analysis.busy = true;
    analysis.error = '';
    analysis.result = null;
    renderColorAnalysis();
    try {
      if (!window.DesktopColorExtractor?.analyze) throw new Error('颜色分析模块未加载');
      const result = await window.DesktopColorExtractor.analyze(source, { mode: analysis.mode });
      if (state.colorAnalysis !== analysis || requestId !== analysis.requestId) return;
      analysis.result = result;
      applied = applyColorAnalysisResult(result);
    } catch (error) {
      if (state.colorAnalysis !== analysis || requestId !== analysis.requestId) return;
      analysis.error = error?.message || String(error);
    } finally {
      if (state.colorAnalysis === analysis && requestId === analysis.requestId) {
        analysis.busy = false;
        const focusTarget = modeFocusTarget || colorAnalysisFocusTarget(analysis);
        if (applied) renderColorDraftPreservingFocus(focusTarget);
        else {
          const focusSelector = shouldRestoreColorAnalysisFocus() ? focusTarget : '';
          renderColorAnalysis(focusSelector);
        }
      }
    }
  }
  async function handleColorAnalysisFile(file, sourceKind = 'upload') {
    const analysis = state.colorAnalysis;
    if (!file || colorAnalysisSourceLocked(analysis)) return;
    if (!/^image\/(png|jpeg|webp)$/i.test(file.type || '')) {
      notify('请选择 PNG、JPG 或 WebP 图片', 'warning');
      return;
    }
    if (file.size > 24 * 1024 * 1024) {
      notify('图片不能超过 24MB', 'warning');
      return;
    }
    syncColorDraftFromForm();
    const requestId = ++analysis.requestId;
    analysis.busy = false;
    analysis.result = null;
    try {
      if (analysis.previewObjectUrl) URL.revokeObjectURL(analysis.previewObjectUrl);
      const previewObjectUrl = URL.createObjectURL(file);
      analysis.sourceBlob = file;
      analysis.previewObjectUrl = previewObjectUrl;
      analysis.previewUrl = previewObjectUrl;
      analysis.fileName = file.name || (sourceKind === 'clipboard' ? '剪贴板图片' : '上传图片');
      analysis.sourceKind = sourceKind;
      analysis.result = null;
      analysis.error = '';
      await runColorAnalysis();
    } catch (error) {
      if (state.colorAnalysis !== analysis || requestId !== analysis.requestId) return;
      analysis.error = error?.message || String(error);
      analysis.busy = false;
      renderColorAnalysis(colorAnalysisFocusTarget(analysis));
    }
  }
  function clearColorAnalysis() {
    if (colorAnalysisSourceLocked()) return;
    syncColorDraftFromForm();
    const previous = state.colorAnalysis;
    const mode = previous.mode;
    resetColorAnalysis();
    state.colorAnalysis.open = true;
    state.colorAnalysis.mode = mode;
    renderColorAnalysis('[data-color-analysis-drop]');
  }
  function setColorAnalysisMode(mode) {
    if (!['balanced', 'subject', 'vivid'].includes(mode)) return;
    syncColorDraftFromForm();
    const analysis = state.colorAnalysis;
    if (colorAnalysisSourceLocked(analysis)) return;
    if (analysis.mode === mode) return;
    analysis.mode = mode;
    if (colorAnalysisHasSource(analysis)) {
      runColorAnalysis();
      return;
    }
    renderColorAnalysis(`[data-color-analysis-mode="${mode}"]`);
  }
  function hasUnsavedColorDraftChanges() {
    if (!state.colorDraft) return false;
    syncColorDraftFromForm();
    return colorDraftFingerprint(state.colorDraft) !== state.colorDraftBaseline;
  }
  function confirmColorDraftDiscard() {
    if (!hasUnsavedColorDraftChanges()) return true;
    return !window.confirm || window.confirm('当前配色方案有未保存修改，确定放弃吗？');
  }
  function discardColorDraft() {
    resetColorAnalysis();
    state.colorDraft = null;
    state.colorDraftBaseline = null;
    state.colorBloomOpen = false;
  }
  function startNewColor(source = null, duplicate = false) {
    if (state.colorDraft && !confirmColorDraftDiscard()) return false;
    setColorDraft(createColorDraft(source, duplicate));
    state.workspace = 'colors';
    state.favoriteOnly = false;
    render();
    requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector('[name="color_name"]')?.focus?.({ preventScroll: true }));
    return true;
  }
  function regenerateColorDraft() {
    const draft = syncColorDraftFromForm();
    if (!draft) return;
    draft.colors = generateFormulaColors(draft.base_color, draft.formula, draft.contrast, draft.neutral_balance, draft.temperature);
    draft.description = draftDescription(draft);
    draft.prompt = draftPrompt(draft);
    renderEditor();
  }
  function applyColorIndustry() {
    const draft = syncColorDraftFromForm();
    if (!draft) return;
    const industry = colorIndustry(draft.industry);
    draft.base_color = industry.base;
    draft.formula = industry.formula;
    draft.temperature = ['finance', 'uiux', 'web'].includes(industry.id) ? 'cool' : ['fashion', 'illustration'].includes(industry.id) ? 'warm' : 'auto';
    draft.scenes = industry.scenes.slice();
    draft.tags = industry.tags.slice();
    draft.colors = generateFormulaColors(draft.base_color, draft.formula, draft.contrast, draft.neutral_balance, draft.temperature);
    draft.description = draftDescription(draft);
    draft.prompt = draftPrompt(draft);
    renderEditor();
  }
  function validateColorDraftForm() {
    const form = els.deskPromptLibraryEditor?.querySelector('[data-color-draft-form]');
    if (!form) throw new Error('配色编辑器未加载');
    const invalidHex = Array.from(form.querySelectorAll('[name="color_base_hex"], [name^="color_hex_"]')).find(input => !/^#[0-9a-f]{6}$/i.test(cleanText(input.value)));
    if (invalidHex) { invalidHex.focus?.({ preventScroll: true }); throw new Error('色值必须使用完整的 HEX 格式，例如 #2563EB'); }
  }
  function saveColorDraft(event) {
    event?.preventDefault?.();
    try {
      validateColorDraftForm();
      const draft = syncColorDraftFromForm();
      if (!draft?.name) throw new Error('请输入配色方案名称');
      if (!draft.prompt) throw new Error('请输入提示词片段');
      const id = draft.id || `custom-color-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
      const existing = state.colors.find(item => itemId(item) === id);
      const item = normalizeCustomColor({ ...draft, id });
      if (!item) throw new Error('配色方案内容无效');
      item.favorite = !!existing?.favorite;
      state.colors = [item, ...state.colors.filter(color => itemId(color) !== id)];
      state.selected.colors = id;
      saveCustomColors();
      discardColorDraft();
      render();
      notify(existing ? '自定义配色方案已更新。' : '自定义配色方案已保存。');
    } catch (error) { reportError(error, '配色方案保存失败'); }
  }
  function cancelColorDraft() {
    if (!confirmColorDraftDiscard()) return;
    discardColorDraft(); renderEditor();
  }
  function deleteColorDraft() {
    const draft = syncColorDraftFromForm();
    if (!draft?.id) return;
    if (window.confirm && !window.confirm(`确定删除“${draft.name || '自定义配色'}”？`)) return;
    state.colors = state.colors.filter(item => itemId(item) !== draft.id);
    state.selected.colors = itemId(state.colors[0]);
    saveCustomColors(); saveColorFavorites(); discardColorDraft(); render(); notify('自定义配色方案已删除。');
  }

  function renderEditor() {
    if (!els.deskPromptLibraryEditor) return;
    if (state.workspace === 'blocks') {
      const item = state.blocks.find(block => itemId(block) === state.selected.blocks);
      if (item) {
        if (!state.blockDraft || itemId(state.blockDraft) !== state.selected.blocks) setBlockDraft(item);
        els.deskPromptLibraryEditor.innerHTML = blockEditorHtml(state.blockDraft);
      } else if (state.blockDraft && !itemId(state.blockDraft)) {
        if (state.blockBaseline === null) state.blockBaseline = blockFingerprint(state.blockDraft);
        els.deskPromptLibraryEditor.innerHTML = blockEditorHtml(state.blockDraft);
      } else {
        els.deskPromptLibraryEditor.innerHTML = emptyEditor('选择或新建一个素材块');
      }
    } else if (state.workspace === 'templates') els.deskPromptLibraryEditor.innerHTML = state.ruleDraft ? ruleDraftEditorHtml(state.ruleDraft) : templateEditorHtml(currentItem());
    else if (state.workspace === 'colors') els.deskPromptLibraryEditor.innerHTML = state.colorDraft ? colorDraftEditorHtml(state.colorDraft) : colorEditorHtml(currentItem());
    else els.deskPromptLibraryEditor.innerHTML = inspirationEditorHtml(currentItem());
    refreshSelects();
  }

  function render() {
    updateWriteControls();
    if (els.deskPromptLibraryNewBtn) {
      const isColors = state.workspace === 'colors';
      els.deskPromptLibraryNewBtn.title = isColors ? '新建配色方案' : '新建素材块';
      const label = els.deskPromptLibraryNewBtn.querySelector('span');
      if (label) label.textContent = isColors ? '新建配色方案' : '新建素材块';
    }
    els.deskPromptLibraryTabs?.querySelectorAll('[data-prompt-workspace]').forEach(button => {
      const active = button.dataset.promptWorkspace === state.workspace;
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
      if (active) els.deskPromptLibraryWorkspace?.setAttribute('aria-labelledby', button.id);
    });
    if (els.deskPromptLibraryFavoriteFilter) {
      els.deskPromptLibraryFavoriteFilter.hidden = !['blocks', 'colors'].includes(state.workspace);
      els.deskPromptLibraryFavoriteFilter.disabled = state.workspace === 'colors' && !!state.colorDraft;
      els.deskPromptLibraryFavoriteFilter.setAttribute('aria-pressed', state.favoriteOnly ? 'true' : 'false');
    }
    if (els.deskPromptLibrarySearchInput) {
      const placeholders = { blocks: '搜索名称、内容或标签', templates: '搜索拆分规则', colors: '搜索方案、色值或场景', inspiration: '搜索远程提示词' };
      els.deskPromptLibrarySearchInput.placeholder = placeholders[state.workspace] || placeholders.blocks;
      els.deskPromptLibrarySearchInput.disabled = (state.workspace === 'colors' && !!state.colorDraft) || (state.workspace === 'templates' && !!state.ruleDraft);
    }
    renderNav(); renderList(); renderEditor();
  }

  function inspirationFilters() {
    const category = state.category.inspiration;
    return {
      source: category && category !== 'all' ? category : '',
      query: cleanText(els.deskPromptLibrarySearchInput?.value),
    };
  }
  function inspirationFilterKey(filters = inspirationFilters()) {
    return `${filters.source}\n${filters.query.toLowerCase()}`;
  }
  function mergeInspirationItems(current, page) {
    const seen = new Set();
    return [...current, ...page].filter((item, index) => {
      const id = itemId(item);
      const key = id || `anonymous_${index}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  async function loadInspiration(options = {}) {
    const append = !!options.append;
    const force = !!options.force;
    const filters = inspirationFilters();
    const filterKey = inspirationFilterKey(filters);
    const sameFilter = filterKey === state.inspirationFilterKey;
    if (!append && !force && sameFilter && state.inspirationLoaded) return true;
    if (append && (!sameFilter || state.inspirationLoading || state.inspiration.length >= state.inspirationTotal)) return false;

    const requestId = ++state.inspirationRequestId;
    const offset = append ? state.inspiration.length : 0;
    if (!append) {
      state.inspiration = [];
      state.inspirationTotal = 0;
      state.inspirationLoaded = false;
      state.inspirationFilterKey = filterKey;
      state.selected.inspiration = '';
    }
    state.inspirationLoading = true;
    state.inspirationLoadingMore = append;
    if (state.workspace === 'inspiration') { renderList(); renderEditor(); }
    try {
      const result = await window.DesktopApi.getPromptSourceItems({
        limit: INSPIRATION_PAGE_SIZE,
        offset,
        source: filters.source,
        query: filters.query,
      });
      if (requestId !== state.inspirationRequestId || filterKey !== inspirationFilterKey()) return false;
      const page = Array.isArray(result?.items) ? result.items : [];
      state.inspiration = append ? mergeInspirationItems(state.inspiration, page) : page;
      const reportedTotal = Number(result?.total);
      state.inspirationTotal = Number.isFinite(reportedTotal) ? Math.max(0, reportedTotal) : offset + page.length;
      state.inspirationLoaded = true;
      if (!state.selected.inspiration || !state.inspiration.some(item => itemId(item) === state.selected.inspiration)) {
        state.selected.inspiration = itemId(state.inspiration[0]);
      }
      return true;
    } catch (error) {
      if (requestId !== state.inspirationRequestId || filterKey !== inspirationFilterKey()) return false;
      throw error;
    } finally {
      if (requestId === state.inspirationRequestId) {
        state.inspirationLoading = false;
        state.inspirationLoadingMore = false;
        if (state.workspace === 'inspiration') { renderList(); renderEditor(); }
      }
    }
  }
  async function loadAll(options = {}) {
    if (!window.DesktopApi?.getPromptBlocks) throw new Error('素材块 API 未加载');
    state.loading = true; renderList();
    try {
      const [blocks, templates, sources] = await Promise.all([
        window.DesktopApi.getPromptBlocks({ limit: 1000 }),
        window.DesktopApi.getPromptTemplates(),
        window.DesktopApi.getPromptSources().catch(() => ({ sources: [] }))
      ]);
      state.blocks = blocks?.items || [];
      state.templates = templates?.templates || [];
      state.sources = sources?.sources || [];
      if (state.workspace === 'inspiration') await loadInspiration({ force: !!options.force });
      for (const workspace of ['blocks', 'templates', 'colors']) {
        const list = workspace === 'blocks' ? state.blocks : workspace === 'templates' ? state.templates : state.colors;
        if (state.selected[workspace] && !list.some(item => itemId(item) === state.selected[workspace])) state.selected[workspace] = '';
        const keepNewBlock = workspace === 'blocks' && state.blockDraft && !itemId(state.blockDraft);
        if (!state.selected[workspace] && list.length && !options.keepNew && !keepNewBlock) state.selected[workspace] = itemId(list[0]);
      }
    } finally { state.loading = false; render(); }
  }

  async function switchWorkspace(workspace) {
    if (!['blocks', 'templates', 'colors', 'inspiration'].includes(workspace)) return false;
    if (workspace !== state.workspace && guardWriteBusy()) return false;
    if (state.inspirationSearchTimer) {
      window.clearTimeout(state.inspirationSearchTimer);
      state.inspirationSearchTimer = 0;
    }
    if (state.workspace === 'inspiration' && workspace !== 'inspiration') {
      state.inspirationRequestId += 1;
      state.inspirationLoading = false;
      state.inspirationLoadingMore = false;
    }
    if (workspace !== state.workspace && state.workspace === 'blocks') {
      if (!confirmBlockDiscard()) return false;
      discardBlockDraft();
    }
    if (workspace !== state.workspace && state.workspace === 'templates' && state.ruleDraft) {
      if (!confirmRuleDiscard()) return false;
      discardRuleDraft();
    }
    if (workspace !== state.workspace && state.workspace === 'colors' && state.colorDraft) {
      if (!confirmColorDraftDiscard()) return false;
      discardColorDraft();
    }
    state.workspace = workspace; state.favoriteOnly = false;
    if (els.deskPromptLibrarySearchInput) els.deskPromptLibrarySearchInput.value = '';
    if (workspace === 'inspiration' && (!state.inspirationLoaded || state.inspirationFilterKey !== inspirationFilterKey())) {
      render();
      try { await loadInspiration(); }
      catch (error) { reportError(error, '灵感库读取失败'); }
    }
    render();
    return true;
  }
  async function selectItem(id, primaryAction = false) {
    const nextId = String(id || '');
    if ((nextId !== state.selected[state.workspace] || primaryAction) && guardWriteBusy()) return;
    if (state.workspace === 'blocks' && nextId !== state.selected.blocks) {
      if (!confirmBlockDiscard()) return;
      discardBlockDraft();
    }
    if (state.workspace === 'templates' && state.ruleDraft && (nextId !== state.selected.templates || primaryAction)) {
      if (!confirmRuleDiscard()) return;
      discardRuleDraft();
    }
    if (state.workspace === 'colors' && state.colorDraft) {
      if (!confirmColorDraftDiscard()) return;
      discardColorDraft();
    }
    state.selected[state.workspace] = nextId;
    renderList(); renderEditor();
    if (!primaryAction) return;
    if (state.workspace === 'blocks') insertBlock();
    else if (state.workspace === 'templates') openExtractor('text', { primaryType: currentItem()?.primary_type || '', ruleId: itemId(currentItem()), splitRule: currentItem() });
    else if (state.workspace === 'colors') insertColor();
    else openExtractor('text', { text: currentItem()?.prompt || '', primaryType: inferType(currentItem()), sourceTitle: currentItem()?.title || '' });
  }

  function startNew() {
    if (guardWriteBusy()) return;
    if (state.workspace === 'colors') { startNewColor(); return; }
    if (state.workspace === 'templates' && state.ruleDraft) {
      if (!confirmRuleDiscard()) return;
      discardRuleDraft();
    }
    if (state.workspace === 'blocks' && !confirmBlockDiscard()) return;
    discardBlockDraft();
    state.workspace = 'blocks'; state.selected.blocks = ''; setBlockDraft(newBlock());
    render(); els.deskPromptLibraryEditor?.querySelector('input[name="name"]')?.focus({ preventScroll: true });
  }
  function syncBlockDraftFromForm() {
    const form = els.deskPromptLibraryEditor?.querySelector('[data-prompt-block-form]');
    if (!form) throw new Error('素材块编辑器未加载');
    const draft = {
      id: cleanText(form.querySelector('[name="id"]')?.value), name: cleanText(form.querySelector('[name="name"]')?.value),
      module_type: cleanText(form.querySelector('[name="module_type"]')?.value) || 'custom', content: cleanText(form.querySelector('[name="content"]')?.value),
      compact_content: cleanText(form.querySelector('[name="compact_content"]')?.value), english_content: cleanText(form.querySelector('[name="english_content"]')?.value),
      applicable_types: parseTags(form.querySelector('[name="applicable_types"]')?.value), tags: parseTags(form.querySelector('[name="tags"]')?.value), favorite: !!state.blockDraft?.favorite
    };
    state.blockDraft = draft;
    return draft;
  }
  function blockPayload() {
    const payload = syncBlockDraftFromForm();
    if (!payload.name) throw new Error('请输入素材块名称');
    if (!payload.content) throw new Error('请输入素材块内容');
    return payload;
  }
  async function saveBlock(event) {
    event?.preventDefault?.();
    if (state.blockSaveBusy) return;
    let requestId = 0;
    try {
      const payload = blockPayload();
      requestId = ++state.blockSaveCounter;
      state.blockSaveBusy = true;
      state.blockWriteAction = 'save';
      render();
      const result = await window.DesktopApi.savePromptBlock(payload); const block = result?.block;
      if (requestId !== state.blockSaveCounter) return;
      if (!block?.id) throw new Error('服务未返回素材块');
      state.blockSaveBusy = false;
      state.blockWriteAction = '';
      resetExtractorState();
      state.blocks = [block, ...state.blocks.filter(item => item.id !== block.id)]; state.selected.blocks = block.id; setBlockDraft(block);
      render(); notify(payload.id ? '素材块已更新。' : '素材块已保存，可通过 / 插入。'); window.DesktopPromptInsert?.refresh?.();
    } catch (error) {
      if (requestId && requestId !== state.blockSaveCounter) return;
      state.blockSaveBusy = false;
      state.blockWriteAction = '';
      render();
      reportError(error, '素材块保存失败');
    }
  }
  async function deleteBlock() {
    if (state.blockSaveBusy) return;
    const block = syncBlockDraftFromForm(); if (!block?.id) return;
    if (window.confirm && !window.confirm(`确定删除“${block.name}”？`)) return;
    const requestId = ++state.blockSaveCounter;
    state.blockSaveBusy = true;
    state.blockWriteAction = 'delete';
    render();
    try {
      await window.DesktopApi.deletePromptBlock(block.id);
      if (requestId !== state.blockSaveCounter) return;
      state.blocks = state.blocks.filter(item => item.id !== block.id); state.selected.blocks = itemId(state.blocks[0]); discardBlockDraft();
      render(); notify('素材块已删除。'); window.DesktopPromptInsert?.refresh?.();
    } catch (error) {
      if (requestId !== state.blockSaveCounter) return;
      state.blockSaveBusy = false;
      state.blockWriteAction = '';
      render();
      throw error;
    }
  }
  function sendBlockToCanvas(block) {
    if (!block || !cleanText(block.content)) throw new Error('素材块内容为空');
    const canvas = window.DesktopCanvas; if (!canvas) throw new Error('画布模块未加载');
    if (!canvas.insertPromptBlockToken) throw new Error('画布素材块编辑器未加载');
    let target = canvas.getPromptTargetInfo?.();
    let created = false;
    if (target?.type !== 'text') {
      const nodeId = canvas.createTextNodeWithText?.('');
      if (!nodeId) throw new Error('无法创建文本节点');
      target = canvas.getPromptTargetInfo?.(nodeId) || { nodeId, type: 'text', label: '新文本节点' };
      created = true;
    }
    canvas.insertPromptBlockToken(block, { targetInfo: target });
    notify(created ? '已创建文本节点并插入素材块。' : `已插入到文本节点：${target.label || '文本节点'}`);
  }
  function insertBlock() {
    try {
      const block = state.workspace === 'blocks' ? syncBlockDraftFromForm() : (state.blockDraft || currentItem());
      sendBlockToCanvas(block); if (block?.id) window.DesktopApi.markPromptBlockUsed(block.id).catch(() => {});
    }
    catch (error) { reportError(error, '素材块插入失败'); }
  }
  function colorPromptBlock(item) {
    if (!item) return null;
    return {
      id: `color-scheme:${item.id}`,
      name: `配色 · ${item.name}`,
      module_type: 'color',
      content: item.prompt,
      compact_content: `${item.description} ${item.colors.join(' ')}`,
      english_content: '',
      applicable_types: [],
      colors: (item.colors || []).slice(0, 5),
      tags: [...(item.tags || []), ...(item.colors || [])],
    };
  }
  function insertColor() {
    try { sendBlockToCanvas(colorPromptBlock(currentItem())); }
    catch (error) { reportError(error, '色彩方案插入失败'); }
  }
  function toggleColorFavorite() {
    const item = currentItem();
    if (!item || state.workspace !== 'colors') return;
    item.favorite = !item.favorite;
    saveColorFavorites();
    if (state.favoriteOnly && !item.favorite) state.selected.colors = itemId(filteredItems()[0]);
    renderList(); renderEditor();
  }
  async function copyText(text, message = '已复制。') {
    const value = cleanText(text); if (!value) throw new Error('没有可复制的内容');
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
    else { const textarea = document.createElement('textarea'); textarea.value = value; textarea.style.cssText = 'position:fixed;opacity:0'; document.body.append(textarea); textarea.select(); document.execCommand('copy'); textarea.remove(); }
    notify(message);
  }
  function inferType(item) {
    const text = `${item?.title || ''} ${item?.prompt || ''} ${(item?.taxonomy?.subject || []).join(' ')}`.toLowerCase();
    if (/poster|海报|banner|kv|封面/.test(text)) return 'poster'; if (/product|商品|产品|电商/.test(text)) return 'product';
    if (/landscape|风景|山|海|forest/.test(text)) return 'landscape'; if (/food|美食|餐饮/.test(text)) return 'food';
    if (/interior|室内/.test(text)) return 'interior'; if (/architecture|建筑/.test(text)) return 'architecture'; return '';
  }
  async function saveInspirationAsBlock() {
    const item = currentItem(); if (!item?.prompt) return;
    const result = await window.DesktopApi.savePromptBlock({ name: item.title || '灵感素材块', module_type: 'custom', content: item.prompt, tags: item.tags || [], applicable_types: inferType(item) ? [inferType(item)] : [], source: `inspiration:${item.sourceSlug || 'remote'}` });
    if (result?.block) state.blocks = [result.block, ...state.blocks.filter(block => block.id !== result.block.id)];
    window.DesktopPromptInsert?.refresh?.(); notify('已保存为素材块。');
  }

  function extractorInputHtml() {
    const extractor = state.extractor;
    const isImage = extractor.mode === 'image';
    const rule = extractor.splitRule || state.templates.find(item => itemId(item) === extractor.ruleId);
    const scope = rule
      ? `<div class="desk-prompt-extractor__rule"><span>拆分规则</span><strong>${escapeHtml(rule.name)}</strong><em>${rule.system ? '内置' : `自定义 v${Number(rule.version || 1)}`}</em><input type="hidden" name="extract_primary_type" value="${escapeHtml(rule.primary_type)}"></div>`
      : `<label class="desk-prompt-field"><span>适用类型</span><select name="extract_primary_type" ${extractor.busy ? 'disabled' : ''}>${typeOptions(extractor.primaryType, true)}</select></label>`;
    return `<div class="desk-prompt-extractor__body">
      <div class="desk-prompt-extractor__scope">${scope}</div>
      ${isImage ? `<label class="desk-prompt-extractor__drop ${extractor.imageData ? 'has-image' : ''} ${extractor.busy ? 'is-disabled' : ''}" data-prompt-image-drop role="button" tabindex="${extractor.busy ? '-1' : '0'}" aria-disabled="${extractor.busy ? 'true' : 'false'}"><input type="file" name="extract_image" accept="image/png,image/jpeg,image/webp" ${extractor.busy ? 'disabled' : ''} hidden>${extractor.imageData ? `<img src="${escapeHtml(extractor.imageData)}" alt="上传预览"><span>${escapeHtml(extractor.imageName)}</span>` : '<strong>选择或拖入图片</strong><span>PNG、JPG、WebP</span>'}</label><label class="desk-prompt-field"><span>补充要求</span><textarea name="extract_direction" placeholder="可选，例如：重点拆分服装、妆发和光线" ${extractor.busy ? 'disabled' : ''}>${escapeHtml(extractor.direction)}</textarea></label>` : `<label class="desk-prompt-field desk-prompt-extractor__text"><span>完整提示词</span><textarea name="extract_text" placeholder="粘贴需要拆分的完整提示词" ${extractor.busy ? 'disabled' : ''}>${escapeHtml(extractor.text)}</textarea></label>`}
      ${extractor.error ? `<div class="desk-prompt-extractor__error">${escapeHtml(extractor.error)}</div>` : ''}
    </div><div class="desk-prompt-extractor__footer"><button type="button" data-extractor-action="close" ${extractor.busy ? 'disabled' : ''}>返回手动新建</button><button type="button" class="is-primary" data-extractor-action="run" ${extractor.busy ? 'disabled' : ''}>${extractor.busy ? (isImage ? '正在解析…' : '正在拆分…') : (isImage ? '解析图片' : '开始拆分')}</button></div>`;
  }
  function extractorResultsHtml() {
    const selectedCount = state.extractor.candidates.filter(item => item.selected).length;
    return `<div class="desk-prompt-extractor__result-body"><div class="desk-prompt-extractor__result-toolbar"><div class="desk-prompt-extractor__result-head"><span>${state.extractor.candidates.length} 个候选</span><button type="button" data-extractor-action="toggle-all" ${state.extractor.busy ? 'disabled' : ''}>${selectedCount === state.extractor.candidates.length ? '取消全选' : '全选'}</button></div>${state.extractor.error ? `<div class="desk-prompt-extractor__error">${escapeHtml(state.extractor.error)}</div>` : ''}</div><div class="desk-prompt-extractor__results">
      ${state.extractor.candidates.map((block, index) => `<article class="desk-prompt-extractor-block ${block.selected ? 'is-selected' : ''}" data-extractor-index="${index}"><label class="desk-prompt-extractor-block__check"><input type="checkbox" name="candidate_selected" aria-label="选择素材块：${escapeHtml(block.name || `候选 ${index + 1}`)}" ${block.selected ? 'checked' : ''} ${state.extractor.busy ? 'disabled' : ''}><span></span></label><div class="desk-prompt-extractor-block__fields"><div class="desk-prompt-field-grid"><label class="desk-prompt-field"><span>名称</span><input name="candidate_name" value="${escapeHtml(block.name || '')}" ${state.extractor.busy ? 'disabled' : ''}></label><label class="desk-prompt-field"><span>模块</span><select name="candidate_module" ${state.extractor.busy ? 'disabled' : ''}>${moduleTypeOptions(block.module_type)}</select></label></div><label class="desk-prompt-field"><span>内容</span><textarea name="candidate_content" ${state.extractor.busy ? 'disabled' : ''}>${escapeHtml(block.content || '')}</textarea></label></div></article>`).join('')}
    </div></div><div class="desk-prompt-extractor__footer"><button type="button" data-extractor-action="back" ${state.extractor.busy ? 'disabled' : ''}>返回</button><span>${selectedCount} 个待保存</span><button type="button" class="is-primary" data-extractor-action="save" ${!selectedCount || state.extractor.busy ? 'disabled' : ''}>${state.extractor.busy ? '保存中…' : '保存选中素材块'}</button></div>`;
  }
  function captureExtractorFocus(root) {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement) || !root.contains(active)) return null;
    const card = active.closest('[data-extractor-index]');
    const action = active.closest('[data-extractor-action]');
    const snapshot = {
      index: card ? Number(card.dataset.extractorIndex) : -1,
      name: active.getAttribute('name') || '',
      action: action?.dataset.extractorAction || '',
      drop: !!active.closest('[data-prompt-image-drop]'),
      selectionStart: null,
      selectionEnd: null,
    };
    if (typeof active.selectionStart === 'number') {
      snapshot.selectionStart = active.selectionStart;
      snapshot.selectionEnd = active.selectionEnd;
    }
    return snapshot;
  }
  function restoreExtractorFocus(root, snapshot) {
    if (!snapshot) return false;
    const scope = snapshot.index >= 0 ? root.querySelector(`[data-extractor-index="${snapshot.index}"]`) : root;
    if (!scope) return false;
    let target = null;
    if (snapshot.name) target = Array.from(scope.querySelectorAll('[name]')).find(element => element.getAttribute('name') === snapshot.name) || null;
    if (!target && snapshot.action) target = Array.from(root.querySelectorAll('[data-extractor-action]')).find(element => element.dataset.extractorAction === snapshot.action) || null;
    if (!target && snapshot.drop) target = root.querySelector('[data-prompt-image-drop]');
    if (!target || target.disabled) return false;
    target.focus?.({ preventScroll: true });
    if (snapshot.selectionStart !== null && typeof target.setSelectionRange === 'function') {
      const end = snapshot.selectionEnd ?? snapshot.selectionStart;
      target.setSelectionRange(Math.min(snapshot.selectionStart, target.value.length), Math.min(end, target.value.length));
    }
    return document.activeElement === target;
  }
  function renderExtractor() {
    const root = els.deskPromptLibraryEditor;
    if (!root || !state.extractor.open) return;
    const extractor = state.extractor;
    state.extractorFocus = captureExtractorFocus(root) || state.extractorFocus;
    updateWriteControls();
    renderEditor();
    const focus = state.extractorFocus;
    requestAnimationFrame(() => {
      if (extractor !== state.extractor || !extractor.open) return;
      if (focus && !restoreExtractorFocus(root, focus)) focusExtractorInitial();
    });
  }
  function focusExtractorInitial() {
    const root = els.deskPromptLibraryEditor;
    const target = root?.querySelector('[name="extract_text"], [data-prompt-image-drop], [name="candidate_name"], [data-extractor-action="close"]');
    target?.focus?.({ preventScroll: true });
  }
  function resetExtractorState() {
    state.extractorSessionCounter += 1;
    state.extractorFileCounter += 1;
    state.extractorFocus = null;
    state.extractorDrafts = { text: null, image: null };
    state.extractor = newExtractorState('text');
  }
  function openExtractor(mode, options = {}) {
    if (guardWriteBusy()) return;
    if (state.workspace === 'blocks' && !confirmBlockDiscard()) return;
    discardBlockDraft();
    state.workspace = 'blocks';
    state.selected.blocks = '';
    setBlockDraft(newBlock());
    state.extractorSessionCounter += 1;
    state.extractorFocus = null;
    state.extractor = newExtractorState(mode, options);
    state.extractor.open = true;
    state.extractorDrafts[mode] = state.extractor;
    render(); requestAnimationFrame(focusExtractorInitial);
  }
  function switchCreateMode(mode) {
    if (!['manual', 'text', 'image'].includes(mode) || state.extractor.busy || guardWriteBusy()) return;
    const form = els.deskPromptLibraryEditor?.querySelector('[data-prompt-block-form]');
    if (form) syncBlockDraftFromForm();
    if (state.extractor.open) {
      syncExtractor();
      state.extractor.open = false;
      state.extractor.busy = false;
      state.extractor.busyAction = '';
      state.extractorDrafts[state.extractor.mode] = state.extractor;
    }
    state.extractorSessionCounter += 1;
    state.extractorFileCounter += 1;
    state.extractorFocus = null;
    if (mode === 'manual') {
      renderEditor();
      requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector('input[name="name"]')?.focus?.({ preventScroll: true }));
      return;
    }
    const context = mode === 'text'
      ? { primaryType: state.extractor.primaryType, ruleId: state.extractor.ruleId, splitRule: state.extractor.splitRule }
      : { primaryType: state.extractor.primaryType };
    state.extractor = state.extractorDrafts[mode] || newExtractorState(mode, context);
    state.extractor.open = true;
    state.extractor.busy = false;
    state.extractor.busyAction = '';
    state.extractorDrafts[mode] = state.extractor;
    renderEditor();
    requestAnimationFrame(focusExtractorInitial);
  }
  function closeExtractor() {
    switchCreateMode('manual');
  }
  function syncExtractor() {
    const root = els.deskPromptLibraryEditor; const extractor = state.extractor;
    if (!root) return;
    const primaryTypeField = root.querySelector('[name="extract_primary_type"]');
    if (primaryTypeField) extractor.primaryType = cleanText(primaryTypeField.value);
    extractor.text = root.querySelector('[name="extract_text"]')?.value ?? extractor.text;
    extractor.direction = root.querySelector('[name="extract_direction"]')?.value ?? extractor.direction;
    root.querySelectorAll('[data-extractor-index]').forEach(card => {
      const item = extractor.candidates[Number(card.dataset.extractorIndex)]; if (!item) return;
      item.selected = !!card.querySelector('[name="candidate_selected"]')?.checked;
      item.name = cleanText(card.querySelector('[name="candidate_name"]')?.value);
      item.module_type = cleanText(card.querySelector('[name="candidate_module"]')?.value) || 'custom';
      item.content = cleanText(card.querySelector('[name="candidate_content"]')?.value);
    });
  }
  function fileToDataUrl(file) {
    return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result || '')); reader.onerror = () => reject(new Error('图片读取失败')); reader.readAsDataURL(file); });
  }
  function isCurrentExtractorSession(extractor, sessionId) {
    return sessionId === state.extractorSessionCounter && state.extractor === extractor && extractor.open;
  }
  async function handleExtractorFile(file) {
    if (state.extractor.busy) return;
    syncExtractor();
    const extractor = state.extractor;
    const sessionId = state.extractorSessionCounter;
    const fileRequestId = ++state.extractorFileCounter;
    try {
      if (!file) return;
      if (!/^image\/(png|jpeg|webp)$/i.test(file.type || '')) throw new Error('请选择 PNG、JPG 或 WebP 图片');
      if (file.size > 24 * 1024 * 1024) throw new Error('图片不能超过 24MB');
      const imageData = await fileToDataUrl(file);
      if (fileRequestId !== state.extractorFileCounter || !isCurrentExtractorSession(extractor, sessionId)) return;
      extractor.imageData = imageData;
      extractor.imageName = file.name || '上传图片';
      extractor.imageType = file.type || 'image/png';
      extractor.error = '';
      renderExtractor();
    } catch (error) {
      if (fileRequestId !== state.extractorFileCounter || !isCurrentExtractorSession(extractor, sessionId)) return;
      extractor.error = error?.message || String(error);
      renderExtractor();
    }
  }
  async function runExtractor() {
    syncExtractor(); const extractor = state.extractor; const sessionId = state.extractorSessionCounter;
    const inputVersion = state.extractorFileCounter;
    if (extractor.mode === 'text' && !cleanText(extractor.text)) { extractor.error = '请粘贴完整提示词'; renderExtractor(); return; }
    if (extractor.mode === 'image' && !extractor.imageData) { extractor.error = '请先选择图片'; renderExtractor(); return; }
    extractor.busy = true; extractor.busyAction = 'extract'; extractor.error = ''; renderExtractor();
    try {
      const payload = extractor.mode === 'image'
        ? { mode: 'image', primary_type: extractor.primaryType, rule_id: extractor.ruleId, message: extractor.direction, images: [{ id: 'upload_image', label: extractor.imageName, data_url: extractor.imageData, mime_type: extractor.imageType, role: 'primary' }] }
        : { mode: 'text', primary_type: extractor.primaryType, rule_id: extractor.ruleId, text: extractor.text };
      const result = await window.DesktopApi.extractPromptBlocks(payload);
      if (!isCurrentExtractorSession(extractor, sessionId) || (extractor.mode === 'image' && inputVersion !== state.extractorFileCounter)) return;
      extractor.primaryType = result?.primary_type || extractor.primaryType;
      extractor.splitRule = result?.split_rule || extractor.splitRule;
      extractor.candidates = (result?.blocks || []).map((block, index) => ({ ...block, draftId: `draft_${index}`, selected: true }));
      if (!extractor.candidates.length) throw new Error('没有得到可保存的素材块');
      if (result?.warning) notify(result.warning, 'warning');
    } catch (error) {
      if (!isCurrentExtractorSession(extractor, sessionId) || (extractor.mode === 'image' && inputVersion !== state.extractorFileCounter)) return;
      extractor.error = error?.message || String(error); reportError(error, '素材块提取失败');
    } finally {
      if (isCurrentExtractorSession(extractor, sessionId)) { extractor.busy = false; extractor.busyAction = ''; renderExtractor(); }
    }
  }
  async function saveExtractedBlocks() {
    syncExtractor(); const extractor = state.extractor; const sessionId = state.extractorSessionCounter;
    const selected = extractor.candidates.filter(item => item.selected && item.name && item.content);
    if (!selected.length) { extractor.error = '请选择至少一个有效素材块'; renderExtractor(); return; }
    extractor.busy = true; extractor.busyAction = 'save'; extractor.error = ''; renderExtractor();
    try {
      const outcomes = await Promise.allSettled(selected.map(block => window.DesktopApi.savePromptBlock({
        ...block,
        source: extractor.mode === 'image' ? 'image_extractor' : (extractor.sourceTitle ? 'inspiration_extractor' : 'prompt_extractor'),
        source_rule_id: extractor.splitRule?.id || extractor.ruleId || '',
        source_rule_version: Number(extractor.splitRule?.version || 0),
        source_rule_snapshot: extractor.splitRule || {},
      })));
      if (!isCurrentExtractorSession(extractor, sessionId)) return;
      const saved = [];
      const savedCandidates = new Set();
      outcomes.forEach((outcome, index) => {
        const block = outcome.status === 'fulfilled' ? outcome.value?.block : null;
        if (!block?.id) return;
        saved.push(block);
        savedCandidates.add(selected[index]);
      });
      const failed = outcomes.length - saved.length;
      if (!saved.length) throw outcomes.find(item => item.status === 'rejected')?.reason || new Error('素材块保存失败');
      saved.forEach(block => { state.blocks = [block, ...state.blocks.filter(item => item.id !== block.id)]; });
      extractor.candidates = extractor.candidates.filter(candidate => !savedCandidates.has(candidate));
      extractor.busy = false;
      extractor.busyAction = '';
      window.DesktopPromptInsert?.refresh?.();
      if (extractor.candidates.length) {
        extractor.error = failed ? `${failed} 个素材块保存失败，可修改后重试。` : '';
        renderExtractor();
        notify(failed ? `已保存 ${saved.length} 个，${failed} 个可重试。` : `已保存 ${saved.length} 个，剩余候选未保存。`, failed ? 'warning' : 'success');
        return;
      }
      state.workspace = 'blocks'; state.category.blocks = 'all'; state.selected.blocks = saved[0]?.id || ''; discardBlockDraft();
      render();
      notify(`已保存 ${saved.length} 个素材块。`);
    } catch (error) {
      if (!isCurrentExtractorSession(extractor, sessionId)) return;
      extractor.error = error?.message || String(error); reportError(error, '素材块保存失败'); extractor.busy = false; extractor.busyAction = ''; renderExtractor();
    }
  }

  async function open() {
    window.DesktopHistory?.closeGallery?.(); window.DesktopSettings?.close?.();
    els.deskPromptLibraryPanel?.classList.add('is-open'); els.deskPromptLibraryPanel?.setAttribute('aria-hidden', 'false');
    document.querySelector('.desk-rail__item[data-tool="prompts"]')?.setAttribute('aria-expanded', 'true');
    try { await loadAll(); } catch (error) { state.loading = false; render(); reportError(error, '提示词素材库读取失败'); }
  }
  function close() {
    if (!els.deskPromptLibraryPanel?.classList.contains('is-open')) return true;
    if (guardWriteBusy()) return false;
    const discardChanges = state.workspace === 'blocks' && hasUnsavedBlockChanges();
    if (discardChanges && !confirmBlockDiscard()) return false;
    if (state.workspace === 'templates' && state.ruleDraft && !confirmRuleDiscard()) return false;
    if (state.workspace === 'colors' && state.colorDraft && !confirmColorDraftDiscard()) return false;
    if (discardChanges || (state.workspace === 'blocks' && state.extractor.open)) discardBlockDraft();
    if (state.workspace === 'templates' && state.ruleDraft) discardRuleDraft();
    if (state.workspace === 'colors' && state.colorDraft) discardColorDraft();
    els.deskPromptLibraryPanel?.classList.remove('is-open'); els.deskPromptLibraryPanel?.setAttribute('aria-hidden', 'true');
    document.querySelector('.desk-rail__item[data-tool="prompts"]')?.setAttribute('aria-expanded', 'false');
    return true;
  }

  function bindEvents() {
    els.deskPromptLibraryCloseBtn?.addEventListener('click', close);
    els.deskPromptLibraryNewBtn?.addEventListener('click', startNew);
    els.deskPromptLibraryRefreshBtn?.addEventListener('click', async () => { if (guardWriteBusy()) return; setBusy(els.deskPromptLibraryRefreshBtn, true); try { await loadAll({ force: true }); notify('素材库已刷新。'); } catch (error) { reportError(error, '刷新失败'); } finally { setBusy(els.deskPromptLibraryRefreshBtn, false); } });
    els.deskPromptLibraryTabs?.addEventListener('click', event => switchWorkspace(event.target.closest('[data-prompt-workspace]')?.dataset.promptWorkspace));
    els.deskPromptLibraryTabs?.addEventListener('keydown', event => {
      const current = event.target.closest('[data-prompt-workspace]');
      if (!current || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const tabs = Array.from(els.deskPromptLibraryTabs.querySelectorAll('[data-prompt-workspace]'));
      const currentIndex = Math.max(0, tabs.indexOf(current));
      const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      const next = tabs[nextIndex];
      if (!next) return;
      event.preventDefault();
      switchWorkspace(next.dataset.promptWorkspace).then(changed => {
        requestAnimationFrame(() => (changed ? next : current).focus?.({ preventScroll: true }));
      });
    });
    els.deskPromptLibraryNav?.addEventListener('click', async event => {
      const category = event.target.closest('[data-prompt-category]')?.dataset.promptCategory;
      if (!category) return;
      if (state.workspace === 'colors' && state.colorDraft) { notify('请先保存或取消当前配色编辑。', 'warning'); return; }
      state.category[state.workspace] = category;
      renderNav();
      if (state.workspace !== 'inspiration') { reconcileColorSelection(); renderList(); renderEditor(); return; }
      if (state.inspirationSearchTimer) { window.clearTimeout(state.inspirationSearchTimer); state.inspirationSearchTimer = 0; }
      try { await loadInspiration({ force: true }); }
      catch (error) { reportError(error, '灵感库读取失败'); }
    });
    els.deskPromptLibrarySearchInput?.addEventListener('input', () => {
      if (state.workspace !== 'inspiration') { reconcileColorSelection(); renderList(); renderEditor(); return; }
      state.inspirationRequestId += 1;
      state.inspiration = [];
      state.inspirationTotal = 0;
      state.inspirationLoaded = false;
      state.inspirationLoading = true;
      state.inspirationLoadingMore = false;
      state.selected.inspiration = '';
      if (state.inspirationSearchTimer) window.clearTimeout(state.inspirationSearchTimer);
      renderList(); renderEditor();
      state.inspirationSearchTimer = window.setTimeout(async () => {
        state.inspirationSearchTimer = 0;
        try { await loadInspiration({ force: true }); }
        catch (error) { state.inspirationLoading = false; renderList(); reportError(error, '灵感库搜索失败'); }
      }, 220);
    });
    els.deskPromptLibraryFavoriteFilter?.addEventListener('click', () => { if (state.colorDraft) return; state.favoriteOnly = !state.favoriteOnly; reconcileColorSelection(); renderList(); renderEditor(); els.deskPromptLibraryFavoriteFilter.setAttribute('aria-pressed', state.favoriteOnly ? 'true' : 'false'); });
    els.deskPromptLibraryList?.addEventListener('click', async event => {
      if (event.target.closest('[data-prompt-load-more]')) {
        try { await loadInspiration({ append: true }); }
        catch (error) { reportError(error, '更多灵感读取失败'); }
        return;
      }
      const row = event.target.closest('[data-prompt-item-id]'); if (row) selectItem(row.dataset.promptItemId, !!event.target.closest('[data-prompt-row-action]'));
    });
    els.deskPromptLibraryEditor?.addEventListener('submit', event => {
      if (event.target.matches('[data-prompt-block-form]')) saveBlock(event);
      else if (event.target.matches('[data-rule-form]')) saveRuleDraft(event);
      else if (event.target.matches('[data-color-draft-form]')) saveColorDraft(event);
    });
    els.deskPromptLibraryEditor?.addEventListener('pointerdown', event => {
      const slider = event.target.closest('[data-bloom-lightness]');
      if (slider && state.colorBloomOpen) beginBloomLightnessDrag(event, slider);
    });
    els.deskPromptLibraryEditor?.addEventListener('click', async event => {
      try {
        const createMode = event.target.closest('[data-prompt-create-mode]')?.dataset.promptCreateMode;
        if (createMode) { switchCreateMode(createMode); return; }
        const colorValue = event.target.closest('[data-color-value]')?.dataset.colorValue;
        if (colorValue) { await copyText(colorValue, `已复制色值 ${safeColor(colorValue)}`); return; }
        const extractorAction = event.target.closest('[data-extractor-action]')?.dataset.extractorAction;
        if (extractorAction) {
          if (extractorAction === 'close') closeExtractor();
          else if (extractorAction === 'run') await runExtractor();
          else if (extractorAction === 'save') await saveExtractedBlocks();
          else if (extractorAction === 'back') { syncExtractor(); state.extractor.candidates = []; state.extractor.error = ''; renderExtractor(); }
          else if (extractorAction === 'toggle-all') { syncExtractor(); const allSelected = state.extractor.candidates.every(item => item.selected); state.extractor.candidates.forEach(item => { item.selected = !allSelected; }); renderExtractor(); }
          return;
        }
        const button = event.target.closest('[data-prompt-action]'); if (!button) return;
        const action = button.dataset.promptAction;
        const colorAnalysisLockedActions = new Set([
          'pick-color-analysis-file',
          'clear-color-analysis',
          'retry-color-analysis',
          'set-color-analysis-mode',
        ]);
        if (colorAnalysisSourceLocked() && colorAnalysisLockedActions.has(action)) return;
        if (action === 'toggle-color-analysis') toggleColorAnalysis();
        else if (action === 'pick-color-analysis-file') els.deskPromptLibraryEditor?.querySelector('[name="color_analysis_image"]')?.click?.();
        else if (action === 'clear-color-analysis') clearColorAnalysis();
        else if (action === 'retry-color-analysis') await runColorAnalysis();
        else if (action === 'set-color-analysis-mode') setColorAnalysisMode(button.dataset.colorAnalysisMode);
        else if (action === 'toggle-color-bloom') {
          state.colorBloomOpen = !state.colorBloomOpen;
          renderEditor();
          requestAnimationFrame(() => {
            const selector = state.colorBloomOpen ? '[data-bloom-petal-key][aria-pressed="true"]' : '[data-prompt-action="toggle-color-bloom"]';
            els.deskPromptLibraryEditor?.querySelector(selector)?.focus?.({ preventScroll: true });
          });
        }
        else if (action === 'select-color-bloom-petal') setColorDraftBaseColor(button.dataset.bloomColor);
        else if (action === 'toggle-block-favorite') { syncBlockDraftFromForm(); state.blockDraft.favorite = !state.blockDraft.favorite; renderEditor(); }
        else if (action === 'delete-block') await deleteBlock();
        else if (action === 'insert-block') insertBlock();
        else if (action === 'copy-block') await copyText(blockPayload().content);
        else if (action === 'edit-rule') startRuleDraft(currentItem());
        else if (action === 'extract-by-template') openExtractor('text', { primaryType: currentItem()?.primary_type || '', ruleId: itemId(currentItem()), splitRule: currentItem() });
        else if (action === 'add-rule-module') addRuleModule();
        else if (action === 'move-rule-module') moveRuleModule(button);
        else if (action === 'delete-rule-module') deleteRuleModule(button);
        else if (action === 'reset-rule-draft') resetRuleDraft();
        else if (action === 'cancel-rule-draft') { if (confirmRuleDiscard()) { discardRuleDraft(); renderEditor(); } }
        else if (action === 'delete-rule-draft') await deleteRuleDraft();
        else if (action === 'duplicate-color') startNewColor(currentItem(), true);
        else if (action === 'edit-color') startNewColor(currentItem(), false);
        else if (action === 'toggle-color-favorite') toggleColorFavorite();
        else if (action === 'insert-color') insertColor();
        else if (action === 'copy-color-prompt') await copyText(currentItem()?.prompt);
        else if (action === 'copy-color-values') await copyText((currentItem()?.colors || []).join(', '));
        else if (action === 'apply-color-industry') applyColorIndustry();
        else if (action === 'generate-color-draft') regenerateColorDraft();
        else if (action === 'cancel-color-draft') cancelColorDraft();
        else if (action === 'delete-color-draft') deleteColorDraft();
        else if (action === 'split-inspiration') openExtractor('text', { text: currentItem()?.prompt || '', primaryType: inferType(currentItem()), sourceTitle: currentItem()?.title || '' });
        else if (action === 'save-inspiration-block') await saveInspirationAsBlock();
        else if (action === 'copy-inspiration') await copyText(currentItem()?.prompt);
        else if (action === 'select-inspiration-image') {
          const imageIndex = Math.max(0, Number(button.dataset.imageIndex || 0));
          state.inspirationImageIndex[itemId(currentItem())] = imageIndex;
          renderEditor();
          requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector(`[data-prompt-action="select-inspiration-image"][data-image-index="${imageIndex}"]`)?.focus?.({ preventScroll: true }));
        }
        else if (action === 'open-source-image') window.open(sourceImage(currentItem()), '_blank', 'noopener');
      } catch (error) { reportError(error); }
    });
    els.deskPromptLibraryEditor?.addEventListener('change', event => {
      if (event.target.name === 'color_analysis_image') {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (colorAnalysisSourceLocked()) return;
        handleColorAnalysisFile(file, 'upload');
        return;
      }
      if (event.target.closest('[data-rule-form]')) {
        syncRuleDraftFromForm();
        if (['rule_module_enabled', 'rule_module_required'].includes(event.target.name)) renderEditor();
        return;
      }
      if (event.target.name === 'extract_image') handleExtractorFile(event.target.files?.[0]);
      if (event.target.name === 'candidate_selected') { syncExtractor(); renderExtractor(); }
      const draftIndex = event.target.dataset.colorDraftIndex;
      if (draftIndex !== undefined) {
        const form = event.target.closest('[data-color-draft-form]');
        const value = cleanText(event.target.value);
        if (!/^#[0-9a-f]{6}$/i.test(value)) { notify('请输入完整 HEX 色值，例如 #2563EB。', 'warning'); return; }
        const previousAutoDescription = draftDescription(state.colorDraft);
        const previousAutoPrompt = draftPrompt(state.colorDraft);
        const color = safeColor(value);
        const picker = form?.querySelector(`[name="color_picker_${draftIndex}"]`); const hex = form?.querySelector(`[name="color_hex_${draftIndex}"]`);
        if (picker) picker.value = color; if (hex) hex.value = color;
        const draft = syncColorDraftFromForm();
        if (Number(draftIndex) === 0) draft.base_color = color;
        if (draft.description === previousAutoDescription) draft.description = draftDescription(draft);
        if (draft.prompt === previousAutoPrompt) draft.prompt = draftPrompt(draft);
        renderEditor(); return;
      }
      if (event.target.name === 'color_base_picker' || event.target.name === 'color_base_hex') {
        const value = cleanText(event.target.value);
        if (!/^#[0-9a-f]{6}$/i.test(value)) { notify('请输入完整 HEX 基色，例如 #2563EB。', 'warning'); return; }
        setColorDraftBaseColor(value);
      }
    });
    els.deskPromptLibraryEditor?.addEventListener('input', event => {
      if (event.target.closest('[data-rule-form]')) { syncRuleDraftFromForm(); return; }
      if (!event.target.closest('[data-color-draft-form]')) return;
      if (event.target.dataset.colorDraftIndex !== undefined || ['color_base_picker', 'color_base_hex'].includes(event.target.name)) return;
      syncColorDraftFromForm();
    });
    els.deskPromptLibraryEditor?.addEventListener('dragover', event => {
      const promptDrop = event.target.closest('[data-prompt-image-drop]');
      const colorDrop = event.target.closest('[data-color-analysis-drop]');
      const drop = promptDrop || colorDrop;
      if (!drop) return;
      event.preventDefault();
      if (!(promptDrop ? state.extractor.busy : colorAnalysisSourceLocked())) drop.classList.add('is-dragging');
    });
    els.deskPromptLibraryEditor?.addEventListener('dragleave', event => event.target.closest('[data-prompt-image-drop], [data-color-analysis-drop]')?.classList.remove('is-dragging'));
    els.deskPromptLibraryEditor?.addEventListener('drop', event => {
      const promptDrop = event.target.closest('[data-prompt-image-drop]');
      const colorDrop = event.target.closest('[data-color-analysis-drop]');
      const drop = promptDrop || colorDrop;
      if (!drop) return;
      event.preventDefault();
      drop.classList.remove('is-dragging');
      if (promptDrop) { if (!state.extractor.busy) handleExtractorFile(event.dataTransfer?.files?.[0]); return; }
      if (!colorAnalysisSourceLocked()) handleColorAnalysisFile(event.dataTransfer?.files?.[0], 'upload');
    });
    els.deskPromptLibraryEditor?.addEventListener('paste', event => {
      if (colorAnalysisSourceLocked() || !state.colorAnalysis.open || !event.target.closest('[data-color-analysis]')) return;
      const file = Array.from(event.clipboardData?.items || []).find(item => item.kind === 'file' && /^image\//i.test(item.type || ''))?.getAsFile?.()
        || Array.from(event.clipboardData?.files || []).find(item => /^image\//i.test(item.type || ''));
      if (!file) return;
      event.preventDefault();
      handleColorAnalysisFile(file, 'clipboard');
    });
    els.deskPromptLibraryEditor?.addEventListener('keydown', event => {
      const bloomSlider = event.target.closest('[data-bloom-lightness]');
      if (bloomSlider && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const current = hexToHsl(state.colorDraft?.base_color || '#000000').l;
        const step = event.shiftKey ? 5 : 2;
        const next = event.key === 'Home' ? 96 : event.key === 'End' ? 4 : current + (['ArrowUp', 'ArrowRight'].includes(event.key) ? step : -step);
        setBloomLightness(next);
        return;
      }
      const colorDrop = event.target.closest('[data-color-analysis-drop]');
      if (colorDrop && !colorAnalysisSourceLocked() && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        els.deskPromptLibraryEditor?.querySelector('[name="color_analysis_image"]')?.click?.();
        return;
      }
      const drop = event.target.closest('[data-prompt-image-drop]');
      if (drop && !state.extractor.busy && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); drop.querySelector('[name="extract_image"]')?.click(); return; }
      const modeTab = event.target.closest('[data-prompt-create-mode]');
      if (!modeTab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const tabs = Array.from(els.deskPromptLibraryEditor.querySelectorAll('[data-prompt-create-mode]:not(:disabled)'));
      if (!tabs.length) return;
      const currentIndex = Math.max(0, tabs.indexOf(modeTab));
      const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      const nextMode = tabs[nextIndex]?.dataset.promptCreateMode;
      if (!nextMode) return;
      event.preventDefault();
      switchCreateMode(nextMode);
      requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector(`[data-prompt-create-mode="${nextMode}"]`)?.focus?.({ preventScroll: true }));
    });
    document.addEventListener('click', event => {
      if (!state.colorBloomOpen || event.target.closest('[data-bloom-picker]')) return;
      state.colorBloomOpen = false;
      if (state.workspace === 'colors' && state.colorDraft) renderEditor();
    });
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || !els.deskPromptLibraryPanel?.classList.contains('is-open') || window.DesktopPromptInsert?.isOpen?.()) return;
      if (state.colorBloomOpen) {
        state.colorBloomOpen = false;
        renderEditor();
        requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector('[data-prompt-action="toggle-color-bloom"]')?.focus?.({ preventScroll: true }));
        return;
      }
      if (state.workspace === 'colors' && state.colorDraft && state.colorAnalysis.open) {
        syncColorDraftFromForm();
        state.colorAnalysis.open = false;
        renderEditor();
        requestAnimationFrame(() => els.deskPromptLibraryEditor?.querySelector('[data-prompt-action="toggle-color-analysis"]')?.focus?.({ preventScroll: true }));
        return;
      }
      close();
    });
  }

  function init() { collectElements(); loadColorSchemes(); bindEvents(); render(); }
  window.DesktopPromptLibrary = {
    init,
    open,
    close,
    render,
    refresh: loadAll,
    getBlocks: () => state.blocks.slice(),
    getColorSchemes: () => state.colors.map(item => ({ ...item, colors: [...(item.colors || [])] })),
    colorPromptBlock,
    getModuleLabel: moduleLabel,
  };
})();
