#!/usr/bin/env python3
"""Official local offline regression entry.

Uses the project .venv when present, sandboxes production settings and
databases, scrubs inherited credentials and polluting environment variables,
then runs the existing stable Python and Node suites plus `npm run check`.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.offline_baseline import (  # noqa: E402
    PROJECT_MARKER,
    build_sandbox_env,
    dependency_report,
    is_project_venv_interpreter,
    new_workdir,
    openmp_conflict_reason,
    project_venv_python,
    scrub_inherited_env,
)


def _reexec_into_venv_if_needed(project_root: Path) -> None:
    if os.environ.get("CANVASHUB_OFFLINE_REEXECED") == "1":
        return
    venv = project_venv_python(project_root)
    if venv is None:
        return
    if is_project_venv_interpreter(project_root):
        return
    env = scrub_inherited_env()
    env["CANVASHUB_OFFLINE_REEXECED"] = "1"
    os.execve(str(venv), [str(venv), *sys.argv], env)


def _preflight(project_root: Path) -> dict:
    report = dependency_report()
    report["project_root"] = str(project_root)
    report["using_project_venv"] = is_project_venv_interpreter(project_root)
    report["project_venv"] = str(project_venv_python(project_root) or "")
    conflict = openmp_conflict_reason(project_root, sys.executable)
    report["openmp_conflict"] = conflict
    missing = [name for name, origin in report["modules"].items() if origin is None]
    report["missing_modules"] = missing
    return report


def _run(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path, timeout: int) -> dict:
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(command)}\n")
        log.write(f"cwd={cwd}\n")
        log.write(f"executable={env.get('VIRTUAL_ENV', '')} {sys.executable}\n")
        log.flush()
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    elapsed = time.monotonic() - started
    return {
        "command": command,
        "cwd": str(cwd),
        "exit": proc.returncode,
        "seconds": round(elapsed, 3),
        "log": str(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-node", action="store_true")
    parser.add_argument("--skip-npm", action="store_true")
    parser.add_argument(
        "--scope",
        choices=("stable",),
        default="stable",
        help="offline baseline always uses the stable scope",
    )
    args = parser.parse_args()

    _reexec_into_venv_if_needed(PROJECT_ROOT)
    preflight = _preflight(PROJECT_ROOT)
    if preflight["openmp_conflict"]:
        print(f"ERROR: {preflight['openmp_conflict']}", file=sys.stderr)
        print("Refusing to start the Python suite in this interpreter.", file=sys.stderr)
        if not args.preflight_only:
            return 2

    if args.preflight_only:
        json.dump(preflight, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 2 if preflight["openmp_conflict"] else 0

    workdir = new_workdir(PROJECT_ROOT, prefix="offline-baseline")
    env = build_sandbox_env(PROJECT_ROOT, workdir)
    if is_project_venv_interpreter(PROJECT_ROOT):
        env["VIRTUAL_ENV"] = str(PROJECT_ROOT / ".venv")
    logs = workdir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (workdir / "preflight.json").write_text(
        json.dumps(preflight, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "started_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "workdir": str(workdir),
        "interpreter": sys.executable,
        "preflight": preflight,
        "steps": {},
    }

    python_exe = sys.executable
    exit_code = 0

    if not args.skip_python:
        summary["steps"]["python"] = _run(
            [python_exe, "tests/run_regressions.py", "--scope", args.scope, "-v"],
            cwd=PROJECT_ROOT,
            env=env,
            log_path=logs / "python-stable.log",
            timeout=30 * 60,
        )
        if summary["steps"]["python"]["exit"] != 0:
            exit_code = 1

    if not args.skip_node:
        summary["steps"]["node"] = _run(
            ["node", "tests/run_node_regressions.mjs", "--scope", args.scope],
            cwd=PROJECT_ROOT,
            env=env,
            log_path=logs / "node-stable.log",
            timeout=15 * 60,
        )
        if summary["steps"]["node"]["exit"] != 0:
            exit_code = 1

    if not args.skip_npm:
        npm = "npm"
        summary["steps"]["npm_check"] = _run(
            [npm, "run", "-s", "check"],
            cwd=PROJECT_ROOT / "frontend",
            env=env,
            log_path=logs / "npm-check.log",
            timeout=10 * 60,
        )
        if summary["steps"]["npm_check"]["exit"] != 0:
            exit_code = 1

    summary["finished_at"] = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    (workdir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"workdir={workdir}")
    print(f"interpreter={sys.executable}")
    for name, step in summary["steps"].items():
        print(f"{name}: exit={step['exit']} seconds={step['seconds']} log={step['log']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
