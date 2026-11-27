// Kandinsky ImageSR 2.0 canvas node controller. Live outputs remain owned by DesktopResults/Tasks.
(function () {
  function create({
    model: M,
    stateIcon,
    loadStatus,
    getState,
    getNodeElement,
    getReferences,
    outputReference,
    save,
    setImageFromResult,
    ensureOutputs,
    submit,
    showError,
    openModelTools = null,
  }) {
    const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const options = (items, current) => items.map(([value, label]) => (
      `<option value="${esc(value)}"${String(value) === String(current) ? ' selected' : ''}>${esc(label)}</option>`
    )).join('');

    let envState = null;
    let envFetchedAt = 0;
    let envPromise = null;
    let envTimer = 0;
    const sizeCache = new Map();

    const icons = {
      idle: '<path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"/>',
      busy: '<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>',
      success: '<path fill="none" stroke="currentColor" stroke-width="2.5" d="m5 12 4 4L20 5"/>',
      error: '<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M6 18 18 6"/>',
    };

    function scheduleEnvWatch() {
      clearTimeout(envTimer);
      if (envState && !envState.ready && envState.preparation?.status === 'running') {
        envTimer = setTimeout(() => refreshStatus(true).catch(() => {}), 2500);
      }
    }

    async function refreshStatus(force = false) {
      if (typeof loadStatus !== 'function') return null;
      if (!force && envState && (Date.now() - envFetchedAt) < 15000) return envState;
      if (envPromise) return envPromise;
      envPromise = loadStatus()
        .then(data => {
          envState = data;
          envFetchedAt = Date.now();
          Object.values(getState?.().canvas?.nodes || {})
            .filter(node => node?.type === M.TYPE)
            .forEach(node => paint(node.id));
          scheduleEnvWatch();
          return data;
        })
        .catch(() => null)
        .finally(() => { envPromise = null; });
      return envPromise;
    }

    function probeSize(src, nodeId) {
      if (!src || typeof Image !== 'function') return null;
      const cached = sizeCache.get(src);
      if (cached && cached.width > 0 && cached.height > 0) return cached;
      if (cached?.pending) return null;
      sizeCache.set(src, { pending: true });
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth > 0 && img.naturalHeight > 0) {
          sizeCache.set(src, { width: img.naturalWidth, height: img.naturalHeight });
          paint(nodeId);
        }
      };
      img.onerror = () => { sizeCache.set(src, { failed: true }); };
      img.src = src;
      return null;
    }

    function nodeHtml(node) {
      M.normalize(node);
      const opts = node.kandinsky_sr;
      const showBanner = Boolean(envState && !envState.ready);
      const bannerText = showBanner
        ? (envState.preparation?.status === 'running' ? (envState.preparation.message || '正在准备 Kandinsky SR 环境…') : (envState.reasons?.[0] || '环境尚未就绪'))
        : '';
      return `<section class="desk-node desk-node--kandinsky-sr desk-glass" data-node-id="${esc(node.id)}" aria-label="Kandinsky SR 2.0 超分节点">
        <header class="desk-ksr__header" data-node-drag-handle>
          <span class="desk-ksr__icon">${M.ICON}</span>
          <div><strong>Kandinsky SR 2.0</strong><small>生成式超分 · 本地</small></div>
          <span class="desk-status-pill" data-output-status>就绪</span>
          <button type="button" class="desk-node-delete" data-node-delete aria-label="删除节点" title="删除节点"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button>
        </header>
        <button type="button" class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接图片输入"></button>
        <button type="button" class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接超分输出"></button>
        <div class="desk-ksr__banner" data-ksr-env-banner ${showBanner ? '' : 'hidden'}>
          <span data-ksr-env-text>${esc(bannerText)}</span>
          <button type="button" class="desk-key" data-ksr-open-settings>前往模型工具</button>
        </div>
        <div class="desk-ksr__grid" data-node-drag-ignore>
          <label><span>放大倍率</span><select class="desk-select" data-ksr-field="upscale_factor">${options([[2, '2×'], [4, '4×']], opts.upscale_factor)}</select></label>
          <label><span>创意度</span><select class="desk-select" data-ksr-field="creativity">${options(M.CREATIVITY_LEVELS, opts.creativity)}</select></label>
          <label><span>分块重叠</span><select class="desk-select" data-ksr-field="overlap">${options(M.OVERLAP_OPTIONS, opts.overlap)}</select></label>
        </div>
        <footer class="desk-ksr__footer" data-node-drag-ignore>
          <div class="desk-ksr__meta">
            <span data-ksr-source>连接图片节点作为输入</span>
            <small data-ksr-estimate>${opts.upscale_factor}× 生成式超分 · 1024px 分块融合 · 自动归档</small>
            <label class="desk-ksr__toggle"><input type="checkbox" data-ksr-telegram ${node.output.telegramEnabled ? 'checked' : ''}><span>发送到 Telegram</span></label>
          </div>
          <button type="button" class="desk-generation-action" data-result-run aria-label="开始超分">${stateIcon.html(icons)}<span class="desk-generation-action__label">开始超分</span></button>
        </footer>
        <div class="desk-progress-float desk-ksr__progress" aria-label="Kandinsky SR 进度" aria-hidden="true">
          <div class="desk-progress-float__panel">
            <div class="desk-progress-float__bar">
              <span data-progress-bar></span>
              <strong class="desk-progress-float__percent" data-progress-percent>
                <span data-progress-percent-value>0%</span>
                <span class="desk-progress-float__timer" data-progress-timer>00:00</span>
              </strong>
            </div>
            <span data-progress-stage class="desk-progress-float__stage">等待任务</span>
          </div>
        </div>
      </section>`;
    }

    function references(id) {
      const refs = getReferences ? getReferences(id) : [];
      if (refs.length) return refs;
      const state = getState?.();
      const edge = (state?.canvas?.edges || []).find(e => e.to === id);
      const source = edge && state?.outputs?.[edge.from];
      const ref = source && outputReference ? outputReference(source, 0, edge.from) : null;
      return ref ? [ref] : [];
    }

    function readConfig(id, explicitRef) {
      const node = getState().canvas.nodes[id];
      if (!node || node.type !== M.TYPE) throw new Error('Kandinsky SR 节点不存在');
      M.normalize(node);
      if (envState && !envState.ready) {
        throw new Error(envState.reasons?.[0] || 'Kandinsky SR 2.0 环境尚未准备，请先前往模型工具准备');
      }
      const ref = explicitRef || references(id)[0];
      if (!ref) throw new Error('请先连接一张图片到 Kandinsky SR 节点');
      return {
        nodeId: id,
        provider: M.TYPE,
        prompt: `Kandinsky SR ${node.kandinsky_sr.upscale_factor}×：${ref.title || ref.name || '图片'}`,
        batchMode: false,
        expectedImageOutputCount: 1,
        params: {
          model: M.MODEL_ID,
          kandinsky_sr: { ...node.kandinsky_sr },
          archiveEnabled: true,
          telegramEnabled: node.output.telegramEnabled === true,
        },
        referenceImages: [ref],
      };
    }

    function paint(id) {
      const state = getState?.();
      const node = state?.canvas?.nodes?.[id];
      const el = getNodeElement?.(id);
      if (node?.type !== M.TYPE || !el) return;
      M.normalize(node);

      const output = state.outputs?.[id] || {};
      const status = output.status;
      const busy = DesktopState.isInFlight(status);
      const unavailable = Boolean(envState && !envState.ready);
      const icon = busy ? 'busy' : DesktopState.isSuccess(status) ? 'success' : DesktopState.isFailure(status) ? 'error' : 'idle';

      const banner = el.querySelector('[data-ksr-env-banner]');
      if (banner) {
        banner.hidden = !unavailable;
        if (unavailable) {
          const txt = banner.querySelector('[data-ksr-env-text]');
          if (txt) {
            txt.textContent = envState.preparation?.status === 'running'
              ? (envState.preparation.message || '正在准备 Kandinsky SR 环境…')
              : (envState.reasons?.[0] || 'Kandinsky SR 环境尚未准备');
          }
        }
      }

      const button = el.querySelector('[data-result-run]');
      if (button) {
        if (button.dataset.ksrIcon !== icon) {
          stateIcon.paint(button.querySelector('svg'), icon);
          button.dataset.ksrIcon = icon;
        }
        button.disabled = busy || unavailable;
        button.setAttribute('aria-busy', String(busy));
        const label = busy
          ? (status === 'queued' ? '排队中' : '超分中')
          : icon === 'success' ? '已完成'
          : icon === 'error' ? '重试超分'
          : status === 'canceled' ? '已停止' : '开始超分';
        const span = button.querySelector('span');
        if (span) span.textContent = label;
        button.setAttribute('aria-label', label);
      }

      const ref = references(id)[0];
      const sourceEl = el.querySelector('[data-ksr-source]');
      if (sourceEl) sourceEl.textContent = ref?.title || '连接图片节点作为输入';

      const estEl = el.querySelector('[data-ksr-estimate]');
      if (estEl) {
        const opts = node.kandinsky_sr;
        const srcUrl = ref?.imageData || ref?.base64 || ref?.imageUrl || ref?.url || '';
        const dims = probeSize(srcUrl, id);
        if (dims) {
          const tiles = M.estimateTiles(dims.width, dims.height, opts.upscale_factor, opts.overlap);
          const outW = dims.width * opts.upscale_factor;
          const outH = dims.height * opts.upscale_factor;
          const warn = tiles > 36 ? ' · 分块较多耗时较长' : '';
          estEl.textContent = `${dims.width}×${dims.height} → ${outW}×${outH} · ${tiles} 块${warn}`;
        } else {
          estEl.textContent = `${opts.upscale_factor}× 生成式超分 · 1024px 分块融合 · 自动归档`;
        }
      }

      el.querySelectorAll('[data-ksr-field], [data-ksr-telegram]').forEach(control => {
        control.disabled = busy;
      });
    }

    function reconcile() {
      const nodes = Object.values(getState?.().canvas?.nodes || {});
      if (loadStatus && nodes.some(n => n?.type === M.TYPE) && (!envState || (Date.now() - envFetchedAt) > 15000)) {
        refreshStatus().catch(() => {});
      }
      for (const node of nodes) {
        if (node?.type !== M.TYPE) continue;
        const el = getNodeElement?.(node.id);
        if (!el) continue;
        if (!el.dataset.ksrBound) {
          el.dataset.ksrBound = '1';
          el.addEventListener('change', event => {
            const target = event.target;
            const live = getState().canvas.nodes[node.id];
            if (live !== node) return;
            const key = target.dataset.ksrField;
            if (key) {
              node.kandinsky_sr[key] = Number(target.value);
              M.normalize(node);
            } else if (target.hasAttribute('data-ksr-telegram')) {
              node.output.telegramEnabled = target.checked;
            } else {
              return;
            }
            save?.();
            paint(node.id);
          });
          el.addEventListener('click', event => {
            if (event.target.closest('[data-ksr-open-settings]')) {
              event.preventDefault();
              openModelTools?.();
            }
          });
        }
        paint(node.id);
      }
    }

    function changed(from, to) {
      reconcile();
      const state = getState?.();
      if (state?.canvas?.nodes?.[from]?.type === M.TYPE && state?.canvas?.nodes?.[to]?.type === 'image' && state?.outputs?.[from]?.imagePaths?.length) {
        setImageFromResult?.(to, from, state.outputs[from], 0)?.catch?.(() => {});
      }
    }

    async function runChains(id, output) {
      const state = getState?.();
      const graph = state?.canvas;
      if (!graph || !['input', 'comfy', 'krea2', 'qwen21', 'moss'].includes(graph.nodes?.[id]?.type)) return 0;
      const ref = outputReference?.(output, 0, id);
      const key = output?.taskId || output?.primaryImagePath;
      if (!ref || !key) return 0;
      let count = 0;
      for (const edge of (graph.edges || []).filter(e => e.from === id && graph.nodes?.[e.to]?.type === M.TYPE)) {
        if (getState().canvas !== graph) break;
        const node = graph.nodes[edge.to];
        if (!node || node.type !== M.TYPE || !graph.edges.includes(edge)) continue;
        if (state.outputs?.[id]?.taskId && state.outputs[id].taskId !== key) break;
        if (node.kandinskySrSourceKey === key || DesktopState.isInFlight(state.outputs?.[edge.to]?.status)) continue;
        node.kandinskySrSourceKey = key;
        count += 1;
        try {
          const config = readConfig(node.id, ref);
          ensureOutputs?.(node.id, config);
          await submit?.(config, node.id);
        } catch (error) {
          if (getState().canvas.nodes[node.id] === node) {
            node.kandinskySrSourceKey = '';
            showError?.(error, node.id);
          }
        }
      }
      return count;
    }

    return Object.freeze({
      nodeHtml,
      reconcile,
      readConfig,
      paint,
      runChains,
      refreshStatus,
      connections: {
        targets: M.targets,
        policy: M.policy,
        changed,
        removed: () => reconcile(),
      },
    });
  }

  window.DesktopCanvasKandinskySr = Object.freeze({ create });
})();
