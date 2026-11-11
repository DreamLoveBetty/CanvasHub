// Frame-picker workbench for video nodes: step frame by frame, mark frames, confirm scene cuts.
// Owns only transient modal state. Frame times come from the backend probe (every frame's real
// presentation time, VFR included); the player seeks to the midpoint between neighbouring
// frames, the same position the backend decodes, so the marked frame is the extracted frame.
// The timeline is time-based (filmstrip, ruler, marks and cuts share one time → % mapping).
// Jobs (scene detection) and node changes stay with the canvas controller (desktop-canvas-video-edit.js).
(function () {
  const MAX_MARKS = 20;
  const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  const ICON = Object.freeze({
    backSecond: '<path d="M12 7l-5 5 5 5M18.5 7l-5 5 5 5"/>',
    back: '<path d="M7 6v12M17 6l-6 6 6 6"/>',
    forward: '<path d="M17 6v12M7 6l6 6-6 6"/>',
    forwardSecond: '<path d="M5.5 7l5 5-5 5M12 7l5 5-5 5"/>',
    mark: '<path d="M7 4.5h10v15l-5-3.8-5 3.8z"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    scan: '<path d="M4 8.5V5h3.5M16.5 5H20v3.5M20 15.5V19h-3.5M7.5 19H4v-3.5M12 8v8"/>',
  });
  const PLAY_ICONS = Object.freeze({play: '<path d="m9 5 11 7-11 7z"/>', pause: '<path d="M7 5h3v14H7zM14 5h3v14h-3z"/>'});

  function bisectFrame(times, seconds) {
    let low = 0, high = times.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (times[middle] <= seconds + 1e-6) low = middle; else high = middle - 1;
    }
    return low;
  }

  // Player position that shows frame `n`: halfway to the next frame (or half a frame past the last).
  function seekTime(times, n, duration = 0) {
    if (!times.length) return 0;
    const index = Math.max(0, Math.min(times.length - 1, n));
    if (index + 1 < times.length) return (times[index] + times[index + 1]) / 2;
    const gap = index > 0 ? times[index] - times[index - 1] : 1 / 30;
    const end = duration > times[index] ? duration : times[index] + gap;
    return Math.min(times[index] + gap / 2, (times[index] + end) / 2);
  }

  function clock(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(value / 60);
    return `${String(minutes).padStart(2, '0')}:${(value - minutes * 60).toFixed(3).padStart(6, '0')}`;
  }

  // Smallest ruler step that keeps at most `maxLabels` labels across `span` seconds.
  function rulerStep(span, maxLabels = 8) {
    const value = Math.max(0, Number(span) || 0);
    return RULER_STEPS.find(step => value / step <= maxLabels) || RULER_STEPS[RULER_STEPS.length - 1];
  }

  function rulerLabel(seconds) {
    const minutes = Math.floor(seconds / 60), rest = seconds - minutes * 60;
    const text = Number.isInteger(rest) ? String(rest) : rest.toFixed(1);
    return `${minutes}:${text.padStart(Number.isInteger(rest) ? 2 : 4, '0')}`;
  }

  function create({api, escapeHtml, mediaUrl = url => url, showMessage = () => {}, stateIcon = window.DesktopStateIcon}) {
    const esc = value => escapeHtml(String(value ?? ''));
    const icon = (body, className = 'desk-video-frames__icon') => `<svg class="${className}" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
    let root = null, ctx = null, info = null, frame = 0, playing = false, returnFocus = null, openToken = 0;
    let marks = new Map(), scenes = [], scenesDetected = false, thumbs = new Map(), detecting = null, lastAdded = null;
    const q = selector => root?.querySelector(selector);
    const frameCount = () => info?.frameCount || 0;
    const step = () => Math.max(1, Math.round(info?.fps || 24));
    const span = () => {
      const times = info?.frameTimes || [];
      if (!times.length) return 1;
      const last = times[times.length - 1], gap = times.length > 1 ? last - times[times.length - 2] : 1 / 30;
      return Math.max(info.durationSeconds || 0, last + gap, 0.01);
    };
    // Every overlay on the timeline shares this mapping: the centre of frame n's display interval.
    const percent = n => Math.max(0, Math.min(100, seekTime(info.frameTimes, n, info.durationSeconds) / span() * 100));

    function ensureRoot() {
      if (root) return;
      root = document.createElement('div');
      root.className = 'desk-video-frames';
      root.hidden = true;
      root.innerHTML = `<div class="desk-video-frames__scrim" data-vf-close></div>
        <section class="desk-video-frames__dialog" role="dialog" aria-modal="true" aria-labelledby="deskVideoFramesTitle" tabindex="-1">
          <header class="desk-video-frames__head">
            <div class="desk-video-frames__title"><strong id="deskVideoFramesTitle">抽帧</strong><span data-vf-name></span></div>
            <div class="desk-video-frames__meta" data-vf-meta></div>
            <button type="button" class="desk-video-frames__close" data-vf-close aria-label="关闭抽帧工作台" title="关闭（Esc）">${icon(ICON.close)}</button>
          </header>
          <div class="desk-video-frames__body">
            <div class="desk-video-frames__main">
              <div class="desk-video-frames__screen"><video data-vf-video playsinline preload="auto"></video>
                <div class="desk-video-frames__badges">
                  <span class="desk-video-frames__badge is-mark" data-vf-badge="mark" hidden>${icon(ICON.mark)}已标记</span>
                  <span class="desk-video-frames__badge is-cut" data-vf-badge="cut" hidden>场景切换点</span>
                </div>
                <div class="desk-video-frames__loading" data-vf-loading>读取帧信息…</div></div>
              <div class="desk-video-frames__transport">
                <div class="desk-video-frames__clock"><b data-vf-time>00:00.000</b><span data-vf-frame>帧 — / —</span></div>
                <div class="desk-video-frames__controls">
                  <button type="button" data-vf-step="-second" aria-label="后退 1 秒" title="后退 1 秒（Shift+←）">${icon(ICON.backSecond)}</button>
                  <button type="button" data-vf-step="-1" aria-label="上一帧" title="上一帧（←）">${icon(ICON.back)}</button>
                  <button type="button" class="desk-video-frames__play" data-vf-play aria-label="播放" title="播放／暂停（空格）">${stateIcon.html(PLAY_ICONS, 'play')}</button>
                  <button type="button" data-vf-step="1" aria-label="下一帧" title="下一帧（→）">${icon(ICON.forward)}</button>
                  <button type="button" data-vf-step="second" aria-label="前进 1 秒" title="前进 1 秒（Shift+→）">${icon(ICON.forwardSecond)}</button>
                </div>
                <button type="button" class="desk-video-frames__mark-button" data-vf-mark aria-pressed="false">${icon(ICON.mark)}<span data-vf-mark-label>标记此帧</span><kbd>M</kbd></button>
              </div>
              <div class="desk-video-frames__timeline">
                <div class="desk-video-frames__track" data-vf-track role="slider" tabindex="0" aria-label="帧位置" aria-valuemin="1">
                  <div class="desk-video-frames__filmstrip" data-vf-filmstrip></div>
                  <div class="desk-video-frames__markers" data-vf-markers></div>
                  <div class="desk-video-frames__playhead" data-vf-head><span></span></div>
                </div>
                <div class="desk-video-frames__ruler" data-vf-ruler aria-hidden="true"></div>
              </div>
            </div>
            <aside class="desk-video-frames__side">
              <section class="desk-video-frames__panel">
                <header class="desk-video-frames__panel-head"><h3>场景切换</h3><small data-vf-scene-count></small>
                  <button type="button" class="desk-video-frames__detect" data-vf-detect>${icon(ICON.scan)}<span>侦测</span></button></header>
                <div class="desk-video-frames__scenes" data-vf-scenes></div>
              </section>
              <section class="desk-video-frames__panel is-marks">
                <header class="desk-video-frames__panel-head"><h3>已标记</h3><small data-vf-count>0 / ${MAX_MARKS}</small></header>
                <ol class="desk-video-frames__marks" data-vf-marks></ol>
              </section>
            </aside>
          </div>
          <footer class="desk-video-frames__foot">
            <p class="desk-video-frames__keys"><span><kbd>←</kbd><kbd>→</kbd>逐帧</span><span><kbd>⇧</kbd><kbd>←</kbd><kbd>→</kbd>1 秒</span><span><kbd>M</kbd>标记</span><span><kbd>空格</kbd>播放</span></p>
            <button type="button" class="desk-video-frames__cancel" data-vf-close>取消</button>
            <button type="button" class="desk-video-frames__extract" data-vf-extract disabled
              title="按帧号抽取原尺寸无损 PNG，存入作品库并生成图片节点">抽出 0 帧</button>
          </footer>
        </section>`;
      document.body.appendChild(root);
      const video = q('[data-vf-video]');
      video.addEventListener('play', () => { playing = true; tick(); paintReadout(); });
      video.addEventListener('pause', () => { playing = false; syncFromVideo(); });
      video.addEventListener('ended', () => { playing = false; paintReadout(); });
      root.addEventListener('click', onClick);
      root.addEventListener('change', onChange);
      root.addEventListener('keydown', onKey);
      const track = q('[data-vf-track]');
      track.addEventListener('pointerdown', event => {
        if (!info) return;
        const go = move => {
          const rect = track.getBoundingClientRect();
          const share = Math.max(0, Math.min(1, (move.clientX - rect.left) / Math.max(1, rect.width)));
          seekFrame(bisectFrame(info.frameTimes, share * span()));
        };
        track.setPointerCapture(event.pointerId);
        root.classList.add('is-scrubbing');
        go(event);
        const up = () => {
          root.classList.remove('is-scrubbing');
          track.removeEventListener('pointermove', go); track.removeEventListener('pointerup', up); track.removeEventListener('pointercancel', up);
        };
        track.addEventListener('pointermove', go);
        track.addEventListener('pointerup', up);
        track.addEventListener('pointercancel', up);
      });
    }

    function tick() {
      if (!playing || !info) return;
      syncFromVideo();
      window.requestAnimationFrame(tick);
    }

    function syncFromVideo() {
      if (!info) return;
      frame = bisectFrame(info.frameTimes, q('[data-vf-video]').currentTime);
      paintReadout();
    }

    function seekFrame(n) {
      if (!info) return;
      const video = q('[data-vf-video]');
      video.pause();
      frame = Math.max(0, Math.min(frameCount() - 1, Math.round(n)));
      video.currentTime = seekTime(info.frameTimes, frame, info.durationSeconds);
      paintReadout();
    }

    function paintReadout() {
      if (!root || !info) return;
      const count = frameCount(), marked = marks.has(frame);
      const isCut = scenes.some(item => item.frame === frame);
      q('[data-vf-time]').textContent = clock(info.frameTimes[frame]);
      q('[data-vf-frame]').textContent = `帧 ${frame + 1} / ${count}`;
      q('[data-vf-badge="mark"]').hidden = !marked;
      q('[data-vf-badge="cut"]').hidden = !isCut;
      q('[data-vf-head]').style.left = percent(frame) + '%';
      const track = q('[data-vf-track]');
      track.setAttribute('aria-valuemax', String(count));
      track.setAttribute('aria-valuenow', String(frame + 1));
      track.setAttribute('aria-valuetext', `第 ${frame + 1} 帧，${clock(info.frameTimes[frame])}`);
      const markButton = q('[data-vf-mark]');
      markButton.setAttribute('aria-pressed', String(marked));
      q('[data-vf-mark-label]').textContent = marked ? '取消标记' : '标记此帧';
      const play = q('[data-vf-play]');
      play.setAttribute('aria-label', playing ? '暂停' : '播放');
      stateIcon.paint(play.querySelector('svg'), playing ? 'pause' : 'play');
      root.querySelectorAll('[data-vf-marks] [data-vf-frame-item]').forEach(item => {
        item.classList.toggle('is-current', Number(item.dataset.vfFrameItem) === frame);
      });
      root.querySelectorAll('[data-vf-scene-row]').forEach(row => {
        row.classList.toggle('is-current', Number(row.dataset.vfSceneRow) === frame);
      });
    }

    function paintRuler() {
      const total = span(), every = rulerStep(total);
      const ticks = [];
      for (let t = 0; t <= total + 1e-6 && ticks.length < 40; t += every) {
        const left = t / total * 100;
        if (left > 94 && t > 0) break;
        ticks.push(`<span style="left:${left.toFixed(3)}%">${rulerLabel(Math.round(t * 10) / 10)}</span>`);
      }
      q('[data-vf-ruler]').innerHTML = ticks.join('');
    }

    async function buildFilmstrip(token) {
      const container = q('[data-vf-filmstrip]');
      const width = container.getBoundingClientRect().width || 720;
      const height = container.getBoundingClientRect().height || 56;
      const tiles = Math.max(6, Math.min(16, Math.round(width / 84)));
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      const tileWidth = Math.round(width / tiles * ratio), tileHeight = Math.round(height * ratio);
      container.classList.remove('is-unavailable');
      container.innerHTML = Array.from({length: tiles}, () => `<canvas width="${tileWidth}" height="${tileHeight}"></canvas>`).join('');
      const canvases = [...container.querySelectorAll('canvas')];
      const probe = document.createElement('video');
      probe.muted = true; probe.preload = 'auto'; probe.playsInline = true; probe.src = mediaUrl(ctx.source);
      const once = (name, timeout = 12000) => new Promise((resolve, reject) => {
        const timer = setTimeout(() => { cleanup(); reject(new Error('timeout')); }, timeout);
        const cleanup = () => { clearTimeout(timer); probe.removeEventListener(name, done); probe.removeEventListener('error', fail); };
        const done = () => { cleanup(); resolve(); }, fail = () => { cleanup(); reject(new Error('video')); };
        probe.addEventListener(name, done, {once: true}); probe.addEventListener('error', fail, {once: true});
      });
      try {
        await once('loadeddata');
        const total = span();
        for (let index = 0; index < canvases.length; index++) {
          if (token !== openToken) return;
          const target = Math.min(Math.max(0, total - 0.03), (index + 0.5) / canvases.length * total);
          if (Math.abs(probe.currentTime - target) > 0.005) { probe.currentTime = target; await once('seeked', 5000); }
          const canvas = canvases[index], context = canvas.getContext('2d');
          if (!context || !probe.videoWidth || !probe.videoHeight) continue;
          const scale = Math.max(canvas.width / probe.videoWidth, canvas.height / probe.videoHeight);
          const drawWidth = probe.videoWidth * scale, drawHeight = probe.videoHeight * scale;
          context.drawImage(probe, (canvas.width - drawWidth) / 2, (canvas.height - drawHeight) / 2, drawWidth, drawHeight);
          canvas.classList.add('is-ready');
        }
      } catch (_error) {
        if (token === openToken) container.classList.add('is-unavailable');
      } finally {
        probe.removeAttribute('src'); probe.load();
      }
    }

    function paintMarkers() {
      const box = q('[data-vf-markers]');
      if (!info) { box.innerHTML = ''; return; }
      const cuts = scenes.map(item => `<i class="desk-video-frames__cut" style="left:${percent(item.frame).toFixed(3)}%"></i>`);
      const pins = [...marks.keys()].map(n => `<i class="desk-video-frames__pin" style="left:${percent(n).toFixed(3)}%"></i>`);
      box.innerHTML = cuts.join('') + pins.join('');
    }

    async function thumbnail(n) {
      if (thumbs.has(n)) return thumbs.get(n);
      const token = openToken;
      const pending = api.previewFrame(ctx.source, n, 240).then(blob => {
        const url = URL.createObjectURL(blob);
        if (token !== openToken) { URL.revokeObjectURL(url); return ''; }
        thumbs.set(n, url);
        return url;
      }).catch(() => { thumbs.delete(n); return ''; });
      thumbs.set(n, pending);
      return pending;
    }

    function paintThumb(img, n) {
      const show = url => { if (!url || !img.isConnected) return; img.src = url; img.classList.add('is-ready'); };
      const value = thumbs.get(n);
      if (typeof value === 'string') { show(value); return; }
      thumbnail(n).then(show);
    }

    function toggleMark(n) {
      if (marks.has(n)) marks.delete(n);
      else if (marks.size >= MAX_MARKS) { showMessage(`单次最多抽 ${MAX_MARKS} 帧`); return; }
      else { marks.set(n, true); lastAdded = n; }
      paintMarks();
      paintReadout();
    }

    function paintMarks() {
      const frames = [...marks.keys()].sort((a, b) => a - b);
      const list = q('[data-vf-marks]');
      q('[data-vf-count]').textContent = `${frames.length} / ${MAX_MARKS}`;
      list.innerHTML = frames.length ? frames.map(n => {
        const classes = [n === frame ? 'is-current' : '', n === lastAdded ? 'is-new' : ''].filter(Boolean).join(' ');
        const cut = scenes.some(item => item.frame === n);
        return `<li data-vf-frame-item="${n}"${classes ? ` class="${classes}"` : ''} title="跳到第 ${n + 1} 帧">
          <img alt="" data-vf-thumb="${n}">
          <span class="desk-video-frames__mark-meta"><b>#${n + 1}</b><small>${esc(clock(info.frameTimes[n]))}</small></span>
          ${cut ? '<i class="desk-video-frames__mark-cut" title="场景切换点"></i>' : ''}
          <button type="button" data-vf-unmark="${n}" title="移除标记" aria-label="移除第 ${n + 1} 帧标记">${icon(ICON.close)}</button></li>`;
      }).join('')
        : '<li class="desk-video-frames__empty">移到想要的画面，按 <kbd>M</kbd> 标记</li>';
      lastAdded = null;
      list.querySelectorAll('[data-vf-thumb]').forEach(img => paintThumb(img, Number(img.dataset.vfThumb)));
      paintMarkers();
      const extract = q('[data-vf-extract]');
      extract.disabled = !frames.length;
      extract.textContent = frames.length ? `抽出 ${frames.length} 帧` : '抽出帧';
      root.querySelectorAll('[data-vf-scene]').forEach(input => { input.checked = marks.has(Number(input.value)); });
    }

    function paintScenes() {
      const box = q('[data-vf-scenes]');
      paintMarkers();
      q('[data-vf-scene-count]').textContent = scenesDetected ? `${scenes.length} 处` : '';
      if (detecting) {
        box.innerHTML = `<div class="desk-video-frames__empty is-busy">${esc(detecting)}</div>`;
        return;
      }
      if (!scenesDetected) {
        box.innerHTML = '<div class="desk-video-frames__empty">找出镜头切换点，勾选后加入标记</div>';
        return;
      }
      box.innerHTML = scenes.length ? scenes.map((item, index) => `<label class="desk-video-frames__scene${item.frame === frame ? ' is-current' : ''}" data-vf-scene-row="${item.frame}">
          <img alt="" data-vf-thumb="${item.frame}">
          <span class="desk-video-frames__scene-text"><b>切换 ${index + 1}</b><small>帧 ${item.frame + 1} · ${esc(clock(item.time))}</small></span>
          <input type="checkbox" value="${item.frame}" data-vf-scene aria-label="标记切换 ${index + 1}"${marks.has(item.frame) ? ' checked' : ''}></label>`).join('')
        : '<div class="desk-video-frames__empty">没有侦测到镜头切换，整段是同一个镜头</div>';
      box.querySelectorAll('[data-vf-thumb]').forEach(img => paintThumb(img, Number(img.dataset.vfThumb)));
    }

    async function detect() {
      if (!ctx || detecting) return;
      const token = openToken;
      const button = q('[data-vf-detect]');
      button.disabled = true;
      detecting = '侦测中…';
      paintScenes();
      try {
        const result = await ctx.detectScenes(value => {
          if (token !== openToken) return;
          detecting = value == null ? '侦测中…' : `侦测中… ${Math.round(value)}%`;
          paintScenes();
        });
        if (token !== openToken) return;
        scenes = (result?.scenes || []).map(item => ({frame: Number(item.frame), time: Number(item.time)}));
        scenesDetected = true;
        q('[data-vf-detect] span').textContent = '重新侦测';
      } catch (error) {
        if (token === openToken) showMessage(error.message || '场景侦测失败');
      } finally {
        if (token === openToken) { detecting = null; button.disabled = false; paintScenes(); paintMarks(); paintReadout(); }
      }
    }

    function onClick(event) {
      const target = event.target;
      if (target.closest('[data-vf-close]')) { close(); return; }
      if (!info) return;
      const stepButton = target.closest('[data-vf-step]');
      if (stepButton) {
        const value = stepButton.dataset.vfStep;
        seekFrame(frame + (value === 'second' ? step() : value === '-second' ? -step() : Number(value)));
        return;
      }
      if (target.closest('[data-vf-play]')) {
        const video = q('[data-vf-video]');
        if (video.paused) {
          if (frame >= frameCount() - 1) video.currentTime = 0;
          video.play().catch(() => {});
        } else video.pause();
        return;
      }
      if (target.closest('[data-vf-mark]')) { toggleMark(frame); return; }
      if (target.closest('[data-vf-detect]')) { detect(); return; }
      const unmark = target.closest('[data-vf-unmark]');
      if (unmark) { marks.delete(Number(unmark.dataset.vfUnmark)); paintMarks(); paintReadout(); return; }
      const item = target.closest('[data-vf-frame-item]');
      if (item) { seekFrame(Number(item.dataset.vfFrameItem)); return; }
      const sceneRow = target.closest('[data-vf-scene-row]');
      if (sceneRow && !target.matches('input')) {
        event.preventDefault();
        seekFrame(Number(sceneRow.dataset.vfSceneRow));
        return;
      }
      if (target.closest('[data-vf-extract]')) {
        const frames = [...marks.keys()].sort((a, b) => a - b);
        const current = ctx;
        close();
        current.onExtract(frames);
      }
    }

    function onChange(event) {
      const input = event.target.closest('[data-vf-scene]');
      if (!input) return;
      const n = Number(input.value);
      if (input.checked !== marks.has(n)) toggleMark(n);
      input.checked = marks.has(n);
    }

    function onKey(event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (!info || event.target.matches('input, textarea, select') || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        seekFrame(frame + (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? step() : 1));
      } else if (event.key === 'm' || event.key === 'M') {
        event.preventDefault();
        toggleMark(frame);
      } else if (event.key === ' ' && !event.target.matches('button')) {
        event.preventDefault();
        q('[data-vf-play]').click();
      }
    }

    // ctx: {source, name, frameCount?, onExtract(frames), detectScenes(onProgress) -> Promise<{scenes}>}
    async function open(context) {
      ensureRoot();
      close({restoreFocus: false});
      const token = ++openToken;
      ctx = context;
      info = null; frame = 0; marks = new Map(); scenes = []; scenesDetected = false; detecting = null; lastAdded = null;
      returnFocus = document.activeElement;
      root.hidden = false;
      document.body.classList.add('desk-video-frames-open');
      q('[data-vf-name]').textContent = context.name || '视频';
      q('[data-vf-name]').title = context.name || '';
      q('[data-vf-meta]').innerHTML = '';
      q('[data-vf-detect] span').textContent = '侦测';
      q('[data-vf-detect]').disabled = true;
      q('[data-vf-loading]').hidden = false;
      q('[data-vf-loading]').textContent = '读取帧信息…';
      q('[data-vf-time]').textContent = clock(0);
      q('[data-vf-frame]').textContent = '帧 — / —';
      q('[data-vf-filmstrip]').innerHTML = '';
      q('[data-vf-ruler]').innerHTML = '';
      q('[data-vf-badge="mark"]').hidden = true;
      q('[data-vf-badge="cut"]').hidden = true;
      paintScenes();
      q('.desk-video-frames__dialog').focus();
      try {
        const probed = await api.probe(context.source);
        if (token !== openToken) return;
        if (!probed.frameCount) throw new Error('无法读取视频帧');
        info = probed;
      } catch (error) {
        if (token !== openToken) return;
        q('[data-vf-loading]').textContent = error.message || '读取帧信息失败';
        return;
      }
      const video = q('[data-vf-video]');
      video.src = mediaUrl(context.source);
      video.addEventListener('loadeddata', () => { if (token === openToken) seekFrame(0); }, {once: true});
      q('[data-vf-loading]').hidden = true;
      q('[data-vf-meta]').innerHTML = [`${info.width}×${info.height}`, info.fps ? `${Math.round(info.fps * 100) / 100} fps` : '',
        `${info.frameCount} 帧`, clock(span()), info.hasAudio ? '有音轨' : '无音轨']
        .filter(Boolean).map(text => `<span>${esc(text)}</span>`).join('');
      q('[data-vf-detect]').disabled = false;
      paintRuler();
      paintMarks();
      paintReadout();
      buildFilmstrip(token);
    }

    function close({restoreFocus = true} = {}) {
      if (!root || root.hidden) return;
      openToken += 1;
      const video = q('[data-vf-video]');
      video.pause();
      video.removeAttribute('src');
      video.load();
      thumbs.forEach(value => { if (typeof value === 'string' && value) URL.revokeObjectURL(value); });
      thumbs = new Map();
      root.hidden = true;
      root.classList.remove('is-scrubbing');
      document.body.classList.remove('desk-video-frames-open');
      ctx = null; info = null; playing = false;
      if (restoreFocus && returnFocus?.isConnected) returnFocus.focus?.({preventScroll: true});
      returnFocus = null;
    }

    return Object.freeze({open, close, isOpen: () => Boolean(root && !root.hidden)});
  }

  window.DesktopVideoFrames = Object.freeze({create, bisectFrame, seekTime, clock, rulerStep, rulerLabel, MAX_MARKS});
})();
