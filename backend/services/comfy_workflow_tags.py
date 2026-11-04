"""ComfyUI workflow title tags: the workflow author declares which nodes the canvas fills.

API-format exports drop ComfyUI groups but keep each node's title (`_meta.title`), so roles
are declared by a bracket tag in the title, e.g. `[提示词] 正向`, `[尺寸] Latent`, `[参考图2]`.
Simplified, traditional and English names and full-width brackets 【】 are accepted.

Once any node carries a tag the workflow is in strict mode: only tagged nodes are written and
only `[参数]` nodes (plus `[负面]` text) are offered as parameters. Image and video tags become
ordered input slots; an empty slot keeps the workflow's own value. Untagged workflows keep the
automatic detection in comfy_workflows / comfy_gateway unchanged.
"""
from __future__ import annotations

import re

from .comfy_video import is_uploaded_video_input

_ROLE_ALIASES = {
    'prompt': ('提示词', '提示詞', 'prompt'),
    'negative': ('负面', '負面', 'negative'),
    'size': ('尺寸', 'size'),
    'image': ('参考图', '參考圖', 'image'),
    'video': ('视频', '視頻', 'video'),
    'param': ('参数', '參數', 'param'),
}
_ROLE_BY_NAME = {alias.lower(): role for role, aliases in _ROLE_ALIASES.items() for alias in aliases}
_TAG_RE = re.compile(r'[\[【]\s*(' + '|'.join(re.escape(name) for name in _ROLE_BY_NAME) + r')\s*(\d{0,2})\s*[\]】]',
                     re.IGNORECASE)
_TEXT_FIELDS = ('text', 'prompt', 'positive', 'string', 'value', 'text_g')
PROMPT_TOKEN = '{{PROMPT}}'


def _title(node):
    return str((node.get('_meta') or {}).get('title') or '') if isinstance(node.get('_meta'), dict) else ''


def title_tags(title):
    """[(role, index or None)] for every tag in a node title."""
    return [(_ROLE_BY_NAME[match.group(1).lower()], int(match.group(2)) if match.group(2) else None)
            for match in _TAG_RE.finditer(str(title or ''))]


def strip_title_tags(title):
    return re.sub(r'\s+', ' ', _TAG_RE.sub(' ', str(title or ''))).strip()


def _scalar(value):
    return value is not None and not isinstance(value, (dict, list))


def collect_workflow_tags(workflow):
    """Tagged targets of an API-format workflow; `tagged` is False when no title has a tag."""
    result = {'tagged': False, 'prompt': [], 'negative': [], 'size': [], 'images': [], 'videos': [],
              'image_titles': [], 'video_titles': [], 'params': [], 'warnings': []}
    if not isinstance(workflow, dict):
        return result
    images, untagged_loaders = [], []
    for position, (raw_id, node) in enumerate(workflow.items()):
        if not isinstance(node, dict):
            continue
        node_id = str(raw_id)
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else {}
        class_type = str(node.get('class_type') or '')
        class_key = class_type.lower().replace('_', '')
        tags = title_tags(_title(node))
        roles = {role for role, _index in tags}
        name = f'#{node_id} {strip_title_tags(_title(node)) or class_type}'
        if tags:
            result['tagged'] = True
        for role in ('prompt', 'negative'):
            if role not in roles:
                continue
            field = next((key for key in _TEXT_FIELDS if isinstance(inputs.get(key), str)), None)
            if field:
                result[role].append({'node_id': node_id, 'field': field, 'value': inputs[field]})
            else:
                result['warnings'].append(f'{name} 标记了 [{"提示词" if role == "prompt" else "负面"}]，但没有可写入的文本字段')
        if 'size' in roles:
            if _scalar(inputs.get('width')) and _scalar(inputs.get('height')):
                result['size'].append(node_id)
            else:
                result['warnings'].append(f'{name} 标记了 [尺寸]，但宽高不是可写入的数值（可能是连线）')
        is_image_loader = 'loadimage' in class_key and 'image' in inputs
        video_field = next((key for key in ('file', 'video') if is_uploaded_video_input(class_type, key) and key in inputs), None)
        if 'image' in roles:
            if is_image_loader and _scalar(inputs.get('image')):
                index = next((index for role, index in tags if role == 'image' and index), None)
                images.append((index or 1000 + position, node_id, name))
            else:
                result['warnings'].append(f'{name} 标记了 [参考图]，但不是 LoadImage 节点')
        elif is_image_loader:
            untagged_loaders.append(f'{name} 未标记 [参考图]，不会接收画布图片')
        if 'video' in roles:
            if video_field and _scalar(inputs.get(video_field)):
                result['videos'].append(node_id)
                result['video_titles'].append(strip_title_tags(_title(node)))
            else:
                result['warnings'].append(f'{name} 标记了 [视频]，但不是 LoadVideo / VHS_LoadVideo 节点')
        elif video_field:
            untagged_loaders.append(f'{name} 未标记 [视频]，不会接收画布视频')
        if 'param' in roles:
            result['params'].append(node_id)
    images.sort(key=lambda item: item[0])
    result['images'] = [node_id for _key, node_id, _name in images]
    result['image_titles'] = [strip_title_tags(_title(workflow[node_id])) for node_id in result['images']]
    if result['tagged']:
        result['warnings'].extend(untagged_loaders)
    return result


def workflow_tag_summary(workflow, raw_text=''):
    """Catalog fields derived from tags; auto-detected workflows only report tag_mode='auto'."""
    tags = collect_workflow_tags(workflow)
    if not tags['tagged']:
        return {'tag_mode': 'auto', 'default_prompt': '', 'size_editable': True, 'tag_warnings': [],
                'accepts_negative': False, 'input_slots': []}, tags
    text = str(raw_text or '')
    prompt = next((item['value'].replace(PROMPT_TOKEN, '').strip() for item in tags['prompt']), '')
    return {
        'tag_mode': 'tags',
        'default_prompt': prompt[:4000],
        'size_editable': bool(tags['size']) or '{{WIDTH}}' in text or '{{HEIGHT}}' in text,
        'tag_warnings': tags['warnings'][:20],
        'accepts_text': bool(tags['prompt']) or PROMPT_TOKEN in text,
        'accepts_image': bool(tags['images']) or '{{IMAGE' in text,
        'image_slots': len(tags['images']),
        'accepts_video': bool(tags['videos']) or '{{VIDEO' in text,
        'video_slots': len(tags['videos']),
        'accepts_negative': bool(tags['negative']),
        'input_slots': input_slots(tags),
    }, tags


def input_slots(tags):
    """Ordered image/video slots the canvas maps connected nodes onto."""
    slots = []
    for kind, prefix, titles in (('image', '参考图', tags['image_titles']), ('video', '视频', tags['video_titles'])):
        for index, title in enumerate(titles, start=1):
            label = f'{prefix}{index}' if kind == 'image' or len(titles) > 1 else prefix
            slots.append({'key': f'{kind}:{index}', 'kind': kind, 'label': f'{label} · {title}' if title else label})
    return slots


def tagged_default_size(workflow, tags):
    """(width, height) of the first tagged size node with numeric values, else None."""
    for node_id in tags['size']:
        inputs = workflow[node_id].get('inputs') or {}
        try:
            return float(inputs['width']), float(inputs['height'])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _slot_value(names, slot):
    return str(names[slot] or '').strip() if slot < len(names or []) else ''


def apply_tagged_inputs(workflow, tags, *, prompt, negative_prompt='', width, height, image_names, video_names):
    """Strict-mode writes: only tagged nodes change. Token-composed prompt fields are left as replaced;
    image/video names are positional per slot and an empty slot keeps the workflow's own value."""
    for item in tags['prompt']:
        if prompt and PROMPT_TOKEN not in item['value']:
            workflow[item['node_id']]['inputs'][item['field']] = prompt
    for item in tags['negative']:
        if negative_prompt:
            workflow[item['node_id']]['inputs'][item['field']] = negative_prompt
    for node_id in tags['size']:
        workflow[node_id]['inputs']['width'] = width
        workflow[node_id]['inputs']['height'] = height
    for slot, node_id in enumerate(tags['images']):
        if name := _slot_value(image_names, slot):
            workflow[node_id]['inputs']['image'] = name
    for slot, node_id in enumerate(tags['videos']):
        if name := _slot_value(video_names, slot):
            node = workflow[node_id]
            field = next(key for key in ('file', 'video') if is_uploaded_video_input(node.get('class_type'), key) and key in node['inputs'])
            node['inputs'][field] = name
    return workflow
