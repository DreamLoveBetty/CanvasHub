"""CanvasHub patch: rotate in-memory only; WebStore owns persistence."""
from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def rotate_1psidts(client, verbose=False):
    response = await client.post(url=Endpoint.ROTATE_COOKIES,
        headers=Headers.ROTATE_COOKIES.value, data='[000,"-0000000000000000000"]')
    if response.status_code == 401:
        raise AuthError('Cookie refresh requires sign-in')
    response.raise_for_status()
    return next((c.value for c in client.cookies.jar if c.name == '__Secure-1PSIDTS'), None)


def save_cookies(cookies, verbose=False):
    # Intentionally no file/cache side effects. Caller persists selected account.
    pass
