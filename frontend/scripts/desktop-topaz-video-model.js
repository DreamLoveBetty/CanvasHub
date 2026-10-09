// Topaz Video owns a video enhancement node, separate from image Topaz and ReShot.
(function () {
  const pipeline = window.DesktopTopazVideoPipeline;
  const TYPE = 'topaz_video';
  const MODELS = Object.freeze([
    ['precise-26', 'Starlight Precise 2.6'],
    ['precise-25', 'Starlight Precise 2.5'],
    ['mini', 'Starlight Mini'],
    ['proteus-v4', 'Proteus v4'],
    ['nyx-v3', 'Nyx v3'],
    ['theia-v4', 'Theia v4'],
    ['iris', 'Iris Medium Quality v2'],
    ['rhea', 'Rhea v1'],
    ['artemis', 'Artemis High Quality v12'],
    ['gaia', 'Gaia High Quality v5'],
    ['gaia-animation', 'Gaia Animation v1'],
  ]);
  const PRESETS = Object.freeze([
    {id: 'recommended', label: '模型默认'},
    {id: 'custom', label: '自定义参数'},
  ]);
  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4zM3 20h18"/></svg>';
  const active = status => ['submitting', 'queued', 'running', 'cancelling'].includes(status);
  const labels = Object.freeze({
    idle: '就绪', submitting: '提交中', queued: '排队中', running: '处理中',
    cancelling: '停止中', succeeded: '已完成', failed: '失败', cancelled: '已停止', interrupted: '已中断',
  });
  const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const aligned = (value, field) => {
    const step = Number(field?.step);
    if (!(step > 0)) return true;
    const units = (Number(value) - Number(field.min)) / step;
    return Math.abs(units - Math.round(units)) < 1e-8;
  };
  function normalize(node) {
    pipeline.normalize(node);
    node.width = 680;
    node.height = 330;
    node.model = String(node.model || 'precise-26');
    node.scale = Number.isFinite(Number(node.scale)) ? Number(node.scale) : 2;
    node.presetId = PRESETS.some(item => item.id === node.presetId) ? node.presetId : 'recommended';
    node.maxSeconds = Number.isInteger(Number(node.maxSeconds)) ? Math.max(0, Math.min(600, Number(node.maxSeconds))) : 0;
    node.modelParams = node.modelParams && typeof node.modelParams === 'object' && !Array.isArray(node.modelParams) ? node.modelParams : {};
    node.jobId = /^[a-f0-9]{32}$/.test(node.jobId || '') ? node.jobId : '';
    node.resultJobId = String(node.resultJobId || '');
    node.previewJobId = /^[a-f0-9]{32}$/.test(node.previewJobId || '') ? node.previewJobId : '';
    node.previewStatus = String(node.previewStatus || 'idle');
    node.previewStartSeconds = Math.max(0, finite(node.previewStartSeconds));
    node.previewDurationSeconds = Math.max(0, Math.min(600, finite(node.previewDurationSeconds)));
    node.previewSourceKey = String(node.previewSourceKey || '');
    node.exportSourceKey = String(node.exportSourceKey || '');
    node.status = String(node.status || 'idle');
    return node;
  }
  function catalogModels(payload) {
    const items = Array.isArray(payload?.models) ? payload.models : [];
    return items.filter(item => item && /^[a-z0-9-]+$/.test(String(item.id || '')))
      .map(item => ({
        id: String(item.id), label: String(item.label || item.id), family: String(item.family || ''),
        available: item.available === true, verified: item.verified === true, reason: String(item.reason || ''),
        scales: (Array.isArray(item.scales) ? item.scales : []).map(Number).filter(value => Number.isInteger(value) && value >= 1 && value <= 8),
        parameters: (Array.isArray(item.parameters) ? item.parameters : []).filter(p => p && /^[a-z][a-z0-9_]*$/.test(String(p.key || '')) && p.type === 'number')
          .map(p => ({key: String(p.key), label: String(p.label || p.key), min: Number(p.min), max: Number(p.max),
            step: Number(p.step), default: Number(p.default)}))
          .filter(p => Number.isFinite(p.min) && Number.isFinite(p.max) && p.max >= p.min && Number.isFinite(p.default)),
      }));
  }
  function syncForModel(node, meta, {reset = false} = {}) {
    normalize(node);
    if (!meta) return node;
    if (!meta.scales.includes(node.scale)) node.scale = meta.scales[0] || 1;
    for (const field of meta.parameters) {
      const value = Number(node.modelParams[field.key]);
      node.modelParams[field.key] = !reset && Number.isFinite(value) && value >= field.min && value <= field.max && aligned(value, field)
        ? value : field.default;
    }
    return node;
  }
  function applyPreset(node, meta, presetId = 'recommended') {
    node.presetId = PRESETS.some(item => item.id === presetId) ? presetId : 'recommended';
    if (node.presetId === 'recommended') syncForModel(node, meta, {reset: true});
    else syncForModel(node, meta);
    return node;
  }
  function request(node, assetId, meta, overrides = {}, runtime = null) {
    if (!meta || meta.id !== node.model || (node.enhancementEnabled !== false && (!meta.available || !meta.scales.includes(node.scale))))
      throw new Error(meta?.reason || '所选视频模型尚不可在本机运行');
    if (!assetId) throw new Error('请先连接或导入视频');
    const taskKind = overrides.taskKind === 'preview' ? 'preview' : 'export';
    const startSeconds = finite(overrides.startSeconds, 0);
    const maxSeconds = overrides.maxSeconds === undefined ? node.maxSeconds : finite(overrides.maxSeconds, 0);
    if (startSeconds < 0 || startSeconds > 86400) throw new Error('选区起点无效');
    if (!Number.isFinite(maxSeconds) || maxSeconds < 0 || maxSeconds > 600)
      throw new Error('处理时长无效');
    if (taskKind === 'preview' && maxSeconds <= 0) throw new Error('请先在时间轴选择预览区间');
    const body = {asset_id: assetId, model: node.model, scale: node.enhancementEnabled === false ? 1 : node.scale,
      task_kind: taskKind, start_seconds: startSeconds, max_seconds: maxSeconds};
    for (const field of meta.parameters) {
      const value = Number(node.modelParams[field.key]);
      if (!Number.isFinite(value) || value < field.min || value > field.max || !aligned(value, field))
        throw new Error(field.label + '超出范围或不符合有效步进');
      body[field.key] = value;
    }
    return {...body, ...pipeline.request(node, runtime)};
  }
  function configurationKey(spec) {
    const {asset_id, task_kind, start_seconds, max_seconds, ...config} = spec || {};
    const canonical = value => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
    return JSON.stringify(canonical({...config, enhancement: config.enhancement !== false,
      filters: config.filters || {}, encoding: {codec: 'h264', bitrate_mbps: 0, audio: 'aac', ...config.encoding}}));
  }
  const targets = Object.freeze({video: ['topaz_video'], topaz_video: ['video']});
  function policy(from, to) {
    return targets[from?.type]?.includes(to?.type)
      ? {inputRole: 'video', outputRole: 'video', single: true, replaceAllInputs: to.type === 'video'}
      : null;
  }
  window.DesktopTopazVideoModel = Object.freeze({
    TYPE, MODELS, PRESETS, ICON, active, labels, normalize, catalogModels, syncForModel, applyPreset, request, configurationKey, targets, policy,
    menu: {type: TYPE, title: 'Topaz 视频增强', subtitle: '本地修复与高清放大', icon: ICON},
  });
})();
