# API and PostgreSQL with Docker Compose (#25)

Issue #25 packages the existing FastAPI application from source and runs it next
to the PostgreSQL service from #11. It uses the shared settings loader (#18),
the database helper (#12) and the real health endpoint (#14). Clinic workflows,
seed data and clinic documents are separate issues; the container serves the
same foundation as `uvicorn clinic_assistant.main:app` on the host.

## Start from a clean checkout

Install Docker with Compose v2. No host Python or uv is required. Copy
`.env.example` to `.env` (`cp .env.example .env`, or `Copy-Item .env.example .env`
in PowerShell), set a local `POSTGRES_PASSWORD` and confirm `CLINIC_TIMEZONE`
(`Asia/Dubai` is an example, not a clinic decision). Leave `MODEL_BACKEND=fake`
and `OPENAI_API_KEY` empty for credential-free operation.

```sh
docker compose up --build -d --wait
docker compose ps
curl --fail http://127.0.0.1:8000/openapi.json
curl --fail http://127.0.0.1:8000/health
```

`--wait` returns once both health checks pass. The API waits for PostgreSQL's
`pg_isready` check before it starts, and its entry point
(`python -m clinic_assistant.serve`) runs `get_settings()` before Uvicorn listens
on port 8000: invalid settings end the container with a nonzero exit and a
field-specific message that never echoes a value. The host command
`uvicorn clinic_assistant.main:app` bypasses that validation; use
`uv run python -m clinic_assistant.serve` to reproduce the container start.

The `Dockerfile` installs uv 0.12.23 and runs `uv sync --locked --no-dev
--no-editable`, so the image is built from the committed source and lockfile; an
outdated lockfile fails the build. The container runs as UID 10001 with no
source or environment mounts. `.dockerignore` allows only `Dockerfile`,
`pyproject.toml`, `uv.lock`, `README.md` and `src/`, so `.env`, `.git`, tests,
experiments and virtual environments never enter the build context. Only public
Python and PostgreSQL base images are pulled; the API image is built locally and
never pushed to a registry.

## Configuration

| Variable | Meaning in Compose |
| --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database name and credentials; the password is required. Use URL-safe characters (letters, digits, `-`, `_`) because Compose builds the API's connection URL from them. |
| `POSTGRES_PORT` | Host-only PostgreSQL port, default 5432. |
| `DATABASE_URL` | For Python and tests on the host only. The API container gets its own `postgresql://<user>:<password>@db:5432/<db>`; the host value is ignored inside Compose. |
| `API_PORT` | Host-only API port, default 8000. The container always listens on 8000. |
| `CLINIC_TIMEZONE` | Required IANA timezone, validated at startup. |
| `MODEL_BACKEND`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES` | Model settings from #18; fake mode by default and no key needed. |
| `DB_CONNECT_TIMEOUT_SECONDS`, `DB_QUERY_TIMEOUT_MS` | Shared helper limits, default 2 seconds and 1000 ms. |

Inside the API container `localhost` is the API container itself. Compose DNS
resolves `db` to the database container on its internal port 5432, whatever the
host port is. Confirm the shared helper from inside the API:

```sh
docker compose exec -T api python -c "from clinic_assistant.settings import get_settings; from clinic_assistant.database import probe_database; r = probe_database(get_settings().database); print(r); assert r.ok"
```

Both published ports bind to `127.0.0.1`. Never print a resolved Compose
configuration containing real credentials. An existing database volume keeps
its original user and password; editing `.env` later does not rotate them.

## Schema initialisation

The `db` service mounts `db/init/` read-only into `/docker-entrypoint-initdb.d`,
so a fresh volume runs `001_doctors_slots.sql`, `002_conversations.sql` and
`003_bookings.sql` in order with no manual SQL (see
[database.md](database.md) for adding a file to an existing volume). Seed data
(#29) and committed clinic documents and sample messages (#42) are not on `main`
yet; once they land, their files join this initialisation path and the image
build context. Until then a fresh clone starts with the schema and no records.

## Container health, failure and recovery

The API health check calls `/health` every 10 seconds with a 4-second HTTP
timeout; Docker allows 5 seconds per check and marks the container unhealthy
after three failures following a 10-second start period. HTTP 503 fails the
check. Health reports API and database reachability only, not model or workflow
readiness. If you raise the database timeouts, raise the check limits with them.

Run the outage exercise only against a disposable Compose project (`-p`, its own
env file and free host ports):

```sh
docker compose stop db
curl -i http://127.0.0.1:8000/health      # 503, database unreachable
curl --fail http://127.0.0.1:8000/openapi.json   # still 200
docker compose ps                         # api becomes unhealthy after ~30 s
docker compose start db
curl --fail http://127.0.0.1:8000/health  # 200 again, same api container
```

An unhealthy status does not restart the container; `restart: unless-stopped`
covers crashes, not failed checks. `docker compose down` keeps the named volume;
add `-v` only to delete that project's database.

## Verification record (2026-11-05)

Built from the committed branch with Docker 29.9.1 and Compose v5 under the
isolated project `clinic-issue25`, an env file with synthetic credentials, fake
model mode, an empty key, host ports 18025 and 55451, and a host `DATABASE_URL`
deliberately pointing at an unusable address.

| Check | Observed result |
| --- | --- |
| `config --quiet` and `up --build -d --wait` | Passed; both services healthy. Image built from source on Python 3.12.16 with uv 0.12.23 (26 locked runtime packages); PostgreSQL 17.6. |
| Host `GET /openapi.json` and `GET /health` | HTTP 200; OpenAPI lists `/health`; health reported `database: reachable`. |
| `probe_database(get_settings().database)` inside the API | `ProbeResult(ok=True, error=None)`; parsed host `db`; fake backend; no key. |
| Image isolation | Runs as UID 10001 (`app`); no `/app/.env`, `/app/.git` or `/app/tests`. |
| Fresh-volume schema | `doctors`, `slots`, `conversations`, `bookings` and `bookings_one_active_per_slot` created by `db/init/` without manual SQL. |
| One-off API with malformed synthetic `DATABASE_URL` | Exit 1 before serving with `Configuration error: DATABASE_URL must be a PostgreSQL URL ...`; the synthetic value was not printed. |
| `stop db` | `/health` 503 with `status: unavailable`, `database: unreachable`; `/openapi.json` still 200; Docker reported the API unhealthy after 32 seconds. |
| `start db` and wait | `/health` 200 immediately; the API container returned to healthy on its next check without being recreated (same container ID). |
| Application checks on the branch | Ruff lint and format and strict Mypy passed; 299 tests passed with real PostgreSQL enabled and no skips, 97.97% application coverage, no model key. |

The disposable project's containers, network, image and volume were removed
afterwards (`down -v --rmi local`). Independent fresh-clone verification is #79.
No VM deployment is claimed.

## Learning question

*Why must application code inside Compose use the database service hostname
instead of localhost?* Each container has its own network namespace, so
`localhost` inside the API container is the API container, where nothing listens
on 5432. Compose registers every service name in the project network's DNS, so
`db` resolves to the database container's address, and the published host port is
irrelevant because the containers talk directly on the internal port.
