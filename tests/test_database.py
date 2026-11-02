"""Real PostgreSQL tests: set TEST_DATABASE_URL to a dedicated test database."""

import os
import socket
from collections.abc import Iterator
from dataclasses import replace
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from clinic_assistant.database import DatabaseSettings, connection, probe_database


@pytest.fixture
def settings() -> DatabaseSettings:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL tests")
    return DatabaseSettings(url=url)


@pytest.fixture
def table(settings: DatabaseSettings) -> Iterator[sql.Identifier]:
    name = sql.Identifier("test_connection_" + uuid4().hex)
    with connection(settings) as conn, conn.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE TABLE {} (value integer)").format(name))
    try:
        yield name
    finally:
        with connection(settings) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("DROP TABLE {}").format(name))


def test_connectivity_and_commit(
    settings: DatabaseSettings, table: sql.Identifier
) -> None:
    assert probe_database(settings).ok
    with connection(settings) as conn, conn.cursor() as cursor:
        cursor.execute(sql.SQL("INSERT INTO {} VALUES (1)").format(table))
    assert conn.closed
    with connection(settings) as check, check.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT value FROM {}").format(table))
        assert cursor.fetchall() == [(1,)]
    assert check.closed


def test_query_failure_rolls_back_and_closes(
    settings: DatabaseSettings, table: sql.Identifier
) -> None:
    with pytest.raises(psycopg.errors.DivisionByZero):
        with connection(settings) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("INSERT INTO {} VALUES (2)").format(table))
            cursor.execute("SELECT 1 / 0")
    assert conn.closed
    with connection(settings) as check, check.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(table))
        assert cursor.fetchone() == (0,)


def test_python_failure_rolls_back_and_closes(
    settings: DatabaseSettings, table: sql.Identifier
) -> None:
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with connection(settings) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("INSERT INTO {} VALUES (3)").format(table))
            raise RuntimeError("synthetic failure")
    assert conn.closed
    with connection(settings) as check, check.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(table))
        assert cursor.fetchone() == (0,)


def test_query_timeout_closes_connection(settings: DatabaseSettings) -> None:
    with pytest.raises(psycopg.errors.QueryCanceled):
        with connection(replace(settings, query_timeout_ms=50)) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_sleep(0.3)")
    assert conn.closed


def test_unavailable_database_returns_safe_failure() -> None:
    # Reserve a local TCP port without listening; no database can own this port.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        settings = DatabaseSettings(
            url=f"postgresql://synthetic:secret-marker@127.0.0.1:{port}/missing"
        )
        started = monotonic()
        result = probe_database(settings)
        elapsed = monotonic() - started
    assert not result.ok and result.error == "unavailable"
    assert elapsed < 5
    assert "secret-marker" not in repr(result)
    assert "secret-marker" not in repr(settings)


def test_missing_configuration_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = probe_database()
    assert not result.ok and result.error == "configuration_error"


def test_environment_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/example")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("DB_QUERY_TIMEOUT_MS", "250")
    settings = DatabaseSettings.from_env()
    assert settings.connect_timeout_seconds == 3
    assert settings.query_timeout_ms == 250
    monkeypatch.setenv("DB_QUERY_TIMEOUT_MS", "invalid-secret-marker")
    result = probe_database()
    assert result.error == "configuration_error"
    assert "invalid-secret-marker" not in repr(result)
