"""Existing task-status and generation-log read endpoints with explicit dependencies."""

import urllib.parse


def handle_status(handler, task_id, *, get_task, missing_task_payload, status_response_task):
    """处理状态查询"""
    task = get_task(task_id)
    if not task:
        # Old cached Telegram WebViews may keep polling stale task ids.
        # Return a terminal failed state instead of 404 so the client can recover.
        handler.send_json(missing_task_payload(task_id))
        return

    handler.send_json(status_response_task(task))


def handle_generation_runs(handler, parsed, task_id, *, page_int, get_runs):
    """返回任务的 generation runs。"""
    try:
        query = urllib.parse.parse_qs(parsed.query or '')
        limit = page_int((query.get('limit') or ['20'])[0], 20, minimum=1, maximum=200)
        offset = page_int((query.get('offset') or ['0'])[0], 0, minimum=0, maximum=100000)
        runs = get_runs(task_id, limit=limit, offset=offset)
        handler.send_json({
            'task_id': task_id,
            'runs': runs,
            'count': len(runs),
        })
    except Exception as e:
        handler.send_json({'error': str(e)}, 500)


def handle_generation_events(handler, parsed, run_id, *, page_int, get_run, get_events):
    """返回指定 generation run 的事件流。"""
    try:
        query = urllib.parse.parse_qs(parsed.query or '')
        limit = page_int((query.get('limit') or ['200'])[0], 200, minimum=1, maximum=1000)
        offset = page_int((query.get('offset') or ['0'])[0], 0, minimum=0, maximum=100000)
        run = get_run(run_id)
        events = get_events(run_id, limit=limit, offset=offset)
        handler.send_json({
            'run_id': run_id,
            'task_id': run.get('task_id') if isinstance(run, dict) else '',
            'run': run,
            'events': events,
            'count': len(events),
        })
    except Exception as e:
        handler.send_json({'error': str(e)}, 500)
