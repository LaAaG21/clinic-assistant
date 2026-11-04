"""Bookings schema (#39) on real PostgreSQL.

Set TEST_DATABASE_URL to run. The `schema_db` fixture (conftest.py) applies the
db/init files in their own schema and drops it afterwards.
"""

import threading
from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg
import pytest
from psycopg import errors

from clinic_assistant.cancellation import cancel_approved_booking

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


@pytest.fixture
def db(schema_db: Connect) -> Connect:
    """Schema with one doctor, one slot and two conversations."""
    with schema_db() as conn:
        conn.execute("INSERT INTO doctors VALUES ('doctor_1', 'Dr. A', 'dermatology')")
        conn.execute(
            "INSERT INTO slots VALUES ('slot_1', 'doctor_1',"
            " '2026-11-04T10:00:00+04:00', '2026-11-04T10:30:00+04:00')"
        )
        conn.execute(
            "INSERT INTO conversations (conversation_id) VALUES ('conv_1'), ('conv_2')"
        )
    return schema_db


def book(
    conn: Conn,
    booking_id: str,
    conversation_id: str = "conv_1",
    slot_id: str = "slot_1",
) -> None:
    conn.execute(
        "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
        " VALUES (%s, %s, %s)",
        (booking_id, slot_id, conversation_id),
    )


def cancel(conn: Conn, booking_id: str) -> None:
    conn.execute(
        "UPDATE bookings SET status = 'cancelled', cancelled_at = now()"
        " WHERE booking_id = %s",
        (booking_id,),
    )


def constraint_of(error: pytest.ExceptionInfo[psycopg.Error]) -> str | None:
    return error.value.diag.constraint_name


def test_new_booking_is_active(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1")
    with db() as conn:
        row = conn.execute(
            "SELECT status, created_at IS NOT NULL, cancelled_at FROM bookings"
        ).fetchone()
    assert row == ("booked", True, None)


def test_second_active_booking_for_a_slot_is_rejected(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1")
    with pytest.raises(errors.UniqueViolation) as error, db() as conn:
        book(conn, "booking_2", "conv_2")
    assert constraint_of(error) == "bookings_one_active_per_slot"


def test_cancelled_slot_can_be_booked_again(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1")
        cancel(conn, "booking_1")
        book(conn, "booking_2", "conv_2")
    with db() as conn:
        rows = conn.execute(
            "SELECT booking_id, status FROM bookings ORDER BY booking_id"
        ).fetchall()
    assert rows == [("booking_1", "cancelled"), ("booking_2", "booked")]
    # The rebooked slot is active again, so a third active booking is rejected.
    with pytest.raises(errors.UniqueViolation), db() as conn:
        book(conn, "booking_3")


def test_concurrent_bookings_for_one_slot_have_one_winner(db: Connect) -> None:
    """Two transactions race for the same slot; PostgreSQL lets only one commit."""
    outcome: dict[str, BaseException] = {}

    def second_request() -> None:
        try:
            with db() as conn:
                book(conn, "booking_2", "conv_2")
        except psycopg.Error as exc:
            outcome["error"] = exc

    with db() as first:
        book(first, "booking_1")  # inserted, not yet committed
        racer = threading.Thread(target=second_request)
        racer.start()
        racer.join(timeout=0.3)
        assert racer.is_alive()  # waits on the first, uncommitted row
    # Leaving the block commits the first booking and releases the second.
    racer.join(timeout=5)
    assert isinstance(outcome.get("error"), errors.UniqueViolation)
    with db() as conn:
        rows = conn.execute("SELECT booking_id FROM bookings").fetchall()
    assert rows == [("booking_1",)]


def test_duplicate_booking_id_is_rejected(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1")
        cancel(conn, "booking_1")
    with pytest.raises(errors.UniqueViolation) as error, db() as conn:
        book(conn, "booking_1", "conv_2")
    assert constraint_of(error) == "bookings_pkey"


@pytest.mark.parametrize(
    ("slot_id", "conversation_id", "constraint"),
    [
        ("slot_missing", "conv_1", "bookings_slot_id_fkey"),
        ("slot_1", "conv_missing", "bookings_conversation_id_fkey"),
    ],
)
def test_booking_needs_existing_slot_and_conversation(
    db: Connect, slot_id: str, conversation_id: str, constraint: str
) -> None:
    with pytest.raises(errors.ForeignKeyViolation) as error, db() as conn:
        book(conn, "booking_1", conversation_id, slot_id)
    assert constraint_of(error) == constraint


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("booking_id", " ", errors.CheckViolation),
        ("booking_id", None, errors.NotNullViolation),
        ("slot_id", None, errors.NotNullViolation),
        ("conversation_id", None, errors.NotNullViolation),
        ("status", "pending", errors.CheckViolation),
    ],
)
def test_booking_required_values(
    db: Connect, column: str, value: str | None, expected: type[psycopg.Error]
) -> None:
    booking: dict[str, str | None] = {
        "booking_id": "booking_1",
        "slot_id": "slot_1",
        "conversation_id": "conv_1",
        "status": "booked",
    }
    booking[column] = value
    with pytest.raises(expected), db() as conn:
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id, status)"
            " VALUES (%(booking_id)s, %(slot_id)s, %(conversation_id)s, %(status)s)",
            booking,
        )


@pytest.mark.parametrize(
    ("status", "cancelled_at"),
    [("cancelled", None), ("booked", "2026-11-04T09:00:00+04:00")],
)
def test_cancelled_at_matches_status(
    db: Connect, status: str, cancelled_at: str | None
) -> None:
    with pytest.raises(errors.CheckViolation) as error, db() as conn:
        conn.execute(
            "INSERT INTO bookings"
            " (booking_id, slot_id, conversation_id, status, cancelled_at)"
            " VALUES ('booking_1', 'slot_1', 'conv_1', %s, %s)",
            (status, cancelled_at),
        )
    assert constraint_of(error) == "bookings_cancelled_at_matches_status"


def test_approved_cancellation_changes_booking_once(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1")
        result = cancel_approved_booking(
            conn, booking_id="booking_1", conversation_id="conv_1"
        )
        assert result == "cancelled"

    query = "SELECT status, cancelled_at FROM bookings WHERE booking_id = 'booking_1'"
    with db() as conn:
        first = conn.execute(query).fetchone()
        assert first is not None
        assert first[0] == "cancelled"
        assert first[1] is not None
        retry = cancel_approved_booking(
            conn, booking_id="booking_1", conversation_id="conv_1"
        )
        # Request-level replay belongs to the completion contract.
        assert retry == "ineligible_target"
        assert conn.execute(query).fetchone() == first


@pytest.mark.parametrize(
    ("booking_id", "conversation_id"),
    [("missing", "conv_1"), ("booking_1", "conv_2")],
)
def test_cancellation_rejects_missing_or_wrong_conversation(
    db: Connect, booking_id: str, conversation_id: str
) -> None:
    with db() as conn:
        book(conn, "booking_1")
        result = cancel_approved_booking(
            conn, booking_id=booking_id, conversation_id=conversation_id
        )
        assert result == "target_not_found"
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchall() == [
            ("booked", None)
        ]


def test_cancellation_rolls_back_if_completion_fails(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1")

    with pytest.raises(RuntimeError, match="completion failed"), db() as conn:
        assert (
            cancel_approved_booking(
                conn, booking_id="booking_1", conversation_id="conv_1"
            )
            == "cancelled"
        )
        raise RuntimeError("completion failed")

    with db() as conn:
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchall() == [
            ("booked", None)
        ]
