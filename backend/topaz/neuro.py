"""Bundled Wonder one-shot runner. Child of the same supervised task process group."""
import json
import os
from pathlib import Path
import re
import subprocess

RUNNER_SHA256 = '8a0751efa21995c98f9e8af2e50e5f81b084f358489f0f3977e766d894c8c9d7'
MANIFEST_SHA256 = '0941c4a4bd42aa013f8f2b831f47f33a4984049c1461eec5f2a864579887ac49'


def runner_path(app):
    return Path(app) / 'MacOS/neuroserver/neuroserver/neuroserver'


def check_runtime(app):
    try:
        from .catalog import _digest
    except ImportError:
        from catalog import _digest
    for path, expected in ((runner_path(app), RUNNER_SHA256),
        (Path(app) / 'Resources/neuroserver/version.json', MANIFEST_SHA256)):
        if not path.is_file(): return 'Topaz Wonder 本地运行器未安装'
        stat = path.stat()
        if _digest(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            return 'Topaz Wonder 运行器版本已变化，需要重新验证'
    return ''


def phase_event(line):
    # These are real runner phase boundaries, not estimated completion timers.
    for marker, percent, label in (
        ('Phase 1:', 10, 'Wonder · 编码'), ('Phase 2:', 25, 'Wonder · 增强推理'),
        ('Phase 3:', 75, 'Wonder · 解码'), ('Phase 4:', 90, 'Wonder · 后处理')):
        if marker in line: return dict(event='progress', percent=percent, stage=label)
    return None


def run(app, source, output, spec, size, out_size, work, report):
    try:
        from .native import sanitize
    except ImportError:
        from native import sanitize
    error = check_runtime(app)
    if error: raise RuntimeError(error)
    runner = runner_path(app)
    env = os.environ.copy()
    env.update(TOPAZ_RUNNER_DIR=str(runner.parent),
               TOPAZ_MODEL_STORE=str(Path(app) / 'Resources/models/neuroserver'),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               HF_HOME=str(work / 'hf-cache'), XDG_CACHE_HOME=str(work / 'cache'), PYTHONUNBUFFERED='1')
    command = [str(runner), '--once', '--input-path', str(source), '--output-path', str(output),
        '--input-width', str(size[0]), '--input-height', str(size[1]),
        '--output-width', str(out_size[0]), '--output-height', str(out_size[1]),
        '--output-codec', 'tiff', '--output-bit-depth', '8', '--filters', json.dumps([spec])]
    # No new session: Runtime cancellation and parent watcher terminate runner too.
    process = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    success, identified = False, False
    try:
        for line in process.stdout:
            line = sanitize(line.rstrip())
            if re.search(r'Bearer\s|(?:access_token|refresh_token|api_key|password)\s*[=:]', line, re.I):
                line = '[credential-bearing diagnostic omitted]'
            report(dict(event='log', message=line))
            if re.search(r'Getting model for request: ' + re.escape(spec['model']) + r'(?:,|$)', line): identified = True
            if 'single_shot_process status: TopServingErrorCode.OK' in line: success = True
            event = phase_event(line)
            if event: report(event)
        code = process.wait()
        if code or not success or not identified or not output.is_file():
            raise RuntimeError(f"Wonder 本地处理未成功（退出码 {code}），请查看任务日志")
        report(dict(event='progress', percent=100, stage='Wonder · 完成'))
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        process.stdout.close()
