"""Atomic request-owned booking insertion on PostgreSQL (#61)."""

from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg
import pytest

from clinic_assistant.bookings import insert_booking
from clinic_assistant.requests import create_request, load_request

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


def request(conn: Conn, slot: str = "s2", status: str = "processing") -> None:
    conn.execute(
        "INSERT INTO requests (request_id, conversation_id, action, slot_id, status)"
        " VALUES ('r', 'c1', 'book', %s, %s)",
        (slot, status),
    )


def test_atomic_insert_and_reconnect_retry(approval_db: Connect) -> None:
    with approval_db() as conn:
        request(conn)
        first = insert_booking(conn, request_id="r")
        assert first is not None
    with approval_db() as conn:
        assert insert_booking(conn, request_id="r") == first
        saved = load_request(conn, "r")
        assert saved is not None and saved.booking_id == first
        assert conn.execute(
            "SELECT count(*) FROM bookings WHERE slot_id='s2'"
        ).fetchone() == (1,)


def test_active_slot_conflict_keeps_transaction_usable(approval_db: Connect) -> None:
    with approval_db() as conn:
        request(conn, slot="s1")
        assert insert_booking(conn, request_id="r") is None
        assert conn.execute("SELECT 1").fetchone() == (1,)
        saved = load_request(conn, "r")
        assert saved is not None and saved.booking_id is None


def test_rollback_removes_mutation_and_request_result(approval_db: Connect) -> None:
    with approval_db() as conn:
        request(conn)
    with pytest.raises(RuntimeError), approval_db() as conn:
        insert_booking(conn, request_id="r")
        raise RuntimeError("synthetic rollback")
    with approval_db() as conn:
        saved = load_request(conn, "r")
        assert saved is not None and saved.booking_id is None
        assert conn.execute(
            "SELECT count(*) FROM bookings WHERE slot_id='s2'"
        ).fetchone() == (0,)


def test_pending_approval_cannot_mutate_and_missing_request_fails(
    approval_db: Connect,
) -> None:
    with approval_db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="book",
            slot_id="s2",
        )
        with pytest.raises(ValueError, match="not ready"):
            insert_booking(conn, request_id="r")
        with pytest.raises(LookupError):
            insert_booking(conn, request_id="missing")
