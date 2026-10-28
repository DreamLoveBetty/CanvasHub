# Third-party Notices

This file summarizes bundled third-party code and assets that are relevant for
open-source publication. The project-owned source code is licensed under the
root `LICENSE`; third-party code and assets remain under their own licenses.
This file is not a substitute for the full upstream license texts kept in the
referenced files.

## Browser / Frontend Runtime

| Component | Files | License / Notice |
| --- | --- | --- |
| Fabric.js 5.3.0 | `frontend/vendor/fabric.min.js` | MIT License. See `frontend/vendor/FABRIC_LICENSE.md`. |
| Fabric eraser mixin | `frontend/vendor/fabric-eraser.mixin.js` | Fabric.js ecosystem extension/mixin used by the image editor. See `frontend/vendor/FABRIC_LICENSE.md`. |
| Three.js r160 | `static/pose/three.module.js`, `static/pose/GLTFLoader.js`, `static/pose/OrbitControls.js`, `static/pose/SkeletonUtils.js`, `static/pose/TransformControls.js`, `static/pose/utils/BufferGeometryUtils.js` | MIT License. See `static/pose/THREE_LICENSE.md`; the bundled `three.module.js` also includes `SPDX-License-Identifier: MIT`. |
| Tabler Icons | `frontend/assets/image-editor-icons/*.svg`, `frontend/assets/image-editor-cursors/*.svg` | MIT License. See `frontend/assets/image-editor-icons/TABLER_LICENSE.md` and `frontend/assets/image-editor-cursors/TABLER_LICENSE.md`. |
| Lucide icons | `frontend/assets/icons/*.svg` | ISC License, with Feather MIT notice for derived icons. See `frontend/assets/icons/LUCIDE_LICENSE.md`; newer bundled SVG files may also include `@license lucide-static v1.23.0 - ISC` comments. |
| Ambient CSS (commit f829df7) | `frontend/vendor/ambientcss/ambient.css`, `frontend/vendor/ambientcss/components.css`; generated subset `frontend/styles/desktop-ambient-controls.css` | MIT License. See `frontend/vendor/ambientcss/LICENSE` and `frontend/vendor/ambientcss/README.md` (upstream paths and SHA-256). |
| liquid-gooey image melt and morph (commit b7c588f) | ported to `frontend/scripts/desktop-canvas-image-group-melt.js` and `frontend/scripts/desktop-canvas-image-group-role-picker.js` (no upstream file bundled) | MIT License. See `frontend/vendor/liquid-gooey/LICENSE` and `frontend/vendor/liquid-gooey/README.md` (upstream paths, SHA-256 and differences). |

## Pose / 3D Assets

| Component | Files | License / Notice |
| --- | --- | --- |
| SOMA-X body model (NVIDIA, `nvidia/soma-x` v0.3.4) | Installed to `APP_DATA_DIR/components/pose-soma/` by `backend/pose_scene/install.py`; GLB mannequins are generated locally | Apache License 2.0. Not bundled in the repository; the installer downloads the pinned files from Hugging Face and keeps their `LICENSE` next to them. The converter uses `py-soma-x` (Apache-2.0). |
| Anny body model (NAVER LABS Europe, `anny` 0.6.1) and `roma` 1.5.7 | Installed into the shared environment by `backend/pose_scene/install.py` to generate the female / male mannequins at install time | Anny code and data: Apache License 2.0; the MakeHuman-derived data inside it: CC0 1.0. `roma`: BSD license (per its package metadata). Not bundled; the Anny↔SOMA wrap meshes come from the pinned `nvidia/soma-x` revision. |
| SAM 3D Body (Meta, `facebookresearch/sam-3d-body` @ `b5c765a`), DINOv3 architecture code (Meta, `facebookresearch/dinov3` @ `6876159a`), MHR model file, and `yacs` 0.1.8 / `braceexpand` 0.1.7 / `termcolor` 3.3.0 | Optional image evidence for video pose recognition; installed to `APP_DATA_DIR/components/pose-capture/` by `backend/pose_capture/install.py` (`--evidence-only` adds it to an existing install); the weights (`sam3d_body.ckpt`, `mhr_model.pt`, `model_config.yaml`) come from the pinned `nvidia/GEM-X` Hugging Face revision | SAM 3D Body code and weights: SAM License; DINOv3 code: DINOv3 License (both Meta license agreements, kept as `LICENSE` / `LICENSE.md` in the checkouts); MHR: Apache License 2.0; the hosting `nvidia/GEM-X` repository lists Apache 2.0 for its code and the NVIDIA Open Model License for its models. `yacs`: Apache 2.0, `braceexpand` and `termcolor`: MIT (per their package metadata). Not bundled in the repository. |

## Optional Runtime Remote Prompt Sources

The gallery workspace can optionally sync prompt/example-image records from
public remote repositories at runtime. These remote records are not bundled in
this repository; synced data is written under local runtime paths such as
`data/source_images/`, which are excluded from Git. Keep upstream repository
links, source URLs, and attribution metadata when displaying or reusing synced
records.

| Source | Upstream repository | Upstream license / notice |
| --- | --- | --- |
| GPT Image 2 | `https://github.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts` | CC0 1.0 Universal. |
| Awesome GPT Image | `https://github.com/ZeroLu/awesome-gpt-image` | MIT License in the repository `LICENSE`; the README may also mention CC BY 4.0, so keep attribution and the upstream link. |
| GPT-4o Image | `https://github.com/ImgEdify/Awesome-GPT4o-Image-Prompts` | MIT License. |
| YouMind GPT Image 2 | `https://github.com/YouMind-OpenLab/awesome-gpt-image-2` | CC BY 4.0. Attribution is required. |
| YouMind Nano Banana Pro | `https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts` | CC BY 4.0. Attribution is required. |
| DavidWu GPT Image2 Prompts | `https://github.com/davidwuw0811-boop/awesome-gpt-image2-prompts` | README states MIT License. This repository also aggregates prompts from other upstream sources, so keep original author/source metadata when available. |

## Python Dependencies

Python dependencies are declared in:

- `requirements.txt`
- `backend/codex_image_runtime/requirements.txt`
- `sidecars/chatgpt_pool/requirements.txt`

Before a public release, generate a dependency license report from the exact
environment used for distribution.

## Krea 2 Instruction-edit Runtime

| Component | Files | License / Notice |
| --- | --- | --- |
| ComfyUI-Krea2Edit | `backend/krea2/edit_profile.py`, `backend/krea2/edit_mlx.py` | Dual-conditioning protocol, reference geometry and attention semantics adapted from `lbouaraba/comfyui-krea2edit` revision `86f886dac23013d88996e3a2e99093ba44d322fb`, Apache-2.0. See `backend/krea2/vendor/LICENSE.comfyui-krea2edit` and `backend/krea2/vendor/NOTICE.md`. |
| KinoMLX | `backend/krea2/edit_mlx.py` | Native MLX Qwen3-VL vision/MRoPE structure cross-checked against `dmlsrc/KinoMLX` revision `02711388f8c7e0a9415eb932f0a130ee87e42724`, MIT. See `backend/krea2/vendor/LICENSE.kinomlx` and `backend/krea2/vendor/NOTICE.md`. |

Krea 2 Identity Edit adapter weights are user-supplied runtime assets, are not
bundled in the project, and remain subject to their own model license.

## Project-owned Runtime Code

`backend/codex_image_runtime/` is project-owned runtime code used by the local
Codex image provider and prompt polishing path.

## Qwen-Image 2.1 optional MLX runtime

| Component | Files | License / Notice |
| --- | --- | --- |
| MFLUX Qwen reference implementation | `backend/qwen21/vendor/*.original`, deterministic adaptation in `backend/qwen21/source_adapter.py`; separately downloaded `components/qwen21/source/mflux/` | MFLUX `adcbe85975760d545ca142069713781929898be0`, MIT. See `backend/qwen21/vendor/MFLUX-LICENSE` and `backend/qwen21/vendor/NOTICE.md`. |

Heretic Qwen 2.1 MLX checkpoint and Viggle turbo adapter are optional, separately
downloaded runtime assets, not bundled in the project. Their pinned repositories,
revisions and checksums are recorded by the Qwen installer. They retain their model
licenses and upstream attribution. Qwen-specific quantization and sigma handling do
not substitute Krea weights or its quantization recipes.

## Gemini Web runtime

`sidecars/google_web/vendor/gemini_webapi` is derived from
`vanch007/gemini-banana-pro-skill` commit `921f63a7f27fb1dc1deb2a43146677b0bf49b772`.
Its GNU AGPL v3 license is preserved at `sidecars/google_web/LICENSE.gemini-webapi`;
local isolation/no-replay patches are documented in `sidecars/google_web/VENDOR.md`.
