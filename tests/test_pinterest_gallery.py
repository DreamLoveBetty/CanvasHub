import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend import pinterest_gallery
from backend import pinterest_storage


def _page(state, handler="www/[username]/[slug].js"):
    props = json.dumps({"initialReduxState": state})
    pws_data = json.dumps({"initialHandlerId": handler})
    return (
        f'<script id="__PWS_INITIAL_PROPS__">{props}</script>'
        f'<script id="__PWS_DATA__">{pws_data}</script>'
    )


class PinterestGalleryFallbackTests(unittest.TestCase):
    def setUp(self):
        pinterest_gallery._PROFILE_CACHE.clear()
        pinterest_gallery._BOARD_CACHE.clear()
        self.config = {
            "enabled": True,
            "profile_url": "https://jp.pinterest.com/example/",
            "auth_configured": True,
            "auth_status": "authenticated",
            "auth_source": "browser_login",
            "auth_updated_at": "2026-07-28T05:42:47Z",
            "download_originals": True,
            "max_pins_per_board": 500,
            "request_timeout_seconds": 20,
        }
        self.board = {
            "id": "board-1",
            "name": "UI",
            "url": "/example/ui/",
            "pin_count": 1,
        }
        self.pin = {
            "id": "pin-1",
            "title": "Example",
            "images": {
                "474x": {
                    "url": "https://i.pinimg.com/474x/example.jpg",
                    "width": 474,
                    "height": 711,
                }
            },
            "board": {
                "id": "board-1",
                "name": "UI",
                "url": "/example/ui/",
            },
        }
        self.empty_state = {"boards": {}, "pins": {}, "users": {}, "resources": {}}

    def _fetch_html(self, session, url, _timeout):
        authenticated = bool(session.headers.get("Cookie"))
        if authenticated:
            return _page(self.empty_state)
        if url.rstrip("/").endswith("/example"):
            return _page({
                "boards": {"board-1": self.board},
                "pins": {"pin-1": self.pin},
                "users": {
                    "user-1": {
                        "username": "example",
                        "full_name": "Example User",
                    }
                },
                "resources": {},
            })
        options = json.dumps({"board_id": "board-1"})
        return _page({
            "boards": {"board-1": self.board},
            "pins": {"pin-1": self.pin},
            "users": {},
            "resources": {
                "BoardFeedResource": {
                    options: {
                        "data": [self.pin],
                        "nextBookmark": "-end-",
                    }
                }
            },
        })

    @patch.object(pinterest_gallery, "load_saved_cookie_header", return_value="session=valid")
    @patch.object(pinterest_gallery, "get_pinterest_config")
    def test_authenticated_empty_profile_falls_back_to_public_discovery(
        self,
        get_config,
        _load_cookie,
    ):
        get_config.return_value = dict(self.config)
        with patch.object(pinterest_gallery, "_fetch_html", side_effect=self._fetch_html):
            result = pinterest_gallery.get_pinterest_library()

        self.assertEqual("authenticated", result["auth_status"])
        self.assertEqual("authenticated_browser", result["source_mode"])
        self.assertEqual("public_profile_fallback", result["discovery_mode"])
        self.assertEqual(["board-1"], [item["id"] for item in result["boards"]])
        self.assertEqual(["pinterest_pin-1"], [item["id"] for item in result["pins"]])

    @patch.object(pinterest_gallery, "load_saved_cookie_header", return_value="session=valid")
    @patch.object(pinterest_gallery, "get_pinterest_config")
    def test_authenticated_empty_board_falls_back_to_public_board_feed(
        self,
        get_config,
        _load_cookie,
    ):
        get_config.return_value = dict(self.config)
        with patch.object(pinterest_gallery, "_fetch_html", side_effect=self._fetch_html):
            result = pinterest_gallery.get_pinterest_library(board_id="board-1")

        self.assertEqual("authenticated", result["auth_status"])
        self.assertEqual("authenticated_browser", result["source_mode"])
        self.assertEqual("public_profile_fallback", result["discovery_mode"])
        self.assertEqual(["pinterest_pin-1"], [item["id"] for item in result["pins"]])


class PinterestStorageTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.source_root = Path(self.tempdir.name)
        self.pinterest_root = self.source_root / "pinterest"
        self.root_patch = patch.object(pinterest_storage, "SOURCE_IMAGE_DIR", self.source_root)
        self.pinterest_patch = patch.object(pinterest_storage, "PINTEREST_SOURCE_DIR", self.pinterest_root)
        self.root_patch.start()
        self.pinterest_patch.start()
        pinterest_storage._RUNS.clear()

        image = Image.new("RGB", (16, 12), color=(220, 40, 60))
        output = io.BytesIO()
        image.save(output, format="JPEG")
        self.image_bytes = output.getvalue()
        self.board = {
            "id": "board-1",
            "name": "UI",
            "url": "https://jp.pinterest.com/example/ui/",
        }
        self.pin = {
            "id": "pinterest_pin-1",
            "pin_id": "pin-1",
            "board_id": "board-1",
            "board_name": "UI",
            "image_url": "https://i.pinimg.com/originals/example.jpg",
            "source_url": "https://jp.pinterest.com/pin/pin-1/",
            "title": "Example",
        }

    def tearDown(self):
        self.pinterest_patch.stop()
        self.root_patch.stop()
        self.tempdir.cleanup()

    def test_pin_download_uses_requested_directory_structure(self):
        image_bytes = self.image_bytes

        class FakeResponse:
            url = "https://i.pinimg.com/originals/example.jpg"
            headers = {
                "Content-Type": "image/jpeg",
                "Content-Length": str(len(image_bytes)),
            }

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield image_bytes

        class FakeSession:
            trust_env = True

            def get(self, *_args, **_kwargs):
                return FakeResponse()

            def close(self):
                return None

        with patch.object(pinterest_storage.requests, "Session", return_value=FakeSession()):
            result = pinterest_storage.download_pinterest_pin(self.board, self.pin)

        pin_dir = self.pinterest_root / "board-1" / "pin-1"
        self.assertTrue((pin_dir / "image.jpg").is_file())
        self.assertTrue((pin_dir / "metadata.json").is_file())
        metadata = json.loads((pin_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual("board-1", metadata["board_id"])
        self.assertEqual("pin-1", metadata["pin_id"])
        self.assertTrue(result["local_cached"])
        self.assertEqual(
            "/source_image/pinterest/board-1/pin-1/image.jpg",
            result["local_image_url"],
        )

    def test_board_download_reports_progress(self):
        with patch.object(
            pinterest_storage,
            "download_pinterest_pin",
            return_value={"ok": True, "downloaded": True, "already_cached": False},
        ):
            started = pinterest_storage.start_pinterest_board_download(
                self.board,
                [self.pin, {**self.pin, "id": "pinterest_pin-2", "pin_id": "pin-2"}],
            )
            run_id = started["run"]["run_id"]
            deadline = time.time() + 2
            run = None
            while time.time() < deadline:
                run = pinterest_storage.get_pinterest_board_download(run_id)
                if run and run["status"] != "running":
                    break
                time.sleep(0.01)

        self.assertIsNotNone(run)
        self.assertEqual("completed", run["status"])
        self.assertEqual(2, run["processed"])
        self.assertEqual(2, run["downloaded"])
        self.assertEqual(100, run["progress_percent"])


if __name__ == "__main__":
    unittest.main()
