import time
from pathlib import Path

import jwt
import pytest

from shared.auth import (
    JWT_ALGORITHM,
    TOKEN_LIFETIME_SECONDS,
    Unauthorized,
    authorize,
    issue_token,
    verify_token,
)
from tests.conftest import TEST_SECRET

ROOT = Path(__file__).resolve().parent.parent


def forge(secret=TEST_SECRET, **overrides):
    claims = {
        "sub": "user-a",
        "email": "a@example.com",
        "scopes": ["records:read"],
        "exp": int(time.time()) + 60,
    } | overrides
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def test_issued_token_has_exactly_the_contract_claims():
    token = issue_token("user-a", "a@example.com", ["records:read"])
    claims = jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])
    assert set(claims) == {"sub", "email", "scopes", "exp"}
    assert claims["exp"] - time.time() == pytest.approx(TOKEN_LIFETIME_SECONDS, abs=5)


def test_valid_token_returns_claims():
    claims = verify_token(forge(), "records:read")
    assert claims["sub"] == "user-a"


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        forge(secret="another-secret-that-is-long-enough-123"),
        forge(exp=int(time.time()) - 10),
        forge(sub=None),
        forge(scopes="records:read"),
        forge(scopes=["pharmacy:read"]),
    ],
    ids=[
        "empty",
        "malformed",
        "bad-signature",
        "expired",
        "no-sub",
        "scopes-not-list",
        "missing-scope",
    ],
)
def test_bad_token_is_rejected(token):
    with pytest.raises(Unauthorized):
        verify_token(token, "records:read")


def test_unsigned_token_is_rejected():
    unsigned = jwt.encode(
        {"sub": "x", "email": "x", "scopes": [], "exp": 9**10}, None, algorithm="none"
    )
    with pytest.raises(Unauthorized):
        verify_token(unsigned)


@pytest.mark.parametrize("header", [None, "", "Bearer", "Basic abc", "bearer abc"])
def test_authorize_rejects_missing_or_malformed_header(monkeypatch, header):
    headers = {} if header is None else {"authorization": header}
    monkeypatch.setattr("shared.auth.get_http_headers", lambda include: headers)
    with pytest.raises(Unauthorized):
        authorize("records:read")


def test_authorize_accepts_bearer_header(monkeypatch):
    headers = {"authorization": f"Bearer {forge()}"}
    monkeypatch.setattr("shared.auth.get_http_headers", lambda include: headers)
    assert authorize("records:read")["email"] == "a@example.com"


def test_server_copies_match_the_shared_contract():
    shared = (ROOT / "shared" / "auth.py").read_text()
    for copy in (ROOT / "servers").glob("*/auth.py"):
        assert copy.read_text() == shared, f"{copy} drifted from shared/auth.py"
