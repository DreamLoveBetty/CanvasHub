// Auth and shared API helpers
  const tg = window.Telegram && Telegram.WebApp;
  const AUTH_TOKEN_STORAGE_KEY = 'miniapp_auth_token_v1';
  let TELEGRAM_INIT_DATA = '';
  let AUTH_TOKEN = '';
  let AUTH_STATE = 'checking';
  const AUTH_STATE_WAITERS = [];

  function setAuthState(state) {
    AUTH_STATE = state;
    const isResolvedState = state === 'authenticated' || state === 'unauthenticated';
    if (!isResolvedState) return;
    while (AUTH_STATE_WAITERS.length) {
      const resolve = AUTH_STATE_WAITERS.shift();
      resolve(state === 'authenticated');
    }
  }

  function isMiniappAuthReady() {
    return AUTH_STATE === 'authenticated';
  }

  function waitForMiniappAuthReady(timeoutMs = 8000) {
    if (AUTH_STATE === 'authenticated') return Promise.resolve(true);
    if (AUTH_STATE === 'unauthenticated') return Promise.resolve(false);

    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        const index = AUTH_STATE_WAITERS.indexOf(done);
        if (index >= 0) AUTH_STATE_WAITERS.splice(index, 1);
        resolve(AUTH_STATE === 'authenticated');
      }, timeoutMs);

      function done(ok) {
        window.clearTimeout(timer);
        resolve(ok);
      }

      AUTH_STATE_WAITERS.push(done);
    });
  }

  window.isMiniappAuthReady = isMiniappAuthReady;
  window.waitForMiniappAuthReady = waitForMiniappAuthReady;
  if (tg) {
    tg.expand();
    tg.ready();
  }

  function getInitData() {
    try {
      // URL params take priority (works with static export and Telegram hash redirects)
      const searchParams = new URLSearchParams(window.location.search || '');
      const hashParams = new URLSearchParams(String(window.location.hash || '').replace(/^#/, ''));
      const fromUrl = searchParams.get('tgWebAppData') || searchParams.get('initData') || hashParams.get('tgWebAppData') || hashParams.get('initData') || '';
      if (fromUrl) return decodeURIComponent(fromUrl);

      // Try Telegram WebApp
      if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
        return window.Telegram.WebApp.initData;
      }
    } catch (e) {
      console.log('[Auth] getInitData error:', e.message);
    }
    return '';
  }

  function isLikelyTelegramWebView() {
    return !!(window.Telegram && window.Telegram.WebApp);
  }

  function waitForInitData(timeoutMs = 2200) {
    const startedAt = Date.now();
    return new Promise((resolve) => {
      const tick = () => {
        const initData = getInitData();
        if (initData || Date.now() - startedAt >= timeoutMs || !isLikelyTelegramWebView()) {
          resolve(initData);
          return;
        }
        setTimeout(tick, 120);
      };
      tick();
    });
  }

  function setTelegramInitDataHeader(headers, initData) {
    if (!headers || !initData) return;
    try {
      headers.set('X-Telegram-Init-Data', initData);
    } catch (e) {
      headers.set('X-Telegram-Init-Data-Encoded', encodeURIComponent(initData));
    }
  }

  function showAuthOverlay(message, showInput = false) {
    const overlay = document.getElementById('authOverlay');
    const msg = document.getElementById('authMessage');
    const inputRow = document.getElementById('authInputRow');
    if (msg) msg.textContent = message || '请在 Telegram 中打开此小程序。';
    if (inputRow) inputRow.style.display = showInput ? 'flex' : 'none';
    if (overlay) overlay.style.display = 'flex';

    const debugEl = document.getElementById('authDebug');
    if (!debugEl) {
      const debugDiv = document.createElement('div');
      debugDiv.id = 'authDebug';
      debugDiv.className = 'mt-3 rounded bg-slate-100 p-2 text-left text-xs text-slate-500';
      debugDiv.style.cssText = 'margin-top:12px;padding:8px;background:#f1f5f9;border-radius:6px;font-size:11px;text-align:left;word-break:break-all;max-height:120px;overflow:auto;';
      const authCard = document.querySelector('.auth-card');
      if (authCard && !document.getElementById('authDebug')) authCard.appendChild(debugDiv);
    }
    const debug = document.getElementById('authDebug');
    if (debug) {
      const initData = getInitData();
      debug.innerHTML = '<p class="font-semibold">Debug:</p><p>initData: ' + (initData ? initData.slice(0,30) + '...' : 'null') + '</p><p>URL params: ' + window.location.search + '</p>';
    }
  }

  function hideAuthOverlay() {
    const overlay = document.getElementById('authOverlay');
    if (overlay) overlay.style.display = 'none';
  }

  function getStoredAuthToken() {
    if (AUTH_TOKEN) return AUTH_TOKEN;
    try {
      const hashParams = new URLSearchParams(String(window.location.hash || '').replace(/^#/, ''));
      const hashToken = hashParams.get('miniappAuth') || hashParams.get('authToken') || '';
      if (hashToken) {
        AUTH_TOKEN = hashToken;
        return hashToken;
      }
    } catch (e) {}
    try {
      AUTH_TOKEN = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || '';
      return AUTH_TOKEN;
    } catch (e) {}
    return '';
  }

  function syncAuthCookie(token) {
    const value = String(token || '').trim();
    if (!value) return;
    try {
      document.cookie = `miniapp_auth=${encodeURIComponent(value)}; Max-Age=${7 * 24 * 60 * 60}; Path=/; SameSite=Lax`;
    } catch (e) {}
  }

  function getMiniappAuthToken() {
    const token = getStoredAuthToken();
    if (token) syncAuthCookie(token);
    return token;
  }

  function miniappMediaUrl(url) {
    const raw = String(url || '').trim();
    if (!raw || raw.startsWith('data:') || raw.startsWith('blob:')) return raw;
    const token = getMiniappAuthToken();
    if (!token) return raw;
    try {
      const parsed = new URL(raw, window.location.origin);
      if (parsed.origin !== window.location.origin) return raw;
      const protectedPath = ['/image/', '/archive_image/', '/source_image/', '/thumb/', '/google_outputs/', '/gpt_outputs/'].some(prefix => parsed.pathname.startsWith(prefix));
      if (!protectedPath) return raw;
      parsed.searchParams.set('miniappAuth', token);
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch (e) {
      return raw;
    }
  }

  window.getMiniappAuthToken = getMiniappAuthToken;
  window.miniappMediaUrl = miniappMediaUrl;

  function storeAuthToken(token) {
    if (!token) return;
    AUTH_TOKEN = token;
    syncAuthCookie(token);
    try {
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    } catch (e) {}
    try {
      const hashParams = new URLSearchParams(String(window.location.hash || '').replace(/^#/, ''));
      hashParams.set('miniappAuth', token);
      history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${hashParams.toString()}`);
    } catch (e) {}
  }

  function clearStoredAuthToken() {
    AUTH_TOKEN = '';
    try {
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    } catch (e) {}
    try {
      const hashParams = new URLSearchParams(String(window.location.hash || '').replace(/^#/, ''));
      hashParams.delete('miniappAuth');
      hashParams.delete('authToken');
      const nextHash = hashParams.toString();
      history.replaceState(null, '', `${window.location.pathname}${window.location.search}${nextHash ? `#${nextHash}` : ''}`);
    } catch (e) {}
  }

  const api = {
    async request(path, options = {}) {
      const headers = new Headers(options.headers || {});

      const initData = TELEGRAM_INIT_DATA || getInitData();
      if (initData) {
        setTelegramInitDataHeader(headers, initData);
      }
      const authToken = getStoredAuthToken();
      if (authToken) {
        headers.set('X-Miniapp-Auth', authToken);
      }

      try {
        const resp = await fetch(path, { ...options, headers, credentials: 'same-origin' });
        if (resp.status === 401) {
          if (authToken && getStoredAuthToken() === authToken) {
            clearStoredAuthToken();
            setAuthState('unauthenticated');
            showAuthOverlay('登录状态已失效，请重新输入访问密码。', true);
          } else if (!authToken) {
            setAuthState('unauthenticated');
            showAuthOverlay('登录状态已失效，请重新输入访问密码。', true);
          }
        }
        return resp;
      } catch (error) {
        if (error.message.includes('502') || error.message.includes('Failed to fetch')) {
          console.error('🔴 API request failed - possible proxy issue');
          const proxyError = new Error('网络连接问题：本地 API 请求被代理拦截。\n\n请确保：\n1. Clash Verge 已添加 localhost 绕过规则\n2. 或暂时关闭系统代理\n\n已在 Clash 配置中自动添加绕过规则，重启 Clash 后生效。');
          proxyError.isProxyError = true;
          throw proxyError;
        }
        throw error;
      }
    },
    async json(path, options = {}) {
      const resp = await api.request(path, options);
      let data = {};
      try { data = await resp.json(); } catch (e) {}
      if (!resp.ok) {
        throw new Error(data.error || ('HTTP ' + resp.status));
      }
      return data;
    },
    async blob(path, options = {}) {
      const resp = await api.request(path, options);
      if (!resp.ok) {
        throw new Error('HTTP ' + resp.status);
      }
      return resp.blob();
    }
  };

  async function handleManualAuth() {
    const pwd = document.getElementById('authPassword').value.trim();
    if (!pwd) return;
    try {
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd })
      });
      const data = await resp.json();
      if (data.ok) {
        storeAuthToken(data.auth_token);
        setAuthState('authenticated');
        const input = document.getElementById('authPassword');
        if (input) input.value = '';
        hideAuthOverlay();
        if (typeof loadHistory === 'function') {
          loadHistory({ force: true }).catch(() => {});
        } else if (typeof scheduleHistoryLoad === 'function') {
          scheduleHistoryLoad({ force: true });
        }
      } else {
        alert('密码错误');
      }
    } catch (e) {
      alert('验证失败: ' + e.message);
    }
  }

  async function verifyAuth() {
    try {
      setAuthState('checking');
      const headers = new Headers({ 'Content-Type': 'application/json' });
      const initData = TELEGRAM_INIT_DATA || await waitForInitData();
      if (initData) {
        TELEGRAM_INIT_DATA = initData;
        setTelegramInitDataHeader(headers, initData);
      }
      const authToken = getStoredAuthToken();
      if (authToken) {
        headers.set('X-Miniapp-Auth', authToken);
      }
      const resp = await fetch('/api/auth/verify', {
        method: 'POST',
        credentials: 'same-origin',
        headers
      });
      let data = {};
      try { data = await resp.json(); } catch (_) {}

      if (resp.ok && data.ok) {
        storeAuthToken(data.auth_token);
        setAuthState('authenticated');
        hideAuthOverlay();
        return;
      }
      if (authToken && getStoredAuthToken() === authToken) {
        clearStoredAuthToken();
      }
      setAuthState('unauthenticated');
      showAuthOverlay(isLikelyTelegramWebView() ? 'Telegram 身份验证未完成，请关闭后重新打开小程序，或输入访问密码继续。' : '请输入访问密码后继续。', true);
    } catch (e) {
      setAuthState('unauthenticated');
      showAuthOverlay('无法验证当前登录状态，请输入访问密码。', true);
    }
  }

  setTimeout(verifyAuth, 100);
