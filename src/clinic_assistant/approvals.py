"""Pending staff-approval storage and stable page traversal (#40)."""

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from psycopg import Connection
from psycopg.rows import class_row
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from clinic_assistant.requests import RequestAction


@dataclass(frozen=True)
class Approval:
    approval_id: str
    request_id: str
    decision: str | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True)
class PendingApproval:
    approval_id: str
    request_id: str
    conversation_id: str
    action: RequestAction
    slot_id: str | None
    booking_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class PendingApprovalPage:
    items: list[PendingApproval]
    next_cursor: str | None


class InvalidApprovalPagination(ValueError):
    """Invalid limit or opaque cursor, suitable for boundary validation."""


class _Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal["1"]
    created_at: AwareDatetime
    approval_id: str = Field(min_length=1)


def _decode_cursor(cursor: str) -> _Cursor:
    if not cursor or len(cursor) > 4096:
        raise InvalidApprovalPagination("Invalid approval cursor")
    try:
        decoded = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        return _Cursor.model_validate_json(decoded)
    except ValueError as exc:
        raise InvalidApprovalPagination("Invalid approval cursor") from exc


def _encode_cursor(item: PendingApproval) -> str:
    payload = _Cursor(
        version="1", created_at=item.created_at, approval_id=item.approval_id
    ).model_dump_json()
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def create_pending_approval(
    conn: Connection[tuple[object, ...]], *, approval_id: str, request_id: str
) -> Approval:
    """Create one approval for a pending request in the caller's transaction.

    The request row is locked while its pending state is checked. Uniqueness
    rejects duplicate IDs and a second approval for the same request. Use the
    shared connection context for commit/rollback and connection cleanup.
    """
    with conn.cursor(row_factory=class_row(Approval)) as cursor:
        cursor.execute(
            "INSERT INTO approvals (approval_id, request_id)"
            " SELECT %s, request_id FROM requests"
            " WHERE request_id = %s AND status = 'pending_approval' FOR UPDATE"
            " RETURNING approval_id, request_id, decision, reason,"
            " created_at, decided_at",
            (approval_id, request_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Request must exist and be pending approval")
        return row


def list_pending_approvals(
    conn: Connection[tuple[object, ...]],
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> PendingApprovalPage:
    """List pending work oldest first, then approval ID, using a keyset cursor.

    A cursor remains valid after its anchor approval is decided or removed.
    Queries leave transaction ownership with the caller and perform only reads.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidApprovalPagination("Limit must be an integer from 1 to 100")
    after = _decode_cursor(cursor) if cursor is not None else None
    query = (
        "SELECT a.approval_id, a.request_id, r.conversation_id, r.action,"
        " r.slot_id, r.booking_id, a.created_at"
        " FROM approvals a JOIN requests r ON r.request_id = a.request_id"
        " WHERE a.decision IS NULL AND r.status = 'pending_approval'"
    )
    params: list[object] = []
    if after is not None:
        query += " AND (a.created_at, a.approval_id) > (%s, %s)"
        params.extend((after.created_at, after.approval_id))
    query += " ORDER BY a.created_at, a.approval_id LIMIT %s"
    params.append(limit + 1)
    with conn.cursor(row_factory=class_row(PendingApproval)) as rows:
        rows.execute(query, params)
        items = rows.fetchall()
    has_more = len(items) > limit
    items = items[:limit]
    next_cursor = _encode_cursor(items[-1]) if has_more else None
    return PendingApprovalPage(items=items, next_cursor=next_cursor)
