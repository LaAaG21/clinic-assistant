"""Bounded model context (#81): fixed histories and the #46 fake adapter, no key."""

import asyncio

import pytest

from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage
from clinic_assistant.model_context import (
    DEFAULT_CONTEXT_MESSAGES,
    build_model_input,
    generate_with_recent_context,
    recent_window,
)
from clinic_assistant.settings import SettingsError, load_settings

SYSTEM = ModelMessage("system", "Answer only from clinic documents.")
EVIDENCE = ModelMessage("system", "Evidence: the clinic opens at 09:00.")


def turns(count: int) -> list[ModelMessage]:
    """Alternating patient/assistant turns numbered 1..count, oldest first."""
    return [
        ModelMessage("user" if n % 2 else "assistant", f"turn {n}")
        for n in range(1, count + 1)
    ]


def numbers(messages: tuple[ModelMessage, ...]) -> list[int]:
    return [int(m.content.split()[-1]) for m in messages if m.role != "system"]


@pytest.mark.parametrize(
    ("size", "limit", "expected"),
    [
        (0, 3, []),  # empty
        (2, 3, [1, 2]),  # shorter than the limit: whole history
        (3, 3, [1, 2, 3]),  # exactly the limit
        (7, 3, [5, 6, 7]),  # over the limit: last three, oldest first
        (7, 1, [7]),  # smallest window
    ],
)
def test_recent_window_boundaries_and_order(
    size: int, limit: int, expected: list[int]
) -> None:
    assert numbers(recent_window(turns(size), limit)) == expected


def test_source_history_is_unchanged() -> None:
    history = turns(12)
    snapshot = list(history)
    window = recent_window(history, 4)
    assert history == snapshot
    assert isinstance(window, tuple)  # an immutable copy, not the stored list


def test_required_messages_are_never_trimmed() -> None:
    result = build_model_input([SYSTEM, EVIDENCE], turns(20), 2)
    assert result[:2] == (SYSTEM, EVIDENCE)
    assert numbers(result) == [19, 20]


@pytest.mark.parametrize("limit", [0, 51])
def test_limit_out_of_range_is_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 50"):
        recent_window(turns(3), limit)


def test_system_text_inside_history_is_rejected() -> None:
    with pytest.raises(ValueError, match="pass system text separately"):
        recent_window([*turns(2), SYSTEM], 5)


def test_adapter_receives_only_the_bounded_context() -> None:
    adapter = FakeModelAdapter("reply")
    history = turns(30)
    reply = asyncio.run(
        generate_with_recent_context(adapter, [SYSTEM, EVIDENCE], history, 5)
    )
    assert reply == "reply"
    assert len(adapter.calls) == 1
    sent = adapter.calls[0]
    assert sent[:2] == (SYSTEM, EVIDENCE)
    assert numbers(sent) == [26, 27, 28, 29, 30]
    assert len(history) == 30  # stored history stays complete


def test_adapter_failure_propagates_unchanged() -> None:
    adapter = FakeModelAdapter(TimeoutError("synthetic"))
    with pytest.raises(TimeoutError):
        asyncio.run(generate_with_recent_context(adapter, [SYSTEM], turns(3), 2))


BASE = {
    "DATABASE_URL": "postgresql://clinic:secret-marker@localhost:5432/clinic",
    "CLINIC_TIMEZONE": "Asia/Muscat",
}


def test_setting_defaults_to_ten() -> None:
    assert load_settings(BASE).model_context_messages == DEFAULT_CONTEXT_MESSAGES == 10


@pytest.mark.parametrize("backend", ["fake", "openai"])
def test_setting_applies_to_both_backends(backend: str) -> None:
    environment = {**BASE, "MODEL_BACKEND": backend, "MODEL_CONTEXT_MESSAGES": "4"}
    if backend == "openai":
        environment |= {"OPENAI_API_KEY": "synthetic", "OPENAI_MODEL": "synthetic"}
    assert load_settings(environment).model_context_messages == 4


@pytest.mark.parametrize("value", ["0", "51", "ten", ""])
def test_invalid_setting_is_rejected(value: str) -> None:
    with pytest.raises(SettingsError, match="MODEL_CONTEXT_MESSAGES"):
        load_settings({**BASE, "MODEL_CONTEXT_MESSAGES": value})
