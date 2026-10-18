"""Point backend.database at a throwaway tasks.db for the duration of a test.

Server task helpers (get_task, update_task_status, ...) read database.DB_PATH at
call time, so without this a test would hit the real root tasks.db in the main
checkout, or fail with "no such table: tasks" in a clean worktree.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def use_temp_task_db(test: unittest.TestCase) -> Path:
    from backend import database

    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    db_path = Path(tmp.name) / "tasks.db"
    patcher = patch.object(database, "DB_PATH", str(db_path))
    patcher.start()
    test.addCleanup(patcher.stop)
    database.init_db()
    return db_path
