"""Stable graph identities, isolation and concurrent-run protection (#56)."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TypedDict

import psycopg
import pytest
from langgraph.graph import END, START, StateGraph

from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.errors import RequestConflict
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage
from clinic_assistant.thread_identity import conversation_run, thread_config

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


class State(TypedDict, total=False):
    text: str


def test_identity_survives_reconnect_and_isolates_conversations(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    settings, schema = checkpoint_db
    for conversation in ("c1", "c2"):
        fake = FakeModelAdapter(conversation + " reply")

        def answer(state: State, model: FakeModelAdapter = fake) -> dict[str, str]:
            return {
                "text": asyncio.run(model.generate((ModelMessage("user", "Hello"),)))
            }

        with (
            postgres_checkpointer(settings, schema=schema) as saver,
            approval_db() as conn,
        ):
            graph = StateGraph(State)
            graph.add_node("answer", answer)
            graph.add_edge(START, "answer")
            graph.add_edge("answer", END)
            with conversation_run(conn, conversation) as config:
                graph.compile(checkpointer=saver).invoke({"text": "Hello"}, config)
    with postgres_checkpointer(settings, schema=schema) as saver, approval_db() as conn:
        graph = StateGraph(State)
        graph.add_edge(START, END)
        restored = graph.compile(checkpointer=saver)
        for conversation in ("c1", "c2"):
            config = thread_config(conn, conversation)
            assert restored.get_state(config).values["text"] == conversation + " reply"


def test_concurrent_run_is_rejected_and_failure_releases_lock(
    approval_db: Connect,
) -> None:
    with pytest.raises(RuntimeError, match="synthetic"), approval_db() as first:
        with conversation_run(first, "c1"):
            with approval_db() as second, pytest.raises(RequestConflict):
                with conversation_run(second, "c1"):
                    pytest.fail("A second run must not enter")
            raise RuntimeError("synthetic")
    with approval_db() as conn, conversation_run(conn, "c1"):
        pass


@pytest.mark.parametrize(
    "conversation,error", [("", ValueError), ("missing", LookupError)]
)
def test_missing_or_invalid_conversation(
    approval_db: Connect,
    conversation: str,
    error: type[Exception],
) -> None:
    with approval_db() as conn, pytest.raises(error):
        thread_config(conn, conversation)
