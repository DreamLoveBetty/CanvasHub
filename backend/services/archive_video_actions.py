"""Gallery actions on archived videos: stable asset ids, hide state and deletion with undo.

Videos are not rows of the image asset index, so they get their own asset id derived from the
public archive path (`video_<sha256[:24]>`). That id keys the shared asset_meta table (hidden),
candidate-set snapshots and delete batches, so the existing undo flow restores them unchanged.
"""
from __future__ import annotations

import hashlib

VIDEO_ASSET_PREFIX = 'video_'
# Sidecars written next to an archived video; reference folders are shared and stay put.
_VIDEO_SIDECAR_SUFFIXES = ('.md', '.txt', '.json')
MAX_VIDEO_DELETE = 60


def video_asset_id(public_path):
    return VIDEO_ASSET_PREFIX + hashlib.sha256(str(public_path).encode('utf-8')).hexdigest()[:24]


def hidden_video_asset_ids(meta):
    """Asset ids of hidden videos from the asset_meta map."""
    return {asset_id for asset_id, row in (meta or {}).items()
            if asset_id.startswith(VIDEO_ASSET_PREFIX) and row.get('hidden')}


def delete_archive_videos(
    paths,
    *,
    resolve_video,
    move_to_trash,
    snapshot_sets,
    remove_from_sets,
    update_meta,
    record_batch,
):
    """Move archived videos and their sidecars to the trash and record an undoable batch."""
    clean_paths = []
    for raw in paths or []:
        path = str(raw or '').strip()
        if path and path not in clean_paths:
            clean_paths.append(path)
    if not clean_paths:
        raise ValueError('缺少视频路径')
    if len(clean_paths) > MAX_VIDEO_DELETE:
        raise ValueError(f'单次最多删除 {MAX_VIDEO_DELETE} 个视频')

    targets = []
    for public_path in clean_paths:
        resolved = resolve_video(public_path)
        if not resolved:
            raise FileNotFoundError(f'视频不存在：{public_path}')
        targets.append((public_path, resolved))

    deleted, missing, skipped, moves = [], [], [], []
    set_snapshots = {}
    asset_ids = []
    assets = []
    for public_path, resolved in targets:
        asset_id = video_asset_id(public_path)
        asset_ids.append(asset_id)
        assets.append({'id': asset_id, 'asset_id': asset_id, 'file': resolved.name, 'kind': 'video', 'path': public_path})
        for snapshot in snapshot_sets(asset_id):
            set_id = str(snapshot.get('set_id') or '').strip()
            if set_id:
                set_snapshots[set_id] = snapshot
        move_to_trash(resolved, deleted, missing, skipped, moves=moves)
        for suffix in _VIDEO_SIDECAR_SUFFIXES:
            sidecar = resolved.with_suffix(suffix)
            if sidecar.exists():
                move_to_trash(sidecar, deleted, missing, skipped, moves=moves)

    set_updates = 0
    for asset_id in asset_ids:
        update_meta(asset_id, hidden=True)
        set_updates += remove_from_sets(asset_id)

    journal = record_batch({
        'asset_ids': asset_ids,
        'assets': assets,
        'moves': moves,
        'task_snapshots': [],
        'set_snapshots': list(set_snapshots.values()),
        'deleted_files': deleted,
        'missing_files': missing,
        'skipped_files': skipped,
    })
    return {
        'ok': True,
        'asset_ids': asset_ids,
        'delete_batch_id': journal.get('batch_id'),
        'undo_id': journal.get('batch_id'),
        'deleted_files': deleted,
        'missing_files': missing,
        'skipped_files': skipped,
        'set_updates': set_updates,
        'message': '视频已移入废纸篓' if deleted else '视频已从资产库移除',
    }
