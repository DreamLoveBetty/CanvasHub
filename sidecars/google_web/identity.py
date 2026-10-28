"""Public identity from the selected Gemini session, never Chrome's sync account."""
from html.parser import HTMLParser
import json
import re


class _AccountMenus(HTMLParser):
    def __init__(self):
        super().__init__()
        self.accounts = []

    def handle_starttag(self, tag, attrs):
        label = dict(attrs).get('aria-label') or ''
        match = re.fullmatch(r'Google\s+(?:Account|账号|帳戶|帐户|账户)\s*[:：]\s*(.*?)\s*[（(]([^()（）\s]+@[^()（）\s]+)[)）]\s*',
                             label, re.IGNORECASE | re.DOTALL)
        if match:
            self.accounts.append((' '.join(match[1].split())[:120], match[2]))


def parse_identity(html):
    """Prefer active bootstrap email; never pick an arbitrary email from page JSON."""
    identity = {'display_name': '', 'email': ''}
    match = re.search(r'"oPEP7c"\s*:\s*("(?:[^"\\]|\\.)*")', html)
    if match:
        try:
            email = json.loads(match[1])
            if isinstance(email, str) and len(email) <= 254 and re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', email):
                identity['email'] = email
        except ValueError:
            pass
    menus = _AccountMenus()
    menus.feed(html)
    accounts = menus.accounts
    if identity['email']:
        accounts = [item for item in accounts if item[1].casefold() == identity['email'].casefold()]
    elif len(accounts) == 1:
        identity['email'] = accounts[0][1][:254]
    else:
        accounts = []
    if accounts:
        identity['display_name'] = accounts[0][0]
    return identity
