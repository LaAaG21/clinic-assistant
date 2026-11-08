"""Available-slot lookup (#71): plain parameterized SQL, clinic-local dates.

A slot is available when it has no active booking (`bookings.status = 'booked'`);
cancelled bookings free the slot again. HTTP integration is #76.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.rows import class_row

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

_QUERY = """
SELECT s.slot_id, s.doctor_id, d.specialty, s.starts_at, s.ends_at
FROM slots AS s
JOIN doctors AS d USING (doctor_id)
WHERE s.starts_at >= %(day_start)s
  AND s.starts_at < %(day_end)s
  AND (%(doctor_id)s::text IS NULL OR s.doctor_id = %(doctor_id)s)
  AND (%(specialty)s::text IS NULL OR lower(d.specialty) = lower(%(specialty)s))
  AND NOT EXISTS (
      SELECT 1 FROM bookings AS b
      WHERE b.slot_id = s.slot_id AND b.status = 'booked'
  )
  AND (
      %(after_start)s::timestamptz IS NULL
      OR (s.starts_at, s.slot_id) > (%(after_start)s, %(after_slot_id)s::text)
  )
ORDER BY s.starts_at, s.slot_id
LIMIT %(limit)s
"""

# Keyset position for pagination: the (starts_at, slot_id) of the last slot seen.
After = tuple[datetime, str]


@dataclass(frozen=True, slots=True)
class AvailableSlot:
    """Same fields as the API `Slot` model (#6), so #76 can map it directly."""

    slot_id: str
    doctor_id: str
    specialty: str
    starts_at: datetime
    ends_at: datetime


def clinic_day_bounds(day: date, clinic_timezone: str) -> tuple[datetime, datetime]:
    """Return [start, end) of a calendar day in the clinic timezone, as instants."""
    try:
        zone = ZoneInfo(clinic_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("clinic_timezone must be an available IANA timezone") from None
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start, end


def list_available_slots(
    conn: psycopg.Connection[tuple[object, ...]],
    day: date,
    clinic_timezone: str,
    *,
    doctor_id: str | None = None,
    specialty: str | None = None,
    limit: int = DEFAULT_LIMIT,
    after: After | None = None,
) -> list[AvailableSlot]:
    """Free slots on a clinic-local day for a doctor, a specialty, or both.

    Both filters together mean their intersection. Results are ordered by start
    time, then slot ID, and capped at `limit` (1..100). The caller owns the
    connection, so its statement timeout bounds the query.
    """
    slots, _ = available_slot_page(
        conn,
        day,
        clinic_timezone,
        doctor_id=doctor_id,
        specialty=specialty,
        limit=limit,
        after=after,
    )
    return slots


def available_slot_page(
    conn: psycopg.Connection[tuple[object, ...]],
    day: date,
    clinic_timezone: str,
    *,
    doctor_id: str | None = None,
    specialty: str | None = None,
    limit: int = DEFAULT_LIMIT,
    after: After | None = None,
) -> tuple[list[AvailableSlot], bool]:
    """Like `list_available_slots`, plus whether more slots follow this page.

    `after` continues strictly after a previous page's last (starts_at, slot_id).
    """
    if specialty is not None:
        specialty = specialty.strip()
        if not specialty:
            raise ValueError("specialty must not be blank")
    if doctor_id is None and specialty is None:
        raise ValueError("give doctor_id, specialty, or both")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    day_start, day_end = clinic_day_bounds(day, clinic_timezone)
    after_start, after_slot_id = after if after is not None else (None, None)
    params = {
        "day_start": day_start,
        "day_end": day_end,
        "doctor_id": doctor_id,
        "specialty": specialty,
        "after_start": after_start,
        "after_slot_id": after_slot_id,
        "limit": limit + 1,  # one extra row tells us whether another page exists
    }
    # class_row builds AvailableSlot from the selected column names.
    with conn.cursor(row_factory=class_row(AvailableSlot)) as cursor:
        cursor.execute(_QUERY, params)
        rows = cursor.fetchall()
    return rows[:limit], len(rows) > limit
