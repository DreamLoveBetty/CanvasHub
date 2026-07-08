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
