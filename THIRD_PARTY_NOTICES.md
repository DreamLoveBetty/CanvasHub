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

## Pose / 3D Assets

| Component | Files | License / Notice |
| --- | --- | --- |
| Optional Director Stage mannequin GLB assets | `static/pose/mannequin/*.glb` | Not bundled in the public repository. Users may download `xbot.glb` from the three.js example asset `examples/models/gltf/Xbot.glb` and `ybot.glb` from the Text2Motion Blender integration example media, then place them in `static/pose/mannequin/`. See `static/pose/mannequin/README.md`. |

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
