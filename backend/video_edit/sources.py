"""Map the canvas's same-origin video URLs to local files without trusting any path.

Only URL shapes the server already serves are accepted. Each one is resolved by the domain
that owns it (injected by server.py), so traversal and symlink checks stay in one place:

* `/video/<archive path>`                     -> archive video resolver
* `/api/topaz_video/source?id=`               -> Topaz Video store asset
* `/api/topaz_video/artifact?id=&name=`       -> Topaz Video verified result
* `/api/video_control/source?id=`             -> ReShot store asset
* `/api/video_control/artifact?id=&name=`     -> ReShot result
"""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from .contracts import AUDIO_ASSET_PATTERN

STORE_ROUTES = ('topaz_video', 'video_control')


class UnsupportedSource(ValueError):
    pass


class SourceResolver:
    def __init__(self, *, archive_video, stores=None):
        self._archive_video = archive_video
        self._stores = dict(stores or {})

    def resolve(self, url: str) -> Path:
        parsed = urlparse(str(url or '').strip())
        if parsed.scheme not in ('', 'http', 'https'):
            raise UnsupportedSource('该视频来源暂不支持剪辑')
        path = parsed.path or ''
        if path.startswith('/video/') and len(path) > len('/video/'):
            resolved = self._archive_video(path[len('/video/'):])
            if not resolved:
                raise FileNotFoundError('视频不存在')
            return Path(resolved)
        query = parse_qs(parsed.query)
        first = lambda key: (query.get(key) or [''])[0]
        for domain in STORE_ROUTES:
            store = self._stores.get(domain)
            if store is None:
                continue
            if path == f'/api/{domain}/source':
                return Path(store.asset(first('id')))
            if path == f'/api/{domain}/artifact':
                return Path(store.artifact(first('id'), first('name')))
        raise UnsupportedSource('该视频来源暂不支持剪辑，请先导入或保存到作品库')


class AudioSourceResolver:
    """Music for compose: archived audio, an audio job artifact, or a file uploaded to the audio store.

    * `/api/assets/audio/file?path=`      -> audio archive resolver
    * `/api/audio/artifact?id=&name=`     -> audio job store artifact
    * `asset_id` (sha256 + extension)      -> `<audio data>/assets/<asset_id>` (POST /api/audio/upload)

    `store` is a zero-argument callable returning the audio job store, read only when an artifact is
    asked for: opening that store takes the audio service's lease, which must not happen at import.
    """

    def __init__(self, *, archive=None, store=None, assets_dir=None):
        self._archive, self._store = archive, store
        self._assets = Path(assets_dir) if assets_dir else None

    def resolve(self, url: str = '', asset_id: str = '') -> Path:
        if asset_id:
            if self._assets is None or not re.fullmatch(AUDIO_ASSET_PATTERN, asset_id):
                raise UnsupportedSource('配乐音频无效')
            path = self._assets / asset_id
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError('配乐音频不存在，请重新导入')
            return path
        parsed = urlparse(str(url or '').strip())
        if parsed.scheme not in ('', 'http', 'https'):
            raise UnsupportedSource('该配乐来源暂不支持')
        query = parse_qs(parsed.query)
        first = lambda key: (query.get(key) or [''])[0]
        if parsed.path == '/api/assets/audio/file' and self._archive is not None:
            return Path(self._archive(first('path')))
        if parsed.path == '/api/audio/artifact' and self._store is not None:
            return Path(self._store().artifact(first('id'), first('name')))
        raise UnsupportedSource('该配乐来源暂不支持，请使用作品库或本地导入的音频')
