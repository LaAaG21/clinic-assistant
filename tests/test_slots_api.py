"""GET /slots (#76). PostgreSQL tests need TEST_DATABASE_URL; no model key used.

The route's connection factory and settings are overridden so requests run
inside the throwaway schema from conftest.py, with Asia/Muscat as clinic time.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from functools import partial
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from clinic_assistant.database import DatabaseSettings
from clinic_assistant.main import app
from clinic_assistant.settings import AppSettings, get_settings
from clinic_assistant.slots_api import (
    connection_factory,
    decode_cursor,
    encode_cursor,
)

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]
TZ = "Asia/Muscat"
SETTINGS = AppSettings(DatabaseSettings(url="postgresql://unused"), TZ)
DERMATOLOGY_NOV_3 = "/slots?specialty=dermatology&date=2026-11-03"


@contextmanager
def client_with(factory: Callable[[], Connect]) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[connection_factory] = factory
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(schema_db: Connect) -> Iterator[TestClient]:
    """Three dermatology slots and one cardiology slot on Nov 3 (Muscat)."""
    with schema_db() as conn:
        conn.execute(
            "INSERT INTO doctors VALUES ('doctor_derm', 'Dr. A', 'dermatology'),"
            " ('doctor_cardio', 'Dr. C', 'cardiology')"
        )
        for slot_id, doctor_id, local in [
            ("slot_1", "doctor_derm", "2026-11-03T09:00"),
            ("slot_2", "doctor_derm", "2026-11-03T10:00"),
            ("slot_3", "doctor_derm", "2026-11-03T11:00"),
            ("slot_c", "doctor_cardio", "2026-11-03T09:00"),
        ]:
            conn.execute(
                "INSERT INTO slots VALUES (%s, %s, %s::timestamp AT TIME ZONE %s,"
                " (%s::timestamp + interval '30 minutes') AT TIME ZONE %s)",
                (slot_id, doctor_id, local, TZ, local, TZ),
            )
        conn.execute("INSERT INTO conversations (conversation_id) VALUES ('conv_1')")
    with client_with(lambda: schema_db) as test_client:
        yield test_client


def slot_ids(body: dict[str, Any]) -> list[str]:
    return [slot["slot_id"] for slot in body["slots"]]


def test_returns_matching_slots_in_clinic_time(client: TestClient) -> None:
    response = client.get(DERMATOLOGY_NOV_3)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["clinic_timezone"] == TZ
    assert body["next_cursor"] is None
    assert slot_ids(body) == ["slot_1", "slot_2", "slot_3"]
    assert body["slots"][0] == {
        "slot_id": "slot_1",
        "doctor_id": "doctor_derm",
        "specialty": "dermatology",
        "starts_at": "2026-11-03T09:00:00+04:00",
        "ends_at": "2026-11-03T09:30:00+04:00",
    }


def test_doctor_and_specialty_intersection(client: TestClient) -> None:
    body = client.get(
        "/slots?doctor_id=doctor_cardio&specialty=dermatology&date=2026-11-03"
    ).json()
    assert body["slots"] == []


def test_pages_follow_next_cursor_without_gaps_or_repeats(client: TestClient) -> None:
    query = {"specialty": "dermatology", "date": "2026-11-03", "limit": "2"}
    first = client.get("/slots", params=query).json()
    assert slot_ids(first) == ["slot_1", "slot_2"]
    assert first["next_cursor"] is not None

    second = client.get(
        "/slots", params={**query, "cursor": first["next_cursor"]}
    ).json()
    assert slot_ids(second) == ["slot_3"]
    assert second["next_cursor"] is None


def test_booked_slot_is_hidden(client: TestClient, schema_db: Connect) -> None:
    with schema_db() as conn:
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
            " VALUES ('booking_1', 'slot_2', 'conv_1')"
        )
    assert slot_ids(client.get(DERMATOLOGY_NOV_3).json()) == ["slot_1", "slot_3"]


def test_no_match_returns_empty_list(client: TestClient) -> None:
    response = client.get("/slots?specialty=neurology&date=2026-11-03")
    assert response.status_code == 200
    assert response.json() == {
        "clinic_timezone": TZ,
        "slots": [],
        "next_cursor": None,
    }


def _must_not_connect() -> Connect:
    def connect() -> AbstractContextManager[Conn]:
        raise AssertionError("invalid input must not reach the database")

    return connect


@pytest.mark.parametrize(
    "query",
    [
        "date=2026-11-03",  # no doctor or specialty
        "specialty=%20%20&date=2026-11-03",  # blank specialty
        "doctor_id=%20&date=2026-11-03",  # blank doctor
        "specialty=dermatology",  # missing date
        "specialty=dermatology&date=2026-13-01",  # invalid date
        "specialty=dermatology&date=2026-11-03&limit=0",
        "specialty=dermatology&date=2026-11-03&limit=101",
        "specialty=dermatology&date=2026-11-03&cursor=not-a-cursor",
        "specialty=dermatology&date=2026-11-03&cursor=e30",  # base64 of {}
    ],
)
def test_invalid_input_returns_shared_422_before_any_query(query: str) -> None:
    with client_with(_must_not_connect) as client:
        response = client.get(f"/slots?{query}")
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
        response = client.get(DERMATOLOGY_NOV_3)
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert "down" not in response.text and "timeout" not in body["error"]["message"]


def test_cursor_round_trip_and_rejects_naive_time() -> None:
    position = (datetime.fromisoformat("2026-11-03T05:00:00+00:00"), "slot_1")
    assert decode_cursor(encode_cursor(position)) == position
    naive = encode_cursor((datetime(2026, 11, 3, 5, 0), "slot_1"))
    with pytest.raises(ValueError):
        decode_cursor(naive)


def test_slots_route_is_in_openapi() -> None:
    schema = app.openapi()
    parameters = {p["name"] for p in schema["paths"]["/slots"]["get"]["parameters"]}
    assert parameters == {"date", "doctor_id", "specialty", "limit", "cursor"}


def test_connection_factory_uses_configured_database() -> None:
    factory = connection_factory(SETTINGS)
    assert isinstance(factory, partial)
    assert factory.args == (SETTINGS.database,)
