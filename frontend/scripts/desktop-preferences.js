(function () {
  const PREF_KEY = 'desktop_ui_preferences_v1';
  const SUPPORTED_LANGUAGES = new Set(['zh', 'en']);
  const SUPPORTED_THEMES = new Set(['light', 'dark']);
  const SUPPORTED_CONNECTION_SWELL_STYLES = new Set(['liquid', 'droplet']);
  const SUPPORTED_CONNECTION_LINE_STYLES = new Set(['straight', 'curve']);

  const state = {
    theme: 'light',
    language: 'zh',
    connectionSwellStyle: 'liquid',
    connectionLineStyle: 'straight',
  };
  let themeTransitionTimer = null;
  let activeThemeReveal = null;
  let themeRevealSequence = 0;
  const THEME_REVEAL_DURATION_MS = 960;

  function normalizeTheme(value) {
    const theme = String(value || '').trim().toLowerCase();
    return SUPPORTED_THEMES.has(theme) ? theme : 'light';
  }

  function normalizeLanguage(value) {
    const language = String(value || '').trim().toLowerCase();
    return window.DesktopI18n?.normalizeLanguage?.(language) || (SUPPORTED_LANGUAGES.has(language) ? language : 'zh');
  }

  function normalizeConnectionSwellStyle(value) {
    const style = String(value || '').trim().toLowerCase();
    return SUPPORTED_CONNECTION_SWELL_STYLES.has(style) ? style : 'liquid';
  }

  function normalizeConnectionLineStyle(value) {
    const style = String(value || '').trim().toLowerCase();
    if (style === 'sag') return 'curve';
    return SUPPORTED_CONNECTION_LINE_STYLES.has(style) ? style : 'straight';
  }

  function readPreferences() {
    try {
      const parsed = JSON.parse(localStorage.getItem(PREF_KEY) || '{}');
      state.theme = normalizeTheme(parsed.theme);
      state.language = normalizeLanguage(parsed.language);
      state.connectionSwellStyle = normalizeConnectionSwellStyle(parsed.connectionSwellStyle);
      state.connectionLineStyle = normalizeConnectionLineStyle(parsed.connectionLineStyle);
    } catch (e) {
      state.theme = 'light';
      state.language = 'zh';
      state.connectionSwellStyle = 'liquid';
      state.connectionLineStyle = 'straight';
    }
  }

  function savePreferences() {
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify({
        theme: state.theme,
        language: state.language,
        connectionSwellStyle: state.connectionSwellStyle,
        connectionLineStyle: state.connectionLineStyle,
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

  function applyConnectionSwellStyle(style = state.connectionSwellStyle) {
    state.connectionSwellStyle = normalizeConnectionSwellStyle(style);
    document.body?.setAttribute('data-connection-swell-style', state.connectionSwellStyle);
    document.documentElement.setAttribute('data-connection-swell-style', state.connectionSwellStyle);
  }

  function applyConnectionLineStyle(style = state.connectionLineStyle) {
    state.connectionLineStyle = normalizeConnectionLineStyle(style);
    document.body?.setAttribute('data-connection-line-style', state.connectionLineStyle);
    document.documentElement.setAttribute('data-connection-line-style', state.connectionLineStyle);
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

  function finishThemeReveal(run, cancelled = false) {
    if (!run || run.finished) return;
    run.finished = true;
    if (run.frameId) window.cancelAnimationFrame(run.frameId);
    run.frameId = 0;
    run.overlay?.remove();
    if (activeThemeReveal === run) {
      document.documentElement?.classList.remove('theme-reveal-transitioning');
      document.body?.classList.remove('theme-reveal-transitioning');
      activeThemeReveal = null;
    }
    run.resolve?.({ cancelled });
  }

  function cancelThemeReveal() {
    if (activeThemeReveal) finishThemeReveal(activeThemeReveal, true);
  }

  function animateThemeRevealOverlay(run, endRadius) {
    return new Promise(resolve => {
      run.resolve = resolve;
      const startedAt = performance.now();
      const frame = now => {
        run.frameId = 0;
        if (activeThemeReveal !== run || run.finished) {
          finishThemeReveal(run, true);
          return;
        }
        const progress = Math.min(1, (now - startedAt) / THEME_REVEAL_DURATION_MS);
        const eased = easeThemeReveal(progress);
        run.overlay.style.setProperty('--theme-reveal-radius', `${Math.ceil(endRadius * eased)}px`);
        if (progress < 1) {
          run.frameId = window.requestAnimationFrame(frame);
        } else {
          finishThemeReveal(run, false);
        }
      };
      run.frameId = window.requestAnimationFrame(frame);
    });
  }

  function runCircularThemeTransition(nextTheme, options = {}) {
    const root = document.documentElement;
    const body = document.body;
    const targetTheme = normalizeTheme(nextTheme);
    const previousTheme = state.theme;
    cancelThemeReveal();
    const origin = resolveThemeTransitionOrigin(options);
    const maxX = Math.max(origin.x, window.innerWidth - origin.x);
    const maxY = Math.max(origin.y, window.innerHeight - origin.y);
    const endRadius = Math.ceil(Math.hypot(maxX, maxY));

    root?.classList.add('theme-reveal-transitioning');
    body?.classList.add('theme-reveal-transitioning');

    const overlay = document.createElement('div');
    overlay.className = 'desk-theme-reveal-overlay';
    overlay.dataset.theme = previousTheme;
    overlay.dataset.frozenTheme = previousTheme;
    overlay.style.colorScheme = previousTheme;
    overlay.style.setProperty('--theme-reveal-x', `${origin.x}px`);
    overlay.style.setProperty('--theme-reveal-y', `${origin.y}px`);
    overlay.style.setProperty('--theme-reveal-radius', '0px');
    body?.appendChild(overlay);

    const run = {
      id: ++themeRevealSequence,
      overlay,
      frameId: 0,
      resolve: null,
      finished: false,
      previousTheme,
      targetTheme,
    };
    activeThemeReveal = run;

    applyTheme(targetTheme);
    return animateThemeRevealOverlay(run, endRadius).catch(() => {
      finishThemeReveal(run, true);
      return { cancelled: true };
    });
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
      themeChangeFinished.then(() => {
        if (state.theme === nextTheme) emitThemeChange(nextTheme);
      });
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

  function setConnectionSwellStyle(style) {
    applyConnectionSwellStyle(style);
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:connection-swell-style-change', {
      detail: { style: state.connectionSwellStyle },
    }));
  }

  function setConnectionLineStyle(style) {
    applyConnectionLineStyle(style);
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:connection-line-style-change', {
      detail: { style: state.connectionLineStyle },
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
    applyConnectionSwellStyle(state.connectionSwellStyle);
    applyConnectionLineStyle(state.connectionLineStyle);
    bindControls();
  }

  window.DesktopPreferences = {
    state,
    t,
    init,
    setTheme,
    setLanguage,
    setConnectionSwellStyle,
    setConnectionLineStyle,
    toggleTheme,
    normalizeConnectionSwellStyle,
    normalizeConnectionLineStyle,
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
      id: 'bundled-release',
      version: '',
      date: '2026-07-30',
      title: {
        zh: 'macOS 自定义更新助手',
        en: 'Custom macOS update helper',
      },
      items: {
        zh: [
          'macOS 桌面版会在后台下载更新，并提供“重启并安装”操作。',
          '安装前会复核文件体积、SHA-512、应用标识、版本和可执行文件。',
          '更新采用原子替换；安装或重启失败时自动恢复旧版本。',
          '更新助手随应用内置，不需要单独安装应用或运行环境。',
        ],
        en: [
          'The macOS desktop app downloads updates in the background and offers Restart and install.',
          'The installer verifies size, SHA-512, bundle identity, version, and executable before replacement.',
          'Updates use an atomic swap and restore the previous version if installation or relaunch fails.',
          'The helper is bundled with CanvasHub and requires no separately installed app or runtime.',
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
      updateDownloadedBody: '新版已下载并校验，可立即重启完成更新。',
      updateInstalling: '正在重启安装',
      updateInstallingBody: 'CanvasHub 正在退出并安装新版。',
      restartInstall: '重启并安装',
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
      updateDownloadedBody: 'The update is downloaded and verified. Restart to finish installing it.',
      updateInstalling: 'Restarting to install',
      updateInstallingBody: 'CanvasHub is closing and installing the update.',
      restartInstall: 'Restart and install',
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

  function releaseVersion(release) {
    return String(release?.version || appVersion()).trim();
  }

  function releaseSeenId(release) {
    return `${String(release?.id || 'release')}:${releaseVersion(release)}`;
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
    return ['available', 'downloaded', 'installing'].includes(String(appUpdateStatus.state || ''))
      && !!String(appUpdateStatus.version || '').trim();
  }

  function hasUnreadRelease() {
    if (hasAvailableAppUpdate()) return true;
    const latest = latestRelease();
    if (!latest) return false;
    try {
      return localStorage.getItem(SEEN_RELEASE_KEY) !== releaseSeenId(latest);
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
      localStorage.setItem(SEEN_RELEASE_KEY, releaseSeenId(latest));
    } catch (error) {}
    updateUnreadState();
  }

  function createReleaseItem(release, index, lang) {
    const article = document.createElement('article');
    article.className = 'desk-release__item';

    const meta = document.createElement('div');
    meta.className = 'desk-release__meta';

    const version = document.createElement('strong');
    version.textContent = releaseVersion(release);
    meta.appendChild(version);

    if (index === 0 && !hasAvailableAppUpdate()) {
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
    title.textContent = appUpdateStatus.state === 'installing'
      ? labels.updateInstalling
      : String(appUpdateStatus.releaseName || '').trim() || (appUpdateStatus.state === 'downloaded'
        ? labels.updateDownloaded
        : labels.updateAvailable);
    const body = document.createElement('p');
    body.className = 'desk-release__update-copy';
    if (appUpdateStatus.error) {
      body.textContent = String(appUpdateStatus.error);
    } else if (appUpdateStatus.state === 'installing') {
      body.textContent = labels.updateInstallingBody;
    } else if (appUpdateStatus.state === 'downloaded') {
      body.textContent = labels.updateDownloadedBody;
    } else if (appUpdateStatus.deployment === 'docker') {
      body.textContent = labels.dockerUpdateBody;
    } else if (appUpdateStatus.deployment === 'source') {
      body.textContent = labels.sourceUpdateBody;
    } else {
      body.textContent = labels.updateAvailableBody;
    }
    article.append(meta, title, body);

    const canInstall = appUpdateStatus.state === 'downloaded'
      && appUpdateStatus.canInstall === true
      && typeof window.CanvasHubDesktop?.installUpdate === 'function';
    const isInstalling = appUpdateStatus.state === 'installing';
    const releaseUrl = String(appUpdateStatus.releaseUrl || '').trim();
    if (canInstall || isInstalling || /^https:\/\//i.test(releaseUrl)) {
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'desk-release__update-action';
      action.disabled = isInstalling;
      action.textContent = isInstalling
        ? labels.updateInstalling
        : canInstall ? labels.restartInstall : labels.viewUpdate;
      action.addEventListener('click', async () => {
        if (isInstalling) return;
        if (canInstall) {
          action.disabled = true;
          action.textContent = labels.updateInstalling;
          applyAppUpdateStatus({ state: 'installing', error: '', canInstall: false });
          try {
            await window.CanvasHubDesktop.installUpdate();
          } catch (error) {
            applyAppUpdateStatus({
              state: 'downloaded',
              error: String(error?.message || error || ''),
              canInstall: true,
            });
          }
          return;
        }
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
