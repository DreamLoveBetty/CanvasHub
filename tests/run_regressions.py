#!/usr/bin/env python3
"""Run stable and machine-local Python regressions as separate suites."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
import unittest

from tests.offline_baseline import ensure_regression_isolation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = PROJECT_ROOT / "tests"
EXTENSIONS_ROOT = PROJECT_ROOT / "extensions"
GENERATED_DIRS = {
    "output",
    "artifacts",
    "reports",
    "test-results",
    "playwright-report",
    "coverage",
    "tmp",
    "__pycache__",
}
LOCAL_DIRS = {"local", "manual"}


def _is_local_test(path: Path, root: Path = TEST_ROOT) -> bool:
    relative = path.relative_to(root)
    return path.name.endswith("_local.py") or bool(set(relative.parts) & LOCAL_DIRS)


def _test_modules(scope: str) -> list[str]:
    modules = []
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        relative = path.relative_to(TEST_ROOT)
        if set(relative.parts) & GENERATED_DIRS:
            continue
        is_local = _is_local_test(path, TEST_ROOT)
        if scope == "stable" and is_local:
            continue
        if scope == "local" and not is_local:
            continue
        modules.append(".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts))
    return modules


def _extension_test_files(scope: str) -> list[tuple[str, Path]]:
    if not EXTENSIONS_ROOT.is_dir() or EXTENSIONS_ROOT.is_symlink():
        return []
    files: list[tuple[str, Path]] = []
    for ext_dir in sorted(EXTENSIONS_ROOT.iterdir(), key=lambda p: p.name):
        if ext_dir.name.startswith(".") or ext_dir.is_symlink() or not ext_dir.is_dir():
            continue
        ext_tests = ext_dir / "tests"
        if not ext_tests.is_dir() or ext_tests.is_symlink():
            continue
        for path in sorted(ext_tests.rglob("test_*.py")):
            relative = path.relative_to(ext_tests)
            if set(relative.parts) & GENERATED_DIRS:
                continue
            is_local = _is_local_test(path, ext_tests)
            if scope == "stable" and is_local:
                continue
            if scope == "local" and not is_local:
                continue
            files.append((ext_dir.name, path))
    return files


def _load_modules(modules: list[str], ext_files: list[tuple[str, Path]] | None = None) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for module in modules:
        try:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
        except unittest.SkipTest as exc:
            reason = str(exc)

            def skip_missing_dependency(reason=reason):
                raise unittest.SkipTest(reason)

            suite.addTest(unittest.FunctionTestCase(skip_missing_dependency, description=module))
    for ext_id, path in ext_files or ():
        rel_id = "_".join(path.relative_to(EXTENSIONS_ROOT / ext_id / "tests").with_suffix("").parts)
        mod_name = f"canvashub_ext_test_{ext_id.replace('-', '_')}_{rel_id}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load extension test {path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(mod))
        except unittest.SkipTest as exc:
            reason = str(exc)

            def skip_ext_dependency(reason=reason):
                raise unittest.SkipTest(reason)

            suite.addTest(unittest.FunctionTestCase(skip_ext_dependency, description=str(path)))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=("stable", "local", "all"),
        default="stable",
        help="stable excludes *_local.py and tests/local|manual; default: stable",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    isolation = ensure_regression_isolation(PROJECT_ROOT)
    if isolation.get("notice"):
        print(isolation["notice"], file=sys.stderr)
    modules = _test_modules(args.scope)
    ext_files = _extension_test_files(args.scope)
    suite = _load_modules(modules, ext_files)
    result = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1,
        warnings="default",
    ).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
