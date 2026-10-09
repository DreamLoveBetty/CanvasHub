"""Portable, synthetic contract tests; never load proprietary model weights."""
from __future__ import annotations

import json
from pathlib import Path
import platform
import tempfile
import threading
import time
import unittest
from unittest import mock

from backend.topaz_video.catalog import BY_ID
from backend.topaz_video.contracts import normalize
from backend.topaz_video.license import resolve_license_dir
from backend.topaz_video.provision_local import (
    CONVENTIONAL_AUXILIARY_FILES, MANIFEST, MODEL_FILES, VALIDATION,
    inspect_conventional, inspect_precise, install_conventional, install_precise,
    local_validation, sync_conventional, sync_neuro_models,
)
from backend.topaz_video.runtime import (
    TopazVideoRuntime, VideoRuntimeError, build_audio_mux_command, build_conventional_command,
    build_precise_command, missing_coreml_asset,
)
from backend.topaz_video.service import TopazVideoService
from backend.topaz_video.storage import Store


def _data(model="proteus-v4", **kwargs):
    return {"asset_id": "a" * 32, "model": model, "scale": BY_ID[model].scales[0], **kwargs}


class ContractsTest(unittest.TestCase):
    def test_full_video_is_default_and_model_options_are_separate(self):
        spec = normalize(_data())
        self.assertEqual(spec["max_seconds"], 0)
        self.assertEqual(spec["start_seconds"], 0)
        self.assertEqual(spec["task_kind"], "export")
        self.assertEqual(spec["preblur"], 0)
        self.assertEqual(spec["prenoise"], 0)
        self.assertEqual(spec["gsize"], 0)
        self.assertEqual(normalize(_data(max_seconds=600))["max_seconds"], 600)
        with self.assertRaisesRegex(ValueError, "未知"):
            normalize({"asset_id": "a" * 32, "model": "bogus"})
        with self.assertRaisesRegex(ValueError, "不可用"):
            normalize({"asset_id": "a" * 32, "model": "mini", "scale": 2})
        with self.assertRaisesRegex(ValueError, "超出范围"):
            normalize(_data(noise=-0.1))
        with self.assertRaisesRegex(ValueError, "0–5 整数"):
            normalize(_data(gsize=0.1))
        self.assertEqual(normalize(_data(gsize=0))["gsize"], 0)
        self.assertEqual(normalize(_data(gsize=2))["gsize"], 2)
        with self.assertRaisesRegex(ValueError, "不支持"):
            normalize(_data(api_key="secret"))

    def test_preview_range_is_explicit_and_bounded(self):
        spec = normalize(_data(task_kind="preview", start_seconds=12.5, max_seconds=4.25))
        self.assertEqual(spec["task_kind"], "preview")
        self.assertEqual(spec["start_seconds"], 12.5)
        self.assertEqual(spec["max_seconds"], 4.25)
        with self.assertRaisesRegex(ValueError, "必须提供"):
            normalize(_data(task_kind="preview", start_seconds=1, max_seconds=0))
        with self.assertRaisesRegex(ValueError, "start_seconds"):
            normalize(_data(start_seconds=-1))

    def test_offline_commands_never_reference_app_or_download(self):
        spec = normalize(_data(max_seconds=0, preblur=-0.25))
        command = build_conventional_command(Path("/stage/ffmpeg"), spec,
            Path("/asset"), Path("/out.mp4"), 512, 512, 8)
        line = " ".join(command)
        self.assertIn("model=prob-4", line)
        self.assertIn("download=0", line)
        self.assertIn("preblur=-0.25", line)
        self.assertNotIn(" -t ", line)
        self.assertNotIn("/Applications", line)
        ranged = normalize(_data(task_kind="preview", start_seconds=2.5, max_seconds=1.5))
        ranged_line = " ".join(build_conventional_command(Path("/stage/ffmpeg"), ranged,
            Path("/asset"), Path("/out.mp4"), 512, 512, 8))
        self.assertIn(" -ss 0.50000000 -i /asset -ss 2.00000000 ", ranged_line)
        self.assertIn(" -t 1.50000000 ", ranged_line)
        short_range = normalize(_data(task_kind="preview", start_seconds=0.25, max_seconds=0.5))
        short_command = build_conventional_command(Path("/stage/ffmpeg"), short_range,
            Path("/asset"), Path("/out.mp4"), 512, 512, 2)
        self.assertEqual(short_command[short_command.index("-i") + 2:short_command.index("-frames:v")],
                         ["-ss", "0.25000000", "-t", "0.50000000"])
        precise = build_precise_command(Path("/stage/neuroserver"),
            normalize(_data("precise-26")), Path("/asset"), Path("/out"), 1024, 1024, 8, 15)
        self.assertIn('"model":"slp-26"', " ".join(precise))
        self.assertIn("--start-frame-idx 15 --end-frame-idx 22", " ".join(precise))
        self.assertNotIn("slp-25", " ".join(precise))

    def test_unstaged_status_does_not_claim_available(self):
        with tempfile.TemporaryDirectory() as directory:
            models = {item["id"]: item for item in TopazVideoRuntime(directory).status()["models"]}
            self.assertFalse(models["mini"]["available"])
            self.assertFalse(models["precise-25"]["available"])
            self.assertFalse(models["precise-26"]["available"])
            self.assertFalse(models["proteus-v4"]["available"])
            self.assertEqual(models["proteus-v4"]["scales"], [1, 4])

    def test_downloaded_conventional_catalog_has_conservative_scales(self):
        self.assertEqual(BY_ID["theia-v4"].scales, (1, 2))
        self.assertEqual(BY_ID["iris"].scales, (1,))
        self.assertEqual(BY_ID["rhea"].scales, (1, 2, 4))
        self.assertEqual(BY_ID["artemis"].scales, (2,))
        self.assertEqual(BY_ID["gaia"].scales, (2,))
        self.assertEqual(BY_ID["gaia-animation"].scales, (2,))

    def test_iris_catalog_matches_the_downloaded_v2_weight(self):
        self.assertEqual(BY_ID["iris"].backend_name, "iris-2")
        self.assertIn("iris-2.json", MODEL_FILES["iris"])
        self.assertNotIn("iris-3.json", MODEL_FILES["iris"])
        spec = normalize(_data("iris", preblur=0.75))
        command = build_conventional_command(Path("/stage/ffmpeg"), spec,
            Path("/asset"), Path("/out.mp4"), 256, 256, 4)
        self.assertIn("model=iris-2", " ".join(command))

    def test_audio_mux_pads_short_audio_before_shortest_cut(self):
        command = build_audio_mux_command(
            Path("/stage/ffmpeg"), Path("/rendered.mp4"), Path("/source.mp4"),
            Path("/output.mp4"), start_seconds=1.25, duration_seconds=15.08333333,
        )
        self.assertEqual(command[command.index("-af") + 1], "apad")
        self.assertLess(command.index("-af"), command.index("-shortest"))
        self.assertEqual(command[command.index("-ss") + 1], "1.25000000")
        self.assertEqual(command[command.index("-t") + 1], "15.08333333")

    def test_missing_coreml_asset_is_reported_as_model_resource_error(self):
        line = ("MLModel Error: 0 The model is not found at URL: file:///runtime/models/"
                "coreMLCache//ganim-v1-fp16-384x672-2x-OS15-mlp path: /runtime/model")
        self.assertEqual(missing_coreml_asset(line),
                         "ganim-v1-fp16-384x672-2x-OS15-mlp")
        self.assertEqual(missing_coreml_asset("Conversion failed!"), "")

    def test_conventional_preview_rejects_fewer_than_four_frames(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("backend.topaz_video.runtime._probe", return_value={
                    "width": 640, "height": 360, "fps": 24.0, "frames": 3,
                    "duration": 0.125, "has_audio": False,
                }):
            runtime = TopazVideoRuntime(directory)
            with self.assertRaisesRegex(VideoRuntimeError, "至少需要 4 帧"):
                runtime._execute(normalize(_data(max_seconds=0)), Path(directory) / "job",
                                 Path(directory) / "input.mp4", threading.Event(), lambda _value: None)


class ProvisionTest(unittest.TestCase):
    @staticmethod
    def _file(path: Path, data=b"mock"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_conventional_import_has_no_external_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in ("ffmpeg", "ffprobe"):
                path = source / "MacOS" / name
                self._file(path)
                path.chmod(0o755)
            self._file(source / "Frameworks" / "lib.mock")
            for name in {*CONVENTIONAL_AUXILIARY_FILES,
                         *(name for values in MODEL_FILES.values() for name in values)}:
                self._file(source / "Resources/models" / name)
            stage = root / "stage"
            result = install_conventional(source, stage)
            self.assertTrue(result["ready"])
            self.assertTrue(all(result["models"].values()))
            self.assertTrue(inspect_conventional(stage)["ready"])
            with self.assertRaises(FileExistsError):
                install_conventional(source, stage)

    def test_conventional_sync_refreshes_allow_list_and_never_copies_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in ("ffmpeg", "ffprobe"):
                path = source / "MacOS" / name
                self._file(path)
                path.chmod(0o755)
            self._file(source / "Frameworks" / "lib.mock")
            files = {*CONVENTIONAL_AUXILIARY_FILES,
                     *(name for values in MODEL_FILES.values() for name in values)}
            for name in files:
                self._file(source / "Resources/models" / name, ("source:" + name).encode())
            self._file(source / "Resources/models/license.lic", b"must-not-be-copied")
            cache_name = "ahq-v12-fnet-fp16-448x576-2x-ml"
            self._file(source / "Resources/models/coreMLCache" / cache_name / "compiled.bin")
            stage = root / "stage"
            install_conventional(source, stage)
            # A later App-side download may add another CoreML tile/aspect
            # variant for an already exposed model.  Sync must carry the
            # allow-listed family variant and its warm cache, without copying
            # arbitrary model-store files.
            extra_name = "ganim-v1-fp16-384x672-2x-OS15-mlp.tz3"
            extra_cache = extra_name.removesuffix(".tz3")
            self._file(source / "Resources/models" / extra_name, b"landscape-variant")
            self._file(source / "Resources/models/coreMLCache" / extra_cache / "compiled.bin")
            self._file(source / "Resources/models/unrelated-v1-fp16-384x672-2x.tz3", b"not-allowed")
            target_name = "ahq-v12-fnet-fp16-448x576-2x-ml.tz3"
            (stage / "Resources/models" / target_name).write_bytes(b"stale")
            (stage / VALIDATION).write_text("{}", encoding="utf-8")
            result = sync_conventional(source, stage)
            self.assertTrue(result["ready"])
            self.assertTrue(all(result["models"].values()))
            self.assertIn(target_name, result["changed"])
            self.assertEqual((stage / "Resources/models" / target_name).read_bytes(),
                             (source / "Resources/models" / target_name).read_bytes())
            self.assertTrue((stage / "Resources/models/coreMLCache" / cache_name / "compiled.bin").is_file())
            self.assertIn(extra_name, result["changed"])
            self.assertIn("coreMLCache/" + extra_cache, result["changed"])
            self.assertTrue((stage / "Resources/models" / extra_name).is_file())
            self.assertTrue((stage / "Resources/models/coreMLCache" / extra_cache / "compiled.bin").is_file())
            self.assertFalse((stage / "Resources/models/unrelated-v1-fp16-384x672-2x.tz3").exists())
            self.assertFalse((stage / "Resources/models/license.lic").exists())
            self.assertFalse((stage / VALIDATION).exists())
            (stage / "Resources/models" / extra_name).unlink()
            self.assertFalse(inspect_conventional(stage)["models"]["gaia-animation"])

    def test_precise_import_stays_unverified_for_unknown_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in ("neuroserver/neuroserver", "ffmpeg/MacOS/ffmpeg"):
                path = source / name
                self._file(path)
                path.chmod(0o755)
            probe = root / "ffprobe"
            self._file(probe)
            probe.chmod(0o755)
            self._file(source / "ffmpeg/Frameworks/lib.mock")
            self._file(source / "resources/deps/lib/mock.so")
            self._file(source / "resources/deps/lib-dynload/mock.so")
            (source / "neuroserver/lib").symlink_to("../resources/deps/lib", target_is_directory=True)
            (source / "neuroserver/lib-dynload").symlink_to("../resources/deps/lib-dynload", target_is_directory=True)
            for number in range(45):
                self._file(source / "models/slp26" / f"blob.{number:03d}")
            stage = root / "precise"
            result = install_precise(source, stage, ffprobe_source=probe)
            self.assertTrue(result["ready"])
            self.assertFalse(result["verified"])
            self.assertTrue(inspect_precise(stage)["ready"])

            app = root / "app"
            self._file(app / "Resources/models/hyp-2.json", b"{}")
            for number in range(43):
                self._file(app / "Resources/models/models/hyp-2" / f"blob.{number:03d}")
            synced = sync_neuro_models(app, stage)
            self.assertEqual(synced["neuro_models"], ["hyp-2"])
            self.assertTrue((stage / "models/hyp-2/blob.000").is_file())
            self.assertTrue((stage / "models/hyp-2.json").is_file())

    def test_validation_is_bound_to_machine_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / MANIFEST).write_text("{}", encoding="utf-8")
            import hashlib
            digest = hashlib.sha256(b"{}").hexdigest()
            record = {"schema": 2, "manifest_sha256": digest, "host": platform.node(),
                      "machine": platform.machine(), "macos": platform.mac_ver()[0],
                      "watermark_verified": True,
                      "authorization": "licensed_topaz_checkout",
                      "scales": {"proteus-v4": [1, 4]}}
            (root / VALIDATION).write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(local_validation(root)["proteus-v4"], [1, 4])
            record["host"] = "another-host"
            (root / VALIDATION).write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(local_validation(root), {})
            record["host"] = platform.node()
            (root / VALIDATION).write_text(json.dumps(record), encoding="utf-8")
            (root / MANIFEST).write_text('{"changed":true}', encoding="utf-8")
            self.assertEqual(local_validation(root), {})

    def test_license_context_is_referenced_without_reading_or_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            license_file = root / "license.lic"
            license_file.write_bytes(b"opaque-machine-license")
            self.assertEqual(resolve_license_dir(root), root.resolve())
            self.assertEqual(license_file.read_bytes(), b"opaque-machine-license")
            license_file.unlink()
            with mock.patch("backend.topaz_video.license.MAC_APP_MODELS", root / "missing"), \
                    mock.patch.dict("os.environ", {}, clear=True):
                self.assertIsNone(resolve_license_dir(root))


class FakeRuntime:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def status(self):
        return {"engine": "fake", "ready": True, "models": [
            {"id": "proteus-v4", "available": True, "reason": "", "verified": False,
             "scales": [1, 4], "verified_scales": []}]}

    def probe_binary(self):
        return Path("/bin/echo")

    def execute(self, spec, directory, asset, cancelled, progress):
        self.started.set()
        progress({"stage": "推理", "message": "处理帧", "percent": 42})
        while not self.release.wait(0.01):
            if cancelled.is_set():
                return "cancelled", ""
        output = directory / "result/enhanced.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"synthetic")
        (output.parent / "provenance.json").write_text(json.dumps({
            "schema": 1,
            "watermark_verified": True,
            "verification": "licensed_topaz_checkout",
        }), encoding="utf-8")
        return "succeeded", ""


class TaskLifecycleTest(unittest.TestCase):
    def test_completed_no_watermark_job_promotes_catalogue_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TopazVideoService(directory, FakeRuntime())
            try:
                verified = service.store.create(_data(scale=1))
                service.store.update(verified["id"], status="succeeded", watermark_verified=True,
                                     export_provenance="licensed_topaz_checkout")
                rejected = service.store.create(_data(scale=4))
                service.store.update(rejected["id"], status="succeeded", watermark_verified=False,
                                     export_provenance="licensed_topaz_checkout")
                model = service.status()["models"][0]
                self.assertTrue(model["verified"])
                self.assertEqual(model["verified_scales"], [1])
                self.assertIn("1×", model["reason"])
                self.assertIn("其他倍率", model["reason"])
            finally:
                service.close()

    def test_submit_progress_result_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime()
            service = TopazVideoService(directory, runtime)
            try:
                asset = service.store.upload(b"\x00\x00\x00\x00ftypdemo", "sample.mp4")
                spec = _data(asset_id=asset["asset_id"])
                job = service.submit(spec)
                self.assertTrue(runtime.started.wait(3))
                self.assertEqual(service.job(job["id"])["progress_percent"], 42)
                runtime.release.set()
                for _ in range(200):
                    current = service.job(job["id"])
                    if current["status"] == "succeeded":
                        break
                    time.sleep(0.01)
                self.assertEqual(current["status"], "succeeded")
                self.assertEqual(current["progress_percent"], 100)
                self.assertTrue(current["watermark_verified"])
                self.assertEqual(current["export_provenance"], "licensed_topaz_checkout")
                self.assertEqual(service.store.artifact(job["id"], "result/enhanced.mp4").read_bytes(), b"synthetic")
                self.assertIn("/api/topaz_video/artifact?", current["artifacts"][0]["url"])
                runtime.started.clear()
                runtime.release.clear()
                second = service.submit(spec)
                self.assertTrue(runtime.started.wait(3))
                service.cancel(second["id"])
                for _ in range(200):
                    current = service.job(second["id"])
                    if current["status"] == "cancelled":
                        break
                    time.sleep(0.01)
                self.assertEqual(current["status"], "cancelled")
                self.assertFalse(current["artifacts"])
            finally:
                runtime.release.set()
                service.close()

    def test_restart_marks_orphans_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            job = store.create(_data())
            store.update(job["id"], status="running")
            store.recover()
            self.assertEqual(store.get(job["id"])["status"], "interrupted")
            with self.assertRaises(ValueError):
                store.asset("../escape")
            with self.assertRaises(FileNotFoundError):
                store.artifact(job["id"], "../../etc/passwd")

    def test_artifact_is_fail_closed_without_no_watermark_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            job = store.create(_data())
            output = store.path(job["id"]) / "result/enhanced.mp4"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"legacy-watermarked-result")
            store.update(job["id"], status="succeeded",
                         artifacts=[{"name": "result/enhanced.mp4"}])
            with self.assertRaisesRegex(FileNotFoundError, "无水印验收"):
                store.artifact(job["id"], "result/enhanced.mp4")
            store.update(job["id"], watermark_verified=True)
            self.assertEqual(store.artifact(job["id"], "result/enhanced.mp4"), output.resolve())


if __name__ == "__main__":
    unittest.main()
