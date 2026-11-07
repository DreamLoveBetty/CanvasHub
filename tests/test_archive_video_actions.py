#!/usr/bin/env python3
"""Video gallery actions: hidden videos only list under `hidden`, deletion moves the video and its
sidecars into an undoable batch, and video snapshots keep their media fields inside candidate sets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import asset_index, server
from backend.services import archive_video_actions as actions


class ArchiveVideoActionsTest(unittest.TestCase):
    def test_hidden_ids_only_take_hidden_videos(self) -> None:
        meta = {'video_a': {'hidden': True}, 'video_b': {'hidden': False}, 'img_c': {'hidden': True}}
        self.assertEqual(actions.hidden_video_asset_ids(meta), {'video_a'})
        self.assertTrue(actions.video_asset_id('main/2026-11-05/x.mp4').startswith('video_'))
        self.assertEqual(len(actions.video_asset_id('main/x.mp4')), len('video_') + 24)

    def test_listing_moves_hidden_videos_to_the_hidden_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = root / '2026-11-05'
            day.mkdir()
            for name in ('a.mp4', 'b.mp4'):
                (day / name).write_bytes(b'\0')
            hidden_id = actions.video_asset_id('main/2026-11-05/a.mp4')
            with mock.patch.object(server, 'archive_scan_roots', lambda: [('main', root)]), \
                    mock.patch.object(server, 'load_asset_meta', lambda: {hidden_id: {'hidden': True}}), \
                    mock.patch.object(server, '_probe_archive_video_metadata', lambda *_a, **_k: {}), \
                    mock.patch.object(server, '_archive_video_task_map', lambda *_a, **_k: {}):
                visible = server._list_archive_videos(source='all')
                hidden = server._list_archive_videos(source='hidden')
        self.assertEqual([item['path'] for item in visible['videos']], ['main/2026-11-05/b.mp4'])
        self.assertEqual([(item['asset_id'], item['hidden']) for item in hidden['videos']], [(hidden_id, True)])
        self.assertEqual(visible['stats']['by_source']['hidden'], 1)
        self.assertEqual(visible['stats']['by_source']['all'], 1)

    def test_delete_moves_video_and_sidecars_into_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / 'clip.mp4'
            video.write_bytes(b'\0')
            video.with_suffix('.md').write_text('p', encoding='utf-8')
            moved, meta, batches = [], {}, []

            def move(path, deleted, _missing, _skipped, moves):
                moved.append(path.name)
                deleted.append(str(path))
                moves.append({'from': str(path)})

            result = actions.delete_archive_videos(
                ['main/clip.mp4', 'main/clip.mp4'],
                resolve_video=lambda public: video if public == 'main/clip.mp4' else None,
                move_to_trash=move,
                snapshot_sets=lambda asset_id: [{'set_id': 's1', 'asset_id': asset_id}],
                remove_from_sets=lambda _asset_id: 1,
                update_meta=lambda asset_id, **patch: meta.update({asset_id: patch}),
                record_batch=lambda payload: batches.append(payload) or {'batch_id': 'b1'},
            )
        asset_id = actions.video_asset_id('main/clip.mp4')
        self.assertEqual(moved, ['clip.mp4', 'clip.md'])
        self.assertEqual(meta, {asset_id: {'hidden': True}})
        self.assertEqual((result['delete_batch_id'], result['set_updates']), ('b1', 1))
        self.assertEqual(batches[0]['set_snapshots'], [{'set_id': 's1', 'asset_id': asset_id}])
        self.assertEqual(batches[0]['task_snapshots'], [])

    def test_delete_rejects_bad_input(self) -> None:
        kwargs = dict(resolve_video=lambda _p: None, move_to_trash=None, snapshot_sets=None,
                      remove_from_sets=None, update_meta=None, record_batch=None)
        with self.assertRaises(ValueError):
            actions.delete_archive_videos([], **kwargs)
        with self.assertRaises(ValueError):
            actions.delete_archive_videos([f'main/{i}.mp4' for i in range(actions.MAX_VIDEO_DELETE + 1)], **kwargs)
        with self.assertRaises(FileNotFoundError):
            actions.delete_archive_videos(['main/missing.mp4'], **kwargs)

    def test_set_snapshot_keeps_video_fields(self) -> None:
        clean = asset_index._clean_asset_snapshot({
            'id': 'video_x', 'imageUrl': '/poster.jpg', 'mediaKind': 'video',
            'videoUrl': '/media/x.mp4', 'videoPath': 'main/x.mp4',
        })
        self.assertEqual((clean['mediaKind'], clean['videoUrl'], clean['videoPath']),
                         ('video', '/media/x.mp4', 'main/x.mp4'))


if __name__ == '__main__':
    unittest.main()
