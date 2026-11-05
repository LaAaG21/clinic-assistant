"""Staff endpoint delegates to real durable graph completion (#82)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from clinic_assistant import staff_decisions
from clinic_assistant.booking_state import Connect
from clinic_assistant.booking_workflow import build_booking_graph, start_booking
from clinic_assistant.cancellation_workflow import (
    build_cancellation_graph,
    pause_cancellation,
)
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import DatabaseSettings
from clinic_assistant.main import app
from clinic_assistant.settings import AppSettings, get_settings


@pytest.mark.parametrize("action", ["book", "cancel"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_endpoint_completes_and_replays(
    approval_db: Connect,
    checkpoint_db: tuple[DatabaseSettings, str],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    decision: str,
) -> None:
    settings, schema = checkpoint_db
    with postgres_checkpointer(settings, schema=schema) as saver:
        if action == "book":
            graph = build_booking_graph(
                approval_db,
                saver,
                clinic_timezone="Asia/Muscat",
                clock=lambda: datetime.fromisoformat("2026-11-06T00:00:00Z"),
            )
            pending = start_booking(
                graph,
                approval_db,
                conversation_id="c1",
                request_id="r",
                slot_id="s2",
            )
            approval_id = pending["approval_id"]
        else:
            with approval_db() as conn:
                conn.execute(
                    "INSERT INTO messages"
                    " (message_id, conversation_id, role, text, client_message_id)"
                    " VALUES ('m', 'c1', 'patient', 'Cancel',"
                    " '00000000-0000-4000-8000-000000000001')"
                )
            response = pause_cancellation(
                build_cancellation_graph(approval_db, saver),
                approval_db,
                conversation_id="c1",
                request_id="r",
                booking_id="b1",
                patient_message_id="m",
            )
            assert response.request is not None
            approval_id = response.request.approval_id
    monkeypatch.setattr(staff_decisions, "connection", lambda settings: approval_db())
    monkeypatch.setattr(
        staff_decisions,
        "postgres_checkpointer",
        lambda settings: postgres_checkpointer(settings, schema=schema),
    )
    app.dependency_overrides[get_settings] = lambda: AppSettings(
        settings, "Asia/Muscat"
    )
    try:
        with TestClient(app) as client:
            path = f"/staff/approvals/{approval_id}/decision"
            first = client.post(
                path, json={"decision": decision, "reason": " Reviewed "}
            )
            assert first.status_code == 200
            assert first.headers["location"] == "/requests/r"
            assert first.json()["action"] == action
            assert first.json()["status"] == (
                "completed" if decision == "approve" else "rejected"
            )
            assert first.json()["decision"]["reason"] == "Reviewed"
            assert (
                client.post(
                    path,
                    json={"decision": decision, "reason": "Reviewed"},
                ).json()
                == first.json()
            )
            assert (
                client.post(
                    path,
                    json={"decision": decision, "reason": "Different"},
                ).status_code
                == 409
            )
            for payload in (
                {"decision": "other", "reason": "Reviewed"},
                {"decision": decision, "reason": " "},
                {"decision": decision, "reason": "Reviewed", "extra": True},
            ):
                assert client.post(path, json=payload).status_code == 422
    finally:
        app.dependency_overrides.pop(get_settings)
