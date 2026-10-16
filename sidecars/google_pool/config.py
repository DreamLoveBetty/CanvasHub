"""Google-only paths and upstream configuration (no GPT account state)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

# The OAuth client of a registered Google desktop application. None is built in: set
# GOOGLE_POOL_CLIENT_ID and GOOGLE_POOL_CLIENT_SECRET together, or keep
# {"client_id": "...", "client_secret": "..."} in oauth_client.json in the Google pool
# data directory (next to accounts.db, never committed). Without either, sign-in reports
# oauth_not_configured; the account service itself still starts.
OAUTH_CLIENT_FILE = 'oauth_client.json'
logger = logging.getLogger(__name__)


def _client_from_file(directory: Path) -> tuple[str, str]:
    path = directory / OAUTH_CLIENT_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return '', ''
    except (OSError, ValueError) as error:
        logger.warning('Google OAuth client file %s is unreadable: %s', path, error)
        return '', ''
    if not isinstance(data, dict):
        logger.warning('Google OAuth client file %s must hold a JSON object', path)
        return '', ''
    client_id = str(data.get('client_id') or '').strip()
    client_secret = str(data.get('client_secret') or '').strip()
    if bool(client_id) != bool(client_secret):
        logger.warning('Google OAuth client file %s needs both client_id and client_secret', path)
        return '', ''
    return client_id, client_secret


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
    client_id = os.environ.get('GOOGLE_POOL_CLIENT_ID') or ''
    client_secret = os.environ.get('GOOGLE_POOL_CLIENT_SECRET') or ''
    if bool(client_id) != bool(client_secret):
        raise ValueError(
            'GOOGLE_POOL_CLIENT_ID 与 GOOGLE_POOL_CLIENT_SECRET 必须一起配置'
        )
    if not client_id:
        client_id, client_secret = _client_from_file(directory)
    return GoogleSettings(
        Path(os.environ.get('GOOGLE_POOL_DB') or directory / 'accounts.db'),
        client_id,
        client_secret,
        os.environ.get('GOOGLE_POOL_REDIRECT_URI')
        or f'http://localhost:{int(callback_port)}/oauth-callback',
        proxy_url=os.environ.get('GOOGLE_POOL_PROXY_URL', '').strip(),
    )
