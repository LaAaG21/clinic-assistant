"""GET /slots (#76): validate the query, call the #71 lookup, serialize the #6 shape.

Read-only: returned slots are not reserved or booked.
"""

import base64
import binascii
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime
from functools import partial
from typing import Annotated
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, Query, Response
from fastapi.exceptions import RequestValidationError

from clinic_assistant import database
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import BoundaryModel, Slot
from clinic_assistant.settings import AppSettings, get_settings
from clinic_assistant.slots import DEFAULT_LIMIT, MAX_LIMIT, After, available_slot_page

router = APIRouter()

Conn = psycopg.Connection[tuple[object, ...]]
ConnectionFactory = Callable[[], AbstractContextManager[Conn]]


class SlotsResponse(BoundaryModel):
    clinic_timezone: str
    slots: list[Slot]
    next_cursor: str | None


def connection_factory(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ConnectionFactory:
    """Opened only after validation, so invalid input never touches the database."""
    return partial(database.connection, settings.database)


def encode_cursor(after: After) -> str:
    """Opaque cursor: URL-safe base64 of the last slot's (starts_at, slot_id)."""
    payload = json.dumps({"s": after[0].isoformat(), "i": after[1]})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> After:
    """Raise ValueError for anything that is not a cursor this API produced."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        starts_at = datetime.fromisoformat(data["s"])
        slot_id = data["i"]
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise ValueError("invalid cursor") from None
    if starts_at.tzinfo is None or not isinstance(slot_id, str) or not slot_id:
        raise ValueError("invalid cursor")
    return starts_at, slot_id


def _invalid(field: str) -> RequestValidationError:
    # Reuses the shared 422 envelope (#43); no user input is echoed back.
    return RequestValidationError(
        [{"type": "value_error", "loc": ("query", field), "msg": "invalid"}]
    )


@router.get(
    "/slots",
    response_model=SlotsResponse,
    responses={
        422: {"description": "Invalid query"},
        503: {"description": "Database unavailable"},
    },
)
def get_slots(
    response: Response,
    open_connection: Annotated[ConnectionFactory, Depends(connection_factory)],
    settings: Annotated[AppSettings, Depends(get_settings)],
    day: Annotated[
        date, Query(alias="date", description="Clinic-local date, YYYY-MM-DD")
    ],
    doctor_id: str | None = None,
    specialty: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> SlotsResponse:
    """Available slots for a doctor, a specialty, or both, on one clinic-local day."""
    if doctor_id is not None and not doctor_id.strip():
        raise _invalid("doctor_id")
    if specialty is not None and not specialty.strip():
        raise _invalid("specialty")
    if doctor_id is None and specialty is None:
        raise _invalid("doctor_id")
    try:
        after = decode_cursor(cursor) if cursor is not None else None
    except ValueError:
        raise _invalid("cursor") from None

    try:
        with open_connection() as conn:
            slots, has_more = available_slot_page(
                conn,
                day,
                settings.clinic_timezone,
                doctor_id=doctor_id,
                specialty=specialty,
                limit=limit,
                after=after,
            )
    except psycopg.errors.QueryCanceled as exc:
        raise DependencyFailure("dependency_timeout") from exc
    except psycopg.OperationalError as exc:
        raise DependencyFailure("dependency_unavailable") from exc

    zone = ZoneInfo(settings.clinic_timezone)
    last = slots[-1] if has_more else None
    response.headers["Cache-Control"] = "no-store"  # availability changes
    return SlotsResponse(
        clinic_timezone=settings.clinic_timezone,
        slots=[
            Slot(
                slot_id=slot.slot_id,
                doctor_id=slot.doctor_id,
                specialty=slot.specialty,
                starts_at=slot.starts_at.astimezone(zone),
                ends_at=slot.ends_at.astimezone(zone),
            )
            for slot in slots
        ],
        next_cursor=encode_cursor((last.starts_at, last.slot_id)) if last else None,
    )
