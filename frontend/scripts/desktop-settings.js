(function () {
  const els = {};
  let lastDiagnostics = null;
  let lastPromptConfig = null;
  let lastChatgptPoolAccounts = null;
  let lastSystemSettings = null;
  let lastGptModelCatalog = null;
  let activeTab = 'status';
  let settingsInfoTipOpen = false;
  let chatgptPoolActivity = null;
  let chatgptPoolRefreshBusy = false;
  let chatgptPoolOAuthActivity = null;
  let chatgptPoolOAuthSessionId = '';
  let chatgptPoolOAuthAuthorizeUrl = '';
  let managedCodexOAuthActivity = null;
  let managedCodexOAuthSessionId = '';
  let managedCodexOAuthAuthorizeUrl = '';
  let managedCodexOAuthPollTimer = null;
  let managedCodexOAuthPollDeadline = 0;
  const MANAGED_CODEX_OAUTH_POLL_INTERVAL_MS = 1500;
  const MANAGED_CODEX_OAUTH_POLL_TIMEOUT_MS = 15 * 60 * 1000;
  const SETTINGS_TAB_HELP = {
    system: {
      title: '系统配置',
      subtitle: '本地监听与公网访问',
      summary: '控制后端绑定地址、端口和公网模式；公网模式必须配置访问密码。',
      sections: [
        ['配置方式', [
          '默认只监听 127.0.0.1，适合本机桌面使用。',
          '开启公网模式后才允许监听 0.0.0.0 或指定网卡地址。',
          '公网模式必须设置访问密码；保存后重启服务，新的监听地址才会生效。'
        ]],
        ['对应模块', [
          'server.py 启动绑定、桌面端设置中心、Mini App 登录鉴权。',
          '访问密码也保护系统诊断、历史、图片读取和生成接口。'
        ]],
        ['注意事项', [
          '公网模式只解决监听地址，不替代 HTTPS、反向代理、系统防火墙或 Telegram 域名配置。',
          '如果只是本机使用，不要开启公网模式。'
        ]]
      ]
    },
    telegram: {
      title: 'Telegram 配置',
      subtitle: '访问控制与结果投递',
      summary: '控制 Mini App 访问密码、Telegram Bot 投递目标、允许用户和代理。',
      sections: [
        ['配置方式', [
          '访问密码为空表示保持原值，填写新密码才会覆盖；已配置时可用字段右侧的清除按钮删除。',
          'Bot Token 来自 Telegram BotFather，Chat ID 是接收图片的个人、群组或频道目标。',
          '允许用户 ID 可一行一个，也可用逗号分隔；留空时按后端默认访问策略处理。'
        ]],
        ['对应模块', [
          'Mini App 登录校验、Telegram initData 校验、生成结果发送到 Telegram。',
          '图片发送保持 sendDocument，避免 Telegram 压缩原图。'
        ]],
        ['注意事项', [
          '清除 Bot Token 后不会再发送到 Telegram，即使底部开关处于开启状态也无法投递。',
          '代理只影响 Telegram 请求，不会改变 GPT、Google 或第三方 API 的访问路径。'
        ]]
      ]
    },
    provider: {
      title: 'Provider 配置',
      subtitle: '本地 Codex 与托管 OAuth',
      summary: '配置 GPT 主模型、推理强度、托管 OAuth 和本地请求超时策略。',
      sections: [
        ['配置方式', [
          'GPT 主模型和推理强度会影响本地 Codex 生成请求。',
          'Codex 授权路径和 API endpoint 收在托管 OAuth 卡片的运行配置中，避免 Provider 连接卡重复。',
          '本地超时到达上限后，会按现有策略切到账号池托底。'
        ]],
        ['对应模块', [
          '本地 Codex 生成、Codex 编辑、托管 Codex OAuth 授权、Codex 到账号池 fallback。'
        ]],
        ['注意事项', [
          '不要同时保留多个旧授权路径误导排查；托管 OAuth 已配置时应优先吃托管 auth。',
          '清空托管 OAuth 是独立授权操作，不等同于清除账号池账号。'
        ]]
      ]
    },
    'third-party': {
      title: '第三方 API',
      subtitle: 'Google / Gemini 与 OpenAI Images 兼容端点',
      summary: '管理 nano banana 和 Gpt-image-2 兼容接口，供 Google 生成和第三方线路使用。',
      sections: [
        ['配置方式', [
          'nano banana API Key / URL 用于 Google 或 Gemini 图像生成兼容请求。',
          'Gpt-image-2 API Key / URL / 路径用于模型节点选择“第三方 API”线路时的图像生成或编辑。',
          '密钥输入框为空表示不修改旧值，右侧清除按钮会立即删除已保存密钥。'
        ]],
        ['对应模块', [
          'Google 生成、Google 编辑、第三方 API 生成、第三方 API 编辑。',
          '不会参与默认 GPT 本地 Codex 到账号池的 fallback 链。'
        ]],
        ['注意事项', [
          '不同服务商的安全策略不同，PROHIBITED_CONTENT 一类错误通常来自上游内容审核。',
          '修改接口路径或模型后建议先跑一次小图测试，确认响应结构仍兼容。'
        ]]
      ]
    },
    'chatgpt-pool': {
      title: '账号池',
      subtitle: 'ChatGPT 账号托底与并发池',
      summary: '管理账号池 Sidecar 连接、授权账号、刷新 AT 和 Codex 失败后的托底生成。',
      sections: [
        ['配置方式', [
          '启用账号池后，本地 Codex 失败或超时时可以切到账号池 API。',
          'Base URL 指向本机 Sidecar；Auth Key 用于保护 Sidecar 接口。',
          '账号可通过 OAuth 登录、粘贴 Auth JSON 或导入本机 Auth 添加。'
        ]],
        ['对应模块', [
          '账号池 API 生成、账号池编辑、Codex fallback、账号状态刷新和限流恢复。',
          '账号列表中的刷新、启用、禁用、删除只影响账号池，不影响托管 Codex OAuth。'
        ]],
        ['注意事项', [
          '清除 Auth Key 后如果 Sidecar 仍要求密钥，前端请求会失败。',
          '限流或异常账号应先禁用或刷新，避免 fallback 命中不可用账号。'
        ]]
      ]
    },
    prompt: {
      title: '润色配置',
      subtitle: '提示词润色 Skill',
      summary: '配置提示词助手使用的 Provider、Skill、模型、推理强度和默认回填内容。',
      sections: [
        ['配置方式', [
          '切换 Provider 后会刷新可用模型列表；保存后影响提示词抽屉的润色请求。',
          '默认回填决定润色结果进入输入框时使用完整提示词还是精简投喂版。',
          '推理强度越高通常更慢，适合复杂提示词改写。'
        ]],
        ['对应模块', [
          '桌面提示词助手抽屉、候选提示词生成、提示词回填。',
          '不直接改变图像生成线路，只改变投喂给生成模型的文本质量。'
        ]],
        ['注意事项', [
          '如果模型列表为空，先检查对应 Provider 的授权和网络状态。',
          '润色模型成本和速度独立于最终图像生成模型。'
        ]]
      ]
    },
    paths: {
      title: '路径配置',
      subtitle: '归档、源图与任务数据库',
      summary: '配置图片归档目录、源图目录和任务数据库路径。',
      sections: [
        ['配置方式', [
          '支持相对项目路径，例如 data/archive；也兼容已有绝对路径。',
          'Image Archive 保存生成结果和 prompt sidecar 文件；Source Image 保存上传或参考源图。',
          'Tasks DB 保存任务记录、生成 runs 和事件日志。'
        ]],
        ['对应模块', [
          '最近记录面板、生成历史、任务状态、图片原图链接和归档读取。',
          '后端生成流程会依赖这些路径写入和查询结果。'
        ]],
        ['注意事项', [
          '改路径前确认目录可写，否则生成成功也可能无法归档或回显。',
          'Tasks DB 路径错误会影响最近记录、日志查询和前端状态详情。'
        ]]
      ]
    }
  };

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function collectElements() {
    [
      'deskSettingsPanel',
      'deskSettingsCloseBtn',
      'deskSettingsRefreshBtn',
      'deskSettingsInfoBtn',
      'deskSettingsInfoTip',
      'deskSettingsInfoTipTitle',
      'deskSettingsInfoTipSubtitle',
      'deskSettingsInfoTipSummary',
      'deskSettingsInfoTipContent',
      'deskSettingsInfoTipClose',
      'deskSettingsTabs',
      'deskSettingsSummary',
      'deskSettingsBody'
    ].forEach(id => {
      els[id] = $(id);
    });
  }

  function valueText(value, fallback = '未设置') {
    const text = String(value ?? '').trim();
    return text || fallback;
  }

  function boolLabel(value) {
    return value ? '已配置' : '未配置';
  }

  function statusClass(ok) {
    return ok ? 'is-ok' : 'is-warn';
  }

  function chatgptPoolPlanLabel(value) {
    const key = String(value || '').trim().toLowerCase();
    if (!key || key === 'unknown') return '套餐未知';
    if (key === 'free') return 'Free';
    if (key.includes('plus')) return 'Plus';
    if (key.includes('team') || key.includes('business')) return 'Team';
    if (key.includes('pro')) return 'Pro';
    if (key.includes('go')) return 'Go';
    return valueText(value, '套餐未知');
  }

  function chatgptPoolTimeLabel(value, prefix) {
    const text = String(value || '').trim();
    if (!text) return '';
    const date = new Date(text);
    const label = Number.isNaN(date.getTime())
      ? text
      : date.toLocaleString('zh-CN', { hour12: false });
    return `${prefix}${label}`;
  }

  function renderKv(label, value, options = {}) {
    const raw = options.boolean ? boolLabel(Boolean(value)) : valueText(value, options.fallback || '未设置');
    return `
      <div class="desk-settings-kv">
        <span>${escapeHtml(label)}</span>
        <strong title="${escapeHtml(raw)}">${escapeHtml(raw)}</strong>
      </div>
    `;
  }

  function renderPath(label, data) {
    if (!data || typeof data !== 'object') {
      return renderKv(label, '未设置');
    }
    const path = valueText(data.path, '未设置');
    const ok = Boolean(data.exists || data.parent_exists);
    return `
      <div class="desk-settings-path ${statusClass(ok)}">
        <div>
          <span>${escapeHtml(label)}</span>
          <strong title="${escapeHtml(path)}">${escapeHtml(path)}</strong>
        </div>
        <em>${data.exists ? '存在' : (data.parent_exists ? '父目录存在' : '缺失')}</em>
      </div>
    `;
  }

  function renderCard(title, rows, ok) {
    return `
      <section class="desk-settings-card ${statusClass(ok)}">
        <header>
          <span class="desk-settings-dot" aria-hidden="true"></span>
          <h3>${escapeHtml(title)}</h3>
        </header>
        <div class="desk-settings-card__body">
          ${rows.join('')}
        </div>
      </section>
    `;
  }

  function optionHtml(value, label, selectedValue) {
    const selected = String(value || '') === String(selectedValue || '') ? ' selected' : '';
    return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label || value)}</option>`;
  }

  function setting(path, fallback = '') {
    const root = lastSystemSettings?.settings || {};
    return String(path || '').split('.').reduce((value, key) => (
      value && typeof value === 'object' ? value[key] : undefined
    ), root) ?? fallback;
  }

  function renderInput(label, field, value, options = {}) {
    const type = options.type || 'text';
    const attrs = [
      `class="desk-input"`,
      `type="${escapeHtml(type)}"`,
      `data-system-setting-field="${escapeHtml(field)}"`,
      options.placeholder ? `placeholder="${escapeHtml(options.placeholder)}"` : '',
      options.min ? `min="${escapeHtml(options.min)}"` : '',
      options.max ? `max="${escapeHtml(options.max)}"` : '',
      options.step ? `step="${escapeHtml(options.step)}"` : '',
      type === 'password' ? 'autocomplete="new-password"' : ''
    ].filter(Boolean).join(' ');
    return `
      <label>
        <span>${escapeHtml(label)}</span>
        <input ${attrs} value="${type === 'password' ? '' : escapeHtml(value ?? '')}">
      </label>
    `;
  }

  function renderSecretInput(label, field, configured, options = {}) {
    const placeholder = options.placeholder || (configured ? '留空则不修改' : '粘贴新的密钥或密码');
    return `
      <div class="desk-settings-secret-field">
        <div class="desk-settings-secret-field__label">
          <span>${escapeHtml(label)}</span>
          ${configured ? `
            <button type="button" class="desk-settings-secret-clear" data-system-secret-clear-field="${escapeHtml(field)}" data-system-secret-clear-label="${escapeHtml(label)}" title="清除已保存的${escapeHtml(label)}">
              清除
            </button>
          ` : ''}
        </div>
        <input class="desk-input" type="password" data-system-setting-field="${escapeHtml(field)}" placeholder="${escapeHtml(placeholder)}" value="" autocomplete="new-password">
      </div>
    `;
  }

  function renderCheckbox(label, field, checked) {
    return `
      <label>
        <span>${escapeHtml(label)}</span>
        <input type="checkbox" data-system-setting-field="${escapeHtml(field)}"${checked ? ' checked' : ''}>
      </label>
    `;
  }

  function renderTextarea(label, field, value, placeholder = '') {
    return `
      <label class="desk-settings-form__wide">
        <span>${escapeHtml(label)}</span>
        <textarea class="desk-settings-textarea" data-system-setting-field="${escapeHtml(field)}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value ?? '')}</textarea>
      </label>
    `;
  }

  function renderSystemSaveButton(scope, label = '保存配置') {
    return `
      <div class="desk-settings-form__actions">
        <button type="button" class="is-primary" data-system-settings-save="${escapeHtml(scope)}">${escapeHtml(label)}</button>
      </div>
    `;
  }

  function renderTelegramSettings() {
    const telegram = setting('telegram', {});
    const auth = setting('auth', {});
    const allowedUsers = Array.isArray(telegram.allowed_user_ids)
      ? telegram.allowed_user_ids.join('\n')
      : (telegram.allowed_user_ids || '');
    return renderCard('Telegram 与访问', [
      `<div class="desk-settings-form" data-system-settings-card="telegram">
        ${renderSecretInput('访问密码', 'miniapp_access_password', auth.miniapp_access_password_configured, {
          placeholder: auth.miniapp_access_password_configured ? '留空则不修改' : '设置 mini app 访问密码'
        })}
        ${renderSecretInput('Bot Token', 'telegram.bot_token', telegram.bot_token_configured, {
          placeholder: telegram.bot_token_configured ? '留空则不修改' : '粘贴 Telegram Bot Token'
        })}
        ${renderInput('Chat ID', 'telegram.chat_id', telegram.chat_id || '')}
        ${renderTextarea('允许用户 ID', 'telegram.allowed_user_ids', allowedUsers, '一行一个，或用逗号分隔')}
        ${renderInput('Telegram 代理', 'telegram.proxy_url', telegram.proxy_url || '', { placeholder: 'http://127.0.0.1:7897' })}
        <p class="desk-settings-form__hint">图片投递仍固定走 sendDocument，避免 Telegram 压缩。</p>
        ${renderSystemSaveButton('telegram', '保存 Telegram 配置')}
      </div>`
    ], Boolean(telegram.bot_token_configured && telegram.chat_id));
  }

  function renderSystemRuntimeSettings(server, auth) {
    const publicMode = Boolean(server?.public_mode);
    const host = server?.host || setting('server.host', '127.0.0.1');
    const port = server?.port || setting('server.port', 18463);
    return renderCard('系统与公网访问', [
      `<div class="desk-settings-form" data-system-settings-card="system">
        ${renderCheckbox('公网模式', 'server.public_mode', publicMode)}
        ${renderInput('监听地址', 'server.host', host, { placeholder: publicMode ? '0.0.0.0' : '127.0.0.1' })}
        ${renderInput('端口', 'server.port', port, { type: 'number', min: 1, max: 65535, step: 1 })}
        ${renderSecretInput('访问密码', 'miniapp_access_password', auth?.miniapp_access_password_configured, {
          placeholder: auth?.miniapp_access_password_configured ? '留空则不修改' : '公网模式必须设置访问密码'
        })}
        <p class="desk-settings-form__hint">默认本机模式会强制绑定 127.0.0.1；公网模式保存后需要重启服务生效，且必须配置访问密码。</p>
        ${renderSystemSaveButton('system', '保存系统配置')}
      </div>`
    ], !publicMode || Boolean(auth?.miniapp_access_password_configured));
  }

  function renderProviderCoreSettings(provider) {
    const currentModel = provider.image_main_model || 'gpt-5.5';
    const codexRoute = lastGptModelCatalog?.routes?.codex || null;
    const models = codexRoute
      ? (codexRoute.available === false
        ? []
        : (Array.isArray(codexRoute.models) ? codexRoute.models.filter(item => item?.image_generation !== false) : []))
      : (provider.allowed_image_main_models || ['gpt-5.5']).map(value => ({ id: value, label: value }));
    const selectedModel = models.some(item => item.id === currentModel)
      ? currentModel
      : (codexRoute?.default_model || models[0]?.id || '');
    const modelOptions = models.length
      ? models.map(item => optionHtml(item.id, item.label || item.id, selectedModel)).join('')
      : optionHtml('', '无可用模型', '');
    const selectedModelMeta = models.find(item => item.id === selectedModel) || null;
    const reasoningEfforts = Array.isArray(selectedModelMeta?.reasoning_efforts)
      ? selectedModelMeta.reasoning_efforts
      : (codexRoute ? [] : (provider.allowed_reasoning_efforts || ['low', 'medium', 'high', 'xhigh']));
    const configuredEffort = provider.reasoning_effort || 'medium';
    const selectedEffort = reasoningEfforts.includes(configuredEffort)
      ? configuredEffort
      : (reasoningEfforts.includes(selectedModelMeta?.default_reasoning_effort)
        ? selectedModelMeta.default_reasoning_effort
        : (reasoningEfforts.includes('medium') ? 'medium' : reasoningEfforts[0]));
    const effortOptions = reasoningEfforts.length
      ? reasoningEfforts.map(value => optionHtml(value, value, selectedEffort)).join('')
      : optionHtml('none', '不适用', 'none');
    return renderCard('Provider 连接', [
      `<div class="desk-settings-form" data-system-settings-card="provider">
        <label>
          <span>主模型</span>
          <select class="desk-select" data-system-setting-field="gpt_provider.image_main_model"${models.length ? '' : ' disabled'}>${modelOptions}</select>
        </label>
        <label>
          <span>推理强度</span>
          <select class="desk-select" data-system-setting-field="gpt_provider.reasoning_effort"${reasoningEfforts.length ? '' : ' disabled'}>${effortOptions}</select>
        </label>
        <p class="desk-settings-form__hint">生图引擎：${escapeHtml(codexRoute?.image_engine?.label || 'GPT Image 2')}</p>
        <div class="desk-settings-form__actions desk-settings-form__actions--compact">
          <button type="button" data-gpt-generation-models-refresh>刷新线路模型</button>
        </div>
        ${renderSystemSaveButton('provider', '保存 Provider 配置')}
      </div>`
    ], true);
  }

  function syncProviderReasoningField(modelSelect) {
    const route = lastGptModelCatalog?.routes?.codex;
    const reasoningSelect = modelSelect?.closest('[data-system-settings-card="provider"]')
      ?.querySelector('[data-system-setting-field="gpt_provider.reasoning_effort"]');
    if (!route || !reasoningSelect) return;
    const model = (route.models || []).find(item => item?.id === modelSelect.value);
    const efforts = Array.isArray(model?.reasoning_efforts) ? model.reasoning_efforts : [];
    const current = reasoningSelect.value;
    const selected = efforts.includes(current)
      ? current
      : (efforts.includes(model?.default_reasoning_effort)
        ? model.default_reasoning_effort
        : (efforts.includes('medium') ? 'medium' : efforts[0]));
    reasoningSelect.innerHTML = efforts.length
      ? efforts.map(value => optionHtml(value, value, selected)).join('')
      : optionHtml('none', '不适用', 'none');
    reasoningSelect.disabled = !efforts.length;
    window.DesktopSelect?.refresh?.(reasoningSelect);
  }

  function renderThirdPartyImageSettings(config, nanoConfig = {}) {
    const api = config || {};
    const nano = nanoConfig || {};
    const nanoCard = renderCard('Nano Banana API', [
      `<div class="desk-settings-form" data-system-settings-card="third-party-nano">
        <p class="desk-settings-form__hint">Google / Gemini 兼容图像生成端点。</p>
        ${renderSecretInput('Nano Banana Key', 'nano_banana_api.api_key', nano.api_key_configured, {
          placeholder: nano.api_key_configured ? '留空则不修改' : '粘贴 nano banana API Key'
        })}
        ${renderInput('API URL', 'nano_banana_api.base_url', nano.base_url || '', {
          placeholder: 'https://your-provider.example/v1beta'
        })}
        ${renderSystemSaveButton('third-party-nano', '保存 Nano Banana API')}
      </div>`
    ], Boolean(nano.api_key_configured && nano.base_url));
    const gptImageCard = renderCard('Gpt-Image-2 API', [
      `<div class="desk-settings-form" data-system-settings-card="third-party-gpt-image">
        <p class="desk-settings-form__hint">OpenAI Images 兼容第三方端点。只在模型节点“线路”选择“第三方 API”时启用，不参与默认 GPT fallback。</p>
        ${renderSecretInput('Gpt-Image-2 Key', 'third_party_image_api.api_key', api.api_key_configured, {
          placeholder: api.api_key_configured ? '留空则不修改' : '粘贴 Gpt-image-2 API Key'
        })}
        ${renderInput('API URL', 'third_party_image_api.base_url', api.base_url || '', {
          placeholder: 'https://your-provider.example'
        })}
        ${renderInput('生成路径', 'third_party_image_api.generate_path', api.generate_path || '/v1/images/generations')}
        ${renderInput('编辑路径', 'third_party_image_api.edit_path', api.edit_path || '/v1/images/edits')}
        ${renderInput('模型', 'third_party_image_api.model', api.model || 'gpt-image-2')}
        <label>
          <span>输出格式</span>
          <select class="desk-select" data-system-setting-field="third_party_image_api.format">
            ${optionHtml('png', 'png', api.format || 'png')}
            ${optionHtml('jpeg', 'jpeg', api.format)}
            ${optionHtml('webp', 'webp', api.format)}
          </select>
        </label>
        ${renderInput('超时秒数', 'third_party_image_api.timeout_seconds', api.timeout_seconds || 900, { type: 'number', min: 30, max: 1800, step: 30 })}
        ${renderSystemSaveButton('third-party-gpt-image', '保存 Gpt-Image-2 API')}
      </div>`
    ], Boolean(api.api_key_configured && api.base_url));
    return nanoCard + gptImageCard;
  }

  function renderPathSettings(storage, database) {
    return renderCard('路径与存储', [
      `<div class="desk-settings-form" data-system-settings-card="paths">
        ${renderInput('Image Archive', 'paths.image_archive_dir', storage.image_archive_dir?.path || setting('paths.image_archive_dir', ''))}
        ${renderInput('Source Image', 'paths.source_image_dir', storage.source_image_dir?.path || setting('paths.source_image_dir', ''))}
        ${renderInput('Tasks DB', 'paths.tasks_db', database.tasks_db?.path || setting('paths.tasks_db', 'tasks.db'))}
        <p class="desk-settings-form__hint">可用相对路径，例如 data/archive；默认旧绝对路径仍可继续使用。</p>
        ${renderSystemSaveButton('paths', '保存路径配置')}
      </div>`
    ], Boolean(storage.image_archive_dir?.exists && storage.source_image_dir?.exists && database.tasks_db?.exists));
  }

  function renderChatgptPoolRuntimeSettings(pool) {
    const poolRoute = lastGptModelCatalog?.routes?.chatgpt_pool || null;
    const models = poolRoute
      ? (poolRoute.available === false
        ? []
        : (Array.isArray(poolRoute.models) ? poolRoute.models.filter(item => item?.image_generation !== false) : []))
      : [{ id: 'gpt-5-5', label: 'GPT-5.5' }];
    const rawConfiguredModel = String(pool.generation_model || 'gpt-5-5');
    const configuredModel = ['gpt-image-2', 'gpt-5-3', 'auto'].includes(rawConfiguredModel)
      ? (poolRoute?.default_model || 'gpt-5-5')
      : rawConfiguredModel;
    const selectedModel = models.some(item => item.id === configuredModel)
      ? configuredModel
      : (poolRoute?.default_model || models[0]?.id || '');
    const poolModelOptions = models.length
      ? models.map(item => optionHtml(item.id, item.label || item.id, selectedModel)).join('')
      : optionHtml('', '无可用模型', '');
    return renderCard('账号池运行配置', [
      `<div class="desk-settings-form" data-system-settings-card="chatgpt-pool">
        ${renderCheckbox('启用账号池', 'chatgpt_pool.enabled', pool.enabled !== false)}
        ${renderInput('Base URL', 'chatgpt_pool.base_url', pool.base_url || 'http://127.0.0.1:18080')}
        ${renderSecretInput('Auth Key', 'chatgpt_pool.auth_key', pool.auth_key_configured, {
          placeholder: pool.auth_key_configured ? '留空则不修改' : '留空可由服务自动生成'
        })}
        <label>
          <span>主模型</span>
          <select class="desk-select" data-system-setting-field="chatgpt_pool.generation_model"${models.length ? '' : ' disabled'}>${poolModelOptions}</select>
        </label>
        <p class="desk-settings-form__hint">生图引擎：${escapeHtml(poolRoute?.image_engine?.label || 'ChatGPT Image')}</p>
        ${renderInput('超时秒数', 'chatgpt_pool.timeout_seconds', pool.timeout_seconds || 900, { type: 'number', min: 60, max: 900, step: 30 })}
        ${renderInput('账号库路径', 'chatgpt_pool.db_path', pool.db_path || 'data/chatgpt_pool/accounts.db')}
        <div class="desk-settings-form__actions desk-settings-form__actions--compact">
          <button type="button" data-gpt-generation-models-refresh>刷新网页模型</button>
        </div>
        ${renderSystemSaveButton('chatgpt-pool', '保存账号池配置')}
      </div>`
    ], Boolean(pool.enabled));
  }

  function renderPromptSettings(promptRuntime) {
    const cfg = promptRuntime?.prompt_skill || {};
    const providers = Array.isArray(promptRuntime?.providers) ? promptRuntime.providers : [];
    const models = Array.isArray(promptRuntime?.models) ? promptRuntime.models : [];
    const currentProvider = cfg.provider || promptRuntime?.provider || 'gpt_oauth';
    const currentModel = cfg.model || promptRuntime?.default_model || '';
    const providerOptions = providers.length
      ? providers.map(item => optionHtml(item.id, item.label || item.id, currentProvider)).join('')
      : optionHtml(currentProvider, currentProvider, currentProvider);
    const modelOptions = models.length
      ? models.map(item => optionHtml(item.id, item.label || item.id, currentModel)).join('')
      : optionHtml('', promptRuntime?.warning || '没有可用模型', '');
    const modelDisabled = models.length ? '' : ' disabled';
    return renderCard('提示词润色 Skill', [
      `<div class="desk-settings-form">
        <label>
          <span>Provider</span>
          <select class="desk-select" data-prompt-config-field="provider">${providerOptions}</select>
        </label>
        <label>
          <span>Skill</span>
          <select class="desk-select" data-prompt-config-field="skill">
            ${optionHtml('image_prompt_v7', 'Image Prompt V7', cfg.skill || 'image_prompt_v7')}
          </select>
        </label>
        <label>
          <span>推理模型</span>
          <select class="desk-select" data-prompt-config-field="model"${modelDisabled}>${modelOptions}</select>
        </label>
        <label>
          <span>推理强度</span>
          <select class="desk-select" data-prompt-config-field="reasoning_effort">
            ${optionHtml('none', '关闭', cfg.reasoning_effort)}
            ${optionHtml('low', '低', cfg.reasoning_effort)}
            ${optionHtml('medium', '中', cfg.reasoning_effort || 'medium')}
            ${optionHtml('high', '高', cfg.reasoning_effort)}
            ${optionHtml('xhigh', '超高', cfg.reasoning_effort)}
          </select>
        </label>
        <label>
          <span>默认回填</span>
          <select class="desk-select" data-prompt-config-field="default_output">
            ${optionHtml('full_prompt', '完整提示词', cfg.default_output || 'full_prompt')}
            ${optionHtml('compact_prompt', '精简投喂版', cfg.default_output)}
          </select>
        </label>
        ${promptRuntime?.warning ? `<p class="desk-settings-form__hint">${escapeHtml(promptRuntime.warning)}</p>` : ''}
        <div class="desk-settings-form__actions">
          <button type="button" data-prompt-config-reload>刷新模型</button>
          <button type="button" class="is-primary" data-prompt-config-save>保存润色配置</button>
        </div>
      </div>`
    ], Boolean(models.length));
  }

  function renderPromptOverview(promptRuntime) {
    const cfg = promptRuntime?.prompt_skill || {};
    return renderCard('提示词润色', [
      renderKv('Provider', cfg.provider || promptRuntime?.provider || '未设置'),
      renderKv('Skill', cfg.skill || 'image_prompt_v7'),
      renderKv('推理模型', cfg.model || promptRuntime?.default_model || '未选择'),
      renderKv('推理强度', cfg.reasoning_effort || 'medium')
    ], Boolean(cfg.model || promptRuntime?.default_model));
  }

  function transportLabel(mode) {
    const labels = {
      stream: '走流式',
      nonstream: '非流式',
      stream_then_nonstream: '先流式，失败走非流'
    };
    return labels[mode] || labels.stream_then_nonstream;
  }

  function renderGptProviderSettings(provider) {
    const currentMode = provider.transport_mode || 'stream_then_nonstream';
    const timeoutSeconds = Number(provider.total_timeout_seconds || 600);
    return renderCard('GPT Provider 传输', [
      `<div class="desk-settings-form">
        <label>
          <span>传输策略</span>
          <select class="desk-select" data-gpt-provider-field="transport_mode">
            ${optionHtml('stream', '走流式', currentMode)}
            ${optionHtml('nonstream', '非流式', currentMode)}
            ${optionHtml('stream_then_nonstream', '先流式，失败走非流', currentMode)}
          </select>
        </label>
        <label>
          <span>本地超时</span>
          <input class="desk-input" type="number" min="30" max="1800" step="30" data-gpt-provider-field="total_timeout_seconds" value="${escapeHtml(timeoutSeconds || 600)}">
        </label>
        <p class="desk-settings-form__hint">默认 600 秒。到达本地 Codex 总等待上限后，自动切账号池托底。</p>
        <div class="desk-settings-form__actions">
          <button type="button" class="is-primary" data-gpt-provider-save>保存 GPT Provider 配置</button>
        </div>
      </div>`
    ], true);
  }

  function renderManagedCodexOAuthSettings(managed) {
    const account = managed?.account || {};
    const reloginCount = Number(managed?.stats?.requires_relogin || managed?.accounts?.stats?.requires_relogin || 0);
    const configured = Boolean(managed?.configured) && reloginCount <= 0;
    const accountLabel = account.email || account.chatgpt_account_id || '未授权';
    const planLabel = chatgptPoolPlanLabel(account.chatgpt_plan_type);
    const accountsPayload = managed?.accounts || {};
    const stats = accountsPayload.stats || managed?.stats || {};
    const accounts = Array.isArray(accountsPayload.items) ? accountsPayload.items : [];
    const statusLabel = reloginCount > 0
      ? '需要重新登录'
      : (configured ? '可用' : (managed?.error || '未授权'));
    return renderCard('托管 Codex OAuth', [
      renderKv('授权状态', statusLabel),
      renderKv('账号', accountLabel),
      renderKv('账号类型', planLabel),
      renderKv('AT 到期时间', managed?.expired ? chatgptPoolTimeLabel(managed.expired, '') : '未设置'),
      renderKv('待完成授权', managed?.pending_sessions ?? 0),
      renderManagedCodexActionBar(managed, stats),
      accounts.length
        ? accounts.map(renderManagedCodexAccount).join('')
        : '<div class="desk-settings-empty desk-settings-empty--compact">暂无托管 Codex 账号，可用 OAuth 登录或粘贴 Auth JSON 添加。</div>',
      managed?.error && !configured ? renderKv('状态', managed.error) : ''
    ].filter(Boolean), configured);
  }

  function renderManagedCodexActionBar(managed, stats = {}) {
    const reloginCount = Number(stats.requires_relogin || 0);
    const ready = Boolean(managed?.configured) && reloginCount <= 0;
    return `
      <div class="desk-settings-pool-toolbar">
        <div class="desk-settings-pool-summary">
          <span class="${ready ? 'is-ok' : 'is-warn'}">当前 ${escapeHtml(ready ? '可用' : (reloginCount > 0 ? '需重新登录' : '未授权'))}</span>
          <span>账号 ${escapeHtml(stats.total ?? 0)}</span>
          <span>可用 ${escapeHtml(stats.available ?? 0)}</span>
          <span>启用 ${escapeHtml(stats.enabled ?? 0)}</span>
          <span>需重登 ${escapeHtml(reloginCount)}</span>
          <span>禁用 ${escapeHtml(stats.disabled ?? 0)}</span>
          <span>可续期 ${escapeHtml(stats.refreshable ?? 0)}</span>
          <span>AT 过期 ${escapeHtml(stats.expired ?? 0)}</span>
        </div>
        <div class="desk-settings-form__actions desk-settings-form__actions--compact">
          <button type="button" data-managed-codex-oauth-refresh-all>刷新全部 AT</button>
          <button type="button" data-managed-codex-oauth-logout>清空全部</button>
        </div>
      </div>
    `;
  }

  function renderManagedCodexAccount(account = {}) {
    const status = valueText(account.status, '未知');
    const requiresRelogin = Boolean(account.requires_relogin);
    const ok = !requiresRelogin && (status === '正常' || status === 'AT过期');
    const accountId = account.account_id || account.id || '';
    const disabled = Boolean(account.disabled);
    const email = valueText(account.email || account.chatgpt_account_id, '未命名账号');
    const meta = [
      account.selected ? '当前使用' : '',
      `账号类型 ${chatgptPoolPlanLabel(account.chatgpt_plan_type || account.plan_type)}`,
      requiresRelogin ? 'Refresh Token 已失效' : '',
      account.refreshable ? '可续期' : '不可续期',
      account.expires_at ? `AT 到期 ${chatgptPoolTimeLabel(account.expires_at, '')}` : 'AT 到期 未设置',
      account.chatgpt_account_id ? `账号 ${account.chatgpt_account_id.slice(0, 8)}` : ''
    ].filter(Boolean).join(' / ');
    return `
      <div class="desk-settings-account ${statusClass(ok && !disabled)} ${account.selected ? 'is-selected' : ''}" data-managed-codex-account data-account-id="${escapeHtml(accountId)}" data-selected="${account.selected ? 'true' : 'false'}" data-disabled="${disabled ? 'true' : 'false'}">
        <div class="desk-settings-account__main">
          <strong title="${escapeHtml(email)}">${escapeHtml(email)}</strong>
          <span>${escapeHtml(account.selected ? `当前 · ${status}` : status)}</span>
        </div>
        <div class="desk-settings-account__meta" title="${escapeHtml(meta)}">${escapeHtml(meta || account.path || '')}</div>
        ${account.last_refresh_error ? `<div class="desk-settings-account__error">${escapeHtml(account.last_refresh_error)}</div>` : ''}
        <div class="desk-settings-account__actions">
          <button type="button" data-managed-codex-account-select data-account-id="${escapeHtml(accountId)}" ${account.selected ? 'disabled' : ''}>设为当前</button>
          <button type="button" data-managed-codex-account-refresh data-account-id="${escapeHtml(accountId)}">${requiresRelogin ? '重试刷新' : '刷新 AT'}</button>
          <button type="button" data-managed-codex-account-toggle data-account-id="${escapeHtml(accountId)}" data-disabled="${disabled ? 'false' : 'true'}">${disabled ? '启用' : '禁用'}</button>
          <button type="button" data-managed-codex-account-delete data-account-id="${escapeHtml(accountId)}">删除</button>
        </div>
      </div>
    `;
  }

  function renderManagedCodexAddSettings(managed) {
    const activity = managedCodexOAuthActivity;
    const activityText = activity ? `${activity.time} · ${activity.message}` : '';
    return renderCard('添加托管 Codex 账号', [
      `<details class="desk-settings-details" open>
        <summary>
          <span>OAuth 登录</span>
          <em>可反复添加多个 ChatGPT / Codex 账号</em>
        </summary>
        <div class="desk-settings-form desk-settings-form--compact">
          <input type="hidden" data-managed-codex-session-id value="${escapeHtml(managedCodexOAuthSessionId)}">
          <label>
            <span>邮箱</span>
            <input class="desk-input" type="email" data-managed-codex-email-hint placeholder="可选">
          </label>
          <label class="desk-settings-form__wide">
            <span>授权链接</span>
            <textarea class="desk-settings-textarea" data-managed-codex-authorize-url readonly>${escapeHtml(managedCodexOAuthAuthorizeUrl)}</textarea>
          </label>
          <label class="desk-settings-form__wide">
            <span>回调 URL / Code</span>
            <textarea class="desk-settings-textarea" data-managed-codex-callback placeholder="http://localhost:1455/auth/callback?code=..."></textarea>
          </label>
          <div
            class="desk-settings-pool-activity ${activity ? `is-${escapeHtml(activity.tone || 'working')}` : ''}"
            data-managed-codex-oauth-feedback
            role="status"
            aria-live="polite"
            ${activityText ? '' : 'hidden'}
          >${escapeHtml(activityText)}</div>
          <div class="desk-settings-form__actions">
            <button type="button" data-managed-codex-oauth-start>打开授权</button>
            <button type="button" class="is-primary" data-managed-codex-oauth-finish>完成授权</button>
          </div>
        </div>
      </details>
      <details class="desk-settings-details">
        <summary>
          <span>粘贴 Auth JSON</span>
          <em>支持单个对象或 accounts 数组</em>
        </summary>
        <div class="desk-settings-form desk-settings-form--compact">
          <label class="desk-settings-form__wide">
            <span>Auth JSON</span>
            <textarea class="desk-settings-textarea" data-managed-codex-import-json placeholder='{"access_token":"...","refresh_token":"...","id_token":"..."}'></textarea>
          </label>
          <div class="desk-settings-form__actions">
            <button type="button" class="is-primary" data-managed-codex-import>导入粘贴 JSON</button>
          </div>
        </div>
      </details>
      <details class="desk-settings-details">
        <summary>
          <span>运行配置</span>
          <em>账号库路径与 Codex API endpoint</em>
        </summary>
        <div class="desk-settings-form" data-system-settings-card="managed-codex-oauth">
          ${renderCheckbox('启用托管 OAuth', 'managed_codex_oauth.enabled', managed?.enabled !== false)}
          ${renderInput('Auth File', 'managed_codex_oauth.auth_file', managed?.auth_file || 'data/managed_codex_oauth/auth.json')}
          ${renderInput('Accounts Dir', 'managed_codex_oauth.accounts_dir', managed?.accounts_dir || 'data/managed_codex_oauth/accounts')}
          ${renderInput('Codex API Base', 'managed_codex_oauth.api_base', managed?.api_base || 'https://chatgpt.com/backend-api/codex')}
          ${renderInput('Redirect URI', 'managed_codex_oauth.redirect_uri', managed?.redirect_uri || 'http://localhost:1455/auth/callback')}
          ${renderSystemSaveButton('managed-codex-oauth', '保存托管 OAuth 配置')}
        </div>
      </details>`
    ], Boolean(managed?.enabled !== false));
  }

  function renderChatgptPoolAccount(account) {
    const status = valueText(account?.status, '未知');
    const ok = status === '正常';
    const accountId = account?.account_id || '';
    const nextStatus = status === '禁用' ? '正常' : '禁用';
    const needsVerification = status === '需要验证';
    const refreshBusyAttrs = chatgptPoolRefreshBusy
      ? ' disabled aria-disabled="true" title="正在刷新 AT，完成后可用"'
      : '';
    const email = valueText(account?.email || account?.token_preview, '未命名账号');
    const meta = [
      chatgptPoolPlanLabel(account?.plan_type || account?.type),
      account?.has_refresh_token ? '可续期' : '临时 AT',
      account?.restore_at ? chatgptPoolTimeLabel(account.restore_at, '恢复 ') : '',
      account?.expires_at_iso ? chatgptPoolTimeLabel(account.expires_at_iso, 'AT ') : '',
      account?.quota ? `额度 ${account.quota}` : ''
    ].filter(Boolean).join(' / ');
    return `
      <div class="desk-settings-account ${statusClass(ok)}">
        <div class="desk-settings-account__main">
          <strong title="${escapeHtml(email)}">${escapeHtml(email)}</strong>
          <span>${escapeHtml(status)}</span>
        </div>
        <div class="desk-settings-account__meta" title="${escapeHtml(meta)}">${escapeHtml(meta || account?.token_preview || '')}</div>
        ${account?.last_refresh_error ? `<div class="desk-settings-account__error">${escapeHtml(account.last_refresh_error)}</div>` : ''}
        <div class="desk-settings-account__actions">
          ${needsVerification ? `<button type="button" data-chatgpt-pool-account-verify data-account-id="${escapeHtml(accountId)}" title="打开 ChatGPT 网页验证窗口">验证</button>` : ''}
          <button type="button" data-chatgpt-pool-account-refresh data-account-id="${escapeHtml(accountId)}"${refreshBusyAttrs}>刷新</button>
          <button type="button" data-chatgpt-pool-account-toggle data-account-id="${escapeHtml(accountId)}" data-next-status="${escapeHtml(nextStatus)}">${status === '禁用' ? '启用' : '禁用'}</button>
          <button type="button" data-chatgpt-pool-account-delete data-account-id="${escapeHtml(accountId)}">删除</button>
        </div>
      </div>
    `;
  }

  function renderChatgptPoolActionBar(pool, accountsPayload) {
    const stats = accountsPayload?.stats || pool?.stats || {};
    const online = Boolean(pool?.online);
    const statusText = online ? '在线' : (pool?.health_error || '离线');
    const activity = chatgptPoolActivity;
    const activityText = activity?.message
      ? `${activity.time ? `${activity.time} · ` : ''}${activity.message}`
      : '';
    const refreshAllBusyAttrs = chatgptPoolRefreshBusy
      ? ' disabled aria-disabled="true"'
      : '';
    return `
      <div class="desk-settings-pool-toolbar">
        <div class="desk-settings-pool-summary">
          <span class="${online ? 'is-ok' : 'is-warn'}">Sidecar ${escapeHtml(statusText)}</span>
          <span>账号 ${escapeHtml(stats.total ?? 0)}</span>
          <span>可用 ${escapeHtml(stats.available ?? stats.active ?? 0)}</span>
          <span>忙碌 ${escapeHtml(stats.inflight ?? 0)}</span>
          <span>可续期 ${escapeHtml(stats.refreshable ?? 0)}</span>
          <span>限流 ${escapeHtml(stats.limited ?? 0)}</span>
          <span>异常 ${escapeHtml(stats.abnormal ?? 0)}</span>
        </div>
        <div class="desk-settings-form__actions desk-settings-form__actions--compact">
          <button type="button" data-chatgpt-pool-load-accounts title="只重新读取本地 Sidecar 账号状态，不刷新 token">读取列表</button>
          <button type="button" data-chatgpt-pool-refresh-all title="用 refresh_token 刷新 Access Token；多个账号可能需要 30-60 秒"${refreshAllBusyAttrs}>刷新 AT</button>
          <button type="button" class="is-primary" data-chatgpt-pool-import-local-auth>导入本机 Auth</button>
        </div>
        <div
          class="desk-settings-pool-activity ${activity ? `is-${escapeHtml(activity.tone || 'info')}` : ''}"
          data-chatgpt-pool-activity
          ${activityText ? '' : 'hidden'}
        >${escapeHtml(activityText)}</div>
      </div>
    `;
  }

  function renderChatgptPoolOverview(pool, accountsPayload) {
    const stats = accountsPayload?.stats || pool?.stats || {};
    const online = Boolean(pool?.online);
    return renderCard('账号池', [
      renderKv('Sidecar', online ? '在线' : (pool?.health_error || '未在线')),
      renderKv('启用状态', pool?.enabled, { boolean: true }),
      renderKv('账号数', stats.total ?? 0),
      renderKv('可用 / 忙碌 / 总数', `${stats.available ?? stats.active ?? 0} / ${stats.inflight ?? 0} / ${stats.total ?? 0}`),
      renderKv('限流 / 异常', `${stats.limited ?? 0} / ${stats.abnormal ?? 0}`),
      renderKv('可续期', stats.refreshable ?? 0),
      renderKv('模型', pool?.generation_model || pool?.model || 'gpt-image-2')
    ], online && Boolean(pool?.enabled));
  }

  function renderChatgptPoolSettings(pool, accountsPayload) {
    const stats = accountsPayload?.stats || pool?.stats || {};
    const accounts = Array.isArray(accountsPayload?.items) ? accountsPayload.items : [];
    const online = Boolean(pool?.online);
    const noAccounts = accounts.length === 0;
    const oauthActivity = chatgptPoolOAuthActivity;
    const oauthActivityText = oauthActivity ? `${oauthActivity.time} · ${oauthActivity.message}` : '';
    const oauthOpen = noAccounts || Boolean(chatgptPoolOAuthSessionId) || Boolean(oauthActivity);
    return [
      renderCard('账号列表', [
        renderChatgptPoolActionBar(pool, accountsPayload),
        accounts.length
          ? accounts.map(renderChatgptPoolAccount).join('')
          : '<div class="desk-settings-empty desk-settings-empty--compact">暂无账号，先在下方添加一个授权账号。</div>'
      ], online && (stats.active ?? 0) > 0),
      renderCard('添加账号', [
        `<details class="desk-settings-details"${oauthOpen ? ' open' : ''}>
          <summary>
            <span>OAuth 登录</span>
            <em>生成授权，登录后粘贴 callback URL</em>
          </summary>
          <div class="desk-settings-form desk-settings-form--compact">
            <input type="hidden" data-chatgpt-pool-session-id value="${escapeHtml(chatgptPoolOAuthSessionId)}">
            <label>
              <span>邮箱</span>
              <input class="desk-input" type="email" data-chatgpt-pool-email-hint placeholder="可选">
            </label>
            <label class="desk-settings-form__wide">
              <span>授权链接</span>
              <textarea class="desk-settings-textarea" data-chatgpt-pool-authorize-url readonly>${escapeHtml(chatgptPoolOAuthAuthorizeUrl)}</textarea>
            </label>
            <label class="desk-settings-form__wide">
              <span>回调 URL / Code</span>
              <textarea class="desk-settings-textarea" data-chatgpt-pool-callback placeholder="登录完成后，复制浏览器地址栏的完整 URL 并粘贴到这里"></textarea>
            </label>
            <div
              class="desk-settings-pool-activity ${oauthActivity ? `is-${escapeHtml(oauthActivity.tone || 'working')}` : ''}"
              data-chatgpt-pool-oauth-feedback
              role="status"
              aria-live="polite"
              ${oauthActivityText ? '' : 'hidden'}
            >${escapeHtml(oauthActivityText)}</div>
            <div class="desk-settings-form__actions">
              <button type="button" data-chatgpt-pool-oauth-start>生成授权</button>
              <button type="button" class="is-primary" data-chatgpt-pool-oauth-finish>完成授权</button>
            </div>
          </div>
        </details>
        <details class="desk-settings-details">
          <summary>
            <span>粘贴 Auth JSON</span>
            <em>仅在已有完整 token JSON 时使用</em>
          </summary>
          <div class="desk-settings-form desk-settings-form--compact">
            <label class="desk-settings-form__wide">
              <span>Auth JSON</span>
              <textarea class="desk-settings-textarea" data-chatgpt-pool-import-json placeholder='{"access_token":"...","refresh_token":"...","id_token":"..."}'></textarea>
            </label>
            <div class="desk-settings-form__actions">
              <button type="button" data-chatgpt-pool-import>导入粘贴 JSON</button>
            </div>
          </div>
        </details>`
      ], online)
    ].join('');
  }

  function renderDiagnostics(data) {
    const telegram = data.telegram || {};
    const nanoBanana = {
      ...(data.yunwu || {}),
      ...(data.nano_banana_api || {}),
      ...(setting('yunwu', {}) || {}),
      ...(setting('nano_banana_api', {}) || {})
    };
    const storage = data.storage || {};
    const database = data.database || {};
    const provider = data.gpt_provider || {};
    const managedCodex = {
      ...(data.managed_codex_oauth || {}),
      ...(setting('managed_codex_oauth', {}) || {})
    };
    const pool = data.chatgpt_pool || {};
    const thirdParty = {
      ...(data.third_party_image_api || {}),
      ...(setting('third_party_image_api', {}) || {})
    };
    const auth = data.auth || {};
    const server = data.server || {};
    const promptRuntime = lastPromptConfig || { prompt_skill: data.prompt_skill || {} };
    const promptSkill = promptRuntime.prompt_skill || data.prompt_skill || {};
    const editableProvider = setting('gpt_provider', {});
    const providerRuntime = { ...provider, ...editableProvider };
    const editableServer = { ...server, ...(setting('server', {}) || {}) };
    const editablePool = { ...pool, ...(setting('chatgpt_pool', {}) || {}) };
    const thirdPartyReady = Boolean(nanoBanana.api_key_configured || thirdParty.api_key_configured);
    const providerNeedsRelogin = Boolean(provider.requires_relogin);
    const providerReady = Boolean(provider.configured) && !providerNeedsRelogin;
    const managedReloginCount = Number(managedCodex?.stats?.requires_relogin || managedCodex?.accounts?.stats?.requires_relogin || 0);
    const managedReady = Boolean(managedCodex.configured) && managedReloginCount <= 0;
    const providerStatusLabel = providerNeedsRelogin
      ? '需要重新登录'
      : (providerReady ? (provider.expiring ? 'AT 将过期/会尝试刷新' : '可用') : '未就绪');
    const managedStatusLabel = managedReloginCount > 0
      ? '需要重新登录'
      : (managedReady ? '已授权' : '未授权');
    const sections = [
      {
        tab: 'status',
        html: renderCard('系统', [
          renderKv('监听地址', `${server.host || '127.0.0.1'}:${server.port || 18463}`),
          renderKv('公网模式', server.public_mode ? '已开启' : '本机模式'),
          renderKv('公网密码', server.password_configured, { boolean: true }),
          server.restart_required ? renderKv('重启状态', '需要重启') : ''
        ], !server.public_mode || server.password_configured)
      },
      {
        tab: 'system',
        html: activeTab === 'system' ? renderSystemRuntimeSettings(editableServer, setting('auth', auth)) : ''
      },
      {
        tab: 'status',
        html: renderCard('Telegram', [
        renderKv('Bot Token', telegram.bot_token_configured, { boolean: true }),
        renderKv('Chat ID', telegram.chat_id_configured, { boolean: true }),
        renderKv('发送方式', telegram.delivery_method || 'sendDocument'),
        renderKv('代理', telegram.proxy_url || '未使用')
        ], telegram.bot_token_configured && telegram.chat_id_configured && telegram.delivery_method === 'sendDocument')
      },
      {
        tab: 'telegram',
        html: activeTab === 'telegram' ? renderTelegramSettings() : ''
      },
      {
        tab: 'status',
        html: renderCard('鉴权', [
          renderKv('访问密码', auth.password_enabled, { boolean: true }),
          renderKv('Telegram initData', auth.telegram_init_data_enabled, { boolean: true }),
          renderKv('允许用户数', auth.allowed_user_count ?? 0)
        ], auth.password_enabled || auth.telegram_init_data_enabled)
      },
      {
        tab: 'status',
        html: renderCard('Provider 连接', [
        renderKv('Codex 登录态', providerStatusLabel),
        renderKv('托管 Codex OAuth', managedStatusLabel),
        renderKv('GPT 传输策略', transportLabel(provider.transport_mode || 'stream_then_nonstream')),
        renderKv('本地 Codex 超时', `${provider.total_timeout_seconds || 600}s`),
        renderKv('Auth File 配置', provider.auth_file_configured, { boolean: true }),
        renderKv('Auth Dir 配置', provider.auth_dir_configured, { boolean: true })
        ], providerReady || managedReady)
      },
      {
        tab: 'provider',
        html: activeTab === 'provider' ? renderProviderCoreSettings(providerRuntime) : ''
      },
      {
        tab: 'provider',
        html: activeTab === 'provider' ? renderGptProviderSettings(providerRuntime) : ''
      },
      {
        tab: 'provider',
        html: activeTab === 'provider' ? renderManagedCodexOAuthSettings(managedCodex) : ''
      },
      {
        tab: 'provider',
        html: activeTab === 'provider' ? renderManagedCodexAddSettings(managedCodex) : ''
      },
      {
        tab: 'third-party',
        html: activeTab === 'third-party' ? renderThirdPartyImageSettings(thirdParty, nanoBanana) : renderCard('第三方 API', [
          renderKv('nano banana API Key', nanoBanana.api_key_configured, { boolean: true }),
          renderKv('nano banana API URL', nanoBanana.base_url || ''),
          renderKv('Gpt-image-2 API Key', thirdParty.api_key_configured, { boolean: true }),
          renderKv('Gpt-image-2 API URL', thirdParty.base_url || ''),
          renderKv('生成接口', thirdParty.generate_path || '/v1/images/generations'),
          renderKv('编辑接口', thirdParty.edit_path || '/v1/images/edits'),
          renderKv('模型', thirdParty.model || 'gpt-image-2')
        ], thirdPartyReady)
      },
      {
        tab: 'chatgpt-pool',
        html: activeTab === 'chatgpt-pool'
          ? renderChatgptPoolRuntimeSettings(editablePool) + renderChatgptPoolSettings(editablePool, lastChatgptPoolAccounts)
          : renderChatgptPoolOverview(pool, lastChatgptPoolAccounts)
      },
      {
        tab: 'paths',
        html: activeTab === 'paths' ? renderPathSettings(storage, database) : renderCard('路径与存储', [
        renderPath('Image Archive', storage.image_archive_dir),
        renderPath('Source Image', storage.source_image_dir),
        renderPath('Tasks DB', database.tasks_db)
        ], Boolean(storage.image_archive_dir?.exists && storage.source_image_dir?.exists && database.tasks_db?.exists))
      },
      {
        tab: 'prompt',
        html: activeTab === 'prompt'
          ? renderPromptSettings(promptRuntime)
          : renderPromptOverview(promptRuntime)
      }
    ];

    const visibleSections = activeTab === 'status'
      ? sections
      : sections.filter(section => section.tab === activeTab);
    const visibleHtml = visibleSections
      .map(section => section.html)
      .filter(Boolean);
    const warnCount = sections.filter(section => section.html.includes('is-warn')).length;
    if (els.deskSettingsSummary) {
      els.deskSettingsSummary.innerHTML = `
        <span class="${warnCount ? 'is-warn' : 'is-ok'}">${warnCount ? `${warnCount} 项需要确认` : '状态正常'}</span>
        <span>GPT provider ${escapeHtml(providerStatusLabel)}</span>
        <span>托管 Codex ${escapeHtml(managedStatusLabel)}</span>
        <span>${server.public_mode ? '公网模式' : '本机模式'}</span>
        <span>第三方 ${thirdPartyReady ? '已配置' : '未配置'}</span>
        <span>账号池 ${pool.online ? '在线' : '未在线'}</span>
        <span>润色 ${promptSkill.model || promptRuntime.default_model || '未选模型'}</span>
        <span>Telegram ${telegram.bot_token_configured && telegram.chat_id_configured ? '可用' : '未就绪'}</span>
      `;
    }
    if (els.deskSettingsBody) {
      els.deskSettingsBody.innerHTML = visibleHtml.join('');
    }
    updateTabs();
  }

  function renderLoading() {
    if (els.deskSettingsSummary) {
      els.deskSettingsSummary.innerHTML = '<span>正在诊断</span>';
    }
    if (els.deskSettingsBody) {
      els.deskSettingsBody.innerHTML = '<div class="desk-settings-empty">正在读取当前服务状态...</div>';
    }
  }

  function showSettingsFeedback(error, fallback = '设置操作失败') {
    const message = error?.message || (typeof error === 'string' ? error : '') || fallback;
    window.DesktopResults?.showTransientMessage?.(message, 'error');
  }

  function chatgptPoolClockLabel(date = new Date()) {
    const pad = value => String(value).padStart(2, '0');
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function setManagedCodexOAuthActivity(message, tone = 'working') {
    const text = String(message || '').trim();
    managedCodexOAuthActivity = text
      ? { message: text, tone: String(tone || 'working'), time: chatgptPoolClockLabel() }
      : null;
    const node = els.deskSettingsBody?.querySelector?.('[data-managed-codex-oauth-feedback]');
    if (!node) return;
    if (!managedCodexOAuthActivity) {
      node.hidden = true;
      node.textContent = '';
      node.className = 'desk-settings-pool-activity';
      return;
    }
    node.hidden = false;
    node.className = `desk-settings-pool-activity is-${managedCodexOAuthActivity.tone}`;
    node.textContent = `${managedCodexOAuthActivity.time} · ${managedCodexOAuthActivity.message}`;
  }

  function setChatgptPoolOAuthActivity(message, tone = 'working') {
    const text = String(message || '').trim();
    chatgptPoolOAuthActivity = text
      ? { message: text, tone: String(tone || 'working'), time: chatgptPoolClockLabel() }
      : null;
    const node = els.deskSettingsBody?.querySelector?.('[data-chatgpt-pool-oauth-feedback]');
    if (!node) return;
    if (!chatgptPoolOAuthActivity) {
      node.hidden = true;
      node.textContent = '';
      node.className = 'desk-settings-pool-activity';
      return;
    }
    node.hidden = false;
    node.className = `desk-settings-pool-activity is-${chatgptPoolOAuthActivity.tone}`;
    node.textContent = `${chatgptPoolOAuthActivity.time} · ${chatgptPoolOAuthActivity.message}`;
  }

  function setChatgptPoolActivity(message, tone = 'info') {
    const text = String(message || '').trim();
    chatgptPoolActivity = text
      ? { message: text, tone: String(tone || 'info'), time: chatgptPoolClockLabel() }
      : null;
    const node = els.deskSettingsBody?.querySelector?.('[data-chatgpt-pool-activity]');
    if (!node) return;
    if (!chatgptPoolActivity) {
      node.hidden = true;
      node.textContent = '';
      node.className = 'desk-settings-pool-activity';
      return;
    }
    node.hidden = false;
    node.className = `desk-settings-pool-activity is-${chatgptPoolActivity.tone}`;
    node.textContent = `${chatgptPoolActivity.time} · ${chatgptPoolActivity.message}`;
  }

  function chatgptPoolStatsLabel(payload = lastChatgptPoolAccounts) {
    const stats = payload?.stats || {};
    const total = stats.total ?? payload?.items?.length ?? 0;
    const available = stats.available ?? stats.active ?? 0;
    const verification = stats.verification_required ?? 0;
    const limited = stats.limited ?? 0;
    const parts = [`账号 ${total}`, `可用 ${available}`];
    if (verification) parts.push(`需验证 ${verification}`);
    if (limited) parts.push(`限流 ${limited}`);
    return parts.join('，');
  }

  function syncChatgptPoolRefreshBusyButtons() {
    const scope = els.deskSettingsBody;
    if (!scope) return;
    const busy = Boolean(chatgptPoolRefreshBusy);
    scope.querySelectorAll('[data-chatgpt-pool-account-refresh], [data-chatgpt-pool-refresh-all]').forEach(button => {
      if (!(button instanceof HTMLButtonElement)) return;
      if (busy) {
        if (!button.dataset.poolBusyOriginalTitle) {
          button.dataset.poolBusyOriginalTitle = button.getAttribute('title') || '';
        }
        button.disabled = true;
        button.setAttribute('aria-disabled', 'true');
        button.classList.add('is-pool-busy');
        if (!button.classList.contains('is-loading')) {
          button.setAttribute('title', '正在刷新 AT，完成后可用');
        }
        return;
      }
      button.classList.remove('is-pool-busy');
      button.removeAttribute('aria-disabled');
      if (!button.classList.contains('is-loading')) {
        button.disabled = false;
        const originalTitle = button.dataset.poolBusyOriginalTitle || '';
        if (originalTitle) {
          button.setAttribute('title', originalTitle);
        } else {
          button.removeAttribute('title');
        }
      }
      delete button.dataset.poolBusyOriginalTitle;
    });
  }

  function setChatgptPoolRefreshBusy(busy) {
    chatgptPoolRefreshBusy = Boolean(busy);
    syncChatgptPoolRefreshBusyButtons();
  }

  function setButtonWorking(button, working, options = {}) {
    if (!button) return;
    if (working) {
      button.dataset.originalHtml = button.innerHTML;
      button.dataset.originalTitle = button.getAttribute('title') || '';
      button.style.minWidth = `${Math.ceil(button.getBoundingClientRect().width || button.offsetWidth || 0)}px`;
      button.classList.add('is-pressed');
      window.setTimeout(() => button.classList.remove('is-pressed'), 140);
      button.classList.add('is-loading');
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      if (options.loadingText) {
        button.textContent = options.loadingText;
      }
      if (options.loadingTitle) {
        button.setAttribute('title', options.loadingTitle);
      }
      return;
    }
    button.classList.remove('is-loading');
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (button.dataset.originalTitle) {
      button.setAttribute('title', button.dataset.originalTitle);
    }
    if (button.dataset.originalHtml) {
      button.innerHTML = button.dataset.originalHtml;
    }
    button.style.minWidth = '';
    delete button.dataset.originalHtml;
    delete button.dataset.originalTitle;
  }

  async function runButtonAction(button, action, options = {}) {
    if (!button || button.disabled) return;
    setButtonWorking(button, true, options);
    try {
      const result = await action();
      if (result === false) {
        if (button.isConnected) {
          setButtonWorking(button, false);
        }
        return result;
      }
      if (button.isConnected && options.doneText) {
        const originalHtml = button.dataset.originalHtml || button.innerHTML;
        const originalTitle = button.dataset.originalTitle || button.getAttribute('title') || '';
        button.classList.remove('is-loading');
        button.classList.add('is-done');
        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.textContent = options.doneText;
        window.setTimeout(() => {
          if (!button.isConnected) return;
          button.classList.remove('is-done');
          button.innerHTML = originalHtml;
          if (originalTitle) {
            button.setAttribute('title', originalTitle);
          } else {
            button.removeAttribute('title');
          }
          button.style.minWidth = '';
          delete button.dataset.originalHtml;
          delete button.dataset.originalTitle;
        }, 650);
      } else if (button.isConnected) {
        setButtonWorking(button, false);
      }
      if (options.successMessage) {
        window.DesktopResults?.showTransientMessage?.(options.successMessage, 'success');
      }
      return result;
    } catch (error) {
      if (button.isConnected) {
        setButtonWorking(button, false);
      }
      showSettingsFeedback(error, options.errorMessage || '设置操作失败');
      return undefined;
    }
  }

  async function refresh() {
    if (!window.DesktopApi?.getSystemDiagnostics) {
      throw new Error('诊断 API 未加载');
    }
    renderLoading();
    const [data, systemSettings, promptConfig, gptModels] = await Promise.all([
      window.DesktopApi.getSystemDiagnostics(),
      window.DesktopApi.getSystemSettings ? window.DesktopApi.getSystemSettings().catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getPromptConfig ? window.DesktopApi.getPromptConfig().catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getGptModels ? window.DesktopApi.getGptModels().catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null)
    ]);
    lastDiagnostics = data;
    lastSystemSettings = systemSettings?.ok ? systemSettings : null;
    lastPromptConfig = promptConfig?.ok ? promptConfig : null;
    lastGptModelCatalog = gptModels?.ok ? gptModels : lastGptModelCatalog;
    if (lastGptModelCatalog) window.DesktopCanvas?.applyGptModelCatalog?.(lastGptModelCatalog);
    renderDiagnostics(data);
    return data;
  }

  async function refreshGptGenerationModels() {
    if (!window.DesktopApi?.getGptModels) throw new Error('GPT 模型目录 API 未加载');
    const payload = await window.DesktopApi.getGptModels(true);
    lastGptModelCatalog = payload;
    window.DesktopCanvas?.applyGptModelCatalog?.(payload);
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    return payload;
  }

  async function reloadPromptModels(provider) {
    if (!window.DesktopApi?.getPromptConfig) return;
    const payload = await window.DesktopApi.getPromptConfig(provider || '');
    lastPromptConfig = payload;
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
  }

  function collectPromptConfigForm() {
    const fields = {};
    els.deskSettingsBody?.querySelectorAll('[data-prompt-config-field]').forEach(input => {
      fields[input.dataset.promptConfigField] = input.value;
    });
    return fields;
  }

  async function savePromptConfig() {
    if (!window.DesktopApi?.savePromptConfig) throw new Error('润色配置 API 未加载');
    const payload = collectPromptConfigForm();
    const result = await window.DesktopApi.savePromptConfig(payload);
    lastPromptConfig = result;
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    window.DesktopResults?.showTransientMessage?.('润色配置已保存。', 'success');
  }

  function collectGptProviderForm() {
    const fields = {};
    els.deskSettingsBody?.querySelectorAll('[data-gpt-provider-field]').forEach(input => {
      fields[input.dataset.gptProviderField] = input.value;
    });
    return fields;
  }

  async function saveGptProviderConfig() {
    if (!window.DesktopApi?.saveGptConfig) throw new Error('GPT 配置 API 未加载');
    await window.DesktopApi.saveGptConfig(collectGptProviderForm());
    await refresh();
    window.DesktopResults?.showTransientMessage?.('GPT Provider 配置已保存。', 'success');
  }

  function setDeepValue(root, path, value) {
    const parts = String(path || '').split('.').filter(Boolean);
    if (!parts.length) return;
    let cursor = root;
    parts.slice(0, -1).forEach(part => {
      if (!cursor[part] || typeof cursor[part] !== 'object') cursor[part] = {};
      cursor = cursor[part];
    });
    cursor[parts[parts.length - 1]] = value;
  }

  function renderSettingsInfoContent(help) {
    if (!help) return '';
    return (help.sections || []).map(([title, items]) => `
      <section class="desk-settings-info-tip__section">
        <h4>${escapeHtml(title)}</h4>
        <ul>
          ${(items || []).map(item => `<li>${escapeHtml(item)}</li>`).join('')}
        </ul>
      </section>
    `).join('');
  }

  function updateSettingsInfoButton() {
    const button = els.deskSettingsInfoBtn;
    if (!button) return;
    const hasHelp = Boolean(SETTINGS_TAB_HELP[activeTab]);
    button.hidden = !hasHelp;
    button.setAttribute('aria-expanded', settingsInfoTipOpen && hasHelp ? 'true' : 'false');
    if (!hasHelp) closeSettingsInfoTip();
  }

  function updateSettingsInfoTipPosition() {
    const panel = els.deskSettingsInfoTip;
    if (!panel || panel.hidden) return;
    const settingsRect = els.deskSettingsPanel?.getBoundingClientRect?.();
    if (!settingsRect) return;
    const gap = 4;
    const viewportPadding = 10;
    const width = Math.min(250, Math.max(220, window.innerWidth - settingsRect.right - gap - viewportPadding));
    const left = Math.min(
      window.innerWidth - width - viewportPadding,
      Math.round(settingsRect.right + gap)
    );
    const top = Math.max(viewportPadding, Math.round(settingsRect.top));
    const height = Math.min(
      Math.round(settingsRect.height),
      Math.max(220, window.innerHeight - top - viewportPadding)
    );
    panel.dataset.placement = 'drawer';
    panel.dataset.positionVersion = 'settings-help3';
    panel.style.left = `${Math.round(left)}px`;
    panel.style.right = 'auto';
    panel.style.top = `${Math.round(top)}px`;
    panel.style.bottom = 'auto';
    panel.style.width = `${Math.round(width)}px`;
    panel.style.height = `${Math.round(height)}px`;
  }

  function renderSettingsInfoTip() {
    const panel = els.deskSettingsInfoTip;
    const help = SETTINGS_TAB_HELP[activeTab];
    if (!panel || !help) return;
    if (els.deskSettingsInfoTipTitle) els.deskSettingsInfoTipTitle.textContent = help.title || '配置说明';
    if (els.deskSettingsInfoTipSubtitle) els.deskSettingsInfoTipSubtitle.textContent = help.subtitle || '当前页';
    if (els.deskSettingsInfoTipSummary) els.deskSettingsInfoTipSummary.textContent = help.summary || '';
    if (els.deskSettingsInfoTipContent) els.deskSettingsInfoTipContent.innerHTML = renderSettingsInfoContent(help);
    updateSettingsInfoTipPosition();
    window.requestAnimationFrame(updateSettingsInfoTipPosition);
  }

  function openSettingsInfoTip() {
    const panel = els.deskSettingsInfoTip;
    if (!panel || !SETTINGS_TAB_HELP[activeTab]) return;
    settingsInfoTipOpen = true;
    panel.hidden = false;
    els.deskSettingsInfoBtn?.setAttribute('aria-expanded', 'true');
    renderSettingsInfoTip();
    window.requestAnimationFrame(() => panel.classList.add('is-open'));
  }

  function closeSettingsInfoTip() {
    const panel = els.deskSettingsInfoTip;
    settingsInfoTipOpen = false;
    if (panel) {
      panel.classList.remove('is-open');
      window.setTimeout(() => {
        if (!settingsInfoTipOpen && panel) panel.hidden = true;
      }, 220);
    }
    els.deskSettingsInfoBtn?.setAttribute('aria-expanded', 'false');
  }

  function toggleSettingsInfoTip() {
    if (settingsInfoTipOpen) closeSettingsInfoTip();
    else openSettingsInfoTip();
  }

  function payloadForClearingSecret(field) {
    const payload = {};
    const parts = String(field || '').split('.').filter(Boolean);
    const key = parts.pop();
    if (!key) return payload;
    setDeepValue(payload, [...parts, `clear_${key}`].join('.'), true);
    return payload;
  }

  function collectSystemSettingsForm(card) {
    const payload = {};
    card?.querySelectorAll('[data-system-setting-field]').forEach(input => {
      const field = input.dataset.systemSettingField;
      if (!field) return;
      let value = input.type === 'checkbox' ? input.checked : input.value;
      if (input.type === 'number' && value !== '') value = Number(value);
      if (input.type === 'password' && !String(value || '').trim()) return;
      setDeepValue(payload, field, value);
    });
    return payload;
  }

  async function saveSystemSettings(button) {
    if (!window.DesktopApi?.saveSystemSettings) throw new Error('系统设置 API 未加载');
    const card = button?.closest('[data-system-settings-card]');
    const payload = collectSystemSettingsForm(card);
    await window.DesktopApi.saveSystemSettings(payload);
    await refresh();
    window.DesktopResults?.showTransientMessage?.('系统配置已保存。', 'success');
  }

  async function clearSystemSecret(button) {
    if (!window.DesktopApi?.saveSystemSettings) throw new Error('系统设置 API 未加载');
    const field = button?.dataset?.systemSecretClearField || '';
    const label = button?.dataset?.systemSecretClearLabel || '密钥';
    if (!field) throw new Error('缺少清除字段');
    const labelPrefix = /^[A-Za-z0-9]/.test(label) ? ' ' : '';
    const message = `确认清空已保存的${labelPrefix}${label}？`;
    if (window.confirm && !window.confirm(message)) return false;
    const payload = payloadForClearingSecret(field);
    await window.DesktopApi.saveSystemSettings(payload);
    await refresh();
    window.DesktopResults?.showTransientMessage?.(`${label} 已清除。`, 'success');
    return true;
  }

  async function loadChatgptPoolAccounts(options = {}) {
    if (!window.DesktopApi?.getChatgptPoolAccounts) throw new Error('账号池 API 未加载');
    const userAction = Boolean(options?.userAction);
    const preserveScroll = Boolean(options?.preserveScroll);
    const scrollTop = preserveScroll ? (els.deskSettingsBody?.scrollTop || 0) : 0;
    if (userAction) setChatgptPoolActivity('正在读取账号列表...', 'working');
    try {
      lastChatgptPoolAccounts = await window.DesktopApi.getChatgptPoolAccounts();
      if (lastDiagnostics) {
        lastDiagnostics = {
          ...lastDiagnostics,
          chatgpt_pool: {
            ...(lastDiagnostics.chatgpt_pool || {}),
            online: true,
            health_error: '',
            stats: lastChatgptPoolAccounts?.stats || lastDiagnostics.chatgpt_pool?.stats || {}
          }
        };
        renderDiagnostics(lastDiagnostics);
        if (preserveScroll && els.deskSettingsBody) els.deskSettingsBody.scrollTop = scrollTop;
      }
      if (userAction) {
        setChatgptPoolActivity(`账号列表已更新：${chatgptPoolStatsLabel(lastChatgptPoolAccounts)}`, 'success');
      }
    } catch (error) {
      if (userAction) setChatgptPoolActivity(`账号列表读取失败：${error?.message || error}`, 'error');
      throw error;
    }
    return lastChatgptPoolAccounts;
  }

  async function refreshChatgptPoolStatus() {
    if (!window.DesktopApi?.getSystemDiagnostics) return;
    lastDiagnostics = await window.DesktopApi.getSystemDiagnostics();
    if (activeTab === 'chatgpt-pool') {
      await loadChatgptPoolAccounts().catch(() => null);
    } else {
      renderDiagnostics(lastDiagnostics);
    }
  }

  async function startChatgptPoolOAuth() {
    if (!window.DesktopApi?.startChatgptPoolOAuth) throw new Error('账号池 OAuth API 未加载');
    const emailHint = els.deskSettingsBody?.querySelector('[data-chatgpt-pool-email-hint]')?.value || '';
    setChatgptPoolOAuthActivity('正在创建账号池 OAuth 授权会话...', 'working');
    try {
      const result = await window.DesktopApi.startChatgptPoolOAuth({ email_hint: emailHint, force_reauth: true });
      chatgptPoolOAuthSessionId = String(result.session_id || '').trim();
      chatgptPoolOAuthAuthorizeUrl = String(result.authorize_url || '').trim();
      if (!chatgptPoolOAuthSessionId || !chatgptPoolOAuthAuthorizeUrl) {
        throw new Error('账号池没有返回有效的 OAuth 授权会话。');
      }
      const sessionInput = els.deskSettingsBody?.querySelector('[data-chatgpt-pool-session-id]');
      const urlInput = els.deskSettingsBody?.querySelector('[data-chatgpt-pool-authorize-url]');
      const callbackInput = els.deskSettingsBody?.querySelector('[data-chatgpt-pool-callback]');
      if (sessionInput) sessionInput.value = chatgptPoolOAuthSessionId;
      if (urlInput) urlInput.value = chatgptPoolOAuthAuthorizeUrl;
      if (callbackInput) callbackInput.value = '';

      let opened = false;
      try {
        if (window.DesktopApi?.openChatgptPoolOAuthClean) {
          await window.DesktopApi.openChatgptPoolOAuthClean({ authorize_url: chatgptPoolOAuthAuthorizeUrl });
        } else {
          window.open(chatgptPoolOAuthAuthorizeUrl, '_blank', 'noopener,noreferrer');
        }
        opened = true;
        setChatgptPoolOAuthActivity('授权页面已打开；登录后请粘贴最终回调 URL，再点击“完成授权”。', 'working');
      } catch (openError) {
        setChatgptPoolOAuthActivity(
          `授权链接已生成，但自动打开失败：${openError.message || '请复制上方链接手动打开'}`,
          'warn'
        );
      }
      window.DesktopResults?.showTransientMessage?.(
        opened ? '账号池授权已生成并打开。' : '账号池授权链接已生成，请手动打开上方链接。',
        opened ? 'success' : 'warning'
      );
      return result;
    } catch (error) {
      setChatgptPoolOAuthActivity(error.message || '账号池 OAuth 授权链接生成失败', 'error');
      throw error;
    }
  }

  function chatgptPoolCallbackHasState(callback) {
    try {
      return Boolean(new URL(String(callback || '').trim()).searchParams.get('state'));
    } catch (_error) {
      return false;
    }
  }

  async function finishChatgptPoolOAuth() {
    if (!window.DesktopApi?.finishChatgptPoolOAuth) throw new Error('账号池 OAuth API 未加载');
    const sessionId = String(
      els.deskSettingsBody?.querySelector('[data-chatgpt-pool-session-id]')?.value
      || chatgptPoolOAuthSessionId
      || ''
    ).trim();
    const callback = String(els.deskSettingsBody?.querySelector('[data-chatgpt-pool-callback]')?.value || '').trim();
    if (!callback) {
      const error = new Error('请先粘贴授权完成后的回调 URL 或 Code。');
      setChatgptPoolOAuthActivity(error.message, 'warn');
      throw error;
    }
    if (!sessionId && !chatgptPoolCallbackHasState(callback)) {
      const error = new Error('当前授权会话已丢失，请重新生成授权；完整回调 URL 可直接重试。');
      setChatgptPoolOAuthActivity(error.message, 'warn');
      throw error;
    }

    setChatgptPoolOAuthActivity('正在兑换 OAuth token 并写入账号池...', 'working');
    try {
      const result = await window.DesktopApi.finishChatgptPoolOAuth({ session_id: sessionId, callback });
      if (result?.pending) {
        setChatgptPoolOAuthActivity('OAuth token 正在兑换，请稍后再次点击“完成授权”。', 'working');
        return false;
      }
      chatgptPoolOAuthSessionId = '';
      chatgptPoolOAuthAuthorizeUrl = '';
      setChatgptPoolOAuthActivity('账号池 OAuth 授权完成，账号已添加。', 'success');
      try {
        await loadChatgptPoolAccounts({ preserveScroll: true });
      } catch (refreshError) {
        setChatgptPoolOAuthActivity(
          `授权已完成，但账号列表刷新失败：${refreshError.message || '网络错误'}`,
          'warn'
        );
      }
      window.DesktopResults?.showTransientMessage?.('账号授权已写入账号池。', 'success');
      return true;
    } catch (error) {
      setChatgptPoolOAuthActivity(error.message || '账号池 OAuth 授权完成失败', 'error');
      throw error;
    }
  }

  function parseChatgptPoolImportPayload() {
    const raw = els.deskSettingsBody?.querySelector('[data-chatgpt-pool-import-json]')?.value || '';
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return { accounts: parsed };
    if (parsed && typeof parsed === 'object') return parsed.accounts ? parsed : { ...parsed };
    throw new Error('Auth JSON 格式错误');
  }

  async function importChatgptPoolAccounts() {
    if (!window.DesktopApi?.importChatgptPoolAccounts) throw new Error('账号池导入 API 未加载');
    await window.DesktopApi.importChatgptPoolAccounts(parseChatgptPoolImportPayload());
    await refreshChatgptPoolStatus();
    window.DesktopResults?.showTransientMessage?.('账号已导入账号池。', 'success');
  }

  async function importLocalChatgptPoolAuth() {
    if (!window.DesktopApi?.importLocalChatgptPoolAuth) throw new Error('本机 Auth 导入 API 未加载');
    await window.DesktopApi.importLocalChatgptPoolAuth({});
    await refreshChatgptPoolStatus();
    window.DesktopResults?.showTransientMessage?.('本机 Codex Auth 已导入账号池。', 'success');
  }

  async function refreshChatgptPoolAccounts(force = true, options = {}) {
    if (!window.DesktopApi?.refreshChatgptPoolAccounts) throw new Error('账号池刷新 API 未加载');
    const userAction = options?.userAction !== false;
    setChatgptPoolRefreshBusy(true);
    if (userAction) {
      setChatgptPoolActivity('正在刷新 Access Token，多个账号可能需要 30-60 秒...', 'working');
    }
    try {
      const result = await window.DesktopApi.refreshChatgptPoolAccounts({ force });
      await refreshChatgptPoolStatus();
      if (userAction) {
        const refreshed = Number(result?.refreshed ?? 0);
        const errors = Array.isArray(result?.errors) ? result.errors.length : 0;
        const tone = errors ? 'warn' : 'success';
        const detail = errors
          ? `AT 刷新完成：刷新 ${refreshed} 个，失败 ${errors} 个；${chatgptPoolStatsLabel(lastChatgptPoolAccounts)}`
          : `AT 刷新完成：刷新 ${refreshed} 个；${chatgptPoolStatsLabel(lastChatgptPoolAccounts)}`;
        setChatgptPoolActivity(detail, tone);
      }
      return result;
    } catch (error) {
      if (userAction) setChatgptPoolActivity(`AT 刷新失败：${error?.message || error}`, 'error');
      throw error;
    } finally {
      setChatgptPoolRefreshBusy(false);
    }
  }

  async function updateChatgptPoolAccount(accountId, status) {
    if (!window.DesktopApi?.updateChatgptPoolAccount) throw new Error('账号池更新 API 未加载');
    if (!accountId) throw new Error('缺少账号 ID');
    await window.DesktopApi.updateChatgptPoolAccount({ account_id: accountId, status });
    await refreshChatgptPoolStatus();
    window.DesktopResults?.showTransientMessage?.('账号状态已更新。', 'success');
  }

  async function verifyChatgptPoolAccount(accountId) {
    if (!window.DesktopApi?.startChatgptPoolAccountVerification) throw new Error('账号池验证 API 未加载');
    if (!window.DesktopApi?.completeChatgptPoolAccountVerification) throw new Error('账号池验证完成 API 未加载');
    if (!accountId) throw new Error('缺少账号 ID');
    const result = await window.DesktopApi.startChatgptPoolAccountVerification({ account_id: accountId });
    const email = result?.email ? `（${result.email}）` : '';
    window.DesktopResults?.showTransientMessage?.(`已打开 ChatGPT 验证窗口${email}。`, 'success');
    const confirmText = `已打开 ChatGPT 验证窗口${email}。\n\n请在新打开的 Chrome 窗口里登录对应账号，完成 Turnstile / 人机验证，并确认 ChatGPT 页面可以正常进入。\n\n完成后回到这里点击“确定”，我会把该账号恢复为正常，后续请求使用轻量 HTTP 链路重新尝试。尚未完成请点“取消”。`;
    if (typeof window.confirm !== 'function' || !window.confirm(confirmText)) {
      await refreshChatgptPoolStatus();
      return false;
    }
    await window.DesktopApi.completeChatgptPoolAccountVerification({
      account_id: accountId,
      debug_port: result?.debug_port || result?.debugPort || ''
    });
    await refreshChatgptPoolStatus();
    window.DesktopResults?.showTransientMessage?.('验证完成，账号已恢复为正常。', 'success');
    return true;
  }

  async function deleteChatgptPoolAccount(accountId) {
    if (!window.DesktopApi?.deleteChatgptPoolAccounts) throw new Error('账号池删除 API 未加载');
    if (!accountId) throw new Error('缺少账号 ID');
    if (window.confirm && !window.confirm('确定删除这个账号？')) return false;
    await window.DesktopApi.deleteChatgptPoolAccounts({ account_id: accountId });
    await refreshChatgptPoolStatus();
    window.DesktopResults?.showTransientMessage?.('账号已删除。', 'success');
    return true;
  }

  async function refreshManagedCodexOAuthStatusView() {
    if (!window.DesktopApi?.getManagedCodexOAuthStatus) throw new Error('托管 Codex OAuth 状态 API 未加载');
    const payload = await window.DesktopApi.getManagedCodexOAuthStatus();
    const managed = payload?.managed_codex_oauth || payload || {};
    if (lastDiagnostics) {
      const scrollTop = els.deskSettingsBody?.scrollTop || 0;
      lastDiagnostics = { ...lastDiagnostics, managed_codex_oauth: managed };
      renderDiagnostics(lastDiagnostics);
      if (els.deskSettingsBody) els.deskSettingsBody.scrollTop = scrollTop;
    }
    return managed;
  }

  function stopManagedCodexOAuthPolling({ clearSession = false } = {}) {
    if (managedCodexOAuthPollTimer) window.clearTimeout(managedCodexOAuthPollTimer);
    managedCodexOAuthPollTimer = null;
    managedCodexOAuthPollDeadline = 0;
    if (clearSession) {
      managedCodexOAuthSessionId = '';
      managedCodexOAuthAuthorizeUrl = '';
    }
  }

  function scheduleManagedCodexOAuthPoll(sessionId, delay = MANAGED_CODEX_OAUTH_POLL_INTERVAL_MS) {
    if (!sessionId || sessionId !== managedCodexOAuthSessionId) return;
    if (managedCodexOAuthPollDeadline && Date.now() >= managedCodexOAuthPollDeadline) {
      stopManagedCodexOAuthPolling();
      setManagedCodexOAuthActivity('授权会话等待超时，可重新打开授权或粘贴回调 URL。', 'warn');
      return;
    }
    if (managedCodexOAuthPollTimer) window.clearTimeout(managedCodexOAuthPollTimer);
    managedCodexOAuthPollTimer = window.setTimeout(() => {
      managedCodexOAuthPollTimer = null;
      pollManagedCodexOAuthSession(sessionId);
    }, delay);
  }

  async function applyManagedCodexOAuthCompletion(result, requestedSessionId = '') {
    const completedSessionId = String(result?.session_id || requestedSessionId || '').trim();
    const activeSessionCompleted = !managedCodexOAuthSessionId
      || !completedSessionId
      || completedSessionId === managedCodexOAuthSessionId;
    if (activeSessionCompleted) {
      stopManagedCodexOAuthPolling({ clearSession: true });
      setManagedCodexOAuthActivity('Codex OAuth 授权完成，账号已添加并设为当前账号。', 'success');
    } else {
      setManagedCodexOAuthActivity('另一个 Codex OAuth 授权已完成，当前会话仍在等待。', 'success');
    }
    try {
      await refreshManagedCodexOAuthStatusView();
    } catch (error) {
      setManagedCodexOAuthActivity(
        `授权已完成，但账号状态刷新失败：${error.message || '网络错误'}`,
        'warn'
      );
    }
    if (!activeSessionCompleted) scheduleManagedCodexOAuthPoll(managedCodexOAuthSessionId);
    refreshGptGenerationModels().catch(() => null);
    window.DesktopResults?.showTransientMessage?.('Codex OAuth 已写入托管账号。', 'success');
    return true;
  }

  async function checkManagedCodexOAuthSession(sessionId, callback = '') {
    const result = await window.DesktopApi.finishManagedCodexOAuth({
      session_id: sessionId,
      callback
    });
    if (result?.pending) {
      setManagedCodexOAuthActivity(
        result.status === 'exchanging'
          ? '正在换取 Codex OAuth token...'
          : '等待浏览器完成登录并返回授权结果...',
        'working'
      );
      return false;
    }
    if (result?.ok === false) {
      const error = new Error(result.error || 'Codex OAuth 授权失败');
      error.oauthTerminal = true;
      throw error;
    }
    return applyManagedCodexOAuthCompletion(result, sessionId);
  }

  async function pollManagedCodexOAuthSession(sessionId) {
    if (!sessionId || sessionId !== managedCodexOAuthSessionId) return;
    try {
      const completed = await checkManagedCodexOAuthSession(sessionId);
      if (!completed) scheduleManagedCodexOAuthPoll(sessionId);
    } catch (error) {
      if (sessionId !== managedCodexOAuthSessionId) return;
      if (error?.oauthTerminal) {
        stopManagedCodexOAuthPolling();
        setManagedCodexOAuthActivity(error.message || 'Codex OAuth 授权失败', 'error');
        return;
      }
      setManagedCodexOAuthActivity(`授权状态检查失败，正在重试：${error.message || '网络错误'}`, 'warn');
      scheduleManagedCodexOAuthPoll(sessionId, 3000);
    }
  }

  async function startManagedCodexOAuth() {
    if (!window.DesktopApi?.startManagedCodexOAuth) throw new Error('托管 Codex OAuth API 未加载');
    const emailHint = els.deskSettingsBody?.querySelector('[data-managed-codex-email-hint]')?.value || '';
    setManagedCodexOAuthActivity('正在创建 Codex OAuth 授权会话...', 'working');
    try {
      const result = await window.DesktopApi.startManagedCodexOAuth({
        email_hint: emailHint,
        force_reauth: true,
        open_browser: true
      });
      stopManagedCodexOAuthPolling();
      managedCodexOAuthSessionId = String(result.session_id || '').trim();
      managedCodexOAuthAuthorizeUrl = String(result.authorize_url || '').trim();
      managedCodexOAuthPollDeadline = Date.now() + MANAGED_CODEX_OAUTH_POLL_TIMEOUT_MS;
      const sessionInput = els.deskSettingsBody?.querySelector('[data-managed-codex-session-id]');
      const urlInput = els.deskSettingsBody?.querySelector('[data-managed-codex-authorize-url]');
      const callbackInput = els.deskSettingsBody?.querySelector('[data-managed-codex-callback]');
      if (sessionInput) sessionInput.value = managedCodexOAuthSessionId;
      if (urlInput) urlInput.value = managedCodexOAuthAuthorizeUrl;
      if (callbackInput) callbackInput.value = '';
      setManagedCodexOAuthActivity('授权页面已打开，等待浏览器回调...', 'working');
      scheduleManagedCodexOAuthPoll(managedCodexOAuthSessionId, 800);
      window.DesktopResults?.showTransientMessage?.('Codex OAuth 授权已打开。', 'success');
      return result;
    } catch (error) {
      setManagedCodexOAuthActivity(error.message || 'Codex OAuth 授权打开失败', 'error');
      throw error;
    }
  }

  async function finishManagedCodexOAuth() {
    if (!window.DesktopApi?.finishManagedCodexOAuth) throw new Error('托管 Codex OAuth API 未加载');
    const sessionId = String(
      els.deskSettingsBody?.querySelector('[data-managed-codex-session-id]')?.value
      || managedCodexOAuthSessionId
      || ''
    ).trim();
    const callback = String(els.deskSettingsBody?.querySelector('[data-managed-codex-callback]')?.value || '').trim();
    if (!sessionId && !callback) {
      const error = new Error('请先点击“打开授权”生成授权会话。');
      setManagedCodexOAuthActivity(error.message, 'warn');
      throw error;
    }
    setManagedCodexOAuthActivity('正在确认 Codex OAuth 授权结果...', 'working');
    try {
      const completed = await checkManagedCodexOAuthSession(sessionId, callback);
      if (!completed) {
        setManagedCodexOAuthActivity('尚未收到浏览器回调，请先在授权页完成登录。', 'warn');
        if (sessionId === managedCodexOAuthSessionId) scheduleManagedCodexOAuthPoll(sessionId);
        return false;
      }
      return true;
    } catch (error) {
      setManagedCodexOAuthActivity(error.message || 'Codex OAuth 授权完成失败', 'error');
      throw error;
    }
  }

  async function refreshManagedCodexOAuth(accountId = '', all = false) {
    if (!window.DesktopApi?.refreshManagedCodexOAuth) throw new Error('托管 Codex OAuth API 未加载');
    await window.DesktopApi.refreshManagedCodexOAuth({ account_id: accountId, all });
    await refresh();
    window.DesktopResults?.showTransientMessage?.('托管 Codex AT 刷新完成。', 'success');
  }

  function parseManagedCodexImportPayload() {
    const raw = els.deskSettingsBody?.querySelector('[data-managed-codex-import-json]')?.value || '';
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return { accounts: parsed };
    if (parsed && typeof parsed === 'object') return parsed.accounts ? parsed : { ...parsed };
    throw new Error('Auth JSON 格式错误');
  }

  async function importManagedCodexOAuth() {
    if (!window.DesktopApi?.importManagedCodexOAuth) throw new Error('托管 Codex OAuth 导入 API 未加载');
    await window.DesktopApi.importManagedCodexOAuth(parseManagedCodexImportPayload());
    await refresh();
    window.DesktopResults?.showTransientMessage?.('托管 Codex 账号已导入。', 'success');
  }

  async function selectManagedCodexAccount(accountId) {
    if (!window.DesktopApi?.selectManagedCodexOAuthAccount) throw new Error('托管 Codex OAuth 选择 API 未加载');
    if (!accountId) throw new Error('缺少账号 ID');
    await window.DesktopApi.selectManagedCodexOAuthAccount({ account_id: accountId });
    await refresh();
    window.DesktopResults?.showTransientMessage?.('已设为当前托管 Codex 账号。', 'success');
  }

  async function updateManagedCodexAccount(accountId, disabled) {
    if (!window.DesktopApi?.updateManagedCodexOAuthAccount) throw new Error('托管 Codex OAuth 更新 API 未加载');
    if (!accountId) throw new Error('缺少账号 ID');
    await window.DesktopApi.updateManagedCodexOAuthAccount({ account_id: accountId, disabled });
    await refresh();
    window.DesktopResults?.showTransientMessage?.('托管 Codex 账号状态已更新。', 'success');
  }

  async function deleteManagedCodexAccount(accountId) {
    if (!window.DesktopApi?.deleteManagedCodexOAuthAccount) throw new Error('托管 Codex OAuth 删除 API 未加载');
    if (!accountId) throw new Error('缺少账号 ID');
    if (window.confirm && !window.confirm('确定删除这个托管 Codex 账号？')) return false;
    await window.DesktopApi.deleteManagedCodexOAuthAccount({ account_id: accountId });
    await refresh();
    window.DesktopResults?.showTransientMessage?.('托管 Codex 账号已删除。', 'success');
    return true;
  }

  async function logoutManagedCodexOAuth() {
    if (!window.DesktopApi?.logoutManagedCodexOAuth) throw new Error('托管 Codex OAuth API 未加载');
    if (window.confirm && !window.confirm('确定清空全部托管 Codex OAuth 账号？')) return false;
    await window.DesktopApi.logoutManagedCodexOAuth({ all: true });
    await refresh();
    window.DesktopResults?.showTransientMessage?.('托管 Codex OAuth 账号已清空。', 'success');
    return true;
  }

  async function open() {
    if (window.DesktopPromptLibrary?.close?.() === false) return false;
    els.deskSettingsPanel?.classList.add('is-open');
    els.deskSettingsPanel?.setAttribute('aria-hidden', 'false');
    document.body.classList.add('desk-settings-open');
    const gallery = document.getElementById('deskGalleryPanel');
    gallery?.classList.remove('is-open');
    gallery?.setAttribute('aria-hidden', 'true');
    try {
      if (!lastDiagnostics) {
        await refresh();
      } else {
        renderDiagnostics(lastDiagnostics);
      }
    } catch (error) {
      if (els.deskSettingsSummary) {
        els.deskSettingsSummary.innerHTML = '<span class="is-warn">诊断读取失败</span>';
      }
      if (els.deskSettingsBody) {
        els.deskSettingsBody.innerHTML = `<div class="desk-settings-empty">${escapeHtml(error.message || '诊断读取失败')}</div>`;
      }
      throw error;
    }
    return true;
  }

  function close() {
    els.deskSettingsPanel?.classList.remove('is-open');
    els.deskSettingsPanel?.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('desk-settings-open');
    closeSettingsInfoTip();
  }

  function updateTabs() {
    els.deskSettingsTabs?.querySelectorAll('[data-settings-tab]').forEach(button => {
      const active = button.dataset.settingsTab === activeTab;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    updateSettingsInfoButton();
    if (settingsInfoTipOpen) {
      if (SETTINGS_TAB_HELP[activeTab]) renderSettingsInfoTip();
      else closeSettingsInfoTip();
    }
  }

  function bindEvents() {
    els.deskSettingsCloseBtn?.addEventListener('click', close);
    els.deskSettingsInfoBtn?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      toggleSettingsInfoTip();
    });
    els.deskSettingsInfoTipClose?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      closeSettingsInfoTip();
      els.deskSettingsInfoBtn?.focus();
    });
    els.deskSettingsRefreshBtn?.addEventListener('click', event => {
      runButtonAction(event.currentTarget, refresh, {
        loadingTitle: '正在刷新诊断',
        successMessage: '设置状态已刷新。',
        errorMessage: '诊断读取失败'
      });
    });
    els.deskSettingsTabs?.addEventListener('click', event => {
      const button = event.target.closest('[data-settings-tab]');
      if (!button) return;
      event.stopPropagation();
      activeTab = button.dataset.settingsTab || 'status';
      if (activeTab === 'browser') {
        activeTab = 'status';
      }
      updateTabs();
      if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
      if (activeTab === 'chatgpt-pool') {
        loadChatgptPoolAccounts().catch(error => showSettingsFeedback(error, '账号池列表读取失败'));
      }
    });
    els.deskSettingsBody?.addEventListener('change', event => {
      const systemField = event.target.closest('[data-system-setting-field]');
      if (systemField?.dataset.systemSettingField === 'gpt_provider.image_main_model') {
        syncProviderReasoningField(systemField);
      }
      const field = event.target.closest('[data-prompt-config-field]');
      if (!field) return;
      if (field.dataset.promptConfigField === 'provider') {
        reloadPromptModels(field.value).catch(error => showSettingsFeedback(error, '模型列表读取失败'));
      }
    });
    els.deskSettingsBody?.addEventListener('click', event => {
      const refreshGenerationModels = event.target.closest('[data-gpt-generation-models-refresh]');
      if (refreshGenerationModels) {
        event.preventDefault();
        runButtonAction(refreshGenerationModels, refreshGptGenerationModels, {
          loadingText: '刷新中...',
          doneText: '已刷新',
          successMessage: '线路模型已刷新。',
          errorMessage: '线路模型刷新失败'
        });
        return;
      }
      const clearSecret = event.target.closest('[data-system-secret-clear-field]');
      if (clearSecret) {
        event.preventDefault();
        event.stopPropagation();
        runButtonAction(clearSecret, () => clearSystemSecret(clearSecret), {
          loadingText: '清除中...',
          doneText: '已清除',
          errorMessage: '密钥清除失败'
        });
        return;
      }
      const reload = event.target.closest('[data-prompt-config-reload]');
      if (reload) {
        event.preventDefault();
        runButtonAction(reload, () => reloadPromptModels(collectPromptConfigForm().provider), {
          loadingText: '刷新中...',
          doneText: '已刷新',
          successMessage: '模型列表已刷新。',
          errorMessage: '模型列表刷新失败'
        });
        return;
      }
      const save = event.target.closest('[data-prompt-config-save]');
      if (save) {
        event.preventDefault();
        runButtonAction(save, savePromptConfig, {
          loadingText: '保存中...',
          doneText: '已保存',
          errorMessage: '润色配置保存失败'
        });
        return;
      }
      const gptSave = event.target.closest('[data-gpt-provider-save]');
      if (gptSave) {
        event.preventDefault();
        runButtonAction(gptSave, saveGptProviderConfig, {
          loadingText: '保存中...',
          doneText: '已保存',
          errorMessage: 'GPT Provider 配置保存失败'
        });
        return;
      }
      const systemSave = event.target.closest('[data-system-settings-save]');
      if (systemSave) {
        event.preventDefault();
        runButtonAction(systemSave, () => saveSystemSettings(systemSave), {
          loadingText: '保存中...',
          doneText: '已保存',
          errorMessage: '系统配置保存失败'
        });
        return;
      }
      const managedCodexStart = event.target.closest('[data-managed-codex-oauth-start]');
      if (managedCodexStart) {
        event.preventDefault();
        runButtonAction(managedCodexStart, startManagedCodexOAuth, {
          loadingText: '打开中...',
          doneText: '已打开',
          errorMessage: 'Codex OAuth 授权打开失败'
        });
        return;
      }
      const managedCodexFinish = event.target.closest('[data-managed-codex-oauth-finish]');
      if (managedCodexFinish) {
        event.preventDefault();
        runButtonAction(managedCodexFinish, finishManagedCodexOAuth, {
          loadingText: '提交中...',
          doneText: '已完成',
          errorMessage: 'Codex OAuth 授权完成失败'
        });
        return;
      }
      const managedCodexRefresh = event.target.closest('[data-managed-codex-oauth-refresh]');
      if (managedCodexRefresh) {
        event.preventDefault();
        runButtonAction(managedCodexRefresh, refreshManagedCodexOAuth, {
          loadingText: '刷新中...',
          doneText: '已刷新',
          errorMessage: '托管 Codex AT 刷新失败'
        });
        return;
      }
      const managedCodexRefreshAll = event.target.closest('[data-managed-codex-oauth-refresh-all]');
      if (managedCodexRefreshAll) {
        event.preventDefault();
        runButtonAction(managedCodexRefreshAll, () => refreshManagedCodexOAuth('', true), {
          loadingText: '刷新中...',
          doneText: '已刷新',
          errorMessage: '托管 Codex 全部 AT 刷新失败'
        });
        return;
      }
      const managedCodexImport = event.target.closest('[data-managed-codex-import]');
      if (managedCodexImport) {
        event.preventDefault();
        runButtonAction(managedCodexImport, importManagedCodexOAuth, {
          loadingText: '导入中...',
          doneText: '已导入',
          errorMessage: '托管 Codex Auth JSON 导入失败'
        });
        return;
      }
      const managedCodexSelect = event.target.closest('[data-managed-codex-account-select]');
      if (managedCodexSelect) {
        event.preventDefault();
        runButtonAction(managedCodexSelect, () => selectManagedCodexAccount(managedCodexSelect.dataset.accountId), {
          loadingText: '切换中...',
          doneText: '已切换',
          errorMessage: '托管 Codex 当前账号切换失败'
        });
        return;
      }
      const managedCodexAccountRefresh = event.target.closest('[data-managed-codex-account-refresh]');
      if (managedCodexAccountRefresh) {
        event.preventDefault();
        runButtonAction(managedCodexAccountRefresh, () => refreshManagedCodexOAuth(managedCodexAccountRefresh.dataset.accountId, false), {
          loadingText: '刷新中...',
          doneText: '已刷新',
          errorMessage: '托管 Codex 账号 AT 刷新失败'
        });
        return;
      }
      const managedCodexAccountToggle = event.target.closest('[data-managed-codex-account-toggle]');
      if (managedCodexAccountToggle) {
        event.preventDefault();
        runButtonAction(managedCodexAccountToggle, () => updateManagedCodexAccount(
          managedCodexAccountToggle.dataset.accountId,
          managedCodexAccountToggle.dataset.disabled === 'true'
        ), {
          loadingText: '处理中...',
          doneText: '已更新',
          errorMessage: '托管 Codex 账号状态更新失败'
        });
        return;
      }
      const managedCodexAccountDelete = event.target.closest('[data-managed-codex-account-delete]');
      if (managedCodexAccountDelete) {
        event.preventDefault();
        runButtonAction(managedCodexAccountDelete, () => deleteManagedCodexAccount(managedCodexAccountDelete.dataset.accountId), {
          loadingText: '删除中...',
          doneText: '已删除',
          errorMessage: '托管 Codex 账号删除失败'
        });
        return;
      }
      const managedCodexLogout = event.target.closest('[data-managed-codex-oauth-logout]');
      if (managedCodexLogout) {
        event.preventDefault();
        runButtonAction(managedCodexLogout, logoutManagedCodexOAuth, {
          loadingText: '清空中...',
          doneText: '已清空',
          errorMessage: '托管 Codex OAuth 清空失败'
        });
        return;
      }
      const poolLoad = event.target.closest('[data-chatgpt-pool-load-accounts]');
      if (poolLoad) {
        event.preventDefault();
        runButtonAction(poolLoad, () => loadChatgptPoolAccounts({ userAction: true }), {
          loadingText: '读取中...',
          doneText: '已读取',
          successMessage: '账号列表已更新。',
          errorMessage: '账号池列表读取失败'
        });
        return;
      }
      const poolOAuthStart = event.target.closest('[data-chatgpt-pool-oauth-start]');
      if (poolOAuthStart) {
        event.preventDefault();
        runButtonAction(poolOAuthStart, startChatgptPoolOAuth, {
          loadingText: '生成中...',
          doneText: '已生成',
          errorMessage: '授权链接生成失败'
        });
        return;
      }
      const poolOAuthFinish = event.target.closest('[data-chatgpt-pool-oauth-finish]');
      if (poolOAuthFinish) {
        event.preventDefault();
        runButtonAction(poolOAuthFinish, finishChatgptPoolOAuth, {
          loadingText: '提交中...',
          doneText: '已完成',
          errorMessage: '账号授权完成失败'
        });
        return;
      }
      const poolImport = event.target.closest('[data-chatgpt-pool-import]');
      if (poolImport) {
        event.preventDefault();
        runButtonAction(poolImport, importChatgptPoolAccounts, {
          loadingText: '导入中...',
          doneText: '已导入',
          errorMessage: '账号导入失败'
        });
        return;
      }
      const poolImportLocal = event.target.closest('[data-chatgpt-pool-import-local-auth]');
      if (poolImportLocal) {
        event.preventDefault();
        runButtonAction(poolImportLocal, importLocalChatgptPoolAuth, {
          loadingText: '导入中...',
          doneText: '已导入',
          errorMessage: '本机 Auth 导入失败'
        });
        return;
      }
      const poolRefreshAll = event.target.closest('[data-chatgpt-pool-refresh-all]');
      if (poolRefreshAll) {
        event.preventDefault();
        runButtonAction(poolRefreshAll, () => refreshChatgptPoolAccounts(true, { userAction: true }), {
          loadingText: '刷新中...',
          loadingTitle: '正在刷新 AT，多个账号可能需要 30-60 秒',
          doneText: '已刷新',
          errorMessage: '账号池刷新失败'
        });
        return;
      }
      const poolRefresh = event.target.closest('[data-chatgpt-pool-account-refresh]');
      if (poolRefresh) {
        event.preventDefault();
        runButtonAction(poolRefresh, () => refreshChatgptPoolAccounts(true, { userAction: true }), {
          loadingText: '刷新中...',
          loadingTitle: '正在刷新 AT，多个账号可能需要 30-60 秒',
          doneText: '已刷新',
          errorMessage: '账号刷新失败'
        });
        return;
      }
      const poolVerify = event.target.closest('[data-chatgpt-pool-account-verify]');
      if (poolVerify) {
        event.preventDefault();
        runButtonAction(poolVerify, () => verifyChatgptPoolAccount(poolVerify.dataset.accountId), {
          loadingText: '打开中...',
          doneText: '已恢复',
          errorMessage: '账号验证流程打开失败'
        });
        return;
      }
      const poolToggle = event.target.closest('[data-chatgpt-pool-account-toggle]');
      if (poolToggle) {
        event.preventDefault();
        runButtonAction(poolToggle, () => updateChatgptPoolAccount(poolToggle.dataset.accountId, poolToggle.dataset.nextStatus || '禁用'), {
          loadingText: '处理中...',
          doneText: '已更新',
          errorMessage: '账号状态更新失败'
        });
        return;
      }
      const poolDelete = event.target.closest('[data-chatgpt-pool-account-delete]');
      if (poolDelete) {
        event.preventDefault();
        runButtonAction(poolDelete, () => deleteChatgptPoolAccount(poolDelete.dataset.accountId), {
          loadingText: '删除中...',
          doneText: '已删除',
          errorMessage: '账号删除失败'
        });
      }
    });
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      if (settingsInfoTipOpen) {
        closeSettingsInfoTip();
        return;
      }
      if (els.deskSettingsPanel?.classList.contains('is-open')) {
        close();
      }
    });
    document.addEventListener('click', event => {
      if (!settingsInfoTipOpen) return;
      const panel = els.deskSettingsInfoTip;
      const trigger = els.deskSettingsInfoBtn;
      if (panel?.contains(event.target) || trigger?.contains(event.target)) return;
      closeSettingsInfoTip();
    });
    window.addEventListener('resize', () => {
      if (settingsInfoTipOpen) updateSettingsInfoTipPosition();
    });
  }

  function init() {
    collectElements();
    bindEvents();
  }

  window.DesktopSettings = {
    init,
    open,
    close,
    refresh
  };

  window.openDesktopSettingsPanel = function () {
    open().catch(error => showSettingsFeedback(error, '设置打开失败'));
  };
})();
