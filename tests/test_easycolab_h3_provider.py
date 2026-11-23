"""Unit and service regression tests for the independent EasyColab MiniMax-H3 domain."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import app_config
from backend.provider_easycolab_h3 import EasyColabH3Client, snap_h3_frames, snap_multiple_of_32
from backend.services.easycolab_h3_generation import EasyColabH3Service


class FakeClient:
    def __init__(self, *, loaded=True, downloaded=(4, 4)):
        self.loaded = loaded
        self.downloaded = downloaded
        self.load_calls = []
        self.generate_calls = []
        self.cancel_calls = 0
        self.status_calls = 0
        self.job_polls = 0
        self.job_states = [
            {"job_id": "remote-job-1", "status": "running", "progress": 0.5, "message": "采样中 4/8"},
            {
                "job_id": "remote-job-1",
                "status": "completed",
                "progress": 1.0,
                "seed": 12345,
                "elapsed": 18.4,
                "filename": "out.mp4",
                "video_url": "/minimax_api/video/out.mp4",
                "completed_videos": [
                    {"filename": "out.mp4", "video_url": "/minimax_api/video/out.mp4", "seed": 12345}
                ],
            },
        ]

    def status(self, model_id=None, *, touch=False):
        self.status_calls += 1
        return {
            "ok": True,
            "gpu_name": "RTX PRO 6000",
            "cuda_available": True,
            "vram_free_gb": 80.0,
            "vram_total_gb": 96.0,
            "vram_used_gb": 16.0,
            "model_loaded": self.loaded,
            "loaded_model_ids": [model_id] if (self.loaded and model_id) else (["minimax_h3_10eros_max"] if self.loaded else []),
            "is_loading_vram": False,
            "is_downloading": False,
            "downloaded_count": self.downloaded[0],
            "total_count": self.downloaded[1],
            "task_message": "就绪",
        }

    def load_model(self, model_id, **kwargs):
        self.load_calls.append(model_id)
        self.loaded = True
        return self.status(model_id=model_id)

    def generate(self, payload):
        self.generate_calls.append(payload)
        return {"job_id": "remote-job-1", "status": "queued"}

    def job_status(self, job_id):
        idx = min(self.job_polls, len(self.job_states) - 1)
        self.job_polls += 1
        return dict(self.job_states[idx])

    def cancel(self):
        self.cancel_calls += 1
        return {"ok": True}

    def download_media(self, media_ref, max_bytes):
        if media_ref.endswith(".png"):
            return b"\x89PNG\r\n\x1a\nfixture", "image/png", f"https://demo.gradio.live{media_ref}"
        return b"\x00\x00\x00\x18ftypmp42fixture", "video/mp4", f"https://demo.gradio.live{media_ref}"


class EasyColabH3ProviderTests(unittest.TestCase):
    def test_frame_and_dimension_snapping(self):
        self.assertEqual(snap_h3_frames(1), 22)
        self.assertEqual(snap_h3_frames(56), 56)
        self.assertEqual(snap_h3_frames(120), 124)
        self.assertEqual(snap_h3_frames(999), 362)
        self.assertEqual(snap_multiple_of_32(1056, default=1056, minimum=256, maximum=1920), 1056)
        self.assertEqual(snap_multiple_of_32(1060, default=1056, minimum=256, maximum=1920), 1056)
        self.assertEqual(snap_multiple_of_32(5472, default=2048, minimum=512, maximum=5472), 5472)

    def test_client_rejects_cross_origin_media_download(self):
        client = EasyColabH3Client("https://demo.gradio.live", "secret-password-value")
        self.assertEqual(
            client._resolve_media_url("/minimax_api/video/test.mp4"),
            "https://demo.gradio.live/minimax_api/video/test.mp4",
        )
        with self.assertRaisesRegex(RuntimeError, "非当前 EasyColab"):
            client._resolve_media_url("https://evil.example/a.mp4")

    def test_config_masks_password_length_and_reads_local_session(self):
        secret = "ec-synthetic-password-0123456789"
        with tempfile.TemporaryDirectory() as tmp:
            sess_path = Path(tmp) / "session.json"
            sess_path.write_text(
                json.dumps({"url": "https://sess.gradio.live", "password": "sess-password-98765432101234", "sleeping": False}),
                encoding="utf-8",
            )
            with mock.patch.object(app_config, "load_app_settings", return_value={"easycolab": {"password": secret}}), \
                    mock.patch.dict(os.environ, {"EASYCOLAB_SESSION_FILE": str(sess_path)}, clear=False):
                os.environ.pop("EASYCOLAB_URL", None)
                os.environ.pop("EASYCOLAB_PASSWORD", None)
                cfg = app_config.get_easycolab_config()
            self.assertEqual(cfg["password_configured"], True)
            self.assertEqual(cfg["password_length"], len(secret))
            self.assertTrue(cfg["session_detected"])
            self.assertEqual(cfg["effective_base_url"], "https://sess.gradio.live")
            self.assertEqual(cfg["effective_password"], secret)

    def test_service_prepare_submit_poll_archive_and_telegram(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "archive"
            tasks = {}
            sent_docs = []

            def create_task(task_id, prompt, params, status="queued", task_type="easycolab-h3-video"):
                tasks[task_id] = {
                    "task_id": task_id,
                    "prompt": prompt,
                    "params": dict(params),
                    "status": status,
                    "type": task_type,
                }

            def get_task(task_id):
                row = tasks.get(task_id)
                if not row:
                    return None
                return dict(row)

            def update_task(task_id, status, result_file=None, result_files=None, error=None, stage=None, progress=None, progress_text=None):
                row = tasks[task_id]
                row["status"] = status
                if result_file is not None:
                    row["result_file"] = result_file
                if result_files is not None:
                    row["result_files"] = json.loads(result_files) if isinstance(result_files, str) else result_files
                if error is not None:
                    row["error"] = error
                if stage is not None:
                    row["stage"] = stage
                if progress is not None:
                    row["progress"] = progress
                if progress_text is not None:
                    row["progress_text"] = progress_text

            def update_task_status(task_id, status, progress_text="", stage="", progress=0):
                row = tasks[task_id]
                row["status"] = status
                row["progress_text"] = progress_text
                row["stage"] = stage
                row["progress"] = progress

            def update_task_fields(task_id, **fields):
                row = tasks[task_id]
                if "params" in fields and isinstance(fields["params"], str):
                    fields["params"] = json.loads(fields["params"])
                row.update(fields)

            fake_client = FakeClient(loaded=False)
            service = EasyColabH3Service(
                get_config=lambda: {
                    "base_url": "https://demo.gradio.live",
                    "effective_base_url": "https://demo.gradio.live",
                    "effective_password": "demo-password-0123456789012345",
                    "auto_load_model": True,
                    "task_timeout_seconds": 300,
                },
                create_task=create_task,
                get_task=get_task,
                get_all_tasks=lambda limit=5000: list(tasks.values()),
                update_task=update_task,
                update_task_status=update_task_status,
                update_task_fields=update_task_fields,
                daily_output_dir=lambda: archive_dir,
                send_document=lambda path, caption: sent_docs.append((Path(path).name, caption)),
                probe_video_metadata=lambda p: {"width": 1056, "height": 608, "fps": 24, "duration_seconds": 5.17},
            )
            service._client = lambda cfg=None: fake_client

            img_tok = service.upload(b"\x89PNG\r\n\x1a\nref", "char.png", "image/png")["upload_token"]
            aud_tok = service.upload(b"RIFF....WAVEfmt ", "voice.wav", "audio/wav")["upload_token"]

            kind, prompt, spec, body, pub = service._prepare({
                "kind": "video",
                "model_id": "minimax_h3_10eros_max",
                "task_mode": "multiref",
                "prompt": "The woman from <Picture 1> (<Audio 1>) smiles.",
                "parameters": {
                    "width": 1056,
                    "height": 608,
                    "num_frames": 120,
                    "num_inference_steps": 8,
                    "ref_image_size": "max",
                    "soundscape_prompt": "soft rain",
                },
                "image_upload_tokens": [img_tok],
                "audio_upload_tokens": [aud_tok],
            })
            self.assertEqual(kind, "video")
            self.assertEqual(body["num_frames"], 124)
            self.assertEqual(body["ref_image_size"], "max")
            self.assertEqual(len(body["ref_images_base64"]), 1)
            self.assertTrue(body["ref_audio_base64"])
            self.assertNotIn("ref_images_base64", pub)

            create_task("easycolab_h3_test1", prompt, {"provider": "easycolab_h3", "kind": "video", "model_id": spec["id"], "model_label": spec["label"], "parameters": pub, "telegram_enabled": True})
            with mock.patch("backend.services.easycolab_h3_generation.time.sleep", return_value=None):
                service.run("easycolab_h3_test1", body)

            self.assertEqual(fake_client.load_calls, ["minimax_h3_10eros_max"])
            self.assertEqual(len(fake_client.generate_calls), 1)
            task = tasks["easycolab_h3_test1"]
            self.assertEqual(task["status"], "succeeded")
            self.assertEqual(task["params"]["remote_job_id"], "remote-job-1")
            self.assertEqual(task["params"]["width"], 1056)
            self.assertEqual(len(sent_docs), 1)
            archived_mp4 = archive_dir / task["result_file"]
            self.assertTrue(archived_mp4.is_file())
            sidecar = archived_mp4.with_suffix(".txt").read_text(encoding="utf-8")
            self.assertIn("The woman from <Picture 1>", sidecar)
            self.assertIn("Soundscape: soft rain", sidecar)

    def test_recover_fails_unconfirmed_and_resumes_confirmed(self):
        tasks = {
            "ec_unknown": {"task_id": "ec_unknown", "type": "easycolab-h3-video", "status": "queued", "params": {}},
            "ec_known": {"task_id": "ec_known", "type": "easycolab-h3-image", "status": "queued", "params": {"remote_job_id": "r1"}},
        }
        resumed = []

        service = EasyColabH3Service(
            get_config=lambda: {},
            create_task=lambda *a, **kw: None,
            get_task=lambda tid: tasks.get(tid),
            get_all_tasks=lambda limit=5000: list(tasks.values()),
            update_task=lambda tid, status, error=None, **kw: tasks[tid].update({"status": status, "error": error}),
            update_task_status=lambda *a, **kw: None,
            update_task_fields=lambda *a, **kw: None,
            daily_output_dir=lambda: Path("."),
            send_document=lambda *a, **kw: None,
        )
        service.run = lambda tid: resumed.append(tid)
        service.recover()
        deadline = time.time() + 2
        while time.time() < deadline and "ec_known" not in resumed:
            time.sleep(0.02)
        self.assertEqual(tasks["ec_unknown"]["status"], "failed")
        self.assertIn("ec_known", resumed)


if __name__ == "__main__":
    unittest.main()
