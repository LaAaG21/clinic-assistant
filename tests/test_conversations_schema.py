"""Conversations schema (#26, first portion) on real PostgreSQL.

Set TEST_DATABASE_URL to run. The `schema_db` fixture (conftest.py) applies the
db/init files in their own schema and drops it afterwards.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import errors

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


def add_conversation(conn: Conn, conversation_id: str = "conv_1") -> None:
    conn.execute(
        "INSERT INTO conversations (conversation_id) VALUES (%s)", (conversation_id,)
    )


def test_new_conversation_gets_a_creation_time(schema_db: Connect) -> None:
    before = datetime.now(UTC)
    with schema_db() as conn:
        add_conversation(conn)
    with schema_db() as conn:
        row = conn.execute("SELECT conversation_id, created_at FROM conversations")
        conversation_id, created_at = row.fetchone() or (None, None)
    assert conversation_id == "conv_1"
    assert isinstance(created_at, datetime) and created_at.tzinfo is not None
    # Database and test clocks may differ slightly (container vs host).
    skew = timedelta(seconds=5)
    assert before - skew <= created_at <= datetime.now(UTC) + skew


def test_duplicate_conversation_id_is_rejected(schema_db: Connect) -> None:
    with schema_db() as conn:
        add_conversation(conn)
    with pytest.raises(errors.UniqueViolation) as error, schema_db() as conn:
        add_conversation(conn)
    assert error.value.diag.constraint_name == "conversations_pkey"


@pytest.mark.parametrize(
    ("conversation_id", "expected"),
    [
        ("", errors.CheckViolation),
        ("   ", errors.CheckViolation),
        (None, errors.NotNullViolation),
    ],
)
def test_conversation_id_is_required(
    schema_db: Connect, conversation_id: str | None, expected: type[psycopg.Error]
) -> None:
    with pytest.raises(expected), schema_db() as conn:
        conn.execute(
            "INSERT INTO conversations (conversation_id) VALUES (%s)",
            (conversation_id,),
        )


def test_created_at_cannot_be_null(schema_db: Connect) -> None:
    with pytest.raises(errors.NotNullViolation), schema_db() as conn:
        conn.execute(
            "INSERT INTO conversations (conversation_id, created_at)"
            " VALUES ('conv_1', NULL)"
        )
