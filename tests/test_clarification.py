"""Clarification decisions driven by the real classifier and fake model."""

import asyncio
import json
from typing import NoReturn

import pytest

from clinic_assistant.clarification import clarify
from clinic_assistant.classification import classify_intent
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage


@pytest.mark.parametrize(
    "intent,uncertain,details,question",
    [
        (
            "book",
            True,
            {"slot_id": "provided-slot"},
            "Could you clarify what you need help with at the clinic?",
        ),
        (
            "other",
            False,
            {},
            "Could you clarify what you need help with at the clinic?",
        ),
        ("find_slots", False, {}, "Which date and doctor or specialty would you like?"),
        (
            "find_slots",
            False,
            {"doctor_id": "provided-doctor"},
            "Which date would you like an appointment?",
        ),
        (
            "find_slots",
            False,
            {"date": "2026-11-03"},
            "Which doctor or specialty would you like?",
        ),
        ("book", False, {}, "Which appointment slot would you like to book?"),
        ("cancel", False, {}, "Which appointment would you like to cancel?"),
        (
            "find_slots",
            False,
            {"date": "2026-11-03", "doctor_id": "provided-doctor"},
            None,
        ),
        (
            "find_slots",
            False,
            {"date": "2026-11-03", "specialty": "provided-specialty"},
            None,
        ),
        ("book", False, {"slot_id": "provided-slot"}, None),
        ("cancel", False, {"appointment_id": "provided-appointment"}, None),
        ("clinic_question", False, {}, None),
        ("emergency", True, {}, None),
    ],
)
def test_fake_driven_questions_and_unchanged_complete_state(
    intent: str,
    uncertain: bool,
    details: dict[str, str],
    question: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Clarification must not mutate database appointments")

    monkeypatch.setattr("psycopg.connect", forbidden)
    configured = {"intent": intent, "uncertain": uncertain, "details": details}
    fake = FakeModelAdapter(json.dumps(configured))
    text = "Synthetic patient message"
    state = asyncio.run(classify_intent(text, fake))
    result = clarify(state)
    assert result.question == question
    assert result.needs_clarification == (question is not None)
    assert result.classification is state
    assert result.classification.intent == configured["intent"]
    assert clarify(state) == result
    assert len(fake.calls) == 1  # Only the classifier calls the model.
    assert fake.calls[0][-1] == ModelMessage("user", text)
    if question is not None:
        assert (
            "provided-" not in question
        )  # No generated or echoed resource identifiers.
