// Pose recognition job for one pose node: upload the connected photo or video, submit, poll, cancel.
// Owns only the job lifecycle; the canvas controller applies the result to node.scene.
(function () {
  const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'interrupted']);
  function create({api, maxPeople = 6, pollMs = 400}) {
    const jobs = new Map(); // nodeId -> {jobId, cancelled}
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
    // options.evidence: refine a video's arms and fingers with SAM 3D Body image evidence (slower).
    async function run(nodeId, reference, onStage = () => {}, options = {}) {
      if (jobs.has(nodeId)) throw new Error('该节点正在识别');
      const job = {jobId: '', cancelled: false};
      jobs.set(nodeId, job);
      try {
        const video = reference.kind === 'video';
        onStage(video ? '读取视频' : '读取图片');
        const blob = await api.capture.mediaBlob(reference.url);
        if (job.cancelled) return null;
        onStage(video ? '上传视频' : '上传图片');
        const asset = await api.capture.upload(blob, reference.name || (video ? 'video' : 'photo'), video ? 'video' : 'image');
        if (job.cancelled) return null;
        const submitted = await api.capture.submit({asset_id: asset.asset_id, max_people: maxPeople,
          ...(video ? {evidence: options.evidence !== false} : {})});
        job.jobId = submitted.id;
        if (job.cancelled) { await api.capture.cancel(job.jobId).catch(() => {}); return null; }
        for (;;) {
          const current = await api.capture.job(job.jobId);
          onStage(current.stage || '识别中');
          if (TERMINAL.has(current.status)) {
            if (current.status === 'succeeded') return current.result_url && !current.result ? {...current, result: await api.capture.result(current.id)} : current;
            if (current.status === 'cancelled' || job.cancelled) return null;
            throw new Error(current.error || current.stage || '识别失败');
          }
          await wait(pollMs);
        }
      } finally {
        jobs.delete(nodeId);
      }
    }
    function cancel(nodeId) {
      const job = jobs.get(nodeId);
      if (!job) return;
      job.cancelled = true;
      if (job.jobId) api.capture.cancel(job.jobId).catch(() => {});
    }
    return Object.freeze({run, cancel, active: nodeId => jobs.has(nodeId)});
  }
  window.DesktopPoseCapture = Object.freeze({create});
})();
