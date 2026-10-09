"""Optional download placeholders are not installed Krea Base models."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from backend.krea2.contracts import BUILTIN_MODEL_IDS, DEFAULT_MODEL_ID, EXPORT_FORMATS
from backend.krea2.model_store import BaseModelStore


class KreaModelMenuTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = BaseModelStore(self.root / "assets", self.root / "component")
        self.weights = {key: self.root / f"{key}.safetensors" for key in BUILTIN_MODEL_IDS}
        pins = {key: {"size": 4} for key in self.weights}
        for patch in (mock.patch("backend.krea2.model_store.model_paths", return_value=self.weights),
                      mock.patch("backend.krea2.model_store.BUILDS", pins)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_first_install_keeps_default_but_not_missing_optional_mixed(self):
        models = self.store.list()
        self.assertEqual([model["id"] for model in models], [DEFAULT_MODEL_ID])
        self.assertFalse(models[0]["ready"])
        self.assertFalse(self.weights["mixed-4-8"].exists())

    def test_installed_mixed_remains_visible_and_loadable(self):
        self.weights["mixed-4-8"].write_bytes(b"tiny")
        model_id = BUILTIN_MODEL_IDS["mixed-4-8"]
        self.assertIn(model_id, [m["id"] for m in self.store.list()])
        self.assertTrue(self.store.resolve(model_id)["ready"])
        self.assertEqual(self.weights["mixed-4-8"].read_bytes(), b"tiny")

    def test_runtime_ready_status_is_respected_and_partial_mixed_stays_hidden(self):
        self.weights["mixed-4-8"].write_bytes(b"partial")
        self.assertNotIn(BUILTIN_MODEL_IDS["mixed-4-8"], [m["id"] for m in self.store.list()])
        models = self.store.list({"8bit": {"ready": True}, "mixed-4-8": {"ready": False}})
        self.assertEqual(len(models), 1)
        self.assertTrue(models[0]["ready"])
        self.assertEqual(self.weights["mixed-4-8"].read_bytes(), b"partial")

    def test_custom_mixed_export_and_other_formats_are_unchanged(self):
        stage = self.store.staging / "synthetic"
        stage.mkdir(parents=True)
        (stage / "transformer.safetensors").write_bytes(b"synthetic output")
        item = self.store.publish(stage, name="Custom Mixed", precision="mixed-4-8", source_name="fixture.safetensors",
                                  source_sha256="a"*64, output_sha256="b"*64, source_prefix="",
                                  source_tensor_count=430, output_tensor_count=878, quantized_linear_count=224)
        self.assertIn(item["id"], [m["id"] for m in self.store.list()])
        self.assertTrue(self.store.resolve(item["id"])["ready"])
        self.assertEqual(set(EXPORT_FORMATS), {"8bit", "mixed-4-8", "bf16"})


if __name__ == "__main__":
    unittest.main()
