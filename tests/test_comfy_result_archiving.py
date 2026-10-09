from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from backend import database
from backend import server


class ComfyResultArchivingTest(unittest.TestCase):
    def test_multi_image_retry_reuses_deterministic_archive_files(self) -> None:
        images = [
            {"filename": "first.png", "subfolder": "", "type": "output"},
            {"filename": "second.png", "subfolder": "", "type": "output"},
        ]
        params = {
            "comfy_images": images,
            "comfy_expected_output_count": 2,
            "telegram_enabled": False,
            "width": 2048,
            "height": 2048,
        }
        attempts = Counter()

        def fetch(filename, _subfolder, _file_type):
            attempts[filename] += 1
            if filename == "second.png" and attempts[filename] == 1:
                raise RuntimeError("second download failed")
            return f"bytes:{filename}".encode("utf-8"), "image/png"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            archive_dir.mkdir()
            task_id = "comfy_retry_task"
            with patch.object(database, "DB_PATH", str(root / "tasks.db")):
                database.init_db()
                server.create_task(task_id, "restore detail", params, task_type="comfy")

                with patch.object(server, "daily_output_dir", return_value=archive_dir), \
                    patch.object(server, "_fetch_comfy_binary", side_effect=fetch), \
                    patch.object(
                        server.random,
                        "randint",
                        side_effect=AssertionError("Comfy archive naming must be deterministic"),
                    ), \
                    patch.object(server, "save_thumbnail"), \
                    patch.object(server, "write_obsidian_prompt_sidecar"), \
                    patch.object(server, "send_status_notification"), \
                    patch.object(server, "send_telegram") as send_telegram:
                    with self.assertRaisesRegex(RuntimeError, "second download failed"):
                        server._send_comfy_result(
                            task_id,
                            "restore detail",
                            "upscale.json",
                            "1:1",
                            images[0],
                            params,
                        )

                    self.assertEqual(list(archive_dir.glob("*.png")), [])
                    retry_params = server.get_task(task_id)["params"]
                    server._send_comfy_result(
                        task_id,
                        "restore detail",
                        "upscale.json",
                        "1:1",
                        images[0],
                        retry_params,
                    )

                    first_names = sorted(path.name for path in archive_dir.glob("*.png"))
                    self.assertEqual(len(first_names), 2)
                    self.assertEqual(len(list(archive_dir.glob("*.txt"))), 2)

                    final_params = server.get_task(task_id)["params"]
                    with patch.object(server, "_fetch_comfy_binary") as fetch_again:
                        server._send_comfy_result(
                            task_id,
                            "restore detail",
                            "upscale.json",
                            "1:1",
                            images[0],
                            final_params,
                        )
                    fetch_again.assert_not_called()
                    send_telegram.assert_not_called()

                final_task = server.get_task(task_id)

        self.assertEqual(final_task["status"], "succeeded_no_telegram")
        self.assertEqual(sorted(final_task["result_files"]), first_names)
        self.assertEqual(sorted(final_task["params"]["archive_files"]), first_names)
        self.assertEqual(attempts["first.png"], 2)
        self.assertEqual(attempts["second.png"], 2)
        self.assertTrue(
            all(name.startswith("comfy_") for name in first_names),
            first_names,
        )

    def test_canceled_task_skips_archive_and_telegram(self) -> None:
        image = {"filename": "canceled.png", "subfolder": "", "type": "output"}
        params = {
            "comfy_images": [image],
            "comfy_expected_output_count": 1,
            "telegram_enabled": True,
        }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.db"
            with patch.object(database, "DB_PATH", str(db_path)):
                database.init_db()
                server.create_task("comfy_canceled", "prompt", params, task_type="comfy")
                server.update_task("comfy_canceled", "canceled", stage="canceled")

                with patch.object(server, "_fetch_comfy_binary") as fetch, \
                    patch.object(server, "send_telegram") as send_telegram:
                    server._send_comfy_result(
                        "comfy_canceled",
                        "prompt",
                        "workflow.json",
                        "1:1",
                        image,
                        params,
                    )

                fetch.assert_not_called()
                send_telegram.assert_not_called()
                self.assertEqual(server.get_task("comfy_canceled")["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
