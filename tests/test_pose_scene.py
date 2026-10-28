"""Portable pose-scene tests: GLB writer, export contract, service status and HTTP adapter.

Synthetic rigs only; no SOMA assets, torch or network required.
"""
import base64
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import time
import unittest
import zlib

import numpy as np

from backend.pose_scene.contracts import BODIES, GLB_VERSION, SOMA_RELEASE, glb_name, normalize_export, png_size
from backend.pose_scene.glb import build_glb, quat_xyzw, read_glb
from backend.pose_scene.convert import rest_height
from backend.pose_scene.service import PoseSceneService
from backend.pose_scene.video_export import ffmpeg
from backend.routes.pose_routes import create_router


def png(width=4, height=3):
    raw = b''.join(b'\0' + b'\x10\x20\x30' * width for _ in range(height))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def rgba(width, height, shade=0):
    return zlib.compress(bytes([40 * shade, 80, 120, 255]) * (width * height))


def data_url(data):
    return 'data:image/png;base64,' + base64.b64encode(data).decode()


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def synthetic_rig():
    """Root -> Hips -> Spine, a 4-vertex strip skinned to Hips and Spine."""
    bind = np.tile(np.eye(4), (3, 1, 1))
    bind[1][:3, 3] = [0, 0.9, 0]
    bind[2][:3, :3] = rot_z(30)
    bind[2][:3, 3] = [0, 1.2, 0]
    weights = np.array([[0, 1, 0], [0, 0.75, 0.25], [0, 0.2, 0.8], [0, 0, 1.0]])
    return {'names': ['Root', 'Hips', 'Spine'], 'parents': np.array([-1, 0, 1]), 'bind_world': bind,
            'orient': np.stack([np.eye(3), np.eye(3), rot_z(30)]),
            'rest': np.array([[0, 0.9, 0], [0.1, 1.0, 0], [-0.1, 1.1, 0], [0, 1.3, 0.05]]),
            'faces': np.array([[0, 1, 2], [1, 3, 2]]), 'weights': weights, 'glb_version': GLB_VERSION, 'release': SOMA_RELEASE, 'lod': 'low'}


def accessor(document, binary, index):
    acc = document['accessors'][index]
    view = document['bufferViews'][acc['bufferView']]
    dtype = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}[acc['componentType']]
    width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[acc['type']]
    return np.frombuffer(binary, dtype, acc['count'] * width, view['byteOffset']).reshape(acc['count'], width)


def quat_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


class GlbWriterTests(unittest.TestCase):
    def test_quaternion_round_trip_covers_every_branch(self):
        rng = np.random.default_rng(3)
        cases = [np.eye(3), rot_z(179.9), np.diag([1, -1, -1.0]), np.diag([-1, 1, -1.0]), np.diag([-1, -1, 1.0])]
        for _ in range(50):
            a, _ = np.linalg.qr(rng.normal(size=(3, 3)))
            cases.append(a * np.sign(np.linalg.det(a)))
        for matrix in cases:
            q = quat_xyzw(matrix)
            self.assertAlmostEqual(float(np.linalg.norm(q)), 1.0, places=12)
            self.assertLess(np.abs(quat_matrix(q) - matrix).max(), 1e-9)

    def test_rest_pose_skinning_reproduces_rest_vertices(self):
        rig = synthetic_rig()
        document, binary = read_glb(build_glb(rig))
        primitive = document['meshes'][0]['primitives'][0]['attributes']
        positions = accessor(document, binary, primitive['POSITION']).astype(float)
        joints = accessor(document, binary, primitive['JOINTS_0']).astype(int)
        weights = accessor(document, binary, primitive['WEIGHTS_0']).astype(float)
        inverse = accessor(document, binary, document['skins'][0]['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
        world = []
        for j, node in enumerate(document['nodes'][:3]):
            local = np.eye(4); local[:3, :3] = quat_matrix(node['rotation']); local[:3, 3] = node['translation']
            parent = rig['parents'][j]
            world.append(local if parent < 0 else world[parent] @ local)
        skin = np.stack(world) @ inverse
        homogeneous = np.c_[positions, np.ones(len(positions))]
        posed = sum(weights[:, k:k + 1] * np.einsum('vab,vb->va', skin[joints[:, k]], homogeneous)[:, :3] for k in range(4))
        self.assertLess(np.abs(posed - rig['rest']).max(), 1e-6)
        np.testing.assert_allclose(weights.sum(axis=1), 1, atol=1e-6)

    def test_editor_metadata_and_hierarchy(self):
        document, _ = read_glb(build_glb(synthetic_rig()))
        soma = document['scenes'][0]['extras']['soma']
        self.assertEqual(soma['joint_names'], ['Root', 'Hips', 'Spine'])
        self.assertEqual(soma['parents'], [-1, 0, 1])
        self.assertEqual(soma['hips_translation'], [0, 0.9, 0])
        self.assertEqual((soma['glb_version'], soma['release']), (GLB_VERSION, SOMA_RELEASE))
        np.testing.assert_allclose(quat_matrix(soma['orient_xyzw'][2]), rot_z(30), atol=1e-12)
        self.assertEqual(document['nodes'][0]['children'], [1])
        self.assertEqual(document['skins'][0]['joints'], [0, 1, 2])
        self.assertEqual((soma['body'], soma['height_ratio']), ('neutral', 1.0))
        document, _ = read_glb(build_glb({**synthetic_rig(), 'body': 'female', 'head_end': 1.6, 'height_ratio': 0.95}))
        soma = document['scenes'][0]['extras']['soma']
        self.assertEqual((soma['body'], soma['head_end'], soma['height_ratio']), ('female', 1.6, 0.95))

    def test_rest_height_skips_the_virtual_root(self):
        bind = np.tile(np.eye(4), (4, 1, 1))
        bind[1:, 1, 3] = [0.9, 0.05, 1.7]  # Hips, a toe, HeadEnd; the Root stays at y = 0 below the toe
        self.assertAlmostEqual(rest_height({'names': ['Root', 'Hips', 'LeftToeEnd', 'HeadEnd'], 'bind_world': bind}), 1.65)

    def test_invalid_rigs_are_rejected(self):
        for change in ({'names': ['Root', 'Pelvis', 'Spine']}, {'parents': np.array([-1, 2, 1])},
                       {'faces': np.array([[0, 1, 9]])}, {'weights': np.zeros((4, 3))}):
            with self.assertRaises(ValueError):
                build_glb({**synthetic_rig(), **change})

    def test_read_glb_rejects_other_files(self):
        with self.assertRaises(ValueError): read_glb(b'glTF' + b'\0' * 16)


class ExportContractTests(unittest.TestCase):
    def test_png_size_and_rejections(self):
        self.assertEqual(png_size(png(7, 5)), (7, 5))
        with self.assertRaises(ValueError): png_size(b'\xff\xd8\xff' + b'\0' * 40)
        with self.assertRaises(ValueError): png_size(png(5000, 4))

    def test_normalize_export(self):
        spec = normalize_export({'image': data_url(png()), 'pass': 'openpose', 'camera': '机位 1', 'scene': {'people': []}})
        self.assertEqual((spec['width'], spec['height'], spec['pass']), (4, 3, 'openpose'))
        for body in ({'image': data_url(png()), 'pass': 'sketch'}, {'image': 'data:image/jpeg;base64,AAAA', 'pass': 'mask'},
                     {'image': data_url(png()), 'pass': 'mask', 'path': '/etc/passwd'}, {'image': 'data:image/png;base64,@@', 'pass': 'mask'},
                     {'image': data_url(png()), 'pass': 'mask', 'scene': {'blob': 'x' * 300000}}):
            with self.assertRaises(ValueError): normalize_export(body)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.component = root / 'components' / 'pose-soma'
        self.service = PoseSceneService(self.component, root / 'data' / 'pose')

    def tearDown(self):
        self.temp.cleanup()

    def install(self, **receipt):
        (self.component / 'glb').mkdir(parents=True, exist_ok=True)
        for level in ('low', 'mid'):
            for kind in BODIES:
                (self.component / 'glb' / glb_name(level, kind)).write_bytes(build_glb(synthetic_rig()))
        (self.component / 'installed.json').write_text(json.dumps({'release': SOMA_RELEASE, 'glb_version': GLB_VERSION,
                                                                   'lods': {'low': {'vertices': 4}, 'mid': {'vertices': 4}}, **receipt}))

    def test_status_states_and_no_paths(self):
        self.assertEqual(self.service.status()['state'], 'missing')
        with self.assertRaises(RuntimeError): self.service.glb('low')
        self.install(glb_version=GLB_VERSION - 1)
        self.assertEqual(self.service.status()['state'], 'outdated')
        self.install()
        (self.component / 'glb' / glb_name('mid', 'female')).unlink()
        self.assertEqual(self.service.status()['state'], 'incomplete')
        self.install()
        status = self.service.status()
        self.assertTrue(status['ready'])
        self.assertEqual(status['lods']['low']['vertices'], 4)
        self.assertNotIn(self.temp.name, json.dumps(status))
        self.assertEqual(self.service.glb('mid').name, 'soma_neutral_mid.glb')
        self.assertEqual(self.service.glb('low', 'female').name, 'soma_female_low.glb')
        self.assertEqual([b['id'] for b in status['bodies']], ['neutral', 'female', 'male'])
        with self.assertRaises(ValueError): self.service.glb('high')
        with self.assertRaises(ValueError): self.service.glb('low', '../neutral')

    def test_symlinked_glb_is_refused(self):
        self.install()
        target = self.component / 'glb' / glb_name('low')
        target.unlink(); target.symlink_to(self.component / 'installed.json')
        with self.assertRaises(FileNotFoundError): self.service.glb('low')

    def test_export_round_trip_keeps_sidecar(self):
        saved = self.service.save_export({'image': data_url(png(8, 6)), 'pass': 'depth', 'camera': '机位 2', 'scene': {'people': [{'id': 'p1'}]}})
        self.assertEqual(saved['url'], '/api/pose/export/artifact?id=' + saved['id'])
        path = self.service.export_path(saved['id'])
        self.assertEqual(path.read_bytes(), png(8, 6))
        meta = json.loads(path.with_suffix('.json').read_text())
        self.assertEqual((meta['pass'], meta['width'], meta['height'], meta['scene']['people'][0]['id']), ('depth', 8, 6, 'p1'))
        with self.assertRaises(ValueError): self.service.export_path('../../etc')
        with self.assertRaises(FileNotFoundError): self.service.export_path('0' * 32)


HAS_FFMPEG = bool(ffmpeg())


class VideoExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.archive = root / 'archive' / '2026-10-21'
        self.service = PoseSceneService(root / 'c', root / 'd', output_dir=lambda: self.archive)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, **change):
        return self.service.video('start', {'frames': 3, 'fps': 30, 'width': 16, 'height': 16, 'format': 'rgba', 'pass': 'openpose',
                                            'camera': '视频机位', 'scene': {'people': []}, **change})

    def test_start_validation(self):
        for bad in ({'frames': 1}, {'frames': 5000}, {'width': 15}, {'height': 9000}, {'fps': 0}, {'format': 'gif'},
                    {'pass': 'sketch'}, {'frames': True}, {'path': '/etc'}):
            with self.assertRaises(ValueError, msg=bad): self.start(**bad)
        self.assertIsNone(PoseSceneService(Path(self.temp.name) / 'x', Path(self.temp.name) / 'y').videos)

    def test_frames_arrive_in_order_with_matching_size(self):
        job = self.start(format='png')
        with self.assertRaisesRegex(ValueError, '顺序'): self.service.video('frame', ident=job['id'], index=1, data=png(16, 16))
        with self.assertRaisesRegex(ValueError, '尺寸'): self.service.video('frame', ident=job['id'], index=0, data=png(8, 8))
        with self.assertRaises(ValueError): self.service.video('frame', ident=job['id'], index=0, data=b'\xff\xd8not-a-png')
        self.assertEqual(self.service.video('frame', ident=job['id'], index=0, data=png(16, 16))['received'], 1)
        with self.assertRaisesRegex(ValueError, '还缺'): self.service.video('finish', ident=job['id'])
        cancelled = self.service.video('cancel', ident=job['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        with self.assertRaises(ValueError): self.service.video('frame', ident=job['id'], index=1, data=png(16, 16))
        with self.assertRaises(ValueError): self.service.video('job', ident='../x')

    def test_raw_frames_are_inflated_with_a_size_cap(self):
        job = self.start()
        with self.assertRaisesRegex(ValueError, '尺寸'): self.service.video('frame', ident=job['id'], index=0, data=zlib.compress(bytes(16 * 16 * 3)))
        with self.assertRaisesRegex(ValueError, '尺寸'): self.service.video('frame', ident=job['id'], index=0, data=zlib.compress(bytes(10 ** 7)))
        with self.assertRaisesRegex(ValueError, '解压'): self.service.video('frame', ident=job['id'], index=0, data=b'not zlib')
        self.assertEqual(self.service.video('frame', ident=job['id'], index=0, data=rgba(16, 16))['received'], 1)

    @unittest.skipUnless(HAS_FFMPEG, 'ffmpeg not installed')
    def test_encode_lands_in_the_archive_with_a_sidecar(self):
        job = self.start()
        for index in range(3):
            self.service.video('frame', ident=job['id'], index=index, data=rgba(16, 16, index))
        self.service.video('finish', ident=job['id'])
        for _ in range(300):
            current = self.service.video('job', ident=job['id'])
            if current['status'] not in ('encoding', 'receiving'):
                break
            time.sleep(0.05)
        self.assertEqual(current['status'], 'succeeded', current)
        name = current['url'].removeprefix('/video/')
        video = self.archive / name
        self.assertTrue(name.startswith('pose_openpose_') and video.is_file() and video.stat().st_size > 0)
        sidecar = json.loads(video.with_suffix('.json').read_text())
        self.assertEqual((sidecar['kind'], sidecar['frames'], sidecar['fps'], sidecar['camera']), ('pose_video', 3, 30.0, '视频机位'))
        self.assertFalse((Path(self.temp.name) / 'd' / 'videos' / job['id'] / 'frames').exists(), 'frames are removed')


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = PoseSceneService(Path(self.temp.name) / 'c', Path(self.temp.name) / 'd')
        self.router = create_router(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def handler(self, path, body=b'', authed=True):
        test = self

        class Handler:
            headers = {'Content-Length': str(len(body))}
            rfile = io.BytesIO(body)
            sent = []
            def __init__(self): self.path = path
            def require_auth(self): return authed
            def send_json(self, payload, status=200, *_): self.sent.append((status, payload))
        Handler.test = test
        return Handler()

    def test_requires_auth_and_ignores_unknown_routes(self):
        handler = self.handler('/api/pose/assets/status', authed=False)
        self.assertTrue(self.router.dispatch(handler, 'GET', '/api/pose/assets/status'))
        self.assertEqual(handler.sent, [])
        self.assertFalse(self.router.dispatch(handler, 'GET', '/api/pose/unknown'))
        self.assertFalse(self.router.dispatch(handler, 'GET', '/api/pose/export/image'))

    def test_status_missing_glb_and_export(self):
        handler = self.handler('/api/pose/assets/status')
        self.router.dispatch(handler, 'GET', '/api/pose/assets/status')
        self.assertEqual(handler.sent[-1][1]['state'], 'missing')
        handler = self.handler('/api/pose/glb?lod=low')
        self.router.dispatch(handler, 'GET', '/api/pose/glb')
        self.assertEqual(handler.sent[-1][0], 503)
        body = json.dumps({'image': data_url(png()), 'pass': 'mask'}).encode()
        handler = self.handler('/api/pose/export/image', body)
        self.router.dispatch(handler, 'POST', '/api/pose/export/image')
        status, payload = handler.sent[-1]
        self.assertEqual((status, payload['pass'], payload['width']), (200, 'mask', 4))
        handler = self.handler('/api/pose/export/image', b'[]')
        self.router.dispatch(handler, 'POST', '/api/pose/export/image')
        self.assertEqual(handler.sent[-1][0], 400)

    def test_video_routes_need_an_archive(self):
        body = json.dumps({'frames': 2, 'fps': 24, 'width': 16, 'height': 16, 'pass': 'mask'}).encode()
        handler = self.handler('/api/pose/export/video/start', body)
        self.router.dispatch(handler, 'POST', '/api/pose/export/video/start')
        self.assertEqual(handler.sent[-1][0], 503, 'video export is off without an archive folder')
        service = PoseSceneService(Path(self.temp.name) / 'c', Path(self.temp.name) / 'd2', output_dir=lambda: Path(self.temp.name) / 'a')
        router = create_router(service)
        handler = self.handler('/api/pose/export/video/start', body)
        router.dispatch(handler, 'POST', '/api/pose/export/video/start')
        status, job = handler.sent[-1]
        if not HAS_FFMPEG:
            self.assertEqual(status, 503)
            return
        self.assertEqual((status, job['status']), (200, 'receiving'))
        handler = self.handler(f'/api/pose/export/video/frame?id={job["id"]}&index=0', rgba(16, 16))
        router.dispatch(handler, 'POST', '/api/pose/export/video/frame')
        self.assertEqual(handler.sent[-1][1]['received'], 1)
        handler = self.handler(f'/api/pose/export/video/frame?id={job["id"]}&index=x', rgba(16, 16))
        router.dispatch(handler, 'POST', '/api/pose/export/video/frame')
        self.assertEqual(handler.sent[-1][0], 400)
        handler = self.handler(f'/api/pose/export/video/job?id={job["id"]}')
        router.dispatch(handler, 'GET', '/api/pose/export/video/job')
        self.assertEqual(handler.sent[-1][1]['received'], 1)


if __name__ == '__main__':
    unittest.main()
