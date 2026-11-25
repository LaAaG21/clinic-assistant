import pytest

TEST_SECRET = "test-secret-that-is-long-enough-for-hs256"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
