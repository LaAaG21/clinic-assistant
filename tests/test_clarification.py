"""Fake-driven clarification cases; real classifier integration follows #63."""

import asyncio
import json
from dataclasses import dataclass
from datetime import date as Date
from typing import Any, NoReturn

import pytest

from clinic_assistant.clarification import clarify
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage


@dataclass(frozen=True)
class DetailsFixture:
    doctor_id: str | None = None
    specialty: str | None = None
    date: Date | None = None
    slot_id: str | None = None
    appointment_id: str | None = None


@dataclass(frozen=True)
class IntentFixture:
    intent: str
    uncertain: bool
    details: DetailsFixture


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
    details: dict[str, Any],
    question: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Clarification must not mutate database appointments")

    monkeypatch.setattr("psycopg.connect", forbidden)
    configured = {"intent": intent, "uncertain": uncertain, "details": details}
    fake = FakeModelAdapter(json.dumps(configured))
    messages = (ModelMessage("user", "Synthetic patient message"),)
    payload = json.loads(asyncio.run(fake.generate(messages)))
    fixture_details = dict(payload["details"])
    if "date" in fixture_details:
        fixture_details["date"] = Date.fromisoformat(fixture_details["date"])
    state = IntentFixture(
        payload["intent"], payload["uncertain"], DetailsFixture(**fixture_details)
    )
    result = clarify(state)
    assert result.question == question
    assert result.needs_clarification == (question is not None)
    assert result.classification is state
    assert result.classification.intent == configured["intent"]
    assert fake.calls == [messages]  # No additional model work to ask a question.
    assert clarify(state) == result
    if question is not None:
        assert (
            "provided-" not in question
        )  # No generated or echoed resource identifiers.
