"""Replaceable Civitai metadata provider. No model uploads or runtime imports."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .previews import MAX_BYTES
from .contracts import validate_fields

MAX_METADATA_BYTES = 8 * 1024**2
IMAGE_HOSTS = frozenset({"image.civitai.com", "blobs-b2.civitai.com"})


class ProviderError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.public_message = status, message


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


class Civitai:
    def __init__(self, root, *, opener=None, sleep=time.sleep):
        self.key_file = Path(root) / "civitai-key.json"
        self.lock = threading.RLock()
        self.opener = opener or build_opener(_NoRedirect())
        self.sleep = sleep

    def _key(self):
        try:
            return str(json.loads(self.key_file.read_text()).get("api_key") or "")
        except (ValueError, OSError, AttributeError):
            return ""

    def has_key(self):
        with self.lock:
            return bool(self._key())

    def set_key(self, value):
        if not isinstance(value, str) or len(value) > 512 or re.search(r"[\x00-\x20\x7f]", value):
            if value != "":
                raise ValueError("Civitai API Key 格式无效")
        with self.lock:
            if not value:
                self.key_file.unlink(missing_ok=True)
                return
            self.key_file.parent.mkdir(parents=True, exist_ok=True)
            pending = self.key_file.with_suffix(".pending")
            descriptor = os.open(pending, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w") as stream:
                    json.dump({"api_key": value}, stream)
                os.replace(pending, self.key_file)
            finally:
                pending.unlink(missing_ok=True)

    @staticmethod
    def binding(value):
        if not isinstance(value, str):
            raise ValueError("请粘贴 Civitai 具体版本链接")
        url = urlparse(value.strip())
        if (url.scheme != "https" or url.hostname not in {"civitai.com", "www.civitai.com"}
                or url.username or url.password or url.port not in {None, 443}):
            raise ValueError("须使用 https://civitai.com 的具体版本链接")
        query = parse_qs(url.query)
        version = (query.get("modelVersionId") or [""])[0]
        if not version:
            match = re.fullmatch(r"/api/v1/model-versions/(\d+)/?", url.path)
            version = match[1] if match else ""
        if not version.isdigit() or not 0 < int(version) < 2**53:
            raise ValueError("链接缺少 modelVersionId，请复制具体版本链接而非模型首页")
        return {"provider": "civitai", "version_id": int(version),
                "url": ("https://civitai.com" + url.path + "?modelVersionId=" + str(int(version))),
                "matched_by": "manual"}

    def _request(self, url, *, image=False):
        # Version JSON may contain multi-MB Comfy workflows in image metadata.
        # Only the small normalized fields are retained by lookup().
        limit = MAX_BYTES if image else MAX_METADATA_BYTES
        # original=true images redirect to Civitai's public object storage.
        # Keep checking every hop; API credentials never follow image hosts.
        hosts = IMAGE_HOSTS if image else {"civitai.com", "www.civitai.com"}
        attempts, redirects = 0, 0
        while True:
            parsed = urlparse(url)
            if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password
                    or parsed.port not in {None, 443}):
                raise ProviderError("error", "Civitai 返回了不受支持的预览地址")
            headers = {"User-Agent": "CanvasHub-LoRA/1.0", "Accept": "image/*" if image else "application/json"}
            with self.lock:
                key = self._key()
            if key and not image:
                headers["Authorization"] = "Bearer " + key
            try:
                with self.opener.open(Request(url, headers=headers), timeout=15) as response:
                    length = response.headers.get("Content-Length")
                    if length and int(length) > limit:
                        raise ProviderError("error", "Civitai 资料或示例图超过大小限制")
                    content = response.read(limit + 1)
                    if len(content) > limit:
                        raise ProviderError("error", "Civitai 资料或示例图超过大小限制")
                    return content
            except HTTPError as exc:
                code, location = exc.code, exc.headers.get("Location", "")
                retry_after = exc.headers.get("Retry-After", "2")
                exc.close()
                if code in {301, 302, 303, 307, 308} and location and redirects < 3:
                    url = urljoin(url, location)
                    redirects += 1
                    continue
                if code == 429 and attempts < 2:
                    attempts += 1
                    delay = min(30, max(2, int(retry_after))) if retry_after.isdigit() else 3
                    self.sleep(delay)
                    continue
                if code == 404:
                    raise ProviderError("not_found", "Civitai 未找到此文件版本，可手动填写或绑定版本") from None
                if code in {401, 403}:
                    raise ProviderError("restricted", "Civitai 资料访问受限，可检查连接设置或手动填写") from None
                if code == 429:
                    raise ProviderError("rate_limited", "Civitai 请求受限，请稍后重试") from None
                raise ProviderError("error", "Civitai 服务暂不可用，请稍后重试") from None
            except (URLError, TimeoutError, OSError):
                raise ProviderError("offline", "无法连接 Civitai，已保留本地资料") from None

    def lookup(self, identity, binding):
        suffix = str(binding["version_id"]) if binding.get("version_id") else "by-hash/" + identity
        try:
            value = json.loads(self._request("https://civitai.com/api/v1/model-versions/" + suffix))
            version, model_id = int(value["id"]), int(value["modelId"])
            if version <= 0 or model_id <= 0:
                raise ValueError("invalid id")
            if binding.get("version_id") and version != binding["version_id"]:
                raise ValueError("version mismatch")
            hashes = {str(item.get("hashes", {}).get("SHA256", "")).lower() for item in value.get("files", [])}
            if not binding and identity.lower() not in hashes:
                raise ProviderError("mismatch", "Civitai 返回文件哈希不匹配，未写入资料")
            parser = _PlainText()
            parser.feed(str(value.get("description") or "")[:40000])
            fields = validate_fields({"name": str((value.get("model") or {}).get("name") or value.get("name") or "LoRA")[:1000],
                "version": str(value.get("name") or "")[:1000], "description": "\n".join(parser.parts)[:12000],
                "trigger_words": value.get("trainedWords") or [], "source_name": "Civitai",
                "source_url": f"https://civitai.com/models/{model_id}?modelVersionId={version}"})
            images = [{"url": str(item["url"])} for item in value.get("images", [])
                      if isinstance(item, dict) and item.get("type", "image") == "image" and item.get("url")]
            return {"fields": fields, "images": images[:4], "version_id": version,
                    "matched_by": "manual" if binding else "hash"}
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("error", "Civitai 资料格式异常，已保留本地资料") from None

    def image(self, url):
        return self._request(url, image=True)
