"""Read and merge history using explicit storage and task-policy dependencies.

Keep the existing batching, legacy compatibility, ordering, and error boundaries.
Pagination, HTTP responses, and task formatting remain outside this service.
"""

import hashlib
import json
from pathlib import Path


def load_database_history_tasks(*, get_all_tasks):
    tasks = []
    batch_size = 1000
    offset = 0
    while True:
        batch = get_all_tasks(limit=batch_size, offset=offset)
        if not batch:
            break
        tasks.extend(batch)
        if len(batch) < batch_size:
            break
        offset += len(batch)
    return tasks


def load_legacy_history_tasks(*, directory, safe_basename):
    history_path = Path(directory) / 'history.jsonl'
    if not history_path.exists():
        return []

    old_tasks = []
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                except Exception:
                    continue
                timestamp = task.get('timestamp', task.get('created_at', 0)) or 0
                output_file = task.get('output_file') or task.get('result_file')
                legacy_key = f"{timestamp}:{safe_basename(output_file)}:{len(old_tasks)}"
                legacy_hash = hashlib.sha1(legacy_key.encode('utf-8')).hexdigest()[:8]
                old_tasks.append({
                    'task_id': f"old_{timestamp}_{legacy_hash}",
                    'status': 'success' if task.get('status') == 'success' else task.get('status', 'failed'),
                    'prompt': task.get('prompt', ''),
                    'params': task.get('params', {}),
                    'output_file': output_file,
                    'result_file': output_file,
                    'error': task.get('error'),
                    'created_at': timestamp,
                    'timestamp': timestamp,
                    'updated_at': int(timestamp or 0) + int(task.get('duration', 0) or 0),
                    'duration': task.get('duration', 0),
                    'type': task.get('type', 'google-gen'),
                    'is_old': True,
                })
    except Exception as e:
        print(f"⚠️ 读取旧 history.jsonl 失败：{e}")
    return old_tasks


def collect_renderable_history_tasks(
    *,
    load_database_tasks,
    load_legacy_tasks,
    task_timestamp,
    task_result_files,
    should_render,
    dedupe_key,
):
    combined = load_database_tasks() + load_legacy_tasks()
    combined.sort(key=task_timestamp, reverse=True)

    renderable = []
    seen = set()
    for task in combined:
        result_files, _primary_output = task_result_files(task)
        if not should_render(task.get('status'), result_files):
            continue
        key = dedupe_key(task)
        if key in seen:
            continue
        seen.add(key)
        renderable.append(task)
    return renderable
