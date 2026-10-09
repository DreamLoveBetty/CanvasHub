"""Synthetic, offline LoRA metadata tests; no MLX, credentials or user assets."""
import gc
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import warnings
from urllib.error import HTTPError, URLError
from unittest import mock

from PIL import Image

from backend.local_image.lora_store import LoRAStore
from backend.lora_library.service import Service, validate_fields
from backend.lora_library.repository import ConflictError
from backend.routes.lora_library_routes import create_router
from backend.lora_library.civitai import Civitai, ProviderError


def weight(metadata=None):
    header = {"layer.lora_A.weight": {"dtype": "F16", "shape": [1, 1], "data_offsets": [0, 2]},
              "layer.lora_B.weight": {"dtype": "F16", "shape": [1, 1], "data_offsets": [2, 4]},
              "__metadata__": metadata or {}}
    encoded = json.dumps(header).encode()
    return len(encoded).to_bytes(8, "little") + encoded + bytes(4)


def picture():
    stream = io.BytesIO()
    Image.new("RGB", (24, 32), "blue").save(stream, format="PNG")
    return stream.getvalue()


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = LoRAStore(self.root / "model_assets")
        self.store.directory.mkdir(parents=True)
        self.file = self.store.directory / "sample.safetensors"
        self.file.write_bytes(weight())
        self.service = Service(self.root / "library",
            catalogs={"krea2": lambda: {"loras": self.store.list()}},
            resolvers={"krea2": self.store.resolve}, deleters={"krea2": self.store.delete})
        self.identity = self.service.list()["items"][0]["asset_id"]

    def edit(self, changes, reset=()):
        return self.service.edit({"asset_id": self.identity, "revision": self.service.detail(self.identity)["revision"],
                                  "changes": changes, "reset_fields": list(reset)})

    def test_manual_edit_survives_rename_and_restart(self):
        self.edit({"name": "My style", "trigger_words": ["My Phrase", "My Phrase"], "tags": ["style"]})
        self.file.rename(self.file.with_name("renamed.safetensors"))
        self.service.scan(True)
        other = Service(self.root / "library", catalogs={}, resolvers={})
        result = other.detail(self.identity)
        self.assertEqual(result["name"], "My style")
        self.assertEqual(result["trigger_words"], ["My Phrase"])
        self.assertEqual(result["members"][0]["filename"], "renamed.safetensors")

    def test_manual_local_remote_priority_and_reset(self):
        repo = self.service.repository
        repo.write_source(self.identity, "remote", {"name": "Remote", "trigger_words": ["remote"], "trigger_status": "provided"})
        repo.write_source(self.identity, "local", {"name": "Local"})
        self.assertEqual(self.service.detail(self.identity)["name"], "Local")
        self.edit({"name": "Manual", "trigger_status": "none"})
        repo.write_source(self.identity, "remote", {"name": "New", "trigger_words": ["new"], "trigger_status": "provided"})
        result = self.service.detail(self.identity)
        self.assertEqual(result["name"], "Manual")
        self.assertEqual(result["trigger_words"], [])
        result = self.edit({}, ["name", "trigger_words"])
        self.assertEqual(result["name"], "Local")
        self.assertEqual(result["trigger_words"], ["new"])

    def test_explicit_empty_is_not_refilled(self):
        self.edit({"trigger_words": []})
        self.service.repository.write_source(self.identity, "remote", {"trigger_words": ["word"], "trigger_status": "provided"})
        self.assertEqual(self.service.detail(self.identity)["trigger_status"], "unknown")
        self.assertEqual(self.service.detail(self.identity)["trigger_words"], [])

    def test_missing_file_keeps_metadata(self):
        content = self.file.read_bytes()
        self.edit({"description": "Keep this"})
        self.file.unlink()
        self.service.scan(True)
        self.assertFalse(self.service.detail(self.identity)["available"])
        self.assertEqual(self.service.list(engine="krea2", filter_value="missing")["total"], 1)
        self.file.write_bytes(content)
        self.service.scan(True)
        self.assertTrue(self.service.detail(self.identity)["available"])
        self.assertEqual(self.service.detail(self.identity)["description"], "Keep this")

    def test_removed_local_sidecar_releases_automatic_fields(self):
        sidecar = self.file.with_suffix(".lora.json")
        sidecar.write_text(json.dumps({"name": "Local description"}))
        self.service.scan(True)
        self.assertEqual(self.service.detail(self.identity)["name"], "Local description")
        self.service.repository.write_source(self.identity, "remote", {"name": "Remote description"})
        sidecar.unlink()
        self.service.scan(True)
        self.assertEqual(self.service.detail(self.identity)["name"], "Remote description")

    def test_routes_reject_non_object_json(self):
        router = create_router(self.service)
        handler = mock.Mock(command="POST", path="/api/lora/update")
        handler.require_auth.return_value = True
        for body in ([], None, "wrong"):
            handler.read_json_body.return_value = body
            router.dispatch(handler, "POST", handler.path)
            self.assertEqual(handler.send_json.call_args.args[1], 400)

    def test_changed_content_has_different_identity(self):
        self.edit({"trigger_words": ["old"]})
        self.file.write_bytes(weight({"changed": "yes"}))
        self.service.scan(True)
        current = self.service.list(engine="krea2")["items"]
        self.assertEqual(len(current), 1)
        self.assertNotEqual(current[0]["asset_id"], self.identity)
        self.assertEqual(current[0]["trigger_words"], [])

    def test_local_sidecar_and_preview(self):
        self.file.with_suffix(".lora.json").write_text(json.dumps({"name": "Local name", "trigger_words": ["precise phrase"]}))
        self.file.with_suffix(".preview.png").write_bytes(picture())
        self.service.scan(True)
        result = self.service.detail(self.identity)
        self.assertEqual(result["name"], "Local name")
        self.assertEqual(result["trigger_words"], ["precise phrase"])
        self.assertEqual(result["cover"]["kind"], "local")

    def test_training_tags_are_not_triggers(self):
        self.file.write_bytes(weight({"ss_tag_frequency": '{"style": 5}'}))
        self.service.scan(True)
        self.assertEqual(self.service.list(engine="krea2")["items"][0]["trigger_words"], [])

    def test_late_local_preview_is_discovered(self):
        self.file.with_suffix(".preview.png").write_bytes(picture())
        self.service.scan(True)
        self.assertIsNotNone(self.service.detail(self.identity)["cover"])

    def test_single_scan_snapshot_does_not_expose_paths(self):
        self.service.catalogs["krea2"] = self.store.library_snapshot
        self.service.resolvers["krea2"] = lambda _: self.fail("per-file rescan")
        result = self.service.list(refresh=True)
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_metadata_sync_does_not_overwrite_concurrent_manual_changes(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        class Provider:
            def lookup(inner, identity, binding):
                entered.set()
                release.wait(3)
                return {"fields": {"name": "Remote", "trigger_words": ["remote"], "trigger_status": "provided"},
                        "images": [], "version_id": 1, "matched_by": "hash"}
        self.service.provider = Provider()
        self.service.sync([self.identity])
        self.assertTrue(entered.wait(2))
        thread = self.service.worker
        self.edit({"name": "User choice", "trigger_status": "none"})
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        result = self.service.detail(self.identity)
        self.assertEqual(result["name"], "User choice")
        self.assertEqual(result["trigger_words"], [])
        self.assertEqual(result["sync"]["status"], "ready")

    def test_unmatched_files_are_not_retried_on_every_scan(self):
        provider = mock.Mock()
        provider.lookup.side_effect = ProviderError("not_found", "no match")
        self.service.provider = provider
        self.service.repository.preferences({"auto_sync": True})
        self.service.scan(True)
        worker = self.service.worker
        if worker:
            worker.join(3)
        self.service.scan(True)
        self.assertEqual(provider.lookup.call_count, 1)
        self.assertEqual(self.service.detail(self.identity)["sync"]["status"], "not_found")

    def test_preview_failures_report_counts_and_safe_reason_without_losing_metadata(self):
        provider = mock.Mock()
        provider.lookup.return_value = {"fields": {"name": "Remote style"},
            "images": [{"url": "https://image.civitai.com/a"}, {"url": "https://image.civitai.com/b"}],
            "version_id": 42, "matched_by": "hash"}
        provider.image.side_effect = [ProviderError("restricted", "示例图访问受限"), OSError("private path / secret")]
        self.service.provider = provider
        self.service.pending = [self.identity]
        self.service._sync_loop()
        result = self.service.detail(self.identity)
        self.assertEqual(result["name"], "Remote style")
        self.assertEqual(result["sync"]["status"], "partial")
        self.assertEqual(result["sync"]["preview_total"], 2)
        self.assertEqual(result["sync"]["preview_failed"], 2)
        self.assertIn("2/2", result["sync"]["message"])
        self.assertIn("示例图访问受限", result["sync"]["message"])
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("secret", json.dumps(result))

    def test_empty_remote_gallery_is_distinguished_from_download_failure(self):
        provider = mock.Mock()
        provider.lookup.return_value = {"fields": {"name": "Style"}, "images": [],
                                       "version_id": 42, "matched_by": "hash"}
        self.service.provider = provider
        self.service.pending = [self.identity]
        self.service._sync_loop()
        state = self.service.detail(self.identity)["sync"]
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["preview_total"], 0)
        self.assertIn("未返回示例图", state["message"])

    def test_interrupted_sync_can_be_retried_after_restart(self):
        self.service.repository.write_source(self.identity, "sync", {"status": "running"})
        restarted = Service(self.root / "library", catalogs={}, resolvers={})
        self.assertEqual(restarted.detail(self.identity)["sync"]["status"], "interrupted")

    def test_preview_copy_and_cache_clear_preserve_manual(self):
        manual = self.service.previews.add(self.identity, picture())
        remote = self.service.previews.add(self.identity, picture(), kind="remote")
        self.edit({"cover_id": manual["id"], "preview_order": [remote["id"], manual["id"]]})
        self.assertEqual(self.service.previews.clear_cache(), 1)
        self.assertTrue(self.service.previews.path(manual["id"]).exists())
        self.assertEqual(self.service.detail(self.identity)["cover"]["id"], manual["id"])
        with self.assertRaises(ValueError):
            self.service.previews.path(remote["id"])

    def test_preview_rejects_traversal_and_non_images(self):
        with self.assertRaises(ValueError):
            self.service.previews.path("../../secret")
        with self.assertRaises(ValueError):
            self.service.previews.add(self.identity, b"<svg></svg>")
        with self.assertRaises(ValueError):
            self.edit({"cover_id": "a" * 32})

    def test_stale_edit_conflict(self):
        self.edit({"name": "one"})
        with self.assertRaises(ConflictError):
            self.service.edit({"asset_id": self.identity, "revision": 0, "changes": {"name": "stale"}})

    def test_validation_rejects_unsafe_links_and_invalid_values(self):
        for fields in ({"source_url": "javascript:alert(1)"}, {"recommended_scale": float("nan")},
                       {"favorite": 1}, {"trigger_words": "not a list"}, {"arbitrary": "field"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_fields(fields)

    def test_delete_uses_domain_guard_and_keeps_metadata(self):
        def blocked(identity):
            raise RuntimeError("busy")
        self.service.deleters["krea2"] = blocked
        with self.assertRaises(RuntimeError):
            self.service.delete_weight(self.identity, "krea2")
        self.assertTrue(self.file.exists())
        self.service.deleters["krea2"] = self.store.delete
        self.service.delete_weight(self.identity, "krea2")
        self.assertFalse(self.service.detail(self.identity)["available"])

    def test_filter_search_and_pagination(self):
        self.edit({"favorite": True, "trigger_words": ["exact phrase"], "hidden": False})
        self.assertEqual(self.service.list(query="PHRASE", filter_value="favorite")["total"], 1)
        self.assertEqual(self.service.list(offset=1)["items"], [])
        self.edit({"hidden": True})
        self.assertEqual(self.service.list()["total"], 0)
        self.assertEqual(self.service.list(filter_value="hidden")["total"], 1)

    def test_connections_close_and_rollback(self):
        with self.service.repository.connection() as db:
            db.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        with self.assertRaises(RuntimeError):
            with self.service.repository.connection() as db:
                db.execute("UPDATE records SET revision=500")
                raise RuntimeError("rollback")
        self.assertEqual(self.service.detail(self.identity)["revision"], 0)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", ResourceWarning)
            for _ in range(10):
                self.service.list()
            gc.collect()
        self.assertFalse([w for w in captured if issubclass(w.category, ResourceWarning)])

    def test_all_routes_require_existing_auth(self):
        router = create_router(self.service)
        class Handler:
            def require_auth(self):
                return False
            def send_json(self, *args):
                raise AssertionError("unauthorized handler executed")
        for method, path in router._routes:
            self.assertTrue(router.dispatch(Handler(), method, path))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.requests = []
        self.answers = []
        class Opener:
            def open(inner, request, timeout):
                self.requests.append(request)
                answer = self.answers.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                result = io.BytesIO(answer)
                result.headers = {"Content-Length": str(len(answer))}
                return result
        self.provider = Civitai(self.temp.name, opener=Opener(), sleep=lambda _: None)
        self.identity = "a" * 64

    def response(self, **extra):
        return json.dumps({"id": 42, "modelId": 7, "name": "v1", "model": {"name": "Style"},
                           "files": [{"hashes": {"SHA256": self.identity.upper()}}],
                           "trainedWords": ["My Phrase"], "description": "<p>Use 0.8</p>",
                           "images": [{"url": "https://image.civitai.com/example.jpg", "type": "image"}],
                           **extra}).encode()

    def test_exact_version_fields_and_hash_verified(self):
        self.answers.append(self.response())
        result = self.provider.lookup(self.identity, {})
        self.assertEqual(result["matched_by"], "hash")
        self.assertEqual(result["fields"]["trigger_words"], ["My Phrase"])
        self.assertEqual(result["fields"]["description"], "Use 0.8")
        self.assertIn("by-hash/" + self.identity, self.requests[0].full_url)

    def test_wrong_hash_is_not_silently_associated(self):
        self.answers.append(self.response(files=[{"hashes": {"SHA256": "b" * 64}}]))
        with self.assertRaises(ProviderError) as context:
            self.provider.lookup(self.identity, {})
        self.assertEqual(context.exception.status, "mismatch")

    def test_manual_version_is_labeled_and_requires_version_id(self):
        with self.assertRaises(ValueError):
            self.provider.binding("https://civitai.com/models/7")
        binding = self.provider.binding("https://civitai.com/models/7/style?modelVersionId=42")
        self.answers.append(self.response(files=[]))
        self.assertEqual(self.provider.lookup(self.identity, binding)["matched_by"], "manual")
        self.assertEqual(self.requests[0].full_url, "https://civitai.com/api/v1/model-versions/42")

    def test_secret_server_only_and_never_sent_to_image_host(self):
        self.provider.set_key("secret-fixture")
        self.assertTrue(self.provider.has_key())
        self.assertEqual(self.provider.key_file.stat().st_mode & 0o777, 0o600)
        self.answers.extend([self.response(), picture()])
        self.provider.lookup(self.identity, {})
        self.provider.image("https://image.civitai.com/example.jpg")
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer secret-fixture")
        self.assertIsNone(self.requests[1].get_header("Authorization"))
        self.provider.set_key("")
        self.assertFalse(self.provider.has_key())

    def test_untrusted_urls_and_redirects_blocked(self):
        for url in ("http://127.0.0.1/a", "https://image.civitai.com.evil.test/a",
                    "https://user@image.civitai.com/a", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                self.provider.image(url)
        self.answers.append(HTTPError("https://image.civitai.com/a", 302, "redirect",
                                      {"Location": "http://127.0.0.1/private"}, None))
        with self.assertRaises(ProviderError):
            self.provider.image("https://image.civitai.com/a")
        self.assertEqual(len(self.requests), 1)

    def test_official_image_storage_redirect_is_followed_without_credentials(self):
        self.provider.set_key("secret-fixture")
        origin = "https://image.civitai.com/fixture/original=true/sample.jpeg"
        target = "https://blobs-b2.civitai.com/file/blobs-managed-public/sample.jpg"
        self.answers.extend([HTTPError(origin, 301, "Moved", {"Location": target}, None), picture()])
        self.assertEqual(self.provider.image(origin), picture())
        self.assertEqual([r.full_url for r in self.requests], [origin, target])
        self.assertTrue(all(r.get_header("Authorization") is None for r in self.requests))

    def test_storage_redirect_does_not_allow_arbitrary_next_hop(self):
        origin = "https://blobs-b2.civitai.com/file/blobs-managed-public/sample.jpg"
        self.answers.append(HTTPError(origin, 302, "Moved", {"Location": "https://127.0.0.1/private"}, None))
        with self.assertRaises(ProviderError):
            self.provider.image(origin)
        self.assertEqual(len(self.requests), 1)
        for url in ("https://blobs-b2.civitai.com.evil.test/a", "https://user@blobs-b2.civitai.com/a",
                    "http://blobs-b2.civitai.com/a", "https://blobs-b2.civitai.com:8443/a"):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                self.provider.image(url)

    def test_api_key_is_not_forwarded_to_storage_redirect(self):
        self.provider.set_key("secret-fixture")
        self.answers.append(HTTPError("https://civitai.com/api/v1/model-versions/42", 302, "Moved",
                            {"Location": "https://blobs-b2.civitai.com/file/blob"}, None))
        with self.assertRaises(ProviderError):
            self.provider.lookup(self.identity, {})
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer secret-fixture")

    def test_large_embedded_workflow_metadata_is_bounded_and_not_persisted(self):
        self.answers.append(self.response(images=[{"url": "https://image.civitai.com/a",
            "type": "image", "meta": {"workflow": "x" * (2500 * 1024)}}]))
        result = self.provider.lookup(self.identity, {})
        self.assertEqual(len(result["images"]), 1)
        self.assertNotIn("workflow", json.dumps(result))

    def test_metadata_response_still_has_a_hard_size_limit(self):
        self.answers.append(b"x" * (8 * 1024**2 + 1))
        with self.assertRaises(ProviderError) as raised:
            self.provider.lookup(self.identity, {})
        self.assertIn("大小限制", str(raised.exception))

    def test_404_offline_and_bounded_rate_limit(self):
        for code, status in ((404, "not_found"), (403, "restricted"), (429, "rate_limited")):
            self.answers.extend([HTTPError("https://civitai.com/a", code, "secret-response", {}, None)
                                 for _ in range(3 if code == 429 else 1)])
            with self.assertRaises(ProviderError) as context:
                self.provider.lookup(self.identity, {})
            self.assertEqual(context.exception.status, status)
            self.assertNotIn("secret-response", str(context.exception))
        self.answers.append(URLError("network contains credential"))
        with self.assertRaises(ProviderError) as context:
            self.provider.lookup(self.identity, {})
        self.assertEqual(context.exception.status, "offline")

    def test_unfilled_triggers_are_unknown_not_none(self):
        self.answers.append(self.response(trainedWords=[]))
        self.assertEqual(self.provider.lookup(self.identity, {})["fields"]["trigger_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
