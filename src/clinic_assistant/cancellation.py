"""Database operation for use inside staff-approved cancellation completion."""

from typing import Literal

from psycopg import Connection

CancellationOutcome = Literal["cancelled", "target_not_found", "ineligible_target"]
CancellationTargetOutcome = Literal["eligible", "target_not_found", "ineligible_target"]
ApprovedCancellationOutcome = Literal[
    "cancelled", "already_completed", "target_not_found", "ineligible_target"
]


def cancel_approved_request(
    conn: Connection[tuple[object, ...]],
    *,
    request_id: str,
    booking_id: str,
    conversation_id: str,
) -> ApprovedCancellationOutcome:
    """Cancel the saved approved target once in the caller's transaction.

    The shared decision handoff must have committed an approval and processing
    state. Lock order is request, approval, booking. Success records the request
    outcome with the booking mutation. Completion callers save their assistant
    outcome message before committing this same transaction.
    """
    if conn.autocommit:
        raise ValueError("Cancellation requires a caller-owned transaction")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT status, outcome_code FROM requests WHERE request_id=%s"
            " AND action='cancel' AND booking_id=%s AND conversation_id=%s FOR UPDATE",
            (request_id, booking_id, conversation_id),
        )
        request = cursor.fetchone()
        if request is None:
            return "target_not_found"
        cursor.execute(
            "SELECT decision FROM approvals WHERE request_id=%s FOR UPDATE",
            (request_id,),
        )
        if cursor.fetchone() != ("approve",):
            return "ineligible_target"
        if request == ("completed", "appointment_cancelled"):
            cursor.execute(
                "SELECT 1 FROM bookings WHERE booking_id=%s AND conversation_id=%s"
                " AND status='cancelled' FOR UPDATE",
                (booking_id, conversation_id),
            )
            return "already_completed" if cursor.fetchone() else "ineligible_target"
        if request != ("processing", None):
            return "ineligible_target"
        outcome = cancel_approved_booking(
            conn,
            booking_id=booking_id,
            conversation_id=conversation_id,
        )
        if outcome != "cancelled":
            return outcome
        cursor.execute(
            "UPDATE requests SET status='completed',"
            " outcome_code='appointment_cancelled',"
            " updated_at=statement_timestamp() WHERE request_id=%s",
            (request_id,),
        )
        return "cancelled"


def validate_cancellation_target(
    conn: Connection[tuple[object, ...]],
    *,
    booking_id: str,
    conversation_id: str,
    for_update: bool = False,
) -> CancellationTargetOutcome:
    """Check ownership and active state without changing the booking.

    A caller-owned transaction retains the optional row lock for subsequent
    request creation or approved cancellation.
    """
    query = "SELECT status FROM bookings WHERE booking_id=%s AND conversation_id=%s"
    if for_update:
        query += " FOR UPDATE"
    with conn.cursor() as cursor:
        cursor.execute(query, (booking_id, conversation_id))
        target = cursor.fetchone()
    if target is None:
        return "target_not_found"
    return "eligible" if target == ("booked",) else "ineligible_target"


def cancel_approved_booking(
    conn: Connection[tuple[object, ...]], *, booking_id: str, conversation_id: str
) -> CancellationOutcome:
    """Cancel a booked target belonging to the supplied conversation.

    The caller must verify approval and own the transaction. Completion must
    check the saved request outcome before calling this function and record the
    result in the same transaction as the update. An already cancelled booking
    does not establish that this request performed the cancellation.
    """
    if conn.autocommit:
        raise ValueError("Cancellation requires a caller-owned transaction")

    target = validate_cancellation_target(
        conn,
        booking_id=booking_id,
        conversation_id=conversation_id,
        for_update=True,
    )
    if target != "eligible":
        return target
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE bookings SET status = 'cancelled',"
            " cancelled_at = statement_timestamp()"
            " WHERE booking_id = %s AND conversation_id = %s AND status = 'booked'",
            (booking_id, conversation_id),
        )
        return "cancelled" if cursor.rowcount == 1 else "ineligible_target"
