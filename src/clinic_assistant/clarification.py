"""Pure clarification decisions over #63's validated classification state."""

from dataclasses import dataclass
from datetime import date as Date
from typing import Protocol


class ActionDetails(Protocol):
    @property
    def doctor_id(self) -> str | None: ...

    @property
    def specialty(self) -> str | None: ...

    @property
    def date(self) -> Date | None: ...

    @property
    def slot_id(self) -> str | None: ...

    @property
    def appointment_id(self) -> str | None: ...


class ClassifiedIntent(Protocol):
    @property
    def intent(self) -> str: ...

    @property
    def uncertain(self) -> bool: ...

    @property
    def details(self) -> ActionDetails: ...


@dataclass(frozen=True, slots=True)
class Clarification[T]:
    classification: T
    question: str | None

    @property
    def needs_clarification(self) -> bool:
        return self.question is not None


def clarify[T: ClassifiedIntent](classification: T) -> Clarification[T]:
    """Ask without inventing details, or forward the original state unchanged."""
    intent, details = classification.intent, classification.details
    if intent == "emergency":
        return Clarification(classification, None)  # Keep the emergency handoff.
    question = None
    if classification.uncertain or intent == "other":
        question = "Could you clarify what you need help with at the clinic?"
    elif intent == "find_slots":
        has_doctor = bool(
            (details.doctor_id or "").strip() or (details.specialty or "").strip()
        )
        if details.date is None and not has_doctor:
            question = "Which date and doctor or specialty would you like?"
        elif details.date is None:
            question = "Which date would you like an appointment?"
        elif not has_doctor:
            question = "Which doctor or specialty would you like?"
    elif intent == "book" and not (details.slot_id or "").strip():
        question = "Which appointment slot would you like to book?"
    elif intent == "cancel" and not (details.appointment_id or "").strip():
        question = "Which appointment would you like to cancel?"
    return Clarification(classification, question)
