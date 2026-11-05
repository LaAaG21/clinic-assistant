"""Shared fixture for schema tests on real PostgreSQL (set TEST_DATABASE_URL).

`schema_db` applies every db/init/*.sql file in name order, as the postgres image
does on a fresh volume, inside a uniquely named schema that is dropped afterwards,
so developer data in the public schema is never touched.
"""

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from clinic_assistant.database import DatabaseSettings, connection

INIT_DIR = Path(__file__).resolve().parents[1] / "db" / "init"

Conn = psycopg.Connection[tuple[object, ...]]


@pytest.fixture
def schema_db() -> Iterator[Callable[[], AbstractContextManager[Conn]]]:
    """Apply all init files in a throwaway schema; yield a connection factory."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL tests")
    settings = DatabaseSettings(url=url)
    schema = sql.Identifier("test_schema_" + uuid4().hex)
    with connection(settings) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        conn.execute(sql.SQL("SET search_path TO {}").format(schema))
        for sql_file in sorted(INIT_DIR.glob("*.sql")):
            conn.execute(sql_file.read_bytes())

    @contextmanager
    def connect() -> Iterator[Conn]:
        with connection(settings) as conn:
            conn.execute(sql.SQL("SET search_path TO {}").format(schema))
            yield conn

    try:
        yield connect
    finally:
        with connection(settings) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


@pytest.fixture
def approval_db(
    schema_db: Callable[[], AbstractContextManager[Conn]],
) -> Callable[[], AbstractContextManager[Conn]]:
    """Synthetic review targets shared by storage and endpoint tests."""
    with schema_db() as conn:
        conn.execute("INSERT INTO doctors VALUES ('d', 'Dr. Example', 'general')")
        conn.execute(
            "INSERT INTO slots VALUES"
            " ('s1', 'd', '2026-11-05T10:00:00Z', '2026-11-05T10:30:00Z'),"
            " ('s2', 'd', '2026-11-06T10:00:00Z', '2026-11-06T10:30:00Z')"
        )
        conn.execute(
            "INSERT INTO conversations (conversation_id) VALUES ('c1'), ('c2')"
        )
        conn.execute(
            "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
            " VALUES ('b1', 's1', 'c1')"
        )
    return schema_db
