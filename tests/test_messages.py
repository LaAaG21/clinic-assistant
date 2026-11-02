"""Patient-message validation and a test-only route's OpenAPI contract (#8)."""

from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import ValidationError

from clinic_assistant.main import app as production_app
from clinic_assistant.messages import PatientMessageRequest, PatientMessageResponse

CLIENT_ID = "00000000-0000-4000-8000-000000000001"
ROUTE = "/conversations/{conversation_id}/messages"
MISSING = object()
INVALID_TEXTS: tuple[object, ...] = (
    None,
    "",
    " \t\r\n",
    "\u2003\u00a0",
    123,
    True,
    [],
    {},
    "x" * 4001,
)


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
    "payload",
    [{"client_message_id": CLIENT_ID, "text": text} for text in INVALID_TEXTS]
    + [
        {},
        {"client_message_id": CLIENT_ID},
        {"text": "Hello"},
        {"client_message_id": None, "text": "Hello"},
        {"client_message_id": "not-a-uuid", "text": "Hello"},
        {"client_message_id": CLIENT_ID, "text": "Hello", "intent": "book"},
    ],
)
def test_invalid_request(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PatientMessageRequest.model_validate(payload)


@pytest.mark.parametrize(
    "text", ["x", "x" * 4000, "🙂" * 4000, " \n" + "x" * 4000 + "\t "]
)
def test_valid_boundary_counts_code_points_after_trimming(text: str) -> None:
    request = PatientMessageRequest.model_validate(
        {"client_message_id": CLIENT_ID, "text": text}
    )
    assert request.text == text.strip()


def test_valid_response_preserves_ids_citations_and_offset() -> None:
    payload = response_payload()
    response = PatientMessageResponse.model_validate(payload)
    assert response.conversation_id == "conv_demo"
    assert response.reply.citations[0].source_name == "Clinic opening hours"
    assert response.reply.created_at.utcoffset() is not None
    assert response.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "path,value",
    [
        (("response_type",), "unknown"),
        (("intent",), "unknown"),
        (("conversation_id",), 123),
        (("extra",), "unexpected"),
        (("reply", "created_at"), "2026-11-02T09:00:00"),
        (("reply", "role"), "patient"),
        (("reply", "extra"), True),
        (("request",), MISSING),
    ],
)
def test_invalid_response(path: tuple[str, ...], value: object) -> None:
    payload = response_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    if value is MISSING:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    with pytest.raises(ValidationError) as error:
        PatientMessageResponse.model_validate(payload)
    assert error.value.errors()[0]["loc"] == path


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
    """Test-only route; no workflow or production endpoint."""
    app = FastAPI()

    @app.post(
        ROUTE,
        response_model=PatientMessageResponse,
        responses={202: {"model": PatientMessageResponse}},
    )
    def message(
        conversation_id: str, body: PatientMessageRequest
    ) -> PatientMessageResponse:
        payload = response_payload()
        payload["conversation_id"] = conversation_id
        return PatientMessageResponse.model_validate(payload)

    return app


def test_route_connected_openapi() -> None:
    with TestClient(demonstration_app()) as client:
        spec = client.get("/openapi.json").json()
        validate(spec)
        operation = spec["paths"][ROUTE]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"][
            "schema"
        ]
        assert request_schema["$ref"].endswith("/PatientMessageRequest")
        for status in ["200", "202"]:
            schema = operation["responses"][status]["content"]["application/json"][
                "schema"
            ]
            assert schema["$ref"].endswith("/PatientMessageResponse")
        schemas = spec["components"]["schemas"]
        request = schemas["PatientMessageRequest"]
        assert set(request["required"]) == {"client_message_id", "text"}
        assert request["additionalProperties"] is False
        assert request["properties"]["text"]["maxLength"] == 4000
        assert schemas["PatientMessageResponse"]["additionalProperties"] is False
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
        assert (
            client.post("/conversations/conv_demo/messages", json=payload).status_code
            == 422
        )
