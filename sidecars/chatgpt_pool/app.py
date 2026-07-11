from __future__ import annotations

import json
import hmac
import time
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from .account_pool import AccountPool
from .account_store import AccountStore, NORMAL_STATUS, VERIFICATION_STATUS
from .capabilities import SIDECAR_CAPABILITIES
from .chat_api import create_chat_completion
from .config import load_settings
from .editable_api import generate_editable_file
from .image_api import edit_image, generate_images, stream_images
from .model_catalog import discover_pool_models
from .oauth_flow import OAuthError, OAuthService
from .openai_backend import OpenAIBackend, VerificationRequiredError
from .search_api import search_web
from .token_refresh import AccountLimitProber, TokenRefresher


settings = load_settings()
store = AccountStore(settings.db_path)
pool = AccountPool(
    store,
    max_concurrency=settings.max_account_concurrency,
    lease_timeout_seconds=settings.lease_timeout_seconds,
)
oauth_service = OAuthService(store)
refresher = TokenRefresher(store)
limit_prober = AccountLimitProber(store)


def require_auth(authorization: str | None) -> None:
    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), settings.auth_key):
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})


def start_watcher(stop_event: threading.Event) -> threading.Thread:
    probe_interval_seconds = min(max(5, settings.refresh_interval_seconds), 30)
    def worker() -> None:
        last_refresh_at = time.monotonic()
        while not stop_event.wait(probe_interval_seconds):
            try:
                limit_prober.probe_due_accounts()
                now = time.monotonic()
                if now - last_refresh_at >= settings.refresh_interval_seconds:
                    refresher.refresh_expiring()
                    refresher.keepalive_refresh_tokens()
                    last_refresh_at = now
            except Exception as exc:
                print(f"[chatgpt-pool] watcher failed: {exc}", flush=True)

    thread = threading.Thread(target=worker, name="chatgpt-pool-watcher", daemon=True)
    thread.start()
    return thread


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = threading.Event()
    thread = start_watcher(stop_event)
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=2)


app = FastAPI(title="chatgpt-pool-sidecar", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "ok": True,
        "stats": pool.stats(),
        "model": settings.generation_model,
        "main_model": settings.generation_model,
        "image_engine": "ChatGPT Image",
        "capabilities": SIDECAR_CAPABILITIES,
    }


@app.get("/accounts")
def list_accounts(authorization: str | None = Header(default=None)):
    require_auth(authorization)
    return {"ok": True, "items": store.list_public_accounts(), "stats": pool.stats()}


@app.get("/models")
def list_models(refresh: bool = False, authorization: str | None = Header(default=None)):
    require_auth(authorization)
    return discover_pool_models(store, force=bool(refresh))


@app.post("/accounts/import")
def import_accounts(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    accounts = body.get("accounts") if isinstance(body.get("accounts"), list) else []
    token = str(body.get("access_token") or body.get("accessToken") or "").strip()
    if token:
        accounts.append(dict(body))
    if not accounts:
        raise HTTPException(status_code=400, detail={"error": "accounts or access_token is required"})
    return store.upsert_accounts(accounts)


@app.post("/accounts/oauth/start")
def oauth_start(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    return oauth_service.start(str(body.get("email_hint") or ""), force_reauth=bool(body.get("force_reauth")))


@app.post("/accounts/oauth/finish")
def oauth_finish(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    try:
        return oauth_service.finish(str(body.get("session_id") or ""), str(body.get("callback") or ""))
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@app.post("/accounts/refresh")
def refresh_accounts(body: dict[str, Any] | None = None, authorization: str | None = Header(default=None)):
    require_auth(authorization)
    force = bool((body or {}).get("force"))
    result = refresher.refresh_expiring(force=force)
    profile_result = refresher.sync_account_profiles()
    result["limit_probe"] = limit_prober.probe_due_accounts()
    result["profile_synced"] = profile_result.get("synced", 0)
    result["profile_errors"] = profile_result.get("errors", [])
    result["items"] = store.list_public_accounts()
    result["stats"] = pool.stats()
    return result


@app.post("/accounts/update")
def update_account(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    token = str(body.get("access_token") or body.get("account_id") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail={"error": "access_token or account_id is required"})
    item = store.update_account(token, body)
    if item is None:
        raise HTTPException(status_code=404, detail={"error": "account not found"})
    return {"ok": True, "item": item, "items": store.list_public_accounts(), "stats": pool.stats()}


@app.post("/accounts/verify/probe")
def probe_account_verification(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    token = store.resolve_access_token(str(body.get("access_token") or body.get("account_id") or "").strip())
    if not token:
        raise HTTPException(status_code=400, detail={"error": "access_token or account_id is required"})
    account = store.get_private_account(token)
    if account is None:
        raise HTTPException(status_code=404, detail={"error": "account not found"})
    backend = OpenAIBackend(
        token,
        timeout_seconds=min(120, int(settings.timeout_seconds or 120)),
    )
    try:
        backend._bootstrap()
        requirements = backend._requirements()
    except VerificationRequiredError as exc:
        message = "Sentinel chat-requirements still requires " + ",".join(exc.challenges or ["browser verification"])
        item = store.update_account(
            token,
            {
                "status": VERIFICATION_STATUS,
                "quota": 0,
                "image_quota_unknown": True,
                "restore_at": "",
                "last_refresh_error": message,
            },
        )
        return {
            "ok": False,
            "verification_required": True,
            "challenges": exc.challenges,
            "error": message,
            "item": item,
            "items": store.list_public_accounts(),
            "stats": pool.stats(),
        }
    except Exception as exc:
        message = str(exc or "verification probe failed")[:600]
        item = store.update_account(token, {"last_refresh_error": message})
        return {
            "ok": False,
            "verification_required": False,
            "error": message,
            "item": item,
            "items": store.list_public_accounts(),
            "stats": pool.stats(),
        }
    item = store.update_account(
        token,
        {
            "status": NORMAL_STATUS,
            "image_quota_unknown": True,
            "restore_at": "",
            "last_refresh_error": "",
        },
    )
    return {
        "ok": True,
        "requirements_ok": bool(requirements.token),
        "item": item,
        "items": store.list_public_accounts(),
        "stats": pool.stats(),
    }


@app.post("/accounts/delete")
def delete_accounts(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    tokens = body.get("access_tokens") if isinstance(body.get("access_tokens"), list) else []
    account_ids = body.get("account_ids") if isinstance(body.get("account_ids"), list) else []
    token = str(body.get("access_token") or "").strip()
    account_id = str(body.get("account_id") or "").strip()
    if token:
        tokens.append(token)
    if account_id:
        tokens.append(account_id)
    tokens.extend(account_ids)
    if not tokens:
        raise HTTPException(status_code=400, detail={"error": "access_tokens or account_ids is required"})
    result = store.delete_accounts(tokens)
    result["stats"] = pool.stats()
    return result


@app.post("/v1/images/generations")
async def images_generations(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    if bool(body.get("stream")):
        def event_lines():
            try:
                for event in stream_images(body, pool):
                    yield f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
            except ValueError as exc:
                yield f"data: {json.dumps({'type': 'final', 'error': str(exc)}, ensure_ascii=False, separators=(',', ':'))}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'final', 'error': str(exc)}, ensure_ascii=False, separators=(',', ':'))}\n\n"

        return StreamingResponse(event_lines(), media_type="text/event-stream")
    try:
        return await run_in_threadpool(generate_images, body, pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc


@app.post("/v1/images/edits")
async def images_edits(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    try:
        return await run_in_threadpool(edit_image, body, pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc


@app.post("/v1/search")
async def search(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    try:
        return await run_in_threadpool(search_web, body, pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc


@app.post("/v1/chat/completions")
async def chat_completions(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    try:
        return await run_in_threadpool(create_chat_completion, body, pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc


@app.post("/v1/ppt/generations")
async def ppt_generations(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    try:
        return await run_in_threadpool(generate_editable_file, body, pool, "ppt")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc


@app.post("/v1/psd/generations")
async def psd_generations(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require_auth(authorization)
    try:
        return await run_in_threadpool(generate_editable_file, body, pool, "psd")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
