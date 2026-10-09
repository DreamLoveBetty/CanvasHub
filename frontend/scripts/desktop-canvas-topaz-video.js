// Local Topaz Video jobs, source uploads and video result publication.
// The workbench is an editor adapter; this controller remains the task owner.
(function () {
  function create({model, api, view, workbench, pipeline, getCanvas, getNodeState, getNodeElement, addNode, connectNodes,
    refreshVideoNode, saveState, reportStatus}) {
    const sessions = new Map(), submissions = new Set();
    let catalog = null, runtimeStatus = null, catalogError = '', catalogPromise = null;
    const live = s => sessions.get(s.id) === s && getNodeState(s.id) === s.node && getNodeElement(s.id) === s.el;
    const sourceFor = node => (getCanvas().edges || []).filter(edge => edge.to === node.id)
      .map(edge => getNodeState(edge.from)).find(source => source?.type === 'video');
    const sourceKey = source => source?.mediaUrl
      ? [String(source.id || ''), String(source.mediaUrl), String(source.sourceTaskId || '')].join('|') : '';
    const metaFor = node => catalog?.find(item => item.id === node.model);
    const artifact = job => job?.artifacts?.find(item => item.name === 'result/enhanced.mp4')
      || job?.artifacts?.find(item => /\.mp4$/i.test(item.name || ''));
    function channel(s, kind) {
      return kind === 'preview'
        ? {kind, job: s.previewJob, pending: s.pending?.kind === kind ? s.pending : null,
          status: s.node.previewStatus, id: s.node.previewJobId, timer: 'previewTimer', epoch: 'previewEpoch'}
        : {kind: 'export', job: s.job, pending: s.pending?.kind === 'export' ? s.pending : null,
          status: s.node.status, id: s.node.jobId, timer: 'timer', epoch: 'epoch'};
    }
    function busyChannel(s) {
      if (s.pending) return channel(s, s.pending.kind);
      const preview = channel(s, 'preview');
      if (model.active(preview.status)) return preview;
      const exported = channel(s, 'export');
      if (model.active(exported.status)) return exported;
      return null;
    }
    function resultSourceKey(s, kind, job, source) {
      const saved = kind === 'preview' ? s.node.previewSourceKey : s.node.exportSourceKey;
      if (saved) return saved;
      const assetId = String(job?.spec?.asset_id || '');
      const sourceAssetId = source?.node?.topazVideoAssetUrl === source?.node?.mediaUrl
        ? String(source.node.topazVideoAssetId || '') : '';
      return assetId && sourceAssetId && assetId === sourceAssetId ? source.key : '';
    }
    function resultFor(s, source = sourceContext(s)) {
      if (!source?.key) return null;
      const candidates = [
        {kind: 'preview', job: s.previewJob, startSeconds: Number(s.node.previewStartSeconds || 0)},
        {kind: 'export', job: s.job, startSeconds: Number(s.job?.spec?.start_seconds || 0)},
      ];
      for (const candidate of candidates) {
        const {kind, job, startSeconds} = candidate;
        const item = job?.status === 'succeeded' ? artifact(job) : null;
        if (!item?.url) continue;
        const matchedSourceKey = resultSourceKey(s, kind, job, source);
        if (!matchedSourceKey || matchedSourceKey !== source.key) continue;
        let stale = true;
        try {stale = model.configurationKey(model.request(s.node, 'pending', metaFor(s.node), {}, runtimeStatus)) !== model.configurationKey(job.spec);} catch (_error) { /* Invalid draft still keeps its last valid preview. */ }
        try {return {url: api.sourceUrl(item.url), name: item.name.split('/').pop(), startSeconds, sourceKey: matchedSourceKey, stale,
          timeScale: Number(job?.media?.time_scale || 1),
          durationSeconds: Number(job?.media?.duration_seconds || job?.spec?.max_seconds || 0), job};}
        catch (_error) { /* Ignore an invalid artifact and try the next valid channel. */ }
      }
      return null;
    }
    function sourceContext(s) {
      const source = sourceFor(s.node);
      if (!source?.mediaUrl) return null;
      try {return {url: api.sourceUrl(source.mediaUrl), name: source.mediaName || '已连接视频', key: sourceKey(source),
        duration: Number(source.durationSeconds || 0), width: Number(source.mediaWidth || 0), height: Number(source.mediaHeight || 0),
        fps: Number(source.fps || 0), node: source};}
      catch (_error) {return null;}
    }
    function feedback(s, error = '', force = false, selected = null) {
      if (!live(s)) return;
      if (error) s.noticeError = error;
      const active = selected || busyChannel(s) || channel(s, 'export');
      const job = active.job, state = s.noticeError ? 'failed' : active.pending ? 'submitting' : active.status;
      const label = model.labels[state] || '就绪';
      const operation = active.kind === 'preview' ? '视频增强预览' : '视频增强';
      const summary = s.noticeError ? '操作失败，点击查看详情' : job?.progress_message || job?.stage || label;
      const raw = {engine: 'Topaz Video', task_kind: active.kind, model: job?.spec?.model || s.node.model,
        status: state, stage: job?.stage || '', progress: job?.progress_percent ?? null,
        message: s.noticeError || job?.error || job?.progress_message || label};
      const value = {message: `${operation} · ${summary}`,
        tone: s.noticeError || ['failed', 'interrupted'].includes(state) ? 'error' : state === 'succeeded' ? 'success' : 'info',
        task: {task_id: job?.id || '', node_id: s.id, node_title: `Topaz 视频增强 · ${s.id.slice(-6)}`,
          operation_label: operation, status: state === 'running' ? 'processing' : state === 'cancelled' ? 'canceled' : state,
          status_label: label, provider_route: 'topaz_video_local', detail_title: 'Topaz 视频日志',
          stage: summary, progress_text: summary, raw_detail: JSON.stringify(raw, null, 2) + (job?.error ? '\n\n' + job.error : '')}};
      const key = JSON.stringify(value);
      if (!force && key === s.lastFeedback) return;
      s.lastFeedback = key;
      reportStatus(value);
    }
    function workbenchContext(s) {
      const active = busyChannel(s) || channel(s, 'export');
      const source = sourceContext(s);
      return {id: s.id, node: s.node, catalog, runtimeStatus, source, result: resultFor(s, source),
        busy: {kind: active.kind, job: active.job, pending: Boolean(active.pending), status: s.noticeError ? 'failed' : active.status}};
    }
    function notifyWorkbench(s) {if (live(s)) workbench?.update?.(s.id, workbenchContext(s));}
    function paint(s) {
      if (!live(s)) return;
      const active = busyChannel(s) || channel(s, 'export');
      const state = s.noticeError ? 'failed' : active.status;
      view.paint(s.el, {...s.node, status: state}, active.job, active.pending, catalog, catalogError,
        {kind: active.kind, status: state, processingReady: runtimeStatus?.processing_ready});
      const source = sourceFor(s.node);
      const sourceLabel = s.el.querySelector('[data-topaz-video-source]');
      if (sourceLabel) sourceLabel.textContent = source?.mediaUrl ? source.mediaName || '已连接视频' : '连接视频节点，或导入本地视频';
      notifyWorkbench(s);
    }
    async function refreshCatalog() {
      if (!catalogPromise) {
        catalogPromise = api.status().then(payload => {
          runtimeStatus = payload;
          catalog = model.catalogModels(payload);
          catalogError = '';
          for (const s of sessions.values()) {
            if (!live(s)) continue;
            model.syncForModel(s.node, metaFor(s.node));
            view.renderFields(s.el, s.node, catalog);
            paint(s);
          }
          return catalog;
        }).catch(error => {
          catalog = [];
          catalogError = error.message || '本机模型目录读取失败';
          sessions.forEach(paint);
          throw error;
        }).finally(() => { catalogPromise = null; });
      }
      return catalogPromise;
    }
    function position(node, before = false) {
      const x = before ? node.x - 440 : node.x + node.width + 60;
      let y = node.y;
      const nodes = Object.values(getCanvas().nodes);
      for (let pass = 0; pass <= nodes.length; pass++) {
        const hits = nodes.filter(n => x < n.x + n.width + 20 && x + 400 + 20 > n.x && y < n.y + n.height + 20 && y + 260 + 20 > n.y);
        if (!hits.length) break;
        y = Math.max(...hits.map(n => n.y + n.height)) + 40;
      }
      return {x: x + 200, y: y + 130};
    }
    function publish(s, job, onlyTarget = null) {
      if (!live(s) || s.node.jobId !== job.id || (!onlyTarget && s.node.resultJobId === job.id)) return;
      const item = artifact(job);
      if (!item?.url) throw new Error('任务完成但没有返回增强视频');
      const url = api.sourceUrl(item.url);
      let targets = (getCanvas().edges || []).filter(edge => edge.from === s.id)
        .map(edge => getNodeState(edge.to)).filter(target => target?.type === 'video');
      if (onlyTarget) targets = targets.filter(target => target.id === onlyTarget);
      if (!targets.length && onlyTarget) return;
      if (!targets.length) {
        const id = addNode('video', position(s.node));
        s.publishing = true;
        try { connectNodes(s.id, id, {quiet: true}); } finally { s.publishing = false; }
        targets = [getNodeState(id)];
      }
      for (const target of targets) {
        Object.assign(target, {mediaUrl: url, mediaName: item.name.split('/').pop(), mimeType: 'video/mp4',
          status: 'succeeded', sourceTaskId: job.id, fileSize: item.file_size || 0,
          mediaWidth: job.media?.width || 0, mediaHeight: job.media?.height || 0,
          durationSeconds: job.media?.duration_seconds || 0, fps: job.media?.fps || 0,
          topazVideoAssetId: '', topazVideoAssetUrl: '',
          topazVideoMetadata: {model: job.spec?.enhancement === false ? '' : job.spec?.model || s.node.model,
            scale: job.spec?.scale || s.node.scale, filters: job.spec?.filters || {}, encoding: job.spec?.encoding || {}}});
        refreshVideoNode(target.id);
      }
      s.node.resultJobId = job.id;
      saveState();
      graphChanged();
    }
    function setChannelJob(s, kind, job) {
      if (kind === 'preview') {
        s.previewJob = job; s.node.previewJobId = job.id; s.node.previewStatus = job.status;
      } else {
        s.job = job; s.node.jobId = job.id; s.node.status = job.status;
      }
    }
    async function poll(s, kind = 'export') {
      const slot = channel(s, kind);
      clearTimeout(s[slot.timer]);
      const id = slot.id, epoch = s[slot.epoch] || 0;
      if (!id || !live(s)) return;
      try {
        const job = await api.job(id);
        const latest = channel(s, kind);
        if (!live(s) || latest.id !== id || (s[slot.epoch] || 0) !== epoch) return;
        s.noticeError = '';
        setChannelJob(s, kind, job);
        if (job.status === 'succeeded' && kind === 'export') publish(s, job);
        paint(s); feedback(s, '', false, channel(s, kind)); saveState();
        if (model.active(job.status)) s[slot.timer] = setTimeout(() => poll(s, kind), 1200);
      } catch (error) {
        if (!live(s) || channel(s, kind).id !== id || (s[slot.epoch] || 0) !== epoch) return;
        if (kind === 'preview') s.node.previewStatus = 'failed'; else s.node.status = 'failed';
        feedback(s, error.message, false, channel(s, kind)); paint(s); saveState();
      }
    }
    async function cancel(s) {
      const active = busyChannel(s);
      if (!active) return;
      if (s.pending) {
        s.pending.cancelled = true;
        if (s.pending.jobId) await api.cancel(s.pending.jobId);
      } else if (active.id && model.active(active.status)) await api.cancel(active.id);
      if (live(s)) {
        if (active.kind === 'preview') s.node.previewStatus = 'cancelling'; else s.node.status = 'cancelling';
        paint(s); if (!s.pending) poll(s, active.kind);
      }
    }
    async function runTask(id, kind = 'export', overrides = {}) {
      const s = sessions.get(id);
      if (!s || busyChannel(s)) return;
      s.noticeError = '';
      const meta = metaFor(s.node);
      if (!meta || (s.node.enhancementEnabled !== false && !meta.available)) {feedback(s, meta?.reason || catalogError || '所选模型尚不可运行'); paint(s); return;}
      const source = sourceFor(s.node);
      if (!source?.mediaUrl) {feedback(s, '请先连接有内容的视频节点'); paint(s); return;}
      let snapshot;
      try {snapshot = model.request(s.node, 'pending', meta, {taskKind: kind,
        startSeconds: overrides.startSeconds ?? 0, maxSeconds: overrides.maxSeconds}, runtimeStatus);}
      catch (error) {feedback(s, error.message); paint(s); return;}
      const epochName = kind === 'preview' ? 'previewEpoch' : 'epoch';
      s[epochName] = (s[epochName] || 0) + 1;
      const inputSourceKey = sourceKey(source);
      if (kind === 'preview') {
        s.previewJob = null; s.node.previewStatus = 'submitting';
        s.node.previewSourceKey = inputSourceKey;
        s.node.previewStartSeconds = snapshot.start_seconds; s.node.previewDurationSeconds = snapshot.max_seconds;
      } else {
        s.job = null; s.node.status = 'submitting'; s.node.exportSourceKey = inputSourceKey;
      }
      const op = {s, kind, cancelled: false, jobId: ''};
      s.pending = op; submissions.add(op);
      const sourceSnapshot = {...source};
      paint(s); feedback(s, '', false, channel(s, kind));
      try {
        let assetId = sourceSnapshot.topazVideoAssetUrl === sourceSnapshot.mediaUrl ? sourceSnapshot.topazVideoAssetId : null;
        if (!assetId) {
          const blob = await api.blob(sourceSnapshot.mediaUrl);
          if (op.cancelled || !live(s)) return;
          const asset = await api.upload(blob, sourceSnapshot.mediaName);
          assetId = asset.asset_id;
          if (getNodeState(source.id) === source && source.mediaUrl === sourceSnapshot.mediaUrl) {
            source.topazVideoAssetId = assetId;
            source.topazVideoAssetUrl = sourceSnapshot.mediaUrl;
            saveState();
          }
        }
        if (op.cancelled || !live(s)) return;
        const job = await api.submit({...snapshot, asset_id: assetId});
        op.jobId = job.id;
        if (op.cancelled || !live(s)) {await api.cancel(job.id); return;}
        setChannelJob(s, kind, job);
        if (kind === 'export') s.node.resultJobId = '';
        saveState();
      } catch (error) {
        if (live(s)) {
          if (kind === 'preview') s.node.previewStatus = op.cancelled ? 'cancelled' : 'failed';
          else s.node.status = op.cancelled ? 'cancelled' : 'failed';
          feedback(s, error.message, false, channel(s, kind));
        }
      } finally {
        submissions.delete(op);
        if (s.pending === op) s.pending = null;
        if (live(s)) {
          if (op.cancelled) {
            if (kind === 'preview') s.node.previewStatus = 'cancelled'; else s.node.status = 'cancelled';
            feedback(s, '', false, channel(s, kind));
          }
          paint(s); saveState();
          if (op.jobId && !op.cancelled) poll(s, kind);
        }
      }
    }
    const run = id => runTask(id, 'export', {});
    async function importFile(s, file) {
      if (!file || busyChannel(s)) return;
      s.noticeError = '';
      const op = {s, kind: 'export', cancelled: false};
      s.pending = op; submissions.add(op); paint(s);
      try {
        const asset = await api.upload(file, file.name);
        if (!live(s) || op.cancelled) return;
        const id = addNode('video', position(s.node, true));
        const url = '/api/topaz_video/source?id=' + encodeURIComponent(asset.asset_id);
        Object.assign(getNodeState(id), {mediaUrl: url, mediaName: file.name,
          topazVideoAssetId: asset.asset_id, topazVideoAssetUrl: url, status: 'succeeded'});
        refreshVideoNode(id); connectNodes(id, s.id, {quiet: true}); saveState();
      } catch (error) {feedback(s, error.message);}
      finally {
        submissions.delete(op); if (s.pending === op) s.pending = null;
        if (live(s) && op.cancelled) {s.node.status = 'cancelled'; feedback(s); saveState();}
        paint(s);
      }
    }
    function applyPatch(s, patch) {
      if (!live(s) || busyChannel(s)) return;
      s.noticeError = '';
      if (patch.model) {
        s.node.model = patch.model;
        model.applyPreset(s.node, metaFor(s.node), 'recommended');
      }
      if (patch.scale !== undefined) s.node.scale = Number(patch.scale);
      if (patch.presetId) model.applyPreset(s.node, metaFor(s.node), patch.presetId);
      if (patch.parameter) {
        const field = metaFor(s.node)?.parameters.find(item => item.key === patch.parameter.key);
        const value = Number(patch.parameter.value);
        const units = field?.step > 0 ? (value - field.min) / field.step : 0;
        const aligned = !field?.step || Math.abs(units - Math.round(units)) < 1e-8;
        if (field && Number.isFinite(value) && value >= field.min && value <= field.max && aligned) {
          s.node.modelParams[field.key] = value; s.node.presetId = 'custom';
        }
      }
      if (patch.processing) {
        try {pipeline.patch(s.node, patch.processing, runtimeStatus);} catch (error) {feedback(s, error.message);}
      }
      model.syncForModel(s.node, metaFor(s.node));
      view.renderFields(s.el, s.node, catalog); paint(s); saveState();
    }
    function openWorkbench(s) {
      const source = sourceContext(s);
      if (!source) {feedback(s, '请先连接有内容的视频节点'); paint(s); return;}
      workbench?.open?.({...workbenchContext(s),
        onPatch: patch => applyPatch(s, patch),
        onPreview: range => runTask(s.id, 'preview', range),
        onExport: range => runTask(s.id, 'export', range || {startSeconds: 0, maxSeconds: 0}),
        onRefresh: () => refreshCatalog().catch(error => feedback(s, error.message)),
        onImport: () => s.el.querySelector('[data-topaz-video-file]')?.click(),
      });
    }
    function mount(node) {
      const el = getNodeElement(node.id);
      if (!el || sessions.has(node.id)) return;
      model.normalize(node);
      const s = {id: node.id, node, el, abort: new AbortController()};
      sessions.set(node.id, s);
      const options = {signal: s.abort.signal};
      el.addEventListener('click', event => {
        if (event.target.closest('[data-topaz-video-run]')) run(s.id);
        if (event.target.closest('[data-topaz-video-workbench]')) openWorkbench(s);
        if (event.target.closest('[data-topaz-video-import]')) el.querySelector('[data-topaz-video-file]').click();
      }, options);
      el.addEventListener('change', event => {
        const input = event.target;
        if (input.matches('[data-topaz-video-file]')) {
          const file = input.files?.[0]; input.value = ''; importFile(s, file); return;
        }
        if (busyChannel(s)) return;
        if (input.matches('[data-topaz-video-model]')) {
          node.model = input.value; model.applyPreset(node, metaFor(node), 'recommended');
          view.renderFields(el, node, catalog);
        } else if (input.matches('[data-topaz-video-preset]')) {
          model.applyPreset(node, metaFor(node), input.value);
        } else if (input.matches('[data-topaz-video-scale]')) {
          node.scale = Number(input.value);
        } else if (input.matches('[data-topaz-video-scope]')) {
          node.maxSeconds = input.value === 'full' ? 0 : node.maxSeconds > 0 ? node.maxSeconds : 15;
          view.renderFields(el, node, catalog);
        } else if (input.matches('[data-topaz-video-seconds]')) {
          if (!input.checkValidity()) {input.value = String(node.maxSeconds || 15); return;}
          node.maxSeconds = Number(input.value);
        } else return;
        paint(s); saveState();
      }, options);
      if (node.status === 'submitting') node.status = 'idle';
      if (node.previewStatus === 'submitting') node.previewStatus = 'idle';
      if (catalog) {model.syncForModel(node, metaFor(node)); view.renderFields(el, node, catalog);}
      paint(s);
      if (!catalog) refreshCatalog().catch(() => {});
      if (node.jobId) poll(s, 'export');
      if (node.previewJobId) poll(s, 'preview');
    }
    function dispose(id, removed = false) {
      const s = sessions.get(id);
      if (!s) return;
      if (s.pending) s.pending.cancelled = true;
      if (removed || getNodeState(id) !== s.node) {
        if (s.node.jobId && model.active(s.node.status)) api.cancel(s.node.jobId).catch(() => {});
        if (s.node.previewJobId && model.active(s.node.previewStatus)) api.cancel(s.node.previewJobId).catch(() => {});
      }
      sessions.delete(id); s.abort.abort(); clearTimeout(s.timer); clearTimeout(s.previewTimer); workbench?.dispose?.(id);
    }
    function disposeAll(removed = false) { [...sessions.keys()].forEach(id => dispose(id, removed)); workbench?.dispose?.(); }
    function reconcile() {
      [...sessions.values()].forEach(s => {if (!live(s)) dispose(s.id);});
      Object.values(getCanvas().nodes).filter(n => n.type === model.TYPE).forEach(mount);
    }
    function graphChanged() {sessions.forEach(paint);}
    function connected(fromId, toId) {
      const s = sessions.get(fromId);
      if (s?.job?.status === 'succeeded' && !s.pending && !s.publishing) {
        try {publish(s, s.job, toId);} catch (error) {feedback(s, error.message);}
      }
      graphChanged();
    }
    function getCancelableTasks() {
      const entries = [];
      sessions.forEach(s => {
        if (busyChannel(s)) entries.push({kind: 'topaz_video', key: 'topaz_video:' + s.id, cancel: () => cancel(s)});
      });
      for (const op of submissions) if (!sessions.has(op.s.id))
        entries.push({kind: 'topaz_video', key: 'topaz_video:pending:' + op.s.id,
          cancel: async () => {op.cancelled = true; if (op.jobId) await api.cancel(op.jobId);}});
      return entries;
    }
    return Object.freeze({nodeHtml: view.html, reconcile, dispose, disposeAll, run, runPreview: (id, range) => runTask(id, 'preview', range),
      graphChanged, getCancelableTasks,
      showStatus: id => {const s = sessions.get(id); if (s?.job || s?.previewJob || s?.noticeError) feedback(s, '', true);},
      connections: {targets: model.targets, policy: model.policy, changed: connected, removed: graphChanged}});
  }
  window.DesktopCanvasTopazVideo = Object.freeze({create});
})();
