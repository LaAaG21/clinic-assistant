"""Exercise the cancellation pause with the existing PostgreSQL checkpointer."""

from typing import Literal, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from psycopg import Connection


class CancellationRequest(TypedDict):
    request_id: str
    approval_id: str
    conversation_id: str
    appointment_id: str


class CancellationState(CancellationRequest, total=False):
    status: Literal["pending_approval", "failed"]
    patient_message: str


def build_cancellation_graph(saver: PostgresSaver, bookings: Connection):
    def validate(state: CancellationState) -> dict[str, str]:
        target = bookings.execute(
            "SELECT 1 FROM bookings WHERE booking_id = %s"
            " AND conversation_id = %s AND status = 'booked'",
            (state["appointment_id"], state["conversation_id"]),
        ).fetchone()
        if target is None:
            return {
                "status": "failed",
                "patient_message": "This appointment cannot be cancelled.",
            }
        return {
            "status": "pending_approval",
            "patient_message": "Your cancellation request is waiting for staff approval.",
        }

    def wait_for_staff(state: CancellationState) -> dict:
        interrupt(dict(state))
        return {}

    graph = StateGraph(CancellationState)
    graph.add_node("validate", validate)
    graph.add_node("wait_for_staff", wait_for_staff)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges(
        "validate",
        lambda state: state["status"],
        {"pending_approval": "wait_for_staff", "failed": END},
    )
    graph.add_edge("wait_for_staff", END)
    return graph.compile(checkpointer=saver)


def pause_or_load(graph, *, thread_id: str, request: CancellationRequest):
    """Use the same checkpoint thread for a retry of the same request."""
    config = {"configurable": {"thread_id": thread_id}}
    saved = graph.get_state(config)
    if saved.values:
        if any(saved.values.get(key) != value for key, value in request.items()):
            raise ValueError("Cancellation request does not match the saved target")
        # An interrupted graph has pending tasks. A checkpoint saved before
        # the interrupt can continue from its next node after a restart.
        if saved.next and not any(task.interrupts for task in saved.tasks):
            graph.invoke(None, config)
    else:
        graph.invoke(request, config)
    return graph.get_state(config)
