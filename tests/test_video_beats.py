"""Music beats for compose snapping (backend.video_edit.beats): level parsing, onset envelope, tempo
and beat tracking on ideal envelopes, a synthetic drum track rendered with the standard library and
analyzed by the local FFmpeg (skipped without it), the service method and its route."""
from __future__ import annotations

import io
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
import wave

from backend.routes.video_edit_routes import create_router
from backend.video_edit import beats, media
from backend.video_edit.compose import ComposeService
from backend.video_edit.storage import ComposeStore

FFMPEG = media.locate('ffmpeg')


def pulse_envelope(bpm, seconds=40.0, offset=0.5):
    """Ideal onset envelope: a spike on every beat, a smaller one on every off-beat."""
    count = int(seconds * beats.FPS)
    env = [0.0] * count
    period = 60 / bpm
    t = offset
    while t + period / 2 < seconds - 0.1:
        env[int(round(t * beats.FPS))] = 1.0
        env[int(round((t + period / 2) * beats.FPS))] = 0.3
        t += period
    return env


def drum_track(path, bpm, seconds=30.0, rate=22050):
    """Kick on 1 and 3, snare on 2 and 4, hats on every eighth, over a quiet chord. Returns beat times."""
    rng = random.Random(0)
    period = 60 / bpm
    samples = [0.1 * math.sin(2 * math.pi * 220 * i / rate) + 0.07 * math.sin(2 * math.pi * 277 * i / rate)
               for i in range(int(rate * seconds))]
    times, t, k = [], 0.5, 0
    while t < seconds - 0.5:
        times.append(round(t, 4))
        start, length = int(t * rate), int(0.15 * rate)
        for n in range(length):
            tt = n / rate
            if k % 2 == 0:
                value = 0.8 * math.sin(2 * math.pi * (55 + 90 * math.exp(-tt * 30)) * tt) * math.exp(-tt * 22)
                value += 0.3 * rng.uniform(-1, 1) if n < 80 else 0.0
            else:
                value = (0.5 * rng.uniform(-1, 1) + 0.4 * math.sin(2 * math.pi * 190 * tt)) * math.exp(-tt * 25)
            if start + n < len(samples):
                samples[start + n] += value
        for half in (0.0, period / 2):
            begin = int((t + half) * rate)
            for n in range(int(0.03 * rate)):
                if begin + n < len(samples):
                    samples[begin + n] += 0.12 * rng.uniform(-1, 1) * math.exp(-n / rate * 80)
        t += period
        k += 1
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b''.join(int(max(-1.0, min(1.0, v)) * 32000).to_bytes(2, 'little', signed=True)
                                 for v in samples))
    return times


def f_measure(reference, estimated, window=0.07, skip=5.0):
    reference = [t for t in reference if t >= skip]
    estimated = [t for t in estimated if t >= skip]
    used, hits = set(), 0
    for t in estimated:
        match = next((i for i, r in enumerate(reference) if i not in used and abs(r - t) <= window), None)
        if match is not None:
            used.add(match)
            hits += 1
    if not hits:
        return 0.0
    precision, recall = hits / len(estimated), hits / len(reference)
    return 2 * precision * recall / (precision + recall)


class PureTests(unittest.TestCase):
    def test_parse_levels_handles_silence(self):
        text = 'frame:0 pts:0\nlavfi.astats.1.RMS_level=-20.5\nlavfi.astats.1.RMS_level=-inf\nlavfi.astats.1.RMS_level=nan\n'
        self.assertEqual(beats.parse_levels(text), [-20.5, beats.SILENCE_DB, beats.SILENCE_DB])

    def test_onset_envelope_counts_rises_in_every_band(self):
        quiet, loud = [-60.0] * 100, [-60.0] * 100
        loud[50] = -20.0
        env = beats.onset_envelope([quiet, loud, loud])
        self.assertEqual(len(env), 100)
        self.assertEqual(max(range(100), key=env.__getitem__), 50)
        self.assertTrue(all(value >= 0 for value in env))

    def test_tempo_prefers_the_beat_not_half_or_two_thirds(self):
        for bpm in (90, 100, 120, 128):
            found = 60 * beats.FPS / beats.tempo_period(pulse_envelope(bpm))
            self.assertAlmostEqual(found, bpm, delta=bpm * 0.03)

    def test_track_lands_on_beats_not_off_beats(self):
        env = pulse_envelope(120)
        frames = beats.track(env, beats.FPS / 2)
        times = [frame / beats.FPS for frame in frames]
        reference = [0.5 + k * 0.5 for k in range(80)]
        self.assertGreater(f_measure(reference, times, window=0.03), 0.95)

    def test_silence_and_short_audio_have_no_beats(self):
        self.assertEqual(beats.beats_from_bands([[beats.SILENCE_DB] * 2000] * 4), {'tempo': 0.0, 'beats': []})
        self.assertEqual(beats.beats_from_bands([[-20.0, -10.0]] * 4), {'tempo': 0.0, 'beats': []})

    def test_command_reads_only_what_compose_can_play(self):
        argv = beats.band_command('ffmpeg', '/a b.flac', beats.BANDS[0])
        self.assertEqual(argv[argv.index('-t') + 1], str(beats.ANALYSIS_SECONDS))
        self.assertLess(argv.index('-t'), argv.index('-i'))
        self.assertIn('asetnsamples=n=512', argv[argv.index('-af') + 1])


@unittest.skipUnless(FFMPEG, 'FFmpeg required')
class FfmpegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.tracks = {bpm: (cls.root / f'drums_{bpm}.wav', drum_track(cls.root / f'drums_{bpm}.wav', bpm))
                      for bpm in (90, 120)}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_synthetic_drums_give_tempo_and_beats(self):
        analyzer = beats.BeatAnalyzer()
        for bpm, (path, truth) in self.tracks.items():
            result = analyzer.analyze(path, f'd{bpm}')
            self.assertAlmostEqual(result['tempo'], bpm, delta=bpm * 0.03)
            self.assertGreater(f_measure(truth, result['beats']), 0.9, bpm)

    def test_results_are_cached_by_digest(self):
        calls = []

        class Counting(media.Runner):
            def run(self, command, **kwargs):
                calls.append(command)
                return super().run(command, **kwargs)

        analyzer = beats.BeatAnalyzer(runner=Counting())
        path = self.tracks[120][0]
        first = analyzer.analyze(path, 'same')
        self.assertEqual(analyzer.analyze(path, 'same'), first)
        self.assertEqual(len(calls), len(beats.BANDS))


class ServiceAndRouteTests(unittest.TestCase):
    def test_music_beats_resolves_the_music_source_and_uses_its_digest(self):
        seen = []

        class Resolver:
            def resolve(self, url='', asset_id=''):
                seen.append((url, asset_id))
                return Path('/music/song.flac')

        class Sources:
            def digest(self, path):
                return 'abc123'

        class Analyzer:
            def analyze(self, path, digest):
                seen.append((str(path), digest))
                return {'tempo': 120.0, 'beats': [0.5, 1.0]}

        with tempfile.TemporaryDirectory() as folder:
            service = ComposeService(store=ComposeStore(Path(folder)), sources=Sources(), audio_resolver=Resolver(),
                                     output_dir=lambda: Path(folder), write_sidecar=lambda *a, **k: None,
                                     beats=Analyzer())
            try:
                result = service.music_beats('/api/assets/audio/file?path=a.flac')
                with self.assertRaises(ValueError):
                    service.music_beats('', '')
            finally:
                service.close()
        self.assertEqual(result, {'tempo': 120.0, 'beats': [0.5, 1.0]})
        self.assertEqual(seen, [('/api/assets/audio/file?path=a.flac', ''), ('/music/song.flac', 'abc123')])

    def test_route(self):
        class Compose:
            def owns(self, ident):
                return False

            def music_beats(self, url, asset):
                return {'tempo': 100.0, 'beats': [1.0], 'url': url, 'asset': asset}

        class Handler:
            def __init__(self, path):
                self.path, self.headers, self.rfile = path, {}, io.BytesIO()

            def require_auth(self):
                return True

            def send_json(self, payload, status=200, headers=None):
                self.sent, self.status = payload, status

        handler = Handler('/api/video_edit/music_beats?asset_id=' + 'a' * 64 + '.wav')
        self.assertTrue(create_router(object(), Compose()).dispatch(handler, 'GET', '/api/video_edit/music_beats'))
        self.assertEqual((handler.status, handler.sent['asset']), (200, 'a' * 64 + '.wav'))
        self.assertNotIn('numpy', (Path(beats.__file__)).read_text(encoding='utf-8').split('"""', 2)[2])


if __name__ == '__main__':
    unittest.main()
