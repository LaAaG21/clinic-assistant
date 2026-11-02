"""Model adapter contract, without a live provider or model credentials."""

from typing import Protocol


class ModelError(Exception):
    """A model adapter could not produce a usable response."""


class LanguageModel(Protocol):
    """Adapters implement generation and translate provider errors to ModelError."""

    def generate(self, message: str) -> str:
        """Return a draft for the supplied message, or raise ModelError."""
        ...


def generate_draft(model: LanguageModel, message: str) -> str:
    """Reject empty model output before it can be returned as a successful draft."""
    result = model.generate(message).strip()
    if not result:
        raise ModelError("The model returned an empty draft")
    return result
