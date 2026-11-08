"""GET /conversations/{id} (#86). PostgreSQL tests need TEST_DATABASE_URL.

Synthetic messages are inserted directly (no workflow or model calls); the route's
connection factory is overridden to use the throwaway schema from conftest.py.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from functools import partial
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from clinic_assistant.database import DatabaseSettings
from clinic_assistant.history import (
    connection_factory,
    decode_cursor,
    encode_cursor,
)
from clinic_assistant.main import app
from clinic_assistant.settings import AppSettings

Conn = psycopg.Connection[tuple[object, ...]]
# #81's proposed default model window (PR #132, not on this branch yet).
MODEL_WINDOW = 10
Connect = Callable[[], AbstractContextManager[Conn]]
CITATION = {
    "source_id": "doc_hours",
    "source_name": "Clinic opening hours",
    "passage_id": "hours_1",
}


@contextmanager
def client_with(factory: Callable[[], Connect]) -> Iterator[TestClient]:
    app.dependency_overrides[connection_factory] = factory
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def add_message(
    conn: Conn,
    message_id: str,
    role: str,
    text: str,
    at: str,
    *,
    conversation_id: str = "conv_1",
    request_id: str | None = None,
    citations: list[dict[str, str]] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (message_id, conversation_id, role, text,"
        " client_message_id, request_id, created_at, citations)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        (
            message_id,
            conversation_id,
            role,
            text,
            uuid4() if role == "patient" else None,
            request_id,
            at,
            json.dumps(citations or []),
        ),
    )


@pytest.fixture
def db(schema_db: Connect) -> Connect:
    """conv_1: a booking with a staff outcome, then a cited answer; conv_empty."""
    with schema_db() as conn:
        conn.execute("INSERT INTO doctors VALUES ('doctor_1', 'Dr. A', 'dermatology')")
        conn.execute(
            "INSERT INTO slots VALUES ('slot_1', 'doctor_1',"
            " '2026-11-09T09:00:00+04:00', '2026-11-09T09:30:00+04:00')"
        )
        conn.execute(
            "INSERT INTO conversations (conversation_id)"
            " VALUES ('conv_1'), ('conv_empty')"
        )
        conn.execute(
            "INSERT INTO requests (request_id, conversation_id, action, slot_id)"
            " VALUES ('req_1', 'conv_1', 'book', 'slot_1')"
        )
        base = "2026-11-08T09:00:0{}+04:00"
        add_message(
            conn, "msg_1", "patient", "Book slot_1", base.format(0), request_id="req_1"
        )
        add_message(
            conn,
            "msg_2",
            "assistant",
            "Waiting for staff approval.",
            base.format(1),
            request_id="req_1",
        )
        add_message(
            conn,
            "msg_3",
            "assistant",
            "Staff approved. Booked.",
            base.format(5),
            request_id="req_1",
        )
        add_message(conn, "msg_4", "patient", "When do you open?", base.format(6))
        add_message(
            conn,
            "msg_5",
            "assistant",
            "At 09:00.",
            base.format(7),
            citations=[CITATION],
        )
    return schema_db


@pytest.fixture
def client(db: Connect) -> Iterator[TestClient]:
    with client_with(lambda: db) as test_client:
        yield test_client


def ids(body: dict[str, Any]) -> list[str]:
    return [m["message_id"] for m in body["messages"]]


def test_full_history_in_order_with_links_and_citations(client: TestClient) -> None:
    response = client.get("/conversations/conv_1")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["conversation_id"] == "conv_1"
    assert body["next_cursor"] is None
    assert ids(body) == ["msg_1", "msg_2", "msg_3", "msg_4", "msg_5"]
    first, outcome, cited = (
        body["messages"][0],
        body["messages"][2],
        body["messages"][4],
    )
    assert first["role"] == "patient" and first["request_id"] == "req_1"
    assert outcome == {
        "message_id": "msg_3",
        "role": "assistant",
        "text": "Staff approved. Booked.",
        "created_at": "2026-11-08T05:00:05Z",
        "citations": [],
        "request_id": "req_1",
    }
    assert cited["citations"] == [CITATION]


def test_new_conversation_has_empty_history(client: TestClient) -> None:
    response = client.get("/conversations/conv_empty")
    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "conv_empty",
        "messages": [],
        "next_cursor": None,
    }


def test_unknown_conversation_is_404(client: TestClient) -> None:
    response = client.get("/conversations/conv_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_pages_cover_history_without_gaps_or_repeats(client: TestClient) -> None:
    seen: list[str] = []
    params: dict[str, str] = {"limit": "2"}
    pages = 0
    while True:
        body = client.get("/conversations/conv_1", params=params).json()
        seen += ids(body)
        pages += 1
        if body["next_cursor"] is None:
            break
        params["cursor"] = body["next_cursor"]
    assert pages == 3
    assert seen == ["msg_1", "msg_2", "msg_3", "msg_4", "msg_5"]


def test_same_timestamp_is_ordered_by_message_id(
    db: Connect, client: TestClient
) -> None:
    with db() as conn:
        at = "2026-11-08T10:00:00+04:00"
        add_message(conn, "msg_b", "assistant", "Second by id.", at)
        add_message(conn, "msg_a", "assistant", "First by id.", at)
    assert ids(client.get("/conversations/conv_1").json())[-2:] == ["msg_a", "msg_b"]


def test_history_is_complete_beyond_the_model_window(
    db: Connect, client: TestClient
) -> None:
    """The API returns every stored message, not #81's recent model window."""
    count = MODEL_WINDOW + 5
    with db() as conn:
        conn.execute("INSERT INTO conversations (conversation_id) VALUES ('conv_long')")
        for n in range(count):
            add_message(
                conn,
                f"msg_{n:02d}",
                "patient" if n % 2 == 0 else "assistant",
                f"turn {n}",
                f"2026-11-08T11:{n:02d}:00+04:00",
                conversation_id="conv_long",
            )
    body = client.get("/conversations/conv_long").json()
    assert len(body["messages"]) == count


def test_reading_changes_nothing(db: Connect, client: TestClient) -> None:
    def snapshot() -> list[tuple[object, ...]]:
        with db() as conn:
            return conn.execute(
                "SELECT message_id, text FROM messages ORDER BY message_id"
            ).fetchall()

    before = snapshot()
    client.get("/conversations/conv_1")
    client.get("/conversations/conv_1", params={"limit": "1"})
    assert snapshot() == before


def _must_not_connect() -> Connect:
    def connect() -> AbstractContextManager[Conn]:
        raise AssertionError("invalid input must not reach the database")

    return connect


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "limit=ten", "cursor=nope", "cursor=e30"]
)
def test_invalid_paging_returns_shared_422(query: str) -> None:
    with client_with(_must_not_connect) as client:
        response = client.get(f"/conversations/conv_1?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (psycopg.OperationalError("down"), 503, "dependency_unavailable"),
        (psycopg.errors.QueryCanceled("timeout"), 504, "dependency_timeout"),
    ],
)
def test_database_failure_returns_shared_error(
    error: psycopg.Error, status: int, code: str
) -> None:
    def failing_factory() -> Connect:
        def connect() -> AbstractContextManager[Conn]:
            raise error

        return connect

    with client_with(failing_factory) as client:
        response = client.get("/conversations/conv_1")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "down" not in response.text


def test_cursor_round_trip_and_rejects_naive_time() -> None:
    position = (datetime.fromisoformat("2026-11-08T05:00:05+00:00"), "msg_3")
    assert decode_cursor(encode_cursor(position)) == position
    with pytest.raises(ValueError):
        decode_cursor(encode_cursor((datetime(2026, 11, 8, 5, 0, 5), "msg_3")))


def test_connection_factory_uses_configured_database() -> None:
    settings = AppSettings(DatabaseSettings(url="postgresql://unused"), "Asia/Muscat")
    factory = connection_factory(settings)
    assert isinstance(factory, partial)
    assert factory.args == (settings.database,)
