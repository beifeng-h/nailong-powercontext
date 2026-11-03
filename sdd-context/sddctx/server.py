"""本地 HTTP 接口：把上下文模块挂给外部 AI 助手 / IDE 插件调用。

只用标准库 `http.server`，默认只监听 127.0.0.1，不对外暴露，
也不需要任何外部服务即可跑起来。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .assistant import AssistantRuntime


class ContextRequestHandler(BaseHTTPRequestHandler):
    """路由表在 `routes()` 里，全部只读（或幂等刷新）。"""

    runtime: AssistantRuntime

    server_version = "sddctx/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102
        return

    # ---------- 工具 ----------
    def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> dict[str, list[str]]:
        parsed = urlparse(self.path)
        return parse_qs(parsed.query)

    def _first(self, query: dict[str, list[str]], key: str, default: str = "") -> str:
        values = query.get(key)
        return values[0] if values else default

    def _list(self, query: dict[str, list[str]], key: str) -> list[str]:
        raw = self._first(query, key)
        return [item.strip() for item in raw.split(",") if item.strip()]

    # ---------- 路由 ----------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = self._query()
        runtime = self.runtime

        if route in ("/", "/api/health"):
            self._send(200, {"status": "ok", "stats": runtime.store.stats()})
            return

        if route == "/api/specs":
            self._send(200, {"specs": [s.to_dict() for s in runtime.store.list_specs()]})
            return

        if route == "/api/decisions":
            self._send(
                200, {"decisions": [d.to_dict() for d in runtime.store.list_decisions()]}
            )
            return

        if route == "/api/context":
            task = self._first(query, "task")
            if not task:
                self._send(400, {"error": "缺少 task 参数"})
                return
            packet = runtime.prepare_task(
                task,
                scope=self._list(query, "scope"),
                tags=self._list(query, "tags"),
                changed_files=self._list(query, "changed"),
            )
            if self._first(query, "format") == "markdown":
                self._send(200, packet.prompt, content_type="text/markdown")
                return
            self._send(200, packet.to_dict())
            return

        if route == "/api/doctor":
            spec_ids = self._list(query, "spec") or None
            findings = runtime.checker.check(spec_ids=spec_ids)
            errors = [f for f in findings if f.severity.value == "error"]
            self._send(
                200,
                {
                    "ok": not errors,
                    "findings": [f.to_dict() for f in findings],
                },
            )
            return

        self._send(404, {"error": f"未知路由 {route}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route == "/api/refresh":
            self._send(200, self.runtime.refresh())
            return
        self._send(404, {"error": f"未知路由 {route}"})


def serve(runtime: AssistantRuntime, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    """启动 HTTP 服务（阻塞）。"""
    handler = type("BoundHandler", (ContextRequestHandler,), {"runtime": runtime})
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"sddctx 服务已启动：http://{host}:{port}/api/health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return httpd

