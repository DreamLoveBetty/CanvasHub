"""Versioned local prompt presets and candidate generation.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _prompt_chat_english_feed(text):
    text = str(text or '').strip()
    if not text:
        return ''
    return (
        "Image prompt in English: "
        f"{text}\n\n"
        "Keep the subject, composition, atmosphere, lighting, materials, and camera details explicit. "
        "Avoid vague decorative wording."
    )


def _prompt_chat_style_enhanced(text, style):
    text = str(text or '').strip()
    if not text:
        return ''
    style = style if isinstance(style, dict) else {}
    style_text = str(style.get('promptTemplate') or style.get('prompt_style') or style.get('description') or '').strip()
    title = str(style.get('title') or style.get('name') or '').strip()
    if style_text:
        return f"{text}\n\n风格增强：{style_text}"
    if title:
        return f"{text}\n\n风格增强：保持「{title}」的视觉语言，强化构图、光影、材质和情绪一致性。"
    return f"{text}\n\n风格增强：强化画面主体、构图层次、光影方向、材质细节和整体情绪，保持可执行的图像生成描述。"


def _prompt_version_candidates(
    base,
    message='',
    style=None,
    polished=None,
    *,
    _prompt_chat_english_feed,
    _prompt_chat_style_enhanced,
    _short_text,
    time,
):
    """Build formal prompt candidates for the text-node assistant, excluding Original."""
    base = str(base or "").strip()
    message = str(message or "").strip()
    style = style if isinstance(style, dict) else {}
    polished = polished if isinstance(polished, dict) else {}
    candidates = []

    def add_candidate(kind, label, text, badge=""):
        text = str(text or "").strip()
        if not text:
            return
        if kind == "original":
            return
        if text == base and kind in {"compact", "polished"}:
            return
        if any(item["text"] == text for item in candidates):
            return
        candidates.append({
            "id": f"{kind}_{len(candidates) + 1}",
            "kind": kind,
            "label": label,
            "badge": badge,
            "text": text,
            "created_at": int(time.time()),
        })

    full_prompt = polished.get("full_prompt") or polished.get("fullPrompt") or ""
    compact_prompt = polished.get("compact_prompt") or polished.get("compactPrompt") or ""
    generation_base = full_prompt or base
    add_candidate("polished", "完整成片版", full_prompt, "完整")
    add_candidate("compact", "精简投喂版", compact_prompt or _short_text(base, 260), "精简")
    add_candidate("english_feed", "英文投喂版", _prompt_chat_english_feed(generation_base), "英文")
    add_candidate("style_enhanced", "风格增强版", _prompt_chat_style_enhanced(generation_base, style), "风格")
    if message:
        direction_text = "\n\n".join(part for part in [
            generation_base,
            f"方向聚焦：{message}。请围绕这个方向强化主体、构图、光影、材质和避免跑偏的约束。"
        ] if part)
        add_candidate("custom_direction", "自定义方向版", direction_text, "方向")
    return candidates[:5]


def _read_versioned_json(path, root_key, *, json):
    try:
        if not path.exists():
            return {"version": 1, root_key: []}
        data = json.loads(path.read_text(encoding='utf-8') or '{}')
        if not isinstance(data, dict):
            return {"version": 1, root_key: []}
        items = data.get(root_key)
        if not isinstance(items, list):
            data[root_key] = []
        data.setdefault("version", 1)
        return data
    except Exception:
        return {"version": 1, root_key: []}


def _write_versioned_json(path, root_key, items, *, PROMPT_DATA_DIR, json):
    PROMPT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, root_key: items}
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return payload


def list_style_presets(*, STYLE_PRESETS_FILE, _read_versioned_json):
    return _read_versioned_json(STYLE_PRESETS_FILE, "presets").get("presets", [])


def save_style_preset(data, *, STYLE_PRESETS_FILE, _write_versioned_json, list_style_presets, random, time):
    name = str(data.get("name") or data.get("title") or "").strip()[:48]
    prompt_style = str(data.get("prompt_style") or data.get("promptTemplate") or data.get("text") or "").strip()
    if not name:
        raise ValueError("风格名称不能为空")
    if not prompt_style:
        raise ValueError("风格内容不能为空")
    now = int(time.time())
    preset_id = str(data.get("id") or f"style_{now}_{random.randint(1000, 9999)}").strip()
    presets = [item for item in list_style_presets() if item.get("id") != preset_id]
    preset = {
        "id": preset_id,
        "name": name,
        "title": name,
        "description": str(data.get("description") or "").strip()[:500],
        "positive_style": str(data.get("positive_style") or prompt_style).strip(),
        "avoid": str(data.get("avoid") or "").strip()[:1000],
        "best_for": str(data.get("best_for") or "").strip()[:500],
        "prompt_style": prompt_style,
        "promptTemplate": prompt_style,
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
        "created_at": int(data.get("created_at") or now),
        "updated_at": now,
        "source": str(data.get("source") or "prompt_drawer"),
    }
    presets.append(preset)
    _write_versioned_json(STYLE_PRESETS_FILE, "presets", presets[-200:])
    return preset


def list_prompt_versions(limit=200, *, PROMPT_VERSIONS_FILE, _read_versioned_json):
    versions = _read_versioned_json(PROMPT_VERSIONS_FILE, "versions").get("versions", [])
    return sorted(versions, key=lambda item: int(item.get("created_at") or 0), reverse=True)[:limit]


def save_prompt_version(data, *, PROMPT_VERSIONS_FILE, _read_versioned_json, _write_versioned_json, random, time):
    text = str(data.get("text") or "").strip()
    if not text:
        raise ValueError("提示词版本内容不能为空")
    now = int(time.time())
    version = {
        "id": str(data.get("id") or f"prompt_version_{now}_{random.randint(1000, 9999)}"),
        "type": str(data.get("type") or data.get("kind") or "custom"),
        "label": str(data.get("label") or data.get("type") or "Prompt Version")[:80],
        "text": text,
        "source_message": str(data.get("source_message") or data.get("message") or "")[:1000],
        "target": data.get("target") if isinstance(data.get("target"), dict) else {},
        "style": data.get("style") if isinstance(data.get("style"), dict) else {},
        "created_at": int(data.get("created_at") or now),
    }
    for key in ("language", "task_type", "intent", "risk_score", "risk_level", "risk_flags", "changed_terms", "warnings", "adapter"):
        value = data.get(key)
        if key in {"risk_flags", "changed_terms", "warnings"} and isinstance(value, list):
            version[key] = value
        elif key in {"task_type", "intent", "adapter"} and isinstance(value, dict):
            version[key] = value
        elif key in {"language", "risk_score", "risk_level"} and value not in (None, ""):
            version[key] = value
    versions = _read_versioned_json(PROMPT_VERSIONS_FILE, "versions").get("versions", [])
    versions.append(version)
    _write_versioned_json(PROMPT_VERSIONS_FILE, "versions", versions[-1000:])
    return version
