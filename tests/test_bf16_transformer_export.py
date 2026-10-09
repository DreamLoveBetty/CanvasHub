"""Portable BF16 export regressions. Tiny synthetic weights, no MLX or downloads."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from backend.local_image.safetensors import estimate_bf16_bytes, validate_bf16_safetensors
from backend.local_image.comfy_fp8 import read_safetensors_header
from backend.krea2 import contracts as k_contracts, converter_worker as k_worker
from backend.krea2.conversion_service import ConversionService as KConversion
from backend.krea2.model_store import BaseModelStore as KStore
from backend.krea2.worker import Engine
from backend.qwen21 import contracts as q_contracts, converter_worker as q_worker
from backend.qwen21.conversion_service import ConversionService as QConversion
from backend.qwen21.model_store import BaseModelStore as QStore, OUTPUT_BYTES


def checkpoint(path, tensors, metadata):
    header, data = {"__metadata__": metadata}, bytearray()
    for key, (dtype, shape) in tensors.items():
        start = len(data)
        size = 1
        for dim in shape:
            size *= dim
        data.extend(b"\0" * size * {"BF16": 2, "F16": 2, "F32": 4, "U32": 4}[dtype])
        header[key] = {"dtype": dtype, "shape": list(shape), "data_offsets": [start, len(data)]}
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + data)


class StorageTests(unittest.TestCase):
    def test_export_formats_do_not_change_default_or_download_catalogs(self):
        self.assertEqual(set(k_contracts.EXPORT_FORMATS), {"8bit", "mixed-4-8", "bf16"})
        self.assertEqual(set(q_contracts.EXPORT_FORMATS), {"8bit", "bf16"})
        self.assertNotIn("bf16", k_contracts.BUILDS)
        self.assertNotIn("bf16", k_contracts.BUILTIN_MODEL_IDS)
        self.assertEqual(k_contracts.normalize_job({"prompt": "x"})["precision"], "8bit")
        self.assertEqual(q_contracts.normalize_job({"prompt": "x"})["base_model_id"], q_contracts.DEFAULT_MODEL_ID)
        spec = k_contracts.normalize_job({"prompt": "x", "precision": "bf16", "base_model_id": "custom-bf16"})
        self.assertEqual(spec["precision"], "bf16")
        with self.assertRaisesRegex(ValueError, "已转换"):
            k_contracts.normalize_job({"prompt": "x", "precision": "bf16"})

    def test_bf16_estimate_uses_shapes_and_excludes_source_auxiliary_tensors(self):
        tensors = {"layer.weight": {"shape": [64, 32]}, "layer.weight_scale": {"shape": []},
                   "layer.comfy_quant": {"shape": [100]}, "norm.weight": {"shape": [64]}}
        self.assertEqual(estimate_bf16_bytes(tensors), 1024**2 + 2 * (64 * 32 + 64))
        self.assertGreater(OUTPUT_BYTES["bf16"], OUTPUT_BYTES["8bit"])

    def test_bf16_header_rejects_wrong_dtype_count_packing_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "0.safetensors"
            for key, dtype, metadata, count in [
                ("weight", "F32", {"precision": "bf16"}, 1),
                ("weight", "F16", {"precision": "bf16"}, 1),
                ("layer.scales", "BF16", {"precision": "bf16"}, 1),
                ("weight", "BF16", {"precision": "8bit"}, 1),
                ("weight", "BF16", {"precision": "bf16"}, 2),
            ]:
                with self.subTest(key=key, dtype=dtype, count=count):
                    checkpoint(file, {key: (dtype, (1,))}, metadata)
                    with self.assertRaisesRegex(ValueError, "BF16"):
                        validate_bf16_safetensors(file, count, metadata={"precision": "bf16"})
            checkpoint(file, {"weight": ("BF16", (1,))}, {"precision": "bf16"})
            validate_bf16_safetensors(file, 1, metadata={"precision": "bf16"})

    def publish(self, engine, store, precision, stage_id, **changes):
        count = 297 if engine == "qwen21" else 105
        stage = store.staging / stage_id
        relative = "transformer/0.safetensors" if engine == "qwen21" else "transformer.safetensors"
        file = stage / relative
        metadata = {"precision": precision, "quantization_level": "None" if precision == "bf16" else "8"}
        checkpoint(file, {f"layer_{i}.weight": ("BF16", (1,)) for i in range(count)}, metadata)
        result = {"source_sha256": "a" * 64, "output_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                  "source_prefix": "", "source_format": "comfy-scaled-fp8-e4m3fn",
                  "source_tensor_count": count, "output_tensor_count": count,
                  "quantized_linear_count": 0 if precision == "bf16" else (228 if engine == "qwen21" else 224),
                  "strict_load": True, "strict_reload": True, "precision": precision}
        result.update(changes)
        if engine == "qwen21":
            (stage / "transformer/config.json").write_text("{}")
            (stage / "transformer/model.safetensors.index.json").write_text("{}")
            return store.publish(stage, result, name="Portrait", source_name="source.safetensors", precision=precision)
        result.pop("strict_load"); result.pop("strict_reload")
        return store.publish(stage, name="Portrait", source_name="source.safetensors", **result)

    def test_both_stores_publish_bf16_beside_8bit_with_unchanged_shared_components(self):
        for engine, cls in [("krea2", KStore), ("qwen21", QStore)]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                store = cls(Path(temp) / "assets", Path(temp) / "component"); store.paths()
                shared = store.shared if engine == "qwen21" else Path(temp) / "component/cache/base"
                for name in ["text_encoder", "vae", "processor"]:
                    marker = shared / name / "unchanged"; marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_bytes(b"existing shared component")
                old = self.publish(engine, store, "8bit", "old")
                item = self.publish(engine, store, "bf16", "new")
                self.assertNotEqual(old["id"], item["id"])
                self.assertTrue(item["id"].endswith("-bf16")); self.assertIn("BF16", item["label"])
                self.assertIsNone(item["group_size"]); self.assertFalse(item["requantized"])
                self.assertTrue(old["requantized"]); self.assertNotIn("path", item)
                self.assertTrue((store.directory / old["id"]).is_dir())
                for name in ["text_encoder", "vae", "processor"]:
                    self.assertEqual((shared / name / "unchanged").read_bytes(), b"existing shared component")
                    if engine == "qwen21":
                        link = store.directory / item["id"] / name
                        self.assertTrue(link.is_symlink()); self.assertEqual(link.resolve(), shared / name)
                duplicate = self.publish(engine, store, "bf16", "duplicate")
                self.assertEqual(item["id"], duplicate["id"])
                self.assertFalse((store.staging / "duplicate").exists())
                store.delete(item["id"])
                self.assertTrue((store.directory / old["id"]).is_dir())
                self.assertTrue((shared / "vae/unchanged").is_file())

    def test_both_stores_reject_bf16_quantized_result_and_count_mismatch(self):
        for engine, cls in [("krea2", KStore), ("qwen21", QStore)]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                store = cls(Path(temp) / "assets", Path(temp) / "component"); store.paths()
                for index, change in enumerate([{"quantized_linear_count": 224}, {"output_tensor_count": 999}]):
                    with self.assertRaisesRegex(RuntimeError, "结构|数量"):
                        self.publish(engine, store, "bf16", str(index), **change)
                self.assertFalse(any(x["precision"] == "bf16" for x in store.list()))

    def test_bf16_discovery_rejects_modified_header_even_with_same_file_size(self):
        for engine, cls in [("krea2", KStore), ("qwen21", QStore)]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                store = cls(Path(temp) / "assets", Path(temp) / "component"); store.paths()
                item = self.publish(engine, store, "bf16", "new")
                folder = store.directory / item["id"]
                file = folder / ("transformer/0.safetensors" if engine == "qwen21" else "transformer.safetensors")
                file.write_bytes(file.read_bytes().replace(b'"BF16"', b'"XXXX"', 1))
                self.assertFalse(any(x["id"] == item["id"] for x in store.list()))


class Array:
    def __init__(self, shape=(1,), dtype="F32"):
        self.shape, self.dtype = tuple(shape), dtype

    def astype(self, dtype):
        return Array(self.shape, dtype)


@contextmanager
def fake_mlx(engine, source, arrays):
    """Exercise real converter control flow and file headers, not GPU math."""
    count = 228 if engine == "qwen21" else 224
    loads = []

    class Model:
        def __init__(self, *args):
            self.values = {key: Array(value.shape) for key, value in arrays.items()}
            self.quantized = False

        def parameters(self):
            return self.values

        def update(self, values):
            self.values = values

        def load_weights(self, weights, strict):
            loads.append(strict)
            if isinstance(weights, str):
                tensors = read_safetensors_header(weights).tensors
                self.values = {key: Array(t["shape"], t["dtype"]) for key, t in tensors.items()}
            else:
                self.values = dict(weights)

        def named_modules(self):
            return [(str(i), types.SimpleNamespace(bits=8)) for i in range(count)] if self.quantized else []

    mx = types.ModuleType("mlx.core")
    mx.bfloat16 = "BF16"
    mx.eval = lambda *args: None
    mx.clear_cache = lambda: None
    mx.load = lambda path: dict(arrays)
    mx.save_safetensors = lambda path, values, metadata: checkpoint(
        Path(path), {k: (v.dtype, v.shape) for k, v in values.items()}, metadata)
    nn = types.ModuleType("mlx.nn")
    nn.quantize = mock.Mock(side_effect=lambda model, **kw: setattr(model, "quantized", True))
    utils = types.ModuleType("mlx.utils")
    utils.tree_flatten = lambda values: list(values.items())
    utils.tree_map = lambda fn, values: {key: fn(value) for key, value in values.items()}
    mlx = types.ModuleType("mlx"); mlx.core, mlx.nn, mlx.utils = mx, nn, utils
    modules = {"mlx": mlx, "mlx.core": mx, "mlx.nn": nn, "mlx.utils": utils}
    if engine == "krea2":
        modules["krea2.transformer"] = types.SimpleNamespace(Krea2Config=lambda: None, SingleStreamDiT=Model)
        modules["krea2.quant_recipes"] = types.SimpleNamespace(quantize_bulk=lambda *args: True, mixed_4_8=lambda *args: True)
    else:
        modules["mflux.models.qwen21.model.qwen21_transformer.qwen21_transformer"] = types.SimpleNamespace(Qwen21Transformer=Model)
        modules["mflux.models.qwen21.reference.weights.qwen_image21_weight_definition"] = types.SimpleNamespace(
            QwenImage21WeightDefinition=types.SimpleNamespace(quantization_predicate=lambda *args: True))
    with mock.patch.dict(sys.modules, modules):
        yield nn, loads


class ConverterTests(unittest.TestCase):
    def run_converter(self, engine, precision, fp8=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "source.safetensors"; config = root / "config.json"
            config.write_text("{}")
            arrays = {f"layer_{i}.weight": Array() for i in range(297 if engine == "qwen21" else 105)}
            checkpoint(source, {key: (value.dtype, value.shape) for key, value in arrays.items()}, {})
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            worker = k_worker if engine == "krea2" else q_worker
            fp8_info = {"source_format": "comfy-scaled-fp8-e4m3fn", "quantized_tensor_count": 1} if fp8 else None
            decoded = {"weights": [(k, v.astype("BF16")) for k, v in arrays.items()], "source_prefix": "",
                       "source_format": "comfy-scaled-fp8-e4m3fn",
                       "source_tensor_count": len(arrays), "quantized_tensor_count": 1, "source_quantized_tensor_count": 1}
            with fake_mlx(engine, source, arrays) as (nn, loads), mock.patch.object(worker, "emit") as emit, \
                    mock.patch.object(worker, "inspect_comfy_scaled_fp8", return_value=fp8_info), \
                    mock.patch.object(worker, "load_comfy_scaled_fp8", return_value=decoded) as decode:
                if engine == "krea2":
                    with mock.patch.object(worker, "configure"):
                        worker.convert(root, source, root / "output", precision, "Synthetic")
                    result = next(call.kwargs for call in emit.call_args_list if call.args[0] == "result")
                    dest = root / "output/transformer.safetensors"
                else:
                    with mock.patch.object(worker, "expected_shapes", return_value={k: v.shape for k, v in arrays.items()}), \
                            mock.patch.object(worker, "match_header", return_value=""):
                        result = worker.convert(source, root / "output", config, "Synthetic", precision)
                    dest = root / "output/transformer/0.safetensors"
                    index = json.loads((dest.parent / "model.safetensors.index.json").read_text())
                    self.assertEqual(index["metadata"]["quantization_level"], "None" if precision == "bf16" else "8")
                self.assertEqual(loads, [True, True])
                self.assertEqual(result["precision"], precision)
                self.assertEqual(result["source_tensor_count"], result["output_tensor_count"])
                self.assertEqual(decode.call_count, int(fp8))
                if precision == "bf16":
                    nn.quantize.assert_not_called()
                    self.assertEqual(result["quantized_linear_count"], 0)
                    header = validate_bf16_safetensors(dest, len(arrays), metadata={"precision": "bf16"})
                    self.assertNotIn("group_size", header.metadata)
                else:
                    self.assertEqual(nn.quantize.call_count, 2)
                    for call in nn.quantize.call_args_list:
                        self.assertEqual(call.kwargs["bits"], 4 if precision == "mixed-4-8" else 8)
                        self.assertEqual(call.kwargs["group_size"], 64)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)

    def test_both_workers_bf16_skip_quantization_and_strictly_reload(self):
        for engine in ["krea2", "qwen21"]:
            with self.subTest(engine=engine):
                self.run_converter(engine, "bf16")

    def test_scaled_fp8_can_export_bf16_without_a_second_quantization(self):
        for engine in ["krea2", "qwen21"]:
            with self.subTest(engine=engine):
                self.run_converter(engine, "bf16", fp8=True)

    def test_existing_8bit_and_mixed_recipes_still_quantize_twice(self):
        for engine, precision in [("krea2", "8bit"), ("krea2", "mixed-4-8"), ("qwen21", "8bit")]:
            with self.subTest(engine=engine, precision=precision):
                self.run_converter(engine, precision)


class ServiceTests(unittest.TestCase):
    def service(self, engine, root):
        store_cls, service_cls = (KStore, KConversion) if engine == "krea2" else (QStore, QConversion)
        store = store_cls(root / "assets", root / "component"); store.paths()
        inspection = {"source_path": str(root / "source.safetensors"), "source_name": "source.safetensors",
                      "suggested_name": "Portrait", "kind": "candidate", "source_format": "float",
                      "estimated_outputs": {"8bit": 8 * 1024**3, "bf16": 28 * 1024**3}}
        store.inspect_source = mock.Mock(return_value=inspection)
        if engine == "qwen21":
            config = store.shared / "transformer/config.json"; config.parent.mkdir(parents=True)
            config.write_text("{}")
        runtime = types.SimpleNamespace(python=Path(sys.executable), child_environment=lambda: {}, close=mock.Mock(),
                                        release_accelerator_memory=mock.Mock())
        service = service_cls(root / "jobs", root / "component", runtime, store)
        self.addCleanup(service.close)
        return service

    def test_both_services_keep_default_and_pass_bf16_to_the_job(self):
        for engine in ["krea2", "qwen21"]:
            for precision in [None, "bf16"]:
                with self.subTest(engine=engine, precision=precision), tempfile.TemporaryDirectory() as temp:
                    service = self.service(engine, Path(temp))
                    module = f"backend.{engine}.conversion_service"
                    with mock.patch(module + ".threading.Thread") as thread, mock.patch(
                            module + ".shutil.disk_usage", return_value=types.SimpleNamespace(free=100 * 1024**3)):
                        state = service.start({"source_path": "source.safetensors", "precision": precision})
                        spec = thread.call_args.kwargs["args"][0]
                        self.assertEqual(state["precision"], precision or "8bit")
                        self.assertEqual(spec["precision"], precision or "8bit")
                        service.cancel(); service.close()

    def test_disk_precheck_rejects_bf16_without_starting_a_worker(self):
        for engine in ["krea2", "qwen21"]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                service = self.service(engine, Path(temp)); module = f"backend.{engine}.conversion_service"
                with mock.patch(module + ".threading.Thread") as thread, mock.patch(
                        module + ".shutil.disk_usage", return_value=types.SimpleNamespace(free=12 * 1024**3)):
                    with self.assertRaisesRegex(RuntimeError, "空间不足"):
                        service.start({"source_path": "source.safetensors", "precision": "bf16"})
                    thread.assert_not_called()
                    self.assertEqual(list(service.store.staging.iterdir()), [])
                    service.start({"source_path": "source.safetensors"})
                    thread.assert_called_once(); service.close()

    def test_unknown_precision_fails_before_source_read(self):
        for engine in ["krea2", "qwen21"]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                service = self.service(engine, Path(temp))
                with self.assertRaisesRegex(ValueError, "输出精度"):
                    service.start({"precision": "16"})
                service.store.inspect_source.assert_not_called()

    def test_bf16_waiting_cancel_does_not_release_or_interrupt_another_worker(self):
        for engine in ["krea2", "qwen21"]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                service = self.service(engine, Path(temp)); waiting = threading.Event()
                module = f"backend.{engine}.conversion_service"

                @contextmanager
                def lease(path, cancel, progress):
                    progress({"message": "等待本地推理资源"}); waiting.set(); cancel.wait(3)
                    yield types.SimpleNamespace(fileno=lambda: 1)

                with mock.patch(module + ".local_accelerator", lease), mock.patch(
                        module + ".shutil.disk_usage", return_value=types.SimpleNamespace(free=100 * 1024**3)), \
                        mock.patch.object(service, "_execute") as execute:
                    service.start({"source_path": "source.safetensors", "precision": "bf16"})
                    self.assertTrue(waiting.wait(2)); self.assertEqual(service.status()["status"], "waiting")
                    service.cancel(); service._thread.join(timeout=3)
                    self.assertEqual(service.status()["status"], "canceled")
                    execute.assert_not_called(); service.runtime.release_accelerator_memory.assert_not_called()
                    self.assertEqual(list(service.store.staging.iterdir()), [])

    def test_both_worker_commands_include_bf16(self):
        for engine in ["krea2", "qwen21"]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); service = self.service(engine, root)
                result = {"event": "result", "precision": "bf16", "source_sha256": "a" * 64,
                          "output_sha256": "b" * 64, "source_tensor_count": 297,
                          "output_tensor_count": 297, "quantized_linear_count": 0}
                prefix = k_worker.PREFIX if engine == "krea2" else q_worker.PREFIX
                process = mock.Mock(stdout=io.StringIO(prefix + json.dumps(result) + "\n"))
                process.wait.return_value = 0
                spec = {"job_id": "probe", "precision": "bf16", "stage": root / "stage", "config": root / "config",
                        "source": "source.safetensors", "source_path": "source.safetensors", "source_name": "source.safetensors",
                        "name": "Portrait", "model_name": "Portrait"}
                module = f"backend.{engine}.conversion_service"
                with mock.patch(module + ".subprocess.Popen", return_value=process) as popen, \
                        mock.patch(module + ".threading.Thread"), mock.patch.object(service.store, "publish", return_value={}) as publish:
                    service._execute(spec, 1)
                    command = popen.call_args.args[0]
                    self.assertEqual(command[command.index("--precision") + 1], "bf16")
                    if engine == "krea2":
                        self.assertEqual(publish.call_args.kwargs["precision"], "bf16")
                    service._process = None

    def test_krea_worker_selects_bf16_without_changing_shared_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); base = root / "cache/krea2_alis_mlx/krea__Krea-2-Turbo"
            base.mkdir(parents=True); (base / "model_index.json").write_text("{}")
            transformer = root / "transformer.safetensors"; transformer.write_bytes(b"synthetic")
            factory = mock.Mock(side_effect=lambda **kw: types.SimpleNamespace(**kw))
            engine = Engine(root, types.SimpleNamespace(Krea2Pipeline=factory))
            with mock.patch.object(engine, "unload"), mock.patch("backend.krea2.worker.emit"):
                selection = {"id": "portrait-bf16", "name": "Portrait", "precision": "bf16", "path": str(transformer)}
                pipeline = engine.load(selection, lambda: False)
                self.assertEqual(pipeline.precision, "bf16")
                self.assertEqual(pipeline.base_dir, str(base))
                self.assertIs(engine.load(selection, lambda: False), pipeline)
                engine.load({**selection, "precision": "8bit"}, lambda: False)
                self.assertEqual(factory.call_count, 2)

    def test_krea_bf16_preparation_only_prepares_existing_shared_components(self):
        from backend.krea2.service import Service
        service = Service.__new__(Service)
        service.conversion = types.SimpleNamespace(status=lambda: {"status": "idle"})
        service.models = types.SimpleNamespace(resolve=lambda model_id: {"precision": "bf16"})
        service.runtime = types.SimpleNamespace(python=Path(sys.executable))
        service._lock, service._prepare_process = threading.RLock(), None
        service._watch_prepare = mock.Mock()
        with mock.patch("backend.krea2.service.subprocess.Popen") as popen, \
                mock.patch("backend.krea2.service.threading.Thread"):
            reply = service.prepare({"base_model_id": "portrait-bf16"})
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--models") + 1], "none")
            self.assertEqual(reply["preparation"]["precision"], "bf16")
            self.assertEqual(reply["preparation"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
