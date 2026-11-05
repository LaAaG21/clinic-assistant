"""Durable booking preparation and same-day staff pause (#57)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from clinic_assistant.approvals import create_pending_approval
from clinic_assistant.booking_completion import complete_booking
from clinic_assistant.booking_policy import is_same_day_booking
from clinic_assistant.booking_state import (
    BookingState as BookingState,
)
from clinic_assistant.booking_state import (
    Conn as Conn,
)
from clinic_assistant.booking_state import (
    Connect as Connect,
)
from clinic_assistant.decisions import persist_staff_decision
from clinic_assistant.errors import RequestConflict
from clinic_assistant.messages import SavedDecision
from clinic_assistant.requests import create_request, load_request
from clinic_assistant.thread_identity import conversation_run

BookingGraph = CompiledStateGraph[BookingState, None, BookingState, BookingState]


def build_booking_graph(
    connect: Connect,
    saver: PostgresSaver,
    *,
    clinic_timezone: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BookingGraph:
    def prepare(state: BookingState) -> BookingState:
        with connect() as conn:
            request = load_request(conn, state["request_id"])
            if request is not None and (
                request.conversation_id != state["conversation_id"]
                or request.action != "book"
                or request.slot_id != state["slot_id"]
            ):
                raise RequestConflict("idempotency_conflict")
            if request is None:
                slot = conn.execute(
                    "SELECT starts_at FROM slots WHERE slot_id=%s",
                    (state["slot_id"],),
                ).fetchone()
                if slot is None:
                    raise LookupError("Slot not found")
                starts_at = cast(datetime, slot[0])
                same_day = is_same_day_booking(starts_at, clock(), clinic_timezone)
                request = create_request(
                    conn,
                    request_id=state["request_id"],
                    conversation_id=state["conversation_id"],
                    action="book",
                    slot_id=state["slot_id"],
                    status="pending_approval" if same_day else "processing",
                )
            existing = conn.execute(
                "SELECT approval_id FROM approvals WHERE request_id=%s",
                (request.request_id,),
            ).fetchone()
            approval_id = cast(str, existing[0]) if existing else None
            if request.status == "pending_approval":
                if existing is None:
                    approval_id = (
                        "approval_"
                        + uuid5(
                            NAMESPACE_URL,
                            "clinic-assistant/approval/" + request.request_id,
                        ).hex
                    )
                    create_pending_approval(
                        conn,
                        approval_id=approval_id,
                        request_id=request.request_id,
                    )
                else:
                    approval_id = cast(str, existing[0])
            return {
                **state,
                "status": request.status,
                "approval_id": approval_id,
                "booking_id": request.booking_id,
                "outcome_code": request.outcome_code,
                "patient_message": (
                    "Your booking request is waiting for staff approval."
                    if request.status == "pending_approval"
                    else "Your booking request is saved."
                ),
            }

    def staff_review(state: BookingState) -> dict[str, object]:
        resumed: object = interrupt(
            {
                "request_id": state["request_id"],
                "approval_id": state["approval_id"],
                "conversation_id": state["conversation_id"],
                "action": "book",
                "target": {"slot_id": state["slot_id"]},
                "status": "pending_approval",
                "patient_message": state["patient_message"],
            }
        )
        if not isinstance(resumed, dict) or (
            resumed.get("approval_id") != state["approval_id"]
            or resumed.get("request_id") != state["request_id"]
        ):
            raise ValueError("Resume identity does not match the paused request")
        with connect() as conn:
            decision = conn.execute(
                "SELECT 1 FROM approvals a JOIN requests r ON r.request_id=a.request_id"
                " WHERE a.approval_id=%s AND a.request_id=%s"
                " AND a.decision IS NOT NULL AND r.status<>'pending_approval'",
                (state["approval_id"], state["request_id"]),
            ).fetchone()
            if decision is None:
                raise ValueError("A durable staff decision is required")
        return {}

    def complete(state: BookingState) -> BookingState:
        return complete_booking(connect, request_id=state["request_id"])

    builder = StateGraph(BookingState)
    builder.add_node("prepare", prepare)
    builder.add_node("staff_review", staff_review)
    builder.add_node("complete", complete)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges(
        "prepare",
        lambda state: state["status"],
        {
            "pending_approval": "staff_review",
            "processing": "complete",
            "completed": "complete",
            "rejected": "complete",
            "failed": "complete",
        },
    )
    builder.add_edge("staff_review", "complete")
    builder.add_edge("complete", END)
    return builder.compile(checkpointer=saver)


def start_booking(
    graph: BookingGraph,
    connect: Connect,
    *,
    conversation_id: str,
    request_id: str,
    slot_id: str,
) -> BookingState:
    """Start/recover a server-identified request on its conversation's thread."""
    with connect() as lock_conn, conversation_run(lock_conn, conversation_id) as config:
        saved = graph.get_state(config)
        if saved.values and saved.next:
            if saved.values["request_id"] != request_id:
                raise RequestConflict("conversation_busy")
            if saved.values["slot_id"] != slot_id:
                raise RequestConflict("idempotency_conflict")
            if not any(task.interrupts for task in saved.tasks):
                graph.invoke(None, config, durability="sync")
        else:
            graph.invoke(
                {
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "slot_id": slot_id,
                    "approval_id": None,
                    "booking_id": None,
                    "status": "processing",
                    "outcome_code": None,
                    "patient_message": "",
                },
                config,
                durability="sync",
            )
        return cast(BookingState, graph.get_state(config).values)


def resume_booking(
    graph: BookingGraph,
    connect: Connect,
    *,
    approval_id: str,
    decision: str,
    reason: str,
) -> BookingState:
    """Commit a validated decision, resume its thread, and recover durable results."""
    validated = SavedDecision.model_validate(
        {
            "decision": decision,
            "reason": reason,
            "decided_at": datetime.now(UTC),
        }
    )
    with connect() as conn:
        target = conn.execute(
            "SELECT r.conversation_id, r.request_id, r.status, r.action"
            " FROM requests r JOIN approvals a ON a.request_id=r.request_id"
            " WHERE a.approval_id=%s",
            (approval_id,),
        ).fetchone()
    if target is None:
        raise LookupError("Approval not found")
    if target[3] != "book":
        raise ValueError("Approval is not for a booking")
    conversation_id, request_id = cast(str, target[0]), cast(str, target[1])
    with connect() as lock_conn, conversation_run(lock_conn, conversation_id) as config:
        saved = graph.get_state(config)
        same_request = saved.values and saved.values.get("request_id") == request_id
        current = load_request(lock_conn, request_id)
        if current is None:
            raise LookupError("Request not found")
        if not same_request and current.status not in (
            "completed",
            "rejected",
            "failed",
        ):
            raise LookupError("The paused request checkpoint was not found")
        persist_staff_decision(connect, approval_id=approval_id, decision=validated)
        if not same_request or not saved.next:
            return complete_booking(connect, request_id=request_id)
        if any(task.interrupts for task in saved.tasks):
            graph.invoke(
                Command(resume={"approval_id": approval_id, "request_id": request_id}),
                config,
                durability="sync",
            )
        else:
            graph.invoke(None, config, durability="sync")
        return cast(BookingState, graph.get_state(config).values)
