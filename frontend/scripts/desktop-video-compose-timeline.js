// Compose workbench timeline: one picture lane of clip blocks (width = output seconds: trimmed
// length / speed, less half of each transition overlap), transition markers on the boundaries, a
// subtitle lane of cue blocks on the output timeline (drag to move, edges to resize, double-click to
// add), a music lane with waveform and fade ramps, a ruler that seeks and a playhead. Trims snap to real
// frame times from the backend probe (in and out handles, at least MIN output seconds); blocks
// drag to reorder.
// Owns only its DOM and drag state; every edit is reported through callbacks and the caller
// re-renders from its own state.
(function () {
  const LANE_H = 52;
  const MUSIC_H = 40;
  const TILE_CHOICES = [8, 16, 24, 40];
  const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));
  // Same snapping as backend contracts.filmstrip_tiles: about four tiles a second, at most 40.
  const tilesFor = seconds => TILE_CHOICES.reduce((best, n) => Math.abs(n - seconds * 4) < Math.abs(best - seconds * 4) ? n : best);

  // view: {clips: [{key, label, url, probe, startFrame, endFrame, audio, hasAudio, speed, transition, error}],
  //        music: {name, seconds, peaks, volume, fadeIn, fadeOut} | null, selected (clip, -1 for none),
  //        cues: [{start, end, text}] (the node's own cues), cue (selected cue, -1 for none)}
  // onShow(k, sourceSeconds): show that source frame of clip k (the cut frame while trimming).
  // onCueEdit(k, edge, start, end, final): edge 'move' | 'start' | 'end'; the caller clamps the cue in place.
  function create({root, model, helpers, filmstrip, escapeHtml, onTrim, onMove, onAudio, onSelect, onSeek, onShow,
    onCueSelect = () => {}, onCueEdit = () => {}, onCueAdd = () => {}}) {
    const esc = value => escapeHtml(String(value ?? ''));
    root.innerHTML = `<div class="desk-video-compose-tl__labels" aria-hidden="true"><span>时间</span><span>画面</span><span>字幕</span><span>配乐</span></div>
      <div class="desk-video-compose-tl__tracks" data-tl-tracks>
        <div class="desk-video-compose-tl__ruler" data-tl-ruler title="点击或拖动跳转"></div>
        <div class="desk-video-compose-tl__lane" data-tl-lane><div class="desk-video-compose-tl__insert" data-tl-insert hidden></div></div>
        <div class="desk-video-compose-tl__lane is-subtitles" data-tl-subs title="双击空白处添加字幕"></div>
        <div class="desk-video-compose-tl__lane is-music" data-tl-music></div>
        <div class="desk-video-compose-tl__playhead" data-tl-head hidden><span></span></div>
      </div>`;
    const q = selector => root.querySelector(selector);
    const tracks = q('[data-tl-tracks]'), ruler = q('[data-tl-ruler]'), lane = q('[data-tl-lane]');
    const musicLane = q('[data-tl-music]'), insert = q('[data-tl-insert]'), head = q('[data-tl-head]');
    const subsLane = q('[data-tl-subs]');
    let view = {clips: [], music: null, selected: 0, cues: [], cue: -1};
    let pps = 40, frozen = false, headTime = 0;
    // url|tiles -> {url, tiles} once loaded, or the pending Promise. Object URLs belong to `filmstrip`'s cache.
    const sprites = new Map();

    const windowOf = clip => clip.probe ? model.clipWindow(clip.probe, clip.startFrame, clip.endFrame) : null;
    // Recomputed per use: trims mutate clips in place while dragging.
    const timing = () => model.timing(view.clips, view.clips.map(windowOf));
    const total = () => timing().total;
    const PLACEHOLDER = 72; // px for clips still probing or unsupported

    function fitScale() {
      const width = tracks.clientWidth || 800;
      const fixed = view.clips.filter(clip => !clip.probe).length * PLACEHOLDER;
      pps = Math.max(2, (width - fixed) / Math.max(total() * 1.04, 8));
    }

    function renderRuler() {
      const width = tracks.clientWidth || 800, span = width / pps;
      const every = helpers.rulerStep(span, Math.max(4, Math.floor(width / 90)));
      const ticks = [];
      for (let t = 0; t * pps <= width - 30 && ticks.length < 60; t += every) {
        ticks.push(`<span style="left:${(t * pps).toFixed(1)}px">${helpers.rulerLabel(Math.round(t * 10) / 10)}</span>`);
      }
      ruler.innerHTML = ticks.join('');
    }

    function sprite(clip) {
      const tiles = tilesFor(clip.probe.durationSeconds || 0), key = clip.url + '|' + tiles;
      const entry = sprites.get(key);
      if (entry && !(entry instanceof Promise)) return entry;
      if (!entry) {
        sprites.set(key, filmstrip(clip.url, tiles).then(url => {
          sprites.set(key, {url, tiles});
          if (!frozen) layout();
        }).catch(() => sprites.set(key, {url: '', tiles})));
      }
      return null;
    }

    // head: output seconds of the clip hidden under the previous transition.
    function tilesHtml(clip, width, head) {
      const probe = clip.probe, strip = sprite(clip);
      const tileW = LANE_H * (probe.width || 16) / Math.max(1, probe.height || 9);
      const count = Math.max(1, Math.ceil(width / tileW));
      const win = windowOf(clip), frames = probe.frameTimes.length;
      const tiles = [];
      for (let i = 0; i < count; i += 1) {
        const at = win.start + (head + (i + 0.5) * tileW / pps) * (clip.speed || 1);
        const frame = helpers.bisectFrame(probe.frameTimes, at);
        const style = strip?.url ? `background-image:url(${strip.url});background-size:${(strip.tiles * tileW).toFixed(1)}px 100%;`
          + `background-position:${(-Math.min(strip.tiles - 1, Math.floor(frame * strip.tiles / frames)) * tileW).toFixed(1)}px 0` : '';
        tiles.push(`<i style="width:${tileW.toFixed(1)}px;${style}"></i>`);
      }
      return tiles.join('');
    }

    function layout() {
      const plan = timing(), edges = [];
      let left = 0;
      lane.querySelectorAll('[data-tl-clip]').forEach(block => {
        const k = Number(block.dataset.tlClip), clip = view.clips[k];
        if (!clip) return;
        const segment = plan.segments[k], width = clip.probe ? segment.length * pps : PLACEHOLDER;
        block.style.left = `${left.toFixed(1)}px`;
        block.style.width = `${Math.max(6, width - 2).toFixed(1)}px`;
        block.dataset.width = String(width);
        if (clip.probe) {
          block.querySelector('[data-tl-strip]').innerHTML = tilesHtml(clip, width, segment.head);
          block.querySelector('[data-tl-length]').textContent = `${plan.lengths[k].toFixed(2)} 秒`;
        }
        left += width;
        edges[k] = left;
      });
      lane.querySelectorAll('[data-tl-transition]').forEach(marker => {
        const k = Number(marker.dataset.tlTransition), clip = view.clips[k];
        marker.style.left = `${(edges[k] - 1).toFixed(1)}px`;
        const cut = plan.cuts[k] || 0, type = clip?.transition?.type || 'none';
        marker.classList.toggle('is-set', type !== 'none');
        marker.classList.toggle('is-selected', k === view.selected);
        marker.title = type === 'none' ? `第 ${k + 1}→${k + 2} 段：直接切换，点击设置转场`
          : `第 ${k + 1}→${k + 2} 段：${transitionLabel(type)} ${cut.toFixed(2)} 秒${cut + 1e-6 < clip.transition.duration ? '（受片段长度限制）' : ''}`;
      });
      layoutCues();
      paintMusic();
      paintHead();
    }

    function cuesHtml() {
      const cues = view.cues || [];
      if (!cues.length) return '<span class="desk-video-compose-tl__empty">双击添加字幕，或在右侧导入 SRT</span>';
      return cues.map((cue, k) => `<div class="desk-video-compose-tl__cue${k === view.cue ? ' is-selected' : ''}" data-tl-cue="${k}"
          tabindex="0" role="button" aria-label="字幕 ${k + 1}"><span data-tl-cue-text></span>
          <i class="desk-video-compose-tl__cue-edge is-start" data-tl-cue-edge="start" title="拖动调整开始时间"></i>
          <i class="desk-video-compose-tl__cue-edge is-end" data-tl-cue-edge="end" title="拖动调整结束时间"></i></div>`).join('');
    }

    // A cue starting after the render ends (late) is drawn pinned to the lane's end so it stays
    // visible: it can still be selected, deleted, or dragged back into range from there.
    const isLate = cue => cue.start >= total() - model.SUBTITLE_MIN_SECONDS + 1e-6;
    const shownRange = cue => isLate(cue) ? {start: Math.max(0, total() - model.SUBTITLE_MIN_SECONDS), end: total()} : cue;

    // Cue blocks sit on output seconds; late ones are marked and pinned (shownRange).
    function layoutCues() {
      subsLane.querySelectorAll('[data-tl-cue]').forEach(block => {
        const k = Number(block.dataset.tlCue), cue = view.cues[k];
        if (!cue) return;
        const shown = shownRange(cue), late = isLate(cue);
        block.style.left = `${(shown.start * pps).toFixed(1)}px`;
        block.style.width = `${Math.max(4, (shown.end - shown.start) * pps - 1).toFixed(1)}px`;
        block.classList.toggle('is-over', late);
        block.classList.toggle('is-empty', !cue.text.trim());
        block.querySelector('[data-tl-cue-text]').textContent = cue.text.replace(/\n/g, ' ') || '（空字幕）';
        block.title = `${helpers.clock(cue.start)} – ${helpers.clock(cue.end)}${late ? ' · 在成片结束之后' : ''}\n${cue.text}`;
      });
    }

    const transitionLabel = type => (model.TRANSITIONS.find(([key]) => key === type) || [])[1] || '';

    function blockHtml(clip, k) {
      const audio = clip.hasAudio
        ? `<button type="button" class="desk-video-compose-tl__audio" data-tl-audio aria-pressed="${clip.audio}" title="${clip.audio ? '保留这段原声，点击静音' : '这段已静音，点击保留原声'}">原声</button>`
        : '<span class="desk-video-compose-tl__audio is-none" title="这段没有音轨，合成时补静音">无音轨</span>';
      const state = clip.error ? ' is-error' : clip.probe ? '' : ' is-loading';
      return `<div class="desk-video-compose-tl__clip${k === view.selected ? ' is-selected' : ''}${state}" data-tl-clip="${k}" tabindex="0"
          role="button" aria-label="第 ${k + 1} 段 ${esc(clip.label)}">
          <div class="desk-video-compose-tl__strip" data-tl-strip></div>
          <span class="desk-video-compose-tl__cap"><b>${k + 1}</b><span>${esc(clip.error || clip.label)}</span>${clip.speed && clip.speed !== 1 ? `<em class="desk-video-compose-tl__speed">${clip.speed}×</em>` : ''}<small data-tl-length>${clip.probe ? '' : clip.error ? '' : '读取中…'}</small></span>
          ${clip.probe ? audio : ''}
          ${clip.probe ? `<span class="desk-video-compose-tl__handle is-in" data-tl-handle="in" title="拖动设定入点（按帧）"></span>
          <span class="desk-video-compose-tl__handle is-out" data-tl-handle="out" title="拖动设定出点（按帧）"></span>` : ''}
        </div>`;
    }

    function render(next) {
      view = next;
      if (!tracks.clientWidth) return;
      if (!frozen) fitScale();
      renderRuler();
      lane.querySelectorAll('[data-tl-clip]').forEach(block => block.remove());
      lane.insertAdjacentHTML('beforeend', view.clips.map(blockHtml).join('')
        + view.clips.slice(0, -1).map((_clip, k) => `<button type="button" class="desk-video-compose-tl__transition" data-tl-transition="${k}" aria-label="第 ${k + 1} 段到第 ${k + 2} 段的转场"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3l6 5-6 5zM14 3l-6 5 6 5z"/></svg></button>`).join(''));
      lane.classList.toggle('is-empty', !view.clips.length);
      subsLane.innerHTML = cuesHtml();
      layout();
    }

    function paintMusic() {
      const music = view.music, end = Math.min(music?.seconds || total(), total());
      if (!music || end <= 0) { musicLane.innerHTML = music ? '' : '<span class="desk-video-compose-tl__empty">连接音频节点作为配乐</span>'; return; }
      const width = end * pps, peaks = music.peaks || [], bars = [];
      for (let x = 2; x < width - 2; x += 4) {
        const value = peaks.length ? peaks[Math.min(peaks.length - 1, Math.floor(x / pps / (music.seconds || end) * peaks.length))] : 0.3;
        const h = (0.12 + 0.88 * clamp(value, 0, 1)) * (MUSIC_H - 14);
        bars.push(`<rect x="${x}" y="${(MUSIC_H - 4 - h).toFixed(1)}" width="3" height="${h.toFixed(1)}" rx="1"/>`);
      }
      const fadeIn = Math.min(music.fadeIn, end) * pps, fadeOut = Math.min(music.fadeOut, end) * pps;
      const fades = (fadeIn ? `<polygon class="is-fade" points="0,0 ${fadeIn},0 0,${MUSIC_H}"/>` : '')
        + (fadeOut ? `<polygon class="is-fade" points="${width - fadeOut},0 ${width},0 ${width},${MUSIC_H}"/>` : '');
      const ramp = `<polyline class="is-ramp" points="0,${fadeIn ? MUSIC_H : 2} ${fadeIn},2 ${width - fadeOut},2 ${width},${fadeOut ? MUSIC_H : 2}"/>`;
      musicLane.innerHTML = `<div class="desk-video-compose-tl__music" style="width:${width.toFixed(1)}px">
        <svg viewBox="0 0 ${width.toFixed(1)} ${MUSIC_H}" preserveAspectRatio="none" aria-hidden="true">${fades}<g class="is-bars">${bars.join('')}</g>${ramp}</svg>
        <span>${esc(music.name)} · ${Math.round(music.volume * 100)}%</span></div>`;
    }

    function paintHead() {
      head.hidden = !view.clips.some(clip => clip.probe) || headTime === null;
      if (!head.hidden) head.style.transform = `translateX(${(headTime * pps).toFixed(1)}px)`;
    }

    // time: draft-timeline seconds, or null to hide (the result plays its own snapshot).
    function setTime(time) { headTime = time; paintHead(); }

    // Frame for a trim edge at `at` source seconds, rounded to the nearest frame boundary; the clip
    // keeps at least MIN output seconds (MIN × speed of source).
    function trimTo(clip, edge, at) {
      const times = clip.probe.frameTimes, count = times.length, half = 0.5 / Math.max(clip.probe.fps || 30, 1);
      const end = clip.endFrame === -1 ? count - 1 : clip.endFrame;
      const span = (s, e) => model.clipWindow(clip.probe, s, e).seconds;
      const least = model.MIN_CLIP_SECONDS * (clip.speed || 1) - 1e-6;
      if (edge === 'in') {
        let start = clamp(helpers.bisectFrame(times, at + half), 0, end);
        while (start > 0 && span(start, end) < least) start -= 1;
        return {startFrame: start, endFrame: clip.endFrame};
      }
      let last = clamp(helpers.bisectFrame(times, at - half), clip.startFrame, count - 1);
      while (last < count - 1 && span(clip.startFrame, last) < least) last += 1;
      return {startFrame: clip.startFrame, endFrame: last === count - 1 ? -1 : last};
    }

    function dragHandle(event, handle, k) {
      const clip = view.clips[k], edge = handle.dataset.tlHandle;
      const win = windowOf(clip), origin = event.clientX, anchor = edge === 'in' ? win.start : win.stop;
      frozen = true;
      handle.setPointerCapture(event.pointerId);
      root.classList.add('is-trimming');
      // Source time of the cut frame: the first frame for the in point, the last for the out point.
      const cutTime = () => {
        const fresh = windowOf(clip);
        return clip.probe.frameTimes[edge === 'in' ? fresh.startFrame : fresh.endFrame];
      };
      const move = moveEvent => {
        const next = trimTo(clip, edge, anchor + (moveEvent.clientX - origin) / pps * (clip.speed || 1));
        if (next.startFrame === clip.startFrame && next.endFrame === clip.endFrame) return;
        Object.assign(clip, next);
        layout();
        onTrim(k, next, false);
        onShow(k, cutTime());
      };
      const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        root.classList.remove('is-trimming');
        frozen = false;
        onTrim(k, {startFrame: clip.startFrame, endFrame: clip.endFrame}, true);
        onShow(k, cutTime());
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    }

    function dragBlock(event, block, k) {
      const origin = event.clientX, blocks = [...lane.querySelectorAll('[data-tl-clip]')];
      let dragging = false, target = k;
      block.setPointerCapture(event.pointerId);
      const move = moveEvent => {
        const dx = moveEvent.clientX - origin;
        if (!dragging && Math.abs(dx) < 4) return;
        dragging = true;
        block.classList.add('is-dragging');
        block.style.translate = `${dx}px 0`;
        const center = block.offsetLeft + dx + block.offsetWidth / 2;
        let boundary = 0;
        target = 0;
        blocks.forEach((other, i) => {
          if (i !== k && center > other.offsetLeft + other.offsetWidth / 2) {
            target = i < k ? i + 1 : i;
            boundary = other.offsetLeft + Number(other.dataset.width || other.offsetWidth);
          }
        });
        insert.hidden = target === k;
        insert.style.left = `${boundary}px`;
      };
      const up = () => {
        block.removeEventListener('pointermove', move);
        block.removeEventListener('pointerup', up);
        block.removeEventListener('pointercancel', up);
        insert.hidden = true;
        block.style.translate = '';
        block.classList.remove('is-dragging');
        if (!dragging) { onSelect(k); return; }
        if (target !== k) onMove(k, target);
      };
      block.addEventListener('pointermove', move);
      block.addEventListener('pointerup', up);
      block.addEventListener('pointercancel', up);
    }

    // Move a cue, or one of its edges; a press without movement selects it.
    function dragCue(event, block, k) {
      const cue = view.cues[k], late = isLate(cue);
      const edge = late ? 'move' : event.target.closest('[data-tl-cue-edge]')?.dataset.tlCueEdge || 'move';
      const origin = event.clientX, shown = shownRange(cue);
      const from = late ? {start: shown.start, end: shown.start + cue.end - cue.start} : {start: cue.start, end: cue.end};
      let dragging = false;
      frozen = true;
      block.setPointerCapture(event.pointerId);
      const move = moveEvent => {
        const dt = (moveEvent.clientX - origin) / pps;
        if (!dragging && Math.abs(moveEvent.clientX - origin) < 3) return;
        dragging = true;
        onCueEdit(k, edge, from.start + (edge === 'end' ? 0 : dt), from.end + (edge === 'start' ? 0 : dt), false);
        layoutCues();
      };
      const up = () => {
        block.removeEventListener('pointermove', move);
        block.removeEventListener('pointerup', up);
        block.removeEventListener('pointercancel', up);
        frozen = false;
        if (dragging) onCueEdit(k, edge, cue.start, cue.end, true); else onCueSelect(k);
      };
      block.addEventListener('pointermove', move);
      block.addEventListener('pointerup', up);
      block.addEventListener('pointercancel', up);
    }

    subsLane.addEventListener('pointerdown', event => {
      const block = event.target.closest('[data-tl-cue]');
      if (event.button !== 0 || !block) return;
      event.preventDefault();
      dragCue(event, block, Number(block.dataset.tlCue));
    });
    subsLane.addEventListener('dblclick', event => {
      if (event.target.closest('[data-tl-cue]')) return;
      onCueAdd(clamp((event.clientX - subsLane.getBoundingClientRect().left) / pps, 0, Math.max(0, total())));
    });
    subsLane.addEventListener('keydown', event => {
      const block = event.target.closest('[data-tl-cue]');
      if (block && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onCueSelect(Number(block.dataset.tlCue)); }
    });

    lane.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const marker = event.target.closest('[data-tl-transition]');
      if (marker) { event.preventDefault(); onSelect(Number(marker.dataset.tlTransition)); return; }
      const block = event.target.closest('[data-tl-clip]');
      if (!block || event.target.closest('[data-tl-audio]')) return;
      const k = Number(block.dataset.tlClip);
      event.preventDefault();
      const handle = event.target.closest('[data-tl-handle]');
      if (handle && view.clips[k]?.probe) dragHandle(event, handle, k); else dragBlock(event, block, k);
    });
    lane.addEventListener('click', event => {
      const button = event.target.closest('[data-tl-audio]');
      if (button) onAudio(Number(button.closest('[data-tl-clip]').dataset.tlClip), button.getAttribute('aria-pressed') !== 'true');
    });
    lane.addEventListener('keydown', event => {
      const block = event.target.closest('[data-tl-clip]');
      if (!block) return;
      const k = Number(block.dataset.tlClip);
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(k); }
      if (event.altKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
        event.preventDefault();
        onMove(k, clamp(k + (event.key === 'ArrowLeft' ? -1 : 1), 0, view.clips.length - 1));
      }
    });
    ruler.addEventListener('pointerdown', event => {
      if (!total()) return;
      const go = moveEvent => onSeek(clamp((moveEvent.clientX - ruler.getBoundingClientRect().left) / pps, 0, total()));
      ruler.setPointerCapture(event.pointerId);
      go(event);
      const up = () => { ruler.removeEventListener('pointermove', go); ruler.removeEventListener('pointerup', up); };
      ruler.addEventListener('pointermove', go);
      ruler.addEventListener('pointerup', up);
    });
    const observer = new ResizeObserver(() => { if (!frozen && root.isConnected && tracks.clientWidth) render(view); });
    observer.observe(tracks);

    // Cue edits (text, add, delete, style) repaint only the subtitle lane and selection.
    function renderCues(cues, cue, selected = view.selected) {
      view = {...view, cues, cue, selected};
      lane.querySelectorAll('[data-tl-clip]').forEach(block => block.classList.toggle('is-selected', Number(block.dataset.tlClip) === selected));
      subsLane.innerHTML = cuesHtml();
      layoutCues();
    }

    return Object.freeze({
      render, renderCues, setTime, total,
      destroy() {
        observer.disconnect();
        sprites.clear();
      },
    });
  }

  window.DesktopVideoComposeTimeline = Object.freeze({create, tilesFor});
})();
