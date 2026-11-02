# API and PostgreSQL with Docker Compose

Issue #25 packages the existing FastAPI application from source. It uses the
shared settings from #18, the PostgreSQL helper from #12, and the real database
health endpoint from #14. This branch includes the prerequisite commits from
[PR #48](https://github.com/LaAaG21/clinic-assistant/pull/48) and
[PR #49](https://github.com/LaAaG21/clinic-assistant/pull/49) for integration testing;
they still need review and merging. No clinic workflows, schema, seed data, or
model calls are added by this task.

## Start from a clean checkout

Install Docker with Compose v2. No host Python or uv installation is required.
Copy `.env.example` to `.env` (`cp .env.example .env`, or
`Copy-Item .env.example .env` in PowerShell). Set a local password and confirm
`CLINIC_TIMEZONE`; `Asia/Dubai` is an example, not a clinic decision. Leave
`MODEL_BACKEND=fake` and `OPENAI_API_KEY` empty for credential-free verification.

```sh
docker compose up --build -d --wait
docker compose ps
curl --fail http://127.0.0.1:8000/openapi.json
curl --fail http://127.0.0.1:8000/health
```

The API waits for the PostgreSQL service's health check before starting. Its
entry point runs #18's `get_settings()` before starting Uvicorn on port 8000.
Invalid settings cause a nonzero exit with a field-specific safe message; no
credential value or traceback is printed. Direct developer use of
`uvicorn clinic_assistant.main:app` bypasses this entry-point validation. Use
`python -m clinic_assistant.serve` when testing the same startup behavior locally.

The Dockerfile installs uv 0.12.23 and runs
`uv sync --locked --no-dev --no-editable`, building the application from the
committed source. An outdated lockfile fails the build. The container runs as
UID 10001, with no host environment/source mounts. `.dockerignore` permits only
build inputs and excludes `.env`, `.git`, caches, local virtual environments,
tests, and research experiments. Only public Python/PostgreSQL base images are
pulled; the API image is built locally and never published to a registry.

## Configuration and connectivity

| Variable | Meaning |
| --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database and API connection credentials; password required. Use URL-safe letters, digits, `-`, `_` for these values because Compose constructs the connection URL. |
| `POSTGRES_PORT` | Host-only PostgreSQL port; default 5432. |
| `DATABASE_URL` | Used by Python/tests on the host. Compose deliberately builds its API URL from the PostgreSQL variables using `db:5432`, ignoring this host URL. |
| `API_PORT` | Host-only API port; default 8000. Internal API port stays 8000. |
| `CLINIC_TIMEZONE` | Required IANA timezone, validated by shared settings. |
| `MODEL_BACKEND`, `OPENAI_API_KEY` | Fake mode by default; key required only for `openai` configuration. This packaging does not implement a model adapter. |
| `DB_CONNECT_TIMEOUT_SECONDS`, `DB_QUERY_TIMEOUT_MS` | Shared helper limits, default 2 seconds and 1000 milliseconds. |

Inside the API container, `localhost` means the API container itself. Compose DNS
resolves `db` to the database container; use its internal port 5432 regardless of
the host's published port. Confirm the shared helper from inside the API:

```sh
docker compose exec -T api python -c "from clinic_assistant.settings import get_settings; from clinic_assistant.database import probe_database; result = probe_database(get_settings().database); print(result); assert result.ok"
```

Both ports bind only to `127.0.0.1` on the host. Use an approved proxy or tunnel
for access from another machine. Never publish real credentials or print a
resolved Compose configuration containing them. A running database volume keeps
its original credentials; changing `.env` does not rotate an existing user.

## Health failure and recovery

The container check calls `/health` with a four-second HTTP timeout every ten
seconds; Docker allows five seconds per check and marks it unhealthy after three
failures following the startup grace period. HTTP 503 fails the check. Increasing
database timeouts may require adjusting these limits together. Health reports API
and database reachability, not model/workflow readiness.

Run the outage exercise only against a disposable local Compose project:

```sh
docker compose stop db
curl -i http://127.0.0.1:8000/health
docker compose ps
docker compose start db
docker compose up -d --wait
curl --fail http://127.0.0.1:8000/health
```

During the outage, `/health` returns 503 with `status: unavailable` and
`database: unreachable`; `/openapi.json` still serves. Wait for the health-check
retries before inspecting Docker's `unhealthy` state. Starting PostgreSQL again
restores HTTP 200 and container health without recreating the API. Compose's
startup ordering does not guarantee that a dependency stays healthy, and an
unhealthy status alone does not restart a container.

`docker compose down` removes containers/network while preserving PostgreSQL's
named volume. Do not add `--volumes` unless you intend to delete that project's
database. For isolated tests, use a distinct `-p` project name, its own env file,
and free host ports for **every** Compose command.

## Recorded verification (November 2, 2026)

Built from a clean local clone of the committed issue branch, with no host venv
or source mounts. The ignored test `.env` used synthetic credentials, fake mode,
an empty model key, and ephemeral localhost ports. Every command used
`-p clinic-issue25-verification --env-file .env` to isolate its containers and
volume. The host `DATABASE_URL` deliberately pointed at an unusable localhost
address, confirming that Compose's internal URL is independent of it.

| Check | Observed result |
| --- | --- |
| `docker compose config --quiet` and `up --build -d --wait` | Passed; API and PostgreSQL became healthy. Python base resolved to 3.12.16; uv 0.12.23 installed 18 locked runtime packages including the source-built application. PostgreSQL was 17.6. |
| Host reads of `/openapi.json` and `/health` | HTTP 200; OpenAPI included `/health`; database reported reachable. |
| Shared `probe_database(get_settings().database)` inside API | `ProbeResult(ok=True, error=None)`; parsed hostname was `db`; fake mode and empty model key verified. |
| Runtime isolation | UID 10001; no `/app/.env` or `/app/.git` in the image. |
| One-off API with malformed synthetic `DATABASE_URL` | Nonzero exit before serving; safe configuration message with no synthetic secret marker or traceback. |
| Stop only test project's PostgreSQL | `/health` returned 503 with unavailable/unreachable values while `/openapi.json` remained 200. Docker reported API `unhealthy` after approximately 39 seconds. |
| Restart PostgreSQL and wait | Both services healthy; `/health` returned 200 again; API container ID unchanged. |
| Application quality gates | Ruff lint/format and strict mypy passed. All 98 tests passed with real PostgreSQL, no skips and 96.65% total coverage; no real model key. |

The successful checks cover the combined #14/#18 prerequisites on this branch.
Their merge/review remains pending; no claim is made that this packaging is
already on `main` or deployed to the Ubuntu VM. The disposable test project's
containers, network, and test-only volume were removed after verification.
