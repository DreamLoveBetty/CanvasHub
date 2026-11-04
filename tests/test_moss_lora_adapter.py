import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from backend.moss import lora_adapter
from backend.moss.lora_store import LoRAStore

SHA = "a" * 64


def blob(rows, cols, seed, width=2):
    size = rows * cols * width
    return bytes((seed + i) % 251 for i in range(size))


def alpha_bytes(value, dtype="F32"):
    if dtype == "F32":
        return struct.pack("<f", value)
    if dtype == "F16":
        return struct.pack("<e", value)
    return struct.pack("<f", value)[2:]


def write_safetensors(path, tensors, metadata=None):
    header, parts, offset = {}, [], 0
    if metadata:
        header["__metadata__"] = metadata
    for key, (dtype, shape, data) in tensors.items():
        header[key] = {"dtype": dtype, "shape": list(shape), "data_offsets": [offset, offset + len(data)]}
        parts.append(data)
        offset += len(data)
    encoded = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + b"".join(parts))
    return path


def read_tensors(path):
    raw = Path(path).read_bytes()
    size = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8:8 + size])
    payload = raw[8 + size:]
    return {key: (value["dtype"], tuple(value["shape"]), payload[slice(*value["data_offsets"])])
            for key, value in header.items() if key != "__metadata__"}, header.get("__metadata__", {})


def peft_pair(layer, module, out, rank=16, width=3072, dtype="BF16", seed=1, prefix="diffusion_model."):
    name = f"{prefix}layers.{layer}.proj.{module}"
    return {f"{name}.lora_A.weight": (dtype, (rank, width), blob(rank, width, seed)),
            f"{name}.lora_B.weight": (dtype, (out, rank), blob(out, rank, seed + 3))}


def kohya_pair(layer, module, out, rank=16, width=3072, dtype="BF16", seed=1, alpha=8.0):
    name = f"lora_unet_layers_{layer}_proj_{module}"
    result = {f"{name}.lora_down.weight": (dtype, (rank, width), blob(rank, width, seed)),
              f"{name}.lora_up.weight": (dtype, (out, rank), blob(out, rank, seed + 3))}
    if alpha is not None:
        result[f"{name}.alpha"] = ("F32", (), alpha_bytes(alpha))
    return result


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"

    def write(self, tensors, name="source.safetensors"):
        return write_safetensors(self.root / name, tensors)

    def rejects(self, tensors, message):
        path = self.write(tensors)
        with self.assertRaisesRegex(ValueError, message):
            lora_adapter.prepare(path, SHA, self.cache)


class FourFormats(Base):
    def test_peft_fused_qkv_splits_up_by_rows_and_shares_down(self):
        tensors = peft_pair(0, "qkv", 9216)
        down = tensors["diffusion_model.layers.0.proj.qkv.lora_A.weight"][2]
        up = tensors["diffusion_model.layers.0.proj.qkv.lora_B.weight"][2]
        output, _ = read_tensors(lora_adapter.prepare(self.write(tensors), SHA, self.cache))
        self.assertEqual(len(output), 6)
        third = len(up) // 3
        for index, module in enumerate("qkv"):
            name = f"diffusion_model.layers.0.proj.{module}"
            self.assertEqual(output[f"{name}.lora_down.weight"], ("BF16", (16, 3072), down))
            self.assertEqual(output[f"{name}.lora_up.weight"],
                             ("BF16", (3072, 16), up[index * third:(index + 1) * third]))

    def test_peft_split_only_renames(self):
        tensors = {**peft_pair(3, "q", 3072), **peft_pair(3, "k", 3072, seed=9), **peft_pair(3, "v", 3072, seed=20)}
        output, _ = read_tensors(lora_adapter.prepare(self.write(tensors), SHA, self.cache))
        self.assertEqual(output["diffusion_model.layers.3.proj.k.lora_up.weight"][2],
                         tensors["diffusion_model.layers.3.proj.k.lora_B.weight"][2])
        self.assertEqual(len(output), 6)

    def test_kohya_fused_copies_alpha_three_times(self):
        tensors = kohya_pair(1, "qkv", 9216)
        output, _ = read_tensors(lora_adapter.prepare(self.write(tensors), SHA, self.cache))
        for module in "qkv":
            self.assertEqual(output[f"diffusion_model.layers.1.proj.{module}.alpha"], ("F32", (), alpha_bytes(8.0)))

    def test_kohya_split_restores_module_names_with_underscores(self):
        tensors = {**kohya_pair(41, "ffn_up_gate", 16384), **kohya_pair(41, "ffn_down", 3072, width=8192, seed=5)}
        output, _ = read_tensors(lora_adapter.prepare(self.write(tensors), SHA, self.cache))
        self.assertIn("diffusion_model.layers.41.proj.ffn_up_gate.lora_up.weight", output)
        self.assertIn("diffusion_model.layers.41.proj.ffn_down.alpha", output)

    def test_every_accepted_wrapper_prefix(self):
        for prefix in ("diffusion_model.", "model.diffusion_model.", "transformer.", "base_model.model.",
                       "base_model.model.diffusion_model."):
            with self.subTest(prefix=prefix):
                path = self.write(peft_pair(0, "o", 3072, prefix=prefix), name="wrapped.safetensors")
                output, _ = read_tensors(lora_adapter.prepare(path, hashlib.sha256(prefix.encode()).hexdigest(), self.cache))
                self.assertIn("diffusion_model.layers.0.proj.o.lora_down.weight", output)

    def test_peft_default_adapter_suffix(self):
        tensors = {"transformer.layers.0.proj.o.lora_A.default.weight": ("BF16", (4, 3072), blob(4, 3072, 1)),
                   "transformer.layers.0.proj.o.lora_B.default.weight": ("BF16", (3072, 4), blob(3072, 4, 2))}
        output, _ = read_tensors(lora_adapter.prepare(self.write(tensors), SHA, self.cache))
        self.assertIn("diffusion_model.layers.0.proj.o.lora_up.weight", output)

    def test_ranks_missing_alpha_and_partial_coverage_pass(self):
        for rank in (16, 128):
            tensors = {}
            for layer in range(42):
                if layer != 22:
                    tensors.update(kohya_pair(layer, "o", 3072, rank=rank, alpha=None, seed=layer))
            path = self.write(tensors, name=f"rank{rank}.safetensors")
            output, _ = read_tensors(lora_adapter.prepare(path, hashlib.sha256(bytes([rank])).hexdigest(), self.cache))
            self.assertEqual(len(output), 82)
            self.assertFalse([key for key in output if key.endswith(".alpha")])

    def test_dtypes_stay_byte_identical(self):
        tensors = {**peft_pair(0, "o", 3072, dtype="F16"), **kohya_pair(1, "o", 3072, seed=4)}
        tensors["diffusion_model.layers.2.proj.o.lora_down.weight"] = ("F32", (2, 3072), blob(2, 3072, 3, 4))
        tensors["diffusion_model.layers.2.proj.o.lora_up.weight"] = ("F32", (3072, 2), blob(3072, 2, 4, 4))
        output, _ = read_tensors(lora_adapter.prepare(self.write(tensors), SHA, self.cache))
        self.assertEqual(output["diffusion_model.layers.0.proj.o.lora_down.weight"][0], "F16")
        self.assertEqual(output["diffusion_model.layers.2.proj.o.lora_up.weight"],
                         ("F32", (3072, 2), blob(3072, 2, 4, 4)))

    def test_output_drops_third_party_metadata_and_records_provenance(self):
        path = write_safetensors(self.root / "meta.safetensors", peft_pair(0, "o", 3072),
                                 {"ss_tag_frequency": "private"})
        _, metadata = read_tensors(lora_adapter.prepare(path, SHA, self.cache))
        self.assertEqual(metadata, {"format": "pt", "canvashub_moss_converter": lora_adapter.CONVERTER_VERSION,
                                    "canvashub_moss_source_sha256": SHA})


class Rejections(Base):
    def test_unknown_or_unsupported_tensors(self):
        base = peft_pair(0, "o", 3072)
        tiny = ("F16", (1,), b"\0\0")
        for key in ("diffusion_model.layers.42.proj.o.lora_A.weight",
                    "diffusion_model.layers.00.proj.o.lora_A.weight",
                    "diffusion_model.layers.0.proj.w.lora_A.weight",
                    "diffusion_model.layers.0.proj.o.lokr_w1",
                    "diffusion_model.layers.0.proj.o.hada_w1_a",
                    "diffusion_model.layers.0.proj.o.dora_scale",
                    "diffusion_model.layers.0.proj.o.diff",
                    "lora_te_text_model_layers_0.lora_down.weight",
                    "text_encoder.layers.0.proj.o.lora_A.weight",
                    "diffusion_model.time_mlp.0.lora_A.weight"):
            with self.subTest(key=key):
                self.rejects({**base, key: tiny}, "不支持的张量")

    def test_flat_names_never_match_dotted_form(self):
        self.rejects({"lora_unet_layers.0.proj.o.lora_down.weight": ("F16", (1,), b"\0\0")}, "不支持的张量")

    def test_fused_and_split_on_the_same_layer(self):
        self.rejects({**peft_pair(0, "qkv", 9216), **peft_pair(0, "q", 3072, seed=9)}, "同时包含")

    def test_duplicate_spelling_of_one_target(self):
        self.rejects({**peft_pair(0, "o", 3072), **kohya_pair(0, "o", 3072, seed=6, alpha=None)}, "重复目标层")

    def test_invalid_alpha(self):
        for value, dtype in ((0.0, "F32"), (-1.0, "F32"), (float("inf"), "F32"), (float("nan"), "F16"),
                             (0.0, "BF16")):
            with self.subTest(value=value):
                tensors = kohya_pair(0, "o", 3072, alpha=None)
                tensors["lora_unet_layers_0_proj_o.alpha"] = (dtype, (), alpha_bytes(value, dtype))
                self.rejects(tensors, "有限正数")

    def test_alpha_must_be_scalar_and_paired(self):
        tensors = kohya_pair(0, "o", 3072, alpha=None)
        tensors["lora_unet_layers_0_proj_o.alpha"] = ("F32", (2,), alpha_bytes(1.0) * 2)
        self.rejects(tensors, "标量")
        self.rejects({"lora_unet_layers_0_proj_o.alpha": ("F32", (), alpha_bytes(1.0))}, "缺少 A/B")

    def test_rank_and_shape_mismatch(self):
        tensors = peft_pair(0, "o", 3072)
        tensors["diffusion_model.layers.0.proj.o.lora_B.weight"] = ("BF16", (3072, 8), blob(3072, 8, 1))
        self.rejects(tensors, "秩不一致")
        self.rejects(peft_pair(0, "o", 2048), "不匹配")
        self.rejects(peft_pair(0, "ffn_down", 3072), "不匹配")

    def test_dtype_and_declared_size(self):
        self.rejects(peft_pair(0, "o", 3072, dtype="F64"), "FP32")
        tensors = peft_pair(0, "o", 3072)
        tensors["diffusion_model.layers.0.proj.o.lora_A.weight"] = ("BF16", (16, 3072), b"\0\0")
        self.rejects(tensors, "大小")


class Cache(Base):
    def test_canonical_file_is_used_without_a_copy(self):
        tensors = {}
        tensors["diffusion_model.layers.0.proj.o.lora_down.weight"] = ("F32", (4, 3072), blob(4, 3072, 1, 4))
        tensors["diffusion_model.layers.0.proj.o.lora_up.weight"] = ("F32", (3072, 4), blob(3072, 4, 2, 4))
        path = self.write(tensors)
        self.assertEqual(lora_adapter.prepare(path, SHA, self.cache), path)
        self.assertFalse(self.cache.exists())

    def test_hit_skips_rewrite_and_source_is_untouched(self):
        path = self.write(peft_pair(0, "qkv", 9216))
        before = path.read_bytes()
        first = lora_adapter.prepare(path, SHA, self.cache)
        stamp = first.stat().st_mtime_ns
        with patch.object(lora_adapter, "_write", side_effect=AssertionError("rewritten")):
            self.assertEqual(lora_adapter.prepare(path, SHA, self.cache), first)
        self.assertEqual(first.stat().st_mtime_ns, stamp)
        self.assertEqual(path.read_bytes(), before)

    def test_truncated_or_foreign_cache_is_rebuilt(self):
        path = self.write(peft_pair(0, "o", 3072))
        first = lora_adapter.prepare(path, SHA, self.cache)
        good = first.read_bytes()
        first.write_bytes(good[:100])
        self.assertEqual(lora_adapter.prepare(path, SHA, self.cache).read_bytes(), good)
        first.write_bytes(b"x" * len(good))
        self.assertEqual(lora_adapter.prepare(path, SHA, self.cache).read_bytes(), good)

    def test_converter_version_change_rebuilds(self):
        path = self.write(peft_pair(0, "o", 3072))
        first = lora_adapter.prepare(path, SHA, self.cache)
        with patch.object(lora_adapter, "CONVERTER_VERSION", "moss-lora-keys-v2"):
            second = lora_adapter.prepare(path, SHA, self.cache)
        self.assertNotEqual(first, second)
        self.assertTrue(second.is_file())

    def test_failed_write_leaves_no_partial_cache(self):
        path = self.write(peft_pair(0, "o", 3072))
        with patch.object(lora_adapter.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                lora_adapter.prepare(path, SHA, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_invalid_asset_id_never_reaches_the_filesystem(self):
        with self.assertRaises(ValueError):
            lora_adapter.prepare(self.write(peft_pair(0, "o", 3072)), "../../evil", self.cache)


class Store(Base):
    def setUp(self):
        super().setUp()
        self.store = LoRAStore(self.root / "state", managed=())

    def upload(self, store, tensors, name="file.safetensors"):
        path = write_safetensors(self.root / name, tensors)
        return store.import_stream(io.BytesIO(path.read_bytes()), path.stat().st_size, name)

    def test_import_resolve_snapshot_delete_clears_cache(self):
        result = self.upload(self.store, peft_pair(0, "qkv", 9216))
        path, public = self.store.resolve(result["asset_id"])
        self.assertEqual(public["adapter_count"], 1)
        self.assertEqual(public["tensor_count"], 6)
        self.assertNotIn("_path", public)
        self.assertEqual(self.store.library_snapshot()["loras"][0]["asset_id"], result["asset_id"])
        cached = lora_adapter.prepare(path, result["asset_id"], self.store.cache_dir)
        self.assertTrue(cached.is_file())
        self.store.delete(result["asset_id"])
        self.assertFalse(cached.exists())
        self.assertEqual(self.store.list(), [])

    def test_cache_defaults_under_the_moss_state_root(self):
        self.assertEqual(self.store.cache_dir, self.root / "state" / "cache" / "lora")

    def test_unsupported_import_is_rejected_and_not_kept(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            self.upload(self.store, {"unet.down.lora_down.weight": ("F16", (1, 1), b"\0\0"),
                                     "unet.down.lora_up.weight": ("F16", (1, 1), b"\0\0")})
        self.assertEqual(self.store.list(), [])

    def test_managed_adapter_hash_is_excluded(self):
        tensors = peft_pair(0, "o", 3072)
        path = write_safetensors(self.root / "managed.safetensors", tensors)
        store = LoRAStore(self.root / "state2", managed={hashlib.sha256(path.read_bytes()).hexdigest()})
        with self.assertRaisesRegex(ValueError, "受管"):
            store.import_stream(io.BytesIO(path.read_bytes()), path.stat().st_size, "managed.safetensors")

    def test_managed_file_copied_into_the_folder_is_a_scan_error(self):
        tensors = peft_pair(0, "o", 3072)
        path = write_safetensors(self.root / "student.safetensors", tensors)
        store = LoRAStore(self.root / "state3", managed={hashlib.sha256(path.read_bytes()).hexdigest()})
        store.directory.mkdir(parents=True)
        (store.directory / "student.safetensors").write_bytes(path.read_bytes())
        self.assertEqual(store.list(), [])
        self.assertIn("受管", store.scan_errors()[0]["error"])

    def test_default_managed_set_comes_from_the_asset_lock(self):
        store = LoRAStore(self.root / "state4")
        self.assertIn("1859687695670d32cd3a2194c7bd931956d260e222d389fba8564f878e7f5a8d", store.managed)
        self.assertIn("fcd0d025f6a62dfe3171ab11fe9b3119eac735e22b94913c4efe45d8c69c2da9", store.managed)


if __name__ == "__main__":
    unittest.main()
