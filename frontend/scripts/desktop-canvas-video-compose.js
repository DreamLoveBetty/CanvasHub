// Video-compose controller: owns compose node sessions (card preview, render jobs, polling), the
// one shared workbench and the clip/music inputs read from connected nodes. Clips follow the
// video edges into the node (order and trims live on the node); one audio node is the music.
// The rendered MP4 stays on the node (mediaUrl) and its output port feeds downstream video
// consumers. Transport: desktop-video-edit-api.js; markup: desktop-video-compose-view.js; subtitle
// panel, cue editor and caption overlay: desktop-video-compose-subtitle-panel.js.
(function () {
  const POLL_MS = 1000;
  const MUSIC_PATHS = Object.freeze(['/api/assets/audio/file', '/api/audio/artifact']);

  function create({model, view, api, asr, players, timelines, subtitles, subtitlePanels, autosubs, beatfits, helpers, escapeHtml, stateIcon, progressView,
    getCanvas, getNodeState, getNodeElement, getAudioInput, uploadAudio, fetchBlob, getAudioPeaks = null, mediaUrl = url => url,
    saveState, reportStatus, showMessage, onResult = () => {}}) {
    const sessions = new Map(), submissions = new Set();
    const probes = new Map();   // source url -> {promise, value, error}
    const thumbs = new Map();   // url|tiles -> Promise<object URL>
    const musicBlobs = new Map(); // audioAssetId -> object URL for the draft preview
    const archivePeaks = new Map(); // archive audio path -> peaks[] once loaded, or the pending Promise
    const musicBeats = new Map(); // music key -> {tempo, beats, failed} once analyzed, or the pending Promise
    const SNAP_KEY = 'desk-video-compose-snap-beats';
    const beatfit = beatfits.create({model});
    let snapBeats = (() => { try { return window.localStorage.getItem(SNAP_KEY) !== 'off'; } catch (_error) { return true; } })();
    let bench = null;           // {root, s, player, timeline, panel, view, selected, cue}
    let saveTimer = 0;
    // Draft caption overlay on the card and workbench previews (renders burn the cues in).
    const captions = subtitlePanels.createCaptions({subtitles, loadFonts: () => api.compose.subtitleFonts()});
    captions.onFonts(() => {
      sessions.forEach(s => { if (live(s)) captions.paint(q(s.el, '[data-compose-caption]'), s.node.subtitles, s.mini.time(), !s.node.result); });
      if (bench?.s) paintCaption(bench.player.time());
    });

    const live = s => sessions.get(s.id) === s && getNodeState(s.id) === s.node && getNodeElement(s.id) === s.el;
    const edgesInto = id => (getCanvas().edges || []).filter(edge => edge.to === id);
    const q = (root, selector) => root.querySelector(selector);

    // ----- inputs ------------------------------------------------------------------------------
    const videoInputs = s => edgesInto(s.id).map(edge => getNodeState(edge.from)).filter(node => node?.type === 'video');
    const musicNode = s => edgesInto(s.id).map(edge => getNodeState(edge.from)).filter(node => node?.type === 'audio').pop() || null;
    const nameOf = node => String(node?.mediaName || '').trim() || String(node?.mediaUrl || '').split(/[?#]/, 1)[0].split('/').pop() || '视频';

    function sourcesOf(s) {
      const sources = {};
      videoInputs(s).forEach(node => {
        sources[node.id] = {url: api.sourceUrl(node.mediaUrl || node.videoUrl || ''), name: nameOf(node), node};
      });
      return sources;
    }

    function probe(url) {
      if (!url) return null;
      let entry = probes.get(url);
      if (!entry) {
        entry = {promise: null, value: null, error: ''};
        probes.set(url, entry);
        entry.promise = api.probe(url).then(info => {
          if (!info.frameCount) throw new Error('无法读取视频帧');
          entry.value = info;
        }).catch(error => { entry.error = error.message || '读取视频失败'; })
          .finally(() => sessions.forEach(s => { if (Object.values(sourcesOf(s)).some(source => source.url === url)) refresh(s); }));
      }
      return entry;
    }

    function filmstrip(url, tiles) {
      const key = url + '|' + tiles;
      if (!thumbs.has(key)) {
        thumbs.set(key, api.filmstrip(url, tiles).then(blob => URL.createObjectURL(blob)).catch(error => {
          thumbs.delete(key);
          throw error;
        }));
      }
      return thumbs.get(key);
    }

    // Clip views in node order: probe facts, trims and why a clip cannot render yet.
    function clipViews(s, sources = sourcesOf(s)) {
      return s.node.clips.map(clip => {
        const source = sources[clip.sourceId];
        const entry = probe(source?.url);
        const error = !source ? '视频节点已断开' : !source.url ? (source.node.mediaUrl ? '该来源不支持合成，请先保存到作品库' : '视频节点还没有内容')
          : entry?.error || '';
        return {key: clip.sourceId, label: source?.name || '视频', url: source?.url || '', probe: error ? null : entry?.value || null,
          startFrame: clip.startFrame, endFrame: clip.endFrame, audio: clip.audio, hasAudio: Boolean(entry?.value?.hasAudio),
          speed: clip.speed, transition: clip.transition, error};
      });
    }

    function windows(clips) {
      return clips.map(clip => clip.probe ? model.clipWindow(clip.probe, clip.startFrame, clip.endFrame) : null);
    }

    // Audio nodes only decode local files; archived audio has server-side peaks.
    function peaksFor(node) {
      if (node.peaks?.length) return node.peaks;
      let path = '';
      try {
        const url = new URL(String(node.mediaUrl || ''), window.location.href);
        if (url.origin === window.location.origin && url.pathname === MUSIC_PATHS[0]) path = url.searchParams.get('path') || '';
      } catch (_error) { /* not an archive URL */ }
      if (!path || !getAudioPeaks) return [];
      const cached = archivePeaks.get(path);
      if (Array.isArray(cached)) return cached;
      if (!cached) {
        archivePeaks.set(path, getAudioPeaks(path).then(result => {
          archivePeaks.set(path, Array.isArray(result?.peaks) ? result.peaks.map(v => Math.min(1, Math.max(0, Number(v) || 0))) : []);
          if (bench?.s) renderTimeline();
        }).catch(() => archivePeaks.set(path, [])));
      }
      return [];
    }

    function musicView(s) {
      const node = musicNode(s);
      if (!node || !(node.audioAssetId || node.mediaUrl)) return null;
      const key = node.audioAssetId || node.mediaUrl, beats = musicBeats.get(key);
      return {node, name: nameOf(node), seconds: Number(node.durationSeconds) || 0, peaks: peaksFor(node), key,
        tempo: beats?.tempo || 0, beats: beats?.beats || [], volume: s.node.music.volume, fadeIn: s.node.music.fadeIn, fadeOut: s.node.music.fadeOut};
    }

    // Everything the card and workbench show, computed once per paint.
    function snapshot(s) {
      const sources = sourcesOf(s), clips = clipViews(s, sources), wins = windows(clips), music = musicView(s);
      const timing = model.timing(clips, wins), seconds = timing.total;
      const first = clips.find(clip => clip.probe)?.probe || null;
      const ready = clips.length > 0 && clips.every(clip => clip.probe);
      const key = model.settingsKey(s.node, sources, music?.key || '');
      const result = s.node.result;
      return {sources, clips, wins, timing, music, seconds, ready, key, result, stale: Boolean(result) && result.key !== key,
        size: first ? model.outputSize(s.node.output, first) : null};
    }

    function musicPlayUrl(music) {
      if (!music) return '';
      if (!music.node.audioAssetId) return music.node.mediaUrl;
      const cached = musicBlobs.get(music.node.audioAssetId);
      if (cached) return cached;
      getAudioInput(music.node.id).then(input => {
        if (!input?.blob || musicBlobs.has(music.node.audioAssetId)) return;
        musicBlobs.set(music.node.audioAssetId, URL.createObjectURL(input.blob));
        sessions.forEach(s => { s.miniKey = ''; paint(s); });
        if (bench?.s) setPlayerPlan(bench.s);
      }).catch(() => {});
      return '';
    }

    // Each clip plays at its speed, less half of each transition overlap (source seconds = output × speed),
    // so the draft lasts as long as the render and cuts where each transition is halfway.
    function draftPlan(s, snap = snapshot(s)) {
      const music = snap.music;
      return {clipVolume: s.node.clipVolume,
        clips: snap.clips.map((clip, k) => {
          const win = snap.wins[k], segment = snap.timing.segments[k];
          return win ? {url: clip.url, speed: clip.speed, start: win.start + segment.head * clip.speed, end: win.stop - segment.tail * clip.speed,
            audio: clip.audio && clip.hasAudio, label: `第 ${k + 1} 段 · ${clip.label}`} : null;
        }).filter(Boolean),
        music: music ? {url: musicPlayUrl(music), seconds: music.seconds, volume: music.volume, fadeIn: music.fadeIn, fadeOut: music.fadeOut} : null};
    }

    const resultPlan = result => ({clipVolume: 1, music: null,
      clips: [{url: result.url, start: 0, end: result.durationSeconds || 0.04, audio: true, label: '成片'}]});

    // ----- feedback ----------------------------------------------------------------------------
    function feedback(s, error = '', force = false) {
      if (!live(s)) return;
      if (error) s.noticeError = error;
      const message = s.noticeError || '';
      const job = s.job, state = message ? 'failed' : s.pending ? 'submitting' : s.node.status;
      const label = model.labels[state] || '未合成';
      const summary = message ? '操作失败，点击查看详情' : job?.stage || label;
      const value = {message: `视频合成 · ${summary}`,
        tone: message || ['failed', 'interrupted'].includes(state) ? 'error' : state === 'succeeded' ? 'success' : 'info',
        task: {task_id: job?.id || '', node_id: s.id, node_title: `视频合成 · ${s.id.slice(-6)}`, operation_label: '视频合成',
          status: state === 'running' ? 'processing' : state === 'cancelled' ? 'canceled' : state, status_label: label,
          provider_route: 'video_compose_local', detail_title: '视频合成日志', stage: summary, progress_text: summary,
          raw_detail: JSON.stringify({status: state, stage: job?.stage || summary, summary: job?.summary || null,
            result: job?.result || null}, null, 2) + (message || job?.error ? '\n\n' + (message || job.error) : '')}};
      const key = JSON.stringify(value);
      if (!force && key === s.lastFeedback) return;
      s.lastFeedback = key;
      reportStatus(value);
    }

    // ----- card --------------------------------------------------------------------------------
    function badgeFor(s, snap) {
      const busy = Boolean(s.pending) || model.active(s.node.status);
      if (busy) return {text: s.pending ? '提交中' : model.labels[s.node.status], tone: 'is-busy'};
      if (snap.result) return snap.stale ? {text: '成片 · 设定已改', tone: 'is-stale'} : {text: '成片 ✓', tone: 'is-result'};
      if (['failed', 'interrupted'].includes(s.node.status)) return {text: model.labels[s.node.status], tone: 'is-error'};
      return {text: '未合成', tone: ''};
    }

    function blocker(s, snap, {subtitles: checkSubtitles = true} = {}) {
      if (!snap.clips.length) return '请先连接视频节点';
      const broken = snap.clips.findIndex(clip => clip.error);
      if (broken >= 0) return `第 ${broken + 1} 段：${snap.clips[broken].error}`;
      if (!snap.ready) return '正在读取片段信息…';
      const short = snap.timing.lengths.findIndex(length => length < model.MIN_CLIP_SECONDS - 1e-6);
      if (short >= 0) return `第 ${short + 1} 段变速后不足 ${model.MIN_CLIP_SECONDS} 秒，请放宽裁切或降低倍速`;
      if (snap.seconds > model.MAX_SECONDS + 1e-6) return `成片超过 3 分钟（${snap.seconds.toFixed(1)} 秒），请裁短或减少片段`;
      return checkSubtitles ? subtitles.blocker(s.node.subtitles, snap.seconds) : '';
    }

    // The frame letterboxes inside its box at the output's shape (see the container-query sizing in CSS).
    function frameShape(frame, size, fit) {
      frame.dataset.fit = fit;
      if (size?.width && size?.height) frame.style.setProperty('--desk-video-compose-ratio', (size.width / size.height).toFixed(4));
      else frame.style.removeProperty('--desk-video-compose-ratio');
    }

    function stripHtml(snap) {
      return snap.clips.map((clip, k) => {
        const win = snap.wins[k];
        if (!win) return `<i class="is-pending" style="flex:1"><b>${k + 1}</b></i>`;
        const tiles = timelines.tilesFor(clip.probe.durationSeconds || 0);
        const strip = thumbs.get(clip.url + '|' + tiles);
        if (!strip) filmstrip(clip.url, tiles).then(() => sessions.forEach(paint)).catch(() => {});
        const tile = Math.min(tiles - 1, Math.floor(win.startFrame * tiles / clip.probe.frameTimes.length));
        return `<i style="flex:${snap.timing.segments[k].length.toFixed(3)}" data-tile="${tile}" data-tiles="${tiles}" data-key="${escapeHtml(clip.url + '|' + tiles)}"><b>${k + 1}</b></i>`;
      }).join('');
    }

    // Tile backgrounds resolve from the shared filmstrip cache once loaded.
    async function paintStripTiles(container) {
      const height = container.clientHeight || 22;
      for (const item of container.querySelectorAll('i[data-key]')) {
        const promise = thumbs.get(item.dataset.key);
        if (!promise) continue;
        const url = await promise.catch(() => '');
        if (!url || !item.isConnected) continue;
        const probeInfo = probes.get(item.dataset.key.split('|')[0])?.value;
        const tileW = height * (probeInfo?.width || 16) / Math.max(1, probeInfo?.height || 9);
        const tiles = Number(item.dataset.tiles), tile = Number(item.dataset.tile);
        item.style.backgroundImage = `url(${url})`;
        item.style.backgroundSize = `${(tiles * tileW).toFixed(1)}px 100%`;
        item.style.backgroundPosition = `${(-tile * tileW).toFixed(1)}px 0`;
      }
    }

    function paint(s) {
      if (!live(s)) return;
      const snap = snapshot(s), el = s.el;
      const badge = badgeFor(s, snap);
      const badgeEl = q(el, '[data-compose-badge]');
      badgeEl.textContent = badge.text;
      badgeEl.className = `desk-video-compose__badge ${badge.tone}`.trim();
      const showResult = Boolean(snap.result);
      const size = showResult ? {width: snap.result.width, height: snap.result.height} : snap.size;
      frameShape(q(el, '[data-compose-frame]'), size, showResult ? 'crop' : s.node.output.fit);
      q(el, '[data-compose-dims]').textContent = size ? `${size.width}×${size.height}` : '';
      q(el, '[data-compose-empty]').hidden = snap.clips.length > 0 || showResult;
      q(el, '[data-compose-play]').hidden = !(showResult || snap.wins.some(Boolean));
      const strip = q(el, '[data-compose-strip]');
      const stripMarkup = stripHtml(snap);
      if (strip.dataset.markup !== stripMarkup) { strip.dataset.markup = stripMarkup; strip.innerHTML = stripMarkup; }
      paintStripTiles(strip);
      q(el, '[data-compose-meta]').innerHTML = view.metaHtml({clips: snap.clips.length, seconds: snap.seconds, size: snap.size,
        music: Boolean(snap.music)});
      paintRun(s, snap, q(el, '[data-compose-run]'));
      const busy = Boolean(s.pending) || model.active(s.node.status);
      const job = s.job;
      const progress = q(el, '[data-compose-progress]');
      progress.hidden = !busy;
      progressView?.update(progress, {visible: busy, running: busy, taskId: s.pending ? '' : job?.id,
        percent: s.pending ? null : job?.progress_percent ?? null, title: s.pending ? '提交合成…' : job?.stage || model.labels[s.node.status],
        detail: '视频合成', startedAt: s.pending ? 0 : job?.created_at, finishedAt: null}, el);
      // Mini preview: the finished video when there is one, else the draft.
      const planKey = showResult ? 'result:' + snap.result.url : 'draft:' + snap.key + '|' + snap.ready;
      if (s.miniKey !== planKey && !s.mini.isPlaying()) {
        s.miniKey = planKey;
        s.mini.setPlan(showResult ? resultPlan(snap.result) : draftPlan(s, snap));
        s.mini.seek(0);
      }
      if (bench?.s === s) paintBench(snap);
    }

    function paintRun(s, snap, button) {
      const busy = Boolean(s.pending) || model.active(s.node.status), reason = blocker(s, snap);
      const state = busy ? 'busy' : snap.result && !snap.stale ? 'succeeded' : ['failed', 'interrupted'].includes(s.node.status) ? 'failed' : 'idle';
      if (button.dataset.icon !== state) { stateIcon.paint(button.querySelector('svg'), state); button.dataset.icon = state; }
      const text = busy ? (s.pending ? '提交中' : model.labels[s.node.status]) : snap.result ? (snap.stale ? '重新合成' : '已合成')
        : ['failed', 'interrupted'].includes(s.node.status) ? '重试合成' : '合成';
      button.querySelector('span').textContent = text;
      button.disabled = busy || Boolean(reason);
      button.setAttribute('aria-busy', String(busy));
      button.setAttribute('aria-label', text);
      button.title = reason || (snap.result && !snap.stale ? '成片与当前设定一致，点击重新合成' : '在后台合成，收起工作台也会继续');
    }

    function refresh(s) {
      if (!live(s)) return;
      paint(s);
      if (bench?.s === s) { renderTimeline(); setPlayerPlan(s); }
    }

    // ----- workbench -----------------------------------------------------------------------------
    function ensureBench() {
      if (bench) return bench;
      const root = document.createElement('div');
      root.className = 'desk-video-compose-bench';
      root.hidden = true;
      root.innerHTML = view.benchHtml();
      document.body.appendChild(root);
      bench = {root, s: null, view: 'draft', selected: 0, cue: -1, player: null, timeline: null, panel: null};
      bench.player = players.create({frame: q(root, '[data-cb-frame]'), mediaUrl, onTick: paintClock});
      bench.timeline = timelines.create({root: q(root, '[data-cb-timeline]'), model, helpers, filmstrip, escapeHtml,
        onTrim(k, next, final) {
          const s = bench.s, clip = s?.node.clips[k];
          if (!clip) return;
          clip.startFrame = next.startFrame; clip.endFrame = next.endFrame;
          // While trimming the preview shows the cut frame (onShow); the timeline re-renders on release.
          bench.trimming = !final;
          if (final) bench.beatUndo = null; // a manual trim after a beat cut: undo would now overwrite it
          if (final) edited(s); else paintTotal(snapshot(s));
        },
        onMove(from, to) {
          const s = bench.s;
          if (s && model.moveClip(s.node, from, to)) { bench.selected = to; edited(s); }
        },
        onAudio(k, on) {
          const s = bench.s, clip = s?.node.clips[k];
          if (clip) { clip.audio = on; edited(s); }
        },
        onSelect(k) {
          bench.selected = k;
          bench.cue = -1;
          if (bench.view === 'result') setView('draft', false);
          renderTimeline();
          bench.player.show(k, 0);
        },
        onSeek(time) {
          if (bench.view === 'result') setView('draft', false);
          bench.player.stop();
          bench.player.seek(time);
        },
        onShow(k, source) {
          if (bench.view === 'result') setView('draft', false);
          bench.player.showSource(k, source);
        },
        onCueSelect: selectCue,
        onCueEdit(k, edge, start, end, final) {
          const s = bench.s;
          if (!s?.node.subtitles.cues[k]) return;
          const placed = subtitles.place(s.node.subtitles, k, edge, start, end, bench.timeline.total());
          if (!final) { paintSubtitles(); return; }
          bench.cue = k;
          subtitlesEdited(s, {final: true});
          bench.player.stop();
          bench.player.seek(edge === 'end' ? Math.max(placed.start, placed.end - 0.05) : placed.start);
        },
        onCueAdd: time => bench.panel.addAt(time),
      });
      bench.panel = subtitlePanels.create({root, subtitles, captions, escapeHtml, showMessage, clock: helpers.clock,
        getTime: () => bench.player.time(),
        onEdit: ({final}) => { if (bench.s) subtitlesEdited(bench.s, {final}); },
        onSelect: selectCue});
      bench.autosub = autosubs.create({root, api: api.compose, asr, showMessage, current: () => bench.s,
        request: autosubRequest, apply: applyAutosub});
      root.addEventListener('click', onBenchClick);
      root.addEventListener('input', onBenchInput);
      root.addEventListener('change', event => { if (bench.s && !bench.autosub.change(event) && !bench.panel.change(event)) saveState(); });
      root.addEventListener('keydown', onBenchKey);
      return bench;
    }

    function openBench(s) {
      if (!live(s)) return;
      ensureBench();
      if (bench.s && bench.s !== s) closeBench({restoreFocus: false});
      s.mini.stop();
      bench.s = s;
      bench.view = 'draft';
      bench.selected = 0;
      bench.cue = -1;
      bench.returnFocus = document.activeElement;
      bench.root.hidden = false;
      document.body.classList.add('desk-video-compose-open');
      q(bench.root, '.desk-video-compose-bench__dialog').focus();
      paint(s);
      renderTimeline();
      setPlayerPlan(s);
      bench.player.seek(0);
    }

    function closeBench({restoreFocus = true} = {}) {
      if (!bench || bench.root.hidden) return;
      const s = bench.s;
      bench.player.stop();
      bench.player.setPlan({clips: []});
      bench.root.hidden = true;
      bench.s = null;
      bench.beatUndo = null;
      document.body.classList.remove('desk-video-compose-open');
      if (restoreFocus && bench.returnFocus?.isConnected) bench.returnFocus.focus?.({preventScroll: true});
      bench.returnFocus = null;
      if (s) { s.miniKey = ''; paint(s); }
    }

    // keep: re-show the same timeline position under the new plan (edits), else the caller seeks.
    function setPlayerPlan(s, {keep = false} = {}) {
      if (bench?.s !== s) return;
      const snap = snapshot(s), at = bench.player.time();
      if (bench.view === 'result' && snap.result) bench.player.setPlan(resultPlan(snap.result));
      else bench.player.setPlan(draftPlan(s, snap));
      if (keep) bench.player.seek(Math.min(at, Math.max(0, bench.player.total() - 0.001)));
      const size = bench.view === 'result' && snap.result ? {width: snap.result.width, height: snap.result.height} : snap.size;
      frameShape(q(bench.root, '[data-cb-frame]'), size, bench.view === 'result' ? 'crop' : s.node.output.fit);
      paintClock(0, 0);
    }

    function setView(next, seek = true) {
      if (!bench?.s) return;
      bench.view = next === 'result' && bench.s.node.result ? 'result' : 'draft';
      setPlayerPlan(bench.s);
      paintBench(snapshot(bench.s));
      if (seek) bench.player.seek(0);
    }

    function renderTimeline() {
      const s = bench?.s;
      if (!s) return;
      const snap = snapshot(s);
      bench.selected = Math.min(bench.selected, Math.max(0, snap.clips.length - 1));
      bench.cue = Math.min(bench.cue, s.node.subtitles.cues.length - 1);
      requestBeats(s, snap.music);
      paintSnap(snap.music);
      paintBeatFit(snap);
      bench.timeline.render({clips: snap.clips, music: snap.music, snap: snapBeats, selected: bench.cue >= 0 ? -1 : bench.selected,
        cues: s.node.subtitles.cues, cue: bench.cue});
      bench.timeline.setTime(bench.view === 'draft' ? bench.player.time() : null);
      paintClipBar(snap);
      paintSubtitles(snap.seconds);
    }

    // ----- beat snapping -------------------------------------------------------------------------
    // Analyzed once per music source while the workbench is open (a local file is uploaded the way
    // compose would upload it); failures just leave the lane without ticks.
    function requestBeats(s, music) {
      if (!music || musicBeats.has(music.key)) return;
      const key = music.key;
      musicBeats.set(key, musicInput(s, music)
        .then(input => api.compose.musicBeats(input))
        .then(result => musicBeats.set(key, result))
        .catch(() => musicBeats.set(key, {tempo: 0, beats: [], failed: true}))
        .finally(() => { if (bench?.s) renderTimeline(); }));
    }

    function paintSnap(music) {
      const button = q(bench.root, '[data-cb-snap]'), state = music ? musicBeats.get(music.key) : null;
      const pending = state instanceof Promise, count = pending ? 0 : state?.beats?.length || 0;
      button.disabled = !count;
      button.setAttribute('aria-pressed', String(snapBeats && count > 0));
      button.title = !music ? '连接配乐后可用' : pending ? '正在分析配乐节拍…' : !count
        ? (state?.failed ? '节拍分析失败' : '这段配乐没有检测到明显节拍')
        : `${snapBeats ? '已开启' : '已关闭'}：拖动片段两端把手时，片段结尾吸附到附近的节拍或配乐结尾（${state.beats[0].toFixed(1)}–${state.beats[count - 1].toFixed(1)} 秒有节拍）`;
    }

    // Beats the music actually plays (the analysis can run past a shorter music node).
    function playedBeats(music) {
      const state = music ? musicBeats.get(music.key) : null;
      if (!state || state instanceof Promise) return [];
      return music.seconds > 0 ? state.beats.filter(beat => beat < music.seconds) : state.beats;
    }

    function paintBeatFit(snap) {
      const group = q(bench.root, '[data-cb-beatfit]'), beats = playedBeats(snap.music);
      const ready = beats.length > 0 && snap.clips.some(clip => clip.probe);
      group.querySelectorAll('button:not([data-value="undo"])').forEach(button => { button.disabled = !ready; });
      q(group, '[data-value="undo"]').hidden = bench.beatUndo?.s !== bench.s;
    }

    // One click: every clip's out point moves so it ends on a beat (in points stay). Undo restores
    // the out points by source, so a reorder in between does not scramble them.
    function fitToBeats(s, mode) {
      const snap = snapshot(s), beats = playedBeats(snap.music);
      if (!beats.length) { showMessage('配乐还没有可用的节拍'); return; }
      const result = beatfit.plan(snap.clips, beats, mode);
      if (!result.aligned) { showMessage('没有片段能对上节拍：片段比第一个节拍还短，或已在配乐结束之后'); return; }
      bench.beatUndo = {s, ends: new Map(s.node.clips.map(clip => [clip.sourceId, clip.endFrame]))};
      result.ends.forEach((end, k) => { if (end !== undefined) s.node.clips[k].endFrame = end; });
      edited(s);
      const notes = [];
      if (result.short.length) notes.push(`第 ${result.short.map(k => k + 1).join('、')} 段素材不够长，停在能到的最后一拍`);
      if (result.missed.length) notes.push(`第 ${result.missed.map(k => k + 1).join('、')} 段附近没有节拍，保持原样`);
      showMessage(`已按节拍裁切：${result.aligned} 段结尾落在节拍上${notes.length ? '；' + notes.join('；') : ''}`);
    }

    function undoBeatFit(s) {
      const undo = bench.beatUndo;
      if (undo?.s !== s) return;
      s.node.clips.forEach(clip => { if (undo.ends.has(clip.sourceId)) clip.endFrame = undo.ends.get(clip.sourceId); });
      bench.beatUndo = null;
      edited(s);
      showMessage('已恢复按节拍裁切之前的出点');
    }

    function toggleSnap() {
      snapBeats = !snapBeats;
      try { window.localStorage.setItem(SNAP_KEY, snapBeats ? 'on' : 'off'); } catch (_error) { /* per-viewer convenience only */ }
      renderTimeline();
    }

    // ----- subtitles -----------------------------------------------------------------------------
    function paintSubtitles(total = bench.timeline.total()) {
      bench.panel.paint({node: bench.s.node, total, cue: bench.cue});
      bench.autosub.paint();
    }

    // Automatic subtitles recognize the clips' own sound on the same timeline the render uses; the
    // current cues may be invalid (they are what gets replaced), music is not sent.
    function autosubRequest(s) {
      if (!live(s)) return {reason: '节点已不存在'};
      const snap = snapshot(s), reason = blocker(s, snap, {subtitles: false});
      if (reason) return {reason};
      if (!snap.clips.some(clip => clip.audio && clip.hasAudio)) return {reason: '所有片段都已静音或没有音轨，没有可识别的原声'};
      return {body: model.request(s.node, snap.sources, null)};
    }

    function applyAutosub(s, cues) {
      if (!live(s)) return false;
      s.node.subtitles.cues = subtitles.normalize({...s.node.subtitles, cues}).cues;
      if (bench?.s === s) bench.cue = -1;
      subtitlesEdited(s, {final: true});
      if (bench?.s === s) renderTimeline();
      return true;
    }

    function paintCaption(time) {
      captions.paint(q(bench.root, '[data-cb-frame] [data-compose-caption]'), bench.s.node.subtitles, time, bench.view === 'draft');
    }

    // A cue (k >= 0) is selected instead of a clip: its editor replaces the clip bar and the preview jumps to it.
    function selectCue(k) {
      const s = bench?.s, cue = s?.node.subtitles.cues[k];
      bench.cue = cue ? k : -1;
      if (cue && bench.view === 'result') setView('draft', false);
      if (cue) { bench.player.stop(); bench.player.seek(cue.start); }
      bench.timeline.renderCues(s.node.subtitles.cues, bench.cue, bench.cue >= 0 ? -1 : bench.selected);
      paintClipBar(snapshot(s));
      paintSubtitles();
    }

    // Subtitle edits change the render but not the draft plan: repaint cues, captions and the run state.
    // Typing saves after a pause; every other edit saves at once.
    function subtitlesEdited(s, {final}) {
      clearTimeout(saveTimer);
      if (final) saveState(); else saveTimer = setTimeout(saveState, 600);
      if (bench?.s === s) {
        if (bench.view === 'result') setView('draft', false);
        bench.cue = Math.min(bench.cue, s.node.subtitles.cues.length - 1);
        bench.timeline.renderCues(s.node.subtitles.cues, bench.cue, bench.cue >= 0 ? -1 : bench.selected);
        paintClipBar(snapshot(s));
        paintSubtitles();
        paintCaption(bench.player.time());
      }
      paint(s);
    }

    // Speed and the transition into the next clip, for the selected clip.
    function paintClipBar(snap) {
      const root = bench.root, k = bench.selected, clip = bench.cue >= 0 ? null : bench.s.node.clips[k], viewClip = snap.clips[k];
      const bar = q(root, '[data-cb-clip]');
      bar.hidden = !clip;
      if (!clip) return;
      const last = k === snap.clips.length - 1, win = snap.wins[k];
      q(root, '[data-cb-clip-name]').textContent = `第 ${k + 1} 段`;
      const values = {speed: clip.speed, transition: clip.transition.type, transitionSeconds: clip.transition.duration};
      bar.querySelectorAll('[data-cb-clip-seg]').forEach(group => group.querySelectorAll('button').forEach(button => {
        const key = group.dataset.cbClipSeg, value = Number.isNaN(Number(button.dataset.value)) ? button.dataset.value : Number(button.dataset.value);
        button.setAttribute('aria-pressed', String(value === values[key]));
        // A speed that would leave the clip under the minimum is unavailable until it is trimmed longer.
        button.disabled = key === 'speed' ? Boolean(win) && win.seconds / value < model.MIN_CLIP_SECONDS - 1e-6
          : last || (key === 'transitionSeconds' && clip.transition.type === 'none');
      }));
      const cut = snap.timing.cuts[k] || 0;
      q(root, '[data-cb-clip-note]').textContent = last ? '最后一段之后没有转场'
        : clip.transition.type === 'none' ? '' : cut + 1e-6 < clip.transition.duration
          ? `受片段长度限制为 ${cut.toFixed(2)} 秒` : `成片缩短 ${cut.toFixed(2)} 秒`;
      if (viewClip?.label) bar.title = viewClip.label;
    }

    // After any edit: save, return the preview to the draft and repaint everything that shows it.
    function edited(s, {timeline = true} = {}) {
      saveState();
      if (bench?.s === s) {
        if (bench.view === 'result') bench.view = 'draft';
        setPlayerPlan(s, {keep: !bench.trimming});
        if (timeline) renderTimeline();
      }
      s.miniKey = '';
      paint(s);
    }

    function paintClock(time, index) {
      if (!bench?.s) return;
      const playing = bench.player.isPlaying();
      const play = q(bench.root, '[data-cb-play]');
      if (play.dataset.icon !== String(playing)) {
        stateIcon.paint(play.querySelector('svg'), playing ? 'pause' : 'play');
        play.dataset.icon = String(playing);
        play.setAttribute('aria-label', playing ? '暂停' : '播放');
      }
      q(bench.root, '[data-cb-time]').textContent = helpers.clock(time);
      q(bench.root, '[data-cb-length]').textContent = '/ ' + helpers.clock(bench.player.total());
      const plan = bench.view === 'result' ? '成片' : `第 ${index + 1} 段`;
      q(bench.root, '[data-cb-label]').textContent = bench.player.total() ? plan : '';
      bench.timeline.setTime(bench.view === 'draft' ? time : null);
      paintCaption(time);
    }

    function paintTotal(snap) {
      const total = q(bench.root, '[data-cb-total]');
      total.textContent = `合计 ${snap.seconds.toFixed(2)} 秒 / 上限 3:00`;
      total.classList.toggle('is-over', snap.seconds > model.MAX_SECONDS + 1e-6);
    }

    function paintBench(snap) {
      const s = bench.s, root = bench.root, node = s.node;
      q(root, '[data-cb-name]').textContent = `${snap.clips.length} 段${snap.music ? ' · 配乐' : ''}`;
      paintTotal(snap);
      const size = bench.view === 'result' && snap.result ? snap.result : snap.size;
      q(root, '[data-cb-dims]').textContent = size ? `${bench.view === 'result' ? '成片 · ' : ''}${size.width}×${size.height} · ${bench.view === 'result' ? snap.result.fps || node.output.fps : node.output.fps}fps` : '';
      q(root, '[data-cb-size]').textContent = snap.size ? `${snap.size.width}×${snap.size.height}` : '';
      const empty = q(root, '[data-cb-empty]');
      empty.hidden = snap.clips.length > 0 && snap.ready;
      empty.textContent = !snap.clips.length ? '连接视频节点作为片段' : blocker(s, snap) || '';
      const music = snap.music;
      q(root, '[data-cb-music-name]').textContent = music ? music.name : '未连接音频节点';
      q(root, '[data-cb-music-note]').textContent = !music ? '' : !music.seconds ? '' : music.seconds > snap.seconds
        ? `配乐 ${music.seconds.toFixed(1)} 秒，于成片结尾截断${node.music.fadeOut ? '并淡出' : ''}`
        : `配乐在 ${music.seconds.toFixed(2)} 秒结束，之后只有原声`;
      const values = {fadeIn: node.music.fadeIn, fadeOut: node.music.fadeOut, ...node.output};
      root.querySelectorAll('[data-cb-seg]').forEach(group => group.querySelectorAll('button').forEach(button => {
        button.setAttribute('aria-pressed', String(String(button.dataset.value) === String(values[group.dataset.cbSeg])));
      }));
      const levels = {musicVolume: node.music.volume, clipVolume: node.clipVolume};
      root.querySelectorAll('[data-cb-range]').forEach(input => {
        const value = levels[input.dataset.cbRange];
        if (document.activeElement !== input) input.value = String(value);
        q(root, `[data-cb-output="${input.dataset.cbRange}"]`).textContent = `${Math.round(value * 100)}%`;
        input.disabled = input.dataset.cbRange === 'musicVolume' && !music;
      });
      root.querySelectorAll('[data-cb-seg="fadeIn"] button, [data-cb-seg="fadeOut"] button').forEach(button => { button.disabled = !music; });
      const viewGroup = q(root, '[data-cb-view]');
      viewGroup.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.value === bench.view)));
      q(viewGroup, '[data-value="result"]').disabled = !snap.result;
      const busy = Boolean(s.pending) || model.active(node.status);
      const run = q(root, '[data-cb-run]'), reason = blocker(s, snap);
      run.textContent = busy ? (s.pending ? '提交中…' : model.labels[node.status]) : snap.result ? (snap.stale ? '重新合成' : '再次合成') : '合成';
      run.disabled = busy || Boolean(reason);
      run.title = reason || '';
      q(root, '[data-cb-cancel]').hidden = !(busy && (s.pending || node.jobId));
      // The card carries the shared progress material; the workbench foot shows a plain bar.
      const percent = s.pending ? null : s.job?.progress_percent ?? null;
      q(root, '[data-cb-progress]').hidden = !busy;
      q(root, '[data-cb-progress]').classList.toggle('is-indeterminate', percent === null);
      q(root, '[data-cb-progress-bar]').style.width = `${percent === null ? 30 : Math.max(2, Math.min(100, percent))}%`;
      q(root, '[data-cb-progress-value]').textContent = percent === null ? '' : `${Math.round(percent)}%`;
      const status = q(root, '[data-cb-status]');
      status.classList.toggle('is-error', Boolean(s.noticeError) || ['failed', 'interrupted'].includes(node.status));
      status.classList.toggle('is-stale', !busy && snap.stale);
      if (busy) status.textContent = `${s.pending ? '提交合成…' : s.job?.stage || model.labels[node.status]} · 在后台执行，收起工作台也会继续`;
      else if (s.noticeError || node.status === 'failed') status.textContent = s.noticeError || s.job?.error || '合成失败';
      else if (node.status === 'interrupted') status.textContent = '服务重启，合成已中断，请重新合成';
      else if (snap.result) {
        const mb = snap.result.fileSize ? ` · ${(snap.result.fileSize / 1048576).toFixed(1)} MB` : '';
        status.textContent = `✓ ${snap.result.filename} · ${snap.result.width}×${snap.result.height} · ${snap.result.durationSeconds.toFixed(2)} 秒${mb}`
          + (snap.stale ? ' · 设定已改，成片仍是上一版' : ' · 已存入作品库');
      } else status.textContent = reason || '合成在后台执行，收起工作台也会继续；成片存入作品库并留在节点内，输出端口可接下游节点';
    }

    function onBenchClick(event) {
      const s = bench.s;
      if (!s) return;
      if (event.target.closest('[data-cb-close]')) { closeBench(); return; }
      if (event.target.closest('[data-cb-play]')) { bench.player.isPlaying() ? bench.player.stop() : bench.player.play(); return; }
      if (event.target.closest('[data-cb-run]')) { run(s.id); return; }
      if (event.target.closest('[data-cb-cancel]')) { cancel(s); return; }
      if (event.target.closest('[data-cb-snap]')) { toggleSnap(); return; }
      const fit = event.target.closest('[data-cb-beatfit] button');
      if (fit) { if (!fit.disabled) fit.dataset.value === 'undo' ? undoBeatFit(s) : fitToBeats(s, fit.dataset.value); return; }
      if (bench.autosub.click(event) || bench.panel.click(event)) return;
      const clipOption = event.target.closest('[data-cb-clip-seg] button');
      if (clipOption) {
        const clip = s.node.clips[bench.selected], key = clipOption.closest('[data-cb-clip-seg]').dataset.cbClipSeg;
        if (!clip || clipOption.disabled) return;
        if (key === 'speed') clip.speed = Number(clipOption.dataset.value);
        else if (key === 'transition') clip.transition.type = clipOption.dataset.value;
        else clip.transition.duration = Number(clipOption.dataset.value);
        model.normalize(s.node);
        edited(s);
        return;
      }
      const viewButton = event.target.closest('[data-cb-view] button');
      if (viewButton && !viewButton.disabled) { setView(viewButton.dataset.value); return; }
      const option = event.target.closest('[data-cb-seg] button');
      if (!option || option.disabled) return;
      const key = option.closest('[data-cb-seg]').dataset.cbSeg;
      const value = /^-?[\d.]+$/.test(option.dataset.value) ? Number(option.dataset.value) : option.dataset.value;
      if (key === 'fadeIn' || key === 'fadeOut') s.node.music[key] = value;
      else s.node.output[key] = value;
      model.normalize(s.node);
      if (key === 'fadeIn' || key === 'fadeOut') {
        bench.player.setLevels({clipVolume: s.node.clipVolume, music: {fadeIn: s.node.music.fadeIn, fadeOut: s.node.music.fadeOut}});
        saveState(); renderTimeline(); paint(s);
      } else edited(s, {timeline: false});
    }

    function onBenchInput(event) {
      if (bench.s && bench.panel.input(event)) return;
      const input = event.target.closest('[data-cb-range]');
      const s = bench.s;
      if (!input || !s) return;
      if (input.dataset.cbRange === 'musicVolume') s.node.music.volume = Number(input.value);
      else s.node.clipVolume = Number(input.value);
      model.normalize(s.node);
      bench.player.setLevels({clipVolume: s.node.clipVolume, music: {volume: s.node.music.volume}});
      if (input.dataset.cbRange === 'musicVolume') renderTimeline();
      paint(s);
    }

    function onBenchKey(event) {
      if (event.key === 'Escape') { event.preventDefault(); closeBench(); return; }
      if (bench.panel.key(event)) return;
      if (event.key === ' ' && !event.target.closest('button, input, textarea, select')) {
        event.preventDefault();
        bench.player.isPlaying() ? bench.player.stop() : bench.player.play();
      }
    }

    // ----- jobs ------------------------------------------------------------------------------
    function musicSourceUrl(value) {
      let url;
      try { url = new URL(String(value || ''), window.location.href); } catch (_error) { return ''; }
      if (url.origin !== window.location.origin || !MUSIC_PATHS.includes(url.pathname)) return '';
      url.searchParams.delete('miniappAuth');
      return url.pathname + url.search;
    }

    // Archive and audio-job URLs go by reference; local-only audio is uploaded once per source.
    async function musicInput(s, music) {
      if (!music) return null;
      const direct = musicSourceUrl(music.node.mediaUrl);
      if (direct) return {sourceUrl: direct, name: music.name};
      if (s.musicAsset?.key === music.key) return {assetId: s.musicAsset.assetId, name: music.name};
      const input = await getAudioInput(music.node.id);
      if (!input) throw new Error('配乐音频已丢失，请重新导入音频节点');
      const blob = input.blob || await fetchBlob(input.url);
      const asset = await uploadAudio(blob, music.name);
      if (!asset?.asset_id) throw new Error('配乐上传失败');
      s.musicAsset = {key: music.key, assetId: asset.asset_id};
      return {assetId: asset.asset_id, name: music.name};
    }

    async function poll(s) {
      clearTimeout(s.timer);
      const id = s.node.jobId, epoch = s.epoch || 0;
      if (!id || !live(s)) return;
      try {
        const job = await api.compose.job(id);
        if (!live(s) || s.node.jobId !== id || (s.epoch || 0) !== epoch) return;
        s.job = job;
        s.noticeError = '';
        const finished = job.status === 'succeeded' && s.node.result?.jobId !== job.id;
        s.node.status = job.status;
        if (finished) {
          s.node.result = model.resultFromJob(job, s.node.submittedKey);
          model.normalize(s.node);
          if (!s.node.result) s.node.status = 'failed';
          saveState();
          onResult(s.id);
          if (bench?.s === s && s.node.result) setView('result');
        }
        paint(s);
        feedback(s);
        if (model.active(job.status)) s.timer = setTimeout(() => poll(s), POLL_MS);
        else saveState();
      } catch (error) {
        if (!live(s) || s.node.jobId !== id || (s.epoch || 0) !== epoch) return;
        if (/不存在|过期/.test(error.message || '')) { s.node.status = 'interrupted'; s.node.jobId = ''; saveState(); }
        feedback(s, error.message);
        paint(s);
        if (model.active(s.node.status)) s.timer = setTimeout(() => poll(s), 3000);
      }
    }

    async function run(id) {
      const s = sessions.get(id);
      if (!s || !live(s) || s.pending || model.active(s.node.status)) return;
      const snap = snapshot(s), reason = blocker(s, snap);
      if (reason) { feedback(s, reason); paint(s); return; }
      s.noticeError = '';
      s.epoch = (s.epoch || 0) + 1;
      bench?.s === s && bench.player.stop();
      s.mini.stop();
      const op = {s, cancelled: false, jobId: ''};
      submissions.add(op);
      s.pending = op;
      s.job = null;
      paint(s);
      feedback(s);
      try {
        const music = await musicInput(s, snap.music);
        if (op.cancelled || !live(s)) return;
        const job = await api.compose.submit(model.request(s.node, snap.sources, music));
        op.jobId = job.id;
        if (op.cancelled || !live(s)) { await api.compose.cancel(job.id); return; }
        Object.assign(s.node, {jobId: job.id, status: job.status, submittedKey: snap.key});
        s.job = job;
        saveState();
      } catch (error) {
        if (live(s)) { s.node.status = op.cancelled ? 'cancelled' : 'failed'; feedback(s, error.message); }
      } finally {
        submissions.delete(op);
        if (s.pending === op) s.pending = null;
        if (live(s)) {
          if (op.cancelled) { s.node.status = 'cancelled'; feedback(s); }
          paint(s);
          saveState();
          if (op.jobId && !op.cancelled) poll(s);
        }
      }
    }

    async function cancel(s) {
      try {
        if (s.pending) { s.pending.cancelled = true; if (s.pending.jobId) await api.compose.cancel(s.pending.jobId); }
        else if (s.node.jobId && model.active(s.node.status)) await api.compose.cancel(s.node.jobId);
      } catch (error) { feedback(s, error.message); }
      if (live(s) && !s.pending) { s.node.status = 'cancelling'; paint(s); poll(s); }
    }

    // ----- lifecycle ------------------------------------------------------------------------------
    function sync(s) {
      if (model.syncClips(s.node, videoInputs(s).map(node => node.id))) saveState();
    }

    function mount(node) {
      const el = getNodeElement(node.id);
      if (!el || sessions.has(node.id)) return;
      model.normalize(node);
      const s = {id: node.id, node, el, abort: new AbortController(), miniKey: ''};
      s.mini = players.create({frame: q(el, '[data-compose-frame]'), mediaUrl, onTick: time => {
        captions.paint(q(el, '[data-compose-caption]'), s.node.subtitles, time, !s.node.result);
        const button = q(el, '[data-compose-play]'), playing = s.mini.isPlaying();
        if (button.dataset.icon === String(playing)) return;
        stateIcon.paint(button.querySelector('svg'), playing ? 'pause' : 'play');
        button.dataset.icon = String(playing);
        button.setAttribute('aria-label', playing ? '暂停预览' : '播放预览');
      }});
      sessions.set(node.id, s);
      const options = {signal: s.abort.signal};
      el.addEventListener('click', event => {
        if (event.target.closest('[data-compose-play]')) { event.stopPropagation(); s.mini.isPlaying() ? s.mini.stop() : s.mini.play(); }
        else if (event.target.closest('[data-compose-open]')) openBench(s);
        else if (event.target.closest('[data-compose-run]')) run(s.id);
      }, options);
      el.addEventListener('dblclick', event => {
        if (event.target.closest('[data-compose-preview]') && !event.target.closest('[data-compose-play]')) { event.stopPropagation(); openBench(s); }
      }, options);
      if (node.status === 'submitting' || node.status === 'cancelling' && !node.jobId) node.status = 'idle';
      sync(s);
      paint(s);
      if (node.jobId && (model.active(node.status) || (node.status === 'succeeded' && node.result?.jobId !== node.jobId))) poll(s);
    }

    function dispose(id, removed = false) {
      const s = sessions.get(id);
      if (!s) return;
      if (s.pending) s.pending.cancelled = true;
      if (removed && s.node.jobId && model.active(s.node.status)) api.compose.cancel(s.node.jobId).catch(() => {});
      if (bench?.s === s) closeBench({restoreFocus: false});
      sessions.delete(id);
      s.abort.abort();
      clearTimeout(s.timer);
      s.mini.destroy();
      progressView?.update(q(s.el, '[data-compose-progress]'), {visible: false});
      // Renders keep running across reloads; mount resumes polling from the persisted job id.
    }

    function disposeAll(removed = false) { [...sessions.keys()].forEach(id => dispose(id, removed)); }

    function reconcile() {
      [...sessions.values()].forEach(s => { if (!live(s)) dispose(s.id); });
      Object.values(getCanvas().nodes || {}).filter(node => node.type === model.TYPE).forEach(mount);
    }

    function graphChanged() {
      // A failed probe (backend restarting, file not saved yet) is retried after the graph changes.
      probes.forEach((entry, url) => { if (entry.error) probes.delete(url); });
      sessions.forEach(s => {
        if (!live(s)) return;
        sync(s);
        refresh(s);
      });
    }

    function getCancelableTasks() {
      const entries = [];
      sessions.forEach(s => {
        if (s.pending || model.active(s.node.status)) entries.push({kind: 'video_compose', key: `video_compose:${s.id}`, cancel: () => cancel(s)});
      });
      for (const op of submissions) {
        if (!sessions.has(op.s.id)) entries.push({kind: 'video_compose', key: `video_compose:pending:${op.s.id}`,
          cancel: async () => { op.cancelled = true; if (op.jobId) await api.compose.cancel(op.jobId); }});
      }
      return entries;
    }

    function connected(fromId, toId) {
      const from = getNodeState(fromId), to = getNodeState(toId);
      if (to?.type === model.TYPE && from?.type === 'video' && sessions.get(toId)) {
        const s = sessions.get(toId);
        sync(s);
        if (s.node.clips.length >= model.MAX_CLIPS && !s.node.clips.some(clip => clip.sourceId === fromId)) {
          showMessage(`合成节点最多 ${model.MAX_CLIPS} 段`);
        }
      }
      if (from?.type === model.TYPE && !from.mediaUrl) showMessage('合成完成后，成片会自动接入下游节点');
      graphChanged();
    }

    // A recipe reopen hands over the archived render: it is current for the rebuilt settings.
    function adopt(id, result) {
      const s = sessions.get(id);
      if (!s || !live(s)) return false;
      sync(s);
      const job = {result: {url: result.url, filename: result.filename, file_size: result.fileSize,
        duration_seconds: result.durationSeconds, width: result.width, height: result.height, fps: result.fps}};
      Object.assign(s.node, {result: model.resultFromJob(job, snapshot(s).key), status: 'succeeded', jobId: '', submittedKey: ''});
      model.normalize(s.node);
      s.miniKey = '';
      paint(s);
      saveState();
      onResult();
      return Boolean(s.node.result);
    }

    return Object.freeze({
      nodeHtml: view.html, mount, reconcile, dispose, disposeAll, graphChanged, run, getCancelableTasks, adopt,
      open: id => { const s = sessions.get(id); if (s) openBench(s); },
      showStatus: id => { const s = sessions.get(id); if (s?.job || s?.noticeError) feedback(s, '', true); },
      connections: Object.freeze({targets: model.targets, policy: model.policy, changed: connected, removed: graphChanged}),
    });
  }

  window.DesktopCanvasVideoCompose = Object.freeze({create});
})();
