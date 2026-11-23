"""Portable offline unit tests for the video_understand domain and HTTP routes."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

from backend.routes.video_understand_routes import create_router
from backend.video_edit.sources import SourceResolver, UnsupportedSource
from backend.video_understand import contracts, environment, prompts
from backend.video_understand.runtime import Runtime
from backend.video_understand.service import VideoUnderstandService
from backend.video_understand.storage import Store


def _create_fake_component(root: Path, *, worker_script: Path | None = None, model_dir: Path | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    src_base = environment.src_dir(root)
    assets = environment.load_assets()
    for rel, item in assets["source"]["files"].items():
        target = src_base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"s" * int(item["size"]))

    active_model = model_dir or environment.default_model_dir(root)
    if model_dir is None:
        active_model.mkdir(parents=True, exist_ok=True)
        for rel, item in assets["model"]["files"].items():
            target = active_model / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel == "config.json":
                payload = json.dumps({"model_type": "wemm_qwen3_5_moe", "quantization": {"bits": 6}}).encode("utf-8")
                target.write_bytes(payload.ljust(int(item["size"]), b" "))
            else:
                with target.open("wb") as stream:
                    stream.truncate(int(item["size"]))

    receipt = {
        "schema_version": 1,
        "python": sys.executable,
        "prepared_at": 1700000000,
        "versions": environment.pinned_packages(),
        "model_variant": contracts.MODEL_LABEL,
    }
    if model_dir is not None:
        receipt["model_dir"] = str(model_dir)
    (root / "installed.json").write_text(json.dumps(receipt), encoding="utf-8")
    return active_model


class _FakeHandler:
    def __init__(self, method: str, path: str, body: bytes = b""):
        self.command = method
        self.path = path
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.rfile = io.BytesIO(body)
        self.sent = []
        self.files = []

    def require_auth(self) -> bool:
        return True

    def send_json(self, payload, status=200):
        self.sent.append((status, payload))


class VideoUnderstandTests(unittest.TestCase):
    def test_contracts_normalize_presets_bounds_and_errors(self):
        spec = contracts.normalize({"video_url": "/video/clip.mp4", "mode": "storyboard"})
        self.assertEqual(spec["fps"], 1.5)
        self.assertEqual(spec["max_frames"], 96)
        self.assertTrue(spec["shot_anchors"])
        self.assertTrue(spec["use_audio"])
        self.assertFalse(spec["thinking"])

        h3_spec = contracts.normalize({"video_url": "/video/clip.mp4", "mode": "h3_prompt"})
        self.assertEqual(h3_spec["fps"], 2.0)
        self.assertEqual(h3_spec["max_frames"], 96)
        self.assertEqual(h3_spec["total_pixels"], 4194304)
        self.assertEqual(h3_spec["max_tokens"], 4096)
        self.assertTrue(h3_spec["shot_anchors"])
        self.assertEqual(h3_spec["min_shot_sec"], 0.8)

        clamped = contracts.normalize({
            "video_url": "/video/clip.mp4",
            "mode": "prompt_reverse",
            "fps": 99,
            "max_frames": 999,
            "total_pixels": 100,
            "max_tokens": 99999,
            "model_dir": "/etc/passwd",
        })
        self.assertEqual(clamped["fps"], 4.0)
        self.assertEqual(clamped["max_frames"], 128)
        self.assertEqual(clamped["total_pixels"], 262144)
        self.assertEqual(clamped["max_tokens"], 8192)
        self.assertNotIn("model_dir", clamped)

        with self.assertRaises(ValueError):
            contracts.normalize({"video_url": "/video/clip.mp4", "mode": "custom", "prompt": "   "})
        with self.assertRaises(ValueError):
            contracts.normalize({"video_url": "/video/clip.mp4", "mode": "unknown"})
        with self.assertRaises(ValueError):
            contracts.normalize({"mode": "summary"})

    def test_prompts_all_modes_and_shot_anchors(self):
        sb = prompts.build_prompt(
            "storyboard",
            duration=10.0,
            shots=[(0.0, 4.5), (4.5, 10.0)],
            custom_prompt="关注打光",
            use_audio=True,
        )
        self.assertIn("Shot 01: 00:00.0 - 00:04.5", sb)
        self.assertIn("关注打光", sb)
        self.assertIn("原始台词", sb)

        pr = prompts.build_prompt("prompt_reverse", duration=6.0, use_audio=False)
        self.assertIn("当前仅分析视觉画面", pr)

        self.assertEqual(prompts.format_h3_timestamp(0.0), "00:00.000")
        self.assertEqual(prompts.format_h3_timestamp(3.5), "00:03.500")
        self.assertEqual(prompts.format_h3_timestamp(59.9999), "01:00.000")

        h3_multi = prompts.build_prompt(
            "h3_prompt",
            duration=8.0,
            shots=[(0.0, 3.5), (3.5, 8.0)],
            custom_prompt="Use I2VA mode",
            use_audio=True,
        )
        for token in (
            "integrated_multimodal_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
            "[Shot 2] At 00:03.500",
            "(S1)",
            "<d>[Language]",
            "<scenetrans>",
            "<cutoff>",
            "Push In",
            "Use I2VA mode",
        ):
            self.assertIn(token, h3_multi)

        h3_single = prompts.build_prompt("h3_prompt", duration=8.0, shots=[(0.0, 8.0)], use_audio=True)
        self.assertIn("Single continuous shot detected", h3_single)

        h3_silent = prompts.build_prompt("h3_prompt", duration=6.0, use_audio=False)
        self.assertIn("Audio Track Disabled Mode", h3_silent)
        self.assertIn("non_diegetic_music**:\n- Output `N/A`", h3_silent)

        sm = prompts.build_prompt("summary", duration=8.0, use_audio=True)
        self.assertIn("原始对白", sm)

        cu = prompts.build_prompt("custom", duration=5.0, custom_prompt="数一数有几辆车")
        self.assertIn("数一数有几辆车", cu)

    def test_environment_prepare_status_and_local_model_dir_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "comp"
            local_model = Path(tmp) / "local-4bit"
            local_model.mkdir(parents=True)
            (local_model / "config.json").write_text(
                json.dumps({"model_type": "wemm_qwen3_5_moe", "quantization": {"bits": 4}}),
                encoding="utf-8",
            )
            (local_model / "tokenizer.json").write_text("{}", encoding="utf-8")
            (local_model / "processor_config.json").write_text("{}", encoding="utf-8")
            (local_model / "model.safetensors.index.json").write_text(
                json.dumps({"weight_map": {"a": "model-00001-of-00001.safetensors"}}),
                encoding="utf-8",
            )
            (local_model / "model-00001-of-00001.safetensors").write_bytes(b"weights")

            calls = []

            def fake_run(cmd, check=True):
                calls.append(cmd)
                if "venv" in cmd:
                    py = Path(cmd[-1]) / "bin" / "python"
                    py.parent.mkdir(parents=True, exist_ok=True)
                    py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    py.chmod(0o755)

            def fake_fetch(url, path, *, size, sha256_value="", blob_id="", progress=None, proxies=None):
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as stream:
                    stream.truncate(int(size))
                if progress:
                    progress(size, size)
                return path

            with unittest.mock.patch.object(environment, "supported_platform", return_value=True), \
                 unittest.mock.patch.object(environment, "probe_packages", return_value=[]), \
                 contextlib.redirect_stdout(io.StringIO()):
                # Bind local 4-bit directory
                res = environment.prepare(
                    root=root,
                    model_dir=local_model,
                    uv="/usr/bin/true",
                    run=fake_run,
                    fetch=fake_fetch,
                    tool_locator=lambda name: f"/usr/bin/{name}",
                )
                self.assertTrue(res["ready"])
                self.assertIn("4-bit", res["model_variant"])
                self.assertNotIn(str(local_model), json.dumps(res))

                # Full 6-bit asset prepare
                root_6 = Path(tmp) / "comp6"
                res6 = environment.prepare(
                    root=root_6,
                    uv="/usr/bin/true",
                    run=fake_run,
                    fetch=fake_fetch,
                    tool_locator=lambda name: f"/usr/bin/{name}",
                )
                self.assertTrue(res6["ready"])
                self.assertEqual(res6["reasons"], [])
                self.assertGreater(res6["download_bytes"], 31 * 1000 ** 3)

                # Skip-model prepare creates default model dir and verifies env + source without weights
                root_env = Path(tmp) / "comp_env_only"
                res_env = environment.prepare(
                    root=root_env,
                    skip_model=True,
                    uv="/usr/bin/true",
                    run=fake_run,
                    fetch=fake_fetch,
                    tool_locator=lambda name: f"/usr/bin/{name}",
                )
                self.assertTrue(environment.default_model_dir(root_env).is_dir())
                self.assertEqual(environment.missing_source(root_env), [])
                self.assertFalse(res_env["ready"])
                self.assertEqual(len(res_env["reasons"]), 1)
                self.assertIn("模型文件缺失", res_env["reasons"][0])

                with self.assertRaises(ValueError):
                    environment.prepare(
                        root=root_env,
                        model_dir=local_model,
                        skip_model=True,
                        uv="/usr/bin/true",
                        run=fake_run,
                        fetch=fake_fetch,
                        tool_locator=lambda name: f"/usr/bin/{name}",
                    )

            # Invalid model dir rejected
            bad_model = Path(tmp) / "bad"
            bad_model.mkdir()
            with self.assertRaises(ValueError):
                environment.validate_local_model_dir(bad_model)

    def test_storage_recover_and_artifact_security(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "data")
            job = store.create({"video_url": "/video/a.mp4"})
            store.update(job["id"], status="running")
            store.recover()
            recovered = store.get(job["id"])
            self.assertEqual(recovered["status"], "interrupted")

            res_dir = store.path(job["id"]) / "result"
            res_dir.mkdir(parents=True)
            (res_dir / "output.md").write_text("hello\n", encoding="utf-8")
            (res_dir / "secret.txt").write_text("nope", encoding="utf-8")
            store.update(job["id"], artifacts=[{"name": "result/output.md", "file_size": 6, "url": "/x"}])
            self.assertEqual(store.artifact(job["id"], "result/output.md").read_text(), "hello\n")
            with self.assertRaises(FileNotFoundError):
                store.artifact(job["id"], "result/secret.txt")
            with self.assertRaises(FileNotFoundError):
                store.artifact(job["id"], "../../etc/passwd")

    def test_runtime_fake_worker_progress_cancel_and_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            comp = Path(tmp) / "comp"
            local_model = Path(tmp) / "model"
            local_model.mkdir(parents=True)
            (local_model / "config.json").write_text(json.dumps({"model_type": "wemm_qwen3_5_moe"}), encoding="utf-8")
            (local_model / "tokenizer.json").write_text("{}", encoding="utf-8")
            (local_model / "processor_config.json").write_text("{}", encoding="utf-8")
            (local_model / "model.safetensors").write_bytes(b"w")
            _create_fake_component(comp, model_dir=local_model)

            fake_worker = Path(tmp) / "fake_worker.py"
            fake_worker.write_text(
                "import json, sys, time\n"
                "from pathlib import Path\n"
                "req = json.loads(Path(sys.argv[1]).read_text())\n"
                "res = Path(sys.argv[2])\n"
                "print('WEMM_EVENT ' + json.dumps({'event': 'progress', 'stage': 'load', 'ratio': 0.2, 'message': 'loading'}), flush=True)\n"
                "if req.get('prompt') == 'sleep':\n"
                "    time.sleep(30)\n"
                "(res / 'output.md').write_text('# OK\\n', encoding='utf-8')\n"
                "(res / 'shots.json').write_text('[]', encoding='utf-8')\n"
                "(res / 'result.json').write_text(json.dumps({'text': '# OK', 'finish_reason': 'stop', 'mode': req['mode'], 'stats': {'generated_tokens': 4}}), encoding='utf-8')\n"
                "print('WEMM_EVENT ' + json.dumps({'event': 'done', 'stage': 'done', 'ratio': 1.0}), flush=True)\n",
                encoding="utf-8",
            )

            released = []
            rt = Runtime(comp, before_load=lambda: released.append("released"), worker=fake_worker)
            events = []
            job_dir = Path(tmp) / "job1"
            video = Path(tmp) / "clip.mp4"
            video.write_bytes(b"mp4")
            status, error = rt.execute(
                {"mode": "summary", "prompt": "go"},
                job_dir,
                video,
                threading.Event(),
                lambda ev: events.append(ev),
            )
            self.assertEqual(status, "succeeded", error)
            self.assertEqual(released, ["released"])
            self.assertTrue(any(e.get("stage") == "load" for e in events))

            # Cancel test
            cancel_ev = threading.Event()
            threading.Timer(0.25, cancel_ev.set).start()
            c_status, _ = rt.execute(
                {"mode": "custom", "prompt": "sleep"},
                Path(tmp) / "job2",
                video,
                cancel_ev,
                lambda _ev: None,
            )
            self.assertEqual(c_status, "cancelled")

    def test_service_caching_queue_and_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            comp = Path(tmp) / "comp"
            data = Path(tmp) / "data"
            archive = Path(tmp) / "archive"
            archive.mkdir()
            video = archive / "clip.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42")

            local_model = Path(tmp) / "model"
            local_model.mkdir()
            (local_model / "config.json").write_text(json.dumps({"model_type": "wemm_qwen3_5_moe"}), encoding="utf-8")
            (local_model / "tokenizer.json").write_text("{}", encoding="utf-8")
            (local_model / "processor_config.json").write_text("{}", encoding="utf-8")
            (local_model / "model.safetensors").write_bytes(b"w")
            _create_fake_component(comp, model_dir=local_model)

            fake_worker = Path(tmp) / "fake_worker.py"
            counter_file = Path(tmp) / "runs.txt"
            fake_worker.write_text(
                f"import json, sys\nfrom pathlib import Path\n"
                f"with Path({str(counter_file)!r}).open('a') as f: f.write('1\\n')\n"
                f"res = Path(sys.argv[2])\n"
                f"(res / 'output.md').write_text('分析正文', encoding='utf-8')\n"
                f"(res / 'shots.json').write_text('[]', encoding='utf-8')\n"
                f"(res / 'result.json').write_text(json.dumps({{'text': '分析正文', 'finish_reason': 'stop', 'mode': 'summary', 'stats': {{'generated_tokens': 2}}}}), encoding='utf-8')\n",
                encoding="utf-8",
            )

            resolver = SourceResolver(archive_video=lambda rel: archive / rel if rel == "clip.mp4" else None)
            rt = Runtime(comp, worker=fake_worker)
            svc = VideoUnderstandService(
                comp,
                data,
                resolver=resolver,
                runtime=rt,
                status_reader=lambda _root: {
                    "ready": True,
                    "reasons": [],
                    "prepared_at": 1700000000,
                    "download_bytes": 100,
                    "model_variant": contracts.MODEL_LABEL,
                },
            )
            router = create_router(svc)
            try:
                # Status route
                h = _FakeHandler("GET", "/api/video_understand/status")
                self.assertTrue(router.dispatch(h, "GET", "/api/video_understand/status"))
                self.assertEqual(h.sent[0][0], 200)
                self.assertTrue(h.sent[0][1]["ready"])

                # Unsupported video URL -> 400
                bad = _FakeHandler(
                    "POST",
                    "/api/video_understand/submit",
                    json.dumps({"video_url": "https://evil.invalid/a.mp4", "mode": "summary"}).encode("utf-8"),
                )
                router.dispatch(bad, "POST", "/api/video_understand/submit")
                self.assertEqual(bad.sent[0][0], 400)

                # Submit valid job
                sub = _FakeHandler(
                    "POST",
                    "/api/video_understand/submit",
                    json.dumps({"video_url": "/video/clip.mp4", "mode": "summary"}).encode("utf-8"),
                )
                router.dispatch(sub, "POST", "/api/video_understand/submit")
                self.assertEqual(sub.sent[0][0], 200)
                job_id = sub.sent[0][1]["id"]

                # Wait for completion
                deadline = time.monotonic() + 10
                job = None
                while time.monotonic() < deadline:
                    jh = _FakeHandler("GET", f"/api/video_understand/job?id={job_id}")
                    router.dispatch(jh, "GET", "/api/video_understand/job")
                    job = jh.sent[0][1]
                    if job["status"] == "succeeded":
                        break
                    time.sleep(0.05)
                self.assertEqual(job["status"], "succeeded")
                self.assertEqual(job["result"]["text"], "分析正文")

                # Cache hit should return same succeeded job without invoking worker again
                sub2 = _FakeHandler(
                    "POST",
                    "/api/video_understand/submit",
                    json.dumps({"video_url": "/video/clip.mp4", "mode": "summary"}).encode("utf-8"),
                )
                router.dispatch(sub2, "POST", "/api/video_understand/submit")
                self.assertEqual(sub2.sent[0][1]["id"], job_id)
                self.assertEqual(len(counter_file.read_text().splitlines()), 1)

                # Missing job -> 404
                miss = _FakeHandler("GET", f"/api/video_understand/job?id={'0' * 32}")
                router.dispatch(miss, "GET", "/api/video_understand/job")
                self.assertEqual(miss.sent[0][0], 404)
            finally:
                svc.close()


if __name__ == "__main__":
    unittest.main()
