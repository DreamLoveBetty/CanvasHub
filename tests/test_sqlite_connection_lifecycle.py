"""Regression coverage for SQLite transaction and close semantics."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from backend import asset_index, layout_drafts


class _ConnectionProbe:
    def __init__(self):
        self.entered = 0
        self.exit_args = None
        self.closed = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *args):
        self.exit_args = args
        return False

    def close(self):
        self.closed += 1


class SqliteConnectionLifecycleTest(unittest.TestCase):
    def test_database_modules_route_every_connection_through_managed_helper(self):
        for module in (asset_index, layout_drafts):
            with self.subTest(module=module.__name__):
                source = inspect.getsource(module)
                self.assertNotIn("with sqlite3.connect(", source)
                self.assertEqual(source.count("sqlite3.connect("), 1)

    def test_managed_connection_closes_after_success(self):
        for module in (asset_index, layout_drafts):
            with self.subTest(module=module.__name__):
                probe = _ConnectionProbe()
                with patch.object(module.sqlite3, "connect", return_value=probe):
                    with module._connect_db() as connection:
                        self.assertIs(connection, probe)
                self.assertEqual(probe.entered, 1)
                self.assertEqual(probe.exit_args, (None, None, None))
                self.assertEqual(probe.closed, 1)

    def test_managed_connection_rolls_back_and_closes_after_exception(self):
        class FixtureError(RuntimeError):
            pass

        for module in (asset_index, layout_drafts):
            with self.subTest(module=module.__name__):
                probe = _ConnectionProbe()
                with patch.object(module.sqlite3, "connect", return_value=probe):
                    with self.assertRaises(FixtureError):
                        with module._connect_db():
                            raise FixtureError("fixture")
                self.assertIs(probe.exit_args[0], FixtureError)
                self.assertEqual(probe.closed, 1)


if __name__ == "__main__":
    unittest.main()
