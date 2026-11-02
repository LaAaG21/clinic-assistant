from typing import Any

import pytest
from fastapi.testclient import TestClient

from clinic_assistant.api import create_app
from clinic_assistant.llm import ModelError
from tests.fakes import FakeLLM


def test_health_is_independent_of_database_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_rejects_missing_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}


def test_draft_is_unavailable_without_an_adapter() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/draft", json={"message": "A test message"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Model adapter is not configured"}


def test_draft_uses_injected_model_and_normalizes_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = FakeLLM(response="  Deterministic test draft.\n")
    with TestClient(create_app(model=model)) as client:
        response = client.post("/draft", json={"message": "  Hello front desk.\n"})
    assert response.status_code == 200
    assert response.json() == {"draft": "Deterministic test draft."}
    assert model.messages == ["Hello front desk."]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "  \t\n"},
        {"message": "a" * 4001},
        {"message": 123},
        {"message": "Hello", "unexpected": "field"},
    ],
)
def test_invalid_requests_do_not_call_the_model(payload: dict[str, Any]) -> None:
    model = FakeLLM()
    with TestClient(create_app(model=model)) as client:
        response = client.post("/draft", json=payload)
    assert response.status_code == 422
    assert model.messages == []


def test_draft_accepts_the_documented_maximum_length() -> None:
    model = FakeLLM()
    with TestClient(create_app(model=model)) as client:
        response = client.post("/draft", json={"message": "a" * 4000})
    assert response.status_code == 200
    assert model.messages == ["a" * 4000]


@pytest.mark.parametrize("empty_output", ["", " \n\t"])
def test_empty_model_output_is_an_upstream_failure(empty_output: str) -> None:
    model = FakeLLM(response=empty_output)
    with TestClient(create_app(model=model)) as client:
        response = client.post("/draft", json={"message": "Hello"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Model adapter could not produce a draft"}


def test_model_errors_do_not_expose_provider_details() -> None:
    model = FakeLLM(error=ModelError("private provider details"))
    with TestClient(create_app(model=model)) as client:
        response = client.post("/draft", json={"message": "Hello"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Model adapter could not produce a draft"}
    assert "private provider details" not in response.text
