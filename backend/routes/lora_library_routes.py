"""Authenticated metadata endpoints, separate from generation contracts."""
from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from ..local_image.lora_store import normalize_asset_id
from ..lora_library.previews import MAX_BYTES
from ..lora_library.repository import ConflictError


def create_router(service):
    def handle(handler, action):
        try:
            query = parse_qs(urlparse(handler.path).query)
            get = lambda key, default="": query.get(key, [default])[0]
            body = {} if handler.command == "GET" or action == "preview-import" else handler.read_json_body(max_bytes=128 * 1024)
            if not isinstance(body, dict):
                raise ValueError("请求内容须为 JSON 对象")
            if action == "list":
                result = service.list(engine=get("engine"), query=get("query"), filter_value=get("filter", "all"),
                                      offset=get("offset", 0), limit=get("limit", 60), refresh=get("refresh") == "1")
            elif action == "detail":
                result = {"ok": True, "item": service.detail(get("asset_id"))}
            elif action == "update":
                result = {"ok": True, "item": service.edit(body)}
            elif action == "preview":
                handler.send_binary_file(service.previews.path(get("id"), thumb=get("thumb") == "1"))
                return
            elif action == "preview-import":
                size = int(handler.headers.get("Content-Length", 0))
                if not 0 < size <= MAX_BYTES:
                    raise ValueError("示例图须为 16 MB 以内的图片")
                content = handler.rfile.read(size)
                if len(content) != size:
                    raise ValueError("示例图上传不完整")
                identity = normalize_asset_id(get("asset_id"))
                service.previews.add(identity, content)
                result = {"ok": True, "item": service.detail(identity)}
            elif action == "preview-delete":
                identity = normalize_asset_id(body.get("asset_id"))
                service.previews.delete(identity, body.get("preview_id"))
                result = {"ok": True, "item": service.detail(identity)}
            elif action == "bind-source":
                result = {"ok": True, "item": service.bind(body.get("asset_id"), body.get("url", ""))}
            elif action == "sync":
                result = service.sync(body.get("asset_ids"))
            elif action == "sync-state":
                result = service.sync_state()
            elif action == "settings":
                result = {"ok": True, **service.settings(None if handler.command == "GET" else body)}
            elif action == "clear-cache":
                with service.lock:
                    if service.sync_state()["active"]:
                        raise ValueError("资料正在同步，请完成后再清理缓存")
                    result = {"ok": True, "removed": service.previews.clear_cache()}
            elif action == "delete-weight":
                result = service.delete_weight(body.get("asset_id"), body.get("engine"))
            else:
                raise ValueError("未知 LoRA 资料操作")
            handler.send_json(result)
        except ConflictError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 409)
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except RuntimeError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 409)
        except Exception:
            handler.send_json({"ok": False, "error": "LoRA 资料读写失败"}, 500)

    routes = {}
    for method, actions in (("GET", ("list", "detail", "preview", "settings", "sync-state")),
                            ("POST", ("update", "preview-import", "preview-delete", "bind-source", "sync",
                                      "settings", "clear-cache", "delete-weight"))):
        for action in actions:
            routes[(method, "/api/lora/" + action)] = lambda handler, action=action: handle(handler, action)
    return ProtectedRouter(routes)
