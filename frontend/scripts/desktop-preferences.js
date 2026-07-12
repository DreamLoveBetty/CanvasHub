(function () {
  const PREF_KEY = 'desktop_ui_preferences_v1';
  const SUPPORTED_LANGUAGES = new Set(['zh', 'en']);
  const SUPPORTED_THEMES = new Set(['light', 'dark']);

  const state = {
    theme: 'light',
    language: 'zh',
  };
  let themeTransitionTimer = null;
  let themeRevealInProgress = false;
  const THEME_REVEAL_DURATION_MS = 960;

  function normalizeTheme(value) {
    const theme = String(value || '').trim().toLowerCase();
    return SUPPORTED_THEMES.has(theme) ? theme : 'light';
  }

  function normalizeLanguage(value) {
    const language = String(value || '').trim().toLowerCase();
    return window.DesktopI18n?.normalizeLanguage?.(language) || (SUPPORTED_LANGUAGES.has(language) ? language : 'zh');
  }

  function readPreferences() {
    try {
      const parsed = JSON.parse(localStorage.getItem(PREF_KEY) || '{}');
      state.theme = normalizeTheme(parsed.theme);
      state.language = normalizeLanguage(parsed.language);
    } catch (e) {
      state.theme = 'light';
      state.language = 'zh';
    }
  }

  function savePreferences() {
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify({
        theme: state.theme,
        language: state.language,
      }));
    } catch (e) {}
  }

  function t(key, language = state.language) {
    return window.DesktopI18n?.t?.(key, language) || key;
  }

  function applyLanguage(language = state.language) {
    state.language = normalizeLanguage(language);
    window.DesktopI18n?.apply?.(state.language);

    const select = document.getElementById('deskLanguageSelect');
    if (select && select.value !== state.language) select.value = state.language;
    updateThemeButton();
  }

  function applyTheme(theme = state.theme) {
    state.theme = normalizeTheme(theme);
    document.body?.setAttribute('data-theme', state.theme);
    document.documentElement.setAttribute('data-theme', state.theme);
    updateThemeButton();
  }

  function startThemeTransition() {
    const body = document.body;
    if (!body) return;
    if (themeTransitionTimer) window.clearTimeout(themeTransitionTimer);
    body.classList.add('theme-is-transitioning');
    themeTransitionTimer = window.setTimeout(() => {
      body.classList.remove('theme-is-transitioning');
      themeTransitionTimer = null;
    }, 520);
  }

  function resolveThemeTransitionOrigin(options = {}) {
    const event = options.event || options.originEvent || null;
    if (
      event &&
      Number.isFinite(event.clientX) &&
      Number.isFinite(event.clientY) &&
      (event.detail > 0 || event.clientX > 0 || event.clientY > 0)
    ) {
      return { x: event.clientX, y: event.clientY };
    }

    const source = options.sourceElement || document.getElementById('deskThemeToggle');
    if (source?.getBoundingClientRect) {
      const rect = source.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        return {
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        };
      }
    }

    return {
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    };
  }

  function shouldUseCircularThemeTransition() {
    if (!document.body || typeof window.requestAnimationFrame !== 'function') return false;
    try {
      return !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    } catch (e) {
      return true;
    }
  }

  function easeThemeReveal(t) {
    return 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
  }

  function animateThemeRevealOverlay(overlay, endRadius) {
    return new Promise(resolve => {
      const startedAt = performance.now();
      const frame = now => {
        const progress = Math.min(1, (now - startedAt) / THEME_REVEAL_DURATION_MS);
        const eased = easeThemeReveal(progress);
        overlay.style.setProperty('--theme-reveal-radius', `${Math.ceil(endRadius * eased)}px`);
        if (progress < 1) {
          window.requestAnimationFrame(frame);
        } else {
          resolve();
        }
      };
      window.requestAnimationFrame(frame);
    });
  }

  function runCircularThemeTransition(nextTheme, options = {}) {
    const root = document.documentElement;
    const body = document.body;
    const targetTheme = normalizeTheme(nextTheme);
    const previousTheme = state.theme;
    if (themeRevealInProgress) {
      applyTheme(targetTheme);
      return Promise.resolve();
    }
    const origin = resolveThemeTransitionOrigin(options);
    const maxX = Math.max(origin.x, window.innerWidth - origin.x);
    const maxY = Math.max(origin.y, window.innerHeight - origin.y);
    const endRadius = Math.ceil(Math.hypot(maxX, maxY));

    themeRevealInProgress = true;
    root?.classList.add('theme-reveal-transitioning');
    body?.classList.add('theme-reveal-transitioning');

    const overlay = document.createElement('div');
    overlay.className = 'desk-theme-reveal-overlay';
    overlay.dataset.theme = previousTheme;
    overlay.style.setProperty('--theme-reveal-x', `${origin.x}px`);
    overlay.style.setProperty('--theme-reveal-y', `${origin.y}px`);
    overlay.style.setProperty('--theme-reveal-radius', '0px');
    body?.appendChild(overlay);

    applyTheme(targetTheme);

    const cleanup = () => {
      overlay.remove();
      root?.classList.remove('theme-reveal-transitioning');
      body?.classList.remove('theme-reveal-transitioning');
      themeRevealInProgress = false;
    };

    return animateThemeRevealOverlay(overlay, endRadius)
      .catch(() => {})
      .then(cleanup);
  }

  function updateThemeButton() {
    const button = document.getElementById('deskThemeToggle');
    const text = document.getElementById('deskThemeToggleText');
    if (!button) return;
    const isDark = state.theme === 'dark';
    button.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    button.dataset.theme = state.theme;
    button.setAttribute('aria-label', t('themeToggleTitle'));
    button.setAttribute('title', t('themeToggleTitle'));
    if (text) {
      text.dataset.i18n = isDark ? 'themeDark' : 'themeLight';
      text.textContent = t(isDark ? 'themeDark' : 'themeLight');
    }
  }

  function emitThemeChange(theme = state.theme) {
    window.dispatchEvent(new CustomEvent('desktop:theme-change', {
      detail: { theme },
    }));
  }

  function setTheme(theme, options = {}) {
    const nextTheme = normalizeTheme(theme);
    const shouldAnimate = nextTheme !== state.theme;
    let themeChangeFinished = null;
    if (shouldAnimate && shouldUseCircularThemeTransition()) {
      try {
        themeChangeFinished = runCircularThemeTransition(nextTheme, options);
      } catch (e) {
        startThemeTransition();
        applyTheme(nextTheme);
      }
    } else {
      if (shouldAnimate) startThemeTransition();
      applyTheme(nextTheme);
    }
    savePreferences();
    if (themeChangeFinished?.then) {
      themeChangeFinished.then(() => emitThemeChange(nextTheme));
    } else {
      emitThemeChange(state.theme);
    }
  }

  function setLanguage(language) {
    applyLanguage(language);
    savePreferences();
    window.DesktopI18n?.setLanguage?.(state.language, { persist: false, emit: false });
    window.dispatchEvent(new CustomEvent('desktop:language-change', {
      detail: { language: state.language },
    }));
  }

  function toggleTheme(event) {
    setTheme(state.theme === 'dark' ? 'light' : 'dark', {
      event,
      sourceElement: event?.currentTarget || document.getElementById('deskThemeToggle'),
    });
  }

  function bindControls() {
    document.getElementById('deskThemeToggle')?.addEventListener('click', toggleTheme);
    document.getElementById('deskLanguageSelect')?.addEventListener('change', (event) => {
      setLanguage(event.target.value);
    });
  }

  function init() {
    readPreferences();
    applyTheme(state.theme);
    applyLanguage(state.language);
    bindControls();
  }

  window.DesktopPreferences = {
    state,
    t,
    init,
    setTheme,
    setLanguage,
    toggleTheme,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();

(function () {
  const SEEN_RELEASE_KEY = 'desktop_release_notes_seen_v1';
  const RELEASES = [
    {
      id: '20260712-1',
      version: 'V26.0.0.1',
      date: '2026-07-12',
      title: {
        zh: '画布能力与连接体验更新',
        en: 'Canvas and account connection updates',
      },
      items: {
        zh: [
          '画布节点支持组合与解组，成组内容可一起选择、移动和对齐。',
          'PSD 分层文件可在预览中独立显示或隐藏图层。',
          'Codex 与 ChatGPT 账号连接流程更稳定，状态反馈更清晰。',
        ],
        en: [
          'Canvas nodes can now be grouped, moved, and aligned together.',
          'PSD previews now support showing or hiding individual layers.',
          'Codex and ChatGPT account connection flows are more reliable and easier to follow.',
        ],
      },
    },
  ];

  const copy = {
    zh: {
      trigger: '版本更新',
      close: '关闭版本更新',
      title: '版本更新',
      current: '当前版本',
      latest: '最新',
      updateAvailable: '发现新版本',
      updateDownloaded: '新版本已下载',
      updateAvailableBody: '新版已经发布，可前往 GitHub Releases 查看并下载。',
      sourceUpdateBody: '新版已经发布，请查看 Release 并按说明更新源码。',
      dockerUpdateBody: '新版已经发布，请拉取最新镜像并重启容器。',
      updateDownloadedBody: '新版已准备完成，将在退出应用后尝试安装。',
      viewUpdate: '查看更新',
      available: '可更新',
    },
    en: {
      trigger: 'Product updates',
      close: 'Close product updates',
      title: 'Product updates',
      current: 'Current version',
      latest: 'Latest',
      updateAvailable: 'Update available',
      updateDownloaded: 'Update downloaded',
      updateAvailableBody: 'A new release is available on GitHub Releases.',
      sourceUpdateBody: 'A new release is available. Open the release and update the source deployment.',
      dockerUpdateBody: 'A new release is available. Pull the latest image and restart the container.',
      updateDownloadedBody: 'The update is ready and will be installed when the app exits.',
      viewUpdate: 'View update',
      available: 'Available',
    },
  };

  const elements = {};
  let appUpdateStatus = { state: 'idle' };
  let backendUpdateRequest = null;

  function language() {
    return window.DesktopPreferences?.state?.language === 'en'
      || window.DesktopI18n?.state?.language === 'en'
      ? 'en'
      : 'zh';
  }

  function latestRelease() {
    return RELEASES[0] || null;
  }

  function appVersion() {
    const version = appUpdateStatus.currentVersion
      || document.body?.dataset.appVersion
      || document.querySelector('meta[name="canvashub-version"]')?.content
      || latestRelease()?.version
      || '';
    return /^v/i.test(version) ? version : `V${version}`;
  }

  function hasAvailableAppUpdate() {
    return ['available', 'downloaded'].includes(String(appUpdateStatus.state || ''))
      && !!String(appUpdateStatus.version || '').trim();
  }

  function hasUnreadRelease() {
    if (hasAvailableAppUpdate()) return true;
    const latest = latestRelease();
    if (!latest) return false;
    try {
      return localStorage.getItem(SEEN_RELEASE_KEY) !== latest.id;
    } catch (error) {
      return true;
    }
  }

  function updateUnreadState() {
    const unread = hasUnreadRelease();
    elements.root?.classList.toggle('has-unread', unread);
    elements.root?.classList.toggle('has-update', hasAvailableAppUpdate());
    elements.trigger?.setAttribute('data-unread', unread ? 'true' : 'false');
  }

  function markLatestReleaseSeen() {
    const latest = latestRelease();
    if (!latest) return;
    try {
      localStorage.setItem(SEEN_RELEASE_KEY, latest.id);
    } catch (error) {}
    updateUnreadState();
  }

  function createReleaseItem(release, index, lang) {
    const article = document.createElement('article');
    article.className = 'desk-release__item';

    const meta = document.createElement('div');
    meta.className = 'desk-release__meta';

    const version = document.createElement('strong');
    version.textContent = release.version;
    meta.appendChild(version);

    if (index === 0) {
      const latest = document.createElement('span');
      latest.className = 'desk-release__latest';
      latest.textContent = copy[lang].latest;
      meta.appendChild(latest);
    }

    const date = document.createElement('time');
    date.dateTime = release.date;
    date.textContent = release.date;
    meta.appendChild(date);

    const title = document.createElement('h3');
    title.textContent = release.title[lang];

    const list = document.createElement('ul');
    release.items[lang].forEach(text => {
      const item = document.createElement('li');
      item.textContent = text;
      list.appendChild(item);
    });

    article.append(meta, title, list);
    return article;
  }

  function createAppUpdateItem(lang) {
    if (!hasAvailableAppUpdate()) return null;
    const labels = copy[lang];
    const article = document.createElement('article');
    article.className = 'desk-release__item desk-release__item--update';

    const meta = document.createElement('div');
    meta.className = 'desk-release__meta';
    const version = document.createElement('strong');
    const rawVersion = String(appUpdateStatus.version || '').trim();
    version.textContent = /^v/i.test(rawVersion) ? rawVersion : `V${rawVersion}`;
    const badge = document.createElement('span');
    badge.className = 'desk-release__latest';
    badge.textContent = labels.available;
    meta.append(version, badge);
    const releaseDate = String(appUpdateStatus.releaseDate || '').slice(0, 10);
    if (releaseDate) {
      const date = document.createElement('time');
      date.dateTime = String(appUpdateStatus.releaseDate || '');
      date.textContent = releaseDate;
      meta.appendChild(date);
    }

    const title = document.createElement('h3');
    title.textContent = String(appUpdateStatus.releaseName || '').trim() || (appUpdateStatus.state === 'downloaded'
      ? labels.updateDownloaded
      : labels.updateAvailable);
    const body = document.createElement('p');
    body.className = 'desk-release__update-copy';
    if (appUpdateStatus.state === 'downloaded') {
      body.textContent = labels.updateDownloadedBody;
    } else if (appUpdateStatus.deployment === 'docker') {
      body.textContent = labels.dockerUpdateBody;
    } else if (appUpdateStatus.deployment === 'source') {
      body.textContent = labels.sourceUpdateBody;
    } else {
      body.textContent = labels.updateAvailableBody;
    }
    article.append(meta, title, body);

    const releaseUrl = String(appUpdateStatus.releaseUrl || '').trim();
    if (/^https:\/\//i.test(releaseUrl)) {
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'desk-release__update-action';
      action.textContent = labels.viewUpdate;
      action.addEventListener('click', () => {
        if (window.CanvasHubDesktop?.openExternal) {
          window.CanvasHubDesktop.openExternal(releaseUrl).catch(() => {});
          return;
        }
        const opened = window.open(releaseUrl, '_blank', 'noopener,noreferrer');
        if (opened) opened.opener = null;
      });
      article.appendChild(action);
    }
    return article;
  }

  function applyAppUpdateStatus(status) {
    if (!status || typeof status !== 'object') return;
    appUpdateStatus = { ...appUpdateStatus, ...status };
    render();
  }

  function applyBackendUpdateStatus(payload) {
    if (!payload || payload.ok === false) return;
    applyAppUpdateStatus({
      state: payload.update_available ? 'available' : 'current',
      currentVersion: payload.current_version || '',
      version: payload.latest_version || '',
      releaseName: payload.release_name || '',
      releaseDate: payload.release_date || '',
      releaseUrl: payload.release_url || '',
      deployment: payload.deployment || 'source',
      stale: payload.stale === true,
      checkError: payload.check_error || '',
    });
  }

  function loadBackendUpdateStatus() {
    if (window.CanvasHubDesktop?.getUpdateStatus || !window.DesktopApi?.getAppUpdateStatus) {
      return Promise.resolve();
    }
    if (backendUpdateRequest) return backendUpdateRequest;
    backendUpdateRequest = window.DesktopApi.getAppUpdateStatus()
      .then(applyBackendUpdateStatus)
      .catch(() => {})
      .finally(() => {
        backendUpdateRequest = null;
      });
    return backendUpdateRequest;
  }

  function render() {
    if (!elements.list) return;
    const lang = language();
    const labels = copy[lang];

    elements.trigger.setAttribute('aria-label', labels.trigger);
    elements.trigger.setAttribute('title', labels.trigger);
    elements.close.setAttribute('aria-label', labels.close);
    elements.close.setAttribute('title', labels.close);
    elements.title.textContent = labels.title;
    elements.currentLabel.textContent = labels.current;
    elements.currentVersion.textContent = appVersion();

    const updateItem = createAppUpdateItem(lang);
    const releaseItems = RELEASES.map((release, index) => createReleaseItem(release, index, lang));
    elements.list.replaceChildren(...(updateItem ? [updateItem, ...releaseItems] : releaseItems));
    updateUnreadState();
  }

  function isOpen() {
    return elements.trigger?.getAttribute('aria-expanded') === 'true';
  }

  function openPanel() {
    if (!elements.panel || isOpen()) return;
    elements.panel.hidden = false;
    elements.trigger.setAttribute('aria-expanded', 'true');
    elements.root.classList.add('is-open');
    markLatestReleaseSeen();
  }

  function closePanel(options = {}) {
    if (!elements.panel || !isOpen()) return;
    elements.panel.hidden = true;
    elements.trigger.setAttribute('aria-expanded', 'false');
    elements.root.classList.remove('is-open');
    if (options.restoreFocus) elements.trigger.focus();
  }

  function togglePanel() {
    if (isOpen()) closePanel();
    else openPanel();
  }

  function bindEvents() {
    elements.trigger.addEventListener('click', togglePanel);
    elements.close.addEventListener('click', () => closePanel({ restoreFocus: true }));
    document.addEventListener('pointerdown', event => {
      if (isOpen() && !elements.root.contains(event.target)) closePanel();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && isOpen()) closePanel({ restoreFocus: true });
    });
    window.addEventListener('desktop:language-change', render);
    const bridge = window.CanvasHubDesktop;
    if (bridge?.getUpdateStatus) {
      bridge.getUpdateStatus().then(applyAppUpdateStatus).catch(() => {});
      bridge.onUpdateStatus?.(applyAppUpdateStatus);
    } else {
      loadBackendUpdateStatus();
      window.addEventListener('miniapp:auth-state-change', event => {
        if (event.detail?.state === 'authenticated') loadBackendUpdateStatus();
      });
    }
  }

  function init() {
    Object.assign(elements, {
      root: document.getElementById('deskRelease'),
      trigger: document.getElementById('deskReleaseTrigger'),
      panel: document.getElementById('deskReleasePanel'),
      close: document.getElementById('deskReleaseClose'),
      title: document.getElementById('deskReleaseTitle'),
      list: document.getElementById('deskReleaseList'),
      currentLabel: document.getElementById('deskReleaseCurrentLabel'),
      currentVersion: document.getElementById('deskReleaseCurrentVersion'),
    });
    if (!elements.root || !elements.trigger || !elements.panel || !elements.close) return;
    render();
    bindEvents();
  }

  window.DesktopUpdates = {
    init,
    render,
    open: openPanel,
    close: closePanel,
    applyAppUpdateStatus,
    loadBackendUpdateStatus,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
