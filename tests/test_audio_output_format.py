"""Portable export-contract tests; no installed MLX, models or running services."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from backend.audio.contracts import normalize_job
from backend.audio.runtime import Runtime
from backend.audio.worker import export_wav, run_cli


class AudioFormatTests(unittest.TestCase):
    def request(self, **kwargs):
        return normalize_job({'request': {'style': 'pop', 'lyrics': 'synthetic lyric'}, **kwargs})

    def test_default_and_explicit_formats(self):
        self.assertEqual(self.request()['audio_format'], 'flac')
        for fmt in ('flac', 'wav'):
            spec = self.request(audio_format=fmt)
            self.assertEqual(spec['audio_format'], fmt)
            self.assertNotIn('audio_format', spec['request'])

    def test_invalid_format_rejected(self):
        for value in ('mp3', 'WAV', '', None, {}, ['wav'], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request(audio_format=value)

    def test_non_song_operations_do_not_export_audio(self):
        self.assertNotIn('audio_format', self.request(operation='plan', audio_format='wav'))
        spec = normalize_job({'operation': 'transcribe', 'asset_id': 'a' * 64 + '.wav'})
        self.assertNotIn('audio_format', spec)

    def test_worker_command_keeps_export_out_of_upstream_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for fmt in ('wav', 'flac'):
                command = Runtime(directory).command(self.request(audio_format=fmt), directory)
                self.assertEqual(command[3:5], ['--audio-format', fmt])
                self.assertIn('generate', command)
                self.assertNotIn('audio_format', json.loads((directory / 'submitted-request.json').read_text()))

    def test_worker_dispatch_exports_only_requested_song(self):
        package, cli = ModuleType('lyra'), ModuleType('lyra.cli')
        cli.main = MagicMock(return_value=0)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {'lyra': package, 'lyra.cli': cli}), patch('backend.audio.worker.export_wav') as export:
            directory = Path(tmp)
            (directory / 'audio.flac').write_bytes(b'fLaC')
            for op, fmt, expected in [('generate', 'wav', 1), ('generate', 'flac', 0), ('plan', 'wav', 0), ('transcribe', 'wav', 0)]:
                export.reset_mock()
                args = [op, 'request.json', '--output', tmp]
                self.assertEqual(run_cli(args, fmt), 0)
                cli.main.assert_called_with(args)
                self.assertEqual(export.call_count, expected)
            cli.main.return_value = 2
            export.reset_mock()
            self.assertEqual(run_cli(['generate', '--output', tmp], 'wav'), 2)
            export.assert_not_called()

    def test_export_bounded_and_atomic_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            original = directory / 'audio.flac'
            original.write_bytes(b'original fixture')
            sf = MagicMock()
            source = sf.SoundFile.return_value.__enter__.return_value
            source.samplerate, source.channels = 48000, 2
            source.blocks.return_value = iter([b'chunk1', b'chunk2'])
            # A fake soundfile writer exercises the real atomic path operations.
            def open_file(path, *args, **kwargs):
                if args:
                    Path(path).write_bytes(b'RIFFfixture')
                return sf.SoundFile.return_value
            sf.SoundFile.side_effect = open_file
            with patch.dict(sys.modules, {'soundfile': sf}):
                export_wav(directory)
            source.blocks.assert_called_once_with(blocksize=65536, dtype='int32', always_2d=True)
            source.write.assert_any_call(b'chunk1')
            source.write.assert_any_call(b'chunk2')
            self.assertEqual(sf.SoundFile.call_args.kwargs['subtype'], 'PCM_24')
            self.assertEqual((directory / 'audio.wav').read_bytes(), b'RIFFfixture')
            self.assertEqual(original.read_bytes(), b'original fixture')
            self.assertFalse((directory / '.audio.wav.tmp').exists())

    def test_export_failure_never_publishes_partial_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            sf = MagicMock()
            def fail(*args, **kwargs):
                (directory / '.audio.wav.tmp').write_bytes(b'partial')
                raise RuntimeError('synthetic disk error')
            sf.SoundFile.side_effect = fail
            with patch.dict(sys.modules, {'soundfile': sf}), self.assertRaisesRegex(RuntimeError, 'disk error'):
                export_wav(directory)
            self.assertFalse((directory / 'audio.wav').exists())
            self.assertFalse((directory / '.audio.wav.tmp').exists())

    def test_runtime_requires_selected_artifact_and_keeps_partial_semantics(self):
        for files, truncated, expected in [(['flac'], False, 'failed'), (['flac', 'wav'], False, 'succeeded'), (['flac', 'wav'], True, 'partial')]:
            with self.subTest(files=files, truncated=truncated), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                runtime = Runtime(directory)
                runtime.source = directory
                script = "from pathlib import Path; import json; p=Path('result'); p.mkdir();"
                script += ';'.join(f"(p/'audio.{fmt}').write_bytes(b'fixture')" for fmt in files)
                script += f";(p/'result.json').write_text(json.dumps({{'truncated': {truncated!r}}}));raise SystemExit({int(truncated)})"
                runtime.command = lambda *args: [sys.executable, '-c', script]
                status, _ = runtime.execute({'operation': 'generate', 'audio_format': 'wav'}, directory, None, threading.Event(), lambda e: None)
                self.assertEqual(status, expected)


if __name__ == '__main__':
    unittest.main()
