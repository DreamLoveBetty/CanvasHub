// Draft preview for the compose node: plays the trimmed clips back to back in one <video> and keeps
// the music in an <audio> at the same timeline position with the configured fades. It is an
// approximation of the render (no re-encode): a clip's speed is the playback rate and a transition
// is a cut at its midpoint (the caller trims each clip by half of each overlap). The finished MP4
// plays through the same player as a single clip. Owns only its media elements and timers; the
// caller owns the plan.
(function () {
  const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));
  const EDGE = 0.015;
  const BLUR_MS = 160;

  // frame: element holding <video> and <canvas data-compose-blur>.
  function create({frame, mediaUrl = url => url, onTick = () => {}}) {
    const video = frame.querySelector('video');
    const blur = frame.querySelector('canvas');
    const music = new Audio();
    music.preload = 'auto';
    let plan = {clips: [], clipVolume: 1, music: null};
    let index = 0, playing = false, raf = 0, token = 0, lastBlur = 0, destroyed = false;

    // Clip times are source seconds; lengths and the timeline are output seconds (source / speed).
    const rate = clip => clip?.speed || 1;
    const length = clip => Math.max(0, (clip.end - clip.start) / rate(clip));
    const total = () => plan.clips.reduce((sum, clip) => sum + length(clip), 0);
    const offset = position => plan.clips.slice(0, position).reduce((sum, clip) => sum + length(clip), 0);
    const once = (target, events) => new Promise(resolve => {
      const done = () => { events.forEach(name => target.removeEventListener(name, done)); resolve(); };
      events.forEach(name => target.addEventListener(name, done, {once: true}));
    });

    function paintBlur(force = false) {
      if (!blur || frame.dataset.fit !== 'blur' || video.readyState < 2) return;
      const now = performance.now();
      if (!force && now - lastBlur < BLUR_MS) return;
      lastBlur = now;
      try { blur.getContext('2d').drawImage(video, 0, 0, blur.width, blur.height); } catch (_error) { /* not decodable yet */ }
    }

    // source: an exact source time to show (the trim preview's cut frame) instead of `local`.
    async function load(position, local = 0, source = null) {
      const mine = ++token;
      index = position;
      const clip = plan.clips[position];
      if (!clip) return false;
      const src = mediaUrl(clip.url);
      if (video.dataset.src !== src) {
        video.dataset.src = src;
        video.src = src;
        await once(video, ['loadedmetadata', 'error']);
        if (mine !== token || destroyed) return false;
      }
      video.muted = !clip.audio;
      video.volume = clamp(plan.clipVolume, 0, 1);
      video.playbackRate = rate(clip);
      const target = source !== null ? source + 0.001
        : clip.start + clamp(local, 0, Math.max(0, length(clip) - 0.001)) * rate(clip) + 0.001;
      if (Math.abs(video.currentTime - target) > 0.0005) {
        video.currentTime = target;
        await once(video, ['seeked', 'error']);
        if (mine !== token || destroyed) return false;
      }
      paintBlur(true);
      return true;
    }

    const timeNow = () => {
      const clip = plan.clips[index];
      return clip ? offset(index) + clamp((video.currentTime - clip.start) / rate(clip), 0, length(clip)) : 0;
    };

    function syncMusic(time) {
      const source = plan.music;
      if (!source?.url) { music.pause(); return; }
      const src = mediaUrl(source.url);
      if (music.dataset.src !== src) { music.dataset.src = src; music.src = src; }
      const end = total();
      let gain = 1;
      if (source.fadeIn > 0) gain = Math.min(gain, time / source.fadeIn);
      const heard = Math.min(end, source.seconds || end);
      if (source.fadeOut > 0) gain = Math.min(gain, (heard - time) / source.fadeOut);
      music.volume = clamp(source.volume * clamp(gain, 0, 1), 0, 1);
      if (source.seconds && time >= source.seconds) { music.pause(); return; }
      if (Math.abs(music.currentTime - time) > 0.25) {
        try { music.currentTime = time; } catch (_error) { /* metadata pending */ }
      }
      if (playing && music.paused) music.play().catch(() => {});
      if (!playing) music.pause();
    }

    async function loop() {
      if (!playing || destroyed) return;
      const clip = plan.clips[index];
      if (clip && (video.currentTime >= clip.end - EDGE || video.ended)) {
        if (index + 1 < plan.clips.length) {
          const loaded = await load(index + 1);
          if (!playing || !loaded) return;
          await video.play().catch(() => {});
        } else {
          stop();
          onTick(total(), index);
          return;
        }
      }
      const time = timeNow();
      syncMusic(time);
      paintBlur();
      onTick(time, index);
      raf = requestAnimationFrame(loop);
    }

    async function play() {
      if (!plan.clips.length || playing) return;
      if (timeNow() >= total() - 0.05 || !video.dataset.src) await seek(0);
      playing = true;
      await video.play().catch(() => { playing = false; });
      if (playing) { onTick(timeNow(), index); loop(); }
    }

    function stop() {
      const was = playing;
      playing = false;
      cancelAnimationFrame(raf);
      video.pause();
      music.pause();
      if (was) onTick(timeNow(), index);
    }

    async function seek(time) {
      if (!plan.clips.length) return;
      const target = clamp(time, 0, Math.max(0, total() - 0.001));
      let position = 0;
      while (position < plan.clips.length - 1 && target >= offset(position + 1)) position += 1;
      if (await load(position, target - offset(position))) {
        syncMusic(target);
        onTick(target, position);
      }
    }

    return Object.freeze({
      setPlan(next) {
        stop();
        plan = {clipVolume: 1, music: null, ...next, clips: (next.clips || []).filter(clip => clip.url && clip.end > clip.start)};
        if (index >= plan.clips.length) index = 0;
        if (!plan.clips.length) { video.removeAttribute('src'); delete video.dataset.src; video.load(); }
      },
      // Volume and fade edits apply while playing; the clip list is unchanged.
      setLevels({clipVolume, music}) {
        plan = {...plan, clipVolume, music: plan.music && music ? {...plan.music, ...music} : plan.music};
        video.volume = clamp(clipVolume, 0, 1);
        syncMusic(timeNow());
      },
      play, stop, seek, total, offset, isPlaying: () => playing, time: timeNow,
      async show(position, local) {
        stop();
        if (await load(position, local)) onTick(offset(position) + local, position);
      },
      // The frame at `source` seconds of clip `position`, even inside a transition's trimmed overlap.
      async showSource(position, source) {
        stop();
        const clip = plan.clips[position];
        if (clip && await load(position, 0, source)) onTick(offset(position) + clamp((source - clip.start) / rate(clip), 0, length(clip)), position);
      },
      destroy() {
        destroyed = true;
        stop();
        token += 1;
        video.removeAttribute('src');
        delete video.dataset.src;
        video.load();
        music.removeAttribute('src');
        music.load();
      },
    });
  }

  window.DesktopVideoComposePlayer = Object.freeze({create});
})();
