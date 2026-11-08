"""Bounded model context (#81): the model sees a recent window; storage keeps all.

Callers pass the full conversation history; nothing here reads or changes the
database. Required system/evidence messages are never trimmed.
"""

from collections.abc import Sequence

from clinic_assistant.model_adapter import ModelAdapter, ModelInput, ModelMessage

DEFAULT_CONTEXT_MESSAGES = 10
MAX_CONTEXT_MESSAGES = 50


def recent_window(history: Sequence[ModelMessage], limit: int) -> ModelInput:
    """Return the last `limit` turns, oldest first, as a new tuple.

    Shorter histories are returned whole; `history` itself is never modified.
    """
    if not 1 <= limit <= MAX_CONTEXT_MESSAGES:
        raise ValueError(f"limit must be between 1 and {MAX_CONTEXT_MESSAGES}")
    if any(message.role == "system" for message in history):
        raise ValueError(
            "history holds conversation turns; pass system text separately"
        )
    return tuple(history[-limit:])


def build_model_input(
    required: Sequence[ModelMessage],
    history: Sequence[ModelMessage],
    limit: int,
) -> ModelInput:
    """Required system/evidence messages first, untrimmed, then the recent window."""
    return (*required, *recent_window(history, limit))


async def generate_with_recent_context(
    adapter: ModelAdapter,
    required: Sequence[ModelMessage],
    history: Sequence[ModelMessage],
    limit: int,
) -> str:
    """Model-call boundary: the adapter only ever receives the bounded input."""
    return await adapter.generate(build_model_input(required, history, limit))
