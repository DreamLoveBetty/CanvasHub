#!/usr/bin/env python3
"""
Spell prompt generation client.

Defaults to the project Codex OAuth text route and asks it to return structured
image prompts as JSON. A legacy OpenAI-compatible endpoint can still be used by
explicitly setting SPELL_PROVIDER=openai_compatible or SPELL_API_URL/SPELL_API_KEY.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .app_config import (
    DEFAULT_GPT_IMAGE_MAIN_MODEL,
    DEFAULT_PROMPT_SKILL_PROVIDER,
    GPT_REASONING_EFFORTS,
    get_gpt_provider_config,
    get_prompt_skill_config,
)
from .prompt_skill_client import _call_prompt_provider_with_pool_fallback

DEFAULT_SPELL_PROVIDER = DEFAULT_PROMPT_SKILL_PROVIDER
DEFAULT_SPELL_API_BASE_URL = ""
DEFAULT_SPELL_API_KEY = ""
DEFAULT_SPELL_MODEL_NAME = ""
DEFAULT_OPENAI_COMPATIBLE_SPELL_MODEL_NAME = "qwen3.5-plus"
DEFAULT_SPELL_REASONING_EFFORT = "medium"

SPELL_API_BASE_URL = os.environ.get("SPELL_API_URL", DEFAULT_SPELL_API_BASE_URL).rstrip("/")
SPELL_API_KEY = os.environ.get("SPELL_API_KEY", DEFAULT_SPELL_API_KEY)
SPELL_MODEL_NAME = os.environ.get("SPELL_MODEL_NAME", DEFAULT_SPELL_MODEL_NAME)
SPELL_PROVIDER = os.environ.get("SPELL_PROVIDER", DEFAULT_SPELL_PROVIDER)
SPELL_REASONING_EFFORT = os.environ.get("SPELL_REASONING_EFFORT", DEFAULT_SPELL_REASONING_EFFORT)
SPELL_TIMEOUT_SECONDS = int(os.environ.get("SPELL_TIMEOUT", os.environ.get("CUSTOM_TIMEOUT", "120")))

SPELL_META_PROMPT = """你是一位图像生成模型的提示词工程师，需要根据用户提供的主题，发挥你的想象力，依据模块要求:扩展/优化/补全/挖掘细节，给用户输出一段完整的可用于gemini-3-image-pro模型直接生成图片的提示词。完整提示词需要按6个模块拆解输出细节参数，再在json结构体内输出英文自然语言的正面提示与负面约束提示块。模块要求如下(最终json结构化提示不能包含各模块名称):
1.角色与身体参数模块
2.面部结构参数模块
3.肤质与妆容参数模块
4.姿势与动作参数模块
5.光线与氛围参数模块
6.场景与景深参数模块
以上每一模块，均要以内在的“视觉目标”为起点，将抽象描述映射到若干基础参数类型：
比例类参数：如脸长宽比、上身:下身比例等；
角度类参数：如头部倾斜角、视线角度、光线入射角等；
范围类参数：如妆容覆盖面积、景深范围、光晕扩散半径等；
强度类参数：如饱和度、水光强度、对比度、颗粒感强度等。
输出json结构提示示例(不能复制抄袭，仅作为示范):
{
  "JK女孩地铁肖像主题中文提示词": {
    "整体风格": "真人电影剧照，PF风格，电影级写实人类"
  },
  "角色描述": {
    "身份": "极其精致的东亚女偶像muse级别女子脸部，角色脸部为东亚顶级偶像级精致五官，same face identity, same facial proportions as reference but elevated to muse celebrity-grade beauty standards",
    "身体测量": {
      "身高": "约180cm，几乎碰到车顶（车顶高度约200cm，头部距离车顶约20cm）",
      "体重": "约60kg"
    }
  },
  "面部细节": {
    "面部形状": "精致鹅蛋脸（脸长宽比约1.4:1，颧骨柔和突出高度约1cm，下颌线条流畅优雅V形角度约120度，下巴尖度约30度）",
    "五官各处": {
      "眼睛": "杏仁形大眼睛（眼长约3cm，眼宽约1.2cm，眼距约3.5cm）",
      "鼻子": "高挺鼻梁高度约1.5cm，鼻翼宽度约2.5cm，鼻尖圆润微翘角度约10度",
      "嘴巴": "樱桃小嘴唇宽约4cm，上唇厚度约0.8cm，下唇厚度约1cm"
    }
  },
  "肤质与妆容": {
    "肤色与底妆": "冷白皮与韩系水光肌，皮肤反射率约0.9，底妆无瑕但保留微纹理",
    "妆容": {
      "眉毛": "自然细眉，眉峰柔和弧度约15度",
      "眼影": "浅粉色珠光眼影打底，眼尾中棕晕染",
      "唇部": "镜面淡粉色唇釉，唇中叠涂细闪颗粒"
    }
  },
  "姿势与动作": {
    "整体姿势": "standing leaning against car door, holding phone with both hands at chest level",
    "头部倾斜": "头部微微向下倾斜约10度，颈部前倾角度5度"
  },
  "灯光与氛围": {
    "灯光设置": "cinematic lighting setup, brighter interior car lighting with subtle rim light",
    "颜色分级": "neutral-warm tone, medium contrast with soft shadows and even highlights"
  },
  "背景与景深": {
    "背景": "inside brighter lit car interior with white walls, handrails, seats, advertisements on walls",
    "景深": "shallow depth of field，焦点在角色脸部与上身，背景模糊半径10像素",
    "镜头": "35mm wide angle interior portrait"
  },
  "prompts": {
    "positive_prompt": "English natural language positive prompt here",
    "negative_prompt": "English natural language negative constraints here"
  }
}

请严格遵守以下输出约束：
1. 必须只返回一个合法 JSON 对象，不要输出 markdown、代码块、解释、前后缀。
2. JSON 中必须包含完整中文结构化描述，同时必须包含英文自然语言的 positive_prompt 和 negative_prompt 两个字符串字段。
3. 不能直接复制示例，要根据用户主题重新构造内容。
4. 最终 JSON 内不能出现“角色与身体参数模块”“面部结构参数模块”“肤质与妆容参数模块”“姿势与动作参数模块”“光线与氛围参数模块”“场景与景深参数模块”这些模块名称本身，但内容必须覆盖这些维度。
5. 若用户信息很少，也要合理补完细节，保证能直接用于 gemini-3-image-pro 出图。
6. 英文 positive_prompt 要完整、流畅、可直接用于图像模型；negative_prompt 要聚焦错误 anatomy、畸形、低清晰度、错误光影、脏乱背景、额外肢体、面部崩坏等常见问题。"""


def _strip_code_fences(text):
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _extract_first_json_block(text):
    cleaned = _strip_code_fences(text)
    if not cleaned:
        raise ValueError("模型未返回内容")

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("模型返回中未找到 JSON 对象")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:index + 1]
    raise ValueError("模型返回的 JSON 不完整")


def _walk_values(node, path=None):
    current_path = list(path or [])
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = current_path + [str(key)]
            if isinstance(value, (dict, list)):
                yield from _walk_values(value, next_path)
            else:
                yield next_path, key, value
    elif isinstance(node, list):
        for index, value in enumerate(node):
            next_path = current_path + [str(index)]
            if isinstance(value, (dict, list)):
                yield from _walk_values(value, next_path)
            else:
                yield next_path, str(index), value


def _match_prompt_value(data, preferred_tokens):
    best_value = ""
    best_score = -1
    for path, key, value in _walk_values(data):
        if not isinstance(value, str):
            continue
        key_text = " ".join([*path[:-1], key]).lower()
        score = 0
        for token, weight in preferred_tokens:
            if token in key_text:
                score += weight
        if score <= 0:
            continue
        if score > best_score or (score == best_score and len(value) > len(best_value)):
            best_score = score
            best_value = value.strip()
    return best_value


def _extract_prompt_blocks(data):
    positive = _match_prompt_value(data, [
        ("positive_prompt", 10),
        ("positive", 8),
        ("正向", 8),
        ("正面", 7),
        ("prompt", 2),
    ])
    negative = _match_prompt_value(data, [
        ("negative_prompt", 10),
        ("negative", 8),
        ("constraint", 6),
        ("约束", 7),
        ("负向", 8),
        ("负面", 8),
    ])
    return positive, negative


def _env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _resolve_spell_provider() -> str:
    provider = _env_str("SPELL_PROVIDER")
    if provider:
        normalized = provider.lower().replace("-", "_")
        if normalized in {"codex", "codex_oauth", "gpt_oauth", "local_codex", "managed_codex_oauth"}:
            return DEFAULT_PROMPT_SKILL_PROVIDER
        if normalized in {"openai", "openai_compatible", "dashscope", "legacy", "http"}:
            return "openai_compatible"
        return normalized
    if _env_str("SPELL_API_URL") or _env_str("SPELL_API_BASE_URL") or _env_str("SPELL_API_KEY"):
        return "openai_compatible"
    return DEFAULT_SPELL_PROVIDER


def _spell_timeout_seconds() -> int:
    try:
        return max(5, int(os.environ.get("SPELL_TIMEOUT", os.environ.get("CUSTOM_TIMEOUT", "120"))))
    except (TypeError, ValueError):
        return 120


def _spell_user_prompt(normalized_topic: str) -> str:
    return "\n".join(
        [
            "用户主题如下，请基于该主题输出一个完整的结构化 JSON 提示词。",
            f"用户主题：{normalized_topic}",
            "请只返回合法 JSON 对象。",
        ]
    )


def _codex_spell_model() -> str:
    prompt_cfg = get_prompt_skill_config()
    gpt_cfg = get_gpt_provider_config()
    return (
        _env_str("SPELL_MODEL_NAME")
        or str(prompt_cfg.get("model") or "").strip()
        or str(gpt_cfg.get("image_main_model") or "").strip()
        or DEFAULT_GPT_IMAGE_MAIN_MODEL
    )


def _codex_spell_reasoning_effort() -> str:
    prompt_cfg = get_prompt_skill_config()
    effort = (
        _env_str("SPELL_REASONING_EFFORT")
        or str(prompt_cfg.get("reasoning_effort") or "").strip()
        or DEFAULT_SPELL_REASONING_EFFORT
    ).lower()
    return effort if effort in GPT_REASONING_EFFORTS else DEFAULT_SPELL_REASONING_EFFORT


def _call_codex_spell(user_prompt: str) -> tuple[str, dict[str, Any]]:
    model = _codex_spell_model()
    reasoning_effort = _codex_spell_reasoning_effort()
    raw_text, provider_id, actual_model, actual_reasoning, fallback_warning = _call_prompt_provider_with_pool_fallback(
        DEFAULT_PROMPT_SKILL_PROVIDER,
        user_prompt,
        SPELL_META_PROMPT,
        model,
        reasoning_effort,
        "咒术生成",
    )
    meta = {
        "provider": provider_id,
        "model": actual_model or model,
        "reasoning_effort": actual_reasoning or reasoning_effort,
        "fallback_warning": fallback_warning,
    }
    return raw_text, meta


def _openai_compatible_spell_model() -> str:
    return _env_str("SPELL_MODEL_NAME") or DEFAULT_OPENAI_COMPATIBLE_SPELL_MODEL_NAME


def _openai_compatible_spell_api_base() -> str:
    return (
        _env_str("SPELL_API_URL")
        or _env_str("SPELL_API_BASE_URL")
        or DEFAULT_SPELL_API_BASE_URL
    ).rstrip("/")


def _call_openai_compatible_spell(user_prompt: str) -> tuple[str, dict[str, Any]]:
    api_base = _openai_compatible_spell_api_base()
    if not api_base:
        raise RuntimeError("咒术模型 API URL 未配置，请设置 SPELL_API_URL，或清空旧环境变量以使用 Codex OAuth。")
    api_key = _env_str("SPELL_API_KEY", DEFAULT_SPELL_API_KEY)
    model = _openai_compatible_spell_model()
    request_body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": SPELL_META_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": 0.9,
    }

    request = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_spell_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore") if error.fp else ""
        raise RuntimeError(f"咒术模型请求失败（HTTP {error.code}）：{body[:600] or '无响应内容'}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"咒术模型连接失败：{error.reason}") from error

    raw_text = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    meta = {
        "provider": "openai_compatible",
        "model": model,
        "reasoning_effort": "",
        "fallback_warning": "",
    }
    return str(raw_text or "").strip(), meta


def generate_structured_spell_prompt(topic):
    normalized_topic = str(topic or "").strip()
    if not normalized_topic:
        raise ValueError("缺少主题内容")

    user_prompt = _spell_user_prompt(normalized_topic)
    provider = _resolve_spell_provider()
    if provider == "openai_compatible":
        raw_text, meta = _call_openai_compatible_spell(user_prompt)
    else:
        raw_text, meta = _call_codex_spell(user_prompt)

    if not raw_text:
        raise RuntimeError("咒术模型没有返回可解析内容")

    json_text = _extract_first_json_block(raw_text)
    result = json.loads(json_text)
    positive_prompt, negative_prompt = _extract_prompt_blocks(result)

    return {
        "ok": True,
        "provider": meta.get("provider") or provider,
        "model": meta.get("model") or "",
        "reasoning_effort": meta.get("reasoning_effort") or "",
        "fallback_warning": meta.get("fallback_warning") or "",
        "topic": normalized_topic,
        "result": result,
        "json_text": json.dumps(result, ensure_ascii=False, indent=2),
        "raw_text": raw_text,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }
