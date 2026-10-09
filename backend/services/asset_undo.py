"""Restore deletion batches using explicit recovery and journal dependencies.

Batch IDs have already been parsed by the caller. Preserve reverse order,
partial restoration, counts and exception propagation without retries or rollback.
HTTP validation, status selection and error responses stay in the controller.
"""


def undo_asset_deletions(
    batch_ids,
    *,
    get_batch,
    restore_move,
    restore_task,
    restore_history,
    restore_sets,
    update_meta,
    mark_restored,
):
    restored_files = 0
    existing_files = 0
    missing_files = 0
    skipped_files = 0
    restored_tasks = 0
    restored_history = 0
    restored_assets = 0
    restored_sets = 0
    restored_batches = []
    errors = []
    for batch_id in reversed(batch_ids):
        batch = get_batch(batch_id)
        if not batch:
            errors.append(f"{batch_id}: 删除记录不存在")
            continue
        if batch.get('restored'):
            errors.append(f"{batch_id}: 已撤销")
            continue
        for move in batch.get('moves') or []:
            status = restore_move(move if isinstance(move, dict) else {})
            if status == 'restored':
                restored_files += 1
            elif status == 'exists':
                existing_files += 1
            elif status == 'missing':
                missing_files += 1
            else:
                skipped_files += 1
        task_snapshots = batch.get('task_snapshots') or []
        if not isinstance(task_snapshots, list):
            task_snapshots = []
        task_snapshot = batch.get('task_snapshot')
        if isinstance(task_snapshot, dict):
            task_snapshots.append(task_snapshot)
        restored_task_ids = set()
        for snapshot in task_snapshots:
            if not isinstance(snapshot, dict) or not snapshot.get('task_id'):
                continue
            task_id = str(snapshot.get('task_id') or '')
            if task_id in restored_task_ids:
                continue
            restored_task_ids.add(task_id)
            restored_tasks += 1 if restore_task(snapshot) else 0
        restored_history += restore_history(batch.get('old_history_lines') or [])
        restored_sets += restore_sets(batch.get('set_snapshots') or [])
        for asset_id in batch.get('asset_ids') or []:
            try:
                update_meta(asset_id, hidden=False)
                restored_assets += 1
            except Exception:
                pass
        mark_restored(batch_id)
        restored_batches.append(batch_id)

    return {
        "ok": bool(restored_batches),
        "batch_ids": restored_batches,
        "errors": errors,
        "restored_files": restored_files,
        "existing_files": existing_files,
        "missing_files": missing_files,
        "skipped_files": skipped_files,
        "restored_tasks": restored_tasks,
        "restored_history": restored_history,
        "restored_assets": restored_assets,
        "restored_sets": restored_sets,
        "message": "已撤销删除" if restored_batches else "没有可撤销的删除",
    }
