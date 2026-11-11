"""Generated audio is archived under <archive>/audio/YYYY-MM-DD/ with sidecars, listed, served
and deleted with undo; the audio job keeps its receipt, and image/video scans skip the subtree.

Synthetic fixtures only: no audio engine, models, real archive or running server."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import subprocess

from backend import asset_index
from backend.audio.service import AudioService
from backend.routes.archive_audio_routes import create_router
from backend.services import archive_audio
from backend.services.archive_audio import AudioArchive, read_stream_info
from backend.storage_paths import write_obsidian_prompt_sidecar


def flac_bytes(rate=48000, channels=2, samples=48000 * 3):
    packed = (rate << 44) | ((channels - 1) << 41) | (15 << 36) | samples
    info = b'\x10\x00\x10\x00' + b'\x00' * 6 + packed.to_bytes(8, 'big') + b'\x00' * 16
    return b'fLaC' + b'\x80' + len(info).to_bytes(3, 'big') + info + b'frames'


def wav_bytes(rate=44100, channels=1, seconds=2):
    byte_rate = rate * channels * 2
    fmt = struct.pack('<HHIIHH', 1, channels, rate, byte_rate, channels * 2, 16)
    data = b'\x00' * (byte_rate * seconds)
    body = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'LIST' + struct.pack('<I', 3) + b'abc\x00' + b'data' + struct.pack('<I', len(data)) + data
    return b'RIFF' + struct.pack('<I', len(body)) + body


SPEC = {'operation': 'generate', 'precision': '8bit', 'audio_format': 'flac',
        'request': {'style': 'Mandarin pop, piano', 'lyrics': '[Verse]\n第一行', 'seed': 7, 'cot': 'full',
                    'generation_config': {'ode_steps': 32}}}


class FakeTrash:
    def __init__(self, root):
        self.root = Path(root)
        self.batches = []

    def move(self, path, deleted, missing, skipped, moves=None):
        target = self.root / path.name
        self.root.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        deleted.append(path.name)
        moves.append({'original_path': str(path), 'trash_path': str(target), 'filename': path.name})

    def record(self, batch):
        self.batches.append(batch)
        return {'batch_id': f'batch-{len(self.batches)}'}


class ArchiveFixture(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.archive_root = self.base / 'archive'
        self.trash = FakeTrash(self.base / 'trash')
        self.peak_calls = []
        self.peak_result = [0.5] * 64
        self.archive = AudioArchive(lambda: self.archive_root / 'audio', write_markdown=write_obsidian_prompt_sidecar,
                                    move_to_trash=self.trash.move, record_batch=self.trash.record,
                                    peaks=self.fake_peaks)
        self.source = self.base / 'job' / 'result' / 'audio.flac'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(flac_bytes())
        (self.source.parent / 'score.abc').write_text('X:1\nK:C\nCDEF|')

    def fake_peaks(self, path):
        self.peak_calls.append(Path(path).name)
        return self.peak_result

    def tearDown(self):
        self._temp.cleanup()

    def publish(self, job_id='a' * 32, created_at=None):
        return self.archive.publish(self.source, job_id=job_id, created_at=created_at or time.time(),
                                    spec=SPEC, score=self.source.parent / 'score.abc')


class StreamInfoTests(ArchiveFixture):
    def test_reads_flac_and_wav_headers_without_audio_libraries(self):
        flac = self.base / 'x.flac'
        flac.write_bytes(flac_bytes(rate=48000, channels=2, samples=48000 * 3))
        self.assertEqual(read_stream_info(flac), {'duration_seconds': 3.0, 'sample_rate': 48000, 'channels': 2})
        wav = self.base / 'x.wav'
        wav.write_bytes(wav_bytes(rate=44100, channels=1, seconds=2))
        self.assertEqual(read_stream_info(wav), {'duration_seconds': 2.0, 'sample_rate': 44100, 'channels': 1})
        broken = self.base / 'y.flac'
        broken.write_bytes(b'not audio')
        self.assertIsNone(read_stream_info(broken))


class PublishListTests(ArchiveFixture):
    def test_publish_copies_song_and_sidecars_into_a_date_folder(self):
        created = time.mktime((2026, 11, 9, 10, 0, 0, 0, 0, -1))
        record = self.publish(created_at=created)
        self.assertEqual(record, {'path': '2026-11-09/yue_aaaaaaaaaaaa.flac'})
        song = self.archive_root / 'audio' / record['path']
        self.assertEqual(song.read_bytes(), self.source.read_bytes())
        self.assertTrue(self.source.is_file(), 'the job directory keeps its receipt')
        self.assertIn('Mandarin pop, piano', song.with_suffix('.txt').read_text(encoding='utf-8'))
        markdown = song.with_suffix('.md').read_text(encoding='utf-8')
        self.assertIn('type: audio_prompt', markdown)
        self.assertIn('audio: "yue_aaaaaaaaaaaa.flac"', markdown)
        self.assertIn('![[yue_aaaaaaaaaaaa.flac]]', markdown)
        self.assertEqual(song.with_suffix('.abc').read_text(), 'X:1\nK:C\nCDEF|')
        meta = json.loads(song.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['job_id'], meta['seed'], meta['duration_seconds'], meta['has_score']), ('a' * 32, 7, 3.0, True))
        self.assertEqual(self.publish(created_at=created), record, 'publishing the same job again is idempotent')
        self.assertEqual(len(list(song.parent.iterdir())), 5, 'no temporary files are left behind')

    def test_list_reports_metadata_filters_and_hides_dotfiles(self):
        first = self.publish('a' * 32, created_at=1000)
        self.publish('b' * 32, created_at=2000)
        day = (self.archive_root / 'audio' / first['path']).parent
        (day / '.audio-partial.flac').write_bytes(flac_bytes())
        (self.archive_root / 'audio' / '.trash').mkdir()
        (self.archive_root / 'audio' / '.trash' / 'old.flac').write_bytes(flac_bytes())
        (day / 'cover.png').write_bytes(b'png')
        loose = self.archive_root / 'audio' / 'imported' / 'take.wav'
        loose.parent.mkdir()
        loose.write_bytes(wav_bytes(seconds=1))
        result = self.archive.list()
        # Newest first; a file without a metadata sidecar falls back to its modification time.
        self.assertEqual([item['name'] for item in result['items']], ['take.wav', 'yue_bbbbbbbbbbbb.flac', 'yue_aaaaaaaaaaaa.flac'])
        self.assertEqual(result['total'], 3)
        newest = result['items'][1]
        self.assertEqual(newest['url'], '/api/assets/audio/file?path=' + newest['path'].replace('/', '%2F'))
        self.assertEqual((newest['format'], newest['mime_type'], newest['duration_seconds'], newest['has_score']), ('FLAC', 'audio/flac', 3.0, True))
        self.assertTrue(newest['id'].startswith('audio_'))
        self.assertNotIn(str(self.base), json.dumps(result), 'no absolute local paths')
        wav = next(item for item in result['items'] if item['name'] == 'take.wav')
        self.assertEqual((wav['duration_seconds'], wav['job_id'], wav['title']), (1.0, '', 'take'))
        self.assertEqual(result['stats']['by_format'], {'FLAC': 2, 'WAV': 1})
        self.assertEqual(self.archive.list('PIANO')['total'], 2)
        self.assertEqual(self.archive.list('第一行')['total'], 2)
        self.assertEqual(self.archive.list('take')['total'], 1)
        self.assertEqual(self.archive.list(limit=1, offset=2)['items'][0]['name'], 'yue_aaaaaaaaaaaa.flac')

    def test_list_of_a_missing_archive_is_empty(self):
        self.assertEqual(self.archive.list()['items'], [])

    def test_resolve_stays_inside_the_audio_subtree(self):
        record = self.publish()
        self.assertEqual(self.archive.resolve(record['path']), (self.archive_root / 'audio' / record['path']).resolve())
        (self.archive_root / 'outside.flac').write_bytes(flac_bytes())
        for bad in ('', '../outside.flac', record['path'].replace('.flac', '.txt'), '/etc/passwd',
                    '2026-11-09/../../outside.flac', '.trash/x.flac', 'missing.flac'):
            with self.subTest(path=bad), self.assertRaises(FileNotFoundError):
                self.archive.resolve(bad)
        link = self.archive_root / 'audio' / 'link.flac'
        link.symlink_to(self.archive_root / 'outside.flac')
        with self.assertRaises(FileNotFoundError):
            self.archive.resolve('link.flac')

    def test_delete_moves_song_and_sidecars_into_an_undoable_batch(self):
        record = self.publish()
        result = self.archive.delete([record['path'], record['path']])
        self.assertEqual(result['delete_batch_id'], 'batch-1')
        self.assertEqual(sorted(result['deleted_files']), sorted(f'yue_aaaaaaaaaaaa{s}' for s in ('.flac', '.txt', '.md', '.json', '.abc')))
        batch = self.trash.batches[0]
        self.assertEqual(batch['asset_ids'], [archive_audio.audio_asset_id(record['path'])])
        self.assertEqual(len(batch['moves']), 5)
        self.assertEqual(self.archive.list()['items'], [])
        with self.assertRaises(ValueError):
            self.archive.delete([])
        with self.assertRaises(FileNotFoundError):
            self.archive.delete(['../x.flac'])


class FakeRuntime:
    def __init__(self, write_song=True):
        self.write_song = write_song

    def status(self):
        return {'generation_ready': True, 'transcription_ready': True, 'reasons': []}

    def execute(self, spec, directory, asset, cancel, progress):
        (directory / 'result').mkdir()
        if self.write_song:
            (directory / 'result' / 'audio.flac').write_bytes(flac_bytes())
        (directory / 'result' / 'score.abc').write_text('X:1')
        return 'succeeded', ''


class ServiceArchiveTests(ArchiveFixture):
    def wait(self, service, job_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            job = service.store.get(job_id)
            if job['status'] not in ('queued', 'running') and ('archive' in job or 'archive_error' in job):
                return job
            time.sleep(.02)
        self.fail('audio job did not finish')

    def test_finished_song_is_archived_and_the_receipt_keeps_working(self):
        service = AudioService(self.base / 'data', FakeRuntime(), archive=self.archive.publish)
        self.addCleanup(service.close)
        job = self.wait(service, service.submit({'request': {'style': 'pop', 'lyrics': 'la'}})['id'])
        self.assertEqual(job['status'], 'succeeded')
        self.assertTrue(job['archive']['path'].endswith(f"/yue_{job['id'][:12]}.flac"))
        self.assertTrue((self.archive_root / 'audio' / job['archive']['path']).is_file())
        self.assertEqual(service.store.artifact(job['id'], 'result/audio.flac').read_bytes(), flac_bytes())
        self.assertEqual(service.unarchived(), {'count': 0, 'enabled': True})

    def test_archive_failure_is_recorded_without_failing_the_job(self):
        def broken(*args, **kwargs):
            raise OSError('disk full')
        service = AudioService(self.base / 'data', FakeRuntime(), archive=broken)
        self.addCleanup(service.close)
        job = self.wait(service, service.submit({'request': {'style': 'pop', 'lyrics': 'la'}})['id'])
        self.assertEqual((job['status'], job['archive_error']), ('succeeded', 'disk full'))
        self.assertNotIn('archive', job)
        self.assertEqual(service.unarchived()['count'], 1, 'a failed archive can be retried by the backfill')

    def test_backfill_copies_only_earlier_finished_songs(self):
        service = AudioService(self.base / 'data', FakeRuntime())
        self.addCleanup(service.close)
        store = service.store
        def finished(spec, status, song=True):
            job = store.create(spec)
            directory = store.path(job['id']) / 'result'
            directory.mkdir()
            if song:
                (directory / f"audio.{spec.get('audio_format', 'flac')}").write_bytes(flac_bytes() if spec.get('audio_format', 'flac') == 'flac' else wav_bytes())
            return store.update(job['id'], status=status, artifacts=service._manifest(job['id']))
        song = finished(SPEC, 'succeeded')
        wav = finished({**SPEC, 'audio_format': 'wav'}, 'partial')
        finished(SPEC, 'failed')
        finished({'operation': 'transcribe', 'asset_id': 'a' * 64 + '.wav'}, 'succeeded', song=False)
        self.assertEqual(service.unarchived(), {'count': 0, 'enabled': False})
        with self.assertRaises(RuntimeError):
            service.archive_existing()
        service.archive = self.archive.publish
        self.assertEqual(service.unarchived()['count'], 2)
        self.assertEqual(service.archive_existing(), {'archived': 2, 'failed': 0})
        self.assertEqual(service.archive_existing(), {'archived': 0, 'failed': 0})
        names = sorted(item['name'] for item in self.archive.list()['items'])
        self.assertEqual(names, sorted([f"yue_{song['id'][:12]}.flac", f"yue_{wav['id'][:12]}.wav"]))
        self.assertTrue((store.path(song['id']) / 'result' / 'audio.flac').is_file(), 'originals stay in place')


class FakeHandler:
    def __init__(self, path, body=None):
        self.path, self.body = path, body or {}
        self.headers = {}
        self.sent = []

    def require_auth(self):
        return True

    def read_json_body(self, max_bytes=0):
        return self.body

    def send_json(self, payload, status=200, headers=None):
        self.sent.append((status, payload))


class PeakTests(ArchiveFixture):
    def test_publish_stores_the_waveform_and_list_returns_it(self):
        record = self.publish()
        sidecar = json.loads((self.archive_root / 'audio' / record['path']).with_suffix('.json').read_text())
        self.assertEqual(sidecar['peaks'], [0.5] * 64)
        self.assertEqual(self.archive.list()['items'][0]['peaks'], [0.5] * 64)
        self.assertEqual(self.archive.peaks(record['path']), {'peaks': [0.5] * 64})
        self.assertEqual(self.peak_calls, ['yue_aaaaaaaaaaaa.flac'], 'a stored waveform is never recomputed')

    def test_older_songs_get_their_waveform_once_and_keep_it_in_the_sidecar(self):
        self.peak_result = None
        record = self.publish()
        self.assertIsNone(self.archive.list()['items'][0]['peaks'])
        self.peak_result = [0.25] * 64
        self.assertEqual(self.archive.peaks(record['path']), {'peaks': [0.25] * 64})
        sidecar = json.loads((self.archive_root / 'audio' / record['path']).with_suffix('.json').read_text())
        self.assertEqual((sidecar['peaks'], sidecar['job_id']), ([0.25] * 64, 'a' * 32), 'other metadata survives')
        self.archive.peaks(record['path'])
        self.assertEqual(self.archive.list()['items'][0]['peaks'], [0.25] * 64)
        self.assertEqual(len(self.peak_calls), 2)

    def test_a_song_without_a_sidecar_is_cached_in_memory_and_bad_output_is_dropped(self):
        day = self.archive_root / 'audio' / '2026-11-09'
        day.mkdir(parents=True)
        (day / 'loose.wav').write_bytes(wav_bytes())
        self.assertEqual(self.archive.peaks('2026-11-09/loose.wav'), {'peaks': [0.5] * 64})
        self.archive.peaks('2026-11-09/loose.wav')
        self.assertEqual(self.peak_calls, ['loose.wav'])
        self.assertFalse((day / 'loose.json').exists(), 'files we did not archive get no new sidecar')
        (day / 'odd.wav').write_bytes(wav_bytes())
        for bad in (None, [2.0] * 64, [0.5] * 3, [True] * 64):
            self.peak_result = bad
            self.assertEqual(self.archive.peaks('2026-11-09/odd.wav'), {'peaks': None})
        with self.assertRaises(FileNotFoundError):
            self.archive.peaks('../outside.wav')

    @unittest.skipUnless(archive_audio._ffmpeg(), 'FFmpeg not installed')
    def test_ffmpeg_envelope_follows_loudness(self):
        song = self.base / 'ramp.wav'
        subprocess.run([archive_audio._ffmpeg(), '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=4,volume=eval=frame:volume=t/4', '-y', str(song)],
                       check=True, capture_output=True, timeout=60)
        peaks = archive_audio.compute_peaks(song, 16)
        self.assertEqual(len(peaks), 16)
        self.assertTrue(all(0 <= value <= 1 for value in peaks))
        self.assertEqual(max(peaks), 1)
        self.assertLess(peaks[1], peaks[-1], 'a fade-in rises from left to right')

    def test_missing_ffmpeg_means_no_waveform(self):
        with patch.object(archive_audio, '_ffmpeg', return_value=None):
            self.assertIsNone(archive_audio.compute_peaks(self.source))


class RouteTests(ArchiveFixture):
    def test_routes_list_serve_and_delete_with_errors_as_json(self):
        router = create_router(self.archive)
        record = self.publish()
        listing = FakeHandler('/api/assets/audio?query=piano&limit=5')
        self.assertTrue(router.dispatch(listing, 'GET', '/api/assets/audio'))
        self.assertEqual(listing.sent[0][1]['total'], 1)
        with patch('backend.routes.archive_audio_routes.send_artifact') as send:
            served = FakeHandler('/api/assets/audio/file?path=' + record['path'])
            router.dispatch(served, 'GET', '/api/assets/audio/file')
            path, content_type = send.call_args.args[1:]
            self.assertEqual((path.name, content_type), ('yue_aaaaaaaaaaaa.flac', 'audio/flac'))
        escape = FakeHandler('/api/assets/audio/file?path=../outside.flac')
        router.dispatch(escape, 'GET', '/api/assets/audio/file')
        self.assertEqual(escape.sent[0][0], 404)
        peaks = FakeHandler('/api/assets/audio/peaks?path=' + record['path'])
        router.dispatch(peaks, 'GET', '/api/assets/audio/peaks')
        self.assertEqual(peaks.sent[0][1], {'peaks': [0.5] * 64})
        outside = FakeHandler('/api/assets/audio/peaks?path=../x.flac')
        router.dispatch(outside, 'GET', '/api/assets/audio/peaks')
        self.assertEqual(outside.sent[0][0], 404)
        bad = FakeHandler('/api/assets/audio/delete', {'paths': 'x'})
        router.dispatch(bad, 'POST', '/api/assets/audio/delete')
        self.assertEqual(bad.sent[0][0], 400)
        delete = FakeHandler('/api/assets/audio/delete', {'paths': [record['path']]})
        router.dispatch(delete, 'POST', '/api/assets/audio/delete')
        self.assertEqual((delete.sent[0][0], delete.sent[0][1]['undo_id']), (200, 'batch-1'))
        self.assertFalse(router.dispatch(FakeHandler('/api/assets/audio'), 'POST', '/api/assets/audio'))


class ScannerExclusionTests(ArchiveFixture):
    def test_image_index_skips_the_audio_subtree(self):
        day = self.archive_root / '2026-11-09'
        day.mkdir(parents=True)
        (day / 'gpt_a.png').write_bytes(b'png')
        cover = self.archive_root / 'audio' / '2026-11-09' / 'cover.png'
        cover.parent.mkdir(parents=True)
        cover.write_bytes(b'png')
        with patch.object(asset_index, 'archive_scan_roots', lambda: [('main', self.archive_root)]):
            names = [rel for _, _, rel in asset_index._archive_image_files()]
            children = [name for part in asset_index._index_fingerprint() if isinstance(part, tuple)
                        for name, *_ in (item for item in part if isinstance(item, tuple))]
        self.assertEqual(names, ['2026-11-09/gpt_a.png'])
        self.assertIn('2026-11-09', children)
        self.assertNotIn('audio', children, 'new audio folders do not invalidate the image index')

    def test_video_scan_skips_the_audio_subtree(self):
        from backend import server
        day = self.archive_root / '2026-11-09'
        day.mkdir(parents=True)
        (day / 'comfy_a.mp4').write_bytes(b'')
        upload = self.archive_root / 'audio' / 'imported' / 'voice.webm'
        upload.parent.mkdir(parents=True)
        upload.write_bytes(b'')
        with patch.object(server, 'archive_scan_roots', lambda: [('main', self.archive_root)]), \
                patch.object(server, '_probe_archive_video_metadata', lambda *a, **k: {}):
            result = server._list_archive_videos(source='all')
        names = [item.get('media_name') or item.get('file_name') or item.get('name') for item in result['videos']]
        self.assertEqual(names, ['comfy_a.mp4'])


if __name__ == '__main__':
    unittest.main()
