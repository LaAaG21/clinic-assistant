"""Small shared model contract; callers own prompts, validation, and policy."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: Literal["system", "user", "assistant"]
    content: str


type ModelInput = tuple[ModelMessage, ...]


class ModelAdapter(Protocol):
    async def generate(self, messages: ModelInput) -> str:
        """Return raw model text, or raise a configured/recognized failure."""
        ...


class FakeModelAdapter:
    """Repeat one explicit outcome; record inputs independently for each fake.

    No output parsing, intent classification, evidence decisions, or SDK calls.
    Empty and malformed output is allowed to exercise consumers' validation.
    """

    def __init__(self, outcome: str | Exception) -> None:
        self._outcome = outcome
        self.calls: list[ModelInput] = []

    async def generate(self, messages: ModelInput) -> str:
        self.calls.append(messages)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome
