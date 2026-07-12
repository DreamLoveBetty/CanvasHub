# Optional Upscale Component

The base CanvasHub installer excludes Torch, Torchvision, NumPy, Spandrel, and
ESRGAN model weights. `build-upscale-component.sh` creates a platform-specific
worker archive and updates `build/upscale-component-release/upscale-manifest.json`.

Publish the archive and manifest next to the Electron update feed. Set
`CANVASHUB_UPDATE_URL` while building the desktop app, or set
`CANVASHUB_UPSCALE_MANIFEST_URL` explicitly. These values are written into the
packaged `release-config.json`; runtime environment variables can still
override them for diagnostics. Downloads are resumed when the server supports
HTTP Range and are activated only after SHA256 verification.

Build each platform and architecture natively:

```bash
CANVASHUB_UPSCALE_VERSION=1.0.0 \
CANVASHUB_UPSCALE_BASE_URL=https://updates.example.com/canvashub \
./packaging/build-upscale-component.sh
```

Run the command natively for every platform/architecture using the same
component version. Merge the resulting `platforms` entries into one manifest
when the artifacts are produced on separate build machines.
