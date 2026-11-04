// ComfyUI video I/O on the canvas: video nodes feed Comfy video workflows, and Comfy video
// results publish into video nodes. Submission and polling stay in the shared generation flow;
// this controller owns only the video edges, the connected-video inputs and result publication.
(function () {
  const targets = Object.freeze({comfy: Object.freeze(['video']), video: Object.freeze(['comfy'])});
  const MIME_TYPES = Object.freeze({mp4: 'video/mp4', m4v: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm'});

  function policy(from, to) {
    if (from?.type === 'comfy' && to?.type === 'video') {
      return {inputRole: 'video', outputRole: 'video', single: true, replaceAllInputs: true};
    }
    if (from?.type === 'video' && to?.type === 'comfy') return {inputRole: 'video', outputRole: 'video'};
    return null;
  }

  function fileName(path) {
    const raw = String(path || '').split('?')[0].split('/').pop() || '';
    try { return decodeURIComponent(raw); } catch (_error) { return raw; }
  }

  function create({getCanvas, getNodeState, addNode, connectNodes, refreshVideoNode, refreshComfyNode,
    getOutput, saveState, showMessage}) {
    let publishing = false;
    const edges = () => getCanvas().edges || [];
    const incomingVideos = comfyId => edges().filter(edge => edge.to === comfyId)
      .map(edge => getNodeState(edge.from)).filter(node => node?.type === 'video');

    function connectedVideoReferences(comfyId) {
      return incomingVideos(comfyId).filter(node => String(node.mediaUrl || '').trim())
        .map(node => ({nodeId: node.id, url: String(node.mediaUrl).trim(), name: node.mediaName || '视频'}));
    }

    function position(node, index) {
      const x = node.x + (node.width || 320) + 60;
      let y = node.y + index * 300;
      const nodes = Object.values(getCanvas().nodes || {});
      for (let pass = 0; pass <= nodes.length; pass++) {
        const hits = nodes.filter(n => x < n.x + n.width + 20 && x + 400 + 20 > n.x && y < n.y + n.height + 20 && y + 260 + 20 > n.y);
        if (!hits.length) break;
        y = Math.max(...hits.map(n => n.y + n.height)) + 40;
      }
      return {x: x + 200, y: y + 130};
    }

    // Returns how many video nodes changed. Repeated polls of the same task are no-ops.
    function publish(comfyId, output, onlyTargetId = '') {
      const comfy = getNodeState(comfyId);
      const paths = Array.isArray(output?.videoPaths) ? output.videoPaths.filter(Boolean) : [];
      if (publishing || comfy?.type !== 'comfy' || !paths.length) return 0;
      let videoNodes = edges().filter(edge => edge.from === comfyId).map(edge => getNodeState(edge.to))
        .filter(node => node?.type === 'video');
      if (onlyTargetId) videoNodes = videoNodes.filter(node => node.id === onlyTargetId);
      if (!videoNodes.length) {
        if (onlyTargetId) return 0;
        publishing = true;
        try {
          videoNodes = paths.map((_path, index) => {
            const id = addNode('video', position(comfy, index));
            connectNodes(comfyId, id, {quiet: true});
            return getNodeState(id);
          }).filter(Boolean);
        } finally { publishing = false; }
      }
      const meta = output.videoMetadata || {};
      let changed = 0;
      videoNodes.slice(0, paths.length).forEach((node, index) => {
        const url = paths[index];
        if (node.mediaUrl === url && node.sourceTaskId === output.taskId) return;
        const name = fileName(url);
        Object.assign(node, {mediaUrl: url, mediaName: name, status: 'succeeded', sourceTaskId: output.taskId || '',
          mimeType: MIME_TYPES[name.split('.').pop().toLowerCase()] || 'video/mp4', fileSize: 0,
          mediaWidth: Number(meta.width || 0), mediaHeight: Number(meta.height || 0),
          durationSeconds: Number(meta.duration_seconds || 0), fps: Number(meta.fps || 0)});
        refreshVideoNode(node.id);
        changed += 1;
      });
      if (changed) saveState();
      return changed;
    }

    function changed(fromId, toId) {
      const from = getNodeState(fromId), to = getNodeState(toId);
      if (from?.type === 'video' && to?.type === 'comfy') {
        refreshComfyNode(toId);
        showMessage('视频已接入 Comfy 工作流节点。');
      } else if (from?.type === 'comfy' && to?.type === 'video') {
        publish(fromId, getOutput(fromId), toId);
      }
    }

    return Object.freeze({
      connectedVideoReferences,
      connectedVideoCount: comfyId => incomingVideos(comfyId).length,
      publish,
      connections: Object.freeze({targets, policy, changed, removed: () => {}}),
    });
  }

  window.DesktopCanvasComfyVideo = Object.freeze({create, targets, policy});
})();
