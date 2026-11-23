"""Category nav group titles must not be smaller than their child items.

Settings and the prompt library share the same hierarchy: titles use the body
token, stay semibold, and rely on weight and spacing rather than shrinking
the type. Child item sizes are left unchanged so the narrow nav does not grow.
Child items indent from the title by a start-side padding increment, keeping
full-width hit targets and trailing status marks.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "frontend" / "styles"
TOKENS = (STYLES / "desktop-tokens.css").read_text(encoding="utf-8")
GEOMETRY = (STYLES / "desktop-geometry.css").read_text(encoding="utf-8")
PROMPT = (STYLES / "desktop-prompt-library.css").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "desktop.html").read_text(encoding="utf-8")
PROMPT_JS = (ROOT / "frontend" / "scripts" / "desktop-prompt-library.js").read_text(encoding="utf-8")

SETTINGS_TITLE = "body.desk-app[data-theme] .desk-settings-tabs__group-label"
SETTINGS_ITEM = "body.desk-app[data-theme] .desk-settings-tabs button"
PROMPT_TITLE = ".desk-prompt-library__nav-label"
PROMPT_ITEM = ".desk-prompt-library__nav button"
TITLE_TOKEN = "--desk-font-size-body"
INDENT_TOKEN = "--desk-space-4"
INDENT_MIN_PX = 8
INDENT_MAX_PX = 12


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _token_px(*sources, name):
    for source in sources:
        match = re.search(rf"{re.escape(name)}:\s*([^;]+);", source)
        if not match:
            continue
        value = match.group(1).strip()
        if value.endswith("px"):
            return float(value[:-2])
        if value.startswith("var("):
            inner = value[4:-1].strip()
            return _token_px(*sources, name=inner)
    raise AssertionError(f"unresolved typography token: {name}")


def _iter_rules(css):
    for match in re.finditer(r"([^{}]+)\{([^{}]+)\}", _strip_comments(css)):
        prelude = match.group(1).strip()
        prelude = re.sub(r"@(?:media|supports)[^{]+", "", prelude, flags=re.I).strip()
        selectors = [item.strip() for item in prelude.split(",") if item.strip()]
        yield selectors, match.group(2), match.start()


def _declarations(body):
    decls = {}
    for item in body.split(";"):
        if ":" not in item:
            continue
        prop, value = item.split(":", 1)
        decls[prop.strip()] = value.strip()
    return decls


def _decl_list(body):
    decls = []
    for item in body.split(";"):
        if ":" not in item:
            continue
        prop, value = item.split(":", 1)
        decls.append((prop.strip(), value.strip()))
    return decls


def _font_size_token(css, selector):
    last = None
    for selectors, body, _ in _iter_rules(css):
        if selector in selectors:
            size = _declarations(body).get("font-size")
            if size:
                last = size
    if not last:
        raise AssertionError(f"no font-size for {selector}")
    return last


def _token_name(value):
    match = re.fullmatch(r"var\((--[^)]+)\)", value)
    if not match:
        raise AssertionError(f"expected a typography token, got {value}")
    return match.group(1)


def _resolved_px(value):
    return _token_px(TOKENS, GEOMETRY, name=_token_name(value))


def _weight_token(css, selector):
    last = None
    for selectors, body, _ in _iter_rules(css):
        if selector in selectors:
            weight = _declarations(body).get("font-weight")
            if weight:
                last = weight
    if not last:
        raise AssertionError(f"no font-weight for {selector}")
    return last


def _later_title_sizes(css, selector):
    found = []
    for selectors, body, start in _iter_rules(css):
        if selector in selectors:
            size = _declarations(body).get("font-size")
            if size:
                found.append((start, size))
    return found


def _css_tokens(value):
    tokens = []
    buf = []
    depth = 0
    for char in value.strip():
        if char == "(":
            depth += 1
            buf.append(char)
        elif char == ")":
            depth -= 1
            buf.append(char)
        elif char.isspace() and depth == 0:
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(char)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _length_px(value, sources=(TOKENS, GEOMETRY, PROMPT)):
    value = value.strip()
    if value.endswith("px"):
        return float(value[:-2])
    if value.startswith("var(") and value.endswith(")"):
        inner = value[4:-1].strip().split(",", 1)[0].strip()
        return _token_px(*sources, name=inner)
    if value.startswith("calc(") and value.endswith(")"):
        inner = value[5:-1].strip()
        parts = re.split(r"\s*\+\s*", inner)
        if len(parts) < 2:
            raise AssertionError(f"unsupported calc(): {value}")
        return sum(_length_px(part, sources) for part in parts)
    raise AssertionError(f"unresolved length: {value}")


def _expand_padding(value):
    tokens = _css_tokens(value)
    if len(tokens) == 1:
        top = right = bottom = left = tokens[0]
    elif len(tokens) == 2:
        top = bottom = tokens[0]
        right = left = tokens[1]
    elif len(tokens) == 3:
        top, right, bottom = tokens
        left = right
    elif len(tokens) == 4:
        top, right, bottom, left = tokens
    else:
        raise AssertionError(f"unexpected padding shorthand: {value}")
    return {"top": top, "right": right, "bottom": bottom, "left": left}


def _logical_padding(css, selector):
    box = {"top": "0", "right": "0", "bottom": "0", "left": "0"}
    inline_start = None
    inline_end = None
    found = False
    for selectors, body, _ in _iter_rules(css):
        if selector not in selectors:
            continue
        for prop, value in _decl_list(body):
            if prop == "padding":
                box.update(_expand_padding(value))
                inline_start = None
                inline_end = None
                found = True
            elif prop == "padding-top":
                box["top"] = value
                found = True
            elif prop == "padding-right":
                box["right"] = value
                found = True
            elif prop == "padding-bottom":
                box["bottom"] = value
                found = True
            elif prop == "padding-left":
                box["left"] = value
                found = True
            elif prop == "padding-inline":
                parts = _css_tokens(value)
                if len(parts) == 1:
                    inline_start = inline_end = parts[0]
                elif len(parts) == 2:
                    inline_start, inline_end = parts
                else:
                    raise AssertionError(f"unexpected padding-inline: {value}")
                found = True
            elif prop == "padding-inline-start":
                inline_start = value
                found = True
            elif prop == "padding-inline-end":
                inline_end = value
                found = True
    if not found:
        raise AssertionError(f"no padding for {selector}")
    start = inline_start if inline_start is not None else box["left"]
    end = inline_end if inline_end is not None else box["right"]
    return start, end


def _selector_targets(selectors, needle):
    for selector in selectors:
        compact = re.sub(r"\s+", " ", selector)
        if needle in compact and f"{needle}__" not in compact:
            return True
    return False


def _padding_overrides(css, needle):
    found = []
    for selectors, body, start in _iter_rules(css):
        if not _selector_targets(selectors, needle):
            continue
        decls = {
            prop: value
            for prop, value in _decl_list(body)
            if prop in {
                "padding",
                "padding-left",
                "padding-right",
                "padding-inline",
                "padding-inline-start",
                "padding-inline-end",
            }
        }
        if decls:
            found.append((start, selectors, decls))
    return found


class NavGroupTitleTypeTest(unittest.TestCase):
    def test_settings_and_prompt_titles_share_the_body_token_and_outsize_items(self):
        settings_title = _font_size_token(GEOMETRY, SETTINGS_TITLE)
        settings_item = _font_size_token(GEOMETRY, SETTINGS_ITEM)
        prompt_title = _font_size_token(PROMPT, PROMPT_TITLE)
        prompt_item = _font_size_token(PROMPT, PROMPT_ITEM)

        self.assertEqual(_token_name(settings_title), TITLE_TOKEN)
        self.assertEqual(_token_name(prompt_title), TITLE_TOKEN)
        self.assertEqual(_token_name(settings_item), "--desk-settings-control-font")
        self.assertEqual(_token_name(prompt_item), "--desk-font-size-caption")

        title_px = _resolved_px(settings_title)
        settings_item_px = _resolved_px(settings_item)
        prompt_title_px = _resolved_px(prompt_title)
        prompt_item_px = _resolved_px(prompt_item)

        self.assertEqual(title_px, prompt_title_px)
        self.assertGreaterEqual(title_px, settings_item_px)
        self.assertLessEqual(title_px - settings_item_px, 2)
        self.assertGreaterEqual(prompt_title_px, prompt_item_px)
        self.assertEqual(title_px, 13)
        self.assertEqual(settings_item_px, 11.5)
        self.assertEqual(prompt_item_px, 11.5)

        self.assertEqual(_weight_token(GEOMETRY, SETTINGS_TITLE), "var(--desk-font-weight-semibold)")
        self.assertEqual(_weight_token(PROMPT, PROMPT_TITLE), "var(--desk-font-weight-semibold)")
        self.assertEqual(_weight_token(GEOMETRY, SETTINGS_ITEM), "var(--desk-font-weight-medium)")

    def test_theme_and_narrow_rules_do_not_shrink_titles_below_items(self):
        settings_item_px = _resolved_px(_font_size_token(GEOMETRY, SETTINGS_ITEM))
        prompt_item_px = _resolved_px(_font_size_token(PROMPT, PROMPT_ITEM))
        for path in sorted(STYLES.glob("*.css")):
            css = path.read_text(encoding="utf-8")
            for selector, floor in (
                (SETTINGS_TITLE, settings_item_px),
                (PROMPT_TITLE, prompt_item_px),
            ):
                for _, value in _later_title_sizes(css, selector):
                    if value.startswith("var("):
                        self.assertGreaterEqual(_resolved_px(value), floor, f"{path.name}: {selector}")
                    elif value.endswith("px"):
                        self.assertGreaterEqual(float(value[:-2]), floor, f"{path.name}: {selector}")
                    else:
                        self.fail(f"{path.name}: unexpected title size {value}")


class NavGroupChildIndentTest(unittest.TestCase):
    def test_child_items_indent_from_titles_by_space_4_on_both_panels(self):
        indent_px = _token_px(TOKENS, name=INDENT_TOKEN)
        self.assertEqual(indent_px, 8)

        cases = (
            ("settings", GEOMETRY, SETTINGS_TITLE, SETTINGS_ITEM),
            ("prompt", PROMPT, PROMPT_TITLE, PROMPT_ITEM),
        )
        deltas = []
        for name, css, title_sel, item_sel in cases:
            title_start, title_end = _logical_padding(css, title_sel)
            item_start, item_end = _logical_padding(css, item_sel)
            title_start_px = _length_px(title_start)
            item_start_px = _length_px(item_start)
            item_end_px = _length_px(item_end)
            delta = item_start_px - title_start_px
            deltas.append(delta)
            self.assertEqual(title_start_px, 8, name)
            self.assertEqual(title_end, "8px", name)
            self.assertEqual(item_end_px, 8, name)
            self.assertGreaterEqual(delta, INDENT_MIN_PX, name)
            self.assertLessEqual(delta, INDENT_MAX_PX, name)
            self.assertEqual(delta, indent_px, name)
            self.assertIn(INDENT_TOKEN, item_start, name)
            self.assertNotIn("  ", item_start.replace("calc(", ""), name)

        self.assertEqual(deltas[0], deltas[1])

        settings_item_rule = None
        prompt_item_rule = None
        for selectors, body, _ in _iter_rules(GEOMETRY):
            if SETTINGS_ITEM in selectors:
                settings_item_rule = body
        for selectors, body, _ in _iter_rules(PROMPT):
            if PROMPT_ITEM in selectors:
                prompt_item_rule = body
        self.assertIsNotNone(settings_item_rule)
        self.assertIsNotNone(prompt_item_rule)
        self.assertIn("width: 100%", settings_item_rule)
        self.assertIn("width: 100%", prompt_item_rule)
        self.assertNotIn("margin-inline-start", settings_item_rule)
        self.assertNotIn("margin-inline-start", prompt_item_rule)
        self.assertNotIn("margin-left", settings_item_rule)
        self.assertNotIn("margin-left", prompt_item_rule)

    def test_theme_and_narrow_rules_do_not_flatten_child_indent(self):
        expected = _token_px(TOKENS, name=INDENT_TOKEN)
        title_starts = {
            ".desk-settings-tabs__group-label": _length_px(_logical_padding(GEOMETRY, SETTINGS_TITLE)[0]),
            ".desk-prompt-library__nav-label": _length_px(_logical_padding(PROMPT, PROMPT_TITLE)[0]),
        }
        item_needles = (
            (".desk-settings-tabs button", ".desk-settings-tabs__group-label", GEOMETRY, SETTINGS_ITEM),
            (".desk-prompt-library__nav button", ".desk-prompt-library__nav-label", PROMPT, PROMPT_ITEM),
        )
        for path in sorted(STYLES.glob("*.css")):
            css = path.read_text(encoding="utf-8")
            for item_needle, title_needle, base_css, item_sel in item_needles:
                title_start = title_starts[title_needle]
                for _, _, decls in _padding_overrides(css, item_needle):
                    start, _ = _logical_padding(base_css + "\n" + _synthetic_rule(item_sel, decls), item_sel)
                    delta = _length_px(start) - title_start
                    self.assertGreaterEqual(delta, INDENT_MIN_PX, f"{path.name} flattened {item_needle}: {decls}")
                    self.assertLessEqual(delta, INDENT_MAX_PX, f"{path.name} over-indented {item_needle}: {decls}")
                    self.assertEqual(delta, expected, f"{path.name} changed indent token for {item_needle}: {decls}")

    def test_indent_is_not_authored_as_leading_spaces_in_labels(self):
        for match in re.finditer(r"desk-settings-tabs__label\s*>([^<]+)", HTML):
            self.assertEqual(match.group(1), match.group(1).strip(), match.group(1))
        self.assertRegex(PROMPT_JS, r"navButton\(id, label, count\)")
        self.assertIn("${escapeHtml(label)}", PROMPT_JS)
        self.assertNotIn("&nbsp;", PROMPT_JS[PROMPT_JS.find("function navButton"):PROMPT_JS.find("function renderNav")])
        self.assertNotIn("  全部", PROMPT_JS)


def _synthetic_rule(selector, decls):
    body = "".join(f"{prop}:{value};" for prop, value in decls.items())
    return f"{selector}{{{body}}}"


if __name__ == "__main__":
    unittest.main()
