#!/usr/bin/env python3
"""Telegram delivery helper for GPT image results."""

from pathlib import Path
from typing import List, Optional

import requests

from .app_config import get_telegram_config


def send_tg_document(path: Path, caption: str = "") -> None:
    """Send a file to Telegram with sendDocument."""
    telegram_cfg = get_telegram_config()
    bot_token = telegram_cfg.get("bot_token", "")
    chat_id = telegram_cfg.get("chat_id", "")
    proxy_url = telegram_cfg.get("proxy_url", "")

    if not bot_token:
        raise RuntimeError("Missing Telegram bot token")
    if not chat_id:
        raise RuntimeError("Missing Telegram chat id")

    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TelegramSendBot/1.0)"})

    try:
        with open(path, "rb") as f:
            response = session.post(
                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f},
                timeout=120,
            )
        if response.status_code != 200:
            raise RuntimeError(f"sendDocument failed: HTTP {response.status_code} {response.text[:200]}")
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"sendDocument failed: {payload}")
    finally:
        try:
            session.close()
        except Exception:
            pass


def send_telegram_result(
    image_path: str,
    prompt: str,
    ratio: str,
    resolution: str,
    image_paths: Optional[List[str]] = None,
) -> bool:
    """Send generated GPT images to Telegram."""
    try:
        candidates: list[str] = []
        for p in image_paths or []:
            if p and p not in candidates:
                candidates.append(p)
        if not candidates and image_path:
            candidates = [image_path]

        valid_paths = [Path(p) for p in candidates if Path(p).exists()]
        if not valid_paths:
            raise RuntimeError("没有可发送的图片文件")

        total = len(valid_paths)
        for idx, p in enumerate(valid_paths, start=1):
            caption = f"🎨 GPT(Web) | {ratio} | {resolution.upper()}"
            if total > 1:
                caption += f" | 候选 {idx}/{total}"
            send_tg_document(p, caption=caption)
            print(f"✅ Telegram 发送成功：{p}")
        return True
    except Exception as e:
        print(f"❌ Telegram 发送失败：{e}")
        return False
