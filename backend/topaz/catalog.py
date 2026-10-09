"""Version-pinned capabilities of the separately installed macOS application."""
from functools import lru_cache
import hashlib
from pathlib import Path
import platform
import shutil
import sys

APP = Path('/Applications/Topaz Gigapixel.app/Contents')
LIBRARIES = {
    'libimageai.dylib': 'cfd420a2757756770ca5d2cdd2b87e949bc12a7713a248d8851e975889ee0da4',
    'libaiengine.dylib': 'a1d3b35bfcc260d28530f300a9095aea15c8d25b725352ac3d30385140796d30',
}
def _model(label, native, profile, evidence, weights, *, protocol='native', verified=True):
    return dict(label=label, native=native, profile=profile, evidence=evidence,
                weights=tuple(weights), protocol=protocol, verified=verified,
                family='topaz', scale=2,
                route='topaz_neuro' if protocol == 'neuro' else 'topaz_native')


# Names are protocol-specific: "Standard MAX" in iai_proc silently uses old ggn!
# Every enabled entry is checked against the actual primary model in worker logs.
COMMON = ('ggn_ap-v2-fp16-128x128-rev2-mlc.tz',)
def classic_weights(prefix, block):
    return COMMON + tuple(name for scale in (2,4) for name in
                          (f'{prefix}-*-{scale}x-mlc.tz', f'gclc-v1-fp16-{block}-{scale}x-mlc.tz'))

MODELS = {
    'topaz-standard-v2': _model('Standard V2', 'Standard V2', 'classic', ('ggnv2',), classic_weights('ggnv2', '128x128')),
    'topaz-standard-v1': _model('Standard V1', 'Standard', 'legacy', ('ggn_noee', 'ggn'), classic_weights('ggn', '128x128'), protocol='stack'),
    'topaz-high-fidelity-v3': _model('High Fidelity V3', 'High Fidelity V3', 'strength', ('ghqv3',),
        ('ghqv3_cache-v2-fp16-224x224-mlc.tz', 'ghqv3-v2-fp16-512x512-rev1-mlc.tz')),
    'topaz-high-fidelity-v2': _model('High Fidelity V2', 'High Fidelity V2', 'classic', ('ghqv2',), classic_weights('ghqv2', '128x128')),
    'topaz-high-fidelity-v1': _model('High Fidelity V1', 'High Fidelity', 'legacy', ('ghq_noee', 'ghq'), classic_weights('ghq', '96x96'), protocol='stack'),
    'topaz-low-res-v2': _model('Low res V2', 'Low Resolution V2', 'classic', ('gmpv2',), classic_weights('gmpv2', '192x192')),
    'topaz-low-res-v1': _model('Low res V1', 'Low Resolution', 'legacy', ('gmp',), classic_weights('gmp', '192x192'), protocol='stack'),
    'topaz-text-shapes': _model('Text & shapes', 'Text Refine', 'classic', ('trf',), classic_weights('trf', '128x128')),
    'topaz-art-cg': _model('Art & CG', 'CGI', 'classic', ('ggi',), classic_weights('ggi', '192x192')),
    'topaz-wonder-35': _model('Wonder 3.5', 'Wonder 3.5', 'wonder', ('Wonder 3.5',), ('neuroserver/wonder-all',), protocol='neuro'),
    'topaz-wonder-3': _model('Wonder 3', 'Wonder 3', 'wonder', ('Wonder 3',), ('neuroserver/wonder-all',), protocol='neuro'),
    'topaz-wonder-2': _model('Wonder 2', 'Wonder 2', 'wonder2', ('Wonder 2',), ('neuroserver/wonder-2',), protocol='neuro'),
    'topaz-wonder-1': _model('Wonder 1', 'Natural Upscale', 'natural', ('tpn', 'tpn_900'),
        ('tpn_enc-v1-fp16-512x512-mlc.tz', 'tpn_unet-v1-fp16-64x64-new-mlc.tz',
         'tpn_dec-v1-fp16-64x64-mlc.tz', 'tpn_embeds.bin', 'ldclc-v1-fp16-64x64-mlc.tz'), protocol='stack'),
    'topaz-standard-max': _model('Standard Max', 'Standard Max', 'strength', ('stdmax', 'stdmax_noee'),
        ('stdmax-v1-fp16-192x192-mlc.tz', 'stdmax-v1-mixed-128x128-mlc.tz'), protocol='stack'),
    'topaz-recover-v3': _model('Recover V3', 'Wonder', 'recover3', ('irwn_dit',),
        ('irwn_dit-*-mlc.tz', 'irwn_enc-*-mlc.tz', 'irwn_dec-*-mlc.tz'), protocol='stack'),
    'topaz-recover-v2': _model('Recover V2', 'Recovery V2', 'recover2', ('ssdunet',),
        ('ssdenc-*-mlc.tz', 'ssdunet-*-mlc.tz', 'ssddec0_0-*-mlc.tz', 'ssddec0_5-*-mlc.tz', 'ssddec1_0-*-mlc.tz')),
    'topaz-recover-v1': _model('Recover V1', 'Recovery', 'recover1', ('ldu21',),
        ('lde21-*-mlc.tz', 'ldu21-*-mlc.tz', 'ldd21-*-mlc.tz', 'lddv21-*-mlc.tz', 'ldclc-*-mlc.tz')),
    'topaz-redefine-realistic': _model('Redefine realistic', 'Redefine', 'redefine_realistic', ('rxl_unet0',),
        ('rxl_unet0-*-mlc.tz', 'lde21-*-mlc.tz', 'lddv21-*-mlc.tz', 'ldclc-*-mlc.tz', 'rxl_encoder0-*-mlc.tz', 'rxl_decoder0-*-mlc.tz',
         'rxl_embed-*-mlc.tz', 'rxl_vocab.txt', 'rxl_merges.txt', 'neg_emb.yaml',
         'ggn-*-2x-mlc.tz', 'ggn-*-4x-mlc.tz'), protocol='stack'),
    'topaz-redefine-creative': _model('Redefine creative', 'Redefine', 'redefine_creative', ('rxl_unet1',),
        ('rxl_unet1-*-mlc.tz', 'rxl_encoder0-*-mlc.tz', 'rxl_encoder1-*-mlc.tz', 'rxl_decoder0-*-mlc.tz',
         'rxl_decoder1-*-mlc.tz', 'rxl_embed-*-mlc.tz', 'default_prompt.bin', 'rxl_vocab.txt', 'rxl_merges.txt', 'neg_emb.yaml',
         'ggn_ap-v2-fp16-512x512-rev2-mlc.tz', 'apnb-v2-fp16-512x512-rev2-mlc.tz',
         'slsp_ap-v2-fp16-512x512-rev2-mlc.tz',
         'ggn-*-2x-mlc.tz', 'ggn-*-4x-mlc.tz'), protocol='stack'),
}



@lru_cache(maxsize=8)
def _digest(path, size, modified):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_installation(app=APP):
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        return 'Topaz 原生放大目前仅支持 Apple Silicon macOS'
    if getattr(sys, 'frozen', False):
        return 'Topaz 原生放大暂不支持冻结桌面包，请使用本机源码服务'
    if not shutil.which('nm'):
        return 'Topaz 原生适配需要已启用的 macOS 开发工具 nm'
    for name, expected in LIBRARIES.items():
        path = Path(app) / 'Frameworks' / name
        if not path.is_file():
            return '请先安装或导入 Topaz Gigapixel 1.3.6 运行资源'
        stat = path.stat()
        if _digest(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            return 'Topaz 原生库版本已变化，需要重新验证后启用，未自动调用未验证版本'
    return ''


def capabilities(app=APP):
    reason = check_installation(app)
    entries = []
    for key, meta in MODELS.items():
        root = Path(app) / 'Resources/models'
        missing = [name for name in meta['weights'] if not any(root.glob(name))]
        error = reason or ('本机模型尚未通过验证，暂未开放' if not meta['verified'] else '')
        if not error and meta['protocol'] == 'neuro':
            try:
                from .neuro import check_runtime
            except ImportError:
                from neuro import check_runtime
            error = check_runtime(app)
            store = root / meta['weights'][0]
            minimum = 43 if meta['profile'] == 'wonder2' else 47
            if sum(1 for file in store.glob('blob.*') if file.is_file() and file.stat().st_size) < minimum:
                missing.append('Wonder 模型数据')
        error = error or ('Topaz 模型资源不完整，请重新导入已验证运行资源' if missing else '')
        entries.append(dict(id=key, label=meta['label'], profile=meta['profile'], family='topaz', default_scale=2,
                            scales=[1,2,4,6], custom_scale=True, available=not error,
                            error=error, route=meta['route']))
    return entries


def request_for(model, width, height, options=None):
    try: from .parameters import dimensions, normalize, model_request
    except ImportError: from parameters import dimensions, normalize, model_request
    if model not in MODELS: raise ValueError('不支持的 Topaz 模型')
    o = normalize(options)
    w, h = dimensions(width, height, o)
    meta = MODELS[model]
    if meta['protocol'] == 'neuro' and (width*height > 4_000_000 or w*h > 16_000_000):
        raise ValueError('Wonder 本地适配上限：输入 400 万像素、输出 1600 万像素')
    return model_request(meta, width, height, w, h, o)
