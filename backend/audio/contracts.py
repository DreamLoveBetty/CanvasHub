"""HTTP-to-YuE request boundary, pinned to upstream 9253ed1. Standard library only."""
import math
import re
import secrets

REVISION = '9253ed133343406947bde7b67d43c7a63fb39d99'
MAX_UPLOAD = 100 * 1024 * 1024
SAMPLING = {
    'abc_sampling': dict(temperature=.7, top_p=.9, top_k=30, repetition_penalty=1.005,
                         penalty_window=100, min_tokens=32, max_tokens=4096),
    'semantic_sampling': dict(temperature=1., top_p=.95, top_k=100, repetition_penalty=1.2,
                              penalty_window=50, min_tokens=200, max_tokens=9000),
}


def number(value, name, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f'{name} 必须为有限数字')
    if not low <= value <= high or (integer and type(value) is not int):
        raise ValueError(f'{name} 范围为 {low}–{high}' + ('（整数）' if integer else ''))
    return value


def text(value, name, limit=65536, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{name} 需要' + ('非空' if required else '') + f'文本（最多 {limit} 字符）')
    return value


def mapping(value, keys, name):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f'{name} 存在未知字段或不是对象')
    return value


def sampling(value, kind):
    defaults = SAMPLING[kind]
    out = {**defaults, **mapping(value, defaults, kind)}
    limits = dict(temperature=(0, 5), top_p=(1e-9, 1), top_k=(1, 184704),
                  repetition_penalty=(1e-9, 100), penalty_window=(1, 100),
                  min_tokens=(0, 24576), max_tokens=(1, 24576))
    for key, val in out.items():
        number(val, key, *limits[key], integer=type(defaults[key]) is int)
    if out['min_tokens'] > out['max_tokens']:
        raise ValueError('min_tokens 不能大于 max_tokens')
    return out


def normalize_job(body):
    mapping(body, ('operation', 'request', 'precision', 'audio_format', 'asset_id', 'task', 'preset', 'max_seconds'), '音频任务')
    operation = body.get('operation', 'generate')
    if operation not in ('generate', 'plan', 'transcribe'):
        raise ValueError('operation 仅支持 generate / plan / transcribe')
    audio_format = body.get('audio_format', 'flac')
    if audio_format not in ('flac', 'wav'):
        raise ValueError('音频格式仅支持 flac / wav')
    if operation == 'transcribe':
        asset_id = body.get('asset_id', '')
        if not isinstance(asset_id, str) or not re.fullmatch(r'[a-f0-9]{64}\.(wav|flac|mp3|m4a|ogg|aac|webm|opus)', asset_id):
            raise ValueError('请先上传有效音频素材')
        task, preset = body.get('task', 'full'), body.get('preset', 'default')
        if task not in ('full', 'melody-full', 'melody-vocal') or preset not in ('default', 'paper'):
            raise ValueError('无效转谱任务或预设')
        return dict(operation=operation, asset_id=asset_id, task=task, preset=preset,
                    max_seconds=number(body.get('max_seconds', 300), '最大时长', 1, 1800))
    precision = body.get('precision', '8bit')
    if precision not in ('8bit', 'bf16'):
        raise ValueError('精度仅支持 8bit / bf16')
    request = dict(mapping(body.get('request', {}),
        ('style', 'tags', 'lyrics', 'cot', 'abc', 'seed', 'cfg_scale', 'id',
         'generation_config', 'abc_sampling', 'semantic_sampling'), 'SongRequest'))
    if 'style' in request and 'tags' in request:
        raise ValueError('style 与 tags 只需填写一个')
    out = dict(style=text(request.get('style', request.get('tags', '')), '风格', 8192, True),
               lyrics=text(request.get('lyrics', ''), '歌词', 32768, True), cot=request.get('cot', 'full'))
    if out['cot'] not in ('full', 'melody', 'off'):
        raise ValueError('cot 仅支持 full / melody / off')
    if operation == 'plan' and out['cot'] == 'off':
        raise ValueError('只生成乐谱不能使用 off 模式')
    # -1 is a CanvasHub convenience, never forwarded as an invalid upstream seed.
    seed = number(request.get('seed', 831001), 'seed', -1, 2**53 - 1, integer=True)
    out['seed'] = secrets.randbits(32) if seed == -1 else seed
    out['id'] = request.get('id', 'song')
    if not isinstance(out['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,179}', out['id']):
        raise ValueError('id 仅支持字母、数字、下划线、点和连字符，且必须以字母或数字开始')
    if request.get('cfg_scale') is not None:
        out['cfg_scale'] = number(request['cfg_scale'], 'cfg_scale', 0, 20)
    if request.get('abc') is not None:
        out['abc'] = text(request['abc'], 'ABC', 131072, True)
        if out['cot'] == 'off':
            raise ValueError('off 模式不能接入 ABC 乐谱')
    config = mapping(request.get('generation_config', {}), ('ode_steps', 'abc', 'semantic'), 'generation_config')
    out['generation_config'] = {'ode_steps': number(config.get('ode_steps', 32), 'ode_steps', 1, 128, integer=True)}
    for kind in SAMPLING:
        alias = kind.removesuffix('_sampling')
        if alias in config:
            out['generation_config'][alias] = sampling(config[alias], kind)
        if kind in request:
            out[kind] = sampling(request[kind], kind)
    spec = dict(operation=operation, precision=precision, request=out)
    if operation == 'generate':
        spec['audio_format'] = audio_format
    return spec
