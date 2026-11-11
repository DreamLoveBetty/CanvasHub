// Compose presentation: the compact canvas card and the workbench markup. Markup and paint only;
// players, the timeline, jobs and node state belong to desktop-canvas-video-compose.js.
(function () {
  const ICONS = Object.freeze({
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    expand: '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    output: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    stop: '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
    subtitles: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 12h4M13 12h4M7 15.5h7M16 15.5h1"/>',
  });
  const PLAY_ICONS = Object.freeze({play: '<path d="m9 5 11 7-11 7z"/>', pause: '<path d="M7 5h3v14H7zM14 5h3v14h-3z"/>'});
  const RUN_ICONS = Object.freeze({
    idle: '<path d="M4 6h7v12H4zM13 6h7v12h-7z"/><path d="m8 10.5 2 1.5-2 1.5zM15.5 10.5l2 1.5-2 1.5z"/>',
    busy: '<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>',
    succeeded: '<path fill="none" stroke="currentColor" stroke-width="2.5" d="m4 12 5 5L20 6"/>',
    failed: '<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M18 6 6 18"/>',
  });

  function create({model, subtitles, escapeHtml, stateIcon}) {
    const esc = value => escapeHtml(String(value ?? ''));
    const icon = body => `<svg class="desk-video-compose__icon-svg" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
    const frameHtml = attr => `<div class="desk-video-compose__frame" ${attr} data-fit="crop">
      <canvas class="desk-video-compose__blur" width="48" height="27" aria-hidden="true"></canvas><video playsinline preload="metadata"></video>
      <div class="desk-video-compose__caption" data-compose-caption hidden aria-hidden="true"></div></div>`;

    function html(node) {
      model.normalize(node);
      const id = esc(node.id);
      return `<section class="desk-node desk-node--video-compose" data-node-id="${id}" data-node-drag-handle aria-label="视频合成">
        <header class="desk-video-compose__head">
          <span class="desk-video-compose__icon">${model.ICON}</span>
          <strong class="desk-video-compose__title" data-compose-title>${esc(node.title)}</strong>
          <span class="desk-video-compose__badge" data-compose-badge>未合成</span>
          <button type="button" class="desk-node-delete" data-node-delete aria-label="删除视频合成节点" title="删除视频合成节点"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button>
        </header>
        <div class="desk-video-compose__preview" data-compose-preview title="双击展开工作台">
          ${frameHtml('data-compose-frame')}
          <span class="desk-video-compose__empty" data-compose-empty>连接视频节点作为片段</span>
          <button type="button" class="desk-video-compose__play" data-compose-play data-node-drag-ignore aria-label="播放预览" title="播放预览">${stateIcon.html(PLAY_ICONS, 'play')}</button>
          <span class="desk-video-compose__dims" data-compose-dims></span>
        </div>
        <div class="desk-video-compose__strip" data-compose-strip aria-hidden="true"></div>
        <div class="desk-video-compose__meta" data-compose-meta></div>
        <div class="desk-video-compose__actions" data-node-drag-ignore>
          <button type="button" class="desk-video-compose__open" data-compose-open title="展开合成工作台">${icon(ICONS.expand)}<span>展开工作台</span></button>
          <button type="button" class="desk-video-compose__run" data-compose-run aria-label="合成">${stateIcon.html(RUN_ICONS)}<span>合成</span></button>
        </div>
        <button class="desk-port desk-port--in" type="button" data-port="in" data-node-id="${id}" aria-label="片段与配乐输入"></button>
        <button class="desk-port desk-port--out" type="button" data-port="out" data-node-id="${id}" aria-label="成片输出"></button>
        <div hidden data-compose-progress role="status"></div>
      </section>`;
    }

    const seg = (key, options, attr = 'data-cb-seg', label = '') => `<div class="desk-video-compose-bench__seg" role="group" ${attr}="${key}"${label ? ` aria-label="${label}"` : ''}>${options
      .map(([value, text]) => `<button type="button" data-value="${esc(value)}" aria-pressed="false">${esc(text)}</button>`).join('')}</div>`;
    const range = (key, label) => `<span class="desk-video-compose-bench__label">${label}</span>
      <div class="desk-video-compose-bench__range"><input type="range" min="0" max="1.5" step="0.05" data-cb-range="${key}" aria-label="${label}"><output data-cb-output="${key}"></output></div>`;
    const row = (label, control) => `<span class="desk-video-compose-bench__label">${label}</span>${control}`;

    function benchHtml() {
      return `<div class="desk-video-compose-bench__scrim" data-cb-close></div>
        <section class="desk-video-compose-bench__dialog" role="dialog" aria-modal="true" aria-labelledby="deskVideoComposeTitle" tabindex="-1">
          <header class="desk-video-compose-bench__head">
            <div class="desk-video-compose-bench__title"><strong id="deskVideoComposeTitle">合成工作台</strong><span data-cb-name></span></div>
            <span class="desk-video-compose-bench__total" data-cb-total></span>
            <button type="button" class="desk-video-compose-bench__close" data-cb-close aria-label="收起合成工作台" title="收起（Esc）——合成会在后台继续">${icon(ICONS.close)}</button>
          </header>
          <div class="desk-video-compose-bench__body">
            <div class="desk-video-compose-bench__stage">
              <div class="desk-video-compose-bench__screen">
                ${frameHtml('data-cb-frame')}
                <span class="desk-video-compose-bench__label-chip" data-cb-label></span>
                <span class="desk-video-compose-bench__dims" data-cb-dims></span>
                <span class="desk-video-compose-bench__empty" data-cb-empty hidden></span>
              </div>
              <div class="desk-video-compose-bench__transport">
                <button type="button" class="desk-video-compose-bench__play" data-cb-play aria-label="播放" title="播放／暂停（空格）">${stateIcon.html(PLAY_ICONS, 'play')}</button>
                <div class="desk-video-compose-bench__clock"><b data-cb-time>00:00.000</b><span data-cb-length>/ 00:00.000</span></div>
                <div class="desk-video-compose-bench__seg is-view" role="group" aria-label="预览内容" data-cb-view>
                  <button type="button" data-value="draft" aria-pressed="true" title="按当前设定在浏览器里连播各段（近似预览）">草稿</button>
                  <button type="button" data-value="result" aria-pressed="false" title="播放合成好的成片">成片</button>
                </div>
              </div>
            </div>
            <aside class="desk-video-compose-bench__side">
              <section class="desk-video-compose-bench__panel">
                <header class="desk-video-compose-bench__panel-head">${icon(ICONS.music)}<h3>配乐</h3><small data-cb-music-name></small></header>
                <div class="desk-video-compose-bench__rows">
                  ${range('musicVolume', '配乐音量')}
                  ${range('clipVolume', '原声音量')}
                  ${row('淡入', seg('fadeIn', model.FADES.slice(0, 4)))}
                  ${row('淡出', seg('fadeOut', model.FADES.slice(0, 5)))}
                </div>
              </section>
              <section class="desk-video-compose-bench__panel">
                <header class="desk-video-compose-bench__panel-head">${icon(ICONS.output)}<h3>输出</h3><small data-cb-size></small></header>
                <div class="desk-video-compose-bench__rows">
                  ${row('比例', seg('aspect', model.ASPECTS))}
                  ${row('分辨率', seg('resolution', model.RESOLUTIONS))}
                  ${row('帧率', seg('fps', model.FRAME_RATES))}
                  ${row('填充', seg('fit', model.FITS))}
                  ${row('编码', seg('encoder', [['quality', '画质优先 · x264'], ['fast', '快速 · 硬件']]))}
                </div>
              </section>
              <section class="desk-video-compose-bench__panel" data-cb-subtitles>
                <header class="desk-video-compose-bench__panel-head">${icon(ICONS.subtitles)}<h3>字幕</h3><small data-cb-sub-count></small></header>
                <div class="desk-video-compose-bench__rows">
                  ${row('大小', seg('size', subtitles.SIZES, 'data-cb-sub-seg', '字幕大小'))}
                  ${row('位置', seg('position', subtitles.POSITIONS, 'data-cb-sub-seg', '字幕位置'))}
                  ${row('样式', seg('look', subtitles.LOOKS, 'data-cb-sub-seg', '字幕样式'))}
                  ${row('字体', '<select class="desk-video-compose-bench__select" data-cb-sub-font aria-label="字幕字体"></select>')}
                </div>
                <div class="desk-video-compose-bench__sub-actions">
                  <button type="button" data-cb-sub="add" title="在播放头位置添加一条 2 秒字幕">添加字幕</button>
                  <button type="button" data-cb-sub="import" title="导入 SRT 或 VTT 字幕文件">导入 SRT</button>
                  <button type="button" data-cb-sub="clear">清空</button>
                  <input type="file" accept=".srt,.vtt,text/plain" hidden data-cb-sub-file>
                </div>
                <div class="desk-video-compose-bench__sub-auto">
                  <button type="button" data-cb-sub="auto" title="识别片段原声，生成可编辑的字幕草稿（不含配乐）">自动字幕</button>
                  <select class="desk-video-compose-bench__select" data-cb-sub-script aria-label="自动字幕的文字">${(window.DesktopVideoComposeAutosub?.SCRIPTS || [])
                    .map(([value, text]) => `<option value="${esc(value)}">${esc(text)}</option>`).join('')}</select>
                  <p class="desk-video-compose-bench__sub-progress" data-cb-auto-status hidden><span></span><button type="button" data-cb-sub="auto-cancel">取消</button></p>
                </div>
              </section>
            </aside>
          </div>
          <section class="desk-video-compose-bench__timeline">
            <header class="desk-video-compose-bench__timeline-head"><h3>时间轴</h3>
              <small>拖动片段排序 · 拖两端把手按帧裁切 · 点片段或接缝设变速与转场 · 双击字幕轨添加字幕</small><small class="is-note" data-cb-music-note></small></header>
            <div class="desk-video-compose-bench__clipbar" data-cb-clip hidden>
              <strong data-cb-clip-name></strong>
              <span class="desk-video-compose-bench__label">变速</span>${seg('speed', model.SPEEDS, 'data-cb-clip-seg', '变速')}
              <span class="desk-video-compose-bench__label">转场到下一段</span>${seg('transition', model.TRANSITIONS, 'data-cb-clip-seg', '转场')}
              ${seg('transitionSeconds', model.TRANSITION_SECONDS, 'data-cb-clip-seg', '转场时长')}
              <small data-cb-clip-note></small>
            </div>
            <div class="desk-video-compose-bench__clipbar is-cue" data-cb-cue hidden>
              <strong data-cb-cue-name></strong>
              <textarea class="desk-video-compose-bench__cue-text" data-cb-cue-text rows="2" maxlength="${subtitles.MAX_CHARS}"
                placeholder="输入字幕文字（Enter 换行）" aria-label="字幕文字"></textarea>
              <span class="desk-video-compose-bench__cue-time" data-cb-cue-time></span>
              <button type="button" data-cb-cue="delete" title="删除这条字幕（Delete）">删除</button>
              <small data-cb-cue-note></small>
            </div>
            <div class="desk-video-compose-tl" data-cb-timeline></div>
          </section>
          <footer class="desk-video-compose-bench__foot">
            <p class="desk-video-compose-bench__status" data-cb-status role="status"></p>
            <div class="desk-video-compose-bench__progress" data-cb-progress hidden><span class="desk-video-compose-bench__bar"><i data-cb-progress-bar></i></span><b data-cb-progress-value></b></div>
            <button type="button" class="desk-video-compose-bench__cancel" data-cb-cancel hidden>${icon(ICONS.stop)}<span>停止</span></button>
            <button type="button" class="desk-video-compose-bench__run" data-cb-run>合成</button>
          </footer>
        </section>`;
    }

    // Card summary: clip count, total (red past the limit), output size, music.
    function metaHtml({clips, seconds, size, music}) {
      const over = seconds > model.MAX_SECONDS;
      return [`<span>${clips} 段</span>`,
        `<span class="${over ? 'is-over' : ''}" title="${over ? '超过 3 分钟上限' : ''}">${seconds.toFixed(2)} 秒</span>`,
        size ? `<span>${size.width}×${size.height}</span>` : '', `<span>${music ? '有配乐' : '无配乐'}</span>`]
        .filter(Boolean).join('<i aria-hidden="true"></i>');
    }

    return Object.freeze({html, benchHtml, metaHtml, PLAY_ICONS, RUN_ICONS});
  }

  window.DesktopVideoComposeView = Object.freeze({create});
})();
