"""Media lookup, previews and original archive paths.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _resolve_download_file(filename, *, image_lookup_roots, time):
    if not filename:
        return None

    for downloads_root in image_lookup_roots():
        direct_path = downloads_root / filename
        if direct_path.exists():
            return direct_path

        today_path = downloads_root / time.strftime('%Y-%m-%d') / filename
        if today_path.exists():
            return today_path

        try:
            subdirs = sorted(
                (p for p in downloads_root.iterdir() if p.is_dir()),
                key=lambda p: p.name,
                reverse=True,
            )
        except FileNotFoundError:
            continue

        for subdir in subdirs:
            candidate = subdir / filename
            if candidate.exists():
                return candidate

    return None


def _resolve_archive_resource_file(rel_path, extensions, *, archive_scan_roots, urllib):
    """Resolve a regular archive file while rejecting traversal and symlink hops."""
    raw = urllib.parse.unquote(str(rel_path or '').strip()).replace('\\', '/')
    if not raw or raw.startswith('/') or '\x00' in raw:
        return None
    path_parts = raw.split('/')
    if any(not part or part in {'.', '..'} for part in path_parts):
        return None

    roots = archive_scan_roots()
    root_map = {key: path for key, path in roots}
    if path_parts[0] in root_map:
        if len(path_parts) < 2:
            return None
        candidates = [(root_map[path_parts[0]], path_parts[1:])]
    else:
        candidates = [(root_path, path_parts) for _, root_path in roots]

    allowed_extensions = {str(extension or '').lower() for extension in (extensions or ())}
    for root_path, relative_parts in candidates:
        try:
            root = root_path.expanduser().resolve()
            candidate = root.joinpath(*relative_parts)
        except Exception:
            continue
        cursor = root
        unsafe = False
        for part in relative_parts:
            cursor = cursor / part
            try:
                if cursor.is_symlink():
                    unsafe = True
                    break
            except OSError:
                unsafe = True
                break
        if unsafe:
            continue
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved != root and root not in resolved.parents:
            continue
        if not resolved.is_file() or resolved.is_symlink():
            continue
        if allowed_extensions and resolved.suffix.lower() not in allowed_extensions:
            continue
        return resolved
    return None


def _resolve_archive_image_file(rel_path, *, _ARCHIVE_IMAGE_EXTENSIONS, _resolve_archive_resource_file):
    return _resolve_archive_resource_file(rel_path, _ARCHIVE_IMAGE_EXTENSIONS)


def _resolve_download_image(filename, *, _resolve_download_file):
    """Compatibility wrapper for history original-image export."""
    return _resolve_download_file(filename)


def save_thumbnail(image_path, output_filename, *, DIRECTORY, Image, THUMB_MAX_SIDE, os):
    """为历史记录生成缩略图到 google_outputs/thumb_*.png"""
    try:
        google_outputs_dir = os.path.join(DIRECTORY, 'google_outputs')
        os.makedirs(google_outputs_dir, exist_ok=True)
        thumb_path = os.path.join(google_outputs_dir, f'thumb_{output_filename}')
        with Image.open(image_path) as img:
            # 与 /thumb/ 的 420px 上限对齐，让 sidecar 可以直接作为图库缩略图转码源
            img.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
            img.save(thumb_path, 'PNG', quality=80)
        print(f"🖼️ 缩略图已保存：{thumb_path}")
        return True
    except Exception as e:
        print(f"⚠️ 缩略图生成失败：{e}")
        return False


def safe_basename(filename, *, os):
    return os.path.basename(str(filename or '').strip())


def ensure_gpt_preview_image(filename, max_side=2048, *, DIRECTORY, Image, Path, safe_basename):
    """为 GPT 原图生成查看页用 2K 预览图，并缓存到 gpt_outputs。"""
    safe_name = safe_basename(filename)
    if not safe_name.endswith('_preview.png'):
        return None

    preview_path = Path(DIRECTORY) / 'gpt_outputs' / safe_name
    if preview_path.exists():
        return preview_path

    source_name = safe_name.replace('_preview.png', '.png')
    source_path = Path(DIRECTORY) / 'gpt_outputs' / source_name
    if not source_path.exists():
        return None

    try:
        with Image.open(source_path) as img:
            img = img.convert('RGB') if img.mode not in ('RGB', 'RGBA') else img.copy()
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            img.save(preview_path, 'PNG', optimize=True)
        print(f"🖼️ GPT 2K 预览已生成：{preview_path.name}")
        return preview_path
    except Exception as e:
        print(f"⚠️ GPT 2K 预览生成失败：{e}")
        return None
