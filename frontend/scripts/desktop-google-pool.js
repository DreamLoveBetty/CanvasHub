// Google account settings controller. Owns only Google UI state; API/auth is injected.
// Load after desktop-api.js and before desktop-settings.js.
(function () {
  function create({ request, renderCard, escapeHtml, onRender, onGptSelected, webSettings = null, now = () => Date.now() }) {
    let provider = 'gpt';
    let status = null;
    let busy = false;
    let message = '';
    let oauth = null;
    let slide = { from: null, to: null, at: 0 };
    const esc = escapeHtml;

    function parseReset(resetTime) {
      if (!resetTime || typeof resetTime !== 'string') return null;
      const ms = Date.parse(resetTime);
      return Number.isFinite(ms) ? ms : null;
    }

    function formatCountdown(resetTime) {
      const ms = parseReset(resetTime);
      if (ms == null) return '';
      const delta = ms - now();
      if (delta <= 0) return '已到期';
      const total = Math.floor(delta / 1000);
      const days = Math.floor(total / 86400);
      const hours = Math.floor((total % 86400) / 3600);
      const mins = Math.floor((total % 3600) / 60);
      const parts = [];
      if (days) parts.push(`${days}天`);
      if (hours) parts.push(`${hours}小时`);
      if (mins) parts.push(`${mins}分`);
      return parts.join('') || '不足1分';
    }

    function barWidth(percentage) {
      if (typeof percentage !== 'number' || !Number.isFinite(percentage) || percentage < 0 || percentage > 100) return null;
      return percentage;
    }

    function barTone(percentage) {
      const width = barWidth(percentage);
      if (width == null) return '';
      if (width < 20) return ' is-low';
      if (width < 50) return ' is-warn';
      return '';
    }

    function percentLabel(percentage) {
      const width = barWidth(percentage);
      return width == null ? '未知' : `${Math.round(width)}%`;
    }

    const FAMILY_ORDER = ['claude', 'gemini', 'argon', 'carbon'];
    const FAMILY_TITLE = { claude: 'Claude', gemini: 'Gemini', argon: 'Argon', carbon: 'Carbon' };

    // Exact Cockpit v1.4.2 summary_bucket_family rules: official bucketId only.
    function officialBucketFamily(bucketId) {
      const name = String(bucketId || '').trim();
      if (!name) return '';
      if (name === '3p-5h' || name === 'claude:5h' || name === '3p-weekly' || name === 'claude:weekly') return 'claude';
      if (name === 'gemini-5h' || name === 'gemini:5h' || name === 'gemini-weekly' || name === 'gemini:weekly') return 'gemini';
      if (name === 'argon:weekly' || name === 'argon:5h') return 'argon';
      if (name === 'carbon:weekly' || name === 'gemini-carbon-wtu-weekly') return 'carbon';
      if (name.startsWith('gemini-argon-') && (name.endsWith('-weekly') || name.endsWith('-5h'))) return 'argon';
      return '';
    }

    function officialBucketWindow(bucket) {
      const window = String(bucket && bucket.window || '').trim();
      const family = officialBucketFamily(bucket && bucket.bucket_id);
      if (window === '5h' || window === 'weekly') return window;
      if (!family) return window;
      const name = String(bucket.bucket_id || '').trim();
      if (name.endsWith('-5h') || name.endsWith(':5h')) return '5h';
      if (name.endsWith('-weekly') || name.endsWith(':weekly')) return 'weekly';
      return window;
    }

    function windowSortKey(bucket) {
      const window = officialBucketWindow(bucket);
      if (window === '5h') return 0;
      if (window === 'weekly') return 1;
      return 2;
    }

    const isArgonModel = value => /argon/i.test(String(value || ''));
    const isCarbonModel = value => /carbon/i.test(String(value || ''));
    const isSharedGeminiModel = value => {
      const name = String(value || '').toLowerCase();
      return name.includes('gemini') && !isArgonModel(name) && !isCarbonModel(name);
    };

    function uiLanguage() {
      const language = window.DesktopI18n?.state?.language
        || (typeof document !== 'undefined' && document.documentElement?.getAttribute?.('data-lang'))
        || (typeof document !== 'undefined' && document.documentElement?.lang === 'en' ? 'en' : 'zh');
      return language === 'en' ? 'en' : 'zh';
    }

    function localizeUi(zh) {
      if (uiLanguage() === 'en' && typeof window.DesktopI18n?.translate === 'function') {
        return window.DesktopI18n.translate(zh, 'en');
      }
      return zh;
    }

    function officialWindowTitle(bucket) {
      const windowKind = officialBucketWindow(bucket);
      if (windowKind === '5h') return localizeUi('5 小时额度');
      if (windowKind === 'weekly') return localizeUi('周额度');
      const label = String(bucket.display_name || '').trim();
      const rawWindow = String(bucket.window || '').trim();
      return label || rawWindow || '未知窗口';
    }

    function windowLabel(bucket) {
      return officialWindowTitle(bucket);
    }

    function hasUsableQuota(percentage) {
      return barWidth(percentage) != null;
    }

    function modelLabel(name) {
      const label = /^gemini-(3(?:\.1)?)-(pro|flash)-image(?:-preview)?$/.exec(name || '');
      return label ? `${label[2] === 'pro' ? 'Pro' : 'Flash'} ${label[1]}` : name;
    }

    function numericPercentages(models) {
      return models
        .map(model => model && model.percentage)
        .filter(value => typeof value === 'number' && Number.isFinite(value));
    }

    function compactPercentLabel(models) {
      const known = numericPercentages(models);
      const missing = known.length !== models.length;
      if (!known.length) return '未知';
      const min = Math.round(Math.min(...known));
      const max = Math.round(Math.max(...known));
      const range = min === max ? `${min}%` : `${min}%–${max}%`;
      return missing ? `${range}，部分未知` : range;
    }

    function compactResetLabel(models) {
      const values = models.map(model => String(model && model.reset_time || ''));
      const unique = [...new Set(values)];
      if (unique.length === 1) return formatCountdown(unique[0]);
      const times = unique.filter(Boolean).map(value => Date.parse(value)).filter(value => !Number.isNaN(value));
      if (!times.length) return '重置时间不一';
      times.sort((left, right) => left - right);
      const start = formatCountdown(new Date(times[0]).toISOString());
      const end = formatCountdown(new Date(times[times.length - 1]).toISOString());
      if (!start && !end) return '重置时间不一';
      if (start && start === end) return `重置时间不一 · 范围 ${start}`;
      return `重置时间不一 · 范围 ${[start, end].filter(Boolean).join('–')}`;
    }

    function renderGeminiCatalogSummary(models) {
      if (!models.length) return '';
      const known = numericPercentages(models);
      if (!known.length) return '';
      const resets = models.map(model => String(model && model.reset_time || ''));
      const same = known.length === models.length && new Set(known).size <= 1 && new Set(resets).size <= 1;
      const names = models.map(model => modelLabel(model.name) || model.name).filter(Boolean).join('、');
      const tooltip = ['模型汇总，非官方共享池', `${models.length} 个模型`, names].filter(Boolean).join(' · ');
      const title = `${models.length} 个模型`;
      const heading = 'Gemini 额度（目录汇总）';
      const note = '模型汇总，非官方共享池';
      const row = same ? quotaRow({
        title,
        tooltip,
        percentage: known[0],
        resetTime: resets[0],
      }) : (() => {
        const percentText = compactPercentLabel(models);
        const resetText = compactResetLabel(models);
        const detail = [tooltip, percentText, resetText].filter(Boolean).join(' · ');
        return `<div class="desk-google-pool-quota-family__row" title="${esc(detail)}">
        ${quotaHeader(title, percentText, resetText)}
      </div>`;
      })();
      return renderFamilyCard(heading, `${note ? `<span class="desk-google-pool-note" title="${esc(note)}">${esc(note)}</span>` : ''}${row}`, 'gemini-catalog');
    }

    function quotaHeader(title, percentText, countdown) {
      return `<div class="desk-google-pool-quota-card__top">
        <span class="desk-google-pool-quota-meta">
          <span class="desk-google-pool-quota-label">${esc(title)}</span>
          ${countdown ? `<span class="desk-google-pool-quota-reset">${esc(countdown)}</span>` : ''}
        </span>
        <b>${esc(percentText)}</b>
      </div>`;
    }

    function quotaCard({ title, tooltip, percentage, resetTime }) {
      const width = barWidth(percentage);
      const countdown = formatCountdown(resetTime);
      const detail = [tooltip || title, percentLabel(percentage), countdown].filter(Boolean).join(' · ');
      const bar = width == null ? '' : `<span class="desk-google-pool-quota-bar${barTone(percentage)}" style="width: ${width}%"></span>`;
      return `<div class="desk-google-pool-quota-card" title="${esc(detail)}">
        ${quotaHeader(title, percentLabel(percentage), countdown)}
        <div class="desk-google-pool-quota-track">${bar}</div>
      </div>`;
    }

    function quotaGroup(title, description, cards) {
      if (!cards) return '';
      return renderFamilyCard(title, `${description ? `<span class="desk-google-pool-note" title="${esc(description)}">${esc(description)}</span>` : ''}${cards}`, 'group');
    }

    function quotaRow({ title, tooltip, percentage, resetTime }) {
      const width = barWidth(percentage);
      const countdown = formatCountdown(resetTime);
      const detail = [tooltip || title, percentLabel(percentage), countdown].filter(Boolean).join(' · ');
      const bar = width == null ? '' : `<span class="desk-google-pool-quota-bar${barTone(percentage)}" style="width: ${width}%"></span>`;
      return `<div class="desk-google-pool-quota-family__row" title="${esc(detail)}">
        ${quotaHeader(title, percentLabel(percentage), countdown)}
        <div class="desk-google-pool-quota-track">${bar}</div>
      </div>`;
    }

    function renderFamilyCard(title, rows, familyKey) {
      if (!rows) return '';
      return `<div class="desk-google-pool-quota-family" data-family="${esc(familyKey || '')}">
        <strong title="${esc(title)}">${esc(title)}</strong>
        ${rows}
      </div>`;
    }

    function quotaStatus(account) {
      const status = account.quota_groups_status;
      if (status === 'stale_empty') return '<p class="desk-google-pool-note">本次未返回分组，显示上次缓存</p>';
      if (status === 'stale') return '<p class="desk-google-pool-note">分组额度更新失败，仍显示上次缓存</p>';
      if (status === 'error') return '<p class="desk-google-pool-note">分组额度获取失败</p>';
      if (status === 'empty') return '<p class="desk-google-pool-note">暂无分组额度</p>';
      if (status === 'missing') return '<p class="desk-google-pool-note">分组额度尚未获取</p>';
      return '';
    }

    function bucketTooltip(familyTitle, group, bucket) {
      const title = officialWindowTitle(bucket);
      const officialName = String(bucket.display_name || '').trim();
      return [
        familyTitle,
        group && group.display_name,
        group && group.description,
        title,
        officialName && officialName !== title ? officialName : '',
        bucket.bucket_id,
        officialBucketWindow(bucket) || bucket.window,
      ].filter(Boolean).join(' · ');
    }

    function renderBucketCards(items, familyTitle) {
      return items.filter(({ bucket }) => hasUsableQuota(bucket.percentage)).map(({ group, bucket }) => quotaRow({
        title: officialWindowTitle(bucket),
        tooltip: bucketTooltip(familyTitle, group, bucket),
        percentage: bucket.percentage,
        resetTime: bucket.reset_time,
      })).join('');
    }

    function renderAccountQuota(account) {
      const groups = Array.isArray(account.quota_groups) ? account.quota_groups : [];
      const models = Array.isArray(account.models) ? account.models : [];
      const familyBuckets = { claude: [], gemini: [], argon: [], carbon: [] };
      const unknownBuckets = [];
      for (const group of groups) {
        for (const bucket of group.buckets || []) {
          const family = officialBucketFamily(bucket.bucket_id);
          const item = { group, bucket };
          if (family) familyBuckets[family].push(item);
          else unknownBuckets.push(item);
        }
      }
      for (const family of FAMILY_ORDER) {
        familyBuckets[family].sort((left, right) => windowSortKey(left.bucket) - windowSortKey(right.bucket));
      }
      const groupHtml = FAMILY_ORDER.map(family => renderFamilyCard(
        FAMILY_TITLE[family],
        renderBucketCards(familyBuckets[family], FAMILY_TITLE[family]),
        family,
      )).join('') + renderFamilyCard('其他额度', renderBucketCards(unknownBuckets, '其他额度'), 'other');
      const hasGeminiOfficial = familyBuckets.gemini.length > 0;
      const hasClaudeOfficial = familyBuckets.claude.length > 0;
      const hasArgonOfficial = familyBuckets.argon.length > 0;
      const geminiModels = [];
      const leftover = [];
      for (const model of models) {
        const name = String(model.name || '');
        const lower = name.toLowerCase();
        if (isArgonModel(lower) || isCarbonModel(lower)) {
          if (isArgonModel(lower) && hasArgonOfficial) continue;
          if (isCarbonModel(lower) && familyBuckets.carbon.length) continue;
          leftover.push(model);
          continue;
        }
        if (isSharedGeminiModel(lower)) {
          if (!hasGeminiOfficial) geminiModels.push(model);
          continue;
        }
        if (hasClaudeOfficial && (lower.startsWith('claude') || lower.startsWith('gpt'))) continue;
        leftover.push(model);
      }
      const geminiHtml = hasGeminiOfficial ? '' : renderGeminiCatalogSummary(geminiModels);
      const leftoverUsable = leftover.filter(model => hasUsableQuota(model.percentage));
      const otherHtml = leftoverUsable.length ? renderFamilyCard('其他模型额度', leftoverUsable.map(model => quotaRow({
        title: modelLabel(model.name),
        tooltip: model.name + (model.reset_time ? ' · 重置 ' + model.reset_time : ''),
        percentage: model.percentage,
        resetTime: model.reset_time,
      })).join(''), 'leftover') : '';
      const status = account.quota_groups_status;
      const argonAbsent = !hasArgonOfficial && (status === 'ok' || status === 'stale' || status === 'stale_empty');
      const argonNote = argonAbsent ? '<p class="desk-google-pool-note">本次分组额度未返回 Argon</p>' : '';
      const cards = groupHtml + geminiHtml + otherHtml;
      const body = cards ? `<div class="desk-google-pool-quota-families">${cards}</div>` : '';
      if (!body) return `${quotaStatus(account)}${argonNote}<div class="desk-google-pool-models"><span class="desk-google-pool-note">额度未读取</span></div>`;
      return `<div class="desk-google-pool-quota">${quotaStatus(account)}${argonNote}${body}</div>`;
    }

    const button = (action, label, extra = '') => `<button type="button" data-google-pool-action="${action}" ${extra}${busy ? ' disabled' : ''}>${label}</button>`;

    function render(gptHtml) {
      // A track with one sliding thumb. Switching tabs starts a slide from the old stop; a
      // re-render during the slide (the tab's own data arriving) resumes it where it is.
      const providers = webSettings ? ['gpt', 'google', 'web'] : ['gpt', 'google'];
      const labels = { gpt: 'GPT 账号池', google: 'Google OAuth', web: 'Gemini Web' };
      const index = Math.max(0, providers.indexOf(provider));
      const now = performance.now();
      if (slide.to !== index) slide = { from: slide.to ?? index, to: index, at: now };
      const elapsed = Math.round(now - slide.at);
      const from = elapsed < 1000 ? slide.from : index;
      const tabs = `<div class="desk-track-switch desk-google-pool-tabs" role="tablist" aria-label="账号池类型" style="--track-count: ${providers.length}; --track-index: ${index}; --track-from: ${from}; --track-elapsed: ${elapsed}ms">
        ${providers.map(id => `<button type="button" role="tab" data-google-pool-provider="${id}" aria-selected="${provider === id}" class="${provider === id ? 'is-active' : ''}">${labels[id]}</button>`).join('')}
      </div>`;
      if (provider === 'gpt') return tabs + gptHtml;
      // Each provider's content sits in a settings card, so its fields read against the card.
      if (provider === 'web') return tabs + renderCard('Gemini Web 账号', [webSettings.render()], webSettings.isEnabled());
      const items = status?.items || [];
      const accounts = items.map(account => {
        const id = `data-google-pool-id="${esc(account.id)}"`;
        const name = account.email || 'Google 账号 ' + account.id.slice(0, 8);
        return `<div class="desk-google-pool-account">
          <div class="desk-google-pool-account__head">
            <strong title="${esc(name)}">${esc(name)}</strong>
            <div class="desk-settings-form__actions">
              ${button('account-refresh', '刷新额度', id + ' title="刷新授权与额度"')}
              ${button('account-update', account.enabled ? '停用' : '启用', id + ` data-google-pool-enabled="${!account.enabled}"`)}
              ${button('account-delete', '删除', id)}
            </div>
          </div>
          <p class="desk-google-pool-note">${account.enabled ? '已启用' : '已停用'} · ${account.requires_relogin ? '需重新授权' : (account.refreshable ? '自动续期' : '临时 Token')} · 成功 ${Number(account.success_count || 0)}</p>
          ${renderAccountQuota(account)}
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
            ${button('status', '刷新状态', 'title="读取账号状态，不请求上游改写额度缓存"')}
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
        <section class="desk-google-pool-import"><strong>导入 JSON</strong>
          <div class="desk-google-pool-import__body">
            <p class="desk-google-pool-note">支持 Antigravity Tools 导出，保存后不回显。</p>
            <textarea class="desk-settings-textarea" data-google-pool-import rows="3" autocomplete="off" spellcheck="false" aria-label="Google 授权 JSON" placeholder="粘贴账号 JSON"></textarea>
            <div class="desk-settings-form__actions">${button('accounts-import', '导入')}</div>
          </div>
        </section>
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
        provider = tab.dataset.googlePoolProvider === 'google' ? 'google' : tab.dataset.googlePoolProvider === 'web' && webSettings ? 'web' : 'gpt';
        onRender();
        if (provider === 'google' && !status && !busy) void run('status');
        if (provider === 'web') void webSettings.refresh();
        if (provider === 'gpt') onGptSelected();
        return true;
      }
      if (provider === 'web') return webSettings.handleClick(event);
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
    return { render, handleClick,
      handleChange: event => provider === 'web' && webSettings?.handleChange(event),
      isGoogle: () => provider !== 'gpt', refresh: () => provider === 'web' ? webSettings.refresh() : run('status') };
  }
  window.DesktopGooglePool = { create };
})();
