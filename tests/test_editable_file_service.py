#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class EditableFileServiceTest(unittest.TestCase):
    def test_save_ppt_artifacts_writes_manifest_under_ppt_root(self):
        from backend import editable_file_service as svc

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GPT Images"
            with patch.object(svc, "EDITABLE_ROOT", root), patch.object(svc, "PPT_ROOT", root / "PPT"), patch.object(svc, "find_libreoffice", return_value=""):
                manifest = svc.save_editable_artifacts(
                    kind="ppt",
                    prompt="品牌发布会方案",
                    primary={"filename": "deck.pptx", "b64": base64.b64encode(b"pptx").decode("ascii")},
                    zip_artifact={"filename": "deck.zip", "b64": base64.b64encode(b"zip").decode("ascii")},
                    task_id="task-1",
                )

                self.assertEqual(manifest["artifact_type"], "ppt")
                self.assertTrue(manifest["directory_relative"].startswith("PPT/"))
                self.assertEqual(manifest["primary"]["name"], "deck.pptx")
                self.assertEqual(manifest["preview"]["status"], "missing_dependency")
                self.assertTrue(Path(manifest["manifest_path"]).exists())

    def test_save_psd_artifacts_extracts_layer_images_from_zip(self):
        from backend import editable_file_service as svc

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GPT Images"
            zip_path = Path(tmp) / "layers.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("layer-1.png", b"png-layer")
            with patch.object(svc, "EDITABLE_ROOT", root), patch.object(svc, "PSD_ROOT", root / "PSD"):
                manifest = svc.save_editable_artifacts(
                    kind="psd",
                    prompt="海报拆层",
                    primary={"filename": "poster.psd", "b64": base64.b64encode(b"psd").decode("ascii")},
                    zip_artifact={"filename": "layers.zip", "b64": base64.b64encode(zip_path.read_bytes()).decode("ascii")},
                    task_id="task-2",
                )

                layers = manifest["preview"]["layers"]
                self.assertEqual(manifest["artifact_type"], "psd")
                self.assertTrue(manifest["directory_relative"].startswith("PSD/"))
                self.assertEqual(len(layers), 1)
                self.assertTrue(Path(layers[0]["path"]).exists())
                self.assertIn("layer-1.png", layers[0]["name"])

    def test_resolve_editable_file_only_allows_ppt_and_psd_roots(self):
        from backend import editable_file_service as svc

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GPT Images"
            ppt_file = root / "PPT" / "demo deck" / "deck.pptx"
            other_file = root / "Mini-app" / "2026-06-01" / "image.png"
            ppt_file.parent.mkdir(parents=True)
            other_file.parent.mkdir(parents=True)
            ppt_file.write_bytes(b"pptx")
            other_file.write_bytes(b"png")

            with patch.object(svc, "EDITABLE_ROOT", root):
                self.assertEqual(svc.resolve_editable_file("PPT/demo deck/deck.pptx"), ppt_file.resolve())
                self.assertIsNone(svc.resolve_editable_file("Mini-app/2026-06-01/image.png"))
                self.assertIsNone(svc.resolve_editable_file("../PPT/demo deck/deck.pptx"))

    def test_save_with_archive_disabled_uses_local_editable_root(self):
        from backend import editable_file_service as svc

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GPT Images"
            local_root = Path(tmp) / "local"
            with patch.object(svc, "EDITABLE_ROOT", root), patch.object(svc, "LOCAL_EDITABLE_ROOT", local_root), patch.object(svc, "find_libreoffice", return_value=""):
                manifest = svc.save_editable_artifacts(
                    kind="ppt",
                    prompt="临时 PPT",
                    primary={"filename": "deck.pptx", "b64": base64.b64encode(b"pptx").decode("ascii")},
                    task_id="task-local",
                    archive_enabled=False,
                )

                self.assertFalse(manifest["archived"])
                self.assertTrue(manifest["directory_relative"].startswith("local/PPT/"))
                self.assertEqual(svc.resolve_editable_file(manifest["primary"]["relative_path"]), Path(manifest["primary"]["path"]).resolve())
                listed = svc.list_editable_files()
                self.assertEqual(listed["stats"]["local"], 1)
                self.assertEqual(listed["files"][0]["task_id"], "task-local")


if __name__ == "__main__":
    unittest.main()
