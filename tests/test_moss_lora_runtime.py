"""Runtime coverage for turbo-style LoRA modules on a tiny DiT.

The conversion-header tests cannot catch moss-image-mlx 0.2.0 wrapping a
Linear as LoRALinear without exposing `.weight`. These cases use a temporary
safetensors file and the real `apply_lora`, then run a tiny forward pass.

MLX cases always execute in `components/moss/venv`. They fail (they are not
skipped) if that interpreter or moss_image_mlx is missing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
MOSS_VENV_PYTHON = ROOT / "components/moss/venv/bin/python"
CHILD_FLAG = "--child-mlx-apply-lora"
RESULT_PREFIX = "MOSS_LORA_RUNTIME_RESULT "
TINY = dict(dim=16, ffn_dim=32, num_heads=2, num_layers=1, text_dim=8, freq_dim=8, latent_channels=4)


def moss_venv_root():
    return (ROOT / "components/moss/venv").resolve()


def moss_venv_python():
    # Do not Path.resolve() the binary: the venv python is a symlink to Homebrew.
    python = MOSS_VENV_PYTHON
    if not python.is_file():
        raise AssertionError(
            f"MLX runtime test requires {python} and must not be skipped"
        )
    return python


def run_moss_child(case):
    python = moss_venv_python()
    env = os.environ.copy()
    env.pop("KMP_DUPLICATE_LIB_OK", None)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [str(python), str(Path(__file__).resolve()), CHILD_FLAG, case]
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise AssertionError(
            "moss venv child failed\n"
            f"cmd: {command}\nexit: {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    for line in (proc.stdout or "").splitlines():
        if line.startswith(RESULT_PREFIX):
            payload = json.loads(line[len(RESULT_PREFIX):])
            payload["_cmd"] = command
            payload["_venv_python"] = str(python)
            payload["_raw"] = output
            return payload
    raise AssertionError(
        "moss venv child produced no result line\n"
        f"cmd: {command}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def _aux_pairs():
    dim, text, freq, latent = TINY["dim"], TINY["text_dim"], TINY["freq_dim"], TINY["latent_channels"]
    return {
        "final_linear_video": (latent, dim),
        "shared_block_modulation": (6 * dim, dim),
        "text_embedder.proj": (dim, text),
        "time_embedding.0": (dim, freq),
        "time_embedding.1": (dim, dim),
        "video_head_modulation": (2 * dim, dim),
    }


def _write_lora(path, pairs, rank=2):
    import mlx.core as mx

    mx.random.seed(0)
    tensors = {}
    for name, (out, width) in pairs.items():
        tensors[f"diffusion_model.{name}.lora_down.weight"] = (
            mx.random.normal((rank, width)).astype(mx.bfloat16) * 0.02
        )
        tensors[f"diffusion_model.{name}.lora_up.weight"] = (
            mx.random.normal((out, rank)).astype(mx.bfloat16) * 0.02
        )
        tensors[f"diffusion_model.{name}.alpha"] = mx.array(float(rank), dtype=mx.float32)
    mx.save_safetensors(str(path), tensors)
    return list(pairs)


def _tiny_model():
    from moss_image_mlx.dit import MOSSImageTransformer

    return MOSSImageTransformer(**TINY)


def _forward(model):
    import mlx.core as mx
    import numpy as np

    latents = mx.zeros((1, TINY["latent_channels"], 2, 2), dtype=mx.float32)
    context = mx.zeros((1, 2, TINY["text_dim"]), dtype=mx.bfloat16)
    mod, head = model.modulation(1.0)
    out = model(latents, 1.0, context)
    mx.eval(mod, head, out)
    values = np.asarray(out.astype(mx.float32))
    if not bool(np.isfinite(values).all()):
        raise AssertionError("tiny forward produced non-finite values")
    return {
        "out_shape": list(out.shape),
        "mod_shape": list(mod.shape),
        "head_shape": list(head.shape),
        "finite": True,
    }


def _wrapped_names(model):
    from moss_image_mlx.lora import LoRALinear

    names = []
    for name, module in model.named_modules():
        if isinstance(module, LoRALinear):
            names.append(name)
            params = module.parameters()
            if "weight" in params:
                raise AssertionError(f"{name} registered a duplicate weight parameter")
            if module.weight is not module.base.weight:
                raise AssertionError(f"{name}.weight is not base.weight")
            if module.weight.dtype != module.base.weight.dtype:
                raise AssertionError(f"{name}.weight.dtype does not match the base linear")
    return names


def _child_aux_forward():
    from backend.moss.lora_compat import ensure_loralinear_weight
    from moss_image_mlx.lora import LoRALinear, apply_lora

    if "weight" in LoRALinear.__dict__:
        raise AssertionError("precondition: unpatched LoRALinear already defines weight")
    installed = ensure_loralinear_weight()
    if not installed or not isinstance(LoRALinear.__dict__.get("weight"), property):
        raise AssertionError("ensure_loralinear_weight did not install a property")
    model = _tiny_model()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "aux.safetensors"
        names = _write_lora(path, _aux_pairs())
        count = apply_lora(model, path, strength=1.0)
    if count != len(names):
        raise AssertionError(f"apply_lora wrapped {count} modules, expected {len(names)}")
    wrapped = _wrapped_names(model)
    expected = set(names)
    if set(wrapped) != expected:
        raise AssertionError(f"wrapped {wrapped}, expected {sorted(expected)}")
    result = _forward(model)
    result.update(wrapped=sorted(wrapped), applied=count, installed=installed)
    return result


def _child_layers_only():
    from backend.moss.lora_compat import ensure_loralinear_weight
    from moss_image_mlx.lora import LoRALinear, apply_lora
    import mlx.nn as nn

    ensure_loralinear_weight()
    model = _tiny_model()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "layer.safetensors"
        _write_lora(path, {"layers.0.proj.q": (TINY["dim"], TINY["dim"])})
        count = apply_lora(model, path, strength=1.0)
    if count != 1:
        raise AssertionError(f"expected one wrapped layer, got {count}")
    wrapped = _wrapped_names(model)
    if wrapped != ["layers.0.proj.q"]:
        raise AssertionError(f"ordinary path wrapped {wrapped}")
    if isinstance(model.time_embedding[0], LoRALinear):
        raise AssertionError("ordinary layers.* LoRA should leave time_embedding unwrapped")
    if not isinstance(model.time_embedding[0], nn.Linear):
        raise AssertionError("time_embedding[0] should remain a Linear")
    result = _forward(model)
    result.update(wrapped=wrapped, applied=count)
    return result


def _child_no_lora():
    from backend.moss.lora_compat import ensure_loralinear_weight
    from moss_image_mlx.lora import LoRALinear

    ensure_loralinear_weight()
    model = _tiny_model()
    if any(isinstance(module, LoRALinear) for _, module in model.named_modules()):
        raise AssertionError("no-LoRA path unexpectedly contained LoRALinear")
    result = _forward(model)
    result.update(wrapped=[], applied=0)
    return result


CHILD_CASES = {
    "aux_forward": _child_aux_forward,
    "layers_only": _child_layers_only,
    "no_lora": _child_no_lora,
}


def _run_child(case):
    if case not in CHILD_CASES:
        raise SystemExit(f"unknown child case: {case}")
    payload = CHILD_CASES[case]()
    payload["interpreter"] = sys.executable
    payload["prefix"] = sys.prefix
    payload["case"] = case
    print(RESULT_PREFIX + json.dumps(payload), flush=True)


class CompatHook(unittest.TestCase):
    def test_installs_property_that_forwards_to_base_weight(self):
        from backend.moss.lora_compat import ensure_loralinear_weight

        class Dummy:
            def __init__(self, weight):
                self.base = types.SimpleNamespace(weight=weight)

        sent = object()
        self.assertTrue(ensure_loralinear_weight(Dummy))
        self.assertIsInstance(Dummy.__dict__["weight"], property)
        self.assertIs(Dummy(sent).weight, sent)

    def test_second_call_is_idempotent_and_keeps_the_same_property(self):
        from backend.moss.lora_compat import ensure_loralinear_weight

        class Dummy:
            def __init__(self):
                self.base = types.SimpleNamespace(weight=1)

        self.assertTrue(ensure_loralinear_weight(Dummy))
        first = Dummy.__dict__["weight"]
        self.assertFalse(ensure_loralinear_weight(Dummy))
        self.assertIs(Dummy.__dict__["weight"], first)

    def test_does_not_override_an_existing_class_weight(self):
        from backend.moss.lora_compat import ensure_loralinear_weight

        class HasWeight:
            weight = "native"

        self.assertFalse(ensure_loralinear_weight(HasWeight))
        self.assertEqual(HasWeight.weight, "native")
        self.assertEqual(HasWeight.__dict__["weight"], "native")


class ApplyLoraRuntime(unittest.TestCase):
    def _run(self, case):
        payload = run_moss_child(case)
        self.assertEqual(Path(payload["prefix"]).resolve(), moss_venv_root())
        self.assertEqual(Path(payload["interpreter"]).resolve(), moss_venv_python().resolve())
        self.assertTrue(str(payload["interpreter"]).endswith("/components/moss/venv/bin/python"))
        self.assertEqual(payload["out_shape"], [1, TINY["latent_channels"], 2, 2])
        self.assertEqual(payload["mod_shape"], [1, 6, TINY["dim"]])
        self.assertEqual(payload["head_shape"], [1, 2, TINY["dim"]])
        self.assertTrue(payload["finite"])
        return payload

    def test_aux_modules_apply_lora_and_complete_a_tiny_forward(self):
        payload = self._run("aux_forward")
        expected = sorted(_aux_pairs())
        self.assertEqual(payload["wrapped"], expected)
        self.assertEqual(payload["applied"], len(expected))
        self.assertTrue(payload["installed"])

    def test_ordinary_layer_lora_still_forwards_without_wrapping_time_embedding(self):
        payload = self._run("layers_only")
        self.assertEqual(payload["wrapped"], ["layers.0.proj.q"])
        self.assertEqual(payload["applied"], 1)

    def test_unadapted_tiny_model_still_forwards(self):
        payload = self._run("no_lora")
        self.assertEqual(payload["wrapped"], [])
        self.assertEqual(payload["applied"], 0)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == CHILD_FLAG:
        _run_child(sys.argv[2])
    else:
        unittest.main()
