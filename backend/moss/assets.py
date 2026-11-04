"""Pinned MOSS asset manifest; data only, no filesystem state beyond the shipped lock."""
from __future__ import annotations

import json
from pathlib import Path

LOCK_PATH = Path(__file__).with_name("assets.lock.json")


def load_lock():
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def managed_sha256():
    """Hashes of adapters that presets own and the ordinary library must refuse."""
    return frozenset(item["sha256"] for item in load_lock()["managed"].values())
