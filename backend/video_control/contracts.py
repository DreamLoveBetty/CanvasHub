"""Public request contract. No filesystem paths or model downloads from clients."""
import math
import re

ENGINE = 'reshot-0.5.0-small-v2-pose-coverage'
MAX_UPLOAD = 200 * 1024 * 1024
ACTIVE = {'queued', 'running', 'cancelling'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('无效视频控制标识')
    return value


def normalize(body):
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    allowed = {'asset_id', 'control', 'quality', 'max_res', 'max_seconds', 'canny_low', 'canny_high', 'pose_hands', 'pose_face', 'invert'}
    if set(body) - allowed:
        raise ValueError('包含不支持的视频控制参数')
    spec = {'asset_id': identifier(body.get('asset_id')), 'control': body.get('control', 'depth'),
            'quality': body.get('quality', 'fast')}
    if spec['control'] not in {'depth', 'pose', 'canny'} or spec['quality'] not in {'fast', 'full'}:
        raise ValueError('未知处理模式或质量')
    for name, default, lo, hi in [('max_res', 640, 256, 1280), ('max_seconds', 15, 1, 30),
                                   ('canny_low', 100, 0, 1000), ('canny_high', 200, 0, 1000)]:
        value = body.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or int(value) != value or not lo <= value <= hi:
            raise ValueError(f'{name} 超出范围')
        spec[name] = int(value)
    if spec['control'] != 'canny':
        spec['canny_low'], spec['canny_high'] = 100, 200
    if spec['canny_low'] > spec['canny_high']:
        raise ValueError('边缘低阈值不能高于高阈值')
    for name, default in [('pose_hands', True), ('pose_face', False), ('invert', False)]:
        value = body.get(name, default)
        if not isinstance(value, bool): raise ValueError(f'{name} 必须为布尔值')
        spec[name] = value
    return spec
