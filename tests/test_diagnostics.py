"""Captured-log checks: useful failure context, no secrets, unchanged responses."""

import logging
from collections.abc import Iterator

import httpx
import psycopg
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from openai import APITimeoutError

from clinic_assistant.diagnostics import describe, log_failure, request_id
from clinic_assistant.errors import DependencyFailure, register_error_handlers
from clinic_assistant.messages import PatientMessageRequest

KEY = "sk-synthetic-provider-key-marker"
DSN = "postgresql://clinic:synthetic-password-marker@db:5432/clinic"
PATIENT_TEXT = "private patient message marker"
SECRETS = (KEY, "synthetic-password-marker", PATIENT_TEXT)
LOGGER = "clinic_assistant.diagnostics"


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/conversations/{conversation_id}/messages")
    def message(conversation_id: str, body: PatientMessageRequest) -> None:
        raise DependencyFailure("dependency_timeout") from APITimeoutError(
            request=httpx.Request("POST", f"https://api.example/v1?key={KEY}")
        )

    @app.get("/persistence")
    def persistence() -> None:
        raise DependencyFailure(
            "persistence_unavailable"
        ) from psycopg.OperationalError(f"connection failed: {DSN}")

    @app.get("/driver")
    def driver() -> None:
        raise psycopg.OperationalError(f"connection failed: {DSN} {PATIENT_TEXT}")

    @app.get("/http/{status}")
    def http_error(status: int) -> None:
        raise HTTPException(status, detail=PATIENT_TEXT)

    @app.get("/emergency")
    def emergency(request: Request) -> JSONResponse:
        # A controlled consumer of the emergency degradation contract (#6): the
        # safety reply still goes out, the persistence failure is logged safely.
        try:
            raise DependencyFailure("persistence_unavailable") from RuntimeError(DSN)
        except DependencyFailure as exc:
            log_failure(
                request,
                "emergency_flag_persistence",
                exc.code,
                exc.__cause__,
                level=logging.ERROR,
            )
        return JSONResponse(
            {
                "reply": "Seek emergency help now. Do not wait for a chat reply.",
                "error": {"code": "persistence_unavailable"},
            },
            status_code=503,
        )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_no_secrets(*texts: str) -> None:
    for text in texts:
        for secret in SECRETS:
            assert secret not in text


def test_dependency_timeout_is_a_warning_with_context(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = client.post(
        "/conversations/conv_1/messages",
        json={
            "client_message_id": "db138ddb-b0b0-41d2-bc52-bd777fa5f322",
            "text": PATIENT_TEXT,
        },
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "dependency_timeout"
    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "event=dependency_failure code=dependency_timeout" in record.message
    assert (
        "method=POST route=/conversations/{conversation_id}/messages" in record.message
    )
    assert "cause=openai.APITimeoutError" in record.message
    assert f"request_id={response.headers['x-request-id']}" in record.message
    assert "conv_1" not in record.message
    assert_no_secrets(record.message, response.text)


def test_unconfirmed_persistence_is_an_error(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = client.get("/persistence")
    assert response.status_code == 503
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "code=persistence_unavailable" in record.message
    assert "cause=psycopg.OperationalError" in record.message
    assert_no_secrets(record.message, response.text)


def test_unexpected_driver_failure_logs_type_and_location_only(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = client.get("/driver")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "event=unexpected_failure code=internal_error" in record.message
    assert "route=/driver" in record.message
    assert "cause=psycopg.OperationalError at test_diagnostics.py:" in record.message
    assert "in driver" in record.message
    assert_no_secrets(record.message, response.text)


@pytest.mark.parametrize(
    ("status", "level", "logged"), [(502, logging.ERROR, True), (404, None, False)]
)
def test_only_server_side_http_errors_are_logged(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    status: int,
    level: int | None,
    logged: bool,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = client.get(f"/http/{status}")
    assert response.status_code == status
    assert [r.levelno for r in caplog.records] == ([level] if logged else [])
    if logged:
        assert f"event=http_{status} code=internal_error" in caplog.text
    assert_no_secrets(caplog.text, response.text)


def test_unmatched_route_and_validation_log_nothing_sensitive(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    missing = client.get(f"/missing/{PATIENT_TEXT}")
    assert missing.status_code == 404
    invalid = client.post("/conversations/conv_1/messages", json={"text": PATIENT_TEXT})
    assert invalid.status_code == 422
    assert caplog.records == []
    assert_no_secrets(missing.text, invalid.text)
    assert "x-request-id" in missing.headers and "x-request-id" in invalid.headers


def test_emergency_persistence_failure_keeps_reply_and_logs_safely(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = client.get("/emergency")
    assert response.status_code == 503
    assert response.json() == {
        "reply": "Seek emergency help now. Do not wait for a chat reply.",
        "error": {"code": "persistence_unavailable"},
    }
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "event=emergency_flag_persistence code=persistence_unavailable" in (
        record.message
    )
    assert "cause=builtins.RuntimeError" in record.message
    assert_no_secrets(record.message)


@pytest.mark.parametrize(
    ("supplied", "reused"),
    [
        ("client-trace-0042", True),
        ("", False),
        ("a" * 65, False),
        (f"bad id {KEY}", False),
    ],
)
def test_request_id_reuses_only_safe_client_values(
    client: TestClient, caplog: pytest.LogCaptureFixture, supplied: str, reused: bool
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = client.get("/driver", headers={"X-Request-ID": supplied})
    returned = response.headers["x-request-id"]
    assert (returned == supplied) is reused
    if not reused:
        assert len(returned) == 32 and returned.isalnum()
    assert f"request_id={returned}" in caplog.text
    assert_no_secrets(caplog.text)


def test_request_id_is_stable_within_one_request() -> None:
    captured: list[str] = []
    app = FastAPI()

    @app.get("/twice")
    def twice(request: Request) -> dict[str, str]:
        captured.extend([request_id(request), request_id(request)])
        return {}

    with TestClient(app) as test_client:
        test_client.get("/twice")
    assert len(captured) == 2 and captured[0] == captured[1]


def test_describe_without_traceback_names_the_type_only() -> None:
    assert describe(ValueError(KEY)) == "builtins.ValueError"


def test_log_failure_without_request(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    log_failure(None, "background_job", "dependency_unavailable", level=logging.INFO)
    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert record.message == "event=background_job code=dependency_unavailable"
