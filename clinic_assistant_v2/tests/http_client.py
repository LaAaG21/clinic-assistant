"""Call a FastMCP server in-process over real HTTP, so the Authorization header
travels the same path as in production."""

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def call_tool(mcp, tool: str, token: str | None = None, **arguments):
    app = mcp.http_app(path="/mcp")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def client_factory(headers=None, timeout=None, auth=None, **kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    transport = StreamableHttpTransport(
        "http://test/mcp", headers=headers, httpx_client_factory=client_factory
    )
    async with app.router.lifespan_context(app):
        async with Client(transport) as client:
            result = await client.call_tool(tool, arguments)
    return result.data
