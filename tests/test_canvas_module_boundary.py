"""Stable boundary contract for the desktop canvas modules split out of desktop-canvas.js.

The module set is derived from the files on disk, so adding a module needs no edit here:
every desktop-canvas-*.js must load once, before the host, as a synchronous classic
script, publish exactly one window.DesktopCanvas<Name> factory namespace used only by the
host, and never reach back into the host's window.DesktopCanvas API.
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
SCRIPTS = FRONTEND / "scripts"
HOST = "scripts/desktop-canvas.js"


class ScriptParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs)


def module_paths():
    return sorted(f"scripts/{path.name}" for path in SCRIPTS.glob("desktop-canvas-*.js"))


class CanvasModuleBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.scripts = ScriptParser((FRONTEND / "desktop.html").read_text(encoding="utf-8")).scripts
        self.paths = [urlsplit(attrs["src"]).path for attrs in self.scripts]
        self.modules = module_paths()
        self.host = (SCRIPTS / "desktop-canvas.js").read_text(encoding="utf-8")

    def test_every_module_on_disk_is_loaded_once_and_nothing_else(self):
        self.assertGreater(len(self.modules), 20)
        loaded = [path for path in self.paths if path.startswith("scripts/desktop-canvas")]
        self.assertCountEqual(loaded, self.modules + [HOST])
        for path in self.modules + [HOST]:
            with self.subTest(script=path):
                self.assertEqual(self.paths.count(path), 1)

    def test_scripts_are_local_synchronous_classic_scripts_with_cache_keys(self):
        for path in self.modules + [HOST]:
            with self.subTest(script=path):
                attrs = self.scripts[self.paths.index(path)]
                for flag in ("async", "defer", "nomodule"):
                    self.assertNotIn(flag, attrs)
                self.assertIn(attrs.get("type", "").strip().lower(), ("", "text/javascript", "application/javascript"))
                src = urlsplit(attrs["src"])
                self.assertFalse(src.scheme or src.netloc or src.fragment)
                self.assertTrue((FRONTEND / src.path).resolve().is_relative_to(FRONTEND.resolve()))
                versions = parse_qs(src.query, keep_blank_values=True).get("v", [])
                self.assertEqual(len(versions), 1)
                self.assertRegex(versions[0], r"^[0-9A-Za-z._-]+$")

    def test_load_order_around_the_host(self):
        host_at = self.paths.index(HOST)
        for path in self.modules:
            self.assertLess(self.paths.index(path), host_at, f"{path} must load before the host")
        first_module = min(self.paths.index(path) for path in self.modules)
        self.assertLess(self.paths.index("scripts/desktop-state.js"), first_module)
        for prerequisite in ("scripts/desktop-api.js", "scripts/desktop-audio-assets.js"):
            self.assertEqual(self.paths.count(prerequisite), 1)
            self.assertLess(self.paths.index(prerequisite), host_at)
        self.assertLess(self.paths.index("scripts/desktop-audio-assets.js"), self.paths.index("scripts/desktop-canvas-audio.js"))
        self.assertEqual(self.paths.count("scripts/desktop-bootstrap.js"), 1)
        self.assertLess(host_at, self.paths.index("scripts/desktop-bootstrap.js"))

    def test_each_module_publishes_one_namespace_that_only_the_host_assembles(self):
        others = {path.name: path.read_text(encoding="utf-8") for path in SCRIPTS.glob("*.js")}
        for path in self.modules:
            name = Path(path).name
            source = others[name]
            with self.subTest(module=name):
                self.assertTrue(source.lstrip().startswith(("(function", "//", "/*", "'use strict'", '"use strict"')), "module must be an IIFE")
                published = set(re.findall(r"window\.(DesktopCanvas[A-Z]\w*)\s*=", source))
                self.assertEqual(len(published), 1, published)
                (namespace,) = published
                stem = name[len("desktop-canvas-"):-len(".js")]
                self.assertEqual(namespace.lower(), "desktopcanvas" + stem.replace("-", ""))
                self.assertRegex(self.host, r"\b" + namespace + r"\b", "the host must assemble it")
                users = sorted(other for other, text in others.items()
                               if other not in (name, "desktop-canvas.js") and re.search(r"\b" + namespace + r"\b", text))
                self.assertEqual(users, [], f"{namespace} is used outside the host")
                # No reverse dependency on the host's public API.
                self.assertNotRegex(source, r"\bDesktopCanvas\.")

    def test_mobile_entry_does_not_load_desktop_canvas(self):
        for attrs in ScriptParser((FRONTEND / "index.html").read_text(encoding="utf-8")).scripts:
            self.assertNotIn("desktop-canvas", urlsplit(attrs["src"]).path)

    def test_comment_with_script_markup_is_not_a_loaded_script(self):
        markup = '<!-- <script src="scripts/desktop-canvas-generation.js?v=fake"></script> -->'
        self.assertEqual(ScriptParser(markup).scripts, [])


if __name__ == "__main__":
    unittest.main()
