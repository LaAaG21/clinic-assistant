"""Deterministic in-process model adapter for tests only."""

from dataclasses import dataclass, field

from clinic_assistant.llm import ModelError


@dataclass
class FakeLLM:
    response: str = "Test draft for staff review."
    error: ModelError | None = None
    messages: list[str] = field(default_factory=list)

    def generate(self, message: str) -> str:
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return self.response
