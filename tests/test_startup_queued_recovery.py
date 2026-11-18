"""Startup recovery of leftover queued/pending online generation tasks."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import database
from backend import server
from backend.krea2.service import Service as KreaService
from backend.moss.service import Service as MossService
from backend.qwen21.service import Service as QwenService
from backend.services.cyimg_generation import CyimgService


class StartupQueuedRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "tasks.db"
        self._db_patch = patch.object(database, "DB_PATH", str(self.db_path))
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)
        database.init_db()

    def test_online_queued_and_pending_are_failed_and_retryable_without_upstream(self) -> None:
        database.create_task("gpt-queued", "gpt prompt", {"ratio": "1:1", "resolution": "2k", "quality": "auto"}, status="queued", task_type="gpt")
        database.create_task("google-pending", "google prompt", {"ratio": "1:1", "quality": "2k"}, status="pending", task_type="google-gen")
        database.create_task("done", "ok", {}, status="succeeded", task_type="gpt")
        database.create_task("canceled", "nope", {}, status="canceled", task_type="google-gen")

        generate_calls = []
        with patch.object(server, "_start_retry_thread", side_effect=lambda *args, **kwargs: generate_calls.append(args) or True):
            in_flight = database.fail_stale_processing_tasks(max_age_seconds=0)
            queued = database.fail_orphaned_queued_generation_tasks()
            gpt = database.get_task("gpt-queued")
            google = database.get_task("google-pending")
            retry = server.retry_failed_task(gpt)

        self.assertEqual(in_flight, 0)
        self.assertEqual(queued, 2)
        self.assertEqual(gpt["status"], "failed")
        self.assertEqual(google["status"], "failed")
        self.assertEqual(gpt["error_code"], "task.orphaned_queue")
        self.assertEqual(database.get_task("done")["status"], "succeeded")
        self.assertEqual(database.get_task("canceled")["status"], "canceled")
        self.assertTrue(retry.get("ok"))
        self.assertNotEqual(retry.get("task_id"), "gpt-queued")
        self.assertEqual(retry.get("retry_of"), "gpt-queued")
        self.assertEqual(len(generate_calls), 1)

    def test_specialty_domain_queued_tasks_are_left_to_their_recover(self) -> None:
        database.create_task("cyimg-unknown", "p", {}, status="queued", task_type="cyimg-image")
        database.create_task("cyimg-known", "p", {"remote_task_id": "remote-abc"}, status="processing", task_type="cyimg-image")
        database.create_task("krea-queued", "p", {}, status="queued", task_type="krea2-image")
        database.create_task("qwen-queued", "p", {}, status="queued", task_type="qwen21-image")
        database.create_task("moss-queued", "p", {}, status="queued", task_type="moss-image")
        database.create_task("gpt-queued", "p", {"ratio": "1:1"}, status="queued", task_type="gpt")

        changed = database.fail_orphaned_queued_generation_tasks()
        self.assertEqual(changed, 1)
        self.assertEqual(database.get_task("gpt-queued")["status"], "failed")
        self.assertEqual(database.get_task("cyimg-unknown")["status"], "queued")
        self.assertEqual(database.get_task("cyimg-known")["status"], "processing")
        self.assertEqual(database.get_task("krea-queued")["status"], "queued")
        self.assertEqual(database.get_task("qwen-queued")["status"], "queued")
        self.assertEqual(database.get_task("moss-queued")["status"], "queued")

        class Shim:
            get_all_tasks = staticmethod(database.get_all_tasks)
            update_task = staticmethod(database.update_task)

            def run(self, task_id):
                self.runs.append(task_id)

            runs = []

        KreaService.recover(Shim())
        QwenService.recover(Shim())
        MossService.recover(Shim())
        CyimgService.recover(Shim())
        deadline = time.time() + 2
        while time.time() < deadline and "cyimg-known" not in Shim.runs:
            time.sleep(0.05)

        self.assertEqual(database.get_task("krea-queued")["status"], "failed")
        self.assertEqual(database.get_task("qwen-queued")["status"], "failed")
        self.assertEqual(database.get_task("moss-queued")["status"], "failed")
        self.assertEqual(database.get_task("cyimg-unknown")["status"], "failed")
        self.assertIn("cyimg-known", Shim.runs)
        self.assertNotIn("cyimg-unknown", Shim.runs)
        self.assertEqual(database.get_task("cyimg-known")["status"], "processing")


if __name__ == "__main__":
    unittest.main()
