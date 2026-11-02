"""Plain-SQL connections and a credential-safe PostgreSQL connectivity probe."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

import psycopg


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = field(repr=False)
    connect_timeout_seconds: int = 2
    query_timeout_ms: int = 1000

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ValueError("DATABASE_URL is required")
        if self.connect_timeout_seconds < 2 or self.query_timeout_ms < 1:
            raise ValueError("Connection timeout must be >=2s; query timeout >=1ms")

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        try:
            return cls(
                url=os.environ["DATABASE_URL"],
                connect_timeout_seconds=int(
                    os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "2")
                ),
                query_timeout_ms=int(os.getenv("DB_QUERY_TIMEOUT_MS", "1000")),
            )
        except (KeyError, ValueError):
            raise ValueError("Invalid database environment configuration") from None


@contextmanager
def connection(
    settings: DatabaseSettings | None = None,
) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Commit on normal exit, roll back on exceptions, and always close.

    The caller must let failures escape this block for automatic rollback.
    psycopg errors propagate; do not expose their text to clients or logs.
    """
    settings = settings if settings is not None else DatabaseSettings.from_env()
    with psycopg.connect(
        settings.url,
        connect_timeout=settings.connect_timeout_seconds,
        options=f"-c statement_timeout={settings.query_timeout_ms}",
    ) as conn:
        yield conn


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    error: Literal["unavailable", "configuration_error"] | None = None


def probe_database(settings: DatabaseSettings | None = None) -> ProbeResult:
    """SELECT 1 with bounded connection/query waits; never return driver details."""
    try:
        with connection(settings) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                return ProbeResult(ok=False, error="unavailable")
        return ProbeResult(ok=True)
    except ValueError:
        return ProbeResult(ok=False, error="configuration_error")
    except psycopg.Error:
        return ProbeResult(ok=False, error="unavailable")
