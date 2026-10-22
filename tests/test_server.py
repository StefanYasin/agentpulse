"""Live server tests against a real socket."""

import contextlib
import json
import threading
import urllib.error
import urllib.request

import pytest

from agentpulse.server import create_server

from conftest import FIXTURES


@contextlib.contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield "http://%s:%d" % (host, port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(url, method="GET"):
    request = urllib.request.Request(url, method=method)
    return urllib.request.urlopen(request, timeout=10)


def test_api_state():
    server = create_server(port=0, cron_dir=FIXTURES)
    with running(server) as base:
        with get(base + "/api/state") as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("application/json")
            assert response.headers["Cache-Control"] == "no-store"
            payload = json.loads(response.read().decode("utf-8"))
    assert payload["counts"]["total"] == 11
    assert payload["counts"]["attention"] == 3
    assert len(payload["jobs"]) == 11
    assert payload["source"].endswith("jobs.json")


def test_dashboard_page():
    server = create_server(port=0, cron_dir=FIXTURES, refresh_seconds=7)
    with running(server) as base:
        with get(base + "/") as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
    assert "AGENTPULSE" in body
    assert "Nightly vault backup push" in body
    assert 'content="7"' in body


def test_healthz():
    server = create_server(port=0, cron_dir=FIXTURES)
    with running(server) as base:
        with get(base + "/healthz") as response:
            payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert payload["status"] == "ok"
    assert payload["jobs"] == 11
    assert payload["attention"] == 3


def test_head_has_no_body():
    server = create_server(port=0, cron_dir=FIXTURES)
    with running(server) as base:
        with get(base + "/", method="HEAD") as response:
            assert response.status == 200
            assert int(response.headers["Content-Length"]) > 0
            assert response.read() == b""


def test_unknown_path_returns_404():
    server = create_server(port=0, cron_dir=FIXTURES)
    with running(server) as base:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            get(base + "/nope")
    assert excinfo.value.code == 404


def test_missing_state_returns_503(tmp_path):
    server = create_server(port=0, cron_dir=tmp_path / "missing")
    with running(server) as base:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            get(base + "/api/state")
        body = excinfo.value.read().decode("utf-8")
        assert excinfo.value.code == 503
        assert "cron state not found" in json.loads(body)["error"]

        with pytest.raises(urllib.error.HTTPError) as page_exc:
            get(base + "/")
        page = page_exc.value.read().decode("utf-8")
    assert page_exc.value.code == 503
    assert "State unavailable" in page


def test_favicon_is_no_content():
    server = create_server(port=0, cron_dir=FIXTURES)
    with running(server) as base:
        with get(base + "/favicon.ico") as response:
            assert response.status == 204
            assert response.read() == b""
