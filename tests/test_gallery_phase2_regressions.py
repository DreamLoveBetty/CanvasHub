#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local regression tests for gallery phase-2 (persistent index cache + card projection + gzip).

Hermetic: patches archive roots / DBs to a temp dir; never touches real data.
Kept uncommitted per project convention.
"""

import gzip
import io
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from PIL import Image

from backend import asset_index
from backend import server as server_mod
from tests.legacy_css import read_legacy_css
from tests.history_js import read_history_js


def _reset_asset_index_caches():
    asset_index.invalidate_asset_index_cache()
    asset_index.IMAGE_INFO_CACHE.clear()
    with asset_index._FILE_META_LOCK:
        asset_index._FILE_META_ROWS = None
        asset_index._FILE_META_PENDING.clear()


class _HermeticIndexEnv:
    """Patch asset_index onto a temp archive root + temp DBs."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.archive_root = root / "archive"
        self.archive_root.mkdir()
        (self.archive_root / "2026-07-26").mkdir()
        self.assets_db = root / "assets.db"
        self.tasks_db = root / "tasks.db"
        self.tasks_db.write_bytes(b"")
        self.history_file = root / "history.jsonl"  # 不存在
        self.patches = [
            mock.patch.object(asset_index, "DB_PATH", self.assets_db),
            mock.patch.object(asset_index, "TASKS_DB_PATH", str(self.tasks_db)),
            mock.patch.object(asset_index, "HISTORY_FILE", self.history_file),
            mock.patch.object(asset_index, "APP_DATA_DIR", root),
            mock.patch.object(asset_index, "archive_scan_roots", lambda: [("main", self.archive_root)]),
            mock.patch.object(asset_index, "get_all_tasks", lambda limit=50, offset=0: []),
        ]

    def add_image(self, name, prompt="", day="2026-07-26", side=64):
        target = self.archive_root / day / name
        Image.new("RGB", (side, side), (30, 60, 90)).save(target, "PNG")
        if prompt:
            target.with_suffix(".txt").write_text(prompt, encoding="utf-8")
        return target

    def start(self):
        for p in self.patches:
            p.start()
        _reset_asset_index_caches()

    def stop(self):
        _reset_asset_index_caches()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class IndexCacheTest(unittest.TestCase):
    def setUp(self):
        self.env = _HermeticIndexEnv()
        self.env.add_image("a.png", prompt="第一张 提示词 alpha")
        self.env.add_image("b.png", prompt="第二张 提示词 beta")
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_second_request_hits_cache(self):
        asset_index.list_assets(limit=10)
        with mock.patch.object(asset_index, "_build_index_variants",
                               side_effect=AssertionError("缓存命中时不应重建")):
            data = asset_index.list_assets(limit=10, offset=1)
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["assets"]), 1)

    def test_new_archive_file_invalidates_via_fingerprint(self):
        data1 = asset_index.list_assets(limit=10)
        self.assertEqual(data1["total"], 2)
        time.sleep(0.02)
        self.env.add_image("c.png", prompt="第三张 gamma")
        data2 = asset_index.list_assets(limit=10)
        self.assertEqual(data2["total"], 3, "新增归档文件应通过目录指纹触发重建")

    def test_meta_update_invalidates_cache(self):
        data1 = asset_index.list_assets(limit=10)
        aid = data1["assets"][0]["id"]
        asset_index.update_asset_meta(aid, favorite=True)
        data2 = asset_index.list_assets(limit=10)
        hit = next(a for a in data2["assets"] if a["id"] == aid)
        self.assertTrue(hit["favorite"])

    def test_get_asset_returns_deepcopy(self):
        data = asset_index.list_assets(limit=10)
        aid = data["assets"][0]["id"]
        got = asset_index.get_asset(aid)
        got["title"] = "被调用方改写"
        got["tags"].append("polluted")
        again = asset_index.get_asset(aid)
        self.assertNotEqual(again["title"], "被调用方改写")
        self.assertNotIn("polluted", again["tags"])

    def test_persistent_file_meta_survives_process_cache_reset(self):
        asset_index.list_assets(limit=10)  # 建立持久化缓存并落库
        # 模拟重启：清空进程内缓存
        asset_index.IMAGE_INFO_CACHE.clear()
        with asset_index._FILE_META_LOCK:
            asset_index._FILE_META_ROWS = None
        asset_index.invalidate_asset_index_cache()
        original_open = asset_index.Image.open
        with mock.patch.object(asset_index.Image, "open", side_effect=original_open) as mocked:
            data = asset_index.list_assets(limit=10)
        self.assertEqual(data["total"], 2)
        self.assertEqual(mocked.call_count, 0, "持久化缓存命中时不应再走 PIL 解码")

    def test_missing_variant_isolated_from_all_variant(self):
        # 两个变体应是独立对象（避免血缘装饰互相污染）
        variants = asset_index._get_index_variants()
        all_ids = {id(a) for a in variants["all"]["assets"]}
        missing_ids = {id(a) for a in variants["missing"]["assets"]}
        self.assertFalse(all_ids & missing_ids)


class CardProjectionTest(unittest.TestCase):
    def setUp(self):
        self.env = _HermeticIndexEnv()
        self.env.add_image("gen_x.png", prompt="卡片投影 测试提示词")
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_card_drops_heavy_fields_keeps_sync_flow_fields(self):
        data = asset_index.list_assets(limit=10, fields="card")
        card = data["assets"][0]
        # 同步流程必需字段
        for key in ("prompt", "file", "type", "provider", "thumbUrl", "imageUrl",
                    "archiveRelPath", "hasTaskRecord", "derivedCount", "createdAt",
                    "favorite", "hidden", "tags"):
            self.assertIn(key, card, f"卡片缺少同步流程字段 {key}")
        # 重字段必须砍掉
        for key in ("revisedPrompt", "revised_prompt", "lineage", "derivedAssets", "relatedAssets"):
            self.assertNotIn(key, card, f"卡片不应包含重字段 {key}")
        self.assertEqual(card["fieldsMode"], "card")
        if isinstance(card.get("params"), dict):
            self.assertNotIn("revised_prompt", card["params"])

    def test_default_mode_keeps_full_shape(self):
        data = asset_index.list_assets(limit=10)
        asset = data["assets"][0]
        for key in ("revisedPrompt", "revised_prompt", "lineage", "derivedAssets", "relatedAssets", "params"):
            self.assertIn(key, asset)
        self.assertNotIn("fieldsMode", asset)
        self.assertEqual(sorted(data.keys()), ["assets", "limit", "offset", "stats", "tags", "total"])

    def test_card_projection_does_not_mutate_cache(self):
        card = asset_index.list_assets(limit=10, fields="card")["assets"][0]
        card["title"] = "改写卡片"
        if isinstance(card.get("params"), dict):
            card["params"]["injected"] = True
        full = asset_index.list_assets(limit=10)["assets"][0]
        self.assertNotEqual(full["title"], "改写卡片")
        self.assertNotIn("injected", full.get("params", {}))

    def test_pagination_offsets_consistent(self):
        self.env.add_image("gen_y.png", prompt="第二张")
        self.env.add_image("gen_z.png", prompt="第三张")
        asset_index.invalidate_asset_index_cache()
        page1 = asset_index.list_assets(limit=2, offset=0, fields="card")
        page2 = asset_index.list_assets(limit=2, offset=2, fields="card")
        self.assertEqual(page1["total"], 3)
        ids1 = {a["id"] for a in page1["assets"]}
        ids2 = {a["id"] for a in page2["assets"]}
        self.assertFalse(ids1 & ids2, "分页不应重叠")
        self.assertEqual(len(ids1) + len(ids2), 3)


class ReviewFixesTest(unittest.TestCase):
    """对抗审查坐实问题的回归锁定。"""

    def setUp(self):
        self.env = _HermeticIndexEnv()
        self.img = self.env.add_image("gen_r.png", prompt="审查修复 测试提示词")
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_transient_sidecar_failure_not_cached(self):
        original = Path.read_text

        def flaky_read(self_path, *args, **kwargs):
            if self_path.suffix == ".txt":
                raise OSError("transient EIO")
            return original(self_path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", flaky_read):
            data1 = asset_index.list_assets(limit=10)
        self.assertEqual(data1["assets"][0].get("prompt"), "", "读失败时本次返回空提示词")
        # 失败不应落缓存：恢复后重建能拿到真实提示词
        asset_index.invalidate_asset_index_cache()
        data2 = asset_index.list_assets(limit=10)
        self.assertEqual(data2["assets"][0].get("prompt"), "审查修复 测试提示词")

    def test_pil_failure_not_persisted(self):
        with mock.patch.object(asset_index.Image, "open", side_effect=OSError("EMFILE")):
            asset_index.list_assets(limit=10)
        # 模拟重启后重建：PIL 恢复，宽高应能解析出来（说明失败没有被持久化）
        _reset_asset_index_caches()
        data = asset_index.list_assets(limit=10)
        self.assertTrue(data["assets"][0].get("width"), "PIL 瞬时失败不应永久缓存为无尺寸")

    def test_vanished_file_rows_pruned_from_cache(self):
        import sqlite3 as _sq
        asset_index.list_assets(limit=10)  # 建缓存
        with closing(_sq.connect(self.env.assets_db)) as conn, conn:
            before = conn.execute("SELECT COUNT(*) FROM file_meta_cache").fetchone()[0]
        self.assertGreater(before, 0)
        # 删除文件 + sidecar 后重建，行应被清理
        self.img.with_suffix(".txt").unlink()
        self.img.unlink()
        time.sleep(0.02)
        self.env.add_image("gen_r2.png", prompt="新文件")  # 保证指纹变化且构建非空
        asset_index.list_assets(limit=10)
        with closing(_sq.connect(self.env.assets_db)) as conn, conn:
            rows = [r[0] for r in conn.execute("SELECT path FROM file_meta_cache")]
        self.assertFalse(any("gen_r.png" in r or "gen_r.txt" in r for r in rows), "消失文件的缓存行应被清理")

    def test_card_keeps_idless_reference_identity_fields(self):
        asset = {
            "id": "a1", "asset_id": "a1", "title": "x", "prompt": "p",
            "referenceAssets": [
                {"id": "ref1", "taskId": "t1", "index": 0, "title": "带id"},
                {"imageUrl": "/image/url_only.png", "title": "仅URL"},
                {"missing": True, "deleted": True, "title": "已删除来源"},
            ],
        }
        card = asset_index._asset_card_projection(asset)
        refs = card["referenceAssets"]
        self.assertEqual(len(refs), 3)
        self.assertEqual(refs[1].get("imageUrl"), "/image/url_only.png")
        self.assertTrue(refs[2].get("missing") and refs[2].get("deleted"))
        self.assertNotIn("title", refs[0], "快照内容字段不应保留")


class FrontendSourceGuardsTest(unittest.TestCase):
    """前端行为的源码级守护（沿用 tests/test_gallery_preview_backdrop.py 的模式）。"""

    @classmethod
    def setUpClass(cls):
        base = Path(__file__).resolve().parent.parent / "frontend"
        cls.js = read_history_js()

    def test_selection_prune_resolves_via_sets(self):
        self.assertIn("resolvableIds", self.js)
        self.assertIn("mergeAssetsFromSet(set)", self.js)

    def test_detail_hydration_shares_inflight_promise(self):
        self.assertIn("__detailPromise", self.js)
        self.assertNotIn("__detailPending", self.js)

    def test_load_more_has_generation_guard(self):
        self.assertIn("galleryAssetsGeneration", self.js)
        self.assertIn("const generation = ++galleryAssetsGeneration;", self.js)
        self.assertIn("generation !== galleryAssetsGeneration", self.js)
        self.assertIn("galleryAssetsFullLoading", self.js)
        self.assertIn("galleryAssetsFromIndex = false;", self.js)
        self.assertIn("galleryServerOffset = 0;", self.js)

    def test_load_more_reuses_inflight_promise(self):
        self.assertIn("let galleryLoadMorePromise = null;", self.js)
        self.assertIn("if (galleryLoadMorePromise) return galleryLoadMorePromise;", self.js)
        self.assertIn("galleryLoadMorePromise === requestPromise", self.js)
        self.assertIn("requestPromise.then(clearRequest, clearRequest);", self.js)
        self.assertNotIn("galleryAssetsLoadingMore", self.js)

    def test_load_more_tracks_server_offset_independently(self):
        self.assertIn("let galleryServerOffset = 0;", self.js)
        self.assertIn("function hasMoreGalleryAssets()", self.js)
        self.assertIn("const loadedCount = galleryAssetsFromIndex ? galleryServerOffset : 0;", self.js)
        self.assertIn("offset: requestOffset", self.js)
        self.assertNotIn("offset: galleryAssets.length", self.js)
        self.assertGreaterEqual(
            self.js.count("+ responseAssets.length;"),
            2,
            "初载和追加都必须按服务端响应原始条数推进 offset",
        )

    def test_membership_changing_meta_updates_rebase_pagination(self):
        self.assertIn("function shouldReloadGalleryAfterMetaPatch", self.js)
        self.assertIn("galleryFilter === 'favorite'", self.js)
        self.assertIn("Boolean(galleryQuery.trim() || galleryTag.trim())", self.js)
        self.assertGreaterEqual(
            self.js.count("await reloadGalleryAfterMetaPatch({ hidden: nextValue });"),
            2,
            "单张和批量隐藏都应在操作完成后各重载一次",
        )
        self.assertGreaterEqual(
            self.js.count("await reloadGalleryAfterMetaPatch({ tags });"),
            2,
            "单张和批量标签编辑都应在操作完成后各重载一次",
        )

    def test_preview_navigation_boundary_aware(self):
        self.assertIn("await loadMoreGalleryAssets();", self.js)
        self.assertIn("const previousLength = assets.length;", self.js)
        self.assertIn("currentIndex = getPreviewIndex();", self.js)
        self.assertIn("if (assets.length <= previousLength && hasMoreGalleryAssets()) return;", self.js)
        self.assertIn("if (direction < 0 && currentIndex <= 0 && pagedView && hasMoreGalleryAssets()) return;", self.js)
        self.assertIn("(currentIndex + direction + assets.length) % assets.length", self.js)

    def test_explicit_refresh_passes_flag(self):
        self.assertIn("loadGalleryAssets({ refresh: true })", self.js)

    def test_image_preview_distinguishes_krea_and_local_timing(self):
        self.assertIn("if (type.includes('krea2') || provider.includes('krea2')) return 'krea2';", self.js)
        self.assertIn("krea2: 'Krea2'", self.js)
        self.assertIn("function assetGenerationTiming", self.js)
        self.assertIn("raw?.local_inference === true", self.js)
        for label in ("加载模型用时", "推理用时", "降噪用时", "保存图片用时", "生成用时"):
            self.assertIn(label, self.js)

    def test_compare_divider_uses_transform_not_clippath(self):
        viewport = (Path(__file__).resolve().parent.parent / 'frontend/scripts/desktop-compare-viewport.js').read_text()
        self.assertNotIn('clipPath', viewport)
        self.assertIn('root.requestAnimationFrame(paint)', viewport)
        self.assertIn('overlay.style.transform = `translateX(-${hidden}px)`', viewport)
        self.assertIn('translate(${hidden + view.x}px, ${view.y}px) scale(${view.zoom})', viewport)

    def test_compare_uses_pointer_tracking(self):
        viewport = (Path(__file__).resolve().parent.parent / 'frontend/scripts/desktop-compare-viewport.js').read_text()
        self.assertIn('setPointerCapture', viewport)
        self.assertIn('releasePointerCapture', viewport)
        self.assertIn("'lostpointercapture'", viewport)

    def test_prompt_drawer_eyes_are_raf_coalesced(self):
        # 眼睛跟随是 document 级 pointermove：必须 rAF 合并 + 矩形缓存，否则拖慢全应用拖拽
        base = Path(__file__).resolve().parent.parent / "frontend"
        drawer = (base / "scripts" / "desktop-prompt-drawer.js").read_text(encoding="utf-8")
        self.assertIn("handleEyesRaf = window.requestAnimationFrame", drawer)
        self.assertIn("handleEyesRect", drawer)
        # 回归锁定：handler 本体不允许直接调用 getBoundingClientRect（只能在 rAF 内的缓存刷新处）
        body = drawer.split("function updatePromptDrawerHandleEyes", 1)[1].split("requestAnimationFrame", 1)[0]
        self.assertNotIn("getBoundingClientRect", body)

    def test_compare_divider_constrained_to_image_band(self):
        viewport = (Path(__file__).resolve().parent.parent / 'frontend/scripts/desktop-compare-viewport.js').read_text()
        self.assertIn('naturalWidth', viewport)
        self.assertIn('band.left + band.width * percent / 100', viewport)
        self.assertIn('const top = Math.max(0,', viewport)
        self.assertIn('const bottom = Math.min(height,', viewport)

    def test_compare_hides_occluded_glass_panels(self):
        # 真机探针实测：对比打开时背后图库面板的毛玻璃面每帧重算 → 18fps；隐藏后 100+fps
        self.assertIn("desk-under-compare", self.js)
        base = Path(__file__).resolve().parent.parent / "frontend"
        css = read_legacy_css()
        self.assertIn(".desk-gallery.desk-under-compare", css)
        self.assertIn(".desk-gallery-preview.desk-under-compare", css)
        # closeCompare 必须恢复
        close_body = self.js.split("function closeCompare", 1)[1].split("}", 1)[0]
        self.assertIn("remove('desk-under-compare')", close_body)

    def test_genie_snapshot_bakes_real_content(self):
        # 神灯快照必须烘焙计算样式 + 内联已加载图片像素（SVG-as-Image 禁网络、裸克隆无主题变量，
        # 旧管线会渲染成"白板"）；禁止再整包序列化 document.styleSheets
        self.assertIn("GENIE_BAKE_PROPS", self.js)
        self.assertIn("genieBakeElementStyles", self.js)
        self.assertIn("genieInlineImages", self.js)
        self.assertIn("toDataURL('image/webp'", self.js)
        snapshot_body = self.js.split("async function snapshotHistoryPanel", 1)[1].split("\n  async function", 1)[0]
        self.assertNotIn("document.styleSheets", snapshot_body)
        # outerHTML 是 HTML 序列化（img 不自闭合），SVG 严格 XML 解析必败 → 必须 XMLSerializer
        self.assertIn("new XMLSerializer().serializeToString(clone)", snapshot_body)
        self.assertNotIn("clone.outerHTML", snapshot_body)

    def test_compare_range_has_fine_step(self):
        # step=1 会把拖动量化成 101 个落点（宽舞台上 ~13px 死区，表现为"不跟手"）
        base = Path(__file__).resolve().parent.parent / "frontend"
        html = (base / "desktop.html").read_text(encoding="utf-8")
        range_tag = next(line for line in html.splitlines() if 'id="deskCompareRange"' in line)
        self.assertIn('step="0.1"', range_tag)


class _FakeJsonRequest:
    """Minimal handler stand-in for send_json gzip behavior."""

    send_json = server_mod.RequestHandler.send_json

    def __init__(self, accept_encoding=""):
        self.headers = {"Accept-Encoding": accept_encoding} if accept_encoding else {}
        self.wfile = io.BytesIO()
        self.sent_headers = {}
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass

    def _apply_cors_headers(self):
        pass


class SendJsonGzipTest(unittest.TestCase):
    def _payload(self, size):
        return {"text": "提示词内容ABC " * (size // 20)}

    def test_large_response_gzipped_when_accepted(self):
        req = _FakeJsonRequest(accept_encoding="gzip, deflate")
        req.send_json(self._payload(200_000))
        body = req.wfile.getvalue()
        self.assertEqual(req.sent_headers.get("Content-Encoding"), "gzip")
        self.assertEqual(int(req.sent_headers["Content-Length"]), len(body))
        decoded = json.loads(gzip.decompress(body))
        self.assertIn("text", decoded)

    def test_small_response_not_gzipped(self):
        req = _FakeJsonRequest(accept_encoding="gzip")
        req.send_json({"ok": True})
        self.assertNotIn("Content-Encoding", req.sent_headers)
        self.assertEqual(json.loads(req.wfile.getvalue()), {"ok": True})

    def test_no_accept_encoding_no_gzip(self):
        req = _FakeJsonRequest()
        req.send_json(self._payload(200_000))
        self.assertNotIn("Content-Encoding", req.sent_headers)
        json.loads(req.wfile.getvalue())  # 可直接解析


if __name__ == "__main__":
    unittest.main()
