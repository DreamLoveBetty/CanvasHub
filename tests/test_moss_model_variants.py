"""Transformer-only MOSS fine-tunes share the official encoder, VAE and adapters but bind as their own model."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from backend.moss import model_store
from backend.moss.contracts import DEFAULT_MODEL_ID
from backend.moss.model_store import ModelStore


def shard(path, tensors):
    header, offset = {}, 0
    for key, (shape, dtype) in tensors.items():
        header[key] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + 2]}
        offset += 2
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * offset)


def index(directory, mapping):
    (directory / model_store.INDEX_NAME).write_text(json.dumps({"weight_map": mapping}))


class VariantBinding(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.official, self.variant = self.tmp / "official", self.tmp / "Fine_Tune-mlx"
        self.tensors = {"final.weight": ([2], "BF16"), "time_embedding.2.weight": ([2], "BF16")}
        self.write_transformer(self.official, "0.safetensors", self.tensors)
        for part in ("text_encoder", "vae"):
            shard(self.official / part / "0.safetensors", {"x": ([1], "BF16")})
            index(self.official / part, {"x": "0.safetensors"})
        (self.official / "tokenizer").mkdir()
        for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
            (self.official / "tokenizer" / name).write_text(name)
        (self.official / "student.safetensors").write_bytes(b"student")
        self.assets = self.tmp / "assets"
        for part in ("transformer", "text_encoder", "vae"):
            (self.assets / "configs" / part).mkdir(parents=True)
            (self.assets / "configs" / part / "config.json").write_text("{}")
        (self.assets / "destripe.safetensors").write_bytes(b"destripe")
        self.store = ModelStore(self.tmp / "state", self.assets, lock={})
        files = [*(str(p.relative_to(self.official)) for p in self.official.rglob("*") if p.is_file()
                   and p.name != "student.safetensors")]
        stamp = lambda name: {**model_store._stamp(self.official / name), "sha256": "a" * 64}
        directory = self.store._directory(DEFAULT_MODEL_ID)
        directory.mkdir(parents=True)
        model_store.create_view(self.official, self.assets / "configs", directory / "view", files)
        self.store._write_binding(DEFAULT_MODEL_ID, {
            "schema_version": 1, "model_id": DEFAULT_MODEL_ID, "source_path": str(self.official.resolve()),
            "fingerprint": "official", "bridge": model_store.BRIDGE_VERSION, "bound_at": 1,
            "files": {name: stamp(name) for name in files},
            "student_path": str(self.official / "student.safetensors"),
            "student": model_store._stamp(self.official / "student.safetensors"),
            "destripe_path": str(self.assets / "destripe.safetensors"),
            "destripe": model_store._stamp(self.assets / "destripe.safetensors"),
            "configs": {part: model_store._stamp(directory / "view" / part / "config.json")
                        for part in model_store.PARTS}})

    @staticmethod
    def write_transformer(root, name, tensors):
        shard(root / "transformer" / name, tensors)
        index(root / "transformer", {key: name for key in tensors})

    def fine_tune(self, tensors=None):
        tensors = tensors or {"final.weight": ([2], "BF16"), "time_embedding.1.weight": ([2], "BF16")}
        self.write_transformer(self.variant, "model-00001-of-00001.safetensors", tensors)
        return self.variant

    def test_bound_variant_reuses_official_parts_and_keeps_its_own_identity(self):
        public = self.store.bind_variant(self.fine_tune(), "fine_tune-mlx", "Fine Tune")
        self.assertTrue(public["ready"], public)
        self.assertEqual((public["model_id"], public["label"]), ("fine_tune-mlx", "Fine Tune"))
        resolved = self.store.resolve("fine_tune-mlx")
        self.assertNotEqual(resolved.fingerprint, "official")
        link = resolved.view_path / "transformer" / "model-00001-of-00001.safetensors"
        self.assertEqual(link.resolve(), (self.variant / "transformer" / link.name).resolve())
        self.assertEqual((resolved.view_path / "vae" / "0.safetensors").resolve(),
                         (self.official / "vae" / "0.safetensors").resolve())
        self.assertEqual(resolved.student_path, self.official / "student.safetensors")
        self.assertEqual([item["model_id"] for item in self.store.list()], [DEFAULT_MODEL_ID, "fine_tune-mlx"])

    def test_changing_either_side_invalidates_the_variant(self):
        self.store.bind_variant(self.fine_tune(), "fine_tune-mlx", "Fine Tune")
        (self.official / "vae" / "0.safetensors").write_bytes(b"changed")
        self.assertFalse(self.store.public("fine_tune-mlx")["ready"])

    def test_rejects_shape_precision_or_key_differences(self):
        for tensors in ({"final.weight": ([3], "BF16"), "time_embedding.1.weight": ([2], "BF16")},
                        {"final.weight": ([2], "F16"), "time_embedding.1.weight": ([2], "BF16")},
                        {"other.weight": ([2], "BF16"), "time_embedding.1.weight": ([2], "BF16")}):
            with self.subTest(tensors=tensors), self.assertRaises(ValueError):
                self.store.bind_variant(self.fine_tune(tensors), "x", "x")

    def test_needs_a_healthy_official_binding(self):
        (self.official / "vae" / "0.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "官方"):
            self.store.bind_variant(self.fine_tune(), "x", "x")


if __name__ == "__main__":
    unittest.main()
