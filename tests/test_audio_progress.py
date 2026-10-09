"""Audio progress is observational, bounded, and independent of MLX/providers."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from backend.audio.progress import normalize_progress, parse_progress_line
from backend.audio.runtime import Runtime
from backend.audio.service import AudioService


class AudioProgressTests(unittest.TestCase):
    def test_unknown_token_total_stays_unknown(self):
        event = parse_progress_line('[YuE2] Running Generating song: 712 tokens | 71.1 tokens/s | elapsed 10.0s')
        self.assertEqual(event, {'stage': 'Generating song', 'phase_status': 'running', 'tokens': 712, 'completed': 712, 'unit': 'tokens'})
        self.assertNotIn('total', event)
        self.assertNotIn('percent', event)

    def test_known_steps_and_chunks_are_stage_counts(self):
        for unit in ('steps', 'chunks'):
            event = parse_progress_line(f'[YuE2] Running Synthesizing audio: 4/8 {unit} (50%) | elapsed 2.5s')
            self.assertEqual((event['completed'], event['total'], event['unit']), (4, 8, unit))
        # An exceeded count must remain honest, not silently report 100%.
        self.assertEqual(parse_progress_line('[YuE2] Running Decoding audio: 9/8 chunks (112%) | elapsed 2.0s')['completed'], 9)

    def test_terminal_phase_is_not_terminal_job(self):
        for prefix, state in [('Completed', 'completed'), ('Failed', 'failed'), ('Cancelled', 'cancelled'), ('Finished (generation limit reached)', 'truncated')]:
            event = parse_progress_line(f'[YuE2] {prefix} Planning score: 300 tokens | 10.0 tokens/s | elapsed 30.0s')
            self.assertEqual(event['phase_status'], state)
            self.assertNotIn('status', event)
        self.assertEqual(parse_progress_line('[YuE2] Starting Verifying model files: elapsed 0.0s')['stage'], 'Verifying model files')

    def test_json_transcription_is_preserved_and_private_fields_dropped(self):
        event = parse_progress_line(json.dumps({'stage': 'encoding', 'window': 1, 'windows': 3, 'secret': 'fixture', 'percent': 55}))
        self.assertEqual(event, {'stage': 'encoding', 'window': 1, 'windows': 3})

    def test_malformed_and_unbounded_events(self):
        for line in ('', 'ordinary log', '[YuE2] Completed: 35.0s audio in 20.0s', '{}', '[]', '{"stage": 23}', 'x' * 5000):
            self.assertIsNone(parse_progress_line(line))
        self.assertEqual(normalize_progress({'stage': 'test', 'total': True, 'completed': -1, 'tokens': 10**15, 'unit': 'bad', 'phase_status': 'bad'}), {'stage': 'test'})

    def test_real_pipe_output_is_adapted_without_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runtime = Runtime(directory)
            runtime.source = directory
            program = "from pathlib import Path; print('[YuE2] Running Synthesizing audio: 4/8 steps (50%) | elapsed 2.0s'); p=Path('result'); p.mkdir(); (p/'audio.flac').write_bytes(b'fLaCfixture')"
            runtime.command = lambda *args: [sys.executable, '-u', '-c', program]
            events = []
            self.assertEqual(runtime.execute({'operation': 'generate'}, directory, None, threading.Event(), events.append), ('succeeded', ''))
            self.assertEqual(events[0]['completed'], 4)
            self.assertEqual(events[0]['total'], 8)

    def test_service_receipt_keeps_new_observations_only(self):
        class FakeRuntime:
            def status(self):
                return {'generation_ready': True, 'reasons': []}
            def execute(self, spec, directory, asset, cancelled, progress):
                progress({'stage': 'Synthesizing audio', 'completed': 4, 'total': 8, 'unit': 'steps', 'phase_status': 'running', 'secret': 'fixture'})
                return 'succeeded', ''
        with tempfile.TemporaryDirectory() as tmp:
            service = AudioService(tmp, FakeRuntime())
            try:
                job = service.submit({'request': {'style': 'pop', 'lyrics': 'synthetic'}})
                for _ in range(100):
                    receipt = service.store.get(job['id'])
                    if receipt['status'] == 'succeeded':
                        break
                    time.sleep(.01)
                self.assertEqual(receipt['status'], 'succeeded')
                self.assertEqual(receipt['progress']['total'], 8)
                self.assertEqual(receipt['progress']['unit'], 'steps')
                self.assertNotIn('secret', receipt['progress'])
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
