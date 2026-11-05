"""Fake-configured intent results and invalid-output rejection without effects."""

import asyncio
import json
from datetime import date
from typing import NoReturn, get_args

import pytest

from clinic_assistant.classification import InvalidIntentOutput, classify_intent
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import Intent
from clinic_assistant.model_adapter import FakeModelAdapter


@pytest.fixture(autouse=True)
def no_database_or_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Classification must not open database connections")

    monkeypatch.setattr("psycopg.connect", forbidden)


@pytest.mark.parametrize("intent", get_args(Intent))
def test_all_six_categories_use_exact_configured_output(intent: str) -> None:
    fake = FakeModelAdapter(json.dumps({"intent": intent, "uncertain": False}))
    result = asyncio.run(classify_intent("Synthetic input", fake))
    assert result.intent == intent
    assert not result.uncertain
    assert all(value is None for value in result.details.model_dump().values())
    assert len(fake.calls) == 1
    assert [message.role for message in fake.calls[0]] == ["system", "user"]
    assert fake.calls[0][1].content == "Synthetic input"


def test_missing_details_and_uncertainty_are_preserved() -> None:
    fake = FakeModelAdapter(
        json.dumps(
            {
                "intent": "book",
                "uncertain": True,
                "details": {"doctor_id": "doctor_demo"},
            }
        )
    )
    result = asyncio.run(classify_intent("Maybe book with that doctor", fake))
    assert result.uncertain and result.intent == "book"
    assert result.details.doctor_id == "doctor_demo"
    assert result.details.slot_id is None and result.details.date is None


def test_explicit_details_are_typed_without_resolving_or_inventing_resources() -> None:
    details = {
        "doctor_id": " doctor_demo ",
        "specialty": "dermatology",
        "date": "2026-11-03",
        "slot_id": "slot_demo",
        "appointment_id": "appt_demo",
    }
    fake = FakeModelAdapter(
        json.dumps({"intent": "find_slots", "uncertain": False, "details": details})
    )
    result = asyncio.run(classify_intent("Supplied synthetic details", fake))
    assert result.details.date == date(2026, 11, 3)
    assert result.details.model_dump(mode="json") == details


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-json-private-marker",
        "[]",
        '"private-marker"',
        "null",
        '{"intent":"unknown","uncertain":false}',
        '{"intent":"book"}',
        '{"intent":"book","uncertain":"yes"}',
        '{"intent":"book","uncertain":false,"execute":true}',
        '{"intent":"book","uncertain":false,"details":{"slot_id":123}}',
        '{"intent":"book","uncertain":false,"details":{"slot_id":" "}}',
        '{"intent":"book","uncertain":false,"details":{"unknown":"private-marker"}}',
        '{"intent":"find_slots","uncertain":false,"details":{"date":"2026-02-30"}}',
        '{"intent":"find_slots","uncertain":false,"details":{"date":123}}',
    ],
)
def test_malformed_or_unrecognized_output_never_becomes_a_guessed_intent(
    raw: str,
) -> None:
    with pytest.raises(InvalidIntentOutput) as error:
        asyncio.run(classify_intent("Question", FakeModelAdapter(raw)))
    assert str(error.value) == "The model returned invalid intent data"
    assert "private-marker" not in str(error.value)


@pytest.mark.parametrize("code", ["dependency_timeout", "dependency_unavailable"])
def test_recognized_model_failure_is_not_classification_fallback(code: str) -> None:
    # Use the existing typed constructor via explicit cases, preserving Literal types.
    failure = (
        DependencyFailure("dependency_timeout")
        if code == "dependency_timeout"
        else DependencyFailure()
    )
    with pytest.raises(DependencyFailure) as error:
        asyncio.run(classify_intent("Question", FakeModelAdapter(failure)))
    assert error.value is failure
