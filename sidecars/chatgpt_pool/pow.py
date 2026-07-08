from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Sequence

from .utils import new_uuid


DEFAULT_POW_SCRIPT = "https://chatgpt.com/backend-api/sentinel/sdk.js"


class ScriptSrcParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.script_sources: list[str] = []
        self.data_build = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attrs_dict = dict(attrs)
        src = attrs_dict.get("src")
        if not src:
            return
        self.script_sources.append(src)
        match = re.search(r"c/[^/]*/_", src)
        if match:
            self.data_build = match.group(0)


def parse_pow_resources(html_content: str) -> tuple[list[str], str]:
    parser = ScriptSrcParser()
    parser.feed(html_content or "")
    return parser.script_sources or [DEFAULT_POW_SCRIPT], parser.data_build


def _legacy_parse_time() -> str:
    now = datetime.now(timezone(timedelta(hours=-5)))
    return now.strftime("%a %b %d %Y %H:%M:%S") + " GMT-0500 (Eastern Standard Time)"


def _pow_config(user_agent: str, script_sources: Sequence[str] | None, data_build: str) -> list[Any]:
    return [
        3000,
        _legacy_parse_time(),
        4294705152,
        0,
        user_agent,
        random.choice(list(script_sources or [DEFAULT_POW_SCRIPT])),
        data_build,
        "zh-CN",
        "zh-CN,zh,en-US,en",
        0,
        "webdriver−false",
        "location",
        "document",
        time.perf_counter() * 1000,
        new_uuid(),
        "",
        16,
        time.time() * 1000 - (time.perf_counter() * 1000),
    ]


def _pow_generate(seed: str, difficulty: str, config: list[Any], limit: int = 200000) -> tuple[str, bool]:
    target = bytes.fromhex(difficulty)
    diff_len = len(difficulty) // 2
    seed_bytes = seed.encode()
    for i in range(limit):
        config[3] = i
        config[9] = i >> 1
        encoded = base64.b64encode(json.dumps(config, separators=(",", ":"), ensure_ascii=False).encode())
        digest = hashlib.sha3_512(seed_bytes + encoded).digest()
        if digest[:diff_len] <= target:
            return encoded.decode(), True
    fallback = base64.b64encode(f'"{seed}"'.encode()).decode()
    return fallback, False


def build_legacy_requirements_token(user_agent: str, script_sources: Sequence[str] | None = None, data_build: str = "") -> str:
    seed = format(random.random())
    answer, _ = _pow_generate(seed, "0fffff", _pow_config(user_agent, script_sources, data_build))
    return "gAAAAAC" + answer


def build_proof_token(seed: str, difficulty: str, user_agent: str, script_sources: Sequence[str] | None = None, data_build: str = "") -> str:
    answer, solved = _pow_generate(seed, difficulty, _pow_config(user_agent, script_sources, data_build))
    if not solved:
        raise RuntimeError(f"failed to solve proof token: difficulty={difficulty}")
    return "gAAAAAB" + answer

