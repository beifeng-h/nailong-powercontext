import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from sddctx.assistant import AssistantRuntime
from sddctx.server import ContextRequestHandler
from sddctx.store import SqliteStore
from tests.support import spec_doc

NL = chr(10)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "spec" / "specs").mkdir(parents=True)
        (self.root / "spec" / "specs" / "SPEC-1.md").write_text(
            spec_doc(
                spec_id="SPEC-1",
                title="任务列表过滤",
                scope=["api"],
                tags=["task"],
                code_refs=[("app.py", "list_tasks", "")],
            ),
            encoding="utf-8",
        )
        (self.root / "app.py").write_text(
            "def list_tasks():" + NL + "    return []" + NL, encoding="utf-8"
        )
        self.store = SqliteStore(":memory:")
        self.runtime = AssistantRuntime(self.store, root=self.root)
        self.runtime.refresh()
        handler = type("BoundHandler", (ContextRequestHandler,), {"runtime": self.runtime})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()
        self._tmp.cleanup()

    def _get(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def test_health_endpoint(self):
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_context_endpoint_returns_bundle(self):
        status, body = self._get("/api/context?task=" + urllib.parse.quote("任务列表过滤"))
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("bundle", payload)
        self.assertTrue(payload["bundle"]["specs"])
        self.assertEqual(payload["bundle"]["specs"][0]["id"], "SPEC-1")
        self.assertIn("checklist", payload)

    def test_context_endpoint_requires_task(self):
        try:
            self._get("/api/context")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
        else:
            self.fail("缺少 task 时应当返回 400")

    def test_doctor_endpoint(self):
        status, body = self._get("/api/doctor")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("findings", payload)


if __name__ == "__main__":
    unittest.main()

