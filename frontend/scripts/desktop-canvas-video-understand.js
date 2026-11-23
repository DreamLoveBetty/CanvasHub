// Owns video_understand sessions, task lifecycle, upstream text/video binding, and text-node output publishing.
(function () {
  function create({
    model,
    api,
    view,
    getCanvas,
    getNodeState,
    getNodeElement,
    addNode,
    connectNodes,
    refreshVideoNode,
    materializeText = node => String(node?.text || ''),
    writeTextNode,
    saveState,
    reportStatus,
    openModelTools = null,
    isVideoSource = n => n?.type === 'video',
  }) {
    const sessions = new Map();
    const submissions = new Set();
    let envState = null;
    let envFetchedAt = 0;
    let envPromise = null;
    let envWatchTimer = 0;

    const live = s => sessions.get(s.id) === s && getNodeState(s.id) === s.node && getNodeElement(s.id) === s.el;

    const videoSourceFor = node => (getCanvas().edges || [])
      .filter(edge => edge.to === node.id)
      .map(edge => getNodeState(edge.from))
      .find(isVideoSource);

    const promptSourceFor = node => (getCanvas().edges || [])
      .filter(edge => edge.to === node.id)
      .map(edge => getNodeState(edge.from))
      .find(source => source?.type === 'text');

    function scheduleEnvWatch() {
      clearTimeout(envWatchTimer);
      if (sessions.size && envState && !envState.ready && envState.preparation?.status === 'running') {
        envWatchTimer = setTimeout(() => refreshEnvStatus(true).catch(() => {}), 2500);
      }
    }

    async function refreshEnvStatus(force = false) {
      if (typeof api.status !== 'function') return null;
      if (!force && envState && (Date.now() - envFetchedAt) < 15000) return envState;
      if (envPromise) return envPromise;
      envPromise = api.status()
        .then(status => {
          envState = status;
          envFetchedAt = Date.now();
          sessions.forEach(paint);
          scheduleEnvWatch();
          return status;
        })
        .catch(() => null)
        .finally(() => { envPromise = null; });
      return envPromise;
    }

    function feedback(s, error = '', force = false) {
      if (!live(s)) return;
      if (error) s.noticeError = error;
      error = s.noticeError || '';
      const job = s.job;
      const state = error ? 'failed' : s.pending ? 'submitting' : s.node.status;
      const label = model.labels[state] || '就绪';
      const summary = error ? '操作失败，点击查看详情' : (job?.progress_message || model.stageLabel(job?.stage) || label);
      const value = {
        message: `视频理解 · ${summary}`,
        tone: error || ['failed', 'interrupted'].includes(state) ? 'error' : state === 'succeeded' ? 'success' : 'info',
        task: {
          task_id: job?.id || '',
          node_id: s.id,
          node_title: `WeMM 视频理解 · ${s.id.slice(-6)}`,
          operation_label: '视频理解',
          status: state === 'running' ? 'processing' : state === 'cancelled' ? 'canceled' : state,
          status_label: label,
          provider_route: 'wemm_video_local',
          detail_title: '视频理解日志',
          stage: summary,
          progress_text: summary,
          raw_detail: JSON.stringify(
            {
              mode: job?.spec?.mode || s.node.mode,
              status: state,
              stage: job?.stage || summary,
              message: error || job?.progress_message || label,
              stats: job?.result?.stats || null,
              events: job?.events || [],
            },
            null,
            2
          ) + (error || job?.error ? '\n\n' + (error || job.error) : ''),
        },
      };
      const key = JSON.stringify(value);
      if (!force && key === s.lastFeedback) return;
      s.lastFeedback = key;
      reportStatus(value);
      if (error) paint(s);
    }

    function paint(s) {
      if (!live(s)) return;
      const promptNode = promptSourceFor(s.node);
      const promptSourceText = promptNode ? String(materializeText(promptNode) || '') : null;
      view.paint(
        s.el,
        s.noticeError ? { ...s.node, status: 'failed' } : s.node,
        s.job,
        { pending: Boolean(s.pending), envStatus: envState, promptSourceText }
      );
      const source = videoSourceFor(s.node);
      const srcEl = s.el.querySelector('[data-understand-source]');
      if (srcEl) {
        srcEl.textContent = source?.mediaUrl ? (source.mediaName || '已连接视频') : '连接视频节点，或导入本地视频';
      }
    }

    function position(node, before = false) {
      const targetWidth = before ? 360 : 340;
      const targetHeight = before ? 260 : 240;
      const x = before ? (node.x - targetWidth - 60) : (node.x + node.width + 60);
      let y = node.y;
      const nodes = Object.values(getCanvas().nodes || {});
      for (let pass = 0; pass <= nodes.length; pass++) {
        const hits = nodes.filter(
          n => x < n.x + n.width + 20 && x + targetWidth + 20 > n.x && y < n.y + n.height + 20 && y + targetHeight + 20 > n.y
        );
        if (!hits.length) break;
        y = Math.max(...hits.map(n => n.y + n.height)) + 40;
      }
      return { x: x + targetWidth / 2, y: y + targetHeight / 2 };
    }

    function publish(s, job, onlyTarget = null) {
      if (!live(s) || s.node.jobId !== job.id || (!onlyTarget && s.node.resultJobId === job.id)) return;
      const text = String(job?.result?.text || '').trim();
      if (!text) throw new Error('任务完成但未返回分析文本');

      let targets = (getCanvas().edges || [])
        .filter(edge => edge.from === s.id)
        .map(edge => getNodeState(edge.to))
        .filter(node => node?.type === 'text');
      if (onlyTarget) targets = targets.filter(node => node.id === onlyTarget);
      if (!targets.length && onlyTarget) return;

      if (!targets.length) {
        const id = addNode('text', position(s.node, false));
        s.publishing = true;
        try {
          connectNodes(s.id, id, { quiet: true });
        } finally {
          s.publishing = false;
        }
        const created = getNodeState(id);
        if (created) targets = [created];
      }

      targets.forEach(target => writeTextNode?.(target.id, text));
      s.node.resultJobId = job.id;
      saveState();
      graphChanged();
    }

    async function poll(s) {
      clearTimeout(s.timer);
      const id = s.node.jobId;
      const epoch = s.epoch || 0;
      if (!id || !live(s)) return;
      try {
        const job = await api.job(id);
        if (!live(s) || s.node.jobId !== id || (s.epoch || 0) !== epoch) return;
        s.noticeError = '';
        s.job = job;
        s.node.status = job.status;
        if (job.status === 'succeeded') publish(s, job);
        paint(s);
        feedback(s);
        saveState();
        if (model.active(job.status)) s.timer = setTimeout(() => poll(s), 1200);
      } catch (error) {
        if (!live(s) || s.node.jobId !== id || (s.epoch || 0) !== epoch) return;
        feedback(s, error.message);
        paint(s);
        if (model.active(s.node.status)) s.timer = setTimeout(() => poll(s), 3000);
      }
    }

    async function cancel(s) {
      if (s.pending) {
        s.pending.cancelled = true;
        if (s.pending.jobId) await api.cancel(s.pending.jobId);
      } else if (s.node.jobId && model.active(s.node.status)) {
        await api.cancel(s.node.jobId);
      }
      if (live(s)) {
        s.node.status = 'cancelling';
        paint(s);
        if (!s.pending) poll(s);
      }
    }

    async function run(id) {
      const s = sessions.get(id);
      if (!s || s.pending || model.active(s.node.status)) return;
      s.noticeError = '';
      const source = videoSourceFor(s.node);
      if (!source?.mediaUrl) {
        feedback(s, '请先连接有内容的视频节点，或导入本地视频');
        return;
      }

      let videoUrl = '';
      try {
        videoUrl = api.sourceUrl(source.mediaUrl);
      } catch (error) {
        feedback(s, error.message);
        return;
      }

      const promptNode = promptSourceFor(s.node);
      const connectedPrompt = promptNode ? String(materializeText(promptNode) || '') : '';
      const payload = model.request(s.node, videoUrl, connectedPrompt);
      if (s.node.mode === 'custom' && !payload.prompt) {
        feedback(s, '自定义分析模式需要填写提问或接入非空文本节点');
        return;
      }

      if (!envState || !envState.ready) {
        const latest = await refreshEnvStatus(true);
        if (latest && !latest.ready) {
          feedback(s, latest.reasons?.[0] || '视频理解环境尚未就绪，请先在设置中心准备');
          return;
        }
      }

      s.epoch = (s.epoch || 0) + 1;
      const op = { s, cancelled: false, jobId: '' };
      submissions.add(op);
      s.pending = op;
      s.job = null;
      paint(s);
      feedback(s);
      try {
        const job = await api.submit(payload);
        op.jobId = job.id;
        if (op.cancelled || !live(s)) {
          await api.cancel(job.id);
          return;
        }
        s.node.jobId = job.id;
        s.node.status = job.status;
        s.node.resultJobId = '';
        s.job = job;
        saveState();
      } catch (error) {
        if (live(s)) {
          s.pending = null;
          s.node.status = op.cancelled ? 'cancelled' : 'failed';
          feedback(s, error.message);
        }
      } finally {
        submissions.delete(op);
        if (s.pending === op) s.pending = null;
        if (live(s)) {
          if (op.cancelled) {
            s.node.status = 'cancelled';
            feedback(s);
          }
          paint(s);
          saveState();
          if (op.jobId && !op.cancelled) poll(s);
        }
      }
    }

    async function importFile(s, file) {
      if (!file || s.pending || model.active(s.node.status)) return;
      s.noticeError = '';
      const op = { s, cancelled: false };
      s.pending = op;
      submissions.add(op);
      paint(s);
      try {
        const asset = await api.uploadVideo(file, file.name);
        if (!live(s) || op.cancelled) return;
        const id = addNode('video', position(s.node, true));
        Object.assign(getNodeState(id), {
          mediaUrl: asset.mediaUrl,
          mediaName: asset.mediaName || file.name,
          mimeType: asset.mimeType || 'video/mp4',
          mediaWidth: asset.mediaWidth || 0,
          mediaHeight: asset.mediaHeight || 0,
          fps: asset.fps || 24,
          durationSeconds: asset.durationSeconds || 0,
          fileSize: asset.fileSize || 0,
          status: 'succeeded',
        });
        refreshVideoNode(id);
        connectNodes(id, s.id, { quiet: true });
        saveState();
      } catch (error) {
        feedback(s, error.message);
      } finally {
        submissions.delete(op);
        if (s.pending === op) s.pending = null;
        if (live(s) && op.cancelled) {
          s.node.status = 'cancelled';
          feedback(s);
          saveState();
        }
        paint(s);
      }
    }

    function syncControlValues(el, node) {
      for (const key of ['fps', 'maxFrames', 'totalPixels', 'maxTokens']) {
        const input = el.querySelector(`[data-understand-field="${key}"]`);
        if (input) input.value = String(node[key]);
      }
      const anchors = el.querySelector('[data-understand-field="shotAnchors"]');
      if (anchors) anchors.checked = Boolean(node.shotAnchors);
    }

    function mount(node) {
      const el = getNodeElement(node.id);
      if (!el || sessions.has(node.id)) return;
      model.normalize(node);
      const s = { id: node.id, node, el, abort: new AbortController() };
      sessions.set(node.id, s);
      const options = { signal: s.abort.signal };

      el.addEventListener('click', event => {
        if (event.target.closest('[data-understand-run]')) {
          run(s.id);
        } else if (event.target.closest('[data-understand-import]')) {
          el.querySelector('[data-understand-file]')?.click();
        } else if (event.target.closest('[data-understand-advanced-toggle]')) {
          node.advancedOpen = !node.advancedOpen;
          paint(s);
          saveState();
        } else if (event.target.closest('[data-understand-open-settings]')) {
          openModelTools?.();
        }
      }, options);

      el.addEventListener('input', event => {
        const input = event.target;
        if (!input.matches('[data-understand-field="prompt"]')) return;
        node.prompt = String(input.value || '').slice(0, 8000);
        saveState();
      }, options);

      el.addEventListener('change', event => {
        const input = event.target;
        if (input.matches('[data-understand-file]')) {
          const file = input.files?.[0];
          input.value = '';
          importFile(s, file);
          return;
        }
        const key = input.dataset?.understandField;
        if (!key || s.pending || model.active(node.status)) return;
        if (key === 'mode') {
          model.applyModeDefaults(node, input.value);
          syncControlValues(el, node);
        } else if (input.type === 'checkbox') {
          node[key] = Boolean(input.checked);
          model.normalize(node);
        } else if (['fps', 'maxFrames', 'totalPixels', 'maxTokens'].includes(key)) {
          node[key] = Number(input.value);
          model.normalize(node);
          input.value = String(node[key]);
        } else {
          node[key] = input.value;
          model.normalize(node);
        }
        paint(s);
        saveState();
      }, options);

      if (node.status === 'submitting') node.status = 'idle';
      paint(s);
      refreshEnvStatus(false);
      if (node.jobId) poll(s);
    }

    function dispose(id, removed = false) {
      const s = sessions.get(id);
      if (!s) return;
      if (s.pending) s.pending.cancelled = true;
      if ((removed || getNodeState(id) !== s.node) && s.node.jobId && model.active(s.node.status)) {
        api.cancel(s.node.jobId).catch(() => {});
      }
      sessions.delete(id);
      s.abort.abort();
      clearTimeout(s.timer);
      if (!sessions.size) clearTimeout(envWatchTimer);
    }

    function disposeAll(removed = false) {
      [...sessions.keys()].forEach(id => dispose(id, removed));
    }

    function reconcile() {
      [...sessions.values()].forEach(s => { if (!live(s)) dispose(s.id); });
      Object.values(getCanvas().nodes || {})
        .filter(node => node?.type === model.TYPE)
        .forEach(mount);
    }

    function graphChanged() {
      sessions.forEach(paint);
    }

    function connected(fromId, toId) {
      const s = sessions.get(fromId);
      if (s?.job?.status === 'succeeded' && !s.pending && !s.publishing) {
        try {
          publish(s, s.job, toId);
        } catch (error) {
          feedback(s, error.message);
        }
      }
      graphChanged();
    }

    function getCancelableTasks() {
      const entries = [];
      sessions.forEach(s => {
        if (s.pending || model.active(s.node.status)) {
          entries.push({
            kind: 'video_understand',
            key: `video_understand:${s.id}`,
            cancel: () => cancel(s),
          });
        }
      });
      for (const op of submissions) {
        if (!sessions.has(op.s.id)) {
          entries.push({
            kind: 'video_understand',
            key: `video_understand:pending:${op.s.id}`,
            cancel: async () => {
              op.cancelled = true;
              if (op.jobId) await api.cancel(op.jobId);
            },
          });
        }
      }
      return entries;
    }

    return {
      nodeHtml: view.html,
      reconcile,
      dispose,
      disposeAll,
      run,
      graphChanged,
      getCancelableTasks,
      refreshEnvStatus,
      showStatus: id => {
        const s = sessions.get(id);
        if (s?.job || s?.noticeError) feedback(s, '', true);
      },
      connections: {
        targets: model.targets,
        policy: model.policy,
        changed: connected,
        removed: graphChanged,
      },
    };
  }

  window.DesktopCanvasVideoUnderstand = Object.freeze({ create });
})();
