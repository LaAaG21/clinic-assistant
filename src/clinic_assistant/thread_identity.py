"""Stable, server-derived conversation threads and serialized graph runs (#56)."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import NAMESPACE_URL, uuid5

from langchain_core.runnables import RunnableConfig
from psycopg import Connection

from clinic_assistant.errors import RequestConflict

Conn = Connection[tuple[object, ...]]


def thread_config(conn: Conn, conversation_id: str) -> RunnableConfig:
    if not conversation_id.strip():
        raise ValueError("A conversation ID is required")
    if (
        conn.execute(
            "SELECT 1 FROM conversations WHERE conversation_id=%s",
            (conversation_id,),
        ).fetchone()
        is None
    ):
        raise LookupError("Conversation not found")
    identity = uuid5(NAMESPACE_URL, "clinic-assistant/conversation/" + conversation_id)
    return {"configurable": {"thread_id": "conversation_" + identity.hex}}


@contextmanager
def conversation_run(conn: Conn, conversation_id: str) -> Iterator[RunnableConfig]:
    """Serialize a graph run using a dedicated connection, released on failure.

    Business nodes use their own transactions. The caller owns and closes this
    connection through the shared connection helper, including on lock failure.
    """
    config = thread_config(conn, conversation_id)
    identity = uuid5(NAMESPACE_URL, "clinic-assistant/conversation/" + conversation_id)
    key = int.from_bytes(identity.bytes[:8], signed=True)
    acquired = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()
    if acquired != (True,):
        raise RequestConflict("conversation_busy")
    try:
        yield config
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
