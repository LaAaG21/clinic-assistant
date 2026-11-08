"""Read-only staff visibility of persisted emergency flags (#60, FR-6).

The route reads what the guard (#55) stored; it never reruns detection,
resumes a graph or touches appointments. Only identifiers and timestamps are
returned, never patient text.
"""

import base64
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime

from clinic_assistant import database
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import BoundaryModel, OpaqueID

router = APIRouter()
Connect = Callable[[], AbstractContextManager[psycopg.Connection[tuple[object, ...]]]]


def get_connect() -> Connect:
    """Connection factory; tests override it to run inside a throwaway schema."""
    return database.connection


class StaffFlag(BoundaryModel):
    flag_id: OpaqueID
    conversation_id: OpaqueID
    message_id: OpaqueID
    created_at: AwareDatetime


class StaffFlagsPage(BoundaryModel):
    items: list[StaffFlag]
    next_cursor: str | None


def _encode(last: StaffFlag) -> str:
    raw = json.dumps([last.created_at.isoformat(), last.flag_id]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode(cursor: str) -> tuple[datetime, str]:
    """Opaque keyset cursor; anything malformed is a 422 validation error."""
    try:
        created_at, flag_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        after = datetime.fromisoformat(created_at)
        if after.tzinfo is None or not isinstance(flag_id, str) or not flag_id:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(422) from None
    return after, flag_id


_SELECT = "SELECT flag_id, conversation_id, message_id, created_at FROM emergency_flags"
# Newest first, flag_id as the tie-break; matches the emergency_flags_created_at index.
_ORDER = " ORDER BY created_at DESC, flag_id LIMIT %(limit)s"
_AFTER = (
    " WHERE created_at < %(created_at)s"
    " OR (created_at = %(created_at)s AND flag_id > %(flag_id)s)"
)


@router.get(
    "/staff/flags",
    response_model=StaffFlagsPage,
    responses={503: {"description": "Database unavailable"}},
)
def list_flags(
    connect: Annotated[Connect, Depends(get_connect)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> StaffFlagsPage:
    """List persisted emergency flags for staff, newest first, with keyset paging."""
    params: dict[str, object] = {"limit": limit + 1}
    query = _SELECT
    if cursor is not None:
        params["created_at"], params["flag_id"] = _decode(cursor)
        query += _AFTER
    try:
        with connect() as conn:
            rows = conn.execute(query + _ORDER, params).fetchall()
    except (psycopg.Error, ValueError) as exc:
        raise DependencyFailure() from exc
    items = [
        StaffFlag(
            flag_id=str(flag_id),
            conversation_id=str(conversation_id),
            message_id=str(message_id),
            created_at=created_at,  # type: ignore[arg-type]
        )
        for flag_id, conversation_id, message_id, created_at in rows[:limit]
    ]
    next_cursor = _encode(items[-1]) if len(rows) > limit else None
    return StaffFlagsPage(items=items, next_cursor=next_cursor)
