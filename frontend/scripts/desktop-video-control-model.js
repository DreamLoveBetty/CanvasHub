// Pure video-control state/connection contract. Does not depend on image/music state.
(function () {
  const TYPE = 'video_control';
  const active = status => ['submitting', 'queued', 'running', 'cancelling'].includes(status);
  function normalize(node) {
    node.width = 720; node.height = 390;
    node.control = ['depth', 'pose', 'canny'].includes(node.control) ? node.control : 'depth';
    node.quality = node.quality === 'full' ? 'full' : 'fast';
    const integer = (key, fallback, lo, hi) => node[key] = Number.isInteger(node[key]) && node[key] >= lo && node[key] <= hi ? node[key] : fallback;
    integer('maxRes', 640, 256, 1280); integer('maxSeconds', 15, 1, 30);
    integer('cannyLow', 100, 0, 1000); integer('cannyHigh', 200, 0, 1000);
    node.poseHands = node.poseHands !== false; node.poseFace = node.poseFace === true; node.invert = node.invert === true;
    node.jobId = /^[a-f0-9]{32}$/.test(node.jobId || '') ? node.jobId : '';
    node.status = String(node.status || 'idle'); return node;
  }
  function request(node, assetId) {
    return { asset_id: assetId, control: node.control, quality: node.quality, max_res: node.maxRes, max_seconds: node.maxSeconds,
      canny_low: node.cannyLow, canny_high: node.cannyHigh, pose_hands: node.poseHands, pose_face: node.poseFace, invert: node.invert };
  }
  const targets = Object.freeze({ video: ['video_control'], video_control: ['video'] });
  function policy(from, to) {
    return targets[from?.type]?.includes(to?.type) ? { inputRole: 'video', outputRole: 'video', single: true, replaceAllInputs: to.type === 'video' } : null;
  }
  const labels = { idle:'就绪',submitting:'提交中',queued:'排队中',running:'处理中',cancelling:'停止中',succeeded:'已完成',failed:'失败',cancelled:'已停止',interrupted:'已中断' };
  const stageLabel = stage => ({prepare:'准备视频',read:'读取视频',plan:'准备处理',check:'检查运行条件',model:'加载模型',load:'加载模型',infer:'提取控制信息',write:'编码控制视频',save:'保存结果',done:'处理完成',warn:'处理提示'})[stage] || stage;
  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m5 16 5-6 4 5 3-3 3 4M8 4v3M16 4v3"/></svg>';
  window.DesktopVideoControlModel = Object.freeze({ TYPE, normalize, request, active, targets, policy, labels, stageLabel,
    menu: { type: TYPE, title:'视频控制', subtitle:'ReShot · 深度 / 姿态 / 边缘', icon: ICON }, ICON });
})();
