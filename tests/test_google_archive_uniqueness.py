"""Google generate/edit archive names must not overwrite in the same second."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend import api_client
from backend import server
from backend.storage_paths import reserve_unique_archive_file, sanitize_archive_token
from tests.temp_task_db import use_temp_task_db

PNG_A = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4&\x00\x00\x00\x00IEND\xaeB`\x82"
)
PNG_B = PNG_A[:-8] + b"XXXXYYYY" + PNG_A[-8:]


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 16, 20, 18, 8)


class ReserveUniqueArchiveFileTests(unittest.TestCase):
    def test_same_base_name_reserves_distinct_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first, first_name = reserve_unique_archive_file(folder, "3-pro_20261116_201808", task_id="gen_a")
            second, second_name = reserve_unique_archive_file(folder, "3-pro_20261116_201808", task_id="gen_b")
            third, third_name = reserve_unique_archive_file(folder, "3-pro_20261116_201808", task_id="gen_a")
            self.assertNotEqual(first_name, second_name)
            self.assertNotEqual(first_name, third_name)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertTrue(third.exists())
            self.assertIn("gen_a", first_name)
            self.assertIn("gen_b", second_name)
            self.assertTrue(third_name.startswith(Path(first_name).stem + "_"))

    def test_sanitize_archive_token_strips_path_separators(self) -> None:
        self.assertEqual(sanitize_archive_token("../weird id"), "weird-id")
        self.assertEqual(sanitize_archive_token(""), "")


class GoogleArchiveUniquenessTests(unittest.TestCase):
    def setUp(self) -> None:
        use_temp_task_db(self)

    def _params(self, telegram_enabled=False):
        return {
            "ratio": "1:1",
            "quality": "2k",
            "model": "gemini-3-pro-image",
            "archive_enabled": True,
            "telegram_enabled": telegram_enabled,
            "caller": "webapp",
        }

    def test_generate_same_second_keeps_distinct_bytes(self) -> None:
        payloads = [PNG_A, PNG_B]
        calls = {"generate": 0}

        def fake_generate(*args, **kwargs):
            data = payloads[calls["generate"]]
            calls["generate"] += 1
            return data, {"bytes_received": len(data)}

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("datetime.datetime", FrozenDateTime), \
                patch.object(server, "generate_image", side_effect=fake_generate), \
                patch.object(server, "send_telegram", return_value=True), \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir):
                from backend import database
                database.create_task("gen-unique-a", "first prompt", self._params(), status="queued", task_type="google-gen")
                database.create_task("gen-unique-b", "second prompt", self._params(), status="queued", task_type="google-gen")
                server.process_task("gen-unique-a", "first prompt", self._params())
                server.process_task("gen-unique-b", "second prompt", self._params())
                task_a = database.get_task("gen-unique-a")
                task_b = database.get_task("gen-unique-b")

            self.assertEqual(calls["generate"], 2)
            self.assertNotEqual(task_a["result_file"], task_b["result_file"])
            path_a = out_dir / task_a["result_file"]
            path_b = out_dir / task_b["result_file"]
            self.assertTrue(path_a.exists())
            self.assertTrue(path_b.exists())
            self.assertEqual(path_a.read_bytes(), PNG_A)
            self.assertEqual(path_b.read_bytes(), PNG_B)
            self.assertIn("gen-unique-a", task_a["result_file"])
            self.assertIn("gen-unique-b", task_b["result_file"])

    def test_edit_same_second_keeps_distinct_bytes(self) -> None:
        payloads = [PNG_A, PNG_B]
        calls = {"edit": 0}

        def fake_edit(*args, **kwargs):
            data = payloads[calls["edit"]]
            calls["edit"] += 1
            return data, {"bytes_received": len(data)}

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            src = out_dir / "src.png"
            src.write_bytes(PNG_A)
            with patch("datetime.datetime", FrozenDateTime), \
                patch.object(api_client, "edit_image", side_effect=fake_edit), \
                patch.object(server, "send_telegram", return_value=True), \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir):
                from backend import database
                params = self._params()
                database.create_task("edit-unique-a", "edit first", params, status="queued", task_type="google-edit")
                database.create_task("edit-unique-b", "edit second", params, status="queued", task_type="google-edit")
                server.process_edit_task("edit-unique-a", "edit first", [str(src)], params)
                server.process_edit_task("edit-unique-b", "edit second", [str(src)], params)
                task_a = database.get_task("edit-unique-a")
                task_b = database.get_task("edit-unique-b")

            self.assertEqual(calls["edit"], 2)
            self.assertNotEqual(task_a["result_file"], task_b["result_file"])
            path_a = out_dir / task_a["result_file"]
            path_b = out_dir / task_b["result_file"]
            self.assertTrue(path_a.exists())
            self.assertTrue(path_b.exists())
            self.assertEqual(path_a.read_bytes(), PNG_A)
            self.assertEqual(path_b.read_bytes(), PNG_B)
            self.assertIn("edit-unique-a", task_a["result_file"])
            self.assertIn("edit-unique-b", task_b["result_file"])


if __name__ == "__main__":
    unittest.main()
