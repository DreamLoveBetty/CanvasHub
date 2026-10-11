"""Turbo distilled Base + shared BF16 text encoder; tiny synthetic fixtures, no MLX."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from backend.qwen21 import bundle_import, install, model_store, text_encoder
from backend.qwen21.contracts import DEFAULT_MODEL_ID, normalize_job
from backend.qwen21.model_store import BaseModelStore
from backend.qwen21.profiles import (ADAPTERS, PRESETS, TURBO_PRESET, TURBO_SIGMAS, preset_kind,
                                     turbo_sigmas, viggle_sigmas)
from backend.qwen21.service import Service
from backend.qwen21.weight_schema import expected_shapes


def safetensors(tensors, dtype="BF16", metadata=None):
    header = {key: {"dtype": dtype, "shape": list(shape), "data_offsets": [0, 2]} for key, shape in tensors.items()}
    header["__metadata__"] = metadata or {"quantization_level": "None", "mflux_version": "0.20.0"}
    encoded = json.dumps(header).encode()
    return struct.pack("<Q", len(encoded)) + encoded + b"\0\0"


def native_transformer():
    """Two shards with the exact raw 297-tensor schema, plus index and config."""
    keys = sorted(expected_shapes())
    shapes = expected_shapes()
    shards = {"0.safetensors": keys[:150], "1.safetensors": keys[150:]}
    files = {f"transformer/{name}": safetensors({key: shapes[key] for key in group})
             for name, group in shards.items()}
    files["transformer/model.safetensors.index.json"] = json.dumps(
        {"weight_map": {key: name for name, group in shards.items() for key in group}}).encode()
    files["transformer/config.json"] = b'{"num_layers": 32}'
    return files


def bundle_payloads():
    files = native_transformer()
    files["model_index.json"] = json.dumps({"sample_sigmas": list(TURBO_SIGMAS)}).encode()
    files["text_encoder/0.safetensors"] = safetensors({"language_model.embed_tokens.weight": (8, 4)})
    files["text_encoder/config.json"] = b'{"model_type": "qwen3_vl"}'
    files["text_encoder/model.safetensors.index.json"] = json.dumps({"metadata": {"quantization_level": "None"},
        "weight_map": {"language_model.embed_tokens.weight": "0.safetensors",
                       "lm_head.weight": "generation_head.safetensors",
                       "language_model.norm.weight": "generation_head.safetensors"}}).encode()
    return files


def pinned(payloads):
    return [{"rfilename": name, "size": len(data), "blobId": "synthetic",
             "lfs": {"sha256": hashlib.sha256(data).hexdigest()}} for name, data in payloads.items()]


class TurboContractTests(unittest.TestCase):
    def test_turbo_preset_is_fixed_eight_steps_cfg_one_and_unshifted(self):
        self.assertEqual(PRESETS[TURBO_PRESET]["label"], "Turbo · 8 步")
        self.assertEqual(preset_kind(TURBO_PRESET), "distilled")
        self.assertEqual(preset_kind("standard"), "standard")
        self.assertEqual({preset_kind(key) for key in ADAPTERS}, {"adapter"})
        spec = normalize_job({"prompt": "x", "preset": TURBO_PRESET})
        self.assertEqual((spec["steps"], spec["guidance"]), (8, 1))
        for fields in ({"steps": 7}, {"steps": 9}, {"guidance": 2}, {"negative_prompt": "blur"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                normalize_job({"prompt": "x", "preset": TURBO_PRESET, **fields})
        tokens = [f"{index:032x}" for index in range(10)]
        self.assertEqual(len(normalize_job({"prompt": "x", "mode": "edit", "preset": TURBO_PRESET,
                                            "reference_upload_tokens": tokens})["reference_upload_tokens"]), 10)
        # The official schedule is used verbatim at every resolution (shift=1, no dynamic shift).
        self.assertEqual(turbo_sigmas(8), [*TURBO_SIGMAS, 0.0])
        self.assertNotEqual(viggle_sigmas(8, 1024, 1024)[1:3], list(TURBO_SIGMAS[1:3]))
        for steps in (6, 7, 9, True):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                turbo_sigmas(steps)
        with self.assertRaises(ValueError):
            preset_kind("turbo-6")


class TurboServiceTests(unittest.TestCase):
    def make_service(self, model):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.tasks, self.queued = {}, []
        runtime = mock.Mock()
        # No Viggle adapter is present: the distilled preset must not require one.
        runtime.status.return_value = {"environment_ready": True, "source_ready": True,
                                       "turbo_ready": False, "turbo_adapters": {key: False for key in ADAPTERS}}
        runtime.python = Path(__file__)
        store = mock.Mock()
        store.resolve.return_value = {**model, "precision": "bf16", "path": root / "base"}
        store.list.return_value = [{"id": model["id"], "ready": True}]
        store.selection.return_value = {"default_model_id": model["id"], "model_replacements": {}}

        def create(task_id, prompt, params, **kwargs):
            self.tasks[task_id] = {"params": params, **kwargs}
        patcher = mock.patch("backend.qwen21.service.ImageTaskQueue")
        queue = patcher.start()
        self.addCleanup(patcher.stop)
        queue.return_value.enqueue.side_effect = lambda task_id, spec, create: (create(), self.queued.append(spec))
        service = Service(root / "data", root / "components/qwen21", runtime, create_task=create,
                          get_task=self.tasks.get, get_all_tasks=lambda **kwargs: [], update_task=mock.Mock(),
                          update_task_status=mock.Mock(), update_task_fields=mock.Mock(),
                          daily_output_dir=lambda: root / "archive", write_prompt_sidecar=mock.Mock(),
                          send_document=mock.Mock(), model_store=store, conversion_service=mock.Mock())
        self.addCleanup(service.close)
        return service

    def test_distilled_base_and_turbo_preset_only_pair_with_each_other(self):
        turbo = self.make_service({"id": "turbo-bf16", "name": "Turbo", "sampling": TURBO_PRESET,
                                   "text_encoder": {"id": "heretic-bf16"}})
        reply = turbo.submit({"prompt": "teapot", "preset": TURBO_PRESET})
        self.assertEqual(self.queued[-1]["preset"], TURBO_PRESET)
        self.assertEqual(self.queued[-1]["steps"], 8)
        self.assertEqual(self.tasks[reply["task_id"]]["params"]["text_encoder"], "heretic-bf16")
        for preset in ("standard", *ADAPTERS):
            with self.subTest(preset=preset), self.assertRaisesRegex(ValueError, "只能使用"):
                turbo.submit({"prompt": "teapot", "preset": preset})
        base = self.make_service({"id": "heretic-bf16", "name": "Heretic"})
        with self.assertRaisesRegex(ValueError, "仅适用于"):
            base.submit({"prompt": "teapot", "preset": TURBO_PRESET})

    def test_preparing_turbo_preset_downloads_no_adapter(self):
        service = self.make_service({"id": "turbo-bf16", "name": "Turbo", "sampling": TURBO_PRESET})
        with mock.patch.object(service.preparation, "start", return_value={"ok": True}) as start:
            service.prepare({"base_model_id": "turbo-bf16", "preset": TURBO_PRESET})
            command = start.call_args.args[0]
            self.assertNotIn("--turbo", command)
            self.assertIn("--shared-only", command)
            service.prepare({"base_model_id": "turbo-bf16", "preset": "viggle-v03-r256"})
            self.assertIn("--turbo", start.call_args.args[0])


class SharedEncoderAndImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.data = self.root / "data"
        self.store = BaseModelStore(self.data / "assets", self.data)
        self.payloads = {name: (name + " synthetic 8-bit").encode() for name in (
            "processor/tokenizer.json", "text_encoder/0.safetensors", "text_encoder/config.json",
            "text_encoder/model.safetensors.index.json", "vae/0.safetensors",
            "transformer/config.json", "transformer/0.safetensors")}
        for module, name in ((model_store, "BUILTIN_FILES"), (install, "FILES")):
            patcher = mock.patch.object(module, name, pinned(self.payloads))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(install, "download", side_effect=self.download)
        self.download_mock = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(install, "_headers", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        install.prepare_model(self.data, "https://huggingface.co")
        self.download_mock.reset_mock()
        self.bundle = self.root / "download"
        self.bundle_files = bundle_payloads()
        for name, data in self.bundle_files.items():
            (self.bundle / name).parent.mkdir(parents=True, exist_ok=True)
            (self.bundle / name).write_bytes(data)
        (self.bundle / "text_encoder/generation_head.safetensors").write_bytes(
            safetensors({"lm_head.weight": (8, 4), "language_model.norm.weight": (4,)}))
        patcher = mock.patch.object(bundle_import, "FILES", pinned(self.bundle_files))
        patcher.start()
        self.addCleanup(patcher.stop)

    def download(self, url, path, **kwargs):
        data = self.payloads[path.relative_to(self.store.shared).as_posix()]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)

    def import_bundle(self, *extra):
        with mock.patch.object(bundle_import, "active_tasks", return_value=[]), \
                mock.patch.object(bundle_import, "emit"):
            bundle_import.main(["--data", str(self.data), "--source", str(self.bundle), *extra])

    def test_import_registers_turbo_base_and_replaces_shared_encoder_in_place(self):
        before = {path: path.read_bytes() for path in self.bundle.rglob("*") if path.is_file()}
        self.import_bundle()
        model = self.store.resolve(bundle_import.MODEL_ID)
        self.assertTrue(model["ready"])
        self.assertEqual((model["sampling"], model["precision"], model["source_format"]),
                         (TURBO_PRESET, "bf16", "mflux-native"))
        self.assertEqual(model["label"], "Qwen-Image-2.1-Turbo-Heretic（BF16）")
        self.assertEqual(model["text_encoder"]["id"], "heretic-bf16")
        self.assertTrue((self.store.directory / bundle_import.MODEL_ID / "text_encoder").is_symlink())
        self.assertTrue(self.store.resolve(DEFAULT_MODEL_ID)["ready"], "builtin keeps working on the BF16 encoder")
        encoder = self.store.shared / "text_encoder"
        self.assertEqual((encoder / "0.safetensors").read_bytes(), self.bundle_files["text_encoder/0.safetensors"])
        self.assertFalse((encoder / "generation_head.safetensors").exists())
        index = json.loads((encoder / "model.safetensors.index.json").read_text())
        self.assertEqual(set(index["weight_map"]), {"language_model.embed_tokens.weight"})
        backup = self.store.shared / text_encoder.BACKUP
        self.assertEqual((backup / "0.safetensors").read_bytes(), self.payloads["text_encoder/0.safetensors"])
        self.assertEqual({path: path.read_bytes() for path in self.bundle.rglob("*") if path.is_file()}, before)
        self.assertFalse(list(self.store.staging.iterdir()))
        # Re-running is idempotent and never touches the 8-bit backup again.
        self.import_bundle()
        self.assertEqual([m["id"] for m in self.store.list()].count(bundle_import.MODEL_ID), 1)

    def test_shared_prepare_keeps_replacement_and_changes_fail_closed(self):
        self.import_bundle()
        for shared_only in (True, False):
            install.prepare_model(self.data, "https://huggingface.co", shared_only=shared_only)
            names = {call.args[1].relative_to(self.store.shared).as_posix()
                     for call in self.download_mock.call_args_list}
            self.assertFalse({name for name in names if name.startswith("text_encoder/")})
            self.assertTrue(all(item["ready"] for item in self.store.list()))
        (self.store.shared / "text_encoder/0.safetensors").write_bytes(b"changed")
        self.assertFalse(any(item["ready"] for item in self.store.list()))
        listed = {item["id"]: item for item in self.store.list()}
        self.assertEqual(listed[bundle_import.MODEL_ID]["text_encoder"]["id"], "invalid", "stays listed as not ready")
        with self.assertRaises(ValueError):
            install.prepare_model(self.data, "https://huggingface.co", shared_only=True)

    def test_restore_returns_pinned_eight_bit_encoder(self):
        self.import_bundle()
        with mock.patch.object(bundle_import, "active_tasks", return_value=[]), \
                mock.patch.object(bundle_import, "emit"):
            bundle_import.main(["--data", str(self.data), "--restore-text-encoder"])
        self.assertIsNone(text_encoder.read(self.store.shared))
        self.assertFalse((self.store.shared / text_encoder.BACKUP).exists())
        self.assertEqual((self.store.shared / "text_encoder/0.safetensors").read_bytes(),
                         self.payloads["text_encoder/0.safetensors"])
        self.assertTrue(all(item["ready"] for item in self.store.list()))
        self.assertEqual(self.store.resolve(DEFAULT_MODEL_ID)["text_encoder"]["id"], "heretic-8bit")

    def test_keep_text_encoder_and_rejections(self):
        self.import_bundle("--keep-text-encoder")
        self.assertIsNone(text_encoder.read(self.store.shared))
        self.assertTrue(self.store.resolve(bundle_import.MODEL_ID)["ready"])
        (self.bundle / "transformer/1.safetensors").write_bytes(b"tampered")
        with mock.patch.object(bundle_import, "emit"), self.assertRaisesRegex(RuntimeError, "固定版本"):
            bundle_import.verify_source(self.bundle)
        with mock.patch.object(bundle_import, "active_tasks", return_value=["qwen21_x"]), \
                self.assertRaisesRegex(RuntimeError, "任务"):
            bundle_import.main(["--data", str(self.data), "--restore-text-encoder"])

    def test_native_schema_tampering_is_not_ready(self):
        self.import_bundle("--keep-text-encoder")
        folder = self.store.directory / bundle_import.MODEL_ID
        shard = folder / "transformer/1.safetensors"
        manifest = json.loads((folder / "manifest.json").read_text())
        keys = sorted(expected_shapes())[150:]
        shard.write_bytes(safetensors({key: expected_shapes()[key] for key in keys}, dtype="F16"))
        stat = shard.stat()
        manifest["verified_files"]["transformer/1.safetensors"].update(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        (folder / "manifest.json").write_text(json.dumps(manifest))
        self.assertNotIn(bundle_import.MODEL_ID, [item["id"] for item in self.store.list()])


if __name__ == "__main__":
    unittest.main()
