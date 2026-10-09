"""Cancellable native worker supervisor; task state remains in the existing store."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from .catalog import MODELS, capabilities
from .native import sanitize
from .parameters import normalize
from ..runtime_resources import local_accelerator


class TopazError(RuntimeError):
    pass


class TopazCancelled(TopazError):
    pass


@dataclass(frozen=True)
class Result:
    input_width: int
    input_height: int
    output_width: int
    output_height: int
    scale: float
    model: str
    device: str


class CancelPort:
    def __init__(self, callback): self.callback = callback
    def is_set(self): return bool(self.callback())
    def wait(self, timeout):
        time.sleep(timeout)
        return self.is_set()


def stop_process(process):
    if process.poll() is not None:
        return
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait(timeout=5)


class Runtime:
    def __init__(self, root, app=None, timeout=1800, before_load=None):
        self.before_load = before_load
        self.root = Path(root).expanduser().resolve()
        # Explicit app= is retained only for isolated probes and portable tests.
        # Production resolves exclusively inside the persistent app-data root.
        self.app = Path(app).expanduser().resolve() if app is not None else self.root / 'vendor' / 'Contents'
        self.timeout = timeout

    def catalog(self): return capabilities(self.app)

    def _models(self):
        # No cache symlinks: compiled CoreML files are owned by CanvasHub, not App.
        destination = self.root / 'models'
        destination.mkdir(parents=True, exist_ok=True)
        source_root = self.app / 'Resources/models'
        if not source_root.is_dir():
            raise TopazError('Topaz 自有 runtime 模型目录不存在，请重新导入运行资源')
        allowed = lambda name: Path(name).suffix.lower() in ('.json', '.tz', '.bin') or name in ('rxl_vocab.txt', 'rxl_merges.txt', 'neg_emb.yaml')
        # Preserve local CoreML cache while removing the old generated links
        # into /Applications. Never retain a model fallback to the vendor App.
        for target in destination.iterdir():
            if target.is_symlink() and allowed(target.name):
                expected = source_root / target.name
                if target.resolve(strict=False) != expected.resolve(strict=False):
                    target.unlink()
        for source in source_root.iterdir():
            target = destination / source.name
            # Redefine's embed model declares these exact auxiliary nets in
            # rxl_embed.json. Do not broaden this to arbitrary .txt/.yaml files
            # (or copy license/config material from the installed app).
            if source.is_file() and allowed(source.name) and not target.exists():
                target.symlink_to(source)
        return destination

    def execute(self, source, output, *, model, options=None, cancelled=lambda: False, progress=None):
        options = normalize(options)
        if model not in MODELS:
            raise TopazError('不支持的 Topaz 模型')
        entry = next(item for item in self.catalog() if item['id'] == model)
        if not entry['available']:
            raise TopazError(entry['error'])
        progress = progress or (lambda ratio, text: None)
        port = CancelPort(cancelled)
        with local_accelerator(self.root.parent / '.local-inference.lock', port,
                               lambda event: progress(0, '等待本地推理资源')):
            if cancelled(): raise TopazCancelled('任务已取消')
            if self.before_load:
                self.before_load()
            return self._execute(Path(source), Path(output), model, cancelled, progress, options)

    def _execute(self, source, output, model, cancelled, progress, options):
        models = self._models()
        work = self.root / 'jobs' / uuid.uuid4().hex
        work.mkdir(parents=True)
        (work / 'options.json').write_text(json.dumps(options), encoding='utf-8')
        for name in ('home', 'tmp'):
            (work / name).mkdir()
        env = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}
        env.update(HOME=str(work / 'home'), TMPDIR=str(work / 'tmp') + '/',
                   DYLD_LIBRARY_PATH=str(self.app / 'Frameworks'), PYTHONUNBUFFERED='1')
        command = [sys.executable, '-u', str(Path(__file__).with_name('worker.py')),
                   str(os.getpid()), str(self.app), str(models), str(source), str(work), model]
        progress(.08, '正在载入 Topaz 原生模型')
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        done = threading.Event()
        expired = threading.Event()
        def monitor():
            deadline = time.monotonic() + self.timeout
            while not done.wait(.1):
                if cancelled() or time.monotonic() >= deadline:
                    if not cancelled(): expired.set()
                    stop_process(process)
                    return
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        result = None
        error = ''
        last_percent = -1
        try:
            with (work / 'runtime.log').open('w', encoding='utf-8') as log:
                written = 0
                for raw in iter(lambda: process.stdout.readline(16384), b''):
                    line = sanitize(raw.decode('utf-8', 'replace'))
                    if written < 4 * 1024 * 1024:
                        log.write(line + '\n'); written += len(line.encode('utf-8'))
                    if not line.startswith('TOPAZ_EVENT '): continue
                    try: event = json.loads(line[len('TOPAZ_EVENT '):])
                    except ValueError: continue
                    if event.get('event') == 'log' and 'Waiting for download of' in str(event.get('message', '')):
                        raise TopazError('Topaz 自有 runtime 缺少模型，已停止自动下载；请重新导入已验证运行资源')
                    if event.get('event') == 'progress' and not cancelled():
                        percent = max(0, min(100, int(event.get('percent', 0))))
                        if percent > last_percent:
                            last_percent = percent
                            progress(.08 + percent / 100 * .84, event.get('stage') or f'Topaz 推理 {percent}%')
                    elif event.get('event') == 'result': result = event
                    elif event.get('event') == 'error': error = str(event.get('message', ''))
            code = process.wait()
            if cancelled(): raise TopazCancelled('任务已取消')
            if expired.is_set(): raise TopazError('Topaz 处理超过时限，已终止推理')
            if code or not result or not (work / ('result.' + options['output_format'])).is_file():
                raise TopazError(error or f'Topaz 推理进程异常退出：{code}')
            metadata = Result(**{key: result[key] for key in Result.__dataclass_fields__})
            progress(.94, '正在保存 Topaz 高清结果')
            if cancelled(): raise TopazCancelled('任务已取消')
            output.parent.mkdir(parents=True, exist_ok=True)
            # Archive may live on another volume: copy through a same-directory temp.
            import shutil
            temporary = output.with_name(output.name + '.topaz-tmp')
            try:
                shutil.copyfile(work / ('result.' + options['output_format']), temporary)
                if cancelled(): raise TopazCancelled('任务已取消')
                os.replace(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)
            (work / 'result.json').write_text(json.dumps(result), encoding='utf-8')
            return metadata
        finally:
            done.set()
            stop_process(process)
            process.stdout.close()
            watcher.join(timeout=5)
            for name in ('input.bmp', 'output.bmp', 'input.png', 'output.tiff', 'result.tmp', 'result.' + options['output_format']):
                (work / name).unlink(missing_ok=True)
