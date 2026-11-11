// Video-edit controller for canvas video nodes: first/last frame, the frame picker, scene
// candidates, audio separation and the「配方」entry on compose outputs (the rebuild itself is
// desktop-canvas-video-compose-recipe.js). It owns the action dock under a video node, the jobs it
// starts and where their outputs land: frames become image nodes and the track an audio node,
// each connected from the video. Transport is desktop-video-edit-api.js, the modal is
// desktop-video-frames.js; desktop-canvas.js only wires dependencies and dispatches clicks.
(function () {
  const targets = Object.freeze({video: Object.freeze(['image', 'audio'])});
  const POLL_MS = 600;
  const GAP = 28;

  // A video feeds one picture into an image node and one track into an audio node.
  function policy(from, to) {
    if (from?.type !== 'video') return null;
    if (to?.type === 'image') return {outputRole: 'frame', replaceAllInputs: true};
    if (to?.type === 'audio') return {outputRole: 'audio', replaceAllInputs: true};
    return null;
  }

  const LABELS = Object.freeze({first: '抽首帧', last: '抽尾帧', pick: '抽帧', audio: '分离音频', scenes: '侦测场景'});

  function create({api, picker, getCanvas, getNodeState, getNodeElement, addNode, connectNodes, insertImageNode,
    getImageNodeSize, setAudioResult, fetchBlob = null, progressView, reportStatus, showMessage, escapeHtml,
    audioSize = {width: 800, height: 360}, recipe = null}) {
    const sessions = new Map(); // nodeId -> {kind, label, receipt, progressRoot}
    const probes = new Map();   // source URL -> Promise<probe>

    const sourceOf = node => (node?.type === 'video' ? api.sourceUrl(node.mediaUrl || node.videoUrl || '') : '');
    const nameOf = node => String(node?.mediaName || '').trim() || String(node?.mediaUrl || '').split(/[?#]/, 1)[0].split('/').pop() || '视频';

    function actionsHtml(node) {
      const busy = sessions.has(node.id) ? ' disabled' : '';
      const probe = probes.get(sourceOf(node))?.value;
      const noAudio = Boolean(probe && !probe.hasAudio);
      return `<div class="desk-video-edit__actions" role="group" aria-label="视频剪辑">
          <button type="button" data-video-edit="first" title="抽第一帧为图片节点"${busy}>首帧</button>
          <button type="button" data-video-edit="last" title="抽最后一帧为图片节点（接下一段图生视频）"${busy}>尾帧</button>
          <button type="button" class="is-accent" data-video-edit="pick" title="打开抽帧工作台"${busy}>抽帧…</button>
          <button type="button" data-video-edit="audio" title="${noAudio ? '这段视频没有音轨' : '把音轨分离成音频节点，原视频不变'}"${busy || (noAudio ? ' disabled' : '')}>${noAudio ? '无音轨' : '♪ 分离音频'}</button>
          ${recipe?.isOutput(node.mediaUrl) ? `<button type="button" data-video-edit="recipe" title="从配方重开：重建片段、配乐与合成节点，改设定后可重新出片"${busy}>配方</button>` : ''}
        </div>`;
    }

    // Rendered inside the video node by its template; the progress float sits under the node like other domains'.
    function dockHtml(node) {
      if (!sourceOf(node)) return '';
      return `<div class="desk-video-edit${sessions.has(node.id) ? ' is-busy' : ''}" data-video-edit-dock data-node-drag-ignore>${actionsHtml(node)}</div>
        <div class="desk-progress-float desk-video-edit__progress" data-video-edit-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar data-video-edit-bar></span><strong class="desk-progress-float__percent" data-video-edit-percent></strong></div><span class="desk-progress-float__stage" data-video-edit-stage></span></div></div>`;
    }

    // Repaint only the dock and progress: re-rendering the whole node would reload its <video>.
    function paint(nodeId) {
      const element = getNodeElement(nodeId);
      const node = getNodeState(nodeId);
      if (!element || !node) return;
      let dock = element.querySelector('[data-video-edit-dock]');
      if (!dock) {
        const html = dockHtml(node);
        if (!html) return;
        element.insertAdjacentHTML('beforeend', html);
        dock = element.querySelector('[data-video-edit-dock]');
      } else {
        dock.innerHTML = actionsHtml(node);
      }
      const session = sessions.get(nodeId);
      dock.classList.toggle('is-busy', Boolean(session));
      const progress = element.querySelector('[data-video-edit-progress]');
      const job = session?.receipt;
      const amount = Number(job?.progress);
      const known = job?.progress != null && Number.isFinite(amount);
      const title = job?.stage && job.stage !== '处理中' ? job.stage : (session?.label || '');
      progress.hidden = !session;
      progress.classList.toggle('is-visible', Boolean(session));
      progress.classList.toggle('is-indeterminate', !known);
      progress.querySelector('[data-video-edit-bar]').style.width = known ? Math.max(0, Math.min(100, amount)) + '%' : '30%';
      progress.querySelector('[data-video-edit-percent]').textContent = known ? Math.round(amount) + '%' : '处理中';
      progress.querySelector('[data-video-edit-stage]').textContent = title;
      progressView?.update(progress, {visible: Boolean(session), running: Boolean(session), taskId: job?.task_id || '',
        percent: known ? amount : null, title: title || '处理中', detail: '视频剪辑 · ' + (session?.label || ''),
        startedAt: job?.raw?.created_at ? job.raw.created_at * 1000 : 0}, element);
    }

    function probe(node) {
      const source = sourceOf(node);
      if (!source) return Promise.reject(new Error('该视频来源暂不支持剪辑，请先导入或保存到作品库'));
      let entry = probes.get(source);
      if (!entry) {
        entry = {promise: api.probe(source).then(value => { entry.value = value; return value; })
          .catch(error => { probes.delete(source); throw error; })};
        probes.set(source, entry);
      }
      return entry.promise;
    }

    // Learn whether the clip has audio before the user reaches the dock; cheap and cached per source.
    function warm(nodeId) {
      const node = getNodeState(nodeId);
      const source = sourceOf(node);
      if (!source || probes.get(source)?.value) return;
      probe(node).then(() => paint(nodeId)).catch(() => {});
    }

    function feedback(nodeId, session, status, message, tone = 'info') {
      const job = session.receipt;
      reportStatus({message: `${session.label} · ${message}`, tone,
        task: {task_id: job?.task_id || '', node_id: nodeId, node_title: `视频 · ${nameOf(getNodeState(nodeId))}`,
          operation_label: session.label, status: status === 'running' ? 'processing' : status === 'cancelled' ? 'canceled' : status,
          status_label: message, provider_route: 'video_edit_local', detail_title: '视频剪辑日志',
          stage: message, progress_text: message,
          raw_detail: JSON.stringify({kind: session.kind, status, stage: job?.stage || '', error: job?.error || ''}, null, 2)}});
    }

    async function run(nodeId, kind, extra, onProgress) {
      const node = getNodeState(nodeId);
      if (!node || node.type !== 'video') throw new Error('视频节点不存在');
      if (sessions.has(nodeId)) throw new Error('这段视频正在处理，请稍候');
      const source = sourceOf(node);
      if (!source) throw new Error('该视频来源暂不支持剪辑，请先导入或保存到作品库');
      const session = {kind, label: LABELS[extra.action || kind] || '视频剪辑', receipt: null, cancelled: false};
      sessions.set(nodeId, session);
      paint(nodeId);
      try {
        session.receipt = await api.submit(kind, source, {sourceName: nameOf(node), frames: extra.frames});
        feedback(nodeId, session, 'queued', '已提交');
        while (['queued', 'running', 'submitting'].includes(session.receipt.status)) {
          await new Promise(resolve => window.setTimeout(resolve, POLL_MS));
          session.receipt = await api.progress(session.receipt.task_id);
          onProgress?.(session.receipt.progress);
          paint(nodeId);
        }
        const receipt = session.receipt;
        if (receipt.status !== 'succeeded') {
          const message = receipt.status === 'cancelled' ? '已取消' : receipt.error || '处理失败';
          feedback(nodeId, session, receipt.status, message, receipt.status === 'cancelled' ? 'info' : 'error');
          throw new Error(message);
        }
        feedback(nodeId, session, 'succeeded', '完成', 'success');
        return receipt.raw.result;
      } finally {
        sessions.delete(nodeId);
        paint(nodeId);
      }
    }

    // Top-left corner of the first free area to the right of `source`, scanning down, then right.
    function freeSlot(source, width, height) {
      const nodes = Object.values(getCanvas().nodes || {});
      const startX = Number(source.x) + Number(source.width) + 80;
      let x = startX, y = Number(source.y);
      for (let pass = 0; pass < 400; pass += 1) {
        const hit = nodes.find(n => n.id !== source.id && x < n.x + n.width + GAP && x + width + GAP > n.x
          && y < n.y + n.height + GAP && y + height + GAP > n.y);
        if (!hit) return {x, y};
        y = hit.y + hit.height + GAP;
        if (y > Number(source.y) + 1800) { y = Number(source.y); x += width + GAP; }
      }
      return {x, y};
    }

    function placeFrames(nodeId, frames) {
      const source = getNodeState(nodeId);
      if (!source) return [];
      return frames.map((item, index) => {
        const meta = {width: Number(item.width) || source.mediaWidth || 1, height: Number(item.height) || source.mediaHeight || 1};
        const size = getImageNodeSize(meta);
        const slot = freeSlot(source, size.width, size.height);
        const imageId = insertImageNode({
          imageUrl: item.url, imageName: item.filename, mimeType: 'image/png', file: item.filename,
          title: `${nameOf(source)} · 第 ${Number(item.frame) + 1} 帧`, provider: 'video_frame', source: 'video-frame', meta,
        }, {x: slot.x + size.width / 2, y: slot.y + size.height / 2}, {exactCenter: true, popIndex: index});
        connectNodes(nodeId, imageId, {quiet: true});
        return imageId;
      });
    }

    async function extractFrames(nodeId, frames, action) {
      const result = await run(nodeId, 'frames', {frames, action});
      if (!getNodeState(nodeId)) { showMessage('视频节点已删除，帧已存入作品库。'); return []; }
      const ids = placeFrames(nodeId, result.frames || []);
      showMessage(ids.length > 1 ? `已抽出 ${ids.length} 帧，存入作品库并生成图片节点。` : '已抽出该帧，存入作品库并生成图片节点。');
      return ids;
    }

    async function separateAudio(nodeId) {
      const result = await run(nodeId, 'extract_audio', {action: 'audio'});
      // Like music results: hand the audio node the bytes too, so it draws a local waveform.
      const blob = fetchBlob && Number(result.file_size) <= 100 * 1024 * 1024
        ? await fetchBlob(result.url).catch(() => null) : null;
      const source = getNodeState(nodeId);
      if (!source) { showMessage('视频节点已删除，音轨已存入音频库。'); return ''; }
      const slot = freeSlot(source, audioSize.width, audioSize.height);
      const audioId = addNode('audio', {x: slot.x + audioSize.width / 2, y: slot.y + audioSize.height / 2});
      connectNodes(nodeId, audioId, {quiet: true});
      await setAudioResult(audioId, {blob, url: result.url, name: result.title || result.name, mime_type: result.mime_type,
        file_size: result.file_size, duration_seconds: result.duration_seconds});
      showMessage(result.reused ? '已从音频库取回这段视频的音轨（原视频不变）。' : '已分离音轨，存入音频库并生成音频节点（原视频不变）。');
      return audioId;
    }

    function openPicker(nodeId) {
      const node = getNodeState(nodeId);
      const source = sourceOf(node);
      if (!source) throw new Error('该视频来源暂不支持剪辑，请先导入或保存到作品库');
      picker.open({source, name: nameOf(node),
        detectScenes: onProgress => run(nodeId, 'scenes', {action: 'scenes'}, onProgress),
        onExtract: frames => extractFrames(nodeId, frames, 'pick').catch(error => showMessage(error.message || '抽帧失败'))});
    }

    // Click dispatch from desktop-canvas.js. Returns true when the click was a dock action.
    function handleAction(button) {
      const element = button.closest('.desk-node--video[data-node-id]');
      if (!element || button.disabled) return Boolean(element);
      const nodeId = element.dataset.nodeId;
      const action = button.dataset.videoEdit;
      const fail = error => showMessage(error.message || '视频剪辑失败');
      if (action === 'first') extractFrames(nodeId, [0], 'first').catch(fail);
      else if (action === 'last') extractFrames(nodeId, [-1], 'last').catch(fail);
      else if (action === 'audio') separateAudio(nodeId).catch(fail);
      else if (action === 'pick') { try { openPicker(nodeId); } catch (error) { fail(error); } }
      else if (action === 'recipe' && recipe) recipe.reopen(nodeId).catch(fail);
      return true;
    }

    function getCancelableTasks() {
      const entries = [];
      sessions.forEach((session, nodeId) => {
        if (session.receipt?.task_id) entries.push({kind: 'video_edit', key: 'video_edit:' + nodeId,
          cancel: () => api.cancel(session.receipt.task_id)});
      });
      return entries;
    }

    return Object.freeze({
      dockHtml, paint, warm, handleAction, extractFrames, separateAudio, openPicker, getCancelableTasks,
      showStatus: () => {},
      connections: Object.freeze({targets, policy, changed: () => {}, removed: () => {}}),
    });
  }

  window.DesktopCanvasVideoEdit = Object.freeze({create, targets, policy});
})();
