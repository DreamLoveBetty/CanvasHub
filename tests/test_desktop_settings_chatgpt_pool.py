#!/usr/bin/env python3

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_asset_has_cache_bust(testcase, html: str, asset_path: str) -> None:
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


class DesktopSettingsChatgptPoolTest(unittest.TestCase):
    def read(self, rel: str) -> str:
        path = ROOT / rel
        if not path.exists() and rel.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
            path = ROOT / "frontend" / rel
        return path.read_text(encoding="utf-8")

    def test_settings_drawer_has_account_pool_tab(self):
        html = self.read("desktop.html")

        self.assertIn('data-settings-tab="chatgpt-pool"', html)
        self.assertIn(">账号池<", html)

    def test_settings_drawer_has_system_public_mode_tab(self):
        html = self.read("desktop.html")
        source = self.read("scripts/desktop-settings.js")

        self.assertIn('data-settings-tab="system"', html)
        self.assertIn(">系统<", html)
        self.assertIn("renderSystemRuntimeSettings", source)
        self.assertIn("server.public_mode", source)
        self.assertIn("server.host", source)
        self.assertIn("公网模式必须设置访问密码", source)

    def test_desktop_api_exposes_account_pool_methods(self):
        source = self.read("scripts/desktop-api.js")

        for name in (
            "getChatgptPoolStatus",
            "startChatgptPoolOAuth",
            "finishChatgptPoolOAuth",
            "openChatgptPoolOAuthClean",
            "importChatgptPoolAccounts",
            "importLocalChatgptPoolAuth",
            "refreshChatgptPoolAccounts",
            "updateChatgptPoolAccount",
            "deleteChatgptPoolAccounts",
        ):
            self.assertIn(name, source)

    def test_desktop_api_exposes_managed_codex_account_methods(self):
        source = self.read("scripts/desktop-api.js")

        for name in (
            "importManagedCodexOAuth",
            "updateManagedCodexOAuthAccount",
            "selectManagedCodexOAuthAccount",
            "deleteManagedCodexOAuthAccount",
        ):
            self.assertIn(name, source)
        self.assertIn("/api/managed-codex-oauth/import", source)
        self.assertIn("/api/managed-codex-oauth/update", source)
        self.assertIn("/api/managed-codex-oauth/select", source)
        self.assertIn("/api/managed-codex-oauth/delete", source)

    def test_settings_js_renders_managed_codex_account_pool_management(self):
        source = self.read("scripts/desktop-settings.js")
        css = self.read("styles/desktop-liquid.css")
        html = self.read("desktop.html")

        self.assertIn("renderManagedCodexAccount", source)
        self.assertIn("renderManagedCodexAddSettings", source)
        self.assertIn("data-managed-codex-account-select", source)
        self.assertIn("data-managed-codex-account data-account-id", source)
        self.assertIn("data-managed-codex-account-refresh", source)
        self.assertIn("data-managed-codex-account-toggle", source)
        self.assertIn("data-managed-codex-account-delete", source)
        self.assertIn("data-managed-codex-import-json", source)
        self.assertIn("managed_codex_oauth.accounts_dir", source)
        self.assertIn("账号类型", source)
        self.assertIn("AT 到期时间", source)
        self.assertIn("AT 到期", source)
        self.assertIn("刷新全部 AT", source)
        self.assertIn("Auth JSON", source)
        self.assertIn("data-managed-codex-account-delete", css)
        assert_asset_has_cache_bust(self, html, "scripts/desktop-settings.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-i18n.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-api.js")
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")

    def test_provider_connection_card_omits_managed_codex_runtime_fields(self):
        source = self.read("scripts/desktop-settings.js")

        start = source.index("function renderProviderCoreSettings")
        end = source.index("\n  function renderThirdPartyImageSettings", start)
        body = source[start:end]

        self.assertIn("gpt_provider.image_main_model", body)
        self.assertIn("gpt_provider.reasoning_effort", body)
        self.assertNotIn("gpt_provider.auth_file", body)
        self.assertNotIn("gpt_provider.auth_dir", body)
        self.assertNotIn("gpt_provider.api_base", body)
        self.assertIn("managed_codex_oauth.auth_file", source)
        self.assertIn("managed_codex_oauth.accounts_dir", source)
        self.assertIn("managed_codex_oauth.api_base", source)

    def test_provider_page_omits_codex_auth_candidates_card(self):
        source = self.read("scripts/desktop-settings.js")

        self.assertNotIn("function renderAuthCandidate", source)
        self.assertNotIn("renderCard('Codex Auth 候选'", source)
        self.assertNotIn("候选文件", source)
        self.assertIn("renderManagedCodexAccount", source)
        self.assertIn("当前使用", source)

    def test_third_party_settings_are_split_into_two_cards(self):
        source = self.read("scripts/desktop-settings.js")

        start = source.index("function renderThirdPartyImageSettings")
        end = source.index("\n  function renderPathSettings", start)
        body = source[start:end]

        self.assertIn("renderCard('Nano Banana API'", body)
        self.assertIn("renderCard('Gpt-Image-2 API'", body)
        self.assertIn("nano_banana_api.api_key", body)
        self.assertIn("nano_banana_api.base_url", body)
        self.assertNotIn("Google / Yunwu", body)
        self.assertIn('data-system-settings-card="third-party-nano"', body)
        self.assertIn("third_party_image_api.api_key", body)
        self.assertIn("third_party_image_api.generate_path", body)
        self.assertIn('data-system-settings-card="third-party-gpt-image"', body)
        self.assertIn("保存 Nano Banana API", body)
        self.assertIn("保存 Gpt-Image-2 API", body)
        self.assertNotIn("renderCard('第三方 API 配置'", body)
        self.assertNotIn("renderFormSectionTitle", source)

    def test_settings_js_renders_account_pool_management(self):
        source = self.read("scripts/desktop-settings.js")

        self.assertIn("renderChatgptPoolSettings", source)
        self.assertIn("data-chatgpt-pool-oauth-start", source)
        self.assertIn("data-chatgpt-pool-oauth-finish", source)
        self.assertIn("data-chatgpt-pool-import-local-auth", source)
        self.assertIn("data-chatgpt-pool-account-refresh", source)
        self.assertIn("data-chatgpt-pool-account-delete", source)
        self.assertIn("生成授权", source)
        self.assertNotIn("data-chatgpt-pool-force-reauth", source)
        self.assertNotIn("干净窗口打开</button>", source)
        self.assertIn("账号池", source)

    def test_desktop_gpt_node_exposes_provider_route(self):
        html = self.read("desktop.html")
        canvas = self.read("scripts/desktop-canvas.js")
        api = self.read("scripts/desktop-api.js")

        self.assertIn("deskGptProviderRouteSelect", html)
        self.assertIn("deskGptTaskTypeSelect", html)
        self.assertIn("PPT", html)
        self.assertIn("PSD", html)
        self.assertIn("data-add-node=\"file_output\"", html)
        self.assertIn("desktop-file-results.js", html)
        self.assertIn("本地 Codex", html)
        self.assertIn("账号池 API", html)
        self.assertIn("gptTaskType", canvas)
        self.assertIn("applyGptTaskTypeToNode", canvas)
        self.assertIn("fileOutputNodeHtml", canvas)
        self.assertIn("gptProviderRoute", canvas)
        self.assertIn("task_type", api)
        self.assertIn("gpt_provider_route", api)


if __name__ == "__main__":
    unittest.main()
