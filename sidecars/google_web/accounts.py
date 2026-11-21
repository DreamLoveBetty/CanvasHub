"""Read-only discovery of Google identities sharing one selected Cookie session."""
import asyncio
import json
import logging
import re
from urllib.parse import urlparse
from .errors import WebError
from .identity import parse_identity
from .store import COOKIE_NAMES, cookie_records_from_jar, cookie_source_stats, normalize_cookies

logger = logging.getLogger(__name__)
HINTS = {
    'login_wall': '当前会话打开 Gemini 时落到登录页，而不是已登录会话',
    'missing_fields': 'Gemini 页面缺少可识别的登录字段',
    'slot_mismatch': '页面账号序号与请求序号不一致',
    'early_stop': '连续两个无效会话后已停止扫描',
}


def bootstrap_field(html, name):
    match = re.search(r'"' + re.escape(name) + r'"\s*:\s*("(?:[^"\\]|\\.)*")', html)
    if match:
        try:
            return json.loads(match[1])
        except ValueError:
            pass
    return ''


def require_identity(html, authuser, expected_email):
    identity = parse_identity(html)
    if expected_email and (identity['email'].casefold() != expected_email.casefold()
            or bootstrap_field(html, 'QrtxK') != str(authuser)):
        raise WebError('Google 账号顺序或登录态已变化，请重新识别同会话账号；未提交生成',
                       409, 'web_account_changed')
    return identity


def response_host_kind(response):
    parsed = urlparse(str(getattr(response, 'url', '') or ''))
    host = (parsed.hostname or '').lower()
    path = parsed.path or ''
    if 'accounts.google.' in host or 'signin' in path.lower() or 'ServiceLogin' in path:
        return 'accounts'
    if 'gemini.google.' in host:
        return 'gemini'
    return 'other' if host else 'unknown'


def classify_slot(slot, response):
    html = response.text or ''
    has_login_token = bool(bootstrap_field(html, 'SNlM0e'))
    has_email = bool(parse_identity(html).get('email'))
    qrtxk = bootstrap_field(html, 'QrtxK')
    has_slot_token = bool(qrtxk)
    slot_matches = qrtxk == str(slot)
    host_kind = response_host_kind(response)
    if has_login_token and has_email and slot_matches:
        reason = 'ok'
    elif has_login_token and has_email:
        reason = 'slot_mismatch'
    elif host_kind == 'accounts' or (
            not has_login_token and not has_email and not has_slot_token and host_kind != 'gemini'):
        reason = 'login_wall'
    else:
        reason = 'missing_fields'
    return {
        'slot': slot,
        'reason': reason,
        'has_login_token': has_login_token,
        'has_email': has_email,
        'has_slot_token': has_slot_token,
        'slot_matches': slot_matches,
        'host_kind': host_kind,
    }


def cookie_presence(cookies):
    return {name: bool(cookies.get(name)) for name in sorted(COOKIE_NAMES)}


def discovery_details(traces, *, stopped_early, valid_count, cookies=None):
    counts = {}
    host_kind_counts = {}
    for trace in traces:
        host = trace.get('host_kind') or 'unknown'
        host_kind_counts[host] = host_kind_counts.get(host, 0) + 1
        if trace['reason'] == 'ok':
            continue
        counts[trace['reason']] = counts.get(trace['reason'], 0) + 1
    if valid_count:
        primary = 'ok'
    elif counts:
        rank = {'login_wall': 3, 'missing_fields': 2, 'slot_mismatch': 1}
        primary = max(counts, key=lambda name: (counts[name], rank.get(name, 0)))
    else:
        primary = 'early_stop' if stopped_early else 'missing_fields'
    details = {
        'primary_reason': primary,
        'reason_counts': counts,
        'host_kind_counts': host_kind_counts,
        'slots_tried': len(traces),
        'valid_count': valid_count,
        'stopped_early': bool(stopped_early),
    }
    if cookies is not None:
        details['cookie_presence'] = cookie_presence(cookies)
    return details


def expired_error(details):
    message = '所选会话未找到已登录的 Gemini 账号，请在该 Chrome 用户内打开 Gemini 后重新导入'
    hint = HINTS.get(details.get('primary_reason'))
    if hint:
        message = message + '（' + hint + '）'
    logger.info('gemini web discovery failed: %s', details)
    return WebError(message, 401, 'web_auth_expired', details={'discovery': details})



def apply_cookie_records(session, records):
    for item in records or []:
        if not isinstance(item, dict):
            continue
        name, value = item.get('name'), item.get('value')
        if not name or not isinstance(value, str) or not value:
            continue
        domain = str(item.get('domain') or '.google.com')
        host = domain.lstrip('.').lower()
        if host != 'google.com' and not host.endswith('.google.com'):
            continue
        path = str(item.get('path') or '/') or '/'
        session.cookies.set(name, value, domain=domain if domain.startswith('.') or host != 'google.com' else '.google.com', path=path)


async def discover_accounts(item, settings):
    from curl_cffi.requests import AsyncSession
    cookies = normalize_cookies(item['cookies'])
    found, seen, missing, traces = [], set(), 0, []
    try:
        async with asyncio.timeout(90), AsyncSession(impersonate='chrome', proxy=settings.proxy_url or None,
                verify=True, timeout=20, allow_redirects=True) as session:
            records = item.get('cookie_records')
            if not isinstance(records, list) or not records:
                records = [{'name': name, 'value': value, 'domain': '.google.com', 'path': '/'}
                           for name, value in cookies.items()]
            apply_cookie_records(session, records)
            last_good_records = list(records)
            for slot in range(20):
                response = await session.get('https://gemini.google.com/app', params={'authuser': slot})
                response.raise_for_status()
                identity = parse_identity(response.text)
                email = identity['email']
                trace = classify_slot(slot, response)
                traces.append(trace)
                valid = trace['reason'] == 'ok'
                if not valid or email.casefold() in seen:
                    missing += 1
                    if missing >= 2:
                        break
                    continue
                missing = 0
                seen.add(email.casefold())
                found.append(dict(identity, authuser=slot, label=item.get('label') or 'Web 账号',
                                  source_profile=item.get('source_profile') or ''))
                last_good_records = cookie_records_from_jar(session.cookies.jar) or last_good_records
            records = last_good_records
            cookies = normalize_cookies(records or cookies)
    except WebError:
        raise
    except Exception:
        raise WebError('读取同会话 Google 账号失败，请检查服务端网络或稍后重试', 502, 'web_discovery_failed') from None
    details = discovery_details(traces, stopped_early=len(traces) < 20, valid_count=len(found), cookies=cookies)
    stats = item.get('cookie_stats')
    if not isinstance(stats, dict):
        stats = cookie_source_stats(item.get('cookie_records') or cookies)
    details['cookie_source'] = stats
    if not found:
        raise expired_error(details)
    logger.info('gemini web discovery succeeded: slots_tried=%s valid_count=%s', details['slots_tried'], details['valid_count'])
    return [dict(account, cookies=cookies, cookie_records=records) for account in found]
