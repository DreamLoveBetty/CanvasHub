from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .utils import (
    account_id_for_token,
    decode_jwt_payload,
    ensure_parent,
    extract_email,
    extract_plan,
    iso_from_timestamp,
    jwt_exp,
    now_iso,
    token_preview,
)


NORMAL_STATUS = "正常"
LIMITED_STATUS = "限流"
DISABLED_STATUS = "禁用"
ERROR_STATUS = "异常"
VERIFICATION_STATUS = "需要验证"


class AccountStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).expanduser()
        ensure_parent(self.db_path)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    access_token TEXT PRIMARY KEY,
                    refresh_token TEXT NOT NULL DEFAULT '',
                    id_token TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    plan_type TEXT NOT NULL DEFAULT 'unknown',
                    status TEXT NOT NULL DEFAULT '正常',
                    quota INTEGER NOT NULL DEFAULT 0,
                    image_quota_unknown INTEGER NOT NULL DEFAULT 1,
                    restore_at TEXT NOT NULL DEFAULT '',
                    expires_at INTEGER NOT NULL DEFAULT 0,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    last_used_at TEXT NOT NULL DEFAULT '',
                    last_refresh_at TEXT NOT NULL DEFAULT '',
                    last_refresh_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 0,
                    fail INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    @staticmethod
    def _explicit_or_current(item: dict[str, Any], current: dict[str, Any], key: str, default: Any = "") -> Any:
        return item[key] if key in item else current.get(key, default)

    @staticmethod
    def _normalize_account(item: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any] | None:
        access_token = str(item.get("access_token") or item.get("accessToken") or "").strip()
        if not access_token:
            return None
        current = current or {}
        id_token = str(item.get("id_token") or item.get("idToken") or current.get("id_token") or "").strip()
        refresh_token = str(item.get("refresh_token") or item.get("refreshToken") or current.get("refresh_token") or "").strip()
        access_payload = decode_jwt_payload(access_token)
        auth_claim = access_payload.get("https://api.openai.com/auth")
        auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
        profile_claim = access_payload.get("https://api.openai.com/profile")
        profile_claim = profile_claim if isinstance(profile_claim, dict) else {}
        exp = jwt_exp(access_token) or int(current.get("expires_at") or 0)
        plan_type = extract_plan(access_token, str(item.get("plan_type") or item.get("type") or ""))
        if plan_type.lower() in {"unknown", "none", "null"}:
            current_plan = str(current.get("plan_type") or "").strip()
            if current_plan and current_plan.lower() not in {"unknown", "none", "null"}:
                plan_type = current_plan
        now = now_iso()
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "email": extract_email(access_token, id_token, str(item.get("email") or current.get("email") or "")),
            "user_id": str(item.get("user_id") or current.get("user_id") or profile_claim.get("id") or "").strip(),
            "plan_type": plan_type,
            "status": str(item.get("status") or current.get("status") or NORMAL_STATUS).strip() or NORMAL_STATUS,
            "quota": max(0, int(item.get("quota") if item.get("quota") is not None else current.get("quota") or 0)),
            "image_quota_unknown": 1 if item.get("image_quota_unknown", current.get("image_quota_unknown", True)) else 0,
            "restore_at": str(AccountStore._explicit_or_current(item, current, "restore_at", "") or "").strip(),
            "expires_at": exp,
            "source_type": str(item.get("source_type") or current.get("source_type") or "manual").strip() or "manual",
            "last_used_at": str(item.get("last_used_at") or current.get("last_used_at") or "").strip(),
            "last_refresh_at": str(item.get("last_refresh_at") or current.get("last_refresh_at") or "").strip(),
            "last_refresh_error": str(AccountStore._explicit_or_current(item, current, "last_refresh_error", "") or "").strip(),
            "created_at": str(current.get("created_at") or item.get("created_at") or now),
            "updated_at": now,
            "success": int(item.get("success") if item.get("success") is not None else current.get("success") or 0),
            "fail": int(item.get("fail") if item.get("fail") is not None else current.get("fail") or 0),
        }

    def _get_private_locked(self, conn: sqlite3.Connection, access_token: str) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM accounts WHERE access_token = ?", (access_token,)).fetchone()
        return dict(row) if row else None

    def upsert_accounts(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        added = 0
        skipped = 0
        with self._lock, self._db() as conn:
            for item in items:
                token = str((item or {}).get("access_token") or (item or {}).get("accessToken") or "").strip()
                if not token:
                    continue
                current = self._get_private_locked(conn, token)
                normalized = self._normalize_account(item, current)
                if normalized is None:
                    continue
                if current:
                    skipped += 1
                else:
                    added += 1
                keys = list(normalized)
                placeholders = ",".join("?" for _ in keys)
                updates = ",".join(f"{key}=excluded.{key}" for key in keys if key != "access_token")
                conn.execute(
                    f"INSERT INTO accounts ({','.join(keys)}) VALUES ({placeholders}) "
                    f"ON CONFLICT(access_token) DO UPDATE SET {updates}",
                    [normalized[key] for key in keys],
                )
            conn.commit()
        return {"added": added, "skipped": skipped, "items": self.list_public_accounts()}

    def apply_refreshed_tokens(self, old_access_token: str, token_data: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock, self._db() as conn:
            current = self._get_private_locked(conn, old_access_token)
            if current is None:
                return None
            new_access = str(token_data.get("access_token") or old_access_token).strip()
            merged = {
                **current,
                "access_token": new_access,
                "refresh_token": str(token_data.get("refresh_token") or current.get("refresh_token") or ""),
                "id_token": str(token_data.get("id_token") or current.get("id_token") or ""),
                "last_refresh_at": now_iso(),
                "last_refresh_error": "",
            }
            normalized = self._normalize_account(merged, current)
            if normalized is None:
                return None
            if new_access != old_access_token:
                conn.execute("DELETE FROM accounts WHERE access_token = ?", (old_access_token,))
            keys = list(normalized)
            placeholders = ",".join("?" for _ in keys)
            updates = ",".join(f"{key}=excluded.{key}" for key in keys if key != "access_token")
            conn.execute(
                f"INSERT INTO accounts ({','.join(keys)}) VALUES ({placeholders}) "
                f"ON CONFLICT(access_token) DO UPDATE SET {updates}",
                [normalized[key] for key in keys],
            )
            conn.commit()
        return self.public_account(new_access)

    def record_refresh_error(self, access_token: str, error: str) -> None:
        with self._lock, self._db() as conn:
            conn.execute(
                "UPDATE accounts SET last_refresh_error = ?, updated_at = ? WHERE access_token = ?",
                (str(error or "")[:600], now_iso(), access_token),
            )
            conn.commit()

    def update_account(self, access_token: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        access_token = self.resolve_access_token(access_token)
        allowed = {
            key: updates[key]
            for key in (
                "status",
                "quota",
                "restore_at",
                "image_quota_unknown",
                "plan_type",
                "user_id",
                "email",
                "last_refresh_error",
            )
            if key in updates
        }
        if not allowed:
            return self.public_account(access_token)
        with self._lock, self._db() as conn:
            current = self._get_private_locked(conn, access_token)
            if current is None:
                return None
            next_item = self._normalize_account({**current, **allowed}, current)
            if next_item is None:
                return None
            assignments = ",".join(f"{key}=?" for key in next_item if key != "access_token")
            conn.execute(
                f"UPDATE accounts SET {assignments} WHERE access_token = ?",
                [next_item[key] for key in next_item if key != "access_token"] + [access_token],
            )
            conn.commit()
        return self.public_account(access_token)

    def delete_accounts(self, tokens: list[str]) -> dict[str, Any]:
        clean = []
        for token in tokens:
            resolved = self.resolve_access_token(str(token or "").strip())
            if resolved:
                clean.append(resolved)
        with self._lock, self._db() as conn:
            removed = 0
            for token in clean:
                cur = conn.execute("DELETE FROM accounts WHERE access_token = ?", (token,))
                removed += cur.rowcount or 0
            conn.commit()
        return {"removed": removed, "items": self.list_public_accounts()}

    def get_private_account(self, access_token: str) -> dict[str, Any] | None:
        with self._lock, self._db() as conn:
            return self._get_private_locked(conn, access_token)

    def resolve_access_token(self, token_or_account_id: str) -> str:
        value = str(token_or_account_id or "").strip()
        if not value:
            return ""
        if self.get_private_account(value):
            return value
        with self._lock, self._db() as conn:
            for row in conn.execute("SELECT access_token FROM accounts"):
                token = str(row["access_token"] or "")
                if account_id_for_token(token) == value:
                    return token
        return value

    def list_private_accounts(self) -> list[dict[str, Any]]:
        with self._lock, self._db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM accounts ORDER BY created_at ASC, email ASC")]

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        exp = int(row.get("expires_at") or 0)
        return {
            "account_id": account_id_for_token(str(row.get("access_token") or "")),
            "token_preview": token_preview(str(row.get("access_token") or "")),
            "email": row.get("email") or "",
            "user_id": row.get("user_id") or "",
            "type": row.get("plan_type") or "unknown",
            "plan_type": row.get("plan_type") or "unknown",
            "status": row.get("status") or NORMAL_STATUS,
            "quota": int(row.get("quota") or 0),
            "image_quota_unknown": bool(row.get("image_quota_unknown")),
            "restore_at": row.get("restore_at") or "",
            "expires_at": exp,
            "expires_at_iso": iso_from_timestamp(exp),
            "source_type": row.get("source_type") or "manual",
            "has_refresh_token": bool(row.get("refresh_token")),
            "success": int(row.get("success") or 0),
            "fail": int(row.get("fail") or 0),
            "last_used_at": row.get("last_used_at") or "",
            "last_refresh_at": row.get("last_refresh_at") or "",
            "last_refresh_error": row.get("last_refresh_error") or "",
        }

    def public_account(self, access_token: str) -> dict[str, Any] | None:
        row = self.get_private_account(access_token)
        return self._public(row) if row else None

    def list_public_accounts(self) -> list[dict[str, Any]]:
        return [self._public(row) for row in self.list_private_accounts()]

    def record_result(self, access_token: str, success: bool, error: str = "") -> None:
        with self._lock, self._db() as conn:
            current = self._get_private_locked(conn, access_token)
            if current is None:
                return
            quota_unknown = bool(current.get("image_quota_unknown"))
            quota = int(current.get("quota") or 0)
            status = str(current.get("status") or NORMAL_STATUS)
            if success:
                quota = quota if quota_unknown else max(0, quota - 1)
                if not quota_unknown and quota == 0:
                    status = LIMITED_STATUS
            conn.execute(
                """
                UPDATE accounts
                SET success = success + ?, fail = fail + ?, quota = ?, status = ?,
                    last_used_at = ?, last_refresh_error = ?, updated_at = ?
                WHERE access_token = ?
                """,
                (1 if success else 0, 0 if success else 1, quota, status, now_iso(), "" if success else str(error or "")[:600], now_iso(), access_token),
            )
            conn.commit()

    def stats(self) -> dict[str, Any]:
        rows = self.list_private_accounts()
        return {
            "total": len(rows),
            "active": sum(1 for row in rows if row.get("status") == NORMAL_STATUS),
            "limited": sum(1 for row in rows if row.get("status") == LIMITED_STATUS),
            "disabled": sum(1 for row in rows if row.get("status") == DISABLED_STATUS),
            "abnormal": sum(1 for row in rows if row.get("status") == ERROR_STATUS),
            "verification_required": sum(1 for row in rows if row.get("status") == VERIFICATION_STATUS),
            "refreshable": sum(1 for row in rows if row.get("refresh_token")),
            "total_quota": sum(int(row.get("quota") or 0) for row in rows if row.get("status") == NORMAL_STATUS),
        }
