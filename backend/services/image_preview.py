"""Browser preview conversion, separate from original-file download/delivery."""
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
import io


def preview_url(url):
    parts = urlsplit(url)
    if Path(parts.path).suffix.lower() not in ('.tif', '.tiff'):
        return url
    query = dict(parse_qsl(parts.query))
    query['preview'] = '1'
    return urlunsplit(parts._replace(query=urlencode(query)))


def image_url(filename):
    return preview_url('/image/' + quote(Path(filename).name))


def preview_png(path):
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        if image.width * image.height > 100_000_000:
            raise ValueError('图片超过浏览器预览像素上限')
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()
