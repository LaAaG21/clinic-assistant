"""Patient-message boundary models following docs/design/service-boundaries-and-api.md.

These schemas validate data shapes, not workflow decisions or state transitions.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

MAX_MESSAGE_LENGTH = 4000
Intent = Literal[
    "clinic_question", "find_slots", "book", "cancel", "other", "emergency"
]
MessageText = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH
    ),
]
OpaqueID = Annotated[str, StringConstraints(strict=True, min_length=1)]


class BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatientMessageRequest(BoundaryModel):
    client_message_id: UUID
    text: MessageText


class Citation(BoundaryModel):
    source_id: OpaqueID
    source_name: str
    passage_id: OpaqueID


class AssistantMessage(BoundaryModel):
    message_id: OpaqueID
    role: Literal["assistant"]
    text: str
    created_at: AwareDatetime
    citations: list[Citation]
    request_id: OpaqueID | None


class Slot(BoundaryModel):
    slot_id: OpaqueID
    doctor_id: OpaqueID
    specialty: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class SavedDecision(BoundaryModel):
    decision: Literal["approve", "reject"]
    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=1000
        ),
    ]
    decided_at: AwareDatetime


class RequestOutcome(BoundaryModel):
    # The contract gives example failure codes, not an exhaustive enum.
    code: str
    appointment_id: OpaqueID | None = None


class BookingTarget(BoundaryModel):
    slot_id: OpaqueID


class CancellationTarget(BoundaryModel):
    appointment_id: OpaqueID


class RequestResource(BoundaryModel):
    request_id: OpaqueID
    conversation_id: OpaqueID
    status: Literal["pending_approval", "processing", "completed", "rejected", "failed"]
    approval_id: OpaqueID | None
    patient_message: str
    decision: SavedDecision | None
    outcome: RequestOutcome | None


class BookingRequestResource(RequestResource):
    action: Literal["book"]
    target: BookingTarget


class CancellationRequestResource(RequestResource):
    action: Literal["cancel"]
    target: CancellationTarget


AppointmentRequest = Annotated[
    BookingRequestResource | CancellationRequestResource, Field(discriminator="action")
]


class PatientMessageResponse(BoundaryModel):
    conversation_id: OpaqueID
    patient_message_id: OpaqueID
    reply: AssistantMessage
    intent: Intent
    response_type: Literal[
        "answer",
        "clarification",
        "unsupported",
        "refusal",
        "emergency",
        "slots",
        "action",
    ]
    slots: list[Slot]
    request: AppointmentRequest | None
