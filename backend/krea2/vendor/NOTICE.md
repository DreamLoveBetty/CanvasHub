# Krea 2 edit runtime attributions

`backend/krea2/edit_profile.py` and `backend/krea2/edit_mlx.py` implement the
community Krea 2 instruction-edit conditioning protocol.

- The dual source-conditioning sequence, reference geometry, and reference
  attention semantics are adapted from
  [lbouaraba/comfyui-krea2edit](https://github.com/lbouaraba/comfyui-krea2edit),
  revision `86f886dac23013d88996e3a2e99093ba44d322fb`, licensed under Apache-2.0.
  The full license is in `LICENSE.comfyui-krea2edit`.
- The native MLX Qwen3-VL vision/MRoPE implementation was cross-checked against
  [dmlsrc/KinoMLX](https://github.com/dmlsrc/KinoMLX), revision
  `02711388f8c7e0a9415eb932f0a130ee87e42724`, licensed under MIT. The full
  license is in `LICENSE.kinomlx`.

The Identity Edit LoRA weights are user-supplied runtime assets and are not
bundled. Their separate model license continues to apply.

## Area-control protocol references

The independently implemented geometry/conditioning contract in `control_profile.py`
and `control_mlx.py` was checked against
[lrzjason/ComfyUI-EditUtils](https://github.com/lrzjason/ComfyUI-EditUtils), revision
`fd87e4c5fdb36032ff129c9d78ee5c1cd6ff30d9` (GPL-3.0), and its published
[area-control tutorial](https://lrzjason.github.io/ComfyUI-EditUtils/breast-size-control.html).
No ComfyUI plugin source is imported, executed or bundled by this runtime.
Direct full-factor LoKr semantics were cross-checked with
[ComfyUI's LoKr adapter](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/weight_adapter/lokr.py)
(GPL-3.0); the factorized matrix algebra is implemented locally and tested against
an explicit Kronecker product. These references do not supply or license user
weights; adapter/model licenses remain attached to those separately obtained files.


The optional cache in `control_attention_mlx.py` implements the same frozen-reference
approximation described by EditUtils' reference KV cache comments (above pinned
revision, `nodes.py` lines 4130 onward). It is a native image-scoped MLX execution
path, not a bundled/executed ComfyUI patch. Deeper reference K/V depend on live
targets, so caching them is not advertised as bit-exact. The uncached control path
remains available and is the default.

Native GQA uses MLX's documented SDPA API without pre-tiling K/V. It changes
neither model weights nor reference-cache ownership; full and cached area-control
paths share this kernel call. Standard and Identity Edit vendor paths are unchanged.
