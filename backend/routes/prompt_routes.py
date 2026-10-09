"""Prompt configuration, library, analysis, chat and streaming endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_prompt_config(handler, parsed, *, _collect_prompt_skill_runtime_config, urllib):
    """Return prompt-skill settings and runtime model options."""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        provider = query.get("provider", [""])[0] or None
        handler.send_json(_collect_prompt_skill_runtime_config(provider))
    except Exception as e:
        print(f"❌ Prompt Skill 配置读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_models(handler, parsed, *, discover_prompt_models, urllib):
    """Return dynamically discovered text model options for a prompt provider."""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        provider = query.get("provider", [""])[0] or None
        handler.send_json(discover_prompt_models(provider))
    except Exception as e:
        print(f"❌ Prompt Skill 模型读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_style_presets(handler, *, list_style_presets):
    """Return project-local style presets saved by the Prompt Drawer."""
    try:
        handler.send_json({"ok": True, "presets": list_style_presets()})
    except Exception as e:
        print(f"❌ 风格预设读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_versions(handler, parsed, *, _history_page_int, list_prompt_versions, urllib):
    """Return saved prompt versions."""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        limit = _history_page_int(query.get('limit', [200])[0], 200, minimum=1, maximum=1000)
        handler.send_json({"ok": True, "versions": list_prompt_versions(limit=limit)})
    except Exception as e:
        print(f"❌ Prompt versions 读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_color_schemes(handler, *, list_color_schemes):
    """Return active built-in and user-defined color schemes."""
    try:
        handler.send_json({"ok": True, "color_schemes": list_color_schemes()})
    except Exception as e:
        print(f"❌ 色彩方案读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_color_scheme_save(handler, *, ColorSchemeNotFoundError, save_color_scheme):
    """Create or update one user-defined color scheme."""
    try:
        color_scheme = save_color_scheme(handler.read_json_body(max_bytes=2 * 1024 * 1024))
        handler.send_json({"ok": True, "color_scheme": color_scheme})
    except ColorSchemeNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 色彩方案保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_color_scheme_delete(handler, *, ColorSchemeNotFoundError, delete_color_scheme):
    """Soft-delete one user-defined color scheme."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        if not isinstance(data, dict):
            raise ValueError("请求体格式错误")
        color_scheme = delete_color_scheme(data.get('id') or data.get('color_scheme_id'))
        handler.send_json({"ok": True, "color_scheme": color_scheme})
    except ColorSchemeNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 色彩方案删除失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_color_scheme_favorite(handler, *, ColorSchemeNotFoundError, set_color_scheme_favorite):
    """Persist an explicit favorite state for one color scheme."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        if not isinstance(data, dict):
            raise ValueError("请求体格式错误")
        if 'favorite' not in data:
            raise ValueError("缺少 favorite")
        color_scheme = set_color_scheme_favorite(
            data.get('id') or data.get('color_scheme_id'),
            data.get('favorite'),
        )
        handler.send_json({"ok": True, "color_scheme": color_scheme})
    except ColorSchemeNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 色彩方案收藏状态保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_color_schemes_migrate_legacy(handler, *, migrate_legacy_color_schemes):
    """Import color schemes and favorites from the former localStorage keys."""
    try:
        data = handler.read_json_body(max_bytes=4 * 1024 * 1024)
        if not isinstance(data, dict):
            raise ValueError("请求体格式错误")
        result = migrate_legacy_color_schemes(
            data.get('custom_schemes'),
            data.get('favorite_ids'),
        )
        handler.send_json({"ok": True, **result})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 旧版色彩方案迁移失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_blocks_list(handler, parsed, *, _coerce_bool, _history_page_int, list_prompt_blocks, urllib):
    """Return reusable short prompt blocks for slash insertion and editors."""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        result = list_prompt_blocks(
            query=str(query.get('query', [''])[0] or '').strip(),
            module_type=str(query.get('module_type', [''])[0] or '').strip(),
            primary_type=str(query.get('primary_type', [''])[0] or '').strip(),
            favorite=_coerce_bool(query.get('favorite', [False])[0], False),
            limit=_history_page_int(query.get('limit', [500])[0], 500, minimum=1, maximum=1000),
            offset=_history_page_int(query.get('offset', [0])[0], 0, minimum=0, maximum=1000000),
        )
        handler.send_json({"ok": True, **result})
    except Exception as e:
        print(f"❌ 提示词素材块读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_templates_list(handler, *, list_prompt_templates):
    """Return active system and user-defined prompt split rules."""
    try:
        handler.send_json({"ok": True, "templates": list_prompt_templates()})
    except Exception as e:
        print(f"❌ 提示词模板读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_template_save(handler, *, save_prompt_template):
    """Create or update one user-defined prompt split rule."""
    try:
        template = save_prompt_template(handler.read_json_body(max_bytes=2 * 1024 * 1024))
        handler.send_json({"ok": True, "template": template})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 拆分规则保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_template_delete(handler, *, delete_prompt_template):
    """Soft-delete one user-defined prompt split rule."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        template = delete_prompt_template(data.get('id') or data.get('template_id'))
        handler.send_json({"ok": True, "template": template})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 拆分规则删除失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_config_save(
    handler,
    *,
    _collect_prompt_skill_runtime_config,
    _sanitize_prompt_skill_patch,
    json,
    update_app_settings_section,
):
    """Persist non-secret prompt-skill settings into project settings.json."""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')
        patch = _sanitize_prompt_skill_patch(data)
        if not patch:
            handler.send_json({"ok": False, "error": "没有可保存的配置"}, 400)
            return
        update_app_settings_section("prompt_skill", patch)
        handler.send_json(_collect_prompt_skill_runtime_config(patch.get("provider")))
    except Exception as e:
        print(f"❌ Prompt Skill 配置保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_polish(handler, *, _polish_prompt_with_chatgpt_pool_chat, json, polish_prompt):
    """Run the selected prompt skill and return full/compact prompt variants."""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')
        text = str(data.get("text") or data.get("prompt") or "").strip()
        options = {
            "provider": data.get("provider"),
            "skill": data.get("skill"),
            "model": data.get("model"),
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort"),
        }
        try:
            result = polish_prompt(text, options)
        except Exception as exc:
            if not text:
                raise
            print(f"⚠️ Prompt Skill 润色失败，尝试账号池 chat 兜底：{exc}")
            try:
                result = _polish_prompt_with_chatgpt_pool_chat(text, exc)
            except Exception as fallback_exc:
                print(f"⚠️ Prompt Skill 账号池 chat 兜底失败：{fallback_exc}")
                raise exc
        handler.send_json(result)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt Skill 润色失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_style_preset_save(handler, *, save_style_preset):
    """Persist one project-local style preset."""
    try:
        preset = save_style_preset(handler.read_json_body(max_bytes=512 * 1024))
        handler.send_json({"ok": True, "preset": preset})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 风格预设保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_style_preset_extract(handler, *, extract_style_preset):
    """Extract a reusable style preset draft from text-node context."""
    try:
        data = handler.read_json_body(max_bytes=512 * 1024)
        preset = extract_style_preset(
            str(data.get("text") or data.get("prompt") or "").strip(),
            str(data.get("message") or data.get("direction") or "").strip(),
            {
                "candidate": data.get("candidate") or "",
                "history": data.get("history") if isinstance(data.get("history"), list) else [],
                "provider": data.get("provider"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
            },
        )
        handler.send_json({"ok": True, "preset": preset})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 风格预设提取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_version_save(handler, *, save_prompt_version):
    """Persist one prompt candidate/version."""
    try:
        version = save_prompt_version(handler.read_json_body(max_bytes=1024 * 1024))
        handler.send_json({"ok": True, "version": version})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt version 保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_block_save(handler, *, save_prompt_block):
    """Create or update one reusable short prompt block."""
    try:
        block = save_prompt_block(handler.read_json_body(max_bytes=2 * 1024 * 1024))
        handler.send_json({"ok": True, "block": block})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 提示词素材块保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_block_delete(handler, *, delete_prompt_block):
    """Soft-delete one reusable short prompt block."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        block = delete_prompt_block(data.get('id') or data.get('block_id'))
        handler.send_json({"ok": True, "block": block})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except Exception as e:
        print(f"❌ 提示词素材块删除失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_block_use(handler, *, mark_prompt_block_used):
    """Update block usage ranking after slash insertion."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        block = mark_prompt_block_used(data.get('id') or data.get('block_id'))
        handler.send_json({"ok": True, "block": block})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except Exception as e:
        print(f"❌ 提示词素材块使用状态更新失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_library_blocks_extract(
    handler,
    *,
    extract_reusable_prompt_blocks,
    extract_reusable_prompt_blocks_from_image,
    generic_19_prompt_block_split_rule,
    random,
    resolve_prompt_template,
    time,
):
    """Extract editable prompt-block candidates from text or one uploaded image."""
    started_at = time.time()
    request_label = f"split_{int(started_at)}_{random.randint(1000, 9999)}"
    try:
        data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        mode = str(data.get('mode') or 'text').strip().lower()
        primary_type = str(data.get('primary_type') or '').strip()
        rule_id = str(data.get('rule_id') or '').strip()
        module_scope = str(data.get('module_scope') or '').strip().lower()
        if module_scope == 'generic_19':
            split_rule = generic_19_prompt_block_split_rule()
        elif module_scope:
            raise ValueError("不支持的素材块模块范围")
        else:
            split_rule = resolve_prompt_template(rule_id, primary_type)
            if rule_id and not split_rule:
                raise ValueError("拆分规则不存在或已删除")
        if split_rule:
            primary_type = str(split_rule.get('primary_type') or primary_type).strip()
        default_reasoning_effort = (
            "medium"
            if mode == "image" and module_scope == "generic_19"
            else ("medium" if mode == "image" else "low")
        )
        default_model = "gpt-5.6-sol" if mode == "image" and module_scope == "generic_19" else None
        options = {
            "provider": data.get("provider"),
            "model": data.get("model") or default_model,
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or default_reasoning_effort,
        }
        print(
            f"🧩 素材块拆分开始：{request_label} "
            f"mode={mode} scope={module_scope or 'template'} "
            f"model={options.get('model') or 'configured'} effort={options['reasoning_effort']}",
            flush=True,
        )
        if mode == 'image':
            images = data.get('images') if isinstance(data.get('images'), list) else []
            result = extract_reusable_prompt_blocks_from_image(
                str(data.get('message') or data.get('direction') or '').strip(),
                images,
                primary_type,
                options,
                split_rule,
            )
        elif mode == 'text':
            result = extract_reusable_prompt_blocks(
                str(data.get('text') or data.get('prompt') or '').strip(),
                primary_type,
                options,
                split_rule,
            )
        else:
            handler.send_json({"ok": False, "error": "不支持的素材块提取模式"}, 400)
            return
        print(
            f"✅ 素材块拆分完成：{request_label} "
            f"elapsed={time.time() - started_at:.2f}s provider={result.get('provider') or '-'} "
            f"model={result.get('model') or '-'} blocks={len(result.get('blocks') or [])}",
            flush=True,
        )
        handler.send_json(result)
    except ValueError as e:
        print(f"❌ 素材块拆分失败：{request_label} elapsed={time.time() - started_at:.2f}s error={e}", flush=True)
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 提示词素材块提取失败：{request_label} elapsed={time.time() - started_at:.2f}s error={e}", flush=True)
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_assistant_chat(handler, *, assistant_chat):
    """Lightweight text-node Prompt Copilot discussion endpoint."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        text = str(data.get("text") or data.get("prompt") or "").strip()
        message = str(data.get("message") or "").strip()
        result = assistant_chat(text, message, {
            "images": data.get("images", []),
            "videos": data.get("videos", []),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            "history": data.get("history") if isinstance(data.get("history"), list) else [],
            "task_context": data.get("task_context") if isinstance(data.get("task_context"), dict) else {},
        })
        handler.send_json({
            **result,
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            "candidates": [],
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt Assistant Chat 失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_assistant_chat_stream(handler, *, assistant_chat_stream):
    """Stream text-node Prompt Copilot discussion deltas."""
    stream_started = False
    try:
        data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        text = str(data.get("text") or data.get("prompt") or "").strip()
        message = str(data.get("message") or "").strip()
        if not text and not message:
            handler.send_json({"ok": False, "error": "请输入聊天内容或选择文本节点"}, 400)
            return
        options = {
            "images": data.get("images", []),
            "videos": data.get("videos", []),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            "history": data.get("history") if isinstance(data.get("history"), list) else [],
            "task_context": data.get("task_context") if isinstance(data.get("task_context"), dict) else {},
        }
        handler._start_ndjson_response()
        stream_started = True
        for event in assistant_chat_stream(text, message, options):
            if event.get("type") == "done":
                event = {
                    **event,
                    "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                    "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                    "candidates": [],
                }
            handler._write_ndjson_event(event)
    except (BrokenPipeError, ConnectionResetError):
        return
    except Exception as e:
        print(f"❌ Prompt Assistant Chat 流式失败：{e}")
        try:
            if stream_started:
                handler._write_ndjson_event({"type": "error", "ok": False, "error": str(e)})
            else:
                handler.send_json({"ok": False, "error": str(e)}, 400 if isinstance(e, ValueError) else 500)
        except Exception:
            pass


def handle_prompt_safe_rewrite(handler, *, random, safe_rewrite_prompt, time):
    """Rewrite one text-node prompt through the standalone safety adapter."""
    try:
        data = handler.read_json_body(max_bytes=512 * 1024)
        prompt = str(data.get("prompt") or data.get("text") or "").strip()
        if not prompt:
            handler.send_json({"ok": False, "error": "缺少要安全改写的提示词"}, 400)
            return
        result = safe_rewrite_prompt(prompt, {
            "provider": data.get("provider"),
            "model": data.get("model"),
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
        })
        zh_prompt = str(result.get("zh_prompt") or result.get("rewritten_prompt") or "").strip()
        en_prompt = str(result.get("en_prompt") or "").strip()
        now = int(time.time())
        base_candidate = {
            "kind": "safe_rewrite",
            "badge": "安全",
            "task_type": result.get("task_type"),
            "intent": result.get("intent") if isinstance(result.get("intent"), dict) else {},
            "risk_score": result.get("risk_score"),
            "risk_level": result.get("risk_level"),
            "risk_flags": result.get("risk_flags") if isinstance(result.get("risk_flags"), list) else [],
            "changed_terms": result.get("changed_terms") if isinstance(result.get("changed_terms"), list) else [],
            "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
            "adapter": result.get("adapter") if isinstance(result.get("adapter"), dict) else {},
            "created_at": now,
        }
        candidates = []
        if zh_prompt:
            candidates.append({
                **base_candidate,
                "id": f"safe_rewrite_zh_{now}_{random.randint(1000, 9999)}",
                "kind": "safe_rewrite_zh",
                "label": "安全审核版（中文）",
                "text": zh_prompt,
                "language": "zh",
            })
        if en_prompt:
            candidates.append({
                **base_candidate,
                "id": f"safe_rewrite_en_{now}_{random.randint(1000, 9999)}",
                "kind": "safe_rewrite_en",
                "label": "安全审核版（英文）",
                "text": en_prompt,
                "language": "en",
            })
        if not candidates:
            raise RuntimeError("安全审核版没有返回有效提示词")
        handler.send_json({
            **result,
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            "candidate": candidates[0],
            "candidates": candidates,
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt Safe Rewrite 失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_image_analysis(handler, *, analyze_prompt_image):
    """Analyze image references into prompt candidates and structured modules."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        images = data.get("images") if isinstance(data.get("images"), list) else []
        message = str(data.get("message") or data.get("direction") or "").strip()
        if not images:
            handler.send_json({"ok": False, "error": "请先上传或选择要分析的图片"}, 400)
            return
        result = analyze_prompt_image(message, images, {
            "provider": data.get("provider"),
            "model": data.get("model"),
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "medium",
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "keep_text": bool(data.get("keep_text") or data.get("keepText")),
        })
        handler.send_json({
            **result,
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt 图片分析失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_video_analysis(handler, *, analyze_prompt_video):
    """Analyze browser-sampled video references into prompt-ready modules."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        videos = data.get("videos") if isinstance(data.get("videos"), list) else []
        images = data.get("images") if isinstance(data.get("images"), list) else []
        message = str(data.get("message") or data.get("direction") or "").strip()
        if not videos:
            handler.send_json({"ok": False, "error": "请先用 @ 选择要分析的视频"}, 400)
            return
        result = analyze_prompt_video(message, videos, {
            "provider": data.get("provider"),
            "model": data.get("model"),
            "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "medium",
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "keep_text": bool(data.get("keep_text") or data.get("keepText")),
        }, images=images)
        handler.send_json({
            **result,
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "style": data.get("style") if isinstance(data.get("style"), dict) else {},
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt 视频分析失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_versions_generate(handler, *, _prompt_version_candidates, polish_prompt, random, time):
    """Generate formal prompt candidates for the text-node assistant."""
    try:
        data = handler.read_json_body(max_bytes=512 * 1024)
        prompt = str(data.get("prompt") or data.get("text") or "").strip()
        message = str(data.get("message") or data.get("direction") or "").strip()
        style = data.get("style") if isinstance(data.get("style"), dict) else {}
        if not prompt and not message:
            handler.send_json({"ok": False, "error": "请输入文本节点内容或生成方向"}, 400)
            return

        base = prompt or message
        instruction = "\n".join(part for part in [
            f"用户确认方向：{message}" if message else "",
            f"文本节点内容：{prompt}" if prompt else "",
            f"风格预设：{style.get('title') or style.get('name') or ''} {style.get('promptTemplate') or style.get('prompt_style') or ''}".strip() if style else "",
        ] if part).strip()
        polish_error = ""
        polished = {}
        try:
            polished = polish_prompt(instruction or base, {
                "provider": data.get("provider"),
                "skill": data.get("skill"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort"),
            })
        except Exception as e:
            polish_error = str(e)
            print(f"⚠️ Prompt 版本生成润色降级：{polish_error}")

        candidates = _prompt_version_candidates(base, message=message, style=style, polished=polished)
        handler.send_json({
            "ok": True,
            "session_id": str(data.get("session_id") or f"prompt_versions_{int(time.time())}_{random.randint(1000, 9999)}"),
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "style": style,
            "candidates": candidates,
            "warning": polish_error,
            "model": polished.get("model"),
            "provider": polished.get("provider"),
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt 版本生成失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_prompt_chat(handler, *, _prompt_version_candidates, polish_prompt, random, time):
    """Return prompt candidates for the desktop Prompt Chat Drawer."""
    try:
        data = handler.read_json_body(max_bytes=512 * 1024)
        prompt = str(data.get("prompt") or data.get("text") or "").strip()
        message = str(data.get("message") or "").strip()
        style = data.get("style") if isinstance(data.get("style"), dict) else {}
        if not prompt and not message:
            handler.send_json({"ok": False, "error": "请输入提示词或改写需求"}, 400)
            return

        base = prompt or message
        instruction = "\n".join(part for part in [
            f"用户需求：{message}" if message else "",
            f"原始提示词：{prompt}" if prompt else "",
            f"风格预设：{style.get('title') or style.get('name') or ''} {style.get('promptTemplate') or style.get('prompt_style') or ''}".strip() if style else "",
        ] if part).strip()
        polish_error = ""
        polished = {}
        try:
            polished = polish_prompt(instruction or base, {
                "provider": data.get("provider"),
                "skill": data.get("skill"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort"),
            })
        except Exception as e:
            polish_error = str(e)
            print(f"⚠️ Prompt Chat 润色降级：{polish_error}")

        candidates = _prompt_version_candidates(base, message=message, style=style, polished=polished)

        handler.send_json({
            "ok": True,
            "session_id": str(data.get("session_id") or f"prompt_chat_{int(time.time())}_{random.randint(1000, 9999)}"),
            "message": message,
            "target": data.get("target") if isinstance(data.get("target"), dict) else {},
            "style": style,
            "candidates": candidates[:5],
            "warning": polish_error,
            "model": polished.get("model"),
            "provider": polished.get("provider"),
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Prompt Chat 失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_spell_generate_prompt(handler, *, generate_structured_spell_prompt, json):
    """处理咒术模块的结构化提示词生成请求"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')

        topic = str(data.get('topic') or data.get('prompt') or '').strip()
        if not topic:
            handler.send_json({"error": "Topic is required"}, 400)
            return

        result = generate_structured_spell_prompt(topic)
        handler.send_json(result)
    except ValueError as e:
        handler.send_json({"error": str(e)}, 400)
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)
