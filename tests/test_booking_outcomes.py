"""Booking success/conflict/replay and dependency outcomes (#66)."""

from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg
import pytest

from clinic_assistant import booking_outcomes
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.requests import create_request

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


@pytest.mark.parametrize(
    "slot,code", [("s2", "appointment_booked"), ("s1", "slot_unavailable")]
)
def test_outcome_and_repeat(
    approval_db: Connect,
    slot: str,
    code: str,
) -> None:
    with approval_db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="book",
            slot_id=slot,
            status="processing",
        )
        first = booking_outcomes.book_request(conn, request_id="r")
    with approval_db() as conn:
        repeated = booking_outcomes.book_request(conn, request_id="r")
        assert repeated == first
        assert first.code == code
        assert (first.booking_id is not None) == (code == "appointment_booked")


@pytest.mark.parametrize(
    "error,code",
    [
        (psycopg.OperationalError, "dependency_unavailable"),
        (psycopg.InterfaceError, "dependency_unavailable"),
        (psycopg.errors.QueryCanceled, "dependency_timeout"),
    ],
)
def test_dependency_failure_is_distinct_from_slot_conflict(
    approval_db: Connect,
    monkeypatch: pytest.MonkeyPatch,
    error: type[psycopg.Error],
    code: str,
) -> None:
    def fail(conn: Conn, *, request_id: str) -> str | None:
        raise error("synthetic private driver detail")

    monkeypatch.setattr(booking_outcomes, "insert_booking", fail)
    with approval_db() as conn, pytest.raises(DependencyFailure) as captured:
        booking_outcomes.book_request(conn, request_id="r")
    assert captured.value.code == code
    assert "private" not in str(captured.value)
