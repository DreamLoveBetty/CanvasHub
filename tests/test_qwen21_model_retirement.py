"""Tiny pinned fixtures: retiring a Transformer must retain shared component integrity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest import mock

from backend.qwen21 import install, model_store
from backend.qwen21.contracts import DEFAULT_MODEL_ID, MODEL_REVISION
from backend.qwen21.model_store import BaseModelStore, shared_model_file
from backend.qwen21.service import Service


class ModelRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = BaseModelStore(self.root / "data/assets", self.root / "component")
        self.payloads = {name: (name + " synthetic fixture").encode() for name in (
            "README.md", "processor/tokenizer.json", "text_encoder/0.safetensors", "vae/0.safetensors",
            "transformer/config.json", "transformer/model.safetensors.index.json",
            "transformer/0.safetensors", "transformer/1.safetensors")}
        files = [{"rfilename": name, "size": len(data), "blobId": "synthetic-blob",
                  "lfs": {"sha256": hashlib.sha256(data).hexdigest()}} for name, data in self.payloads.items()]
        for module, name in ((model_store, "BUILTIN_FILES"), (install, "FILES")):
            patch = mock.patch.object(module, name, files)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(install, "download", side_effect=self.download)
        self.download_mock = patch.start()
        self.addCleanup(patch.stop)
        headers = mock.patch.object(install, "_headers", return_value={})
        headers.start()
        self.addCleanup(headers.stop)
        install.prepare_model(self.root / "data", "https://huggingface.co")
        self.download_mock.reset_mock()
        self.add_model("fixture-bf16", "bf16")
        self.add_model("fixture-custom8", "8bit")

    def download(self, url, path, **kwargs):
        name = path.relative_to(self.store.shared).as_posix()
        data = self.payloads[name]
        assert hashlib.sha256(data).hexdigest() == kwargs["sha256_value"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)

    def add_model(self, model_id, precision):
        directory = self.store.directory / model_id
        file = directory / "transformer/0.safetensors"
        file.parent.mkdir(parents=True)
        if precision == "bf16":
            header = {f"tensor_{i}": {"dtype": "BF16", "shape": [1], "data_offsets": [i*2, i*2+2]}
                      for i in range(297)}
            header["__metadata__"] = {"precision": "bf16", "quantization_level": "None"}
            encoded = json.dumps(header).encode()
            file.write_bytes(struct.pack("<Q", len(encoded)) + encoded + bytes(594))
        else:
            file.write_bytes(b"synthetic packed checkpoint")
        for name in ("text_encoder", "vae", "processor"):
            (directory / name).symlink_to(self.store.shared / name, target_is_directory=True)
        stat = file.stat()
        manifest = {"schema_version": 1, "architecture": "qwen-image-2.1", "id": model_id,
                    "name": "Synthetic Heretic", "builtin": False, "precision": precision,
                    "source_tensor_count": 297, "output_tensor_count": 297,
                    "quantized_linear_count": 0 if precision == "bf16" else 228,
                    "group_size": None if precision == "bf16" else 64,
                    "verification": {"strict_load": True, "strict_reload": True},
                    "verified_files": {"transformer/0.safetensors": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}}}
        (directory / "manifest.json").write_text(json.dumps(manifest))

    def test_only_pinned_builtin_transformer_files_are_removed(self):
        preserved = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.store.directory.rglob("*")
                     if p.is_file() and p not in {self.store.shared / f"transformer/{i}.safetensors" for i in range(2)}}
        reply = self.store.delete(DEFAULT_MODEL_ID)
        self.assertEqual(reply["removed_bytes"], sum(len(self.payloads[f"transformer/{i}.safetensors"]) for i in range(2)))
        self.assertTrue(reply["shared_components_retained"])
        self.assertEqual([m["id"] for m in self.store.list()], ["fixture-bf16", "fixture-custom8"])
        self.assertTrue(all(m["ready"] for m in self.store.list()))
        self.assertEqual(self.store.resolve("fixture-bf16")["label"], "Synthetic Heretic（BF16）")
        self.assertEqual(self.store.resolve(None)["id"], "fixture-bf16")
        self.assertEqual(self.store.selection()["model_replacements"], {DEFAULT_MODEL_ID: "fixture-bf16"})
        for path, expected in preserved.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected, path.name)
        with self.assertRaisesRegex(ValueError, "已删除"):
            self.store.resolve(DEFAULT_MODEL_ID)
        reloaded = BaseModelStore(self.root / "data/assets", self.root / "component")
        self.assertEqual(reloaded.selection(), self.store.selection())
        self.assertEqual(reloaded.delete(DEFAULT_MODEL_ID)["removed_bytes"], 0)

    def test_legacy_complete_receipt_still_validates_shared_components(self):
        (self.store.shared / ".shared-manifest.json").unlink()
        self.store.delete(DEFAULT_MODEL_ID)
        self.assertTrue(self.store.resolve("fixture-bf16")["ready"])
        (self.store.shared / "text_encoder/0.safetensors").write_bytes(b"corrupt")
        self.assertFalse(any(m["ready"] for m in self.store.list()))

    def test_shared_receipt_cannot_skip_visual_component_or_change_revision(self):
        receipt = self.store.shared / ".shared-manifest.json"
        original = json.loads(receipt.read_text())
        for change in ("missing_component", "revision", "checksum"):
            value = json.loads(json.dumps(original))
            if change == "missing_component":
                value["verified_files"].pop("processor/tokenizer.json")
            elif change == "revision":
                value["repo_revision"] = "wrong"
            else:
                value["verified_files"]["vae/0.safetensors"]["sha256"] = "f"*64
            receipt.write_text(json.dumps(value))
            with self.subTest(change=change):
                self.assertFalse(self.store.list()[1]["ready"])
        self.assertEqual(original["repo_revision"], MODEL_REVISION)

    def test_normal_or_shared_prepare_never_downloads_retired_transformer(self):
        self.store.delete(DEFAULT_MODEL_ID)
        for shared_only in (False, True):
            self.download_mock.reset_mock()
            install.prepare_model(self.root / "data", "https://huggingface.co", shared_only=shared_only)
            names = [call.args[1].relative_to(self.store.shared).as_posix() for call in self.download_mock.call_args_list]
            self.assertEqual(set(names), {name for name in self.payloads if shared_model_file(name)})
            self.assertFalse(list((self.store.shared / "transformer").glob("*.safetensors")))
            self.assertTrue(all(m["ready"] for m in self.store.list()))

    def test_shared_only_preparation_keeps_existing_builtin_available(self):
        before = (self.store.shared / "manifest.json").read_bytes()
        install.prepare_model(self.root / "data", "https://huggingface.co", shared_only=True)
        self.assertEqual((self.store.shared / "manifest.json").read_bytes(), before)
        self.assertTrue(self.store.resolve(DEFAULT_MODEL_ID)["ready"])
        self.assertEqual(self.store.selection(), {"default_model_id": DEFAULT_MODEL_ID, "model_replacements": {}})

    def test_missing_builtin_without_retirement_still_visible(self):
        (self.store.shared / "transformer/0.safetensors").unlink()
        self.assertEqual(self.store.list()[0]["id"], DEFAULT_MODEL_ID)
        self.assertFalse(self.store.list()[0]["ready"])
        self.assertTrue(self.store.resolve("fixture-bf16")["ready"])

    def test_corrupt_selection_fails_closed_without_downloading(self):
        (self.store.directory / ".selection.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "选择记录"):
            install.prepare_model(self.root / "data", "https://huggingface.co")
        self.download_mock.assert_not_called()

    def test_last_custom_base_cannot_be_deleted_after_retirement(self):
        self.store.delete(DEFAULT_MODEL_ID)
        self.store.delete("fixture-bf16")
        self.assertEqual(self.store.selection()["default_model_id"], "fixture-custom8")
        with self.assertRaisesRegex(ValueError, "至少一个"):
            self.store.delete("fixture-custom8")

    def test_cannot_retire_without_ready_replacement(self):
        self.store.delete("fixture-bf16")
        self.store.delete("fixture-custom8")
        with self.assertRaisesRegex(ValueError, "替代 Base"):
            self.store.delete(DEFAULT_MODEL_ID)
        self.assertFalse(self.store.builtin_removed)

    def service(self):
        service = Service.__new__(Service)
        service.models = self.store
        service.root, service.component = self.root / "data", self.root / "component"
        service._model_lock = threading.RLock()
        service.runtime = mock.Mock(python=Path(__file__))
        service.runtime.status.return_value = {"environment_ready": True, "source_ready": True}
        service.preparation = mock.Mock()
        service.preparation.status.return_value = {"status": "idle"}
        service.conversion = mock.Mock()
        service.conversion.status.return_value = {"status": "idle"}
        service.get_all_tasks = lambda **kwargs: []
        service.loras = mock.Mock()
        service.loras.list.return_value = []
        service.vaes = mock.Mock()
        service.vaes.status.return_value = {}
        return service

    def test_service_default_catalog_prepare_and_submission_follow_retirement(self):
        self.store.delete(DEFAULT_MODEL_ID)
        service = self.service()
        for reply in (service.status(), service.catalog(), service.model_tools()):
            self.assertEqual(reply["default_model_id"], "fixture-bf16")
        self.assertEqual(service.catalog()["defaults"]["base_model_id"], "fixture-bf16")
        service.prepare({"preset": "standard"})
        self.assertIn("--shared-only", service.preparation.start.call_args.args[0])
        self.assertEqual(service.preparation.start.call_args.args[2]["base_model_id"], "fixture-bf16")
        with self.assertRaisesRegex(ValueError, "已不存在"):
            service.prepare({"base_model_id": DEFAULT_MODEL_ID})
        service.runtime.status.return_value = {"environment_ready": False}
        with mock.patch.object(self.store, "resolve", wraps=self.store.resolve) as resolve:
            with self.assertRaisesRegex(RuntimeError, "尚未就绪"):
                service.submit({"prompt": "synthetic"})
            resolve.assert_called_once_with("fixture-bf16")
        with self.assertRaisesRegex(ValueError, "已删除"):
            service.submit({"prompt": "synthetic", "base_model_id": DEFAULT_MODEL_ID})

    def test_service_blocks_deletion_during_preparation_conversion_or_generation(self):
        service = self.service()
        with mock.patch.object(self.store, "delete") as delete:
            for guard in ("preparation", "conversion", "generation"):
                service.preparation.status.return_value = {"status": "running" if guard == "preparation" else "idle"}
                service.conversion.status.return_value = {"status": "running" if guard == "conversion" else "idle"}
                service._model_in_use = lambda model_id: guard == "generation"
                with self.subTest(guard=guard), self.assertRaises(RuntimeError):
                    service.delete_model(DEFAULT_MODEL_ID)
            delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
