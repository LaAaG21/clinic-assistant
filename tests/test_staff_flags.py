"""GET /staff/flags (#60) on real PostgreSQL through the production app.

The route's connection factory is overridden so the endpoint reads the
throwaway schema created by `schema_db` (set TEST_DATABASE_URL).
"""

import base64
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from clinic_assistant.main import app
from clinic_assistant.staff_flags import get_connect

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]
SECRET = "synthetic-dsn-password-marker"
PATIENT_TEXT = "private patient message marker"


@pytest.fixture
def db(schema_db: Connect) -> Iterator[Connect]:
    with schema_db() as conn:
        conn.execute(
            "INSERT INTO conversations (conversation_id) VALUES ('conv_a'), ('conv_b')"
        )
    app.dependency_overrides[get_connect] = lambda: schema_db
    yield schema_db
    app.dependency_overrides.clear()


@pytest.fixture
def client(db: Connect) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def add_flag(
    connect: Connect, flag_id: str, conversation_id: str, created_at: str
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO emergency_flags"
            " (flag_id, conversation_id, message_id, created_at)"
            " VALUES (%s, %s, %s, %s)",
            (flag_id, conversation_id, f"msg_{flag_id}", created_at),
        )


def ids(page: dict[str, object]) -> list[str]:
    items = page["items"]
    assert isinstance(items, list)
    return [item["flag_id"] for item in items]


def test_empty_list(client: TestClient) -> None:
    response = client.get("/staff/flags")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_flags_are_listed_newest_first_with_agreed_fields(
    client: TestClient, db: Connect
) -> None:
    add_flag(db, "flag_old", "conv_a", "2026-11-05T08:00:00+00:00")
    add_flag(db, "flag_new", "conv_b", "2026-11-05T13:30:00+04:00")
    response = client.get("/staff/flags")
    assert response.status_code == 200
    page = response.json()
    assert ids(page) == ["flag_new", "flag_old"]
    newest = page["items"][0]
    assert datetime.fromisoformat(newest.pop("created_at")) == datetime(
        2026, 11, 5, 9, 30, tzinfo=UTC
    )
    assert newest == {
        "flag_id": "flag_new",
        "conversation_id": "conv_b",
        "message_id": "msg_flag_new",
    }
    assert page["next_cursor"] is None
    assert PATIENT_TEXT not in response.text


def test_pagination_follows_the_cursor_without_gaps_or_repeats(
    client: TestClient, db: Connect
) -> None:
    same_instant = "2026-11-05T10:00:00+00:00"
    add_flag(db, "flag_c", "conv_a", same_instant)
    add_flag(db, "flag_a", "conv_a", same_instant)
    add_flag(db, "flag_b", "conv_b", same_instant)
    add_flag(db, "flag_older", "conv_b", "2026-11-04T10:00:00+00:00")
    first = client.get("/staff/flags", params={"limit": 2}).json()
    assert ids(first) == ["flag_a", "flag_b"] and first["next_cursor"]
    second = client.get(
        "/staff/flags", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert ids(second) == ["flag_c", "flag_older"] and second["next_cursor"] is None


def test_exact_page_boundary_has_no_empty_trailing_page(
    client: TestClient, db: Connect
) -> None:
    add_flag(db, "flag_1", "conv_a", "2026-11-05T10:00:00+00:00")
    add_flag(db, "flag_2", "conv_a", "2026-11-05T11:00:00+00:00")
    page = client.get("/staff/flags", params={"limit": 2}).json()
    assert ids(page) == ["flag_2", "flag_1"] and page["next_cursor"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "ten"},
        {"cursor": "not-base64!"},
        {"cursor": base64.urlsafe_b64encode(b'["2026-11-05T10:00:00", "f"]').decode()},
        {"cursor": base64.urlsafe_b64encode(b'{"created_at": 1}').decode()},
        {
            "cursor": base64.urlsafe_b64encode(
                b'["2026-11-05T10:00:00+00:00", ""]'
            ).decode()
        },
    ],
)
def test_invalid_limit_or_cursor_is_422(
    client: TestClient, params: dict[str, str | int]
) -> None:
    response = client.get("/staff/flags", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_database_failure_is_a_safe_503(
    db: Connect, caplog: pytest.LogCaptureFixture
) -> None:
    @contextmanager
    def failing() -> Iterator[Conn]:
        raise psycopg.OperationalError(f"connection failed: password={SECRET}")
        yield  # pragma: no cover

    app.dependency_overrides[get_connect] = lambda: failing
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/staff/flags")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert SECRET not in response.text + caplog.text


def test_reading_flags_changes_nothing(client: TestClient, db: Connect) -> None:
    with db() as conn:
        conn.execute("INSERT INTO doctors VALUES ('doctor_1', 'Dr. A', 'dermatology')")
        conn.execute(
            "INSERT INTO slots VALUES ('slot_1', 'doctor_1',"
            " '2026-11-06T10:00:00+04:00', '2026-11-06T10:30:00+04:00')"
        )
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
            " VALUES ('booking_1', 'slot_1', 'conv_a')"
        )
    add_flag(db, "flag_1", "conv_a", "2026-11-05T10:00:00+00:00")

    def snapshot() -> list[tuple[object, ...]]:
        with db() as conn:
            return conn.execute(
                "SELECT booking_id, status, cancelled_at FROM bookings"
                " UNION ALL SELECT flag_id, message_id, created_at FROM emergency_flags"
                " ORDER BY 1"
            ).fetchall()

    before = snapshot()
    for _ in range(2):
        assert client.get("/staff/flags").status_code == 200
    assert (
        snapshot()
        == before
        == [
            ("booking_1", "booked", None),
            ("flag_1", "msg_flag_1", datetime(2026, 11, 5, 10, 0, tzinfo=UTC)),
        ]
    )


def test_openapi_documents_the_route() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()
    operation = document["paths"]["/staff/flags"]["get"]
    assert {p["name"] for p in operation["parameters"]} == {"limit", "cursor"}
    assert "503" in operation["responses"]
