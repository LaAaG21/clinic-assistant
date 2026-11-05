"""Read-only pending staff-approval HTTP boundary (#45)."""

from collections.abc import Iterator
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, Field

from clinic_assistant import approvals, database
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import (
    BookingTarget,
    BoundaryModel,
    CancellationTarget,
    OpaqueID,
)

Conn = psycopg.Connection[tuple[object, ...]]
router = APIRouter()


class ApprovalFields(BoundaryModel):
    approval_id: OpaqueID
    request_id: OpaqueID
    conversation_id: OpaqueID
    created_at: AwareDatetime


class PendingBookingApproval(ApprovalFields):
    action: Literal["book"]
    target: BookingTarget


class PendingCancellationApproval(ApprovalFields):
    action: Literal["cancel"]
    target: CancellationTarget


PendingApprovalItem = Annotated[
    PendingBookingApproval | PendingCancellationApproval, Field(discriminator="action")
]


class PendingApprovalsResponse(BoundaryModel):
    items: list[PendingApprovalItem]
    next_cursor: str | None


def approval_connection() -> Iterator[Conn]:
    try:
        settings = database.DatabaseSettings.from_env()
    except ValueError as exc:
        raise DependencyFailure() from exc
    try:
        with database.connection(settings) as conn:
            yield conn
    except psycopg.errors.QueryCanceled as exc:
        raise DependencyFailure("dependency_timeout") from exc
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise DependencyFailure() from exc


def _approval_item(
    item: approvals.PendingApproval,
) -> PendingBookingApproval | PendingCancellationApproval:
    if item.action == "book":
        assert item.slot_id is not None
        return PendingBookingApproval(
            action="book",
            approval_id=item.approval_id,
            request_id=item.request_id,
            conversation_id=item.conversation_id,
            created_at=item.created_at,
            target=BookingTarget(slot_id=item.slot_id),
        )
    assert item.booking_id is not None
    return PendingCancellationApproval(
        action="cancel",
        approval_id=item.approval_id,
        request_id=item.request_id,
        conversation_id=item.conversation_id,
        created_at=item.created_at,
        target=CancellationTarget(appointment_id=item.booking_id),
    )


@router.get(
    "/staff/approvals",
    response_model=PendingApprovalsResponse,
    responses={
        422: {"description": "Invalid limit or cursor."},
        503: {"description": "Database unavailable."},
        504: {"description": "Database query timed out."},
    },
)
def pending_approvals(
    response: Response,
    conn: Annotated[Conn, Depends(approval_connection)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> PendingApprovalsResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        page = approvals.list_pending_approvals(conn, limit=limit, cursor=cursor)
    except approvals.InvalidApprovalPagination as exc:
        raise HTTPException(status_code=422) from exc
    return PendingApprovalsResponse(
        items=[_approval_item(item) for item in page.items],
        next_cursor=page.next_cursor,
    )
