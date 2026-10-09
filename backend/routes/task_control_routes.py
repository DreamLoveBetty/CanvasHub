"""Task cancel/retry/batch-control HTTP endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_task_cancel(handler, task_id, *, _missing_task_payload, get_task, time, update_task_fields):
    """取消正在运行的任务。

        生成线程会通过任务状态感知取消；正在进行中的单次上游调用不会被强杀，
        但后续图片、托底和 Telegram 发送会停止。
        """
    task = get_task(task_id)
    if not task:
        handler.send_json(_missing_task_payload(task_id), 404)
        return

    status = str(task.get('status') or '')
    if status in ('succeeded', 'success', 'succeeded_no_telegram', 'failed', 'telegram_failed', 'canceled'):
        handler.send_json({
            **task,
            'ok': True,
            'message': '任务已结束，无需取消。'
        })
        return

    result_files = task.get('result_files') or []
    progress_text = f'任务已取消，已保留 {len(result_files)} 张图' if result_files else '任务已取消'
    now = int(time.time())
    update_task_fields(
        task_id,
        status='canceled',
        stage='canceled',
        progress_text=progress_text,
        error='',
        transport_error_type='UserCanceled',
        heartbeat_at=now,
        finished_at=now,
    )
    canceled_task = get_task(task_id) or task
    if canceled_task.get('result_files'):
        canceled_task['output_files'] = canceled_task['result_files']
        canceled_task['image_paths'] = [f"/gpt_outputs/{name}" for name in canceled_task['result_files']] if canceled_task.get('type') in ('gpt', 'gpt-edit') else [f"/image/{name}" for name in canceled_task['result_files']]
        canceled_task['image_count'] = len(canceled_task['result_files'])
    canceled_task['ok'] = True
    canceled_task['message'] = progress_text
    handler.send_json(canceled_task)


def handle_task_retry(
    handler,
    task_id,
    *,
    GenerationQueueFullError,
    TaskRetryError,
    _generation_busy_payload,
    _missing_task_payload,
    get_task,
    retry_failed_task,
):
    """从失败历史记录创建一个新的重跑任务，不修改原任务。"""
    task = get_task(task_id)
    if not task:
        handler.send_json(_missing_task_payload(task_id), 404)
        return
    try:
        retry_task = retry_failed_task(task)
        handler.send_json(retry_task, 202)
    except GenerationQueueFullError as e:
        payload = _generation_busy_payload()
        payload.update({"message": str(e), "task_id": task_id})
        handler.send_json(payload, 503)
    except TaskRetryError as e:
        handler.send_json({"ok": False, "error": str(e), "task_id": task_id}, 400)
    except Exception as e:
        print(f"❌ 重跑任务失败：{task_id} - {e}")
        handler.send_json({"ok": False, "error": str(e), "task_id": task_id}, 500)


def handle_task_batch(handler, *, TaskRetryError, _batch_prompt_items, _create_batch_tasks, process_batch_tasks):
    """创建顺序执行的批量生成任务。"""
    try:
        data = handler.read_json_body()
        provider = str(data.get('provider') or 'gpt').strip().lower()
        if provider not in ('gpt', 'google'):
            handler.send_json({"ok": False, "error": "批量第一版只支持 GPT 和 Google 纯生成任务。"}, 400)
            return
        if data.get('images') or data.get('base64_images') or data.get('reference_images'):
            handler.send_json({"ok": False, "error": "批量第一版暂不支持带参考图的编辑任务。"}, 400)
            return
        prompts = _batch_prompt_items(data)
        if len(prompts) < 2:
            handler.send_json({"ok": False, "error": "批量任务至少需要 2 条提示词。"}, 400)
            return
        if len(prompts) > 50:
            handler.send_json({"ok": False, "error": "批量任务一次最多 50 条提示词。"}, 400)
            return
        params = data.get('params') if isinstance(data.get('params'), dict) else {}
        lineage = data.get('lineage') if isinstance(data.get('lineage'), dict) else None
        batch_id, tasks = _create_batch_tasks(provider, prompts, params, lineage=lineage)
        if not handler.start_generation_task(
            batch_id,
            process_batch_tasks,
            (batch_id, tasks),
            task_ids=[task['task_id'] for task in tasks],
        ):
            return
        handler.send_json({
            "ok": True,
            "batch_id": batch_id,
            "status": "queued",
            "counts": {
                "total": len(tasks),
                "queued": len(tasks),
                "processing": 0,
                "succeeded": 0,
                "failed": 0,
                "canceled": 0,
            },
            "tasks": tasks,
            "message": f"已提交 {len(tasks)} 个批量任务，将按线路容量调度执行。",
        }, 202)
    except TaskRetryError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 创建批量任务失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_batch_status(handler, batch_id, *, get_batch_summary):
    """聚合同一个 batch_id 下的子任务状态。"""
    summary = get_batch_summary(batch_id)
    handler.send_json(summary, 200 if summary.get('ok') else 404)


def handle_batch_control(handler, batch_id, action, *, cancel_batch_queued_tasks, get_batch_summary, set_batch_control):
    """暂停、恢复或取消批量任务。"""
    if action not in ('pause', 'resume', 'cancel'):
        handler.send_json({"ok": False, "error": "不支持的批量操作"}, 404)
        return
    if not batch_id:
        handler.send_json({"ok": False, "error": "缺少 batch_id"}, 400)
        return
    try:
        control = 'running' if action == 'resume' else ('canceled' if action == 'cancel' else 'paused')
        changed = set_batch_control(batch_id, control)
        if not changed:
            handler.send_json({"ok": False, "error": "批量任务不存在", "batch_id": batch_id}, 404)
            return
        canceled = cancel_batch_queued_tasks(batch_id) if action == 'cancel' else 0
        summary = get_batch_summary(batch_id)
        summary.update({
            "ok": True,
            "action": action,
            "changed": changed,
            "canceled": canceled,
            "message": {
                "pause": "批量任务已暂停，将在当前子任务结束后停止启动新任务。",
                "resume": "批量任务已恢复。",
                "cancel": "批量任务已取消。",
            }[action],
        })
        handler.send_json(summary)
    except Exception as e:
        print(f"❌ 批量控制失败：{batch_id} {action} - {e}")
        handler.send_json({"ok": False, "error": str(e), "batch_id": batch_id}, 500)


def start_generation_task(
    handler,
    task_id,
    target,
    args=(),
    task_ids=None,
    *,
    _generation_busy_message,
    _generation_busy_payload,
    _start_generation_thread,
    update_task,
):
    thread = _start_generation_thread(target, args=args)
    if thread:
        return True
    message = _generation_busy_message()
    for rejected_id in (task_ids or [task_id]):
        update_task(
            rejected_id,
            'failed',
            error=message,
            stage='rejected',
            progress_text=message,
            transport_error_type='GenerationQueueFull',
        )
    payload = _generation_busy_payload()
    payload['task_id'] = task_id
    handler.send_json(payload, 503)
    return False
