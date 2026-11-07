"""Switchable ComfyUI workflows: branches, toggles and option groups declared in node titles.

An API export records only the switch state at export time, so the author exports with every
switch on and tags the alternatives in node titles:

  [分支:名称]  one first-stage alternative (e.g. 文生 / 图生); exactly one branch survives. In
              auto mode the branch fed by the connected media wins when media is connected,
              otherwise the branch without media inputs.
  [开关:名称]  a node that can be turned off (usually an output such as the 二采 save node).
  [选项:组名]  one alternative of a group (e.g. 3/4/5-step sigmas); one per group survives and
              the rest of the title (tags stripped) is the option's label.
  [输出]       the final result: while an enabled [输出] node exists, untagged outputs are dropped.

Before /prompt the workflow is pruned. Removing a node also removes every node that consumes it,
except rgthree "Any Switch" nodes, which only lose that input (they pick the first live input).
Empty media slots only detach from their consumers (the H3 reference inputs are optional), and
finally every node no output can reach is dropped, so a disabled branch never executes.
"""
from __future__ import annotations

import re

from .comfy_workflow_tags import strip_title_tags, title_tags

_KIND_ALIASES = {
    'branch': ('分支', 'branch'),
    'toggle': ('开关', '開關', 'toggle', 'switch'),
    'option': ('选项', '選項', 'option'),
}
_KIND_BY_NAME = {alias.lower(): kind for kind, aliases in _KIND_ALIASES.items() for alias in aliases}
_SWITCH_RE = re.compile(r'[\[【]\s*(' + '|'.join(re.escape(name) for name in _KIND_BY_NAME) + r')\s*[:：]\s*([^\]】]{1,24}?)\s*[\]】]',
                        re.IGNORECASE)
_OUTPUT_RE = re.compile(r'[\[【]\s*(?:输出|輸出|output)\s*[\]】]', re.IGNORECASE)
_ANY_TAG_RE = re.compile(r'[\[【]([^\]】]{1,40})[\]】]')

SWITCH_NODE_ID = '__switches__'
SWITCH_PREFIX = 'switch:'
BRANCH_PARAM_ID = 'switch:branch'
AUTO_BRANCH = '自动'


def _title(node):
    meta = node.get('_meta') if isinstance(node, dict) else None
    return str(meta.get('title') or '') if isinstance(meta, dict) else ''


def strip_switch_tags(title):
    text = _OUTPUT_RE.sub(' ', _SWITCH_RE.sub(' ', str(title or '')))
    return re.sub(r'\s+', ' ', strip_title_tags(text)).strip()


def _is_any_switch(node):
    return 'anyswitch' in str(node.get('class_type') or '').lower().replace(' ', '').replace('_', '')


def is_output_node(node):
    key = str(node.get('class_type') or '').lower().replace('_', '')
    return 'save' in key or 'preview' in key or key == 'vhsvideocombine'


def _links(inputs):
    for name, value in (inputs or {}).items():
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int):
            yield name, str(value[0])


def _inputs(node):
    return node.get('inputs') if isinstance(node.get('inputs'), dict) else {}


def collect_workflow_switches(workflow):
    """Branches, toggles, option groups and [输出] nodes declared in an API-format workflow."""
    result = {'branches': [], 'toggles': [], 'options': [], 'outputs': [], 'warnings': []}
    if not isinstance(workflow, dict):
        return result
    branches, toggles, options = {}, {}, {}
    for raw_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        node_id, title = str(raw_id), _title(node)
        for match in _SWITCH_RE.finditer(title):
            kind, name = _KIND_BY_NAME[match.group(1).lower()], match.group(2).strip()
            if kind == 'branch':
                branches.setdefault(name, []).append(node_id)
            elif kind == 'toggle':
                toggles.setdefault(name, []).append(node_id)
            else:
                label = strip_switch_tags(title) or f'#{node_id}'
                group = options.setdefault(name, {})
                group.setdefault(label, []).append(node_id)
        if _OUTPUT_RE.search(title):
            result['outputs'].append(node_id)
    result['branches'] = [{'name': name, 'node_ids': ids} for name, ids in branches.items()]
    result['toggles'] = [{'name': name, 'node_ids': ids} for name, ids in toggles.items()]
    result['options'] = [{'group': group, 'choices': [{'label': label, 'node_ids': ids} for label, ids in choices.items()]}
                         for group, choices in options.items()]
    if len(result['branches']) == 1:
        result['warnings'].append(f'只有一个 [分支:{result["branches"][0]["name"]}]，至少需要两个分支才能切换')
    for group in result['options']:
        if len(group['choices']) < 2:
            result['warnings'].append(f'[选项:{group["group"]}] 只有一个选项')
    return result


def has_switches(switches):
    return bool(switches['branches'] or switches['toggles'] or switches['options'])


def unknown_title_tags(workflow):
    """Bracket tags no parser understands; they would otherwise be ignored silently."""
    warnings = []
    for raw_id, node in (workflow or {}).items():
        if not isinstance(node, dict):
            continue
        title = _title(node)
        for match in _ANY_TAG_RE.finditer(title):
            text = match.group(0)
            if title_tags(text) or _SWITCH_RE.fullmatch(text) or _OUTPUT_RE.fullmatch(text):
                continue
            warnings.append(f'#{raw_id} 标题中的 {text} 不是可识别的标记（参数请写成 [参数] 名称）')
    return warnings


def switch_parameters(switches):
    """Switches exposed through the workflow parameter list (rendered by the existing parameter UI)."""
    base = {'node_id': SWITCH_NODE_ID, 'node_title': '工作流开关', 'class_type': 'WorkflowSwitch'}
    parameters = []
    if len(switches['branches']) >= 2:
        names = [item['name'] for item in switches['branches']]
        parameters.append({**base, 'id': BRANCH_PARAM_ID, 'input_name': 'branch', 'label': '生成模式', 'type': 'select',
                           'options': [AUTO_BRANCH, *names], 'default': AUTO_BRANCH})
    for item in switches['toggles']:
        parameters.append({**base, 'id': f'{SWITCH_PREFIX}toggle:{item["name"]}', 'input_name': item['name'],
                           'label': item['name'], 'type': 'boolean', 'default': True})
    for group in switches['options']:
        if len(group['choices']) < 2:
            continue
        labels = [choice['label'] for choice in group['choices']]
        parameters.append({**base, 'id': f'{SWITCH_PREFIX}option:{group["group"]}', 'input_name': group['group'],
                           'label': group['group'], 'type': 'select', 'options': labels, 'default': labels[0]})
    return parameters


def _coerce_flag(value, default):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return default


def resolve_switch_choices(switches, overrides):
    """Validated choices from workflow_parameters; unknown values fall back to the defaults."""
    overrides = overrides if isinstance(overrides, dict) else {}
    choices = {}
    for parameter in switch_parameters(switches):
        raw = overrides.get(parameter['id'], parameter['default'])
        if parameter['type'] == 'boolean':
            choices[parameter['id']] = _coerce_flag(raw, parameter['default'])
        else:
            text = str(raw if raw is not None else '')
            choices[parameter['id']] = text if text in parameter['options'] else parameter['default']
    return choices


def _ancestors(workflow, node_id):
    seen, stack = set(), [node_id]
    while stack:
        current = stack.pop()
        for _name, source in _links(_inputs(workflow.get(current) or {})):
            if source in workflow and source not in seen:
                seen.add(source)
                stack.append(source)
    return seen


def _pick_branch(workflow, branches, choice, media_ids, has_media):
    by_name = {item['name']: item for item in branches}
    if choice in by_name:
        return by_name[choice]
    fed = [item for item in branches
           if any(media_ids & (_ancestors(workflow, node_id) | {node_id}) for node_id in item['node_ids'])]
    plain = [item for item in branches if item not in fed]
    if has_media and fed:
        return fed[0]
    return (plain or branches)[0]


def apply_workflow_switches(workflow, switches, choices, *, media_ids=(), empty_media_ids=()):
    """Prune a prepared workflow for the chosen switches. Returns the same dict, mutated.

    media_ids: tagged image/video/audio loaders; empty_media_ids: those whose slot is empty.
    """
    media_ids, empty = set(media_ids), set(empty_media_ids)
    removed = set()
    if len(switches['branches']) >= 2:
        keep = _pick_branch(workflow, switches['branches'], choices.get(BRANCH_PARAM_ID), media_ids,
                            has_media=bool(media_ids - empty))
        for item in switches['branches']:
            if item is not keep:
                removed.update(item['node_ids'])
    for item in switches['toggles']:
        if not choices.get(f'{SWITCH_PREFIX}toggle:{item["name"]}', True):
            removed.update(item['node_ids'])
    for group in switches['options']:
        chosen = choices.get(f'{SWITCH_PREFIX}option:{group["group"]}')
        if len(group['choices']) >= 2:
            for choice in group['choices']:
                if choice['label'] != chosen:
                    removed.update(choice['node_ids'])

    # Empty media slots detach from consumers without taking them along.
    for node_id in empty - removed:
        workflow.pop(node_id, None)
    for node in workflow.values():
        inputs = _inputs(node)
        for name, source in list(_links(inputs)):
            if source in empty:
                del inputs[name]

    # Hard removals cascade to consumers; Any Switch nodes only drop the dead input.
    pending = set(removed)
    while pending:
        for node_id in pending:
            workflow.pop(node_id, None)
        pending = set()
        for node_id, node in workflow.items():
            inputs = _inputs(node)
            dead = [name for name, source in _links(inputs) if source not in workflow]
            if not dead:
                continue
            if _is_any_switch(node):
                for name in dead:
                    del inputs[name]
                if not any(True for _ in _links(inputs)):
                    pending.add(node_id)
            else:
                pending.add(node_id)

    outputs = [node_id for node_id, node in workflow.items() if is_output_node(node)]
    final = [node_id for node_id in switches['outputs'] if node_id in workflow]
    if final:
        outputs = final
    if not outputs:
        raise ValueError('按当前开关裁剪后，工作流没有任何输出节点')
    reachable = set(outputs)
    for node_id in outputs:
        reachable |= _ancestors(workflow, node_id)
    for node_id in [node_id for node_id in workflow if node_id not in reachable]:
        del workflow[node_id]
    return workflow
