"""Pose scene contracts: pinned SOMA assets, mannequin levels of detail and bounded exports.

Clients never send filesystem paths, URLs to fetch or model choices beyond these names.
"""
import base64
import binascii
import json
import re
import struct

# nvidia/soma-x release v0.3.4 (Apache-2.0). Only the files the 78-joint LBS mannequins need:
# the SOMA neutral body plus the Anny (Apache-2.0, NAVER) wrap used for the female/male presets.
SOMA_REPO = 'nvidia/soma-x'
SOMA_RELEASE = 'v0.3.4'
SOMA_REVISION = 'f81a01796f652260ff930d5318d6c6b845a505ed'
SOMA_FILES = {
    'SOMA_neutral.npz': '5829af4a5333abdba5ad449360b868faacee99d395971e62f35c0e7169432b63',
    'SOMA_template_rig.usda': 'a952cb7bdf4ccd801e355d53122d395b985b69d0d9181439edad5081bb171856',
    'SOMA_procedural_transforms.json': '9853e19ab51625ffaa7d9e7ccf0e443272c2740837604e6bacd66604e8edf509',
    'LICENSE': 'd1a7d615ab8eff4de143b1456f46dabf232f54daf0fcf9a70442bb6f637a9e95',
    'Anny/base_body.obj': '7bf31cbc0897670de51b7cd6b1a3da55a35fe56ef1d7b2e6aae2f95a11196504',
    'Anny/SOMA_wrap.obj': '15e1500a13d3fac2db17b622ab54292cfb2e58d9efaa1e86cc11e46071bffb2e',
}
# Bump when the converter output changes so stale mannequins are reported and regenerated.
GLB_VERSION = 2
LODS = ('low', 'mid')
# Body presets. `neutral` is the SOMA neutral body; the others are adult Anny phenotypes
# (gender 0 = male, 1 = female; age 0.75 is Anny's "young adult" anchor; everything else average).
BODIES = ('neutral', 'female', 'male')
BODY_LABELS = {'neutral': '中性', 'female': '女性', 'male': '男性'}
ANNY_PRESETS = {'female': {'gender': 1.0, 'age': 0.75}, 'male': {'gender': 0.0, 'age': 0.75}}
PASSES = ('mannequin', 'openpose', 'depth', 'normal', 'mask')
MAX_EXPORT_BYTES = 24 * 1024 * 1024
MAX_EXPORT_REQUEST = 34 * 1024 * 1024
MAX_EXPORT_SIDE = 4096
MAX_SCENE_BYTES = 256 * 1024
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('无效姿态导出标识')
    return value


def lod(value):
    value = value or 'low'
    if value not in LODS:
        raise ValueError('未知人偶精细度')
    return value


def body(value):
    value = value or 'neutral'
    if value not in BODIES:
        raise ValueError('未知人偶体型')
    return value


def glb_name(level, kind='neutral'):
    return f'soma_{body(kind)}_{lod(level)}.glb'


def png_size(data):
    """Return (width, height) of a PNG; reject anything else."""
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b'IHDR':
        raise ValueError('导出图片必须为 PNG')
    width, height = struct.unpack('>II', data[16:24])
    if not (1 <= width <= MAX_EXPORT_SIDE and 1 <= height <= MAX_EXPORT_SIDE):
        raise ValueError('导出图片尺寸超出范围')
    return width, height


def normalize_export(body):
    """Validate an image export request: a PNG data URL, its pass and an optional scene snapshot."""
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    if set(body) - {'image', 'pass', 'camera', 'scene'}:
        raise ValueError('包含不支持的导出参数')
    image = body.get('image')
    prefix = 'data:image/png;base64,'
    if not isinstance(image, str) or not image.startswith(prefix):
        raise ValueError('导出图片必须为 PNG data URL')
    try:
        data = base64.b64decode(image[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('导出图片编码无效') from None
    if not 0 < len(data) <= MAX_EXPORT_BYTES:
        raise ValueError('导出图片超过大小限制')
    width, height = png_size(data)
    render_pass = body.get('pass')
    if render_pass not in PASSES:
        raise ValueError('未知输出通道')
    camera = body.get('camera', '')
    if not isinstance(camera, str) or len(camera) > 40:
        raise ValueError('机位名称无效')
    scene = body.get('scene')
    if scene is not None:
        if not isinstance(scene, dict):
            raise ValueError('场景快照必须为对象')
        if len(json.dumps(scene, ensure_ascii=False).encode()) > MAX_SCENE_BYTES:
            raise ValueError('场景快照超过大小限制')
    return {'data': data, 'width': width, 'height': height, 'pass': render_pass, 'camera': camera, 'scene': scene}
