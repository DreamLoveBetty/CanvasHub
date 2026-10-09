"""Original Spandrel backend only; Topaz is a separate domain and API."""
from .. import upscale_runtime as spandrel
MODELS = spandrel.UPSCALE_MODELS

def normalize_model(value):
    if str(value or '').startswith('topaz-'):
        raise ValueError('Topaz 已迁移为独立节点，请使用 Topaz Gigapixel 节点')
    return spandrel.normalize_upscale_model(value)

def available_models(model_dir):
    return spandrel.available_upscale_models(model_dir)

def execute(source, output, *, cancelled=lambda: False, **options):
    if cancelled(): raise spandrel.UpscaleRuntimeError('任务已取消')
    if 'model_name' in options: options['model_name'] = normalize_model(options['model_name'])
    return spandrel.upscale_image_file(source, output, **options)
