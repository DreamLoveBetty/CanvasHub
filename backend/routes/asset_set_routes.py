"""Existing gallery candidate-set endpoints with explicit storage dependencies."""

import urllib.parse


def handle_asset_sets(handler, parsed, *, list_sets):
    """返回图库候选集。"""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        limit = int(query.get('limit', [80])[0])
        offset = int(query.get('offset', [0])[0])
        search = str(query.get('query', [''])[0] or '').strip()
        tag = str(query.get('tag', [''])[0] or '').strip()
        handler.send_json(list_sets(
            limit=limit,
            offset=offset,
            query=search,
            tag=tag,
        ))
    except Exception as e:
        handler.send_json({"error": str(e)}, 400)


def handle_asset_set_post(handler, *, create_set, update_set):
    """新建或更新图库候选集。"""
    try:
        data = handler.read_json_body(max_bytes=4 * 1024 * 1024)
        set_id = data.get('set_id') or data.get('id') or ''
        if set_id:
            payload = {}
            if 'name' in data:
                payload['name'] = data.get('name') or ''
            if 'asset_ids' in data or 'assetIds' in data:
                payload['asset_ids'] = data.get('asset_ids') or data.get('assetIds') or []
            if 'tags' in data:
                payload['tags'] = data.get('tags') or []
            if 'assets' in data:
                payload['assets'] = data.get('assets') or []
            item = update_set(set_id, **payload)
            handler.send_json({"ok": True, "set": item})
        else:
            payload = {
                "name": data.get('name') or '',
                "asset_ids": data.get('asset_ids') or data.get('assetIds') or [],
                "tags": data.get('tags') or [],
                "assets": data.get('assets') or [],
            }
            item = create_set(**payload)
            handler.send_json({"ok": True, "set": item}, 201)
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)


def handle_asset_set_delete(handler, set_id, *, delete_set):
    """删除图库候选集。"""
    try:
        item = delete_set(set_id)
        handler.send_json({"ok": True, "set": item})
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
