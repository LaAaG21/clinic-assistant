# Shared application settings

Issue #18 provides `clinic_assistant.settings.get_settings()` for one validated
environment snapshot per process. `load_settings(mapping)` provides an uncached
loader for isolated tests and explicit configuration. Both raise `SettingsError`
with the field name and a safe explanation for missing or invalid values. They
do not echo input values, open database/model connections, or implicitly read
`.env`. Restart the process after changing environment settings.

| Variable | Rule |
| --- | --- |
| `DATABASE_URL` | Required PostgreSQL URL (`postgresql://` or `postgres://`) with one host, user, database, and a valid port. Password handling remains with PostgreSQL/libpq; the URL is hidden from settings representations. |
| `DB_CONNECT_TIMEOUT_SECONDS` | Integer >= 2, default 2; matches #12. |
| `DB_QUERY_TIMEOUT_MS` | Integer >= 1, default 1000; matches #12. |
| `CLINIC_TIMEZONE` | Required available IANA timezone; no machine-timezone default. `Asia/Dubai` in `.env.example` is an example, not a new clinic-policy decision. |
| `MODEL_BACKEND` | `fake` (default) or `openai`. This selects configuration, not an adapter implementation. |
| `OPENAI_API_KEY` | Required only for `openai`, stored as `SecretStr` and omitted from settings repr. Fake mode needs no key and discards any supplied key. |
| `OPENAI_MODEL` | Required only for `openai`; no model is silently selected. |
| `OPENAI_TIMEOUT_SECONDS` | Integer 1..120, default 10; SDK timeout and whole-call deadline. |
| `OPENAI_MAX_RETRIES` | Integer 0..2, default 0; bounded SDK retries inside the whole-call deadline. |

`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_PORT` keep their
existing #11 Compose meanings. The application uses `DATABASE_URL`, as #12 does;
it does not reconstruct a competing connection string from the Compose variables.
Keep the example's connection details consistent with the service. A container's
internal database port can differ from the port published to the developer host.

The #53 [real adapter](openai-model-adapter.md) consumes these validated fields;
fake mode requires no provider settings. This loader still performs no model I/O.

Call `get_settings()` at the consumer's initialization boundary, then pass the
validated fields to the existing helpers rather than re-reading the environment:

```python
from clinic_assistant.settings import get_settings
from clinic_assistant.database import connection

settings = get_settings()  # Validation only; raises immediately on bad values.
with connection(settings.database) as conn:
    pass  # The existing #12 helper owns connections and transactions.
```

Pass `settings.clinic_timezone` to `is_same_day_booking()` from #20. The timezone
defines the clinic's calendar day, not a fixed UTC offset. The loader uses the
existing `tzdata` dependency so named zones work on Windows too. This change
adds no routes and does not change #12's independent `from_env()` fallback;
consumers adopting the shared snapshot pass `settings.database` explicitly.

## Verification

```sh
uv sync --locked --group dev
uv run --locked pytest tests/test_settings.py -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

Tests use synthetic mappings or a replaced process environment, including a local
`.env` that must be ignored. They cover valid defaults/overrides, missing/blank
fields, malformed PostgreSQL URLs, ports, timeout bounds, invalid zones, safe
tracebacks, fake/real model-key rules, cached snapshots, and the existing same-day
policy. No real model key is needed and settings validation never contacts a DB.

Verified November 2, 2026 on Python 3.12.15: all 26 settings cases passed. With
`TEST_DATABASE_URL` set to a disposable PostgreSQL 17.6 database, the full suite
passed 90 tests with no skips and 97.04% application coverage; the settings module
had 100% statement/branch coverage. The full command was `uv run --locked pytest
--cov --cov-config=pyproject.toml --cov-report=term-missing --cov-fail-under=80`.
Lint, format, and strict types also passed. These are local results, not a claim
that a GitHub CI run has completed.

Validating a single snapshot gives consumers consistent configuration and clear
errors at initialization, rather than different defaults or failures scattered
through request handling.
