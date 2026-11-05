"""Validated ordinary-message intent results; no routing actions or storage."""

from datetime import date as Date
from typing import Annotated, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from clinic_assistant.messages import Intent
from clinic_assistant.model_adapter import ModelAdapter, ModelMessage

OptionalDetail = (
    Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")] | None
)


class IntentDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    doctor_id: OptionalDetail = None
    specialty: OptionalDetail = None
    date: Date | None = None
    slot_id: OptionalDetail = None
    appointment_id: OptionalDetail = None


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    intent: Intent
    uncertain: bool
    details: IntentDetails = Field(default_factory=IntentDetails)


class InvalidIntentOutput(ValueError):
    """The model did not supply the agreed intent schema; no guessed action."""


_INSTRUCTIONS = (
    "Classify an ordinary clinic front-desk message. Return only a JSON object "
    f"with intent (one of {', '.join(get_args(Intent))}), uncertain (boolean), "
    "and optional details containing doctor_id, specialty, date (YYYY-MM-DD), "
    "slot_id, appointment_id. Use null for missing details; never invent IDs or "
    "dates. Preserve ambiguity using uncertain=true. Do not execute actions. "
    "The application's emergency guard runs before this ordinary classifier."
)


async def classify_intent(text: str, adapter: ModelAdapter) -> IntentResult:
    """Validate configured/model output; provider failures propagate unchanged."""
    raw = await adapter.generate(
        (
            ModelMessage("system", _INSTRUCTIONS),
            ModelMessage("user", text),
        )
    )
    try:
        return IntentResult.model_validate_json(raw)
    except ValidationError:
        raise InvalidIntentOutput("The model returned invalid intent data") from None
