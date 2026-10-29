// Pose reference node markup and paint. Same frame, header, field and footer rhythm as the
// Topaz Video node; the controller owns state, exports and the editor.
(function () {
  const icons = {
    idle: '<path d="M13 2 4 14h7l-1 8 10-13h-7z"/>',
    busy: '<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>',
    succeeded: '<path fill="none" stroke="currentColor" stroke-width="2.5" d="m4 12 5 5L20 6"/>',
    failed: '<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M18 6 6 18"/>',
  };
  function create({model, escapeHtml: e, stateIcon}) {
    const esc = value => e(String(value ?? ''));
    const options = (entries, selected) => entries.map(([value, label]) =>
      `<option value="${esc(value)}"${value === selected ? ' selected' : ''}>${esc(label)}</option>`).join('');
    function fields(node) {
      const cameras = node.scene.cameras.map(c => [c.id, `${c.name} · ${c.aspect}`]);
      return `<div class="desk-pose-node__grid">
        <label><span>输出通道</span><select data-pose-field="pass" aria-label="输出通道">${options(Object.entries(model.PASSES), node.output.pass)}</select></label>
        <label><span>机位</span><select data-pose-field="camera" aria-label="机位">${options(cameras, node.scene.activeCameraId)}</select></label>
        <label><span>输出尺寸（长边）</span><select data-pose-field="size" aria-label="输出尺寸">${options(Object.keys(model.SIZES).map(k => [k, k + ' px']), node.output.size)}</select></label>
      </div>`;
    }
    function html(node) {
      return `<section class="desk-node desk-node--pose" data-node-id="${esc(node.id)}" aria-label="姿态参考节点">
        <header class="desk-pose-node__header" data-node-drag-handle><span class="desk-pose-node__icon">${model.ICON}</span><div><strong>${esc(node.title)}</strong><small>姿态参考 · SOMA</small></div><span class="desk-status-pill" data-pose-status>就绪</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除姿态参考节点" title="删除姿态参考节点"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button></header>
        <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接参考图片"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接姿态参考输出"></button>
        <div class="desk-pose-node__body" data-node-drag-ignore>
          <div class="desk-pose-node__preview" data-pose-preview>
            <img data-pose-preview-image alt="姿态参考导出图" hidden>
            <div class="desk-pose-node__preview-empty" data-pose-preview-empty><strong>尚未导出</strong><span>打开编辑器摆好姿势和机位，再导出到节点</span></div>
            <div class="desk-pose-node__preview-meta"><span data-pose-preview-pass></span><span data-pose-preview-size></span></div>
            <button type="button" class="desk-pose-node__preview-open" data-pose-open aria-label="打开姿态编辑器"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 3h6v6M21 3l-7 7M9 21H3v-6M3 21l7-7"/></svg></button>
          </div>
          <div class="desk-pose-node__fields">${fields(node)}</div>
          <div class="desk-pose-node__source-row"><div class="desk-pose-node__source-copy"><span data-pose-scene-summary></span><small data-pose-source-hint></small></div><button type="button" class="desk-key desk-pose-node__evidence" data-pose-evidence aria-pressed="true" hidden title="用 SAM 3D Body 读画面，修正手臂前后位置与手指形状（每段视频约多 1 分钟）">精修手部</button><button type="button" class="desk-key" data-pose-recognize disabled>识别动作</button></div>
          <footer class="desk-pose-node__footer"><button type="button" class="desk-key desk-pose-node__editor" data-pose-open>${model.ICON}<span>打开编辑器</span></button><span class="desk-pose-node__note" data-pose-note></span><button type="button" class="desk-generation-action desk-pose-node__export" data-pose-export aria-label="导出姿态参考">${stateIcon.html(icons)}<span class="desk-generation-action__label">导出</span></button></footer>
        </div>
        <div class="desk-progress-float desk-pose-node__progress" data-pose-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar data-pose-bar></span><strong class="desk-progress-float__percent" data-pose-percent>渲染中</strong></div><span class="desk-progress-float__stage" data-pose-stage>渲染中</span></div></div>
      </section>`;
    }
    function renderFields(el, node) {
      const container = el.querySelector('.desk-pose-node__fields');
      if (container) container.innerHTML = fields(node);
    }
    // display: {busy (export), recognizing, assets / recognition: status payloads|null,
    //           references / videos: connected image / video counts, stage, error, flash}
    function paint(el, node, display = {}) {
      const exported = model.artifactUrl(node);
      const dirty = model.dirty(node);
      const camera = model.activeCamera(node.scene);
      const [width, height] = model.outputSize(node.output.size, camera.aspect);
      const image = el.querySelector('[data-pose-preview-image]');
      if (exported && image.getAttribute('src') !== exported) image.setAttribute('src', exported);
      image.hidden = !exported;
      el.querySelector('[data-pose-preview-empty]').hidden = Boolean(exported);
      el.querySelector('[data-pose-preview-pass]').textContent = exported ? model.PASSES[node.output.pass] || '' : '';
      el.querySelector('[data-pose-preview-size]').textContent = exported ? `${node.output.width}×${node.output.height}` : '';
      el.querySelector('[data-pose-preview-pass]').hidden = !exported;
      el.querySelector('[data-pose-preview-size]').hidden = !exported;
      const visible = node.scene.characters.filter(c => c.visible).length;
      const recognized = node.scene.cameras.some(c => c.id === model.PHOTO_CAMERA);
      const sequence = node.scene.sequence;
      el.querySelector('[data-pose-scene-summary]').textContent = sequence
        ? `视频识别 · ${visible} 个角色 · ${sequence.frameCount} 帧 ${Math.round(sequence.fps)} fps`
        : `${recognized ? '照片识别' : '静态姿势'} · ${visible} 个角色 · ${camera.name} ${camera.focalMm} mm`;
      const engineReady = display.recognition?.ready === true;
      const videoReady = display.recognition?.modes?.video === true;
      const sources = (display.videos || 0) + (display.references || 0);
      const evidence = Boolean(display.videos) && engineReady && videoReady && display.recognition?.modes?.evidence === true;
      const evidenceKey = el.querySelector('[data-pose-evidence]');
      evidenceKey.hidden = !evidence;
      evidenceKey.setAttribute('aria-pressed', String(node.capture.evidence));
      evidenceKey.disabled = Boolean(display.recognizing);
      const usable = display.videos ? videoReady : Boolean(display.references);
      el.querySelector('[data-pose-source-hint]').textContent = display.recognizing ? `识别中：${display.stage || '准备识别'}`
        : !sources ? '连接图片或视频节点后可识别其中人物的动作'
          : !display.recognition ? '正在检查识别引擎…'
            : !engineReady ? `${display.recognition.message || '姿态识别引擎尚未安装'}：${display.recognition.install_command || ''}`
              : display.videos && !videoReady ? `${display.recognition.video_message || '视频识别尚未就绪'}：${display.recognition.install_command || ''}`
                : display.videos ? `已连接视频，识别前 ${display.recognition.max_seconds || 30} 秒（最多 ${display.recognition.max_video_people || 4} 人）${evidence && node.capture.evidence ? ' · 精修手部约多 1 分钟' : ''}`
                  : `已连接 ${display.references} 张图片，可识别动作，或在编辑器机位视角中对照`;
      const recognize = el.querySelector('[data-pose-recognize]');
      recognize.textContent = display.recognizing ? '停止识别' : '识别动作';
      recognize.disabled = !display.recognizing && (Boolean(display.busy) || !usable || !engineReady);
      recognize.title = display.recognizing ? '停止当前识别' : !sources ? '先连接图片或视频节点' : !engineReady || !usable ? '识别引擎尚未就绪'
        : display.videos ? '用 GEM-X 识别视频中的人物动作' : '用 GEM-X 识别图片中的人物姿势';
      const assetsReady = display.assets?.ready === true;
      const badge = el.querySelector('[data-pose-status]');
      const failed = node.status === 'failed' || Boolean(display.error);
      badge.textContent = display.recognizing ? '识别中' : display.busy ? '导出中' : failed ? '失败' : !display.assets ? '检测中' : !assetsReady ? '未安装' : exported && !dirty ? '已导出' : exported ? '待导出' : '就绪';
      badge.classList.toggle('is-success', !display.busy && !display.recognizing && !failed && assetsReady && (!exported || !dirty));
      const note = el.querySelector('[data-pose-note]');
      const videoExport = model.exportsVideo(node), video = node.output.video;
      note.textContent = display.error || node.error
        || (!display.assets ? '正在检查人偶资源…' : !assetsReady ? display.assets.message || '姿态人偶尚未安装'
          : exported && dirty ? '有未导出的修改' : videoExport && video ? `已导出视频 ${video.width}×${video.height} · ${video.frames} 帧`
            : exported ? `已导出 ${width}×${height} PNG` : videoExport ? `将导出 ${node.scene.sequence.outFrame - node.scene.sequence.inFrame + 1} 帧视频` : '本地渲染 · 无需模型');
      note.classList.toggle('is-dirty', Boolean(exported && dirty && !display.error));
      note.classList.toggle('is-unavailable', failed || (display.assets && !assetsReady));
      const button = el.querySelector('[data-pose-export]');
      // During a video export the button stops it; otherwise it starts an export.
      button.disabled = (Boolean(display.busy) && !videoExport) || Boolean(display.recognizing) || !assetsReady;
      button.querySelector('.desk-generation-action__label').textContent = display.busy && videoExport ? '停止' : videoExport ? '导出视频' : '导出';
      button.setAttribute('aria-label', display.busy && videoExport ? '停止导出姿态视频' : videoExport ? '导出姿态视频' : '导出姿态参考');
      button.dataset.poseExportState = display.busy ? 'busy' : failed ? 'failed' : 'idle';
      stateIcon.paint(button.querySelector('.desk-state-icon'), display.busy ? 'busy' : display.flash || (failed ? 'failed' : 'idle'));
      el.querySelectorAll('[data-pose-open]').forEach(open => { open.disabled = !assetsReady || Boolean(display.recognizing); });
      const working = Boolean(display.busy || display.recognizing);
      const progress = el.querySelector('[data-pose-progress]');
      progress.hidden = !working;
      if (working) {
        const stage = display.stage || (display.recognizing ? '识别中' : '渲染中');
        el.querySelector('[data-pose-stage]').textContent = stage;
        el.querySelector('[data-pose-percent]').textContent = stage;
      }
    }
    return Object.freeze({html, renderFields, paint});
  }
  window.DesktopPoseView = Object.freeze({create});
})();
