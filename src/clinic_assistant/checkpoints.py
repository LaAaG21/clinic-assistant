"""Synchronous production checkpointer lifecycle with bounded PostgreSQL I/O."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from psycopg.rows import dict_row

from clinic_assistant.database import DatabaseSettings


@contextmanager
def postgres_checkpointer(
    settings: DatabaseSettings | None = None,
    *,
    schema: str = "workflow_checkpoints",
) -> Iterator[PostgresSaver]:
    """Initialize library tables under a serialized setup lock and always close.

    Business repositories use separate caller-owned transactions. Checkpoint
    connections use autocommit and dict rows as required by PostgresSaver.
    Errors propagate to the application's safe dependency boundary.
    """
    settings = settings or DatabaseSettings.from_env()
    with psycopg.connect(
        settings.url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        connect_timeout=settings.connect_timeout_seconds,
        options=f"-c statement_timeout={settings.query_timeout_ms}",
    ) as conn:
        # Session locks are released by connection cleanup if setup fails.
        conn.execute("SELECT pg_advisory_lock(%s)", (510057,))
        conn.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        saver = PostgresSaver(conn)
        saver.setup()
        conn.execute("SELECT pg_advisory_unlock(%s)", (510057,))
        yield saver
