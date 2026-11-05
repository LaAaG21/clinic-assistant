"""Shared durable decision/progress handoff before workflow resume (#62)."""

from clinic_assistant.booking_state import Connect
from clinic_assistant.errors import RequestConflict
from clinic_assistant.messages import SavedDecision
from clinic_assistant.requests import AppointmentRequest, load_request


def persist_staff_decision(
    connect: Connect,
    *,
    approval_id: str,
    decision: SavedDecision,
) -> AppointmentRequest:
    """Commit the normalized decision and progress before any graph resume.

    Lock requests before approvals, matching the booking mutation lock order.
    An identical normalized decision preserves the original timestamp; a
    different value or reason raises the shared decision_conflict.
    """
    with connect() as conn:
        target = conn.execute(
            "SELECT r.request_id FROM requests r"
            " JOIN approvals a ON a.request_id=r.request_id"
            " WHERE a.approval_id=%s FOR UPDATE OF r",
            (approval_id,),
        ).fetchone()
        if target is None:
            raise LookupError("Approval not found")
        request_id = str(target[0])
        request = load_request(conn, request_id)
        assert request is not None
        approval = conn.execute(
            "SELECT decision, reason FROM approvals WHERE approval_id=%s FOR UPDATE",
            (approval_id,),
        ).fetchone()
        assert approval is not None
        if approval[0] is not None:
            if approval != (decision.decision, decision.reason):
                raise RequestConflict("decision_conflict")
        else:
            if request.status != "pending_approval":
                raise RequestConflict("decision_conflict")
            conn.execute(
                "UPDATE approvals SET decision=%s, reason=%s,"
                " decided_at=statement_timestamp() WHERE approval_id=%s",
                (decision.decision, decision.reason, approval_id),
            )
        if request.status == "pending_approval":
            conn.execute(
                "UPDATE requests SET status='processing',"
                " updated_at=statement_timestamp()"
                " WHERE request_id=%s",
                (request_id,),
            )
        saved = load_request(conn, request_id)
        assert saved is not None
        return saved
