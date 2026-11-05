"""Durable cancellation requests and real staff-review interruption (#72)."""

from typing import Any, Literal, TypedDict, cast
from uuid import NAMESPACE_URL, uuid5

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from psycopg.rows import class_row

from clinic_assistant.approvals import create_pending_approval
from clinic_assistant.booking_state import Connect
from clinic_assistant.cancellation import validate_cancellation_target
from clinic_assistant.cancellation_completion import complete_cancellation
from clinic_assistant.errors import RequestConflict
from clinic_assistant.messages import (
    AssistantMessage,
    CancellationRequestResource,
    CancellationTarget,
    PatientMessageResponse,
)
from clinic_assistant.requests import create_request, load_request
from clinic_assistant.thread_identity import conversation_run

_WAITING_TEXT = "Your cancellation request is waiting for staff approval."


class InvalidCancellationTarget(ValueError):
    def __init__(
        self,
        outcome: Literal["target_not_found", "ineligible_target"],
    ) -> None:
        self.outcome = outcome
        super().__init__(outcome)


class CancellationState(TypedDict):
    request_id: str
    conversation_id: str
    booking_id: str
    patient_message_id: str
    waiting_response: dict[str, Any] | None


CancellationGraph = CompiledStateGraph[
    CancellationState, None, CancellationState, CancellationState
]


def build_cancellation_graph(
    connect: Connect, saver: PostgresSaver
) -> CancellationGraph:
    def prepare(state: CancellationState) -> CancellationState:
        with connect() as conn:
            request = load_request(conn, state["request_id"])
            if request is not None and (
                request.action != "cancel"
                or request.conversation_id != state["conversation_id"]
                or request.booking_id != state["booking_id"]
            ):
                raise RequestConflict("idempotency_conflict")
            patient = conn.execute(
                "SELECT request_id FROM messages WHERE message_id=%s"
                " AND conversation_id=%s AND role='patient' FOR UPDATE",
                (state["patient_message_id"], state["conversation_id"]),
            ).fetchone()
            if patient is None:
                raise LookupError("Patient message not found")
            if patient[0] not in (None, state["request_id"]):
                raise RequestConflict("idempotency_conflict")
            if request is None:
                target = validate_cancellation_target(
                    conn,
                    booking_id=state["booking_id"],
                    conversation_id=state["conversation_id"],
                    for_update=True,
                )
                if target != "eligible":
                    raise InvalidCancellationTarget(target)
                request = create_request(
                    conn,
                    request_id=state["request_id"],
                    conversation_id=state["conversation_id"],
                    action="cancel",
                    booking_id=state["booking_id"],
                )
            if request.status != "pending_approval":
                raise ValueError("Cancellation request is not pending approval")
            approval = conn.execute(
                "SELECT approval_id, decision FROM approvals WHERE request_id=%s",
                (request.request_id,),
            ).fetchone()
            if approval is None:
                approval_id = (
                    "approval_"
                    + uuid5(
                        NAMESPACE_URL, "clinic-assistant/approval/" + request.request_id
                    ).hex
                )
                create_pending_approval(
                    conn,
                    approval_id=approval_id,
                    request_id=request.request_id,
                )
            else:
                approval_id = cast(str, approval[0])
                if approval[1] is not None:
                    raise ValueError("Cancellation approval is already decided")
            conn.execute(
                "UPDATE messages SET request_id=%s WHERE message_id=%s",
                (request.request_id, state["patient_message_id"]),
            )
            reply_id = (
                "message_"
                + uuid5(
                    NAMESPACE_URL,
                    "clinic-assistant/cancellation-pending/" + request.request_id,
                ).hex
            )
            conn.execute(
                "INSERT INTO messages"
                " (message_id, conversation_id, role, text, request_id)"
                " VALUES (%s, %s, 'assistant', %s, %s)"
                " ON CONFLICT (message_id) DO NOTHING",
                (reply_id, request.conversation_id, _WAITING_TEXT, request.request_id),
            )
            with conn.cursor(row_factory=class_row(AssistantMessage)) as cursor:
                cursor.execute(
                    "SELECT message_id, role, text, created_at, citations, request_id"
                    " FROM messages WHERE message_id=%s AND conversation_id=%s"
                    " AND request_id=%s AND role='assistant'",
                    (reply_id, request.conversation_id, request.request_id),
                )
                reply = cursor.fetchone()
            if reply is None:
                raise RequestConflict("idempotency_conflict")
            response = PatientMessageResponse(
                conversation_id=request.conversation_id,
                patient_message_id=state["patient_message_id"],
                reply=reply,
                intent="cancel",
                response_type="action",
                slots=[],
                request=CancellationRequestResource(
                    request_id=request.request_id,
                    conversation_id=request.conversation_id,
                    action="cancel",
                    target=CancellationTarget(appointment_id=state["booking_id"]),
                    status="pending_approval",
                    approval_id=approval_id,
                    patient_message=reply.text,
                    decision=None,
                    outcome=None,
                ),
            )
            return {**state, "waiting_response": response.model_dump(mode="json")}

    def staff_review(state: CancellationState) -> dict[str, object]:
        resumed: object = interrupt(state["waiting_response"])
        if (
            not isinstance(resumed, dict)
            or resumed.get("request_id") != state["request_id"]
        ):
            raise ValueError("Cancellation completion workflow identity mismatch")
        complete_cancellation(connect, request_id=state["request_id"])
        return {}

    builder = StateGraph(CancellationState)
    builder.add_node("prepare", prepare)
    builder.add_node("staff_review", staff_review)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "staff_review")
    builder.add_edge("staff_review", END)
    return builder.compile(checkpointer=saver)


def pause_cancellation(
    graph: CancellationGraph,
    connect: Connect,
    *,
    conversation_id: str,
    request_id: str,
    booking_id: str,
    patient_message_id: str,
) -> PatientMessageResponse:
    """Prepare/recover a cancellation for an already accepted patient message."""
    with connect() as lock_conn, conversation_run(lock_conn, conversation_id) as config:
        saved = graph.get_state(config)
        if saved.values and saved.next:
            if saved.values["request_id"] != request_id:
                raise RequestConflict("conversation_busy")
            if (
                saved.values.get("booking_id") != booking_id
                or saved.values.get("patient_message_id") != patient_message_id
            ):
                raise RequestConflict("idempotency_conflict")
            if not any(task.interrupts for task in saved.tasks):
                graph.invoke(None, config, durability="sync")
        else:
            graph.invoke(
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "booking_id": booking_id,
                    "patient_message_id": patient_message_id,
                    "waiting_response": None,
                },
                config,
                durability="sync",
            )
        return PatientMessageResponse.model_validate(
            graph.get_state(config).values["waiting_response"]
        )
