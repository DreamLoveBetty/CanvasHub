"""Authenticated desktop management adapter, separate from GPT account routes."""

import json
from .base import ProtectedRouter


def create_router(client, *, domain='google-pool'):
    def handle(handler, action, method):
        try:
            body = None
            if method == 'POST':
                length = int(handler.headers.get('Content-Length') or 0)
                if not 0 < length <= 2 * 1024 * 1024:
                    handler.send_json({'error': 'Google账号操作请求大小无效'}, 400)
                    return
                body = json.loads(handler.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError()
            handler.send_json(client.request(action, body))
        except (ValueError, TypeError):
            handler.send_json({'error': '请求必须为有效JSON对象'}, 400)
        except RuntimeError as e:
            handler.send_json({'error': str(e)}, 502)

    actions = [
        'config',
        'oauth-start',
        'oauth-finish',
        'accounts-import',
        'account-refresh',
        'account-update',
        'account-delete',
    ]
    if domain == 'google-web':
        actions = ['config', 'accounts-import', 'account-check', 'account-update',
                   'account-delete', 'account-expand', 'browser-profiles', 'browser-import']
    elif domain != 'google-pool':
        raise ValueError('未知 Google 账号服务')
    prefix = '/api/' + domain + '/'
    routes = {('GET', prefix + 'status'): lambda h: handle(h, 'status', 'GET')}
    for action in actions:
        routes[('POST', prefix + action)] = lambda h, a=action: handle(
            h, a, 'POST'
        )
    return ProtectedRouter(routes)
