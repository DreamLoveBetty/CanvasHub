"""Model-specific prompt enhancement (PE) for text-to-image prompts.

The caller injects the prompt-model adapter, so the provider choice and the
Codex -> account-pool fallback stay owned by prompt_skill_client. No HTTP,
canvas state or credentials live here.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from ..app_config import BASE_DIR

MAX_SOURCE_CHARS = 8000
MAX_OUTPUT_CHARS = 6000
MAX_TRACE_NODES = 16
LEGACY_NODE_PROFILES = ("moss_caption", "qwen_t2i")
H3_IMAGE_PROFILE = "h3_image_t2i"
PROFILES = (*LEGACY_NODE_PROFILES, H3_IMAGE_PROFILE)
H3_IMAGE_MAX_SOURCE_CHARS = 32000
H3_IMAGE_MAX_OUTPUT_CHARS = 16000
H3_IMAGE_RATIOS = frozenset(("1:1", "5:4", "4:3", "3:2", "16:9", "21:9", "4:5", "3:4", "2:3", "9:16"))
# Increment when the built-in profile files change so saved rewrites can be reviewed again.
RULESET_VERSION = 2
MODEL_OPTIONS = ("provider", "model", "reasoning_effort")

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_LABEL = re.compile(r"^(rewritten prompt|prompt|improved prompt|enhanced prompt|改写后的提示词|提示词|改写结果)\s*[:：]\s*", re.I)


def config_key(config: dict[str, Any]) -> str:
    values = [RULESET_VERSION, *(config.get(name, "") for name in MODEL_OPTIONS)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def normalize_request(body: Any) -> dict[str, str]:
    if not isinstance(body, dict):
        raise ValueError("请求必须是对象")
    unknown = sorted(set(body) - {"text", "profile"})
    if unknown:
        raise ValueError(f"请求包含未知字段：{unknown[0]}")
    profile = body.get("profile")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError("未知 PE 规则")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("缺少要改写的提示词")
    limit = H3_IMAGE_MAX_SOURCE_CHARS if profile == H3_IMAGE_PROFILE else MAX_SOURCE_CHARS
    if len(text.strip() if profile == H3_IMAGE_PROFILE else text) > limit:
        raise ValueError(f"提示词不能超过 {limit} 个字符")
    return {"text": text.strip(), "profile": profile}


def clean_output(raw: Any) -> str:
    """Strip the wrappers chat models add around a plain-text answer; the content itself is kept as is."""
    text = _FENCE.sub("", raw.strip()).strip() if isinstance(raw, str) else ""
    text = _LABEL.sub("", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'" and text.count(text[0]) == 2:
        text = text[1:-1].strip()
    if text.startswith("“") and text.endswith("”") and text.count("“") == 1:
        text = text[1:-1].strip()
    if not text:
        raise ValueError("PE 模型没有返回改写结果")
    if len(text) > MAX_OUTPUT_CHARS:
        raise ValueError("PE 改写结果过长")
    return text


def _parse_h3_output(raw: Any) -> dict[str, str]:
    if not isinstance(raw, str):
        raise ValueError("H3 Image 扩展未返回 JSON")
    result = json.loads(_FENCE.sub("", raw.strip()).strip())
    caption = result.get("expanded_caption") if isinstance(result, dict) else None
    if not isinstance(caption, str) or not caption.strip() or len(caption.strip()) > H3_IMAGE_MAX_OUTPUT_CHARS:
        raise ValueError("H3 Image 扩展未返回可用的描述")
    output = {"prompt": caption.strip()}
    ratio = result.get("aspect_ratio")
    if isinstance(ratio, str) and ratio in H3_IMAGE_RATIOS:
        output["aspect_ratio"] = ratio
    return output


def rewrite(request: dict[str, str], call_model: Callable[..., dict[str, Any]],
            config: dict[str, Any]) -> dict[str, Any]:
    """Compile the selected profile with the configured shared prompt-model adapter."""
    profile = request["profile"]
    system = (BASE_DIR / "prompt_skills" / f"{profile}.md").read_text(encoding="utf-8").strip()
    instruction = ("Expand this still-image brief. Return only the specified JSON object."
                   if profile == H3_IMAGE_PROFILE else "Rewrite this image prompt. Reply with the rewritten prompt only.")
    user_prompt = instruction + "\n\n<<<\n" + request["text"] + "\n>>>"
    options = {name: config.get(name, "") for name in MODEL_OPTIONS}
    reply = call_model(user_prompt, system, options, error_label="PE 改写")
    if profile == H3_IMAGE_PROFILE:
        output = _parse_h3_output(reply.get("text"))
    else:
        prompt = clean_output(reply.get("text"))
        if profile == "qwen_t2i":
            # Only compact line wraps in prose, not characters inside on-image strings.
            parts = re.split(r'("(?:[^"\\]|\\.)*")', prompt, flags=re.S)
            prompt = "".join(part if index % 2 else re.sub(r"[^\S\r\n]*[\r\n]+\s*", " ", part)
                             for index, part in enumerate(parts)).strip()
        output = {"prompt": prompt}
    return {"ok": True, "profile": profile, **output,
            "provider": reply.get("provider", ""), "model": reply.get("model", ""),
            "config_key": config_key(config),
            "latency_seconds": reply.get("latency_seconds", 0)}


def job_trace(body: dict[str, Any], prompt: str, *, text_to_image: bool) -> dict[str, Any]:
    """Validate optional audit data. The generator only consumes the actual prompt, never the trace."""
    if "prompt_pe" not in body:
        return {}
    raw = body["prompt_pe"]
    if not isinstance(raw, list) or len(raw) > MAX_TRACE_NODES:
        raise ValueError("PE 来源记录无效")
    if not raw:
        return {}
    if not text_to_image:
        raise ValueError("PE 提示词改写当前只支持文生图")
    limits = {"node_id": 128, "source_text": MAX_SOURCE_CHARS, "rewritten_prompt": MAX_OUTPUT_CHARS,
              "model": 160, "provider": 80}
    records, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict) or entry.keys() != limits.keys() | {"profile", "edited"}:
            raise ValueError("PE 来源字段无效")
        if any(not isinstance(entry[k], str) or len(entry[k]) > limit for k, limit in limits.items()):
            raise ValueError("PE 来源文本或模型字段无效")
        if (entry["profile"] not in LEGACY_NODE_PROFILES or type(entry["edited"]) is not bool
                or not entry["node_id"].strip() or not entry["source_text"].strip()):
            raise ValueError("PE 来源内容无效")
        rewritten = entry["rewritten_prompt"]
        if not rewritten.strip() or rewritten not in prompt or entry["node_id"] in seen:
            raise ValueError("PE 来源重复或与提交的提示词不一致")
        seen.add(entry["node_id"])
        records.append(dict(entry))
    return {"prompt_pe": records}
