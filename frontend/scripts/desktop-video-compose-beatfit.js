// One-click beat cutting for the compose workbench: new out points so every clip ends on a music
// beat on the output timeline. Pure planning over the clip views (probe, frames, speed, transition)
// and the beat list; the caller applies the result, keeps an undo copy and re-renders.
// In points stay where the user put them: only end frames move. Modes:
//   'nearest' — each clip ends on the beat nearest its current end (keeps the edit, fixes the timing);
//   2 / 4 / 8 — each clip lasts that many beats from the beat at its start.
// A clip whose source cannot reach its beat ends on the latest beat it can reach (`short`); one that
// reaches no beat at all keeps its trim (`missed`). Transitions overlap neighbours, so a clip's end
// depends on the next clip's length: the plan is re-solved until every end holds (three passes).
(function () {
  const PASSES = 3;

  function create({model}) {
    // End frame whose window stop is nearest `stop` source seconds, from `startFrame` on.
    function endFrameFor(probe, startFrame, stop) {
      const times = probe.frameTimes, count = times.length;
      let low = startFrame, high = count - 1;
      const stopOf = frame => model.clipWindow(probe, startFrame, frame).stop;
      while (low < high) {
        const middle = (low + high) >> 1;
        if (stopOf(middle) < stop) low = middle + 1; else high = middle;
      }
      if (low > startFrame && Math.abs(stopOf(low - 1) - stop) <= Math.abs(stopOf(low) - stop)) low -= 1;
      return low;
    }

    const encode = (probe, frame) => frame >= probe.frameTimes.length - 1 ? -1 : frame;

    // clips: views with {probe, startFrame, endFrame, speed, transition}; beats: sorted output seconds.
    // Returns {ends: [endFrame | undefined per clip], aligned, short: [k], missed: [k], changed}.
    function plan(clips, beats, mode) {
      const work = clips.map(clip => ({...clip}));
      const per = mode === 'nearest' ? 0 : Math.max(1, Number(mode) || 4);
      const targets = new Array(work.length).fill(null);
      const short = new Set(), missed = new Set();
      const windows = () => work.map(clip => clip.probe ? model.clipWindow(clip.probe, clip.startFrame, clip.endFrame) : null);
      const segmentEnd = k => { const s = model.timing(work, windows()).segments[k]; return s.from + s.length; };
      const nearestIndex = time => beats.reduce((best, beat, i) => Math.abs(beat - time) < Math.abs(beats[best] - time) ? i : best, 0);

      // Output end of clip k with out point `frame` (everything else as planned so far).
      function endWith(k, frame) {
        const saved = work[k].endFrame;
        work[k].endFrame = encode(work[k].probe, frame);
        const end = segmentEnd(k);
        work[k].endFrame = saved;
        return end;
      }

      // Out point that puts clip k's end nearest `time`; the source stop it needs moves by the miss × speed.
      function solve(k, time) {
        const clip = work[k], speed = clip.speed || 1;
        let frame = model.clipWindow(clip.probe, clip.startFrame, clip.endFrame).endFrame;
        for (let step = 0; step < 4; step += 1) {
          const miss = time - endWith(k, frame);
          if (Math.abs(miss) < 1e-4) break;
          const stop = model.clipWindow(clip.probe, clip.startFrame, frame).stop + miss * speed;
          const next = endFrameFor(clip.probe, clip.startFrame, stop);
          if (next === frame) break;
          frame = next;
        }
        return frame;
      }

      for (let pass = 0; pass < PASSES; pass += 1) {
        for (let k = 0; k < work.length; k += 1) {
          const clip = work[k];
          if (!clip.probe || !beats.length) { missed.add(k); continue; }
          const last = clip.probe.frameTimes.length - 1;
          const shortest = model.MIN_CLIP_SECONDS * (clip.speed || 1) - 1e-6;
          let first = clip.startFrame;
          while (first < last && model.clipWindow(clip.probe, clip.startFrame, first).seconds < shortest) first += 1;
          const lo = endWith(k, first), hi = endWith(k, last);
          if (pass === 0) {
            const from = model.timing(work, windows()).segments[k].from;
            const wanted = per ? nearestIndex(from) + per : nearestIndex(segmentEnd(k));
            let index = Math.min(wanted, beats.length - 1);
            while (index >= 0 && beats[index] > hi + 1e-6) index -= 1;
            while (index >= 0 && index < beats.length - 1 && beats[index] < lo - 1e-6 && beats[index + 1] <= hi + 1e-6) index += 1;
            if (index < 0 || beats[index] < lo - 1e-6 || beats[index] <= from + 1e-6) {
              missed.add(k);
              continue;
            }
            if (per && index < wanted) short.add(k);
            targets[k] = beats[index];
          }
          if (targets[k] === null) continue;
          clip.endFrame = encode(clip.probe, solve(k, targets[k]));
        }
      }
      const ends = work.map((clip, k) => targets[k] === null ? undefined : clip.endFrame);
      const changed = ends.filter((end, k) => end !== undefined && end !== clips[k].endFrame).length;
      return {ends, aligned: ends.filter(end => end !== undefined).length, short: [...short], missed: [...missed], changed};
    }

    return Object.freeze({plan});
  }

  window.DesktopVideoComposeBeatFit = Object.freeze({create});
})();
