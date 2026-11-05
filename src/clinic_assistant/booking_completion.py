"""Atomic booking/outcome/message completion and durable replay recovery (#62)."""

from typing import cast
from uuid import NAMESPACE_URL, uuid5

from clinic_assistant.booking_outcomes import book_request
from clinic_assistant.booking_state import BookingState, Connect
from clinic_assistant.requests import RequestStatus, load_request


def complete_booking(connect: Connect, *, request_id: str) -> BookingState:
    """Commit booking, request outcome and assistant message together.

    Terminal requests reuse their saved outcome. A graph replay after this
    transaction commits repairs its checkpoint without running the mutation.
    """
    with connect() as conn:
        conn.execute(
            "SELECT request_id FROM requests WHERE request_id=%s FOR UPDATE",
            (request_id,),
        )
        request = load_request(conn, request_id)
        if request is None:
            raise LookupError("Request not found")
        if request.action != "book" or request.slot_id is None:
            raise ValueError("Request is not a booking")
        approval = conn.execute(
            "SELECT approval_id, decision FROM approvals WHERE request_id=%s",
            (request_id,),
        ).fetchone()
        if request.status == "pending_approval":
            raise ValueError("Staff decision is required")
        if request.status == "processing":
            if approval is not None and approval[1] is None:
                raise ValueError("Staff decision is required")
            if approval is not None and approval[1] == "reject":
                if request.booking_id is not None:
                    raise ValueError(
                        "Rejected request has a conflicting booking result"
                    )
                status: RequestStatus = "rejected"
                code = "request_rejected"
            else:
                outcome = book_request(conn, request_id=request_id)
                status = (
                    "completed" if outcome.code == "appointment_booked" else "failed"
                )
                code = outcome.code
            conn.execute(
                "UPDATE requests SET status=%s, outcome_code=%s,"
                " updated_at=statement_timestamp() WHERE request_id=%s",
                (status, code, request_id),
            )
            request = load_request(conn, request_id)
            assert request is not None
        assert request.outcome_code is not None
        text = {
            "appointment_booked": "Your appointment is confirmed.",
            "slot_unavailable": "That slot is no longer available.",
            "request_rejected": "Staff declined your booking request.",
        }.get(request.outcome_code, "Your booking request could not be completed.")
        message_id = (
            "message_"
            + uuid5(NAMESPACE_URL, "clinic-assistant/booking-outcome/" + request_id).hex
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text, request_id)"
            " VALUES (%s, %s, 'assistant', %s, %s)"
            " ON CONFLICT (message_id) DO NOTHING",
            (message_id, request.conversation_id, text, request_id),
        )
        message = conn.execute(
            "SELECT conversation_id, request_id, role, text FROM messages"
            " WHERE message_id=%s",
            (message_id,),
        ).fetchone()
        if message is None or message[:3] != (
            request.conversation_id,
            request_id,
            "assistant",
        ):
            raise ValueError("Outcome message identity conflicts with the request")
        return {
            "request_id": request_id,
            "conversation_id": request.conversation_id,
            "slot_id": cast(str, request.slot_id),
            "approval_id": cast(str, approval[0]) if approval else None,
            "booking_id": request.booking_id,
            "status": request.status,
            "outcome_code": request.outcome_code,
            "patient_message": cast(str, message[3]),
        }
