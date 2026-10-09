import unittest
from pathlib import Path

from backend import asset_index
from backend.services.generation_timing import (
    normalize_generation_timing,
    task_total_seconds,
)
from backend.services.history_format import format_history_task


class GenerationTimingTests(unittest.TestCase):
    def test_remote_task_exposes_total_without_local_phases(self):
        task = {"started_at": 100.25, "finished_at": 112.75, "params": {}}
        self.assertEqual(task_total_seconds(task), 12.5)
        self.assertEqual(normalize_generation_timing(task["params"]), {})

    def test_local_timing_is_bounded_and_phase_scoped(self):
        timing = normalize_generation_timing({"generation_timing": {
            "local_inference": True,
            "model_load_seconds": 1.2,
            "inference_seconds": 2.3,
            "denoise_seconds": 3.4,
            "save_seconds": .5,
            "total_seconds": 7.4,
            "private_debug_value": "hidden",
        }})
        self.assertTrue(timing["local_inference"])
        self.assertEqual(timing["denoise_seconds"], 3.4)
        self.assertNotIn("private_debug_value", timing)

    def test_history_format_derives_total_duration(self):
        task = {
            "task_id": "remote-1", "type": "gpt", "status": "succeeded",
            "params": {}, "started_at": 200, "finished_at": 209,
            "created_at": 200, "updated_at": 209,
        }
        result = format_history_task(
            task,
            task_result_files=lambda value: (["result.png"], "result.png"),
            h3_task_type="h3-video",
            public_h3_params=lambda value: value,
            safe_basename=lambda value: Path(value).name,
        )
        self.assertEqual(result["duration"], 9)
        self.assertEqual(result["duration_seconds"], 9)

    def test_krea_asset_classification_and_timing(self):
        timing = {
            "schema_version": 1, "local_inference": True,
            "model_load_seconds": 1.0, "inference_seconds": 2.0,
            "denoise_seconds": 3.0, "save_seconds": 1.0,
            "total_seconds": 7.0,
        }
        task = {
            "task_id": "krea2_test", "type": "krea2-image", "status": "succeeded",
            "prompt": "portrait", "result_file": "krea2_test_1.png",
            "created_at": 100, "updated_at": 107, "started_at": 100, "finished_at": 107,
            "params": {
                "provider": "krea2-alis-mlx",
                "base_model_name": "Dark Beast",
                "generation_timing": timing,
            },
        }
        asset = asset_index._task_assets(task, {})[0]
        self.assertEqual(asset["provider"], "krea2")
        self.assertEqual(asset["providerLabel"], "Krea2")
        self.assertEqual(asset["mainModel"], "Krea2 · Dark Beast")
        self.assertEqual(asset["durationSeconds"], 7.0)
        self.assertEqual(asset["generationTiming"], timing)

    def test_krea_archive_filename_is_not_google(self):
        self.assertEqual(
            asset_index._infer_archive_provider(Path("/tmp/krea2_example_1.png")),
            "krea2",
        )


if __name__ == "__main__":
    unittest.main()
