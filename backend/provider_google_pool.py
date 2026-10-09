"""Native Gemini adapter to the independent Google sidecar module.

Returns original image bytes to the existing archive/Telegram worker. No fallback,
no account-token handling, and no writes to the GPT or Google account database.
"""

from __future__ import annotations
import base64
import io
import time
from urllib.parse import quote
import requests
from PIL import Image
from .gemini_image_response import GeminiImageResponse
from .image_resolution import build_resolution_metadata


class GooglePoolProvider:
    def __init__(self, client, is_cancelled=lambda _task_id: False):
        self.client = client
        self.is_cancelled = is_cancelled

    def generate(
        self,
        prompt,
        aspect_ratio='1:1',
        quality='2k',
        model='gemini-3.1-flash-image',
        max_tokens=4096,
        temperature=None,
        progress_cb=None,
        task_id=None,
    ):
        return self.edit(
            prompt,
            [],
            aspect_ratio,
            quality,
            model,
            max_tokens,
            temperature,
            progress_cb,
            task_id,
        )

    def edit(
        self,
        prompt,
        images,
        aspect_ratio='1:1',
        quality='2k',
        model='gemini-3.1-flash-image',
        max_tokens=4096,
        temperature=None,
        progress_cb=None,
        task_id=None,
    ):
        size = (
            '4K'
            if str(quality).lower() in ('4k', 'hd')
            else ('1K' if str(quality).lower() == '1k' else '2K')
        )
        parts = [{'text': str(prompt)}]
        for value in images:
            encoded = str(value).split(',', 1)[-1]
            try:
                raw = base64.b64decode(encoded, validate=True)
                with Image.open(io.BytesIO(raw)) as img:
                    mime = Image.MIME.get(img.format)
                    img.verify()
                if mime not in ('image/png', 'image/jpeg', 'image/webp'):
                    raise ValueError()
            except Exception:
                raise ValueError('Google参考图数据无效') from None
            parts.append({'inlineData': {'mimeType': mime, 'data': encoded}})
        body = {
            'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {
                'imageConfig': {'aspectRatio': aspect_ratio, 'imageSize': size}
            },
        }
        base, headers = self.client.connection()
        endpoint = (
            '/v1beta/models/'
            + quote(str(model), safe='')
            + ':streamGenerateContent?alt=sse'
        )
        route_meta = {}

        def capture_document(document):
            if not isinstance(document, dict):
                return
            info = document.get('google_pool')
            if isinstance(info, dict):
                route_meta.update(
                    {
                        key: str(info[key])[:160]
                        for key in ('requested_model', 'resolved_model', 'account_id')
                        if key in info
                    }
                )

        start = time.monotonic()
        decoder = GeminiImageResponse(on_document=capture_document)
        first = None
        if task_id and self.is_cancelled(task_id):
            raise RuntimeError('任务已取消')
        try:
            with self.client.session_factory() as s:
                s.trust_env = False
                with s.post(
                    base + endpoint,
                    json=body,
                    headers=headers,
                    stream=True,
                    timeout=(15, 30),
                    allow_redirects=False,
                ) as r:
                    if not 200 <= r.status_code < 300:
                        try:
                            error = r.json().get('error')
                        except ValueError:
                            error = None
                        raise RuntimeError(error or f'Google账号池HTTP {r.status_code}')
                    for chunk in r.iter_content(chunk_size=None):
                        if task_id and self.is_cancelled(task_id):
                            raise RuntimeError('任务已取消；未重新提交')
                        if time.monotonic() - start > 930:
                            raise RuntimeError('Google账号池等待超时；未重新提交')
                        if first is None:
                            first = time.time()
                        if progress_cb:
                            progress_cb(
                                stage='calling_api',
                                progress_text='Google OAuth账号池生成中…',
                                heartbeat=True,
                            )
                        if decoder.feed(chunk) is not None:
                            break
        except requests.RequestException:
            raise RuntimeError(
                'Google账号池连接中断；执行状态未知，未重新提交'
            ) from None
        image = decoder.finish()
        with Image.open(io.BytesIO(image)) as picture:
            width, height = picture.size
        metadata = build_resolution_metadata(size, [{'width': width, 'height': height}])
        rw, rh = (float(x) for x in aspect_ratio.split(':'))
        ratio_mismatch = abs((width / height) / (rw / rh) - 1) > 0.02
        metadata.update(
            {
                'request_endpoint': endpoint,
                'google_provider_route': 'google_pool',
                'requested_model': model,
                'requested_aspect_ratio': aspect_ratio,
                'aspect_ratio_mismatch': ratio_mismatch,
                'bytes_received': decoder.bytes_received,
                'first_byte_at': int(first or time.time()),
                'response_protocol': decoder.mode,
            }
        )
        metadata.update(route_meta)
        if ratio_mismatch or metadata.get('resolution_mismatch'):
            metadata['output_size_warning'] = (
                f'Google返回原图{width}×{height}，与请求{aspect_ratio}/{size}不完全一致；原图已保留，未重新生成'
            )
        return image, metadata
