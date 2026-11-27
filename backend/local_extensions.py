"""Generic runtime loader and allowlisted bridge for extensions.

Tracked core modules have zero knowledge of specific extension plugins. Any
directory under ``<project_root>/extensions/<id>/`` (tracked built-in extensions
served at ``/ext/<id>/``) or ``<project_root>/local_extensions/<id>/``
(gitignored local-only plugins served at ``/local-ext/<id>/``, skipped when
``CANVASHUB_DISABLE_LOCAL_EXTENSIONS`` is truthy) with a ``plugin.py`` defining
``register(host)`` is discovered at startup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import logging
import os
from pathlib import Path
import posixpath
import re
import sys
from typing import Any, Callable

DISABLE_ENV = "CANVASHUB_DISABLE_LOCAL_EXTENSIONS"
STYLES_MARKER = "<!-- local-extensions:styles -->"
SCRIPTS_MARKER = "<!-- local-extensions:scripts -->"

_DOMAIN_PATTERN = re.compile(r"^[a-z0-9_]+$")
_EXT_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")
_LOGGER = logging.getLogger(__name__)


def extensions_disabled(environ: dict[str, str] | None = None) -> bool:
    """Return True when local extension discovery is disabled via environment."""
    source = os.environ if environ is None else environ
    raw = str(source.get(DISABLE_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _confine_relative_posix(base_dir: Path, rel_path: str) -> tuple[str, Path]:
    if not isinstance(rel_path, str) or not rel_path or "\\" in rel_path or rel_path.startswith("/"):
        raise ValueError(f"Invalid extension asset path: {rel_path!r}")
    normalized = posixpath.normpath(rel_path)
    if normalized in {"", ".", ".."} or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError(f"Extension asset path escapes base directory: {rel_path!r}")
    base_resolved = base_dir.resolve()
    candidate = base_dir.joinpath(*normalized.split("/"))
    if candidate.is_symlink():
        raise ValueError(f"Extension asset must not be a symlink: {candidate}")
    candidate_resolved = candidate.resolve()
    if not candidate_resolved.is_relative_to(base_resolved):
        raise ValueError(f"Extension asset resolves outside base directory: {candidate}")
    if not candidate_resolved.is_file():
        raise FileNotFoundError(f"Extension asset not found: {candidate}")
    return normalized, candidate_resolved


@dataclass(frozen=True)
class AssetProviderMeta:
    key: str
    label: str
    filename_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrontendAssetEntry:
    url_path: str
    kind: str  # "style" | "script"
    base_dir: Path
    file_path: Path


@dataclass
class LocalExtensionHost:
    """Explicit dependency facade passed into each extension's register(host)."""

    extension_id: str
    extension_dir: Path
    project_root: Path
    app_data_dir: Path
    asset_url_prefix: str = "/local-ext"
    release_local_image_memory: Callable[[], Any] | None = None
    create_task: Callable[..., Any] | None = None
    attach_lineage_params: Callable[..., Any] | None = None
    process_image_enhancement_task: Callable[..., Any] | None = None
    _registry: "LocalExtensionRegistry" = field(repr=False, default=None)  # type: ignore[assignment]

    def register_startup_hook(self, hook: Callable[[], Any]) -> None:
        if not callable(hook):
            raise TypeError("startup hook must be callable")
        self._registry._startup_hooks.append((self.extension_id, hook))

    def register_router(self, router: Any) -> None:
        if router is None or not callable(getattr(router, "dispatch", None)):
            raise TypeError("router must expose a callable dispatch(handler, method, path)")
        self._registry._routers.append(router)

    def register_video_store(self, domain: str, store: Any) -> None:
        name = str(domain or "").strip()
        if not _DOMAIN_PATTERN.fullmatch(name):
            raise ValueError(f"Invalid video store domain name: {domain!r}")
        if store is None:
            raise ValueError(f"Video store for {name!r} cannot be None")
        self._registry._video_stores[name] = store

    def register_asset_provider(self, key: str, label: str, *, filename_prefixes: tuple[str, ...] = ()) -> None:
        normalized = str(key or "").strip().lower()
        if not _DOMAIN_PATTERN.fullmatch(normalized):
            raise ValueError(f"Invalid asset provider key: {key!r}")
        clean_prefixes = tuple(str(p or "").strip().lower() for p in filename_prefixes if str(p or "").strip())
        self._registry._asset_providers[normalized] = AssetProviderMeta(
            key=normalized,
            label=str(label or normalized),
            filename_prefixes=clean_prefixes,
        )

    def register_frontend_assets(
        self,
        base_dir: Path,
        *,
        styles: tuple[str, ...] = (),
        scripts: tuple[str, ...] = (),
    ) -> None:
        root = Path(base_dir)
        if not root.is_dir() or root.is_symlink():
            raise ValueError(f"Extension frontend directory does not exist or is a symlink: {base_dir}")
        root_resolved = root.resolve()
        for kind, items in (("style", styles), ("script", scripts)):
            for rel in items:
                norm_rel, resolved = _confine_relative_posix(root_resolved, rel)
                url_path = f"{self.asset_url_prefix}/{self.extension_id}/{norm_rel}"
                entry = FrontendAssetEntry(
                    url_path=url_path,
                    kind=kind,
                    base_dir=root_resolved,
                    file_path=resolved,
                )
                self._registry._frontend_assets[url_path] = entry
                if kind == "style":
                    self._registry._styles.append(entry)
                else:
                    self._registry._scripts.append(entry)


class LocalExtensionRegistry:
    """In-process registry for tracked built-in and optional local extensions."""

    def __init__(self) -> None:
        self._routers: list[Any] = []
        self._startup_hooks: list[tuple[str, Callable[[], Any]]] = []
        self._video_stores: dict[str, Any] = {}
        self._asset_providers: dict[str, AssetProviderMeta] = {}
        self._frontend_assets: dict[str, FrontendAssetEntry] = {}
        self._styles: list[FrontendAssetEntry] = []
        self._scripts: list[FrontendAssetEntry] = []
        self._loaded_ids: list[str] = []

    def reset(self) -> None:
        self._routers.clear()
        self._startup_hooks.clear()
        self._video_stores.clear()
        self._asset_providers.clear()
        self._frontend_assets.clear()
        self._styles.clear()
        self._scripts.clear()
        self._loaded_ids.clear()

    def load_all(
        self,
        project_root: Path,
        *,
        app_data_dir: Path,
        release_local_image_memory: Callable[[], Any] | None = None,
        create_task: Callable[..., Any] | None = None,
        attach_lineage_params: Callable[..., Any] | None = None,
        process_image_enhancement_task: Callable[..., Any] | None = None,
        environ: dict[str, str] | None = None,
    ) -> list[str]:
        self.reset()
        root = Path(project_root)
        roots: list[tuple[Path, str]] = [(root / "extensions", "/ext")]
        if not extensions_disabled(environ):
            roots.append((root / "local_extensions", "/local-ext"))

        for ext_root, asset_prefix in roots:
            if not ext_root.is_dir() or ext_root.is_symlink():
                continue
            for candidate in sorted(ext_root.iterdir(), key=lambda p: p.name):
                ext_id = candidate.name
                if ext_id.startswith(".") or not _EXT_ID_PATTERN.fullmatch(ext_id):
                    continue
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                if ext_id in self._loaded_ids:
                    _LOGGER.warning("Skipping duplicate extension %r (%s)", ext_id, candidate)
                    continue
                plugin_file = candidate / "plugin.py"
                if plugin_file.is_symlink() or not plugin_file.is_file():
                    continue
                try:
                    module_name = f"canvashub_local_ext_{ext_id.replace('-', '_')}"
                    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
                    if spec is None or spec.loader is None:
                        raise ImportError(f"Could not create module spec for {plugin_file}")
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    register_fn = getattr(module, "register", None)
                    if not callable(register_fn):
                        raise AttributeError(f"{plugin_file} does not define register(host)")
                    host = LocalExtensionHost(
                        extension_id=ext_id,
                        extension_dir=candidate.resolve(),
                        project_root=root.resolve(),
                        app_data_dir=Path(app_data_dir),
                        asset_url_prefix=asset_prefix,
                        release_local_image_memory=release_local_image_memory,
                        create_task=create_task,
                        attach_lineage_params=attach_lineage_params,
                        process_image_enhancement_task=process_image_enhancement_task,
                        _registry=self,
                    )
                    register_fn(host)
                    self._loaded_ids.append(ext_id)
                except Exception as exc:
                    _LOGGER.warning("Skipping extension %r (%s): %s", ext_id, plugin_file, exc)
        return list(self._loaded_ids)

    def run_startup_hooks(self) -> int:
        completed = 0
        for ext_id, hook in list(self._startup_hooks):
            try:
                hook()
                completed += 1
            except Exception as exc:
                _LOGGER.warning("Extension startup hook failed for %r: %s", ext_id, exc)
        return completed

    @property
    def loaded_ids(self) -> tuple[str, ...]:
        return tuple(self._loaded_ids)

    def dispatch_route(self, handler: Any, method: str, path: str) -> bool:
        for router in self._routers:
            if router.dispatch(handler, method, path):
                return True
        return False

    def video_stores(self) -> dict[str, Any]:
        return dict(self._video_stores)

    def asset_providers(self) -> dict[str, AssetProviderMeta]:
        return dict(self._asset_providers)

    def match_asset_provider_group(self, raw: str, provider_hint: str = "") -> str | None:
        raw_lower = str(raw or "").strip().lower()
        hint_lower = str(provider_hint or "").strip().lower()
        for key in self._asset_providers:
            if raw_lower == key or hint_lower == key:
                return key
        return None

    def asset_provider_label(self, provider: str) -> str | None:
        meta = self._asset_providers.get(str(provider or "").strip().lower())
        return meta.label if meta else None

    def infer_archive_provider(self, filename_lower: str) -> str | None:
        lower = str(filename_lower or "").lower()
        for key, meta in self._asset_providers.items():
            for prefix in meta.filename_prefixes:
                if lower.startswith(prefix):
                    return key
        return None

    def has_frontend_assets(self) -> bool:
        return bool(self._styles or self._scripts)

    def _versioned_url(self, entry: FrontendAssetEntry) -> str:
        try:
            stamp = entry.file_path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        return f"{entry.url_path}?v={stamp}"

    def inject_desktop_html(self, html: str) -> str:
        if not self.has_frontend_assets():
            return html
        style_tags = "\n".join(
            f'  <link rel="stylesheet" href="{self._versioned_url(entry)}">'
            for entry in self._styles
        )
        script_tags = "\n".join(
            f'  <script src="{self._versioned_url(entry)}"></script>'
            for entry in self._scripts
        )
        result = html
        if STYLES_MARKER in result and style_tags:
            result = result.replace(STYLES_MARKER, style_tags, 1)
        if SCRIPTS_MARKER in result and script_tags:
            result = result.replace(SCRIPTS_MARKER, script_tags, 1)
        return result

    def resolve_frontend_asset(self, url_path: str) -> Path | None:
        if not isinstance(url_path, str) or not url_path.startswith(("/local-ext/", "/ext/")):
            return None
        if "\\" in url_path or "\x00" in url_path:
            return None
        normalized = posixpath.normpath(url_path)
        entry = self._frontend_assets.get(normalized)
        if entry is None:
            return None
        try:
            if entry.file_path.is_symlink():
                return None
            resolved = entry.file_path.resolve()
            if not resolved.is_relative_to(entry.base_dir) or not resolved.is_file():
                return None
            return resolved
        except OSError:
            return None


_DEFAULT_REGISTRY = LocalExtensionRegistry()


def get_registry() -> LocalExtensionRegistry:
    return _DEFAULT_REGISTRY


def load_local_extensions(
    project_root: Path,
    *,
    app_data_dir: Path,
    release_local_image_memory: Callable[[], Any] | None = None,
    create_task: Callable[..., Any] | None = None,
    attach_lineage_params: Callable[..., Any] | None = None,
    process_image_enhancement_task: Callable[..., Any] | None = None,
    environ: dict[str, str] | None = None,
) -> LocalExtensionRegistry:
    _DEFAULT_REGISTRY.load_all(
        project_root,
        app_data_dir=app_data_dir,
        release_local_image_memory=release_local_image_memory,
        create_task=create_task,
        attach_lineage_params=attach_lineage_params,
        process_image_enhancement_task=process_image_enhancement_task,
        environ=environ,
    )
    return _DEFAULT_REGISTRY


def match_asset_provider_group(raw: str, provider_hint: str = "") -> str | None:
    return _DEFAULT_REGISTRY.match_asset_provider_group(raw, provider_hint)


def asset_provider_label(provider: str) -> str | None:
    return _DEFAULT_REGISTRY.asset_provider_label(provider)


def infer_archive_provider(filename_lower: str) -> str | None:
    return _DEFAULT_REGISTRY.infer_archive_provider(filename_lower)
