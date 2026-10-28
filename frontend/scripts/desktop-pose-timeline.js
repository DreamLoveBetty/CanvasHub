// Sequence timeline for the pose editor: transport, a scrub track (recognition confidence band, keyframe
// diamonds, export range, playhead) and playback at the clip's frame rate. Owns only its DOM and clock;
// frames, keys and the export range belong to the editor, which it calls back with every change.
const LOW_CONFIDENCE = 0.45;

export function timelineHtml() {
  return `<div class="desk-pose-editor__timeline" data-pe-timeline hidden>
    <div class="desk-pose-editor__transport">
      <button type="button" data-pe-tl="start" title="第一帧（Home）" aria-label="第一帧">⏮</button>
      <button type="button" data-pe-tl="prev" title="上一帧（←）" aria-label="上一帧">‹</button>
      <button type="button" class="is-play" data-pe-tl="play" title="播放 / 暂停（空格）" aria-label="播放">▶</button>
      <button type="button" data-pe-tl="next" title="下一帧（→）" aria-label="下一帧">›</button>
      <button type="button" data-pe-tl="end" title="最后一帧（End）" aria-label="最后一帧">⏭</button>
      <span class="desk-pose-editor__timecode" data-pe-tl-time></span>
      <span class="desk-pose-editor__transport-gap"></span>
      <button type="button" data-pe-tl="key" title="在当前帧为选中角色打关键帧（K）">◆ 关键帧</button>
      <button type="button" data-pe-tl="unkey" title="删除当前帧的关键帧，回到识别结果">删除关键帧</button>
      <button type="button" data-pe-tl="in" title="把当前帧设为导出起点">入点</button>
      <button type="button" data-pe-tl="out" title="把当前帧设为导出终点">出点</button>
    </div>
    <div class="desk-pose-editor__track" data-pe-tl-track><canvas data-pe-tl-canvas aria-label="时间轴：拖动切换帧"></canvas></div>
  </div>`;
}

export function createTimeline(root, {onFrame, onKey, onUnkey, onRange}) {
  const el = root.querySelector('[data-pe-timeline]');
  const canvas = el.querySelector('[data-pe-tl-canvas]');
  const track = el.querySelector('[data-pe-tl-track]');
  let state = null, playing = false, raf = 0, clock = 0, dragging = false, pendingX = null;
  const abort = new AbortController();
  const time = frame => {
    const seconds = frame / (state?.fps || 30);
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${(seconds % 60).toFixed(2).padStart(5, '0')}`;
  };

  function draw() {
    if (!state) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), w = track.clientWidth, h = track.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext('2d'), css = getComputedStyle(el);
    const color = name => css.getPropertyValue(name).trim();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const n = Math.max(1, state.frameCount - 1), x = f => 6 + (w - 12) * f / n;
    // Export range.
    ctx.fillStyle = color('--desk-pose-timeline-range');
    ctx.fillRect(x(state.inFrame), 0, Math.max(1, x(state.outFrame) - x(state.inFrame)), h);
    // Confidence band of the selected character: low-confidence frames marked.
    if (state.confidence) {
      ctx.fillStyle = color('--desk-pose-timeline-low');
      for (let f = 0; f < state.frameCount; f++) {
        const c = state.confidence[f];
        if (Number.isFinite(c) && c < LOW_CONFIDENCE) ctx.fillRect(x(f) - 0.5, h - 7, Math.max(1.5, (w - 12) / n), 5);
      }
      ctx.fillStyle = color('--desk-pose-timeline-span');
      let start = -1;
      for (let f = 0; f <= state.frameCount; f++) {
        const inside = f < state.frameCount && Number.isFinite(state.confidence[f]);
        if (inside && start < 0) start = f;
        if (!inside && start >= 0) { ctx.fillRect(x(start), h - 2, x(f - 1) - x(start) + 1, 2); start = -1; }
      }
    }
    // Keyframes of the selected character.
    ctx.fillStyle = color('--desk-color-accent');
    for (const f of state.keys || []) {
      const cx = x(f), cy = h / 2 - 1;
      ctx.beginPath(); ctx.moveTo(cx, cy - 5); ctx.lineTo(cx + 5, cy); ctx.lineTo(cx, cy + 5); ctx.lineTo(cx - 5, cy); ctx.closePath(); ctx.fill();
    }
    // Playhead.
    ctx.fillStyle = color('--desk-pose-timeline-playhead');
    ctx.fillRect(Math.round(x(state.frame)) - 1, 0, 2, h);
  }

  function paint(next) {
    state = next;
    el.hidden = !state;
    if (!state) { stop(); return; }
    el.querySelector('[data-pe-tl-time]').textContent = `${time(state.frame)} / ${time(state.frameCount - 1)} · 帧 ${state.frame + 1}/${state.frameCount}`;
    const play = el.querySelector('[data-pe-tl="play"]');
    play.textContent = playing ? '❚❚' : '▶';
    play.setAttribute('aria-label', playing ? '暂停' : '播放');
    const keyed = (state.keys || []).includes(state.frame);
    el.querySelector('[data-pe-tl="key"]').disabled = !state.canKey;
    el.querySelector('[data-pe-tl="unkey"]').disabled = !keyed;
    draw();
  }

  function frameAt(clientX) {
    const r = track.getBoundingClientRect();
    return Math.round(Math.min(1, Math.max(0, (clientX - r.left - 6) / Math.max(1, r.width - 12))) * (state.frameCount - 1));
  }
  function go(frame) {
    if (!state) return;
    const f = Math.min(state.frameCount - 1, Math.max(0, Math.round(frame)));
    if (f !== state.frame) onFrame(f);
  }
  function tick(now) {
    if (!playing || !state) return;
    const step = Math.floor((now - clock) * state.fps / 1000);
    if (step > 0) {
      clock += step * 1000 / state.fps;
      const last = state.outFrame > state.inFrame ? state.outFrame : state.frameCount - 1;
      const first = state.outFrame > state.inFrame ? state.inFrame : 0;
      let f = state.frame + step;
      if (f > last) f = first + (f - last - 1) % (last - first + 1);
      onFrame(f);
    }
    raf = requestAnimationFrame(tick);
  }
  function toggle() {
    if (!state) return;
    playing = !playing;
    cancelAnimationFrame(raf);
    if (playing) { clock = performance.now(); raf = requestAnimationFrame(tick); }
    paint(state);
  }
  function stop() { if (playing) { playing = false; cancelAnimationFrame(raf); } }

  el.addEventListener('click', event => {
    const action = event.target.closest('[data-pe-tl]')?.dataset.peTl;
    if (!action || !state) return;
    if (action === 'play') toggle();
    else if (action === 'start') go(0);
    else if (action === 'end') go(state.frameCount - 1);
    else if (action === 'prev') go(state.frame - 1);
    else if (action === 'next') go(state.frame + 1);
    else if (action === 'key') onKey();
    else if (action === 'unkey') onUnkey();
    else if (action === 'in') onRange(state.frame, Math.max(state.frame, state.outFrame));
    else if (action === 'out') onRange(Math.min(state.inFrame, state.frame), state.frame);
  }, {signal: abort.signal});
  // Scrubbing: pointer moves are merged per animation frame.
  track.addEventListener('pointerdown', event => {
    if (!state) return;
    stop(); dragging = true; track.setPointerCapture(event.pointerId); go(frameAt(event.clientX));
  }, {signal: abort.signal});
  track.addEventListener('pointermove', event => {
    if (!dragging) return;
    const first = pendingX === null;
    pendingX = event.clientX;
    if (first) requestAnimationFrame(() => { if (pendingX !== null) go(frameAt(pendingX)); pendingX = null; });
  }, {signal: abort.signal});
  track.addEventListener('pointerup', () => { dragging = false; }, {signal: abort.signal});
  const resize = new ResizeObserver(draw);
  resize.observe(track);

  return Object.freeze({paint, toggle, stop, step: delta => state && go(state.frame + delta), home: () => go(0),
    end: () => state && go(state.frameCount - 1), playing: () => playing,
    destroy() { stop(); abort.abort(); resize.disconnect(); }});
}
