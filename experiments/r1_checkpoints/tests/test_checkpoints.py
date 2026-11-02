"""PostgreSQL checkpoint tests: real database, fake LLM, no API key."""

import os
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver

from fake_llm import FIXED_REPLIES
from spike import ChatState, build_graph

pytestmark = pytest.mark.postgres


@pytest.fixture
def database_url() -> str:
    """Real PostgreSQL only; fail loudly instead of silently skipping."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL is not set; run the tests in the spike container.")
    return url


def thread_config() -> RunnableConfig:
    """A fresh, unique thread ID so tests never see each other's data."""
    return {"configurable": {"thread_id": f"test-{uuid4()}"}}


def patient(text: str) -> ChatState:
    """Build the graph input for one patient message."""
    return {"messages": [f"patient: {text}"]}


def test_same_thread_is_restored_by_a_new_saver_and_graph(database_url: str) -> None:
    """State written by one connection is read back by a brand-new one."""
    config = thread_config()

    with PostgresSaver.from_conn_string(database_url) as saver:
        saver.setup()
        graph = build_graph(saver)
        graph.invoke(patient("When is Dr. Salma free?"), config)
        graph.invoke(patient("Book 10:00"), config)

    # New connection, new saver, new compiled graph: nothing shared in memory.
    with PostgresSaver.from_conn_string(database_url) as new_saver:
        new_graph = build_graph(new_saver)
        restored = new_graph.get_state(config).values
        assert restored["turns"] == 2
        assert len(restored["messages"]) == 4

        result = new_graph.invoke(patient("Thanks"), config)

    assert result["turns"] == 3
    assert result["messages"][-1] == f"bot: {FIXED_REPLIES[2]}"


def test_a_different_thread_is_isolated(database_url: str) -> None:
    """Another thread ID starts empty even when other threads have data."""
    used, other = thread_config(), thread_config()

    with PostgresSaver.from_conn_string(database_url) as saver:
        saver.setup()
        graph = build_graph(saver)
        graph.invoke(patient("Hello"), used)

        assert graph.get_state(other).values == {}
        assert graph.get_state(used).values["turns"] == 1
