import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from backend.moss import contracts, lora_adapter, prompt_cache, runtime as runtime_module, worker
from backend.moss.model_store import ResolvedModel
from backend.moss.runtime import MossCancelled, MossError, Runtime, worker_spec
from tests.test_moss_lora_adapter import peft_pair, write_safetensors

ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["PYTHONPATH"])
from backend.moss.contracts import WORKER_PREFIX
def emit(event, **extra):
    print(WORKER_PREFIX + json.dumps({"event": event, **extra}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request["command"] == "shutdown":
        break
    spec, job = request["spec"], request["job_id"]
    Path = __import__("pathlib").Path
    if spec["behavior"] == "hang":
        time.sleep(60)
    if spec["behavior"] == "crash":
        os._exit(7)
    if spec["behavior"] == "error":
        emit("error", job_id=job, message="boom")
        continue
    emit("progress", ratio=0.5, stage="half")
    output = Path(request["job_dir"]) / "output.png"
    output.write_bytes(b"png")
    emit("result", job_id=job, paths=[str(output)], seed=1)
'''


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.component = self.base / "components" / "moss"
        self.component.mkdir(parents=True)
        (self.component / "installed.json").write_text(json.dumps({"python": sys.executable}))
        self.fake = self.base / "fake_worker.py"
        self.fake.write_text(FAKE_WORKER)

    def runtime(self, **options):
        instance = Runtime(self.component, worker=self.fake, **options)
        self.addCleanup(instance.close)
        return instance

    def job_dir(self, name="job"):
        path = self.base / name
        path.mkdir()
        return path


class Supervision(Base):
    def test_defaults_follow_the_spec(self):
        instance = self.runtime()
        self.assertEqual((instance.timeout, instance.idle_seconds, instance.prefix),
                         (3600, 600, contracts.WORKER_PREFIX))
        self.assertEqual(Path(Runtime(self.component).worker_path).name, "worker.py")

    def test_worker_result_and_progress(self):
        seen = []
        result = self.runtime().execute({"behavior": "ok"}, self.job_dir(), threading.Event(),
                                        lambda ratio, stage: seen.append((ratio, stage)))
        self.assertEqual(result["paths"][0].name, "output.png")
        self.assertIn((0.5, "half"), seen)

    def test_shared_lease_wait_can_be_cancelled_before_the_worker_starts(self):
        lock = self.component.parent / ".local-inference.lock"
        cancelled, stages, errors = threading.Event(), [], []
        instance = self.runtime()
        with lock.open("a+b") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            def run():
                try:
                    instance.execute({"behavior": "ok"}, self.job_dir(), cancelled, lambda _r, s: stages.append(s))
                except MossCancelled as error:
                    errors.append(error)

            thread = threading.Thread(target=run)
            thread.start()
            deadline = time.monotonic() + 5
            while not stages and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertIn("等待本地推理资源", stages)
            cancelled.set()
            thread.join(5)
        self.assertTrue(errors)
        self.assertIsNone(instance._process)

    def test_before_load_runs_under_the_lease(self):
        calls = []
        instance = self.runtime(before_load=lambda: calls.append("release_other"))
        instance.execute({"behavior": "ok"}, self.job_dir(), threading.Event(), lambda *_: None)
        self.assertEqual(calls, ["release_other"])

    def test_timeout_kills_the_worker(self):
        instance = self.runtime(timeout=1)
        with self.assertRaisesRegex(MossError, "超过时限"):
            instance.execute({"behavior": "hang"}, self.job_dir(), threading.Event(), lambda *_: None)
        self.assertIsNone(instance._process)

    def test_cancel_stops_a_hung_worker(self):
        cancelled = threading.Event()
        threading.Timer(0.3, cancelled.set).start()
        with self.assertRaises(MossCancelled):
            self.runtime().execute({"behavior": "hang"}, self.job_dir(), cancelled, lambda *_: None)

    def test_crash_and_reported_error_fail_the_job(self):
        instance = self.runtime()
        with self.assertRaisesRegex(MossError, "异常退出"):
            instance.execute({"behavior": "crash"}, self.job_dir("a"), threading.Event(), lambda *_: None)
        with self.assertRaisesRegex(MossError, "boom"):
            instance.execute({"behavior": "error"}, self.job_dir("b"), threading.Event(), lambda *_: None)

    def test_idle_worker_exits(self):
        instance = self.runtime(idle_seconds=1)
        instance.execute({"behavior": "ok"}, self.job_dir(), threading.Event(), lambda *_: None)
        process = instance._process
        self.assertIsNone(process.poll())
        process.wait(timeout=5)
        self.assertIsNone(instance._process)

    def test_missing_environment_is_an_error(self):
        (self.component / "installed.json").unlink()
        with self.assertRaises(MossError):
            self.runtime().execute({"behavior": "ok"}, self.job_dir(), threading.Event(), lambda *_: None)

    def test_child_is_offline_and_has_no_ambient_pythonpath_entries(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/elsewhere"}):
            env = self.runtime().child_environment()
        self.assertEqual(env["PYTHONPATH"], str(ROOT))
        self.assertEqual((env["HF_HUB_OFFLINE"], env["TRANSFORMERS_OFFLINE"]), ("1", "1"))
        self.assertTrue(env["MOSS_MLX_CACHE"].startswith(str(self.component)))

    def test_real_worker_stops_with_its_parent(self):
        script = (f"import sys,os\nsys.path.insert(0,{str(ROOT)!r})\nfrom pathlib import Path\n"
                  "from backend.moss.runtime import Runtime\n"
                  f"r=Runtime(Path({str(self.component)!r}))\np=r._start()\nprint(p.pid,flush=True)\nos._exit(0)")
        pid = int(subprocess.check_output([sys.executable, "-c", script], text=True, timeout=30).strip())
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.kill(pid, 9)
        self.fail("worker outlived its parent")

    def test_server_side_modules_do_not_import_heavy_runtimes(self):
        code = ("import sys\n"
                f"sys.path.insert(0,{str(ROOT)!r})\n"
                "import backend.moss.runtime, backend.moss.worker\n"
                "bad=[m for m in ('mlx','mlx.core','moss_image_mlx','transformers','torch') if m in sys.modules]\n"
                "print(bad)\nraise SystemExit(bool(bad))")
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=60)


class TokenBudget(Base):
    def setUp(self):
        super().setUp()
        store_view = self.base / "view"
        (store_view / "tokenizer").mkdir(parents=True)
        self.model = ResolvedModel("id", store_view, Path("s"), Path("d"), "f" * 64)
        self.store = types.SimpleNamespace(resolve=lambda: self.model)

    def probe_returning(self, *counts):
        output = json.dumps({"counts": list(counts)})
        return patch.object(runtime_module.subprocess, "run",
                            return_value=types.SimpleNamespace(stdout=output + "\n"))

    def test_exactly_at_the_limit_passes_and_one_over_is_rejected(self):
        instance = self.runtime(model_store=self.store)
        with self.probe_returning(4096, 3):
            result = instance.inspect_prompt("x")
        self.assertEqual((result["checked"], result["valid"], result["prompt_tokens"]), (True, True, 4096))
        with self.probe_returning(4097, 3):
            result = instance.inspect_prompt("x")
        self.assertEqual((result["checked"], result["valid"]), (True, False))
        self.assertIn("4096", result["reason"])

    def test_oversized_negative_is_rejected_too(self):
        with self.probe_returning(5, 4097):
            self.assertFalse(self.runtime(model_store=self.store).inspect_prompt("x")["valid"])

    def test_unprepared_or_unbound_is_unchecked_not_passed(self):
        (self.component / "installed.json").unlink()
        result = self.runtime(model_store=self.store).inspect_prompt("x")
        self.assertEqual((result["checked"], result["valid"]), (False, None))
        (self.component / "installed.json").write_text(json.dumps({"python": sys.executable}))
        result = self.runtime(model_store=None).inspect_prompt("x")
        self.assertEqual((result["checked"], result["valid"]), (False, None))

    def test_probe_failure_is_unchecked(self):
        instance = self.runtime(model_store=self.store)
        with patch.object(runtime_module.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            result = instance.inspect_prompt("x")
        self.assertEqual((result["checked"], result["valid"]), (False, None))

    def test_probe_sends_prompt_on_stdin_isolated_and_takes_no_lease(self):
        instance = self.runtime(model_store=self.store)
        with self.probe_returning(1, 1) as run, patch.object(runtime_module.JsonLineRuntime, "execute") as execute:
            instance.inspect_prompt("秘密提示词", "")
        command = run.call_args.args[0]
        self.assertEqual(command[1], "-I")
        self.assertFalse(any("秘密" in part for part in command))
        self.assertIn("秘密", run.call_args.kwargs["input"])
        execute.assert_not_called()

    def test_probe_file_stays_free_of_mlx_and_backend(self):
        source = runtime_module.PROBE.read_text()
        self.assertNotIn("mlx", source.replace("MLX", "").replace("free of mlx", ""))
        self.assertNotIn("from backend", source)

    def test_count_uses_the_template_and_never_truncates(self):
        calls = {}

        class Tokenizer:
            def apply_chat_template(self, messages, **options):
                calls["template"] = options
                return messages[0]["content"] + "!"

            def __call__(self, text, truncation):
                calls["truncation"] = truncation
                return {"input_ids": list(text)}

        self.assertEqual(worker.count_tokens(Tokenizer(), "abc"), 4)
        self.assertEqual(calls["template"], {"tokenize": False, "add_generation_prompt": True, "enable_thinking": True})
        self.assertIs(calls["truncation"], False)


class PromptCacheBudget(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def entry(self, name, size, age):
        path = self.root / "a" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"x" * size)
        os.utime(path, (age, age))
        return path

    def test_evicts_oldest_until_within_budget(self):
        old, middle, new = self.entry("o.safetensors", 10, 100), self.entry("m.safetensors", 10, 200), \
            self.entry("n.safetensors", 10, 300)
        self.assertEqual(prompt_cache.evict(self.root, limit=15), 2)
        self.assertEqual((old.exists(), middle.exists(), new.exists()), (False, False, True))

    def test_default_budget_is_two_gib(self):
        self.assertEqual(prompt_cache.MAX_BYTES, 2 * 1024**3)

    def test_current_entries_survive(self):
        old, new = self.entry("o.safetensors", 10, 100), self.entry("n.safetensors", 10, 300)
        prompt_cache.evict(self.root, limit=5, keep=[old])
        self.assertTrue(old.exists())
        self.assertFalse(new.exists())

    def test_touch_refreshes_hits_and_ignores_misses(self):
        hit = self.entry("h.safetensors", 1, 100)
        cache = types.SimpleNamespace(_path=lambda prompt, limit: hit if prompt == "hit" else self.root / "miss")
        prompt_cache.touch(cache, ["hit", "miss"], 4096)
        self.assertGreater(hit.stat().st_mtime, 1000)
        self.assertFalse((self.root / "miss").exists())


class Tensor:
    def __init__(self, length):
        self.shape = (1, length, 4096)


class FakePipe:
    def __init__(self, backend):
        self.backend = backend
        self.cache = types.SimpleNamespace(_path=lambda prompt, limit: backend.root / "cache-entry")

    def denoise(self, request, positive, negative, on_step):
        self.backend.calls.append("denoise")
        self.backend.requested = request
        on_step(0, 15)
        if self.backend.cancel_during:
            self.backend.cancel_during.touch()
            on_step(1, 15)
        return "latents"

    def decode(self, latents):
        return "image"


class FakeTokenizer:
    def apply_chat_template(self, messages, **_options):
        return messages[0]["content"]

    def __call__(self, text, truncation):
        return {"input_ids": list(text)}


class FakeBackend:
    def __init__(self, root):
        self.root, self.calls, self.stack, self.requested = root, [], None, None
        self.cancel_during, self.encoded_lengths = None, None

    def tokenizer(self, view):
        return FakeTokenizer()

    def pipeline(self, view, cache_dir, stack):
        self.calls.append("pipeline")
        self.stack, self.cache_dir = stack, cache_dir
        return FakePipe(self)

    def encode(self, pipe, prompts, max_tokens):
        self.calls.append("encode")
        return [Tensor(length) for length in (self.encoded_lengths or [len(text) for text in prompts])]

    def request(self, kwargs):
        return kwargs

    def save_png(self, image, path):
        Path(path).write_bytes(b"png")


class Job(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.events = []
        patcher = patch.object(worker, "emit", lambda event, **extra: self.events.append((event, extra)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = FakeBackend(self.root)

    def spec(self, preset="turbo", loras=(), prompt="hello"):
        job = contracts.normalize_job({"mode": "text", "prompt": prompt, "preset": preset, "seed": 7,
                                       "loras": [{"asset_id": sha, "scale": scale} for sha, _, scale in loras]})
        model = ResolvedModel("id", self.root / "view", self.root / "student", self.root / "destripe", "e" * 64)
        resolved = [(path, {"asset_id": sha, "name": path.name}) for sha, path, _ in loras]
        return worker_spec(job, model, resolved, prompt, state_root=self.root / "state")

    def run_job(self, spec):
        request = {"job_dir": str(self.root), "cancel_file": str(self.root / "cancel"), "spec": spec}
        return worker.run_job(request, self.backend)

    def lora(self, name="a.safetensors"):
        path = write_safetensors(self.root / name, peft_pair(0, "qkv", 9216))
        return "a" * 64, path, 0.7

    def test_turbo_stack_and_fixed_schedule(self):
        result = self.run_job(self.spec())
        self.assertEqual([item[3] for item in self.backend.stack], ["destripe", "student"])
        self.assertEqual(self.backend.stack[0][1:3], (1.5, "bfloat16"))
        self.assertEqual(self.backend.stack[1][1:3], (1.0, "float32"))
        request = self.backend.requested
        self.assertEqual((request["turbo"], request["steps"], request["guidance"], request["shift"]),
                         (True, 50, 3.0, 5.0))
        self.assertEqual(request["uncond_skip_layers"], [22])
        self.assertEqual(result["effective"]["sampler"]["network_passes"], 15)

    def test_standard_never_loads_the_student(self):
        result = self.run_job(self.spec("standard"))
        self.assertEqual([item[3] for item in self.backend.stack], ["destripe"])
        request = self.backend.requested
        self.assertEqual((request["turbo"], request["steps"], request["guidance"]), (False, 50, 3.0))
        self.assertEqual(result["effective"]["managed_adapters"], [{"id": "destripe", "scale": 1.5}])

    def test_ordinary_lora_stays_outside_the_student_group_on_both_presets(self):
        for preset in ("turbo", "standard"):
            self.run_job(self.spec(preset, [self.lora()]))
            group = self.backend.stack[-1]
            self.assertEqual((group[1], group[2], group[3]), (0.7, "float16", "ordinary"))

    def test_lora_is_prepared_before_the_pipeline_and_reported(self):
        original = lora_adapter.prepare

        def recording(*args):
            self.backend.calls.append("prepare")
            return original(*args)

        with patch.object(lora_adapter, "prepare", recording):
            self.run_job(self.spec("turbo", [self.lora()]))
        self.assertLess(self.backend.calls.index("prepare"), self.backend.calls.index("pipeline"))
        self.assertTrue(any(extra.get("stage") == "准备LoRA" for _, extra in self.events))
        path = Path(self.backend.stack[-1][0])
        self.assertEqual(path.parent, self.root / "state" / "cache" / "lora")

    def test_failed_lora_fails_the_job_and_names_the_file(self):
        bad = self.root / "broken.safetensors"
        bad.write_bytes(b"not a lora file")
        with self.assertRaisesRegex(RuntimeError, "准备LoRA失败（broken.safetensors）"):
            self.run_job(self.spec("turbo", [("b" * 64, bad, 1.0)]))
        self.assertNotIn("pipeline", self.backend.calls)

    def test_over_budget_is_rejected_before_any_model_load(self):
        with self.assertRaisesRegex(ValueError, "4096"):
            self.run_job(self.spec(prompt="x" * 4097))
        self.assertEqual(self.backend.calls, [])

    def test_encoded_length_mismatch_fails(self):
        self.backend.encoded_lengths = [4, 0]
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            self.run_job(self.spec())
        self.assertNotIn("denoise", self.backend.calls)

    def test_prompt_cache_is_partitioned_by_the_binding_fingerprint(self):
        self.run_job(self.spec())
        self.assertEqual(self.backend.cache_dir, self.root / "state/cache/prompt-embeds" / ("e" * 16))

    def test_cancel_before_load_and_between_steps(self):
        (self.root / "cancel").touch()
        with self.assertRaises(worker.Cancelled):
            self.run_job(self.spec())
        (self.root / "cancel").unlink()
        self.backend.cancel_during = self.root / "cancel"
        with self.assertRaises(worker.Cancelled):
            self.run_job(self.spec())
        self.assertFalse((self.root / "output.png").exists())

    def test_result_holds_real_values_and_no_local_paths_in_effective(self):
        result = self.run_job(self.spec("turbo", [self.lora()]))
        self.assertEqual(Path(result["paths"][0]).name, "output.png")
        self.assertEqual(result["seed"], 7)
        effective = result["effective"]
        self.assertEqual(effective["prompt_tokens"], 5)
        self.assertEqual(effective["loras"][0]["converter"], lora_adapter.CONVERTER_VERSION)
        self.assertNotIn(str(self.root), json.dumps(effective))

    def test_serve_reports_outcomes_and_releases_every_time(self):
        released = []

        class Backend(FakeBackend):
            def release(self):
                released.append(True)

        backend = Backend(self.root)
        job = {"command": "generate", "job_id": "j", "job_dir": str(self.root),
               "cancel_file": str(self.root / "cancel"), "spec": self.spec()}
        bad = {**job, "job_id": "k", "spec": self.spec("turbo", prompt="x" * 4097)}
        lines = [json.dumps(job), json.dumps(bad), "not json", json.dumps({"command": "shutdown"}), json.dumps(job)]
        with patch.object(worker.traceback, "print_exc"):
            worker.serve(lines, lambda: backend)
        outcomes = [(event, extra.get("job_id")) for event, extra in self.events if event in {"result", "error"}]
        self.assertEqual(outcomes, [("result", "j"), ("error", "k")])
        self.assertEqual(len(released), 2)


if __name__ == "__main__":
    unittest.main()
