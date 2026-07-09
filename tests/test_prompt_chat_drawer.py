import json
import re
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend import server
from backend import prompt_skill_client


ROOT = Path(__file__).resolve().parents[1]


def read_text(path):
    target = ROOT / path
    if not target.exists() and path.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
        target = ROOT / "frontend" / path
    return target.read_text(encoding="utf-8")


def assert_asset_has_cache_bust(testcase, html, asset_path):
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


class PromptChatBackendTest(unittest.TestCase):
    def test_assistant_chat_is_separate_from_formal_candidates(self):
        with patch.object(server, "assistant_chat", return_value={
            "ok": True,
            "reply": "先减少广告感词汇，再强化冷调光影和角色姿态。",
            "provider": "gpt_oauth",
            "model": "gpt-5.5",
        }):
            result = server.assistant_chat("雨夜城市街道", "为什么像广告图", {})

        self.assertEqual(result["reply"], "先减少广告感词汇，再强化冷调光影和角色姿态。")
        self.assertNotIn("candidates", result)

    def test_assistant_chat_stream_contract_exists(self):
        server_py = read_text("backend/server.py")
        prompt_client_py = read_text("backend/prompt_skill_client.py")

        self.assertIn("assistant_chat_stream", server_py)
        self.assertIn("'/api/prompt/assistant-chat/stream'", server_py)
        self.assertIn("application/x-ndjson", server_py)
        self.assertIn("_write_ndjson_event", server_py)
        self.assertIn("X-Accel-Buffering", server_py)
        self.assertIn("def assistant_chat_stream", prompt_client_py)
        self.assertIn("_call_prompt_provider_stream", prompt_client_py)
        self.assertIn("_call_gpt_oauth_stream", prompt_client_py)
        self.assertIn("_call_openai_compatible_stream", prompt_client_py)

        with patch.object(
            prompt_skill_client,
            "_assistant_chat_request",
            return_value={
                "prompt": "讨论",
                "provider_id": "gpt_oauth",
                "model": "gpt-5.5",
                "reasoning_effort": "low",
            },
        ), patch.object(
            prompt_skill_client,
            "_call_prompt_provider_stream",
            return_value=iter(["先", "讨论"]),
        ):
            events = list(prompt_skill_client.assistant_chat_stream("文本", "消息", {}))

        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[1], {"type": "delta", "text": "先"})
        self.assertEqual(events[2], {"type": "delta", "text": "讨论"})
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["reply"], "先讨论")

    def test_assistant_chat_stream_falls_back_to_account_pool_on_any_codex_failure(self):
        pool_payload = {
            "ok": True,
            "result": {
                "model": "pool-auto",
                "choices": [{"message": {"content": "账号池兜底回复"}}],
            },
        }
        with patch.object(
            prompt_skill_client,
            "_assistant_chat_request",
            return_value={
                "prompt": "讨论",
                "provider_id": "gpt_oauth",
                "model": "gpt-5.5",
                "reasoning_effort": "low",
            },
        ), patch.object(
            prompt_skill_client,
            "_call_prompt_provider_stream",
            side_effect=RuntimeError("provider exploded after request started"),
        ), patch.object(
            prompt_skill_client,
            "chat_chatgpt_pool",
            return_value=pool_payload,
        ) as pool_chat:
            events = list(prompt_skill_client.assistant_chat_stream("文本", "消息", {}))

        pool_chat.assert_called_once()
        self.assertEqual(events[1], {"type": "delta", "text": "账号池兜底回复"})
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["provider"], "chatgpt_pool")
        self.assertEqual(events[-1]["model"], "pool-auto")
        self.assertEqual(events[-1]["fallback"], "chatgpt_pool_chat")

    def test_formal_prompt_candidates_exclude_original(self):
        candidates = server._prompt_version_candidates(
            "雨夜城市街道",
            message="更电影感",
            style={"title": "Raw", "promptTemplate": "光影克制"},
            polished={
                "full_prompt": "电影感雨夜城市街道，霓虹反光",
                "compact_prompt": "雨夜街道，霓虹反光",
            },
        )

        kinds = [item["kind"] for item in candidates]
        self.assertNotIn("original", kinds)
        self.assertIn("polished", kinds)
        self.assertIn("compact", kinds)
        self.assertIn("english_feed", kinds)
        self.assertIn("style_enhanced", kinds)
        self.assertIn("custom_direction", kinds)

    def test_prompt_chat_fallback_helpers_keep_text_available(self):
        text = "未来城市海报"
        self.assertIn(text, server._prompt_chat_english_feed(text))
        self.assertIn(text, server._prompt_chat_style_enhanced(text, {}))

    def test_prompt_gpt_oauth_prefers_managed_codex_env(self):
        with patch.object(
            prompt_skill_client,
            "get_managed_codex_oauth_status",
            return_value={"enabled": True, "configured": True},
        ), patch.object(
            prompt_skill_client,
            "get_managed_codex_provider_env",
            return_value={
                "CODEX_API_AUTH_FILE": "/tmp/managed-auth.json",
                "CODEX_API_AUTH_DIR": "",
                "GPT_PROVIDER_AUTH_FILE": "",
                "GPT_PROVIDER_AUTH_DIR": "",
                "CODEX_API_AUTH_STRICT": "1",
                "CODEX_API_BASE": "https://chatgpt.com/backend-api/codex",
            },
        ), patch.object(
            prompt_skill_client,
            "get_gpt_provider_config",
            return_value={
                "auth_file": "/tmp/local-auth.json",
                "auth_dir": "",
                "api_base": "",
                "image_main_model": "gpt-5.5",
                "reasoning_effort": "medium",
                "transport_mode": "nonstream",
            },
        ):
            _, env = prompt_skill_client._gpt_oauth_env_overrides()

        self.assertEqual(env["CODEX_API_AUTH_FILE"], "/tmp/managed-auth.json")
        self.assertEqual(env["CODEX_API_AUTH_STRICT"], "1")

    def test_prompt_polish_chatgpt_pool_fallback_returns_polish_payload(self):
        content = json.dumps({
            "full_prompt": "完整成片提示词",
            "compact_prompt": "精简提示词",
            "modules": ["M0"],
            "warnings": ["fallback"],
        }, ensure_ascii=False)
        with patch.object(server, "chat_chatgpt_pool", return_value={
            "ok": True,
            "result": {
                "model": "pool-auto",
                "choices": [{"message": {"content": content}}],
            },
        }):
            result = server._polish_prompt_with_chatgpt_pool_chat(
                "原始提示词",
                RuntimeError("refresh_token_reused"),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "chatgpt_pool")
        self.assertEqual(result["skill"], "chat_fallback")
        self.assertEqual(result["full_prompt"], "完整成片提示词")
        self.assertEqual(result["compact_prompt"], "精简提示词")
        self.assertEqual(result["prompt_polish_fallback"], "chatgpt_pool_chat")

    def test_style_presets_and_prompt_versions_are_saved_as_versioned_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with patch.object(server, "PROMPT_DATA_DIR", data_dir), \
                 patch.object(server, "STYLE_PRESETS_FILE", data_dir / "style_presets.json"), \
                 patch.object(server, "PROMPT_VERSIONS_FILE", data_dir / "prompt_versions.json"), \
                 patch.object(server.time, "time", return_value=1710000000), \
                 patch.object(server.random, "randint", return_value=1234):
                preset = server.save_style_preset({
                    "name": "商业摄影",
                    "prompt_style": "clean product lighting",
                    "avoid": "avoid clutter",
                    "best_for": "product hero",
                })
                version = server.save_prompt_version({
                    "type": "polished",
                    "label": "Polished",
                    "text": "polished prompt",
                    "target": {"nodeId": "input", "type": "input"},
                    "language": "zh",
                    "intent": {"aspect_ratio": "9:16", "style": ["cinematic"]},
                    "risk_score": 4,
                    "risk_level": "medium",
                    "changed_terms": [{"from": "seductive", "to": "softly posed"}],
                    "warnings": ["changed"],
                })
                presets = server.list_style_presets()
                versions = server.list_prompt_versions()

            self.assertEqual(preset["id"], "style_1710000000_1234")
            self.assertEqual(version["id"], "prompt_version_1710000000_1234")
            self.assertEqual(presets[0]["prompt_style"], "clean product lighting")
            self.assertEqual(presets[0]["avoid"], "avoid clutter")
            self.assertEqual(presets[0]["best_for"], "product hero")
            self.assertEqual(versions[0]["text"], "polished prompt")
            self.assertEqual(versions[0]["language"], "zh")
            self.assertEqual(versions[0]["intent"]["aspect_ratio"], "9:16")
            self.assertEqual(versions[0]["risk_score"], 4)
            self.assertEqual(versions[0]["risk_level"], "medium")
            self.assertEqual(versions[0]["changed_terms"][0]["from"], "seductive")

    def test_style_preset_extract_has_local_fallback(self):
        with patch.object(prompt_skill_client, "_choose_model", return_value="gpt-5.5"), \
             patch.object(prompt_skill_client, "_call_prompt_provider", side_effect=RuntimeError("upstream down")), \
             patch.object(prompt_skill_client, "chat_chatgpt_pool", None):
            preset = prompt_skill_client.extract_style_preset(
                "雨夜城市角色海报，冷调电影感",
                "提取风格",
                {"candidate": "克制冷调电影感，玻璃反光，避免广告感"},
            )

        self.assertTrue(preset["ok"])
        self.assertIn("电影", preset["name"])
        self.assertIn("prompt_style", preset)
        self.assertIn("avoid", preset)

    def test_style_preset_extract_falls_back_to_account_pool_on_codex_failure(self):
        pool_payload = {
            "ok": True,
            "result": {
                "model": "pool-auto",
                "choices": [{"message": {"content": json.dumps({
                    "name": "冷调电影感",
                    "description": "低饱和城市夜景视觉。",
                    "positive_style": "冷调电影光，玻璃反光，克制高级。",
                    "avoid": "避免广告感和过曝。",
                    "best_for": "城市角色海报",
                    "prompt_style": "冷调电影光，玻璃反光，克制高级，低饱和夜景氛围。",
                    "tags": ["电影感", "冷调"]
                }, ensure_ascii=False)}}],
            },
        }
        with patch.object(prompt_skill_client, "_choose_model", return_value="gpt-5.5"), \
             patch.object(prompt_skill_client, "_call_prompt_provider", side_effect=RuntimeError("provider down")), \
             patch.object(prompt_skill_client, "chat_chatgpt_pool", return_value=pool_payload) as pool_chat:
            preset = prompt_skill_client.extract_style_preset(
                "雨夜城市角色海报，冷调电影感",
                "提取风格",
                {"candidate": "克制冷调电影感，玻璃反光，避免广告感"},
            )

        pool_chat.assert_called_once()
        self.assertTrue(preset["ok"])
        self.assertEqual(preset["provider"], "chatgpt_pool")
        self.assertEqual(preset["fallback"], "chatgpt_pool_chat")
        self.assertIn("冷调电影", preset["prompt_style"])

    def test_safe_rewrite_uses_standalone_adapter_rules(self):
        with patch.object(prompt_skill_client, "_choose_model", return_value="gpt-5.5"), \
             patch.object(
                 prompt_skill_client,
                 "_call_prompt_provider",
                 return_value=json.dumps({
                     "zh_prompt": "[1. 画布]\n16:9。\n\n[2. 图像类型]\n电影感角色定妆。\n\n[3. 主体]\n三位明确成年的女性角色。\n\n[4. 角色 / 世界观]\n奇幻角色。\n\n[5. 姿态 / 动作]\n克制姿态。\n\n[6. 服装 / 造型]\n优雅深 V 奇幻礼服。\n\n[7. 构图 / 镜头]\n完整构图。\n\n[8. 场景 / 背景]\n漫展编辑人像背景。\n\n[9. 光线 / 色彩]\n电影级布光。\n\n[10. 材质 / 渲染]\n真实材质。\n\n[11. 约束]\nSafety constraints: non-explicit, no nudity, no minors, no watermark.",
                     "en_prompt": "[1. Canvas]\n16:9.\n\n[2. Image Type]\nCinematic character lookbook.\n\n[3. Subject]\nThree clearly adult women.\n\n[4. Role / Worldbuilding]\nFantasy characters.\n\n[5. Pose / Action]\nRestrained pose.\n\n[6. Clothing / Styling]\nElegant deep-V fantasy gowns.\n\n[7. Composition / Camera]\nFull composition.\n\n[8. Scene / Background]\nEditorial convention portrait background.\n\n[9. Lighting / Color]\nCinematic lighting.\n\n[10. Material / Rendering]\nRealistic material detail.\n\n[11. Constraints]\nSafety constraints: non-explicit, no nudity, no minors, no watermark.",
                 }),
             ) as provider:
            result = prompt_skill_client.safe_rewrite_prompt(
                "three young women, mildly seductive, revealing cleavage, see-through gown",
                {},
            )

        self.assertTrue(result["ok"])
        self.assertIn("[1. 画布]", result["zh_prompt"])
        self.assertIn("[11. 约束]", result["zh_prompt"])
        self.assertIn("[1. Canvas]", result["en_prompt"])
        self.assertIn("[11. Constraints]", result["en_prompt"])
        self.assertIn("明确成年", result["zh_prompt"])
        self.assertIn("clearly adult", result["en_prompt"])
        self.assertIn("rewritten_prompts", result)
        self.assertIn("non-explicit", result["rewritten_prompt"])
        self.assertIn("no nudity", result["rewritten_prompt"])
        self.assertGreaterEqual(result["risk_score"], 7)
        self.assertIn(result["risk_level"], {"high", "severe"})
        self.assertTrue(result["changed_terms"])
        self.assertTrue(result["warnings"])
        system_prompt = provider.call_args.args[2]
        user_prompt = provider.call_args.args[1]
        self.assertIn("You are a prompt rewriting assistant for image generation.", system_prompt)
        self.assertIn('"zh_prompt"', system_prompt)
        self.assertIn('"en_prompt"', system_prompt)
        self.assertIn("11-section prompt skeleton", system_prompt)
        self.assertIn("cleavage / revealing cleavage", system_prompt)
        self.assertIn("see-through / transparent dress", system_prompt)
        self.assertIn("Apply the role instructions and the high-risk wording replacement table exactly.", user_prompt)
        self.assertIn("strict JSON only with keys zh_prompt and en_prompt", user_prompt)
        self.assertIn("zh_prompt headings must be [1. 画布] through [11. 约束]", user_prompt)
        self.assertIn("intent", user_prompt)
        self.assertIn("changed_terms", user_prompt)

    def test_prompt_adapter_analysis_tracks_risk_and_dictionary_changes(self):
        analysis = prompt_skill_client.analyze_prompt_adapter(
            "A low angle photo of young East Asian women, seductive pose, revealing cleavage, see-through gown, glossy skin, one foot reaching camera, readable random text."
        )

        self.assertGreaterEqual(analysis["risk_score"], 10)
        self.assertEqual(analysis["risk_level"], "severe")
        self.assertFalse(analysis["blocked"])
        self.assertEqual(analysis["intent"]["aspect_ratio"], "")
        self.assertIn("women", analysis["intent"]["subject"])
        self.assertIn("gown", analysis["intent"]["clothing"])
        self.assertIn("low angle", analysis["intent"]["camera"])
        changed_from = {item["from"] for item in analysis["changed_terms"]}
        self.assertIn("young East Asian women", changed_from)
        self.assertIn("seductive pose", changed_from)
        self.assertIn("revealing cleavage", changed_from)
        self.assertIn("see-through", changed_from)
        self.assertIn("readable random text", changed_from)
        self.assertIn("clearly adult East Asian women", analysis["rewritten_seed"])
        self.assertTrue(any("低机位" in warning or "风险分" in warning for warning in analysis["warnings"]))

    def test_prompt_adapter_respects_negative_safety_constraints(self):
        prompt = (
            "从《赘婿》小说中选取一位明确成年的女性角色，生成全身像壁纸；"
            "服饰为角色自身服饰风格，搭配现代高跟鞋与不透明连裤袜。"
            "动漫角色 cosplay 电影演员质感，偏真人定妆照风格；"
            "镜头：24-28mm 超广角，轻微低机位电影镜头，控制透视，完整构图，不形成身体局部强调，艺术透视。"
            "非露骨、无裸露、无未成年人、无水印。--ar 16:9。"
            "Safety constraints: non-explicit, no nudity, no minors, no watermark."
        )
        analysis = prompt_skill_client.analyze_prompt_adapter(prompt)

        self.assertFalse(analysis["blocked"])
        self.assertNotIn("transparent_exposure", analysis["risk_flags"])
        self.assertNotIn("nudity", analysis["risk_flags"])
        self.assertFalse(analysis["changed_terms"])
        self.assertNotIn("不叠层", analysis["rewritten_seed"])
        self.assertNotIn("控制叠层", analysis["rewritten_seed"])
        self.assertEqual(analysis["intent"]["aspect_ratio"], "16:9")
        self.assertEqual(analysis["intent"]["scene"], [])

    def test_prompt_adapter_still_blocks_positive_minor_sexual_combo(self):
        analysis = prompt_skill_client.analyze_prompt_adapter("未成年少女，性感透视衣服，低机位写真")

        self.assertTrue(analysis["blocked"])
        self.assertTrue(any("未成年" in warning for warning in analysis["warnings"]))

    def test_prompt_adapter_does_not_preblock_non_age_risks(self):
        analysis = prompt_skill_client.analyze_prompt_adapter(
            "real person nude deepfake poster with explicit sexual framing and readable random text"
        )

        self.assertFalse(analysis["blocked"])
        changed_from = {item["from"] for item in analysis["changed_terms"]}
        self.assertIn("real person nude", changed_from)
        self.assertIn("deepfake", changed_from)
        self.assertIn("explicit sexual", changed_from)
        self.assertTrue(any("安全改写" in warning or "原创角色" in warning for warning in analysis["warnings"]))

    def test_safe_rewrite_falls_back_to_local_adapter_when_provider_fails(self):
        with patch.object(prompt_skill_client, "_choose_model", return_value="gpt-5.5"), \
             patch.object(prompt_skill_client, "_call_prompt_provider", side_effect=RuntimeError("upstream down")), \
             patch.object(prompt_skill_client, "chat_chatgpt_pool", None):
            result = prompt_skill_client.safe_rewrite_prompt(
                "young women in a seductive pose with transparent dress and cleavage",
                {},
            )

        self.assertTrue(result["ok"])
        self.assertIn("[1. 画布]", result["zh_prompt"])
        self.assertIn("[11. 约束]", result["zh_prompt"])
        self.assertIn("[1. Canvas]", result["en_prompt"])
        self.assertIn("[11. Constraints]", result["en_prompt"])
        self.assertIn("clearly adult women", result["zh_prompt"])
        self.assertIn("clearly adult women", result["en_prompt"])
        self.assertIn("Safety constraints: non-explicit, no nudity, no minors, no watermark.", result["zh_prompt"])

    def test_safe_rewrite_falls_back_to_account_pool_on_codex_failure(self):
        pool_payload = {
            "ok": True,
            "result": {
                "model": "pool-auto",
                "choices": [{"message": {"content": json.dumps({
                    "zh_prompt": "[1. 画布]\n16:9。\n\n[11. 约束]\nSafety constraints: non-explicit, no nudity, no minors, no watermark.",
                    "en_prompt": "[1. Canvas]\n16:9.\n\n[11. Constraints]\nSafety constraints: non-explicit, no nudity, no minors, no watermark.",
                }, ensure_ascii=False)}}],
            },
        }
        with patch.object(prompt_skill_client, "_choose_model", return_value="gpt-5.5"), \
             patch.object(prompt_skill_client, "_call_prompt_provider", side_effect=RuntimeError("provider down")), \
             patch.object(prompt_skill_client, "chat_chatgpt_pool", return_value=pool_payload) as pool_chat:
            result = prompt_skill_client.safe_rewrite_prompt(
                "young women in a seductive pose with transparent dress and cleavage",
                {},
            )

        pool_chat.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "chatgpt_pool")
        self.assertIn("non-explicit", result["zh_prompt"])
        self.assertIn("Safety constraints: non-explicit, no nudity, no minors, no watermark.", result["en_prompt"])
        self.assertIn("已切换 ChatGPT 账号池", result["adapter_warning"])
        self.assertTrue(result["changed_terms"])


class PromptChatFrontendTest(unittest.TestCase):
    def test_drawer_shell_and_actions_exist_without_direct_generate(self):
        html = read_text("desktop.html")
        api_js = read_text("scripts/desktop-api.js")
        drawer_js = read_text("scripts/desktop-prompt-drawer.js")
        editor_js = read_text("scripts/desktop-prompt-editor.js")
        canvas_js = read_text("scripts/desktop-canvas.js")
        bootstrap_js = read_text("scripts/desktop-bootstrap.js")

        self.assertIn('id="deskPromptDrawer"', html)
        self.assertIn("desktop-prompt-drawer.js", html)
        self.assertIn("desktop-prompt-editor.js", html)
        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-api.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-prompt-editor.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-prompt-drawer.js")
        self.assertIn("DesktopPromptDrawer?.init", bootstrap_js)
        self.assertIn("DesktopPromptEditor", editor_js)
        self.assertIn("insertAttachment", editor_js)
        self.assertIn("getAttachments", editor_js)
        self.assertIn("data-source-node-id", editor_js)
        self.assertIn("desk-prompt-editor__label", editor_js)
        self.assertIn("data-prompt-editor-remove-image", editor_js)
        self.assertIn("syncImageAttachmentsFromEditor", drawer_js)
        self.assertIn("data-candidate-action=\"copy\"", drawer_js)
        self.assertIn("data-candidate-action=\"apply-text\"", drawer_js)
        self.assertIn("data-candidate-action=\"save-style\"", drawer_js)
        self.assertIn("data-candidate-action=\"toggle\"", drawer_js)
        self.assertIn("data-prompt-create-text", drawer_js)
        self.assertIn("setPromptDrawerHandleEyesOffset", drawer_js)
        self.assertIn("resetPromptDrawerHandleEyes", drawer_js)
        self.assertIn("updatePromptDrawerHandleEyes", drawer_js)
        self.assertIn("document.addEventListener('pointermove', updatePromptDrawerHandleEyes", drawer_js)
        self.assertIn("els.deskPromptDrawerToggle?.addEventListener('focus', resetPromptDrawerHandleEyes)", drawer_js)
        self.assertIn('id="deskPromptChatExpand"', html)
        self.assertIn('id="deskPromptVersionsExpand"', html)
        self.assertIn('id="deskPromptModal"', html)
        self.assertIn('class="desk-prompt-modal__backdrop" aria-hidden="true"', html)
        self.assertIn('id="deskPromptModalClose" data-prompt-modal-close', html)
        self.assertNotIn('class="desk-prompt-modal__backdrop" data-prompt-modal-close', html)

        self.assertIn("openModal('chat')", drawer_js)
        self.assertIn("openModal('versions')", drawer_js)
        self.assertIn("modalChatHtml", drawer_js)
        self.assertIn("modalCandidatesHtml", drawer_js)
        self.assertIn("forceExpanded", drawer_js)
        self.assertIn("deskPromptModalContent", drawer_js)
        self.assertNotIn("event.key === 'Escape' && state.modalMode", drawer_js)
        self.assertIn("promptAssistantChat", api_js)
        self.assertIn("promptAssistantChatStream", api_js)
        self.assertIn("/api/prompt/assistant-chat/stream", api_js)
        self.assertIn("resp.body.getReader", api_js)
        self.assertIn("new TextDecoder", api_js)
        self.assertIn("handlers.onDelta", api_js)
        self.assertIn("DesktopApi.promptAssistantChatStream", drawer_js)
        self.assertIn("enqueueAssistantTyping", drawer_js)
        self.assertIn("appendAssistantStreamText", drawer_js)
        self.assertIn("waitAssistantTypingIdle", drawer_js)
        self.assertIn("data-prompt-message-index", drawer_js)
        self.assertIn("streaming: true", drawer_js)
        self.assertIn("DesktopApi.promptAssistantChat(payload)", drawer_js)
        self.assertIn("analyzePromptImage", api_js)
        self.assertIn("/api/prompt/image-analysis", api_js)
        self.assertIn("DesktopApi.analyzePromptImage", drawer_js)
        self.assertIn("function submitImageAnalysis", drawer_js)
        self.assertIn("normalizeAnalysisResult", drawer_js)
        self.assertIn("state.expandedCandidateId = first ? (first.id || '0') : ''", drawer_js)
        self.assertIn("listPromptImageNodes", canvas_js)
        self.assertNotIn('id="deskPromptImageUpload"', html)
        self.assertNotIn('class="desk-prompt-image-upload__button"', html)
        self.assertNotIn('id="deskPromptImageInput"', html)
        self.assertNotIn("deskPromptImageUpload", drawer_js)
        self.assertNotIn("deskPromptImageInput", drawer_js)
        self.assertIn('id="deskPromptImageAnalysisToggle"', html)
        self.assertNotIn('id="deskPromptInputTokens"', html)
        self.assertIn('class="desk-prompt-editor"', html)
        self.assertIn('contenteditable="true"', html)
        self.assertIn('id="deskPromptImageMenu"', html)
        self.assertIn("data-prompt-pick-image-node", drawer_js)
        self.assertIn("保留图中文字", drawer_js)
        self.assertIn("data-analysis-ocr-text", drawer_js)
        self.assertIn("textRegions: []", drawer_js)
        self.assertIn("function textRegionPlacementPrompt", drawer_js)
        self.assertIn("parseEditedTextRegions(state.ocrText, state.textRegions)", drawer_js)
        self.assertIn("严格按以下文字槽位映射", drawer_js)
        self.assertIn("文字内容：", drawer_js)
        self.assertIn("function textBaseForKeepText", drawer_js)
        self.assertIn("formatTextRegionsForEditor(state.textRegions", drawer_js)
        self.assertIn("safeRewritePrompt", api_js)
        self.assertIn("/api/prompt/safe-rewrite", api_js)
        self.assertIn("DesktopApi.safeRewritePrompt", drawer_js)
        self.assertIn("function generateSafeRewrite", drawer_js)
        self.assertIn("generateSafeRewriteForTextNode", drawer_js)
        self.assertIn("result.candidates", drawer_js)
        self.assertIn("candidates.slice().reverse().forEach(candidate => prependCandidate(candidate))", drawer_js)
        self.assertIn("已生成安全审核版中文和英文提示词", drawer_js)
        self.assertIn("candidateAdapterMetaHtml", drawer_js)
        self.assertIn("intent: candidate.intent", drawer_js)
        self.assertIn("language: candidate.language", drawer_js)
        self.assertIn("risk_score", drawer_js)
        self.assertIn("changed_terms", drawer_js)
        self.assertIn("generatePromptVersions", api_js)
        self.assertIn("extractStylePreset", api_js)
        self.assertIn("savePromptVersion", api_js)
        self.assertIn("saveStylePreset", api_js)
        self.assertIn("registerTextStylePresets", canvas_js)
        self.assertIn("applyTextStylePresetToTarget", canvas_js)
        self.assertIn("请先选择文本节点", canvas_js)
        self.assertIn("event.target.closest('.desk-node--text, #deskPromptDrawer')", canvas_js)
        self.assertIn("boundTextNodeId: ''", drawer_js)
        self.assertIn("desktop:canvas-selection-change", canvas_js)
        self.assertIn("desktop:canvas-selection-change", drawer_js)
        self.assertIn("getPromptTargetInfo?.(state.boundTextNodeId)", drawer_js)
        self.assertNotIn("preserveSession", drawer_js)
        self.assertNotIn("changed &&", drawer_js)
        bind_body = re.search(r"function bindTextNode\(nodeId\)\s*\{(?P<body>.*?)\n  \}", drawer_js, re.S).group("body")
        self.assertNotIn("state.messages = []", bind_body)
        self.assertNotIn("state.candidates = []", bind_body)
        removed_body = re.search(r"desktop:canvas-node-removed', event => \{(?P<body>.*?)\n    \}\);", drawer_js, re.S).group("body")
        self.assertNotIn("state.messages = []", removed_body)
        self.assertNotIn("state.candidates = []", removed_body)
        render_messages_body = re.search(r"function renderMessages\(\)\s*\{(?P<body>.*?)\n  \}", drawer_js, re.S).group("body")
        self.assertLess(render_messages_body.index("if (state.messages.length)"), render_messages_body.index("if (!hasTextTarget())"))
        render_candidates_body = re.search(r"function renderCandidates\(\)\s*\{(?P<body>.*?)\n  \}", drawer_js, re.S).group("body")
        self.assertLess(render_candidates_body.index("if (state.candidates.length)"), render_candidates_body.index("if (!hasTextTarget())"))
        get_target_body = re.search(r"function getTarget\(\)\s*\{(?P<body>.*?)\n  \}", drawer_js, re.S).group("body")
        self.assertNotIn("state.boundTextNodeId = target.nodeId;", get_target_body)
        self.assertIn("function candidateTextForTextNode(candidate = {})", drawer_js)
        self.assertIn("state.imageAnalysis?.prompt_blocks?.negative_prompt", drawer_js)
        self.assertIn("const textForNode = candidateTextForTextNode(candidate);", drawer_js)
        self.assertIn("fillPromptTarget?.(textForNode, { target: getTarget() })", drawer_js)
        self.assertIn("createTextNodeWithText?.(textForNode)", drawer_js)
        self.assertNotIn('id="deskPromptDrawerPin"', html)
        self.assertNotIn('id="deskPromptDrawerClose"', html)
        self.assertNotIn('id="deskPromptStyleStrip"', html)
        self.assertNotIn("deskPromptDrawerPin", drawer_js)
        self.assertNotIn("deskPromptDrawerClose", drawer_js)
        self.assertNotIn("deskPromptStyleStrip", drawer_js)
        self.assertNotIn("pinned:", drawer_js)
        self.assertNotIn("selectedStyleId", drawer_js)
        self.assertNotIn("document.addEventListener('click'", drawer_js)
        self.assertIn("deskPromptDrawerToggle?.addEventListener('click', () => setOpen(!state.open))", drawer_js)
        self.assertIn("globalThis.crypto?.randomUUID?.()?.replaceAll", canvas_js)
        self.assertIn('id="deskPromptNodeSelect"', html)
        self.assertIn("listTextNodes", canvas_js)
        self.assertIn("data-text-node-alias", canvas_js)
        self.assertIn("data-text-node-alias-edit", canvas_js)
        self.assertIn("readonly tabindex=\"-1\"", canvas_js)
        self.assertIn("textNodeAliasStyle(alias)", canvas_js)
        self.assertIn("commitTextNodeAliasInput", canvas_js)
        self.assertIn("setTextNodeAliasEditing", canvas_js)
        self.assertIn("sanitizeTextNodeAlias", canvas_js)
        self.assertIn("desktop:canvas-text-nodes-change", drawer_js)
        self.assertIn("选择文本节点", html)
        self.assertIn('class="desk-prompt-drawer__control-row"', html)
        self.assertIn('id="deskPromptDrawerClear" aria-label="清空提示词助手" title="清空">清空</button>', html)
        self.assertNotIn("已绑定：", html)
        self.assertNotIn("已绑定：", drawer_js)
        self.assertIn("安全审核版", canvas_js)
        self.assertIn('data-text-action="safe-rewrite"', canvas_js)
        self.assertNotIn("deskPromptSafeRewrite", html)
        self.assertNotIn("safety_review", drawer_js)
        self.assertNotIn("更电影感", drawer_js)
        self.assertNotIn("更产品感", drawer_js)
        self.assertNotIn("英文投喂", drawer_js)
        self.assertNotIn("增强风格", drawer_js)
        self.assertNotIn("更简洁", drawer_js)
        self.assertIn("id=\"deskPromptGenerateVersions\"", html)
        self.assertIn(">发送</button>", html)
        self.assertIn(">生成版本</button>", html)
        self.assertIn("<strong>分析结果</strong>", html)
        self.assertNotIn("<strong>讨论</strong>", html)
        self.assertIn('<option value="web_search">联网检索</option>', html)
        self.assertIn("{ value: 'web_search', label: '联网检索' }", canvas_js)
        self.assertNotIn("data-style-action=", drawer_js)
        self.assertNotIn("直接生成", html)
        self.assertNotIn("发送到模型节点", drawer_js)
        self.assertNotIn("data-candidate-action=\"send-input\"", drawer_js)
        self.assertNotIn("data-candidate-action=\"new-text\"", drawer_js)
        self.assertNotIn("submitTaskConfig", drawer_js)
        self.assertNotIn("submitAndTrack", drawer_js)

    def test_canvas_delete_key_and_detach_connection_hooks_exist(self):
        canvas_js = read_text("scripts/desktop-canvas.js")

        self.assertIn("function handleCanvasDeleteKeydown(event)", canvas_js)
        self.assertIn("document.addEventListener('keydown', handleCanvasDeleteKeydown, true)", canvas_js)
        self.assertIn("function startConnectionDetachDrag(event, button)", canvas_js)
        self.assertIn("getDetachableIncomingEdge(detachPortButton.dataset.nodeId)", canvas_js)
        self.assertIn("removeEdgesById([edge.id], { quiet: true })", canvas_js)

    def test_drawer_uses_compact_center_handle_and_mid_panel(self):
        html = read_text("desktop.html")
        css = read_text("styles/desktop-liquid.css")
        canvas_js = read_text("scripts/desktop-canvas.js")

        self.assertIn('aria-label="展开或收起提示词助手"', html)
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertIn(".desk-prompt-candidate__meta", css)
        self.assertIn("desk-history-windchime__cap", html)
        self.assertIn("--desk-radius: 4px;", css)
        self.assertIn("--desk-radius-lg: 7px;", css)
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*top:\s*0;[^}]*left:\s*0;[^}]*right:\s*0;[^}]*height:\s*36px;")
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*z-index:\s*20;")
        self.assertRegex(css, r"\.desk-titlebar::before,\s*\n\.desk-bottombar::before\s*\{[^}]*display:\s*none;[^}]*content:\s*none;[^}]*pointer-events:\s*none;")
        self.assertRegex(css, r"\.desk-titlebar::before\s*\{[^}]*height:\s*0;[^}]*background:\s*transparent;")
        self.assertRegex(css, r"\.desk-bottombar::before\s*\{[^}]*height:\s*0;[^}]*background:\s*transparent;")
        self.assertRegex(css, r"\.desk-canvas\s*\{[^}]*inset:\s*34px\s*0\s*34px\s*0;[^}]*border-radius:\s*0;")
        self.assertRegex(css, r"\.desk-canvas\s*\{[^}]*linear-gradient\(to bottom,\s*rgba\(31,\s*45,\s*62,\s*0\.12\),\s*rgba\(31,\s*45,\s*62,\s*0\)\s*18px\)")
        self.assertRegex(css, r"\.desk-canvas\s*\{[^}]*linear-gradient\(to top,\s*rgba\(31,\s*45,\s*62,\s*0\.12\),\s*rgba\(31,\s*45,\s*62,\s*0\)\s*18px\)")
        self.assertRegex(css, r"\.desk-canvas\s*\{[^}]*background-repeat:\s*repeat,\s*repeat,\s*no-repeat,\s*no-repeat;")
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*height:\s*36px;[^}]*background:\s*transparent;")
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*border:\s*0;")
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*box-shadow:\s*none;")
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*backdrop-filter:\s*none;")
        self.assertRegex(css, r"\.desk-titlebar\s*\{[^}]*border-radius:\s*0;")
        self.assertRegex(css, r"\.desk-rail\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.28\);")
        self.assertRegex(css, r"\.desk-rail\s*\{[^}]*backdrop-filter:\s*blur\(22px\)\s*saturate\(1\.35\);")
        self.assertRegex(css, r"\.desk-bottombar\s*\{[^}]*right:\s*0;[^}]*bottom:\s*0;[^}]*left:\s*0;[^}]*height:\s*34px;")
        self.assertRegex(css, r"\.desk-history\s*\{[^}]*top:\s*36px;[^}]*right:\s*0;[^}]*z-index:\s*11;")
        self.assertRegex(css, r"\.desk-history\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.3\);")
        self.assertNotIn('id="deskRefreshHistoryBtn"', html)
        self.assertIn('class="desk-history__rail desk-history-windchime-button desk-history-windchime-button--hang"', html)
        self.assertIn('class="desk-history__collapse desk-history-windchime-button desk-history-windchime-button--dock"', html)
        self.assertIn('aria-label="展开最近记录"', html)
        self.assertIn('aria-label="收回历史"', html)
        self.assertIn("desk-history-windchime__cord", html)
        self.assertIn("desk-history-windchime__bell", html)
        self.assertIn("desk-history-windchime__clapper", html)
        self.assertIn("desk-history-windchime__sail", html)
        self.assertIn('id="deskHistoryGenieCanvas"', html)
        self.assertRegex(css, r"\.desk-history\.is-collapsed\s*\{[^}]*top:\s*24px;[^}]*right:\s*18px;[^}]*bottom:\s*auto;[^}]*z-index:\s*19;[^}]*width:\s*52px;[^}]*height:\s*72px;")
        self.assertRegex(css, r"\.desk-history\.is-collapsed\s*\{[^}]*transform:\s*translate3d\(0,\s*0,\s*0\);")
        self.assertRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*clip-path:\s*none;")
        self.assertRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*border-radius:\s*999px;")
        self.assertRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*color:\s*var\(--desk-jewel\);")
        self.assertRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*background:\s*transparent;")
        self.assertRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*border:\s*0;")
        self.assertNotRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.46\);")
        self.assertNotRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail\s*\{[^}]*background:\s*rgba\(80,\s*169,\s*255,\s*0\.16\);")
        self.assertRegex(css, r"\.desk-history\.is-collapsed \.desk-history__rail::before\s*\{[^}]*display:\s*none;")
        self.assertRegex(css, r"\.desk-history-windchime-button--hang \.desk-history-windchime\s*\{[^}]*animation:\s*desk-windchime-sway\s*4\.6s")
        self.assertRegex(css, r"\.desk-history-windchime-button--hang \.desk-history-windchime__body\s*\{[^}]*animation:\s*desk-windchime-dangle\s*3\.7s")
        self.assertRegex(css, r"\.desk-history-windchime-button--hang \.desk-history-windchime__sail\s*\{[^}]*animation:\s*desk-windchime-sail\s*2\.9s")
        self.assertRegex(css, r"\.desk-history-windchime-button--dock \.desk-history-windchime\s*\{[^}]*animation:\s*desk-windchime-dock-in\s*360ms")
        self.assertRegex(css, r"\.desk-history:not\(\.is-collapsed\)\s*\{[^}]*animation:\s*none;")
        self.assertRegex(css, r"\.desk-history\.is-genie-closing,\s*\n\.desk-history\.is-genie-materializing\s*\{[^}]*opacity:\s*0;[^}]*transition:\s*none;[^}]*animation:\s*none;")
        self.assertRegex(css, r"\.desk-history-genie-canvas\s*\{[^}]*position:\s*fixed;[^}]*inset:\s*0;[^}]*z-index:\s*18;")
        self.assertRegex(css, r"\.desk-history-genie-canvas\.is-active\s*\{[^}]*opacity:\s*1;[^}]*visibility:\s*visible;")
        self.assertNotIn("@keyframes desk-history-genie-open", css)
        self.assertNotIn("@keyframes desk-history-genie-close", css)
        self.assertIn("contain: paint;", css)
        self.assertIn("will-change: transform, opacity;", css)
        self.assertNotIn("\n    filter: blur(8px);", css)
        self.assertNotIn("clip-path: polygon(82% 0, 100% 0, 100% 100%, 70% 100%)", css)
        self.assertIn("@keyframes desk-windchime-sway", css)
        self.assertIn("@keyframes desk-windchime-dangle", css)
        self.assertIn("@keyframes desk-windchime-sail", css)
        self.assertIn("@keyframes desk-windchime-dock-in", css)
        self.assertNotRegex(html, r"deskHistoryExpandBtn[^>]*title=")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*left:\s*50%;")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*bottom:\s*35px;")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*width:\s*87px;")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*font-size:\s*12px;")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*background:\s*transparent;")
        self.assertRegex(css, r"body\.desk-app\s*\{[^}]*--desk-jewel:\s*#06346f;")
        self.assertRegex(css, r"body\.desk-app\s*\{[^}]*--desk-jewel-top:\s*#0b58a8;")
        self.assertRegex(css, r"body\.desk-app\s*\{[^}]*--desk-jewel-bottom:\s*#021f4f;")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*--desk-prompt-jewel:\s*var\(--desk-jewel\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*--desk-prompt-jewel-top:\s*var\(--desk-jewel-top\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\s*\{[^}]*--desk-prompt-jewel-bottom:\s*var\(--desk-jewel-bottom\);")
        self.assertRegex(css, r"\.desk-history-windchime__cap\s*\{[^}]*background:\s*var\(--desk-jewel-gradient\);")
        self.assertRegex(css, r"\.desk-history-windchime__bell\s*\{[^}]*linear-gradient\(145deg,\s*var\(--desk-jewel-top\),\s*var\(--desk-jewel-bottom\)\)")
        self.assertRegex(css, r"\.desk-history-windchime__sail\s*\{[^}]*linear-gradient\(180deg,\s*var\(--desk-jewel-hover-top\),\s*var\(--desk-jewel-bottom\)\)")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open\s*\{[^}]*width:\s*clamp\(570px,\s*48vw,\s*960px\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open\s*\{[^}]*height:\s*min\(270px,\s*calc\(75vh\s*-\s*99px\)\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open\s*\{[^}]*bottom:\s*35px;")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle\s*\{[^}]*border-radius:\s*999px;")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle\s*\{[^}]*color:\s*#ffffff;")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle\s*\{[^}]*linear-gradient\(180deg,\s*var\(--desk-prompt-jewel-top\),\s*var\(--desk-prompt-jewel-bottom\)\)")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle::before\s*\{[^}]*background:\s*rgba\(212,\s*235,\s*255,\s*0\.86\);")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle-eye\s*\{[^}]*top:\s*calc\(50% - 4px\);[^}]*width:\s*4px;[^}]*height:\s*4px;[^}]*opacity:\s*0;")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle-eye--left\s*\{[^}]*left:\s*calc\(50% - 15px\);")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle-eye--right\s*\{[^}]*left:\s*calc\(50% \+ 11px\);")
        self.assertRegex(css, r"\.desk-prompt-drawer.is-open \.desk-prompt-drawer__handle::before\s*\{[^}]*opacity:\s*0;[^}]*transform:\s*scaleX\(0\.42\);")
        self.assertRegex(css, r"\.desk-prompt-drawer.is-open \.desk-prompt-drawer__handle-eye\s*\{[^}]*opacity:\s*1;")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle:hover\s*\{[^}]*transform:\s*translateX\(-50%\)\s*translateY\(-3px\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open \.desk-prompt-drawer__handle:hover\s*\{[^}]*translateX\(-50%\)\s*translateY\(-2px\)")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle > span:not\(\.desk-prompt-drawer__handle-eye\),\s*\n\.desk-prompt-drawer__handle em\s*\{[^}]*clip:\s*rect")
        self.assertRegex(css, r"\.desk-canvas\s*\{[^}]*background-size:\s*[^}]*var\(--canvas-grid-size,\s*20px\)\s*var\(--canvas-grid-size,\s*20px\),[^}]*100%\s*18px,[^}]*100%\s*18px;")
        self.assertIn("const gridSize = 20 * canvas.scale;", canvas_js)
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*overflow:\s*hidden;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*grid-template-rows:\s*30px\s*minmax\(0,\s*1fr\);")
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*background:\s*[^}]*linear-gradient\(158deg,[^}]*rgba\(255,\s*255,\s*255,\s*0\.14\);")
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*border:\s*0;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*backdrop-filter:\s*blur\(30px\)\s*saturate\(1\.9\)\s*brightness\(1\.05\);")
        self.assertRegex(css, r"\.desk-prompt-drawer__body::before\s*\{[^}]*display:\s*block;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body::before\s*\{[^}]*padding:\s*1\.5px;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body::before\s*\{[^}]*mask-composite:\s*exclude;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body::after\s*\{[^}]*display:\s*none;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body > \*\s*\{[^}]*z-index:\s*2;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*filter:\s*blur\(10px\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open \.desk-prompt-drawer__body\s*\{[^}]*filter:\s*none;")
        self.assertRegex(css, r"\.desk-prompt-drawer__body\s*\{[^}]*scaleX\(0\.16\)\s*scaleY\(0\.08\)")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open \.desk-prompt-drawer__body\s*\{[^}]*scaleX\(1\)\s*scaleY\(1\)")
        self.assertRegex(css, r"\.desk-prompt-drawer button:not\(\.desk-prompt-drawer__handle\)\s*\{[^}]*min-height:\s*20px;")
        self.assertRegex(css, r"\.desk-prompt-drawer button:not\(\.desk-prompt-drawer__handle\)\s*\{[^}]*font-size:\s*8px;")
        self.assertRegex(css, r"\.desk-prompt-drawer button:not\(\.desk-prompt-drawer__handle\)\s*\{[^}]*color:\s*#ffffff;")
        self.assertRegex(css, r"\.desk-prompt-drawer button:not\(\.desk-prompt-drawer__handle\)\s*\{[^}]*background:\s*linear-gradient\(180deg,\s*var\(--desk-prompt-jewel-top\),\s*var\(--desk-prompt-jewel-bottom\)\);")
        self.assertRegex(css, r"\.desk-prompt-drawer button:not\(\.desk-prompt-drawer__handle\)\s*\{[^}]*border:\s*1px\s*solid\s*var\(--desk-prompt-jewel-border\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open button:not\(\.desk-prompt-drawer__handle\):not\(:disabled\)\s*\{[^}]*background:\s*linear-gradient\(180deg,\s*var\(--desk-prompt-jewel-top\),\s*var\(--desk-prompt-jewel-bottom\)\);")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open button:not\(\.desk-prompt-drawer__handle\):disabled\s*\{[^}]*background:\s*linear-gradient\(180deg,\s*rgba\(6,\s*52,\s*111,\s*0\.36\),\s*var\(--desk-prompt-jewel-disabled\)\);")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-prompt-drawer\s*\{[^}]*--desk-prompt-jewel-top:\s*#ff6a22;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-prompt-drawer\s*\{[^}]*--desk-prompt-jewel-bottom:\s*#b93312;")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-prompt-drawer__body,\s*\nbody\.desk-app\[data-theme=\"dark\"\] \.desk-prompt-drawer\.is-open \.desk-prompt-drawer__body\s*\{[^}]*rgba\(48,\s*56,\s*58,\s*0\.86\)")
        self.assertRegex(css, r"body\.desk-app\[data-theme=\"dark\"\] \.desk-prompt-drawer__handle\s*\{[^}]*background:\s*[^}]*linear-gradient\(180deg,\s*rgba\(48,\s*56,\s*58,\s*0\.96\),\s*rgba\(31,\s*37,\s*39,\s*0\.98\)\)")
        self.assertRegex(css, r"\.desk-text-node__alias\s*\{[^}]*position:\s*absolute;[^}]*top:\s*-26px;[^}]*left:\s*8px;")
        self.assertRegex(css, r"\.desk-text-node__alias\s*\{[^}]*width:\s*min\(calc\(var\(--text-node-alias-ch,\s*6ch\)\s*\+\s*39px\),\s*calc\(100%\s*-\s*16px\)\);")
        self.assertRegex(css, r"\.desk-text-node__alias input\s*\{[^}]*width:\s*0;[^}]*min-width:\s*38px;")
        self.assertRegex(css, r"\.desk-text-node__alias button\s*\{[^}]*width:\s*20px;[^}]*height:\s*20px;")
        self.assertRegex(css, r"\.desk-text-node__alias input\s*\{[^}]*border-radius:\s*4px;")
        self.assertRegex(css, r"\.desk-prompt-node-picker select\s*\{[^}]*border-radius:\s*4px;")
        self.assertRegex(css, r"\.desk-prompt-drawer__grid\s*\{[^}]*grid-template-columns:\s*minmax\(210px,\s*0\.82fr\)\s*minmax\(270px,\s*1\.18fr\);")
        self.assertRegex(css, r"\.desk-prompt-chat,\s*\n\.desk-prompt-candidates\s*\{[^}]*background:\s*transparent;")
        self.assertRegex(css, r"\.desk-prompt-chat\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)\s*auto;")
        self.assertRegex(css, r"\.desk-prompt-chat\s*\{[^}]*border:\s*1px\s*solid\s*rgba\(92,\s*112,\s*132,\s*0\.16\);")
        self.assertRegex(css, r"\.desk-prompt-expand-btn\s*\{[^}]*width:\s*20px;")
        self.assertRegex(css, r"\.desk-prompt-drawer button\.desk-prompt-expand-btn\s*\{[^}]*display:\s*grid;")
        self.assertRegex(css, r"\.desk-prompt-drawer button\.desk-prompt-expand-btn\s*\{[^}]*padding:\s*0;")
        self.assertIn('class="desk-icon desk-icon--expand"', html)
        self.assertIn('class="desk-icon desk-icon--close"', html)
        self.assertIn('url("../assets/icons/expand-diagonal.svg")', css)
        self.assertIn('url("../assets/icons/close.svg")', css)
        self.assertNotIn("M15 3h6v6", html)
        self.assertRegex(css, r"\.desk-prompt-modal\s*\{[^}]*pointer-events:\s*none;")
        self.assertRegex(css, r"\.desk-prompt-modal__backdrop\s*\{[^}]*background:\s*transparent;")
        self.assertRegex(css, r"\.desk-prompt-modal__backdrop\s*\{[^}]*backdrop-filter:\s*none;")
        self.assertRegex(css, r"\.desk-prompt-modal__backdrop\s*\{[^}]*pointer-events:\s*none;")
        self.assertRegex(css, r"\.desk-prompt-modal__panel\s*\{[^}]*backdrop-filter:\s*blur\(6px\)\s*saturate\(1\.08\);")
        self.assertRegex(css, r"\.desk-prompt-modal__panel\s*\{[^}]*pointer-events:\s*auto;")
        self.assertRegex(css, r"\.desk-prompt-modal__panel\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;")
        self.assertRegex(css, r"\.desk-prompt-modal__panel\s*\{[^}]*isolation:\s*isolate;")
        self.assertRegex(css, r"\.desk-prompt-modal__panel\s*\{[^}]*max-height:\s*calc\(100dvh\s*-\s*96px\);")
        self.assertRegex(css, r"\.desk-prompt-modal__head\s*\{[^}]*position:\s*relative;[^}]*z-index:\s*2;")
        self.assertRegex(css, r"\.desk-prompt-modal__head\s*\{[^}]*rgba\(242,\s*249,\s*253,\s*0\.96\);")
        self.assertRegex(css, r"\.desk-prompt-modal__content\s*\{[^}]*flex:\s*1\s*1\s*auto;[^}]*overflow:\s*auto;")
        self.assertRegex(css, r"\.desk-prompt-modal__content \.desk-prompt-candidate p\s*\{[^}]*max-height:\s*min\(260px,\s*32dvh\);[^}]*overflow:\s*auto;")
        self.assertRegex(css, r"\.desk-prompt-modal__content \.desk-prompt-analysis-editor\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*max-height:\s*min\(300px,\s*38dvh\);[^}]*overflow:\s*hidden;")
        self.assertRegex(css, r"\.desk-prompt-modal__content \.desk-prompt-analysis-editor textarea\s*\{[^}]*flex:\s*1\s*1\s*auto;[^}]*max-height:\s*min\(220px,\s*24dvh\);[^}]*overflow:\s*auto;")
        self.assertRegex(css, r"\.desk-prompt-modal__content \.desk-prompt-analysis-module p,\s*\n\.desk-prompt-modal__content \.desk-prompt-analysis-module pre\s*\{[^}]*max-height:\s*min\(240px,\s*30dvh\);")
        self.assertRegex(css, r"\.desk-prompt-modal__content \.desk-prompt-analysis-module\.is-json\s*\{[^}]*max-height:\s*min\(360px,\s*42dvh\);")
        self.assertRegex(css, r"\.desk-prompt-modal__content \.desk-prompt-analysis-module\.is-json pre\s*\{[^}]*max-height:\s*none;")
        self.assertRegex(css, r"\.desk-prompt-modal__head button\s*\{[^}]*background:\s*linear-gradient\(180deg,\s*var\(--desk-prompt-jewel-top,\s*#0b58a8\),\s*var\(--desk-prompt-jewel-bottom,\s*#021f4f\)\);")
        self.assertRegex(css, r"\.desk-prompt-modal__content button\s*\{[^}]*font-size:\s*10px;")
        self.assertRegex(css, r"\.desk-prompt-modal__content button\s*\{[^}]*background:\s*linear-gradient\(180deg,\s*var\(--desk-prompt-jewel-top,\s*#0b58a8\),\s*var\(--desk-prompt-jewel-bottom,\s*#021f4f\)\);")
        self.assertRegex(css, r"\.desk-prompt-modal__content button\s*\{[^}]*border:\s*1px\s*solid\s*var\(--desk-prompt-jewel-border,\s*rgba\(126,\s*189,\s*255,\s*0\.44\)\);")
        self.assertRegex(css, r"\.desk-prompt-chat__message p,\s*\n\.desk-prompt-candidate p\s*\{[^}]*font-size:\s*8px;")
        self.assertRegex(css, r"\.desk-prompt-chat__input\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*78px;")
        self.assertRegex(css, r"\.desk-prompt-drawer__control-row\s*\{[^}]*display:\s*flex;")
        self.assertRegex(css, r"#deskPromptDrawerClear\s*\{[^}]*min-width:\s*42px;")
        self.assertRegex(css, r"\.desk-text-node__drawer button\[data-text-action=\"clear\"\]\s*\{[^}]*flex:\s*0\s*0\s*42px;")
        self.assertRegex(css, r"\.desk-prompt-image-menu button\s*\{[^}]*width:\s*60px;[^}]*height:\s*60px;")
        self.assertRegex(css, r"\.desk-prompt-image-menu\s*\{[^}]*grid-template-columns:\s*repeat\(var\(--desk-prompt-image-menu-cols,\s*1\),\s*60px\);")
        self.assertRegex(css, r"\.desk-prompt-image-menu\s*\{[^}]*width:\s*max-content;")
        self.assertRegex(css, r"\.desk-prompt-editor__image\s*\{[^}]*min-width:\s*42px;[^}]*height:\s*20px;")
        self.assertRegex(css, r"\.desk-prompt-editor__image\s*\{[^}]*border-radius:\s*999px;")
        self.assertRegex(css, r"\.desk-prompt-chat__textwrap\s*\{[^}]*min-height:\s*86px;")
        self.assertRegex(css, r"\.desk-prompt-editor\s*\{[^}]*height:\s*100%;[^}]*min-height:\s*86px;")
        self.assertRegex(css, r"\.desk-prompt-editor:empty::before\s*\{[^}]*content:\s*attr\(data-placeholder\);")
        self.assertIn(".desk-prompt-editor__image", css)
        self.assertIn(".desk-prompt-analysis-module", css)
        self.assertIn(".desk-prompt-analysis-editor", css)
        self.assertRegex(css, r"\.desk-prompt-editor\s*\{[^}]*font-size:\s*9px;")
        self.assertRegex(css, r"\.desk-prompt-editor\s*\{[^}]*border:\s*1px\s*solid\s*rgba\(92,\s*112,\s*132,\s*0\.18\);")
        self.assertRegex(css, r"\.desk-prompt-candidates\s*\{[^}]*border:\s*1px\s*solid\s*rgba\(92,\s*112,\s*132,\s*0\.16\);")
        self.assertRegex(css, r"\.desk-prompt-candidate p\s*\{[^}]*-webkit-line-clamp:\s*3;")
        self.assertRegex(css, r"\.desk-prompt-candidate\.is-expanded p\s*\{[^}]*max-height:\s*none;")
        self.assertNotIn(".desk-prompt-style-strip", css)
        self.assertRegex(css, r"\.desk-titlebar,\s*\n\.desk-rail,\s*\n\.desk-node-palette,")
        self.assertRegex(css, r"\.desk-prompt-drawer__body,\s*\n\.desk-prompt-drawer\.is-open \.desk-prompt-drawer__body\s*\{[^}]*border-radius:\s*7px;")
        self.assertRegex(css, r"\.desk-button,[^}]*\.desk-prompt-chat,[^}]*\.desk-prompt-candidate\s*\{[^}]*border-radius:\s*var\(--desk-radius\);")
        self.assertRegex(css, r"\.desk-prompt-drawer__handle\s*\{[^}]*border-radius:\s*999px;")
        self.assertRegex(css, r"@media \(max-width:\s*980px\)\s*\{[^}]*\.desk-prompt-drawer\s*\{[^}]*position:\s*fixed;")
        self.assertRegex(css, r"\.desk-prompt-drawer\.is-open\s*\{[^}]*right:\s*12px;[^}]*bottom:\s*35px;[^}]*left:\s*12px;[^}]*width:\s*auto;")


if __name__ == "__main__":
    unittest.main()
