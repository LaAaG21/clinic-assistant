"""Pending-approval HTTP reads using real PostgreSQL datasets (#45)."""

import base64
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from clinic_assistant import database
from clinic_assistant.approvals import create_pending_approval
from clinic_assistant.main import app
from clinic_assistant.requests import create_request
from clinic_assistant.staff_approvals import approval_connection

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


@pytest.fixture
def client(approval_db: Connect) -> Iterator[TestClient]:
    def connect() -> Iterator[Conn]:
        with approval_db() as conn:
            yield conn

    original = app.dependency_overrides.copy()
    app.dependency_overrides[approval_connection] = connect
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


def pending(conn: Conn, approval_id: str) -> None:
    create_request(
        conn,
        request_id="r_" + approval_id,
        conversation_id="c2",
        action="book",
        slot_id="s2",
    )
    create_pending_approval(
        conn,
        approval_id=approval_id,
        request_id="r_" + approval_id,
    )


def snapshot(conn: Conn) -> tuple[list[tuple[object, ...]], ...]:
    return (
        conn.execute("SELECT * FROM requests ORDER BY request_id").fetchall(),
        conn.execute("SELECT * FROM approvals ORDER BY approval_id").fetchall(),
        conn.execute("SELECT * FROM bookings ORDER BY booking_id").fetchall(),
    )


def test_pending_results_preserve_targets_and_do_only_reads(
    client: TestClient,
    approval_db: Connect,
) -> None:
    with approval_db() as conn:
        pending(conn, "book")
        create_request(
            conn,
            request_id="r_cancel",
            conversation_id="c1",
            action="cancel",
            booking_id="b1",
        )
        create_pending_approval(conn, approval_id="cancel", request_id="r_cancel")
        before = snapshot(conn)
    response = client.get("/staff/approvals")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["next_cursor"] is None
    items = {item["approval_id"]: item for item in body["items"]}
    assert len(items) == 2
    assert items["book"]["request_id"] == "r_book"
    assert items["book"]["conversation_id"] == "c2"
    assert items["book"]["action"] == "book"
    assert items["book"]["target"] == {"slot_id": "s2"}
    assert items["cancel"]["request_id"] == "r_cancel"
    assert items["cancel"]["conversation_id"] == "c1"
    assert items["cancel"]["action"] == "cancel"
    assert items["cancel"]["target"] == {"appointment_id": "b1"}
    assert set(items["book"]) == {
        "approval_id",
        "request_id",
        "conversation_id",
        "action",
        "target",
        "created_at",
    }
    assert datetime.fromisoformat(items["book"]["created_at"]).utcoffset() is not None
    with approval_db() as conn:
        assert snapshot(conn) == before


def test_empty_results(client: TestClient) -> None:
    response = client.get("/staff/approvals")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_decided_records_are_not_listed(
    client: TestClient,
    approval_db: Connect,
    decision: str,
) -> None:
    with approval_db() as conn:
        pending(conn, "decided")
        pending(conn, "pending")
        conn.execute(
            "UPDATE approvals SET decision=%s, reason='Reviewed', decided_at=now()"
            " WHERE approval_id='decided'",
            (decision,),
        )
    body = client.get("/staff/approvals").json()
    assert [item["approval_id"] for item in body["items"]] == ["pending"]
    assert body["next_cursor"] is None


def test_pagination_orders_by_time_then_id_and_survives_deciding_anchor(
    client: TestClient,
    approval_db: Connect,
) -> None:
    with approval_db() as conn:
        for approval_id, created_at in (
            ("d", "2000-01-03T00:00:00Z"),
            ("c", "2000-01-02T00:00:00Z"),
            ("b", "2000-01-01T00:00:00Z"),
            ("a", "2000-01-02T00:00:00Z"),
        ):
            pending(conn, approval_id)
            conn.execute(
                "UPDATE approvals SET created_at=%s WHERE approval_id=%s",
                (created_at, approval_id),
            )
    first = client.get("/staff/approvals", params={"limit": 2}).json()
    assert [item["approval_id"] for item in first["items"]] == ["b", "a"]
    assert isinstance(first["next_cursor"], str)
    with approval_db() as conn:
        conn.execute(
            "UPDATE approvals SET decision='reject', reason='Reviewed',"
            " decided_at=now() WHERE approval_id='a'"
        )
    response = client.get(
        "/staff/approvals",
        params={"limit": 2, "cursor": first["next_cursor"]},
    )
    assert response.status_code == 200
    last = response.json()
    assert [item["approval_id"] for item in last["items"]] == ["c", "d"]
    assert last["next_cursor"] is None
    with approval_db() as conn:
        conn.execute(
            "UPDATE approvals SET decision='approve', reason='Reviewed',"
            " decided_at=now()"
        )
    assert client.get(
        "/staff/approvals",
        params={"cursor": first["next_cursor"]},
    ).json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("limit,expected", [(None, 50), (1, 1), (100, 100)])
def test_default_and_boundary_limits(
    client: TestClient,
    approval_db: Connect,
    limit: int | None,
    expected: int,
) -> None:
    with approval_db() as conn:
        conn.execute(
            "INSERT INTO requests (request_id, conversation_id, action, slot_id)"
            " SELECT 'r' || i, 'c2', 'book', 's2' FROM generate_series(1, 101) i"
        )
        conn.execute(
            "INSERT INTO approvals (approval_id, request_id)"
            " SELECT 'a' || lpad(i::text, 3, '0'), 'r' || i"
            " FROM generate_series(1, 101) i"
        )
    params = {} if limit is None else {"limit": limit}
    response = client.get("/staff/approvals", params=params)
    assert response.status_code == 200
    assert len(response.json()["items"]) == expected
    assert response.json()["next_cursor"] is not None


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "-1"},
        {"limit": "1.5"},
        {"limit": "bad"},
        {"limit": ""},
        {"limit": "true"},
        {"cursor": ""},
        {"cursor": "!"},
        {"cursor": "x" * 4097},
        {"cursor": base64.urlsafe_b64encode(b"{}").decode()},
        {
            "cursor": base64.urlsafe_b64encode(
                b'{"version":"2","created_at":"2000-01-01T00:00:00Z","approval_id":"a"}'
            ).decode()
        },
        {
            "cursor": base64.urlsafe_b64encode(
                b'{"version":"1","created_at":"2000-01-01T00:00:00","approval_id":"a"}'
            ).decode()
        },
    ],
)
def test_invalid_pagination_returns_safe_validation_error(
    client: TestClient,
    params: dict[str, str],
) -> None:
    response = client.get("/staff/approvals", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "traceback" not in response.text.lower()


def test_openapi_contains_route_response_and_page_limits() -> None:
    spec = app.openapi()
    validate(spec)
    operation = spec["paths"]["/staff/approvals"]["get"]
    parameters = {item["name"]: item["schema"] for item in operation["parameters"]}
    assert parameters["limit"]["default"] == 50
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 100
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/PendingApprovalsResponse")
    schemas = spec["components"]["schemas"]
    assert (
        schemas["PendingApprovalsResponse"]["properties"]["items"]["items"][
            "discriminator"
        ]["propertyName"]
        == "action"
    )


@pytest.mark.parametrize(
    "error,status,code",
    [
        (psycopg.OperationalError, 503, "dependency_unavailable"),
        (psycopg.InterfaceError, 503, "dependency_unavailable"),
        (psycopg.errors.QueryCanceled, 504, "dependency_timeout"),
    ],
)
def test_database_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
    error: type[psycopg.Error],
    status: int,
    code: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-only")

    @contextmanager
    def unavailable(*args: Any, **kwargs: Any) -> Iterator[Conn]:
        raise error("private-database-error-marker")
        yield  # pragma: no cover

    monkeypatch.setattr(database, "connection", unavailable)
    with TestClient(app) as test_client:
        response = test_client.get("/staff/approvals")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private-database-error-marker" not in response.text


def test_missing_database_configuration_returns_safe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as test_client:
        response = test_client.get("/staff/approvals")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
