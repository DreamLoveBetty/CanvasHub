"""Asset health cleanup and legacy history maintenance endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_asset_health_cleanup(
    handler,
    *,
    _cleanup_lineage_refs,
    _cleanup_no_image_history,
    _collect_asset_health,
    _remove_asset_from_task,
    cleanup_asset_sets,
    get_gallery_asset,
    remove_asset_from_sets,
    update_asset_meta,
):
    """清理缺文件资产、候选集坏引用、空候选集和失效溯源。"""
    try:
        health = _collect_asset_health()
        removed_asset_refs = 0
        task_updates = 0
        hidden_updates = 0
        for item in health.get('missing_assets_all') or health.get('missing_assets') or []:
            asset = get_gallery_asset(item.get('asset_id') or item.get('id') or '')
            if not asset:
                continue
            removed_history = []
            if _remove_asset_from_task(asset, removed_history=removed_history):
                task_updates += 1
            try:
                update_asset_meta(item.get('asset_id') or item.get('id') or '', hidden=True)
                hidden_updates += 1
            except Exception:
                pass
            removed_asset_refs += remove_asset_from_sets(item.get('asset_id') or item.get('id') or '')

        refreshed = _collect_asset_health()
        valid_ids = set(refreshed.get('valid_asset_ids') or [])
        set_cleanup = cleanup_asset_sets(valid_ids, delete_empty=True)
        lineage_cleanup = _cleanup_lineage_refs(valid_ids)
        no_image_removed = _cleanup_no_image_history()
        after = _collect_asset_health()
        public_before = {key: value for key, value in health.items() if key not in ('valid_asset_ids', 'all_asset_ids', 'missing_assets_all')}
        public_after = {key: value for key, value in after.items() if key not in ('valid_asset_ids', 'all_asset_ids', 'missing_assets_all')}
        handler.send_json({
            "ok": True,
            "before": public_before,
            "after": public_after,
            "cleanup": {
                "missing_assets_removed": len(health.get('missing_assets_all') or health.get('missing_assets') or []),
                "task_updates": task_updates,
                "hidden_updates": hidden_updates,
                "set_updates_from_missing": removed_asset_refs,
                "sets": set_cleanup,
                "lineage": lineage_cleanup,
                "no_image_history_removed": no_image_removed,
            },
            "message": "图库体检清理完成",
        })
    except Exception as e:
        print(f"❌ 图库体检清理失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_history_export_tg(
    handler,
    *,
    DIRECTORY,
    Path,
    _decode_data_uri_image,
    _fetch_comfy_binary,
    _resolve_archive_image_file,
    _resolve_download_image,
    get_task,
    json,
    os,
    random,
    resolve_editable_file,
    safe_basename,
    send_telegram,
    tempfile,
    time,
):
    """把历史记录中的本机原图通过 Telegram sendDocument 发送出去。"""
    temp_path = None
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')

        raw_output_file = str(data.get('output_file') or data.get('filename') or '').strip()
        image_data = str(data.get('image_data') or data.get('imageData') or '').strip()
        filename = safe_basename(raw_output_file)
        archive_rel_path = str(data.get('archiveRelPath') or data.get('archive_rel_path') or '').strip()
        task_id = str(data.get('task_id') or '').strip()
        item_type = str(data.get('type') or '').strip()
        prompt = str(data.get('prompt') or '').strip()

        if image_data:
            image_bytes, _mime_type, extension = _decode_data_uri_image(image_data)
            filename = filename or f"source_{int(time.time())}_{random.randint(1000, 9999)}{extension}"
            suffix = Path(filename).suffix or extension
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(image_bytes)
                temp_path = tmp.name
            file_path = Path(temp_path)
        elif not raw_output_file:
            handler.send_json({"error": "缺少 output_file"}, 400)
            return
        elif item_type != 'gpt-file' and not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff')):
            handler.send_json({"error": "不支持的文件类型"}, 400)
            return

        if not image_data:
            task = get_task(task_id) if task_id else None
            if task_id:
                allowed_files = task.get('result_files') if task else []
                primary_file = task.get('result_file') if task else ''
                check_name = raw_output_file if item_type == 'gpt-file' else filename
                if task and check_name not in allowed_files and check_name != primary_file:
                    handler.send_json({"error": "文件不属于该任务"}, 403)
                    return

            if item_type == 'gpt-file':
                file_path = resolve_editable_file(raw_output_file)
            elif archive_rel_path:
                file_path = _resolve_archive_image_file(archive_rel_path)
            elif item_type in ('gpt', 'gpt-edit'):
                file_path = Path(DIRECTORY) / 'gpt_outputs' / filename
            elif item_type == 'comfy':
                params = task.get('params') if task else {}
                comfy_image = params.get('comfy_image') if isinstance(params, dict) else None
                if not isinstance(comfy_image, dict) or not comfy_image.get('filename'):
                    handler.send_json({"error": "ComfyUI 原图信息不存在"}, 404)
                    return

                comfy_filename = safe_basename(comfy_image.get('filename'))
                if comfy_filename != filename:
                    handler.send_json({"error": "文件不属于该任务"}, 403)
                    return

                image_bytes, _ = _fetch_comfy_binary(
                    comfy_filename,
                    comfy_image.get('subfolder', ''),
                    comfy_image.get('type', 'output'),
                )
                suffix = Path(comfy_filename).suffix or '.png'
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(image_bytes)
                    temp_path = tmp.name
                file_path = Path(temp_path)
            else:
                file_path = _resolve_download_image(filename)

        if not file_path or not Path(file_path).exists():
            handler.send_json({"error": "原图文件不存在"}, 404)
            return

        caption = '📎 File' if item_type == 'gpt-file' else '📸 Original'
        if item_type:
            caption += f' | {item_type}'
        if prompt:
            trimmed_prompt = prompt[:420] + ('...' if len(prompt) > 420 else '')
            caption += f'\n{trimmed_prompt}'

        sent = send_telegram(None, str(file_path), caption[:900])
        if not sent:
            raise RuntimeError('Telegram 发送失败')

        handler.send_json({"ok": True, "message": "原图已发送到 Telegram"})
    except Exception as e:
        print(f"❌ history export_tg failed: {e}")
        handler.send_json({"error": str(e)}, 500)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


def handle_delete_history_item(handler, *, DIRECTORY, delete_task, get_database_path, json, os, urllib):
    """删除单条历史记录，兼容新任务和旧 history.jsonl 记录"""
    try:
        parsed = urllib.parse.urlparse(handler.path)
        query = urllib.parse.parse_qs(parsed.query)
        task_id = query.get('task_id', [''])[0].strip()
        timestamp_raw = query.get('timestamp', [''])[0].strip()
        deleted = 0

        if task_id and not task_id.startswith('old_'):
            deleted += delete_task(task_id)
        elif timestamp_raw:
            try:
                timestamp = int(timestamp_raw)
            except ValueError:
                handler.send_json({"error": "timestamp 非法"}, 400)
                return

            history_path = os.path.join(DIRECTORY, 'history.jsonl')
            if os.path.exists(history_path):
                with open(history_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                kept = []
                removed = 0
                for line in lines:
                    try:
                        item = json.loads(line)
                    except Exception:
                        kept.append(line)
                        continue
                    if int(item.get('timestamp', -1)) == timestamp:
                        removed += 1
                        continue
                    kept.append(line)
                if removed:
                    with open(history_path, 'w', encoding='utf-8') as f:
                        f.writelines(kept)
                    deleted += removed
            if deleted == 0:
                import sqlite3
                conn = sqlite3.connect(str(get_database_path()))
                cur = conn.cursor()
                cur.execute('DELETE FROM tasks WHERE created_at=?', (timestamp,))
                conn.commit()
                deleted += conn.total_changes
                conn.close()
        else:
            handler.send_json({"error": "缺少 task_id 或 timestamp"}, 400)
            return

        handler.send_json({"deleted": deleted})
    except Exception as e:
        print(f"❌ 删除单条历史失败：{e}")
        handler.send_json({"error": str(e)}, 500)


def handle_delete_failed(handler, *, get_database_path):
    """删除所有失败任务"""
    try:
        import sqlite3
        conn = sqlite3.connect(str(get_database_path()))
        c = conn.cursor()
        
        # 统计失败任务数量
        c.execute('SELECT COUNT(*) FROM tasks WHERE status="failed"')
        count = c.fetchone()[0]
        
        # 删除失败任务
        c.execute('DELETE FROM tasks WHERE status="failed"')
        conn.commit()
        conn.close()
        
        print(f"✅ 删除 {count} 条失败任务")
        handler.send_json({"deleted": count})
        
    except Exception as e:
        print(f"❌ 删除失败任务出错：{e}")
        handler.send_json({"error": str(e)}, 500)
