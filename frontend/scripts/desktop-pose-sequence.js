// Pose sequences from video recognition: decoding, per-frame character evaluation and the keyframe
// override layer. Sequences live on the backend (one per recognition job) and are fetched once and cached;
// a character points at its person with `track` and keeps manual fixes as `keys` (absolute joint
// rotations at a frame). A key's correction (key rotation x recognised rotation^-1) is interpolated
// between keys of the same joint and fades out over FALLOFF frames beyond the first and last key, so a
// one-frame fix stays local and the recognition itself is never changed.
(function () {
  const FALLOFF = 10;
  const IDENTITY = Object.freeze([0, 0, 0, 1]);

  const mul = (a, b) => [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
  const conj = q => [-q[0], -q[1], -q[2], q[3]];
  function slerp(a, b, t) {
    let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
    const sign = d < 0 ? -1 : 1;
    d *= sign;
    if (d > 0.9995) {
      const out = a.map((v, i) => v + (sign * b[i] - v) * t), n = Math.hypot(...out);
      return out.map(v => v / n);
    }
    const theta = Math.acos(d), s = Math.sin(theta), wa = Math.sin((1 - t) * theta) / s, wb = Math.sin(t * theta) / s * sign;
    return a.map((v, i) => wa * v + wb * b[i]);
  }
  function fromAxisAngle(x, y, z) {
    const angle = Math.hypot(x, y, z);
    if (angle < 1e-9) return [...IDENTITY];
    const s = Math.sin(angle / 2) / angle;
    return [x * s, y * s, z * s, Math.cos(angle / 2)];
  }
  function floats(text) {
    const raw = atob(String(text || '').replace(/^base64:/, ''));
    if (raw.length % 4) throw new Error('识别结果格式无效');
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return new Float32Array(bytes.buffer);
  }

  // Backend result (snake_case) -> typed arrays per person.
  function decode(result) {
    const frameCount = Math.max(1, Math.round(Number(result?.frame_count) || 0));
    const people = (result?.people || []).map(p => {
      const f = p.frames || {}, count = Math.round(Number(f.count) || 0), rotations = floats(f.rotations);
      if (!count || rotations.length !== count * 77 * 3 || (f.transl || []).length !== count) throw new Error('识别序列数据不完整');
      return {start: Math.max(0, Math.round(Number(f.start) || 0)), count, rotations,
        transl: Float32Array.from(f.transl.flat()), lift: Float32Array.from(f.lift || new Array(count).fill(0)),
        hips: Array.isArray(f.hips) && f.hips.length === count ? Float32Array.from(f.hips) : null,
        confidence: Float32Array.from(p.confidence || new Array(count).fill(1))};
    });
    return {fps: Number(result?.fps) || 30, frameCount, people};
  }

  function create({model, fetchResult}) {
    const cache = new Map();   // job id -> Promise<sequence>
    const loaded = new Map();  // job id -> sequence (synchronous access once fetched)
    const names = model.SOMA_JOINTS.slice(1);

    function load(jobId) {
      if (!cache.has(jobId)) {
        const pending = fetchResult(jobId).then(result => { const s = decode(result); loaded.set(jobId, s); return s; });
        cache.set(jobId, pending);
        pending.catch(() => cache.delete(jobId));
      }
      return cache.get(jobId);
    }
    const peek = jobId => loaded.get(jobId) || null;

    // Recognised rotations of a person at a clip frame (clamped to the person's span).
    function baseRotations(person, frame) {
      const local = Math.min(person.count - 1, Math.max(0, frame - person.start)), out = {};
      for (let j = 0; j < 77; j++) {
        const o = (local * 77 + j) * 3;
        out[names[j]] = fromAxisAngle(person.rotations[o], person.rotations[o + 1], person.rotations[o + 2]);
      }
      return out;
    }
    // The override layer: per joint, the interpolated correction at `frame` from that joint's keys.
    function correction(keys, joint, frame, person) {
      const list = keys.filter(k => k.rotations[joint]).sort((a, b) => a.frame - b.frame);
      if (!list.length) return null;
      const delta = k => mul(k.rotations[joint], conj(baseRotations(person, k.frame)[joint]));
      const first = list[0], last = list[list.length - 1];
      if (frame <= first.frame) {
        const w = Math.max(0, 1 - (first.frame - frame) / FALLOFF);
        return w > 0 ? slerp([...IDENTITY], delta(first), w) : null;
      }
      if (frame >= last.frame) {
        const w = Math.max(0, 1 - (frame - last.frame) / FALLOFF);
        return w > 0 ? slerp([...IDENTITY], delta(last), w) : null;
      }
      const after = list.findIndex(k => k.frame > frame), a = list[after - 1], b = list[after];
      return slerp(delta(a), delta(b), (frame - a.frame) / (b.frame - a.frame));
    }
    function rotationsAt(character, sequence, frame) {
      const person = sequence.people[character.track.person];
      const rotations = baseRotations(person, frame);
      const keyed = new Set((character.keys || []).flatMap(k => Object.keys(k.rotations)));
      keyed.forEach(joint => {
        const c = correction(character.keys, joint, frame, person);
        if (c && rotations[joint]) rotations[joint] = mul(c, rotations[joint]);
      });
      return rotations;
    }
    // The character as the rig sees it at a frame: recognised pose + overrides; trajectory turned by its
    // yaw about the first frame's position and shifted by its position / elevation offsets. Results with
    // per-frame `hips` heights place the figure by its hips (any body lines up with the video); older ones
    // stand its lowest foot at `lift`.
    function characterAt(character, sequence, frame) {
      if (!character.track || !sequence) return character;
      const person = sequence.people[character.track.person];
      if (!person) return {...character, visible: false};
      const inside = frame >= person.start && frame < person.start + person.count;
      const local = Math.min(person.count - 1, Math.max(0, frame - person.start));
      const ox = person.transl[0], oz = person.transl[2];
      const x = person.transl[local * 3] - ox, z = person.transl[local * 3 + 2] - oz;
      const yaw = character.yaw * Math.PI / 180, cos = Math.cos(yaw), sin = Math.sin(yaw);
      return {...character, rotations: rotationsAt(character, sequence, frame), visible: character.visible && inside,
        position: [ox + x * cos + z * sin + character.position[0], oz - x * sin + z * cos + character.position[1]],
        elevation: person.lift[local] + (character.elevation || 0), grounded: true,
        ...(person.hips ? {hips: person.hips[local] + (character.elevation || 0)} : {})};
    }
    return Object.freeze({load, peek, rotationsAt, characterAt, baseRotations, FALLOFF});
  }

  window.DesktopPoseSequence = Object.freeze({create, decode, slerp, fromAxisAngle});
})();
