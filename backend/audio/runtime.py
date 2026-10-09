"""Pinned offline CLI adapter. The HTTP process never imports MLX or model dependencies."""
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import threading
import time

from .contracts import REVISION
from .environment import read_receipt, ready, remove_finder_metadata, shared_python
from .progress import parse_progress_line


def worker_path():
    # launchd/Finder do not load shell profiles. Reuse the system FFmpeg without
    # installing a bundled copy or changing the parent/image process environment.
    return os.pathsep.join(filter(None, (os.environ.get('PATH', ''), '/opt/homebrew/bin', '/usr/local/bin')))


class Runtime:
    def __init__(self, component, before_load=None):
        self.before_load = before_load
        self.root = Path(component)
        self.source = self.root / 'source'
        self.python = shared_python(read_receipt(self.root))
        self.models = self.root / 'models'
        self._environment_check = (None, 0, False)

    def status(self):
        supported = platform.system() == 'Darwin' and platform.machine() == 'arm64'
        receipt = read_receipt(self.root)
        key = (str(self.python), json.dumps(receipt, sort_keys=True))
        previous, checked, environment = self._environment_check
        if key != previous or time.monotonic() - checked > 30:
            environment = ready(self.python, receipt) and self.source.is_dir()
            self._environment_check = (key, time.monotonic(), environment)
        generator = all((self.models / 'generator' / f).is_file() for f in
                        ('conversion.json', 'config.json', 'ar-8bit.safetensors', 'ar-bf16.safetensors',
                         'nar-bf16.safetensors', 'qwen.tiktoken'))
        vae = all((self.models / 'vae' / f).is_file() for f in ('config.json', 'model.safetensors'))
        transcription = all((self.models / d / f).is_file() for d in ('transcription', 'mert') for f in ('config.json', 'model.safetensors'))
        ffmpeg = bool(shutil.which('ffmpeg', path=worker_path()))
        reasons = []
        if not supported: reasons.append('MLX 推理需要 Apple Silicon macOS')
        if not environment: reasons.append('主 Python 3.14 环境的音频依赖未安装或与安装记录不符')
        if not generator or not vae: reasons.append('歌曲模型未安装')
        if not transcription: reasons.append('转谱模型未安装')
        if not ffmpeg: reasons.append('转谱需要 ffmpeg')
        return dict(engine='mlx-Yue', revision=REVISION, environment_ready=environment,
                    generation_ready=supported and environment and generator and vae,
                    transcription_ready=supported and environment and transcription and ffmpeg,
                    precision=['8bit', 'bf16'], reasons=reasons,
                    install_command='.venv/bin/python -m backend.audio.install', offline=True)

    def command(self, spec, directory, asset=None):
        if self.python is None:
            raise RuntimeError('未配置可执行音频任务的共享 Python 环境')
        base = [str(self.python), '-u', str(Path(__file__).with_name('worker.py'))]
        if spec['operation'] == 'generate':
            base += ['--audio-format', spec.get('audio_format', 'flac')]
        base.append(str(os.getpid()))
        output = directory / 'result'
        if spec['operation'] == 'transcribe':
            return base + ['transcribe', str(asset), '--output', str(output), '--offline',
                           '--model', str(self.models / 'transcription'), '--base-model', str(self.models / 'mert'),
                           '--cache-dir', str(self.root / 'cache'), '--task', spec['task'], '--preset', spec['preset'],
                           '--max-seconds', str(spec['max_seconds']), '--memory-budget-gib', '24']
        request = directory / 'submitted-request.json'
        request.write_text(json.dumps(spec['request'], ensure_ascii=False, indent=2), encoding='utf-8')
        return base + [spec['operation'], str(request), '--output', str(output), '--offline',
                       '--model', str(self.models / 'generator'), '--vae', str(self.models / 'vae'),
                       '--precision', spec['precision'], '--memory-budget-gib', '16']

    def execute(self, spec, directory, asset, cancelled, progress):
        from ..runtime_resources import local_accelerator
        # Finder can recreate .DS_Store after the operator opens a model folder.
        # YuE2 treats every unlisted file as a conversion-integrity failure, so
        # remove only this known macOS metadata before starting the worker.
        remove_finder_metadata(self.models)
        with local_accelerator(self.root.parent / '.local-inference.lock', cancelled, progress):
            if cancelled.is_set(): return 'cancelled', ''
            if self.before_load:
                self.before_load()
            return self._execute(spec, directory, asset, cancelled, progress)

    def _execute(self, spec, directory, asset, cancelled, progress):
        command = self.command(spec, directory, asset)
        # Audio worker only, before MLX/Metal initialization. Mitigates the OS
        # interactivity abort (ml-explore/mlx#3267); never mutate the server env.
        env = {**os.environ, 'PATH': worker_path(), 'HF_HUB_OFFLINE': '1',
               'HF_HOME': str(self.root / 'cache'), 'PYTHONUNBUFFERED': '1',
               'MLX_ENABLE_TF32': '0', 'AGX_RELAX_CDM_CTXSTORE_TIMEOUT': '1'}
        process = subprocess.Popen(command, cwd=self.source, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        done = threading.Event()
        def watchdog():
            deadline = time.monotonic() + 7200
            while not done.wait(.2):
                if cancelled.is_set() or time.monotonic() > deadline:
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: return
                    if not done.wait(3):
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    return
        thread = threading.Thread(target=watchdog, daemon=True)
        thread.start()
        tail = []
        try:
            with (directory / 'runtime.log').open('wb') as log:
                written = 0
                for raw in iter(lambda: process.stdout.readline(65536), b''):
                    if written < 8 * 1024 * 1024:
                        log.write(raw); written += len(raw)
                    line = raw.decode('utf-8', 'replace').strip()
                    tail = (tail + [line])[-8:]
                    event = parse_progress_line(line)
                    if event:
                        progress(event)
            code = process.wait()
        finally:
            done.set()
            process.stdout.close()
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
            thread.join(timeout=4)
        if cancelled.is_set():
            return 'cancelled', ''
        result_file = directory / 'result' / ('plan.json' if spec['operation'] == 'plan' else 'result.json')
        result = json.loads(result_file.read_text()) if result_file.is_file() else {}
        truncated = result.get('truncated')
        if isinstance(truncated, dict): truncated = any(truncated.values())
        if code != 0 and not (code == 1 and truncated):
            return 'failed', '\n'.join(tail)[-2000:] or f'音频进程退出码 {code}'
        expected = 'score.abc' if spec['operation'] in ('plan', 'transcribe') else f"audio.{spec.get('audio_format', 'flac')}"
        if not list((directory / 'result').rglob(expected)):
            return 'failed', '引擎未生成预期产物，请查看运行日志'
        return ('partial' if truncated else 'succeeded'), ''
