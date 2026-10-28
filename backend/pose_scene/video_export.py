"""Pose videos: frames rendered by the editor (fixed time steps, never MediaRecorder), encoded by ffmpeg.

A session receives frames 0..N-1 in order into data/pose/videos/<id>/, then a
background thread encodes H.264 (yuv420p, the sequence's own frame rate) into the image archive's date
folder with a JSON sidecar (pass, camera, frames, scene snapshot). Archive videos are served by the
authenticated /video/ route with byte ranges, so downstream video nodes accept them like any other
generated clip. Frames are deleted after encoding; unfinished sessions older than a day are swept.

Frames are normally `rgba`: the canvas's raw pixels, zlib-deflated by the browser's CompressionStream
(pose frames are mostly flat background: ~10-40 KB each, ~10 ms). Browser PNG/JPEG encoding took 1-7 s a
frame in the embedded browser, so encoding is left to ffmpeg, which reads the raw frames from a pipe.
PNG and JPEG frames are still accepted.
"""
import zlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from .contracts import MAX_EXPORT_SIDE, PASSES, identifier, png_size

MAX_FRAMES = 1800          # 60 s at 30 fps; recognition keeps 30 s
MAX_FRAME_BYTES = 12 * 1024 * 1024
STALE_SECONDS = 24 * 3600
FORMATS = {'rgba': '.rgba.z', 'png': '.png', 'jpeg': '.jpg'}
ACTIVE = {'receiving', 'encoding'}


def ffmpeg():
    path = os.pathsep.join([os.environ.get('PATH', ''), '/opt/homebrew/bin', '/usr/local/bin'])
    return shutil.which('ffmpeg', path=path)


def check_rgba(data, width, height):
    """Inflate a deflated RGBA frame without letting it grow past the expected size (no zip bombs)."""
    expected = width * height * 4
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(data, expected + 1)
    except zlib.error:
        raise ValueError('视频帧数据无法解压') from None
    if len(raw) != expected or inflater.unconsumed_tail:
        raise ValueError('视频帧尺寸与导出设置不一致')
    return raw


def frame_size(data, kind):
    if kind == 'png':
        return png_size(data)
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('视频帧必须为 JPEG')
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def normalize_start(body):
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    if set(body) - {'frames', 'fps', 'width', 'height', 'format', 'pass', 'camera', 'scene'}:
        raise ValueError('包含不支持的导出参数')
    frames, width, height = (body.get(k) for k in ('frames', 'width', 'height'))
    for value, name in ((frames, '帧数'), (width, '宽度'), (height, '高度')):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{name}无效')
    if not 2 <= frames <= MAX_FRAMES:
        raise ValueError(f'视频帧数须为 2–{MAX_FRAMES}')
    if not (16 <= width <= MAX_EXPORT_SIDE and 16 <= height <= MAX_EXPORT_SIDE) or width % 2 or height % 2:
        raise ValueError('视频尺寸须为 16–4096 的偶数')
    fps = body.get('fps')
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 1 <= fps <= 240:
        raise ValueError('帧率须为 1–240')
    kind = body.get('format', 'rgba')
    if kind not in FORMATS:
        raise ValueError('视频帧格式须为 RGBA、PNG 或 JPEG')
    pass_name = body.get('pass')
    if pass_name not in PASSES:
        raise ValueError('未知输出通道')
    scene = body.get('scene')
    if scene is not None and (not isinstance(scene, dict) or len(json.dumps(scene)) > 512 * 1024):
        raise ValueError('场景快照无效或过大')
    return {'frames': frames, 'fps': round(float(fps), 4), 'width': width, 'height': height, 'format': kind,
            'pass': pass_name, 'camera': str(body.get('camera') or '')[:32], 'scene': scene}


class VideoExports:
    def __init__(self, root, output_dir):
        """output_dir(): today's archive folder (storage_paths.daily_output_dir), injected by server.py."""
        self.root, self.output_dir = Path(root), output_dir
        self._lock = threading.Lock()
        self._processes = {}

    # ---- state ---------------------------------------------------------------
    def _dir(self, ident):
        return self.root / identifier(ident)

    def _read(self, ident):
        path = self._dir(ident) / 'meta.json'  # invalid ids raise ValueError here, before the lookup
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            raise FileNotFoundError('视频导出不存在') from None

    def _write(self, ident, meta):
        path = self._dir(ident) / 'meta.json'
        pending = path.with_suffix('.json.writing')
        pending.write_text(json.dumps(meta, ensure_ascii=False))
        os.replace(pending, path)
        return meta

    def _sweep(self):
        if not self.root.is_dir():
            return
        now = time.time()
        for folder in self.root.iterdir():
            try:
                stale = folder.is_dir() and not folder.is_symlink() and now - folder.stat().st_mtime > STALE_SECONDS
            except OSError:
                continue
            if stale:
                shutil.rmtree(folder, ignore_errors=True)

    @staticmethod
    def public(meta):
        keys = ('id', 'status', 'stage', 'frames', 'received', 'fps', 'width', 'height', 'pass', 'url', 'error', 'file_size')
        return {k: meta[k] for k in keys if k in meta}

    # ---- protocol ------------------------------------------------------------
    def start(self, body):
        spec = normalize_start(body)
        if not ffmpeg():
            raise RuntimeError('未找到 ffmpeg，请先安装（brew install ffmpeg）')
        self._sweep()
        ident = uuid.uuid4().hex
        (self._dir(ident) / 'frames').mkdir(parents=True)
        meta = {'id': ident, 'status': 'receiving', 'stage': '接收帧', 'received': 0, 'created_at': time.time(), **spec}
        return self.public(self._write(ident, meta))

    def frame(self, ident, index, data):
        with self._lock:
            meta = self._read(ident)
            if meta['status'] != 'receiving':
                raise ValueError('该导出已不再接收帧')
            if index != meta['received']:
                raise ValueError(f'帧顺序错误：应为第 {meta["received"]} 帧')
            if not 0 < len(data) <= MAX_FRAME_BYTES:
                raise ValueError('视频帧为空或过大')
            if meta['format'] == 'rgba':
                check_rgba(data, meta['width'], meta['height'])
            elif tuple(frame_size(data, meta['format'])) != (meta['width'], meta['height']):
                raise ValueError('视频帧尺寸与导出设置不一致')
            path = self._dir(ident) / 'frames' / f'{index:05d}{FORMATS[meta["format"]]}'
            pending = path.with_name(path.name + '.writing')
            pending.write_bytes(data)
            os.replace(pending, path)
            meta['received'] = index + 1
            return self.public(self._write(ident, meta))

    def finish(self, ident):
        with self._lock:
            meta = self._read(ident)
            if meta['status'] != 'receiving':
                return self.public(meta)
            if meta['received'] != meta['frames']:
                raise ValueError(f'还缺 {meta["frames"] - meta["received"]} 帧')
            meta.update(status='encoding', stage='编码视频')
            self._write(ident, meta)
        threading.Thread(target=self._encode, args=(ident,), name=f'pose-video-{ident[:8]}', daemon=True).start()
        return self.public(meta)

    def cancel(self, ident):
        with self._lock:
            meta = self._read(ident)
            if meta['status'] not in ACTIVE:
                return self.public(meta)
            meta.update(status='cancelled', stage='已取消')
            self._write(ident, meta)
            process = self._processes.get(ident)
        if process:
            process.kill()
        shutil.rmtree(self._dir(ident) / 'frames', ignore_errors=True)
        return self.public(meta)

    def job(self, ident):
        return self.public(self._read(ident))

    def _encode(self, ident):
        meta = self._read(ident)
        folder = self._dir(ident)
        output = folder / 'video.mp4'
        raw = meta['format'] == 'rgba'
        source = (['-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{meta["width"]}x{meta["height"]}', '-framerate', f'{meta["fps"]:g}', '-i', 'pipe:0']
                  if raw else ['-framerate', f'{meta["fps"]:g}', '-start_number', '0', '-i', str(folder / 'frames' / f'%05d{FORMATS[meta["format"]]}')])
        command = [ffmpeg(), '-v', 'error', '-y', *source, '-c:v', 'libx264', '-preset', 'medium',
                   '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)]
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE if raw else subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            with self._lock:
                self._processes[ident] = process
            if raw:
                try:
                    for index in range(meta['frames']):
                        process.stdin.write(zlib.decompress((folder / 'frames' / f'{index:05d}.rgba.z').read_bytes()))
                except BrokenPipeError:
                    pass  # ffmpeg stopped (cancelled or failed); its exit code and stderr say why
                finally:
                    process.stdin.close()
            _, error = process.communicate(timeout=120 + meta['frames'] // 5)
            error = (error or b'').decode(errors='replace')
            if self._read(ident)['status'] == 'cancelled':
                return
            if process.returncode or not output.is_file():
                raise RuntimeError((error or 'ffmpeg 编码失败').strip()[-600:])
            day = Path(self.output_dir())
            day.mkdir(parents=True, exist_ok=True)
            name = f'pose_{meta["pass"]}_{time.strftime("%H%M%S")}_{ident[:8]}.mp4'
            target = day / name
            shutil.move(str(output), target)
            sidecar = {k: meta[k] for k in ('pass', 'camera', 'frames', 'fps', 'width', 'height', 'scene')}
            target.with_suffix('.json').write_text(json.dumps({'kind': 'pose_video', 'created_at': time.time(), **sidecar}, ensure_ascii=False))
            with self._lock:
                meta = self._read(ident)
                meta.update(status='succeeded', stage='导出完成', url='/video/' + name, file_size=target.stat().st_size)
                self._write(ident, meta)
        except subprocess.TimeoutExpired:
            process.kill()
            self._fail(ident, 'ffmpeg 编码超时')
        except Exception as exc:  # report, never leave the session hanging in "encoding"
            self._fail(ident, str(exc) or type(exc).__name__)
        finally:
            with self._lock:
                self._processes.pop(ident, None)
            shutil.rmtree(folder / 'frames', ignore_errors=True)

    def _fail(self, ident, error):
        with self._lock:
            meta = self._read(ident)
            if meta['status'] != 'cancelled':
                meta.update(status='failed', stage='导出失败', error=error[:600])
                self._write(ident, meta)
