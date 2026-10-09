"""Offline regressions for V1 video @ mentions in Prompt Assistant and Agent."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend import agent_runtime
from backend import prompt_skill_client
from backend.routes import prompt_routes
from backend.services import prompt_video


def sampled_video(frame_count: int = 12, suffix: str = "a") -> dict:
    return {
        "id": f"video-{suffix}",
        "label": "参考视频",
        "source_node_id": "video-ref",
        "duration_seconds": 8,
        "width": 1280,
        "height": 720,
        "fps": 24,
        "frames": [
            {
                "timestamp_seconds": index / 2,
                "data_url": f"data:image/jpeg;base64,{suffix}{index:02d}",
            }
            for index in range(frame_count)
        ],
    }


class Handler:
    def __init__(self, payload):
        self.payload = payload
        self.status = None
        self.response = None

    def read_json_body(self, *, max_bytes):
        self.max_bytes = max_bytes
        return self.payload

    def send_json(self, data, status=200):
        self.response = data
        self.status = status


class PromptVideoServiceTests(unittest.TestCase):
    def setUp(self):
        with prompt_video._SUMMARY_CACHE_LOCK:
            prompt_video._SUMMARY_CACHE.clear()

    def test_contract_accepts_12_to_24_frames_only(self):
        self.assertEqual(len(prompt_video.normalize_video_references([sampled_video(12)])[0]["frames"]), 12)
        self.assertEqual(len(prompt_video.normalize_video_references([sampled_video(24)])[0]["frames"]), 24)
        with self.assertRaises(ValueError):
            prompt_video.normalize_video_references([sampled_video(11)])
        with self.assertRaises(ValueError):
            prompt_video.normalize_video_references([sampled_video(25)])

    def test_24_frames_are_analyzed_in_three_bounded_batches_and_cached(self):
        call_model = Mock(side_effect=lambda prompt, system, options, images, error_label: {
            "text": f"批次含 {len(images)} 帧",
            "provider": "fixture",
            "model": "fixture-model",
        })
        video = sampled_video(24, "batch")
        first = prompt_video.summarize_video_references([video], call_model=call_model, options={})
        second = prompt_video.summarize_video_references([video], call_model=call_model, options={})

        self.assertEqual(call_model.call_count, 3)
        self.assertEqual([len(call.kwargs["images"]) for call in call_model.call_args_list], [8, 8, 8])
        self.assertEqual(first[0]["frame_count"], 24)
        self.assertEqual(first, second)

    def test_assistant_request_includes_video_summary_without_forwarding_frames(self):
        summaries = [{
            "id": "video1",
            "label": "运镜参考",
            "frame_count": 16,
            "duration_seconds": 10,
            "summary": "人物向镜头走近，镜头缓慢后移。",
        }]
        with patch.object(prompt_skill_client, "get_prompt_skill_config", return_value={"provider": "gpt_oauth", "model": "fixture"}), patch.object(prompt_skill_client, "_choose_model", return_value="fixture"):
            request = prompt_skill_client._assistant_chat_request(
                "当前提示词",
                "参考这个节奏",
                {"video_summaries": summaries},
            )

        self.assertIn("人物向镜头走近", request["prompt"])
        self.assertIn("12--24 帧", request["prompt"])
        self.assertNotIn("data:image", request["prompt"])
        self.assertEqual(request["video_summaries"], summaries)

    def test_video_analysis_route_forwards_sampled_videos(self):
        videos = [sampled_video(12, "route")]
        callback = Mock(return_value={"ok": True, "candidates": []})
        handler = Handler({"message": "分析动作", "videos": videos, "images": []})
        prompt_routes.handle_prompt_video_analysis(handler, analyze_prompt_video=callback)

        self.assertEqual(handler.status, 200)
        self.assertEqual(callback.call_args.args[1], videos)
        self.assertGreaterEqual(handler.max_bytes, 64 * 1024 * 1024)

    def test_video_analysis_returns_prompt_drawer_compatible_shape(self):
        summaries = [{
            "id": "video1",
            "label": "参考视频",
            "source_node_id": "video-ref",
            "duration_seconds": 8,
            "width": 1280,
            "height": 720,
            "fps": 24,
            "frame_count": 12,
            "batch_count": 2,
            "recommended_frame_minimum_met": True,
            "summary": "主体从左向右移动。",
            "warnings": [],
        }]
        model_json = '{"visual_summary":"单人街景","motion":"从左向右移动","camera":"固定中景","timing":"匀速","style":"冷调纪实","visible_text":"","prompt_candidate":"冷调街景，单人从左向右匀速移动，固定中景","warnings":[]}'
        with patch.object(prompt_skill_client, "summarize_video_references", return_value=summaries), patch.object(prompt_skill_client, "call_prompt_model", return_value={
            "text": model_json,
            "provider": "fixture",
            "model": "fixture-model",
            "reasoning_effort": "medium",
        }):
            result = prompt_skill_client.analyze_prompt_video("", [sampled_video(12)], {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "video")
        self.assertEqual(result["candidate"]["kind"], "video_analysis_main")
        self.assertIn("从左向右", result["candidate"]["text"])
        self.assertTrue(any(module["id"] == "motion" for module in result["modules"]))


class AgentVideoReferenceTests(unittest.TestCase):
    def image_task_context(self):
        return {
            "workflow": {
                "state": {
                    "canvas": {
                        "nodes": {
                            "input": {"id": "input", "type": "input"},
                            "video-ref": {
                                "id": "video-ref",
                                "type": "video",
                                "mediaUrl": "/api/video/reference.mp4",
                            },
                        },
                        "edges": [],
                    },
                    "params": {},
                },
            },
            "result_node_id": "input",
            "referenced_video_node_ids": ["video-ref"],
            "referenced_videos": [{
                "id": "video1",
                "label": "动作参考",
                "source_node_id": "video-ref",
                "mime_type": "video/mp4",
            }],
        }

    def test_agent_plan_analyzes_video_without_connecting_it_as_image(self):
        context = self.image_task_context()
        summary = agent_runtime.summarize_context(context)
        plan = agent_runtime.build_plan("参考视频节奏整理提示词，不生成", context, {"auto_generate": False})
        kinds = [step["kind"] for step in plan["steps"]]

        self.assertEqual(summary["referenced_video_count"], 1)
        self.assertEqual(summary["referenced_image_count"], 0)
        self.assertIn("analyze_videos", kinds)
        self.assertNotIn("analyze_images", kinds)
        self.assertNotIn("connect_nodes", kinds)

    def test_video_reference_never_substitutes_for_h3_first_frame(self):
        context = self.image_task_context()
        context["workflow"]["state"]["canvas"]["nodes"]["h3"] = {
            "id": "h3",
            "type": "video_inference",
            "provider": "minimax_h3",
        }
        context["result_node_id"] = "h3"
        summary = agent_runtime.summarize_context(context)

        self.assertEqual(summary["task_domain"], "video")
        self.assertEqual(summary["referenced_video_count"], 1)
        self.assertEqual(summary["first_frame_node_id"], "")
        with self.assertRaisesRegex(ValueError, "首帧"):
            agent_runtime.build_plan("参考视频生成 H3 视频", context, {"auto_generate": True})


if __name__ == "__main__":
    unittest.main()
