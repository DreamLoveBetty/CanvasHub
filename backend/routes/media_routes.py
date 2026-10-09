"""Original image, video, archive, thumbnail and import HTTP endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_asset_videos(
    handler,
    parsed,
    *,
    _ARCHIVE_VIDEO_SOURCE_TYPES,
    _coerce_archive_video_source,
    _history_page_int,
    _list_archive_videos,
    urllib,
):
    """返回归档目录中的视频资产，不暴露本机绝对路径。"""
    try:
        query = urllib.parse.parse_qs(parsed.query or '')
        limit = _history_page_int((query.get('limit') or ['200'])[0], 200, minimum=1, maximum=500)
        offset = _history_page_int((query.get('offset') or ['0'])[0], 0, minimum=0, maximum=100000)
        search = str((query.get('query') or [''])[0] or '').strip()
        source_value = str((query.get('source') or [''])[0] or '').strip().lower()
        filter_alias = str((query.get('filter') or [''])[0] or '').strip().lower()
        if not source_value and filter_alias in _ARCHIVE_VIDEO_SOURCE_TYPES:
            source_value = filter_alias
        source = _coerce_archive_video_source(source_value)
        handler.send_json(_list_archive_videos(limit=limit, offset=offset, query=search, source=source))
    except Exception as e:
        print(f'❌ video assets list failed: {e}')
        handler.send_json({'ok': False, 'error': '视频资产列表读取失败'}, 500)


def handle_image(handler, filename, *, _resolve_download_file, mimetypes, os):
    """处理图片请求（archive directory, with legacy fallback）"""
    filepath = _resolve_download_file(filename)
    
    if filepath and os.path.exists(filepath):
        from urllib.parse import urlparse, parse_qs
        from pathlib import Path
        from ..services.image_preview import preview_png
        preview = Path(filepath).suffix.lower() in ('.tif','.tiff') and parse_qs(urlparse(getattr(handler, 'path', '')).query).get('preview') == ['1']
        try:
            data = preview_png(filepath) if preview else Path(filepath).read_bytes()
        except (ValueError, OSError):
            handler.send_error(422, 'Image preview unavailable')
            return
        content_type = 'image/png' if preview else mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler._apply_cors_headers()
        handler.end_headers()
        handler.wfile.write(data)
    else:
        handler.send_error(404, "Image not found")


def handle_image_import_url(handler, *, _download_remote_image_for_import, urllib):
    """Download a public remote image for a canvas drag/drop import."""
    try:
        data = handler.read_json_body(max_bytes=16 * 1024)
        imported = _download_remote_image_for_import(data.get('url'))
        content = imported['content']
        filename = imported['filename']
        encoded_filename = urllib.parse.quote(filename, safe='')
        handler.send_response(200)
        handler.send_header('Content-Type', imported['content_type'])
        handler.send_header('Content-Length', str(len(content)))
        handler.send_header('Content-Disposition', f"inline; filename*=UTF-8''{encoded_filename}")
        handler.send_header('X-CanvasHub-Filename', encoded_filename)
        handler._apply_cors_headers()
        handler.end_headers()
        handler.wfile.write(content)
    except ValueError as error:
        handler.send_json({"ok": False, "error": str(error)}, 400)
    except Exception as error:
        print(f"❌ 远程图片导入失败：{error}")
        handler.send_json({"ok": False, "error": "远程图片导入失败"}, 502)


def handle_video(
    handler,
    filename,
    *,
    Path,
    _ARCHIVE_VIDEO_EXTENSIONS,
    _resolve_archive_video_file,
    _resolve_download_file,
    mimetypes,
    os,
    re,
    safe_basename,
    urllib,
):
    """Serve an archived video with byte-range support for the canvas player."""
    raw_path = urllib.parse.unquote(str(filename or '').strip()).lstrip('/\\')
    safe_name = safe_basename(raw_path)
    if Path(safe_name).suffix.lower() not in _ARCHIVE_VIDEO_EXTENSIONS:
        handler.send_error(404, 'Video not found')
        return
    filepath = _resolve_archive_video_file(raw_path)
    if not filepath and '/' not in raw_path.replace('\\', '/'):
        filepath = _resolve_download_file(safe_name)
    if not filepath or not os.path.isfile(filepath):
        handler.send_error(404, 'Video not found')
        return

    file_size = os.path.getsize(filepath)
    start = 0
    end = max(0, file_size - 1)
    range_header = str(handler.headers.get('Range') or '').strip()
    partial = False
    if range_header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
        if not match:
            handler.send_error(416, 'Invalid Range')
            return
        raw_start, raw_end = match.groups()
        if raw_start:
            start = int(raw_start)
            end = int(raw_end) if raw_end else end
        elif raw_end:
            suffix_length = int(raw_end)
            start = max(0, file_size - suffix_length)
        if start >= file_size or start > end:
            handler.send_response(416)
            handler.send_header('Content-Range', f'bytes */{file_size}')
            handler.end_headers()
            return
        end = min(end, file_size - 1)
        partial = True

    content_length = max(0, end - start + 1)
    handler.send_response(206 if partial else 200)
    handler.send_header('Content-Type', mimetypes.guess_type(str(filepath))[0] or 'video/mp4')
    handler.send_header('Accept-Ranges', 'bytes')
    handler.send_header('Content-Length', str(content_length))
    if partial:
        handler.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
    handler._apply_cors_headers()
    handler.end_headers()
    if handler.command == 'HEAD' or content_length <= 0:
        return
    try:
        with open(filepath, 'rb') as stream:
            stream.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        # Native video players routinely close Range requests after reading metadata.
        return


def handle_archive_image(handler, rel_path, *, _resolve_archive_image_file, mimetypes):
    """Archive-relative original / browser preview, using the same image adapter."""
    import os
    return handle_image(handler, rel_path, _resolve_download_file=_resolve_archive_image_file,
                        mimetypes=mimetypes, os=os)


def handle_archive_resource(
    handler,
    rel_path,
    *,
    _ARCHIVE_VIDEO_SIDECAR_MAX_BYTES,
    _ARCHIVE_VIDEO_TEXT_EXTENSIONS,
    _resolve_archive_resource_file,
    urllib,
):
    """Read a prompt TXT/Markdown sidecar from the archive roots only."""
    filepath = _resolve_archive_resource_file(rel_path, _ARCHIVE_VIDEO_TEXT_EXTENSIONS)
    if not filepath:
        handler.send_error(404, 'Archive resource not found')
        return
    try:
        file_size = filepath.stat().st_size
        if file_size > _ARCHIVE_VIDEO_SIDECAR_MAX_BYTES:
            handler.send_error(413, 'Archive resource is too large')
            return
        payload = filepath.read_bytes()
    except OSError:
        handler.send_error(404, 'Archive resource not found')
        return
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/plain; charset=utf-8')
    handler.send_header('Content-Length', str(len(payload)))
    fallback_name = filepath.name.encode('ascii', errors='ignore').decode('ascii') or 'archive-resource.txt'
    fallback_name = fallback_name.replace('"', '_').replace('\\', '_').replace('\r', '_').replace('\n', '_')
    encoded_name = urllib.parse.quote(filepath.name, safe='')
    handler.send_header(
        'Content-Disposition',
        f'inline; filename="{fallback_name}"; filename*=UTF-8\'\'{encoded_name}',
    )
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler._apply_cors_headers()
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(payload)


def handle_source_image(handler, rel_path, *, mimetypes, resolve_source_image):
    """读取 Source_Image 下的远程源本地图片。"""
    filepath = resolve_source_image(rel_path)

    if filepath and filepath.exists():
        content_type = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler._apply_cors_headers()
        handler.end_headers()
        with open(filepath, 'rb') as f:
            handler.wfile.write(f.read())
    else:
        handler.send_error(404, "Source image not found")


def handle_thumb(
    handler,
    parsed,
    *,
    _ARCHIVE_VIDEO_EXTENSIONS,
    _resolve_archive_image_file,
    _resolve_archive_video_file,
    _resolve_download_file,
    ensure_video_webp_thumbnail,
    ensure_webp_thumbnail,
    parse_thumb_request,
    resolve_media_path,
    resolve_source_image,
    shutil,
    urllib,
):
    """Generate and serve an authenticated WebP thumbnail for local media."""
    try:
        params = urllib.parse.parse_qs(parsed.query or "")
        size = int((params.get("w") or params.get("size") or ["420"])[0] or 420)
    except Exception:
        size = 420
    media_path = parse_thumb_request(parsed.path)
    filepath = resolve_media_path(media_path, {
        "archive": _resolve_archive_image_file,
        "video": _resolve_archive_video_file,
        "source": resolve_source_image,
        "image": _resolve_download_file,
    })
    if not filepath:
        handler.send_error(404, "Thumbnail source not found")
        return
    try:
        if filepath.suffix.lower() in _ARCHIVE_VIDEO_EXTENSIONS:
            thumb_path = ensure_video_webp_thumbnail(filepath, size=size)
        else:
            thumb_path = ensure_webp_thumbnail(filepath, size=size)
    except Exception as exc:
        print(f"⚠️ WebP 缩略图生成失败：{exc}")
        handler.send_error(500, "Thumbnail generation failed")
        return

    handler.send_response(200)
    handler.send_header('Content-Type', 'image/webp')
    handler.send_header('Content-Length', str(thumb_path.stat().st_size))
    handler.send_header('Cache-Control', 'public, max-age=31536000, immutable')
    handler._apply_cors_headers()
    handler.end_headers()
    with open(thumb_path, 'rb') as f:
        shutil.copyfileobj(f, handler.wfile)


def handle_google_output(handler, filename, *, DIRECTORY, os):
    """处理 google_outputs 目录的图片请求"""
    filepath = os.path.join(DIRECTORY, 'google_outputs', filename)
    
    if os.path.exists(filepath):
        handler.send_response(200)
        handler.send_header('Content-Type', 'image/png')
        handler._apply_cors_headers()
        handler.end_headers()
        with open(filepath, 'rb') as f:
            handler.wfile.write(f.read())
    else:
        handler.send_error(404, "Image not found")


def handle_gpt_output(handler, filename, *, DIRECTORY, ensure_gpt_preview_image, os, safe_basename):
    """处理 gpt_outputs 目录的图片请求"""
    safe_name = safe_basename(filename)
    preview_path = ensure_gpt_preview_image(safe_name)
    filepath = str(preview_path) if preview_path else os.path.join(DIRECTORY, 'gpt_outputs', safe_name)
    
    if os.path.exists(filepath):
        handler.send_response(200)
        handler.send_header('Content-Type', 'image/png')
        handler._apply_cors_headers()
        handler.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        handler.end_headers()
        with open(filepath, 'rb') as f:
            handler.wfile.write(f.read())
    else:
        handler.send_error(404, "Image not found")
