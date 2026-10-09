"""Asset file, history and metadata maintenance policies.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
        resolved_root = root.expanduser().resolve()
        return resolved == resolved_root or resolved_root in resolved.parents
    except Exception:
        return False


def _allowed_asset_delete_roots(*, DIRECTORY, Path, image_lookup_roots):
    roots = [
        Path(root).expanduser()
        for root in image_lookup_roots()
    ]
    roots.extend([
        Path(DIRECTORY) / 'gpt_outputs',
        Path(DIRECTORY) / 'google_outputs',
    ])
    return roots


def _unique_trash_path(filename, *, Path, safe_basename, time, uuid):
    trash_dir = Path.home() / '.Trash'
    trash_dir.mkdir(parents=True, exist_ok=True)
    clean_name = safe_basename(filename) or f"deleted_asset_{int(time.time())}"
    target = trash_dir / clean_name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(1, 1000):
        candidate = trash_dir / f"{stem} {index}{suffix}"
        if not candidate.exists():
            return candidate
    return trash_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _move_asset_file_to_trash(
    path,
    deleted,
    missing,
    skipped,
    moves=None,
    *,
    Path,
    _allowed_asset_delete_roots,
    _path_is_inside,
    _unique_trash_path,
    shutil,
):
    if not path:
        return
    candidate = Path(path).expanduser()
    if not candidate.exists():
        missing.append(candidate.name)
        return
    if not candidate.is_file():
        skipped.append(candidate.name)
        return
    if not any(_path_is_inside(candidate, root) for root in _allowed_asset_delete_roots()):
        skipped.append(candidate.name)
        return
    target = _unique_trash_path(candidate.name)
    shutil.move(str(candidate), str(target))
    deleted.append(candidate.name)
    if isinstance(moves, list):
        moves.append({
            "original_path": str(candidate),
            "trash_path": str(target),
            "filename": candidate.name,
        })


def _asset_delete_candidates(
    asset,
    *,
    DIRECTORY,
    Path,
    _resolve_archive_image_file,
    _resolve_download_file,
    safe_basename,
    urllib,
):
    filename = safe_basename(asset.get('file') or urllib.parse.urlparse(str(asset.get('imageUrl') or '')).path.split('/')[-1])
    archive_rel = str(asset.get('archiveRelPath') or asset.get('archive_rel_path') or '').strip()
    archive_path = _resolve_archive_image_file(archive_rel)
    if not filename and not archive_path:
        return []

    provider = str(asset.get('provider') or '').lower()
    project_gpt_dir = Path(DIRECTORY) / 'gpt_outputs'
    project_google_dir = Path(DIRECTORY) / 'google_outputs'
    candidates = []

    if archive_path:
        candidates.append(archive_path)
        candidates.append(archive_path.with_suffix('.txt'))

    original = _resolve_download_file(filename)
    if original:
        candidates.append(original)
        candidates.append(original.with_suffix('.txt'))

    if provider == 'gpt':
        gpt_file = project_gpt_dir / filename
        candidates.append(gpt_file)
        candidates.append(gpt_file.with_suffix('.txt'))
        candidates.append(project_gpt_dir / f"{Path(filename).stem}_thumb.png")
        candidates.append(project_gpt_dir / f"{Path(filename).stem}_preview.png")
    else:
        candidates.append(project_google_dir / f"thumb_{filename}")

    deduped = []
    seen = set()
    for path in candidates:
        key = str(Path(path).expanduser())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(Path(path))
    return deduped


def _asset_filename(asset, *, safe_basename, urllib):
    return safe_basename(
        asset.get('file')
        or urllib.parse.urlparse(str(asset.get('imageUrl') or asset.get('image_url') or '')).path.split('/')[-1]
    )


def _asset_url_file_exists(
    url,
    *,
    DIRECTORY,
    Path,
    _resolve_archive_image_file,
    _resolve_download_file,
    safe_basename,
    urllib,
):
    raw_url = str(url or '').strip()
    if not raw_url:
        return False
    if raw_url.startswith(('http://', 'https://', 'data:', 'blob:')):
        return True
    parsed = urllib.parse.urlparse(raw_url)
    path = urllib.parse.unquote(parsed.path or raw_url)
    filename = safe_basename(path)
    if path.startswith('/archive_image/'):
        return bool(_resolve_archive_image_file(path[len('/archive_image/'):]))
    if path.startswith('/gpt_outputs/') and filename:
        return (Path(DIRECTORY) / 'gpt_outputs' / filename).exists() or bool(_resolve_download_file(filename))
    if path.startswith('/google_outputs/') and filename:
        return (Path(DIRECTORY) / 'google_outputs' / filename).exists()
    if path.startswith('/image/') and filename:
        return bool(_resolve_download_file(filename))
    if filename:
        return bool(_resolve_download_file(filename))
    return True


def _asset_file_exists(
    asset,
    *,
    DIRECTORY,
    Path,
    _asset_filename,
    _asset_url_file_exists,
    _resolve_archive_image_file,
    _resolve_download_file,
):
    filename = _asset_filename(asset)
    provider = str(asset.get('provider') or '').lower()
    archive_rel = str(asset.get('archiveRelPath') or asset.get('archive_rel_path') or '').strip()
    if archive_rel and _resolve_archive_image_file(archive_rel):
        return True
    if filename:
        if provider == 'gpt':
            if (Path(DIRECTORY) / 'gpt_outputs' / filename).exists():
                return True
            if _resolve_download_file(filename):
                return True
            if _asset_url_file_exists(asset.get('imageUrl') or asset.get('image_url') or asset.get('thumbUrl') or ''):
                return True
            return False
        if _resolve_download_file(filename):
            return True
        if (Path(DIRECTORY) / 'google_outputs' / filename).exists():
            return True
        if (Path(DIRECTORY) / 'gpt_outputs' / filename).exists():
            return True
    return _asset_url_file_exists(asset.get('imageUrl') or asset.get('image_url') or asset.get('thumbUrl') or '')


def _remove_old_history_asset(asset, filename, removed_lines=None, *, DIRECTORY, Path, json, re, safe_basename):
    timestamp = int(asset.get('createdAt') or asset.get('created_at') or 0)
    if not timestamp:
        raw_task_id = str(asset.get('taskId') or asset.get('task_id') or '')
        match = re.match(r'old_(\d+)', raw_task_id)
        timestamp = int(match.group(1)) if match else 0
    if not timestamp:
        return False

    history_path = Path(DIRECTORY) / 'history.jsonl'
    if not history_path.exists():
        return False

    removed = False
    kept = []
    with open(history_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                kept.append(line)
                continue
            same_time = int(item.get('timestamp') or item.get('created_at') or -1) == timestamp
            same_file = safe_basename(item.get('output_file') or item.get('result_file') or '') == filename
            if same_time and same_file:
                removed = True
                if isinstance(removed_lines, list):
                    removed_lines.append(line.rstrip('\n'))
                continue
            kept.append(line)

    if removed:
        with open(history_path, 'w', encoding='utf-8') as f:
            f.writelines(kept)
    return removed


def _restore_old_history_lines(lines, *, DIRECTORY, Path):
    clean_lines = [str(line or '').strip() for line in (lines or []) if str(line or '').strip()]
    if not clean_lines:
        return 0
    history_path = Path(DIRECTORY) / 'history.jsonl'
    existing = set()
    if history_path.exists():
        with open(history_path, 'r', encoding='utf-8') as f:
            existing = {line.strip() for line in f if line.strip()}
    restored = 0
    with open(history_path, 'a', encoding='utf-8') as f:
        for line in clean_lines:
            if line in existing:
                continue
            f.write(line + '\n')
            existing.add(line)
            restored += 1
    return restored


def _remove_asset_from_task(
    asset,
    removed_history=None,
    *,
    _asset_filename,
    _remove_old_history_asset,
    get_task,
    json,
    update_task_fields,
):
    task_id = str(asset.get('taskId') or asset.get('task_id') or '').strip()
    filename = _asset_filename(asset)
    if not task_id or not filename:
        return False
    if task_id.startswith('old_'):
        return _remove_old_history_asset(asset, filename, removed_history)
    task = get_task(task_id)
    if not task:
        return False
    files = list(task.get('result_files') or [])
    primary = task.get('result_file') or ''
    if not files and primary:
        files = [primary]
    if filename not in files and filename != primary:
        return False
    remaining = [item for item in files if item != filename]
    if not remaining:
        update_task_fields(
            task_id,
            result_file='',
            result_files=json.dumps([], ensure_ascii=False),
            progress_text='图片资产已从图库移除',
        )
        return True
    update_task_fields(
        task_id,
        result_file=remaining[0],
        result_files=json.dumps(remaining, ensure_ascii=False),
        progress_text='部分图片已从图库移除',
    )
    return True


def _remove_assets_from_tasks(
    assets,
    removed_history=None,
    *,
    _asset_filename,
    _remove_old_history_asset,
    get_task,
    json,
    safe_basename,
    update_task_fields,
):
    grouped = {}
    old_assets = []
    for asset in assets or []:
        task_id = str(asset.get('taskId') or asset.get('task_id') or '').strip()
        filename = _asset_filename(asset)
        if not task_id or not filename:
            continue
        if task_id.startswith('old_'):
            old_assets.append((asset, filename))
            continue
        grouped.setdefault(task_id, set()).add(filename)

    changed = 0
    for asset, filename in old_assets:
        if _remove_old_history_asset(asset, filename, removed_history):
            changed += 1

    for task_id, filenames in grouped.items():
        task = get_task(task_id)
        if not task:
            continue
        files = list(task.get('result_files') or [])
        primary = task.get('result_file') or ''
        if not files and primary:
            files = [primary]
        if not files:
            continue
        remaining = [item for item in files if safe_basename(item) not in filenames]
        if len(remaining) == len(files):
            continue
        if not remaining:
            update_task_fields(
                task_id,
                result_file='',
                result_files=json.dumps([], ensure_ascii=False),
                progress_text='图片资产已从图库移除',
            )
        else:
            update_task_fields(
                task_id,
                result_file=remaining[0],
                result_files=json.dumps(remaining, ensure_ascii=False),
                progress_text='部分图片已从图库移除',
            )
        changed += 1
    return changed


def _cleanup_lineage_refs(valid_asset_ids, *, get_all_tasks, json, update_task_fields):
    valid_ids = {str(value or '').strip() for value in (valid_asset_ids or []) if str(value or '').strip()}
    removed = 0
    updated_tasks = 0
    for task in get_all_tasks(limit=3000, offset=0):
        task_id = str(task.get('task_id') or '').strip()
        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        lineage = params.get('lineage') if isinstance(params.get('lineage'), dict) else {}
        refs = lineage.get('reference_assets') or lineage.get('referenceAssets') or []
        if not task_id or not isinstance(refs, list):
            continue
        next_refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip()
            if ref_id and ref_id not in valid_ids:
                removed += 1
                continue
            next_refs.append(ref)
        if len(next_refs) == len(refs):
            continue
        asset_ids = []
        task_ids = []
        for ref in next_refs:
            ref_id = str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip()
            ref_task_id = str(ref.get('task_id') or ref.get('taskId') or '').strip()
            if ref_id and ref_id not in asset_ids:
                asset_ids.append(ref_id)
            if ref_task_id and ref_task_id not in task_ids:
                task_ids.append(ref_task_id)
        lineage['reference_assets'] = next_refs
        lineage['referenceAssets'] = next_refs
        lineage['reference_asset_ids'] = asset_ids
        lineage['referenceAssetIds'] = asset_ids
        lineage['source_task_ids'] = task_ids
        lineage['sourceTaskIds'] = task_ids
        params['lineage'] = lineage
        update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))
        updated_tasks += 1
    return {"removed_refs": removed, "updated_tasks": updated_tasks}


def _cleanup_no_image_history(
    *,
    DIRECTORY,
    Path,
    _history_task_should_render,
    delete_task,
    get_all_tasks,
    json,
    safe_basename,
):
    removed = 0
    for task in get_all_tasks(limit=3000, offset=0):
        result_files = task.get('result_files') or []
        primary = task.get('result_file') or ''
        if not result_files and primary:
            result_files = [primary]
        if _history_task_should_render(task.get('status'), result_files):
            continue
        task_id = str(task.get('task_id') or '').strip()
        if task_id and delete_task(task_id):
            removed += 1

    history_path = Path(DIRECTORY) / 'history.jsonl'
    if history_path.exists():
        kept = []
        old_removed = 0
        with open(history_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    kept.append(line)
                    continue
                filename = safe_basename(item.get('output_file') or item.get('result_file') or '')
                status = item.get('status') or 'success'
                if not _history_task_should_render(status, [filename] if filename else []):
                    old_removed += 1
                    continue
                kept.append(line)
        if old_removed:
            with open(history_path, 'w', encoding='utf-8') as f:
                f.writelines(kept)
            removed += old_removed
    return removed


def _restore_trash_move(move, *, Path, _allowed_asset_delete_roots, _path_is_inside, shutil):
    original_raw = str(move.get('original_path') or '').strip()
    trash_raw = str(move.get('trash_path') or '').strip()
    if not original_raw or not trash_raw:
        return "skipped"
    original = Path(original_raw).expanduser()
    trash_path = Path(trash_raw).expanduser()
    trash_root = Path.home() / '.Trash'
    if not _path_is_inside(trash_path, trash_root):
        return "skipped"
    if not any(_path_is_inside(original, root) for root in _allowed_asset_delete_roots()):
        return "skipped"
    if original.exists():
        return "exists"
    if not trash_path.exists() or not trash_path.is_file():
        return "missing"
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(trash_path), str(original))
    return "restored"
