"""Existing gallery metadata update endpoint with an explicit storage dependency."""

import json


def handle_asset_meta(handler, *, update_meta):
    """更新图库资产人工元数据。"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')
        asset_id = data.get('asset_id') or data.get('id') or ''
        payload = {}
        for key in ('favorite', 'hidden', 'tags', 'rating', 'note'):
            if key in data:
                payload[key] = data.get(key)
        meta = update_meta(asset_id, **payload)
        handler.send_json({"ok": True, "asset": meta})
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
