import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import server
from backend.upscale_runtime import available_upscale_models, normalize_upscale_model


ROOT = Path(__file__).resolve().parents[1]


class FakeUpscaleHandler:
    def __init__(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.response = None
        self.started = None

    def send_json(self, data, status=200, extra_headers=None):
        self.response = {"data": data, "status": status}

    def start_generation_task(self, task_id, target, args=(), task_ids=None):
        self.started = {
            "task_id": task_id,
            "target": target,
            "args": args,
        }
        return True


class UpscaleRuntimeConfigTest(unittest.TestCase):
    def test_model_aliases_normalize(self):
        self.assertEqual(normalize_upscale_model("anime"), "4x-AnimeSharp")
        self.assertEqual(normalize_upscale_model("4x_ultrasharp"), "4x-UltraSharp")
        self.assertEqual(normalize_upscale_model("unknown"), "4x-UltraSharp")

    def test_available_models_reports_expected_weights(self):
        models = available_upscale_models(ROOT / "models" / "upscale")
        filenames = {item["filename"] for item in models}
        self.assertIn("4x-UltraSharp.pth", filenames)
        self.assertIn("4x-AnimeSharp.pth", filenames)


class UpscaleEndpointTest(unittest.TestCase):
    def test_upscale_run_creates_local_task(self):
        handler = FakeUpscaleHandler({
            "prompt": "",
            "images": ["data:image/png;base64,AAAA"],
            "model": "anime",
            "tile_size": 384,
            "tile_overlap": 64,
            "telegram_enabled": False,
            "lineage": {
                "reference_assets": [{"source_node_id": "image_1", "title": "source.png"}]
            },
        })

        with patch.object(server.time, "time", return_value=1710000000), \
             patch.object(server.random, "randint", return_value=1234), \
             patch.object(server, "create_task") as create_task:
            server.RequestHandler.handle_upscale_run(handler)

        self.assertEqual(handler.response["status"], 202)
        self.assertEqual(handler.response["data"]["task_id"], "upscale_1710000000_1234")
        create_task.assert_called_once()
        task_id, prompt, params = create_task.call_args.args[:3]
        self.assertEqual(task_id, "upscale_1710000000_1234")
        self.assertEqual(create_task.call_args.kwargs["task_type"], "upscale")
        self.assertEqual(prompt, "高清放大：4x-AnimeSharp")
        self.assertEqual(params["model"], "4x-AnimeSharp")
        self.assertEqual(params["tile_size"], 384)
        self.assertEqual(params["tile_overlap"], 64)
        self.assertEqual(params["archive_enabled"], True)
        self.assertEqual(params["telegram_enabled"], False)
        self.assertEqual(params["lineage"]["reference_assets"][0]["source_node_id"], "image_1")
        self.assertIs(handler.started["target"], server.process_upscale_task)

    def test_upscale_run_rejects_missing_image(self):
        handler = FakeUpscaleHandler({"model": "4x-UltraSharp", "images": []})

        with patch.object(server, "create_task") as create_task:
            server.RequestHandler.handle_upscale_run(handler)

        self.assertEqual(handler.response["status"], 400)
        self.assertIn("请先连接或上传一张图片", handler.response["data"]["error"])
        create_task.assert_not_called()

    def test_upscale_progress_callback_persists_numeric_progress(self):
        with patch.object(server.time, "time", return_value=1710000010), \
             patch.object(server, "update_task_status") as update_status, \
             patch.object(server, "update_task_fields") as update_fields:
            progress = server._upscale_progress_callback("upscale_task")
            progress(0.5, "高清放大中 2/4")
            progress(0.5, "高清放大中 2/4")

        update_status.assert_called_once_with(
            "upscale_task",
            "processing",
            "高清放大中 2/4",
            stage="upscaling",
            progress=50,
        )
        update_fields.assert_called_once_with(
            "upscale_task",
            heartbeat_at=1710000010,
            progress=50,
        )


class UpscaleDesktopSourceTest(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_desktop_exposes_upscale_node(self):
        html = self.read("frontend/desktop.html")
        canvas = self.read("frontend/scripts/desktop-canvas.js")
        api = self.read("frontend/scripts/desktop-api.js")
        css = self.read("frontend/styles/desktop-liquid.css")
        state_js = self.read("frontend/scripts/desktop-state.js")
        results_js = self.read("frontend/scripts/desktop-results.js")
        database_py = self.read("backend/database.py")
        server_py = self.read("backend/server.py")

        self.assertIn('data-add-node="upscale"', html)
        self.assertIn("DEFAULT_UPSCALE_NODE_WIDTH = 360", canvas)
        self.assertIn("DEFAULT_UPSCALE_NODE_HEIGHT = 180", canvas)
        self.assertIn("4x-UltraSharp", canvas)
        self.assertIn("readUpscaleNodeConfig", canvas)
        self.assertIn("readUpscaleNodeConfigForReference", canvas)
        self.assertIn("runUpscaleChainsForOutput", canvas)
        self.assertIn("modelToUpscale", canvas)
        self.assertIn('data-upscale-actions', canvas)
        self.assertIn('desk-upscale-telegram', canvas)
        self.assertIn('data-output-telegram', canvas)
        self.assertIn('desk-upscale-progress', canvas)
        self.assertIn('desk-progress-float__bar', canvas)
        self.assertIn("width: 360px", css)
        self.assertIn("height: 180px", css)
        self.assertRegex(css, r"--desk-node-radius:\s*8px;")
        self.assertRegex(css, r"\.desk-node--upscale\s*\{[^}]*border-radius:\s*var\(--desk-node-radius\);")
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", css)
        self.assertRegex(css, r"\.desk-upscale-controls\s*\{[^}]*position:\s*relative;[^}]*z-index:\s*4;")
        self.assertIn(".desk-node--upscale .desk-upscale-controls .desk-select-anchor-root.is-select-open", css)
        self.assertIn(".desk-node--upscale .desk-upscale-controls .desk-select-shell.is-open", css)
        self.assertIn(".desk-node--upscale .desk-upscale-controls .desk-select-menu", css)
        self.assertRegex(css, r"\.desk-node--upscale \.desk-upscale-actions\s*\{[^}]*z-index:\s*1;")
        self.assertIn(".desk-node--upscale .desk-upscale-controls:has(.desk-select-shell.is-open) ~ .desk-upscale-actions", css)
        self.assertIn("top: calc(100% + 2px)", css)
        self.assertIn(".desk-node--upscale .desk-upscale-progress .desk-progress-float__bar", css)
        self.assertIn("height: 9px", css)
        self.assertIn("min-width: 78px", css)
        self.assertIn("font-size: 8px", css)
        self.assertIn(".desk-node--upscale .desk-upscale-progress .desk-progress-float__timer", css)
        self.assertIn("font-size: 7px", css)
        self.assertIn("background: transparent", css)
        self.assertIn('body.desk-app[data-theme="dark"] .desk-node--upscale .desk-upscale-progress', css)
        upscale_snippet = canvas[canvas.index("function upscaleNodeHtml"):canvas.index("function imageNodeHtml")]
        self.assertIn('data-i18n="upscaleEyebrow"', upscale_snippet)
        self.assertIn('data-i18n="upscaleTitle"', upscale_snippet)
        self.assertIn('data-i18n="upscaleTileLabel">分块</span>', upscale_snippet)
        self.assertIn('data-i18n="upscaleOverlapLabel">重叠</span>', upscale_snippet)
        self.assertIn('data-i18n-aria="upscaleNodeAria"', upscale_snippet)
        self.assertIn('data-i18n-title="upscaleRunTitle"', upscale_snippet)
        self.assertNotIn('<span>Tile</span>', upscale_snippet)
        self.assertNotIn('<span>Overlap</span>', upscale_snippet)
        self.assertNotIn("data-node-resize-handle", upscale_snippet)
        self.assertNotIn('data-upscale-send-original', canvas)
        self.assertNotIn("desk-upscale-result", canvas)
        self.assertNotIn("Spandrel · ESRGAN 4x", canvas)
        self.assertIn("/api/upscale/run", api)
        self.assertIn("getUpscaleModels", api)
        self.assertIn("'progress': 'REAL DEFAULT 0'", database_py)
        self.assertIn("'progress': 'progress'", database_py)
        self.assertIn("update_task_status(task_id, 'processing', message, stage='upscaling', progress=percent)", server_py)
        self.assertIn("task.setdefault('progress'", server_py)
        self.assertIn("const explicitProgress = Number(", state_js)
        self.assertIn("task?.progress ?? task?.progress_percent ?? task?.progressPercent", state_js)
        self.assertIn("if (stage === 'upscaling')", state_js)
        self.assertIn("18 + (done / total) * 72", state_js)
        self.assertIn("output.progress =", results_js)

    def test_upscale_node_i18n_terms_exist(self):
        i18n = self.read("frontend/scripts/desktop-i18n.js")

        self.assertIn("upscaleTileLabel: '分块'", i18n)
        self.assertIn("upscaleTileLabel: 'Tile'", i18n)
        self.assertIn("upscaleOverlapLabel: '重叠'", i18n)
        self.assertIn("upscaleOverlapLabel: 'Overlap'", i18n)
        self.assertIn("'分块': 'Tile'", i18n)
        self.assertIn("'重叠': 'Overlap'", i18n)

    def test_upscale_auto_chain_does_not_retrigger_from_upscale_result(self):
        canvas = self.read("frontend/scripts/desktop-canvas.js")
        start = canvas.index("async function runUpscaleChainsForOutput")
        end = canvas.index("async function populateResultImageNodes", start)
        snippet = canvas[start:end]

        self.assertIn("if (resultNode?.type === 'upscale') return 0;", snippet)
        self.assertIn("String(output?.type || '').toLowerCase() === 'upscale'", snippet)
        self.assertLess(
            snippet.index("if (resultNode?.type === 'upscale') return 0;"),
            snippet.index("const modelNodeId"),
        )
        self.assertLess(
            snippet.index("String(output?.type || '').toLowerCase() === 'upscale'"),
            snippet.index("const modelNodeId"),
        )


if __name__ == "__main__":
    unittest.main()
