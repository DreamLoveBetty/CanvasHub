#!/usr/bin/env python3
"""Packaged desktop runtime entrypoint for CanvasHub services."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

from .version import APP_VERSION


def _source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _configure_environment(args: argparse.Namespace) -> tuple[Path, Path]:
    resource_dir = Path(
        args.resource_dir
        or os.environ.get("CANVASHUB_RESOURCE_DIR")
        or _source_root()
    ).expanduser().resolve()
    data_dir = Path(
        args.data_dir
        or os.environ.get("CANVASHUB_DATA_DIR")
        or resource_dir
    ).expanduser().resolve()

    os.environ["CANVASHUB_RESOURCE_DIR"] = str(resource_dir)
    if args.data_dir or os.environ.get("CANVASHUB_DATA_DIR"):
        os.environ["CANVASHUB_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("APP_SETTINGS_PATH", str(data_dir / "settings.json"))
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    for relative in (
        "archive",
        "source_images",
        "auth",
        "cache",
        "components",
        "downloads",
        "logs",
        "chatgpt_pool",
    ):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)
    os.chdir(resource_dir)
    return resource_dir, data_dir


def _run_server(args: argparse.Namespace) -> int:
    _configure_environment(args)
    os.environ["HOST"] = "127.0.0.1"
    os.environ["MINIAPP_HOST"] = "127.0.0.1"
    os.environ["PORT"] = str(args.port)
    os.environ["MINIAPP_PORT"] = str(args.port)
    os.environ["MINIAPP_PUBLIC_MODE"] = "0"
    from backend.server import run_server

    run_server()
    return 0


def _run_sidecar(args: argparse.Namespace) -> int:
    _configure_environment(args)
    host = "127.0.0.1"
    os.environ["CHATGPT_POOL_HOST"] = host
    os.environ["CHATGPT_POOL_PORT"] = str(args.port)
    import uvicorn

    uvicorn.run(
        "sidecars.chatgpt_pool.app:app",
        host=host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
        workers=1,
    )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    resource_dir, data_dir = _configure_environment(args)
    required_resources = (
        resource_dir / "frontend" / "desktop.html",
        resource_dir / "prompt_skills",
        resource_dir / "static",
    )
    writable_probe = data_dir / ".runtime-write-probe"
    writable = False
    try:
        writable_probe.write_text("ok", encoding="ascii")
        writable_probe.unlink(missing_ok=True)
        writable = True
    except OSError:
        writable = False

    optional = {}
    for module_name in ("torch", "spandrel", "numpy"):
        optional[module_name] = importlib.util.find_spec(module_name) is not None

    payload = {
        "ok": writable and all(path.exists() for path in required_resources),
        "version": APP_VERSION,
        "resource_dir": str(resource_dir),
        "data_dir": str(data_dir),
        "data_dir_writable": writable,
        "resources": {str(path.relative_to(resource_dir)): path.exists() for path in required_resources},
        "optional_upscale_dependencies": optional,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="canvashub-runtime")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_runtime_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("--resource-dir", default="")
        command.add_argument("--data-dir", default="")

    server = subparsers.add_parser("server", help="Run the CanvasHub HTTP server")
    add_runtime_args(server)
    server.add_argument("--port", type=int, required=True)
    server.set_defaults(handler=_run_server)

    sidecar = subparsers.add_parser("sidecar", help="Run the ChatGPT account-pool sidecar")
    add_runtime_args(sidecar)
    sidecar.add_argument("--port", type=int, required=True)
    sidecar.add_argument("--log-level", default="warning")
    sidecar.set_defaults(handler=_run_sidecar)

    doctor = subparsers.add_parser("doctor", help="Validate packaged resources and writable state")
    add_runtime_args(doctor)
    doctor.set_defaults(handler=_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
