"""Topaz's own validated request contract (UI percentages -> native units).

No raw engine JSON, local paths, or opaque native context may enter this boundary.
"""
import math

DEFAULTS = dict(resize_mode='scale', scale=2, dimension=2048, unit='px', ppi=300,
    auto=False, denoise=20, sharpen=20, fix_compression=0, strength=75,
    gamma_correction=False, grain=False, grain_strength=10, grain_intensity=50,
    grain_size=1, face_enhancement=False, face_strength=80, face_creativity=0,
    output_format='png', jpeg_quality=95, enhancement_strength=1.0, detail=50,
    creativity=3, realistic_detail=0, texture=3, seed=42, description='')
RANGES = dict(scale=(.2, 6), dimension=(.01, 32000), ppi=(1, 1200),
    denoise=(0, 100), sharpen=(0, 100), fix_compression=(0, 100), strength=(0, 100),
    grain_strength=(0, 100), grain_intensity=(0, 100), grain_size=(1, 5),
    face_strength=(0, 100), face_creativity=(0, 1), jpeg_quality=(1, 100), enhancement_strength=(.7, 1.3), detail=(0,100),
    creativity=(2,5), realistic_detail=(0,1), texture=(1,5), seed=(0,2147483647))
CHOICES = dict(resize_mode=('scale','width','height','longest'), unit=('px','in','cm'),
               output_format=('png','jpg','tiff'))


def normalize(options=None):
    if options is None: options = {}
    if not isinstance(options, dict): raise ValueError('Topaz 参数必须是对象')
    unknown = set(options) - set(DEFAULTS)
    if unknown: raise ValueError('未知 Topaz 参数：' + ', '.join(sorted(unknown)))
    value = {**DEFAULTS, **options}
    for key, (lo, hi) in RANGES.items():
        raw = value[key]
        if isinstance(raw, bool): raise ValueError(f'{key} 必须是数值')
        try: number = float(raw)
        except (TypeError, ValueError): raise ValueError(f'{key} 必须是数值') from None
        if not math.isfinite(number) or not lo <= number <= hi:
            raise ValueError(f'{key} 必须在 {lo:g}–{hi:g} 之间')
        value[key] = number
    for key, choices in CHOICES.items():
        if value[key] not in choices: raise ValueError(f'{key} 选项无效')
    for key in ('auto','gamma_correction','grain','face_enhancement'):
        if not isinstance(value[key], bool): raise ValueError(f'{key} 必须为布尔值')
    for key in ('face_creativity','jpeg_quality','creativity','realistic_detail','texture','seed'):
        if value[key] != int(value[key]): raise ValueError(f'{key} 必须为整数')
        value[key] = int(value[key])
    if value['enhancement_strength'] not in (.7,1.0,1.3):
        raise ValueError('增强档位只能是 0.7、1.0、1.3')
    if not isinstance(value['description'], str) or len(value['description']) > 2000:
        raise ValueError('图像描述需为最多 2000 字的文本')
    return value


def dimensions(width, height, options):
    if min(width, height) < 16 or width * height > 16_000_000:
        raise ValueError('Topaz 输入最短边需至少 16 px，最多 1600 万像素')
    o = normalize(options)
    ratio = o['scale']
    if o['resize_mode'] != 'scale':
        pixels = o['dimension'] * (1 if o['unit']=='px' else o['ppi'] / (2.54 if o['unit']=='cm' else 1))
        ratio = pixels / {'width':width, 'height':height, 'longest':max(width,height)}[o['resize_mode']]
    out = (max(1, math.floor(width*ratio+.5)), max(1, math.floor(height*ratio+.5)))
    if max(out) > 32000 or out[0]*out[1] > 100_000_000:
        raise ValueError('本地 Topaz 输出上限：最长边 32000 px、总计 1 亿像素；请减小尺寸')
    return out


def native_options(options, *, standard):
    o = normalize(options)
    spec = dict(subject_detection='All', gamma_correction=str(o['gamma_correction']).lower(),
        grain=str(o['grain']).lower(), face_enhancement=o['face_enhancement'])
    if standard:
        # Omission invokes the installed model's automatic estimation, not a UI guess.
        if not o['auto']:
            spec.update({k: str(o[k]/100) for k in ('denoise','sharpen','fix_compression')})
    else:
        spec['strength'] = str(o['strength']/100)
    if o['grain']:
        spec.update(grain_strength=str(o['grain_strength']/100),
                    grain_intensity=str(o['grain_intensity']/100), grain_size=str(o['grain_size']))
    if o['face_enhancement']:
        spec.update(face_enhancement_strength=o['face_strength']/100,
                    face_enhancement_creativity=o['face_creativity'])
    return spec


def model_request(meta, width, height, out_width, out_height, o):
    """Build only known per-model fields. Never accept arbitrary native stack JSON."""
    profile, protocol = meta['profile'], meta['protocol']
    if protocol == 'neuro':
        params = dict(model=meta['native'], upscale_factor=out_width/width)
        if profile == 'wonder': params['enhancement_strength'] = o['enhancement_strength']
        return params
    if protocol == 'native':
        settings = native_options(o, standard=profile == 'classic')
        if profile in ('recover1','recover2'):
            settings.pop('strength', None)
            settings['detail'] = str(o['detail']/100)
        return dict(category='Enhance', model=meta['native'], output_width=out_width,
                    output_height=out_height, **settings)
    params = dict(model=meta['native'], scale=out_width/width,
                  param1=o['denoise']/100, param2=o['sharpen']/100,
                  param3=o['fix_compression']/100, strength=o['strength']/100,
                  gamma_correction=o['gamma_correction'])
    category = 'Enhance'
    if profile == 'natural':
        category = 'Natural Upscale'
        params.update(creativity_strength=o['enhancement_strength'], seed=o['seed'])
    elif profile == 'recover3':
        category = 'Wonder'
        params['strength'] = o['enhancement_strength']
    elif profile.startswith('redefine_'):
        category = 'Redefine'
        params.update(creativity=o['creativity'] if profile == 'redefine_creative' else o['realistic_detail'],
                      texture=o['texture'], seed=o['seed'],
                      prompt=o['description'] if profile == 'redefine_creative' else '')
    return [dict(category=category, enabled=True, name=meta['native'], params=params)] + grain_stack(o)


def grain_stack(o):
    if not o['grain']: return []
    return [dict(category='Grain', name='Grain', enabled=True, params=dict(model='Gaussian',
        scale=1.0, strength=o['grain_strength']/100, sigma=o['grain_intensity']/100,
        noiseSize=o['grain_size']))]
