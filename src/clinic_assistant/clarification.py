"""Pure clarification decisions over #63's validated classification state."""

from dataclasses import dataclass

from clinic_assistant.classification import IntentDetails, IntentResult


@dataclass(frozen=True, slots=True)
class Clarification:
    classification: IntentResult
    question: str | None

    @property
    def needs_clarification(self) -> bool:
        return self.question is not None


def clarify(classification: IntentResult) -> Clarification:
    """Ask without inventing details, or forward the original state unchanged."""
    intent = classification.intent
    details: IntentDetails = classification.details
    if intent == "emergency":
        return Clarification(classification, None)  # Keep the emergency handoff.
    question = None
    if classification.uncertain or intent == "other":
        question = "Could you clarify what you need help with at the clinic?"
    elif intent == "find_slots":
        has_doctor = details.doctor_id is not None or details.specialty is not None
        if details.date is None and not has_doctor:
            question = "Which date and doctor or specialty would you like?"
        elif details.date is None:
            question = "Which date would you like an appointment?"
        elif not has_doctor:
            question = "Which doctor or specialty would you like?"
    elif intent == "book" and details.slot_id is None:
        question = "Which appointment slot would you like to book?"
    elif intent == "cancel" and details.appointment_id is None:
        question = "Which appointment would you like to cancel?"
    return Clarification(classification, question)
