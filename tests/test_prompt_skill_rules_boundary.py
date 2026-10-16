"""Boundary regressions for the pure prompt rules split out of prompt_skill_client."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from backend import prompt_skill_client
from backend.services import (
    prompt_adapter_rules,
    prompt_block_rules,
    prompt_image_analysis_rules,
    prompt_text_rules,
)

ROOT = Path(__file__).resolve().parents[1]
RULE_MODULES = {
    "prompt_text_rules": set(),
    "prompt_adapter_rules": {"prompt_text_rules"},
    "prompt_image_analysis_rules": {"prompt_text_rules"},
    "prompt_block_rules": {"prompt_text_rules", "prompt_image_analysis_rules"},
}
# Network, process, file and settings access belongs to prompt_skill_client.
FORBIDDEN_IMPORTS = {"requests", "urllib", "subprocess", "socket", "sys", "time", "pathlib", "PIL"}
FORBIDDEN_NAMES = {"open", "Path", "load_app_settings", "get_prompt_skill_config", "get_gpt_provider_config"}


def _tree(name: str) -> ast.Module:
    return ast.parse((ROOT / "backend" / "services" / f"{name}.py").read_text(encoding="utf-8"))


class PromptSkillRulesBoundaryTest(unittest.TestCase):
    def test_rule_modules_import_only_lower_rule_modules(self):
        for name, allowed in RULE_MODULES.items():
            imported = set()
            for node in ast.walk(_tree(name)):
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                    imported.add(node.module)
                if isinstance(node, ast.ImportFrom) and node.level == 2:
                    self.assertIn(node.module, {"prompt_library"}, f"{name} imports backend.{node.module}")
            self.assertEqual(imported, allowed, name)

    def test_rule_modules_stay_free_of_io_and_settings(self):
        for name in RULE_MODULES:
            tree = _tree(name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.split(".")[0] for alias in node.names}
                    self.assertFalse(roots & FORBIDDEN_IMPORTS, f"{name} imports {roots & FORBIDDEN_IMPORTS}")
                if isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn((node.module or "").split(".")[0], FORBIDDEN_IMPORTS, name)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, FORBIDDEN_NAMES, f"{name} uses {node.id}")
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                    self.assertNotEqual(node.attr, "environ", f"{name} reads os.environ; tunables stay in prompt_skill_client")

    def test_facade_keeps_public_names_and_patch_points(self):
        self.assertIs(prompt_skill_client.analyze_prompt_adapter, prompt_adapter_rules.analyze_prompt_adapter)
        self.assertIs(
            prompt_skill_client.generic_19_prompt_block_split_rule,
            prompt_block_rules.generic_19_prompt_block_split_rule,
        )
        self.assertIs(prompt_skill_client._format_visual_style_prompt, prompt_image_analysis_rules._format_visual_style_prompt)
        # Readers of these patch points and tunables must live in the facade, or patching
        # prompt_skill_client would not reach them.
        for name in (
            "_choose_model",
            "_call_prompt_provider",
            "_call_prompt_provider_with_pool_fallback",
            "_is_full_prompt_too_short",
            "_image_analysis_limits",
        ):
            self.assertEqual(getattr(prompt_skill_client, name).__module__, prompt_skill_client.__name__, name)
        for name in ("MIN_FULL_PROMPT_CHARS", "PROMPT_IMAGE_ANALYSIS_MAX_EDGE", "PROMPT_IMAGE_ANALYSIS_MAX_BYTES"):
            for module in (prompt_text_rules, prompt_adapter_rules, prompt_image_analysis_rules, prompt_block_rules):
                self.assertFalse(hasattr(module, name), f"{module.__name__} defines {name}")

    def test_block_module_tables_are_filled_from_templates(self):
        self.assertTrue(prompt_block_rules.PROMPT_BLOCK_PRIMARY_TYPES)
        self.assertTrue(prompt_block_rules.PROMPT_BLOCK_MODULE_TYPE_OWNERS)
        self.assertIs(prompt_skill_client.PROMPT_BLOCK_MODULE_LABELS, prompt_block_rules.PROMPT_BLOCK_MODULE_LABELS)


if __name__ == "__main__":
    unittest.main()
