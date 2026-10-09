"""Incremental Gemini image responses (JSON or real SSE), without I/O state."""
from __future__ import annotations

import base64
import io
import json

from PIL import Image

_BLOCKED = {'SAFETY', 'IMAGE_SAFETY', 'BLOCKLIST', 'PROHIBITED_CONTENT'}
MAX_RESPONSE_BYTES = 128 * 1024 * 1024


def find_image(data) -> bytes | None:
    """Scan every candidate/part; text or a blocked candidate isn't an image."""
    if isinstance(data, list):
        for item in data:
            image = find_image(item)
            if image is not None:
                return image
        return None
    if not isinstance(data, dict):
        return None
    if data.get('error'):
        error = data['error']
        detail = error.get('message') if isinstance(error, dict) else str(error)
        raise ValueError(f'Google 流式接口错误：{str(detail)[:300]}')
    for candidate in data.get('candidates') or []:
        if candidate.get('finishReason') in _BLOCKED:
            continue
        for part in (candidate.get('content') or {}).get('parts') or []:
            inline = part.get('inlineData') or part.get('inline_data') or {}
            encoded = inline.get('data')
            if not encoded:
                continue
            mime = str(inline.get('mimeType') or inline.get('mime_type') or '')
            if mime and not mime.startswith('image/'):
                continue
            try:
                image = base64.b64decode(''.join(encoded.split()), validate=True)
                with Image.open(io.BytesIO(image)) as img:
                    img.verify()
                with Image.open(io.BytesIO(image)) as img:
                    img.load()
            except Exception:
                # A malformed first part must not hide a valid later part.
                continue
            return image
    return None


def response_detail(data) -> str:
    if isinstance(data, list):
        return '；'.join(filter(None, (response_detail(item) for item in data)))[:500]
    if not isinstance(data, dict):
        return ''
    blocked = (data.get('promptFeedback') or {}).get('blockReason')
    if blocked:
        return f'内容安全过滤：{blocked}'
    notes = []
    for candidate in data.get('candidates') or []:
        reason = candidate.get('finishReason')
        if reason in _BLOCKED:
            notes.append(f'内容安全过滤：{reason}')
        for part in (candidate.get('content') or {}).get('parts') or []:
            if part.get('text'):
                notes.append(str(part['text'])[:240])
    return '；'.join(notes)[:500]


class GeminiImageResponse:
    """One image per local task; finish as soon as a complete image event arrives.

    Handles split UTF-8/CRLF, multi-line data, comments/heartbeats, [DONE], and
    gateways that answer a streaming request with a regular JSON document.
    """
    def __init__(self, on_document=None):
        self.on_document = on_document
        self.buffer = bytearray()
        self.mode = None
        self.event_lines = []
        self.search_from = 0
        self.bytes_received = 0
        self.notes = ''
        self.image = None
        self.done = False
        self.event_count = 0

    def _document(self, data):
        self.event_count += 1
        if self.on_document is not None:
            self.on_document(data)
        image = find_image(data)
        if image is not None:
            self.image = image
            self.done = True
        else:
            detail = response_detail(data)
            if detail:
                self.notes = detail
        return image

    def _event(self):
        if not self.event_lines:
            return None
        payload = b'\n'.join(self.event_lines).decode('utf-8').strip()
        self.event_lines = []
        if payload == '[DONE]':
            self.done = True
            return None
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise ValueError('Google SSE 返回了不完整或无效的 JSON 事件') from exc
        return self._document(data)

    def _line(self, line):
        line = line.rstrip(b'\r')
        if not line:
            return self._event()
        if line.startswith(b'data:'):
            self.event_lines.append(line[5:].removeprefix(b' '))
        return None

    def feed(self, chunk: bytes) -> bytes | None:
        if self.done:
            return self.image
        self.bytes_received += len(chunk)
        if self.bytes_received > MAX_RESPONSE_BYTES:
            raise ValueError('Google 响应超过 128 MiB，已停止接收，未重新提交')
        self.buffer.extend(chunk)
        if self.mode is None:
            head = bytes(self.buffer).lstrip()
            if not head or b'\xef\xbb\xbf'.startswith(head):
                return None
            if head.startswith(b'\xef\xbb\xbf'):
                self.buffer = bytearray(head[3:])
                head = bytes(self.buffer).lstrip()
                if not head:
                    return None
            self.mode = 'json' if head[:1] in (b'{', b'[') else 'sse'
        if self.mode == 'json':
            try:
                data = json.loads(self.buffer)
            except (ValueError, UnicodeDecodeError):
                return None
            self.done = True
            return self._document(data)
        consumed = 0
        while True:
            end = self.buffer.find(b'\n', self.search_from)
            if end < 0:
                self.search_from = len(self.buffer) - consumed
                if consumed:
                    del self.buffer[:consumed]
                return None
            image = self._line(bytes(self.buffer[consumed:end]))
            consumed = end + 1
            self.search_from = consumed
            if image is not None or self.done:
                return image

    def finish(self) -> bytes:
        if self.image is not None:
            return self.image
        if self.mode == 'sse' and not self.done:
            if self.buffer:
                self._line(bytes(self.buffer))
            self._event()
            if self.image is not None:
                return self.image
        detail = self.notes or '未收到完整的 inlineData 图片数据'
        raise ValueError(f'Google 响应未包含完整图片：{detail}')
