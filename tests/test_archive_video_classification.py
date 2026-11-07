#!/usr/bin/env python3
"""Every generated video lands under 生成视频: any task with a video result (H3, Cyimg, ComfyUI) maps to its
archive file, video sidecars are written as `video_prompt`, and measured media values beat requested ones."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend import server
from backend.services import archive_video
from backend.storage_paths import write_obsidian_prompt_sidecar


def _task_map(tasks):
    return archive_video._archive_video_task_map(
        H3_VIDEO_TASK_TYPE=server.H3_VIDEO_TASK_TYPE, Path=Path, get_all_tasks=lambda **_kw: tasks,
        _ARCHIVE_VIDEO_EXTENSIONS=server._ARCHIVE_VIDEO_EXTENSIONS,
    )


class ArchiveVideoClassificationTest(unittest.TestCase):
    def test_any_task_with_a_video_result_is_generated(self) -> None:
        mapping = _task_map([
            {'task_id': 'c1', 'type': 'comfy', 'result_files': ['comfy_a.mp4']},
            {'task_id': 'c2', 'type': 'comfy', 'result_files': ['comfy_b.png']},
            {'task_id': 'y1', 'type': 'cyimg-video', 'result_file': 'cyimg_1.mp4'},
            {'task_id': 'h1', 'type': server.H3_VIDEO_TASK_TYPE, 'params': {'video_filename': 'h3_x.mp4'}},
        ])
        self.assertEqual(sorted(mapping), ['comfy_a.mp4', 'cyimg_1.mp4', 'h3_x.mp4'])
        self.assertEqual([archive_video._archive_video_provider_label(mapping[name])
                          for name in ('comfy_a.mp4', 'cyimg_1.mp4', 'h3_x.mp4')], ['ComfyUI', 'Cyimg', 'MiniMax H3'])
        self.assertEqual(archive_video._archive_video_provider_label(None), '')

    def test_ambiguous_basenames_stay_unmapped(self) -> None:
        mapping = _task_map([{'task_id': 'a', 'type': 'comfy', 'result_files': ['same.mp4']},
                             {'task_id': 'b', 'type': 'comfy', 'result_files': ['same.mp4']}])
        self.assertEqual(mapping, {})

    def test_video_sidecar_is_a_video_prompt_and_counts_as_generated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / '2026-11-05' / 'comfy_a.mp4'
            video.parent.mkdir()
            video.write_bytes(b'')
            markdown = write_obsidian_prompt_sidecar(video, 'workflow: x.json').read_text(encoding='utf-8')
            self.assertIn('type: video_prompt', markdown)
            self.assertIn('video: "comfy_a.mp4"', markdown)
            self.assertEqual(server._classify_archive_video_source(video)[0], 'generated')
            image = video.with_name('still.png')
            image.write_bytes(b'')
            self.assertIn('type: image_prompt', write_obsidian_prompt_sidecar(image, 'p').read_text(encoding='utf-8'))

    def test_measured_media_values_beat_requested_size(self) -> None:
        task = {'params': {'width': 1536, 'height': 2688, 'fps': 24.0}}
        public = server._public_archive_video_parameters({}, task, {'width': 1080, 'height': 1920, 'fps': 0})
        self.assertEqual((public['width'], public['height'], public['fps']), (1080, 1920, 24.0))


if __name__ == '__main__':
    unittest.main()
