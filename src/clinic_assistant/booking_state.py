"""Shared durable booking graph state and database connection contract."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TypedDict

from psycopg import Connection

from clinic_assistant.requests import RequestStatus

Conn = Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


class BookingState(TypedDict):
    request_id: str
    conversation_id: str
    slot_id: str
    approval_id: str | None
    booking_id: str | None
    status: RequestStatus
    outcome_code: str | None
    patient_message: str
