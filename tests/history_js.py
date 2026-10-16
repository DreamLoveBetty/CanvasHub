"""desktop-history.js plus the history and gallery modules split out of it.

The history panel and gallery workspace started as one classic script. Engines and
gallery tabs that moved to their own scripts (desktop-genie-fx.js, desktop-gallery-*.js)
load before desktop-history.js. Tests that pin that source read them together, in
desktop.html load order, so an assertion keeps passing wherever the split put the code.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
HOST = "desktop-history.js"
SCRIPT = re.compile(r'<script src="scripts/(desktop-genie-fx\.js|desktop-gallery-[\w-]+\.js|desktop-history\.js)\?')


def history_js_files():
    html = (FRONTEND / "desktop.html").read_text(encoding="utf-8")
    names = SCRIPT.findall(html)
    if names.count(HOST) != 1 or names[-1] != HOST:
        raise AssertionError(f"history modules must load once, before {HOST}: {names}")
    return [FRONTEND / "scripts" / name for name in names]


def read_history_js():
    return "\n".join(path.read_text(encoding="utf-8") for path in history_js_files())
