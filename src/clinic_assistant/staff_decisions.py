"""Thin staff decision integration over durable completion functions (#82)."""

from contextlib import AbstractContextManager
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response

from clinic_assistant.booking_state import Conn
from clinic_assistant.booking_workflow import build_booking_graph, resume_booking
from clinic_assistant.cancellation_completion import resume_cancellation
from clinic_assistant.cancellation_workflow import build_cancellation_graph
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import connection
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import (
    AppointmentRequest,
    BookingRequestResource,
    BookingTarget,
    CancellationRequestResource,
    CancellationTarget,
    RequestOutcome,
    SavedDecision,
    StaffDecisionRequest,
)
from clinic_assistant.requests import load_request
from clinic_assistant.settings import AppSettings, get_settings

router = APIRouter()


@router.post(
    "/staff/approvals/{approval_id}/decision", response_model=AppointmentRequest
)
def decide(
    approval_id: str,
    body: StaffDecisionRequest,
    response: Response,
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> BookingRequestResource | CancellationRequestResource:
    def connect() -> AbstractContextManager[Conn]:
        return connection(settings.database)

    try:
        with connect() as conn:
            target = conn.execute(
                "SELECT r.request_id, r.action FROM requests r"
                " JOIN approvals a ON a.request_id=r.request_id WHERE a.approval_id=%s",
                (approval_id,),
            ).fetchone()
        if target is None:
            raise HTTPException(status_code=404)
        request_id, action = str(target[0]), str(target[1])
        with postgres_checkpointer(settings.database) as saver:
            if action == "book":
                resume_booking(
                    build_booking_graph(
                        connect, saver, clinic_timezone=settings.clinic_timezone
                    ),
                    connect,
                    approval_id=approval_id,
                    decision=body.decision,
                    reason=body.reason,
                )
            else:
                resume_cancellation(
                    build_cancellation_graph(connect, saver),
                    connect,
                    approval_id=approval_id,
                    decision=body.decision,
                    reason=body.reason,
                )
        with connect() as conn:
            request = load_request(conn, request_id)
            assert request is not None
            saved = conn.execute(
                "SELECT decision, reason, decided_at FROM approvals"
                " WHERE approval_id=%s",
                (approval_id,),
            ).fetchone()
            message = conn.execute(
                "SELECT text FROM messages WHERE request_id=%s AND role='assistant'"
                " ORDER BY created_at DESC, message_id DESC LIMIT 1",
                (request_id,),
            ).fetchone()
        assert saved is not None and message is not None
        values = {
            "request_id": request_id,
            "conversation_id": request.conversation_id,
            "status": request.status,
            "approval_id": approval_id,
            "patient_message": message[0],
            "decision": SavedDecision.model_validate(
                dict(zip(("decision", "reason", "decided_at"), saved, strict=True))
            ),
            "outcome": RequestOutcome(
                code=request.outcome_code or "",
                appointment_id=request.booking_id,
            ),
        }
        response.headers["Location"] = "/requests/" + request_id
        response.headers["Cache-Control"] = "no-store"
        if action == "book":
            assert request.slot_id is not None
            return BookingRequestResource.model_validate(
                {
                    **values,
                    "action": "book",
                    "target": BookingTarget(slot_id=request.slot_id),
                }
            )
        assert request.booking_id is not None
        return CancellationRequestResource.model_validate(
            {
                **values,
                "action": "cancel",
                "target": CancellationTarget(appointment_id=request.booking_id),
            }
        )
    except LookupError as exc:
        raise HTTPException(status_code=404) from exc
    except psycopg.errors.QueryCanceled as exc:
        raise DependencyFailure("dependency_timeout") from exc
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise DependencyFailure("persistence_unavailable") from exc
