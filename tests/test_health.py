"""HTTP checks using the real shared probe and a dedicated PostgreSQL database."""

import os
import socket
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from clinic_assistant.main import app


def test_health_with_real_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("DB_QUERY_TIMEOUT_MS", "1000")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "api": "reachable",
        "database": "reachable",
    }
    assert response.headers["cache-control"] == "no-store"


def test_health_with_unavailable_database(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        monkeypatch.setenv(
            "DATABASE_URL",
            f"postgresql://synthetic:secret-marker@127.0.0.1:{port}/missing",
        )
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "2")
        monkeypatch.setenv("DB_QUERY_TIMEOUT_MS", "50")
        with TestClient(app) as client:
            started = monotonic()
            response = client.get("/health")
            elapsed = monotonic() - started
    assert elapsed < 5
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "api": "reachable",
        "database": "unreachable",
    }
    assert response.headers["cache-control"] == "no-store"
    assert "secret-marker" not in response.text + caplog.text
    assert "Health probe failed: unavailable" in caplog.text


@pytest.mark.parametrize("invalid_timeout", [None, "secret-marker"])
def test_health_with_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    invalid_timeout: str | None,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if invalid_timeout is not None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://unused:secret-marker@host/db")
        monkeypatch.setenv("DB_QUERY_TIMEOUT_MS", invalid_timeout)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "api": "reachable",
        "database": "unreachable",
    }
    assert "secret-marker" not in response.text + caplog.text
    assert "Health probe failed: configuration_error" in caplog.text


def test_health_openapi_includes_both_outcomes() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()
    responses = document["paths"]["/health"]["get"]["responses"]
    for code in ("200", "503"):
        assert responses[code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/HealthResponse"
        }
