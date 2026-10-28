"""Canvas video-node uploads: header sniffing, archive storage, reuse and the authenticated route."""
import io
from pathlib import Path
import tempfile
import unittest

from backend.routes.video_upload_routes import create_router
from backend.services.video_upload import MAX_UPLOAD, VideoUploads, video_suffix

MP4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2' + b'\x00' * 64
MOV = b'\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00qt  ' + b'\x00' * 64
WEBM = b'\x1a\x45\xdf\xa3' + b'\x00' * 64


class VideoUploadServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.day = Path(self.temp.name) / '2026-10-21'
        self.probed = []
        self.meta = {'width': 1280, 'height': 720, 'fps': 30.0, 'duration_seconds': 15.03}
        self.uploads = VideoUploads(lambda: self.day, self.probe)

    def tearDown(self):
        self.temp.cleanup()

    def probe(self, path):
        self.probed.append(path)
        return dict(self.meta)

    def test_container_comes_from_the_header(self):
        self.assertEqual(video_suffix(MP4), '.mp4')
        self.assertEqual(video_suffix(MOV), '.mov')
        self.assertEqual(video_suffix(WEBM), '.webm')
        for data in (b'\x89PNG\r\n\x1a\n' + b'\x00' * 16, b'plain text', b''):
            with self.assertRaises(ValueError):
                video_suffix(data)

    def test_upload_lands_in_todays_archive_folder_with_metadata(self):
        result = self.uploads.upload(MP4, 'dance clip.mov')
        path = self.day / result['filename']
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), MP4)
        self.assertRegex(result['filename'], r'^video_upload_\d{6}_[0-9a-f]{12}\.mp4$')
        self.assertEqual(result['url'], '/video/' + result['filename'])
        self.assertEqual(result['name'], 'dance clip.mov')
        self.assertEqual((result['width'], result['height'], result['fps'], result['duration_seconds']), (1280, 720, 30.0, 15.03))
        self.assertEqual((result['mime_type'], result['file_size'], result['reused']), ('video/mp4', len(MP4), False))
        self.assertEqual(list(self.day.glob('*.writing')), [])

    def test_same_content_reuses_the_file(self):
        first = self.uploads.upload(WEBM, 'a.webm')
        second = self.uploads.upload(WEBM, 'renamed.webm')
        self.assertEqual(first['filename'], second['filename'])
        self.assertTrue(second['reused'])
        self.assertEqual(second['name'], 'renamed.webm')
        self.assertEqual(len(list(self.day.iterdir())), 1)

    def test_unreadable_video_is_rejected_and_removed(self):
        self.meta = {}
        with self.assertRaisesRegex(ValueError, '无法读取视频'):
            self.uploads.upload(MOV, 'broken.mov')
        self.assertEqual(list(self.day.iterdir()), [])

    def test_names_are_display_only(self):
        result = self.uploads.upload(MP4, '../../etc/passwd\x00.mp4')
        self.assertEqual(result['name'], 'passwd.mp4')
        self.assertEqual(self.uploads.upload(MP4, '')['name'], '本地视频.mp4')
        self.assertEqual([p.parent for p in self.day.iterdir()], [self.day])

    def test_size_limits(self):
        with self.assertRaises(ValueError):
            self.uploads.upload(b'', 'empty.mp4')


class VideoUploadRouteTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        test = self

        class Uploads:
            def upload(self, data, name):
                test.calls.append((data, name))
                if data == b'bad':
                    raise ValueError('仅支持 MP4、MOV 或 WebM 视频')
                return {'url': '/video/x.mp4'}
        self.router = create_router(Uploads())

    def handler(self, path, body=b'', authed=True, length=None):
        class Handler:
            headers = {'Content-Length': str(len(body) if length is None else length)}
            rfile = io.BytesIO(body)
            def __init__(self):
                self.path, self.sent = path, []
            def require_auth(self): return authed
            def send_json(self, payload, status=200, *_): self.sent.append((status, payload))
        return Handler()

    def test_requires_auth_and_only_claims_its_route(self):
        handler = self.handler('/api/video/upload', b'data', authed=False)
        self.assertTrue(self.router.dispatch(handler, 'POST', '/api/video/upload'))
        self.assertEqual((handler.sent, self.calls), ([], []))
        self.assertFalse(self.router.dispatch(handler, 'GET', '/api/video/upload'))
        self.assertFalse(self.router.dispatch(handler, 'POST', '/api/video/generate'))

    def test_passes_raw_body_and_name(self):
        handler = self.handler('/api/video/upload?name=%E8%88%9E.mp4', b'data')
        self.router.dispatch(handler, 'POST', '/api/video/upload')
        self.assertEqual(self.calls, [(b'data', '舞.mp4')])
        self.assertEqual(handler.sent, [(200, {'url': '/video/x.mp4'})])

    def test_errors_are_400(self):
        for body, length in ((b'', 0), (b'x', MAX_UPLOAD + 1), (b'abc', 10), (b'bad', None)):
            handler = self.handler('/api/video/upload', body, length=length)
            self.router.dispatch(handler, 'POST', '/api/video/upload')
            self.assertEqual(handler.sent[-1][0], 400, (body, length))


if __name__ == '__main__':
    unittest.main()
