"""Portable synthetic control/LoKr regressions; no real weights or MLX needed."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import time
import unittest
from unittest.mock import patch

import numpy as np

from backend.krea2.control_profile import PROFILE, normalize_control, render_control
from backend.krea2.lokr import FORMAT, inspect_lokr, target_path
from backend.krea2.lora_store import LoRAStore
from backend.krea2.contracts import normalize_job
from backend.krea2.service import Service
from backend.krea2.worker import Engine, Cancelled
from PIL import Image
from tests.test_krea2_domain import FakeRuntime, FakeModelStore


def marker(**changes):
    return {"profile": PROFILE, "circles": [{"cx": .5, "cy": .5, "rx": .1, "ry": .2,
                                            "angle": 0, **changes}]}


def write_lokr(path, *, entries=None):
    entries = entries or {
        "lycoris_img_in.lokr_w1": ([2, 3], [1.]*6),
        "lycoris_img_in.lokr_w2": ([3, 4], [1.]*12),
        "lycoris_img_in.alpha": ([], [17.]),
    }
    header, data = {}, bytearray()
    for key, (shape, values) in entries.items():
        start = len(data)
        data.extend(struct.pack("<"+"f"*len(values), *values))
        header[key] = {"dtype": "F32", "shape": shape, "data_offsets": [start, len(data)]}
    encoded = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(encoded))+encoded+data)


class ControlTests(unittest.TestCase):
    def test_reference_size_changes_only_vae_geometry_and_preserves_padding(self):
        from backend.krea2 import control_profile
        self.assertTrue(hasattr(control_profile, 'prepare_control_images'))
        image=Image.new('RGB',(720,1280),'black')
        for size,expected in ((1024,(576,1024)),(768,(432,768)),(512,(288,512))):
            ref,vision=control_profile.prepare_control_images(image,size)
            self.assertEqual(ref.size,expected)
            self.assertEqual(vision.size,(288,512))
            self.assertEqual(image.size,(720,1280))
        ref,_=control_profile.prepare_control_images(Image.new('RGB',(832,1248),'black'),512)
        self.assertEqual(ref.size,(352,512))
        self.assertEqual(ref.getpixel((340,0)),(0,0,0))
        self.assertEqual(ref.getpixel((351,0)),(255,255,255))

    def test_render_two_colours_and_area(self):
        image, report = render_control(marker(), 512, 512)
        self.assertEqual(set(map(tuple, np.asarray(image).reshape(-1, 3))), {(0, 0, 0), (250, 219, 174)})
        self.assertAlmostEqual(report["coverage"], np.pi*.1*.2, places=3)

    def test_overlap_is_union_not_sum(self):
        spec = marker()
        one, first = render_control(spec, 256, 512)
        spec["circles"].append(copy.deepcopy(spec["circles"][0]))
        two, second = render_control(spec, 256, 512)
        self.assertEqual(one.tobytes(), two.tobytes())
        self.assertEqual(first, second)

    def test_angle_rotates_in_pixel_not_normalized_space(self):
        one, _ = render_control(marker(rx=.1, ry=.3), 256, 512)
        two, _ = render_control(marker(rx=.1, ry=.3, angle=90), 256, 512)
        self.assertNotEqual(one.tobytes(), two.tobytes())
        ys, xs = np.where(np.asarray(one)[..., 0]>0)
        yt, xt = np.where(np.asarray(two)[..., 0]>0)
        self.assertGreater(ys.ptp() if hasattr(ys, 'ptp') else np.ptp(ys), np.ptp(xs))
        self.assertGreater(np.ptp(xt), np.ptp(yt))

    def test_strips_guide_pixels_and_unknown_fields(self):
        spec = marker()
        spec.update({"guide": "private/photo.png", "color": "#ffffff"})
        self.assertEqual(normalize_control(spec), marker())

    def test_archived_control_png_is_not_a_generated_gallery_asset(self):
        from backend import asset_index
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = root / "2026-01-02"
            internal = day / ".krea2-controls"
            internal.mkdir(parents=True)
            Image.new("RGB", (16, 16)).save(internal / "krea2_synthetic.png")
            output = day / "krea2_synthetic_1.png"
            Image.new("RGB", (16, 16)).save(output)
            with patch.object(asset_index, "archive_scan_roots", return_value=[("main", root)]):
                files = asset_index._archive_image_files()
            self.assertEqual([item[0] for item in files], [output])

    def test_bad_input(self):
        for value in (None, {}, {"profile": PROFILE, "circles": []},
                      marker(cx=float("nan")), marker(rx=0), marker(angle=181), marker(cx=True)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_control(value)
        with self.assertRaises(ValueError):
            render_control(marker(), 255, 512)


class LoKrTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "adapter.safetensors"

    def test_direct_shapes_and_library(self):
        write_lokr(self.path)
        report = inspect_lokr(self.path)
        self.assertEqual(report["layers"]["first"]["shape"], [6, 12])
        self.assertEqual(report["adapter_format"], FORMAT)
        store = LoRAStore(self.root)
        store.directory.mkdir()
        self.path.rename(store.directory / self.path.name)
        item = store.list()[0]
        self.assertEqual(item["adapter_format"], FORMAT)
        self.assertEqual(item["adapter_count"], 1)
        self.assertNotIn("layers", item)
        self.assertNotIn("_file", item)

    def test_incomplete_decomposed_or_unknown_rejected(self):
        for key in ("lycoris_img_in.lokr_w1", "lycoris_img_in.lokr_w1_a", "lycoris_unknown.lokr_w1"):
            write_lokr(self.path, entries={key: ([1, 1], [1.])})
            with self.subTest(key=key), self.assertRaises(ValueError):
                inspect_lokr(self.path)

    def test_aliases_are_explicit(self):
        self.assertEqual(target_path("lycoris_text_fusion_layerwise_blocks_1_attn_to_out_0"),
                         "txtfusion.layerwise_blocks.1.attn.wo")
        self.assertEqual(target_path("lycoris_transformer_blocks_27_ff_down"), "blocks.27.mlp.down")
        for name in ("lycoris_transformer_blocks_28_ff_down", "lycoris_text_fusion_layerwise_blocks_2_ff_down",
                     "lycoris_text_fusion_projector_extra", "first"):
            with self.assertRaises(ValueError):
                target_path(name)

    def test_factorization_matches_dense_kron(self):
        # Load the exact production algebra with an ndarray backend, not a
        # second hand-written implementation. No MLX dependency in stable CI.
        fake = types.ModuleType("mlx")
        fake.core = types.SimpleNamespace(swapaxes=np.swapaxes)
        fake.nn = types.SimpleNamespace(Module=object)
        source = Path(__file__).resolve().parents[1]/"backend/krea2/lokr_mlx.py"
        spec = importlib.util.spec_from_file_location("backend.krea2._test_lokr_mlx", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"mlx": fake, "mlx.core": fake.core, "mlx.nn": fake.nn}):
            spec.loader.exec_module(module)
        rng = np.random.default_rng(1)
        for shape in ((12,), (7, 12), (2, 5, 12)):
            x, a, b = rng.normal(size=shape), rng.normal(size=(2, 3)), rng.normal(size=(3, 4))
            np.testing.assert_allclose(module.factorized_delta(x, a, b), x @ np.kron(a, b).T, atol=1e-12)


class ReferenceCacheTests(unittest.TestCase):
    def setUp(self):
        fake=types.ModuleType("mlx")
        fake.core=types.SimpleNamespace(contiguous=np.ascontiguousarray,concatenate=np.concatenate)
        source=Path(__file__).resolve().parents[1]/"backend/krea2/control_attention_mlx.py"
        spec=importlib.util.spec_from_file_location("_test_control_attention",source)
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{"mlx":fake,"mlx.core":fake.core}):
            spec.loader.exec_module(self.module)
        self.cache=self.module.ReferenceKV(3,2)
        self.k=np.arange(40,dtype=np.float32).reshape(1,2,5,4)

    def test_native_attention_preserves_compact_heads_and_matches_expanded_math(self):
        # Execute the production projection/cache boundary without a GPU. Only
        # the MLX kernel and RoPE dependency are replaced by small NumPy math.
        rng=np.random.default_rng(9)
        value=rng.normal(size=(1,3,8)).astype(np.float32)
        key=value[:,:,:4]
        heads=[]
        def sdpa(q,k,v,*,scale,mask=None):
            heads.append((q.shape[1],k.shape[1],v.shape[1]))
            k=np.repeat(k,q.shape[1]//k.shape[1],axis=1)
            v=np.repeat(v,q.shape[1]//v.shape[1],axis=1)
            scores=q@k.swapaxes(-1,-2)*scale
            weights=np.exp(scores-scores.max(axis=-1,keepdims=True))
            return (weights/weights.sum(axis=-1,keepdims=True))@v
        self.module.mx.fast=types.SimpleNamespace(scaled_dot_product_attention=sdpa)
        self.module.mx.sigmoid=lambda x:1/(1+np.exp(-x))
        attn=types.SimpleNamespace(heads=4,kvheads=2,headdim=2,scale=2**-.5,
            wq=lambda x:x,wk=lambda x:x[:,:,:4],wv=lambda x:x[:,:,:4],
            gate=np.zeros_like,wo=lambda x:x,
            qknorm=types.SimpleNamespace(qnorm=lambda x:x,knorm=lambda x:x))
        dependency=types.ModuleType('krea2.transformer')
        dependency._apply_rope=lambda value,*_:value
        with patch.dict(sys.modules,{'krea2':types.ModuleType('krea2'),'krea2.transformer':dependency}):
            result=self.module._attention(attn,value,None,None,None,0,False)
        self.assertEqual(heads,[(4,2,2)])
        q=value.reshape(1,3,4,2).transpose(0,2,1,3)
        k=np.repeat(key.reshape(1,3,2,2).transpose(0,2,1,3),2,axis=1)
        scores=(q@k.swapaxes(-1,-2))*2**-.5
        probabilities=np.exp(scores-scores.max(axis=-1,keepdims=True))
        probabilities/=probabilities.sum(axis=-1,keepdims=True)
        expected=((probabilities@k).transpose(0,2,1,3).reshape(1,3,8))*.5
        np.testing.assert_allclose(result,expected,rtol=1e-6,atol=1e-6)

    def test_capture_reuse_and_bounded_original_kv_heads(self):
        self.assertTrue(self.cache.begin_step())
        for index in range(2):self.cache.capture(index,self.k,self.k+1)
        self.cache.finish_step(True)
        self.assertFalse(self.cache.begin_step())
        k,v=self.cache.append(0,self.k[:,:,:2],self.k[:,:,:2]+1)
        np.testing.assert_array_equal(k,np.concatenate([self.k[:,:,:2],self.k[:,:,-3:]],axis=2))
        self.cache.finish_step(False)
        self.assertEqual(self.cache.report()["capture_steps"],1)
        self.assertEqual(self.cache.report()["reuse_steps"],1)
        self.assertEqual(self.cache.report()["cache_bytes"],2*2*1*2*3*4*4)
        self.assertEqual(len(self.cache.arrays),4)

    def test_partial_and_wrong_shapes_fail_closed(self):
        self.cache.capture(0,self.k,self.k)
        with self.assertRaises(ValueError):self.cache.finish_step(True)
        with self.assertRaises(ValueError):self.cache.capture(0,self.k,self.k)
        self.cache.capture(1,self.k,self.k);self.cache.finish_step(True)
        with self.assertRaises(ValueError):self.cache.append(0,self.k[:,:1],self.k[:,:1])
        with self.assertRaises(ValueError):self.cache.append(0,self.k.astype(np.float16),self.k.astype(np.float16))

    def test_clear_is_idempotent_and_never_leaks_to_another_image(self):
        for index in range(2):self.cache.capture(index,self.k,self.k)
        self.cache.finish_step(True);self.cache.clear();self.cache.clear()
        self.assertEqual(self.cache.arrays,[])
        with self.assertRaises(ValueError):self.cache.begin_step()
        other=self.module.ReferenceKV(3,2)
        self.assertTrue(other.begin_step())
        self.assertEqual(other.report()["cache_bytes"],0)


class ControlRequestTests(unittest.TestCase):
    def request(self, **changes):
        return {"prompt": "clothed studio portrait", "mode": "control", "control": marker(),
                "control_adapter_asset_id": "a"*64, **changes}

    def test_control_mode_preserves_geometry_and_adjustable_steps(self):
        try:
            job = normalize_job(self.request(steps=11))
        except ValueError as exc:
            self.fail(f"valid control contract rejected: {exc}")
        self.assertEqual(job["control"], marker())
        self.assertEqual(job["steps"], 11)
        self.assertEqual(job["control_adapter_asset_id"], "a"*64)

    def test_reference_kv_is_explicit_boolean_off_by_default_and_control_only(self):
        self.assertFalse(normalize_job(self.request())["control_reference_kv_cache"])
        self.assertTrue(normalize_job(self.request(control_reference_kv_cache=True))["control_reference_kv_cache"])
        for value in ("true",1,{},None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_job(self.request(control_reference_kv_cache=value))
        with self.assertRaisesRegex(ValueError,"control"):
            normalize_job({"prompt":"portrait","control_reference_kv_cache":True})

    def test_reference_size_default_strict_values_and_mode_boundary(self):
        self.assertEqual(normalize_job(self.request()).get('control_reference_size'),1024)
        for value in (512,768,1024):
            self.assertEqual(normalize_job(self.request(control_reference_size=value))['control_reference_size'],value)
        for value in (0,256,2048,True,768.5,'768',None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_job(self.request(control_reference_size=value))
        with self.assertRaisesRegex(ValueError,'control'):
            normalize_job({'prompt':'portrait','control_reference_size':512})

    def test_joint_edit_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, "联合编辑"):
            normalize_job(self.request(edit_image_upload_token="source"))

    def test_control_adapter_deduplicated_and_budgeted(self):
        for loras in ([{"asset_id": "a"*64}], [{"asset_id": x*64} for x in "bcde"]):
            with self.assertRaises(ValueError):
                normalize_job(self.request(loras=loras))

    def test_standard_cannot_silently_ignore_control(self):
        with self.assertRaisesRegex(ValueError, "control"):
            normalize_job(self.request(mode="standard"))


class ControlServiceTests(unittest.TestCase):
    def test_control_queue_and_archive_and_regular_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root, tasks = Path(temp), {}
            def create(identity, prompt, params, status, task_type):
                tasks[identity] = dict(task_id=identity, prompt=prompt, params=params,
                                       status=status, type=task_type)
            def fields(identity, **values):
                for key, value in values.items():
                    if key in {"params", "result_files"} and isinstance(value, str):
                        value = json.loads(value)
                    if value is not None:
                        tasks[identity][key] = value
            runtime = FakeRuntime()
            original_execute=runtime.execute
            acceleration=[{"invariant_cache":True,"reference_kv_cache":True,
                           "reference_kv":{"capture_steps":1,"reuse_steps":7}}]
            def execute(*args,**kwargs):
                result=original_execute(*args,**kwargs)
                result["control_acceleration"]=acceleration
                return result
            runtime.execute=execute
            service = Service(root/'data', root/'component', runtime,
                create_task=create, get_task=tasks.get, get_all_tasks=lambda **_: list(tasks.values()),
                update_task=lambda identity, status, **kw: fields(identity, status=status, **kw),
                update_task_status=lambda identity, status, message=None, **kw: fields(identity, status=status, **kw),
                update_task_fields=fields, daily_output_dir=lambda: root/'archive',
                write_prompt_sidecar=lambda *args, **kw: None, send_document=lambda *args: None,
                model_store=FakeModelStore(root/'base.safetensors'))
            self.addCleanup(service.close)
            service.loras.directory.mkdir(parents=True)
            write_lokr(service.loras.directory/'control.safetensors')
            asset = service.list_loras()["loras"][0]["asset_id"]
            with self.assertRaisesRegex(ValueError, "控制适配器"):
                service.submit({"prompt":"portrait", "loras":[{"asset_id":asset}]})
            reply = service.submit({"prompt":"portrait", "mode":"control", "control":marker(),
                                    "control_adapter_asset_id":asset, "control_reference_kv_cache":True,
                                    "control_reference_size":768, "width":512, "height":512})
            identity = reply["task_id"]
            deadline=time.monotonic()+4
            while tasks[identity]["status"] not in {"succeeded_no_telegram","failed"} and time.monotonic()<deadline:
                time.sleep(.02)
            task = tasks[identity]
            self.assertEqual(task["status"], "succeeded_no_telegram", task)
            self.assertTrue(Path(runtime.last_spec["control_image"]).is_file())
            self.assertEqual(task["params"]["control_adapter"]["asset_id"], asset)
            self.assertNotIn(str(root), json.dumps(task["params"]))
            self.assertTrue((root/'archive'/'.krea2-controls'/f'{identity}.png').is_file())
            image = root/'archive'/task["result_files"][0]
            metadata=json.loads(image.with_suffix('.krea2.json').read_text())
            self.assertIn('control_artifact',metadata)
            self.assertEqual(metadata['control_acceleration'],acceleration)
            self.assertTrue(task['params']['control_reference_kv_cache'])
            self.assertTrue(runtime.last_spec['control_reference_kv_cache'])
            self.assertEqual(runtime.last_spec['control_reference_size'],768)
            self.assertEqual(task['params']['control_reference_size'],768)
            self.assertEqual(metadata['parameters']['control_reference_size'],768)


class WorkerIsolationTests(unittest.TestCase):
    def test_control_binding_is_removed_after_success_failure_and_cancellation(self):
        for failure in (None, ValueError("decode failed"), Cancelled("cancelled")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                image = root / "control.png"
                Image.new("RGB", (512, 512)).save(image)
                events = []
                class Pipeline:
                    transformer = object()
                    def set_loras(self, values):
                        events.append("ordinary_loras")
                    def generate(self, prompt, **kwargs):
                        events.append("standard")
                        return [Image.new("RGB", (32, 32))]
                class Binding:
                    def apply(self, *args): events.append("bind")
                    def clear(self): events.append("clear")
                def generate_control(pipe, prompt, **kwargs):
                    events.append("control")
                    self.assertEqual(kwargs["reference_kv_cache"],failure is not None)
                    self.assertEqual(kwargs.get('reference_size'),512)
                    kwargs["diagnostics"].update(invariant_cache=True,reference_kv_cache=kwargs["reference_kv_cache"])
                    kwargs["phase_callback"](.1,"grounding")
                    kwargs["phase_callback"](1,"conditioning done")
                    if failure:
                        raise failure
                    kwargs["step_callback"](1, 1)
                    return [Image.new("RGB", (32, 32))]
                engine = Engine(root, object())
                engine.load = lambda *_: Pipeline()
                request = {"job_id":"test", "job_dir":str(root), "cancel_file":str(root/"cancel"),
                           "spec":{"mode":"control", "control_image":str(image),
                                   "control_adapter":{"path":"synthetic"}, "prompt":"portrait",
                                   "control_reference_kv_cache":failure is not None,
                                   "control_reference_size":512,
                                   "width":512,"height":512,"steps":1,"seed":5,"image_count":2 if failure is None else 1,
                                   "loras":[],"strength":.6,"safety_enabled":False}}
                modules = {"backend.krea2.lokr_mlx":types.SimpleNamespace(LoKrBinding=Binding),
                           "backend.krea2.control_mlx":types.SimpleNamespace(generate_control=generate_control)}
                with patch.dict(sys.modules, modules), patch("backend.krea2.worker.emit") as emitted:
                    if failure:
                        with self.assertRaises(type(failure)): engine.run(request)
                    else:
                        result=engine.run(request)
                        self.assertEqual(result["mode"], "control")
                        self.assertEqual(len(result["control_acceleration"]),2)
                        self.assertTrue(result["control_acceleration"][0]["invariant_cache"])
                    self.assertEqual(events, ["ordinary_loras","bind"]+["control"]*(2 if failure is None else 1)+["clear"])
                    self.assertIsNone(engine.control_binding)
                    ratios=[call.kwargs["ratio"] for call in emitted.call_args_list if "ratio" in call.kwargs]
                    self.assertEqual(ratios,sorted(ratios),"control progress must not move backwards")
                    request["spec"].update(mode="standard",control_image=None,control_adapter=None,image_count=1)
                    self.assertEqual(engine.run(request)["mode"], "standard")
                    self.assertEqual(events[-2:], ["ordinary_loras","standard"])

    def test_worker_rejects_joint_edit_before_loading_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            engine = Engine(root, object())
            engine.load = lambda *_: self.fail("invalid request loaded model")
            with self.assertRaisesRegex(ValueError, "联合编辑"):
                engine.run({"job_id":"test", "job_dir":str(root), "cancel_file":str(root/"cancel"),
                            "spec":{"mode":"control", "edit_image":"photo"}})


if __name__ == "__main__":
    unittest.main()
