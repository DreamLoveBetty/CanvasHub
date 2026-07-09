#!/usr/bin/env python3

from __future__ import annotations

import os
import importlib
import sys
import unittest
from unittest.mock import patch

sys.modules.setdefault("prompt_skill_client", importlib.import_module("backend.prompt_skill_client"))


class PromptSkillClientTest(unittest.TestCase):
    def test_gpt_oauth_retries_transient_stream_503_with_nonstream(self):
        import prompt_skill_client as client

        calls = []

        def fake_post_responses(payload, timeout=None, transport_mode=None):
            calls.append(transport_mode)
            if len(calls) == 1:
                raise client.CodexAPIError(
                    "HTTP 503: upstream connect error or disconnect/reset before headers",
                    503,
                )
            return {"response": {"output": [{"content": [{"text": "ok"}]}]}}

        with patch.object(client, "post_responses", fake_post_responses), patch.object(
            client, "extract_text", return_value="ok"
        ), patch.object(client, "build_text_request", return_value={"input": []}), patch.object(
            client, "get_gpt_provider_config", return_value={"transport_mode": "stream_then_nonstream"}
        ), patch.object(
            client.time, "sleep"
        ):
            result = client._call_gpt_oauth("prompt", "system", "gpt-5.5", "high")

        self.assertEqual(result, "ok")
        self.assertEqual(calls[:2], ["stream_then_nonstream", "nonstream"])

    def test_gpt_oauth_applies_provider_env_without_overwriting_existing_values(self):
        import prompt_skill_client as client

        keys = [
            "CODEX_API_AUTH_FILE",
            "CODEX_API_AUTH_DIR",
            "CODEX_API_BASE",
            "GPT_IMAGE_MAIN_MODEL",
            "GPT_REASONING_EFFORT",
            "GPT_TRANSPORT_MODE",
        ]
        original = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            os.environ["CODEX_API_BASE"] = "https://existing.example"
            with patch.object(
                client,
                "get_gpt_provider_config",
                return_value={
                    "auth_file": "/tmp/auth.json",
                    "auth_dir": "/tmp/auth-dir",
                    "api_base": "https://configured.example",
                    "image_main_model": "gpt-5.5",
                    "reasoning_effort": "high",
                    "transport_mode": "stream_then_nonstream",
                },
            ), patch.object(
                client,
                "_managed_codex_prompt_env",
                return_value={},
            ):
                client._apply_gpt_oauth_env()

            self.assertEqual(os.environ["CODEX_API_AUTH_FILE"], "/tmp/auth.json")
            self.assertEqual(os.environ["CODEX_API_AUTH_DIR"], "/tmp/auth-dir")
            self.assertEqual(os.environ["CODEX_API_BASE"], "https://existing.example")
            self.assertEqual(os.environ["GPT_IMAGE_MAIN_MODEL"], "gpt-5.5")
            self.assertEqual(os.environ["GPT_REASONING_EFFORT"], "high")
            self.assertEqual(os.environ["GPT_TRANSPORT_MODE"], "stream_then_nonstream")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_gpt_oauth_prefers_managed_codex_oauth_env_when_configured(self):
        import prompt_skill_client as client

        keys = [
            "CODEX_API_AUTH_FILE",
            "CODEX_API_AUTH_DIR",
            "CODEX_API_BASE",
            "GPT_IMAGE_MAIN_MODEL",
            "GPT_REASONING_EFFORT",
            "GPT_TRANSPORT_MODE",
            "CODEX_API_AUTH_STRICT",
        ]
        original = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            with patch.object(
                client,
                "get_gpt_provider_config",
                return_value={
                    "auth_file": "/tmp/local-auth.json",
                    "auth_dir": "/tmp/local-auth-dir",
                    "api_base": "https://local.example",
                    "image_main_model": "gpt-5.5",
                    "reasoning_effort": "high",
                    "transport_mode": "stream_then_nonstream",
                },
            ), patch.object(
                client,
                "_managed_codex_prompt_env",
                return_value={
                    "CODEX_API_AUTH_FILE": "/tmp/managed-auth.json",
                    "CODEX_API_AUTH_DIR": None,
                    "CODEX_API_BASE": "https://managed.example",
                    "CODEX_API_AUTH_STRICT": "1",
                },
            ):
                client._apply_gpt_oauth_env()

            self.assertEqual(os.environ["CODEX_API_AUTH_FILE"], "/tmp/managed-auth.json")
            self.assertNotIn("CODEX_API_AUTH_DIR", os.environ)
            self.assertEqual(os.environ["CODEX_API_BASE"], "https://managed.example")
            self.assertEqual(os.environ["CODEX_API_AUTH_STRICT"], "1")
            self.assertNotIn("GPT_IMAGE_MAIN_MODEL", os.environ)
            self.assertNotIn("GPT_REASONING_EFFORT", os.environ)
            self.assertNotIn("GPT_TRANSPORT_MODE", os.environ)
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_analyze_prompt_image_normalizes_candidate_modules_and_fusion_shape(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "海报",
            "visual_summary": "一张层级清晰的小红书封面。",
            "prompt_blocks": {
                "main_prompt_no_text": "竖版封面，中心主体，柔和光影。",
                "universal_style_prompt": "清爽商业视觉，高级留白。",
                "layout_prompt": "标题区在上方，主体居中，底部信息卡。",
                "negative_prompt": "避免杂乱背景。",
                "no_text_prompt": "不要生成任何文字。"
            },
            "text_markdown": "# 原图标题\n- 卖点",
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "提取同款提示词",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["candidate"]["kind"], "image_analysis_main")
        self.assertIn("画面无可读文字", result["candidate"]["text"])
        self.assertNotIn("Do not render", result["candidate"]["text"])
        module_ids = {module["id"] for module in result["modules"]}
        self.assertNotIn("main", module_ids)
        self.assertNotIn("visual_summary", module_ids)
        self.assertNotIn("text_markdown", module_ids)
        self.assertIn("原图标题", result["analysis"]["text_markdown"])
        self.assertTrue(any(module["id"] == "layout_prompt" for module in result["modules"]))
        self.assertTrue(any(module["id"] == "placeholder_slots" for module in result["modules"]))
        self.assertTrue(any(module["id"] == "negative_prompt" for module in result["modules"]))
        self.assertFalse(any(module["id"] == "no_text_prompt" for module in result["modules"]))
        self.assertTrue(result["analysis"]["image_type_flags"]["layout_design"])
        self.assertIn("[SUBJECT_GROUP]", result["analysis"]["prompt_blocks"]["layout_prompt"])
        self.assertIn("[MAIN_TITLE]", result["analysis"]["prompt_blocks"]["layout_prompt"])
        self.assertTrue(any(slot["slot"] == "[SUBJECT_GROUP]" for slot in result["analysis"]["placeholder_slots"]))
        self.assertIn("封面", result["analysis"]["prompt_blocks"]["negative_prompt"])
        self.assertIn("options", result["fusion"])
        self.assertEqual(result["analysis"]["schema_version"], "image_prompt_analysis_v1")

    def test_analyze_prompt_image_rewrites_non_ocr_prompts_to_chinese_display(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "cover poster",
            "image_type_flags": {
                "layout_design": True,
                "cover_template": True,
                "table_card": False,
                "web_design": False,
            },
            "visual_summary": "黑白时尚杂志封面，人物肖像和蓝色选择框构成视觉焦点。",
            "subjects": [
                {
                    "name": "女性封面人物",
                    "role": "主视觉人物",
                    "visual_traits": "黑白高反差近景人像，头发遮挡部分脸部",
                    "pose": "头部微侧倾，肩颈斜向裁切，手臂抬起靠近头顶",
                    "expression": "冷静自信的时尚表情",
                    "gaze": "视线朝向镜头",
                    "body_crop": "胸像到半身裁切",
                    "outfit": "深色西装外套",
                    "placement": "画面中下部"
                }
            ],
            "overlays": [
                {
                    "id": "O1",
                    "type": "彩色局部图层与选择框",
                    "position": "画面中部偏右",
                    "appearance": "彩色人像局部矩形图层，亮蓝紫色选区边框，四角控制点",
                    "layering": "覆盖在黑白人物和网点纹理之上",
                    "relationship": "白色鼠标指针贴近右侧边缘，形成正在框选编辑的视觉效果"
                }
            ],
            "prompt_blocks": {
                "main_prompt_no_text": "Vertical fashion magazine cover poster, monochrome portrait, electric blue selection frame.",
                "universal_style_prompt": "High contrast editorial fashion, gritty print texture.",
                "layout_prompt": "Large portrait, top masthead, centered inset image frame.",
                "negative_prompt": "low quality, blurry, watermark, bad anatomy",
                "cover_template_prompt": "Magazine cover template with masthead and inset portrait.",
                "no_text_prompt": "Do not render text."
            },
            "text_markdown": "```markdown\nJULY 2029 / VOL 12\nWOMAN\n```",
            "text_regions": [
                {
                    "id": "T1",
                    "text": "JULY 2029 / VOL 12",
                    "role": "刊期信息",
                    "position": "顶部左侧",
                    "alignment": "left",
                    "size": "small",
                    "style": "细体无衬线，大写"
                },
                {
                    "id": "T2",
                    "text": "WOMAN",
                    "role": "主标题",
                    "position": "左侧中上部",
                    "alignment": "left",
                    "size": "hero",
                    "style": "粗体大写"
                }
            ],
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "按同款分析",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        blocks = result["analysis"]["prompt_blocks"]
        self.assertRegex(result["candidate"]["text"], r"[\u4e00-\u9fff]")
        self.assertNotIn("Vertical fashion", result["candidate"]["text"])
        self.assertNotIn("Do not render", result["candidate"]["text"])
        self.assertNotIn("参考图", result["candidate"]["text"])
        self.assertNotIn("原图", result["candidate"]["text"])
        self.assertNotIn("同款", result["candidate"]["text"])
        self.assertIn("黑白时尚杂志封面", result["candidate"]["text"])
        self.assertIn("头部微侧倾", result["candidate"]["text"])
        self.assertIn("手臂抬起靠近头顶", result["candidate"]["text"])
        self.assertIn("亮蓝紫色选区边框", result["candidate"]["text"])
        self.assertIn("白色鼠标指针", result["candidate"]["text"])
        self.assertEqual(result["analysis"]["subjects"][0]["pose"], "头部微侧倾，肩颈斜向裁切，手臂抬起靠近头顶")
        self.assertEqual(result["analysis"]["overlays"][0]["type"], "彩色局部图层与选择框")
        self.assertIn("提取可复用的整体视觉语言", blocks["universal_style_prompt"])
        self.assertNotIn("参考图", blocks["universal_style_prompt"])
        self.assertNotIn("原图", blocks["universal_style_prompt"])
        self.assertIn("封面", blocks["negative_prompt"])
        self.assertIn("标题区", blocks["negative_prompt"])
        self.assertIn("[SUBJECT_GROUP]", blocks["cover_template_prompt"])
        self.assertIn("[POSE_OR_EXPRESSION]", blocks["cover_template_prompt"])
        self.assertIn("[OUTFIT_STYLE]", blocks["cover_template_prompt"])
        self.assertIn("[MAIN_TITLE]", blocks["cover_template_prompt"])
        self.assertIn("[SUBTITLE]", blocks["cover_template_prompt"])
        self.assertIn("[SUBJECT_GROUP]", result["analysis"]["placeholder_slots"][0]["slot"])
        self.assertIn("T1｜刊期信息｜位置：顶部左侧", result["analysis"]["text_markdown"])
        self.assertIn("JULY 2029", result["analysis"]["text_markdown"])
        self.assertNotIn("```", result["analysis"]["text_markdown"])
        self.assertEqual(result["analysis"]["text_regions"][0]["id"], "T1")

    def test_analyze_prompt_image_preserves_legwear_and_footwear_in_outfit(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "插画",
            "visual_summary": "学院风角色立绘，人物全身展示，服饰层次清晰。",
            "subjects": [
                {
                    "name": "学院风角色",
                    "role": "主角",
                    "visual_traits": "年轻成人女性角色，浅色头发，动漫插画风格",
                    "pose": "站姿，双腿自然并拢，手臂轻放身体两侧",
                    "expression": "平静表情",
                    "gaze": "看向镜头",
                    "body_crop": "全身立绘",
                    "outfit": "深色制服外套与短裙，白色衬衫和领结",
                    "legwear": "白色连裤袜，覆盖腰部到脚尖，半哑光不透明质感",
                    "footwear": "黑色圆头玛丽珍鞋",
                    "placement": "画面中心"
                }
            ],
            "prompt_blocks": {
                "main_prompt_no_text": "学院风动漫角色全身立绘，深色制服外套与短裙，白色衬衫和领结，画面中心站姿。",
                "universal_style_prompt": "干净动漫插画线条，柔和阴影，低饱和配色。",
                "negative_prompt": "避免服饰层次缺失、腿部服饰颜色错误、鞋履变形和随机文字。",
                "no_text_prompt": "不要生成任何可读文字。"
            },
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "分析角色服饰",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "角色图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        subject = result["analysis"]["subjects"][0]
        self.assertIn("白色连裤袜", subject["outfit"])
        self.assertIn("半哑光不透明质感", subject["outfit"])
        self.assertIn("黑色圆头玛丽珍鞋", subject["outfit"])
        self.assertIn("白色连裤袜", result["candidate"]["text"])
        self.assertIn("黑色圆头玛丽珍鞋", result["candidate"]["text"])

    def test_visual_style_prompt_does_not_duplicate_scope_and_region_context(self):
        import prompt_skill_client as client

        data = {
            "visual_style": {
                "medium": "真实摄影",
                "rendering": "浅景深人像摄影，主体清晰，背景虚化",
                "style_scope": "真实摄影风格作用于整张画面",
                "subject_background_style": "人物和前景行李箱清晰，背景机场大厅散景虚化",
                "typography_style": "背景航班屏仅作为模糊发光信息块，不生成具体字符",
                "style_regions": [
                    {
                        "target": "中心偏左的人物主体",
                        "medium": "真实摄影",
                        "rendering": "高细节人像，肤色自然，面部清晰",
                        "edge_quality": "主体边缘清晰",
                        "texture": "皮肤细腻、黑色布料柔软",
                        "palette": "黑色服装、自然肤色、米色高跟鞋"
                    },
                    {
                        "target": "机场大厅背景",
                        "medium": "真实摄影",
                        "rendering": "大空间公共交通枢纽，背景人群虚化",
                        "edge_quality": "背景边缘柔化",
                        "texture": "玻璃、金属桁架、反光地面",
                        "palette": "冷灰、蓝色、白色高光"
                    },
                ],
                "palette": "冷灰蓝机场环境",
                "resolution_language": "竖幅高清商业人像摄影",
            }
        }

        style_prompt = client._format_visual_style_prompt(data)

        self.assertEqual(style_prompt.count("整体作用范围："), 1)
        self.assertEqual(style_prompt.count("主体/背景："), 1)
        self.assertEqual(style_prompt.count("区域风格："), 1)
        self.assertLessEqual(style_prompt.count("真实摄影"), 2)
        self.assertNotIn("中心偏左的人物主体：真实摄影，高细节人像", style_prompt)

    def test_analyze_prompt_image_rebuilds_polluted_visual_prompt(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "封面",
            "image_type_flags": {
                "layout_design": True,
                "cover_template": True,
                "table_card": False,
                "web_design": False,
            },
            "visual_summary": "时尚杂志封面，黑白人物肖像和蓝色选择框构成视觉焦点。",
            "prompt_blocks": {
                "main_prompt_no_text": "生成一张参考图同款图像，保留原图的顶部大标题区域和小型刊期信息区域但不生成可读文字，底部左侧可有白色条码样式占位块但不可读不可扫描，除非用户明确勾选保留图中文字。",
                "universal_style_prompt": "黑白高反差时尚封面视觉。",
                "negative_prompt": "避免标题区失衡。"
            },
            "text_regions": [
                {"id": "T1", "text": "JULY 2025 / VOI 09", "role": "刊期", "position": "顶部左侧"}
            ],
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "清理污染词",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        candidate_text = result["candidate"]["text"]
        self.assertIn("时尚杂志封面", candidate_text)
        self.assertNotIn("保留原图", candidate_text)
        self.assertNotIn("占位", candidate_text)
        self.assertNotIn("除非用户", candidate_text)
        self.assertNotIn("参考图", candidate_text)
        self.assertNotIn("原图", candidate_text)
        self.assertNotIn("同款", candidate_text)

    def test_analyze_prompt_image_filters_specialized_modules_by_detected_type(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "摄影",
            "image_type_flags": {
                "layout_design": False,
                "cover_template": False,
                "table_card": False,
                "web_design": False,
            },
            "visual_summary": "自然光下的街头人像照片。",
            "prompt_blocks": {
                "main_prompt_no_text": "自然光街头摄影，人物半身，浅景深。",
                "universal_style_prompt": "真实摄影，柔和自然光，干净肤色。",
                "layout_prompt": "模型误填的排版布局提示词，不应显示。",
                "cover_template_prompt": "模型误填的封面模板提示词，不应显示。",
                "table_card_layout_prompt": "模型误填的信息卡提示词，不应显示。",
                "web_design_style_prompt": "模型误填的网页设计提示词，不应显示。",
            },
            "warnings": [],
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "分析这张照片",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        module_ids = {module["id"] for module in result["modules"]}
        self.assertIn("universal_style_prompt", module_ids)
        self.assertIn("negative_prompt", module_ids)
        self.assertIn("full_json", module_ids)
        self.assertNotIn("layout_prompt", module_ids)
        self.assertNotIn("cover_template_prompt", module_ids)
        self.assertNotIn("table_card_layout_prompt", module_ids)
        self.assertNotIn("web_design_style_prompt", module_ids)
        self.assertFalse(result["analysis"]["image_type_flags"]["layout_design"])

    def test_analyze_prompt_image_preserves_pixel_art_rendering_style(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "像素插画封面",
            "image_type_flags": {
                "layout_design": True,
                "cover_template": True,
                "table_card": False,
                "web_design": False,
            },
            "visual_summary": "浅蓝天空下的日系便利店竖版封面插画。",
            "visual_style": {
                "medium": "像素风插画",
                "rendering": "低分辨率 pixel art，sprite/tile-like 建筑和车辆结构",
                "style_scope": "中心便利店建筑、车辆、天空背景和电线杆",
                "subject_background_style": "便利店主体、货车、背景建筑、电线和天空云层为像素风",
                "typography_style": "顶部英文标题和底部日文为平滑粗体无衬线平面字体",
                "text_style_is_pixelated": False,
                "style_regions": [
                    {
                        "target": "中心便利店建筑、货车、天空背景和电线杆",
                        "medium": "像素风插画",
                        "rendering": "低分辨率 sprite/tile-like 渲染",
                        "edge_quality": "硬边无柔化抗锯齿",
                        "texture": "方块像素颗粒和块状阴影",
                        "palette": "浅蓝、白色、橙色有限色板",
                        "notes": "不要扩散到标题和底部文字"
                    },
                    {
                        "target": "顶部英文标题和底部日文标题",
                        "medium": "平滑粗体无衬线平面字体",
                        "rendering": "干净矢量排版",
                        "edge_quality": "平滑清晰边缘",
                        "texture": "",
                        "palette": "高饱和蓝色和白色",
                        "notes": "不使用像素字体"
                    }
                ],
                "edge_quality": "硬边无柔化抗锯齿，斜线呈阶梯状",
                "texture": "方块像素颗粒和块状阴影",
                "palette": "浅蓝、白色、橙色构成的有限色板",
                "resolution_language": "低分辨率像素网格"
            },
            "generation_hints": {
                "medium": "pixel art poster",
                "palette": "limited blue-white-orange palette",
                "rendering": "crisp low-res pixel grid"
            },
            "prompt_blocks": {
                "main_prompt_no_text": "便利店主题竖版封面，蓝色天空，雪地街景，建筑居中。",
                "universal_style_prompt": "清爽日系海报视觉，明亮蓝白配色。",
                "negative_prompt": "避免风格跑偏。",
                "no_text_prompt": "不要生成任何可读文字。"
            },
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "分析这个像素风插画封面",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        candidate_text = result["candidate"]["text"]
        blocks = result["analysis"]["prompt_blocks"]
        self.assertIn("媒介与渲染", candidate_text)
        self.assertIn("像素风插画", candidate_text)
        self.assertIn("区域风格", candidate_text)
        self.assertIn("中心便利店建筑、车辆、天空背景和电线杆", candidate_text)
        self.assertIn("中心便利店建筑、货车、天空背景和电线杆", candidate_text)
        self.assertIn("方块像素", candidate_text)
        self.assertIn("阶梯状斜线", candidate_text)
        self.assertIn("有限色板", candidate_text)
        self.assertIn("文字/标题：顶部英文标题和底部日文为平滑粗体无衬线平面字体", candidate_text)
        self.assertIn("不要强制像素化", candidate_text)
        self.assertIn("平滑粗体无衬线平面字体", candidate_text)
        self.assertIn("媒介与渲染", blocks["universal_style_prompt"])
        self.assertIn("像素风插画", blocks["universal_style_prompt"])
        self.assertIn("文字/标题：顶部英文标题和底部日文为平滑粗体无衬线平面字体", blocks["universal_style_prompt"])
        self.assertIn("避免把某一区域的媒介风格错误扩散", blocks["negative_prompt"])
        self.assertIn("避免转成真实摄影", blocks["negative_prompt"])
        self.assertIn("平滑渐变", blocks["negative_prompt"])
        self.assertEqual(result["analysis"]["visual_style"]["medium"], "像素风插画")
        self.assertEqual(result["analysis"]["visual_style"]["text_style_is_pixelated"], False)
        self.assertIn("平滑粗体无衬线", result["analysis"]["visual_style"]["typography_style"])
        self.assertEqual(result["analysis"]["visual_style"]["style_regions"][0]["target"], "中心便利店建筑、货车、天空背景和电线杆")

    def test_analyze_prompt_image_preserves_generic_scoped_non_pixel_styles(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "插画海报",
            "image_type_flags": {
                "layout_design": True,
                "cover_template": True,
                "table_card": False,
                "web_design": False,
            },
            "visual_summary": "水彩背景与干净矢量标题混合的竖版旅行海报。",
            "visual_style": {
                "medium": "混合媒介海报",
                "rendering": "背景使用水彩晕染，前景图标使用扁平矢量",
                "style_scope": "背景、装饰图标和标题分别使用不同媒介",
                "subject_background_style": "天空和山脉背景为柔和水彩纸纹",
                "typography_style": "标题为干净现代无衬线矢量字体",
                "text_style_is_pixelated": False,
                "style_regions": [
                    {
                        "target": "天空和山脉背景",
                        "medium": "水彩插画",
                        "rendering": "柔和晕染和纸张纹理",
                        "edge_quality": "边缘自然扩散",
                        "texture": "轻微水彩颗粒",
                        "palette": "低饱和蓝绿",
                        "notes": "保持背景柔和"
                    },
                    {
                        "target": "标题和说明文字",
                        "medium": "现代无衬线矢量字体",
                        "rendering": "清晰平面排版",
                        "edge_quality": "锐利干净",
                        "texture": "无纹理",
                        "palette": "深蓝",
                        "notes": "不要水彩化文字"
                    }
                ],
            },
            "prompt_blocks": {
                "main_prompt_no_text": "竖版旅行海报，山脉背景，顶部标题区，留白充足。",
                "universal_style_prompt": "清爽旅行海报视觉。",
                "negative_prompt": "避免风格混乱。",
                "no_text_prompt": "不要生成任何可读文字。"
            },
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "分析这个混合媒介海报",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        candidate_text = result["candidate"]["text"]
        negative = result["analysis"]["prompt_blocks"]["negative_prompt"]
        self.assertIn("区域风格", candidate_text)
        self.assertIn("天空和山脉背景：水彩插画", candidate_text)
        self.assertIn("标题和说明文字：现代无衬线矢量字体", candidate_text)
        self.assertIn("不要水彩化文字", candidate_text)
        self.assertNotIn("像素风必须", candidate_text)
        self.assertNotIn("方块像素", candidate_text)
        self.assertIn("避免把某一区域的媒介风格错误扩散", negative)

    def test_analyze_prompt_image_keeps_matching_specialized_modules(self):
        import json
        import prompt_skill_client as client

        model_payload = {
            "image_kind": "网页截图",
            "image_type_flags": {
                "layout_design": True,
                "cover_template": False,
                "table_card": True,
                "web_design": True,
            },
            "visual_summary": "SaaS 仪表盘网页截图，包含卡片和表格。",
            "prompt_blocks": {
                "main_prompt_no_text": "现代 SaaS 仪表盘网页界面，顶部导航，数据卡片和表格区域。",
                "universal_style_prompt": "克制专业的产品界面视觉，浅色背景，清晰层级。",
                "layout_prompt": "12 栏网格，顶部导航，左侧筛选，右侧内容区。",
                "table_card_layout_prompt": "多张数据卡片加表格，字段对齐，状态标签清晰。",
                "web_design_style_prompt": "现代 SaaS dashboard UI，细线分隔，圆角卡片，低饱和蓝灰配色。",
                "negative_prompt": "避免花哨装饰和不可读文字。",
            },
            "warnings": [],
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            return_value=json.dumps(model_payload, ensure_ascii=False),
        ):
            result = client.analyze_prompt_image(
                "提取网页风格",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        module_ids = {module["id"] for module in result["modules"]}
        self.assertIn("layout_prompt", module_ids)
        self.assertIn("table_card_layout_prompt", module_ids)
        self.assertIn("web_design_style_prompt", module_ids)
        self.assertNotIn("cover_template_prompt", module_ids)
        self.assertTrue(result["analysis"]["image_type_flags"]["web_design"])
        self.assertTrue(result["analysis"]["image_type_flags"]["table_card"])
        self.assertIn("[DATA_GROUP]", result["analysis"]["prompt_blocks"]["table_card_layout_prompt"])
        self.assertIn("[NAV_ITEMS]", result["analysis"]["prompt_blocks"]["web_design_style_prompt"])

    def test_analyze_prompt_image_falls_back_to_account_pool_on_invalid_codex_token(self):
        import json
        import prompt_skill_client as client

        pool_payload = {
            "image_kind": "摄影",
            "visual_summary": "机场场景里的人像参考图。",
            "prompt_blocks": {
                "main_prompt_no_text": "真实纪实摄影风格，机场候机大厅，人物居中，柔和环境光。",
                "universal_style_prompt": "高质量纪实摄影，自然肤色，轻微 CCD 质感。",
                "layout_prompt": "竖向构图，主体位于画面中心，背景有航站楼空间层次。",
                "negative_prompt": "避免文字、水印、品牌标志。",
                "no_text_prompt": "不要生成任何可读文字。"
            },
            "warnings": []
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            side_effect=RuntimeError("HTTP 401 token_invalidated"),
        ), patch.object(
            client,
            "chat_chatgpt_pool",
            return_value={
                "ok": True,
                "result": {
                    "model": "pool-auto",
                    "choices": [{"message": {"content": json.dumps(pool_payload, ensure_ascii=False)}}],
                },
            },
        ) as pool_chat:
            result = client.analyze_prompt_image(
                "分析这张图片",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        pool_chat.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "chatgpt_pool")
        self.assertEqual(result["model"], "pool-auto")
        self.assertEqual(result["fallback"], "chatgpt_pool_multimodal_chat")
        self.assertIn("Codex OAuth 失效", result["warning"])
        self.assertIn("真实纪实摄影风格", result["candidate"]["text"])
        self.assertFalse(any(module["id"] == "layout_prompt" for module in result["modules"]))

    def test_image_analysis_normalizer_compresses_large_data_url_before_provider_calls(self):
        import base64
        from io import BytesIO

        import prompt_skill_client as client

        if client.Image is None:
            self.skipTest("Pillow unavailable")

        image = client.Image.new("RGB", (2400, 1600), (32, 64, 96))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

        with patch.object(client, "PROMPT_IMAGE_ANALYSIS_MAX_EDGE", 512), patch.object(
            client,
            "PROMPT_IMAGE_ANALYSIS_MAX_BYTES",
            256 * 1024,
        ):
            normalized = client._normalize_image_analysis_inputs(
                [{"id": "image1", "dataUrl": data_url, "label": "大图"}]
            )

        self.assertEqual(len(normalized), 1)
        compressed_url = normalized[0]["image_url"]
        self.assertTrue(compressed_url.startswith("data:image/jpeg;base64,"))
        self.assertLess(len(compressed_url), len(data_url))
        payload = compressed_url.split(",", 1)[1]
        compressed = client.Image.open(BytesIO(base64.b64decode(payload)))
        self.assertLessEqual(max(compressed.size), 512)
        self.assertEqual(normalized[0]["mime_type"], "image/jpeg")

    def test_account_pool_image_analysis_uses_short_timeout(self):
        import json
        import prompt_skill_client as client

        calls = []

        def fake_pool_chat(messages, model="", timeout_seconds=None, base64_images=None):
            calls.append(
                {
                    "timeout_seconds": timeout_seconds,
                    "base64_images": list(base64_images or []),
                }
            )
            return {
                "ok": True,
                "result": {
                    "model": "pool-auto",
                    "choices": [{"message": {"content": json.dumps({"ok": True})}}],
                },
            }

        with patch.object(client, "chat_chatgpt_pool", fake_pool_chat), patch.object(
            client,
            "PROMPT_IMAGE_ANALYSIS_POOL_TIMEOUT_SECONDS",
            90,
        ):
            content, model = client._chatgpt_pool_image_json_reply(
                "prompt",
                "system",
                ["data:image/png;base64,AAAA"],
            )

        self.assertEqual(model, "pool-auto")
        self.assertEqual(json.loads(content), {"ok": True})
        self.assertEqual(calls[0]["timeout_seconds"], 90)
        self.assertEqual(calls[0]["base64_images"], ["data:image/png;base64,AAAA"])

    def test_analyze_prompt_image_falls_back_to_account_pool_on_usage_limit(self):
        import json
        import prompt_skill_client as client

        pool_payload = {
            "image_kind": "摄影",
            "visual_summary": "自然光人像照片。",
            "prompt_blocks": {
                "main_prompt_no_text": "自然光人像摄影，人物位于画面中央，背景柔和虚化。",
                "universal_style_prompt": "真实摄影质感，自然肤色，柔和环境光。",
                "negative_prompt": "避免肤色失真、背景抢主体和随机文字。",
                "no_text_prompt": "不要生成任何可读文字。"
            },
            "warnings": []
        }
        usage_limit_error = (
            'HTTP 429: {"error":{"type":"usage_limit_reached",'
            '"message":"The usage limit has been reached"}}'
        )
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider_image_json",
            side_effect=RuntimeError(usage_limit_error),
        ), patch.object(
            client,
            "chat_chatgpt_pool",
            return_value={
                "ok": True,
                "result": {
                    "model": "pool-auto",
                    "choices": [{"message": {"content": json.dumps(pool_payload, ensure_ascii=False)}}],
                },
            },
        ) as pool_chat:
            result = client.analyze_prompt_image(
                "分析这张图片",
                [{"id": "image1", "dataUrl": "data:image/png;base64,AAAA", "label": "参考图"}],
                {"provider": "gpt_oauth", "reasoning_effort": "low"},
            )

        pool_chat.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "chatgpt_pool")
        self.assertEqual(result["model"], "pool-auto")
        self.assertEqual(result["fallback"], "chatgpt_pool_multimodal_chat")
        self.assertIn("Codex 用量受限", result["warning"])
        self.assertIn("自然光人像摄影", result["candidate"]["text"])

    def test_prompt_pool_fallback_predicate_accepts_any_codex_failure(self):
        import prompt_skill_client as client

        with patch.object(client, "chat_chatgpt_pool", object()):
            self.assertTrue(
                client._should_fallback_prompt_chat_to_pool(
                    "gpt_oauth",
                    RuntimeError("unexpected provider failure without a known marker"),
                )
            )

    def test_polish_prompt_falls_back_to_account_pool_on_codex_failure(self):
        import json
        import prompt_skill_client as client

        pool_payload = {
            "ok": True,
            "result": {
                "model": "pool-auto",
                "choices": [{"message": {"content": json.dumps({
                    "full_prompt": "雨夜城市街道，霓虹反光铺满湿润路面，主体位于画面中心，电影感低饱和蓝绿色光线，玻璃橱窗形成层次。\n\n负面约束：避免广告感、过曝、文字水印和背景抢主体。",
                    "compact_prompt": "雨夜城市街道，霓虹反光，电影感低饱和光线，湿润路面，避免广告感和水印。",
                    "modules": ["M0", "M3"],
                    "warnings": [],
                }, ensure_ascii=False)}}],
            },
        }
        with patch.object(client, "_choose_model", return_value="gpt-5.5"), patch.object(
            client,
            "_call_prompt_provider",
            side_effect=RuntimeError("provider down"),
        ), patch.object(
            client,
            "chat_chatgpt_pool",
            return_value=pool_payload,
        ) as pool_chat, patch.object(
            client,
            "MIN_FULL_PROMPT_CHARS",
            20,
        ), patch.object(
            client,
            "MIN_FULL_PROMPT_PARAGRAPHS",
            1,
        ):
            result = client.polish_prompt("雨夜城市街道", {"provider": "gpt_oauth"})

        pool_chat.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "chatgpt_pool")
        self.assertEqual(result["fallback"], "chatgpt_pool_chat")
        self.assertIn("雨夜城市街道", result["full_prompt"])


if __name__ == "__main__":
    unittest.main()
