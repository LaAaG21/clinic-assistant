import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from clinic_assistant.api import create_app
from clinic_assistant.database import database_is_ready

pytestmark = pytest.mark.integration


def test_readiness_requires_a_successful_postgresql_query(database_url: str) -> None:
    assert database_is_ready(database_url)
    with TestClient(create_app(database_url=database_url)) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reads_database_url_from_environment(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    with TestClient(create_app()) as client:
        response = client.get("/ready")
    assert response.status_code == 200


def test_database_connection_failure_returns_unavailable(database_url: str) -> None:
    invalid_url = make_conninfo(database_url, dbname="clinic_missing_readiness_test")
    assert not database_is_ready(invalid_url)
    with TestClient(create_app(database_url=invalid_url)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert "clinic_missing_readiness_test" not in response.text
