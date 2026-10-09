"""Worker-side immutable component view; upstream owns VAE tensor mapping."""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from .vae_store import BUILTIN, inspect_vae, validate_snapshot


def vae_signature(snapshot):
    if not snapshot or snapshot.get("id") == BUILTIN:
        return (BUILTIN,)
    validate_snapshot(snapshot)
    return (snapshot["id"], snapshot["format"], snapshot["sha256"], str(snapshot["path"]))


@contextmanager
def model_view(model_path, snapshot, cache):
    """No overrides, transforms or new paths at all for the original VAE.

    Custom views exist only while constructing the pipeline: upstream eagerly
    loads all configs/weights/processors then. Never mutate the real Base links
    or patch global MFLUX loaders; raw weights retain no MFLUX metadata, so the
    upstream loader applies vae_weight exactly once. Native exports bypass it.
    """
    if not snapshot or snapshot.get("id") == BUILTIN:
        yield Path(model_path)
        return
    validate_snapshot(snapshot, checksum=True)
    inspected = inspect_vae(Path(snapshot["path"]) / "0.safetensors")
    if inspected["format"] != snapshot["format"]:
        raise ValueError("VAE 格式与登记信息不符")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vae-view-", dir=cache) as scratch:
        view = Path(scratch)
        for component in ("transformer", "text_encoder", "processor"):
            target = (Path(model_path) / component).resolve(strict=True)
            (view / component).symlink_to(target, target_is_directory=True)
        (view / "vae").symlink_to(Path(snapshot["path"]).resolve(strict=True), target_is_directory=True)
        yield view
