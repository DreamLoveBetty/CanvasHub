(function () {
  const els = {};
  let lastDiagnostics = null;
  let lastPromptConfig = null;
  let lastChatgptPoolAccounts = null;
  let lastSystemSettings = null;
  let lastGptModelCatalog = null;
  let lastComfyWorkflows = null;
  let lastComfyHealth = null;
  let lastVideoRuntimeStatus = null;
  let lastVideoRuntimeCapabilities = null;
  let lastVideoSupervisorStatus = null;
  let activeComfyWorkflowId = '';
  let krea2Tools = null;
  let qwen21Tools = null;
  let loraSettings = null;
  let pinterestAuthSessionId = window.sessionStorage?.getItem('deskPinterestAuthSessionId') || '';
  let pinterestAuthActivity = null;
  let activeTab = 'status';
  let settingsSearch = null;
  let settingsDrawer = null;
  let searchIndexCache = null;
  const searchHitTimers = new WeakMap();
  const googlePoolSettings = window.DesktopGooglePool.create({
    request: (action, body) => window.DesktopApi.googlePool(action, body),
    renderCard, escapeHtml,
    onRender: () => { if (lastDiagnostics) renderDiagnostics(lastDiagnostics); },
    onGptSelected: () => loadChatgptPoolAccounts().catch(error => showSettingsFeedback(error, '账号池列表读取失败'))
  });
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
          '访问密码也保护系统诊断、历史、图片读取和生成接口。',
          'Pinterest 图库参数保存在 settings.json，完整浏览器登录态单独保存在 browser_auth.json。'
        ]],
        ['注意事项', [
          '公网模式只解决监听地址，不替代 HTTPS、反向代理、系统防火墙或 Telegram 域名配置。',
          '如果只是本机使用，不要开启公网模式。',
          '“连接 Pinterest”会打开隔离浏览器窗口；登录完成后回到设置页点击“完成登录”。',
          'Cookie 备用导入保存后不会回显；退出登录会删除 browser_auth.json。'
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
    },
    'model-tools': {
      title: '模型工具',
      subtitle: 'Qwen 2.1 / Krea 2 Base 权重转换与管理',
      summary: '按模型架构检查本地完整 Transformer，使用共享 MLX 环境转换并注册到对应画布节点。',
      sections: [
        ['转换流程', [
          '源文件保持在本地，不通过浏览器上传；放入对应“模型导入目录”后刷新设置页，再从下拉列表选择。',
          '先检查 safetensors 文件头，再开始转换；检查不会载入完整模型。转换在独立子进程中严格加载，按输出精度写入并严格重载。',
          '验证通过后才会原子写入对应 Base 权重目录，并在节点中显示实际模型名称。'
        ]],
        ['兼容范围与输出精度', [
          '支持与 Krea 2 Turbo、Qwen-Image 2.1 同结构的完整 FP32/BF16/FP16 Transformer，以及严格配对 weight_scale/comfy_quant 的 ComfyUI scaled-FP8 E4M3FN 单文件。',
          '兼容 transformer/model.diffusion_model 等包装前缀。仅转换完整 Transformer；Qwen 1、旧 Edit、LoRA、GGUF、其它 FP8、MLX packed 权重和修改了层数或 shape 的模型会被拒绝。',
          '两种模型均可选 MLX BF16 · 不量化；默认仍为 MLX 8-bit · group_size 64，Krea 2 另有 Mixed 4/8-bit。不同精度独立存放，不覆盖已有模型。',
          'BF16 仅导出 Transformer，保留现有共享文本编码器与 VAE；Qwen 共享文本编码器仍为 8-bit，不等于整套 BF16 模型。BF16 需要更多磁盘和统一内存。',
          'FP8 解码为 BF16 或再次量化均不会恢复已损失的精度。'
        ]],
        ['资源调度', [
          '转换复用画布主 Python 环境，不安装或降级 MLX、mflux、Transformers。',
          'Qwen 首次使用需要准备固定源码与共享模型；共用画布 Python 环境，不升级 Krea2 / YuE 依赖。共享文本与视觉编码器、RGBA VAE 供全部 Qwen Base 使用。',
          '转换与 YuE、Qwen、Krea 及其他本机推理任务串行排队；不会强制终止正在运行的任务。'
        ]],
        ['Qwen 2.1 · VAE', [
          '支持完整 Qwen-Image 2.1 RGBA VAE（FP32 / BF16 / FP16）。放入 VAE 导入目录后点击“刷新目录”；无需重命名为 0.safetensors。使用固定 Qwen 2.1 配置，不支持不同架构或归一化配置的 VAE。',
          '原版 MLX 直接加载，自定义 Diffusers VAE 自动适配布局，不量化、不覆盖原版。',
          '导入后点击“应用 VAE”，用于新提交的 Qwen 任务；已排队或正在生成的任务保留原选择。'
        ]]
      ]
    },
    comfy: {
      title: 'ComfyUI 配置',
      subtitle: '本地服务与工作流目录',
      summary: '配置 ComfyUI 服务连接，并管理画布节点中展示的工作流名称、能力和缩略图。',
      sections: [
        ['服务连接', [
          'Base URL 同时包含协议、地址和端口，保存后立即用于后续 ComfyUI 请求。',
          '测试连接会读取 ComfyUI system_stats 和 queue，不会向工作流队列提交任务。'
        ]],
        ['工作流库', [
          '节点只显示已启用工作流；停用不会删除 JSON，也不会破坏旧画布引用。',
          '缩略图会压缩成 WebP 保存，工作流 JSON 本身仍保留在后端 workflows 目录。',
          '画布节点会自动解析 JSON 中的数字、开关、文本和常用枚举参数；节点修改只作为本次运行覆盖，不会改写原工作流。'
        ]]
      ]
    },
    'video-inference': {
      title: '视频推理配置',
      subtitle: '独立 MiniMax H3 Runtime',
      summary: '选择主程序调用本机或局域网中的独立 H3 Runtime；画布不保存服务地址和密钥。',
      sections: [
        ['运行方式', [
          '自动检测会先尝试本机 Runtime，再尝试已配置的局域网 Runtime。',
          '本机 H3 适合主程序和 RTX 显卡部署在同一台 Windows 设备；局域网 H3 适合 Mac 或其他设备调用 Windows 推理机。',
          'H3_Runtime_Server 独立启动，不依赖 ComfyUI 前端和工作流 JSON。'
        ]],
        ['参数边界', [
          '节点中的画幅只决定宽高比，质量表示像素量，并由两者映射到实际分辨率。',
          '实际尺寸始终按 Runtime 的 dimension_multiple 对齐，并受 max_pixels 限制。',
          'FirstBlockCache 与 Sol-Attn 属于近似加速；Sol-Attn 和组合模式继续标记为实验性。'
        ]],
        ['安全与保存', [
          '局域网 API Key 只保存在后端 settings.json，不会返回前端或写入画布工作流。',
          'Runtime 与 Supervisor 地址只允许本机或局域网完整 URL；连接检测不经过系统代理。',
          'Supervisor 管理员密码只在独立管理台登录，CanvasHub 不保存也不代理管理凭据。'
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
      'deskSettingsSearchInput',
      'deskSettingsSearchResults',
      'deskSettingsResize',
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
      options.disabled ? 'disabled aria-disabled="true"' : '',
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

  function renderSecretTextarea(label, field, configured, options = {}) {
    const placeholder = options.placeholder || (configured ? '留空则不修改' : '粘贴登录态');
    return `
      <div class="desk-settings-secret-field desk-settings-form__wide">
        <div class="desk-settings-secret-field__label">
          <span>${escapeHtml(label)}</span>
          ${configured ? `
            <button type="button" class="desk-settings-secret-clear" data-system-secret-clear-field="${escapeHtml(field)}" data-system-secret-clear-label="${escapeHtml(label)}" title="清除已保存的${escapeHtml(label)}">
              清除
            </button>
          ` : ''}
        </div>
        <textarea class="desk-settings-textarea" data-system-setting-field="${escapeHtml(field)}" placeholder="${escapeHtml(placeholder)}" autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>
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

  function renderCanvasInteractionSettings() {
    const collisionEnabled = window.DesktopPreferences?.state?.canvasCollisionEnabled === true;
    const swellStyle = window.DesktopPreferences?.normalizeConnectionSwellStyle?.(
      window.DesktopPreferences?.state?.connectionSwellStyle
    ) || 'liquid';
    const lineStyle = window.DesktopPreferences?.normalizeConnectionLineStyle?.(
      window.DesktopPreferences?.state?.connectionLineStyle
    ) || 'straight';
    return renderCard('画布交互', [
      `<div class="desk-settings-canvas-interaction">
        <span class="desk-settings-canvas-interaction__label">连接端点</span>
        <div class="desk-settings-canvas-interaction__segment desk-key-bank" role="group" aria-label="连接端点样式">
          <button type="button" class="${swellStyle === 'liquid' ? 'is-active' : ''}" data-connection-swell-style="liquid" aria-pressed="${swellStyle === 'liquid' ? 'true' : 'false'}">液化</button>
          <button type="button" class="${swellStyle === 'droplet' ? 'is-active' : ''}" data-connection-swell-style="droplet" aria-pressed="${swellStyle === 'droplet' ? 'true' : 'false'}">水滴</button>
        </div>
        <span class="desk-settings-canvas-interaction__label">连线线条</span>
        <div class="desk-settings-canvas-interaction__segment desk-key-bank" role="group" aria-label="连线线条样式">
          <button type="button" class="${lineStyle === 'straight' ? 'is-active' : ''}" data-connection-line-style="straight" aria-pressed="${lineStyle === 'straight' ? 'true' : 'false'}">直线</button>
          <button type="button" class="${lineStyle === 'curve' ? 'is-active' : ''}" data-connection-line-style="curve" aria-pressed="${lineStyle === 'curve' ? 'true' : 'false'}">曲线</button>
        </div>
        <span class="desk-settings-canvas-interaction__label" title="拖动节点时，自动推开碰到的其他节点；图片靠近合组优先。">节点碰撞</span>
        <div class="desk-settings-canvas-interaction__segment desk-key-bank" role="group" aria-label="节点碰撞开关">
          <button type="button" class="${!collisionEnabled ? 'is-active' : ''}" data-canvas-collision="false" aria-pressed="${!collisionEnabled}">关闭</button>
          <button type="button" class="${collisionEnabled ? 'is-active' : ''}" data-canvas-collision="true" aria-pressed="${collisionEnabled}">开启</button>
        </div>
      </div>`
    ], true);
  }

  function pinterestAuthLabel(status, configured) {
    if (!configured) return '未配置';
    if (status === 'authenticated') return '已登录';
    if (status === 'invalid') return '登录已失效';
    if (status === 'error') return '验证失败';
    return '已保存，待验证';
  }

  function renderProgressSettings() {
    const model = window.DesktopProgressModel;
    const { style, height, colors } = model.normalizePreferences(window.DesktopPreferences?.state?.progress);
    const color = colors[style] || model.PROGRESS_STYLES[style].color;
    return renderCard('节点进度条', [`<div class="desk-settings-form" data-progress-settings>
      <label><span>动效样式</span><select class="desk-select" data-progress-preference="style" aria-label="进度条动效样式">${Object.entries(model.PROGRESS_STYLES).map(([key, item]) => `<option value="${key}"${style === key ? ' selected' : ''}>${item.label} · ${item.english}</option>`).join('')}</select></label>
      <label><span>轨道高度</span><select class="desk-select" data-progress-preference="height" aria-label="进度条轨道高度"${style === 'classic' ? ' disabled' : ''}>${model.PROGRESS_HEIGHTS.map(size => `<option value="${size}"${height === size ? ' selected' : ''}>${size} px${size === 36 ? ' · 紧凑' : size === 48 ? ' · 标准' : ' · 宽松'}</option>`).join('')}</select></label>
      <div class="desk-settings-color-field"><span>填充颜色</span>${window.DesktopColorBloom.html({ value: color, label: '进度条填充颜色', hexClass: 'desk-input',
        hexAttrs: 'data-progress-preference="hex" aria-label="进度条颜色 HEX" placeholder="#42B8FA"', valueAttrs: 'data-progress-preference="color"',
        after: '<button type="button" class="desk-button" data-progress-color-reset title="恢复当前样式的原始配色">原色</button>' })}</div>
      <p class="desk-settings-form__hint">即时生效并保存在本浏览器。新样式将进度、阶段和用时置于轨道内；经典保留原有胶囊与下挂标签。</p>
    </div>`], true);
  }

  function syncProgressSettings(card) {
    if (!card) return;
    const model = window.DesktopProgressModel;
    const { style, height, colors } = model.normalizePreferences(window.DesktopPreferences?.state?.progress);
    const color = colors[style] || model.PROGRESS_STYLES[style].color;
    card.querySelectorAll('[data-progress-preference]').forEach(control => {
      const field = control.dataset.progressPreference;
      control.value = field === 'style' ? style : field === 'height' ? String(height) : color;
      if (field === 'height') control.disabled = style === 'classic';
      control.removeAttribute('aria-invalid');
      if (field === 'style' || field === 'height') window.DesktopSelect?.refresh(control);
    });
    window.DesktopColorBloom?.refresh(card);
  }

  function updateProgressPreference(event) {
    const input = event.target.closest('[data-progress-preference]');
    if (!input) return false;
    const field = input.dataset.progressPreference;
    const preferences = window.DesktopPreferences;
    const previous = window.DesktopProgressModel.normalizePreferences(preferences?.state?.progress);
    if (field === 'style' || field === 'height') {
      if (event.type !== 'change') return true;
      preferences.setProgressPreferences({ [field]: input.value });
      // Preserve focus/scroll and unsaved fields in other System cards.
      syncProgressSettings(input.closest('[data-progress-settings]'));
    } else {
      const color = window.DesktopProgressModel.normalizeFillColor(input.value);
      input.setAttribute('aria-invalid', String(!color));
      if (!color) return true;
      preferences.setProgressPreferences({ colors: { ...previous.colors, [previous.style]: color } });
      const card = input.closest('[data-progress-settings]');
      card.querySelectorAll('[data-progress-preference="color"], [data-progress-preference="hex"]').forEach(control => {
        if (control !== input || event.type === 'change') control.value = color;
        control.removeAttribute('aria-invalid');
      });
      window.DesktopColorBloom?.refresh(card);
    }
    return true;
  }

  function renderControlMaterialSettings() {
    const material = window.DesktopControlMaterial;
    if (!material) return '';
    return renderCard('节点按钮材质', [material.renderSettings(window.DesktopPreferences?.state?.controlMaterial)], true);
  }

  // Assembly only: the module validates the event and owns the card's in-place refresh.
  function updateControlMaterialPreference(event) {
    const material = window.DesktopControlMaterial;
    const card = event.target.closest?.('[data-control-material-settings]');
    if (!material || !card) return false;
    const patch = material.patchFromEvent(event, window.DesktopPreferences.state.controlMaterial);
    if (patch) {
      window.DesktopPreferences.setControlMaterialPreferences(patch);
      material.syncSettings(card, window.DesktopPreferences.state.controlMaterial);
    }
    return true;
  }

  function pinterestAuthSourceLabel(source) {
    if (source === 'browser_login') return '浏览器授权 JSON';
    if (source === 'cookie_import') return 'Cookie 导入 JSON';
    if (source === 'browser_auth_json') return '授权 JSON';
    if (source === 'legacy_cookie') return '旧版 settings Cookie';
    return '未配置';
  }

  function renderPinterestSettings(config = {}) {
    const authConfigured = Boolean(config.auth_configured);
    const authStatus = config.auth_status || (authConfigured ? 'unverified' : 'not_configured');
    const authOk = authStatus === 'authenticated';
    const authLabel = pinterestAuthLabel(authStatus, authConfigured);
    const authUsername = String(config.auth_username || '').trim();
    const authDisplayName = String(config.auth_display_name || '').trim();
    const authProfileUrl = String(config.auth_profile_url || '').trim();
    const accountLabel = authUsername
      ? `@${authUsername}`
      : (authConfigured ? '账号信息待验证' : '未连接账号');
    const accountMeta = authDisplayName && authDisplayName !== authUsername
      ? `${authDisplayName} · ${authLabel}`
      : authLabel;
    const verifiedAt = config.last_verified_at
      ? chatgptPoolTimeLabel(config.last_verified_at, '验证于 ')
      : '尚未验证';
    const browserAvailable = config.browser_login_available !== false;
    const browserLabel = config.browser_name || 'Chrome';
    const activityText = pinterestAuthActivity?.message || '';
    return renderCard('Pinterest 图库', [
      `<div class="desk-settings-form" data-system-settings-card="pinterest">
        ${renderCheckbox('启用 Pinterest 图库', 'pinterest.enabled', Boolean(config.enabled))}
        ${renderKv('授权账号', accountLabel)}
        ${renderKv('个人主页', authProfileUrl || (authConfigured ? '验证后自动识别' : '连接账号后自动识别'))}
        ${renderInput('同步目标主页（可选）', 'pinterest.sync_profile_url', config.sync_profile_url || '', { placeholder: 'https://www.pinterest.com/username/' })}
        <label>
          <span>同步方式</span>
          <select class="desk-select" data-system-setting-field="pinterest.sync_mode">
            ${optionHtml('auto', '自动（登录态优先，RSS 托底）', config.sync_mode || 'auto')}
            ${optionHtml('authenticated_browser', '登录态完整同步', config.sync_mode)}
            ${optionHtml('rss', '仅 RSS 增量同步', config.sync_mode)}
          </select>
        </label>
        ${renderInput('每个图板最多 Pin 数', 'pinterest.max_pins_per_board', config.max_pins_per_board || 500, { type: 'number', min: 20, max: 5000, step: 20 })}
        ${renderInput('验证超时（秒）', 'pinterest.request_timeout_seconds', config.request_timeout_seconds || 20, { type: 'number', min: 5, max: 60, step: 1 })}
        ${renderCheckbox('下载 Pinterest 原图', 'pinterest.download_originals', config.download_originals !== false)}
        ${renderSecretTextarea('Cookie（备用导入）', 'pinterest.auth_cookie', authConfigured, {
          placeholder: authConfigured ? '登录态已保存；留空则不修改' : '浏览器登录不可用时，粘贴完整 Cookie'
        })}
        <div class="desk-settings-pinterest-status ${authOk ? 'is-ok' : 'is-warn'}">
          <span aria-hidden="true"></span>
          <strong>${escapeHtml(accountLabel)}</strong>
          <small>${escapeHtml(`${accountMeta} · ${pinterestAuthSourceLabel(config.auth_source)} · ${verifiedAt}`)}</small>
        </div>
        ${activityText ? `<p class="desk-settings-form__activity">${escapeHtml(activityText)}</p>` : ''}
        <p class="desk-settings-form__hint">授权账号和个人主页会在验证登录态后自动识别；仅在需要读取其他公开主页时填写“同步目标主页”。</p>
        <div class="desk-settings-form__actions">
          ${pinterestAuthSessionId
            ? '<button type="button" class="is-primary" data-pinterest-auth-complete>完成登录</button><button type="button" data-pinterest-auth-cancel>取消登录</button>'
            : `<button type="button" data-pinterest-auth-start${browserAvailable ? '' : ' disabled'} title="${escapeHtml(browserAvailable ? `使用 ${browserLabel} 登录` : '未找到 Chrome 或 Edge')}">${authConfigured ? '切换账号' : '连接 Pinterest'}</button>`}
          ${authConfigured ? '<button type="button" data-pinterest-auth-verify>验证登录态</button>' : ''}
          ${authConfigured ? '<button type="button" data-pinterest-auth-logout>退出登录</button>' : ''}
          <button type="button" class="is-primary" data-system-settings-save="pinterest">保存 Pinterest 配置</button>
        </div>
      </div>`
    ], !config.enabled || authOk);
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

  function renderThirdPartyImageSettings(config, nanoConfig = {}, cyimgConfig = {}) {
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
    const cyimgCard = renderCard('绘栾 API', [
      `<div class="desk-settings-form" data-system-settings-card="third-party-cyimg">
        <p class="desk-settings-form__hint">独立异步接口，支持画布上的绘栾图像与视频节点。模型目录实时读取；不会改动现有第三方图像或 GPT 托底线路。</p>
        ${renderSecretInput('绘栾 API Key', 'cyimg.api_key', cyimgConfig.api_key_configured, {
          placeholder: cyimgConfig.api_key_configured ? '留空则不修改' : '粘贴 sk_ 开头的绘栾 API Key'
        })}
        ${renderInput('任务等待上限（秒）', 'cyimg.task_timeout_seconds', cyimgConfig.task_timeout_seconds || 3600, { type:'number', min:60, max:7200, step:60 })}
        ${renderSystemSaveButton('third-party-cyimg', '保存绘栾 API')}
      </div>`
    ], Boolean(cyimgConfig.api_key_configured));
    return nanoCard + gptImageCard + cyimgCard;
  }

  function comfyWorkflowPlaceholder() {
    return `<span class="desk-comfy-workflow-placeholder" aria-hidden="true"><i></i><i></i><i></i></span>`;
  }

  function renderComfyWorkflowCards(catalog = {}) {
    const items = Array.isArray(catalog.items) ? catalog.items : [];
    if (!items.length) return '<div class="desk-settings-empty">没有发现可配置的工作流 JSON。</div>';
    if (!activeComfyWorkflowId || !items.some(item => item.id === activeComfyWorkflowId)) {
      activeComfyWorkflowId = catalog.default_workflow || items[0].id;
    }
    return `<div class="desk-comfy-settings-workflows" role="listbox" aria-label="ComfyUI 工作流库">${items.map(item => `
      <button type="button" class="desk-comfy-settings-workflow${item.id === activeComfyWorkflowId ? ' is-selected' : ''}${item.enabled ? '' : ' is-disabled'}" data-comfy-workflow-edit="${escapeHtml(item.id)}" role="option" aria-selected="${item.id === activeComfyWorkflowId ? 'true' : 'false'}">
        <span class="desk-comfy-settings-workflow__thumb">${item.thumbnail_url ? `<img src="${escapeHtml(item.thumbnail_url)}" alt="">` : comfyWorkflowPlaceholder()}</span>
        <span class="desk-comfy-settings-workflow__copy"><strong>${escapeHtml(item.label || item.id)}</strong><small>${escapeHtml(item.summary || item.id)}</small></span>
        <span class="desk-comfy-settings-workflow__state">${item.enabled ? (item.is_default ? '默认' : '启用') : '停用'}</span>
      </button>
    `).join('')}</div>`;
  }

  function renderComfyWorkflowEditor(catalog = {}) {
    const items = Array.isArray(catalog.items) ? catalog.items : [];
    const item = items.find(entry => entry.id === activeComfyWorkflowId) || items[0];
    if (!item) return '';
    return `
      <div class="desk-comfy-workflow-editor" data-comfy-workflow-editor="${escapeHtml(item.id)}">
        <div class="desk-comfy-workflow-editor__heading">
          <div><span>工作流配置</span><strong>${escapeHtml(item.id)}</strong></div>
          <small>节点卡片会同步使用这些展示信息</small>
        </div>
        <div class="desk-settings-form desk-settings-form--comfy-workflow">
          <label><span>显示名称</span><input class="desk-input" data-comfy-workflow-field="label" value="${escapeHtml(item.label || '')}"></label>
          <label><span>简短说明</span><input class="desk-input" data-comfy-workflow-field="summary" value="${escapeHtml(item.summary || '')}"></label>
          <label><span>默认宽度</span><input class="desk-input" type="number" min="64" max="8192" step="8" data-comfy-workflow-field="default_width" value="${escapeHtml(item.default_width || 1024)}"></label>
          <label><span>默认高度</span><input class="desk-input" type="number" min="64" max="8192" step="8" data-comfy-workflow-field="default_height" value="${escapeHtml(item.default_height || 1024)}"></label>
          <label><span>排序</span><input class="desk-input" type="number" min="0" max="9999" step="1" data-comfy-workflow-field="order" value="${escapeHtml(item.order ?? 100)}"></label>
          <label><span>最大图片数</span><input class="desk-input" type="number" min="0" max="8" step="1" data-comfy-workflow-field="max_images" value="${escapeHtml(item.max_images ?? 0)}"></label>
          <label><span>输出数量</span><input class="desk-input" type="number" min="1" max="8" step="1" data-comfy-workflow-field="output_count" value="${escapeHtml(item.output_count ?? 1)}"></label>
          <label><span>节点中显示</span><input type="checkbox" data-comfy-workflow-field="enabled"${item.enabled ? ' checked' : ''}></label>
          <label><span>默认工作流</span><input type="checkbox" data-comfy-workflow-field="is_default"${item.is_default ? ' checked' : ''}></label>
          <label><span>接受文本</span><input type="checkbox" data-comfy-workflow-field="accepts_text"${item.accepts_text !== false ? ' checked' : ''}></label>
          <label><span>接受图片</span><input type="checkbox" data-comfy-workflow-field="accepts_image"${item.accepts_image ? ' checked' : ''}></label>
          <label class="desk-settings-form__wide desk-comfy-thumbnail-field"><span>卡片缩略图</span><input type="file" accept="image/png,image/jpeg,image/webp" data-comfy-workflow-thumbnail><small>${item.thumbnail_url ? '已配置，可重新选择图片替换' : '建议使用 320 × 200 或同等比例图片'}</small></label>
          <div class="desk-settings-form__actions desk-settings-form__wide">
            <button type="button" class="is-primary" data-comfy-workflow-save>保存工作流信息</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderComfySettings(config = {}, catalog = {}, health = null) {
    const environmentFields = Array.isArray(config.environment_fields) ? config.environment_fields : [];
    const isEnvironmentManaged = field => environmentFields.includes(field);
    const environmentHint = config.environment_managed
      ? `<p class="desk-settings-form__hint">部分字段由环境变量托管：${escapeHtml(environmentFields.join('、') || 'ComfyUI 配置')}。</p>`
      : '<p class="desk-settings-form__hint">Base URL 已包含协议、地址和端口；保存后立即用于新的 ComfyUI 请求。</p>';
    const statusText = health?.online
      ? `在线 · ${Number(health.latency_ms || 0)}ms · 队列 ${Number(health.queue_pending || 0) + Number(health.queue_running || 0)}`
      : (health?.error ? `离线 · ${health.error}` : '尚未测试连接');
    const serviceCard = renderCard('ComfyUI 服务连接', [
      `<div class="desk-settings-form" data-system-settings-card="comfy">
        ${renderInput('Base URL', 'comfy.base_url', config.base_url || 'http://127.0.0.1:8188', { placeholder: 'http://127.0.0.1:8188', disabled: isEnvironmentManaged('base_url') })}
        ${renderInput('请求超时', 'comfy.timeout_seconds', config.timeout_seconds || 120, { type: 'number', min: 5, max: 1800, step: 5, disabled: isEnvironmentManaged('timeout_seconds') })}
        ${renderInput('任务超时', 'comfy.task_timeout_seconds', config.task_timeout_seconds || 1800, { type: 'number', min: 60, max: 86400, step: 60, disabled: isEnvironmentManaged('task_timeout_seconds') })}
        ${renderInput('轮询间隔', 'comfy.poll_interval_seconds', config.poll_interval_seconds || 2, { type: 'number', min: 0.25, max: 30, step: 0.25, disabled: isEnvironmentManaged('poll_interval_seconds') })}
        ${environmentHint}
        <div class="desk-comfy-service-status${health?.online ? ' is-online' : ''}"><span></span><strong>${escapeHtml(statusText)}</strong></div>
        <div class="desk-settings-form__actions desk-settings-form__wide">
          <button type="button" data-comfy-connection-test>测试连接</button>
          <button type="button" class="is-primary" data-system-settings-save="comfy">保存 ComfyUI 配置</button>
        </div>
      </div>`
    ], Boolean(health?.online || config.base_url));
    const workflowsCard = renderCard('工作流库', [
      `<div class="desk-comfy-settings-library">
        <div class="desk-comfy-settings-library__meta"><span>${(catalog.items || []).filter(item => item.enabled).length} 已启用 / ${(catalog.items || []).length} 全部</span><small>点击卡片配置</small></div>
        ${renderComfyWorkflowCards(catalog)}
        ${renderComfyWorkflowEditor(catalog)}
      </div>`
    ], Boolean((catalog.items || []).some(item => item.enabled)));
    return serviceCard + workflowsCard;
  }

  function renderVideoInferenceSettings(config = {}, status = null, supervisorStatus = null) {
    const runtimeMode = ['auto', 'local', 'lan'].includes(config.runtime_mode) ? config.runtime_mode : 'auto';
    const local = config.local || {};
    const lan = config.lan || {};
    const component = status?.component || {};
    const environmentFields = Array.isArray(config.environment_fields) ? config.environment_fields : [];
    const isManaged = field => environmentFields.includes(field);
    const statusText = status?.online
      ? `H3 Runtime ${status.version || ''} · 在线 · ${Number(status.latency_ms || 0)}ms`
      : (status?.checked
        ? `离线${status?.error ? ` · ${status.error}` : ''}`
        : '尚未检测连接');
    const componentText = component.exists
      ? `组件已发现${component.start_script ? ` · ${component.start_script}` : ''}`
      : (component.supported ? '组件目录未发现' : '当前设备仅可作为远程调用端');
    const localVisible = runtimeMode !== 'lan';
    const lanVisible = runtimeMode !== 'local';
    const supervisorUrl = String(config.manager_base_url || '').trim();
    const supervisorOnline = Boolean(supervisorStatus?.online);
    const supervisorStatusText = supervisorOnline
      ? `Supervisor ${supervisorStatus.version || ''} · 在线`
      : (supervisorStatus?.checked ? 'Supervisor 离线' : 'Supervisor 未检测');
    const supervisorMeta = supervisorOnline
      ? `${Number(supervisorStatus.latency_ms || 0)}ms · ${supervisorStatus.admin_initialized ? '管理员已初始化' : '管理员待初始化'}`
      : (supervisorStatus?.error || supervisorUrl || '未配置管理台地址');
    const managerOpenUrl = String(supervisorStatus?.manager_url || '').trim();
    return renderCard('视频推理运行方式', [
      `<div class="desk-settings-form desk-video-runtime-settings" data-system-settings-card="video-inference">
        <input type="hidden" data-system-setting-field="video_inference.runtime_mode" value="${escapeHtml(runtimeMode)}">
        <div class="desk-video-runtime-mode desk-key-bank" role="tablist" aria-label="H3 Runtime 运行方式">
          ${[
            ['auto', '自动检测'],
            ['local', '本机 H3'],
            ['lan', '局域网 H3']
          ].map(([value, label]) => `<button type="button" data-video-runtime-mode="${value}" class="${runtimeMode === value ? 'is-active' : ''}" aria-pressed="${runtimeMode === value ? 'true' : 'false'}">${label}</button>`).join('')}
        </div>
        <div class="desk-video-runtime-status${status?.online ? ' is-online' : ''}${status?.checked && !status?.online ? ' is-offline' : ''}">
          <span aria-hidden="true"></span>
          <div><strong>${escapeHtml(statusText)}</strong><small>${escapeHtml(status?.base_url || (runtimeMode === 'lan' ? lan.base_url : local.base_url) || '未配置服务地址')}</small></div>
        </div>
        <section class="desk-video-runtime-panel" data-video-runtime-mode-panel="local"${localVisible ? '' : ' hidden'}>
          <div class="desk-settings-form__section-title"><strong>本机服务</strong><span>${escapeHtml(componentText)}</span></div>
          ${renderInput('组件目录', 'video_inference.local.component_dir', local.component_dir || '', { placeholder: 'D:\\Program\\H3_Runtime_Server', disabled: isManaged('local.component_dir') })}
          ${renderInput('服务地址', 'video_inference.local.base_url', local.base_url || 'http://127.0.0.1:8190', { placeholder: 'http://127.0.0.1:8190', disabled: isManaged('local.base_url') })}
          <label><span>启动方式</span><select class="desk-select" data-system-setting-field="video_inference.local.start_mode"${isManaged('local.start_mode') ? ' disabled aria-disabled="true"' : ''}>
            ${optionHtml('on_demand', '按需启动', local.start_mode || 'on_demand')}
            ${optionHtml('manual', '手动启动', local.start_mode)}
            ${optionHtml('always', '随组件常驻', local.start_mode)}
          </select></label>
        </section>
        <section class="desk-video-runtime-panel" data-video-runtime-mode-panel="lan"${lanVisible ? '' : ' hidden'}>
          <div class="desk-settings-form__section-title"><strong>局域网服务</strong><span>主程序与推理机可部署在不同设备</span></div>
          ${renderInput('服务地址', 'video_inference.lan.base_url', lan.base_url || '', { placeholder: 'http://192.168.3.22:8190', disabled: isManaged('lan.base_url') })}
          ${isManaged('lan.api_key')
            ? '<p class="desk-settings-form__hint">Runtime API Key 由环境变量 H3_RUNTIME_API_KEY 托管。</p>'
            : renderSecretInput('Runtime API Key', 'video_inference.lan.api_key', lan.api_key_configured, { placeholder: lan.api_key_configured ? '留空则不修改' : '填写 H3 Runtime API Key' })}
          ${renderInput('连接超时（秒）', 'video_inference.lan.connect_timeout_seconds', lan.connect_timeout_seconds || 5, { type: 'number', min: 0.5, max: 30, step: 0.5, disabled: isManaged('lan.connect_timeout_seconds') })}
        </section>
        <section class="desk-video-supervisor">
          <div class="desk-settings-form__section-title"><strong>H3 Supervisor 管理台</strong><span>独立于 Runtime 运行</span></div>
          ${renderInput('管理台地址', 'video_inference.manager_base_url', supervisorUrl, { placeholder: 'http://192.168.3.22:8191', disabled: isManaged('manager_base_url') })}
          <div class="desk-video-supervisor-status${supervisorOnline ? ' is-online' : ''}${supervisorStatus?.checked && !supervisorOnline ? ' is-offline' : ''}">
            <span class="desk-video-supervisor-status__dot" aria-hidden="true"></span>
            <div class="desk-video-supervisor-status__copy">
              <strong data-video-supervisor-status-label>${escapeHtml(supervisorStatusText)}</strong>
              <small data-video-supervisor-status-meta>${escapeHtml(supervisorMeta)}</small>
            </div>
            <div class="desk-settings-form__actions desk-settings-form__actions--compact desk-video-supervisor-status__actions">
              <button type="button" data-video-supervisor-refresh title="检测 H3 Supervisor 管理台"><span aria-hidden="true">&#8635;</span><span>刷新状态</span></button>
              <button type="button" class="is-primary" data-video-supervisor-open data-video-supervisor-url="${escapeHtml(managerOpenUrl)}" title="在新窗口打开 H3 Supervisor 管理台"${managerOpenUrl ? '' : ' disabled'}><span aria-hidden="true">&#8599;</span><span>打开管理台</span></button>
            </div>
          </div>
          <p class="desk-settings-form__hint">Runtime API Key 用于推理请求；Supervisor 管理员密码只在独立管理台登录。</p>
        </section>
        <div class="desk-settings-form__actions desk-settings-form__wide">
          <button type="button" data-video-runtime-test>检测连接</button>
          <button type="button" data-video-runtime-start${component.startable ? '' : ' disabled'} title="${escapeHtml(component.startable ? '启动本机 H3 Runtime' : componentText)}">启动服务</button>
          <button type="button" class="is-primary" data-system-settings-save="video-inference">保存视频推理设置</button>
        </div>
      </div>`
    ], Boolean(status?.online));
  }

  function updateVideoRuntimeStatusView(status = null) {
    const card = els.deskSettingsBody?.querySelector('[data-system-settings-card="video-inference"]');
    const statusView = card?.querySelector('.desk-video-runtime-status');
    if (!statusView || !status) return;
    const online = Boolean(status.online);
    const checked = Boolean(status.checked);
    const statusText = online
      ? `H3 Runtime ${status.version || ''} · 在线 · ${Number(status.latency_ms || 0)}ms`
      : (checked
        ? `离线${status.error ? ` · ${status.error}` : ''}`
        : '尚未检测连接');
    statusView.classList.toggle('is-online', online);
    statusView.classList.toggle('is-offline', checked && !online);
    const title = statusView.querySelector('strong');
    const address = statusView.querySelector('small');
    if (title) title.textContent = statusText;
    if (address) {
      const selectedMode = status.selected_mode || status.runtime_mode || 'lan';
      const addressField = selectedMode === 'local'
        ? 'video_inference.local.base_url'
        : 'video_inference.lan.base_url';
      const addressInput = card.querySelector(`[data-system-setting-field="${addressField}"]`);
      address.textContent = status.base_url || addressInput?.value || '未配置服务地址';
    }
    const settingsCard = card.closest('.desk-settings-card');
    settingsCard?.classList.toggle('is-ok', online);
    settingsCard?.classList.toggle('is-warn', !online);
  }

  function updateVideoSupervisorStatusView(status = null) {
    const card = els.deskSettingsBody?.querySelector('[data-system-settings-card="video-inference"]');
    const statusView = card?.querySelector('.desk-video-supervisor-status');
    if (!statusView || !status) return;
    const online = Boolean(status.online);
    const checked = Boolean(status.checked);
    const statusText = online
      ? `Supervisor ${status.version || ''} · 在线`
      : (checked ? 'Supervisor 离线' : 'Supervisor 未检测');
    const metaText = online
      ? `${Number(status.latency_ms || 0)}ms · ${status.admin_initialized ? '管理员已初始化' : '管理员待初始化'}`
      : (status.error || status.base_url || '未配置管理台地址');
    statusView.classList.toggle('is-online', online);
    statusView.classList.toggle('is-offline', checked && !online);
    const title = statusView.querySelector('[data-video-supervisor-status-label]');
    const meta = statusView.querySelector('[data-video-supervisor-status-meta]');
    if (title) title.textContent = statusText;
    if (meta) meta.textContent = metaText;
    const openButton = statusView.querySelector('[data-video-supervisor-open]');
    const managerUrl = String(status.manager_url || '').trim();
    if (openButton) {
      openButton.disabled = !managerUrl;
      openButton.dataset.videoSupervisorUrl = managerUrl;
    }
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

  // One category's sections from already-loaded data. `activeTab` is shadowed so each
  // section renders its full form for `tab` and its summary card otherwise; the search
  // index calls this for every category without touching the DOM or the active tab.
  function buildSections(data, tab) {
    const activeTab = tab;
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
    const cyimg = { ...(data.cyimg || {}), ...(setting('cyimg', {}) || {}) };
    const auth = data.auth || {};
    const server = data.server || {};
    const promptRuntime = lastPromptConfig || { prompt_skill: data.prompt_skill || {} };
    const promptSkill = promptRuntime.prompt_skill || data.prompt_skill || {};
    const editableProvider = setting('gpt_provider', {});
    const providerRuntime = { ...provider, ...editableProvider };
    const editableServer = { ...server, ...(setting('server', {}) || {}) };
    const editablePool = { ...pool, ...(setting('chatgpt_pool', {}) || {}) };
    const comfyConfig = { ...(data.comfy || {}), ...(setting('comfy', {}) || {}) };
    const videoInferenceConfig = {
      ...(data.video_inference || {}),
      ...(setting('video_inference', {}) || {})
    };
    const pinterest = setting('pinterest', {});
    const thirdPartyReady = Boolean(nanoBanana.api_key_configured || thirdParty.api_key_configured || cyimg.api_key_configured);
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
        html: activeTab === 'system'
          ? renderCanvasInteractionSettings() + renderProgressSettings() + renderControlMaterialSettings() + renderSystemRuntimeSettings(editableServer, setting('auth', auth)) + renderPinterestSettings(pinterest)
          : ''
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
        html: activeTab === 'third-party' ? renderThirdPartyImageSettings(thirdParty, nanoBanana, cyimg) : renderCard('第三方 API', [
          renderKv('nano banana API Key', nanoBanana.api_key_configured, { boolean: true }),
          renderKv('nano banana API URL', nanoBanana.base_url || ''),
          renderKv('Gpt-image-2 API Key', thirdParty.api_key_configured, { boolean: true }),
          renderKv('Gpt-image-2 API URL', thirdParty.base_url || ''),
          renderKv('生成接口', thirdParty.generate_path || '/v1/images/generations'),
          renderKv('编辑接口', thirdParty.edit_path || '/v1/images/edits'),
          renderKv('模型', thirdParty.model || 'gpt-image-2'),
          renderKv('绘栾 API Key', cyimg.api_key_configured, { boolean: true })
        ], thirdPartyReady)
      },
      {
        tab: 'chatgpt-pool',
        html: activeTab === 'chatgpt-pool'
          ? googlePoolSettings.render(renderChatgptPoolRuntimeSettings(editablePool) + renderChatgptPoolSettings(editablePool, lastChatgptPoolAccounts))
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
      },
      {
        tab: 'model-tools',
        html: activeTab === 'model-tools'
          ? (loraSettings?.render?.() || '') + (qwen21Tools?.render?.() || '') + (krea2Tools?.render?.() || renderCard('Krea 2 模型转换', [
              '<div class="desk-settings-empty">模型工具模块未加载。</div>'
            ], false))
          : ''
      },
      {
        tab: 'comfy',
        html: activeTab === 'comfy'
          ? renderComfySettings(comfyConfig, lastComfyWorkflows || {}, lastComfyHealth)
          : renderCard('ComfyUI', [
            renderKv('服务地址', comfyConfig.base_url || '未配置'),
            renderKv('工作流数量', (lastComfyWorkflows?.items || []).filter(item => item.enabled).length),
            renderKv('连接状态', lastComfyHealth?.online ? '在线' : '未测试')
          ], Boolean(comfyConfig.base_url))
      },
      {
        tab: 'video-inference',
        html: activeTab === 'video-inference'
          ? renderVideoInferenceSettings(videoInferenceConfig, lastVideoRuntimeStatus, lastVideoSupervisorStatus)
          : renderCard('视频推理', [
            renderKv('运行方式', ({ auto: '自动检测', local: '本机 H3', lan: '局域网 H3' })[videoInferenceConfig.runtime_mode] || '自动检测'),
            renderKv('连接状态', lastVideoRuntimeStatus?.online ? '在线' : (lastVideoRuntimeStatus?.checked ? '离线' : '未检测')),
            renderKv('Runtime 版本', lastVideoRuntimeStatus?.version || '未知'),
            renderKv('Supervisor', lastVideoSupervisorStatus?.online ? '在线' : (lastVideoSupervisorStatus?.checked ? '离线' : '未检测')),
            renderKv('管理台地址', videoInferenceConfig.manager_base_url || '未配置')
          ], Boolean(lastVideoRuntimeStatus?.online))
      }
    ];

    return { sections, server, pool, telegram, pinterest, promptSkill, promptRuntime, thirdPartyReady, providerStatusLabel, managedStatusLabel };
  }

  function renderDiagnostics(data) {
    const { sections, server, pool, telegram, pinterest, promptSkill, promptRuntime, thirdPartyReady, providerStatusLabel, managedStatusLabel } = buildSections(data, activeTab);
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
        <span>ComfyUI ${lastComfyHealth?.online ? '在线' : '未测试'}</span>
        <span>H3 Runtime ${lastVideoRuntimeStatus?.online ? '在线' : (lastVideoRuntimeStatus?.checked ? '离线' : '未检测')}</span>
        <span>Supervisor ${lastVideoSupervisorStatus?.online ? '在线' : (lastVideoSupervisorStatus?.checked ? '离线' : '未检测')}</span>
        <span>Pinterest ${pinterest.enabled ? pinterestAuthLabel(pinterest.auth_status, pinterest.auth_configured) : '未启用'}</span>
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
    const [data, systemSettings, promptConfig, gptModels, comfyWorkflows, videoRuntimeStatus, videoRuntimeCapabilities, videoSupervisorStatus] = await Promise.all([
      window.DesktopApi.getSystemDiagnostics(),
      window.DesktopApi.getSystemSettings ? window.DesktopApi.getSystemSettings().catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getPromptConfig ? window.DesktopApi.getPromptConfig().catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getGptModels ? window.DesktopApi.getGptModels().catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getComfyWorkflows ? window.DesktopApi.getComfyWorkflows(true).catch(error => ({ ok: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getVideoRuntimeStatus ? window.DesktopApi.getVideoRuntimeStatus(true).catch(error => ({ ok: false, online: false, checked: true, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getVideoRuntimeCapabilities ? window.DesktopApi.getVideoRuntimeCapabilities().catch(error => ({ ok: false, runtime_online: false, error: error.message })) : Promise.resolve(null),
      window.DesktopApi.getVideoSupervisorStatus ? window.DesktopApi.getVideoSupervisorStatus(true).catch(error => ({ ok: false, online: false, checked: true, error: error.message })) : Promise.resolve(null)
    ]);
    lastDiagnostics = data;
    lastSystemSettings = systemSettings?.ok ? systemSettings : null;
    lastPromptConfig = promptConfig?.ok ? promptConfig : null;
    lastGptModelCatalog = gptModels?.ok ? gptModels : lastGptModelCatalog;
    lastComfyWorkflows = comfyWorkflows?.ok ? comfyWorkflows : lastComfyWorkflows;
    lastVideoRuntimeStatus = videoRuntimeStatus || lastVideoRuntimeStatus;
    lastVideoRuntimeCapabilities = videoRuntimeCapabilities?.capabilities ? videoRuntimeCapabilities : lastVideoRuntimeCapabilities;
    lastVideoSupervisorStatus = videoSupervisorStatus || lastVideoSupervisorStatus;
    if (lastGptModelCatalog) window.DesktopCanvas?.applyGptModelCatalog?.(lastGptModelCatalog);
    if (comfyWorkflows?.ok) {
      window.dispatchEvent(new CustomEvent('desktop:comfy-workflows-updated', { detail: comfyWorkflows }));
    }
    if (videoRuntimeStatus) window.DesktopVideoConfig?.setRuntimeStatus?.(videoRuntimeStatus);
    if (videoRuntimeCapabilities?.capabilities) window.DesktopVideoConfig?.setCapabilities?.(videoRuntimeCapabilities);
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
      if (!field || input.disabled) return;
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
    if (payload.cyimg) window.dispatchEvent(new CustomEvent('desktop:cyimg-settings-updated'));
    window.DesktopResults?.showTransientMessage?.('系统配置已保存。', 'success');
  }

  async function verifyPinterestAuth(button) {
    if (!window.DesktopApi?.saveSystemSettings || !window.DesktopApi?.verifyPinterestAuth) {
      throw new Error('Pinterest 登录验证 API 未加载');
    }
    const card = button?.closest('[data-system-settings-card="pinterest"]');
    const payload = collectSystemSettingsForm(card);
    await window.DesktopApi.saveSystemSettings(payload);
    let result;
    try {
      result = await window.DesktopApi.verifyPinterestAuth();
    } finally {
      await refresh().catch(() => {});
    }
    if (!result?.authenticated) {
      throw new Error('Pinterest 登录态已失效，请更新 Cookie');
    }
    const account = result?.auth_username ? ` @${result.auth_username}` : '';
    window.DesktopResults?.showTransientMessage?.(`Pinterest${account} 登录态验证通过。`, 'success');
    return result;
  }

  async function startPinterestAuth(button) {
    if (!window.DesktopApi?.saveSystemSettings || !window.DesktopApi?.startPinterestAuth) {
      throw new Error('Pinterest 浏览器登录 API 未加载');
    }
    const card = button?.closest('[data-system-settings-card="pinterest"]');
    const payload = collectSystemSettingsForm(card);
    const saved = await window.DesktopApi.saveSystemSettings(payload);
    if (saved?.ok) lastSystemSettings = saved;
    const result = await window.DesktopApi.startPinterestAuth();
    pinterestAuthSessionId = result.session_id || '';
    if (pinterestAuthSessionId) window.sessionStorage?.setItem('deskPinterestAuthSessionId', pinterestAuthSessionId);
    pinterestAuthActivity = result;
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    window.DesktopResults?.showTransientMessage?.(`已打开 ${result.browser || '浏览器'}，完成 Pinterest 登录后点击“完成登录”。`, 'success');
    return result;
  }

  async function completePinterestAuth() {
    if (!window.DesktopApi?.completePinterestAuth) throw new Error('Pinterest 登录完成 API 未加载');
    if (!pinterestAuthSessionId) throw new Error('没有等待完成的 Pinterest 登录会话');
    const result = await window.DesktopApi.completePinterestAuth(pinterestAuthSessionId);
    pinterestAuthActivity = result;
    if (result.pending) {
      if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
      window.DesktopResults?.showTransientMessage?.(result.message || '尚未检测到登录，请在浏览器完成后重试。', 'warning');
      return false;
    }
    pinterestAuthSessionId = '';
    window.sessionStorage?.removeItem('deskPinterestAuthSessionId');
    pinterestAuthActivity = null;
    await refresh();
    const account = result?.auth_username ? ` @${result.auth_username}` : '';
    window.DesktopResults?.showTransientMessage?.(`Pinterest${account} 登录态已保存。`, 'success');
    return result;
  }

  async function cancelPinterestAuth() {
    if (!window.DesktopApi?.cancelPinterestAuth) throw new Error('Pinterest 登录取消 API 未加载');
    await window.DesktopApi.cancelPinterestAuth(pinterestAuthSessionId);
    pinterestAuthSessionId = '';
    window.sessionStorage?.removeItem('deskPinterestAuthSessionId');
    pinterestAuthActivity = null;
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    window.DesktopResults?.showTransientMessage?.('Pinterest 登录窗口已关闭。');
    return true;
  }

  async function logoutPinterestAuth() {
    if (!window.DesktopApi?.logoutPinterestAuth) throw new Error('Pinterest 退出登录 API 未加载');
    if (window.confirm && !window.confirm('确认删除 Pinterest browser_auth.json 并退出登录？')) return false;
    await window.DesktopApi.logoutPinterestAuth();
    pinterestAuthSessionId = '';
    window.sessionStorage?.removeItem('deskPinterestAuthSessionId');
    pinterestAuthActivity = null;
    await refresh();
    window.DesktopResults?.showTransientMessage?.('Pinterest 登录态已删除。', 'success');
    return true;
  }

  async function testComfyConnection() {
    if (!window.DesktopApi?.testComfyConnection) throw new Error('ComfyUI 连接测试 API 未加载');
    const card = els.deskSettingsBody?.querySelector('[data-system-settings-card="comfy"]');
    const payload = collectSystemSettingsForm(card)?.comfy || {};
    if (!payload.base_url) payload.base_url = setting('comfy.base_url', '');
    if (!payload.timeout_seconds) payload.timeout_seconds = setting('comfy.timeout_seconds', 120);
    lastComfyHealth = await window.DesktopApi.testComfyConnection(payload);
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    window.DesktopResults?.showTransientMessage?.(`ComfyUI 已连接，延迟 ${Number(lastComfyHealth.latency_ms || 0)}ms。`, 'success');
    return lastComfyHealth;
  }

  async function testVideoRuntimeConnection() {
    if (!window.DesktopApi?.testVideoRuntime) throw new Error('H3 Runtime 连接测试 API 未加载');
    const card = els.deskSettingsBody?.querySelector('[data-system-settings-card="video-inference"]');
    const payload = collectSystemSettingsForm(card)?.video_inference || {};
    lastVideoRuntimeStatus = await window.DesktopApi.testVideoRuntime(payload);
    window.DesktopVideoConfig?.setRuntimeStatus?.(lastVideoRuntimeStatus);
    if (lastVideoRuntimeStatus?.online && window.DesktopApi.getVideoRuntimeCapabilities) {
      lastVideoRuntimeCapabilities = await window.DesktopApi.getVideoRuntimeCapabilities();
      window.DesktopVideoConfig?.setCapabilities?.(lastVideoRuntimeCapabilities);
    }
    updateVideoRuntimeStatusView(lastVideoRuntimeStatus);
    if (!lastVideoRuntimeStatus?.online) {
      throw new Error(lastVideoRuntimeStatus?.error || lastVideoRuntimeStatus?.message || 'H3 Runtime 离线');
    }
    window.DesktopResults?.showTransientMessage?.(`H3 Runtime 已连接，延迟 ${Number(lastVideoRuntimeStatus.latency_ms || 0)}ms。`, 'success');
    return lastVideoRuntimeStatus;
  }

  async function testVideoSupervisorConnection() {
    if (!window.DesktopApi?.testVideoSupervisor) throw new Error('H3 Supervisor 检测 API 未加载');
    const card = els.deskSettingsBody?.querySelector('[data-system-settings-card="video-inference"]');
    const managerBaseUrl = card?.querySelector('[data-system-setting-field="video_inference.manager_base_url"]')?.value || '';
    lastVideoSupervisorStatus = await window.DesktopApi.testVideoSupervisor({ manager_base_url: managerBaseUrl });
    updateVideoSupervisorStatusView(lastVideoSupervisorStatus);
    if (!lastVideoSupervisorStatus?.online) {
      throw new Error(lastVideoSupervisorStatus?.error || lastVideoSupervisorStatus?.message || 'H3 Supervisor 离线');
    }
    const adminText = lastVideoSupervisorStatus.admin_initialized ? '管理员已初始化' : '管理员待初始化';
    window.DesktopResults?.showTransientMessage?.(
      `H3 Supervisor 已连接，${adminText}。`,
      lastVideoSupervisorStatus.admin_initialized ? 'success' : 'warning'
    );
    return lastVideoSupervisorStatus;
  }

  function openVideoSupervisorManager(button) {
    const managerUrl = String(button?.dataset?.videoSupervisorUrl || '').trim();
    if (!managerUrl) throw new Error('请先保存并检测有效的管理台地址');
    window.open(managerUrl, '_blank', 'noopener,noreferrer');
  }

  async function startVideoRuntimeService() {
    if (!window.DesktopApi?.startVideoRuntime || !window.DesktopApi?.saveSystemSettings) {
      throw new Error('H3 Runtime 启动 API 未加载');
    }
    const card = els.deskSettingsBody?.querySelector('[data-system-settings-card="video-inference"]');
    const payload = collectSystemSettingsForm(card);
    await window.DesktopApi.saveSystemSettings(payload);
    const result = await window.DesktopApi.startVideoRuntime();
    window.DesktopResults?.showTransientMessage?.(result.message || 'H3 Runtime 启动命令已发送。', 'success');
    window.setTimeout(() => refresh().catch(() => {}), 1800);
    return result;
  }

  function readFileAsDataUrl(file) {
    if (!file) return Promise.resolve('');
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('缩略图读取失败'));
      reader.readAsDataURL(file);
    });
  }

  async function saveComfyWorkflowConfig(button) {
    if (!window.DesktopApi?.saveComfyWorkflowConfig) throw new Error('ComfyUI 工作流配置 API 未加载');
    const editor = button?.closest('[data-comfy-workflow-editor]');
    const workflowId = editor?.dataset?.comfyWorkflowEditor || '';
    if (!workflowId) throw new Error('缺少工作流 ID');
    const payload = { id: workflowId };
    editor.querySelectorAll('[data-comfy-workflow-field]').forEach(input => {
      const field = input.dataset.comfyWorkflowField;
      if (!field) return;
      let value = input.type === 'checkbox' ? input.checked : input.value;
      if (input.type === 'number') value = Number(value);
      payload[field] = value;
    });
    const thumbnail = editor.querySelector('[data-comfy-workflow-thumbnail]')?.files?.[0];
    if (thumbnail) payload.thumbnail_data = await readFileAsDataUrl(thumbnail);
    const response = await window.DesktopApi.saveComfyWorkflowConfig(payload);
    lastComfyWorkflows = response;
    activeComfyWorkflowId = workflowId;
    window.dispatchEvent(new CustomEvent('desktop:comfy-workflows-updated', { detail: response }));
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    window.DesktopResults?.showTransientMessage?.('ComfyUI 工作流信息已保存。', 'success');
    return response;
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
    settingsDrawer?.refresh();
    updateTabs();
    // Focus moves into the drawer; search is the most useful first stop.
    els.deskSettingsSearchInput?.focus({ preventScroll: true });
    const gallery = document.getElementById('deskGalleryPanel');
    gallery?.classList.remove('is-open');
    gallery?.setAttribute('aria-hidden', 'true');
    try {
      if (!lastDiagnostics) {
        await refresh();
      } else {
        renderDiagnostics(lastDiagnostics);
      }
      if (activeTab === 'model-tools') await Promise.all([krea2Tools?.activate?.(),qwen21Tools?.activate?.(),loraSettings?.activate?.()]);
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
    const activeElement = document.activeElement;
    if (activeElement && els.deskSettingsPanel?.contains(activeElement)) {
      const trigger = document.querySelector('.desk-rail__item[data-tool="settings"]');
      if (trigger instanceof HTMLElement) trigger.focus({ preventScroll: true });
      else if (activeElement instanceof HTMLElement) activeElement.blur();
    }
    els.deskSettingsPanel?.classList.remove('is-open');
    els.deskSettingsPanel?.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('desk-settings-open');
    settingsSearch?.close();
    krea2Tools?.deactivate?.();
    qwen21Tools?.deactivate?.();
    loraSettings?.deactivate?.();
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

  function selectTab(tab) {
    const previousTab = activeTab;
    activeTab = tab || 'status';
    if (activeTab === 'browser') {
      activeTab = 'status';
    }
    updateTabs();
    if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
    if (previousTab === 'model-tools' && activeTab !== 'model-tools') {krea2Tools?.deactivate?.();qwen21Tools?.deactivate?.();loraSettings?.deactivate?.();}
    if (activeTab === 'model-tools') {
      loraSettings?.activate?.().catch(error => showSettingsFeedback(error, 'LoRA 连接设置读取失败'));
      krea2Tools?.activate?.().catch(error => showSettingsFeedback(error, '模型工具状态读取失败'));
      qwen21Tools?.activate?.().catch(error => showSettingsFeedback(error, 'Qwen 模型工具状态读取失败'));
    }
    if (activeTab === 'chatgpt-pool' && googlePoolSettings.isGoogle()) {
      void googlePoolSettings.refresh();
    } else if (activeTab === 'chatgpt-pool') {
      loadChatgptPoolAccounts().catch(error => showSettingsFeedback(error, '账号池列表读取失败'));
    }
  }

  // ---- Search: index every category's cards from the data already loaded --------------
  function settingsCategories() {
    return [...(els.deskSettingsTabs?.querySelectorAll('[data-settings-tab]') || [])]
      .map(button => ({
        tab: button.dataset.settingsTab,
        label: button.textContent.trim(),
        group: button.closest('[data-settings-group]')?.dataset.settingsGroup || ''
      }))
      .filter(category => category.tab !== 'status');
  }

  function settingsSearchIndex() {
    if (!lastDiagnostics) return [];
    if (searchIndexCache?.data === lastDiagnostics) return searchIndexCache.entries;
    const categories = settingsCategories().map(category => ({
      ...category,
      html: buildSections(lastDiagnostics, category.tab).sections
        .filter(section => section.tab === category.tab)
        .map(section => section.html)
        .join('')
    }));
    const entries = window.DesktopSettingsSearch?.buildIndex(categories) || [];
    searchIndexCache = { data: lastDiagnostics, entries };
    return entries;
  }

  function revealSearchHit(hit) {
    if (activeTab !== hit.entry.tab) selectTab(hit.entry.tab);
    const card = els.deskSettingsBody?.querySelectorAll('.desk-settings-card')[hit.entry.cardIndex];
    if (!card) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    card.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' });
    const field = hit.field && [...card.querySelectorAll('label, .desk-settings-kv, .desk-settings-path, .desk-settings-secret-field, .desk-settings-form__section-title, .desk-settings-canvas-interaction__label')]
      .find(el => el.textContent.replace(/\s+/g, ' ').trim().startsWith(hit.field));
    [card, field].filter(Boolean).forEach(el => {
      // A newer hit on the same element must not be cut short by an older timer.
      clearTimeout(searchHitTimers.get(el));
      el.classList.remove('is-search-hit');
      void el.offsetWidth;
      el.classList.add('is-search-hit');
      searchHitTimers.set(el, setTimeout(() => el.classList.remove('is-search-hit'), 1800));
    });
    // DesktopSelect enhances freshly rendered selects on the next frame and hides the
    // native <select>; wait for that, then focus what is actually rendered.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!card.isConnected) return;
      const focusable = [...(field || card).querySelectorAll('.desk-select-trigger, input:not([type="hidden"]), select, textarea, button')]
        .find(el => !el.disabled && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
      focusable?.focus({ preventScroll: true });
    }));
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
      selectTab(button.dataset.settingsTab);
    });
    els.deskSettingsBody?.addEventListener('input', event => {
      if (updateProgressPreference(event) || updateControlMaterialPreference(event)) return;
      if (loraSettings?.handleInput?.(event) || qwen21Tools?.handleInput?.(event) || krea2Tools?.handleInput?.(event)) return;
      const managerField = event.target.closest('[data-system-setting-field="video_inference.manager_base_url"]');
      if (!managerField) return;
      const managerBaseUrl = String(managerField.value || '').trim();
      lastVideoSupervisorStatus = {
        ok: true,
        online: false,
        checked: false,
        configured: Boolean(managerBaseUrl),
        base_url: managerBaseUrl,
        manager_url: '',
        message: '管理台地址已修改，等待检测'
      };
      updateVideoSupervisorStatusView(lastVideoSupervisorStatus);
    });
    els.deskSettingsBody?.addEventListener('change', event => {
      if (updateProgressPreference(event) || updateControlMaterialPreference(event)) return;
      if (loraSettings?.handleInput?.(event) || qwen21Tools?.handleInput?.(event) || krea2Tools?.handleInput?.(event)) return;
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
      if (event.target.closest('[data-control-material-accent-reset]') && updateControlMaterialPreference(event)) return;
      const progressColorReset = event.target.closest('[data-progress-color-reset]');
      if (progressColorReset) {
        const { style, colors } = window.DesktopProgressModel.normalizePreferences(window.DesktopPreferences.state.progress);
        delete colors[style];
        window.DesktopPreferences.setProgressPreferences({ colors });
        syncProgressSettings(progressColorReset.closest('[data-progress-settings]'));
        return;
      }
      if (loraSettings?.handleClick?.(event) || qwen21Tools?.handleClick?.(event) || krea2Tools?.handleClick?.(event)) return;
      if (googlePoolSettings.handleClick(event)) return;
      const videoRuntimeMode = event.target.closest('[data-video-runtime-mode]');
      if (videoRuntimeMode) {
        event.preventDefault();
        const card = videoRuntimeMode.closest('[data-system-settings-card="video-inference"]');
        const mode = videoRuntimeMode.dataset.videoRuntimeMode || 'auto';
        const hiddenInput = card?.querySelector('[data-system-setting-field="video_inference.runtime_mode"]');
        if (hiddenInput) hiddenInput.value = mode;
        card?.querySelectorAll('[data-video-runtime-mode]').forEach(button => {
          const active = button.dataset.videoRuntimeMode === mode;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        card?.querySelectorAll('[data-video-runtime-mode-panel]').forEach(panel => {
          const panelMode = panel.dataset.videoRuntimeModePanel;
          panel.hidden = mode === 'local' ? panelMode !== 'local' : (mode === 'lan' ? panelMode !== 'lan' : false);
        });
        return;
      }
      const videoRuntimeTest = event.target.closest('[data-video-runtime-test]');
      if (videoRuntimeTest) {
        event.preventDefault();
        runButtonAction(videoRuntimeTest, testVideoRuntimeConnection, {
          loadingText: '检测中...',
          doneText: '已连接',
          errorMessage: 'H3 Runtime 连接失败'
        });
        return;
      }
      const videoRuntimeStart = event.target.closest('[data-video-runtime-start]');
      if (videoRuntimeStart) {
        event.preventDefault();
        runButtonAction(videoRuntimeStart, startVideoRuntimeService, {
          loadingText: '启动中...',
          doneText: '已启动',
          errorMessage: 'H3 Runtime 启动失败'
        });
        return;
      }
      const videoSupervisorRefresh = event.target.closest('[data-video-supervisor-refresh]');
      if (videoSupervisorRefresh) {
        event.preventDefault();
        runButtonAction(videoSupervisorRefresh, testVideoSupervisorConnection, {
          loadingText: '检测中...',
          doneText: '已连接',
          errorMessage: 'H3 Supervisor 连接失败'
        });
        return;
      }
      const videoSupervisorOpen = event.target.closest('[data-video-supervisor-open]');
      if (videoSupervisorOpen) {
        event.preventDefault();
        try {
          openVideoSupervisorManager(videoSupervisorOpen);
        } catch (error) {
          showSettingsFeedback(error, '管理台打开失败');
        }
        return;
      }
      const swellStyleButton = event.target.closest('button[data-connection-swell-style]');
      const collisionButton = event.target.closest('button[data-canvas-collision]');
      if (collisionButton) {
        event.preventDefault();
        const enabled = collisionButton.dataset.canvasCollision === 'true';
        window.DesktopPreferences?.setCanvasCollisionEnabled?.(enabled);
        collisionButton.parentElement?.querySelectorAll('[data-canvas-collision]').forEach(button => {
          const active = (button.dataset.canvasCollision === 'true') === enabled;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', String(active));
        });
        return;
      }
      if (swellStyleButton) {
        event.preventDefault();
        const style = window.DesktopPreferences?.normalizeConnectionSwellStyle?.(
          swellStyleButton.dataset.connectionSwellStyle
        ) || 'liquid';
        window.DesktopPreferences?.setConnectionSwellStyle?.(style);
        swellStyleButton.parentElement?.querySelectorAll('[data-connection-swell-style]').forEach(button => {
          const active = button.dataset.connectionSwellStyle === style;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        return;
      }
      const lineStyleButton = event.target.closest('button[data-connection-line-style]');
      if (lineStyleButton) {
        event.preventDefault();
        const style = window.DesktopPreferences?.normalizeConnectionLineStyle?.(
          lineStyleButton.dataset.connectionLineStyle
        ) || 'straight';
        window.DesktopPreferences?.setConnectionLineStyle?.(style);
        lineStyleButton.parentElement?.querySelectorAll('[data-connection-line-style]').forEach(button => {
          const active = button.dataset.connectionLineStyle === style;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        return;
      }
      const comfyWorkflowCard = event.target.closest('[data-comfy-workflow-edit]');
      if (comfyWorkflowCard) {
        event.preventDefault();
        activeComfyWorkflowId = comfyWorkflowCard.dataset.comfyWorkflowEdit || '';
        if (lastDiagnostics) renderDiagnostics(lastDiagnostics);
        return;
      }
      const comfyTest = event.target.closest('[data-comfy-connection-test]');
      if (comfyTest) {
        event.preventDefault();
        runButtonAction(comfyTest, testComfyConnection, {
          loadingText: '测试中...',
          doneText: '已连接',
          errorMessage: 'ComfyUI 连接失败'
        });
        return;
      }
      const comfyWorkflowSave = event.target.closest('[data-comfy-workflow-save]');
      if (comfyWorkflowSave) {
        event.preventDefault();
        runButtonAction(comfyWorkflowSave, () => saveComfyWorkflowConfig(comfyWorkflowSave), {
          loadingText: '保存中...',
          doneText: '已保存',
          errorMessage: '工作流信息保存失败'
        });
        return;
      }
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
      const pinterestVerify = event.target.closest('[data-pinterest-auth-verify]');
      if (pinterestVerify) {
        event.preventDefault();
        runButtonAction(pinterestVerify, () => verifyPinterestAuth(pinterestVerify), {
          loadingText: '验证中...',
          doneText: '验证通过',
          errorMessage: 'Pinterest 登录态验证失败'
        });
        return;
      }
      const pinterestStart = event.target.closest('[data-pinterest-auth-start]');
      if (pinterestStart) {
        event.preventDefault();
        runButtonAction(pinterestStart, () => startPinterestAuth(pinterestStart), {
          loadingText: '打开中...',
          doneText: '已打开',
          errorMessage: 'Pinterest 登录窗口打开失败'
        });
        return;
      }
      const pinterestComplete = event.target.closest('[data-pinterest-auth-complete]');
      if (pinterestComplete) {
        event.preventDefault();
        runButtonAction(pinterestComplete, completePinterestAuth, {
          loadingText: '读取中...',
          doneText: '已登录',
          errorMessage: 'Pinterest 登录完成失败'
        });
        return;
      }
      const pinterestCancel = event.target.closest('[data-pinterest-auth-cancel]');
      if (pinterestCancel) {
        event.preventDefault();
        runButtonAction(pinterestCancel, cancelPinterestAuth, {
          loadingText: '关闭中...',
          doneText: '已取消',
          errorMessage: 'Pinterest 登录取消失败'
        });
        return;
      }
      const pinterestLogout = event.target.closest('[data-pinterest-auth-logout]');
      if (pinterestLogout) {
        event.preventDefault();
        runButtonAction(pinterestLogout, logoutPinterestAuth, {
          loadingText: '退出中...',
          doneText: '已退出',
          errorMessage: 'Pinterest 退出登录失败'
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
      // An open colour picker closes before the drawer (focus may have left it).
      if (window.DesktopColorBloom?.close(els.deskSettingsPanel, { focus: true })) return;
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
    loraSettings = window.DesktopLoRASettings.create({
      library: DesktopApi.lora,
      rerender: () => { if (activeTab === 'model-tools' && lastDiagnostics) renderDiagnostics(lastDiagnostics); },
      notify: message => window.DesktopResults?.showTransientMessage?.(message)
    });
    krea2Tools = window.DesktopKrea2Tools?.create?.({
      api: window.DesktopKrea2API,
      escapeHtml,
      rerender: () => {
        if (activeTab === 'model-tools' && lastDiagnostics) renderDiagnostics(lastDiagnostics);
      },
      notify: (message, tone) => window.DesktopResults?.showTransientMessage?.(message, tone)
    }) || null;
    qwen21Tools = window.DesktopQwen21Tools?.create?.({
      api: window.DesktopQwen21API, escapeHtml,
      rerender: () => { if (activeTab === 'model-tools' && lastDiagnostics) renderDiagnostics(lastDiagnostics); },
      notify: (message, tone) => window.DesktopResults?.showTransientMessage?.(message, tone)
    }) || null;
    settingsDrawer = window.DesktopSettingsDrawer?.create({
      panel: els.deskSettingsPanel,
      handle: els.deskSettingsResize,
      getWidth: () => window.DesktopPreferences?.state?.settingsWidth,
      setWidth: width => window.DesktopPreferences?.setSettingsWidth?.(width)
    }) || null;
    settingsSearch = window.DesktopSettingsSearch?.create({
      input: els.deskSettingsSearchInput,
      results: els.deskSettingsSearchResults,
      getIndex: settingsSearchIndex,
      onSelect: revealSearchHit
    }) || null;
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
