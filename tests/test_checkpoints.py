"""Real production saver initialization, reconnection and cleanup (#51)."""

import asyncio
from typing import TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage


class State(TypedDict, total=False):
    prompt: str
    reply: str


def test_reopen_and_continue_with_shared_fake(
    checkpoint_db: tuple[DatabaseSettings, str],
) -> None:
    settings, schema = checkpoint_db
    fake = FakeModelAdapter("Configured reply")

    def answer(state: State) -> dict[str, str]:
        return {
            "reply": asyncio.run(
                fake.generate((ModelMessage("user", state["prompt"]),))
            )
        }

    config: RunnableConfig = {"configurable": {"thread_id": "synthetic-thread"}}
    for attempt in range(2):
        with postgres_checkpointer(settings, schema=schema) as saver:
            builder = StateGraph(State)
            builder.add_node("answer", answer)
            builder.add_edge(START, "answer")
            builder.add_edge("answer", END)
            graph = builder.compile(checkpointer=saver)
            if attempt:
                assert graph.get_state(config).values["reply"] == "Configured reply"
            result = graph.invoke({"prompt": "Hello"}, config)
            assert result["reply"] == "Configured reply"
            saved_connection = saver.conn
        assert saved_connection.closed
    assert len(fake.calls) == 2


def test_setup_failure_closes_connection(
    checkpoint_db: tuple[DatabaseSettings, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, schema = checkpoint_db
    captured: list[PostgresSaver] = []

    def fail_setup(saver: PostgresSaver) -> None:
        captured.append(saver)
        raise RuntimeError("synthetic setup failure")

    monkeypatch.setattr(PostgresSaver, "setup", fail_setup)
    with pytest.raises(RuntimeError, match="synthetic setup failure"):
        with postgres_checkpointer(settings, schema=schema):
            pytest.fail("Setup should fail before yielding")
    assert captured[0].conn.closed
