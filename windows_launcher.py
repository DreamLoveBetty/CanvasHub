#!/usr/bin/env python3
"""Windows background launcher for CanvasHub services."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "data" / "windows-start"
MAIN_PORT = int(os.environ.get("CANVASHUB_MAIN_PORT") or os.environ.get("MINIAPP_PORT") or "18463")
SIDECAR_HOST = os.environ.get("CHATGPT_POOL_HOST") or "127.0.0.1"
SIDECAR_PORT = int(os.environ.get("CHATGPT_POOL_PORT") or "18080")
PYTHON = Path(os.environ.get("CANVASHUB_PY") or sys.executable)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
SW_HIDE = 0
START_FLAGS = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP


def _service_python() -> Path:
    """Use pythonw.exe for background services on Windows to avoid extra consoles."""
    override = os.environ.get("CANVASHUB_SERVICE_PY")
    if override:
        return Path(override)
    if os.name == "nt" and PYTHON.name.lower() == "python.exe":
        pythonw = PYTHON.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw
    return PYTHON


def _startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_HIDE
    return startupinfo


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("CANVASHUB_MAIN_PORT", str(MAIN_PORT))
    env.setdefault("MINIAPP_PORT", str(MAIN_PORT))
    env.setdefault("PORT", str(MAIN_PORT))
    env.setdefault("CHATGPT_POOL_HOST", SIDECAR_HOST)
    env.setdefault("CHATGPT_POOL_PORT", str(SIDECAR_PORT))
    return env


def _write_log(name: str, text: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / name).open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(text.rstrip() + "\n")


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _wait_url(url: str, seconds: int) -> bool:
    for _ in range(max(1, seconds)):
        if _http_ok(url):
            return True
        time.sleep(1)
    return False


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return str(pid) in (result.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(name: str) -> int:
    try:
        return int((LOG_DIR / f"{name}.pid").read_text(encoding="ascii").strip() or "0")
    except Exception:
        return 0


def _write_pid(name: str, pid: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"{name}.pid").write_text(str(pid), encoding="ascii")


def _tail(path: Path, max_chars: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-max_chars:]


def _spawn(name: str, args: list[str], log_name: str) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    _write_log(log_name, f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting {name}: {' '.join(args)}")
    log_fh = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(ROOT),
            env=_env(),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=START_FLAGS if os.name == "nt" else 0,
            startupinfo=_startupinfo(),
            close_fds=False if os.name == "nt" else True,
        )
    except Exception as exc:
        log_fh.close()
        _write_log(log_name, f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] failed to spawn {name}: {exc!r}")
        raise
    log_fh.close()
    _write_pid(name, proc.pid)
    return proc.pid


def _start_service(name: str, port: int, args: list[str], health_url: str, log_name: str, wait_seconds: int = 60) -> bool:
    if _port_open("127.0.0.1", port):
        print(f"{name} port {port} is already listening; skip start.")
        return True
    pid = _spawn(name, args, log_name)
    print(f"Started {name} PID {pid}; log: {LOG_DIR / log_name}")
    time.sleep(2)
    if not _is_pid_alive(pid):
        print(f"{name} exited immediately. Log tail:")
        print(_tail(LOG_DIR / log_name) or f"(log is empty: {LOG_DIR / log_name})")
        return False
    if not _wait_url(health_url, wait_seconds):
        alive = _is_pid_alive(pid)
        print(f"Warning: {name} did not answer health check in {wait_seconds}s. PID alive: {alive}. Log: {LOG_DIR / log_name}")
        tail = _tail(LOG_DIR / log_name, 4000)
        print(tail or "(log has no Python output yet; service may still be initializing or stuck before first flush)")
        return False
    print(f"{name} is online.")
    return True


def start(open_browser: bool = True) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"CanvasHub root: {ROOT}")
    print(f"Logs: {LOG_DIR}")
    sidecar_ok = _start_service(
        "sidecar",
        SIDECAR_PORT,
        [str(_service_python()), "-u", "-X", "utf8", "-m", "uvicorn", "sidecars.chatgpt_pool.app:app", "--host", SIDECAR_HOST, "--port", str(SIDECAR_PORT)],
        f"http://{SIDECAR_HOST}:{SIDECAR_PORT}/health",
        "sidecar.combined.log",
        wait_seconds=45,
    )
    server_ok = _start_service(
        "server",
        MAIN_PORT,
        [str(_service_python()), "-u", "-X", "utf8", "server.py"],
        f"http://127.0.0.1:{MAIN_PORT}/desktop.html",
        "server.combined.log",
        wait_seconds=120,
    )
    if server_ok and open_browser:
        webbrowser.open(f"http://127.0.0.1:{MAIN_PORT}/desktop.html")
    print("")
    print(f"Desktop: http://127.0.0.1:{MAIN_PORT}/desktop.html")
    print(f"Sidecar: http://{SIDECAR_HOST}:{SIDECAR_PORT}/health")
    print("Stop with: stop-windows.bat")
    return 0 if server_ok and sidecar_ok else 1


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def stop() -> int:
    for name in ("server", "sidecar"):
        pid = _read_pid(name)
        if pid:
            print(f"Stopping {name} PID {pid}...")
            _kill_pid(pid)
            try:
                (LOG_DIR / f"{name}.pid").unlink()
            except OSError:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "stop":
        return stop()
    return start(open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
