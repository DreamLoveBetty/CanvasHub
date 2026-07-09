import unittest

from backend import asset_index
from backend.image_resolution import build_resolution_metadata


class ImageResolutionMetadataTest(unittest.TestCase):
    def test_build_resolution_metadata_marks_actual_lower_than_requested(self):
        metadata = build_resolution_metadata("4k", [{"width": 941, "height": 1672}], "2304x4096")

        self.assertEqual(metadata["requested_resolution"], "4k")
        self.assertEqual(metadata["actual_resolution"], "1k")
        self.assertEqual(metadata["effective_resolution"], "1k")
        self.assertTrue(metadata["resolution_mismatch"])
        self.assertEqual(metadata["actual_size"], "941x1672")

    def test_gallery_asset_resolution_filter_prefers_actual_resolution(self):
        asset = {
            "resolution": "1k",
            "params": {
                "resolution": "4k",
                "requested_resolution": "4k",
                "actual_resolution": "1k",
            },
        }

        self.assertEqual(asset_index._asset_resolution(asset), "1k")


if __name__ == "__main__":
    unittest.main()
