"""Authenticated HTTP adapter. Uses the existing task store/progress/cancel routes."""
import uuid
from .service import normalize_model
from .parameters import normalize, DEFAULTS, RANGES, CHOICES


def models(handler, runtime):
    handler.send_json(dict(models=runtime.catalog(), defaults=DEFAULTS, ranges=RANGES, choices=CHOICES))


def submit(handler, *, runtime, create_task, process_task, attach_lineage):
    try:
        data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        if not isinstance(data, dict): raise ValueError('请求必须为对象')
        images = data.get('images')
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
            raise ValueError('请连接一张图片到 Topaz 节点')
        if not images[0].startswith('data:image/'): raise ValueError('Topaz 需要上传图片数据')
        model = normalize_model(data.get('model'))
        options = normalize(data.get('options'))
        entry = next(item for item in runtime.catalog() if item['id'] == model)
        if not entry['available']:
            handler.send_json({'error': entry['error']}, 409); return
        prompt = str(data.get('prompt') or 'Topaz 图像增强')[:2000]
        params = dict(model=model, topaz=options, archive_enabled=True,
                      telegram_enabled=data.get('telegram_enabled') is True)
        attach_lineage(params, data)
        task_id = 'topaz_' + uuid.uuid4().hex
        create_task(task_id, prompt, params, status='queued', task_type='topaz')
        if handler.start_generation_task(task_id, process_task, (task_id, prompt, images[0], params)):
            handler.send_json(dict(task_id=task_id,status='queued',type='topaz',message='Topaz 任务已提交'),202)
    except ValueError as exc:
        handler.send_json({'error':str(exc)},400)
