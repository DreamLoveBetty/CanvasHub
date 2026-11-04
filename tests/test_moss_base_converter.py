"""Community Base conversion: ConvRot math, QKV split, BF16 passthrough, library rules. Tiny synthetic tensors only."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import numpy as np

from backend.moss import base_converter as converter
from backend.moss.base_library import BaseLibrary, model_id_for
from backend.moss.contracts import DEFAULT_MODEL_ID


def write(path, tensors, metadata=None):
    header, body = {}, bytearray()
    if metadata is not None:
        header["__metadata__"] = metadata
    for name, dtype, value in tensors:
        raw = value.tobytes()
        header[name] = {"dtype": dtype, "shape": list(value.shape), "data_offsets": [len(body), len(body) + len(raw)]}
        body.extend(raw)
    encoded = json.dumps(header, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + body)


def independent_h256():
    """Base-4 sign formula, independent of the converter's Kronecker construction."""
    result = np.ones((256, 256), dtype=np.float64)
    for i in range(256):
        for j in range(256):
            a, b, sign = i, j, 1
            for _ in range(4):
                if (a % 4) + (b % 4) == 3:
                    sign = -sign
                a //= 4
                b //= 4
            result[i, j] = sign / 16
    return result


CONFIG = {"format": "int8_tensorwise", "convrot": True, "convrot_groupsize": 256}


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.reference = self.tmp / "official" / "transformer"
        bf = lambda shape: np.zeros(shape, dtype="<u2")
        write(self.reference / "0.safetensors", [
            ("layers.0.proj.q.weight", "BF16", bf((2, 256))), ("layers.0.proj.k.weight", "BF16", bf((2, 256))),
            ("layers.0.proj.v.weight", "BF16", bf((2, 256))), ("time_embedding.2.weight", "BF16", bf((1, 2)))])
        self.q = np.zeros((6, 256), dtype=np.int8)
        self.q[0, 0], self.q[3, 3] = 16, -32
        self.scales = np.full((6, 1), .5, dtype="<f4")
        self.source = self.tmp / "imports" / "tune.safetensors"
        p = converter.PREFIX
        marker = np.frombuffer(json.dumps(CONFIG).encode(), dtype=np.uint8)
        write(self.source, [(p + "layers.0.proj.qkv.weight", "I8", self.q), (p + "layers.0.proj.qkv.weight_scale", "F32", self.scales),
                            ("layers.0.proj.qkv.comfy_quant", "U8", marker),
                            (p + "time_embedding.2.weight", "BF16", np.array([[7, 9]], dtype="<u2"))],
              {"_quantization_metadata": json.dumps({"format_version": "1.0", "layers": {"layers.0.proj.qkv": CONFIG}})})


class Converter(Fixture):
    def test_hadamard_matches_independent_formula_and_restores_rows(self):
        np.testing.assert_allclose(converter.regular_hadamard(256), independent_h256(), atol=1e-6)
        restored = converter.restore_convrot(self.q, self.scales, 256)
        np.testing.assert_allclose(restored, (self.q.astype(np.float64) * .5) @ independent_h256().T, atol=1e-5)

    def test_converted_output_splits_qkv_and_keeps_bf16_bytes(self):
        output = self.tmp / "stage"
        result = converter.convert_file(self.source, self.reference, output)
        self.assertEqual(result["source_format"], "comfy-int8-convrot")
        index = json.loads((output / "transformer" / "model.safetensors.index.json").read_text())["weight_map"]
        self.assertEqual(sorted(index), ["layers.0.proj.k.weight", "layers.0.proj.q.weight", "layers.0.proj.v.weight",
                                         "time_embedding.1.weight"])
        reader = converter.SafeTensorReader(output / "transformer" / index["time_embedding.1.weight"])
        self.assertEqual(np.frombuffer(reader.raw("time_embedding.1.weight"), dtype="<u2").tolist(), [7, 9])
        k = np.frombuffer(reader.raw("layers.0.proj.k.weight"), dtype="<u2").reshape(2, 256)
        expected = converter.float32_to_bf16(converter.restore_convrot(self.q, self.scales, 256)[2:4])
        np.testing.assert_array_equal(k, expected)

    def test_rejects_mismatched_architecture(self):
        write(self.reference / "1.safetensors", [("extra.weight", "BF16", np.zeros((1, 2), dtype="<u2"))])
        with self.assertRaises(ValueError):
            converter.prepare(self.source, self.reference)


class Library(Fixture):
    def library(self):
        models = mock.Mock()
        models.healthy_binding.return_value = {"source_path": str(self.reference.parent)}
        library = BaseLibrary(self.tmp / "state", models)
        library.paths()
        return library, models

    def test_import_list_only_shows_usable_sources(self):
        library, _ = self.library()
        library.import_directory.joinpath("tune.safetensors").write_bytes(self.source.read_bytes())
        library.import_directory.joinpath("note.txt").write_text("x")
        library.import_directory.joinpath(".hidden.safetensors").write_text("x")
        self.assertEqual([item["source_name"] for item in library.list_imports()], ["tune.safetensors"])

    def test_inspect_reports_format_and_rejects_foreign_files_without_leaving_import_folder(self):
        library, _ = self.library()
        library.import_directory.joinpath("tune.safetensors").write_bytes(self.source.read_bytes())
        write(library.import_directory / "other.safetensors", [("x", "BF16", np.zeros((1, 2), dtype="<u2"))])
        self.assertEqual(library.inspect("tune.safetensors")["source_format"], "comfy-int8-convrot")
        self.assertFalse(library.inspect("other.safetensors")["compatible_candidate"])
        with self.assertRaises(ValueError):
            library.inspect("../tune.safetensors")

    def test_needs_official_binding(self):
        library, models = self.library()
        models.healthy_binding.return_value = None
        library.import_directory.joinpath("tune.safetensors").write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, "官方"):
            library.inspect("tune.safetensors")

    def test_publish_moves_into_library_and_a_failed_bind_leaves_nothing(self):
        library, models = self.library()
        stage = library.staging / "job"
        stage.mkdir()
        models.bind_variant.side_effect = ValueError("bad")
        with self.assertRaises(ValueError):
            library.publish(stage, "My Tune")
        self.assertFalse((library.directory / "my-tune").exists())
        stage.mkdir()
        models.bind_variant.side_effect = None
        library.publish(stage, "My Tune")
        models.bind_variant.assert_called_with(library.directory / "my-tune", "my-tune", "My Tune")
        self.assertTrue((library.directory / "my-tune").is_dir())

    def test_official_base_cannot_be_deleted_and_chinese_names_get_a_stable_id(self):
        library, _ = self.library()
        with self.assertRaises(ValueError):
            library.delete(DEFAULT_MODEL_ID)
        self.assertRegex(model_id_for("写实微调"), r"^moss-[a-f0-9]{12}$")


if __name__ == "__main__":
    unittest.main()
