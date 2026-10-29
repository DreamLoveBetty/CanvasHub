"""Google edits keep the resolution the user picked instead of forcing 4K."""

import unittest

from backend.services.generation_policy import _coerce_google_edit_quality
from tests.test_gemini_reference_labels import CapturedPost, FakeClient, png_b64
from backend.provider_google_pool import GooglePoolProvider


class GoogleEditResolutionTest(unittest.TestCase):
    def requested_size(self, quality):
        client = FakeClient()
        with self.assertRaises(CapturedPost):
            GooglePoolProvider(client).edit("prompt", [png_b64("red")], quality=_coerce_google_edit_quality(quality))
        return client.session.json["generationConfig"]["imageConfig"]["imageSize"]

    def test_desktop_resolutions_reach_google_unchanged(self):
        for quality, size in (("1k", "1K"), ("2k", "2K"), ("4k", "4K")):
            self.assertEqual(self.requested_size(quality), size, quality)

    def test_legacy_mobile_tiers_keep_their_meaning(self):
        self.assertEqual(_coerce_google_edit_quality("hd"), "hd")
        self.assertEqual(_coerce_google_edit_quality(None), "hd")
        self.assertEqual(_coerce_google_edit_quality("standard"), "standard")
        self.assertEqual(self.requested_size("hd"), "4K")
        self.assertEqual(self.requested_size("standard"), "2K")


if __name__ == "__main__":
    unittest.main()
