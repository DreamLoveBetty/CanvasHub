"""Portable offline regression tests for the kandinsky_sr domain, routes, and asset_index."""
from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

from PIL import Image

from backend import asset_index
from backend.kandinsky_sr import contracts, environment
from backend.kandinsky_sr.runtime import KandinskySrCancelled, KandinskySrError, Result, Runtime
from backend.kandinsky_sr.service import Service
from backend.routes.kandinsky_sr_routes import create_router
from backend.services.image_enhancement import _coerce_upscale_tile, _write_upscale_sidecar, process_image_enhancement_task


def _create_fake_component(root: Path, *, with_python: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    src_base = environment.src_dir(root)
    assets = environment.load_assets()
    for rel, item in assets["source"]["files"].items():
        target = src_base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"s" * int(item["size"]))

    model_dir = environment.default_model_dir(root)
    model_dir.mkdir(parents=True, exist_ok=True)
    for rel, item in assets["model"]["files"].items():
        target = model_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:
            stream.truncate(int(item["size"]))

    if with_python:
        py_link = environment.venv_python(root)
        py_link.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sys.executable, py_link)
        py_link.chmod(0o755)

    receipt = {
        "schema_version": 1,
        "python": str(environment.venv_python(root)),
        "prepared_at": 1700000000,
        "versions": environment.pinned_packages(),
        "model_variant": contracts.MODEL_LABEL,
    }
    (root / "installed.json").write_text(json.dumps(receipt), encoding="utf-8")
    return model_dir


class _FakeHandler:
    def __init__(self, method: str, path: str, body: bytes = b""):
        self.command = method
        self.path = path
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.rfile = io.BytesIO(body)
        self.sent = []
        self.started = []

    def require_auth(self) -> bool:
        return True

    def read_json_body(self, max_bytes=64 * 1024 * 1024):
        if len(self.rfile.getvalue()) > max_bytes:
            raise ValueError("请求体过大")
        return json.loads(self.rfile.getvalue() or b"{}")

    def send_json(self, payload, status=200):
        self.sent.append((status, payload))

    def start_generation_task(self, task_id, fn, args):
        self.started.append((task_id, fn, args))
        return True


class KandinskySrDomainTests(unittest.TestCase):
    def test_contracts_validation_and_tiling(self):
        self.assertEqual(contracts.normalize_options(None), {"upscale_factor": 2, "creativity": 4, "overlap": 0.25})
        opts = contracts.normalize_options({"upscale_factor": "4", "creativity": 7, "overlap": 0.375})
        self.assertEqual(opts, {"upscale_factor": 4, "creativity": 7, "overlap": 0.375})

        for bad in (
            {"upscale_factor": 3},
            {"upscale_factor": True},
            {"creativity": -1},
            {"creativity": 9},
            {"creativity": 1.5},
            {"overlap": 0.3},
        ):
            with self.assertRaises(ValueError):
                contracts.normalize_options(bad)

        self.assertEqual(contracts.creativity_to_timestep(2, 4), 0.15)
        self.assertEqual(contracts.creativity_to_timestep(4, 4), 0.244)
        self.assertEqual(contracts.estimate_tile_count(1024, 1024, 2, 0.25), 9)
        self.assertEqual(contracts.estimate_tile_count(1024, 1024, 4, 0.25), 25)
        self.assertEqual(contracts.estimate_tile_count(512, 512, 2, 0.25), 1)

    def test_environment_status_and_local_model_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ksr"
            unready = environment.status(root)
            self.assertFalse(unready["ready"])
            self.assertGreater(unready["download_bytes"], 9 * 1024**3)

            _create_fake_component(root)
            ready = environment.status(root, probe=lambda _py, _exp: [])
            self.assertTrue(ready["ready"])
            self.assertEqual(ready["reasons"], [])

            local_model = Path(tmp) / "custom-model"
            (local_model / "transformer").mkdir(parents=True)
            (local_model / "vae").mkdir(parents=True)
            (local_model / "model_index.json").write_text(
                json.dumps({"_class_name": "KandinskyImageSRPipeline"}), encoding="utf-8"
            )
            (local_model / "transformer" / "config.json").write_text(
                json.dumps({"_class_name": "KandinskyImageSRBakedTransformer3DModel"}), encoding="utf-8"
            )
            (local_model / "transformer" / "diffusion_pytorch_model.safetensors.index.json").write_text(
                json.dumps({"weight_map": {"w": "shard-1.safetensors"}}), encoding="utf-8"
            )
            (local_model / "transformer" / "shard-1.safetensors").write_bytes(b"weights")
            (local_model / "vae" / "config.json").write_text("{}", encoding="utf-8")
            (local_model / "vae" / "diffusion_pytorch_model.safetensors").write_bytes(b"vae")

            self.assertEqual(environment.validate_local_model_dir(local_model), local_model.resolve())

            (local_model / "transformer" / "shard-1.safetensors").unlink()
            with self.assertRaises(ValueError):
                environment.validate_local_model_dir(local_model)

    def test_runtime_worker_progress_error_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "components" / "kandinsky-sr"
            _create_fake_component(root, with_python=False)
            py_path = environment.venv_python(root)
            py_path.parent.mkdir(parents=True, exist_ok=True)
            py_path.symlink_to(sys.executable)

            fake_worker = base / "fake_worker.py"
            fake_worker.write_text(
                "\n".join([
                    "import json, sys",
                    "from pathlib import Path",
                    "from PIL import Image",
                    "spec = json.loads(Path(sys.argv[1]).read_text())",
                    "print('KSR_EVENT ' + json.dumps({'event': 'progress', 'percent': 50, 'stage': '超分分块 1/2'}), flush=True)",
                    "if spec['creativity'] == 8:",
                    "    print('KSR_EVENT ' + json.dumps({'event': 'error', 'message': '模拟推理错误'}), flush=True)",
                    "    sys.exit(1)",
                    "img = Image.new('RGB', (128, 128), (12, 34, 56))",
                    "Path(spec['output_path']).parent.mkdir(parents=True, exist_ok=True)",
                    "img.save(spec['output_path'])",
                    "print('KSR_EVENT ' + json.dumps({'event': 'result', 'input_width': 64, 'input_height': 64, 'output_width': 128, 'output_height': 128, 'scale': 2, 'model': spec['model'], 'device': 'mps'}), flush=True)",
                ]),
                encoding="utf-8",
            )

            before_calls = []
            progress_events = []
            runtime = Runtime(
                root,
                before_load=lambda: before_calls.append(True),
                worker=fake_worker,
                status_reader=lambda _root: {"ready": True, "reasons": []},
            )

            src = base / "in.png"
            out = base / "out.png"
            Image.new("RGB", (64, 64), (1, 2, 3)).save(src)

            res = runtime.execute(
                src,
                out,
                options={"upscale_factor": 2, "creativity": 4, "overlap": 0.25},
                progress=lambda ratio, text: progress_events.append((ratio, text)),
            )
            self.assertEqual(len(before_calls), 1)
            self.assertEqual((res.output_width, res.output_height, res.scale, res.device), (128, 128, 2, "mps"))
            self.assertTrue(out.is_file())
            self.assertTrue(any("1/2" in text for _, text in progress_events))

            with self.assertRaisesRegex(KandinskySrError, "模拟推理错误"):
                runtime.execute(src, base / "err.png", options={"upscale_factor": 2, "creativity": 8, "overlap": 0.25})

            with self.assertRaises(KandinskySrCancelled):
                runtime.execute(src, base / "cancel.png", cancelled=lambda: True)

    def test_routes_and_enhancement_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "components" / "kandinsky-sr"
            archive_root = base / "archive"
            ready_state = {"ready": False, "reasons": ["Kandinsky SR 环境尚未准备"]}

            class FakeRuntime:
                def execute(self, source, output, *, options, cancelled, progress):
                    progress(0.5, "超分分块 1/1")
                    Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(output)
                    return Result(16, 16, 32, 32, int(options["upscale_factor"]), "kandinsky-imagesr-2.0", "mps")

            svc = Service(
                root,
                runtime=FakeRuntime(),
                status_reader=lambda _root: dict(ready_state),
            )
            created = []
            router = create_router(
                svc,
                create_task=lambda *args, **kwargs: created.append((args, kwargs)),
                process_task=lambda *args: None,
                attach_lineage=lambda params, data: params.update({"lineage": data.get("lineage")} if data.get("lineage") else {}),
            )

            h_status = _FakeHandler("GET", "/api/kandinsky_sr/status")
            self.assertTrue(router.dispatch(h_status, "GET", "/api/kandinsky_sr/status"))
            self.assertEqual(h_status.sent[0][0], 200)
            self.assertFalse(h_status.sent[0][1]["ready"])

            buf = io.BytesIO()
            Image.new("RGB", (16, 16), (255, 0, 0)).save(buf, format="PNG")
            import base64
            data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

            h_unready = _FakeHandler(
                "POST",
                "/api/kandinsky_sr/run",
                json.dumps({"images": [data_uri], "options": {"upscale_factor": 2, "creativity": 4, "overlap": 0.25}}).encode(),
            )
            router.dispatch(h_unready, "POST", "/api/kandinsky_sr/run")
            self.assertEqual(h_unready.sent[0][0], 409)

            ready_state["ready"] = True
            svc._status_cache = (0.0, None, None)

            h_bad = _FakeHandler("POST", "/api/kandinsky_sr/run", json.dumps({"images": []}).encode())
            router.dispatch(h_bad, "POST", "/api/kandinsky_sr/run")
            self.assertEqual(h_bad.sent[0][0], 400)

            h_ok = _FakeHandler(
                "POST",
                "/api/kandinsky_sr/run",
                json.dumps({
                    "prompt": "测试超分",
                    "images": [data_uri],
                    "options": {"upscale_factor": 2, "creativity": 5, "overlap": 0.125},
                    "telegram_enabled": True,
                }).encode(),
            )
            router.dispatch(h_ok, "POST", "/api/kandinsky_sr/run")
            self.assertEqual(h_ok.sent[0][0], 202)
            task_id = h_ok.sent[0][1]["task_id"]
            self.assertTrue(task_id.startswith("kandinsky_sr_"))

            # Verify full EnhancementEngine archive + sidecar + Telegram sendDocument lifecycle
            _, _, task_args = h_ok.started[0]
            _, task_prompt, task_img, task_params = task_args
            sent_docs = []
            finalized = []

            def write_sidecar(img_path, content, txt_path=None):
                Path(txt_path).write_text(content, encoding="utf-8")

            process_image_enhancement_task(
                task_id,
                task_prompt,
                task_img,
                task_params,
                Path=Path,
                UPSCALE_MODELS={},
                UPSCALE_MODEL_DIR=base,
                UpscaleRuntimeError=RuntimeError,
                _coerce_bool=lambda v, d=False: bool(v) if v is not None else d,
                _coerce_upscale_tile=_coerce_upscale_tile,
                _decode_data_uri_image=lambda _uri: (buf.getvalue(), "image/png", ".png"),
                _finalize_generation_task=lambda tid, status, **kw: finalized.append((tid, status, kw)),
                _merge_task_params=lambda *_args, **_kw: None,
                _record_generation_event=lambda *_args, **_kw: None,
                _start_generation_audit=lambda *_args, **_kw: "run_1",
                _translate_generation_failure=lambda *_args, **_kw: {"display_error": "err"},
                _upscale_progress_callback=lambda _tid: (lambda _r, _t: None),
                _write_upscale_sidecar=lambda out_p, pr, pa, meta: _write_upscale_sidecar(
                    out_p, pr, pa, meta, Path=Path, write_obsidian_prompt_sidecar=write_sidecar
                ),
                daily_output_dir=lambda now: archive_root / now.strftime("%Y-%m-%d"),
                datetime=datetime,
                normalize_upscale_model=lambda v: v,
                os=__import__("os"),
                random=__import__("random"),
                re=__import__("re"),
                save_thumbnail=lambda *_args: None,
                send_status_notification=lambda *_args: None,
                send_tg_document=lambda path, caption="": sent_docs.append((Path(path), caption)),
                tempfile=__import__("tempfile"),
                update_task_status=lambda *_args, **_kw: None,
                upscale_image_file=lambda *_args, **_kw: None,
                engine=svc.engine(task_params),
            )
            self.assertEqual(finalized[0][1], "succeeded")
            self.assertEqual(len(sent_docs), 1)
            out_file = sent_docs[0][0]
            self.assertTrue(out_file.is_file())
            self.assertTrue(out_file.name.startswith("kandinsky_sr_"))
            sidecar_text = out_file.with_suffix(".txt").read_text(encoding="utf-8")
            self.assertIn("kandinsky_sr_parameters:", sidecar_text)
            self.assertIn('"creativity": 5', sidecar_text)

    def test_asset_index_provider_mapping(self):
        self.assertEqual(asset_index._provider_group({"type": "kandinsky_sr"}), "kandinsky_sr")
        self.assertEqual(asset_index._provider_label("kandinsky_sr"), "Kandinsky SR 2.0")
        self.assertEqual(asset_index._infer_archive_provider(Path("kandinsky_sr_x_1234.png")), "kandinsky_sr")


if __name__ == "__main__":
    unittest.main()
