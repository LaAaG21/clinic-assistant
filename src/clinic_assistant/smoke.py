"""Smoke checks for a running service: health, OpenAPI and conversation creation.

Run ``python -m clinic_assistant.smoke --base-url http://127.0.0.1:8000``. Uses only
the standard library, so it needs no model key or database credentials. Every
check runs and is reported; the exit status is 0 only when all of them passed.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import Message
from typing import IO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 60.0
MAX_BODY_BYTES = 1_000_000
EXIT_OK = 0
EXIT_FAILED = 1  # argparse exits 2 for invalid arguments

HEALTHY = {"status": "ok", "api": "reachable", "database": "reachable"}


class SmokeFailure(Exception):
    """A check's assertion failed; the message is safe to print."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None

    def json(self) -> object:
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SmokeFailure(f"HTTP {self.status} body is not valid JSON") from exc


class _NoRedirect(HTTPRedirectHandler):
    """Report redirects as responses instead of silently following them."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class Client:
    """Minimal JSON HTTP client with a per-operation socket timeout."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener: OpenerDirector = build_opener(_NoRedirect)

    def request(
        self, method: str, path: str, payload: object | None = None
    ) -> HttpResponse:
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return _read(resp.status, resp.headers, resp)
        except HTTPError as exc:
            with exc:
                return _read(exc.code, exc.headers, exc)
        except (URLError, OSError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            raise SmokeFailure(
                f"{method} {path} failed: {type(reason).__name__}"
            ) from exc


def _read(status: int, headers: Message, stream: IO[bytes]) -> HttpResponse:
    body = stream.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise SmokeFailure(f"HTTP {status} body exceeds {MAX_BODY_BYTES} bytes")
    return HttpResponse(status=status, headers=dict(headers.items()), body=body)


def _expect_status(response: HttpResponse, expected: int, what: str) -> None:
    if response.status != expected:
        raise SmokeFailure(f"{what}: expected HTTP {expected}, got {response.status}")


def check_health(client: Client) -> str:
    response = client.request("GET", "/health")
    _expect_status(response, 200, "GET /health")
    body = response.json()
    if body != HEALTHY:
        raise SmokeFailure("GET /health: body is not the agreed healthy response")
    if response.header("Cache-Control") != "no-store":
        raise SmokeFailure("GET /health: Cache-Control is not no-store")
    return "API and database reachable"


def check_openapi(client: Client) -> str:
    response = client.request("GET", "/openapi.json")
    _expect_status(response, 200, "GET /openapi.json")
    spec = response.json()
    if not isinstance(spec, dict):
        raise SmokeFailure("GET /openapi.json: document is not a JSON object")
    version = spec.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise SmokeFailure("GET /openapi.json: missing OpenAPI 3.x version field")
    info = spec.get("info")
    if not isinstance(info, dict) or not info.get("title") or "version" not in info:
        raise SmokeFailure("GET /openapi.json: missing info.title or info.version")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise SmokeFailure("GET /openapi.json: missing paths object")
    for path, method in (("/health", "get"), ("/conversations", "post")):
        operations = paths.get(path)
        if not isinstance(operations, dict) or method not in operations:
            raise SmokeFailure(
                f"GET /openapi.json: {method.upper()} {path} is not documented"
            )
    return f"OpenAPI {version} documents GET /health and POST /conversations"


def check_create_conversation(client: Client) -> str:
    response = client.request("POST", "/conversations", payload={})
    _expect_status(response, 201, "POST /conversations")
    body = response.json()
    if not isinstance(body, dict):
        raise SmokeFailure("POST /conversations: body is not a JSON object")
    conversation_id = body.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise SmokeFailure("POST /conversations: missing conversation_id")
    created_at = body.get("created_at")
    if not isinstance(created_at, str) or not _is_aware_timestamp(created_at):
        raise SmokeFailure(
            "POST /conversations: created_at is not an ISO 8601 time with offset"
        )
    location = response.header("Location")
    expected_path = "/conversations/" + quote(conversation_id, safe="")
    if location is None or urlsplit(location).path.rstrip("/") != expected_path:
        raise SmokeFailure(
            "POST /conversations: Location header does not point to the conversation"
        )
    content_type = response.header("Content-Type") or ""
    if not content_type.lower().startswith("application/json"):
        raise SmokeFailure("POST /conversations: Content-Type is not application/json")
    return "created a synthetic empty conversation with a valid Location"


def _is_aware_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


Check = Callable[[Client], str]
CHECKS: tuple[tuple[str, Check], ...] = (
    ("health", check_health),
    ("openapi", check_openapi),
    ("create-conversation", check_create_conversation),
)


def run_checks(client: Client, out: IO[str]) -> bool:
    passed = True
    for name, check in CHECKS:
        try:
            detail = check(client)
        except SmokeFailure as exc:
            passed = False
            print(f"FAIL {name}: {exc}", file=out)
        else:
            print(f"PASS {name}: {detail}", file=out)
    return passed


def _base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise argparse.ArgumentTypeError("must be an http(s) URL with a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise argparse.ArgumentTypeError(
            "must not contain credentials, a query or a fragment"
        )
    return value


def _timeout(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number of seconds") from exc
    if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be greater than 0 and at most {MAX_TIMEOUT_SECONDS:g}"
        )
    return seconds


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m clinic_assistant.smoke",
        description="Smoke-check a running clinic-assistant service.",
    )
    parser.add_argument(
        "--base-url",
        type=_base_url,
        default=os.getenv("SMOKE_BASE_URL", DEFAULT_BASE_URL),
        help="service root URL (default: $SMOKE_BASE_URL or %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="per-request socket timeout in seconds (default: %(default)s)",
    )
    # argparse also applies `type` to the string default from $SMOKE_BASE_URL.
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, out: IO[str] | None = None) -> int:
    stream = sys.stdout if out is None else out
    args = parse_args(argv)
    client = Client(args.base_url, args.timeout)
    host = urlsplit(args.base_url)
    print(f"Smoke-checking {host.scheme}://{host.netloc}{host.path}", file=stream)
    if run_checks(client, stream):
        print("All smoke checks passed.", file=stream)
        return EXIT_OK
    print("Smoke checks failed.", file=stream)
    return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
