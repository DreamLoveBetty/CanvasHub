import json
import unittest

from backend.moss import contracts
from backend.moss.layout import DEFAULT_TEXT_CAPTION, compile_layout, grid_geometry, import_draft


def item(**fields):
    return {"id": "a", "label": "object", "caption": "青瓷茶壶", "bbox": [0, 0, 512, 256], **fields}


def grid(rows=2, cols=2, margin=8, gutter=8, captions=None, **fields):
    captions = captions or [f"第{i + 1}格" for i in range(rows * cols)]
    return {"rows": rows, "cols": cols, "margin": margin, "gutter": gutter,
            "panels": [{"id": f"p{i}", "caption": text} for i, text in enumerate(captions)], **fields}


class TextModeTests(unittest.TestCase):
    def test_passes_prompt_through_unchanged(self):
        result = compile_layout("text", 1024, 1024, None, "第一行\n第二行")
        self.assertEqual(result["prompt"], "第一行\n第二行")
        self.assertIsNone(result["geometry_spec"])
        self.assertIsNone(result["geometry_hash"])
        self.assertEqual(len(result["prompt_hash"]), 64)
        self.assertEqual(result["warnings"], [])


class FreeLayoutTests(unittest.TestCase):
    def compile(self, *items, summary=None, width=1024, height=1024, prompt="春日茶饮"):
        draft = {"items": list(items)}
        if summary is not None:
            draft["summary"] = summary
        return json.loads(compile_layout("layout", width, height, draft, prompt)["prompt"])

    def test_golden_official_centering(self):
        self.assertEqual(self.compile(item())["items"][0]["bbox"], [-512, -512, -256, 0])

    def test_floor_ceil_with_nine_digit_rounding(self):
        box = self.compile(item(bbox=[10.2, 20.7, 100.1, 200.1]))["items"][0]["bbox"]
        self.assertEqual(box, [20 - 512, 10 - 512, 201 - 512, 101 - 512])
        box = self.compile(item(bbox=[10.0000000001, 20, 100, 200]))["items"][0]["bbox"]
        self.assertEqual(box[1], 10 - 512)

    def test_non_square_uses_each_half(self):
        box = self.compile(item(bbox=[0, 0, 1280, 720]), width=1280, height=720)["items"][0]["bbox"]
        self.assertEqual(box, [-360, -640, 360, 640])

    def test_output_shape_has_no_ui_fields(self):
        result = compile_layout("layout", 1024, 1024, {"items": [item(tags=["柔光"], palette=["#fff"])]}, "春\n日")
        payload = json.loads(result["prompt"])
        self.assertEqual(set(payload), {"summary", "items", "bbox_coord_space", "bbox_format"})
        self.assertEqual(payload["summary"]["caption"], "春\n日")
        self.assertEqual((payload["bbox_coord_space"], payload["bbox_format"]), ("abs_centralized", "yxyx"))
        self.assertEqual(set(payload["items"][0]), {"label", "caption", "bbox", "tags", "palette"})
        self.assertIn("春\\n日", result["prompt"])
        self.assertNotIn(" ", result["prompt"])
        self.assertIsNone(result["geometry_spec"])

    def test_text_item_defaults_caption_and_needs_literal_text(self):
        payload = self.compile(item(label="text", caption="", text="山野茶事"))
        self.assertEqual(payload["items"][0]["caption"], DEFAULT_TEXT_CAPTION)
        self.assertEqual(payload["items"][0]["text"], "山野茶事")
        with self.assertRaisesRegex(ValueError, "文案"):
            self.compile(item(label="text", caption="标题"))
        with self.assertRaisesRegex(ValueError, "文案"):
            self.compile(item(label="text", text="   "))

    def test_object_needs_caption(self):
        with self.assertRaisesRegex(ValueError, "描述"):
            self.compile(item(caption="  "))

    def test_overlap_allowed(self):
        payload = self.compile(item(id="a"), item(id="b", bbox=[100, 0, 400, 200]))
        self.assertEqual(len(payload["items"]), 2)

    def test_rejects_bad_boxes(self):
        boxes = ([0, 0, 0, 10], [10, 0, 0, 10], [0, 0, 1025, 10], [-1, 0, 10, 10], [0, 0, 10],
                 [0, 0, float("nan"), 10], [0, 0, float("inf"), 10], [0, 0, 10**400, 10], [True, 0, 10, 10],
                 ["0", 0, 10, 10], "x")
        for box in boxes:
            with self.assertRaises(ValueError):
                self.compile(item(bbox=box))

    def test_rejects_duplicate_ids_unknown_fields_bad_labels(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            self.compile(item(), item())
        with self.assertRaisesRegex(ValueError, "x"):
            self.compile(item(x=1))
        with self.assertRaisesRegex(ValueError, "类型"):
            self.compile(item(label="person"))
        with self.assertRaisesRegex(ValueError, "x"):
            self.compile(item(), summary={"x": 1})
        with self.assertRaisesRegex(ValueError, "canvas"):
            self.compile(item(), summary={"canvas": "grid"})

    def test_needs_global_text_and_at_least_one_bounded_region(self):
        with self.assertRaisesRegex(ValueError, "全局描述"):
            self.compile(item(), prompt="  ")
        with self.assertRaisesRegex(ValueError, "区域"):
            self.compile()
        many = [item(id=str(i)) for i in range(contracts.MAX_FREE_REGIONS + 1)]
        with self.assertRaisesRegex(ValueError, "64"):
            self.compile(*many)


class GridGeometryTests(unittest.TestCase):
    def test_two_by_two_golden(self):
        spec = grid_geometry(1024, 1024, 2, 2, 8, 8, ["a", "b", "c", "d"])
        self.assertEqual([panel["bbox"] for panel in spec["panels"]],
                         [[8, 8, 508, 508], [516, 8, 1016, 508], [8, 516, 508, 1016], [516, 516, 1016, 1016]])
        self.assertEqual([panel["panel_id"] for panel in spec["panels"]], ["a", "b", "c", "d"])
        self.assertEqual([panel["index"] for panel in spec["panels"]], [0, 1, 2, 3])
        self.assertEqual({key: spec[key] for key in ("width", "height", "rows", "cols", "margin", "gutter")},
                         {"width": 1024, "height": 1024, "rows": 2, "cols": 2, "margin": 8, "gutter": 8})

    def test_every_grid_stays_inside_without_overlap(self):
        for rows, cols in ((1, 3), (3, 1), (2, 2), (2, 3), (3, 2), (2, 4), (4, 2), (3, 3)):
            for width, height in ((1024, 1024), (1280, 720), (720, 1280), (1920, 1088)):
                ids = [str(i) for i in range(rows * cols)]
                spec = grid_geometry(width, height, rows, cols, 8, 8, ids)
                boxes = [panel["bbox"] for panel in spec["panels"]]
                for x1, y1, x2, y2 in boxes:
                    self.assertTrue(8 <= x1 < x2 <= width - 8 and 8 <= y1 < y2 <= height - 8)
                for i, a in enumerate(boxes):
                    for b in boxes[i + 1:]:
                        self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
                self.assertEqual(boxes[-1][2], width - 8)
                self.assertEqual(boxes[-1][3], height - 8)

    def test_remainder_differs_by_at_most_one_pixel(self):
        spec = grid_geometry(1024, 1024, 3, 3, 8, 8, [str(i) for i in range(9)])
        widths = {panel["bbox"][2] - panel["bbox"][0] for panel in spec["panels"]}
        self.assertEqual(widths, {330, 331})
        self.assertEqual(sum(p["bbox"][2] - p["bbox"][0] for p in spec["panels"][:3]) + 16 + 16, 1024)

    def test_rejects_unsupported_shapes(self):
        for rows, cols, margin, gutter in ((1, 2, 8, 8), (5, 2, 8, 8), (0, 2, 8, 8), (2, 2, 300, 8), (2, 2, -1, 8),
                                           (2, 2, 200, 256)):
            with self.assertRaises(ValueError):
                grid_geometry(512, 512, rows, cols, margin, gutter, [str(i) for i in range(max(rows * cols, 0))])

    def test_rejects_wrong_or_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "格数"):
            grid_geometry(1024, 1024, 2, 2, 8, 8, ["a"])
        with self.assertRaisesRegex(ValueError, "重复"):
            grid_geometry(1024, 1024, 2, 2, 8, 8, ["a", "a", "b", "c"])


class StoryboardTests(unittest.TestCase):
    def test_structured_prompt_golden(self):
        captions = ["茶园晨雾", "取茶入壶", "注水冲泡", "端杯品茶"]
        result = compile_layout("storyboard", 1024, 1024, grid(captions=captions), "春日茶饮")
        payload = json.loads(result["prompt"])
        self.assertEqual(payload["summary"], {"caption": "单一画布，严格对称 2×2 网格，恰好 4 个面板，细白线分隔；春日茶饮"})
        self.assertEqual([entry["caption"] for entry in payload["items"]], captions)
        self.assertEqual(payload["items"][0], {"label": "object", "caption": "茶园晨雾", "bbox": [-504, -504, -4, -4]})
        self.assertEqual((payload["bbox_coord_space"], payload["bbox_format"]), ("abs_centralized", "yxyx"))

    def test_items_and_crop_share_one_geometry(self):
        result = compile_layout("storyboard", 1280, 720, grid(), "茶")
        payload = json.loads(result["prompt"])
        for entry, panel in zip(payload["items"], result["geometry_spec"]["panels"]):
            x1, y1, x2, y2 = panel["bbox"]
            self.assertEqual(entry["bbox"], [y1 - 360, x1 - 640, y2 - 360, x2 - 640])

    def test_empty_global_keeps_only_declaration(self):
        payload = json.loads(compile_layout("storyboard", 1024, 1024, grid(), "  ")["prompt"])
        self.assertEqual(payload["summary"]["caption"], "单一画布，严格对称 2×2 网格，恰好 4 个面板，细白线分隔")

    def test_empty_cell_blocks_submission(self):
        with self.assertRaisesRegex(ValueError, "第 2 格"):
            compile_layout("storyboard", 1024, 1024, grid(captions=["a", " ", "c", "d"]), "茶")

    def test_panel_count_must_match(self):
        draft = grid()
        draft["panels"].pop()
        with self.assertRaisesRegex(ValueError, "格数"):
            compile_layout("storyboard", 1024, 1024, draft, "茶")

    def test_rejects_unknown_fields(self):
        draft = grid()
        draft["panels"][0]["bbox"] = [0, 0, 1, 1]
        with self.assertRaisesRegex(ValueError, "bbox"):
            compile_layout("storyboard", 1024, 1024, draft, "茶")
        with self.assertRaisesRegex(ValueError, "canvas"):
            compile_layout("storyboard", 1024, 1024, grid(summary={"canvas": "multi_panel"}), "茶")

    def test_conflicting_count_warns_without_rewriting(self):
        for text in ("六宫格，春日茶饮", "恰好 6 个面板", "9 panels"):
            result = compile_layout("storyboard", 1024, 1024, grid(), text)
            self.assertEqual([warning["code"] for warning in result["warnings"]], ["panel_count_conflict"])
            self.assertIn(text, result["prompt"])
        same = compile_layout("storyboard", 1024, 1024, grid(), "恰好 4 个面板，春日茶饮")
        self.assertNotIn("panel_count_conflict", [w["code"] for w in same["warnings"]])
        plain = compile_layout("storyboard", 1024, 1024, grid(), "第8格没有，3个人喝茶")
        self.assertEqual(plain["warnings"], [])

    def test_small_cells_warn(self):
        result = compile_layout("storyboard", 1024, 1024, grid(rows=3, cols=3), "茶")
        self.assertEqual(result["warnings"], [])
        result = compile_layout("storyboard", 512, 512, grid(rows=3, cols=3), "茶")
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["small_panels"])

    def test_hashes_are_stable_and_change_with_geometry(self):
        one = compile_layout("storyboard", 1024, 1024, grid(), "茶")
        two = compile_layout("storyboard", 1024, 1024, grid(), "茶")
        other = compile_layout("storyboard", 1024, 1024, grid(gutter=16), "茶")
        self.assertEqual(one["geometry_hash"], two["geometry_hash"])
        self.assertEqual(one["prompt_hash"], two["prompt_hash"])
        self.assertNotEqual(one["geometry_hash"], other["geometry_hash"])


class ImportTests(unittest.TestCase):
    def official(self, **fields):
        return {"width": 1024, "height": 1024, "bbox_coord_space": "abs", "bbox_format": "xyxy",
                "summary": {"caption": "春日", "canvas": "single"},
                "items": [{"label": "text", "caption": "标题", "text": "山野", "bbox": [0, 0, 512, 256]}], **fields}

    def own(self, **fields):
        return {"schema": "canvashub.moss.layout", "schema_version": 1, "mode": "layout", "width": 1024,
                "height": 1024, "prompt": "春日", "prompt_source": {"kind": "inline"},
                "free_draft": {"items": [{"id": "a", "label": "object", "caption": "壶", "bbox": [0, 0, 10, 10],
                                          "caption_source": {"kind": "inline"}}]},
                "grid_draft": {"rows": 2, "cols": 2, "margin": 8, "gutter": 8,
                               "panels": [{"id": "p", "caption": ""}]}, **fields}

    def load(self, value):
        return import_draft(json.dumps(value, ensure_ascii=False))

    def test_official_draft_becomes_inline_own_draft(self):
        receipt = self.load(self.official())
        self.assertEqual(receipt["kind"], "import_draft")
        self.assertIs(receipt["requires_source_resolution"], False)
        draft = receipt["draft"]
        self.assertEqual((draft["mode"], draft["prompt"], draft["width"]), ("layout", "春日", 1024))
        self.assertEqual(draft["free_draft"]["summary"], {"canvas": "single"})
        self.assertEqual(draft["free_draft"]["items"][0]["id"], "item-1")
        self.assertEqual(draft["free_draft"]["items"][0]["text"], "山野")

    def test_official_caption_draft(self):
        receipt = self.load({"caption": "一杯茶"})
        self.assertEqual((receipt["draft"]["mode"], receipt["draft"]["prompt"]), ("text", "一杯茶"))
        self.assertIs(receipt["requires_source_resolution"], False)

    def test_official_rejects_compiled_or_invalid_drafts(self):
        cases = ({"bbox_coord_space": "abs_centralized"}, {"bbox_format": "yxyx"}, {"width": 1000},
                 {"items": []}, {"extra": 1}, {"width": 4096})
        for fields in cases:
            with self.assertRaises(ValueError):
                self.load(self.official(**fields))
        with self.assertRaises(ValueError):
            self.load({"summary": {"caption": "x"}, "items": []})

    def test_own_draft_keeps_sources_without_looking_up_nodes(self):
        value = self.own()
        value["free_draft"]["items"][0].update(caption="", caption_source={"kind": "text_node", "node_id": "n9"})
        receipt = self.load(value)
        self.assertIs(receipt["requires_source_resolution"], True)
        self.assertEqual(receipt["draft"]["free_draft"]["items"][0]["caption_source"],
                         {"kind": "text_node", "node_id": "n9"})

    def test_inline_own_draft_needs_no_resolution(self):
        self.assertIs(self.load(self.own())["requires_source_resolution"], False)

    def test_global_source_counts(self):
        value = self.own(prompt="", prompt_source={"kind": "text_node", "node_id": "n1"})
        self.assertIs(self.load(value)["requires_source_resolution"], True)

    def test_inactive_draft_may_be_incomplete(self):
        self.assertEqual(self.load(self.own())["draft"]["grid_draft"]["panels"][0]["caption"], "")

    def test_active_inline_content_is_checked(self):
        value = self.own()
        value["free_draft"]["items"][0]["caption"] = " "
        with self.assertRaisesRegex(ValueError, "描述"):
            self.load(value)
        with self.assertRaisesRegex(ValueError, "第 1 格"):
            self.load(self.own(mode="storyboard"))
        value = self.own(mode="storyboard")
        value["grid_draft"]["panels"][0]["caption"] = "茶园"
        with self.assertRaisesRegex(ValueError, "格数"):
            self.load(value)

    def test_own_rejects_unknown_version_fields_and_sources(self):
        for fields in ({"schema_version": 2}, {"job_id": "x"}, {"model_path": "/x"},
                       {"prompt_source": {"kind": "text_node"}}, {"prompt_source": {"kind": "other"}},
                       {"prompt_source": {"kind": "inline", "node_id": "n"}}, {"mode": "edit"}):
            with self.assertRaises(ValueError):
                self.load(self.own(**fields))

    def test_rejects_duplicate_keys_in_original_text(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            import_draft('{"caption": "a", "caption": "b"}')

    def test_unknown_shape(self):
        with self.assertRaises(ValueError):
            self.load({"foo": 1})


if __name__ == "__main__":
    unittest.main()
