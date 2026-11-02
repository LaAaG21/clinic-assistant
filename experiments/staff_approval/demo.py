"""Issue #4: synthetic, durable interrupt/resume; no production API or model key."""

import argparse
import json
import os
from importlib.metadata import version
from uuid import uuid4
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict, total=False):
    pending_id: str
    request: str
    proposal: str
    status: str
    patient_message: str
    decision: dict
    action_performed: bool


def trace(node):
    # This console trace intentionally exposes node replay; never put a mutation here.
    print(f"NODE {node}", flush=True)


class FakeLLM:
    def invoke(self, _request):
        return "Propose synthetic same-day appointment SYNTHETIC-SLOT-1 for staff review."


def propose(state):
    trace("propose")
    return {"proposal": FakeLLM().invoke(state["request"]),
            "status": "pending_approval", "action_performed": False,
            "patient_message": "Your request is waiting for staff approval. No appointment has been booked."}


def validate_decision(payload, pending_id):
    if not isinstance(payload, dict):
        raise ValueError("Decision must be a JSON object")
    if payload.get("pending_id") != pending_id:
        raise ValueError("Decision does not match pending_id")
    if payload.get("decision") not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        raise ValueError("A non-empty staff reason is required")
    return payload


def staff_review(state):
    trace("staff_review")  # Runs both at pause and at resume.
    decision = interrupt({"pending_id": state["pending_id"],
                          "status": "pending_approval",
                          "proposal": state["proposal"],
                          "patient_message": state["patient_message"]})
    return {"decision": validate_decision(decision, state["pending_id"])}


def simulate_action(state):
    trace("simulate_action")
    # State-only simulation: deliberately no appointment database write.
    return {"action_performed": True, "status": "approved",
            "patient_message": "Staff approved your request. The synthetic booking was simulated."}


def reject(state):
    trace("reject")
    return {"action_performed": False, "status": "rejected",
            "patient_message": "Staff declined your request. No appointment has been booked."}


def build_graph(saver):
    graph = StateGraph(State)
    graph.add_node("propose", propose)
    graph.add_node("staff_review", staff_review)
    graph.add_node("simulate_action", simulate_action)
    graph.add_node("reject", reject)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "staff_review")
    graph.add_conditional_edges("staff_review",
                               lambda s: s["decision"]["decision"],
                               {"approve": "simulate_action", "reject": "reject"})
    graph.add_edge("simulate_action", END)
    graph.add_edge("reject", END)
    return graph.compile(checkpointer=saver)


def emit(label, payload):
    print(label + " " + json.dumps(payload, sort_keys=True), flush=True)


def snapshot(graph, config):
    saved = graph.get_state(config)
    interrupts = [item for task in saved.tasks for item in task.interrupts]
    return saved, interrupts


def show(graph, config):
    saved, interrupts = snapshot(graph, config)
    result = {"thread_id": config["configurable"]["thread_id"],
              "next": list(saved.next), "state": saved.values,
              "interrupts": [{"id": i.id, "value": i.value} for i in interrupts]}
    emit("SAVED_STATE", result)
    return result


def start(graph, thread_id):
    config = {"configurable": {"thread_id": thread_id}}
    if graph.get_state(config).values:
        raise ValueError("Thread already exists; use inspect/resume or a fresh thread ID")
    graph.invoke({"pending_id": str(uuid4()),
                  "request": "Synthetic patient requests a same-day booking."}, config)
    saved, interrupts = snapshot(graph, config)
    assert saved.next == ("staff_review",) and len(interrupts) == 1
    assert saved.values["status"] == "pending_approval"
    assert saved.values["action_performed"] is False
    emit("PENDING_API_RESPONSE", {"thread_id": thread_id,
                                 "interrupt_id": interrupts[0].id,
                                 **interrupts[0].value})
    return show(graph, config)


def resume(graph, thread_id, pending_id, decision, reason):
    config = {"configurable": {"thread_id": thread_id}}
    saved, interrupts = snapshot(graph, config)
    if saved.values.get("status") != "pending_approval" or len(interrupts) != 1:
        raise ValueError("Thread must have exactly one pending staff interrupt")
    payload = validate_decision({"pending_id": pending_id, "decision": decision,
                                 "reason": reason}, saved.values["pending_id"])
    emit("SIMULATED_API_DECISION", {"thread_id": thread_id, **payload})
    graph.invoke(Command(resume=payload), config)
    final = show(graph, config)
    assert not final["next"] and not final["interrupts"]
    assert final["state"]["action_performed"] is (decision == "approve")
    assert final["state"]["status"] == ("approved" if decision == "approve" else "rejected")
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "inspect", "resume"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--thread", required=True)
        if name == "resume":
            cmd.add_argument("--pending-id", required=True)
            cmd.add_argument("--decision", choices=("approve", "reject"), required=True)
            cmd.add_argument("--reason", required=True)
    sub.add_parser("verify", help="Close and reopen PostgreSQL connections between pause and resume")
    args = parser.parse_args()
    emit("VERSIONS", {p: version(p) for p in
                      ("langgraph", "langgraph-checkpoint-postgres", "psycopg")})
    if args.command == "verify":
        # Close and rebuild graph/checkpointer at each boundary to prove DB recovery.
        for decision in ("approve", "reject"):
            thread_id = "issue4-" + decision + "-" + str(uuid4())
            with PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as saver:
                saver.setup()
                paused = start(build_graph(saver), thread_id)
            with PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as saver:
                graph = build_graph(saver)
                restored = show(graph, {"configurable": {"thread_id": thread_id}})
                assert restored == paused
                resume(graph, thread_id, paused["state"]["pending_id"], decision,
                       "Synthetic staff decision for verification")
        print("VERIFICATION PASSED: pending, reconnect, approval and rejection")
        return
    with PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as saver:
        saver.setup()
        graph = build_graph(saver)
        if args.command == "start":
            start(graph, args.thread)
        elif args.command == "inspect":
            show(graph, {"configurable": {"thread_id": args.thread}})
        else:
            resume(graph, args.thread, args.pending_id, args.decision, args.reason)


if __name__ == "__main__":
    main()
