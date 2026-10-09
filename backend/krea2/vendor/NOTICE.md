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
