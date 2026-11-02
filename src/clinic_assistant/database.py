"""Small PostgreSQL readiness probe; no application schema exists yet."""

import psycopg


def database_is_ready(database_url: str | None) -> bool:
    """Check PostgreSQL without exposing connection details in API responses."""
    if not database_url:
        return False

    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            # This fixed query has no interpolated input. Future data queries must
            # bind values through psycopg's parameter argument, never SQL strings.
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except psycopg.Error:
        return False
