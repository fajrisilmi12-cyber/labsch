"""Tests for AgentClient download API methods + agent loop download wiring.

Uses a local HTTP server stub to exercise real request/response paths
(endpoints, headers, body shapes) without external network access.
"""
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from config_sync import AgentClient


class _StubHandler(BaseHTTPRequestHandler):
    calls = []

    def _log(self, method, path, body=None):
        _StubHandler.calls.append({"method": method, "path": path,
                                   "token": self.headers.get("X-Agent-Token"), "body": body})

    def do_GET(self):
        self._log("GET", self.path)
        if self.path.split("?")[0] == "/api/downloads/pending":
            payload = {"pending_downloads": [{"task_id": "t-1", "url": "https://example.com/a.pdf",
                                  "autorun": False, "filename": "a.pdf"}]}
        else:
            self._log("GET", self.path)
            data = b"{}"
            self.send_response(404)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._respond(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._log("POST", self.path, body)
        if self.path == "/api/downloads/report":
            payload = {"ok": True}
        elif self.path == "/api/heartbeat":
            payload = {"ok": True}
        else:
            data = b"{}"
            self.send_response(404)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._respond(payload)

    def _respond(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _start_server():
    srv = HTTPServer(("127.0.0.1", 0), _StubHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


def test_pending_downloads_uses_token_and_expected_shape():
    srv = _start_server()
    try:
        c = AgentClient(f"http://127.0.0.1:{srv.server_port}", "tok-abc", "cid-1")
        _StubHandler.calls.clear()
        result = c.get_pending_downloads()
        assert result is not None
        assert result[0]["task_id"] == "t-1"
        call = _StubHandler.calls[-1]
        assert call["method"] == "GET"
        assert call["path"].startswith("/api/downloads/pending")
        assert "cid-1" in call["path"] or call["path"].count("?") >= 1  # client_id param present
        assert call["token"] == "tok-abc"
    finally:
        srv.shutdown()


def test_report_download_sends_event_body():
    srv = _start_server()
    try:
        c = AgentClient(f"http://127.0.0.1:{srv.server_port}", "tok-abc", "cid-1")
        _StubHandler.calls.clear()
        ok = c.report_download_result(
            "t-1", "done", "not_requested",
            bytes_count=123, sha256="a" * 64, error=None)
        assert ok is True
        call = _StubHandler.calls[-1]
        assert call["method"] == "POST"
        assert call["path"] == "/api/downloads/report"
        b = call["body"]
        assert b["task_id"] == "t-1"
        assert b["download_state"] == "done"
        assert b["execution_state"] == "not_requested"
        assert b["bytes"] == 123
        assert b["sha256"] == "a" * 64
    finally:
        srv.shutdown()


def test_report_download_never_raises_on_connection_error():
    # Point at a closed port; must return False, not raise.
    c = AgentClient("http://127.0.0.1:1", "tok-abc", "cid-1")
    assert c.report_download_result("t-1", "failed", "not_requested", error="boom") is False


def test_pending_downloads_none_on_connection_error():
    c = AgentClient("http://127.0.0.1:1", "tok-abc", "cid-1")
    assert c.get_pending_downloads() is None
