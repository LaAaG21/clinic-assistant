"""Shared application outcomes around the atomic booking boundary (#66)."""

from dataclasses import dataclass
from typing import Literal

import psycopg

from clinic_assistant.bookings import insert_booking
from clinic_assistant.errors import DependencyFailure


@dataclass(frozen=True)
class BookingOutcome:
    code: Literal["appointment_booked", "slot_unavailable"]
    booking_id: str | None


def book_request(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    request_id: str,
) -> BookingOutcome:
    """Use the existing mutation once; the caller commits result and outcome."""
    try:
        booking_id = insert_booking(conn, request_id=request_id)
    except psycopg.errors.QueryCanceled as exc:
        raise DependencyFailure("dependency_timeout") from exc
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise DependencyFailure() from exc
    if booking_id is None:
        return BookingOutcome("slot_unavailable", None)
    return BookingOutcome("appointment_booked", booking_id)
