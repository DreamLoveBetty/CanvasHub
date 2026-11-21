const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-google-pool.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'frontend/styles/desktop-layout.css'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
const escapeHtml = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NOW = Date.parse('2026-11-20T13:59:32Z');

function claudeGroup(overrides = {}) {
  return {
    display_name: 'Claude and GPT models',
    description: 'Models within this group: Claude Sonnet 4.6, GPT-OSS 120B',
    buckets: [
      { bucket_id: '3p-weekly', window: 'weekly', remaining_fraction: 1, percentage: 100, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
      { bucket_id: '3p-5h', window: '5h', remaining_fraction: 1, percentage: 100, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
    ],
    ...overrides,
  };
}

function fixture(overrides = {}) {
  const calls = [], renders = [];
  const language = overrides.language === 'en' ? 'en' : 'zh';
  const state = { enabled: true, stats: { inflight: 0 }, items: [], ...overrides };
  delete state.language;
  const i18n = {
    state: { language },
    translate(value, lang = language) {
      if (lang !== 'en') return String(value ?? '');
      const map = { '5 小时额度': '5-hour quota', '周额度': 'Weekly quota' };
      return map[value] || String(value ?? '');
    },
  };
  const context = vm.createContext({
    URL,
    performance: { now: () => 0 },
    Date,
    document: {
      documentElement: {
        lang: language === 'en' ? 'en' : 'zh-CN',
        getAttribute: name => (name === 'lang' ? (language === 'en' ? 'en' : 'zh-CN') : name === 'data-lang' ? language : null),
      },
    },
    window: { confirm: () => true, Date, DesktopI18n: i18n },
  });
  vm.runInContext(source, context);
  let gptSelected = 0;
  const ui = context.window.DesktopGooglePool.create({
    request: async (action, body) => {
      calls.push(JSON.parse(JSON.stringify({ action, body })));
      if (action === 'oauth-start') {
        return { authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?fixture=1', session_id: 'fixture-session' };
      }
      return state;
    },
    renderCard: (title, content) => `<h3>${title}</h3>${content.join('')}`,
    escapeHtml,
    onRender: () => renders.push(ui.render('GPT unchanged')),
    onGptSelected: () => gptSelected++,
    now: () => NOW,
  });
  function tab(provider) {
    const control = { dataset: { googlePoolProvider: provider } };
    ui.handleClick({ preventDefault() {}, target: { closest: selector => selector === '[data-google-pool-provider]' ? control : null } });
  }
  function click(action, { values = {}, id = 'fixture-id', enabled = 'false' } = {}) {
    const control = {
      dataset: { googlePoolAction: action, googlePoolId: id, googlePoolEnabled: enabled },
      closest: () => ({ querySelector: selector => ({ value: values[selector] || '' }) }),
    };
    ui.handleClick({ preventDefault() {}, target: { closest: selector => selector === '[data-google-pool-action]' ? control : null } });
  }
  return { ui, state, calls, renders, tab, click, get gptSelected() { return gptSelected; } };
}

async function googleHtml(overrides) {
  const f = fixture(overrides);
  f.tab('google');
  await settle();
  return { f, html: f.ui.render('') };
}

test('one real group renders as one heading with two window cards, not two groups', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      email: 'person@example.test',
      enabled: true,
      refreshable: true,
      success_count: 2,
      quota_groups_status: 'ok',
      quota_groups_updated_at: 1763613578,
      quota_groups: [claudeGroup()],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 70, reset_time: '2026-11-20T18:59:32Z' },
        { name: 'claude-sonnet-4-6', percentage: 100, reset_time: '2026-11-20T18:59:32Z' },
      ],
    }],
  });
  assert.equal((html.match(/class="desk-google-pool-quota-families"/g) || []).length, 1);
  assert.equal((html.match(/class="desk-google-pool-quota-family"/g) || []).length, 2); // Claude family + Gemini catalog
  assert.equal((html.match(/class="desk-google-pool-quota-family__row"/g) || []).length, 3); // two group buckets + gemini supplement model
  assert.match(html, /Claude and GPT models/);
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /模型汇总，非官方共享池/);
  assert.match(html, /本次分组额度未返回 Argon/);
  assert.match(html, /Weekly Limit Remaining|weekly/);
  assert.match(html, /Five Hour Limit Remaining|5h/);
  assert.match(html, /100%/);
  assert.match(html, /desk-google-pool-quota-bar/);
  assert.doesNotMatch(html, /Gemini 4 Argon/);
  // email stays in the identity head, not copied into quota cards
  assert.match(html, /title="person@example\.test"/);
  const quotaBlock = html.slice(html.indexOf('desk-google-pool-quota'));
  assert.doesNotMatch(quotaBlock, /person@example\.test/);
  // existing actions and status remain
  for (const action of ['account-refresh', 'account-update', 'account-delete']) {
    assert.match(html, new RegExp(`data-google-pool-action="${action}"`));
  }
  assert.match(html, /已启用/);
  assert.match(html, /自动续期/);
});

test('unknown window is shown honestly and out-of-range percentage does not fill the bar', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Custom Family',
        buckets: [
          { bucket_id: 'family-daily', window: 'daily', remaining_fraction: 0.4, percentage: 40, reset_time: '2026-11-21T00:00:00Z', display_name: 'Daily' },
          { bucket_id: 'family-odd', window: '', remaining_fraction: null, percentage: null, reset_time: '' },
          { bucket_id: 'family-zero', window: '5h', remaining_fraction: 0, percentage: 0, reset_time: '2026-11-20T18:59:32Z' },
        ],
      }],
    }],
  });
  assert.match(html, />Daily<|>daily</i);
  assert.doesNotMatch(html, /family-odd|未知窗口/);
  assert.match(html, /0%/);
  assert.match(html, /style="width:\s*40%"/);
  assert.match(html, /style="width:\s*0%"/);
  assert.doesNotMatch(html, /style="width:\s*100%"/);
  assert.doesNotMatch(html, /style="width:\s*150%"/);
});

test('expired or unparseable reset times never show a negative countdown or invented window', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Timers',
        buckets: [
          { bucket_id: 'ok', window: '5h', percentage: 10, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
          { bucket_id: 'expired', window: 'weekly', percentage: 10, reset_time: '2026-11-20T13:59:31Z' },
          { bucket_id: 'bad', window: 'weekly', percentage: 10, reset_time: 'not-a-date' },
          { bucket_id: 'missing', window: 'weekly', percentage: 10, reset_time: '' },
        ],
      }],
    }],
  });
  assert.match(html, /5小时|5 小时|5h/);
  assert.doesNotMatch(html, /(?:^|>|\s)-\d+(?:天|小时|分)/);
  assert.match(html, /已到期|已重置/);
  // unparseable/missing reset does not fabricate 5h/week from the duration
  assert.doesNotMatch(html, /重置 not-a-date/);
});

test('group and model labels are escaped, and missing Gemini groups use a supplement without window tags', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      email: '<unsafe@example.test>',
      enabled: true,
      requires_relogin: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Claude <xss>',
        description: '<script>group</script>',
        buckets: [
          { bucket_id: '3p-weekly', window: 'weekly', percentage: 50, reset_time: '2026-11-27T13:59:32Z', display_name: '<b>Weekly</b>' },
        ],
      }],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 70, reset_time: '2026-11-20T18:59:32Z' },
        { name: 'gemini-3-pro-image-preview', percentage: 0 },
        { name: 'unknown<model>', percentage: null, reset_time: '2026-11-20T18:59:32Z' },
      ],
      last_error: '<script>fixture</script>',
    }],
  });
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /模型汇总，非官方共享池/);
  assert.match(html, /Flash 3\.1/);
  assert.match(html, /70%/);
  assert.match(html, /Pro 3/);
  assert.doesNotMatch(html, /Gemini 额度（目录汇总）[\s\S]*\b5h\b/);
  assert.doesNotMatch(html, /Gemini 额度（目录汇总）[\s\S]*weekly/i);
  assert.doesNotMatch(html, /unknown&lt;model&gt;/);
  assert.match(html, /Claude &lt;xss&gt;/);
  assert.match(html, /&lt;b&gt;Weekly&lt;\/b&gt;/);
  assert.match(html, /&lt;script&gt;group&lt;\/script&gt;/);
  assert.match(html, /&lt;unsafe@example.test&gt;/);
  assert.match(html, /&lt;script&gt;fixture&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  // uncategorized model without a valid fraction is hidden
  assert.doesNotMatch(html, /其他模型额度|unknown&lt;model&gt;/);
});

test('a real Gemini group suppresses the per-model Gemini supplement without inventing mappings', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [
        claudeGroup(),
        {
          display_name: 'Gemini Models',
          buckets: [
            { bucket_id: 'gemini-weekly', window: 'weekly', percentage: 80, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
            { bucket_id: 'gemini-5h', window: '5h', percentage: 60, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
          ],
        },
      ],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 70, reset_time: '2026-11-20T18:59:32Z' },
      ],
    }],
  });
  assert.match(html, /Gemini Models/);
  assert.doesNotMatch(html, /Gemini 模型额度（补充）/);
  assert.doesNotMatch(html, /Gemini 额度（目录汇总）/);
  assert.doesNotMatch(html, /Flash 3\.1/);
});

test('stale or failed grouped quota keeps cached cards and does not fake a full bar or leak secrets', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'stale',
      quota_groups_updated_at: 1763610000,
      quota_groups_last_attempt_at: 1763613578,
      quota_groups: [claudeGroup({ buckets: [
        { bucket_id: '3p-weekly', window: 'weekly', percentage: 25, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
      ] })],
    }],
  });
  assert.match(html, /25%/);
  assert.match(html, /style="width:\s*25%"/);
  assert.match(html, /分组额度|上次|陈旧|缓存/);
  assert.doesNotMatch(html, /style="width:\s*100%"/);
});

test('existing account buttons still send the original payloads', async () => {
  const { f } = await googleHtml({ items: [{ id: 'fixture-id', enabled: true, quota_groups: [], models: [] }] });
  for (const action of ['config', 'account-refresh', 'account-update', 'account-delete']) {
    f.click(action);
    await settle();
  }
  assert.deepEqual(f.calls.slice(1), [
    { action: 'config', body: { enabled: false } },
    { action: 'account-refresh', body: { account_id: 'fixture-id' } },
    { action: 'account-update', body: { account_id: 'fixture-id', enabled: false } },
    { action: 'account-delete', body: { account_id: 'fixture-id' } },
  ]);
});

test('layout css uses a compact auto-fit family row that wraps when narrow', () => {
  assert.match(css, /\.desk-app \.desk-google-pool-quota-families\s*\{[^}]*display:\s*flex/);
  assert.match(css, /\.desk-app \.desk-google-pool-quota-families\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.doesNotMatch(css, /\.desk-app \.desk-google-pool-quota-families\s*\{[^}]*grid-template-columns:\s*repeat\(2,/);
});

test('Claude description mentioning Gemini does not suppress the Gemini model supplement', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup({ description: 'These are not Gemini models; Claude only' })],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 70, reset_time: '2026-11-20T18:56:32Z' },
      ],
    }],
  });
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /模型汇总，非官方共享池/);
  assert.match(html, /Flash 3\.1/);
});

test('Argon models stay as a leftover unless an official Argon bucket is returned', async () => {
  const noGroup = (await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [{ name: 'gemini-4-argon', percentage: 55, reset_time: '2026-11-20T18:56:32Z' }],
    }],
  })).html;
  assert.match(noGroup, /其他模型额度/);
  assert.match(noGroup, /gemini-4-argon/);
  assert.doesNotMatch(noGroup, /<strong title="Argon">Argon<\/strong>/);
  const withGroup = (await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [
        claudeGroup(),
        { display_name: 'Gemini 4 Argon', buckets: [
          { bucket_id: 'argon:weekly', window: 'weekly', percentage: 90, reset_time: '2026-11-27T13:56:32Z', display_name: 'Weekly Limit Remaining' },
        ] },
      ],
      models: [{ name: 'gemini-4-argon', percentage: 55 }],
    }],
  })).html;
  assert.match(withGroup, /<strong title="Argon">Argon<\/strong>/);
  assert.match(withGroup, /90%/);
  assert.doesNotMatch(withGroup, /其他模型额度/);
});

test('empty bucket groups do not render a heading, and first empty is explicit', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'empty',
      quota_groups: [{ display_name: 'Should Not Appear', description: '', buckets: [] }],
      models: [],
    }],
  });
  assert.doesNotMatch(html, /Should Not Appear/);
  assert.doesNotMatch(html, /class="desk-google-pool-quota-group"/);
  assert.match(html, /暂无分组额度/);
  assert.doesNotMatch(html, /style="width:\s*100%"/);
});

test('error and missing statuses are distinct and do not invent a full bar', async () => {
  const errorHtml = (await googleHtml({
    items: [{ id: 'e', enabled: true, quota_groups_status: 'error', quota_groups: [], models: [] }],
  })).html;
  const missingHtml = (await googleHtml({
    items: [{ id: 'm', enabled: true, quota_groups_status: 'missing', quota_groups: [], models: [] }],
  })).html;
  assert.match(errorHtml, /分组额度获取失败/);
  assert.doesNotMatch(errorHtml, /分组额度尚未获取/);
  assert.match(missingHtml, /分组额度尚未获取/);
  assert.doesNotMatch(missingHtml, /分组额度获取失败/);
  assert.doesNotMatch(errorHtml, /style="width:\s*100%"/);
  assert.doesNotMatch(missingHtml, /style="width:\s*100%"/);
});

test('stale empty keeps last cached cards and says groups were not returned this time', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'stale_empty',
      quota_groups_updated_at: 1763610000,
      quota_groups_last_attempt_at: 1763613578,
      quota_groups: [claudeGroup({ buckets: [
        { bucket_id: '3p-weekly', window: 'weekly', percentage: 25, reset_time: '2026-11-27T13:56:32Z', display_name: 'Weekly Limit Remaining' },
      ] })],
    }],
  });
  assert.match(html, /25%/);
  assert.match(html, /本次未返回分组，显示上次缓存/);
  assert.doesNotMatch(html, /style="width:\s*100%"/);
});

test('countdown includes days, hours and minutes without inventing leftover time', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Timers',
        buckets: [
          { bucket_id: 'weekly', window: 'weekly', percentage: 100, reset_time: '2026-11-27T13:56:32Z', display_name: 'Weekly' },
          { bucket_id: 'five', window: '5h', percentage: 100, reset_time: '2026-11-20T18:56:32Z', display_name: 'Five Hour' },
          { bucket_id: 'exact', window: 'weekly', percentage: 100, reset_time: '2026-11-27T13:59:32Z', display_name: 'Exact Week' },
        ],
      }],
    }],
  });
  assert.match(html, /6天23小时57分/);
  assert.match(html, /4小时57分/);
  assert.match(html, /7天/);
  assert.doesNotMatch(html, /7天0小时|7天0分/);
});

test('quota bars mark warn and low thresholds', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Tones',
        buckets: [
          { bucket_id: 'ok', window: '5h', percentage: 80, reset_time: '', display_name: 'High' },
          { bucket_id: 'warn', window: '5h', percentage: 40, reset_time: '', display_name: 'Mid' },
          { bucket_id: 'low', window: '5h', percentage: 10, reset_time: '', display_name: 'Low' },
        ],
      }],
    }],
  });
  assert.match(html, /desk-google-pool-quota-bar is-warn" style="width:\s*40%"/);
  assert.match(html, /desk-google-pool-quota-bar is-low" style="width:\s*10%"/);
  assert.match(html, /desk-google-pool-quota-bar" style="width:\s*80%"/);
  assert.doesNotMatch(html, /desk-google-pool-quota-bar is-(?:warn|low)" style="width:\s*80%"/);
});

test('toolbar and account refresh labels distinguish read-only status from quota write', async () => {
  const { html, f } = await googleHtml({ items: [{ id: 'fixture-id', enabled: true, quota_groups: [], models: [] }] });
  assert.match(html, /data-google-pool-action="status"[^>]*>刷新状态</);
  assert.match(html, /data-google-pool-action="account-refresh"[^>]*>刷新额度</);
  assert.match(html, /data-google-pool-action="account-refresh"[^>]*title="刷新授权与额度"/);
  assert.doesNotMatch(html, /data-google-pool-action="status"[^>]*>刷新</);
  f.click('status');
  await settle();
  assert.equal(f.calls.at(-1).action, 'status');
  assert.equal(f.calls.at(-1).body, undefined);
});

test('status is a read-only GET and account-refresh is a write POST', () => {
  const api = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-api.js'), 'utf8');
  assert.match(api, /function googlePool\(action = 'status', body\)/);
  assert.match(api, /\/api\/google-pool\/' \+ action, action === 'status' \? \{\} : \{[\s\S]*method: 'POST'/);
});

test('quota cards reuse shared theme tokens and do not hardcode bar colors', () => {
  const rule = (selector) => {
    const match = css.match(new RegExp(selector + '\\s*\\{[^}]+\\}'));
    assert.ok(match, 'missing CSS rule ' + selector);
    return match[0];
  };
  const card = rule('\\.desk-app \\.desk-google-pool-quota-card');
  const track = rule('\\.desk-app \\.desk-google-pool-quota-track');
  const bar = rule('\\.desk-app \\.desk-google-pool-quota-bar');
  const warn = rule('\\.desk-app \\.desk-google-pool-quota-bar\\.is-warn');
  const low = rule('\\.desk-app \\.desk-google-pool-quota-bar\\.is-low');
  assert.match(card, /background:\s*var\(--desk-settings-account-background/);
  assert.doesNotMatch(card, /--desk-settings-account-bg\b/);
  assert.match(card, /border:\s*1px solid var\(--desk-settings-pool-chip-border/);
  assert.match(track, /background:\s*var\(--desk-file-progress-background/);
  assert.match(bar, /background:\s*var\(--desk-status-live-dot\)/);
  assert.match(warn, /background:\s*var\(--desk-status-warning-dot\)/);
  assert.match(low, /background:\s*var\(--desk-status-error-dot\)/);
  for (const block of [card, track, bar, warn, low]) {
    assert.doesNotMatch(block, /#(?:207f55|e46b0b|e05252)\b/i);
    assert.doesNotMatch(block, /background:\s*#/);
  }
  assert.doesNotMatch(bar, /--desk-status-success-base|--desk-ink|--desk-red/);
  assert.doesNotMatch(low, /--desk-red/);
});



test('official 3p bucketIds map to Claude windows and do not become Argon or Gemini', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [],
    }],
  });
  assert.match(html, /<strong title="Claude">Claude<\/strong>/);
  assert.match(html, /100%/);
  assert.match(html, /3p-weekly/);
  assert.match(html, /3p-5h/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Gemini">Gemini<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Carbon">Carbon<\/strong>/);
  // Family heading replaces the source group title; source remains in the tooltip only.
  const heads = html.match(/data-family="claude">[\s\S]*?<strong[^>]*>[^<]+<\/strong>/g) || [];
  assert.equal(heads.length, 1);
  assert.match(heads[0], />Claude</);
  assert.doesNotMatch(heads[0], /Claude and GPT models/);
});

test('claude alias bucketIds map to Claude and do not cross into other families', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Shared source group',
        description: 'Contains Claude aliases only',
        buckets: [
          { bucket_id: 'claude:weekly', window: 'weekly', percentage: 42, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
          { bucket_id: 'claude:5h', window: '5h', percentage: 18, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
        ],
      }],
    }],
  });
  assert.match(html, /<strong title="Claude">Claude<\/strong>/);
  assert.match(html, /42%/);
  assert.match(html, /18%/);
  assert.match(html, /desk-google-pool-quota-bar is-low" style="width:\s*18%"/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Gemini">Gemini<\/strong>/);
});

test('official Gemini aliases render Gemini windows and suppress the model supplement', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Gemini Models',
        buckets: [
          { bucket_id: 'gemini:weekly', window: 'weekly', percentage: 80, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
          { bucket_id: 'gemini-5h', window: '5h', percentage: 60, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
        ],
      }],
      models: [{ name: 'gemini-3.1-flash-image', percentage: 70, reset_time: '2026-11-20T18:59:32Z' }],
    }],
  });
  assert.match(html, /<strong title="Gemini">Gemini<\/strong>/);
  assert.match(html, /80%/);
  assert.match(html, /60%/);
  assert.doesNotMatch(html, /Gemini 模型额度（补充）/);
  assert.doesNotMatch(html, /Gemini 额度（目录汇总）/);
  assert.doesNotMatch(html, /Flash 3\.1/);
});

test('official Argon aliases and gemini-argon window suffixes show real bucket values only', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Source group',
        buckets: [
          { bucket_id: 'argon:weekly', window: 'weekly', percentage: 90, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
          { bucket_id: 'gemini-argon-wtu-weekly', window: 'weekly', percentage: 33, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
          { bucket_id: 'argon:5h', window: '5h', percentage: 15, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
          { bucket_id: 'gemini-argon-foo-5h', window: '5h', percentage: 7, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
        ],
      }],
    }],
  });
  assert.match(html, /<strong title="Argon">Argon<\/strong>/);
  assert.match(html, /90%/);
  assert.match(html, /33%/);
  assert.match(html, /15%/);
  assert.match(html, /7%/);
  assert.match(html, /argon:weekly/);
  assert.match(html, /gemini-argon-wtu-weekly/);
  assert.match(html, /argon:5h/);
  assert.match(html, /gemini-argon-foo-5h/);
});

test('official Carbon weekly aliases render Carbon and do not invent a 5h Carbon bar', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Source group',
        buckets: [
          { bucket_id: 'carbon:weekly', window: 'weekly', percentage: 64, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
          { bucket_id: 'gemini-carbon-wtu-weekly', window: 'weekly', percentage: 12, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
        ],
      }],
    }],
  });
  assert.match(html, /<strong title="Carbon">Carbon<\/strong>/);
  assert.match(html, /64%/);
  assert.match(html, /12%/);
  assert.equal((html.match(/class="desk-google-pool-quota-family__row"/g) || []).length, 2);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
});

test('without official Argon buckets, catalog Argon models must not invent Argon family numbers', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [{ name: 'gemini-4-argon', percentage: 55, reset_time: '2026-11-20T18:59:32Z' }],
    }],
  });
  assert.match(html, /<strong title="Claude">Claude<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.match(html, /其他模型额度/);
  assert.match(html, /gemini-4-argon/);
  assert.match(html, /55%/);
});

test('unofficial argon-weekly bucket is kept as unknown and is not an official Argon family', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Gemini 4 Argon',
        buckets: [
          { bucket_id: 'argon-weekly', window: 'weekly', percentage: 90, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
        ],
      }],
    }],
  });
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.match(html, /其他额度/);
  assert.match(html, /90%/);
  assert.match(html, /argon-weekly/);
});

test('unknown official-looking buckets stay visible and missing fraction or missing 5h is not forged', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Mixed source',
        description: 'These are not Gemini models; mentions Argon too',
        buckets: [
          { bucket_id: '3p-weekly', window: 'weekly', percentage: 40, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
          { bucket_id: 'family-daily', window: 'daily', percentage: 25, reset_time: '2026-11-21T00:00:00Z', display_name: 'Daily' },
          { bucket_id: 'family-odd', window: '', remaining_fraction: null, percentage: null, reset_time: '' },
        ],
      }],
    }],
  });
  assert.match(html, /<strong title="Claude">Claude<\/strong>/);
  assert.match(html, /40%/);
  assert.doesNotMatch(html, /<strong title="Gemini">Gemini<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  // Only weekly official Claude bucket: do not invent a 5h placeholder bar.
  const claudeBlock = html.slice(html.indexOf('title="Claude"'), html.indexOf('其他额度'));
  assert.doesNotMatch(claudeBlock, /3p-5h|claude:5h/);
  assert.equal((claudeBlock.match(/class="desk-google-pool-quota-family__row"/g) || []).length, 1);
  assert.match(html, /其他额度/);
  assert.match(html, /25%/);
  assert.doesNotMatch(html, /family-odd|未知窗口/);
  assert.doesNotMatch(html, /style="width:\s*100%"/);
  assert.doesNotMatch(html, /style="width:\s*0%"/);
});

test('stale and error statuses stay honest after family mapping', async () => {
  const stale = (await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'stale',
      quota_groups_updated_at: 1763610000,
      quota_groups_last_attempt_at: 1763613578,
      quota_groups: [claudeGroup({ buckets: [
        { bucket_id: '3p-weekly', window: 'weekly', percentage: 25, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
      ] })],
    }],
  })).html;
  assert.match(stale, /<strong title="Claude">Claude<\/strong>/);
  assert.match(stale, /25%/);
  assert.match(stale, /分组额度更新失败，仍显示上次缓存/);
  assert.doesNotMatch(stale, /style="width:\s*100%"/);
  const errorHtml = (await googleHtml({
    items: [{ id: 'e', enabled: true, quota_groups_status: 'error', quota_groups: [], models: [] }],
  })).html;
  assert.match(errorHtml, /分组额度获取失败/);
  assert.doesNotMatch(errorHtml, /<strong title="Argon">Argon<\/strong>/);
  assert.doesNotMatch(errorHtml, /style="width:\s*100%"/);
});

test('missing grouped quota with catalog models matches the no-family-card screenshot state', async () => {
  const reset = '2026-11-20T16:19:32Z';
  const models = [
    'gemini-3-pro-image-preview',
    'gemini-3.1-flash-image',
    'gemini-3-pro-image',
    'gemini-2.5-pro',
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-2.0-pro',
    'gemini-2.5-flash-image',
    'gemini-exp-image',
    'gemini-3-flash-image',
    'claude-sonnet-4-6',
    'claude-sonnet-4-5',
    'claude-haiku-4-5',
    'claude-opus-4-6',
    'claude-opus-4-5',
    'claude-sonnet-4',
    'gpt-oss-120b',
  ].map(name => ({ name, percentage: 100, reset_time: reset }));
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-screenshot',
      email: 'person-s@example.test',
      enabled: true,
      refreshable: true,
      success_count: 1,
      quota_groups_status: 'missing',
      quota_groups: [],
      models,
    }],
  });
  assert.match(html, /已启用 · 自动续期 · 成功 1/);
  assert.match(html, /分组额度尚未获取/);
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /模型汇总，非官方共享池/);
  assert.match(html, /10 个模型/);
  assert.match(html, /其他模型额度/);
  assert.match(html, /2小时20分/);
  assert.match(html, /desk-google-pool-quota-bar" style="width:\s*100%"/);
  const supplement = (html.match(/data-family="gemini-catalog"[\s\S]*?(?=<div class="desk-google-pool-quota-family"|$)/) || [''])[0];
  assert.equal((supplement.match(/class="desk-google-pool-quota-family__row"/g) || []).length, 1);
  assert.doesNotMatch(html, /本次分组额度未返回 Argon/);
  assert.doesNotMatch(html, /<strong title="Claude">Claude<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Gemini">Gemini<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Carbon">Carbon<\/strong>/);
  assert.doesNotMatch(html, /<strong title="其他额度">其他额度<\/strong>/);
  assert.doesNotMatch(html, /Five Hour Limit Remaining|Weekly Limit Remaining/);
});

function cssBlock(source, selector) {
  const needle = selector + ' {';
  const start = source.indexOf(needle);
  assert.ok(start >= 0, 'missing selector ' + selector);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, i);
    }
  }
  assert.fail('unclosed selector ' + selector);
}

function cssVar(block, name) {
  const match = block.match(new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*:\\s*([^;]+);'));
  return match ? match[1].replace(/\s+/g, ' ').trim() : '';
}

test('settings and canvas share light/dark and liquid/graphite selectors, not cinematic skins', () => {
  const preferences = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-preferences.js'), 'utf8');
  const state = fs.readFileSync(path.join(root, 'frontend/scripts/state.js'), 'utf8');
  const tokens = fs.readFileSync(path.join(root, 'frontend/styles/desktop-tokens.css'), 'utf8');
  const graphite = fs.readFileSync(path.join(root, 'frontend/styles/desktop-graphite.css'), 'utf8');
  const liquid = fs.readFileSync(path.join(root, 'frontend/styles/desktop-liquid.css'), 'utf8');
  assert.match(preferences, /SUPPORTED_THEMES = new Set\(\['light', 'dark'\]\)/);
  assert.match(preferences, /SUPPORTED_THEME_STYLES = new Set\(\['liquid', 'graphite'\]\)/);
  assert.match(preferences, /document\.body\?\.setAttribute\('data-theme', state\.theme\)/);
  assert.match(preferences, /document\.documentElement\.setAttribute\('data-theme', state\.theme\)/);
  assert.match(preferences, /state\.themeStyle === 'liquid'[\s\S]*removeAttribute\('data-desk-style'\)/);
  assert.match(preferences, /setAttribute\('data-desk-style', state\.themeStyle\)/);
  assert.match(state, /AVAILABLE_SKINS = \['skeuo-tech', 'cassette-light', 'garden', 'midnight', 'paper'\]/);
  for (const sheet of [css, tokens, graphite, liquid]) {
    assert.doesNotMatch(sheet, /\[data-skin=/);
  }
});

test('each workbench theme remaps the semantic tokens quota cards consume', () => {
  const tokens = fs.readFileSync(path.join(root, 'frontend/styles/desktop-tokens.css'), 'utf8');
  const graphite = fs.readFileSync(path.join(root, 'frontend/styles/desktop-graphite.css'), 'utf8');
  const light = cssBlock(tokens, 'body.desk-app');
  const dark = cssBlock(tokens, 'body.desk-app[data-theme="dark"]');
  const graphiteLight = cssBlock(graphite, 'body.desk-app[data-desk-style="graphite"]');
  const graphiteDark = cssBlock(graphite, 'body.desk-app[data-desk-style="graphite"][data-theme="dark"]');
  const graphiteShared = cssBlock(graphite, 'body.desk-app[data-desk-style="graphite"][data-theme]');

  assert.equal(cssVar(light, '--desk-status-live-dot'), 'var(--desk-status-success-dot)');
  assert.equal(cssVar(light, '--desk-status-success-dot'), '#207f55');
  assert.equal(cssVar(light, '--desk-status-warning-dot'), '#e46b0b');
  assert.equal(cssVar(light, '--desk-status-error-dot'), '#cd3b6a');
  assert.match(cssVar(light, '--desk-settings-account-background'), /rgba\(255, 255, 255, 0\.46\)/);
  assert.match(cssVar(light, '--desk-file-progress-background'), /rgba\(255, 255, 255, 0\.46\)/);

  assert.equal(cssVar(dark, '--desk-status-success-dot'), '#46b77b');
  assert.equal(cssVar(dark, '--desk-status-warning-dot'), '#ffad52');
  assert.equal(cssVar(dark, '--desk-status-error-dot'), '#e16088');
  assert.match(cssVar(dark, '--desk-settings-account-background'), /rgba\(28, 34, 36, 0\.58\)/);
  assert.match(cssVar(dark, '--desk-file-progress-background'), /linear-gradient/);
  assert.equal(cssVar(dark, '--desk-status-live-dot'), '');

  assert.equal(cssVar(graphiteShared, '--desk-status-live-dot'), 'var(--desk-graphite-accent)');
  assert.equal(cssVar(graphiteShared, '--desk-settings-account-background'), 'var(--desk-graphite-card)');
  assert.equal(cssVar(graphiteLight, '--desk-graphite-accent'), '#1f8f7c');
  assert.equal(cssVar(graphiteLight, '--desk-file-progress-background'), 'var(--desk-graphite-inset)');
  assert.equal(cssVar(graphiteLight, '--desk-graphite-card'), '#fafaf8');

  assert.equal(cssVar(graphiteDark, '--desk-graphite-accent'), '#5ec4b0');
  assert.equal(cssVar(graphiteDark, '--desk-graphite-card'), '#383838');
  assert.equal(cssVar(graphiteDark, '--desk-file-progress-background'), 'var(--desk-graphite-inset)');
  assert.equal(cssVar(graphiteDark, '--desk-graphite-inset'), '#2f2f2f');
});

test('multi-theme fixture covers all four workbench combinations with safe synthetic data', () => {
  const dir = path.join(root, 'tests/fixtures');
  const index = fs.readFileSync(path.join(dir, 'google-pool-quota-themes.html'), 'utf8');
  const combos = [
    ['light', 'liquid', 'google-pool-quota-theme-light-liquid.html'],
    ['dark', 'liquid', 'google-pool-quota-theme-dark-liquid.html'],
    ['light', 'graphite', 'google-pool-quota-theme-light-graphite.html'],
    ['dark', 'graphite', 'google-pool-quota-theme-dark-graphite.html'],
  ];
  for (const [theme, style, file] of combos) {
    assert.match(index, new RegExp(file.replace(/[.]/g, '\\.')));
    const html = fs.readFileSync(path.join(dir, file), 'utf8');
    assert.match(html, new RegExp(`<body[^>]*class="desk-app"[^>]*data-theme="${theme}"`));
    if (style === 'graphite') {
      assert.match(html, /data-desk-style="graphite"/);
      assert.match(html, /<html[^>]*data-desk-style="graphite"/);
    } else {
      assert.doesNotMatch(html, /data-desk-style=/);
    }
    assert.match(html, /<html[^>]*data-theme="/);
    const cssOrder = [
      'desktop-tokens.css',
      'desktop-liquid.css',
      'desktop-layout.css',
      'desktop-settings-auth.css',
      'desktop-graphite.css',
    ].map(name => html.indexOf(name));
    assert.ok(cssOrder.every(index => index >= 0), 'theme fixture missing a shared stylesheet in ' + file);
    assert.deepEqual(cssOrder, [...cssOrder].sort((a, b) => a - b));
    assert.match(html, /<strong title="Claude">Claude<\/strong>/);
    assert.match(html, /desk-google-pool-quota-bar is-warn"/);
    assert.match(html, /desk-google-pool-quota-bar is-low"/);
    assert.match(html, /分组额度尚未获取/);
    assert.match(html, /Gemini 额度（目录汇总）/);
    assert.match(html, /模型汇总，非官方共享池/);
    assert.match(html, /其他模型额度/);
    assert.match(html, /2 个模型/);
    assert.match(html, /40%–100%/);
    assert.match(html, /重置时间不一/);
    assert.match(html, /本次分组额度未返回 Argon/);
    assert.match(html, /<strong title="Argon">Argon<\/strong>/);
    assert.match(html, /argon:weekly/);
    assert.match(html, /person-[abcd]@example\.test/);
    assert.doesNotMatch(html, /@gmail\.com|ya[hr]oo|auth_key|access_token|refresh_token/i);
    assert.match(html, /class="desk-settings desk-settings--workbench is-open"/);
    assert.match(html, /<body[^>]*>\s*<section class="desk-settings desk-settings--workbench is-open"/);
    assert.match(html, /desktop-settings-auth\.css/);
  }
  const main = fs.readFileSync(path.join(dir, 'google-pool-quota-display.html'), 'utf8');
  assert.match(main, /class="desk-settings desk-settings--workbench is-open"/);
});

test('quota text tokens follow the settings workbench remap, not body default ink in dark liquid', () => {
  const liquid = fs.readFileSync(path.join(root, 'frontend/styles/desktop-liquid.css'), 'utf8');
  const auth = fs.readFileSync(path.join(root, 'frontend/styles/desktop-settings-auth.css'), 'utf8');
  const tokens = fs.readFileSync(path.join(root, 'frontend/styles/desktop-tokens.css'), 'utf8');
  const body = cssBlock(liquid, 'body.desk-app');
  const dark = cssBlock(tokens, 'body.desk-app[data-theme="dark"]');
  assert.equal(cssVar(body, '--desk-ink'), '#16202b');
  assert.equal(cssVar(body, '--desk-muted'), '#637182');
  // Dark liquid changes the page background but does not retarget body --desk-ink.
  assert.equal(cssVar(dark, '--desk-ink'), '');
  assert.equal(cssVar(dark, '--desk-muted'), '');
  assert.equal(cssVar(dark, '--desk-settings-ink'), '#edf2f3');
  assert.equal(cssVar(dark, '--desk-settings-muted-ink'), 'rgba(190, 199, 201, 0.68)');
  // Production settings ancestor remaps --desk-ink; .desk-settings-form alone does not.
  assert.match(
    auth,
    /body\.desk-app\[data-theme\] :is\(\s*\.desk-settings,\s*\.desk-settings-info-tip\s*\)\s*\{[^}]*--desk-ink:\s*var\(--desk-settings-ink\)/,
  );
  assert.match(auth, /--desk-muted:\s*var\(--desk-settings-muted-ink\)/);
  assert.doesNotMatch(auth, /\.desk-settings-form[^{]*\{[^}]*--desk-ink:/);
  assert.match(liquid, /body\.desk-app\[data-theme="dark"\]\s*\{[^}]*--desk-bg:\s*#171b22/s);
  // Quota cards keep using theme text tokens, not hardcoded ink.
  assert.match(css, /\.desk-app \.desk-google-pool-account__head strong\s*\{[^}]*color:\s*var\(--desk-ink\)/);
  assert.match(css, /\.desk-app \.desk-google-pool-note\s*\{[^}]*color:\s*var\(--desk-muted\)/);
  assert.match(css, /\.desk-app \.desk-google-pool-quota-label\s*\{[^}]*color:\s*var\(--desk-muted\)/);
  assert.match(css, /\.desk-app \.desk-google-pool-quota-card b\s*\{[^}]*color:\s*var\(--desk-ink\)/);
  assert.match(css, /\.desk-app \.desk-google-pool-quota-reset\s*\{[^}]*color:\s*var\(--desk-muted\)/);
});


test('identical catalog Gemini fractions collapse to one summary card, not official Gemini or Argon', async () => {
  const reset = '2026-11-20T16:19:32Z';
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 100, reset_time: reset },
        { name: 'gemini-2.5-pro', percentage: 100, reset_time: reset },
        { name: 'gemini-4-hydrogen-sonar', percentage: 100, reset_time: reset },
      ],
    }],
  });
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /模型汇总，非官方共享池/);
  assert.match(html, /3 个模型/);
  assert.match(html, /100%/);
  assert.match(html, /2小时20分/);
  assert.match(html, /gemini-4-hydrogen-sonar/);
  const summary = (html.match(/data-family="gemini-catalog"[\s\S]*?(?=<div class="desk-google-pool-quota-family"|$)/) || [''])[0];
  assert.equal((summary.match(/class="desk-google-pool-quota-family__row"/g) || []).length, 1);
  assert.match(summary, /desk-google-pool-quota-bar" style="width:\s*100%"/);
  assert.doesNotMatch(html, /<strong title="Gemini">Gemini<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.match(html, /本次分组额度未返回 Argon/);
});

test('different catalog Gemini values show an honest range without a single official bar', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 40, reset_time: '2026-11-20T16:19:32Z' },
        { name: 'gemini-2.5-pro', percentage: 100, reset_time: '2026-11-21T13:59:32Z' },
      ],
    }],
  });
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /模型汇总，非官方共享池/);
  assert.match(html, /2 个模型/);
  assert.match(html, /40%–100%/);
  assert.match(html, /重置时间不一/);
  const summary = (html.match(/data-family="gemini-catalog"[\s\S]*?(?=<div class="desk-google-pool-quota-family"|$)/) || [''])[0];
  assert.equal((summary.match(/class="desk-google-pool-quota-family__row"/g) || []).length, 1);
  assert.doesNotMatch(summary, /desk-google-pool-quota-bar/);
  assert.doesNotMatch(html, /70%/); // no invented average
});

test('catalog Gemini summary keeps missing values unknown and does not treat them as zero', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 80, reset_time: '2026-11-20T16:19:32Z' },
        { name: 'gemini-2.5-pro', percentage: null, reset_time: '' },
      ],
    }],
  });
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /80%–80%，部分未知|80%，部分未知/);
  assert.match(html, /未知|重置时间不一/);
  const summary = (html.match(/data-family="gemini-catalog"[\s\S]*?(?=<div class="desk-google-pool-quota-family"|$)/) || [''])[0];
  assert.doesNotMatch(summary, /desk-google-pool-quota-bar/);
  assert.doesNotMatch(summary, />0%</);
});

test('Argon and Carbon catalog models are not swallowed into the Gemini summary', async () => {
  const reset = '2026-11-20T16:19:32Z';
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [
        { name: 'gemini-3.1-flash-image', percentage: 100, reset_time: reset },
        { name: 'gemini-4-argon', percentage: 55, reset_time: reset },
        { name: 'gemini-carbon-preview', percentage: 12, reset_time: reset },
      ],
    }],
  });
  assert.match(html, /Gemini 额度（目录汇总）/);
  assert.match(html, /1 个模型/);
  const summary = (html.match(/data-family="gemini-catalog"[\s\S]*?(?=<div class="desk-google-pool-quota-family"|$)/) || [''])[0];
  assert.doesNotMatch(summary, /gemini-4-argon|55%/);
  assert.doesNotMatch(summary, /gemini-carbon-preview|12%/);
  assert.match(html, /其他模型额度/);
  assert.match(html, /gemini-4-argon/);
  assert.match(html, /gemini-carbon-preview/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.doesNotMatch(html, /<strong title="Carbon">Carbon<\/strong>/);
});

test('an official summary without Argon buckets says so and never forges Argon numbers', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [{ name: 'gemini-4-hydrogen-sonar', percentage: 100, reset_time: '2026-11-20T16:19:32Z' }],
    }],
  });
  assert.match(html, /本次分组额度未返回 Argon/);
  assert.doesNotMatch(html, /<strong title="Argon">Argon<\/strong>/);
  assert.match(html, /gemini-4-hydrogen-sonar/);
  assert.doesNotMatch(html, /Gemini 4 Argon/);
  const missing = (await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'missing',
      quota_groups: [],
      models: [{ name: 'gemini-3-flash', percentage: 100, reset_time: '2026-11-20T16:19:32Z' }],
    }],
  })).html;
  assert.doesNotMatch(missing, /本次分组额度未返回 Argon/);
});

function visibleQuotaLabels(html) {
  return [...html.matchAll(/class="desk-google-pool-quota-label"[^>]*>([^<]*)</g)].map(match => match[1]);
}

test('real 0% exhausted leftover and official buckets stay visible', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup({ buckets: [
        { bucket_id: '3p-weekly', window: 'weekly', percentage: 0, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
        { bucket_id: '3p-5h', window: '5h', percentage: 0, remaining_fraction: 0, display_name: 'Five Hour Limit Remaining' },
      ] })],
      models: [{ name: 'gemini-4-argon', percentage: 0, reset_time: '2026-11-20T18:56:32Z' }],
    }],
  });
  assert.match(html, /<strong[^>]*>Claude<\/strong>/);
  assert.equal((html.match(/>0%</g) || []).length, 3);
  assert.match(html, /style="width:\s*0%"/);
  assert.match(html, /其他模型额度/);
  assert.match(html, /gemini-4-argon/);
  assert.match(html, /本次分组额度未返回 Argon/);
});

test('unknown or disabled leftovers without a valid fraction are hidden and an empty leftover heading is omitted', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup()],
      models: [
        { name: 'gemini-4-carbon-disabled', percentage: null, reset_time: '' },
        { name: 'gemini-4-argon-disabled' },
        { name: 'unknown-model', percentage: Number.NaN },
      ],
    }],
  });
  assert.doesNotMatch(html, /其他模型额度/);
  assert.doesNotMatch(html, /gemini-4-carbon-disabled/);
  assert.doesNotMatch(html, /gemini-4-argon-disabled/);
  assert.doesNotMatch(html, /unknown-model/);
  assert.match(html, /<strong[^>]*>Claude<\/strong>/);
  assert.match(html, /本次分组额度未返回 Argon/);
});

test('error and stale diagnostics stay when leftover unknown rows are filtered out', async () => {
  const stale = (await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'stale',
      quota_groups: [claudeGroup()],
      models: [{ name: 'gemini-4-carbon-disabled', percentage: null }],
    }],
  })).html;
  assert.match(stale, /分组额度更新失败，仍显示上次缓存/);
  assert.doesNotMatch(stale, /其他模型额度|gemini-4-carbon-disabled/);
  const failed = (await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'error',
      quota_groups: [],
      models: [{ name: 'gemini-4-carbon-disabled' }],
    }],
  })).html;
  assert.match(failed, /分组额度获取失败/);
  assert.doesNotMatch(failed, /其他模型额度|gemini-4-carbon-disabled/);
});

test('official buckets with a valid fraction still render when reset time is unknown', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [{
        display_name: 'Claude and GPT models',
        buckets: [
          { bucket_id: '3p-weekly', window: 'weekly', percentage: 42, remaining_fraction: 0.42, reset_time: '', display_name: 'Weekly Limit Remaining' },
        ],
      }],
    }],
  });
  assert.match(html, /42%/);
  assert.match(html, /style="width:\s*42%"/);
  assert.doesNotMatch(html, /desk-google-pool-quota-reset/);
});

test('Claude, Gemini, and Argon family cards share one compact layout container with only real windows', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [
        claudeGroup(),
        {
          display_name: 'Gemini Models',
          buckets: [
            { bucket_id: 'gemini-weekly', window: 'weekly', percentage: 80, reset_time: '2026-11-27T13:59:32Z', display_name: 'Weekly Limit Remaining' },
            { bucket_id: 'gemini-5h', window: '5h', percentage: 60, reset_time: '2026-11-20T18:59:32Z', display_name: 'Five Hour Limit Remaining' },
          ],
        },
        {
          display_name: 'Gemini 4 Argon',
          buckets: [
            { bucket_id: 'gemini-argon-wtu-weekly', window: 'weekly', percentage: 90, reset_time: '2026-11-27T13:59:32Z', display_name: 'Gemini 4 Argon Weekly Limit' },
          ],
        },
      ],
    }],
  });
  assert.equal((html.match(/class="desk-google-pool-quota-families"/g) || []).length, 1);
  const container = (html.match(/<div class="desk-google-pool-quota-families">[\s\S]*?<\/div>\s*(?:<div class="desk-google-pool-quota-group"|$)/) || [html])[0];
  assert.match(container, /data-family="claude"/);
  assert.match(container, /data-family="gemini"/);
  assert.match(container, /data-family="argon"/);
  assert.equal((container.match(/class="desk-google-pool-quota-family"/g) || []).length, 3);
  const claude = (html.match(/data-family="claude"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  const gemini = (html.match(/data-family="gemini"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  const argon = (html.match(/data-family="argon"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  assert.equal((claude.match(/desk-google-pool-quota-family__row/g) || []).length, 2);
  assert.equal((gemini.match(/desk-google-pool-quota-family__row/g) || []).length, 2);
  assert.equal((argon.match(/desk-google-pool-quota-family__row/g) || []).length, 1);
  assert.doesNotMatch(html, /本次分组额度未返回 Argon/);
  assert.doesNotMatch(html, /Gemini 额度（目录汇总）/);
});

test('Chinese locale maps recognized official 5h and weekly labels and leaves unknown official copy alone', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [
        claudeGroup(),
        {
          display_name: 'Gemini 4 Argon',
          buckets: [
            { bucket_id: 'gemini-argon-wtu-weekly', window: 'weekly', percentage: 90, display_name: 'Gemini 4 Argon Weekly Limit' },
          ],
        },
        {
          display_name: 'Custom Family',
          buckets: [
            { bucket_id: 'custom-burst', window: 'daily', percentage: 40, display_name: 'Five Hour Limit Remaining' },
            { bucket_id: 'custom-named', window: '', percentage: 15, display_name: 'Special Project Allowance' },
          ],
        },
      ],
    }],
  });
  const labels = visibleQuotaLabels(html);
  assert.deepEqual(labels.filter(label => label === '5 小时额度' || label === '周额度').sort(), ['5 小时额度', '周额度', '周额度']);
  assert.equal(labels.filter(label => label === '5 小时额度').length, 1);
  assert.equal(labels.filter(label => label === '周额度').length, 2);
  assert.ok(labels.includes('Five Hour Limit Remaining'));
  assert.ok(labels.includes('Special Project Allowance'));
  assert.doesNotMatch(html, /class="desk-google-pool-quota-label">Five Hour Limit Remaining<\/span>[\s\S]*3p-5h|class="desk-google-pool-quota-label">Weekly Limit Remaining/);
  const officialClaude = (html.match(/data-family="claude"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  assert.doesNotMatch(officialClaude, /class="desk-google-pool-quota-label">Five Hour Limit Remaining/);
  assert.doesNotMatch(officialClaude, /class="desk-google-pool-quota-label">Weekly Limit Remaining/);
  assert.match(officialClaude, /5 小时额度/);
  assert.match(officialClaude, /周额度/);
});

test('English locale keeps compact English window labels via project i18n', async () => {
  const { html } = await googleHtml({
    language: 'en',
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [
        claudeGroup(),
        {
          display_name: 'Gemini 4 Argon',
          buckets: [
            { bucket_id: 'gemini-argon-wtu-weekly', window: 'weekly', percentage: 90, display_name: 'Gemini 4 Argon Weekly Limit' },
          ],
        },
      ],
    }],
  });
  const labels = visibleQuotaLabels(html);
  assert.deepEqual(labels.sort(), ['5-hour quota', 'Weekly quota', 'Weekly quota']);
  assert.doesNotMatch(html, /class="desk-google-pool-quota-label">5 小时额度/);
  assert.doesNotMatch(html, /class="desk-google-pool-quota-label">周额度/);
  const i18n = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-i18n.js'), 'utf8');
  assert.match(i18n, /'5 小时额度':\s*'5-hour quota'/);
  assert.match(i18n, /'周额度':\s*'Weekly quota'/);
});

test('compact family layout css auto-fits, wraps on narrow screens, and allows long titles to wrap', () => {
  const families = cssBlock(css, '.desk-app .desk-google-pool-quota-families');
  assert.match(families, /display:\s*flex/);
  assert.match(families, /flex-wrap:\s*wrap/);
  assert.doesNotMatch(families, /overflow-x:\s*auto/);
  assert.doesNotMatch(families, /grid-template-columns:\s*repeat\(2,/);
  const family = cssBlock(css, '.desk-app .desk-google-pool-quota-family');
  assert.match(family, /max-width:/);
  assert.match(family, /min-width:\s*min\(100%/);
  const title = cssBlock(css, '.desk-app .desk-google-pool-quota-family > strong');
  assert.match(title, /overflow-wrap:\s*anywhere/);
  assert.match(title, /white-space:\s*normal/);
  const label = cssBlock(css, '.desk-app .desk-google-pool-quota-family .desk-google-pool-quota-label');
  assert.match(label, /white-space:\s*normal/);
  assert.match(label, /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(css, /@media[^{]+\{[^}]*\.desk-app \.desk-google-pool-quota-families\s*\{[^}]*overflow-x:\s*auto/);
});

test('countdown sits in the window header so adjacent rows with and without reset stay aligned', async () => {
  const { html } = await googleHtml({
    items: [{
      id: 'fixture-id',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [
        claudeGroup({ buckets: [
          { bucket_id: '3p-5h', window: '5h', percentage: 100, reset_time: '', display_name: 'Five Hour Limit Remaining' },
          { bucket_id: '3p-weekly', window: 'weekly', percentage: 100, reset_time: '', display_name: 'Weekly Limit Remaining' },
        ] }),
        {
          display_name: 'Gemini Models',
          buckets: [
            { bucket_id: 'gemini-5h', window: '5h', percentage: 80, reset_time: '2026-11-20T17:42:32Z', display_name: 'Five Hour Limit Remaining' },
            { bucket_id: 'gemini-weekly', window: 'weekly', percentage: 64, reset_time: '2026-11-26T21:55:32Z', display_name: 'Weekly Limit Remaining' },
          ],
        },
        {
          display_name: 'Gemini 4 Argon',
          buckets: [
            { bucket_id: 'gemini-argon-wtu-weekly', window: 'weekly', percentage: 90, reset_time: '2026-11-28T12:42:32Z', display_name: 'Gemini 4 Argon Weekly Limit' },
          ],
        },
      ],
    }],
  });
  const rows = html.match(/<div class="desk-google-pool-quota-family__row"[\s\S]*?<\/div>\s*<\/div>/g) || [];
  assert.equal((html.match(/data-family="claude"/g) || []).length, 1);
  assert.equal((html.match(/data-family="gemini"/g) || []).length, 1);
  assert.equal((html.match(/data-family="argon"/g) || []).length, 1);
  const claude = (html.match(/data-family="claude"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  const gemini = (html.match(/data-family="gemini"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  const argon = (html.match(/data-family="argon"[\s\S]*?(?=data-family=|$)/) || [''])[0];
  assert.equal((claude.match(/desk-google-pool-quota-family__row/g) || []).length, 2);
  assert.equal((gemini.match(/desk-google-pool-quota-family__row/g) || []).length, 2);
  assert.equal((argon.match(/desk-google-pool-quota-family__row/g) || []).length, 1);
  assert.doesNotMatch(claude, /desk-google-pool-quota-reset/);
  assert.match(gemini, /3小时43分/);
  assert.match(gemini, /6天7小时56分/);
  assert.match(argon, /7天22小时43分/);
  function quotaRows(block) {
    return block.match(/<div class="desk-google-pool-quota-family__row"[^>]*>[\s\S]*?<div class="desk-google-pool-quota-track">[\s\S]*?<\/div>\s*<\/div>/g) || [];
  }
  function assertResetStaysInHeader(block) {
    const rows = quotaRows(block);
    assert.ok(rows.length, 'expected quota rows');
    for (const row of rows) {
      const afterTrack = row.split(/class="desk-google-pool-quota-track"/)[1] || '';
      assert.doesNotMatch(afterTrack, /desk-google-pool-quota-reset/);
      if (row.includes('desk-google-pool-quota-reset')) {
        assert.match(row, /desk-google-pool-quota-card__top[\s\S]*?desk-google-pool-quota-reset[\s\S]*?desk-google-pool-quota-track/);
      }
      assert.match(row, /desk-google-pool-quota-card__top/);
      assert.match(row, /<b>\d+%<\/b>/);
    }
    return rows;
  }
  assert.equal(assertResetStaysInHeader(claude).length, 2);
  assert.equal(assertResetStaysInHeader(gemini).length, 2);
  assert.equal(assertResetStaysInHeader(argon).length, 1);
  const long = (await googleHtml({
    items: [{
      id: 'fixture-long',
      enabled: true,
      quota_groups_status: 'ok',
      quota_groups: [claudeGroup({ buckets: [
        { bucket_id: '3p-weekly', window: 'weekly', percentage: 0, reset_time: '2027-02-28T13:59:32Z', display_name: 'Weekly Limit Remaining' },
      ] })],
    }],
  })).html;
  assert.match(long, /desk-google-pool-quota-card__top[\s\S]*?desk-google-pool-quota-reset[\s\S]*?100天/);
  assert.match(long, />0%</);
  assertResetStaysInHeader(long);
});

test('quota css keeps countdown in the header and does not use fixed family height to align bars', () => {
  const family = cssBlock(css, '.desk-app .desk-google-pool-quota-family');
  const row = cssBlock(css, '.desk-app .desk-google-pool-quota-family__row');
  const top = cssBlock(css, '.desk-app .desk-google-pool-quota-card__top');
  const meta = cssBlock(css, '.desk-app .desk-google-pool-quota-meta');
  const reset = cssBlock(css, '.desk-app .desk-google-pool-quota-reset');
  const percent = cssBlock(css, '.desk-app .desk-google-pool-quota-family b');
  assert.doesNotMatch(family, /(?:min-height|height)\s*:\s*\d/);
  assert.doesNotMatch(row, /(?:min-height|height)\s*:\s*\d/);
  assert.match(top, /display:\s*flex/);
  assert.match(meta, /display:\s*flex/);
  assert.match(meta, /flex-wrap:\s*wrap/);
  assert.match(meta, /min-width:\s*0/);
  assert.doesNotMatch(reset, /position:\s*absolute/);
  assert.doesNotMatch(top, /position:\s*absolute/);
  assert.match(percent, /flex:\s*none/);
});
