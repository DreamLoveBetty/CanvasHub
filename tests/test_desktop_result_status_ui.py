import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tests.legacy_css import read_legacy_css


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    path = ROOT / relative_path
    if not path.exists() and relative_path.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
        path = ROOT / "frontend" / relative_path
    return path.read_text(encoding="utf-8")


def assert_asset_has_cache_bust(testcase, html, asset_path):
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


class _DesktopScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            if attrs.get("src"):
                self.scripts.append(attrs)


def read_loaded_canvas_sources(testcase, html):
    """Read actual classic scripts, never snapshots or a reconstructed monolith."""
    parser = _DesktopScriptParser()
    parser.feed(html)
    scripts = [
        (attrs["src"].split("?", 1)[0], attrs)
        for attrs in parser.scripts
    ]
    host_path = "scripts/desktop-canvas.js"
    testcase.assertEqual(sum(path == host_path for path, _ in scripts), 1)
    host_index = next(i for i, (path, _) in enumerate(scripts) if path == host_path)
    sources = {}
    for index, (path, attrs) in enumerate(scripts):
        if path != host_path and not path.startswith("scripts/desktop-canvas-"):
            continue
        testcase.assertNotIn(path, sources, f"Duplicate canvas script: {path}")
        testcase.assertNotIn("async", attrs, path)
        testcase.assertNotIn("defer", attrs, path)
        testcase.assertIn(attrs.get("type", ""), ("", "text/javascript"), path)
        if path != host_path:
            testcase.assertLess(index, host_index, f"Canvas module must load before host: {path}")
        sources[path] = read_text(path)
    return sources


def read_named_function(testcase, source, name):
    """Extract one current named body, independent of its adjacent functions.

    The inspected bodies have ordinary strings/comments, not regex/template literals;
    reject those forms rather than silently truncating a future changed body.
    """
    declarations = list(re.finditer(
        r"\bfunction " + re.escape(name) + r"\([^\n]*\) \{", source
    ))
    testcase.assertEqual(len(declarations), 1, name)
    declaration = declarations[0]
    token_pattern = re.compile(
        r"//[^\n]*|/\*[\s\S]*?\*/|"
        r"\"(?:\\[\s\S]|[^\"\\])*\"|'(?:\\[\s\S]|[^'\\])*'|[{}]|[`/]"
    )
    depth = 1
    for token in token_pattern.finditer(source, declaration.end()):
        value = token.group()
        testcase.assertNotIn(value, ("`", "/"), f"Unsupported literal in {name}")
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
            if depth == 0:
                return source[declaration.start():token.end()]
    testcase.fail(f"Unterminated function: {name}")


class DesktopResultStatusUiTest(unittest.TestCase):
    def test_model_node_directly_owns_generation_controls_and_image_outputs(self):
        html = read_text("desktop.html")
        canvas_sources = read_loaded_canvas_sources(self, html)
        canvas_js = canvas_sources["scripts/desktop-canvas.js"]
        model_nodes_js = canvas_sources["scripts/desktop-canvas-model-nodes.js"]
        generation_js = canvas_sources["scripts/desktop-canvas-generation.js"]
        connections_js = canvas_sources["scripts/desktop-canvas-connections.js"]
        results_js = read_text("scripts/desktop-results.js")
        css = read_legacy_css()

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
        self.assertIn("function ensureImageOutputsForConfig", generation_js)
        self.assertIn("function syncOutputControlsToNodes", model_nodes_js)
        self.assertIn("syncOutputControlsToNodes(state.output, { save: false });", model_nodes_js)
        self.assertIn("function refreshOutputConfigStatus", results_js)
        self.assertIn("refreshOutputConfigStatus,", results_js)
        self.assertIn("function syncOutputControlsFromNode", model_nodes_js)
        self.assertIn("event.target.closest('[data-output-archive], [data-output-telegram]')", canvas_js)
        self.assertIn("updateBottom: node.classList.contains('desk-node--input')", model_nodes_js)
        self.assertIn("if (options.updateBottom !== false) renderOutputStatusChips(liveParams, status);", results_js)
        self.assertIn("const controls = globalOutputControlParams(params);", results_js)
        self.assertIn("const imagePaths = normalizeTaskImagePaths(task, resultFiles);", results_js)
        self.assertIn("task?.result_file", results_js)
        select_body = read_named_function(self, canvas_js, "selectNode")
        self.assertNotIn("syncOutputControlsToNodes", select_body)
        pointer_start = canvas_js.index("els.deskCanvasWorld?.addEventListener('pointerdown'")
        pointer_end = canvas_js.index("\n      const aliasShell", pointer_start)
        self.assertNotIn("syncOutputControlsToNodes", canvas_js[pointer_start:pointer_end])
        self.assertIn("const modelToImage = from?.type === 'input' && to?.type === 'image';", connections_js)
        self.assertIn("setImageNodeFromResult(targets[index], resultNodeId, output, index)", generation_js)
        self.assertIn("const DEFAULT_TEXT_NODE_WIDTH = 600;", canvas_js)
        self.assertIn("const DEFAULT_IMAGE_NODE_WIDTH = 600;", canvas_js)
        self.assertIn("const DEFAULT_IMAGE_LONGEST_SIDE = 520;", canvas_js)
        self.assertIn("desk-image-pop-in", css)
        self.assertIn("animation: desk-image-pop-in 0.47s", css)
        self.assertIn("cubic-bezier(0.17, 0.84, 0.44, 1.25)", css)

    def test_result_progress_is_only_visible_while_task_is_in_flight(self):
        html = read_text("desktop.html")
        canvas_sources = read_loaded_canvas_sources(self, html)
        model_nodes_js = canvas_sources["scripts/desktop-canvas-model-nodes.js"]
        results_js = read_text("scripts/desktop-results.js")
        css = read_legacy_css()

        self.assertNotIn('class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true"', html)
        self.assertIn('class="desk-progress-float" id="deskProgressFloat" aria-hidden="true"', html)
        self.assertIn('class="desk-progress-float__percent" data-progress-percent', html)
        self.assertIn("data-progress-percent-value", html)
        self.assertIn('class="desk-progress-float__timer" data-progress-timer', html)
        self.assertIn('class="desk-progress-wrap" aria-label="生成进度" aria-hidden="true"', model_nodes_js)
        self.assertNotIn("deskProgressLabel", html)
        for source in canvas_sources.values():
            self.assertNotIn("data-progress-label", source)
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
        css = read_legacy_css()
        tokens_css = read_text("styles/desktop-tokens.css")
        canvas_css = read_text("styles/desktop-canvas-nodes.css")
        prefs_js = read_text("scripts/desktop-preferences.js")

        self.assertNotIn("desk-window-dots", html)
        self.assertNotIn("desk-dot--red", html)
        self.assertNotIn("desk-dot--yellow", html)
        self.assertNotIn("desk-dot--green", html)
        self.assertNotIn(".desk-window-dots", css)
        self.assertNotIn(".desk-dot--red", css)
        self.assertIn('class="desk-titlebar-logo" aria-label="CanvasHub"', html)
        self.assertIn('class="desk-titlebar-logo__image"', html)
        assert_asset_has_cache_bust(self, html, "assets/animated.webp")
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
        self.assertRegex(css, r"\.desk-rail__glyph\s*\{[^}]*transition:\s*var\(--desk-motion-icon-transition\);")
        self.assertIn("--desk-motion-icon-transition:", tokens_css)
        self.assertIn("color var(--desk-motion-duration-fast) var(--desk-motion-ease-standard),", tokens_css)
        self.assertIn("fill var(--desk-motion-duration-fast) var(--desk-motion-ease-standard),", tokens_css)
        self.assertIn("stroke var(--desk-motion-duration-fast) var(--desk-motion-ease-standard),", tokens_css)
        self.assertIn("opacity var(--desk-motion-duration-normal) var(--desk-motion-ease-standard),", tokens_css)
        self.assertIn("transform var(--desk-motion-duration-normal) var(--desk-motion-ease-interactive);", tokens_css)
        self.assertNotRegex(f"{tokens_css}\n{css}", r"transition\s*:\s*all\b")
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
        self.assertRegex(
            canvas_css,
            r"body\.desk-app\[data-theme\] \.desk-node--input \.desk-input-footer "
            r"\.desk-manual-send:disabled\s*\{[^}]*"
            r"color:\s*var\(--desk-node-manual-send-disabled-ink\);[^}]*"
            r"background:\s*var\(--desk-node-manual-send-disabled-background\);[^}]*"
            r"border-color:\s*var\(--desk-node-manual-send-disabled-border\);[^}]*"
            r"box-shadow:\s*var\(--desk-node-manual-send-disabled-shadow\);",
        )
        self.assertNotIn(".desk-manual-send:disabled", css)
        for token in (
            "--desk-node-manual-send-disabled-ink",
            "--desk-node-manual-send-disabled-background",
            "--desk-node-manual-send-disabled-border",
            "--desk-node-manual-send-disabled-shadow",
        ):
            self.assertEqual(tokens_css.count(f"{token}:"), 2, token)
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

    def test_node_palette_uses_lucide_motion_icon_system(self):
        html = read_text("desktop.html")
        canvas_js = read_text("scripts/desktop-canvas.js")
        css = read_legacy_css()
        tokens_css = read_text("styles/desktop-tokens.css")

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
        self.assertRegex(css, r"\.desk-node-palette__icon\s*\{[^}]*transition:\s*var\(--desk-motion-icon-transition\);")
        self.assertIn("--desk-motion-icon-transition:", tokens_css)
        self.assertNotRegex(f"{tokens_css}\n{css}", r"transition\s*:\s*all\b")
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
        canvas_sources = read_loaded_canvas_sources(self, html)
        viewport_js = canvas_sources["scripts/desktop-canvas-viewport.js"]
        history_js = read_text("scripts/desktop-history.js")
        css = read_legacy_css()

        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn("--desk-minimap-open-height: 86px;", css)
        self.assertIn("--desk-minimap-open-height: 92px;", css)
        self.assertIn("height: var(--desk-minimap-open-height);", css)
        geometry_css = read_text("styles/desktop-geometry.css")
        self.assertNotRegex(css, r"\.desk-zoom-controls\s*\{[^}]*z-index:")
        self.assertRegex(
            geometry_css,
            r"body\.desk-app :is\(\.desk-rail, \.desk-history, \.desk-zoom-controls\)\s*\{"
            r"[^}]*z-index:\s*var\(--desk-layer-node\);",
        )
        self.assertIn("function getMiniMapTargetHeight", viewport_js)
        self.assertIn("function dispatchMiniMapLayoutChange", viewport_js)
        self.assertIn("function setMiniMapPinned", viewport_js)
        self.assertIn("targetHeight: getMiniMapTargetHeight(controls, !!pinned)", viewport_js)
        self.assertRegex(viewport_js, r"window\.setTimeout\(\(\) => \{\s*renderMiniMap\(\);\s*dispatchMiniMapLayoutChange\(!!controls\?\.classList\.contains\('is-pinned'\), controls\);\s*\}, 220\);")
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
        canvas_sources = read_loaded_canvas_sources(self, html)
        viewport_js = canvas_sources["scripts/desktop-canvas-viewport.js"]
        css = read_legacy_css()

        self.assertIn('aria-controls="deskZoomPresetMenu"', html)
        self.assertIn('role="menuitemradio" aria-checked="false" data-zoom-preset="0.3"', html)
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        self.assertRegex(css, r"\.desk-zoom-presets\s*\{[^}]*bottom:\s*46px;[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*width:\s*76px;")
        self.assertIn("animation: desk-zoom-presets-rise 170ms cubic-bezier(0.2, 0.8, 0.2, 1);", css)
        self.assertIn("@keyframes desk-zoom-presets-rise", css)
        self.assertIn(".desk-zoom-presets button.is-active,", css)
        self.assertIn("function updateZoomPresetButtons", viewport_js)
        self.assertIn("button.setAttribute('aria-checked', isActive ? 'true' : 'false');", viewport_js)

    def test_dark_settings_center_uses_graphite_orange_palette(self):
        html = read_text("desktop.html")
        css = read_legacy_css()

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
            r"body\.desk-app\[data-theme=\"dark\"\] \.desk-settings-path em,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-settings-account__main span,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-settings-pool-summary span\.is-ok\s*\{[\s\S]*?rgba\(34, 197, 94, 0\.16\);[\s\S]*?rgba\(150, 240, 189, 0\.24\);"
        )

    def test_dark_gallery_workspace_uses_graphite_orange_palette(self):
        html = read_text("desktop.html")
        css = read_legacy_css()

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
            read_legacy_css(),
            r"\.desk-status-chip--service,\s*\n\.desk-status-group--run \.desk-status-chip--ok\s*\{[^}]*background:\s*\n\s*linear-gradient\(180deg,\s*rgba\(227,\s*250,\s*240,\s*0\.96\),\s*rgba\(212,\s*236,\s*245,\s*0\.82\)\);"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-status-chip--service::after,\s*\n\.desk-status-group--run \.desk-status-chip--ok::after\s*\{[^}]*rgba\(34,\s*197,\s*94,\s*0\.34\)"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-status-group--run \.desk-status-chip--ok:not\(\.desk-status-chip--service\)::before\s*\{[^}]*background:\s*#22c55e;"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-status-group--feedback\s*\{[^}]*margin-left:\s*auto;[^}]*flex:\s*0\s+1"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-status-feedback-trigger\s*\{[^}]*color:\s*#138a42;"
        )
        self.assertIn("data-tone=\"error\"", read_legacy_css())
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

        show_message_body = read_named_function(self, results_js, "showTransientMessage")
        self.assertIn("els.deskStatusMessage", show_message_body)
        self.assertNotIn("deskProgressLabel", show_message_body)
        self.assertRegex(show_message_body, re.compile(r"dataset\.tone\s*=\s*tone"))

        self.assertIn("showTransientMessage?.('润色配置已保存。'", settings_js)
        self.assertIn("showTransientMessage?.('GPT Provider 配置已保存。'", settings_js)

    def test_file_gallery_has_dedicated_preview_modal(self):
        html = read_text("desktop.html")
        history_js = read_text("scripts/desktop-history.js")
        css = read_legacy_css()

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
        canvas_sources = read_loaded_canvas_sources(self, html)
        canvas_js = canvas_sources["scripts/desktop-canvas.js"]
        media_import_js = canvas_sources["scripts/desktop-canvas-media-import.js"]
        generation_js = canvas_sources["scripts/desktop-canvas-generation.js"]
        image_editor_js = canvas_sources["scripts/desktop-canvas-image-editor.js"]
        image_editor_tools_js = canvas_sources["scripts/desktop-canvas-image-editor-tools.js"]
        css = read_legacy_css()

        self.assertIn('id="deskGalleryPreviewEditBtn"', html)
        self.assertIn("continueEditPreviewAsset", history_js)
        self.assertIn("deskGalleryPreviewEditBtn", history_js)
        self.assertIn("data-history-edit", history_js)
        self.assertIn('class="desk-icon desk-icon--edit"', history_js)
        self.assertIn('class="desk-history-item__copy"', history_js)
        self.assertIn('class="desk-history-item__meta"', history_js)
        self.assertIn('aria-label="继续编辑"', history_js)
        self.assertNotIn('title="创建继续编辑流程">编辑</button>', history_js)
        self.assertIn('url("../assets/icons/edit-pencil.svg")', read_legacy_css())
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-history-row__actions\s*\{[^}]*align-content:\s*center;[^}]*justify-items:\s*center;"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-history-edit\s*\{[^}]*width:\s*28px;[^}]*height:\s*28px;[^}]*color:\s*var\(--desk-muted\);"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-history-item\s*\{[^}]*grid-template-columns:\s*44px\s*minmax\(0,\s*1fr\);[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-history-item strong\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*none;[^}]*font-size:\s*11px;[^}]*text-overflow:\s*ellipsis;"
        )
        self.assertRegex(
            read_legacy_css(),
            r"\.desk-history-item__meta\s*\{[^}]*width:\s*100%;[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;"
        )
        self.assertIn("continueEditHistoryItem", history_js)
        self.assertIn("data-result-edit", read_text("scripts/desktop-results.js"))
        self.assertIn("desk-result-edit", read_legacy_css())
        self.assertIn("continueEditFromHistoryItem", media_import_js)
        self.assertIn("openImageEditor(imageNodeId)", media_import_js)
        self.assertIn("connectNodes(imageNodeId, inputNodeId)", media_import_js)
        for source in canvas_sources.values():
            self.assertNotIn("connectNodes(inputNodeId, outputNodeId)", source)
        self.assertIn("ensureImageOutputsForConfig(targetOutputId, config)", generation_js)
        self.assertIn("['shape', '形状'", image_editor_js)
        for source in canvas_sources.values():
            self.assertNotIn("['rect', '矩形'", source)
        for source in canvas_sources.values():
            self.assertNotIn("['ellipse', '圆形'", source)
        self.assertIn("'#ffffff'", image_editor_js)
        self.assertIn("rectFilled", image_editor_js)
        self.assertIn("ellipseFilled", image_editor_js)
        self.assertIn("data-image-edit-export-node", image_editor_js)
        self.assertIn("exportImageEditAnnotatedToNode", image_editor_js)
        self.assertIn("insertImageNode({", image_editor_js)
        self.assertIn("desk-image-editor__rail--top", image_editor_js)
        self.assertIn("desk-image-editor__rail--bottom", image_editor_js)
        self.assertIn("data-image-edit-zoom-in", image_editor_js)
        self.assertIn("data-image-edit-zoom-out", image_editor_js)
        self.assertIn("data-image-edit-zoom-fit", image_editor_js)
        self.assertIn("setImageEditZoom", image_editor_js)
        self.assertIn("IMAGE_EDIT_ZOOM_STEP", canvas_js)
        self.assertIn("getImageEditToolIcon(tool)", image_editor_js)
        self.assertIn("select: `assets/image-editor-icons/select.svg", image_editor_tools_js)
        self.assertIn("eraser: `assets/image-editor-icons/eraser.svg", image_editor_tools_js)
        for source in canvas_sources.values():
            self.assertNotIn("desk-image-editor__rail--left", source)
        for source in canvas_sources.values():
            self.assertNotIn("desk-image-editor__rail--right", source)
        for source in canvas_sources.values():
            self.assertNotIn("data-image-edit-prompt", source)
        for source in canvas_sources.values():
            self.assertNotIn("编辑说明</span>", source)
        for source in canvas_sources.values():
            self.assertNotIn("data-image-edit-submit", source)
        self.assertIn("new fabric.Path(buildImageEditArrowPath", image_editor_tools_js)
        self.assertIn("applyImageEditObjectControls(object, state.color)", image_editor_js)
        self.assertIn("return applyImageEditObjectControls(pin, fill)", image_editor_tools_js)
        self.assertIn("imageEditScreenToCanvasSize(28)", image_editor_tools_js)
        self.assertIn("cornerSize: imageEditScreenToCanvasSize(8)", image_editor_tools_js)
        self.assertIn("touchCornerSize: imageEditScreenToCanvasSize(26)", image_editor_tools_js)
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
        css = read_legacy_css()
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
        self.assertIn("let historyGenieHandle = null;", history_js)
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
        self.assertIn("const summaryLine = isPinterest", history_js)
        self.assertIn("? (asset.title || 'Pinterest Pin')", history_js)
        self.assertIn(": `比例 ${ratioLabel} · 分辨率 ${resolutionLabel}`;", history_js)
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
        css = read_legacy_css()

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
        css = read_legacy_css()

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
        self.assertIn("menuContainer(select).appendChild(menu);", select_js)
        self.assertIn("return select.closest('dialog') || document.body;", select_js)
        self.assertIn("function placeAnchoredMenu(state)", select_js)
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored\s*\{[^}]*z-index:\s*1;")
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored\.is-open\s*\{[^}]*z-index:\s*70;")
        self.assertRegex(css, r"\.desk-select-anchor-root\s*\{[^}]*position:\s*relative;")
        self.assertRegex(css, r"\.desk-select-anchor-root\.is-select-open\s*\{[^}]*z-index:\s*75;")
        self.assertRegex(css, r"\.desk-select-stack-root\s*\{[^}]*position:\s*relative;")
        self.assertRegex(css, r"\.desk-select-stack-root\.is-select-open\s*\{[^}]*z-index:\s*80;")
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored \.desk-select-menu\s*\{[^}]*position:\s*absolute;")
        self.assertRegex(css, r"\.desk-select-shell\.is-anchored \.desk-select-menu\.is-above\s*\{[^}]*bottom:\s*calc\(100%\s*\+\s*4px\);")

    def test_special_motion_and_canvas_gestures_have_bounded_lifecycles(self):
        html = read_text("desktop.html")
        canvas_sources = read_loaded_canvas_sources(self, html)
        canvas_js = canvas_sources["scripts/desktop-canvas.js"]
        image_group_interaction_js = canvas_sources["scripts/desktop-canvas-image-group-interaction.js"]
        connections_js = canvas_sources["scripts/desktop-canvas-connections.js"]
        port_interaction_js = canvas_sources["scripts/desktop-canvas-port-interaction.js"]
        preferences_js = read_text("scripts/desktop-preferences.js")
        prompt_drawer_js = read_text("scripts/desktop-prompt-drawer.js")
        performance_css = read_text("styles/desktop-performance.css")

        assert_asset_has_cache_bust(self, html, "styles/desktop-performance.css")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-preferences.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-prompt-drawer.js")
        self.assertLess(html.index("styles/desktop-motion.css"), html.index("styles/desktop-performance.css"))

        lifecycle_names = (
            "createImageGroupProximityPreview",
            "clearImageGroupProximity",
            "releaseImageGroupProximity",
            "beginImageGroupProximity",
            "updateImageGroupProximity",
            "commitImageGroupProximity",
        )
        for name in lifecycle_names:
            self.assertEqual(canvas_js.count(f"function {name}"), 1, name)
            self.assertEqual(image_group_interaction_js.count(f"function {name}"), 1, name)
            self.assertEqual(sum(
                source.count(f"function {name}")
                for path, source in canvas_sources.items()
                if path != "scripts/desktop-canvas.js"
            ), 1, name)
            shim_body = read_named_function(self, canvas_js, name)
            self.assertIn(f"return canvasImageGroupInteraction.{name}(", shim_body)
        for source in canvas_sources.values():
            self.assertNotIn("function createImageGroupPreviewChip", source)
        for source in canvas_sources.values():
            self.assertNotIn("function captureImageGroupProximitySources", source)
        self.assertIn("function startLiveImageGroupPreviewFrame", image_group_interaction_js)
        self.assertIn("if (preview.reducedMotion)", image_group_interaction_js)
        self.assertIn("startLiveImageGroupPreviewFrame(existing.preview);", image_group_interaction_js)

        preview_body = read_named_function(self, connections_js, "renderConnectionPreview")
        self.assertNotIn("updateLinkPath()", preview_body)
        self.assertIn("pendingConnectionPreview =", preview_body)
        self.assertIn("data-live-connection-preview", connections_js)
        self.assertIn("function flushConnectionPreviewFrame", connections_js)
        self.assertIn("pendingConnectionDropPoint = { x: event.clientX, y: event.clientY };", canvas_js)
        self.assertIn("function refreshContextMenuConnectionPreview", connections_js)
        self.assertIn("refreshContextMenuConnectionPreview();", canvas_js)
        self.assertIn("function renderImageGroupItemSortFrame", image_group_interaction_js)
        self.assertIn("if (imageGroupSortFrameId) return;", image_group_interaction_js)
        self.assertIn("const imageGroupSortCleanupTimers = new WeakMap();", image_group_interaction_js)
        self.assertIn("function renderReducedMotionFloatingSwells", port_interaction_js)

        self.assertIn("overlay.dataset.frozenTheme = previousTheme;", preferences_js)
        self.assertIn("function cancelThemeReveal", preferences_js)
        self.assertIn("window.cancelAnimationFrame(run.frameId)", preferences_js)
        self.assertIn("let promptGenieHandle = null;", prompt_drawer_js)
        self.assertIn("function stopPromptGenieAnimation", prompt_drawer_js)
        self.assertIn("promptGenieHandle?.cancel?.();", prompt_drawer_js)
        self.assertIn("const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;", prompt_drawer_js)

        self.assertRegex(performance_css, r"\.desk-canvas-world,[^}]*\.desk-node[^}]*will-change:\s*auto;")
        self.assertRegex(performance_css, r"\.is-wheel-transforming\) \.desk-canvas-world\s*\{[^}]*will-change:\s*transform;")
        self.assertRegex(performance_css, r"\.is-wheel-transforming\) \.desk-image-group__liquid,[^}]*filter:\s*none\s*!important;")
        self.assertRegex(performance_css, r"\.is-wheel-transforming\)[^}]*\.desk-image-group__thumb > img[^}]*box-shadow:\s*none\s*!important;")

    def test_desktop_geometry_keeps_agent_controls_and_input_layout_intact(self):
        html = read_text("desktop.html")
        liquid_css = read_legacy_css()
        prompt_css = read_text("styles/desktop-prompt-assistant.css")
        controls_css = read_text("styles/desktop-controls.css")
        geometry_css = read_text("styles/desktop-geometry.css")
        agent_js = read_text("scripts/desktop-prompt-agent.js")
        prompt_insert_js = read_text("scripts/desktop-prompt-insert.js")

        assert_asset_has_cache_bust(self, html, "styles/desktop-geometry.css")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-prompt-insert.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-prompt-agent.js")
        self.assertIn(
            'class="desk-prompt-mode-switch" data-mode="assistant"',
            html,
        )
        self.assertEqual(html.count('class="desk-prompt-mode-button'), 2)
        self.assertIn("if (modeSwitch) modeSwitch.dataset.mode = next;", agent_js)
        self.assertRegex(
            geometry_css,
            r"\.desk-prompt-chat__textwrap,\s*"
            r"body\.desk-app\[data-theme\] \.desk-prompt-chat__input \.desk-prompt-editor\s*\{"
            r"[^}]*height:\s*74px;"
            r"[^}]*min-height:\s*74px;"
            r"[^}]*max-height:\s*74px;",
        )
        self.assertNotRegex(
            geometry_css,
            r"body\.desk-app\[data-theme\] \.desk-prompt-editor\s*,",
        )
        self.assertIn(
            "#deskPromptChatInput, #deskAgentGoal, .desk-prompt-library textarea",
            prompt_insert_js,
        )
        self.assertIn("@ 引用图片或视频，# 选择配色，/ 插入提示词素材", html)

        self.assertGreaterEqual(prompt_css.count(":not(.desk-select-trigger)"), 6)
        self.assertIn(
            "button:not(.desk-prompt-drawer__handle):not(.desk-select-trigger):not(:disabled)",
            prompt_css,
        )
        self.assertIn(
            ".desk-agent-task-rail button.desk-agent-task-card:not(.desk-prompt-drawer__handle):not(.desk-select-trigger)",
            prompt_css,
        )
        self.assertRegex(
            controls_css,
            r'\.desk-agent-field \.desk-select-shell\[data-select-variant="default"\] '
            r'\.desk-select-trigger:hover:not\(:disabled\)\s*\{'
            r'[^}]*color:\s*var\(--desk-prompt-assistant-ink\);'
            r'[^}]*background:\s*var\(--desk-agent-field-background-strong\);',
        )
        self.assertIn(
            "grid-template-columns: minmax(104px, 116px) auto minmax(82px, auto);",
            geometry_css,
        )
        self.assertRegex(
            geometry_css,
            r'button\.desk-agent-command:not\(\.desk-prompt-drawer__handle\)\s*\{'
            r'[^}]*height:\s*var\(--desk-control-height-sm\);'
            r'[^}]*min-height:\s*var\(--desk-control-height-sm\);',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-compose > button\.desk-agent-command:not\(\.desk-prompt-drawer__handle\)\s*\{'
            r'[^}]*min-width:\s*82px;'
            r'[^}]*justify-self:\s*end;',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-field \.desk-select-trigger,[\s\S]*?\.desk-agent-toggle\s*\)'
            r'[\s\S]*?height:\s*var\(--desk-control-height-sm\);',
        )
        self.assertRegex(
            liquid_css,
            r'\.desk-agent-approval \.desk-agent-command\s*\{[^}]*width:\s*100%;',
        )
        self.assertIn(
            "grid-template-rows: 34px minmax(0, 1fr) var(--desk-agent-footer-height, 64px);",
            geometry_css,
        )
        self.assertIn('class="desk-agent-plan-body"', html)
        self.assertIn('class="desk-agent-plan-details"', html)
        plan_body_start = html.index('<div class="desk-agent-plan-body">')
        plan_details_start = html.index('<div class="desk-agent-plan-details">', plan_body_start)
        approval_start = html.index('<footer class="desk-agent-approval"', plan_details_start)
        self.assertLess(plan_details_start, html.index('id="deskAgentDecision"'))
        self.assertLess(html.index('id="deskAgentParams"'), approval_start)
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-plan-body\s*\{'
            r'[^}]*display:\s*grid;'
            r'[^}]*min-height:\s*0;'
            r'[^}]*grid-template-rows:\s*minmax\(0, 1fr\) auto;',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-plan-details\s*\{'
            r'[^}]*max-height:\s*190px;'
            r'[^}]*overflow:\s*auto;',
        )
        self.assertIn("@supports (grid-template-rows: subgrid)", geometry_css)
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-workbench\s*\{'
            r'[^}]*grid-template-rows:\s*34px minmax\(0, 1fr\) var\(--desk-agent-footer-height, 64px\);',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-pane\s*\{'
            r'[^}]*grid-row:\s*1 / -1;'
            r'[^}]*grid-template-rows:\s*subgrid;',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-agent-context > span\s*\{'
            r'[^}]*height:\s*20px;'
            r'[^}]*min-height:\s*20px;'
            r'[^}]*font-size:\s*var\(--desk-font-size-micro\);',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-prompt-drawer__header \.desk-agent-status\s*\{'
            r'[^}]*display:\s*inline-flex;'
            r'[^}]*box-sizing:\s*border-box;'
            r'[^}]*height:\s*var\(--desk-control-height-xs\);'
            r'[^}]*min-height:\s*var\(--desk-control-height-xs\);'
            r'[^}]*align-items:\s*center;'
            r'[^}]*padding-block:\s*0;'
            r'[^}]*margin-top:\s*0;'
            r'[^}]*line-height:\s*1;',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-prompt-drawer__header \.desk-agent-status > span\s*\{'
            r'[^}]*display:\s*inline-flex;'
            r'[^}]*height:\s*100%;'
            r'[^}]*align-items:\s*center;'
            r'[^}]*margin-top:\s*0;'
            r'[^}]*line-height:\s*1;',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-prompt-image-menu button:not\(\.desk-prompt-drawer__handle\)\s*\{'
            r'[^}]*position:\s*relative;'
            r'[^}]*box-sizing:\s*border-box;'
            r'[^}]*width:\s*60px;'
            r'[^}]*height:\s*60px;'
            r'[^}]*padding:\s*2px;'
            r'[^}]*overflow:\s*hidden;'
            r'[^}]*border-style:\s*dashed;',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-prompt-image-menu img\s*\{'
            r'[^}]*position:\s*absolute;'
            r'[^}]*display:\s*block;'
            r'[^}]*width:\s*calc\(100% - 4px\);'
            r'[^}]*height:\s*calc\(100% - 4px\);'
            r'[^}]*max-width:\s*100%;'
            r'[^}]*max-height:\s*100%;'
            r'[^}]*object-fit:\s*cover;'
            r'[^}]*object-position:\s*center;',
        )
        self.assertRegex(
            prompt_css,
            r'\.desk-prompt-image-menu button:not\(\.desk-prompt-drawer__handle\):not\(\.desk-select-trigger\):not\(:disabled\)\s*\{'
            r'[^}]*background:\s*var\(--desk-agent-image-menu-thumb-background\);'
            r'[^}]*border-color:\s*var\(--desk-agent-image-menu-thumb-border\);'
            r'[^}]*box-shadow:\s*none;',
        )
        self.assertNotIn(".desk-prompt-image-menu.desk-agent-image-menu", prompt_css)
        self.assertRegex(
            prompt_css,
            r'\.desk-prompt-mode-switch::before\s*\{'
            r'[^}]*background:\s*var\(--desk-agent-switch-thumb-background\);'
            r'[^}]*box-shadow:\s*var\(--desk-agent-switch-thumb-shadow\);',
        )
        self.assertRegex(
            controls_css,
            r'\.desk-prompt-mode-switch\[data-mode="agent"\]::before\s*\{'
            r'[^}]*transform:\s*translateX\(100%\);',
        )
        self.assertRegex(
            controls_css,
            r'\.desk-prompt-mode-switch::before\s*\{'
            r'[^}]*transform:\s*translateX\(0\);'
            r'[^}]*transition:\s*var\(--desk-agent-switch-thumb-transition\);',
        )
        self.assertRegex(
            geometry_css,
            r'\.desk-prompt-mode-switch::before\s*\{'
            r'[^}]*position:\s*absolute;'
            r'[^}]*box-sizing:\s*border-box;'
            r'[^}]*width:\s*calc\(50% - 2px\);'
            r'[^}]*pointer-events:\s*none;',
        )
        self.assertRegex(
            prompt_css,
            r'\.desk-prompt-mode-switch\[data-mode\] button\.is-active:not\(\.desk-prompt-drawer__handle\)'
            r':not\(:disabled\)\s*\{'
            r'[^}]*background:\s*transparent;'
            r'[^}]*box-shadow:\s*none;',
        )
        self.assertGreaterEqual(prompt_css.count(":not(.desk-prompt-mode-button)"), 4)
        self.assertRegex(
            geometry_css,
            r"\.desk-agent-task-card-slot\s*\{"
            r"[^}]*position:\s*relative;"
            r"[^}]*width:\s*152px;"
            r"[^}]*flex:\s*0 0 152px;"
            r"[^}]*scroll-snap-align:\s*start;",
        )
        self.assertRegex(
            geometry_css,
            r"body\.desk-app\[data-theme\] \.desk-prompt-drawer\.is-open button\.desk-agent-task-card__menu-toggle:not\(\.desk-prompt-drawer__handle\)\s*\{"
            r"[^}]*position:\s*absolute;"
            r"[^}]*width:\s*20px;"
            r"[^}]*transform:\s*translateY\(-50%\);",
        )

        self.assertRegex(
            geometry_css,
            r"button\.desk-agent-icon-btn:not\(\.desk-prompt-drawer__handle\)\s*\{"
            r"[^}]*width:\s*var\(--desk-control-height-xs\);"
            r"[^}]*min-width:\s*var\(--desk-control-height-xs\);"
            r"[^}]*height:\s*var\(--desk-control-height-xs\);"
            r"[^}]*min-height:\s*var\(--desk-control-height-xs\);"
            r"[^}]*padding:\s*0;",
        )
        self.assertRegex(
            geometry_css,
            r"button\.desk-agent-icon-btn \.desk-icon\s*\{[^}]*margin:\s*0;",
        )
        # Settings is a left drawer: a category column beside the scrolling content.
        self.assertRegex(
            geometry_css,
            r"\.desk-settings__layout\s*\{[^}]*grid-template-columns:\s*var\(--desk-settings-nav-width\) minmax\(0, 1fr\);",
        )

    def test_agent_multitask_workbench_keeps_tasks_associated_and_canvas_mutations_serial(self):
        html = read_text("desktop.html")
        agent_js = read_text("scripts/desktop-prompt-agent.js")
        tokens_css = read_text("styles/desktop-tokens.css")
        prompt_css = read_text("styles/desktop-prompt-assistant.css")
        geometry_css = read_text("styles/desktop-geometry.css")
        motion_css = read_text("styles/desktop-motion.css")
        desktop_api_js = read_text("scripts/desktop-api.js")
        agent_runtime_py = read_text("backend/agent_runtime.py")
        agent_store_py = read_text("backend/agent_store.py")
        server_py = read_text("backend/server.py")

        self.assertIn('id="deskAgentTaskRail"', html)
        self.assertIn('id="deskAgentTaskTrack" role="tablist"', html)
        self.assertIn('id="deskAgentTaskPrev"', html)
        self.assertIn('id="deskAgentTaskNext"', html)
        self.assertIn('id="deskAgentTaskAll"', html)
        self.assertIn('id="deskAgentTaskAllCount"', html)
        self.assertIn('id="deskAgentNewTask"', html)
        self.assertIn('id="deskAgentStage"', html)
        self.assertIn(
            'id="deskAgentTaskDrawer" role="dialog" aria-modal="false" '
            'aria-labelledby="deskAgentTaskDrawerTitle" aria-hidden="true"',
            html,
        )
        self.assertIn('aria-controls="deskAgentTaskDrawer"', html)
        self.assertIn('id="deskAgentTaskDrawerBackdrop"', html)
        self.assertIn('id="deskAgentTaskDrawerClose"', html)
        self.assertIn('id="deskAgentTaskSearch" type="search"', html)
        self.assertIn('id="deskAgentTaskFilters" role="group"', html)
        self.assertIn('data-agent-task-filter="archived"', html)
        self.assertIn('id="deskAgentTaskList" role="list"', html)
        self.assertIn('id="deskAgentTaskEmpty" hidden', html)
        self.assertIn('id="deskAgentTaskCardMenu" role="menu"', html)
        self.assertIn('id="deskAgentTaskCardShelve"', html)
        self.assertIn('id="deskAgentTaskCardDelete"', html)
        self.assertIn('id="deskAgentTaskDialog" role="dialog" aria-modal="true"', html)
        self.assertIn('id="deskAgentTaskNameInput" type="text"', html)
        for asset_path in (
            "styles/desktop-tokens.css",
            "styles/desktop-prompt-assistant.css",
            "styles/desktop-geometry.css",
            "styles/desktop-motion.css",
            "scripts/desktop-api.js",
            "scripts/desktop-prompt-agent.js",
        ):
            assert_asset_has_cache_bust(self, html, asset_path)

        for source_contract in (
            "const ACTIVE_TASK_KEY = 'desktop_prompt_agent_active_task_v2';",
            "const TASK_REGISTRY_KEY = 'desktop_prompt_agent_tasks_v2';",
            "const MAX_ACTIVE_TASKS = 24;",
            "const MAX_TASK_HISTORY = 100;",
            "const MAX_RAIL_TERMINAL_TASKS = 3;",
            "const RESTORE_HYDRATE_CONCURRENCY = 4;",
            "const TASK_POLL_DELAYS = Object.freeze({",
            "tasks: new Map(),",
            "taskDrawerOpen: false,",
            "taskSearch: '',",
            "taskFilter: 'all'",
            "function createDraftTask(options = {})",
            "function selectTask(taskKey, options = {})",
            "function explicitTaskClientIdFromRun(run = {})",
            "function railTasks()",
            "function filteredDrawerTasks()",
            "function taskFilterCounts()",
            "function canArchiveTask(task)",
            "function taskFocusDescriptor(root)",
            "function findTaskControl(root, descriptor)",
            "function taskNavigationSignature(task)",
            "function renderTaskDrawerList()",
            "function renderTaskDrawer()",
            "function scheduleTaskNavigationRender()",
            "function setTaskDrawerOpen(open, options = {})",
            "function scrollTaskRail(direction)",
            "function toggleTaskPinned(taskKey)",
            "function shelveTask(taskKey)",
            "function toggleTaskArchived(taskKey)",
            "function canDeleteTask(task)",
            "function openTaskCardMenu(taskKey, toggle)",
            "function openTaskDialog(mode, options = {})",
            "async function submitTaskDialog(event)",
            "async function deleteTask(taskKey)",
            "const ACTION_RECEIPT_STORE = 'action_receipts';",
            "function workflowFingerprint(snapshot = null)",
            "agent_task_id: selectedTask()?.clientTaskId || createClientTaskId(),",
            "const response = await window.DesktopApi.listAgentRuns({ limit: MAX_TASK_HISTORY });",
            "const run = await window.DesktopApi.getAgentRun(task.runId, {",
            "nextDelay = await processWaitingAction(task);",
            "function taskPollDelay(task)",
            "function rescheduleTaskPolls(options = {})",
            "async function settleWithConcurrency(items, limit, worker)",
            "async function resumeHydratedTask(task)",
            "await settleWithConcurrency(hydrateTargets, RESTORE_HYDRATE_CONCURRENCY, async item => {",
        ):
            self.assertIn(source_contract, agent_js)

        # Polling stays responsive for the selected running task, but inactive,
        # waiting and hidden-page tasks must not hammer the API or rebuild the
        # potentially 100-row history drawer on every response.
        for polling_contract in (
            "selectedRunning: 850,",
            "backgroundRunning: 5_000,",
            "selectedWaiting: 850,",
            "backgroundWaiting: 10_000,",
            "backgroundIdle: 15_000,",
            "hiddenSelectedRunning: 5_000,",
            "hiddenBackground: 30_000",
            "if (navigationChanged) scheduleTaskNavigationRender();",
            "if (navigationChanged) scheduleTaskRegistryPersist();",
        ):
            self.assertIn(polling_contract, agent_js)
        self.assertNotIn("await Promise.allSettled(hydrateTargets.map", agent_js)

        waiting_action_path = agent_js.split("async function processWaitingAction", 1)[1].split(
            "async function createPlan", 1
        )[0]
        self.assertIn("return 120;", waiting_action_path)
        self.assertIn("return 500;", waiting_action_path)
        self.assertNotIn("scheduleTaskPoll", waiting_action_path)

        poll_path = agent_js.split("async function pollTask", 1)[1].split(
            "async function pollRun", 1
        )[0]
        self.assertIn("let nextDelay = null;", poll_path)
        self.assertIn("nextDelay = await processWaitingAction(task);", poll_path)
        self.assertIn("scheduleTaskPoll(task, nextDelay);", poll_path)

        hydrate_path = agent_js.split("const hydrateTargets =", 1)[1].split(
            "restored = true;", 1
        )[0]
        self.assertIn("Number(right?.key === state.selectedTaskKey)", hydrate_path)
        self.assertIn("if (item.polling) return;", hydrate_path)
        self.assertIn("item.polling = true;", hydrate_path)
        self.assertIn("item.polling = false;", hydrate_path)
        self.assertIn("void resumeHydratedTask(item);", hydrate_path)
        self.assertNotIn("await processWaitingAction(item)", hydrate_path)

        # The rail has a small active-task limit, while persisted/history
        # hydration retains substantially more terminal tasks for the drawer.
        self.assertNotIn("const MAX_TASKS =", agent_js)
        self.assertIn("function retainedTaskRecordsForStorage()", agent_js)
        self.assertIn("function pruneTaskRegistry()", agent_js)
        self.assertIn("stored?.tasks) ? stored.tasks.slice(-MAX_TASK_HISTORY)", agent_js)
        self.assertIn("activeCount >= MAX_ACTIVE_TASKS", agent_js)
        self.assertIn("terminal.slice(0, MAX_RAIL_TERMINAL_TASKS)", agent_js)

        # Persistence reserves selected and all non-terminal work before pins
        # and newest history. Runtime pruning may only remove old unpinned
        # terminal records and must cancel their timers/snapshot references.
        retention_path = agent_js.split("function retainedTaskRecordsForStorage()", 1)[1].split(
            "function pruneTaskRegistry()", 1
        )[0]
        self.assertLess(retention_path.index("reserve(selected);"), retention_path.index("active.forEach(reserve);"))
        self.assertLess(retention_path.index("active.forEach(reserve);"), retention_path.index("pinned.forEach(reserve);"))
        self.assertLess(retention_path.index("pinned.forEach(reserve);"), retention_path.index("newest.forEach(reserve);"))
        self.assertIn("if (!task || task.archived) return false;", agent_js)
        prune_path = agent_js.split("function pruneTaskRegistry()", 1)[1].split(
            "function persistTaskRegistry()", 1
        )[0]
        self.assertIn("task.key === state.selectedTaskKey || task.pinned === true || isTaskNonTerminal(task)", prune_path)
        self.assertIn("task.archived || (", prune_path)
        self.assertIn("task.runId && TERMINAL_STATUSES.has(String(task.run?.status || ''))", prune_path)
        self.assertIn("window.clearTimeout(task.pollTimer);", prune_path)
        self.assertIn("task.pollTimer = 0;", prune_path)
        self.assertIn("state.snapshots.delete(task.runId);", prune_path)
        self.assertIn("state.tasks.delete(task.key);", prune_path)
        persist_path = agent_js.split("function persistTaskRegistry()", 1)[1].split(
            "function scheduleTaskRegistryPersist()", 1
        )[0]
        self.assertIn("const retainedRecords = retainedTaskRecordsForStorage();", persist_path)
        self.assertIn("const retainedKeys = new Set(retainedRecords.map(task => task.key));", persist_path)
        self.assertIn("retainedKeys.has(state.selectedTaskKey) ? selectedTask() : null", persist_path)

        # Names plus pin/archive/shelve metadata are local UI state keyed by the
        # stable task identity. Schema v5 must persist and restore it without changing the
        # Agent run itself.
        self.assertIn("name: task.name || '',", agent_js)
        self.assertIn("pinned: task.pinned === true,", agent_js)
        self.assertIn("archived: task.archived === true,", agent_js)
        self.assertIn("shelved: task.shelved === true,", agent_js)
        self.assertIn("JSON.stringify({ version: 5, tasks })", agent_js)
        self.assertIn("name: normalizeTaskName(record.name || ''),", agent_js)
        self.assertIn("pinned: record.pinned === true,", agent_js)
        self.assertIn("archived: record.archived === true,", agent_js)
        self.assertIn("shelved: record.shelved === true,", agent_js)
        self.assertIn("if (task.archived) task.pinned = false;", agent_js)
        self.assertIn("if (task.pinned) task.shelved = false;", agent_js)
        self.assertIn("task.shelved = false;", agent_js)
        self.assertIn("return TERMINAL_STATUSES.has(String(task.run?.status || ''));", agent_js)
        self.assertIn("event.stopPropagation();", agent_js)
        self.assertIn("if (event.key === 'Escape' && state.taskDrawerOpen)", agent_js)
        self.assertIn("if (!state.taskDrawerOpen) return;", agent_js)
        self.assertIn(
            "if (els.deskAgentTaskDrawer?.getAttribute('aria-hidden') !== 'false') return;",
            agent_js,
        )
        self.assertIn("els.deskAgentTaskSearch?.focus?.();", agent_js)
        self.assertIn("els.deskAgentTaskAll?.focus?.({ preventScroll: true });", agent_js)

        # Selecting an already visible task must not reorder the rail. Shelving
        # removes only the shortcut card; opening it from the drawer restores it.
        rail_path = agent_js.split("function railTasks()", 1)[1].split(
            "function taskMatchesFilter", 1
        )[0]
        self.assertIn("!task.archived && !task.shelved", rail_path)
        self.assertIn("return tasks.filter(task => visibleKeys.has(task.key));", rail_path)
        self.assertNotIn("[selected,", rail_path)
        self.assertIn('data-agent-task-menu="${escapeHtml(task.key)}"', agent_js)
        self.assertIn("const focusKey = shelveTask(taskKey);", agent_js)
        self.assertIn("data-agent-card-menu-action=\"delete\"", html)
        self.assertIn('data-agent-task-action="delete"', agent_js)
        self.assertIn("task.shelved = true;", agent_js)
        self.assertIn("· 已收纳", agent_js)
        self.assertIn("归档：移出常规任务，数据不会删除", agent_js)

        # A busy task or the active-task cap must reject a new draft before
        # `ensureTaskRecord` mutates the registry. The click handler also
        # respects that nullable result and suppresses double-click duplicates.
        create_draft_path = agent_js.split("function createDraftTask(options = {})", 1)[1].split(
            "function collectElements()", 1
        )[0]
        self.assertIn(
            "if (state.creating || state.controlling || state.revising) return null;",
            create_draft_path,
        )
        self.assertIn("if (activeCount >= MAX_ACTIVE_TASKS) return null;", create_draft_path)
        self.assertLess(
            create_draft_path.index("if (activeCount >= MAX_ACTIVE_TASKS) return null;"),
            create_draft_path.index("const task = ensureTaskRecord({"),
        )
        self.assertIn("if (state.draftCreationLocked || Number(event.detail || 0) > 1) return;", agent_js)
        self.assertIn("openTaskDialog('create', { returnFocus: els.deskAgentNewTask });", agent_js)
        self.assertIn("const created = createDraftTask({ name, reuseEmpty: false, select: true });", agent_js)
        self.assertIn("agent_task_name: taskIdentity(),", agent_js)
        self.assertIn("await window.DesktopApi.deleteAgentRun(task.runId);", agent_js)
        self.assertIn("await deletePersistedTaskData(task.runId);", agent_js)
        self.assertIn("els.deskAgentTaskNameInput.required = namingTask;", agent_js)
        self.assertIn("els.deskAgentTaskNameInput.disabled = !namingTask;", agent_js)
        self.assertIn("function deleteAgentRun(runId)", desktop_api_js)
        self.assertIn("method: 'DELETE'", desktop_api_js)
        self.assertIn("def delete_run(run_id: str) -> bool:", agent_store_py)
        self.assertIn("def delete_run(self, run_id: str) -> dict[str, Any]:", agent_runtime_py)
        self.assertIn("运行中的任务需先取消或等待完成后再删除", agent_runtime_py)
        self.assertIn("def handle_agent_run_delete(self, parsed):", server_py)
        self.assertIn("get_agent_runtime().delete_run(parts[3])", server_py)

        # Re-rendering either the rail or drawer must not drop keyboard focus.
        self.assertIn("const focus = taskFocusDescriptor(els.deskAgentTaskList);", agent_js)
        self.assertIn("const focus = taskFocusDescriptor(els.deskAgentTaskTrack);", agent_js)
        self.assertIn("const target = findTaskControl(els.deskAgentTaskList, focus)", agent_js)
        self.assertIn("const target = findTaskControl(els.deskAgentTaskTrack, focus)", agent_js)
        self.assertIn("target?.focus?.({ preventScroll: true });", agent_js)
        self.assertIn("(taskCard || els.deskAgentTaskAll)?.focus?.({ preventScroll: true });", agent_js)

        # Archived tasks must be restored before they can replace the current
        # workspace. A rejected switch leaves the drawer open instead of
        # falsely implying that the requested task was selected.
        self.assertIn(
            "${task.archived ? ' disabled aria-disabled=\"true\" title=\"先恢复归档后再打开\"' : (task.shelved ? ' title=\"打开并放回顶部任务轨\"' : '')}",
            agent_js,
        )
        self.assertIn(
            "if (task.archived && options.allowArchived !== true) return selectedTask();",
            agent_js,
        )
        self.assertIn("const selected = selectTask(requestedKey);", agent_js)
        self.assertIn("if (selected?.key === requestedKey) {", agent_js)
        self.assertIn("setTaskDrawerOpen(false, { focusTaskKey: requestedKey });", agent_js)

        self.assertIn("const CANVAS_MUTATION_ACTIONS = new Set([", agent_js)
        self.assertIn("canvasMutationTail: Promise.resolve(),", agent_js)
        self.assertIn("const queued = state.canvasMutationTail.catch(() => undefined).then(async () => {", agent_js)
        self.assertIn("state.canvasMutationTail = queued.then(() => undefined, () => undefined);", agent_js)
        self.assertIn("return await executeClientAction(action, { runId: task.runId, task });", agent_js)
        self.assertIn("await loadPersistedActionReceipt(task.runId, actionId);", agent_js)
        self.assertIn("await storePersistedActionReceipt(task.runId, actionId, {", agent_js)
        self.assertIn("await deletePersistedActionReceipt(task.runId, actionId);", agent_js)
        self.assertIn("currentFingerprint !== task.canvasFingerprint", agent_js)
        self.assertIn("本次整画布回滚已阻止", agent_js)
        self.assertIn("已阻止旧任务覆盖整张画布", agent_js)
        self.assertIn("state.restoreRetryTimer = window.setTimeout(restoreActiveRun, retryDelay);", agent_js)
        self.assertIn("window.addEventListener('pagehide'", agent_js)

        # Historical runs without the new client field must not overwrite a
        # locally persisted logical task identity during hydration.
        self.assertIn("const payloadClientTaskId = explicitTaskClientIdFromRun(payload);", agent_js)
        self.assertIn("if (payloadClientTaskId || !target.clientTaskId)", agent_js)
        self.assertIn("if (clientTaskId || !task.clientTaskId)", agent_js)
        self.assertIn("item?.clientTaskId === clientTaskId && !item.runId", agent_js)
        self.assertIn("def find_run_by_client_task_id(client_task_id: str)", agent_store_py)
        self.assertIn("existing = agent_store.find_run_by_client_task_id(client_task_id)", agent_runtime_py)
        self.assertIn('return self.get_run(existing["run_id"])', agent_runtime_py)

        self.assertRegex(
            geometry_css,
            r"\.desk-prompt-drawer\.is-agent \.desk-prompt-drawer__body\s*\{"
            r"[^}]*grid-template-rows:\s*34px 46px minmax\(0, 1fr\);",
        )
        self.assertRegex(
            geometry_css,
            r"\.desk-agent-task-navigator\s*\{"
            r"[^}]*grid-template-columns:\s*var\(--desk-control-height-xs\) "
            r"minmax\(0, 1fr\) var\(--desk-control-height-xs\);",
        )
        self.assertRegex(
            geometry_css,
            r"\.desk-agent-task-track\s*\{"
            r"[^}]*display:\s*flex;"
            r"[^}]*overflow-x:\s*auto;"
            r"[^}]*overflow-y:\s*hidden;"
            r"[^}]*scroll-snap-type:\s*inline proximity;",
        )
        self.assertRegex(
            geometry_css,
            r"\.desk-agent-stage\s*\{"
            r"[^}]*position:\s*relative;"
            r"[^}]*overflow:\s*hidden;"
            r"[^}]*isolation:\s*isolate;",
        )
        self.assertRegex(
            geometry_css,
            r"\.desk-agent-task-drawer\s*\{"
            r"[^}]*position:\s*absolute;"
            r"[^}]*right:\s*var\(--desk-space-2\);"
            r"[^}]*bottom:\s*var\(--desk-space-2\);"
            r"[^}]*width:\s*clamp\(360px, 38%, 430px\);"
            r"[^}]*max-width:\s*calc\(100% - var\(--desk-space-2\) - "
            r"var\(--desk-space-2\)\);"
            r"[^}]*overflow:\s*hidden;",
        )
        self.assertRegex(
            geometry_css,
            r"\.desk-agent-task-filters\s*\{"
            r"[^}]*display:\s*flex;"
            r"[^}]*flex-wrap:\s*wrap;"
            r"[^}]*overflow:\s*visible;",
        )
        medium_agent_layout = geometry_css[
            geometry_css.index("@media (max-width: 860px)"):
            geometry_css.index("@media (max-width: 760px)")
        ]
        self.assertNotRegex(
            medium_agent_layout,
            r"\.desk-agent-task-nav\s*\{[^}]*display:\s*none",
        )
        self.assertRegex(
            geometry_css,
            r"@media \(max-width: 760px\)\s*\{[\s\S]*?"
            r"\.desk-agent-task-nav\s*\{[^}]*display:\s*none\s*!important;",
        )
        self.assertRegex(
            geometry_css,
            r":is\(\.desk-agent-compose, \.desk-agent-approval, \.desk-agent-artifact\)\s*\{"
            r"[^}]*height:\s*var\(--desk-agent-footer-height\);"
            r"[^}]*min-height:\s*var\(--desk-agent-footer-height\);"
            r"[^}]*max-height:\s*var\(--desk-agent-footer-height\);",
        )

        for token in (
            "--desk-agent-task-running-background:",
            "--desk-agent-task-draft-background:",
            "--desk-agent-task-waiting-background:",
            "--desk-agent-task-card-selected-border:",
            "--desk-agent-task-drawer-background:",
            "--desk-agent-task-drawer-border:",
            "--desk-agent-task-drawer-row-selected-background:",
        ):
            self.assertEqual(tokens_css.count(token), 2, token)
        for tone in ("running", "draft", "waiting"):
            self.assertIn(f'data-task-tone="{tone}"', prompt_css)
        self.assertIn("background-position: var(--desk-agent-task-card-material-position-hover);", prompt_css)
        self.assertIn(
            ":not(:disabled):not(.desk-agent-task-card):not(.desk-agent-task-secondary):not(.desk-prompt-mode-button):hover",
            prompt_css,
        )
        self.assertIn("background: var(--desk-agent-task-drawer-background);", prompt_css)
        self.assertIn("background: var(--desk-agent-task-drawer-row-selected-background);", prompt_css)
        self.assertRegex(
            motion_css,
            r"\.desk-agent-task-drawer\.is-open\s*\{"
            r"[^}]*visibility:\s*visible;"
            r"[^}]*pointer-events:\s*auto;"
            r"[^}]*opacity:\s*1;"
            r"[^}]*transform:\s*translate3d\(0, 0, 0\) scale\(1\);",
        )
        self.assertRegex(
            motion_css,
            r"@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?"
            r"\.desk-agent-task-drawer,[\s\S]*?"
            r"\.desk-agent-task-drawer-backdrop[\s\S]*?"
            r"transition-duration:\s*0\.01ms;",
        )

    def test_desktop_light_theme_uses_powder_to_ink_blue_scale(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        light_css, dark_css = tokens_css.split('body.desk-app[data-theme="dark"]', 1)

        for declaration in (
            "--desk-blue-powder: #c8d7e9;",
            "--desk-blue-baby: #afcbe7;",
            "--desk-blue-periwinkle: #7aa3dc;",
            "--desk-blue-cornflower: #6691ce;",
            "--desk-blue-denim: #2e599b;",
            "--desk-blue-royal: #1454a0;",
            "--desk-blue-navy: #173b70;",
            "--desk-blue-midnight: #102950;",
            "--desk-blue-ink: #0c1b34;",
            "--desk-color-bg-app: var(--desk-blue-mist);",
            "--desk-color-text-primary: var(--desk-blue-ink);",
            "--desk-color-accent: var(--desk-blue-royal);",
            "--desk-shell-rail-marker-open-background: var(--desk-blue-cornflower);",
        ):
            self.assertIn(declaration, light_css)

        self.assertNotIn("#084fbd", light_css)
        self.assertNotIn("rgba(8, 79, 189,", light_css)
        self.assertIn("--desk-color-accent: #ff5a1f;", dark_css)
        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")

    def test_desktop_primary_commands_use_scoped_satin_material(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        controls_css = read_text("styles/desktop-controls.css")
        prompt_css = read_text("styles/desktop-prompt-assistant.css")
        motion_css = read_text("styles/desktop-motion.css")

        for declaration in (
            "--desk-action-primary-top: #244f87;",
            "--desk-action-primary-bottom: var(--desk-blue-navy);",
            "--desk-action-primary-hover-top: #2b5c99;",
            "--desk-action-primary-active-bottom: var(--desk-blue-midnight);",
            "--desk-action-primary-silk-lustre:",
            "--desk-action-primary-silk-fold:",
            "--desk-action-primary-silk-lowlight:",
            "--desk-action-primary-edge-lowlight:",
            "--desk-action-primary-edge-lowlight-hover:",
            "--desk-action-primary-silk-background-size:",
            "--desk-action-primary-silk-position:",
            "--desk-action-primary-silk-position-hover:",
            "--desk-action-primary-silk-position-active:",
            "--desk-action-primary-gloss-active:",
            "--desk-motion-material-transition:",
        ):
            self.assertIn(declaration, tokens_css)

        self.assertIn("radial-gradient(ellipse 74% 82%", tokens_css)
        self.assertIn("linear-gradient(116deg", tokens_css)
        self.assertIn("--desk-prompt-assistant-button-background: var(--desk-action-primary-gloss);", tokens_css)
        self.assertIn("--desk-agent-provider-active-background: var(--desk-action-primary-gloss);", tokens_css)
        self.assertIn("background-image: var(--desk-action-primary-gloss-hover);", controls_css)
        self.assertIn("background-image: var(--desk-action-primary-gloss-active);", controls_css)
        self.assertIn("background-position: var(--desk-action-primary-silk-position-hover);", controls_css)
        self.assertIn("inset 0 -1px 0 var(--desk-action-primary-edge-lowlight)", controls_css)
        self.assertIn("var(--desk-motion-material-transition);", controls_css)
        self.assertIn(
            "background-image: var(--desk-prompt-assistant-button-hover-background);",
            prompt_css,
        )
        self.assertIn(
            "background-size: var(--desk-prompt-assistant-material-background-size);",
            prompt_css,
        )
        self.assertIn("var(--desk-motion-material-transition);", motion_css)
        self.assertRegex(
            controls_css,
            r"\.desk-button--generate:disabled,[\s\S]*?"
            r"background:\s*var\(--desk-action-primary-gradient-disabled\);[\s\S]*?"
            r"background-size:\s*100% 100%;",
        )
        self.assertNotRegex(tokens_css, r"@keyframes\s+desk-(?:silk|satin)")
        for asset_path in (
            "styles/desktop-tokens.css",
            "styles/desktop-controls.css",
            "styles/desktop-prompt-assistant.css",
            "styles/desktop-motion.css",
        ):
            assert_asset_has_cache_bust(self, html, asset_path)

    def test_desktop_semantic_statuses_use_shared_silk_palette(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        shell_css = read_text("styles/desktop-shell.css")
        controls_css = read_text("styles/desktop-controls.css")
        prompt_css = read_text("styles/desktop-prompt-assistant.css")
        library_css = read_text("styles/desktop-prompt-library.css")

        for declaration in (
            "--desk-status-success-top: #207f55;",
            "--desk-status-success-bottom: #0d5b39;",
            "--desk-status-warning-top: #ffad52;",
            "--desk-status-warning-bottom: #e46b0b;",
            "--desk-status-error-top: #cd3b6a;",
            "--desk-status-error-bottom: #951642;",
            "--desk-status-success-silk-background:",
            "--desk-status-warning-silk-background:",
            "--desk-status-error-silk-background:",
            "--desk-status-success-soft-background:",
            "--desk-status-warning-soft-background:",
            "--desk-status-error-soft-background:",
            "--desk-status-material-position-hover:",
            "--desk-status-material-position-active:",
        ):
            self.assertIn(declaration, tokens_css)

        for alias in (
            "--desk-agent-running-background: var(--desk-status-success-soft-background);",
            "--desk-agent-waiting-background: var(--desk-status-warning-soft-background);",
            "--desk-agent-failure-background: var(--desk-status-error-soft-background);",
            "--desk-settings-summary-ok-background: var(--desk-status-success-soft-background);",
            "--desk-settings-summary-warn-background: var(--desk-status-warning-silk-background);",
            "--desk-settings-pool-error-background: var(--desk-status-error-soft-background);",
            "--desk-video-online-background: var(--desk-status-success-silk-background);",
            "--desk-video-offline-background: var(--desk-status-warning-silk-background);",
        ):
            self.assertEqual(tokens_css.count(alias), 2, alias)

        self.assertIn("background-size: var(--desk-status-material-background-size);", shell_css)
        self.assertIn("background-position: var(--desk-status-material-position-hover);", shell_css)
        self.assertIn("var(--desk-motion-material-transition);", shell_css)
        self.assertIn("background-image: var(--desk-status-stop-hover-background);", shell_css)
        self.assertIn('.desk-status-group--feedback :is(span, .desk-status-feedback-trigger)', shell_css)
        self.assertIn(".desk-status-pill.is-success", controls_css)
        self.assertIn(".desk-status-pill.is-warning", controls_css)
        self.assertIn(".desk-status-pill.is-error", controls_css)
        self.assertIn("background-image: var(--desk-status-error-silk-background);", controls_css)
        self.assertIn("background: var(--desk-agent-failure-background);", prompt_css)
        self.assertIn("background: var(--desk-status-error-soft-background);", library_css)
        self.assertIn(
            'body.desk-app[data-theme="dark"] .desk-prompt-color-analysis__status.is-success',
            library_css,
        )
        self.assertNotIn("#b52c39", library_css)

        for asset_path in (
            "styles/desktop-tokens.css",
            "styles/desktop-file-results.css",
            "styles/desktop-prompt-library.css",
            "styles/desktop-shell.css",
            "styles/desktop-prompt-assistant.css",
            "styles/desktop-controls.css",
        ):
            assert_asset_has_cache_bust(self, html, asset_path)

    def test_desktop_phase7_removes_confirmed_dead_style_families(self):
        html = read_text("desktop.html")
        touched_styles = (
            "styles/desktop-liquid.css",
            "styles/desktop-prompt-library.css",
            "styles/desktop-controls.css",
            "styles/desktop-geometry.css",
            "styles/desktop-settings-auth.css",
            "styles/desktop-gallery.css",
        )
        css = "\n".join(read_text(path) for path in touched_styles)

        for asset_path in touched_styles:
            assert_asset_has_cache_bust(self, html, asset_path)

        for dead_selector in (
            ".desk-result-grid",
            ".desk-settings-auth-file",
            ".desk-gallery-video-detail__header",
            ".desk-prompt-module",
            ".desk-prompt-variant-tabs",
        ):
            self.assertNotIn(dead_selector, css)

    def test_desktop_phase7_uses_normal_cascade_and_named_top_level_layers(self):
        html = read_text("desktop.html")
        liquid_css = read_legacy_css()
        prompt_css = read_text("styles/desktop-prompt-library.css")
        controls_css = read_text("styles/desktop-controls.css")
        geometry_css = read_text("styles/desktop-geometry.css")
        creation_tools_css = read_text("styles/desktop-creation-tools.css")
        layout_css = read_text("styles/desktop-layout.css")
        pose_css = read_text("styles/desktop-pose.css")

        # Resource versions may advance independently of the layer contract.
        for asset_path in (
            "styles/desktop-tokens.css",
            "styles/desktop-liquid.css",
            "styles/desktop-layout.css",
            "styles/desktop-pose.css",
            "styles/desktop-prompt-library.css",
            "styles/desktop-canvas-nodes.css",
            "styles/desktop-creation-tools.css",
            "styles/desktop-controls.css",
            "styles/desktop-geometry.css",
        ):
            assert_asset_has_cache_bust(self, html, asset_path)

        self.assertNotIn("!important", controls_css)
        important_lines = [line.strip() for line in prompt_css.splitlines() if "!important" in line]
        # The petal picker's reduced-motion transition override moved to desktop-color-bloom.css.
        self.assertEqual(len(important_lines), 1)
        self.assertTrue(all("none !important" in line for line in important_lines))
        self.assertIn(".desk-prompt-library :where(", prompt_css)
        self.assertNotRegex(
            prompt_css,
            r"\.desk-prompt-library__header-actions button,\s*\n"
            r"\.desk-prompt-library__toolbar button,[\s\S]*?\)\s*\{",
        )

        self.assertNotIn(".desk-manual-send:disabled", liquid_css)
        self.assertIn(":not(.desk-manual-send):disabled", controls_css)
        self.assertNotRegex(
            liquid_css,
            r"(?ms)body\.desk-app\[data-theme=\"dark\"\] "
            r"\.desk-gallery-inspector__actions \.desk-button:disabled,[^}]*!important",
        )
        pose_important_lines = [line.strip() for line in pose_css.splitlines() if "!important" in line]
        self.assertEqual(
            pose_important_lines,
            ["cursor: ns-resize !important;", "user-select: none !important;"],
        )
        self.assertRegex(
            creation_tools_css,
            r"\.desk-pose-studio__bar-actions \.desk-pose-studio__close\s*\{"
            r"[^}]*color:\s*var\(--desk-pose-close-ink\);",
        )
        self.assertRegex(
            geometry_css,
            r"\.desk-pose-studio__bar-actions \.desk-pose-studio__close\s*\{"
            r"[^}]*font-size:\s*18px;",
        )

        legacy_top_level_selectors = {
            liquid_css: (
                "body.desk-app.theme-is-transitioning::before",
                ".desk-theme-reveal-overlay",
                ".desk-titlebar",
                ".desk-release__panel",
                ".desk-rail",
                ".desk-node-palette",
                ".desk-node-context-menu",
                ".desk-selection-toolbar",
                ".desk-zoom-controls",
                ".desk-image-editor",
                ".desk-image-group-dwell",
                ".desk-image-group-transition",
                ".desk-history",
                ".desk-gallery",
                ".desk-settings",
                ".desk-text-polish-modal",
                ".desk-text-copy-fallback",
                ".desk-file-preview-modal",
                ".desk-gallery-preview",
                ".desk-compare",
                ".desk-bottombar",
                ".desk-prompt-drawer",
                ".desk-prompt-modal",
                ".auth-overlay",
                ".desk-status-tip",
                ".desk-pinterest-split-modal",
                ".desk-pinterest-analysis-modal",
                ".desk-edge-menu",
            ),
            prompt_css: (".desk-prompt-library", ".desk-prompt-slash-menu"),
            layout_css: (".desk-layout-editor",),
            pose_css: (".desk-pose-studio",),
        }
        for stylesheet, selectors in legacy_top_level_selectors.items():
            for selector in selectors:
                self.assertNotRegex(
                    stylesheet,
                    rf"(?ms)^{re.escape(selector)}\s*\{{[^}}]*\bz-index\s*:",
                )

        for token in (
            "--desk-layer-node",
            "--desk-layer-chrome",
            "--desk-layer-workspace",
            "--desk-layer-panel",
            "--desk-layer-popover",
            "--desk-layer-tooltip",
            "--desk-layer-drawer",
            "--desk-layer-canvas-menu",
            "--desk-layer-modal",
            "--desk-layer-interaction",
            "--desk-layer-interaction-indicator",
            "--desk-layer-theme-reveal",
        ):
            self.assertIn(f"z-index: var({token});", geometry_css)

        self.assertRegex(
            geometry_css,
            r"\.desk-pinterest-analysis-modal,\s*"
            r"\.desk-pinterest-split-modal\s*\)\s*\{\s*"
            r"z-index:\s*var\(--desk-layer-panel-dialog\);",
        )
        self.assertIn("z-index: var(--desk-layer-menu);", liquid_css)

    def test_desktop_panels_restore_focus_before_becoming_aria_hidden(self):
        html = read_text("desktop.html")
        cases = (
            (
                "scripts/desktop-history.js",
                "function closeGallery()",
                "\n  function normalizeCompareValue",
                "els.deskGalleryPanel?.contains(activeElement)",
                '.desk-rail__item[data-tool="gallery"]',
                "els.deskGalleryPanel?.setAttribute('aria-hidden', 'true')",
            ),
            (
                "scripts/desktop-prompt-library.js",
                "async function open()",
                "\n  function bindEvents()",
                "els.deskPromptLibraryPanel?.contains(activeElement)",
                '.desk-rail__item[data-tool="prompts"]',
                "els.deskPromptLibraryPanel?.setAttribute('aria-hidden', 'true')",
            ),
            (
                "scripts/desktop-settings.js",
                "async function open()",
                "\n  function updateTabs()",
                "els.deskSettingsPanel?.contains(activeElement)",
                '.desk-rail__item[data-tool="settings"]',
                "els.deskSettingsPanel?.setAttribute('aria-hidden', 'true')",
            ),
        )

        for asset_path, start_marker, end_marker, contains_marker, trigger_marker, hidden_marker in cases:
            script = read_text(asset_path)
            start = script.index(start_marker)
            end = script.index(end_marker, start)
            close_path = script[start:end]
            self.assertIn(contains_marker, close_path)
            self.assertIn(trigger_marker, close_path)
            self.assertIn("trigger.focus({ preventScroll: true })", close_path)
            self.assertLess(close_path.index("trigger.focus({ preventScroll: true })"), close_path.index(hidden_marker))
            assert_asset_has_cache_bust(self, html, asset_path)

    def test_desktop_shell_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        shell_css = read_text("styles/desktop-shell.css")

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-shell.css")
        self.assertLess(html.index("styles/desktop-prompt-library.css"), html.index("styles/desktop-shell.css"))
        self.assertLess(html.index("styles/desktop-shell.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-shell.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-shell.css"), html.index("styles/desktop-motion.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', shell_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', shell_css)
        self.assertNotIn('body.desk-app:not([data-theme', shell_css)
        self.assertNotRegex(shell_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", shell_css)
        self.assertIn("body.desk-app[data-theme] .desk-titlebar", shell_css)
        self.assertIn("background: var(--desk-shell-titlebar-band-background);", shell_css)
        self.assertIn("body.desk-app[data-theme] .desk-rail", shell_css)
        self.assertIn("background: var(--desk-shell-rail-background);", shell_css)
        self.assertIn("body.desk-app[data-theme] .desk-bottombar", shell_css)
        self.assertIn("background: var(--desk-shell-bottombar-background);", shell_css)
        self.assertIn("body.desk-app[data-theme] #deskStatusTip", shell_css)
        self.assertNotRegex(shell_css, r"body\.desk-app\[data-theme\]\s+\.desk-status-tip\s*\{")
        self.assertIn('.desk-theme-toggle[data-theme="dark"] .desk-theme-toggle__icon--moon', shell_css)

        referenced_tokens = set(re.findall(r"var\((--desk-[\w-]+)", shell_css))
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", f"{tokens_css}\n{shell_css}"))
        self.assertFalse(referenced_tokens - declared_tokens, sorted(referenced_tokens - declared_tokens))
        for token in (
            "--desk-shell-app-background",
            "--desk-shell-titlebar-band-background",
            "--desk-shell-rail-background",
            "--desk-shell-bottombar-background",
            "--desk-theme-track-background",
            "--desk-status-chip-background",
            "--desk-status-tip-background",
        ):
            self.assertEqual(tokens_css.count(f"{token}:"), 2, token)

    def test_desktop_canvas_node_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        canvas_css = read_text("styles/desktop-canvas-nodes.css")

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-canvas-nodes.css")
        self.assertLess(html.index("styles/desktop-liquid.css"), html.index("styles/desktop-canvas-nodes.css"))
        self.assertLess(html.index("styles/desktop-shell.css"), html.index("styles/desktop-canvas-nodes.css"))
        self.assertLess(html.index("styles/desktop-canvas-nodes.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-canvas-nodes.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-canvas-nodes.css"), html.index("styles/desktop-motion.css"))
        self.assertLess(html.index("styles/desktop-canvas-nodes.css"), html.index("styles/desktop-performance.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', canvas_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', canvas_css)
        self.assertNotIn('body.desk-app:not([data-theme', canvas_css)
        self.assertNotRegex(canvas_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", canvas_css)
        self.assertNotRegex(canvas_css, r"(?m)^\.desk-")

        self.assertIn("body.desk-app[data-theme] .desk-canvas", canvas_css)
        self.assertIn("background-image: var(--desk-canvas-surface-background-image);", canvas_css)
        self.assertIn("body.desk-app[data-theme] .desk-node-palette:not(.desk-node-context-menu)", canvas_css)
        self.assertIn("body.desk-app[data-theme] .desk-minimap", canvas_css)
        self.assertIn("body.desk-app[data-theme] .desk-node-context-menu", canvas_css)
        self.assertIn("body.desk-app[data-theme] .desk-edge-menu", canvas_css)
        self.assertIn(".desk-node.desk-glass:not(.desk-node--image-group)", canvas_css)
        self.assertIn(".desk-node:not(.desk-node--image-group).is-connection-drop-target", canvas_css)
        self.assertNotRegex(
            canvas_css,
            r"body\.desk-app\[data-theme\]\s+\.desk-node--image-group(?:\s|[>{+~])",
        )

        referenced_tokens = set(re.findall(r"var\((--desk-[\w-]+)", canvas_css))
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", f"{tokens_css}\n{canvas_css}"))
        self.assertFalse(referenced_tokens - declared_tokens, sorted(referenced_tokens - declared_tokens))
        for token in (
            "--desk-canvas-surface-background-image",
            "--desk-canvas-palette-background",
            "--desk-canvas-selection-stroke",
            "--desk-canvas-zoom-background",
            "--desk-canvas-menu-background",
            "--desk-node-glass-background",
            "--desk-node-text-background",
            "--desk-node-image-placeholder-background",
            "--desk-node-manual-send-disabled-ink",
            "--desk-node-manual-send-disabled-background",
            "--desk-node-manual-send-disabled-border",
            "--desk-node-manual-send-disabled-shadow",
        ):
            self.assertEqual(tokens_css.count(f"{token}:"), 2, token)

    def test_desktop_image_group_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        image_group_css = read_text("styles/desktop-image-group.css")
        image_group_css_without_comments = re.sub(r"/\*.*?\*/", "", image_group_css, flags=re.S)

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-image-group.css")
        self.assertLess(html.index("styles/desktop-canvas-nodes.css"), html.index("styles/desktop-image-group.css"))
        self.assertLess(html.index("styles/desktop-image-group.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-image-group.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-image-group.css"), html.index("styles/desktop-motion.css"))
        self.assertLess(html.index("styles/desktop-image-group.css"), html.index("styles/desktop-performance.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', image_group_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', image_group_css)
        self.assertNotIn('body.desk-app:not([data-theme', image_group_css)
        self.assertNotRegex(image_group_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", image_group_css)
        self.assertNotRegex(image_group_css, r"(?m)^\.desk-")

        self.assertIn("body.desk-app[data-theme] .desk-node--image-group", image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group__silhouette", image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group__thumb img", image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group__item-actions", image_group_css)
        self.assertIn('.desk-select-menu[data-select-variant="image-group-role"]', image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group__node-actions", image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group-dwell", image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group-transition__goo span", image_group_css)
        self.assertIn("body.desk-app[data-theme] .desk-image-group-transition__chip.is-incoming img", image_group_css)

        referenced_tokens = set(re.findall(r"var\((--desk-[\w-]+)", image_group_css))
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", tokens_css))
        local_tokens = {"--desk-image-group-chip-unit"}
        self.assertFalse(
            referenced_tokens - declared_tokens - local_tokens,
            sorted(referenced_tokens - declared_tokens - local_tokens),
        )
        for token in sorted(referenced_tokens - local_tokens):
            self.assertTrue(token.startswith("--desk-image-group-"), token)
            self.assertEqual(tokens_css.count(f"{token}:"), 2, token)

        self.assertNotIn("@keyframes", image_group_css_without_comments)
        self.assertNotRegex(image_group_css_without_comments, r"(?m)^\s*(?:transition|animation)(?:-[\w-]+)?\s*:")
        self.assertNotRegex(image_group_css_without_comments, r"--desk-image-group-(?:ui-scale|mother-radius)\s*:")

    def test_desktop_prompt_assistant_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        controls_css = read_text("styles/desktop-controls.css")
        prompt_css = read_text("styles/desktop-prompt-assistant.css")
        prompt_css_without_comments = re.sub(r"/\*.*?\*/", "", prompt_css, flags=re.S)

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-prompt-assistant.css")
        self.assertLess(html.index("styles/desktop-image-group.css"), html.index("styles/desktop-prompt-assistant.css"))
        self.assertLess(html.index("styles/desktop-prompt-assistant.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-prompt-assistant.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-prompt-assistant.css"), html.index("styles/desktop-motion.css"))
        self.assertLess(html.index("styles/desktop-prompt-assistant.css"), html.index("styles/desktop-performance.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', prompt_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', prompt_css)
        self.assertNotIn('body.desk-app:not([data-theme', prompt_css)
        self.assertNotRegex(prompt_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", prompt_css)
        self.assertNotRegex(prompt_css, r"(?m)^\.desk-")

        for selector in (
            "body.desk-app[data-theme] .desk-prompt-drawer__handle",
            "body.desk-app[data-theme] .desk-prompt-drawer__body::before",
            "body.desk-app[data-theme] .desk-prompt-drawer.is-open .desk-prompt-editor",
            'body.desk-app[data-theme] .desk-select-menu[data-select-variant="prompt"]',
            "body.desk-app[data-theme] .desk-prompt-modal__panel",
            "body.desk-app[data-theme] .desk-prompt-mode-switch",
            "body.desk-app[data-theme] .desk-prompt-task-mode",
            "body.desk-app[data-theme] .desk-agent-status",
            "body.desk-app[data-theme] .desk-agent-workbench",
            "body.desk-app[data-theme] .desk-agent-decision",
            "body.desk-app[data-theme] .desk-agent-params",
        ):
            self.assertIn(selector, prompt_css)

        referenced_tokens = set(re.findall(r"var\((--desk-[\w-]+)", prompt_css))
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", tokens_css))
        self.assertFalse(referenced_tokens - declared_tokens, sorted(referenced_tokens - declared_tokens))
        for token in sorted(referenced_tokens):
            self.assertTrue(
                token.startswith((
                    "--desk-prompt-assistant-",
                    "--desk-agent-",
                    "--desk-color-",
                    "--desk-status-",
                )),
                token,
            )
            declaration_count = tokens_css.count(f"{token}:")
            if token.startswith(("--desk-prompt-assistant-", "--desk-agent-")):
                self.assertEqual(declaration_count, 2, token)
            else:
                self.assertGreaterEqual(declaration_count, 1, token)

        self.assertNotIn("@keyframes", prompt_css_without_comments)
        self.assertNotRegex(
            prompt_css_without_comments,
            r"(?m)^\s*(?:transition|animation)(?:-[\w-]+)?\s*:",
        )
        self.assertNotRegex(
            prompt_css_without_comments,
            r"(?m)^\s*(?:position|display|inset|width|height|min-width|max-width|min-height|max-height|padding|margin|gap|overflow|transform|filter|backdrop-filter|font-size|line-height|opacity|z-index)\s*:",
        )
        self.assertNotRegex(
            controls_css,
            r'body\.desk-app\[data-theme="dark"\][^,{]*(?:desk-prompt-drawer|desk-prompt-modal|desk-agent-|desk-prompt-task-mode)',
        )

    def test_desktop_gallery_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        gallery_css = read_text("styles/desktop-gallery.css")
        gallery_css_without_comments = re.sub(r"/\*.*?\*/", "", gallery_css, flags=re.S)

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-gallery.css")
        self.assertLess(html.index("styles/desktop-prompt-assistant.css"), html.index("styles/desktop-gallery.css"))
        self.assertLess(html.index("styles/desktop-gallery.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-gallery.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-gallery.css"), html.index("styles/desktop-motion.css"))
        self.assertLess(html.index("styles/desktop-gallery.css"), html.index("styles/desktop-performance.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', gallery_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', gallery_css)
        self.assertNotIn('body.desk-app:not([data-theme', gallery_css)
        self.assertNotRegex(gallery_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", gallery_css)
        self.assertNotRegex(gallery_css, r"(?m)^\.desk-")

        for selector in (
            "body.desk-app[data-theme] .desk-gallery {",
            "body.desk-app[data-theme] .desk-gallery-search svg",
            "body.desk-app[data-theme] .desk-gallery-card {",
            "body.desk-app[data-theme] .desk-gallery-card.is-selected",
            "body.desk-app[data-theme] .desk-gallery-video.is-expanded",
            "body.desk-app[data-theme] .desk-gallery-video-folder__visual",
            "body.desk-app[data-theme] .desk-gallery-file {",
            "body.desk-app[data-theme] .desk-gallery-set {",
            "body.desk-app[data-theme] .desk-gallery-inspector {",
            "body.desk-app[data-theme] .desk-gallery .desk-prompt-source-controls::before",
            "body.desk-app[data-theme] .desk-gallery-preview {",
            "body.desk-app[data-theme] .desk-pinterest-analysis-modal__prompt textarea",
            "body.desk-app[data-theme] .desk-pinterest-split-modal__candidate.is-selected",
        ):
            self.assertIn(selector, gallery_css)

        referenced_tokens = set(re.findall(r"var\((--desk-[\w-]+)", gallery_css))
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", tokens_css))
        self.assertFalse(referenced_tokens - declared_tokens, sorted(referenced_tokens - declared_tokens))
        for token in sorted(referenced_tokens):
            self.assertTrue(token.startswith("--desk-gallery-"), token)
            self.assertEqual(tokens_css.count(f"{token}:"), 2, token)

        self.assertNotIn("@keyframes", gallery_css_without_comments)
        self.assertNotRegex(
            gallery_css_without_comments,
            r"(?m)^\s*(?:transition|animation)(?:-[\w-]+)?\s*:",
        )
        self.assertNotRegex(
            gallery_css_without_comments,
            r"(?m)^\s*(?:position|display|inset|width|height|min-width|max-width|min-height|max-height|padding|margin|gap|overflow|border-radius|transform|filter|backdrop-filter|font-size|line-height|opacity|z-index)\s*:",
        )

    def test_desktop_settings_auth_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        controls_css = read_text("styles/desktop-controls.css")
        settings_css = read_text("styles/desktop-settings-auth.css")
        settings_css_without_comments = re.sub(r"/\*.*?\*/", "", settings_css, flags=re.S)

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-settings-auth.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-controls.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-geometry.css")
        self.assertLess(html.index("styles/desktop-gallery.css"), html.index("styles/desktop-settings-auth.css"))
        self.assertLess(html.index("styles/desktop-settings-auth.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-settings-auth.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-settings-auth.css"), html.index("styles/desktop-motion.css"))
        self.assertLess(html.index("styles/desktop-settings-auth.css"), html.index("styles/desktop-performance.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', settings_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', settings_css)
        self.assertNotIn('body.desk-app:not([data-theme', settings_css)
        self.assertNotRegex(settings_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", settings_css)
        self.assertNotRegex(settings_css, r"(?m)^\.desk-")

        for selector in (
            "body.desk-app[data-theme] .desk-settings {",
            "body.desk-app[data-theme] .desk-settings-tabs {",
            "body.desk-app[data-theme] .desk-settings-card {",
            "body.desk-app[data-theme] .desk-settings-form input[type=\"checkbox\"]",
            "body.desk-app[data-theme] .desk-settings-secret-clear {",
            "body.desk-app[data-theme] .desk-settings-pool-toolbar {",
            "body.desk-app[data-theme] .desk-settings-pool-activity.is-error",
            "body.desk-app[data-theme] .desk-settings-account {",
            "body.desk-app[data-theme] .desk-settings .desk-comfy-settings-workflow {",
            "body.desk-app[data-theme] .desk-settings-info-tip {",
            "body.desk-app[data-theme] .desk-settings-info-tip__section li::before",
            "body.desk-app[data-theme] .auth-overlay {",
            "body.desk-app[data-theme] .auth-card {",
        ):
            self.assertIn(selector, settings_css)

        referenced_tokens = set(re.findall(r"var\((--desk-[\w-]+)", settings_css))
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", tokens_css))
        self.assertFalse(referenced_tokens - declared_tokens, sorted(referenced_tokens - declared_tokens))
        for token in sorted(referenced_tokens):
            self.assertTrue(token.startswith(("--desk-settings-", "--desk-auth-", "--desk-status-")), token)
            declarations = tokens_css.count(f"{token}:")
            if token.startswith(("--desk-settings-", "--desk-auth-")):
                self.assertEqual(declarations, 2, token)
            else:
                self.assertGreaterEqual(declarations, 1, token)

        self.assertNotIn("@keyframes", settings_css_without_comments)
        self.assertNotRegex(
            settings_css_without_comments,
            r"(?m)^\s*(?:transition|animation)(?:-[\w-]+)?\s*:",
        )
        self.assertNotRegex(
            settings_css_without_comments,
            r"(?m)^\s*(?:position|display|inset|width|height|min-width|max-width|min-height|max-height|padding|margin|gap|overflow|border-radius|transform|filter|backdrop-filter|font-size|line-height|opacity|z-index)\s*:",
        )
        self.assertNotRegex(
            controls_css,
            r'body\.desk-app\[data-theme="dark"\][^,{]*(?:desk-settings|auth-)',
        )

    def test_desktop_creation_tools_module_consumes_root_theme_tokens(self):
        html = read_text("desktop.html")
        tokens_css = read_text("styles/desktop-tokens.css")
        controls_css = read_text("styles/desktop-controls.css")
        tools_css = read_text("styles/desktop-creation-tools.css")
        tools_css_without_comments = re.sub(r"/\*.*?\*/", "", tools_css, flags=re.S)

        assert_asset_has_cache_bust(self, html, "styles/desktop-tokens.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-creation-tools.css")
        assert_asset_has_cache_bust(self, html, "styles/desktop-controls.css")
        self.assertLess(html.index("styles/desktop-settings-auth.css"), html.index("styles/desktop-creation-tools.css"))
        self.assertLess(html.index("styles/desktop-creation-tools.css"), html.index("styles/desktop-controls.css"))
        self.assertLess(html.index("styles/desktop-creation-tools.css"), html.index("styles/desktop-geometry.css"))
        self.assertLess(html.index("styles/desktop-creation-tools.css"), html.index("styles/desktop-motion.css"))
        self.assertLess(html.index("styles/desktop-creation-tools.css"), html.index("styles/desktop-performance.css"))

        self.assertNotIn('body.desk-app[data-theme="dark"]', tools_css)
        self.assertNotIn('body.desk-app[data-theme="light"]', tools_css)
        self.assertNotIn('body.desk-app:not([data-theme', tools_css)
        self.assertNotRegex(tools_css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", tools_css)
        self.assertNotRegex(tools_css, r"(?m)^\.desk-")

        for selector in (
            "body.desk-app[data-theme] .desk-file-node-heading__icon {",
            "body.desk-app[data-theme] .desk-file-preview-modal {",
            "body.desk-app[data-theme] .desk-file-preview-modal__layer-visibility {",
            "body.desk-app[data-theme] .desk-video-node__icon {",
            "body.desk-app[data-theme] .desk-video-runtime-mode button.is-active {",
            "body.desk-app[data-theme] .desk-video-result__preview {",
            "body.desk-app[data-theme] .desk-pose-studio__panel {",
            "body.desk-app[data-theme] .desk-director-joint-hud__card {",
            ".desk-director-field .desk-select-trigger",
            "body.desk-app[data-theme] .desk-layout-editor {",
            "body.desk-app[data-theme] .desk-layout-stage {",
            "body.desk-app[data-theme] .desk-layout-group-selection {",
            "body.desk-app[data-theme] .desk-layout-create__panel {",
        ):
            self.assertIn(selector, tools_css)

        referenced_tokens = set(
            re.findall(r"var\((--desk-(?:file|video|pose|layout)-[\w-]+)", tools_css)
        )
        declared_tokens = set(re.findall(r"(--desk-[\w-]+)\s*:", tokens_css))
        self.assertFalse(referenced_tokens - declared_tokens, sorted(referenced_tokens - declared_tokens))
        self.assertGreaterEqual(len(referenced_tokens), 250)
        for token in sorted(referenced_tokens):
            self.assertTrue(
                token.startswith(("--desk-file-", "--desk-video-", "--desk-pose-", "--desk-layout-")),
                token,
            )
            self.assertEqual(tokens_css.count(f"{token}:"), 2, token)

        self.assertNotIn("@keyframes", tools_css_without_comments)
        self.assertNotRegex(
            tools_css_without_comments,
            r"(?m)^\s*(?:transition|animation)(?:-[\w-]+)?\s*:",
        )
        self.assertNotRegex(
            tools_css_without_comments,
            r"(?m)^\s*(?:position|display|inset|width|height|min-width|max-width|min-height|max-height|padding|margin|gap|overflow|border-radius|transform|filter|backdrop-filter|font-size|line-height|opacity|z-index)\s*:",
        )

        self.assertNotIn("fixed light skins", controls_css)
        self.assertNotRegex(
            controls_css,
            r"body\.desk-app\s+:is\([\s\S]*?\.desk-layout-editor[\s\S]*?\.desk-pose-studio[\s\S]*?\)\s*\{",
        )


if __name__ == "__main__":
    unittest.main()
