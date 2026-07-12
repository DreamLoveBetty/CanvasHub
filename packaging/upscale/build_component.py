#!/usr/bin/env python3
"""Assemble an upscale worker, models, archive, and release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--worker-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    worker_dir = Path(args.worker_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    stage = output_dir / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "runtime").mkdir(parents=True)
    (stage / "models").mkdir(parents=True)
    shutil.copytree(worker_dir, stage / "runtime", dirs_exist_ok=True)

    for filename in ("4x-UltraSharp.pth", "4x-AnimeSharp.pth"):
        source = root / "models" / "upscale" / filename
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, stage / "models" / filename)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"upscale-{args.version}-{args.platform}.zip"
    archive = output_dir / archive_name
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(stage).as_posix())

    worker_name = "upscale-worker.exe" if args.platform.startswith("windows-") else "upscale-worker"
    manifest_path = output_dir / "upscale-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {"schema_version": 1, "component": "upscale", "version": args.version, "platforms": {}}
    manifest.update({"schema_version": 1, "component": "upscale", "version": args.version})
    platforms = manifest.setdefault("platforms", {})
    base_url = args.base_url.rstrip("/")
    platforms[args.platform] = {
        "url": f"{base_url}/{archive_name}" if base_url else archive_name,
        "sha256": sha256(archive),
        "size": archive.stat().st_size,
        "worker": f"runtime/{worker_name}",
        "model_dir": "models",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(stage, ignore_errors=True)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
