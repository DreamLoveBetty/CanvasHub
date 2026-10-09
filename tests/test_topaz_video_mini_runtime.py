"""Portable command-contract checks for the standalone Starlight Mini runner."""

from __future__ import annotations

import unittest
from pathlib import Path
import errno
import tempfile
import threading
import sys
import subprocess
from unittest.mock import patch

from backend.topaz_video.mini_runtime import (
    MiniRequest, MiniRuntimeError, MiniTaskCancelled, MiniTaskTimeout,
    _terminate_process_group, build_command, run_mini,
)


@unittest.skipUnless(sys.platform == "darwin", "Starlight Mini runtime is macOS-only")
class MiniRuntimeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = MiniRequest(
            source_path=Path("/synthetic/input.mp4"),
            output_path=Path("/synthetic/output.mp4"),
            output_width=2160,
            output_height=3840,
            start_seconds=6.0,
            duration_seconds=0.5,
            frame_limit=15,
        )

    def test_builds_offline_mini_filter_and_face_sample(self) -> None:
        command = build_command(Path("/stage/MacOS/ffmpeg"), self.request, Path("/tmp/result.mp4"))
        self.assertEqual(command[0], "/stage/MacOS/ffmpeg")
        self.assertEqual(command[command.index("-ss") + 1], "6")
        self.assertEqual(command[command.index("-t") + 1], "0.5")
        self.assertEqual(command[command.index("-frames:v") + 1], "15")
        model_filter = command[command.index("-filter_complex") + 1]
        self.assertIn("model=slm-1", model_filter)
        self.assertIn("w=2160:h=3840", model_filter)
        self.assertIn("download=0", model_filter)
        self.assertIn("-an", command)
        self.assertEqual(command[-1], "/tmp/result.mp4")

    def test_rejects_invalid_dimensions_and_memory(self) -> None:
        for update in ({"output_width": 0}, {"output_height": -1},
                       {"max_memory_fraction": 0.05}, {"instances": 4},
                       {"start_seconds": -1}, {"frame_limit": 0}):
            with self.subTest(update=update):
                request = MiniRequest(**{**self.request.__dict__, **update})
                with self.assertRaises(ValueError):
                    request.validate()

    def test_device_selector_cannot_inject_filter_options(self) -> None:
        request = MiniRequest(**{**self.request.__dict__, "device": "0:download=1"})
        with self.assertRaises(ValueError):
            build_command(Path("/stage/ffmpeg"), request, Path("/tmp/result.mp4"))

    def test_unreapable_process_shutdown_is_bounded(self) -> None:
        class StuckProcess:
            pid = 4242

            def poll(self):
                return None

            def wait(self, timeout):
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

        with patch("backend.topaz_video.mini_runtime.os.killpg") as kill_group:
            self.assertFalse(_terminate_process_group(StuckProcess()))
            self.assertEqual(kill_group.call_count, 2)


@unittest.skipUnless(sys.platform == "darwin", "Starlight Mini runtime is macOS-only")
class MiniRuntimeProcessTests(unittest.TestCase):
    def _stage(self, root: Path, body: str) -> Path:
        stage = root / "stage"
        ffmpeg = stage / "MacOS" / "ffmpeg"
        ffmpeg.parent.mkdir(parents=True)
        ffmpeg.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        ffmpeg.chmod(0o755)
        return stage

    def _request(self, root: Path) -> MiniRequest:
        source = root / "input.mp4"
        source.write_bytes(b"synthetic source")
        return MiniRequest(source, root / "output.mp4", 720, 1280, frame_limit=3)

    def test_progress_and_atomic_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf synthetic > "$output"\n'
                                'printf "model_dir=%s\\n" "$TVAI_MODEL_DIR"\n'
                                "printf 'frame=3\\nprogress=end\\n'\n")
            progress = []
            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage), \
                 patch("backend.topaz_video.mini_runtime._probe_video", return_value=(3, 720, 1280, "30/1")):
                result = run_mini(stage, self._request(root), log_path=root / "run.log",
                                  on_progress=progress.append,
                                  extra_env={"TVAI_MODEL_DIR": "/wrong/override"})
            self.assertEqual(result.frames, 3)
            self.assertEqual(result.output_path.read_bytes(), b"synthetic")
            self.assertEqual(progress[-1]["progress"], "end")
            self.assertIn(f"model_dir={stage.resolve() / 'Resources' / 'models'}", result.log_path.read_text())
            self.assertFalse(list(root.glob(".*.partial.mp4")))

    def test_cancel_and_timeout_remove_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf partial > "$output"\n'
                                "sleep 30\n")
            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage):
                cancelled = threading.Event()
                cancelled.set()
                with self.assertRaises(MiniTaskCancelled):
                    run_mini(stage, self._request(root), log_path=root / "cancel.log",
                             cancel_event=cancelled)
                with self.assertRaises(MiniTaskTimeout):
                    run_mini(stage, self._request(root), log_path=root / "timeout.log",
                             timeout_seconds=0.1)
            self.assertFalse((root / "output.mp4").exists())
            self.assertFalse(list(root.glob(".*.partial.mp4")))

    def test_progress_callback_failure_does_not_abort_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf synthetic > "$output"\n'
                                "printf 'frame=3\\nprogress=end\\n'\n")

            def fail(_: dict[str, str]) -> None:
                raise RuntimeError("consumer failed")

            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage), \
                 patch("backend.topaz_video.mini_runtime._probe_video", return_value=(3, 720, 1280, "30/1")):
                result = run_mini(stage, self._request(root), log_path=root / "run.log", on_progress=fail)
            self.assertEqual(result.output_path.read_bytes(), b"synthetic")
            self.assertIn("MINI_RUNTIME_PROGRESS_CALLBACK_ERROR=RuntimeError: consumer failed",
                          result.log_path.read_text())
            self.assertFalse(list(root.glob(".*.partial.mp4")))

    def test_zero_frame_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf synthetic > "$output"\n')
            request = self._request(root)
            request = MiniRequest(**{**request.__dict__, "frame_limit": None})
            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage), \
                 patch("backend.topaz_video.mini_runtime._probe_video", return_value=(0, 720, 1280, "30/1")):
                with self.assertRaisesRegex(MiniRuntimeError, "no video frames"):
                    run_mini(stage, request, log_path=root / "run.log")
            self.assertFalse(request.output_path.exists())
            self.assertFalse(list(root.glob(".*.partial.mp4")))

    def test_concurrent_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf synthetic > "$output"\n')
            request = self._request(root)

            def concurrent_output(_: Path) -> tuple[int, int, int, str]:
                request.output_path.write_bytes(b"other task")
                return (3, 720, 1280, "30/1")

            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage), \
                 patch("backend.topaz_video.mini_runtime._probe_video", side_effect=concurrent_output):
                with self.assertRaisesRegex(MiniRuntimeError, "Refusing to replace"):
                    run_mini(stage, request, log_path=root / "run.log")
            self.assertEqual(request.output_path.read_bytes(), b"other task")
            self.assertFalse(list(root.glob(".*.partial.mp4")))

    def test_unsupported_atomic_publish_reports_filesystem_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf synthetic > "$output"\n')
            request = self._request(root)
            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage), \
                 patch("backend.topaz_video.mini_runtime._probe_video", return_value=(3, 720, 1280, "30/1")), \
                 patch("backend.topaz_video.mini_runtime.os.link",
                       side_effect=OSError(errno.EOPNOTSUPP, "hard links unsupported")):
                with self.assertRaisesRegex(MiniRuntimeError, "Cannot atomically publish"):
                    run_mini(stage, request, log_path=root / "run.log")
            self.assertFalse(request.output_path.exists())
            self.assertFalse(list(root.glob(".*.partial.mp4")))

    def test_log_must_not_destroy_source_or_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, "exit 0\n")
            request = self._request(root)
            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage):
                with self.assertRaisesRegex(MiniRuntimeError, "log path conflicts"):
                    run_mini(stage, request, log_path=request.source_path)
                with self.assertRaisesRegex(MiniRuntimeError, "outside the verified runtime stage"):
                    run_mini(stage, request, log_path=stage / "Resources" / "models" / "task.log")
            self.assertEqual(request.source_path.read_bytes(), b"synthetic source")

    def test_cancelled_zero_exit_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self._stage(root, 'for arg in "$@"; do output="$arg"; done\n'
                                'printf partial > "$output"\n')
            request = self._request(root)
            cancelled = threading.Event()
            cancelled.set()
            with patch("backend.topaz_video.mini_runtime.require_stage", return_value=stage), \
                 patch("backend.topaz_video.mini_runtime._terminate_process_group", return_value=None):
                with self.assertRaises(MiniTaskCancelled):
                    run_mini(stage, request, log_path=root / "cancel.log", cancel_event=cancelled)
            self.assertFalse(request.output_path.exists())
            self.assertFalse(list(root.glob(".*.partial.mp4")))


if __name__ == "__main__":
    unittest.main()
