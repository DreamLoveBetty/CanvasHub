"""Existing GPT and account-pool user error conversion.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _format_gpt_provider_error(error, *, re, time):
    """Turn common local provider failures into user-readable status text."""
    text = str(error or '').strip()
    if not text:
        return '本地 provider 失败'

    lower_text = text.lower()

    if 'usage_limit_reached' in text or 'usage limit has been reached' in text.lower():
        reset_text = ''
        match = re.search(r'"resets_at"\s*:\s*(\d+)', text)
        if match:
            try:
                reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(match.group(1))))
                reset_text = f'，预计 {reset_time} 恢复'
            except (TypeError, ValueError, OverflowError):
                reset_text = ''
        return f'本地 GPT 授权额度已用完{reset_text}'

    if 'moderation_blocked' in text or 'safety_violations' in text or 'rejected by the safety system' in lower_text:
        request_id = ''
        match = re.search(r'(?:request_id=|request ID\s+)([A-Za-z0-9_-]+)', text, re.I)
        if match:
            request_id = f'（request_id: {match.group(1)}）'
        return f'本地 GPT provider 被安全系统拒绝{request_id}，请降低敏感姿势、暴露、低角度或擦边描述后重试'

    if 'did not return image output' in lower_text and 'output_text=' in lower_text:
        if any(marker in lower_text for marker in ('violate', 'policy', 'safety', 'cannot', 'refuse', 'sorry', '违反', '安全', '抱歉', '拒绝')):
            return '本地 GPT provider 返回了文字而不是图片，可能触发安全/内容边界；请修改提示词后重新生成'
        return '本地 GPT provider 返回了文字而不是图片；请把需求改成明确的图片生成描述后重试'

    if 'did not return image output' in lower_text or 'missing image output' in lower_text:
        return '本地 GPT provider 没有返回图片数据，通常是上游生成失败或返回了非图片结果'

    if 'chunkedencodingerror' in lower_text or 'response ended prematurely' in lower_text:
        if 'last_event=response.image_generation_call.generating' in lower_text:
            return '本地 GPT provider 连接中途断开：已进入图片生成阶段，但上游/网络没有完整返回图片流；可稍后重试，连续发生时检查网络/代理或降低分辨率'
        if 'before first event' in lower_text:
            return '本地 GPT provider 连接在收到模型响应前断开；请优先检查网络、代理或稍后重试'
        return '本地 GPT provider 连接中途断开，通常是上游图片流提前结束或网络/代理中断'

    if 'stream disconnected' in lower_text:
        return '本地 GPT provider 图片流未完整返回，通常是上游连接提前结束或网络/代理中断'

    if 'response.failed' in text or 'server_error' in text:
        request_id = ''
        match = re.search(r'(?:request_id=|request ID\s+)([A-Za-z0-9_-]+)', text, re.I)
        if match:
            request_id = f'（request_id: {match.group(1)}）'
        return f'OpenAI/Codex 上游临时错误{request_id}'

    if 'total timeout after' in text.lower():
        match = re.search(r'total timeout after\s+(\d+)s', text, re.I)
        waited = f"{match.group(1)}s" if match else '超时阈值'
        return f'本地 GPT provider 调用超时（{waited}）'

    if text.startswith('HTTP 429'):
        return '本地 GPT provider 返回 429 限流'

    return f'本地 provider 失败：{text[:120]}'


def _first_user_error_line(error, *, re):
    text = str(error or '').strip()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('at ') or line.startswith('File '):
            continue
        if re.match(r'^\^+$', line):
            continue
        line = re.sub(r'^(?:Error|RuntimeError|Exception):\s*', '', line).strip()
        if line:
            return line
    return ''


def _format_gpt_pool_error(error, *, _first_user_error_line, datetime, re):
    """Turn account-pool sidecar failures into user-readable status text."""
    text = str(error or '').strip()
    if not text:
        return 'ChatGPT 账号池托底失败'
    lower_text = text.lower()
    if 'browser verification' in lower_text or '需要浏览器验证' in text or 'turnstile' in lower_text or 'arkose' in lower_text:
        return 'ChatGPT 账号池需要浏览器验证'
    if (
        'image quota exhausted' in lower_text
        or 'image generation quota reached' in lower_text
        or 'image generations requests' in lower_text
        or 'free plan limit' in lower_text
        or '图片创建上限' in text
        or '图片生成额度' in text
        or '恢复时间' in text
    ):
        reset_text = ''
        match = re.search(r'(?:reset_after=|恢复时间\s*)([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+)', text)
        if match:
            reset_raw = match.group(1)
            try:
                reset_dt = datetime.fromisoformat(reset_raw.replace('Z', '+00:00'))
                reset_text = f'，预计 {reset_dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")} 恢复'
            except Exception:
                reset_text = f'，恢复时间 {reset_raw}'
        elif 'resets_after_text=' in text:
            match = re.search(r'resets_after_text=([^;|]+)', text)
            if match:
                reset_text = f'，{match.group(1).strip()}后恢复'
        return f'ChatGPT 账号池图片生成额度已用完{reset_text}'
    if 'disabled' in lower_text:
        return 'ChatGPT 账号池未启用'
    if 'connection refused' in lower_text or 'failed to establish a new connection' in lower_text:
        return 'ChatGPT 账号池 sidecar 未在线'
    if 'unauthorized' in lower_text or 'http 401' in lower_text:
        return 'ChatGPT 账号池鉴权失败，请确认 server.py 与 sidecar 使用同一个 auth key'
    if 'no available image quota' in lower_text:
        return 'ChatGPT 账号池没有可用账号或额度'
    if (
        'finished without image output' in lower_text
        or 'did not return any images' in lower_text
        or 'upstream did not return image output' in lower_text
    ):
        return 'ChatGPT 账号池上游会话已结束但没有返回图片，请重试或切换线路'
    if 'timeout' in lower_text or 'timed out' in lower_text:
        return 'ChatGPT 账号池生成等待超时'
    if 'http 429' in lower_text or 'rate limit' in lower_text or '限流' in text:
        return 'ChatGPT 账号池账号被限流'
    summary = _first_user_error_line(text)
    return f'ChatGPT 账号池托底失败：{summary[:120]}' if summary else 'ChatGPT 账号池托底失败'


def _chatgpt_pool_failure_metadata(error):
    result = getattr(error, 'provider_result', None)
    if not isinstance(result, dict):
        return {}
    metadata = {}
    for key in ('error_code', 'timed_out', 'partial_errors', 'completed_image_count', 'requested_image_count'):
        if result.get(key) is not None:
            metadata[key] = result.get(key)
    return metadata


def _format_gpt_failure_error(error, *, _first_user_error_line, _format_gpt_pool_error, _format_gpt_provider_error, re):
    """Format final GPT task failures without leaking raw stack traces to users."""
    text = str(error or '').strip()
    if not text:
        return 'GPT 生成失败'

    parts = re.split(r'\s*\|\s*账号池托底失败[:：]\s*', text, maxsplit=1)
    if len(parts) == 2:
        provider_part = re.sub(
            r'^本地\s*(?:GPT\s*)?provider\s*(?:失败|异常)?[:：]\s*',
            '',
            parts[0].strip(),
            flags=re.I,
        )
        return f'{_format_gpt_provider_error(provider_part)}；{_format_gpt_pool_error(parts[1])}'

    if '本地 provider 失败' in text or '本地 GPT provider' in text:
        provider_part = re.sub(
            r'^本地\s*(?:GPT\s*)?provider\s*(?:失败|异常)?[:：]\s*',
            '',
            text,
            flags=re.I,
        )
        return _format_gpt_provider_error(provider_part)

    summary = _first_user_error_line(text)
    return summary[:180] if summary else 'GPT 生成失败'
