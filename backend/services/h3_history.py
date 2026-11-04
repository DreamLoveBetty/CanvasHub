"""Public view of archived MiniMax H3 task params.

The H3 Runtime bridge is gone; these helpers keep old tasks readable in history.
Dependencies are supplied explicitly by the compatibility entrypoints.
"""
from __future__ import annotations


def _public_h3_acceleration(value, *, _H3_PUBLIC_ACCELERATION_KEYS):
    if not isinstance(value, dict):
        return {}
    public = {}
    for key in _H3_PUBLIC_ACCELERATION_KEYS:
        item = value.get(key)
        if item is None or isinstance(item, (dict, list, tuple, set, bytes, bytearray)):
            continue
        if isinstance(item, str):
            item = item[:200]
        public[key] = item
    return public


def _public_h3_task_params(params, *, _H3_PUBLIC_TASK_PARAM_KEYS, _public_h3_acceleration, safe_basename):
    if not isinstance(params, dict):
        return {}
    public = {
        key: value
        for key, value in params.items()
        if key in _H3_PUBLIC_TASK_PARAM_KEYS
    }
    seed = public.get('seed')
    if isinstance(seed, int) and abs(seed) > 9_007_199_254_740_991:
        public['seed'] = str(seed)
    if 'acceleration' in public:
        public['acceleration'] = _public_h3_acceleration(public.get('acceleration'))
    if isinstance(public.get('sidecar_files'), dict):
        public['sidecar_files'] = {
            str(key)[:40]: safe_basename(value)
            for key, value in public['sidecar_files'].items()
            if value
        }
    return public
