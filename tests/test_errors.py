"""Exercise the production handlers through test-only HTTP routes."""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from clinic_assistant.errors import (
    DependencyFailure,
    RequestConflict,
    register_error_handlers,
)
from clinic_assistant.main import app as production_app
from clinic_assistant.messages import PatientMessageRequest

SECRET = "private-patient-and-password-marker"
VALID = {"client_message_id": "db138ddb-b0b0-41d2-bc52-bd777fa5f322", "text": "Hi"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/message")
    def message(body: PatientMessageRequest) -> PatientMessageRequest:
        return body

    @app.get("/http/{status}")
    def http_error(status: int) -> None:
        raise HTTPException(
            status,
            detail={"secret": SECRET},
            headers={
                "WWW-Authenticate": "Bearer",
                "Retry-After": "10",
                "X-Internal-Debug": SECRET,
            },
        )

    @app.get("/dependency/{kind}")
    def dependency(kind: str) -> None:
        codes = {
            "service": DependencyFailure(),
            "persistence": DependencyFailure("persistence_unavailable"),
            "timeout": DependencyFailure("dependency_timeout"),
        }
        raise codes[kind] from RuntimeError(SECRET)

    @app.get("/unexpected/{kind}")
    def unexpected(kind: str) -> None:
        errors = {
            "runtime": RuntimeError(SECRET),
            "value": ValueError(SECRET),
            "timeout": TimeoutError(SECRET),
            "driver": psycopg.OperationalError(SECRET),
        }
        raise errors[kind]

    @app.get("/conflict/{kind}")
    def conflict(kind: str) -> None:
        errors = {
            "busy": RequestConflict("conversation_busy"),
            "retry": RequestConflict("idempotency_conflict"),
            "decision": RequestConflict("decision_conflict"),
        }
        raise errors[kind] from ValueError(SECRET)

    @app.get("/invalid-response", response_model=PatientMessageRequest)
    def invalid_response() -> dict[str, str]:
        return {"secret": SECRET}

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/emergency")
    def emergency() -> JSONResponse:
        return JSONResponse(
            {
                "reply": "Seek emergency help now.",
                "error": {"code": "persistence_unavailable"},
            },
            status_code=503,
        )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_valid_message_reuses_existing_validation(client: TestClient) -> None:
    response = client.post("/message", json={**VALID, "text": "  Hello  "})
    assert response.status_code == 200
    assert response.json()["text"] == "Hello"


def test_malformed_json_is_400(client: TestClient) -> None:
    response = client.post(
        "/message",
        content='{"text":"' + SECRET,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"
    assert SECRET not in response.text


@pytest.mark.parametrize(
    ("body", "field", "reason"),
    [
        ({"client_message_id": VALID["client_message_id"]}, "text", "required"),
        ({**VALID, "text": " "}, "text", "invalid_length"),
        ({**VALID, "text": SECRET * 200}, "text", "invalid_length"),
        ({**VALID, "text": 123}, "text", "invalid_type"),
        ({**VALID, "text": None}, "text", "invalid_type"),
        ({**VALID, "client_message_id": SECRET}, "client_message_id", "invalid_uuid"),
        ({**VALID, SECRET: SECRET}, "request", "unexpected_field"),
        ([SECRET], "request", "invalid_value"),
    ],
)
def test_validation_is_safe(
    client: TestClient, body: Any, field: str, reason: str
) -> None:
    response = client.post("/message", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {field: reason}
    assert SECRET not in response.text
    assert "input" not in response.json()["error"]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (409, "conflict"),
        (418, "http_error"),
        (422, "validation_error"),
        (429, "too_many_requests"),
        (500, "internal_error"),
        (502, "internal_error"),
        (503, "dependency_unavailable"),
        (504, "dependency_timeout"),
    ],
)
def test_http_errors_preserve_protocol_headers_only(
    client: TestClient, status: int, code: str
) -> None:
    response = client.get(f"/http/{status}")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["retry-after"] == "10"
    assert "x-internal-debug" not in response.headers
    assert SECRET not in response.text


def test_framework_404_and_405(client: TestClient) -> None:
    missing = client.get("/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    wrong_method = client.get("/message")
    assert wrong_method.status_code == 405
    assert wrong_method.headers["allow"] == "POST"
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("busy", "conversation_busy"),
        ("retry", "idempotency_conflict"),
        ("decision", "decision_conflict"),
    ],
)
def test_recognized_conflicts(client: TestClient, kind: str, code: str) -> None:
    response = client.get(f"/conflict/{kind}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert SECRET not in response.text


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("service", 503, "dependency_unavailable"),
        ("persistence", 503, "persistence_unavailable"),
        ("timeout", 504, "dependency_timeout"),
    ],
)
def test_recognized_dependency_failure(
    client: TestClient, kind: str, status: int, code: str
) -> None:
    response = client.get(f"/dependency/{kind}")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert SECRET not in response.text


@pytest.mark.parametrize("kind", ["runtime", "value", "timeout", "driver"])
def test_unexpected_failures_are_generic(client: TestClient, kind: str) -> None:
    response = client.get(f"/unexpected/{kind}")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "fields": {},
        }
    }
    assert SECRET not in response.text


def test_response_validation_is_a_server_error(client: TestClient) -> None:
    response = client.get("/invalid-response")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert SECRET not in response.text


def test_special_responses_are_not_replaced(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    response = client.get("/emergency")
    assert response.status_code == 503
    assert response.json()["reply"] == "Seek emergency help now."


def test_production_app_registers_handlers_without_demo_routes() -> None:
    with TestClient(production_app) as client:
        response = client.get("/message")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert "/message" not in client.get("/openapi.json").json()["paths"]
