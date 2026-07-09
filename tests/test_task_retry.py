import unittest
import tempfile
import time
import json
import threading
from pathlib import Path
from unittest.mock import patch

from backend import server


class FakeThread:
    started = []

    def __init__(self, target=None, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        FakeThread.started.append(self)


class TaskRetryTest(unittest.TestCase):
    def setUp(self):
        FakeThread.started = []

    def test_gpt_retry_creates_new_task_with_clean_params(self):
        original = {
            "task_id": "gpt_old",
            "status": "failed",
            "prompt": "city at night",
            "type": "gpt",
            "error": "TLS failed",
            "params": {
                "ratio": "16:9",
                "resolution": "2k",
                "quality": "auto",
                "image_count": 2,
                "moderation": "auto",
                "prompt_mode": "smart",
                "gpt_provider_route": "codex",
                "route_trace": [{"provider": "codex"}],
                "revised_prompt": "old revised prompt",
                "attempt_no": 1,
            },
        }

        with patch.object(server.time, "time", return_value=1710000000), \
             patch.object(server.random, "randint", return_value=1234), \
             patch.object(server, "create_task") as create_task, \
             patch.object(server, "get_task", return_value=None), \
             patch.object(server.threading, "Thread", FakeThread):
            task = server.retry_failed_task(original)

        self.assertEqual(task["task_id"], "gpt_1710000000_1234")
        self.assertEqual(task["retry_of"], "gpt_old")
        create_task.assert_called_once()
        task_id, prompt, params = create_task.call_args.args[:3]
        self.assertEqual(task_id, "gpt_1710000000_1234")
        self.assertEqual(prompt, "city at night")
        self.assertEqual(create_task.call_args.kwargs["status"], "queued")
        self.assertEqual(create_task.call_args.kwargs["task_type"], "gpt")
        self.assertEqual(params["retry_of"], "gpt_old")
        self.assertEqual(params["attempt_no"], 2)
        self.assertEqual(params["retry_source_status"], "failed")
        self.assertNotIn("route_trace", params)
        self.assertNotIn("revised_prompt", params)
        self.assertEqual(len(FakeThread.started), 1)
        self.assertIs(FakeThread.started[0].target, server._run_generation_target)
        self.assertIs(FakeThread.started[0].args[0], server.process_gpt_task)

    def test_edit_retry_is_rejected_without_original_images(self):
        original = {
            "task_id": "edit_old",
            "status": "failed",
            "prompt": "edit me",
            "type": "gpt-edit",
            "params": {"source_image_count": 1},
        }

        with patch.object(server, "create_task") as create_task:
            with self.assertRaises(server.TaskRetryError):
                server.retry_failed_task(original)

        create_task.assert_not_called()


class StatusPayloadTest(unittest.TestCase):
    def test_google_status_derives_image_paths_from_result_file(self):
        captured = {}

        class FakeHandler:
            def send_json(self, data, status=200, extra_headers=None):
                captured["data"] = data
                captured["status"] = status

        task = {
            "task_id": "google_1",
            "status": "succeeded",
            "type": "google-gen",
            "prompt": "city",
            "result_file": "flash_20260624.png",
            "result_files": [],
            "params": {},
        }

        with patch.object(server, "get_task", return_value=task):
            server.RequestHandler.handle_status(FakeHandler(), "google_1")

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["data"]["result_file"], "flash_20260624.png")
        self.assertEqual(captured["data"]["result_files"], ["flash_20260624.png"])
        self.assertEqual(captured["data"]["output_files"], ["flash_20260624.png"])
        self.assertEqual(captured["data"]["image_paths"], ["/image/flash_20260624.png"])
        self.assertEqual(captured["data"]["image_count"], 1)

    def test_status_payload_keeps_display_error_and_run_fields(self):
        captured = {}

        class FakeHandler:
            def send_json(self, data, status=200, extra_headers=None):
                captured["data"] = data
                captured["status"] = status

        task = {
            "task_id": "google_fail",
            "status": "failed",
            "type": "google-gen",
            "prompt": "city",
            "params": {},
            "error": "原始失败",
            "display_error": "Google 图像生成被安全策略拦截（PROHIBITED_CONTENT）",
            "error_code": "google.prohibited_content",
            "error_category": "safety",
            "raw_error": "HTTP 错误 500：request blocked by Gemini API: PROHIBITED_CONTENT",
            "last_run_id": "run_123",
            "run_count": 2,
        }

        with patch.object(server, "get_task", return_value=task):
            server.RequestHandler.handle_status(FakeHandler(), "google_fail")

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["data"]["display_error"], "Google 图像生成被安全策略拦截（PROHIBITED_CONTENT）")
        self.assertEqual(captured["data"]["error_code"], "google.prohibited_content")
        self.assertEqual(captured["data"]["error_category"], "safety")
        self.assertEqual(captured["data"]["raw_error"], "HTTP 错误 500：request blocked by Gemini API: PROHIBITED_CONTENT")
        self.assertEqual(captured["data"]["last_run_id"], "run_123")
        self.assertEqual(captured["data"]["run_count"], 2)


class TaskBatchTest(unittest.TestCase):
    def test_create_gpt_batch_tasks_adds_shared_batch_metadata(self):
        prompts = ["first prompt", "second prompt"]
        params = {
            "ratio": "16:9",
            "resolution": "4k",
            "quality": "high",
            "imageCount": 1,
            "promptMode": "smart",
            "gptProviderRoute": "codex",
        }

        with patch.object(server.time, "time", return_value=1710000000), \
             patch.object(server.random, "randint", side_effect=[9000, 1111, 2222]), \
             patch.object(server, "create_task") as create_task:
            batch_id, tasks = server._create_batch_tasks("gpt", prompts, params)

        self.assertEqual(batch_id, "batch_1710000000_9000")
        self.assertEqual([task["task_id"] for task in tasks], [
            "gpt_1710000000_1111_1",
            "gpt_1710000000_2222_2",
        ])
        self.assertEqual(create_task.call_count, 2)
        first_params = create_task.call_args_list[0].args[2]
        self.assertEqual(first_params["batch_id"], batch_id)
        self.assertEqual(first_params["batch_index"], 1)
        self.assertEqual(first_params["batch_total"], 2)
        self.assertEqual(first_params["ratio"], "16:9")
        self.assertEqual(first_params["resolution"], "4k")
        self.assertEqual(first_params["quality"], "high")
        self.assertEqual(first_params["task_type"], "image")
        self.assertNotIn("route_trace", first_params)

    def test_batch_chatgpt_pool_parallel_limit_uses_capacity_and_image_count(self):
        tasks = [
            {
                "task_id": "b1",
                "prompt": "one",
                "type": "gpt",
                "params": {"gpt_provider_route": "chatgpt_pool", "image_count": 2},
            },
            {
                "task_id": "b2",
                "prompt": "two",
                "type": "gpt",
                "params": {"gpt_provider_route": "chatgpt_pool", "image_count": 2},
            },
            {
                "task_id": "b3",
                "prompt": "three",
                "type": "gpt",
                "params": {"gpt_provider_route": "chatgpt_pool", "image_count": 2},
            },
        ]

        with patch.object(server, "_collect_chatgpt_pool_status", return_value={"stats": {"capacity": 4}}), \
             patch.object(server, "_current_generation_limit", return_value=8):
            self.assertEqual(server._batch_chatgpt_pool_parallel_limit(tasks), 2)

        with patch.object(server, "_collect_chatgpt_pool_status", return_value={"stats": {"capacity": 4}}), \
             patch.object(server, "_current_generation_limit", return_value=1):
            self.assertEqual(server._batch_chatgpt_pool_parallel_limit(tasks), 1)

        codex_tasks = [dict(tasks[0], params={"gpt_provider_route": "codex", "image_count": 2})]
        self.assertEqual(server._batch_chatgpt_pool_parallel_limit(codex_tasks), 1)

    def test_process_batch_tasks_runs_account_pool_children_in_parallel(self):
        tasks = [
            {
                "task_id": f"b{i}",
                "prompt": f"prompt {i}",
                "type": "gpt",
                "params": {"gpt_provider_route": "chatgpt_pool", "image_count": 1},
            }
            for i in range(4)
        ]
        lock = threading.Lock()
        active = 0
        max_active = 0
        ran = []

        def fake_run(task):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                ran.append(task["task_id"])
            time.sleep(0.03)
            with lock:
                active -= 1

        old_sem = server._GENERATION_SEMAPHORE
        server._GENERATION_SEMAPHORE = threading.BoundedSemaphore(3)
        try:
            with patch.object(server, "_batch_chatgpt_pool_parallel_limit", return_value=3), \
                 patch.object(server, "_run_batch_task", side_effect=fake_run), \
                 patch.object(server, "get_batch_control", return_value="running"), \
                 patch.object(server, "get_task", return_value={}), \
                 patch.object(server, "update_task"):
                server.process_batch_tasks("batch_parallel", tasks)
        finally:
            server._GENERATION_SEMAPHORE = old_sem

        self.assertEqual(set(ran), {task["task_id"] for task in tasks})
        self.assertEqual(max_active, 3)

    def test_batch_summary_counts_status_groups(self):
        with patch.object(server, "get_all_tasks", return_value=[
            {
                "task_id": "b2",
                "status": "failed",
                "prompt": "two",
                "params": {"batch_id": "batch_a", "batch_index": 2, "batch_total": 3},
                "type": "gpt",
                "result_files": [],
            },
            {
                "task_id": "b1",
                "status": "succeeded",
                "prompt": "one",
                "params": {"batch_id": "batch_a", "batch_index": 1, "batch_total": 3},
                "type": "gpt",
                "result_file": "one.png",
                "result_files": ["one.png"],
            },
            {
                "task_id": "other",
                "status": "queued",
                "prompt": "other",
                "params": {"batch_id": "batch_b", "batch_index": 1, "batch_total": 1},
                "type": "gpt",
                "result_files": [],
            },
        ]):
            summary = server.get_batch_summary("batch_a")

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["counts"]["total"], 2)
        self.assertEqual(summary["counts"]["succeeded"], 1)
        self.assertEqual(summary["counts"]["failed"], 1)
        self.assertEqual([task["task_id"] for task in summary["tasks"]], ["b1", "b2"])

    def test_batch_summary_reports_paused_control(self):
        with patch.object(server, "get_all_tasks", return_value=[
            {
                "task_id": "b1",
                "status": "queued",
                "prompt": "one",
                "params": {
                    "batch_id": "batch_paused",
                    "batch_index": 1,
                    "batch_total": 2,
                    "batch_control": "paused",
                },
                "type": "gpt",
                "result_files": [],
            },
            {
                "task_id": "b2",
                "status": "queued",
                "prompt": "two",
                "params": {
                    "batch_id": "batch_paused",
                    "batch_index": 2,
                    "batch_total": 2,
                    "batch_control": "paused",
                },
                "type": "gpt",
                "result_files": [],
            },
        ]):
            summary = server.get_batch_summary("batch_paused")

        self.assertEqual(summary["status"], "paused")
        self.assertEqual(summary["control"], "paused")
        self.assertEqual(summary["counts"]["queued"], 2)

    def test_cancel_batch_queued_tasks_skips_completed_tasks(self):
        tasks = [
            {
                "task_id": "done",
                "status": "succeeded",
                "prompt": "done",
                "params": {"batch_id": "batch_cancel", "batch_index": 1},
                "type": "gpt",
                "result_files": [],
            },
            {
                "task_id": "queued",
                "status": "queued",
                "prompt": "queued",
                "params": {"batch_id": "batch_cancel", "batch_index": 2},
                "type": "gpt",
                "result_files": [],
            },
            {
                "task_id": "processing",
                "status": "processing",
                "prompt": "processing",
                "params": {"batch_id": "batch_cancel", "batch_index": 3},
                "type": "gpt",
                "result_files": [],
            },
        ]

        with patch.object(server, "get_all_tasks", return_value=tasks), \
             patch.object(server, "update_task_fields") as update_task_fields:
            changed = server.cancel_batch_queued_tasks("batch_cancel")

        self.assertEqual(changed, 2)
        self.assertEqual([call.args[0] for call in update_task_fields.call_args_list], ["queued", "processing"])


class TaskStartupRecoveryTest(unittest.TestCase):
    def test_restart_fails_all_in_progress_tasks_immediately(self):
        from backend import database

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.db"
            now = int(time.time())
            with patch.object(database, "DB_PATH", str(db_path)):
                database.init_db()
                database.create_task("processing", "p", {}, status="processing", task_type="gpt")
                database.create_task("fallback", "p", {}, status="fallback_running", task_type="gpt")
                database.create_task("queued", "p", {}, status="queued", task_type="gpt")
                database.create_task("done", "p", {}, status="succeeded", task_type="gpt")

                changed = database.fail_stale_processing_tasks(max_age_seconds=0)
                tasks = {task["task_id"]: task for task in database.get_all_tasks(limit=10)}

        self.assertEqual(changed, 2)
        self.assertEqual(tasks["processing"]["status"], "failed")
        self.assertEqual(tasks["fallback"]["status"], "failed")
        self.assertEqual(tasks["processing"]["transport_error_type"], "OrphanedTask")
        self.assertEqual(tasks["processing"]["error"], "生成进程已中断，请重新提交任务")
        self.assertGreaterEqual(tasks["processing"]["finished_at"], now)
        self.assertEqual(tasks["queued"]["status"], "queued")
        self.assertEqual(tasks["done"]["status"], "succeeded")


class GenerationTrackingDbTest(unittest.TestCase):
    def test_generation_run_tables_and_history_fields_exist(self):
        from backend import database
        from backend import generation_tracking

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.db"
            with patch.object(database, "DB_PATH", str(db_path)), patch.object(generation_tracking, "get_db", database.get_db):
                database.init_db()
                database.create_task("task_1", "prompt", {"ratio": "1:1"}, status="queued", task_type="gpt")
                run = generation_tracking.start_generation_run(
                    "task_1",
                    "gpt",
                    provider="codex",
                    route="codex",
                    prompt="prompt",
                    params={"ratio": "1:1"},
                )
                generation_tracking.record_generation_event(
                    run["run_id"],
                    "task_1",
                    "provider_call_started",
                    "开始调用 Codex",
                    stage="calling_gpt",
                    payload={"provider": "codex"},
                )
                error_info = generation_tracking.translate_generation_error(
                    "HTTP 错误 500：request blocked by Gemini API: PROHIBITED_CONTENT",
                    provider="google",
                    route="google_gen",
                    task_type="google-gen",
                )
                generation_tracking.finish_generation_run(
                    run["run_id"],
                    "task_1",
                    status="failed",
                    stage="failed",
                    provider="codex",
                    route="codex",
                    error_info=error_info,
                    error_type="RuntimeError",
                )

                task = database.get_task("task_1")
                runs = generation_tracking.get_generation_runs("task_1")
                events = generation_tracking.get_generation_events(run["run_id"])

        self.assertEqual(task["last_run_id"], run["run_id"])
        self.assertEqual(task["run_count"], 1)
        self.assertEqual(task["error_code"], "google.prohibited_content")
        self.assertTrue(task["display_error"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], run["run_id"])
        self.assertEqual(runs[0]["error_code"], "google.prohibited_content")
        self.assertEqual(len(events), 1)
        payload = json.loads(events[0]["payload"]) if events[0].get("payload") else {}
        self.assertEqual(payload.get("provider"), "codex")


if __name__ == "__main__":
    unittest.main()
