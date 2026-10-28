// Pose reference nodes on the canvas: mounting, node fields, the editor session, image and video exports
// and applying photo / video recognition results. A pose video is published to a connected video node. Owns export state; the editor (ES module, window.DesktopPoseEditor)
// edits node.scene in place and renders through the shared offscreen engine; recognition jobs live in
// desktop-pose-capture.js. Downstream nodes read node.output.artifactUrl.
(function () {
  function create({model, api, view, capture, getCanvas, getNodeState, getNodeElement, saveState, connectedImages, connectedVideos = () => [],
    addNode = null, connectNodes = null, refreshVideoNode = () => {}, showMessage, confirm}) {
    const sessions = new Map();
    let assets = null, assetsPromise = null, recognition = null;
    const live = s => sessions.get(s.id) === s && getNodeState(s.id) === s.node && getNodeElement(s.id) === s.el;
    const editor = () => window.DesktopPoseEditor || null;

    function paint(s) {
      if (!live(s)) return;
      view.paint(s.el, s.node, {busy: s.busy, assets, recognition, recognizing: s.recognizing, references: connectedImages(s.id).length,
        videos: connectedVideos(s.id).length,
        stage: s.stage, error: s.error, flash: s.flash});
    }
    function refreshAssets() {
      assetsPromise ||= Promise.all([
        api.status().then(payload => { assets = payload; })
          .catch(error => { assets = {ready: false, state: 'error', message: error.message || '人偶状态读取失败'}; }),
        api.capture.status().then(payload => { recognition = payload; })
          .catch(error => { recognition = {ready: false, state: 'error', message: error.message || '识别引擎状态读取失败'}; }),
      ]).finally(() => { assetsPromise = null; sessions.forEach(paint); });
      return assetsPromise;
    }
    async function recognize(s) {
      if (capture.active(s.id)) { capture.cancel(s.id); return; }
      // A connected video wins over images (images stay usable as camera-view references).
      const reference = connectedVideos(s.id)[0] || connectedImages(s.id)[0];
      if (!reference) { showMessage('请先把图片或视频节点连接到姿态参考节点'); return; }
      if (!recognition?.ready) { refreshAssets(); showMessage(recognition?.message || '姿态识别引擎尚未安装'); return; }
      if (reference.kind === 'video' && !recognition.modes?.video) { showMessage(recognition.video_message || '视频识别尚未就绪'); return; }
      if (model.hasCustomPose(s.node) && !confirm('识别结果会替换当前的角色和姿势，继续？')) return;
      s.recognizing = true; s.stage = '准备识别'; s.error = '';
      paint(s);
      try {
        const job = await capture.run(s.id, reference, stage => { s.stage = stage; paint(s); },
          {evidence: s.node.capture.evidence && recognition.modes?.evidence === true});
        if (!job || !live(s)) return;
        if (!job.people) { showMessage(reference.kind === 'video' ? '视频中没有识别到人物' : '照片中没有识别到人物'); return; }
        if (reference.kind === 'video') model.applyCaptureSequence(s.node, job.result, job.id);
        else model.applyCapture(s.node, job.result);
        changed(s);
        const sequence = s.node.scene.sequence;
        showMessage(sequence
          ? `已识别 ${s.node.scene.characters.length} 个人物、${sequence.frameCount} 帧${job.result.source?.truncated ? '（只识别前 30 秒）' : ''}。打开编辑器可播放与修正。`
          : `已识别 ${s.node.scene.characters.length} 个人物。打开编辑器可微调，机位视角可叠加原图对照。`);
      } catch (error) {
        s.error = error?.message || '识别失败';
        showMessage(s.error);
      } finally {
        s.recognizing = false; s.stage = '';
        paint(s);
      }
    }
    function changed(s) {
      if (!live(s)) return;
      view.renderFields(s.el, s.node);
      paint(s);
      saveState();
    }
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
    // A video frame as raw RGBA, deflated by the browser (fast and lossless; ffmpeg does the encoding).
    // Browser PNG / JPEG encoding took seconds per frame in embedded browsers.
    async function rawFrame(canvas) {
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      return new Response(new Blob([pixels]).stream().pipeThrough(new CompressionStream('deflate'))).blob();
    }
    // The pose video goes to the video node this pose node feeds (created beside it the first time).
    function publishVideo(s, video) {
      const canvas = getCanvas();
      let target = (canvas.edges || []).filter(e => e.from === s.id).map(e => getNodeState(e.to)).find(n => n?.type === 'video');
      if (!target && addNode && connectNodes) {
        const id = addNode('video', {x: s.node.x + s.node.width + 260, y: s.node.y + 160});
        connectNodes(s.id, id, {quiet: true});
        target = getNodeState(id);
      }
      if (!target) return '';
      Object.assign(target, {mediaUrl: video.url, mediaName: video.url.split('/').pop(), mimeType: 'video/mp4', status: 'succeeded',
        mediaWidth: video.width, mediaHeight: video.height, fps: video.fps, fileSize: video.file_size || 0, sourceTaskId: '', durationSeconds: 0});
      refreshVideoNode(target.id);
      return target.id;
    }
    async function runVideoExport(s) {
      const node = s.node, seq = node.scene.sequence, key = model.sceneKey(node), pass = node.output.pass;
      const first = seq.inFrame, total = seq.outFrame - seq.inFrame + 1;
      s.stage = '渲染首帧'; paint(s);
      // The first frame is also the node's image output (preview and image consumers).
      const head = await editor().renderNode(node, {frame: first});
      const snapshot = model.snapshot(node, head.world);
      const image = await api.exportImage({image: head.canvas.toDataURL('image/png'), pass, camera: head.shot.name, scene: snapshot});
      const job = await api.video.start({frames: total, fps: seq.fps, width: head.width, height: head.height, format: 'rgba', pass, camera: head.shot.name, scene: snapshot});
      s.videoJob = job.id;
      for (let i = 0; i < total; i++) {
        if (s.cancelExport) throw new Error('已取消导出');
        const {canvas} = i ? await editor().renderNode(node, {frame: first + i}) : head;
        await api.video.frame(job.id, i, await rawFrame(canvas));
        if (i % 5 === 0 || i === total - 1) { s.stage = `渲染 ${i + 1}/${total}`; paint(s); }
      }
      await api.video.finish(job.id);
      s.stage = '编码视频'; paint(s);
      let current = await api.video.job(job.id);
      while (current.status === 'encoding') {
        if (s.cancelExport) throw new Error('已取消导出');
        await wait(600);
        current = await api.video.job(job.id);
      }
      if (current.status !== 'succeeded') throw new Error(current.error || '视频编码失败');
      const now = Date.now();
      const video = {url: current.url, frames: total, fps: seq.fps, width: head.width, height: head.height, exportedAt: now, sceneKey: key};
      Object.assign(node.output, {artifactUrl: image.url, width: image.width, height: image.height, exportedAt: now, cameraName: head.shot.name, sceneKey: key,
        video: {...video, videoNodeId: publishVideo(s, {...video, file_size: current.file_size})}});
    }
    function cancelExport(s) {
      s.cancelExport = true;
      if (s.videoJob) api.video.cancel(s.videoJob).catch(() => {});
    }
    async function runExport(s) {
      if (s.busy) return;
      if (!editor()) throw new Error('姿态编辑器仍在加载，请稍后再试');
      if (model.exportsVideo(s.node)) {
        s.busy = true; s.error = ''; s.flash = ''; s.cancelExport = false; s.videoJob = '';
        try {
          await runVideoExport(s);
          s.node.status = 'exported'; s.node.error = '';
          s.flash = 'succeeded';
          setTimeout(() => { s.flash = ''; paint(s); }, 1600);
          saveState();
          editor()?.exported(s.node);
        } catch (error) {
          if (s.videoJob) api.video.cancel(s.videoJob).catch(() => {});
          s.node.status = s.cancelExport ? (s.node.output.video ? 'exported' : 'idle') : 'failed';
          s.node.error = s.cancelExport ? '' : error?.message || '姿态视频导出失败';
          if (!s.cancelExport) throw error;
        } finally {
          s.busy = false; s.stage = ''; s.videoJob = '';
          paint(s);
        }
        return;
      }
      s.busy = true; s.error = ''; s.flash = ''; s.stage = '渲染中';
      paint(s);
      const node = s.node;
      try {
        const key = model.sceneKey(node);
        const {canvas, shot, world} = await editor().renderNode(node);
        s.stage = '保存中';
        paint(s);
        const result = await api.exportImage({image: canvas.toDataURL('image/png'), pass: node.output.pass, camera: shot.name, scene: model.snapshot(node, world)});
        Object.assign(node.output, {artifactUrl: result.url, width: result.width, height: result.height, exportedAt: Date.now(), cameraName: shot.name, sceneKey: key});
        node.status = 'exported'; node.error = '';
        s.flash = 'succeeded';
        setTimeout(() => { s.flash = ''; paint(s); }, 1600);
        saveState();
        editor()?.exported(node);
      } catch (error) {
        node.status = 'failed'; node.error = error?.message || '姿态导出失败';
        throw error;
      } finally {
        s.busy = false; s.stage = '';
        paint(s);
      }
    }
    function exportFromNode(s) {
      if (s.busy && model.exportsVideo(s.node)) { cancelExport(s); return; }
      runExport(s).catch(error => showMessage(error.message || '姿态导出失败'));
    }
    function openEditor(s) {
      if (!assets?.ready) { refreshAssets(); showMessage(assets?.message || '姿态人偶尚未安装'); return; }
      if (!editor()) { showMessage('姿态编辑器正在加载，请稍后再试'); return; }
      editor().open({node: s.node, references: connectedImages(s.id), videos: connectedVideos(s.id),
        onChange: () => changed(s),
        onExport: () => runExport(s),
        onClose: () => changed(s)});
    }
    function mount(node) {
      const el = getNodeElement(node.id);
      if (!el || sessions.has(node.id)) return;
      model.normalize(node);
      const s = {id: node.id, node, el, abort: new AbortController(), busy: false, stage: '', error: '', flash: ''};
      sessions.set(node.id, s);
      const options = {signal: s.abort.signal};
      el.addEventListener('click', event => {
        if (event.target.closest('[data-pose-open]:not(:disabled)')) { event.stopPropagation(); openEditor(s); }
        if (event.target.closest('[data-pose-export]:not(:disabled)')) { event.stopPropagation(); exportFromNode(s); }
        if (event.target.closest('[data-pose-recognize]:not(:disabled)')) { event.stopPropagation(); recognize(s); }
        if (event.target.closest('[data-pose-evidence]:not(:disabled)')) { event.stopPropagation(); s.node.capture.evidence = !s.node.capture.evidence; changed(s); }
      }, options);
      el.addEventListener('change', event => {
        const field = event.target.dataset.poseField;
        if (!field || s.busy || s.recognizing) return;
        if (field === 'pass' && model.PASSES[event.target.value]) node.output.pass = event.target.value;
        else if (field === 'size' && model.SIZES[event.target.value]) node.output.size = event.target.value;
        else if (field === 'camera' && node.scene.cameras.some(c => c.id === event.target.value)) node.scene.activeCameraId = event.target.value;
        else return;
        changed(s);
      }, options);
      paint(s);
      if (!assets) refreshAssets();
    }
    function dispose(id) {
      const s = sessions.get(id);
      if (!s) return;
      if (getNodeState(id) !== s.node) capture.cancel(id);
      if (editor()?.isOpen() && getNodeState(id) !== s.node) editor().close();
      sessions.delete(id); s.abort.abort();
    }
    function disposeAll() { [...sessions.keys()].forEach(dispose); if (editor()?.isOpen()) editor().close(); }
    function reconcile() {
      [...sessions.values()].forEach(s => { if (!live(s)) dispose(s.id); });
      Object.values(getCanvas().nodes).filter(n => n.type === model.TYPE && !model.isLegacy(n)).forEach(mount);
    }
    function refresh(id) { const s = sessions.get(id); if (s) paint(s); }
    // Old Mixamo/Director nodes are removed, not migrated (docs/POSE_REFERENCE_REBUILD_PLAN.md §10.2).
    function purgeLegacy(canvas = getCanvas()) {
      const removed = model.purgeLegacy(canvas);
      if (removed) showMessage(`已移除 ${removed} 个旧版姿态节点，请用新的姿态参考节点重新摆姿势。`);
      return removed;
    }
    return Object.freeze({nodeHtml: view.html, reconcile, dispose, disposeAll, refresh, purgeLegacy,
      graphChanged: () => sessions.forEach(paint), refreshAssets});
  }
  window.DesktopCanvasPose = Object.freeze({create});
})();
