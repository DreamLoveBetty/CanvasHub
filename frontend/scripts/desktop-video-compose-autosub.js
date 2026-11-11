// Automatic subtitles in the compose workbench: the 「自动字幕」 button and script choice in the
// subtitle panel, one recognition job at a time (submit, poll, cancel) and handing the resulting
// draft cues back to the controller. The cues replace the node's subtitles only after the user
// agreed; they are a draft to edit, never burned in by themselves. Recognition runs on the server
// (POST /api/video_edit/transcribe, Qwen3-ASR); readiness comes from DesktopAsrAPI.
(function () {
  const POLL_MS = 800;
  const SCRIPT_KEY = 'desk-video-compose-asr-script';
  const SCRIPTS = Object.freeze([['original', '原文'], ['traditional', '繁体'], ['simplified', '简体']]);

  const readScript = () => {
    try { const value = window.localStorage.getItem(SCRIPT_KEY); return SCRIPTS.some(([key]) => key === value) ? value : 'original'; }
    catch (_error) { return 'original'; }
  };
  const saveScript = value => { try { window.localStorage.setItem(SCRIPT_KEY, value); } catch (_error) { /* per-viewer convenience only */ } };

  // root: the workbench. request(s) -> {body} or {reason}; apply(s, cues) replaces the session's cues.
  function create({root, api, asr, showMessage, confirm = message => window.confirm(message), request, apply, current}) {
    const q = selector => root.querySelector(selector);
    const button = q('[data-cb-sub="auto"]'), select = q('[data-cb-sub-script]'), status = q('[data-cb-auto-status]');
    let op = null; // {s, id, stage, percent, cancelled, before}
    select.value = readScript();

    function paint() {
      const busy = Boolean(op);
      const mine = busy && op.s === current();
      button.disabled = busy;
      button.textContent = mine ? `识别中 ${op.percent}%` : '自动字幕';
      select.disabled = busy;
      status.hidden = !mine;
      if (mine) status.querySelector('span').textContent = op.stage || '语音识别中';
    }

    const finish = message => { op = null; paint(); if (message) showMessage(message); };

    async function poll(task) {
      if (op !== task) return;
      let job;
      try { job = await api.job(task.id); }
      catch (error) { if (op === task) finish(/不存在|过期/.test(error.message || '') ? '自动字幕任务已失效，请重试' : error.message); return; }
      if (op !== task) return;
      if (job.status === 'queued' || job.status === 'running') {
        task.stage = job.stage;
        task.percent = Math.max(0, Math.min(99, Math.round(Number(job.progress_percent) || 0)));
        paint();
        setTimeout(() => poll(task), POLL_MS);
        return;
      }
      if (job.status === 'cancelled') { finish('已取消自动字幕'); return; }
      if (job.status !== 'succeeded') { finish(job.error || '自动字幕失败'); return; }
      const result = api.transcribeResult(job);
      op = null;
      paint();
      if (!result.speech || !result.cues.length) { showMessage('没有识别到人声（可能只有音乐或环境声）'); return; }
      const cues = task.s.node.subtitles.cues;
      if (cues.length && JSON.stringify(cues) !== task.before
        && !confirm(`识别完成，用 ${result.cues.length} 条自动字幕替换你刚改过的 ${cues.length} 条字幕？`)) return;
      if (apply(task.s, result.cues)) showMessage(`已生成 ${result.cues.length} 条字幕草稿，请检查文字和时间后再合成`);
    }

    async function start() {
      const s = current();
      if (op || !s) return;
      const prepared = request(s);
      if (prepared.reason) { showMessage(prepared.reason); return; }
      const task = {s, id: '', stage: '检查语音识别环境', percent: 0, cancelled: false, before: ''};
      op = task;
      paint();
      try {
        const state = await asr.status();
        if (!state.ready) {
          finish(state.preparation.status === 'running' ? '语音识别环境正在准备，请稍后再试'
            : '语音识别环境未准备：请到 设置中心 › 模型工具 › 语音识别 准备');
          return;
        }
        if (task.cancelled) { finish(); return; }
        const count = s.node.subtitles.cues.length;
        if (count && !confirm(`自动字幕会替换现有 ${count} 条字幕，继续？`)) { finish(); return; }
        task.before = JSON.stringify(s.node.subtitles.cues);
        task.stage = '提交中';
        paint();
        const job = await api.transcribe({recipe: prepared.body, script: select.value});
        task.id = job.id;
        if (task.cancelled) { await api.cancel(job.id).catch(() => {}); finish(); return; }
        poll(task);
      } catch (error) {
        if (op === task) finish(error.message || '自动字幕失败');
      }
    }

    async function cancel() {
      const task = op;
      if (!task) return;
      task.cancelled = true;
      task.stage = '正在取消';
      paint();
      if (task.id) await api.cancel(task.id).catch(error => showMessage(error.message));
    }

    function click(event) {
      const action = event.target.closest('[data-cb-sub]')?.dataset.cbSub;
      if (action === 'auto') { start(); return true; }
      if (action === 'auto-cancel') { cancel(); return true; }
      return false;
    }

    function change(event) {
      if (event.target !== select) return false;
      saveScript(select.value);
      return true;
    }

    return Object.freeze({paint, click, change, busy: () => Boolean(op)});
  }

  window.DesktopVideoComposeAutosub = Object.freeze({create, SCRIPTS});
})();
