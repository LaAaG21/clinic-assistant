"""Fixed-time examples of the clinic-local calendar-date boundary."""

import os
import subprocess
import sys
from datetime import datetime, tzinfo

import pytest

from clinic_assistant.booking_policy import is_same_day_booking


@pytest.mark.parametrize(
    ("appointment", "current", "clinic_timezone", "expected"),
    [
        ("2026-11-02T10:00:00+04:00", "2026-11-02T09:00:00+04:00", "Asia/Dubai", True),
        ("2026-11-03T10:00:00+04:00", "2026-11-02T09:00:00+04:00", "Asia/Dubai", False),
        # Past times on today's date still count; availability is a separate policy.
        ("2026-11-02T08:00:00+04:00", "2026-11-02T09:00:00+04:00", "Asia/Dubai", True),
        # The same instant has different UTC and offset-local dates.
        ("2026-11-03T00:30:00+04:00", "2026-11-02T20:30:00+00:00", "Asia/Dubai", True),
        # Different UTC dates, same clinic date (Nov 3).
        ("2026-11-03T01:00:00+00:00", "2026-11-02T21:00:00+00:00", "Asia/Dubai", True),
        # Same UTC date, opposite sides of clinic midnight.
        ("2026-11-02T20:00:00+00:00", "2026-11-02T19:59:59+00:00", "Asia/Dubai", False),
        ("2026-11-02T19:59:59+00:00", "2026-11-02T20:00:00+00:00", "Asia/Dubai", False),
        # Negative offset: UTC Nov 3 still belongs to clinic Nov 2.
        (
            "2026-11-03T02:00:00+00:00",
            "2026-11-02T23:00:00+00:00",
            "America/New_York",
            True,
        ),
        # Repeated hour during DST fallback: different instants, same local date.
        (
            "2026-11-01T01:30:00-05:00",
            "2026-11-01T01:30:00-04:00",
            "America/New_York",
            True,
        ),
        # The DST spring-forward day is a calendar day, not a 24-hour window.
        (
            "2026-03-08T23:30:00-04:00",
            "2026-03-08T00:30:00-05:00",
            "America/New_York",
            True,
        ),
    ],
)
def test_clinic_calendar_dates(
    appointment: str, current: str, clinic_timezone: str, expected: bool
) -> None:
    assert (
        is_same_day_booking(
            datetime.fromisoformat(appointment),
            datetime.fromisoformat(current),
            clinic_timezone,
        )
        is expected
    )


@pytest.mark.parametrize("naive_input", ["appointment_time", "current_time"])
def test_rejects_naive_timestamps(naive_input: str) -> None:
    aware = datetime.fromisoformat("2026-11-02T12:00:00+00:00")
    naive = aware.replace(tzinfo=None)
    appointment = naive if naive_input == "appointment_time" else aware
    current = naive if naive_input == "current_time" else aware
    with pytest.raises(ValueError, match=naive_input):
        is_same_day_booking(appointment, current, "Asia/Dubai")


def test_rejects_tzinfo_without_offset() -> None:
    # tzinfo being present alone does not make a datetime timezone-aware.
    class NoOffset(tzinfo):
        def utcoffset(self, dt: datetime | None) -> None:
            return None

        def dst(self, dt: datetime | None) -> None:
            return None

        def tzname(self, dt: datetime | None) -> None:
            return None

    aware = datetime.fromisoformat("2026-11-02T12:00:00+00:00")
    with pytest.raises(ValueError, match="appointment_time"):
        is_same_day_booking(aware.replace(tzinfo=NoOffset()), aware, "Asia/Dubai")


@pytest.mark.parametrize("zone", ["Invalid/Clinic", "", "../Asia/Dubai", "/Asia/Dubai"])
def test_rejects_invalid_timezone(zone: str) -> None:
    aware = datetime.fromisoformat("2026-11-02T12:00:00+00:00")
    with pytest.raises(ValueError, match="clinic_timezone"):
        is_same_day_booking(aware, aware, zone)


@pytest.mark.parametrize("machine_timezone", ["UTC0", "EST5EDT", "JST-9"])
def test_independent_of_machine_timezone(machine_timezone: str) -> None:
    # tzset applies TZ on Unix; on Windows the helper still uses explicit zones.
    program = """
import time
from datetime import datetime
from clinic_assistant.booking_policy import is_same_day_booking
if hasattr(time, 'tzset'):
    time.tzset()
assert is_same_day_booking(
    datetime.fromisoformat('2026-11-03T01:00:00+00:00'),
    datetime.fromisoformat('2026-11-02T21:00:00+00:00'),
    'Asia/Dubai',
)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "TZ": machine_timezone},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
