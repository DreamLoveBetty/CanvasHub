// Prompt/Agent media-reference adapter. Canvas owns media state; this module only
// decodes referenced videos into bounded JPEG key frames for prompt understanding.
(function () {
  const MIN_VIDEO_FRAMES = 12;
  const MAX_VIDEO_FRAMES = 24;
  const MAX_VIDEO_REFERENCES = 2;
  const MAX_FRAME_EDGE = 768;
  const FRAME_JPEG_QUALITY = 0.78;
  const CACHE_LIMIT = 6;
  const frameCache = new Map();

  function mediaKind(item = {}) {
    const explicit = String(item.mediaKind || item.media_kind || item.kind || '').trim().toLowerCase();
    if (explicit === 'video' || String(item.mimeType || item.mime_type || '').toLowerCase().startsWith('video/')) return 'video';
    return 'image';
  }

  function videoSource(item = {}) {
    return String(item.mediaUrl || item.media_url || item.videoUrl || item.video_url || item.url || '').trim();
  }

  function playableVideoSource(item = {}) {
    const source = videoSource(item);
    return typeof window.miniappMediaUrl === 'function' ? window.miniappMediaUrl(source) : source;
  }

  function frameCountForDuration(seconds) {
    const duration = Number(seconds || 0);
    if (!Number.isFinite(duration) || duration <= 0) return 16;
    if (duration <= 15) return 12;
    if (duration <= 60) return 16;
    if (duration <= 180) return 20;
    return 24;
  }

  function cacheKey(item = {}) {
    return [
      videoSource(item),
      item.sourceNodeId || item.nodeId || item.source_node_id || item.id || '',
      item.sourceTaskId || item.source_task_id || '',
      Number(item.fileSize || item.file_size || 0),
      Number(item.durationSeconds || item.duration_seconds || 0)
    ].join('|');
  }

  function getCached(key) {
    if (!key || !frameCache.has(key)) return null;
    const value = frameCache.get(key);
    frameCache.delete(key);
    frameCache.set(key, value);
    return value;
  }

  function setCached(key, value) {
    if (!key) return;
    frameCache.delete(key);
    frameCache.set(key, value);
    while (frameCache.size > CACHE_LIMIT) frameCache.delete(frameCache.keys().next().value);
  }

  function waitForVideoEvent(video, names, timeoutMs, ready) {
    if (ready?.()) return Promise.resolve();
    const events = Array.isArray(names) ? names : [names];
    return new Promise((resolve, reject) => {
      let timer = 0;
      const cleanup = () => {
        events.forEach(name => video.removeEventListener(name, onReady));
        video.removeEventListener('error', onError);
        if (timer) window.clearTimeout(timer);
      };
      const onReady = () => {
        if (ready && !ready()) return;
        cleanup();
        resolve();
      };
      const onError = () => {
        const detail = video.error?.message || `媒体错误 ${video.error?.code || ''}`.trim();
        cleanup();
        reject(new Error(detail || '视频读取失败'));
      };
      events.forEach(name => video.addEventListener(name, onReady));
      video.addEventListener('error', onError);
      timer = window.setTimeout(() => {
        cleanup();
        reject(new Error('视频读取超时'));
      }, timeoutMs);
    });
  }

  async function loadVideo(item = {}) {
    const source = playableVideoSource(item);
    if (!source) throw new Error('视频节点没有可播放地址');
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
    video.setAttribute('aria-hidden', 'true');
    video.style.cssText = 'position:fixed;left:-10000px;top:-10000px;width:1px;height:1px;opacity:0;pointer-events:none;';
    try {
      const parsed = new URL(source, window.location.href);
      if (parsed.origin !== window.location.origin) video.crossOrigin = 'anonymous';
    } catch (error) {}
    document.body.append(video);
    video.src = source;
    video.load();
    await waitForVideoEvent(video, ['loadedmetadata', 'durationchange'], 20_000, () => (
      video.readyState >= 1 && (Number.isFinite(video.duration) || Number(item.durationSeconds || item.duration_seconds) > 0)
    ));
    return video;
  }

  function resolvedDuration(video, item = {}) {
    const direct = Number(video.duration);
    if (Number.isFinite(direct) && direct > 0) return direct;
    const seekable = video.seekable;
    if (seekable?.length) {
      const end = Number(seekable.end(seekable.length - 1));
      if (Number.isFinite(end) && end > 0) return end;
    }
    const fallback = Number(item.durationSeconds || item.duration_seconds || 0);
    return Number.isFinite(fallback) && fallback > 0 ? fallback : 0;
  }

  function samplingTimes(duration, count, fps = 24) {
    const safeCount = Math.max(MIN_VIDEO_FRAMES, Math.min(MAX_VIDEO_FRAMES, Number(count || 0) || frameCountForDuration(duration)));
    const frameInset = Math.max(0.04, 1 / Math.max(1, Number(fps || 24)));
    const start = Math.min(frameInset, duration / 4);
    const end = Math.max(start, duration - frameInset);
    if (safeCount <= 1) return [Math.max(0, Math.min(duration, start))];
    if (end <= start) {
      return Array.from({ length: safeCount }, (_, index) => (
        Math.max(0, duration * 0.999 * index / (safeCount - 1))
      ));
    }
    return Array.from({ length: safeCount }, (_, index) => (
      start + ((end - start) * index / (safeCount - 1))
    ));
  }

  async function seekVideo(video, timestamp) {
    const target = Math.max(0, Number(timestamp || 0));
    if (video.readyState >= 2 && Math.abs(Number(video.currentTime || 0) - target) < 0.02) return;
    const waiting = waitForVideoEvent(video, ['seeked', 'loadeddata'], 12_000, () => (
      video.readyState >= 2 && Math.abs(Number(video.currentTime || 0) - target) < 0.12
    ));
    // fastSeek() is allowed to land on a nearby key frame.  That makes the
    // requested 12--24 samples collapse into repeated frames on long-GOP
    // videos, so V1 deliberately prefers precise sequential seeks.
    video.currentTime = target;
    await waiting;
  }

  function captureVideoFrame(video, timestamp, index) {
    const sourceWidth = Math.max(1, Number(video.videoWidth || 0));
    const sourceHeight = Math.max(1, Number(video.videoHeight || 0));
    if (sourceWidth <= 1 || sourceHeight <= 1) throw new Error('视频画面尺寸不可用');
    const scale = Math.min(1, MAX_FRAME_EDGE / Math.max(sourceWidth, sourceHeight));
    const width = Math.max(2, Math.round(sourceWidth * scale));
    const height = Math.max(2, Math.round(sourceHeight * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { alpha: false });
    if (!context) throw new Error('浏览器无法创建视频抽帧画布');
    context.drawImage(video, 0, 0, width, height);
    let dataUrl = '';
    try {
      dataUrl = canvas.toDataURL('image/jpeg', FRAME_JPEG_QUALITY);
    } catch (error) {
      throw new Error('视频画面受跨域限制，无法用于 @ 引用分析');
    }
    return {
      index: index + 1,
      timestamp_seconds: Number(Number(timestamp || 0).toFixed(3)),
      data_url: dataUrl,
      width,
      height
    };
  }

  async function sampleVideoReference(item = {}, options = {}) {
    if (mediaKind(item) !== 'video') throw new Error('抽帧对象不是视频节点');
    const key = cacheKey(item);
    const cached = options.force !== true ? getCached(key) : null;
    if (cached) return cached;
    const video = await loadVideo(item);
    try {
      const duration = resolvedDuration(video, item);
      if (!(duration > 0)) throw new Error('无法读取视频时长');
      const desiredCount = Math.max(
        MIN_VIDEO_FRAMES,
        Math.min(MAX_VIDEO_FRAMES, Number(options.frameCount || 0) || frameCountForDuration(duration))
      );
      const times = samplingTimes(duration, desiredCount, item.fps);
      const frames = [];
      for (let index = 0; index < times.length; index += 1) {
        await seekVideo(video, times[index]);
        frames.push(captureVideoFrame(video, times[index], index));
        options.onProgress?.({
          video: item,
          completed: index + 1,
          total: times.length,
          timestampSeconds: times[index]
        });
      }
      const sampled = {
        id: String(item.id || 'video1'),
        label: String(item.label || item.name || item.mediaName || item.id || '视频节点'),
        source_node_id: String(item.sourceNodeId || item.nodeId || item.source_node_id || ''),
        mime_type: String(item.mimeType || item.mime_type || 'video/mp4'),
        duration_seconds: Number(duration.toFixed(3)),
        width: Number(video.videoWidth || item.mediaWidth || item.width || 0),
        height: Number(video.videoHeight || item.mediaHeight || item.height || 0),
        fps: Math.max(1, Number(item.fps || 24)),
        frames
      };
      setCached(key, sampled);
      return sampled;
    } finally {
      video.pause();
      video.removeAttribute('src');
      video.load();
      video.remove();
    }
  }

  async function sampleVideoReferences(items = [], options = {}) {
    const videos = (Array.isArray(items) ? items : [])
      .filter(item => mediaKind(item) === 'video')
      .slice(0, MAX_VIDEO_REFERENCES);
    const output = [];
    for (let index = 0; index < videos.length; index += 1) {
      output.push(await sampleVideoReference(videos[index], {
        ...options,
        onProgress(progress) {
          options.onProgress?.({ ...progress, videoIndex: index + 1, videoTotal: videos.length });
        }
      }));
    }
    return output;
  }

  window.DesktopPromptMedia = Object.freeze({
    MIN_VIDEO_FRAMES,
    MAX_VIDEO_FRAMES,
    MAX_VIDEO_REFERENCES,
    frameCountForDuration,
    mediaKind,
    sampleVideoReference,
    sampleVideoReferences,
    videoSource
  });
})();
