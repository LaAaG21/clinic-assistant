"""Database operation for use inside staff-approved cancellation completion."""

from typing import Literal

from psycopg import Connection

CancellationOutcome = Literal["cancelled", "target_not_found", "ineligible_target"]


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

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM bookings"
            " WHERE booking_id = %s AND conversation_id = %s FOR UPDATE",
            (booking_id, conversation_id),
        )
        target = cursor.fetchone()
        if target is None:
            return "target_not_found"
        if target != ("booked",):
            return "ineligible_target"

        cursor.execute(
            "UPDATE bookings SET status = 'cancelled',"
            " cancelled_at = statement_timestamp()"
            " WHERE booking_id = %s AND conversation_id = %s AND status = 'booked'",
            (booking_id, conversation_id),
        )
        return "cancelled" if cursor.rowcount == 1 else "ineligible_target"
