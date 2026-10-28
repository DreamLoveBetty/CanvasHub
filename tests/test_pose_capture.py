"""Portable pose-capture tests: scene conversion, upload contract, job lifecycle, status, HTTP.

Synthetic engine output and a fake runtime only; no GEM-X, models or network. The keypoint-fit tests
use torch when it is installed and are skipped otherwise.
"""
import base64
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from backend.pose_capture.bodies import BodyStore, body_id
from backend.pose_capture.contracts import DINOV3_COMMIT, EVIDENCE_FILES, MODEL_FILES, SAM3DB_COMMIT, normalize, video_suffix
from backend.pose_capture import evidence as evidence_mod
from backend.pose_capture.refine import (carry_world, fit_pose, fit_sequence, hold_unseen_legs, keypoint_weights, steady_trunk,
                                         upper_body_only)
from backend.pose_capture.runtime import PoseCaptureCancelled, PoseCaptureError, Runtime
from backend.pose_capture.scene import (MANNEQUIN_HEIGHT, axis_angle, build_sequence, build_snapshot, camera_to_world, common_ground,
                                        nearest_aspect, rodrigues)
from backend.pose_capture.video import (fill_dropouts, frame_speed, interpolate_quats, interpolate_rows, keep_evidence, select_tracks,
                                        smooth_keypoints, smooth_series, stitch, trusted_tracks)
from backend.pose_capture.service import PoseCaptureService
from backend.routes.pose_capture_routes import create_router

FLIP = np.diag([1.0, -1.0, -1.0])  # OpenCV camera frame vs a Y-up body facing the camera


def png_bytes(width=64, height=48):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (width, height), (120, 130, 140)).save(out, format='PNG')
    return out.getvalue()


def person(x=0.0, depth=3.0, yaw_world=0.0, tilt_deg=0.0, height=MANNEQUIN_HEIGHT, score=0.9, height_px=480, lift=0.0):
    """A T-pose-ish body standing `depth` metres in front of a camera pitched down by `tilt_deg`."""
    pitch = rodrigues([math.radians(tilt_deg), 0, 0])  # camera tilt around its x axis
    cam_from_body = pitch @ FLIP
    joints_body = np.zeros((77, 3))
    joints_body[:, 1] = np.linspace(0.0, 1.7, 77) - 0.9  # hips at index 0 sits mid-body after the shift below
    joints_body[0] = [0, 0, 0]
    joints_body[7] = [0, 0.8, 0]
    centre = pitch @ np.array([x, -lift, depth])  # camera y points down
    joints_cam = (cam_from_body @ joints_body.T).T + centre
    world_from_body = rodrigues([0, math.radians(yaw_world), 0])
    K = np.array([[800.0, 0, 320], [0, 800.0, height_px / 2], [0, 0, 1]])
    uv = (K @ joints_cam.T).T
    keypoints = np.c_[uv[:, :2] / uv[:, 2:], np.full(77, 0.9)]
    return {'incam': {'global_orient': axis_angle(cam_from_body), 'body_pose': np.zeros(76 * 3), 'joints': joints_cam,
                      'identity_coeffs': np.zeros(45), 'scale_params': np.r_[1.0, np.zeros(68)]},
            'global': {'global_orient': axis_angle(world_from_body), 'joints': (world_from_body @ joints_body.T).T},
            'K': K, 'keypoints': keypoints, 'bbx_xys': np.array([320, 240, 300.0]), 'box_xyxy': np.array([200, 40, 440, 460.0]),
            'score': score, 'rest_height': height}


def decode(rotations):
    raw = base64.b64decode(rotations.split(':', 1)[1])
    return np.frombuffer(raw, dtype=np.float32).reshape(77, 3)


class SceneTests(unittest.TestCase):
    def test_level_camera_person_faces_camera_on_floor(self):
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [person(yaw_world=1.2)]}, asset_id='a' * 32)
        p = snap['people'][0]
        hips_world = rodrigues(decode(p['frames']['rotations'])[0])
        np.testing.assert_allclose(hips_world, np.eye(3), atol=1e-5)  # facing +Z, upright: the camera side
        cam = snap['cameras'][0]
        self.assertAlmostEqual(cam['position'][2], 3.0, places=4)  # camera 3 m in front of the person
        self.assertGreater(cam['position'][2], cam['target'][2])
        self.assertAlmostEqual(cam['roll_deg'], 0.0, places=4)
        self.assertEqual(p['frames']['transl'][0][0], 0.0)
        self.assertGreaterEqual(min(p['frames']['transl'][0][1], 0), 0)  # floor at y = 0
        self.assertEqual(snap['source']['input_asset_id'], 'a' * 32)

    def test_pitched_camera_is_levelled_by_gravity(self):
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [person(tilt_deg=20)]})
        hips_world = rodrigues(decode(snap['people'][0]['frames']['rotations'])[0])
        np.testing.assert_allclose(hips_world @ [0, 1, 0], [0, 1, 0], atol=1e-5)  # body stays upright in the world
        cam = snap['cameras'][0]
        direction = np.subtract(cam['target'], cam['position'])
        self.assertAlmostEqual(math.degrees(math.atan2(-direction[1], -direction[2])), 20.0, places=2)  # positions are rounded

    def test_camera_basis_is_right_handed(self):
        basis = camera_to_world([person(tilt_deg=10)])
        self.assertAlmostEqual(float(np.linalg.det(basis)), 1.0, places=6)
        np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-9)

    def test_multi_person_layout_heights_and_camera(self):
        people = [person(x=-0.6, height=1.1 * MANNEQUIN_HEIGHT, score=0.95), person(x=0.6, depth=4.0, height=0.9 * MANNEQUIN_HEIGHT, score=0.6)]
        snap = build_snapshot({'width': 640, 'height': 480, 'people': people})
        a, b = snap['people']
        self.assertLess(a['frames']['transl'][0][0], b['frames']['transl'][0][0])
        self.assertGreater(a['frames']['transl'][0][2], b['frames']['transl'][0][2])  # the farther person is deeper (-Z)
        self.assertAlmostEqual(a['frames']['transl'][0][0] + b['frames']['transl'][0][0], 0.0, places=4)  # centred
        self.assertGreater(a['height_cm'], b['height_cm'])
        self.assertLessEqual(abs(a['height_cm'] - 192.5), 1)  # 175 * 1.1 / median 1.0
        self.assertLessEqual(abs(b['height_cm'] - 157.5), 1)
        cam = snap['cameras'][0]
        self.assertEqual((cam['focal_mm'], cam['aspect'], cam['width'], cam['height']), (40, '4:3', 640, 480))
        self.assertLess(a['diagnostics']['reprojection_median_pct'], 1e-3)

    def test_single_person_is_175_cm_and_empty_photo(self):
        self.assertEqual(build_snapshot({'width': 640, 'height': 480, 'people': [person(height=2.1)]})['people'][0]['height_cm'], 175)
        empty = build_snapshot({'width': 640, 'height': 480, 'people': []})
        self.assertEqual((empty['people'], empty['cameras'], empty['active_camera']), ([], [], None))

    def test_people_off_the_shared_floor_keep_their_lift(self):
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [person(x=-0.6), person(x=0.6, lift=0.3)]})
        self.assertEqual([p['floor_offset'] for p in snap['people']], [0.0, 0.3])
        names = ['Hips'] + [f'J{i}' for i in range(75)] + ['LeftFoot']  # only the foot joint defines the floor
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [person(x=-0.6), person(x=0.6, lift=0.3)]}, joint_names=names)
        self.assertEqual([p['floor_offset'] for p in snap['people']], [0.0, 0.3])

    def test_height_normalisation_scales_scene_about_the_camera(self):
        tall = person(depth=3.0, height=1.1 * MANNEQUIN_HEIGHT)
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [tall]})
        cam = snap['cameras'][0]
        hips = np.array(snap['people'][0]['frames']['transl'][0])
        # The 175 cm mannequin is 1.1x shorter, so the camera moves 1.1x closer and the body keeps its size in frame.
        self.assertAlmostEqual(np.linalg.norm(hips - cam['position']), 3.0 / 1.1, places=3)
        self.assertEqual(snap['people'][0]['height_cm'], 175)

    def test_axis_angle_round_trip_and_aspects(self):
        rng = np.random.default_rng(4)
        for v in [np.array([math.pi, 0, 0]), np.array([0, 0, math.pi - 1e-8])] + [rng.normal(size=3) for _ in range(100)]:
            np.testing.assert_allclose(rodrigues(axis_angle(rodrigues(v))), rodrigues(v), atol=1e-6)
        self.assertEqual(nearest_aspect(720, 1080), '2:3')
        self.assertEqual(nearest_aspect(1920, 1080), '16:9')
        self.assertEqual(nearest_aspect(1000, 990), '1:1')


class ContractTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize({'asset_id': 'b' * 32}), {'asset_id': 'b' * 32, 'max_people': 6, 'mode': 'photo'})
        self.assertEqual(normalize({'asset_id': 'b' * 32, 'max_people': 6}, 'video')['max_people'], 4, 'videos cap at four people')
        self.assertEqual(normalize({'asset_id': 'b' * 32}, 'video')['mode'], 'video')
        self.assertIs(normalize({'asset_id': 'b' * 32}, 'video')['evidence'], True, 'image evidence is on unless turned off')
        self.assertIs(normalize({'asset_id': 'b' * 32, 'evidence': False}, 'video')['evidence'], False)
        self.assertNotIn('evidence', normalize({'asset_id': 'b' * 32, 'evidence': True}), 'photos have no image evidence')
        with self.assertRaises(ValueError): normalize({'asset_id': 'b' * 32, 'evidence': 'yes'}, 'video')
        for body in ({'asset_id': 'x'}, {'asset_id': 'b' * 32, 'max_people': 0}, {'asset_id': 'b' * 32, 'max_people': True},
                     {'asset_id': 'b' * 32, 'path': '/etc/passwd'}, []):
            with self.assertRaises(ValueError): normalize(body)

    def test_video_containers_are_recognised_by_signature(self):
        self.assertEqual(video_suffix(b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00'), '.mp4')
        self.assertEqual(video_suffix(b'\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00'), '.mov')
        self.assertEqual(video_suffix(b'\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81'), '.webm')
        for data in (png_bytes(), b'', b'ftyp', b'GIF89a' + b'\x00' * 10):
            self.assertIsNone(video_suffix(data))

    def test_every_model_file_is_pinned(self):
        for name, (url, size, sha256) in MODEL_FILES.items():
            self.assertTrue(name.startswith(('gemx/inputs/', 'models/')), name)
            self.assertGreater(size, 0)
            self.assertRegex(sha256, '^[0-9a-f]{64}$')
            self.assertTrue(url is None or url.startswith('https://'), name)
        for name, (url, size, sha256) in EVIDENCE_FILES.items():
            self.assertTrue(name.startswith('gemx/inputs/') and url.startswith('https://huggingface.co/nvidia/GEM-X/resolve/'), name)
            self.assertGreater(size, 0)
            self.assertRegex(sha256, '^[0-9a-f]{64}$')
        for commit in (SAM3DB_COMMIT, DINOV3_COMMIT):
            self.assertRegex(commit, '^[0-9a-f]{40}$', 'image evidence code is pinned, never a branch')


class FakeRuntime:
    def __init__(self, ready=True, outcome='ok', video=True, evidence=False, comotion=False):
        self.ready, self.outcome, self.video, self.evidence, self.calls = ready, outcome, video, evidence, []
        self.comotion = comotion
        self.closed = 0

    def status(self):
        return {'state': 'ready' if self.ready else 'missing', 'ready': self.ready,
                'modes': {'photo': self.ready, 'video': self.ready and self.video, 'evidence': self.ready and self.evidence,
                          'comotion': self.ready and self.video and self.comotion},
                'video_message': '影片识别尚未就绪'}

    def execute(self, spec, directory, cancelled, progress):
        self.calls.append(spec)
        progress(0.5, '识别姿势 1/1')
        if self.outcome == 'slow':
            while not cancelled.is_set():
                time.sleep(.01)
            raise PoseCaptureCancelled('任务已取消')
        if self.outcome == 'fail':
            raise PoseCaptureError('合成失败')
        if spec.get('mode') == 'video':
            snap = build_sequence({'fps': 30.0, 'frames': 64, 'width': 640, 'height': 480, 'people': [video_person()]},
                                  asset_id=spec['asset_id'])
        else:
            snap = build_snapshot({'width': 64, 'height': 48, 'people': [person(height_px=48)]}, asset_id=spec['asset_id'])
        Path(directory, 'result.json').write_text(json.dumps(snap))
        return {'people': 1, 'paths': [Path(directory, 'result.json')]}

    def close(self):
        self.closed += 1

    def close_idle(self):
        self.closed += 1


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def service(self, name='data', **kwargs):
        service = PoseCaptureService(self.root / name, FakeRuntime(**kwargs))
        self.addCleanup(service.close)
        return service

    def finished(self, service, job):
        for _ in range(500):
            current = service.job(job['id'])
            if current['status'] not in ('queued', 'running', 'cancelling'):
                return current
            time.sleep(.01)
        self.fail('job did not finish')

    def test_upload_validation_and_dedupe(self):
        service = self.service()
        first = service.upload(png_bytes(), 'a.png')
        self.assertEqual((first['width'], first['height']), (64, 48))
        self.assertEqual(service.upload(png_bytes(), '../../b.png')['asset_id'], first['asset_id'])
        self.assertEqual(json.loads(service.store.asset(first['asset_id']).with_suffix('.json').read_text())['name'], 'b.png')
        for data in (b'', b'not an image', png_bytes(8, 8)):
            with self.assertRaises(ValueError): service.upload(data, 'x')
        with self.assertRaises(FileNotFoundError): service.store.asset('0' * 32)

    def test_success_returns_contract_result(self):
        service = self.service()
        asset = service.upload(png_bytes(), 'a.png')
        job = self.finished(service, service.submit({'asset_id': asset['asset_id'], 'max_people': 2}))
        self.assertEqual((job['status'], job['people'], job['stage']), ('succeeded', 1, '识别完成'))
        self.assertEqual(job['result']['skeleton'], 'soma77')
        spec = service.runtime.calls[0]
        self.assertTrue(Path(spec['image']).is_absolute() and spec['max_people'] == 2)

    def test_failure_cancel_and_not_installed(self):
        service = self.service(outcome='fail')
        asset = service.upload(png_bytes(), 'a.png')
        job = self.finished(service, service.submit({'asset_id': asset['asset_id']}))
        self.assertEqual((job['status'], job['error']), ('failed', '合成失败'))
        slow = self.service('slow', outcome='slow')
        slow_job = slow.submit({'asset_id': slow.upload(png_bytes(), 'a.png')['asset_id']})
        time.sleep(.05)
        self.assertIn(slow.cancel(slow_job['id'])['status'], ('cancelling', 'cancelled'))
        self.assertEqual(self.finished(slow, slow_job)['status'], 'cancelled')
        missing = PoseCaptureService(self.root / 'other', FakeRuntime(ready=False))
        self.addCleanup(missing.close)
        with self.assertRaises(RuntimeError):
            missing.submit({'asset_id': missing.upload(png_bytes(), 'a.png')['asset_id']})

    def test_video_upload_submit_and_sequence_result(self):
        service = self.service()
        mp4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00' + b'\x00' * 64
        asset = service.upload(mp4, 'clip.mp4')
        self.assertEqual((asset['kind'], service.store.asset(asset['asset_id']).suffix), ('video', '.mp4'))
        job = self.finished(service, service.submit({'asset_id': asset['asset_id'], 'max_people': 6}))
        self.assertEqual((job['spec']['mode'], job['spec']['max_people']), ('video', 4))
        self.assertNotIn('result', job, 'a sequence is fetched separately, not with every poll')
        self.assertEqual(job['result_url'], '/api/pose_capture/result?id=' + job['id'])
        self.assertEqual(service.result(job['id'])['frame_count'], 64)
        photo = self.finished(service, service.submit({'asset_id': service.upload(png_bytes(), 'a.png')['asset_id']}))
        self.assertIn('result', photo)
        with self.assertRaises(ValueError): service.upload(b'\x00\x00\x00\x18ftypisom' + b'\x00' * (200 * 1024 * 1024), 'big.mp4')

    def test_video_evidence_follows_the_install(self):
        mp4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00' + b'\x00' * 64
        for installed, asked, sent in ((False, True, False), (True, True, True), (True, False, False)):
            service = self.service(name=f'evidence-{installed}-{asked}', evidence=installed)
            asset = service.upload(mp4, 'clip.mp4')
            self.finished(service, service.submit({'asset_id': asset['asset_id'], 'evidence': asked}))
            self.assertIs(service.runtime.calls[0]['evidence'], sent, (installed, asked))

    def test_video_tracker_follows_the_install(self):
        mp4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00' + b'\x00' * 64
        for installed in (False, True):
            service = self.service(name=f'comotion-{installed}', comotion=installed)
            asset = service.upload(mp4, 'clip.mp4')
            self.finished(service, service.submit({'asset_id': asset['asset_id']}))
            self.assertIs(service.runtime.calls[0]['comotion'], installed)
            with self.assertRaisesRegex(ValueError, '不支持'):   # the client cannot choose the tracker
                service.submit({'asset_id': asset['asset_id'], 'comotion': True})
        photo = self.service(name='comotion-photo', comotion=True)
        self.finished(photo, photo.submit({'asset_id': photo.upload(png_bytes(), 'a.png')['asset_id']}))
        self.assertNotIn('comotion', photo.runtime.calls[0])

    def test_video_needs_the_video_install(self):
        service = self.service('novideo', video=False)
        asset = service.upload(b'\x1a\x45\xdf\xa3' + b'\x00' * 32, 'clip.webm')
        with self.assertRaisesRegex(RuntimeError, '影片识别'):
            service.submit({'asset_id': asset['asset_id']})
        with self.assertRaises(FileNotFoundError): service.result('f' * 32)

    def test_body_assets_reach_the_worker_only_when_installed(self):
        service = self.service()
        asset = service.upload(png_bytes(), 'a.png')
        self.finished(service, service.submit({'asset_id': asset['asset_id']}))
        self.assertNotIn('bodies', service.runtime.calls[0])
        assets = self.root / 'soma-assets'
        with_bodies = PoseCaptureService(self.root / 'bodies-data', FakeRuntime(), body_assets=lambda: assets)
        self.addCleanup(with_bodies.close)
        asset = with_bodies.upload(png_bytes(), 'a.png')
        self.finished(with_bodies, with_bodies.submit({'asset_id': asset['asset_id']}))
        spec = with_bodies.runtime.calls[0]
        self.assertEqual(spec['bodies'], {'dir': str((self.root / 'bodies-data' / 'bodies').resolve()), 'soma_assets': str(assets)})

    def test_interrupted_jobs_recover(self):
        service = self.service()
        job = service.store.create({'asset_id': 'c' * 32, 'max_people': 1})
        service.store.update(job['id'], status='running')
        service.job(job['id'])  # starting the queue recovers stale jobs
        self.assertEqual(service.store.get(job['id'])['status'], 'interrupted')


HAS_TORCH = importlib.util.find_spec('torch') is not None


def chain_forward(torch):
    """A two-bone leg hanging from a hip 3 m in front of the camera: body_pose rotates both bones."""
    def rot(v):
        angle = v.norm().clamp(min=1e-9)
        k = v / angle
        K = torch.stack([torch.stack([0 * k[0], -k[2], k[1]]), torch.stack([k[2], 0 * k[0], -k[0]]), torch.stack([-k[1], k[0], 0 * k[0]])])
        return torch.eye(3) + torch.sin(angle) * K + (1 - torch.cos(angle)) * K @ K

    def forward(global_orient, body_pose):
        root = rot(global_orient.reshape(3))
        upper = root @ rot(body_pose.reshape(-1, 3)[0])
        lower = upper @ rot(body_pose.reshape(-1, 3)[1])
        hip = torch.tensor([0.0, 0.0, 3.0])
        knee = hip + upper @ torch.tensor([0.0, 0.45, 0.0])
        ankle = knee + lower @ torch.tensor([0.0, 0.45, 0.0])
        return torch.stack([hip, knee, ankle])
    return forward


class KeypointFitTests(unittest.TestCase):
    def test_weights_drop_unsure_joints_and_damp_fingers(self):
        kp = np.array([[0, 0, 0.9], [0, 0, 0.2], [0, 0, 0.8]])
        np.testing.assert_allclose(keypoint_weights(kp, ['Hips', 'LeftLeg', 'LeftHandIndex1']), [0.9, 0.0, 0.08])

    def test_video_fit_takes_feet_only_when_reliably_seen(self):
        # A guessed ankle past the frame edge (0.51) and toes (0.54) must not pull the leg; the knee at 0.55 still counts.
        names = ['LeftShin', 'LeftFoot', 'LeftToeBase', 'RightFoot']
        kp = np.array([[0, 0, 0.55], [0, 0, 0.51], [0, 0, 0.54], [0, 0, 0.9]])
        np.testing.assert_allclose(keypoint_weights(kp, names, min_confidence=0.5, foot_min_confidence=0.7), [0.55, 0.0, 0.0, 0.9])
        np.testing.assert_allclose(keypoint_weights(kp, names, min_confidence=0.5), [0.55, 0.51, 0.54, 0.9], err_msg='photos unchanged')

    def test_world_rotation_follows_the_camera_frame_change(self):
        world, before, after = [0.1, 1.2, -0.3], [2.9, 0.2, 0.1], [2.7, 0.4, 0.05]
        new = carry_world(world, before, after)
        np.testing.assert_allclose(rodrigues(new) @ rodrigues(after).T, rodrigues(world) @ rodrigues(before).T, atol=1e-9)

    @unittest.skipUnless(HAS_TORCH, 'torch not installed')
    def test_fit_pulls_a_misplaced_knee_onto_its_keypoints(self):
        import torch
        forward = chain_forward(torch)
        K = np.array([[1000.0, 0, 320], [0, 1000.0, 240], [0, 0, 1]])
        truth = np.array([0.6, 0.0, 0.3, -1.1, 0.0, 0.0])  # thigh swung forward and across, shin folded back
        with torch.no_grad():
            joints = forward(torch.zeros(1, 3), torch.tensor(truth, dtype=torch.float32)[None]).numpy()
        uv = (K @ joints.T).T
        keypoints = np.c_[uv[:, :2] / uv[:, 2:], np.full(3, 0.95)]
        start = truth + np.array([-0.4, 0.0, -0.3, 0.6, 0.0, 0.0])  # what the prior produced: knee under the hip
        orient, pose, info = fit_pose(forward, np.zeros(3), start, keypoints, K, 300.0, np.ones(3), steps=400)
        self.assertTrue(info['accepted'])
        self.assertLess(info['error_after'], info['error_before'] / 4)
        self.assertEqual(pose.shape, start.shape)
        with torch.no_grad():
            fitted = forward(torch.tensor(orient, dtype=torch.float32)[None], torch.tensor(pose, dtype=torch.float32)[None]).numpy()
        projected = (K @ fitted.T).T
        self.assertLess(np.abs(projected[:, :2] / projected[:, 2:] - keypoints[:, :2]).max(), 6)

    @unittest.skipUnless(HAS_TORCH, 'torch not installed')
    def test_video_fit_moves_a_misplaced_body_to_its_keypoints(self):
        # A close-up: GEM-X put the person too high and too far; rotations alone cannot move the body.
        import torch
        single = chain_forward(torch)
        forward = lambda go, bp: torch.stack([single(go[i], bp[i]) for i in range(len(go))])
        K = np.array([[1000.0, 0, 320], [0, 1000.0, 240], [0, 0, 1]])
        pose = np.tile([0.2, 0.0, 0.0, -0.3, 0.0, 0.0], (2, 1))
        shift = np.array([[0.0, 0.0, 0.0], [0.05, 0.35, -0.6]])  # frame 1: lower and closer than GEM-X said
        with torch.no_grad():
            truth = forward(torch.zeros(2, 3), torch.tensor(pose, dtype=torch.float32)).numpy() + shift[:, None]
        uv = truth @ K.T
        keypoints = np.concatenate([uv[..., :2] / uv[..., 2:], np.full((2, 3, 1), 0.95)], -1)
        orient, fitted, offset, info = fit_sequence(forward, np.zeros((2, 3)), pose, keypoints, K, np.array([300.0, 300.0]),
                                                    np.ones((2, 3)), steps=400)
        self.assertEqual((orient.shape, fitted.shape, offset.shape), ((2, 3), (2, 6), (2, 3)))
        self.assertLess(np.abs(offset[0]).max(), 0.03, 'a frame GEM-X placed right stays put')
        self.assertGreater(offset[1, 1], 0.2)
        self.assertLess(info['worst_after'], info['worst_before'] / 4)
        with torch.no_grad():
            joints = forward(torch.tensor(orient, dtype=torch.float32), torch.tensor(fitted, dtype=torch.float32)).numpy() + offset[:, None]
        projected = joints @ K.T
        self.assertLess(np.abs(projected[..., :2] / projected[..., 2:] - keypoints[..., :2]).max(), 15)  # from ~150 px; the weak anchor keeps a little

    @unittest.skipUnless(HAS_TORCH, 'torch not installed')
    def test_evidence_moves_a_joint_in_depth_and_keeps_the_2d(self):
        import torch
        single = chain_forward(torch)
        forward = lambda go, bp: torch.stack([single(go[i], bp[i]) for i in range(len(go))])
        K = np.array([[1000.0, 0, 320], [0, 1000.0, 240], [0, 0, 1]])
        pose = np.array([[0.0, 0.0, 0.0, 0.6, 0.0, 0.0]])   # knee bent: the ankle swings towards the camera
        with torch.no_grad():
            joints = forward(torch.zeros(1, 3), torch.tensor(pose, dtype=torch.float32)).numpy()
        uv = joints @ K.T
        keypoints = np.concatenate([uv[..., :2] / uv[..., 2:], np.full((1, 3, 1), 0.95)], -1)
        start = np.array([[0.0, 0.0, 0.0, 0.2, 0.0, 0.0]])   # GEM-X bent the knee less; its depth anchor holds that
        evidence = {'depth': np.zeros((1, 3)), 'depth_mask': np.zeros((1, 3)), 'shape': np.zeros((1, 3, 3)),
                    'shape_mask': np.zeros((1, 3)), 'shape_base': np.arange(3)}
        evidence['depth'][0, 2] = joints[0, 2, 2] - joints[0, 0, 2]
        evidence['depth_mask'][0, 2] = 1.0
        args = (forward, np.zeros((1, 3)), start, keypoints, K, np.array([300.0]), np.ones((1, 3)))
        _, plain, _, _ = fit_sequence(*args, steps=400)
        orient, fitted, offset, info = fit_sequence(*args, steps=400, evidence=evidence)
        with torch.no_grad():
            got = forward(torch.tensor(orient, dtype=torch.float32), torch.tensor(fitted, dtype=torch.float32)).numpy() + offset[:, None]
            without = forward(torch.zeros(1, 3), torch.tensor(plain, dtype=torch.float32)).numpy()
        target = evidence['depth'][0, 2]
        miss = abs((got[0, 2, 2] - got[0, 0, 2]) - target)
        self.assertLess(miss, abs((without[0, 2, 2] - without[0, 0, 2]) - target), 'the evidence replaces the GEM-X depth anchor')
        self.assertLess(miss, 0.02)
        projected = got @ K.T
        self.assertLess(np.abs(projected[..., :2] / projected[..., 2:] - keypoints[..., :2]).max(), 8)

    @unittest.skipUnless(HAS_TORCH, 'torch not installed')
    def test_depth_anchor_stops_limbs_swinging_towards_the_camera(self):
        import torch
        forward = chain_forward(torch)
        K = np.array([[1000.0, 0, 320], [0, 1000.0, 240], [0, 0, 1]])
        start = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # a straight leg hanging down
        with torch.no_grad():
            straight = forward(torch.zeros(1, 3), torch.tensor(start, dtype=torch.float32)[None]).numpy()
        uv = (K @ straight.T).T
        # Keypoints that a shorter-looking leg would explain by swinging it towards the camera.
        keypoints = np.c_[uv[:, :2] / uv[:, 2:], np.ones(3)]
        keypoints[1:, 1] -= np.array([40.0, 90.0])
        _, _, loose = fit_pose(forward, np.zeros(3), start, keypoints, K, 300.0, np.ones(3), depth_anchor=0.0, steps=300)
        _, _, held = fit_pose(forward, np.zeros(3), start, keypoints, K, 300.0, np.ones(3), depth_anchor=5.0, steps=300)
        self.assertTrue(loose['accepted'] and held['accepted'])
        self.assertGreater(loose['depth_shift_cm'], 10)
        self.assertLess(held['depth_shift_cm'], loose['depth_shift_cm'] / 3)

    @unittest.skipUnless(HAS_TORCH, 'torch not installed')
    def test_fit_keeps_the_input_when_it_cannot_help(self):
        import torch
        forward = chain_forward(torch)
        K = np.array([[1000.0, 0, 320], [0, 1000.0, 240], [0, 0, 1]])
        pose = np.array([0.2, 0.0, 0.0, -0.4, 0.0, 0.0])
        with torch.no_grad():
            joints = forward(torch.zeros(1, 3), torch.tensor(pose, dtype=torch.float32)[None]).numpy()
        uv = (K @ joints.T).T
        exact = np.c_[uv[:, :2] / uv[:, 2:], np.ones(3)]
        orient, kept, info = fit_pose(forward, np.zeros(3), pose, exact, K, 300.0, np.ones(3), steps=20)
        self.assertFalse(info['accepted'])
        np.testing.assert_array_equal(kept, pose)
        broken = lambda g, b: forward(g, b) * float('nan')
        _, kept, info = fit_pose(broken, np.zeros(3), pose, exact, K, 300.0, np.ones(3), steps=5)
        self.assertFalse(info['accepted'])
        np.testing.assert_array_equal(kept, pose)

    def test_snapshot_reports_the_fit(self):
        fit = {'accepted': True, 'error_before': 4.3, 'error_after': 1.3, 'depth_shift_cm': 10.9, 'steps': 183, 'seconds': 1.2}
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [{**person(), 'fit': fit}, person(x=1)]})
        self.assertEqual(snap['people'][0]['diagnostics']['keypoint_fit'], fit)
        self.assertNotIn('keypoint_fit', snap['people'][1]['diagnostics'])


def video_person(frames=60, x=0.0, depth=3.0, bob=0.0, jump_at=None):
    """A person walking sideways in front of a level camera; optional vertical bob (depth noise) and a jump."""
    base = person(x=x, depth=depth)
    joints = np.repeat(base['incam']['joints'][None], frames, 0).copy()
    joints[:, :, 0] += np.linspace(0, 0.5, frames)[:, None]
    world = joints.copy()
    world[:, :, 1] *= -1  # world joints only need a Y-up vertical; their sideways drift is ignored
    if bob:
        joints[:, :, 1] += bob * np.sin(np.arange(frames) * 1.3)[:, None]  # camera y points down
    if jump_at is not None:
        world[jump_at:jump_at + 5, :, 1] += 0.3
    orient = np.repeat(np.asarray(base['incam']['global_orient'])[None], frames, 0)
    return {'start': 2, 'count': frames, 'K': base['K'], 'keypoints': np.repeat(base['keypoints'][None], frames, 0),
            'incam': {'global_orient': orient, 'body_pose': np.zeros((frames, 76 * 3)), 'joints': joints,
                      'identity_coeffs': np.zeros(45), 'scale_params': np.r_[1.0, np.zeros(68)]},
            'global': {'global_orient': np.repeat(np.asarray(base['global']['global_orient'])[None], frames, 0), 'joints': world},
            'score': 0.9, 'rest_height': MANNEQUIN_HEIGHT, 'coverage': 1.0}


class VideoSceneTests(unittest.TestCase):
    def result(self, *people):
        return {'fps': 30.0, 'frames': 64, 'source_frames': 300, 'truncated': True, 'width': 640, 'height': 480,
                'people': list(people), 'backend': 'coreml'}

    def test_sequence_contract_shapes(self):
        snap = build_sequence(self.result(video_person()), asset_id='a' * 32)
        self.assertEqual((snap['fps'], snap['frame_count'], snap['source']['kind'], snap['source']['truncated']), (30.0, 64, 'video', True))
        frames = snap['people'][0]['frames']
        self.assertEqual((frames['start'], frames['count'], len(frames['transl']), len(frames['lift'])), (2, 60, 60, 60))
        self.assertEqual(len(base64.b64decode(frames['rotations'].split(':', 1)[1])), 60 * 77 * 3 * 4)
        self.assertEqual(len(snap['people'][0]['confidence']), 60)
        self.assertLess(abs(frames['transl'][0][0]), 0.02)  # centred on the first frame (smoothing nudges it)
        self.assertGreater(frames['transl'][-1][0], frames['transl'][0][0] + 0.3)  # walks to the camera's right
        self.assertEqual(snap['cameras'][0]['label'], '视频机位')
        self.assertEqual(build_sequence(self.result())['people'], [])
        tracked = build_sequence({**self.result(video_person()), 'tracker': {'engine': 'comotion', 'seconds': 31.2}})
        self.assertEqual(tracked['source']['tracker'], {'engine': 'comotion', 'seconds': 31.2})

    def test_lift_ignores_camera_bob_and_keeps_world_jumps(self):
        snap = build_sequence(self.result(video_person(bob=0.08, jump_at=30)))
        lift = np.array(snap['people'][0]['frames']['lift'])
        self.assertLess(np.median(lift), 0.02, 'depth jitter along the camera ray does not lift a standing person')
        self.assertGreater(lift[30:35].max(), 0.15, 'a jump in the world trajectory survives')
        self.assertLess(np.abs(np.r_[lift[:30], lift[35:]]).max(), 0.03, 'the jump does not pull the frames around it down')

    def test_a_chest_up_person_follows_the_camera_view_frame_by_frame(self):
        selfie = {**video_person(bob=0.08, jump_at=30), 'upper_body': True}   # a hand-held selfie bobs; GEM-X's world is a guess
        snap = build_sequence(self.result(selfie))
        frames = snap['people'][0]['frames']
        seen = -np.asarray(selfie['incam']['joints'])[:, 0, 1]                # camera y points down
        np.testing.assert_allclose(np.diff(frames['hips']), np.diff(seen), atol=2e-3)   # (heights are rounded to mm)
        np.testing.assert_allclose(np.diff(np.asarray(frames['transl'])[:, 0]), np.diff(selfie['incam']['joints'][:, 0, 0]), atol=2e-4)
        self.assertIs(snap['people'][0]['diagnostics']['upper_body'], True)

    def test_hips_follow_the_camera_on_a_push_in(self):
        # The camera pushes in: the hips sink in the camera view while GEM-X's world keeps the person on its floor.
        walker = video_person()
        sink = np.clip(np.linspace(-0.1, 0.5, 60), 0.0, None)
        walker['incam']['joints'][:, :, 1] += sink[:, None]  # camera y points down
        walker['keypoints'][sink > 0, :, 2] = 0.1             # the feet leave the frame as it pushes in
        snap = build_sequence(self.result(walker))
        lift = np.array(snap['people'][0]['frames']['lift'])
        hips_above_feet = 0.9 - 1.7 / 76  # fixture: hips at index 0, its lowest joint (index 1) this far below
        rendered = lift + hips_above_feet
        expected = hips_above_feet - sink
        error = np.abs(rendered - expected)
        self.assertLess(error.mean(), 0.01, 'the hips land where the camera sees them')
        self.assertLess(error.max(), 0.04, 'the running median only rounds the start of the push-in')
        self.assertLess(lift[-1], -0.4, 'the camera, not GEM-X\'s floor contact, sets the height')
        hips = np.array(snap['people'][0]['frames']['hips'])
        np.testing.assert_allclose(hips, lift + hips_above_feet, atol=2e-3, err_msg='hips = lift + the hips above the lowest foot')

    def test_held_legs_lower_the_figure_and_keep_the_hips(self):
        walker = video_person()
        walker['incam']['observed_joints'] = walker['incam']['joints'].copy()
        walker['incam']['joints'][30:, 1, 1] += 0.3  # the held leg's foot (the fixture's lowest joint) reaches lower; camera y down
        walker['keypoints'][30:, :, 2] = 0.1                                   # the frame no longer shows the feet
        snap = build_sequence(self.result(walker))
        lift = np.array(snap['people'][0]['frames']['lift'])
        self.assertLess(np.abs(lift[:25]).max(), 0.02, 'the floor comes from the frames that show the feet')
        self.assertLess(np.abs(lift[35:] + 0.3).max(), 0.02, 'the figure sinks by what the held legs add, the hips stay')

    def test_floor_comes_from_planted_feet_not_feet_in_the_air(self):
        # A backflip: the feet stay in view while the body is in the air for two thirds of the clip.
        flipper = video_person()
        flipper['incam']['joints'][10:50, :, 1] -= 1.0 * np.sin(np.linspace(0, np.pi, 40))[:, None]  # camera y points down
        snap = build_sequence(self.result(flipper))
        lift = np.array(snap['people'][0]['frames']['lift'])
        self.assertLess(np.abs(np.r_[lift[:5], lift[55:]]).max(), 0.03, 'the standing figure stays on the floor')

    def test_people_share_the_floor_without_moving_in_the_image(self):
        snap = build_sequence(self.result(video_person(x=-0.6), {**video_person(x=0.6), 'start': 0}))
        a, b = (np.median(p['frames']['lift']) for p in snap['people'])
        self.assertLess(abs(a - b), 0.02)
        # Monocular depth put one person 15 cm too high: moved along the camera rays, they stand on the floor too.
        raised = video_person(x=0.6)
        raised['incam']['joints'][:, :, 1] -= 0.15  # camera y points down
        result = self.result(video_person(x=-0.6), raised)
        snap = build_sequence(result)
        for person in snap['people']:
            self.assertLess(abs(np.median(person['frames']['lift'])), 0.03, 'everyone on the one floor')
        self.assertGreater(snap['people'][1]['diagnostics']['ground_scale'], 1.03)
        camera = np.array(snap['cameras'][0]['position'])
        placed = np.c_[np.array(snap['people'][1]['frames']['transl'])[:, [0]], snap['people'][1]['frames']['hips'],
                       np.array(snap['people'][1]['frames']['transl'])[:, [2]]] - camera
        seen = np.einsum('ij,fj->fi', camera_to_world(result['people']), raised['incam']['joints'][:, 0])
        cosine = (placed * seen).sum(1) / np.linalg.norm(placed, axis=1) / np.linalg.norm(seen, axis=1)
        self.assertGreater(np.median(cosine), 0.999, 'the hips stay on their camera ray')

    def test_common_ground_needs_two_planted_people_and_a_camera_above_the_floor(self):
        floor, scales = common_ground([-1.6, -1.2, -1.4], [True, True, False])
        self.assertAlmostEqual(floor, -1.4)
        np.testing.assert_allclose(scales, [1.4 / 1.6, 1.4 / 1.2, 1.0])
        self.assertEqual(common_ground([-1.6, -1.2], [True, False])[0], -1.6, 'one planted person: the lowest floor as before')
        np.testing.assert_allclose(common_ground([-0.1, -0.4], [True, True])[1], [1, 1], err_msg='a low camera moves nobody')
        np.testing.assert_allclose(common_ground([-1.0, -3.0], [True, True])[1], [1.5, 1 / 1.5], err_msg='rescaling is bounded')
        # The editor draws 140-200 cm: a 150 cm person shrinks only to 140, a 180 cm one grows only to 200.
        limits = (np.minimum(1, 140 / np.array([150.0, 180.0])), np.maximum(1, 200 / np.array([150.0, 180.0])))
        np.testing.assert_allclose(common_ground([-1.0, -0.7], [True, True], limits)[1], [140 / 150, 200 / 180])


TRUNK_NAMES = ['Hips', 'Spine1', 'Spine2', 'Chest'] + [f'J{i}' for i in range(4, 67)] + [
    side + j for side in ('Left', 'Right') for j in ('Leg', 'Shin', 'Foot', 'ToeBase', 'ToeEnd')]


class UpperBodyTests(unittest.TestCase):
    """A person framed from the chest up stands straight under the chest (synthetic poses)."""
    trunk = [TRUNK_NAMES.index(n) - 1 for n in ('Spine1', 'Spine2', 'Chest')]   # body_pose rows exclude Hips

    def chest(self, orient, pose):
        from scipy.spatial.transform import Rotation
        out = Rotation.from_rotvec(orient)
        for j in self.trunk:
            out = out * Rotation.from_rotvec(pose[:, j])
        return out.as_matrix()

    def test_hips_seen_on_a_few_frames_is_a_chest_up_shot(self):
        conf = np.full((100, 77), 0.9)
        hips = [TRUNK_NAMES.index('LeftLeg'), TRUNK_NAMES.index('RightLeg')]
        conf[:, hips] = 0.1
        conf[:4, hips[0]] = 0.8      # a selfie dips to the waist for a moment
        self.assertTrue(upper_body_only(conf, TRUNK_NAMES))
        conf[:30, hips[1]] = 0.8     # a half-body speaker whose hips show now and then
        self.assertFalse(upper_body_only(conf, TRUNK_NAMES))

    def test_the_chest_keeps_its_turn_and_the_body_hangs_straight_below_it(self):
        frames = 48
        t = np.linspace(0, 1, frames)
        orient = np.c_[0.4 * np.sin(6 * t), 0.2 * t, np.zeros(frames)]   # the fit swings the pelvis ...
        pose = np.zeros((frames, 76, 3))
        pose[:, self.trunk, 0] = -0.5 * np.sin(6 * t)[:, None]           # ... and bends the spine back against it
        pose[:, TRUNK_NAMES.index('LeftShin') - 1, 0] = 1.2               # a guessed folded knee
        pose[:, 10, 1] = 0.3                                              # an arm or neck joint, never touched
        out_orient, out_pose = steady_trunk(orient, pose.reshape(frames, -1), TRUNK_NAMES, 24.0)
        out_pose = out_pose.reshape(frames, 76, 3)
        np.testing.assert_allclose(self.chest(out_orient, out_pose), self.chest(orient, pose), atol=1e-9)
        np.testing.assert_allclose(out_pose[:, self.trunk[0]], out_pose[:, self.trunk[2]])   # the rest in equal parts
        self.assertFalse(out_pose[:, TRUNK_NAMES.index('LeftLeg') - 1:].any())                # legs in their T-pose
        np.testing.assert_allclose(out_pose[:, 10], pose[:, 10])
        from scipy.spatial.transform import Rotation
        swing = lambda o: np.abs(np.diff(o, axis=0)).max()
        chest = Rotation.from_matrix(self.chest(orient, pose)).as_rotvec()
        self.assertLess(swing(out_orient), 0.5 * swing(chest))                             # the pelvis turns slowly

    def test_a_steady_chest_straightens_the_spine(self):
        frames = 30
        orient = np.tile([0.0, 0.0, 0.0], (frames, 1))
        pose = np.zeros((frames, 76, 3))
        pose[:, self.trunk, 0] = 0.4   # bowed 69 deg in all
        out_orient, out_pose = steady_trunk(orient, pose.reshape(frames, -1), TRUNK_NAMES, 30.0)
        np.testing.assert_allclose(out_pose.reshape(frames, 76, 3)[:, self.trunk], 0.0, atol=1e-9)
        np.testing.assert_allclose(out_orient[:, 0], 1.2, atol=1e-9)

    def test_gravity_follows_a_chest_up_persons_own_axis(self):
        level = person(tilt_deg=20)
        guessed = {**level, 'upper_body': True,   # GEM-X leaned the world 45 deg with no legs to go on
                   'global': {**level['global'], 'global_orient': np.array([math.radians(45), 0.0, 0.0])}}
        np.testing.assert_allclose(camera_to_world([guessed]), camera_to_world([level]), atol=1e-9)
        self.assertGreater(np.abs(camera_to_world([{**guessed, 'upper_body': False}]) - camera_to_world([level])).max(), 0.3)


LEG_NAMES = ['Hips'] + [f'J{i}' for i in range(1, 67)] + [side + j for side in ('Left', 'Right')
                                                          for j in ('Leg', 'Shin', 'Foot', 'ToeBase', 'ToeEnd')]


class HoldUnseenLegsTests(unittest.TestCase):
    """Leg joints whose child keypoint left the frame keep their last seen rotation (synthetic poses)."""
    knee = LEG_NAMES.index('LeftShin') - 1   # body_pose rows exclude Hips

    def clip(self, frames=60):
        pose = np.zeros((frames, 76, 3))
        pose[:, self.knee, 0] = np.linspace(0.1, 2.0, frames)   # GEM-X folds the knee as the feet leave the frame
        pose[:, 3, 1] = 0.4                                        # an arm joint, never touched
        conf = np.full((frames, 77), 0.9)
        return pose, conf

    def run_hold(self, pose, conf, outside=lambda p: np.ones((len(p), 77), bool)):
        out, held = hold_unseen_legs(pose.reshape(len(pose), -1), conf, LEG_NAMES, 30.0, outside=outside)
        return out.reshape(len(pose), 76, 3), held

    def test_cut_off_ankle_holds_the_knee_at_its_last_seen_rotation(self):
        pose, conf = self.clip()
        conf[30:, LEG_NAMES.index('LeftFoot')] = 0.1
        out, held = self.run_hold(pose, conf)
        np.testing.assert_allclose(out[:28], pose[:28], atol=1e-9)
        np.testing.assert_allclose(out[40:, self.knee], np.repeat(pose[[29], self.knee], 20, 0), atol=1e-6)
        np.testing.assert_allclose(out[:, 3], pose[:, 3], atol=1e-9)
        self.assertEqual((held[:28].max(), held[40:].min()), (0.0, 1.0))

    def test_occluded_ankle_inside_the_frame_keeps_gem(self):
        pose, conf = self.clip()
        conf[30:, LEG_NAMES.index('LeftFoot')] = 0.1
        seen = []
        out, held = self.run_hold(pose, conf, outside=lambda p: seen.append(p.copy()) or np.zeros((len(p), 77), bool))
        np.testing.assert_allclose(out, pose, atol=1e-9)
        self.assertFalse(held.any())
        candidate = seen[0].reshape(60, 76, 3)
        np.testing.assert_allclose(candidate[45, self.knee], pose[29, self.knee], atol=1e-6, err_msg='the held candidate is what gets projected')

    def test_leg_never_seen_is_straight_and_before_first_sight_uses_it(self):
        pose, conf = self.clip()
        conf[:, LEG_NAMES.index('LeftFoot')] = 0.1
        out, _ = self.run_hold(pose, conf)
        np.testing.assert_allclose(out[:, self.knee], 0.0, atol=1e-9)
        pose, conf = self.clip()
        conf[:20, LEG_NAMES.index('LeftFoot')] = 0.1
        out, _ = self.run_hold(pose, conf)
        np.testing.assert_allclose(out[:15, self.knee], np.repeat(pose[[22], self.knee], 15, 0), atol=0.2)

    def test_a_foot_guessed_below_the_frame_never_counts_as_seen(self):
        # VitPose rates a foot below the frame edge around 0.36 and now and then 0.55: above GEM-X's 0.5, but a guess.
        pose, conf = self.clip()
        conf[:, LEG_NAMES.index('LeftFoot')] = 0.36
        conf[10:22, LEG_NAMES.index('LeftFoot')] = 0.55
        out, held = self.run_hold(pose, conf)
        self.assertGreater(held.min(), 0.5)
        self.assertLess(np.abs(out[:, self.knee]).max(), 0.5 * np.abs(pose[:, self.knee]).max(),
                        'the folded GEM-X knee of the guessed frames is not held')

    def test_a_one_frame_dropout_is_ignored(self):
        pose, conf = self.clip()
        conf[30, LEG_NAMES.index('LeftFoot')] = 0.05
        out, held = self.run_hold(pose, conf)
        np.testing.assert_allclose(out, pose, atol=1e-9)
        self.assertFalse(held.any())


EVIDENCE_NAMES = (['Hips', 'LeftLeg', 'RightLeg', 'LeftArm', 'RightArm', 'LeftForeArm', 'RightForeArm', 'LeftHand', 'RightHand']
                  + ['LeftHandIndex2', 'LeftHandIndexEnd', 'LeftHandMiddle2'])


class EvidenceTargetTests(unittest.TestCase):
    """SAM 3D Body observations -> fit targets: relative, scaled, gated against VitPose, interpolated (no model)."""
    ix = {n: i for i, n in enumerate(EVIDENCE_NAMES)}

    def scene(self, rows=5):
        # Our skeleton (camera frame, metres): pelvis at 2 m depth, torso 0.5 m; VitPose sees every joint.
        ours = np.zeros((len(EVIDENCE_NAMES), 3))
        place = {'Hips': (0, 0, 2.0), 'LeftLeg': (0.1, 0, 2.0), 'RightLeg': (-0.1, 0, 2.0), 'LeftArm': (0.2, -0.5, 2.0),
                 'RightArm': (-0.2, -0.5, 2.0), 'LeftForeArm': (0.3, -0.25, 2.0), 'RightForeArm': (-0.3, -0.25, 2.0),
                 'LeftHand': (0.3, 0.0, 2.0), 'RightHand': (-0.3, 0.0, 2.0), 'LeftHandIndex2': (0.3, 0.08, 2.0),
                 'LeftHandIndexEnd': (0.3, 0.15, 2.0), 'LeftHandMiddle2': (0.32, 0.08, 2.0)}
        for n, v in place.items():
            ours[self.ix[n]] = v
        joints = np.repeat(ours[None], rows, 0)
        K = np.array([[1000.0, 0, 500], [0, 1000.0, 500], [0, 0, 1]])
        uv = joints @ K.T
        keypoints = np.concatenate([uv[..., :2] / uv[..., 2:], np.full((rows, len(EVIDENCE_NAMES), 1), 0.9)], -1)
        return joints, keypoints, K

    def observation(self, joints, K, wrist_forward=0.0, scale=2.0):
        """SAM 3D Body at twice our size and 1 m further, the left wrist `wrist_forward` m nearer than the pelvis."""
        k3d = np.zeros((70, 3))
        def put(m, name, dz=0.0):
            k3d[m] = (joints[self.ix[name]] - joints[self.ix['Hips']]) * scale + np.array([0, 0, 3.0 + dz])
        put(9, 'LeftLeg'); put(10, 'RightLeg'); put(5, 'LeftArm'); put(6, 'RightArm'); put(7, 'LeftForeArm'); put(8, 'RightForeArm')
        put(62, 'LeftHand', -wrist_forward * scale); put(41, 'RightHand')
        put(46 + 3, 'LeftHandIndex2', -wrist_forward * scale); put(46, 'LeftHandIndexEnd', -wrist_forward * scale - 0.04)
        k2d = np.zeros((70, 2))
        for name, m in evidence_mod.ARM.items():
            k2d[m] = (joints[self.ix[name]] @ K.T)[:2] / joints[self.ix[name], 2]
        for name, m in (('LeftHandIndex2', 49), ('LeftHandIndexEnd', 46)):
            k2d[m] = (joints[self.ix[name]] @ K.T)[:2] / joints[self.ix[name], 2]
        return {'k3d': k3d, 'k2d': k2d}

    def test_body_shape_is_the_median_of_enough_observations(self):
        obs = {r: {'k3d': None, 'k2d': None, 'shape': np.full(45, float(r))} for r in range(4)}
        np.testing.assert_allclose(evidence_mod.body_shape(obs), np.full(45, 1.5))
        obs[1] = None
        obs[2]['shape'] = None   # a frame without a usable shape does not count
        self.assertIsNone(evidence_mod.body_shape(obs), 'two frames are too few to replace GEM-X')

    def test_the_sequence_identity_follows_the_body_shape(self):
        person = video_person()
        self.assertEqual(build_sequence(VideoSceneTests.result(None, person))['people'][0]['identity']['coeffs'], [0.0] * 45)
        snap = build_sequence(VideoSceneTests.result(None, {**person, 'body_shape': np.full(45, 0.25)}))
        self.assertEqual(snap['people'][0]['identity']['coeffs'], [0.25] * 45)

    def targets(self, observations, keypoints=None, rows=5, keys=None):
        joints, kp, K = self.scene(rows)
        return evidence_mod.targets(observations, joints, kp if keypoints is None else keypoints, np.full(rows, 600.0),
                                    EVIDENCE_NAMES, np.arange(rows) * 2 if keys is None else keys, 24.0)

    def test_depth_is_relative_to_the_hips_and_scaled_to_our_body(self):
        joints, kp, K = self.scene()
        t = self.targets({0: self.observation(joints[0], K, wrist_forward=0.1)})
        wrist = self.ix['LeftHand']
        self.assertAlmostEqual(t['depth'][0, wrist], -0.1, places=6, msg='0.2 m in SAM at twice the size is 0.1 m here')
        self.assertAlmostEqual(t['depth'][0, self.ix['LeftArm']], 0.0, places=6)
        self.assertEqual(t['depth_mask'][0, self.ix['Hips']], 0.0, 'only arm joints get depth evidence')
        np.testing.assert_allclose(t['shape'][0, self.ix['LeftHandIndexEnd']], [0, 0.15, -0.02], atol=1e-6)
        self.assertEqual(t['shape_base'][self.ix['LeftHandIndexEnd']], wrist)

    def test_unseen_or_misplaced_joints_get_no_target(self):
        joints, kp, K = self.scene()
        unsure = kp.copy(); unsure[0, self.ix['LeftForeArm'], 2] = 0.3
        t = self.targets({0: self.observation(joints[0], K)}, unsure)
        self.assertEqual(t['depth_mask'][0, self.ix['LeftForeArm']], 0.0, 'VitPose does not see it')
        obs = self.observation(joints[0], K); obs['k2d'][7] += [120, 0]   # 20 % of the 600 px box away
        t = self.targets({0: obs})
        self.assertEqual(t['depth_mask'][0, self.ix['LeftForeArm']], 0.0, 'SAM 3D Body puts it elsewhere')
        self.assertEqual(t['depth_mask'][0, self.ix['LeftHand']], 1.0)
        turned = self.observation(joints[0], K); turned['k2d'][46] += [0, -140]   # fingertip pointing the other way
        t = self.targets({0: turned})
        self.assertEqual(t['shape_mask'][0, self.ix['LeftHandIndexEnd']], 0.0, 'a different hand shape keeps VitPose')
        self.assertEqual(t['depth_mask'][0, self.ix['LeftHand']], 1.0, 'the wrist depth still counts')

    def test_evidence_is_interpolated_only_across_short_gaps(self):
        joints, kp, K = self.scene(rows=12)
        near, far = self.observation(joints[0], K, 0.0), self.observation(joints[0], K, 0.2)
        t = self.targets({0: near, 4: far}, rows=12)    # keys 0 and 8: a third of a second apart at 24 fps
        wrist = self.ix['LeftHand']
        np.testing.assert_allclose(t['depth'][:5, wrist], [0, -0.05, -0.1, -0.15, -0.2], atol=1e-6)
        self.assertTrue(t['depth_mask'][:5, wrist].all())
        t = self.targets({0: near, 11: far}, rows=12, keys=np.arange(12) * 3)   # 33 frames apart: too far
        self.assertFalse(t['depth_mask'][1:11, wrist].any())
        self.assertGreater(t['used']['depth'], 0)


class SmoothMotionTests(unittest.TestCase):
    """Keyframe keypoints are smoothed by speed and joined by smooth curves (the 12 Hz shimmer of a 24 fps clip)."""
    keys = np.arange(0, 96, 2)
    fps = 24.0

    def track(self, motion):
        t = self.keys / self.fps
        kp = np.zeros((len(self.keys), 1, 3)); kp[..., 2] = 0.9
        kp[:, 0, 0] = motion(t)
        return kp

    def test_steady_motion_keeps_its_speed_and_still_joints_lose_their_noise(self):
        sizes = np.full(len(self.keys), 500.0)
        fast = self.track(lambda t: 100 + 1500 * t)          # three person boxes a second
        np.testing.assert_allclose(smooth_keypoints(fast, self.keys, self.fps, sizes)[:, 0, 0], fast[:, 0, 0], atol=1e-6)
        rng = np.random.default_rng(1)
        still = self.track(lambda t: 300 + 0 * t)
        noisy = still.copy(); noisy[..., :2] += rng.normal(0, 4, noisy[..., :2].shape)
        smoothed = smooth_keypoints(noisy, self.keys, self.fps, sizes)
        self.assertLess(np.abs(np.diff(smoothed[:, 0, 0], 2)).mean(), np.abs(np.diff(noisy[:, 0, 0], 2)).mean() / 3)
        np.testing.assert_allclose(smoothed[..., 2], noisy[..., 2], err_msg='confidences are untouched')

    def test_fast_joints_are_smoothed_less_than_still_ones(self):
        sizes = np.full(len(self.keys), 500.0)
        rng = np.random.default_rng(2)
        noise = rng.normal(0, 4, (len(self.keys),))
        swing = self.track(lambda t: 300 + 400 * np.sin(2 * np.pi * 1.5 * t))   # a fast arm swing
        swing[:, 0, 0] += noise
        clean = 300 + 400 * np.sin(2 * np.pi * 1.5 * self.keys / self.fps)
        adaptive = smooth_keypoints(swing, self.keys, self.fps, sizes)
        fixed = smooth_keypoints(swing, self.keys, self.fps, sizes, speed=1e9)  # the same width whatever the speed
        self.assertLess(np.abs(adaptive[:, 0, 0] - clean).mean(), np.abs(fixed[:, 0, 0] - clean).mean())

    def test_corrections_are_smoothed_in_still_moments_only(self):
        rng = np.random.default_rng(3)
        t = self.keys / self.fps
        trend = np.stack([0.1 + 0.05 * t, -0.2 * t], 1)               # a slowly changing correction
        np.testing.assert_allclose(smooth_series(trend, self.keys, self.fps, 0.15), trend, atol=1e-9)
        noisy = trend + rng.normal(0, 0.02, trend.shape)
        smoothed = smooth_series(noisy, self.keys, self.fps, 0.15)
        self.assertLess(np.abs(smoothed - trend).mean(), np.abs(noisy - trend).mean() / 2)
        widths = np.where(np.arange(len(self.keys)) < 24, 0.15, 1e-4)  # the second half moves fast: left alone
        mixed = smooth_series(noisy, self.keys, self.fps, widths)
        np.testing.assert_allclose(mixed[30:], noisy[30:], atol=1e-6)
        self.assertLess(np.abs(mixed[:20] - trend[:20]).mean(), np.abs(noisy[:20] - trend[:20]).mean() / 2)
        still = self.track(lambda t: 300 + 0 * t); moving = self.track(lambda t: 300 + 1000 * t)
        sizes = np.full(len(self.keys), 500.0)
        self.assertLess(frame_speed(still, self.keys, self.fps, sizes).max(), 1e-9)
        np.testing.assert_allclose(frame_speed(moving, self.keys, self.fps, sizes)[2:-2], 2.0, atol=1e-6)

    def test_interpolation_is_smooth_through_the_keyframes(self):
        values = np.array([[0.0], [10.0], [10.0], [0.0]])
        out = interpolate_rows(values, np.array([2, 4, 6, 8]), 11)
        np.testing.assert_allclose(out[[2, 4, 6, 8], 0], values[:, 0])
        self.assertTrue((out <= 10 + 1e-9).all() and (out >= -1e-9).all(), 'no overshoot')
        np.testing.assert_allclose(out[:2, 0], 0.0, err_msg='the ends hold the first / last keyframe')
        q = np.tile([0.0, 0.0, 0.0, 1.0], (3, 1, 1))
        q[1, 0] = [0, 0, np.sin(0.3), np.cos(0.3)]
        q[2, 0] = -np.array([0, 0, np.sin(0.6), np.cos(0.6)])   # the same rotation on the other hemisphere
        out = interpolate_quats(q, np.array([0, 2, 4]), 5)
        np.testing.assert_allclose(np.linalg.norm(out, axis=-1), 1.0)
        angle = 2 * np.arccos(np.clip(np.abs(out[:, 0, 3]), 0, 1))
        self.assertTrue(np.all(np.diff(angle) > 0), 'turns steadily instead of flipping the long way round')


class KeepEvidenceTests(unittest.TestCase):
    def test_evidence_never_trades_2d_accuracy(self):
        plain = np.array([1.0, 1.0, 1.0, 1.0])
        evidence = np.array([0.9, 1.08, 1.2, 0.5])
        targeted = np.array([True, True, True, False])
        self.assertEqual(keep_evidence(plain, evidence, targeted).tolist(), [True, True, False, False],
                         'better or within the slack keeps the evidence; worse, or no targets, keeps the plain fit')
        self.assertEqual(keep_evidence(plain, evidence, targeted, slack=1.0).tolist(), [True, False, False, False])


class DropoutTests(unittest.TestCase):
    """Short VitPose confidence dropouts at keyframes are bridged; open-ended ones (out of frame) are not."""
    def keyframes(self, conf):
        kp = np.zeros((len(conf), 2, 3))
        kp[:, 0, 0] = np.arange(len(conf)) * 10.0   # joint 0 moves 10 px per keyframe
        kp[:, 0, 1] = 100.0
        kp[:, 0, 2] = conf
        kp[:, 1, 2] = 0.9
        return kp

    def test_a_short_dropout_seen_on_both_sides_is_bridged(self):
        conf = [0.9, 0.9, 0.3, 0.2, 0.4, 0.9, 0.9]
        kp = self.keyframes(conf)
        kp[2:5, 0, :2] = [[600, 900], [5, 5], [300, 20]]  # what VitPose guessed while unsure
        out = fill_dropouts(kp, np.arange(7) * 2, 24.0)
        np.testing.assert_allclose(out[2:5, 0, :2], [[20, 100], [30, 100], [40, 100]])
        np.testing.assert_allclose(out[2:5, 0, 2], 0.55)
        np.testing.assert_allclose(out[[0, 1, 5, 6]], kp[[0, 1, 5, 6]])
        np.testing.assert_allclose(out[:, 1], kp[:, 1])
        self.assertIsNot(out, kp)

    def test_long_or_open_ended_dropouts_are_left_alone(self):
        long_gap = self.keyframes([0.9] + [0.2] * 14 + [0.9])        # 30 frames at 24 fps: longer than a second
        np.testing.assert_allclose(fill_dropouts(long_gap, np.arange(16) * 2, 24.0), long_gap)
        left_frame = self.keyframes([0.9, 0.9, 0.2, 0.1, 0.1])        # the foot never comes back
        np.testing.assert_allclose(fill_dropouts(left_frame, np.arange(5) * 2, 24.0), left_frame)


class TrackTests(unittest.TestCase):
    def test_broken_tracks_of_one_person_are_stitched(self):
        box = lambda x: np.array([x, 100, x + 80, 300.0])
        observed = {1: {i: box(100 + i) for i in range(0, 40)}, 2: {i: box(100 + i) for i in range(48, 90)},
                    3: {i: box(500) for i in range(50, 60)}}
        merged = stitch(observed, 90, 30.0)
        self.assertEqual(sorted(len(v) for v in merged.values()), [10, 82])
        far = {1: {i: box(100) for i in range(0, 40)}, 2: {i: box(400) for i in range(45, 90)}}
        self.assertEqual(len(stitch(far, 90, 30.0)), 2, 'a different place is a different person')
        late = {1: {i: box(100) for i in range(0, 20)}, 2: {i: box(100) for i in range(70, 90)}}
        self.assertEqual(len(stitch(late, 90, 30.0)), 2, 'gaps longer than a second are not bridged')
        # ByteTrack took a new id before the old one expired: overlapping frames, near-identical boxes.
        relay = {1: {i: box(100 + i) for i in range(0, 80)}, 2: {i: box(102 + i) for i in range(75, 90)}}
        self.assertEqual([len(v) for v in stitch(relay, 90, 30.0).values()], [90])
        wide = lambda x: np.array([x - 4, 98, x + 146, 300.0])  # same dancer, arms spread: IoU ~0.53, contained
        spread = {1: {i: box(100) for i in range(0, 80)}, 2: {i: wide(100) for i in range(77, 90)}}
        self.assertEqual(len(stitch(spread, 90, 30.0)), 1)
        partners = {1: {i: box(100) for i in range(0, 90)}, 2: {i: box(150) for i in range(0, 90)}}
        self.assertEqual(len(stitch(partners, 90, 30.0)), 2, 'a dance partner beside you is someone else')

    def test_far_background_figures_are_left_out(self):
        # A runner 480 px tall, two pedestrians far down the path (60 px) and a passer-by at a quarter of her height.
        def person(x, top, height):
            return {i: np.array([x, top, x + height * 0.4, top + height]) for i in range(60)}
        observed = {1: person(500, 150, 480), 2: person(760, 400, 60), 3: person(780, 400, 62), 4: person(100, 300, 120)}
        chosen = select_tracks(observed, people=4, length=60, fps=25.0)
        self.assertEqual(sorted(round(float(t['boxes'][0, 3] - t['boxes'][0, 1])) for t in chosen), [120, 480])

    def test_a_dancer_entering_elsewhere_is_not_the_one_who_left(self):
        # Tall standing boxes: one dancer leaves on the left, another enters 270 px to the right 22 frames later.
        tall = lambda x: np.array([x, 100, x + 130, 640.0])
        swap = {1: {i: tall(10) for i in range(0, 144)}, 2: {i: tall(280) for i in range(166, 216)}}
        self.assertEqual(len(stitch(swap, 216, 25.0)), 2)
        moving = {1: {i: tall(10 + 6 * i) for i in range(0, 60)}, 2: {i: tall(10 + 6 * i) for i in range(80, 120)}}
        self.assertEqual(len(stitch(moving, 120, 25.0)), 1, 'one moving on at its speed across the gap is the same')

    def test_a_flip_changes_the_box_shape_not_the_person(self):
        # Mid-flip the body lies sideways (short wide box); 10 frames later it stands (tall box), moving right.
        lying = {i: np.array([8 * i, 400, 8 * i + 280, 590.0]) for i in range(5, 21)}
        standing = {i: np.array([8 * i, 200, 8 * i + 300, 645.0]) for i in range(30, 60)}
        self.assertEqual(len(stitch({1: lying, 2: standing}, 60, 25.0)), 1)

    def test_a_shorter_box_inside_is_someone_behind_not_a_relay(self):
        front = {i: np.array([100, 100, 260, 850.0]) for i in range(0, 80)}
        behind = {i: np.array([120, 150, 220, 480.0]) for i in range(76, 90)}
        self.assertEqual(len(stitch({1: front, 2: behind}, 90, 25.0)), 2)

    def test_tracks_no_keypoint_can_see_are_dropped(self):
        names = ['Hips', 'LeftArm', 'LeftHandIndex1', 'LeftHandIndexEnd']
        seen, speck, blurry = (np.full((5, 4, 3), c) for c in (0.9, 0.03, 0.5))
        speck[:, 2:, 2] = 0.9   # fingers and end joints do not count either way
        blurry[:, 2:, 2] = 0.0
        tracks, keyed = trusted_tracks([{'id': 'a'}, {'id': 'b'}, {'id': 'c'}], {0: seen, 1: speck, 2: blurry}, names)
        self.assertEqual([t['id'] for t in tracks], ['a', 'c'])
        self.assertIs(keyed[1], blurry)

    def test_selection_drops_short_tracks_and_limits_people(self):
        box = lambda x, w: np.array([x, 0, x + w, 2 * w])
        observed = {1: {i: box(0, 100) for i in range(0, 90, 5)}, 2: {i: box(300, 60) for i in range(0, 90, 5)},
                    3: {i: box(600, 200) for i in range(0, 20)}}
        tracks = select_tracks(observed, 2, 90, 30.0)
        self.assertEqual([t['start'] for t in tracks], [0, 0])
        self.assertEqual([len(t['boxes']) for t in tracks], [86, 86])
        self.assertGreater(tracks[0]['boxes'][0, 2] - tracks[0]['boxes'][0, 0], tracks[1]['boxes'][0, 2] - tracks[1]['boxes'][0, 0])
        np.testing.assert_allclose(tracks[0]['boxes'][2], box(0, 100))  # interpolated between detections


class BodyTests(unittest.TestCase):
    def test_id_ignores_global_scale_and_tracks_shape(self):
        coeffs, scales = np.linspace(-1, 1, 45), np.r_[0.9, np.linspace(0, 0.2, 68)]
        ident = body_id(coeffs, scales)
        self.assertRegex(ident, '^[0-9a-f]{32}$')
        self.assertEqual(body_id(coeffs, np.r_[0.7, scales[1:]]), ident)  # overall size is height_cm
        self.assertEqual(body_id(coeffs + 1e-6, scales), ident)  # rounding absorbs float noise
        self.assertNotEqual(body_id(coeffs + 0.01, scales), ident)

    def test_store_validates_ids_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            store = BodyStore(Path(temp) / 'bodies')
            with self.assertRaises(FileNotFoundError): store.path('a' * 32)
            store.write('a' * 32, b'glTF')
            self.assertEqual(store.path('a' * 32).read_bytes(), b'glTF')
            for bad in ('../x', 'A' * 32, ''):
                with self.assertRaises(ValueError): store.path(bad)
            store.target('b' * 32).symlink_to(store.path('a' * 32))
            with self.assertRaises(FileNotFoundError): store.path('b' * 32)

    def test_snapshot_carries_body_id(self):
        snap = build_snapshot({'width': 640, 'height': 480, 'people': [{**person(), 'body_id': 'c' * 32}, person(x=1)]})
        self.assertEqual([p.get('body_id') for p in snap['people']], ['c' * 32, None])


class RuntimeStatusTests(unittest.TestCase):
    def test_states(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Runtime(temp)
            self.assertEqual(runtime.status()['state'], 'missing')
            Path(temp, 'installed.json').write_text(json.dumps({'engine': 'old', 'commit': 'x'}))
            self.assertEqual(runtime.status()['state'], 'outdated')
            self.assertNotIn(temp, json.dumps(runtime.status()))
            self.assertIs(runtime.status()['modes']['evidence'], False)
            self.assertTrue(runtime.status()['evidence_message'])


class RouteTests(unittest.TestCase):
    def test_auth_and_unknown_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            service = PoseCaptureService(Path(temp), FakeRuntime())
            router = create_router(service)

            class Handler:
                path = '/api/pose_capture/submit'
                headers = {'Content-Length': '2'}
                rfile = io.BytesIO(b'{}')
                def require_auth(self): return False
                def send_json(self, *args): raise AssertionError('unauthenticated dispatch')
            self.assertTrue(router.dispatch(Handler(), 'POST', Handler.path))
            self.assertFalse(router.dispatch(Handler(), 'POST', '/api/pose_capture/install'))
            self.assertFalse(router.dispatch(Handler(), 'GET', '/api/pose_capture/upload'))
            service.close()

    def test_body_route_serves_glb_and_rejects_bad_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            service = PoseCaptureService(Path(temp), FakeRuntime())
            self.addCleanup(service.close)
            service.bodies.write('d' * 32, b'glTF-body')
            router = create_router(service)
            sent = []

            class Handler:
                headers = {}
                def __init__(self, path): self.path = path
                def require_auth(self): return True
                def send_json(self, payload, status=200): sent.append((status, payload))
            with mock.patch('backend.routes.pose_capture_routes.send_artifact', lambda h, path, kind: sent.append((200, path.name, kind))):
                router.dispatch(Handler('/api/pose_capture/body?id=' + 'd' * 32), 'GET', '/api/pose_capture/body')
                router.dispatch(Handler('/api/pose_capture/body?id=../x'), 'GET', '/api/pose_capture/body')
                router.dispatch(Handler('/api/pose_capture/body?id=' + 'e' * 32), 'GET', '/api/pose_capture/body')
            self.assertEqual(sent[0], (200, 'd' * 32 + '.glb', 'model/gltf-binary'))
            self.assertEqual([s[0] for s in sent[1:]], [400, 404])


if __name__ == '__main__':
    unittest.main()
