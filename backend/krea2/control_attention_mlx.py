"""Worker-only native GQA with optional image-scoped frozen-reference cache.

No model monkeypatches or persistent warm-pipeline state. Capture stores K/V
after QK norm / RoPE with compact grouped-query heads. Subsequent steps
omit reference queries and MLPs. This is explicitly approximate at deeper layers.
"""
import mlx.core as mx


class ReferenceKV:
    def __init__(self, reference_tokens, layer_count):
        if reference_tokens < 1 or layer_count < 1:
            raise ValueError("参考 KV 尺寸无效")
        self.reference_tokens = reference_tokens
        self._layers = [None] * layer_count
        self.ready = False
        self.closed = False
        self.captures = self.reuses = 0

    @property
    def arrays(self):
        return [array for pair in self._layers if pair is not None for array in pair]

    def begin_step(self):
        if self.closed or (not self.ready and any(pair is not None for pair in self._layers)):
            raise ValueError("参考 KV 已释放或捕获不完整")
        return not self.ready

    def _slot(self, layer):
        if self.closed or not isinstance(layer, int) or not 0 <= layer < len(self._layers):
            raise ValueError("参考 KV 层索引无效")
        return self._layers[layer]

    def capture(self, layer, k, v):
        pair = self._slot(layer)
        if (self.ready or pair is not None or len(k.shape) != 4 or k.shape != v.shape
                or k.dtype != v.dtype or k.shape[2] < self.reference_tokens):
            raise ValueError("参考 KV 捕获形状或状态无效")
        # Compact tails instead of keeping views into whole live-sequence buffers.
        self._layers[layer] = (mx.contiguous(k[:, :, -self.reference_tokens:]),
                               mx.contiguous(v[:, :, -self.reference_tokens:]))

    def append(self, layer, k, v):
        pair = self._slot(layer)
        if not self.ready or pair is None:
            raise ValueError("参考 KV 尚未捕获完成")
        kk, vv = pair
        if (len(k.shape) != 4 or k.shape != v.shape or k.dtype != kk.dtype or v.dtype != vv.dtype
                or k.shape[:2] != kk.shape[:2] or k.shape[-1] != kk.shape[-1]):
            raise ValueError("参考 KV 与当前注意力形状或精度不一致")
        return mx.concatenate([k, kk], axis=2), mx.concatenate([v, vv], axis=2)

    def finish_step(self, capture):
        if self.closed or any(pair is None for pair in self._layers) or capture == self.ready:
            raise ValueError("参考 KV 捕获不完整或步骤状态无效")
        if capture:
            self.captures += 1
            self.ready = True
        else:
            self.reuses += 1

    def report(self):
        return {"reference_tokens": self.reference_tokens, "layers": len(self._layers),
                "capture_steps": self.captures, "reuse_steps": self.reuses,
                "cache_bytes": sum(array.nbytes for array in self.arrays)}

    def clear(self):
        self._layers = [None] * len(self._layers)
        self.ready = False
        self.closed = True


def _attention(attn, value, cos, sin, cache, layer, capture):
    from krea2.transformer import _apply_rope

    batch, length, _ = value.shape
    q = attn.wq(value).reshape(batch, length, attn.heads, attn.headdim).transpose(0, 2, 1, 3)
    k = attn.wk(value).reshape(batch, length, attn.kvheads, attn.headdim).transpose(0, 2, 1, 3)
    v = attn.wv(value).reshape(batch, length, attn.kvheads, attn.headdim).transpose(0, 2, 1, 3)
    gate = attn.gate(value)
    q, k = attn.qknorm.qnorm(q), attn.qknorm.knorm(k)
    q, k = _apply_rope(q, cos, sin), _apply_rope(k, cos, sin)
    if cache is not None:
        if capture:
            cache.capture(layer, k, v)
        else:
            k, v = cache.append(layer, k, v)
    # MLX SDPA natively groups query heads. Do not expand the K/V buffers.
    out = mx.fast.scaled_dot_product_attention(q, k, v, scale=attn.scale, mask=None)
    out = out.transpose(0, 2, 1, 3).reshape(batch, length, attn.heads * attn.headdim)
    return attn.wo(out * mx.sigmoid(gate))


def reference_block(block, states, modulation, cos, sin, cache, layer, capture):
    """Pinned block math with native GQA; optional image-scoped reference cache."""
    prescale, preshift, pregate, postscale, postshift, postgate = block.mod(modulation)
    states = states + pregate * _attention(
        block.attn, (1 + prescale) * block.prenorm(states) + preshift,
        cos, sin, cache, layer, capture)
    return states + postgate * block.mlp((1 + postscale) * block.postnorm(states) + postshift)
