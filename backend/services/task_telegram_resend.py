"""Resend already archived generation results to Telegram without regenerating."""
from __future__ import annotations

import threading
from pathlib import Path

_RESEND_GUARD = threading.Lock()
_RESEND_IN_FLIGHT: set[str] = set()

RESENDABLE_STATUSES = {
    'telegram_failed',
    'succeeded',
    'success',
    'succeeded_no_telegram',
}


class TaskTelegramResendError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def task_result_names(task, *, task_result_files):
    result_files, primary = task_result_files(task)
    names = [str(name or '').strip() for name in (result_files or []) if str(name or '').strip()]
    primary = str(primary or '').strip()
    if primary and primary not in names:
        names.insert(0, primary)
    return names, primary


def task_has_trusted_archive(task, *, task_result_files):
    names, _primary = task_result_names(task, task_result_files=task_result_files)
    return bool(names)


def should_resend_telegram_instead_of_retry(task, *, task_result_files):
    status = str((task or {}).get('status') or '')
    return status == 'telegram_failed' and task_has_trusted_archive(task, task_result_files=task_result_files)


def begin_task_resend(task_id):
    ident = str(task_id or '').strip()
    if not ident:
        return False
    with _RESEND_GUARD:
        if ident in _RESEND_IN_FLIGHT:
            return False
        _RESEND_IN_FLIGHT.add(ident)
        return True


def end_task_resend(task_id):
    ident = str(task_id or '').strip()
    with _RESEND_GUARD:
        _RESEND_IN_FLIGHT.discard(ident)


def _path_is_allowed(path, roots):
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        return False
    for root in roots:
        if not root:
            continue
        try:
            root_resolved = Path(root).expanduser().resolve()
        except Exception:
            continue
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


def resolve_trusted_task_file_from_names(
    task,
    filename,
    allowed_names,
    *,
    DIRECTORY,
    Path,
    _resolve_archive_image_file,
    _resolve_download_image,
    resolve_editable_file,
    safe_basename,
    image_archive_dir=None,
):
    task_type = str((task or {}).get('type') or '')
    raw = str(filename or '').strip()
    if not raw:
        raise TaskTelegramResendError('缺少可发送的文件', 400)
    check_name = raw if task_type == 'gpt-file' else safe_basename(raw)
    allowed = {str(name or '').strip() for name in (allowed_names or []) if str(name or '').strip()}
    if check_name not in allowed and raw not in allowed:
        raise TaskTelegramResendError('文件不属于该任务', 403)

    resolved_by_helper = False
    if task_type == 'gpt-file':
        file_path = resolve_editable_file(raw)
        resolved_by_helper = True
    elif task_type in ('gpt', 'gpt-edit'):
        candidate = Path(DIRECTORY) / 'gpt_outputs' / safe_basename(raw)
        if candidate.exists():
            file_path = candidate
        else:
            file_path = _resolve_download_image(safe_basename(raw))
            resolved_by_helper = True
    else:
        file_path = _resolve_download_image(safe_basename(raw))
        resolved_by_helper = True

    if not file_path or not Path(file_path).exists():
        raise TaskTelegramResendError('原图文件不存在', 404)

    path = Path(file_path)
    if not resolved_by_helper:
        allowed_roots = [Path(DIRECTORY), Path(DIRECTORY) / 'gpt_outputs']
        if image_archive_dir:
            allowed_roots.append(Path(image_archive_dir))
        if not _path_is_allowed(path, allowed_roots):
            raise TaskTelegramResendError('文件不在允许的归档目录内', 403)
    return path


def resend_task_telegram(
    task_id,
    *,
    DIRECTORY,
    Path,
    _record_generation_event,
    _resolve_archive_image_file,
    _resolve_download_image,
    get_task,
    resolve_editable_file,
    safe_basename,
    send_telegram,
    task_result_files,
    update_task,
    image_archive_dir=None,
    requested_file=None,
):
    """Send trusted archived files for a task. Never calls a generation provider."""
    ident = str(task_id or '').strip()
    if not ident:
        raise TaskTelegramResendError('缺少 task_id', 400)
    task = get_task(ident)
    if not task:
        raise TaskTelegramResendError('找不到任务。', 404)
    status = str(task.get('status') or '')
    if status not in RESENDABLE_STATUSES:
        raise TaskTelegramResendError('只有已保存结果的任务可以补发 Telegram。', 400)
    names, primary = task_result_names(task, task_result_files=task_result_files)
    if not names:
        raise TaskTelegramResendError('没有可补发的归档文件，无法只补发。', 400)

    selected = [requested_file] if requested_file else names
    if not begin_task_resend(ident):
        raise TaskTelegramResendError('该任务正在补发中，请稍后再试。', 409)

    sent = []
    try:
        prompt = str(task.get('prompt') or '').strip()
        caption = '📸 Original'
        if task.get('type'):
            caption += f" | {task.get('type')}"
        if prompt:
            trimmed = prompt[:420] + ('...' if len(prompt) > 420 else '')
            caption += f"\n{trimmed}"
        for filename in selected:
            path = resolve_trusted_task_file_from_names(
                task,
                filename,
                names,
                DIRECTORY=DIRECTORY,
                Path=Path,
                _resolve_archive_image_file=_resolve_archive_image_file,
                _resolve_download_image=_resolve_download_image,
                resolve_editable_file=resolve_editable_file,
                safe_basename=safe_basename,
                image_archive_dir=image_archive_dir,
            )
            ok = send_telegram(None, str(path), caption[:900])
            if not ok:
                _record_generation_event(
                    ident, 'telegram_resend_failed', 'Telegram 补发失败',
                    stage='telegram_failed', severity='error',
                    payload={'filename': Path(path).name},
                )
                raise TaskTelegramResendError('Telegram 发送失败', 502)
            sent.append(Path(path).name)
        update_task(
            ident,
            'succeeded',
            error='',
            stage='done',
            progress_text='已补发到 Telegram',
            transport_error_type='',
        )
        _record_generation_event(
            ident, 'telegram_resend_succeeded', '已补发到 Telegram',
            stage='done',
            payload={'filenames': sent, 'regenerated': False},
        )
        refreshed = get_task(ident) or task
        refreshed['ok'] = True
        refreshed['resent'] = True
        refreshed['regenerated'] = False
        refreshed['message'] = '已补发到 Telegram，未重新生成。'
        refreshed['sent_files'] = sent
        return refreshed
    finally:
        end_task_resend(ident)
