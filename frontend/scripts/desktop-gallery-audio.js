// The gallery's audio page: generated songs archived under <archive>/audio/, one player card
// each (generated cover art, title from the lyrics, real waveform, seek and ±10 s, download,
// send to a canvas audio node), details with style, lyrics, parameters and delete-with-undo,
// search, and the explicit backfill of songs made before archiving existed.
// Like the LoRA view it mounts into the gallery grid; desktop-history.js only switches views
// and passes every dependency in. Backend snake_case is translated in normalize().
(function () {
  const SEARCH_DELAY_MS = 180;
  const SKIP_SECONDS = 10;
  const PLACEHOLDER_PEAKS = Array.from({ length: 64 }, () => 0.12);

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    if (!total) return '';
    const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
    const pad = value => String(value).padStart(2, '0');
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  function validPeaks(value) {
    return Array.isArray(value) && value.length >= 8 && value.every(v => Number.isFinite(Number(v)));
  }

  // A song has no name: its first sung line reads like one; the style says what it sounds like.
  function songTitle(lyrics, style, name) {
    const line = String(lyrics || '').split('\n')
      .map(text => text.replace(/^\s*\[[^\]]*\]\s*/, '').trim())
      .find(Boolean);
    return line || String(style || '').split(/[,，。\n]/)[0].trim() || name;
  }

  function songSubtitle(style) {
    return String(style || '').split(/[,，]/).map(part => part.trim()).filter(Boolean).slice(0, 3).join(' · ');
  }

  function normalize(item) {
    const number = value => (Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0);
    const name = String(item?.name || '音频');
    const style = String(item?.style || '');
    const lyrics = String(item?.lyrics || '');
    return {
      id: String(item?.id || ''),
      path: String(item?.path || ''),
      name,
      title: songTitle(lyrics, style, name.replace(/\.[^.]+$/, '')),
      subtitle: songSubtitle(style),
      url: String(item?.url || ''),
      mimeType: String(item?.mime_type || ''),
      format: String(item?.format || ''),
      fileSize: number(item?.file_size),
      createdAt: number(item?.created_at),
      durationSeconds: number(item?.duration_seconds),
      sampleRate: number(item?.sample_rate),
      channels: number(item?.channels),
      jobId: String(item?.job_id || ''),
      style,
      lyrics,
      seed: Number.isFinite(Number(item?.seed)) && item?.seed !== null ? Number(item.seed) : null,
      precision: String(item?.precision || ''),
      hasScore: item?.has_score === true,
      peaks: validPeaks(item?.peaks) ? item.peaks.map(v => Math.min(1, Math.max(0, Number(v)))) : null
    };
  }

  function hash(text) {
    let value = 2166136261;
    for (const char of String(text)) value = Math.imul(value ^ char.codePointAt(0), 16777619);
    // Finalising mix: paths differ in a few characters, and plain FNV leaves the hue clustered.
    value = Math.imul(value ^ (value >>> 16), 0x85ebca6b);
    value = Math.imul(value ^ (value >>> 13), 0xc2b2ae35);
    return (value ^ (value >>> 16)) >>> 0;
  }

  // Cover art for a song that has none: a sun over dunes, its palette fixed by the file path.
  function coverArt(key) {
    const h = hash(key);
    const hue = h % 360, warm = (hue + 18 + ((h >>> 9) % 34)) % 360;
    const sunX = 40 + ((h >>> 3) % 22), sunY = 34 + ((h >>> 7) % 14), sunR = 20 + ((h >>> 11) % 8);
    const lift = n => 8 + ((h >>> (13 + n)) % 9);
    const id = `desk-audio-cover-${h.toString(36)}`;
    const dune = (y, n, fill) => `<path d="M0 ${y} Q 26 ${y - lift(n)} 52 ${y - 2} T 100 ${y - lift(n + 2) / 2} V100 H0 Z" fill="${fill}"/>`;
    return `<svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <linearGradient id="${id}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl(${warm} 70% 90%)"/><stop offset="1" stop-color="hsl(${hue} 62% 74%)"/></linearGradient>
        <radialGradient id="${id}-sun" cx=".42" cy=".38" r=".7"><stop offset="0" stop-color="hsl(${warm} 95% 76%)"/><stop offset="1" stop-color="hsl(${hue} 88% 58%)"/></radialGradient>
      </defs>
      <rect width="100" height="100" fill="url(#${id}-sky)"/>
      <circle cx="${sunX}" cy="${sunY}" r="${sunR}" fill="url(#${id}-sun)"/>
      ${dune(66, 0, `hsl(${hue} 58% 62% / .92)`)}${dune(76, 1, `hsl(${(hue + 350) % 360} 46% 48% / .94)`)}${dune(88, 2, `hsl(${(hue + 340) % 360} 36% 34%)`)}
    </svg>`;
  }

  function waveBars(peaks) {
    const width = 3;
    return peaks.map((peak, index) => {
      const height = Math.max(2, peak * 34);
      return `<rect x="${index * width}" y="${(36 - height) / 2}" width="1.8" height="${height}" rx=".9"/>`;
    }).join('');
  }

  const ICONS = Object.freeze({
    play: '<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z"/>',
    pause: '<rect x="6.5" y="5" width="4" height="14" rx="1.2"/><rect x="13.5" y="5" width="4" height="14" rx="1.2"/>',
    back: '<path d="M11.5 7 5 12l6.5 5z"/><path d="M19.5 7 13 12l6.5 5z"/>',
    forward: '<path d="M12.5 7 19 12l-6.5 5z"/><path d="M4.5 7 11 12l-6.5 5z"/>',
    download: '<path d="M12 4.5v10"/><path d="m7.5 10 4.5 4.5 4.5-4.5"/><path d="M4.5 15.5v2a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2"/>',
    canvas: '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M12 9v6M9 12h6"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.6v.2"/>'
  });
  const icon = (name, fill = false) => `<svg viewBox="0 0 24 24" aria-hidden="true"${fill ? ' class="is-filled"' : ''}>${ICONS[name]}</svg>`;

  function create({ api, sendToCanvas, closeGallery, notify, showError, copyText, escapeHtml, formatFileSize, formatTime }) {
    let root = null, controller = null, player = null;
    let items = [], stats = {}, query = '', loading = false, error = '', request = 0;
    let playingPath = '', expandedPath = '', undoIds = [], unarchived = 0, searchTimer = 0;
    let pendingSeek = null, peakQueue = Promise.resolve();
    const requestedPeaks = new Set();
    const find = path => items.find(item => item.path === path);
    const esc = value => escapeHtml(String(value ?? ''));
    const sounding = item => item.path === playingPath && Boolean(player) && !player.paused;
    const cardOf = path => root?.querySelector(`[data-audio-path="${CSS.escape(path)}"]`);

    function eyebrow(item) {
      if (item.path === playingPath) {
        return `<span class="desk-gallery-audio__eyebrow is-live"><i aria-hidden="true"><b></b><b></b><b></b><b></b></i>${sounding(item) ? '正在播放' : '已暂停'}</span>`;
      }
      return `<span class="desk-gallery-audio__eyebrow">${esc([item.format, formatTime(item.createdAt)].filter(Boolean).join(' · '))}</span>`;
    }

    function detail(item) {
      const parameters = [
        ['种子', item.seed ?? ''], ['精度', item.precision], ['采样率', item.sampleRate ? `${item.sampleRate} Hz` : ''],
        ['声道', item.channels ? String(item.channels) : ''], ['大小', formatFileSize(item.fileSize)],
        ['乐谱', item.hasScore ? '已附 .abc 侧车' : ''], ['文件', item.path]
      ].filter(([, value]) => value !== '' && value !== null);
      return `<div class="desk-gallery-audio__detail" id="desk-gallery-audio-detail-${esc(item.id)}">
        <section><header><strong>风格</strong></header><p>${item.style ? esc(item.style) : '<span class="is-empty">没有风格记录</span>'}</p></section>
        <section><header><strong>歌词</strong>${item.lyrics ? `<button type="button" class="desk-button" data-audio-asset-action="copy-lyrics" data-path="${esc(item.path)}">复制</button>` : ''}</header>
          ${item.lyrics ? `<pre>${esc(item.lyrics)}</pre>` : '<p><span class="is-empty">没有歌词记录</span></p>'}</section>
        <section><header><strong>参数</strong></header><dl>${parameters.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd title="${esc(value)}">${esc(value)}</dd></div>`).join('')}</dl></section>
        <footer><button type="button" class="desk-button desk-button--danger" data-audio-asset-action="delete" data-path="${esc(item.path)}">删除</button></footer>
      </div>`;
    }

    function card(item) {
      const current = item.path === playingPath;
      const expanded = item.path === expandedPath;
      const path = esc(item.path);
      const peaks = item.peaks || PLACEHOLDER_PEAKS;
      const bars = waveBars(peaks);
      const control = (action, name, label) =>
        `<button type="button" class="desk-gallery-audio__control" data-audio-asset-action="${action}" data-path="${path}" aria-label="${esc(label)}" title="${esc(label)}">${icon(name)}</button>`;
      return `<article class="desk-gallery-audio__card${current ? ' is-current' : ''}${expanded ? ' is-expanded' : ''}" data-audio-path="${path}">
        <div class="desk-gallery-audio__cover">${coverArt(item.path)}</div>
        <div class="desk-gallery-audio__main">
          <div class="desk-gallery-audio__head">
            ${eyebrow(item)}
            <button type="button" class="desk-gallery-audio__control desk-gallery-audio__info" data-audio-asset-action="toggle" data-path="${path}" aria-expanded="${expanded}" aria-controls="desk-gallery-audio-detail-${esc(item.id)}" aria-label="${esc(`${item.title} 的详情`)}" title="详情">${icon('info')}</button>
          </div>
          <strong class="desk-gallery-audio__title" title="${esc(item.title)}">${esc(item.title)}</strong>
          <span class="desk-gallery-audio__subtitle" title="${esc(item.style)}">${esc(item.subtitle || item.name)}</span>
          <div class="desk-gallery-audio__wave${item.peaks ? '' : ' is-pending'}" data-audio-asset-wave style="--progress: 0%">
            <svg viewBox="0 0 ${peaks.length * 3} 36" preserveAspectRatio="none" aria-hidden="true">${bars}</svg>
            <svg class="desk-gallery-audio__wave-played" viewBox="0 0 ${peaks.length * 3} 36" preserveAspectRatio="none" aria-hidden="true">${bars}</svg>
            <input type="range" min="0" max="1000" step="1" value="0" data-audio-asset-seek data-path="${path}" aria-label="${esc(`${item.title} 播放进度`)}">
          </div>
          <div class="desk-gallery-audio__times"><span data-audio-asset-time>0:00</span><span>${esc(formatDuration(item.durationSeconds) || '--:--')}</span></div>
        </div>
        <div class="desk-gallery-audio__controls">
          ${control('download', 'download', `下载 ${item.name}`)}
          ${control('back', 'back', `后退 ${SKIP_SECONDS} 秒`)}
          <button type="button" class="desk-gallery-audio__play" data-audio-asset-action="play" data-path="${path}" aria-label="${esc(`${sounding(item) ? '暂停' : '播放'} ${item.title}`)}" aria-pressed="${sounding(item)}">${icon(sounding(item) ? 'pause' : 'play', true)}</button>
          ${control('forward', 'forward', `前进 ${SKIP_SECONDS} 秒`)}
          ${control('canvas', 'canvas', '发送到画布')}
        </div>
        ${expanded ? detail(item) : ''}
      </article>`;
    }

    function statusText() {
      if (loading && !items.length) return '正在读取音频资产…';
      if (error && !items.length) return error;
      const parts = [`共 ${Number(stats.total ?? items.length).toLocaleString('zh-CN')} 首`];
      if (query) parts.push(`匹配 ${items.length.toLocaleString('zh-CN')}`);
      if (stats.total_duration_seconds) parts.push(`总时长 ${formatDuration(stats.total_duration_seconds)}`);
      if (stats.total_file_size) parts.push(`总计 ${formatFileSize(stats.total_file_size)}`);
      return parts.join(' · ');
    }

    function emptyText() {
      if (loading) return '正在读取音频资产…';
      if (error) return error;
      return query ? '没有匹配的音频' : '还没有归档的音频。生成完成的歌曲会自动保存到存储路径下的 audio 目录。';
    }

    // Repainting replaces the cards, so the control that triggered it gets its focus back.
    function paint(focus = null) {
      if (!root?.isConnected) return;
      const list = root.querySelector('[data-audio-asset-list]');
      list.innerHTML = items.length ? items.map(card).join('') : `<div class="desk-gallery-empty">${esc(emptyText())}</div>`;
      root.querySelector('[data-audio-asset-status]').textContent = statusText();
      root.querySelector('[data-audio-asset-undo]').hidden = !undoIds.length;
      const banner = root.querySelector('[data-audio-asset-backfill]');
      banner.hidden = !unarchived;
      banner.querySelector('span').textContent = `有 ${unarchived} 首较早生成的歌曲还没有归档到存储路径。原始文件会保留，归档只是复制一份。`;
      paintProgress();
      if (focus) list.querySelector(`[data-audio-asset-action="${focus.action}"][data-path="${CSS.escape(focus.path)}"]`)?.focus({ preventScroll: true });
      loadPeaks();
    }

    // Play/pause only touches the current card's button and label, so focus and scroll stay put.
    function paintPlayState() {
      const item = find(playingPath);
      const element = item && cardOf(item.path);
      if (!element) return;
      const button = element.querySelector('[data-audio-asset-action="play"]');
      button.setAttribute('aria-pressed', String(sounding(item)));
      button.setAttribute('aria-label', `${sounding(item) ? '暂停' : '播放'} ${item.title}`);
      button.innerHTML = icon(sounding(item) ? 'pause' : 'play', true);
      const template = document.createElement('template');
      template.innerHTML = eyebrow(item);
      element.querySelector('.desk-gallery-audio__eyebrow')?.replaceWith(template.content.firstElementChild);
    }

    function paintProgress() {
      const element = playingPath && cardOf(playingPath);
      if (!element || !player) return;
      const duration = Number.isFinite(player.duration) ? player.duration : (find(playingPath)?.durationSeconds || 0);
      const fraction = duration ? Math.min(1, player.currentTime / duration) : 0;
      element.querySelector('[data-audio-asset-wave]').style.setProperty('--progress', `${(fraction * 100).toFixed(2)}%`);
      element.querySelector('[data-audio-asset-seek]').value = String(Math.round(fraction * 1000));
      element.querySelector('[data-audio-asset-time]').textContent = formatDuration(player.currentTime) || '0:00';
    }

    // Waveforms the archive has not measured yet are fetched one at a time and painted in place.
    function loadPeaks() {
      items.filter(item => !item.peaks && !requestedPeaks.has(item.path)).forEach(item => {
        requestedPeaks.add(item.path);
        peakQueue = peakQueue.then(async () => {
          if (!root?.isConnected) return;
          const result = await api.getAudioPeaks(item.path).catch(() => null);
          if (!validPeaks(result?.peaks) || !root?.isConnected) return;
          item.peaks = result.peaks.map(v => Math.min(1, Math.max(0, Number(v))));
          const wave = cardOf(item.path)?.querySelector('[data-audio-asset-wave]');
          if (!wave) return;
          const bars = waveBars(item.peaks);
          wave.querySelectorAll('svg').forEach(svg => {
            svg.setAttribute('viewBox', `0 0 ${item.peaks.length * 3} 36`);
            svg.innerHTML = bars;
          });
          wave.classList.remove('is-pending');
        });
      });
    }

    function stop() {
      if (!player) return;
      player.pause();
      player.removeAttribute('src');
      player.load();
      playingPath = '';
      pendingSeek = null;
    }

    async function togglePlay(item, seekFraction = null) {
      if (item.path === playingPath) {
        if (player.paused) await player.play();
        else player.pause();
        return;
      }
      stop();
      playingPath = item.path;
      pendingSeek = seekFraction;
      player.src = item.url;
      paint({ action: 'play', path: item.path });
      await player.play();
    }

    // On a card that is not playing, skipping starts it: from the top, or 10 s in.
    function skip(item, seconds) {
      if (item.path !== playingPath) {
        const ahead = seconds > 0 && item.durationSeconds > seconds ? seconds / item.durationSeconds : null;
        return togglePlay(item, ahead);
      }
      if (!Number.isFinite(player.duration)) return;
      player.currentTime = Math.min(player.duration, Math.max(0, player.currentTime + seconds));
    }

    async function toCanvas(item, button) {
      button.disabled = true;
      button.classList.add('is-busy');
      try {
        const blob = await api.getAudioAssetBlob(item.url);
        await sendToCanvas({
          blob, url: item.url, name: item.name, mime_type: item.mimeType || blob.type,
          file_size: item.fileSize || blob.size, duration_seconds: item.durationSeconds, task_id: item.jobId
        });
        stop();
        closeGallery();
        notify('音频已发送到画布。');
      } finally {
        if (button.isConnected) { button.disabled = false; button.classList.remove('is-busy'); }
      }
    }

    function download(item) {
      const anchor = document.createElement('a');
      anchor.href = item.url;
      anchor.download = item.name;
      anchor.rel = 'noopener';
      anchor.click();
    }

    async function remove(item) {
      if (!window.confirm(`将「${item.name}」和它的提示词、歌词、乐谱侧车移入废纸篓？可撤销。`)) return;
      const result = await api.deleteAudioAssets([item.path]);
      if (!result?.ok) throw new Error(result?.error || '删除失败');
      undoIds = [result.delete_batch_id || result.undo_id].filter(Boolean);
      if (playingPath === item.path) stop();
      if (expandedPath === item.path) expandedPath = '';
      notify(result.message || '音频已移入废纸篓。');
      await refresh();
    }

    async function undo(button) {
      if (!undoIds.length) return;
      button.disabled = true;
      try {
        const result = await api.undoAssetDelete(undoIds);
        if (!result?.ok) throw new Error(result?.error || result?.errors?.join('；') || '撤销失败');
        undoIds = [];
        notify(`已撤销删除，恢复 ${result.restored_files || 0} 个文件。`);
        await refresh();
      } finally {
        button.disabled = false;
      }
    }

    async function backfill(button) {
      button.disabled = true;
      try {
        const result = await api.archiveExistingAudio();
        notify(result.failed ? `已归档 ${result.archived} 首，${result.failed} 首失败（原始文件仍在任务目录）。` : `已归档 ${result.archived} 首歌曲。`);
        await refresh();
      } finally {
        button.disabled = false;
      }
    }

    async function refresh() {
      if (!root?.isConnected) return;
      const current = ++request;
      loading = true;
      error = '';
      paint();
      const [list, pending] = await Promise.allSettled([api.listAudioAssets({ query, limit: 500 }), api.getUnarchivedAudio()]);
      if (current !== request || !root?.isConnected) return;
      loading = false;
      if (list.status === 'fulfilled') {
        const known = new Map(items.map(item => [item.path, item.peaks]));
        items = (Array.isArray(list.value?.items) ? list.value.items : []).map(normalize).filter(item => item.path && item.url);
        items.forEach(item => { item.peaks ||= known.get(item.path) || null; });
        stats = list.value?.stats || {};
      } else {
        error = String(list.reason?.message || list.reason || '音频资产加载失败');
      }
      unarchived = pending.status === 'fulfilled' ? Math.max(0, Number(pending.value?.count) || 0) : 0;
      if (playingPath && !find(playingPath)) stop();
      if (expandedPath && !find(expandedPath)) expandedPath = '';
      paint();
    }

    const actions = {
      play: item => togglePlay(item),
      back: item => skip(item, -SKIP_SECONDS),
      forward: item => skip(item, SKIP_SECONDS),
      toggle: item => { expandedPath = expandedPath === item.path ? '' : item.path; paint({ action: 'toggle', path: item.path }); },
      canvas: (item, button) => toCanvas(item, button),
      download: item => download(item),
      delete: item => remove(item),
      'copy-lyrics': item => copyText(item.lyrics).then(() => notify('歌词已复制。'))
    };

    function seek(input) {
      const item = find(input.dataset.path || '');
      if (!item) return;
      const fraction = Number(input.value) / 1000;
      // Seeking a card that is not playing starts it at that point.
      if (item.path !== playingPath) { togglePlay(item, fraction).catch(showError); return; }
      if (Number.isFinite(player.duration)) player.currentTime = player.duration * fraction;
      else pendingSeek = fraction;
    }

    function bind() {
      const signal = controller.signal;
      root.addEventListener('click', event => {
        const target = event.target.closest('[data-audio-asset-action]');
        if (target && !target.disabled) {
          const item = find(target.dataset.path || '');
          const action = actions[target.dataset.audioAssetAction];
          if (item && action) Promise.resolve(action(item, target)).catch(showError);
          return;
        }
        if (event.target.closest('[data-audio-asset-undo]')) undo(event.target.closest('button')).catch(showError);
        else if (event.target.closest('[data-audio-asset-backfill] button')) backfill(event.target.closest('button')).catch(showError);
        else if (event.target.closest('[data-audio-asset-refresh]')) refresh();
      }, { signal });
      root.addEventListener('input', event => {
        if (event.target.matches('[data-audio-asset-query]')) {
          clearTimeout(searchTimer);
          searchTimer = setTimeout(() => { query = event.target.value.trim(); refresh(); }, SEARCH_DELAY_MS);
        } else if (event.target.matches('[data-audio-asset-seek]')) {
          seek(event.target);
        }
      }, { signal });
      ['play', 'pause', 'ended'].forEach(name => player.addEventListener(name, paintPlayState, { signal }));
      ['timeupdate', 'durationchange', 'seeked'].forEach(name => player.addEventListener(name, paintProgress, { signal }));
      player.addEventListener('loadedmetadata', () => {
        if (pendingSeek !== null && Number.isFinite(player.duration)) player.currentTime = player.duration * pendingSeek;
        pendingSeek = null;
      }, { signal });
      player.addEventListener('error', () => {
        if (player.getAttribute('src')) showError(new Error('无法播放这首音频，请检查文件是否仍在存储路径中'));
      }, { signal });
    }

    function mount(container) {
      unmount();
      root = container;
      root.classList.add('desk-gallery-audio');
      root.innerHTML = `<div class="desk-gallery-audio__toolbar">
          <label class="desk-gallery-search desk-gallery-audio__search">
            <span aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"></circle><path d="m16 16 4 4"></path></svg></span>
            <input type="search" data-audio-asset-query placeholder="搜索歌词 / 风格 / 文件名" value="${esc(query)}" aria-label="搜索音频">
          </label>
          <button type="button" class="desk-button" data-audio-asset-refresh>刷新</button>
          <span class="desk-gallery-audio__status" data-audio-asset-status role="status" aria-live="polite"></span>
          <button type="button" class="desk-button" data-audio-asset-undo hidden>撤销删除</button>
        </div>
        <div class="desk-gallery-audio__backfill" data-audio-asset-backfill hidden><span></span><button type="button" class="desk-button">归档到存储路径</button></div>
        <div class="desk-gallery-audio__list" data-audio-asset-list></div>`;
      player = new Audio();
      player.preload = 'metadata';
      controller = new AbortController();
      bind();
      paint();
      return refresh();
    }

    function unmount() {
      request += 1;
      clearTimeout(searchTimer);
      controller?.abort();
      controller = null;
      stop();
      player = null;
      // The host redraws the grid for the next view; clearing it here would blank a closing panel.
      root?.classList.remove('desk-gallery-audio');
      root = null;
    }

    return Object.freeze({ mount, unmount, refresh: () => refresh(), mounted: () => Boolean(root?.isConnected) });
  }

  window.DesktopGalleryAudio = Object.freeze({ create, normalize, formatDuration, songTitle, coverArt });
})();
