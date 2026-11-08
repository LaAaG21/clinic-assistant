"""Request create/load and integrity tests on real PostgreSQL (#52)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg import errors

from clinic_assistant.requests import create_request, load_request

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


@pytest.fixture
def db(schema_db: Connect) -> Connect:
    with schema_db() as conn:
        conn.execute("INSERT INTO doctors VALUES ('d', 'Dr. Example', 'general')")
        conn.execute(
            "INSERT INTO slots VALUES"
            " ('slot_1', 'd', '2026-11-05T10:00:00Z', '2026-11-05T10:30:00Z'),"
            " ('slot_2', 'd', '2026-11-06T10:00:00Z', '2026-11-06T10:30:00Z')"
        )
        conn.execute(
            "INSERT INTO conversations (conversation_id) VALUES ('c1'), ('c2')"
        )
    return schema_db


def book(conn: Conn) -> None:
    conn.execute(
        "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
        " VALUES ('booking_1', 'slot_1', 'c1')"
    )


def test_pending_booking_persists_without_a_booking(db: Connect) -> None:
    request_id = "request_'_parameterized"
    with db() as conn:
        created = create_request(
            conn,
            request_id=request_id,
            conversation_id="c1",
            action="book",
            slot_id="slot_1",
        )
        assert conn.execute("SELECT count(*) FROM bookings").fetchone() == (0,)
    with db() as conn:
        saved = load_request(conn, request_id)
    assert saved == created
    assert saved is not None
    assert saved.request_id == request_id
    assert saved.conversation_id == "c1"
    assert saved.action == "book"
    assert saved.slot_id == "slot_1"
    assert saved.booking_id is None
    assert saved.status == "pending_approval"
    assert saved.outcome_code is None
    assert saved.created_at.utcoffset() is not None
    assert saved.updated_at == saved.created_at


def test_cancellation_target_persists_across_connections(db: Connect) -> None:
    with db() as conn:
        book(conn)
        created = create_request(
            conn,
            request_id="cancel",
            conversation_id="c1",
            action="cancel",
            booking_id="booking_1",
        )
    with db() as conn:
        assert load_request(conn, "cancel") == created
        assert conn.execute("SELECT status FROM bookings").fetchone() == ("booked",)
    assert created.slot_id is None
    assert created.booking_id == "booking_1"


def test_load_missing_request(db: Connect) -> None:
    with db() as conn:
        assert load_request(conn, "missing") is None
        assert load_request(conn, "' OR true --") is None


@pytest.mark.parametrize(
    "status,outcome_code",
    [
        ("pending_approval", None),
        ("processing", None),
        ("completed", "appointment_booked"),
        ("rejected", "request_rejected"),
        ("failed", "slot_unavailable"),
    ],
)
def test_supported_states(db: Connect, status: str, outcome_code: str | None) -> None:
    with db() as conn:
        book(conn)
        conn.execute(
            "INSERT INTO requests"
            " (request_id, conversation_id, action, slot_id, booking_id,"
            " status, outcome_code) VALUES ('r', 'c1', 'book', 'slot_1', %s, %s, %s)",
            ("booking_1" if status == "completed" else None, status, outcome_code),
        )
    with db() as conn:
        saved = load_request(conn, "r")
    assert saved is not None
    assert saved.status == status
    assert saved.outcome_code == outcome_code


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"request_id": ""}, errors.CheckViolation),
        ({"request_id": " "}, errors.CheckViolation),
        ({"request_id": None}, errors.NotNullViolation),
        ({"conversation_id": None}, errors.NotNullViolation),
        ({"conversation_id": "missing"}, errors.ForeignKeyViolation),
        ({"action": None}, errors.NotNullViolation),
        ({"action": "unknown"}, errors.CheckViolation),
        ({"slot_id": None}, errors.CheckViolation),
        ({"slot_id": "missing"}, errors.ForeignKeyViolation),
        ({"status": None}, errors.NotNullViolation),
        ({"status": "unknown"}, errors.CheckViolation),
        (
            {"status": "completed", "outcome_code": "appointment_booked"},
            errors.CheckViolation,
        ),
        ({"outcome_code": "premature"}, errors.CheckViolation),
        ({"status": "processing", "outcome_code": "premature"}, errors.CheckViolation),
        ({"status": "failed"}, errors.CheckViolation),
        ({"status": "rejected", "outcome_code": " "}, errors.CheckViolation),
        ({"status": "completed", "booking_id": "booking_1"}, errors.CheckViolation),
        ({"booking_id": "booking_1"}, errors.CheckViolation),
    ],
)
def test_invalid_request_values(
    db: Connect, changes: dict[str, Any], expected: type[psycopg.Error]
) -> None:
    values: dict[str, Any] = {
        "request_id": "r",
        "conversation_id": "c1",
        "action": "book",
        "slot_id": "slot_1",
        "booking_id": None,
        "status": "pending_approval",
        "outcome_code": None,
    }
    values.update(changes)
    with db() as conn:
        book(conn)
    with pytest.raises(expected), db() as conn:
        conn.execute(
            "INSERT INTO requests"
            " (request_id, conversation_id, action, slot_id, booking_id,"
            " status, outcome_code) VALUES"
            " (%(request_id)s, %(conversation_id)s, %(action)s, %(slot_id)s,"
            " %(booking_id)s, %(status)s, %(outcome_code)s)",
            values,
        )


@pytest.mark.parametrize(
    "conversation_id,booking_id,slot_id,expected",
    [
        ("c1", None, None, errors.CheckViolation),
        ("c1", "missing", None, errors.ForeignKeyViolation),
        ("c2", "booking_1", None, errors.ForeignKeyViolation),
        ("c1", "booking_1", "slot_1", errors.CheckViolation),
    ],
)
def test_invalid_cancellation_targets(
    db: Connect,
    conversation_id: str,
    booking_id: str | None,
    slot_id: str | None,
    expected: type[psycopg.Error],
) -> None:
    with db() as conn:
        book(conn)
    with pytest.raises(expected), db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id=conversation_id,
            action="cancel",
            booking_id=booking_id,
            slot_id=slot_id,
        )


def test_booking_result_must_match_slot_and_conversation(db: Connect) -> None:
    with db() as conn:
        book(conn)
    for conversation, slot in (("c2", "slot_1"), ("c1", "slot_2")):
        with pytest.raises(errors.ForeignKeyViolation), db() as conn:
            create_request(
                conn,
                request_id="r",
                conversation_id=conversation,
                action="book",
                slot_id=slot,
                booking_id="booking_1",
                status="completed",
                outcome_code="appointment_booked",
            )


def test_duplicate_id_preserves_original_request(db: Connect) -> None:
    with db() as conn:
        original = create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="book",
            slot_id="slot_1",
        )
    with pytest.raises(errors.UniqueViolation), db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c2",
            action="book",
            slot_id="slot_2",
        )
    with db() as conn:
        assert load_request(conn, "r") == original


def test_caller_can_roll_back_request_creation(db: Connect) -> None:
    with pytest.raises(RuntimeError, match="rollback"), db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="book",
            slot_id="slot_1",
        )
        raise RuntimeError("rollback")
    with db() as conn:
        assert load_request(conn, "r") is None


def test_updated_at_cannot_precede_created_at(db: Connect) -> None:
    with pytest.raises(errors.CheckViolation), db() as conn:
        conn.execute(
            "INSERT INTO requests"
            " (request_id, conversation_id, action, slot_id, created_at, updated_at)"
            " VALUES ('r', 'c1', 'book', 'slot_1', %s, %s)",
            (datetime(2026, 11, 5, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC)),
        )
