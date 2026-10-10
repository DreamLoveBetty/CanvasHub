"""Portable contracts for the settings-only compact control scale and material."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SettingsControlStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry = (ROOT / "frontend/styles/desktop-geometry.css").read_text()
        cls.paint = (ROOT / "frontend/styles/desktop-settings-auth.css").read_text()
        cls.controls = (ROOT / "frontend/styles/desktop-controls.css").read_text()

    def test_settings_scale_uses_shared_tokens_without_global_changes(self):
        block = re.search(r"body\.desk-app\[data-theme\] \.desk-settings\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("--desk-settings-tab-height: var(--desk-control-height-xs);", block)
        self.assertIn("--desk-settings-control-height: var(--desk-control-height-xs);", block)
        self.assertIn("--desk-settings-control-font: var(--desk-font-size-caption);", block)
        self.assertIn("min-width: 0;", block)
        # Drawer between title bar and status bar, right of the tool rail; width is
        # user-resizable through --desk-settings-width (desktop-settings-drawer.js).
        self.assertIn("width: var(--desk-settings-width, 760px);", block)
        self.assertIn("max-width: calc(100vw - var(--desk-settings-drawer-left) - 24px);", block)
        for declaration in ("top: var(--desk-settings-drawer-top);", "bottom: var(--desk-settings-drawer-bottom);",
                            "left: var(--desk-settings-drawer-left);"):
            self.assertIn(declaration, block)
        self.assertIn("--desk-settings-label-width: 100px;", block)

    def test_all_command_families_share_the_scale_but_thumbnail_cards_do_not(self):
        match = re.search(r"body\.desk-app\[data-theme\] \.desk-settings :is\(\s*\.desk-segment button,([^}]+)\}", self.geometry)
        self.assertIsNotNone(match)
        block = match[1]
        for selector in (".desk-button", ".desk-video-runtime-mode button", ".desk-settings-form__actions button",
                         ".desk-settings-account__actions button", ".desk-qwen21-tools__inspection > button",
                         ".desk-krea2-tools__model > button", ".desk-qwen21-tools__progress > button"):
            with self.subTest(selector=selector):
                self.assertIn(selector, block)
        self.assertNotIn(".desk-comfy-settings-workflow", block)
        self.assertNotIn(".desk-settings-tabs button", block)
        self.assertIn("min-height: var(--desk-settings-control-height);", block)
        self.assertIn("line-height: var(--desk-line-height-caption);", block)
        self.assertIn("border-radius: var(--desk-radius-control);", block)
        self.assertIn("font-weight: var(--desk-font-weight-medium);", block)
        self.assertIn("padding: var(--desk-space-1) var(--desk-space-3);", block)

    def test_help_text_includes_small_and_uses_caption_tokens(self):
        self.assertRegex(self.geometry, r"\.desk-settings :where\(\s*span, strong, em, p, small,")
        self.assertRegex(self.geometry, r"\.desk-settings :is\(\.desk-settings-form__hint, \.desk-settings-form__activity\)\s*\{\s*font-size: var\(--desk-font-size-caption\);")

    def test_plain_fields_use_shared_radius_and_keep_width_inside_parent(self):
        block = re.search(r"\.desk-settings :is\(\s*input:not\(\[type=\"checkbox\"\]\)[^}]+\}", self.geometry)[0]
        for declaration in ("height: var(--desk-settings-control-height);", "max-width: 100%;", "min-width: 0;",
                            "border-width: 1px;", "border-style: solid;",
                            "border-radius: var(--desk-radius-control);"):
            self.assertIn(declaration, block)

    def test_textareas_are_not_forced_to_single_line_height(self):
        block = re.search(r"body\.desk-app\[data-theme\] \.desk-settings textarea\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("min-height: calc(var(--desk-control-height-xs) * 2);", block)
        self.assertIn("resize: vertical;", block)
        self.assertNotRegex(block, r"(?<![\w-])height:")
        self.assertIn("line-height: var(--desk-line-height-normal);", block)

    def test_navigation_keeps_a_separate_height_contract_without_oversizing(self):
        match = re.search(r"body\.desk-app\[data-theme\] \.desk-settings-tabs button\s*\{([^}]+)\}", self.geometry)
        self.assertIsNotNone(match)
        for declaration in ("height: var(--desk-settings-nav-item-height);", "min-height: var(--desk-settings-nav-item-height);",
                            "font-weight: var(--desk-font-weight-medium);", "text-align: left;"):
            self.assertIn(declaration, match[1])
        self.assertIn("--desk-settings-nav-item-height: 28px;", self.geometry)

    def test_segments_use_inset_paint_not_extra_height_for_the_track(self):
        match = re.search(r"body\.desk-app\[data-theme\] \.desk-settings :is\(\s*\.desk-segment,([^}]+)\}", self.geometry)
        self.assertIsNotNone(match)
        for selector in (".desk-settings-canvas-interaction__segment", ".desk-video-runtime-mode"):
            self.assertIn(selector, match[1])
        for declaration in ("padding: 0;", "border-width: 0;", "box-sizing: border-box;", "gap: var(--desk-space-1);"):
            self.assertIn(declaration, match[1])
        self.assertNotIn("height:", match[1], "do not clip wrapped labels or multi-row controls")
        self.assertIn("box-shadow: inset 0 0 0 1px var(--desk-settings-segment-border);", self.controls)

    def test_fields_are_regular_weight_and_settings_body_shadows_are_quiet(self):
        fields = re.search(r"\.desk-settings :is\(\s*input:not\(\[type=\"checkbox\"\]\)[^}]+\}", self.geometry)[0]
        self.assertIn("font-weight: var(--desk-font-weight-regular);", fields)
        self.assertIn(".desk-settings .desk-settings__body {", self.controls)
        self.assertIn("--desk-shadow-button: none;", self.controls)
        self.assertIn(".desk-settings .desk-settings__body button:is(", self.controls)
        self.assertIn("0 1px 3px color-mix(in srgb, var(--desk-action-primary-shadow) 45%, transparent);", self.controls)
        self.assertIn("0 1px 4px color-mix(in srgb, var(--desk-action-primary-shadow-strong) 45%, transparent);", self.controls)

    def test_material_covers_model_tool_fields_outside_legacy_forms(self):
        block = re.search(r"body\.desk-app\[data-theme\] :where\(\s*\.desk-settings input:not[^}]+\}", self.paint)[0]
        self.assertIn('.desk-settings input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"])', block)
        self.assertIn(".desk-settings textarea", block)
        self.assertIn("background: var(--desk-settings-field-background);", block)
        self.assertIn("box-shadow: var(--desk-settings-field-shadow);", block)

    def test_settings_selects_use_field_borders_not_white_button_edges(self):
        block = self.controls.split("/* Settings selects are fields", 1)[1].split("/* The Agent scope picker", 1)[0]
        base = block.split("}", 1)[0]
        self.assertIn('.desk-settings select:not(.desk-select-native)', base)
        self.assertIn('.desk-settings .desk-select-shell', base)
        self.assertIn(':not([data-select-variant="language"]):not([data-select-variant="image-group-role"])', base)
        for token in ("ink", "background", "border", "shadow"):
            self.assertIn(f"var(--desk-settings-field-{token})", base)
        self.assertNotIn("var(--desk-color-control-border)", base)
        self.assertNotIn("!important", block)

    def test_settings_select_interactions_keep_hover_pressed_focus_open_and_disabled_edges(self):
        block = self.controls.split("/* Settings selects are fields", 1)[1].split("/* The Agent scope picker", 1)[0]
        block = block.split("*/", 1)[1]
        for state in (":hover:not(:disabled)", ":active:not(:disabled)", ":focus-visible", ".is-open", ".is-disabled", ":disabled"):
            self.assertIn(state, block)
        for token in ("--desk-color-control-border-hover", "--desk-color-control-border-active",
                      "--desk-color-focus-border", "--desk-color-control-border-disabled", "--desk-shadow-focus"):
            self.assertIn(f"var({token})", block)
        for selector in ("select:not(.desk-select-native):hover", "select:not(.desk-select-native):active",
                         "select:not(.desk-select-native):focus-visible", "select:not(.desk-select-native):disabled"):
            self.assertIn(selector, block)
        for selectors, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
            self.assertTrue(all(".desk-settings " in selector for selector in selectors.split(",")), selectors)

    def test_contextual_help_shrinks_its_header_and_wraps_technical_tokens(self):
        block = self.geometry.split("/* Contextual Settings help", 1)[1].split("@media", 1)[0]
        self.assertRegex(block, r"\.desk-settings-info-tip\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\);")
        self.assertRegex(block, r"\.desk-status-tip__head > div\s*\{[^}]*min-width: 0;[^}]*flex: 1 1 auto;")
        self.assertRegex(block, r"\.desk-status-tip__head span\s*\{[^}]*max-width: 100%;")
        for declaration in ("min-width: var(--desk-control-height-xs);", "width: var(--desk-control-height-xs);",
                            "height: var(--desk-control-height-xs);", "overflow-wrap: anywhere;"):
            self.assertIn(declaration, block)
        self.assertNotIn("desk-status-tip__raw", block, "do not resize ordinary diagnostic tooltips")

    def test_lora_key_gets_a_full_row_and_narrow_accounts_can_wrap(self):
        block = re.search(r"\.desk-settings \.desk-lora-settings \.desk-lora-actions input\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("flex: 1 1 100%;", block)
        self.assertIn("min-width: 0;", block)
        narrow = re.search(r"@media \(max-width: 560px\)\s*\{([\s\S]+?)\n\}", self.geometry)[1]
        self.assertRegex(narrow, r"\.desk-settings-account\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\);")
        self.assertRegex(self.geometry, r"\.desk-settings-account__actions\s*\{\s*grid-column: 1;\s*grid-row: auto;\s*flex-wrap: wrap;")

    def test_small_clear_action_preserves_separate_size(self):
        block = re.search(r"body\.desk-app\[data-theme\] \.desk-settings-secret-clear\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("min-height: var(--desk-control-height-xs);", block)

    def test_single_line_rows_include_nested_runtime_and_supervisor_sections(self):
        match = re.search(r"\.desk-settings \.desk-settings-form :is\(\s*label:has\(([\s\S]+?)\)\s*\{([^}]+)\}", self.geometry)
        self.assertIsNotNone(match)
        self.assertIn('input:not([type="file"]):not([type="hidden"])', match[1])
        self.assertIn("> select, > .desk-select-shell", match[1])
        self.assertIn(".desk-settings-secret-field:has(> input)", match[1])
        self.assertNotIn("textarea", match[1])
        for declaration in ("grid-template-columns: var(--desk-settings-label-width) minmax(0, 1fr);",
                            "align-items: center;", "min-height: var(--desk-settings-control-height);"):
            self.assertIn(declaration, match[2])

    def test_secret_clear_has_reserved_trailing_space_not_an_overlaid_input(self):
        root = re.search(r"\.desk-settings \.desk-settings-secret-field:has\(> input\)\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("position: relative;", root)
        reserve = re.search(r"\.desk-settings-secret-field:has\(> input\):has\(\.desk-settings-secret-clear\)\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("padding-inline-end: 42px;", reserve)
        command = re.search(r"\.desk-settings-secret-field:has\(> input\) \.desk-settings-secret-clear\s*\{([^}]+)\}", self.geometry)[1]
        for declaration in ("position: absolute;", "inset-inline-end: 0;", "width: 36px;",
                            "height: var(--desk-settings-control-height);"):
            self.assertIn(declaration, command)
        self.assertIn(".desk-settings-secret-clear:is(.is-loading, .is-done)", self.geometry)
        self.assertIn("padding-inline-end: 70px;", self.geometry)
        self.assertRegex(self.geometry, r"\.desk-settings-secret-clear:is\(\.is-loading, \.is-done\)\s*\{\s*width: 64px;")
        self.assertRegex(self.geometry, r"\.desk-settings-secret-clear\s*\{[^}]+white-space: nowrap;")
        self.assertNotIn("display: contents", self.geometry)
        self.assertIn(".desk-settings .desk-settings-secret-clear:active:not(:disabled)", self.controls)

    def test_heading_hierarchy_does_not_make_auxiliary_text_bolder_than_values(self):
        title = re.search(r"\.desk-settings__title h2\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("font-size: 15px;", title)
        heading = re.search(r"\.desk-settings-card h3\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("font-size: var(--desk-font-size-caption);", heading)
        self.assertIn("font-weight: var(--desk-font-weight-medium);", heading)
        labels = re.search(r"\.desk-settings-form :is\(label > span, \.desk-settings-secret-field__label > span\)\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("font-weight: 500;", labels)
        self.assertRegex(self.geometry, r"\.desk-settings__body :is\(\s*p, small, em,[^}]+font-weight: var\(--desk-font-weight-regular\);")

    def test_nested_groups_are_flat_but_real_status_frames_remain_domain_owned(self):
        groups = re.search(r"\.desk-settings :is\(\.desk-video-runtime-panel, \.desk-video-supervisor\)\s*\{([^}]+)\}", self.geometry)[1]
        self.assertIn("padding: var(--desk-space-3) 0 0;", groups)
        self.assertIn("border-width: 1px 0 0;", groups)
        self.assertIn("border-radius: 0;", groups)
        paint = re.search(r"\.desk-settings :is\(\.desk-video-runtime-panel, \.desk-video-supervisor\)\s*\{([^}]+)\}", self.paint)[1]
        self.assertIn("background: transparent;", paint)
        self.assertIn("border-color: var(--desk-settings-field-border);", paint)
        for name in ("krea2", "qwen21"):
            css = (ROOT / f"frontend/styles/desktop-{name}.css").read_text()
            self.assertIn(f".desk-{name}-tools__inspection.is-warn", css)
            self.assertIn(f".desk-{name}-tools__progress.is-error", css)
            self.assertIn("border-color: var(--desk-color-danger-border);", css)
        self.assertRegex(self.geometry, r"\.desk-qwen21-tools__inspection\)\.is-empty\s*\{[^}]+border-width: 0;")

    def test_context_selection_has_flat_hover_pressed_disabled_and_focus_states(self):
        context = self.controls.split("/* Category/mode selection", 1)[1]
        for family in (".desk-settings-tabs", ".desk-segment", ".desk-settings-canvas-interaction__segment", ".desk-video-runtime-mode"):
            self.assertIn(family, context)
        for state in ("button.is-active:not(", "button.is-active:hover:not(", "button.is-active:active:not(",
                      "button:disabled:not(", "button:focus-visible:not("):
            self.assertIn(state, context)
        self.assertIn("background: var(--desk-color-accent-soft);", context)
        self.assertIn("outline: 2px solid var(--desk-color-accent);", context)
        self.assertIn("outline-offset: -2px;", context)
        self.assertNotIn("--desk-action-primary", context)

    def test_file_picker_remains_native_and_has_shared_button_material(self):
        self.assertIn('input[type="file"]::file-selector-button', self.geometry)
        block = re.search(r"\.desk-settings input\[type=\"file\"\]::file-selector-button\s*\{([^}]+)\}", self.controls)[1]
        self.assertIn("background: var(--desk-color-control-bg);", block)

    def test_standalone_model_commands_have_theme_aware_hover_and_disabled_states(self):
        for state in ("> button {", "> button:hover:not(:disabled) {", "> button:disabled {"):
            self.assertIn(state, self.controls)
        self.assertIn(".desk-qwen21-tools__inspection,", self.controls)
        self.assertIn(".desk-krea2-tools__progress,", self.controls)
        self.assertIn("border-color: var(--desk-color-control-border-hover);", self.controls)
        self.assertIn("> button.is-danger:hover:not(:disabled)", self.controls)
        self.assertIn("background: var(--desk-settings-danger-control-background);", self.controls)
        danger = re.search(r"body\.desk-app\[data-theme\] \.desk-settings :is\(([^)]+)\) > button\.is-danger\s*\{", self.controls)[1]
        self.assertIn(".desk-krea2-tools__progress,", danger)
        self.assertIn(".desk-qwen21-tools__progress,", danger)

    def test_changed_styles_are_loaded_once_with_new_cache_versions(self):
        html = (ROOT / "frontend/desktop.html").read_text()
        for asset in ("desktop-geometry.css", "desktop-settings-auth.css", "desktop-controls.css"):
            versions = re.findall(rf'styles/{re.escape(asset)}\?v=([^"\s]+)', html)
            expected = "20261009-settings-drawer2" if asset == "desktop-controls.css" else "20261010-color-bloom1"
            self.assertEqual(versions, [expected])


if __name__ == "__main__":
    unittest.main()
