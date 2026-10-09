"""Prompt fidelity, pool-chat polishing and search enrichment.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _prepare_chatgpt_pool_generation_prompt(
    task_id,
    prompt,
    prompt_mode,
    *,
    _coerce_prompt_mode,
    _is_generic_19_fidelity_prompt,
    _prepare_chatgpt_pool_generation_prompt_with_chat,
    get_prompt_skill_config,
    polish_prompt,
    update_task_status,
):
    """Use the configured prompt skill before Web-conversation image generation."""
    raw_prompt = str(prompt or '')
    if _is_generic_19_fidelity_prompt(raw_prompt):
        return raw_prompt, {
            'prompt_fidelity_locked': True,
            'prompt_optimized': False,
            'prompt_optimized_by': 'generic_19_fidelity_bundle',
        }
    if _coerce_prompt_mode(prompt_mode) != 'smart':
        return raw_prompt, {}
    try:
        update_task_status(task_id, 'processing', '正在调用提示词润色模型...', stage='polishing_prompt')
        result = polish_prompt(str(prompt or ''), {})
        cfg = get_prompt_skill_config()
        preferred_key = str(cfg.get('default_output') or 'full_prompt')
        optimized = str(result.get(preferred_key) or result.get('full_prompt') or result.get('compact_prompt') or '').strip()
        if not optimized:
            return str(prompt or ''), {'prompt_polish_error': '润色结果为空'}
        return optimized, {
            'prompt_optimized': True,
            'prompt_optimized_by': 'prompt_skill',
            'prompt_skill_provider': result.get('provider'),
            'prompt_skill_model': result.get('model'),
            'prompt_skill': result.get('skill'),
            'prompt_skill_output': preferred_key,
            'prompt_skill_latency_seconds': result.get('latency_seconds'),
            'original_prompt': str(prompt or ''),
            'optimized_prompt': optimized,
        }
    except Exception as exc:
        error = str(exc)
        print(f"⚠️ ChatGPT 账号池本地提示词润色失败，尝试账号池 chat 兜底：{error}")
        return _prepare_chatgpt_pool_generation_prompt_with_chat(task_id, prompt, error)


def _extract_json_object_from_text(text, *, json, re):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.IGNORECASE | re.MULTILINE)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象")
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
                return json.loads(cleaned[start:index + 1])
    raise ValueError("模型返回的 JSON 不完整")


def _chatgpt_pool_chat_content(result):
    payload = result.get("result") if isinstance(result, dict) else {}
    choices = payload.get("choices") if isinstance(payload, dict) else []
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    return str(message.get("content") or "").strip(), payload


def _prompt_polish_chat_messages(original):
    system_prompt = (
        "你是图像生成提示词优化助手。只做提示词润色和结构整理，不要联网检索，不要研究资料。"
        "请把用户文本改写为图像模型可直接使用的成片提示词，保留用户语义，不新增无根据的主体。"
        "只返回合法 JSON 对象，不要 markdown，不要解释。JSON 字段必须包含 full_prompt、compact_prompt、warnings。"
    )
    user_prompt = "\n".join([
        "请优化下面的图像提示词。",
        "要求：",
        "- full_prompt 是较完整的成片提示词，包含主体、场景、构图、光影、材质/媒介、负面约束。",
        "- compact_prompt 是更短的可投喂版本。",
        "- warnings 是字符串数组，可为空。",
        "",
        "原始提示词：",
        "<<<",
        original,
        ">>>",
    ])
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _polish_prompt_with_chatgpt_pool_chat(
    prompt,
    polish_error,
    *,
    _chatgpt_pool_chat_content,
    _extract_json_object_from_text,
    _prompt_polish_chat_messages,
    chat_chatgpt_pool,
    time,
):
    original = str(prompt or '').strip()
    if not original:
        raise ValueError("缺少要润色的文本")
    started = time.time()
    result = chat_chatgpt_pool(
        _prompt_polish_chat_messages(original),
        model="auto",
        timeout_seconds=180,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "账号池 chat 失败")
    content, payload = _chatgpt_pool_chat_content(result)
    data = _extract_json_object_from_text(content)
    full_prompt = str(data.get('full_prompt') or data.get('完整提示词') or '').strip()
    compact_prompt = str(data.get('compact_prompt') or data.get('精简提示词') or data.get('精简可投喂版') or '').strip()
    if not full_prompt and compact_prompt:
        full_prompt = compact_prompt
    if not compact_prompt and full_prompt:
        compact_prompt = full_prompt
    if not full_prompt:
        raise RuntimeError("账号池 chat 润色结果为空")
    warnings = data.get('warnings') if isinstance(data.get('warnings'), list) else []
    modules = data.get('modules') if isinstance(data.get('modules'), list) else []
    return {
        'ok': True,
        'full_prompt': full_prompt,
        'compact_prompt': compact_prompt,
        'modules': modules,
        'warnings': warnings,
        'router_summary': str(data.get('router_summary') or '').strip(),
        'original_text': original,
        'provider': 'chatgpt_pool',
        'model': payload.get('model') if isinstance(payload, dict) else 'auto',
        'skill': 'chat_fallback',
        'reasoning_effort': '',
        'expanded': False,
        'latency_seconds': round(time.time() - started, 2),
        'fallback': 'chatgpt_pool_chat',
        'prompt_polish_fallback': 'chatgpt_pool_chat',
        'prompt_polish_error': str(polish_error)[:300],
    }


def _prepare_chatgpt_pool_generation_prompt_with_chat(
    task_id,
    prompt,
    polish_error,
    *,
    _polish_prompt_with_chatgpt_pool_chat,
    get_prompt_skill_config,
    update_task_status,
):
    update_task_status(task_id, 'processing', '本地润色失败，正在用账号池 chat 兜底润色...', stage='polishing_prompt')
    original = str(prompt or '').strip()
    if not original:
        return str(prompt or ''), {'prompt_polish_error': str(polish_error)[:300]}
    try:
        result = _polish_prompt_with_chatgpt_pool_chat(original, polish_error)
        cfg = get_prompt_skill_config()
        preferred_key = str(cfg.get('default_output') or 'full_prompt')
        optimized = str(result.get(preferred_key) or result.get('full_prompt') or result.get('compact_prompt') or '').strip()
        if not optimized:
            raise RuntimeError("账号池 chat 润色结果为空")
        return optimized, {
            'prompt_optimized': True,
            'prompt_optimized_by': 'chatgpt_pool_chat',
            'prompt_skill_provider': 'chatgpt_pool',
            'prompt_skill_model': result.get('model') or 'auto',
            'prompt_skill': 'chat_fallback',
            'prompt_skill_output': preferred_key,
            'prompt_polish_fallback': 'chatgpt_pool_chat',
            'prompt_polish_error': str(polish_error)[:300],
            'original_prompt': original,
            'optimized_prompt': optimized,
        }
    except Exception as exc:
        chat_error = str(exc)
        print(f"⚠️ ChatGPT 账号池 chat 润色兜底失败，改用原 prompt：{chat_error}")
        return str(prompt or ''), {
            'prompt_polish_error': str(polish_error)[:300],
            'prompt_pool_chat_error': chat_error[:300],
        }


def _source_summary_list(sources, limit=5):
    items = []
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            continue
        url = str(source.get('url') or '').strip()
        title = str(source.get('title') or '').strip()
        snippet = str(source.get('snippet') or '').strip()
        if not url and not title and not snippet:
            continue
        items.append({'title': title, 'url': url, 'snippet': snippet[:240], 'source_type': str(source.get('source_type') or '').strip()})
        if len(items) >= limit:
            break
    return items


def _prepare_web_search_generation_prompt(
    task_id,
    prompt,
    *,
    _append_task_route_trace,
    _chatgpt_pool_chat_content,
    _extract_json_object_from_text,
    _source_summary_list,
    chat_chatgpt_pool,
    get_prompt_skill_config,
    json,
    search_chatgpt_pool,
    update_task_status,
):
    original = str(prompt or '').strip()
    if not original:
        return str(prompt or ''), {'web_search_error': 'prompt is empty'}
    update_task_status(task_id, 'processing', '正在联网检索并整理提示词...', stage='web_search_prompt')
    _append_task_route_trace(task_id, 'chatgpt_pool_search', 'started', '正在执行联网检索')
    query = "\n".join([
        "围绕下面的图像生成需求做联网检索或研究。",
        "目标是提取可用于图像创作的真实事实、视觉细节、时代/地点/物体特征、风格参考和注意事项。",
        "不要直接生成图片提示词，先给出检索结论和来源。",
        "",
        "图像生成需求：",
        "<<<",
        original,
        ">>>",
    ])
    search_response = search_chatgpt_pool(query, timeout_seconds=300)
    if not search_response.get('ok'):
        error = str(search_response.get('error') or '账号池联网检索失败')
        _append_task_route_trace(task_id, 'chatgpt_pool_search', 'failed', error)
        raise RuntimeError(f"联网检索失败：{error}")
    search_result = search_response.get('result') if isinstance(search_response.get('result'), dict) else {}
    answer = str(search_result.get('answer') or '').strip()
    sources = _source_summary_list(search_result.get('sources') or [])
    if not answer:
        raise RuntimeError("联网检索没有返回可用正文")
    _append_task_route_trace(
        task_id,
        'chatgpt_pool_search',
        'succeeded',
        '联网检索完成',
        conversation_id=str(search_result.get('conversation_id') or ''),
        source_count=len(sources),
    )
    update_task_status(task_id, 'processing', '正在将检索结果整理为图像提示词...', stage='web_search_prompt')
    system_prompt = (
        "你是图像生成提示词整理助手。你会收到用户原始需求、联网检索结论和来源。"
        "请把这些材料整理成图像模型可直接使用的提示词。"
        "只使用检索材料中有依据的信息，不编造事实；来源只用于理解，不要在提示词里写 URL。"
        "只返回合法 JSON 对象，不要 markdown，不要解释。JSON 字段必须包含 full_prompt、compact_prompt、warnings。"
    )
    user_prompt = "\n".join([
        "用户原始需求：",
        "<<<",
        original,
        ">>>",
        "",
        "联网检索结论：",
        "<<<",
        answer,
        ">>>",
        "",
        "来源摘要：",
        json.dumps(sources, ensure_ascii=False),
        "",
        "请输出：",
        "- full_prompt：融合检索结论的完整图像提示词。",
        "- compact_prompt：更短的可投喂版本。",
        "- warnings：不确定、冲突或不适合直接视觉化的点。",
    ])
    chat_response = chat_chatgpt_pool(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model="auto",
        timeout_seconds=180,
    )
    if not chat_response.get('ok'):
        raise RuntimeError(f"检索结果整理失败：{chat_response.get('error') or '账号池 chat 失败'}")
    content, payload = _chatgpt_pool_chat_content(chat_response)
    data = _extract_json_object_from_text(content)
    full_prompt = str(data.get('full_prompt') or data.get('完整提示词') or '').strip()
    compact_prompt = str(data.get('compact_prompt') or data.get('精简提示词') or data.get('精简可投喂版') or '').strip()
    cfg = get_prompt_skill_config()
    preferred_key = str(cfg.get('default_output') or 'full_prompt')
    optimized = str(data.get(preferred_key) or full_prompt or compact_prompt).strip()
    if not optimized:
        raise RuntimeError("检索结果整理为空")
    return optimized, {
        'prompt_optimized': True,
        'prompt_optimized_by': 'chatgpt_pool_search',
        'prompt_skill_provider': 'chatgpt_pool',
        'prompt_skill_model': payload.get('model') if isinstance(payload, dict) else 'auto',
        'prompt_skill': 'web_search_prompt',
        'prompt_skill_output': preferred_key,
        'original_prompt': original,
        'optimized_prompt': optimized,
        'web_search_answer': answer[:4000],
        'web_search_sources': sources,
        'web_search_conversation_id': str(search_result.get('conversation_id') or ''),
        'web_search_model': search_response.get('model'),
    }
