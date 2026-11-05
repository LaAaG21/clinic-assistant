"""Database operation for use inside staff-approved cancellation completion."""

from typing import Literal

from psycopg import Connection

CancellationOutcome = Literal["cancelled", "target_not_found", "ineligible_target"]
CancellationTargetOutcome = Literal["eligible", "target_not_found", "ineligible_target"]


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
