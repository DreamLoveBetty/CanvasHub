"""CoMotion tracking for video pose capture: track selection, the rows behind each track, the detector's close-ups,
the detector fallback, install status and dependency pins. No models are loaded (the tracker is faked)."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

import numpy as np

from backend.pose_capture import install
from backend.pose_capture.comotion import Comotion, Tracker, bodies_for, observed
from backend.pose_capture.contracts import COMOTION_DIR, COMOTION_ENGINE, COMOTION_FILES
from backend.pose_capture.runtime import TRACKER_ENV, Runtime
from backend.pose_capture.video import VideoEngine, add_close_ups, select_tracks


def result(rows):
    """A CoMotion result from (id, frame, x0) rows: 100 x 200 boxes, pose/trans/betas tagged with the row."""
    rows = np.asarray(rows, dtype=np.float64)
    n = len(rows)
    return {'id': rows[:, 0].astype(np.int64), 'frame': rows[:, 1].astype(np.int64),
            'box': np.c_[rows[:, 2], np.full(n, 50.0), rows[:, 2] + 100, np.full(n, 250.0)],
            'pose': np.repeat(np.arange(n, dtype=np.float64)[:, None], 72, 1), 'trans': np.zeros((n, 3)), 'betas': np.zeros((n, 10))}


class TrackRowsTests(unittest.TestCase):
    def test_observed_groups_rows_by_id_inside_the_limit(self):
        r = result([(1, 0, 10), (1, 1, 11), (2, 0, 300), (1, 40, 50)])
        tracks = observed(r, limit=30)
        self.assertEqual(sorted(tracks), [1, 2])
        self.assertEqual(sorted(tracks[1]), [0, 1])
        np.testing.assert_allclose(tracks[2][0], [300, 50, 400, 250])

    def test_a_track_finds_its_rows_and_skips_the_frames_it_interpolated(self):
        # Person 1 seen at frames 0..39 except 10..14 (interpolated by select_tracks); a second person elsewhere.
        rows = [(1, f, 10 + f) for f in range(40) if not 10 <= f < 15] + [(2, f, 400) for f in range(40)]
        r = result(rows)
        tracks = select_tracks(observed(r, 40), people=2, length=40, fps=30.0)
        mine = next(t for t in tracks if t['boxes'][0, 0] < 100)
        bodies = bodies_for(r, mine)
        self.assertEqual(len(bodies['offset']), 35)
        self.assertNotIn(12, bodies['offset'].tolist())
        self.assertTrue((bodies['id'] == 1).all())
        np.testing.assert_array_equal(bodies['pose'][:, 0], [rows.index((1, f, 10 + f)) for f in bodies['offset']])

    def test_a_stitched_track_keeps_each_ids_rows(self):
        # CoMotion lost one person for a moment and gave them a new id: the product's stitching joins the two tracks.
        r = result([(1, f, 100 + f) for f in range(40)] + [(7, f, 100 + f) for f in range(44, 80)])
        tracks = select_tracks(observed(r, 80), people=1, length=80, fps=30.0)
        self.assertEqual(len(tracks), 1)
        bodies = bodies_for(r, tracks[0])
        self.assertEqual(sorted(set(bodies['id'].tolist())), [1, 7])
        self.assertEqual(len(bodies['offset']), 76)

    def test_no_matching_row_means_no_bodies(self):
        r = result([(1, f, 10) for f in range(40)])
        self.assertIsNone(bodies_for(r, {'start': 0, 'boxes': np.full((40, 4), 999.0)}))


def boxes(frames, box):
    return {f: np.asarray(box, dtype=np.float64) for f in frames}


class CloseUpTests(unittest.TestCase):
    """A 1280 x 720 selfie: CoMotion sees her only in a short waist-up shot, the detector the whole clip."""
    FACE = [100, 20, 1100, 715]                 # chest-up: 97 % of the frame height
    WAIST_UP = [250, 212, 873, 1294]            # CoMotion's mesh box runs far below the frame
    WAIST_UP_SEEN = [393, 187, 844, 716]        # the detector's box for that shot (IoU 0.69 with CoMotion's, clipped)
    PASSER = [1030, 320, 1060, 400]

    def test_a_close_up_comotion_missed_replaces_its_short_track(self):
        followed = {1023: boxes(range(239, 277), self.WAIST_UP), 58: boxes(range(0, 120), self.PASSER)}
        detected = {0: {**boxes(range(0, 239), self.FACE), **boxes(range(239, 334), self.WAIST_UP_SEEN)}}
        merged = add_close_ups(followed, detected, 1280, 720)
        self.assertEqual(sorted(merged), [-1, 58])
        self.assertEqual(len(merged[-1]), 334)
        chosen = select_tracks(merged, people=4, length=360, fps=24.0)
        self.assertEqual((chosen[0]['start'], len(chosen[0]['boxes'])), (0, 334))

    def test_people_comotion_follows_stay_its_own(self):
        dancer = [400, 100, 700, 715]
        followed = {5: boxes(range(0, 300), dancer)}
        detected = {3: boxes(range(0, 300), [410, 110, 690, 712])}
        self.assertEqual(add_close_ups(followed, detected, 1280, 720), followed)

    def test_small_people_and_fragments_only_the_detector_saw_are_left_out(self):
        followed = {5: boxes(range(0, 300), [400, 100, 700, 715])}
        detected = {8: boxes(range(0, 300), [1000, 300, 1060, 450]),   # a passer-by CoMotion did not follow
                    9: boxes(range(47, 52), [0, 3, 380, 715])}         # five frames of a tumbler
        self.assertEqual(add_close_ups(followed, detected, 1280, 720), followed)

    def test_comotion_tracks_take_the_detectors_close_ups_without_bodies(self):
        rows = [(1023, f, 250) for f in range(239, 277)]
        r = result(rows)
        r['box'][:] = CloseUpTests.WAIST_UP
        tracker = mock.Mock()
        tracker.track.return_value = {**r, 'size': (720, 1280)}
        comotion = Comotion.__new__(Comotion)
        comotion.tracker = tracker
        detected = {0: {**boxes(range(0, 239), self.FACE), **boxes(range(239, 334), self.WAIST_UP_SEEN)}}
        chosen = comotion.tracks('clip.mp4', 360, 4, 24.0, detected=detected)
        self.assertEqual(len(chosen), 1)
        self.assertEqual((chosen[0]['start'], len(chosen[0]['boxes'])), (0, 334))
        self.assertIsNone(chosen[0]['comotion'])

    def test_nobody_found_by_comotion_still_falls_back(self):
        tracker = mock.Mock()
        tracker.track.return_value = {**result([(1, 0, 10)]), 'id': np.zeros(0, np.int64), 'frame': np.zeros(0, np.int64),
                                      'box': np.zeros((0, 4)), 'size': None}
        comotion = Comotion.__new__(Comotion)
        comotion.tracker = tracker
        self.assertEqual(comotion.tracks('clip.mp4', 360, 4, 24.0, detected={0: boxes(range(0, 334), self.FACE)}), [])


class NewClipTests(unittest.TestCase):
    def test_each_clip_starts_with_a_fresh_shot_detector_and_counter(self):
        class Detector:
            def __init__(self, threshold, min_scene_len):
                self.settings, self.last_frame = (threshold, min_scene_len), None
        model = mock.Mock(shot_detector=Detector(50.0, 3), frame_count=231)
        model.shot_detector.last_frame = np.zeros((1280, 720, 3))   # the previous (portrait) clip's last frame
        tracker = Tracker.__new__(Tracker)
        tracker.model = model
        tracker._new_clip((720, 1280))
        self.assertIsNone(model.shot_detector.last_frame)
        self.assertEqual(model.shot_detector.settings, (50.0, 3))
        self.assertEqual(model.frame_count, 0)
        model.init_tracks.assert_called_once_with((720, 1280))


class FakeComotion:
    def __init__(self, tracks=None, error=None, report_error=None):
        self.result, self.error, self.report_error = tracks, error, report_error

    def tracks(self, path, limit, people, fps, report=None, detected=None):
        self.detected = detected
        if self.report_error is not None:
            report(3)
        if self.error is not None:
            raise self.error
        return self.result


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = VideoEngine.__new__(VideoEngine)   # _comotion_tracks needs no models

    def follow(self, comotion, report=lambda *a, **k: None):
        return self.engine._comotion_tracks(comotion, 'clip.mp4', 30, 4, 30.0, report)

    def test_comotion_tracks_are_used(self):
        tracks = [{'start': 0, 'boxes': np.zeros((30, 4))}]
        self.assertIs(self.follow(FakeComotion(tracks)), tracks)

    def test_the_clip_is_detected_once(self):
        seen = {0: boxes(range(30), [0, 0, 100, 200])}
        comotion = FakeComotion(tracks=[{'start': 0, 'boxes': np.zeros((30, 4))}])
        self.engine._comotion_tracks(comotion, 'clip.mp4', 30, 4, 30.0, lambda *a, **k: None, seen)
        self.assertIs(comotion.detected, seen)   # CoMotion gets the detector's tracks ...
        with mock.patch.object(VideoEngine, '_sightings', side_effect=AssertionError('detected twice')):
            tracks = self.engine._detect('clip.mp4', 30, 1, 4, 30.0, lambda *a, **k: None, seen)   # ... and so does the fallback
        self.assertEqual([len(t['boxes']) for t in tracks], [30])

    def test_nobody_found_or_a_failure_falls_back_to_the_detector(self):
        self.assertIsNone(self.follow(FakeComotion([])))
        log = io.StringIO()
        with redirect_stderr(log):
            self.assertIsNone(self.follow(FakeComotion(error=RuntimeError('MPS out of memory'))))
        self.assertIn('改用检测器', log.getvalue())

    def test_a_cancellation_still_ends_the_job(self):
        class Cancelled(Exception):
            pass

        def report(*a, **k):
            raise Cancelled('任务已取消')
        with self.assertRaises(Cancelled):
            self.follow(FakeComotion(report_error=True, error=RuntimeError('tracker stopped by the cancellation')), report)


class StatusTests(unittest.TestCase):
    def install(self, root, entry):
        receipt = {'comotion': entry}
        Path(root, 'installed.json').write_text(json.dumps(receipt))
        for name, (_, size, _) in COMOTION_FILES.items():
            path = Path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('wb') as f:
                f.truncate(size)   # sparse: only the size is checked
        Path(root, COMOTION_DIR, 'src', 'comotion_demo').mkdir(parents=True, exist_ok=True)

    def test_comotion_mode_needs_video_an_install_mps_files_and_pins(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Runtime(temp)
            entry = {'engine': COMOTION_ENGINE, 'device': 'mps'}
            self.assertEqual(runtime._comotion({'comotion': entry}, video=False)[0], False)
            self.assertIn('未安装', runtime._comotion({}, video=True)[1])
            self.assertIn('过旧', runtime._comotion({'comotion': {**entry, 'engine': 'comotion@old'}}, video=True)[1])
            self.assertIn('MPS', runtime._comotion({'comotion': {**entry, 'device': 'cpu'}}, video=True)[1])
            self.assertIn('缺失', runtime._comotion({'comotion': entry}, video=True)[1])
            self.install(temp, entry)
            with mock.patch.object(Runtime, '_packages', return_value=False):
                self.assertIn('依赖', runtime._comotion({'comotion': entry}, video=True)[1])
            with mock.patch.object(Runtime, '_packages', return_value=True):
                self.assertEqual(runtime._comotion({'comotion': entry}, video=True), (True, ''))
                with mock.patch.dict(os.environ, {TRACKER_ENV: 'detector'}):
                    self.assertIn('detector', runtime._comotion({'comotion': entry}, video=True)[1])

    def test_status_reports_the_mode_without_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            status = Runtime(temp).status()
            self.assertIs(status['modes']['comotion'], False)
            self.assertTrue(status['comotion_message'])
            self.assertNotIn(temp, json.dumps(status))


class DependencyPinTests(unittest.TestCase):
    def test_requirement_files_are_exact_pins(self):
        core, comotion = install.pinned('requirements-py314.txt'), install.pinned('requirements-comotion-py314.txt')
        self.assertEqual(core['timm'], '1.0.13')   # CoMotion's ConvNeXtV2 backbone needs timm >= 0.9; GEM-X runs unchanged on it
        self.assertEqual(comotion['scenedetect'], '0.6.5')
        self.assertFalse(set(core) & set(comotion))

    def test_a_files_own_packages_may_move_and_everything_else_stays_locked(self):
        seen = {}

        def run(cmd, check=False, **kwargs):
            if '-c' in cmd:
                seen['constraints'] = Path(cmd[cmd.index('-c') + 1]).read_text()
            return mock.Mock(returncode=0)
        installed = [mock.Mock(metadata={'Name': 'timm'}, version='0.6.7'), mock.Mock(metadata={'Name': 'torch'}, version='2.14.0')]
        with mock.patch.object(install.importlib.metadata, 'distributions', return_value=installed), \
                mock.patch.object(install.importlib.metadata, 'version', side_effect=lambda name: {'torch': '2.14.0'}[name]), \
                mock.patch.object(install.subprocess, 'run', side_effect=run):
            install.install_dependencies('requirements-py314.txt', prebuild=())
        self.assertIn('torch==2.14.0', seen['constraints'])
        self.assertNotIn('timm', seen['constraints'])


if __name__ == '__main__':
    unittest.main()
