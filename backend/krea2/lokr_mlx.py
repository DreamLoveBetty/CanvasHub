"""Worker-only reversible direct LoKr branch; never materializes kron(W1,W2).

For two full factors ComfyUI uses scale * kron(W1,W2), WITHOUT alpha/rank.
Alpha/rank applies only to decomposed variants, which our inspector rejects.
"""
from __future__ import annotations

import math
import mlx.core as mx
from mlx import nn

from .lokr import inspect_lokr


def factorized_delta(x, w1, w2):
    grouped = x.reshape(*x.shape[:-1], w1.shape[1], w2.shape[1])
    inner = grouped @ w2.T
    outer = mx.swapaxes(inner, -1, -2) @ w1.T
    return mx.swapaxes(outer, -1, -2).reshape(*x.shape[:-1], w1.shape[0] * w2.shape[0])


class LoKrLinear(nn.Module):
    def __init__(self, base, w1, w2, strength):
        super().__init__()
        self.base, self.w1, self.w2, self.strength = base, w1, w2, strength

    def __call__(self, x):
        value = self.base(x)
        # Cast the factors to the activation dtype, as in Comfy's bypass path.
        delta = factorized_delta(x, self.w1.astype(x.dtype), self.w2.astype(x.dtype))
        return value + (delta * self.strength).astype(value.dtype)


def _parent(model, path):
    parts = path.split(".")
    for part in parts[:-1]:
        model = model[int(part)] if part.isdigit() else getattr(model, part)
    return model, parts[-1]


def _get(parent, name):
    return parent[int(name)] if name.isdigit() else getattr(parent, name)


def _put(parent, name, value):
    if name.isdigit():
        parent[int(name)] = value
    else:
        setattr(parent, name, value)


class LoKrBinding:
    """Owns only its wrappers; ordinary LoRA lifecycle remains upstream-owned."""
    def __init__(self):
        self._swaps = []

    def clear(self):
        for parent, name, wrapped in reversed(self._swaps):
            if _get(parent, name) is wrapped:
                _put(parent, name, wrapped.base)
        self._swaps.clear()

    def apply(self, model, path, strength=1.0):
        if self._swaps:
            raise RuntimeError("请先卸载已有控制适配器")
        strength = float(strength)
        if not math.isfinite(strength) or not 0 <= strength <= 2:
            raise ValueError("LoKr 强度必须在 0–2 之间")
        report = inspect_lokr(path)
        if report is None:
            raise ValueError("控制适配器不是受支持的直接 LoKr")
        from krea2.lora import LoRALinear
        weights = mx.load(str(path))
        planned = []
        for target, group in report["layers"].items():
            try:
                parent, name = _parent(model, target)
                base = _get(parent, name)
            except (AttributeError, KeyError, IndexError) as exc:
                raise ValueError(f"LoKr 目标层不存在：{target}") from exc
            linear = base.base if isinstance(base, LoRALinear) else base
            if isinstance(linear, nn.QuantizedLinear):
                shape = [linear.scales.shape[0], linear.scales.shape[1] * linear.group_size]
            elif isinstance(linear, nn.Linear):
                shape = list(linear.weight.shape)
            else:
                raise ValueError(f"LoKr 目标不是线性层：{target}")
            if shape != group["shape"]:
                raise ValueError(f"LoKr 形状与 Base 不兼容：{target}")
            w1, w2 = weights[group["lokr_w1"]["key"]], weights[group["lokr_w2"]["key"]]
            # A NaN in an unused alpha is also rejected rather than silently accepted.
            arrays = [w1, w2] + ([weights[group["alpha"]["key"]]] if "alpha" in group else [])
            if not all(bool(mx.all(mx.isfinite(value)).item()) for value in arrays):
                raise ValueError(f"LoKr 包含非有限值：{target}")
            planned.append((parent, name, LoKrLinear(base, w1, w2, strength)))
        mx.eval([wrapped.parameters() for _, _, wrapped in planned])
        try:
            for parent, name, wrapped in planned:
                self._swaps.append((parent, name, wrapped))
                _put(parent, name, wrapped)
        except Exception:
            self.clear()
            raise
        return len(planned)
