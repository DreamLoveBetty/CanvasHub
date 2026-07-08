# Optional Director Stage GLB Assets

The public repository does not bundle `xbot.glb` or `ybot.glb`.

To enable real bone-rig mannequins locally, download the assets yourself and
place them here:

```text
static/pose/mannequin/xbot.glb
static/pose/mannequin/ybot.glb
```

Suggested sources:

- `xbot.glb`: three.js example asset `examples/models/gltf/Xbot.glb`
  <https://github.com/mrdoob/three.js/blob/dev/examples/models/gltf/Xbot.glb>
- `ybot.glb`: Text2Motion Blender integration example `Y Bot.glb`
  <https://github.com/text2motion/blender-integration/blob/main/README.md>

Direct download commands:

```bash
mkdir -p static/pose/mannequin
curl -L -o static/pose/mannequin/xbot.glb \
  https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf/Xbot.glb
curl -L -o static/pose/mannequin/ybot.glb \
  'https://media.githubusercontent.com/media/text2motion/blender-integration/refs/tags/releases/0.1.0/assets/Y%20Bot.glb?download=true'
```

If these files are absent, Director Stage falls back to the procedural
mannequin.
