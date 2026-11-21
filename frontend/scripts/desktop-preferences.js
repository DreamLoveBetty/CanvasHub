(function () {
  const PREF_KEY = 'desktop_ui_preferences_v1';
  const SUPPORTED_LANGUAGES = new Set(['zh', 'en']);
  const SUPPORTED_THEMES = new Set(['light', 'dark']);
  const SUPPORTED_CONNECTION_SWELL_STYLES = new Set(['liquid', 'droplet']);
  const SUPPORTED_CONNECTION_LINE_STYLES = new Set(['straight', 'curve']);
  // Visual style family, orthogonal to the light/dark theme: liquid (default) or graphite.
  const SUPPORTED_THEME_STYLES = new Set(['liquid', 'graphite']);
  // Day/night switch animation: the ripple reveal, or a plain cross-fade ('none').
  const SUPPORTED_THEME_TRANSITIONS = new Set(['ripple', 'none']);

  const state = {
    theme: 'light',
    themeStyle: 'liquid',
    themeTransition: 'ripple',
    themeTransitionSpeed: 'standard',
    language: 'zh',
    connectionSwellStyle: 'liquid',
    connectionLineStyle: 'straight',
    canvasCollisionEnabled: false,
    progress: { style: 'liquid', height: 36, colors: {} },
    controlMaterial: normalizeControlMaterial(),
  };
  let themeTransitionTimer = null;
  let activeThemeReveal = null;
  let themeRevealSequence = 0;
  // Fallback when desktop-theme-ripple.js is missing; the speed presets live there.
  const THEME_REVEAL_DEFAULT_MS = 1400;
  // Longest wait for the ripple to become showable before the clock starts regardless.
  const THEME_REVEAL_READY_TIMEOUT_MS = 3000;

  function normalizeTheme(value) {
    const theme = String(value || '').trim().toLowerCase();
    return SUPPORTED_THEMES.has(theme) ? theme : 'light';
  }

  function normalizeThemeStyle(value) {
    const style = String(value || '').trim().toLowerCase();
    return SUPPORTED_THEME_STYLES.has(style) ? style : 'liquid';
  }

  function normalizeThemeTransition(value) {
    const transition = String(value || '').trim().toLowerCase();
    return SUPPORTED_THEME_TRANSITIONS.has(transition) ? transition : 'ripple';
  }

  function normalizeThemeTransitionSpeed(value) {
    return window.DesktopThemeRipple?.normalizeSpeed?.(value) || 'standard';
  }

  function themeRevealDuration() {
    return window.DesktopThemeRipple?.durationFor?.(state.themeTransitionSpeed) || THEME_REVEAL_DEFAULT_MS;
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
      state.themeStyle = normalizeThemeStyle(parsed.themeStyle);
      state.themeTransition = normalizeThemeTransition(parsed.themeTransition);
      state.themeTransitionSpeed = normalizeThemeTransitionSpeed(parsed.themeTransitionSpeed);
      state.language = normalizeLanguage(parsed.language);
      state.connectionSwellStyle = normalizeConnectionSwellStyle(parsed.connectionSwellStyle);
      state.connectionLineStyle = normalizeConnectionLineStyle(parsed.connectionLineStyle);
      state.canvasCollisionEnabled = parsed.canvasCollisionEnabled === true;
      state.progress = normalizeProgressPreferences(parsed.progress);
      state.controlMaterial = normalizeControlMaterial(parsed.controlMaterial);
    } catch (e) {
      state.theme = 'light';
      state.themeStyle = 'liquid';
      state.themeTransition = 'ripple';
      state.themeTransitionSpeed = 'standard';
      state.language = 'zh';
      state.connectionSwellStyle = 'liquid';
      state.connectionLineStyle = 'straight';
      state.canvasCollisionEnabled = false;
      state.progress = normalizeProgressPreferences();
      state.controlMaterial = normalizeControlMaterial();
    }
  }

  function savePreferences() {
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify({
        theme: state.theme,
        themeStyle: state.themeStyle,
        themeTransition: state.themeTransition,
        themeTransitionSpeed: state.themeTransitionSpeed,
        language: state.language,
        connectionSwellStyle: state.connectionSwellStyle,
        connectionLineStyle: state.connectionLineStyle,
        canvasCollisionEnabled: state.canvasCollisionEnabled,
        progress: state.progress,
        controlMaterial: state.controlMaterial,
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

  // Liquid is the stylesheet default, so only graphite projects an attribute.
  function applyThemeStyle(style = state.themeStyle) {
    state.themeStyle = normalizeThemeStyle(style);
    [document.body, document.documentElement].forEach(element => {
      if (!element) return;
      if (state.themeStyle === 'liquid') element.removeAttribute('data-desk-style');
      else element.setAttribute('data-desk-style', state.themeStyle);
    });
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
    if (state.themeTransition === 'none') return false;
    if (!document.body || typeof window.requestAnimationFrame !== 'function') return false;
    if (!window.DesktopThemeRipple?.supported?.()) return false;
    try {
      return !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    } catch (e) {
      return true;
    }
  }

  // Ease in and out so the wobbling edge lingers on screen instead of leaving it at once.
  function easeThemeReveal(t) {
    const p = Math.min(1, Math.max(0, t));
    return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(2 - 2 * p, 3) / 2;
  }

  function finishThemeReveal(run, cancelled = false) {
    if (!run || run.finished) return;
    run.finished = true;
    if (run.frameId) window.cancelAnimationFrame(run.frameId);
    run.frameId = 0;
    run.ripple?.dispose();
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

  function animateThemeRevealOverlay(run) {
    return new Promise(resolve => {
      run.resolve = resolve;
      // The clock starts on the first frame the ripple can show: the snapshot path waits for
      // the new theme to be captured, which can take longer than a fast reveal itself.
      let startedAt = null;
      const requestedAt = performance.now();
      const frame = now => {
        run.frameId = 0;
        if (activeThemeReveal !== run || run.finished) {
          finishThemeReveal(run, true);
          return;
        }
        if (run.ripple.isReady?.() === false && now - requestedAt < THEME_REVEAL_READY_TIMEOUT_MS) {
          run.frameId = window.requestAnimationFrame(frame);
          return;
        }
        if (startedAt === null) startedAt = now;
        const progress = Math.min(1, (now - startedAt) / run.duration);
        try {
          run.ripple.frame(progress, easeThemeReveal(progress), (now - startedAt) / 1000);
        } catch (error) {
          // Never leave the page frozen mid-reveal: end it and land on the target theme.
          finishThemeReveal(run, true);
          if (state.theme === run.targetTheme) applyTheme(run.targetTheme);
          return;
        }
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
    const duration = themeRevealDuration();

    root?.classList.add('theme-reveal-transitioning');
    body?.classList.add('theme-reveal-transitioning');

    // Snapshot path: a View Transition shows the real outgoing page and refracts the edge;
    // the new theme is applied inside its update callback. Fallback: a painted overlay.
    const snapshot = window.DesktopThemeRippleSnapshot;
    const useSnapshot = Boolean(snapshot?.supported?.());
    let overlay = null;
    let ripple = null;
    try {
      if (useSnapshot) {
        // Saved and toggled from now on; a superseded run's late callback must not win.
        state.theme = targetTheme;
        ripple = snapshot.create({
          origin,
          endRadius,
          fromTheme: previousTheme,
          duration,
          ease: easeThemeReveal,
          apply: () => {
            if (state.theme === targetTheme) applyTheme(targetTheme);
          },
        });
      } else {
        overlay = document.createElement('div');
        overlay.className = 'desk-theme-reveal-overlay';
        overlay.dataset.theme = previousTheme;
        overlay.dataset.frozenTheme = previousTheme;
        overlay.style.colorScheme = previousTheme;
        body?.appendChild(overlay);
        ripple = window.DesktopThemeRipple.create({ overlay, origin, endRadius, fromTheme: previousTheme });
        ripple.frame(0, 0, 0);
      }
    } catch (error) {
      // setTheme() falls back to an instant switch; leave nothing of the reveal behind.
      ripple?.dispose();
      overlay?.remove();
      root?.classList.remove('theme-reveal-transitioning');
      body?.classList.remove('theme-reveal-transitioning');
      throw error;
    }

    const run = {
      id: ++themeRevealSequence,
      overlay,
      ripple,
      frameId: 0,
      resolve: null,
      finished: false,
      previousTheme,
      targetTheme,
      duration,
    };
    activeThemeReveal = run;

    if (!useSnapshot) applyTheme(targetTheme);
    return animateThemeRevealOverlay(run).catch(() => {
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

  function setThemeStyle(style) {
    const nextStyle = normalizeThemeStyle(style);
    if (nextStyle !== state.themeStyle) startThemeTransition();
    applyThemeStyle(nextStyle);
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:theme-style-change', {
      detail: { style: state.themeStyle },
    }));
  }

  function setThemeTransition(transition) {
    state.themeTransition = normalizeThemeTransition(transition);
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:theme-transition-change', {
      detail: { transition: state.themeTransition },
    }));
  }

  function setThemeTransitionSpeed(speed) {
    state.themeTransitionSpeed = normalizeThemeTransitionSpeed(speed);
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:theme-transition-speed-change', {
      detail: { speed: state.themeTransitionSpeed },
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

  function setCanvasCollisionEnabled(enabled) {
    state.canvasCollisionEnabled = enabled === true;
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:canvas-collision-change', {
      detail: { enabled: state.canvasCollisionEnabled },
    }));
  }

  function normalizeProgressPreferences(value) {
    return window.DesktopProgressModel?.normalizePreferences(value)
      || { style: 'liquid', height: 36, colors: {} };
  }

  function applyProgressPreferences() {
    const body = document.body;
    body?.setAttribute('data-progress-style', state.progress.style);
    const color = state.progress.colors.classic;
    if (color) {
      body?.setAttribute('data-progress-classic-tint', 'true');
      body?.style?.setProperty('--desk-progress-classic-fill', window.DesktopProgressModel.classicFillGradient(color));
    } else {
      body?.removeAttribute?.('data-progress-classic-tint');
      body?.style?.removeProperty('--desk-progress-classic-fill');
    }
  }

  function setProgressPreferences(patch = {}) {
    state.progress = normalizeProgressPreferences({ ...state.progress, ...patch });
    applyProgressPreferences();
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:progress-preferences-change', {
      detail: { progress: state.progress },
    }));
  }

  // Schema/normalisation and the body projection belong to DesktopControlMaterial.
  function normalizeControlMaterial(value) {
    return window.DesktopControlMaterial?.normalize(value) || { material: 'current' };
  }

  function setControlMaterialPreferences(patch = {}) {
    state.controlMaterial = normalizeControlMaterial({ ...state.controlMaterial, ...patch });
    window.DesktopControlMaterial?.apply(state.controlMaterial, document.body);
    savePreferences();
    window.dispatchEvent(new CustomEvent('desktop:control-material-change', {
      detail: { controlMaterial: state.controlMaterial },
    }));
  }

  function bindControls() {
    document.getElementById('deskThemeToggle')?.addEventListener('click', toggleTheme);
    document.getElementById('deskLanguageSelect')?.addEventListener('change', (event) => {
      setLanguage(event.target.value);
    });
  }

  function init() {
    readPreferences();
    applyProgressPreferences();
    window.DesktopControlMaterial?.apply(state.controlMaterial, document.body);
    applyTheme(state.theme);
    applyThemeStyle(state.themeStyle);
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
    setThemeStyle,
    setThemeTransition,
    setThemeTransitionSpeed,
    setLanguage,
    setConnectionSwellStyle,
    setConnectionLineStyle,
    setCanvasCollisionEnabled,
    setProgressPreferences,
    setControlMaterialPreferences,
    toggleTheme,
    normalizeThemeStyle,
    normalizeThemeTransition,
    normalizeThemeTransitionSpeed,
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
      date: '2026-11-21',
      title: {
        zh: '官方分组额度、Gemini Web 会话修复与桌面交互',
        en: 'Official grouped quotas, Gemini Web session fixes and desktop interaction',
      },
      items: {
        zh: [
          'Google OAuth 账号池按 Cockpit v1.4.2 官方桶展示 Claude / Gemini / Argon / Carbon 的 5 小时与周额度，四主题紧凑并排，隐藏无有效额度，真实 0% 保留；工具栏刷新只读缓存，需手动点账号行「刷新额度」。新图像任务在可用账号间顺序轮换，政策限制立即停止。',
          'Gemini Web 修复同名跨域会话互相覆盖、保存时裁掉必要会话，以及登录页误判；发现失败改为脱敏分类。流中间已解析的图片在末帧无图时保留；无图错误归为 output。结构计数诊断尚未端到端写入运行记录。',
          'Telegram「已生成，未发送」提供补发，不重新生成。桌面批量暂停/取消与复制提示词、手动发送拆开；Esc 只关面板，不再停止进度轮询。',
          'Mini App 锁定 Cinematic 布局，Comfy 在布局内工作台打开，并改进历史续编与重媒体预览。',
          '设置保存若需重启会提示且不自动重启；模型工具路径行可复制完整路径。MiniMax H3 工作流拆为带提示词扩展与无扩写两份。',
        ],
        en: [
          'The Google OAuth pool shows official Cockpit v1.4.2 Claude / Gemini / Argon / Carbon 5-hour and weekly quotas in compact four-theme cards. Unused buckets stay hidden, a real 0% remains, the toolbar rereads the cache, and quota refresh is manual. New image tasks rotate across eligible accounts and stop immediately on policy limits.',
          'Gemini Web keeps same-name cookies from different hosts from overwriting each other, persists necessary session cookies, and no longer treats a login wall as an account-order change. Discovery failures are classified without leaking page content. Images parsed mid-stream are kept if the final frame has none; a missing image is classified as output. Structured no-image counts are not yet saved end-to-end on the run record.',
          'Telegram “generated, not sent” offers resend without starting a new generation. Batch pause/cancel is split from copy-prompt and manual send; Escape closes panels and does not stop progress polling.',
          'The Mini App locks the Cinematic layout, opens Comfy in a hosted workbench, and improves history continue-edit plus heavy media previews.',
          'A settings save that requires a restart shows a notice and does not restart automatically. Model-tools path rows can copy the full directory path. The MiniMax H3 workflow is split into prompt-expansion and no-expansion editions.',
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
