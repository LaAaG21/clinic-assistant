# Database helper and connectivity probe (issue #12)

`clinic_assistant.database.connection()` reads `DATABASE_URL`,
`DB_CONNECT_TIMEOUT_SECONDS` (default 2) and `DB_QUERY_TIMEOUT_MS` (default 1000).
Configuration is read at call time, so importing the app needs no database.
The application does not automatically load `.env`; export its variables into the
process before running Python. Compose reads `.env` separately.

```python
from clinic_assistant.database import connection, probe_database

with connection() as conn, conn.cursor() as cursor:
    cursor.execute("SELECT %s::integer", (1,))
    value = cursor.fetchone()

result = probe_database()
```

Normal exit commits; an escaping exception rolls back; both paths close the
connection and cursor. Let query exceptions leave the block. Do not swallow an
exception and assume the block will roll back prior successful work. Each helper
call creates one connection; this is not a pool or a LangGraph checkpointer.

The probe executes `SELECT 1` and returns `ProbeResult(ok=True, error=None)`,
`ProbeResult(ok=False, error="unavailable")` for driver/database failures, or
`ProbeResult(ok=False, error="configuration_error")` for invalid configuration.
It returns no DSN, credentials or exception text. The lower-level helper propagates
errors so callers can handle query failures; never expose raw driver exceptions.

Connection establishment uses explicit libpq `connect_timeout` (minimum 2 seconds).
Every statement has a PostgreSQL `statement_timeout` set at connection startup.
These bound connection attempts per host and server statement execution, not an
absolute wall-clock deadline covering DNS, multiple hosts or network outages after
connection. The local probe should use one host. No HTTP endpoint or application
tables are added.

## Verify on real PostgreSQL

From the repository root, copy `.env.example` to `.env` if needed, set a local
password and ensure its `DATABASE_URL` matches the PostgreSQL variables. Then:

```powershell
docker compose up -d --wait db
uv sync --locked --group dev
# Export your DATABASE_URL from .env into this terminal; do not commit it.
$env:DATABASE_URL = 'postgresql://clinic:YOUR_LOCAL_PASSWORD@127.0.0.1:5432/clinic'
$env:TEST_DATABASE_URL = $env:DATABASE_URL
uv run --locked pytest tests/test_database.py -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

Use a dedicated local/test database: integration tests create and drop uniquely
named test-only tables to observe commit and rollback across connections. They do
not create production tables. Without `TEST_DATABASE_URL`, four PostgreSQL tests
skip explicitly; unavailable-database and configuration tests still run. No model
API key is needed. The unavailable test reserves a non-listening localhost port,
uses the 2-second connection timeout and checks the safe failure result within 5s.
The statement-timeout test executes `pg_sleep(0.3)` with a 50ms timeout.

Connections must close after failed queries to release server slots, sockets,
transactions and locks. Leaking them can exhaust PostgreSQL even when each request
appears to have failed cleanly.

References: [psycopg connection contexts](https://www.psycopg.org/psycopg3/docs/basic/usage.html#connection-context),
[libpq connection timeout](https://www.postgresql.org/docs/17/libpq-connect.html#LIBPQ-CONNECT-CONNECT-TIMEOUT).

## Verification recorded on 2026-11-02

Focused pytest run: 3 passed (unavailable database and configuration), 4 skipped
(real PostgreSQL required). Ruff lint passed after formatting. Dependency lockfile
was updated with uv. Docker engine was unavailable, so successful PostgreSQL
connectivity, transaction cleanup/rollback and statement timeout still require
the real-database run above before closing #12. No HTTP endpoint was added.
