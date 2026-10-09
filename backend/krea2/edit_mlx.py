"""Worker-only native MLX runtime for Krea 2 instruction editing.

The released identity-edit adapters are not ordinary img2img LoRAs.  They were
trained with two source-image paths at once:

* image-grounded Qwen3-VL instruction features (semantic grounding), and
* clean VAE source tokens prepended to the noisy target tokens (appearance).

This module adds those paths around the pinned ``krea2_alis_mlx`` pipeline.  It
is imported only by ``worker.py`` after that source tree is on ``sys.path``;
the CanvasHub HTTP process therefore remains free of MLX imports.

The reference sequence and v1.2 fit geometry follow the Apache-2.0
``lbouaraba/comfyui-krea2edit`` implementation.  The native Qwen3-VL vision and
MRoPE structure was cross-checked against the MIT ``dmlsrc/KinoMLX`` port.
"""
from __future__ import annotations

from dataclasses import dataclass
import gc
import math
from pathlib import Path

import mlx.core as mx
from mlx import nn
import numpy as np
from PIL import Image

try:  # Script execution in the optional shared runtime.
    from edit_profile import reference_geometry
except ImportError:  # Package import in tests/development.
    from .edit_profile import reference_geometry


_DEFAULT_SYSTEM = (
    "Describe the image by detailing the color, shape, size, texture, quantity, "
    "text, spatial relationships of the objects and background:"
)
_PREFIX = f"<|im_start|>system\n{_DEFAULT_SYSTEM}<|im_end|>\n<|im_start|>user\n"
_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n"
_IMAGE_TOKEN_ID = 151655
_SELECT_LAYERS = (2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35)


@dataclass(frozen=True)
class _VisualFeatures:
    embeddings: mx.array
    deepstack: tuple[mx.array, ...]
    grid: tuple[int, int]


@dataclass(frozen=True)
class _ImageSpan:
    start: int
    features: _VisualFeatures

    @property
    def length(self):
        return self.features.grid[0] * self.features.grid[1]


class _VisionNorm(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.weight = mx.ones((width,), dtype=mx.bfloat16)
        self.bias = mx.zeros((width,), dtype=mx.bfloat16)

    def __call__(self, value):
        return mx.fast.layer_norm(value, self.weight, self.bias, 1e-6)


def _vision_gelu(value, approximate):
    if approximate:
        return 0.5 * value * (1 + mx.tanh(
            math.sqrt(2 / math.pi) * (value + 0.044715 * value**3)))
    return 0.5 * value * (1 + mx.erf(value / math.sqrt(2)))


class _VisionMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.linear_fc1 = nn.Linear(1024, 4096, bias=True)
        self.linear_fc2 = nn.Linear(4096, 1024, bias=True)

    def __call__(self, value):
        return self.linear_fc2(_vision_gelu(self.linear_fc1(value), True))


class _VisionAttention(nn.Module):
    def __init__(self):
        super().__init__()
        self.heads = 16
        self.head_dim = 64
        self.qkv = nn.Linear(1024, 3072, bias=True)
        self.proj = nn.Linear(1024, 1024, bias=True)

    def __call__(self, value, phases):
        length, width = value.shape
        qkv = self.qkv(value).reshape(length, 3, self.heads, self.head_dim)
        query, key, projected = (
            qkv[:, index].transpose(1, 0, 2)[None] for index in range(3))
        cos, sin = mx.cos(phases)[None, None], mx.sin(phases)[None, None]

        def rotate(item):
            first, last = mx.split(item.astype(mx.float32), 2, axis=-1)
            rotated = mx.concatenate([-last, first], axis=-1)
            return (item.astype(mx.float32) * cos + rotated * sin).astype(item.dtype)

        attended = mx.fast.scaled_dot_product_attention(
            rotate(query), rotate(key), projected, scale=self.head_dim**-0.5)
        return self.proj(attended[0].transpose(1, 0, 2).reshape(length, width))


class _VisionBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.norm1 = _VisionNorm(1024)
        self.norm2 = _VisionNorm(1024)
        self.attn = _VisionAttention()
        self.mlp = _VisionMLP()

    def __call__(self, value, phases):
        value = value + self.attn(self.norm1(value), phases)
        return value + self.mlp(self.norm2(value))


class _VisionMerger(nn.Module):
    def __init__(self, postshuffle):
        super().__init__()
        self.postshuffle = bool(postshuffle)
        self.norm = _VisionNorm(4096 if self.postshuffle else 1024)
        self.linear_fc1 = nn.Linear(4096, 4096, bias=True)
        self.linear_fc2 = nn.Linear(4096, 2560, bias=True)

    def __call__(self, value):
        if self.postshuffle:
            value = value.reshape(-1, 4096)
        value = self.norm(value).reshape(-1, 4096)
        return self.linear_fc2(_vision_gelu(self.linear_fc1(value), False))


class _PatchEmbed(nn.Module):
    def __init__(self):
        super().__init__()
        self.proj = nn.Linear(1536, 1024, bias=True)


def _vision_grid_positions(height, width):
    if min(height, width) <= 0 or height % 2 or width % 2:
        raise ValueError("Qwen3-VL 视觉网格必须按 2 对齐")
    rows = mx.broadcast_to(mx.arange(height)[:, None], (height, width))
    columns = mx.broadcast_to(mx.arange(width)[None, :], (height, width))
    return (mx.stack([rows, columns], axis=-1)
            .reshape(height // 2, 2, width // 2, 2, 2)
            .transpose(0, 2, 1, 3, 4).reshape(-1, 2))


class _VisionModel(nn.Module):
    """Qwen3-VL still-image tower; one source image per forward."""

    def __init__(self):
        super().__init__()
        self.patch_embed = _PatchEmbed()
        self.pos_embed = nn.Embedding(2304, 1024)
        self.blocks = [_VisionBlock() for _ in range(24)]
        self.merger = _VisionMerger(False)
        self.deepstack_merger_list = [_VisionMerger(True) for _ in range(3)]

    def __call__(self, patches, grid):
        height, width = grid
        positions = _vision_grid_positions(height, width)
        expected = (height * width, 1536)
        if tuple(patches.shape) != expected:
            raise ValueError(f"Qwen3-VL 视觉 patch 形状 {patches.shape}，期望 {expected}")
        value = self.patch_embed.proj(patches)
        side = 48
        coordinates = positions.astype(mx.float32) * mx.array([
            (side - 1) / max(height - 1, 1),
            (side - 1) / max(width - 1, 1),
        ])
        low = mx.floor(coordinates).astype(mx.int32)
        high = mx.minimum(low + 1, side - 1)
        weight = coordinates - low
        positional = mx.zeros(value.shape, dtype=mx.float32)
        for y in range(2):
            for x in range(2):
                row = low[:, 0] if y == 0 else high[:, 0]
                column = low[:, 1] if x == 0 else high[:, 1]
                factor = (1 - weight[:, 0] if y == 0 else weight[:, 0]) * (
                    1 - weight[:, 1] if x == 0 else weight[:, 1])
                positional = positional + self.pos_embed(
                    row * side + column).astype(mx.float32) * factor[:, None]
        value = value + positional.astype(value.dtype)
        frequency = 1 / (10000 ** (mx.arange(
            0, 32, 2, dtype=mx.float32) / 32))
        angles = (positions[..., None] * frequency).reshape(height * width, -1)
        phases = mx.concatenate([angles, angles], axis=-1)
        deepstack = []
        for index, block in enumerate(self.blocks):
            value = block(value, phases)
            if index in (5, 11, 17):
                deepstack.append(self.deepstack_merger_list[len(deepstack)](value))
        embeddings = self.merger(value)
        mx.eval(embeddings, deepstack)
        return _VisualFeatures(
            embeddings=embeddings,
            deepstack=tuple(deepstack),
            grid=(height // 2, width // 2),
        )


def _load_vision_model(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise RuntimeError("Krea 2 文本编码器文件缺失，无法载入视觉塔")
    model = _VisionModel()
    weights = mx.load(str(path))
    selected = []
    for key, value in weights.items():
        if not key.startswith("visual."):
            continue
        target = key[len("visual."):]
        if target == "patch_embed.proj.weight":
            value = value.reshape(value.shape[0], -1)
        selected.append((target, value.astype(mx.bfloat16)))
    if len(selected) != 315:
        raise RuntimeError(f"Krea 2 Qwen3-VL 视觉权重不完整：{len(selected)}/315")
    model.load_weights(selected, strict=True)
    weights.clear()
    mx.eval(model.parameters())
    return model


def _grounding_patches(image, longest_side=768):
    image = image.convert("RGB")
    height, width = image.height, image.width
    if longest_side and max(height, width) > longest_side:
        scale = longest_side / max(height, width)
        height, width = max(1, round(height * scale)), max(1, round(width * scale))
        image = image.resize((width, height), Image.Resampling.BOX)
    resized_height = max(32, round(height / 32) * 32)
    resized_width = max(32, round(width / 32) * 32)
    if resized_height * resized_width < 3136:
        scale = math.sqrt(3136 / (height * width))
        resized_height = max(32, math.ceil(height * scale / 32) * 32)
        resized_width = max(32, math.ceil(width * scale / 32) * 32)
    elif resized_height * resized_width > 12_845_056:
        # Qwen3-VL's own processor caps the patch canvas as well.  This mostly
        # protects grounding_px=0 on a very large camera original.
        scale = math.sqrt(height * width / 12_845_056)
        resized_height = max(32, math.floor(height / scale / 32) * 32)
        resized_width = max(32, math.floor(width / scale / 32) * 32)
    image = image.resize((resized_width, resized_height), Image.Resampling.BILINEAR)
    pixels = np.asarray(image, dtype=np.float32)[None] / 255.0
    pixels = mx.array(pixels) * 2 - 1
    grid_height, grid_width = resized_height // 16, resized_width // 16
    frames = mx.repeat(pixels.transpose(0, 3, 1, 2), 2, axis=0)
    patches = frames.reshape(
        1, 2, 3, grid_height // 2, 2, 16, grid_width // 2, 2, 16)
    patches = patches.transpose(0, 3, 6, 4, 7, 2, 1, 5, 8).reshape(
        grid_height * grid_width, 1536)
    return patches.astype(mx.bfloat16), (grid_height, grid_width)


def _multimodal_positions(length, spans):
    cursor = 0
    offset = 0
    pieces = []
    for span in spans:
        height, width = span.features.grid
        if span.start < cursor or span.start + span.length > length:
            raise ValueError("Qwen3-VL 图片 token 区间无效")
        text_length = span.start - cursor
        text = mx.arange(text_length, dtype=mx.int32) + offset
        pieces.append(mx.broadcast_to(text[None], (3, text_length)))
        offset += text_length
        row = mx.repeat(mx.arange(height, dtype=mx.int32), width)
        column = mx.tile(mx.arange(width, dtype=mx.int32), height)
        pieces.append(mx.stack([mx.zeros_like(row), row, column]) + offset)
        offset += max(height, width)
        cursor = span.start + span.length
    tail = mx.arange(length - cursor, dtype=mx.int32) + offset
    pieces.append(mx.broadcast_to(tail[None], (3, length - cursor)))
    return mx.concatenate(pieces, axis=1)[:, None, :]


def _mrope(hidden, position_ids):
    head_dim = 128
    inv = 1.0 / (5_000_000.0 ** (
        mx.arange(0, head_dim, 2, dtype=mx.float32) / head_dim))
    frequencies = position_ids.astype(mx.float32)[..., None] * inv[None, None, None, :]
    selector = [0] * (head_dim // 2)
    for axis, start, count in ((1, 1, 20), (2, 2, 20)):
        for index in range(start, count * 3, 3):
            selector[index] = axis
    selector = mx.array(selector, dtype=mx.int32)[None, None, :]
    selected = mx.where(
        selector == 1, frequencies[1],
        mx.where(selector == 2, frequencies[2], frequencies[0]))
    embedding = mx.concatenate([selected, selected], axis=-1)
    # The pinned text graph accepts a shared (sequence, head_dim) table.
    return (mx.cos(embedding)[0].astype(hidden.dtype),
            mx.sin(embedding)[0].astype(hidden.dtype))


def _grounded_context(encoder, prompt, image, text_encoder_path, grounding_px,
                      phase_callback):
    phase_callback(0.08, "载入 Qwen3-VL 视觉塔")
    vision = _load_vision_model(text_encoder_path)
    try:
        phase_callback(0.22, "识别编辑源图语义")
        patches, grid = _grounding_patches(image, grounding_px)
        features = vision(patches, grid)
    finally:
        del vision
        gc.collect()
        mx.clear_cache()

    tokenizer = encoder.tokenizer
    prefix_ids = tokenizer.encode(_PREFIX, add_special_tokens=False)
    suffix_ids = tokenizer.encode(_SUFFIX, add_special_tokens=False)
    prompt_ids = tokenizer.encode(str(prompt), add_special_tokens=False)
    prompt_ids = prompt_ids[:max(0, 512 - len(suffix_ids))]
    vision_start = tokenizer.encode("<|vision_start|>", add_special_tokens=False)
    vision_end = tokenizer.encode("<|vision_end|>", add_special_tokens=False)
    tokens = list(prefix_ids) + list(vision_start)
    span = _ImageSpan(len(tokens), features)
    tokens.extend([_IMAGE_TOKEN_ID] * span.length)
    tokens.extend(vision_end)
    tokens.extend(prompt_ids)
    tokens.extend(suffix_ids)
    input_ids = mx.array([tokens], dtype=mx.int32)
    positions = _multimodal_positions(len(tokens), (span,))

    phase_callback(0.52, "编码图片语义与编辑指令")
    model = encoder.model
    hidden = model.embed_tokens(input_ids)
    hidden = mx.concatenate([
        hidden[:, :span.start],
        features.embeddings.astype(hidden.dtype)[None],
        hidden[:, span.start + span.length:],
    ], axis=1)
    cos, sin = _mrope(hidden, positions)
    length = len(tokens)
    indexes = mx.arange(length)
    causal = (indexes[None, :] > indexes[:, None]).astype(mx.float32) * -1e9
    mask = causal[None, None].astype(hidden.dtype)
    selected = []
    selected_set = frozenset(_SELECT_LAYERS)
    for completed, layer in enumerate(model.layers, start=1):
        hidden = layer(hidden, cos, sin, mask)
        if completed <= len(features.deepstack):
            hidden = hidden.at[0, span.start:span.start + span.length].add(
                features.deepstack[completed - 1].astype(hidden.dtype))
        if completed in selected_set:
            selected.append(hidden)
    if len(selected) != len(_SELECT_LAYERS):
        raise RuntimeError("Krea 2 grounded Qwen 未产生完整隐藏层")
    stacked = mx.stack(selected, axis=2)[:, len(prefix_ids):]
    valid = mx.ones(stacked.shape[:2], dtype=mx.float32)
    mx.eval(stacked, valid)
    del span, features, hidden, selected
    gc.collect()
    mx.clear_cache()
    return stacked.astype(mx.bfloat16), valid


def _encode_reference(vae, image, width, height, fit_mode):
    from mflux.models.common.vae.vae_util import VAEUtil
    from mflux.utils.image_util import ImageUtil

    geometry = reference_geometry(
        image.width, image.height, width, height, fit_mode)
    cropped = image.crop((
        geometry.crop_left,
        geometry.crop_top,
        geometry.crop_left + geometry.crop_width,
        geometry.crop_top + geometry.crop_height,
    ))
    fitted = cropped.resize(
        (geometry.output_width, geometry.output_height), Image.Resampling.BICUBIC)
    latent = VAEUtil.encode(vae=vae, image=ImageUtil.to_array(fitted))
    if latent.ndim == 5 and latent.shape[2] == 1:
        latent = latent[:, :, 0]
    expected = (geometry.output_height // 8, geometry.output_width // 8)
    if tuple(latent.shape[-2:]) != expected:
        raise RuntimeError(
            f"Krea 2 编辑源 latent 形状 {latent.shape[-2:]}，期望 {expected}")
    mx.eval(latent)
    return latent, geometry


def _reference_attention(attention, states, cos, sin, target_start, key_bias):
    """Krea attention with a linear-size target-to-reference logit bias."""
    from krea2.transformer import _apply_rope

    batch, length, _ = states.shape
    queries = attention.wq(states).reshape(
        batch, length, attention.heads, attention.headdim).transpose(0, 2, 1, 3)
    keys = attention.wk(states).reshape(
        batch, length, attention.kvheads, attention.headdim).transpose(0, 2, 1, 3)
    values = attention.wv(states).reshape(
        batch, length, attention.kvheads, attention.headdim).transpose(0, 2, 1, 3)
    gate = attention.gate(states)
    queries = _apply_rope(attention.qknorm.qnorm(queries), cos, sin)
    keys = _apply_rope(attention.qknorm.knorm(keys), cos, sin)
    if attention.kvheads != attention.heads:
        repeat = attention.heads // attention.kvheads
        keys = mx.repeat(keys, repeat, axis=1)
        values = mx.repeat(values, repeat, axis=1)
    prefix = mx.fast.scaled_dot_product_attention(
        queries[:, :, :target_start], keys, values, scale=attention.scale)
    target = mx.fast.scaled_dot_product_attention(
        queries[:, :, target_start:], keys, values, scale=attention.scale,
        mask=key_bias.astype(queries.dtype)[None, None, None, :])
    output = mx.concatenate([prefix, target], axis=2)
    output = output.transpose(0, 2, 1, 3).reshape(
        batch, length, attention.heads * attention.headdim)
    return attention.wo(output * mx.sigmoid(gate))


def _edit_forward(transformer, target_tokens, source_tokens, context, timestep,
                  positions, reference_strength):
    from krea2.transformer import _make_rope, _timestep_embed

    image_tokens = mx.concatenate([source_tokens, target_tokens], axis=1)
    image_projection = transformer.first(image_tokens)
    time_embedding = transformer._run_seq(
        transformer.tmlp,
        _timestep_embed(timestep, transformer.cfg.tdim).astype(image_projection.dtype),
    )
    time_modulation = transformer._run_seq(transformer.tproj, time_embedding)
    text_length = context.shape[1]
    source_length = source_tokens.shape[1]
    fused = transformer.txtfusion(context, mask=None)
    text_projection = transformer._run_seq(transformer.txtmlp, fused)
    combined = mx.concatenate([text_projection, image_projection], axis=1)
    cos, sin = _make_rope(positions.astype(mx.float32), transformer.axes, transformer.cfg.theta)
    target_start = text_length + source_length
    strength = max(float(reference_strength), 1e-4)
    if abs(strength - 1.0) < 1e-9:
        for block in transformer.blocks:
            combined = block(combined, time_modulation, cos, sin, None)
    else:
        key_bias = mx.zeros((combined.shape[1],), dtype=mx.float32)
        key_bias = key_bias.at[text_length:target_start].add(math.log(strength))
        for block in transformer.blocks:
            prescale, preshift, pregate, postscale, postshift, postgate = block.mod(
                time_modulation)
            attention_input = ((1 + prescale) * block.prenorm(combined) + preshift)
            combined = combined + pregate * _reference_attention(
                block.attn, attention_input, cos, sin, target_start, key_bias)
            combined = combined + postgate * block.mlp(
                (1 + postscale) * block.postnorm(combined) + postshift)
    final = transformer.last(combined, time_embedding)
    return final[:, target_start:target_start + target_tokens.shape[1], :]


def _edit_positions(text_length, geometry, target_height, target_width):
    source_height, source_width = geometry.token_height, geometry.token_width
    target_grid_height, target_grid_width = target_height // 16, target_width // 16
    text = np.zeros((text_length, 3), dtype=np.float32)
    source = np.zeros((source_height, source_width, 3), dtype=np.float32)
    source[..., 0] = 1
    source[..., 1] = np.arange(source_height, dtype=np.float32)[:, None] + geometry.offset_y
    source[..., 2] = np.arange(source_width, dtype=np.float32)[None, :] + geometry.offset_x
    target = np.zeros((target_grid_height, target_grid_width, 3), dtype=np.float32)
    target[..., 1] = np.arange(target_grid_height, dtype=np.float32)[:, None]
    target[..., 2] = np.arange(target_grid_width, dtype=np.float32)[None, :]
    return mx.array(np.concatenate([
        text, source.reshape(-1, 3), target.reshape(-1, 3)], axis=0))


def generate_edit(pipe, prompt, *, source_image, text_encoder_path, width=1024,
                  height=1024, steps=8, seed=0, reference_strength=4.0,
                  grounding_px=768, fit_mode="fit", step_callback=None,
                  phase_callback=None):
    """Generate one instruction-edited image through the existing warm pipeline."""
    from krea2.sampling import patchify, timesteps, to_pil, unpatchify

    report = phase_callback or (lambda _ratio, _stage: None)
    source_path = Path(source_image).resolve()
    if not source_path.is_file():
        raise ValueError("Krea 2 编辑源图不存在")
    width, height, steps, seed = int(width), int(height), int(steps), int(seed)
    if width % 16 or height % 16 or min(width, height) < 256:
        raise ValueError("Krea 2 编辑尺寸必须是不小于 256 的 16 倍数")
    if not 1 <= steps <= 50:
        raise ValueError("Krea 2 编辑步数必须在 1–50 之间")
    if grounding_px and (grounding_px < 256 or grounding_px > 2048 or grounding_px % 32):
        raise ValueError("Krea 2 语义识图尺寸必须为 0 或 256–2048 的 32 倍数")

    report(0.02, "读取 Krea 2 编辑源图")
    with Image.open(source_path) as opened:
        source = opened.convert("RGB").copy()
    context, _mask = _grounded_context(
        pipe.encoder, prompt, source, text_encoder_path, grounding_px, report)
    report(0.72, "按输出画幅编码参考图")
    source_latent, geometry = _encode_reference(
        pipe.vae, source, width, height, fit_mode)
    source_tokens = patchify(source_latent.astype(mx.bfloat16), pipe.transformer.cfg.patch)

    compression = pipe.vae.spatial_scale
    latent_height, latent_width = height // compression, width // compression
    mx.random.seed(seed)
    noise = mx.random.normal((
        1, pipe.vae.latent_channels, latent_height, latent_width)).astype(mx.bfloat16)
    target_tokens = patchify(noise, pipe.transformer.cfg.patch)
    positions = _edit_positions(context.shape[1], geometry, height, width)
    expected = context.shape[1] + source_tokens.shape[1] + target_tokens.shape[1]
    if positions.shape[0] != expected:
        raise RuntimeError("Krea 2 编辑 RoPE 序列与 token 数量不一致")

    align = compression * pipe.transformer.cfg.patch
    sequence = (latent_height // pipe.transformer.cfg.patch) * (
        latent_width // pipe.transformer.cfg.patch)
    schedule = timesteps(
        sequence, steps, (256 // align) ** 2, (1280 // align) ** 2)
    report(1.0, "双路条件准备完成，开始编辑")
    pairs = list(zip(schedule[:-1], schedule[1:]))
    for index, (current, previous) in enumerate(pairs, 1):
        timestep = mx.full((1,), current, dtype=mx.bfloat16)
        velocity = _edit_forward(
            pipe.transformer, target_tokens, source_tokens, context, timestep,
            positions, reference_strength)
        target_tokens = target_tokens + (previous - current) * velocity
        mx.eval(target_tokens)
        if step_callback is not None:
            step_callback(index, len(pairs))

    latent = unpatchify(
        target_tokens, pipe.transformer.cfg.patch,
        latent_height // pipe.transformer.cfg.patch,
        latent_width // pipe.transformer.cfg.patch,
        pipe.vae.latent_channels,
    )
    decoded = pipe.vae.decode(latent.astype(mx.float32))
    decoded = mx.clip(decoded, -1, 1) * 0.5 + 0.5
    decoded = decoded[:, :, 0]
    mx.eval(decoded)
    return to_pil(decoded)


__all__ = ["generate_edit"]
