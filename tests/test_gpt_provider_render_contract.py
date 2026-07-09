import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend import provider_gpt_codex


class GptProviderRenderContractTest(unittest.TestCase):
    def test_render_contract_prompt_locks_ratio_and_size(self):
        prompt = provider_gpt_codex._render_contract_prompt("make a cinematic poster", "16:9", "4k")

        self.assertIn("Final canvas aspect ratio must be exactly 16:9.", prompt)
        self.assertIn("3840x2160 pixels", prompt)
        self.assertIn("Do not reinterpret the canvas as vertical", prompt)
        self.assertIn("USER CREATIVE BRIEF:", prompt)
        self.assertTrue(prompt.endswith("make a cinematic poster"))

    def test_render_contract_warnings_detect_wrong_ratio_and_low_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "wrong.png"
            Image.new("RGB", (1003, 1568), "white").save(image_path)

            warnings = provider_gpt_codex._render_contract_warnings(image_path, "16:9", "4k")

        self.assertTrue(any("actual_ratio_mismatch" in item for item in warnings))
        self.assertTrue(any("actual_resolution_lower_than_requested" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
