# Smoke checks

Issue #54 adds one entry point for quick checks against a running service. It
uses only the Python standard library and needs no model key or database
credentials. With the API running, run this from the repository root:

```sh
uv run --locked python -m clinic_assistant.smoke --base-url http://127.0.0.1:8000
```

`--base-url` defaults to `$SMOKE_BASE_URL`, or to `http://127.0.0.1:8000` when that
variable isn't set. It must be an `http(s)` URL with no credentials, query or
fragment. `--timeout` (default 5, maximum 60) sets the timeout for each socket
operation. DNS lookups aren't covered by that timeout, so use a host that
resolves locally.

## Checks

Every check runs and prints one `PASS` or `FAIL` line. The script never skips a
check or reports one as passed when it wasn't run.

| Check | Expectation |
| --- | --- |
| `health` | `GET /health` returns `200`, exactly the [agreed healthy body](health.md) from #14, and `Cache-Control: no-store`. |
| `openapi` | `GET /openapi.json` returns `200` with a JSON object that has an OpenAPI `3.x` version, `info.title`, `info.version`, and documented `GET /health` and `POST /conversations` operations. |
| `create-conversation` | `POST /conversations` with `{}` returns `201` and `application/json`, with a non-empty `conversation_id`, a `created_at` ISO 8601 timestamp that includes an offset, and a `Location` header whose path is `/conversations/{conversation_id}`. These follow the #6 contract; #44 implements them. |

The script doesn't follow redirects; it reports one as an unexpected status. It
rejects a response body larger than 1 MB.

## Exit status

| Code | Meaning |
| --- | --- |
| `0` | All checks passed. |
| `1` | At least one assertion failed, a request failed, or a request timed out. |
| `2` | The arguments are invalid. |

Failure lines show the method, path, status code, or exception type only. They
never include response bodies, headers, or the base URL's credentials.

## Synthetic records

Each run creates one empty conversation and sends no patient text, so it uses no
real patient data. Repeated runs are safe: each one adds a separate empty
conversation and changes no existing data. Message and booking scenarios will be
added in #74.

## Current status

Until #44 adds `POST /conversations`, a run against `main` reports `PASS health`
(when the database is reachable), then `FAIL openapi` and `FAIL
create-conversation`, and exits `1`. That's the intended result, because a
required endpoint is missing. A smoke run of the source-built Compose candidate
from #25 can succeed only after #44 and #25 are merged.

Verified November 5, 2026 on Python 3.12, using a disposable PostgreSQL 17.6
container and a local `uvicorn` server. The run against the live API gave the
partial result above and exited `1`. A run against an unreachable port reported
three `FAIL` lines and exited `1`. `tests/test_smoke.py` uses a local fake
service to cover the passing path and each failure path. The full suite, Ruff and
mypy passed with 98.73% coverage.
