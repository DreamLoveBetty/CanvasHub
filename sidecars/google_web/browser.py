"""Optional macOS Chrome importer. Never invoked implicitly by a request/session."""
import importlib.util
from pathlib import Path
import sys
from .errors import WebError
from .store import normalize_cookies

CHROME_ROOT = Path.home() / 'Library/Application Support/Google/Chrome'


def available():
    return sys.platform == 'darwin' and importlib.util.find_spec('browser_cookie3') is not None and CHROME_ROOT.is_dir()


def profiles():
    try:
        if not available():
            raise WebError('当前服务端不支持本机 Chrome 导入，请导入 Cookie JSON', 409, 'browser_unavailable')
        return [{'id': p.name, 'label': p.name} for p in sorted(CHROME_ROOT.iterdir())
                if p.is_dir() and not p.is_symlink() and (p.name == 'Default' or p.name.startswith('Profile '))
                and any((p / name).is_file() for name in ('Cookies', 'Network/Cookies'))]
    except PermissionError:
        raise WebError('macOS 阻止账号服务读取 Chrome 目录。请在服务端电脑的「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中为账号服务 Python 授权，再重启账号服务。',
                       409, 'browser_permission_required') from None


def import_profile(profile):
    if profile not in {item['id'] for item in profiles()}:
        raise WebError('请选择服务端可用的 Chrome Profile', 400, 'invalid_profile')
    import browser_cookie3
    directory = CHROME_ROOT / profile
    cookie_file = next(p for p in (directory / 'Cookies', directory / 'Network/Cookies') if p.is_file())
    try:
        jar = browser_cookie3.chrome(cookie_file=str(cookie_file), domain_name='google.com')
        cookies = normalize_cookies([{'name': c.name, 'value': c.value, 'domain': c.domain, 'expires': c.expires} for c in jar])
    except Exception:
        raise WebError('无法读取服务端 Chrome 登录态，请在服务端电脑完成系统授权或改用 JSON 导入', 409, 'browser_permission_required') from None
    return {'label': 'Chrome · ' + profile, 'source_profile': profile, 'cookies': cookies}
