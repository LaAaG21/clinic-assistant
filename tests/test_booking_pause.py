"""Real same-day interrupts and durable pending recovery (#57)."""

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

import pytest

from clinic_assistant.booking_workflow import (
    Conn,
    Connect,
    build_booking_graph,
    start_booking,
)
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.errors import RequestConflict
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage
from clinic_assistant.thread_identity import thread_config


@pytest.mark.parametrize(
    "now", ["2026-11-06T00:00:00+00:00", "2026-11-05T22:00:00+00:00"]
)
def test_same_day_pause_reloads_original_target_without_mutation(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    now: str,
) -> None:
    settings, schema = checkpoint_db
    fake = FakeModelAdapter('{"slot_id":"s2"}')
    target = json.loads(asyncio.run(fake.generate((ModelMessage("user", "Book"),))))[
        "slot_id"
    ]
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_booking_graph(
            approval_db,
            saver,
            clinic_timezone="Asia/Muscat",
            clock=lambda: datetime.fromisoformat(now),
        )
        waiting = start_booking(
            graph,
            approval_db,
            conversation_id="c1",
            request_id="r",
            slot_id=target,
        )
        assert waiting["status"] == "pending_approval"
        assert waiting["approval_id"] is not None
        with approval_db() as conn:
            saved = graph.get_state(thread_config(conn, "c1"))
            interruptions = [item for task in saved.tasks for item in task.interrupts]
            assert len(interruptions) == 1
            assert interruptions[0].value["target"] == {"slot_id": "s2"}
            assert interruptions[0].value["approval_id"] == waiting["approval_id"]
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_booking_graph(
            approval_db,
            saver,
            clinic_timezone="Asia/Muscat",
            clock=lambda: datetime.fromisoformat("2026-11-07T00:00:00Z"),
        )
        assert (
            start_booking(
                graph,
                approval_db,
                conversation_id="c1",
                request_id="r",
                slot_id=target,
            )
            == waiting
        )
        with pytest.raises(RequestConflict):
            start_booking(
                graph,
                approval_db,
                conversation_id="c1",
                request_id="different",
                slot_id=target,
            )
    with approval_db() as conn:
        assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM requests").fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM bookings WHERE slot_id='s2'"
        ).fetchone() == (0,)


def test_ordinary_booking_uses_atomic_operation(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    settings, schema = checkpoint_db
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_booking_graph(
            approval_db,
            saver,
            clinic_timezone="Asia/Muscat",
            clock=lambda: datetime.fromisoformat("2026-11-05T00:00:00Z"),
        )
        result = start_booking(
            graph,
            approval_db,
            conversation_id="c1",
            request_id="r",
            slot_id="s2",
        )
    assert result["status"] == "completed"
    assert result["outcome_code"] == "appointment_booked"
    with approval_db() as conn:
        assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM bookings WHERE slot_id='s2'"
        ).fetchone() == (1,)


def test_recover_after_pending_commit_before_checkpoint(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    settings, schema = checkpoint_db
    fail_once = True

    @contextmanager
    def interrupted_connection() -> Iterator[Conn]:
        nonlocal fail_once
        with approval_db() as conn:
            yield conn
        if fail_once:
            fail_once = False
            raise RuntimeError("synthetic post-commit failure")

    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_booking_graph(
            interrupted_connection,
            saver,
            clinic_timezone="Asia/Muscat",
            clock=lambda: datetime.fromisoformat("2026-11-06T00:00:00Z"),
        )
        with pytest.raises(RuntimeError, match="post-commit"):
            start_booking(
                graph,
                approval_db,
                conversation_id="c1",
                request_id="r",
                slot_id="s2",
            )
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_booking_graph(
            approval_db,
            saver,
            clinic_timezone="Asia/Muscat",
            clock=lambda: datetime.fromisoformat("2026-11-07T00:00:00Z"),
        )
        result = start_booking(
            graph,
            approval_db,
            conversation_id="c1",
            request_id="r",
            slot_id="s2",
        )
        assert result["status"] == "pending_approval"
    with approval_db() as conn:
        assert conn.execute("SELECT count(*) FROM approvals").fetchone() == (1,)


def test_missing_slot_leaves_no_pending_records(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    settings, schema = checkpoint_db
    with postgres_checkpointer(settings, schema=schema) as saver:
        graph = build_booking_graph(approval_db, saver, clinic_timezone="Asia/Muscat")
        with pytest.raises(LookupError, match="Slot"):
            start_booking(
                graph,
                approval_db,
                conversation_id="c1",
                request_id="r",
                slot_id="missing",
            )
    with approval_db() as conn:
        assert conn.execute("SELECT count(*) FROM requests").fetchone() == (0,)
