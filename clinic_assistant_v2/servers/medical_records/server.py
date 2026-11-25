"""Medical Records MCP (item 3). Every tool reads the caller from the verified JWT."""

import os

from fastmcp import FastMCP

from .auth import UNAUTHORIZED, Unauthorized, authorize

PORT = int(os.environ.get("PORT", "8003"))
HOST = "0.0.0.0"  # must not be 127.0.0.1 inside Docker
SCOPE = "records:read"

# Seed data keyed by the user's `sub`. Replace with Google sub values for real use.
RECORDS: dict[str, list[dict]] = {
    "user-a": [
        {"date": "2026-03-14", "diagnosis": "Sprained ankle", "notes": "Ice, brace"},
        {"date": "2026-10-02", "diagnosis": "Flu", "notes": "Rest"},
    ],
    "user-b": [
        {
            "date": "2026-08-21",
            "diagnosis": "Migraine",
            "notes": "Hydration, dark room",
        },
        {
            "date": "2026-11-05",
            "diagnosis": "Seasonal allergy",
            "notes": "Antihistamine",
        },
    ],
}

mcp = FastMCP("Medical Records")


@mcp.tool
def get_my_medical_records() -> list[dict] | dict:
    """Return all medical records of the signed-in user, oldest first."""
    try:
        sub = authorize(SCOPE)["sub"]
    except Unauthorized:
        return UNAUTHORIZED
    return sorted(RECORDS.get(sub, []), key=lambda record: record["date"])


@mcp.tool
def get_my_last_medical_record() -> dict:
    """Return the most recent medical record of the signed-in user."""
    try:
        sub = authorize(SCOPE)["sub"]
    except Unauthorized:
        return UNAUTHORIZED
    records = RECORDS.get(sub, [])
    if not records:
        return {"error": "no medical records found"}
    return max(records, key=lambda record: record["date"])


if __name__ == "__main__":
    mcp.run(transport="http", host=HOST, port=PORT)
