import time

import jwt
import pytest

from servers.medical_records.server import mcp
from shared.auth import JWT_ALGORITHM, UNAUTHORIZED, issue_token
from tests.conftest import TEST_SECRET
from tests.http_client import call_tool

LAST_A = {"date": "2026-10-02", "diagnosis": "Flu", "notes": "Rest"}
LAST_B = {
    "date": "2026-11-05",
    "diagnosis": "Seasonal allergy",
    "notes": "Antihistamine",
}


def token_for(sub: str, scopes=("records:read",)) -> str:
    return issue_token(sub, f"{sub}@example.com", list(scopes))


async def test_user_a_gets_own_last_record():
    assert (
        await call_tool(mcp, "get_my_last_medical_record", token_for("user-a"))
        == LAST_A
    )


async def test_user_b_gets_own_last_record():
    assert (
        await call_tool(mcp, "get_my_last_medical_record", token_for("user-b"))
        == LAST_B
    )


async def test_all_records_are_only_the_callers_and_sorted():
    records = await call_tool(mcp, "get_my_medical_records", token_for("user-a"))
    assert [record["date"] for record in records] == ["2026-03-14", "2026-10-02"]
    assert all(
        record["diagnosis"] not in ("Migraine", "Seasonal allergy")
        for record in records
    )


async def test_user_without_records_gets_error_not_someone_elses():
    result = await call_tool(mcp, "get_my_last_medical_record", token_for("user-c"))
    assert result == {"error": "no medical records found"}


@pytest.mark.parametrize(
    "tool", ["get_my_medical_records", "get_my_last_medical_record"]
)
async def test_missing_token_is_unauthorized(tool):
    assert await call_tool(mcp, tool) == UNAUTHORIZED


def forged(secret: str, expires_in: int) -> str:
    claims = {
        "sub": "user-a",
        "email": "a@example.com",
        "scopes": ["records:read"],
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


BAD_TOKENS = {
    "malformed": lambda: "garbage",
    "bad-signature": lambda: forged("wrong-secret-that-is-long-enough-123456", 60),
    "expired": lambda: forged(TEST_SECRET, -5),
    "missing-scope": lambda: token_for("user-a", scopes=("pharmacy:read",)),
}


@pytest.mark.parametrize(
    "tool", ["get_my_medical_records", "get_my_last_medical_record"]
)
@pytest.mark.parametrize("make_token", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
async def test_bad_token_returns_unauthorized_and_no_data(tool, make_token):
    assert await call_tool(mcp, tool, make_token()) == UNAUTHORIZED


async def test_tools_take_no_user_argument():
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.parameters.get("properties", {}) == {}
