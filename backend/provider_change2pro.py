"""Change2Pro's documented image contract; no network/config/worker state.

Feishu: ZWYbwd68HiZYKnksEC1cAfZCnUX (Google), En21wwe9wiHMMuk8aYac0746nhf (GPT).
Unknown custom paths and other providers are deliberately not rewritten.
"""
from __future__ import annotations

import base64
import io
from urllib.parse import quote, urlsplit, urlunsplit

from PIL import Image

from .image_resolution import build_resolution_metadata


def is_change2pro(url: str) -> bool:
    return urlsplit(str(url or '')).hostname == 'api.change2pro.com'


def uses_documented_google_api(base: str) -> bool:
    if not is_change2pro(base):
        return False
    path = urlsplit(base).path.rstrip('/')
    return path in {'', '/v1', '/v1beta', '/chat/completions', '/v1/chat/completions'}


def google_url(base: str, model: str, *, stream: bool) -> str:
    parsed = urlsplit(base)
    action = 'streamGenerateContent' if stream else 'generateContent'
    return urlunsplit((parsed.scheme, parsed.netloc,
                      f'/v1beta/models/{quote(model, safe="")}:{action}',
                      'alt=sse' if stream else '', ''))


def gpt_endpoint(base: str, path: str) -> str:
    parsed = urlsplit(base)
    if (is_change2pro(base) and parsed.path.rstrip('/') in {'', '/v1'}
            and path in {'/v1/images/generations', '/v1/images/edits',
                         '/images/generations', '/images/edits'}):
        path = path.removeprefix('/v1')
        return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))
    return f'{base.rstrip("/")}{path}'


def reference_part(value: str) -> dict:
    """Validate base64 locally and use actual image MIME, not a PNG default."""
    encoded = str(value or '').strip()
    if encoded.startswith('data:'):
        header, encoded = encoded.split(',', 1)
        if ';base64' not in header.lower():
            raise ValueError('参考图必须是 base64 图片')
    encoded = ''.join(encoded.split())
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as img:
            mime = Image.MIME.get(img.format)
            img.verify()
    except Exception as exc:
        raise ValueError('参考图 base64 或图片数据无效') from exc
    if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
        raise ValueError(f'参考图格式不支持：{mime or "unknown"}')
    return {'inlineData': {'mimeType': mime, 'data': encoded}}


def google_payload(prompt: str, aspect_ratio: str, image_size: str, images=()) -> dict:
    parts = [{'text': prompt}, *(reference_part(img) for img in images)]
    return {
        'contents': [{'role': 'user', 'parts': parts}],
        'generationConfig': {'imageConfig': {
            'imageSize': image_size, 'aspectRatio': aspect_ratio,
        }},
    }


def output_metadata(image_data: bytes, aspect_ratio: str, image_size: str) -> dict:
    with Image.open(io.BytesIO(image_data)) as img:
        width, height = img.size
    meta = build_resolution_metadata(image_size, [{'width': width, 'height': height}])
    if meta['requested_resolution'] and not meta['actual_resolution']:
        meta['resolution_mismatch'] = True
        meta['effective_resolution'] = f'{width}x{height}'
    # Native models can round dimensions slightly to their pixel grid.
    try:
        ratio_w, ratio_h = (float(part) for part in aspect_ratio.split(':'))
        mismatch = abs((width / height) / (ratio_w / ratio_h) - 1) > 0.02
    except (ValueError, ZeroDivisionError):
        mismatch = False
    meta.update(requested_aspect_ratio=aspect_ratio, aspect_ratio_mismatch=mismatch)
    if mismatch or meta['resolution_mismatch']:
        meta['output_size_warning'] = (
            f'上游返回 {width}×{height}，与请求 {image_size} / {aspect_ratio} 不符；'
            '保留原图，未自动重新生成'
        )
    return meta
