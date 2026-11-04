import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from backend.moss.contracts import TASK_TYPE, TERMINAL
from backend.moss.model_store import ResolvedModel
from backend.moss.service import Service

STORYBOARD = {"rows": 2, "cols": 2, "margin": 8, "gutter": 8, "panels": [{"id": f"p{i}", "caption": f"镜头{i}"} for i in range(4)]}


class Tasks:
    def __init__(self):
        self.items = {}

    def create(self, task_id, prompt, params, status, task_type):
        self.items[task_id] = {"task_id": task_id, "prompt": prompt, "params": copy.deepcopy(params),
                               "status": status, "type": task_type}

    def get(self, task_id):
        return copy.deepcopy(self.items.get(task_id))

    def all(self, limit):
        return [copy.deepcopy(item) for item in self.items.values()]

    def update(self, task_id, status, **fields):
        if "result_files" in fields:
            fields["result_files"] = json.loads(fields["result_files"])
        self.items[task_id].update(status=status, **fields)

    def status(self, task_id, status, text, **fields):
        self.items[task_id].update(status=status, **fields)

    def fields(self, task_id, params):
        self.items[task_id]["params"] = json.loads(params)


class FakeRuntime:
    def __init__(self):
        self.status_value = {"ready": True, "reasons": []}
        self.budget = {"checked": True, "valid": True, "prompt_tokens": 5, "negative_tokens": 1, "max_tokens": 4096,
                       "reason": None}
        self.gate = threading.Event()
        self.gate.set()
        self.specs, self.invalidated, self.closed = [], 0, False

    def status(self):
        return dict(self.status_value)

    def invalidate_status(self):
        self.invalidated += 1

    def inspect_prompt(self, prompt, negative, maximum):
        self.inspected = (prompt, negative, maximum)
        return dict(self.budget)

    def execute(self, spec, directory, cancel, progress):
        self.specs.append(spec)
        self.gate.wait(5)
        output = Path(directory) / "output.png"
        output.write_bytes(b"png")
        return {"paths": [output], "seed": spec["seed"], "effective": {}}

    def close(self):
        self.closed = True


class FakeModels:
    def __init__(self, root):
        self.model = ResolvedModel("moss-image-sft-mflux-bf16", root / "secret-view", root / "secret-student",
                                   root / "secret-destripe", "f" * 64)
        self.error = None

    def resolve(self, model_id="x"):
        if self.error:
            raise ValueError(self.error)
        return self.model

    def list(self):
        return [self.public()]

    def public(self, model_id="moss-image-sft-mflux-bf16"):
        return {"model_id": model_id, "ready": not self.error, "reason": self.error, "fingerprint": "f" * 64,
                "bound_at": 1}


class FakeLoras:
    def __init__(self):
        self.deleted = []

    def list(self):
        return []

    def scan_errors(self):
        return []

    def resolve(self, asset_id):
        if asset_id == "9" * 64:
            raise ValueError("LoRA 资产不存在，请检查 LoRA 目录")
        return Path("/secret/lora.safetensors"), {"asset_id": asset_id, "name": "风格"}

    def delete(self, asset_id):
        self.deleted.append(asset_id)
        return {"asset_id": asset_id}


class FakePreparation:
    def __init__(self):
        self.state = {"status": "idle"}
        self.commands = []

    def status(self):
        return dict(self.state)

    def start(self, command, cwd, metadata):
        self.commands.append(command)
        self.state = {"status": "succeeded", **metadata}
        return {"ok": True, "preparation": dict(self.state), "already_running": False}

    def close(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.tasks, self.runtime = Tasks(), FakeRuntime()
        self.models, self.loras, self.preparation = FakeModels(self.root), FakeLoras(), FakePreparation()
        self.published = []
        self.service = Service(self.root / "state", self.root / "component", self.runtime,
                               create_task=self.tasks.create, get_task=self.tasks.get, get_all_tasks=self.tasks.all,
                               update_task=self.tasks.update, update_task_status=self.tasks.status,
                               update_task_fields=self.tasks.fields, daily_output_dir=lambda: self.root / "archive",
                               write_prompt_sidecar=lambda *a, **k: None, send_document=lambda *a: None,
                               publisher=self.publish, model_store=self.models, lora_store=self.loras,
                               preparation=self.preparation)
        self.addCleanup(self.finish)

    def finish(self):
        self.runtime.gate.set()
        self.service.close()

    def publish(self, task_id, task, result, **ports):
        self.published.append((task_id, ports["job_dir"]))
        outcome = {"published": True, "status": "succeeded_no_telegram", "result_file": "a.png",
                   "result_files": ["a.png"], "params": {**task["params"], "artifacts": [{"file": "a.png"}]},
                   "artifacts": [], "warnings": [], "telegram_error": None}
        ports["on_archived"](outcome)
        return outcome

    def wait_done(self, task_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.tasks.get(task_id)["status"] in TERMINAL:
                return
            time.sleep(0.01)
        self.fail("task did not finish")


class Compile(Base):
    def test_text_compile_reports_budget_and_echoes_fingerprint(self):
        result = self.service.compile({"mode": "text", "prompt": "猫", "input_fingerprint": "abc"})
        self.assertEqual((result["kind"], result["input_fingerprint"]), ("compiled", "abc"))
        self.assertEqual(result["compiled"]["prompt"], "猫")
        self.assertTrue(result["token_budget"]["valid"])
        self.assertEqual(result["model_fingerprint"], "f" * 64)
        self.assertEqual(self.runtime.inspected, ("猫", "", 4096))

    def test_negative_prompt_is_counted_in_the_budget(self):
        self.service.compile({"mode": "text", "prompt": "猫", "negative_prompt": "模糊"})
        self.assertEqual(self.runtime.inspected, ("猫", "模糊", 4096))

    def test_unchecked_budget_stays_unchecked(self):
        self.runtime.budget = {"checked": False, "valid": None}
        self.assertIsNone(self.service.compile({"mode": "text", "prompt": "x"})["token_budget"]["valid"])

    def test_import_never_looks_like_a_compile(self):
        result = self.service.compile({"draft_json": json.dumps({"caption": "春日"})})
        self.assertEqual(result["kind"], "import_draft")
        self.assertNotIn("compiled", result)
        self.assertNotIn("token_budget", result)

    def test_import_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            self.service.compile({"draft_json": '{"a":1,"a":2}'})


class Submit(Base):
    def body(self, **extra):
        return {"mode": "text", "prompt": "一只猫", "seed": 3, **extra}

    def test_client_cannot_supply_a_final_prompt_or_paths(self):
        for field in ("final_prompt", "compiled_prompt", "model_path", "sampler", "steps"):
            with self.assertRaisesRegex(ValueError, "未知字段"):
                self.service.submit(self.body(**{field: "x"}))
        self.assertEqual(self.tasks.items, {})

    def test_negative_prompt_reaches_worker_budget_and_params(self):
        result = self.service.submit(self.body(negative_prompt="模糊"))
        self.assertEqual(self.runtime.inspected[1], "模糊")
        self.assertEqual(self.tasks.get(result["task_id"])["params"]["negative_prompt"], "模糊")
        self.wait_done(result["task_id"])
        self.assertEqual(self.runtime.specs[0]["sampler"]["negative_prompt"], "模糊")

    def test_storyboard_is_recompiled_on_the_server(self):
        result = self.service.submit({"mode": "storyboard", "prompt": "茶园", "layout_draft": STORYBOARD, "seed": 1})
        task = self.tasks.get(result["task_id"])
        self.assertTrue(task["prompt"].startswith('{"summary"'))
        self.assertIn("单一画布", task["prompt"])
        self.assertEqual(task["params"]["raw_prompt"], "茶园")
        self.assertEqual(len(task["params"]["geometry_spec"]["panels"]), 4)
        self.wait_done(result["task_id"])
        self.assertEqual(self.runtime.specs[0]["prompt"], task["prompt"])

    def test_task_flows_to_the_recorded_result(self):
        result = self.service.submit(self.body())
        self.assertRegex(result["task_id"], r"^moss_[0-9a-f]{32}$")
        self.wait_done(result["task_id"])
        task = self.tasks.get(result["task_id"])
        self.assertEqual((task["type"], task["status"], task["result_files"]),
                         (TASK_TYPE, "succeeded_no_telegram", ["a.png"]))
        self.assertTrue(task["params"]["artifacts"])
        self.assertEqual(self.published[0][1], self.root / "state/jobs" / result["task_id"])

    def test_job_copy_is_dropped_once_published(self):
        result = self.service.submit(self.body())
        self.wait_done(result["task_id"])
        path = self.root / "state/jobs" / result["task_id"] / "output.png"
        deadline = time.monotonic() + 5
        while path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(path.exists())

    def test_seed_is_resolved_once_and_returned(self):
        result = self.service.submit({"mode": "text", "prompt": "x"})
        self.wait_done(result["task_id"])
        self.assertEqual(self.runtime.specs[0]["seed"], result["seed"])

    def test_readiness_precedes_queueing(self):
        self.runtime.status_value = {"ready": False, "reasons": ["MOSS 环境尚未准备"]}
        with self.assertRaisesRegex(RuntimeError, "尚未准备"):
            self.service.submit(self.body())
        self.runtime.status_value = {"ready": True}
        self.models.error = "绑定已失效"
        with self.assertRaisesRegex(RuntimeError, "绑定已失效"):
            self.service.submit(self.body())
        self.assertEqual(self.tasks.items, {})

    def test_over_budget_and_unchecked_never_queue(self):
        self.runtime.budget = {"checked": True, "valid": False, "reason": "提示词超过 4096 token 上限"}
        with self.assertRaisesRegex(ValueError, "4096"):
            self.service.submit(self.body())
        self.runtime.budget = {"checked": False, "valid": None, "reason": "token 检查失败"}
        with self.assertRaisesRegex(RuntimeError, "token 检查失败"):
            self.service.submit(self.body())
        self.assertEqual(self.tasks.items, {})

    def test_snapshot_is_independent_of_the_request_body(self):
        draft = copy.deepcopy(STORYBOARD)
        result = self.service.submit({"mode": "storyboard", "prompt": "茶园", "layout_draft": draft, "seed": 1})
        draft["panels"][0]["caption"] = "改过"
        self.assertEqual(self.tasks.get(result["task_id"])["params"]["layout_draft"]["panels"][0]["caption"], "镜头0")

    def test_queue_capacity_is_backpressure_without_ghost_tasks(self):
        self.runtime.gate.clear()
        accepted = 0
        for _ in range(20):
            try:
                self.service.submit(self.body())
                accepted += 1
            except RuntimeError as error:
                self.assertIn("繁忙", str(error))
                break
        self.assertLessEqual(accepted, 9)
        self.assertEqual(len(self.tasks.items), accepted)
        self.assertEqual(len(list((self.root / "state/jobs").iterdir())), accepted)

    def test_public_task_has_no_private_paths(self):
        result = self.service.submit(self.body(loras=[{"asset_id": "a" * 64, "scale": 0.7}]))
        task = self.tasks.get(result["task_id"])
        self.assertNotIn("secret", json.dumps(task, ensure_ascii=False))
        self.assertEqual(task["params"]["loras"][0]["name"], "风格")
        self.wait_done(result["task_id"])
        self.assertEqual(self.runtime.specs[0]["model"]["view"], str(self.root / "secret-view"))
        self.assertEqual(self.runtime.specs[0]["loras"][0]["path"], "/secret/lora.safetensors")

    def test_missing_lora_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.service.submit(self.body(loras=[{"asset_id": "9" * 64, "scale": 1}]))

    def test_text_sources_must_match_submitted_content(self):
        good = hashlib.sha256("一只猫".encode()).hexdigest()
        trace = {"source_node_id": "n1", "target_id": "global", "field": "prompt", "content_hash": good}
        result = self.service.submit(self.body(text_sources=[trace]))
        self.assertEqual(self.tasks.get(result["task_id"])["params"]["text_sources"][0]["source_node_id"], "n1")
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.service.submit(self.body(text_sources=[{**trace, "content_hash": "0" * 64}]))

    def test_text_sources_target_regions_and_panels(self):
        panel = {"source_node_id": "n", "target_id": "p1", "field": "caption",
                 "content_hash": hashlib.sha256("镜头1".encode()).hexdigest()}
        self.service.submit({"mode": "storyboard", "prompt": "茶", "layout_draft": STORYBOARD, "text_sources": [panel]})
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.service.submit({"mode": "storyboard", "prompt": "茶", "layout_draft": STORYBOARD,
                                 "text_sources": [{**panel, "target_id": "p9"}]})

    def test_submit_refused_while_an_operation_runs(self):
        self.preparation.state = {"status": "running"}
        with self.assertRaisesRegex(RuntimeError, "准备或绑定"):
            self.service.submit(self.body())


class Operations(Base):
    def test_prepare_and_bind_return_an_operation_and_never_validate_inline(self):
        result = self.service.bind_model({"source_path": "/weights"})
        self.assertRegex(result["operation_id"], r"^mossop_")
        self.assertEqual(self.preparation.commands[0][-4:], ["-m", "backend.moss.environment", "bind", "/weights"])
        self.assertEqual(self.service.status()["preparation"]["operation_id"], result["operation_id"])

    def test_prepare_passes_the_optional_source(self):
        self.service.prepare({"source_path": "/weights"})
        self.assertEqual(self.preparation.commands[0][-3:], ["prepare", "--source", "/weights"])
        self.service.prepare({})
        self.assertEqual(self.preparation.commands[1][-1], "prepare")

    def test_relative_source_and_unknown_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            self.service.bind_model({"source_path": "relative"})
        with self.assertRaises(ValueError):
            self.service.prepare({"python": "/bin/sh"})
        self.assertEqual(self.preparation.commands, [])

    def test_operations_refuse_while_a_task_is_active(self):
        self.tasks.items["t"] = {"task_id": "t", "type": TASK_TYPE, "status": "processing"}
        for action in (lambda: self.service.prepare({}), lambda: self.service.bind_model({"source_path": "/w"})):
            with self.assertRaisesRegex(RuntimeError, "任务进行中"):
                action()

    def test_other_domains_tasks_do_not_block(self):
        self.tasks.items["t"] = {"task_id": "t", "type": "qwen21", "status": "processing"}
        self.service.prepare({})
        self.assertEqual(len(self.preparation.commands), 1)

    def test_finished_operation_refreshes_runtime_status(self):
        self.service.status()
        before = self.runtime.invalidated
        self.preparation.state = {"status": "succeeded", "operation_id": "x"}
        self.service.status()
        self.assertEqual(self.runtime.invalidated, before + 1)
        self.service.status()
        self.assertEqual(self.runtime.invalidated, before + 1)

    def test_status_combines_environment_and_model_without_paths(self):
        self.models.error = "尚未绑定"
        result = self.service.status()
        self.assertFalse(result["ready"])
        self.assertIn("尚未绑定", result["reasons"][0])
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))

    def test_catalog_is_public(self):
        result = self.service.catalog()
        self.assertEqual(result["models"][0]["model_id"], "moss-image-sft-mflux-bf16")
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))


class Lifecycle(Base):
    def test_cancel_only_accepts_this_domain(self):
        self.tasks.items["q"] = {"task_id": "q", "type": "qwen21", "status": "processing"}
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.service.cancel("q")
        self.assertEqual(self.tasks.get("q")["status"], "processing")

    def test_cancel_is_idempotent(self):
        self.runtime.gate.clear()
        task_id = self.service.submit({"mode": "text", "prompt": "x"})["task_id"]
        self.service.cancel(task_id)
        self.assertEqual(self.service.cancel(task_id)["status"], "canceled")

    def test_lora_in_use_cannot_be_deleted(self):
        self.tasks.items["t"] = {"task_id": "t", "type": TASK_TYPE, "status": "queued",
                                 "params": {"loras": [{"asset_id": "a" * 64}]}}
        with self.assertRaisesRegex(RuntimeError, "使用"):
            self.service.delete_lora("a" * 64)
        self.assertEqual(self.loras.deleted, [])
        self.tasks.items["t"]["status"] = "succeeded"
        self.service.delete_lora("a" * 64)
        self.assertEqual(self.loras.deleted, ["a" * 64])

    def test_recover_fails_leftovers_without_replaying(self):
        self.tasks.items.update({"a": {"task_id": "a", "type": TASK_TYPE, "status": "processing"},
                                 "b": {"task_id": "b", "type": TASK_TYPE, "status": "succeeded"},
                                 "c": {"task_id": "c", "type": "qwen21", "status": "processing"}})
        self.service.recover()
        self.assertEqual([self.tasks.items[key]["status"] for key in "abc"], ["failed", "succeeded", "processing"])
        self.assertEqual(self.runtime.specs, [])

    def test_runtime_receives_the_model_store(self):
        self.assertIs(self.runtime.model_store, self.models)


if __name__ == "__main__":
    unittest.main()
