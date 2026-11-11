// Reopen a rendered compose from its recipe: reads the `.json` beside an archived
// video_compose_*.mp4 (/api/video_edit/compose_recipe) and rebuilds the graph below that video
// node: one video node per clip, the music as an audio node, and a compose node holding the trims,
// levels and output settings with the archived file as its current result. Owns only this rebuild;
// compose node sessions, jobs and the workbench stay in desktop-canvas-video-compose.js.
(function () {
  const OUTPUT_NAME = /^video_compose_[\w.-]+\.mp4$/;
  const GAP = 40, BELOW = 160, COLUMNS = 4;

  const fileName = url => String(url || '').split(/[?#]/, 1)[0].split('/').pop();

  // A served compose output (the dock shows「配方」only for these).
  const isOutput = url => OUTPUT_NAME.test(fileName(url));

  function create({model, api, getNodeState, addNode, connectNodes, refreshVideoNode, setAudioResult, compose,
    videoSize = {width: 320, height: 470}, audioSize = {width: 800, height: 360}, selectNode = () => {}, showMessage}) {
    const pending = new Set();

    // Clips fill a grid under the archived video; music sits under the clips; compose to their right.
    // Video nodes take their clip's aspect once loaded, so each cell fits the long side either way.
    function layout(anchor, count) {
      const left = anchor.x, top = anchor.y + anchor.height + BELOW;
      const cell = Math.max(videoSize.width, videoSize.height) + GAP;
      const columns = Math.min(COLUMNS, Math.max(1, count));
      const rows = Math.ceil(count / columns);
      const at = (x, y) => ({x: x + cell / 2, y: y + cell / 2});
      return {
        clip: index => at(left + (index % columns) * cell, top + Math.floor(index / columns) * cell),
        music: {x: left + audioSize.width / 2, y: top + rows * cell + audioSize.height / 2},
        compose: {x: left + columns * cell + BELOW + model.WIDTH / 2, y: top + model.HEIGHT / 2},
      };
    }

    async function reopen(nodeId) {
      const anchor = getNodeState(nodeId);
      if (anchor?.type !== 'video' || !isOutput(anchor.mediaUrl)) throw new Error('这段视频不是合成成片，没有可重开的配方');
      if (pending.has(nodeId)) return null;
      pending.add(nodeId);
      try {
        const recipe = await api.compose.recipe(anchor.mediaUrl);
        if (getNodeState(nodeId) !== anchor) return null;
        const place = layout(anchor, recipe.clips.length);
        const clipIds = recipe.clips.map((clip, index) => {
          const id = addNode('video', place.clip(index));
          Object.assign(getNodeState(id), {mediaUrl: clip.sourceUrl, mediaName: clip.sourceName || fileName(clip.sourceUrl),
            mimeType: 'video/mp4', status: 'succeeded', fileSize: 0, mediaWidth: 0, mediaHeight: 0, durationSeconds: 0, fps: 0});
          refreshVideoNode(id);
          return id;
        });
        const composeId = addNode(model.TYPE, place.compose);
        // Connect first: each new edge re-syncs the clip list from the edges present so far,
        // which would drop trims set for clips not yet connected.
        clipIds.forEach(id => connectNodes(id, composeId, {quiet: true}));
        const node = getNodeState(composeId);
        Object.assign(node, {title: recipe.title || node.title, clipVolume: recipe.clipVolume, output: {...recipe.output},
          clips: recipe.clips.map((clip, index) => ({sourceId: clipIds[index], startFrame: clip.startFrame,
            endFrame: clip.endFrame, audio: clip.audio, speed: clip.speed, transition: {...clip.transition}}))});
        if (recipe.music) Object.assign(node.music, {volume: recipe.music.volume, fadeIn: recipe.music.fadeIn, fadeOut: recipe.music.fadeOut});
        if (recipe.subtitles) node.subtitles = recipe.subtitles;
        model.normalize(node);
        // Uploaded (local-only) music has no served URL to rebuild from; archive music does.
        let musicNote = recipe.music ? '' : '，无配乐';
        if (recipe.music?.sourceUrl) {
          const audioId = addNode('audio', place.music);
          await setAudioResult(audioId, {url: recipe.music.sourceUrl, name: recipe.music.sourceName || fileName(recipe.music.sourceUrl)});
          connectNodes(audioId, composeId, {quiet: true});
        } else if (recipe.music) {
          musicNote = '；配乐是当时临时上传的音频，请重新连接音频节点';
        }
        compose.adopt(composeId, recipe.result);
        selectNode(composeId);
        showMessage(`已从配方重建 ${clipIds.length} 段${musicNote}。改设定后按「重新合成」出新版。`);
        return composeId;
      } finally {
        pending.delete(nodeId);
      }
    }

    return Object.freeze({reopen, isOutput});
  }

  window.DesktopCanvasVideoComposeRecipe = Object.freeze({create, isOutput});
})();
