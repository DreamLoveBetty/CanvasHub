"""Existing gallery read endpoints with explicit index and health dependencies."""

import urllib.parse


def handle_assets(handler, parsed, *, invalidate_cache, list_assets):
    """返回图库资产索引。"""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        limit = int(query.get('limit', [200])[0])
        offset = int(query.get('offset', [0])[0])
        search = str(query.get('query', [''])[0] or '').strip()
        filter_value = str(query.get('filter', ['all'])[0] or 'all').strip().lower()
        tag = str(query.get('tag', [''])[0] or '').strip()

        provider = filter_value if filter_value in ('gpt', 'google', 'comfy', 'layout') else 'all'
        source = query.get('source', [''])[0] or ''
        if not source and filter_value in ('linked', 'history', 'task_record', 'orphan', 'archive_only', 'missing_history'):
            source = filter_value
        orientation = str(query.get('orientation', [''])[0] or '').strip().lower()
        if not orientation and filter_value in ('landscape', 'portrait', 'square'):
            orientation = filter_value
        file_format = str(query.get('format', query.get('file_format', ['']))[0] or '').strip().lower()
        if not file_format and filter_value in ('png', 'jpg', 'jpeg', 'webp'):
            file_format = filter_value
        resolution = str(query.get('resolution', [''])[0] or '').strip().lower()
        if not resolution and filter_value in ('1k', '2k', '4k'):
            resolution = filter_value
        ratio = str(query.get('ratio', [''])[0] or '').strip().lower()
        favorite = filter_value == 'favorite' or str(query.get('favorite', [''])[0]).lower() in ('1', 'true', 'yes')
        hidden = filter_value == 'hidden' or str(query.get('hidden', [''])[0]).lower() in ('1', 'true', 'yes')
        include_hidden = hidden or str(query.get('include_hidden', [''])[0]).lower() in ('1', 'true', 'yes')
        fields = str(query.get('fields', [''])[0] or '').strip().lower()
        refresh = str(query.get('refresh', [''])[0]).lower() in ('1', 'true', 'yes')
        if refresh:
            # 显式刷新逃生阀：绕过成品索引缓存的 TTL/指纹判定，强制重建
            invalidate_cache()

        handler.send_json(list_assets(
            limit=limit,
            offset=offset,
            query=search,
            provider=provider,
            tag=tag,
            favorite=favorite,
            hidden=hidden,
            include_hidden=include_hidden,
            source=source,
            ratio=ratio,
            orientation=orientation,
            file_format=file_format,
            resolution=resolution,
            fields=fields,
        ))
    except Exception as e:
        handler.send_json({"error": str(e)}, 400)


def handle_asset_detail(handler, parsed, *, get_asset):
    """按 id 返回单个资产的完整字段（瘦身列表的详情补全）。"""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        asset_id = str(query.get('id', [''])[0] or '').strip()
        if not asset_id:
            handler.send_json({"ok": False, "error": "缺少 id 参数"}, 400)
            return
        asset = get_asset(asset_id)
        if not asset:
            handler.send_json({"ok": False, "error": "资产不存在"}, 404)
            return
        handler.send_json({"ok": True, "asset": asset})
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)


def handle_asset_health(handler, *, collect_health):
    """检查图库资产、候选集和溯源引用健康状态。"""
    try:
        health = collect_health()
        public_health = {key: value for key, value in health.items() if key not in ('valid_asset_ids', 'all_asset_ids', 'missing_assets_all')}
        handler.send_json({"ok": True, "health": public_health})
    except Exception as e:
        print(f"❌ 图库体检失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)
