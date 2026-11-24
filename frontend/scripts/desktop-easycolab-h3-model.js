// Independent EasyColab MiniMax-H3 node schema and connection contract. No transport or DOM.
(function () {
  const TYPES = Object.freeze(['easycolab_h3_image', 'easycolab_h3_video']);
  const DEFAULT_MODEL_ID = Object.freeze({
    easycolab_h3_image: 'minimax_h3_image',
    easycolab_h3_video: 'minimax_h3_10eros_max'
  });
  const MODEL_KINDS = Object.freeze({
    minimax_h3_image: 'image',
    minimax_h3_10eros_max: 'video',
    minimax_h3_sulphur3: 'video',
    minimax_h3: 'video'
  });
  const active = status => ['submitting', 'queued', 'processing', 'running'].includes(status);

  function modelKind(node) {
    const id = String(node?.modelId || '');
    if (MODEL_KINDS[id]) return MODEL_KINDS[id];
    return node?.type === 'easycolab_h3_image' ? 'image' : 'video';
  }

  function snapFrames(value) {
    const raw = Number(value);
    const clamped = Math.max(22, Math.min(362, Number.isFinite(raw) ? Math.round(raw) : 124));
    const k = Math.max(1, Math.min(21, Math.round((clamped - 5) / 17)));
    return 17 * k + 5;
  }

  function normalize(node) {
    if (!TYPES.includes(node?.type)) return node;
    node.width = 680;
    const isVideo = modelKind(node) === 'video';
    node.height = Math.max(isVideo ? 580 : 440, Number(node.height) || (isVideo ? 640 : 460));
    node.modelId = String(node.modelId || DEFAULT_MODEL_ID[node.type] || 'minimax_h3_10eros_max');
    node.parameters = node.parameters && typeof node.parameters === 'object' && !Array.isArray(node.parameters)
      ? node.parameters
      : {};
    node.telegramEnabled = node.telegramEnabled === true;
    node.jobId = /^easycolab_h3_[a-f0-9]{32}$/.test(node.jobId || '') ? node.jobId : '';
    node.resultJobId = String(node.resultJobId || '');
    node.status = String(node.status || 'idle');
    return node;
  }

  const targets = Object.freeze({
    text: TYPES,
    image: TYPES,
    image_group: TYPES,
    audio: TYPES,
    easycolab_h3_image: ['image', 'video'],
    easycolab_h3_video: ['image', 'video']
  });

  function policy(from, to) {
    if (!targets[from?.type]?.includes(to?.type)) return null;
    if (from.type === 'audio') {
      if (modelKind(to) !== 'video') {
        return { reject: '当前 EasyColab 图像模型不支持声纹音频输入，请切换为视频模型后再连线。' };
      }
      return { inputRole: 'audio', outputRole: 'audio', single: true, replaceAllInputs: false };
    }
    if (TYPES.includes(from.type)) {
      const outKind = modelKind(from);
      if (to.type !== outKind) {
        return {
          reject: outKind === 'video'
            ? '当前 EasyColab 视频模型仅可输出到视频节点。'
            : '当前 EasyColab 图像模型仅可输出到图片节点。'
        };
      }
      return { inputRole: outKind, outputRole: outKind, single: false, replaceAllInputs: true };
    }
    const role = from.type === 'text' ? 'prompt' : 'image';
    return {
      inputRole: role,
      outputRole: role,
      single: false,
      replaceAllInputs: false
    };
  }

  const ICON_IMAGE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m4 17 5-5 3 3 3-4 5 6"/></svg>';
  const ICON_VIDEO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 9 5 3-5 3z"/></svg>';

  const MENU_ITEMS = Object.freeze([
    {
      type: 'easycolab_h3_image',
      title: 'MiniMax H3 图像',
      subtitle: 'EasyColab · 4K / 可切全系 H3',
      icon: ICON_IMAGE
    },
    {
      type: 'easycolab_h3_video',
      title: 'MiniMax H3 视频',
      subtitle: 'EasyColab · 10Eros / Sulphur3 / H3',
      icon: ICON_VIDEO
    }
  ]);

  window.DesktopEasyColabH3Model = Object.freeze({
    TYPES,
    DEFAULT_MODEL_ID,
    MODEL_KINDS,
    MENU_ITEMS,
    ICON_IMAGE,
    ICON_VIDEO,
    modelKind,
    snapFrames,
    normalize,
    active,
    targets,
    policy
  });
})();
