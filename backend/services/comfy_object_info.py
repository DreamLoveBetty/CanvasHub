"""ComfyUI COMBO choices for workflow parameters, and repair of exported values they reject.

An API-format export keeps only a dropdown's current value, not its choices, so a string input
such as ResolutionSelector.aspect_ratio would render as free text. ComfyOptionLookup asks
ComfyUI's /object_info/<class> once per node class and caches the answer; while ComfyUI is
unreachable it returns None and the parameter stays a text field.

ComfyUI's "Export (API)" also writes some widget values into the wrong input when a node has
dynamic or hidden (advanced) widgets, e.g. CreateVideo.chroma_subsampling = 'none'. /prompt
rejects such values, so repair_invalid_choices() swaps them for the node's default before submit.
File pickers (uploads, model lists) are never repaired: their choices change as files are added.
"""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import quote

SUCCESS_TTL = 600.0
FAILURE_TTL = 60.0
LOOKUP_TIMEOUT = 3.0


def combo_choices(spec):
    """Choices of one /object_info input spec: legacy [[...], {...}] or ["COMBO", {"options": [...]}]."""
    if not isinstance(spec, list) or not spec:
        return None
    head = spec[0]
    if isinstance(head, list):
        values = head
    elif head == 'COMBO' and len(spec) > 1 and isinstance(spec[1], dict):
        values = spec[1].get('options')
    else:
        return None
    if not isinstance(values, list) or not values or not all(isinstance(item, str) for item in values):
        return None
    return list(values)


_FILE_CHOICE_RE = re.compile(r'[/\\]|\.[A-Za-z0-9]{2,12}$')
_UPLOAD_FLAGS = ('image_upload', 'video_upload', 'audio_upload', 'remote')


def combo_spec(spec):
    """{'choices', 'default', 'files'} for a COMBO input spec, or None for any other input type."""
    choices = combo_choices(spec)
    if not choices:
        return None
    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    files = any(options.get(flag) for flag in _UPLOAD_FLAGS) or any(_FILE_CHOICE_RE.search(item) for item in choices)
    default = options.get('default')
    return {'choices': choices, 'default': default if default in choices else choices[0], 'files': bool(files)}


def class_combo_specs(info, class_type):
    """{input_name: combo_spec} for one class from an /object_info/<class> response."""
    node = info.get(class_type) if isinstance(info, dict) else None
    inputs = node.get('input') if isinstance(node, dict) else None
    result = {}
    for section in ('required', 'optional'):
        fields = inputs.get(section) if isinstance(inputs, dict) else None
        for name, spec in (fields.items() if isinstance(fields, dict) else ()):
            parsed = combo_spec(spec)
            if parsed:
                result[str(name)] = parsed
    return result


def class_combo_choices(info, class_type):
    """{input_name: [choices]} for one class from an /object_info/<class> response."""
    return {name: spec['choices'] for name, spec in class_combo_specs(info, class_type).items()}


def repair_invalid_choices(workflow, class_specs):
    """Replace literal COMBO values ComfyUI would reject with that input's default, in place.

    class_specs(class_type) -> {input: combo_spec} or None (unknown / offline: the node is left alone).
    Returns one record per change: {node_id, title, class_type, input, value, replacement}.
    """
    repairs = []
    for node_id, node in (workflow.items() if isinstance(workflow, dict) else ()):
        inputs = node.get('inputs') if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        class_type = str(node.get('class_type') or '')
        specs = None
        for name, value in list(inputs.items()):
            if not isinstance(value, str) or '{{' in value:  # links, numbers, booleans and unfilled tokens
                continue
            if specs is None:
                specs = class_specs(class_type) or {}
            spec = specs.get(name)
            if not spec or spec['files'] or value in spec['choices']:
                continue
            inputs[name] = spec['default']
            repairs.append({'node_id': str(node_id), 'title': str((node.get('_meta') or {}).get('title') or class_type)[:100],
                            'class_type': class_type, 'input': name, 'value': value, 'replacement': spec['default']})
    return repairs


class ComfyOptionLookup:
    """lookup(class_type, input_name) -> list of choices, or None when unknown or offline.

    class_specs(class_type) -> {input: combo_spec} feeds repair_invalid_choices().
    """

    def __init__(self, new_session, get_config, *, clock=time.monotonic):
        self.new_session, self.get_config, self.clock = new_session, get_config, clock
        self._lock = threading.Lock()
        self._classes = {}  # (base_url, class_type) -> (expires_at, {input: combo_spec})
        self._offline = {}  # base_url -> expires_at; one failed request skips the host for a while

    def __call__(self, class_type, input_name):
        specs = self.class_specs(class_type)
        return list(specs[input_name]['choices']) if specs and input_name in specs else None

    def class_specs(self, class_type):
        class_type = str(class_type or '').strip()
        if not class_type:
            return None
        config = self.get_config()
        base_url = str(config.get('base_url') or '').rstrip('/')
        if not base_url:
            return None
        now = self.clock()
        with self._lock:
            cached = self._classes.get((base_url, class_type))
            if cached and cached[0] > now:
                return cached[1]
            if self._offline.get(base_url, 0) > now:
                return None
        try:
            timeout = min(LOOKUP_TIMEOUT, float(config.get('timeout_seconds') or LOOKUP_TIMEOUT))
            with self.new_session() as session:
                response = session.get(f'{base_url}/object_info/{quote(class_type, safe="")}', timeout=timeout)
                response.raise_for_status()
                info = response.json()
        except Exception:
            with self._lock:
                self._offline[base_url] = now + FAILURE_TTL
            return None
        specs = class_combo_specs(info, class_type)
        with self._lock:
            self._classes[(base_url, class_type)] = (now + SUCCESS_TTL, specs)
        return specs
