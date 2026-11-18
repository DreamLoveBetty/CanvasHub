"""Delivery status and archive-only Telegram resend, without regenerating."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import api_client
from backend import server
from backend.services.task_telegram_resend import (
    TaskTelegramResendError,
    begin_task_resend,
    end_task_resend,
)
from tests.temp_task_db import use_temp_task_db

PNG_A = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4&\x00\x00\x00\x00IEND\xaeB`\x82"
)
PNG_B = PNG_A + b"B"


class TelegramDeliveryAndResendTests(unittest.TestCase):
    def setUp(self) -> None:
        use_temp_task_db(self)
        end_task_resend("google-tg-fail")
        end_task_resend("google-edit-tg-fail")
        end_task_resend("gpt-tg-fail")
        end_task_resend("lock-me")

    def _google_params(self, telegram_enabled=True):
        return {
            "ratio": "1:1",
            "quality": "2k",
            "model": "gemini-3-pro-image",
            "archive_enabled": True,
            "telegram_enabled": telegram_enabled,
            "caller": "webapp",
        }

    def _resolver(self, out_dir: Path):
        def resolve(filename):
            path = out_dir / Path(filename).name
            return path if path.exists() else None
        return resolve

    def test_google_generate_telegram_fail_stays_failed_and_can_resend_only(self) -> None:
        from backend import database
        generate_calls = {"n": 0}
        send_calls = []

        def fake_generate(*args, **kwargs):
            generate_calls["n"] += 1
            return PNG_A, {"bytes_received": len(PNG_A)}

        def fake_send(*args, **kwargs):
            send_calls.append(args)
            return False

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            params = self._google_params(True)
            with patch.object(server, "generate_image", side_effect=fake_generate), \
                patch.object(server, "send_telegram", side_effect=fake_send), \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir):
                database.create_task("google-tg-fail", "a cat", params, status="queued", task_type="google-gen")
                server.process_task("google-tg-fail", "a cat", params)
                task = database.get_task("google-tg-fail")
                self.assertEqual(task["status"], "telegram_failed")
                self.assertTrue(task["result_file"])
                self.assertEqual((out_dir / task["result_file"]).read_bytes(), PNG_A)
                self.assertEqual(generate_calls["n"], 1)
                self.assertEqual(len(send_calls), 1)

                def fake_send_ok(*args, **kwargs):
                    send_calls.append(args)
                    return True

                with patch.object(server, "send_telegram", side_effect=fake_send_ok), \
                    patch.object(server, "_resolve_download_image", side_effect=self._resolver(out_dir)), \
                    patch.object(server, "generate_image", side_effect=AssertionError("must not regenerate")), \
                    patch.object(server, "generate_image_gpt_pool", side_effect=AssertionError("must not fallback")):
                    result = server.retry_failed_task(task)
                    after = database.get_task("google-tg-fail")

            self.assertTrue(result.get("resent"))
            self.assertFalse(result.get("regenerated"))
            self.assertEqual(result.get("task_id"), "google-tg-fail")
            self.assertEqual(after["status"], "succeeded")
            self.assertEqual(generate_calls["n"], 1)
            self.assertEqual(len(send_calls), 2)
            self.assertTrue(str(send_calls[1][1]).endswith(task["result_file"]))

    def test_google_edit_telegram_fail_stays_failed_and_can_resend_only(self) -> None:
        from backend import database
        edit_calls = {"n": 0}
        send_calls = []

        def fake_edit(*args, **kwargs):
            edit_calls["n"] += 1
            return PNG_B, {"bytes_received": len(PNG_B)}

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            src = out_dir / "src.png"
            src.write_bytes(PNG_A)
            params = self._google_params(True)
            with patch.object(api_client, "edit_image", side_effect=fake_edit), \
                patch.object(server, "send_telegram", side_effect=lambda *a, **k: send_calls.append(a) or False), \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir):
                database.create_task("google-edit-tg-fail", "edit me", params, status="queued", task_type="google-edit")
                server.process_edit_task("google-edit-tg-fail", "edit me", [str(src)], params)
                task = database.get_task("google-edit-tg-fail")
                self.assertEqual(task["status"], "telegram_failed")
                self.assertEqual((out_dir / task["result_file"]).read_bytes(), PNG_B)
                self.assertEqual(edit_calls["n"], 1)

                with patch.object(server, "send_telegram", side_effect=lambda *a, **k: send_calls.append(a) or True), \
                    patch.object(server, "_resolve_download_image", side_effect=self._resolver(out_dir)), \
                    patch.object(api_client, "edit_image", side_effect=AssertionError("must not edit again")), \
                    patch.object(server, "generate_image_gpt_pool", side_effect=AssertionError("must not fallback")):
                    result = server.resend_task_telegram("google-edit-tg-fail")
                    after = database.get_task("google-edit-tg-fail")

            self.assertTrue(result.get("resent"))
            self.assertEqual(after["status"], "succeeded")
            self.assertEqual(edit_calls["n"], 1)

    def test_skipped_telegram_is_not_retryable_as_failure(self) -> None:
        from backend import database
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            params = self._google_params(False)
            with patch.object(server, "generate_image", return_value=(PNG_A, {})), \
                patch.object(server, "send_telegram") as send_telegram, \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir):
                database.create_task("google-tg-off", "skip", params, status="queued", task_type="google-gen")
                server.process_task("google-tg-off", "skip", params)
                task = database.get_task("google-tg-off")
                send_telegram.assert_not_called()
                self.assertEqual(task["status"], "succeeded_no_telegram")
                with self.assertRaises(server.TaskRetryError) as ctx:
                    server.retry_failed_task(task)
                self.assertIn("只有失败任务可以重跑", str(ctx.exception))

    def test_telegram_failed_without_archive_does_not_regenerate(self) -> None:
        task = {
            "task_id": "no-file",
            "status": "telegram_failed",
            "type": "gpt",
            "prompt": "x",
            "result_file": "",
            "result_files": [],
            "params": {"ratio": "1:1", "resolution": "2k", "quality": "auto"},
        }
        with self.assertRaises(server.TaskRetryError) as ctx:
            server.retry_failed_task(task)
        self.assertIn("没有可补发的归档文件", str(ctx.exception))

    def test_concurrent_resend_is_rejected(self) -> None:
        self.assertTrue(begin_task_resend("lock-me"))
        try:
            with self.assertRaises(TaskTelegramResendError) as ctx:
                # Force the lock path without a real task fetch by calling begin again.
                from backend.services.task_telegram_resend import begin_task_resend as begin
                if not begin("lock-me"):
                    raise TaskTelegramResendError("该任务正在补发中，请稍后再试。", 409)
            self.assertEqual(ctx.exception.status, 409)
        finally:
            end_task_resend("lock-me")

    def test_resend_rejects_file_not_belonging_to_task(self) -> None:
        from backend import database
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            owned = out_dir / "owned.png"
            other = out_dir / "other.png"
            owned.write_bytes(PNG_A)
            other.write_bytes(PNG_B)
            database.create_task(
                "owned-task", "p", {}, status="telegram_failed", task_type="google-gen",
            )
            database.update_task("owned-task", "telegram_failed", result_file="owned.png", error="tg")
            # update_task may need result_files
            database.update_task_fields("owned-task", result_file="owned.png", result_files='["owned.png"]', status="telegram_failed")
            with patch.object(server, "_resolve_download_image", side_effect=self._resolver(out_dir)), \
                patch.object(server, "send_telegram", side_effect=AssertionError("must not send foreign file")):
                with self.assertRaises(TaskTelegramResendError) as ctx:
                    server.resend_task_telegram("owned-task", requested_file="other.png")
            self.assertEqual(ctx.exception.status, 403)

    def test_generation_failed_retry_still_creates_new_task(self) -> None:
        started = []
        original = {
            "task_id": "gen-failed",
            "status": "failed",
            "prompt": "city at night",
            "type": "gpt",
            "result_file": "",
            "params": {"ratio": "1:1", "resolution": "2k", "quality": "auto"},
        }
        with patch.object(server, "create_task", return_value=None) as create_task, \
            patch.object(server, "get_task", return_value={"task_id": "new-id", "status": "queued"}), \
            patch.object(server, "_start_retry_thread", side_effect=lambda *a, **k: started.append(a) or True):
            result = server.retry_failed_task(original)
        self.assertTrue(result.get("ok"))
        self.assertFalse(result.get("resent"))
        self.assertEqual(result.get("retry_of"), "gen-failed")
        self.assertEqual(len(started), 1)
        self.assertEqual(create_task.call_args.kwargs["status"], "queued")


class GptTelegramDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        use_temp_task_db(self)

    def test_gpt_send_failure_is_telegram_failed(self) -> None:
        from backend import database
        image_path = None
        with tempfile.TemporaryDirectory() as tmp:
            image_path = str(Path(tmp) / "gpt-task.png")
            Path(image_path).write_bytes(PNG_A)
            database.create_task("gpt-tg-fail", "gpt prompt", {"telegram_enabled": True}, status="queued", task_type="gpt")
            with patch.object(server, "generate_image_gpt_codex", return_value={
                "success": True, "image_path": image_path, "image_paths": [image_path],
            }), \
                patch.object(server, "generate_image_gpt_pool", side_effect=AssertionError("no fallback")), \
                patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": False}), \
                patch.object(server, "resolve_route_model", return_value={
                    "model": "gpt-5.5", "reasoning_effort": "medium", "available": True,
                }), \
                patch.object(server, "send_telegram_result", return_value=False), \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "_prepare_chatgpt_pool_generation_prompt", side_effect=lambda *a, **k: ("gpt prompt", {})):
                server.process_gpt_task(
                    "gpt-tg-fail", "gpt prompt", "1:1", "2k", "auto",
                    image_count=1, gpt_provider_route="codex",
                    use_third_party_api=False, archive_enabled=True, telegram_enabled=True,
                )
                task = database.get_task("gpt-tg-fail")
        self.assertEqual(task["status"], "telegram_failed")
        self.assertTrue(task.get("result_file"))


if __name__ == "__main__":
    unittest.main()
