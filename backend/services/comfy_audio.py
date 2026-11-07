"""ComfyUI audio sources: canvas audio nodes feeding `[参考音频N]` LoadAudio slots.

Audio is uploaded into ComfyUI's input folder through /upload/image (it stores any file type and
is what LoadAudio reads from). The container is sniffed from the file header, never the client name.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

MAX_AUDIOS = 4
MAX_AUDIO_UPLOAD = 50 * 1024 * 1024
AUDIO_MIME_TYPES = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.flac': 'audio/flac', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4'}
AUDIO_SUFFIXES = frozenset(AUDIO_MIME_TYPES)
_INPUT_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$')


def audio_suffix(data):
    """MP3 (ID3 tag or MPEG frame sync), WAV, FLAC, Ogg or MP4 audio, from the file header."""
    if data[:3] == b'ID3' or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return '.mp3'
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return '.wav'
    if data[:4] == b'fLaC':
        return '.flac'
    if data[:4] == b'OggS':
        return '.ogg'
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return '.m4a'
    raise ValueError('仅支持 MP3、WAV、FLAC、OGG 或 M4A 音频')


def normalize_audio_input_names(values, limit):
    """Positional names returned by upload(); '' leaves a slot empty, anything else is rejected."""
    names = []
    for value in values if isinstance(values, list) else []:
        name = str(value or '').strip()
        if name and (not _INPUT_NAME_RE.fullmatch(name) or Path(name).suffix.lower() not in AUDIO_SUFFIXES):
            raise ValueError('音频输入无效，请重新连接音频节点')
        names.append(name)
    return names[:max(0, int(limit))]


class ComfyAudioUploads:
    """Upload a canvas audio clip into ComfyUI's input folder; returns the stored input name."""

    def __init__(self, new_session, get_config):
        self.new_session, self.get_config = new_session, get_config

    def upload(self, data, name=''):
        if not 0 < len(data) <= MAX_AUDIO_UPLOAD:
            raise ValueError('音频须小于 50 MiB')
        suffix = audio_suffix(data)
        stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(str(name or '')).stem).strip('_')[:40] or 'audio'
        filename = f'miniapp_{int(time.time())}_{stem}{suffix}'
        config = self.get_config()
        with self.new_session() as session:
            response = session.post(
                f"{config['base_url']}/upload/image",
                files={'image': (filename, data, AUDIO_MIME_TYPES[suffix])},
                data={'type': 'input', 'overwrite': 'true'},
                timeout=config['timeout_seconds'],
            )
            response.raise_for_status()
            result = response.json() if response.content else {}
        if str(result.get('subfolder') or '').strip():
            raise RuntimeError('ComfyUI 把音频存进了子目录，LoadAudio 无法直接读取')
        return {'name': str(result.get('name') or filename)}
