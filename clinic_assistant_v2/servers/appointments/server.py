"""Appointments MCP (item 1). Every tool reads the caller from the verified JWT."""

import os
from datetime import date, time

from fastmcp import FastMCP

from .auth import UNAUTHORIZED, Unauthorized, authorize

PORT = int(os.environ.get("PORT", "8001"))
HOST = "0.0.0.0"  # must not be 127.0.0.1 inside Docker
READ_SCOPE = "appointments:read"
WRITE_SCOPE = "appointments:write"

# In-memory store: id -> appointment. `owner` is the caller's `sub`; it is never returned.
APPOINTMENTS: dict[int, dict] = {
    1: {
        "owner": "user-a",
        "doctor": "Dr. Salma Haddad",
        "date": "2026-12-03",
        "time": "09:30",
    },
    2: {
        "owner": "user-b",
        "doctor": "Dr. Omar Nasser",
        "date": "2026-12-04",
        "time": "14:00",
    },
}

mcp = FastMCP("Appointments")


def _public(appointment_id: int) -> dict:
    appointment = APPOINTMENTS[appointment_id]
    return {
        "appointment_id": appointment_id,
        "doctor": appointment["doctor"],
        "date": appointment["date"],
        "time": appointment["time"],
    }


@mcp.tool
def book_appointment(doctor: str, date_iso: str, time_hhmm: str) -> dict:
    """Book an appointment for the signed-in user. Date is YYYY-MM-DD, time is HH:MM."""
    try:
        sub = authorize(WRITE_SCOPE)["sub"]
    except Unauthorized:
        return UNAUTHORIZED
    try:
        date.fromisoformat(date_iso)
        time.fromisoformat(time_hhmm)
    except ValueError:
        return {"error": "date must be YYYY-MM-DD and time must be HH:MM"}
    if any(
        a["doctor"] == doctor and a["date"] == date_iso and a["time"] == time_hhmm
        for a in APPOINTMENTS.values()
    ):
        return {"error": f"{doctor} is not available at {date_iso} {time_hhmm}"}
    appointment_id = max(APPOINTMENTS, default=0) + 1
    APPOINTMENTS[appointment_id] = {
        "owner": sub,
        "doctor": doctor,
        "date": date_iso,
        "time": time_hhmm,
    }
    return _public(appointment_id)


@mcp.tool
def list_my_appointments() -> list[dict] | dict:
    """Return the signed-in user's appointments, earliest first."""
    try:
        sub = authorize(READ_SCOPE)["sub"]
    except Unauthorized:
        return UNAUTHORIZED
    mine = [_public(i) for i, a in APPOINTMENTS.items() if a["owner"] == sub]
    return sorted(mine, key=lambda a: (a["date"], a["time"]))


@mcp.tool
def cancel_appointment(appointment_id: int) -> dict:
    """Cancel one of the signed-in user's own appointments by its id."""
    try:
        sub = authorize(WRITE_SCOPE)["sub"]
    except Unauthorized:
        return UNAUTHORIZED
    appointment = APPOINTMENTS.get(appointment_id)
    # Same answer for "does not exist" and "belongs to someone else": no id probing.
    if appointment is None or appointment["owner"] != sub:
        return {"error": "appointment not found"}
    cancelled = _public(appointment_id)
    del APPOINTMENTS[appointment_id]
    return {"cancelled": cancelled}


if __name__ == "__main__":
    mcp.run(transport="http", host=HOST, port=PORT)
