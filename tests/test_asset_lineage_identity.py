"""Synthetic identity regressions; no production DB, credentials or providers."""
import copy
import functools
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from backend import asset_index as index
from backend.services import generation_policy as policy


def asset(asset_id, task_id, file="source.png", refs=()):
    lineage = index._lineage_from_params({"lineage": {"reference_assets": list(refs)}})
    return {"id": asset_id, "asset_id": asset_id, "taskId": task_id,
            "file": file, "imageUrl": "/archive_image/day/" + file,
            "title": file, "createdAt": 1, "index": 0,
            "lineage": lineage, "referenceAssets": lineage["referenceAssets"],
            "referenceAssetIds": lineage["referenceAssetIds"]}


class LineageIdentityTests(unittest.TestCase):
    def test_legacy_task_id_resolves_to_real_asset_and_reverse_links(self):
        source = asset("asset_source", "gpt_source")
        ref = {"asset_id": "gpt_source", "task_id": "gpt_source",
               "image_url": "/gpt_outputs/source.png"}
        first = asset("asset_edit", "edit", "edit.png", [ref])
        second = asset("asset_upscale", "upscale", "upscale.png", [ref])
        original = copy.deepcopy(first["lineage"])
        index._decorate_lineage([source, first, second])
        self.assertEqual(first["referenceAssetIds"], ["asset_source"])
        self.assertFalse(first["referenceAssets"][0].get("missing"))
        self.assertEqual(first["referenceAssets"][0]["imageUrl"], source["imageUrl"])
        self.assertEqual(first["lineage"]["reference_asset_ids"], ["asset_source"])
        self.assertEqual(source["derivedCount"], 2)
        self.assertEqual(first["relatedAssets"][0]["id"], "asset_upscale")
        self.assertEqual(original["reference_asset_ids"], ["gpt_source"])

    def test_task_only_reference_is_resolved(self):
        source = asset("asset_source", "source")
        child = asset("asset_child", "child", refs=[{"task_id": "source"}])
        index._decorate_lineage([source, child])
        self.assertEqual(child["referenceAssets"][0]["asset_id"], "asset_source")

    def test_exact_asset_id_has_priority_and_clears_stale_missing(self):
        source = asset("asset_source", "source")
        child = asset("asset_child", "child", refs=[{"asset_id": "asset_source"}])
        child["referenceAssets"][0].update(missing=True, deleted=True)
        index._decorate_lineage([source, child])
        self.assertFalse(child["referenceAssets"][0].get("missing"))
        self.assertFalse(child["referenceAssets"][0].get("deleted"))

    def test_multiple_outputs_match_filename_not_reference_position(self):
        first = asset("asset_a", "source", "a.png")
        second = asset("asset_b", "source", "b.png")
        child = asset("asset_child", "child", refs=[{
            "asset_id": "source", "task_id": "source", "index": 0,
            "image_url": "http://localhost/gpt_outputs/b.png?v=1"}])
        index._decorate_lineage([first, second, child])
        self.assertEqual(child["referenceAssetIds"], ["asset_b"])

    def test_two_references_from_same_task_are_not_dropped(self):
        refs = [{"asset_id": "source", "task_id": "source", "file": file}
                for file in ("a.png", "b.png")]
        child = asset("asset_child", "child", refs=refs)
        self.assertEqual(len(child["referenceAssets"]), 2)
        index._decorate_lineage([asset("asset_a", "source", "a.png"),
                                 asset("asset_b", "source", "b.png"), child])
        self.assertEqual(child["referenceAssetIds"], ["asset_a", "asset_b"])

    def test_ambiguous_or_mismatched_source_is_not_guessed(self):
        for files, locator in [(["a.png", "b.png"], {}),
                               (["a.png"], {"file": "deleted.png"}),
                               (["a.png", "a.png"], {"file": "a.png"})]:
            with self.subTest(files=files, locator=locator):
                sources = [asset("asset_" + str(i), "source", f) for i, f in enumerate(files)]
                child = asset("asset_child", "child", refs=[{
                    "asset_id": "source", "task_id": "source", **locator}])
                index._decorate_lineage(sources + [child])
                self.assertTrue(child["referenceAssets"][0]["missing"])

    def test_deleted_asset_does_not_match_other_task_by_filename(self):
        child = asset("asset_child", "child", refs=[{
            "asset_id": "gone", "task_id": "gone", "file": "source.png"}])
        index._decorate_lineage([asset("asset_other", "other"), child])
        self.assertTrue(child["referenceAssets"][0]["missing"])

    def test_missing_variant_resolves_against_full_index(self):
        source = asset("asset_source", "source")
        child = asset("asset_child", "child", refs=[{"asset_id": "source", "task_id": "source"}])
        index._decorate_lineage([child], lookup_assets=[source, child])
        self.assertEqual(child["referenceAssetIds"], ["asset_source"])

    def test_redecoration_is_idempotent(self):
        assets = [asset("asset_source", "source"), asset("asset_child", "child", refs=[{
            "asset_id": "source", "task_id": "source"}])]
        index._decorate_lineage(assets)
        original = copy.deepcopy(assets)
        index._decorate_lineage(assets)
        self.assertEqual(assets, original)


class LineageRequestTests(unittest.TestCase):
    normalize = staticmethod(functools.partial(policy._normalize_lineage_reference,
        _short_text=policy._short_text, _stable_lineage_url=policy._stable_lineage_url))

    def test_task_id_never_written_as_asset_id(self):
        for field in ("asset_id", "assetId", "id"):
            with self.subTest(field=field):
                ref = self.normalize({field: "source", "task_id": "source", "file": "a.png"})
                self.assertEqual(ref["asset_id"], "")
                self.assertEqual(ref["task_id"], "source")

    def test_valid_and_remote_ids_are_preserved(self):
        for aid in ("asset_source", "pinterest_123"):
            self.assertEqual(self.normalize({"asset_id": aid, "task_id": "source"})["asset_id"], aid)

    def test_request_dedup_keeps_different_files_of_one_task(self):
        refs = [{"asset_id": "source", "task_id": "source", "file": f} for f in ("a.png", "b.png", "a.png")]
        lineage = policy._extract_lineage_payload({"reference_assets": refs}, _normalize_lineage_reference=self.normalize)
        self.assertEqual(len(lineage["reference_assets"]), 2)
        self.assertEqual(lineage["reference_asset_ids"], [])
        self.assertEqual(lineage["source_task_ids"], ["source"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for desktop adapter regression")
    def test_desktop_adapter_serializes_old_canvas_without_id_mixup(self):
        root = Path(__file__).resolve().parents[1]
        script = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ctx = {window: {}, api: {json: async (url, options) => JSON.parse(options.body)},
  DesktopState: {state: {output: {}, params: {}}, normalizeRatio: x => x, normalizeResolution: x => x}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
(async () => {
  const refs = ['a.png', 'b.png', 'a.png'].map(file => ({assetId: 'source', taskId: 'source',
    file, base64: 'data:image/png;base64,AA=='}));
  const before = JSON.stringify(refs);
  const body = await ctx.window.DesktopApi.submitTaskConfig({provider: 'google', prompt: 'synthetic', referenceImages: refs});
  assert.equal(body.lineage.reference_assets.length, 2);
  assert.equal(body.lineage.reference_asset_ids.length, 0);
  assert.equal(body.lineage.reference_assets[0].task_id, 'source');
  assert.equal(JSON.stringify(refs), before);
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
        result = subprocess.run([
            shutil.which("node"),
            "-e",
            script,
            str(root / "frontend/scripts/desktop-tasks.js"),
            str(root / "frontend/scripts/desktop-api.js"),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
