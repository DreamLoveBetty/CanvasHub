import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


class LegacyMediaPathTest(unittest.TestCase):
    def _write_png(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 6), (24, 48, 96)).save(path)

    def test_gallery_scans_read_only_legacy_archive_roots(self):
        import backend.asset_index as asset_index

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_archive = root / "data" / "archive"
            legacy_archive = root / "Obsidian Vault" / "GPT Images" / "Mini-app"
            self._write_png(legacy_archive / "2026-06-27" / "legacy.png")

            with patch.object(asset_index, "DB_PATH", root / "assets.db"), patch.object(
                asset_index,
                "archive_scan_roots",
                return_value=[("main", main_archive), ("legacy_obsidian", legacy_archive)],
            ), patch.object(asset_index, "get_all_tasks", return_value=[]), patch.object(
                asset_index, "_load_old_history", return_value=[]
            ):
                data = asset_index.list_assets(limit=10)

        self.assertEqual(data["stats"]["archive_image_count"], 1)
        self.assertEqual(data["assets"][0]["imageUrl"], "/archive_image/legacy_obsidian/2026-06-27/legacy.png")

    def test_source_image_resolves_legacy_root_without_changing_default(self):
        import backend.prompt_source_sync as prompt_source_sync

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_source = root / "data" / "source_images"
            legacy_source = root / "Obsidian Vault" / "Source_Image"
            self._write_png(legacy_source / "GPT Image 2" / "case" / "image-01.jpg")

            with patch.object(
                prompt_source_sync,
                "source_image_roots",
                return_value=[("main", main_source), ("legacy_obsidian", legacy_source)],
            ):
                resolved = prompt_source_sync.resolve_source_image("GPT Image 2/case/image-01.jpg")
                explicit = prompt_source_sync.resolve_source_image("legacy_obsidian/GPT Image 2/case/image-01.jpg")

        expected = (legacy_source / "GPT Image 2" / "case" / "image-01.jpg").resolve()
        self.assertEqual(resolved.resolve(), expected)
        self.assertEqual(explicit.resolve(), expected)

    def test_webp_thumb_cache_uses_frontend_generated_cache(self):
        import backend.thumb_cache as thumb_cache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "archive" / "image.png"
            cache_root = root / "frontend" / "thumb"
            self._write_png(source)

            with patch.object(thumb_cache, "THUMB_CACHE_ROOT", cache_root):
                public_url = thumb_cache.thumb_url_for_media_url("/archive_image/2026-06-30/image.png")
                parsed = thumb_cache.parse_thumb_request(public_url.split("?", 1)[0])
                thumb_path = thumb_cache.ensure_webp_thumbnail(source, size=128)
                self.assertEqual(public_url, "/thumb/%2Farchive_image%2F2026-06-30%2Fimage.png.webp?w=420")
                self.assertEqual(parsed, "/archive_image/2026-06-30/image.png")
                self.assertTrue(thumb_path.is_file())
                self.assertEqual(thumb_path.suffix, ".webp")
                with Image.open(thumb_path) as image:
                    self.assertEqual(image.format, "WEBP")
                    self.assertLessEqual(max(image.size), 128)


if __name__ == "__main__":
    unittest.main()
