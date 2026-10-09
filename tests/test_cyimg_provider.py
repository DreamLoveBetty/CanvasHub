"""Offline 绘栾 provider/task regression; no account, quota or network required."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from backend.provider_cyimg import _validate_public_https, normalize_catalog
from backend.services.cyimg_generation import CyimgService
from backend.services.history_format import format_history_task
from backend.services.task_tracking import _status_response_task


def catalog_fixture():
    return normalize_catalog({"configs": {
        "shizhuang": {"h5_enabled": True, "creditCost": 2, "parameters": [
            {"name_en": "prompt", "type": "text", "required": True},
            {"name_en": "image", "name": "参考图", "type": "image", "resource_count": 3},
            {"name_en": "model", "type": "custom_radio", "api_channel": ["Banana:one"],
             "options": [{"label": "图像 A", "value": "same", "extraCredit": 3}]},
            {"name_en": "model", "type": "custom_radio", "api_channel": ["Banana:two"],
             "options": [{"label": "图像 B", "value": "same", "extraCredit": 5}]},
            {"name_en": "size", "type": "custom_radio", "api_channel": ["Banana:one"],
             "options": [{"label": "方形", "value": "1:1"}]},
            {"name_en": "moderation", "type": "custom_radio", "required": True,
             "visible": False, "default": "low", "api_channel": ["Banana:one"],
             "options": [{"label": "低", "value": "low"}]},
        ]},
        "i2v": {"h5_enabled": True, "creditCost": 0, "parameters": [
            {"name_en": "prompt", "type": "text", "required": True},
            {"name_en": "image", "type": "image", "resource_count": 2, "api_channel": ["AsyncAPI:one"]},
            {"name_en": "model", "api_target": "mode", "type": "custom_radio", "api_channel": ["AsyncAPI:one"],
             "options": [{"label": "视频 A", "value": "pro", "extraCredit": 9}]},
            {"name_en": "duration", "type": "number", "default": 15, "api_channel": ["AsyncAPI:one"]},
        ]},
        "seedance": {"h5_enabled": True, "creditCost": 80, "parameters": [
            {"name_en": "model", "type": "custom_radio", "api_channel": ["Dreamina:one"],
             "options": [{"label": "2.5", "value": "2.5", "extraCredit": "180%"}]},
            {"name_en": "resolution", "type": "custom_radio", "api_channel": ["Dreamina:one"],
             "options": [{"label": "1080P", "value": "1080p", "extraCredit": "248.9%"}]},
        ]},
        "Minimax": {"h5_enabled": True, "creditCost": 5, "parameters": [
            {"name_en": "model", "type": "custom_radio", "api_channel": ["AsyncAPI:h3"],
             "options": [{"label": "H3", "value": "H3", "extraCredit": 5}]},
            {"name_en": "image", "type": "image", "required": True, "resource_count": 9,
             "api_channel": ["AsyncAPI:h3"]},
        ]},
    }})


class FakeClient:
    def __init__(self):
        self.sent = None

    def catalog(self):
        return catalog_fixture()

    def submit(self, body):
        self.sent = body
        return "img_task_remote"

    def status(self, task_id):
        assert task_id == "img_task_remote"
        return {"status": "completed", "result": "https://assets.example.test/result.png"}

    def download(self, url, max_bytes):
        return b"\x89PNG\r\n\x1a\n" + b"test", "image/png", url


class CyimgTests(unittest.TestCase):
    def test_result_url_accepts_proxy_fake_dns_but_not_private_destinations(self):
        public_url = "https://cdn.example.com/original.png"
        fake_dns = [(None, None, None, None, ("198.18.0.84", 443))]
        with patch("backend.provider_cyimg.socket.getaddrinfo", return_value=fake_dns):
            self.assertEqual(_validate_public_https(public_url), public_url)
            with self.assertRaisesRegex(ValueError, "公网 HTTPS"):
                _validate_public_https("https://198.18.0.84/original.png")
            with self.assertRaisesRegex(ValueError, "公网 HTTPS"):
                _validate_public_https("https://localhost/original.png")
        private_dns = [(None, None, None, None, ("192.168.1.12", 443))]
        with patch("backend.provider_cyimg.socket.getaddrinfo", return_value=private_dns):
            with self.assertRaisesRegex(ValueError, "公网 HTTPS"):
                _validate_public_https(public_url)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tasks = {}
        self.sent = []
        self.client = FakeClient()

        def create(task_id, prompt, params, status, task_type):
            self.tasks[task_id] = {"task_id": task_id, "prompt": prompt, "params": dict(params),
                                   "status": status, "type": task_type, "result_files": []}

        def fields(task_id, **values):
            if "params" in values:
                values["params"] = json.loads(values["params"])
            if "result_files" in values:
                values["result_files"] = json.loads(values["result_files"])
            self.tasks[task_id].update(values)

        self.service = CyimgService(get_config=lambda: {"api_key": "secret-not-public", "api_key_configured": True,
                                                        "task_timeout_seconds": 60},
            create_task=create, get_task=lambda task_id:self.tasks.get(task_id),
            get_all_tasks=lambda limit=50:list(self.tasks.values())[:limit],
            update_task=lambda task_id,status,**kwargs:fields(task_id,status=status,**kwargs),
            update_task_status=lambda task_id,status,message=None,stage=None,**kwargs:fields(task_id,status=status,
                progress_text=message,stage=stage,**kwargs),update_task_fields=fields,
            daily_output_dir=lambda:Path(self.temp.name)/"2026-09-27",
            send_document=lambda path, caption:self.sent.append((path,caption)))
        self.service._client = lambda:self.client

    def test_channel_is_part_of_identity_and_fields(self):
        catalog = catalog_fixture()["models"]
        self.assertEqual(len(catalog["image"]), 2)
        self.assertNotEqual(catalog["image"][0]["id"], catalog["image"][1]["id"])
        self.assertEqual([f["name"] for f in catalog["image"][1]["fields"]], ["image"])
        self.assertEqual(catalog["image"][0]["credit_estimate"], 5)
        self.assertNotIn("model", [field["name"] for field in catalog["video"][0]["fields"]])
        self.assertNotIn("mode", [field["name"] for field in catalog["video"][0]["fields"]])
        self.assertEqual(len(catalog["video"]), 3)
        self.assertIsNone(catalog["video"][1]["credit_estimate"])
        self.assertEqual(catalog["video"][2]["credit_estimate"], 10)

    def test_submit_uses_flattened_resource_slots_and_archives_original(self):
        first = catalog_fixture()["models"]["image"][0]
        self.service._uploads["tok1"] = ("https://cyimg.cn/upload/a.png", "image", 99999999999)
        self.service._uploads["tok2"] = ("https://cyimg.cn/upload/b.png", "image", 99999999999)
        queued = []
        self.service._spawn = lambda task_id, body: queued.append((task_id, body))
        response = self.service.submit({"kind":"image", "model_id":first["id"], "prompt":"test prompt",
            "parameters":{"size":"1:1"}, "image_upload_tokens":["tok1","tok2"],
            "telegram_enabled":True})
        task_id = response["task_id"]
        self.service.run(*queued[0])
        self.assertEqual(self.client.sent["image1"], "https://cyimg.cn/upload/a.png")
        self.assertNotIn("image", self.client.sent)
        self.assertEqual(self.tasks[task_id]["status"], "succeeded")
        self.assertEqual(self.tasks[task_id]["params"]["credit_estimate"], 5)
        path = Path(self.temp.name)/"2026-09-27"/self.tasks[task_id]["result_file"]
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
        self.assertEqual(path.with_suffix(".txt").read_text(), "test prompt\n")
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("secret-not-public", json.dumps(self.tasks[task_id]))

    def test_prepare_rejects_stale_model_and_invalid_option(self):
        with self.assertRaisesRegex(ValueError, "模型已变化"):
            self.service._prepare({"kind":"image","model_id":"stale","prompt":"a"})
        model_id = catalog_fixture()["models"]["image"][0]["id"]
        with self.assertRaisesRegex(ValueError, "选项已变化"):
            self.service._prepare({"kind":"image","model_id":model_id,"prompt":"a",
                                   "parameters":{"size":"invalid"}})

    def test_status_and_history_expose_video_as_video(self):
        task = {"task_id":"cyimg_x", "type":"cyimg-video", "status":"succeeded_no_telegram",
                "prompt":"clip", "params":{}, "result_file":"clip.mp4", "result_files":["clip.mp4"]}
        result = _status_response_task(task, H3_VIDEO_TASK_TYPE="minimax-h3-video",
            _history_task_result_files=lambda value:(value["result_files"],value["result_file"]),
            _public_h3_task_params=lambda params:params,safe_basename=lambda name:name,
            urllib=__import__("urllib"))
        self.assertEqual(result["video_path"], "/video/clip.mp4")
        self.assertEqual(result["image_count"], 0)
        history = format_history_task(task, task_result_files=lambda value:(value["result_files"],value["result_file"]),
            h3_task_type="minimax-h3-video",public_h3_params=lambda params:params,safe_basename=lambda name:name)
        self.assertEqual(history["video_count"], 1)
        self.assertEqual(history["image_paths"], [])

    def test_transient_status_connection_error_retries_without_resubmitting(self):
        task_id = "cyimg_" + "a" * 32
        self.tasks[task_id] = {"task_id": task_id, "type": "cyimg-image", "status": "queued",
            "prompt": "retry", "params": {"kind": "image", "remote_task_id": "img_task_remote"}}
        calls = []
        original_status = self.client.status

        def status(remote_id):
            calls.append(remote_id)
            if len(calls) == 1:
                raise requests.ConnectionError("temporary")
            return original_status(remote_id)

        self.client.status = status
        self.client.submit = lambda body: self.fail("existing remote task must not be submitted again")
        with patch("backend.services.cyimg_generation.time.sleep", return_value=None):
            self.service.run(task_id)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.tasks[task_id]["status"], "succeeded_no_telegram")

    def test_video_result_archives_mp4_with_prompt_sidecar(self):
        task_id = "cyimg_" + "b" * 32
        self.tasks[task_id] = {"task_id": task_id, "type": "cyimg-video", "status": "queued",
            "prompt": "camera move", "params": {"kind": "video", "remote_task_id": "img_task_remote"}}
        self.client.status = lambda remote_id: {"status": "completed", "result": "https://assets.example.test/clip.mp4"}
        self.client.download = lambda url, max_bytes: (b"synthetic video", "video/mp4", url)
        self.service.run(task_id)
        row = self.tasks[task_id]
        self.assertEqual(row["status"], "succeeded_no_telegram")
        clip = Path(self.temp.name)/"2026-09-27"/row["result_file"]
        self.assertEqual(clip.suffix, ".mp4")
        self.assertEqual(clip.read_bytes(), b"synthetic video")
        self.assertEqual(clip.with_suffix(".txt").read_text(), "camera move\n")

    def test_failed_status_preserves_reason_returned_in_result_field(self):
        task_id = "cyimg_" + "c" * 32
        self.tasks[task_id] = {"task_id": task_id, "type": "cyimg-video", "status": "queued",
            "prompt": "camera move", "params": {"kind": "video", "remote_task_id": "img_task_remote"}}
        reason = "内容审核未通过：执行平台判定「色情/低俗」，判定码 Porn，请修改提示词或素材后重试"
        self.client.status = lambda remote_id: {
            "status": "failed", "result": reason, "message": "", "error_message": ""
        }

        self.service.run(task_id)

        self.assertEqual(self.tasks[task_id]["status"], "failed")
        self.assertEqual(self.tasks[task_id]["error"], reason)


if __name__ == "__main__":
    unittest.main()
