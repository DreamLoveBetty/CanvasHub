#!/usr/bin/env python3
"""Chat with Codex models directly through the Codex Responses endpoint."""

from __future__ import annotations

import argparse
import sys
import time

from codex_api import CodexAPIError, build_text_request, extract_text, post_responses_stream


def chat(prompt: str, model: str, system: str | None = None) -> str:
    started = time.time()
    event = post_responses_stream(build_text_request(prompt=prompt, model=model, system=system))
    result = extract_text(event)
    elapsed = time.time() - started
    print(result)
    print(f"\nElapsed: {elapsed:.1f}s | chars={len(result)}", file=sys.stderr)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with Codex models without CLIProxyAPI")
    parser.add_argument("prompt", nargs="?", default=None, help="User prompt, or pipe via stdin")
    parser.add_argument("--model", "-m", default="gpt-5.5", help="Codex model name")
    parser.add_argument("--system", "-s", default=None, help="System/developer instruction")
    args = parser.parse_args()

    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        parser.error("prompt is required")

    try:
        chat(prompt=prompt, model=args.model, system=args.system)
    except CodexAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
