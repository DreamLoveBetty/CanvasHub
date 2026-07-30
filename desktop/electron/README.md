# CanvasHub Desktop

Runtime data is stored under Electron's per-user `userData` directory, never
under the installed application resources.

## Development

Install the project dependencies, then run:

```bash
cd desktop/electron
npm install
npm run dev
```

Set `CANVASHUB_DEV_PYTHON` to override the project `.venv` interpreter. Set
`CANVASHUB_DESKTOP_DATA_DIR` to use an isolated desktop data directory.

## Packaging

Build the Python runtime before invoking electron-builder:

```bash
CANVASHUB_UPDATE_URL=https://updates.example.com/canvashub \
CANVASHUB_UPSCALE_MANIFEST_URL=https://updates.example.com/canvashub/upscale-manifest.json \
./packaging/build-desktop.sh
```

Use `CANVASHUB_DESKTOP_BUILD_MODE=pack` for an unpacked smoke build. The release
URLs are saved into `release-config.json` inside the application resources, so
Finder and Start Menu launches do not depend on shell environment variables.
Runtime variables with the same names override the embedded values for
diagnostics. Release builds require platform-native code signing; development
builds never check for updates.

On macOS, release builds also contain a native `canvashub-updater` helper. The
application downloads and verifies the update ZIP through `electron-updater`,
then the helper waits for CanvasHub to exit, replaces the application bundle,
rolls back on replacement or relaunch failure, and starts the new version.
The helper is copied to the per-user data directory before the application
quits, so it remains available while the old bundle is replaced. The helper is
a small Objective-C/Foundation executable with no separately installed runtime.

GitHub Releases can host the generic update feed. For a public release
repository, use `https://github.com/OWNER/REPO/releases/latest/download` as the
update URL and upload the generated `latest-mac.yml` / `latest.yml`, installers,
ZIP files, blockmaps, upscale manifest, and upscale archives as release assets.
Private repositories are not suitable for general client distribution because
the updater would need an embedded GitHub credential.

Unsigned macOS builds are suitable for controlled testing only. Recipients can
right-click the app and choose Open, use System Settings -> Privacy & Security
-> Open Anyway, or remove the downloaded quarantine attribute with:

```bash
xattr -dr com.apple.quarantine /Applications/CanvasHub.app
```

Do not ask recipients to disable Gatekeeper globally. Reliable automatic
updates on macOS require a Developer ID signed and notarized build; unsigned
test builds should be updated by downloading a new DMG manually.
