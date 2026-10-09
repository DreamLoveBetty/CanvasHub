"""Bounded public remote-image import policies.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _validated_remote_image_url(value, *, REMOTE_IMAGE_PROXY_FAKE_NETWORK, ipaddress, socket, urllib):
    """Allow public HTTP(S) image sources while blocking local-network fetches."""
    raw_url = str(value or '').strip()
    if not raw_url or len(raw_url) > 8192:
        raise ValueError('图片地址无效')
    try:
        parsed = urllib.parse.urlparse(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError('图片地址端口无效') from exc
    if parsed.scheme.lower() not in {'http', 'https'}:
        raise ValueError('仅支持 HTTP 或 HTTPS 图片地址')
    if parsed.username or parsed.password:
        raise ValueError('图片地址不能包含登录信息')
    hostname = str(parsed.hostname or '').strip().rstrip('.')
    if not hostname:
        raise ValueError('图片地址缺少主机名')
    if hostname.lower() == 'localhost' or hostname.lower().endswith('.localhost'):
        raise ValueError('不能导入本机或局域网图片地址')
    try:
        addresses = socket.getaddrinfo(hostname, port or (443 if parsed.scheme.lower() == 'https' else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError('图片地址无法解析') from exc
    if not addresses:
        raise ValueError('图片地址无法解析')
    for entry in addresses:
        address_text = str(entry[4][0] or '').split('%', 1)[0]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError as exc:
            raise ValueError('图片地址解析结果无效') from exc
        if not address.is_global and address not in REMOTE_IMAGE_PROXY_FAKE_NETWORK:
            raise ValueError('不能导入本机或局域网图片地址')
    return parsed.geturl()


def _sniff_remote_image_mime(image_bytes, *, Image, _REMOTE_IMAGE_FORMAT_MIME, io):
    head = bytes(image_bytes[:4096])
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if len(head) >= 12 and head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        return 'image/webp'
    if head.startswith(b'BM'):
        return 'image/bmp'
    if head.startswith(b'\x00\x00\x01\x00'):
        return 'image/x-icon'
    if len(head) >= 16 and head[4:8] == b'ftyp' and (b'avif' in head[:32] or b'avis' in head[:32]):
        return 'image/avif'
    text_head = head.lstrip(b'\xef\xbb\xbf\x00\t\r\n ')
    if text_head.startswith(b'<svg') or (text_head.startswith(b'<?xml') and b'<svg' in text_head[:2048]):
        return 'image/svg+xml'
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
            return _REMOTE_IMAGE_FORMAT_MIME.get(str(image.format or '').upper(), '')
    except Exception:
        return ''


def _remote_image_filename(url, mime_type, *, Path, _REMOTE_IMAGE_MIME_EXTENSION, re, safe_basename, urllib):
    parsed = urllib.parse.urlparse(str(url or ''))
    raw_name = safe_basename(urllib.parse.unquote(parsed.path or ''))
    clean_name = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', raw_name).strip(' ._')[:180]
    extension = _REMOTE_IMAGE_MIME_EXTENSION.get(mime_type, '.png')
    if not clean_name:
        return f'imported-image{extension}'
    accepted_extensions = set(_REMOTE_IMAGE_MIME_EXTENSION.values()) | {'.jpeg', '.jfif'}
    if Path(clean_name).suffix.lower() not in accepted_extensions:
        clean_name = f'{clean_name}{extension}'
    return clean_name


def _download_remote_image_for_import(
    url,
    *,
    REMOTE_IMAGE_IMPORT_MAX_BYTES,
    REMOTE_IMAGE_IMPORT_MAX_REDIRECTS,
    REMOTE_IMAGE_IMPORT_TIMEOUT,
    _remote_image_filename,
    _sniff_remote_image_mime,
    _validated_remote_image_url,
    get_proxy_config,
    requests,
    urllib,
):
    current_url = _validated_remote_image_url(url)
    headers = {
        'Accept': 'image/avif,image/webp,image/png,image/jpeg,image/gif,image/svg+xml,image/*;q=0.8,*/*;q=0.2',
        'User-Agent': 'CanvasHub/1.0 image-import',
    }
    with requests.Session() as client:
        client.trust_env = False
        proxy_config = get_proxy_config('prompt_source')
        if not proxy_config.get('enabled') or not proxy_config.get('proxy_url'):
            proxy_config = get_proxy_config()
        proxy_url = str(proxy_config.get('proxy_url') or '').strip() if proxy_config.get('enabled') else ''
        if proxy_url:
            client.proxies.update({'http': proxy_url, 'https': proxy_url})
        for redirect_index in range(REMOTE_IMAGE_IMPORT_MAX_REDIRECTS + 1):
            try:
                response = client.get(
                    current_url,
                    headers=headers,
                    stream=True,
                    timeout=REMOTE_IMAGE_IMPORT_TIMEOUT,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise ValueError(f'图片下载失败：{exc}') from exc
            with response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_index >= REMOTE_IMAGE_IMPORT_MAX_REDIRECTS:
                        raise ValueError('图片地址重定向次数过多')
                    location = str(response.headers.get('Location') or '').strip()
                    if not location:
                        raise ValueError('图片地址重定向缺少目标')
                    current_url = _validated_remote_image_url(urllib.parse.urljoin(current_url, location))
                    continue
                if response.status_code < 200 or response.status_code >= 300:
                    raise ValueError(f'图片服务器返回 HTTP {response.status_code}')
                declared_length = str(response.headers.get('Content-Length') or '').strip()
                if declared_length:
                    try:
                        declared_size = int(declared_length)
                    except ValueError:
                        declared_size = 0
                    if declared_size > REMOTE_IMAGE_IMPORT_MAX_BYTES:
                        raise ValueError('远程图片不能超过 32 MB')
                chunks = []
                total = 0
                try:
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > REMOTE_IMAGE_IMPORT_MAX_BYTES:
                            raise ValueError('远程图片不能超过 32 MB')
                        chunks.append(chunk)
                except requests.RequestException as exc:
                    raise ValueError(f'图片下载中断：{exc}') from exc
                image_bytes = b''.join(chunks)
                if not image_bytes:
                    raise ValueError('图片内容为空')
                mime_type = _sniff_remote_image_mime(image_bytes)
                if not mime_type:
                    raise ValueError('远程内容不是支持的图片格式')
                return {
                    'content': image_bytes,
                    'content_type': mime_type,
                    'filename': _remote_image_filename(current_url, mime_type),
                    'source_url': current_url,
                }
    raise ValueError('图片下载失败')
