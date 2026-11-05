"""Emergency guard (#55): prompt reply, bypassed ordinary work, durable flags.

Flag persistence tests use real PostgreSQL through the shared `schema_db`
fixture (set TEST_DATABASE_URL); detection and failure tests need no database.
"""

import asyncio
import logging
import socket
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

import psycopg
import pytest
from psycopg import errors

from clinic_assistant.emergency import (
    EMERGENCY_REPLY,
    EmergencyResult,
    flag_emergency,
    guard,
    is_emergency,
)
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]
SECRET = "synthetic-dsn-password-marker"


@pytest.mark.parametrize(
    "text",
    [
        "I have chest pain and my left arm is numb",
        "My father is NOT BREATHING",
        "she can’t breathe properly",
        "I think I took an overdose",
        "It's an emergency, he is unconscious",
        "  severe   bleeding \n from the wound ",
    ],
)
def test_agreed_emergency_examples_are_detected(text: str) -> None:
    assert is_emergency(text)


@pytest.mark.parametrize(
    "text",
    [
        "I have a mild headache, can I book a slot tomorrow?",
        "When does the clinic open?",
        "Cancel appt_demo_1",
        "Where is the emergency exit of the building?",
        "My strokes in swimming class hurt my shoulder",
        "",
    ],
)
def test_ordinary_messages_are_not_emergencies(text: str) -> None:
    assert not is_emergency(text)


@pytest.fixture
def db(schema_db: Connect) -> Connect:
    """Schema with one conversation and an unrelated active booking."""
    with schema_db() as conn:
        conn.execute("INSERT INTO conversations (conversation_id) VALUES ('conv_1')")
        conn.execute("INSERT INTO doctors VALUES ('doctor_1', 'Dr. A', 'dermatology')")
        conn.execute(
            "INSERT INTO slots VALUES ('slot_1', 'doctor_1',"
            " '2026-11-06T10:00:00+04:00', '2026-11-06T10:30:00+04:00')"
        )
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
            " VALUES ('booking_pending', 'slot_1', 'conv_1')"
        )
    return schema_db


def flags(connect: Connect) -> list[tuple[object, ...]]:
    with connect() as conn:
        return conn.execute(
            "SELECT flag_id, conversation_id, message_id FROM emergency_flags"
        ).fetchall()


def test_emergency_bypasses_ordinary_work_and_persists_a_flag(db: Connect) -> None:
    model = FakeModelAdapter('{"intent":"book","uncertain":false}')

    def ordinary() -> str:
        pytest.fail("ordinary classification/appointment work must not run")

    result = guard("I have chest pain", "conv_1", "msg_1", ordinary, db)
    assert isinstance(result, EmergencyResult)
    assert result.reply == EMERGENCY_REPLY
    assert result.flag_persisted and result.error is None
    assert isinstance(result.flagged_at, datetime)
    assert model.calls == []  # The model was never given the message.
    assert flags(db) == [(result.flag_id, "conv_1", "msg_1")]
    with db() as conn:
        booking = conn.execute("SELECT status FROM bookings").fetchall()
    assert booking == [("booked",)]  # Unrelated pending work is untouched.


def test_ordinary_message_runs_the_ordinary_path(db: Connect) -> None:
    model = FakeModelAdapter('{"intent":"clinic_question","uncertain":false}')

    def ordinary() -> str:
        return asyncio.run(model.generate((ModelMessage("user", "Opening hours?"),)))

    result = guard("Opening hours?", "conv_1", "msg_1", ordinary, db)
    assert result == '{"intent":"clinic_question","uncertain":false}'
    assert len(model.calls) == 1
    assert flags(db) == []


def test_retrying_the_same_message_returns_the_same_flag(db: Connect) -> None:
    first = flag_emergency("conv_1", "msg_1", db)
    second = flag_emergency("conv_1", "msg_1", db)
    assert first.flag_id == second.flag_id and first.flagged_at == second.flagged_at
    assert len(flags(db)) == 1
    other = flag_emergency("conv_1", "msg_2", db)
    assert other.flag_id != first.flag_id and len(flags(db)) == 2


@pytest.fixture
def failing_connect() -> Connect:
    @contextmanager
    def connect() -> Iterator[Conn]:
        raise psycopg.OperationalError(f"connection failed: password={SECRET}")
        yield  # pragma: no cover

    return connect


def test_persistence_failure_still_returns_the_reply(
    failing_connect: Connect, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="clinic_assistant.emergency")
    calls: list[str] = []
    result = guard(
        "he is unconscious",
        "conv_1",
        "msg_1",
        lambda: calls.append("x"),
        failing_connect,
    )
    assert isinstance(result, EmergencyResult)
    assert result.reply == EMERGENCY_REPLY
    assert not result.flag_persisted
    assert result.flag_id is None and result.error == "persistence_unavailable"
    assert calls == []
    assert caplog.messages == [
        "Emergency flag persistence failed: persistence_unavailable"
    ]
    assert SECRET not in caplog.text


def test_default_connection_failure_is_reported_safely(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{SECRET}@127.0.0.1:{port}/db")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "2")
    result = flag_emergency("conv_1", "msg_1")
    assert result.error == "persistence_unavailable" and not result.flag_persisted
    monkeypatch.delenv("DATABASE_URL")
    assert flag_emergency("conv_1", "msg_1").error == "persistence_unavailable"
    assert SECRET not in caplog.text


def test_flag_needs_an_existing_conversation(db: Connect) -> None:
    result = flag_emergency("conv_missing", "msg_1", db)
    assert result.error == "persistence_unavailable" and flags(db) == []


@pytest.mark.parametrize(
    ("flag_id", "message_id", "expected"),
    [
        (" ", "msg_1", errors.CheckViolation),
        ("flag_1", "", errors.CheckViolation),
        ("flag_1", None, errors.NotNullViolation),
    ],
)
def test_flag_required_values(
    db: Connect, flag_id: str, message_id: str | None, expected: type[psycopg.Error]
) -> None:
    with pytest.raises(expected), db() as conn:
        conn.execute(
            "INSERT INTO emergency_flags (flag_id, conversation_id, message_id)"
            " VALUES (%s, 'conv_1', %s)",
            (flag_id, message_id),
        )


def test_one_flag_per_message(db: Connect) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO emergency_flags (flag_id, conversation_id, message_id)"
            " VALUES ('flag_1', 'conv_1', 'msg_1')"
        )
    with pytest.raises(errors.UniqueViolation) as error, db() as conn:
        conn.execute(
            "INSERT INTO emergency_flags (flag_id, conversation_id, message_id)"
            " VALUES ('flag_2', 'conv_1', 'msg_1')"
        )
    assert error.value.diag.constraint_name == "emergency_flags_message_id_key"
