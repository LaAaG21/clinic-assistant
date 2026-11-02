"""PostgreSQL is required for integration tests; there is no fallback database."""

import os

import pytest


@pytest.fixture
def database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL must point to a running PostgreSQL test database. "
            "Start the Compose database or use the CI PostgreSQL service."
        )
    return url
