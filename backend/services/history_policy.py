"""Pure policies shared by history and existing status/asset/pagination callers.

Preserve legacy coercion, visibility, and key semantics. No storage or HTTP work;
deduplication receives callbacks to retain the server's compatibility hooks.
"""

import json


def task_should_render(status, result_files):
    if result_files:
        return True
    status_key = str(status or '').strip().lower()
    return status_key in {
        'pending',
        'preparing',
        'processing',
        'fallback_running',
        'queued',
        'running',
    }


def page_int(raw_value, default, minimum=0, maximum=500):
    try:
        value = int(raw_value)
    except Exception:
        return default
    return max(minimum, min(value, maximum))


def task_result_files(task):
    result_files = task.get('result_files') or []
    if isinstance(result_files, str):
        try:
            parsed = json.loads(result_files)
            result_files = parsed if isinstance(parsed, list) else []
        except Exception:
            result_files = [result_files]
    if not isinstance(result_files, list):
        result_files = []
    result_files = [str(name or '').strip() for name in result_files if str(name or '').strip()]

    primary_output = str(task.get('result_file') or task.get('output_file') or '').strip()
    if not result_files and primary_output:
        result_files = [primary_output]
    if not primary_output and result_files:
        primary_output = result_files[0]
    return result_files, primary_output


def task_timestamp(task):
    try:
        return int(task.get('created_at') or task.get('timestamp') or 0)
    except Exception:
        return 0


def dedupe_key(task, *, task_result_files, task_timestamp, safe_basename):
    result_files, primary_output = task_result_files(task)
    filename = safe_basename(primary_output or (result_files[0] if result_files else ''))
    if filename:
        return ('file', filename)

    task_id = str(task.get('task_id') or '').strip()
    if task_id:
        return ('task', task_id)

    prompt = str(task.get('prompt') or '')[:120]
    return ('time', task_timestamp(task), prompt)
