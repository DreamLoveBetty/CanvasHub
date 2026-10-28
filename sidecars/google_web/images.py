"""Download Web originals without assuming a fixed number of URL pointer hops."""
import io
import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from PIL import Image
from .errors import WebError

REFERER = {'Referer': 'https://gemini.google.com/', 'Origin': 'https://gemini.google.com'}
MAX_BYTES = 32 * 1024 * 1024


def _trusted_url(url):
    if not isinstance(url, str) or not url or len(url) > 16384 or any(c.isspace() for c in url):
        raise ValueError('invalid image URL')
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    # Generated-image CDN URLs can authenticate through these Google gateways and
    # then redirect back to the CDN. Do not allow arbitrary Google pages/hosts.
    image_host = host.endswith('.googleusercontent.com') or (
        host == 'work.fife.usercontent.google.com' and parsed.path.startswith('/rd-gg-dl/')) or (
        host == 'lh3.google.com' and parsed.path.startswith('/rd-gg/')
        and not any(part in ('.', '..') for part in unquote(parsed.path).split('/')))
    if (parsed.scheme != 'https' or not image_host
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('untrusted image URL')
    return url


def _size_url(url, *, original=False, authuser=None):
    parsed = urlsplit(_trusted_url(url))
    # Only replace a Google image transformation suffix, never a signed query.
    path = re.sub(r'=(?:s\d+|w\d+|d)(?:-[A-Za-z0-9]+)*$', '', parsed.path)
    query = parsed.query
    if original:
        if re.search(r'(^|&)alr=', query):
            query = re.sub(r'(^|&)alr=[^&]*', r'\1alr=yes', query)
        else:
            query += ('&' if query else '') + 'alr=yes'
    if authuser is not None:
        if type(authuser) is not int or not 0 <= authuser < 20:
            raise ValueError('invalid image account')
        if re.search(r'(^|&)authuser=', query):
            query = re.sub(r'(^|&)authuser=[^&]*', lambda match: match[1] + f'authuser={authuser}', query)
        elif authuser:
            # The CDN otherwise authenticates as slot 0, independently of the RPC.
            # Append only this selector, preserving all existing signature bytes.
            query += ('&' if query else '') + f'authuser={authuser}'
    return urlunsplit((parsed.scheme, parsed.netloc, path + ('=d-I' if original else '=s0'), query, ''))


def _validate_image(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('invalid image size')
    with Image.open(io.BytesIO(raw)) as image:
        mime = Image.MIME.get(image.format)
        image.verify()
    if mime not in ('image/png', 'image/jpeg', 'image/webp'):
        raise ValueError('invalid image format')
    return mime


class ImageDownloadFailure(ValueError):
    """Safe transport classification, never an upstream exception message."""
    def __init__(self, reason, http_status=None, transport_code=None):
        super().__init__(reason)
        self.reason, self.http_status, self.transport_code = reason, http_status, transport_code

    def public_reason(self):
        if self.http_status is not None:
            return f'HTTP {self.http_status}'
        label = {'transport_error': '网络传输失败', 'url_rejected': '地址校验未通过',
            'loop': '下载地址循环', 'invalid_image': '图片数据无效',
            'invalid_pointer': '下载地址响应无效', 'too_many_hops': '下载跳转过多',
            'rpc_missing_context': '缺少原图定位信息', 'rpc_no_url': 'RPC 未返回地址',
            'rpc_error': 'RPC 请求失败'}.get(self.reason, '下载异常')
        return label + (f'（网络代码 {self.transport_code}）' if self.transport_code is not None else '')


async def _fetch_image(session, url, *, trace=None, stage='original'):
    seen = set()
    for hop in range(6):
        def fail(reason, *, http_status=None, transport_code=None):
            if trace:
                trace.event(stage, reason, hop=hop, http_status=http_status, transport_code=transport_code)
            raise ImageDownloadFailure(reason, http_status, transport_code) from None

        try:
            url = _trusted_url(url)
        except Exception:
            fail('url_rejected')
        if url in seen:
            fail('loop')
        seen.add(url)
        try:
            response = await session.get(url, headers=REFERER, allow_redirects=False)
        except Exception as error:
            code = getattr(error, 'code', None)
            code = int(code) if isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 999 else None
            fail('transport_error', transport_code=code)
        if trace:
            trace.event(stage, 'response', hop=hop, http_status=response.status_code,
                host_kind='cdn' if urlsplit(url).hostname.endswith('.googleusercontent.com') else 'image_gateway')
        if response.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, response.headers.get('location', ''))
            continue
        if response.status_code != 200:
            fail('http_error', http_status=response.status_code)
        raw = response.content
        # Google can return bytes on the first hop, after text pointers or redirects.
        # Do not interpret HTML/error documents as either a URL or a successful image.
        if raw.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'RIFF')):
            try:
                return raw, _validate_image(raw)
            except Exception:
                fail('invalid_image')
        if len(raw) > 16384:
            fail('invalid_pointer')
        try:
            pointer = raw.decode('utf-8').strip()
        except UnicodeError:
            fail('invalid_pointer')
        if not pointer.startswith('https://') or any(c.isspace() for c in pointer):
            fail('invalid_pointer')
        url = pointer
    if trace:
        trace.event(stage, 'too_many_hops')
    raise ImageDownloadFailure('too_many_hops')


async def download_generated_image(image, session, *, trace=None):
    """Returns unchanged bytes, MIME and public provenance, never signed URLs."""
    reason = 'rpc_missing_context'
    original_error = ImageDownloadFailure('rpc_missing_context')
    authuser = getattr(image.client_ref, 'authuser', None)
    if all((image.client_ref, image.cid, image.rid, image.rcid, image.image_id)):
        reason = 'rpc_unavailable'
        original_error = ImageDownloadFailure('rpc_no_url')
        try:
            context = dict(cid=image.cid, rid=image.rid, rcid=image.rcid, image_id=image.image_id)
            if getattr(image, 'temporary', False):
                context['temporary'] = True
            if trace:
                context['on_diagnostic'] = lambda event, **fields: trace.event('rpc', event, **fields)
            original_url = await image.client_ref._get_full_size_image(**context)
        except Exception:
            original_error = ImageDownloadFailure('rpc_error')
            if trace:
                trace.event('rpc', 'rpc_error')
        else:
            if original_url:
                reason = 'download_failed'
                if trace:
                    trace.original_url(original_url)
                try:
                    raw, mime = await _fetch_image(session, _size_url(original_url, original=True,
                        authuser=authuser), trace=trace, stage='original')
                except ImageDownloadFailure as error:
                    original_error = error
                except Exception as error:
                    original_error = ImageDownloadFailure('url_rejected' if isinstance(error, ValueError) else 'unexpected_error')
                    if trace:
                        trace.event('original', original_error.reason)
                else:
                    if trace:
                        trace.finish('verified')
                    return raw, mime, {'web_image_source': 'original_rpc', 'web_original_verified': True}
            elif trace:
                trace.event('rpc', 'rpc_no_url')
    elif trace:
        trace.event('rpc', 'rpc_missing_context')
    try:
        raw, mime = await _fetch_image(session, _size_url(image.url, authuser=authuser), trace=trace, stage='preview')
    except Exception as error:
        preview_error = error if isinstance(error, ImageDownloadFailure) else ImageDownloadFailure(
            'url_rejected' if isinstance(error, ValueError) else 'unexpected_error')
        if trace:
            if not isinstance(error, ImageDownloadFailure):
                trace.event('preview', preview_error.reason)
            trace.finish('failed')
        diagnostic = f'；诊断 {trace.id}' if trace else ''
        raise WebError(f'Gemini Web 图片下载失败（原图 {original_error.public_reason()}；'
            f'预览图 {preview_error.public_reason()}）{diagnostic}；未重新提交生成',
            502, 'web_image_download_failed') from None
    if trace:
        trace.finish('preview')
    return raw, mime, {'web_image_source': 'preview_fallback', 'web_original_verified': False,
                       'web_original_error': reason}
