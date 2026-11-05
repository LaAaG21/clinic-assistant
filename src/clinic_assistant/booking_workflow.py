"""Durable booking preparation and same-day staff pause (#57)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import TypedDict, cast
from uuid import NAMESPACE_URL, uuid5

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from psycopg import Connection

from clinic_assistant.approvals import create_pending_approval
from clinic_assistant.booking_outcomes import book_request
from clinic_assistant.booking_policy import is_same_day_booking
from clinic_assistant.errors import RequestConflict
from clinic_assistant.requests import RequestStatus, create_request, load_request
from clinic_assistant.thread_identity import conversation_run

Conn = Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


class BookingState(TypedDict):
    request_id: str
    conversation_id: str
    slot_id: str
    approval_id: str | None
    booking_id: str | None
    status: RequestStatus
    outcome_code: str | None
    patient_message: str


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
            approval_id = None
            if request.status == "pending_approval":
                existing = conn.execute(
                    "SELECT approval_id FROM approvals WHERE request_id=%s",
                    (request.request_id,),
                ).fetchone()
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
        interrupt(
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
        return {}

    def ordinary_booking(state: BookingState) -> BookingState:
        with connect() as conn:
            outcome = book_request(conn, request_id=state["request_id"])
            status: RequestStatus = (
                "completed" if outcome.code == "appointment_booked" else "failed"
            )
            conn.execute(
                "UPDATE requests SET status=%s, outcome_code=%s,"
                " updated_at=statement_timestamp() WHERE request_id=%s",
                (status, outcome.code, state["request_id"]),
            )
            return {
                **state,
                "status": status,
                "outcome_code": outcome.code,
                "booking_id": outcome.booking_id,
                "patient_message": (
                    "Your appointment is confirmed."
                    if status == "completed"
                    else "That slot is no longer available."
                ),
            }

    builder = StateGraph(BookingState)
    builder.add_node("prepare", prepare)
    builder.add_node("staff_review", staff_review)
    builder.add_node("ordinary_booking", ordinary_booking)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges(
        "prepare",
        lambda state: state["status"],
        {
            "pending_approval": "staff_review",
            "processing": "ordinary_booking",
            "completed": END,
            "rejected": END,
            "failed": END,
        },
    )
    builder.add_edge("staff_review", END)
    builder.add_edge("ordinary_booking", END)
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
