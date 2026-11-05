"""The remaining message schema uses real request and conversation FKs (#26)."""

from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


def test_patient_retry_identity_and_reconnect(approval_db: Connect) -> None:
    with approval_db() as conn:
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text,"
            " client_message_id) VALUES ('m', 'c1', 'patient', 'Hello',"
            " '00000000-0000-4000-8000-000000000001')"
        )
    with approval_db() as conn:
        assert conn.execute("SELECT text, citations FROM messages").fetchone() == (
            "Hello",
            [],
        )
    with pytest.raises(psycopg.errors.UniqueViolation), approval_db() as conn:
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text,"
            " client_message_id) SELECT 'm2', conversation_id, role, text,"
            " client_message_id FROM messages"
        )


@pytest.mark.parametrize(
    "conversation,role,text,client_id,request_id,error",
    [
        (
            "missing",
            "assistant",
            "Hello",
            None,
            None,
            psycopg.errors.ForeignKeyViolation,
        ),
        ("c1", "unknown", "Hello", None, None, psycopg.errors.CheckViolation),
        ("c1", "assistant", " ", None, None, psycopg.errors.CheckViolation),
        ("c1", "patient", "Hello", None, None, psycopg.errors.CheckViolation),
        (
            "c1",
            "assistant",
            "Hello",
            None,
            "missing",
            psycopg.errors.ForeignKeyViolation,
        ),
        (
            "c1",
            "patient",
            "x" * 4001,
            "00000000-0000-4000-8000-000000000001",
            None,
            psycopg.errors.CheckViolation,
        ),
    ],
)
def test_invalid_messages(
    approval_db: Connect,
    conversation: str,
    role: str,
    text: str,
    client_id: str | None,
    request_id: str | None,
    error: type[psycopg.Error],
) -> None:
    with pytest.raises(error), approval_db() as conn:
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text,"
            " client_message_id, request_id) VALUES ('m', %s, %s, %s, %s, %s)",
            (conversation, role, text, client_id, request_id),
        )


def test_assistant_outcome_must_match_request_conversation(
    approval_db: Connect,
) -> None:
    with approval_db() as conn:
        conn.execute(
            "INSERT INTO requests (request_id, conversation_id, action, slot_id)"
            " VALUES ('r', 'c1', 'book', 's2')"
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text, request_id)"
            " VALUES ('m', 'c1', 'assistant', 'Waiting', 'r')"
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation), approval_db() as conn:
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text, request_id)"
            " VALUES ('m2', 'c2', 'assistant', 'Wrong conversation', 'r')"
        )
