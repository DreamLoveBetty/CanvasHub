"""Collect asset health using explicit read and history-policy dependencies.

Preserve the existing scan limits, counts, private details and error propagation.
HTTP field filtering and all cleanup or storage mutation remain outside this service.
"""


def collect_asset_health(
    *,
    list_assets,
    list_sets,
    list_tasks,
    asset_exists,
    should_render_history,
):
    data = list_assets(limit=3000, offset=0, include_hidden=True)
    stats = data.get('stats') if isinstance(data.get('stats'), dict) else {}
    assets = [asset for asset in data.get('assets', []) if asset.get('id') or asset.get('asset_id')]
    missing_assets = []
    valid_asset_ids = set()
    all_asset_ids = set()
    for asset in assets:
        asset_id = str(asset.get('id') or asset.get('asset_id') or '').strip()
        if not asset_id:
            continue
        all_asset_ids.add(asset_id)
        if asset_exists(asset):
            valid_asset_ids.add(asset_id)
        else:
            missing_assets.append({
                "asset_id": asset_id,
                "id": asset_id,
                "task_id": asset.get('taskId') or asset.get('task_id') or '',
                "title": asset.get('title') or '',
                "file": asset.get('file') or '',
                "imageUrl": asset.get('imageUrl') or asset.get('image_url') or '',
                "provider": asset.get('provider') or '',
            })

    sets_data = list_sets(limit=300, offset=0)
    invalid_set_refs = 0
    empty_sets = []
    for asset_set in sets_data.get('sets', []):
        ids = [str(value or '').strip() for value in (asset_set.get('assetIds') or asset_set.get('asset_ids') or []) if str(value or '').strip()]
        valid_count = sum(1 for asset_id in ids if asset_id in valid_asset_ids)
        invalid_set_refs += sum(1 for asset_id in ids if asset_id not in valid_asset_ids)
        if ids and valid_count <= 0:
            empty_sets.append({
                "set_id": asset_set.get('id') or asset_set.get('set_id') or '',
                "name": asset_set.get('name') or '未命名候选集',
                "count": len(ids),
            })

    invalid_lineage_refs = 0
    invalid_lineage_tasks = 0
    no_image_history = 0
    for task in list_tasks(limit=3000, offset=0):
        result_files = task.get('result_files') or []
        primary = task.get('result_file') or ''
        if not result_files and primary:
            result_files = [primary]
        if not should_render_history(task.get('status'), result_files):
            no_image_history += 1

        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        lineage = params.get('lineage') if isinstance(params.get('lineage'), dict) else {}
        refs = lineage.get('reference_assets') or lineage.get('referenceAssets') or []
        if not isinstance(refs, list):
            continue
        missing_refs = [
            ref for ref in refs
            if isinstance(ref, dict)
            and str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip()
            and str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip() not in valid_asset_ids
        ]
        if missing_refs:
            invalid_lineage_refs += len(missing_refs)
            invalid_lineage_tasks += 1

    history_missing_count = int(stats.get('history_missing_count') or 0)
    issue_count = len(missing_assets) + invalid_set_refs + len(empty_sets) + invalid_lineage_refs + no_image_history + history_missing_count
    return {
        "ok": issue_count == 0,
        "assets_total": len(assets),
        "assets_valid": len(valid_asset_ids),
        "missing_count": len(missing_assets),
        "missing_assets": missing_assets[:120],
        "missing_assets_all": missing_assets,
        "invalid_set_refs": invalid_set_refs,
        "empty_sets": empty_sets,
        "empty_set_count": len(empty_sets),
        "invalid_lineage_refs": invalid_lineage_refs,
        "invalid_lineage_tasks": invalid_lineage_tasks,
        "no_image_history": no_image_history,
        "valid_asset_ids": sorted(valid_asset_ids),
        "all_asset_ids": sorted(all_asset_ids),
        "issue_count": issue_count,
        "stats": stats,
        "obsidian_image_count": stats.get('obsidian_image_count', len(assets)),
        "archive_image_count": stats.get('archive_image_count', len(assets)),
        "gallery_asset_count": stats.get('gallery_asset_count', len(assets)),
        "indexed_asset_count": stats.get('indexed_asset_count', len(assets)),
        "task_record_image_count": stats.get('task_record_image_count', 0),
        "linked_asset_count": stats.get('linked_asset_count', 0),
        "orphan_asset_count": stats.get('orphan_asset_count', 0),
        "archive_only_count": stats.get('archive_only_count', 0),
        "history_result_count": stats.get('history_result_count', 0),
        "history_missing_count": history_missing_count,
        "history_missing_archive_count": stats.get('history_missing_archive_count', history_missing_count),
    }
