"""Shared fixtures for the surge_sdk test suite.

No network: every test that sends a report points the SDK at a local stub
HTTP server (127.0.0.1, ephemeral port) that records what it received and
answers however the test asks. No provider SDK is required either — the
anthropic tests install a fake `anthropic` module via monkeypatch.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# Import the package from this checkout, not a site-packages install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import surge_sdk  # noqa: E402
from surge_sdk import _config, _reporter  # noqa: E402


class StubSurge:
    """A tiny Surge backend: records requests, answers with a configured reply."""

    def __init__(self):
        self.requests = []  # list of dicts: path, headers, body
        self.status = 201
        self.headers = {}
        self.body = b'{"recorded": true}'
        self.hold = None  # threading.Event: block responses until set
        self.received = threading.Event()
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw or b"null")
                except ValueError:
                    body = raw
                with stub._lock:
                    stub.requests.append({
                        "path": self.path,
                        "headers": {k: v for k, v in self.headers.items()},
                        "body": body,
                    })
                stub.received.set()
                if stub.hold is not None:
                    stub.hold.wait(10)
                self.send_response(stub.status)
                for k, v in stub.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(stub.body)))
                self.end_headers()
                self.wfile.write(stub.body)

            def log_message(self, *args):  # silence test output
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def bodies(self, path):
        with self._lock:
            return [r["body"] for r in self.requests if r["path"] == path]

    def close(self):
        if self.hold is not None:
            self.hold.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _reset_sdk_state():
    """Every test starts unconfigured, with no diagnostics handler and the
    once-per-process quota warning re-armed."""
    _config._config = _config.SurgeConfig()
    _reporter.set_diagnostics(None)
    _reporter._quota_warned = False
    yield
    _reporter.flush(timeout=5)
    _config._config = _config.SurgeConfig()
    _reporter.set_diagnostics(None)
    _reporter._quota_warned = False


@pytest.fixture
def stub():
    s = StubSurge()
    yield s
    s.close()


@pytest.fixture
def configured(stub):
    """SDK configured against the stub server with a recognisable key."""
    surge_sdk.configure(
        product_line="global-app",
        surge_api_url=stub.url,
        surge_api_key="sk_surge_SECRET_TEST_KEY_123",
    )
    return stub
