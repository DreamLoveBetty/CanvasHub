"""Audio-only Metal compatibility environment, using a synthetic child process."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend.audio.runtime import Runtime


class AudioWorkerEnvironmentTests(unittest.TestCase):
    def check_child_environment(self, inherited):
        key = 'AGX_RELAX_CDM_CTXSTORE_TIMEOUT'
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            if inherited is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = inherited
            os.environ['MLX_ENABLE_TF32'] = '1'
            before = dict(os.environ)
            directory = Path(tmp)
            runtime = Runtime(directory)
            runtime.source = directory
            program = (
                "import json, os; from pathlib import Path; "
                "keys=('AGX_RELAX_CDM_CTXSTORE_TIMEOUT','MLX_ENABLE_TF32','HF_HUB_OFFLINE'); "
                "Path('child.json').write_text(json.dumps({k:os.environ.get(k) for k in keys})); "
                "p=Path('result'); p.mkdir(); (p/'audio.flac').write_bytes(b'fLaCfixture')"
            )
            runtime.command = lambda *args: [sys.executable, '-u', '-c', program]
            spec = {'operation': 'generate', 'precision': '8bit', 'audio_format': 'flac',
                    'request': {'style': 'pop', 'lyrics': 'synthetic', 'seed': 831001,
                                'generation_config': {'ode_steps': 8}}}
            original = copy.deepcopy(spec)
            result = runtime.execute(spec, directory, None, threading.Event(), lambda event: None)
            self.assertEqual(result, ('succeeded', ''))
            self.assertEqual(json.loads((directory / 'child.json').read_text()), {
                key: '1', 'MLX_ENABLE_TF32': '0', 'HF_HUB_OFFLINE': '1',
            })
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(spec, original)

    def test_worker_removes_only_finder_metadata_from_known_model_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runtime = Runtime(directory)
            runtime.source = directory
            for name in ('generator', 'vae', 'transcription', 'mert'):
                model = directory / 'models' / name
                (model / 'nested').mkdir(parents=True)
                (model / '.DS_Store').write_bytes(b'finder')
                (model / 'nested' / '.DS_Store').write_bytes(b'finder')
                (model / '.keep').write_bytes(b'model metadata')
            unrelated = directory / 'models' / 'unrelated'
            unrelated.mkdir(parents=True)
            (unrelated / '.DS_Store').write_bytes(b'outside allowlist')
            program = (
                "from pathlib import Path; "
                "p=Path('result'); p.mkdir(); (p/'audio.flac').write_bytes(b'fLaCfixture')"
            )
            runtime.command = lambda *args: [sys.executable, '-u', '-c', program]
            spec = {'operation': 'generate', 'precision': '8bit', 'audio_format': 'flac',
                    'request': {'style': 'pop', 'lyrics': 'synthetic', 'seed': 831001,
                                'generation_config': {'ode_steps': 8}}}

            result = runtime.execute(spec, directory, None, threading.Event(), lambda event: None)

            self.assertEqual(result, ('succeeded', ''))
            for name in ('generator', 'vae', 'transcription', 'mert'):
                model = directory / 'models' / name
                self.assertFalse((model / '.DS_Store').exists())
                self.assertFalse((model / 'nested' / '.DS_Store').exists())
                self.assertTrue((model / '.keep').is_file())
            self.assertTrue((unrelated / '.DS_Store').is_file())

    def test_audio_child_gets_compatibility_without_mutating_parent(self):
        self.check_child_environment(None)

    def test_audio_override_leaves_parent_and_other_workers_unchanged(self):
        self.check_child_environment('0')


if __name__ == '__main__':
    unittest.main()
