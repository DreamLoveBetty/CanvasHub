"""Read-only discovery of Google identities sharing one selected Cookie session."""
import asyncio
import json
import re
from .errors import WebError
from .identity import parse_identity
from .store import normalize_cookies


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


async def discover_accounts(item, settings):
    from curl_cffi.requests import AsyncSession
    cookies = normalize_cookies(item['cookies'])
    found, seen, missing = [], set(), 0
    try:
        async with asyncio.timeout(90), AsyncSession(impersonate='chrome', proxy=settings.proxy_url or None,
                verify=True, timeout=20, allow_redirects=True) as session:
            for name, value in cookies.items():
                session.cookies.set(name, value, domain='.google.com')
            for slot in range(20):
                response = await session.get('https://gemini.google.com/app', params={'authuser': slot})
                response.raise_for_status()
                identity = parse_identity(response.text)
                email = identity['email']
                valid = (bootstrap_field(response.text, 'SNlM0e') and email
                         and bootstrap_field(response.text, 'QrtxK') == str(slot))
                if not valid or email.casefold() in seen:
                    missing += 1
                    if missing >= 2:
                        break
                    continue
                missing = 0
                seen.add(email.casefold())
                found.append(dict(identity, authuser=slot, label=item.get('label') or 'Web 账号',
                                  source_profile=item.get('source_profile') or ''))
            rotated = {c.name: c.value for c in session.cookies.jar
                       if (str(c.domain).lstrip('.') == 'google.com' or str(c.domain).endswith('.google.com')) and not c.is_expired()}
            cookies = normalize_cookies(dict(cookies, **rotated))
    except WebError:
        raise
    except Exception:
        raise WebError('读取同会话 Google 账号失败，请检查服务端网络或稍后重试', 502, 'web_discovery_failed') from None
    if not found:
        raise WebError('所选会话未找到已登录的 Gemini 账号，请在该 Chrome 用户内打开 Gemini 后重新导入',
                       401, 'web_auth_expired')
    return [dict(account, cookies=cookies) for account in found]
