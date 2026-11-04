"""ComfyUI video workflows: input/output detection, video outputs and source uploads.

Image workflows keep the existing image-only paths in comfy_gateway / comfy_generation.
A workflow is a video workflow when it saves video (SaveVideo, SaveWEBM, VHS_VideoCombine);
it accepts video when it loads one (LoadVideo, VHS_LoadVideo) or uses {{VIDEO}} / {{VIDEO_n}}.
Video sources are uploaded to ComfyUI's input folder through its /upload/image endpoint,
which stores any file type and is what LoadVideo / VHS_LoadVideo read from.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .video_upload import MAX_UPLOAD, MIME_TYPES, video_suffix

VIDEO_SUFFIXES = frozenset({'.mp4', '.webm', '.mov', '.m4v'})
# ComfyUI history keys that may carry saved files: core SaveVideo reports `images`,
# VideoHelperSuite reports `gifs`.
_OUTPUT_KEYS = ('images', 'gifs', 'videos')
_INPUT_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$')
MAX_VIDEOS = 4


def _class_key(node):
    return str(node.get('class_type') or '').lower().replace('_', '')


def _is_video_saver(class_key):
    return 'savevideo' in class_key or class_key in ('savewebm', 'vhsvideocombine')


def _is_video_loader(class_key):
    # Path-based loaders expect a server path, not an uploaded input name.
    return 'loadvideo' in class_key and 'path' not in class_key


def is_uploaded_video_input(class_type, input_name):
    """Loader fields filled from connected video nodes; never offered as workflow parameters."""
    return _is_video_loader(str(class_type or '').lower().replace('_', '')) and input_name in ('file', 'video')


def _workflow_nodes(workflow):
    if not isinstance(workflow, dict):
        return []
    return [node for node in workflow.values() if isinstance(node, dict)]


def workflow_video_io(workflow, raw_text=''):
    """Return {'output_kind': 'image'|'video', 'accepts_video': bool} for an API-format workflow."""
    keys = [_class_key(node) for node in _workflow_nodes(workflow)]
    text = str(raw_text or '')
    return {
        'output_kind': 'video' if any(_is_video_saver(key) for key in keys) else 'image',
        'accepts_video': any(_is_video_loader(key) for key in keys) or '{{VIDEO}}' in text or '{{VIDEO_' in text,
    }


def find_comfy_videos(outputs):
    """Saved video files from a history entry; final outputs win over temp previews."""
    if not isinstance(outputs, dict):
        return []
    final_items, temp_items, seen = [], [], set()
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in _OUTPUT_KEYS:
            for item in node_output.get(key) or []:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get('filename') or '').strip()
                if Path(filename).suffix.lower() not in VIDEO_SUFFIXES:
                    continue
                identity = (filename, item.get('subfolder'), item.get('type'))
                if identity in seen:
                    continue
                seen.add(identity)
                entry = {'filename': filename, 'subfolder': str(item.get('subfolder') or ''),
                         'type': str(item.get('type') or 'output')}
                (final_items if entry['type'] == 'output' else temp_items).append(entry)
    return final_items or temp_items


def video_token_replacements(video_names):
    names = [str(name) for name in video_names or [] if str(name).strip()]
    replacements = {'{{VIDEO}}': names[0] if names else ''}
    for index, name in enumerate(names, start=1):
        replacements[f'{{{{VIDEO_{index}}}}}'] = name
    return replacements


def fill_video_loaders(workflow, video_names):
    """Point LoadVideo (`file`) / VHS_LoadVideo (`video`) inputs at the uploaded names, in node order."""
    names = [str(name) for name in video_names or [] if str(name).strip()]
    if not names:
        return workflow
    index = 0
    for node in _workflow_nodes(workflow):
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else None
        if not inputs or not _is_video_loader(_class_key(node)):
            continue
        field = next((key for key in ('file', 'video') if key in inputs and not isinstance(inputs.get(key), (dict, list))), None)
        if field is None:
            continue
        inputs[field] = names[min(index, len(names) - 1)]
        index += 1
    return workflow


def normalize_video_input_names(values, limit, allow_empty=False):
    """Validate names returned by upload(); anything else never reaches the workflow.
    With allow_empty, '' marks a tagged slot left to the workflow's own value."""
    names = []
    for value in values if isinstance(values, list) else []:
        name = str(value or '').strip()
        if allow_empty and not name:
            names.append('')
            continue
        if not _INPUT_NAME_RE.fullmatch(name) or Path(name).suffix.lower() not in VIDEO_SUFFIXES:
            raise ValueError('视频输入无效，请重新连接视频节点')
        names.append(name)
    return names[:max(0, int(limit))]


class ComfyVideoUploads:
    """Upload a canvas video into ComfyUI's input folder; returns the stored input name."""

    def __init__(self, new_session, get_config):
        self.new_session, self.get_config = new_session, get_config

    def upload(self, data, name=''):
        if not 0 < len(data) <= MAX_UPLOAD:
            raise ValueError('视频须小于 200 MiB')
        suffix = video_suffix(data)
        stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(str(name or '')).stem).strip('_')[:40] or 'video'
        filename = f'miniapp_{int(time.time())}_{stem}{suffix}'
        config = self.get_config()
        with self.new_session() as session:
            response = session.post(
                f"{config['base_url']}/upload/image",
                files={'image': (filename, data, MIME_TYPES[suffix])},
                data={'type': 'input', 'overwrite': 'true'},
                timeout=config['timeout_seconds'],
            )
            response.raise_for_status()
            result = response.json() if response.content else {}
        stored = str(result.get('name') or filename)
        subfolder = str(result.get('subfolder') or '').strip()
        if subfolder:
            raise RuntimeError('ComfyUI 把视频存进了子目录，LoadVideo 无法直接读取')
        return {'name': stored}
