#!/usr/bin/env python3
"""Run stable and machine-local Python regressions as separate suites."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = PROJECT_ROOT / "tests"
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


def _is_local_test(path: Path) -> bool:
    relative = path.relative_to(TEST_ROOT)
    return path.name.endswith("_local.py") or bool(set(relative.parts) & LOCAL_DIRS)


def _test_modules(scope: str) -> list[str]:
    modules = []
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        relative = path.relative_to(TEST_ROOT)
        if set(relative.parts) & GENERATED_DIRS:
            continue
        is_local = _is_local_test(path)
        if scope == "stable" and is_local:
            continue
        if scope == "local" and not is_local:
            continue
        modules.append(".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts))
    return modules


def _load_modules(modules: list[str]) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for module in modules:
        try:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
        except unittest.SkipTest as exc:
            reason = str(exc)

            def skip_missing_dependency(reason=reason):
                raise unittest.SkipTest(reason)

            suite.addTest(unittest.FunctionTestCase(skip_missing_dependency, description=module))
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
    modules = _test_modules(args.scope)
    suite = _load_modules(modules)
    result = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1,
        warnings="default",
    ).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
