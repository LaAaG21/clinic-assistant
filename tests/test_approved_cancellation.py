"""Request-aware approved cancellation, durable replay and races (#67)."""

import threading
from datetime import UTC, datetime
from typing import Literal

import pytest

from clinic_assistant.approvals import create_pending_approval
from clinic_assistant.booking_state import Conn, Connect
from clinic_assistant.cancellation import (
    ApprovedCancellationOutcome,
    cancel_approved_request,
    validate_cancellation_target,
)
from clinic_assistant.decisions import persist_staff_decision
from clinic_assistant.messages import SavedDecision
from clinic_assistant.requests import create_request


def request(
    connect: Connect,
    request_id: str = "r",
    decision: Literal["approve", "reject"] | None = "approve",
) -> None:
    with connect() as conn:
        create_request(
            conn,
            request_id=request_id,
            conversation_id="c1",
            action="cancel",
            booking_id="b1",
        )
        create_pending_approval(
            conn,
            approval_id="approval_" + request_id,
            request_id=request_id,
        )
    if decision is not None:
        persist_staff_decision(
            connect,
            approval_id="approval_" + request_id,
            decision=SavedDecision(
                decision=decision,
                reason="Synthetic staff review",
                decided_at=datetime.now(UTC),
            ),
        )


def cancel(conn: Conn, request_id: str = "r") -> ApprovedCancellationOutcome:
    return cancel_approved_request(
        conn,
        request_id=request_id,
        booking_id="b1",
        conversation_id="c1",
    )


def test_success_and_reconnect_replay_preserve_one_result(approval_db: Connect) -> None:
    request(approval_db)
    with approval_db() as conn:
        assert cancel(conn) == "cancelled"
        first = conn.execute("SELECT status, cancelled_at FROM bookings").fetchone()
        assert first is not None and first[0] == "cancelled" and first[1] is not None
    with approval_db() as conn:
        assert cancel(conn) == "already_completed"
        assert (
            conn.execute("SELECT status, cancelled_at FROM bookings").fetchone()
            == first
        )
        assert conn.execute(
            "SELECT status, outcome_code FROM requests WHERE request_id='r'"
        ).fetchone() == ("completed", "appointment_cancelled")
        assert conn.execute("SELECT count(*) FROM bookings").fetchone() == (1,)


def test_a_different_request_is_a_conflict_not_a_completed_retry(
    approval_db: Connect,
) -> None:
    request(approval_db, "first")
    request(approval_db, "second")
    with approval_db() as conn:
        assert cancel(conn, "first") == "cancelled"
        cancelled_at = conn.execute("SELECT cancelled_at FROM bookings").fetchone()
    with approval_db() as conn:
        assert cancel(conn, "second") == "ineligible_target"
        assert (
            conn.execute("SELECT cancelled_at FROM bookings").fetchone() == cancelled_at
        )
        assert conn.execute(
            "SELECT status, outcome_code FROM requests WHERE request_id='second'"
        ).fetchone() == ("processing", None)


def test_retry_after_rebooking_keeps_the_new_appointment_active(
    approval_db: Connect,
) -> None:
    request(approval_db)
    with approval_db() as conn:
        assert cancel(conn) == "cancelled"
    with approval_db() as conn:
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
            " VALUES ('new', 's1', 'c2')"
        )
        assert cancel(conn) == "already_completed"
        assert conn.execute(
            "SELECT status, cancelled_at FROM bookings WHERE booking_id='new'"
        ).fetchone() == ("booked", None)


@pytest.mark.parametrize(
    "request_id,booking_id,conversation_id",
    [
        ("missing", "b1", "c1"),
        ("r", "missing", "c1"),
        ("r", "b1", "c2"),
        ("r", "another", "c1"),
    ],
)
def test_request_target_identity_must_match(
    approval_db: Connect,
    request_id: str,
    booking_id: str,
    conversation_id: str,
) -> None:
    request(approval_db)
    with approval_db() as conn:
        assert (
            cancel_approved_request(
                conn,
                request_id=request_id,
                booking_id=booking_id,
                conversation_id=conversation_id,
            )
            == "target_not_found"
        )
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchone() == (
            "booked",
            None,
        )


@pytest.mark.parametrize("decision", [None, "reject"])
def test_only_a_durable_approval_can_cancel(
    approval_db: Connect,
    decision: Literal["reject"] | None,
) -> None:
    request(approval_db, decision=decision)
    with approval_db() as conn:
        assert cancel(conn) == "ineligible_target"
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchone() == (
            "booked",
            None,
        )


def test_processing_state_without_an_approval_is_ineligible(
    approval_db: Connect,
) -> None:
    with approval_db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="cancel",
            booking_id="b1",
            status="processing",
        )
        assert cancel(conn) == "ineligible_target"
        assert conn.execute("SELECT status FROM bookings").fetchone() == ("booked",)


@pytest.mark.parametrize(
    "status,code",
    [
        ("pending_approval", None),
        ("rejected", "request_rejected"),
        ("failed", "appointment_not_cancellable"),
        ("completed", "appointment_not_cancellable"),
        ("completed", "appointment_cancelled"),
    ],
)
def test_conflicting_request_states_are_never_reapplied(
    approval_db: Connect,
    status: str,
    code: str | None,
) -> None:
    request(approval_db)
    with approval_db() as conn:
        conn.execute(
            "UPDATE requests SET status=%s, outcome_code=%s WHERE request_id='r'",
            (status, code),
        )
        assert cancel(conn) == "ineligible_target"
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchone() == (
            "booked",
            None,
        )


def test_changed_booking_after_approval_is_not_mistaken_for_replay(
    approval_db: Connect,
) -> None:
    request(approval_db)
    with approval_db() as conn:
        conn.execute("UPDATE bookings SET status='cancelled', cancelled_at=now()")
        original = conn.execute("SELECT cancelled_at FROM bookings").fetchone()
    with approval_db() as conn:
        assert cancel(conn) == "ineligible_target"
        assert conn.execute("SELECT cancelled_at FROM bookings").fetchone() == original


def test_caller_failure_rolls_back_booking_request_and_message(
    approval_db: Connect,
) -> None:
    request(approval_db)
    with pytest.raises(RuntimeError, match="completion failed"), approval_db() as conn:
        assert cancel(conn) == "cancelled"
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text, request_id)"
            " VALUES ('outcome', 'c1', 'assistant', 'Cancelled', 'r')"
        )
        raise RuntimeError("completion failed")
    with approval_db() as conn:
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchone() == (
            "booked",
            None,
        )
        assert conn.execute(
            "SELECT status, outcome_code FROM requests WHERE request_id='r'"
        ).fetchone() == ("processing", None)
        assert conn.execute("SELECT count(*) FROM messages").fetchone() == (0,)
        assert cancel(conn) == "cancelled"


def test_request_aware_cancellation_rejects_autocommit(approval_db: Connect) -> None:
    request(approval_db)
    with approval_db() as conn:
        conn.commit()
        conn.autocommit = True
        with pytest.raises(ValueError, match="caller-owned transaction"):
            cancel(conn)
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchone() == (
            "booked",
            None,
        )


@pytest.mark.parametrize(
    "second_request,expected",
    [("r", "already_completed"), ("different", "ineligible_target")],
)
def test_concurrent_calls_serialize_without_a_second_mutation(
    approval_db: Connect,
    second_request: str,
    expected: str,
) -> None:
    request(approval_db)
    if second_request != "r":
        request(approval_db, second_request)
    started = threading.Event()
    results: dict[str, object] = {}

    def second() -> None:
        try:
            with approval_db() as conn:
                started.set()
                results["outcome"] = cancel(conn, second_request)
        except Exception as error:
            results["error"] = error

    with approval_db() as conn:
        assert cancel(conn) == "cancelled"
        original = conn.execute("SELECT cancelled_at FROM bookings").fetchone()
        racer = threading.Thread(target=second)
        racer.start()
        assert started.wait(timeout=3)
        racer.join(timeout=0.1)
        assert racer.is_alive()
    racer.join(timeout=3)
    assert not racer.is_alive()
    assert "error" not in results
    assert results["outcome"] == expected
    with approval_db() as conn:
        assert conn.execute("SELECT cancelled_at FROM bookings").fetchone() == original


@pytest.mark.parametrize(
    "booking_id,conversation_id,outcome",
    [
        ("b1", "c1", "eligible"),
        ("missing", "c1", "target_not_found"),
        ("b1", "c2", "target_not_found"),
    ],
)
def test_nonmutating_lookup_uses_the_same_target_contract(
    approval_db: Connect,
    booking_id: str,
    conversation_id: str,
    outcome: str,
) -> None:
    with approval_db() as conn:
        assert (
            validate_cancellation_target(
                conn,
                booking_id=booking_id,
                conversation_id=conversation_id,
            )
            == outcome
        )
        assert conn.execute("SELECT status, cancelled_at FROM bookings").fetchone() == (
            "booked",
            None,
        )
