import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    path = ROOT / relative_path
    if not path.exists() and relative_path.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
        path = ROOT / "frontend" / relative_path
    return path.read_text(encoding="utf-8")


def assert_asset_has_cache_bust(testcase, html, asset_path):
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


class DesktopResultStatusUiTest(unittest.TestCase):
    def test_model_node_directly_owns_generation_controls_and_image_outputs(self):
        html = read_text("desktop.html")
        canvas_js = read_text("scripts/desktop-canvas.js")
        results_js = read_text("scripts/desktop-results.js")
        css = read_text("styles/desktop-liquid.css")

        self.assertNotIn('data-add-node="output"', html)
        self.assertNotIn('id="deskOutputNode"', html)
        self.assertNotIn('id="deskPromptInput"', html)
        self.assertNotIn('id="deskCopyPromptBtn"', html)
        self.assertIn('id="deskInputOutputStatus"', html)
        self.assertIn('data-output-archive', html)
        self.assertIn('data-output-telegram', html)
        self.assertIn('data-send-original', html)
        self.assertIn('data-result-run', html)
        self.assertIn("const DEFAULT_RESULT_NODE_ID = 'input';", results_js)
        self.assertIn("function ensureImageOutputsForConfig", canvas_js)
        self.assertIn("function syncOutputControlsToNodes", canvas_js)
        self.assertIn("syncOutputControlsToNodes(state.output, { save: false });", canvas_js)
        self.assertIn("function refreshOutputConfigStatus", results_js)
        self.assertIn("refreshOutputConfigStatus,", results_js)
        self.assertIn("function syncOutputControlsFromNode", canvas_js)
        self.assertIn("event.target.closest('[data-output-archive], [data-output-telegram]')", canvas_js)
        self.assertIn("updateBottom: node.classList.contains('desk-node--input')", canvas_js)
        self.assertIn("if (options.updateBottom !== false) renderOutputStatusChips(liveParams, status);", results_js)
        self.assertIn("const controls = globalOutputControlParams(params);", results_js)
        self.assertIn("const imagePaths = normalizeTaskImagePaths(task, resultFiles);", results_js)
        self.assertIn("task?.result_file", results_js)
        select_start = canvas_js.index("function selectNode")
        select_end = canvas_js.index("\n  function getPromptTargetInfo", select_start)
        self.assertNotIn("syncOutputControlsToNodes", canvas_js[select_start:select_end])
        pointer_start = canvas_js.index("els.deskCanvasWorld?.addEventListener('pointerdown'")
        pointer_end = canvas_js.index("\n      const aliasShell", pointer_start)
        self.assertNotIn("syncOutputControlsToNodes", canvas_js[pointer_start:pointer_end])
        self.assertIn("const modelToImage = from?.type === 'input' && to?.type === 'image';", canvas_js)
        self.assertIn("setImageNodeFromResult(targets[index], resultNodeId, output, index)", canvas_js)
        self.assertIn("const DEFAULT_TEXT_NODE_WIDTH = 600;", canvas_js)
        self.assertIn("const DEFAULT_IMAGE_NODE_WIDTH = 600;", canvas_js)
        self.assertIn("const DEFAULT_IMAGE_LONGEST_SIDE = 520;", canvas_js)
        self.assertIn("desk-image-pop-in", css)
        self.assertIn("animation: desk-image-pop-in 0.47s", css)
        self.assertIn("cubic-bezier(0.17, 0.84, 0.44, 1.25)", css)

    def test_result_progress_is_only_visible_while_task_is_in_flight(self):
        html = read_text("desktop.html")
        canvas_js = read_text("scripts/desktop-canvas.js")
        results_js = read_text("scripts/desktop-results.js")
        css = read_text("styles/desktop-liquid.css")

        self.assertNotIn('class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true"', html)
        self.assertIn('class="desk-progress-float" id="deskProgressFloat" aria-hidden="true"', html)
        self.assertIn('class="desk-progress-float__percent" data-progress-percent', html)
        self.assertIn("data-progress-percent-value", html)
        self.assertIn('class="desk-progress-float__timer" data-progress-timer', html)
        self.assertIn('class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true"', canvas_js)
        self.assertNotIn("deskProgressLabel", html)
        self.assertNotIn("data-progress-label", canvas_js)
        self.assertNotIn("progressLabel:", results_js)
        self.assertNotIn("resultEls.progressLabel", results_js)
        self.assertIn("progressWrap:", results_js)
        self.assertIn("function setProgressVisibility", results_js)
        self.assertIn("setProgressVisibility(DesktopState.isInFlight(status), resultNodeId);", results_js)
        self.assertIn("setProgress(DesktopState.estimateProgress(task), resultNodeId);", results_js)
        self.assertIn("const isInputNode = node.classList.contains('desk-node--input');", results_js)
        self.assertIn("resultEls.progressBar.parentElement?.style.setProperty('--progress-percent'", results_js)
        self.assertIn("data-progress-percent-value", results_js)
        self.assertRegex(css, r"\.desk-progress-float__bar\s*\{[^}]*height:\s*18px;[^}]*isolation:\s*isolate;[^}]*border-radius:\s*999px;")
        self.assertRegex(css, r"\.desk-progress-float__bar \[data-progress-bar\]\s*\{[^}]*#084fbd")
        self.assertRegex(css, r"\.desk-progress-float__bar \[data-progress-bar\]\s*\{[^}]*inset:\s*2px\s+auto\s+2px\s+2px;[^}]*max-width:\s*calc\(100%\s*-\s*4px\);")
        self.assertRegex(css, r"\.desk-progress-float__bar \[data-progress-bar\]::after\s*\{[^}]*height:\s*5px;")
        self.assertRegex(css, r"\.desk-progress-float__panel\s*\{[^}]*padding:\s*4px\s+0\s+32px;")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*top:\s*17px;[^}]*left:\s*clamp\(72px,\s*var\(--progress-percent,\s*0%\),\s*calc\(100%\s*-\s*72px\)\);")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*z-index:\s*-1;[^}]*min-width:\s*138px;[^}]*height:\s*28px;")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*padding:\s*0\s+17px\s+2px;")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*color:\s*#084fbd;")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*border-top:\s*0;")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*border-radius:\s*0\s+0\s+18px\s+18px;")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*inset\s+0\s+9px\s+10px\s+rgba\(54,\s*70,\s*86,\s*0\.28\),")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*0\s+-3px\s+8px\s+rgba\(55,\s*72,\s*88,\s*0\.2\),")
        self.assertNotRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*0\s+-1px\s+4px\s+rgba\(255,\s*255,\s*255,\s*0\.62\);")
        self.assertNotRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*0\s+8px\s+14px\s+rgba\(32,\s*45,\s*58,\s*0\.16\);")
        self.assertRegex(css, r"\.desk-progress-float__percent\s*\{[^}]*clip-path:\s*none;")
        self.assertRegex(css, r"\.desk-progress-float__percent::before\s*\{[^}]*display:\s*none;[^}]*content:\s*none;")
        self.assertRegex(css, r"\.desk-progress-float__timer\s*\{[^}]*position:\s*static;[^}]*font-size:\s*14px;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-progress-float__bar\s*\{[^}]*rgba\(53,\s*62,\s*64,\s*0\.9\)[^}]*rgba\(19,\s*23,\s*25,\s*0\.96\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-progress-float__bar \[data-progress-bar\]\s*\{[^}]*#ff7a33[^}]*#f4511e[^}]*#b93312")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-progress-float__percent\s*\{[^}]*color:\s*#ffb089;[^}]*rgba\(48,\s*56,\s*58,\s*0\.88\)[^}]*rgba\(31,\s*37,\s*39,\s*0\.92\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-progress-float__timer\s*\{[^}]*color:\s*#ffb089;")
        self.assertRegex(css, r"\.desk-progress-wrap\s*\{[^}]*display:\s*none;")
        self.assertRegex(css, r"\.desk-progress-wrap\.is-visible\s*\{[^}]*display:\s*block;")
        self.assertRegex(css, r"\.desk-progress-copy\s*\{[^}]*justify-content:\s*flex-end;")

    def test_titlebar_uses_canvasgpt_motion_logo_without_traffic_dots(self):
        html = read_text("desktop.html")
        css = read_text("styles/desktop-liquid.css")
        prefs_js = read_text("scripts/desktop-preferences.js")

        self.assertNotIn("desk-window-dots", html)
        self.assertNotIn("desk-dot--red", html)
        self.assertNotIn("desk-dot--yellow", html)
        self.assertNotIn("desk-dot--green", html)
        self.assertNotIn(".desk-window-dots", css)
        self.assertNotIn(".desk-dot--red", css)
        self.assertIn('class="desk-titlebar-logo" aria-label="CanvasHub"', html)
        self.assertIn('class="desk-titlebar-logo__image"', html)
        self.assertIn('assets/animated.webp?v=20260621-ui3', html)
        self.assertIn('alt="Canvas Hub"', html)
        self.assertNotIn('id="deskTitleLogo"', html)
        self.assertNotIn('class="desk-titlebar-logo__spark"', html)
        self.assertNotIn('class="desk-titlebar-logo__dot"', html)
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*height:\s*36px;")
        self.assertRegex(css, r"\.desk-titlebar-logo\s*\{[^}]*width:\s*141px;[^}]*height:\s*30px;[^}]*pointer-events:\s*none;")
        self.assertRegex(css, r"\.desk-titlebar-logo__image\s*\{[^}]*width:\s*100%;[^}]*height:\s*100%;[^}]*object-fit:\s*contain;")
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn('id="deskThemeToggle"', html)
        self.assertIn('id="deskLanguageSelect"', html)
        assert_asset_has_cache_bust(self, html, "scripts/desktop-preferences.js")
        self.assertIn("desktop_ui_preferences_v1", prefs_js)
        self.assertIn("theme: 'light'", prefs_js)
        self.assertNotIn("systemTheme", prefs_js)
        self.assertIn("setTheme", prefs_js)
        self.assertIn("setLanguage", prefs_js)
        self.assertIn("desktop:language-change", prefs_js)
        self.assertRegex(css, r"\.desk-titlebar-actions\s*\{[^}]*position:\s*relative;[^}]*z-index:\s*2;")
        self.assertRegex(css, r"\.desk-titlebar-actions\s*\{[^}]*margin-left:\s*auto;")
        self.assertRegex(css, r"\.desk-titlebar-actions\s*\{[^}]*gap:\s*6px;")
        self.assertRegex(css, r"\.desk-theme-toggle\s*\{[^}]*--desk-theme-toggle-width:\s*64px;[^}]*--desk-theme-toggle-height:\s*22px;[^}]*width:\s*var\(--desk-theme-toggle-width\);[^}]*height:\s*var\(--desk-theme-toggle-height\);[^}]*overflow:\s*hidden;")
        self.assertIn("--desk-theme-toggle-width: 64px;", css)
        self.assertIn("--desk-theme-toggle-height: 22px;", css)
        self.assertIn("--desk-theme-toggle-orb: 18px;", css)
        self.assertIn("width: var(--desk-theme-toggle-orb);", css)
        self.assertIn("height: var(--desk-theme-toggle-orb);", css)
        self.assertIn("opacity 420ms ease,", css)
        self.assertIn("transform 560ms cubic-bezier(0.42, 0, 0.58, 1),", css)
        self.assertIn("transform: translate(0, -50%) rotate(-360deg) scale(0.72);", css)
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-theme-toggle__icon--moon\s*\{[^}]*transform:\s*translate\(var\(--desk-theme-toggle-travel\),\s*-50%\)\s*rotate\(0deg\)\s*scale\(1\);")
        self.assertRegex(css, r"\.desk-theme-toggle__text\s*\{[^}]*clip-path:\s*inset\(50%\);[^}]*position:\s*absolute;")
        self.assertRegex(css, r"\.desk-language-picker\s*\{[^}]*height:\s*22px;[^}]*padding:\s*0\s+8px\s+0\s+9px;")
        self.assertRegex(css, r"\.desk-language-picker__label\s*\{[^}]*font-size:\s*10px;")
        self.assertRegex(css, r"\.desk-language-picker__select\s*\{[^}]*min-width:\s*60px;[^}]*font-size:\s*10px;")
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertIn('class="desk-rail__glyph desk-rail__glyph--select"', html)
        self.assertIn('class="desk-rail-icon desk-rail-icon--select"', html)
        self.assertIn('class="desk-rail__glyph desk-rail__glyph--node"', html)
        self.assertIn('class="desk-rail-icon desk-rail-icon--node"', html)
        self.assertIn('class="desk-rail__glyph desk-rail__glyph--gallery"', html)
        self.assertIn('class="desk-rail-icon desk-rail-icon--gallery"', html)
        self.assertIn('class="desk-rail__glyph desk-rail__glyph--settings"', html)
        self.assertIn('class="desk-rail-icon desk-rail-icon--settings"', html)
        self.assertRegex(css, r"\.desk-rail__glyph\s*\{[^}]*width:\s*30px;[^}]*height:\s*30px;[^}]*background:\s*transparent;[^}]*border:\s*0;")
        self.assertRegex(css, r"\.desk-rail__glyph\s*\{[^}]*transition:\s*all 0\.18s cubic-bezier\(0\.2,\s*0\.8,\s*0\.2,\s*1\);")
        self.assertRegex(css, r"\.desk-rail__glyph svg\s*\{[^}]*width:\s*20px;[^}]*height:\s*20px;")
        self.assertRegex(css, r"\.desk-rail__item:hover \.desk-rail__glyph,[^}]*\.desk-rail__item:focus-visible \.desk-rail__glyph\s*\{[^}]*transform:\s*scale\(1\.12\);")
        self.assertRegex(css, r"\.desk-rail__item\.is-active \.desk-rail__glyph,[^}]*\.desk-rail__item\[aria-expanded=\"true\"\] \.desk-rail__glyph\s*\{[^}]*transform:\s*scale\(1\.1\);")
        self.assertRegex(css, r"\.desk-rail__item:active \.desk-rail__glyph\s*\{[^}]*transform:\s*scale\(0\.98\);")
        self.assertIn("animation: desk-rail-dash-move 1.2s linear infinite;", css)
        self.assertIn("animation: desk-rail-cursor-capture 1.2s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)
        self.assertIn("animation: desk-rail-flow 2s linear infinite;", css)
        self.assertIn("animation: desk-rail-media-pulse 1.8s ease-in-out infinite;", css)
        self.assertIn("animation: desk-rail-play-flash 1.8s ease-in-out infinite;", css)
        self.assertIn("animation: desk-rail-cog-spin 2.5s linear infinite;", css)
        self.assertIn("@keyframes desk-rail-dash-move", css)
        self.assertIn("@keyframes desk-rail-flow", css)
        self.assertIn("@keyframes desk-rail-cog-spin", css)
        self.assertRegex(css, r"\.desk-history-windchime-button--dock\s*\{[^}]*background:\s*transparent;[^}]*border:\s*0;[^}]*transform:\s*translateY\(-6px\);")
        self.assertRegex(css, r"\.desk-node--input \.desk-input-footer \.desk-manual-send:disabled\s*\{[^}]*rgba\(83,\s*98,\s*112,\s*0\.68\)[^}]*rgba\(255,\s*255,\s*255,\s*0\.36\)")
        self.assertIn("Night mode uses a graphite neumorphic palette", css)
        self.assertNotRegex(css, r"body\.desk-app\[data-theme=\"dark\"\]\s*\{[^}]*--desk-ink")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-canvas\s*\{[^}]*--desk-ink:\s*#edf2f3;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-canvas\s*\{[^}]*--desk-jewel:\s*#f4511e;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-canvas\s*\{[^}]*background-color:\s*#202628;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-canvas\s*\{[^}]*linear-gradient\(180deg,\s*#30383a\s*0%,\s*#232a2c\s*45%,\s*#171b1d\s*100%\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-canvas\s*\{[^}]*background-repeat:\s*no-repeat;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-node:not\(\.desk-node--image\)\s*\{[^}]*rgba\(54,\s*63,\s*65,\s*0\.95\)[^}]*rgba\(43,\s*50,\s*52,\s*0\.98\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-segment button\.is-active\s*\{[^}]*rgba\(255,\s*106,\s*34,\s*0\.92\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-rail,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-node-palette,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-history:not\(\.is-collapsed\),\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-zoom-controls\s*\{[^}]*rgba\(48,\s*56,\s*58,\s*0\.86\)[^}]*rgba\(31,\s*37,\s*39,\s*0\.92\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-rail__item\.is-active,[^}]*\.desk-rail__item:hover\s*\{[^}]*color:\s*#ffb089;[^}]*rgba\(255,\s*90,\s*31,\s*0\.12\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-history-item\s*\{[^}]*rgba\(42,\s*50,\s*52,\s*0\.72\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-zoom-row button\[aria-pressed=\"true\"\]\s*\{[^}]*rgba\(255,\s*106,\s*34,\s*0\.72\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-minimap\s*\{[^}]*background:\s*linear-gradient\(180deg,\s*rgba\(28,\s*34,\s*36,\s*0\.9\),\s*rgba\(19,\s*23,\s*25,\s*0\.92\)\);[^}]*background-size:\s*100%\s*100%;")
        self.assertNotRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-minimap\s*\{[^}]*linear-gradient\(rgba\(255,\s*255,\s*255,\s*0\.045\)\s*1px,\s*transparent\s*1px\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-smart-guide--x\s*\{[^}]*border-left-color:\s*rgba\(223,\s*228,\s*230,\s*0\.56\);[^}]*filter:\s*drop-shadow\(0 0 5px rgba\(0,\s*0,\s*0,\s*0\.28\)\);")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-smart-guide--y\s*\{[^}]*border-top-color:\s*rgba\(223,\s*228,\s*230,\s*0\.56\);[^}]*filter:\s*drop-shadow\(0 0 5px rgba\(0,\s*0,\s*0,\s*0\.28\)\);")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-history\.is-collapsed\s*\{[^}]*background:\s*transparent;[^}]*box-shadow:\s*none;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-titlebar,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-bottombar\s*\{[^}]*border:\s*0;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-titlebar\s*\{[^}]*height:\s*36px;[^}]*padding:\s*0\s+18px;[^}]*background:\s*transparent;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-titlebar::before\s*\{[^}]*display:\s*block;[^}]*height:\s*34px;[^}]*rgba\(48,\s*56,\s*58,\s*0\.86\)[^}]*rgba\(31,\s*37,\s*39,\s*0\.9\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-bottombar\s*\{[^}]*right:\s*0;[^}]*bottom:\s*0;[^}]*left:\s*0;[^}]*height:\s*34px;[^}]*padding:\s*0\s+6px\s+0\s+10px;[^}]*rgba\(48,\s*56,\s*58,\s*0\.86\)[^}]*rgba\(31,\s*37,\s*39,\s*0\.94\)[^}]*border-radius:\s*0;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-theme-toggle\s*\{[^}]*linear-gradient\(180deg,\s*#0a1629\s*0%,\s*#13253e\s*54%,\s*#0c1a31\s*100%\)[^}]*border-color:\s*rgba\(168,\s*195,\s*223,\s*0\.42\);")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-language-picker\s*\{[^}]*background:\s*rgba\(24,\s*30,\s*33,\s*0\.7\);[^}]*border-color:\s*rgba\(255,\s*255,\s*255,\s*0\.08\);")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-status-chip,[^}]*\.desk-status-feedback-trigger\s*\{[^}]*background:\s*rgba\(28,\s*34,\s*36,\s*0\.58\);[^}]*border-color:\s*rgba\(255,\s*255,\s*255,\s*0\.08\);")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-rail__glyph,[^}]*\.desk-rail__item\.is-active \.desk-rail__glyph,[^}]*\.desk-rail__item:hover \.desk-rail__glyph\s*\{[^}]*background:\s*transparent;[^}]*box-shadow:\s*none;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-history-windchime-button--dock\s*\{[^}]*background:\s*transparent;[^}]*box-shadow:\s*none;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-history__header \.desk-history-windchime-button--dock\s*\{[^}]*background:\s*transparent;[^}]*border-color:\s*transparent;[^}]*box-shadow:\s*none;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-history__header \.desk-history-windchime-button--dock:hover\s*\{[^}]*background:\s*transparent;[^}]*border-color:\s*transparent;[^}]*box-shadow:\s*none;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-node--input \.desk-input-footer \.desk-manual-send:disabled\s*\{[^}]*rgba\(190,\s*199,\s*201,\s*0\.46\)[^}]*rgba\(28,\s*34,\s*36,\s*0\.42\)")

    def test_node_palette_uses_lucide_motion_icon_system(self):
        html = read_text("desktop.html")
        canvas_js = read_text("scripts/desktop-canvas.js")
        css = read_text("styles/desktop-liquid.css")

        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        for icon_class in (
            "desk-node-icon--input",
            "desk-node-icon--files",
            "desk-node-icon--image",
            "desk-node-icon--upscale",
            "desk-node-icon--pose",
            "desk-node-icon--text",
            "desk-node-icon--layout",
        ):
            self.assertIn(icon_class, html)
            self.assertIn(icon_class, canvas_js)

        self.assertIn("desk-node-icon__enter", html)
        self.assertIn("desk-node-icon__file-front", html)
        self.assertIn("desk-node-icon__plus", html)
        self.assertIn("desk-node-icon__upscale-arrow", html)
        self.assertIn("desk-node-icon__pose-body", html)
        self.assertIn("desk-node-icon__text-lines", html)
        self.assertIn("desk-node-icon__layout-panels", html)
        self.assertRegex(css, r"\.desk-node-palette__icon\s*\{[^}]*transition:\s*all 0\.18s cubic-bezier\(0\.2,\s*0\.8,\s*0\.2,\s*1\);")
        self.assertRegex(css, r"\.desk-node-palette button:hover \.desk-node-palette__icon,[^}]*\.desk-node-palette button:focus-visible \.desk-node-palette__icon\s*\{[^}]*transform:\s*scale\(1\.06\);")
        self.assertRegex(css, r"\.desk-node-palette button:active \.desk-node-palette__icon\s*\{[^}]*transform:\s*scale\(0\.98\);")
        self.assertIn("animation: desk-node-enter-flow 1.05s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)
        self.assertIn("animation: desk-node-file-lift 1.35s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)
        self.assertIn("animation: desk-node-plus-pop 1.25s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)
        self.assertIn("animation: desk-node-upscale-rise 1.2s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)
        self.assertIn("animation: desk-node-pose-balance 1.4s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)
        self.assertIn("animation: desk-node-scan-text 1.25s linear infinite;", css)
        self.assertIn("animation: desk-node-layout-snap 1.28s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;", css)

    def test_minimap_and_history_panel_resize_from_same_target_height(self):
        html = read_text("desktop.html")
        canvas_js = read_text("scripts/desktop-canvas.js")
        history_js = read_text("scripts/desktop-history.js")
        css = read_text("styles/desktop-liquid.css")

        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn("--desk-minimap-open-height: 86px;", css)
        self.assertIn("--desk-minimap-open-height: 92px;", css)
        self.assertIn("height: var(--desk-minimap-open-height);", css)
        self.assertRegex(css, r"\.desk-zoom-controls\s*\{[^}]*z-index:\s*12;")
        self.assertIn("function getMiniMapTargetHeight", canvas_js)
        self.assertIn("function dispatchMiniMapLayoutChange", canvas_js)
        self.assertIn("function setMiniMapPinned", canvas_js)
        self.assertIn("targetHeight: getMiniMapTargetHeight(controls, !!pinned)", canvas_js)
        self.assertIn("window.setTimeout(() => dispatchMiniMapLayoutChange(nextPinned, controls), 220);", canvas_js)
        self.assertIn("function getLayoutTopWithin", history_js)
        self.assertIn("function syncHistoryPanelBounds(options = {})", history_js)
        self.assertIn("const parentHeight = parent.clientHeight || parentRect.height || window.innerHeight || 0;", history_js)
        self.assertIn("const targetHeight = Number(options.targetHeight || 0);", history_js)
        self.assertIn("parentHeight - controlsBottom + targetHeight + 10", history_js)
        self.assertIn("parentHeight - controlsTop + 10", history_js)
        self.assertIn("window.addEventListener('desktop:minimap-layout-change', event =>", history_js)
        self.assertIn("scheduleHistoryPanelBoundsSync(0, { targetHeight });", history_js)

    def test_minimap_zoom_presets_open_as_vertical_rise_menu(self):
        html = read_text("desktop.html")
        canvas_js = read_text("scripts/desktop-canvas.js")
        css = read_text("styles/desktop-liquid.css")

        self.assertIn('aria-controls="deskZoomPresetMenu"', html)
        self.assertIn('role="menuitemradio" aria-checked="false" data-zoom-preset="0.3"', html)
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        self.assertRegex(css, r"\.desk-zoom-presets\s*\{[^}]*bottom:\s*46px;[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*width:\s*76px;")
        self.assertIn("animation: desk-zoom-presets-rise 170ms cubic-bezier(0.2, 0.8, 0.2, 1);", css)
        self.assertIn("@keyframes desk-zoom-presets-rise", css)
        self.assertIn(".desk-zoom-presets button.is-active,", css)
        self.assertIn("function updateZoomPresetButtons", canvas_js)
        self.assertIn("button.setAttribute('aria-checked', isActive ? 'true' : 'false');", canvas_js)

    def test_dark_settings_center_uses_graphite_orange_palette(self):
        html = read_text("desktop.html")
        css = read_text("styles/desktop-liquid.css")

        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertIn("body.desk-app[data-theme=\"dark\"] .desk-settings", css)
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings\s*\{[\s\S]*?--desk-ink:\s*#edf2f3;[\s\S]*?--desk-jewel-top:\s*#ff6a22;[\s\S]*?background:\s*\n\s*linear-gradient\(180deg, rgba\(48, 56, 58, 0\.86\), rgba\(31, 37, 39, 0\.92\)\),\n\s*rgba\(32, 38, 40, 0\.84\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-tabs\s*\{[\s\S]*?rgba\(28, 34, 36, 0\.58\);[\s\S]*?rgba\(255, 255, 255, 0\.07\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-tabs button\.is-active,[\s\S]*?linear-gradient\(180deg, rgba\(255, 122, 51, 0\.96\), rgba\(185, 51, 18, 0\.96\)\);[\s\S]*?rgba\(255, 148, 92, 0\.58\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings__actions button\s*\{[\s\S]*?color:\s*#ffb089;[\s\S]*?rgba\(53, 62, 64, 0\.94\)[\s\S]*?rgba\(31, 37, 39, 0\.96\)[\s\S]*?rgba\(255, 106, 34, 0\.28\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-pool-summary span\s*\{[\s\S]*?rgba\(53, 62, 64, 0\.82\)[\s\S]*?rgba\(31, 37, 39, 0\.88\)[\s\S]*?rgba\(255, 255, 255, 0\.08\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-form__actions button\.is-primary,[\s\S]*?rgba\(255, 122, 51, 0\.96\)[\s\S]*?rgba\(185, 51, 18, 0\.96\)"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-form input,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-settings-textarea\s*\{[\s\S]*?rgba\(28, 34, 36, 0\.74\);[\s\S]*?rgba\(255, 255, 255, 0\.07\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-path em,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-settings-auth-file span,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-settings-account__main span,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-settings-pool-summary span\.is-ok\s*\{[\s\S]*?rgba\(34, 197, 94, 0\.16\);[\s\S]*?rgba\(150, 240, 189, 0\.24\);"
        )

    def test_dark_gallery_workspace_uses_graphite_orange_palette(self):
        html = read_text("desktop.html")
        css = read_text("styles/desktop-liquid.css")

        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery\s*\{[\s\S]*?--desk-ink:\s*#edf2f3;[\s\S]*?--desk-jewel-top:\s*#ff6a22;[\s\S]*?linear-gradient\(180deg, rgba\(48, 56, 58, 0\.86\), rgba\(31, 37, 39, 0\.92\)\),\n\s*rgba\(32, 38, 40, 0\.84\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-tabs,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-search,[\s\S]*?rgba\(28, 34, 36, 0\.58\);[\s\S]*?rgba\(255, 255, 255, 0\.08\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-tabs button\.is-active,[\s\S]*?linear-gradient\(180deg, rgba\(255, 122, 51, 0\.96\), rgba\(185, 51, 18, 0\.96\)\);[\s\S]*?rgba\(255, 148, 92, 0\.58\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-inspector,[\s\S]*?body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-set-asset\s*\{[\s\S]*?rgba\(42, 50, 52, 0\.72\)[\s\S]*?rgba\(31, 37, 39, 0\.82\)"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-selected\s*\{[\s\S]*?background:\s*rgba\(28, 34, 36, 0\.58\);[\s\S]*?border-color:\s*rgba\(255, 255, 255, 0\.07\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-card\s*\{[\s\S]*?--desk-gallery-card-shadow:[\s\S]*?rgba\(0, 0, 0, 0\.22\)"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-card:hover,[\s\S]*?body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-card:focus-visible\s*\{[\s\S]*?box-shadow:\s*var\(--desk-gallery-card-shadow-hover\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery-inspector__actions \.desk-button:disabled,[\s\S]*?rgba\(53, 62, 64, 0\.58\)[\s\S]*?rgba\(31, 37, 39, 0\.62\)"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-controls::before\s*\{[\s\S]*?rgba\(32, 39, 41, 0\.74\)[\s\S]*?backdrop-filter:\s*none;"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-head,[\s\S]*?body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-taxonomy\s*\{[\s\S]*?background:\s*transparent;[\s\S]*?backdrop-filter:\s*none;"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-tabs,[\s\S]*?body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-sync\s*\{[\s\S]*?border-top:\s*1px\s+solid\s+rgba\(255, 255, 255, 0\.06\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-tabs span,[\s\S]*?body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-sync em\s*\{[\s\S]*?color:\s*rgba\(176, 188, 191, 0\.8\);"
        )
        self.assertRegex(
            css,
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-actions button:hover,[\s\S]*?body\.desk-app\[data-theme=\"dark\"\] \.desk-gallery \.desk-prompt-source-taxonomy button\.is-active\s*\{[\s\S]*?linear-gradient\(180deg, rgba\(255, 122, 51, 0\.92\), rgba\(185, 51, 18, 0\.92\)\);"
        )

    def test_progress_and_transient_feedback_use_bottom_status_message_area(self):
        html = read_text("desktop.html")
        results_js = read_text("scripts/desktop-results.js")
        settings_js = read_text("scripts/desktop-settings.js")

        self.assertIn("desk-status-group--feedback", html)
        self.assertIn('id="deskSidecarStatus"', html)
        self.assertIn('id="deskFallbackStatus"', html)
        self.assertIn('id="deskStatusMessage"', html)
        self.assertIn("'deskStatusMessage'", results_js)
        self.assertLess(html.index("desk-status-group--task"), html.index("desk-status-group--output"))
        self.assertLess(html.index("desk-status-group--output"), html.index("desk-status-group--feedback"))
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-status-chip--service,\s*\n\.desk-status-group--run \.desk-status-chip--ok\s*\{[^}]*background:\s*\n\s*linear-gradient\(180deg,\s*rgba\(227,\s*250,\s*240,\s*0\.96\),\s*rgba\(212,\s*236,\s*245,\s*0\.82\)\);"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-status-chip--service::after,\s*\n\.desk-status-group--run \.desk-status-chip--ok::after\s*\{[^}]*rgba\(34,\s*197,\s*94,\s*0\.34\)"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-status-group--run \.desk-status-chip--ok:not\(\.desk-status-chip--service\)::before\s*\{[^}]*background:\s*#22c55e;"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-status-group--feedback\s*\{[^}]*margin-left:\s*auto;[^}]*flex:\s*0\s+1"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-status-feedback-trigger\s*\{[^}]*color:\s*#138a42;"
        )
        self.assertIn("data-tone=\"error\"", read_text("styles/desktop-liquid.css"))
        self.assertIn("function setBottomStatus", results_js)
        self.assertIn("let nextBottomMessage = '';", results_js)
        self.assertIn("nextBottomMessage = output.progressText || DesktopState.getStatusLabel(status);", results_js)
        self.assertIn("status === 'canceled') {", results_js)
        self.assertIn("setBottomStatus(nextBottomMessage, nextBottomTone);", results_js)
        self.assertIn("const sourceValue = (snakeName, camelName, fallback = '') =>", results_js)
        self.assertIn("pendingOutput.taskId = '';", results_js)
        self.assertIn("task_id: '',", results_js)
        self.assertIn("const shouldApplyToOutput = options.applyToOutput === true || !output.taskId || DesktopState.isFailure(output.status);", results_js)
        state_js = read_text("scripts/desktop-state.js")
        self.assertIn("function sanitizeOutputState", state_js)
        self.assertIn("请先连接(?:或上传)?一张图片", state_js)
        self.assertIn("state.outputs = { ...state.outputs, ...sanitizeOutputMap(parsed.outputs) };", state_js)
        self.assertNotIn("${output.progressText || '连接模型节点后点击生成。'}", results_js)

        show_message_start = results_js.index("function showTransientMessage")
        next_function = results_js.index("\n  function getCancelableTaskEntries", show_message_start)
        show_message_body = results_js[show_message_start:next_function]
        self.assertIn("els.deskStatusMessage", show_message_body)
        self.assertNotIn("deskProgressLabel", show_message_body)
        self.assertRegex(show_message_body, re.compile(r"dataset\.tone\s*=\s*tone"))

        self.assertIn("showTransientMessage?.('润色配置已保存。'", settings_js)
        self.assertIn("showTransientMessage?.('GPT Provider 配置已保存。'", settings_js)

    def test_file_gallery_has_dedicated_preview_modal(self):
        html = read_text("desktop.html")
        history_js = read_text("scripts/desktop-history.js")
        css = read_text("styles/desktop-liquid.css")

        self.assertIn('id="deskFilePreviewModal"', html)
        self.assertIn('id="deskFilePreviewStage"', html)
        self.assertIn('id="deskFilePreviewLayers"', html)
        self.assertIn("function openEditableFilePreview", history_js)
        self.assertIn("data-gallery-file-preview", history_js)
        self.assertIn("sendEditableFile(previewEditableFile", history_js)
        self.assertIn("deleteEditableFile(previewEditableFile", history_js)
        self.assertRegex(css, r"\.desk-file-preview-modal\s*\{[^}]*position:\s*fixed;")
        self.assertRegex(css, r"\.desk-file-preview-modal\.is-open\s*\{[^}]*display:\s*flex;")

    def test_gallery_preview_can_continue_editing_image(self):
        html = read_text("desktop.html")
        history_js = read_text("scripts/desktop-history.js")
        canvas_js = read_text("scripts/desktop-canvas.js")
        css = read_text("styles/desktop-liquid.css")

        self.assertIn('id="deskGalleryPreviewEditBtn"', html)
        self.assertIn("continueEditPreviewAsset", history_js)
        self.assertIn("deskGalleryPreviewEditBtn", history_js)
        self.assertIn("data-history-edit", history_js)
        self.assertIn('class="desk-icon desk-icon--edit"', history_js)
        self.assertIn('class="desk-history-item__copy"', history_js)
        self.assertIn('class="desk-history-item__meta"', history_js)
        self.assertIn('aria-label="继续编辑"', history_js)
        self.assertNotIn('title="创建继续编辑流程">编辑</button>', history_js)
        self.assertIn('url("../assets/icons/edit-pencil.svg")', read_text("styles/desktop-liquid.css"))
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-history-row__actions\s*\{[^}]*align-content:\s*center;[^}]*justify-items:\s*center;"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-history-edit\s*\{[^}]*width:\s*28px;[^}]*height:\s*28px;[^}]*color:\s*var\(--desk-muted\);"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-history-item\s*\{[^}]*grid-template-columns:\s*44px\s*minmax\(0,\s*1fr\);[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-history-item strong\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*none;[^}]*font-size:\s*11px;[^}]*text-overflow:\s*ellipsis;"
        )
        self.assertRegex(
            read_text("styles/desktop-liquid.css"),
            r"\.desk-history-item__meta\s*\{[^}]*width:\s*100%;[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;"
        )
        self.assertIn("continueEditHistoryItem", history_js)
        self.assertIn("data-result-edit", read_text("scripts/desktop-results.js"))
        self.assertIn("desk-result-edit", read_text("styles/desktop-liquid.css"))
        self.assertIn("continueEditFromHistoryItem", canvas_js)
        self.assertIn("openImageEditor(imageNodeId)", canvas_js)
        self.assertIn("connectNodes(imageNodeId, inputNodeId)", canvas_js)
        self.assertNotIn("connectNodes(inputNodeId, outputNodeId)", canvas_js)
        self.assertIn("ensureImageOutputsForConfig(targetOutputId, config)", canvas_js)
        self.assertIn("['shape', '形状'", canvas_js)
        self.assertNotIn("['rect', '矩形'", canvas_js)
        self.assertNotIn("['ellipse', '圆形'", canvas_js)
        self.assertIn("'#ffffff'", canvas_js)
        self.assertIn("rectFilled", canvas_js)
        self.assertIn("ellipseFilled", canvas_js)
        self.assertIn("data-image-edit-export-node", canvas_js)
        self.assertIn("exportImageEditAnnotatedToNode", canvas_js)
        self.assertIn("insertImageNode({", canvas_js)
        self.assertIn("desk-image-editor__rail--top", canvas_js)
        self.assertIn("desk-image-editor__rail--bottom", canvas_js)
        self.assertIn("data-image-edit-zoom-in", canvas_js)
        self.assertIn("data-image-edit-zoom-out", canvas_js)
        self.assertIn("data-image-edit-zoom-fit", canvas_js)
        self.assertIn("setImageEditZoom", canvas_js)
        self.assertIn("IMAGE_EDIT_ZOOM_STEP", canvas_js)
        self.assertIn("getImageEditToolIcon(tool)", canvas_js)
        self.assertIn("select: `assets/image-editor-icons/select.svg", canvas_js)
        self.assertIn("eraser: `assets/image-editor-icons/eraser.svg", canvas_js)
        self.assertNotIn("desk-image-editor__rail--left", canvas_js)
        self.assertNotIn("desk-image-editor__rail--right", canvas_js)
        self.assertNotIn("data-image-edit-prompt", canvas_js)
        self.assertNotIn("编辑说明</span>", canvas_js)
        self.assertNotIn("data-image-edit-submit", canvas_js)
        self.assertIn("new fabric.Path(buildImageEditArrowPath", canvas_js)
        self.assertIn("applyImageEditObjectControls(object, state.color)", canvas_js)
        self.assertIn("return applyImageEditObjectControls(pin, fill)", canvas_js)
        self.assertIn("imageEditScreenToCanvasSize(28)", canvas_js)
        self.assertIn("cornerSize: imageEditScreenToCanvasSize(8)", canvas_js)
        self.assertIn("touchCornerSize: imageEditScreenToCanvasSize(26)", canvas_js)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)
        self.assertIn(".desk-image-editor__rail--top", css)
        self.assertIn(".desk-image-editor__rail--bottom", css)
        self.assertIn("flex-wrap: nowrap;", css)
        self.assertIn("width: 32px;", css)
        self.assertIn("clip-path: inset(50%);", css)
        self.assertIn("display: none;", css)
        self.assertIn("overflow: hidden;", css)
        self.assertIn(".desk-image-editor__canvas-shell", css)
        self.assertIn("overflow: auto;", css)
        self.assertIn(".desk-image-editor__zoom", css)
        self.assertIn("scrollbar-width: none;", css)
        self.assertIn("width: max-content;", css)
        self.assertIn("display: inline-grid;", css)

    def test_gallery_workspace_uses_prompt_drawer_glass(self):
        html = read_text("desktop.html")
        css = read_text("styles/desktop-liquid.css")
        history_js = read_text("scripts/desktop-history.js")

        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn("function historySortTime", history_js)
        self.assertIn(".sort((a, b) => historySortTime(b) - historySortTime(a))", history_js)
        self.assertRegex(
            css,
            r"\.desk-history__list\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*justify-content:\s*flex-start;"
        )
        self.assertNotIn("<p>全局资产</p>", html)
        self.assertNotIn('id="deskGalleryModelBtn"', html)
        self.assertNotIn('id="deskGalleryApplyBtn"', html)
        self.assertNotIn('id="deskGallerySendBtn"', html)
        self.assertNotIn('id="deskGalleryLayoutBtn"', html)
        self.assertNotIn('id="deskGalleryCopyPromptBtn"', html)
        self.assertNotIn('id="deskGalleryFavoriteBtn"', html)
        self.assertNotIn("'deskGalleryModelBtn'", history_js)
        self.assertNotIn("'deskGalleryApplyBtn'", history_js)
        self.assertNotIn("'deskGallerySendBtn'", history_js)
        self.assertNotIn("'deskGalleryLayoutBtn'", history_js)
        self.assertNotIn("'deskGalleryCopyPromptBtn'", history_js)
        self.assertNotIn("'deskGalleryFavoriteBtn'", history_js)
        self.assertNotIn("els.deskGalleryModelBtn?.addEventListener", history_js)
        self.assertNotIn("els.deskGalleryFavoriteBtn?.addEventListener", history_js)
        self.assertIn("选择图片后可对比、发送到画布或整理候选集。", html)
        self.assertIn("选择图片后可对比、发送到画布或整理候选集。", history_js)
        self.assertNotIn('id="deskRefreshHistoryBtn"', html)
        self.assertNotIn("'deskRefreshHistoryBtn'", history_js)
        self.assertIn("let historyGenieTimer = null;", history_js)
        self.assertIn("let historyGenieRaf = 0;", history_js)
        self.assertIn("let historyGenieRunId = 0;", history_js)
        self.assertIn("const HISTORY_GENIE_DURATION_MS = 500;", history_js)
        self.assertIn("function renderHistoryGenieFrame", history_js)
        self.assertIn("ctx.drawImage(source, 0, sourceY, sourceWidth, 1", history_js)
        self.assertIn("const runId = ++historyGenieRunId;", history_js)
        self.assertIn("stopHistoryGenieAnimation();", history_js)
        self.assertIn("if (runId !== historyGenieRunId) return;", history_js)
        self.assertIn("animateHistoryGenieClose(panel, runId)", history_js)
        self.assertIn("animateHistoryGenieOpen(panel, runId)", history_js)
        self.assertIn("panel.classList.add('is-genie-closing')", history_js)
        self.assertIn("panel.classList.add('is-genie-materializing')", history_js)
        self.assertIn("els.deskHistoryExpandBtn?.setAttribute('aria-expanded'", history_js)
        self.assertRegex(css, r"\.desk-gallery\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.4\);")
        self.assertRegex(css, r"\.desk-gallery\s*\{[^}]*border:\s*1px\s*solid\s*rgba\(255,\s*255,\s*255,\s*0\.28\);")
        self.assertRegex(css, r"\.desk-gallery\s*\{[^}]*backdrop-filter:\s*blur\(4px\)\s*saturate\(1\.06\);")
        self.assertRegex(css, r"\.desk-gallery__actions button,\s*\n\.desk-gallery-tabs,")
        self.assertRegex(css, r"\.desk-gallery\s*\{[^}]*gap:\s*8px;[^}]*padding:\s*12px;")
        self.assertRegex(css, r"\.desk-gallery__header h2\s*\{[^}]*font-size:\s*17px;")
        self.assertNotIn(".desk-compare__header h2", css)
        self.assertRegex(css, r"\.desk-gallery__actions button\s*\{[^}]*width:\s*24px;[^}]*height:\s*24px;")
        self.assertRegex(css, r"\.desk-compare__actions button\s*\{[^}]*width:\s*34px;[^}]*height:\s*34px;")
        self.assertRegex(css, r"\.desk-gallery__actions svg\s*\{[^}]*width:\s*13px;[^}]*height:\s*13px;")
        self.assertRegex(css, r"\.desk-gallery-tabs\s*\{[^}]*align-items:\s*center;[^}]*gap:\s*3px;[^}]*height:\s*30px;[^}]*min-width:\s*min\(226px,\s*100%\);[^}]*min-height:\s*30px;[^}]*padding:\s*2px;")
        self.assertRegex(css, r"\.desk-gallery-tabs button\s*\{[^}]*height:\s*24px;[^}]*min-width:\s*56px;[^}]*font-size:\s*11px;")
        self.assertRegex(css, r"\.desk-gallery-search\s*\{[^}]*gap:\s*6px;[^}]*height:\s*30px;[^}]*padding:\s*0\s*9px;")
        self.assertRegex(css, r"\.desk-gallery-filter\s*\{[^}]*flex:\s*0\s*1\s*126px;[^}]*height:\s*30px;[^}]*font-size:\s*11px;")
        self.assertRegex(css, r"#deskGalleryFilterSelect \+ \.desk-select-shell\s*\{[^}]*flex:\s*0\s*1\s*126px;[^}]*min-width:\s*106px;")
        self.assertRegex(css, r"#deskGalleryFilterSelect \+ \.desk-select-shell \.desk-select-trigger\s*\{[^}]*height:\s*30px;[^}]*padding:\s*0\s*7px;[^}]*font-size:\s*11px;[^}]*border-radius:\s*10px;")
        self.assertRegex(css, r"\.desk-gallery-stats\s*\{[^}]*gap:\s*5px;[^}]*min-height:\s*24px;")
        self.assertRegex(css, r"\.desk-gallery-stats span\s*\{[^}]*min-height:\s*21px;[^}]*padding:\s*0\s*8px;[^}]*font-size:\s*10px;")
        self.assertRegex(css, r"\.desk-gallery-tag-filter\s*\{[^}]*flex:\s*0\s*1\s*86px;[^}]*height:\s*30px;")
        self.assertRegex(css, r"body\.desk-app\s*\{[^}]*--desk-jewel-top:\s*#0b58a8;[^}]*--desk-jewel-bottom:\s*#021f4f;")
        self.assertNotRegex(css, r"\.desk-gallery__actions button:not\(\.desk-button--danger\),[^}]*background:\s*var\(--desk-jewel-gradient\);")
        self.assertRegex(css, r"\.desk-gallery__actions button\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.7\);")
        self.assertRegex(css, r"\.desk-button--generate:hover:not\(:disabled\),[^}]*background:\s*var\(--desk-jewel-gradient-hover\);")
        assert_asset_has_cache_bust(self, html, "styles/desktop-layout.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-pose.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-file-results.css")
        self.assertNotRegex(read_text("styles/desktop-layout.css"), r"background:\s*var\(--desk-jewel-gradient,")
        self.assertNotRegex(read_text("styles/desktop-pose.css"), r"background:\s*var\(--desk-jewel-gradient,")
        self.assertNotRegex(read_text("styles/desktop-file-results.css"), r"background:\s*var\(--desk-jewel-gradient,")
        self.assertRegex(read_text("styles/desktop-file-results.css"), r"\.desk-file-card__actions a,[^}]*\.desk-file-card__actions button\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.62\);")
        self.assertRegex(css, r"\.desk-gallery-inspector\s*\{[^}]*background:\s*rgba\(250,\s*253,\s*255,\s*0\.72\);")
        self.assertRegex(css, r"\.desk-gallery-inspector\s*\{[^}]*box-shadow:[^}]*0\s+18px\s+42px\s+rgba\(31,\s*45,\s*62,\s*0\.1\)")
        self.assertRegex(css, r"\.desk-gallery-selected\s*\{[^}]*background:\s*rgba\(245,\s*250,\s*253,\s*0\.7\);[^}]*border:")
        self.assertRegex(css, r"\.desk-gallery-selected \.desk-gallery-empty\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.66\);")
        self.assertRegex(css, r"\.desk-gallery-inspector,[^}]*\.desk-gallery-selected-item,[^}]*\.desk-prompt-source-taxonomy\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.4\);")
        self.assertRegex(css, r"\.desk-gallery-tabs button\.is-active,[^}]*\.desk-prompt-source-taxonomy button\.is-active\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.5\);")
        self.assertRegex(css, r"\.desk-prompt-source-controls::before\s*\{[^}]*backdrop-filter:\s*blur\(18px\)\s*saturate\(1\.18\);")
        self.assertRegex(css, r"\.desk-prompt-source-tabs\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.16\);[^}]*backdrop-filter:\s*blur\(12px\)\s*saturate\(1\.1\);")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-controls\s*\{[^}]*gap:\s*0;[^}]*padding:\s*0;[^}]*overflow:\s*hidden;[^}]*border-radius:\s*12px;")
        self.assertRegex(css, r"\.desk-gallery-grid\s*\{[^}]*--desk-gallery-card-height:\s*214px;")
        self.assertRegex(css, r"\.desk-gallery-grid\s*\{[^}]*--desk-gallery-inline-padding:\s*14px;")
        self.assertRegex(css, r"\.desk-gallery-grid\s*\{[^}]*padding:\s*2px\s*var\(--desk-gallery-inline-padding\)\s*20px;")
        self.assertRegex(css, r"\.desk-gallery-grid\.is-prompt-sources\s*\{[^}]*--desk-prompt-source-inline-end:\s*14px;[^}]*padding:\s*0;")
        self.assertRegex(css, r"\.desk-prompt-source-scroll\s*\{[^}]*padding:\s*10px\s*2px\s*18px\s*0;")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-controls,[^}]*\.desk-gallery \.desk-prompt-source-taxonomy\s*\{[^}]*backdrop-filter:\s*none;")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-head,[^}]*\.desk-gallery \.desk-prompt-source-taxonomy\s*\{[^}]*background:\s*transparent;[^}]*border:\s*0;[^}]*border-radius:\s*0;")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-tabs,[^}]*\.desk-gallery \.desk-prompt-source-sync\s*\{[^}]*border-top:\s*1px\s+solid\s+rgba\(92, 112, 132, 0\.12\);")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-taxonomy\.is-collapsed\s*\{[^}]*padding:\s*8px\s*12px;")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-head__meta span,[^}]*\.desk-gallery \.desk-prompt-source-taxonomy button\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.18\);")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-tabs button\.is-active\s*\{[^}]*background:\s*transparent;[^}]*border-color:\s*transparent;")
        self.assertRegex(css, r"\.desk-gallery \.desk-prompt-source-taxonomy button\.is-active\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.32\);")
        self.assertRegex(css, r"\.desk-gallery-card,[^}]*\.desk-gallery-set\s*\{[^}]*transform-origin:\s*center\s*top;")
        self.assertIn("desk-gallery-card__meta-head", history_js)
        self.assertIn("desk-gallery-card__meta-copy", history_js)
        self.assertIn("desk-gallery-card__meta-actions", history_js)
        self.assertIn("desk-gallery-card__description", history_js)
        self.assertIn("function compactGalleryModelLabel", history_js)
        self.assertIn("return 'gemini-pro';", history_js)
        self.assertIn("return 'gemini-flash';", history_js)
        self.assertIn("function galleryAssetModelLabel", history_js)
        self.assertIn("function galleryAssetRatioLabel", history_js)
        self.assertIn("function requestedAssetResolution", history_js)
        self.assertIn("function actualAssetResolution", history_js)
        self.assertIn("function galleryAssetResolutionLabel", history_js)
        self.assertIn("实际 ${prettyResolutionLabel(actual)}（请求 ${prettyResolutionLabel(requested)}）", history_js)
        self.assertIn("resolution: actualResolution || requestedResolution", history_js)
        self.assertIn("resolutionMismatch:", history_js)
        self.assertIn("function updateGalleryCardState", history_js)
        self.assertIn("function restoreGalleryCardFocus", history_js)
        self.assertIn("function focusGalleryAsset", history_js)
        self.assertIn("const focused = previewAsset?.id === asset.id;", history_js)
        self.assertIn("focusGalleryAsset(assetId);", history_js)
        self.assertIn("restoreGalleryCardFocus(assetId);", history_js)
        self.assertIn("if (galleryFilter === 'selected') {\n      renderGallery();\n    } else {\n      updateGalleryCardState(assetId);\n    }", history_js)
        self.assertIn("await updateAssetMeta(asset, { favorite: nextValue }, options);", history_js)
        self.assertIn("toggleAssetFavorite(asset, { render: galleryFilter === 'favorite' })", history_js)
        self.assertIn(".then(() => restoreGalleryCardFocus(asset.id))", history_js)
        self.assertIn("event.preventDefault();\n        event.stopPropagation();\n        toggleAssetSelection", history_js)
        self.assertIn("restoreGalleryCardFocus(asset.id)", history_js)
        self.assertIn("is-remote-source", history_js)
        self.assertIn("has-gallery-switcher", history_js)
        self.assertIn("has-gallery-count", history_js)
        self.assertIn("is-focus-active", history_js)
        self.assertNotIn("desk-gallery-card__verified", history_js)
        self.assertNotIn("String(asset.prompt || asset.file || sourceBadge || '')", history_js)
        self.assertNotIn("description || detailLine", history_js)
        self.assertIn("const summaryLine = `比例 ${ratioLabel} · 分辨率 ${resolutionLabel}`;", history_js)
        self.assertRegex(css, r"\.desk-gallery-card\s*\{[^}]*--desk-gallery-card-pad:\s*4px;[^}]*--desk-gallery-card-shadow:")
        self.assertRegex(css, r"\.desk-gallery-card\s*\{[^}]*height:\s*var\(--desk-gallery-card-height\);[^}]*background:\s*var\(--desk-gallery-card-surface\);[^}]*border:\s*0;")
        self.assertRegex(css, r"\.desk-gallery-card\s*\{[^}]*border-radius:\s*14px;[^}]*box-shadow:\s*var\(--desk-gallery-card-shadow\);")
        self.assertRegex(css, r"\.desk-prompt-source-scroll \.desk-gallery-card\s*\{[^}]*height:\s*var\(--desk-gallery-card-height\);")
        self.assertRegex(css, r"\.desk-gallery-card__image\s*\{[^}]*position:\s*relative;[^}]*height:\s*var\(--desk-gallery-card-image-height\);[^}]*clip-path:\s*inset\(0 round var\(--desk-gallery-card-image-radius\)\);")
        self.assertRegex(css, r"\.desk-gallery-card__image::after\s*\{[^}]*box-shadow:\s*var\(--desk-gallery-image-inner-shadow\);[^}]*pointer-events:\s*none;")
        self.assertRegex(css, r"\.desk-gallery-card__meta\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*auto;[^}]*padding:\s*0\s*2px\s*0\s*3px;")
        self.assertRegex(css, r"\.desk-gallery-card__meta\s*\{[^}]*background:\s*transparent;[^}]*border-top:\s*0;[^}]*isolation:\s*isolate;")
        self.assertRegex(css, r"\.desk-gallery-card__meta-actions\s*\{[^}]*flex-wrap:\s*wrap;[^}]*max-width:\s*74px;")
        self.assertRegex(css, r"\.desk-gallery-card__meta-actions button\s*\{[^}]*width:\s*18px;[^}]*height:\s*18px;")
        self.assertRegex(css, r"\.desk-gallery-card__lineage\s*\{[^}]*position:\s*static;")
        self.assertRegex(css, r"\.desk-gallery-card__switcher\s*\{[^}]*top:\s*auto;[^}]*left:\s*8px;[^}]*bottom:\s*8px;")
        self.assertRegex(css, r"\.desk-gallery-card__meta strong\s*\{[^}]*font-size:\s*10px;")
        self.assertRegex(css, r"\.desk-gallery-card__description\s*\{[^}]*font-size:\s*8px;[^}]*-webkit-line-clamp:\s*1;")
        self.assertRegex(css, r"\.desk-gallery-card:hover,[^}]*\.desk-gallery-set:hover,[^}]*\.desk-gallery-card\.is-selected,[^}]*\.desk-gallery-card\.is-focus-active,[^}]*\.desk-gallery-card:focus-visible\s*\{")
        self.assertRegex(css, r"\.desk-gallery-card:hover \.desk-gallery-card__image img,[^}]*\.desk-gallery-card\.is-hover-active \.desk-gallery-card__image img,[^}]*\.desk-gallery-card\.is-focus-active \.desk-gallery-card__image img,[^}]*\.desk-gallery-card:focus-visible \.desk-gallery-card__image img\s*\{[^}]*transform:\s*scale\(1\.1\);")
        self.assertRegex(css, r"\.desk-gallery-card:hover,[^}]*\.desk-gallery-set:hover,[^}]*\.desk-gallery-card\.is-hover-active,[^}]*\.desk-gallery-set\.is-hover-active\s*\{[^}]*transform:\s*none;")
        self.assertNotIn("transform: translateZ(0) scale(1.2);", css)
        self.assertNotIn(".desk-gallery-grid.is-card-hovering .desk-gallery-card:not(.is-hover-active),", css)
        self.assertNotIn(".desk-prompt-source-scroll.is-card-hovering .desk-gallery-card:not(.is-hover-active)", css)
        self.assertNotIn(".desk-gallery-grid.is-card-hovering .desk-gallery-card:not(.is-hover-active)::after", css)
        self.assertNotIn("transform: translateZ(0) scale(0.985);", css)
        self.assertIn("bindGalleryHoverState", history_js)
        self.assertIn("is-card-hovering", history_js)
        self.assertIn("is-hover-active", history_js)
        self.assertNotRegex(css, r"\.desk-gallery-grid:has\(\.desk-gallery-card:hover")
        self.assertNotRegex(css, r"\.desk-prompt-source-scroll:has\(\.desk-gallery-card:hover")

    def test_gallery_cards_use_webp_thumbs_and_virtual_scrolling(self):
        html = read_text("desktop.html")
        history_js = read_text("scripts/desktop-history.js")
        auth_js = read_text("scripts/auth-api.js")
        css = read_text("styles/desktop-liquid.css")

        assert_asset_has_cache_bust(self, html, "scripts/auth-api.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertIn("const GALLERY_INITIAL_RENDER_LIMIT = 28;", history_js)
        self.assertIn("function thumbUrlForMediaUrl", history_js)
        self.assertIn("return `/thumb/${encodeURIComponent(path)}.webp?w=420`;", history_js)
        self.assertIn("thumbUrl: thumbUrlForMediaUrl(imageUrl),", history_js)
        self.assertIn("function renderVirtualGalleryCards", history_js)
        self.assertIn("function scheduleGalleryVirtualRender", history_js)
        self.assertIn("data-gallery-virtual-canvas", history_js)
        self.assertIn("scheduleGalleryVirtualRender(grid);", history_js)
        self.assertNotIn("GALLERY_RENDER_STEP", history_js)
        self.assertNotIn("function loadMoreGalleryImages", history_js)
        self.assertIn("'/thumb/'", auth_js)
        self.assertRegex(css, r"\.desk-gallery-virtual-canvas\s*\{[^}]*position:\s*relative;")
        self.assertRegex(css, r"\.desk-gallery-virtual-cell\s*\{[^}]*position:\s*absolute;[^}]*contain:\s*layout style;[^}]*overflow:\s*visible;")

    def test_canvas_select_menus_are_anchored_for_zoom_scaling(self):
        html = read_text("desktop.html")
        select_js = read_text("scripts/desktop-select.js")
        css = read_text("styles/desktop-liquid.css")

        assert_asset_has_cache_bust(self, html, "scripts/desktop-select.js")
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertIn("function usesAnchoredMenu(select)", select_js)
        self.assertIn("'.desk-canvas-world .desk-node'", select_js)
        self.assertIn("const menuMode = usesAnchoredMenu(select) ? 'anchored' : 'fixed';", select_js)
        self.assertIn("const anchorRoot = menuMode === 'anchored' ? select.closest('label') : null;", select_js)
        self.assertIn("select.closest('.desk-param-grid, .desk-prompt-mode, .desk-prompt-panel, .desk-upload-panel, .desk-node__drawer')", select_js)
        self.assertIn("shell.dataset.menuMode = menuMode;", select_js)
        self.assertIn("shell.classList.toggle('is-anchored', menuMode === 'anchored');", select_js)
        self.assertIn("anchorRoot?.classList.add('desk-select-anchor-root');", select_js)
        self.assertIn("stackRoot?.classList.add('desk-select-stack-root');", select_js)
        self.assertIn("state.anchorRoot?.classList.add('is-select-open');", select_js)
        self.assertIn("state.anchorRoot?.classList.remove('is-select-open');", select_js)
        self.assertIn("state.stackRoot?.classList.add('is-select-open');", select_js)
        self.assertIn("state.stackRoot?.classList.remove('is-select-open');", select_js)
        self.assertIn("shell.appendChild(menu);", select_js)
        self.assertIn("document.body.appendChild(menu);", select_js)
        self.assertIn("function placeAnchoredMenu(state)", select_js)
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored\s*\{[^}]*z-index:\s*1;")
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored\.is-open\s*\{[^}]*z-index:\s*70;")
        self.assertRegex(css, r"\.desk-select-anchor-root\s*\{[^}]*position:\s*relative;")
        self.assertRegex(css, r"\.desk-select-anchor-root\.is-select-open\s*\{[^}]*z-index:\s*75;")
        self.assertRegex(css, r"\.desk-select-stack-root\s*\{[^}]*position:\s*relative;")
        self.assertRegex(css, r"\.desk-select-stack-root\.is-select-open\s*\{[^}]*z-index:\s*80;")
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored \.desk-select-menu\s*\{[^}]*position:\s*absolute;")
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored \.desk-select-menu\.is-above\s*\{[^}]*bottom:\s*calc\(100%\s*\+\s*4px\);")


if __name__ == "__main__":
    unittest.main()
