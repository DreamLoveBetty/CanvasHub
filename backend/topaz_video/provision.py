"""Explicit, integrity-checked staging of Starlight Mini's local FFmpeg assets.

This module only copies a selected local installation into a selected stage. It
does not launch Topaz Video, perform inference, access account state, or choose a
runtime stage implicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid


MODEL_ID = "slm-1"
DEPENDENCIES = (
    "slmes-1", "slmem-1", "slmus-1", "slmum-1",
    "slmds-1", "slmdm-1", "slmdl-1",
)
WEIGHTS = (
    "slme-v1-1fr-fp16-720x1280-mlp.tz3",
    "slmu-v1-16fr-fp16-90x160-mlp.tz3",
    "slmd-v1-16fr-fp16-30x40-mlp.tz3",
)
GLOBAL_METADATA = "tvai.tz"
CACHE_DIRS = tuple(Path(name).stem for name in WEIGHTS)
MANIFEST_NAME = "mini-stage-manifest.json"
MANIFEST_SCHEMA = 2
LEGACY_MANIFEST_SCHEMA = 1


class ProvisionError(RuntimeError):
    """A Mini stage is incomplete, corrupt, or cannot be safely prepared."""


def _required_paths(root: Path) -> tuple[Path, ...]:
    models = root / "Resources" / "models"
    paths = [root / "MacOS" / "ffmpeg", models / f"{MODEL_ID}.json"]
    paths.extend(models / f"{dependency}.json" for dependency in DEPENDENCIES)
    paths.extend(models / name for name in (*WEIGHTS, GLOBAL_METADATA))
    return tuple(paths)


def _check_payload(root: Path, *, require_writable_cache: bool = False) -> list[str]:
    errors: list[str] = []
    if not (root / "Frameworks").is_dir():
        errors.append("Frameworks directory missing")
    for relative in ("Frameworks", "MacOS", "Resources", "Resources/models",
                     "Resources/models/coreMLCache",
                     *(f"Resources/models/coreMLCache/{name}" for name in CACHE_DIRS)):
        if (root / relative).is_symlink():
            errors.append(f"linked payload directory: {relative}")
    if require_writable_cache:
        cache = root / "Resources" / "models" / "coreMLCache"
        if not cache.is_dir() or not os.access(cache, os.W_OK):
            errors.append("writable coreMLCache directory missing")
    for path in _required_paths(root):
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing, empty, or linked file: {path.relative_to(root)}")
    ffmpeg = root / "MacOS" / "ffmpeg"
    if ffmpeg.is_file() and not ffmpeg.is_symlink() and not os.access(ffmpeg, os.X_OK):
        errors.append("MacOS/ffmpeg is not executable")
    models = root / "Resources" / "models"
    for name in (f"{MODEL_ID}.json", *(f"{value}.json" for value in DEPENDENCIES)):
        path = models / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("manifest must be a JSON object")
            if name == f"{MODEL_ID}.json" and set(data.get("dependencies", ())) != set(DEPENDENCIES):
                errors.append("slm-1.json dependency set differs from the checked Mini contract")
            if name == f"{MODEL_ID}.json" and data.get("shortName") != "slm":
                errors.append("slm-1.json is not the expected Mini model")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"invalid model JSON {name}: {exc}")
    return errors


def _entries(root: Path):
    """Enumerate without following symlinked directories."""
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in sorted(dirs + files):
            yield base / name


def _link_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for path in _entries(root):
        if not path.is_symlink():
            continue
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(f"broken or recursive symlink: {path.relative_to(root)}")
            continue
        if not target.is_relative_to(root):
            errors.append(f"symlink escapes stage: {path.relative_to(root)}")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> dict[str, dict]:
    inventory = {}
    for path in _entries(root):
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        if _is_cache_path(relative):
            # Compiled CoreML artifacts are a mutable accelerator cache. Never
            # make successful future compilation invalidate the runtime stage.
            continue
        if path.is_symlink():
            inventory[relative] = {"type": "symlink", "target": os.readlink(path)}
        elif path.is_file():
            inventory[relative] = {"type": "file", "size": path.stat().st_size,
                                   "sha256": _sha256(path)}
    return inventory


def _is_cache_path(relative: str) -> bool:
    return relative == "Resources/models/coreMLCache" or relative.startswith("Resources/models/coreMLCache/")


def _manifest_inventory(manifest: dict) -> dict:
    """Read immutable entries, accepting a legacy manifest that hashed cache."""
    schema = manifest.get("schema")
    if schema not in (LEGACY_MANIFEST_SCHEMA, MANIFEST_SCHEMA):
        raise ValueError("unsupported stage manifest schema")
    if manifest.get("model") != MODEL_ID:
        raise ValueError("stage manifest has a different model")
    records = manifest.get("inventory")
    if not isinstance(records, dict):
        raise ValueError("stage manifest inventory missing")
    if schema == LEGACY_MANIFEST_SCHEMA:
        return {key: value for key, value in records.items() if not _is_cache_path(key)}
    if any(_is_cache_path(key) for key in records):
        raise ValueError("cache entries are not allowed in the current manifest")
    return records


def inspect_stage(stage: str | Path) -> dict:
    """Check exact Mini files, internal links, and staged-byte fingerprints.

    The caller must explicitly provide the stage's ``Contents`` directory.
    """
    selected = Path(stage).expanduser()
    root = selected.resolve()
    errors = [] if root.is_dir() else ["stage directory missing"]
    if selected.is_symlink():
        errors.append("stage itself is a symlink")
    if root.is_dir() and not errors:
        errors.extend(_link_errors(root))
        # Do not open model files through a hostile stage symlink.
        if not errors:
            errors.extend(_check_payload(root, require_writable_cache=True))
        if not errors:
            manifest_path = root / MANIFEST_NAME
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("stage manifest must be an object")
                if _manifest_inventory(manifest) != _inventory(root):
                    errors.append("stage contents differ from the recorded fingerprints")
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"invalid stage manifest: {exc}")
    return {"stage": str(root), "model": MODEL_ID, "ready": not errors, "errors": errors}


def require_stage(stage: str | Path) -> Path:
    """Return a verified, explicitly selected Mini stage or raise."""
    result = inspect_stage(stage)
    if not result["ready"]:
        raise ProvisionError("Mini runtime stage unavailable: " + "; ".join(result["errors"]))
    return Path(result["stage"])


def refresh_stage_manifest(stage: str | Path) -> dict:
    """Explicitly migrate a validated idle stage to cache-independent schema 2.

    No files other than the manifest are changed. This is not run implicitly;
    callers should invoke it only after all inference using the stage stops.
    The legacy immutable fingerprints must still match before migration.
    """
    root = require_stage(stage)
    manifest_path = root / MANIFEST_NAME
    old = json.loads(manifest_path.read_text(encoding="utf-8"))
    if old.get("schema") == MANIFEST_SCHEMA:
        return inspect_stage(root)
    current = _inventory(root)
    if _manifest_inventory(old) != current:
        raise ProvisionError("immutable Mini assets changed; refusing manifest migration")
    updated = {"schema": MANIFEST_SCHEMA, "model": MODEL_ID, "inventory": current}
    temporary = root / (MANIFEST_NAME + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    return inspect_stage(root)


def _clone(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        result = subprocess.run(("cp", "-c", "-R", str(source), str(destination)),
                                capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink(missing_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def _make_cache_writable(cache: Path) -> None:
    """Allow the runtime to populate/refresh only its private compiled cache."""
    for path in (cache, *_entries(cache)):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        extra = stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0)
        path.chmod(mode | extra)


def provision_stage(source: str | Path, stage: str | Path) -> dict:
    """Create an immutable-by-convention Mini stage from explicit paths.

    The destination must not exist. Work is first placed in a sibling staging
    directory and atomically renamed after payload and fingerprint checks.
    """
    origin = Path(source).expanduser().resolve()
    destination = Path(stage).expanduser().resolve()
    if not origin.is_dir():
        raise ProvisionError("source Contents directory missing")
    if destination == origin or destination.is_relative_to(origin) or origin.is_relative_to(destination):
        raise ProvisionError("source and stage must be disjoint directories")
    if destination.exists() or destination.is_symlink():
        raise ProvisionError("stage already exists; refusing to overwrite it")
    source_errors = _check_payload(origin)
    source_errors.extend(_link_errors(origin / "Frameworks"))
    source_cache = origin / "Resources" / "models" / "coreMLCache"
    for name in CACHE_DIRS:
        cache = source_cache / name
        if cache.is_dir() and not cache.is_symlink():
            source_errors.extend(_link_errors(cache))
    if source_errors:
        raise ProvisionError("source Mini assets incomplete: " + "; ".join(source_errors))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".preparing-" + uuid.uuid4().hex)
    try:
        _clone(origin / "MacOS" / "ffmpeg", temporary / "MacOS" / "ffmpeg")
        _clone(origin / "Frameworks", temporary / "Frameworks")
        source_models = origin / "Resources" / "models"
        target_models = temporary / "Resources" / "models"
        for name in (f"{MODEL_ID}.json", *(f"{value}.json" for value in DEPENDENCIES),
                     *WEIGHTS, GLOBAL_METADATA):
            _clone(source_models / name, target_models / name)
        target_cache = target_models / "coreMLCache"
        target_cache.mkdir(parents=True)
        for name in CACHE_DIRS:
            cache = source_models / "coreMLCache" / name
            if cache.is_dir():
                _clone(cache, target_cache / name)
        errors = _link_errors(temporary)
        if not errors:
            _make_cache_writable(target_cache)
            errors.extend(_check_payload(temporary, require_writable_cache=True))
        if errors:
            raise ProvisionError("prepared Mini stage invalid: " + "; ".join(errors))
        manifest = {"schema": MANIFEST_SCHEMA, "model": MODEL_ID, "inventory": _inventory(temporary)}
        (temporary / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
        if destination.exists() or destination.is_symlink():
            raise ProvisionError("stage appeared during preparation; refusing to overwrite it")
        os.replace(temporary, destination)
        return inspect_stage(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or inspect an explicit Starlight Mini Contents stage")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="copy a selected local installation to a new stage")
    prepare.add_argument("--source", required=True, type=Path, help="installed Topaz Video Contents directory")
    prepare.add_argument("--stage", required=True, type=Path, help="new standalone Contents directory")
    inspect = commands.add_parser("inspect", help="verify an existing standalone stage")
    inspect.add_argument("--stage", required=True, type=Path, help="standalone Contents directory")
    refresh = commands.add_parser("refresh-manifest", help="explicitly migrate an idle stage to cache-independent fingerprints")
    refresh.add_argument("--stage", required=True, type=Path, help="idle standalone Contents directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = provision_stage(args.source, args.stage)
        elif args.command == "refresh-manifest":
            result = refresh_stage_manifest(args.stage)
        else:
            result = inspect_stage(args.stage)
    except ProvisionError as exc:
        result = {"model": MODEL_ID, "ready": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
