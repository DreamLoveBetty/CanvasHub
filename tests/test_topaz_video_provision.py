"""Portable synthetic contract tests; no real Topaz files or inference needed."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from backend.topaz_video.provision import (
    CACHE_DIRS, DEPENDENCIES, GLOBAL_METADATA, MANIFEST_NAME, MANIFEST_SCHEMA, MODEL_ID, WEIGHTS,
    ProvisionError, inspect_stage, provision_stage, refresh_stage_manifest, require_stage,
)


def fixture(root: Path) -> Path:
    contents = root / "source" / "Contents"
    ffmpeg = contents / "MacOS" / "ffmpeg"
    ffmpeg.parent.mkdir(parents=True)
    ffmpeg.write_bytes(b"synthetic ffmpeg")
    ffmpeg.chmod(0o755)
    frameworks = contents / "Frameworks"
    frameworks.mkdir()
    (frameworks / "libbase.dylib").write_bytes(b"synthetic dylib")
    (frameworks / "libalias.dylib").symlink_to("libbase.dylib")
    models = contents / "Resources" / "models"
    models.mkdir(parents=True)
    (models / f"{MODEL_ID}.json").write_text(json.dumps({
        "shortName": "slm", "dependencies": list(DEPENDENCIES),
    }), encoding="utf-8")
    for name in DEPENDENCIES:
        (models / f"{name}.json").write_text(json.dumps({"shortName": name[:-2]}), encoding="utf-8")
    for name in WEIGHTS:
        (models / name).write_bytes(("synthetic " + name).encode())
    (models / GLOBAL_METADATA).write_bytes(b"synthetic tvai metadata")
    for name in CACHE_DIRS:
        cache = models / "coreMLCache" / name
        (cache / "weights").mkdir(parents=True)
        (cache / "model.mil").write_bytes(b"synthetic mil")
        (cache / "weights" / "weight.bin").write_bytes(b"synthetic weight")
        (cache / "coremldata.bin").write_bytes(b"synthetic cache")
    return contents


@unittest.skipUnless(sys.platform == "darwin", "Starlight Mini staging is macOS-only")
class ProvisionTest(unittest.TestCase):
    def test_explicit_stage_preserves_internal_links_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            stage = root / "stage" / "Contents"
            self.assertTrue(provision_stage(source, stage)["ready"])
            self.assertEqual(require_stage(stage), stage.resolve())
            self.assertEqual((stage / "Frameworks/libalias.dylib").readlink(), Path("libbase.dylib"))
            self.assertEqual((stage / "Resources/models" / WEIGHTS[0]).read_bytes(),
                             (source / "Resources/models" / WEIGHTS[0]).read_bytes())
            self.assertEqual(sorted(p.name for p in (stage / "Resources/models").glob("*.tz3")),
                             sorted(WEIGHTS))
            self.assertEqual((stage / "Resources/models" / GLOBAL_METADATA).read_bytes(),
                             (source / "Resources/models" / GLOBAL_METADATA).read_bytes())
            self.assertFalse((stage / "Resources/models/license.lic").exists())
            with self.assertRaises(ProvisionError):
                provision_stage(source, stage)

    def test_immutable_corruption_rejected_but_cache_mutations_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            stage = root / "stage" / "Contents"
            provision_stage(source, stage)
            cache = stage / "Resources/models/coreMLCache" / CACHE_DIRS[0]
            (cache / "weights/weight.bin").write_bytes(b"recompiled weight")
            (cache / "model.mil").unlink()
            (stage / "Resources/models/coreMLCache/new-compiled-model").mkdir()
            self.assertTrue(inspect_stage(stage)["ready"])
            (stage / "Resources/models" / WEIGHTS[0]).write_bytes(b"tampered")
            self.assertFalse(inspect_stage(stage)["ready"])
            with self.assertRaises(ProvisionError):
                require_stage(stage)

    def test_fresh_source_without_coreml_cache_is_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            import shutil
            shutil.rmtree(source / "Resources/models/coreMLCache")
            stage = root / "stage" / "Contents"
            self.assertTrue(provision_stage(source, stage)["ready"])
            self.assertTrue((stage / "Resources/models/coreMLCache").is_dir())
            self.assertEqual(list((stage / "Resources/models/coreMLCache").iterdir()), [])
            (stage / "Resources/models/coreMLCache/compiled.bin").write_bytes(b"created after first run")
            self.assertTrue(inspect_stage(stage)["ready"])

    def test_external_symlink_in_mutable_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            stage = root / "stage" / "Contents"
            provision_stage(source, stage)
            outside = root / "outside-cache.bin"
            outside.write_bytes(b"not staged")
            (stage / "Resources/models/coreMLCache/external.bin").symlink_to(outside)
            self.assertTrue(any("symlink escapes stage" in error for error in inspect_stage(stage)["errors"]))

    def test_legacy_cache_fingerprints_are_ignored_and_can_be_migrated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "stage" / "Contents"
            provision_stage(fixture(root), stage)
            manifest_path = stage / MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema"] = 1
            manifest["inventory"]["Resources/models/coreMLCache/compiled.bin"] = {
                "type": "file", "size": 7, "sha256": "legacy-cache-fingerprint",
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (stage / "Resources/models/coreMLCache/compiled.bin").write_bytes(b"new compilation")
            self.assertTrue(inspect_stage(stage)["ready"])
            self.assertTrue(refresh_stage_manifest(stage)["ready"])
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["schema"], MANIFEST_SCHEMA)
            self.assertFalse(any("coreMLCache" in key for key in updated["inventory"]))

    def test_missing_global_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            (source / "Resources/models" / GLOBAL_METADATA).unlink()
            with self.assertRaisesRegex(ProvisionError, GLOBAL_METADATA):
                provision_stage(source, root / "stage" / "Contents")

    def test_ffmpeg_must_remain_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            ffmpeg = source / "MacOS" / "ffmpeg"
            ffmpeg.chmod(0o644)
            with self.assertRaisesRegex(ProvisionError, "not executable"):
                provision_stage(source, root / "stage" / "Contents")
            ffmpeg.chmod(0o755)
            stage = root / "stage" / "Contents"
            provision_stage(source, stage)
            (stage / "MacOS" / "ffmpeg").chmod(0o644)
            self.assertFalse(inspect_stage(stage)["ready"])

    def test_external_symlink_and_incomplete_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            outside = root / "outside.dylib"
            outside.write_bytes(b"not staged")
            (source / "Frameworks/external.dylib").symlink_to(outside)
            stage = root / "stage" / "Contents"
            with self.assertRaisesRegex(ProvisionError, "symlink"):
                provision_stage(source, stage)
            self.assertFalse(stage.exists())
            (source / "Frameworks/external.dylib").unlink()
            (source / "Resources/models" / WEIGHTS[2]).unlink()
            with self.assertRaisesRegex(ProvisionError, "missing"):
                provision_stage(source, stage)

    def test_stage_cannot_overlap_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = fixture(Path(temporary))
            with self.assertRaisesRegex(ProvisionError, "disjoint"):
                provision_stage(source, source / "nested")


if __name__ == "__main__":
    unittest.main()
