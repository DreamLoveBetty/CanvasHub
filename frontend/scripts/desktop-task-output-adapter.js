// Adapter for existing image/Comfy/upscale/batch outputs. Receipts and pollers stay owned
// by their controllers. Capture identity before awaiting; never write into a new workflow.
(function () {
  function create({ defaultResultNodeId = 'input', getState, isInFlight, api, applyTask, applyBatch, stopTaskPolling, stopBatchPolling, cancelVideo }) {
    function listCancelable() {
      const state = getState(), outputs = state.outputs || {}, nodes = state.canvas?.nodes || {};
      const entries = [], groups = new Map();
      const add = (kind, id, nodeId, output) => {
        const key = kind + ':' + id;
        if (!groups.has(key)) groups.set(key, {kind, id, targets: []});
        const targets = groups.get(key).targets;
        if (!targets.some(t => t.nodeId === nodeId)) targets.push({nodeId, output, node: nodes[nodeId]});
      };
      Object.entries(outputs).forEach(([nodeId, output]) => {
        if (output?.taskId && isInFlight(output.status)) add('task', output.taskId, nodeId, output);
        if (output?.batchId && !['completed','missing'].includes(String(output.batchStatus || ''))) add('batch', output.batchId, nodeId, output);
      });
      if (state.selectedTaskId && isInFlight(state.output?.status)) add('task', state.selectedTaskId, defaultResultNodeId, state.output);
      for (const [key, {kind, id, targets}] of groups) {
        const current = t => {
          const now = getState();
          const output = now.outputs?.[t.nodeId] || (t.nodeId === defaultResultNodeId ? now.output : null);
          return now.outputs === outputs && output === t.output && now.canvas?.nodes?.[t.nodeId] === t.node
            && (kind === 'batch' ? output.batchId === id : (output.taskId || now.selectedTaskId) === id);
        };
        entries.push({key, cancel: async () => {
          const active = targets.filter(current); if (!active.length) return;
          const video = kind === 'task' && active.find(t => t.node?.type === 'video_inference');
          if (video) return cancelVideo(video.nodeId);
          const receipt = kind === 'batch' ? await api().controlBatch(id, 'cancel') : await api().cancelTask(id);
          for (const target of targets.filter(current)) {
            if (kind === 'batch') { applyBatch(receipt, target.nodeId); stopBatchPolling(target.nodeId); }
            else { applyTask({...receipt, task_id: id}, target.nodeId); stopTaskPolling(target.nodeId); }
          }
          return receipt;
        }});
      }
      return entries;
    }
    return Object.freeze({listCancelable});
  }
  window.DesktopTaskOutputAdapter = Object.freeze({create});
})();
