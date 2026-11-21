"""Allowlisted, size-limited grouped quota records. Never keep raw upstream payloads."""

from __future__ import annotations

import re

MAX_GROUPS = 16
MAX_BUCKETS = 16
MAX_LABEL = 80
MAX_WINDOW = 40
MAX_DESCRIPTION = 200
MAX_RESET = 80

_EMAIL_RE = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')
_URL_RE = re.compile(r'(https?://|www\.)', re.I)
_JWT_RE = re.compile(r'eyJ[A-Za-z0-9_-]+')
_BEARER_RE = re.compile(r'Bearer\s+\S', re.I)
_BLOB_RE = re.compile(r'^[A-Za-z0-9+/=._-]{80,}$')


def _polluted(value: str) -> bool:
    return bool(
        _EMAIL_RE.search(value)
        or _URL_RE.search(value)
        or _JWT_RE.search(value)
        or _BEARER_RE.search(value)
        or _BLOB_RE.fullmatch(value)
    )


def safe_text(value, maximum):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _polluted(text):
        return None
    return text[:maximum]


def _first(raw: dict, *keys):
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def parse_remaining_fraction(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    if number < 0 or number > 1:
        return None
    return number


def normalize_bucket(raw):
    if not isinstance(raw, dict):
        return None
    fraction = parse_remaining_fraction(
        _first(raw, 'remaining_fraction', 'remainingFraction')
    )
    percentage = None if fraction is None else int(round(fraction * 100))
    return {
        'bucket_id': safe_text(_first(raw, 'bucket_id', 'bucketId'), MAX_LABEL) or '',
        'window': safe_text(_first(raw, 'window'), MAX_WINDOW) or '',
        'remaining_fraction': fraction,
        'percentage': percentage,
        'reset_time': safe_text(_first(raw, 'reset_time', 'resetTime'), MAX_RESET) or '',
        'display_name': safe_text(_first(raw, 'display_name', 'displayName'), MAX_LABEL) or '',
        'description': safe_text(_first(raw, 'description'), MAX_DESCRIPTION) or '',
    }


def normalize_group(raw):
    if not isinstance(raw, dict):
        return None
    buckets_raw = raw.get('buckets')
    buckets = []
    if isinstance(buckets_raw, list):
        for item in buckets_raw:
            bucket = normalize_bucket(item)
            if bucket is None:
                continue
            buckets.append(bucket)
            if len(buckets) >= MAX_BUCKETS:
                break
    return {
        'display_name': safe_text(_first(raw, 'display_name', 'displayName'), MAX_LABEL) or '',
        'description': safe_text(_first(raw, 'description'), MAX_DESCRIPTION) or '',
        'buckets': buckets,
    }


def normalize_quota_summary(raw):
    if not isinstance(raw, dict):
        return None
    groups_raw = raw.get('groups')
    if not isinstance(groups_raw, list):
        return None
    groups = []
    for item in groups_raw:
        group = normalize_group(item)
        if group is None:
            continue
        groups.append(group)
        if len(groups) >= MAX_GROUPS:
            break
    value = {'groups': groups}
    description = safe_text(raw.get('description'), MAX_DESCRIPTION)
    if description:
        value['description'] = description
    return value


def has_usable_quota_groups(groups):
    if not isinstance(groups, list):
        return False
    for group in groups:
        if not isinstance(group, dict):
            continue
        buckets = group.get('buckets')
        if isinstance(buckets, list) and any(isinstance(bucket, dict) for bucket in buckets):
            return True
    return False


def sanitize_quota_groups(groups):
    normalized = normalize_quota_summary({'groups': groups if isinstance(groups, list) else []})
    return normalized['groups'] if normalized else []


# Official retrieveUserQuotaSummary bucketId families, matching Cockpit Tools
# v1.4.2 summary_bucket_family (exact id, not description or model-name guesses).
_CLAUDE_IDS = {'3p-5h', 'claude:5h', '3p-weekly', 'claude:weekly'}
_GEMINI_IDS = {'gemini-5h', 'gemini:5h', 'gemini-weekly', 'gemini:weekly'}
_ARGON_IDS = {'argon:weekly', 'argon:5h'}
_CARBON_IDS = {'carbon:weekly', 'gemini-carbon-wtu-weekly'}


def official_bucket_family(bucket_id):
    name = bucket_id.strip() if isinstance(bucket_id, str) else ''
    if not name:
        return None
    if name in _CLAUDE_IDS:
        return 'claude'
    if name in _GEMINI_IDS:
        return 'gemini'
    if name in _ARGON_IDS:
        return 'argon'
    if name in _CARBON_IDS:
        return 'carbon'
    if name.startswith('gemini-argon-') and (name.endswith('-weekly') or name.endswith('-5h')):
        return 'argon'
    return None


def official_bucket_window(bucket):
    if not isinstance(bucket, dict):
        return ''
    window = bucket.get('window')
    window = window.strip() if isinstance(window, str) else ''
    family = official_bucket_family(bucket.get('bucket_id'))
    if window in ('5h', 'weekly'):
        return window
    if family:
        name = bucket.get('bucket_id')
        name = name.strip() if isinstance(name, str) else ''
        if name.endswith('-5h') or name.endswith(':5h'):
            return '5h'
        if name.endswith('-weekly') or name.endswith(':weekly'):
            return 'weekly'
        return window
    return window

