"""Application cancellation pauses using shared fake and real PostgreSQL (#72)."""

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from langgraph.types import Command

from clinic_assistant.booking_state import Conn, Connect
from clinic_assistant.booking_workflow import build_booking_graph, start_booking
from clinic_assistant.cancellation_workflow import (
    CancellationGraph,
    InvalidCancellationTarget,
    build_cancellation_graph,
    pause_cancellation,
)
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.errors import RequestConflict
from clinic_assistant.messages import CancellationRequestResource
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage
from clinic_assistant.thread_identity import thread_config


@pytest.fixture
def cancellation_db(approval_db: Connect) -> Connect:
    today = datetime.now(ZoneInfo("Asia/Muscat")).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    with approval_db() as conn:
        for slot_id, offset in (("s1", 0), ("s2", 2)):
            start = today + timedelta(days=offset)
            conn.execute(
                "UPDATE slots SET starts_at=%s, ends_at=%s WHERE slot_id=%s",
                (start, start + timedelta(minutes=30), slot_id),
            )
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
            " VALUES ('b2', 's2', 'c1')"
        )
        conn.execute(
            "INSERT INTO messages"
            " (message_id, conversation_id, role, text, client_message_id) VALUES"
            " ('m1', 'c1', 'patient', 'Cancel my appointment.',"
            " '00000000-0000-4000-8000-000000000001'),"
            " ('m2', 'c1', 'patient', 'Cancel my other appointment.',"
            " '00000000-0000-4000-8000-000000000002'),"
            " ('other', 'c2', 'patient', 'Cancel my appointment.',"
            " '00000000-0000-4000-8000-000000000003')"
        )
    return approval_db


@contextmanager
def workflow(
    connect: Connect,
    checkpoint: tuple[DatabaseSettings, str],
) -> Iterator[CancellationGraph]:
    settings, schema = checkpoint
    with postgres_checkpointer(settings, schema=schema) as saver:
        yield build_cancellation_graph(connect, saver)


def bookings(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute("SELECT * FROM bookings ORDER BY booking_id").fetchall()


@pytest.mark.parametrize("booking_id", ["b1", "b2"], ids=["today", "future"])
def test_every_cancellation_pauses_with_durable_records_and_envelope(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    booking_id: str,
) -> None:
    fake = FakeModelAdapter(json.dumps({"appointment_id": booking_id}))
    target = json.loads(
        asyncio.run(fake.generate((ModelMessage("user", "Cancel my appointment."),)))
    )["appointment_id"]
    with cancellation_db() as conn:
        original = bookings(conn)
    with workflow(cancellation_db, checkpoint_db) as graph:
        response = pause_cancellation(
            graph,
            cancellation_db,
            conversation_id="c1",
            request_id="r",
            booking_id=target,
            patient_message_id="m1",
        )
        assert response.conversation_id == "c1"
        assert response.patient_message_id == "m1"
        assert response.intent == "cancel"
        assert response.response_type == "action"
        assert response.slots == []
        assert isinstance(response.request, CancellationRequestResource)
        assert response.request.target.appointment_id == target
        assert response.request.status == "pending_approval"
        assert response.request.approval_id is not None
        assert response.request.decision is None
        assert response.request.outcome is None
        assert response.reply.request_id == "r"
        assert response.reply.text == response.request.patient_message
        with cancellation_db() as conn:
            saved = graph.get_state(thread_config(conn, "c1"))
            interruptions = [item for task in saved.tasks for item in task.interrupts]
            assert len(interruptions) == 1
            assert interruptions[0].value == response.model_dump(mode="json")
    with workflow(cancellation_db, checkpoint_db) as graph:
        assert (
            pause_cancellation(
                graph,
                cancellation_db,
                conversation_id="c1",
                request_id="r",
                booking_id=target,
                patient_message_id="m1",
            )
            == response
        )
    with cancellation_db() as conn:
        assert bookings(conn) == original
        assert conn.execute(
            "SELECT conversation_id, action, booking_id, status FROM requests"
        ).fetchone() == ("c1", "cancel", target, "pending_approval")
        assert conn.execute(
            "SELECT approval_id, request_id, decision, reason, decided_at"
            " FROM approvals"
        ).fetchone() == (response.request.approval_id, "r", None, None, None)
        assert conn.execute(
            "SELECT request_id FROM messages WHERE message_id='m1'"
        ).fetchone() == ("r",)
        assert conn.execute(
            "SELECT message_id, text FROM messages WHERE role='assistant'"
        ).fetchall() == [(response.reply.message_id, response.reply.text)]
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "booking_id,change,outcome",
    [
        ("missing", None, "target_not_found"),
        ("b2", "wrong_conversation", "target_not_found"),
        ("b1", "cancelled", "ineligible_target"),
    ],
)
def test_invalid_targets_create_no_pending_work(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    booking_id: str,
    change: str | None,
    outcome: str,
) -> None:
    with cancellation_db() as conn:
        if change == "wrong_conversation":
            conn.execute(
                "UPDATE bookings SET conversation_id='c2' WHERE booking_id='b2'"
            )
        if change == "cancelled":
            conn.execute(
                "UPDATE bookings SET status='cancelled', cancelled_at=now()"
                " WHERE booking_id='b1'"
            )
        original = bookings(conn)
    with workflow(cancellation_db, checkpoint_db) as graph:
        with pytest.raises(InvalidCancellationTarget) as captured:
            pause_cancellation(
                graph,
                cancellation_db,
                conversation_id="c1",
                request_id="r",
                booking_id=booking_id,
                patient_message_id="m1",
            )
        assert captured.value.outcome == outcome
        assert str(captured.value) == outcome
    with cancellation_db() as conn:
        assert bookings(conn) == original
        assert conn.execute("SELECT count(*) FROM requests").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM messages WHERE role='assistant'"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "request_id,booking_id,message_id,code",
    [
        ("r", "b2", "m1", "idempotency_conflict"),
        ("r", "b1", "m2", "idempotency_conflict"),
        ("different", "b1", "m1", "conversation_busy"),
    ],
)
def test_pending_retries_preserve_original_identities(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    request_id: str,
    booking_id: str,
    message_id: str,
    code: str,
) -> None:
    with workflow(cancellation_db, checkpoint_db) as graph:
        original = pause_cancellation(
            graph,
            cancellation_db,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id="m1",
        )
        with pytest.raises(RequestConflict) as captured:
            pause_cancellation(
                graph,
                cancellation_db,
                conversation_id="c1",
                request_id=request_id,
                booking_id=booking_id,
                patient_message_id=message_id,
            )
        assert captured.value.code == code
        assert (
            pause_cancellation(
                graph,
                cancellation_db,
                conversation_id="c1",
                request_id="r",
                booking_id="b1",
                patient_message_id="m1",
            )
            == original
        )


def test_recover_after_pending_commit_before_checkpoint(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    fail_once = True

    @contextmanager
    def interrupted_connection() -> Iterator[Conn]:
        nonlocal fail_once
        with cancellation_db() as conn:
            yield conn
        if fail_once:
            fail_once = False
            raise RuntimeError("synthetic post-commit failure")

    with workflow(interrupted_connection, checkpoint_db) as graph:
        with pytest.raises(RuntimeError, match="post-commit"):
            pause_cancellation(
                graph,
                cancellation_db,
                conversation_id="c1",
                request_id="r",
                booking_id="b1",
                patient_message_id="m1",
            )
    with cancellation_db() as conn:
        original = conn.execute(
            "SELECT message_id, created_at FROM messages WHERE role='assistant'"
        ).fetchall()
        assert len(original) == 1
    with workflow(cancellation_db, checkpoint_db) as graph:
        response = pause_cancellation(
            graph,
            cancellation_db,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id="m1",
        )
        assert response.request is not None
        assert response.request.status == "pending_approval"
    with cancellation_db() as conn:
        assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM requests").fetchone() == (1,)
        assert (
            conn.execute(
                "SELECT message_id, created_at FROM messages WHERE role='assistant'"
            ).fetchall()
            == original
        )


def test_pending_record_and_message_failure_roll_back_together(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with cancellation_db() as conn:
        conn.execute(
            "ALTER TABLE messages ADD CONSTRAINT synthetic_reply_failure"
            " CHECK (role <> 'assistant')"
        )
        original = bookings(conn)
    with workflow(cancellation_db, checkpoint_db) as graph:
        with pytest.raises(psycopg.errors.CheckViolation):
            pause_cancellation(
                graph,
                cancellation_db,
                conversation_id="c1",
                request_id="r",
                booking_id="b1",
                patient_message_id="m1",
            )
        with cancellation_db() as conn:
            assert bookings(conn) == original
            assert conn.execute("SELECT count(*) FROM requests").fetchone() == (0,)
            assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (0,)
            assert conn.execute(
                "SELECT request_id FROM messages WHERE message_id='m1'"
            ).fetchone() == (None,)
            conn.execute("ALTER TABLE messages DROP CONSTRAINT synthetic_reply_failure")
        response = pause_cancellation(
            graph,
            cancellation_db,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id="m1",
        )
        assert response.request is not None
        assert response.request.status == "pending_approval"


@pytest.mark.parametrize("message_id", ["missing", "other"])
def test_only_the_accepted_conversation_message_can_start_the_request(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    message_id: str,
) -> None:
    with workflow(cancellation_db, checkpoint_db) as graph, pytest.raises(LookupError):
        pause_cancellation(
            graph,
            cancellation_db,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id=message_id,
        )
    with cancellation_db() as conn:
        assert conn.execute("SELECT count(*) FROM requests").fetchone() == (0,)


def test_raw_resume_cannot_apply_a_cancellation(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with workflow(cancellation_db, checkpoint_db) as graph:
        pause_cancellation(
            graph,
            cancellation_db,
            conversation_id="c1",
            request_id="r",
            booking_id="b1",
            patient_message_id="m1",
        )
        with cancellation_db() as conn:
            original = bookings(conn)
            config = thread_config(conn, "c1")
        with pytest.raises(ValueError, match="completion workflow"):
            graph.invoke(Command(resume={"decision": "approve"}), config)
    with cancellation_db() as conn:
        assert bookings(conn) == original
        assert conn.execute("SELECT decision FROM approvals").fetchone() == (None,)


def test_conversations_remain_isolated(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    with cancellation_db() as conn:
        conn.execute("UPDATE bookings SET conversation_id='c2' WHERE booking_id='b2'")
        original = bookings(conn)
    with workflow(cancellation_db, checkpoint_db) as graph:
        for conversation, request, target, message in (
            ("c1", "r1", "b1", "m1"),
            ("c2", "r2", "b2", "other"),
        ):
            result = pause_cancellation(
                graph,
                cancellation_db,
                conversation_id=conversation,
                request_id=request,
                booking_id=target,
                patient_message_id=message,
            )
            assert result.conversation_id == conversation
        with cancellation_db() as conn:
            for conversation, target in (("c1", "b1"), ("c2", "b2")):
                saved = graph.get_state(thread_config(conn, conversation))
                assert saved.values["booking_id"] == target
            assert bookings(conn) == original
            assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (2,)


def test_completed_booking_can_enter_cancellation_on_the_same_thread(
    cancellation_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    start = datetime.now(ZoneInfo("Asia/Muscat")) + timedelta(days=3)
    with cancellation_db() as conn:
        conn.execute(
            "INSERT INTO slots VALUES ('s3', 'd', %s, %s)",
            (start, start + timedelta(minutes=30)),
        )
    settings, schema = checkpoint_db
    with postgres_checkpointer(settings, schema=schema) as saver:
        booking_graph = build_booking_graph(
            cancellation_db,
            saver,
            clinic_timezone="Asia/Muscat",
        )
        booked = start_booking(
            booking_graph,
            cancellation_db,
            conversation_id="c1",
            request_id="book",
            slot_id="s3",
        )
        assert booked["booking_id"] is not None
        cancellation_graph = build_cancellation_graph(cancellation_db, saver)
        waiting = pause_cancellation(
            cancellation_graph,
            cancellation_db,
            conversation_id="c1",
            request_id="cancel",
            booking_id=booked["booking_id"],
            patient_message_id="m2",
        )
        assert isinstance(waiting.request, CancellationRequestResource)
        assert waiting.request.target.appointment_id == booked["booking_id"]
        with pytest.raises(RequestConflict):
            start_booking(
                booking_graph,
                cancellation_db,
                conversation_id="c1",
                request_id="another",
                slot_id="s3",
            )
