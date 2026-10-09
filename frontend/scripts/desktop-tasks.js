// Neutral task contracts. No polling, canvas state, storage, provider routing or DOM.
(function () {
  const aliases = { processing: 'running', canceled: 'cancelled', succeeded_no_telegram: 'succeeded', completed: 'succeeded' };
  const statuses = new Set(['idle','submitting','queued','running','cancelling','cancelled','succeeded','partial','failed','interrupted']);
  function snapshot(domain, raw = {}, artifacts = []) {
    const status = aliases[raw.status] || raw.status;
    const amount = raw.progress ?? raw.progress_percent;
    return { schema_version: 1, domain, task_id: String(raw.task_id || raw.id || raw.batch_id || ''),
      status: statuses.has(status) ? status : 'unknown', stage: String(raw.stage || ''),
      message: String(raw.progress_text || raw.progress_message || raw.message || ''),
      progress: amount == null || amount === '' || !Number.isFinite(Number(amount)) ? null : Math.max(0, Math.min(100, Number(amount))),
      error: String(raw.display_error || raw.error || ''), artifacts: Array.isArray(artifacts) ? artifacts.map(a => ({...a})) : [], raw };
  }
  function createClient({ domain, submit, progress, cancel, artifacts = raw => raw.artifacts || [] }) {
    if (!domain || [submit, progress, cancel, artifacts].some(fn => typeof fn !== 'function')) throw Error('任务适配器缺少必要接口');
    const inspect = raw => snapshot(domain, raw, artifacts(raw));
    const client = { inspect,
      submit: async (...args) => inspect(await submit(...args)),
      progress: async (...args) => inspect(await progress(...args)),
      cancel: async (...args) => inspect(await cancel(...args)),
      // Receipt reuse avoids another request; IDs query once. Neither path waits/polls.
      result: async value => typeof value === 'string' ? client.progress(value) : inspect(value?.raw || value),
    };
    return Object.freeze(client);
  }
  function createRegistry({ reportStatus }) {
    const domains = new Map(), cancellations = new Map();
    function get(domain) { const adapter = domains.get(domain); if (!adapter) throw Error('未注册任务领域：' + domain); return adapter; }
    const registry = {
      register(domain, adapter) {
        if (domains.has(domain)) throw Error('任务领域重复注册：' + domain);
        if (!adapter || typeof adapter.client !== 'function') throw Error('任务领域缺少 client');
        domains.set(domain, adapter);
        return () => { if (domains.get(domain) === adapter) domains.delete(domain); };
      },
      submit: async (domain, ...args) => get(domain).client().submit(...args),
      progress: async (domain, ...args) => get(domain).client().progress(...args),
      cancel: async (domain, ...args) => get(domain).client().cancel(...args),
      result: async (domain, ...args) => get(domain).client().result(...args),
      report(domain, feedback) {
        get(domain);
        const task = feedback.task || {};
        reportStatus({...feedback, task: {...task, task_domain: domain,
          progress_text: task.progress_text || task.message || task.stage || feedback.message || ''}});
      },
      showStatus(nodeId) { domains.forEach(adapter => adapter.showStatus?.(nodeId)); },
      listCancelable() {
        const seen = new Set(), entries = [];
        domains.forEach((adapter, domain) => {
          for (const entry of adapter.listCancelable?.() || []) {
            if (typeof entry.cancel !== 'function' || !entry.key) throw Error('取消任务必须提供稳定 key 和 cancel');
            const key = domain + ':' + entry.key;
            if (seen.has(key)) continue;
            seen.add(key); entries.push({...entry, domain, key});
          }
        });
        return entries;
      },
      async cancelAll() {
        const entries = registry.listCancelable();
        const results = await Promise.allSettled(entries.map(entry => {
          if (!cancellations.has(entry.key)) {
            const pending = Promise.resolve().then(entry.cancel).finally(() => cancellations.delete(entry.key));
            cancellations.set(entry.key, pending);
          }
          return cancellations.get(entry.key);
        }));
        return { total: entries.length, failed: results.filter(r => r.status === 'rejected').length, results };
      },
    };
    return Object.freeze(registry);
  }
  window.DesktopTasks = Object.freeze({createClient, createRegistry, snapshot});
})();
