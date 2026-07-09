#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


def fake_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"header.{encoded}.sig"


class ChatgptPoolSidecarTest(unittest.TestCase):
    def make_store(self):
        from sidecars.chatgpt_pool.account_store import AccountStore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return AccountStore(Path(tmp.name) / "accounts.db")

    def test_health_reports_search_and_chat_capabilities(self):
        from sidecars.chatgpt_pool.capabilities import SIDECAR_CAPABILITIES

        self.assertTrue(SIDECAR_CAPABILITIES["search"])
        self.assertTrue(SIDECAR_CAPABILITIES["chat_completions"])
        self.assertTrue(SIDECAR_CAPABILITIES["image_edits"])

    def test_account_store_redacts_tokens_and_reports_stats(self):
        store = self.make_store()
        access = fake_jwt(
            {
                "exp": int(time.time()) + 3600,
                "https://api.openai.com/profile": {"email": "artist@example.com"},
                "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
            }
        )

        result = store.upsert_accounts(
            [
                {
                    "access_token": access,
                    "refresh_token": "rt-secret",
                    "id_token": fake_jwt({"email": "artist@example.com"}),
                    "source_type": "oauth_login",
                }
            ]
        )
        accounts = store.list_public_accounts()
        stats = store.stats()

        self.assertEqual(result["added"], 1)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["email"], "artist@example.com")
        self.assertTrue(accounts[0]["has_refresh_token"])
        self.assertIn("token_preview", accounts[0])
        self.assertNotIn("access_token", accounts[0])
        self.assertNotIn("refresh_token", accounts[0])
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["active"], 1)

    def test_account_store_ignores_legacy_browser_profile_fields(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool

        store = self.make_store()
        store.upsert_accounts(
            [
                {
                    "access_token": "token-profile",
                    "email": "profile@example.com",
                    "impersonate": "chrome",
                    "proxy_url": "http://127.0.0.1:8888",
                }
            ]
        )

        pool = AccountPool(store, max_concurrency=1)
        lease = pool.acquire_available()
        public = store.public_account("token-profile")

        self.assertEqual(lease.email, "profile@example.com")
        self.assertFalse(hasattr(lease, "client_profile"))
        self.assertFalse(hasattr(lease, "proxy_url"))
        self.assertNotIn("client_profile_configured", public)
        self.assertNotIn("proxy_configured", public)
        self.assertNotIn("impersonate", public)
        self.assertNotIn("proxy_url", public)

    def test_account_store_ignores_browser_verification_cookie_patch(self):
        store = self.make_store()
        store.upsert_accounts(
            [
                {
                    "access_token": "token-profile",
                    "email": "profile@example.com",
                    "last_refresh_error": "needs turnstile",
                }
            ]
        )

        store.update_account(
            "token-profile",
            {
                "status": "正常",
                "last_refresh_error": "",
                "client_profile": {
                    "cookie_header": "cf_clearance=clearance-token; oai-did=device-from-cookie",
                    "oai_device_id": "device-from-cookie",
                    "verification_cookie_names": ["cf_clearance", "oai-did"],
                },
            },
        )
        private = store.get_private_account("token-profile")
        public = store.public_account("token-profile")

        self.assertEqual(private["last_refresh_error"], "")
        self.assertEqual(private["status"], "正常")
        self.assertNotIn("client_profile", private)
        self.assertNotIn("client_profile_configured", public)

    def test_account_pool_round_robin_and_inflight_release(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-a", "email": "a@example.com", "quota": 2, "status": "正常"},
                {"access_token": "token-b", "email": "b@example.com", "quota": 2, "status": "正常"},
                {"access_token": "token-c", "email": "c@example.com", "quota": 2, "status": "限流"},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)

        first = pool.acquire_available()
        second = pool.acquire_available()
        with self.assertRaises(RuntimeError):
            pool.acquire_available()
        pool.mark_result(first.access_token, success=True)
        third = pool.acquire_available()

        self.assertEqual(first.email, "a@example.com")
        self.assertEqual(second.email, "b@example.com")
        self.assertEqual(third.email, "a@example.com")
        pool.mark_result(second.access_token, success=False, error="upstream failed")
        pool.mark_result(third.access_token, success=True)

    def test_account_store_allows_plan_type_to_be_synced_after_unknown_jwt(self):
        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com"}])
        self.assertEqual(store.public_account("token-a")["plan_type"], "unknown")

        store.update_account("token-a", {"plan_type": "free", "user_id": "user-1"})
        account = store.public_account("token-a")

        self.assertEqual(account["plan_type"], "free")
        self.assertEqual(account["user_id"], "user-1")

        store.update_account("token-a", {"plan_type": "unknown"})
        self.assertEqual(store.public_account("token-a")["plan_type"], "free")

    def test_account_pool_stats_report_available_capacity_and_busy_accounts(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-a", "email": "a@example.com", "quota": 2, "status": "正常", "image_quota_unknown": False},
                {"access_token": "token-b", "email": "b@example.com", "quota": 2, "status": "正常", "image_quota_unknown": False},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        initial = pool.stats()
        lease = pool.acquire_available()
        busy = pool.stats()
        pool.mark_result(lease.access_token, success=True)
        released = pool.stats()

        self.assertEqual(initial["available"], 2)
        self.assertEqual(initial["capacity"], 2)
        self.assertEqual(busy["inflight"], 1)
        self.assertEqual(busy["busy_accounts"], 1)
        self.assertEqual(busy["available"], 1)
        self.assertEqual(busy["capacity"], 1)
        self.assertEqual(released["inflight"], 0)
        self.assertEqual(released["available"], 2)

    def test_account_limit_prober_reactivates_due_limited_accounts(self):
        from sidecars.chatgpt_pool.account_store import LIMITED_STATUS, NORMAL_STATUS
        from sidecars.chatgpt_pool.openai_backend import ImageGenerationStatus
        from sidecars.chatgpt_pool.token_refresh import AccountLimitProber

        store = self.make_store()
        store.upsert_accounts(
            [
                {
                    "access_token": "token-limited",
                    "email": "limited@example.com",
                    "quota": 0,
                    "status": LIMITED_STATUS,
                    "image_quota_unknown": False,
                    "restore_at": "2000-01-01T00:00:00+00:00",
                }
            ]
        )
        probed_tokens = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                probed_tokens.append(access_token)

            def check_image_generation_status(self):
                return ImageGenerationStatus(available=True, remaining=3)

        prober = AccountLimitProber(store, backend_factory=FakeBackend, probe_delay_seconds=60)
        result = prober.probe_due_accounts()
        account = store.public_account("token-limited")

        self.assertEqual(probed_tokens, ["token-limited"])
        self.assertEqual(result["probed"], 1)
        self.assertEqual(result["reactivated"], 1)
        self.assertEqual(account["status"], NORMAL_STATUS)
        self.assertEqual(account["restore_at"], "")
        self.assertFalse(account["image_quota_unknown"])
        self.assertEqual(account["quota"], 3)

    def test_account_limit_prober_waits_until_one_minute_after_restore_time(self):
        from sidecars.chatgpt_pool.account_store import LIMITED_STATUS
        from sidecars.chatgpt_pool.token_refresh import AccountLimitProber

        store = self.make_store()
        store.upsert_accounts(
            [
                {
                    "access_token": "token-limited",
                    "email": "limited@example.com",
                    "quota": 0,
                    "status": LIMITED_STATUS,
                    "image_quota_unknown": False,
                    "restore_at": "2099-01-01T00:00:00+00:00",
                }
            ]
        )

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                raise AssertionError("probe should wait until restore_at plus grace period")

        prober = AccountLimitProber(store, backend_factory=FakeBackend, probe_delay_seconds=60)
        result = prober.probe_due_accounts()
        account = store.public_account("token-limited")

        self.assertEqual(result["probed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(account["status"], LIMITED_STATUS)
        self.assertEqual(account["restore_at"], "2099-01-01T00:00:00+00:00")

    def test_account_limit_prober_keeps_account_limited_when_probe_still_blocked(self):
        from sidecars.chatgpt_pool.account_store import LIMITED_STATUS
        from sidecars.chatgpt_pool.openai_backend import ImageGenerationStatus
        from sidecars.chatgpt_pool.token_refresh import AccountLimitProber

        store = self.make_store()
        store.upsert_accounts(
            [
                {
                    "access_token": "token-limited",
                    "email": "limited@example.com",
                    "quota": 0,
                    "status": LIMITED_STATUS,
                    "image_quota_unknown": False,
                    "restore_at": "2000-01-01T00:00:00+00:00",
                }
            ]
        )

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                pass

            def check_image_generation_status(self):
                return ImageGenerationStatus(
                    available=False,
                    remaining=0,
                    reset_after="2099-01-01T00:00:00+00:00",
                )

        prober = AccountLimitProber(store, backend_factory=FakeBackend, probe_delay_seconds=60)
        result = prober.probe_due_accounts()
        account = store.public_account("token-limited")

        self.assertEqual(result["probed"], 1)
        self.assertEqual(result["still_limited"], 1)
        self.assertEqual(account["status"], LIMITED_STATUS)
        self.assertEqual(account["restore_at"], "2099-01-01T00:00:00+00:00")

    def test_account_pool_prunes_stale_inflight_leases(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 2, "status": "正常"}])
        pool = AccountPool(store, max_concurrency=1, lease_timeout_seconds=60)

        lease = pool.acquire_available()
        self.assertEqual(lease.access_token, "token-a")
        self.assertEqual(pool.stats()["available"], 0)
        with pool._lock:
            pool._inflight["token-a"] = [time.monotonic() - 120]

        stats = pool.stats()
        self.assertEqual(stats["inflight"], 0)
        self.assertEqual(stats["available"], 1)
        self.assertEqual(pool.acquire_available().access_token, "token-a")

    def test_oauth_finish_stores_refreshable_account(self):
        from sidecars.chatgpt_pool.oauth_flow import OAuthService

        store = self.make_store()

        def exchange(code, code_verifier, redirect_uri):
            self.assertEqual(code, "oauth-code")
            self.assertTrue(code_verifier)
            self.assertIn("platform.openai.com", redirect_uri)
            return {
                "access_token": fake_jwt(
                    {
                        "exp": int(time.time()) + 3600,
                        "https://api.openai.com/profile": {"email": "oauth@example.com"},
                    }
                ),
                "refresh_token": "refresh-token",
                "id_token": fake_jwt({"email": "oauth@example.com"}),
            }

        service = OAuthService(store, token_exchange=exchange)
        started = service.start("oauth@example.com")
        callback = f"https://platform.openai.com/auth/callback?code=oauth-code&state={started['state']}"

        self.assertIn("screen_hint=login_or_signup", started["authorize_url"])
        self.assertIn("max_age=0", started["authorize_url"])
        finished = service.finish(started["session_id"], callback)
        accounts = store.list_public_accounts()

        self.assertEqual(finished["account"]["email"], "oauth@example.com")
        self.assertEqual(len(accounts), 1)
        self.assertTrue(accounts[0]["has_refresh_token"])

    def test_refresh_service_rotates_access_token_without_leaking_secret(self):
        from sidecars.chatgpt_pool.token_refresh import TokenRefresher

        store = self.make_store()
        old_access = fake_jwt({"exp": int(time.time()) - 60})
        new_access = fake_jwt(
            {
                "exp": int(time.time()) + 7200,
                "https://api.openai.com/profile": {"email": "refresh@example.com"},
            }
        )
        store.upsert_accounts(
            [
                {
                    "access_token": old_access,
                    "refresh_token": "refresh-token",
                    "id_token": fake_jwt({"email": "refresh@example.com"}),
                    "email": "refresh@example.com",
                }
            ]
        )

        refresher = TokenRefresher(
            store,
            token_exchange=lambda refresh_token: {
                "access_token": new_access,
                "refresh_token": refresh_token,
                "id_token": fake_jwt({"email": "refresh@example.com"}),
            },
        )
        result = refresher.refresh_expiring(force=True)
        accounts = store.list_public_accounts()

        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(accounts[0]["email"], "refresh@example.com")
        self.assertNotIn(new_access, json.dumps(accounts, ensure_ascii=False))

    def test_search_api_uses_account_pool_and_returns_sources(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.search_api import search_web

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

            def search(self, prompt, model="gpt-5-5", timeout_secs=300.0, poll_interval_secs=3.0):
                return {
                    "conversation_id": "conv-search",
                    "answer": f"answer for {prompt}",
                    "sources": [{"title": "Source", "url": "https://example.com", "snippet": "", "source_type": ""}],
                }

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-search", "email": "search@example.com", "quota": 2, "status": "正常"}])
        pool = AccountPool(store, max_concurrency=1)

        result = search_web({"prompt": "联网查一下", "model": "gpt-5-5"}, pool, backend_factory=FakeBackend)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["conversation_id"], "conv-search")
        self.assertEqual(result["result"]["sources"][0]["url"], "https://example.com")

    def test_chat_api_uses_account_pool_and_returns_chat_completion_shape(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.chat_api import create_chat_completion

        test_case = self

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

            def chat_completion(self, messages, model="auto", timeout_secs=180.0):
                test_case.assertEqual(messages[0]["content"], "润色这个提示词")
                return {
                    "conversation_id": "conv-chat",
                    "assistant_message_id": "msg-chat",
                    "content": '{"full_prompt":"优化后提示词","compact_prompt":"短提示词","warnings":[]}',
                }

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-chat", "email": "chat@example.com", "quota": 2, "status": "正常"}])
        pool = AccountPool(store, max_concurrency=1)

        result = create_chat_completion(
            {"messages": [{"role": "user", "content": "润色这个提示词"}], "model": "auto"},
            pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(result["object"], "chat.completion")
        self.assertEqual(result["conversation_id"], "conv-chat")
        self.assertIn("优化后提示词", result["choices"][0]["message"]["content"])

    def test_chat_api_passes_base64_images_to_multimodal_chat(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.chat_api import create_chat_completion

        test_case = self

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

            def chat_completion_with_images(self, messages, base64_images, model="auto", timeout_secs=180.0):
                test_case.assertEqual(messages[0]["content"], "分析这张图片")
                test_case.assertEqual(base64_images, ["data:image/png;base64,AAAA"])
                return {
                    "conversation_id": "conv-vision",
                    "assistant_message_id": "msg-vision",
                    "content": '{"image_kind":"摄影","prompt_blocks":{"main_prompt_no_text":"机场人像"}}',
                }

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-vision", "email": "vision@example.com", "quota": 2, "status": "正常"}])
        pool = AccountPool(store, max_concurrency=1)

        result = create_chat_completion(
            {
                "messages": [{"role": "user", "content": "分析这张图片"}],
                "model": "auto",
                "base64_images": ["data:image/png;base64,AAAA"],
            },
            pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(result["object"], "chat.completion")
        self.assertEqual(result["conversation_id"], "conv-vision")
        self.assertIn("机场人像", result["choices"][0]["message"]["content"])

    def test_chat_api_marks_verification_required_and_tries_next_account(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.account_store import VERIFICATION_STATUS
        from sidecars.chatgpt_pool.chat_api import create_chat_completion
        from sidecars.chatgpt_pool.openai_backend import VerificationRequiredError

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-needs-verify", "email": "verify@example.com", "quota": 2, "status": "正常"},
                {"access_token": "token-ready", "email": "ready@example.com", "quota": 2, "status": "正常"},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token
                used_tokens.append(access_token)

            def chat_completion(self, messages, model="auto", timeout_secs=180.0):
                if self.access_token == "token-needs-verify":
                    raise VerificationRequiredError(challenges=["arkose"])
                return {"conversation_id": "conv-ok", "assistant_message_id": "msg-ok", "content": "ok"}

        result = create_chat_completion(
            {"messages": [{"role": "user", "content": "hello"}], "model": "auto"},
            pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(used_tokens, ["token-needs-verify", "token-ready"])
        self.assertEqual(result["conversation_id"], "conv-ok")
        self.assertEqual(store.public_account("token-needs-verify")["status"], VERIFICATION_STATUS)
        self.assertEqual(pool.stats()["inflight"], 0)

    def test_refresh_success_clears_previous_refresh_error(self):
        from sidecars.chatgpt_pool.token_refresh import TokenRefresher

        store = self.make_store()
        old_access = fake_jwt({"exp": int(time.time()) - 60})
        new_access = fake_jwt(
            {
                "exp": int(time.time()) + 7200,
                "https://api.openai.com/profile": {"email": "refresh@example.com"},
            }
        )
        store.upsert_accounts(
            [
                {
                    "access_token": old_access,
                    "refresh_token": "refresh-token",
                    "id_token": fake_jwt({"email": "refresh@example.com"}),
                    "email": "refresh@example.com",
                }
            ]
        )
        store.record_refresh_error(old_access, "curl TLS connect error")

        refresher = TokenRefresher(
            store,
            token_exchange=lambda refresh_token: {
                "access_token": new_access,
                "refresh_token": refresh_token,
                "id_token": fake_jwt({"email": "refresh@example.com"}),
            },
        )
        result = refresher.refresh_expiring(force=True)
        accounts = store.list_public_accounts()

        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(accounts[0]["email"], "refresh@example.com")
        self.assertEqual(accounts[0]["last_refresh_error"], "")

    def test_image_api_uses_account_pool_and_returns_openai_shape(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 3}])
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token):
                used_tokens.append(access_token)

            def generate_image(self, prompt, model, size, quality):
                return {"b64_json": image_b64, "revised_prompt": f"rev:{prompt}"}

        result = generate_images(
            {
                "prompt": "draw a poster",
                "model": "gpt-image-2",
                "n": 1,
                "response_format": "b64_json",
            },
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(used_tokens, ["token-a"])
        self.assertEqual(result["data"][0]["b64_json"], image_b64)
        self.assertEqual(result["data"][0]["revised_prompt"], "rev:draw a poster")

    def test_image_api_passes_timeout_to_backend_when_supported(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 3}])
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        captured = {}

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                captured["access_token"] = access_token
                captured["timeout_seconds"] = timeout_seconds

            def generate_image(self, prompt, model, size, quality):
                return {"b64_json": image_b64}

        result = generate_images(
            {
                "prompt": "draw a poster",
                "model": "gpt-image-2",
                "n": 1,
                "response_format": "b64_json",
                "timeout_seconds": 123,
            },
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(captured["access_token"], "token-a")
        self.assertEqual(captured["timeout_seconds"], 123)
        self.assertEqual(result["data"][0]["b64_json"], image_b64)

    def test_image_edit_api_uses_account_pool_and_returns_openai_shape(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import edit_image

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 3}])
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"edited-png").decode("ascii")
        captured = {}

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                captured["access_token"] = access_token
                captured["timeout_seconds"] = timeout_seconds

            def edit_image(self, prompt, images, model, size, quality, mask=None):
                captured["prompt"] = prompt
                captured["images"] = images
                captured["model"] = model
                captured["size"] = size
                captured["quality"] = quality
                captured["mask"] = mask
                return {"b64_json": image_b64, "revised_prompt": f"rev:{prompt}"}

        result = edit_image(
            {
                "prompt": "change the poster color",
                "model": "gpt-image-2",
                "image": ["source-b64"],
                "mask": "mask-b64",
                "response_format": "b64_json",
                "size": "1024x1024",
                "quality": "medium",
                "timeout_seconds": 123,
            },
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(captured["access_token"], "token-a")
        self.assertEqual(captured["timeout_seconds"], 123)
        self.assertEqual(captured["images"], ["source-b64"])
        self.assertEqual(captured["mask"], "mask-b64")
        self.assertEqual(result["data"][0]["b64_json"], image_b64)
        self.assertEqual(result["data"][0]["revised_prompt"], "rev:change the poster color")
        self.assertEqual(pool.stats()["inflight"], 0)

    def test_image_api_releases_lease_when_backend_runtime_error_occurs(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 3}])
        pool = AccountPool(store, max_concurrency=1)

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token

            def generate_image(self, prompt, model, size, quality):
                raise RuntimeError("ChatGPT image generation timed out while polling results")

        with self.assertRaisesRegex(RuntimeError, "timed out while polling results"):
            generate_images(
                {
                    "prompt": "draw a poster",
                    "model": "gpt-image-2",
                    "n": 1,
                    "response_format": "b64_json",
                },
                pool=pool,
                backend_factory=FakeBackend,
            )

        self.assertEqual(pool.stats()["inflight"], 0)
        self.assertEqual(pool.stats()["available"], 1)
        self.assertEqual(store.public_account("token-a")["fail"], 1)

    def test_image_api_uses_account_capacity_as_parallel_queue(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-a", "email": "a@example.com", "quota": 8, "status": "正常", "image_quota_unknown": False},
                {"access_token": "token-b", "email": "b@example.com", "quota": 8, "status": "正常", "image_quota_unknown": False},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        lock = threading.Lock()
        active = 0
        max_active = 0
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token

            def generate_image(self, prompt, model, size, quality):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                    used_tokens.append(self.access_token)
                time.sleep(0.02)
                with lock:
                    active -= 1
                return {"b64_json": image_b64, "revised_prompt": f"{self.access_token}:{prompt}"}

        result = generate_images(
            {
                "prompt": "draw a poster",
                "model": "gpt-image-2",
                "n": 5,
                "response_format": "b64_json",
            },
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(len(result["data"]), 5)
        self.assertEqual(max_active, 2)
        self.assertEqual(pool.stats()["inflight"], 0)
        self.assertEqual(store.public_account("token-a")["success"] + store.public_account("token-b")["success"], 5)
        self.assertGreater(store.public_account("token-a")["success"], 0)
        self.assertGreater(store.public_account("token-b")["success"], 0)
        self.assertEqual(set(used_tokens), {"token-a", "token-b"})

    def test_image_api_streams_completed_images_before_final_errors(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import stream_images

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-a", "email": "a@example.com", "quota": 8, "status": "正常", "image_quota_unknown": False},
                {"access_token": "token-b", "email": "b@example.com", "quota": 8, "status": "正常", "image_quota_unknown": False},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token

            def generate_image(self, prompt, model, size, quality):
                if self.access_token == "token-b":
                    time.sleep(0.03)
                    raise RuntimeError("slow worker timed out")
                return {"b64_json": image_b64, "revised_prompt": f"{self.access_token}:{prompt}"}

        events = list(
            stream_images(
                {
                    "prompt": "draw a poster",
                    "model": "gpt-image-2",
                    "n": 2,
                    "response_format": "b64_json",
                },
                pool=pool,
                backend_factory=FakeBackend,
            )
        )

        self.assertEqual(events[0]["type"], "started")
        image_events = [event for event in events if event.get("type") == "image"]
        error_events = [event for event in events if event.get("type") == "error"]
        final = events[-1]
        self.assertEqual(len(image_events), 1)
        self.assertEqual(image_events[0]["item"]["b64_json"], image_b64)
        self.assertEqual(len(error_events), 1)
        self.assertEqual(final["type"], "final")
        self.assertEqual(len(final["data"]), 1)
        self.assertIn("partial_errors", final)
        self.assertEqual(pool.stats()["inflight"], 0)

    def test_image_api_clamps_requested_count_to_eight(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 12}])
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        calls = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                pass

            def generate_image(self, prompt, model, size, quality):
                calls.append(prompt)
                return {"b64_json": image_b64}

        result = generate_images(
            {"prompt": "draw", "model": "gpt-image-2", "n": 99, "response_format": "b64_json"},
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(len(calls), 8)
        self.assertEqual(len(result["data"]), 8)

    def test_image_api_skips_accounts_with_image_generation_limit(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.account_store import LIMITED_STATUS
        from sidecars.chatgpt_pool.image_api import generate_images
        from sidecars.chatgpt_pool.openai_backend import ImageGenerationStatus

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-limited", "email": "limited@example.com", "quota": 3},
                {"access_token": "token-ready", "email": "ready@example.com", "quota": 3},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token
                used_tokens.append(access_token)

            def check_image_generation_status(self):
                if self.access_token == "token-limited":
                    return ImageGenerationStatus(
                        available=False,
                        remaining=0,
                        reset_after="2026-06-22T05:56:44+00:00",
                        title="你已达到图片创建上限",
                    )
                return ImageGenerationStatus(available=True, remaining=2)

            def generate_image(self, prompt, model, size, quality):
                return {"b64_json": image_b64}

        result = generate_images(
            {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(used_tokens, ["token-limited", "token-ready"])
        self.assertEqual(result["data"][0]["b64_json"], image_b64)
        limited = store.public_account("token-limited")
        self.assertEqual(limited["status"], LIMITED_STATUS)
        self.assertEqual(limited["quota"], 0)
        self.assertFalse(limited["image_quota_unknown"])
        self.assertEqual(limited["restore_at"], "2026-06-22T05:56:44+00:00")

    def test_image_api_marks_verification_required_and_tries_next_account(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.account_store import VERIFICATION_STATUS
        from sidecars.chatgpt_pool.image_api import generate_images
        from sidecars.chatgpt_pool.openai_backend import VerificationRequiredError

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-needs-verify", "email": "verify@example.com", "quota": 3},
                {"access_token": "token-ready", "email": "ready@example.com", "quota": 3},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token
                used_tokens.append(access_token)

            def generate_image(self, prompt, model, size, quality):
                if self.access_token == "token-needs-verify":
                    raise VerificationRequiredError(challenges=["turnstile"])
                return {"b64_json": image_b64}

        result = generate_images(
            {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(used_tokens, ["token-needs-verify", "token-ready"])
        self.assertEqual(result["data"][0]["b64_json"], image_b64)
        self.assertEqual(store.public_account("token-needs-verify")["status"], VERIFICATION_STATUS)
        self.assertEqual(pool.stats()["inflight"], 0)

    def test_image_api_retries_next_account_after_web_tool_system_error(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-rpc-error", "email": "rpc@example.com", "quota": 3},
                {"access_token": "token-ready", "email": "ready@example.com", "quota": 3},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token
                used_tokens.append(access_token)

            def generate_image(self, prompt, model, size, quality):
                if self.access_token == "token-rpc-error":
                    raise RuntimeError(
                        "ChatGPT conversation finished without image output: "
                        "conversation_id=abc; last_state=nodes=8, content_types=code,model_editable_context,system_error,text; "
                        "system_error=RPCError: Encountered exception: <class 'temporalio.service.RPCError'>."
                    )
                return {"b64_json": image_b64}

        result = generate_images(
            {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
            pool=pool,
            backend_factory=FakeBackend,
        )

        self.assertEqual(used_tokens, ["token-rpc-error", "token-ready"])
        self.assertEqual(result["data"][0]["b64_json"], image_b64)
        self.assertEqual(store.public_account("token-rpc-error")["fail"], 1)
        self.assertEqual(store.public_account("token-ready")["success"], 1)
        self.assertEqual(pool.stats()["inflight"], 0)

    def test_image_api_reports_upstream_error_after_retryable_accounts_fail(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-a", "email": "a@example.com", "quota": 3},
                {"access_token": "token-b", "email": "b@example.com", "quota": 3},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)
        used_tokens = []

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token
                used_tokens.append(access_token)

            def generate_image(self, prompt, model, size, quality):
                raise RuntimeError("system_error=RPCError: Encountered exception: temporalio.service.RPCError")

        with self.assertRaisesRegex(RuntimeError, "upstream image generation failed after trying available accounts"):
            generate_images(
                {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
                pool=pool,
                backend_factory=FakeBackend,
            )

        self.assertEqual(used_tokens, ["token-a", "token-b"])
        self.assertEqual(store.public_account("token-a")["fail"], 1)
        self.assertEqual(store.public_account("token-b")["fail"], 1)
        self.assertEqual(pool.stats()["inflight"], 0)

    def test_image_api_reports_verification_required_when_all_accounts_need_verification(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.account_store import VERIFICATION_STATUS
        from sidecars.chatgpt_pool.image_api import generate_images
        from sidecars.chatgpt_pool.openai_backend import VerificationRequiredError

        store = self.make_store()
        store.upsert_accounts(
            [
                {"access_token": "token-a", "email": "a@example.com", "quota": 3},
                {"access_token": "token-b", "email": "b@example.com", "quota": 3},
            ]
        )
        pool = AccountPool(store, max_concurrency=1)

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token

            def generate_image(self, prompt, model, size, quality):
                raise VerificationRequiredError(challenges=["turnstile"])

        with self.assertRaisesRegex(RuntimeError, "browser verification required"):
            generate_images(
                {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
                pool=pool,
                backend_factory=FakeBackend,
            )

        self.assertEqual(store.public_account("token-a")["status"], VERIFICATION_STATUS)
        self.assertEqual(store.public_account("token-b")["status"], VERIFICATION_STATUS)

    def test_image_api_reports_quota_exhausted_when_all_accounts_limited(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images
        from sidecars.chatgpt_pool.openai_backend import ImageGenerationStatus

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-limited", "email": "limited@example.com", "quota": 3}])
        pool = AccountPool(store, max_concurrency=1)

        class FakeBackend:
            def __init__(self, access_token, timeout_seconds=None):
                self.access_token = access_token

            def check_image_generation_status(self):
                return ImageGenerationStatus(
                    available=False,
                    remaining=0,
                    reset_after="2026-06-22T05:56:44+00:00",
                    title="你已达到图片创建上限",
                    description="升级至 ChatGPT Plus，或于 14小时 内重试。",
                )

            def generate_image(self, prompt, model, size, quality):
                raise AssertionError("limited account should not generate")

        with self.assertRaisesRegex(RuntimeError, "image quota exhausted"):
            generate_images(
                {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
                pool=pool,
                backend_factory=FakeBackend,
            )

    def test_image_api_reports_restore_time_when_pool_already_has_no_available_quota(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.image_api import generate_images

        store = self.make_store()
        store.upsert_accounts(
            [
                {
                    "access_token": "token-limited",
                    "email": "limited@example.com",
                    "quota": 0,
                    "status": "限流",
                    "image_quota_unknown": False,
                    "restore_at": "2099-06-22T05:56:44+00:00",
                }
            ]
        )
        pool = AccountPool(store, max_concurrency=1)

        with self.assertRaisesRegex(RuntimeError, "2099-06-22T05:56:44"):
            generate_images(
                {"prompt": "draw", "model": "gpt-image-2", "response_format": "b64_json"},
                pool=pool,
                backend_factory=lambda access_token: None,
            )

    def test_sidecar_config_lease_outlives_image_timeout(self):
        from sidecars.chatgpt_pool import config

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(json.dumps({"chatgpt_pool": {"timeout_seconds": 900, "lease_timeout_seconds": 300}}), encoding="utf-8")
            with patch.object(config, "SETTINGS_PATH", settings_path):
                loaded = config.load_settings()

        self.assertEqual(loaded.timeout_seconds, 900)
        self.assertEqual(loaded.lease_timeout_seconds, 960)

    def test_editable_api_uses_account_pool_and_returns_file_payloads(self):
        from sidecars.chatgpt_pool.account_pool import AccountPool
        from sidecars.chatgpt_pool.editable_api import generate_editable_file

        store = self.make_store()
        store.upsert_accounts([{"access_token": "token-a", "email": "a@example.com", "quota": 3}])
        pool = AccountPool(store, max_concurrency=1)
        used_tokens = []

        class FakeResult:
            conversation_id = "conv-1"

            def __init__(self, tmp):
                self.primary_path = Path(tmp) / "deck.pptx"
                self.zip_path = Path(tmp) / "deck.zip"
                self.primary_path.write_bytes(b"pptx")
                self.zip_path.write_bytes(b"zip")

        class FakeBackend:
            def __init__(self, access_token):
                used_tokens.append(access_token)

            def export_ppt_zip(self, base64_images, prompt, output_dir):
                self.prompt = prompt
                return FakeResult(output_dir)

        result = generate_editable_file({"prompt": "做一个品牌方案"}, pool=pool, kind="ppt", backend_factory=FakeBackend)

        self.assertEqual(used_tokens, ["token-a"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["conversation_id"], "conv-1")
        self.assertEqual(base64.b64decode(result["result"]["primary"]["b64"]), b"pptx")
        self.assertEqual(base64.b64decode(result["result"]["zip"]["b64"]), b"zip")

    def test_editable_download_retries_until_sandbox_url_is_ready(self):
        from sidecars.chatgpt_pool.openai_backend import EditableFileArtifact, OpenAIBackend

        class FakeResponse:
            def __init__(self, payload=None, content=b"", url="https://chatgpt.com/file"):
                self.status_code = 200
                self._payload = payload
                self.content = content
                self.text = json.dumps(payload or {})
                self.headers = {}
                self.url = url

            def json(self):
                if self._payload is None:
                    raise ValueError("not json")
                return self._payload

        calls = []
        backend = OpenAIBackend("access-token")

        def fake_request(method, url, **kwargs):
            self.assertEqual(method, "GET")
            calls.append(url)
            if "interpreter/download" in url and len(calls) == 1:
                return FakeResponse({"status": "pending"})
            if "interpreter/download" in url:
                return FakeResponse({"status": "success", "download_url": "https://download.local/deck.pptx"})
            return FakeResponse(None, b"pptx")

        backend.session.request = fake_request
        artifact = EditableFileArtifact(
            name="deck.pptx",
            sandbox_path="/mnt/data/deck.pptx",
            message_id="message-1",
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "sidecars.chatgpt_pool.openai_backend.time.sleep"
        ), patch("sidecars.chatgpt_pool.openai_backend.EDITABLE_FILE_DOWNLOAD_TIMEOUT_SECS", 1):
            path = backend._download_editable_artifact(
                "conversation-1",
                artifact,
                Path(tmp),
                {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
                ("presentation", "powerpoint"),
                ".pptx",
            )
            self.assertEqual(path.name, "deck.pptx")
            self.assertEqual(path.read_bytes(), b"pptx")

        self.assertGreaterEqual(len([url for url in calls if "interpreter/download" in url]), 2)

    def test_editable_artifact_extraction_merges_text_path_with_attachment_id(self):
        from sidecars.chatgpt_pool.openai_backend import EDITABLE_PSD_EXPORT_FILE_RE, OpenAIBackend

        backend = OpenAIBackend("access-token")
        conversation = {
            "mapping": {
                "node-1": {
                    "message": {
                        "id": "message-1",
                        "create_time": 100,
                        "author": {"role": "assistant"},
                        "metadata": {
                            "attachments": [
                                {
                                    "id": "file-service://artifact_123",
                                    "name": "reconstructed_editable.psd",
                                    "mime_type": "image/vnd.adobe.photoshop",
                                }
                            ]
                        },
                        "content": {
                            "content_type": "text",
                            "parts": ["已生成 sandbox:/mnt/data/reconstructed_editable.psd"]
                        },
                    }
                },
                "node-2": {
                    "message": {
                        "id": "message-2",
                        "create_time": 101,
                        "author": {"role": "assistant"},
                        "metadata": {
                            "attachments": [
                                {
                                    "id": "file-service://zip_123",
                                    "name": "layers.zip",
                                    "mime_type": "application/zip",
                                }
                            ]
                        },
                        "content": {
                            "content_type": "text",
                            "parts": ["素材包 sandbox:/mnt/data/layers.zip"]
                        },
                    }
                },
            }
        }

        artifacts = backend._extract_editable_artifacts(conversation, EDITABLE_PSD_EXPORT_FILE_RE)
        targets = backend._pick_editable_target_artifacts(
            artifacts,
            (".psd",),
            {"image/vnd.adobe.photoshop"},
            ("photoshop",),
        )

        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0].attachment_id, "artifact_123")
        self.assertEqual(targets[0].sandbox_path, "/mnt/data/reconstructed_editable.psd")
        self.assertEqual(targets[1].attachment_id, "zip_123")
        self.assertEqual(targets[1].sandbox_path, "/mnt/data/layers.zip")

    def test_web_image_prompt_only_adds_meaningful_hints(self):
        from sidecars.chatgpt_pool.openai_backend import build_image_prompt

        self.assertEqual(build_image_prompt("draw", None, "auto"), "draw")
        self.assertEqual(build_image_prompt("draw", "1024x1024", "auto"), "draw\n\n输出图片尺寸为 1024x1024。")
        self.assertEqual(
            build_image_prompt("draw", "1024x1024", "high"),
            "draw\n\n输出图片尺寸为 1024x1024。输出图片质量为 high。",
        )

    def test_openai_backend_extracts_image_generation_limit_status(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        backend = OpenAIBackend("access-token")
        status = backend._extract_image_generation_status(
            {
                "blocked_features": [
                    {
                        "name": "image_gen",
                        "resets_after": "2026-06-22T05:56:44+00:00",
                        "resets_after_text": "14小时 内",
                        "limit": 3.0,
                        "title": "你已达到图片创建上限",
                        "description": "升级至 ChatGPT Plus，或于 14小时 内重试。",
                    }
                ],
                "limits_progress": [
                    {"feature_name": "image_gen", "remaining": 0, "reset_after": "2026-06-22T05:56:44+00:00"}
                ],
            }
        )

        self.assertFalse(status.available)
        self.assertEqual(status.remaining, 0)
        self.assertEqual(status.reset_after, "2026-06-22T05:56:44+00:00")
        self.assertEqual(status.limit, 3.0)

    def test_openai_backend_uses_lightweight_legacy_headers(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, USER_AGENT

        backend = OpenAIBackend("access-token")
        headers = backend._headers("/backend-api/conversation")
        payload = backend._conversation_payload([{"role": "user", "content": "hello"}], "auto")

        self.assertEqual(headers["User-Agent"], USER_AGENT)
        self.assertNotIn("sec-ch-ua-platform", headers)
        self.assertNotIn("Sec-Fetch-Site", headers)
        self.assertNotIn("Cookie", headers)
        self.assertEqual(payload["timezone"], "Asia/Shanghai")
        self.assertEqual(payload["client_contextual_info"]["app_name"], "chatgpt.com")

    def test_openai_backend_detects_verification_challenges(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        backend = OpenAIBackend("access-token")

        self.assertEqual(
            backend._required_challenges(
                {
                    "arkose": {"required": True},
                    "turnstile": {"required": True},
                }
            ),
            ["arkose"],
        )
        self.assertEqual(backend._required_challenges({"turnstile": {"required": True}}), [])

    def test_openai_backend_detects_image_limit_message_in_conversation_text(self):
        from sidecars.chatgpt_pool.openai_backend import ImageGenerationLimitError, OpenAIBackend

        backend = OpenAIBackend("access-token")
        with self.assertRaises(ImageGenerationLimitError):
            backend._raise_if_image_limit_message(
                {
                    "mapping": {
                        "node": {
                            "message": {
                                "content": {
                                    "content_type": "text",
                                    "parts": [
                                        "You've hit the Free plan limit for image generations requests. "
                                        "You can create more images when the limit resets in 13 hours."
                                    ],
                                }
                            }
                        }
                    }
                }
            )

    def test_openai_backend_retries_transient_proxy_disconnect(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        class FakeResponse:
            status_code = 200
            text = "{}"

        backend = OpenAIBackend("access-token")
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if len(calls) == 1:
                raise requests.exceptions.ProxyError("Unable to connect to proxy")
            return FakeResponse()

        backend.session.request = fake_request
        with patch("sidecars.chatgpt_pool.openai_backend.time.sleep"):
            response = backend._request("GET", "https://chatgpt.com/backend-api/conversation/test", timeout=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_openai_backend_image_poll_uses_configured_timeout(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        backend = OpenAIBackend("access-token", timeout_seconds=420)
        observed_deadlines = []

        def fake_time():
            if not observed_deadlines:
                observed_deadlines.append("deadline-start")
                return 1000
            if len(observed_deadlines) == 1:
                observed_deadlines.append("loop-after-180")
                return 1300
            return 2000

        def fake_get_conversation(conversation_id):
            return {"id": conversation_id}

        def fake_sleep(_seconds):
            observed_deadlines.append("slept")

        with patch("sidecars.chatgpt_pool.openai_backend.time.time", side_effect=fake_time), patch(
            "sidecars.chatgpt_pool.openai_backend.time.sleep", side_effect=fake_sleep
        ), patch.object(backend, "_get_conversation", side_effect=fake_get_conversation):
            with self.assertRaises(Exception):
                backend._poll_image_results("conversation-id")

        self.assertIn("slept", observed_deadlines)

    def test_openai_backend_extracts_file_service_image_asset_pointer(self):
        from sidecars.chatgpt_pool.openai_backend import extract_ids

        conversation_id, file_ids, attachment_ids = extract_ids(
            json.dumps(
                {
                    "conversation_id": "conversation-id",
                    "message": {
                        "content": {
                            "content_type": "image_asset_pointer",
                            "asset_pointer": "file-service://image_abc123",
                        }
                    },
                }
            )
        )

        self.assertEqual(conversation_id, "conversation-id")
        self.assertEqual(file_ids, [])
        self.assertEqual(attachment_ids, ["image_abc123"])

    def test_openai_backend_image_poll_timeout_includes_conversation_diagnostics(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        backend = OpenAIBackend("access-token", timeout_seconds=60)
        times = iter([1000, 1000, 1000, 1065])

        def fake_time():
            return next(times)

        def fake_get_conversation(conversation_id):
            return {
                "mapping": {
                    "node-1": {
                        "message": {
                            "id": "message-1",
                            "author": {"role": "assistant"},
                            "content": {"content_type": "text", "parts": ["still working"]},
                        }
                    }
                }
            }

        with patch("sidecars.chatgpt_pool.openai_backend.time.time", side_effect=fake_time), patch(
            "sidecars.chatgpt_pool.openai_backend.time.sleep"
        ), patch.object(backend, "_get_conversation", side_effect=fake_get_conversation):
            with self.assertRaisesRegex(Exception, "conversation-id.*polls=1.*assistant_messages=1"):
                backend._poll_image_results("conversation-id")

    def test_web_image_generation_payload_matches_conversation_shape(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, Requirements

        captured = {}

        class FakeResponse:
            status_code = 200
            text = "{}"

            def iter_lines(self, *args, **kwargs):
                return iter(())

        backend = OpenAIBackend("access-token")

        def fake_post(url, headers=None, json=None, timeout=None, stream=False):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["json"] = json or {}
            captured["timeout"] = timeout
            captured["stream"] = stream
            return FakeResponse()

        backend.session.post = fake_post
        response = backend._start_image_generation(
            "draw a poster",
            Requirements(token="requirements-token"),
            "conduit-token",
            "gpt-image-2",
        )

        payload = captured["json"]
        message = payload["messages"][0]
        self.assertIs(response.status_code, 200)
        self.assertEqual(payload["model"], "gpt-5-3")
        self.assertEqual(payload["system_hints"], ["picture_v2"])
        self.assertTrue(payload["enable_message_followups"])
        self.assertEqual(payload["paragen_cot_summary_display_override"], "allow")
        self.assertEqual(payload["force_parallel_switch"], "auto")
        self.assertEqual(message["content"], {"content_type": "text", "parts": ["draw a poster"]})
        self.assertEqual(message["metadata"]["system_hints"], ["picture_v2"])
        self.assertIn("serialization_metadata", message["metadata"])
        self.assertEqual(captured["headers"]["X-Conduit-Token"], "conduit-token")
        self.assertTrue(captured["stream"])
        self.assertIsInstance(captured["timeout"], tuple)
        self.assertEqual(captured["timeout"][0], 30.0)
        self.assertLessEqual(captured["timeout"][1], 120.0)

    def test_openai_backend_image_stream_timeout_falls_back_to_polling_after_conversation_id(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        class FakeResponse:
            status_code = 200
            text = "{}"

            def iter_lines(self, *args, **kwargs):
                yield b'data: {"conversation_id":"conversation-id"}'
                raise requests.exceptions.ReadTimeout("idle stream")

            def close(self):
                pass

        backend = OpenAIBackend("access-token")
        with patch.object(backend, "_bootstrap"), patch.object(
            backend, "_requirements", return_value=object()
        ), patch.object(
            backend, "_prepare_image_conversation", return_value="conduit-token"
        ), patch.object(
            backend, "_start_image_generation", return_value=FakeResponse()
        ), patch.object(
            backend, "_poll_image_results", return_value=(["file-id"], [])
        ) as poll_mock, patch.object(
            backend, "_resolve_image_urls", return_value=["https://example.test/image.png"]
        ), patch.object(
            backend, "_download_image", return_value=b"image-bytes"
        ):
            result = backend.generate_image("draw a poster")

        self.assertEqual(result["b64_json"], base64.b64encode(b"image-bytes").decode("ascii"))
        poll_mock.assert_called_once()
        self.assertEqual(poll_mock.call_args.args[0], "conversation-id")
        self.assertIn("deadline", poll_mock.call_args.kwargs)

    def test_openai_backend_image_finished_without_assets_uses_images_library_fallback(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, UpstreamError

        class FakeResponse:
            status_code = 200
            text = "{}"

            def iter_lines(self, *args, **kwargs):
                yield b'data: {"conversation_id":"conversation-id"}'
                yield b"data: [DONE]"

            def close(self):
                pass

        backend = OpenAIBackend("access-token")
        with patch.object(
            backend,
            "_poll_image_results",
            side_effect=UpstreamError("ChatGPT conversation finished without image output: conversation_id=conversation-id"),
        ) as poll_mock, patch.object(
            backend,
            "_recent_image_library_urls_for_conversation",
            return_value=["https://chatgpt.com/backend-api/estuary/content?id=file_123"],
        ) as library_mock, patch.object(
            backend,
            "_resolve_image_urls",
            side_effect=AssertionError("conversation refs should not be resolved when library URL exists"),
        ), patch.object(
            backend, "_download_image", return_value=b"library-image-bytes"
        ):
            result = backend._result_from_image_response(FakeResponse(), "draw a poster")

        self.assertEqual(result["b64_json"], base64.b64encode(b"library-image-bytes").decode("ascii"))
        poll_mock.assert_called_once()
        library_mock.assert_called_once()
        self.assertEqual(library_mock.call_args.args[0], "conversation-id")

    def test_openai_backend_extracts_images_library_estuary_urls_for_conversation(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend

        backend = OpenAIBackend("access-token")
        pages = [
            {
                "items": [
                    {
                        "conversation_id": "other-conversation",
                        "created_at": 2100,
                        "url": "https://chatgpt.com/backend-api/estuary/content?id=file_other",
                    },
                    {
                        "conversation_id": "conversation-id",
                        "created_at": 2001,
                        "url": "https://chatgpt.com/backend-api/estuary/content?id=file_recent",
                        "encodings": {
                            "thumbnail": {
                                "path": "https://chatgpt.com/backend-api/estuary/content?id=thumb%23file_recent%23thumbnail"
                            }
                        },
                    },
                    {
                        "conversation_id": "conversation-id",
                        "created_at": 1000,
                        "url": "https://chatgpt.com/backend-api/estuary/content?id=file_old",
                    },
                ],
                "cursor": "",
            }
        ]

        with patch.object(backend, "_get_recent_image_generation_items", side_effect=pages) as recent_mock:
            urls = backend._recent_image_library_urls_for_conversation("conversation-id", started_at=2000)

        self.assertEqual(urls[0], "https://chatgpt.com/backend-api/estuary/content?id=file_recent")
        self.assertIn("https://chatgpt.com/backend-api/estuary/content?id=thumb%23file_recent%23thumbnail", urls)
        self.assertNotIn("https://chatgpt.com/backend-api/estuary/content?id=file_old", urls)
        recent_mock.assert_called_once()

    def test_openai_backend_image_stream_timeout_before_conversation_id_fails_fast(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, UpstreamError

        class FakeResponse:
            status_code = 200
            text = "{}"

            def iter_lines(self, *args, **kwargs):
                raise requests.exceptions.ReadTimeout("idle stream")

            def close(self):
                pass

        backend = OpenAIBackend("access-token")
        with patch.object(backend, "_bootstrap"), patch.object(
            backend, "_requirements", return_value=object()
        ), patch.object(
            backend, "_prepare_image_conversation", return_value="conduit-token"
        ), patch.object(
            backend, "_start_image_generation", return_value=FakeResponse()
        ):
            with self.assertRaisesRegex(UpstreamError, "before the stream produced a conversation id"):
                backend.generate_image("draw a poster")

    def test_openai_backend_image_poll_fails_when_conversation_finished_without_assets(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, UpstreamError

        backend = OpenAIBackend("access-token", timeout_seconds=60)

        def fake_get_conversation(conversation_id):
            return {
                "mapping": {
                    "node-1": {
                        "message": {
                            "id": "message-1",
                            "status": "finished_successfully",
                            "author": {"role": "assistant"},
                            "content": {"content_type": "text", "parts": ["I can only answer in text here."]},
                        }
                    }
                }
            }

        with patch.object(backend, "_get_conversation", side_effect=fake_get_conversation):
            with self.assertRaisesRegex(UpstreamError, "finished without image output.*conversation-id"):
                backend._poll_image_results("conversation-id")

    def test_openai_backend_image_poll_includes_system_error_detail(self):
        from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, UpstreamError

        backend = OpenAIBackend("access-token", timeout_seconds=60)

        def fake_get_conversation(conversation_id):
            return {
                "mapping": {
                    "node-1": {
                        "message": {
                            "id": "message-1",
                            "status": "finished_successfully",
                            "author": {"role": "assistant"},
                            "content": {"content_type": "code", "parts": ["{}"]},
                        }
                    },
                    "node-2": {
                        "message": {
                            "id": "message-2",
                            "status": "finished_successfully",
                            "author": {"role": "tool", "name": "image_tool"},
                            "content": {
                                "content_type": "system_error",
                                "name": "RPCError",
                                "text": "Encountered exception: temporalio.service.RPCError",
                            },
                        }
                    },
                }
            }

        with patch.object(backend, "_get_conversation", side_effect=fake_get_conversation):
            with self.assertRaisesRegex(UpstreamError, "system_error=RPCError"):
                backend._poll_image_results("conversation-id")


if __name__ == "__main__":
    unittest.main()
