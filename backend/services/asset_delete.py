"""Orchestrate gallery deletion with explicit lookup, snapshot and mutation dependencies.

Keep file/storage policies in their original helpers, including partial-failure
semantics. This service does not own HTTP, configuration, transactions or retries.
"""
from pathlib import Path


def delete_gallery_assets(
    asset_ids,
    *,
    list_assets,
    get_asset,
    get_task,
    snapshot_sets,
    delete_candidates,
    move_to_trash,
    remove_from_tasks,
    update_meta,
    remove_from_sets,
    record_batch,
):
    clean_ids = []
    seen_ids = set()
    for raw_id in asset_ids or []:
        asset_id = str(raw_id or '').strip()
        if not asset_id or asset_id in seen_ids:
            continue
        seen_ids.add(asset_id)
        clean_ids.append(asset_id)
    if not clean_ids:
        raise ValueError("缺少资产 ID")
    if len(clean_ids) > 120:
        raise ValueError("单次最多删除 120 张图片")

    data = list_assets(limit=5000, offset=0, include_hidden=True)
    missing_data = list_assets(limit=5000, offset=0, include_hidden=True, source='missing_history')
    asset_map = {
        str(asset.get('id') or asset.get('asset_id') or ''): asset
        for asset in (data.get('assets') or []) + (missing_data.get('assets') or [])
        if asset.get('id') or asset.get('asset_id')
    }
    assets = []
    missing_asset_ids = []
    for asset_id in clean_ids:
        asset = asset_map.get(asset_id) or get_asset(asset_id)
        if asset:
            assets.append(asset)
        else:
            missing_asset_ids.append(asset_id)
    if not assets:
        raise FileNotFoundError("资产不存在")

    task_snapshots = {}
    set_snapshots = {}
    for asset in assets:
        task_id = str(asset.get('taskId') or asset.get('task_id') or '').strip()
        if task_id and not task_id.startswith('old_') and task_id not in task_snapshots:
            task = get_task(task_id)
            if task:
                task_snapshots[task_id] = task
        for snapshot in snapshot_sets(str(asset.get('id') or asset.get('asset_id') or '')):
            set_id = str(snapshot.get('set_id') or '').strip()
            if set_id:
                set_snapshots[set_id] = snapshot

    deleted = []
    missing = []
    skipped = []
    moves = []
    seen_paths = set()
    for asset in assets:
        for path in delete_candidates(asset):
            path_key = str(Path(path).expanduser())
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            move_to_trash(path, deleted, missing, skipped, moves=moves)

    removed_history = []
    task_updates = remove_from_tasks(assets, removed_history=removed_history)
    hidden_updates = 0
    set_updates = 0
    processed_ids = []
    for asset in assets:
        asset_id = str(asset.get('id') or asset.get('asset_id') or '').strip()
        if not asset_id:
            continue
        processed_ids.append(asset_id)
        try:
            update_meta(asset_id, hidden=True)
            hidden_updates += 1
        except Exception:
            pass
        set_updates += remove_from_sets(asset_id)

    journal = record_batch({
        "asset_ids": processed_ids,
        "assets": assets,
        "moves": moves,
        "task_snapshots": list(task_snapshots.values()),
        "task_snapshot": next(iter(task_snapshots.values()), None),
        "old_history_lines": removed_history,
        "set_snapshots": list(set_snapshots.values()),
        "deleted_files": deleted,
        "missing_files": missing,
        "skipped_files": skipped,
    })

    return {
        "ok": True,
        "asset_ids": processed_ids,
        "asset_id": processed_ids[0] if len(processed_ids) == 1 else "",
        "missing_asset_ids": missing_asset_ids,
        "delete_batch_id": journal.get("batch_id"),
        "undo_id": journal.get("batch_id"),
        "deleted_files": deleted,
        "missing_files": missing,
        "skipped_files": skipped,
        "task_updates": task_updates,
        "task_updated": task_updates > 0,
        "hidden_updates": hidden_updates,
        "set_updates": set_updates,
        "message": "资产文件已移入废纸篓" if deleted else "资产已从图库移除",
    }
