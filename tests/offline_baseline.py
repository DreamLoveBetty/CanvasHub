"""Shared helpers for the official offline regression entry.

These helpers isolate tests from production settings, databases and inherited
process environment. They do not change product defaults in backend code.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import time
from typing import Any


PROJECT_MARKER = "CANVASHUB_TEST_SANDBOX"

# Names only; never log values.
CREDENTIAL_ENV_NAMES = (
    "MINIAPP_ACCESS_PASSWORD",
    "MINIAPP_AUTH_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_AUTH_BOT_TOKEN",
    "BOT_TOKEN",
    "TELEGRAM_PROXY",
    "OPENAI_API_KEY",
    "OPENAI_ACCESS_TOKEN",
    "CHATGPT_API_KEY",
    "YUNWU_API_KEY",
    "NANO_BANANA_API_KEY",
    "COMFY_API_KEY",
    "MINIMAX_API_KEY",
    "PINTEREST_COOKIE",
    "PINTEREST_ACCESS_TOKEN",
)

# Inherited values that have been shown to change settings-test outcomes
# or to point tests at the live server / a user proxy.
POLLUTING_ENV_NAMES = (
    "MINIAPP_PUBLIC_MODE",
    "PUBLIC_MODE",
    "HOST",
    "BIND_HOST",
    "MINIAPP_HOST",
    "PORT",
    "MINIAPP_PORT",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "KMP_DUPLICATE_LIB_OK",
)

PRODUCTION_RELATIVE_PATHS = (
    "settings.json",
    "tasks.db",
    "data/tasks.db",
    "data/video-edit/jobs.sqlite3",
    "assets.db",
    "prompt_library.db",
)


def project_venv_python(project_root: Path) -> Path | None:
    candidate = project_root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def is_project_venv_interpreter(project_root: Path, executable: str | None = None) -> bool:
    """Return True when the given (or current) interpreter is the project venv.

    Do not resolve the `python` symlink: on Homebrew, `.venv/bin/python` and
    the system `python3` can point at the same binary.
    """
    venv_root = project_root / ".venv"
    venv_bin = venv_root / "bin"
    if not venv_bin.exists():
        return False
    in_this_process = Path(sys.prefix).resolve() == venv_root.resolve()
    if executable is None:
        return in_this_process
    exe = Path(os.path.abspath(executable))
    if exe.parent == Path(os.path.abspath(venv_bin)):
        return True
    if in_this_process and os.path.abspath(executable) == os.path.abspath(sys.executable):
        return True
    return False


def module_origin(name: str) -> Path | None:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin)


def torch_bundled_libomp(project_root: Path | None = None) -> Path | None:
    """Locate torch's bundled libomp without importing torch (import can abort)."""
    origin = module_origin("torch")
    if origin is None:
        return None
    bundled = origin.resolve().parent / "lib" / "libomp.dylib"
    return bundled if bundled.exists() else None


def numpy_loaded_libomps(executable: str) -> list[str]:
    """List OpenMP dylibs visible after `import numpy` in a child process."""
    script = r"""
import ctypes
import json
import sys
from ctypes import c_char_p, c_uint32
import numpy  # noqa: F401
names = []
try:
    libc = ctypes.CDLL(None)
    count = libc._dyld_image_count
    count.restype = c_uint32
    name_at = libc._dyld_get_image_name
    name_at.argtypes = [c_uint32]
    name_at.restype = c_char_p
    for i in range(count()):
        raw = name_at(i)
        if raw:
            names.append(raw.decode("utf-8", "replace"))
except Exception as exc:
    print(json.dumps({"error": type(exc).__name__}))
    sys.exit(0)
needles = ("libomp", "libiomp", "libgomp")
hits = [n for n in names if any(s in n.lower() for s in needles)]
print(json.dumps(hits))
"""
    import json
    import subprocess

    result = subprocess.run(
        [executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return []
    return [str(item) for item in payload]


def openmp_conflict_reason(project_root: Path, executable: str) -> str | None:
    """Return a human reason if numpy and torch would load two OpenMP runtimes."""
    bundled = torch_bundled_libomp(project_root)
    if bundled is None:
        return None
    loaded = numpy_loaded_libomps(executable)
    foreign = [path for path in loaded if Path(path).resolve() != bundled.resolve()]
    if not foreign:
        return None
    return (
        "this interpreter already loads a non-torch OpenMP runtime via numpy "
        f"({', '.join(foreign)}) and torch bundles {bundled}; importing torch "
        "can abort with OMP Error #15. Use the project .venv."
    )


def dependency_report(executable: str | None = None) -> dict[str, Any]:
    exe = executable or sys.executable
    report: dict[str, Any] = {
        "executable": exe,
        "version": sys.version.split()[0] if exe == sys.executable else None,
        "modules": {},
    }
    for name in ("numpy", "scipy", "torch", "PIL"):
        origin = module_origin(name)
        report["modules"][name] = None if origin is None else str(origin)
    return report


def new_workdir(project_root: Path, prefix: str = "offline-baseline") -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    workdir = project_root / "tests" / "tmp" / f"{prefix}-{stamp}"
    workdir.mkdir(parents=True, exist_ok=False)
    return workdir


def production_paths(project_root: Path) -> dict[str, Path]:
    return {rel: project_root / rel for rel in PRODUCTION_RELATIVE_PATHS}


def assert_sandbox_isolated(project_root: Path, sandbox_root: Path) -> None:
    sandbox = sandbox_root.resolve()
    tmp_root = (project_root / "tests" / "tmp").resolve()
    if tmp_root not in sandbox.parents and sandbox != tmp_root:
        raise RuntimeError(f"sandbox must live under tests/tmp: {sandbox}")
    for rel, path in production_paths(project_root).items():
        resolved = path.resolve()
        if sandbox == resolved or sandbox in resolved.parents or resolved in sandbox.parents or resolved == sandbox:
            raise RuntimeError(f"sandbox overlaps production path {rel}: {sandbox}")
        # Child files must not be the production files themselves.
        if resolved.exists() and resolved.is_relative_to(sandbox):
            raise RuntimeError(f"production path unexpectedly inside sandbox: {rel}")


def scrub_inherited_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of env with credentials and polluting variables removed."""
    cleaned = dict(os.environ if env is None else env)
    for key in CREDENTIAL_ENV_NAMES + POLLUTING_ENV_NAMES:
        cleaned.pop(key, None)
    return cleaned


def build_sandbox_env(project_root: Path, workdir: Path) -> dict[str, str]:
    """Construct an isolated environment that cannot resolve production data."""
    assert_sandbox_isolated(project_root, workdir)
    data_dir = workdir / "sandbox" / "data"
    settings_path = workdir / "sandbox" / "settings.json"
    archive_dir = data_dir / "archive"
    source_dir = data_dir / "source_images"
    data_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    if not settings_path.exists():
        settings_path.write_text("{}", encoding="utf-8")

    env = scrub_inherited_env()
    env["CANVASHUB_DATA_DIR"] = str(data_dir)
    env["APP_SETTINGS_PATH"] = str(settings_path)
    env["TASKS_DB_PATH"] = str(data_dir / "tasks.db")
    env["IMAGE_ARCHIVE_DIR"] = str(archive_dir)
    env["SOURCE_IMAGE_DIR"] = str(source_dir)
    env["CHATGPT_POOL_ENABLED"] = "false"
    env["CHATGPT_POOL_BASE_URL"] = "http://127.0.0.1:1"
    env["COMFY_BASE_URL"] = "http://127.0.0.1:1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(project_root)
    env[PROJECT_MARKER] = str(workdir)
    env["CANVASHUB_TEST_KEEP_CWD"] = "1"
    env.pop("CANVASHUB_RESOURCE_DIR", None)
    # Never opt into the unsafe OpenMP workaround.
    env.pop("KMP_DUPLICATE_LIB_OK", None)
    return env


def install_keep_cwd_hook(project_root: Path) -> None:
    """Keep the test process in the project root if backend.server calls os.chdir."""
    root = str(project_root.resolve())
    if getattr(os.chdir, "_canvashub_keep_cwd", False):
        return
    original = os.chdir

    def _keep(path):
        original(root)

    _keep._canvashub_keep_cwd = True  # type: ignore[attr-defined]
    os.chdir = _keep  # type: ignore[assignment]
    original(root)


def ensure_regression_isolation(project_root: Path) -> dict[str, Any]:
    """If the official runner was invoked without a sandbox, create one.

    Returns a small report. Does not re-exec interpreters and does not start tests.
    """
    existing = os.environ.get(PROJECT_MARKER, "").strip()
    if existing:
        workdir = Path(existing)
        install_keep_cwd_hook(project_root)
        return {"workdir": workdir, "created": False, "keep_cwd": True}
    workdir = new_workdir(project_root, prefix="run-regressions-sandbox")
    env = build_sandbox_env(project_root, workdir)
    # Apply isolation in-place; do not drop PATH/HOME/LANG.
    for key in list(os.environ):
        if key not in env and key in CREDENTIAL_ENV_NAMES + POLLUTING_ENV_NAMES:
            os.environ.pop(key, None)
    os.environ.update(env)
    install_keep_cwd_hook(project_root)
    return {
        "workdir": workdir,
        "created": True,
        "keep_cwd": True,
        "notice": (
            f"Isolated official Python regressions under {workdir}. "
            "Prefer: python3 tests/run_offline_baseline.py"
        ),
    }
