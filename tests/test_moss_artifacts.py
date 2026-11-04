import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from backend import asset_index as index
from backend.moss import artifacts
from backend.moss.artifacts import publish_artifacts
from backend.moss.layout import grid_geometry

TASK_ID = "moss_" + "ab" * 16


def coordinate_image(path, width, height):
    """Every pixel encodes its own position, so one wrong offset cannot pass."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (x % 256, y % 256, (x // 256) * 16 + y // 256)
    image.save(path, format="PNG")


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = self.root / "job"
        self.job.mkdir()
        self.archive = self.root / "archive"
        self.sent, self.sidecars = [], []

    def task(self, rows=2, cols=2, width=512, height=512, mode="storyboard", margin=8, gutter=8, **params):
        ids = [f"p{index}" for index in range(rows * cols)]
        draft = {"rows": rows, "cols": cols, "panels": [{"id": item, "caption": f"cap-{item}"} for item in ids]}
        coordinate_image(self.job / "output.png", width, height)
        return {"task_id": TASK_ID, "status": "processing", "prompt": "最终提示词",
                "params": {"mode": mode, "split_panels": mode == "storyboard", "draw_grid": False,
                           "telegram_enabled": False, "raw_prompt": "原文", "layout_draft": draft,
                           "prompt_hash": "p" * 64, "geometry_hash": "g" * 64,
                           "text_sources": [{"field": "prompt", "content_hash": "c" * 64}],
                           "geometry_spec": grid_geometry(width, height, rows, cols, margin, gutter, ids), **params}}

    def publish(self, task, **options):
        result = {"paths": [self.job / "output.png"], "seed": 7, "effective": {"preset": "turbo"},
                  "generation_timing": {"schema_version": 1, "local_inference": True, "total_seconds": 1.0}}
        return publish_artifacts(TASK_ID, task, options.pop("result", result), job_dir=self.job,
                                 daily_output_dir=lambda: self.archive,
                                 write_prompt_sidecar=lambda path, prompt, txt_path: self.sidecars.append(path.name),
                                 send_document=options.pop("send", lambda path, caption: self.sent.append(path)),
                                 **options)


class Cropping(Base):
    def test_every_grid_shape_crops_exact_source_pixels_without_resizing(self):
        for rows, cols, width, height in ((2, 2, 512, 512), (1, 3, 768, 256), (3, 1, 256, 768), (2, 3, 1024, 576),
                                          (3, 3, 1024, 1024), (3, 2, 512, 512)):
            with self.subTest(rows=rows, cols=cols):
                self.archive = self.root / f"a{rows}{cols}{width}"
                task = self.task(rows, cols, width, height)
                outcome = self.publish(task)
                with Image.open(self.archive / outcome["result_file"]) as image:
                    original = image.copy()
                self.assertEqual(original.tobytes(), Image.open(self.job / "output.png").tobytes())
                panels = outcome["artifacts"][1:]
                self.assertEqual(len(panels), rows * cols)
                for panel, expected in zip(panels, task["params"]["geometry_spec"]["panels"]):
                    self.assertEqual(panel["source_bbox"], expected["bbox"])
                    with Image.open(self.archive / panel["file"]) as image:
                        crop = image.copy()
                    x1, y1, x2, y2 = expected["bbox"]
                    self.assertEqual((crop.width, crop.height), (x2 - x1, y2 - y1))
                    self.assertEqual(crop.tobytes(), original.crop((x1, y1, x2, y2)).tobytes())

    def test_overlay_is_separate_and_marks_neither_original_nor_panels(self):
        outcome = self.publish(self.task(draw_grid=True))
        roles = [item["role"] for item in outcome["artifacts"]]
        self.assertEqual(roles, ["original", *["panel"] * 4, "grid_overlay"])
        self.assertEqual(len(outcome["result_files"]), 5)
        overlay = outcome["artifacts"][-1]
        self.assertTrue((self.archive / overlay["file"]).is_file())
        source = Image.open(self.job / "output.png")
        self.assertEqual(Image.open(self.archive / outcome["result_file"]).tobytes(), source.tobytes())
        bbox = outcome["artifacts"][1]["source_bbox"]
        self.assertEqual(Image.open(self.archive / outcome["result_files"][1]).tobytes(), source.crop(bbox).tobytes())
        self.assertNotEqual(Image.open(self.archive / overlay["file"]).tobytes(), source.tobytes())

    def test_overlay_directory_stays_out_of_the_archive_scan(self):
        self.publish(self.task(draw_grid=True))
        with patch.object(index, "archive_scan_roots", return_value=[("archive", self.archive)]):
            names = [path.name for path, _, _ in index._archive_image_files()]
        self.assertEqual(len(names), 5)
        self.assertFalse([name for name in names if "grid" in name])


class Delivery(Base):
    def test_split_on_gives_original_first_then_panels_in_order(self):
        outcome = self.publish(self.task())
        self.assertEqual(outcome["result_files"][0], f"{TASK_ID}_1.png")
        self.assertEqual(outcome["result_files"][1:], [f"{TASK_ID}_1_p0{n}.png" for n in range(1, 5)])
        self.assertEqual([item.get("panel_index") for item in outcome["artifacts"][1:]], [0, 1, 2, 3])
        self.assertTrue(all(item["original_ref"] == f"{TASK_ID}_1.png" for item in outcome["artifacts"][1:]))
        self.assertEqual(outcome["status"], "succeeded_no_telegram")

    def test_split_off_keeps_only_the_original(self):
        outcome = self.publish(self.task(split_panels=False))
        self.assertEqual(len(outcome["result_files"]), 1)

    def test_other_modes_never_split(self):
        outcome = self.publish(self.task(mode="layout", split_panels=True))
        self.assertEqual(len(outcome["artifacts"]), 1)

    def test_telegram_sends_only_the_original_once(self):
        outcome = self.publish(self.task(telegram_enabled=True))
        self.assertEqual([path.name for path in self.sent], [f"{TASK_ID}_1.png"])
        self.assertEqual(outcome["status"], "succeeded")

    def test_telegram_failure_keeps_every_file(self):
        def fail(*_args):
            raise RuntimeError("telegram down")

        outcome = self.publish(self.task(telegram_enabled=True), send=fail)
        self.assertEqual(outcome["status"], "telegram_failed")
        self.assertIn("down", outcome["telegram_error"])
        self.assertTrue(all((self.archive / name).is_file() for name in outcome["result_files"]))

    def test_files_are_recorded_before_telegram(self):
        order = []
        self.publish(self.task(telegram_enabled=True), send=lambda *_: order.append("telegram"),
                     on_archived=lambda outcome: order.append(outcome["status"]))
        self.assertEqual(order, ["succeeded_no_telegram", "telegram"])

    def test_split_failure_keeps_the_job_and_the_original(self):
        task = self.task()
        task["params"]["geometry_spec"]["panels"][-1]["bbox"] = [0, 0, 9999, 9999]
        outcome = self.publish(task, send=lambda *_: None)
        self.assertEqual(outcome["status"], "succeeded_no_telegram")
        self.assertEqual(len(outcome["result_files"]), 1)
        self.assertIn("切图失败", outcome["warnings"][0])

    def test_failure_midway_leaves_no_partial_panels(self):
        real = artifacts._write_panel
        calls = []

        def flaky(*args):
            calls.append(1)
            if len(calls) == 3:
                raise OSError("disk full")
            return real(*args)

        with patch.object(artifacts, "_write_panel", flaky):
            outcome = self.publish(self.task())
        self.assertEqual(len(outcome["artifacts"]), 1)
        self.assertEqual([path.name for path in self.archive.glob("*_p*")], [])
        self.assertTrue((self.archive / outcome["result_file"]).is_file())


class Records(Base):
    def test_original_sidecar_traces_every_version_of_the_text(self):
        outcome = self.publish(self.task())
        record = json.loads((self.archive / f"{TASK_ID}_1.moss.json").read_text())
        self.assertEqual(record["prompt"], "最终提示词")
        self.assertEqual(record["raw_prompt"], "原文")
        self.assertEqual(record["seed"], 7)
        self.assertEqual(record["effective"], {"preset": "turbo"})
        self.assertEqual(record["text_sources"][0]["field"], "prompt")
        self.assertEqual(record["layout_draft"]["rows"], 2)
        self.assertEqual((self.archive / f"{TASK_ID}_1.txt").read_text(), "最终提示词\n")
        self.assertEqual(outcome["params"]["effective"], {"preset": "turbo"})

    def test_negative_prompt_is_kept_in_both_sidecars(self):
        self.publish(self.task(negative_prompt="模糊"))
        record = json.loads((self.archive / f"{TASK_ID}_1.moss.json").read_text())
        self.assertEqual(record["negative_prompt"], "模糊")
        self.assertEqual((self.archive / f"{TASK_ID}_1.txt").read_text(), "最终提示词\n\nnegative_prompt: 模糊\n")

    def test_panel_sidecar_points_at_the_page_and_claims_no_seed_of_its_own(self):
        self.publish(self.task())
        record = json.loads((self.archive / f"{TASK_ID}_1_p02.moss.json").read_text())
        self.assertEqual((record["original_ref"], record["panel_id"], record["caption"]),
                         (f"{TASK_ID}_1.png", "p1", "cap-p1"))
        self.assertEqual((record["seed"], record["seed_scope"]), (7, "page"))
        self.assertIn(f"{TASK_ID}_1_p02.png", self.sidecars)


class Boundaries(Base):
    def test_cancel_at_the_boundary_publishes_nothing(self):
        task = self.task(telegram_enabled=True)
        task["status"] = "canceled"
        outcome = self.publish(task)
        self.assertFalse(outcome["published"])
        self.assertEqual(outcome["status"], "canceled")
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.sent, [])

    def test_repeat_publish_keeps_the_record_and_never_resends(self):
        task = self.task(telegram_enabled=True)
        first = self.publish(task)
        repeated = {**task, "status": first["status"], "result_file": first["result_file"],
                    "result_files": first["result_files"], "params": first["params"]}
        again = self.publish(repeated)
        self.assertFalse(again["published"])
        self.assertEqual(again["status"], "succeeded")
        self.assertEqual(again["result_files"], first["result_files"])
        self.assertEqual(len(self.sent), 1)

    def test_paths_outside_the_job_are_rejected(self):
        outside = self.root / "other.png"
        Image.new("RGB", (4, 4)).save(outside)
        with self.assertRaisesRegex(ValueError, "结果文件"):
            self.publish(self.task(), result={"paths": [outside], "seed": 1})

    def test_multiple_or_missing_results_are_rejected(self):
        task = self.task()
        for paths in ([], [self.job / "output.png"] * 2, [self.job / "missing.png"]):
            with self.assertRaisesRegex(ValueError, "结果文件"):
                self.publish(task, result={"paths": paths, "seed": 1})

    def test_unsafe_task_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "任务 ID"):
            publish_artifacts("../evil", self.task(), {"paths": []}, job_dir=self.job, daily_output_dir=lambda: self.archive,
                              write_prompt_sidecar=None, send_document=None)

    def test_disk_failure_never_reports_success_and_keeps_saved_original(self):
        real = Path.write_text

        def failing(path, *args, **kwargs):
            if path.name.endswith(artifacts.SIDECAR_SUFFIX):
                raise OSError("disk full")
            return real(path, *args, **kwargs)

        with patch.object(Path, "write_text", failing), self.assertRaises(OSError):
            self.publish(self.task(telegram_enabled=True))
        self.assertTrue((self.archive / f"{TASK_ID}_1.png").is_file())
        self.assertEqual(self.sent, [])


class AssetProjection(Base):
    def assets(self, outcome, task):
        item = {"task_id": TASK_ID, "type": "moss-image", "prompt": task["prompt"], "status": outcome["status"],
                "created_at": 1, "result_file": outcome["result_file"], "result_files": outcome["result_files"],
                "params": outcome["params"]}
        return index._task_assets(item, {})

    def test_roles_provider_and_order(self):
        task = self.task()
        assets = self.assets(self.publish(task), task)
        self.assertEqual([item["assetRole"] for item in assets], ["original", *["panel"] * 4])
        self.assertEqual([item.get("panelIndex") for item in assets[1:]], [0, 1, 2, 3])
        self.assertEqual((assets[0]["provider"], assets[0]["providerLabel"], assets[0]["mainModel"]),
                         ("moss", "MOSS", "MOSS"))

    def test_panels_resolve_to_the_original_and_it_counts_them(self):
        task = self.task()
        assets = self.assets(self.publish(task), task)
        index._decorate_lineage(assets)
        original, panels = assets[0], assets[1:]
        self.assertEqual(original["derivedCount"], 4)
        for panel in panels:
            self.assertEqual(panel["referenceAssetIds"], [original["id"]])
            self.assertNotEqual(panel["referenceAssetIds"], [panel["id"]])
            self.assertFalse(panel["referenceAssets"][0]["missing"])
        self.assertEqual(original["referenceAssets"], [])

    def test_deleted_original_leaves_panels_marked_missing(self):
        task = self.task()
        assets = self.assets(self.publish(task), task)[1:]
        index._decorate_lineage(assets)
        for panel in assets:
            self.assertTrue(panel["referenceAssets"][0]["missing"])
            self.assertEqual(panel["assetRole"], "panel")

    def test_archive_view_and_card_projection_keep_the_role(self):
        task = self.task()
        outcome = self.publish(task)
        template = self.assets(outcome, task)[1]
        path = self.archive / template["file"]
        asset = index._archive_asset_from_path(path, "archive", path.name, {}, template, True)
        self.assertEqual((asset["assetRole"], asset["panelIndex"]), ("panel", 0))
        self.assertEqual(asset["referenceAssets"][0]["file"], f"{TASK_ID}_1.png")
        card = index._asset_card_projection(asset)
        self.assertEqual((card["assetRole"], card["panelIndex"]), ("panel", 0))

    def test_filename_prefix_identifies_moss_archives(self):
        self.assertEqual(index._infer_archive_provider(Path(f"{TASK_ID}_1_p01.png")), "moss")

    def test_tasks_without_artifacts_are_unchanged(self):
        assets = index._task_assets({"task_id": "t", "type": "qwen21", "result_file": "a.png", "params": {}}, {})
        self.assertNotIn("assetRole", assets[0])


if __name__ == "__main__":
    unittest.main()
