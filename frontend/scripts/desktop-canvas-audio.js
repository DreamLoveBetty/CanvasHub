// Independent audio material/result node. Persistent metadata belongs to live canvas
// nodes; players, object URLs, decode jobs and RAFs belong only to this controller.
(function () {
  const WIDTH = 800, HEIGHT = 360, PEAK_COUNT = 240;
  const DECODE_MAX_SECONDS = 15 * 60;
  const MIME_BY_EXTENSION = Object.freeze({ mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4', aac: 'audio/aac', ogg: 'audio/ogg', flac: 'audio/flac', webm: 'audio/webm', opus: 'audio/ogg' });
  const ICON = '<svg viewBox="0 0 24 24" class="desk-node-icon" aria-hidden="true"><path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/></svg>';
  const PLAY_ICONS = Object.freeze({play: '<path d="m9 5 11 7-11 7z"/>', pause: '<path d="M7 5h3v14H7zM14 5h3v14h-3z"/>'});
  const MENU_ITEM = Object.freeze({ type: 'audio', title: '音频节点', subtitle: '音频素材与结果', icon: ICON });
  const finite = (value, fallback = 0, max = 1e9) => Number.isFinite(Number(value)) ? Math.min(max, Math.max(0, Number(value))) : fallback;

  function mediaUrl(value) {
    const url = String(value || '').trim();
    if (/^https?:\/\//i.test(url) || /^\/(?!\/)/.test(url)) return url;
    return '';
  }

  function normalizeState(node) {
    node.type = 'audio'; node.width = WIDTH; node.height = HEIGHT;
    node.mediaName = String(node.mediaName || '未导入音频').slice(0, 180);
    node.mediaUrl = mediaUrl(node.mediaUrl);
    node.audioAssetId = /^audio-[a-z0-9-]+$/i.test(String(node.audioAssetId || '')) ? String(node.audioAssetId) : '';
    node.mimeType = /^audio\/[a-z0-9.+-]+$/i.test(String(node.mimeType || '')) ? String(node.mimeType).toLowerCase() : '';
    node.fileSize = finite(node.fileSize);
    node.durationSeconds = finite(node.durationSeconds, 0, 7 * 86400);
    node.sampleRate = finite(node.sampleRate, 0, 384000);
    node.channels = Math.floor(finite(node.channels, 0, 32));
    node.peaks = Array.isArray(node.peaks) ? node.peaks.slice(0, PEAK_COUNT).map(v => finite(v, 0, 1)) : [];
    node.volume = finite(node.volume ?? 0.8, 0.8, 1);
    node.loop = node.loop === true;
    node.sourceTaskId = String(node.sourceTaskId || '').slice(0, 180);
    if (node.audioData && (!/^data:audio\/[a-z0-9.+-]+;base64,/i.test(node.audioData) || node.audioData.length > 140000000)) delete node.audioData;
    return node;
  }

  function createState(id, position = {}) {
    // Canvas coordinates may be negative; media dimensions and time may not.
    const coordinate = value => Number.isFinite(Number(value)) ? Number(value) : 0;
    return normalizeState({ id, type: 'audio', x: coordinate(position.x), y: coordinate(position.y), volume: 0.8 });
  }

  function formatTime(seconds) {
    const value = Math.floor(finite(seconds));
    const pad = n => String(n).padStart(2, '0');
    return value >= 3600 ? `${pad(Math.floor(value / 3600))}:${pad(Math.floor(value / 60) % 60)}:${pad(value % 60)}` : `${pad(Math.floor(value / 60))}:${pad(value % 60)}`;
  }

  function formatSize(bytes) {
    const value = finite(bytes);
    return value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : value ? `${Math.ceil(value / 1024)} KB` : '—';
  }

  function extractPeaks(buffer, count = PEAK_COUNT) {
    const result = new Array(count).fill(0);
    const channels = Math.min(buffer.numberOfChannels, 2);
    for (let channel = 0; channel < channels; channel++) {
      const data = buffer.getChannelData(channel);
      for (let bucket = 0; bucket < count; bucket++) {
        const start = Math.floor(bucket * data.length / count), end = Math.floor((bucket + 1) * data.length / count);
        const stride = Math.max(1, Math.floor((end - start) / 256));
        let peak = 0;
        for (let i = start; i < end; i += stride) peak = Math.max(peak, Math.abs(data[i]));
        result[bucket] = Math.max(result[bucket], Math.min(1, peak));
      }
    }
    return result;
  }

  function waveformPath(peaks) {
    return peaks.map((peak, i) => {
      const x = (i + 0.5) * 1000 / peaks.length, h = Math.max(1, finite(peak, 0, 1) * 32);
      return `M${x.toFixed(2)},${(38 - h).toFixed(2)}V${(38 + h).toFixed(2)}`;
    }).join('');
  }

  function nodeHtml(node, escapeHtml, stateIcon) {
    const id = escapeHtml(node.id);
    return `<section class="desk-node desk-node--audio" data-node-id="${id}" aria-label="音频节点" data-i18n-skip>
      <header class="desk-audio__header" data-node-drag-handle><span>${ICON}<strong>音频</strong><em>AUDIO</em></span><div><span class="desk-status-pill" data-audio-status>待导入</span><button type="button" class="desk-node-delete" data-node-delete title="删除音频节点" aria-label="删除音频节点">删</button></div></header>
      <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${id}" data-value-type="audio" aria-label="音频输入端点" title="音频模型结果输入"></button>
      <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${id}" data-value-type="audio" aria-label="音频输出端点" title="音频输出 · 转谱 / 结果对比"></button>
      <div class="desk-audio__timeline" data-node-drag-ignore>
        <svg class="desk-audio__wave" viewBox="0 0 1000 76" preserveAspectRatio="none" aria-hidden="true"><path d="M0 38H1000" class="desk-audio__baseline"/><path data-audio-wave/><svg class="desk-audio__wave-progress" data-audio-played-window x="0" y="0" width="0" height="76" overflow="hidden"><path data-audio-wave-played/></svg></svg>
        <span class="desk-audio__wave-hint" data-audio-wave-hint>导入音频后显示波形</span>
        <span class="desk-audio__playhead" data-audio-playhead aria-hidden="true"></span>
        <input class="desk-audio__seek" data-audio-seek type="range" min="0" max="1000" value="0" step="1" aria-label="音频播放位置" disabled>
        <div class="desk-audio__ruler" data-audio-ruler aria-hidden="true"><span>00:00</span><span>—</span><span>—</span><span>—</span><span>—</span><span>—</span></div>
      </div>
      <div class="desk-audio__body" data-node-drag-ignore>
        <div class="desk-audio__display"><div><span data-audio-format>AUDIO FILE</span><span data-audio-channel-mark>— CH</span></div><strong data-audio-clock>00:00</strong><p><span data-audio-duration>总时长 —</span><span data-audio-loop-label>单次播放</span></p>
          <div class="desk-audio__meter" data-audio-meter data-meter-state="idle" title="输出电平 · 随节点音量变化，不代表系统扬声器响度">
            ${['L', 'R'].map((channel, i) => `<div class="desk-audio__meter-row"><span>${channel}</span><span class="desk-audio__meter-track" data-audio-meter-channel="${i}" role="meter" aria-label="${i ? '右' : '左'}声道输出电平" aria-valuemin="-60" aria-valuemax="0" aria-valuenow="-60" aria-valuetext="静音"><i class="desk-audio__meter-fill" data-audio-meter-fill></i><i class="desk-audio__meter-peak" data-audio-meter-peak></i></span><span data-audio-meter-db aria-hidden="true">−∞</span></div>`).join('')}
            <div class="desk-audio__meter-scale" aria-hidden="true"><span class="desk-audio__meter-ticks"><i>−60</i><i>−30</i><i>0</i></span><span>dBFS</span></div><span class="desk-audio__meter-note" data-audio-meter-note hidden>电平不可用</span>
          </div><small data-audio-tech>等待音频素材</small></div>
        <div class="desk-audio__file"><strong data-audio-name title="${escapeHtml(node.mediaName)}">${escapeHtml(node.mediaName)}</strong><span data-audio-size>—</span><dl><div><dt>声道</dt><dd data-audio-channels>—</dd></div><div><dt>解码采样</dt><dd data-audio-rate>—</dd></div></dl><span class="desk-audio__source" data-audio-source>素材 / 模型结果</span></div>
        <div class="desk-audio__wheel" role="group" aria-label="音频播放控制">
          <button type="button" data-audio-action="volume-up" class="desk-audio__wheel-top" aria-label="增大音量" title="增大音量"><svg viewBox="0 0 24 24"><path d="m7 14 5-5 5 5"/></svg></button>
          <button type="button" data-audio-action="back" class="desk-audio__wheel-left" aria-label="后退 10 秒" title="后退 10 秒" data-audio-needs-media disabled><svg viewBox="0 0 24 24"><path d="m11 6-6 6 6 6m8-12-6 6 6 6"/></svg></button>
          <button type="button" data-audio-action="play" class="desk-audio__play" aria-label="播放音频" title="播放音频" data-audio-needs-media disabled>${stateIcon.html(PLAY_ICONS, 'play')}</button>
          <button type="button" data-audio-action="forward" class="desk-audio__wheel-right" aria-label="前进 10 秒" title="前进 10 秒" data-audio-needs-media disabled><svg viewBox="0 0 24 24"><path d="m5 6 6 6-6 6m8-12 6 6-6 6"/></svg></button>
          <button type="button" data-audio-action="volume-down" class="desk-audio__wheel-bottom" aria-label="减小音量" title="减小音量"><svg viewBox="0 0 24 24"><path d="m7 10 5 5 5-5"/></svg></button>
        </div>
        <div class="desk-audio__side"><button type="button" class="desk-audio__round" data-audio-action="stop" aria-label="停止音频" title="停止并回到开头" data-audio-needs-media disabled><svg viewBox="0 0 24 24"><path d="M7 7h10v10H7z"/></svg></button><span>停止</span><button type="button" class="desk-audio__round" data-audio-action="loop" aria-label="循环播放" title="循环播放" aria-pressed="false"><svg viewBox="0 0 24 24"><path d="M4 10V7h14l-3-3M20 14v3H6l3 3"/></svg></button><span>循环</span></div>
      </div>
      <footer class="desk-audio__footer" data-node-drag-ignore><div class="desk-audio__actions"><button type="button" data-audio-action="import">导入音频</button><button type="button" data-audio-action="download" data-audio-needs-media disabled>下载原音频</button></div><span class="desk-audio__message" data-audio-message role="status">音频素材 / 模型结果 · 本地播放</span><label class="desk-audio__volume"><button type="button" data-audio-action="mute" aria-label="静音" title="静音"><svg viewBox="0 0 24 24"><path d="M4 9h4l5-4v14l-5-4H4zm12-1c3 2 3 6 0 8"/></svg></button><input type="range" min="0" max="100" value="80" step="1" data-audio-volume aria-label="音频音量"><output data-audio-volume-value>80%</output></label></footer>
      <input type="file" data-audio-file accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac,.webm,.opus" hidden><audio data-audio-player preload="metadata" hidden></audio>
    </section>`;
  }

  function create({ assets, meters, getNodeState, getNodeElement, saveState, escapeHtml, stateIcon }) {
    const sessions = new Map();
    let decodeQueue = Promise.resolve();
    const live = session => sessions.get(session.id) === session && getNodeState(session.id) === session.node && getNodeElement(session.id) === session.element && session.element.isConnected;
    const text = (s, selector, value) => { s.element.querySelector(selector).textContent = value; };
    const sourceKey = n => `${n.audioAssetId}\n${n.mediaUrl}\n${n.audioData ? 'embedded' : ''}`;
    function message(s, value, error = false) {
      if (!live(s)) return;
      text(s, '[data-audio-message]', value);
      s.element.querySelector('[data-audio-message]').classList.toggle('is-error', error);
    }
    function paintMeter(s) {
      const reading = s.meter?.sample(performance.now());
      if (!reading) return;
      s.meterElement.dataset.meterState = reading.state;
      s.meterElement.querySelector('[data-audio-meter-note]').hidden = reading.state !== 'unavailable';
      s.meterChannels.forEach((channel, i) => {
        const value = reading.channels[i], audible = Number.isFinite(value.db);
        channel.querySelector('[data-audio-meter-fill]').style.transform = `scaleX(${value.level})`;
        const peak = channel.querySelector('[data-audio-meter-peak]');
        peak.style.left = `${value.peak * 100}%`; peak.style.opacity = value.peak > 0 ? '1' : '0';
        channel.classList.toggle('is-hot', value.peakDb >= -1);
        const label = reading.state === 'unavailable' || reading.state === 'waiting' ? '—' : audible ? value.db.toFixed(1) : '−∞';
        channel.parentElement.querySelector('[data-audio-meter-db]').textContent = label;
        channel.setAttribute('aria-valuenow', String(audible ? Math.max(-60, Math.min(0, value.db)).toFixed(1) : -60));
        channel.setAttribute('aria-valuetext', label === '—' ? '电平暂不可用' : audible ? `${label} dBFS` : '静音');
      });
    }
    function paintPosition(s) {
      if (!live(s)) return;
      const n = s.node, a = s.audio, ready = !!a.getAttribute('src') && Number.isFinite(a.duration) && a.duration > 0 && !a.error;
      const seek = s.element.querySelector('[data-audio-seek]');
      const duration = ready ? a.duration : n.durationSeconds;
      const current = ready ? finite(a.currentTime) : 0, progress = ready ? Math.min(1, current / duration) : 0;
      seek.disabled = !ready; seek.value = String(Math.round(progress * 1000));
      seek.setAttribute('aria-valuetext', `${formatTime(current)} / ${formatTime(duration)}`);
      s.element.querySelector('[data-audio-playhead]').style.left = `${progress * 100}%`;
      // Nested SVG clips the same sample path, without scaling it or sharing IDs
      // between nodes. Only this viewport and the cursor move during playback.
      s.element.querySelector('[data-audio-played-window]').setAttribute('width', String(progress * 1000));
      text(s, '[data-audio-clock]', formatTime(current)); text(s, '[data-audio-duration]', `总时长 ${duration ? formatTime(duration) : '—'}`);
      paintMeter(s);
    }
    function paint(s) {
      if (!live(s)) return;
      const n = s.node, a = s.audio, ready = !!a.getAttribute('src') && Number.isFinite(a.duration) && a.duration > 0 && !a.error;
      const playing = ready && !a.paused && !a.ended;
      const status = s.element.querySelector('[data-audio-status]');
      status.textContent = s.loading ? '载入中' : playing ? '播放中' : ready ? '就绪' : s.failed ? '不可用' : '待导入';
      status.className = `desk-status-pill${ready ? ' is-success' : s.failed ? ' is-error' : ''}`;
      s.element.classList.toggle('is-playing', playing);
      s.element.querySelectorAll('[data-audio-needs-media]').forEach(button => { button.disabled = !ready; });
      const play = s.element.querySelector('[data-audio-action="play"]');
      play.setAttribute('aria-label', playing ? '暂停音频' : '播放音频'); play.title = playing ? '暂停音频' : '播放音频';
      stateIcon.paint(play.querySelector('svg'), playing ? 'pause' : 'play');
      const duration = ready ? a.duration : n.durationSeconds;
      paintPosition(s);
      text(s, '[data-audio-name]', n.mediaName); s.element.querySelector('[data-audio-name]').title = n.mediaName;
      text(s, '[data-audio-size]', formatSize(n.fileSize));
      const format = (n.mimeType.split('/')[1] || 'AUDIO FILE').toUpperCase().replace('MPEG', 'MP3');
      text(s, '[data-audio-format]', format); text(s, '[data-audio-channel-mark]', n.channels ? `${n.channels} CH` : '— CH');
      text(s, '[data-audio-channels]', n.channels === 1 ? '单声道' : n.channels === 2 ? '立体声' : n.channels ? `${n.channels} 声道` : '—');
      text(s, '[data-audio-rate]', n.sampleRate ? `${(n.sampleRate / 1000).toFixed(1)} kHz` : '—');
      text(s, '[data-audio-tech]', n.sampleRate ? `解码 ${n.sampleRate.toLocaleString()} Hz · ${n.channels} CH` : ready ? '原音频播放' : '等待音频素材');
      text(s, '[data-audio-source]', n.sourceTaskId ? '模型结果' : n.audioAssetId ? '本地音频' : '素材 / 模型结果');
      text(s, '[data-audio-loop-label]', n.loop ? '循环播放' : '单次播放');
      s.element.querySelector('[data-audio-action="loop"]').setAttribute('aria-pressed', String(n.loop));
      s.element.querySelector('[data-audio-volume]').value = String(Math.round(n.volume * 100));
      text(s, '[data-audio-volume-value]', `${Math.round(n.volume * 100)}%`);
      const mute = s.element.querySelector('[data-audio-action="mute"]'); mute.setAttribute('aria-label', n.volume ? '静音' : '取消静音'); mute.title = n.volume ? '静音' : '取消静音';
      s.element.querySelectorAll('[data-audio-ruler] span').forEach((el, i) => { el.textContent = duration ? formatTime(duration * i / 5) : i ? '—' : '00:00'; });
      if (s.paintedPeaks !== n.peaks) {
        const path = waveformPath(n.peaks);
        s.element.querySelector('[data-audio-wave]').setAttribute('d', path);
        s.element.querySelector('[data-audio-wave-played]').setAttribute('d', path);
        s.paintedPeaks = n.peaks;
      }
      const hint = s.element.querySelector('[data-audio-wave-hint]'); hint.hidden = !!n.peaks.length;
      hint.textContent = ready ? s.decoding ? '正在解析波形…' : s.waveformNote || '音频已就绪 · 波形暂不可用' : '导入音频后显示波形';
    }
    function tick(s) {
      s.frame = 0;
      if (!live(s)) return;
      paintPosition(s);
      if (!s.audio.paused && !s.audio.ended) s.frame = requestAnimationFrame(() => tick(s));
    }
    function dispose(id) {
      const s = sessions.get(id); if (!s) return;
      sessions.delete(id); s.controller.abort(); cancelAnimationFrame(s.frame); s.decodeContext?.close().catch(() => {});
      s.audio.pause(); s.audio.removeAttribute('src'); s.audio.load();
      s.meter?.dispose();
      if (s.url) URL.revokeObjectURL(s.url);
    }
    function disposeAll() { [...sessions.keys()].forEach(dispose); }
    function setVolume(s, value) { s.node.volume = finite(value, 0.8, 1); s.audio.volume = s.node.volume; paint(s); }
    async function decode(s, blob) {
      if (!Number.isFinite(s.audio.duration) || s.audio.duration <= 0 || s.node.peaks.length || s.decoding) return;
      const Context = window.AudioContext || window.webkitAudioContext;
      // Files accepted by the audio asset store must not hit a second, smaller
      // compressed-byte limit here. Retain the duration guard for decoded PCM.
      s.waveformNote = !blob ? '音频已就绪 · 在线音频尚无本地波形'
        : blob.size > assets.MAX_FILE_BYTES ? '音频超过波形解析的文件大小上限'
        : s.audio.duration > DECODE_MAX_SECONDS ? '音频超过 15 分钟，已跳过波形解析'
        : !Context ? '当前浏览器不支持波形解析' : '';
      if (s.waveformNote) { paint(s); return; }
      const key = sourceKey(s.node), version = s.version;
      const current = () => live(s) && version === s.version && key === sourceKey(s.node);
      s.decoding = true; paint(s);
      const run = async () => {
        if (!current()) return;
        let context;
        try {
          context = new Context(); s.decodeContext = context;
          const buffer = await context.decodeAudioData(await blob.arrayBuffer());
          if (!current()) return;
          s.node.peaks = extractPeaks(buffer); s.node.sampleRate = buffer.sampleRate; s.node.channels = buffer.numberOfChannels;
          saveState();
        } catch (error) {
          if (current()) s.waveformNote = '波形解析失败，仍可播放原音频';
        } finally {
          if (context) await context.close().catch(() => {});
          if (current()) { s.decoding = false; s.decodeContext = null; paint(s); }
        }
      };
      // Restoring several full-song nodes must not allocate all PCM buffers at
      // once. A failed/deleted/replaced source cannot block or overwrite the next.
      decodeQueue = decodeQueue.then(run, run);
      await decodeQueue;
    }
    async function load(s) {
      const version = ++s.version; s.loading = true; s.failed = false; s.blob = null;
      if (!s.meter) s.meter = meters?.create(s.audio);
      s.meter?.reset();
      s.decodeContext?.close().catch(() => {}); s.decodeContext = null; s.decoding = false; s.waveformNote = '';
      cancelAnimationFrame(s.frame); s.audio.pause(); s.audio.removeAttribute('src'); s.audio.load();
      if (s.url) { URL.revokeObjectURL(s.url); s.url = ''; }
      paint(s);
      try {
        if (s.node.audioData) {
          const embedded = s.node.audioData;
          const id = await assets.put(assets.fromDataUrl(embedded));
          if (!live(s) || version !== s.version) { await assets.remove(id); return; }
          s.node.audioAssetId = id; delete s.node.audioData; saveState();
        }
        const blob = s.node.audioAssetId ? await assets.get(s.node.audioAssetId) : null;
        if (!live(s) || version !== s.version) return;
        if (s.node.audioAssetId && !blob) throw new Error('本地音频已丢失，请重新导入');
        s.blob = blob; s.key = sourceKey(s.node);
        const src = blob ? (s.url = URL.createObjectURL(blob)) : s.node.mediaUrl;
        if (src) { s.audio.src = src; s.audio.load(); }
        else message(s, '音频素材 / 模型结果 · 本地播放');
      } catch (error) { if (live(s) && version === s.version) { s.failed = true; message(s, error.message, true); } }
      finally { if (live(s) && version === s.version) { s.loading = false; paint(s); } }
    }
    async function importFile(nodeId, file) {
      const s = sessions.get(nodeId); if (!s || !live(s)) return false;
      const extension = String(file?.name || '').split('.').pop().toLowerCase();
      const mime = /^audio\/[a-z0-9.+-]+$/i.test(file?.type || '') ? file.type : MIME_BY_EXTENSION[extension];
      if (!mime) { message(s, '请选择 MP3、WAV、M4A、AAC、OGG 或 FLAC 音频', true); return false; }
      const token = ++s.importToken;
      message(s, '正在保存音频…');
      try {
        const blob = file.type === mime ? file : file.slice(0, file.size, mime);
        const id = await assets.put(blob);
        if (!live(s) || token !== s.importToken) { await assets.remove(id); return false; }
        Object.assign(s.node, { audioAssetId: id, mediaUrl: '', mediaName: String(file.name || '音频').slice(0, 180), mimeType: mime, fileSize: blob.size, peaks: [], durationSeconds: 0, sampleRate: 0, channels: 0, sourceTaskId: '' });
        delete s.node.audioData; saveState(); s.key = sourceKey(s.node); await load(s); return true;
      } catch (error) { message(s, error.message || '音频导入失败', true); return false; }
    }
    async function action(s, name) {
      try {
        if (name === 'import') { s.element.querySelector('[data-audio-file]').click(); return; }
        if (name === 'play') {
          if (s.audio.paused) { sessions.forEach(other => { if (other !== s) other.audio.pause(); }); s.meter?.start(); await s.audio.play(); }
          else s.audio.pause();
        } else if (name === 'stop') { s.audio.pause(); s.audio.currentTime = 0; }
        else if (name === 'back' || name === 'forward') s.audio.currentTime = Math.min(finite(s.audio.duration), Math.max(0, s.audio.currentTime + (name === 'back' ? -10 : 10)));
        else if (name === 'loop') { s.node.loop = !s.node.loop; s.audio.loop = s.node.loop; saveState(); }
        else if (name === 'volume-up' || name === 'volume-down') { setVolume(s, s.node.volume + (name === 'volume-up' ? 0.1 : -0.1)); saveState(); }
        else if (name === 'mute') { const previous = s.node.volume; setVolume(s, previous ? 0 : (s.lastVolume || 0.8)); if (previous) s.lastVolume = previous; saveState(); }
        else if (name === 'download') {
          const anchor = document.createElement('a'); anchor.href = s.audio.currentSrc || s.audio.src; anchor.download = s.node.mediaName; anchor.rel = 'noopener'; anchor.click();
        }
        paint(s);
      } catch (error) { if (name === 'play') { s.meter?.pause(); paint(s); } message(s, name === 'play' ? '无法播放，请重新导入或使用浏览器支持的音频格式' : '音频操作失败', true); }
    }
    function mount(nodeId) {
      const node = getNodeState(nodeId), element = getNodeElement(nodeId);
      if (node?.type !== 'audio' || !element) return;
      const previous = sessions.get(nodeId);
      if (previous && live(previous)) { if (sourceKey(node) !== previous.key) load(previous); return; }
      dispose(nodeId); normalizeState(node);
      const s = { id: nodeId, node, element, audio: element.querySelector('[data-audio-player]'), controller: new AbortController(), frame: 0, version: 0, importToken: 0, key: sourceKey(node), loading: false, failed: false };
      s.meterElement = element.querySelector('[data-audio-meter]');
      s.meterChannels = [...element.querySelectorAll('[data-audio-meter-channel]')];
      sessions.set(nodeId, s); const options = { signal: s.controller.signal };
      s.audio.volume = node.volume; s.audio.loop = node.loop;
      element.addEventListener('click', event => { const button = event.target.closest('[data-audio-action]'); if (button) { event.stopPropagation(); action(s, button.dataset.audioAction); } }, options);
      element.querySelector('[data-audio-file]').addEventListener('change', event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) importFile(nodeId, file); }, options);
      element.querySelector('[data-audio-seek]').addEventListener('input', event => { if (Number.isFinite(s.audio.duration)) s.audio.currentTime = s.audio.duration * Number(event.target.value) / 1000; paint(s); }, options);
      element.querySelector('[data-audio-volume]').addEventListener('input', event => setVolume(s, Number(event.target.value) / 100), options);
      element.querySelector('[data-audio-volume]').addEventListener('change', () => saveState(), options);
      // Node-local files never enter the canvas's image drop pipeline.
      element.addEventListener('dragover', event => { if (event.dataTransfer?.types?.includes('Files')) { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'copy'; } }, options);
      element.addEventListener('drop', event => { if (event.dataTransfer?.files?.length) { event.preventDefault(); event.stopPropagation(); importFile(nodeId, event.dataTransfer.files[0]); } }, options);
      s.audio.addEventListener('loadedmetadata', () => {
        if (!live(s)) return;
        if (Number.isFinite(s.audio.duration)) { s.node.durationSeconds = s.audio.duration; saveState(); }
        message(s, '音频素材 / 模型结果 · 本地播放'); paint(s); decode(s, s.blob);
      }, options);
      s.audio.addEventListener('error', () => { if (live(s) && s.audio.getAttribute('src')) { s.failed = true; s.meter?.pause(); message(s, '无法读取音频，请检查文件或重新导入', true); paint(s); } }, options);
      ['play', 'pause', 'ended', 'durationchange'].forEach(name => s.audio.addEventListener(name, () => {
        if (name === 'play') s.meter?.start();
        else if (name === 'pause' || name === 'ended') s.meter?.pause();
        paint(s); cancelAnimationFrame(s.frame); tick(s);
      }, options));
      ['volumechange', 'seeking', 'seeked'].forEach(name => s.audio.addEventListener(name, () => paintMeter(s), options));
      s.audio.addEventListener('timeupdate', () => paintPosition(s), options);
      paint(s); load(s);
    }
    function reconcile() {
      [...sessions.values()].forEach(s => { if (!live(s)) dispose(s.id); });
      document.querySelectorAll('.desk-node--audio[data-node-id]').forEach(el => mount(el.dataset.nodeId));
    }
    // Future Provider adapters translate backend snake_case at this explicit boundary.
    async function setResult(nodeId, result = {}) {
      const s = sessions.get(nodeId); if (!s || !live(s)) throw new Error('音频节点不存在');
      const token = ++s.importToken;
      const suppliedBlob = result.blob instanceof Blob ? result.blob : null;
      const mime = String(result.mime_type || suppliedBlob?.type || '').toLowerCase();
      if (suppliedBlob && !/^audio\/[a-z0-9.+-]+$/.test(mime)) throw new Error('音频 Blob 需要有效的 audio MIME 类型');
      const blob = suppliedBlob && suppliedBlob.type !== mime ? suppliedBlob.slice(0, suppliedBlob.size, mime) : suppliedBlob;
      const id = blob ? await assets.put(blob) : '';
      if (!live(s) || token !== s.importToken) { if (id) await assets.remove(id); return false; }
      const url = mediaUrl(result.url);
      if (!id && !url) throw new Error('音频结果需要可播放的 URL 或 Blob');
      Object.assign(s.node, { audioAssetId: id, mediaUrl: url, mediaName: String(result.name || '模型音频').slice(0, 180), mimeType: result.mime_type || result.blob?.type || '', fileSize: result.file_size || result.blob?.size || 0, durationSeconds: result.duration_seconds || 0, sourceTaskId: result.task_id || '', peaks: [], sampleRate: 0, channels: 0 });
      delete s.node.audioData; normalizeState(s.node); saveState(); s.key = sourceKey(s.node); await load(s); return true;
    }
    async function getInput(nodeId) {
      const node = getNodeState(nodeId); if (node?.type !== 'audio') return null;
      const key = sourceKey(node);
      const blob = node.audioAssetId ? await assets.get(node.audioAssetId) : null;
      if (getNodeState(nodeId) !== node || key !== sourceKey(node)) return null;
      return blob || node.mediaUrl ? { data_type: 'audio', blob, url: node.mediaUrl, name: node.mediaName, mime_type: node.mimeType, duration_seconds: node.durationSeconds, file_size: node.fileSize } : null;
    }
    return Object.freeze({ mount, reconcile, dispose, disposeAll, importFile, setResult, getInput, nodeHtml: node => nodeHtml(normalizeState(node), escapeHtml, stateIcon) });
  }
  window.DesktopCanvasAudio = Object.freeze({ WIDTH, HEIGHT, MENU_ITEM, normalizeState, createState, formatTime, formatSize, extractPeaks, waveformPath, create });
})();
