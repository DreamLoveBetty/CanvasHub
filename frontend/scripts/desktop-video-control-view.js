// Presentation only; shared visual tokens, no audio-domain CSS or controllers.
(function () {
  const icons = { idle:'<path d="M13 2 4 14h7l-1 8 10-13h-7z"/>', busy:'<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>', succeeded:'<path fill="none" stroke="currentColor" stroke-width="2.5" d="m4 12 5 5L20 6"/>', failed:'<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M18 6 6 18"/>' };
  function create({ model, escapeHtml:e, stateIcon, progressView }) {
    const field = (key, label, value, choices) => `<label>${label}${choices ? `<select data-control-field="${key}">${choices.map(([v,t]) => `<option value="${v}" ${String(v) === String(value) ? 'selected' : ''}>${t}</option>`).join('')}</select>` : `<input type="number" data-control-field="${key}" value="${value}">`}</label>`;
    function html(node) {
      return `<section class="desk-node desk-node--video-control" data-node-id="${e(node.id)}" data-node-drag-handle aria-label="ReShot 视频控制">
      <header class="desk-video-control__header"><span class="desk-video-control__icon">${model.ICON}</span><div><strong>ReShot 视频控制</strong><small>VIDEO CONTROL</small></div><span class="desk-status-pill" data-control-status>就绪</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除视频控制节点">删</button></header>
      <div class="desk-video-control__body" data-node-drag-ignore>
        <div class="desk-video-control__grid">
          ${field('control','处理模式',node.control,[['depth','深度 · Depth'],['pose','姿态 · Pose'],['canny','边缘 · Canny']])}
          ${field('quality','处理质量',node.quality,[['fast','快速'],['full','精细']])}
          ${field('maxRes','最长边',node.maxRes,[[640,'640 px'],[960,'960 px'],[1280,'1280 px']])}
          ${field('maxSeconds','截取前段（秒）',node.maxSeconds)}
        </div>
        <div class="desk-video-control__options" data-control-options="depth"><label><input type="checkbox" data-control-field="invert" ${node.invert?'checked':''}>反转深度</label><span>Video Depth Anything · Small</span></div>
        <div class="desk-video-control__options" data-control-options="pose"><label><input type="checkbox" data-control-field="poseHands" ${node.poseHands?'checked':''}>手部</label><label><input type="checkbox" data-control-field="poseFace" ${node.poseFace?'checked':''}>面部</label><span>DWPose · 姿态平滑</span></div>
        <div class="desk-video-control__options" data-control-options="canny">${field('cannyLow','低阈值',node.cannyLow)}${field('cannyHigh','高阈值',node.cannyHigh)}</div>
        <div class="desk-video-control__input"><span data-control-source>连接视频节点，或导入本地视频</span><button type="button" data-control-import>导入视频</button><input type="file" data-control-file accept="video/mp4,video/quicktime,video/webm,.mkv" hidden></div>
        <div class="desk-video-control__footer"><small>本地处理 · 输出控制视频 · 24 fps</small><button type="button" class="desk-video-control__generate desk-generation-action" data-control-run aria-label="开始处理">${stateIcon.html(icons)}<span class="desk-generation-action__label">开始处理</span></button></div>
      </div>
      <button class="desk-port desk-port--in" type="button" data-port="in" data-node-id="${e(node.id)}" aria-label="视频输入"></button><button class="desk-port desk-port--out" type="button" data-port="out" data-node-id="${e(node.id)}" aria-label="控制视频输出"></button>
      <div class="desk-video-control__progress" hidden data-control-progress role="status"><span data-control-stage></span><div><i></i></div></div></section>`;
    }
    function paint(el, node, job, pending=false) {
      const busy = pending || model.active(node.status), state = pending ? 'submitting' : node.status;
      el.querySelector('[data-control-status]').textContent = model.labels[state] || '就绪';
      el.querySelector('[data-control-status]').classList.toggle('is-success',['succeeded','idle'].includes(state));
      const button = el.querySelector('[data-control-run]'); button.disabled=busy;
      button.setAttribute('aria-busy',String(busy)); button.dataset.controlState=state;
      const icon=busy?'busy':state==='succeeded'?'succeeded':['failed','interrupted'].includes(state)?'failed':'idle';
      if(button.dataset.controlIcon!==icon) { stateIcon.paint(button.querySelector('svg'),icon); button.dataset.controlIcon=icon; }
      button.querySelector('span').textContent=busy ? model.labels[state] : state === 'failed' || state === 'interrupted' ? '重试处理' : state === 'succeeded' ? '已完成' : '开始处理';
      button.setAttribute('aria-label',button.querySelector('span').textContent);
      button.title=state==='succeeded'?'处理完成，点击重新处理':button.querySelector('span').textContent;
      el.querySelectorAll('[data-control-options]').forEach(area => area.hidden=area.dataset.controlOptions!==node.control);
      el.querySelectorAll('[data-control-field],[data-control-import]').forEach(item => item.disabled=busy);
      el.querySelector('[data-control-field="quality"]').disabled=busy || node.control!=='depth';
      const bar=el.querySelector('[data-control-progress]'); bar.hidden=!busy;
      el.querySelector('[data-control-stage]').textContent=pending ? '提交素材…' : model.stageLabel(job?.stage) || model.labels[state];
      progressView?.update(bar, { visible: busy, running: busy, taskId: pending ? '' : job?.id,
        percent: pending ? null : job?.progress_percent, title: pending ? '提交素材…' : model.stageLabel(job?.stage) || model.labels[state],
        detail: 'ReShot · 视频控制', startedAt: pending ? 0 : job?.started_at || job?.created_at,
        finishedAt: job?.finished_at }, el);
    }
    return { html, paint };
  }
  window.DesktopVideoControlView=Object.freeze({create});
})();
