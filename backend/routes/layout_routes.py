"""Layout HTTP handlers with explicit resource dependencies, not server imports."""

import os
from pathlib import Path
import shutil
import urllib.parse


def handle_layout_draft_get(handler, parsed, *, load_draft, get_file) -> None:
    """读取排版草稿、预览图、导出图或草稿资产。"""
    parts = parsed.path.strip('/').split('/')
    if len(parts) < 4:
        handler.send_json({"error": "缺少草稿 ID"}, 400)
        return

    draft_id = parts[3]
    try:
        if len(parts) == 4:
            handler.send_json(load_draft(draft_id))
            return

        kind = parts[4]
        if kind in ('preview', 'export'):
            handler.send_binary_file(get_file(draft_id, kind))
            return
        if kind == 'assets' and len(parts) >= 6:
            asset_name = urllib.parse.unquote(parts[5])
            handler.send_binary_file(get_file(draft_id, 'asset', asset_name))
            return

        handler.send_json({"error": "排版草稿资源不存在"}, 404)
    except FileNotFoundError as e:
        handler.send_json({"error": str(e)}, 404)
    except Exception as e:
        handler.send_json({"error": str(e)}, 400)


def handle_layout_draft_list(handler, parsed, *, list_drafts) -> None:
    """列出排版草稿。"""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        limit = int(query.get('limit', [50])[0])
        offset = int(query.get('offset', [0])[0])
        handler.send_json({"drafts": list_drafts(limit=limit, offset=offset)})
    except Exception as e:
        handler.send_json({"error": str(e)}, 400)


def handle_layout_draft_post(handler, parsed, *, create_draft, update_draft, save_asset) -> None:
    """创建或更新排版草稿。"""
    parts = parsed.path.strip('/').split('/')
    try:
        data = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "请求体格式错误"}, 400)
        return

    try:
        if parsed.path == '/api/layout/drafts':
            draft = create_draft(
                title=str(data.get('title') or '排版工作区'),
                node_id=str(data.get('node_id') or ''),
                project=data.get('project') or {},
                preview_data_url=str(data.get('preview_data_url') or ''),
                export_data_url=str(data.get('export_data_url') or ''),
            )
            handler.send_json(draft, 201)
            return

        if len(parts) < 4:
            handler.send_json({"error": "缺少草稿 ID"}, 400)
            return

        draft_id = parts[3]
        if len(parts) == 4:
            draft = update_draft(
                draft_id,
                title=data.get('title') if 'title' in data else None,
                node_id=data.get('node_id') if 'node_id' in data else None,
                project=data.get('project') if 'project' in data else None,
                preview_data_url=str(data.get('preview_data_url') or ''),
                export_data_url=str(data.get('export_data_url') or ''),
            )
            handler.send_json(draft)
            return

        action = parts[4]
        if action == 'asset':
            asset = save_asset(
                draft_id,
                filename=str(data.get('filename') or ''),
                data_url=str(data.get('data_url') or ''),
            )
            handler.send_json(asset, 201)
            return

        if action in ('preview', 'export'):
            draft = update_draft(
                draft_id,
                preview_data_url=str(data.get('data_url') or '') if action == 'preview' else '',
                export_data_url=str(data.get('data_url') or '') if action == 'export' else '',
            )
            handler.send_json(draft)
            return

        if action == 'publish':
            handler.send_json(handler.publish_layout_draft(draft_id, data), 201)
            return

        handler.send_json({"error": "排版草稿操作不存在"}, 404)
    except FileNotFoundError as e:
        handler.send_json({"error": str(e)}, 404)
    except Exception as e:
        handler.send_json({"error": str(e)}, 400)


def handle_layout_fonts(handler, *, font_dir: Path) -> None:
    """列出项目内置字体，供排版编辑器按需加载。"""
    extensions = {'.ttf', '.otf', '.ttc', '.woff', '.woff2'}

    def infer_weight(stem):
        lower = stem.lower()
        if 'thin' in lower:
            return 100
        if 'extralight' in lower or lower.endswith('-el'):
            return 200
        if 'light' in lower or lower.endswith('-l'):
            return 300
        if 'medium' in lower or lower.endswith('-m'):
            return 500
        if 'semibold' in lower or lower.endswith('-sb') or 'demibold' in lower:
            return 600
        if 'extrabold' in lower or lower.endswith('-h'):
            return 800
        if 'black' in lower or 'heavy' in lower:
            return 900
        if 'bold' in lower or lower.endswith('-b'):
            return 700
        return 400

    def normalize_family(stem):
        family = stem
        suffixes = [
            'VariableFont_wght',
            'ExtraLight',
            'ExtraBold',
            'SemiBold',
            'Regular',
            'Medium',
            'Light',
            'Black',
            'Heavy',
            'Bold',
            'Thin',
            'EL',
            'SB',
            'B',
            'H',
            'L',
            'M',
            'R',
        ]
        changed = True
        while changed:
            changed = False
            for suffix in suffixes:
                for separator in ('-', '_', ' '):
                    tail = f'{separator}{suffix}'
                    if family.endswith(tail):
                        family = family[:-len(tail)]
                        changed = True
        return family.strip('-_ ') or stem

    if not font_dir.exists():
        handler.send_json({"fonts": []})
        return

    paths = sorted(font_dir.iterdir(), key=lambda item: item.name.lower())
    web_stems = {path.stem for path in paths if path.suffix.lower() == '.woff2' and path.is_file()}
    groups = {}
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        # An offline-prepared companion replaces only the same-stem native face.
        # Keep the original file and family name, but do not register both sources.
        if path.suffix.lower() != '.woff2' and path.stem in web_stems:
            continue
        stem = path.stem
        family = normalize_family(stem)
        face = {
            "file": path.name,
            "url": f"/font/{urllib.parse.quote(path.name)}",
            "weight": infer_weight(stem),
            "style": "normal",
        }
        groups.setdefault(family, {
            "family": family,
            "label": family,
            "faces": [],
        })["faces"].append(face)

    fonts = sorted(groups.values(), key=lambda item: item["label"].lower())
    handler.send_json({"fonts": fonts})


def handle_layout_font_file(handler, encoded_name: str, *, font_dir: Path,
                            head_only: bool = False) -> None:
    """Serve a catalog font after the caller applies the existing authentication."""
    content_types = {
        '.ttf': 'font/ttf',
        '.otf': 'font/otf',
        '.ttc': 'font/collection',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
    }
    name = urllib.parse.unquote(encoded_name)
    if not name or any(char in name for char in ('/', '\\', '\x00', ':')):
        handler.send_error(404, 'Font not found')
        return
    content_type = content_types.get(Path(name).suffix.lower())
    if not content_type:
        handler.send_error(404, 'Font not found')
        return

    try:
        root = font_dir.resolve()
        path = (root / name).resolve()
        # The catalog is flat. Reject traversal and symlinks outside its root.
        if path.parent != root or not path.is_file():
            handler.send_error(404, 'Font not found')
            return
        stream = path.open('rb')
    except (OSError, ValueError, RuntimeError):
        handler.send_error(404, 'Font not found')
        return

    with stream:
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
        handler.send_header('Cache-Control', 'private, max-age=60')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.end_headers()
        if not head_only:
            # CJK font collections can exceed 100 MB; do not read them all at once.
            shutil.copyfileobj(stream, handler.wfile, length=64 * 1024)
