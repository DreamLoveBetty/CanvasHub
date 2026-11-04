import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.moss import assets, contracts, environment
from backend.moss.model_store import ModelStore, STUDENT_LOCATIONS, whitelist
from backend.moss.native_adapter import PARTS

ROOT = Path(__file__).resolve().parents[1]


def shard(path, tensors):
    header, offset = {}, 0
    for key, shape in tensors.items():
        header[key] = {"dtype": "BF16", "shape": shape, "data_offsets": [offset, offset + 2]}
        offset += 2
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + b"\0" * offset)
    return path


def entry(path):
    raw = Path(path).read_bytes()
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.source, self.state, self.assets = self.base / "src", self.base / "state", self.base / "assets"
        layout = {"transformer": {"layers.0.proj.q.weight": [3072, 3072], "layers.0.proj.o.weight": [3072, 3072]},
                  "text_encoder": {"norm.weight": [4, 4]}, "vae": {"decoder.conv_in.weight": [3, 3]}}
        files = {}
        for part, tensors in layout.items():
            path = shard(self.source / part / "0.safetensors", tensors)
            files[f"{part}/0.safetensors"] = entry(path)
            (self.source / part / "model.safetensors.index.json").write_text(
                json.dumps({"weight_map": {key: "0.safetensors" for key in tensors}}))
        (self.source / "tokenizer").mkdir()
        for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
            (self.source / "tokenizer" / name).write_text(name)
        student = self.source / STUDENT_LOCATIONS[0]
        student.parent.mkdir()
        student.write_bytes(b"student")
        destripe = self.assets / "destripe.safetensors"
        self.assets.mkdir()
        destripe.write_bytes(b"destripe")
        configs = {}
        for part in PARTS:
            config = self.assets / "configs" / part / "config.json"
            config.parent.mkdir(parents=True)
            config.write_text("{}")
            configs[f"{part}/config.json"] = entry(config)
        self.lock = {"base_model": {"id": contracts.DEFAULT_MODEL_ID, "files": files},
                     "configs": {"files": configs},
                     "managed": {"student": {"file": "turbo_student.safetensors", **entry(student)},
                                 "destripe": {"file": "loras/destripe.safetensors", **entry(destripe)}}}
        self.store = ModelStore(self.state, self.assets, lock=self.lock)

    def tree(self):
        return {str(path): (path.stat().st_mtime_ns, path.stat().st_size)
                for path in self.source.rglob("*") if path.is_file()}

    def rewrite_locked(self, relative, tensors):
        """Change a shard and accept it in the lock, to reach the checks behind the hash."""
        path = shard(self.source / relative, tensors)
        self.lock["base_model"]["files"][relative] = entry(path)


class Binding(Fixture):
    def test_bind_is_read_only_and_public_state_hides_paths(self):
        before = self.tree()
        public = self.store.bind(str(self.source))
        self.assertEqual(self.tree(), before)
        self.assertTrue(public["ready"])
        self.assertNotIn(str(self.base), json.dumps(public))
        resolved = self.store.resolve()
        self.assertEqual(resolved.fingerprint, public["fingerprint"])
        self.assertTrue((resolved.view_path / "transformer/0.safetensors").is_symlink())
        self.assertFalse(str(resolved.view_path).startswith(str(self.source)))

    def test_view_config_comes_from_managed_assets(self):
        self.store.bind(str(self.source))
        self.assertFalse((self.store.resolve().view_path / "vae/config.json").is_symlink())

    def test_non_whitelisted_changes_do_not_invalidate(self):
        self.store.bind(str(self.source))
        (self.source / ".DS_Store").write_text("x")
        (self.source / "README.md").write_text("x")
        (self.source / "lora" / "ordinary.safetensors").write_bytes(b"x")
        (self.source / "mflux_model.json").write_text("{}")
        self.assertTrue(self.store.public()["ready"])
        self.store.resolve()

    def test_whitelisted_changes_invalidate(self):
        for relative in ("transformer/0.safetensors", "transformer/model.safetensors.index.json",
                         "tokenizer/chat_template.jinja", STUDENT_LOCATIONS[0]):
            with self.subTest(relative=relative):
                self.store.bind(str(self.source))
                path = self.source / relative
                original, stamp = path.read_bytes(), path.stat()
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "已失效"):
                    self.store.resolve()
                self.assertFalse(self.store.public()["ready"])
                path.write_bytes(original)
                os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def test_view_link_retarget_and_loss_invalidate(self):
        self.store.bind(str(self.source))
        view = self.store.resolve().view_path
        (view / "vae/0.safetensors").unlink()
        with self.assertRaisesRegex(ValueError, "模型视图"):
            self.store.resolve()
        self.store.bind(str(self.source))
        link = self.store.resolve().view_path / "vae/0.safetensors"
        link.unlink()
        link.symlink_to(self.source / "text_encoder/0.safetensors")
        with self.assertRaisesRegex(ValueError, "模型视图"):
            self.store.resolve()

    def test_removed_file_invalidates(self):
        self.store.bind(str(self.source))
        (self.source / "vae/0.safetensors").unlink()
        with self.assertRaisesRegex(ValueError, "丢失"):
            self.store.resolve()

    def test_rebinding_replaces_the_view(self):
        first = self.store.bind(str(self.source))
        second = self.store.bind(str(self.source))
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_unbound_model_is_not_ready(self):
        self.assertFalse(self.store.public()["ready"])
        with self.assertRaisesRegex(ValueError, "尚未绑定"):
            self.store.resolve()

    def test_student_found_at_the_root_or_in_lora(self):
        moved = self.source / STUDENT_LOCATIONS[1]
        (self.source / STUDENT_LOCATIONS[0]).rename(moved)
        self.store.bind(str(self.source))
        self.assertEqual(self.store.resolve().student_path, moved)

    def test_same_student_in_both_locations_is_fine(self):
        shutil.copyfile(self.source / STUDENT_LOCATIONS[0], self.source / STUDENT_LOCATIONS[1])
        self.assertTrue(self.store.bind(str(self.source))["ready"])

    def test_two_different_students_are_rejected(self):
        (self.source / STUDENT_LOCATIONS[1]).write_bytes(b"other")
        with self.assertRaisesRegex(ValueError, "不同的 Turbo student"):
            self.store.bind(str(self.source))

    def test_student_falls_back_to_prepared_assets(self):
        shutil.move(self.source / STUDENT_LOCATIONS[0], self.assets / "turbo_student.safetensors")
        self.store.bind(str(self.source))
        self.assertEqual(self.store.resolve().student_path, self.assets / "turbo_student.safetensors")

    def test_missing_prepared_inputs_ask_for_preparation(self):
        (self.source / STUDENT_LOCATIONS[0]).unlink()
        with self.assertRaisesRegex(ValueError, "准备"):
            self.store.bind(str(self.source))

    def test_missing_shard_is_rejected(self):
        (self.source / "vae/0.safetensors").unlink()
        with self.assertRaisesRegex(ValueError, "缺少文件"):
            self.store.bind(str(self.source))

    def test_hash_mismatch_is_rejected(self):
        self.lock["base_model"]["files"]["vae/0.safetensors"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "锁定版本"):
            self.store.bind(str(self.source))

    def test_duplicate_tensor_across_shards_is_rejected(self):
        extra = shard(self.source / "vae/1.safetensors", {"decoder.conv_in.weight": [3, 3]})
        self.lock["base_model"]["files"]["vae/1.safetensors"] = entry(extra)
        with self.assertRaisesRegex(ValueError, "重复张量"):
            self.store.bind(str(self.source))

    def test_shard_that_disagrees_with_its_index_is_rejected(self):
        self.rewrite_locked("vae/0.safetensors", {"decoder.other.weight": [3, 3]})
        with self.assertRaisesRegex(ValueError, "索引不一致"):
            self.store.bind(str(self.source))

    def test_wrong_shape_is_rejected(self):
        self.rewrite_locked("transformer/0.safetensors",
                            {"layers.0.proj.q.weight": [3072, 16], "layers.0.proj.o.weight": [3072, 3072]})
        with self.assertRaisesRegex(ValueError, "shape"):
            self.store.bind(str(self.source))

    def test_state_inside_the_source_is_rejected(self):
        store = ModelStore(self.source / "state", self.assets, lock=self.lock)
        with self.assertRaisesRegex(ValueError, "源权重目录内"):
            store.bind(str(self.source))

    def test_relative_or_unknown_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "绝对路径"):
            self.store.bind("relative/path")
        with self.assertRaisesRegex(ValueError, "Base 模型"):
            self.store.bind(str(self.source), "other-model")

    def test_size_must_stay_a_multiple_of_sixteen(self):
        with self.assertRaises(ValueError):
            contracts.validate_size(1000, 1024)


class ShippedLocks(unittest.TestCase):
    def test_asset_lock_is_complete_and_pinned(self):
        lock = assets.load_lock()
        self.assertEqual(len(lock["base_model"]["files"]), 14)
        self.assertEqual(lock["base_model"]["id"], contracts.DEFAULT_MODEL_ID)
        self.assertEqual(len(whitelist(lock)), 20)
        items = [*lock["base_model"]["files"].values(), *lock["configs"]["files"].values(), *lock["managed"].values()]
        for item in items:
            self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$")
            self.assertGreater(item["size"], 0)
        for source in (lock["base_model"], lock["configs"], *lock["managed"].values()):
            self.assertRegex(source["revision"], r"^[a-f0-9]{40}$")
            self.assertEqual(source["license"], "Apache-2.0")

    def test_requirements_are_exact_hashed_and_exclude_mflux(self):
        pinned = environment.pinned_packages()
        self.assertEqual((pinned["moss-image-mlx"], pinned["mlx"], pinned["mlx-lm"], pinned["transformers"]),
                         ("0.2.0", "0.32.4", "0.32.2", "5.10.4"))
        self.assertNotIn("mflux", pinned)
        text = environment.REQUIREMENTS.read_text()
        self.assertEqual(text.count("=="), len(pinned))
        self.assertGreaterEqual(text.count("--hash=sha256:"), len(pinned))

    def test_domain_does_not_import_test_code_or_heavy_runtime_at_module_level(self):
        for path in (ROOT / "backend/moss").glob("*.py"):
            for line in path.read_text().splitlines():
                if line.startswith(("import ", "from ")):
                    self.assertFalse(any(name in line for name in ("tests", "mlx", "transformers", "mflux")), line)


class Environment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "moss"
        self.commands, self.fetched = [], []
        platform = patch.object(environment, "supported_platform", return_value=True)
        platform.start()
        self.addCleanup(platform.stop)
        quiet = patch.object(environment, "emit")
        quiet.start()
        self.addCleanup(quiet.stop)

    def run_fake(self, command, check):
        self.assertTrue(check)
        self.commands.append([str(part) for part in command])
        if command[1] == "venv":
            python = Path(command[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("")

    def fetch_fake(self, url, path, *, size, sha256_value):
        self.fetched.append((url, Path(path).name))

    def prepare(self, source=None, python=None):
        python = python or self.root.parent / "python"
        python.write_text("") if not python.exists() else None
        return environment.prepare(root=self.root, source=source, uv="/bin/uv", python=python, run=self.run_fake,
                                   fetch=self.fetch_fake)

    def test_status_before_prepare_reports_reason_without_paths(self):
        result = environment.status(self.root)
        self.assertFalse(result["ready"])
        self.assertIn("尚未准备", result["reasons"][0])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_status_never_touches_the_network_or_creates_state(self):
        environment.status(self.root)
        self.assertFalse(self.root.exists())

    def test_unsupported_platform_is_never_ready(self):
        with patch.object(environment, "supported_platform", return_value=False):
            self.assertIn("Apple Silicon", environment.status(self.root)["reasons"][0])
            with self.assertRaisesRegex(RuntimeError, "Apple Silicon"):
                environment.prepare(root=self.root, uv="/bin/uv", python=self.root / "python")

    def test_prepare_uses_the_hash_lock_and_pinned_urls(self):
        self.root.parent.mkdir(exist_ok=True)
        with patch.object(environment, "probe_packages", return_value=[]):
            with patch.object(environment, "status", wraps=lambda root: {"ready": True}):
                self.prepare()
        install = next(command for command in self.commands if command[1:3] == ["pip", "install"])
        self.assertIn("--require-hashes", install)
        self.assertIn("--no-config", install)
        self.assertEqual(install[-1], str(environment.REQUIREMENTS))
        self.assertEqual(sum(command[1] == "venv" for command in self.commands), 1)
        urls = [url for url, _ in self.fetched]
        self.assertEqual(len(urls), 5)
        self.assertTrue(all("/resolve/" in url and "/main/" not in url for url in urls))
        receipt = json.loads((self.root / "installed.json").read_text())
        self.assertEqual(Path(receipt["python"]), environment.venv_python(self.root))

    def test_existing_student_is_not_downloaded(self):
        source = self.root.parent / "source"
        (source / "lora").mkdir(parents=True)
        (source / STUDENT_LOCATIONS[0]).write_bytes(b"x")
        with patch.object(environment, "status", wraps=lambda root: {"ready": True}):
            self.prepare(source=source)
        self.assertNotIn("turbo_student.safetensors", [name for _, name in self.fetched])

    def test_failure_leaves_no_receipt(self):
        self.root.parent.mkdir(exist_ok=True)
        def fail(*_args, **_kwargs):
            raise subprocess.CalledProcessError(1, "uv")
        (self.root.parent / "python").write_text("")
        with self.assertRaises(subprocess.CalledProcessError):
            environment.prepare(root=self.root, uv="/bin/uv", python=self.root.parent / "python", run=fail)
        self.assertFalse((self.root / "installed.json").exists())

    def test_missing_uv_or_python_is_a_clear_error(self):
        with patch.object(environment.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "uv"):
                environment.prepare(root=self.root, python=self.root / "python")
        with self.assertRaisesRegex(RuntimeError, "共享 Python"):
            environment.prepare(root=self.root, uv="/bin/uv", python=self.root / "missing")

    def test_frozen_build_takes_python_from_a_receipt(self):
        components = self.root.parent / "components"
        python = components / "python"
        (components / "krea2").mkdir(parents=True)
        python.write_text("")
        (components / "krea2/installed.json").write_text(json.dumps({"python": str(python)}))
        with patch.object(environment.sys, "frozen", True, create=True):
            self.assertEqual(environment.base_python(components), python)
            self.assertIsNone(environment.base_python(components / "empty"))

    def test_status_detects_lock_drift(self):
        self.root.mkdir(parents=True)
        (self.root / "installed.json").write_text(json.dumps({"prepared_at": 1, "versions": {"mlx": "0.32.4"}}))
        python = environment.venv_python(self.root)
        self.assertIn("丢失", environment.status(self.root)["reasons"][0])
        python.parent.mkdir(parents=True)
        python.write_text("")
        self.assertTrue(environment.status(self.root, probe=lambda *_: [])["ready"])
        self.assertIn("mlx", environment.status(self.root, probe=lambda *_: ["mlx"])["reasons"][0])
        def broken(*_args):
            raise OSError("boom")
        self.assertIn("无法读取", environment.status(self.root, probe=broken)["reasons"][0])


if __name__ == "__main__":
    unittest.main()
