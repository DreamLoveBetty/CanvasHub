// Independent 绘栾 node schema and connection contract. No transport or DOM.
(function () {
  const TYPES = Object.freeze(['cyimg_image', 'cyimg_video']);
  const active = status => ['submitting', 'queued', 'processing', 'running'].includes(status);
  function normalize(node) {
    if (!TYPES.includes(node.type)) return node;
    node.width = 650;
    node.height = node.type === 'cyimg_video' ? 500 : 410;
    node.modelId = String(node.modelId || '');
    node.parameters = node.parameters && typeof node.parameters === 'object' && !Array.isArray(node.parameters) ? node.parameters : {};
    node.telegramEnabled = node.telegramEnabled === true;
    node.jobId = /^cyimg_[a-f0-9]{32}$/.test(node.jobId || '') ? node.jobId : '';
    node.resultJobId = String(node.resultJobId || '');
    node.status = String(node.status || 'idle');
    return node;
  }
  const targets = Object.freeze({
    text: TYPES, image: TYPES, image_group: TYPES,
    video: ['cyimg_video'], audio: ['cyimg_video'],
    cyimg_image: ['image'], cyimg_video: ['video']
  });
  function policy(from, to) {
    if (!targets[from?.type]?.includes(to?.type)) return null;
    const role = from.type === 'text' ? 'prompt' : from.type === 'image' || from.type === 'image_group' ? 'image'
      : from.type === 'audio' ? 'audio' : 'video';
    return { inputRole: role, outputRole: role, single: !['image', 'image_group'].includes(from.type),
      replaceAllInputs: to.type === 'image' || to.type === 'video' };
  }
  const ICON_IMAGE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8" cy="9" r="1.5"/><path d="m4 17 5-5 3 3 3-4 5 6"/></svg>';
  const ICON_VIDEO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 9 5 3-5 3z"/></svg>';
  const MENU_ITEMS = Object.freeze([
    { type:'cyimg_image', title:'绘栾图像', subtitle:'在线模型 · 生图 / 参考图', icon:ICON_IMAGE },
    { type:'cyimg_video', title:'绘栾视频', subtitle:'在线模型 · 文生 / 图生视频', icon:ICON_VIDEO }
  ]);
  window.DesktopCyimgModel = Object.freeze({ TYPES, MENU_ITEMS, ICON_IMAGE, ICON_VIDEO, normalize, active, targets, policy });
})();
