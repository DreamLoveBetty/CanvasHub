import json
import unittest
from unittest import mock

from backend.moss import contracts
from backend.moss.contracts import (MAX_JSON_BYTES, MAX_TEXT_SOURCES, catalog, normalize_compile, normalize_job,
                                    strict_json_loads)

HASH = "a" * 64


def job(**fields):
    return {"mode": "text", "prompt": "春日茶饮", **fields}


def layout_job(**fields):
    return {"mode": "layout", "prompt": "", "layout_draft": {"items": []}, **fields}


def storyboard_job(**fields):
    return {"mode": "storyboard", "prompt": "", "layout_draft": {"panels": []}, **fields}


class StrictJsonTests(unittest.TestCase):
    def test_accepts_object_from_bytes_and_text(self):
        self.assertEqual(strict_json_loads(b'{"a": 1}'), {"a": 1})
        self.assertEqual(strict_json_loads('{"a": "茶"}'), {"a": "茶"})

    def test_rejects_duplicate_keys_at_any_depth(self):
        for raw in ('{"a": 1, "a": 2}', '{"x": {"a": 1, "a": 2}}'):
            with self.assertRaisesRegex(ValueError, "重复"):
                strict_json_loads(raw)

    def test_rejects_non_finite_numbers(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(ValueError):
                strict_json_loads(f'{{"a": {literal}}}')

    def test_rejects_non_object_invalid_and_oversized_input(self):
        for raw in ("[]", "1", "{", b"\xff"):
            with self.assertRaises(ValueError):
                strict_json_loads(raw)
        with self.assertRaisesRegex(ValueError, "256"):
            strict_json_loads(json.dumps({"a": "x" * MAX_JSON_BYTES}))

    def test_size_limit_counts_utf8_bytes_not_characters(self):
        with self.assertRaisesRegex(ValueError, "256"):
            strict_json_loads(json.dumps({"a": "茶" * (MAX_JSON_BYTES // 2)}, ensure_ascii=False))


class ModeTests(unittest.TestCase):
    def test_text_defaults(self):
        result = normalize_job(job(seed=7))
        self.assertEqual(result["mode"], "text")
        self.assertEqual(result["preset"], "turbo")
        self.assertEqual(result["base_model_id"], contracts.DEFAULT_MODEL_ID)
        self.assertEqual((result["width"], result["height"]), (1024, 1024))
        self.assertEqual(result["loras"], [])
        self.assertIs(result["telegram_enabled"], False)
        self.assertIsNone(result["layout_draft"])

    def test_text_needs_prompt_and_refuses_layout_input(self):
        with self.assertRaisesRegex(ValueError, "提示词"):
            normalize_job({"mode": "text", "prompt": "   "})
        with self.assertRaisesRegex(ValueError, "普通模式"):
            normalize_job(job(layout_draft={"items": []}))

    def test_layout_modes_need_a_draft_object(self):
        self.assertEqual(normalize_job(layout_job())["layout_draft"], {"items": []})
        self.assertEqual(normalize_job(storyboard_job())["layout_draft"], {"panels": []})
        for mode in ("layout", "storyboard"):
            for draft in (None, [], "x"):
                with self.assertRaisesRegex(ValueError, "草稿"):
                    normalize_job({"mode": mode, "prompt": "", "layout_draft": draft})

    def test_unknown_mode(self):
        with self.assertRaisesRegex(ValueError, "模式"):
            normalize_job(job(mode="edit"))

    def test_split_panels_defaults_on_for_storyboard_only(self):
        self.assertIs(normalize_job(storyboard_job())["split_panels"], True)
        self.assertIs(normalize_job(storyboard_job(split_panels=False))["split_panels"], False)
        self.assertIs(normalize_job(job())["split_panels"], False)
        self.assertIs(normalize_job(job(split_panels=True))["split_panels"], False)
        self.assertIs(normalize_job(layout_job(split_panels=True))["split_panels"], False)

    def test_draw_grid_only_on_storyboard(self):
        self.assertIs(normalize_job(storyboard_job(draw_grid=True))["draw_grid"], True)
        self.assertIs(normalize_job(storyboard_job())["draw_grid"], False)
        self.assertIs(normalize_job(job(draw_grid=False))["draw_grid"], False)
        for body in (job(draw_grid=True), layout_job(draw_grid=True)):
            with self.assertRaisesRegex(ValueError, "分镜"):
                normalize_job(body)


class SizeTests(unittest.TestCase):
    def test_accepts_limits(self):
        for width, height in ((256, 256), (1440, 1440), (1920, 1088), (2048, 1024), (1024, 2048)):
            result = normalize_job(job(width=width, height=height))
            self.assertEqual((result["width"], result["height"]), (width, height))

    def test_rejects_range_multiple_and_total_pixels(self):
        cases = (((240, 1024), "256"), ((2064, 256), "256"), ((1920, 1080), "16"), ((1032, 1024), "16"),
                 ((2048, 1040), "像素"), ((1456, 1456), "像素"))
        for (width, height), message in cases:
            with self.assertRaisesRegex(ValueError, message):
                normalize_job(job(width=width, height=height))

    def test_size_must_be_a_real_integer(self):
        for value in (True, 1024.0, "1024", None):
            with self.assertRaisesRegex(ValueError, "整数"):
                normalize_job(job(width=value))


class SeedTests(unittest.TestCase):
    def test_edges(self):
        self.assertEqual(normalize_job(job(seed=0))["seed"], 0)
        self.assertEqual(normalize_job(job(seed=2**32 - 1))["seed"], 2**32 - 1)
        for value in (-1, 2**32):
            with self.assertRaisesRegex(ValueError, "Seed"):
                normalize_job(job(seed=value))

    def test_blank_resolves_once_inside_range(self):
        for body in (job(), job(seed=None), job(seed="")):
            with mock.patch.object(contracts.secrets, "randbits", return_value=99) as randbits:
                self.assertEqual(normalize_job(body)["seed"], 99)
            randbits.assert_called_once_with(32)

    def test_rejects_bool_and_text(self):
        for value in (True, "7", "random", 1.5):
            with self.assertRaisesRegex(ValueError, "Seed"):
                normalize_job(job(seed=value))


class PresetTests(unittest.TestCase):
    def test_turbo_reports_real_schedule(self):
        result = normalize_job(job(preset="turbo", seed=1))
        sampler = result["sampler"]
        self.assertEqual((sampler["updates"], sampler["network_passes"]), (10, 15))
        self.assertEqual((sampler["teacher_cfg"], sampler["student_cfg"]), (3, 1))
        self.assertEqual(result["managed_adapters"], [{"id": "student", "scale": 1.0},
                                                      {"id": "destripe", "scale": 1.5}])

    def test_standard_has_no_student(self):
        result = normalize_job(job(preset="standard", seed=1))
        self.assertEqual((result["sampler"]["steps"], result["sampler"]["cfg"], result["sampler"]["shift"]),
                         (50, 3, 5))
        self.assertEqual(result["managed_adapters"], [{"id": "destripe", "scale": 1.5}])

    def test_job_copy_does_not_alias_preset_tables(self):
        result = normalize_job(job(seed=1))
        result["sampler"]["updates"] = 1
        result["managed_adapters"].clear()
        again = normalize_job(job(seed=1))
        self.assertEqual(again["sampler"]["updates"], 10)
        self.assertEqual(len(again["managed_adapters"]), 2)

    def test_unknown_preset_and_model(self):
        for value in ("fast", ["turbo"], {"id": "turbo"}, None):
            with self.assertRaisesRegex(ValueError, "预设"):
                normalize_job(job(preset=value))
        for value in ("../x", "A B", "x" * 200):
            with self.assertRaisesRegex(ValueError, "模型"):
                normalize_job(job(base_model_id=value))


class LoRATests(unittest.TestCase):
    def test_four_finite_strengths(self):
        loras = [{"asset_id": f"{i:x}" * 64, "scale": scale} for i, scale in enumerate((-20, 0, 0.7, 20))]
        result = normalize_job(job(loras=loras))["loras"]
        self.assertEqual([item["scale"] for item in result], [-20.0, 0.0, 0.7, 20.0])

    def test_rejects_too_many_duplicates_bad_id_and_extra_fields(self):
        many = [{"asset_id": f"{i:x}" * 64} for i in range(5)]
        for loras, message in ((many, "最多"), ([{"asset_id": HASH}, {"asset_id": HASH}], "重复"),
                               ([{"asset_id": "x"}], "资产"), ({}, "LoRA"), (["x"], "LoRA"),
                               ([{"asset_id": HASH, "path": "/tmp/a"}], "path")):
            with self.assertRaisesRegex(ValueError, message):
                normalize_job(job(loras=loras))

    def test_rejects_bad_scale(self):
        for scale in (True, "1", None, float("nan"), float("inf"), -20.5, 21, 10**400):
            with self.assertRaisesRegex(ValueError, "强度"):
                normalize_job(job(loras=[{"asset_id": HASH, "scale": scale}]))

    def test_scale_defaults_to_one(self):
        self.assertEqual(normalize_job(job(loras=[{"asset_id": HASH}]))["loras"][0]["scale"], 1.0)


class FieldBoundaryTests(unittest.TestCase):
    def test_rejects_sampling_overrides_tokens_paths_and_final_prompt(self):
        for name in ("steps", "guidance", "cfg", "shift", "sampler", "sigmas", "image_count",
                     "reference_upload_tokens", "model_path", "source_path", "final_prompt", "compiled_prompt"):
            with self.assertRaisesRegex(ValueError, name):
                normalize_job(job(**{name: 1}))

    def test_negative_prompt_feeds_the_sampler_for_both_presets(self):
        for preset in ("turbo", "standard"):
            normalized = normalize_job(job(preset=preset, negative_prompt="  模糊, 水印 "))
            self.assertEqual(normalized["negative_prompt"], "模糊, 水印")
            self.assertEqual(normalized["sampler"]["negative_prompt"], "模糊, 水印")
        self.assertEqual(normalize_job(job())["sampler"]["negative_prompt"], "")
        self.assertEqual(contracts.PRESETS["standard"]["sampler"]["negative_prompt"], "", "preset stays pristine")
        self.assertEqual(normalize_compile(job(negative_prompt="模糊"))["negative_prompt"], "模糊")
        for value in (1, None, ["x"]):
            with self.assertRaisesRegex(ValueError, "负面提示词必须是文本"):
                normalize_job(job(negative_prompt=value))
        with self.assertRaisesRegex(ValueError, "负面提示词过长"):
            normalize_job(job(negative_prompt="x" * (contracts.MAX_NEGATIVE_CHARS + 1)))

    def test_bool_fields_must_be_bool(self):
        for name in ("telegram_enabled", "draw_grid", "split_panels"):
            for value in (1, "true", None):
                with self.assertRaisesRegex(ValueError, "布尔"):
                    normalize_job(storyboard_job(**{name: value}))

    def test_body_must_be_object_and_prompt_text(self):
        for body in (None, [], "x"):
            with self.assertRaises(ValueError):
                normalize_job(body)
        with self.assertRaisesRegex(ValueError, "提示词"):
            normalize_job(job(prompt=1))

    def test_prompt_keeps_chinese_and_newlines(self):
        self.assertEqual(normalize_job(job(prompt="第一行\n第二行", seed=1))["prompt"], "第一行\n第二行")


class TextSourceTests(unittest.TestCase):
    def source(self, **fields):
        return {"source_node_id": "n1", "target_id": "global", "field": "prompt", "content_hash": HASH, **fields}

    def test_accepts_trace(self):
        source = self.source(source_alias="商品说明")
        self.assertEqual(normalize_job(job(text_sources=[source]))["text_sources"], [source])
        self.assertEqual(normalize_job(job())["text_sources"], [])

    def test_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "来源"):
            normalize_job(job(text_sources=[self.source()] * (MAX_TEXT_SOURCES + 1)))

    def test_rejects_canvas_payloads_and_instructions(self):
        for extra in ({"canvas": {}}, {"nodes": []}, {"execute": "x"}, {"text": "正文"}):
            with self.assertRaisesRegex(ValueError, next(iter(extra))):
                normalize_job(job(text_sources=[self.source(**extra)]))

    def test_rejects_bad_values(self):
        for fields in ({"field": "steps"}, {"content_hash": "x"}, {"source_node_id": ""},
                       {"source_node_id": "x" * 200}, {"target_id": 1}, {"source_alias": "x" * 200}):
            with self.assertRaises(ValueError):
                normalize_job(job(text_sources=[self.source(**fields)]))
        with self.assertRaises(ValueError):
            normalize_job(job(text_sources={}))


class CompileTests(unittest.TestCase):
    def test_compile_never_draws_a_seed(self):
        with mock.patch.object(contracts.secrets, "randbits") as randbits:
            result = normalize_compile({"mode": "text", "prompt": "茶", "input_fingerprint": "fp-1"})
        randbits.assert_not_called()
        self.assertEqual(result["kind"], "compile")
        self.assertEqual(result["input_fingerprint"], "fp-1")
        self.assertNotIn("seed", result)
        with self.assertRaisesRegex(ValueError, "seed"):
            normalize_compile({"mode": "text", "prompt": "茶", "seed": 1})

    def test_same_validation_as_jobs(self):
        with self.assertRaisesRegex(ValueError, "16"):
            normalize_compile({"mode": "text", "prompt": "茶", "width": 1000})
        with self.assertRaisesRegex(ValueError, "草稿"):
            normalize_compile({"mode": "layout", "prompt": ""})
        with self.assertRaisesRegex(ValueError, "普通模式"):
            normalize_compile({"mode": "text", "prompt": "茶", "layout_draft": {}})

    def test_draft_import_is_exclusive(self):
        result = normalize_compile({"draft_json": '{"a":1}'})
        self.assertEqual(result, {"kind": "import", "draft_json": '{"a":1}', "input_fingerprint": None})
        for extra in ({"prompt": "茶"}, {"mode": "text"}, {"layout_draft": {}}, {"width": 1024}):
            with self.assertRaisesRegex(ValueError, "互斥"):
                normalize_compile({"draft_json": "{}", **extra})

    def test_draft_import_must_be_bounded_text(self):
        for value in (1, "", "x" * (MAX_JSON_BYTES + 1)):
            with self.assertRaises(ValueError):
                normalize_compile({"draft_json": value})

    def test_rejects_bad_fingerprint(self):
        for value in (1, "", "x" * 200, "a b"):
            with self.assertRaisesRegex(ValueError, "指纹"):
                normalize_compile({"mode": "text", "prompt": "茶", "input_fingerprint": value})


class CatalogTests(unittest.TestCase):
    def test_lists_presets_limits_and_defaults(self):
        result = catalog([{"id": "m"}])
        self.assertEqual(result["models"], [{"id": "m"}])
        self.assertEqual([item["id"] for item in result["presets"]], ["turbo", "standard"])
        self.assertEqual(result["limits"]["dimension_multiple"], 16)
        self.assertEqual(result["limits"]["max_pixels"], 2_097_152)
        self.assertEqual(result["limits"]["max_tokens"], 4096)
        self.assertEqual(result["limits"]["free_regions"], 64)
        self.assertEqual(result["limits"]["lora_count"], 4)
        self.assertEqual(result["defaults"]["preset"], "turbo")
        self.assertEqual((result["defaults"]["width"], result["defaults"]["height"]), (1024, 1024))
        self.assertIs(result["defaults"]["split_panels"], True)

    def test_catalog_is_json_and_does_not_alias_tables(self):
        result = catalog()
        json.dumps(result, allow_nan=False)
        result["presets"][0]["sampler"]["updates"] = 1
        self.assertEqual(catalog()["presets"][0]["sampler"]["updates"], 10)


if __name__ == "__main__":
    unittest.main()
