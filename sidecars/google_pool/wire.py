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
TEXT_MODEL_PREFIXES = (
    'gemini-',
    'claude-',
    'gpt-oss-',
)
EXCLUDED_MODEL_PREFIXES = (
    'chat_',
    'tab_',
)
MAX_BYTES = 128 * 1024 * 1024


def is_image_model(value):
    model = (
        str(value or '')
        .strip()
        .lower()
        .removeprefix('models:')
        .removeprefix('models/')
        .removesuffix('-preview')
    )
    return model in IMAGE_MODELS or '-image' in model


def is_text_model(value):
    model = (
        str(value or '')
        .strip()
        .lower()
        .removeprefix('models:')
        .removeprefix('models/')
    )
    if not model or is_image_model(model) or model.startswith(EXCLUDED_MODEL_PREFIXES):
        return False
    return model.startswith(TEXT_MODEL_PREFIXES) and bool(
        re.fullmatch(r'[a-z0-9._-]+', model)
    )


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


def normalize_text_model(value):
    model = (
        str(value or '')
        .strip()
        .removeprefix('models:')
        .removeprefix('models/')
    )
    if not is_text_model(model):
        raise GoogleError(
            '不支持的 Google LLM 模型', 400, 'invalid_model'
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


def _clean_contents(contents):
    if not isinstance(contents, list) or not contents or len(contents) > 64:
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
                if len(part['text']) > 400000:
                    raise GoogleError('提示词过长', 400, 'invalid_request')
                copied.append({'text': part['text']})
            elif isinstance(part.get('inlineData') or part.get('inline_data'), dict):
                img = part.get('inlineData') or part.get('inline_data')
                data = img.get('data', '')
                mime = img.get('mimeType') or img.get('mime_type')
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
                if image_count > 16 or total > 64 * 1024 * 1024:
                    raise GoogleError('参考图数量或大小超限', 400, 'invalid_image')
                copied.append({'inlineData': {'mimeType': mime, 'data': data}})
            else:
                raise GoogleError(
                    '仅支持 text/inlineData，不能读取远端文件', 400, 'invalid_request'
                )
        clean.append({'role': content.get('role', 'user'), 'parts': copied})
    return clean


def prepare_text_request(body):
    if not isinstance(body, dict):
        raise GoogleError('请求必须为 JSON 对象', 400, 'invalid_request')
    clean = _clean_contents(body.get('contents'))
    request = {'contents': clean}
    sys_inst = body.get('systemInstruction') or body.get('system_instruction')
    if isinstance(sys_inst, str) and sys_inst.strip():
        request['systemInstruction'] = {'parts': [{'text': sys_inst.strip()}]}
    elif isinstance(sys_inst, dict):
        parts = sys_inst.get('parts')
        if isinstance(parts, list):
            sys_parts = [
                {'text': p['text']}
                for p in parts
                if isinstance(p, dict) and isinstance(p.get('text'), str) and p['text']
            ]
            if sys_parts:
                request['systemInstruction'] = {'parts': sys_parts}
    cfg = body.get('generationConfig') or body.get('generation_config')
    if isinstance(cfg, dict):
        clean_cfg = {}
        for key in ('temperature', 'topP', 'topK', 'maxOutputTokens', 'responseMimeType'):
            if key in cfg and cfg[key] is not None:
                clean_cfg[key] = cfg[key]
        thinking_cfg = cfg.get('thinkingConfig') or cfg.get('thinking_config')
        if isinstance(thinking_cfg, dict):
            clean_cfg['thinkingConfig'] = dict(thinking_cfg)
        if clean_cfg:
            request['generationConfig'] = clean_cfg
    return request


def extract_text_parts(value):
    texts = []
    thoughts = []
    finish_reason = None
    if isinstance(value, list):
        for item in value:
            t_list, th_list, f_reason = extract_text_parts(item)
            texts.extend(t_list)
            thoughts.extend(th_list)
            if f_reason:
                finish_reason = f_reason
        return texts, thoughts, finish_reason
    if not isinstance(value, dict):
        return texts, thoughts, finish_reason
    if value.get('error'):
        raise GoogleError('Google 流式响应返回错误')
    inner = value.get('response', value)
    if not isinstance(inner, dict):
        return texts, thoughts, finish_reason
    if inner.get('error'):
        raise GoogleError('Google 流式响应返回错误')
    candidates = inner.get('candidates')
    if not isinstance(candidates, list):
        return texts, thoughts, finish_reason
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if isinstance(candidate.get('finishReason'), str) and candidate['finishReason']:
            finish_reason = candidate['finishReason']
        content = candidate.get('content')
        if not isinstance(content, dict):
            continue
        parts = content.get('parts')
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get('text')
            if not isinstance(text, str) or not text:
                continue
            if part.get('thought') is True:
                thoughts.append(text)
            else:
                texts.append(text)
    return texts, thoughts, finish_reason


class TextResponse:
    def __init__(self):
        self.buffer = bytearray()
        self.total = 0
        self.mode = None
        self.search_from = 0
        self.text_parts = []
        self.thought_parts = []
        self.finish_reason = None

    def _consume_payload(self, value):
        texts, thoughts, finish_reason = extract_text_parts(value)
        if texts:
            self.text_parts.extend(texts)
        if thoughts:
            self.thought_parts.extend(thoughts)
        if finish_reason:
            self.finish_reason = finish_reason
        return texts

    def feed(self, chunk):
        self.total += len(chunk)
        if self.total > MAX_BYTES:
            raise GoogleError('Google 文本响应超过大小限制')
        self.buffer.extend(chunk)
        if self.mode is None:
            stripped = self.buffer.lstrip()
            if stripped:
                self.mode = 'json' if stripped[:1] in (b'{', b'[') else 'sse'
        if self.mode == 'json':
            if not chunk.rstrip().endswith((b'}', b']')):
                return []
            try:
                value = json.loads(self.buffer)
            except (ValueError, UnicodeDecodeError):
                return []
            self.buffer.clear()
            return self._consume_payload(value)
        deltas = []
        while True:
            match = re.compile(br'\r?\n\r?\n').search(self.buffer, self.search_from)
            if not match:
                self.search_from = max(0, len(self.buffer) - 3)
                return deltas
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
            deltas.extend(self._consume_payload(value))

    def finish(self):
        if self.mode == 'sse' and self.buffer.strip():
            self.feed(b'\n\n')
        text = ''.join(self.text_parts)
        if not text and self.thought_parts:
            text = ''.join(self.thought_parts)
        if not text:
            raise GoogleError('Google 模型未返回有效文本', 502, 'google_empty_text')
        return {
            'candidates': [
                {
                    'content': {
                        'role': 'model',
                        'parts': [{'text': text}],
                    },
                    'finishReason': self.finish_reason or 'STOP',
                }
            ]
        }
