// Music-domain controller. Owns polling/preview lifetimes, not the shared canvas or players.
// Graph operations, text materialization and the shared audio-node API are injected.
(function () {
  function create({ model, api, score, view, workflow, getCanvas, getNodeState, getNodeElement, materializeText,
    audio, addNode, connectNodes, saveState, reportStatus = () => {}, escapeHtml: e }) {
    const sessions = new Map();
    const cancellations = new Map();
    let progressClock = 0;
    const chain = workflow.create({ getCanvas, getNodeState, runTranscription: ensureTranscription });
    const labels = { idle: '就绪', queued: '排队中', running: '推理中', cancelling: '停止中',
      succeeded: '已完成', partial: '结果截断', cancelled: '已停止', failed: '失败', interrupted: '已中断' };
    const incoming = id => (getCanvas().edges || []).filter(edge => edge.to === id);
    const live = s => sessions.get(s.id) === s && getNodeState(s.id) === s.node && getNodeElement(s.id) === s.el;
    const inference = s => ['music_generate', 'music_transcribe'].includes(s.node.type);
    function report(s, force = false) {
      if (!live(s) || !inference(s)) return;
      const job = s.progressJob?.id === s.node.jobId ? s.progressJob : null;
      if (!job && !s.submission && !s.runOutcome && !s.noticeError) return;
      const feedback = model.taskFeedback(s.node, job, buttonState(s), {
        pending: Boolean(s.runOutcome || s.submission && !s.submission.jobId), error: s.noticeError, publishing: s.publishing,
      });
      const key = JSON.stringify(feedback);
      if (!force && key === s.statusKey) return;
      s.statusKey = key; reportStatus(feedback);
    }
    function error(s, message = '') {
      if (!live(s)) return;
      if (inference(s)) { s.noticeError = message; if (message) report(s); return; }
      const el = s.el.querySelector('[data-music-error]'); if (el) { el.textContent = message; el.hidden = !message; }
    }
    function abcFor(node, visited = new Set()) {
      if (!node || visited.has(node.id)) return '';
      visited.add(node.id);
      if (node.type === 'music_abc') return node.abc || '';
      if (node.type === 'music_score') {
        const source = node.resultAbc || abcFor(getNodeState(incoming(node.id)[0]?.from), visited) || node.abc || '';
        return model.scoreAbc(source, node.scoreTitle);
      }
      if (node.resultAbc) return node.resultAbc;
      return '';
    }
    function inputsFor(node) {
      const result = {};
      incoming(node.id).forEach(edge => {
        const source = getNodeState(edge.from); if (!source) return;
        if (source.type === 'text') result[edge.inputRole === 'style' ? 'style' : 'lyrics'] = materializeText(source);
        else if (source.type === 'audio') result.audioId = source.id;
        else { const abc = abcFor(source); if (abc) result.abc = abc; }
      });
      return result;
    }
    function connections(s) {
      if (!live(s)) return;
      const standalone = s.el.querySelector('[data-music-standalone-actions]');
      if (standalone) {
        const chained = chain.isChained(s.node);
        standalone.hidden = chained;
        s.el.querySelector('[data-music-chain-hint]').hidden = !chained;
      }
      const edges = incoming(s.id), area = s.el.querySelector('[data-music-inputs]');
      if (!area) return;
      const linked = edges.map(edge => {
        const source = getNodeState(edge.from); if (!source) return '';
        const name = e(source.alias || source.mediaName || model.definitions[source.type]?.title || source.type);
        if (source.type !== 'text') return `<span>${name}</span>`;
        return `<label>${name}<select data-music-edge-role="${e(edge.id)}" aria-label="${name}用途"><option value="lyrics" ${edge.inputRole !== 'style' ? 'selected' : ''}>歌词</option><option value="style" ${edge.inputRole === 'style' ? 'selected' : ''}>风格</option></select></label>`;
      }).join(' · ');
      if (s.node.type === 'music_generate') {
        const inputs = inputsFor(s.node);
        area.innerHTML = `<div class="desk-music__input-status">${[['style', '风格'], ['lyrics', '歌词']].map(([role, label]) => {
          const value = inputs[role], ready = Boolean(value?.trim());
          return `<span data-music-input-state="${role}" class="${ready ? 'is-ready' : ''}">${label} · ${ready ? '已接入' : value === undefined ? '待接入文本' : '文本为空'}</span>`;
        }).join('')}</div>${linked ? `<div>${linked}</div>` : '<span>连接两个文本节点，分别指定用途；ABC 可选</span>'}`;
      } else area.innerHTML = linked || '等待兼容节点接入';
      const chooser = s.el.querySelector('[data-music-add-source]');
      if (chooser) chooser.innerHTML = '<option value="">选择音频或乐谱…</option>' + Object.values(getCanvas().nodes)
        .filter(n => model.TARGETS[n.type]?.includes('music_compare') && !edges.some(edge => edge.from === n.id))
        .map(n => `<option value="${e(n.id)}">${e(n.mediaName || model.definitions[n.type]?.title || n.type)} · ${e(n.id.slice(-6))}</option>`).join('');
    }
    function buttonState(s) {
      return model.generationButtonState(s.node, { submitting: s.submitting,
        cancelRequested: s.cancelPending || s.submission?.cancelRequested,
        phase: s.submission?.phase, outcome: s.runOutcome });
    }
    function paintProgress(s) {
      if (!live(s) || s.node.type !== 'music_generate') return;
      view.paintProgress(s.el, model.generationProgress(s.node, s.progressJob, buttonState(s), {
        submittedAt: s.submission?.startedAt,
      }));
    }
    // One display clock for all active music nodes; polling and persisted jobs
    // remain unchanged. Node-relative overlays follow pan/zoom without observers.
    function syncProgressClock() {
      const busy = [...sessions.values()].some(s => live(s) && s.node.type === 'music_generate' && buttonState(s).busy);
      if (!busy) { clearTimeout(progressClock); progressClock = 0; }
      else if (!progressClock) progressClock = setTimeout(() => {
        progressClock = 0; sessions.forEach(paintProgress); syncProgressClock();
      }, 1000);
    }
    function paintJob(s, job) {
      if (!live(s)) return;
      if (job) s.progressJob = job;
      const label = s.el.querySelector('[data-music-status]');
      label.textContent = s.cancelPending || s.submission?.cancelRequested ? '停止中' : s.submitting ? (s.submission.phase ? '等待转谱' : '提交中') : labels[s.runOutcome || s.node.status] || s.node.status;
      label.classList.toggle('is-success', ['succeeded', 'idle'].includes(s.runOutcome || s.node.status) && !s.submitting);
      const run = s.el.querySelector('[data-music-action="run"]');
      if (run && s.node.type === 'music_generate') {
        view.paintRunButton(run, buttonState(s));
      } else if (run) run.disabled = s.submitting || model.active(s.node.status);
      const area = s.el.querySelector('[data-music-artifacts]');
      if (area) area.innerHTML = (s.node.artifacts || []).map((f, index) => `<button type="button" data-music-download="${index}" title="${e(f.name)}">${e(f.name.split('/').pop())}</button>`).join('');
      paintProgress(s); syncProgressClock(); report(s);
    }
    function outputPosition(source, type) {
      const width = type === 'audio' ? 800 : model.definitions[type].width;
      const height = type === 'audio' ? 360 : model.definitions[type].height;
      const x = source.x + source.width + 80;
      let y = source.y;
      // Generated results must not cover an existing editor or another result.
      const nodes = Object.values(getCanvas().nodes);
      for (let pass = 0; pass <= nodes.length; pass++) {
        const overlapping = nodes.filter(n => x < n.x + n.width + 28 && x + width + 28 > n.x && y < n.y + n.height + 28 && y + height + 28 > n.y);
        if (!overlapping.length) break;
        y = Math.max(...overlapping.map(n => n.y + n.height)) + 48;
      }
      return { x: x + width / 2, y: y + height / 2 };
    }
    async function publish(s, job) {
      if (!live(s) || s.node.jobId !== job.id || s.node.resultJobId === job.id) return;
      const files = job.artifacts || [], abcFile = files.find(f => f.name.endsWith('/score.abc'));
      const song = model.audioArtifact(files, job.spec);
      const abc = abcFile ? await api.text(abcFile.url) : '';
      // Fetch before mutating the graph. A workflow replacement/deleted node cannot receive stale results.
      const blob = song && song.file_size <= 100 * 1024 * 1024 ? await api.blob(song.url) : null;
      if (!live(s) || s.node.jobId !== job.id) return;
      s.node.resultAbc = abc; s.node.artifacts = files; s.node.resultSpec = job.spec;
      let targets = (getCanvas().edges || []).filter(edge => edge.from === s.id).map(edge => getNodeState(edge.to)).filter(Boolean);
      if (song && !targets.some(n => n.type === 'audio')) {
        const id = addNode('audio', outputPosition(s.node, 'audio'));
        connectNodes(s.id, id, { quiet: true }); targets.push(getNodeState(id));
      }
      if (abc && !targets.some(n => n.type === 'music_abc' || n.type === 'music_score')) {
        const id = addNode('music_abc', outputPosition(s.node, 'music_abc'));
        connectNodes(s.id, id, { quiet: true }); targets.push(getNodeState(id));
      }
      for (const target of targets) {
        if (!live(s) || s.node.jobId !== job.id) return;
        if (target.type === 'audio' && song) {
          await audio.setResult(target.id, { blob, url: song.url, name: song.name.split('/').pop(), mime_type: song.mime_type || (song.name.endsWith('.wav') ? 'audio/wav' : 'audio/flac'),
            file_size: song.file_size, task_id: job.id });
        } else if (target.type === 'music_abc' && abc) {
          target.abc = abc; target.sourceTaskId = job.id; syncEditor(sessions.get(target.id));
        }
      }
      if (!live(s) || s.node.jobId !== job.id) return;
      s.node.resultJobId = job.id;
      if (s.node.type === 'music_transcribe') s.node.transcriptionResultKey = s.node.transcriptionInputKey || '';
      saveState(); graphChanged();
    }
    function notifyWaiters(s, failure) { s.waiters?.forEach(check => check(failure)); }
    function waitForResult(s, jobId, signal) {
      return new Promise((resolve, reject) => {
        const finish = (failure) => {
          s.waiters.delete(check); signal.removeEventListener('abort', abort);
          if (failure) reject(failure); else resolve();
        };
        const abort = () => finish(Object.assign(new Error('已停止执行链'), { name: 'AbortError' }));
        const check = failure => {
          if (failure) return finish(failure);
          if (!live(s) || s.node.jobId !== jobId) return finish(new Error('上游转谱节点或任务已变化'));
          if (['failed', 'cancelled', 'cancelling', 'interrupted', 'partial'].includes(s.node.status)) {
            return finish(new Error(s.jobError || `上游转谱${labels[s.node.status]}，未提交生成`));
          }
          if (s.node.status === 'succeeded' && s.node.resultJobId === jobId) finish();
        };
        if (signal.aborted) return abort();
        s.waiters.add(check); signal.addEventListener('abort', abort, { once: true }); check();
      });
    }
    async function ensureTranscription(node, key, signal) {
      const s = sessions.get(node.id);
      if (!s || !live(s) || s.node !== node) throw new Error('上游转谱节点不可用');
      if (chain.cached(node, key)) return;
      // Reuse the controller's pending submission/polling, including concurrent consumers.
      const publishing = node.status === 'succeeded' && node.transcriptionInputKey === key && node.jobId && node.resultJobId !== node.jobId;
      if (!s.submission && !model.active(node.status) && !publishing) run(s);
      const submission = s.submission;
      if (submission) {
        await workflow.wait(submission.done, signal);
        if (submission.failure) throw submission.failure;
      }
      if (!live(s) || !node.jobId || node.transcriptionInputKey !== key) throw new Error('上游转谱输入已变化，请等待当前任务结束后重试');
      await waitForResult(s, node.jobId, signal);
    }
    async function poll(s) {
      if (!live(s) || !s.node.jobId || s.polling) return;
      s.polling = true; clearTimeout(s.timer);
      const jobId = s.node.jobId;
      const cancelRevision = s.cancelRevision;
      try {
        const job = await api.job(jobId); if (!live(s) || s.node.jobId !== jobId || s.cancelRevision !== cancelRevision) return;
        const changed = s.node.status !== job.status;
        s.jobError = job.error || '';
        s.node.status = job.status; s.node.artifacts = job.artifacts || [];
        error(s);
        s.publishing = ['succeeded', 'partial'].includes(job.status) && s.node.resultJobId !== jobId;
        paintJob(s, job);
        if (changed) saveState();
        if (s.publishing) { await publish(s, job); s.publishing = false; if (live(s)) paintJob(s); }
      } catch (err) {
        if (!live(s) || s.node.jobId !== jobId || s.cancelRevision !== cancelRevision) return;
        error(s, `${s.publishing ? '接入生成结果失败' : '读取任务失败'}：${err.message}`); notifyWaiters(s, err);
      }
      finally {
        s.polling = false;
        notifyWaiters(s);
        if (live(s) && s.node.jobId !== jobId) poll(s);
        else if (live(s) && (model.active(s.node.status) || ['succeeded', 'partial'].includes(s.node.status) && s.node.resultJobId !== jobId)) s.timer = setTimeout(() => poll(s), 2500);
      }
    }
    async function run(s) {
      if (s.submitting || model.active(s.node.status)) return;
      const submission = { cancelRequested: false, abort: new AbortController(), startedAt: Date.now() };
      submission.done = new Promise(resolve => { submission.finish = resolve; });
      s.submission = submission;
      s.runOutcome = ''; s.publishing = false; s.statusKey = '';
      error(s); s.submitting = true; paintJob(s);
      try {
        const inputs = inputsFor(s.node); let body, inputKey = '';
        if (s.node.type === 'music_transcribe') {
          if (!inputs.audioId) throw new Error('请先连接音频素材节点');
          inputKey = chain.transcriptionKey(s.node);
          const sourceNode = getNodeState(inputs.audioId), source = await audio.getInput(inputs.audioId);
          if (!source) throw new Error('连接的音频节点没有素材');
          const blob = source.blob || await api.blob(source.url);
          if (!live(s) || submission.cancelRequested || getNodeState(inputs.audioId) !== sourceNode || inputsFor(s.node).audioId !== inputs.audioId) return;
          const uploaded = await api.upload(blob, source.name || 'audio.wav');
          if (chain.transcriptionKey(s.node) !== inputKey) throw new Error('参考音频或转谱参数已变化，请重新转谱');
          body = { operation: 'transcribe', asset_id: uploaded.asset_id, task: s.node.transcribeTask, preset: s.node.preset, max_seconds: s.node.maxSeconds };
        } else {
          const ref = chain.reference(s.node);
          const request = () => {
            const current = inputsFor(s.node);
            const value = model.generationRequest(s.node, ref ? { ...current, abc: '' } : current);
            value.request.id = s.node.songId || 'song'; return value;
          };
          body = request();
          if (ref) {
            const signature = JSON.stringify(body);
            const abc = await chain.prepare(s.node, {
              signal: submission.abort.signal,
              valid: () => live(s) && JSON.stringify(request()) === signature,
              stage: phase => { submission.phase = phase; paintJob(s); },
            });
            if (abc) body.request.abc = abc;
            submission.phase = ''; paintJob(s);
          }
        }
        if (!live(s) || submission.cancelRequested) return;
        const job = await api.submit(body);
        submission.jobId = job.id;
        if (!live(s)) { await api.cancel(job.id).catch(() => {}); return; }
        s.node.jobId = job.id; s.node.status = job.status; s.node.artifacts = [];
        if (s.node.type === 'music_transcribe') s.node.transcriptionInputKey = inputKey;
        saveState(); paintJob(s, job);
        if (submission.cancelRequested) {
          try { await cancelJob(job.id); }
          catch (err) { submission.cancelError = err; error(s, `停止任务失败：${err.message}`); }
        }
        poll(s);
      } catch (err) {
        submission.failure = err; s.runOutcome = err.name === 'AbortError' ? 'cancelled' : 'failed';
        error(s, err.name === 'AbortError' ? '' : err.message);
      } finally {
        if (submission.cancelRequested && !submission.jobId) s.runOutcome = 'cancelled';
        s.submitting = false; s.submission = null; submission.finish(); if (live(s)) paintJob(s);
      }
    }
    // The canvas stop button gets transient commands, never ownership of music job state.
    function cancelJob(jobId) {
      if (cancellations.has(jobId)) return cancellations.get(jobId);
      sessions.forEach(s => {
        if (!live(s) || s.node.jobId !== jobId) return;
        s.cancelRevision = (s.cancelRevision || 0) + 1; s.cancelPending = true; paintJob(s);
      });
      const task = (async () => {
        try {
          const job = await api.cancel(jobId);
          let changed = false;
          sessions.forEach(s => {
            if (!live(s) || s.node.jobId !== jobId) return;
            changed = true; s.node.status = job.status; error(s); paintJob(s, job); notifyWaiters(s);
          });
          if (changed) saveState(); return job;
        } catch (err) {
          sessions.forEach(s => { if (live(s) && s.node.jobId === jobId) error(s, `停止任务失败：${err.message}`); });
          throw err;
        } finally {
          cancellations.delete(jobId);
          sessions.forEach(s => {
            if (live(s) && s.node.jobId === jobId) { s.cancelPending = false; paintJob(s); }
          });
        }
      })();
      cancellations.set(jobId, task); return task;
    }
    function getCancelableTasks() {
      const seen = new Set(), entries = [];
      sessions.forEach(s => {
        if (!live(s) || !['music_generate', 'music_transcribe'].includes(s.node.type)) return;
        const submission = s.submission, jobId = s.node.jobId;
        if (!submission && (!jobId || !model.active(s.node.status))) return;
        const key = submission ? `music:submit:${s.id}` : `music:job:${jobId}`;
        if (seen.has(key)) return; seen.add(key);
        entries.push({ kind: 'music', key, cancel: async () => {
          if (!live(s)) return;
          if (submission) {
            if (s.submission !== submission) return;
            submission.cancelRequested = true; submission.abort.abort(); paintJob(s);
            await submission.done;
            if (submission.cancelError) throw submission.cancelError;
            return;
          }
          if (s.submitting || s.node.jobId !== jobId || !model.active(s.node.status)) return;
          return cancelJob(jobId);
        } });
      });
      return entries;
    }
    function syncEditor(s) {
      if (!s || !live(s) || s.node.type !== 'music_abc') return;
      const editor = s.el.querySelector('[data-music-field="abc"]');
      if (document.activeElement !== editor) editor.value = s.node.abc;
      s.el.querySelector('[data-music-lines]').textContent = Array.from({ length: s.node.abc.split('\n').length }, (_, i) => i + 1).join('\n');
      if (s.editorText !== s.node.abc) {
        s.editorText = s.node.abc;
        s.el.querySelector('[data-music-validation]').textContent = '尚未校验当前内容';
      }
    }
    async function refreshScore(s) {
      if (!live(s) || s.node.type !== 'music_score') return;
      const abc = abcFor(s.node), key = JSON.stringify([abc, s.node.tab, s.node.voice, s.node.scoreScale]);
      if (key === s.scoreKey) return;
      s.scoreKey = key;
      const token = ++s.renderToken, paper = s.el.querySelector('[data-music-staff]');
      const source = s.el.querySelector('[data-music-score-source]'), midi = s.el.querySelector('[data-music-midi-info]');
      paper.hidden = ['abc', 'midi'].includes(s.node.tab); source.hidden = s.node.tab !== 'abc'; midi.hidden = s.node.tab !== 'midi';
      source.textContent = abc || '未接入乐谱';
      s.el.querySelector('[data-music-score-meta]').textContent = ['K', 'M', 'Q'].map(key => new RegExp('^' + key + ':(.*)$', 'm').exec(abc)?.[1] || '—').join(' · ');
      try {
        await score.library(); if (!live(s) || token !== s.renderToken) return;
        await score.render(paper, abc, { voice: s.node.voice, scale: s.node.scoreScale });
      } catch (err) { if (live(s) && token === s.renderToken) { s.scoreKey = ''; error(s, err.message); } }
    }
    function releaseCompare(s) {
      s.el.querySelectorAll('[data-music-compare] audio').forEach(player => { player.pause(); player.removeAttribute('src'); player.load(); });
      s.urls.forEach(url => URL.revokeObjectURL(url)); s.urls = [];
    }
    async function refreshCompare(s) {
      if (!live(s) || s.node.type !== 'music_compare') return;
      const token = ++s.compareToken; releaseCompare(s);
      const area = s.el.querySelector('[data-music-compare]'), sources = incoming(s.id).map(edge => getNodeState(edge.from)).filter(Boolean);
      area.replaceChildren();
      for (const [index, node] of sources.entries()) {
        if (!live(s) || token !== s.compareToken) return;
        const card = document.createElement('div'); card.className = 'desk-music__compare-card';
        const title = document.createElement('strong'); title.textContent = `${String.fromCharCode(65 + index)} · ${node.mediaName || model.definitions[node.type]?.title || '音频'}`; card.appendChild(title); area.appendChild(card);
        if (s.node.tab !== 'audio') {
          const pre = document.createElement('pre'); card.appendChild(pre);
          try {
            let abc = abcFor(node), spec = node.resultSpec;
            if (node.type === 'audio' && /^[a-f0-9]{32}$/.test(node.sourceTaskId || '')) {
              const job = await api.job(node.sourceTaskId); spec = job.spec;
              const file = job.artifacts.find(f => f.name.endsWith('/score.abc'));
              if (file && s.node.tab === 'score') abc = await api.text(file.url);
            }
            if (!live(s) || token !== s.compareToken) return;
            pre.textContent = s.node.tab === 'score' ? abc || '此项没有关联乐谱' : JSON.stringify(spec || { source_task_id: node.sourceTaskId || '', duration_seconds: node.durationSeconds, sample_rate: node.sampleRate, channels: node.channels }, null, 2);
          } catch (err) { pre.textContent = `关联任务不可用：${err.message}`; }
          continue;
        }
        try {
          let input = node.type === 'audio' ? await audio.getInput(node.id) : model.audioArtifact(node.artifacts, node.resultSpec);
          if (!input) { card.appendChild(document.createTextNode('没有可播放音频')); continue; }
          const blob = input.blob || await api.blob(input.url);
          if (!live(s) || token !== s.compareToken) return;
          const url = URL.createObjectURL(blob); s.urls.push(url);
          const wave = node.peaks?.length ? node : Object.values(getCanvas().nodes).find(n => n.type === 'audio' && n.sourceTaskId && n.sourceTaskId === node.jobId);
          if (wave?.peaks?.length) {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', '0 0 240 50');
            const path = document.createElementNS(svg.namespaceURI, 'path');
            path.setAttribute('d', wave.peaks.map((v, i) => `M${i} ${25 - v * 23}v${v * 46}`).join(' ')); svg.appendChild(path); card.appendChild(svg);
          }
          const player = document.createElement('audio'); player.controls = true; player.preload = 'metadata'; player.src = url; card.appendChild(player);
        } catch (err) { if (live(s) && token === s.compareToken) card.appendChild(document.createTextNode(err.message)); }
      }
      if (!sources.length) area.textContent = '连接音频、生成结果或乐谱，添加 A / B 对比项。';
    }
    async function action(s, name) {
      error(s);
      try {
        if (name === 'run') return await run(s);
        if (name === 'template') {
          if (s.node.abc.trim() && !window.confirm('用示例替换当前 ABC？')) return;
          s.node.abc = model.DEFAULT_ABC; syncEditor(s); saveState(); graphChanged(); return;
        }
        if (name === 'import-abc') { s.el.querySelector('[data-music-abc-file]').click(); return; }
        if (name === 'validate' || name === 'strip-chords') {
          const original = s.node.abc;
          const result = await api.score({ operation: name === 'validate' ? 'inspect' : name, abc: original });
          if (!live(s) || s.node.abc !== original) return;
          if (result.abc) { s.node.abc = result.abc; syncEditor(s); saveState(); graphChanged(); }
          s.el.querySelector('[data-music-validation]').textContent = name === 'validate' ? `YuE 双声部结构校验通过 · ${result.bpm} BPM · 约 ${result.nominal_duration_seconds.toFixed(1)} 秒（不代表音频质量）` : '已移除和弦，保留旋律'; return;
        }
        if (name.startsWith('export-')) {
          // Loading may overlap typing. Snapshot only after the library is ready,
          // and repaint before graphical exports so they cannot use a stale title.
          const graphical = ['export-png', 'export-svg', 'export-pdf'].includes(name);
          if (graphical && s.node.type === 'music_score') {
            await score.library(); if (!live(s)) return;
          }
          const abc = abcFor(s.node); if (!abc.trim()) throw new Error('没有可导出的乐谱');
          if (graphical && s.node.type === 'music_score') {
            ++s.renderToken;
            await score.render(s.el.querySelector('[data-music-staff]'), abc, { voice: s.node.voice, scale: s.node.scoreScale });
            if (!live(s)) return;
          }
          return await score.exportFile(name.slice(7), s.el.querySelector('[data-music-staff]'), abc);
        }
        if (name === 'zoom-in' || name === 'zoom-out') { s.node.scoreScale = Math.max(.5, Math.min(2, s.node.scoreScale + (name === 'zoom-in' ? .1 : -.1))); saveState(); return refreshScore(s); }
        if (name === 'refresh-compare') { connections(s); return await refreshCompare(s); }
        if (name === 'play-compare') {
          const players = [...s.el.querySelectorAll('[data-music-compare] audio')];
          const selected = s.node.syncPlayback ? players : players.slice(0, 1);
          selected.forEach(p => { p.currentTime = 0; });
          try { await Promise.all(selected.map(p => p.play())); } catch (err) { selected.forEach(p => p.pause()); throw err; } return;
        }
        if (name === 'stop-compare') s.el.querySelectorAll('[data-music-compare] audio').forEach(p => { p.pause(); p.currentTime = 0; });
      } catch (err) { error(s, err.message); }
    }
    function mount(node) {
      if (sessions.has(node.id)) return;
      const el = getNodeElement(node.id); if (!el) return;
      model.normalizeState(node);
      const s = { id: node.id, node, el, abort: new AbortController(), timer: 0, urls: [], renderToken: 0, compareToken: 0, waiters: new Set() };
      sessions.set(node.id, s); const options = { signal: s.abort.signal };
      el.addEventListener('click', event => {
        const button = event.target.closest('[data-music-action], [data-music-tab], [data-music-download]'); if (!button) return;
        event.stopPropagation();
        if (button.dataset.musicTab) {
          node.tab = button.dataset.musicTab; el.querySelectorAll('[data-music-tab]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
          const tools = el.querySelector('[data-music-tools]'); if (tools) tools.hidden = node.tab !== 'tools';
          if (node.tab === 'check') action(s, 'validate');
          saveState(); refreshScore(s); refreshCompare(s); return;
        }
        if (button.dataset.musicDownload !== undefined) {
          const file = node.artifacts?.[Number(button.dataset.musicDownload)];
          if (file?.url?.startsWith('/api/audio/artifact?')) api.blob(file.url).then(blob => score.download(blob, file.name.split('/').pop())).catch(err => error(s, err.message));
          return;
        }
        action(s, button.dataset.musicAction);
      }, options);
      el.addEventListener('input', event => {
        const field = event.target.dataset.musicField; if (!field) return;
        if (event.target.readOnly) return;
        node[field] = event.target.type === 'checkbox' ? event.target.checked : event.target.type === 'number' ? (event.target.value === '' ? '' : Number(event.target.value)) : event.target.value;
        if (field === 'odeSteps') {
          node[field] = Number(node[field]);
          el.querySelectorAll('[data-music-field="odeSteps"]').forEach(peer => {
            if (peer === event.target) return;
            if (peer.tagName === 'SELECT' && ![...peer.options].some(option => option.value === String(node[field]))) {
              peer.querySelector('[data-custom-steps]')?.remove();
              const option = new Option(`${node[field]} 步`, String(node[field])); option.dataset.customSteps = ''; peer.appendChild(option);
            }
            peer.value = String(node[field]);
          });
        }
        if (field === 'abc') { syncEditor(s); el.querySelector('[data-music-validation]').textContent = '已修改 · 尚未重新校验'; }
        if (field === 'scoreTitle') node.scoreTitle = model.normalizeScoreTitle(node.scoreTitle);
        if (field === 'voice' || field === 'scoreTitle') refreshScore(s);
        clearTimeout(s.saveTimer); s.saveTimer = setTimeout(() => { if (live(s)) { saveState(); graphChanged(); } }, 350);
      }, options);
      el.addEventListener('change', async event => {
        if (event.target.dataset.musicEdgeRole) {
          const edge = getCanvas().edges.find(edge => edge.id === event.target.dataset.musicEdgeRole);
          if (edge) {
            const oldRole = edge.inputRole || 'lyrics';
            incoming(node.id).filter(other => other.id !== edge.id && other.inputRole === event.target.value).forEach(other => { other.inputRole = oldRole; });
            edge.inputRole = event.target.value; saveState(); connections(s);
          }
        }
        if (event.target.matches('[data-music-add-source]') && event.target.value) { connectNodes(event.target.value, node.id, { quiet: true }); }
        if (event.target.matches('[data-music-abc-file]')) {
          const file = event.target.files?.[0]; event.target.value = '';
          if (file) try {
            if (file.size > 131072) throw new Error('ABC 文件上限 128 KB');
            const value = await file.text(); if (!live(s)) return; node.abc = value; syncEditor(s); saveState(); graphChanged();
          } catch (err) { error(s, err.message); }
        }
      }, options);
      const editor = el.querySelector('[data-music-field="abc"]');
      editor?.addEventListener('scroll', () => { el.querySelector('[data-music-lines]').scrollTop = editor.scrollTop; }, options);
      syncEditor(s); connections(s); paintJob(s); refreshScore(s); refreshCompare(s);
      if (node.jobId) poll(s);
    }
    function dispose(id) {
      const s = sessions.get(id); if (!s) return;
      sessions.delete(id); s.submission?.abort.abort(); notifyWaiters(s, new Error('上游转谱节点已移除'));
      s.abort.abort(); clearTimeout(s.timer); clearTimeout(s.saveTimer); releaseCompare(s);
      syncProgressClock();
    }
    function disposeAll() { [...sessions.keys()].forEach(dispose); }
    function reconcile() {
      [...sessions.values()].forEach(s => { if (!live(s)) dispose(s.id); });
      Object.values(getCanvas().nodes || {}).filter(n => model.TYPES.includes(n.type)).forEach(mount);
    }
    function graphChanged() {
      sessions.forEach(s => {
        connections(s); refreshScore(s);
        if (s.node.type === 'music_compare') {
          const key = JSON.stringify(incoming(s.id).map(edge => {
            const n = getNodeState(edge.from) || {};
            return [edge.from, n.audioAssetId, n.mediaUrl, n.resultJobId, abcFor(n)];
          }));
          if (key !== s.compareKey) { s.compareKey = key; refreshCompare(s); }
        }
      });
    }
    function connected(fromId, toId) {
      const from = getNodeState(fromId), to = getNodeState(toId), s = sessions.get(toId);
      if (to?.type === 'music_abc' && abcFor(from)) { to.abc = abcFor(from); syncEditor(s); saveState(); }
      if (to?.type === 'audio') {
        const file = model.audioArtifact(from?.artifacts, from?.resultSpec);
        if (file) audio.setResult(to.id, { url: file.url, name: file.name.split('/').pop(), mime_type: file.mime_type || (file.name.endsWith('.wav') ? 'audio/wav' : 'audio/flac'), file_size: file.file_size, task_id: from.jobId }).catch(() => {});
      }
      graphChanged();
    }
    return Object.freeze({ nodeHtml: view.nodeHtml, reconcile, dispose, disposeAll, connected, graphChanged, getCancelableTasks,
      showStatus: id => { const s = sessions.get(id); if (s) report(s, true); },
      run: id => { const s = sessions.get(id); return s ? run(s) : Promise.reject(new Error('音乐节点不存在')); },
      connections: { targets: model.TARGETS, policy: model.policy, changed: connected, removed: graphChanged } });
  }
  window.DesktopCanvasMusic = Object.freeze({ create });
})();
