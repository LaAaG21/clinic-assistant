import copy
import time

import jwt
import pytest

from servers.appointments import server
from servers.appointments.server import mcp
from shared.auth import JWT_ALGORITHM, UNAUTHORIZED, issue_token
from tests.conftest import TEST_SECRET
from tests.http_client import call_tool

ALL_SCOPES = ("appointments:read", "appointments:write")


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(server, "APPOINTMENTS", copy.deepcopy(server.APPOINTMENTS))


def token_for(sub: str, scopes=ALL_SCOPES) -> str:
    return issue_token(sub, f"{sub}@example.com", list(scopes))


async def test_user_sees_only_own_appointments():
    mine = await call_tool(mcp, "list_my_appointments", token_for("user-a"))
    assert [a["doctor"] for a in mine] == ["Dr. Salma Haddad"]
    assert all("owner" not in a for a in mine)


async def test_booking_appears_in_own_list_only():
    booked = await call_tool(
        mcp,
        "book_appointment",
        token_for("user-a"),
        doctor="Dr. Lina Farouk",
        date_iso="2026-12-10",
        time_hhmm="11:00",
    )
    assert booked["doctor"] == "Dr. Lina Farouk"
    own = await call_tool(mcp, "list_my_appointments", token_for("user-a"))
    other = await call_tool(mcp, "list_my_appointments", token_for("user-b"))
    assert booked["appointment_id"] in [a["appointment_id"] for a in own]
    assert booked["appointment_id"] not in [a["appointment_id"] for a in other]


async def test_double_booking_the_same_slot_is_refused():
    result = await call_tool(
        mcp,
        "book_appointment",
        token_for("user-b"),
        doctor="Dr. Salma Haddad",
        date_iso="2026-12-03",
        time_hhmm="09:30",
    )
    assert "not available" in result["error"]


@pytest.mark.parametrize(
    ("date_iso", "time_hhmm"), [("12/10/2026", "11:00"), ("2026-12-10", "late")]
)
async def test_invalid_date_or_time_is_refused(date_iso, time_hhmm):
    result = await call_tool(
        mcp,
        "book_appointment",
        token_for("user-a"),
        doctor="Dr. Lina Farouk",
        date_iso=date_iso,
        time_hhmm=time_hhmm,
    )
    assert "error" in result


async def test_user_can_cancel_own_appointment():
    result = await call_tool(
        mcp, "cancel_appointment", token_for("user-a"), appointment_id=1
    )
    assert result["cancelled"]["appointment_id"] == 1
    assert await call_tool(mcp, "list_my_appointments", token_for("user-a")) == []


async def test_user_cannot_cancel_another_users_appointment():
    # Appointment 2 belongs to user-b; the answer matches a missing id.
    stolen = await call_tool(
        mcp, "cancel_appointment", token_for("user-a"), appointment_id=2
    )
    missing = await call_tool(
        mcp, "cancel_appointment", token_for("user-a"), appointment_id=999
    )
    assert stolen == missing == {"error": "appointment not found"}
    assert len(await call_tool(mcp, "list_my_appointments", token_for("user-b"))) == 1


CALLS = {
    "book_appointment": {
        "doctor": "Dr. X",
        "date_iso": "2026-12-10",
        "time_hhmm": "11:00",
    },
    "list_my_appointments": {},
    "cancel_appointment": {"appointment_id": 1},
}


def forged(secret: str, expires_in: int) -> str:
    claims = {
        "sub": "user-a",
        "email": "a@example.com",
        "scopes": list(ALL_SCOPES),
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


BAD_TOKENS = {
    "missing": lambda: None,
    "malformed": lambda: "garbage",
    "bad-signature": lambda: forged("wrong-secret-that-is-long-enough-123456", 60),
    "expired": lambda: forged(TEST_SECRET, -5),
    "missing-scope": lambda: token_for("user-a", scopes=("records:read",)),
}


@pytest.mark.parametrize("tool", CALLS)
@pytest.mark.parametrize("make_token", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
async def test_bad_token_returns_unauthorized_and_changes_nothing(tool, make_token):
    assert await call_tool(mcp, tool, make_token(), **CALLS[tool]) == UNAUTHORIZED
    assert len(server.APPOINTMENTS) == 2


async def test_read_only_scope_cannot_write():
    read_only = token_for("user-a", scopes=("appointments:read",))
    result = await call_tool(mcp, "cancel_appointment", read_only, appointment_id=1)
    assert result == UNAUTHORIZED
    assert len(await call_tool(mcp, "list_my_appointments", read_only)) == 1


async def test_no_tool_takes_a_user_argument():
    for tool in await mcp.list_tools():
        arguments = set(tool.parameters["properties"])
        assert not {"sub", "user", "user_id", "patient_id"} & arguments
