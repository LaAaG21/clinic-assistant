# API and database health

Issue #14 implements `GET /health` from the #6 contract using
`database.probe_database()`. Healthy API/database responses are HTTP 200:

```json
{"status":"ok","api":"reachable","database":"reachable"}
```

An unavailable database or invalid database configuration returns HTTP 503:

```json
{"status":"unavailable","api":"reachable","database":"unreachable"}
```

Responses use `Cache-Control: no-store`. Both outcomes are documented in OpenAPI.
Logs contain only the probe's fixed error code; responses contain no credentials
or driver exception. This endpoint does not check model-provider availability.

Export `DATABASE_URL`, `DB_CONNECT_TIMEOUT_SECONDS` (default 2), and
`DB_QUERY_TIMEOUT_MS` (default 1000) as described in [database access](../database-access.md).
The sync handler runs blocking database I/O in FastAPI's thread pool. It inherits
the helper's connection and query timeouts, not an absolute deadline covering DNS
or every network failure. Use one database host for the local probe.

Start the API with the README command and call `curl http://127.0.0.1:8000/health`.
No model key is needed. Set `TEST_DATABASE_URL` to a dedicated PostgreSQL database
and run `uv run --locked pytest tests/test_health.py tests/test_database.py -v`.
The healthy endpoint test performs a real `SELECT 1`; it fails rather than skips
when the test database is not configured. CI supplies the variable using its
existing ephemeral PostgreSQL service, also enabling #12's database tests.
The unavailable test reserves a non-listening local port and checks a safe 503
within five seconds. Configuration and OpenAPI checks require no database.

Verified November 2, 2026 on Python 3.12.15 against a disposable PostgreSQL 17.6
container: `uv run --locked pytest --cov --cov-config=pyproject.toml
--cov-report=term-missing --cov-fail-under=80` passed all 69 tests with no skips,
including five health tests and all seven database-helper tests. Application
coverage was 96.03%; the health module had 100% statement/branch coverage.
`uv run --locked ruff check .`, `uv run --locked ruff format --check .`, and
`uv run --locked mypy .` also passed. No model key was used. This is local
verification; GitHub CI results must be checked on the PR.
