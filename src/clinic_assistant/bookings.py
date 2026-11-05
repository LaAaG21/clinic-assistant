"""Atomic booking insertion tied to a locked request identity (#61)."""

from uuid import NAMESPACE_URL, uuid5

from psycopg import Connection

from clinic_assistant.requests import load_request


def insert_booking(
    conn: Connection[tuple[object, ...]],
    *,
    request_id: str,
) -> str | None:
    """Return the stored booking ID, or None for an active-slot conflict.

    The caller owns a non-autocommit transaction and records its outcome before
    commit. The request row serializes same-request retries. Keeping its result
    ID in this transaction makes a retry reuse a committed booking.
    """
    if conn.autocommit:
        raise ValueError("Booking requires a caller-owned transaction")
    conn.execute(
        "SELECT request_id FROM requests WHERE request_id=%s FOR UPDATE", (request_id,)
    )
    request = load_request(conn, request_id)
    if request is None:
        raise LookupError("Request not found")
    if request.action != "book" or request.status not in ("processing", "completed"):
        raise ValueError("Request is not ready for booking")
    if request.booking_id is not None:
        return request.booking_id
    booking_id = (
        "booking_" + uuid5(NAMESPACE_URL, "clinic-assistant/booking/" + request_id).hex
    )
    row = conn.execute(
        "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
        " VALUES (%s, %s, %s)"
        " ON CONFLICT (slot_id) WHERE status='booked' DO NOTHING"
        " RETURNING booking_id",
        (booking_id, request.slot_id, request.conversation_id),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE requests SET booking_id=%s, updated_at=statement_timestamp()"
        " WHERE request_id=%s",
        (booking_id, request_id),
    )
    return booking_id
