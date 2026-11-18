import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend import prompt_skill_client
from backend.krea2.contracts import normalize_job as krea_job
from backend.local_image.archiving import archive_pngs
from backend.moss.contracts import normalize_job as moss_job
from backend.qwen21.contracts import normalize_job as qwen_job
from backend.routes import prompt_routes
from backend.services import prompt_pe
from backend.services.history_format import format_history_task


CONFIG = {"provider": "gpt_oauth", "model": "fixture-llm", "reasoning_effort": "low"}
SOURCE = '招牌上写“好茶”'
OUTPUT = 'A green sign reads "好茶".'


class Handler:
    def __init__(self, body):
        self.body = body
        self.response = None

    def read_json_body(self, *, max_bytes):
        return self.body

    def send_json(self, data, status=200):
        self.response = status, data


class Rewrite(unittest.TestCase):
    def post(self, body, call=prompt_skill_client.call_prompt_model):
        handler = Handler(body)
        prompt_routes.handle_prompt_pe(handler, call_prompt_model=call, prompt_pe=prompt_pe,
                                       get_prompt_skill_config=lambda: CONFIG)
        return handler.response

    def test_profiles_use_distinct_caption_rules_and_preserve_visible_text(self):
        systems = []

        def call(user, system, options, *, error_label):
            self.assertIn(SOURCE, user)
            self.assertEqual(options["model"], "fixture-llm")
            systems.append(system)
            return {"text": '```text\nPrompt: ' + OUTPUT + '\n```', "provider": "gpt_oauth", "model": "fixture-llm"}

        for profile in ("moss_caption", "qwen_t2i"):
            status, result = self.post({"text": SOURCE, "profile": profile}, call)
            self.assertEqual(status, 200)
            self.assertEqual(result["prompt"], OUTPUT)
            self.assertEqual(result["profile"], profile)
            self.assertEqual(result["config_key"], prompt_pe.config_key(CONFIG))
        self.assertIn("MOSS", systems[0])
        self.assertIn("Qwen-Image 2.1", systems[1])
        self.assertNotEqual(*systems)

    def test_model_config_key_is_stable_and_changes_only_with_model_settings(self):
        original = prompt_pe.config_key(CONFIG)
        self.assertEqual(original, prompt_pe.config_key({**CONFIG, "skill": "image_prompt_v7"}))
        self.assertNotEqual(original, prompt_pe.config_key({**CONFIG, "model": "other-llm"}))
        self.assertNotEqual(original, prompt_pe.config_key({**CONFIG, "provider": "other-provider"}))

    def test_expanded_rules_invalidate_the_first_release_cache_for_the_same_model(self):
        # Captured from the initial PE release with this synthetic model configuration.
        old_key = "e8def15d87498a478fa373b7d85063049f3cb85584f89be0cd14e0c1ed431db5"
        handler = Handler(None)
        prompt_routes.handle_prompt_pe_config(handler, prompt_pe=prompt_pe, get_prompt_skill_config=lambda: CONFIG)
        self.assertEqual(handler.response[0], 200)
        self.assertNotEqual(handler.response[1]["config_key"], old_key)

    def test_saving_a_model_returns_the_key_for_the_persisted_config(self):
        handler = Handler(None)
        body = b'{"model":"other-llm"}'
        handler.headers, handler.rfile = {"Content-Length": str(len(body))}, io.BytesIO(body)
        config = dict(CONFIG)
        prompt_routes.handle_prompt_config_save(
            handler, _collect_prompt_skill_runtime_config=lambda _: {"ok": True, "prompt_skill": config},
            _sanitize_prompt_skill_patch=lambda data: data, json=json,
            update_app_settings_section=lambda _, patch: config.update(patch), pe_config_key=prompt_pe.config_key,
        )
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["pe_config_key"], prompt_pe.config_key({**CONFIG, "model": "other-llm"}))

    def test_qwen_normalizes_provider_line_wraps_to_a_single_paragraph(self):
        def call(*args, **kwargs):
            return {"text": 'A green sign reads "好\n茶".\n\nSunlight crosses\nthe paper.', "model": "fixture"}
        status, result = self.post({"text": SOURCE, "profile": "qwen_t2i"}, call)
        self.assertEqual(status, 200)
        self.assertEqual(result["prompt"], 'A green sign reads "好\n茶". Sunlight crosses the paper.')

    def test_pe_uses_existing_codex_fallback_and_keeps_the_config_key(self):
        wire = {"ok": True, "result": {"model": "pool-model", "choices": [{"message": {"content": OUTPUT}}]}}
        with (patch.object(prompt_skill_client, "get_prompt_skill_config", return_value=CONFIG),
              patch.object(prompt_skill_client, "_choose_model", return_value="fixture-llm"),
              patch.object(prompt_skill_client, "_call_prompt_provider", side_effect=RuntimeError("HTTP 429")),
              patch.object(prompt_skill_client, "chat_chatgpt_pool", return_value=wire)):
            status, result = self.post({"text": SOURCE, "profile": "moss_caption"})
        self.assertEqual(status, 200)
        self.assertEqual((result["provider"], result["model"]), ("chatgpt_pool", "pool-model"))
        self.assertEqual(result["config_key"], prompt_pe.config_key(CONFIG))
        self.assertEqual(result["prompt"], OUTPUT)

    def test_invalid_requests_do_not_call_model(self):
        def unexpected(*args, **kwargs):
            self.fail("invalid prompt must not call a provider")

        for body in ({}, {"profile": "image_prompt_v7", "text": SOURCE},
                     {"profile": "qwen_t2i", "text": "  "},
                     {"profile": "qwen_t2i", "text": "x" * 8001},
                     {"profile": "qwen_t2i", "text": SOURCE, "model": "override"}):
            with self.subTest(body=str(body)[:100]):
                status, result = self.post(body, unexpected)
                self.assertEqual(status, 400)
                self.assertFalse(result["ok"])

    def test_provider_failure_does_not_echo_payload_or_use_raw_text(self):
        def failed(*args, **kwargs):
            raise RuntimeError("fixture private upstream error")

        status, result = self.post({"text": SOURCE, "profile": "qwen_t2i"}, failed)
        self.assertEqual(status, 502)
        self.assertFalse(result["ok"])
        self.assertNotIn("prompt", result)
        self.assertNotIn("private upstream", result["error"])

    def test_cache_config_endpoint_exposes_only_the_cache_key(self):
        handler = Handler(None)
        prompt_routes.handle_prompt_pe_config(handler, prompt_pe=prompt_pe,
                                             get_prompt_skill_config=lambda: {**CONFIG, "api_key": "never-public"})
        self.assertEqual(handler.response, (200, {"ok": True, "config_key": prompt_pe.config_key(CONFIG)}))


class H3Rewrite(unittest.TestCase):
    post = Rewrite.post

    def test_h3_uses_configured_llm_and_keeps_ratio_separate(self):
        from backend import server

        handler = Handler({"profile": "h3_image_t2i", "text": f" {SOURCE} "})
        raw = json.dumps({"expanded_caption": OUTPUT, "aspect_ratio": "4:5"}, ensure_ascii=False)
        with (patch.object(server, "get_prompt_skill_config", return_value=CONFIG),
              patch.object(server, "call_prompt_model", return_value={
                  "text": "```json\n" + raw + "\n```", "provider": CONFIG["provider"], "model": CONFIG["model"],
              }) as chat,
              patch("requests.post", side_effect=AssertionError("H3 expansion must not call MiniMax PE")) as official):
            server.RequestHandler.handle_prompt_pe(handler)
        status, result = handler.response
        self.assertEqual(status, 200)
        self.assertEqual(result["prompt"], OUTPUT)
        self.assertEqual(result["aspect_ratio"], "4:5")
        self.assertEqual(result["profile"], "h3_image_t2i")
        self.assertEqual((result["provider"], result["model"]), (CONFIG["provider"], CONFIG["model"]))
        official.assert_not_called()
        user, system, options = chat.call_args.args
        self.assertIn(SOURCE, user)
        self.assertIn("H3 Image", system)
        self.assertIn("expanded_caption", system)
        self.assertEqual(options, CONFIG)
        self.assertNotIn("images", chat.call_args.kwargs)

    def test_h3_discards_an_invalid_ratio_but_keeps_the_caption(self):
        def call(*args, **kwargs):
            return {"text": json.dumps({"expanded_caption": OUTPUT, "aspect_ratio": "square"})}

        status, result = self.post({"profile": "h3_image_t2i", "text": SOURCE}, call)
        self.assertEqual(status, 200)
        self.assertEqual(result["prompt"], OUTPUT)
        self.assertNotIn("aspect_ratio", result)

    def test_h3_invalid_model_output_never_passes_provider_text_as_a_prompt(self):
        for raw in ("fixture private unstructured response", '{"expanded_caption": ""}', '{"caption": "other field"}'):
            with self.subTest(raw=raw):
                status, result = self.post({"profile": "h3_image_t2i", "text": SOURCE},
                                           lambda *args, **kwargs: {"text": raw})
                self.assertEqual(status, 502)
                self.assertNotIn("prompt", result)
                self.assertNotIn(raw, result["error"])

    def test_h3_still_uses_existing_codex_to_account_pool_fallback(self):
        result_json = json.dumps({"expanded_caption": OUTPUT, "aspect_ratio": "16:9"}, ensure_ascii=False)
        wire = {"ok": True, "result": {"model": "pool-model", "choices": [{"message": {"content": result_json}}]}}
        with (patch.object(prompt_skill_client, "get_prompt_skill_config", return_value=CONFIG),
              patch.object(prompt_skill_client, "_choose_model", return_value=CONFIG["model"]),
              patch.object(prompt_skill_client, "_call_prompt_provider", side_effect=RuntimeError("HTTP 429")),
              patch.object(prompt_skill_client, "chat_chatgpt_pool", return_value=wire)):
            status, result = self.post({"profile": "h3_image_t2i", "text": SOURCE})
        self.assertEqual(status, 200)
        self.assertEqual((result["prompt"], result["aspect_ratio"]), (OUTPUT, "16:9"))
        self.assertEqual((result["provider"], result["model"]), ("chatgpt_pool", "pool-model"))


class Provenance(unittest.TestCase):
    def setUp(self):
        self.trace = {"node_id": "pe-1", "profile": "moss_caption", "source_text": SOURCE,
                      "rewritten_prompt": OUTPUT, "provider": "gpt_oauth", "model": "fixture-llm", "edited": True}

    def test_local_generation_contracts_keep_only_valid_pe_records(self):
        for job in (moss_job, qwen_job, krea_job):
            with self.subTest(engine=job.__module__):
                self.assertNotIn("prompt_pe", job({"prompt": OUTPUT}))
                result = job({"prompt": OUTPUT, "prompt_pe": [self.trace]})
                self.assertEqual(result["prompt_pe"], [self.trace])
                for bad in (
                    {**self.trace, "profile": "auto"},
                    {**self.trace, "rewritten_prompt": "not used"},
                    {**self.trace, "api_key": "fixture"},
                    {**self.trace, "source_text": "x" * 8001},
                ):
                    with self.assertRaisesRegex(ValueError, "PE"):
                        job({"prompt": OUTPUT, "prompt_pe": [bad]})

    def test_local_generation_contracts_disallow_pe_in_non_caption_modes(self):
        for job, mode in ((krea_job, "edit"), (krea_job, "control"), (qwen_job, "edit"), (moss_job, "layout")):
            with self.subTest(engine=job.__module__, mode=mode):
                with self.assertRaisesRegex(ValueError, "只支持文生图"):
                    extra = {"layout_draft": {"items": []}} if mode == "layout" else {}
                    job({"prompt": OUTPUT, "prompt_pe": [self.trace], "mode": mode, **extra})

    def test_history_and_image_archive_keep_provenance_without_changing_prompt(self):
        params = {"prompt_pe": qwen_job({"prompt": OUTPUT, "prompt_pe": [self.trace]})["prompt_pe"]}
        task = {"task_id": "pe-test", "prompt": OUTPUT, "params": params, "type": "qwen21"}
        history = format_history_task(task, task_result_files=lambda _: ([], ""), h3_task_type="h3",
                                      public_h3_params=lambda value: value, safe_basename=lambda value: value)
        self.assertEqual(history["prompt"], OUTPUT)
        self.assertEqual(history["params"]["prompt_pe"], [self.trace])
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "test.png"
            source.write_bytes(b"fixture bytes; the archiver preserves rather than decodes them")
            images, _ = archive_pngs("pe-test", task, {"paths": [source]}, directory=folder / "archive",
                                    write_prompt_sidecar=lambda *a, **kw: None, metadata={}, suffix=".qwen21.json")
            self.assertEqual(images[0].read_bytes(), source.read_bytes())
            self.assertEqual(images[0].with_suffix(".txt").read_text(), OUTPUT + "\n")
            sidecar = json.loads(images[0].with_suffix(".qwen21.json").read_text())
            self.assertEqual(sidecar["parameters"]["prompt_pe"], [self.trace])
