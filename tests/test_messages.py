"""Synthetic boundary validation and route-connected OpenAPI checks (#8)."""

from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import ValidationError

from clinic_assistant.main import app as production_app
from clinic_assistant.messages import (
    MAX_MESSAGE_LENGTH,
    PatientMessageRequest,
    PatientMessageResponse,
)

CLIENT_ID = "00000000-0000-4000-8000-000000000001"
ROUTE = "/conversations/{conversation_id}/messages"


def response_payload() -> dict[str, Any]:
    return {
        "conversation_id": "conv_demo",
        "patient_message_id": "msg_1",
        "reply": {
            "message_id": "msg_2",
            "role": "assistant",
            "text": "The clinic opens at 09:00. Source: Clinic opening hours.",
            "created_at": "2026-11-02T09:00:01+04:00",
            "citations": [
                {
                    "source_id": "doc_hours",
                    "source_name": "Clinic opening hours",
                    "passage_id": "hours_1",
                }
            ],
            "request_id": None,
        },
        "intent": "clinic_question",
        "response_type": "answer",
        "slots": [],
        "request": None,
    }


def test_valid_request_trims_text_and_round_trips_uuid() -> None:
    request = PatientMessageRequest.model_validate(
        {"client_message_id": CLIENT_ID, "text": " \tWhen does the clinic open?\n"}
    )
    assert request.text == "When does the clinic open?"
    assert request.client_message_id == UUID(CLIENT_ID)
    assert request.model_dump(mode="json")["client_message_id"] == CLIENT_ID


@pytest.mark.parametrize(
    "text", [None, "", " \t\r\n", "\u2003\u00a0", 123, True, [], {}, "x" * 4001]
)
def test_invalid_message_text(text: object) -> None:
    with pytest.raises(ValidationError) as error:
        PatientMessageRequest.model_validate(
            {"client_message_id": CLIENT_ID, "text": text}
        )
    assert error.value.errors()[0]["loc"] == ("text",)


@pytest.mark.parametrize(
    "text", ["x", "x" * 4000, "🙂" * 4000, " \n" + "x" * 4000 + "\t "]
)
def test_valid_length_boundary_is_after_trimming_and_counts_code_points(
    text: str,
) -> None:
    request = PatientMessageRequest.model_validate(
        {"client_message_id": CLIENT_ID, "text": text}
    )
    assert request.text == text.strip()
    assert 1 <= len(request.text) <= MAX_MESSAGE_LENGTH


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"client_message_id": CLIENT_ID},
        {"text": "Hello"},
        {"client_message_id": None, "text": "Hello"},
        {"client_message_id": "not-a-uuid", "text": "Hello"},
        {"client_message_id": CLIENT_ID, "text": "Hello", "intent": "book"},
    ],
)
def test_missing_fields_invalid_uuid_and_unknown_fields(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        PatientMessageRequest.model_validate(payload)


def test_valid_response_preserves_opaque_ids_citations_and_offset() -> None:
    payload = response_payload()
    response = PatientMessageResponse.model_validate(payload)
    assert response.conversation_id == "conv_demo"
    assert response.reply.citations[0].source_name == "Clinic opening hours"
    assert response.reply.created_at.utcoffset() is not None
    assert response.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "response_type",
    [
        "answer",
        "clarification",
        "unsupported",
        "refusal",
        "emergency",
        "slots",
        "action",
    ],
)
def test_documented_response_types(response_type: str) -> None:
    payload = response_payload()
    payload["response_type"] = response_type
    PatientMessageResponse.model_validate(payload)


@pytest.mark.parametrize(
    "action,target",
    [
        ("book", {"slot_id": "slot_demo_1"}),
        ("cancel", {"appointment_id": "appt_demo"}),
    ],
)
def test_pending_request_and_final_decision_shapes(
    action: str, target: dict[str, str]
) -> None:
    payload = response_payload()
    payload.update(intent=action, response_type="action")
    payload["reply"]["request_id"] = "req_demo"
    payload["request"] = {
        "request_id": "req_demo",
        "conversation_id": "conv_demo",
        "action": action,
        "target": target,
        "status": "pending_approval",
        "approval_id": "approval_demo",
        "patient_message": "Waiting for staff approval.",
        "decision": None,
        "outcome": None,
    }
    pending = PatientMessageResponse.model_validate(payload)
    assert pending.request is not None
    assert pending.request.target.model_dump() == target
    payload["request"].update(
        status="completed",
        decision={
            "decision": "approve",
            "reason": " Staff confirmed. ",
            "decided_at": "2026-11-02T09:10:00+04:00",
        },
        outcome={
            "code": "appointment_booked"
            if action == "book"
            else "appointment_cancelled",
            "appointment_id": "appt_demo",
        },
    )
    completed = PatientMessageResponse.model_validate(payload)
    assert completed.request is not None and completed.request.decision is not None
    assert completed.request.decision.reason == "Staff confirmed."


def test_slot_response_shape() -> None:
    payload = response_payload()
    payload.update(intent="find_slots", response_type="slots")
    payload["slots"] = [
        {
            "slot_id": "slot_demo_1",
            "doctor_id": "doctor_demo",
            "specialty": "dermatology",
            "starts_at": "2026-11-03T10:00:00+04:00",
            "ends_at": "2026-11-03T10:30:00+04:00",
        }
    ]
    assert (
        PatientMessageResponse.model_validate(payload).slots[0].slot_id == "slot_demo_1"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_type", "unknown"),
        ("intent", "unknown"),
        ("conversation_id", 123),
        ("extra", "unexpected"),
    ],
)
def test_invalid_response_envelope(field: str, value: object) -> None:
    payload = response_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        PatientMessageResponse.model_validate(payload)


def test_invalid_nested_response_and_missing_required_nullable_field() -> None:
    for field, value in [
        ("created_at", "2026-11-02T09:00:00"),
        ("role", "patient"),
        ("extra", True),
    ]:
        payload = response_payload()
        payload["reply"][field] = value
        with pytest.raises(ValidationError):
            PatientMessageResponse.model_validate(payload)
    payload = response_payload()
    del payload["request"]
    with pytest.raises(ValidationError):
        PatientMessageResponse.model_validate(payload)


def test_action_target_mismatch_is_rejected() -> None:
    payload = response_payload()
    payload["request"] = {
        "request_id": "req_demo",
        "conversation_id": "conv_demo",
        "action": "book",
        "target": {"appointment_id": "appt_demo"},
        "status": "processing",
        "approval_id": None,
        "patient_message": "Processing",
        "decision": None,
        "outcome": None,
    }
    with pytest.raises(ValidationError):
        PatientMessageResponse.model_validate(payload)


def demonstration_app() -> FastAPI:
    """Test-only route: no classification, database, workflow, or production wiring."""
    app = FastAPI()

    @app.post(
        ROUTE,
        response_model=PatientMessageResponse,
        responses={202: {"model": PatientMessageResponse}},
    )
    def message(
        conversation_id: str, body: PatientMessageRequest
    ) -> PatientMessageResponse:
        payload = deepcopy(response_payload())
        payload["conversation_id"] = conversation_id
        return PatientMessageResponse.model_validate(payload)

    return app


def test_route_connected_openapi_contains_request_response_and_nested_schemas() -> None:
    with TestClient(demonstration_app()) as client:
        spec = client.get("/openapi.json").json()
        validate(spec)
        operation = spec["paths"][ROUTE]["post"]
        assert operation["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/PatientMessageRequest")
        for status in ["200", "202"]:
            assert operation["responses"][status]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/PatientMessageResponse")
        schemas = spec["components"]["schemas"]
        request = schemas["PatientMessageRequest"]
        assert set(request["required"]) == {"client_message_id", "text"}
        assert request["additionalProperties"] is False
        assert request["properties"]["client_message_id"]["format"] == "uuid"
        assert request["properties"]["text"]["minLength"] == 1
        assert request["properties"]["text"]["maxLength"] == 4000
        assert schemas["PatientMessageResponse"]["additionalProperties"] is False
        assert schemas["Citation"]["properties"]["source_name"]["type"] == "string"
        assert "Slot" in schemas and "SavedDecision" in schemas
        result = client.post(
            "/conversations/conv_demo/messages",
            json={"client_message_id": CLIENT_ID, "text": "Hello"},
        )
        assert result.status_code == 200
        PatientMessageResponse.model_validate(result.json())
    assert ROUTE not in production_app.openapi()["paths"]


@pytest.mark.parametrize(
    "payload",
    [
        {"client_message_id": CLIENT_ID},
        {"client_message_id": CLIENT_ID, "text": " \n\t"},
        {"client_message_id": CLIENT_ID, "text": "x" * 4001},
        {"client_message_id": CLIENT_ID, "text": 123},
        {"client_message_id": CLIENT_ID, "text": "Hello", "extra": True},
    ],
)
def test_invalid_http_input_returns_422(payload: dict[str, Any]) -> None:
    with TestClient(demonstration_app()) as client:
        response = client.post("/conversations/conv_demo/messages", json=payload)
        assert response.status_code == 422


def test_http_accepts_maximum_length() -> None:
    with TestClient(demonstration_app()) as client:
        response = client.post(
            "/conversations/conv_demo/messages",
            json={"client_message_id": CLIENT_ID, "text": "x" * 4000},
        )
        assert response.status_code == 200
