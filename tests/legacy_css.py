"""desktop-liquid.css plus the legacy domain stylesheets split out of it.

The legacy desktop styles live in desktop-liquid.css, the desktop-legacy-*.css files
loaded right after it, and the desktop-<domain>-geometry.css files a migrated domain's
live legacy rules moved to (desktop-geometry.css itself is a module, not one of them).
Tests that pin legacy rules read them together, in desktop.html load order, so a rule
keeps passing wherever the split or the migration put it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def legacy_css_files():
    html = (FRONTEND / "desktop.html").read_text(encoding="utf-8")
    names = re.findall(r'href="styles/(desktop-(?:liquid|legacy-[\w-]+|[\w-]+-geometry)\.css)\?', html)
    return [FRONTEND / "styles" / name for name in names]


def read_legacy_css():
    return "\n".join(path.read_text(encoding="utf-8") for path in legacy_css_files())
