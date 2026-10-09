"""Local-first LoRA catalog; owns metadata, not inference or weight lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import threading
import time

from ..local_image.lora_store import normalize_asset_id
from .repository import Repository
from .previews import Previews, MAX_BYTES

from .contracts import FIELDS, validate_fields


def local_description(path):
    """Read explicit local descriptions; training tag frequencies are not triggers."""
    result = {}
    try:
        with path.open("rb") as stream:
            size = struct.unpack("<Q", stream.read(8))[0]
            header = json.loads(stream.read(size)) if size <= 8 * 1024**2 else {}
        metadata = header.get("__metadata__") or {}
        for key in ("trainedWords", "trigger_words", "ss_trigger_words"):
            words = metadata.get(key)
            if isinstance(words, str):
                try:
                    words = json.loads(words)
                except ValueError:
                    words = [words]
            if isinstance(words, list):
                result.update(validate_fields({"trigger_words": words}))
                break
    except (OSError, ValueError, TypeError, struct.error, AttributeError):
        pass
    for suffix in (".civitai.info", ".lora.json"):
        sidecar = path.with_suffix(suffix)
        try:
            if sidecar.is_symlink() or sidecar.stat().st_size > 256 * 1024:
                continue
            value = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                continue
            if suffix == ".civitai.info":
                value = {"version": str(value.get("name") or ""),
                         "trigger_words": value.get("trainedWords") or []}
            result.update(validate_fields({key: val for key, val in value.items()
                                           if key in FIELDS - {"cover_id", "preview_order", "favorite", "hidden"}}))
        except (OSError, ValueError, TypeError):
            pass
    return result


class Service:
    def __init__(self, root, *, catalogs, resolvers, deleters=None, excluded_ids=(), provider=None):
        self.repository = Repository(root)
        self.previews = Previews(root, self.repository)
        self.catalogs, self.resolvers = dict(catalogs), dict(resolvers)
        self.deleters = dict(deleters or {})
        self.excluded_ids = set(excluded_ids)
        self.provider = provider
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self.last_scan = 0.0
        self.scan_errors = []
        self.local_fingerprints = {}
        self.pending = []
        self.worker = None
        # Metadata sync is recoverable, and never appears as a generation task.
        for identity, record in self.repository.records().items():
            if record["sync"].get("status") in {"queued", "running"}:
                self.repository.write_source(identity, "sync", {"status": "interrupted", "message": "服务重启，可重新同步"})

    def scan(self, force=False):
        with self.scan_lock:
            if not force and time.monotonic() - self.last_scan < 15:
                return
            errors = []
            for engine, catalog in self.catalogs.items():
                try:
                    response = catalog()
                    items = [dict(item) for item in response.get("loras", [])
                             if item["asset_id"] not in self.excluded_ids]
                    paths = {}
                    for item in items:
                        path = item.pop("_path", None)
                        if path is None:
                            path, _ = self.resolvers[engine](item["asset_id"])
                        path = Path(path)
                        paths[item["asset_id"]] = path
                        item["filename"] = path.name
                    self.repository.reconcile(engine, items)
                    errors.extend({"engine": engine, **error} for error in response.get("scan_errors", []))
                    for item in items:
                        identity = item["asset_id"]
                        path = paths[identity]
                        siblings = [path] + [path.with_suffix(suffix) for suffix in (".lora.json", ".civitai.info", ".preview.png", ".preview.jpg", ".preview.webp", ".png", ".jpg", ".webp")]
                        fingerprint = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns)
                                            for p in siblings if p.is_file() and not p.is_symlink())
                        if self.local_fingerprints.get((engine, identity)) != fingerprint:
                            description = local_description(path)
                            self.repository.write_source(identity, "local", description)
                            self._import_local_preview(identity, path)
                            self.local_fingerprints[(engine, identity)] = fingerprint
                except (ValueError, OSError, RuntimeError):
                    # A failed scan is not proof that every model was removed.
                    errors.append({"engine": engine, "error": "本地 LoRA 目录读取失败"})
            self.scan_errors, self.last_scan = errors, time.monotonic()
        if self.repository.preferences().get("auto_sync") and self.provider:
            ids = [key for key, row in self.repository.records().items()
                   if not row["sync"] and any(m["present"] for m in row["members"])]
            if ids:
                self.sync(ids[:100])

    def _import_local_preview(self, identity, path):
        if any(item["kind"] == "local" for item in self.repository.get(identity)["previews"]):
            return
        for suffix in (".preview.png", ".preview.jpg", ".preview.webp", ".png", ".jpg", ".webp"):
            candidate = path.with_suffix(suffix)
            try:
                if candidate.is_file() and not candidate.is_symlink() and candidate.stat().st_size <= MAX_BYTES:
                    self.previews.add(identity, candidate.read_bytes(), kind="local", caption="本地附带示例")
                    return
            except (ValueError, OSError):
                continue

    def public(self, record):
        effective, sources = {}, {}
        for source in ("remote", "local", "manual"):
            for key, value in record[source].items():
                if key in FIELDS:
                    effective[key], sources[key] = value, source
        members = record["members"]
        effective.setdefault("name", next((m.get("name") for m in members if m.get("name")), record["asset_id"][:12]))
        effective.setdefault("trigger_words", [])
        effective.setdefault("trigger_status", "provided" if effective["trigger_words"] else "unknown")
        effective.setdefault("tags", [])
        if effective["trigger_status"] != "provided":
            effective["trigger_words"] = []
        order = effective.get("preview_order", [])
        previews = sorted(record["previews"], key=lambda item: (
            order.index(item["id"]) if item["id"] in order else len(order), item["created_at"]))
        for item in previews:
            item["url"] = "/api/lora/preview?id=" + item["id"]
            item["thumb_url"] = item["url"] + "&thumb=1"
        cover = next((p for p in previews if p["id"] == effective.get("cover_id")), None)
        if cover is None and effective.get("cover_id") != "":
            cover = next((p for p in previews if p["kind"] == "manual"), previews[0] if previews else None)
        available = [m["engine"] for m in members if m["present"]]
        return {**effective, "asset_id": record["asset_id"], "revision": record["revision"],
                "engines": available, "members": members, "available": bool(available),
                "field_sources": sources, "manual_fields": list(record["manual"]),
                "previews": previews, "cover": cover, "binding": record["binding"],
                "sync": record["sync"]}

    def list(self, *, engine="", query="", filter_value="all", offset=0, limit=60, refresh=False):
        if engine and engine not in self.catalogs:
            raise ValueError("推理框架无效")
        self.scan(refresh)
        items = [self.public(row) for row in self.repository.records().values()]
        if engine:
            items = [item for item in items if engine in item["engines"] or (
                filter_value == "missing" and any(m["engine"] == engine for m in item["members"]))]
        if filter_value == "favorite":
            items = [item for item in items if item.get("favorite")]
        elif filter_value == "missing":
            items = [item for item in items if not item["available"]]
        elif filter_value == "incomplete":
            items = [item for item in items if not item["cover"] or item["trigger_status"] == "unknown"]
        elif filter_value == "hidden":
            items = [item for item in items if item.get("hidden")]
        if filter_value != "hidden":
            items = [item for item in items if not item.get("hidden")]
        search = str(query).strip().casefold()
        if search:
            items = [item for item in items if search in " ".join([
                item["name"], item.get("version", ""), *item["trigger_words"], *item["tags"],
                *(m.get("filename", "") for m in item["members"])]).casefold()]
        items.sort(key=lambda item: (not bool(item.get("favorite")), item["name"].casefold(), item["asset_id"]))
        offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
        total = len(items)
        # List payloads contain only the cover, full gallery is loaded on demand.
        return {"ok": True, "items": [{k: v for k, v in item.items() if k != "previews"}
                for item in items[offset:offset + limit]], "total": total, "scan_errors": self.scan_errors}

    def detail(self, identity):
        return self.public(self.repository.get(normalize_asset_id(identity)))

    def edit(self, body):
        identity = normalize_asset_id(body.get("asset_id"))
        changes = validate_fields(body.get("changes", {}))
        reset = body.get("reset_fields", [])
        if not isinstance(reset, list) or any(key not in FIELDS for key in reset):
            raise ValueError("重置字段无效")
        # Trigger text and its meaning always move together, including explicit empty.
        if {"trigger_status", "trigger_words"} & set(reset):
            reset = list(set(reset) | {"trigger_status", "trigger_words"})
        ids = {p["id"] for p in self.repository.get(identity)["previews"]}
        if (changes.get("cover_id") and changes["cover_id"] not in ids
                or any(key not in ids for key in changes.get("preview_order", []))):
            raise ValueError("示例图不属于此 LoRA")
        self.repository.edit(identity, changes, reset, body.get("revision"))
        return self.detail(identity)

    def delete_weight(self, identity, engine):
        identity = normalize_asset_id(identity)
        if engine not in self.deleters:
            raise ValueError("推理框架无效")
        result = self.deleters[engine](identity)  # Preserve domain queued/running guards.
        self.scan(True)
        return result

    def settings(self, changes=None):
        if changes is not None:
            if not isinstance(changes, dict) or set(changes) - {"auto_sync", "api_key"}:
                raise ValueError("LoRA 设置无效")
            if "auto_sync" in changes:
                if not isinstance(changes["auto_sync"], bool):
                    raise ValueError("自动补全须为布尔值")
                self.repository.preferences({"auto_sync": changes["auto_sync"]})
            if "api_key" in changes and self.provider:
                self.provider.set_key(changes["api_key"])
        return {**self.repository.preferences(), "api_key_configured": bool(self.provider and self.provider.has_key())}

    def bind(self, identity, url):
        identity = normalize_asset_id(identity)
        if not self.provider:
            raise ValueError("Civitai 适配器未启用")
        binding = self.provider.binding(url) if url else {}
        with self.lock:
            self.repository.write_source(identity, "binding", binding)
            self.repository.write_source(identity, "remote", {})
            self.repository.write_source(identity, "sync", {})
            for item in self.repository.get(identity)["previews"]:
                if item["kind"] == "remote":
                    self.previews.delete(identity, item["id"])
        return self.detail(identity)

    def sync(self, identities):
        if not self.provider:
            raise ValueError("Civitai 适配器未启用")
        if not isinstance(identities, list) or not 1 <= len(identities) <= 100:
            raise ValueError("每批同步 1–100 个 LoRA")
        identities = list(dict.fromkeys(normalize_asset_id(item) for item in identities))
        for identity in identities:
            self.repository.get(identity)
        with self.lock:
            for identity in identities:
                if self.repository.get(identity)["sync"].get("status") in {"queued", "running"}:
                    continue
                self.repository.write_source(identity, "sync", {"status": "queued", "message": "等待资料同步"})
                self.pending.append(identity)
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._sync_loop, name="lora-metadata", daemon=True)
                self.worker.start()
        return {"ok": True, "queued": len(identities)}

    def sync_state(self):
        items = [{"asset_id": key, **row["sync"]} for key, row in self.repository.records().items() if row["sync"]]
        return {"ok": True, "items": items,
                "active": any(item.get("status") in {"running", "queued"} for item in items)}

    def _sync_loop(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.worker = None
                    return
                identity = self.pending.pop(0)
                binding = self.repository.get(identity)["binding"]
                self.repository.write_source(identity, "sync", {"status": "running", "message": "正在获取 Civitai 资料"})
            try:
                result = self.provider.lookup(identity, binding)
                with self.lock:
                    if self.repository.get(identity)["binding"] != binding:
                        continue
                    self.repository.write_source(identity, "remote", result["fields"])
                failed_images = 0
                images = result.get("images", [])[:4]
                image_errors = []
                for remote in images:
                    with self.lock:
                        record = self.repository.get(identity)
                        if record["binding"] != binding:
                            break
                        if any(p["source_url"] == remote["url"] for p in record["previews"]):
                            continue
                    try:
                        content = self.provider.image(remote["url"])
                        with self.lock:
                            if self.repository.get(identity)["binding"] != binding:
                                break
                            self.previews.add(identity, content, kind="remote", source_url=remote["url"],
                                              caption="Civitai 版本示例（可能包含其他模型）")
                    except (ValueError, OSError, RuntimeError) as exc:
                        failed_images += 1
                        # ProviderError exposes a sanitized reason. Do not leak
                        # raw network errors, local paths or image metadata.
                        reason = getattr(exc, "public_message", "示例图读取或保存失败")
                        if reason not in image_errors:
                            image_errors.append(reason)
                message = "资料已同步" if images else "资料已同步，该版本未返回示例图"
                if failed_images:
                    message = f"资料已同步，{failed_images}/{len(images)} 张示例图下载失败：" + "；".join(image_errors[:3])
                state = {"status": "partial" if failed_images else "ready",
                         "message": message, "preview_total": len(images), "preview_failed": failed_images,
                         "matched_by": result["matched_by"], "model_version_id": result["version_id"]}
            except Exception as exc:
                state = {"status": getattr(exc, "status", "error"),
                         "message": getattr(exc, "public_message", "Civitai 暂不可用，可稍后重试")}
            with self.lock:
                if self.repository.get(identity)["binding"] == binding:
                    self.repository.write_source(identity, "sync", {**state, "updated_at": time.time()})
