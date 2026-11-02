"""R1 spike: prove LangGraph state survives a restart via PostgreSQL checkpoints.

Usage (inside the `spike` container):
    docker compose exec spike python spike.py send <thread_id> <message>
    docker compose exec spike python spike.py show <thread_id>
"""

import operator
import os
import sys
from typing import Annotated, NotRequired, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from fake_llm import FakeLLM

llm = FakeLLM()


class ChatState(TypedDict):
    """Conversation state saved by the checkpointer after every node."""

    messages: Annotated[list[str], operator.add]
    turns: NotRequired[int]


def fake_reply(state: ChatState) -> dict[str, object]:
    """Answer with the fake LLM; the turn number comes from the restored state."""
    turn = state.get("turns", 0) + 1
    return {"messages": [f"bot: {llm.reply(turn)}"], "turns": turn}


def build_graph(saver: PostgresSaver) -> CompiledStateGraph[ChatState]:
    """Compile a one-node graph that checkpoints into PostgreSQL."""
    builder = StateGraph(ChatState)
    builder.add_node("reply", fake_reply)
    builder.add_edge(START, "reply")
    builder.add_edge("reply", END)
    return builder.compile(checkpointer=saver)


def database_url() -> str:
    """Read DATABASE_URL or stop with a clear message."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. Copy .env.example to .env and fill it.")
    return url


def main(argv: list[str]) -> None:
    """Run `send` or `show` for one thread ID."""
    if len(argv) < 2 or argv[0] not in {"send", "show"}:
        sys.exit(__doc__)
    command, thread_id = argv[0], argv[1]
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(database_url()) as saver:
        saver.setup()  # idempotent: creates/migrates checkpoint tables once
        graph = build_graph(saver)
        if command == "send":
            text = " ".join(argv[2:]) or "hello"
            new_input: ChatState = {"messages": [f"patient: {text}"]}
            graph.invoke(new_input, config)
        values = graph.get_state(config).values

    print(f"thread={thread_id} turns={values.get('turns', 0)}")
    for message in values.get("messages", []):
        print(f"  {message}")


if __name__ == "__main__":
    main(sys.argv[1:])
