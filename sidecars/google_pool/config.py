"""Google-only paths and upstream configuration (no GPT account state)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# No OAuth client is built in: set GOOGLE_POOL_CLIENT_ID and
# GOOGLE_POOL_CLIENT_SECRET together for a registered desktop client.
DEFAULT_CLIENT_ID = ''
DEFAULT_CLIENT_SECRET = ''


@dataclass(frozen=True)
class GoogleSettings:
    db_path: Path
    client_id: str
    client_secret: str
    redirect_uri: str
    upstream: str = 'https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal'
    timeout: int = 900
    proxy_url: str = ""


def load_settings(callback_port=18080) -> GoogleSettings:
    root = Path(
        os.environ.get('CANVASHUB_RESOURCE_DIR') or Path(__file__).resolve().parents[2]
    )
    data = Path(os.environ.get('CANVASHUB_DATA_DIR') or root)
    directory = data / (
        'google_pool' if os.environ.get('CANVASHUB_DATA_DIR') else 'data/google_pool'
    )
    client_id = os.environ.get('GOOGLE_POOL_CLIENT_ID') or DEFAULT_CLIENT_ID
    client_secret = os.environ.get('GOOGLE_POOL_CLIENT_SECRET') or DEFAULT_CLIENT_SECRET
    if bool(os.environ.get('GOOGLE_POOL_CLIENT_ID')) != bool(
        os.environ.get('GOOGLE_POOL_CLIENT_SECRET')
    ):
        raise ValueError(
            'GOOGLE_POOL_CLIENT_ID 与 GOOGLE_POOL_CLIENT_SECRET 必须一起配置'
        )
    return GoogleSettings(
        Path(os.environ.get('GOOGLE_POOL_DB') or directory / 'accounts.db'),
        client_id,
        client_secret,
        os.environ.get('GOOGLE_POOL_REDIRECT_URI')
        or f'http://localhost:{int(callback_port)}/oauth-callback',
        proxy_url=os.environ.get('GOOGLE_POOL_PROXY_URL', '').strip(),
    )
