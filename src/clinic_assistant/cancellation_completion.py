"""Cancellation completion using the shared durable approval handoff (#77)."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import NAMESPACE_URL, uuid5

from langgraph.types import Command

from clinic_assistant.booking_state import Connect
from clinic_assistant.cancellation import cancel_approved_request
from clinic_assistant.decisions import persist_staff_decision
from clinic_assistant.messages import SavedDecision
from clinic_assistant.requests import load_request
from clinic_assistant.thread_identity import conversation_run


def complete_cancellation(connect: Connect, *, request_id: str) -> str:
    """Commit cancellation, terminal outcome and final message atomically."""
    with connect() as conn:
        conn.execute(
            "SELECT request_id FROM requests WHERE request_id=%s FOR UPDATE",
            (request_id,),
        )
        request = load_request(conn, request_id)
        if request is None or request.action != "cancel":
            raise LookupError("Cancellation request not found")
        approval = conn.execute(
            "SELECT decision FROM approvals WHERE request_id=%s",
            (request_id,),
        ).fetchone()
        if (
            approval is None
            or approval[0] is None
            or request.status == "pending_approval"
        ):
            raise ValueError("A durable staff decision is required")
        if request.status == "processing":
            if approval[0] == "reject":
                status, code = "rejected", "request_rejected"
            else:
                assert request.booking_id is not None
                result = cancel_approved_request(
                    conn,
                    request_id=request_id,
                    booking_id=request.booking_id,
                    conversation_id=request.conversation_id,
                )
                status, code = (
                    ("completed", "appointment_cancelled")
                    if result in ("cancelled", "already_completed")
                    else ("failed", "appointment_not_cancellable")
                )
            conn.execute(
                "UPDATE requests SET status=%s, outcome_code=%s,"
                " updated_at=statement_timestamp() WHERE request_id=%s",
                (status, code, request_id),
            )
        else:
            code = request.outcome_code or "appointment_not_cancellable"
        text = {
            "appointment_cancelled": "Your appointment has been cancelled.",
            "request_rejected": "Staff declined your cancellation request.",
        }.get(code or "", "This appointment can no longer be cancelled.")
        message_id = (
            "message_"
            + uuid5(
                NAMESPACE_URL, "clinic-assistant/cancellation-outcome/" + request_id
            ).hex
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, role, text, request_id)"
            " VALUES (%s, %s, 'assistant', %s, %s)"
            " ON CONFLICT (message_id) DO NOTHING",
            (message_id, request.conversation_id, text, request_id),
        )
        saved = conn.execute(
            "SELECT text FROM messages WHERE message_id=%s AND conversation_id=%s"
            " AND request_id=%s AND role='assistant'",
            (message_id, request.conversation_id, request_id),
        ).fetchone()
        if saved is None:
            raise ValueError("Outcome message identity conflict")
        return cast(str, saved[0])


def resume_cancellation(
    graph: "CancellationGraph",
    connect: Connect,
    *,
    approval_id: str,
    decision: str,
    reason: str,
) -> str:
    """Resolve the original identity and recover the shared decision handoff."""
    validated = SavedDecision.model_validate(
        {
            "decision": decision,
            "reason": reason,
            "decided_at": datetime.now(UTC),
        }
    )
    with connect() as conn:
        row = conn.execute(
            "SELECT r.request_id, r.conversation_id, r.action FROM requests r"
            " JOIN approvals a ON a.request_id=r.request_id WHERE a.approval_id=%s",
            (approval_id,),
        ).fetchone()
    if row is None or row[2] != "cancel":
        raise LookupError("Cancellation approval not found")
    request_id, conversation_id = str(row[0]), str(row[1])
    with connect() as lock_conn, conversation_run(lock_conn, conversation_id) as config:
        saved = graph.get_state(config)
        request = load_request(lock_conn, request_id)
        assert request is not None
        same = saved.values.get("request_id") == request_id
        if not same and request.status not in ("completed", "rejected", "failed"):
            raise LookupError("Paused cancellation checkpoint not found")
        persist_staff_decision(connect, approval_id=approval_id, decision=validated)
        if same and saved.next:
            if any(task.interrupts for task in saved.tasks):
                graph.invoke(
                    Command(resume={"request_id": request_id}),
                    config,
                    durability="sync",
                )
            else:
                graph.invoke(None, config, durability="sync")
        return complete_cancellation(connect, request_id=request_id)


if TYPE_CHECKING:
    from clinic_assistant.cancellation_workflow import CancellationGraph
