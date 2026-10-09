"""Bounded observations from the pinned YuE2 CLI; no inferred global percentage.

Song generation writes non-TTY [YuE2] progress, transcription writes JSON.
Counts belong to the current stage. AR token limits are never work totals.
"""
import json
import re

_LINE = re.compile(r'^\[YuE2\] (Starting|Running|Completed|Failed|Cancelled|Finished \(generation limit reached\)) ([^:\r\n]{1,120}): (.*)$')
_COUNT = re.compile(r'^(\d{1,12})(?:/(\d{1,12}))? (tokens|steps|chunks|items)(?: \([\d.]+%\))?(?: \| |$)')
_STATES = {'Starting': 'starting', 'Running': 'running', 'Completed': 'completed',
           'Failed': 'failed', 'Cancelled': 'cancelled',
           'Finished (generation limit reached)': 'truncated'}


def normalize_progress(event):
    if not isinstance(event, dict) or not isinstance(event.get('stage'), str) or not event['stage'].strip():
        return None
    result = {'stage': event['stage'].strip()[:120]}
    for key in ('tokens', 'window', 'windows', 'completed', 'total'):
        value = event.get(key)
        if type(value) is int and 0 <= value <= 10**12:
            result[key] = value
    if event.get('unit') in ('tokens', 'steps', 'chunks', 'items'):
        result['unit'] = event['unit']
    if event.get('phase_status') in _STATES.values():
        result['phase_status'] = event['phase_status']
    return result


def parse_progress_line(line):
    if not isinstance(line, str) or len(line) > 4096:
        return None
    try:
        return normalize_progress(json.loads(line))
    except (ValueError, TypeError):
        pass
    match = _LINE.fullmatch(line.strip())
    if not match:
        return None
    state, stage, detail = match.groups()
    event = {'stage': stage, 'phase_status': _STATES[state]}
    count = _COUNT.match(detail)
    if count:
        completed, total, unit = count.groups()
        event.update(completed=int(completed), unit=unit)
        if total is not None:
            event['total'] = int(total)
        if unit == 'tokens':
            event['tokens'] = int(completed)
    return normalize_progress(event)
