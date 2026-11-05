"""Smoke-script checks against a local fake service; no database or model needed."""

import io
import json
import socket
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic

import pytest

from clinic_assistant import smoke
from clinic_assistant.main import app

Reply = tuple[int, dict[str, str], bytes]
Route = Callable[[], Reply]


def _json(status: int, body: object, **headers: str) -> Reply:
    return (
        status,
        {"Content-Type": "application/json", **headers},
        json.dumps(body).encode(),
    )


def _openapi() -> dict[str, object]:
    spec = app.openapi()
    paths = dict(spec["paths"])
    paths.setdefault("/conversations", {"post": {"responses": {"201": {}}}})
    return {**spec, "paths": paths}


def healthy_routes() -> dict[tuple[str, str], Route]:
    return {
        ("GET", "/health"): lambda: _json(
            200, smoke.HEALTHY, **{"Cache-Control": "no-store"}
        ),
        ("GET", "/openapi.json"): lambda: _json(200, _openapi()),
        ("POST", "/conversations"): lambda: _json(
            201,
            {"conversation_id": "conv_smoke", "created_at": "2026-11-05T09:00:00Z"},
            Location="/conversations/conv_smoke",
        ),
    }


class FakeService:
    def __init__(self) -> None:
        self.routes = healthy_routes()
        self.requests: list[tuple[str, str, bytes]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                service.requests.append(
                    (self.command, self.path, self.rfile.read(length))
                )
                route = service.routes.get((self.command, self.path))
                status, headers, body = (
                    route() if route else _json(404, {"error": "not_found"})
                )
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _handle
            do_POST = _handle

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    thread = threading.Thread(target=fake.server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        fake.server.shutdown()
        fake.server.server_close()


def run(url: str, *extra: str) -> tuple[int, str]:
    out = io.StringIO()
    code = smoke.main(["--base-url", url, "--timeout", "2", *extra], out=out)
    return code, out.getvalue()


def test_all_checks_pass_against_healthy_service(service: FakeService) -> None:
    code, output = run(service.url + "/")
    assert code == 0
    assert "PASS health" in output
    assert "PASS openapi" in output
    assert "PASS create-conversation" in output
    assert "All smoke checks passed." in output
    post = [r for r in service.requests if r[0] == "POST"]
    assert post == [("POST", "/conversations", b"{}")]


def test_missing_conversation_endpoint_fails(service: FakeService) -> None:
    del service.routes[("POST", "/conversations")]
    code, output = run(service.url)
    assert code == 1
    assert "PASS health" in output
    assert (
        "FAIL create-conversation: POST /conversations: expected HTTP 201, got 404"
        in output
    )
    assert "SKIP" not in output
    assert "Smoke checks failed." in output


def test_real_openapi_without_conversations_route_fails(
    service: FakeService,
) -> None:
    service.routes[("GET", "/openapi.json")] = lambda: _json(200, app.openapi())
    code, output = run(service.url)
    assert code == 1
    assert "FAIL openapi: GET /openapi.json: POST /conversations is not documented" in (
        output
    )


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (
            _json(
                503,
                {"status": "unavailable", "api": "reachable", "database": "x"},
            ),
            "expected HTTP 200, got 503",
        ),
        (_json(200, {"status": "ok"}), "not the agreed healthy response"),
        (_json(200, smoke.HEALTHY), "Cache-Control is not no-store"),
        ((200, {}, b"<html>"), "body is not valid JSON"),
    ],
)
def test_bad_health_responses_fail(
    service: FakeService, reply: Reply, message: str
) -> None:
    service.routes[("GET", "/health")] = lambda: reply
    code, output = run(service.url)
    assert code == 1
    assert "FAIL health" in output
    assert message in output


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ([], "not a JSON object"),
        ({"openapi": "2.0"}, "missing OpenAPI 3.x version field"),
        ({"openapi": "3.1.0", "info": {}}, "missing info.title"),
        (
            {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}},
            "missing paths object",
        ),
    ],
)
def test_invalid_openapi_fails(
    service: FakeService, spec: object, message: str
) -> None:
    service.routes[("GET", "/openapi.json")] = lambda: _json(200, spec)
    code, output = run(service.url)
    assert code == 1
    assert message in output


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (_json(200, {}), "expected HTTP 201, got 200"),
        (_json(201, []), "body is not a JSON object"),
        (_json(201, {"conversation_id": " "}), "missing conversation_id"),
        (
            _json(201, {"conversation_id": "c1", "created_at": "2026-11-05T09:00"}),
            "created_at is not an ISO 8601 time with offset",
        ),
        (
            _json(201, {"conversation_id": "c1", "created_at": "yesterday"}),
            "created_at is not an ISO 8601 time with offset",
        ),
        (
            _json(201, {"conversation_id": "c1", "created_at": "2026-11-05T09:00Z"}),
            "Location header does not point to the conversation",
        ),
        (
            _json(
                201,
                {"conversation_id": "c1", "created_at": "2026-11-05T09:00Z"},
                Location="/conversations/other",
            ),
            "Location header does not point to the conversation",
        ),
        (
            (
                201,
                {"Location": "/conversations/c1", "Content-Type": "text/plain"},
                b'{"conversation_id": "c1", "created_at": "2026-11-05T09:00Z"}',
            ),
            "Content-Type is not application/json",
        ),
    ],
)
def test_bad_conversation_responses_fail(
    service: FakeService, reply: Reply, message: str
) -> None:
    service.routes[("POST", "/conversations")] = lambda: reply
    code, output = run(service.url)
    assert code == 1
    assert "FAIL create-conversation" in output
    assert message in output


def test_absolute_location_is_accepted(service: FakeService) -> None:
    service.routes[("POST", "/conversations")] = lambda: _json(
        201,
        {"conversation_id": "c1", "created_at": "2026-11-05T13:00:00+04:00"},
        Location=f"{service.url}/conversations/c1",
    )
    code, output = run(service.url)
    assert code == 0, output


def test_redirect_is_reported_not_followed(service: FakeService) -> None:
    service.routes[("GET", "/health")] = lambda: (302, {"Location": "/elsewhere"}, b"")
    code, output = run(service.url)
    assert code == 1
    assert "FAIL health: GET /health: expected HTTP 200, got 302" in output


def test_oversized_body_fails(service: FakeService) -> None:
    big = b" " * (smoke.MAX_BODY_BYTES + 1)
    service.routes[("GET", "/health")] = lambda: (200, {}, big)
    code, output = run(service.url)
    assert code == 1
    assert "body exceeds" in output


def test_unreachable_service_fails_quickly() -> None:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        started = monotonic()
        code, output = run(f"http://127.0.0.1:{port}")
        elapsed = monotonic() - started
    assert code == 1
    assert elapsed < 10
    assert output.count("FAIL") == 3
    assert "PASS" not in output


def test_unresponsive_service_times_out() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        out = io.StringIO()
        started = monotonic()
        code = smoke.main(
            ["--base-url", f"http://127.0.0.1:{port}", "--timeout", "0.2"], out=out
        )
        elapsed = monotonic() - started
    assert code == 1
    assert elapsed < 5
    assert "FAIL health: GET /health failed: TimeoutError" in out.getvalue()


@pytest.mark.parametrize(
    "argv",
    [
        ["--base-url", "ftp://example.test"],
        ["--base-url", "http://user:secret@example.test"],
        ["--base-url", "http://example.test/?q=1"],
        ["--timeout", "0"],
        ["--timeout", "61"],
        ["--timeout", "soon"],
    ],
)
def test_invalid_arguments_exit_with_usage_error(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        smoke.main(argv, out=io.StringIO())
    assert exc.value.code == 2


def test_invalid_environment_base_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", "not a url")
    with pytest.raises(SystemExit) as exc:
        smoke.main([], out=io.StringIO())
    assert exc.value.code == 2


def test_environment_base_url_is_used(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", service.url)
    out = io.StringIO()
    assert smoke.main([], out=out) == 0
    assert service.url in out.getvalue()
