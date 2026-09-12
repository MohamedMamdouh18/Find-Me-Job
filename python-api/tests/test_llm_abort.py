"""Stop must kill an in-flight LLM call, not wait it out.

This reaches into httpx's private connection pool, so it is the first thing an
httpx upgrade will break, and the failure is silent: stop quietly degrades into
pause and the user waits out the 120s timeout again.

The server holds every connection open forever in a module-level list. That is
load-bearing: an earlier version of this test let the server thread drop its only
reference, so the socket was garbage collected and the read ended on its own. The
test passed while the abort did nothing.
"""
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time

import pytest

from src.services import settings as settings_module
from src.services.http import get as http_get
from src.services.llm import call_llm
from src.services.net_abort import abort_active_calls
from src.services.run_context import PauseRequested

_KEEP: list = []  # nothing in here is ever collected


def _tls_context():
    d = tempfile.mkdtemp()
    cert, key = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
         "-out", cert, "-days", "1", "-nodes", "-subj", "/CN=127.0.0.1",
         "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx


def _stalling_server(tls: bool) -> int:
    """Accepts, reads the request, then never answers and never lets go."""
    ctx = _tls_context() if tls else None
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    _KEEP.append(srv)

    def loop():
        raw, _ = srv.accept()
        _KEEP.append(raw)
        sock = ctx.wrap_socket(raw, server_side=True) if ctx else raw
        _KEEP.append(sock)
        try:
            sock.recv(65536)
        except Exception:
            pass
        while True:
            time.sleep(3600)

    thread = threading.Thread(target=loop, daemon=True)
    _KEEP.append(thread)
    thread.start()
    return srv.getsockname()[1]


@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
def test_abort_kills_a_blocked_llm_read(tls, monkeypatch):
    port = _stalling_server(tls)

    if tls:
        # httpx trusts certifi, so a self-signed cert would fail the handshake fast
        # and the read would never block — which would make this test vacuous.
        import httpx
        import src.services.llm as llm_module

        real_client = httpx.Client
        monkeypatch.setattr(
            llm_module.httpx, "Client",
            lambda **kw: real_client(**{**kw, "verify": False}),
        )

    scheme = "https" if tls else "http"
    monkeypatch.setattr(
        settings_module, "get_llm_url",
        lambda: f"{scheme}://127.0.0.1:{port}/v1/chat/completions",
    )
    monkeypatch.setattr(settings_module, "get_llm_model", lambda: "m")
    monkeypatch.setattr(settings_module, "get_llm_api_key", lambda: "")

    event = threading.Event()
    result: dict = {}

    def call():
        try:
            call_llm([{"role": "user", "content": "hi"}], interrupt=event)
            result["outcome"] = "returned"
        except PauseRequested:
            result["outcome"] = "PauseRequested"
        except Exception as e:
            result["outcome"] = type(e).__name__

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    time.sleep(3.0)
    assert worker.is_alive(), "the call never blocked, so this test proves nothing"

    event.set()
    abort_active_calls()
    worker.join(timeout=15)

    assert not worker.is_alive(), (
        f"{scheme}: the blocked read was never killed — stop has degraded into pause"
    )
    assert result["outcome"] == "PauseRequested", result


@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
def test_abort_kills_a_blocked_scraper_get(tls, monkeypatch):
    """The scraper path matters as much as the LLM one: a LinkedIn scrape sits in
    services.http.get once per search and once per job page, so a stop during the
    scrape phase used to wait out tries x timeout plus the backoff."""
    port = _stalling_server(tls)

    if tls:
        import httpx
        import src.services.http as http_module

        real_client = httpx.Client
        monkeypatch.setattr(
            http_module.httpx, "Client",
            lambda **kw: real_client(**{**kw, "verify": False}),
        )

    scheme = "https" if tls else "http"
    result: dict = {}
    event = threading.Event()

    def call():
        try:
            http_get(f"{scheme}://127.0.0.1:{port}/jobs", timeout=25.0, tries=3,
                     wait=5.0, interrupt=event)
            result["outcome"] = "returned"
        except PauseRequested:
            result["outcome"] = "PauseRequested"
        except Exception as e:
            result["outcome"] = type(e).__name__

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    time.sleep(3.0)
    assert worker.is_alive(), "the GET never blocked, so this test proves nothing"

    event.set()
    abort_active_calls()
    worker.join(timeout=15)

    assert not worker.is_alive(), (
        f"{scheme}: the blocked scraper GET was never killed"
    )
    assert result["outcome"] == "PauseRequested", result
