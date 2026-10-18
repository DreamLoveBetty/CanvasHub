"""Worker-only area-conditioned Krea inference, separate from Identity Edit.

Contract reference: lrzjason/ComfyUI-EditUtils fd87e4c5fdb36032ff129c9d78ee5c1cd6ff30d9.
Sequence [text,target,reference]; reference timestep zero; centre-aligned RoPE.
No monkeypatching, implicit Identity adapter or source photo. Frozen-reference
KV acceleration is explicit and defaults off; exact constants are always cached.
"""
from __future__ import annotations

from dataclasses import dataclass
import mlx.core as mx
import numpy as np
from PIL import Image

from .edit_mlx import encode_grounded_image
from .control_profile import prepare_control_images


def control_positions(text_length, target_grid, reference_grid):
    th, tw = target_grid
    rh, rw = reference_grid
    target = np.zeros((th, tw, 3), dtype=np.float32)
    target[..., 1] = np.arange(th)[:, None]
    target[..., 2] = np.arange(tw)[None, :]
    reference = np.ones((rh, rw, 3), dtype=np.float32)
    reference[..., 1] = (np.arange(rh)[:, None] + .5) * th / rh - .5
    reference[..., 2] = (np.arange(rw)[None, :] + .5) * tw / rw - .5
    return mx.array(np.concatenate([np.zeros((text_length, 3), np.float32),
                                    target.reshape(-1, 3), reference.reshape(-1, 3)]))


@dataclass
class PreparedControl:
    """Constants owned by one image generation, after all adapters are applied."""
    model: object
    text: object
    reference: object
    clean_mod: object
    cos: object
    sin: object
    target_length: int


def prepare_control_forward(model, reference, context, positions, target_length):
    from krea2.transformer import _make_rope, _timestep_embed

    clean = model.first(reference)
    text = model._run_seq(model.txtmlp, model.txtfusion(context, mask=None))
    zero = model._run_seq(model.tmlp, _timestep_embed(
        mx.zeros((reference.shape[0],), dtype=reference.dtype), model.cfg.tdim).astype(clean.dtype))
    clean_mod = model._run_seq(model.tproj, zero)
    cos, sin = _make_rope(positions, model.axes, model.cfg.theta)
    # Materialize once instead of retaining and re-evaluating the constant graph
    # at every denoise step. No arrays survive this image's generate call.
    mx.eval(text, clean, clean_mod, cos, sin)
    return PreparedControl(model, text, clean, clean_mod, cos, sin, target_length)


def control_forward(model, target, reference, context, timestep, positions, *,
                    prepared=None, reference_cache=None):
    from krea2.transformer import _make_rope, _timestep_embed

    image = model.first(target)
    if prepared is None:  # Original full path retained for local A/B verification.
        clean = model.first(reference)
        text = model._run_seq(model.txtmlp, model.txtfusion(context, mask=None))
        zero = model._run_seq(model.tmlp, _timestep_embed(mx.zeros_like(timestep), model.cfg.tdim).astype(image.dtype))
        clean_mod = model._run_seq(model.tproj, zero)
        cos, sin = _make_rope(positions, model.axes, model.cfg.theta)
    else:
        if prepared.model is not model or target.shape[1] != prepared.target_length:
            raise ValueError("区域控制准备状态与模型或目标长度不一致")
        text, clean, clean_mod = prepared.text, prepared.reference, prepared.clean_mod
        cos, sin = prepared.cos, prepared.sin
    capture = reference_cache.begin_step() if reference_cache is not None else False
    reuse = reference_cache is not None and not capture
    if reference_cache is not None and prepared is None:
        raise ValueError("参考 KV 加速需要当前图像的准备状态")
    states = mx.concatenate([text, image] if reuse else [text, image, clean], axis=1)
    real = model._run_seq(model.tmlp, _timestep_embed(timestep, model.cfg.tdim).astype(image.dtype))
    real_mod = model._run_seq(model.tproj, real)
    target_end = text.shape[1] + target.shape[1]
    modulation = mx.broadcast_to(real_mod, (states.shape[0], target_end, real_mod.shape[-1]))
    if not reuse:
        modulation = mx.concatenate([modulation,
            mx.broadcast_to(clean_mod, (states.shape[0], reference.shape[1], clean_mod.shape[-1]))], axis=1)
    if prepared is None:
        for block in model.blocks:
            states = block(states, modulation, cos, sin, None)
    else:
        from .control_attention_mlx import reference_block
        if reuse:
            cos, sin = cos[:target_end], sin[:target_end]
        for layer, block in enumerate(model.blocks):
            states = reference_block(block, states, modulation, cos, sin, reference_cache, layer, capture)
        if reference_cache is not None:
            reference_cache.finish_step(capture)
    return model.last(states[:, text.shape[1]:target_end], real)


def denoise_control(model, target, reference, context, positions, schedule, *,
                    prepared, reference_kv_cache=False, step_callback=None):
    """Own the cache for exactly one image, never a warm worker or batch."""
    from .control_attention_mlx import ReferenceKV

    cache = ReferenceKV(reference.shape[1], len(model.blocks)) if reference_kv_cache else None
    try:
        for index, (current, following) in enumerate(zip(schedule[:-1], schedule[1:]), 1):
            velocity = control_forward(model, target, reference, context,
                mx.full((target.shape[0],), current, dtype=target.dtype), positions,
                prepared=prepared, reference_cache=cache)
            target = target + (following-current)*velocity
            # Include compact cached slices in the same eval: no deferred first
            # step graphs may be recomputed when the next step reads the cache.
            mx.eval(target, *(cache.arrays if cache is not None else []))
            if not bool(mx.all(mx.isfinite(target)).item()):
                raise ValueError("区域控制推理产生非有限值")
            if step_callback:
                step_callback(index, len(schedule)-1)
        metadata = {"implementation": "control-cache-v2-gqa", "invariant_cache": prepared is not None,
                    "attention": "native_gqa" if prepared is not None else "upstream",
                    "reference_kv_cache": cache is not None, "cache_scope": "per_image",
                    "reference_kv": cache.report() if cache is not None else None}
        return target, metadata
    finally:
        if cache is not None:
            cache.clear()


def generate_control(pipe, prompt, *, control_image, text_encoder_path,
                     width, height, steps, seed, step_callback=None, phase_callback=None,
                     reference_kv_cache=False, reference_size=1024, diagnostics=None):
    from krea2.sampling import patchify, unpatchify, timesteps, to_pil
    from mflux.models.common.vae.vae_util import VAEUtil
    from mflux.utils.image_util import ImageUtil

    report = phase_callback or (lambda *_: None)
    with Image.open(control_image) as opened:
        image = opened.convert("RGB")
    if image.size != (width, height):
        raise ValueError("控制图与输出尺寸不一致")
    reference_image, vision_image = prepare_control_images(image, reference_size)
    context, _ = encode_grounded_image(
        pipe.encoder, prompt, vision_image, text_encoder_path, grounding_px=0,
        image_label="Picture 1: ", phase_callback=report)
    report(.75, "编码区域控制图")
    latent = VAEUtil.encode(vae=pipe.vae, image=ImageUtil.to_array(reference_image))
    if latent.ndim == 5 and latent.shape[2] == 1:
        latent = latent[:, :, 0]
    patch, compression = pipe.transformer.cfg.patch, pipe.vae.spatial_scale
    reference = patchify(latent.astype(mx.bfloat16), patch)
    lh, lw = height // compression, width // compression
    mx.random.seed(seed)
    noise = mx.random.normal((1, pipe.vae.latent_channels, lh, lw)).astype(mx.bfloat16)
    target = patchify(noise, patch)
    positions = control_positions(context.shape[1], (lh//patch, lw//patch),
                                  (latent.shape[-2]//patch, latent.shape[-1]//patch))
    align = compression * patch
    schedule = timesteps(target.shape[1], steps, (256//align)**2, (1280//align)**2)
    prepared = prepare_control_forward(pipe.transformer, reference, context, positions, target.shape[1])
    report(1, "区域条件准备完成")
    target, acceleration = denoise_control(pipe.transformer, target, reference, context,
        positions, schedule, prepared=prepared, reference_kv_cache=reference_kv_cache,
        step_callback=step_callback)
    if diagnostics is not None:
        diagnostics.update(acceleration)
        diagnostics.update(reference_size=reference_size, reference_dimensions=list(reference_image.size),
                           reference_tokens=reference.shape[1], target_tokens=target.shape[1])
    output = unpatchify(target, patch, lh//patch, lw//patch, pipe.vae.latent_channels)
    decoded = mx.clip(pipe.vae.decode(output.astype(mx.float32)), -1, 1) * .5 + .5
    decoded = decoded[:, :, 0]
    mx.eval(decoded)
    return to_pil(decoded)
