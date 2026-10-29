"""Observable stages of a cloud image task, for stage-based progress.

Cloud providers only expose a few real checkpoints (queued, upstream call started,
result received, delivery). Each stage gets an equal share of the bar; the UI may
advance inside the generating stage from the duration estimate but never past it.
"""
from __future__ import annotations

from .task_duration_estimate import ESTIMATED_TASK_TYPES, IN_FLIGHT_STATUSES

PREPARING, GENERATING, SAVING, DELIVERING = 'preparing', 'generating', 'saving', 'delivering'
STAGE_LABELS = {PREPARING: '准备', GENERATING: '生成中', SAVING: '接收并保存', DELIVERING: '发送 Telegram'}


def _stage_kind(stage, status):
    stage = str(stage or '').lower()
    if stage in ('queued', 'preparing') or (not stage and status in ('queued', 'preparing')):
        return PREPARING
    if stage.startswith('calling_') or stage in ('started', 'fallback_running') or status == 'fallback_running':
        return GENERATING
    if stage.startswith(('receiving_', 'downloading_')) or stage == 'saving':
        return SAVING
    if stage == 'sending_telegram':
        return DELIVERING
    return None


def progress_stage(task):
    """{'stage_index', 'stage_count', 'stage_label', 'stage_kind'} for an in-flight cloud task, else None."""
    task = task or {}
    if task.get('type') not in ESTIMATED_TASK_TYPES or task.get('status') not in IN_FLIGHT_STATUSES:
        return None
    kind = _stage_kind(task.get('stage'), task.get('status'))
    if kind is None:
        return None
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    stages = [PREPARING, GENERATING, SAVING]
    if params.get('telegram_enabled') is not False or kind == DELIVERING:
        stages.append(DELIVERING)
    return {
        'stage_index': stages.index(kind) + 1,
        'stage_count': len(stages),
        'stage_label': STAGE_LABELS[kind],
        'stage_kind': kind,
    }
