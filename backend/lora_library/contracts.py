"""Validated descriptive fields; shared by local and remote metadata adapters."""
import math
from urllib.parse import urlparse

FIELDS = {"name", "version", "description", "trigger_words", "trigger_status", "tags",
          "favorite", "hidden", "recommended_scale", "source_url", "source_name",
          "cover_id", "preview_order"}


def validate_fields(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError("资料字段无效")
    result = {}
    for key, item in value.items():
        if key in {"trigger_words", "tags", "preview_order"}:
            maximum = 24 if key == "preview_order" else 64
            if not isinstance(item, list) or len(item) > maximum or any(
                    not isinstance(word, str) or len(word) > 500 for word in item):
                raise ValueError("标签／触发词格式无效或过长")
            result[key] = list(dict.fromkeys(word.strip() for word in item if word.strip()))
        elif key in {"favorite", "hidden"}:
            if not isinstance(item, bool):
                raise ValueError("收藏／隐藏须为布尔值")
            result[key] = item
        elif key == "recommended_scale":
            if item is not None and (isinstance(item, bool) or not isinstance(item, (int, float))
                                     or not math.isfinite(item) or not 0 <= item <= 2):
                raise ValueError("推荐强度须在 0–2 之间")
            result[key] = item
        else:
            if not isinstance(item, str) or len(item) > (12000 if key == "description" else 1000):
                raise ValueError("资料文本无效或过长")
            result[key] = item.strip()
    if "trigger_status" in result and result["trigger_status"] not in {"unknown", "provided", "none"}:
        raise ValueError("触发词状态无效")
    if "source_url" in result and result["source_url"]:
        url = urlparse(result["source_url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("来源链接须为 HTTP(S) 地址")
    if "trigger_words" in result and "trigger_status" not in result:
        result["trigger_status"] = "provided" if result["trigger_words"] else "unknown"
    if result.get("trigger_status") in {"none", "unknown"}:
        result["trigger_words"] = []
    if result.get("trigger_status") == "provided" and not result.get("trigger_words"):
        raise ValueError("请填写触发词，或选择未填写／不需要")
    return result


