"""Offline Krea 2 domain regression tests; no model download or MLX import."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from PIL import Image

from backend.krea2.contracts import (BASE_REPO, BUILTIN_MODEL_IDS, DEFAULT_MODEL_ID,
                                     SAFETY_REPO, TASK_TYPE, normalize_job)
from backend.krea2.install import prepare_models
from backend.krea2.lora_store import LoRAStore
from backend.krea2.model_store import BaseModelStore
from backend.krea2.service import Service
from backend.krea2.converter_worker import save_safetensors_atomic, select_weights
from backend.krea2.comfy_fp8 import (SOURCE_FORMAT, load_comfy_scaled_fp8,
                                     read_safetensors_header)
from backend.krea2.edit_profile import reference_geometry
from backend.krea2.worker import Engine


def synthetic_lora():
    header = json.dumps({
        "transformer.blocks.0.attn.to_q.lora_A.weight": {
            "dtype": "F16", "shape": [1, 1], "data_offsets": [0, 2]},
        "transformer.blocks.0.attn.to_q.lora_B.weight": {
            "dtype": "F16", "shape": [1, 1], "data_offsets": [2, 4]},
    }, separators=(",", ":")).encode()
    return len(header).to_bytes(8, "little") + header + b"\0\0\0\0"


def synthetic_checkpoint(*, quantized=False, dtype="F16"):
    header = {}
    payload = bytearray()
    for index in range(105):
        key = f"blocks.0.attn.layer_{index}.weight"
        start = len(payload)
        payload.extend(b"\0\0")
        header[key] = {"dtype": dtype, "shape": [1], "data_offsets": [start, len(payload)]}
    if quantized:
        header["blocks.0.attn.layer_0.scales"] = {
            "dtype": "F16", "shape": [1], "data_offsets": [0, 2]}
    encoded = json.dumps(header, separators=(",", ":")).encode()
    return len(encoded).to_bytes(8, "little") + encoded + payload


def synthetic_comfy_fp8_checkpoint(*, pair_count=105, omit_last_scale=False):
    header = {}
    payload = bytearray()

    def add(key, dtype, shape, data):
        start = len(payload)
        payload.extend(data)
        header[key] = {"dtype": dtype, "shape": shape,
                       "data_offsets": [start, len(payload)]}

    marker = json.dumps({"format": "float8_e4m3fn"}, separators=(",", ":")).encode()
    for index in range(pair_count):
        base = f"blocks.0.attn.layer_{index}"
        add(base + ".weight", "F8_E4M3", [1], b"\0")
        if not (omit_last_scale and index == pair_count - 1):
            add(base + ".weight_scale", "F32", [], struct.pack("<f", 0.25))
        add(base + ".comfy_quant", "U8", [len(marker)], marker)
    encoded = json.dumps(header, separators=(",", ":")).encode()
    return len(encoded).to_bytes(8, "little") + encoded + payload


class FakeRuntime:
    def __init__(self, safety_ready=False):
        self.closed = False
        self.safety_ready = safety_ready
        self.last_spec = None

    def status(self):
        return {"revision": "test-revision", "environment_ready": True, "source_ready": True,
                "base_ready": True, "safety_ready": self.safety_ready,
                "builds": {"8bit": {"ready": True}, "mixed-4-8": {"ready": False}},
                "ready": True, "warm": False, "reasons": []}

    def execute(self, spec, directory, cancelled, progress):
        self.last_spec = spec
        progress(.5, "synthetic inference")
        output = Path(directory) / "generated"
        output.mkdir()
        paths = []
        for index in range(spec["image_count"]):
            path = output / f"result_{index + 1}.png"
            Image.new("RGB", (32, 32), (20, 40, 60)).save(path)
            paths.append(path)
        enabled = spec["safety_enabled"] is True
        return {"paths": paths, "flagged": 0, "precision": spec["precision"],
                "base_model_id": spec["base_model_id"],
                "base_model_name": spec["base_model_name"],
                "seed": spec["seed"], "safety_enabled": enabled,
                "safety_threshold": .85 if enabled else None,
                "generation_timing": {
                    "schema_version": 1, "local_inference": True,
                    "model_load_seconds": 1.25, "inference_seconds": 2.5,
                    "denoise_seconds": 3.75, "save_seconds": .5,
                    "total_seconds": 8.0,
                }}

    def close(self):
        self.closed = True


class FakeModelStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"synthetic")

    def resolve(self, model_id):
        if model_id != DEFAULT_MODEL_ID:
            raise ValueError("Base 权重模型不存在")
        return {"id": DEFAULT_MODEL_ID, "name": "Krea 2 Turbo · Alis MLX",
                "label": "Krea 2 Turbo · Alis MLX（8-bit）", "precision": "8bit",
                "path": self.path, "ready": True, "builtin": True}

    def list(self, build_status=None):
        return [{key: value for key, value in self.resolve(DEFAULT_MODEL_ID).items()
                 if key != "path"}]


class Krea2Tests(unittest.TestCase):
    def test_contract_normalizes_multi_lora_and_dimensions(self):
        first, second = "a" * 64, "b" * 64
        spec = normalize_job({"prompt": "local image", "width": 768, "height": 1024,
                              "steps": 9, "seed": "42", "image_count": 2,
                              "loras": [{"asset_id": first, "scale": .7},
                                        {"asset_id": second, "scale": 1.25}]})
        self.assertEqual(spec["seed"], 42)
        self.assertEqual(spec["aspect_ratio"], "3:4")
        self.assertEqual([item["scale"] for item in spec["loras"]], [.7, 1.25])
        self.assertFalse(spec["safety_enabled"])
        self.assertEqual(spec["base_model_id"], DEFAULT_MODEL_ID)
        custom = normalize_job({"prompt": "custom", "base_model_id": "portrait-v2"})
        self.assertEqual(custom["base_model_id"], "portrait-v2")
        self.assertTrue(normalize_job({"prompt": "checked", "safety_enabled": True})["safety_enabled"])
        wide = normalize_job({"prompt": "wide", "aspect_ratio": "16:9",
                              "width": 1280, "height": 720})
        self.assertEqual((wide["aspect_ratio"], wide["width"], wide["height"]),
                         ("16:9", 1280, 720))
        with self.assertRaisesRegex(ValueError, "未知画幅比例"):
            normalize_job({"prompt": "bad", "aspect_ratio": "3:5"})
        with self.assertRaisesRegex(ValueError, "16 的倍数"):
            normalize_job({"prompt": "bad", "width": 769})
        with self.assertRaisesRegex(ValueError, "不能重复"):
            normalize_job({"prompt": "bad", "loras": [
                {"asset_id": first, "scale": 1}, {"asset_id": first, "scale": 1}]})

    def test_contract_normalizes_instruction_edit_and_reserves_adapter_slot(self):
        adapter, style = "c" * 64, "d" * 64
        spec = normalize_job({
            "prompt": "turn the coat red", "mode": "edit",
            "edit_image_upload_token": "source-token",
            "edit_adapter_asset_id": adapter,
            "edit_adapter_scale": .9, "reference_strength": 5.5,
            "grounding_px": 1024, "fit_mode": "fit",
            "loras": [{"asset_id": style, "scale": .7}],
        })
        self.assertEqual(spec["mode"], "edit")
        self.assertEqual(spec["edit_adapter_asset_id"], adapter)
        self.assertEqual(spec["edit_adapter_scale"], .9)
        self.assertEqual(spec["reference_strength"], 5.5)
        self.assertEqual(spec["grounding_px"], 1024)
        self.assertEqual(spec["fit_mode"], "fit")
        with self.assertRaisesRegex(ValueError, "必须连接 1 张源图"):
            normalize_job({"prompt": "edit", "mode": "edit",
                           "edit_adapter_asset_id": adapter})
        with self.assertRaisesRegex(ValueError, "传统重绘"):
            normalize_job({"prompt": "edit", "mode": "edit",
                           "edit_image_upload_token": "source",
                           "init_image_upload_token": "legacy",
                           "edit_adapter_asset_id": adapter})
        with self.assertRaisesRegex(ValueError, "最多加载 3 个普通 LoRA"):
            normalize_job({"prompt": "edit", "mode": "edit",
                           "edit_image_upload_token": "source",
                           "edit_adapter_asset_id": adapter,
                           "loras": [{"asset_id": str(index) * 64, "scale": 1}
                                     for index in range(4)]})
        with self.assertRaisesRegex(ValueError, "只能用于指令编辑"):
            normalize_job({"prompt": "bad", "edit_image_upload_token": "source"})

    def test_instruction_edit_reference_geometry_matches_v12_fit_policy(self):
        wide = reference_geometry(1920, 1080, 1024, 1024, "fit")
        self.assertEqual((wide.output_width, wide.output_height), (1024, 576))
        self.assertEqual((wide.token_width, wide.token_height), (64, 36))
        self.assertEqual((wide.offset_x, wide.offset_y), (0, 14))
        near = reference_geometry(1000, 950, 1024, 1024, "fit")
        self.assertEqual((near.output_width, near.output_height), (1024, 1024))
        self.assertEqual((near.offset_x, near.offset_y), (0, 0))
        legacy = reference_geometry(1920, 1080, 1024, 1024, "crop")
        self.assertEqual((legacy.output_width, legacy.output_height), (1024, 1024))
        self.assertLess(legacy.crop_width, 1920)
        with self.assertRaisesRegex(ValueError, "16 的倍数"):
            reference_geometry(640, 480, 769, 1024, "fit")

    def test_lora_store_streams_content_addressed_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LoRAStore(temp)
            content = synthetic_lora()
            item = store.import_stream(io.BytesIO(content), len(content), "style.safetensors")
            self.assertEqual(item["asset_id"], hashlib.sha256(content).hexdigest())
            self.assertEqual(item["adapter_count"], 1)
            path, resolved = store.resolve(item["asset_id"])
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(resolved["name"], "style")
            duplicate = store.import_stream(io.BytesIO(content), len(content), "renamed.safetensors")
            self.assertEqual(duplicate["asset_id"], item["asset_id"])
            self.assertEqual(len(store.list()), 1)
            store.delete(item["asset_id"])
            self.assertFalse(path.exists())

    def test_lora_store_discovers_safetensors_copied_into_library(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LoRAStore(temp)
            store.directory.mkdir(parents=True)
            content = synthetic_lora()
            source = store.directory / "cinematic-light.safetensors"
            source.write_bytes(content)

            items = store.list()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["asset_id"], hashlib.sha256(content).hexdigest())
            self.assertEqual(items[0]["name"], "cinematic-light")
            self.assertNotIn("_file", items[0])
            path, metadata = store.resolve(items[0]["asset_id"])
            self.assertEqual(path, source.resolve())
            self.assertEqual(metadata["adapter_count"], 1)

            # A broken file must not hide the valid library from the dropdown.
            (store.directory / "broken.safetensors").write_bytes(b"not-a-lora")
            self.assertEqual([item["name"] for item in store.list()], ["cinematic-light"])
            self.assertEqual(store.scan_errors()[0]["name"], "broken.safetensors")

    def test_lora_store_rejects_unpaired_or_out_of_range_tensors(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LoRAStore(temp)
            for header, message in [
                ({"layer.lora_A.weight": {"dtype": "F16", "shape": [1, 1],
                                           "data_offsets": [0, 2]}}, "A/B 张量不完整"),
                ({"layer.lora_A.weight": {"dtype": "F16", "shape": [1, 1], "data_offsets": [0, 2]},
                  "layer.lora_B.weight": {"dtype": "F16", "shape": [1, 1], "data_offsets": [2, 99]}},
                 "张量范围无效"),
            ]:
                encoded = json.dumps(header, separators=(",", ":")).encode()
                content = len(encoded).to_bytes(8, "little") + encoded + b"\0\0\0\0"
                with self.assertRaisesRegex(ValueError, message):
                    store.import_stream(io.BytesIO(content), len(content), "bad.safetensors")

    def test_model_preparation_skips_optional_safety_download_when_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []

            def repo_files(repo, revision, patterns):
                calls.append(repo)
                return [("model_index.json", 1, "")] if repo == BASE_REPO else []

            def download(repo, revision, filename, destination, **kwargs):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"x")
                return destination

            with mock.patch("backend.krea2.install._repo_files", side_effect=repo_files), \
                    mock.patch("backend.krea2.install.download_file", side_effect=download):
                records = prepare_models(temp, ["8bit"], include_safety=False)
            self.assertEqual(calls, [BASE_REPO])
            self.assertNotIn(SAFETY_REPO, calls)
            self.assertNotIn("safety", records)
            self.assertIn("8bit", records)

    def test_custom_model_preparation_still_fetches_shared_base_without_builtin_transformer(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []

            def repo_files(repo, revision, patterns):
                calls.append(repo)
                return [("model_index.json", 1, "")]

            def download(repo, revision, filename, destination, **kwargs):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"x")
                return destination

            with mock.patch("backend.krea2.install._repo_files", side_effect=repo_files), \
                    mock.patch("backend.krea2.install.download_file", side_effect=download):
                records = prepare_models(temp, [], include_safety=False)
            self.assertEqual(calls, [BASE_REPO])
            self.assertEqual(set(records), {"base"})

    def test_base_model_store_inspects_and_publishes_verified_custom_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BaseModelStore(root / "data" / "assets", root / "component")
            source = root / "community.safetensors"
            source.write_bytes(synthetic_checkpoint())
            inspection = store.inspect_source(source)
            self.assertEqual(inspection["kind"], "candidate")
            self.assertEqual(inspection["tensor_count"], 105)
            self.assertEqual(inspection["suggested_name"], "community")
            with self.assertRaisesRegex(ValueError, "模型导入目录"):
                store.inspect_source("../../community.safetensors")
            store.paths()
            imported = store.import_directory / "Imported Portrait.safetensors"
            imported.write_bytes(synthetic_checkpoint())
            (store.import_directory / "ignore.txt").write_text("ignore")
            self.assertEqual(store.list_imports(), [{
                "source_name": imported.name,
                "file_size": imported.stat().st_size,
            }])
            self.assertEqual(store.inspect_source(imported.name)["kind"], "candidate")
            with self.assertRaisesRegex(ValueError, "当前选择的是目录"):
                store.inspect_source(store.import_directory)

            quantized = root / "quantized.safetensors"
            quantized.write_bytes(synthetic_checkpoint(quantized=True))
            self.assertEqual(store.inspect_source(quantized)["kind"], "quantized")

            unsupported = root / "unsupported.safetensors"
            unsupported.write_bytes(synthetic_checkpoint(dtype="I64"))
            unsupported_inspection = store.inspect_source(unsupported)
            self.assertEqual(unsupported_inspection["kind"], "unsupported")
            self.assertFalse(unsupported_inspection["compatible_candidate"])
            self.assertIn("I64", unsupported_inspection["message"])

            stage = store.staging / "job"
            stage.mkdir()
            transformer = stage / "transformer.safetensors"
            transformer.write_bytes(b"converted")
            item = store.publish(stage, name="Community Portrait", precision="8bit",
                                 source_name=source.name, source_sha256="a" * 64,
                                 output_sha256="b" * 64, source_prefix="transformer.",
                                 source_tensor_count=430, output_tensor_count=878,
                                 quantized_linear_count=224)
            self.assertEqual(item["name"], "Community Portrait")
            self.assertNotIn("path", item)
            resolved = store.resolve(item["id"])
            self.assertTrue(resolved["path"].is_file())
            self.assertTrue(resolved["verification"]["strict_reload"])
            self.assertEqual(resolved["source_tensor_count"], 430)
            self.assertEqual(resolved["output_tensor_count"], 878)
            self.assertEqual(resolved["quantized_linear_count"], 224)
            self.assertEqual(resolved["source_format"], "float")
            self.assertFalse(resolved["requantized"])
            self.assertIn(item["id"], [model["id"] for model in store.list()])
            store.delete(item["id"])
            with self.assertRaisesRegex(ValueError, "不存在"):
                store.resolve(item["id"])

    def test_model_store_recognizes_strict_comfy_scaled_fp8(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BaseModelStore(root / "data" / "assets", root / "component")
            source = root / "community-fp8.safetensors"
            source.write_bytes(synthetic_comfy_fp8_checkpoint())
            inspection = store.inspect_source(source)
            self.assertEqual(inspection["kind"], "comfy_scaled_fp8")
            self.assertTrue(inspection["compatible_candidate"])
            self.assertEqual(inspection["source_format"], SOURCE_FORMAT)
            self.assertEqual(inspection["source_tensor_count"], 105)
            self.assertEqual(inspection["quantized_tensor_count"], 105)
            self.assertIn("scaled-FP8", inspection["message"])

            malformed = root / "malformed-fp8.safetensors"
            malformed.write_bytes(synthetic_comfy_fp8_checkpoint(omit_last_scale=True))
            rejected = store.inspect_source(malformed)
            self.assertEqual(rejected["kind"], "unsupported")
            self.assertFalse(rejected["compatible_candidate"])
            self.assertIn("数量不一致", rejected["message"])

    def test_comfy_scaled_fp8_adapter_decodes_one_tensor_to_bf16(self):
        from contextlib import nullcontext
        import sys
        import types

        class Array:
            shape = (1,)

        class Tensor:
            def __init__(self, value, dtype="fp8"):
                self.value = float(value)
                self.dtype = dtype
                self.shape = (1,)

            def to(self, dtype):
                return Tensor(self.value, dtype)

            def __mul__(self, other):
                return Tensor(self.value * other.value, self.dtype)

            def contiguous(self):
                return self

        class DecodedArray:
            def __init__(self, tensor):
                self.value = tensor.value
                self.dtype = "bf16"
                self.shape = tensor.shape

            def tolist(self):
                return [self.value]

        class Source:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def get_tensor(self, key):
                return Tensor(0.25, "f32") if key.endswith(".weight_scale") else Tensor(2.0)

        torch = types.ModuleType("torch")
        torch.float32 = "f32"
        torch.bfloat16 = "bf16"
        torch.inference_mode = nullcontext
        safetensors = types.ModuleType("safetensors")
        safetensors.safe_open = lambda *_args, **_kwargs: Source()

        class MX:
            bfloat16 = "bf16"

            @staticmethod
            def from_dlpack(tensor, copy):
                self.assertTrue(copy)
                return DecodedArray(tensor)

            @staticmethod
            def eval(_array):
                return None

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "tiny-fp8.safetensors"
            source.write_bytes(synthetic_comfy_fp8_checkpoint(pair_count=1))
            updates = []
            with mock.patch.dict(sys.modules, {"torch": torch, "safetensors": safetensors}):
                result = load_comfy_scaled_fp8(
                    source,
                    {"blocks.0.attn.layer_0.weight": Array()},
                    MX,
                    header=read_safetensors_header(source),
                    progress=lambda done, total, key: updates.append((done, total, key)),
                )
            self.assertEqual(result["source_format"], SOURCE_FORMAT)
            self.assertEqual(result["source_quantized_tensor_count"], 1)
            self.assertEqual(result["source_tensor_count"], 1)
            self.assertEqual(result["source_prefix"], "")
            key, value = result["weights"][0]
            self.assertEqual(key, "blocks.0.attn.layer_0.weight")
            self.assertEqual(value.dtype, MX.bfloat16)
            self.assertEqual(value.tolist(), [0.5])
            self.assertEqual(updates[-1][0], updates[-1][1])

    def test_frozen_runtime_bundles_converter_fp8_and_edit_workers_side_by_side(self):
        spec = (Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller"
                / "canvashub-runtime.spec").read_text(encoding="utf-8")
        self.assertIn('"converter_worker.py"), "backend/krea2"', spec)
        self.assertIn('"comfy_fp8.py"), "backend/krea2"', spec)
        self.assertIn('"edit_mlx.py"), "backend/krea2"', spec)
        self.assertIn('"edit_profile.py"), "backend/krea2"', spec)

    def test_converter_selects_known_wrapper_prefix_and_rejects_shape_mismatch(self):
        class Array:
            def __init__(self, shape):
                self.shape = shape

        expected = {"blocks.0.attn.wq.weight": Array((8, 8)),
                    "last.linear.weight": Array((4, 8))}
        weights = {"transformer." + key: Array(value.shape) for key, value in expected.items()}
        prefix, mapped = select_weights(weights, expected)
        self.assertEqual(prefix, "transformer.")
        self.assertEqual([key for key, _ in mapped], list(expected))
        weights["transformer.last.linear.weight"] = Array((5, 8))
        with self.assertRaisesRegex(ValueError, "shape 不一致"):
            select_weights(weights, expected)

    def test_converter_uses_mlx_safe_atomic_safetensors_filename(self):
        class FakeMX:
            @staticmethod
            def save_safetensors(path, arrays, metadata=None):
                path = Path(path)
                actual = path if path.suffix == ".safetensors" else Path(str(path) + ".safetensors")
                actual.write_bytes(b"converted")

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "transformer.safetensors"
            save_safetensors_atomic(FakeMX, destination, {"weight": object()}, {"kind": "test"})
            self.assertEqual(destination.read_bytes(), b"converted")
            self.assertFalse((destination.parent / ".transformer.tmp.safetensors").exists())
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_worker_loads_catalog_model_path_instead_of_hardcoded_build(self):
        class Pipeline:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class PipelineModule:
            Krea2Pipeline = Pipeline

        with tempfile.TemporaryDirectory() as temp:
            component = Path(temp)
            base = component / "cache" / "krea2_alis_mlx" / "krea__Krea-2-Turbo"
            base.mkdir(parents=True)
            (base / "model_index.json").write_text("{}")
            transformer = component / "custom.safetensors"
            transformer.write_bytes(b"custom")
            engine = Engine(component, PipelineModule)
            pipeline = engine.load({"id": "portrait-v2", "name": "Portrait v2",
                                    "precision": "8bit", "path": str(transformer)},
                                   lambda: False)
            self.assertEqual(pipeline.kwargs["transformer_path"], str(transformer.resolve()))
            self.assertEqual(engine.model_id, "portrait-v2")
            self.assertEqual(engine.model_name, "Portrait v2")

    def test_worker_bypasses_classifier_when_safety_is_disabled(self):
        class Pipeline:
            def set_loras(self, loras):
                self.loras = loras

            def generate(self, prompt, **kwargs):
                kwargs["step_callback"](1, 1)
                return [Image.new("RGB", (32, 32), (20, 40, 60))]

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = root / "job"
            job.mkdir()
            engine = Engine(root, object())
            engine.load = lambda precision, cancelled: Pipeline()
            engine.safety = lambda: self.fail("关闭安全检查时不应加载分类器")
            request = {"job_id": "test", "job_dir": str(job),
                       "cancel_file": str(job / "cancel"), "spec": {
                           "prompt": "local image", "precision": "8bit", "width": 512,
                           "height": 512, "steps": 1, "seed": 7, "image_count": 1,
                           "strength": .6, "loras": [], "safety_enabled": False}}
            with mock.patch("backend.krea2.worker.emit"):
                result = engine.run(request)
            self.assertFalse(result["safety_enabled"])
            self.assertIsNone(result["safety_threshold"])
            self.assertEqual(result["flagged"], 0)
            self.assertTrue(Path(result["paths"][0]).is_file())
            timing = result["generation_timing"]
            self.assertTrue(timing["local_inference"])
            self.assertGreater(timing["total_seconds"], 0)
            self.assertAlmostEqual(
                timing["total_seconds"],
                sum(timing[key] for key in (
                    "model_load_seconds", "inference_seconds",
                    "denoise_seconds", "save_seconds")),
                delta=.01,
            )

    def test_worker_dispatches_instruction_edit_with_adapter_first(self):
        calls = {}

        class Pipeline:
            def set_loras(self, loras):
                calls["loras"] = loras

        module = types.ModuleType("edit_mlx")

        def generate_edit(pipe, prompt, **kwargs):
            calls.update({"pipe": pipe, "prompt": prompt, **kwargs})
            kwargs["phase_callback"](.5, "synthetic grounding")
            kwargs["step_callback"](1, 1)
            return [Image.new("RGB", (32, 32), (80, 40, 20))]

        module.generate_edit = generate_edit
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = root / "job"
            job.mkdir()
            source = job / "edit_input.png"
            Image.new("RGB", (40, 30), (20, 40, 60)).save(source)
            adapter = root / "edit.safetensors"
            style = root / "style.safetensors"
            adapter.write_bytes(b"edit")
            style.write_bytes(b"style")
            engine = Engine(root, object())
            pipe = Pipeline()
            engine.load = lambda precision, cancelled: pipe
            request = {"job_id": "edit-test", "job_dir": str(job),
                       "cancel_file": str(job / "cancel"), "spec": {
                           "prompt": "change the coat", "mode": "edit",
                           "precision": "8bit", "width": 512, "height": 512,
                           "steps": 1, "seed": 9, "image_count": 1,
                           "strength": .6, "edit_image": str(source),
                           "edit_adapter": {"path": str(adapter), "scale": .95},
                           "reference_strength": 4.5, "grounding_px": 768,
                           "fit_mode": "fit",
                           "loras": [{"path": str(style), "scale": .6}],
                           "safety_enabled": False,
                       }}
            with mock.patch.dict(sys.modules, {"edit_mlx": module}), \
                    mock.patch("backend.krea2.worker.emit"):
                result = engine.run(request)
            self.assertEqual(calls["loras"], [(str(adapter.resolve()), .95),
                                                (str(style.resolve()), .6)])
            self.assertIs(calls["pipe"], pipe)
            self.assertEqual(calls["source_image"], str(source.resolve()))
            self.assertEqual(calls["reference_strength"], 4.5)
            self.assertEqual(calls["grounding_px"], 768)
            self.assertEqual(result["mode"], "edit")
            self.assertTrue(Path(result["paths"][0]).is_file())

    def test_service_queues_archives_sidecars_and_keeps_public_params_path_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tasks, sent = {}, []

            def create(task_id, prompt, params, status, task_type):
                tasks[task_id] = {"task_id": task_id, "prompt": prompt, "params": dict(params),
                                  "status": status, "type": task_type, "result_files": []}

            def fields(task_id, **values):
                if isinstance(values.get("params"), str):
                    values["params"] = json.loads(values["params"])
                if isinstance(values.get("result_files"), str):
                    values["result_files"] = json.loads(values["result_files"])
                tasks[task_id].update({key: value for key, value in values.items() if value is not None})

            runtime = FakeRuntime()
            service = Service(root / "data", root / "component", runtime,
                create_task=create, get_task=lambda task_id: tasks.get(task_id),
                get_all_tasks=lambda limit=50: list(tasks.values())[:limit],
                update_task=lambda task_id, status, **kwargs: fields(task_id, status=status, **kwargs),
                update_task_status=lambda task_id, status, message=None, stage=None, **kwargs:
                    fields(task_id, status=status, progress_text=message, stage=stage, **kwargs),
                update_task_fields=fields, daily_output_dir=lambda: root / "archive" / "2026-09-28",
                write_prompt_sidecar=lambda image, prompt, txt_path=None:
                    image.with_suffix(".md").write_text(prompt, encoding="utf-8"),
                send_document=lambda path, caption: sent.append((path, caption)),
                model_store=FakeModelStore(root / "fake-transformer.safetensors"))
            self.addCleanup(service.close)

            lora_bytes = synthetic_lora()
            asset = service.import_lora(io.BytesIO(lora_bytes), len(lora_bytes), "ink.safetensors")["lora"]
            reply = service.submit({"prompt": "a glass fox", "precision": "8bit", "width": 512,
                "height": 512, "steps": 4, "image_count": 2, "seed": 7,
                "loras": [{"asset_id": asset["asset_id"], "scale": .8}],
                "telegram_enabled": False})
            deadline = time.time() + 4
            while tasks[reply["task_id"]]["status"] not in {"succeeded_no_telegram", "failed"} and time.time() < deadline:
                time.sleep(.02)
            task = tasks[reply["task_id"]]
            self.assertEqual(task["type"], TASK_TYPE)
            self.assertEqual(task["status"], "succeeded_no_telegram")
            self.assertEqual(len(task["result_files"]), 2)
            for name in task["result_files"]:
                image = root / "archive" / "2026-09-28" / name
                self.assertTrue(image.is_file())
                self.assertEqual(image.with_suffix(".txt").read_text(), "a glass fox\n")
                self.assertTrue(image.with_suffix(".md").is_file())
                self.assertTrue(image.with_suffix(".krea2.json").is_file())
            serialized = json.dumps(task["params"])
            self.assertIn(asset["asset_id"], serialized)
            self.assertEqual(task["params"]["aspect_ratio"], "1:1")
            self.assertEqual(task["params"]["base_model_id"], DEFAULT_MODEL_ID)
            self.assertEqual(task["params"]["base_model_name"], "Krea 2 Turbo · Alis MLX")
            self.assertEqual(task["params"]["main_model"], "Krea 2 Turbo · Alis MLX")
            self.assertFalse(task["params"]["safety_enabled"])
            self.assertIsNone(task["params"]["safety_threshold"])
            timing = task["params"]["generation_timing"]
            self.assertTrue(timing["local_inference"])
            self.assertGreaterEqual(timing["save_seconds"], .5)
            self.assertGreaterEqual(timing["total_seconds"], 8.0)
            self.assertEqual(task["params"]["duration_seconds"], timing["total_seconds"])
            first = root / "archive" / "2026-09-28" / task["result_files"][0]
            sidecar = json.loads(first.with_suffix(".krea2.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["generation_timing"], timing)
            self.assertNotIn(str((root / "data").resolve()), serialized)
            self.assertEqual(sent, [])
            with self.assertRaisesRegex(RuntimeError, "安全分类模型"):
                service.submit({"prompt": "checked", "precision": "8bit",
                                "safety_enabled": True})

    def test_service_resolves_instruction_edit_source_and_adapter_server_side(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tasks = {}

            def create(task_id, prompt, params, status, task_type):
                tasks[task_id] = {"task_id": task_id, "prompt": prompt,
                                  "params": dict(params), "status": status,
                                  "type": task_type, "result_files": []}

            def fields(task_id, **values):
                if isinstance(values.get("params"), str):
                    values["params"] = json.loads(values["params"])
                if isinstance(values.get("result_files"), str):
                    values["result_files"] = json.loads(values["result_files"])
                tasks[task_id].update(
                    {key: value for key, value in values.items() if value is not None})

            runtime = FakeRuntime()
            service = Service(
                root / "data", root / "component", runtime,
                create_task=create, get_task=lambda task_id: tasks.get(task_id),
                get_all_tasks=lambda limit=50: list(tasks.values())[:limit],
                update_task=lambda task_id, status, **kwargs:
                    fields(task_id, status=status, **kwargs),
                update_task_status=lambda task_id, status, message=None, stage=None, **kwargs:
                    fields(task_id, status=status, progress_text=message, stage=stage, **kwargs),
                update_task_fields=fields,
                daily_output_dir=lambda: root / "archive" / "2026-09-28",
                write_prompt_sidecar=lambda image, prompt, txt_path=None:
                    image.with_suffix(".md").write_text(prompt, encoding="utf-8"),
                send_document=lambda path, caption: None,
                model_store=FakeModelStore(root / "fake-transformer.safetensors"),
            )
            self.addCleanup(service.close)
            adapter_bytes = synthetic_lora()
            adapter = service.import_lora(
                io.BytesIO(adapter_bytes), len(adapter_bytes),
                "krea2_identity_edit_v1_2.safetensors")["lora"]
            image_stream = io.BytesIO()
            Image.new("RGB", (96, 64), (20, 80, 120)).save(image_stream, format="PNG")
            upload = service.upload_image(image_stream.getvalue(), "source.png")
            reply = service.submit({
                "prompt": "make the jacket emerald", "mode": "edit",
                "width": 512, "height": 512, "steps": 4, "seed": 11,
                "edit_image_upload_token": upload["upload_token"],
                "edit_adapter_asset_id": adapter["asset_id"],
                "edit_adapter_scale": .9, "reference_strength": 4,
                "grounding_px": 768, "fit_mode": "fit",
            })
            deadline = time.time() + 4
            while tasks[reply["task_id"]]["status"] not in {
                    "succeeded_no_telegram", "failed"} and time.time() < deadline:
                time.sleep(.02)
            task = tasks[reply["task_id"]]
            self.assertEqual(task["status"], "succeeded_no_telegram")
            self.assertEqual(task["params"]["mode"], "edit")
            self.assertTrue(task["params"]["has_edit_image"])
            self.assertFalse(task["params"]["has_init_image"])
            self.assertEqual(task["params"]["edit_adapter"]["asset_id"],
                             adapter["asset_id"])
            serialized = json.dumps(task["params"])
            self.assertNotIn(str((root / "data").resolve()), serialized)
            self.assertEqual(runtime.last_spec["mode"], "edit")
            self.assertTrue(Path(runtime.last_spec["edit_image"]).is_file())
            self.assertTrue(Path(runtime.last_spec["edit_image"]).is_relative_to(
                (root / "data" / "jobs" / reply["task_id"]).resolve()))
            self.assertTrue(Path(runtime.last_spec["edit_adapter"]["path"]).is_file())
            submission = json.loads((root / "data" / "jobs" / reply["task_id"]
                                     / "submission.json").read_text(encoding="utf-8"))
            self.assertNotIn("path", submission["edit_adapter"])
            archived = root / "archive" / "2026-09-28" / task["result_files"][0]
            sidecar = json.loads(archived.with_suffix(".krea2.json").read_text(
                encoding="utf-8"))
            self.assertEqual(sidecar["parameters"]["mode"], "edit")


if __name__ == "__main__":
    unittest.main()
