"""Unit tests for the fixed-reply fake LLM (no database, no API key)."""

from fake_llm import FIXED_REPLIES, FakeLLM


def test_each_turn_gets_its_fixed_reply() -> None:
    """Turns 1..3 map to the replies in order."""
    llm = FakeLLM()
    assert [llm.reply(turn) for turn in (1, 2, 3)] == list(FIXED_REPLIES)


def test_turns_past_the_end_repeat_the_last_reply() -> None:
    """A long conversation never raises IndexError."""
    assert FakeLLM().reply(10) == FIXED_REPLIES[-1]


def test_same_turn_always_gives_same_reply() -> None:
    """Two separate instances are deterministic."""
    assert FakeLLM().reply(2) == FakeLLM().reply(2)
