"""Agent run lifecycle and desktop workflow-file adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_agent_runs(handler, parsed, *, get_agent_runtime, urllib):
    """List persisted Agent runs without exposing server configuration."""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        limit = int(query.get('limit', [20])[0])
        offset = int(query.get('offset', [0])[0])
        status = str(query.get('status', [''])[0] or '').strip()
        handler.send_json(get_agent_runtime().list_runs(limit=limit, offset=offset, status=status))
    except Exception as error:
        handler._send_agent_error(error)


def handle_agent_run_get(handler, parsed, *, get_agent_runtime, urllib):
    """Return one run plus incremental audit events."""
    try:
        parts = handler._agent_run_route_parts(parsed)
        if len(parts) != 4 or parts[:3] != ['api', 'agent', 'runs'] or not parts[3]:
            handler.send_json({"ok": False, "error": "Agent 运行路径不存在"}, 404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        events_since = int(query.get('events_since', query.get('since', [0]))[0])
        event_limit = int(query.get('event_limit', query.get('limit', [240]))[0])
        handler.send_json(get_agent_runtime().get_run(
            parts[3],
            events_since=events_since,
            event_limit=event_limit,
        ))
    except Exception as error:
        handler._send_agent_error(error)


def handle_agent_run_post(handler, parsed, *, get_agent_runtime):
    """Create or control a supervised Agent run."""
    try:
        parts = handler._agent_run_route_parts(parsed)
        if parts == ['api', 'agent', 'runs']:
            payload = handler.read_json_body(max_bytes=64 * 1024 * 1024)
            handler.send_json(get_agent_runtime().create_run(payload), 201)
            return
        if len(parts) < 5 or parts[:3] != ['api', 'agent', 'runs'] or not parts[3]:
            handler.send_json({"ok": False, "error": "Agent 操作路径不存在"}, 404)
            return

        run_id = parts[3]
        action = parts[4]
        payload = handler.read_json_body(max_bytes=2 * 1024 * 1024)
        runtime = get_agent_runtime()
        if len(parts) == 5 and action == 'approve':
            approval = payload.get('approval') if isinstance(payload.get('approval'), dict) else payload
            handler.send_json(runtime.approve_run(run_id, approval))
            return
        if len(parts) == 5 and action == 'revise':
            instruction = str(payload.get('instruction') or payload.get('message') or '').strip()
            handler.send_json(runtime.revise_run(run_id, instruction))
            return
        if len(parts) == 5 and action == 'pause':
            handler.send_json(runtime.pause_run(run_id))
            return
        if len(parts) == 5 and action == 'resume':
            handler.send_json(runtime.resume_run(run_id))
            return
        if len(parts) == 5 and action == 'cancel':
            handler.send_json(runtime.cancel_run(run_id))
            return
        if len(parts) == 5 and action == 'rollback':
            handler.send_json(runtime.request_rollback(run_id))
            return
        if len(parts) == 6 and action == 'actions' and parts[5]:
            error = str(payload.get('error') or '').strip()
            if payload.get('ok') is False and not error:
                error = '桌面动作执行失败'
            result = payload.get('result') if isinstance(payload.get('result'), dict) else {}
            handler.send_json(runtime.submit_action_result(
                run_id,
                parts[5],
                result=result,
                error=error,
            ))
            return
        handler.send_json({"ok": False, "error": "Agent 操作不存在"}, 404)
    except Exception as error:
        handler._send_agent_error(error)


def _agent_run_route_parts(handler, parsed, *, urllib):
    return [urllib.parse.unquote(part) for part in parsed.path.strip('/').split('/')]


def _send_agent_error(handler, error, *, AgentRunConflict, AgentRunNotFound, AgentRuntimeError):
    if isinstance(error, AgentRunNotFound):
        handler.send_json({"ok": False, "error": str(error)}, 404)
    elif isinstance(error, AgentRunConflict):
        handler.send_json({"ok": False, "error": str(error)}, 409)
    elif isinstance(error, (ValueError, AgentRuntimeError)):
        handler.send_json({"ok": False, "error": str(error)}, 400)
    else:
        print(f"❌ Agent API 失败：{error}")
        handler.send_json({"ok": False, "error": str(error)}, 500)


def handle_desktop_workflow_save(handler, *, Path, _coerce_bool, json, os, uuid):
    """Save a desktop workflow JSON file to a user-provided local path."""
    tmp_path = None
    try:
        data = handler.read_json_body(max_bytes=192 * 1024 * 1024)
        payload = data.get('payload')
        if not isinstance(payload, dict):
            handler.send_json({"ok": False, "error": "工作流内容格式错误"}, 400)
            return

        raw_path = str(data.get('path') or data.get('file_path') or data.get('filePath') or '').strip()
        if not raw_path or '\x00' in raw_path:
            handler.send_json({"ok": False, "error": "请填写保存路径"}, 400)
            return

        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            target = Path.home() / 'Downloads' / target
        target = target.resolve()
        if not target.name.lower().endswith(('.tcflow.json', '.json')):
            handler.send_json({"ok": False, "error": "工作流文件必须保存为 .tcflow.json 或 .json"}, 400)
            return
        if target.exists() and target.is_dir():
            handler.send_json({"ok": False, "error": "保存路径不能是文件夹"}, 400)
            return
        if target.exists() and not _coerce_bool(data.get('overwrite'), False):
            handler.send_json({"ok": False, "error": "文件已存在", "path": str(target)}, 409)
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp_path, target)
        handler.send_json({
            "ok": True,
            "path": str(target),
            "filename": target.name,
            "bytes": target.stat().st_size,
        })
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 工作流文件保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)
    finally:
        try:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
