"""Cross-domain guarantees that no single MOSS module can prove alone; fake runtimes, no model, no MLX."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from backend.moss.contracts import TASK_TYPE
from backend.runtime_resources import IdleWorkerCoordinator, local_accelerator
from tests.test_moss_routes import ROUTES
from tests.test_moss_service import Base

ROOT = Path(__file__).resolve().parents[1]
WIRING_PROBE = """
import json, sys
from backend import server
calls = []
workers = server._LOCAL_IMAGE_MEMORY._workers
for name in list(workers):
    workers[name] = lambda name=name: calls.append(name)
seen = {}
for owner, service in (("moss", server._MOSS_SERVICE), ("qwen21", server._QWEN21_SERVICE), ("krea2", server._KREA2_SERVICE)):
    calls.clear()
    service.runtime.before_load()
    seen[owner] = sorted(calls)
print(json.dumps({"mlx": any(name == "mlx" or name.startswith("mlx.") for name in sys.modules), "workers": sorted(workers), "seen": seen}))
"""


def clean_env(root):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TELEGRAM", "BOT_", "CHAT_"))}
    env.update(CANVASHUB_DATA_DIR=str(root), PYTHONPATH=str(ROOT))
    return env


class ServerWiring(unittest.TestCase):
    def test_importing_the_server_loads_no_mlx_and_each_engine_unloads_only_the_others(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, "-c", WIRING_PROBE], cwd=ROOT, env=clean_env(temp), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(report["mlx"])
        self.assertLessEqual({"moss", "qwen21", "krea2"}, set(report["workers"]))
        for owner, released in report["seen"].items():
            self.assertEqual(released, sorted(set(report["workers"]) - {owner}))

    def test_real_http_rejects_every_moss_route_without_a_session(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as temp:
            env = {**clean_env(temp), "PORT": str(port), "MINIAPP_ACCESS_PASSWORD": secrets.token_urlsafe(24)}
            server = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def status(method, path):
                data = b"{}" if method == "POST" else None
                try:
                    return opener.open(urllib.request.Request(f"http://127.0.0.1:{port}{path}", data), timeout=5).status
                except urllib.error.HTTPError as error:
                    with error:
                        return error.code
            try:
                for _ in range(120):
                    try:
                        status("GET", "/api/moss/status")
                        break
                    except (urllib.error.URLError, ConnectionError):
                        time.sleep(0.25)
                self.assertEqual({route: status(*route) for route in ROUTES}, {route: 401 for route in ROUTES})
            finally:
                server.terminate()
                server.wait(timeout=30)


class SharedLease(unittest.TestCase):
    def test_two_engines_never_hold_the_accelerator_together_and_a_waiter_can_leave(self):
        with tempfile.TemporaryDirectory() as temp:
            path, leave, progress = Path(temp) / "lease", threading.Event(), []
            finished = threading.Event()

            def waiter():
                with local_accelerator(path, leave, progress.append) as handle:
                    self.assertIsNotNone(handle)
                finished.set()
            with local_accelerator(path, threading.Event(), lambda _: None):
                thread = threading.Thread(target=waiter)
                thread.start()
                time.sleep(0.4)
                self.assertTrue(progress)
                self.assertFalse(finished.is_set())
                leave.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_release_other_spares_the_owner_and_release_all_does_not(self):
        closed = []
        memory = IdleWorkerCoordinator({"moss": lambda: closed.append("moss"), "qwen21": lambda: closed.append("qwen21")})
        memory.release_other("moss")
        self.assertEqual(closed, ["qwen21"])
        memory.release_all()
        self.assertEqual(closed, ["qwen21", "moss", "qwen21"])


class NoImplicitFallback(Base):
    def test_a_failed_generation_stays_failed_on_moss(self):
        self.runtime.gate.set()

        def broken(spec, directory, cancel, progress):
            self.runtime.specs.append(spec)
            raise RuntimeError("Metal 设备丢失")
        self.runtime.execute = broken
        result = self.service.submit({"mode": "text", "prompt": "x"})
        self.wait_done(result["task_id"])
        task = self.tasks.get(result["task_id"])
        self.assertEqual((task["status"], task["type"], len(self.runtime.specs)), ("failed", TASK_TYPE, 1))
        self.assertIn("Metal", task["error"])
        self.assertEqual(self.published, [])


if __name__ == "__main__":
    unittest.main()
