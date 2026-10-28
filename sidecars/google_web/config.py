"""Persistent Web-only data paths and explicitly configured proxy."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class WebSettings:
    db_path: Path
    proxy_url: str = ''
    timeout: int = 900
    cooldown_seconds: int = 60


def load_settings():
    root = Path(os.environ.get('CANVASHUB_RESOURCE_DIR') or Path(__file__).resolve().parents[2])
    data = Path(os.environ.get('CANVASHUB_DATA_DIR') or root / 'data')
    return WebSettings(
        Path(os.environ.get('GOOGLE_WEB_DB') or data / 'google_web' / 'accounts.db'),
        proxy_url=os.environ.get('GOOGLE_WEB_PROXY_URL', '').strip(),
    )
