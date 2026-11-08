"""Conversation history (#86): read-only, complete stored messages, paged.

This is the full record; it never applies the model window from #81, never
calls the model, and never changes stored messages.
"""

import base64
import binascii
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from psycopg.rows import class_row

from clinic_assistant import database
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import BoundaryModel, Citation
from clinic_assistant.settings import AppSettings, get_settings

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

Conn = psycopg.Connection[tuple[object, ...]]
ConnectionFactory = Callable[[], AbstractContextManager[Conn]]
After = tuple[datetime, str]

_MESSAGES = """
SELECT message_id, role, text, created_at, citations, request_id
FROM messages
WHERE conversation_id = %(conversation_id)s
  AND (
      %(after_at)s::timestamptz IS NULL
      OR (created_at, message_id) > (%(after_at)s, %(after_id)s::text)
  )
ORDER BY created_at, message_id
LIMIT %(limit)s
"""


@dataclass(frozen=True, slots=True)
class StoredMessage:
    message_id: str
    role: Literal["patient", "assistant"]
    text: str
    created_at: datetime
    citations: list[dict[str, Any]]
    request_id: str | None


def conversation_exists(conn: Conn, conversation_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM conversations WHERE conversation_id = %s", (conversation_id,)
    ).fetchone()
    return row is not None


def history_page(
    conn: Conn, conversation_id: str, *, limit: int, after: After | None = None
) -> tuple[list[StoredMessage], bool]:
    """Messages oldest first by (created_at, message_id); True if more follow."""
    after_at, after_id = after if after is not None else (None, None)
    params = {
        "conversation_id": conversation_id,
        "after_at": after_at,
        "after_id": after_id,
        "limit": limit + 1,  # one extra row tells us whether another page exists
    }
    with conn.cursor(row_factory=class_row(StoredMessage)) as cursor:
        cursor.execute(_MESSAGES, params)
        rows = cursor.fetchall()
    return rows[:limit], len(rows) > limit


router = APIRouter()


class HistoryMessage(BoundaryModel):
    message_id: str
    role: Literal["patient", "assistant"]
    text: str
    created_at: datetime
    citations: list[Citation]
    request_id: str | None


class ConversationHistory(BoundaryModel):
    conversation_id: str
    messages: list[HistoryMessage]
    next_cursor: str | None


def connection_factory(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ConnectionFactory:
    """Opened only after validation, so invalid input never touches the database."""
    return partial(database.connection, settings.database)


def encode_cursor(after: After) -> str:
    """Opaque cursor: URL-safe base64 of the last message's (created_at, id)."""
    payload = json.dumps({"t": after[0].isoformat(), "i": after[1]})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> After:
    """Raise ValueError for anything that is not a cursor this API produced."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(data["t"])
        message_id = data["i"]
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise ValueError("invalid cursor") from None
    if created_at.tzinfo is None or not isinstance(message_id, str) or not message_id:
        raise ValueError("invalid cursor")
    return created_at, message_id


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationHistory,
    responses={
        404: {"description": "Unknown conversation"},
        422: {"description": "Invalid paging"},
        503: {"description": "Database unavailable"},
    },
)
def get_conversation(
    conversation_id: str,
    response: Response,
    open_connection: Annotated[ConnectionFactory, Depends(connection_factory)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> ConversationHistory:
    """The complete stored conversation, oldest first; read-only."""
    try:
        after = decode_cursor(cursor) if cursor is not None else None
    except ValueError:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("query", "cursor"), "msg": "invalid"}]
        ) from None

    try:
        with open_connection() as conn:
            if not conversation_exists(conn, conversation_id):
                raise HTTPException(status_code=404)
            messages, has_more = history_page(
                conn, conversation_id, limit=limit, after=after
            )
    except psycopg.errors.QueryCanceled as exc:
        raise DependencyFailure("dependency_timeout") from exc
    except psycopg.OperationalError as exc:
        raise DependencyFailure("dependency_unavailable") from exc

    last = messages[-1] if has_more else None
    response.headers["Cache-Control"] = "no-store"  # new messages may arrive
    return ConversationHistory(
        conversation_id=conversation_id,
        messages=[
            HistoryMessage(
                message_id=m.message_id,
                role=m.role,
                text=m.text,
                created_at=m.created_at,
                citations=[Citation.model_validate(c) for c in m.citations],
                request_id=m.request_id,
            )
            for m in messages
        ],
        next_cursor=encode_cursor((last.created_at, last.message_id)) if last else None,
    )
