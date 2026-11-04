#!/usr/bin/env python3
"""GPT generate/edit tasks record the local Codex request endpoint in task params."""

from __future__ import annotations

import inspect
import os
import time
import unittest
from unittest.mock import MagicMock

from backend.services import gpt_generation


def codex_result(endpoint: str) -> dict:
    return {
        "success": True,
        "image_path": "/archive/gpt_1.png",
        "image_paths": ["/archive/gpt_1.png"],
        "main_model": "gpt-5.5",
        "reasoning_effort": "medium",
        "request_endpoint": endpoint,
        "gpt_provider_route": "codex",
    }


def build_deps(fn, merged: list[dict], **overrides) -> dict:
    deps = {
        name: MagicMock(name=name)
        for name, param in inspect.signature(fn).parameters.items()
        if param.kind == param.KEYWORD_ONLY
    }
    deps.update(
        _coerce_bool=lambda value, default: default if value is None else bool(value),
        _coerce_gpt_main_model=lambda value: value or "gpt-5.5",
        _coerce_gpt_reasoning_effort=lambda value: value or "medium",
        _coerce_gpt_provider_route=lambda value: value or "codex",
        _coerce_gpt_provider_total_timeout=lambda value: 600,
        _coerce_use_third_party_api=lambda value: False,
        _gpt_route_uses_third_party=lambda route: False,
        _effective_image_ratio=lambda prompt, ratio, default: ratio or default,
        _effective_prompt_mode=lambda prompt, mode: mode,
        _is_generic_19_fidelity_prompt=lambda prompt: False,
        _is_task_canceled=lambda task_id: False,
        _augment_result_resolution_metadata=lambda result, resolution: {},
        _result_image_filenames=lambda result: ["gpt_1.png"],
        _merge_task_params=lambda task_id, params: merged.append(params),
        get_task=lambda task_id: {},
        os=os,
        time=time,
    )
    if "_coerce_prompt_mode" in deps:
        deps["_coerce_prompt_mode"] = lambda value: value
    deps.update(overrides)
    return deps


class GptTaskRequestEndpointTest(unittest.TestCase):
    def test_generate_task_records_endpoint(self) -> None:
        merged: list[dict] = []
        deps = build_deps(
            gpt_generation.process_gpt_task,
            merged,
            _generate_gpt_with_pool_fallback=lambda *args, **kwargs: (codex_result("images"), "codex", None),
        )

        gpt_generation.process_gpt_task("task", "prompt", "1:1", "1k", telegram_enabled=False, **deps)

        self.assertEqual(merged[-1]["request_endpoint"], "images")
        deps["_finalize_generation_task"].assert_called_once()
        self.assertEqual(deps["_finalize_generation_task"].call_args.args[1], "succeeded")

    def test_edit_task_records_endpoint(self) -> None:
        merged: list[dict] = []
        deps = build_deps(
            gpt_generation.process_gpt_edit_task,
            merged,
            resolve_route_model=lambda route, model, reasoning_effort=None: {
                "available": True,
                "model": model,
                "reasoning_effort": reasoning_effort,
            },
            _resolve_codex_provider_env=lambda: (None, "local_codex_auth"),
            edit_image_gpt_codex=lambda *args, **kwargs: codex_result("responses"),
        )

        gpt_generation.process_gpt_edit_task(
            "task", "prompt", ["data:image/png;base64,AA=="], "1:1", "1k", telegram_enabled=False, **deps
        )

        self.assertEqual(merged[-1]["request_endpoint"], "responses")
        self.assertEqual(deps["_finalize_generation_task"].call_args.args[1], "succeeded")

    def test_pool_result_leaves_endpoint_empty(self) -> None:
        merged: list[dict] = []
        pool_result = {**codex_result("images"), "gpt_provider_route": "chatgpt_pool"}
        pool_result.pop("request_endpoint")
        deps = build_deps(
            gpt_generation.process_gpt_task,
            merged,
            _generate_gpt_with_pool_fallback=lambda *args, **kwargs: (pool_result, "chatgpt_pool", "codex failed"),
        )

        gpt_generation.process_gpt_task("task", "prompt", "1:1", "1k", telegram_enabled=False, **deps)

        self.assertIsNone(merged[-1]["request_endpoint"])


if __name__ == "__main__":
    unittest.main()
