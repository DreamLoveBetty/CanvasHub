"""Bounded native Gemini request/response adaptation, independent of GPT."""

from __future__ import annotations
import base64
import io
import json
import re
from PIL import Image
from .errors import GoogleError

IMAGE_MODELS = (
    'gemini-3-pro-image',
    'gemini-3.1-pro-image',
    'gemini-3-flash-image',
    'gemini-3.1-flash-image',
)
MAX_BYTES = 128 * 1024 * 1024


def normalize_model(value):
    model = (
        str(value or '')
        .removeprefix('models:')
        .removeprefix('models/')
        .removesuffix('-preview')
    )
    if model not in IMAGE_MODELS:
        raise GoogleError(
            '该 Google 账号池仅支持 Gemini 图像模型', 400, 'invalid_model'
        )
    return model


def prepare_request(body):
    if not isinstance(body, dict):
        raise GoogleError('请求必须为 JSON 对象', 400, 'invalid_request')
    contents = body.get('contents')
    if not isinstance(contents, list) or not contents or len(contents) > 32:
        raise GoogleError('需要有效 contents', 400, 'invalid_request')
    clean = []
    image_count = total = 0
    for content in contents:
        if not isinstance(content, dict) or content.get('role', 'user') not in (
            'user',
            'model',
        ):
            raise GoogleError('contents role 无效', 400, 'invalid_request')
        parts = content.get('parts')
        if not isinstance(parts, list) or not parts:
            raise GoogleError('需要有效 parts', 400, 'invalid_request')
        copied = []
        for part in parts:
            if not isinstance(part, dict):
                raise GoogleError('parts 无效', 400, 'invalid_request')
            if isinstance(part.get('text'), str):
                if len(part['text']) > 100000:
                    raise GoogleError('提示词过长', 400, 'invalid_request')
                copied.append({'text': part['text']})
            elif isinstance(part.get('inlineData'), dict):
                img = part['inlineData']
                data = img.get('data', '')
                mime = img.get('mimeType')
                if mime not in (
                    'image/png',
                    'image/jpeg',
                    'image/webp',
                ) or not isinstance(data, str):
                    raise GoogleError('参考图格式无效', 400, 'invalid_image')
                try:
                    raw = base64.b64decode(data, validate=True)
                    if not raw or len(raw) > 20 * 1024 * 1024:
                        raise ValueError()
                    with Image.open(io.BytesIO(raw)) as picture:
                        actual_mime = Image.MIME.get(picture.format)
                        picture.verify()
                    if actual_mime != mime:
                        raise ValueError()
                except Exception:
                    raise GoogleError('参考图数据无效', 400, 'invalid_image') from None
                image_count += 1
                total += len(raw)
                if image_count > 8 or total > 48 * 1024 * 1024:
                    raise GoogleError('参考图数量或大小超限', 400, 'invalid_image')
                copied.append({'inlineData': {'mimeType': mime, 'data': data}})
            else:
                raise GoogleError(
                    '仅支持 text/inlineData，不能读取远端文件', 400, 'invalid_request'
                )
        clean.append({'role': content.get('role', 'user'), 'parts': copied})
    cfg = body.get('generationConfig') or {}
    if not isinstance(cfg, dict):
        raise GoogleError('generationConfig 无效', 400, 'invalid_request')
    image_cfg = cfg.get('imageConfig') or {}
    if not isinstance(image_cfg, dict):
        raise GoogleError('imageConfig 无效', 400, 'invalid_request')
    ratio = image_cfg.get('aspectRatio', '1:1')
    size = image_cfg.get('imageSize', '2K')
    if ratio not in (
        '1:1',
        '2:3',
        '3:2',
        '3:4',
        '4:3',
        '4:5',
        '5:4',
        '9:16',
        '16:9',
        '21:9',
    ) or size not in ('1K', '2K', '4K'):
        raise GoogleError('画幅或分辨率无效', 400, 'invalid_request')
    return {
        'contents': clean,
        'generationConfig': {
            'candidateCount': 1,
            'imageConfig': {'aspectRatio': ratio, 'imageSize': size},
        },
    }


def find_image_response(value):
    if isinstance(value, list):
        for v in value:
            found = find_image_response(v)
            if found is not None:
                return found
        return None
    if not isinstance(value, dict):
        return None
    if value.get('error'):
        raise GoogleError('Google 流式响应返回错误；未重新提交')
    value = value.get('response', value)
    if not isinstance(value, dict):
        return None
    candidates = value.get('candidates')
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(
            candidate.get('content'), dict
        ):
            continue
        parts = candidate['content'].get('parts')
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            image = part.get('inlineData') or {}
            if not isinstance(image, dict):
                continue
            if not image.get('data'):
                continue
            try:
                raw = base64.b64decode(image['data'], validate=True)
                with Image.open(io.BytesIO(raw)) as picture:
                    mime = Image.MIME.get(picture.format)
                    picture.verify()
                if mime not in ('image/png', 'image/jpeg', 'image/webp'):
                    raise ValueError()
            except Exception:
                raise GoogleError('Google 返回的图片数据无效') from None
            # Return only image data, not upstream account/project/session internals.
            return {
                'candidates': [
                    {
                        'content': {
                            'role': 'model',
                            'parts': [
                                {
                                    'inlineData': {
                                        'mimeType': mime,
                                        'data': image['data'],
                                    }
                                }
                            ],
                        },
                        'finishReason': 'STOP',
                    }
                ]
            }
    return None


class ImageResponse:
    def __init__(self):
        self.buffer = bytearray()
        self.total = 0
        self.mode = None
        self.search_from = 0

    def feed(self, chunk):
        self.total += len(chunk)
        if self.total > MAX_BYTES:
            raise GoogleError('Google 图片响应超过大小限制')
        self.buffer.extend(chunk)
        if self.mode is None:
            stripped = self.buffer.lstrip()
            if stripped:
                self.mode = 'json' if stripped[:1] in (b'{', b'[') else 'sse'
        if self.mode == 'json':
            if not chunk.rstrip().endswith((b'}', b']')):
                return None
            try:
                value = json.loads(self.buffer)
            except (ValueError, UnicodeDecodeError):
                return None
            return find_image_response(value)
        # SSE events can span arbitrary network chunks; never assume one chunk == one event.
        while True:
            match = re.compile(br'\r?\n\r?\n').search(self.buffer, self.search_from)
            if not match:
                self.search_from = max(0, len(self.buffer) - 3)
                return None
            self.search_from = 0
            event = bytes(self.buffer[: match.start()])
            del self.buffer[: match.end()]
            data = b'\n'.join(
                line.split(b':', 1)[1].lstrip()
                for line in event.splitlines()
                if line.startswith(b'data:')
            )
            if not data or data == b'[DONE]':
                continue
            try:
                value = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                raise GoogleError('Google SSE 数据无效') from None
            found = find_image_response(value)
            if found is not None:
                return found

    def finish(self):
        if self.mode == 'sse' and self.buffer.strip():
            return self.feed(b'\n\n')
        return None
