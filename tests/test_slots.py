"""Available-slot query (#71). PostgreSQL tests need TEST_DATABASE_URL.

All dates are clinic-local in Asia/Muscat (+04:00, no DST), passed explicitly.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Any, cast

import psycopg
import pytest

from clinic_assistant.slots import (
    AvailableSlot,
    clinic_day_bounds,
    list_available_slots,
)

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]
TZ = "Asia/Muscat"
NOV_3 = date(2026, 11, 3)

# slot_id: (doctor_id, local start in Muscat)
SLOTS = {
    "slot_prev_night": ("doctor_derm_1", "2026-11-02T23:30"),
    "slot_midnight": ("doctor_derm_1", "2026-11-03T00:00"),
    "slot_morning_a": ("doctor_derm_1", "2026-11-03T09:00"),
    "slot_morning_b": ("doctor_derm_2", "2026-11-03T09:00"),
    "slot_cardio": ("doctor_cardio", "2026-11-03T10:00"),
    "slot_late": ("doctor_derm_1", "2026-11-03T23:30"),
    "slot_next_midnight": ("doctor_derm_1", "2026-11-04T00:00"),
}


@pytest.fixture
def db(schema_db: Connect) -> Connect:
    """Two dermatologists, one cardiologist, slots around Nov 3 midnights."""
    with schema_db() as conn:
        conn.execute(
            "INSERT INTO doctors VALUES"
            " ('doctor_derm_1', 'Dr. A', 'dermatology'),"
            " ('doctor_derm_2', 'Dr. B', 'dermatology'),"
            " ('doctor_cardio', 'Dr. C', 'cardiology')"
        )
        for slot_id, (doctor_id, local_start) in SLOTS.items():
            conn.execute(
                "INSERT INTO slots VALUES (%s, %s, %s::timestamp AT TIME ZONE %s,"
                " (%s::timestamp + interval '30 minutes') AT TIME ZONE %s)",
                (slot_id, doctor_id, local_start, TZ, local_start, TZ),
            )
        conn.execute("INSERT INTO conversations (conversation_id) VALUES ('conv_1')")
    return schema_db


def ids(slots: list[AvailableSlot]) -> list[str]:
    return [slot.slot_id for slot in slots]


def book(conn: Conn, booking_id: str, slot_id: str) -> None:
    conn.execute(
        "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
        " VALUES (%s, %s, 'conv_1')",
        (booking_id, slot_id),
    )


def test_filter_by_specialty_returns_ordered_slots(db: Connect) -> None:
    with db() as conn:
        slots = list_available_slots(conn, NOV_3, TZ, specialty="dermatology")
    assert ids(slots) == [
        "slot_midnight",
        "slot_morning_a",
        "slot_morning_b",  # same start as _a: slot_id breaks the tie
        "slot_late",
    ]
    assert slots[0] == AvailableSlot(
        slot_id="slot_midnight",
        doctor_id="doctor_derm_1",
        specialty="dermatology",
        starts_at=datetime.fromisoformat("2026-11-03T00:00:00+04:00"),
        ends_at=datetime.fromisoformat("2026-11-03T00:30:00+04:00"),
    )


def test_specialty_ignores_case_and_outer_spaces(db: Connect) -> None:
    with db() as conn:
        slots = list_available_slots(conn, NOV_3, TZ, specialty="  Cardiology ")
    assert ids(slots) == ["slot_cardio"]


def test_filter_by_doctor(db: Connect) -> None:
    with db() as conn:
        slots = list_available_slots(conn, NOV_3, TZ, doctor_id="doctor_derm_2")
    assert ids(slots) == ["slot_morning_b"]


@pytest.mark.parametrize(
    ("doctor_id", "specialty", "expected"),
    [
        ("doctor_derm_2", "dermatology", ["slot_morning_b"]),
        ("doctor_cardio", "dermatology", []),
    ],
)
def test_doctor_and_specialty_mean_intersection(
    db: Connect, doctor_id: str, specialty: str, expected: list[str]
) -> None:
    with db() as conn:
        slots = list_available_slots(
            conn, NOV_3, TZ, doctor_id=doctor_id, specialty=specialty
        )
    assert ids(slots) == expected


def test_clinic_midnight_boundaries(db: Connect) -> None:
    """Start-of-day midnight is in; next-day midnight and the night before are out."""
    with db() as conn:
        nov_3 = ids(list_available_slots(conn, NOV_3, TZ, doctor_id="doctor_derm_1"))
        nov_4 = ids(
            list_available_slots(conn, date(2026, 11, 4), TZ, doctor_id="doctor_derm_1")
        )
    assert nov_3 == ["slot_midnight", "slot_morning_a", "slot_late"]
    assert nov_4 == ["slot_next_midnight"]


def test_clinic_timezone_decides_the_day_not_utc(db: Connect) -> None:
    """slot_late is 23:30 Muscat on Nov 3 but 19:30 UTC; slot_midnight is Nov 2 UTC."""
    with db() as conn:
        utc_day = ids(
            list_available_slots(conn, NOV_3, "UTC", doctor_id="doctor_derm_1")
        )
    assert utc_day == ["slot_morning_a", "slot_late", "slot_next_midnight"]


def test_booked_slot_is_hidden_and_cancelled_slot_returns(db: Connect) -> None:
    with db() as conn:
        book(conn, "booking_1", "slot_morning_a")
    with db() as conn:
        assert "slot_morning_a" not in ids(
            list_available_slots(conn, NOV_3, TZ, specialty="dermatology")
        )
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', cancelled_at = now()"
            " WHERE booking_id = 'booking_1'"
        )
        assert "slot_morning_a" in ids(
            list_available_slots(conn, NOV_3, TZ, specialty="dermatology")
        )


def test_no_match_returns_empty_list(db: Connect) -> None:
    with db() as conn:
        assert list_available_slots(conn, NOV_3, TZ, specialty="neurology") == []
        assert (
            list_available_slots(conn, date(2026, 12, 1), TZ, specialty="cardiology")
            == []
        )


def test_limit_caps_results_in_order(db: Connect) -> None:
    with db() as conn:
        slots = list_available_slots(conn, NOV_3, TZ, specialty="dermatology", limit=2)
    assert ids(slots) == ["slot_midnight", "slot_morning_a"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "doctor_id, specialty, or both"),
        ({"specialty": "   "}, "specialty must not be blank"),
        ({"doctor_id": "d", "limit": 0}, "limit must be between 1 and 100"),
        ({"doctor_id": "d", "limit": 101}, "limit must be between 1 and 100"),
        ({"doctor_id": "d", "tz": "Mars/Base"}, "available IANA timezone"),
    ],
)
def test_invalid_input_is_rejected_before_querying(
    kwargs: dict[str, Any], message: str
) -> None:
    tz = kwargs.pop("tz", TZ)
    no_connection = cast(Conn, None)  # validation must fail before any query
    with pytest.raises(ValueError, match=message):
        list_available_slots(no_connection, NOV_3, tz, **kwargs)


def test_clinic_day_bounds_are_local_midnights() -> None:
    start, end = clinic_day_bounds(NOV_3, TZ)
    assert start.isoformat() == "2026-11-03T00:00:00+04:00"
    assert end.isoformat() == "2026-11-04T00:00:00+04:00"
