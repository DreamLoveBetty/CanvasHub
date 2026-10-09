// Read-only playback signal tap. Never reroutes the media element's speaker output.
// This module owns capture tracks/Web Audio resources, not canvas state or a RAF.
(function () {
  const FLOOR_DB = -60, FFT_SIZE = 1024, FRAME_MS = 1000 / 30, HOLD_MS = 400;
  const SILENT = Object.freeze({ db: -Infinity, peakDb: -Infinity, level: 0, peak: 0 });
  const fraction = db => Math.max(0, Math.min(1, (db - FLOOR_DB) / -FLOOR_DB));
  const decibels = amplitude => amplitude > 0 ? 20 * Math.log10(amplitude) : -Infinity;
  const stopLateTrack = event => event.track?.stop();

  function measure(samples, volume) {
    let power = 0, peak = 0;
    for (const value of samples) {
      const sample = Number.isFinite(value) ? value : 0;
      power += sample * sample; peak = Math.max(peak, Math.abs(sample));
    }
    const gain = Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0;
    const db = decibels(Math.sqrt(power / (samples.length || 1)) * gain);
    const peakDb = decibels(peak * gain);
    return { db, peakDb, level: fraction(db), peak: fraction(peakDb) };
  }

  function create(audio, environment = window) {
    let graph = null, disposed = false, unavailable = false, active = false;
    let lastTime = -Infinity, lastVolume = -1;
    let held = [SILENT.peakDb, SILENT.peakDb], heldUntil = [0, 0];
    let lastState = '';
    const empty = state => {
      held = [-Infinity, -Infinity]; heldUntil = [0, 0]; lastTime = -Infinity;
      if (lastState === state) return null;
      lastState = state;
      return { state, channels: [SILENT, SILENT] };
    };
    function release() {
      const old = graph; graph = null;
      if (!old) return;
      old.stream?.removeEventListener('addtrack', old.sync);
      old.stream?.removeEventListener('removetrack', old.sync);
      // captureStream stays associated with its element: a queued addtrack may
      // arrive even after release. Keep only this stateless cleanup listener.
      old.stream?.addEventListener('addtrack', stopLateTrack);
      old.stream?.getTracks().forEach(track => old.tracks.add(track));
      old.tracks.forEach(track => track.stop());
      [old.source, old.stereo, old.splitter, ...(old.analysers || [])].forEach(node => {
        try { node?.disconnect(); } catch (_) { /* Already disconnected. */ }
      });
      old.context?.close().catch(() => {});
    }
    function fail(current) {
      if (graph !== current || disposed) return;
      unavailable = true; release();
    }
    function start() {
      if (disposed || unavailable) return;
      active = true;
      try {
        if (!graph) {
          const Context = environment.AudioContext || environment.webkitAudioContext;
          const capture = audio.captureStream || audio.mozCaptureStream;
          if (!Context || !capture || !environment.MediaStream) { unavailable = true; return; }
          // Capture is independent of element volume/mute per the DOM capture spec.
          // Apply the current element gain to measured samples, not to speaker routing.
          const current = graph = { context: new Context(), stream: null, source: null, track: null, tracks: new Set() };
          current.stream = capture.call(audio);
          current.stereo = current.context.createGain();
          current.stereo.channelCount = 2; current.stereo.channelCountMode = 'explicit';
          current.stereo.channelInterpretation = 'speakers'; // Mono feeds both output meters.
          current.splitter = current.context.createChannelSplitter(2);
          current.analysers = [0, 1].map(channel => {
            const analyser = current.context.createAnalyser(); analyser.fftSize = FFT_SIZE;
            current.splitter.connect(analyser, channel);
            return analyser;
          });
          current.buffers = current.analysers.map(() => new Float32Array(FFT_SIZE));
          current.stereo.connect(current.splitter);
          // Analysers work without a destination. Connecting this tap to speakers
          // would duplicate playback and must never be done.
          current.sync = event => {
            if (graph !== current || disposed) return;
            try {
              // A browser may remove a captured track before a source replacement
              // reaches us. Retain ownership so it is stopped on disposal too.
              if (event?.track) current.tracks.add(event.track);
              current.stream.getTracks().forEach(track => current.tracks.add(track));
              if (event?.type === 'removetrack') { event.track?.stop(); current.tracks.delete(event.track); }
              const track = current.stream.getAudioTracks().find(item => item.readyState === 'live');
              if (track === current.track) return;
              current.source?.disconnect(); current.source = null; current.track = track;
              if (track) {
                current.source = current.context.createMediaStreamSource(new environment.MediaStream([track]));
                current.source.connect(current.stereo);
                current.signalAfter = current.context.currentTime + FFT_SIZE / current.context.sampleRate;
              }
            } catch (_) { fail(current); }
          };
          current.stream.addEventListener('addtrack', current.sync);
          current.stream.addEventListener('removetrack', current.sync);
          current.sync();
        }
        const current = graph;
        if (current) current.signalAfter = current.context.currentTime + FFT_SIZE / current.context.sampleRate;
        current?.context.resume().catch(() => fail(current));
      } catch (_) { unavailable = true; release(); }
    }
    function pause() {
      active = false;
      graph?.context.suspend().catch(() => {});
    }
    function reset() {
      // Reuse the capture stream for this element across source replacements.
      // New media tracks are supplied by addtrack; do not create parallel taps.
      pause(); unavailable = false; lastState = ''; lastVolume = -1;
      held = [-Infinity, -Infinity]; heldUntil = [0, 0]; lastTime = -Infinity;
      if (graph) {
        graph.source?.disconnect(); graph.source = null; graph.track = null;
        graph.tracks.forEach(track => track.stop()); graph.tracks.clear();
      }
    }
    function sample(now) {
      if (disposed) return null;
      if (unavailable) return empty('unavailable');
      if (!active || audio.paused || audio.ended || audio.error || audio.seeking) return empty('idle');
      if (!graph?.source || graph.context.state !== 'running' || graph.track?.muted || graph.context.currentTime < graph.signalAfter) return empty('waiting');
      const volume = audio.muted ? 0 : audio.volume;
      if (!volume) return empty('silent');
      if (now - lastTime < FRAME_MS && volume === lastVolume) return null;
      if (volume !== lastVolume) { held = [-Infinity, -Infinity]; heldUntil = [0, 0]; }
      const elapsed = Number.isFinite(lastTime) ? Math.max(0, Math.min(100, now - lastTime)) : 0;
      lastTime = now; lastVolume = volume; lastState = 'active';
      try {
        const channels = graph.analysers.map((analyser, channel) => {
          analyser.getFloatTimeDomainData(graph.buffers[channel]);
          const value = measure(graph.buffers[channel], volume);
          if (value.peakDb >= held[channel]) { held[channel] = value.peakDb; heldUntil[channel] = now + HOLD_MS; }
          else if (now >= heldUntil[channel]) held[channel] = Math.max(value.peakDb, held[channel] - elapsed * .03);
          return { ...value, peak: fraction(held[channel]) };
        });
        return { state: 'active', channels };
      } catch (_) { fail(graph); return empty('unavailable'); }
    }
    function dispose() { disposed = true; active = false; release(); }
    return Object.freeze({ start, pause, reset, sample, dispose });
  }
  window.DesktopAudioMeter = Object.freeze({ create, measure });
})();
