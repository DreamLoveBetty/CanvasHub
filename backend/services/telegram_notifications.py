"""Existing uncompressed result notifications.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _load_telegram_notify_config(*, get_telegram_config):
    telegram_cfg = get_telegram_config()
    return (
        telegram_cfg.get('bot_token', ''),
        telegram_cfg.get('chat_id', ''),
        telegram_cfg.get('proxy_url', ''),
    )


def send_status_notification(task_id, message, icon='🔄', *, _load_telegram_notify_config, requests):
    """发送状态通知到 Telegram"""
    session = None
    try:
        bot_token, chat_id, proxy_url = _load_telegram_notify_config()
        if not bot_token or not chat_id:
            return False

        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        text = f'{icon} {message}'.strip()[:4000]
        session = requests.Session()
        session.trust_env = False
        session.proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else {}
        response = session.post(
            url,
            data={'chat_id': chat_id, 'text': text},
            timeout=20,
        )
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return True
            print(f"⚠️ Telegram 状态通知返回错误：{result}")
        else:
            print(f"⚠️ Telegram 状态通知 HTTP {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"⚠️ 发送状态通知失败：{e}")
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    return False
