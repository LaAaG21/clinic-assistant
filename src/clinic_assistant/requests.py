"""Plain-SQL appointment-request storage with caller-owned transactions (#52)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from psycopg import Connection
from psycopg.rows import class_row

RequestAction = Literal["book", "cancel"]
RequestStatus = Literal[
    "pending_approval", "processing", "completed", "rejected", "failed"
]


@dataclass(frozen=True)
class AppointmentRequest:
    request_id: str
    conversation_id: str
    action: RequestAction
    slot_id: str | None
    booking_id: str | None
    status: RequestStatus
    outcome_code: str | None
    created_at: datetime
    updated_at: datetime


_COLUMNS = (
    "request_id, conversation_id, action, slot_id, booking_id,"
    " status, outcome_code, created_at, updated_at"
)


def create_request(
    conn: Connection[tuple[object, ...]],
    *,
    request_id: str,
    conversation_id: str,
    action: RequestAction,
    slot_id: str | None = None,
    booking_id: str | None = None,
    status: RequestStatus = "pending_approval",
    outcome_code: str | None = None,
) -> AppointmentRequest:
    """Insert an identified request; constraints reject invalid states/targets.

    Use the shared connection context to commit, roll back on failure and close.
    This helper leaves transaction ownership with the caller, so later approval
    creation can share the transaction. Duplicate IDs raise a unique violation
    and preserve the existing request. Driver errors propagate to the caller.
    """
    with conn.cursor(row_factory=class_row(AppointmentRequest)) as cursor:
        cursor.execute(
            "INSERT INTO requests"
            " (request_id, conversation_id, action, slot_id, booking_id,"
            " status, outcome_code) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " RETURNING " + _COLUMNS,
            (
                request_id,
                conversation_id,
                action,
                slot_id,
                booking_id,
                status,
                outcome_code,
            ),
        )
        row = cursor.fetchone()
        assert row is not None
        return row


def load_request(
    conn: Connection[tuple[object, ...]], request_id: str
) -> AppointmentRequest | None:
    """Load the saved target and state, or None when the request does not exist."""
    with conn.cursor(row_factory=class_row(AppointmentRequest)) as cursor:
        cursor.execute(
            "SELECT " + _COLUMNS + " FROM requests WHERE request_id = %s",
            (request_id,),
        )
        return cursor.fetchone()
