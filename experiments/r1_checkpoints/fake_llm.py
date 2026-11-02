"""Tiny deterministic stand-in for a chat model: fixed replies, no API key."""

FIXED_REPLIES = (
    "I can help with that. Which day suits you?",
    "Noted. Anything else I can help with?",
    "You're welcome. Have a good day!",
)


class FakeLLM:
    """Returns the same reply for the same turn on every run."""

    def __init__(self, replies: tuple[str, ...] = FIXED_REPLIES) -> None:
        self._replies = replies

    def reply(self, turn: int) -> str:
        """Return the fixed reply for a 1-based turn; the last one repeats."""
        return self._replies[min(turn, len(self._replies)) - 1]
