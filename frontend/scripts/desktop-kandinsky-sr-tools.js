// Settings-center card for Kandinsky ImageSR 2.0: readiness, one-click prepare (isolated Python 3.12 venv + pinned weights), and progress.
(function () {
  function create({ api, escapeHtml: esc, rerender, notify } = {}) {
    const state = { loaded: false, loading: false, busy: false, data: null, timer: 0, active: false, lastKey: '' };
    const tell = (message, tone = 'info') => notify?.(message, tone);
    const running = () => state.data?.preparation?.status === 'running';
    const gib = value => `${((Number(value) || 0) / 1024 ** 3).toFixed(1)} GiB`;

    function schedule() {
      clearTimeout(state.timer);
      if (running()) state.timer = setTimeout(() => refresh().catch(() => {}), state.active ? 1500 : 4000);
    }

    function settle() {
      const operation = state.data?.preparation || {};
      const key = operation.status;
      if (state.lastKey === 'running' && key === 'succeeded') {
        tell('Kandinsky SR 2.0 环境已就绪，可以在画布使用超分节点。', 'success');
      } else if (state.lastKey === 'running' && key === 'failed') {
        tell(operation.message || 'Kandinsky SR 2.0 环境准备失败', 'error');
      }
      state.lastKey = key;
    }

    async function refresh() {
      if (state.loading) return;
      state.loading = true;
      try {
        state.data = await api.status();
        state.loaded = true;
        settle();
      } finally {
        state.loading = false;
        rerender?.();
        schedule();
      }
    }

    const card = (body, ok) => (
      `<section class="desk-settings-card ${ok ? 'is-ok' : 'is-warn'} desk-moss-tools" data-kandinsky-sr-tools>`
      + '<header><span class="desk-settings-dot" aria-hidden="true"></span><h3>图像超分（Kandinsky SR 2.0）</h3></header>'
      + `<div class="desk-settings-card__body">${body}</div></section>`
    );

    const row = (label, value) => (
      `<div class="desk-moss-tools__row"><span>${esc(label)}</span><strong title="${esc(value)}">${esc(value)}</strong></div>`
    );

    function progressHtml(operation) {
      if (operation.status !== 'running' && operation.status !== 'failed') return '';
      const percent = operation.total ? Math.max(0, Math.min(100, (operation.downloaded / operation.total) * 100)) : 0;
      const label = operation.status === 'failed' ? '失败' : operation.stage === 'assets' ? '下载模型' : '准备中';
      return (
        `<div class="desk-qwen21-tools__progress ${operation.status === 'failed' ? 'is-error' : ''}">`
        + `<div><strong>${esc(label)}</strong><span>${esc(operation.message)}</span>`
        + `<em>${operation.total ? `${gib(operation.downloaded)} / ${gib(operation.total)}` : ''}</em></div>`
        + `${operation.total ? `<div class="desk-qwen21-tools__bar"><span style="width:${percent.toFixed(1)}%"></span></div>` : ''}`
        + '</div>'
      );
    }

    function render() {
      if (!state.loaded) {
        return card(`<div class="desk-settings-empty">${state.loading ? '正在读取 Kandinsky SR 2.0 状态…' : '打开页面后读取 Kandinsky SR 2.0 状态。'}</div>`, false);
      }
      const data = state.data;
      const operation = data.preparation;
      const locked = running() || state.busy;
      const reasons = data.ready ? [] : data.reasons;
      return card(
        `<div class="desk-moss-tools__rows">`
        + row('引擎', data.modelVariant || 'Kandinsky ImageSR 2.0')
        + row('状态', data.ready ? '已就绪' : running() ? '准备中' : '未就绪')
        + row('模型体积', gib(data.downloadBytes))
        + '</div>'
        + reasons.map(reason => `<p class="desk-settings-form__hint">${esc(reason)}</p>`).join('')
        + progressHtml(operation)
        + `<div class="desk-settings-form__actions"><button type="button" class="${data.ready ? '' : 'is-primary'}" data-kandinsky-sr-prepare ${locked ? 'disabled' : ''}>${data.ready ? '重新准备' : '准备环境'}</button></div>`
        + `<p class="desk-settings-form__hint">准备会创建独立 Python 3.12 环境并下载 Kandinsky-ImageSR-2.0 权重（约 ${gib(data.downloadBytes)}）。每次超分在独立后台进程单次运行，结束后立即释放内存。</p>`,
        Boolean(data.ready)
      );
    }

    async function prepare() {
      state.busy = true;
      rerender?.();
      try {
        const reply = await api.prepare();
        state.data = { ...state.data, ready: false, preparation: reply.preparation };
        state.lastKey = 'running';
        schedule();
      } finally {
        state.busy = false;
        rerender?.();
      }
    }

    function handleClick(event) {
      const button = event.target.closest('[data-kandinsky-sr-prepare]');
      if (!button) return false;
      event.preventDefault();
      if (state.busy || running()) return true;
      if (state.data?.ready && window.confirm && !window.confirm('环境已就绪，确定重新准备？会重建隔离环境并校验模型文件。')) {
        return true;
      }
      prepare().catch(error => tell(error?.message || 'Kandinsky SR 2.0 环境准备失败', 'error'));
      return true;
    }

    async function activate() {
      state.active = true;
      await refresh();
    }

    function deactivate() {
      state.active = false;
      schedule();
    }

    return Object.freeze({
      render: () => render(),
      activate,
      deactivate,
      refresh,
      handleClick,
      handleInput: () => false,
      state,
    });
  }

  window.DesktopKandinskySrTools = Object.freeze({ create });
})();
