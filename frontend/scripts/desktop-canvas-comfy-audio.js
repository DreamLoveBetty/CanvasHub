// ComfyUI audio inputs on the canvas: audio nodes feed `[参考音频N]` slots of tagged Comfy
// workflows. This controller owns only the audio -> comfy edge and the connected-audio references;
// slot mapping lives in desktop-canvas-comfy-inputs.js and the upload in desktop-api.js.
(function () {
  const targets = Object.freeze({audio: Object.freeze(['comfy'])});

  function policy(from, to) {
    if (from?.type === 'audio' && to?.type === 'comfy') return {inputRole: 'audio', outputRole: 'audio'};
    return null;
  }

  function create({getCanvas, getNodeState, refreshComfyNode, showMessage}) {
    const incomingAudios = comfyId => (getCanvas().edges || []).filter(edge => edge.to === comfyId)
      .map(edge => getNodeState(edge.from)).filter(node => node?.type === 'audio');

    // Local imports live in the audio asset store (audioAssetId); results and archive clips have a URL.
    function connectedAudioReferences(comfyId) {
      return incomingAudios(comfyId).filter(node => node.audioAssetId || String(node.mediaUrl || '').trim())
        .map(node => ({nodeId: node.id, assetId: node.audioAssetId || '', url: String(node.mediaUrl || '').trim(),
          name: node.mediaName || '音频'}));
    }

    function changed(fromId, toId) {
      if (getNodeState(fromId)?.type !== 'audio' || getNodeState(toId)?.type !== 'comfy') return;
      refreshComfyNode(toId);
      showMessage('音频已接入 Comfy 工作流节点。');
    }

    return Object.freeze({
      connectedAudioReferences,
      connectedAudioCount: comfyId => incomingAudios(comfyId).length,
      connections: Object.freeze({targets, policy, changed, removed: () => {}}),
    });
  }

  window.DesktopCanvasComfyAudio = Object.freeze({create, targets, policy});
})();
