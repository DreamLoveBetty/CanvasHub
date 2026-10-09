"""Topaz service adapter to the model-independent image task lifecycle."""
from .catalog import MODELS
from .parameters import normalize
from ..services.image_enhancement import EnhancementEngine


def normalize_model(value):
    value = 'topaz-standard-v2' if value is None or value == '' else value
    if not isinstance(value, str) or value not in MODELS: raise ValueError('不支持的 Topaz 模型')
    return value


def engine(runtime, params):
    options = normalize(params.get('topaz'))
    def execute(source, output, *, model_name, cancelled, progress, **unused):
        return runtime.execute(source, output, model=model_name, options=options,
                               cancelled=cancelled, progress=progress)
    return EnhancementEngine('topaz', 'topaz', MODELS, normalize_model, execute, options['output_format'], parameter_key='topaz', display_name='Topaz 图像增强')
