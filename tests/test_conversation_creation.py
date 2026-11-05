"""Conversation creation commits a server-generated identity (#44)."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from clinic_assistant.conversations import conversation_connection
from clinic_assistant.main import app

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


def test_creation_is_committed_and_ids_are_distinct(schema_db: Connect) -> None:
    def connect() -> Iterator[Conn]:
        with schema_db() as conn:
            yield conn

    app.dependency_overrides[conversation_connection] = connect
    try:
        with TestClient(app) as client:
            first = client.post("/conversations", json={})
            second = client.post("/conversations", json={})
            assert first.status_code == second.status_code == 201
            assert first.json()["conversation_id"] != second.json()["conversation_id"]
            for response in (first, second):
                body = response.json()
                assert (
                    response.headers["location"]
                    == "/conversations/" + body["conversation_id"]
                )
                with schema_db() as conn:
                    saved = conn.execute(
                        "SELECT created_at FROM conversations WHERE conversation_id=%s",
                        (body["conversation_id"],),
                    ).fetchone()
                assert saved == (datetime.fromisoformat(body["created_at"]),)
            assert (
                client.post(
                    "/conversations",
                    json={"conversation_id": "client-chosen"},
                ).status_code
                == 422
            )
    finally:
        app.dependency_overrides.pop(conversation_connection)


def test_unavailable_database_has_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        response = client.post("/conversations", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "persistence_unavailable"
