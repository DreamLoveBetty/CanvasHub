"""Existing PPT/PSD artifact endpoints with explicit dependencies."""

import mimetypes
import urllib.parse


def handle_editable_file(handler, rel_path, *, resolve_file):
    """读取 PPT/PSD 文件产物目录下的文件。"""
    filepath = resolve_file(rel_path)

    if filepath and filepath.exists():
        content_type = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler._apply_cors_headers()
        if filepath.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.pdf'):
            handler.send_header('Content-Disposition', f'attachment; filename="{filepath.name}"')
        handler.end_headers()
        with open(filepath, 'rb') as f:
            handler.wfile.write(f.read())
    else:
        handler.send_error(404, "File not found")


def handle_editable_files(handler, parsed, *, list_files, coerce_bool):
    """列出 PPT/PSD 文件产物，用于图库文件管理页。"""
    try:
        params = urllib.parse.parse_qs(parsed.query or '')
        limit = int((params.get('limit') or ['200'])[0] or 200)
        query = (params.get('query') or [''])[0]
        kind = (params.get('kind') or [''])[0]
        include_local = coerce_bool((params.get('include_local') or ['1'])[0], True)
        handler.send_json(list_files(limit=limit, query=query, kind=kind, include_local=include_local))
    except Exception as e:
        print(f"❌ editable files list failed: {e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_editable_file_send(handler, *, resolve_file, send_telegram):
    """发送一个已生成的 PPT/PSD 主文件到 Telegram。"""
    try:
        data = handler.read_json_body()
        rel_path = str(data.get('relative_path') or data.get('result_file') or data.get('file') or '').strip()
        filepath = resolve_file(rel_path)
        if not filepath:
            handler.send_json({"ok": False, "error": "文件不存在"}, 404)
            return
        caption = str(data.get('caption') or '📎 File').strip() or '📎 File'
        sent = send_telegram(None, str(filepath), caption[:900])
        if not sent:
            raise RuntimeError('Telegram 发送失败')
        handler.send_json({"ok": True, "message": "文件已发送到 Telegram"})
    except Exception as e:
        print(f"❌ editable file send failed: {e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_editable_file_delete(handler, *, delete_item):
    """删除一个 PPT/PSD 文件产物目录。前端会先二次确认。"""
    try:
        data = handler.read_json_body()
        rel_path = str(data.get('directory_relative') or data.get('relative_path') or data.get('manifest') or '').strip()
        if not rel_path:
            handler.send_json({"ok": False, "error": "缺少文件目录"}, 400)
            return
        handler.send_json(delete_item(rel_path))
    except FileNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except Exception as e:
        print(f"❌ editable file delete failed: {e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)
