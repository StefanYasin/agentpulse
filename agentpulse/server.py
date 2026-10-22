"""Stdlib HTTP server for the dashboard and the JSON API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from . import __version__
from .parser import CronStateError, load_snapshot
from .render import render_error_page, render_page

DEFAULT_PORT = 8788
DEFAULT_REFRESH = 20


class AgentPulseServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(cron_dir, state_dir, refresh_seconds: int):
    """Build a request handler bound to one state source."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentPulse/" + __version__
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 - stdlib naming
            self._route(send_body=True)

        def do_HEAD(self):  # noqa: N802 - stdlib naming
            self._route(send_body=False)

        def _route(self, send_body: bool) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._serve_page(send_body)
            elif path == "/api/state":
                self._serve_state(send_body)
            elif path == "/healthz":
                self._serve_health(send_body)
            elif path == "/favicon.ico":
                self._send(b"", 204, "image/x-icon", send_body)
            else:
                self._send(b"not found\n", 404, "text/plain; charset=utf-8", send_body)

        def _serve_page(self, send_body: bool) -> None:
            try:
                snapshot = load_snapshot(cron_dir, state_dir=state_dir)
            except CronStateError as exc:
                body = render_error_page(str(exc), 503).encode("utf-8")
                self._send(body, 503, "text/html; charset=utf-8", send_body)
                return
            body = render_page(snapshot, refresh_seconds=refresh_seconds).encode("utf-8")
            self._send(body, 200, "text/html; charset=utf-8", send_body)

        def _serve_state(self, send_body: bool) -> None:
            try:
                snapshot = load_snapshot(cron_dir, state_dir=state_dir)
            except CronStateError as exc:
                payload = {
                    "error": str(exc),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                self._send_json(payload, 503, send_body)
                return
            self._send_json(snapshot.to_dict(), 200, send_body)

        def _serve_health(self, send_body: bool) -> None:
            try:
                snapshot = load_snapshot(cron_dir, state_dir=state_dir)
            except CronStateError as exc:
                self._send_json({"status": "error", "error": str(exc)}, 503, send_body)
                return
            counts = snapshot.counts()
            self._send_json(
                {
                    "status": "ok",
                    "jobs": counts["total"],
                    "attention": counts["attention"],
                    "generated_at": snapshot.generated_at.isoformat(),
                },
                200,
                send_body,
            )

        def _send_json(self, payload, status: int, send_body: bool) -> None:
            body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
            self._send(body, status, "application/json; charset=utf-8", send_body)

        def _send(self, body, status: int, content_type: str, send_body: bool) -> None:
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not send_body or not body:
                return
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt, *args):
            return

    return Handler


def create_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    cron_dir=None,
    state_dir=None,
    refresh_seconds: int = DEFAULT_REFRESH,
) -> AgentPulseServer:
    """Create (but do not start) the dashboard server."""
    handler = make_handler(cron_dir, state_dir, refresh_seconds)
    return AgentPulseServer((host, port), handler)


def serve_forever(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    cron_dir=None,
    state_dir=None,
    refresh_seconds: int = DEFAULT_REFRESH,
    server: Optional[AgentPulseServer] = None,
) -> None:
    """Block until interrupted."""
    httpd = server or create_server(host, port, cron_dir, state_dir, refresh_seconds)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
