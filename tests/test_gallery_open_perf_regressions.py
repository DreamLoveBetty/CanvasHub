#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local regression tests for the gallery-open performance fixes (kept uncommitted).

Covers:
1. list_asset_sets short-circuits without running the full asset scan when no sets exist.
2. _thumb_url prefers pre-generated sidecar thumbnails and falls back to the original.
3. ensure_webp_thumbnail dedupes concurrent generation of the same cache key.
4. thumbnail lock entries remain shared across a failed leader and waiting retries.
5. /api/auth/verify token reuse keeps a still-fresh token byte-identical.
"""

from contextlib import closing
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from backend import asset_index
from backend import thumb_cache
from backend import server as server_mod


class ListAssetSetsShortCircuitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "assets.db"
        self._db_patch = mock.patch.object(asset_index, "DB_PATH", self.db_path)
        self._db_patch.start()
        asset_index.init_asset_store()

    def tearDown(self):
        self._db_patch.stop()
        self.tmp.cleanup()

    def test_empty_sets_skip_full_asset_scan(self):
        def _fail(*args, **kwargs):
            raise AssertionError("_asset_map_for_sets must not run when asset_sets is empty")

        with mock.patch.object(asset_index, "_asset_map_for_sets", _fail):
            data = asset_index.list_asset_sets(limit=120, offset=0)
        self.assertEqual(data["sets"], [])
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["limit"], 120)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(data["tags"], [])

    def test_existing_sets_still_resolve_assets(self):
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO asset_sets (set_id, name, asset_ids_json, asset_snapshots_json,
                                        tags_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("set_test1", "测试集", '["asset_a"]',
                 '[{"asset_id": "asset_a", "id": "asset_a", "title": "快照标题"}]',
                 "[]", "active", now, now),
            )
        with mock.patch.object(asset_index, "_asset_map_for_sets", return_value={}):
            data = asset_index.list_asset_sets(limit=10, offset=0)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["sets"][0]["id"], "set_test1")
        # 快照兜底仍然生效
        self.assertEqual(data["sets"][0]["assets"][0]["asset_id"], "asset_a")


class SidecarThumbSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "gpt_outputs").mkdir()
        (self.root / "google_outputs").mkdir()
        self._patch = mock.patch.object(asset_index, "APP_DATA_DIR", self.root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def _write_png(self, rel_path, side=400):
        target = self.root / rel_path
        Image.new("RGB", (side, side), (10, 120, 200)).save(target, "PNG")
        return target

    def test_gpt_sidecar_preferred(self):
        self._write_png("gpt_outputs/gen_1_thumb.png", side=400)
        url = asset_index._thumb_url("gpt", "gen_1.png", "/gpt_outputs/gen_1.png")
        self.assertIn("gen_1_thumb.png", url)
        self.assertTrue(url.startswith("/thumb/"))

    def test_gpt_without_sidecar_falls_back(self):
        url = asset_index._thumb_url("gpt", "gen_2.png", "/gpt_outputs/gen_2.png")
        self.assertIn("gen_2.png", url)
        self.assertNotIn("_thumb", url)

    def test_google_sidecar_preferred(self):
        self._write_png("google_outputs/thumb_img.png", side=420)
        url = asset_index._thumb_url("google", "img.png", "/image/img.png")
        self.assertIn("thumb_img.png", url)

    def test_google_without_sidecar_falls_back(self):
        url = asset_index._thumb_url("google", "img2.png", "/image/img2.png")
        self.assertIn("img2.png", url)
        self.assertNotIn("thumb_", url)

    def test_empty_file_name_falls_back(self):
        url = asset_index._thumb_url("gpt", "", "/gpt_outputs/x.png")
        self.assertIn("x.png", url)

    def test_undersized_legacy_sidecar_rejected(self):
        # 旧版 300px google sidecar 不足以喂 420px 请求，应回退原图
        self._write_png("google_outputs/thumb_small.png", side=300)
        url = asset_index._thumb_url("google", "small.png", "/image/small.png")
        self.assertNotIn("thumb_small", url)
        self.assertIn("small.png", url)

    def test_corrupt_sidecar_rejected(self):
        (self.root / "gpt_outputs" / "gen_bad_thumb.png").write_bytes(b"not a png")
        url = asset_index._thumb_url("gpt", "gen_bad.png", "/gpt_outputs/gen_bad.png")
        self.assertNotIn("_thumb", url)

    def test_edited_original_rejects_stale_sidecar(self):
        import os
        sidecar = self._write_png("gpt_outputs/gen_e_thumb.png", side=400)
        original = self._write_png("gpt_outputs/gen_e.png", side=1024)
        # 原图被就地编辑：mtime 比 sidecar 晚 120s（超过 60s 容差）
        late = sidecar.stat().st_mtime + 120
        os.utime(original, (late, late))
        url = asset_index._thumb_url("gpt", "gen_e.png", "/gpt_outputs/gen_e.png")
        self.assertNotIn("_thumb", url)

    def test_archive_copy_lag_within_tolerance_keeps_sidecar(self):
        import os
        sidecar = self._write_png("gpt_outputs/gen_f_thumb.png", side=400)
        original = self._write_png("gpt_outputs/gen_f.png", side=1024)
        # 归档搬运写入延迟（<60s 容差）不应放弃 sidecar
        near = sidecar.stat().st_mtime + 30
        os.utime(original, (near, near))
        url = asset_index._thumb_url("gpt", "gen_f.png", "/gpt_outputs/gen_f.png")
        self.assertIn("gen_f_thumb.png", url)

    def test_archive_original_path_used_for_freshness(self):
        import os
        sidecar = self._write_png("gpt_outputs/gen_g_thumb.png", side=400)
        archive_file = self._write_png("gpt_outputs/gen_g_archive.png", side=1024)
        late = sidecar.stat().st_mtime + 600
        os.utime(archive_file, (late, late))
        url = asset_index._thumb_url("gpt", "gen_g.png", "/archive_image/x/gen_g.png",
                                     original_path=archive_file)
        self.assertNotIn("_thumb", url)


class ThumbGenerationDedupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_root = Path(self.tmp.name) / "cache"
        self.source = Path(self.tmp.name) / "source.png"
        Image.new("RGB", (800, 600), (200, 40, 40)).save(self.source, "PNG")
        self._patch = mock.patch.object(thumb_cache, "THUMB_CACHE_ROOT", self.cache_root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_concurrent_requests_decode_once(self):
        original_open = thumb_cache.Image.open
        calls = []
        lock = threading.Lock()

        def counting_open(*args, **kwargs):
            with lock:
                calls.append(1)
            return original_open(*args, **kwargs)

        barrier = threading.Barrier(4)
        results, errors = [], []

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(thumb_cache.ensure_webp_thumbnail(self.source, size=420))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        with mock.patch.object(thumb_cache.Image, "open", side_effect=counting_open):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual(len({str(p) for p in results}), 1)
        self.assertTrue(results[0].is_file())
        self.assertEqual(len(calls), 1, "同一缩略图并发生成应只解码一次")
        self.assertEqual(thumb_cache._GEN_LOCKS, {}, "生成完成后锁表应清空")

    def test_cached_hit_skips_lock_and_decode(self):
        first = thumb_cache.ensure_webp_thumbnail(self.source, size=420)
        with mock.patch.object(thumb_cache.Image, "open",
                               side_effect=AssertionError("缓存命中不应再解码")):
            second = thumb_cache.ensure_webp_thumbnail(self.source, size=420)
        self.assertEqual(first, second)

    def test_different_cache_keys_generate_in_parallel(self):
        second_source = Path(self.tmp.name) / "source-two.png"
        Image.new("RGB", (640, 480), (40, 80, 200)).save(second_source, "PNG")
        original_open = thumb_cache.Image.open
        both_opened = threading.Barrier(2)
        entered = []
        state_lock = threading.Lock()
        results = []
        errors = []

        def synchronized_open(*args, **kwargs):
            with state_lock:
                entered.append(Path(args[0]).name)
            both_opened.wait(timeout=5)
            return original_open(*args, **kwargs)

        def worker(source):
            try:
                results.append(thumb_cache.ensure_webp_thumbnail(source, size=420))
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(thumb_cache.Image, "open", side_effect=synchronized_open):
            threads = [
                threading.Thread(target=worker, args=(self.source,)),
                threading.Thread(target=worker, args=(second_source,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(set(entered), {self.source.name, second_source.name})
        self.assertEqual(len(results), 2)
        self.assertTrue(all(path.is_file() for path in results))
        self.assertEqual(thumb_cache._GEN_LOCKS, {})

    def test_failed_leader_keeps_waiters_on_the_same_lock(self):
        original_open = thumb_cache.Image.open
        first_opened = threading.Event()
        release_first = threading.Event()
        retry_opened = threading.Event()
        release_retry = threading.Event()
        state_lock = threading.Lock()
        open_calls = 0
        active_calls = 0
        max_active_calls = 0
        results = {}
        errors = {}

        def controlled_open(*args, **kwargs):
            nonlocal open_calls, active_calls, max_active_calls
            with state_lock:
                open_calls += 1
                call_number = open_calls
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                if call_number == 1:
                    first_opened.set()
                    if not release_first.wait(timeout=5):
                        raise TimeoutError("timed out releasing the failed leader")
                    raise OSError("forced first thumbnail decode failure")
                if call_number == 2:
                    retry_opened.set()
                    if not release_retry.wait(timeout=5):
                        raise TimeoutError("timed out releasing the waiting retry")
                return original_open(*args, **kwargs)
            finally:
                with state_lock:
                    active_calls -= 1

        def worker(name):
            try:
                results[name] = thumb_cache.ensure_webp_thumbnail(self.source, size=420)
            except Exception as exc:
                errors[name] = exc

        cache_key = str(thumb_cache.thumb_cache_path(self.source, size=420))

        def wait_for_users(expected):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with thumb_cache._GEN_LOCKS_GUARD:
                    entry = thumb_cache._GEN_LOCKS.get(cache_key)
                    if entry is not None and entry.users >= expected:
                        return
                time.sleep(0.01)
            self.fail(f"thumbnail lock did not reach {expected} users")

        leader = threading.Thread(target=worker, args=("leader",))
        waiter = threading.Thread(target=worker, args=("waiter",))
        third = threading.Thread(target=worker, args=("third",))
        threads = (leader, waiter, third)

        try:
            with mock.patch.object(thumb_cache.Image, "open", side_effect=controlled_open):
                leader.start()
                self.assertTrue(first_opened.wait(timeout=5))

                waiter.start()
                wait_for_users(2)
                release_first.set()
                self.assertTrue(retry_opened.wait(timeout=5))
                leader.join(timeout=5)
                self.assertFalse(leader.is_alive())

                third.start()
                wait_for_users(2)
                time.sleep(0.05)
                with state_lock:
                    self.assertEqual(open_calls, 2)
                    self.assertEqual(max_active_calls, 1)

                release_retry.set()
                waiter.join(timeout=5)
                third.join(timeout=5)
        finally:
            release_first.set()
            release_retry.set()
            for thread in threads:
                thread.join(timeout=5)

        self.assertIsInstance(errors.get("leader"), OSError)
        self.assertNotIn("waiter", errors)
        self.assertNotIn("third", errors)
        self.assertEqual(set(results), {"waiter", "third"})
        self.assertEqual(results["waiter"], results["third"])
        self.assertTrue(results["waiter"].is_file())
        self.assertEqual(open_calls, 2)
        self.assertEqual(max_active_calls, 1)
        self.assertEqual(thumb_cache._GEN_LOCKS, {})


class _FakeVerifyRequest:
    """Minimal stand-in exposing what _presented_auth_token/_reusable_auth_token read."""

    def __init__(self, header_token="", cookie_token="", path="/api/auth/verify"):
        headers = {}
        if header_token:
            headers[server_mod.AUTH_HEADER_NAME] = header_token
        self.headers = headers
        self.path = path
        self._cookie_token = cookie_token

    def _get_cookie_value(self, name):
        return self._cookie_token if name == server_mod.AUTH_COOKIE_NAME else ""

    _presented_auth_token = server_mod.RequestHandler._presented_auth_token
    _reusable_auth_token = server_mod.RequestHandler._reusable_auth_token


class AuthTokenReuseTest(unittest.TestCase):
    def setUp(self):
        self._pw_patch = mock.patch.object(server_mod, "AUTH_PASSWORD", "test-pass-123")
        self._pw_patch.start()

    def tearDown(self):
        self._pw_patch.stop()

    def test_fresh_token_reused_verbatim(self):
        token = server_mod._build_auth_cookie_value()
        req = _FakeVerifyRequest(header_token=token)
        self.assertEqual(req._reusable_auth_token(), token)

    def test_fresh_cookie_token_reused(self):
        token = server_mod._build_auth_cookie_value()
        req = _FakeVerifyRequest(cookie_token=token)
        self.assertEqual(req._reusable_auth_token(), token)

    def test_query_token_reused(self):
        token = server_mod._build_auth_cookie_value()
        from urllib.parse import quote
        req = _FakeVerifyRequest(path=f"/api/auth/verify?miniappAuth={quote(token)}")
        self.assertEqual(req._reusable_auth_token(), token)

    def test_token_past_half_life_not_reused(self):
        stale_issued = int(time.time()) - server_mod.AUTH_COOKIE_MAX_AGE // 2 - 60
        token = server_mod._build_auth_cookie_value(issued_at=stale_issued)
        # 仍在总有效期内（能通过校验），但超过半程 → 应换新
        self.assertTrue(server_mod._verify_auth_cookie_value(token))
        req = _FakeVerifyRequest(header_token=token)
        self.assertEqual(req._reusable_auth_token(), "")

    def test_tampered_token_not_reused(self):
        token = server_mod._build_auth_cookie_value()
        payload, signature = token.split(".", 1)
        bad = f"{payload}.{'0' * len(signature)}"
        req = _FakeVerifyRequest(header_token=bad)
        self.assertEqual(req._reusable_auth_token(), "")

    def test_expired_token_not_reused(self):
        expired_issued = int(time.time()) - server_mod.AUTH_COOKIE_MAX_AGE - 60
        token = server_mod._build_auth_cookie_value(issued_at=expired_issued)
        req = _FakeVerifyRequest(header_token=token)
        self.assertEqual(req._reusable_auth_token(), "")

    def test_missing_token_not_reused(self):
        req = _FakeVerifyRequest()
        self.assertEqual(req._reusable_auth_token(), "")

    def test_non_ascii_query_token_does_not_crash(self):
        # 回归：%FF%FE 解码为非 ASCII，hmac.compare_digest 会抛 TypeError，必须被吞掉而不是 500
        req = _FakeVerifyRequest(path="/api/auth/verify?miniappAuth=1700000000.%FF%FE")
        self.assertEqual(req._reusable_auth_token(), "")

    def test_non_ascii_header_token_does_not_crash(self):
        req = _FakeVerifyRequest(header_token="1700000000.��")
        self.assertEqual(req._reusable_auth_token(), "")


if __name__ == "__main__":
    unittest.main()
