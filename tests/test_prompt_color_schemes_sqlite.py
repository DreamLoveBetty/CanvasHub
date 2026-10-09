import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import prompt_library


class PromptColorSchemesSqliteTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = prompt_library.DB_PATH
        prompt_library.DB_PATH = Path(self.tempdir.name) / "prompt_library.db"
        self.store_key = str(prompt_library.DB_PATH.resolve())
        prompt_library._INITIALIZED_STORE_PATHS.discard(self.store_key)

    def tearDown(self):
        prompt_library._INITIALIZED_STORE_PATHS.discard(self.store_key)
        prompt_library.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    @staticmethod
    def custom_payload(scheme_id="custom-color-test", name="测试配色"):
        return {
            "id": scheme_id,
            "name": name,
            "description": "SQLite 自定义配色",
            "colors": ["#112233", "#445566", "#778899", "#DDEEFF", "#101820"],
            "categories": ["cool", "muted"],
            "scenes": ["界面系统"],
            "tags": ["测试", "冷色"],
            "prompt": "使用冷静的蓝灰配色并保持清晰层级。",
            "industry": "uiux",
            "formula": "monochromatic",
            "base_color": "#112233",
            "contrast": "balanced",
            "temperature": "cool",
            "neutral_balance": True,
            "use_ratio": True,
        }

    def test_seeds_built_ins_and_preserves_favorite_on_reinitialize(self):
        schemes = prompt_library.list_color_schemes()
        self.assertEqual(15, len(schemes))
        self.assertTrue(all(not item["custom"] for item in schemes))
        self.assertEqual("珊瑚日出", next(item for item in schemes if item["id"] == "coral-sunrise")["name"])

        prompt_library.set_color_scheme_favorite("coral-sunrise", True)
        prompt_library._INITIALIZED_STORE_PATHS.discard(self.store_key)
        prompt_library.init_prompt_library_store()
        reloaded = next(item for item in prompt_library.list_color_schemes() if item["id"] == "coral-sunrise")
        self.assertTrue(reloaded["favorite"])

    def test_custom_crud_and_system_guards(self):
        created = prompt_library.save_color_scheme(self.custom_payload())
        self.assertTrue(created["custom"])
        self.assertEqual("#112233", created["base_color"])

        favorited = prompt_library.set_color_scheme_favorite(created["id"], True)
        self.assertTrue(favorited["favorite"])

        updated = prompt_library.save_color_scheme(self.custom_payload(name="测试配色 v2"))
        self.assertEqual("测试配色 v2", updated["name"])
        self.assertTrue(updated["favorite"])

        deleted = prompt_library.delete_color_scheme(created["id"])
        self.assertEqual("deleted", deleted["status"])
        self.assertNotIn(created["id"], {item["id"] for item in prompt_library.list_color_schemes()})
        with self.assertRaises(prompt_library.ColorSchemeNotFoundError):
            prompt_library.set_color_scheme_favorite(created["id"], True)
        with self.assertRaises(prompt_library.ColorSchemeNotFoundError):
            prompt_library.save_color_scheme(self.custom_payload())

        with self.assertRaises(ValueError):
            prompt_library.save_color_scheme({**self.custom_payload("coral-sunrise"), "name": "覆盖内置"})
        with self.assertRaises(ValueError):
            prompt_library.delete_color_scheme("coral-sunrise")

    def test_legacy_migration_is_idempotent_after_edit_delete_and_unfavorite(self):
        legacy = self.custom_payload("custom-color-legacy", "旧版配色")
        first = prompt_library.migrate_legacy_color_schemes(
            [legacy],
            ["custom-color-legacy", "coral-sunrise"],
        )
        self.assertTrue(first["migration_complete"])
        self.assertEqual(1, first["imported_custom_schemes"])
        self.assertEqual(2, first["imported_favorites"])

        edited = prompt_library.save_color_scheme({**legacy, "name": "SQLite 已编辑"})
        self.assertEqual("SQLite 已编辑", edited["name"])
        prompt_library.set_color_scheme_favorite("custom-color-legacy", False)
        prompt_library.set_color_scheme_favorite("coral-sunrise", False)
        prompt_library.delete_color_scheme("custom-color-legacy")

        second = prompt_library.migrate_legacy_color_schemes(
            [legacy],
            ["custom-color-legacy", "coral-sunrise"],
        )
        self.assertTrue(second["migration_complete"])
        self.assertEqual(0, second["imported_custom_schemes"])
        self.assertEqual(0, second["imported_favorites"])
        self.assertNotIn("custom-color-legacy", {item["id"] for item in second["color_schemes"]})
        coral = next(item for item in second["color_schemes"] if item["id"] == "coral-sunrise")
        self.assertFalse(coral["favorite"])

    def test_legacy_id_conflict_is_not_marked_complete_or_overwritten(self):
        prompt_library.save_color_scheme(self.custom_payload("custom-color-conflict", "SQLite 版本"))
        result = prompt_library.migrate_legacy_color_schemes(
            [self.custom_payload("custom-color-conflict", "localStorage 版本")],
            [],
        )
        self.assertFalse(result["migration_complete"])
        stored = next(item for item in result["color_schemes"] if item["id"] == "custom-color-conflict")
        self.assertEqual("SQLite 版本", stored["name"])

    def test_missing_legacy_favorite_keeps_migration_incomplete(self):
        result = prompt_library.migrate_legacy_color_schemes([], ["custom-color-missing"])
        self.assertFalse(result["migration_complete"])
        self.assertEqual(1, result["failed_favorites"])

    def test_removed_builtin_is_soft_deleted_and_custom_id_collision_is_preserved(self):
        prompt_library.list_color_schemes()
        with prompt_library._db() as conn:
            conn.execute(
                "UPDATE prompt_color_schemes SET system=0, name='用户同名方案' WHERE color_scheme_id='coral-sunrise'"
            )
            conn.execute(
                "INSERT INTO prompt_color_schemes(color_scheme_id, name, colors_json, prompt, system, status) "
                "VALUES('retired-system-color', '旧内置', '[\"#111111\",\"#222222\",\"#333333\"]', '旧内置', 1, 'active')"
            )
        prompt_library._INITIALIZED_STORE_PATHS.discard(self.store_key)
        prompt_library.init_prompt_library_store()
        with prompt_library._db() as conn:
            collision = conn.execute(
                "SELECT name, system FROM prompt_color_schemes WHERE color_scheme_id='coral-sunrise'"
            ).fetchone()
            retired = conn.execute(
                "SELECT status FROM prompt_color_schemes WHERE color_scheme_id='retired-system-color'"
            ).fetchone()
        self.assertEqual("用户同名方案", collision["name"])
        self.assertFalse(collision["system"])
        self.assertEqual("deleted", retired["status"])

    def test_concurrent_delete_cannot_be_undone_by_inflight_save(self):
        scheme_id = "custom-color-concurrent"
        prompt_library.save_color_scheme(self.custom_payload(scheme_id))
        save_checked = threading.Event()
        release_save = threading.Event()
        results = {}
        original_normalize = prompt_library._normalize_color_scheme_payload

        def paused_normalize(data, existing=None):
            if threading.current_thread().name == "color-save-thread":
                save_checked.set()
                release_save.wait(timeout=2)
            return original_normalize(data, existing)

        def run_save():
            results["save"] = prompt_library.save_color_scheme(
                self.custom_payload(scheme_id, "并发保存")
            )

        def run_delete():
            results["delete"] = prompt_library.delete_color_scheme(scheme_id)

        with mock.patch.object(prompt_library, "_normalize_color_scheme_payload", paused_normalize):
            save_thread = threading.Thread(target=run_save, name="color-save-thread")
            delete_thread = threading.Thread(target=run_delete, name="color-delete-thread")
            save_thread.start()
            self.assertTrue(save_checked.wait(timeout=2))
            delete_thread.start()
            time.sleep(0.05)
            self.assertTrue(delete_thread.is_alive())
            release_save.set()
            save_thread.join(timeout=2)
            delete_thread.join(timeout=2)

        self.assertFalse(save_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual("deleted", results["delete"]["status"])
        self.assertNotIn(scheme_id, {item["id"] for item in prompt_library.list_color_schemes()})


if __name__ == "__main__":
    unittest.main()
