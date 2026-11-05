"""Real cancellation resume and durable completion (#77)."""

import pytest

from clinic_assistant import cancellation_workflow
from clinic_assistant.booking_state import Connect
from clinic_assistant.cancellation_completion import (
    complete_cancellation,
    resume_cancellation,
)
from clinic_assistant.cancellation_workflow import (
    build_cancellation_graph,
    pause_cancellation,
)
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.errors import RequestConflict


@pytest.fixture
def accepted(approval_db: Connect) -> Connect:
    with approval_db() as conn:
        conn.execute(
            "INSERT INTO messages"
            " (message_id, conversation_id, role, text, client_message_id)"
            " VALUES ('m', 'c1', 'patient', 'Cancel',"
            " '00000000-0000-4000-8000-000000000001')"
        )
    return approval_db


@pytest.mark.parametrize(
    "decision,changed,status",
    [
        ("approve", False, "completed"),
        ("reject", False, "rejected"),
        ("approve", True, "failed"),
    ],
)
def test_completion_and_retry(
    accepted: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    decision: str,
    changed: bool,
    status: str,
) -> None:
    settings, schema = checkpoint_db
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_cancellation_graph(accepted, saver)
        pending = pause_cancellation(
            graph,
            accepted,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id="m",
        )
        assert pending.request is not None and pending.request.approval_id is not None
        approval_id = pending.request.approval_id
    if changed:
        with accepted() as conn:
            conn.execute("UPDATE bookings SET status='cancelled', cancelled_at=now()")
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_cancellation_graph(accepted, saver)
        text = resume_cancellation(
            graph,
            accepted,
            approval_id=approval_id,
            decision=decision,
            reason="Reviewed",
        )
        assert (
            resume_cancellation(
                graph,
                accepted,
                approval_id=approval_id,
                decision=decision,
                reason=" Reviewed ",
            )
            == text
        )
        with pytest.raises(RequestConflict):
            resume_cancellation(
                graph,
                accepted,
                approval_id=approval_id,
                decision="reject" if decision == "approve" else "approve",
                reason="Reviewed",
            )
    with accepted() as conn:
        assert conn.execute("SELECT status FROM requests").fetchone() == (status,)
        assert conn.execute(
            "SELECT count(*) FROM messages WHERE role='assistant' AND text=%s",
            (text,),
        ).fetchone() == (1,)
        assert conn.execute("SELECT status FROM bookings").fetchone() == (
            "booked" if decision == "reject" else "cancelled",
        )


def test_postcommit_replay(
    accepted: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, schema = checkpoint_db

    def fail(connect: Connect, *, request_id: str) -> str:
        complete_cancellation(connect, request_id=request_id)
        raise RuntimeError("after commit")

    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_cancellation_graph(accepted, saver)
        pending = pause_cancellation(
            graph,
            accepted,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id="m",
        )
        assert pending.request is not None and pending.request.approval_id is not None
        approval_id = pending.request.approval_id
        with monkeypatch.context() as scoped:
            scoped.setattr(cancellation_workflow, "complete_cancellation", fail)
            with pytest.raises(RuntimeError, match="after commit"):
                resume_cancellation(
                    graph,
                    accepted,
                    approval_id=approval_id,
                    decision="approve",
                    reason="Reviewed",
                )
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_cancellation_graph(accepted, saver)
        resume_cancellation(
            graph,
            accepted,
            approval_id=approval_id,
            decision="approve",
            reason="Reviewed",
        )
    with accepted() as conn:
        assert conn.execute(
            "SELECT count(*) FROM messages WHERE role='assistant'"
        ).fetchone() == (2,)
