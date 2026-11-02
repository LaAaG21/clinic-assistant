"""Calendar-date policy for identifying same-day clinic bookings."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_same_day_booking(
    appointment_time: datetime,
    current_time: datetime,
    clinic_timezone: str,
) -> bool:
    """Compare aware instants by calendar date in an explicit IANA timezone.

    Raise ValueError for naive timestamps or an invalid/unavailable timezone.
    No system clock or machine timezone is consulted. This does not determine
    whether the appointment is in the future, available, or approved.
    """
    for name, value in (
        ("appointment_time", appointment_time),
        ("current_time", current_time),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")

    try:
        clinic_zone = ZoneInfo(clinic_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("clinic_timezone must be an available IANA timezone") from None

    return (
        appointment_time.astimezone(clinic_zone).date()
        == current_time.astimezone(clinic_zone).date()
    )
