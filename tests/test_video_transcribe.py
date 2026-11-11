"""Automatic subtitles (backend.video_edit.transcribe): cue shaping, the request contract, the voice-only
audio graph, the in-memory job service and its routes.

The ASR port is a fake; the voice WAV is rendered by the local FFmpeg from synthetic clips (skipped
without FFmpeg).
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import wave

from backend.routes.video_edit_routes import create_router
from backend.video_edit import contracts, media, plan
from backend.video_edit.transcribe import TranscribeService, cues_from_tokens

from tests import test_video_compose as compose_tests
from tests.test_video_compose import FakeHandler, clip

FFMPEG = media.locate('ffmpeg')


def chars(text, start, step=0.2):
    """One token per character, `step` seconds each, punctuation attached to the character before it."""
    tokens, time_at = [], start
    for char in text:
        if tokens and char in '，。！？,.!?':
            tokens[-1]['text'] += char
            continue
        tokens.append({'start': round(time_at, 3), 'end': round(time_at + step, 3), 'text': char})
        time_at += step
    return tokens


class CueTests(unittest.TestCase):
    def test_sentences_split_at_punctuation_and_drop_trailing_marks(self):
        cues = cues_from_tokens(chars('你好。今天天气很好！', 0.0), 10)
        self.assertEqual([cue['text'] for cue in cues], ['你好', '今天天气很好！'])
        self.assertEqual(cues[0]['start'], 0.0)
        self.assertLessEqual(cues[0]['end'], cues[1]['start'])

    def test_short_comma_clause_stays_with_the_sentence(self):
        cues = cues_from_tokens(chars('好的，我们走。', 0.0), 10)
        self.assertEqual([cue['text'] for cue in cues], ['好的，我们走'])

    def test_long_clause_breaks_at_comma_and_width(self):
        cues = cues_from_tokens(chars('一二三四五六七八九十十一，' + '天' * 30, 0.0, 0.1), 20)
        self.assertEqual(cues[0]['text'], '一二三四五六七八九十十一')
        self.assertTrue(all(len(cue['text']) <= 24 for cue in cues))
        self.assertEqual(''.join(cue['text'] for cue in cues[1:]), '天' * 30)

    def test_pause_and_duration_breaks(self):
        tokens = chars('我来了', 0.0) + chars('你呢', 2.0)
        self.assertEqual([cue['text'] for cue in cues_from_tokens(tokens, 10)], ['我来了', '你呢'])
        slow = chars('慢' * 20, 0.0, 0.5)
        self.assertTrue(all(cue['end'] - cue['start'] <= 6.0 + 0.2 + 1e-6 for cue in cues_from_tokens(slow, 20)))

    def test_english_words_keep_spaces(self):
        tokens = [{'start': 0, 'end': .3, 'text': 'Hello '}, {'start': .3, 'end': .6, 'text': 'world. '},
                  {'start': .8, 'end': 1.1, 'text': 'Bye'}]
        self.assertEqual([cue['text'] for cue in cues_from_tokens(tokens, 5)], ['Hello world', 'Bye'])

    def test_cues_are_long_enough_never_overlap_and_stay_inside_total(self):
        tokens = [{'start': 1.0, 'end': 1.05, 'text': '嗨。'}, {'start': 1.1, 'end': 1.2, 'text': '好。'},
                  {'start': 4.9, 'end': 5.0, 'text': '晚。'}, {'start': 9.9, 'end': 10.0, 'text': '尾。'}]
        cues = cues_from_tokens(tokens, 10)
        self.assertEqual([cue['text'] for cue in cues], ['嗨', '好', '晚'])
        for cue in cues:
            self.assertGreaterEqual(cue['end'] - cue['start'], contracts.MIN_CUE_SECONDS - 1e-6)
            self.assertLessEqual(cue['end'], 10)
        for left, right in zip(cues, cues[1:]):
            self.assertLessEqual(left['end'], right['start'] + 1e-6)

    def test_limits(self):
        tokens = [{'start': index * 0.5, 'end': index * 0.5 + 0.2, 'text': '字。'} for index in range(300)]
        cues = cues_from_tokens(tokens, 200)
        self.assertEqual(len(cues), contracts.MAX_CUES)
        self.assertEqual(cues_from_tokens([], 10), [])
        self.assertEqual(cues_from_tokens([{'start': 0, 'end': 1, 'text': '，。'}], 10), [])


class ContractTests(unittest.TestCase):
    def test_request_ignores_subtitles_and_checks_script(self):
        request = contracts.transcribe_request({'recipe': {'clips': [clip()], 'subtitles': {'cues': 'broken'}},
                                                'script': 'traditional'})
        self.assertEqual((request['script'], request['recipe']['subtitles']), ('traditional', None))
        self.assertEqual(contracts.transcribe_request({'recipe': {'clips': [clip()]}})['script'], 'original')
        for body in (None, {}, {'recipe': {'clips': [clip()]}, 'script': 'latin'}):
            with self.assertRaises(ValueError):
                contracts.transcribe_request(body)


class VoiceGraphTests(unittest.TestCase):
    def clips(self, **second):
        info = {'audio': True}
        return [{'path': '/a.mp4', 'seek': ['-ss', '0'], 'seconds': 2.0, 'audio': True, 'has_audio': True,
                 'info': info, 'speed': 1.0, 'transition': {'type': 'fade', 'duration': 0.5}},
                {'path': '/b.mp4', 'seek': ['-ss', '0'], 'seconds': 2.0, 'audio': False, 'has_audio': True,
                 'info': info, 'speed': 2.0, 'transition': {'type': 'none', 'duration': 0.5}, **second}]

    def test_voice_graph_has_no_music_and_ends_in_16k_mono(self):
        graph, total = plan.voice_graph(self.clips())
        self.assertIn('acrossfade=d=0.500000', graph)
        self.assertTrue(graph.endswith('[voice]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono[aout]'))
        self.assertNotIn('amix', graph)
        self.assertAlmostEqual(total, plan.total_seconds(self.clips()))
        argv, _ = plan.voice_command('ffmpeg', self.clips(), target='/t/v.wav')
        self.assertEqual(argv[argv.index('-c:a') + 1], 'pcm_s16le')
        self.assertEqual(argv[argv.index('-t') + 1], f'{total:.6f}')
        self.assertEqual(argv[-2:], ['-y', '/t/v.wav'])


class FakeAsr:
    def __init__(self, heard=None, block=None):
        self.calls, self.heard, self.block = [], heard, block

    def transcribe(self, audio, *, seconds, script, cancelled, progress):
        with wave.open(str(audio)) as file:
            self.calls.append({'rate': file.getframerate(), 'channels': file.getnchannels(),
                               'seconds': file.getnframes() / file.getframerate(), 'total': seconds, 'script': script})
        progress(0.5, '识别语音并对齐时间')
        if self.block:
            self.block.wait(10)
            if cancelled.is_set():
                raise RuntimeError('已取消')
        return self.heard or {'language': 'Chinese', 'text': '你好。', 'speech': True,
                              'tokens': [{'start': 0.2, 'end': 0.6, 'text': '你好。'}]}


@unittest.skipUnless(FFMPEG and media.locate('ffprobe'), 'FFmpeg required')
class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name, extra in (('tone.mp4', ['-f', 'lavfi', '-i', 'sine=f=440:d=2', '-c:a', 'aac', '-shortest']),
                            ('mute.mp4', [])):
            subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=red:s=160x120:r=24:d=2', *extra, '-c:v', 'libx264', '-y', str(cls.root / name)],
                           check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        root = self.root

        class Compose:
            def resolve(self, spec):
                clips = []
                for item in spec['clips']:
                    path = root / item['source_url'].rsplit('/', 1)[-1]
                    has = path.name == 'tone.mp4'
                    clips.append({'path': path, 'seek': ['-ss', '0'], 'seconds': 2.0, 'audio': has and item['audio'],
                                  'has_audio': has, 'info': {'audio': has}, 'speed': item['speed'],
                                  'transition': item['transition']})
                return {'clips': clips, 'seconds': plan.total_seconds(clips)}

        self.Compose = Compose

    def wait(self, transcribe, receipt):
        deadline = time.time() + 30
        while time.time() < deadline:
            job = transcribe.job(receipt['id'])
            if job['status'] not in contracts.ACTIVE:
                return job
            time.sleep(0.05)
        raise AssertionError('transcribe did not finish')

    def test_voice_audio_is_16k_mono_on_the_output_timeline_and_cues_come_back(self):
        asr = FakeAsr()
        service = TranscribeService(compose=self.Compose(), asr=asr)
        self.addCleanup(service.close)
        body = {'recipe': {'clips': [clip('/video/tone.mp4', speed=2.0), clip('/video/mute.mp4')]},
                'script': 'simplified'}
        job = self.wait(service, service.submit(body))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        self.assertTrue(service.owns(job['id']) and job['id'].startswith('transcribe_'))
        call = asr.calls[0]
        self.assertEqual((call['rate'], call['channels'], call['script']), (16000, 1, 'simplified'))
        self.assertAlmostEqual(call['seconds'], 3.0, delta=0.05)
        self.assertAlmostEqual(call['total'], 3.0, delta=1e-6)
        self.assertEqual(job['result']['cues'], [{'start': 0.2, 'end': 0.8, 'text': '你好'}])
        self.assertEqual(job['result']['language'], 'Chinese')

    def test_music_only_returns_no_cues(self):
        asr = FakeAsr(heard={'language': 'Chinese', 'text': '啊。', 'speech': False,
                             'tokens': [{'start': 0, 'end': 1, 'text': '啊。'}]})
        service = TranscribeService(compose=self.Compose(), asr=asr)
        self.addCleanup(service.close)
        job = self.wait(service, service.submit({'recipe': {'clips': [clip('/video/tone.mp4')]}}))
        self.assertEqual((job['status'], job['result']['cues'], job['result']['speech']), ('succeeded', [], False))

    def test_silent_recipe_is_refused_up_front(self):
        service = TranscribeService(compose=self.Compose(), asr=FakeAsr())
        self.addCleanup(service.close)
        with self.assertRaisesRegex(ValueError, '没有可识别的原声'):
            service.submit({'recipe': {'clips': [clip('/video/mute.mp4'), clip('/video/tone.mp4', audio=False)]}})

    def test_cancel_and_queue_limit(self):
        gate = threading.Event()
        service = TranscribeService(compose=self.Compose(), asr=FakeAsr(block=gate))
        self.addCleanup(service.close)
        body = {'recipe': {'clips': [clip('/video/tone.mp4')]}}
        first, second = service.submit(body), service.submit(body)
        with self.assertRaisesRegex(RuntimeError, '已有自动字幕任务'):
            service.submit(body)
        self.assertEqual(service.cancel(second['id'])['status'], 'cancelled')
        deadline = time.time() + 10
        while service.job(first['id'])['status'] != 'running' and time.time() < deadline:
            time.sleep(0.05)
        service.cancel(first['id'])
        gate.set()
        self.assertEqual(self.wait(service, first)['status'], 'cancelled')
        with self.assertRaises(FileNotFoundError):
            service.job('transcribe_missing')


class TranscribeRouteTests(unittest.TestCase):
    class Transcribe:
        def owns(self, ident):
            return ident == 'transcribe_1'

        def submit(self, body):
            return {'id': 'transcribe_1', 'kind': 'transcribe', 'status': 'queued'}

        def job(self, ident):
            return {'id': ident, 'kind': 'transcribe'}

        def cancel(self, ident):
            return {'id': ident, 'kind': 'transcribe', 'status': 'cancelled'}

    def call(self, method, path, body=None):
        handler = FakeHandler(path, body)
        router = create_router(compose_tests.RouteTests.Edit(), compose_tests.RouteTests.Compose(), self.Transcribe())
        self.assertTrue(router.dispatch(handler, method, path.split('?')[0]))
        return handler

    def test_submit_job_and_cancel_go_to_the_transcribe_service(self):
        submitted = self.call('POST', '/api/video_edit/transcribe', {'recipe': {'clips': [clip()]}})
        self.assertEqual((submitted.status, submitted.sent['kind']), (202, 'transcribe'))
        self.assertEqual(self.call('GET', '/api/video_edit/job?id=transcribe_1').sent['kind'], 'transcribe')
        self.assertEqual(self.call('POST', '/api/video_edit/cancel', {'id': 'transcribe_1'}).sent['kind'], 'transcribe')
        self.assertEqual(self.call('GET', '/api/video_edit/job?id=' + 'c' * 32).sent['kind'], 'compose')

    def test_transcribe_never_touches_telegram_or_the_archive(self):
        source = (Path(__file__).resolve().parents[1] / 'backend' / 'video_edit' / 'transcribe.py').read_text(
            encoding='utf-8').lower()
        for word in ('telegram', 'senddocument', 'write_sidecar', 'output_dir'):
            self.assertNotIn(word, source)


if __name__ == '__main__':
    unittest.main()
