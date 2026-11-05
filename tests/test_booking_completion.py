"""Production approval/resume, durable outcomes and failure recovery (#62)."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from clinic_assistant import booking_completion, booking_workflow
from clinic_assistant.booking_outcomes import BookingOutcome, book_request
from clinic_assistant.booking_state import BookingState, Conn, Connect
from clinic_assistant.booking_workflow import (
    BookingGraph,
    build_booking_graph,
    resume_booking,
    start_booking,
)
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.decisions import persist_staff_decision
from clinic_assistant.errors import RequestConflict
from clinic_assistant.messages import SavedDecision
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage
from clinic_assistant.thread_identity import thread_config


@contextmanager
def workflow(
    connect: Connect,
    checkpoint: tuple[DatabaseSettings, str],
) -> Iterator[BookingGraph]:
    settings, schema = checkpoint
    with postgres_checkpointer(settings, schema=schema) as saver:
        yield build_booking_graph(
            connect,
            saver,
            clinic_timezone="Asia/Muscat",
            clock=lambda: datetime.fromisoformat("2026-11-06T00:00:00Z"),
        )


def pause(graph: BookingGraph, connect: Connect, conversation: str = "c1") -> str:
    result = start_booking(
        graph,
        connect,
        conversation_id=conversation,
        request_id="r_" + conversation,
        slot_id="s2",
    )
    assert result["status"] == "pending_approval"
    assert result["approval_id"] is not None
    return result["approval_id"]


@pytest.mark.parametrize(
    "decision,occupied,status,code",
    [
        ("approve", False, "completed", "appointment_booked"),
        ("reject", False, "rejected", "request_rejected"),
        ("approve", True, "failed", "slot_unavailable"),
    ],
)
def test_resume_saves_outcome_and_identical_retry(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    decision: str,
    occupied: bool,
    status: str,
    code: str,
) -> None:
    fake = FakeModelAdapter("  Staff reviewed the target.  ")
    reason = asyncio.run(fake.generate((ModelMessage("user", "Review"),)))
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        if occupied:
            with approval_db() as conn:
                conn.execute(
                    "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
                    " VALUES ('other', 's2', 'c2')"
                )
        result = resume_booking(
            graph,
            approval_db,
            approval_id=approval_id,
            decision=decision,
            reason=reason,
        )
        assert result["status"] == status
        assert result["outcome_code"] == code
        with approval_db() as conn:
            saved_decision = conn.execute(
                "SELECT decision, reason, decided_at FROM approvals"
                " WHERE approval_id=%s",
                (approval_id,),
            ).fetchone()
            assert saved_decision is not None
            assert saved_decision[:2] == (decision, reason.strip())
            assert saved_decision[2] is not None
            assert not graph.get_state(thread_config(conn, "c1")).next
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision=decision,
                reason=reason.strip(),
            )
            == result
        )
    with approval_db() as conn:
        assert (
            conn.execute(
                "SELECT decision, reason, decided_at FROM approvals"
                " WHERE approval_id=%s",
                (approval_id,),
            ).fetchone()
            == saved_decision
        )
        assert conn.execute(
            "SELECT text FROM messages WHERE request_id='r_c1' AND role='assistant'"
        ).fetchall() == [(result["patient_message"],)]
        assert conn.execute(
            "SELECT count(*) FROM bookings WHERE slot_id='s2' AND conversation_id='c1'"
        ).fetchone() == (1 if status == "completed" else 0,)


@pytest.mark.parametrize(
    "decision,reason",
    [("reject", "Reviewed"), ("approve", "Different reason")],
)
def test_conflicting_decisions_preserve_original_result(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    decision: str,
    reason: str,
) -> None:
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        original = resume_booking(
            graph,
            approval_db,
            approval_id=approval_id,
            decision="approve",
            reason="Reviewed",
        )
        with pytest.raises(RequestConflict) as captured:
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision=decision,
                reason=reason,
            )
        assert captured.value.code == "decision_conflict"
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision="approve",
                reason="Reviewed",
            )
            == original
        )


def test_reconnect_after_decision_commit_before_resume(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        persist_staff_decision(
            approval_db,
            approval_id=approval_id,
            decision=SavedDecision(
                decision="approve",
                reason="Reviewed",
                decided_at=datetime.now(UTC),
            ),
        )
    with workflow(approval_db, checkpoint_db) as graph:
        result = resume_booking(
            graph,
            approval_db,
            approval_id=approval_id,
            decision="approve",
            reason="Reviewed",
        )
    assert result["status"] == "completed"


def test_replay_after_committed_outcome_never_repeats_mutation(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_book = book_request
    actual_complete = booking_completion.complete_booking
    calls: list[str] = []

    def book(conn: Conn, *, request_id: str) -> BookingOutcome:
        calls.append(request_id)
        return actual_book(conn, request_id=request_id)

    def fail_after_commit(connect: Connect, *, request_id: str) -> BookingState:
        actual_complete(connect, request_id=request_id)
        raise RuntimeError("synthetic post-commit failure")

    monkeypatch.setattr(booking_completion, "book_request", book)
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        with monkeypatch.context() as scoped:
            scoped.setattr(booking_workflow, "complete_booking", fail_after_commit)
            with pytest.raises(RuntimeError, match="post-commit"):
                resume_booking(
                    graph,
                    approval_db,
                    approval_id=approval_id,
                    decision="approve",
                    reason="Reviewed",
                )
    with workflow(approval_db, checkpoint_db) as graph:
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision="approve",
                reason="Reviewed",
            )["status"]
            == "completed"
        )
        with approval_db() as conn:
            assert not graph.get_state(thread_config(conn, "c1")).next
            assert conn.execute(
                "SELECT count(*) FROM messages WHERE request_id='r_c1'"
            ).fetchone() == (1,)
    assert calls == ["r_c1"]


def test_failure_before_outcome_commit_rolls_back_booking_and_message(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_book = book_request

    def fail_after_insert(conn: Conn, *, request_id: str) -> BookingOutcome:
        actual_book(conn, request_id=request_id)
        raise RuntimeError("synthetic pre-commit failure")

    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        with monkeypatch.context() as scoped:
            scoped.setattr(booking_completion, "book_request", fail_after_insert)
            with pytest.raises(RuntimeError, match="pre-commit"):
                resume_booking(
                    graph,
                    approval_db,
                    approval_id=approval_id,
                    decision="approve",
                    reason="Reviewed",
                )
        with approval_db() as conn:
            assert conn.execute(
                "SELECT status, booking_id FROM requests WHERE request_id='r_c1'"
            ).fetchone() == ("processing", None)
            assert conn.execute(
                "SELECT count(*) FROM bookings WHERE slot_id='s2'"
            ).fetchone() == (0,)
            assert conn.execute("SELECT count(*) FROM messages").fetchone() == (0,)
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision="approve",
                reason="Reviewed",
            )["status"]
            == "completed"
        )


def test_direct_resume_cannot_bypass_durable_staff_decision(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        with approval_db() as conn:
            config = thread_config(conn, "c1")
        with pytest.raises(ValueError, match="durable staff decision"):
            graph.invoke(
                Command(resume={"approval_id": approval_id, "request_id": "r_c1"}),
                config,
            )
        with approval_db() as conn:
            assert conn.execute(
                "SELECT count(*) FROM bookings WHERE slot_id='s2'"
            ).fetchone() == (0,)
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision="reject",
                reason="Reviewed",
            )["status"]
            == "rejected"
        )


def test_old_completed_retry_preserves_a_new_pending_thread(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        original = resume_booking(
            graph,
            approval_db,
            approval_id=approval_id,
            decision="approve",
            reason="Reviewed",
        )
        with approval_db() as conn:
            conn.execute(
                "INSERT INTO slots VALUES"
                " ('s3', 'd', '2026-11-06T11:00:00Z', '2026-11-06T11:30:00Z')"
            )
        pending = start_booking(
            graph,
            approval_db,
            conversation_id="c1",
            request_id="new",
            slot_id="s3",
        )
        assert pending["status"] == "pending_approval"
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision="approve",
                reason="Reviewed",
            )
            == original
        )
        assert (
            start_booking(
                graph,
                approval_db,
                conversation_id="c1",
                request_id="new",
                slot_id="s3",
            )
            == pending
        )


def test_decision_resumes_only_its_own_conversation(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with workflow(approval_db, checkpoint_db) as graph:
        first = pause(graph, approval_db, "c1")
        second = pause(graph, approval_db, "c2")
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=second,
                decision="approve",
                reason="Reviewed",
            )["conversation_id"]
            == "c2"
        )
        with approval_db() as conn:
            assert (
                graph.get_state(thread_config(conn, "c1")).values["status"]
                == "pending_approval"
            )
        assert (
            resume_booking(
                graph,
                approval_db,
                approval_id=first,
                decision="approve",
                reason="Reviewed",
            )["outcome_code"]
            == "slot_unavailable"
        )


@pytest.mark.parametrize("decision,reason", [("unknown", "Reviewed"), ("approve", " ")])
def test_invalid_decisions_leave_request_pending(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    decision: str,
    reason: str,
) -> None:
    with workflow(approval_db, checkpoint_db) as graph:
        approval_id = pause(graph, approval_db)
        with pytest.raises(ValidationError):
            resume_booking(
                graph,
                approval_db,
                approval_id=approval_id,
                decision=decision,
                reason=reason,
            )
    with approval_db() as conn:
        assert conn.execute("SELECT decision FROM approvals").fetchone() == (None,)
