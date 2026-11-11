"""Video-edit domain: exact frames, scene candidates, audio separation and the HTTP contract.

Synthetic fixtures only: clips are rendered by the local FFmpeg into a temp directory, and the
archive, stores and sidecar writer are fakes. FFmpeg-dependent cases skip without FFmpeg.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from backend import asset_index
from backend.routes.video_edit_routes import create_router
from backend.services.archive_audio import AudioArchive
from backend.video_edit import contracts, media
from backend.video_edit.service import VideoEditService
from backend.video_edit.sources import SourceResolver, UnsupportedSource

FFMPEG, FFPROBE = media.locate('ffmpeg'), media.locate('ffprobe')
HAS_FFMPEG = bool(FFMPEG and FFPROBE)


def render(target: Path, *args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', *args, '-y', str(target)], check=True)
    return target


def rgb(path: Path, *pre) -> bytes:
    """Decode one image (or the selected frame of a clip) to raw RGB for byte comparison."""
    return subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(path), *pre,
                           '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                          check=True, capture_output=True).stdout


def write_sidecar(target, prompt, txt_path=None):
    Path(target).with_suffix('.md').write_text(prompt, encoding='utf-8')


class FakeStore:
    def __init__(self, path):
        self.path = path

    def asset(self, ident):
        if ident != 'a' * 32:
            raise FileNotFoundError('视频素材不存在，请重新导入')
        return self.path

    def artifact(self, ident, name):
        if (ident, name) != ('b' * 32, 'out.mp4'):
            raise FileNotFoundError('视频结果不存在')
        return self.path


def wait(service, receipt, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = service.job(receipt['id'])
        if job['status'] not in contracts.ACTIVE:
            return job
        time.sleep(0.05)
    raise AssertionError('job did not finish')


class ContractTests(unittest.TestCase):
    def test_frame_lists_are_bounded_unique_and_accept_last(self):
        self.assertEqual(contracts.frame_list([5, 0, 5, -1], 100), [0, 5, 99])
        for bad in ([], [100], [1.5], [True], ['x'], list(range(contracts.MAX_FRAMES_PER_JOB + 1))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                contracts.frame_list(bad, 100)

    def test_submit_requires_known_kind_and_source(self):
        with self.assertRaises(ValueError):
            contracts.submit_request({'kind': 'render', 'source_url': '/video/a.mp4'})
        with self.assertRaises(ValueError):
            contracts.submit_request({'kind': 'scenes', 'source_url': ''})
        self.assertEqual(contracts.preview_width('999'), 320)
        self.assertEqual(contracts.preview_width('150'), 160)

    def test_sources_accept_only_served_media_urls(self):
        clip = Path('/clip.mp4')
        seen = []
        resolver = SourceResolver(archive_video=lambda rel: seen.append(rel) or (clip if rel == '2026-01-01/a.mp4' else None),
                                  stores={'topaz_video': FakeStore(clip), 'video_control': FakeStore(clip)})
        self.assertEqual(resolver.resolve('/video/2026-01-01/a.mp4'), clip)
        self.assertEqual(resolver.resolve('http://127.0.0.1:18463/video/2026-01-01/a.mp4'), clip)
        self.assertEqual(resolver.resolve('/api/topaz_video/source?id=' + 'a' * 32), clip)
        self.assertEqual(resolver.resolve(f'/api/video_control/artifact?id={"b" * 32}&name=out.mp4'), clip)
        with self.assertRaises(FileNotFoundError):
            resolver.resolve('/video/../../etc/passwd.mp4')
        with self.assertRaises(FileNotFoundError):
            resolver.resolve('/api/topaz_video/source?id=other')
        for url in ('/etc/passwd', 'file:///tmp/a.mp4', '/api/audio/artifact?id=x', 'blob:http://x/1', '/image/a.png'):
            with self.subTest(url=url), self.assertRaises(UnsupportedSource):
                resolver.resolve(url)

    def test_scene_picking_keeps_strong_separated_cuts_in_time_order(self):
        times = [index / 10 for index in range(100)]
        scored = [(1.0, 9.0), (1.1, 8.5), (3.0, 7.0), (5.0, 2.0), (0.0, 50.0), (7.0, 6.0)]
        self.assertEqual([scene['frame'] for scene in media.pick_scenes(scored, times)], [10, 30, 70])
        self.assertEqual(media.nearest_frame(times, 3.04), 30)
        self.assertEqual(media.nearest_frame(times, 3.06), 31)

    def test_audio_plan_copies_common_codecs_and_reencodes_others(self):
        self.assertEqual(media.audio_plan('aac'), ('.m4a', True))
        self.assertEqual(media.audio_plan('opus'), ('.ogg', True))
        self.assertEqual(media.audio_plan('pcm_s16le'), ('.wav', True))
        self.assertEqual(media.audio_plan('pcm_s16be'), ('.flac', False))
        self.assertEqual(media.audio_plan('ac3'), ('.flac', False))

    def test_archive_names_are_filed_as_video_frames(self):
        self.assertEqual(asset_index._infer_archive_provider(Path('/x/video_frame_120000_abc_f000001.png')), 'video_frame')
        self.assertEqual(asset_index._provider_label('video_frame'), '视频抽帧')


@unittest.skipUnless(HAS_FFMPEG, 'FFmpeg not installed')
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        # B-frames, a non-zero start time and a frame counter burned into every frame.
        cls.clip = render(root / 'counter.mp4', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=24:duration=3',
                          '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-output_ts_offset', '0.5',
                          '-c:v', 'libx264', '-bf', '3', '-g', '48', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest')
        # Variable frame rate: 10 fps for one second, then 30 fps.
        cls.vfr = render(root / 'vfr.mp4', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=30:duration=2',
                         '-vf', "select='gte(t,1)+not(mod(n,3))'", '-fps_mode', 'vfr',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p')
        cls.cuts = render(root / 'cuts.mp4', '-f', 'lavfi', '-i', 'color=red:size=160x96:rate=24:duration=1',
                          '-f', 'lavfi', '-i', 'color=blue:size=160x96:rate=24:duration=1',
                          '-f', 'lavfi', '-i', 'color=green:size=160x96:rate=24:duration=1',
                          '-filter_complex', '[0][1][2]concat=n=3:v=1:a=0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p')
        cls.pcm = render(root / 'pcm.mov', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=24:duration=1',
                         '-f', 'lavfi', '-i', 'sine=duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                         '-c:a', 'pcm_s16be', '-shortest')
        cls.silent = render(root / 'silent.mp4', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=24:duration=1',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        root = Path(self.work.name)
        self.day = root / 'archive' / '2026-11-10'
        clips = {path.name: path for path in (self.clip, self.vfr, self.cuts, self.pcm, self.silent)}
        self.archive = AudioArchive(lambda: root / 'archive' / 'audio', write_markdown=write_sidecar, peaks=lambda path: None)
        self.service = VideoEditService(
            resolver=SourceResolver(archive_video=lambda rel: clips.get(rel)),
            frame_dir=lambda: self.day, write_sidecar=write_sidecar, audio_archive=self.archive)

    def tearDown(self):
        self.service.close()
        self.work.cleanup()

    def assert_frames_exact(self, clip, frames):
        job = wait(self.service, self.service.submit({'kind': 'frames', 'source_url': '/video/' + clip.name, 'frames': frames}))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        for item in job['result']['frames']:
            with self.subTest(clip=clip.name, frame=item['frame']):
                expected = rgb(clip, '-vf', f"select=eq(n\\,{item['frame']})", '-fps_mode', 'passthrough')
                self.assertEqual(rgb(self.day / item['filename']), expected)
        return job

    def test_probe_lists_every_frame_relative_to_the_first(self):
        info = self.service.probe('/video/counter.mp4')
        self.assertEqual((info['width'], info['height'], info['frame_count']), (160, 96, 72))
        self.assertEqual(info['frame_times'][:3], [0.0, round(1 / 24, 6), round(2 / 24, 6)])
        self.assertTrue(info['has_audio'])
        self.assertNotIn('pts', info)
        vfr = self.service.probe('/video/vfr.mp4')
        gaps = {round(b - a, 3) for a, b in zip(vfr['frame_times'], vfr['frame_times'][1:])}
        self.assertEqual(gaps, {0.1, 0.033})

    def test_frames_match_ffmpeg_frame_numbers_with_b_frames_offset_and_vfr(self):
        job = self.assert_frames_exact(self.clip, [0, 1, 23, 24, 50, -1])
        self.assertEqual([item['frame'] for item in job['result']['frames']], [0, 1, 23, 24, 50, 71])
        first = job['result']['frames'][0]
        self.assertEqual((first['width'], first['height'], first['url']), (160, 96, '/image/' + first['filename']))
        self.assertRegex(first['filename'], r'^video_frame_\d{6}_[0-9a-f]{12}_f000000\.png$')
        self.assertIn('第 1 帧 / 共 72 帧', (self.day / first['filename']).with_suffix('.txt').read_text())
        self.assertTrue((self.day / first['filename']).with_suffix('.md').is_file())
        self.assertEqual(list(self.day.glob('.*')), [], 'no temp files left behind')
        self.assert_frames_exact(self.vfr, [0, 9, 10, 11, 25])

    def test_repeated_frames_reuse_archived_files(self):
        first = wait(self.service, self.service.submit({'kind': 'frames', 'source_url': '/video/counter.mp4', 'frames': [3]}))
        again = wait(self.service, self.service.submit({'kind': 'frames', 'source_url': '/video/counter.mp4', 'frames': [3, 4]}))
        self.assertEqual(again['result']['frames'][0]['filename'], first['result']['frames'][0]['filename'])
        self.assertEqual([item['reused'] for item in again['result']['frames']], [True, False])
        self.assertEqual(len(list(self.day.glob('*.png'))), 2)

    def test_scenes_find_hard_cuts(self):
        job = wait(self.service, self.service.submit({'kind': 'scenes', 'source_url': '/video/cuts.mp4'}))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        self.assertEqual([scene['frame'] for scene in job['result']['scenes']], [24, 48])
        self.assertEqual(job['progress_percent'], 100)

    def test_audio_is_copied_archived_and_reused(self):
        job = wait(self.service, self.service.submit({'kind': 'extract_audio', 'source_url': '/video/counter.mp4',
                                                      'source_name': '镜头一.mp4'}))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        result = job['result']
        self.assertRegex(result['name'], r'^video_audio_\d{6}_[0-9a-f]{12}\.m4a$')
        self.assertEqual((result['title'], result['source_codec'], result['reused']), ('镜头一 · 音轨', 'aac', False))
        self.assertTrue(result['url'].startswith('/api/assets/audio/file?path='))
        meta = json.loads(self.archive.resolve(result['path']).with_suffix('.json').read_text())
        self.assertEqual((meta['engine'], meta['copied'], meta['source_video']), ('video_edit', True, '镜头一.mp4'))
        again = wait(self.service, self.service.submit({'kind': 'extract_audio', 'source_url': '/video/counter.mp4'}))
        self.assertEqual((again['result']['path'], again['result']['reused']), (result['path'], True))
        listed = self.archive.list('镜头一')
        self.assertEqual(listed['total'], 1)

    def test_uncommon_audio_is_reencoded_to_flac_and_silent_video_is_rejected(self):
        job = wait(self.service, self.service.submit({'kind': 'extract_audio', 'source_url': '/video/pcm.mov'}))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        self.assertTrue(job['result']['name'].endswith('.flac'))
        self.assertEqual(job['result']['source_codec'], 'pcm_s16be')
        self.assertFalse(self.service.probe('/video/silent.mp4')['has_audio'])
        with self.assertRaisesRegex(ValueError, '没有音轨'):
            self.service.submit({'kind': 'extract_audio', 'source_url': '/video/silent.mp4'})

    def test_preview_is_a_small_jpeg(self):
        image = self.service.preview_frame('/video/counter.mp4', '10', '160')
        self.assertEqual(image[:2], b'\xff\xd8')
        with self.assertRaises(ValueError):
            self.service.preview_frame('/video/counter.mp4', '72', '160')

    def test_cancel_queued_job(self):
        jobs = [self.service.submit({'kind': 'scenes', 'source_url': '/video/cuts.mp4'}) for _ in range(3)]
        cancelled = self.service.cancel(jobs[-1]['id'])
        self.assertIn(cancelled['status'], {'cancelled', 'running'})
        self.assertEqual(wait(self.service, jobs[-1])['status'], 'cancelled')


class FakeHandler:
    def __init__(self, path, body=None):
        self.path = path
        data = json.dumps(body).encode() if body is not None else b''
        self.headers = {'Content-Length': str(len(data))}
        self.rfile = io.BytesIO(data)
        self.wfile = io.BytesIO()
        self.sent = None
        self.status = None

    def require_auth(self):
        return True

    def send_json(self, payload, status=200, headers=None):
        self.sent, self.status = payload, status

    def send_response(self, status):
        self.status = status

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass

    def _apply_cors_headers(self):
        pass


class RouteTests(unittest.TestCase):
    class Service:
        def status(self):
            return {'available': True}

        def probe(self, url):
            if url != '/video/a.mp4':
                raise UnsupportedSource('该视频来源暂不支持剪辑')
            return {'frame_count': 3}

        def preview_frame(self, url, frame, width):
            return b'\xff\xd8jpeg'

        def submit(self, body):
            return {'id': 'x', 'status': 'queued', 'kind': body['kind']}

        def job(self, ident):
            raise FileNotFoundError('视频剪辑任务不存在或已过期')

        def cancel(self, ident):
            raise RuntimeError('busy')

    def call(self, method, path, body=None):
        handler = FakeHandler(path, body)
        self.assertTrue(create_router(self.Service()).dispatch(handler, method, path.split('?')[0]))
        return handler

    def test_routes_map_errors_and_stream_previews(self):
        self.assertEqual(self.call('GET', '/api/video_edit/probe?source_url=%2Fvideo%2Fa.mp4').sent, {'frame_count': 3})
        self.assertEqual(self.call('GET', '/api/video_edit/probe?source_url=%2Fetc%2Fpasswd').status, 400)
        self.assertEqual(self.call('GET', '/api/video_edit/job?id=1').status, 404)
        self.assertEqual(self.call('POST', '/api/video_edit/cancel', {'id': 'x'}).status, 503)
        submitted = self.call('POST', '/api/video_edit/submit', {'kind': 'scenes'})
        self.assertEqual((submitted.status, submitted.sent['kind']), (202, 'scenes'))
        preview = self.call('GET', '/api/video_edit/preview_frame?source_url=x&frame=1')
        self.assertEqual((preview.status, preview.wfile.getvalue()), (200, b'\xff\xd8jpeg'))
        self.assertFalse(create_router(self.Service()).dispatch(FakeHandler('/'), 'GET', '/api/video_edit/render'))

    def test_server_wires_the_domain_with_resolvers_not_paths(self):
        server = (Path(__file__).resolve().parents[1] / 'backend' / 'server.py').read_text(encoding='utf-8')
        self.assertIn("'topaz_video': _TOPAZ_VIDEO_SERVICE.store, 'video_control': _VIDEO_CONTROL_SERVICE.store", server)
        self.assertIn("_VIDEO_EDIT_ROUTES.dispatch(self, 'GET', path)", server)
        self.assertIn("_VIDEO_EDIT_ROUTES.dispatch(self, 'POST', path)", server)
        self.assertIn('archive_video=_resolve_public_video_file', server)


if __name__ == '__main__':
    unittest.main()
