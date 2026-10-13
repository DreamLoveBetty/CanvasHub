"""desktop-liquid.css plus the legacy domain stylesheets split out of it.

The legacy desktop styles live in desktop-liquid.css and the desktop-legacy-*.css files
loaded right after it. Tests that pin legacy rules read them together, in desktop.html
load order, so a rule keeps passing wherever the legacy split put it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def legacy_css_files():
    html = (FRONTEND / "desktop.html").read_text(encoding="utf-8")
    names = re.findall(r'href="styles/(desktop-(?:liquid|legacy-[\w-]+)\.css)\?', html)
    return [FRONTEND / "styles" / name for name in names]


def read_legacy_css():
    return "\n".join(path.read_text(encoding="utf-8") for path in legacy_css_files())
