"""CanvasHub isolation patch: use only explicitly selected account cookies."""
import re
from curl_cffi.requests import AsyncSession, Cookies
from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def get_access_token(base_cookies, proxy=None, verbose=False, verify=True, on_bootstrap=None, authuser=0):
    client = AsyncSession(impersonate='chrome', proxy=proxy, allow_redirects=True,
                          verify=verify, timeout=45)
    try:
        if isinstance(base_cookies, Cookies):
            client.cookies.update(base_cookies)
        else:
            for name, value in base_cookies.items():
                client.cookies.set(name, value, domain='.google.com')
        response = await client.get(Endpoint.INIT, params={'authuser': authuser}, headers=Headers.GEMINI.value)
        response.raise_for_status()
        def field(key):
            match = re.search(r'"' + key + r'":\s*"(.*?)"', response.text)
            return match.group(1) if match else None
        token = field('SNlM0e')
        if not token:
            raise AuthError('Gemini login session is unavailable')
        if on_bootstrap:
            on_bootstrap(response.text)
        return token, field('cfb2h'), field('FdrFJe'), field('TuX5cc'), field('qKIAYe'), client
    except BaseException:
        await client.close()
        raise
