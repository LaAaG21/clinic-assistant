"""Shared JWT contract for #314. Every MCP server keeps an identical copy.

Claims: sub (str), email (str), scopes (list[str]), exp (Unix time).
Signed with HS256 using the shared JWT_SECRET environment variable.
"""

import os
import time

import jwt
from fastmcp.server.dependencies import get_http_headers

JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME_SECONDS = 3600
REQUIRED_CLAIMS = ("sub", "email", "scopes", "exp")
UNAUTHORIZED = {"error": "unauthorized"}


class Unauthorized(Exception):
    """The token is missing, malformed, expired, badly signed or lacks a scope."""


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def issue_token(sub: str, email: str, scopes: list[str]) -> str:
    """Create the signed token that FastAPI hands to the MCP servers."""
    claims = {
        "sub": sub,
        "email": email,
        "scopes": scopes,
        "exp": int(time.time()) + TOKEN_LIFETIME_SECONDS,
    }
    return jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str, required_scope: str | None = None) -> dict:
    """Return the verified claims, or raise Unauthorized."""
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError as error:
        raise Unauthorized from error
    if not isinstance(claims["sub"], str) or not isinstance(claims["scopes"], list):
        raise Unauthorized
    if required_scope is not None and required_scope not in claims["scopes"]:
        raise Unauthorized
    return claims


def authorize(required_scope: str) -> dict:
    """Read the Bearer token from the current HTTP request and verify it."""
    header = get_http_headers(include={"authorization"}).get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme != "Bearer" or not token:
        raise Unauthorized
    return verify_token(token, required_scope)
