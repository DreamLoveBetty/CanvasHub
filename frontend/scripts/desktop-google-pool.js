// Google account settings controller. Owns only Google UI state; API/auth is injected.
// Load after desktop-api.js and before desktop-settings.js.
(function () {
  function create({ request, renderCard, escapeHtml, onRender, onGptSelected }) {
    let provider = 'gpt';
    let status = null;
    let busy = false;
    let message = '';
    let oauth = null;
    const esc = escapeHtml;
    const button = (action, label, extra = '') => `<button type="button" data-google-pool-action="${action}" ${extra}${busy ? ' disabled' : ''}>${label}</button>`;

    function render(gptHtml) {
      const tabs = `<div class="desk-segment desk-google-pool-tabs${provider === 'google' ? ' desk-google-pool-tabs--compact' : ''}" role="tablist" aria-label="账号池类型">
        <button type="button" role="tab" data-google-pool-provider="gpt" aria-selected="${provider === 'gpt'}" class="${provider === 'gpt' ? 'is-active' : ''}">GPT 账号池</button>
        <button type="button" role="tab" data-google-pool-provider="google" aria-selected="${provider === 'google'}" class="${provider === 'google' ? 'is-active' : ''}">Google OAuth</button>
      </div>`;
      if (provider === 'gpt') return tabs + gptHtml;
      const items = status?.items || [];
      const accounts = items.map(account => {
        const models = (account.models || []).map(model => {
          const label = /^gemini-(3(?:\.1)?)-(pro|flash)-image(?:-preview)?$/.exec(model.name);
          const name = label ? `${label[2] === 'pro' ? 'Pro' : 'Flash'} ${label[1]}` : model.name;
          const detail = model.name + (model.reset_time ? ' · 重置 ' + model.reset_time : '');
          return `<span class="desk-google-pool-model" title="${esc(detail)}">${esc(name)} <b>${model.percentage == null ? '未知' : esc(String(model.percentage)) + '%'}</b></span>`;
        }).join('');
        const id = `data-google-pool-id="${esc(account.id)}"`;
        const name = account.email || 'Google 账号 ' + account.id.slice(0, 8);
        return `<div class="desk-google-pool-account">
          <div class="desk-google-pool-account__head">
            <strong title="${esc(name)}">${esc(name)}</strong>
            <div class="desk-settings-form__actions">
              ${button('account-refresh', '刷新', id + ' title="刷新授权与额度"')}
              ${button('account-update', account.enabled ? '停用' : '启用', id + ` data-google-pool-enabled="${!account.enabled}"`)}
              ${button('account-delete', '删除', id)}
            </div>
          </div>
          <p class="desk-google-pool-note">${account.enabled ? '已启用' : '已停用'} · ${account.requires_relogin ? '需重新授权' : (account.refreshable ? '自动续期' : '临时 Token')} · 成功 ${Number(account.success_count || 0)}</p>
          <div class="desk-google-pool-models">${models || '<span class="desk-google-pool-note">额度未读取</span>'}</div>
          ${account.last_error ? `<p class="desk-google-pool-error">${esc(account.last_error)}</p>` : ''}
        </div>`;
      }).join('');
      const summary = status
        ? `${status.enabled ? '已启用' : '已关闭'} · ${items.length} 个账号${status.stats?.inflight ? ' · ' + Number(status.stats.inflight) + ' 个运行中' : ''}`
        : '未连接';
      return tabs + renderCard('Google 账号', [`<div class="desk-settings-form desk-google-pool" data-google-pool-panel aria-busy="${busy}">
        <div class="desk-google-pool-toolbar">
          <span class="desk-google-pool-note">${esc(summary)}</span>
          <div class="desk-settings-form__actions">
            ${button('config', status?.enabled ? '关闭' : '启用', (status ? '' : 'disabled ') + 'title="启用或关闭 Google 账号池"')}
            ${button('status', '刷新', 'title="读取账号状态"')}
            ${button('oauth-start', '添加授权', 'class="is-primary"')}
          </div>
        </div>
        ${busy || message ? `<p class="desk-google-pool-feedback" role="status">${esc(busy ? '处理中…' : message)}</p>` : ''}
        <p class="desk-google-pool-note">画布线路选择「Google OAuth」即可使用。</p>
        ${oauth ? `<div class="desk-google-pool-oauth">
          <div class="desk-google-pool-toolbar"><a href="${esc(oauth.authorize_url)}" target="_blank" rel="noopener noreferrer">打开 Google 授权</a><span class="desk-google-pool-note">10 分钟内有效</span></div>
          <p class="desk-google-pool-note">完成后刷新；远程登录可粘贴回调链接。</p>
          <div class="desk-google-pool-callback">
            <input type="text" data-google-pool-callback autocomplete="off" spellcheck="false" aria-label="完整回调 URL" placeholder="完整回调 URL（远程登录）">
            <div class="desk-settings-form__actions">${button('oauth-finish', '完成授权')}</div>
          </div>
        </div>` : ''}
        <details class="desk-google-pool-import"><summary>导入 JSON</summary>
          <div class="desk-google-pool-import__body">
            <p class="desk-google-pool-note">支持 Antigravity Tools 导出，保存后不回显。</p>
            <textarea class="desk-settings-textarea" data-google-pool-import rows="3" autocomplete="off" spellcheck="false" aria-label="Google 授权 JSON" placeholder="粘贴账号 JSON"></textarea>
            <div class="desk-settings-form__actions">${button('accounts-import', '导入')}</div>
          </div>
        </details>
        <div class="desk-google-pool-accounts">${accounts || '<p class="desk-google-pool-empty">暂无账号，点击「添加授权」。</p>'}</div>
      </div>`], !!status?.enabled);
    }

    async function run(action, body) {
      busy = true; message = ''; onRender();
      try {
        const result = await request(action, body);
        if (action === 'oauth-start') {
          // Keep authorization navigation user-initiated (a link), avoiding popup blockers.
          const url = new URL(result.authorize_url);
          if (url.origin !== 'https://accounts.google.com') throw new Error('授权地址无效');
          oauth = result;
          message = '';
        } else {
          if (action === 'oauth-finish') { oauth = null; status = await request('status'); }
          else status = result;
          message = action === 'status' ? '' : '已完成';
        }
      } catch (error) {
        // Do not echo user-supplied JSON/authorization codes through parser errors.
        message = error.message || 'Google 账号池操作失败';
      } finally { busy = false; onRender(); }
    }

    function handleClick(event) {
      const tab = event.target.closest('[data-google-pool-provider]');
      if (tab) {
        event.preventDefault();
        provider = tab.dataset.googlePoolProvider === 'google' ? 'google' : 'gpt';
        onRender();
        if (provider === 'google' && !status && !busy) void run('status');
        if (provider === 'gpt') onGptSelected();
        return true;
      }
      const control = event.target.closest('[data-google-pool-action]');
      if (!control) return false;
      event.preventDefault();
      if (busy || control.disabled) return true;
      const action = control.dataset.googlePoolAction;
      const panel = control.closest('[data-google-pool-panel]');
      let body = action === 'status' ? undefined : {};
      if (action === 'config') body.enabled = !status?.enabled;
      if (action === 'oauth-finish') {
        body = { session_id: oauth?.session_id || '', callback: panel.querySelector('[data-google-pool-callback]')?.value || '' };
      }
      if (action === 'accounts-import') {
        try {
          const raw = JSON.parse(panel.querySelector('[data-google-pool-import]')?.value || '');
          body.accounts = Array.isArray(raw) ? raw : (Array.isArray(raw?.accounts) ? raw.accounts : [raw]);
        } catch (_) { message = '请输入有效的授权 JSON。'; onRender(); return true; }
      }
      if (action.startsWith('account-')) {
        body.account_id = control.dataset.googlePoolId;
        if (action === 'account-update') body.enabled = control.dataset.googlePoolEnabled === 'true';
        if (action === 'account-delete' && !window.confirm('删除此 Google 账号的本地授权？不会影响 GPT 账号。')) return true;
      }
      void run(action, body);
      return true;
    }
    return { render, handleClick, isGoogle: () => provider === 'google', refresh: () => run('status') };
  }
  window.DesktopGooglePool = { create };
})();
