from fastmcp import FastMCP

from shared.auth import UNAUTHORIZED, Unauthorized, authorize, issue_token
from tests.http_client import call_tool

mcp = FastMCP("probe")


@mcp.tool
def whoami() -> dict:
    """Return the caller's email from the verified token."""
    try:
        return {"email": authorize("records:read")["email"]}
    except Unauthorized:
        return UNAUTHORIZED


async def test_header_reaches_the_tool():
    token = issue_token("user-a", "a@example.com", ["records:read"])
    assert await call_tool(mcp, "whoami", token) == {"email": "a@example.com"}


async def test_no_header_is_unauthorized():
    assert await call_tool(mcp, "whoami") == UNAUTHORIZED
