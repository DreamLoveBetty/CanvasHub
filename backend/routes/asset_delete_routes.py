"""Existing gallery deletion and undo endpoints with explicit mutation dependencies.

Keep request parsing, operation order, response fields and error boundaries intact.
File, task, history, candidate-set and journal operations stay in their existing helpers.
"""
from ..services.asset_undo import undo_asset_deletions as _undo_asset_deletions


def handle_asset_delete(handler, asset_id, *, delete_assets):
    """从图库移除资产，并把本地原图/提示词/预览移入废纸篓。"""
    try:
        handler.send_json(delete_assets([asset_id]))
    except FileNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 删除图库资产失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_asset_delete_batch(handler, *, delete_assets):
    """批量删除图库资产，避免同任务多图逐张删除时 asset_id 重新计算。"""
    try:
        data = handler.read_json_body(max_bytes=256 * 1024)
        raw_ids = data.get('asset_ids') or data.get('assetIds') or data.get('ids') or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        result = delete_assets(raw_ids if isinstance(raw_ids, list) else [])
        handler.send_json(result)
    except FileNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 批量删除图库资产失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_asset_undo_delete(
    handler,
    *,
    get_batch,
    restore_move,
    restore_task,
    restore_history,
    restore_sets,
    update_meta,
    mark_restored,
):
    """撤销最近的图库物理删除。"""
    try:
        data = handler.read_json_body(max_bytes=128 * 1024)
        raw_ids = data.get('batch_ids') or data.get('batchIds') or data.get('batch_id') or data.get('batchId') or []
        if isinstance(raw_ids, str):
            batch_ids = [raw_ids]
        elif isinstance(raw_ids, list):
            batch_ids = [str(value or '').strip() for value in raw_ids if str(value or '').strip()]
        else:
            batch_ids = []
        if not batch_ids:
            handler.send_json({"ok": False, "error": "缺少删除批次 ID"}, 400)
            return

        result = _undo_asset_deletions(
            batch_ids,
            get_batch=get_batch,
            restore_move=restore_move,
            restore_task=restore_task,
            restore_history=restore_history,
            restore_sets=restore_sets,
            update_meta=update_meta,
            mark_restored=mark_restored,
        )
        status = 207 if result['errors'] and result['batch_ids'] else (400 if result['errors'] and not result['batch_ids'] else 200)
        handler.send_json(result, status)
    except Exception as e:
        print(f"❌ 撤销图库删除失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)
