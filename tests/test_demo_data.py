"""Shared synthetic demo fixtures (#42) load and match the #6 scenarios.

These checks read the packaged demo files; they do not execute any workflow.
"""

import json
from importlib.resources import as_file, files
from typing import Any, get_args
from uuid import uuid4

import pytest

from clinic_assistant.documents import ClinicDocument, load_document
from clinic_assistant.messages import Intent, PatientMessageRequest
from clinic_assistant.passages import split_document

DEMO_DATA = files("clinic_assistant") / "demo_data"
DOCUMENT_NAMES = {
    "appointments.md",
    "clinic-hours.md",
    "urgent-care.md",
    "visiting-the-clinic.md",
}
# Scenario label -> (intent, response_type) under the proposed #6 contract.
SCENARIOS = {
    "supported_clinic_question": ("clinic_question", "answer"),
    "unsupported_clinic_question": ("clinic_question", "unsupported"),
    "availability": ("find_slots", "slots"),
    "booking": ("book", "action"),
    "cancellation": ("cancel", "action"),
    "emergency": ("emergency", "emergency"),
}


def _load_documents() -> list[ClinicDocument]:
    with as_file(DEMO_DATA / "clinic_documents") as directory:
        return [load_document(path) for path in sorted(directory.iterdir())]


def _messages() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (DEMO_DATA / "patient_messages.json").read_text(encoding="utf-8")
    )
    return data


def test_every_demo_document_loads_with_its_filename_as_source() -> None:
    documents = _load_documents()
    assert {document.source_name for document in documents} == DOCUMENT_NAMES
    for document in documents:
        assert document.source_id == document.source_name
        assert document.text.startswith("# ")
        assert "Synthetic demo document" in document.text
        passages = split_document(document)
        assert len(passages) >= 3
        assert all(p.source_name == document.source_name for p in passages)


def test_messages_are_labelled_synthetic_examples_for_each_scenario() -> None:
    data = _messages()
    assert data["synthetic"] is True
    messages = data["messages"]
    assert [message["scenario"] for message in messages] == list(SCENARIOS)
    assert len({message["id"] for message in messages}) == len(messages)


@pytest.mark.parametrize("message", _messages()["messages"], ids=lambda m: m["id"])
def test_message_matches_its_contract_scenario(message: dict[str, Any]) -> None:
    PatientMessageRequest(client_message_id=uuid4(), text=message["text"])
    intent, response_type = SCENARIOS[message["scenario"]]
    assert message["expected_intent"] == intent
    assert message["expected_intent"] in get_args(Intent)
    assert message["expected_response_type"] == response_type
    assert message["note"].strip()

    sources = message["expected_sources"]
    assert set(sources) <= DOCUMENT_NAMES
    # Only a document-grounded answer carries citations.
    assert bool(sources) == (response_type == "answer")


def test_supported_answer_is_present_in_its_cited_document() -> None:
    by_name = {document.source_name: document for document in _load_documents()}
    assert "opens Monday to Friday from 09:00" in by_name["clinic-hours.md"].text
    # The unsupported example must stay unsupported by every document.
    assert not any("Maple" in document.text for document in by_name.values())
